import os
import smtplib

from dotenv import load_dotenv

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))

EMAIL = os.getenv("SMTP_EMAIL")
PASSWORD = os.getenv("SMTP_PASSWORD")


# =====================================================
# Generic Email Sender
# =====================================================

def send_email(
    receiver: str,
    subject: str,
    message: str
):

    try:

        msg = MIMEMultipart()

        msg["From"] = EMAIL
        msg["To"] = receiver
        msg["Subject"] = subject

        msg.attach(
            MIMEText(
                message,
                "plain"
            )
        )

        server = smtplib.SMTP(
            SMTP_SERVER,
            SMTP_PORT
        )

        server.starttls()

        server.login(
            EMAIL,
            PASSWORD
        )

        server.sendmail(
            EMAIL,
            receiver,
            msg.as_string()
        )

        server.quit()

        return True

    except Exception as e:

        print("Email Error:", e)

        return False


# =====================================================
# Compliance Report Email
# =====================================================

def send_compliance_report_email(

    receiver: str,

    manager_name: str,

    comparison: dict,

    report_name: str

):

    summary = comparison["summary"]

    message = f"""
Hello {manager_name},

Your VeriTrack AI compliance verification has completed successfully.

====================================================

Compliance Score : {summary['compliance_score']}%

Risk Level       : {summary['risk_level']}

Employees in Database : {summary['employees_in_database']}

Employees in GETS     : {summary['employees_in_gets']}

Matched Employees     : {summary['matched']}

Missing in GETS       : {summary['missing_in_gets']}

Unknown Employee IDs  : {summary['missing_in_employee']}

Missing Email IDs     : {summary['missing_email']}

====================================================

Recommendations

"""

    for recommendation in comparison["recommendations"]:

        message += f"\n• {recommendation}"

    message += f"""

====================================================

Generated Report

{report_name}

Thank you,

VeriTrack AI
Sacha Global Private Limited
"""

    return send_email(

        receiver=receiver,

        subject="VeriTrack AI - Compliance Report Ready",

        message=message

    )


# =====================================================
# Password Reset Email
# =====================================================

def send_password_reset_email(

    receiver: str,

    reset_token: str

):

    reset_link = (
        f"http://localhost:5173/reset-password?token={reset_token}"
    )

    message = f"""
Hello,

A password reset request has been received for your VeriTrack AI account.

Click the link below to reset your password:

{reset_link}

This password reset link is valid for 30 minutes.

If you did not request this password reset, you can safely ignore this email.

====================================================

VeriTrack AI
Sacha Global Private Limited

This is an automated email. Please do not reply.
"""

    return send_email(

        receiver=receiver,

        subject="VeriTrack AI - Password Reset",

        message=message

    )