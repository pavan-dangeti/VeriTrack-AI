from app.services.excel_report_service import (
    create_excel_report
)

path = create_excel_report()

print(path)