import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

FHIR_SERVER_URL = os.getenv("FHIR_SERVER_URL", "http://fhir-server:8080/fhir").rstrip("/")
HOSPITAL_A_URL = os.getenv("HOSPITAL_A_URL", "http://his-a:5000").rstrip("/")

FHIR_TIMEOUT = 20


# =========================
# Utility
# =========================
def json_response(data: Any, status: int = 200):
    return jsonify(data), status


def build_fhir_url(resource_type: str = "", resource_id: str = "") -> str:
    url = FHIR_SERVER_URL
    if resource_type:
        url += f"/{resource_type}"
    if resource_id:
        url += f"/{resource_id}"
    return url


def safe_get(d: Dict[str, Any], key: str, default: str = "") -> str:
    value = d.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def fhir_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    }


def parse_fhir_response(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def extract_hn_from_patient(patient: Dict[str, Any]) -> str:
    for ident in patient.get("identifier", []):
        system = ident.get("system", "")
        if "hn" in system.lower():
            return ident.get("value", "")
    return ""


def extract_patient_name(patient: Dict[str, Any]) -> str:
    name_list = patient.get("name", [])
    if not name_list:
        return ""
    name = name_list[0]
    given = " ".join(name.get("given", []))
    family = name.get("family", "")
    return f"{given} {family}".strip()


def normalize_patient_summary(patient: Dict[str, Any]) -> Dict[str, Any]:
    telecom = patient.get("telecom", [])
    address = patient.get("address", [])

    phone = ""
    for t in telecom:
        if t.get("system") == "phone":
            phone = t.get("value", "")
            break

    return {
        "id": patient.get("id"),
        "hn": extract_hn_from_patient(patient),
        "citizenId": next(
            (
                i.get("value", "")
                for i in patient.get("identifier", [])
                if "citizen-id" in i.get("system", "").lower()
            ),
            "",
        ),
        "firstName": (
            patient.get("name", [{}])[0].get("given", [""])[0]
            if patient.get("name")
            else ""
        ),
        "lastName": patient.get("name", [{}])[0].get("family", "") if patient.get("name") else "",
        "fullName": extract_patient_name(patient),
        "gender": patient.get("gender", ""),
        "birthDate": patient.get("birthDate", ""),
        "phone": phone,
        "address": address[0].get("text", "") if address else "",
        "resource": patient,
    }


def find_patient_by_hn(hn: str) -> Optional[Dict[str, Any]]:
    if not hn:
        return None

    params = {
        "identifier": f"http://hospital-b.local/hn|{hn}",
        "_count": 1,
    }

    response = requests.get(
        build_fhir_url("Patient"),
        params=params,
        headers=fhir_headers(),
        timeout=FHIR_TIMEOUT,
    )
    data = parse_fhir_response(response)

    if not response.ok:
        raise RuntimeError(data.get("issue", data))

    entries = data.get("entry", [])
    if not entries:
        return None

    return entries[0].get("resource")


def get_patient_reference_by_hn(hn: str) -> Tuple[str, Dict[str, Any]]:
    patient = find_patient_by_hn(hn)
    if not patient:
        raise ValueError(f"Patient with HN '{hn}' not found")

    patient_id = patient.get("id")
    if not patient_id:
        raise ValueError("Patient resource has no id")

    return patient_id, patient


# =========================
# FHIR Builders
# =========================
def build_patient_resource(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "http://hospital-b.local/hn",
                "value": safe_get(data, "hn"),
            },
            {
                "system": "http://hospital-b.local/citizen-id",
                "value": safe_get(data, "citizenId"),
            },
        ],
        "name": [
            {
                "family": safe_get(data, "lastName"),
                "given": [safe_get(data, "firstName")],
            }
        ],
        "gender": safe_get(data, "gender").lower(),
        "birthDate": safe_get(data, "birthDate"),
        "telecom": [
            {
                "system": "phone",
                "value": safe_get(data, "phone"),
            }
        ],
        "address": [
            {
                "text": safe_get(data, "address"),
            }
        ],
    }


def format_fhir_datetime(dt_str: str) -> str:
    """
    แปลง datetime-local จาก frontend
    เช่น 2026-04-11T10:30 -> 2026-04-11T10:30:00+07:00
    """
    dt_str = (dt_str or "").strip()
    if not dt_str:
        return ""

    if len(dt_str) == 16:  # YYYY-MM-DDTHH:MM
        return dt_str + ":00+07:00"

    if len(dt_str) == 19:  # YYYY-MM-DDTHH:MM:SS
        return dt_str + "+07:00"

    return dt_str


