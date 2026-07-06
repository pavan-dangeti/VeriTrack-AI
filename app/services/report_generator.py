import os
from datetime import datetime


REPORT_DIR = "app/reports"

os.makedirs(REPORT_DIR, exist_ok=True)


def generate_compliance_report(
    manager_name: str,
    comparison: dict
):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"Compliance_Report_{timestamp}.txt"

    filepath = os.path.join(
        REPORT_DIR,
        filename
    )

    summary = comparison["summary"]

    with open(filepath, "w") as report:

        report.write("=============================================================\n")
        report.write("                 VERITRACK AI COMPLIANCE REPORT\n")
        report.write("=============================================================\n\n")

        report.write(
            f"Manager              : {manager_name}\n"
        )

        report.write(
            f"Generated On         : {datetime.now()}\n"
        )

        report.write(
            f"Compliance Score     : {summary['compliance_score']}%\n"
        )

        report.write(
            f"Risk Level           : {summary['risk_level']}\n\n"
        )

        report.write("=============================================================\n")
        report.write("EXECUTIVE SUMMARY\n")
        report.write("=============================================================\n\n")

        report.write(
            f"Employees in Database : {summary['employees_in_database']}\n"
        )

        report.write(
            f"Employees in GETS     : {summary['employees_in_gets']}\n"
        )

        report.write(
            f"Matched Employees     : {summary['matched']}\n"
        )

        report.write(
            f"Missing in GETS       : {summary['missing_in_gets']}\n"
        )

        report.write(
            f"Unknown Employee IDs  : {summary['missing_in_employee']}\n"
        )

        report.write(
            f"Missing Email IDs     : {summary['missing_email']}\n\n"
        )

        report.write("=============================================================\n")
        report.write("DEPARTMENT SUMMARY\n")
        report.write("=============================================================\n\n")

        for department in comparison["department_summary"]:

            report.write(
                f"{department['department']} : "
                f"{department['employees']} Employees\n"
            )

        report.write("\n")

        report.write("=============================================================\n")
        report.write("AI RECOMMENDATIONS\n")
        report.write("=============================================================\n\n")

        for recommendation in comparison["recommendations"]:

            report.write(
                f"• {recommendation}\n"
            )

        report.write("\n")

        report.write("=============================================================\n")
        report.write("MATCHED EMPLOYEES\n")
        report.write("=============================================================\n\n")

        for emp in comparison["matched_employee_ids"]:

            report.write(f"{emp}\n")

        report.write("\n")

        report.write("=============================================================\n")
        report.write("EMPLOYEES MISSING IN GETS\n")
        report.write("=============================================================\n\n")

        for emp in comparison["missing_in_gets"]:

            report.write(f"{emp}\n")

        report.write("\n")

        report.write("=============================================================\n")
        report.write("UNKNOWN EMPLOYEE IDS FOUND IN GETS\n")
        report.write("=============================================================\n\n")

        for emp in comparison["missing_in_employee"]:

            report.write(f"{emp}\n")

        report.write("\n")

        report.write("=============================================================\n")
        report.write("EMPLOYEES WITHOUT COMPANY EMAIL\n")
        report.write("=============================================================\n\n")

        for emp in comparison["employees_without_email"]:

            report.write(f"{emp}\n")

        report.write("\n")

        report.write("=============================================================\n")
        report.write("END OF REPORT\n")
        report.write("=============================================================\n")

    return {

        "filename": filename,

        "filepath": filepath

    }