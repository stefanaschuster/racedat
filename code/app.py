"""Racedat auf nativeAI — Einstiegspunkt (uvicorn app:app).

Die komplette Anwendungslogik (Seiten, API, Auth, Parser, Reports) liegt
unverändert in webserver.py (WebHandler). Dieses Modul bindet sie an FastAPI:
jede Anfrage wird als HTTP-Request an den WebHandler übergeben, der in einem
Worker-Thread läuft; seine Antwort (Status, Header, Body, auch mehrere
Set-Cookie) wird 1:1 zurückgegeben. Statische Assets liefert StaticFiles.

Laufzeit-Konfiguration (.env):
  BASE_URL           öffentliche Adresse der App, z. B. https://<app>.<domain> (Verify-Links)
  BREVO_API_KEY      Brevo-API-Key (Registrierungsmails über HTTPS)
  MAIL_SENDER_EMAIL  verifizierter Brevo-Absender
  MAIL_SENDER_NAME   Anzeigename (optional)
  MAPTILER_KEY       optional, für die Kartenansicht
  MAX_UPLOAD_MB      Upload-Limit in MB (Standard 50)
  DEBUG_LOG          "1" für strukturierte Request-Logs auf stderr
  HANDLER_TIMEOUT_S  Watchdog: Neustart, wenn ein Request länger hängt (Standard 300)
Daten: $APP_DATA (sessions.db, originals/, reports/, legal_data.js, ...).
"""
import asyncio
import io
import faulthandler
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# --- Große Module können als Teile unter code/_parts/<modul>/pNN.txt liegen
# (der nativeAI-Connector schreibt pro Aufruf nur begrenzt viel). Dann werden
# sie hier zur Laufzeit zusammengesetzt; __file__ zeigt auf code/<modul>.py,
# damit relative Pfade (webapp/, thresholds.json) unverändert funktionieren.
import importlib.abc  # noqa: E402
import importlib.util  # noqa: E402

_PARTS = HERE / "_parts"


class _PartsFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path=None, target=None):
        if path is None and (_PARTS / name).is_dir():
            return importlib.util.spec_from_loader(
                name, self, origin=str(HERE / f"{name}.py"))
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        parts = sorted((_PARTS / module.__name__).glob("p*.txt"))
        src = b"".join(p.read_bytes() for p in parts).decode("utf-8")
        module.__file__ = str(HERE / f"{module.__name__}.py")
        exec(compile(src, module.__file__, "exec"), module.__dict__)


sys.meta_path.append(_PartsFinder())

import debuglog  # noqa: E402
import webserver  # noqa: E402
import mobile  # noqa: E402  Handy-Ansicht unter /m

DATA = Path(os.environ.get("APP_DATA", str(HERE.parent / "data")))
STATIC = HERE / "static"

# Obergrenze gleichzeitig laufender Handler (512 MB RAM für alle Apps).
_LIMITER = anyio.CapacityLimiter(3)  # große Uploads belegen mehrfach RAM
_MAX_BODY = webserver.MAX_UPLOAD_BYTES + 2 * 1024 * 1024
_DROP_REQ = {b"connection", b"transfer-encoding", b"content-length",
             b"keep-alive", b"upgrade", b"expect"}
_DROP_RESP = {"connection", "content-length", "server", "date",
              "transfer-encoding", "keep-alive"}

# --- Watchdog -----------------------------------------------------------------
# Hängt ein Handler (alle Plätze im _LIMITER belegt → App antwortet nicht mehr,
# /health aber schon), schreibt der Watchdog die Stacks aller Threads ins Log
# und beendet den Prozess; systemd startet ihn neu.
_HANG_S = int(os.environ.get("HANDLER_TIMEOUT_S", "300"))
_SLOW_S = 5          # ab hier landet ein Request mit Wartezeit/Laufzeit im Log
_LOOP_WARN_S = 10    # Ereignisschleife so lange ohne Reaktion → Stacks ins Log
_LOOP_KILL_S = 120   # … so lange → Prozess beenden, systemd startet neu
_ACTIVE: dict[int, tuple[float, str]] = {}
_ACTIVE_LOCK = threading.Lock()


