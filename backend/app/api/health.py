from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.db.database import SessionLocal

router = APIRouter(
    prefix="/health",
    tags=["Health"]
)


@router.get("/")
def health():

    db = SessionLocal()

    database = "DOWN"

    try:

        db.execute(text("SELECT 1"))

        database = "UP"

    except Exception:

        database = "DOWN"

    finally:

        db.close()

    return {

        "application": "VeriTrack AI",

        "version": "1.0.0",

        "status": "HEALTHY",

        "database": database,

        "server_time": datetime.utcnow(),

        "environment": "Development"

    }