"""Racedat — Handy-Ansicht unter /m.

Eigene, schlanke Oberfläche fürs Handy (code/static/m/). Dieses Modul liefert
die Seite und ein kleines JSON-API, das auf dieselben Daten und Funktionen wie
die Desktop-Seiten zugreift (webserver.AppState, step1_upload_session, …).

Schreibende Aktionen (Login, Speichern, Löschen, Profil, Motorräder, Schritt 2
des Uploads) gehen bewusst an die bestehenden Formular-Endpunkte; damit gelten
dieselben Prüfungen wie am Desktop. Neu ist nur Schritt 1 des Uploads als JSON.

Diagramm-Ansichten (Datenviewer, Vergleich, AI-Coach) zeigt die Handy-Ansicht
in einem Rahmen mit den bestehenden Seiten an, ohne Desktop-Navigation.
"""
from __future__ import annotations

import os
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

import webserver as ws

HERE = Path(__file__).resolve().parent
INDEX = HERE / "static" / "m" / "index.html"
DESKTOP_COOKIE = "rd_desktop"

router = APIRouter()
_UPLOAD_LIMITER = anyio.CapacityLimiter(1)   # Parsen großer Dateien kostet RAM


# ---------------------------------------------------------------- Hilfen

def current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(ws.AUTH_COOKIE_NAME)
    result = ws._verify_token(token) if token else None
    if not result:
        return None
    uid, _exp = result
    user = ws.AppState.db.get_user(uid)
    if not user:
        return None
    return {"id": user["id"], "email": user["email"], "is_admin": bool(user["is_admin"])}


def err(status: int, text: str) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=status)


def display_name(user_id: Optional[int], fallback: str = "") -> str:
    """Wie die öffentliche Profilseite: driver_name, sonst Teil vor dem @."""
    if user_id is None:
        return fallback
    try:
        prof = ws.AppState.db.get_profile(int(user_id))
        name = (prof.get("driver_name") or "").strip()
        if name:
            return name
        u = ws.AppState.db.get_user(int(user_id)) or {}
        email = u.get("email") or ""
        return email.split("@", 1)[0] if "@" in email else (fallback or f"Fahrer #{user_id}")
    except Exception:
        return fallback


def lap_row(lp: dict, user: Optional[dict], medals: dict, per_session: Counter,
            names: dict, roles: dict) -> dict:
    uid = lp.get("user_id")
    own = bool(user) and (user["is_admin"] or (uid is not None and uid == user["id"]))
    if uid is not None and uid not in names:
        names[uid] = display_name(uid)
    s = roles.get(int(lp["lap_id"])) or {}
    return {
        "lap_id": int(lp["lap_id"]),
        "lap_number": lp.get("lap_number"),
        "duration_s": float(lp["duration_s"]),
        "time": ws.fmt_seconds(float(lp["duration_s"])),
        "session_id": lp["session_id"],
        "session_laps": per_session.get(lp["session_id"], 1),
        "driver": lp.get("driver") or "",
        "bike": lp.get("bike") or "",
        "track": lp.get("track") or "",
        "date": lp.get("session_date") or "",
        "notes": lp.get("notes") or "",
        "user_id": uid,
        "owner": names.get(uid, "") if uid is not None else "",
        "mine": bool(user) and uid is not None and uid == user["id"],
        "can_edit": own,
        "medal": medals.get(int(lp["lap_id"]), 0),
        "roles": len(s.get("assigned_role_ids") or []),
        "total_roles": int(s.get("total_roles") or 0),
    }


def all_laps(user: Optional[dict], only_user: Optional[int] = None) -> list[dict]:
    laps = ws.AppState.db.list_all_laps_flat()
    if only_user is not None:
        laps = [lp for lp in laps if lp.get("user_id") == only_user]
    per_session = Counter(lp["session_id"] for lp in laps)
    medals = ws.medal_map_from_top_n(ws.AppState.db.global_top_n_per_track(3))
    try:
        roles = ws.AppState.db.get_channel_summary([int(lp["lap_id"]) for lp in laps])
    except Exception:
        roles = {}
    names: dict = {}
    return [lap_row(lp, user, medals, per_session, names, roles) for lp in laps]