def _watchdog():
    while True:
        time.sleep(10)
        now = time.monotonic()
        with _ACTIVE_LOCK:
            hung = [(now - t0, tgt) for t0, tgt in _ACTIVE.values()
                    if now - t0 > _HANG_S]
        if not hung:
            continue
        for age, tgt in hung:
            sys.stderr.write(f"[watchdog] Handler hängt seit {int(age)} s: {tgt}\n")
        sys.stderr.write("[watchdog] Thread-Stacks:\n")
        sys.stderr.flush()
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        sys.stderr.write("[watchdog] Prozess wird beendet (Neustart durch systemd)\n")
        sys.stderr.flush()
        os._exit(70)


def _dump(reason: str) -> None:
    sys.stderr.write(f"[watchdog] {reason} – Thread-Stacks:\n")
    sys.stderr.flush()
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    sys.stderr.flush()


def _loop_watch(loop: asyncio.AbstractEventLoop) -> None:
    """Prüft alle 5 s, ob die Ereignisschleife reagiert. Hängt sie, kommt
    kein Request mehr durch – auch /health nicht."""
    while True:
        time.sleep(5)
        ev = threading.Event()
        try:
            loop.call_soon_threadsafe(ev.set)
        except RuntimeError:      # Schleife beendet (Shutdown)
            return
        if ev.wait(_LOOP_WARN_S):
            continue
        _dump(f"Ereignisschleife reagiert seit {_LOOP_WARN_S} s nicht")
        if ev.wait(_LOOP_KILL_S - _LOOP_WARN_S):
            sys.stderr.write("[watchdog] Ereignisschleife reagiert wieder\n")
            continue
        _dump(f"Ereignisschleife reagiert seit {_LOOP_KILL_S} s nicht, Prozess wird beendet")
        os._exit(70)


class _BridgeHandler(webserver.WebHandler):
    """WebHandler ohne Socket: liest aus einem Puffer, schreibt in einen Puffer."""

    def __init__(self, raw: bytes, client_ip: str):
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.client_address = (client_ip or "", 0)
        self.request = self.connection = self.server = None
        self.close_connection = True
        self.handle_one_request()

    def finish(self):  # nichts zu schließen
        pass


def _legal_file() -> Path:
    p = DATA / "legal_data.js"
    return p if p.is_file() else STATIC / "legal_data.js"


def _legal_version() -> str:
    try:
        return str(int(_legal_file().stat().st_mtime))
    except OSError:
        return "0"


def _run_handler(method: str, target: str, headers, body: bytes,
                 client_ip: str, t_in: float) -> Response:
    key = threading.get_ident()
    t0 = time.monotonic()
    with _ACTIVE_LOCK:
        _ACTIVE[key] = (t0, f"{method} {target} ({client_ip})")
    try:
        return _run_handler_inner(method, target, headers, body, client_ip)
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.pop(key, None)
        dt = time.monotonic() - t0
        wait = t0 - t_in
        if dt + wait > _SLOW_S:
            # Warten = Zeit bis ein Platz im _LIMITER frei war; Handler = Rechenzeit
            with _ACTIVE_LOCK:
                busy = len(_ACTIVE)
            sys.stderr.write(f"[slow] {dt + wait:.1f} s (Warten {wait:.1f} s, Handler {dt:.1f} s, "
                             f"belegt {busy}/3) {method} {target} ({client_ip})\n")


