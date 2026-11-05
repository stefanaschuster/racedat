"""Tests für den Starlane CSV Parser.

Validiert gegen die Beispieldatei LapTable.CSV (Oschersleben, Panigale V2)
und stellt sicher, dass die .csv-Format-Erkennung RaceBox und AIM NICHT
fehlklassifiziert (Backward-Compat für die bestehenden Importer).

Run: cd /home/claude/lap_tool && python3 -m pytest tests/test_starlane_csv_parser.py -v
oder: python3 tests/test_starlane_csv_parser.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from parsers import is_aim_csv, is_starlane_csv
from parsers.starlane_csv_parser import (
    parse_starlane_csv,
    is_starlane_csv as is_starlane_direct,
    _parse_laptime,
    _parse_starlane_date,
)
from laps import detect_laps, fastest_lap, extract_lap_data


SAMPLE = "/mnt/user-data/uploads/LapTable.CSV"


def _write_tmp(text: str, suffix=".csv") -> str:
    path = tempfile.mktemp(suffix=suffix)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


# ===========================================================================
# Pure Helpers
# ===========================================================================

class TestParseLaptime(unittest.TestCase):
    def test_mm_ss(self):
        self.assertAlmostEqual(_parse_laptime("01:36.00"), 96.0)
        self.assertAlmostEqual(_parse_laptime("02:09.55"), 129.55)
        self.assertAlmostEqual(_parse_laptime("00:18.03"), 18.03)

    def test_quoted(self):
        self.assertAlmostEqual(_parse_laptime('"01:35.24"'), 95.24)

    def test_single_digit_minute(self):
        self.assertAlmostEqual(_parse_laptime("1:36.00"), 96.0)

    def test_with_hours(self):
        self.assertAlmostEqual(_parse_laptime("1:02:03.5"), 3723.5)

    def test_empty_and_garbage(self):
        self.assertIsNone(_parse_laptime(""))
        self.assertIsNone(_parse_laptime("   "))
        self.assertIsNone(_parse_laptime("abc"))
        self.assertIsNone(_parse_laptime("230"))


class TestParseStarlaneDate(unittest.TestCase):
    def test_iso_passthrough(self):
        self.assertEqual(_parse_starlane_date("2023-07-18"), "2023-07-18")

    def test_eu_dotted(self):
        self.assertEqual(_parse_starlane_date("18.07.2023"), "2023-07-18")

    def test_eu_slashed(self):
        self.assertEqual(_parse_starlane_date("18/07/2023"), "2023-07-18")

    def test_empty(self):
        self.assertEqual(_parse_starlane_date(""), "")

    def test_unknown_kept(self):
        self.assertEqual(_parse_starlane_date("July 18 2023"), "July 18 2023")


# ===========================================================================
# Format-Erkennung — der kritische Backward-Compat-Teil
# ===========================================================================

class TestSniffIsolation(unittest.TestCase):
    """is_starlane_csv darf NUR Starlane erkennen, niemals RaceBox/AIM."""

    def test_detects_real_starlane(self):
        self.assertTrue(is_starlane_csv(SAMPLE))
        self.assertTrue(is_starlane_direct(SAMPLE))

    def test_aim_not_misdetected_as_starlane(self):
        am = _write_tmp('"Format","AiM CSV File"\r\n"Session","Jerez"\r\n')
        try:
            self.assertFalse(is_starlane_csv(am))
            self.assertTrue(is_aim_csv(am))  # AIM-Sniff bleibt intakt
        finally:
            os.remove(am)

    def test_racebox_not_misdetected_as_starlane(self):
        rb = _write_tmp(
            "Format, RaceBox Fastlap\r\nTrack, Mugello\r\n"
            "Time,Latitude,Longitude,Speed,Lap\r\n"
        )
        try:
            self.assertFalse(is_starlane_csv(rb))
        finally:
            os.remove(rb)

    def test_starlane_not_misdetected_as_aim(self):
        self.assertFalse(is_aim_csv(SAMPLE))

    def test_comma_file_rejected(self):
        # Eine Datei ganz ohne Semikolon ist nie Starlane.
        f = _write_tmp("a,b,c\r\n1,2,3\r\n")
        try:
            self.assertFalse(is_starlane_csv(f))
        finally:
            os.remove(f)

    def test_semicolon_but_wrong_header_rejected(self):
        f = _write_tmp("Foo;Bar;Baz\r\n1;2;3\r\n")
        try:
            self.assertFalse(is_starlane_csv(f))
        finally:
            os.remove(f)

    def test_missing_file_returns_false(self):
        self.assertFalse(is_starlane_csv("/no/such/file.csv"))


# ===========================================================================
# Voller Parse gegen die Beispieldatei
# ===========================================================================

class TestParseSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = parse_starlane_csv(SAMPLE)

    def test_source_format(self):
        self.assertEqual(self.t["source_format"], "STARLANE_CSV")

    def test_meta_session_fields(self):
        m = self.t["meta"]
        self.assertEqual(m["TRACK"], "Oschersleben")
        self.assertEqual(m["VENUE"], "Oschersleben")
        self.assertEqual(m["VEHICLE"], "Panigale V2")
        self.assertEqual(m["RACER"], "Uwe")
        self.assertEqual(m["EVENT"], "FR OSL")
        self.assertEqual(m["SESSION"], "RACE")
        self.assertEqual(m["RUN"], "4")
        self.assertEqual(m["DATE"], "2023-07-18")
        self.assertEqual(m["TIME_OF_DAY"], "16:25")
        self.assertEqual(m["SOURCE"], "STARLANE")

    def test_fastest_lap_excludes_in_lap(self):
        # Die 18s-In-Lap darf die Bestzeit nicht verfälschen; schnellste
        # plausible Runde ist 01:35.24 = 95.24s.
        self.assertEqual(self.t["meta"]["FASTEST_LAP"], "1:35.240")

    def test_lap_times_count(self):
        # 15 Zeilen mit gültiger Zeit (Lap 0..14).
        self.assertEqual(len(self.t["lap_times"]), 15)

    def test_lap_times_cumulative_start(self):
        lt = self.t["lap_times"]
        self.assertAlmostEqual(lt[0][0], 0.0)
        self.assertAlmostEqual(lt[0][1], 129.55)
        self.assertAlmostEqual(lt[1][0], 129.55)   # start = sum of prior
        self.assertAlmostEqual(lt[1][1], 96.0)

    def test_empty_gps_arrays(self):
        # Starlane hat keine GPS-Spur — Arrays sind leer, aber vorhanden.
        for k in ("time", "lat", "lon", "speed"):
            self.assertIsInstance(self.t[k], np.ndarray)
            self.assertEqual(self.t[k].size, 0)

    def test_lap_summaries(self):
        s = self.t["lap_summaries"]
        self.assertEqual(len(s), 15)
        lap1 = s[1]
        self.assertEqual(lap1["lap_index"], 1)
        self.assertAlmostEqual(lap1["duration_s"], 96.0)
        self.assertEqual(lap1["splits"], [22.26, 31.72, 14.30, 27.72])
        self.assertAlmostEqual(lap1["max_speed"], 230.0)

    def test_finish_line_none(self):
        self.assertIsNone(self.t["finish_line"])


# ===========================================================================
# Downstream-Integration: detect_laps / extract_lap_data
# ===========================================================================

class TestDownstreamIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = parse_starlane_csv(SAMPLE)

    def test_detect_laps_uses_lap_times(self):
        laps = detect_laps(self.t)
        # 30<dur<600-Filter wirft die 18s-In-Lap raus → 14 Runden.
        self.assertEqual(len(laps), 14)
        self.assertTrue(all(lp["method"] == "running_lap_time" for lp in laps))

    def test_fastest_detected(self):
        laps = detect_laps(self.t)
        fl = fastest_lap(laps)
        self.assertAlmostEqual(fl["duration"], 95.24, places=2)

    def test_extract_lap_data_no_crash_on_empty_gps(self):
        laps = detect_laps(self.t)
        fl = fastest_lap(laps)
        ld = extract_lap_data(self.t, fl)
        # Keine Samples, aber strukturell valide Rückgabe.
        self.assertIn("time", ld)
        self.assertIn("duration", ld)
        self.assertEqual(len(ld["time"]), 0)

    def test_single_lap_payload_no_crash_on_empty_gps(self):
        # /analyze?lap_id=N → compute_single_lap_payload. Darf bei GPS-loser
        # Starlane-Runde NICHT mit IndexError crashen, sondern einen validen
        # Payload mit leeren Arrays + gefülltem Header liefern.
        from report_single import compute_single_lap_payload
        laps = detect_laps(self.t)
        fl = fastest_lap(laps)
        ld = extract_lap_data(self.t, fl)
        p = compute_single_lap_payload(track=self.t, lap_meta=fl, lap_data=ld)
        self.assertEqual(len(p["speed"]), 0)
        self.assertEqual(len(p["distance"]), 0)
        self.assertEqual(p["header"]["driver"], "Uwe")
        self.assertEqual(p["header"]["bike"], "Panigale V2")
        self.assertEqual(p["header"]["track"], "Oschersleben")
        self.assertEqual(p["header"]["lap_time"], "1:35.240")
        # Analysis ist leer aber strukturell vollständig.
        self.assertEqual(p["analysis"]["braking_zones"], [])
        self.assertIn("headline", p["analysis"]["assessment"])


# ===========================================================================
# Fehlerfälle
# ===========================================================================

class TestErrorCases(unittest.TestCase):
    def test_missing_session_header(self):
        f = _write_tmp("Lap;Lap Time;\r\n1;01:30.00;\r\n")
        try:
            with self.assertRaises(ValueError):
                parse_starlane_csv(f)
        finally:
            os.remove(f)

    def test_missing_lap_header(self):
        f = _write_tmp(
            "Event;Session;Run;Driver;Vehicle;Date;Time;Track;\r\n"
            "X;RACE;1;A;B;2023-01-01;12:00;Track;\r\n"
        )
        try:
            with self.assertRaises(ValueError):
                parse_starlane_csv(f)
        finally:
            os.remove(f)

    def test_no_valid_laps(self):
        f = _write_tmp(
            "Event;Session;Run;Driver;Vehicle;Date;Time;Track;\r\n"
            "X;RACE;1;A;B;2023-01-01;12:00;Track;\r\n"
            "\r\n"
            "Lap;Lap Time;\r\n"
            "0;abc;\r\n"
        )
        try:
            with self.assertRaises(ValueError):
                parse_starlane_csv(f)
        finally:
            os.remove(f)


if __name__ == "__main__":
    unittest.main(verbosity=2)
