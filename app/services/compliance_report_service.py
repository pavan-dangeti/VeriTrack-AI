from app.services.leave_comparison_service import (
    compare_leave_data
)


def generate_report(
    employee_file: str,
    gets_file: str
):

    result = compare_leave_data(
        employee_file,
        gets_file
    )

    report = {
        "summary": {
            "missing_in_gets":
                len(
                    result["missing_in_gets"]
                ),

            "missing_in_employee":
                len(
                    result[
                        "missing_in_employee"
                    ]
                ),

            "leave_mismatches":
                len(
                    result[
                        "leave_mismatches"
                    ]
                )
        },

        "issues": []
    }

    for emp_id in result[
        "missing_in_gets"
    ]:

        report["issues"].append({
            "type":
                "MISSING_IN_GETS",

            "employee_id":
                emp_id
        })

    for emp_id in result[
        "missing_in_employee"
    ]:

        report["issues"].append({
            "type":
                "UNKNOWN_EMPLOYEE",

            "employee_id":
                emp_id
        })

    for issue in result[
        "leave_mismatches"
    ]:

        report["issues"].append({
            "type":
                "LEAVE_MISMATCH",

            "employee_id":
                issue["employee_id"]
        })

    return report