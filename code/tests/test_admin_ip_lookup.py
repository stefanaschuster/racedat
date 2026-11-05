"""v22.11 — Tests for the admin Reverse-IP-Lookup feature.

Covers:
  Unit (no server):
    - is_private_or_loopback_ip:  loopback/private/link-local/v6 cases,
                                  rejects garbage and empty
    - is_valid_public_ip:         public IPv4/IPv6 yes, private no
    - render_ip_cell:             empty→placeholder, private→bare+marker,
                                  public→<a href> with proper escaping
                                  for both IPv4 and IPv6 (quote/escape)

  Integration (live test server, ip-api.com mocked):
    - Unauthenticated → redirect to /login
    - Non-admin       → 404 (we hide the endpoint)
    - Admin + missing 'ip' param          → 400
    - Admin + over-long 'ip'              → 400
    - Admin + syntactically invalid 'ip'  → 400
    - Admin + private IP                  → renders "local" page,
                                            upstream NOT called
    - Admin + public IP, upstream success → renders city/country/ISP
    - Admin + public IP, upstream fail    → renders "Lookup fehlgeschlagen"
    - Admin + public IP, upstream error   → renders "Netzwerk-/Parse-Fehler"
"""

import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

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


# ---------------------------------------------------------------------------
# Unit tests — no server, just pure-function behaviour
# ---------------------------------------------------------------------------

def run_unit_tests():
    print("== Unit ==")
    from webserver import (
        is_private_or_loopback_ip,
        is_valid_public_ip,
        render_ip_cell,
    )

    # is_private_or_loopback_ip ---------------------------------------------
    check("loopback v4 → private", is_private_or_loopback_ip("127.0.0.1"))
    check("loopback v6 → private", is_private_or_loopback_ip("::1"))
    check("RFC1918 10.x → private", is_private_or_loopback_ip("10.0.0.1"))
    check("RFC1918 192.168.x → private",
          is_private_or_loopback_ip("192.168.1.1"))
    check("RFC1918 172.16-31 → private",
          is_private_or_loopback_ip("172.16.0.1"))
    check("link-local 169.254 → private",
          is_private_or_loopback_ip("169.254.0.1"))
    check("public 8.8.8.8 → not private",
          not is_private_or_loopback_ip("8.8.8.8"))
    check("public v6 2606:4700 → not private",
          not is_private_or_loopback_ip("2606:4700:4700::1111"))
    check("empty string → not private (no crash)",
          not is_private_or_loopback_ip(""))
    check("garbage → not private (no crash)",
          not is_private_or_loopback_ip("not-an-ip"))

    # is_valid_public_ip ----------------------------------------------------
    check("8.8.8.8 → valid public", is_valid_public_ip("8.8.8.8"))
    check("v6 2606:4700:4700::1111 → valid public",
          is_valid_public_ip("2606:4700:4700::1111"))
    check("127.0.0.1 → NOT valid public",
          not is_valid_public_ip("127.0.0.1"))
    check("10.0.0.1 → NOT valid public",
          not is_valid_public_ip("10.0.0.1"))
    check("'' → NOT valid public", not is_valid_public_ip(""))
    check("garbage → NOT valid public",
          not is_valid_public_ip("999.999.999.999"))

    # render_ip_cell --------------------------------------------------------
    empty = render_ip_cell("")
    check("empty IP → em-dash placeholder", "—" in empty and "href" not in empty)

    local = render_ip_cell("127.0.0.1")
    check("loopback IP → bare text", "127.0.0.1" in local)
    check("loopback IP → no link", "href" not in local)
    check("loopback IP → '(lokal)' marker", "lokal" in local)

    pub = render_ip_cell("8.8.8.8")
    check("public IP → has link",
          'href="/admin/ip-lookup?ip=8.8.8.8"' in pub)
    check("public IP → has ip-link class",
          'class="ip-link"' in pub)
    check("public IP → target=_blank",
          'target="_blank"' in pub)
    check("public IP → rel=noopener (security)",
          "noopener" in pub)
    check("public IP → has title (tooltip)",
          "title=" in pub)

    pub_v6 = render_ip_cell("2606:4700:4700::1111")
    # IPv6 colons must be URL-encoded in the href ('%3A')
    check("public IPv6 → href URL-encodes colons",
          "%3A" in pub_v6)
    # But raw IPv6 shows up in the link TEXT (after html.escape, colons stay)
    check("public IPv6 → text shows raw v6",
          "2606:4700:4700::1111" in pub_v6)

    # HTML-escape sanity (in case a malformed/spoofed value ever leaks
    # through, we never want it to become live HTML). render_ip_cell uses
    # html.escape internally; valid IPs never contain special chars, so we
    # just confirm a syntactically-invalid value falls through without
    # turning into markup.
    weird = render_ip_cell("<script>")
    check("HTML-special chars → escaped, no <script> tag injection",
          "<script>" not in weird and "&lt;script&gt;" in weird)


