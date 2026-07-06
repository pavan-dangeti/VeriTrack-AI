import pandas as pd


COLUMN_MAPPING = {
    "employee id": "employee_id",
    "emp id": "employee_id",
    "associate id": "employee_id",

    "employee name": "employee_name",
    "name": "employee_name",

    "department": "department",

    "company email": "company_email",
    "email": "company_email",

    "customer leave": "customer_leave",
    "sacha leave": "sacha_leave"
}


def read_employee_file(file_path: str):

    if file_path.endswith(".csv"):
        df = pd.read_csv(file_path)

    elif file_path.endswith(".xlsx"):
        df = pd.read_excel(file_path)

    else:
        raise Exception(
            "Unsupported file format"
        )

    detected_columns = {}

    for column in df.columns:

        key = column.strip().lower()

        if key in COLUMN_MAPPING:
            detected_columns[column] = (
                COLUMN_MAPPING[key]
            )

    return {
        "columns": list(df.columns),
        "mapped_columns": detected_columns,
        "records": df.to_dict(
            orient="records"
        )
    }