"""v21.38 — Verify GET /api/laps includes channel-summary counts on
each row. The AI-Coach lap-picker uses these to render its badge
without a second round-trip.

Spins up the webserver, inserts three laps in distinct states
(no extras / partial / full), logs in as an admin, hits the endpoint
and asserts the per-row counts match what the badge needs.
"""

import http.cookiejar
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
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
    for _ in range(40):
        try:
            urllib.request.urlopen(base + "/favicon.ico", timeout=0.2).close()
            break
        except Exception:
            time.sleep(0.05)
    return base, webserver.AppState.db, server


def login(base, jar, email, password):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = urllib.parse.urlencode({"email": email, "password": password}
                                  ).encode("utf-8")
    req = urllib.request.Request(
        base + "/login", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        resp = opener.open(req, timeout=2); resp.close()
    except urllib.error.HTTPError as e:
        e.close()
    return opener


def get_json(opener, url):
    try:
        resp = opener.open(url, timeout=2)
        status = resp.getcode(); body = resp.read().decode("utf-8"); resp.close()
    except urllib.error.HTTPError as e:
        status = e.code; body = e.read().decode("utf-8"); e.close()
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, {"raw": body}


def insert_lap(db, *, with_channels=True, roles=None, track="Foo"):
    n = 200
    t = np.linspace(0, 30, n)
    extras = {}
    if with_channels:
        extras = {
            "ch_p_brake_fr": {"name": "p_brake_fr", "unit": "bar",
                              "data": np.linspace(0, 10, n)},
            "ch_phi_lean":   {"name": "phi_lean", "unit": "deg",
                              "data": np.linspace(-30, 30, n)},
        }
    lap_data = {
        "time": t, "lat": np.linspace(45.0, 45.001, n),
        "lon": np.linspace(11.0, 11.001, n),
        "speed": np.full(n, 30.0),
        "distance": np.linspace(0, 1000, n),
        "duration": 30.0, "total_distance": 1000.0,
        "extra_channels": extras,
    }
    if roles is not None:
        lap_data["channel_roles"] = roles
    sid = db.create_session(
        original_filename=f"{track}.xrk", file_path="/tmp/x",
        user_id=None, driver="t", bike="t", track=track,
        session_date="2026-05-15", notes="", format="xrk",
    )
    return db.add_lap(sid, 1, 30.0, lap_data)


def main():
    tmpdir = tempfile.mkdtemp(prefix="lap38_")
    try:
        base, db, server = setup_server(tmpdir)
        db.create_user(email="admin@x", password="pw_admin", is_admin=True)

        # Three laps in distinct badge states
        lap_no_extras = insert_lap(db, with_channels=False, track="NoExtras")
        lap_untouched = insert_lap(db, with_channels=True, roles=None,
                                   track="Untouched")
        lap_partial = insert_lap(
            db, with_channels=True,
            roles={"lean": "ch_phi_lean"}, track="Partial")
        # "Full" means all 4 registry roles assigned (pattern match irrelevant)
        from parsers.channel_roles import ROLES
        all_assigned = {r["id"]: "ch_phi_lean" for r in ROLES}
        lap_full = insert_lap(db, with_channels=True, roles=all_assigned,
                              track="Full")

        # Login + hit /api/laps
        jar = http.cookiejar.CookieJar()
        opener = login(base, jar, "admin@x", "pw_admin")

        st, rows = get_json(opener, f"{base}/api/laps")
        check("/api/laps → 200", st == 200, f"got {st}")
        check("payload is a list", isinstance(rows, list))
        check("4 rows returned", len(rows) == 4, f"got {len(rows)}")

        # Index by lap_id for easy lookup
        by_id = {int(r["lap_id"]): r for r in rows}

        # Every row carries the three new fields
        for r in rows:
            check(f"row lap_id={r['lap_id']} has extras_count",
                  "extras_count" in r)
            check(f"row lap_id={r['lap_id']} has roles_count",
                  "roles_count" in r)
            check(f"row lap_id={r['lap_id']} has total_roles",
                  "total_roles" in r)
            # v22.3 — every row also carries the per-role assignment list
            check(f"row lap_id={r['lap_id']} has assigned_role_ids",
                  "assigned_role_ids" in r and
                  isinstance(r["assigned_role_ids"], list))

        total = len(ROLES)
        # Per-state assertions
        r_no = by_id[lap_no_extras]
        check("no-extras: extras_count=0", r_no["extras_count"] == 0)
        check("no-extras: roles_count=0", r_no["roles_count"] == 0)
        check("no-extras: total_roles set", r_no["total_roles"] == total)
        check("no-extras: assigned_role_ids=[]",
              r_no["assigned_role_ids"] == [])

        r_un = by_id[lap_untouched]
        check("untouched: extras_count=2", r_un["extras_count"] == 2)
        check("untouched: roles_count=0",  r_un["roles_count"] == 0)
        check("untouched: assigned_role_ids=[]",
              r_un["assigned_role_ids"] == [])

        r_pa = by_id[lap_partial]
        check("partial: extras_count=2", r_pa["extras_count"] == 2)
        check("partial: roles_count=1",  r_pa["roles_count"] == 1)
        check("partial: assigned_role_ids=['lean']",
              r_pa["assigned_role_ids"] == ["lean"])

        r_fu = by_id[lap_full]
        check("full: extras_count=2", r_fu["extras_count"] == 2)
        check("full: roles_count=total", r_fu["roles_count"] == total)
        check("full: assigned_role_ids = sorted(all role ids)",
              r_fu["assigned_role_ids"] == sorted(r["id"] for r in ROLES))

        # Mirror of the JS badge classifier — make sure each lap maps to
        # the expected visual state
        def classify(r):
            ex, ro, tot = r["extras_count"], r["roles_count"], r["total_roles"]
            if ex == 0: return "none"
            if tot > 0 and ro >= tot: return "full"
            if ro == 0: return "untouched"
            return "partial"
        check("no-extras → none",      classify(r_no) == "none")
        check("untouched → untouched", classify(r_un) == "untouched")
        check("partial → partial",     classify(r_pa) == "partial")
        check("full → full",           classify(r_fu) == "full")

        # Empty result set still works (no laps match filter)
        st, rows2 = get_json(opener, f"{base}/api/laps?driver=NoSuchDriver")
        check("filtered empty → 200", st == 200)
        check("filtered empty → []", rows2 == [])

        # --- v22.3 — /api/channel-roles-registry endpoint -----------------
        # Static list of {id, label, description}, one entry per role in
        # the registry (CHANNEL_ROLES). Used by the picker UIs to render
        # one status-dot per role next to each lap.
        print("\n== /api/channel-roles-registry ==")
        st, reg = get_json(opener, f"{base}/api/channel-roles-registry")
        check("/api/channel-roles-registry → 200", st == 200, f"got {st}")
        check("registry is a list", isinstance(reg, list))
        check(f"registry has {total} entries",
              len(reg) == total, f"got {len(reg)}")
        for entry in reg:
            check(f"entry {entry.get('id')!r} has id+label+description+icon",
                  set(entry.keys()) >= {"id", "label", "description", "icon"})
        # IDs and order match the underlying ROLES registry exactly
        check("registry preserves order",
              [e["id"] for e in reg] == [r["id"] for r in ROLES])
        # Labels are non-empty (UI uses them in tooltips)
        check("all labels non-empty",
              all(e["label"] for e in reg))
        # v22.4 — icon field is a non-empty SVG string
        check("all icons are non-empty SVGs",
              all(e["icon"] and "<svg" in e["icon"] for e in reg))

        server.shutdown(); server.server_close()
        print(f"\n{PASS} pass, {FAIL} fail")
        return 0 if FAIL == 0 else 1
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
