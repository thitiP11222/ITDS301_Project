
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
