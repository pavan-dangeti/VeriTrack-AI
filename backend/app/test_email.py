from app.services.email_service import send_email

success = send_email(
    receiver="bsvercel@gmail.com",
    subject="VeriTrack AI Test",
    message="Congratulations! Email integration is working."
)

print(success)