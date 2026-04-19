import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flasgger import Swagger

app = Flask(__name__)
CORS(app)
app.config["SWAGGER"] = {
    "title": "HIS A API",
    "uiversion": 3,
}
Swagger(
    app,
    template={
        "info": {
            "title": "HIS A API",
            "version": "1.0.0",
            "description": "Swagger documentation for Hospital A service.",
        }
    },
)

FHIR_SERVER_URL = os.getenv("FHIR_SERVER_URL", "http://fhir-server:8080/fhir").rstrip("/")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

FHIR_TIMEOUT = 20
FHIR_HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json",
}


# =========================================
# Utility
# =========================================
def json_response(data: Any, status: int = 200):
    return jsonify(data), status


def build_fhir_url(resource_type: str = "", resource_id: str = "") -> str:
    url = FHIR_SERVER_URL
    if resource_type:
        url += f"/{resource_type}"
    if resource_id:
        url += f"/{resource_id}"
    return url


def parse_fhir_response(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def safe_get(data: Dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def extract_hn_from_patient(patient: Dict[str, Any]) -> str:
    for ident in patient.get("identifier", []):
        system = ident.get("system", "").lower()
        if "hn" in system:
            return ident.get("value", "")
    return ""


def extract_citizen_id_from_patient(patient: Dict[str, Any]) -> str:
    for ident in patient.get("identifier", []):
        system = ident.get("system", "").lower()
        if "citizen-id" in system:
            return ident.get("value", "")
    return ""


def extract_patient_name(patient: Dict[str, Any]) -> str:
    names = patient.get("name", [])
    if not names:
        return ""
    name = names[0]
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
        "citizenId": extract_citizen_id_from_patient(patient),
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

    systems_to_try = [
        "http://hospital-a.local/hn",
        "http://hospital-b.local/hn",
        "http://hospital.local/hn",
    ]

    for system in systems_to_try:
        response = requests.get(
            build_fhir_url("Patient"),
            params={
                "identifier": f"{system}|{hn}",
                "_count": 1,
            },
            headers=FHIR_HEADERS,
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if not response.ok:
            continue

        entries = data.get("entry", [])
        if entries:
            return entries[0].get("resource")

    return None

def get_patient_reference_by_hn(hn: str) -> Tuple[str, Dict[str, Any]]:
    patient = find_patient_by_hn(hn)
    if not patient:
        raise ValueError(f"Patient with HN '{hn}' not found")

    patient_id = patient.get("id")
    if not patient_id:
        raise ValueError("Patient resource has no id")

    return patient_id, patient


# =========================================
# FHIR Builders
# =========================================
def build_patient_resource(data: Dict[str, Any]) -> Dict[str, Any]:
    gender = safe_get(data, "gender").lower()

    gender_map = {
        "male": "male",
        "female": "female",
        "other": "other",
        "unknown": "unknown",
        "m": "male",
        "f": "female",
        "ชาย": "male",
        "หญิง": "female",
    }

    patient = {
        "resourceType": "Patient",
        "identifier": [],
        "name": [
            {
                "family": safe_get(data, "lastName"),
                "given": [safe_get(data, "firstName")],
            }
        ],
        "gender": gender_map.get(gender, "unknown"),
        "birthDate": safe_get(data, "birthDate"),
        "telecom": [],
        "address": [],
    }

    hn = safe_get(data, "hn")
    citizen_id = safe_get(data, "citizenId")
    phone = safe_get(data, "phone")
    address = safe_get(data, "address")

    if hn:
        patient["identifier"].append(
            {
                "system": "http://hospital-a.local/hn",
                "value": hn,
            }
        )

    if citizen_id:
        patient["identifier"].append(
            {
                "system": "http://hospital-a.local/citizen-id",
                "value": citizen_id,
            }
        )

    if phone:
        patient["telecom"].append(
            {
                "system": "phone",
                "value": phone,
            }
        )

    if address:
        patient["address"].append(
            {
                "text": address,
            }
        )

    if not patient["identifier"]:
        patient.pop("identifier")
    if not patient["telecom"]:
        patient.pop("telecom")
    if not patient["address"]:
        patient.pop("address")
    if not patient["birthDate"]:
        patient.pop("birthDate")

    return patient


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
    service_type = safe_get(data, "serviceType")

    encounter = {
        "resourceType": "Encounter",
        "status": status,
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory"
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
            "display": extract_patient_name(patient)
        },
        "serviceProvider": {
            "display": "Hospital A"
        }
    }

    if visit_start:
        encounter["period"] = {
            "start": visit_start
        }

    if service_type:
        encounter["serviceType"] = {
            "text": service_type
        }

    if doctor:
        encounter["participant"] = [
            {
                "individual": {
                    "display": doctor
                }
            }
        ]

    if department:
        encounter["location"] = [
            {
                "location": {
                    "display": department
                }
            }
        ]

    return encounter


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
                "text": "Prescribed at Hospital A"
            }
        ],
    }


