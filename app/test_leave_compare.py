from app.services.leave_comparison_service import (
    compare_leave_data
)

result = compare_leave_data(
    "app/uploads/employees/test_employees.csv",
    "app/uploads/gets/test_gets.csv"
)

print(result)