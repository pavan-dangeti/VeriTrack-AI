from app.db.database import SessionLocal
from app.models.user import User
from app.auth.security import hash_password

db = SessionLocal()

existing = db.query(User).filter(
    User.email == "admin@veritrack.ai"
).first()

if existing:
    print("Admin already exists")
else:
    admin = User(
        name="Master Admin",
        email="admin@veritrack.ai",
        password_hash=hash_password("Admin@123"),
        role="MASTER_ADMIN",
        active=True
    )

    db.add(admin)
    db.commit()

    print("Master Admin Created")

db.close()