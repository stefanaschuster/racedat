"""Tests für den AIM CSV Parser (v23.6).

Validiert gegen die beiden Beispieldateien:
  • Jerez 2025-12-31 (RSV4 — voller Channel-Satz inkl. RPM/GEAR/ENG TEMP/THRT HAND)
  • Aragon 2026-03-23 (nur GPS-Block, keine Bike-Kanäle)

Run: cd /home/claude/lap_tool && python3 -m pytest tests/test_aim_csv_parser.py -v
"""
import io
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from parsers.aim_csv_parser import (
    parse_aim_csv,
    is_aim_csv,
    _parse_aim_date,
    MIN_LAP_DURATION_S,
)


SAMPLE_JEREZ = "/mnt/user-data/uploads/jerez.csv"
SAMPLE_ARAGON = "/mnt/user-data/uploads/aragon.csv"


# ===========================================================================
# Unit-Tests: pure Helpers (kein File-I/O)
# ===========================================================================

class TestParseAimDate(unittest.TestCase):
    """_parse_aim_date soll robust sein und bei Failure '' zurückgeben."""

    def test_standard_format(self):
        self.assertEqual(
            _parse_aim_date("Wednesday, December 31, 2025"),
            "2025-12-31",
        )

    def test_other_months(self):
        self.assertEqual(_parse_aim_date("Monday, March 23, 2026"), "2026-03-23")
        self.assertEqual(_parse_aim_date("Friday, January 1, 2027"), "2027-01-01")
        self.assertEqual(_parse_aim_date("Sunday, August 15, 2024"), "2024-08-15")

    def test_case_insensitive_month(self):
        # Robustheit: Monatsname case-insensitive (in Praxis immer Title-Case
        # bei AIM, aber wir wollen nicht bei "december" crashen).
        self.assertEqual(
            _parse_aim_date("Wednesday, DECEMBER 31, 2025"),
            "2025-12-31",
        )

    def test_empty_string(self):
        self.assertEqual(_parse_aim_date(""), "")

    def test_garbled_input(self):
        self.assertEqual(_parse_aim_date("not a date"), "")
        self.assertEqual(_parse_aim_date("31/12/2025"), "")

    def test_invalid_month_name(self):
        # "Smarch" gibt's nicht — kein Crash, leerer String zurück.
        self.assertEqual(_parse_aim_date("Monday, Smarch 1, 2025"), "")


class TestIsAimCsvSniffer(unittest.TestCase):
    """is_aim_csv soll Format-Diskriminierung sauber durchführen."""

    def _write(self, content: str) -> str:
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        self.addCleanup(os.unlink, path)
        return path

    def test_aim_quoted_header(self):
        p = self._write('"Format","AiM CSV File"\r\n"Session","Test"\r\n')
        self.assertTrue(is_aim_csv(p))

    def test_aim_unquoted_header(self):
        # Defensiv: manche AIM-Exporte könnten unquoted sein.
        p = self._write("Format,AiM CSV File\r\nSession,Test\r\n")
        self.assertTrue(is_aim_csv(p))

    def test_racebox_header_is_not_aim(self):
        # Echtes RaceBox-Format darf NICHT als AIM erkannt werden.
        p = self._write("Format, RaceBox Mini\r\nTrack, Mugello\r\n")
        self.assertFalse(is_aim_csv(p))

    def test_empty_file(self):
        p = self._write("")
        self.assertFalse(is_aim_csv(p))

    def test_skips_leading_blanks(self):
        p = self._write('\r\n\r\n"Format","AiM CSV File"\r\n')
        self.assertTrue(is_aim_csv(p))

    def test_nonexistent_file_returns_false(self):
        # Kein Crash bei nicht-existenter Datei.
        self.assertFalse(is_aim_csv("/nonexistent/path/foo.csv"))


# ===========================================================================
# Integration-Tests: parse_aim_csv mit den Beispieldateien
# ===========================================================================

