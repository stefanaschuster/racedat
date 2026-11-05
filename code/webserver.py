#!/usr/bin/env python3
"""webserver — Racedat web UI with session library.

Stdlib-only (no Flask, no FastAPI). Uses SQLite for the session/lap
database. Originals are stored on disk under <data_dir>/originals/,
reports under <data_dir>/reports/.

Usage:
  python3 webserver.py                   # 0.0.0.0:8000
  python3 webserver.py --port 9000
  python3 webserver.py --data /var/lap

Endpoints:
  GET  /                          Compare page (slot selection)
  POST /compare                   Run a comparison, redirect to report
  GET  /report/<id>               Show interactive report
  GET  /download/<id>             Download report HTML

  GET  /sessions                  Library listing
  GET  /sessions/upload           Session upload form (step 1: file + meta)
  POST /sessions/upload           Parse file, show lap-picker (step 2)
  POST /sessions/save             Persist session + selected laps
  POST /sessions/<id>/edit        Admin-only: update session metadata (JSON)
  POST /laps/<id>/delete          Delete a single lap (and its session if empty)

  GET  /api/distinct              JSON: distinct driver/bike/track values
  GET  /api/laps?...filters...    JSON: filtered lap list
"""
from __future__ import annotations

import argparse
import html
import io
import json
import os
import pickle
import re
import shutil
import ssl
import sys
import tempfile
import threading
import traceback
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote, unquote
import urllib.request
import urllib.error
import ipaddress

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Bumped on every release; surfaced ONLY on the /admin page so you can verify
# from the browser which build is actually loaded into the running process.
VERSION = "v23.21"
PROCESS_START_UTC = datetime.now(timezone.utc)

def version_info() -> dict:
    """Build a snapshot of the running build for the admin header.

    Includes the SHA-1 of the in-memory report_single source (so you can tell
    whether the file on disk matches what the running process executes; the
    process won't reload changes until restart) and mtimes of the key files.
    """
    import hashlib
    info = {
        "version": VERSION,
        "process_started": PROCESS_START_UTC.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "report_single_sha": "?",
        "report_single_mtime": "?",
        "coach_sha": "?",
        "coach_mtime": "?",
        "report_sha": "?",
        "report_mtime": "?",
        "webserver_sha": "?",
        "webserver_mtime": "?",
    }
    for label, fname in (("report_single", "report_single.py"),
                         ("coach",         "coach.py"),
                         ("report",        "report.py"),
                         ("webserver",     "webserver.py")):
        p = HERE / fname
        try:
            data = p.read_bytes()
            info[f"{label}_sha"] = hashlib.sha1(data).hexdigest()[:10]
            mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            info[f"{label}_mtime"] = mt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            pass
    return info


try:
    import numpy as np  # noqa: F401
except ImportError:
    sys.stderr.write(
        "ERROR: numpy is required.\n"
        "Install: sudo apt install python3-numpy\n"
    )
    sys.exit(2)

from parsers import (parse_ses, parse_ld, parse_xrk, parse_racebox_csv,
                     parse_aim_csv, is_aim_csv,
                     parse_starlane_csv, is_starlane_csv,
                     parse_i2m, parse_2d)
from parsers.channel_roles import (
    ROLES as CHANNEL_ROLES,
    build_available_extras,
    suggest_channel,
    sanitise_assignment,
)
# v22.4 — SVG icons, one per channel role, used by the picker dots row.
# `webapp/` has no __init__.py (it's mainly a static-file dir), but Python
# 3.3+ treats it as a namespace package, which is what we want — no need
# to add a __init__.py just for this import.
from webapp.role_icons import ROLE_ICONS as _ROLE_ICONS, icon_for as _icon_for
from laps import detect_laps, fastest_lap, extract_lap_data
from compare import align_laps, hot_zones
from report import (
    build_html_report,
    build_compare_html,
    build_compare_empty_html,
    _fmt_lap,
)
from report_single import (
    build_single_lap_html,
    compute_single_lap_payload,
    build_single_lap_empty_html,
)
from coach import (
    build_coach_html,
    build_coach_empty_html,
)
from db import DB, EmailNotVerifiedError
import debuglog
import mailer


# ---------- Configuration ---------------------------------------------------

ALLOWED_EXTS = {".ses", ".ld", ".xrk", ".xrz", ".csv", ".dat", ".zip"}
# nativeAI: der Proxy erlaubt höchstens 10 MB pro Request.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
WEBAPP_DIR = HERE / "webapp"     # HTML-Templates
STATIC_DIR = HERE / "static"     # ausgelieferte JS/CSS-Assets


# ---------- Template helpers ------------------------------------------------

def render_template(name: str, **vars) -> bytes:
    """Read template file and do simple {{KEY}} substitution.
    Variables not provided default to empty string."""
    tpl_path = WEBAPP_DIR / name
    text = tpl_path.read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v))
    # Sweep any remaining placeholders (e.g. NAV_USER if caller didn't pass)
    text = re.sub(r"\{\{[A-Z_]+\}\}", "", text)
    return text.encode("utf-8")


def build_user_nav_snippet(user) -> str:
    """Return the small HTML snippet that goes at the end of the nav links
    showing either '+ LOGIN' (no user) or '<email>  ABMELDEN' (logged in)."""
    if not user:
        return ('<a href="/login" style="color:#00d4ff">+ LOGIN</a>')
    email = html.escape(user["email"])
    admin_tag = (' <span style="color:#ff3d00;font-size:9px;'
                 'letter-spacing:.15em;margin-left:2px">(ADMIN)</span>'
                 if user["is_admin"] else "")
    # Inline form so logout is a POST
    return (
        f'<span style="color:#a0a0a0">{email}{admin_tag}</span>'
        f'<form method="POST" action="/logout" style="display:inline;margin-left:12px">'
        f'<button type="submit" style="background:none;border:none;color:#a0a0a0;'
        f'font-family:inherit;font-size:inherit;letter-spacing:inherit;'
        f'text-transform:inherit;cursor:pointer;padding:0">ABMELDEN</button>'
        f'</form>'
    )


def build_admin_nav_snippet(user, current_path: str = "") -> str:
    """Return the 'ADMIN' nav link, but ONLY for admin users.
    Empty string for everyone else — the link is invisible to non-admins.
    `current_path` is used to add the .active class when on /admin."""
    if not user or not user.get("is_admin"):
        return ""
    active = ' class="active"' if current_path.startswith("/admin") else ""
    return f'<a href="/admin"{active}><span class="label">ADMIN</span></a>'


# === v22.11 — Reverse IP lookup ============================================
# Each row in the admin tabs that carries an IP address gets a clickable
# link to /admin/ip-lookup?ip=<ip>, which renders a small page with the
# geo info (city, country, ISP, …) pulled server-side from ip-api.com.
#
# Why server-side: ip-api.com's free tier is HTTP-only (HTTPS is paid).
# A direct browser fetch from an HTTPS-served admin page would trip the
# mixed-content block. The server has no such restriction, and gating it
# behind an admin-only handler also prevents the endpoint from being
# abused as an open proxy that would burn the 45/min rate limit.

_IP_API_URL = "http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
_IP_API_TIMEOUT_S = 4.0


