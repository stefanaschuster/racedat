#!/usr/bin/env python3
"""tests/test_records.py — v23.2

Globale Bestzeiten-Seite (`/records`) + Pokal-Icons in der Sessions-
Liste und auf der Profilseite. Drei Schichten:

  (1) Route + Rendering — /records für anon und logged-in, Empty-State,
      Header-Active-Marker, Landing-Tile.
  (2) Pokal-Icons in der Sessions-Liste — globale Top-3 pro Strecke
      werden mit gold/silver/bronze markiert.
  (3) Pokal-Icons im Profil — wenn die Bestzeit eines Users auf einer
      Strecke gleichzeitig im globalen Top-3 ist, erscheint der Pokal.
"""
import re
import shutil
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import db as dbmod
import webserver


class _Server:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="racedat-test-records-")
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


def _ld(dur):
    import numpy as np
    return {"time": np.array([0.0, dur]),
            "speed": np.array([100.0, 100.0]),
            "distance": np.array([0.0, 30.0]),
            "lat": np.array([0.0]), "lon": np.array([0.0]),
            "lap_index": 1, "duration": dur}


def _add_lap(db, user_id, track, dur, driver="", bike=""):
    import time as _t
    sid = db.create_session(
        original_filename="x", file_path="/tmp/x",
        user_id=user_id, driver=driver, bike=bike,
        track=track, session_date="2026-05-22",
        notes="", format="ses",
    )
    lid = db.add_lap(sid, 1, dur, _ld(dur))
    _t.sleep(0.005)
    return lid


# ---------------------------------------------------------------------------
# (1) /records-Seite
# ---------------------------------------------------------------------------

class TestRecordsPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        db = webserver.AppState.db
        cls.stefan = db.create_user(email="stefan@x.de", password="secret123")
        cls.renate = db.create_user(email="renate@x.de", password="secret123")
        cls.mike = db.create_user(email="mike@x.de", password="secret123")
        db.upsert_profile(cls.stefan, driver_name="Stefan")
        db.upsert_profile(cls.renate, driver_name="Renate")
        # mike absichtlich ohne driver_name → fallback to email local-part
        # Aragon: Renate (90.5) #1, Stefan (91.8) #2, Stefan (92.1) #3
        cls.lap_stefan_aragon_1 = _add_lap(db, cls.stefan, "Aragon", 92.1, "Stefan")
        cls.lap_stefan_aragon_2 = _add_lap(db, cls.stefan, "Aragon", 91.8, "Stefan")
        cls.lap_renate_aragon = _add_lap(db, cls.renate, "Aragon", 90.5, "Renate")
        # Mugello: Renate (87.9) #1, Mike (88.0) #2, Stefan (88.5) #3
        cls.lap_renate_mugello = _add_lap(db, cls.renate, "Mugello", 87.9, "Renate")
        cls.lap_mike_mugello = _add_lap(db, cls.mike, "Mugello", 88.0, "mike")
        cls.lap_stefan_mugello = _add_lap(db, cls.stefan, "Mugello", 88.5, "Stefan")
        # Hockenheim: nur Mike (95.0) — Top-1 ohne #2/#3
        cls.lap_mike_hockenheim = _add_lap(db, cls.mike, "Hockenheim", 95.0, "mike")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_records_anon_renders(self):
        r = self.srv.request("GET", "/records")
        self.assertEqual(r["status"], 200)
        body = r["body"].decode("utf-8")
        self.assertIn(">BESTZEITEN<", body)

    def test_three_tracks_visible(self):
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        self.assertIn(">Aragon<", body)
        self.assertIn(">Mugello<", body)
        self.assertIn(">Hockenheim<", body)

    def test_tracks_alphabetically_sorted(self):
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        i_a = body.find('class="rec-track-name">Aragon')
        i_h = body.find('class="rec-track-name">Hockenheim')
        i_m = body.find('class="rec-track-name">Mugello')
        self.assertGreater(i_a, 0)
        self.assertGreater(i_h, i_a)
        self.assertGreater(i_m, i_h)

    def test_top1_has_gold_medal(self):
        # v23.5: Statt SVG-Medaillen-Icon trägt der Gold-Sockel die
        # CSS-Klasse rec-step-1 und zeigt eine "1" als rec-rank.
        # Pro Strecke ein Gold-Sockel → drei mit "rec-step-1" gesamt.
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        body_html = body[body.find("</style>"):]
        gold_count = body_html.count("rec-step-1")
        self.assertEqual(gold_count, 3)

    def test_top3_medal_counts(self):
        # v23.10: Dedupe pro Fahrer. Aragon hat Renate #1 + Stefan #2 —
        # Stefans zweite Runde zählt nicht mehr, also KEIN Bronze dort.
        # Mugello hat 3 verschiedene Fahrer → Silber + Bronze echt.
        # Hockenheim nur Gold. → Silber echt: 2, Bronze echt: 1.
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        body_html = body[body.find("</style>"):]
        # Echte Silber-Sockel: 'rec-step-2"' (ohne "empty" daran)
        silver_real = body_html.count('rec-step rec-step-2"')
        bronze_real = body_html.count('rec-step rec-step-3"')
        self.assertEqual(silver_real, 2)
        self.assertEqual(bronze_real, 1)

    def test_owner_links_to_profile(self):
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        # Renate's Profil sollte verlinkt sein (sie hält Bestzeiten)
        self.assertRegex(
            body,
            r'<a href="/profile/' + str(self.renate) + r'"\s+class="rec-owner-link"'
        )

    def test_driver_name_preferred_over_email(self):
        # Renate hat driver_name="Renate" → wird angezeigt, nicht "renate"
        # (E-Mail-Local-Part)
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        self.assertIn(">Renate<", body)
        # E-Mail-Adresse soll NICHT komplett geleakt werden
        self.assertNotIn("renate@x.de", body)

    def test_no_driver_name_fallback_to_localpart(self):
        # Mike hat keinen driver_name gesetzt im profile, aber der Session-
        # driver-Field hat "mike". Eine der beiden Werte muss kommen, aber
        # NIE die ganze E-Mail.
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        self.assertNotIn("mike@x.de", body)
        # Mike's Display-Name ist irgendwo da (Session driver-Field "mike")
        # — gelinkter Owner-Anchor:
        self.assertRegex(
            body,
            r'<a href="/profile/' + str(self.mike) + r'"\s+class="rec-owner-link"'
        )

    def test_lap_link_to_analyze(self):
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        # Jeder Eintrag sollte einen /analyze-Link haben
        self.assertRegex(body, r'href="/analyze\?lap_id=\d+&go=1"')

    def test_times_formatted(self):
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        # Renate 90.5s → 1:30.500, Stefan 91.8 → 1:31.800
        self.assertIn("1:30.500", body)
        self.assertIn("1:31.800", body)
        self.assertIn("1:27.900", body)  # Renate Mugello

    def test_logged_in_user_can_view(self):
        cookie = self.srv.login("stefan@x.de", "secret123")
        r = self.srv.request("GET", "/records",
                             headers={"Cookie": cookie})
        self.assertEqual(r["status"], 200)

    def test_header_marks_records_active(self):
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        self.assertRegex(
            body,
            r'<a href="/records" class="active"><span class="label">BESTZEITEN'
        )

    def test_xss_in_track_name_escaped(self):
        # Erst neue Strecke mit Payload anlegen
        _add_lap(webserver.AppState.db, self.stefan,
                 "<script>alert(1)</script>Track", 99.0, "Stefan")
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)


# ---------------------------------------------------------------------------
# (2) Empty-State der /records-Seite
# ---------------------------------------------------------------------------

class TestRecordsEmptyState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        # Kein Setup von Laps — DB ist leer

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_empty_state_shown(self):
        r = self.srv.request("GET", "/records")
        self.assertEqual(r["status"], 200)
        body = r["body"].decode("utf-8")
        self.assertIn("NOCH KEINE BESTZEITEN", body)
        # KEIN .rec-grid Container
        self.assertNotIn('class="rec-grid"', body)


# ---------------------------------------------------------------------------
# (3) Pokal-Icons in der Sessions-Liste
# ---------------------------------------------------------------------------

