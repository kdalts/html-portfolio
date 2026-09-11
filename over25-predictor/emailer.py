"""
Sends the daily CSV as an email attachment via Gmail SMTP, using an app
password (never the main Google account password).

Generate an app password at https://myaccount.google.com/apppasswords
(requires 2-Step Verification to be enabled on the Google account), then put
it in .env as GMAIL_APP_PASSWORD.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("over25.emailer")


def send_csv_email(
    smtp_host: str,
    smtp_port: int,
    gmail_address: str,
    gmail_app_password: str,
    to_address: str,
    subject: str,
    body: str,
    attachment_path: Path,
) -> None:
    msg = EmailMessage()
    msg["From"] = gmail_address
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)

    data = attachment_path.read_bytes()
    msg.add_attachment(
        data,
        maintype="text",
        subtype="csv",
        filename=attachment_path.name,
    )

    log.info("Sending email to %s via %s:%s ...", to_address, smtp_host, smtp_port)
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(gmail_address, gmail_app_password)
        server.send_message(msg)
    log.info("Email sent.")
