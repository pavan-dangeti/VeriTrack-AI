from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from app.auth.permissions import require_permission
from app.models.user import User
from app.services.audit_service import log_action

from app.services.leave_comparison_service import (
    compare_leave_data
)

from app.services.upload_service import (
    get_latest_employee_file,
    get_latest_gets_file
)

router = APIRouter(
    prefix="/comparison",
    tags=["Comparison"]
)


@router.get("/run")
def run_comparison(
    current_user: User = Depends(
        require_permission("can_compare")
    )
):

    employee_file = get_latest_employee_file()
    gets_file = get_latest_gets_file()

    if employee_file is None:
        raise HTTPException(
            status_code=404,
            detail="No employee data uploaded"
        )

    if gets_file is None:
        raise HTTPException(
            status_code=404,
            detail="No GETS sheet uploaded"
        )

    result = compare_leave_data(
        employee_file,
        gets_file
    )

    log_action(
    current_user.email,
    "RUN_COMPARISON",
    "Employee vs GETS comparison"
)

    return result