
## โครงสร้างโปรเจคภาพรวม

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
│
└── fhir-server/
    ├── config/
    └── README.md
```


ฟอร์มกรอกข้อมูล 3 ส่วน
Backend รับข้อมูล
ฟังก์ชันแปลงข้อมูลเป็น FHIR
เชื่อมต่อ HAPI FHIR Server
ทดสอบ POST/GET ได้จริง