def build_encounter_resource(data: Dict[str, Any], patient_id: str, patient: Dict[str, Any]) -> Dict[str, Any]:
    doctor = safe_get(data, "doctor")
    department = safe_get(data, "department")
    status = safe_get(data, "encounterStatus", "finished") or "finished"
    visit_start = format_fhir_datetime(safe_get(data, "visitDateTime"))

    return {
        "resourceType": "Encounter",
        "status": status,
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory",
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
            "display": extract_patient_name(patient),
        },
        "period": {
            "start": visit_start,
        },
        "serviceType": {
            "text": safe_get(data, "serviceType"),
        },
        "serviceProvider": {
            "display": "Hospital B",
        },
        "participant": [
            {
                "individual": {
                    "display": doctor,
                }
            }
        ] if doctor else [],
        "location": [
            {
                "location": {
                    "display": department,
                }
            }
        ] if department else [],
    }


def build_medication_request_resource(
    data: Dict[str, Any],
    patient_id: str,
    patient: Dict[str, Any],
) -> Dict[str, Any]:
    quantity_value = 0
    try:
        quantity_value = int(float(data.get("quantity", 0) or 0))
    except Exception:
        quantity_value = 0

    instruction_text = safe_get(data, "instruction")
    frequency = safe_get(data, "frequency")
    dosage = safe_get(data, "dosage")

    return {
        "resourceType": "MedicationRequest",
        "status": "active",
        "intent": "order",
        "subject": {
            "reference": f"Patient/{patient_id}",
            "display": extract_patient_name(patient),
        },
        "medicationCodeableConcept": {
            "text": safe_get(data, "medicineName"),
        },
        "authoredOn": safe_get(data, "prescriptionDate"),
        "requester": {
            "display": safe_get(data, "prescribingDoctor"),
        },
        "dosageInstruction": [
            {
                "text": f"{dosage} | {frequency}".strip(" |"),
                "patientInstruction": instruction_text,
                "additionalInstruction": [
                    {
                        "text": instruction_text
                    }
                ] if instruction_text else [],
            }
        ],
        "dispenseRequest": {
            "quantity": {
                "value": quantity_value
            }
        },
        "note": [
            {
                "text": "Prescribed at Hospital B"
            }
        ],
    }


# =========================
# Static Pages
# =========================
@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/form")
def form_page():
    return send_from_directory(app.static_folder, "form.html")


@app.route("/view-patient")
def view_patient_page():
    return send_from_directory(app.static_folder, "view-patient.html")


@app.route("/view-encounter")
def view_encounter_page():
    return send_from_directory(app.static_folder, "view-encounter.html")


@app.route("/view-medication")
def view_medication_page():
    return send_from_directory(app.static_folder, "view-medication.html")


# =========================
# Health Check
# =========================
@app.route("/health")
def health():
    return json_response(
        {
            "message": "Hospital B backend is running",
            "fhir_server_url": FHIR_SERVER_URL,
            "hospital_a_url": HOSPITAL_A_URL,
        }
    )


@app.route("/fhir-health")
def fhir_health():
    try:
        response = requests.get(
            build_fhir_url("metadata"),
            headers={"Accept": "application/fhir+json"},
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)
        return json_response(
            {
                "ok": response.ok,
                "status_code": response.status_code,
                "fhir_server_url": FHIR_SERVER_URL,
                "response": data,
            },
            200 if response.ok else 502,
        )
    except Exception as e:
        return json_response(
            {
                "ok": False,
                "message": "Cannot connect to FHIR server",
                "detail": str(e),
            },
            500,
        )