# =========================================
# Route Pages
# =========================================
@app.route("/")
def home_page():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/form")
def form_page():
    return send_from_directory(FRONTEND_DIR, "form.html")


@app.route("/view-patient")
def view_patient_page():
    return send_from_directory(FRONTEND_DIR, "view-patient.html")


@app.route("/view-encounter")
def view_encounter_page():
    return send_from_directory(FRONTEND_DIR, "view-encounter.html")


@app.route("/view-medication")
def view_medication_page():
    return send_from_directory(FRONTEND_DIR, "view-medication.html")


# =========================================
# Health
# =========================================
@app.route("/api", methods=["GET"])
def api_home():
    # คืนค่าสถานะพื้นฐานของ backend ฝั่ง HIS A
    """
    Basic API status
    ---
    tags:
      - System
    responses:
      200:
        description: Basic backend status
    """
    return json_response(
        {
            "message": "Hospital A Flask backend is running",
            "fhir_server_url": FHIR_SERVER_URL,
        }
    )


@app.route("/health", methods=["GET"])
def health():
    # ใช้ตรวจว่า HIS A เชื่อมต่อ FHIR server ได้หรือไม่
    """
    Health check
    ---
    tags:
      - System
    responses:
      200:
        description: Backend and FHIR server are reachable
      502:
        description: FHIR server is unavailable
    """
    try:
        response = requests.get(
            build_fhir_url("metadata"),
            headers={"Accept": "application/fhir+json"},
            timeout=15,
        )
        return json_response(
            {
                "status": "ok" if response.ok else "error",
                "fhir_status_code": response.status_code,
                "fhir_server_url": FHIR_SERVER_URL,
            },
            200 if response.ok else 502,
        )
    except requests.RequestException as e:
        return json_response(
            {
                "status": "error",
                "message": "Cannot connect to FHIR server",
                "detail": str(e),
            },
            502,
        )


