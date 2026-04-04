from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)

# เปลี่ยน URL นี้ตาม FHIR Server จริงของคุณ
FHIR_BASE_URL = "http://localhost:8080/fhir"


def build_patient_resource(data):
    patient = {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "http://hospitalA.com/hn",
                "value": data.get("hn", "").strip()
            }
        ],
        "name": [
            {
                "family": data.get("lastName", "").strip(),
                "given": [data.get("firstName", "").strip()]
            }
        ],
        "gender": data.get("gender", "").strip().lower(),
        "birthDate": data.get("birthDate", "").strip(),
        "telecom": [],
        "address": []
    }

    citizen_id = data.get("citizenId", "").strip()
    if citizen_id:
        patient["identifier"].append({
            "system": "http://hl7.org/fhir/sid/id-th-citizenid",
            "value": citizen_id
        })

    phone = data.get("phone", "").strip()
    if phone:
        patient["telecom"].append({
            "system": "phone",
            "value": phone,
            "use": "mobile"
        })

    address = data.get("address", "").strip()
    if address:
        patient["address"].append({
            "text": address
        })

    return patient


def map_service_type_to_class(service_type):
    mapping = {
        "opd": {"code": "AMB", "display": "ambulatory"},
        "ipd": {"code": "IMP", "display": "inpatient encounter"},
        "emergency": {"code": "EMER", "display": "emergency"},
        "followup": {"code": "AMB", "display": "ambulatory"}
    }
    return mapping.get(service_type, {"code": "AMB", "display": "ambulatory"})


def build_encounter_resource(data, patient_ref):
    service_type = data.get("serviceType", "").strip()
    encounter_class = map_service_type_to_class(service_type)

    encounter = {
        "resourceType": "Encounter",
        "status": data.get("encounterStatus", "finished").strip() or "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": encounter_class["code"],
            "display": encounter_class["display"]
        },
        "subject": {
            "reference": patient_ref
        },
        "period": {
            "start": data.get("visitDateTime", "").strip()
        }
    }

    department = data.get("department", "").strip()
    if department:
        encounter["serviceType"] = {
            "text": department
        }

    doctor = data.get("doctor", "").strip()
    if doctor:
        encounter["participant"] = [
            {
                "individual": {
                    "display": doctor
                }
            }
        ]

    return encounter


def build_medication_request_resource(data, patient_ref, encounter_ref):
    medication_name = data.get("medicineName", "").strip()
    dosage = data.get("dosage", "").strip()
    instruction = data.get("instruction", "").strip()
    frequency = data.get("frequency", "").strip()
    quantity = data.get("quantity", "")
    prescription_date = data.get("prescriptionDate", "").strip()
    prescribing_doctor = data.get("prescribingDoctor", "").strip()

    dosage_text_parts = [instruction]
    if dosage:
        dosage_text_parts.append(f"ขนาดยา {dosage}")
    if frequency:
        dosage_text_parts.append(f"ความถี่ {frequency}")

    dosage_text = " | ".join([x for x in dosage_text_parts if x])

    med_request = {
        "resourceType": "MedicationRequest",
        "status": "active",
        "intent": "order",
        "subject": {
            "reference": patient_ref
        },
        "encounter": {
            "reference": encounter_ref
        },
        "medicationCodeableConcept": {
            "text": medication_name
        },
        "authoredOn": prescription_date or datetime.now().date().isoformat(),
        "dosageInstruction": [
            {
                "text": dosage_text or "Use as directed"
            }
        ]
    }

    if quantity not in [None, ""]:
        try:
            med_request["dispenseRequest"] = {
                "quantity": {
                    "value": float(quantity),
                    "unit": "unit"
                }
            }
        except ValueError:
            pass

    if prescribing_doctor:
        med_request["requester"] = {
            "display": prescribing_doctor
        }

    return med_request


def create_fhir_resource(resource_type, resource_data):
    url = f"{FHIR_BASE_URL}/{resource_type}"
    headers = {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json"
    }

    response = requests.post(url, json=resource_data, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json()


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "message": "HIS-A backend is running"
    })


@app.route("/api/preview-fhir", methods=["POST"])
def preview_fhir():
    try:
        data = request.get_json()
        active_tab = data.get("activeTab", "patientTab")

        patient_ref = f"Patient/{data.get('hn', 'TEMP-HN')}"
        encounter_ref = "Encounter/TEMP-ENC"

        if active_tab == "patientTab":
            patient_resource = build_patient_resource(data)
            return jsonify({
                "success": True,
                "resourceType": "Patient",
                "resource": patient_resource
            }), 200

        elif active_tab == "encounterTab":
            encounter_resource = build_encounter_resource(data, patient_ref)
            return jsonify({
                "success": True,
                "resourceType": "Encounter",
                "resource": encounter_resource
            }), 200

        elif active_tab == "medicationTab":
            medication_resource = build_medication_request_resource(data, patient_ref, encounter_ref)
            return jsonify({
                "success": True,
                "resourceType": "MedicationRequest",
                "resource": medication_resource
            }), 200

        else:
            return jsonify({
                "success": False,
                "error": "Unknown active tab"
            }), 400

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/send-fhir", methods=["POST"])
def send_fhir():
    try:
        data = request.get_json()

        patient_resource = build_patient_resource(data)
        patient_response = create_fhir_resource("Patient", patient_resource)
        patient_id = patient_response.get("id")
        patient_ref = f"Patient/{patient_id}"

        encounter_resource = build_encounter_resource(data, patient_ref)
        encounter_response = create_fhir_resource("Encounter", encounter_resource)
        encounter_id = encounter_response.get("id")
        encounter_ref = f"Encounter/{encounter_id}"

        medication_resource = build_medication_request_resource(data, patient_ref, encounter_ref)
        medication_response = create_fhir_resource("MedicationRequest", medication_resource)

        return jsonify({
            "success": True,
            "message": "FHIR resources sent successfully",
            "sentResources": {
                "patient": patient_resource,
                "encounter": encounter_resource,
                "medicationRequest": medication_resource
            },
            "serverResponses": {
                "patient": patient_response,
                "encounter": encounter_response,
                "medicationRequest": medication_response
            }
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "error": "Failed to connect to FHIR Server",
            "details": str(e)
        }), 500

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)