from app.db.database import Base
from app.db.database import engine

from app.models.user import User
from app.models.role import Role
from app.models.employee import Employee
from app.models.upload_history import UploadHistory
from app.models.user_role import UserRole
from app.models.user_request import UserRequest
from app.models.user_role import UserRole
from app.models.audit_log import AuditLog
from app.models.report_history import ReportHistory
from app.models.refresh_token import RefreshToken
from app.models.password_reset import PasswordReset

print("Creating tables...")

Base.metadata.create_all(bind=engine)

print("Done.")