# =========================
# Patient APIs
# =========================
@app.route("/patients", methods=["POST"])
def create_patient():
    data = request.get_json(silent=True) or {}

    hn = safe_get(data, "hn")
    first_name = safe_get(data, "firstName")
    last_name = safe_get(data, "lastName")

    if not hn:
        return json_response({"message": "HN is required"}, 400)
    if not first_name or not last_name:
        return json_response({"message": "firstName and lastName are required"}, 400)

    try:
        existing = find_patient_by_hn(hn)
        if existing:
            return json_response(
                {
                    "message": "Patient with this HN already exists",
                    "patient": normalize_patient_summary(existing),
                },
                409,
            )

        patient_resource = build_patient_resource(data)
        response = requests.post(
            build_fhir_url("Patient"),
            headers=fhir_headers(),
            json=patient_resource,
            timeout=FHIR_TIMEOUT,
        )
        result = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to create Patient in FHIR server",
                    "response": result,
                },
                response.status_code,
            )

        created_id = result.get("id")
        created_resource = result

        if created_id:
            get_resp = requests.get(
                build_fhir_url("Patient", created_id),
                headers=fhir_headers(),
                timeout=FHIR_TIMEOUT,
            )
            if get_resp.ok:
                created_resource = parse_fhir_response(get_resp)

        return json_response(
            {
                "message": "Patient created successfully in Hospital B",
                "patient": normalize_patient_summary(created_resource),
                "resource": created_resource,
            },
            201,
        )
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)


@app.route("/patients/search", methods=["GET"])
def search_patient():
    hn = request.args.get("hn", "").strip()

    if not hn:
        return json_response({"message": "hn query parameter is required"}, 400)

    try:
        patient = find_patient_by_hn(hn)
        if not patient:
            return json_response({"patients": []}, 200)

        return json_response({"patients": [normalize_patient_summary(patient)]}, 200)
    except Exception as e:
        return json_response({"message": "Search failed", "detail": str(e)}, 500)


@app.route("/patients", methods=["GET"])
def list_patients():
    try:
        response = requests.get(
            build_fhir_url("Patient"),
            params={"_count": 50},
            headers=fhir_headers(),
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if not response.ok:
            return json_response({"message": "Failed to fetch patients", "response": data}, response.status_code)

        patients = [
            normalize_patient_summary(entry.get("resource", {}))
            for entry in data.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Patient"
        ]

        return json_response({"count": len(patients), "patients": patients})
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)
    
@app.route("/patients/<patient_id>", methods=["GET"])
def get_patient_by_id(patient_id):
    try:
        response = requests.get(
            build_fhir_url("Patient", patient_id),
            headers=fhir_headers(),
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if response.status_code == 404:
            return json_response(
                {
                    "message": "Patient not found",
                    "patientId": patient_id,
                    "response": data,
                },
                404,
            )

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to fetch patient",
                    "response": data,
                },
                response.status_code,
            )

        return json_response(data, 200)
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)


@app.route("/patients/<patient_id>", methods=["PUT"])
def update_patient(patient_id):
    try:
        body = request.get_json(silent=True) or {}

        if not safe_get(body, "firstName") or not safe_get(body, "lastName"):
            return json_response({"message": "firstName and lastName are required"}, 400)

        patient_resource = build_patient_resource(body)
        patient_resource["id"] = patient_id

        response = requests.put(
            build_fhir_url("Patient", patient_id),
            headers=fhir_headers(),
            json=patient_resource,
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to update patient",
                    "response": data,
                },
                response.status_code,
            )

        return json_response(
            {
                "message": "Patient updated successfully",
                "patient": data,
            },
            200,
        )
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)


@app.route("/patients/<patient_id>", methods=["DELETE"])
def delete_patient(patient_id):
    try:
        response = requests.delete(
            build_fhir_url("Patient", patient_id),
            headers=fhir_headers(),
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if response.status_code in [200, 204]:
            return json_response({"message": "ลบข้อมูลสำเร็จ"}, 200)

        return json_response(
            {
                "message": "ลบข้อมูลไม่สำเร็จ",
                "response": data,
            },
            response.status_code,
        )
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)


# =========================
# Encounter APIs
# =========================
@app.route("/encounters", methods=["POST"])
def create_encounter():
    data = request.get_json(silent=True) or {}
    hn = safe_get(data, "hn")

    if not hn:
        return json_response({"message": "HN is required"}, 400)

    try:
        patient_id, patient = get_patient_reference_by_hn(hn)
        encounter_resource = build_encounter_resource(data, patient_id, patient)

        response = requests.post(
            build_fhir_url("Encounter"),
            headers=fhir_headers(),
            json=encounter_resource,
            timeout=FHIR_TIMEOUT,
        )
        result = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to create Encounter in FHIR server",
                    "response": result,
                },
                response.status_code,
            )

        return json_response(
            {
                "message": "Encounter created successfully in Hospital B",
                "resource": result,
            },
            201,
        )
    except ValueError as e:
        return json_response({"message": str(e)}, 404)
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)


