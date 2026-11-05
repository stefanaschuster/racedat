"""Tests für den 2D → MoTeC LD Konverter (d22ld).

Strategie:
  * **Synthetische Tracks**: Wir konstruieren einen `track`-Dict in dem Format,
    das `parse_2d` zurückgibt (beide Varianten), und monkey-patchen parse_2d
    auf einen Fake. Dann ruft der Test `convert_2d` auf, parsed das Ergebnis
    mit `parse_ld` zurück und prüft Roundtrip-Invarianten.
  * **End-to-End mit echten Bundles** (optional): Wenn Stefans 2D-Test-Bundles
    in /mnt/user-data/uploads/ liegen, läuft zusätzlich der echte Konverter
    durch — wird übersprungen wenn die Bundles fehlen.

Run:
    python3 tests/test_d22ld.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

import d22ld
from d22ld import (
    _format_motec_date, _pick_dtype, _build_channels, convert_2d,
    GPS_LAT_NAMES, GPS_LON_NAMES, GPS_SPEED_NAMES, GPS_ALL_NAMES,
)
from parsers.ld_parser import parse_ld
from parsers.ld_writer import DTA_INT16, DTA_INT32


# ---------------------------------------------------------------------------
# Synthetische Track-Builder
# ---------------------------------------------------------------------------

def _synth_bmw_hp_track(duration_s: float = 120.0,
                        lap_durs=(45.0, 40.0, 35.0)):
    """Synthetisierter bmw_hp-Track, 100 Hz, Mugello-Koordinaten."""
    rate = 100.0
    n = int(duration_s * rate)
    t = np.arange(n) / rate
    # Lat/Lon: kleiner Wackler um Mugello-Center
    lat = 43.998 + np.sin(t * 2 * np.pi / 30) * 0.005
    lon = 11.372 + np.cos(t * 2 * np.pi / 30) * 0.005
    speed = 80 + 60 * np.abs(np.sin(t * 2 * np.pi / 20))  # 80..140 km/h
    rpm = 6000 + 4000 * np.abs(np.sin(t * 2 * np.pi / 5))
    throttle = 50 + 50 * np.sin(t * 2 * np.pi / 15)
    brake = np.clip(20 * np.sin(t * 2 * np.pi / 25), 0, None)

    # Lap_times als (start_s, duration_s); 2D-Parser filtert Out-/In-Lap raus
    lap_times = []
    cursor = 5.0  # Out-Lap-Ende
    for d in lap_durs:
        lap_times.append((cursor, d))
        cursor += d

    channels = {
        # Lat/Lon auch als "channel" — soll vom Konverter ausgefiltert werden
        "Latitude":   {"time": t.copy(), "data": lat,    "rate": 25, "unit": "deg"},
        "Longitude":  {"time": t.copy(), "data": lon,    "rate": 25, "unit": "deg"},
        "Speed":      {"time": t.copy(), "data": speed,  "rate": 25, "unit": "km/h"},
        # Echte 2D-bmw_hp-Channels
        "RPM":        {"time": t.copy(), "data": rpm,    "rate": 100, "unit": "1/min"},
        "Throttle":   {"time": t.copy(), "data": throttle, "rate": 100, "unit": "%"},
        "Brake":      {"time": t.copy(), "data": brake,  "rate": 100, "unit": "bar"},
        "VWheelFL":   {"time": t.copy(), "data": speed * 1.02, "rate": 100, "unit": "km/h"},
        "VWheelFR":   {"time": t.copy(), "data": speed * 0.98, "rate": 100, "unit": "km/h"},
    }
    return {
        "meta": {
            "DATE": "2023-07-01",
            "VENUE": "MUGELLO",
            "TRACK": "MUGELLO",
            "RACER": "TestRider",
            "VEHICLE": "BMW HP",
            "SOURCE": "2D",
            "VARIANT": "bmw_hp",
            "LAPMETER_M": "5245",
            "LOGGER": "2D MultiMaster",
            "FASTEST_LAP": "0:35.000",
            "LAP_COUNT": len(lap_times),
        },
        "time": t,
        "lat": lat,
        "lon": lon,
        "speed": speed,
        "finish_line": None,
        "source_format": "2D",
        "source_file": "(synth)",
        "running_lap_time": None,
        "channels": channels,
        "all_channels": ["lat", "lon", "speed"] + list(channels.keys()),
        "lap_times": lap_times,
    }


def _synth_race2025_track(duration_s: float = 180.0,
                          lap_durs=(50.0, 45.0, 42.0)):
    """Synthetisierter race2025-Track, 100 Hz, Valencia-Koordinaten."""
    rate = 100.0
    n = int(duration_s * rate)
    t = np.arange(n) / rate
    lat = 39.484 + np.sin(t * 2 * np.pi / 40) * 0.004
    lon = -0.630 + np.cos(t * 2 * np.pi / 40) * 0.004
    speed = 100 + 70 * np.abs(np.sin(t * 2 * np.pi / 25))
    rpm = 7000 + 5000 * np.abs(np.sin(t * 2 * np.pi / 6))
    lean = 45 * np.sin(t * 2 * np.pi / 18)

    lap_times = []
    cursor = 10.0
    for d in lap_durs:
        lap_times.append((cursor, d))
        cursor += d

    channels = {
        # race2025 nutzt teilweise andere Namen
        "GPS_Latitude":  {"time": t.copy(), "data": lat,    "rate": 25, "unit": "deg"},
        "GPS_Longitude": {"time": t.copy(), "data": lon,    "rate": 25, "unit": "deg"},
        "V_GPS":         {"time": t.copy(), "data": speed,  "rate": 25, "unit": "km/h"},
        "RPM":           {"time": t.copy(), "data": rpm,    "rate": 100, "unit": "1/min"},
        "ThrottleGrip":  {"time": t.copy(), "data": np.clip(50 + 50 * np.sin(t), 0, 100),
                          "rate": 100, "unit": "%"},
        "LeanAngle":     {"time": t.copy(), "data": lean,   "rate": 100, "unit": "deg"},
        "SUSF":          {"time": t.copy(), "data": 30 + 5*np.sin(t*10), "rate": 250, "unit": "mm"},
    }
    return {
        "meta": {
            "DATE": "2026-03-24",
            "VENUE": "VALENCIA",
            "TRACK": "Circuit de la Comunitat Valenciana Ricardo Tormo",
            "RACER": "",
            "VEHICLE": "",
            "SOURCE": "2D",
            "VARIANT": "race2025",
            "LAPMETER_M": "4005",
            "LOGGER": "M1000RR-Datalogger",
            "FASTEST_LAP": "0:42.000",
            "LAP_COUNT": len(lap_times),
        },
        "time": t,
        "lat": lat,
        "lon": lon,
        "speed": speed,
        "finish_line": (39.4836, -0.6311),
        "source_format": "2D",
        "source_file": "(synth)",
        "running_lap_time": None,
        "channels": channels,
        "all_channels": ["lat", "lon", "speed"] + list(channels.keys()),
        "lap_times": lap_times,
    }


# ---------------------------------------------------------------------------
# Unit-Tests: kleine Helper
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_format_motec_date_iso_to_dmy(self):
        # Parser-Output (ISO) → MoTeC-Format
        self.assertEqual(_format_motec_date("2023-07-01"), "01/07/2023")
        self.assertEqual(_format_motec_date("2026-03-24"), "24/03/2026")

    def test_format_motec_date_empty(self):
        self.assertEqual(_format_motec_date(""), "")

    def test_format_motec_date_passthrough(self):
        # Schon im DD/MM/YYYY-Format → unverändert
        self.assertEqual(_format_motec_date("01/07/2023"), "01/07/2023")
        self.assertEqual(_format_motec_date("garbage"), "garbage")

    def test_pick_dtype_small_int(self):
        # 0..100 — int16 reicht. Die Heuristik nimmt das KLEINSTE dec, bei dem
        # max_abs * 10^dec < 32000 — also dec=0 (100 < 32000).
        arr = np.linspace(0, 100, 1000)
        dta, sz, dec = _pick_dtype(arr)
        self.assertEqual(dta, DTA_INT16)
        self.assertEqual(sz, 2)
        self.assertEqual(dec, 0)

    def test_pick_dtype_huge_value_needs_int32(self):
        # RPM bis 16000 → 16000 ist <32000, passt mit dec=0 in int16.
        arr = np.array([15000.0, 16000.0])
        dta, sz, dec = _pick_dtype(arr)
        self.assertEqual(dta, DTA_INT16)
        self.assertEqual(dec, 0)

    def test_pick_dtype_lat_like_needs_precision(self):
        # Lat-Werte (-90..90): max_abs ~39 → mit dec=2 gerade noch <32000
        # (39 * 100 = 3900). Heuristik nimmt das KLEINSTE passende dec — dec=0
        # weil 39 < 32000. Das ist für GPS unzureichend (1° Auflösung wäre
        # ~111 km), aber unser Konverter benutzt für Lat/Lon ohnehin den
        # dedizierten gps_lat_channel-Builder mit int32 dec=7 — _pick_dtype
        # kommt für GPS gar nicht zum Einsatz.
        arr = np.array([39.484, 39.485, -0.630])
        dta, sz, dec = _pick_dtype(arr)
        self.assertEqual(dta, DTA_INT16)
        self.assertEqual(dec, 0)  # heuristik nimmt minimales dec

    def test_pick_dtype_very_precise_input(self):
        # max_abs = 0.001 — die Heuristik bevorzugt das KLEINSTE passende dec
        # (für jedes dec=0..3 ist 0.001*10^dec < 32000), also dec=0. Das ist
        # für sehr kleine Werte verlustbehaftet, aber es ist die etablierte
        # xrk2ld-Heuristik. Stefan kann für Spezialchannels manuell anpassen.
        arr = np.array([0.0001, 0.001, -0.0005])
        dta, sz, dec = _pick_dtype(arr)
        self.assertEqual(dta, DTA_INT16)
        self.assertEqual(dec, 0)

    def test_pick_dtype_needs_int32(self):
        # max_abs >32000 → int16 reicht nicht mit dec=0, dec=1..3 macht's
        # noch schlimmer; muss int32 sein.
        arr = np.array([50000.0, 100000.0])
        dta, sz, dec = _pick_dtype(arr)
        self.assertEqual(dta, DTA_INT32)
        self.assertEqual(sz, 4)

    def test_pick_dtype_all_zero(self):
        arr = np.zeros(100)
        dta, sz, dec = _pick_dtype(arr)
        self.assertEqual(dta, DTA_INT16)
        self.assertEqual(dec, 0)

    def test_pick_dtype_all_nan(self):
        arr = np.full(100, np.nan)
        dta, sz, dec = _pick_dtype(arr)
        self.assertEqual(dta, DTA_INT16)

    def test_gps_name_sets_cover_both_variants(self):
        # bmw_hp- und race2025-Schreibweisen müssen alle drin sein.
        self.assertIn("Latitude", GPS_LAT_NAMES)
        self.assertIn("GPS_Latitude", GPS_LAT_NAMES)
        self.assertIn("Lat_dez", GPS_LAT_NAMES)
        self.assertIn("V_GPS", GPS_SPEED_NAMES)


# ---------------------------------------------------------------------------
# Unit-Tests: _build_channels
# ---------------------------------------------------------------------------

class TestBuildChannels(unittest.TestCase):

    def test_lat_lon_not_duplicated_bmw_hp(self):
        track = _synth_bmw_hp_track()
        channels, rate = _build_channels(track, rename=False)
        names = [c.name for c in channels]
        # "GPS Latitude" / "GPS Longitude" / "GPS Speed" GENAU EINMAL.
        self.assertEqual(names.count("GPS Latitude"), 1)
        self.assertEqual(names.count("GPS Longitude"), 1)
        self.assertEqual(names.count("GPS Speed"), 1)
        # Die rohen Channel-Namen "Latitude"/"Longitude"/"Speed" dürfen NICHT
        # nochmal als separate Channels erscheinen — sonst hätten wir Lat/Lon
        # mit zwei verschiedenen Skalierungen im File.
        self.assertNotIn("Latitude", names)
        self.assertNotIn("Longitude", names)
        self.assertNotIn("Speed", names)

    def test_lat_lon_not_duplicated_race2025(self):
        track = _synth_race2025_track()
        channels, rate = _build_channels(track, rename=False)
        names = [c.name for c in channels]
        self.assertEqual(names.count("GPS Latitude"), 1)
        self.assertEqual(names.count("GPS Longitude"), 1)
        self.assertEqual(names.count("GPS Speed"), 1)
        self.assertNotIn("GPS_Latitude", names)
        self.assertNotIn("GPS_Longitude", names)
        self.assertNotIn("V_GPS", names)

    def test_rate_derived_from_time_axis(self):
        track = _synth_bmw_hp_track()
        _, rate = _build_channels(track, rename=False)
        self.assertEqual(rate, 100)  # 100 Hz wie konstruiert

    def test_other_channels_passed_through(self):
        track = _synth_bmw_hp_track()
        channels, _ = _build_channels(track, rename=False)
        names = [c.name for c in channels]
        # Echte 2D-Datenchannels sollen drin sein
        self.assertIn("RPM", names)
        self.assertIn("Throttle", names)
        self.assertIn("VWheelFL", names)

    def test_rename_applies(self):
        track = _synth_bmw_hp_track()
        channels, _ = _build_channels(track, rename=True)
        names = [c.name for c in channels]
        # VWheelFL → "Wheel Speed FL" (aus parsers/channel_names.py)
        self.assertIn("Wheel Speed FL", names)
        self.assertIn("Engine RPM", names)
        # Brake bleibt nicht "Brake" sondern wird zu "Brake Pos" gemappt
        self.assertIn("Brake Pos", names)
        # Ohne Mapping bekannte Channels (Throttle) bleiben gleich
        self.assertIn("Throttle", names)

    def test_no_rename_keeps_2d_names(self):
        track = _synth_bmw_hp_track()
        channels, _ = _build_channels(track, rename=False)
        names = [c.name for c in channels]
        self.assertIn("RPM", names)
        self.assertIn("VWheelFL", names)
        self.assertNotIn("Engine RPM", names)

    def test_empty_channel_dropped(self):
        track = _synth_bmw_hp_track()
        # Add a channel that's all NaN — must NOT make it into the LD.
        track["channels"]["DeadSensor"] = {
            "time": track["time"].copy(),
            "data": np.full(len(track["time"]), np.nan),
            "rate": 100, "unit": "",
        }
        channels, _ = _build_channels(track, rename=False)
        names = [c.name for c in channels]
        self.assertNotIn("DeadSensor", names)

    def test_units_preserved(self):
        track = _synth_bmw_hp_track()
        channels, _ = _build_channels(track, rename=False)
        by_name = {c.name: c for c in channels}
        self.assertEqual(by_name["RPM"].unit, "1/min")
        self.assertEqual(by_name["Throttle"].unit, "%")
        # GPS-Builder setzen Standard-Units
        self.assertEqual(by_name["GPS Speed"].unit, "km/h")
        self.assertEqual(by_name["GPS Latitude"].unit, "deg")


# ---------------------------------------------------------------------------
# End-to-End: convert_2d mit gemockten parse_2d → LD-Roundtrip
# ---------------------------------------------------------------------------

class TestConvertRoundtripBmwHp(unittest.TestCase):
    """Roundtrip: synth-track → write LD → parse_ld → Werte zurückvergleichen."""

    def setUp(self):
        self.track = _synth_bmw_hp_track()
        self.tmpdir = tempfile.mkdtemp(prefix="d22ld_test_")
        self.bundle = os.path.join(self.tmpdir, "test_bundle.zip")
        # Wir erzeugen keine echte ZIP — parse_2d wird gemockt.
        Path(self.bundle).touch()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _convert(self, **kwargs):
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            return convert_2d(self.bundle, quiet=True, **kwargs)

    def test_output_files_created(self):
        ld_path, ldx_path = self._convert()
        self.assertTrue(os.path.exists(ld_path))
        self.assertTrue(os.path.exists(ldx_path))
        # LD muss substantiell groß sein
        self.assertGreater(os.path.getsize(ld_path), 1000)

    def test_ld_parses_back(self):
        ld_path, _ = self._convert()
        parsed = parse_ld(ld_path)
        # Pflicht-GPS-Channels da
        self.assertEqual(len(parsed["lat"]), len(self.track["time"]))
        # Lat/Lon-Werte ungefähr stimmen (int32 dec=7 → 0.0000001-Präzision)
        np.testing.assert_allclose(parsed["lat"], self.track["lat"], atol=1e-5)
        np.testing.assert_allclose(parsed["lon"], self.track["lon"], atol=1e-5)
        # Speed in km/h, dec=1 → 0.1-Präzision
        np.testing.assert_allclose(parsed["speed"], self.track["speed"], atol=0.2)

    def test_extra_channels_roundtrip(self):
        ld_path, _ = self._convert()
        parsed = parse_ld(ld_path)
        # Datenchannels sind als "extra channels" dabei
        self.assertIn("RPM", parsed["channels"])
        self.assertIn("Throttle", parsed["channels"])
        # RPM-Werte ungefähr stimmen (int16 dec=0 → ±1 RPM)
        rpm_back = parsed["channels"]["RPM"]["data"]
        np.testing.assert_allclose(rpm_back, self.track["channels"]["RPM"]["data"],
                                   atol=2.0)
        # Unit-Erhalt
        self.assertEqual(parsed["channels"]["RPM"]["unit"], "1/min")
        self.assertEqual(parsed["channels"]["Throttle"]["unit"], "%")

    def test_beacon_and_running_lap_channels_present(self):
        ld_path, _ = self._convert()
        parsed = parse_ld(ld_path)
        # Beacon: nicht in "channels" weil SKIP_AS_EXTRA es nicht skippt,
        # aber wir checken explizit dass es im all_channels-List ist.
        self.assertIn("Beacon", parsed["all_channels"])
        self.assertIn("Running Lap Time", parsed["all_channels"])

    def test_lap_count_in_ldx(self):
        _, ldx_path = self._convert()
        ldx = Path(ldx_path).read_text(encoding="utf-8")
        # LDX nutzt <Marker Version="100" .../> pro Lap-Boundary (3 Laps → 3
        # Marker), siehe parsers/ldx_writer.py Z.79.
        self.assertGreaterEqual(ldx.count("<Marker"), 3)
        # Plus Total Laps wird gesetzt
        self.assertIn("Total Laps", ldx)

    def test_metadata_in_header(self):
        ld_path, _ = self._convert(driver="Custom Driver", session="FP2")
        with open(ld_path, "rb") as f:
            head = f.read(1800)
        self.assertIn(b"Custom Driver", head)
        # Venue aus dem Track-Meta
        self.assertIn(b"MUGELLO", head)
        # Datum als DD/MM/YYYY
        self.assertIn(b"01/07/2023", head)

    def test_comment_default_includes_variant(self):
        ld_path, _ = self._convert()
        with open(ld_path, "rb") as f:
            # Comment-Feld liegt bei Offset 1572 (parsers/ld_writer.py Z.59).
            # Header insgesamt 1762 Bytes — lesen wir 1800 zur Sicherheit.
            head = f.read(1800)
        self.assertIn(b"2D", head)
        self.assertIn(b"bmw_hp", head)

    def test_metadata_overrides(self):
        ld_path, _ = self._convert(
            driver="Stefan", vehicle="S1000RR", venue="OVERRIDE_VENUE",
            event="Test Event", session="Q1", comment="custom comment",
        )
        with open(ld_path, "rb") as f:
            # Comment liegt bei Offset 1572, Driver bei 158, Vehicle bei 222,
            # Venue bei 350 — bis 1800 lesen deckt alles ab.
            head = f.read(1800)
        self.assertIn(b"Stefan", head)
        self.assertIn(b"S1000RR", head)
        self.assertIn(b"OVERRIDE_VENUE", head)
        self.assertIn(b"custom comment", head)
        # Default-Comment ("2D · bmw_hp · ...") darf nicht mehr da sein, da
        # explizit überschrieben.
        self.assertNotIn(b"bmw_hp", head)


class TestConvertRoundtripRace2025(unittest.TestCase):
    """Roundtrip mit race2025-Track-Format."""

    def setUp(self):
        self.track = _synth_race2025_track()
        self.tmpdir = tempfile.mkdtemp(prefix="d22ld_test_")
        self.bundle = os.path.join(self.tmpdir, "valencia_test.zip")
        Path(self.bundle).touch()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_output_files_created(self):
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            ld_path, ldx_path = convert_2d(self.bundle, quiet=True)
        self.assertTrue(os.path.exists(ld_path))
        self.assertTrue(os.path.exists(ldx_path))

    def test_race2025_specific_channels_pass_through(self):
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            ld_path, _ = convert_2d(self.bundle, quiet=True)
        parsed = parse_ld(ld_path)
        # race2025-Spezifika: LeanAngle, ThrottleGrip, SUSF
        self.assertIn("LeanAngle", parsed["channels"])
        self.assertIn("ThrottleGrip", parsed["channels"])
        self.assertIn("SUSF", parsed["channels"])

    def test_track_long_name_used_as_event(self):
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            ld_path, _ = convert_2d(self.bundle, quiet=True)
        with open(ld_path, "rb") as f:
            data = f.read()
        # TRACK-Feld aus race2025 EVENT.INI ist lang ("Circuit de la
        # Comunitat Valenciana ...") und landet im Event-Block.
        self.assertIn(b"Comunitat Valenciana", data)

    def test_venue_from_event_ini(self):
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            ld_path, _ = convert_2d(self.bundle, quiet=True)
        with open(ld_path, "rb") as f:
            head = f.read(0x600)
        self.assertIn(b"VALENCIA", head)

    def test_comment_default_includes_race2025_variant(self):
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            ld_path, _ = convert_2d(self.bundle, quiet=True)
        with open(ld_path, "rb") as f:
            head = f.read(0x800)
        self.assertIn(b"race2025", head)


class TestConvertNoLaps(unittest.TestCase):
    """Edge-Case: Bundle ohne erkannte Laps (nur eine Out-Lap, alles gefiltert)."""

    def test_zero_laps_still_writes_ld_and_ldx(self):
        track = _synth_bmw_hp_track()
        track["lap_times"] = []  # keine Laps
        tmpdir = tempfile.mkdtemp(prefix="d22ld_nolap_")
        try:
            bundle = os.path.join(tmpdir, "nolap.zip")
            Path(bundle).touch()
            with mock.patch("d22ld.parse_2d", return_value=track):
                ld_path, ldx_path = convert_2d(bundle, quiet=True)
            self.assertTrue(os.path.exists(ld_path))
            self.assertTrue(os.path.exists(ldx_path))
            # Beacon-Channel darf NICHT existieren, wenn keine Laps da sind
            parsed = parse_ld(ld_path)
            self.assertNotIn("Beacon", parsed["all_channels"])
            self.assertNotIn("Running Lap Time", parsed["all_channels"])
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestConvertNoChannels(unittest.TestCase):
    """Edge-Case: Bundle dessen Channels alle leer/NaN sind → RuntimeError."""

    def test_empty_bundle_raises(self):
        track = _synth_bmw_hp_track()
        # Alle Channels (auch Lat/Lon/Speed) auf leere Arrays setzen
        nan_arr = np.array([], dtype=np.float64)
        track["lat"] = nan_arr
        track["lon"] = nan_arr
        track["speed"] = nan_arr
        track["channels"] = {}
        track["time"] = nan_arr

        tmpdir = tempfile.mkdtemp(prefix="d22ld_empty_")
        try:
            bundle = os.path.join(tmpdir, "empty.zip")
            Path(bundle).touch()
            with mock.patch("d22ld.parse_2d", return_value=track):
                with self.assertRaises(RuntimeError):
                    convert_2d(bundle, quiet=True)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestOutputPathHandling(unittest.TestCase):
    """Pfad-Auflösung: -o als File-Prefix vs. -o als Verzeichnis."""

    def setUp(self):
        self.track = _synth_bmw_hp_track()
        self.tmpdir = tempfile.mkdtemp(prefix="d22ld_paths_")
        self.bundle = os.path.join(self.tmpdir, "src.zip")
        Path(self.bundle).touch()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_output_next_to_input(self):
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            ld_path, ldx_path = convert_2d(self.bundle, quiet=True)
        self.assertEqual(ld_path, os.path.join(self.tmpdir, "src.ld"))
        self.assertEqual(ldx_path, os.path.join(self.tmpdir, "src.ldx"))

    def test_explicit_out_base(self):
        out_base = os.path.join(self.tmpdir, "subdir", "myresult")
        os.makedirs(os.path.dirname(out_base), exist_ok=True)
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            ld_path, ldx_path = convert_2d(self.bundle, out_base=out_base,
                                            quiet=True)
        self.assertEqual(ld_path, out_base + ".ld")
        self.assertEqual(ldx_path, out_base + ".ldx")

    def test_mes_dir_input_strips_suffix(self):
        # Input ist ein Verzeichnis namens "foo.MES" → Output soll "foo.ld"
        # heißen, nicht "foo.MES.ld"
        mes_dir = os.path.join(self.tmpdir, "foo.MES")
        os.makedirs(mes_dir)
        with mock.patch("d22ld.parse_2d", return_value=self.track):
            ld_path, _ = convert_2d(mes_dir, quiet=True)
        # ".MES" muss gestrippt sein, ".ld" angehängt
        self.assertEqual(ld_path, os.path.join(self.tmpdir, "foo.ld"))
        self.assertNotIn(".MES.", ld_path)


# ---------------------------------------------------------------------------
# Optional: End-to-End mit Stefans echten Bundles, wenn vorhanden
# ---------------------------------------------------------------------------

BUNDLE_MUGELLO = "/mnt/user-data/uploads/2D_MUGELLO_20230701-1547-01_MES.zip"
BUNDLE_HHM = "/mnt/user-data/uploads/2D_HHM-GP_20230811-1144-01_MES.zip"
BUNDLE_VALENCIA = "/mnt/user-data/uploads/2D_Measurements_from_VALENCIA6D_26.zip"


class TestRealBundlesIfAvailable(unittest.TestCase):
    """Smoke-Tests gegen Stefans Original-Bundles. Skip wenn nicht da."""

    def _convert_and_check(self, bundle_path, expected_min_channels=20):
        if not os.path.exists(bundle_path):
            self.skipTest(f"Bundle missing: {bundle_path}")
        tmpdir = tempfile.mkdtemp(prefix="d22ld_real_")
        try:
            out_base = os.path.join(tmpdir, "out")
            ld_path, ldx_path = convert_2d(bundle_path, out_base=out_base,
                                            quiet=True)
            self.assertTrue(os.path.exists(ld_path))
            self.assertTrue(os.path.exists(ldx_path))
            parsed = parse_ld(ld_path)
            # GPS muss da sein
            self.assertGreater(len(parsed["lat"]), 1000)
            # Channels müssen substantiell sein (80+ erwartet)
            self.assertGreaterEqual(len(parsed["channels"]),
                                    expected_min_channels)
            # Beacon-Channels da
            self.assertIn("Beacon", parsed["all_channels"])
            self.assertIn("Running Lap Time", parsed["all_channels"])
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_mugello_bmw_hp(self):
        self._convert_and_check(BUNDLE_MUGELLO, expected_min_channels=50)

    def test_hockenheim_bmw_hp(self):
        self._convert_and_check(BUNDLE_HHM, expected_min_channels=50)

    def test_valencia_race2025(self):
        self._convert_and_check(BUNDLE_VALENCIA, expected_min_channels=50)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