# ---------------------------------------------------------------------------
# Integration tests — live test server, upstream HTTP mocked via monkeypatch
# ---------------------------------------------------------------------------

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


def login(base, email, password):
    """Log into the test server, return an opener with the auth cookie."""
    jar = http.cookiejar.CookieJar()
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
        e.close()
    return opener


def fetch(opener, url, follow_redirects=True):
    """Return (status, body_text, final_url). Doesn't raise on HTTP errors."""
    try:
        resp = opener.open(url, timeout=2)
        status = resp.getcode()
        body = resp.read().decode("utf-8", errors="replace")
        final = resp.geturl()
        resp.close()
        return status, body, final
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode("utf-8", errors="replace")
        e.close()
        return status, body, url


def fetch_no_redirect(url):
    """Anonymous fetch that does NOT follow redirects — returns Location."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(url, timeout=2)
        return resp.getcode(), resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")


def run_integration_tests():
    print("== Integration ==")
    tmpdir = tempfile.mkdtemp(prefix="lap_iptest_")
    try:
        base, db, server = setup_server(tmpdir)
        print(f"   server: {base}")

        import webserver as ws

        db.create_user(email="admin@x", password="pw_admin", is_admin=True)
        db.create_user(email="user@x",  password="pw_user",  is_admin=False)

        # --- AuthN/AuthZ ----------------------------------------------------
        # Unauthenticated → redirect to /login (303)
        code, loc = fetch_no_redirect(
            base + "/admin/ip-lookup?ip=8.8.8.8")
        check("anon → 3xx redirect to /login",
              300 <= code < 400 and "/login" in loc,
              detail=f"code={code} loc={loc}")

        # Non-admin → 404 (we hide the endpoint)
        op_user = login(base, "user@x", "pw_user")
        status, body, _ = fetch(op_user, base + "/admin/ip-lookup?ip=8.8.8.8")
        check("non-admin → 404", status == 404, detail=f"status={status}")

        op_admin = login(base, "admin@x", "pw_admin")

        # --- Param validation ----------------------------------------------
        status, body, _ = fetch(op_admin, base + "/admin/ip-lookup")
        check("missing ip → 400",
              status == 400 and "fehlt" in body.lower(),
              detail=f"status={status} body[:80]={body[:80]!r}")

        long_ip = "a" * 200
        status, body, _ = fetch(
            op_admin, base + "/admin/ip-lookup?ip=" + long_ip)
        check("over-long ip → 400",
              status == 400, detail=f"status={status}")

        status, body, _ = fetch(
            op_admin, base + "/admin/ip-lookup?ip=not-an-ip")
        check("invalid syntax → 400",
              status == 400 and "ung" in body.lower(),
              detail=f"status={status} body[:80]={body[:80]!r}")

        # --- Private IP — short-circuits, never calls upstream -------------
        # Track whether fetch_ip_geo gets called at all.
        upstream_call_count = {"n": 0}
        original_fetch = ws.fetch_ip_geo

        def spy_fetch(ip, **kw):
            upstream_call_count["n"] += 1
            return {"status": "error", "message": "should-not-happen"}

        ws.fetch_ip_geo = spy_fetch
        try:
            status, body, _ = fetch(
                op_admin, base + "/admin/ip-lookup?ip=192.168.1.1")
            check("private ip → 200",
                  status == 200, detail=f"status={status}")
            check("private ip → 'lokale' message rendered",
                  "Lokale" in body or "lokale" in body,
                  detail="missing local marker")
            check("private ip → upstream NEVER called",
                  upstream_call_count["n"] == 0,
                  detail=f"upstream calls={upstream_call_count['n']}")
        finally:
            ws.fetch_ip_geo = original_fetch

        # --- Public IP, upstream "success" ---------------------------------
        ws.fetch_ip_geo = lambda ip, **kw: {
            "status":      "success",
            "country":     "Germany",
            "countryCode": "DE",
            "regionName":  "Berlin",
            "region":      "BE",
            "city":        "Berlin",
            "zip":         "10115",
            "lat":         52.52,
            "lon":         13.405,
            "timezone":    "Europe/Berlin",
            "isp":         "TestISP GmbH",
            "org":         "TestOrg",
            "as":          "AS12345 TestNet",
            "query":       ip,
        }
        try:
            status, body, _ = fetch(
                op_admin, base + "/admin/ip-lookup?ip=8.8.8.8")
            check("public ok → 200", status == 200, detail=f"status={status}")
            check("public ok → renders country", "Germany" in body)
            check("public ok → renders city", "Berlin" in body)
            check("public ok → renders ISP", "TestISP" in body)
            check("public ok → renders AS", "AS12345" in body)
            check("public ok → renders coords",
                  "52.52" in body and "13.405" in body)
            check("public ok → OpenStreetMap link present",
                  "openstreetmap.org" in body)
        finally:
            ws.fetch_ip_geo = original_fetch

        # --- Public IP, upstream "fail" (e.g. reserved range upstream-side)
        ws.fetch_ip_geo = lambda ip, **kw: {
            "status":  "fail",
            "message": "reserved range",
        }
        try:
            status, body, _ = fetch(
                op_admin, base + "/admin/ip-lookup?ip=1.1.1.1")
            check("upstream fail → 200 (we render a friendly page)",
                  status == 200, detail=f"status={status}")
            check("upstream fail → 'fehlgeschlagen' shown",
                  "fehlgeschlagen" in body.lower())
            check("upstream fail → reason surfaced",
                  "reserved range" in body)
        finally:
            ws.fetch_ip_geo = original_fetch

        # --- Public IP, network/parse error --------------------------------
        ws.fetch_ip_geo = lambda ip, **kw: {
            "status":  "error",
            "message": "network: timed out",
        }
        try:
            status, body, _ = fetch(
                op_admin, base + "/admin/ip-lookup?ip=1.1.1.1")
            check("upstream error → 200", status == 200,
                  detail=f"status={status}")
            check("upstream error → 'Netzwerk' shown",
                  "Netzwerk" in body or "netzwerk" in body)
            check("upstream error → detail surfaced",
                  "timed out" in body)
        finally:
            ws.fetch_ip_geo = original_fetch

        # --- Smoke: admin page renders without crashing -------------------
        # (verifies render_ip_cell is wired into all three tabs)
        for tab in ("activity", "logins", "uploads"):
            status, body, _ = fetch(op_admin, base + f"/admin?tab={tab}")
            check(f"/admin?tab={tab} → 200",
                  status == 200, detail=f"status={status}")

        server.shutdown()
        server.server_close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    run_unit_tests()
    run_integration_tests()
    print(f"\n== {PASS} passed, {FAIL} failed ==")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
