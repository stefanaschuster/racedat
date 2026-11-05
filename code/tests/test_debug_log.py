#!/usr/bin/env python3
"""tests/test_debug_log.py — Unit tests für debuglog.py (v22.1).

Deckt ab:
- enabled-Flag: log() ist no-op wenn aus
- logfmt-Formatierung: bare tokens, quoted strings, escaped chars
- None/leerer-String werden gefiltert
- Sonderzeichen in Keys werden sanitised
- Reihenfolge ts/lvl/ev/...
- bool/int/float Rendering
- Newlines werden escaped (one event = one line)
- fields_from_ctx() projiziert request_ctx → user/ip
"""
import io
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import debuglog


class TestDebugLog(unittest.TestCase):
    def setUp(self):
        self.buf = io.StringIO()
        debuglog.configure(enabled=True, stream=self.buf)

    def tearDown(self):
        debuglog.configure(enabled=False)

    def _lines(self):
        return [ln for ln in self.buf.getvalue().split("\n") if ln]

    # -- enable/disable -------------------------------------------------------

    def test_disabled_is_noop(self):
        debuglog.configure(enabled=False, stream=self.buf)
        debuglog.log("req", method="GET", path="/")
        self.assertEqual(self.buf.getvalue(), "")
        self.assertFalse(debuglog.is_enabled())

    def test_enabled(self):
        self.assertTrue(debuglog.is_enabled())
        debuglog.log("req")
        self.assertEqual(len(self._lines()), 1)

    # -- format basics --------------------------------------------------------

    def test_ts_lvl_ev_first(self):
        debuglog.log("req", method="GET")
        line = self._lines()[0]
        # ts comes first, then lvl, then ev, then fields
        self.assertTrue(line.startswith("ts="))
        # ev= must precede method=
        ev_pos = line.index("ev=req")
        method_pos = line.index("method=")
        self.assertLess(ev_pos, method_pos)
        # lvl is in between
        lvl_pos = line.index("lvl=")
        self.assertLess(lvl_pos, ev_pos)

    def test_ts_iso_format(self):
        debuglog.log("req")
        line = self._lines()[0]
        m = re.search(r"ts=(\S+)", line)
        self.assertIsNotNone(m)
        # 2026-05-19T13:01:22Z
        self.assertRegex(m.group(1), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_bare_token(self):
        debuglog.log("req", method="GET", path="/sessions")
        line = self._lines()[0]
        self.assertIn("method=GET", line)
        self.assertIn("path=/sessions", line)

    def test_quoting_space(self):
        debuglog.log("action", detail="lap deleted")
        line = self._lines()[0]
        self.assertIn('detail="lap deleted"', line)

    def test_quoting_equals(self):
        debuglog.log("req", detail="a=b")
        line = self._lines()[0]
        self.assertIn('detail="a=b"', line)

    def test_quoting_doublequote(self):
        debuglog.log("err", msg='he said "hi"')
        line = self._lines()[0]
        # inner quotes escaped, whole thing quoted
        self.assertIn('msg="he said \\"hi\\""', line)

    def test_quoting_backslash(self):
        debuglog.log("err", path=r"C:\foo")
        line = self._lines()[0]
        # Single backslash → escaped backslash. The path has no space so
        # it wouldn't need quoting, but the backslash escaping still applies.
        self.assertIn(r"path=C:\\foo", line)

    def test_newline_escaped(self):
        """Newlines must NEVER appear in output — one event = one line."""
        debuglog.log("err", trace="line1\nline2")
        out = self.buf.getvalue()
        # Exactly one line break (the final one from log() itself)
        self.assertEqual(out.count("\n"), 1)
        self.assertIn(r"trace=line1\nline2", out)

    def test_cr_escaped(self):
        debuglog.log("err", v="x\ry")
        out = self.buf.getvalue()
        self.assertIn(r"v=x\ry", out)
        self.assertEqual(out.count("\n"), 1)

    # -- value types ----------------------------------------------------------

    def test_int(self):
        debuglog.log("req", status=200, dur_ms=42)
        line = self._lines()[0]
        self.assertIn("status=200", line)
        self.assertIn("dur_ms=42", line)

    def test_float(self):
        debuglog.log("req", elapsed=1.5)
        line = self._lines()[0]
        self.assertIn("elapsed=1.5", line)

    def test_bool(self):
        debuglog.log("req", admin=True, anon=False)
        line = self._lines()[0]
        self.assertIn("admin=true", line)
        self.assertIn("anon=false", line)

    def test_none_dropped(self):
        debuglog.log("req", method="GET", user=None, path="/x")
        line = self._lines()[0]
        self.assertNotIn("user=", line)
        self.assertIn("method=GET", line)
        self.assertIn("path=/x", line)

    def test_empty_string_dropped(self):
        debuglog.log("req", method="GET", user="", path="/x")
        line = self._lines()[0]
        self.assertNotIn("user=", line)

    # -- key sanitisation -----------------------------------------------------

    def test_key_with_space_sanitised(self):
        # Caller shouldn't do this, but we don't want it breaking the format.
        debuglog.log("req", **{"weird key": "v"})
        line = self._lines()[0]
        self.assertIn("weird_key=v", line)

    def test_key_with_equals_sanitised(self):
        debuglog.log("req", **{"a=b": "v"})
        line = self._lines()[0]
        self.assertIn("a_b=v", line)

    # -- level ----------------------------------------------------------------

    def test_default_level(self):
        debuglog.log("req")
        self.assertIn("lvl=info", self._lines()[0])

    def test_explicit_level(self):
        debuglog.log("req", level="warn")
        self.assertIn("lvl=warn", self._lines()[0])

    # -- fields_from_ctx ------------------------------------------------------

    def test_ctx_to_fields_full(self):
        ctx = {"user_id": 1, "user_email": "a@b.c", "ip_address": "10.0.0.1"}
        self.assertEqual(
            debuglog.fields_from_ctx(ctx),
            {"user": "a@b.c", "ip": "10.0.0.1"},
        )

    def test_ctx_to_fields_anon(self):
        ctx = {"user_id": None, "user_email": "", "ip_address": "10.0.0.1"}
        # Empty user_email is dropped, only ip remains
        self.assertEqual(debuglog.fields_from_ctx(ctx), {"ip": "10.0.0.1"})

    def test_ctx_to_fields_none(self):
        self.assertEqual(debuglog.fields_from_ctx(None), {})
        self.assertEqual(debuglog.fields_from_ctx({}), {})

    # -- crash safety ---------------------------------------------------------

    def test_write_failure_does_not_raise(self):
        class BrokenStream:
            def write(self, _):
                raise IOError("pipe broken")
        debuglog.configure(enabled=True, stream=BrokenStream())
        # Should not raise
        debuglog.log("req", method="GET")

    # -- referer field (v22.11 — HTTP Referer in req logs) --------------------

    def test_req_with_referer(self):
        debuglog.log("req", method="GET", path="/sessions",
                     referer="https://example.com/page")
        line = self._lines()[0]
        # URL contains "://" → no whitespace/=/" → bare token, no quotes
        self.assertIn("referer=https://example.com/page", line)

    def test_req_without_referer_dropped(self):
        # None and "" must be filtered out — same convention as other fields,
        # so the log doesn't carry empty referer= noise on direct-nav requests.
        debuglog.log("req", method="GET", path="/sessions", referer=None)
        debuglog.log("req", method="GET", path="/sessions", referer="")
        for line in self._lines():
            self.assertNotIn("referer=", line)


if __name__ == "__main__":
    unittest.main()