@app.route("/encounters", methods=["GET"])
def list_encounters():
    try:
        response = requests.get(
            build_fhir_url("Encounter"),
            params={"_count": 50},
            headers=fhir_headers(),
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if not response.ok:
            return json_response({"message": "Failed to fetch encounters", "response": data}, response.status_code)

        encounters: List[Dict[str, Any]] = []
        for entry in data.get("entry", []):
            resource = entry.get("resource", {})
            encounters.append(
                {
                    "id": resource.get("id"),
                    "status": resource.get("status"),
                    "subject": resource.get("subject", {}).get("display", ""),
                    "subjectReference": resource.get("subject", {}).get("reference", ""),
                    "serviceType": resource.get("serviceType", {}).get("text", ""),
                    "periodStart": resource.get("period", {}).get("start", ""),
                    "doctor": (
                        resource.get("participant", [{}])[0]
                        .get("individual", {})
                        .get("display", "")
                        if resource.get("participant")
                        else ""
                    ),
                    "resource": resource,
                }
            )

        return json_response({"count": len(encounters), "encounters": encounters})
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)


# =========================
# Medication APIs
# =========================
@app.route("/medications", methods=["POST"])
def create_medication():
    data = request.get_json(silent=True) or {}
    hn = safe_get(data, "hn")

    if not hn:
        return json_response({"message": "HN is required"}, 400)

    if not safe_get(data, "medicineName"):
        return json_response({"message": "medicineName is required"}, 400)

    try:
        patient_id, patient = get_patient_reference_by_hn(hn)
        medication_resource = build_medication_request_resource(data, patient_id, patient)

        response = requests.post(
            build_fhir_url("MedicationRequest"),
            headers=fhir_headers(),
            json=medication_resource,
            timeout=FHIR_TIMEOUT,
        )
        result = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to create MedicationRequest in FHIR server",
                    "response": result,
                },
                response.status_code,
            )

        return json_response(
            {
                "message": "MedicationRequest created successfully in Hospital B",
                "resource": result,
            },
            201,
        )
    except ValueError as e:
        return json_response({"message": str(e)}, 404)
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)