class TestMedalsInSessionsList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        db = webserver.AppState.db
        cls.u1 = db.create_user(email="a@x.de", password="secret123")
        cls.u2 = db.create_user(email="b@x.de", password="secret123")
        # Aragon: u1 (92.1), u2 (90.5) → u2 ist gold, u1 ist silber
        cls.gold_lap = _add_lap(db, cls.u2, "Aragon", 90.5, "U2")
        cls.silver_lap = _add_lap(db, cls.u1, "Aragon", 92.1, "U1")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_medals_render_in_sessions(self):
        r = self.srv.request("GET", "/sessions")
        body = r["body"].decode("utf-8")
        self.assertIn("medal-gold", body)
        self.assertIn("medal-silver", body)

    def test_lap_medal_span_present(self):
        # Spalte rendert für jede Row, leer wenn keine Medaille
        r = self.srv.request("GET", "/sessions")
        body = r["body"].decode("utf-8")
        # Mindestens zwei lap-medal Spans (eine pro Row)
        n = body.count('class="lap-medal"')
        self.assertGreaterEqual(n, 2)


# ---------------------------------------------------------------------------
# (4) Pokal-Icons auf Profilseite
# ---------------------------------------------------------------------------

class TestMedalsOnProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        db = webserver.AppState.db
        cls.u1 = db.create_user(email="stefan@x.de", password="secret123")
        cls.u2 = db.create_user(email="renate@x.de", password="secret123")
        db.upsert_profile(cls.u1, driver_name="Stefan")
        db.upsert_profile(cls.u2, driver_name="Renate")
        # Aragon: u2 (90.5) #1, u1 (91.8) #2  → u1's Bestzeit ist silber
        _add_lap(db, cls.u2, "Aragon", 90.5, "Renate")
        _add_lap(db, cls.u1, "Aragon", 92.1, "Stefan")
        _add_lap(db, cls.u1, "Aragon", 91.8, "Stefan")
        # Mugello: nur u1 (88.5) → u1 ist gold
        _add_lap(db, cls.u1, "Mugello", 88.5, "Stefan")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_silver_appears_for_user_with_2nd_place(self):
        # Stefan's Aragon-Bestzeit (91.8) ist global #2 → Silber
        r = self.srv.request("GET", f"/profile/{self.u1}")
        body = r["body"].decode("utf-8")
        self.assertIn("medal-silver", body)

    def test_gold_appears_for_user_with_1st_place(self):
        # Stefan's Mugello-Bestzeit ist global #1 (einziger Fahrer) → Gold
        r = self.srv.request("GET", f"/profile/{self.u1}")
        body = r["body"].decode("utf-8")
        self.assertIn("medal-gold", body)

    def test_only_user_specific_bestzeiten_shown(self):
        # Auf Stefan's Profil: Renate's Gold auf Aragon erscheint NICHT
        # (das ist nicht Stefan's Bestzeit). Stefan hat genau zwei
        # Bestzeiten (Aragon + Mugello), entsprechend zwei Medaillen.
        r = self.srv.request("GET", f"/profile/{self.u1}")
        body = r["body"].decode("utf-8")
        # Genau 1× Silver + 1× Gold = 2 Medaillen in der .best-laps
        # Tabelle. Aber die SVGs haben "medal-gold" und "medal-silver"
        # auch in <style>-Block nicht — also können wir direkt zählen.
        # NB: das .bl-medal Span ist immer da (auch leer); wir zählen
        # die echten SVG-Klassen.
        medal_count = (body.count("medal-gold") + body.count("medal-silver")
                       + body.count("medal-bronze"))
        # 1 Gold (Mugello) + 1 Silver (Aragon) = 2
        self.assertEqual(medal_count, 2)

    def test_no_medal_for_user_without_top3(self):
        # Renate ist Gold auf Aragon → ihre Bestzeit dort sollte Gold
        # zeigen. Sie hat keine Mugello-Runde, also nur eine Medaille.
        r = self.srv.request("GET", f"/profile/{self.u2}")
        body = r["body"].decode("utf-8")
        self.assertIn("medal-gold", body)
        self.assertNotIn("medal-silver", body)


