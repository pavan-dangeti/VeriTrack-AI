import pandas as pd


def extract_spreadsheet(file_path):

    if file_path.endswith(".csv"):
        df = pd.read_csv(file_path)

    elif (
        file_path.endswith(".xlsx")
        or file_path.endswith(".xls")
    ):
        df = pd.read_excel(file_path)

    else:
        return {
            "success": False,
            "message": "Unsupported file"
        }

    return {
        "success": True,
        "columns": list(df.columns),
        "rows": len(df),
        "preview": df.head(10).to_dict(
            orient="records"
        )
    }