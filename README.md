<div align="center">

# 🛡️ VeriTrack AI

**Industry-Grade Enterprise Employee Compliance Verification Platform**

[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](./LICENSE)
[![Status](https://img.shields.io/badge/Backend-Production_Ready-success?style=for-the-badge)]()

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-LangGraph-blueviolet?style=flat-square)
![JWT](https://img.shields.io/badge/JWT-Secured-orange?style=flat-square)
![PaddleOCR](https://img.shields.io/badge/PaddleOCR-Document_AI-red?style=flat-square)

> VeriTrack AI is an industry-grade backend platform that automates employee compliance verification by comparing employee master data with monthly GETS sheets. It delivers secure user management, role-based access control, AI-powered compliance recommendations, OCR-based document processing, automated report generation, audit logging, and real-time analytics — all through a production-ready RESTful API layer.

</div>

---

## 🏗️ System Overview

```
                    ┌─────────────────────────────┐
                    │         React Frontend        │
                    │     (Production — Private)    │
                    └──────────────┬──────────────┘
                                   │ REST API
                    ┌──────────────▼──────────────┐
                    │        FastAPI Backend        │
                    │   ┌─────────────────────┐    │
                    │   │   JWT Auth + RBAC   │    │
                    │   ├─────────────────────┤    │
                    │   │  Compliance Engine  │    │
                    │   ├─────────────────────┤    │
                    │   │  AI Recommendation  │    │
                    │   │  (LangChain/Graph)  │    │
                    │   ├─────────────────────┤    │
                    │   │   OCR Processing    │    │
                    │   │   (PaddleOCR)       │    │
                    │   ├─────────────────────┤    │
                    │   │  Report Generation  │    │
                    │   │  (ReportLab)        │    │
                    │   └─────────────────────┘    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │     PostgreSQL Database       │
                    └─────────────────────────────┘
```

---

## ✨ Core Modules

### 🔐 Authentication & Authorization
- JWT Authentication with Refresh Token rotation
- Password Reset via Email (SMTP)
- Role-Based Access Control (RBAC) — HR, Manager, Admin
- Account Lock Protection after failed attempts
- Rate Limiting on sensitive endpoints

### 👥 Employee Management
- Employee Master Data Upload (Excel/CSV)
- Full-text Employee Search & Filter
- Department & Manager-wise Mapping
- Employee Database CRUD Management

### ✅ Compliance Verification Engine
- Automated comparison of Employee Database vs GETS Sheet
- Missing Employee Detection
- Unknown Employee Detection
- Missing Email Detection
- Department-wise Compliance Summary
- Compliance Score Calculation (0–100%)
- Risk Level Classification (Low / Medium / High / Critical)
- **AI-Based Recommendations** using LangChain + LangGraph

### 📄 OCR & Document Processing
- Document upload and text extraction via PaddleOCR
- PDF parsing with PyMuPDF + pdfplumber
- SHA-256 duplicate file detection
- Secure filename sanitization

### 📊 Report Management
- Automated Compliance Report Generation (PDF via ReportLab)
- Report History & Upload History tracking
- Downloadable reports per compliance cycle
- Full Audit Log trail

### 🔔 Notifications
- Compliance Report delivery via Email
- Password Reset Email flow
- Background async task processing

### ⚙️ Background Processing
- Asynchronous GETS Sheet processing
- Auto-triggered Report Generation post-analysis
- Background task queue management

---

## 🔒 Security Architecture

| Layer | Implementation |
|---|---|
| Authentication | JWT + Refresh Token (Passlib + bcrypt) |
| Authorization | Role-Based Access Control (RBAC) |
| File Security | SHA-256 duplicate detection + secure sanitization |
| Transport | CORS Protection + Security Headers |
| Host Validation | Trusted Host Middleware |
| Rate Limiting | Per-endpoint request throttling |
| Input Validation | Pydantic schema validation on all endpoints |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI (Python) |
| ORM | SQLAlchemy |
| Database | PostgreSQL |
| Authentication | JWT · Passlib · bcrypt |
| Data Processing | Pandas · OpenPyXL |
| OCR | PaddleOCR · PyMuPDF · pdfplumber |
| AI Engine | LangChain · LangGraph |
| Reporting | ReportLab |
| Containerization | Docker · Docker Compose |
| API Docs | Swagger UI (auto-generated) |

---

## 📡 API Reference

| Module | Endpoints |
|---|---|
| Authentication | Login, Logout, Refresh, Password Reset |
| User Management | Create, Update, Delete, Role Assignment |
| Employee Management | Upload, Search, Filter, CRUD |
| Upload Management | GETS Sheet Upload, History |
| Compliance Engine | Run Analysis, Department Summary, Score |
| AI Recommendations | Generate, Retrieve |
| Dashboard | Metrics, Charts, Analytics |
| Manager Dashboard | Team Compliance View |
| HR Dashboard | Organization-wide View |
| Reports | Generate, Download, History |
| Audit Logs | Full Activity Trail |
| Health Check | System Status |

Full interactive API documentation available at: `http://localhost:8000/docs`

---

## 📊 Module Status

| Module | Status |
|---|---|
| Backend APIs | ✅ Production Ready |
| Authentication + RBAC | ✅ Production Ready |
| Employee Management | ✅ Production Ready |
| Upload Engine | ✅ Production Ready |
| Compliance Engine | ✅ Production Ready |
| AI Recommendation Engine | ✅ Production Ready |
| OCR Document Processing | ✅ Production Ready |
| Report Generation | ✅ Production Ready |
| Email Notifications | ✅ Production Ready |
| Audit Logging | ✅ Production Ready |
| Security Layer | ✅ Production Ready |
| Docker Deployment | ✅ Production Ready |
| Frontend Dashboard | ✅ Complete (Private) |

---

## 📁 Project Structure

```
backend/
├── app/
│   ├── api/            # Route handlers
│   ├── auth/           # JWT + RBAC logic
│   ├── core/           # Config, settings
│   ├── db/             # Database session
│   ├── middleware/      # Security middleware
│   ├── models/         # SQLAlchemy models
│   ├── schemas/        # Pydantic schemas
│   ├── services/       # Business logic
│   ├── uploads/        # Uploaded files
│   └── reports/        # Generated reports
├── logs/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- PostgreSQL 14+
- Docker & Docker Compose (optional)

### Local Setup

```bash
# Clone the repository
git clone https://github.com/pavan-dangeti/VeriTrack-AI.git
cd VeriTrack-AI

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in your values

# Run the application
uvicorn app.main:app --reload
```

### Environment Variables

```env
DATABASE_URL=postgresql://user:password@localhost/veritrack
SECRET_KEY=your_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your_email@gmail.com
SMTP_PASSWORD=your_app_password
```

### Docker Deployment

```bash
docker compose build
docker compose up
```

API available at: `http://localhost:8000`
Swagger docs at: `http://localhost:8000/docs`

---

## 🗺️ Roadmap

- [ ] OCR-based Employee Document Verification
- [ ] Machine Learning-Based Fraud Detection
- [ ] Real-Time Notifications (WebSocket)
- [ ] Automated Testing Suite (pytest)
- [ ] CI/CD Pipeline (GitHub Actions)
- [ ] Cloud Deployment (AWS / GCP)
- [ ] Multi-tenant Architecture

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](./LICENSE) file for details.

---

<div align="center">

🛡️ **VeriTrack AI — Automate compliance. Eliminate errors. Build trust.**

*Industry-grade backend. Production-ready architecture.*

</div>