class TestJerezSample(unittest.TestCase):
    """Jerez: voller Channel-Satz inkl. RSV4-Bike-Kanäle."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(SAMPLE_JEREZ):
            raise unittest.SkipTest(f"Sample fehlt: {SAMPLE_JEREZ}")
        cls.track = parse_aim_csv(SAMPLE_JEREZ)

    def test_meta_basics(self):
        m = self.track["meta"]
        self.assertEqual(m["SOURCE"], "AIM")
        self.assertEqual(m["LOGGER"], "AIM")
        self.assertEqual(m["VENUE"], "Jerez")
        self.assertEqual(m["TRACK"], "Jerez")
        self.assertEqual(m["VEHICLE"], "RJ27")
        self.assertEqual(m["RACER"], "Andrea")
        self.assertEqual(m["DATE"], "2025-12-31")
        self.assertEqual(m["TIME_OF_DAY"], "11:45 AM")
        self.assertEqual(m["SAMPLE_RATE_HZ"], 20)
        self.assertEqual(m["FASTEST_LAP"], "1:46.405")

    def test_source_format(self):
        self.assertEqual(self.track["source_format"], "AIM_CSV")

    def test_time_axis_20Hz(self):
        # 20 Hz = 50 ms Intervall, Duration ≈ 14062 s → ~281240 samples
        t = self.track["time"]
        self.assertGreater(len(t), 280_000)
        self.assertLess(len(t), 282_000)
        dt = np.median(np.diff(t))
        self.assertAlmostEqual(dt, 0.05, places=4)
        self.assertEqual(t[0], 0.0)

    def test_gps_at_jerez(self):
        # Jerez: ca. 36.708° N, -6.034° E
        lat = self.track["lat"]
        lon = self.track["lon"]
        self.assertAlmostEqual(np.median(lat), 36.71, places=1)
        self.assertAlmostEqual(np.median(lon), -6.03, places=1)
        # Strecke passt in <5 km Bounding-Box
        self.assertLess(lat.max() - lat.min(), 0.05)
        self.assertLess(lon.max() - lon.min(), 0.05)

    def test_speed_realistic_superbike(self):
        s = self.track["speed"]
        self.assertGreaterEqual(s.min(), 0.0)
        # Aprilia RSV4 in Jerez: definitiv >200 km/h, aber <300
        self.assertGreater(s.max(), 200.0)
        self.assertLess(s.max(), 300.0)

    def test_lap_count_after_filter(self):
        # Beacon-Liste aus dem Header ist Source of Truth (Stefan-Decision
        # v23.7, RS3-konform). Von 35 Beacons werden gefiltert:
        # - 1 Duration-Sentinel (letzter == Duration)
        # - 4 Splits mit Dauer <60s (Box-/Pit-Trigger: 26.999, 7.900,
        #   5.097, 33.999 — z.B. 2937.97/2945.87/2950.97/2984.97)
        # → 30 Runden übrig.
        self.assertEqual(self.track["meta"]["LAP_COUNT"], 30)
        self.assertEqual(len(self.track["lap_times"]), 30)

    def test_fastest_lap_value(self):
        # 1:46.405 = 106.405 s — exakt aus den Segment Times im Header
        durations = [d for _, d in self.track["lap_times"]]
        self.assertAlmostEqual(min(durations), 106.405, places=3)

    def test_no_phantom_last_lap(self):
        # Sicherheitsnetz gegen den ursprünglichen Sentinel-Bug: kein Lap
        # darf >600s lang sein (das wäre Duration - letzter_Beacon).
        for start_t, dur in self.track["lap_times"]:
            self.assertLess(dur, 600.0, f"Phantom-Lap {dur}s erkannt")
            self.assertGreaterEqual(dur, MIN_LAP_DURATION_S)

    def test_filter_drops_box_triggers(self):
        # Im Jerez-Sample gibt es 4 Beacon-Paare mit <60s Abstand
        # (z.B. 2937.97/2945.87/2950.97/2984.97 = 3 Splits unter 60s).
        # Die müssen alle rausgefiltert sein — keine Lap unter 60s.
        for _, dur in self.track["lap_times"]:
            self.assertGreaterEqual(dur, MIN_LAP_DURATION_S)

    def test_lap_distances_export(self):
        # Hybrid-Trackmap: jede Lap muss zusätzlich Distance-Boundaries
        # haben (für Datenviewer-Fallback bei tot-GPS).
        self.assertIn("lap_distances", self.track)
        self.assertEqual(
            len(self.track["lap_distances"]),
            len(self.track["lap_times"]),
        )
        # Jerez-Strecke = 4423m. Echte Runden sollten ~4300..4500m haben,
        # einige Out/In-Laps können länger sein.
        for i, (d0, dd) in enumerate(self.track["lap_distances"]):
            self.assertGreater(dd, 3000.0, f"Lap {i+1} Distance {dd}m zu klein")
            self.assertLess(dd, 6000.0, f"Lap {i+1} Distance {dd}m zu groß")

    def test_lap_distances_monotone(self):
        # Distance läuft kumulativ — d_start jeder folgenden Lap muss
        # >= d_end der vorherigen sein (mit kleiner Sentinel-Toleranz für
        # Splits die wir wegfiltern).
        prev_end = -1.0
        for d0, dd in self.track["lap_distances"]:
            self.assertGreaterEqual(d0, prev_end - 1.0)
            prev_end = d0 + dd

    def test_bike_channels_present(self):
        # Jerez hat RSV4-spezifische Bike-Kanäle
        ch = self.track["channels"]
        self.assertIn("RSV4 RPM", ch)
        self.assertIn("RSV4 GEAR", ch)
        self.assertIn("RSV4 ENG TEMP", ch)
        self.assertIn("RSV4 THRT HAND", ch)

    def test_channel_shape_consistent(self):
        # Alle Channels müssen gleiche Länge wie time haben
        n = len(self.track["time"])
        for name, info in self.track["channels"].items():
            self.assertEqual(
                len(info["data"]), n,
                f"Channel {name} hat Länge {len(info['data'])}, erwartet {n}",
            )

    def test_channel_units(self):
        ch = self.track["channels"]
        self.assertEqual(ch["GPS Altitude"]["unit"], "m")
        self.assertEqual(ch["RSV4 RPM"]["unit"], "rpm")
        self.assertEqual(ch["RSV4 ENG TEMP"]["unit"], "°C")

    def test_top_level_columns_not_in_channels(self):
        # Time/Lat/Lon/Speed sind im Top-Level-Dict, nicht in channels
        ch = self.track["channels"]
        self.assertNotIn("Time", ch)
        self.assertNotIn("GPS Speed", ch)
        self.assertNotIn("GPS Latitude", ch)
        self.assertNotIn("GPS Longitude", ch)


class TestAragonSample(unittest.TestCase):
    """Aragon: nur GPS-Kanäle, keine Bike-Daten. Regression-Schutz für
    Files ohne ECU-Telemetrie."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(SAMPLE_ARAGON):
            raise unittest.SkipTest(f"Sample fehlt: {SAMPLE_ARAGON}")
        cls.track = parse_aim_csv(SAMPLE_ARAGON)

    def test_meta_basics(self):
        m = self.track["meta"]
        self.assertEqual(m["VENUE"], "Aragon")
        self.assertEqual(m["VEHICLE"], "RJ27")
        self.assertEqual(m["RACER"], "Andrea")
        self.assertEqual(m["DATE"], "2026-03-23")
        self.assertEqual(m["SAMPLE_RATE_HZ"], 20)
        self.assertEqual(m["FASTEST_LAP"], "1:13.405")

    def test_gps_at_aragon(self):
        # MotorLand Aragón: ca. 41.08° N, -0.20° E
        lat = self.track["lat"]
        lon = self.track["lon"]
        self.assertAlmostEqual(np.median(lat), 41.08, places=1)
        self.assertAlmostEqual(np.median(lon), -0.20, places=1)

    def test_lap_count(self):
        # Aragon: 30 Beacons → 1 Sentinel raus, 6 Splits <60s raus
        # (Pit-Stops: 19.592s, 10.999s, 16.097s, 24.999s, 17.889s, 10.999s)
        # → 23 echte Runden, identisch zu RS3 (das in der Lap-Liste die
        # Splits separat zeigt aber als "out/in/numerische Runden" mischt).
        self.assertEqual(self.track["meta"]["LAP_COUNT"], 23)

    def test_fastest_lap(self):
        durations = [d for _, d in self.track["lap_times"]]
        self.assertAlmostEqual(min(durations), 73.405, places=3)

    def test_lap_22_is_206_runde(self):
        # Regression-Test für Stefans Bug-Report v23.6→v23.7: RS3 zeigt
        # eine Runde "2:06.974 - 27" mit echter Trackmap obwohl GPS Speed
        # und Lat/Lon-Spalten ab Lap 6 konstant 0/eingefroren sind. Diese
        # Runde MUSS importiert werden (war in v23.6 fälschlich rausgefiltert
        # vom Speed-Filter). In unserer Filter-Liste (Splits raus) ist
        # diese Runde Lap 22 (Header-Beacon-Index 27).
        durations = [d for _, d in self.track["lap_times"]]
        self.assertAlmostEqual(durations[21], 127.000, places=3)

    def test_lap_distances_export(self):
        # Aragon-Spezialfall: die GPS-Antenne fällt ab Lap 6 aus
        # (GPS Lat/Lon eingefroren, GPS Speed konstant 0), ABER die
        # `Distance on GPS Speed`-Spalte läuft korrekt weiter. Das ist
        # genau der Use-Case für Hybrid-Trackmap: lap_distances muss
        # vorhanden sein, plausibel mit Aragon-Strecke (5077m) matchen.
        self.assertIn("lap_distances", self.track)
        self.assertEqual(
            len(self.track["lap_distances"]),
            len(self.track["lap_times"]),
        )
        for i, (d0, dd) in enumerate(self.track["lap_distances"]):
            self.assertGreater(dd, 2000.0, f"Lap {i+1} dist {dd}m zu klein")
            self.assertLess(dd, 6000.0, f"Lap {i+1} dist {dd}m zu groß")

    def test_lap_22_distance_matches_rs3_screenshot(self):
        # Stefan hat einen RS3-Screenshot geliefert der Lap 27 (RS3-Index)
        # = unsere Lap 22 zeigt: x-Achse Distance 103000..107000m.
        # Wenn unsere Distance-Boundaries stimmen, muss diese Range
        # überdeckt werden.
        d0, dd = self.track["lap_distances"][21]
        self.assertGreater(d0 + dd, 107000.0, "Lap 22 sollte bis ≥107000m gehen")
        self.assertLess(d0, 104000.0, "Lap 22 sollte vor 104000m starten")

    def test_no_bike_channels(self):
        # Aragon: nur GPS-Block, keine RSV4-Kanäle
        ch = self.track["channels"]
        self.assertNotIn("RSV4 RPM", ch)
        self.assertNotIn("RSV4 GEAR", ch)
        # GPS-Kanäle aber schon
        self.assertIn("GPS Altitude", ch)
        self.assertIn("GPS Heading", ch)

    def test_distance_channel(self):
        # "Distance on GPS Speed" muss als Channel erscheinen
        self.assertIn("Distance on GPS Speed", self.track["channels"])


