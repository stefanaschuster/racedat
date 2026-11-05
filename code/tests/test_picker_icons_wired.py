#!/usr/bin/env python3
"""tests/test_picker_icons_wired.py — v22.5

Regression test for a real bug shipped in v22.3/v22.4: the picker UI
edits landed in webapp/analyze.html and webapp/upload.html, which are
dead files. The actual Datenviewer picker template lives in
report_single.py's _PAGE_TEMPLATE; the Compare picker template lives
in report.py's _TEMPLATE. The bug surfaced as "no icons visible" on
both pages.

This test loads the rendered HTML of /analyze (empty mode) and
/compare (empty mode) and asserts that all four pickers have the
icon CSS + JS wiring present:
  - The CSS class .lp-ch-icon-wrap (Coach/Datenviewer/Compare style)
    OR .ch-icon-wrap (sessions list style)
  - The JS function loadRolesRegistry()
  - A chDots() function
  - A reference to role.icon (means the SVG path is wired up)

If any of these go missing on either page again, the test fails
immediately — a green smoke test is the contract that the picker
shows icons.
"""
import http.cookiejar
import os
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

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
    # Wait for server to be ready
    for _ in range(20):
        try:
            urllib.request.urlopen(f"{base}/login", timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    return base, webserver.AppState.db, server


def login(base, jar, email, pw):
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar)
    )
    data = urllib.parse.urlencode({"email": email, "password": pw}).encode()
    opener.open(f"{base}/login", data=data)
    return opener


def assert_picker_wired(html, page_label):
    """Assert that a picker page has all 4 wiring points present."""
    # CSS: either Coach/Datenviewer/Compare wrapper (lp-ch-icon-wrap) or
    # sessions-list wrapper (ch-icon-wrap). At least one must be present.
    has_wrapper_css = (
        "lp-ch-icon-wrap" in html or "ch-icon-wrap" in html
    )
    check(f"[{page_label}] picker CSS wrapper class present", has_wrapper_css,
          "no .lp-ch-icon-wrap or .ch-icon-wrap CSS — icons can't be styled")

    check(f"[{page_label}] loadRolesRegistry() defined",
          "loadRolesRegistry" in html,
          "no registry-loader JS — icons will never be fetched")

    check(f"[{page_label}] chDots() function defined",
          "function chDots" in html,
          "no chDots() — icon row will never be rendered")

    check(f"[{page_label}] role.icon referenced in JS",
          "role.icon" in html,
          "chDots doesn't reference role.icon — SVG never inserted")


def main():
    tmpdir = tempfile.mkdtemp(prefix="picker_icons_")
    try:
        base, db, server = setup_server(tmpdir)
        db.create_user(email="admin@x", password="pw_admin", is_admin=True)
        jar = http.cookiejar.CookieJar()
        opener = login(base, jar, "admin@x", "pw_admin")

        # Datenviewer empty mode — picker is in report_single._PAGE_TEMPLATE
        print("\n== Datenviewer picker (/analyze) ==")
        r = opener.open(f"{base}/analyze")
        check("/analyze → 200", r.status == 200)
        analyze_html = r.read().decode("utf-8")
        assert_picker_wired(analyze_html, "/analyze")

        # Compare empty mode — picker is in report._TEMPLATE
        print("\n== Compare picker (/compare) ==")
        r = opener.open(f"{base}/compare")
        check("/compare → 200", r.status == 200)
        compare_html = r.read().decode("utf-8")
        assert_picker_wired(compare_html, "/compare")

        # Coach picker — JS is in coach.py
        print("\n== Coach picker (/coach) ==")
        r = opener.open(f"{base}/coach")
        check("/coach → 200", r.status == 200)
        coach_html = r.read().decode("utf-8")
        assert_picker_wired(coach_html, "/coach")

        # Sessions list — server-rendered Python, different mechanism
        # (icons are rendered inline by _channel_dots, no JS). We can't
        # easily assert "icons present" without inserting laps, but we
        # can assert the CSS class is present in the rendered page.
        print("\n== Sessions list (/sessions) ==")
        r = opener.open(f"{base}/sessions")
        check("/sessions → 200", r.status == 200)
        sessions_html = r.read().decode("utf-8")
        check("[/sessions] picker CSS wrapper class present",
              "ch-icon-wrap" in sessions_html,
              "no .ch-icon-wrap CSS — icons can't be styled")

        server.shutdown()
        server.server_close()
        print(f"\n{PASS} pass, {FAIL} fail")
        return 0 if FAIL == 0 else 1
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
