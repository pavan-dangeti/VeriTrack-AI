from fastapi import APIRouter
from fastapi import HTTPException

from app.db.database import SessionLocal

from app.models.user_request import UserRequest
from app.models.user import User

from app.auth.security import hash_password
from app.services.email_service import send_email

router = APIRouter(
    prefix="/requests",
    tags=["User Requests"]
)


@router.post("/register")
def register_request(
    name: str,
    email: str,
    requested_role: str,
    reason: str
):

    db = SessionLocal()

    request = UserRequest(
        name=name,
        email=email,
        requested_role=requested_role,
        reason=reason
    )

    db.add(request)
    db.commit()
    db.close()

    return {
        "message": "Request submitted",
        "status": "PENDING"
    }


@router.get("/pending")
def pending_requests():

    db = SessionLocal()

    requests = (
        db.query(UserRequest)
        .filter(UserRequest.status == "PENDING")
        .all()
    )

    result = []

    for request in requests:

        result.append({
            "id": str(request.id),
            "name": request.name,
            "email": request.email,
            "requested_role": request.requested_role,
            "reason": request.reason
        })

    db.close()

    return result


@router.post("/approve")
def approve_request(
    request_id: str,
    assigned_role: str,
    password: str,
    manager_id: str = ""
):

    db = SessionLocal()

    request = (
        db.query(UserRequest)
        .filter(UserRequest.id == request_id)
        .first()
    )

    if request is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Request not found"
        )

    existing_user = (
        db.query(User)
        .filter(User.email == request.email)
        .first()
    )

    if existing_user:
        db.close()
        raise HTTPException(
            status_code=400,
            detail="User already exists"
        )

    user = User(
        name=request.name,
        email=request.email,
        password_hash=hash_password(password),
        role=assigned_role,
        manager_id=manager_id,
        approval_status="APPROVED",
        active=True
    )

    db.add(user)

    request.status = "APPROVED"

    db.commit()

    # Send approval email
    send_email(
        receiver=request.email,
        subject="VeriTrack AI - Account Approved",
        message=f"""
Hello {request.name},

Congratulations!

Your VeriTrack AI account has been approved.

Role: {assigned_role}

You can now log in using the following credentials:

Email: {request.email}
Password: {password}

Please change your password after your first login.

Welcome to VeriTrack AI!

Regards,
VeriTrack AI Team
"""
    )

    db.close()

    return {
        "message": "User approved successfully",
        "assigned_role": assigned_role
    }


@router.post("/reject")
def reject_request(request_id: str):

    db = SessionLocal()

    request = (
        db.query(UserRequest)
        .filter(UserRequest.id == request_id)
        .first()
    )

    if request is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Request not found"
        )

    request.status = "REJECTED"

    db.commit()

    # Send rejection email
    send_email(
        receiver=request.email,
        subject="VeriTrack AI - Registration Request Rejected",
        message=f"""
Hello {request.name},

Thank you for your interest in VeriTrack AI.

Unfortunately, your registration request has been rejected by the administrator.

If you think this was a mistake, please contact the administrator for further clarification.

Regards,
VeriTrack AI Team
"""
    )

    db.close()

    return {
        "message": "Request rejected"
    }