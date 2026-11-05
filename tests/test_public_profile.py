#!/usr/bin/env python3
"""tests/test_public_profile.py — v23.0

Öffentliche Read-Only-Profilansicht. Klickbar gemacht über den
Owner-Link in der Rundenliste. Drei Schichten getestet:

  (1) Route + Rendering — /profile/<id> für anon und logged-in,
      404 bei unbekanntem User, Fallback auf E-Mail-Local-Part wenn
      kein Fahrername gesetzt, full email niemals nach aussen
      gerendert (Privacy-Check).
  (2) Self-Hint Banner — sichtbar nur wenn der eingeloggte User
      sein eigenes Profil anschaut.
  (3) Owner-Link in der Rundenliste — anchor zu /profile/<user_id>,
      Verwaiste Sessions ohne Owner bleiben unverlinkt.
"""
import io
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


# Wiederverwendung der Server-Klasse aus test_profile.py wäre möglich,
# aber wir duplizieren bewusst minimal — das hält die Tests autark und
# resilient gegen Refactoring der anderen Datei.
class _Server:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="racedat-test-pubprof-")
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
               "body": data}
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


# ---------------------------------------------------------------------------
# (1) Route + Rendering
# ---------------------------------------------------------------------------

class TestPublicProfileRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        db = webserver.AppState.db
        # User 1: hat Fahrername + 2 Bikes
        cls.u1 = db.create_user(email="stefan@example.com",
                                password="secret123")
        db.upsert_profile(cls.u1, driver_name="Stefan Müller")
        db.add_bike(cls.u1, name="CBR 1000 RR")
        db.add_bike(cls.u1, name="R6")
        # User 2: kein Fahrername (testet E-Mail-Fallback)
        cls.u2 = db.create_user(email="anon@example.com",
                                password="secret123")
        # User 3: existiert, aber kein Profil, keine Bikes
        cls.u3 = db.create_user(email="empty@example.com",
                                password="secret123")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_anon_can_view_public_profile(self):
        r = self.srv.request("GET", f"/profile/{self.u1}")
        self.assertEqual(r["status"], 200)
        body = r["body"].decode("utf-8")
        self.assertIn("Stefan Müller", body)
        self.assertIn("CBR 1000 RR", body)
        self.assertIn("R6", body)

    def test_anon_does_not_get_self_hint(self):
        r = self.srv.request("GET", f"/profile/{self.u1}")
        body = r["body"].decode("utf-8")
        # CSS-Selektor steht im <style>, aber der konkrete Banner-DIV
        # NICHT (Server rendert ihn nur für self).
        self.assertNotIn('<div class="self-hint">', body)
        self.assertNotIn("EIGENES PROFIL EDITIEREN", body)

    def test_self_view_shows_self_hint(self):
        cookie = self.srv.login("stefan@example.com", "secret123")
        r = self.srv.request("GET", f"/profile/{self.u1}",
                             headers={"Cookie": cookie})
        body = r["body"].decode("utf-8")
        self.assertIn('<div class="self-hint">', body)
        self.assertIn("EIGENES PROFIL EDITIEREN", body)
        # Auch der "Eigene Runden"-Link kommt raus (statt fremden Fahrer-Filter)
        self.assertIn("EIGENE RUNDEN", body)
        self.assertIn("/sessions?mine=1", body)

    def test_other_logged_in_user_no_self_hint(self):
        # u3 schaut u1 an — kein Self-Hint
        cookie = self.srv.login("empty@example.com", "secret123")
        r = self.srv.request("GET", f"/profile/{self.u1}",
                             headers={"Cookie": cookie})
        body = r["body"].decode("utf-8")
        self.assertNotIn('<div class="self-hint">', body)
        self.assertNotIn("EIGENES PROFIL EDITIEREN", body)

    def test_unknown_user_returns_404(self):
        r = self.srv.request("GET", "/profile/9999")
        self.assertEqual(r["status"], 404)

    def test_non_integer_id_returns_404(self):
        # Regex matched gar nicht — kein Crash, sondern fall-through
        # zum Router-Standard-404
        r = self.srv.request("GET", "/profile/abc")
        self.assertEqual(r["status"], 404)
        r = self.srv.request("GET", "/profile/-1")
        self.assertEqual(r["status"], 404)

    def test_email_not_leaked_when_driver_name_set(self):
        # User mit Fahrername: die E-Mail darf NIE in der gerenderten
        # Seite vorkommen. Privacy-Garantie.
        r = self.srv.request("GET", f"/profile/{self.u1}")
        body = r["body"].decode("utf-8")
        self.assertNotIn("stefan@example.com", body)

    def test_email_localpart_fallback_when_no_driver_name(self):
        # User OHNE Fahrername: Local-Part der E-Mail wird angezeigt, aber
        # nicht die volle Adresse mit Domain.
        r = self.srv.request("GET", f"/profile/{self.u2}")
        body = r["body"].decode("utf-8")
        self.assertEqual(r["status"], 200)
        self.assertIn(">anon<", body)
        # @example.com darf NICHT im Body sein
        self.assertNotIn("@example.com", body)
        self.assertNotIn("anon@example.com", body)

    def test_empty_user_renders_with_placeholder(self):
        # u3 hat kein Profil, keine Bikes — Seite rendert trotzdem
        r = self.srv.request("GET", f"/profile/{self.u3}")
        self.assertEqual(r["status"], 200)
        body = r["body"].decode("utf-8")
        self.assertIn(">empty<", body)
        self.assertIn("KEINE MOTORRÄDER HINTERLEGT", body)

    def test_page_title_uses_display_name(self):
        r = self.srv.request("GET", f"/profile/{self.u1}")
        body = r["body"].decode("utf-8")
        self.assertIn("<title>Stefan Müller", body)

    def test_no_edit_forms_anywhere(self):
        # Das ist der Kern der Read-Only-Garantie: keine <form>-Tags
        # die irgendwas am Profil ändern könnten.
        r = self.srv.request("GET", f"/profile/{self.u1}")
        body = r["body"].decode("utf-8")
        # Es ist OK wenn der Header ein logout-Form hat — aber KEIN
        # action="/profile/save" oder "/profile/bike/..."
        self.assertNotIn('action="/profile/save"', body)
        self.assertNotIn('/profile/bike/', body)

    def test_bike_image_renders_when_present(self):
        # Bild zu einem Bike hinzufügen und prüfen dass der Tag rauskommt
        bikes = webserver.AppState.db.list_bikes(self.u1)
        # Mock-PNG (1×1)
        png = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00'
               b'\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00'
               b'\x00\rIDATx\x9cc\xf8\xcf\x00\x00\x00\x03\x00\x01\x5a\xf6'
               b'\x16\xff\x00\x00\x00\x00IEND\xaeB`\x82')
        fname = webserver.save_profile_image(png, "cbr.png")
        webserver.AppState.db.update_bike(
            bikes[0]["id"], self.u1, image_path=fname
        )
        r = self.srv.request("GET", f"/profile/{self.u1}")
        body = r["body"].decode("utf-8")
        self.assertIn(f'/profile/image/{fname}', body)

    def test_lap_count_zero_no_link(self):
        # u3: keine Runden → kein Runden-Link (statt eines Links auf
        # /sessions?driver= mit leerem Wert).
        r = self.srv.request("GET", f"/profile/{self.u3}")
        body = r["body"].decode("utf-8")
        # Die "0 hochgeladene Runde(n)"-Stats bleiben sichtbar; aber
        # KEIN .my-laps-link block im DOM (im <style> steht der Selektor,
        # das matchen wir nicht — wir suchen das tatsächliche <a> oder
        # <div class="my-laps-link"> Element).
        self.assertIn("0 hochgeladene", body)
        self.assertNotIn('class="my-laps-link"', body)

    def test_xss_in_driver_name_escaped(self):
        # User legt sich einen "Fahrernamen" mit HTML-Payload an. Read-
        # only-Seite muss escape; ein <script> darf nie als unescaped
        # Tag rauskommen.
        evil_uid = webserver.AppState.db.create_user(
            email="evil@example.com", password="secret123")
        webserver.AppState.db.upsert_profile(
            evil_uid, driver_name="<script>alert(1)</script>BadGuy")
        webserver.AppState.db.add_bike(
            evil_uid, name='<img src=x onerror=alert(2)>')
        r = self.srv.request("GET", f"/profile/{evil_uid}")
        body = r["body"].decode("utf-8")
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertNotIn("<img src=x onerror=alert(2)>", body)
        # Die escapten Versionen müssen da sein (Beweis dass es nicht
        # aus Versehen aus dem Output gefallen ist)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("&lt;img", body)


