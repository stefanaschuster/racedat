"""v21.35 — End-to-end test for the admin channel-role editing flow.

Spins up the webserver in a background thread, creates a test admin
user + a synthetic lap directly via the DB, then exercises:
    GET  /api/laps/<id>/channel-roles       (admin reads current state)
    POST /api/laps/<id>/channel-roles       (admin writes new assignment)
    GET  /api/laps/<id>/channel-roles       (re-read confirms persistence)

Also covers:
    - Non-admin gets 403 on both routes
    - Unauthenticated gets 401
    - Empty-assignment POST clears the dict entirely
    - Unknown role_ids and unknown channel_ids are rejected silently
"""

import json
import os
import pickle
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import http.cookiejar
import http.client
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def setup_server(tmpdir):
    """Start the webserver in a background thread on a random free port.
    Returns (base_url, db, server). The caller is responsible for shutting
    down the server."""
    import webserver
    from pathlib import Path

    data_dir = Path(tmpdir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    webserver.AppState.init(data_dir)

    server = webserver._make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    # Wait until the server is ready
    for _ in range(40):
        try:
            urllib.request.urlopen(base + "/favicon.ico", timeout=0.2).close()
            break
        except Exception:
            time.sleep(0.05)
    return base, webserver.AppState.db, server


def make_lap(db, with_channels=True, with_roles=None, owner_id=None):
    """Insert a synthetic lap directly via DB methods. Returns lap_id.

    owner_id=None creates an orphan/anonymous lap (admins only).
    owner_id=<int> creates a lap owned by that user (admin OR owner).
    """
    n = 500
    t = np.linspace(0.0, 30.0, n)
    extra_channels = {}
    if with_channels:
        extra_channels = {
            "ch_p_brake_fr": {
                "name": "p_brake_fr", "unit": "bar",
                "data": np.linspace(0, 10, n),
            },
            "ch_phi_lean": {
                "name": "phi_lean", "unit": "deg",
                "data": np.linspace(-30, 30, n),
            },
            "ch_tpd": {
                "name": "tpd", "unit": "%",
                "data": np.linspace(0, 100, n),
            },
        }
    lap_data = {
        "time":           t,
        "lat":            np.linspace(45.0, 45.001, n),
        "lon":            np.linspace(11.0, 11.001, n),
        "speed":          np.full(n, 30.0),
        "distance":       np.linspace(0, 1000, n),
        "duration":       30.0,
        "total_distance": 1000.0,
        "extra_channels": extra_channels,
    }
    if with_roles:
        lap_data["channel_roles"] = with_roles
    session_id = db.create_session(
        original_filename="x.xrk", file_path="/tmp/x.xrk",
        user_id=owner_id, driver="t", bike="t", track="t",
        session_date="2026-05-15", notes="", format="xrk",
    )
    return db.add_lap(session_id, 1, 30.0, lap_data)


def login(base, jar, email, password):
    """Log into the test server, populating the cookie jar."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = urllib.parse.urlencode(
        {"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        base + "/login",
        data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        resp = opener.open(req, timeout=2)
        resp.close()
    except urllib.error.HTTPError as e:
        # Login uses a 303 redirect on success → urllib follows; on failure
        # it returns the form page (200). Either way no exception expected.
        e.close()
    return opener


def get_json(opener, url):
    try:
        resp = opener.open(url, timeout=2)
        status = resp.getcode()
        body = resp.read().decode("utf-8")
        resp.close()
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode("utf-8")
        e.close()
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, {"raw": body}


def post_form(opener, url, data: dict):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        resp = opener.open(req, timeout=2)
        status = resp.getcode()
        body_text = resp.read().decode("utf-8")
        resp.close()
    except urllib.error.HTTPError as e:
        status = e.code
        body_text = e.read().decode("utf-8")
        e.close()
    try:
        return status, json.loads(body_text)
    except json.JSONDecodeError:
        return status, {"raw": body_text}


def main():
    tmpdir = tempfile.mkdtemp(prefix="lap_test_")
    try:
        base, db, server = setup_server(tmpdir)
        print(f"== Server up at {base} ==")

        # Seed users
        db.create_user(email="admin@x", password="pw_admin", is_admin=True)
        db.create_user(email="user@x",  password="pw_user",  is_admin=False)

        # --- 1) Unauthenticated GET → 401 ---
        print("\n== Unauthenticated GET ==")
        lap_id = make_lap(db)
        nojar = http.cookiejar.CookieJar()
        nopener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(nojar))
        st, data = get_json(nopener, f"{base}/api/laps/{lap_id}/channel-roles")
        check("anon GET → 401", st == 401, f"got {st}")
        check("anon GET → ok=False", data.get("ok") is False)

        # --- 2) Non-admin GET → 403 ---
        print("\n== Non-admin GET ==")
        user_jar = http.cookiejar.CookieJar()
        user_opener = login(base, user_jar, "user@x", "pw_user")
        st, data = get_json(user_opener, f"{base}/api/laps/{lap_id}/channel-roles")
        check("non-admin GET → 403", st == 403, f"got {st}")

        # --- 3) Admin GET on lap without prior assignment ---
        print("\n== Admin GET (fresh lap) ==")
        admin_jar = http.cookiejar.CookieJar()
        admin_opener = login(base, admin_jar, "admin@x", "pw_admin")
        st, data = get_json(admin_opener, f"{base}/api/laps/{lap_id}/channel-roles")
        check("admin GET → 200", st == 200, f"got {st}")
        check("ok=True", data.get("ok") is True)
        check("channel_roles starts empty", data.get("channel_roles") == {})
        check("available_channels has 3 entries",
              len(data.get("available_channels") or []) == 3)
        registry = data.get("registry") or []
        # v21.39 — registry size is now 8 (added 4 electronics roles) but we
        # avoid hardcoding the number; just assert it matches the imported
        # ROLES list so future role additions don't require a test edit.
        from parsers.channel_roles import ROLES as _ROLES_chk
        check(f"registry size matches ROLES ({len(_ROLES_chk)})",
              len(registry) == len(_ROLES_chk))
        # Suggestions are pre-computed server-side
        sugs = {r["id"]: r.get("suggested") for r in registry}
        check("brake_pressure suggested ch_p_brake_fr",
              sugs.get("brake_pressure") == "ch_p_brake_fr")
        check("lean suggested ch_phi_lean",
              sugs.get("lean") == "ch_phi_lean")
        check("throttle suggested ch_tpd",
              sugs.get("throttle") == "ch_tpd")

        # --- 4) Admin POST: assign all three ---
        print("\n== Admin POST: assign ==")
        st, data = post_form(admin_opener, f"{base}/api/laps/{lap_id}/channel-roles", {
            "role_brake_pressure": "ch_p_brake_fr",
            "role_lean":           "ch_phi_lean",
            "role_throttle":       "ch_tpd",
            "role_throttle_butterfly": "",
        })
        check("admin POST → 200", st == 200, f"got {st}, body={data}")
        check("POST ok=True", data.get("ok") is True)
        cr = data.get("channel_roles") or {}
        check("returned brake_pressure", cr.get("brake_pressure") == "ch_p_brake_fr")
        check("returned lean", cr.get("lean") == "ch_phi_lean")
        check("returned throttle", cr.get("throttle") == "ch_tpd")
        check("returned without empty throttle_butterfly",
              "throttle_butterfly" not in cr)

        # --- 5) Re-GET confirms persistence ---
        print("\n== Re-GET confirms persistence ==")
        st, data = get_json(admin_opener, f"{base}/api/laps/{lap_id}/channel-roles")
        check("re-GET ok", st == 200 and data.get("ok") is True)
        cr2 = data.get("channel_roles") or {}
        check("persisted brake_pressure",
              cr2.get("brake_pressure") == "ch_p_brake_fr")
        check("persisted lean", cr2.get("lean") == "ch_phi_lean")
        check("persisted throttle", cr2.get("throttle") == "ch_tpd")

        # --- 6) Re-confirm via DB get_lap directly ---
        print("\n== DB direct read ==")
        lap_row = db.get_lap(lap_id)
        check("DB lap_data has channel_roles",
              "channel_roles" in (lap_row["lap_data"] or {}))
        check("DB persisted dict matches",
              lap_row["lap_data"].get("channel_roles") == {
                  "brake_pressure": "ch_p_brake_fr",
                  "lean": "ch_phi_lean",
                  "throttle": "ch_tpd",
              })

        # --- 7) POST with unknown role + unknown channel → rejected silently ---
        print("\n== Sanitisation: bad role + bad channel ==")
        st, data = post_form(admin_opener, f"{base}/api/laps/{lap_id}/channel-roles", {
            "role_lean":            "ch_phi_lean",     # OK
            "role_made_up_role":    "ch_phi_lean",     # unknown role → drop
            "role_throttle":        "ch_does_not_exist",  # unknown channel → drop
            "role_brake_pressure":  "",                # cleared
            "role_throttle_butterfly": "",
        })
        check("POST ok", st == 200 and data.get("ok"))
        cr3 = data.get("channel_roles") or {}
        check("only lean retained", cr3 == {"lean": "ch_phi_lean"},
              f"got {cr3}")

        # --- 8) Clear all → dict gone from blob ---
        print("\n== Clear all ==")
        st, data = post_form(admin_opener, f"{base}/api/laps/{lap_id}/channel-roles", {
            "role_brake_pressure": "",
            "role_lean":           "",
            "role_throttle":       "",
            "role_throttle_butterfly": "",
        })
        check("clear OK", st == 200 and data.get("ok"))
        check("cleared dict empty", data.get("channel_roles") == {})
        # Verify the key was popped from the blob (not just left as {})
        lap_row = db.get_lap(lap_id)
        check("channel_roles key absent in blob",
              "channel_roles" not in lap_row["lap_data"])

        # --- 9) Non-admin POST → 403 ---
        print("\n== Non-admin POST ==")
        st, data = post_form(user_opener, f"{base}/api/laps/{lap_id}/channel-roles", {
            "role_lean": "ch_phi_lean",
        })
        check("non-admin POST → 403", st == 403, f"got {st}")

        # --- 10) Lap-id 0 (non-existent) → 404 ---
        print("\n== Non-existent lap ==")
        st, data = get_json(admin_opener, f"{base}/api/laps/999999/channel-roles")
        check("GET 999999 → 404", st == 404, f"got {st}")
        st, data = post_form(admin_opener, f"{base}/api/laps/999999/channel-roles", {
            "role_lean": "ch_phi_lean",
        })
        check("POST 999999 → 404", st == 404, f"got {st}")

        # --- 11) Lap with no extra channels → registry returns suggestions=None,
        # available is empty ---
        print("\n== Lap without channels ==")
        empty_lap = make_lap(db, with_channels=False)
        st, data = get_json(admin_opener, f"{base}/api/laps/{empty_lap}/channel-roles")
        check("GET empty-lap ok", st == 200 and data.get("ok"))
        check("empty available_channels",
              data.get("available_channels") == [])
        check("all registry suggestions are None",
              all(r.get("suggested") is None for r in (data.get("registry") or [])))

        # --- 12) Audit event was logged ---
        print("\n== Audit log ==")
        # Pull last few events
        with db._cur() as cur:
            cur.execute(
                "SELECT kind, detail FROM events "
                "WHERE kind='lap_channel_roles_edit' "
                "ORDER BY id DESC LIMIT 5")
            audit_rows = [dict(r) for r in cur.fetchall()]
        check(f"audit events recorded ({len(audit_rows)})",
              len(audit_rows) >= 3)

        # --- 13) v21.37 — Owner may GET/POST their own lap's channel roles ---
        print("\n== Owner can edit own lap (v21.37) ==")
        # Resolve the user id for user@x and create a lap owned by them
        with db._cur() as cur:
            cur.execute("SELECT id FROM users WHERE email='user@x'")
            user_x_id = cur.fetchone()["id"]
        owned_lap = make_lap(db, owner_id=user_x_id)

        # GET as the owner → 200, channel_roles starts empty
        st, data = get_json(user_opener,
                            f"{base}/api/laps/{owned_lap}/channel-roles")
        check("owner GET own lap → 200", st == 200, f"got {st}")
        check("owner GET ok=True", data.get("ok") is True)
        check("owner GET channel_roles empty", data.get("channel_roles") == {})

        # POST as the owner → 200, change persists
        st, data = post_form(user_opener,
                             f"{base}/api/laps/{owned_lap}/channel-roles",
                             {"role_lean": "ch_phi_lean"})
        check("owner POST own lap → 200", st == 200, f"got {st}")
        check("owner POST ok=True", data.get("ok") is True)
        check("owner POST returns lean",
              (data.get("channel_roles") or {}).get("lean") == "ch_phi_lean")

        # Re-GET as owner confirms persistence
        st, data = get_json(user_opener,
                            f"{base}/api/laps/{owned_lap}/channel-roles")
        check("owner re-GET sees own change",
              (data.get("channel_roles") or {}).get("lean") == "ch_phi_lean")

        # Also: session-meta edit for the same owner's session
        # (we need the session_id of the owned lap)
        lap_row = db.get_lap(owned_lap)
        sid = lap_row["session_id"]
        st, data = post_form(user_opener, f"{base}/sessions/{sid}/edit", {
            "driver": "Stefan", "bike": "M1000RR", "track": "TestStrecke",
            "session_date": "", "notes": "edited by owner",
        })
        check("owner session-meta edit → 200", st == 200, f"got {st}")
        check("owner session-meta ok", data.get("ok") is True)

        # --- 14) v21.37 — Foreign non-admin user cannot edit owned lap ---
        print("\n== Foreign user denied on someone else's lap (v21.37) ==")
        db.create_user(email="other@x", password="pw_other", is_admin=False)
        other_jar = http.cookiejar.CookieJar()
        other_opener = login(base, other_jar, "other@x", "pw_other")

        st, data = get_json(other_opener,
                            f"{base}/api/laps/{owned_lap}/channel-roles")
        check("foreign GET → 403", st == 403, f"got {st}")

        st, data = post_form(other_opener,
                             f"{base}/api/laps/{owned_lap}/channel-roles",
                             {"role_lean": "ch_phi_lean"})
        check("foreign POST → 403", st == 403, f"got {st}")

        st, data = post_form(other_opener, f"{base}/sessions/{sid}/edit", {
            "driver": "Hacker", "bike": "", "track": "",
            "session_date": "", "notes": "",
        })
        check("foreign session-meta edit → 403", st == 403, f"got {st}")

        # --- 15) Orphan lap (user_id NULL) is still admin-only ---
        print("\n== Orphan lap stays admin-only ==")
        st, data = get_json(user_opener,
                            f"{base}/api/laps/{lap_id}/channel-roles")
        # lap_id from step 1 was created without owner → still 403 for
        # non-admin non-owner (since there's no owner to match)
        check("orphan GET as non-admin → 403", st == 403, f"got {st}")
        st, data = get_json(admin_opener,
                            f"{base}/api/laps/{lap_id}/channel-roles")
        check("orphan GET as admin → 200", st == 200, f"got {st}")

        # --- Shutdown ---
        server.shutdown()
        server.server_close()
        print(f"\n{PASS} pass, {FAIL} fail")
        return 0 if FAIL == 0 else 1
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
