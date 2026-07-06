from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.users import router as user_router
from app.api.uploads import router as upload_router
from app.api.detection import router as detection_router
from app.api.extractor import router as extractor_router
from app.api.comparison import router as comparison_router
from app.api.reports import router as reports_router
from app.api.requests import router as requests_router
from app.api.roles import router as roles_router
from app.api.manager import router as manager_router
from app.api.dashboard import router as dashboard_router
from app.api.employees import router as employees_router
from app.api.manager_dashboard import router as manager_dashboard_router
from app.api.audit import router as audit_router
from app.api.master_admin import router as master_admin_router
from app.api.hr_dashboard import router as hr_dashboard_router
from app.api import upload_history
from app.api.analytics import router as analytics_router
from app.api.search import router as search_router
from app.api.job_status import router as job_status_router
from slowapi.middleware import SlowAPIMiddleware
from app.core.rate_limit import limiter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.core.logger import logger
from app.api.health import router as health_router


app = FastAPI(
    title="VeriTrack AI",
    version="1.0.0"
)

logger.info("VeriTrack AI Server Started")

app.add_middleware(

    TrustedHostMiddleware,

    allowed_hosts=[

        "localhost",

        "127.0.0.1",

        "*.sachaglobal.com"

    ]

)

app.add_middleware(

    CORSMiddleware,

    allow_origins=[

        "http://localhost:5173",

        "http://127.0.0.1:5173",

        "https://veritrack.sachaglobal.com"

    ],

    allow_credentials=True,

    allow_methods=[
        "*"
    ],

    allow_headers=[
        "*"
    ]

)


app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(upload_router)
app.include_router(detection_router)
app.include_router(extractor_router)
app.include_router(comparison_router)
app.include_router(reports_router)
app.include_router(requests_router)
app.include_router(roles_router)
app.include_router(manager_router)
app.include_router(dashboard_router)
app.include_router(employees_router)
app.include_router(manager_dashboard_router)
app.include_router(audit_router)
app.include_router(master_admin_router)
app.include_router(hr_dashboard_router)
app.include_router(upload_history.router)
app.include_router(analytics_router)
app.include_router(search_router)
app.include_router(job_status_router)
app.include_router(health_router)


@app.get("/")
def root():
    return {
        "application": "VeriTrack AI",
        "status": "running"
    }