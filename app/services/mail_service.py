"""Send outbound email via SMTP (used for EOD / manager updates)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings


def is_smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def send_plain_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
) -> None:
    if not is_smtp_configured():
        raise RuntimeError(
            "Email is not configured. Set SMTP_HOST, SMTP_FROM_EMAIL, and credentials in the API environment."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to_email
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    context = ssl.create_default_context()
    host = settings.SMTP_HOST
    port = int(settings.SMTP_PORT)

    if settings.SMTP_USE_TLS:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as server:
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
