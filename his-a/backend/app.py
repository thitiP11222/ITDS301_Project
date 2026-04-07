from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

def build_patient_resource(data):
    return {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "http://hospital.local/hn",
                "value": data.get("hn", "")
            },
            {
                "system": "http://hospital.local/citizen-id",
                "value": data.get("citizenId", "")
            }
        ],
        "name": [
            {
                "family": data.get("lastName", ""),
                "given": [data.get("firstName", "")]
            }
        ],
        "gender": data.get("gender", "").lower(),
        "birthDate": data.get("birthDate", ""),
        "telecom": [
            {
                "system": "phone",
                "value": data.get("phone", "")
            }
        ],
        "address": [
            {
                "text": data.get("address", "")
            }
        ]
    }

def build_encounter_resource(data):
    service_type = data.get("serviceType", "")
    class_code_map = {
        "opd": "AMB",
        "ipd": "IMP",
        "emergency": "EMER",
        "followup": "AMB"
    }

    return {
        "resourceType": "Encounter",
        "status": data.get("encounterStatus", "planned"),
        "class": {
            "code": class_code_map.get(service_type, "AMB")
        },
        "period": {
            "start": data.get("visitDateTime", "")
        },
        "serviceType": {
            "text": service_type
        },
        "participant": [
            {
                "individual": {
                    "display": data.get("doctor", "")
                }
            }
        ],
        "serviceProvider": {
            "display": data.get("department", "")
        }
    }

def build_medication_request_resource(data):
    return {
        "resourceType": "MedicationRequest",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "text": data.get("medicineName", "")
        },
        "dosageInstruction": [
            {
                "text": data.get("instruction", ""),
                "patientInstruction": data.get("frequency", ""),
                "additionalInstruction": [
                    {
                        "text": data.get("dosage", "")
                    }
                ]
            }
        ],
        "dispenseRequest": {
            "quantity": {
                "value": int(data.get("quantity", 0) or 0)
            }
        },
        "authoredOn": data.get("prescriptionDate", ""),
        "requester": {
            "display": data.get("prescribingDoctor", "")
        }
    }

@app.route("/submit-all", methods=["POST"])
def submit_all():
    body = request.get_json()

    patient_data = body.get("patient", {})
    encounter_data = body.get("encounter", {})
    medication_data = body.get("medication", {})

    if not patient_data.get("firstName") or not patient_data.get("lastName"):
        return jsonify({"message": "กรุณากรอกชื่อและนามสกุลผู้ป่วย"}), 400

    patient_resource = build_patient_resource(patient_data)
    encounter_resource = build_encounter_resource(encounter_data)
    medication_resource = build_medication_request_resource(medication_data)

    return jsonify({
        "message": "received successfully",
        "patient": patient_resource,
        "encounter": encounter_resource,
        "medicationRequest": medication_resource
    }), 200

if __name__ == "__main__":
    app.run(debug=True)