# =========================================
# Patient APIs
# =========================================
@app.route("/patients", methods=["GET", "POST"])
def patients():
    # GET ใช้ดูรายการผู้ป่วยทั้งหมด, POST ใช้สร้างผู้ป่วยใหม่
    """
    List patients or create a patient
    ---
    tags:
      - Patients
    parameters:
      - in: body
        name: body
        required: false
        schema:
          type: object
          properties:
            hn:
              type: string
              example: TEST-A-001
            citizenId:
              type: string
              example: 1100000000001
            firstName:
              type: string
              example: Demo
            lastName:
              type: string
              example: Patient
            gender:
              type: string
              example: male
            birthDate:
              type: string
              example: 1999-01-01
            phone:
              type: string
              example: 0812345678
            address:
              type: string
              example: Bangkok
    responses:
      200:
        description: Patient list returned
      201:
        description: Patient created
      400:
        description: Missing required fields
      409:
        description: Duplicate HN
    """
    if request.method == "POST":
        body = request.get_json(force=True) or {}

        hn = safe_get(body, "hn")
        if not hn:
            return json_response({"message": "HN is required"}, 400)

        if not body.get("firstName") or not body.get("lastName"):
            return json_response({"message": "กรุณากรอกชื่อและนามสกุล"}, 400)

        try:
            existing = find_patient_by_hn(hn)
            if existing:
                return json_response(
                    {
                        "message": "Patient with this HN already exists in Hospital A",
                        "patient": normalize_patient_summary(existing),
                    },
                    409,
                )

            patient_resource = build_patient_resource(body)

            response = requests.post(
                build_fhir_url("Patient"),
                json=patient_resource,
                headers=FHIR_HEADERS,
                timeout=FHIR_TIMEOUT,
            )

            response_json = parse_fhir_response(response)

            if not response.ok:
                return json_response(
                    {
                        "message": "Failed to create Patient in FHIR server",
                        "response": response_json,
                    },
                    response.status_code,
                )

            created_id = response_json.get("id")
            created_resource = response_json

            if created_id:
                get_resp = requests.get(
                    build_fhir_url("Patient", created_id),
                    headers=FHIR_HEADERS,
                    timeout=FHIR_TIMEOUT,
                )
                if get_resp.ok:
                    created_resource = parse_fhir_response(get_resp)

            return json_response(
                {
                    "message": "Patient created successfully in Hospital A",
                    "patientId": created_resource.get("id"),
                    "patient": normalize_patient_summary(created_resource),
                    "resource": created_resource,
                },
                201,
            )

        except requests.RequestException as e:
            return json_response(
                {
                    "message": "Cannot connect to FHIR server",
                    "detail": str(e),
                },
                502,
            )
        except Exception as e:
            return json_response(
                {
                    "message": "Internal server error",
                    "detail": str(e),
                },
                500,
            )

    try:
        response = requests.get(
            build_fhir_url("Patient"),
            headers={"Accept": "application/fhir+json"},
            params={"_count": 50},
            timeout=FHIR_TIMEOUT,
        )

        data = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to fetch patients from FHIR server",
                    "fhir_response": data,
                },
                502,
            )

        patients_data = [
            normalize_patient_summary(entry.get("resource", {}))
            for entry in data.get("entry", [])
            if entry.get("resource", {}).get("resourceType") == "Patient"
        ]

        return json_response(
            {
                "total": len(patients_data),
                "patients": patients_data,
            },
            200,
        )

    except requests.RequestException as e:
        return json_response(
            {
                "message": "Cannot connect to FHIR server",
                "detail": str(e),
            },
            502,
        )


@app.route("/patients/<patient_id>", methods=["GET"])
def get_patient_by_id(patient_id):
    # ใช้ดูข้อมูลผู้ป่วยรายคนด้วย patient id
    """
    Get patient by id
    ---
    tags:
      - Patients
    parameters:
      - in: path
        name: patient_id
        type: string
        required: true
        example: 123
    responses:
      200:
        description: Patient resource returned
      404:
        description: Patient not found
    """
    try:
        response = requests.get(
            build_fhir_url("Patient", patient_id),
            headers={"Accept": "application/fhir+json"},
            timeout=FHIR_TIMEOUT,
        )

        response_json = parse_fhir_response(response)

        if response.status_code == 404:
            return json_response(
                {
                    "message": "Patient not found",
                    "patientId": patient_id,
                    "fhir_response": response_json,
                },
                404,
            )

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to fetch Patient from FHIR server",
                    "status_code": response.status_code,
                    "fhir_response": response_json,
                },
                502,
            )

        return json_response(response_json, 200)

    except requests.RequestException as e:
        return json_response(
            {
                "message": "Cannot connect to FHIR server",
                "detail": str(e),
            },
            502,
        )


@app.route("/patients/search", methods=["GET"])
def search_patient():
    # ใช้ค้นหาผู้ป่วยด้วย HN หรือเลขประชาชนจากข้อมูลใน FHIR กลาง
    """
    Search patient by HN or citizen ID
    ---
    tags:
      - Patients
    parameters:
      - in: query
        name: hn
        type: string
        required: false
        example: TEST-A-001
      - in: query
        name: citizenId
        type: string
        required: false
        example: 1100000000001
    responses:
      200:
        description: Search completed
      400:
        description: Missing hn or citizenId
    """
    hn = (request.args.get("hn") or "").strip()
    citizen_id = (request.args.get("citizenId") or "").strip()

    if not hn and not citizen_id:
        return json_response({"message": "Please provide hn or citizenId"}, 400)

    try:
        params = {}
        if hn:
            params["identifier"] = hn
        else:
            params["identifier"] = citizen_id

        response = requests.get(
            build_fhir_url("Patient"),
            params=params,
            headers={"Accept": "application/fhir+json"},
            timeout=FHIR_TIMEOUT,
        )

        response_json = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to search Patient from FHIR server",
                    "status_code": response.status_code,
                    "fhir_response": response_json,
                },
                502,
            )

        entries = response_json.get("entry", [])
        patients_found = [
            normalize_patient_summary(entry.get("resource", {}))
            for entry in entries
        ]

        return json_response(
            {
                "total": response_json.get("total", len(patients_found)),
                "patients": patients_found,
                "bundle": response_json,
            },
            200,
        )

    except requests.RequestException as e:
        return json_response(
            {
                "message": "Cannot connect to FHIR server",
                "detail": str(e),
            },
            502,
        )