# ---------------------------------------------------------------- Seite

@router.get("/m")
@router.get("/m/")
def page(request: Request) -> Response:
    resp = Response(INDEX.read_bytes(), media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-cache"})
    # Wer die Handy-Ansicht öffnet, will sie auch auf "/" wieder haben
    resp.delete_cookie(DESKTOP_COOKIE, path="/")
    return resp


@router.get("/m/desktop")
def to_desktop() -> Response:
    """Zur Desktop-Ansicht wechseln; "/" leitet Handys danach nicht mehr um."""
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(DESKTOP_COOKIE, "1", max_age=180 * 86400, path="/", samesite="lax")
    return resp


# ---------------------------------------------------------------- Lesen

@router.get("/m/api/me")
def me(request: Request) -> JSONResponse:
    user = current_user(request)
    if not user:
        return JSONResponse({"user": None})
    prof = ws.AppState.db.get_profile(user["id"])
    bike = ws.AppState.db.get_current_bike(user["id"])
    return JSONResponse({"user": {
        "id": user["id"],
        "email": user["email"],
        "is_admin": user["is_admin"],
        "name": display_name(user["id"]),
        "driver_name": prof.get("driver_name") or "",
        "image": prof.get("image_path") or "",
        "current_bike": bike["name"] if bike else "",
    }})


@router.get("/m/api/laps")
def laps(request: Request) -> JSONResponse:
    try:
        return JSONResponse({"laps": all_laps(current_user(request))})
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return err(500, f"Runden konnten nicht geladen werden: {e}")


@router.get("/m/api/records")
def records(request: Request) -> JSONResponse:
    flat = {int(lp["lap_id"]): lp for lp in ws.AppState.db.list_all_laps_flat()}
    names: dict = {}
    out = []
    for tr in ws.AppState.db.global_top_n_per_track(3):
        entries = []
        for e in tr.get("entries") or []:
            lp = flat.get(int(e["lap_id"])) or {}
            uid = e.get("user_id")
            if uid is not None and uid not in names:
                names[uid] = (e.get("driver_name") or "").strip() or display_name(uid)
            entries.append({
                "rank": int(e["rank"]),
                "lap_id": int(e["lap_id"]),
                "time": ws.fmt_seconds(float(e["duration_s"])),
                "user_id": uid,
                "name": names.get(uid) or lp.get("driver") or "—",
                "bike": lp.get("bike") or "",
                "date": lp.get("session_date") or "",
            })
        out.append({"track": tr["track"], "entries": sorted(entries, key=lambda x: x["rank"])})
    return JSONResponse({"records": out})


@router.get("/m/api/profile")
def own_profile(request: Request) -> JSONResponse:
    user = current_user(request)
    if not user:
        return err(401, "Bitte anmelden")
    prof = ws.AppState.db.get_profile(user["id"])
    bikes = ws.AppState.db.list_bikes(user["id"])
    return JSONResponse({
        "driver_name": prof.get("driver_name") or "",
        "image": prof.get("image_path") or "",
        "email": user["email"],
        "bikes": [{"id": b["id"], "name": b["name"], "image": b.get("image_path") or "",
                   "is_current": bool(b.get("is_current"))} for b in bikes],
    })


@router.get("/m/api/driver/{user_id}")
def driver(user_id: int, request: Request) -> JSONResponse:
    if not ws.AppState.db.get_user(user_id):
        return err(404, "Profil nicht gefunden")
    prof = ws.AppState.db.get_profile(user_id)
    bikes = ws.AppState.db.list_bikes(user_id)
    viewer = current_user(request)
    return JSONResponse({
        "user_id": user_id,
        "name": display_name(user_id),
        "image": prof.get("image_path") or "",
        "is_self": bool(viewer) and viewer["id"] == user_id,
        "bikes": [{"name": b["name"], "image": b.get("image_path") or "",
                   "is_current": bool(b.get("is_current"))} for b in bikes],
        "laps": all_laps(viewer, only_user=user_id),
    })


@router.get("/m/api/roles")
def roles() -> JSONResponse:
    return JSONResponse({"roles": [
        {"id": r["id"], "label": r.get("label", r["id"]), "description": r.get("description", "")}
        for r in ws.CHANNEL_ROLES
    ]})


# ---------------------------------------------------------------- Upload, Schritt 1

def _step1(form: dict, user_id: int) -> dict:
    pending_id = ws.step1_upload_session(form, user_id=user_id)
    with ws.PENDING_LOCK:
        p = dict(ws.PENDING_SESSIONS[pending_id])
    available = p.get("available_channels") or []
    role_list = []
    for role in ws.CHANNEL_ROLES:
        role_list.append({
            "id": role["id"],
            "label": role.get("label", role["id"]),
            "description": role.get("description", ""),
            "suggested": ws.suggest_channel(role, available) or "",
        })
    laps_sorted = sorted(p["laps"], key=lambda lp: lp["duration_s"])
    return {
        "pending_id": pending_id,
        "filename": p["original_filename"],
        "driver": p["driver"], "bike": p["bike"], "track": p["track"],
        "session_date": p["session_date"], "notes": p["notes"],
        "auto": p.get("auto_sources") or {},
        "laps": [{"lap_number": lp["lap_number"], "duration_s": lp["duration_s"],
                  "time": ws.fmt_seconds(lp["duration_s"])} for lp in laps_sorted],
        "channels": [{"id": c["id"], "name": c["name"], "unit": c.get("unit") or ""} for c in available],
        "roles": role_list,
    }


@router.post("/m/api/upload")
async def upload(request: Request) -> JSONResponse:
    """Rohdaten der Datei im Body, Name und Metadaten als Query-Parameter."""
    user = current_user(request)
    if not user:
        return err(401, "Bitte anmelden")
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > ws.MAX_UPLOAD_BYTES:
        return err(413, f"Datei zu groß (max. {ws.MAX_UPLOAD_BYTES // 1048576} MB)")
    data = await request.body()
    if len(data) > ws.MAX_UPLOAD_BYTES:
        return err(413, f"Datei zu groß (max. {ws.MAX_UPLOAD_BYTES // 1048576} MB)")
    if not data:
        return err(400, "Bitte eine Datei auswählen.")
    q = request.query_params
    name = os.path.basename(q.get("name", "") or "")
    form: dict[str, Any] = {"file": (name, data)}
    for key in ("driver", "bike", "track", "session_date", "notes"):
        form[key] = (q.get(key) or "")[:2000]
    # Wie am Desktop: leere Felder aus dem Profil vorbelegen
    if not form["driver"]:
        form["driver"] = (ws.AppState.db.get_profile(user["id"]).get("driver_name") or "")
    if not form["bike"]:
        cur = ws.AppState.db.get_current_bike(user["id"])
        form["bike"] = cur["name"] if cur else ""
    try:
        result = await anyio.to_thread.run_sync(_step1, form, user["id"], limiter=_UPLOAD_LIMITER)
    except ValueError as e:
        return err(400, str(e))
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return err(500, f"Interner Fehler: {type(e).__name__}: {e}")
    try:
        ws.debuglog.log("action.session.upload.step1.ok", user=user["email"],
                        pending_id=result["pending_id"], via="mobile")
    except Exception:
        pass
    return JSONResponse(result)


# ---------------------------------------------------------------- Weiche auf "/"

MOBILE_UA = ("iphone", "ipod", "android", "mobile", "windows phone", "blackberry", "opera mini")


def wants_mobile(request: Request) -> bool:
    if request.cookies.get(DESKTOP_COOKIE):
        return False
    ua = (request.headers.get("user-agent") or "").lower()
    if "ipad" in ua or ("android" in ua and "mobile" not in ua):
        return False   # Tablets: Desktop-Ansicht passt
    return any(k in ua for k in MOBILE_UA)


def mobile_redirect(request: Request) -> Optional[Response]:
    if request.method == "GET" and wants_mobile(request):
        target = "/m"
        if request.url.query:
            target += "?" + request.url.query
        return RedirectResponse(target, status_code=302)
    return None


__all__ = ["router", "mobile_redirect"]
