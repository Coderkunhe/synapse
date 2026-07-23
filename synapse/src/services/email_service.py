"""Email sending service — SMTP-based transactional emails.

P10-B15: Minimal email infrastructure for password reset.
Design: two-layer API — generic send_email() for reuse, plus
domain-specific convenience functions.

Template engine: string.Template (stdlib) — sufficient for
simple password-reset emails with 2 variables.
"""

from __future__ import annotations

import asyncio
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

    Tries aiosmtplib (async, preferred) first; falls back to stdlib
    smtplib (sync, run_in_executor) when aiosmtplib is not installed.
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

    # Preferred: async via aiosmtplib
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
    except ImportError:
        logger.debug("aiosmtplib not installed — falling back to stdlib smtplib")
    except Exception:
        logger.exception("Failed to send email to %s via aiosmtplib", to_email)
        return False

    # Fallback: stdlib smtplib (sync, run in thread pool for async compat)
    try:
        import smtplib
        from email.message import Message

        def _send_sync() -> None:
            msg_bytes: bytes
            if isinstance(message, Message):
                msg_bytes = message.as_bytes()
            else:
                msg_bytes = message.as_string().encode("utf-8")
            if settings.smtp_use_tls:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
                server.starttls()
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.smtp_from_email, [to_email], msg_bytes)
            server.quit()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send_sync)
        logger.info("Email sent to %s via stdlib smtplib (subject: %s)", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s via stdlib smtplib", to_email)
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
