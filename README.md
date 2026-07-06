# VeriTrack AI

## Enterprise Employee Compliance Verification Platform

VeriTrack AI is a backend application designed to automate employee compliance verification by comparing employee master data with monthly GETS sheets. The system provides secure user management, role-based access control, compliance analysis, AI-powered recommendations, report generation, audit logging, and analytics through RESTful APIs.

---

# Features

## Authentication & Authorization

- JWT Authentication
- Refresh Tokens
- Password Reset via Email
- Role-Based Access Control (RBAC)
- Account Lock Protection
- Rate Limiting

---

## Employee Management

- Employee Master Data Upload
- Employee Search
- Department Management
- Manager-wise Employee Mapping
- Employee Database Management

---

## Compliance Verification

- Compare Employee Database with GETS Sheet
- Missing Employee Detection
- Unknown Employee Detection
- Missing Email Detection
- Department-wise Compliance Summary
- Compliance Score Calculation
- Risk Level Classification
- AI-Based Recommendations

---

## Report Management

- Compliance Report Generation
- Report History
- Upload History
- Audit Logs

---

## Notifications

- Compliance Report Email
- Password Reset Email

---

## Background Processing

- Background GETS Processing
- Automatic Report Generation
- Asynchronous Tasks

---

## Security Features

- JWT Authentication
- Refresh Tokens
- Password Hashing (bcrypt)
- File Validation
- SHA-256 Duplicate Detection
- Secure Filename Sanitization
- Security Headers
- Trusted Host Validation
- CORS Protection

---

# Technology Stack

## Backend

- FastAPI
- SQLAlchemy
- PostgreSQL

## Authentication

- JWT
- Passlib
- bcrypt

## Data Processing

- Pandas
- OpenPyXL

## OCR & Document Processing

- PaddleOCR
- PyMuPDF
- pdfplumber

## AI

- LangChain
- LangGraph

## Reporting

- ReportLab

## Deployment

- Docker
- Docker Compose

---

# Project Structure

```text
backend/
│
├── app/
│   ├── api/
│   ├── auth/
│   ├── core/
│   ├── db/
│   ├── middleware/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── uploads/
│   └── reports/
│
├── logs/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── .env.example
```

---

# REST API Modules

- Authentication
- User Management
- Employee Management
- Upload Management
- Compliance Engine
- Dashboard
- Manager Dashboard
- HR Dashboard
- Reports
- Audit Logs
- Health Check

---

# API Features

- Secure Login
- Employee Upload
- GETS Upload
- Compliance Analysis
- AI Recommendations
- Report Generation
- Email Notifications
- Dashboard Analytics
- Audit Tracking

---

# Installation

## Clone Repository

```bash
git clone <repository-url>
cd backend
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Configure Environment

Create a `.env` file.

```env
DATABASE_URL=
SECRET_KEY=
ALGORITHM=
ACCESS_TOKEN_EXPIRE_MINUTES=

SMTP_SERVER=
SMTP_PORT=
SMTP_EMAIL=
SMTP_PASSWORD=
```

## Run Application

```bash
uvicorn app.main:app --reload
```

Swagger Documentation:

```
http://localhost:8000/docs
```

---

# Docker

Build

```bash
docker compose build
```

Run

```bash
docker compose up
```

---

# Core Functionalities

- Employee Data Import
- Monthly GETS Sheet Upload
- Compliance Verification
- Department Analysis
- AI Recommendation Generation
- Compliance Report Generation
- Email Notification
- Upload Tracking
- Report History
- Audit Logging

---

# Security

- JWT Authentication
- Refresh Token Authentication
- Password Encryption
- Role-Based Authorization
- Duplicate File Detection
- Rate Limiting
- Secure Upload Validation
- Trusted Host Middleware
- Security Headers
- CORS Protection

---

# Current Status

| Module | Status |
|---------|--------|
| Backend APIs | ✅ Complete |
| Authentication | ✅ Complete |
| RBAC | ✅ Complete |
| Employee Management | ✅ Complete |
| Upload Engine | ✅ Complete |
| Compliance Engine | ✅ Complete |
| AI Recommendation Engine | ✅ Complete |
| Reporting | ✅ Complete |
| Security | ✅ Complete |
| Docker Support | ✅ Complete |
| Frontend | 🚧 Under Development |

---

# Future Enhancements

- Web Dashboard
- OCR-based Employee Document Verification
- Machine Learning-Based Fraud Detection
- Real-Time Notifications
- Automated Testing
- CI/CD Pipeline
- Cloud Deployment