def _run_handler_inner(method: str, target: str, headers, body: bytes,
                       client_ip: str) -> Response:
    head = [f"{method} {target} HTTP/1.1".encode("latin-1")]
    for k, v in headers:
        if k.lower() in _DROP_REQ:
            continue
        head.append(k + b": " + v)
    head.append(b"Content-Length: " + str(len(body)).encode())
    head.append(b"Connection: close")
    raw = b"\r\n".join(head) + b"\r\n\r\n" + body
    try:
        h = _BridgeHandler(raw, client_ip)
        out = h.wfile.getvalue()
    except Exception as e:  # Handler-Fehler dürfen den Worker nicht killen
        sys.stderr.write(f"[bridge] handler error: {e!r}\n")
        return Response("Internal Server Error", status_code=500,
                        media_type="text/plain")
    sep = out.find(b"\r\n\r\n")
    if sep < 0:
        return Response("Bad Gateway", status_code=502, media_type="text/plain")
    lines = out[:sep].decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    payload = out[sep + 4:]
    if target.split("?", 1)[0].rstrip("/") in ("/impressum", "/datenschutz"):
        # Adresse der Rechtstexte versionieren: ändert sich legal_data.js,
        # ändert sich die URL, und kein Browser behält eine alte Kopie.
        payload = payload.replace(
            b'src="/static/legal_data.js"',
            b'src="/static/legal_data.js?v=' + _legal_version().encode() + b'"')
    resp = Response(content=payload, status_code=status)
    raw_headers = []
    for ln in lines[1:]:
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        if k.strip().lower() in _DROP_RESP:
            continue
        raw_headers.append((k.strip().lower().encode("latin-1"),
                            v.strip().encode("latin-1")))
    raw_headers.append((b"content-length", str(len(payload)).encode()))
    resp.raw_headers = raw_headers
    return resp


@asynccontextmanager
async def lifespan(app: FastAPI):
    debuglog.configure(enabled=os.environ.get("DEBUG_LOG") == "1")
    DATA.mkdir(parents=True, exist_ok=True)
    webserver.AppState.init(DATA.resolve())  # Schema/Verzeichnisse idempotent
    threading.Thread(target=_watchdog, name="watchdog", daemon=True).start()
    threading.Thread(target=_loop_watch, args=(asyncio.get_running_loop(),),
                     name="loop-watch", daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None,
              openapi_url=None)


# --- Crawler ------------------------------------------------------------------
# 1) robots.txt: rechenintensive und private Seiten für alle Crawler gesperrt,
#    bekannte SEO-/KI-Crawler komplett.
# 2) Sperre: bekannte Crawler bekommen sofort 403 (sie halten sich oft nicht an
#    robots.txt); jeder andere Bot bekommt 403 auf den teuren Seiten.
#    Weitere Namen per .env: BLOCKED_BOTS=name1,name2

_HEAVY_PATHS = ("/analyze", "/analysis", "/compare", "/report", "/download",
                "/coach", "/api/", "/m/api/", "/sessions", "/admin",
                "/profile", "/login", "/register", "/verify", "/logout")

_BLOCKED_BOTS = [
    # SEO-Werkzeuge
    "semrushbot", "ahrefsbot", "mj12bot", "dotbot", "blexbot", "dataforseobot",
    "serpstatbot", "barkrowler", "seekportbot", "megaindex", "linkpadbot",
    "seznambot", "screaming frog", "sistrix", "siteauditbot", "rogerbot",
    # KI- und Datensammler
    "gptbot", "chatgpt-user", "oai-searchbot", "claudebot", "claude-web",
    "anthropic-ai", "ccbot", "bytespider", "amazonbot", "meta-externalagent",
    "facebookbot", "imagesiftbot", "diffbot", "omgili", "timpibot",
    "perplexitybot", "youbot", "cohere-ai", "petalbot", "applebot-extended",
    "google-extended",
    # Sonstige
    "zoominfobot", "awario", "magpie-crawler", "turnitinbot", "censysinspect",
    "scrapy",
]
_BLOCKED_BOTS += [b.strip().lower() for b in
                  os.environ.get("BLOCKED_BOTS", "").split(",") if b.strip()]
