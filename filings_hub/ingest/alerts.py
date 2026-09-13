"""Failure / anomaly alerts for the daily refresh: Slack webhook and/or email, stdout otherwise."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from filings_hub.config import Settings, get_settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str, settings: Settings | None = None) -> bool:
    """One plain-text email through the configured SMTP relay. False (and a log line) when not configured."""
    s = settings or get_settings()
    if not s.smtp_host:
        log.warning("email to %s not sent (no SMTP_HOST): %s", to, subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.smtp_user or "filings-hub@localhost"
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)
    return True


def notify(subject: str, body: str, settings: Settings | None = None) -> list[str]:
    """Send an alert through every configured channel. Returns the channels used."""
    s = settings or get_settings()
    used: list[str] = []
    if s.slack_webhook_url:
        try:
            httpx.post(s.slack_webhook_url, json={"text": f"*{subject}*\n{body}"}, timeout=15).raise_for_status()
            used.append("slack")
        except Exception as e:
            log.error("slack alert failed: %s", e)
    if s.alert_email_to and s.smtp_host:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = s.smtp_user or "filings-hub@localhost"
            msg["To"] = s.alert_email_to
            msg.set_content(body)
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
            used.append("email")
        except Exception as e:
            log.error("email alert failed: %s", e)
    if not used:
        log.warning("ALERT %s: %s", subject, body)
        used.append("log")
    return used
