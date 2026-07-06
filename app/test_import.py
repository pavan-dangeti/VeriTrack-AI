from app.services.employee_import_service import (
    read_employee_file
)

result = read_employee_file(
    "app/uploads/employees/test_employees.csv"
)

print(result)