# ---------------------------------------------------------------------------
# (2) Klickbarkeit in der Rundenliste
# ---------------------------------------------------------------------------

class TestOwnerLinkInSessionsList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        db = webserver.AppState.db
        cls.u1 = db.create_user(email="stefan@example.com",
                                password="secret123")
        # Fake-Session anlegen damit die Sessions-Liste nicht leer ist
        import numpy as np
        sid = db.create_session(
            original_filename="t.ses", file_path="/tmp/x",
            user_id=cls.u1,
            driver="Stefan", bike="CBR", track="Aragon",
            session_date="2026-05-22", notes="", format="ses",
        )
        ld = {
            "time": np.array([0.0, 1.0]),
            "speed": np.array([100.0, 110.0]),
            "distance": np.array([0.0, 30.0]),
            "lat": np.array([0.0, 0.0]),
            "lon": np.array([0.0, 0.0]),
            "lap_index": 1, "duration": 90.0,
        }
        db.add_lap(sid, 1, 90.0, ld)
        # Verwaiste Session ohne owner (user_id=None)
        sid2 = db.create_session(
            original_filename="orphan.ses", file_path="/tmp/o",
            user_id=None,
            driver="Anon", bike="?", track="Mugello",
            session_date="2026-05-22", notes="", format="ses",
        )
        db.add_lap(sid2, 1, 92.0, ld)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_owner_email_is_clickable_anchor(self):
        r = self.srv.request("GET", "/sessions")
        body = r["body"].decode("utf-8")
        # <a href="/profile/<id>" class="owner-link" ...>
        self.assertRegex(
            body,
            r'<a href="/profile/' + str(self.u1) + r'"\s+class="owner-link"',
        )
        # Anchor enthält tatsächlich die E-Mail als Linktext
        self.assertRegex(
            body,
            r'class="owner-link"[^>]*>stefan@example\.com</a>',
        )

    def test_orphan_session_no_link(self):
        # Die Owner-Spalte für die zweite Session zeigt "(verwaist)"
        # ohne Link.
        r = self.srv.request("GET", "/sessions")
        body = r["body"].decode("utf-8")
        self.assertIn("(verwaist)", body)
        # Es darf kein <a href="/profile/None"> entstanden sein
        self.assertNotIn('/profile/None', body)
        self.assertNotIn('/profile/null', body)
        self.assertNotIn('/profile/"', body)

    def test_owner_link_has_title_tooltip(self):
        # title="Profil von <email> ansehen" für Hover-UX
        r = self.srv.request("GET", "/sessions")
        body = r["body"].decode("utf-8")
        self.assertIn('title="Profil von stefan@example.com ansehen"',
                      body)

    def test_anon_can_use_owner_link(self):
        # Wir machen den Roundtrip: Click auf den Owner-Link rendert das
        # Profile-Page, auch ohne Login.
        r = self.srv.request("GET", "/sessions")
        body = r["body"].decode("utf-8")
        # Extrahiere die href
        m = re.search(
            r'<a href="(/profile/\d+)"\s+class="owner-link"', body
        )
        self.assertIsNotNone(m)
        target = m.group(1)
        # Folge dem Link, ohne Auth-Cookie
        r2 = self.srv.request("GET", target)
        self.assertEqual(r2["status"], 200)


