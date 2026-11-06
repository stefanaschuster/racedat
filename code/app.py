"""Racedat auf nativeAI — Einstiegspunkt (uvicorn app:app).

Die komplette Anwendungslogik (Seiten, API, Auth, Parser, Reports) liegt
unverändert in webserver.py (WebHandler). Dieses Modul bindet sie an FastAPI:
jede Anfrage wird als HTTP-Request an den WebHandler übergeben, der in einem
Worker-Thread läuft; seine Antwort (Status, Header, Body, auch mehrere
Set-Cookie) wird 1:1 zurückgegeben. Statische Assets liefert StaticFiles.

Laufzeit-Konfiguration (.env):
  BASE_URL           https://<app>.nativeai.digitalsandkasten.de (Verify-Links)
  BREVO_API_KEY      Brevo-API-Key (Registrierungsmails über HTTPS)
  MAIL_SENDER_EMAIL  verifizierter Brevo-Absender
  MAIL_SENDER_NAME   Anzeigename (optional)
  MAPTILER_KEY       optional, für die Kartenansicht
  MAX_UPLOAD_MB      Upload-Limit in MB (Standard 50)
  DEBUG_LOG          "1" für strukturierte Request-Logs auf stderr
Daten: $APP_DATA (sessions.db, originals/, reports/, ...).
"""
import io
import os
import sys
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

DATA = Path(os.environ.get("APP_DATA", str(HERE.parent / "data")))
STATIC = HERE / "static"

# Obergrenze gleichzeitig laufender Handler (512 MB RAM für alle Apps).
_LIMITER = anyio.CapacityLimiter(3)  # große Uploads belegen mehrfach RAM
_MAX_BODY = webserver.MAX_UPLOAD_BYTES + 2 * 1024 * 1024
_DROP_REQ = {b"connection", b"transfer-encoding", b"content-length",
             b"keep-alive", b"upgrade", b"expect"}
_DROP_RESP = {"connection", "content-length", "server", "date",
              "transfer-encoding", "keep-alive"}


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


def _run_handler(method: str, target: str, headers, body: bytes,
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
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None,
              openapi_url=None)


@app.get("/health")
def health():
    return {"ok": True, "version": webserver.VERSION}


# Statische Assets (speed_chart.js, legal_data.js, ...)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.api_route("/{path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD",
                        "OPTIONS"])
async def bridge(request: Request, path: str):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > _MAX_BODY:
        return Response("Upload zu groß (max. " + str(webserver.MAX_UPLOAD_BYTES // 1048576) + " MB).",
                        status_code=413, media_type="text/plain")
    body = await request.body()
    if len(body) > _MAX_BODY:
        return Response("Upload zu groß (max. " + str(webserver.MAX_UPLOAD_BYTES // 1048576) + " MB).",
                        status_code=413, media_type="text/plain")
    raw_path = request.scope.get("raw_path") or request.url.path.encode()
    target = raw_path.decode("latin-1")
    if request.url.query:
        target += "?" + request.url.query
    client_ip = request.client.host if request.client else ""
    return await anyio.to_thread.run_sync(
        _run_handler, request.method, target, request.headers.raw, body,
        client_ip, limiter=_LIMITER)
