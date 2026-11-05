#!/usr/bin/env python3
"""tests/test_profile.py — v22.12

Profilverwaltung: Fahrername + n Motorräder pro User. Vier Schichten
getestet:

  (1) DB-CRUD (profiles + bikes tables) — Migration, Upsert, Liste,
      Current-Promotion bei Delete, Auth-Gate über user_id auf jedem
      Bike-Schreibvorgang.
  (2) Image-Helper save_profile_image / delete_profile_image —
      Whitelist-Extensions, Größen-Limit, UUID-Filename-Schema,
      Path-Traversal-Schutz beim Lesen.
  (3) HTTP-Endpunkte (mit hand-gerolltem Test-Server analog
      test_admin_ip_lookup): anon → /login, profile-Save, bike-add /
      edit / delete / set-current, Bild-Serving, Path-Traversal 404,
      Owner-Gate bei fremden Bikes.
  (4) Integration: Upload-Form pre-fillt Driver + Current-Bike;
      Sessions-Liste hat data-* Attribute für Mine-Filter.
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from http.client import HTTPConnection
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import db as dbmod
import webserver


# ---------------------------------------------------------------------------
# Helper: ein echter Test-Server (analog tests/test_admin_ip_lookup.py)
# ---------------------------------------------------------------------------

class _Server:
    """Bootet einen webserver.WebHandler-Server gegen ein frisches
    Tempdir + frische SQLite-DB. Ermöglicht echte HTTP-Roundtrips ohne
    Mocking der Request-Handler."""

    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="racedat-test-profile-")
        webserver.AppState.init(Path(self.tmpdir))
        # Wichtige Defaults so resetten, dass kein Vorgänger-State leakt
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

    def conn(self):
        return HTTPConnection("127.0.0.1", self.port, timeout=5)

    def request(self, method, path, *, body=None, headers=None, follow=False):
        c = self.conn()
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        out = {"status": r.status, "headers": dict(r.getheaders()),
               "body": data}
        c.close()
        return out

    def post_form(self, path, fields, *, cookies=""):
        """multipart/form-data POST. fields: list of (name, value) — wenn
        value ein bytes-tuple (filename, data, content_type), wird's als
        File-Field gesendet."""
        boundary = "----RDtest" + uuid.uuid4().hex
        body = io.BytesIO()
        for name, value in fields:
            body.write(("--" + boundary + "\r\n").encode())
            if isinstance(value, tuple):
                fname, fdata, ctype = value
                body.write(
                    (f'Content-Disposition: form-data; name="{name}"; '
                     f'filename="{fname}"\r\n').encode()
                )
                body.write((f"Content-Type: {ctype}\r\n\r\n").encode())
                body.write(fdata)
                body.write(b"\r\n")
            else:
                body.write(
                    (f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
                    .encode()
                )
                body.write(str(value).encode("utf-8"))
                body.write(b"\r\n")
        body.write(("--" + boundary + "--\r\n").encode())
        b = body.getvalue()
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(b)),
        }
        if cookies:
            headers["Cookie"] = cookies
        return self.request("POST", path, body=b, headers=headers)

    def login(self, email, password):
        """POST /login, gibt Cookie-String zurück."""
        body = f"email={email}&password={password}".encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "Content-Length": str(len(body))}
        r = self.request("POST", "/login", body=body, headers=headers)
        sc = r["headers"].get("Set-Cookie", "")
        # Extrahiere den Token-Teil "name=value"
        m = re.match(r"([^=]+)=([^;]+);", sc)
        if not m:
            return ""
        return f"{m.group(1)}={m.group(2)}"


# Mini-PNG für Image-Upload-Tests (1×1 transparent, valid header).
_TINY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf'
    b'\x00\x00\x00\x03\x00\x01\x5a\xf6\x16\xff\x00\x00\x00\x00IEND\xaeB`\x82'
)


# ---------------------------------------------------------------------------
# (1) DB-CRUD
# ---------------------------------------------------------------------------

class TestProfileCRUD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rd-prof-")
        self.db = dbmod.DB(Path(self.tmp) / "x.db")
        self.uid = self.db.create_user(email="a@x.de", password="secret123")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_profile_returns_synthetic_dict(self):
        # Nie gespeichert → gleiche Form wie ein realer Datensatz, aber leer
        p = self.db.get_profile(self.uid)
        self.assertEqual(p["user_id"], self.uid)
        self.assertEqual(p["driver_name"], "")
        self.assertEqual(p["image_path"], "")

    def test_upsert_creates_then_updates(self):
        self.db.upsert_profile(self.uid, driver_name="Alice", image_path="a.jpg")
        p = self.db.get_profile(self.uid)
        self.assertEqual(p["driver_name"], "Alice")
        self.assertEqual(p["image_path"], "a.jpg")
        # Zweiter Aufruf updated
        self.db.upsert_profile(self.uid, driver_name="Bob", image_path="b.jpg")
        p = self.db.get_profile(self.uid)
        self.assertEqual(p["driver_name"], "Bob")
        self.assertEqual(p["image_path"], "b.jpg")

    def test_upsert_image_none_keeps_existing(self):
        """image_path=None bedeutet "Bild nicht anfassen", "" heisst "leeren"."""
        self.db.upsert_profile(self.uid, driver_name="A", image_path="keep.jpg")
        self.db.upsert_profile(self.uid, driver_name="B", image_path=None)
        self.assertEqual(self.db.get_profile(self.uid)["image_path"], "keep.jpg")
        self.db.upsert_profile(self.uid, driver_name="B", image_path="")
        self.assertEqual(self.db.get_profile(self.uid)["image_path"], "")

    def test_first_bike_forced_current(self):
        """Auch wenn is_current=False, das erste Bike wird current. Sonst
        hätte die Upload-Pre-Fill für neue User leeres Bike-Feld."""
        bid = self.db.add_bike(self.uid, name="CBR", is_current=False)
        bk = self.db.get_bike(bid)
        self.assertTrue(bk["is_current"])
        self.assertEqual(self.db.get_current_bike(self.uid)["id"], bid)

    def test_second_bike_doesnt_steal_current(self):
        b1 = self.db.add_bike(self.uid, name="CBR")
        b2 = self.db.add_bike(self.uid, name="R6")
        self.assertEqual(self.db.get_current_bike(self.uid)["id"], b1)
        # Setze b2 explizit als current
        self.db.add_bike(self.uid, name="GSXR", is_current=True)
        # GSXR ist jetzt current, b1 nicht mehr
        cur = self.db.get_current_bike(self.uid)
        self.assertEqual(cur["name"], "GSXR")
        self.assertFalse(self.db.get_bike(b1)["is_current"])

    def test_at_most_one_current(self):
        b1 = self.db.add_bike(self.uid, name="CBR")
        b2 = self.db.add_bike(self.uid, name="R6")
        self.db.set_current_bike(b2, self.uid)
        currents = [b for b in self.db.list_bikes(self.uid) if b["is_current"]]
        self.assertEqual(len(currents), 1)
        self.assertEqual(currents[0]["id"], b2)

    def test_set_current_owner_check(self):
        other = self.db.create_user(email="b@x.de", password="secret123")
        b1 = self.db.add_bike(self.uid, name="CBR")
        self.assertFalse(self.db.set_current_bike(b1, other))

    def test_delete_promotes_next_when_current(self):
        b1 = self.db.add_bike(self.uid, name="CBR")  # current
        b2 = self.db.add_bike(self.uid, name="R6")
        self.db.delete_bike(b1, self.uid)
        # b2 sollte jetzt current sein (einziges verbliebenes Bike)
        cur = self.db.get_current_bike(self.uid)
        self.assertIsNotNone(cur)
        self.assertEqual(cur["id"], b2)

    def test_delete_no_promotion_when_not_current(self):
        """Wenn ein Nicht-Current gelöscht wird, bleibt das Current
        unverändert (keine Lottery)."""
        b1 = self.db.add_bike(self.uid, name="CBR")  # current
        b2 = self.db.add_bike(self.uid, name="R6")
        self.db.delete_bike(b2, self.uid)
        self.assertEqual(self.db.get_current_bike(self.uid)["id"], b1)

    def test_delete_returns_image_path(self):
        b1 = self.db.add_bike(self.uid, name="CBR", image_path="cbr.jpg")
        img = self.db.delete_bike(b1, self.uid)
        self.assertEqual(img, "cbr.jpg")

    def test_delete_other_user_denied(self):
        other = self.db.create_user(email="b@x.de", password="secret123")
        b1 = self.db.add_bike(self.uid, name="CBR")
        self.assertIsNone(self.db.delete_bike(b1, other))
        # Bike ist noch da
        self.assertIsNotNone(self.db.get_bike(b1))

    def test_update_other_user_denied(self):
        other = self.db.create_user(email="b@x.de", password="secret123")
        b1 = self.db.add_bike(self.uid, name="CBR")
        self.assertFalse(self.db.update_bike(b1, other, name="Stolen"))
        self.assertEqual(self.db.get_bike(b1)["name"], "CBR")

    def test_add_bike_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            self.db.add_bike(self.uid, name="")
        with self.assertRaises(ValueError):
            self.db.add_bike(self.uid, name="   ")

    def test_add_bike_too_long_rejected(self):
        with self.assertRaises(ValueError):
            self.db.add_bike(self.uid, name="x" * 201)

    def test_update_keeps_image_when_none(self):
        b1 = self.db.add_bike(self.uid, name="CBR", image_path="cbr.jpg")
        self.db.update_bike(b1, self.uid, name="CBR 1000")
        self.assertEqual(self.db.get_bike(b1)["image_path"], "cbr.jpg")

    def test_update_clears_image_when_empty_string(self):
        b1 = self.db.add_bike(self.uid, name="CBR", image_path="cbr.jpg")
        self.db.update_bike(b1, self.uid, name=None, image_path="")
        self.assertEqual(self.db.get_bike(b1)["image_path"], "")

    def test_user_cascade_deletes_profile_and_bikes(self):
        """FK ON DELETE CASCADE — User-Delete räumt seine Profile + Bikes."""
        self.db.upsert_profile(self.uid, driver_name="X")
        self.db.add_bike(self.uid, name="CBR")
        self.db.delete_user(self.uid)
        self.assertEqual(self.db.list_bikes(self.uid), [])
        # get_profile() gibt ein synthetisches leeres Profil — nicht None
        p = self.db.get_profile(self.uid)
        self.assertEqual(p["driver_name"], "")


# ---------------------------------------------------------------------------
# (2) Image-Helper
# ---------------------------------------------------------------------------

class TestImageHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rd-img-")
        webserver.AppState.init(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_jpg_returns_uuid_filename(self):
        fname = webserver.save_profile_image(_TINY_PNG, "photo.jpg")
        self.assertTrue(fname.endswith(".jpg"))
        self.assertRegex(fname, webserver._PROFILE_IMG_NAME_RE)
        # File liegt physisch
        self.assertTrue(
            (webserver.AppState.profile_images_dir / fname).is_file()
        )

    def test_jpeg_normalized_to_jpg(self):
        fname = webserver.save_profile_image(_TINY_PNG, "photo.JPEG")
        self.assertTrue(fname.endswith(".jpg"))

    def test_png_extension(self):
        fname = webserver.save_profile_image(_TINY_PNG, "photo.PNG")
        self.assertTrue(fname.endswith(".png"))

    def test_webp_extension(self):
        fname = webserver.save_profile_image(_TINY_PNG, "photo.webp")
        self.assertTrue(fname.endswith(".webp"))

    def test_reject_unknown_extension(self):
        with self.assertRaises(ValueError):
            webserver.save_profile_image(_TINY_PNG, "photo.gif")
        with self.assertRaises(ValueError):
            webserver.save_profile_image(_TINY_PNG, "photo.svg")
        with self.assertRaises(ValueError):
            webserver.save_profile_image(_TINY_PNG, "noext")

    def test_reject_empty(self):
        with self.assertRaises(ValueError):
            webserver.save_profile_image(b"", "x.jpg")

    def test_reject_oversize(self):
        big = b"x" * (webserver.PROFILE_IMAGE_MAX_BYTES + 1)
        with self.assertRaises(ValueError):
            webserver.save_profile_image(big, "x.jpg")

    def test_unique_filenames_even_same_input(self):
        a = webserver.save_profile_image(_TINY_PNG, "x.png")
        b = webserver.save_profile_image(_TINY_PNG, "x.png")
        self.assertNotEqual(a, b)

    def test_delete_existing(self):
        fname = webserver.save_profile_image(_TINY_PNG, "x.png")
        self.assertTrue(webserver.delete_profile_image(fname))
        self.assertFalse(
            (webserver.AppState.profile_images_dir / fname).exists()
        )

    def test_delete_missing_is_safe(self):
        # Schon weg → returns False, kein Crash
        self.assertFalse(webserver.delete_profile_image(
            "00000000-0000-0000-0000-000000000000.jpg"))

    def test_delete_empty_or_invalid_name(self):
        self.assertFalse(webserver.delete_profile_image(""))
        self.assertFalse(webserver.delete_profile_image("not-a-uuid.jpg"))
        # Path-Traversal-Versuch
        self.assertFalse(webserver.delete_profile_image("../sessions.db"))

    def test_filename_regex_strict(self):
        ok = "12345678-1234-1234-1234-123456789012.jpg"
        self.assertTrue(webserver._PROFILE_IMG_NAME_RE.match(ok))
        # Falsches Format
        bad = [
            "ZZZZZZZZ-1234-1234-1234-123456789012.jpg",  # nicht-hex
            "12345678-1234-1234-1234-123456789012.gif",  # GIF nicht in whitelist
            "../etc/passwd",
            "12345678-1234-1234-1234-123456789012",       # ohne ext
            "subdir/12345678-1234-1234-1234-123456789012.jpg",
        ]
        for n in bad:
            self.assertFalse(webserver._PROFILE_IMG_NAME_RE.match(n),
                             msg=f"sollte ablehnen: {n}")


# ---------------------------------------------------------------------------
# (3) HTTP-Endpunkte
# ---------------------------------------------------------------------------

class TestProfileEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        # User anlegen + einloggen
        webserver.AppState.db.create_user(
            email="stefan@example.com", password="secret123"
        )
        cls.cookie = cls.srv.login("stefan@example.com", "secret123")
        cls.user_id = 1  # erstes user-record in der frischen DB

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_anon_profile_redirects_to_login(self):
        r = self.srv.request("GET", "/profile")
        self.assertEqual(r["status"], 303)
        loc = r["headers"].get("Location", "")
        self.assertIn("/login", loc)
        self.assertIn("next=", loc)

    def test_logged_in_profile_renders(self):
        r = self.srv.request("GET", "/profile",
                             headers={"Cookie": self.cookie})
        self.assertEqual(r["status"], 200)
        body = r["body"].decode("utf-8")
        # Eyebrow + Headline
        self.assertIn("PROFIL", body)
        self.assertIn("FAHRERNAME", body)
        # Mein-Runden-Link
        self.assertIn("/sessions?mine=1", body)

    def test_profile_page_has_header_with_profile_link(self):
        # Header rendert PROFIL-Link auch für anon (Klick → Redirect)
        r = self.srv.request("GET", "/")
        body = r["body"].decode("utf-8")
        self.assertIn('href="/profile"', body)
        self.assertIn(">PROFIL<", body)

    def test_profile_save_sets_driver_name(self):
        r = self.srv.post_form("/profile/save",
                               [("driver_name", "Stefan Müller")],
                               cookies=self.cookie)
        self.assertEqual(r["status"], 303)
        self.assertIn("/profile?saved=1", r["headers"]["Location"])
        # Nachher in der DB
        p = webserver.AppState.db.get_profile(self.user_id)
        self.assertEqual(p["driver_name"], "Stefan Müller")

    def test_profile_save_with_image(self):
        r = self.srv.post_form(
            "/profile/save",
            [("driver_name", "Stefan"),
             ("image", ("p.png", _TINY_PNG, "image/png"))],
            cookies=self.cookie,
        )
        self.assertEqual(r["status"], 303)
        p = webserver.AppState.db.get_profile(self.user_id)
        self.assertTrue(p["image_path"])
        self.assertRegex(p["image_path"], webserver._PROFILE_IMG_NAME_RE)

    def test_bike_add_with_image(self):
        r = self.srv.post_form(
            "/profile/bike/add",
            [("name", "CBR 1000 RR"),
             ("image", ("cbr.png", _TINY_PNG, "image/png"))],
            cookies=self.cookie,
        )
        self.assertEqual(r["status"], 303)
        bikes = webserver.AppState.db.list_bikes(self.user_id)
        names = [b["name"] for b in bikes]
        self.assertIn("CBR 1000 RR", names)

    def test_bike_add_empty_name_redirects_with_error(self):
        r = self.srv.post_form("/profile/bike/add",
                               [("name", "  ")],
                               cookies=self.cookie)
        self.assertEqual(r["status"], 303)
        self.assertIn("error=", r["headers"]["Location"])

    def test_bike_set_current_other_users_bike_denied(self):
        # Zweiter User legt sich ein Bike an
        other_uid = webserver.AppState.db.create_user(
            email="other@example.com", password="secret123")
        other_bike = webserver.AppState.db.add_bike(other_uid, name="Foreign")
        # Stefan versucht das Foreign-Bike als current zu markieren
        r = self.srv.post_form(
            f"/profile/bike/{other_bike}/set-current", [],
            cookies=self.cookie,
        )
        self.assertEqual(r["status"], 303)
        # Bike bleibt im anderen User
        b = webserver.AppState.db.get_bike(other_bike)
        self.assertEqual(b["user_id"], other_uid)

    def test_anon_bike_post_redirects(self):
        r = self.srv.post_form("/profile/bike/add",
                               [("name", "Anything")])
        self.assertEqual(r["status"], 303)
        self.assertIn("/login", r["headers"]["Location"])

    def test_serve_profile_image_public(self):
        # Lade ein Bild hoch
        fname = webserver.save_profile_image(_TINY_PNG, "test.png")
        # Anonyme Anfrage geht durch (no auth needed for read)
        r = self.srv.request("GET", f"/profile/image/{fname}")
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["body"], _TINY_PNG)
        self.assertEqual(r["headers"]["Content-Type"], "image/png")

    def test_serve_profile_image_invalid_filename(self):
        # Kein UUID-Schema
        r = self.srv.request("GET", "/profile/image/not-a-uuid.jpg")
        self.assertEqual(r["status"], 404)

    def test_serve_profile_image_path_traversal_blocked(self):
        # Regex matched gar nicht — 404 wird vom Router (do_GET) zurückgegeben,
        # weil der Regex die Slashes nicht akzeptiert
        r = self.srv.request("GET", "/profile/image/../sessions.db")
        self.assertEqual(r["status"], 404)

    def test_serve_profile_image_unknown_uuid(self):
        # Korrektes Schema, aber Datei existiert nicht
        r = self.srv.request("GET",
            "/profile/image/00000000-0000-0000-0000-000000000000.jpg")
        self.assertEqual(r["status"], 404)


# ---------------------------------------------------------------------------
# (4) Integration: Upload-Form pre-fill + Sessions-Liste data-attrs
# ---------------------------------------------------------------------------

class TestProfileIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Server()
        webserver.AppState.db.create_user(
            email="x@example.com", password="secret123")
        cls.cookie = cls.srv.login("x@example.com", "secret123")

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def test_upload_form_empty_profile_no_prefill(self):
        # Frischer User, kein Profil-Speichern → keine value=, kein Hint
        r = self.srv.request("GET", "/sessions/upload",
                             headers={"Cookie": self.cookie})
        body = r["body"].decode("utf-8")
        self.assertIn('name="driver"', body)
        # value="" oder gar kein value-Attribut
        self.assertNotIn("Aus Profil vorbelegt", body)

    def test_upload_form_prefills_driver_and_current_bike(self):
        webserver.AppState.db.upsert_profile(1, driver_name="Renate")
        webserver.AppState.db.add_bike(1, name="CBR 1000 RR")
        r = self.srv.request("GET", "/sessions/upload",
                             headers={"Cookie": self.cookie})
        body = r["body"].decode("utf-8")
        self.assertIn('value="Renate"', body)
        self.assertIn('value="CBR 1000 RR"', body)
        self.assertIn("Aus Profil vorbelegt", body)

    def test_upload_form_uses_current_bike_after_switch(self):
        webserver.AppState.db.upsert_profile(1, driver_name="Renate")
        b1 = webserver.AppState.db.add_bike(1, name="CBR 1000 RR")
        b2 = webserver.AppState.db.add_bike(1, name="R6")
        # Per Default ist b1 current (first-bike-promotion). Wir switchen:
        webserver.AppState.db.set_current_bike(b2, 1)
        r = self.srv.request("GET", "/sessions/upload",
                             headers={"Cookie": self.cookie})
        body = r["body"].decode("utf-8")
        self.assertIn('value="R6"', body)

    def test_sessions_list_has_data_attrs_for_mine_filter(self):
        # Logged-in user
        r = self.srv.request("GET", "/sessions",
                             headers={"Cookie": self.cookie})
        body = r["body"].decode("utf-8")
        self.assertIn('data-logged-in="1"', body)
        self.assertIn('data-cur-user-id="1"', body)
        self.assertIn('data-mine-default=""', body)

    def test_sessions_list_with_mine_param_sets_default(self):
        r = self.srv.request("GET", "/sessions?mine=1",
                             headers={"Cookie": self.cookie})
        body = r["body"].decode("utf-8")
        self.assertIn('data-mine-default="1"', body)

    def test_sessions_list_anon_ignores_mine_param(self):
        # Ohne Cookie: data-logged-in=0, mine-default leer
        r = self.srv.request("GET", "/sessions?mine=1")
        body = r["body"].decode("utf-8")
        self.assertIn('data-logged-in="0"', body)
        # mine=1 wird nicht aktiviert wenn nicht eingeloggt
        self.assertIn('data-mine-default=""', body)

    def test_landing_has_profile_tile(self):
        r = self.srv.request("GET", "/")
        body = r["body"].decode("utf-8")
        # Tile + Link
        self.assertIn('hub-card profile', body)
        self.assertIn('href="/profile"', body)
        # Beibehaltene Tiles
        self.assertIn('hub-card-title">RUNDEN', body)
        self.assertIn('hub-card-title">DATENVIEWER', body)

    def test_landing_tile_flatter(self):
        # Stefan hat um "etwas flacher" gebeten: min-height ist von 200
        # auf 130 reduziert (siehe v22.12-Diff in landing.html). Wir
        # checken den Pixel-Wert um Regressionen zu fangen.
        r = self.srv.request("GET", "/")
        body = r["body"].decode("utf-8")
        self.assertIn("min-height:130px", body)
        self.assertNotIn("min-height:200px", body)


# ---------------------------------------------------------------------------
# (5) Header: PROFIL-Link auf jeder Seite, immer sichtbar
# ---------------------------------------------------------------------------

class TestProfileLinkInHeader(unittest.TestCase):
    def test_header_includes_profile_link_for_anon(self):
        # Pure-function-Test, kein Server nötig
        hdr = webserver.build_header_html(None, "/")
        self.assertIn('href="/profile"', hdr)
        self.assertIn(">PROFIL<", hdr)

    def test_header_includes_profile_link_for_user(self):
        hdr = webserver.build_header_html(
            {"id": 1, "email": "x@y", "is_admin": False}, "/")
        self.assertIn('href="/profile"', hdr)

    def test_header_marks_active_on_profile_path(self):
        hdr = webserver.build_header_html(None, "/profile")
        # Der PROFIL-Link sollte class="active" haben
        # Wir matchen den Link mit aktiver Klasse:
        self.assertRegex(
            hdr,
            r'<a href="/profile" class="active"><span class="label">PROFIL'
        )

    def test_header_does_not_mark_profile_active_on_other_paths(self):
        hdr = webserver.build_header_html(None, "/sessions")
        # PROFIL-Link existiert, hat aber kein class="active"
        self.assertIn('<a href="/profile"><span class="label">PROFIL', hdr)


# ---------------------------------------------------------------------------
# (6) Bestzeiten pro Strecke — DB-Method + Render-Helper (v23.1)
# ---------------------------------------------------------------------------

class TestBestLapPerTrackDB(unittest.TestCase):
    """Direkte DB-Tests für db.best_lap_per_track_for_user(). Isoliert
    von Webserver-State."""

    def setUp(self):
        import numpy as np
        self.tmp = tempfile.mkdtemp(prefix="rd-bl-")
        self.db = dbmod.DB(Path(self.tmp) / "x.db")
        self.uid = self.db.create_user(email="a@x.de", password="secret123")
        self.other = self.db.create_user(email="b@x.de", password="secret123")
        self._np = np

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ld(self, dur):
        return {
            "time": self._np.array([0.0, dur]),
            "speed": self._np.array([100.0, 100.0]),
            "distance": self._np.array([0.0, 30.0]),
            "lat": self._np.array([0.0]),
            "lon": self._np.array([0.0]),
            "lap_index": 1, "duration": dur,
        }

    def _add(self, user_id, track, dur, sleep=0.005):
        import time as _t
        sid = self.db.create_session(
            original_filename="x", file_path="/tmp/x",
            user_id=user_id, driver="X", bike="", track=track,
            session_date="2026-01-01", notes="", format="ses",
        )
        self.db.add_lap(sid, 1, dur, self._ld(dur))
        _t.sleep(sleep)
        return sid

    def test_unknown_user_returns_empty(self):
        self.assertEqual(self.db.best_lap_per_track_for_user(99999), [])

    def test_user_without_laps_returns_empty(self):
        self.assertEqual(self.db.best_lap_per_track_for_user(self.uid), [])

    def test_one_track_one_lap(self):
        self._add(self.uid, "Aragon", 92.5)
        bests = self.db.best_lap_per_track_for_user(self.uid)
        self.assertEqual(len(bests), 1)
        self.assertEqual(bests[0]["track"], "Aragon")
        self.assertAlmostEqual(bests[0]["duration_s"], 92.5)

    def test_picks_fastest_per_track(self):
        self._add(self.uid, "Aragon", 92.5)
        self._add(self.uid, "Aragon", 91.0)  # bestzeit
        self._add(self.uid, "Aragon", 93.1)
        bests = self.db.best_lap_per_track_for_user(self.uid)
        self.assertEqual(len(bests), 1)
        self.assertAlmostEqual(bests[0]["duration_s"], 91.0)

    def test_excludes_empty_track(self):
        self._add(self.uid, "Aragon", 92.5)
        self._add(self.uid, "", 70.0)  # would be faster but track is empty
        bests = self.db.best_lap_per_track_for_user(self.uid)
        self.assertEqual(len(bests), 1)
        self.assertEqual(bests[0]["track"], "Aragon")

    def test_case_insensitive_track_grouping(self):
        # Drei Schreibweisen sollten zu einem Bucket kollabieren.
        self._add(self.uid, "Aragon", 92.5)   # first → canonical name
        self._add(self.uid, "aragon", 91.5)   # tatsächlich schnellste
        self._add(self.uid, "ARAGON", 92.0)
        bests = self.db.best_lap_per_track_for_user(self.uid)
        self.assertEqual(len(bests), 1)
        # Canonical name = first-seen spelling
        self.assertEqual(bests[0]["track"], "Aragon")
        self.assertAlmostEqual(bests[0]["duration_s"], 91.5)

    def test_multiple_tracks_sorted_fastest_first(self):
        self._add(self.uid, "Aragon", 92.5)
        self._add(self.uid, "Mugello", 88.0)
        self._add(self.uid, "Hockenheim", 105.0)
        bests = self.db.best_lap_per_track_for_user(self.uid)
        names = [b["track"] for b in bests]
        durations = [b["duration_s"] for b in bests]
        self.assertEqual(names, ["Mugello", "Aragon", "Hockenheim"])
        # Sortierung explizit prüfen
        self.assertTrue(all(durations[i] <= durations[i+1]
                            for i in range(len(durations)-1)))

    def test_does_not_bleed_across_users(self):
        # Stefan hat Mugello in 90.0, Renate hat Mugello in 85.0 — beide
        # erscheinen NUR in ihrer eigenen Bestzeitenliste, nie gemischt.
        self._add(self.uid, "Mugello", 90.0)
        self._add(self.other, "Mugello", 85.0)
        bests_u1 = self.db.best_lap_per_track_for_user(self.uid)
        bests_u2 = self.db.best_lap_per_track_for_user(self.other)
        self.assertAlmostEqual(bests_u1[0]["duration_s"], 90.0)
        self.assertAlmostEqual(bests_u2[0]["duration_s"], 85.0)

    def test_returns_lap_id_for_click_through(self):
        sid = self._add(self.uid, "Aragon", 91.5)
        bests = self.db.best_lap_per_track_for_user(self.uid)
        # lap_id muss eine echte Lap-Row referenzieren
        lap_id = bests[0]["lap_id"]
        rec = self.db.get_lap(lap_id)
        self.assertIsNotNone(rec)
        self.assertAlmostEqual(rec["duration_s"], 91.5)

    def test_includes_session_date(self):
        sid = self.db.create_session(
            original_filename="x", file_path="/tmp/x",
            user_id=self.uid, driver="X", bike="", track="Aragon",
            session_date="2026-05-22", notes="", format="ses",
        )
        self.db.add_lap(sid, 1, 91.5, self._ld(91.5))
        bests = self.db.best_lap_per_track_for_user(self.uid)
        self.assertEqual(bests[0]["session_date"], "2026-05-22")


class TestRenderBestLapsHelper(unittest.TestCase):
    """Pure-Function-Tests für webserver.render_best_laps_html()."""

    def test_empty_input_returns_placeholder(self):
        out = webserver.render_best_laps_html([])
        self.assertIn("NOCH KEINE BESTZEITEN", out)
        # KEIN .best-laps Container (das ist der echte Tabellen-Wrapper)
        self.assertNotIn('class="best-laps"', out)

    def test_single_row_has_link_and_time(self):
        # v23.2: Datum nicht mehr in der Tabelle (Stefan-Bugfix).
        # Wir geben das Datum trotzdem an den Helper weiter — er
        # ignoriert es im Output.
        out = webserver.render_best_laps_html([
            {"track": "Aragon", "duration_s": 91.5,
             "lap_id": 42, "session_date": "2026-05-22"},
        ])
        self.assertIn('class="best-laps"', out)
        self.assertIn('class="bl-row"', out)
        self.assertIn('href="/analyze?lap_id=42&go=1"', out)
        # Formatierung M:SS.sss
        self.assertIn("1:31.500", out)
        self.assertIn("Aragon", out)
        # v23.2: Datum erscheint NICHT mehr im Output, auch wenn an den
        # Helper übergeben.
        self.assertNotIn("2026-05-22", out)
        self.assertNotIn('class="bl-date"', out)

    def test_xss_in_track_name_escaped(self):
        out = webserver.render_best_laps_html([
            {"track": "<script>alert(1)</script>",
             "duration_s": 91.5, "lap_id": 1, "session_date": ""},
        ])
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_date_not_in_output(self):
        # v23.2 — Stefan-Bugfix: Datum darf nirgends rauskommen, egal
        # was an den Helper übergeben wird (das Input-Feld bleibt erhalten
        # für künftige API-Konsumenten, aber im HTML wird's ausgeblendet).
        out = webserver.render_best_laps_html([
            {"track": "Aragon", "duration_s": 91.5,
             "lap_id": 1, "session_date": "2026-05-22"},
            {"track": "Mugello", "duration_s": 88.0,
             "lap_id": 2, "session_date": "2025-12-31"},
        ])
        self.assertNotIn("2026-05-22", out)
        self.assertNotIn("2025-12-31", out)
        self.assertNotIn('class="bl-date"', out)

    def test_multiple_rows_rendered_in_input_order(self):
        # Helper soll die Reihenfolge der Eingabe respektieren — das
        # Sortieren passiert in der DB-Methode, nicht hier.
        rows = [
            {"track": "Mugello", "duration_s": 88.0, "lap_id": 1,
             "session_date": ""},
            {"track": "Aragon", "duration_s": 91.0, "lap_id": 2,
             "session_date": ""},
            {"track": "Hockenheim", "duration_s": 100.0, "lap_id": 3,
             "session_date": ""},
        ]
        out = webserver.render_best_laps_html(rows)
        # Mugello kommt vor Aragon kommt vor Hockenheim
        i_m = out.find("Mugello")
        i_a = out.find("Aragon")
        i_h = out.find("Hockenheim")
        self.assertGreater(i_m, 0)
        self.assertGreater(i_a, i_m)
        self.assertGreater(i_h, i_a)


# ---------------------------------------------------------------------------
# (7) v23.2 — Globale Top-N pro Strecke (DB-Method)
# ---------------------------------------------------------------------------

class TestGlobalTopNPerTrack(unittest.TestCase):
    """Direkte DB-Tests für db.global_top_n_per_track()."""

    def setUp(self):
        import numpy as np
        self.tmp = tempfile.mkdtemp(prefix="rd-top-")
        self.db = dbmod.DB(Path(self.tmp) / "x.db")
        self.u1 = self.db.create_user(email="a@x.de", password="secret123")
        self.u2 = self.db.create_user(email="b@x.de", password="secret123")
        self.u3 = self.db.create_user(email="c@x.de", password="secret123")
        self._np = np

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ld(self, dur):
        return {
            "time": self._np.array([0.0, dur]),
            "speed": self._np.array([100.0, 100.0]),
            "distance": self._np.array([0.0, 30.0]),
            "lat": self._np.array([0.0]),
            "lon": self._np.array([0.0]),
            "lap_index": 1, "duration": dur,
        }

    def _add(self, user_id, track, dur, sleep=0.005):
        import time as _t
        sid = self.db.create_session(
            original_filename="x", file_path="/tmp/x",
            user_id=user_id, driver="X", bike="", track=track,
            session_date="2026-01-01", notes="", format="ses",
        )
        lap_id = self.db.add_lap(sid, 1, dur, self._ld(dur))
        _t.sleep(sleep)
        return lap_id

    def test_no_laps_returns_empty(self):
        self.assertEqual(self.db.global_top_n_per_track(3), [])

    def test_single_track_single_lap_returns_top1(self):
        lap_id = self._add(self.u1, "Aragon", 92.5)
        result = self.db.global_top_n_per_track(3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["track"], "Aragon")
        self.assertEqual(len(result[0]["entries"]), 1)
        self.assertEqual(result[0]["entries"][0]["rank"], 1)
        self.assertEqual(result[0]["entries"][0]["lap_id"], lap_id)

    def test_aggregates_across_users(self):
        # Drei User, eine Strecke — Top-3 sind die schnellsten 3 Laps
        # über alle User.
        self._add(self.u1, "Aragon", 92.0)
        self._add(self.u2, "Aragon", 90.5)  # Top 1
        self._add(self.u3, "Aragon", 91.0)  # Top 2
        result = self.db.global_top_n_per_track(3)
        self.assertEqual(len(result), 1)
        entries = result[0]["entries"]
        self.assertEqual(len(entries), 3)
        # Sortierung: schnellste zuerst
        self.assertAlmostEqual(entries[0]["duration_s"], 90.5)
        self.assertAlmostEqual(entries[1]["duration_s"], 91.0)
        self.assertAlmostEqual(entries[2]["duration_s"], 92.0)
        # Ranks korrekt zugewiesen
        self.assertEqual(entries[0]["rank"], 1)
        self.assertEqual(entries[1]["rank"], 2)
        self.assertEqual(entries[2]["rank"], 3)

    def test_one_user_can_hold_multiple_top_slots(self):
        # v23.10-Spec (Stefan): ein Fahrer erscheint pro Strecke nur EINMAL,
        # mit seiner Bestzeit — auch wenn er die 3 schnellsten Runden hält.
        self._add(self.u1, "Aragon", 92.0)
        self._add(self.u1, "Aragon", 91.5)
        self._add(self.u1, "Aragon", 91.0)
        self._add(self.u2, "Aragon", 95.0)
        result = self.db.global_top_n_per_track(3)
        entries = result[0]["entries"]
        # u1 nur 1× (Bestzeit 91.0), dahinter u2
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["user_id"], self.u1)
        self.assertEqual(entries[0]["duration_s"], 91.0)
        self.assertEqual(entries[1]["user_id"], self.u2)

    def test_excludes_empty_track(self):
        self._add(self.u1, "Aragon", 92.0)
        self._add(self.u1, "", 70.0)  # would beat anything, but no track
        result = self.db.global_top_n_per_track(3)
        # Nur Aragon im Output
        names = [r["track"] for r in result]
        self.assertEqual(names, ["Aragon"])

    def test_case_insensitive_track_grouping(self):
        # 'Aragon' / 'aragon' / 'ARAGON' sollten in einem Bucket landen
        self._add(self.u1, "Aragon", 92.0)
        self._add(self.u2, "aragon", 90.5)
        self._add(self.u3, "ARAGON", 91.0)
        result = self.db.global_top_n_per_track(3)
        self.assertEqual(len(result), 1)
        # Canonical Spelling = first-seen
        self.assertEqual(result[0]["track"], "Aragon")
        self.assertEqual(len(result[0]["entries"]), 3)

    def test_tracks_sorted_alphabetically(self):
        self._add(self.u1, "Mugello", 88.0)
        self._add(self.u1, "Aragon", 92.0)
        self._add(self.u1, "Hockenheim", 105.0)
        result = self.db.global_top_n_per_track(3)
        names = [r["track"] for r in result]
        # Alphabetisch, nicht nach Speed sortiert. Stabilität > Speed-
        # Ranking auf der äusseren Liste.
        self.assertEqual(names, ["Aragon", "Hockenheim", "Mugello"])

    def test_n_limits_entries_per_track(self):
        # v23.10: Dedupe pro Fahrer — für den n-Limit-Test braucht es
        # deshalb 5 VERSCHIEDENE Fahrer (sonst kollabiert alles auf 1).
        uids = [self.db.create_user(email=f"nlimit{i}@x.de",
                                    password="geheim1")
                for i in range(5)]
        for uid, dur in zip(uids, [95.0, 94.0, 93.0, 92.0, 91.0]):
            self._add(uid, "Aragon", dur)
        # Top-1
        r1 = self.db.global_top_n_per_track(1)
        self.assertEqual(len(r1[0]["entries"]), 1)
        self.assertAlmostEqual(r1[0]["entries"][0]["duration_s"], 91.0)
        # Top-3
        r3 = self.db.global_top_n_per_track(3)
        self.assertEqual(len(r3[0]["entries"]), 3)
        # Top-99 → alle 5 Fahrer
        r99 = self.db.global_top_n_per_track(99)
        self.assertEqual(len(r99[0]["entries"]), 5)

    def test_invalid_n_returns_empty(self):
        self._add(self.u1, "Aragon", 92.0)
        self.assertEqual(self.db.global_top_n_per_track(0), [])
        self.assertEqual(self.db.global_top_n_per_track(-1), [])

    def test_ex_aequo_deterministic(self):
        # Zwei Laps mit identischer Zeit — ältere lap_id gewinnt (ORDER BY
        # laps.id ASC).
        lap1 = self._add(self.u1, "Aragon", 92.0)
        lap2 = self._add(self.u2, "Aragon", 92.0)
        result = self.db.global_top_n_per_track(3)
        entries = result[0]["entries"]
        self.assertEqual(entries[0]["lap_id"], lap1)
        self.assertEqual(entries[1]["lap_id"], lap2)

    def test_includes_owner_email_and_driver_name(self):
        self.db.upsert_profile(self.u1, driver_name="Stefan")
        self._add(self.u1, "Aragon", 92.0)
        result = self.db.global_top_n_per_track(3)
        e = result[0]["entries"][0]
        self.assertEqual(e["owner_email"], "a@x.de")
        # driver_name kommt aus session.driver (was beim Upload gesetzt
        # wird), nicht aus profiles.driver_name — die Helper-Methode
        # joint sessions, nicht profiles. Wir asserten nur dass das
        # Feld da ist, nicht den exakten Wert.
        self.assertIn("driver_name", e)


# ---------------------------------------------------------------------------
# (8) v23.2 — Medal-Helper (pure functions)
# ---------------------------------------------------------------------------

class TestMedalHelpers(unittest.TestCase):
    def test_render_medal_html_none_returns_empty(self):
        self.assertEqual(webserver.render_medal_html(None), "")

    def test_render_medal_html_gold(self):
        out = webserver.render_medal_html(1)
        self.assertIn("<svg", out)
        self.assertIn("medal-gold", out)
        # Gold-Farbe (#FFD700) sollte im SVG sein
        self.assertIn("#FFD700", out)

    def test_render_medal_html_silver(self):
        out = webserver.render_medal_html(2)
        self.assertIn("medal-silver", out)
        self.assertIn("#C0C0C0", out)

    def test_render_medal_html_bronze(self):
        out = webserver.render_medal_html(3)
        self.assertIn("medal-bronze", out)
        self.assertIn("#CD7F32", out)

    def test_render_medal_html_out_of_range(self):
        self.assertEqual(webserver.render_medal_html(0), "")
        self.assertEqual(webserver.render_medal_html(4), "")
        self.assertEqual(webserver.render_medal_html(99), "")

    def test_medal_map_from_top_n_empty(self):
        self.assertEqual(webserver.medal_map_from_top_n([]), {})
        self.assertEqual(webserver.medal_map_from_top_n(None), {})

    def test_medal_map_from_top_n_basic(self):
        top_n = [{
            "track": "Aragon",
            "entries": [
                {"rank": 1, "lap_id": 10, "duration_s": 90.0,
                 "user_id": 1, "owner_email": "a@x", "driver_name": "A"},
                {"rank": 2, "lap_id": 20, "duration_s": 91.0,
                 "user_id": 2, "owner_email": "b@x", "driver_name": "B"},
                {"rank": 3, "lap_id": 30, "duration_s": 92.0,
                 "user_id": 3, "owner_email": "c@x", "driver_name": "C"},
            ],
        }]
        m = webserver.medal_map_from_top_n(top_n)
        self.assertEqual(m, {10: 1, 20: 2, 30: 3})

    def test_medal_map_from_top_n_multiple_tracks(self):
        top_n = [
            {"track": "Aragon", "entries": [
                {"rank": 1, "lap_id": 10, "duration_s": 90.0,
                 "user_id": 1, "owner_email": "", "driver_name": ""}]},
            {"track": "Mugello", "entries": [
                {"rank": 1, "lap_id": 20, "duration_s": 88.0,
                 "user_id": 2, "owner_email": "", "driver_name": ""},
                {"rank": 2, "lap_id": 30, "duration_s": 89.0,
                 "user_id": 3, "owner_email": "", "driver_name": ""}]},
        ]
        m = webserver.medal_map_from_top_n(top_n)
        self.assertEqual(m, {10: 1, 20: 1, 30: 2})

    def test_medal_map_skips_invalid_entries(self):
        # Entries mit ungültigem rank oder lap_id=0 werden ausgefiltert
        top_n = [{
            "track": "Aragon",
            "entries": [
                {"rank": 0, "lap_id": 10, "duration_s": 90.0,
                 "user_id": 1, "owner_email": "", "driver_name": ""},
                {"rank": 1, "lap_id": 0, "duration_s": 90.0,
                 "user_id": 1, "owner_email": "", "driver_name": ""},
                {"rank": 1, "lap_id": 99, "duration_s": 90.0,
                 "user_id": 1, "owner_email": "", "driver_name": ""},
            ],
        }]
        m = webserver.medal_map_from_top_n(top_n)
        self.assertEqual(m, {99: 1})


# ---------------------------------------------------------------------------
# (9) v23.2 — render_best_laps_html mit Medals
# ---------------------------------------------------------------------------

class TestRenderBestLapsWithMedals(unittest.TestCase):
    def test_medals_appear_when_lap_in_top3(self):
        rows = [{"track": "Aragon", "duration_s": 91.5,
                 "lap_id": 42, "session_date": ""}]
        out = webserver.render_best_laps_html(rows, medals={42: 1})
        self.assertIn("medal-gold", out)

    def test_no_medal_when_lap_not_in_map(self):
        rows = [{"track": "Aragon", "duration_s": 91.5,
                 "lap_id": 42, "session_date": ""}]
        out = webserver.render_best_laps_html(rows, medals={99: 1})
        self.assertNotIn("medal-gold", out)
        self.assertNotIn("medal-silver", out)
        self.assertNotIn("medal-bronze", out)
        # Aber: die .bl-medal Spalte ist immer noch da (leer), damit
        # das CSS-Grid alignment hält.
        self.assertIn('class="bl-medal"', out)

    def test_medals_none_renders_without_medals(self):
        rows = [{"track": "Aragon", "duration_s": 91.5,
                 "lap_id": 42, "session_date": ""}]
        out = webserver.render_best_laps_html(rows, medals=None)
        self.assertIn('class="bl-medal"', out)  # column still present
        self.assertNotIn("medal-gold", out)


if __name__ == "__main__":
    unittest.main()