# ===========================================================================
# Edge-Cases: synthetische Inputs
# ===========================================================================

def _make_minimal_aim_csv(
    beacons,
    duration_s,
    n_samples=200,
    has_bike_channel=False,
    sample_rate=20,
    speed_fn=None,
):
    """Minimale, aber valide AIM CSV als String. Beacons in Sekunden,
    Duration als float. n_samples Datenzeilen zu sample_rate Hz.

    speed_fn: optional callable(t_seconds) -> km/h. Default: konstant 150."""
    bm = ",".join(f'"{b}"' for b in beacons)
    st_dummy = ",".join(f'"0:00.000"' for _ in beacons)
    dt = 1.0 / sample_rate
    if speed_fn is None:
        speed_fn = lambda t: 150.0
    header_cols = ['"Time"', '"GPS Speed"', '"GPS Nsat"', '"GPS LatAcc"',
                   '"GPS LonAcc"', '"GPS Slope"', '"GPS Heading"', '"GPS Gyro"',
                   '"GPS Altitude"', '"GPS PosAccuracy"', '"GPS SpdAccuracy"',
                   '"GPS Radius"', '"GPS Latitude"', '"GPS Longitude"',
                   '"Distance on GPS Speed"']
    units = ['"s"', '"km/h"', '" "', '"g"', '"g"', '"deg"', '"deg"', '"deg/s"',
             '"m"', '"mm"', '"km/h"', '"m"', '"deg"', '"deg"', '"m"']
    if has_bike_channel:
        header_cols.insert(-1, '"RSV4 RPM"')
        units.insert(-1, '"rpm"')

    lines = [
        '"Format","AiM CSV File"',
        '"Session","TestTrack"',
        '"Vehicle","TestBike"',
        '"Racer","TestRider"',
        '"Championship","None"',
        '"Comment",""',
        '"Date","Monday, January 1, 2026"',
        '"Time","12:00 PM"',
        f'"Sample Rate","{sample_rate}"',
        f'"Duration","{duration_s}"',
        '"Segment","Session"',
        f'"Beacon Markers",{bm}',
        f'"Segment Times",{st_dummy}',
        '',
        ",".join(header_cols),
        ",".join(units),
        '',
    ]
    for i in range(n_samples):
        t = i * dt
        v = speed_fn(t)
        vals = [f'"{t:.3f}"', f'"{v:.4f}"', '"7"', '"0"', '"0"', '"0"', '"0"',
                '"0"', '"100"', '"1"', '"0.1"', '"500"', '"36.7"', '"-6.0"',
                f'"{i*2.0:.4f}"']
        if has_bike_channel:
            vals.insert(-1, '"10000"')
        lines.append(",".join(vals))
    return "\r\n".join(lines) + "\r\n"


