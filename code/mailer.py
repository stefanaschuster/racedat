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
  BASE_URL=https://<app>.<domain>                (öffentliche Adresse der App)
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
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


MAIL_TEMPLATES = Path(__file__).resolve().parent / "mail"


def _fill(text: str, values: dict, escape: bool = False) -> str:
    """{platzhalter} einmal ersetzen; unbekannte bleiben stehen."""
    def repl(m):
        if m.group(1) not in values:
            return m.group(0)
        v = str(values[m.group(1)])
        return html.escape(v, quote=True) if escape else v
    return re.sub(r"\{(\w+)\}", repl, text)


def render_mail(template: str, **values) -> tuple[str, str, Optional[str]]:
    """Vorlage mail/<template>.txt (erste Zeile "Betreff: …", Leerzeile, Text)
    und optional mail/<template>.html. Liefert (Betreff, Text, HTML oder None)."""
    try:
        raw = (MAIL_TEMPLATES / f"{template}.txt").read_text(encoding="utf-8")
    except OSError as e:
        raise MailSendError(f"Mail-Vorlage {template}.txt nicht lesbar: {e}") from e
    head, _, body = raw.partition("\n")
    if not head.lower().startswith("betreff:"):
        raise MailSendError(f"{template}.txt: erste Zeile muss mit 'Betreff:' beginnen")
    subject = _fill(head.split(":", 1)[1].strip(), values)
    text_body = _fill(body.lstrip("\n"), values)
    html_path = MAIL_TEMPLATES / f"{template}.html"
    html_body = None
    if html_path.is_file():
        html_body = _fill(html_path.read_text(encoding="utf-8"), values, escape=True)
    return subject, text_body, html_body


def send_verification_email(smtp_cfg: dict, *, to_email: str,
                             verify_url: str) -> None:
    """Bestätigungsmail aus mail/bestaetigung.txt/.html senden."""
    subject, text_body, html_body = render_mail("bestaetigung", link=verify_url)
    send_mail(smtp_cfg, to_email=to_email, subject=subject,
              text_body=text_body, html_body=html_body)
