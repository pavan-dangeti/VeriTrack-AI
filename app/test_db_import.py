from app.services.employee_db_import import (
    import_employees
)

result = import_employees(
    "app/uploads/employees/test_employees.csv"
)

print(result)