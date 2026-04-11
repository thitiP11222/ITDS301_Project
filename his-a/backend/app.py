import os
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

FHIR_SERVER_URL = os.getenv("FHIR_SERVER_URL", "http://fhir-server:8080/fhir").rstrip("/")

FHIR_HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json"
}


def build_patient_resource(data):
    gender = (data.get("gender") or "").strip().lower()

    # map ค่าที่ frontend อาจส่งมา
    gender_map = {
        "male": "male",
        "female": "female",
        "other": "other",
        "unknown": "unknown",
        "m": "male",
        "f": "female",
        "ชาย": "male",
        "หญิง": "female"
    }

    patient = {
        "resourceType": "Patient",
        "identifier": [],
        "name": [
            {
                "family": data.get("lastName", "").strip(),
                "given": [data.get("firstName", "").strip()]
            }
        ],
        "gender": gender_map.get(gender, "unknown"),
        "birthDate": data.get("birthDate", "").strip(),
        "telecom": [],
        "address": []
    }

    hn = data.get("hn", "").strip()
    citizen_id = data.get("citizenId", "").strip()
    phone = data.get("phone", "").strip()
    address = data.get("address", "").strip()

    if hn:
        patient["identifier"].append({
            "system": "http://hospital.local/hn",
            "value": hn
        })

    if citizen_id:
        patient["identifier"].append({
            "system": "http://hospital.local/citizen-id",
            "value": citizen_id
        })

    if phone:
        patient["telecom"].append({
            "system": "phone",
            "value": phone
        })

    if address:
        patient["address"].append({
            "text": address
        })

    # ลบ key ว่าง ๆ เพื่อให้ payload สะอาดขึ้น
    if not patient["identifier"]:
        patient.pop("identifier")
    if not patient["telecom"]:
        patient.pop("telecom")
    if not patient["address"]:
        patient.pop("address")
    if not patient["birthDate"]:
        patient.pop("birthDate")

    return patient

@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "form.html")
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "HIS-A Flask backend is running",
        "fhir_server_url": FHIR_SERVER_URL
    })


@app.route("/health", methods=["GET"])
def health():
    try:
        url = f"{FHIR_SERVER_URL}/metadata"
        response = requests.get(url, headers={"Accept": "application/fhir+json"}, timeout=15)
        return jsonify({
            "status": "ok" if response.ok else "error",
            "fhir_status_code": response.status_code,
            "fhir_server_url": FHIR_SERVER_URL
        }), 200 if response.ok else 502
    except requests.RequestException as e:
        return jsonify({
            "status": "error",
            "message": "Cannot connect to FHIR server",
            "detail": str(e)
        }), 502


@app.route("/patients", methods=["POST"])
def add_patient():
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"message": "Invalid JSON body"}), 400

    if not body:
        return jsonify({"message": "Request body is required"}), 400

    first_name = (body.get("firstName") or "").strip()
    last_name = (body.get("lastName") or "").strip()

    if not first_name or not last_name:
        return jsonify({"message": "กรุณากรอก firstName และ lastName"}), 400

    patient_resource = build_patient_resource(body)

    try:
        response = requests.post(
            f"{FHIR_SERVER_URL}/Patient",
            json=patient_resource,
            headers=FHIR_HEADERS,
            timeout=20
        )

        # HAPI มักตอบ resource ที่สร้างกลับมา หรืออย่างน้อยมี Location header / id
        response_json = {}
        try:
            response_json = response.json()
        except ValueError:
            response_json = {"raw_response": response.text}

        if response.status_code not in (200, 201):
            return jsonify({
                "message": "Failed to create Patient in FHIR server",
                "status_code": response.status_code,
                "fhir_response": response_json,
                "sent_resource": patient_resource
            }), 502

        patient_id = response_json.get("id")
        location = response.headers.get("Location")

        return jsonify({
            "message": "Patient created successfully in HAPI FHIR",
            "patientId": patient_id,
            "location": location,
            "patient": response_json,
            "sent_resource": patient_resource
        }), 201

    except requests.RequestException as e:
        return jsonify({
            "message": "Cannot connect to FHIR server",
            "detail": str(e)
        }), 502


@app.route("/patients/<patient_id>", methods=["GET"])
def get_patient_by_id(patient_id):
    try:
        response = requests.get(
            f"{FHIR_SERVER_URL}/Patient/{patient_id}",
            headers={"Accept": "application/fhir+json"},
            timeout=20
        )

        response_json = {}
        try:
            response_json = response.json()
        except ValueError:
            response_json = {"raw_response": response.text}

        if response.status_code == 404:
            return jsonify({
                "message": "Patient not found",
                "patientId": patient_id,
                "fhir_response": response_json
            }), 404

        if not response.ok:
            return jsonify({
                "message": "Failed to fetch Patient from FHIR server",
                "status_code": response.status_code,
                "fhir_response": response_json
            }), 502

        return jsonify(response_json), 200

    except requests.RequestException as e:
        return jsonify({
            "message": "Cannot connect to FHIR server",
            "detail": str(e)
        }), 502


@app.route("/patients/search", methods=["GET"])
def search_patient():
    """
    ตัวอย่าง:
    /patients/search?hn=HN001
    /patients/search?citizenId=1234567890123
    """
    hn = (request.args.get("hn") or "").strip()
    citizen_id = (request.args.get("citizenId") or "").strip()

    if not hn and not citizen_id:
        return jsonify({
            "message": "Please provide hn or citizenId"
        }), 400

    try:
        if hn:
            search_url = f"{FHIR_SERVER_URL}/Patient"
            params = {"identifier": f"http://hospital.local/hn|{hn}"}
        else:
            search_url = f"{FHIR_SERVER_URL}/Patient"
            params = {"identifier": f"http://hospital.local/citizen-id|{citizen_id}"}

        response = requests.get(
            search_url,
            params=params,
            headers={"Accept": "application/fhir+json"},
            timeout=20
        )

        response_json = {}
        try:
            response_json = response.json()
        except ValueError:
            response_json = {"raw_response": response.text}

        if not response.ok:
            return jsonify({
                "message": "Failed to search Patient from FHIR server",
                "status_code": response.status_code,
                "fhir_response": response_json
            }), 502

        entries = response_json.get("entry", [])
        patients = [entry.get("resource", {}) for entry in entries]

        return jsonify({
            "total": response_json.get("total", len(patients)),
            "patients": patients,
            "bundle": response_json
        }), 200

    except requests.RequestException as e:
        return jsonify({
            "message": "Cannot connect to FHIR server",
            "detail": str(e)
        }), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)