"""Tests für den I2M-Parser — self-describing Dialekt (v23.17).

Synthetische Fixtures im neuen $CANALI/$SETTAGGICANALI/$VAL-Format
(beobachtet auf Ducati-V4-Loggern) plus Regression für den Legacy-
$VALUE-Dialekt.

Run: python3 -m pytest tests/test_i2m_v2_parser.py -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from parsers.i2m_parser import parse_i2m


def _gps_lines(n=20, ts0=1000000):
    """n GPS-Records, 10 Hz, leicht wandernde Position."""
    out = []
    for i in range(n):
        ts = ts0 + i * 10
        lat = f"{4919.7550 + i * 0.001:.4f}"
        lon = f"{833.8982 + i * 0.001:09.4f}"
        utc = f"{80908.300 + i * 0.1:010.3f}"
        out.append(f"$GPS,{ts},A,{lat},N,0{lon},E,31.14,{utc},92.10,")
    return out


def _write(lines, suffix=".dat"):
    path = tempfile.mktemp(suffix=suffix)
    with open(path, "w", encoding="latin-1", newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _v2_file():
    lines = [
        "$TIPO,0,",
        "$BEST,1:30.616,",          # Prelude VOR $NEW SESSION
        "$DIST,27.59",
        "$NEW SESSION",
        "$PILOTA,V4SG,",
        "$SETTAGGICANALI,1;Rpm;0.0;1023.0,5;FrontSusp;-11.7302;138.27,"
        "8;LAMBDA INT.;8.0;22.0,67;Atm. pressure;15.0;424.2,",
        "$CANALI,10,1,5,8,",
        "$CANALI,100,67,",
        "$DATE,260926",
    ]
    lines += _gps_lines()
    # 10-Hz-Stream: Rpm (dummy-cal → raw), FrontSusp (kalibriert),
    # LAMBDA (kalibriert); ein Sentinel in FrontSusp.
    for i in range(20):
        ts = 1000000 + i * 10
        susp = 65535 if i == 3 else (100 + i * 10)
        lines.append(f"$VAL,10,{ts}.000,{3000 + i * 100}.000,{susp}.000,"
                     f"{300 + i}.000,")
    # 100-Hz-Stream: Atm. pressure, variierend
    for i in range(200):
        ts = 1000000 + i
        lines.append(f"$VAL,100,{ts}.000,{215 + (i % 3)}.000,")
    # Kaputte Zeile (zu wenig Spalten) — muss überlebt werden
    lines.append("$VAL,10,1000210.000,1.000,")
    return _write(lines)


class TestI2MV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.track = parse_i2m(_v2_file())

    def test_meta(self):
        m = self.track["meta"]
        self.assertEqual(m["PILOTA"], "V4SG")
        self.assertEqual(m["VEHICLE"], "V4SG")
        self.assertEqual(m["BEST_LAP_HINT"], "1:30.616")   # aus dem Prelude
        self.assertEqual(m["DATE"], "260926")

    def test_channels_built(self):
        ch = self.track["channels"]
        self.assertIn("Rpm", ch)
        self.assertIn("FrontSusp", ch)
        self.assertIn("LAMBDA INT.", ch)
        self.assertIn("Atm. pressure", ch)

    def test_rates(self):
        ch = self.track["channels"]
        self.assertEqual(ch["Rpm"]["rate"], 10)
        self.assertEqual(ch["Atm. pressure"]["rate"], 100)

    def test_dummy_cal_stays_raw(self):
        ch = self.track["channels"]["Rpm"]
        self.assertEqual(ch["unit"], "raw")
        self.assertAlmostEqual(float(ch["data"][0]), 3000.0)

    def test_calibration_applied(self):
        ch = self.track["channels"]["FrontSusp"]
        self.assertEqual(ch["unit"], "mm")
        # raw 100 → -11.7302 + 100/1023*150.0002 ≈ 2.93 mm
        self.assertAlmostEqual(float(ch["data"][0]), 2.933, places=2)
        lam = self.track["channels"]["LAMBDA INT."]
        self.assertEqual(lam["unit"], "AFR")
        # raw 300 → 8 + 300/1023*14 ≈ 12.11
        self.assertAlmostEqual(float(lam["data"][0]), 12.105, places=2)

    def test_sentinel_masked(self):
        ch = self.track["channels"]["FrontSusp"]
        self.assertTrue(np.isnan(ch["data"][3]))

    def test_gps(self):
        self.assertEqual(len(self.track["time"]), 20)
        self.assertAlmostEqual(float(self.track["speed"][0]),
                               31.14 * 1.852, places=2)
        self.assertAlmostEqual(float(self.track["lat"][0]),
                               49 + 19.7550 / 60, places=5)

    def test_malformed_val_line_survived(self):
        # Die kaputte Zeile (1 Wert statt 3) wird verworfen, nicht gecrasht
        self.assertEqual(len(self.track["channels"]["Rpm"]["data"]), 20)


class TestLegacyRegression(unittest.TestCase):
    def test_legacy_value_dialect_still_parses(self):
        lines = ["$NEW SESSION", "$DATE,010126,"]
        lines += _gps_lines()
        for i in range(20):
            ts = 1000000 + i * 5
            cols = ",".join(str(400 + i * j) for j in range(14))
            lines.append(f"$VALUE,{ts},{cols},{i}")
        t = parse_i2m(_write(lines))
        self.assertEqual(len(t["time"]), 20)
        self.assertEqual(t["meta"]["DATE"], "010126")
        # Legacy-Kanäle da (TPS variiert → überlebt den Konstant-Filter)
        self.assertIn("channels", t)
        self.assertGreater(len(t["channels"]), 0)


class TestFractionalGpsTimestamp(unittest.TestCase):
    """Barcelona-Datei: $GPS-ts ist Dezimalzahl (34811458.4)."""

    def test_fractional_ts(self):
        lines = ["$NEW SESSION", "$DATE,081026,"]
        for i in range(20):
            lat = f"{4134.1281 + i * 0.0005:.4f}"
            utc = f"{144241.300 + i * 0.1:010.3f}"
            lines.append(f"$GPS,{34811458.4 + i * 10:.1f},A,{lat},N,"
                         f"00215.6409,E,17.87,{utc},129.70")
        t = parse_i2m(_write(lines))
        self.assertEqual(len(t["time"]), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
