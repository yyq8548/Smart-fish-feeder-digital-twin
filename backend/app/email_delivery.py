import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

settings = get_settings()
logger = logging.getLogger("fish_feeder")


def deliver_account_email(recipient: str, subject: str, text_body: str) -> None:
    if settings.email_delivery_mode == "console":
        logger.info(
            "development_account_email",
            extra={"recipient": recipient, "subject": subject, "account_email_body": text_body},
        )
        return
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP delivery is enabled but SMTP host/from address is not configured")
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
