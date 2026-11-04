"""Server-side n8n or SMTP delivery. Never log bodies or invitation secrets."""
import os
import smtplib
import ssl
from urllib.parse import urlparse
from email.message import EmailMessage
import httpx


def send_email(destination: str, subject: str, body: str):
    # Existing SMTP deployments keep working; new deployments select n8n explicitly.
    provider = os.getenv("EMAIL_PROVIDER", "n8n" if os.getenv("N8N_EMAIL_WEBHOOK_URL") else "smtp").strip().lower()
    if provider == "n8n":
        return send_via_n8n(destination, subject, body)
    if provider != "smtp":
        raise RuntimeError("Unsupported EMAIL_PROVIDER")
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


def send_via_n8n(destination: str, subject: str, body: str):
    url = os.getenv("N8N_EMAIL_WEBHOOK_URL", "").strip()
    token = os.getenv("N8N_EMAIL_WEBHOOK_TOKEN", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise RuntimeError("N8N_EMAIL_WEBHOOK_URL must be an HTTPS production webhook")
    if not token or not os.getenv("SMTP_FROM", ""):
        raise RuntimeError("N8N_EMAIL_WEBHOOK_TOKEN / SMTP_FROM are not configured")
    # No redirects: never forward a webhook credential or private invitation elsewhere.
    # No automatic retries: an ambiguous timeout may already have delivered the email.
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            result = client.post(url, headers={"X-Interview-Token": token}, json={
                "event": "interview.email", "to": destination,
                "from": os.environ["SMTP_FROM"], "subject": subject, "text": body,
            })
        if result.status_code != 200 or result.json().get("status") != "sent":
            raise RuntimeError("Email workflow did not confirm delivery to the mail server")
    except (httpx.HTTPError, ValueError, AttributeError) as from_error:
        raise RuntimeError("Email workflow unavailable or returned an invalid response") from from_error
