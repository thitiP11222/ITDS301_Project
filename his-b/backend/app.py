from flask import Flask, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

FHIR_SERVER_URL = os.getenv("FHIR_SERVER_URL", "http://fhir-server:8080/fhir")

@app.route("/")
def home():
    return jsonify({
        "service": "his-b",
        "message": "HIS B is running",
        "fhir_server": FHIR_SERVER_URL
    })

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "his-b"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)