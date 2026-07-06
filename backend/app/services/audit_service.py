from app.db.database import SessionLocal
from app.models.audit_log import AuditLog


def log_action(
    user_email: str,
    action: str,
    details: str = ""
):

    db = SessionLocal()

    log = AuditLog(
        user_email=user_email,
        action=action,
        details=details
    )

    db.add(log)
    db.commit()
    db.close()