@app.route("/medications", methods=["GET"])
def list_medications():
    try:
        response = requests.get(
            build_fhir_url("MedicationRequest"),
            params={"_count": 50},
            headers=fhir_headers(),
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if not response.ok:
            return json_response({"message": "Failed to fetch medications", "response": data}, response.status_code)

        medications: List[Dict[str, Any]] = []
        for entry in data.get("entry", []):
            resource = entry.get("resource", {})
            dosage_list = resource.get("dosageInstruction", [])
            medications.append(
                {
                    "id": resource.get("id"),
                    "status": resource.get("status"),
                    "subject": resource.get("subject", {}).get("display", ""),
                    "medicineName": resource.get("medicationCodeableConcept", {}).get("text", ""),
                    "authoredOn": resource.get("authoredOn", ""),
                    "requester": resource.get("requester", {}).get("display", ""),
                    "dosageText": dosage_list[0].get("text", "") if dosage_list else "",
                    "instruction": dosage_list[0].get("patientInstruction", "") if dosage_list else "",
                    "quantity": resource.get("dispenseRequest", {}).get("quantity", {}).get("value", 0),
                    "resource": resource,
                }
            )

        return json_response({"count": len(medications), "medications": medications})
    except Exception as e:
        return json_response({"message": "Internal server error", "detail": str(e)}, 500)


# =========================
# Import / Exchange with Hospital A
# =========================
@app.route("/import-from-hospital-a/<hn>", methods=["POST"])
def import_from_hospital_a(hn: str):
    """
    Expected Hospital A endpoint:
    GET http://his-a:5000/exchange/patient/<hn>

    Expected JSON shape from Hospital A:
    {
      "patient": {...},
      "encounter": {...},              # optional
      "medicationRequest": {...}       # optional
    }
    """
    try:
        response = requests.get(
            f"{HOSPITAL_A_URL}/exchange/patient/{hn}",
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to fetch data from Hospital A",
                    "hospital_a_response": data,
                },
                response.status_code,
            )

        patient_payload = data.get("patient")
        encounter_payload = data.get("encounter")
        medication_payload = data.get("medicationRequest")

        if not patient_payload:
            return json_response({"message": "Hospital A did not return patient data"}, 400)

        imported: Dict[str, Any] = {
            "patient": None,
            "encounter": None,
            "medicationRequest": None,
        }

        existing_patient = find_patient_by_hn(hn)
        if existing_patient:
            imported["patient"] = {
                "message": "Patient already exists in Hospital B",
                "patient": normalize_patient_summary(existing_patient),
            }
            patient_resource = existing_patient
            patient_id = existing_patient.get("id")
        else:
            create_patient_resp = requests.post(
                build_fhir_url("Patient"),
                headers=fhir_headers(),
                json=build_patient_resource(patient_payload),
                timeout=FHIR_TIMEOUT,
            )
            created_patient = parse_fhir_response(create_patient_resp)

            if not create_patient_resp.ok:
                return json_response(
                    {
                        "message": "Failed to import patient into Hospital B",
                        "response": created_patient,
                    },
                    create_patient_resp.status_code,
                )

            patient_resource = created_patient
            patient_id = created_patient.get("id")
            imported["patient"] = {
                "message": "Patient imported successfully",
                "patient": normalize_patient_summary(patient_resource),
            }

        if not patient_id:
            return json_response({"message": "Imported patient has no id"}, 500)

        if encounter_payload:
            encounter_resource = build_encounter_resource(encounter_payload, patient_id, patient_resource)
            enc_resp = requests.post(
                build_fhir_url("Encounter"),
                headers=fhir_headers(),
                json=encounter_resource,
                timeout=FHIR_TIMEOUT,
            )
            enc_result = parse_fhir_response(enc_resp)
            imported["encounter"] = enc_result if enc_resp.ok else {
                "error": True,
                "response": enc_result,
            }

        if medication_payload:
            medication_resource = build_medication_request_resource(medication_payload, patient_id, patient_resource)
            med_resp = requests.post(
                build_fhir_url("MedicationRequest"),
                headers=fhir_headers(),
                json=medication_resource,
                timeout=FHIR_TIMEOUT,
            )
            med_result = parse_fhir_response(med_resp)
            imported["medicationRequest"] = med_result if med_resp.ok else {
                "error": True,
                "response": med_result,
            }

        return json_response(
            {
                "message": f"Import from Hospital A completed for HN {hn}",
                "hospital_a_url": HOSPITAL_A_URL,
                "imported": imported,
            },
            200,
        )
    except Exception as e:
        return json_response(
            {
                "message": "Import from Hospital A failed",
                "detail": str(e),
            },
            500,
        )


# =========================
# Optional export endpoint for Hospital B
# =========================
@app.route("/exchange/patient/<hn>", methods=["GET"])
def export_patient_package(hn: str):
    """
    Export package so Hospital A can also pull data from Hospital B.
    """
    try:
        patient = find_patient_by_hn(hn)
        if not patient:
            return json_response({"message": "Patient not found"}, 404)

        patient_id = patient.get("id")
        patient_ref = f"Patient/{patient_id}"

        encounter_resp = requests.get(
            build_fhir_url("Encounter"),
            params={"subject": patient_ref, "_count": 1},
            headers=fhir_headers(),
            timeout=FHIR_TIMEOUT,
        )
        encounter_data = parse_fhir_response(encounter_resp)

        medication_resp = requests.get(
            build_fhir_url("MedicationRequest"),
            params={"subject": patient_ref, "_count": 1},
            headers=fhir_headers(),
            timeout=FHIR_TIMEOUT,
        )
        medication_data = parse_fhir_response(medication_resp)

        encounter_resource = None
        if encounter_resp.ok and encounter_data.get("entry"):
            encounter_resource = encounter_data["entry"][0]["resource"]

        medication_resource = None
        if medication_resp.ok and medication_data.get("entry"):
            medication_resource = medication_data["entry"][0]["resource"]

        return json_response(
            {
                "sourceHospital": "Hospital B",
                "patient": normalize_patient_summary(patient)["resource"],
                "encounter": encounter_resource,
                "medicationRequest": medication_resource,
            }
        )
    except Exception as e:
        return json_response({"message": "Export failed", "detail": str(e)}, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