@app.route("/patients/<patient_id>", methods=["DELETE"])
def delete_patient(patient_id):
    try:
        response = requests.delete(
            build_fhir_url("Patient", patient_id),
            headers={"Accept": "application/fhir+json"},
            timeout=FHIR_TIMEOUT,
        )

        print("DELETE patient_id =", patient_id)
        print("FHIR delete status =", response.status_code)
        print("FHIR delete response =", response.text)

        if response.status_code in [200, 204]:
            return json_response({"message": "ลบข้อมูลสำเร็จ"}, 200)

        return json_response(
            {
                "message": "ลบข้อมูลไม่สำเร็จ",
                "status_code": response.status_code,
                "detail": response.text,
            },
            response.status_code,
        )

    except requests.RequestException as e:
        return json_response(
            {
                "message": "Cannot connect to FHIR server",
                "detail": str(e),
                },
    response.status_code,
)


@app.route("/patients/<patient_id>", methods=["PUT"])
def update_patient(patient_id):
    try:
        body = request.get_json(force=True) or {}

        if not body.get("firstName") or not body.get("lastName"):
            return json_response({"message": "กรุณากรอกชื่อและนามสกุล"}, 400)

        patient_resource = build_patient_resource(body)
        patient_resource["id"] = patient_id

        response = requests.put(
            build_fhir_url("Patient", patient_id),
            json=patient_resource,
            headers=FHIR_HEADERS,
            timeout=FHIR_TIMEOUT,
        )

        response_json = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "แก้ไขข้อมูลไม่สำเร็จ",
                    "status_code": response.status_code,
                    "detail": response_json,
                },
                502,
            )

        return json_response(
            {
                "message": "แก้ไขข้อมูลสำเร็จ",
                "patient": response_json,
            },
            200,
        )

    except requests.RequestException as e:
        return json_response(
            {
                "message": "Cannot connect to FHIR server",
                "detail": str(e),
            },
            502,
        )


# =========================================
# Encounter APIs
# =========================================
@app.route("/encounters", methods=["POST"])
def create_encounter():
    # ใช้บันทึกข้อมูลการเข้ารับบริการของผู้ป่วย
    """
    Create encounter
    ---
    tags:
      - Encounters
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - hn
            - visitDateTime
          properties:
            hn:
              type: string
              example: TEST-A-001
            visitDateTime:
              type: string
              example: 2026-04-19T10:30
            serviceType:
              type: string
              example: opd
            department:
              type: string
              example: อายุรกรรม
            doctor:
              type: string
              example: นพ.ตัวอย่าง
            encounterStatus:
              type: string
              example: finished
    responses:
      201:
        description: Encounter created
      400:
        description: Missing required fields
      404:
        description: Patient not found
    """
    data = request.get_json(silent=True) or {}
    hn = safe_get(data, "hn")

    if not hn:
        return json_response({"message": "HN is required"}, 400)

    if not safe_get(data, "visitDateTime"):
        return json_response({"message": "visitDateTime is required"}, 400)

    try:
        patient_id, patient = get_patient_reference_by_hn(hn)
        encounter_resource = build_encounter_resource(data, patient_id, patient)

        response = requests.post(
            build_fhir_url("Encounter"),
            headers=FHIR_HEADERS,
            json=encounter_resource,
            timeout=FHIR_TIMEOUT,
        )
        result = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to create Encounter in FHIR server",
                    "sent_resource": encounter_resource,
                    "response": result,
                },
                response.status_code,
            )

        return json_response(
            {
                "message": "Encounter created successfully in Hospital A",
                "resource": result,
            },
            201,
        )

    except ValueError as e:
        return json_response({"message": str(e)}, 404)
    except Exception as e:
        return json_response(
            {
                "message": "Internal server error",
                "detail": str(e),
            },
            500,
        )
