from typing import Dict


def generate_ai_summary(comparison: Dict):

    summary = comparison["summary"]

    matched = summary["matched"]

    total = summary["employees_in_database"]

    missing_gets = summary["missing_in_gets"]

    missing_employee = summary["missing_in_employee"]

    missing_email = summary["missing_email"]

    compliance = summary["compliance_score"]

    risk = summary["risk_level"]

    recommendations = []

    priority = "LOW"

    # =======================================
    # Priority Calculation
    # =======================================

    if compliance >= 95:

        priority = "LOW"

    elif compliance >= 80:

        priority = "MEDIUM"

    else:

        priority = "HIGH"

    # =======================================
    # AI Recommendations
    # =======================================

    if missing_gets > 0:

        recommendations.append(
            f"{missing_gets} employees are missing in the GETS sheet. Verify payroll records before processing."
        )

    if missing_employee > 0:

        recommendations.append(
            f"{missing_employee} unknown employee IDs were found inside the GETS sheet."
        )

    if missing_email > 0:

        recommendations.append(
            f"{missing_email} employees do not have official company email addresses."
        )

    if compliance < 90:

        recommendations.append(
            "Overall compliance is below the enterprise target of 90%. Immediate review is recommended."
        )

    if len(recommendations) == 0:

        recommendations.append(
            "Excellent compliance detected. No operational issues require immediate attention."
        )

    # =======================================
    # Executive Summary
    # =======================================

    executive_summary = (
        f"{matched} of {total} employees were successfully verified. "
        f"The current compliance score is {compliance}%. "
        f"The organization is currently classified as {risk} risk."
    )

    return {

        "executive_summary": executive_summary,

        "priority": priority,

        "risk_level": risk,

        "recommendations": recommendations

    }