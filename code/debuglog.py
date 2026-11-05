"""debuglog — opt-in, structured logging for the webserver.

v22.1 — Stefan wollte "viel mehr logging" via --debug-log flag. Format:
logfmt (key=value, key="value with spaces"), eine Zeile pro Event,
nach stderr. Lesbar im Terminal, aber auch grep/awk/cut-freundlich.

Beispiel-Output:
    2026-05-19T13:01:22Z lvl=info ev=req method=GET path=/sessions status=200 dur_ms=42 user=stefan@example.com ip=10.0.0.5
    2026-05-19T13:01:23Z lvl=info ev=auth.login.ok user=stefan@example.com ip=10.0.0.5
    2026-05-19T13:01:30Z lvl=info ev=action.lap.delete user=stefan@example.com ip=10.0.0.5 lap_id=42 session_id=abc-123
    2026-05-19T13:01:30Z lvl=warn ev=action.lap.delete.denied user=other@example.com ip=10.0.0.6 lap_id=42 reason=not_owner

Design:
- Globaler enabled-Flag. Wenn aus, ist `log()` ein no-op (kostengünstig).
- logfmt-Quoting: Strings mit Whitespace, "=" oder " in doppelte Quotes,
  innenliegende " und \\ werden escaped. None/leerer-String wird übersprungen
  damit Logs nicht von leeren Feldern verrauscht werden.
- Reihenfolge: ts, lvl, ev kommen zuerst (für Augen), dann die Felder in
  insertion-order (sodass user/ip früh kommen wenn die Caller sie früh
  übergeben).
- Thread-safe via Lock — mehrere Listener-Threads schreiben gleichzeitig.

Tests: tests/test_debug_log.py
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from typing import Any, IO, Optional


# ---------- module-global state -----------------------------------------------

_enabled: bool = False
_stream: IO[str] = sys.stderr
_lock = threading.Lock()


def configure(enabled: bool, stream: Optional[IO[str]] = None) -> None:
    """Enable or disable debug logging. If stream is None, stderr is used.

    Called once from main() during startup; tests use this to redirect to
    a StringIO."""
    global _enabled, _stream
    _enabled = bool(enabled)
    if stream is not None:
        _stream = stream
    else:
        _stream = sys.stderr


def is_enabled() -> bool:
    return _enabled


# ---------- logfmt formatting -------------------------------------------------

# Characters that force quoting: space, equals, double-quote.
_NEEDS_QUOTING = (" ", "\t", "=", '"')


def _format_value(v: Any) -> str:
    """Render a single value as a logfmt token.

    - None and "" caller-side filtered out before reaching here; if they
      sneak through we render as empty string in quotes so the parser
      still sees the key.
    - bool → true/false (lowercase, conventional for logfmt)
    - int/float → str(v)
    - everything else → str(v), quoted if it contains space/=/"
    """
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    s = str(v)
    # Replace newlines/CR with their escape sequences — a multi-line value
    # would otherwise break the "one event = one line" invariant.
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
    if any(c in s for c in _NEEDS_QUOTING) or s == "":
        s = s.replace('"', '\\"')
        return f'"{s}"'
    return s


def _format_key(k: str) -> str:
    """Sanitise a key. Keys may not contain whitespace/equals/quotes — if
    a caller passes something weird we strip the offending chars rather
    than emit invalid logfmt."""
    out = []
    for c in k:
        if c.isspace() or c in ("=", '"'):
            out.append("_")
        else:
            out.append(c)
    return "".join(out) or "_"


def _now_iso() -> str:
    """UTC timestamp, second-precision, ISO-8601 with Z. Second precision
    is enough for ops; if we ever need ms we can switch to %f."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- public log entry point --------------------------------------------

def log(event: str, *, level: str = "info", **fields: Any) -> None:
    """Emit a single logfmt line. No-op if logging is disabled.

    Args:
        event: short hierarchical name like "req", "auth.login.ok",
               "action.lap.delete". Lower-case, dot-separated.
        level: "info", "warn", "error" (free-form, but stick to these).
        **fields: arbitrary key=value pairs. Keys with None or "" values
                  are dropped to keep logs sparse.
    """
    if not _enabled:
        return
    parts = [
        f"ts={_now_iso()}",
        f"lvl={_format_value(level)}",
        f"ev={_format_value(event)}",
    ]
    for k, v in fields.items():
        if v is None or v == "":
            continue
        parts.append(f"{_format_key(k)}={_format_value(v)}")
    line = " ".join(parts) + "\n"
    # Single write under lock — avoids interleaved bytes between threads.
    # We don't flush explicitly: stderr is line-buffered when attached to
    # a TTY and unbuffered otherwise, which is what we want.
    with _lock:
        try:
            _stream.write(line)
        except Exception:
            # Logging must never crash the request path. If stderr is
            # somehow broken (closed, pipe gone) we silently drop.
            pass


# ---------- helper for request context ----------------------------------------

def fields_from_ctx(ctx: Optional[dict]) -> dict:
    """Project a request_ctx dict (as produced by WebHandler._request_ctx())
    into a {user, ip} dict suitable for splatting into log()."""
    if not ctx:
        return {}
    out = {}
    email = ctx.get("user_email")
    if email:
        out["user"] = email
    ip = ctx.get("ip_address")
    if ip:
        out["ip"] = ip
    return out
