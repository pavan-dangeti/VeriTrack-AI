import pandas as pd

from app.db.database import SessionLocal
from app.models.employee import Employee


def compare_leave_data(
    manager_id: str,
    gets_file: str
):

    db = SessionLocal()

    employees = db.query(Employee).filter(
        Employee.manager_id == manager_id
    ).all()

    db.close()

    employee_ids = set()

    employee_lookup = {}

    department_summary = {}

    employees_without_email = []

    for employee in employees:

        employee_ids.add(employee.employee_id)

        employee_lookup[employee.employee_id] = {
            "employee_id": employee.employee_id,
            "full_name": employee.full_name,
            "company_email": employee.company_email,
            "department": employee.department
        }

        department = (
            employee.department
            if employee.department
            else "Unknown"
        )

        department_summary[department] = (
            department_summary.get(department, 0) + 1
        )

        if (
            employee.company_email is None
            or employee.company_email.strip() == ""
        ):

            employees_without_email.append(
                employee.employee_id
            )

    gets_df = pd.read_csv(gets_file)

    gets_df["Employee ID"] = (
        gets_df["Employee ID"]
        .astype(str)
        .str.strip()
    )

    gets_ids = set(
        gets_df["Employee ID"]
    )

    missing_in_gets = sorted(
        list(employee_ids - gets_ids)
    )

    missing_in_employee = sorted(
        list(gets_ids - employee_ids)
    )

    matched = sorted(
        list(employee_ids.intersection(gets_ids))
    )

    total_checks = len(employee_ids)

    if total_checks == 0:

        compliance_score = 0

    else:

        compliance_score = round(
            (
                len(matched)
                / total_checks
            ) * 100,
            2
        )


    if compliance_score >= 95:

        risk_level = "LOW"

    elif compliance_score >= 80:

        risk_level = "MEDIUM"

    else:

        risk_level = "HIGH"


    recommendations = []

    if len(missing_in_gets) > 0:

        recommendations.append(
            "Review employees missing from GETS before payroll processing."
        )

    if len(missing_in_employee) > 0:

        recommendations.append(
            "Verify unknown employee IDs found in GETS."
        )

    if len(employees_without_email) > 0:

        recommendations.append(
            "Update company email addresses for employees missing official email IDs."
        )

    if len(recommendations) == 0:

        recommendations.append(
            "No compliance issues detected. Payroll processing can continue."
        )


    department_stats = []

    for department, count in department_summary.items():

        department_stats.append({

            "department": department,

            "employees": count

        })

    department_stats = sorted(
        department_stats,
        key=lambda x: x["employees"],
        reverse=True
    )


    return {

        "summary": {

            "employees_in_database":
                len(employee_ids),

            "employees_in_gets":
                len(gets_ids),

            "matched":
                len(matched),

            "missing_in_gets":
                len(missing_in_gets),

            "missing_in_employee":
                len(missing_in_employee),

            "missing_email":
                len(employees_without_email),

            "compliance_score":
                compliance_score,

            "risk_level":
                risk_level

        },

        "department_summary":
            department_stats,

        "recommendations":
            recommendations,

        "matched_employee_ids":
            matched,

        "missing_in_gets":
            missing_in_gets,

        "missing_in_employee":
            missing_in_employee,

        "employees_without_email":
            employees_without_email

    }