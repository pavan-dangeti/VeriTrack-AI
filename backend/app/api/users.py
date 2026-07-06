from fastapi import APIRouter
from app.schemas.user import CreateUserRequest
from app.models.user import User
from app.db.database import SessionLocal
from app.auth.security import hash_password

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

@router.post("/")
def create_user(data: CreateUserRequest):

    db = SessionLocal()

    user = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
        active=True
    )

    db.add(user)
    db.commit()

    return {
        "message": "User Created"
    }