# ---------------------------------------------------------------------------
# (5) Landing-Tile
# ---------------------------------------------------------------------------

class TestLandingTile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_landing_has_records_tile(self):
        r = self.srv.request("GET", "/")
        body = r["body"].decode("utf-8")
        self.assertIn('class="hub-card records"', body)
        self.assertIn('href="/records"', body)
        self.assertIn('hub-card-title">BESTZEITEN', body)

    def test_header_has_bestzeiten_link(self):
        r = self.srv.request("GET", "/")
        body = r["body"].decode("utf-8")
        self.assertIn('<a href="/records"', body)
        self.assertIn('>BESTZEITEN<', body)


# ---------------------------------------------------------------------------
# (6) v23.5 — Echtes Podium-Layout (Treppchen) + Motorrad unter dem Namen
# ---------------------------------------------------------------------------

class TestPodiumLayout(unittest.TestCase):
    """v23.5 — Pro Strecke ein Treppchen mit Sieger in der Mitte (Gold)
    am höchsten, Silber links mittel, Bronze rechts am niedrigsten.
    Fahrer-Info über dem Sockel. Motorrad unter dem Fahrernamen wenn
    vorhanden. Akzentfarbe nicht mehr das tiefe #00d4ff."""

    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        db = webserver.AppState.db
        cls.stefan = db.create_user(email="stefan@x.de", password="x" * 8)
        cls.renate = db.create_user(email="renate@x.de", password="x" * 8)
        db.upsert_profile(cls.stefan, driver_name="Stefan")
        db.upsert_profile(cls.renate, driver_name="Renate")
        # Aragon: 3 Einträge — Stefan auf "CBR 1000", Renate auf "R6",
        # einer ohne Bike-Eintrag.
        _add_lap(db, cls.renate, "Aragon", 90.5, "Renate", "R6")
        _add_lap(db, cls.stefan, "Aragon", 91.8, "Stefan", "CBR 1000")
        _add_lap(db, cls.stefan, "Aragon", 92.1, "Stefan", "")
        # Hockenheim: nur 1 Eintrag — fehlende Slots werden ausgegraut.
        _add_lap(db, cls.renate, "Hockenheim", 95.0, "Renate", "R6")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def _body_html(self):
        """Liefert den HTML-Body ohne den <style>-Block, damit
        Klassen-Greps nicht versehentlich im CSS treffen."""
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        return body[body.find("</style>"):]

    def test_podium_has_three_steps(self):
        body = self._body_html()
        self.assertIn('class="rec-podium"', body)
        self.assertIn('rec-step rec-step-1', body)
        self.assertIn('rec-step rec-step-2', body)
        self.assertIn('rec-step rec-step-3', body)
        self.assertIn('class="rec-rank"', body)
        self.assertIn('class="rec-divider"', body)
        self.assertIn('class="rec-driver"', body)

    def test_dom_order_is_silver_gold_bronze(self):
        body = self._body_html()
        i_silver = body.find('rec-step-2')
        i_gold = body.find('rec-step-1')
        i_bronze = body.find('rec-step-3')
        self.assertGreater(i_silver, 0)
        self.assertGreater(i_gold, i_silver,
                           "Gold muss DOM-mässig nach Silber kommen.")
        self.assertGreater(i_bronze, i_gold)

    def test_step_is_div_not_anchor(self):
        # v23.5 robust: der Sockel-Container ist ein <div>, NICHT <a>.
        # Browser behandeln <a> in Flex/Grid-Containern in seltenen
        # Konstellationen inkonsistent — der <div> ist immer sicher.
        # Der Klick-Link sitzt als position:absolute Overlay drin.
        body = self._body_html()
        self.assertRegex(body, r'<div class="rec-step rec-step-1"')
        # KEIN <a class="rec-step ..."> (mit Klassennamen direkt am a)
        self.assertNotRegex(body, r'<a [^>]*class="rec-step rec-step-')

    def test_step_link_overlay_present(self):
        # Der Sockel-Klick funktioniert über ein <a class="rec-step-link">
        # innerhalb des <div class="rec-step">.
        body = self._body_html()
        self.assertRegex(
            body,
            r'<div class="rec-step rec-step-1">\s*'
            r'<a href="/analyze\?lap_id=\d+&go=1"\s+'
            r'class="rec-step-link"'
        )

    def test_rank_number_on_each_step(self):
        body = self._body_html()
        # Gold-Sockel: rec-step-1 div → enthält rec-rank "1"
        # (zwischen kommt jetzt der Klick-Link-Anchor)
        self.assertRegex(
            body,
            r'<div class="rec-step rec-step-1">.*?'
            r'<div class="rec-rank">\s*1\s*</div>',
            "Gold-Sockel muss '1' als rec-rank zeigen."
        )
        self.assertRegex(
            body,
            r'<div class="rec-step rec-step-2">.*?'
            r'<div class="rec-rank">\s*2\s*</div>',
            "Silber-Sockel muss '2' als rec-rank zeigen."
        )

    def test_bike_shown_on_step(self):
        body = self._body_html()
        self.assertRegex(body, r'class="rec-bike"[^>]*>R6<')
        self.assertRegex(body, r'class="rec-bike"[^>]*>CBR 1000<')

    def test_no_bike_no_bike_row(self):
        body = self._body_html()
        self.assertNotIn('class="rec-bike" title=""', body)
        self.assertNotIn('class="rec-bike"></div>', body)

    def test_bike_html_escaped(self):
        db = webserver.AppState.db
        u = db.create_user(email="xss@x.de", password="x" * 8)
        _add_lap(db, u, "Imola", 88.0, "X", "<script>alert(1)</script>")
        body = self._body_html()
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_empty_slots_for_missing_ranks(self):
        body = self._body_html()
        self.assertIn('rec-step rec-step-2 empty', body)
        self.assertIn('rec-step rec-step-3 empty', body)

    def test_accent_color_is_lighter(self):
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        m = re.search(r"<style>(.*?)</style>", body, re.DOTALL)
        self.assertIsNotNone(m)
        css = m.group(1)
        self.assertRegex(css, r"--accent\s*:\s*#")
        self.assertNotRegex(css, r"--accent\s*:\s*#00d4ff")

    def test_driver_name_still_renders_as_link(self):
        body = self._body_html()
        self.assertRegex(
            body,
            r'<a href="/profile/' + str(self.stefan) + r'"\s+class="rec-owner-link"'
        )

    def test_db_returns_bike_field(self):
        rows = webserver.AppState.db.global_top_n_per_track(3)
        any_bike = False
        for track in rows:
            for e in track["entries"]:
                self.assertIn("bike", e)
                if e["bike"]:
                    any_bike = True
        self.assertTrue(any_bike)

    def test_winner_step_taller_than_silver(self):
        # v23.5 — Höhenstaffelung jetzt über padding-top am Sockel
        # (Gold am meisten, Bronze am wenigsten), nicht über separate
        # spacer divs.
        r = self.srv.request("GET", "/records")
        body = r["body"].decode("utf-8")
        def _pad(rank):
            # ".rec-step-N{...padding-top:Xpx...}" — wir nehmen das
            # erste Vorkommen von padding-top in der Regel für diese
            # Klasse
            m = re.search(
                r"\.rec-step-" + str(rank) + r"\s*\{[^}]*padding-top\s*:\s*(\d+)px",
                body)
            self.assertIsNotNone(m, f"rec-step-{rank} muss padding-top "
                                    "im CSS setzen")
            return int(m.group(1))
        p_gold = _pad(1)
        p_silver = _pad(2)
        p_bronze = _pad(3)
        self.assertGreater(p_gold, p_silver)
        self.assertGreater(p_silver, p_bronze)

    def test_lap_time_on_each_step(self):
        body = self._body_html()
        self.assertIn('class="rec-time"', body)
        self.assertRegex(body, r'class="rec-time">\s*1:30\.500\s*</div>')
        self.assertRegex(body, r'class="rec-time">\s*1:31\.800\s*</div>')
        self.assertNotIn('class="rec-track-time-row"', body)



if __name__ == "__main__":
    unittest.main()