# ---------------------------------------------------------------------------
# (3) Architektur-Sanity — /profile (ohne id) und /profile/image/ konflikten
# nicht mit /profile/<id>
# ---------------------------------------------------------------------------

class TestRouteDisambiguation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        webserver.AppState.db.create_user(email="x@example.com",
                                          password="secret123")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_profile_without_id_still_requires_login(self):
        # Anon → 303 zu /login (unverändert von v22.12)
        r = self.srv.request("GET", "/profile")
        self.assertEqual(r["status"], 303)
        self.assertIn("/login", r["headers"]["Location"])

    def test_profile_image_path_does_not_match_user_route(self):
        # /profile/image/<file> wird VOR /profile/<id> geprüft im Router.
        # Ein File-Name mit Punkten matcht den Image-Regex; reine Ziffern
        # könnten in beide. Aber /profile/image/ ist ein anderer Prefix —
        # 12345 alleine könnte missverstanden werden? Test: ein File-
        # Name ohne valides UUID-Format gibt 404 vom Image-Handler, NICHT
        # ein "User #1" auf dem User-Route.
        r = self.srv.request("GET", "/profile/image/garbage.jpg")
        self.assertEqual(r["status"], 404)
        # User-Route mit nur Ziffern (1) → User existiert → 200
        r2 = self.srv.request("GET", "/profile/1")
        self.assertEqual(r2["status"], 200)


