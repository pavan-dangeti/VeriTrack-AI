from pydantic import BaseModel


class RoleCreate(BaseModel):
    role_name: str

    can_upload_employee: bool = False
    can_upload_gets: bool = False
    can_compare: bool = False

    can_view_reports: bool = False
    can_download_reports: bool = False

    can_manage_users: bool = False
    can_create_roles: bool = False
    can_assign_manager: bool = False
    can_approve_requests: bool = False


class RoleUpdate(RoleCreate):
    pass