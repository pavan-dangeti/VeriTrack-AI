import pandas as pd

from app.services.compliance_report_service import (
    generate_report
)


def create_excel_report():

    report = generate_report(
        "app/uploads/employees/test_employees.csv",
        "app/uploads/gets/test_gets.csv"
    )

    output_file = (
        "app/reports/Compliance_Report.xlsx"
    )

    summary_df = pd.DataFrame(
        [report["summary"]]
    )

    issues_df = pd.DataFrame(
        report["issues"]
    )

    with pd.ExcelWriter(
        output_file,
        engine="openpyxl"
    ) as writer:

        summary_df.to_excel(
            writer,
            sheet_name="Summary",
            index=False
        )

        issues_df.to_excel(
            writer,
            sheet_name="Issues",
            index=False
        )

    return output_file