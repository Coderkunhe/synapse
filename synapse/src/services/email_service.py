"""Email sending service — SMTP-based transactional emails.

P10-B15: Minimal email infrastructure for password reset.
Design: two-layer API — generic send_email() for reuse, plus
domain-specific convenience functions.

Template engine: string.Template (stdlib) — sufficient for
simple password-reset emails with 2 variables.
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from string import Template

from src.config import settings

logger = logging.getLogger(__name__)

# Template directory relative to this file
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"


async def send_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str = "",
) -> bool:
    """Send a multipart/alternative email via SMTP.

    Returns True if the email was sent successfully.
    Returns False (with log warning) if SMTP_HOST is empty.
    Returns False (with log error) if SMTP send fails for any reason.
    Never raises — all exceptions are caught and logged.
    """
    if not settings.smtp_host:
        logger.warning(
            "SMTP not configured (smtp_host is empty) — skipping email to %s",
            to_email,
        )
        return False

    message = MIMEMultipart("alternative")
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        import aiosmtplib  # type: ignore[import-not-found]

        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_use_tls,
        )
        logger.info("Email sent to %s (subject: %s)", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


def _load_template(name: str) -> Template:
    """Load a template file from the email templates directory."""
    path = _TEMPLATE_DIR / name
    return Template(path.read_text(encoding="utf-8"))


async def send_password_reset_email(
    *,
    to_email: str,
    reset_token: str,
) -> bool:
    """Send a password reset email with a reset link.

    Loads password_reset.html and password_reset.txt templates,
    substitutes the reset URL and expiry, and sends via send_email().
    """
    reset_url = f"{settings.frontend_url}/reset-password?token={reset_token}"
    expires_minutes = settings.reset_token_expire_minutes

    html_template = _load_template("password_reset.html")
    text_template = _load_template("password_reset.txt")

    substitutes = {
        "reset_url": reset_url,
        "expires_in_minutes": str(expires_minutes),
    }

    return await send_email(
        to_email=to_email,
        subject="Synapse — Password Reset",
        html_body=html_template.substitute(substitutes),
        text_body=text_template.substitute(substitutes),
    )
