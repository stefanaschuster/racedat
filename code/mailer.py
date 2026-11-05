#!/usr/bin/env python3
"""mailer — E-Mail-Versand über die Brevo-HTTPS-API (Port 443), stdlib only.

nativeAI erlaubt keinen SMTP-Versand aus der App. Brevo bietet denselben
Transaktionsversand über die REST-API an (POST /v3/smtp/email); das läuft
über HTTPS. Voraussetzung: Internetzugang ist für den Nutzer freigeschaltet.

Konfiguration (.env im App-Verzeichnis):
  BREVO_API_KEY=xkeysib-...        (Brevo -> SMTP & API -> API Keys; NICHT
                                    der SMTP-Key)
  MAIL_SENDER_EMAIL=no-reply@racedat.de   (in Brevo als Absender verifiziert)
  MAIL_SENDER_NAME=Racedat
  BASE_URL=https://<app>.nativeai.digitalsandkasten.de
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


class MailerNotConfigured(Exception):
    """Raised when the mail configuration is missing or incomplete."""


class MailSendError(Exception):
    """Raised when the Brevo API call fails (auth, network, rejected...)."""


REQUIRED_MAIL_KEYS = ("api_key", "sender_email")


def smtp_config_from_app_config(cfg: dict) -> dict:
    """Name aus Kompatibilität beibehalten: liefert den Mail-Abschnitt
    (api_key, sender_email, sender_name) oder wirft MailerNotConfigured."""
    mail_cfg = (cfg or {}).get("smtp")
    if not isinstance(mail_cfg, dict):
        raise MailerNotConfigured(
            "Mail nicht konfiguriert (BREVO_API_KEY / MAIL_SENDER_EMAIL "
            "in .env fehlen).")
    missing = [k for k in REQUIRED_MAIL_KEYS if not mail_cfg.get(k)]
    if missing:
        raise MailerNotConfigured(
            f"Mail-Konfiguration unvollständig: fehlende Felder {missing}.")
    return mail_cfg


def send_mail(smtp_cfg: dict, *, to_email: str, subject: str,
              text_body: str, html_body: Optional[str] = None,
              timeout: float = 15.0) -> None:
    """Send one e-mail via the Brevo transactional API."""
    payload = {
        "sender": {"email": smtp_cfg["sender_email"],
                   "name": smtp_cfg.get("sender_name") or "Racedat"},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text_body,
    }
    if html_body:
        payload["htmlContent"] = html_body
    req = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"api-key": smtp_cfg["api_key"],
                 "content-type": "application/json",
                 "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise MailSendError(f"Brevo-API HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise MailSendError(f"Brevo-API nicht erreichbar: {e}") from e


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
