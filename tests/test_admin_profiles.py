#!/usr/bin/env python3
"""tests/test_admin_profiles.py — v23.4

Admin-Tab "Profile": Liste aller angelegten Profile mit Link auf die
öffentliche Profilseite (`/profile/<user_id>`).

Zwei Schichten:
  (1) DB-Layer: `list_all_profiles()` JOINt profiles + users + aggregiert
      Bikes pro User; `count_users()` für die "X von Y"-Info-Zeile.
  (2) Route: `/admin?tab=profiles` rendert die Rows mit Email-Links und
      Öffnen-Buttons. Admin-only — anon und non-admin sehen 404/Login.
"""
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import uuid
from http.client import HTTPConnection
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import db as dbmod
import webserver


# ---------------------------------------------------------------------------
# (1) DB-Layer
# ---------------------------------------------------------------------------

class TestListAllProfilesDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rd-adm-prof-")
        self.db = dbmod.DB(Path(self.tmp) / "x.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_when_no_profiles(self):
        # Auch User ohne Profil sollen NICHT auftauchen — bewusst.
        self.db.create_user(email="a@x.de", password="secret123")
        self.assertEqual(self.db.list_all_profiles(), [])
        self.assertEqual(self.db.count_users(), 1)

    def test_lists_profile_rows_with_email_join(self):
        uid1 = self.db.create_user(email="alice@x.de", password="secret123")
        uid2 = self.db.create_user(email="bob@x.de",   password="secret123",
                                   is_admin=True)
        # nur uid1 legt ein Profil an
        self.db.upsert_profile(uid1, driver_name="Alice A.", image_path="a.jpg")
        rows = self.db.list_all_profiles()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["user_id"], uid1)
        self.assertEqual(r["email"], "alice@x.de")
        self.assertEqual(r["driver_name"], "Alice A.")
        self.assertEqual(r["image_path"], "a.jpg")
        self.assertEqual(r["is_admin"], 0)
        self.assertEqual(r["bike_count"], 0)
        self.assertIsNone(r["current_bike_name"])

    def test_bike_count_and_current_bike(self):
        uid = self.db.create_user(email="r@x.de", password="secret123")
        self.db.upsert_profile(uid, driver_name="Rider", image_path="")
        self.db.add_bike(uid, name="Beemer Q", image_path="", is_current=False)
        self.db.add_bike(uid, name="Beemer R", image_path="", is_current=True)
        self.db.add_bike(uid, name="Beemer S", image_path="", is_current=False)
        rows = self.db.list_all_profiles()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bike_count"], 3)
        self.assertEqual(rows[0]["current_bike_name"], "Beemer R")

    def test_admin_flag_propagates(self):
        uid = self.db.create_user(email="admin@x.de", password="secret123",
                                  is_admin=True)
        self.db.upsert_profile(uid, driver_name="Boss", image_path="")
        rows = self.db.list_all_profiles()
        self.assertEqual(rows[0]["is_admin"], 1)

    def test_sort_order_newest_updated_first(self):
        # Wir können nicht ohne Sleep zwischen Updates unterscheiden, aber
        # wir können prüfen dass die ORDER BY-Klausel ein deterministisches
        # Output liefert und beide Rows enthält.
        uid1 = self.db.create_user(email="early@x.de", password="secret123")
        uid2 = self.db.create_user(email="late@x.de",  password="secret123")
        self.db.upsert_profile(uid1, driver_name="Early")
        # kleiner Sleep nicht nötig — sqlite ISO-Strings haben Sekunden-Auflösung,
        # aber unsere upsert_profile setzt updated_at jedes Mal neu
        import time
        time.sleep(1.1)
        self.db.upsert_profile(uid2, driver_name="Late")
        rows = self.db.list_all_profiles()
        self.assertEqual(len(rows), 2)
        # Late (uid2) sollte zuerst kommen (neueres updated_at)
        self.assertEqual(rows[0]["user_id"], uid2)
        self.assertEqual(rows[1]["user_id"], uid1)

    def test_count_users(self):
        self.assertEqual(self.db.count_users(), 0)
        self.db.create_user(email="a@x.de", password="secret123")
        self.db.create_user(email="b@x.de", password="secret123")
        self.assertEqual(self.db.count_users(), 2)


# ---------------------------------------------------------------------------
# (2) Route-Layer — echter Test-Server (analog test_profile.py)
# ---------------------------------------------------------------------------

class _Server:
    """Bootet einen webserver.WebHandler gegen ein frisches Tempdir. Wir
    nutzen den gleichen Aufsatz wie tests/test_profile.py / test_admin_
    ip_lookup.py, um Cookies und Roundtrips realistisch zu testen."""

    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="rd-test-adm-prof-")
        webserver.AppState.init(Path(self.tmpdir))
        from http.server import ThreadingHTTPServer
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), webserver.WebHandler)
        self.port = self.srv.server_address[1]
        self.thr = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thr.start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thr.join(timeout=2)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def request(self, method, path, *, body=None, headers=None):
        c = HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        out = {"status": r.status, "headers": dict(r.getheaders()),
               "body": data.decode("utf-8", errors="replace")}
        c.close()
        return out

    def login(self, email, password):
        body = f"email={email}&password={password}".encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "Content-Length": str(len(body))}
        r = self.request("POST", "/login", body=body, headers=headers)
        sc = r["headers"].get("Set-Cookie", "")
        m = re.match(r"([^=]+)=([^;]+);", sc)
        return f"{m.group(1)}={m.group(2)}" if m else ""


class TestAdminProfilesRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        db = webserver.AppState.db
        # Setup: admin + user mit Profil + user ohne Profil
        cls.admin_id = db.create_user(email="admin@x.de",
                                      password="secret123", is_admin=True)
        cls.alice_id = db.create_user(email="alice@x.de",
                                      password="secret123")
        cls.bob_id   = db.create_user(email="bob@x.de",
                                      password="secret123")  # kein profil
        db.upsert_profile(cls.alice_id, driver_name="Alice A.",
                          image_path="alice.jpg")
        db.add_bike(cls.alice_id, name="Beemer R", image_path="",
                    is_current=True)
        db.upsert_profile(cls.admin_id, driver_name="The Admin",
                          image_path="")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_anon_redirected_to_login(self):
        r = self.srv.request("GET", "/admin?tab=profiles")
        # Login-Redirect (302/303) — der Admin-Handler macht das pauschal
        # vor der is_admin-Prüfung.
        self.assertIn(r["status"], (302, 303))
        self.assertIn("/login", r["headers"].get("Location", ""))

    def test_non_admin_gets_404(self):
        cookie = self.srv.login("alice@x.de", "secret123")
        r = self.srv.request("GET", "/admin?tab=profiles",
                             headers={"Cookie": cookie})
        self.assertEqual(r["status"], 404)

    def test_admin_sees_profiles_tab(self):
        cookie = self.srv.login("admin@x.de", "secret123")
        r = self.srv.request("GET", "/admin?tab=profiles",
                             headers={"Cookie": cookie})
        self.assertEqual(r["status"], 200)
        body = r["body"]
        # Tab-Eintrag selbst muss da sein
        self.assertIn("Profile", body)
        # Beide Profile sollten gerendert sein (2 angelegt, 3 user total)
        self.assertIn("alice@x.de", body)
        self.assertIn("admin@x.de", body)
        # User ohne Profil darf NICHT auftauchen
        self.assertNotIn("bob@x.de", body)
        # Count-Text zeigt 2 von 3
        self.assertRegex(body, r"2\s+Profile.*3\s+Usern")

    def test_admin_profile_rows_link_to_public_profile(self):
        cookie = self.srv.login("admin@x.de", "secret123")
        r = self.srv.request("GET", "/admin?tab=profiles",
                             headers={"Cookie": cookie})
        body = r["body"]
        # Direktlinks auf die öffentliche Profilseite müssen drin sein —
        # genau das war Stefans Anforderung.
        self.assertIn(f'href="/profile/{self.alice_id}"', body)
        self.assertIn(f'href="/profile/{self.admin_id}"', body)

    def test_admin_profile_rows_show_bike_info(self):
        cookie = self.srv.login("admin@x.de", "secret123")
        r = self.srv.request("GET", "/admin?tab=profiles",
                             headers={"Cookie": cookie})
        body = r["body"]
        # Alice hat 1 Motorrad ("Beemer R")
        self.assertIn("Beemer R", body)
        # Singular vs Plural korrekt
        self.assertRegex(body, r"1\s+Motorrad")

    def test_default_tab_unchanged(self):
        # Regression: das Hinzufügen des neuen Tab-Slugs darf den Default
        # (activity) nicht beeinflussen.
        cookie = self.srv.login("admin@x.de", "secret123")
        r = self.srv.request("GET", "/admin",
                             headers={"Cookie": cookie})
        self.assertEqual(r["status"], 200)
        # Im count_text muss "View-Aufruf" stehen (das ist der Activity-Default)
        self.assertIn("View-Aufruf", r["body"])


class TestAdminProfilesEmptyState(unittest.TestCase):
    """Eigener Server (frisches AppState-Singleton), weil das Empty-State-
    Szenario auf einer DB ohne Profile aufsetzt. Wir mischen das nicht mit
    der populierten DB der Hauptklasse — `AppState.init()` ersetzt das
    Singleton, was bei einem zweiten Server-Boot im laufenden Test den
    Hauptklasse-Server inkonsistent gemacht hätte."""

    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        db = webserver.AppState.db
        db.create_user(email="solo@x.de", password="secret123", is_admin=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_empty_state_rendered(self):
        cookie = self.srv.login("solo@x.de", "secret123")
        r = self.srv.request("GET", "/admin?tab=profiles",
                             headers={"Cookie": cookie})
        self.assertEqual(r["status"], 200)
        self.assertIn("KEINE PROFILE ANGELEGT", r["body"])
        # Count-Text: 0 Profile von 1 User
        self.assertRegex(r["body"], r"0\s+Profile.*1\s+User")


if __name__ == "__main__":
    unittest.main(verbosity=2)