# ---------------------------------------------------------------------------
# (4) v23.1 — Bugfix: "Eigene Runden"-Link ausgeblendet bei Fremd-Profil
# ---------------------------------------------------------------------------

class TestLapsLinkBugfix(unittest.TestCase):
    """v23.1 — Stefan-Spec: 'Wenn die Profilseite eines anderen Users
    angezeigt wird, dann blenden wir den Link für die Selektion der
    eigenen Runden ganz aus.'

    Konkret: das ganze .my-laps-link Element darf bei fremden Profilen
    nicht auftauchen (weder als Link noch als Info-Block). Nur beim
    self-View und nur in der Profilseite des eingeloggten Users bleibt
    der Link drin."""

    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.srv = _Server()
        db = webserver.AppState.db
        cls.alice = db.create_user(email="alice@example.com",
                                   password="secret123")
        cls.bob = db.create_user(email="bob@example.com",
                                 password="secret123")
        db.upsert_profile(cls.alice, driver_name="Alice")
        db.upsert_profile(cls.bob, driver_name="Bob")
        # Alice hat Runden — damit lap_count > 0 ist; falls der Bug
        # zurückkommt würde das Code-Pfad-Branch greifen.
        def _ld(d):
            return {"time": np.array([0.0, d]),
                    "speed": np.array([100.0, 100.0]),
                    "distance": np.array([0.0, 30.0]),
                    "lat": np.array([0.0]), "lon": np.array([0.0]),
                    "lap_index": 1, "duration": d}
        sid = db.create_session(original_filename="x", file_path="/tmp/x",
            user_id=cls.alice, driver="Alice", bike="", track="Aragon",
            session_date="2026-05-22", notes="", format="ses")
        db.add_lap(sid, 1, 91.5, _ld(91.5))

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_anon_viewing_alice_no_laps_link(self):
        r = self.srv.request("GET", f"/profile/{self.alice}")
        body = r["body"].decode("utf-8")
        # Kein Link-Element zur Sessions-Liste
        self.assertNotIn('class="my-laps-link"', body)
        # Insbesondere: NICHT die "RUNDEN VON X"-Variante die früher
        # bei fremd + driver_name gesetzt gerendert wurde
        self.assertNotIn("RUNDEN VON", body)
        # Auch keine "N HOCHGELADENE RUNDEN"-Info-Box
        self.assertNotIn("HOCHGELADENE RUNDEN", body)
        # EIGENE RUNDEN darf gar nicht stehen — das ist self-only
        self.assertNotIn("EIGENE RUNDEN", body)

    def test_bob_viewing_alice_no_laps_link(self):
        cookie = self.srv.login("bob@example.com", "secret123")
        r = self.srv.request("GET", f"/profile/{self.alice}",
                             headers={"Cookie": cookie})
        body = r["body"].decode("utf-8")
        self.assertNotIn('class="my-laps-link"', body)
        self.assertNotIn("RUNDEN VON", body)
        self.assertNotIn("EIGENE RUNDEN", body)

    def test_alice_self_view_still_has_laps_link(self):
        # Self-View darf den Link nicht verlieren.
        cookie = self.srv.login("alice@example.com", "secret123")
        r = self.srv.request("GET", f"/profile/{self.alice}",
                             headers={"Cookie": cookie})
        body = r["body"].decode("utf-8")
        self.assertIn('class="my-laps-link"', body)
        self.assertIn("EIGENE RUNDEN", body)
        self.assertIn("/sessions?mine=1", body)

    def test_bob_viewing_bob_self_has_laps_link(self):
        # Bob ohne Runden sieht trotzdem den Link auf der eigenen
        # public-Seite — Konsistenz mit der Edit-Profilseite.
        cookie = self.srv.login("bob@example.com", "secret123")
        r = self.srv.request("GET", f"/profile/{self.bob}",
                             headers={"Cookie": cookie})
        body = r["body"].decode("utf-8")
        self.assertIn('class="my-laps-link"', body)
        self.assertIn("EIGENE RUNDEN", body)


# ---------------------------------------------------------------------------
# (5) v23.1 — Feature: Bestzeiten-Tabelle pro Strecke
# ---------------------------------------------------------------------------

