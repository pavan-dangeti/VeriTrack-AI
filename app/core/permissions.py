"""Central permission map — the single source of truth for RBAC.

Server-side enforcement uses this map; it mirrors the product permission matrix.
Frontend display must never be trusted; every route checks here (or via
require_roles) before executing.
"""

from enum import StrEnum

from app.models.user import UserRole


class Permission(StrEnum):
    CREATE_MANAGER_OR_EXECUTIVE = "create_manager_or_executive"
    CREATE_HR = "create_hr"
    MANAGE_ACCOUNT_STATUS = "manage_account_status"
    APPROVE_M365_DOMAINS = "approve_m365_domains"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    VIEW_ALL_DATA = "view_all_data"
    VIEW_REPORTS_ALL = "view_reports_all"
    VIEW_OWN_REPORTS = "view_own_reports"
    UPLOAD_DATA = "upload_data"
    RUN_ANALYZE = "run_analyze"


ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.MASTER_ADMIN: {
        Permission.CREATE_MANAGER_OR_EXECUTIVE,
        Permission.MANAGE_ACCOUNT_STATUS,
        Permission.APPROVE_M365_DOMAINS,
        Permission.VIEW_AUDIT_LOGS,
        Permission.VIEW_ALL_DATA,
        Permission.VIEW_REPORTS_ALL,
        Permission.VIEW_OWN_REPORTS,
    },
    UserRole.EXECUTIVE: {
        Permission.VIEW_ALL_DATA,
        Permission.VIEW_REPORTS_ALL,
        Permission.VIEW_OWN_REPORTS,
    },
    UserRole.MANAGER: {
        Permission.CREATE_HR,
        Permission.VIEW_OWN_REPORTS,
        Permission.UPLOAD_DATA,
        Permission.RUN_ANALYZE,
    },
    UserRole.HR: {
        Permission.VIEW_OWN_REPORTS,  # scoped to their manager's data at query layer
    },
}


def role_has(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