def is_private_or_loopback_ip(ip: str) -> bool:
    """Return True for loopback / private / link-local / reserved addresses.
    These are not meaningful for reverse-IP lookup — short-circuit them
    so we don't waste the ip-api.com rate-limit budget."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (addr.is_loopback or addr.is_private or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


def is_valid_public_ip(ip: str) -> bool:
    """True if `ip` is a syntactically valid IPv4/IPv6 address that is
    NOT in a private/loopback/reserved range. Used to gate the upstream
    API call from /admin/ip-lookup."""
    if not ip:
        return False
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not is_private_or_loopback_ip(ip)


def fetch_ip_geo(ip: str, *, timeout: float = _IP_API_TIMEOUT_S) -> dict:
    """Server-side call to ip-api.com/json. Returns a dict with at minimum
    a 'status' key ('success'|'fail'|'error'). On network or parse errors,
    we return {'status':'error','message':<str>} rather than raising, so the
    caller can render a friendly message instead of a 500."""
    url = _IP_API_URL.format(ip=quote(ip, safe=""))
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "racedat/admin-ip-lookup",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if not isinstance(data, dict):
            return {"status": "error", "message": "unexpected response shape"}
        return data
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"network: {e.reason}"}
    except (TimeoutError, OSError) as e:
        return {"status": "error", "message": f"network: {e}"}
    except (ValueError, json.JSONDecodeError) as e:
        return {"status": "error", "message": f"parse: {e}"}


def render_ip_cell(ip: str) -> str:
    """Render an IP value as it should appear inside a .col-ip table cell
    in the admin tabs. Single source of truth — used by logins, uploads,
    and the activity tab so they stay consistent.

    - Empty/None -> '—' (dim placeholder)
    - Loopback/private -> bare text + small dim '(lokal)' marker, NOT a link
      (no useful geo lookup possible)
    - Public -> <a> linking to /admin/ip-lookup?ip=<ip> (target=_blank)

    Caller is responsible for escaping anything else in the row; this helper
    HTML-escapes the IP itself."""
    if not ip:
        return '<span style="color:var(--ink-faint)">—</span>'
    ip_esc = html.escape(ip)
    if is_private_or_loopback_ip(ip):
        return (f'{ip_esc} <span style="color:var(--ink-faint);font-size:10px">'
                f'(lokal)</span>')
    if not is_valid_public_ip(ip):
        # Syntactically invalid — show as plain text, no link
        return ip_esc
    return (f'<a href="/admin/ip-lookup?ip={quote(ip, safe="")}" '
            f'class="ip-link" target="_blank" rel="noopener" '
            f'title="Standort & ISP nachschlagen (ip-api.com)">{ip_esc}</a>')


# Single source of truth for the page header. Every page — static
# templates, generated reports, and analyses — calls this so they all
# look and feel identical. No more jumpy nav between page types.
HEADER_CSS = """
<style>
  /* === Unified header ===================================================
     Same height, same padding, same alignment on every page. Sticky so it
     stays put when the user scrolls a long report or analysis. */
  .rd-header{
    position:sticky;top:0;z-index:999;
    background:var(--bg,#0a0a0a);
    border-bottom:1px solid var(--line,#262626);
    font-family:'JetBrains Mono',monospace;
  }
  .rd-header .inner{
    max-width:1280px;margin:0 auto;
    padding:14px 32px;
    display:flex;justify-content:space-between;align-items:center;
    gap:24px;
  }
  .rd-header .brand-wrap{display:flex;flex-direction:column;line-height:1;text-decoration:none;color:inherit}
  .rd-header .brand{font-family:'Bebas Neue',sans-serif;font-size:26px;letter-spacing:.02em;color:var(--ink,#f5f5f0)}
  .rd-header .tagline{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.2em;color:var(--ink-faint,#888);text-transform:uppercase;margin-top:4px}
  .rd-header .links{display:flex;gap:24px;font-size:11px;letter-spacing:.15em;text-transform:uppercase;align-items:center}
  .rd-header .links a{color:var(--ink-dim,#a0a0a0);text-decoration:none;padding-bottom:2px}
  .rd-header .links a:hover{color:var(--ink,#f5f5f0)}
  .rd-header .links a.active{color:var(--ink,#f5f5f0)}
  .rd-header .links a .plus{margin-right:4px;color:var(--ink-faint,#888)}
  .rd-header .links a.active .plus{color:var(--ink,#f5f5f0)}
  .rd-header .links a .label{padding-bottom:2px;border-bottom:2px solid transparent}
  .rd-header .links a.active .label{border-bottom-color:var(--accent,#00d4ff)}
  .rd-header form{display:inline;margin:0}
  .rd-header button{background:none;border:none;color:inherit;font-family:inherit;font-size:inherit;letter-spacing:inherit;text-transform:inherit;cursor:pointer;padding:0}
  /* v23.16 — Mobile: Brand über einer horizontal scrollenden Nav-Zeile.
     Kein Burger-Menü (kein JS, ein Tap weniger); die Zeile scrollt seitlich,
     ein Fade am rechten Rand signalisiert "da kommt noch was". */
  @media (max-width:700px){
    .rd-header .inner{
      padding:10px 0 0;
      flex-direction:column;align-items:stretch;gap:8px;
    }
    .rd-header .brand-wrap{padding:0 16px}
    .rd-header .brand{font-size:22px}
    .rd-header .tagline{font-size:9px}
    .rd-header .links{
      gap:0;overflow-x:auto;-webkit-overflow-scrolling:touch;
      scrollbar-width:none;padding:0 16px;
      mask-image:linear-gradient(90deg,#000 calc(100% - 28px),transparent);
      -webkit-mask-image:linear-gradient(90deg,#000 calc(100% - 28px),transparent);
    }
    .rd-header .links::-webkit-scrollbar{display:none}
    .rd-header .links a,
    .rd-header .links > span,
    .rd-header .links form button{
      flex:0 0 auto;
      padding:10px 10px 12px;
      white-space:nowrap;
    }
    .rd-header .links a .label{padding-bottom:4px}
  }
</style>
"""


def build_header_html(user, current_path: str) -> str:
    """Return the unified header HTML (CSS + nav) used on every page.

    `current_path` drives which nav item gets the .active highlight.
    Compare, Datenviewer, and Runden are always shown; Admin only for admin
    users; the user-snippet is at the end (login link or email+logout)."""
    def _active(path_prefix: str) -> str:
        return ' class="active"' if current_path.startswith(path_prefix) else ''

    # The "/compare" page is the default home for the compare flow.
    # Reports (/report/<id>) are conceptually part of compare too,
    # so highlight compare while viewing one.
    is_compare = current_path == "/compare" or current_path.startswith("/report")
    is_analyse = current_path == "/analyze" or current_path.startswith("/analysis")
    is_coach = current_path == "/coach" or current_path.startswith("/coach/")
    is_runden = current_path.startswith("/sessions")
    is_admin = current_path.startswith("/admin")
    # v22.12 — PROFIL-Link immer sichtbar; nicht-eingeloggte landen über
    # _page_profile() Redirect auf /login?next=/profile (siehe Handler).
    is_profile = current_path.startswith("/profile")
    # v23.2 — Globale Bestzeiten je Strecke (ein Punkt im Header)
    is_records = current_path.startswith("/records")

    def _cls(active: bool) -> str:
        return ' class="active"' if active else ''

    parts = [
        f'<a href="/compare"{_cls(is_compare)}><span class="label">VERGLEICH</span></a>',
        f'<a href="/analyze"{_cls(is_analyse)}><span class="label">DATENVIEWER</span></a>',
        f'<a href="/coach"{_cls(is_coach)}><span class="label">AI COACH</span></a>',
        f'<a href="/sessions"{_cls(is_runden)}><span class="label">RUNDEN</span></a>',
        f'<a href="/records"{_cls(is_records)}><span class="label">BESTZEITEN</span></a>',
        f'<a href="/profile"{_cls(is_profile)}><span class="label">PROFIL</span></a>',
    ]
    if user and user.get("is_admin"):
        parts.append(
            f'<a href="/admin"{_cls(is_admin)}><span class="label">ADMIN</span></a>'
        )
    # User identity / login link
    parts.append(build_user_nav_snippet(user))

    links_html = "\n      ".join(parts)
    return (
        HEADER_CSS +
        '<div class="rd-header">'
        '  <div class="inner">'
        '    <a href="/" class="brand-wrap">'
        '      <span class="brand">RACEDAT</span>'
        '      <span class="tagline">Faster with Data</span>'
        '    </a>'
        f'    <span class="links">\n      {links_html}\n    </span>'
        '  </div>'
        '</div>'
    )



def fmt_seconds(s: float) -> str:
    """Format seconds as M:SS.sss"""
    if s is None:
        return "—"
    m = int(s // 60)
    sec = s - m * 60
    return f"{m}:{sec:06.3f}"


# v23.11 — Runden-Auswahl nach Rundenzeit statt Lap-Nummer. Fahrer kennen
# ihre Zeiten ("die 1:35.3er Runde"), nicht die Zählnummer aus der
# Logger-Datei. Gilt für alle Ad-hoc-Uploads (Compare-Picker, Analyze);
# leer gelassen heißt weiterhin "auto" = schnellste Runde.

def parse_lap_time_input(s: str) -> float:
    """Parse a user-typed lap time into seconds.
    Accepts '95.3', '95,3', '1:35.3', '1:35,3'. Raises ValueError."""
    s = (s or "").strip().replace(",", ".")
    if not s:
        raise ValueError("Leere Rundenzeit.")
    try:
        if ":" in s:
            mins_str, secs_str = s.split(":", 1)
            mins = int(mins_str)
            secs = float(secs_str)
            if mins < 0 or secs < 0 or secs >= 60:
                raise ValueError
            return mins * 60 + secs
        val = float(s)
        if val <= 0:
            raise ValueError
        return val
    except ValueError:
        raise ValueError(
            f"Rundenzeit '{s}' ungültig — erwartet z.B. '1:35.3' oder '95.3'."
        )


def select_lap_by_time(laps: List[Dict[str, Any]], target_s: float,
                       tolerance_s: float = 1.5) -> Dict[str, Any]:
    """Return the detected lap whose duration is closest to target_s.
    Raises ValueError (listing all available times) if none is within
    tolerance_s — that tolerance keeps a typo'd '2:35' from silently
    picking a completely different lap. Laps use detect_laps() dicts
    (key 'duration')."""
    if not laps:
        raise ValueError("Keine Runden in der Datei erkannt.")
    best = min(laps, key=lambda lp: abs(lp["duration"] - target_s))
    if abs(best["duration"] - target_s) > tolerance_s:
        avail = ", ".join(
            fmt_seconds(lp["duration"])
            for lp in sorted(laps, key=lambda l: l["duration"])
        )
        raise ValueError(
            f"Keine Runde nahe {fmt_seconds(target_s)} gefunden "
            f"(verfügbare Zeiten: {avail})"
        )
    return best


# v23.1 — Bestzeiten-Tabelle pro Strecke. Wird sowohl auf dem eigenen
# Profil (`profile.html`) als auch auf der öffentlichen Profilansicht
# (`profile_public.html`) gerendert; deshalb als gemeinsamer Helper
# statt zwei Stellen duplizieren.
def render_best_laps_html(best_laps: List[Dict[str, Any]],
                          medals: Optional[Dict[int, int]] = None) -> str:
    """Render a small HTML table of best lap times per track. Each row
    has an optional medal icon (gold/silver/bronze if the lap is in the
    global Top-3 of that track), track name, formatted M:SS.sss time,
    and a link to /analyze?lap_id=<id>&go=1.

    `medals` is an optional {lap_id: rank} dict where rank is 1, 2 or 3
    (gold/silver/bronze). Pass None to skip medal rendering entirely.

    v23.2 — Bugfix: Datumsangabe entfernt (Stefan: "raus aus der
    Tabelle"). v23.2 — Medal-Spalte hinzugefügt.

    Empty input → empty-state placeholder (no table). Single source of
    truth for the look; the CSS class names match what both profile
    templates ship.
    """
    if not best_laps:
        return (
            '<div class="empty-state">'
            '  <div class="icon">∅</div>'
            '  <div class="label">NOCH KEINE BESTZEITEN</div>'
            '  <div class="hint">'
            '    Sobald Runden mit einer Strecke hochgeladen sind, erscheint '
            '    hier pro Strecke die schnellste Runde.'
            '  </div>'
            '</div>'
        )
    medals = medals or {}
    rows = []
    for b in best_laps:
        track_esc = html.escape(b.get("track") or "—")
        dur = fmt_seconds(b.get("duration_s"))
        lap_id = int(b.get("lap_id") or 0)
        medal_html = render_medal_html(medals.get(lap_id))
        rows.append(
            f'<a href="/analyze?lap_id={lap_id}&go=1" class="bl-row" '
            f'   title="Datenviewer öffnen für die schnellste Runde auf '
            f'{track_esc}">'
            f'  <span class="bl-medal">{medal_html}</span>'
            f'  <span class="bl-track">{track_esc}</span>'
            f'  <span class="bl-time mono">{dur}</span>'
            '  <span class="bl-arrow">→</span>'
            '</a>'
        )
    return '<div class="best-laps">' + "".join(rows) + '</div>'


# v23.2 — Pokal-Icons als Inline-SVG für die globalen Top-3-Bestzeiten
# pro Strecke. Drei feste Farb-Varianten (Gold #FFD700, Silver #C0C0C0,
# Bronze #CD7F32) und drei klare Glyphen — Stefan-Stil "echte Icons
# statt Punkte" wie bei den v22.4-Channel-Icons.
_MEDAL_SVG_GOLD = (
    '<svg viewBox="0 0 20 20" width="16" height="16" '
    'class="medal medal-gold" aria-label="Gold (Top 1)" '
    'xmlns="http://www.w3.org/2000/svg">'
    # Trophy cup body
    '<path d="M5 3h10v3a5 5 0 0 1-10 0V3z" fill="#FFD700" '
    'stroke="#B8860B" stroke-width="0.6"/>'
    # Side handles
    '<path d="M3 4h2v3a2 2 0 0 1-2-2V4zM17 4h-2v3a2 2 0 0 0 2-2V4z" '
    'fill="none" stroke="#B8860B" stroke-width="0.8"/>'
    # Stem + base
    '<path d="M9 11h2v3H9zM7 14h6v1H7z" fill="#B8860B"/>'
    '</svg>'
)
_MEDAL_SVG_SILVER = (
    '<svg viewBox="0 0 20 20" width="16" height="16" '
    'class="medal medal-silver" aria-label="Silber (Top 2)" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<path d="M5 3h10v3a5 5 0 0 1-10 0V3z" fill="#C0C0C0" '
    'stroke="#7A7A7A" stroke-width="0.6"/>'
    '<path d="M3 4h2v3a2 2 0 0 1-2-2V4zM17 4h-2v3a2 2 0 0 0 2-2V4z" '
    'fill="none" stroke="#7A7A7A" stroke-width="0.8"/>'
    '<path d="M9 11h2v3H9zM7 14h6v1H7z" fill="#7A7A7A"/>'
    '</svg>'
)
_MEDAL_SVG_BRONZE = (
    '<svg viewBox="0 0 20 20" width="16" height="16" '
    'class="medal medal-bronze" aria-label="Bronze (Top 3)" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<path d="M5 3h10v3a5 5 0 0 1-10 0V3z" fill="#CD7F32" '
    'stroke="#7A4A1F" stroke-width="0.6"/>'
    '<path d="M3 4h2v3a2 2 0 0 1-2-2V4zM17 4h-2v3a2 2 0 0 0 2-2V4z" '
    'fill="none" stroke="#7A4A1F" stroke-width="0.8"/>'
    '<path d="M9 11h2v3H9zM7 14h6v1H7z" fill="#7A4A1F"/>'
    '</svg>'
)
_MEDAL_SVGS = {1: _MEDAL_SVG_GOLD, 2: _MEDAL_SVG_SILVER, 3: _MEDAL_SVG_BRONZE}


def render_medal_html(rank: Optional[int]) -> str:
    """Return inline SVG for a medal of `rank` (1/2/3) or "" for None
    and any out-of-range rank. Single source of truth — used by the
    sessions list, the profile best-laps section, and the global
    /records page."""
    if rank is None:
        return ""
    return _MEDAL_SVGS.get(int(rank), "")


def medal_map_from_top_n(top_n: List[Dict[str, Any]]) -> Dict[int, int]:
    """Flatten the output of db.global_top_n_per_track() to a
    {lap_id: rank} dict — the shape that render_best_laps_html() and
    the sessions-list rendering loop consume. Stable single hop from
    DB query to UI."""
    out: Dict[int, int] = {}
    for track in top_n or []:
        for e in track.get("entries") or []:
            lap_id = int(e.get("lap_id") or 0)
            rank = int(e.get("rank") or 0)
            if lap_id and 1 <= rank <= 3:
                out[lap_id] = rank
    return out


# ---------- Multipart parser (no cgi dependency) ----------------------------

class UploadTooLarge(Exception):
    pass


_NAME_RE = re.compile(rb'name="([^"]*)"', re.IGNORECASE)
_FILENAME_RE = re.compile(rb'filename="([^"]*)"', re.IGNORECASE)


def _parse_part_headers(header_bytes: bytes):
    name = None
    filename = None
    for line in header_bytes.split(b"\r\n"):
        if line[:20].lower().startswith(b"content-disposition:"):
            n = _NAME_RE.search(line)
            if n:
                name = n.group(1).decode("utf-8", errors="replace")
            f = _FILENAME_RE.search(line)
            if f:
                filename = f.group(1).decode("utf-8", errors="replace")
    return name, filename


def parse_form(handler) -> dict:
    """Parse a POST body. Supports both:
      - multipart/form-data  (forms with file uploads)
      - application/x-www-form-urlencoded  (plain text forms)

    Returns dict {field_name: value or list_of_values}. File fields get
    tuples (filename, bytes); text fields get strings.
    """
    ctype = (handler.headers.get("Content-Type") or "").lower()
    if ctype.startswith("multipart/form-data"):
        return _parse_multipart(handler)
    if ctype.startswith("application/x-www-form-urlencoded"):
        return _parse_urlencoded(handler)
    raise ValueError(
        f"Unsupported Content-Type: "
        f"'{handler.headers.get('Content-Type', '(none)')}'. "
        f"Expected multipart/form-data or application/x-www-form-urlencoded."
    )


# Backwards-compat alias
parse_multipart = parse_form


def _parse_urlencoded(handler) -> dict:
    """Parse application/x-www-form-urlencoded request body.

    Returns dict {field_name: value or list_of_values} matching the shape
    of _parse_multipart for text-only fields.
    """
    cl_str = handler.headers.get("Content-Length")
    if not cl_str:
        raise ValueError("Missing Content-Length")
    total = int(cl_str)
    # 10 MB cap — urlencoded forms should never be huge
    if total > 10 * 1024 * 1024:
        raise UploadTooLarge(
            f"Form body {total/1024/1024:.1f} MB is unreasonably large "
            f"for a urlencoded request."
        )
    body = handler.rfile.read(total)
    if len(body) != total:
        raise ValueError(f"Body short: expected {total}, got {len(body)}")

    parsed = parse_qs(body.decode("utf-8", errors="replace"),
                      keep_blank_values=True)
    result: dict = {}
    for k, v in parsed.items():
        result[k] = v[0] if len(v) == 1 else v
    return result


def _parse_multipart(handler) -> dict:
    """Multipart/form-data parser using only stdlib.

    Returns dict {field_name: value or list_of_values}.
    File fields get tuples (filename, bytes). Multiple values for the same
    field name are returned as a list.
    """
    ctype = handler.headers.get("Content-Type", "")
    m = re.search(r'boundary=([^;,\s]+)', ctype)
    if not m:
        raise ValueError("Missing boundary in Content-Type")
    boundary = m.group(1).strip('"').encode("ascii", errors="replace")
    delim = b"--" + boundary

    cl_str = handler.headers.get("Content-Length")
    if not cl_str:
        raise ValueError("Missing Content-Length")
    total = int(cl_str)
    max_total = MAX_UPLOAD_BYTES + 1024 * 1024
    if total > max_total:
        raise UploadTooLarge(
            f"Total upload {total/1024/1024:.1f} MB > limit "
            f"{max_total/1024/1024:.0f} MB."
        )

    body = handler.rfile.read(total)
    if len(body) != total:
        raise ValueError(f"Body short: expected {total}, got {len(body)}")

    result: dict = {}
    pos = body.find(delim)
    if pos < 0:
        raise ValueError("No boundary found")

    while True:
        pos += len(delim)
        if body[pos:pos + 2] == b"--":
            break
        if body[pos:pos + 2] == b"\r\n":
            pos += 2
        hdr_end = body.find(b"\r\n\r\n", pos)
        if hdr_end < 0:
            raise ValueError("Malformed: missing header terminator")
        header_block = body[pos:hdr_end]
        content_start = hdr_end + 4
        next_b = body.find(b"\r\n" + delim, content_start)
        if next_b < 0:
            raise ValueError("Malformed: no terminating boundary")
        content = body[content_start:next_b]

        name, filename = _parse_part_headers(header_block)
        if name is None:
            pos = next_b + 2
            continue

        if filename is not None:
            if len(content) > MAX_UPLOAD_BYTES:
                raise UploadTooLarge(
                    f"File '{filename}' is {len(content)/1024/1024:.1f} MB — "
                    f"limit is {MAX_UPLOAD_BYTES/1024/1024:.0f} MB."
                )
            if filename == "" and len(content) == 0:
                pos = next_b + 2
                continue
            value = (filename, content)
        else:
            try:
                value = content.decode("utf-8")
            except UnicodeDecodeError:
                value = content.decode("latin-1", errors="replace")

        # Multiple values for the same field → list
        if name in result:
            if isinstance(result[name], list):
                result[name].append(value)
            else:
                result[name] = [result[name], value]
        else:
            result[name] = value
        pos = next_b + 2

    return result


# ---------- Format dispatch -------------------------------------------------

def parse_track(filepath: str):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".ses":
        return parse_ses(filepath)
    if ext == ".ld":
        return parse_ld(filepath)
    if ext in (".xrk", ".xrz"):
        return parse_xrk(filepath)
    if ext == ".csv":
        # v23.6: AIM und RaceBox teilen sich die .csv-Extension. AIM-Dateien
        # beginnen mit "Format","AiM CSV File" — sniffen wir, sonst Default
        # RaceBox (Backward-Compat).
        # Starlane LapTable (Semikolon-getrennt, "Event;Session;...") wird
        # ebenfalls gesnifft; Reihenfolge AIM → Starlane → RaceBox-Default
        # hält RaceBox als Fallback unangetastet.
        if is_aim_csv(filepath):
            return parse_aim_csv(filepath)
        if is_starlane_csv(filepath):
            return parse_starlane_csv(filepath)
        return parse_racebox_csv(filepath)
    if ext == ".dat":
        return parse_i2m(filepath)
    if ext == ".zip":
        # v21.30: 2D BMW HP Race Datalogger bundles are shipped as .zip
        # containing a *.MES directory. parse_2d handles both .zip and the
        # already-extracted directory form.
        return parse_2d(filepath)
    raise ValueError(f"Unsupported extension: {ext}")


def safe_filename(name: str, fallback: str) -> str:
    if not name:
        return fallback
    base = os.path.basename(name).replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or fallback


def _path_is_inside(child: Path, parent: Path) -> bool:
    """True if child is the same as or a descendant of parent (both resolved)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


# v22.12 — Profile-Bild Constraints. Klein (5 MB) weil's nur Profil-/
# Bike-Bilder sind, nicht Telemetrie. Whitelist auf gängige Web-Bildformate;
# .gif und .svg bewusst raus (SVG-XSS-Risiko, GIF überflüssig).
PROFILE_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
PROFILE_IMAGE_MAX_BYTES = 5 * 1024 * 1024

# Filename-Format unter <data_dir>/profile_images/: <uuid><ext>. Wir
# erzwingen genau dieses Schema beim Lesen, damit der read-path keine
# beliebigen Pfade akzeptiert (Path-Traversal-Schutz, defense in depth
# zusätzlich zu _path_is_inside).
_PROFILE_IMG_NAME_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"\.(jpg|jpeg|png|webp)$"
)


def save_profile_image(data: bytes, original_filename: str) -> str:
    """Persist a profile/bike image to <profile_images_dir>/<uuid>.<ext>.
    Returns the stored filename (no path). Raises ValueError on invalid
    extension or oversize input.

    Filename includes a fresh UUID even if the user uploads the same file
    twice — keeps the writers idempotent without any disk-side de-dup."""
    if not data:
        raise ValueError("Leere Datei.")
    if len(data) > PROFILE_IMAGE_MAX_BYTES:
        raise ValueError(
            f"Bild zu groß ({len(data)/1024/1024:.1f} MB). "
            f"Limit: {PROFILE_IMAGE_MAX_BYTES/1024/1024:.0f} MB."
        )
    ext = os.path.splitext(original_filename or "")[1].lower()
    if ext not in PROFILE_IMAGE_EXTS:
        raise ValueError(
            f"Format '{ext}' nicht unterstützt. "
            f"Erlaubt: {', '.join(sorted(PROFILE_IMAGE_EXTS))}"
        )
    # .jpeg → .jpg (Stefan-Style: deutsche Disziplin auch im Dateinamen)
    if ext == ".jpeg":
        ext = ".jpg"
    fname = f"{uuid.uuid4()}{ext}"
    dest = AppState.profile_images_dir / fname
    dest.write_bytes(data)
    return fname


def delete_profile_image(filename: str) -> bool:
    """Remove a previously saved profile image. Silently ignores empty
    input, invalid names, or already-missing files (the read path doesn't
    care either way). Returns True iff a file was actually unlinked."""
    if not filename or not _PROFILE_IMG_NAME_RE.match(filename):
        return False
    p = AppState.profile_images_dir / filename
    if not _path_is_inside(p, AppState.profile_images_dir):
        return False
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


# ---------- Core processing -------------------------------------------------

class AppState:
    db: DB = None
    data_dir: Path = None
    originals_dir: Path = None
    adhoc_dir: Path = None
    reports_dir: Path = None
    analyses_dir: Path = None
    tmp_dir: Path = None
    profile_images_dir: Path = None
    server_secret: bytes = None
    # v21.26 — Konfigurations-Werte aus <data_dir>/config.json.
    # Die Datei ist optional; fehlende Werte degradieren einzeln (Mapview
    # aus, Registrierung deaktiviert) statt den Start zu verhindern.
    config: dict = None
    maptiler_key: str = ""
    # v23.4 — base_url für Verify-Links in Registrierungsmails, z.B.
    # "https://racedat.example.com" (kein trailing slash).
    base_url: str = ""
    registration_enabled: bool = False

    @classmethod
    def init(cls, data_dir: Path):
        cls.data_dir = data_dir
        cls.originals_dir = data_dir / "originals"
        cls.adhoc_dir = data_dir / "adhoc_uploads"
        cls.reports_dir = data_dir / "reports"
        cls.analyses_dir = data_dir / "analyses"
        cls.tmp_dir = data_dir / "tmp"
        # v22.12 — Profile-Bilder (Fahrer-Foto + Bike-Bilder). Filename-only
        # storage: jeder Upload bekommt einen UUID-Namen, die DB hält nur
        # diesen Namen. Read-path ist serve_profile_image() mit strikter
        # Filename-Validierung gegen Path-Traversal.
        cls.profile_images_dir = data_dir / "profile_images"
        for d in (cls.originals_dir, cls.adhoc_dir, cls.reports_dir,
                  cls.analyses_dir, cls.tmp_dir, cls.profile_images_dir):
            d.mkdir(parents=True, exist_ok=True)
        cls.db = DB(data_dir / "sessions.db")
        cls.server_secret = _load_or_create_secret(data_dir / "server_secret")
        cls.config, cls.maptiler_key, cls.base_url = \
            cls._load_config(data_dir / "config.json")
        # nativeAI: Konfiguration/Geheimnisse kommen aus .env (Umgebungs-
        # variablen); config.json bleibt optionaler Fallback.
        cls.config, cls.maptiler_key, cls.base_url = \
            cls._overlay_env(cls.config, cls.maptiler_key, cls.base_url)
        # v23.4 — Registration is only offered if SMTP is fully configured;
        # checked once at startup so a boot-log warning surfaces
        # misconfiguration immediately instead of failing silently on the
        # first /register attempt.
        try:
            mailer.smtp_config_from_app_config(cls.config)
            cls.registration_enabled = bool(cls.base_url)
            if not cls.base_url:
                print("[config] \"base_url\" fehlt in config.json — "
                      "Registrierung bleibt deaktiviert (Verify-Links "
                      "bräuchten eine absolute URL).", file=sys.stderr)
        except mailer.MailerNotConfigured as e:
            cls.registration_enabled = False
            print(f"[config] Registrierung deaktiviert: {e}", file=sys.stderr)

    @staticmethod
    def _overlay_env(cfg: dict, maptiler_key: str, base_url: str):
        """Umgebungsvariablen (.env) überschreiben config.json.
        MAPTILER_KEY, BASE_URL, BREVO_API_KEY, MAIL_SENDER_EMAIL,
        MAIL_SENDER_NAME."""
        e = os.environ.get
        cfg = dict(cfg or {})
        mk = (e("MAPTILER_KEY") or "").strip() or maptiler_key
        bu = (e("BASE_URL") or "").strip().rstrip("/") or base_url
        mail = dict(cfg.get("smtp") or {}) if isinstance(cfg.get("smtp"), dict) else {}
        if e("BREVO_API_KEY"):
            mail["api_key"] = e("BREVO_API_KEY").strip()
        if e("MAIL_SENDER_EMAIL"):
            mail["sender_email"] = e("MAIL_SENDER_EMAIL").strip()
        if e("MAIL_SENDER_NAME"):
            mail["sender_name"] = e("MAIL_SENDER_NAME").strip()
        if mail:
            cfg["smtp"] = mail
        return (cfg, mk, bu)

    @staticmethod
    def _load_config(path: Path) -> tuple[dict, str, str]:
        """Load <data_dir>/config.json. Returns (cfg_dict, maptiler_key,
        base_url).

        Missing or unreadable config files are silently tolerated (returns
        empty dict + empty values). Logs a warning if the file exists but is
        malformed JSON, so misconfigurations surface in the boot log.
        """
        if not path.is_file():
            return ({}, "", "")
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                print(f"[config] {path} is not a JSON object, ignoring",
                      file=sys.stderr)
                return ({}, "", "")
        except Exception as e:
            print(f"[config] could not parse {path}: {e}", file=sys.stderr)
            return ({}, "", "")
        key = cfg.get("maptiler_key") or ""
        if not isinstance(key, str):
            key = ""
        base_url = cfg.get("base_url") or ""
        if not isinstance(base_url, str):
            base_url = ""
        return (cfg, key.strip(), base_url.strip().rstrip("/"))


# ---------- Admin: list reports + analyses ---------------------------------

def list_all_artefacts():
    """Return a sorted list of all reports and analyses on disk, newest first.

    Each entry is a dict with at least: kind ('report'/'analysis'), id (uuid),
    created_at (ISO string), path (Path on disk). Optional extras come from
    the sidecar meta.json that's written alongside each output.

    If meta.json is missing (older artefacts created before the sidecar was
    added), we fall back to the directory's mtime as creation time and leave
    the metadata fields blank.
    """
    items = []

    def _walk(root: Path, kind: str, html_filename: str):
        if not root.is_dir():
            return
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            if not UUID_RE.match(entry.name):
                continue
            html_path = entry / html_filename
            if not html_path.is_file():
                continue
            meta_path = entry / "meta.json"
            sidecar = {}
            if meta_path.is_file():
                try:
                    sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    sidecar = {}
            # Created-at: prefer sidecar value, fall back to file mtime
            created_at = sidecar.get("created_at")
            if not created_at:
                try:
                    ts = entry.stat().st_mtime
                    created_at = datetime.fromtimestamp(
                        ts, tz=timezone.utc
                    ).isoformat(timespec="seconds")
                except OSError:
                    created_at = ""
            # Try to get bytes size of the HTML (for display)
            try:
                size_bytes = html_path.stat().st_size
            except OSError:
                size_bytes = 0
            items.append({
                "kind": kind,
                "id": entry.name,
                "created_at": created_at,
                "size_bytes": size_bytes,
                "meta": sidecar,
                "dir": entry,
            })

    _walk(AppState.reports_dir, "report", "report.html")
    _walk(AppState.analyses_dir, "analysis", "analysis.html")

    # Newest first
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return items


# ---------- Auth: cookie token ---------------------------------------------
# Token layout (in the lapcomp_auth cookie): "<user_id>.<expires_epoch>.<hmac_hex>"
# - hmac is computed over "<user_id>.<expires_epoch>" with the server_secret.
# - We use HMAC-SHA256 truncated to 32 hex chars for brevity.

import hashlib as _hashlib
import hmac as _hmac
import secrets as _secrets
import time as _time

AUTH_COOKIE_NAME = "lapcomp_auth"
AUTH_TTL_SECONDS = 14 * 24 * 3600  # 14 days


def _load_or_create_secret(path: Path) -> bytes:
    """Read the server's signing secret, creating a new random one if missing."""
    if path.is_file():
        data = path.read_bytes().strip()
        if len(data) >= 32:
            return data
    data = _secrets.token_bytes(48)
    # Best-effort restrictive mode (0600)
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return data


def _sign_token(user_id: int, expires: int) -> str:
    msg = f"{user_id}.{expires}".encode("ascii")
    mac = _hmac.new(AppState.server_secret, msg, _hashlib.sha256).hexdigest()[:32]
    return f"{user_id}.{expires}.{mac}"


def _verify_token(token: str):
    """Return (user_id, expires) if valid + unexpired, else None."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    uid_s, exp_s, mac_given = parts
    try:
        uid = int(uid_s)
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < int(_time.time()):
        return None
    expected = _hmac.new(
        AppState.server_secret,
        f"{uid}.{exp}".encode("ascii"),
        _hashlib.sha256,
    ).hexdigest()[:32]
    if not _hmac.compare_digest(expected, mac_given):
        return None
    return uid, exp


def _parse_cookies(header: str) -> dict:
    """Parse the Cookie: header into a dict. Tolerates whitespace variants."""
    out: dict = {}
    if not header:
        return out
    for part in header.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out



def resolve_slot_lap(form: dict, slot: str,
                     request_ctx: Optional[Dict[str, Any]] = None):
    """Resolve slot A or B to (track_dict, lap_meta, lap_data).
    slot is 'a' or 'b'. Reads form fields like {slot}_mode etc."""
    mode = form.get(f"{slot}_mode", "")
    if mode == "library":
        lap_id_str = form.get(f"{slot}_lap_id", "")
        try:
            lap_id = int(lap_id_str)
        except (TypeError, ValueError):
            raise ValueError(f"Slot {slot.upper()}: ungültige Lap-ID")
        rec = AppState.db.get_lap(lap_id)
        if rec is None:
            raise ValueError(f"Slot {slot.upper()}: Runde nicht in Bibliothek gefunden")
        lap_data = rec["lap_data"]
        lap_meta = {
            "lap_index": rec["lap_number"],
            "duration": rec["duration_s"],
            "start_time": 0.0,
            "end_time": rec["duration_s"],
            "method": "library",
        }
        # Synthesize a minimal track dict — only fields used by build_html_report
        track_dict = {
            "meta": {
                "RACER": rec.get("driver") or "",
                "VEHICLE": rec.get("bike") or "",
                "TRACK": rec.get("track") or "",
                "VENUE": rec.get("track") or "",
            },
            "source_format": "LIBRARY",
            "source_file": (
                f"{rec.get('track','')} · {rec.get('bike','')} · "
                f"{rec.get('driver','')} · LAP {rec['lap_number']}"
            ).strip(" ·"),
            "finish_line": None,
            "channels": {},
            "gps_channels": {},
        }
        return track_dict, lap_meta, lap_data

    if mode == "upload":
        if f"{slot}_file" not in form:
            raise ValueError(f"Slot {slot.upper()}: keine Datei hochgeladen")
        fname, data = form[f"{slot}_file"]
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_EXTS:
            raise ValueError(
                f"Slot {slot.upper()}: Endung '{ext}' nicht unterstützt"
            )

        # Persist the ad-hoc upload to disk under adhoc_uploads/<uuid>/<filename>.
        # Kept indefinitely (admin deletes manually). Logged as an event.
        ad_id = uuid.uuid4().hex
        ad_dir = AppState.adhoc_dir / ad_id
        ad_dir.mkdir(parents=True, exist_ok=True)
        safe_name = safe_filename(fname, f"upload_{ad_id}{ext}")
        target_file = ad_dir / safe_name
        target_file.write_bytes(data)

        # Record the upload event for the admin overview.
        try:
            ctx = request_ctx or {}
            AppState.db.add_event(
                kind="upload_adhoc",
                user_id=ctx.get("user_id"),
                user_email=ctx.get("user_email", ""),
                ip_address=ctx.get("ip_address", ""),
                detail=f"compare slot {slot.upper()}: {safe_name}",
                file_path=str(target_file),
            )
        except Exception as e:
            sys.stderr.write(f"[event-log] failed: {e}\n")

        track = parse_track(str(target_file))
        track["source_file"] = safe_name
        laps = detect_laps(track)
        if not laps:
            raise ValueError(
                f"Slot {slot.upper()}: keine Runden in der Datei erkannt"
            )
        lap_time_str = form.get(f"{slot}_lap_time", "")
        if lap_time_str and str(lap_time_str).strip():
            try:
                target_s = parse_lap_time_input(str(lap_time_str))
                lap_meta = select_lap_by_time(laps, target_s)
            except ValueError as e:
                raise ValueError(f"Slot {slot.upper()}: {e}")
        else:
            lap_meta = fastest_lap(laps)
        lap_data = extract_lap_data(track, lap_meta)
        return track, lap_meta, lap_data

    raise ValueError(f"Slot {slot.upper()}: kein Modus gesetzt")


_ADHOC_SLOT_RE = re.compile(r"^ad-[0-9a-f]{8,40}$")


def is_adhoc_slot(s: str) -> bool:
    """Slot identifiers come from URL params. Two flavors:
       - plain integer "42" → library lap_id
       - "ad-<uuid_hex>"    → ad-hoc compare upload (persisted in adhoc_dir).
    """
    return bool(s) and bool(_ADHOC_SLOT_RE.match(s))


def stash_adhoc_upload(file_name: str, file_bytes: bytes,
                       request_ctx: Optional[Dict[str, Any]] = None
                       ) -> Tuple[str, List[Dict[str, Any]]]:
    """v23.12 — Phase 1 des Ad-hoc-Uploads: Datei persistieren, parsen,
    Rundenliste zurückgeben. Noch KEINE Runde extrahieren — die Auswahl
    trifft der User danach in der UI aus der Liste.

    Returns (token, laps) mit laps = [{lap_number, duration_s}, ...]
    sortiert nach Zeit (schnellste zuerst).
    Token shape: "ad-<uuid_hex>"."""
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"Endung '{ext}' nicht unterstützt")

    ad_uuid = uuid.uuid4().hex[:16]
    ad_dir = AppState.adhoc_dir / ("compare-" + ad_uuid)
    ad_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(file_name, f"upload_{ad_uuid}{ext}")
    target_file = ad_dir / safe_name
    target_file.write_bytes(file_bytes)

    try:
        ctx = request_ctx or {}
        AppState.db.add_event(
            kind="upload_adhoc",
            user_id=ctx.get("user_id"),
            user_email=ctx.get("user_email", ""),
            ip_address=ctx.get("ip_address", ""),
            detail=f"adhoc stash: {safe_name}",
            file_path=str(target_file),
        )
    except Exception as e:
        sys.stderr.write(f"[event-log] upload_adhoc(stash) failed: {e}\n")

    track = parse_track(str(target_file))
    laps = detect_laps(track)
    if not laps:
        raise ValueError("Keine Runden in der Datei erkannt")
    lap_list = sorted(
        ({"lap_number": lp["lap_index"], "duration_s": float(lp["duration"])}
         for lp in laps),
        key=lambda l: l["duration_s"],
    )
    return "ad-" + ad_uuid, lap_list


def _adhoc_dir_for_token(token: str) -> Path:
    if not is_adhoc_slot(token):
        raise ValueError(f"Ungültiger Adhoc-Slot: {token}")
    return AppState.adhoc_dir / ("compare-" + token[3:])


def _adhoc_original_file(ad_dir: Path) -> Path:
    """Locate the stashed original upload inside a token dir (the only
    file that isn't parsed.pkl)."""
    if not ad_dir.is_dir():
        raise ValueError("Upload nicht mehr verfügbar — bitte erneut hochladen.")
    for p in sorted(ad_dir.iterdir()):
        if p.is_file() and p.name != "parsed.pkl":
            return p
    raise ValueError("Upload nicht mehr verfügbar — bitte erneut hochladen.")


def resolve_adhoc_lap_choice(token: str, lap_choice: str):
    """v23.12 — Phase 2: parse the stashed file again and pick the lap the
    user chose from the list. lap_choice: 'auto' (= schnellste) oder die
    lap_number als String. Returns (track, lap_meta, lap_data)."""
    ad_dir = _adhoc_dir_for_token(token)
    target_file = _adhoc_original_file(ad_dir)
    track = parse_track(str(target_file))
    track["source_file"] = target_file.name
    laps = detect_laps(track)
    if not laps:
        raise ValueError("Keine Runden in der Datei erkannt")
    choice = (lap_choice or "auto").strip().lower()
    if choice in ("", "auto"):
        lap_meta = fastest_lap(laps)
    else:
        try:
            n = int(choice)
        except ValueError:
            raise ValueError(f"Ungültige Rundenauswahl: {lap_choice!r}")
        lap_meta = next((lp for lp in laps if lp["lap_index"] == n), None)
        if lap_meta is None:
            raise ValueError(
                "Gewählte Runde nicht mehr in der Datei gefunden — "
                "bitte erneut hochladen.")
    lap_data = extract_lap_data(track, lap_meta)
    return track, lap_meta, lap_data


def finalize_adhoc_compare(token: str, lap_choice: str
                           ) -> Tuple[str, Dict[str, Any]]:
    """Phase 2 für den Compare-Picker: Runde wählen, Ergebnis als
    parsed.pkl cachen (damit /compare?a=ad-X in <100ms lädt), Summary
    für die Toolbar zurückgeben."""
    track, lap_meta, lap_data = resolve_adhoc_lap_choice(token, lap_choice)
    ad_dir = _adhoc_dir_for_token(token)
    parsed_path = ad_dir / "parsed.pkl"
    with parsed_path.open("wb") as fh:
        pickle.dump({"track": track, "lap_meta": lap_meta, "lap_data": lap_data}, fh,
                    protocol=pickle.HIGHEST_PROTOCOL)

    track_name = (track.get("meta") or {}).get("TRACK", "") \
                 or (track.get("meta") or {}).get("VENUE", "") or ""
    summary = (
        f"{_fmt_lap(lap_meta['duration'])} · {track_name or '—'} · "
        f"LAP {lap_meta.get('lap_index','?')} (lokal)"
    )
    return token, {
        "track": track_name,
        "summary": summary,
    }


def load_adhoc_compare_upload(slot_token: str):
    """Reload a parsed ad-hoc upload by its token. Raises if missing/expired."""
    if not is_adhoc_slot(slot_token):
        raise ValueError(f"Ungültiger Adhoc-Slot: {slot_token}")
    ad_uuid = slot_token[3:]  # strip 'ad-'
    ad_dir = AppState.adhoc_dir / ("compare-" + ad_uuid)
    parsed_path = ad_dir / "parsed.pkl"
    if not parsed_path.is_file():
        raise ValueError("Lokale Datei nicht mehr verfügbar — bitte erneut hochladen.")
    with parsed_path.open("rb") as fh:
        d = pickle.load(fh)
    return d["track"], d["lap_meta"], d["lap_data"]


def resolve_compare_slot(slot_value: str,
                         request_ctx: Optional[Dict[str, Any]] = None):
    """Resolve a single compare slot from a URL query param.

    slot_value: either an integer string (library lap_id) or 'ad-<hex>'.
    Returns (track, lap_meta, lap_data).
    """
    if is_adhoc_slot(slot_value):
        return load_adhoc_compare_upload(slot_value)
    # else library path
    return resolve_lap_from_form(
        {"mode": "library", "lap_id": str(slot_value)},
        request_ctx,
    )


def resolve_lap_from_form(form: dict,
                          request_ctx: Optional[Dict[str, Any]] = None):
    """Resolve a single-lap selection from form. Used by /analyze.

    Form fields: mode ('library'|'upload'), lap_id, file, lap_time.
    Returns (track, lap_meta, lap_data).
    """
    mode = form.get("mode", "")
    if mode == "library":
        lap_id_str = form.get("lap_id", "")
        try:
            lap_id = int(lap_id_str)
        except (TypeError, ValueError):
            raise ValueError("Ungültige Lap-ID")
        rec = AppState.db.get_lap(lap_id)
        if rec is None:
            raise ValueError("Runde nicht in Bibliothek gefunden")
        lap_data = rec["lap_data"]
        lap_meta = {
            "lap_index": rec["lap_number"],
            "duration": rec["duration_s"],
            "start_time": 0.0,
            "end_time": rec["duration_s"],
            "method": "library",
        }
        track_dict = {
            "meta": {
                "RACER": rec.get("driver") or "",
                "VEHICLE": rec.get("bike") or "",
                "TRACK": rec.get("track") or "",
                "VENUE": rec.get("track") or "",
            },
            "source_format": "LIBRARY",
            "source_file": rec.get("original_filename") or "",
            "finish_line": None,
            "channels": {},
            "gps_channels": {},
        }
        return track_dict, lap_meta, lap_data

    if mode == "upload":
        # v23.12 — Zwei-Phasen-Flow: die UI hat die Datei bereits per
        # /api/adhoc/laps eingelagert und schickt adhoc_token + lap
        # ('auto' oder lap_number). Fallback ohne JS: Datei direkt im
        # Formular → schnellste Runde.
        token = (form.get("adhoc_token") or "").strip()
        if token:
            return resolve_adhoc_lap_choice(token,
                                            (form.get("lap") or "auto"))
        if "file" not in form:
            raise ValueError("Keine Datei hochgeladen")
        fname, data = form["file"]
        stash_token, _laps = stash_adhoc_upload(fname, data,
                                                request_ctx=request_ctx)
        return resolve_adhoc_lap_choice(stash_token, "auto")

    raise ValueError("Kein Modus gesetzt")


def process_analyze(form: dict,
                    request_ctx: Optional[Dict[str, Any]] = None) -> str:
    """Run single-lap analysis. Returns the analysis UUID."""
    track, lap_meta, lap_data = resolve_lap_from_form(form, request_ctx)
    html_doc = build_single_lap_html(
        track=track, lap_meta=lap_meta, lap_data=lap_data,
        maptiler_key=AppState.maptiler_key,
    )
    analysis_id = str(uuid.uuid4())
    out_dir = AppState.analyses_dir / analysis_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis.html").write_text(html_doc, encoding="utf-8")
    # Sidecar metadata for the admin overview page
    meta = track.get("meta") or {}
    ctx = request_ctx or {}
    sidecar = {
        "kind": "analysis",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_format": track.get("source_format", ""),
        "source_file": track.get("source_file", ""),
        "lap_number": lap_meta.get("lap_index"),
        "lap_duration_s": float(lap_meta.get("duration") or 0.0),
        "track": meta.get("TRACK") or meta.get("VENUE") or "",
        "racer": meta.get("RACER") or "",
        "vehicle": meta.get("VEHICLE") or "",
        "date": meta.get("DATE") or "",
        # NEW v16: requester info for admin overview
        "ip_address": ctx.get("ip_address", ""),
        "user_email": ctx.get("user_email", ""),
        "user_id": ctx.get("user_id"),
    }
    (out_dir / "meta.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return analysis_id


def process_compare(form: dict,
                    request_ctx: Optional[Dict[str, Any]] = None) -> str:
    """Run a comparison. Returns the report session UUID for redirect."""
    gps_anchor = form.get("gps_anchor", "") == "on"

    track_a, lap_a_meta, lap_a_data = resolve_slot_lap(form, "a", request_ctx)
    track_b, lap_b_meta, lap_b_data = resolve_slot_lap(form, "b", request_ctx)

    aligned = align_laps(lap_a_data, lap_b_data, n_samples=1000,
                         gps_anchor=gps_anchor)
    zones = hot_zones(aligned)

    report_html = build_html_report(
        track_a, lap_a_meta, lap_a_data,
        track_b, lap_b_meta, lap_b_data,
        aligned, zones,
        maptiler_key=AppState.maptiler_key,
    )

    report_id = str(uuid.uuid4())
    report_dir = AppState.reports_dir / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.html").write_text(report_html, encoding="utf-8")
    # Sidecar metadata for the admin overview page
    meta_a = track_a.get("meta") or {}
    meta_b = track_b.get("meta") or {}
    ctx = request_ctx or {}
    sidecar = {
        "kind": "report",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # NEW v16: requester info for admin overview
        "ip_address": ctx.get("ip_address", ""),
        "user_email": ctx.get("user_email", ""),
        "user_id": ctx.get("user_id"),
        "a": {
            "source_format": track_a.get("source_format", ""),
            "source_file": track_a.get("source_file", ""),
            "lap_number": lap_a_meta.get("lap_index"),
            "lap_duration_s": float(lap_a_meta.get("duration") or 0.0),
            "track": meta_a.get("TRACK") or meta_a.get("VENUE") or "",
            "racer": meta_a.get("RACER") or "",
        },
        "b": {
            "source_format": track_b.get("source_format", ""),
            "source_file": track_b.get("source_file", ""),
            "lap_number": lap_b_meta.get("lap_index"),
            "lap_duration_s": float(lap_b_meta.get("duration") or 0.0),
            "track": meta_b.get("TRACK") or meta_b.get("VENUE") or "",
            "racer": meta_b.get("RACER") or "",
        },
    }
    (report_dir / "meta.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return report_id


# ---------- Session upload (multi-step) -------------------------------------

# In-memory holding area for the lap-picker step. After step 1 (file + meta),
# the file is on disk under originals_dir/<pending_id>/ and metadata in this
# dict. Step 2 (lap selection) reads from here.
PENDING_LOCK = threading.Lock()
PENDING_SESSIONS: dict[str, dict] = {}


def step1_upload_session(form: dict, user_id: Optional[int] = None) -> str:
    """Save file to originals_dir, parse laps, build a pending session.
    Returns pending_id used in step 2."""
    if "file" not in form:
        raise ValueError("Bitte eine Datei auswählen.")
    fname, data = form["file"]
    ext = os.path.splitext(fname)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(
            f"Dateiendung '{ext}' nicht unterstützt. "
            f"Erlaubt: {', '.join(sorted(ALLOWED_EXTS))}"
        )

    pending_id = str(uuid.uuid4())
    sess_dir = AppState.originals_dir / pending_id
    sess_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(fname, f"upload{ext}")
    file_path = sess_dir / safe_name
    file_path.write_bytes(data)

    try:
        track = parse_track(str(file_path))
        laps = detect_laps(track)
    except Exception as e:
        # Clean up on parse failure
        shutil.rmtree(sess_dir, ignore_errors=True)
        raise ValueError(f"Datei konnte nicht gelesen werden: {e}")

    if not laps:
        shutil.rmtree(sess_dir, ignore_errors=True)
        raise ValueError("In der Datei wurden keine Runden erkannt.")

    # Compute lap durations + numbers for the picker
    lap_summaries = [
        {
            "lap_number": lap["lap_index"],
            "duration_s": float(lap["duration"]),
        }
        for lap in laps
    ]

    meta = track.get("meta") or {}

    def _resolve(form_key, *meta_keys):
        """Return (value, source) where source is 'user' or 'auto' or ''."""
        user_val = (form.get(form_key) or "").strip()
        if user_val:
            return user_val, "user"
        for mk in meta_keys:
            mv = meta.get(mk)
            if mv:
                return str(mv).strip(), "auto"
        return "", ""

    driver_v, driver_src = _resolve("driver", "RACER")
    bike_v,   bike_src   = _resolve("bike",   "VEHICLE")
    track_v,  track_src  = _resolve("track",  "TRACK", "VENUE")
    date_v,   date_src   = _resolve("session_date", "DATE")

    pending = {
        "file_path": str(file_path),
        "original_filename": safe_name,
        "format": ext.lstrip("."),
        "user_id": user_id,
        "driver": driver_v,
        "bike":   bike_v,
        "track":  track_v,
        "session_date": date_v,
        "notes":  (form.get("notes")  or "").strip(),
        # Track which fields came from auto-extraction (for UI hints)
        "auto_sources": {
            "driver": driver_src == "auto",
            "bike":   bike_src   == "auto",
            "track":  track_src  == "auto",
            "session_date": date_src == "auto",
        },
        "laps":   lap_summaries,
        # v21.34 — Channel-role-assignment registry-driven. We build a
        # flat list of available channels from the parsed track (mirrors
        # what the Coach will later present as DATA.extras) and a
        # pattern-based suggestion per role. The picker UI renders these
        # so the user can confirm/override before saving.
        "available_channels": build_available_extras(track),
        # Pickled full track + laps for the save step (avoid re-parsing)
        "track_pickle": pickle.dumps((track, laps), protocol=pickle.HIGHEST_PROTOCOL),
    }
    with PENDING_LOCK:
        PENDING_SESSIONS[pending_id] = pending
    return pending_id


def step2_save_session(pending_id: str, form: dict,
                       user_id: Optional[int] = None,
                       request_ctx: Optional[Dict[str, Any]] = None) -> str:
    """Persist the pending session + the ONE selected lap. Returns the
    session id. Each session contains exactly one lap (UI invariant)."""
    with PENDING_LOCK:
        pending = PENDING_SESSIONS.pop(pending_id, None)
    if pending is None:
        raise ValueError("Upload-Vorgang abgelaufen oder nicht gefunden. "
                         "Bitte neu hochladen.")

    selected_raw = form.get("lap")
    # Form may deliver str or list[str] — normalise to a single int
    if isinstance(selected_raw, list):
        if not selected_raw:
            selected_raw = None
        else:
            selected_raw = selected_raw[0]
    if not selected_raw:
        raise ValueError("Bitte eine Runde auswählen.")
    try:
        selected_num = int(selected_raw)
    except ValueError:
        raise ValueError("Ungültige Lap-Nummer in der Auswahl.")

    # Allow user to override metadata at the save step
    driver = (form.get("driver") or pending["driver"]).strip()
    bike   = (form.get("bike")   or pending["bike"]).strip()
    track_name = (form.get("track") or pending["track"]).strip()
    # v22.2 — if a session already exists with a case-insensitively matching
    # track name, take that one verbatim. Keeps "Hockenheim" / "hockenheim" /
    # "HOCKENHEIM" from forking into three filter-dropdown entries.
    track_name = AppState.db.canonical_track_name(track_name)
    session_date = (form.get("session_date") or pending["session_date"]).strip()
    notes  = (form.get("notes")  or pending["notes"]).strip()

    track, laps = pickle.loads(pending["track_pickle"])
    laps_by_num = {lp["lap_index"]: lp for lp in laps}
    picker_duration_by_num = {
        s["lap_number"]: float(s["duration_s"]) for s in pending["laps"]
    }

    if selected_num not in laps_by_num:
        valid_nums = sorted(laps_by_num.keys())
        raise ValueError(
            f"Ungültige Lap-Nummer: {selected_num}. "
            f"Verfügbar: {', '.join(map(str, valid_nums))}"
        )

    effective_user_id = user_id if user_id is not None else pending.get("user_id")
    session_id = AppState.db.create_session(
        original_filename=pending["original_filename"],
        file_path=pending["file_path"],
        user_id=effective_user_id,
        driver=driver, bike=bike, track=track_name,
        session_date=session_date, notes=notes,
        format=pending["format"],
    )

    # Extract + persist the single selected lap
    lp_meta = laps_by_num[selected_num]
    lp_data = extract_lap_data(track, lp_meta)
    duration = picker_duration_by_num[selected_num]

    # v21.34 — Channel-role assignment from the step 2 form. Fields are
    # named "role_<role_id>" and carry either a channel id from the
    # available_channels list or an empty value (= no assignment).
    # Sanitise against the actual extracted extras so we don't store ids
    # that disappeared between step 1 and step 2 (shouldn't happen, but
    # we're being defensive).
    raw_roles = {}
    for r in CHANNEL_ROLES:
        v = form.get(f"role_{r['id']}")
        if isinstance(v, list):
            v = v[0] if v else ""
        if v:
            raw_roles[r["id"]] = v
    available_ids = [c["id"] for c in
                     build_available_extras(track, lap_data=lp_data)]
    role_assignment = sanitise_assignment(raw_roles, available_ids)
    if role_assignment:
        lp_data["channel_roles"] = role_assignment

    AppState.db.add_lap(session_id, selected_num, duration, lp_data)

    # Audit log: session upload completed
    try:
        ctx = request_ctx or {}
        AppState.db.add_event(
            kind="upload_session",
            user_id=effective_user_id,
            user_email=ctx.get("user_email", ""),
            ip_address=ctx.get("ip_address", ""),
            detail=(f"lap {selected_num} ({fmt_seconds(duration)}) — "
                    f"{track_name or '?'} — {pending['original_filename']}"),
            file_path=pending["file_path"],
        )
    except Exception as e:
        sys.stderr.write(f"[event-log] failed: {e}\n")

    return session_id


# ---------- HTTP handler ----------------------------------------------------

class WebHandler(BaseHTTPRequestHandler):
    server_version = "LapCompare/2.0"

    # v23.3 — Read/write timeout on the socket. Without this, a client that
    # opens a connection and then sends the request slowly (or not at all —
    # flaky mobile networks, health-check pingers, port scanners) blocks
    # this thread in self.rfile.readline() forever. BaseHTTPRequestHandler
    # applies this via socket.settimeout() in setup() and already handles
    # the resulting socket.timeout cleanly (closes the connection). 30s is
    # generous for real clients but short enough that stalled connections
    # don't accumulate.
    timeout = 30

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s - %s\n" % (
            self.log_date_time_string(),
            self.client_address[0],
            fmt % args,
        ))

    # --- v22.1: request-level debug logging
    #
    # We hook the per-request entry point (handle_one_request) so we wrap
    # exactly one request, regardless of HTTP keep-alive reuse of the
    # connection. send_response_only() is the lowest-level point where
    # Python's BaseHTTPRequestHandler writes the status line; overriding
    # it lets us capture the status code without touching every handler.
    # If a handler calls send_error() instead, that funnels through
    # send_response → send_response_only too, so we still see it.
    #
    # The "duration" we report is wall-clock time from "request line read"
    # to "handler returned" — i.e. it includes parsing, DB work, and
    # writing the response body. Good enough for "is this slow?" triage.

    def send_response_only(self, code, message=None):
        # Stash the status code so handle_one_request can log it. Use
        # int() defensively because code may be an http.HTTPStatus.
        try:
            self._req_status = int(code)
        except Exception:
            self._req_status = 0
        return super().send_response_only(code, message)

    def handle_one_request(self):
        if not debuglog.is_enabled():
            return super().handle_one_request()
        import time as _t
        t0 = _t.monotonic()
        self._req_status = 0
        try:
            super().handle_one_request()
        finally:
            # parse_request() may have failed and never set self.command —
            # in that case we still want to log "something happened" with
            # whatever we have. Skip empty/aborted reads (e.g. keep-alive
            # idle close) — those have no command and a 0 status.
            method = getattr(self, "command", None) or ""
            path = getattr(self, "path", None) or ""
            if not method and self._req_status == 0:
                return
            # Resolve user from the auth cookie. Wrap in try/except —
            # the request may be malformed and self.headers None.
            try:
                ctx = self._request_ctx()
            except Exception:
                ctx = {}
            # HTTP Referer (header name historically misspelled — that's the
            # standard). Same defensive try/except: parse-error can leave
            # self.headers None. None/"" is dropped by debuglog.log().
            try:
                referer = self.headers.get("Referer") if self.headers else None
            except Exception:
                referer = None
            dur_ms = int((_t.monotonic() - t0) * 1000)
            debuglog.log(
                "req",
                method=method,
                path=path,
                status=self._req_status,
                dur_ms=dur_ms,
                **debuglog.fields_from_ctx(ctx),
                referer=referer,
            )

    # --- GET dispatch
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._page_landing()
        if path == "/favicon.ico":
            return self._no_content()

        # v21.46 — Static assets aus webapp/ (z.B. speed_chart.js).
        # Whitelist nur .js/.css/.svg/.png, kein Path-Traversal.
        m = re.match(r"^/static/([A-Za-z0-9_./-]+)$", path)
        if m:
            return self._serve_static(m.group(1))
        if path == "/compare" or path == "/compare/":
            return self._page_compare(qs)
        if path == "/login" or path == "/login/":
            return self._page_login(qs)
        if path == "/register" or path == "/register/":
            return self._page_register(qs)
        if path == "/verify" or path == "/verify/":
            return self._page_verify_email(qs)
        if path == "/impressum" or path == "/impressum/":
            return self._page_legal("impressum.html")
        if path == "/datenschutz" or path == "/datenschutz/":
            return self._page_legal("datenschutz.html")

        if path == "/sessions" or path == "/sessions/":
            return self._page_sessions_list(qs)
        if path == "/sessions/upload" or path == "/sessions/upload/":
            return self._page_session_upload_form(qs)

        # v23.2 — Globale Bestzeiten je Strecke (über alle Fahrer)
        if path == "/records" or path == "/records/":
            return self._page_records(qs)

        # v22.12 — Profilverwaltung
        if path == "/profile" or path == "/profile/":
            return self._page_profile(qs)
        m = re.match(r"^/profile/image/([A-Za-z0-9._-]+)$", path)
        if m:
            return self._serve_profile_image(m.group(1))
        # v23.0 — Öffentliche Profilansicht (read-only). Klickbar gemacht
        # über den Owner-Link in der Rundenliste. Ganz bewusst nach
        # /profile/image/ einsortiert: der Image-Pfad-Regex matcht zuerst
        # und schluckt nur Filenames mit Punkt; reine Ziffern landen hier.
        m = re.match(r"^/profile/(\d+)/?$", path)
        if m:
            return self._page_public_profile(int(m.group(1)))

        if path == "/analyze" or path == "/analyze/":
            return self._page_analyze_form(qs)

        # v20.3: AI Analyse und Coach SPA
        if path == "/coach" or path == "/coach/":
            return self._page_coach_form(qs)

        if path == "/admin" or path == "/admin/":
            return self._page_admin_artefacts(qs)

        # v21.7 — admin downloads the original uploaded file for an event
        m = re.match(r"^/admin/event/(\d+)/file/?$", path)
        if m:
            return self._handle_admin_event_download(int(m.group(1)))

        # v22.11 — admin-only reverse IP lookup (clickable IPs in /admin tabs)
        if path == "/admin/ip-lookup" or path == "/admin/ip-lookup/":
            return self._handle_admin_ip_lookup(qs)

        m = re.match(r"^/analysis/([0-9a-f-]{36})/?$", path)
        if m:
            return self._serve_analysis(m.group(1))

        m = re.match(r"^/report/([0-9a-f-]{36})/?$", path)
        if m:
            return self._serve_report(m.group(1), download=False)
        m = re.match(r"^/download/([0-9a-f-]{36})/?$", path)
        if m:
            return self._serve_report(m.group(1), download=True)

        if path == "/api/distinct":
            return self._api_distinct()
        if path == "/api/laps":
            return self._api_laps(qs)
        if path == "/api/analyze":
            return self._api_analyze(qs)
        if path == "/api/channel-roles-registry":
            # v22.3 — Static registry shape for the lap-picker dots.
            return self._api_channel_roles_registry()

        # v21.35 — Admin: read channel-role assignment for one lap.
        m = re.match(r"^/api/laps/(\d+)/channel-roles/?$", path)
        if m:
            return self._api_lap_channel_roles_get(int(m.group(1)))

        self._send_text(HTTPStatus.NOT_FOUND, "404 Not Found")

    # --- POST dispatch
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/login":
            return self._handle_login()
        if path == "/logout":
            return self._handle_logout()
        if path == "/register":
            return self._handle_register()
        if path == "/register/resend":
            return self._handle_resend_verification()
        if path == "/api/adhoc/laps":
            return self._api_adhoc_laps()

        if path == "/compare":
            return self._handle_compare()
        if path == "/sessions/upload":
            return self._handle_session_upload_step1()
        if path == "/sessions/save":
            return self._handle_session_save_step2()
        if path == "/analyze":
            return self._handle_analyze()
        if path == "/coach":
            return self._handle_coach()
        if path == "/api/analyze/upload":
            return self._api_analyze_upload()

        # v22.12 — Profilverwaltung POST-Endpunkte. Alle erwarten einen
        # eingeloggten User; der Handler redirected sonst auf /login.
        if path == "/profile/save":
            return self._handle_profile_save()
        if path == "/profile/bike/add":
            return self._handle_bike_add()
        m = re.match(r"^/profile/bike/(\d+)/edit/?$", path)
        if m:
            return self._handle_bike_edit(int(m.group(1)))
        m = re.match(r"^/profile/bike/(\d+)/delete/?$", path)
        if m:
            return self._handle_bike_delete(int(m.group(1)))
        m = re.match(r"^/profile/bike/(\d+)/set-current/?$", path)
        if m:
            return self._handle_bike_set_current(int(m.group(1)))

        m = re.match(r"^/laps/(\d+)/delete/?$", path)
        if m:
            return self._handle_lap_delete(int(m.group(1)))

        m = re.match(r"^/sessions/([0-9a-f-]{36})/edit/?$", path)
        if m:
            return self._handle_session_edit(m.group(1))

        # v21.35 — Admin: update channel-role assignment for one lap.
        m = re.match(r"^/api/laps/(\d+)/channel-roles/?$", path)
        if m:
            return self._api_lap_channel_roles_post(int(m.group(1)))

        m = re.match(r"^/admin/(report|analysis)/([0-9a-f-]{36})/delete/?$", path)
        if m:
            return self._handle_admin_delete(m.group(1), m.group(2))

        m = re.match(r"^/admin/event/(\d+)/delete/?$", path)
        if m:
            return self._handle_admin_event_delete(int(m.group(1)))

        self._send_text(HTTPStatus.NOT_FOUND, "404 Not Found")

    # --- Auth helpers
    def _current_user(self):
        """Return current user dict {id, email, is_admin} or None."""
        cookies = _parse_cookies(self.headers.get("Cookie", ""))
        token = cookies.get(AUTH_COOKIE_NAME)
        result = _verify_token(token) if token else None
        if not result:
            return None
        uid, _exp = result
        user = AppState.db.get_user(uid)
        if not user:
            return None
        return {"id": user["id"], "email": user["email"],
                "is_admin": bool(user["is_admin"])}

    def _client_ip(self) -> str:
        """Return the client IP. Honour X-Forwarded-For if it's set, but
        only take the first IP (the original client). Otherwise fall back
        to the socket peer address."""
        xff = self.headers.get("X-Forwarded-For", "").strip()
        if xff:
            # Could be "client, proxy1, proxy2" — take the first
            return xff.split(",")[0].strip()
        try:
            return self.client_address[0]
        except Exception:
            return ""

    def _request_ctx(self) -> Dict[str, Any]:
        """Return a dict with the requester's user info and IP, used to
        annotate events and sidecar metadata."""
        user = self._current_user()
        return {
            "user_id":    (user["id"]    if user else None),
            "user_email": (user["email"] if user else ""),
            "ip_address": self._client_ip(),
        }

    def _set_auth_cookie(self, user_id: int):
        """Add Set-Cookie header (caller still needs to send the response)."""
        exp = int(_time.time()) + AUTH_TTL_SECONDS
        token = _sign_token(user_id, exp)
        self.send_header(
            "Set-Cookie",
            f"{AUTH_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={AUTH_TTL_SECONDS}",
        )

    def _clear_auth_cookie(self):
        self.send_header(
            "Set-Cookie",
            f"{AUTH_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )

    # --- Pages
    # --- Login / Logout
    def _page_login(self, qs):
        user = self._current_user()
        if user:
            # Already logged in → bounce to sessions
            return self._redirect("/sessions")
        error = qs.get("error", [""])[0]
        unverified_email = qs.get("unverified", [""])[0]
        resent = bool(qs.get("resent"))
        next_url = qs.get("next", ["/sessions"])[0]
        # Sanitise next_url to local paths only
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/sessions"
        if unverified_email:
            error_html = (
                '<div class="error-banner active">⚠  '
                'Diese E-Mail-Adresse ist noch nicht bestätigt. '
                'Bitte schau in dein Postfach — oder '
                '<form method="POST" action="/register/resend" '
                'style="display:inline">'
                f'<input type="hidden" name="email" '
                f'value="{html.escape(unverified_email)}">'
                '<button type="submit" class="link-btn">'
                'Mail erneut senden</button></form>.'
                '</div>'
            )
        elif error:
            error_html = (f'<div class="error-banner active">⚠  '
                          f'{html.escape(error)}</div>')
        else:
            error_html = ""
        info_html = (
            '<div class="info-banner active">'
            'Bestätigungsmail wurde erneut gesendet — bitte Postfach '
            '(auch Spam) prüfen.</div>'
        ) if resent and not error_html else ""
        content = render_template(
            "login.html",
            HEADER=build_header_html(None, "/login"),
            ERROR_HTML=error_html,
            INFO_HTML=info_html,
            NEXT_URL=html.escape(next_url),
        )
        self._send_html(content)

    def _handle_login(self):
        try:
            form = parse_form(self)
        except Exception as e:
            return self._redirect("/login?error=" + quote(f"Fehler: {e}"))
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""
        next_url = form.get("next") or "/sessions"
        if not isinstance(next_url, str) or not next_url.startswith("/") \
                or next_url.startswith("//"):
            next_url = "/sessions"
        ip = self._client_ip()
        try:
            user = AppState.db.verify_login(email, password)
        except EmailNotVerifiedError as e:
            debuglog.log("auth.login.unverified", level="warn",
                         user=email, ip=ip)
            return self._redirect(
                "/login?unverified=" + quote(e.email)
                + "&next=" + quote(next_url))
        if not user:
            # Record failed attempt with the e-mail that was tried (no pw stored)
            try:
                AppState.db.add_event(
                    kind="login_fail",
                    user_email=email,
                    ip_address=ip,
                    detail="bad credentials",
                )
            except Exception:
                pass
            debuglog.log("auth.login.fail", level="warn",
                         user=email, ip=ip, reason="bad_credentials")
            return self._redirect("/login?error=" + quote(
                "E-Mail oder Passwort ungültig.")
                + "&next=" + quote(next_url))
        # Successful login — record event before setting cookie
        try:
            AppState.db.add_event(
                kind="login",
                user_id=user["id"],
                user_email=user["email"],
                ip_address=ip,
                detail=f"next={next_url}",
            )
        except Exception:
            pass
        debuglog.log("auth.login.ok",
                     user=user["email"], ip=ip,
                     admin=bool(user.get("is_admin")),
                     next=next_url)
        # Set cookie and redirect
        self.send_response(HTTPStatus.SEE_OTHER)
        self._set_auth_cookie(user["id"])
        self.send_header("Location", next_url)
        self.end_headers()

    def _handle_logout(self):
        # Log who logged out (the cookie is still valid at this point)
        try:
            u = self._current_user()
        except Exception:
            u = None
        debuglog.log("auth.logout",
                     user=(u["email"] if u else None),
                     ip=self._client_ip())
        self.send_response(HTTPStatus.SEE_OTHER)
        self._clear_auth_cookie()
        self.send_header("Location", "/")
        self.end_headers()

    # --- Registration / e-mail verification (v23.4) ------------------------

    def _page_legal(self, template_name: str):
        """v23.9 — Impressum / Datenschutzerklärung. Öffentlich, kein Login
        nötig. Inhalte kommen aus dem Template + webapp/legal_data.js."""
        user = self._current_user()
        content = render_template(
            template_name,
            HEADER=build_header_html(user, "/" + template_name.split(".")[0]),
        )
        self._send_html(content)

    def _verify_url_for(self, token: str) -> str:
        return f"{AppState.base_url}/verify?token={quote(token)}"

    def _api_adhoc_laps(self):
        """v23.12 — POST /api/adhoc/laps (multipart, Feld 'file').
        Phase 1 des Ad-hoc-Uploads: Datei einlagern + parsen, Rundenliste
        als JSON zurück. Die UI zeigt daraus die Auswahl-Liste; die
        eigentliche Runden-Wahl kommt später als 'adhoc_token' + 'lap'
        beim regulären Formular-POST an."""
        try:
            form = parse_form(self)
        except UploadTooLarge as e:
            return self._send_json({"ok": False, "error": str(e)},
                                   status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except Exception as e:
            return self._send_json({"ok": False, "error": f"Upload-Fehler: {e}"},
                                   status=HTTPStatus.BAD_REQUEST)
        if "file" not in form:
            return self._send_json({"ok": False,
                                    "error": "Keine Datei hochgeladen"},
                                   status=HTTPStatus.BAD_REQUEST)
        fname, fdata = form["file"]
        try:
            token, laps = stash_adhoc_upload(
                fname, fdata, request_ctx=self._request_ctx())
        except ValueError as e:
            debuglog.log("action.adhoc.stash.error", level="warn",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         filename=fname, error=str(e))
            return self._send_json({"ok": False, "error": str(e)},
                                   status=HTTPStatus.BAD_REQUEST)
        except Exception as e:
            sys.stderr.write("=== /api/adhoc/laps error ===\n")
            traceback.print_exc(file=sys.stderr)
            return self._send_json(
                {"ok": False, "error": f"{type(e).__name__}: {e}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR)
        debuglog.log("action.adhoc.stash.ok",
                     **debuglog.fields_from_ctx(self._request_ctx()),
                     filename=fname, token=token, lap_count=len(laps))
        # Zeiten fürs UI vorformatieren — ein Formatter, überall dieselbe
        # Darstellung.
        for lp in laps:
            lp["duration_fmt"] = fmt_seconds(lp["duration_s"])
        return self._send_json({
            "ok": True,
            "token": token,
            "laps": laps,
            "fastest_lap_number": laps[0]["lap_number"] if laps else None,
        })

    def _page_register(self, qs):
        user = self._current_user()
        if user:
            return self._redirect("/sessions")
        if not AppState.registration_enabled:
            return self._send_text(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "Registrierung ist derzeit nicht verfügbar. Bitte den "
                "Admin kontaktieren.")
        error = qs.get("error", [""])[0]
        content = render_template(
            "register.html",
            HEADER=build_header_html(None, "/register"),
            ERROR_HTML=(f'<div class="error-banner active">⚠  '
                        f'{html.escape(error)}</div>') if error else "",
        )
        self._send_html(content)

    def _page_register_sent(self, email: str):
        content = render_template(
            "register_sent.html",
            HEADER=build_header_html(None, "/register"),
            EMAIL=html.escape(email),
        )
        self._send_html(content)

    def _handle_register(self):
        if not AppState.registration_enabled:
            return self._send_text(HTTPStatus.SERVICE_UNAVAILABLE,
                                   "Registrierung ist derzeit nicht verfügbar.")
        try:
            form = parse_form(self)
        except Exception as e:
            return self._redirect("/register?error=" + quote(f"Fehler: {e}"))
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""
        password2 = form.get("password2") or ""
        ip = self._client_ip()
        if password != password2:
            return self._redirect("/register?error=" + quote(
                "Passwörter stimmen nicht überein."))
        try:
            user_id, token = AppState.db.create_pending_user(
                email=email, password=password)
        except ValueError as e:
            return self._redirect("/register?error=" + quote(str(e)))
        try:
            smtp_cfg = mailer.smtp_config_from_app_config(AppState.config)
            mailer.send_verification_email(
                smtp_cfg, to_email=email,
                verify_url=self._verify_url_for(token))
        except (mailer.MailerNotConfigured, mailer.MailSendError) as e:
            # The account row already exists at this point. Rather than
            # leaving an unreachable half-account (user can never verify,
            # never told why), delete it and surface a clean error — the
            # e-mail is free again for a retry once SMTP is fixed.
            debuglog.log("auth.register.mail_failed", level="error",
                         user=email, ip=ip, error=str(e))
            try:
                AppState.db.delete_user(user_id)
            except Exception:
                pass
            return self._redirect("/register?error=" + quote(
                "Bestätigungsmail konnte nicht versendet werden. "
                "Bitte später erneut versuchen oder den Admin kontaktieren."))
        try:
            AppState.db.add_event(kind="register", user_id=user_id,
                                  user_email=email, ip_address=ip)
        except Exception:
            pass
        debuglog.log("auth.register", user=email, ip=ip)
        return self._page_register_sent(email)

    def _handle_resend_verification(self):
        # Always redirect back with a generic "sent" confirmation regardless
        # of whether the e-mail exists or is already verified — avoids
        # leaking account existence to anyone poking this endpoint.
        try:
            form = parse_form(self)
        except Exception:
            return self._redirect("/login")
        email = (form.get("email") or "").strip().lower()
        rec = AppState.db.get_user_by_email(email) if email else None
        if rec and not rec["email_verified"] and AppState.registration_enabled:
            # Simple cooldown: skip actually resending if the last mail
            # went out less than 60s ago, but still show the same
            # confirmation (no signal to the caller either way).
            sent_at = rec.get("verify_sent_at")
            too_soon = False
            if sent_at:
                try:
                    last = datetime.fromisoformat(sent_at)
                    too_soon = (datetime.now(timezone.utc) - last
                               ).total_seconds() < 60
                except Exception:
                    too_soon = False
            if not too_soon:
                token = AppState.db.resend_verify_token(rec["id"])
                if token:
                    try:
                        smtp_cfg = mailer.smtp_config_from_app_config(
                            AppState.config)
                        mailer.send_verification_email(
                            smtp_cfg, to_email=email,
                            verify_url=self._verify_url_for(token))
                    except (mailer.MailerNotConfigured,
                           mailer.MailSendError) as e:
                        debuglog.log("auth.resend.mail_failed",
                                     level="error", user=email, error=str(e))
        return self._redirect("/login?resent=1")

    def _page_verify_email(self, qs):
        token = qs.get("token", [""])[0]
        rec = AppState.db.get_user_by_verify_token(token) if token else None
        if not rec:
            return self._redirect("/login?error=" + quote(
                "Bestätigungslink ungültig. Bitte neu registrieren oder "
                "eine neue Mail anfordern."))
        expires = rec.get("verify_token_expires")
        try:
            expired = expires is None or float(expires) < _time.time()
        except (TypeError, ValueError):
            expired = True
        if expired:
            return self._redirect("/login?unverified=" + quote(rec["email"]))
        AppState.db.confirm_email(rec["id"])
        try:
            AppState.db.add_event(kind="email_verified", user_id=rec["id"],
                                  user_email=rec["email"],
                                  ip_address=self._client_ip())
        except Exception:
            pass
        debuglog.log("auth.email_verified", user=rec["email"])
        # Auto-login straight into the freshly verified account.
        self.send_response(HTTPStatus.SEE_OTHER)
        self._set_auth_cookie(rec["id"])
        self.send_header("Location", "/sessions?welcome=1")
        self.end_headers()

    def _page_landing(self):
        """Main entry page with cards for all major sections."""
        user = self._current_user()
        # Admin card visibility hint
        admin_card = ""
        if user and user.get("is_admin"):
            admin_card = (
                '<a href="/admin" class="hub-card admin">'
                '  <div class="hub-card-eyebrow">Admin</div>'
                '  <div class="hub-card-title">VERWALTUNG</div>'
                '  <div class="hub-card-desc">'
                '    Übersicht aller gerenderten Reports und Analysen. '
                '    Einträge öffnen oder bereinigen.'
                '  </div>'
                '  <div class="hub-card-arrow">→</div>'
                '</a>'
            )
        content = render_template(
            "landing.html",
            HEADER=build_header_html(user, "/"),
            NAV_USER=build_user_nav_snippet(user),
            NAV_ADMIN=build_admin_nav_snippet(user, "/"),
            ADMIN_CARD=admin_card,
        )
        self._send_html(content)

    # === v22.12 — Profile (Fahrer + Motorräder) ============================
    # Eine Profilseite pro eingeloggtem User. Fahrername + optionales
    # Fahrerfoto + n Motorräder (jeweils Name + optionales Bild, eines
    # davon "aktuell"). Beim Hochladen einer Session werden Fahrername und
    # aktuelles Bike als Defaults in die Upload-Maske eingesetzt.
    #
    # Routes:
    #   GET  /profile                       → Seite (Redirect /login wenn anonym)
    #   POST /profile/save                  → Fahrername + optionales Foto
    #   POST /profile/bike/add              → neues Motorrad anlegen
    #   POST /profile/bike/<id>/edit        → Motorrad-Namen/Bild ändern
    #   POST /profile/bike/<id>/delete      → Motorrad entfernen
    #   POST /profile/bike/<id>/set-current → Motorrad als aktuell markieren
    #   GET  /profile/image/<filename>      → ein gespeichertes Bild ausliefern
    #
    # Bilder liegen auf Disk unter <data_dir>/profile_images/ — die DB
    # speichert nur den Dateinamen (kein Pfad). Read-Path validiert den
    # Namen gegen ein striktes UUID-Schema.

    def _redirect_to_login(self, next_path: str):
        return self._redirect("/login?next=" + quote(next_path))

    def _serve_profile_image(self, filename: str):
        """GET /profile/image/<filename> — public read.

        Begründung public: Bilder sind keine Geheimnisse (kein Auth-Check
        nötig), und nicht-public würde den Image-Tag im HTML brechen wenn
        ein Admin/anderer User ein Profil anschaut. Schutz ist
        Path-Traversal + striktes Namensschema."""
        if not _PROFILE_IMG_NAME_RE.match(filename):
            return self._send_text(HTTPStatus.NOT_FOUND, "Not found")
        fp = AppState.profile_images_dir / filename
        if not _path_is_inside(fp, AppState.profile_images_dir):
            return self._send_text(HTTPStatus.NOT_FOUND, "Not found")
        try:
            body = fp.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            return self._send_text(HTTPStatus.NOT_FOUND, "Not found")
        ext = filename.rsplit(".", 1)[-1].lower()
        ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
              "png": "image/png",  "webp": "image/webp"}.get(ext, "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def _page_profile(self, qs):
        user = self._current_user()
        if not user:
            return self._redirect_to_login("/profile")

        profile = AppState.db.get_profile(user["id"])
        bikes = AppState.db.list_bikes(user["id"])

        # Flash- und Fehler-Banner aus dem Query-String
        flash_html = ""
        if "saved" in qs:
            flash_html = '<div class="flash">PROFIL GESPEICHERT</div>'
        elif "bike_added" in qs:
            flash_html = '<div class="flash">MOTORRAD HINZUGEFÜGT</div>'
        elif "bike_updated" in qs:
            flash_html = '<div class="flash">MOTORRAD GEÄNDERT</div>'
        elif "bike_deleted" in qs:
            flash_html = '<div class="flash">MOTORRAD GELÖSCHT</div>'
        elif "bike_set_current" in qs:
            flash_html = '<div class="flash">AKTUELLES MOTORRAD AKTUALISIERT</div>'
        elif "error" in qs:
            flash_html = (f'<div class="flash error">⚠  '
                          f'{html.escape(qs["error"][0])}</div>')

        # Fahrerfoto Vorschau
        driver_img_html = ""
        if profile.get("image_path"):
            driver_img_html = (
                f'<img src="/profile/image/{html.escape(profile["image_path"])}" '
                f'  alt="Fahrerfoto" class="profile-img">'
            )
        else:
            driver_img_html = '<div class="profile-img placeholder">F</div>'

        # Bike-Cards
        if not bikes:
            bikes_html = (
                '<div class="empty-state">'
                '  <div class="icon">∅</div>'
                '  <div class="label">NOCH KEINE MOTORRÄDER</div>'
                '  <div class="hint">'
                '    Trage unten ein Motorrad ein. Das erste wird automatisch '
                '    als "aktuell" markiert.'
                '  </div>'
                '</div>'
            )
        else:
            cards = []
            for b in bikes:
                bid = int(b["id"])
                name_esc = html.escape(b["name"])
                # Bild oder Platzhalter
                if b.get("image_path"):
                    img_html = (
                        f'<img src="/profile/image/{html.escape(b["image_path"])}" '
                        f'  alt="{name_esc}" class="bike-img">'
                    )
                else:
                    img_html = (
                        '<div class="bike-img placeholder">'
                        '  <span>—</span>'
                        '</div>'
                    )
                # Current-Badge
                current_badge = ""
                set_current_btn = ""
                row_class = "bike-card"
                if b.get("is_current"):
                    current_badge = '<span class="current-badge">AKTUELL</span>'
                    row_class += " is-current"
                else:
                    set_current_btn = (
                        f'<form method="POST" '
                        f'  action="/profile/bike/{bid}/set-current" '
                        f'  style="display:inline">'
                        f'  <button type="submit" class="btn small secondary">'
                        f'    ALS AKTUELL MARKIEREN</button>'
                        f'</form>'
                    )
                cards.append(
                    f'<div class="{row_class}" data-bike-id="{bid}">'
                    f'  <div class="bike-img-wrap">{img_html}</div>'
                    f'  <div class="bike-meta">'
                    f'    <div class="bike-name">{name_esc} {current_badge}</div>'
                    f'    <form method="POST" '
                    f'      action="/profile/bike/{bid}/edit" '
                    f'      enctype="multipart/form-data" '
                    f'      class="bike-edit-form">'
                    f'      <div class="bike-edit-row">'
                    f'        <input type="text" name="name" '
                    f'          value="{name_esc}" maxlength="200" required>'
                    f'        <input type="file" name="image" '
                    f'          accept=".jpg,.jpeg,.png,.webp">'
                    f'        <button type="submit" class="btn small">'
                    f'          SPEICHERN</button>'
                    f'      </div>'
                    f'    </form>'
                    f'    <div class="bike-actions">'
                    f'      {set_current_btn}'
                    f'      <form method="POST" '
                    f'        action="/profile/bike/{bid}/delete" '
                    f'        onsubmit="return confirm(\'Motorrad löschen?\')" '
                    f'        style="display:inline">'
                    f'        <button type="submit" class="btn small danger">'
                    f'          LÖSCHEN</button>'
                    f'      </form>'
                    f'    </div>'
                    f'  </div>'
                    '</div>'
                )
            bikes_html = '<div class="bikes-grid">' + "".join(cards) + "</div>"

        # Anzahl eigener Runden — für den "Eigene Runden"-Link Counter
        try:
            all_laps = AppState.db.list_all_laps_flat()
            my_lap_count = sum(1 for lp in all_laps
                               if lp.get("user_id") == user["id"])
        except Exception:
            my_lap_count = 0

        # v23.1 — Bestzeiten pro Strecke. Selbe Anzeige wie auf der
        # öffentlichen Profilseite, damit der Owner sieht was andere
        # sehen.
        # v23.2 — Pokal-Icons für Runden die global Top-3 sind. Der
        # Owner sieht so direkt welche seiner Bestzeiten auch im
        # globalen Ranking weit oben sind.
        best_laps = AppState.db.best_lap_per_track_for_user(user["id"])
        global_top3 = AppState.db.global_top_n_per_track(3)
        medals = medal_map_from_top_n(global_top3)
        best_laps_html = render_best_laps_html(best_laps, medals=medals)

        content = render_template(
            "profile.html",
            HEADER=build_header_html(user, "/profile"),
            FLASH=flash_html,
            EMAIL=html.escape(user["email"]),
            DRIVER_NAME=html.escape(profile.get("driver_name") or ""),
            DRIVER_IMG=driver_img_html,
            BIKES_HTML=bikes_html,
            BEST_LAPS_HTML=best_laps_html,
            MY_LAP_COUNT=str(my_lap_count),
            NOW=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        self._send_html(content)

    # --- v23.0 — Read-only public profile view -----------------------------
    # Klickbar gemacht über den Owner-Link in der Rundenliste. Funktioniert
    # ohne Login: Nicht-Geheimnisse (Name, Bilder, Bike-Auswahl) eines
    # Users der Runden hochgeladen hat. Keine Edit-Forms, keine Add-
    # Buttons, keine E-Mail-Adresse (Privacy — die E-Mail ist intern,
    # extern reicht der Fahrername; wir fallen auf die E-Mail nur zurück
    # falls der User noch keinen Fahrernamen gesetzt hat — sonst wäre die
    # Seite anonymer Karteileichen).

    def _page_public_profile(self, target_user_id: int):
        target = AppState.db.get_user(target_user_id)
        if not target:
            return self._send_text(HTTPStatus.NOT_FOUND,
                                   "Profil nicht gefunden.")

        viewer = self._current_user()
        # Der eingeloggte Owner sieht oben einen kleinen "Editieren"-Hint,
        # damit klar ist: das ist die externe Sicht auf das eigene Profil.
        is_self = bool(viewer) and viewer["id"] == target_user_id

        profile = AppState.db.get_profile(target_user_id)
        bikes = AppState.db.list_bikes(target_user_id)

        # Anzeige-Name: bevorzugt driver_name, fallback auf den Local-Part
        # der E-Mail (Stefan @ x → "stefan"). Volle E-Mail nie nach aussen.
        display_name = (profile.get("driver_name") or "").strip()
        if not display_name:
            email = target.get("email") or ""
            display_name = email.split("@", 1)[0] if "@" in email else email
        display_name = display_name or f"User #{target_user_id}"

        # Fahrerfoto oder Platzhalter (selbe Optik wie eigene Profilseite)
        if profile.get("image_path"):
            driver_img_html = (
                f'<img src="/profile/image/{html.escape(profile["image_path"])}" '
                f'  alt="Fahrerfoto" class="profile-img">'
            )
        else:
            # Initial des Anzeige-Namens als Platzhalter — persönlicher als
            # immer "F"
            initial = (display_name[:1].upper() if display_name else "?")
            driver_img_html = (
                f'<div class="profile-img placeholder">{html.escape(initial)}</div>'
            )

        # Anzahl Runden dieses Users (= Anzahl Sessions, da 1 Lap/Session)
        try:
            all_laps = AppState.db.list_all_laps_flat()
            lap_count = sum(1 for lp in all_laps
                            if lp.get("user_id") == target_user_id)
        except Exception:
            lap_count = 0

        # Bikes als Galerie (read-only): nur Bild + Name + Aktuell-Badge,
        # keine Edit-Forms, keine Action-Buttons.
        if not bikes:
            bikes_html = (
                '<div class="empty-state">'
                '  <div class="icon">∅</div>'
                '  <div class="label">KEINE MOTORRÄDER HINTERLEGT</div>'
                '  <div class="hint">'
                f'    {html.escape(display_name)} hat noch keine Motorräder '
                '    im Profil eingetragen.'
                '  </div>'
                '</div>'
            )
        else:
            cards = []
            for b in bikes:
                name_esc = html.escape(b["name"])
                if b.get("image_path"):
                    img_html = (
                        f'<img src="/profile/image/{html.escape(b["image_path"])}" '
                        f'  alt="{name_esc}" class="bike-img">'
                    )
                else:
                    img_html = '<div class="bike-img placeholder"><span>—</span></div>'
                current_badge = ""
                row_class = "bike-card"
                if b.get("is_current"):
                    current_badge = '<span class="current-badge">AKTUELL</span>'
                    row_class += " is-current"
                cards.append(
                    f'<div class="{row_class}">'
                    f'  <div class="bike-img-wrap">{img_html}</div>'
                    f'  <div class="bike-meta">'
                    f'    <div class="bike-name">{name_esc} {current_badge}</div>'
                    f'  </div>'
                    '</div>'
                )
            bikes_html = '<div class="bikes-grid">' + "".join(cards) + "</div>"

        # Banner-Hint nur wenn der Owner sich selbst anschaut
        self_hint = ""
        if is_self:
            self_hint = (
                '<div class="self-hint">'
                '  <span>Dies ist die externe Sicht auf dein Profil.</span>'
                '  <a href="/profile">→ EIGENES PROFIL EDITIEREN</a>'
                '</div>'
            )

        # v23.1 — Bestzeiten pro Strecke. Berechnet aus *allen* Runden
        # dieses Users, nicht nur den im DOM gerenderten. Sichtbar für
        # jeden Viewer.
        # v23.2 — Wenn eine dieser Runden global Top-3 auf ihrer Strecke
        # ist, wird das Pokal-Icon mit gerendert (gold/silber/bronze).
        best_laps = AppState.db.best_lap_per_track_for_user(target_user_id)
        global_top3 = AppState.db.global_top_n_per_track(3)
        medals = medal_map_from_top_n(global_top3)
        best_laps_html = render_best_laps_html(best_laps, medals=medals)

        # v23.1 — BUGFIX: Beim Anschauen *fremder* Profilseite blenden wir
        # den Link zur Rundenliste komplett aus. Die Bestzeiten-Tabelle
        # oben deckt das Info-Bedürfnis ab; der Sessions-Filter-Link
        # ("EIGENE RUNDEN") war ohnehin nur self-relevant, und die
        # vorher gezeigte "RUNDEN VON X"-Variante war redundant mit der
        # Bestzeitenliste.
        if is_self:
            laps_link_html = (
                '<a href="/sessions?mine=1" class="my-laps-link">'
                f'  <div>'
                f'    <div class="label">EIGENE RUNDEN ({lap_count})</div>'
                f'    <div class="desc">RUNDENLISTE · GEFILTERT AUF EIGENE</div>'
                f'  </div>'
                '  <div class="arrow">→</div>'
                '</a>'
            )
        else:
            laps_link_html = ""

        content = render_template(
            "profile_public.html",
            HEADER=build_header_html(viewer, f"/profile/{target_user_id}"),
            DISPLAY_NAME=html.escape(display_name),
            DRIVER_IMG=driver_img_html,
            BIKES_HTML=bikes_html,
            BEST_LAPS_HTML=best_laps_html,
            LAP_COUNT=str(lap_count),
            LAPS_LINK=laps_link_html,
            SELF_HINT=self_hint,
            NOW=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        self._send_html(content)

    # --- Profile actions (POST) -------------------------------------------

    def _parse_profile_form(self) -> dict:
        """Wrap parse_multipart with a friendlier error path. Used by all
        five POST endpoints so the error redirects stay consistent."""
        try:
            return parse_multipart(self)
        except UploadTooLarge as e:
            raise ValueError(str(e))
        except Exception as e:
            raise ValueError(f"Upload-Fehler: {e}")

    def _save_optional_image(self, form: dict, field: str) -> Optional[str]:
        """If `form[field]` is a non-empty (filename, bytes) pair, save the
        image and return the stored filename. Returns None if the field is
        absent or empty (the upsert/update helpers treat None as 'do not
        change'). Raises ValueError on invalid format / oversize."""
        if field not in form:
            return None
        val = form[field]
        if not isinstance(val, tuple) or len(val) != 2:
            return None
        fname, fdata = val
        if not fname or not fdata:
            return None
        return save_profile_image(fdata, fname)

    def _handle_profile_save(self):
        user = self._current_user()
        if not user:
            return self._redirect_to_login("/profile")
        try:
            form = self._parse_profile_form()
        except ValueError as e:
            debuglog.log("action.profile.save.error", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         error=str(e))
            return self._redirect("/profile?error=" + quote(str(e)))

        driver_name = (form.get("driver_name") or "").strip()
        if len(driver_name) > 200:
            return self._redirect("/profile?error=" + quote(
                "Fahrername zu lang (max 200 Zeichen)."))

        # Optional: neues Foto hochladen. Nur wenn ein File-Field
        # tatsächlich Bytes enthält, ersetzen wir das alte Bild — eine
        # leere File-Input lässt das bestehende Bild unberührt.
        try:
            new_img = self._save_optional_image(form, "image")
        except ValueError as e:
            debuglog.log("action.profile.save.error", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         error=str(e))
            return self._redirect("/profile?error=" + quote(str(e)))

        old_profile = AppState.db.get_profile(user["id"])
        AppState.db.upsert_profile(user["id"], driver_name=driver_name,
                                   image_path=new_img)
        # Altes Bild auf Disk aufräumen wenn ersetzt
        if new_img and old_profile.get("image_path") \
                and old_profile["image_path"] != new_img:
            delete_profile_image(old_profile["image_path"])

        debuglog.log("action.profile.save.ok",
                     user=user["email"], ip=self._client_ip(),
                     driver_name=driver_name,
                     image_changed=bool(new_img))
        return self._redirect("/profile?saved=1")

    def _handle_bike_add(self):
        user = self._current_user()
        if not user:
            return self._redirect_to_login("/profile")
        try:
            form = self._parse_profile_form()
        except ValueError as e:
            debuglog.log("action.profile.bike.add.error", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         error=str(e))
            return self._redirect("/profile?error=" + quote(str(e)))

        name = (form.get("name") or "").strip()
        if not name:
            return self._redirect("/profile?error=" + quote(
                "Bitte einen Bike-Namen eingeben."))
        is_current = bool(form.get("is_current"))

        try:
            img = self._save_optional_image(form, "image")
        except ValueError as e:
            debuglog.log("action.profile.bike.add.error", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         error=str(e))
            return self._redirect("/profile?error=" + quote(str(e)))

        try:
            bid = AppState.db.add_bike(user["id"], name=name,
                                       image_path=img or "",
                                       is_current=is_current)
        except ValueError as e:
            if img:
                delete_profile_image(img)
            return self._redirect("/profile?error=" + quote(str(e)))

        debuglog.log("action.profile.bike.add.ok",
                     user=user["email"], ip=self._client_ip(),
                     bike_id=bid, name=name)
        return self._redirect("/profile?bike_added=1")

    def _handle_bike_edit(self, bike_id: int):
        user = self._current_user()
        if not user:
            return self._redirect_to_login("/profile")
        try:
            form = self._parse_profile_form()
        except ValueError as e:
            return self._redirect("/profile?error=" + quote(str(e)))

        existing = AppState.db.get_bike(bike_id)
        if not existing or existing["user_id"] != user["id"]:
            debuglog.log("action.profile.bike.edit.denied", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         bike_id=bike_id,
                         reason=("notfound" if not existing else "not_owner"))
            return self._redirect("/profile?error=" + quote(
                "Motorrad nicht gefunden."))

        new_name = (form.get("name") or "").strip()
        try:
            new_img = self._save_optional_image(form, "image")
        except ValueError as e:
            return self._redirect("/profile?error=" + quote(str(e)))

        try:
            AppState.db.update_bike(bike_id, user["id"],
                                    name=new_name if new_name else None,
                                    image_path=new_img)
        except ValueError as e:
            if new_img:
                delete_profile_image(new_img)
            return self._redirect("/profile?error=" + quote(str(e)))

        # Altes Bild auf Disk aufräumen wenn ersetzt
        if new_img and existing.get("image_path") \
                and existing["image_path"] != new_img:
            delete_profile_image(existing["image_path"])

        debuglog.log("action.profile.bike.edit.ok",
                     user=user["email"], ip=self._client_ip(),
                     bike_id=bike_id,
                     name_changed=bool(new_name),
                     image_changed=bool(new_img))
        return self._redirect("/profile?bike_updated=1")

    def _handle_bike_delete(self, bike_id: int):
        user = self._current_user()
        if not user:
            return self._redirect_to_login("/profile")
        img_path = AppState.db.delete_bike(bike_id, user["id"])
        if img_path is None:
            debuglog.log("action.profile.bike.delete.denied", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         bike_id=bike_id, reason="notfound_or_not_owner")
            return self._redirect("/profile?error=" + quote(
                "Motorrad nicht gefunden."))
        if img_path:
            delete_profile_image(img_path)
        debuglog.log("action.profile.bike.delete.ok",
                     user=user["email"], ip=self._client_ip(),
                     bike_id=bike_id)
        return self._redirect("/profile?bike_deleted=1")

    def _handle_bike_set_current(self, bike_id: int):
        user = self._current_user()
        if not user:
            return self._redirect_to_login("/profile")
        ok = AppState.db.set_current_bike(bike_id, user["id"])
        if not ok:
            debuglog.log("action.profile.bike.set_current.denied", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         bike_id=bike_id, reason="notfound_or_not_owner")
            return self._redirect("/profile?error=" + quote(
                "Motorrad nicht gefunden."))
        debuglog.log("action.profile.bike.set_current.ok",
                     user=user["email"], ip=self._client_ip(),
                     bike_id=bike_id)
        return self._redirect("/profile?bike_set_current=1")

    def _page_compare(self, qs):
        """GET /compare[?a=<slot>&b=<slot>] — Compare SPA.

        Slot values come in two flavors:
          - integer  ("42")        → library lap_id
          - "ad-<hex>"             → ad-hoc compare upload (parsed once,
                                     pickled into adhoc_dir/compare-<hex>/)

        States:
          - 0 slots: empty SPA (charts are placeholders)
          - 1 slot:  half-state (toolbar shows it, charts still placeholders)
          - 2 slots: full compare render
        """
        user = self._current_user()

        def _norm_slot(s):
            s = (s or "").strip()
            if not s:
                return ""
            if is_adhoc_slot(s):
                return s
            # Try as integer
            try:
                n = int(s)
                return str(n) if n > 0 else ""
            except ValueError:
                return ""

        a_slot = _norm_slot(qs.get("a", [""])[0])
        b_slot = _norm_slot(qs.get("b", [""])[0])

        # For audit/UI we still want a numeric ID where possible
        def _id_for_url(slot):
            if not slot:
                return ""
            return slot  # toolbar uses this as the data-*-lap-id attr

        # Full compare render
        if a_slot and b_slot:
            try:
                track_a, lap_a_meta, lap_a_data = resolve_compare_slot(
                    a_slot, self._request_ctx(),
                )
                track_b, lap_b_meta, lap_b_data = resolve_compare_slot(
                    b_slot, self._request_ctx(),
                )
                aligned = align_laps(lap_a_data, lap_b_data)
                zones = hot_zones(aligned)
                html_doc = build_compare_html(
                    track_a, lap_a_meta, lap_a_data,
                    track_b, lap_b_meta, lap_b_data,
                    aligned, zones,
                    a_lap_id=a_slot, b_lap_id=b_slot,
                    maptiler_key=AppState.maptiler_key,
                )
            except ValueError as e:
                return self._redirect("/compare?error=" + quote(str(e)))
            except Exception as e:
                sys.stderr.write("=== /compare render error ===\n")
                traceback.print_exc(file=sys.stderr)
                return self._redirect("/compare?error=" + quote(
                    f"Interner Fehler: {type(e).__name__}: {e}"
                ))
            try:
                ctx = self._request_ctx()
                AppState.db.add_event(
                    kind="view_compare",
                    user_id=ctx.get("user_id"),
                    user_email=ctx.get("user_email", ""),
                    ip_address=ctx.get("ip_address", ""),
                    detail=(f"a_lap_id={a_slot} b_lap_id={b_slot} "
                            f"track={(track_a.get('meta') or {}).get('TRACK','')}").strip(),
                    file_path="",
                )
            except Exception as e:
                sys.stderr.write(f"[event-log] view_compare(deep) failed: {e}\n")
            content = self._inject_topnav(html_doc.encode("utf-8"), "/compare")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # Empty or half-state — collect per-slot fields (time / track / lap / bike / driver)
        # so the lap-card displays them as separate columns (analog Datenviewer).
        def _empty_slot():
            return {"time":"—:—.—","track":"—","lap_no":"—","bike":"—","driver":"—","local":False}

        slot_a = _empty_slot()
        slot_b = _empty_slot()
        a_track = ""; b_track = ""
        if a_slot:
            try:
                track_a, lap_a_meta, _ = resolve_compare_slot(a_slot, self._request_ctx())
                meta_a = track_a.get("meta") or {}
                a_track = meta_a.get("TRACK", "") or meta_a.get("VENUE", "")
                slot_a = {
                    "time":   _fmt_lap(lap_a_meta["duration"]),
                    "track":  a_track or "—",
                    "lap_no": f"#{lap_a_meta.get('lap_index','?')}",
                    "bike":   meta_a.get("VEHICLE", "") or "—",
                    "driver": meta_a.get("RACER", "") or "—",
                    "local":  is_adhoc_slot(a_slot),
                }
            except Exception as e:
                sys.stderr.write(f"[/compare half-state a] {e}\n")
                a_slot = ""  # drop the bad slot
        if b_slot:
            try:
                track_b, lap_b_meta, _ = resolve_compare_slot(b_slot, self._request_ctx())
                meta_b = track_b.get("meta") or {}
                b_track = meta_b.get("TRACK", "") or meta_b.get("VENUE", "")
                slot_b = {
                    "time":   _fmt_lap(lap_b_meta["duration"]),
                    "track":  b_track or "—",
                    "lap_no": f"#{lap_b_meta.get('lap_index','?')}",
                    "bike":   meta_b.get("VEHICLE", "") or "—",
                    "driver": meta_b.get("RACER", "") or "—",
                    "local":  is_adhoc_slot(b_slot),
                }
            except Exception as e:
                sys.stderr.write(f"[/compare half-state b] {e}\n")
                b_slot = ""

        try:
            html_doc = build_compare_empty_html(
                a_lap_id=a_slot, a_track=a_track, a_fields=slot_a,
                b_lap_id=b_slot, b_track=b_track, b_fields=slot_b,
                maptiler_key=AppState.maptiler_key,
            )
        except Exception as e:
            sys.stderr.write("=== /compare empty render error ===\n")
            traceback.print_exc(file=sys.stderr)
            return self._send_text(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"Render-Fehler: {type(e).__name__}: {e}",
            )
        content = self._inject_topnav(html_doc.encode("utf-8"), "/compare")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _page_sessions_list(self, qs):
        user = self._current_user()
        laps = AppState.db.list_all_laps_flat()
        flash = ""
        if "saved" in qs:
            sid_short = qs.get("saved", [""])[0][:8]
            flash = (f'<div class="flash">RUNDE GESPEICHERT (ID: '
                     f'{html.escape(sid_short)}…)</div>')
        if "deleted" in qs:
            flash = '<div class="flash">RUNDE GELÖSCHT</div>'
        if "welcome" in qs:
            flash = ('<div class="flash">ACCOUNT BESTÄTIGT — '
                     'WILLKOMMEN BEI RACEDAT!</div>')
        if "error" in qs:
            flash = (f'<div class="flash error">⚠  '
                     f'{html.escape(qs["error"][0])}</div>')

        if not laps:
            list_html = (
                '<div class="empty-state">'
                '  <div class="icon">∅</div>'
                '  <div class="label">NOCH KEINE RUNDEN</div>'
                '  <div class="hint">RUNDE HOCHLADEN — METADATEN ANGEBEN, EINE RUNDE WÄHLEN</div>'
                + ('  <a href="/sessions/upload" class="btn">+ ERSTE RUNDE HOCHLADEN</a>'
                   if user else
                   '  <a href="/login?next=%2Fsessions%2Fupload" class="btn">+ LOGIN ZUM HOCHLADEN</a>')
                + '</div>'
            )
            count_text = ""
        else:
            count_text = f"{len(laps)} Runde{'n' if len(laps) != 1 else ''} in der Bibliothek."
            # v21.16 — Pre-aggregate lap_count per session (cheap, no extra SQL):
            # list_all_laps_flat returns one row per lap, but a session can
            # have multiple. The edit modal shows "Änderung gilt für alle N
            # Runden dieser Session." → we need the count.
            from collections import Counter
            laps_per_session = Counter(lp["session_id"] for lp in laps)
            # v21.36 — Channel-status badges. One batched depickle of all
            # visible laps gives us {lap_id: {extras_count, roles_count,
            # matchable_roles}}. We never persist this — see comment in
            # db.get_channel_summary on why.
            ch_summary = AppState.db.get_channel_summary(
                [int(lp["lap_id"]) for lp in laps]
            )
            # v23.2 — Pokal-Icons für globale Top-3 pro Strecke. Eine
            # einzige DB-Query liefert das gesamte Mapping; pro Row
            # lookup-Kosten konstant.
            global_top3 = AppState.db.global_top_n_per_track(3)
            medals_map = medal_map_from_top_n(global_top3)
            # v22.3/v22.4 — Per-role status icons replace the v21.36
            # status-badge.
            # Stefan: "Zeige pro Kanal-Rolle ein graues
            # Symbol; wenn die Rolle in diesem Lap zugeordnet ist, wird's
            # grün." v22.4: small SVG icons specific to each role
            # (brake disc, throttle grip, etc.) instead of the v22.3 dot.
            def _channel_dots(lap_id: int) -> str:
                """Return inline HTML for the per-role channel-status icons.

                One <span class="ch-icon-wrap"> per registry role wrapping
                an inline SVG icon, in registry order. Grey if that role
                is not assigned for this lap, green if it is. Each
                wrapper has a title= tooltip with the role's label.
                Returns "" if the lap has no extra channels at all
                (nothing to assign, nothing to show).
                """
                s = ch_summary.get(int(lap_id)) or {}
                extras = int(s.get("extras_count") or 0)
                if extras == 0:
                    return ""
                assigned = set(s.get("assigned_role_ids") or [])
                parts = ['<span class="ch-dots" aria-label="Standardkanal-Zuordnung">']
                for r in CHANNEL_ROLES:
                    cls = "ch-icon-wrap on" if r["id"] in assigned else "ch-icon-wrap off"
                    label = html.escape(r.get("label", r["id"]))
                    icon = _icon_for(r["id"])
                    parts.append(
                        f'<span class="{cls}" title="{label}">{icon}</span>'
                    )
                parts.append("</span>")
                return "".join(parts)

            rows = []
            for lp in laps:
                lap_time = fmt_seconds(lp["duration_s"])
                # v23.2 — Pokal-Icon, wenn diese Runde global Top-3 auf
                # ihrer Strecke ist. Empty string sonst (CSS:empty kollabiert).
                medal_html = render_medal_html(medals_map.get(int(lp["lap_id"])))
                owner_email = lp.get("owner_email") or ""
                owner_uid = lp.get("user_id")
                # v23.0 — Owner-Name ist klickbar → /profile/<user_id>
                # (read-only Profilseite). Verwaiste Sessions (user_id=NULL)
                # bleiben unverlinkt; auch der gleiche Stil wie bisher
                # damit der visuelle Diff klein bleibt.
                if owner_email and owner_uid is not None:
                    owner_display = (
                        f'<a href="/profile/{int(owner_uid)}" '
                        f'  class="owner-link" '
                        f'  title="Profil von {html.escape(owner_email)} ansehen">'
                        f'{html.escape(owner_email)}</a>'
                    )
                elif owner_email:
                    # Owner existiert in der DB nicht mehr (FK SET NULL) —
                    # E-Mail ist noch in events.user_email konserviert, aber
                    # /profile/<id> würde 404en. Plain Text statt Link.
                    owner_display = html.escape(owner_email)
                else:
                    owner_display = (
                        '<span style="color:var(--ink-faint);'
                        'font-style:italic">(verwaist)</span>'
                    )
                # Show delete button only if current user can delete this lap
                # (owner of the parent session, or admin)
                can_delete = bool(user) and (
                    user["is_admin"] or
                    (lp.get("user_id") is not None and lp["user_id"] == user["id"])
                )
                delete_html = ""
                if can_delete:
                    delete_html = (
                        f'<form method="POST" action="/laps/{lp["lap_id"]}/delete" '
                        f'onsubmit="return confirm(\'Runde unwiderruflich löschen?\')" '
                        f'style="display:inline">'
                        f'  <button type="submit" class="btn danger">×</button>'
                        f'</form>'
                    )
                # v21.8 — Datenviewer-Link dezent (kein Button), AI-Coach-Link
                # raus. Direkt-Aufruf via /analyze?lap_id=N&go=1 lädt die Runde.
                analyse_href = (f"/analyze?lap_id={lp['lap_id']}&go=1")
                # v21.32 — Vergleich-Link: lap_id als Slot A vorbelegen.
                # /compare?a=<lap_id> rendert die Half-State-View (Slot A
                # geladen, Slot B leer zur Auswahl).
                compare_href = f"/compare?a={lp['lap_id']}"
                # v21.16 — Edit-Button für Session-Meta + Kanal-Zuordnung.
                # v21.37 — Auch Owner einer Runde dürfen editieren (vorher
                # nur Admins). Gate identisch zu can_delete oben.
                can_edit = bool(user) and (
                    user["is_admin"] or
                    (lp.get("user_id") is not None and lp["user_id"] == user["id"])
                )
                edit_html = ""
                if can_edit:
                    edit_html = (
                        f'<button type="button" class="btn edit-meta-btn" '
                        f'data-session-id="{html.escape(lp["session_id"])}" '
                        f'data-lap-id="{int(lp["lap_id"])}" '
                        f'data-lap-count="{laps_per_session.get(lp["session_id"], 1)}" '
                        f'data-driver="{html.escape(lp["driver"] or "")}" '
                        f'data-bike="{html.escape(lp["bike"] or "")}" '
                        f'data-track="{html.escape(lp["track"] or "")}" '
                        f'data-session-date="{html.escape(lp["session_date"] or "")}" '
                        f'data-notes="{html.escape(lp.get("notes", "") or "")}" '
                        f'title="Meta editieren (Admin)">✎</button>'
                    )
                rows.append(
                    f'<div class="session-row" '
                    f'  data-user-id="{int(lp["user_id"]) if lp.get("user_id") is not None else ""}" '
                    f'  data-driver="{html.escape(lp["driver"] or "")}" '
                    f'  data-bike="{html.escape(lp["bike"] or "")}" '
                    f'  data-track="{html.escape(lp["track"] or "")}">'
                    f'  <div class="col-meta">'
                    f'    <span class="k">STRECKE · OWNER</span>'
                    f'    <span class="v {"dim" if not lp["track"] else ""}" title="{html.escape(lp["track"] or "")}">{html.escape(lp["track"] or "—")}</span>'
                    f'    <span class="v sub" title="{html.escape(owner_email)}">{owner_display}</span>'
                    '  </div>'
                    f'  <div class="col-meta">'
                    f'    <span class="k">FAHRER · BIKE</span>'
                    f'    <span class="v {"dim" if not lp["driver"] and not lp["bike"] else ""}" title="{html.escape(lp["driver"] or "")} · {html.escape(lp["bike"] or "")}">{html.escape(lp["driver"] or "—")} · {html.escape(lp["bike"] or "—")}</span>'
                    '  </div>'
                    f'  <div class="col-meta">'
                    f'    <span class="k">DATUM · DATEI</span>'
                    f'    <span class="v" title="{html.escape(lp["session_date"] or "")}">{html.escape(lp["session_date"] or "—")}</span>'
                    f'    <span class="v sub mono" title="{html.escape(lp["original_filename"])}">{html.escape(lp["original_filename"])}</span>'
                    f'    {_channel_dots(lp["lap_id"])}'
                    '  </div>'
                    f'  <div class="num">'
                    f'    <a href="{analyse_href}" class="lap-time-link"><span class="lap-medal">{medal_html}</span><span class="lap-time">{lap_time}</span></a>'
                    f'    <a href="{analyse_href}" class="lap-time-sub">DATENVIEWER →</a>'
                    f'    <a href="{compare_href}" class="lap-time-sub">VERGLEICH →</a>'
                    f'  </div>'
                    f'  <div class="actions">'
                    f'    {edit_html}'
                    f'    {delete_html}'
                    f'  </div>'
                    '</div>'
                )
            list_html = '<div class="session-list">' + "".join(rows) + '</div>'

        # v22.12 — Wenn der Profil-Link mit ?mine=1 hier landet und der
        # User eingeloggt ist, soll der Filter clientseitig schon angezogen
        # sein. Das spart einen Round-Trip und matched die existierende
        # Architektur (Filter ist JS auf gerenderten Rows). Wenn nicht
        # eingeloggt: ?mine=1 wird ignoriert (lautlos — kein Redirect
        # auf /login, weil die Seite selbst ohne Login lesbar ist).
        mine_mode = bool(qs.get("mine")) and bool(user)
        cur_user_id = str(user["id"]) if user else ""

        content = render_template(
            "sessions.html",
            HEADER=build_header_html(user, "/sessions"),
            FLASH=flash, LIST=list_html, COUNT_TEXT=count_text,
            NOW=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            NAV_USER=build_user_nav_snippet(user),
            NAV_ADMIN=build_admin_nav_snippet(user, "/sessions"),
            MINE_MODE=("1" if mine_mode else ""),
            CUR_USER_ID=cur_user_id,
            LOGGED_IN=("1" if user else "0"),
        )
        self._send_html(content)

    # --- v23.2 — Globale Bestzeiten je Strecke ----------------------------
    # Eine eigene Seite die für jede Strecke das Top-3 Podium zeigt: Gold,
    # Silber, Bronze über *alle* Fahrer hinweg. Sichtbar für jeden Viewer
    # (kein Login nötig — die Information ist sowieso aus den /sessions-
    # und /profile-Seiten ableitbar; die Seite ist eine bequemere Sicht).

    def _page_records(self, qs):
        user = self._current_user()
        records = AppState.db.global_top_n_per_track(3)

        if not records:
            content_html = (
                '<div class="empty-state">'
                '  <div class="icon">∅</div>'
                '  <div class="label">NOCH KEINE BESTZEITEN</div>'
                '  <div class="hint">'
                '    Sobald Runden mit einer Strecke hochgeladen sind, '
                '    erscheinen hier die schnellsten drei Runden pro '
                '    Strecke über alle Fahrer hinweg.'
                '  </div>'
                '</div>'
            )
        else:
            # v23.5 — Podium-Sockel im Stil eines echten Siegerpodests:
            # drei Quader nebeneinander auf gemeinsamer Bodenlinie, Gold
            # in der Mitte am höchsten, Silber links mittel, Bronze
            # rechts am niedrigsten. Auf jedem Sockel direkt aufgedruckt:
            # Platzziffer (1/2/3) groß in Medaillenfarbe, dünner Strich
            # darunter, Fahrername in Weiß, Motorrad in Medaillenfarbe
            # italic, Lap-Zeit unten am Sockel-Boden (margin-top:auto
            # schiebt sie ans Sockel-Unterende, unabhängig von Bike).
            blocks = []
            for track in records:
                track_name = html.escape(track["track"])
                by_rank = {int(e["rank"]): e for e in track["entries"]}
                steps = []
                # DOM-Reihenfolge: 2 (links), 1 (Mitte), 3 (rechts) —
                # passt visuell zum klassischen Treppchen.
                for rank in (2, 1, 3):
                    e = by_rank.get(rank)
                    if e is None:
                        steps.append(
                            f'<div class="rec-step rec-step-{rank} empty" '
                            'aria-label="Kein Eintrag">'
                            f'  <div class="rec-rank">{rank}</div>'
                            '  <div class="rec-divider"></div>'
                            '  <div class="rec-empty-mark">—</div>'
                            '</div>'
                        )
                        continue
                    lap_id = int(e["lap_id"])
                    dur = fmt_seconds(e["duration_s"])
                    owner_email = e.get("owner_email") or ""
                    driver_name = (e.get("driver_name") or "").strip()
                    bike = (e.get("bike") or "").strip()
                    # Display-Name: driver_name aus Session bevorzugt,
                    # sonst E-Mail-Local-Part. Volle E-Mail nie nach
                    # aussen — v23.0 Privacy-Regel.
                    if driver_name:
                        display = html.escape(driver_name)
                    elif owner_email:
                        display = html.escape(
                            owner_email.split("@", 1)[0]
                            if "@" in owner_email else owner_email
                        )
                    else:
                        display = ('<span style="color:var(--ink-faint);'
                                   'font-style:italic">(verwaist)</span>')
                    # Owner-Link auf Profil. z-index:3 in CSS damit er
                    # über dem Klick-Overlay (z-index:1) liegt.
                    if e.get("user_id"):
                        display_html = (
                            f'<a href="/profile/{int(e["user_id"])}" '
                            f'   class="rec-owner-link">{display}</a>'
                        )
                    else:
                        display_html = display
                    bike_html = (
                        f'<div class="rec-bike" title="{html.escape(bike)}">'
                        f'{html.escape(bike)}</div>'
                        if bike else ""
                    )
                    # Sockel ist ein <div> (Grid-/Flex-Item-sicher), und
                    # der Klick-Link sitzt als position:absolute Overlay
                    # darin — füllt den ganzen Sockel aus, lässt aber
                    # den Owner-Link auf dem Fahrernamen durchklicken
                    # weil der ein höheres z-index hat.
                    steps.append(
                        f'<div class="rec-step rec-step-{rank}">'
                        f'  <a href="/analyze?lap_id={lap_id}&go=1" '
                        f'     class="rec-step-link" '
                        f'     title="Runde im Datenviewer öffnen" '
                        f'     aria-label="Runde von {html.escape(driver_name or "Fahrer")} im Datenviewer öffnen"></a>'
                        f'  <div class="rec-rank">{rank}</div>'
                        f'  <div class="rec-divider"></div>'
                        f'  <div class="rec-driver">{display_html}</div>'
                        f'  {bike_html}'
                        f'  <div class="rec-time">{dur}</div>'
                        '</div>'
                    )
                blocks.append(
                    f'<div class="rec-track">'
                    f'  <div class="rec-track-name">{track_name}</div>'
                    f'  <div class="rec-podium">{"".join(steps)}</div>'
                    '</div>'
                )
            content_html = '<div class="rec-grid">' + "".join(blocks) + '</div>'

        content = render_template(
            "records.html",
            HEADER=build_header_html(user, "/records"),
            CONTENT=content_html,
            NOW=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        self._send_html(content)

    def _page_session_upload_form(self, qs):
        user = self._current_user()
        if not user:
            return self._redirect("/login?next=" + quote("/sessions/upload"))
        # Step 1 form: file + metadata
        error_html = ""
        if "error" in qs:
            error_html = (f'<div class="error-banner active">⚠  '
                          f'{html.escape(qs["error"][0])}</div>')

        # v22.12 — Defaults aus dem Profil ziehen: Fahrername und das
        # aktuell markierte Motorrad werden als value= eingesetzt. Der
        # User kann immer noch überschreiben — und der Server fällt
        # in step1_upload_session zusätzlich auf die Profil-Defaults
        # zurück, falls beide Felder leer bleiben (z.B. wenn der User
        # das value clear macht und auf "Auto-Extract aus Datei" hofft).
        profile = AppState.db.get_profile(user["id"])
        cur_bike = AppState.db.get_current_bike(user["id"])
        default_driver = html.escape(profile.get("driver_name") or "")
        default_bike = html.escape(cur_bike["name"] if cur_bike else "")
        # Hinweistext nur wenn tatsächlich ein Default kommt — sonst nicht
        # rauschen.
        profile_hint = ""
        if default_driver or default_bike:
            profile_hint = (
                '<span class="hint" style="color:var(--accent)">'
                '✓ Aus Profil vorbelegt</span>'
            )

        body = error_html + f"""
  <div class="eyebrow">Schritt 1 von 2</div>
  <h1>SESSION HOCHLADEN</h1>
  <div class="subtitle">
    Datei + Metadaten eingeben. Im nächsten Schritt wählst du aus, welche
    Runden in der Bibliothek gespeichert werden sollen.
  </div>

  <form id="upload-form" method="POST" action="/sessions/upload" enctype="multipart/form-data">
    <div class="section-title">
      <h2>DATEI</h2>
      <span class="num">.SES · .LD · .XRK · .XRZ · .CSV · .DAT (I2M) · .ZIP (2D) · MAX 10MB</span>
    </div>
    <label class="drop-zone" id="drop">
      <div class="icon">⌁</div>
      <div class="label">SESSION-DATEI</div>
      <div class="hint">KLICKEN ODER DROPPEN</div>
      <input type="file" hidden style="display:none;position:absolute;left:-9999px" name="file" id="file" accept=".ses,.SES,.ld,.LD,.xrk,.XRK,.xrz,.XRZ,.csv,.CSV,.dat,.DAT,.zip,.ZIP">
    </label>
    <div class="file-info" id="info"><span class="name"></span><span class="size"></span></div>

    <div class="section-title">
      <h2>METADATEN</h2>
      <span class="num">OPTIONAL — DIENT DEM SPÄTEREN FILTERN</span>
    </div>
    <div class="meta-grid">
      <div class="field">
        <label>FAHRER</label>
        <input type="text" name="driver" value="{default_driver}" placeholder="z.B. Stefan">
        {profile_hint if default_driver else ""}
      </div>
      <div class="field">
        <label>BIKE</label>
        <input type="text" name="bike" value="{default_bike}" placeholder="z.B. CBR 1000 RR">
        {profile_hint if default_bike else ""}
      </div>
      <div class="field">
        <label>STRECKE</label>
        <input type="text" name="track" placeholder="z.B. Aragon">
        <span class="hint">Wird automatisch aus der Datei extrahiert, falls leer.</span>
      </div>
      <div class="field">
        <label>DATUM</label>
        <input type="date" name="session_date">
        <span class="hint">Wird automatisch aus der Datei extrahiert, falls leer.</span>
      </div>
      <div class="field full">
        <label>NOTIZEN</label>
        <textarea name="notes" placeholder="Setup, Wetter, Reifen, sonstige Anmerkungen…"></textarea>
      </div>
    </div>

    <div class="submit-row">
      <a href="/sessions" class="btn secondary">← ZURÜCK</a>
      <button type="submit" class="btn">WEITER ZUR RUNDEN-AUSWAHL →</button>
    </div>
  </form>
"""
        content = render_template(
            "session_upload.html", CONTENT=body,
            HEADER=build_header_html(user, "/sessions/upload"),
            NAV_USER=build_user_nav_snippet(user),
            NAV_ADMIN=build_admin_nav_snippet(user, "/sessions/upload"),
        )
        self._send_html(content)

    def _page_session_upload_picker(self, pending_id: str):
        """Step 2 of session upload: show lap picker."""
        with PENDING_LOCK:
            pending = PENDING_SESSIONS.get(pending_id)
        if pending is None:
            return self._redirect("/sessions/upload?error="
                                  + quote("Upload abgelaufen, bitte erneut hochladen."))

        # Find fastest lap to highlight
        durations = [lp["duration_s"] for lp in pending["laps"]]
        fastest = min(durations) if durations else 0

        lap_rows = []
        # v23.11 — Auswahl nach Rundenzeit: Liste sortiert nach Zeit
        # (schnellste zuerst), Zeit ist das primäre Element, die
        # Lap-Nummer nur noch sekundäre Info. Radio-Value bleibt die
        # lap_number — die ist der stabile interne Identifier.
        for lp in sorted(pending["laps"], key=lambda l: l["duration_s"]):
            n = lp["lap_number"]
            d = lp["duration_s"]
            is_fast = abs(d - fastest) < 0.001
            checked = " checked" if is_fast else ""
            extra_class = " fastest" if is_fast else ""
            badge = '<span class="badge">SCHNELLSTE</span>' if is_fast else ""
            lap_rows.append(
                f'<label class="lap-row{extra_class}" data-duration="{d:.3f}">'
                f'  <input type="radio" name="lap" value="{n}"{checked} required>'
                f'  <span class="lap-time {"best" if is_fast else ""}">{html.escape(fmt_seconds(d))}</span>'
                f'  <span class="lap-num">LAP {n}</span>'
                f'  <span class="lap-info">{badge}</span>'
                '</label>'
            )

        meta = pending
        auto = pending.get("auto_sources") or {}
        def _hint(key):
            return ('<span class="hint" style="color:var(--accent)">'
                    '✓ Aus Datei extrahiert</span>') if auto.get(key) else ""

        # v21.34 — Channel-role assignment block. Driven entirely by the
        # CHANNEL_ROLES registry: one <select> per role, choices populated
        # from pending['available_channels'] (the same channels the Coach
        # will later see). Default selection is the pattern-based
        # auto-suggestion; user can override or clear.
        available = pending.get("available_channels") or []
        if not available:
            role_block = (
                '<div class="role-empty">'
                'Diese Datei enthält keine Datenkanäle, die zugeordnet werden '
                'könnten. Die Analysen verwenden Position und Geschwindigkeit.'
                '</div>'
            )
        else:
            role_fields = []
            for role in CHANNEL_ROLES:
                suggested = suggest_channel(role, available)
                option_html = ['<option value="">— nicht zugeordnet —</option>']
                for ch in available:
                    cid = html.escape(ch["id"])
                    cname = html.escape(ch["name"])
                    cunit = html.escape(ch.get("unit") or "")
                    sel = " selected" if ch["id"] == suggested else ""
                    label = f"{cname}" + (f" ({cunit})" if cunit else "")
                    option_html.append(
                        f'<option value="{cid}"{sel}>{html.escape(label)}</option>'
                    )
                role_fields.append(
                    f'<div class="field">'
                    f'  <label>{html.escape(role["label"])}</label>'
                    f'  <select name="role_{html.escape(role["id"])}">'
                    f'    {"".join(option_html)}'
                    f'  </select>'
                    f'  <span class="desc">{html.escape(role["description"])}</span>'
                    f'</div>'
                )
            role_block = (
                '<div class="meta-grid">'
                + "".join(role_fields)
                + '</div>'
            )

        body = f"""
  <div class="eyebrow">Schritt 2 von 2</div>
  <h1>RUNDE AUSWÄHLEN</h1>
  <div class="subtitle">
    Datei <span class="mono" style="color:var(--ink)">{html.escape(meta["original_filename"])}</span>
    enthält {len(pending["laps"])} Runde(n). Wähle eine Runde aus,
    die in der Bibliothek gespeichert wird.
  </div>

  <form method="POST" action="/sessions/save">
    <input type="hidden" name="pending_id" value="{html.escape(pending_id)}">

    <div class="section-title">
      <h2>METADATEN BESTÄTIGEN</h2>
      <span class="num">OPTIONAL</span>
    </div>
    <div class="meta-grid">
      <div class="field">
        <label>FAHRER</label>
        <input type="text" name="driver" value="{html.escape(meta["driver"])}">
        {_hint("driver")}
      </div>
      <div class="field">
        <label>BIKE</label>
        <input type="text" name="bike" value="{html.escape(meta["bike"])}">
        {_hint("bike")}
      </div>
      <div class="field">
        <label>STRECKE</label>
        <input type="text" name="track" value="{html.escape(meta["track"])}">
        {_hint("track")}
      </div>
      <div class="field">
        <label>DATUM</label>
        <input type="date" name="session_date" value="{html.escape(meta["session_date"])}">
        {_hint("session_date")}
      </div>
      <div class="field full">
        <label>NOTIZEN</label>
        <textarea name="notes">{html.escape(meta["notes"])}</textarea>
      </div>
    </div>

    <div class="section-title">
      <h2>STANDARDKANAL-ZUORDNUNG</h2>
      <span class="num">OPTIONAL · FÜR AI-COACH-ANALYSEN</span>
    </div>
    {role_block}

    <div class="section-title">
      <h2>RUNDE</h2>
      <span class="num">{len(pending["laps"])} ERKANNT — EINE AUSWÄHLEN</span>
    </div>
    <div class="lap-list">
      {''.join(lap_rows)}
    </div>

    <div class="submit-row">
      <a href="/sessions/upload" class="btn secondary">← ABBRECHEN</a>
      <button type="submit" class="btn">SPEICHERN →</button>
    </div>
  </form>
"""
        user = self._current_user()
        content = render_template(
            "session_upload.html", CONTENT=body,
            HEADER=build_header_html(user, "/sessions/upload"),
            NAV_USER=build_user_nav_snippet(user),
            NAV_ADMIN=build_admin_nav_snippet(user, "/sessions/upload"),
        )
        self._send_html(content)

    # --- Analyze: single-lap inspection
    def _page_analyze_form(self, qs):
        """The /analyze endpoint.

        Two modes:
          - Empty (?lap_id is absent or empty): render the SPA picker page —
            a library browser + ad-hoc upload that, on selection, navigates
            to /analyze?lap_id=N.
          - With ?lap_id=N: render the full analysis HTML inline (same
            output as the legacy /analysis/<uuid> page used to be), but
            without persisting a UUID-keyed snapshot. The lap id stays in
            the URL so the link is bookmarkable; each visit re-renders
            from the current DB blob (Option B in the v20 refactor).

        Also: ?upload=1 lets ad-hoc upload paths land back here after a
        POST /api/analyze/upload — but for now we just route uploads
        directly to a one-shot rendered page (see _handle_analyze).
        """
        user = self._current_user()

        # Direct-link analysis: ?lap_id=N → render inline, no persistence.
        lap_id_str = (qs.get("lap_id", [""])[0] or "").strip()
        if lap_id_str:
            try:
                lap_id = int(lap_id_str)
            except ValueError:
                return self._redirect("/analyze?error=" + quote("Ungültige Lap-ID"))
            try:
                track, lap_meta, lap_data = resolve_lap_from_form(
                    {"mode": "library", "lap_id": str(lap_id)},
                    self._request_ctx(),
                )
                html_doc = build_single_lap_html(
                    track=track, lap_meta=lap_meta, lap_data=lap_data,
                    coach_href=f"/coach?lap_id={lap_id}",
                    compare_href=f"/compare?a={lap_id}",
                    maptiler_key=AppState.maptiler_key,
                )
            except ValueError as e:
                return self._redirect("/analyze?error=" + quote(str(e)))
            except Exception as e:
                sys.stderr.write("=== /analyze?lap_id render error ===\n")
                traceback.print_exc(file=sys.stderr)
                return self._redirect("/analyze?error=" + quote(
                    f"Interner Fehler: {type(e).__name__}: {e}"
                ))
            # Audit log: every direct-link rendering counts as a view event.
            try:
                ctx = self._request_ctx()
                AppState.db.add_event(
                    kind="view_analysis",
                    user_id=ctx.get("user_id"),
                    user_email=ctx.get("user_email", ""),
                    ip_address=ctx.get("ip_address", ""),
                    detail=(f"lap_id={lap_id} "
                            f"track={(track.get('meta') or {}).get('TRACK','')} "
                            f"lap={lap_meta.get('lap_index')}").strip(),
                    file_path="",
                )
            except Exception as e:
                sys.stderr.write(f"[event-log] view_analysis(deep) failed: {e}\n")
            # Inject the unified topnav into the rendered analysis HTML.
            content = self._inject_topnav(html_doc.encode("utf-8"), "/analyze")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # Empty mode: render the same analysis SPA shell as /analyze?lap_id,
        # but with no data. The picker modal in that page is the entry point
        # for loading a lap. Picking from the library navigates to
        # /analyze?lap_id=N; upload posts to /analyze.
        try:
            html_doc = build_single_lap_empty_html(
                maptiler_key=AppState.maptiler_key,
            )
        except Exception as e:
            sys.stderr.write("=== /analyze empty render error ===\n")
            traceback.print_exc(file=sys.stderr)
            return self._send_text(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"Render-Fehler: {type(e).__name__}: {e}",
            )
        content = self._inject_topnav(html_doc.encode("utf-8"), "/analyze")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # --- Admin: artefact overview
    def _page_admin_artefacts(self, qs):
        user = self._current_user()
        if not user:
            return self._redirect("/login?next=" + quote("/admin"))
        if not user["is_admin"]:
            return self._send_text(
                HTTPStatus.NOT_FOUND, "404 Not Found"
            )

        # v21.25 — Default-Tab ist Aktivität (zeigt was zuletzt angeschaut wurde,
        # das ist im täglichen Betrieb interessanter als die Upload-Liste).
        tab = (qs.get("tab", ["activity"])[0] or "activity").lower()
        if tab not in ("legacy", "logins", "uploads", "activity", "profiles"):
            tab = "activity"

        all_items = list_all_artefacts()
        # v20.4: All persisted artefacts (compare reports AND analysis snapshots)
        # are now legacy — Compare and Datenviewer are rendered live.
        # Existing snapshots are accessible under "Legacy".
        items_legacy = [it for it in all_items
                        if it["kind"] in ("report", "analysis")]
        events_logins = AppState.db.list_events(kinds=["login", "login_fail"], limit=500)
        events_uploads = AppState.db.list_events(kinds=["upload_session", "upload_adhoc"], limit=500)
        # v20.3 + v20.4: viewer/coach/compare views all live in activity.
        events_views = AppState.db.list_events(
            kinds=["view_analysis", "view_coach", "view_compare"], limit=500,
        )
        # v23.4: profile overview (rows in `profiles` table) with bike counts.
        profiles = AppState.db.list_all_profiles()
        total_users = AppState.db.count_users()

        flash = ""
        if "deleted" in qs:
            flash = '<div class="flash">EINTRAG GELÖSCHT</div>'
        if "error" in qs:
            flash = (f'<div class="flash error">⚠  '
                     f'{html.escape(qs["error"][0])}</div>')

        # Count text — depends on current tab
        if tab == "artefacts":
            count_text = (
                "Vergleiche werden seit v20.4 live gerendert — "
                "es gibt keine neuen Snapshots mehr. "
                'Bereits vorhandene Reports findest du unter „Legacy".'
            )
        elif tab == "legacy":
            count_text = (
                f"{len(items_legacy)} Legacy-Snapshot"
                f"{'s' if len(items_legacy) != 1 else ''} "
                f"(vorgenerierte Reports und Datenviewer-Snapshots — "
                f"neue Aufrufe werden live gerendert)."
            )
        elif tab == "logins":
            ok = sum(1 for e in events_logins if e["kind"] == "login")
            failed = sum(1 for e in events_logins if e["kind"] == "login_fail")
            count_text = (f"{len(events_logins)} Logins erfasst — "
                          f"{ok} erfolgreich, {failed} fehlgeschlagen.")
        elif tab == "activity":
            count_text = (
                f"{len(events_views)} View-Aufruf"
                f"{'e' if len(events_views) != 1 else ''} "
                f"(Datenviewer, AI Coach und Vergleich)."
            )
        elif tab == "profiles":
            count_text = (
                f"{len(profiles)} Profil"
                f"{'e' if len(profiles) != 1 else ''} "
                f"angelegt — von insgesamt {total_users} User"
                f"{'n' if total_users != 1 else ''}. "
                f"Klick auf E-Mail öffnet die öffentliche Profilseite."
            )
        else:  # uploads
            sess = sum(1 for e in events_uploads if e["kind"] == "upload_session")
            adhoc = sum(1 for e in events_uploads if e["kind"] == "upload_adhoc")
            count_text = (f"{len(events_uploads)} Uploads — "
                          f"{sess} Runden in Bibliothek, {adhoc} ad-hoc (Vergleich/Datenviewer).")

        # Renders rows for /admin?tab=legacy (legacy compare reports + analysis snapshots).
        def _render_artefact_rows(items, empty_label, empty_hint):
            if not items:
                return (
                    '<div class="empty-state">'
                    '  <div class="icon">∅</div>'
                    f'  <div class="label">{empty_label}</div>'
                    f'  <div class="hint">{empty_hint}</div>'
                    '</div>'
                )
            rows = []
            for it in items:
                kind = it["kind"]
                m = it.get("meta") or {}
                created = it["created_at"] or "—"
                created_short = created.replace("T", " ").replace("+00:00", " UTC")
                req_email = m.get("user_email") or ""
                req_ip = m.get("ip_address") or ""
                requester = (
                    html.escape(req_email) if req_email
                    else '<span style="color:var(--ink-faint);font-style:italic">anonym</span>'
                )
                ip_display = (html.escape(req_ip) if req_ip
                              else '<span style="color:var(--ink-faint)">—</span>')
                if kind == "report":
                    a = m.get("a", {})
                    b = m.get("b", {})
                    track = a.get("track") or b.get("track") or ""
                    a_time = fmt_seconds(a.get("lap_duration_s")) if a.get("lap_duration_s") else "—"
                    b_time = fmt_seconds(b.get("lap_duration_s")) if b.get("lap_duration_s") else "—"
                    summary = (
                        f'<span class="lap-time mono">{a_time}</span> · '
                        f'<span class="lap-time mono">{b_time}</span>'
                    )
                    detail = (
                        f'<span style="color:var(--ink-dim);font-family:JetBrains Mono;font-size:11px">'
                        f'{html.escape(a.get("source_file") or "?")} vs {html.escape(b.get("source_file") or "?")}'
                        f'</span>'
                    )
                    view_url = f"/report/{it['id']}"
                    kind_pill = '<span class="pill pill-report">VERGLEICH</span>'
                else:  # analysis (legacy)
                    track = m.get("track") or ""
                    racer = m.get("racer") or ""
                    lap_time = fmt_seconds(m.get("lap_duration_s")) if m.get("lap_duration_s") else "—"
                    summary = f'<span class="lap-time mono">{lap_time}</span>'
                    detail = (
                        f'<span style="color:var(--ink-dim);font-family:JetBrains Mono;font-size:11px">'
                        f'{html.escape(m.get("source_file") or "?")}'
                        f'{" · " + html.escape(racer) if racer else ""}'
                        f'</span>'
                    )
                    view_url = f"/analysis/{it['id']}"
                    kind_pill = '<span class="pill pill-analysis">DATENVIEWER (LEGACY)</span>'
                size_kb = it["size_bytes"] / 1024.0
                size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
                rows.append(
                    f'<div class="artefact-row" '
                    f'  data-kind="{html.escape(kind)}" '
                    f'  data-track="{html.escape(track or "")}">'
                    f'  <div class="col-kind">{kind_pill}</div>'
                    f'  <div class="col-when" title="{html.escape(created)}">{html.escape(created_short)}</div>'
                    f'  <div class="col-track" title="{html.escape(track)}">{html.escape(track or "—")}</div>'
                    f'  <div class="col-who">{requester}<br>'
                    f'    <span style="color:var(--ink-faint);font-family:JetBrains Mono;font-size:10px">{ip_display}</span>'
                    f'  </div>'
                    f'  <div class="col-summary">{summary}<br>{detail}</div>'
                    f'  <div class="col-size">{size_str}</div>'
                    f'  <div class="col-actions">'
                    f'    <a href="{view_url}" class="btn small" target="_blank" rel="noopener">ÖFFNEN ↗</a>'
                    f'    <form method="POST" action="/admin/{kind}/{it["id"]}/delete" '
                    f'          onsubmit="return confirm(\'Eintrag unwiderruflich löschen?\')" '
                    f'          style="display:inline">'
                    f'      <button type="submit" class="btn small danger">×</button>'
                    f'    </form>'
                    f'  </div>'
                    '</div>'
                )
            return '<div class="artefact-list">' + "".join(rows) + '</div>'

        legacy_html = _render_artefact_rows(
            items_legacy,
            empty_label="KEINE LEGACY-SNAPSHOTS",
            empty_hint=(
                "VORGENERIERTE REPORTS (PRE-V20.4) UND DATENVIEWER-SNAPSHOTS (PRE-V20). "
                "NEUE AUFRUFE WERDEN LIVE GERENDERT UND ERSCHEINEN UNTER „AKTIVITÄT“."
            ),
        )

        # Logins list -------------------------------------------------------
        if not events_logins:
            logins_html = (
                '<div class="empty-state">'
                '  <div class="icon">∅</div>'
                '  <div class="label">KEINE LOGIN-EREIGNISSE</div>'
                '  <div class="hint">SOBALD JEMAND SICH ANMELDET, ERSCHEINT HIER EIN EINTRAG</div>'
                '</div>'
            )
        else:
            rows = []
            for ev in events_logins:
                created_short = (ev["created_at"] or "").replace("T", " ").replace("+00:00", " UTC")
                ok = (ev["kind"] == "login")
                pill = ('<span class="pill pill-ok">ERFOLGREICH</span>' if ok
                        else '<span class="pill pill-fail">FEHLGESCHLAGEN</span>')
                email = ev["user_email"] or ""
                email_display = html.escape(email) if email else '<span style="color:var(--ink-faint);font-style:italic">—</span>'
                ip_display = render_ip_cell(ev["ip_address"] or "")
                detail = html.escape(ev["detail"] or "")
                rows.append(
                    f'<div class="event-row" data-kind="{html.escape(ev["kind"])}">'
                    f'  <div class="col-kind">{pill}</div>'
                    f'  <div class="col-when" title="{html.escape(ev["created_at"] or "")}">{html.escape(created_short)}</div>'
                    f'  <div class="col-who">{email_display}</div>'
                    f'  <div class="col-ip mono">{ip_display}</div>'
                    f'  <div class="col-detail mono" style="color:var(--ink-dim);font-size:11px">{detail}</div>'
                    '</div>'
                )
            logins_html = '<div class="event-list">' + "".join(rows) + '</div>'

        # Uploads list ------------------------------------------------------
        if not events_uploads:
            uploads_html = (
                '<div class="empty-state">'
                '  <div class="icon">∅</div>'
                '  <div class="label">KEINE UPLOADS</div>'
                '  <div class="hint">SOBALD DATEIEN HOCHGELADEN WERDEN, ERSCHEINT HIER EIN EINTRAG</div>'
                '</div>'
            )
        else:
            rows = []
            for ev in events_uploads:
                created_short = (ev["created_at"] or "").replace("T", " ").replace("+00:00", " UTC")
                is_session = (ev["kind"] == "upload_session")
                pill = ('<span class="pill pill-session">RUNDE</span>' if is_session
                        else '<span class="pill pill-adhoc">AD-HOC</span>')
                email = ev["user_email"] or ""
                email_display = html.escape(email) if email else '<span style="color:var(--ink-faint);font-style:italic">anonym</span>'
                ip_display = render_ip_cell(ev["ip_address"] or "")
                detail = html.escape(ev["detail"] or "")
                # File-path display: show only the leaf name, full as tooltip
                fp_full = ev["file_path"] or ""
                fp_leaf = os.path.basename(fp_full) if fp_full else ""
                file_html = (
                    f'<span title="{html.escape(fp_full)}">{html.escape(fp_leaf)}</span>'
                    if fp_leaf else
                    '<span style="color:var(--ink-faint)">—</span>'
                )
                # v21.7 — Download link for the original file (admin only).
                # Show only when the file still exists on disk; otherwise the
                # link would 404. Cheap stat() per row is fine for ≤500 rows.
                download_html = ''
                if fp_full:
                    try:
                        exists = os.path.isfile(fp_full)
                    except OSError:
                        exists = False
                    if exists:
                        download_html = (
                            f'<a href="/admin/event/{ev["id"]}/file" '
                            f'   class="btn small" title="Originaldatei herunterladen">'
                            f'   ↓</a>'
                        )
                # Delete-event button: removes the row AND the file (for upload events)
                del_form = (
                    f'<form method="POST" action="/admin/event/{ev["id"]}/delete" '
                    f'      onsubmit="return confirm(\'Eintrag und Datei unwiderruflich löschen?\')" '
                    f'      style="display:inline">'
                    f'  <button type="submit" class="btn small danger">×</button>'
                    f'</form>'
                )
                actions_html = download_html + del_form
                rows.append(
                    f'<div class="event-row" data-kind="{html.escape(ev["kind"])}">'
                    f'  <div class="col-kind">{pill}</div>'
                    f'  <div class="col-when" title="{html.escape(ev["created_at"] or "")}">{html.escape(created_short)}</div>'
                    f'  <div class="col-who">{email_display}</div>'
                    f'  <div class="col-ip mono">{ip_display}</div>'
                    f'  <div class="col-detail mono" style="color:var(--ink-dim);font-size:11px">{detail}<br>{file_html}</div>'
                    f'  <div class="col-actions">{actions_html}</div>'
                    '</div>'
                )
            uploads_html = '<div class="event-list">' + "".join(rows) + '</div>'

        # Activity list (view_analysis events) -----------------------------
        # Each row represents one /analyze?lap_id render. We can link back
        # to the same lap_id if it parses out of the detail string.
        if not events_views:
            activity_html = (
                '<div class="empty-state">'
                '  <div class="icon">∅</div>'
                '  <div class="label">KEINE VIEW-AUFRUFE</div>'
                '  <div class="hint">SOBALD JEMAND DEN DATENVIEWER, AI COACH ODER VERGLEICH ÖFFNET, ERSCHEINT HIER EIN EINTRAG</div>'
                '</div>'
            )
        else:
            rows = []
            _lap_id_re = re.compile(r"lap_id=(\d+)")
            _ab_lap_id_re = re.compile(r"a_lap_id=(\d+)\s+b_lap_id=(\d+)")
            for ev in events_views:
                created_short = (ev["created_at"] or "").replace("T", " ").replace("+00:00", " UTC")
                email = ev["user_email"] or ""
                email_display = (html.escape(email) if email
                                 else '<span style="color:var(--ink-faint);'
                                      'font-style:italic">anonym</span>')
                ip_display = render_ip_cell(ev["ip_address"] or "")
                detail = html.escape(ev["detail"] or "")
                kind = ev["kind"]
                # Each view kind points back to its own SPA when "ÖFFNEN" is clicked
                open_html = ""
                if kind == "view_coach":
                    pill = '<span class="pill pill-coach">AI COACH</span>'
                    m = _lap_id_re.search(ev["detail"] or "")
                    if m:
                        open_html = (
                            f'<a href="/coach?lap_id={m.group(1)}" '
                            f'   class="btn small" target="_blank" rel="noopener">'
                            f'   ÖFFNEN ↗</a>'
                        )
                elif kind == "view_compare":
                    pill = '<span class="pill pill-compare">VERGLEICH</span>'
                    m = _ab_lap_id_re.search(ev["detail"] or "")
                    if m:
                        open_html = (
                            f'<a href="/compare?a={m.group(1)}&b={m.group(2)}" '
                            f'   class="btn small" target="_blank" rel="noopener">'
                            f'   ÖFFNEN ↗</a>'
                        )
                else:  # view_analysis
                    pill = '<span class="pill pill-analysis">DATENVIEWER</span>'
                    m = _lap_id_re.search(ev["detail"] or "")
                    if m:
                        open_html = (
                            f'<a href="/analyze?lap_id={m.group(1)}" '
                            f'   class="btn small" target="_blank" rel="noopener">'
                            f'   ÖFFNEN ↗</a>'
                        )
                rows.append(
                    f'<div class="event-row" data-kind="{html.escape(kind)}">'
                    f'  <div class="col-kind">{pill}</div>'
                    f'  <div class="col-when" title="{html.escape(ev["created_at"] or "")}">'
                    f'    {html.escape(created_short)}</div>'
                    f'  <div class="col-who">{email_display}</div>'
                    f'  <div class="col-ip mono">{ip_display}</div>'
                    f'  <div class="col-detail mono" '
                    f'       style="color:var(--ink-dim);font-size:11px">{detail}</div>'
                    f'  <div class="col-actions">{open_html}</div>'
                    '</div>'
                )
            activity_html = '<div class="event-list">' + "".join(rows) + '</div>'

        # Profiles list (v23.4) -------------------------------------------
        # Eine Row pro Eintrag in der `profiles`-Tabelle. E-Mail klickt
        # auf /profile/<user_id> (öffentliche Read-Only-Ansicht aus v23.0).
        # User ohne Profil tauchen hier nicht auf — siehe count_text für die
        # "X von Y"-Info-Zeile.
        if not profiles:
            profiles_html = (
                '<div class="empty-state">'
                '  <div class="icon">∅</div>'
                '  <div class="label">KEINE PROFILE ANGELEGT</div>'
                '  <div class="hint">SOBALD JEMAND UNTER /profile EINEN FAHRERNAMEN ODER '
                'EIN MOTORRAD SPEICHERT, ERSCHEINT HIER EIN EINTRAG</div>'
                '</div>'
            )
        else:
            rows = []
            for p in profiles:
                user_id = p["user_id"]
                email = p["email"] or ""
                driver = p["driver_name"] or ""
                bike_count = p["bike_count"] or 0
                current_bike = p["current_bike_name"] or ""
                has_image = bool(p["image_path"])
                updated_short = (p["updated_at"] or "").replace("T", " ").replace("+00:00", " UTC")
                # E-Mail = klickbarer Link auf die öffentliche Profilseite.
                # Auch ohne driver_name funktioniert die Seite (Fallback auf
                # E-Mail-Localpart aus v23.0).
                email_link = (
                    f'<a href="/profile/{user_id}" target="_blank" rel="noopener" '
                    f'   style="color:var(--ink);font-family:JetBrains Mono">'
                    f'  {html.escape(email)}</a>'
                )
                admin_tag = ('<span class="pill pill-fail" style="margin-left:6px">ADMIN</span>'
                             if p["is_admin"] else '')
                # Driver-Name: leere Strings als unauffälliges Em-Dash anzeigen.
                driver_html = (html.escape(driver) if driver
                               else '<span style="color:var(--ink-faint);'
                                    'font-style:italic">—</span>')
                # Bike-Info: "2 Motorräder · aktuell: Beemer-R", oder Dashes.
                if bike_count == 0:
                    bike_html = ('<span style="color:var(--ink-faint);'
                                 'font-style:italic">keine</span>')
                else:
                    suffix = "Motorrad" if bike_count == 1 else "Motorräder"
                    cur_html = (f' · <span style="color:var(--ink-dim)">aktuell: '
                                f'{html.escape(current_bike)}</span>' if current_bike else '')
                    bike_html = f'{bike_count} {suffix}{cur_html}'
                # Foto-Indikator: ✓ wenn Bild gesetzt, sonst —
                photo_html = ('<span title="Profilfoto gesetzt" '
                              'style="color:var(--ink-dim)">✓ Foto</span>'
                              if has_image else
                              '<span style="color:var(--ink-faint)">—</span>')
                rows.append(
                    f'<div class="event-row" data-kind="profile">'
                    f'  <div class="col-kind">'
                    f'    <span class="pill pill-session">PROFIL</span>{admin_tag}'
                    f'  </div>'
                    f'  <div class="col-when" title="updated_at={html.escape(p["updated_at"] or "")}">'
                    f'    {html.escape(updated_short)}</div>'
                    f'  <div class="col-who">{email_link}<br>'
                    f'    <span style="color:var(--ink-dim);font-size:11px">{driver_html}</span>'
                    f'  </div>'
                    f'  <div class="col-detail mono" '
                    f'       style="color:var(--ink-dim);font-size:11px">{bike_html}<br>{photo_html}</div>'
                    f'  <div class="col-actions">'
                    f'    <a href="/profile/{user_id}" class="btn small" '
                    f'       target="_blank" rel="noopener">ÖFFNEN ↗</a>'
                    f'  </div>'
                    '</div>'
                )
            profiles_html = '<div class="event-list">' + "".join(rows) + '</div>'

        # Build tabs nav
        def _tab(slug, label, count):
            cls = "tab active" if slug == tab else "tab"
            return (f'<a href="/admin?tab={slug}" class="{cls}">'
                    f'<span class="label">{label}</span> '
                    f'<span class="count">{count}</span>'
                    f'</a>')
        tabs_html = (
            '<div class="tabs">'
            + _tab("uploads",   "Uploads",     len(events_uploads))
            + _tab("activity",  "Aktivität",   len(events_views))
            + _tab("logins",    "Logins",      len(events_logins))
            + _tab("profiles",  "Profile",     len(profiles))
            + _tab("legacy",    "Legacy",      len(items_legacy))
            + '</div>'
        )

        # Active panel
        panels = {
            "legacy":    legacy_html,
            "logins":    logins_html,
            "uploads":   uploads_html,
            "activity":  activity_html,
            "profiles":  profiles_html,
        }
        active_panel = panels[tab]

        # Version info — built once per request so the hashes reflect the
        # CURRENT file state on disk (helps catch "did I restart?" issues).
        vi = version_info()
        version_html = (
            f'<div class="version-info mono">'
            f'  <span class="vi-tag">BUILD</span>'
            f'  <span class="vi-version">{html.escape(vi["version"])}</span>'
            f'  <span class="vi-sep">·</span>'
            f'  <span class="vi-label">prozess gestartet</span>'
            f'  <span>{html.escape(vi["process_started"])}</span>'
            f'  <span class="vi-sep">·</span>'
            f'  <span class="vi-label">webserver.py</span>'
            f'  <span>{html.escape(vi["webserver_sha"])}</span>'
            f'  <span class="vi-faint">({html.escape(vi["webserver_mtime"])})</span>'
            f'  <span class="vi-sep">·</span>'
            f'  <span class="vi-label">report.py</span>'
            f'  <span>{html.escape(vi["report_sha"])}</span>'
            f'  <span class="vi-faint">({html.escape(vi["report_mtime"])})</span>'
            f'  <span class="vi-sep">·</span>'
            f'  <span class="vi-label">report_single.py</span>'
            f'  <span>{html.escape(vi["report_single_sha"])}</span>'
            f'  <span class="vi-faint">({html.escape(vi["report_single_mtime"])})</span>'
            f'  <span class="vi-sep">·</span>'
            f'  <span class="vi-label">coach.py</span>'
            f'  <span>{html.escape(vi["coach_sha"])}</span>'
            f'  <span class="vi-faint">({html.escape(vi["coach_mtime"])})</span>'
            f'</div>'
        )

        content = render_template(
            "admin.html",
            HEADER=build_header_html(user, "/admin"),
            FLASH=flash, LIST=active_panel,
            TABS=tabs_html,
            COUNT_TEXT=count_text,
            NOW=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            NAV_USER=build_user_nav_snippet(user),
            VERSION_INFO=version_html,
        )
        self._send_html(content)

    def _handle_admin_delete(self, kind: str, art_id: str):
        """Admin-only: delete a single report or analysis directory."""
        user = self._current_user()
        if not user:
            return self._redirect("/login?next=" + quote("/admin"))
        if not user["is_admin"]:
            debuglog.log("action.admin.delete.denied", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         kind=kind, art_id=art_id, reason="not_admin")
            return self._send_text(HTTPStatus.NOT_FOUND, "404 Not Found")
        if not UUID_RE.match(art_id):
            return self._redirect("/admin?error=" + quote("Ungültige ID"))
        if kind == "report":
            target = AppState.reports_dir / art_id
        elif kind == "analysis":
            target = AppState.analyses_dir / art_id
        else:
            return self._redirect("/admin?error=" + quote("Unbekannter Typ"))
        if not target.is_dir():
            return self._redirect("/admin?error=" + quote("Nicht gefunden"))
        try:
            shutil.rmtree(target)
        except OSError as e:
            debuglog.log("action.admin.delete.error", level="error",
                         user=user["email"], ip=self._client_ip(),
                         kind=kind, art_id=art_id,
                         error=f"{type(e).__name__}: {e}")
            return self._redirect("/admin?error=" + quote(f"Lösch-Fehler: {e}"))
        debuglog.log("action.admin.delete.ok",
                     user=user["email"], ip=self._client_ip(),
                     kind=kind, art_id=art_id)
        return self._redirect("/admin?deleted=1")

    def _handle_admin_event_delete(self, event_id: int):
        """Admin: delete an event row, and the persisted file if any."""
        user = self._current_user()
        if not user:
            return self._redirect("/login?next=" + quote("/admin"))
        if not user["is_admin"]:
            debuglog.log("action.admin.event_delete.denied", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         event_id=event_id, reason="not_admin")
            return self._send_text(HTTPStatus.NOT_FOUND, "404 Not Found")
        fp = AppState.db.delete_event(event_id)
        if fp is None:
            debuglog.log("action.admin.event_delete.notfound", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         event_id=event_id)
            return self._redirect("/admin?tab=uploads&error=" + quote("Eintrag nicht gefunden"))
        # Remove the file too if present
        if fp:
            try:
                p = Path(fp)
                if p.is_file():
                    p.unlink()
                if p.parent.is_dir() and not any(p.parent.iterdir()):
                    p.parent.rmdir()
            except OSError:
                pass
        debuglog.log("action.admin.event_delete.ok",
                     user=user["email"], ip=self._client_ip(),
                     event_id=event_id, file_removed=bool(fp))
        return self._redirect("/admin?tab=uploads&deleted=1")

    def _handle_admin_event_download(self, event_id: int):
        """Admin-only: send the original uploaded file for an upload event.

        Safety: file_path on the event row must point INSIDE the originals
        or adhoc directory — anything outside is rejected to prevent
        path traversal via a forged DB row.
        """
        user = self._current_user()
        if not user:
            return self._redirect("/login?next=" + quote("/admin"))
        if not user["is_admin"]:
            return self._send_text(HTTPStatus.NOT_FOUND, "404 Not Found")
        ev = AppState.db.get_event(event_id)
        if not ev:
            return self._send_text(HTTPStatus.NOT_FOUND, "Event nicht gefunden")
        fp_str = ev.get("file_path") or ""
        if not fp_str:
            return self._send_text(HTTPStatus.NOT_FOUND,
                                   "Für diesen Event ist kein File gespeichert")
        # Resolve and confine to known upload roots
        try:
            fp = Path(fp_str).resolve()
        except (OSError, ValueError):
            return self._send_text(HTTPStatus.BAD_REQUEST, "Ungültiger Pfad")
        roots = []
        for attr in ("originals_dir", "adhoc_dir"):
            r = getattr(AppState, attr, None)
            if r:
                try:
                    roots.append(Path(r).resolve())
                except (OSError, ValueError):
                    pass
        if not any(_path_is_inside(fp, r) for r in roots):
            return self._send_text(HTTPStatus.FORBIDDEN,
                                   "Pfad liegt außerhalb der erlaubten Verzeichnisse")
        if not fp.is_file():
            return self._send_text(HTTPStatus.NOT_FOUND,
                                   "Datei nicht mehr vorhanden")
        data = fp.read_bytes()
        # Suggest the original filename as the download name
        download_name = fp.name or f"event_{event_id}"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{download_name}"',
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


    def _handle_admin_ip_lookup(self, qs):
        """v22.11 — Reverse IP geo lookup, admin only.

        Renders a small page with country/city/region/ISP/AS for the IP
        in the `ip` query parameter. We hit ip-api.com server-side because
        their free tier is HTTP-only (so a browser fetch from an HTTPS
        admin page would be blocked by mixed-content rules) and because
        gating it behind the admin role prevents the endpoint from being
        abused as an open relay that would burn the 45 req/min limit.

        Loopback / private IPs short-circuit to a friendly message; we
        never hit the upstream for those."""
        user = self._current_user()
        if not user:
            return self._redirect("/login?next=" + quote("/admin"))
        if not user["is_admin"]:
            debuglog.log("action.admin.ip_lookup.denied", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         reason="not_admin")
            return self._send_text(HTTPStatus.NOT_FOUND, "404 Not Found")

        ip = (qs.get("ip", [""])[0] or "").strip()
        if not ip:
            return self._send_text(HTTPStatus.BAD_REQUEST,
                                   "Parameter 'ip' fehlt")
        # Length cap — defence against a forged absurdly long value
        if len(ip) > 64:
            return self._send_text(HTTPStatus.BAD_REQUEST, "IP zu lang")
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return self._send_text(HTTPStatus.BAD_REQUEST,
                                   "Ungültige IP-Adresse")

        # Build geo dict. Private/loopback → synthesised "local" record,
        # public → upstream call.
        if is_private_or_loopback_ip(ip):
            geo = {"status": "local"}
            debuglog.log("action.admin.ip_lookup.ok",
                         user=user["email"], ip=self._client_ip(),
                         lookup_ip=ip, result="local")
        else:
            geo = fetch_ip_geo(ip)
            outcome = geo.get("status") or "unknown"
            debuglog.log("action.admin.ip_lookup.ok",
                         user=user["email"], ip=self._client_ip(),
                         lookup_ip=ip, result=outcome)

        html_doc = self._render_ip_lookup_page(ip, geo)
        return self._send_html(html_doc.encode("utf-8"))

    def _render_ip_lookup_page(self, ip: str, geo: dict) -> str:
        """Render the small standalone page for /admin/ip-lookup.
        Same dark theme as the rest of admin, minimal markup, no JS."""
        ip_esc = html.escape(ip)
        status = geo.get("status") or ""

        if status == "local":
            body = (
                '<div class="card">'
                '<div class="row"><span class="k">STATUS</span>'
                '<span class="v">Lokale / private Adresse</span></div>'
                '<div class="hint">RFC 1918 / Loopback / Link-Local. Geo-Lookup '
                'nicht möglich — der Client ist im selben Netz oder kommt über '
                'einen Reverse-Proxy ohne X-Forwarded-For.</div>'
                '</div>'
            )
        elif status == "success":
            def _f(k: str) -> str:
                v = geo.get(k)
                return html.escape(str(v)) if v not in (None, "", 0) else "—"
            lat = geo.get("lat")
            lon = geo.get("lon")
            map_html = ""
            if lat not in (None, "") and lon not in (None, ""):
                # OpenStreetMap link — opens in new tab from the lookup
                # page itself (which is already in a new tab).
                osm = (f'https://www.openstreetmap.org/?mlat={lat}&mlon={lon}'
                       f'#map=10/{lat}/{lon}')
                map_html = (
                    f'<div class="row"><span class="k">KARTE</span>'
                    f'<span class="v"><a href="{html.escape(osm)}" '
                    f'target="_blank" rel="noopener">'
                    f'OpenStreetMap ↗</a></span></div>'
                )
            cc = geo.get("countryCode") or ""
            country_line = _f("country")
            if cc:
                country_line += f' <span class="dim">({html.escape(cc)})</span>'
            body = (
                '<div class="card">'
                f'<div class="row"><span class="k">LAND</span>'
                f'<span class="v">{country_line}</span></div>'
                f'<div class="row"><span class="k">REGION</span>'
                f'<span class="v">{_f("regionName")} '
                f'<span class="dim">({_f("region")})</span></span></div>'
                f'<div class="row"><span class="k">STADT</span>'
                f'<span class="v">{_f("city")} '
                f'<span class="dim">{_f("zip")}</span></span></div>'
                f'<div class="row"><span class="k">KOORDINATEN</span>'
                f'<span class="v mono">{_f("lat")}, {_f("lon")}</span></div>'
                f'<div class="row"><span class="k">ZEITZONE</span>'
                f'<span class="v">{_f("timezone")}</span></div>'
                f'<div class="row"><span class="k">ISP</span>'
                f'<span class="v">{_f("isp")}</span></div>'
                f'<div class="row"><span class="k">ORG</span>'
                f'<span class="v">{_f("org")}</span></div>'
                f'<div class="row"><span class="k">AS</span>'
                f'<span class="v mono">{_f("as")}</span></div>'
                f'{map_html}'
                '</div>'
            )
        elif status == "fail":
            msg = html.escape(geo.get("message") or "unbekannt")
            body = (
                '<div class="card error">'
                '<div class="row"><span class="k">STATUS</span>'
                '<span class="v">Lookup fehlgeschlagen</span></div>'
                f'<div class="row"><span class="k">GRUND</span>'
                f'<span class="v mono">{msg}</span></div>'
                '<div class="hint">ip-api.com hat die Adresse abgelehnt — '
                'oft bei reservierten oder unbekannten Bereichen.</div>'
                '</div>'
            )
        else:  # "error" or unknown
            msg = html.escape(geo.get("message") or "unbekannt")
            body = (
                '<div class="card error">'
                '<div class="row"><span class="k">STATUS</span>'
                '<span class="v">Netzwerk-/Parse-Fehler</span></div>'
                f'<div class="row"><span class="k">DETAIL</span>'
                f'<span class="v mono">{msg}</span></div>'
                '<div class="hint">Server konnte ip-api.com nicht erreichen. '
                'Im Zweifel später nochmal versuchen.</div>'
                '</div>'
            )

        return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>IP-Lookup {ip_esc} · Racedat</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0a0a0a; --bg-2:#141414;
  --ink:#f5f5f0; --ink-dim:#a0a0a0; --ink-faint:#888;
  --line:#262626; --accent:#00d4ff; --fail:#ff3d00;
}}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{background:var(--bg);color:var(--ink);font-family:'Space Grotesk',sans-serif;line-height:1.5;min-height:100vh}}
.mono{{font-family:'JetBrains Mono',monospace;font-feature-settings:'tnum'}}
.page{{max-width:720px;margin:0 auto;padding:48px 32px}}
@media (max-width:520px){{.page{{padding:24px 16px 48px}}}}
.eyebrow{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.2em;color:var(--accent);text-transform:uppercase;margin-bottom:16px}}
h1{{font-family:'Bebas Neue',sans-serif;font-size:48px;line-height:.9;letter-spacing:.01em;margin-bottom:8px;word-break:break-all}}
.subtitle{{color:var(--ink-dim);font-size:13px;margin-bottom:32px;font-family:'JetBrains Mono',monospace;letter-spacing:.05em}}
.card{{background:var(--bg-2);border:1px solid var(--line);border-left:3px solid var(--accent);padding:20px 24px;margin-bottom:24px}}
.card.error{{border-left-color:var(--fail)}}
.row{{display:grid;grid-template-columns:140px 1fr;gap:12px;padding:8px 0;border-bottom:1px solid var(--line);align-items:baseline}}
.row:last-child{{border-bottom:none}}
.row .k{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.15em;color:var(--ink-faint);text-transform:uppercase}}
.row .v{{font-size:14px;color:var(--ink)}}
.row .v.mono{{font-family:'JetBrains Mono',monospace;font-size:12px}}
.row .v a{{color:var(--accent);text-decoration:none}}
.row .v a:hover{{text-decoration:underline}}
.dim{{color:var(--ink-faint);font-size:11px;font-family:'JetBrains Mono',monospace}}
.hint{{color:var(--ink-dim);font-size:12px;margin-top:12px;padding-top:12px;border-top:1px solid var(--line);font-family:'JetBrains Mono',monospace;letter-spacing:.03em;line-height:1.5}}
footer{{margin-top:48px;padding-top:24px;border-top:1px solid var(--line);color:var(--ink-faint);font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.05em;display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px}}
footer a{{color:var(--ink-faint);text-decoration:none}}
footer a:hover{{color:var(--accent)}}
</style>
</head>
<body>
<div class="page">
  <div class="eyebrow">REVERSE IP LOOKUP</div>
  <h1 class="mono">{ip_esc}</h1>
  <div class="subtitle">Geo-Daten via ip-api.com (kostenfreier Tier, 45 req/min)</div>
  {body}
  <footer>
    <span>RACEDAT · ADMIN · IP LOOKUP</span>
    <span><a href="javascript:window.close()">Tab schließen ×</a></span>
  </footer>
</div>
</body>
</html>"""


    def _handle_analyze(self):
        """POST /analyze — entry point from the picker SPA.

        Two cases (mode-dependent):

        1) mode=library, lap_id=N → redirect to /analyze?lap_id=N. The
           GET handler will render. Bookmarkable URL.

        2) mode=upload, file=... → render the analysis from the uploaded
           file ONCE (no persistence, no UUID), return HTML directly.
           The browser shows it but the URL stays /analyze (so a refresh
           re-submits — the user is expected to save the lap to the
           library via /sessions/upload for a persistent link).
        """
        try:
            form = parse_form(self)
        except UploadTooLarge as e:
            return self._redirect("/analyze?error=" + quote(str(e)))
        except Exception as e:
            return self._redirect("/analyze?error=" + quote(f"Upload-Fehler: {e}"))

        mode = (form.get("mode") or "").strip()
        if mode == "library":
            lap_id_str = (form.get("lap_id") or "").strip()
            if not lap_id_str:
                return self._redirect("/analyze?error=" + quote("Lap-ID fehlt"))
            debuglog.log("action.analyze.library",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         lap_id=lap_id_str)
            return self._redirect(f"/analyze?lap_id={quote(lap_id_str)}")

        # Upload path — render one-shot.
        try:
            track, lap_meta, lap_data = resolve_lap_from_form(
                form, self._request_ctx(),
            )
        except ValueError as e:
            debuglog.log("action.analyze.upload.error", level="warn",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         error=f"ValueError: {e}")
            return self._redirect("/analyze?error=" + quote(str(e)))
        except Exception as e:
            sys.stderr.write("=== /analyze upload error ===\n")
            traceback.print_exc(file=sys.stderr)
            debuglog.log("action.analyze.upload.error", level="error",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         error=f"{type(e).__name__}: {e}")
            return self._redirect("/analyze?error=" + quote(
                f"Interner Fehler: {type(e).__name__}: {e}"
            ))

        try:
            html_doc = build_single_lap_html(
                track=track, lap_meta=lap_meta, lap_data=lap_data,
                maptiler_key=AppState.maptiler_key,
            )
        except Exception as e:
            sys.stderr.write("=== /analyze upload render error ===\n")
            traceback.print_exc(file=sys.stderr)
            debuglog.log("action.analyze.upload.error", level="error",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         error=f"render: {type(e).__name__}: {e}")
            return self._redirect("/analyze?error=" + quote(
                f"Render-Fehler: {type(e).__name__}: {e}"
            ))

        # Audit event for upload-based analysis.
        try:
            ctx = self._request_ctx()
            AppState.db.add_event(
                kind="view_analysis",
                user_id=ctx.get("user_id"),
                user_email=ctx.get("user_email", ""),
                ip_address=ctx.get("ip_address", ""),
                detail=(f"upload src={track.get('source_file','')} "
                        f"lap={lap_meta.get('lap_index')}").strip(),
                file_path="",
            )
        except Exception as e:
            sys.stderr.write(f"[event-log] view_analysis(upload) failed: {e}\n")

        debuglog.log("action.analyze.upload.ok",
                     **debuglog.fields_from_ctx(self._request_ctx()),
                     source_file=track.get("source_file"),
                     lap_index=lap_meta.get("lap_index"))

        content = self._inject_topnav(html_doc.encode("utf-8"), "/analyze")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # ===== v20.3: AI Analyse und Coach SPA =====
    # Same shape as Datenviewer (/analyze): empty shell when ?lap_id is
    # missing, live-rendered when set. POST mirror handles uploads.

    def _page_coach_form(self, qs):
        """GET /coach[?lap_id=N] — Coach SPA, empty or filled."""
        user = self._current_user()

        lap_id_str = (qs.get("lap_id", [""])[0] or "").strip()
        if lap_id_str:
            try:
                lap_id = int(lap_id_str)
            except ValueError:
                return self._redirect("/coach?error=" + quote("Ungültige Lap-ID"))
            try:
                track, lap_meta, lap_data = resolve_lap_from_form(
                    {"mode": "library", "lap_id": str(lap_id)},
                    self._request_ctx(),
                )
                html_doc = build_coach_html(
                    track=track, lap_meta=lap_meta, lap_data=lap_data,
                    viewer_href=f"/analyze?lap_id={lap_id}",
                    maptiler_key=AppState.maptiler_key,
                )
            except ValueError as e:
                return self._redirect("/coach?error=" + quote(str(e)))
            except Exception as e:
                sys.stderr.write("=== /coach?lap_id render error ===\n")
                traceback.print_exc(file=sys.stderr)
                return self._redirect("/coach?error=" + quote(
                    f"Interner Fehler: {type(e).__name__}: {e}"
                ))
            try:
                ctx = self._request_ctx()
                AppState.db.add_event(
                    kind="view_coach",
                    user_id=ctx.get("user_id"),
                    user_email=ctx.get("user_email", ""),
                    ip_address=ctx.get("ip_address", ""),
                    detail=(f"lap_id={lap_id} "
                            f"track={(track.get('meta') or {}).get('TRACK','')} "
                            f"lap={lap_meta.get('lap_index')}").strip(),
                    file_path="",
                )
            except Exception as e:
                sys.stderr.write(f"[event-log] view_coach(deep) failed: {e}\n")
            content = self._inject_topnav(html_doc.encode("utf-8"), "/coach")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        try:
            html_doc = build_coach_empty_html(
                maptiler_key=AppState.maptiler_key,
            )
        except Exception as e:
            sys.stderr.write("=== /coach empty render error ===\n")
            traceback.print_exc(file=sys.stderr)
            return self._send_text(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"Render-Fehler: {type(e).__name__}: {e}",
            )
        content = self._inject_topnav(html_doc.encode("utf-8"), "/coach")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _handle_coach(self):
        """POST /coach — library→redirect, upload→one-shot render."""
        try:
            form = parse_form(self)
        except UploadTooLarge as e:
            return self._redirect("/coach?error=" + quote(str(e)))
        except Exception as e:
            return self._redirect("/coach?error=" + quote(f"Upload-Fehler: {e}"))

        mode = (form.get("mode") or "").strip()
        if mode == "library":
            lap_id_str = (form.get("lap_id") or "").strip()
            if not lap_id_str:
                return self._redirect("/coach?error=" + quote("Lap-ID fehlt"))
            debuglog.log("action.coach.library",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         lap_id=lap_id_str)
            return self._redirect(f"/coach?lap_id={quote(lap_id_str)}")

        # Upload path — render one-shot.
        try:
            track, lap_meta, lap_data = resolve_lap_from_form(
                form, self._request_ctx(),
            )
        except ValueError as e:
            debuglog.log("action.coach.upload.error", level="warn",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         error=f"ValueError: {e}")
            return self._redirect("/coach?error=" + quote(str(e)))
        except Exception as e:
            sys.stderr.write("=== /coach upload error ===\n")
            traceback.print_exc(file=sys.stderr)
            debuglog.log("action.coach.upload.error", level="error",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         error=f"{type(e).__name__}: {e}")
            return self._redirect("/coach?error=" + quote(
                f"Interner Fehler: {type(e).__name__}: {e}"
            ))

        try:
            # Ad-hoc upload has no library lap_id, so no cross-link possible.
            html_doc = build_coach_html(
                track=track, lap_meta=lap_meta, lap_data=lap_data,
                viewer_href="",
                maptiler_key=AppState.maptiler_key,
            )
        except Exception as e:
            sys.stderr.write("=== /coach upload render error ===\n")
            traceback.print_exc(file=sys.stderr)
            debuglog.log("action.coach.upload.error", level="error",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         error=f"render: {type(e).__name__}: {e}")
            return self._redirect("/coach?error=" + quote(
                f"Render-Fehler: {type(e).__name__}: {e}"
            ))

        try:
            ctx = self._request_ctx()
            AppState.db.add_event(
                kind="view_coach",
                user_id=ctx.get("user_id"),
                user_email=ctx.get("user_email", ""),
                ip_address=ctx.get("ip_address", ""),
                detail=(f"upload src={track.get('source_file','')} "
                        f"lap={lap_meta.get('lap_index')}").strip(),
                file_path="",
            )
        except Exception as e:
            sys.stderr.write(f"[event-log] view_coach(upload) failed: {e}\n")

        debuglog.log("action.coach.upload.ok",
                     **debuglog.fields_from_ctx(self._request_ctx()),
                     source_file=track.get("source_file"),
                     lap_index=lap_meta.get("lap_index"))

        content = self._inject_topnav(html_doc.encode("utf-8"), "/coach")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_analysis(self, analysis_id: str):
        if not UUID_RE.match(analysis_id):
            return self._send_text(HTTPStatus.BAD_REQUEST, "Invalid id")
        path = AppState.analyses_dir / analysis_id / "analysis.html"
        if not path.is_file():
            return self._send_text(HTTPStatus.NOT_FOUND, "Snapshot nicht gefunden.")
        content = path.read_bytes()
        content = self._inject_topnav(content, f"/analysis/{analysis_id}")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # --- Compare handler (ad-hoc uploads — single or pair)
    def _handle_compare(self):
        """POST /compare — handles two ad-hoc upload paths.

        - mode=adhoc:          two files at once (legacy "AD-HOC VERGLEICH"
                               form). Renders the full compare and persists
                               as /report/<uuid> snapshot.
        - mode=single_upload:  one file, one slot. Parses + caches the
                               uploaded file, then redirects to
                               /compare?<slot>=ad-<token>&<other>=<other>
                               so the SPA can continue the picker flow.

        Library-mode compares never come via POST — they're plain GETs.
        """
        try:
            form = parse_multipart(self)
        except UploadTooLarge as e:
            return self._redirect("/compare?error=" + quote(str(e)))
        except Exception as e:
            return self._redirect("/compare?error=" + quote(f"Upload-Fehler: {e}"))

        mode = (form.get("mode") or "").strip()

        # ---- Single-slot upload (Compare picker → LOKALE DATEI tab) ----
        # v23.12 — Zwei-Phasen-Flow: die Datei wurde bereits per
        # /api/adhoc/laps eingelagert (adhoc_token), hier kommt nur noch
        # die Rundenauswahl an ('auto' oder lap_number). Fallback ohne
        # JS: Datei direkt im Formular → schnellste Runde.
        if mode == "single_upload":
            slot = (form.get("slot") or "").strip().lower()
            if slot not in ("a", "b"):
                return self._redirect("/compare?error=" + quote("Slot fehlt"))
            token = (form.get("adhoc_token") or "").strip()
            lap_choice = (form.get("lap") or "auto").strip()
            other_raw = (form.get("other_lap_id") or "").strip()
            fname = ""

            try:
                if token:
                    token, _summary = finalize_adhoc_compare(token, lap_choice)
                elif "file" in form:
                    fname, fdata = form["file"]
                    token, _laps = stash_adhoc_upload(
                        fname, fdata, request_ctx=self._request_ctx())
                    token, _summary = finalize_adhoc_compare(token, "auto")
                else:
                    return self._redirect("/compare?error="
                                          + quote("Keine Datei hochgeladen"))
            except ValueError as e:
                debuglog.log("action.compare.upload.error", level="warn",
                             **debuglog.fields_from_ctx(self._request_ctx()),
                             filename=fname, slot=slot,
                             error=f"ValueError: {e}")
                return self._redirect("/compare?error=" + quote(str(e)))
            except Exception as e:
                sys.stderr.write("=== /compare single_upload error ===\n")
                traceback.print_exc(file=sys.stderr)
                debuglog.log("action.compare.upload.error", level="error",
                             **debuglog.fields_from_ctx(self._request_ctx()),
                             filename=fname, slot=slot,
                             error=f"{type(e).__name__}: {e}")
                return self._redirect("/compare?error=" + quote(
                    f"Upload-Fehler: {type(e).__name__}: {e}"
                ))

            debuglog.log("action.compare.upload.ok",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         filename=fname, slot=slot, lap_choice=lap_choice,
                         token=token)

            # Build redirect URL — keep the other slot if it was set
            params = []
            if slot == "a":
                params.append(("a", token))
                if other_raw:
                    params.append(("b", other_raw))
            else:
                if other_raw:
                    params.append(("a", other_raw))
                params.append(("b", token))
            qs = "&".join(f"{k}={quote(str(v))}" for k, v in params)
            return self._redirect(f"/compare?{qs}")

        # ---- Legacy ad-hoc (two files at once) ----
        try:
            report_id = process_compare(form, self._request_ctx())
        except ValueError as e:
            debuglog.log("action.compare.error", level="warn",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         error=f"ValueError: {e}")
            return self._redirect("/compare?error=" + quote(str(e)))
        except Exception as e:
            sys.stderr.write("=== Unhandled in /compare ===\n")
            traceback.print_exc(file=sys.stderr)
            debuglog.log("action.compare.error", level="error",
                         **debuglog.fields_from_ctx(self._request_ctx()),
                         error=f"{type(e).__name__}: {e}")
            return self._redirect("/compare?error=" + quote(
                f"Interner Fehler: {type(e).__name__}: {e}"
            ))

        debuglog.log("action.compare.ok",
                     **debuglog.fields_from_ctx(self._request_ctx()),
                     report_id=report_id)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/report/{report_id}")
        self.end_headers()

    # --- Session upload handlers
    def _handle_session_upload_step1(self):
        user = self._current_user()
        if not user:
            return self._redirect("/login?next=" + quote("/sessions/upload"))
        try:
            form = parse_multipart(self)
        except UploadTooLarge as e:
            debuglog.log("action.session.upload.step1.error", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         error=f"too_large: {e}")
            return self._redirect("/sessions/upload?error=" + quote(str(e)))
        except Exception as e:
            debuglog.log("action.session.upload.step1.error", level="error",
                         user=user["email"], ip=self._client_ip(),
                         error=f"{type(e).__name__}: {e}")
            return self._redirect("/sessions/upload?error=" + quote(f"Upload-Fehler: {e}"))

        try:
            pending_id = step1_upload_session(form, user_id=user["id"])
        except ValueError as e:
            debuglog.log("action.session.upload.step1.error", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         error=f"ValueError: {e}")
            return self._redirect("/sessions/upload?error=" + quote(str(e)))
        except Exception as e:
            sys.stderr.write("=== Unhandled in step1 ===\n")
            traceback.print_exc(file=sys.stderr)
            debuglog.log("action.session.upload.step1.error", level="error",
                         user=user["email"], ip=self._client_ip(),
                         error=f"{type(e).__name__}: {e}")
            return self._redirect("/sessions/upload?error=" + quote(
                f"Interner Fehler: {type(e).__name__}: {e}"
            ))

        debuglog.log("action.session.upload.step1.ok",
                     user=user["email"], ip=self._client_ip(),
                     pending_id=pending_id)
        # Show step 2 directly (server-rendered)
        return self._page_session_upload_picker(pending_id)

    def _handle_session_save_step2(self):
        user = self._current_user()
        if not user:
            return self._redirect("/login?next=" + quote("/sessions/upload"))
        try:
            form = parse_multipart(self)
        except Exception as e:
            debuglog.log("action.session.upload.step2.error", level="error",
                         user=user["email"], ip=self._client_ip(),
                         error=f"parse: {type(e).__name__}: {e}")
            return self._redirect("/sessions/upload?error=" + quote(f"Upload-Fehler: {e}"))

        pending_id = form.get("pending_id", "")
        if not isinstance(pending_id, str) or not UUID_RE.match(pending_id):
            debuglog.log("action.session.upload.step2.error", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         error="bad_pending_id")
            return self._redirect("/sessions/upload?error=" + quote("Ungültiger pending_id"))

        try:
            session_id = step2_save_session(
                pending_id, form,
                user_id=user["id"],
                request_ctx=self._request_ctx(),
            )
        except ValueError as e:
            debuglog.log("action.session.upload.step2.error", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         pending_id=pending_id,
                         error=f"ValueError: {e}")
            return self._redirect("/sessions/upload?error=" + quote(str(e)))
        except Exception as e:
            sys.stderr.write("=== Unhandled in step2 ===\n")
            traceback.print_exc(file=sys.stderr)
            debuglog.log("action.session.upload.step2.error", level="error",
                         user=user["email"], ip=self._client_ip(),
                         pending_id=pending_id,
                         error=f"{type(e).__name__}: {e}")
            return self._redirect("/sessions/upload?error=" + quote(
                f"Interner Fehler: {type(e).__name__}: {e}"
            ))

        debuglog.log("action.session.upload.step2.ok",
                     user=user["email"], ip=self._client_ip(),
                     session_id=session_id)
        return self._redirect(f"/sessions?saved={session_id}")

    def _handle_lap_delete(self, lap_id: int):
        user = self._current_user()
        if not user:
            debuglog.log("action.lap.delete.denied", level="warn",
                         ip=self._client_ip(), lap_id=lap_id,
                         reason="not_logged_in")
            return self._redirect("/login?next=" + quote("/sessions"))
        lp = AppState.db.get_lap(lap_id)
        if lp is None:
            debuglog.log("action.lap.delete.notfound", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         lap_id=lap_id)
            return self._redirect("/sessions?error=" + quote("Runde nicht gefunden."))
        # Ownership / admin check — we need the parent session's owner.
        # get_lap doesn't return user_id, so go via the session.
        sess = AppState.db.get_session(lp["session_id"])
        owner_id = sess.get("user_id") if sess else None
        is_owner = (owner_id is not None and owner_id == user["id"])
        if not (is_owner or user["is_admin"]):
            debuglog.log("action.lap.delete.denied", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         lap_id=lap_id, session_id=lp["session_id"],
                         reason="not_owner_not_admin")
            return self._redirect("/sessions?error=" + quote(
                "Keine Berechtigung — nur der Besitzer oder ein Admin kann diese Runde löschen."))
        try:
            result = AppState.db.delete_lap(lap_id)
        except Exception as e:
            debuglog.log("action.lap.delete.error", level="error",
                         user=user["email"], ip=self._client_ip(),
                         lap_id=lap_id, error=f"{type(e).__name__}: {e}")
            return self._redirect("/sessions?error=" + quote(str(e)))
        if result is None:
            debuglog.log("action.lap.delete.notfound", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         lap_id=lap_id)
            return self._redirect("/sessions?error=" + quote("Runde nicht gefunden."))
        # If the parent session became empty, clean the on-disk original
        file_path = result.get("file_path_to_clean")
        if file_path:
            try:
                p = Path(file_path)
                if p.is_file():
                    p.unlink()
                if p.parent.is_dir() and not any(p.parent.iterdir()):
                    p.parent.rmdir()
            except OSError:
                pass
        debuglog.log("action.lap.delete.ok",
                     user=user["email"], ip=self._client_ip(),
                     lap_id=lap_id, session_id=lp["session_id"],
                     as_admin=(not is_owner),
                     session_purged=bool(file_path))
        return self._redirect("/sessions?deleted=1")

    def _handle_session_edit(self, session_id: str):
        """Update editable session metadata.

        v21.37 — Permission gate widened from admin-only to "owner of
        the session, OR admin". The owner is the user_id stored on the
        sessions row (set at upload time). Anonymous-uploaded sessions
        (user_id NULL) can only be edited by admins.

        Accepts application/x-www-form-urlencoded (also works with FormData
        from fetch()). Returns JSON {ok, error?, session?}.

        Editable fields: driver, bike, track, session_date (YYYY-MM-DD),
        notes. Unspecified fields are treated as empty strings to keep the
        semantics of "the form is the source of truth"."""
        user = self._current_user()
        if not user:
            debuglog.log("action.session.edit.denied", level="warn",
                         ip=self._client_ip(), session_id=session_id,
                         reason="not_logged_in")
            return self._send_json(
                {"ok": False, "error": "Nicht eingeloggt."},
                status=HTTPStatus.UNAUTHORIZED)
        sess = AppState.db.get_session(session_id)
        if sess is None:
            debuglog.log("action.session.edit.notfound", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         session_id=session_id)
            return self._send_json(
                {"ok": False, "error": "Session nicht gefunden."},
                status=HTTPStatus.NOT_FOUND)
        # Owner-or-admin gate
        owner_id = sess.get("user_id")
        is_owner = owner_id is not None and owner_id == user["id"]
        if not (user["is_admin"] or is_owner):
            debuglog.log("action.session.edit.denied", level="warn",
                         user=user["email"], ip=self._client_ip(),
                         session_id=session_id,
                         reason="not_owner_not_admin")
            return self._send_json(
                {"ok": False, "error": "Nur der Besitzer oder ein Admin "
                                       "darf diese Session ändern."},
                status=HTTPStatus.FORBIDDEN)
        try:
            form = parse_form(self)
        except Exception as e:
            return self._send_json(
                {"ok": False, "error": f"Ungültiger Request-Body: {e}"},
                status=HTTPStatus.BAD_REQUEST)

        def _f(name: str) -> str:
            v = form.get(name, "")
            if isinstance(v, list):
                v = v[0] if v else ""
            return (v or "").strip()

        driver       = _f("driver")
        bike         = _f("bike")
        track        = _f("track")
        # v22.2 — same canonicalisation as on upload save: an edit that
        # changes only the case of an existing other-session's track snaps
        # to that one's spelling.
        track        = AppState.db.canonical_track_name(track)
        session_date = _f("session_date")
        notes        = _f("notes")

        # Validation
        # session_date: must be empty or YYYY-MM-DD
        if session_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", session_date):
            return self._send_json(
                {"ok": False,
                 "error": "Datum muss leer oder im Format YYYY-MM-DD sein."},
                status=HTTPStatus.BAD_REQUEST)
        # Length caps — sessions table is TEXT but we don't want pathological
        # inputs filling the column.
        for label, val in (("Fahrer", driver), ("Bike", bike),
                           ("Strecke", track)):
            if len(val) > 200:
                return self._send_json(
                    {"ok": False,
                     "error": f"{label} zu lang (max 200 Zeichen)."},
                    status=HTTPStatus.BAD_REQUEST)
        if len(notes) > 5000:
            return self._send_json(
                {"ok": False, "error": "Notizen zu lang (max 5000 Zeichen)."},
                status=HTTPStatus.BAD_REQUEST)

        try:
            ok = AppState.db.update_session_meta(
                session_id,
                driver=driver, bike=bike, track=track,
                session_date=session_date, notes=notes,
            )
        except Exception as e:
            return self._send_json(
                {"ok": False, "error": str(e)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR)
        if not ok:
            return self._send_json(
                {"ok": False, "error": "Session nicht gefunden."},
                status=HTTPStatus.NOT_FOUND)

        # Audit log — compact diff in detail field
        changed_keys = []
        try:
            ctx = self._request_ctx()
            diff_parts = []
            for k, new in (("driver", driver), ("bike", bike),
                           ("track", track),
                           ("session_date", session_date),
                           ("notes", notes)):
                old = sess.get(k) or ""
                if old != new:
                    changed_keys.append(k)
                    # Truncate notes for the audit line — full content is in DB
                    if k == "notes":
                        diff_parts.append(f"{k}: ({len(old)} → {len(new)} chars)")
                    else:
                        diff_parts.append(f"{k}: {old!r} → {new!r}")
            detail = (f"session_id={session_id}; "
                      + ("; ".join(diff_parts) if diff_parts else "no-op"))
            AppState.db.add_event(
                "session_meta_edit",
                user_id=ctx["user_id"], user_email=ctx["user_email"],
                ip_address=ctx["ip_address"], detail=detail,
            )
        except Exception:
            pass  # audit log is best-effort
        debuglog.log("action.session.edit.ok",
                     user=user["email"], ip=self._client_ip(),
                     session_id=session_id,
                     as_admin=(not is_owner),
                     # Comma-joined keys keep the field bare-token
                     # (no quoting needed); empty if nothing changed.
                     changed=(",".join(changed_keys) or None))

        updated = AppState.db.get_session(session_id) or {}
        return self._send_json({
            "ok": True,
            "session": {
                "id": session_id,
                "driver":       updated.get("driver", ""),
                "bike":         updated.get("bike", ""),
                "track":        updated.get("track", ""),
                "session_date": updated.get("session_date", ""),
                "notes":        updated.get("notes", ""),
            },
        })

    # --- v21.35 — Admin: channel-role assignment per lap ---------------------

    def _api_lap_channel_roles_get(self, lap_id: int):
        """GET /api/laps/<id>/channel-roles
        Returns the registry, the available channels for this lap, and the
        currently persisted assignment.

        v21.37 — Owner-or-admin gate (was admin-only). Owners can read
        their own laps' role assignments to populate the edit modal."""
        user = self._current_user()
        if not user:
            return self._send_json(
                {"ok": False, "error": "Nicht eingeloggt."},
                status=HTTPStatus.UNAUTHORIZED)
        lap = AppState.db.get_lap(lap_id)
        if lap is None:
            return self._send_json(
                {"ok": False, "error": "Lap nicht gefunden."},
                status=HTTPStatus.NOT_FOUND)
        owner_id = lap.get("session_user_id")
        is_owner = owner_id is not None and owner_id == user["id"]
        if not (user["is_admin"] or is_owner):
            return self._send_json(
                {"ok": False, "error": "Nur der Besitzer oder ein Admin "
                                       "darf diese Runde lesen."},
                status=HTTPStatus.FORBIDDEN)
        lap_data = lap["lap_data"]
        # Available channels: derive from the lap_data blob (same view the
        # Coach has — no re-parse of the source file needed).
        available = build_available_extras({}, lap_data=lap_data)
        current = dict(lap_data.get("channel_roles") or {})
        # Sanitise current against the actual available list so a stale
        # role doesn't show up as "selected" pointing to a gone channel.
        valid_ids = {c["id"] for c in available}
        current = {k: v for k, v in current.items() if v in valid_ids}
        # Registry: ship only the fields the modal needs (no regex objects).
        registry = [
            {
                "id":          r["id"],
                "label":       r["label"],
                "description": r["description"],
                "analyses":    list(r.get("analyses") or []),
                "suggested":   suggest_channel(r, available),
            }
            for r in CHANNEL_ROLES
        ]
        return self._send_json({
            "ok":                 True,
            "lap_id":             lap_id,
            "channel_roles":      current,
            "available_channels": available,
            "registry":           registry,
        })

    def _api_lap_channel_roles_post(self, lap_id: int):
        """POST /api/laps/<id>/channel-roles
        Body: urlencoded `role_<id>=<channel_id>` fields, or JSON
        {role_id: channel_id, ...}. Empty channel_id = unassign.

        v21.37 — Owner-or-admin gate (was admin-only). Returns
        {ok, channel_roles}."""
        user = self._current_user()
        if not user:
            return self._send_json(
                {"ok": False, "error": "Nicht eingeloggt."},
                status=HTTPStatus.UNAUTHORIZED)
        lap = AppState.db.get_lap(lap_id)
        if lap is None:
            return self._send_json(
                {"ok": False, "error": "Lap nicht gefunden."},
                status=HTTPStatus.NOT_FOUND)
        owner_id = lap.get("session_user_id")
        is_owner = owner_id is not None and owner_id == user["id"]
        if not (user["is_admin"] or is_owner):
            return self._send_json(
                {"ok": False, "error": "Nur der Besitzer oder ein Admin "
                                       "darf Kanal-Zuordnungen ändern."},
                status=HTTPStatus.FORBIDDEN)

        # Parse body — accept both urlencoded (role_<id>=...) and JSON.
        try:
            content_type = (self.headers.get("Content-Type") or "").lower()
            if "application/json" in content_type:
                raw_len = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(raw_len).decode("utf-8") if raw_len else "{}"
                payload = json.loads(body or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON body must be an object")
                raw_roles = {str(k): ("" if v is None else str(v))
                             for k, v in payload.items()}
            else:
                form = parse_form(self)
                raw_roles = {}
                for r in CHANNEL_ROLES:
                    v = form.get(f"role_{r['id']}", "")
                    if isinstance(v, list):
                        v = v[0] if v else ""
                    raw_roles[r["id"]] = (v or "").strip()
        except Exception as e:
            return self._send_json(
                {"ok": False, "error": f"Ungültiger Request-Body: {e}"},
                status=HTTPStatus.BAD_REQUEST)

        lap_data = lap["lap_data"]
        available = build_available_extras({}, lap_data=lap_data)
        available_ids = [c["id"] for c in available]
        new_roles = sanitise_assignment(raw_roles, available_ids)

        # Compute diff for audit log before writing.
        old_roles = dict(lap_data.get("channel_roles") or {})

        # Read-modify-write the pickled blob.
        if new_roles:
            lap_data["channel_roles"] = new_roles
        else:
            # Empty dict — drop the key entirely so legacy laps look identical
            # to a freshly-cleared one (no orphan empty {} in the pickle).
            lap_data.pop("channel_roles", None)
        try:
            ok = AppState.db.update_lap_blob(lap_id, lap_data)
        except Exception as e:
            return self._send_json(
                {"ok": False, "error": f"Speichern fehlgeschlagen: {e}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR)
        if not ok:
            return self._send_json(
                {"ok": False, "error": "Lap nicht gefunden (race)."},
                status=HTTPStatus.NOT_FOUND)

        # Audit log
        changed_role_ids = []
        try:
            ctx = self._request_ctx()
            diff_parts = []
            all_role_ids = set(old_roles) | set(new_roles)
            for rid in sorted(all_role_ids):
                old_v = old_roles.get(rid, "")
                new_v = new_roles.get(rid, "")
                if old_v != new_v:
                    changed_role_ids.append(rid)
                    diff_parts.append(f"{rid}: {old_v!r} → {new_v!r}")
            detail = (f"lap_id={lap_id}; "
                      + ("; ".join(diff_parts) if diff_parts else "no-op"))
            AppState.db.add_event(
                "lap_channel_roles_edit",
                user_id=ctx["user_id"], user_email=ctx["user_email"],
                ip_address=ctx["ip_address"], detail=detail,
            )
        except Exception:
            pass  # audit log is best-effort

        debuglog.log("action.lap.channel_roles.edit.ok",
                     user=user["email"], ip=self._client_ip(),
                     lap_id=lap_id,
                     as_admin=(not is_owner),
                     changed=(",".join(changed_role_ids) or None))

        return self._send_json({"ok": True, "channel_roles": new_roles})

    # --- API endpoints
    def _api_distinct(self):
        try:
            data = AppState.db.distinct_values()
        except Exception as e:
            return self._send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
        return self._send_json(data)

    def _api_channel_roles_registry(self):
        """v22.3/v22.4 — Static channel-role registry for the lap-picker UI.

        Returns a list of {id, label, description, icon} entries in the
        same order as parsers.channel_roles.ROLES. Picker UIs (sessions
        list, Coach, Compare, Datenviewer) use this to render one
        per-role status icon next to each lap, coloured grey or green
        depending on whether the lap has that role assigned (see
        /api/laps response, field `assigned_role_ids`).

        The `icon` field is a complete inline SVG string with
        currentColor strokes/fills, so the UI just sets `color:` on the
        wrapper to switch grey ↔ green.
        """
        try:
            payload = [
                {
                    "id":          r["id"],
                    "label":       r.get("label", r["id"]),
                    "description": r.get("description", ""),
                    "icon":        _icon_for(r["id"]),
                }
                for r in CHANNEL_ROLES
            ]
        except Exception as e:
            return self._send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
        return self._send_json(payload)

    def _api_laps(self, qs):
        def first(name, default=""):
            v = qs.get(name, [default])[0]
            return v.strip() if isinstance(v, str) else default
        def first_float(name):
            v = first(name)
            if not v:
                return None
            try:
                return float(v)
            except ValueError:
                return None
        try:
            laps = AppState.db.query_laps(
                driver=first("driver"),
                bike=first("bike"),
                track=first("track"),
                date_from=first("date_from"),
                date_to=first("date_to"),
                min_seconds=first_float("min"),
                max_seconds=first_float("max"),
                search=first("search"),
                limit=int(first("limit", "200")),
            )
            # v21.38 — Enrich each row with channel-summary counts so the
            # AI-Coach lap-picker (and any future client) can render the
            # same status badge as the sessions list without a second API
            # round-trip. One batched depickle keeps this cheap (~12 ms /
            # 200 rows).
            ch_summary = AppState.db.get_channel_summary(
                [int(lp["lap_id"]) for lp in laps]
            )
            for lp in laps:
                s = ch_summary.get(int(lp["lap_id"])) or {}
                lp["extras_count"] = int(s.get("extras_count") or 0)
                lp["roles_count"]  = int(s.get("roles_count")  or 0)
                lp["total_roles"]  = int(s.get("total_roles")  or 0)
                # v22.3 — per-lap list of role ids that have a channel
                # assigned. Drives the picker status-dots (grey vs green
                # per role). Empty list = no role assignments.
                lp["assigned_role_ids"] = list(s.get("assigned_role_ids") or [])
        except Exception as e:
            return self._send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
        return self._send_json(laps)

    # --- NEW v20: SPA data endpoint
    # GET /api/analyze?lap_id=N  → JSON payload for the analysis SPA.
    # Resolves a library lap, runs the same computation that build_single_lap_html
    # used to inline as {{DATA_JSON}}, and returns just the data part.
    def _api_analyze(self, qs):
        lap_id_str = (qs.get("lap_id", [""])[0] or "").strip()
        if not lap_id_str:
            return self._send_json({"error": "lap_id missing"}, status=400)
        try:
            lap_id = int(lap_id_str)
        except ValueError:
            return self._send_json({"error": "lap_id invalid"}, status=400)
        try:
            track, lap_meta, lap_data = resolve_lap_from_form(
                {"mode": "library", "lap_id": str(lap_id)},
                self._request_ctx(),
            )
        except ValueError as e:
            return self._send_json({"error": str(e)}, status=404)
        except Exception as e:
            sys.stderr.write("=== /api/analyze error ===\n")
            traceback.print_exc(file=sys.stderr)
            return self._send_json({"error": f"{type(e).__name__}: {e}"},
                                   status=500)

        try:
            payload = compute_single_lap_payload(
                track=track, lap_meta=lap_meta, lap_data=lap_data,
            )
        except Exception as e:
            sys.stderr.write("=== /api/analyze compute error ===\n")
            traceback.print_exc(file=sys.stderr)
            return self._send_json({"error": f"compute: {e}"}, status=500)

        # Audit log: every successful API analyse counts as a "view" event,
        # so we can show recent analyses in the admin Activity tab.
        try:
            ctx = self._request_ctx()
            AppState.db.add_event(
                kind="view_analysis",
                user_id=ctx.get("user_id"),
                user_email=ctx.get("user_email", ""),
                ip_address=ctx.get("ip_address", ""),
                detail=(f"lap_id={lap_id} "
                        f"track={(track.get('meta') or {}).get('TRACK','')} "
                        f"lap={lap_meta.get('lap_index')} "
                        f"t={payload['header']['lap_time']}").strip(),
                file_path="",
            )
        except Exception as e:
            sys.stderr.write(f"[event-log] view_analysis failed: {e}\n")

        # Enrich payload with the source descriptor for the SPA header.
        payload["source"] = {
            "kind": "library",
            "lap_id": lap_id,
        }
        return self._send_json(payload)

    # POST /api/analyze/upload — multipart upload, returns SPA payload.
    # Same flow as legacy /analyze upload path, but never produces a
    # persisted analysis artefact: just parses, computes, returns JSON.
    def _api_analyze_upload(self):
        try:
            form = parse_form(self)
        except UploadTooLarge as e:
            return self._send_json({"error": str(e)}, status=413)
        except Exception as e:
            return self._send_json({"error": f"Upload-Fehler: {e}"}, status=400)

        try:
            # Inject mode='upload' so the resolver takes the upload branch.
            form["mode"] = "upload"
            track, lap_meta, lap_data = resolve_lap_from_form(
                form, self._request_ctx(),
            )
        except ValueError as e:
            return self._send_json({"error": str(e)}, status=400)
        except Exception as e:
            sys.stderr.write("=== /api/analyze/upload error ===\n")
            traceback.print_exc(file=sys.stderr)
            return self._send_json(
                {"error": f"{type(e).__name__}: {e}"}, status=500)

        try:
            payload = compute_single_lap_payload(
                track=track, lap_meta=lap_meta, lap_data=lap_data,
            )
        except Exception as e:
            sys.stderr.write("=== /api/analyze/upload compute error ===\n")
            traceback.print_exc(file=sys.stderr)
            return self._send_json({"error": f"compute: {e}"}, status=500)

        try:
            ctx = self._request_ctx()
            AppState.db.add_event(
                kind="view_analysis",
                user_id=ctx.get("user_id"),
                user_email=ctx.get("user_email", ""),
                ip_address=ctx.get("ip_address", ""),
                detail=(f"upload src={track.get('source_file','')} "
                        f"lap={lap_meta.get('lap_index')} "
                        f"t={payload['header']['lap_time']}").strip(),
                file_path="",
            )
        except Exception as e:
            sys.stderr.write(f"[event-log] view_analysis(upload) failed: {e}\n")

        payload["source"] = {
            "kind": "upload",
            "filename": track.get("source_file", ""),
        }
        return self._send_json(payload)

    # --- Report serving
    def _serve_report(self, report_id: str, download: bool):
        if not UUID_RE.match(report_id):
            return self._send_text(HTTPStatus.BAD_REQUEST, "Invalid id")
        report_path = AppState.reports_dir / report_id / "report.html"
        if not report_path.is_file():
            return self._send_text(HTTPStatus.NOT_FOUND,
                                   "Report nicht gefunden.")
        content = report_path.read_bytes()
        if download:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="lap_compare_{report_id[:8]}.html"',
            )
        else:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            content = self._inject_toolbar(content, report_id)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _inject_topnav(self, content: bytes, current_path: str = "") -> bytes:
        """Insert the unified header into an HTML page right after <body>.
        Used by /report/<id> and /analysis/<id>. Identical look to every
        static page — same height, same items, same styling."""
        user = self._current_user()
        # The header builder also injects the necessary CSS variables it
        # depends on. Compare/analysis report pages have their own theme
        # CSS so we provide fallback values inline (already done in
        # HEADER_CSS via var(..., default)).
        header_html = build_header_html(user, current_path).encode("utf-8")
        body_open = re.search(rb"<body[^>]*>", content)
        if body_open:
            insert_at = body_open.end()
            return content[:insert_at] + header_html + content[insert_at:]
        return header_html + content

    def _inject_toolbar(self, content: bytes, report_id: str) -> bytes:
        # Top navigation (shared with analysis page)
        content = self._inject_topnav(content, f"/report/{report_id}")

        # Bottom floating toolbar — report-specific (download)
        toolbar = f"""
<style>
  #lc-toolbar{{position:fixed;bottom:24px;right:24px;z-index:1000;display:flex;gap:8px;font-family:'JetBrains Mono',monospace}}
  #lc-toolbar a{{background:#141414;color:#f5f5f0;border:1px solid #262626;padding:10px 16px;font-size:11px;letter-spacing:.15em;text-transform:uppercase;text-decoration:none;cursor:pointer;transition:border-color .15s,color .15s}}
  #lc-toolbar a:hover{{border-color:#00d4ff;color:#00d4ff}}
</style>
<div id="lc-toolbar">
  <a href="/download/{html.escape(report_id)}">↓ HTML DOWNLOAD</a>
</div>
""".encode("utf-8")

        idx = content.rfind(b"</body>")
        if idx < 0:
            return content + toolbar
        return content[:idx] + toolbar + content[idx:]

    # --- Low-level helpers
    def _send_html(self, content: bytes, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_text(self, status, msg):
        body = msg.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _no_content(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def _serve_static(self, rel_path: str):
        """v21.46 — Serve a file from webapp/. Whitelisted extensions,
        no path traversal (the regex in do_GET already excludes '..' but
        we double-check). Used for shared JS modules like speed_chart.js
        that the datenviewer and coach both pull in."""
        if ".." in rel_path.split("/"):
            return self._send_text(HTTPStatus.NOT_FOUND, "Not found")
        ext_to_ct = {
            ".js":  "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml; charset=utf-8",
            ".png": "image/png",
        }
        suffix = "." + rel_path.rsplit(".", 1)[-1].lower() if "." in rel_path else ""
        ct = ext_to_ct.get(suffix)
        if ct is None:
            return self._send_text(HTTPStatus.NOT_FOUND, "Not found")
        fp = STATIC_DIR / rel_path
        try:
            body = fp.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            return self._send_text(HTTPStatus.NOT_FOUND, "Not found")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        # Cache busting handled by versioning the URL when needed; for now
        # cache aggressively in the browser since the file rarely changes.
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)