# Nur auf den teuren Seiten gesperrt (Skript-Clients bleiben für / und den
# Health-Check des Deploys erlaubt)
_GENERIC_BOT = ("bot", "crawl", "spider", "slurp", "fetcher", "scraper",
                "python-requests", "python-urllib", "go-http-client",
                "curl/", "wget/", "httpx", "aiohttp")

_ROBOTS_TXT = "\n".join(
    [f"User-agent: {name}\nDisallow: /\n" for name in (
        "SemrushBot", "AhrefsBot", "MJ12bot", "DotBot", "BLEXBot",
        "DataForSeoBot", "serpstatbot", "Barkrowler", "SeekportBot",
        "PetalBot", "GPTBot", "ClaudeBot", "CCBot", "Bytespider",
        "Amazonbot", "meta-externalagent", "ImagesiftBot", "PerplexityBot",
        "Google-Extended", "Applebot-Extended")]
    + ["User-agent: *"]
    + [f"Disallow: {p}" for p in _HEAVY_PATHS]
    + ["Crawl-delay: 10", ""])


def _is_heavy(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/")
               or (p.endswith("/") and path.startswith(p)) for p in _HEAVY_PATHS)


@app.middleware("http")
async def block_crawlers(request: Request, call_next):
    path = request.url.path
    if path == "/robots.txt" or path == "/health":
        return await call_next(request)
    ua = (request.headers.get("user-agent") or "").lower()
    if not ua:
        blocked = _is_heavy(path)
    elif any(b in ua for b in _BLOCKED_BOTS):
        blocked = True
    else:
        blocked = _is_heavy(path) and any(g in ua for g in _GENERIC_BOT)
    if blocked:
        return Response("Forbidden", status_code=403, media_type="text/plain")
    return await call_next(request)


@app.get("/robots.txt")
def robots_txt():
    return Response(_ROBOTS_TXT, media_type="text/plain; charset=utf-8")


@app.get("/health")
def health():
    return {"ok": True, "version": webserver.VERSION}


@app.get("/static/legal_data.js")
def legal_data():
    """Impressum/Datenschutz-Angaben: $APP_DATA/legal_data.js hat Vorrang
    (überlebt Code-Updates, wird von migrate_data.py aus dem alten Server
    übernommen), sonst die mitgelieferte Vorlage."""
    return Response(_legal_file().read_bytes(),
                    media_type="application/javascript; charset=utf-8",
                    headers={"Cache-Control": "no-cache"})


# Statische Assets (speed_chart.js, Handy-Ansicht unter static/m/, ...)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Handy-Ansicht (/m und /m/api/...), vor der Brücke zum WebHandler
app.include_router(mobile.router)


@app.api_route("/{path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD",
                        "OPTIONS"])
async def bridge(request: Request, path: str):
    t_in = time.monotonic()
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > _MAX_BODY:
        return Response("Upload zu groß (max. " + str(webserver.MAX_UPLOAD_BYTES // 1048576) + " MB).",
                        status_code=413, media_type="text/plain")
    body = await request.body()
    if len(body) > _MAX_BODY:
        return Response("Upload zu groß (max. " + str(webserver.MAX_UPLOAD_BYTES // 1048576) + " MB).",
                        status_code=413, media_type="text/plain")
    if path == "":
        # Startseite: Handys landen in der Handy-Ansicht (außer sie haben
        # dort "Desktop-Version" gewählt)
        redirect = mobile.mobile_redirect(request)
        if redirect is not None:
            return redirect
    raw_path = request.scope.get("raw_path") or request.url.path.encode()
    target = raw_path.decode("latin-1")
    if request.url.query:
        target += "?" + request.url.query
    client_ip = request.client.host if request.client else ""
    return await anyio.to_thread.run_sync(
        _run_handler, request.method, target, request.headers.raw, body,
        client_ip, t_in, limiter=_LIMITER)
