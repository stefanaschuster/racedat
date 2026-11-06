"""nativeAI-Anbindung (app.py), Brevo-Mailer und Migrationsskript."""
import importlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE.parent
sys.path.insert(0, str(CODE))

try:
    import fastapi  # noqa: F401
    from fastapi.testclient import TestClient
    HAVE_APP = True
except Exception:  # fastapi/httpx nicht installiert
    HAVE_APP = False


@unittest.skipUnless(HAVE_APP, "fastapi/httpx fehlt")
class TestApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["APP_DATA"] = cls.tmp.name
        import app as appmod
        importlib.reload(appmod)
        cls.client_cm = TestClient(appmod.app)
        cls.c = cls.client_cm.__enter__()
        from db import DB
        import webserver
        webserver.AppState.db.create_user(
            email="t@example.com", password="secret123pw")

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        cls.tmp.cleanup()

    def test_health_and_root(self):
        self.assertEqual(self.c.get("/health").json()["ok"], True)
        self.assertEqual(self.c.get("/").status_code, 200)

    def test_static(self):
        r = self.c.get("/static/speed_chart.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers["content-type"])

    def test_legal_data_prefers_data_dir(self):
        r = self.c.get("/static/legal_data.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("LEGAL_DATA", r.text)
        (Path(self.tmp.name) / "legal_data.js").write_text("const LEGAL_DATA={x:'ueberschrieben'};")
        try:
            r = self.c.get("/static/legal_data.js")
            self.assertIn("ueberschrieben", r.text)
        finally:
            (Path(self.tmp.name) / "legal_data.js").unlink()

    def test_legal_pages_version_the_script_url(self):
        import re
        for page in ("/impressum", "/datenschutz"):
            r = self.c.get(page)
            self.assertRegex(r.text, r'src="/static/legal_data\.js\?v=\d+"')
        self.assertEqual(self.c.get("/static/legal_data.js").headers["cache-control"], "no-cache")

    def test_login_sets_cookie(self):
        r = self.c.post("/login", data={"email": "t@example.com",
                                        "password": "secret123pw"},
                        follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("lapcomp_auth", r.headers.get("set-cookie", ""))

    def test_oversize_rejected(self):
        r = self.c.post("/api/adhoc/laps",
                        files={"file": ("x.dat", b"x" * (53 * 1024 * 1024))})
        self.assertEqual(r.status_code, 413)


class TestMailer(unittest.TestCase):
    def test_config_requires_api_key(self):
        import mailer
        with self.assertRaises(mailer.MailerNotConfigured):
            mailer.smtp_config_from_app_config({})
        with self.assertRaises(mailer.MailerNotConfigured):
            mailer.smtp_config_from_app_config(
                {"smtp": {"sender_email": "a@b.de"}})
        self.assertEqual(mailer.smtp_config_from_app_config(
            {"smtp": {"api_key": "k", "sender_email": "a@b.de"}})["api_key"], "k")


class TestMigration(unittest.TestCase):
    def test_paths_remapped_and_nonempty_target_protected(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            old, new = t / "old", t / "new"
            (old / "originals" / "a").mkdir(parents=True)
            (old / "originals" / "a" / "f.dat").write_text("x")
            con = sqlite3.connect(old / "sessions.db")
            con.executescript(
                "CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT);"
                "CREATE TABLE sessions(id TEXT, file_path TEXT);"
                "CREATE TABLE events(id INTEGER, file_path TEXT);"
                "CREATE TABLE laps(id INTEGER);")
            con.execute("INSERT INTO users VALUES(1,'a@b.de')")
            con.execute("INSERT INTO sessions VALUES('s',?)",
                        (str(old / "originals/a/f.dat"),))
            con.execute("INSERT INTO sessions VALUES('s2','/elsewhere/originals/b/g.dat')")
            con.commit(); con.close()
            script = str(CODE / "migrate_data.py")
            r = subprocess.run([sys.executable, "-I", script, "--src", str(old),
                                "--dst", str(new)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            rows = dict(sqlite3.connect(new / "sessions.db").execute(
                "SELECT id,file_path FROM sessions").fetchall())
            self.assertEqual(rows["s"], str(new / "originals/a/f.dat"))
            self.assertEqual(rows["s2"], str(new / "originals/b/g.dat"))
            self.assertTrue((new / "originals/a/f.dat").is_file())
            r2 = subprocess.run([sys.executable, "-I", script, "--src", str(old),
                                 "--dst", str(new)], capture_output=True, text=True)
            self.assertEqual(r2.returncode, 2)

    def test_config_is_taken_over_into_env(self):
        import json
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            old, app = t / "old", t / "racedat"
            new = app / "data"
            old.mkdir(); app.mkdir()
            con = sqlite3.connect(old / "sessions.db")
            con.executescript(
                "CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT);"
                "CREATE TABLE sessions(id TEXT, file_path TEXT);"
                "CREATE TABLE events(id INTEGER, file_path TEXT);"
                "CREATE TABLE laps(id INTEGER);")
            con.commit(); con.close()
            (old / "config.json").write_text(json.dumps({
                "maptiler_key": "mt-key-123456", "base_url": "https://racedat.de",
                "smtp": {"password": "xkeysib-abcdef0123456789",
                         "sender_email": "no-reply@racedat.de",
                         "sender_name": "Racedat"},
                "foo": 1}))
            (app / ".env").write_text("MAIL_SENDER_NAME=Behalten\n")
            legacy = t / "legacy"
            (legacy / "webapp").mkdir(parents=True)
            (legacy / "webapp" / "legal_data.js").write_text('const LEGAL_DATA={name:"Max Muster"};')
            script = str(CODE / "migrate_data.py")
            r = subprocess.run([sys.executable, "-I", script, "--src", str(old),
                                "--dst", str(new), "--legacy-app", str(legacy)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            env = dict(l.split("=", 1) for l in (app / ".env").read_text().splitlines())
            self.assertEqual(env["MAPTILER_KEY"], "mt-key-123456")
            self.assertEqual(env["BREVO_API_KEY"], "xkeysib-abcdef0123456789")
            self.assertEqual(env["MAIL_SENDER_EMAIL"], "no-reply@racedat.de")
            self.assertEqual(env["MAIL_SENDER_NAME"], "Behalten")  # nicht überschrieben
            self.assertEqual(env["BASE_URL"],
                             "https://racedat.nativeai.digitalsandkasten.de")
            self.assertNotIn("xkeysib-abcdef0123456789", r.stdout)  # maskiert
            self.assertIn("foo", r.stdout)  # unbekannter Schlüssel gemeldet
            self.assertTrue(list(app.glob(".env.bak-*")))
            self.assertIn("Max Muster", (new / "legal_data.js").read_text())


if __name__ == "__main__":
    unittest.main()