def _write_tmp(content: str, suffix=".csv") -> str:
    import tempfile
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return path


class TestEdgeCases(unittest.TestCase):
    """Synthetische Edge-Cases mit minimalen aber validen AIM CSVs."""

    def _parse(self, content):
        p = _write_tmp(content)
        self.addCleanup(os.unlink, p)
        return parse_aim_csv(p)

    def test_min_duration_filter(self):
        # 3 Beacons: 100s, 105s, 200s, Duration=200s.
        # Erwartete Laps: 0→100 (100s OK), 100→105 (5s VERWORFEN),
        # 105→200 (95s OK). Duration=200 → letzter Beacon ist Sentinel.
        # Letzte Boundary 200 wird gedroppt → boundaries [0, 100, 105].
        # Laps: 0-100 (100s ✓), 100-105 (5s ✗) → 1 Lap, dauer 100s.
        # Hmm, das ist wenig. Bauen wir's anders:
        # Beacons: 100s, 105s, 250s, Duration=300s.
        # Sentinel? letzter Beacon 250 != Duration 300 → KEIN Sentinel-Drop.
        # boundaries = [0, 100, 105, 250]; Laps:
        #   0-100 (100s ✓), 100-105 (5s ✗), 105-250 (145s ✓) = 2 Laps.
        track = self._parse(_make_minimal_aim_csv([100, 105, 250], 300, 50))
        durs = [d for _, d in track["lap_times"]]
        self.assertEqual(len(durs), 2)
        self.assertAlmostEqual(durs[0], 100.0, places=2)
        self.assertAlmostEqual(durs[1], 145.0, places=2)

    def test_duration_sentinel_dropped(self):
        # Letzter Beacon == Duration → wird als Sentinel gedroppt
        track = self._parse(_make_minimal_aim_csv([100, 250, 300], 300, 50))
        # boundaries nach Sentinel-Drop: [0, 100, 250]
        # Laps: 0-100 (100s ✓), 100-250 (150s ✓) = 2 Laps, KEIN Phantom.
        durs = [d for _, d in track["lap_times"]]
        self.assertEqual(len(durs), 2)
        self.assertAlmostEqual(durs[-1], 150.0, places=2)

    def test_duration_sentinel_tolerance(self):
        # Floating-Point: 14062 vs 14061.95 sollten als gleich gelten
        # (Sentinel-Drop mit 0.5s Toleranz).
        track = self._parse(_make_minimal_aim_csv([100, 14061.95], 14062, 100))
        # Sentinel-Drop greift → boundaries = [0, 100], 1 Lap dauer 100s
        durs = [d for _, d in track["lap_times"]]
        self.assertEqual(len(durs), 1)
        self.assertAlmostEqual(durs[0], 100.0, places=2)

    def test_no_beacons_returns_empty_laps(self):
        # Beacons leer/zu wenige → lap_times leer, kein Crash
        # Single beacon + ist Sentinel → boundaries = [0], keine Laps
        track = self._parse(_make_minimal_aim_csv([100.0], 100, 50))
        # lap_times ist optional — fehlt entweder oder ist leer
        self.assertEqual(track.get("lap_times", []), [])
        self.assertNotIn("LAP_COUNT", track["meta"])
        self.assertNotIn("FASTEST_LAP", track["meta"])

    def test_bike_channel_in_channels_dict(self):
        track = self._parse(
            _make_minimal_aim_csv([100, 200], 200, 80, has_bike_channel=True)
        )
        self.assertIn("RSV4 RPM", track["channels"])
        self.assertEqual(track["channels"]["RSV4 RPM"]["unit"], "rpm")
        self.assertEqual(track["channels"]["RSV4 RPM"]["rate"], 20)

    def test_top_level_arrays(self):
        track = self._parse(_make_minimal_aim_csv([100, 200], 200, 100))
        for key in ("time", "lat", "lon", "speed"):
            self.assertIn(key, track)
            self.assertEqual(len(track[key]), 100)

    def test_sample_rate_propagated_to_channels(self):
        track = self._parse(
            _make_minimal_aim_csv([100, 200], 200, 100, sample_rate=20)
        )
        for name, info in track["channels"].items():
            self.assertEqual(info["rate"], 20, f"Channel {name} rate wrong")

    def test_missing_header_raises(self):
        # Datei ohne Data-Header sollte ValueError werfen, nicht crashen
        broken = (
            '"Format","AiM CSV File"\r\n'
            '"Session","Broken"\r\n'
            # absichtlich kein Data-Header
        )
        p = _write_tmp(broken)
        self.addCleanup(os.unlink, p)
        with self.assertRaises(ValueError):
            parse_aim_csv(p)

    def test_missing_required_column_raises(self):
        # Data-Header ohne GPS Latitude → ValueError. Header muss >2 Spalten
        # haben damit unsere Detection ihn als Data-Header erkennt
        # (sonst wird er als Key/Value-Meta-Zeile interpretiert).
        broken = (
            '"Format","AiM CSV File"\r\n'
            '"Sample Rate","20"\r\n'
            '"Duration","100"\r\n'
            '\r\n'
            '"Time","GPS Speed","GPS Heading"\r\n'  # GPS Latitude/Longitude fehlen
            '"s","km/h","deg"\r\n'
            '\r\n'
            '"0.0","100","45"\r\n'
        )
        p = _write_tmp(broken)
        self.addCleanup(os.unlink, p)
        with self.assertRaises(ValueError) as cm:
            parse_aim_csv(p)
        self.assertIn("GPS Latitude", str(cm.exception))

    def test_malformed_row_skipped_not_crashed(self):
        # Eine kaputte Datenzeile mitten drin darf nicht den ganzen Parse
        # killen — wird einfach übersprungen.
        good = _make_minimal_aim_csv([100, 200], 200, 80)
        # Eine Zeile durch Mist ersetzen (Spaltenzahl falsch)
        lines = good.split("\r\n")
        lines[20] = '"junk"'  # kurz, wird übersprungen
        p = _write_tmp("\r\n".join(lines))
        self.addCleanup(os.unlink, p)
        track = parse_aim_csv(p)
        # 79 statt 80 Samples (eine Zeile übersprungen)
        self.assertEqual(len(track["time"]), 79)

    def test_no_speed_filter_regression(self):
        # Stefan-Decision v23.7: der Speed-Filter aus v23.6 wurde entfernt
        # weil er bei der Aragon-Datei 24 echte Runden weggeworfen hatte
        # (GPS-Antenne ausgefallen → Speed konstant 0, aber Runden real).
        # Eine "Lap" mit konstantem Speed 5 km/h aber Dauer 100s muss jetzt
        # importiert werden (Beacons sind Source of Truth).
        def speed_fn(t):
            return 150.0 if t < 100.0 else 5.0
        content = _make_minimal_aim_csv(
            [100, 200], 250, n_samples=5000,
            speed_fn=speed_fn,
        )
        p = _write_tmp(content)
        self.addCleanup(os.unlink, p)
        track = parse_aim_csv(p)
        # Beide Laps müssen jetzt durchkommen (>60s Dauer beide).
        self.assertEqual(len(track["lap_times"]), 2)
        # Beide auch in lap_distances vertreten.
        self.assertEqual(len(track.get("lap_distances", [])), 2)

    def test_lap_distances_consistency(self):
        # Distance-Boundaries müssen monoton wachsen und gleiche Länge
        # wie lap_times haben.
        content = _make_minimal_aim_csv([100, 200, 300], 350, n_samples=7000)
        p = _write_tmp(content)
        self.addCleanup(os.unlink, p)
        track = parse_aim_csv(p)
        self.assertEqual(
            len(track["lap_distances"]),
            len(track["lap_times"]),
        )
        # Im synthetischen Helper läuft Distance linear mit 2m/Sample.
        # Bei 20 Hz = 40 m/s = 144 km/h. Lap 1 (0..100s) = 4000m, dann
        # 100..200s = weitere 4000m etc. Toleranz wegen Sample-Boundary.
        for d0, dd in track["lap_distances"]:
            self.assertGreater(dd, 3500.0)
            self.assertLess(dd, 4500.0)


# ===========================================================================
# Integration mit detect_laps (laps.py)
# ===========================================================================

class TestLapsIntegration(unittest.TestCase):
    """Sicherstellen dass `lap_times` aus dem Parser kompatibel mit
    `laps.detect_laps()`-Strategie 0 (pre-computed) ist."""

    def test_detect_laps_uses_aim_lap_times(self):
        if not os.path.exists(SAMPLE_JEREZ):
            self.skipTest("Sample fehlt")
        from laps import detect_laps
        track = parse_aim_csv(SAMPLE_JEREZ)
        laps = detect_laps(track)
        # Strategie 0 trifft → method == "running_lap_time"
        self.assertEqual(laps[0]["method"], "running_lap_time")
        # Alle Laps sollten in den 30..600s sanity-Range fallen, das
        # heißt detect_laps verwirft keine weiter, weil parse_aim_csv
        # bereits strikter mit 60s gefiltert hat.
        self.assertEqual(len(laps), len(track["lap_times"]))


if __name__ == "__main__":
    unittest.main()
