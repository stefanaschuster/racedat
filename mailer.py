#!/usr/bin/env python3
"""mailer — minimal SMTP sending via Brevo, stdlib only (smtplib).

Used for the self-registration e-mail-verification flow. Config comes from
<data_dir>/config.json (see webserver.py AppState._load_config), same
"optional, silently degrade" pattern as maptiler_key — except here, if SMTP
isn't configured, registration itself must refuse rather than pretend to
have sent a mail nobody will get.

config.json keys (all under a top-level "smtp" object):
  {
    "smtp": {
      "host": "smtp-relay.brevo.com",
      "port": 587,
      "login": "xxxxxx@smtp-brevo.com",
      "password": "<Brevo SMTP key>",
      "sender_email": "no-reply@racedat.example.com",
      "sender_name": "Racedat"
    },
    "base_url": "https://racedat.example.com"
  }

Brevo SMTP docs: relay host smtp-relay.brevo.com, port 587 with STARTTLS.
Login/password are the SMTP credentials shown in the Brevo dashboard under
SMTP & API — NOT your Brevo account password.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional


class MailerNotConfigured(Exception):
    """Raised when config.json has no (complete) "smtp" section."""


class MailSendError(Exception):
    """Raised when the SMTP conversation itself fails (auth, connection,
    rejected recipient, ...). Wraps the underlying smtplib/OSError."""


REQUIRED_SMTP_KEYS = ("host", "port", "login", "password", "sender_email")


def smtp_config_from_app_config(cfg: dict) -> dict:
    """Extract + validate the "smtp" section from the parsed config.json
    dict. Raises MailerNotConfigured if missing or incomplete."""
    smtp_cfg = (cfg or {}).get("smtp")
    if not isinstance(smtp_cfg, dict):
        raise MailerNotConfigured(
            "config.json enthält keinen \"smtp\"-Abschnitt.")
    missing = [k for k in REQUIRED_SMTP_KEYS if not smtp_cfg.get(k)]
    if missing:
        raise MailerNotConfigured(
            f"config.json smtp-Abschnitt: fehlende Felder {missing}.")
    return smtp_cfg


def send_mail(smtp_cfg: dict, *, to_email: str, subject: str,
              text_body: str, html_body: Optional[str] = None,
              timeout: float = 15.0) -> None:
    """Send one e-mail via the configured Brevo SMTP relay.

    Raises MailSendError on any failure (connection, auth, rejected
    recipient, ...). Caller decides how to surface that (log + generic
    error to the user — never expose SMTP internals to end users)."""
    sender_email = smtp_cfg["sender_email"]
    sender_name = smtp_cfg.get("sender_name") or "Racedat"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = to_email
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    host = smtp_cfg["host"]
    port = int(smtp_cfg["port"])
    login = smtp_cfg["login"]
    password = smtp_cfg["password"]

    try:
        # Brevo's relay uses STARTTLS on 587 (the common case). Port 465
        # (implicit TLS) is supported too if someone configures it that way.
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=timeout,
                                  context=context) as server:
                server.login(login, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(login, password)
                server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise MailSendError(f"SMTP-Versand fehlgeschlagen: {e}") from e


def send_verification_email(smtp_cfg: dict, *, to_email: str,
                             verify_url: str) -> None:
    """Compose + send the registration-verification e-mail."""
    subject = "Racedat — E-Mail-Adresse bestätigen"
    text_body = (
        "Willkommen bei Racedat!\n\n"
        "Bitte bestätige deine E-Mail-Adresse über diesen Link "
        "(gültig 24 Stunden):\n\n"
        f"{verify_url}\n\n"
        "Falls du dich nicht registriert hast, kannst du diese Mail "
        "ignorieren.\n"
    )
    html_body = f"""\
<div style="font-family:sans-serif;max-width:480px;margin:0 auto">
  <h2 style="margin-bottom:8px">Willkommen bei Racedat!</h2>
  <p>Bitte bestätige deine E-Mail-Adresse, um deinen Account zu aktivieren
     (Link ist 24 Stunden gültig):</p>
  <p style="margin:24px 0">
    <a href="{verify_url}"
       style="background:#00d4ff;color:#000;padding:12px 24px;
              text-decoration:none;font-weight:bold;display:inline-block">
      E-MAIL BESTÄTIGEN
    </a>
  </p>
  <p style="color:#888;font-size:13px">
    Falls du dich nicht registriert hast, kannst du diese Mail ignorieren.
  </p>
</div>
"""
    send_mail(smtp_cfg, to_email=to_email, subject=subject,
              text_body=text_body, html_body=html_body)