class TestBestLapsOnPublicProfile(unittest.TestCase):
    """Bestzeiten-Sektion wird auf der öffentlichen Profilansicht
    gerendert, ist sichtbar für anon und logged-in, mit Click-Through
    auf den Datenviewer."""

    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.srv = _Server()
        db = webserver.AppState.db
        cls.uid = db.create_user(email="stefan@example.com",
                                 password="secret123")
        db.upsert_profile(cls.uid, driver_name="Stefan")

        import time as _t
        def _ld(d):
            return {"time": np.array([0.0, d]),
                    "speed": np.array([100.0, 100.0]),
                    "distance": np.array([0.0, 30.0]),
                    "lat": np.array([0.0]), "lon": np.array([0.0]),
                    "lap_index": 1, "duration": d}
        # Aragon zweimal (91.5 schneller), Mugello einmal (88.2)
        for track, dur in [("Aragon", 92.5), ("Aragon", 91.5),
                           ("Mugello", 88.2)]:
            sid = db.create_session(original_filename="x", file_path="/tmp/x",
                user_id=cls.uid, driver="Stefan", bike="", track=track,
                session_date="2026-05-22", notes="", format="ses")
            db.add_lap(sid, 1, dur, _ld(dur))
            _t.sleep(0.01)
        # User ohne Runden — fragt die Bestzeiten-Sektion ab
        cls.empty_uid = db.create_user(email="empty@example.com",
                                       password="secret123")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_bestzeiten_section_present_for_anon(self):
        r = self.srv.request("GET", f"/profile/{self.uid}")
        body = r["body"].decode("utf-8")
        self.assertIn(">BESTZEITEN<", body)
        self.assertIn('class="best-laps"', body)

    def test_tracks_listed_fastest_first(self):
        r = self.srv.request("GET", f"/profile/{self.uid}")
        body = r["body"].decode("utf-8")
        # Mugello (88.2) sollte vor Aragon (91.5) erscheinen
        i_m = body.find(">Mugello<")
        i_a = body.find(">Aragon<")
        self.assertGreater(i_m, 0)
        self.assertGreater(i_a, i_m,
                           "Mugello sollte vor Aragon stehen (schneller)")

    def test_formatted_times_displayed(self):
        r = self.srv.request("GET", f"/profile/{self.uid}")
        body = r["body"].decode("utf-8")
        # Mugello 88.2s → 1:28.200, Aragon 91.5s → 1:31.500
        self.assertIn("1:28.200", body)
        self.assertIn("1:31.500", body)

    def test_click_through_links_to_datenviewer(self):
        r = self.srv.request("GET", f"/profile/{self.uid}")
        body = r["body"].decode("utf-8")
        # Pro Strecke ein Link auf /analyze?lap_id=X&go=1
        self.assertRegex(body, r'href="/analyze\?lap_id=\d+&go=1"')

    def test_empty_state_when_no_laps(self):
        r = self.srv.request("GET", f"/profile/{self.empty_uid}")
        body = r["body"].decode("utf-8")
        self.assertIn(">BESTZEITEN<", body)
        self.assertIn("NOCH KEINE BESTZEITEN", body)
        # Aber NICHT die .best-laps Tabelle (das wäre eine leere Tabelle)
        self.assertNotIn('class="best-laps"', body)

    def test_self_view_also_shows_bestzeiten(self):
        cookie = self.srv.login("stefan@example.com", "secret123")
        r = self.srv.request("GET", f"/profile/{self.uid}",
                             headers={"Cookie": cookie})
        body = r["body"].decode("utf-8")
        self.assertIn(">BESTZEITEN<", body)
        self.assertIn(">Mugello<", body)
        self.assertIn(">Aragon<", body)

    def test_edit_profile_also_shows_bestzeiten(self):
        # /profile (Edit-Modus) zeigt jetzt auch die Bestzeiten —
        # Konsistenz mit der öffentlichen Seite.
        cookie = self.srv.login("stefan@example.com", "secret123")
        r = self.srv.request("GET", "/profile",
                             headers={"Cookie": cookie})
        body = r["body"].decode("utf-8")
        self.assertIn(">BESTZEITEN<", body)
        self.assertIn('class="best-laps"', body)
        self.assertIn(">Mugello<", body)


if __name__ == "__main__":
    unittest.main()
