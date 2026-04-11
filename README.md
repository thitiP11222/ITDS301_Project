
## โครงสร้างโปรเจคภาพรวม
https://docs.google.com/document/d/1uIcz8np1T9Hv8bNEc42iKe_zlDy1G0ZIj9NBFJd_yHI/edit?usp=sharing
```text
ITDS301_Project/
│
├── docker-compose.yml
│
├── his-a/
│   ├── frontend/
│   ├── backend/
│   ├── Dockerfile
│   └── README.md
│
├── his-b/
│   ├── frontend/
│   ├── backend/
│   ├── Dockerfile
│   └── README.md

```
เช็กใน HAPI:
http://localhost:8080/fhir/Patient

---

# 🚀 HIS-HIS Dev Cheatsheet

---

## 🐳 Docker Commands

### Start / Build

```bash
docker compose up --build
```

### Run Background

```bash
docker compose up -d
```

### Stop

```bash
docker compose down
```

### Restart Service

```bash
docker compose restart his-a
```

---

## 📊 Logs

```bash
docker compose logs -f his-a
docker compose logs -f fhir-server
```

---

## 📦 Containers

```bash
docker ps
```

---

## 🌐 Important URLs

```bash
# HIS-A (Frontend + Backend)
http://localhost:5001/

# Health Check
http://localhost:5001/health

# HAPI FHIR
http://localhost:8080/fhir/metadata

# View Patients
http://localhost:8080/fhir/Patient
```

---

## 📂 Important Files

```bash
his-a/backend/app.py
his-a/frontend/form.html
his-a/backend/requirements.txt
docker-compose.yml
```

---

## 🔁 Dev Workflow

```bash
# 1. Start system
docker compose up -d

# 2. Check logs
docker compose logs -f his-a

# 3. Test API
http://localhost:5001/health

# 4. Test UI
http://localhost:5001/
```

---

## 🛠 Common Fixes

### Backend not updated

```bash
docker compose restart his-a
```

### Dependency change

```bash
docker compose down
docker compose up --build
```

### Check FHIR ready

```bash
http://localhost:8080/fhir/metadata
```

---

## 🔗 FHIR Flow (สำคัญ)

```text
Patient → Encounter → MedicationRequest
```

---

## ⚠️ Debug Tips

```bash
# Request เข้า backend ไหม
docker compose logs -f his-a

# ถ้า 400 = data ไม่ถูก
# ถ้า 500 = backend error
# ถ้า connect ไม่ได้ = URL / port ผิด
```

---

## 🧪 Test API

```bash
POST http://localhost:5001/patients
GET  http://localhost:5001/patients/{id}
GET  http://localhost:5001/patients/search?hn=HN001
```

---

## 💡 Key Rule

```text
Frontend → Flask → HAPI FHIR
```

---