@app.route("/encounters", methods=["GET"])
def list_encounters():
    # ใช้ดูรายการข้อมูลการเข้ารับบริการทั้งหมด
    """
    List encounters
    ---
    tags:
      - Encounters
    responses:
      200:
        description: Encounter list returned
    """
    try:
        response = requests.get(
            build_fhir_url("Encounter"),
            params={"_count": 50},
            headers=FHIR_HEADERS,
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to fetch encounters",
                    "response": data,
                },
                response.status_code,
            )

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


# =========================================
# Medication APIs
# =========================================
@app.route("/medications", methods=["POST"])
def create_medication():
    # ใช้บันทึกข้อมูลใบสั่งยาของผู้ป่วย
    """
    Create medication request
    ---
    tags:
      - Medications
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - hn
            - medicineName
          properties:
            hn:
              type: string
              example: TEST-A-001
            medicineName:
              type: string
              example: Paracetamol 500 mg
            dosage:
              type: string
              example: 1 tablet
            instruction:
              type: string
              example: After meals
            frequency:
              type: string
              example: 3 times daily
            quantity:
              type: integer
              example: 10
            prescriptionDate:
              type: string
              example: 2026-04-19
            prescribingDoctor:
              type: string
              example: นพ.ตัวอย่าง
    responses:
      201:
        description: Medication request created
      400:
        description: Missing required fields
      404:
        description: Patient not found
    """
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
            headers=FHIR_HEADERS,
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
                "message": "MedicationRequest created successfully in Hospital A",
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
    # ใช้ดูรายการใบสั่งยาทั้งหมด
    """
    List medication requests
    ---
    tags:
      - Medications
    responses:
      200:
        description: Medication list returned
    """
    try:
        response = requests.get(
            build_fhir_url("MedicationRequest"),
            params={"_count": 50},
            headers=FHIR_HEADERS,
            timeout=FHIR_TIMEOUT,
        )
        data = parse_fhir_response(response)

        if not response.ok:
            return json_response(
                {
                    "message": "Failed to fetch medications",
                    "response": data,
                },
                response.status_code,
            )

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


# =========================================
# Exchange Endpoint for Hospital B
# =========================================
@app.route("/exchange/patient/<hn>", methods=["GET"])
def export_patient_package(hn: str):
    # ใช้ส่งออกข้อมูลผู้ป่วยตาม HN เพื่อให้ HIS B ดึงไป import
    """
    Export patient package for Hospital B
    ---
    tags:
      - Exchange
    parameters:
      - in: path
        name: hn
        type: string
        required: true
        example: TEST-A-001
    responses:
      200:
        description: Export package returned
      404:
        description: Patient not found in Hospital A
    """
    try:
        patient = find_patient_by_hn(hn)
        if not patient:
            return json_response({"message": "Patient not found in Hospital A"}, 404)

        patient_id = patient.get("id")
        patient_ref = f"Patient/{patient_id}"

        encounter_resp = requests.get(
            build_fhir_url("Encounter"),
            params={"subject": patient_ref, "_count": 1},
            headers=FHIR_HEADERS,
            timeout=FHIR_TIMEOUT,
        )
        encounter_data = parse_fhir_response(encounter_resp)

        medication_resp = requests.get(
            build_fhir_url("MedicationRequest"),
            params={"subject": patient_ref, "_count": 1},
            headers=FHIR_HEADERS,
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
                "sourceHospital": "Hospital A",
                "patient": normalize_patient_summary(patient)["resource"],
                "encounter": encounter_resource,
                "medicationRequest": medication_resource,
            },
            200,
        )

    except Exception as e:
        return json_response(
            {
                "message": "Export failed",
                "detail": str(e),
            },
            500,
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
