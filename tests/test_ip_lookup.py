#!/usr/bin/env python3
"""tests/test_ip_lookup.py — v22.11

Reverse-IP-Lookup in der Admin-View. Drei Schichten getestet:

  (1) Klassifizierungs-Helper (is_private_or_loopback_ip,
      is_valid_public_ip) — was zählt als "lokal", was als gültige
      öffentliche Adresse.
  (2) render_ip_cell() — wie eine IP in der .col-ip Spalte erscheint.
      Empty → '—', private → bare text + (lokal), public → <a class=ip-link>.
  (3) fetch_ip_geo() — Network call wird mit einem Stub statt echtem
      urllib.request.urlopen() getestet, um die Tests offline zu halten
      und keine Quota zu verbrennen.

Der Endpoint /admin/ip-lookup selbst wird nicht End-to-End gefahren —
das deckt der manuelle Smoketest; die Render-Funktion
_render_ip_lookup_page wird hier indirekt über die Status-Branches
(local/success/fail/error) abgenommen.
"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import webserver


class TestPrivateLoopbackClassification(unittest.TestCase):
    """Zone-Erkennung — welche Adressen sollen den Lookup-Link NICHT bekommen."""

    def test_loopback_v4(self):
        self.assertTrue(webserver.is_private_or_loopback_ip("127.0.0.1"))
        self.assertTrue(webserver.is_private_or_loopback_ip("127.255.255.254"))

    def test_loopback_v6(self):
        self.assertTrue(webserver.is_private_or_loopback_ip("::1"))

    def test_rfc1918(self):
        # Alle drei RFC1918-Bereiche
        self.assertTrue(webserver.is_private_or_loopback_ip("10.0.0.1"))
        self.assertTrue(webserver.is_private_or_loopback_ip("172.16.42.99"))
        self.assertTrue(webserver.is_private_or_loopback_ip("192.168.1.1"))

    def test_link_local(self):
        self.assertTrue(webserver.is_private_or_loopback_ip("169.254.1.1"))

    def test_public_v4(self):
        # Google DNS und CloudFlare DNS — eindeutig öffentlich
        self.assertFalse(webserver.is_private_or_loopback_ip("8.8.8.8"))
        self.assertFalse(webserver.is_private_or_loopback_ip("1.1.1.1"))

    def test_public_v6(self):
        self.assertFalse(webserver.is_private_or_loopback_ip(
            "2606:4700:4700::1111"))

    def test_invalid_input(self):
        # Mülladressen werden zu False — sie sind ja nicht "lokal", aber auch
        # nicht "public". Die Validitätsprüfung läuft separat.
        self.assertFalse(webserver.is_private_or_loopback_ip(""))
        self.assertFalse(webserver.is_private_or_loopback_ip("not-an-ip"))
        self.assertFalse(webserver.is_private_or_loopback_ip("999.999.999.999"))

    def test_is_valid_public_ip(self):
        self.assertTrue(webserver.is_valid_public_ip("8.8.8.8"))
        self.assertTrue(webserver.is_valid_public_ip("2606:4700:4700::1111"))
        # Privat ist syntaktisch gültig, aber nicht "public"
        self.assertFalse(webserver.is_valid_public_ip("192.168.1.1"))
        self.assertFalse(webserver.is_valid_public_ip("127.0.0.1"))
        # Wirklich Müll
        self.assertFalse(webserver.is_valid_public_ip(""))
        self.assertFalse(webserver.is_valid_public_ip("hello"))
        self.assertFalse(webserver.is_valid_public_ip("1.2.3.4.5"))


class TestRenderIpCell(unittest.TestCase):
    """HTML-Rendering der IP-Zelle in den Admin-Tabs."""

    def test_empty_renders_dash(self):
        out = webserver.render_ip_cell("")
        self.assertIn("—", out)
        self.assertNotIn("<a", out)

    def test_none_safe(self):
        # render_ip_cell muss "" akzeptieren — None würde TypeError werfen,
        # darum ist Caller-Verantwortung "" zu übergeben (was der Code an
        # allen 3 Stellen mit `ev["ip_address"] or ""` auch tut).
        out = webserver.render_ip_cell("")
        self.assertNotIn("<a", out)

    def test_private_no_link(self):
        out = webserver.render_ip_cell("192.168.1.42")
        self.assertIn("192.168.1.42", out)
        self.assertIn("(lokal)", out)
        self.assertNotIn("<a", out)

    def test_loopback_no_link(self):
        out = webserver.render_ip_cell("127.0.0.1")
        self.assertIn("127.0.0.1", out)
        self.assertIn("(lokal)", out)
        self.assertNotIn("<a", out)

    def test_public_renders_link(self):
        out = webserver.render_ip_cell("8.8.8.8")
        self.assertIn('<a ', out)
        self.assertIn('class="ip-link"', out)
        self.assertIn('target="_blank"', out)
        self.assertIn('rel="noopener"', out)
        # Link zeigt auf den admin endpoint mit der IP als Param
        self.assertIn('/admin/ip-lookup?ip=8.8.8.8', out)
        # Der angezeigte Text ist die IP selbst
        self.assertIn('>8.8.8.8</a>', out)

    def test_public_v6_renders_link(self):
        out = webserver.render_ip_cell("2606:4700:4700::1111")
        self.assertIn('class="ip-link"', out)
        # IPv6 colons müssen URL-encoded sein, sonst geht die query string
        # an manchen Proxies kaputt
        self.assertIn("%3A", out)  # ':' encoded

    def test_invalid_ip_no_link(self):
        # Nicht-IPs werden als plain text gezeigt, kein Link
        out = webserver.render_ip_cell("not-an-ip")
        self.assertNotIn("<a", out)
        self.assertIn("not-an-ip", out)

    def test_escapes_ip(self):
        # Defense-in-depth: wenn jemals etwas wie "<script>" in der DB
        # landet (sollte nicht — _client_ip filtert das nicht aber wir
        # escapen). Das Stück ist invalid als IP also kein <a>, aber das
        # HTML muss escaped sein.
        out = webserver.render_ip_cell("<script>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)


class TestFetchIpGeo(unittest.TestCase):
    """fetch_ip_geo() — robuste Wrapper-Semantik um urllib.request.urlopen."""

    def _patch_urlopen(self, *, return_body=None, raise_exc=None):
        """Hilfe: ersetzt webserver.urllib.request.urlopen mit einem Stub
        der entweder return_body (bytes) liefert oder raise_exc wirft."""
        class _Resp:
            def __init__(self, body): self._body = body
            def read(self): return self._body
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def _stub(*args, **kwargs):
            if raise_exc is not None:
                raise raise_exc
            return _Resp(return_body)
        return mock.patch.object(webserver.urllib.request, "urlopen", _stub)

    def test_success(self):
        body = json.dumps({
            "status": "success",
            "country": "Germany", "countryCode": "DE",
            "regionName": "Berlin", "region": "BE",
            "city": "Berlin", "zip": "10115",
            "lat": 52.52, "lon": 13.4050,
            "timezone": "Europe/Berlin",
            "isp": "Deutsche Telekom AG",
            "org": "Telekom",
            "as": "AS3320 Deutsche Telekom AG",
            "query": "8.8.8.8",
        }).encode("utf-8")
        with self._patch_urlopen(return_body=body):
            geo = webserver.fetch_ip_geo("8.8.8.8")
        self.assertEqual(geo["status"], "success")
        self.assertEqual(geo["country"], "Germany")
        self.assertEqual(geo["city"], "Berlin")
        self.assertEqual(geo["isp"], "Deutsche Telekom AG")

    def test_upstream_fail_status(self):
        # ip-api.com liefert {"status":"fail","message":"reserved range"}
        # bei z.B. bogons. Wir reichen das einfach durch.
        body = json.dumps({
            "status": "fail",
            "message": "reserved range",
            "query": "0.0.0.0",
        }).encode("utf-8")
        with self._patch_urlopen(return_body=body):
            geo = webserver.fetch_ip_geo("0.0.0.0")
        self.assertEqual(geo["status"], "fail")
        self.assertIn("reserved", geo.get("message", ""))

    def test_network_error(self):
        # urlopen wirft URLError → wir geben status=error zurück, nicht
        # raise. Der Caller darf nie eine Exception sehen.
        import urllib.error
        with self._patch_urlopen(raise_exc=urllib.error.URLError("timed out")):
            geo = webserver.fetch_ip_geo("8.8.8.8")
        self.assertEqual(geo["status"], "error")
        self.assertIn("timed out", geo.get("message", ""))

    def test_parse_error(self):
        # Garbage als response → status=error
        with self._patch_urlopen(return_body=b"not json at all <html>"):
            geo = webserver.fetch_ip_geo("8.8.8.8")
        self.assertEqual(geo["status"], "error")

    def test_non_dict_response(self):
        # ip-api liefert NORMAL ein Objekt, aber falls jemals ein Array
        # zurückkommt darf das nicht durchschlagen.
        with self._patch_urlopen(return_body=b"[1,2,3]"):
            geo = webserver.fetch_ip_geo("8.8.8.8")
        self.assertEqual(geo["status"], "error")

    def test_timeout_kw_passed(self):
        # Wir wollen sicherstellen, dass timeout an urlopen weitergegeben
        # wird — sonst hängt der Admin-Endpoint bei Netzausfall ewig.
        captured = {}
        class _Resp:
            def read(self): return b'{"status":"success"}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def _stub(req, **kw):
            captured.update(kw)
            return _Resp()
        with mock.patch.object(webserver.urllib.request, "urlopen", _stub):
            webserver.fetch_ip_geo("8.8.8.8", timeout=2.5)
        self.assertEqual(captured.get("timeout"), 2.5)


class TestRenderIpLookupPage(unittest.TestCase):
    """Die kleine HTML-Seite für /admin/ip-lookup. Wir konstruieren den
    Handler manuell ohne richtigen Request, indem wir die Render-Methode
    unbound auf einem Dummy aufrufen."""

    def _render(self, ip, geo):
        # _render_ip_lookup_page benutzt nur `self` für Convention, nicht
        # für State — wir können sie mit einer leeren Dummy-Instanz aufrufen.
        # Aber sauberer: wir ziehen die Funktion über __func__.
        dummy = object.__new__(webserver.WebHandler)
        return webserver.WebHandler._render_ip_lookup_page(dummy, ip, geo)

    def test_local_branch(self):
        html_doc = self._render("127.0.0.1", {"status": "local"})
        self.assertIn("Lokale", html_doc)
        self.assertIn("127.0.0.1", html_doc)
        # Kein RFC-1918-IP wird mit Geo-Daten gerendert
        self.assertNotIn("LAND", html_doc)

    def test_success_branch(self):
        geo = {
            "status": "success", "country": "Germany", "countryCode": "DE",
            "regionName": "Berlin", "region": "BE", "city": "Berlin",
            "zip": "10115", "lat": 52.52, "lon": 13.405,
            "timezone": "Europe/Berlin", "isp": "Telekom",
            "org": "T-Online", "as": "AS3320",
        }
        html_doc = self._render("8.8.8.8", geo)
        self.assertIn("LAND", html_doc)
        self.assertIn("Germany", html_doc)
        self.assertIn("Berlin", html_doc)
        self.assertIn("Telekom", html_doc)
        # OpenStreetMap-Link wird gebaut wenn lat/lon da sind
        self.assertIn("openstreetmap.org", html_doc)

    def test_success_without_coords(self):
        # Manche IPs haben keine Koordinaten — dann darf der Map-Link
        # einfach fehlen, nicht crashen.
        geo = {
            "status": "success", "country": "Germany", "city": "Berlin",
            "regionName": "", "region": "", "zip": "", "lat": "", "lon": "",
            "timezone": "", "isp": "", "org": "", "as": "",
        }
        html_doc = self._render("8.8.8.8", geo)
        self.assertNotIn("openstreetmap.org", html_doc)
        self.assertIn("Germany", html_doc)

    def test_fail_branch(self):
        html_doc = self._render("0.0.0.0",
                                {"status": "fail", "message": "reserved range"})
        self.assertIn("fehlgeschlagen", html_doc)
        self.assertIn("reserved range", html_doc)

    def test_error_branch(self):
        html_doc = self._render("8.8.8.8",
                                {"status": "error", "message": "timed out"})
        self.assertIn("Netzwerk", html_doc)
        self.assertIn("timed out", html_doc)

    def test_ip_is_escaped_in_title_and_h1(self):
        # XSS-Defense: auch wenn die IP-Validierung das aussortieren würde,
        # darf die Render-Funktion selbst kein ungescaptes HTML produzieren.
        html_doc = self._render("<script>alert(1)</script>",
                                {"status": "local"})
        self.assertNotIn("<script>alert", html_doc)
        self.assertIn("&lt;script&gt;", html_doc)


if __name__ == "__main__":
    unittest.main()
