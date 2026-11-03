"""SMTP STARTTLS delivery. Never log message bodies or invitation secrets."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def send_email(destination: str, subject: str, body: str):
    host = os.getenv("SMTP_HOST", "")
    sender = os.getenv("SMTP_FROM", "")
    if not host or not sender:
        raise RuntimeError("SMTP_HOST / SMTP_FROM are not configured")
    port = int(os.getenv("SMTP_PORT", "587"))
    if port not in range(1, 65536):
        raise RuntimeError("Invalid SMTP port")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = destination
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.ehlo()
        if not smtp.has_extn("starttls"):
            raise RuntimeError("SMTP server does not support STARTTLS")
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        username = os.getenv("SMTP_USER", "")
        if username:
            smtp.login(username, os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(msg)
