"""Tests for the 2D BMW HP Race Datalogger parser.

Validates against the two sample bundles Stefan provided:
  • Mugello 2023-07-01 (11 declared laps, fastest 2:01.540)
  • Hockenheim GP 2023-08-11 (10 declared laps, fastest 1:51.190)

Run: cd /home/claude/lap_tool && python3 -m pytest tests/test_2d_parser.py -v
Or:  python3 tests/test_2d_parser.py
"""
import sys
import os
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from parsers.d2_parser import parse_2d


BUNDLE_MUGELLO = "/mnt/user-data/uploads/2D_MUGELLO_20230701-1547-01_MES.zip"
BUNDLE_HHM = "/mnt/user-data/uploads/2D_HHM-GP_20230811-1144-01_MES.zip"
# 2025er M1000RR-Logger mit MainSamplingRate=400 (statt 100 wie ältere Bundles).
# Q1-Qualifying von Rijeka 2025-08-09: 6 [Laptimes]-Einträge (Lap 0 = 0:00.000
# Outlap-Platzhalter, dann Out-Lap + 3 Flying Laps + In-Lap), Fastest=1:32.398.
BUNDLE_RIJEKA_Q1 = "/mnt/user-data/uploads/1_32_398_AAIMC_Q1_MES.zip"


class Test2DMugello(unittest.TestCase):
    """Sanity checks for the Mugello bundle."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(BUNDLE_MUGELLO):
            raise unittest.SkipTest(f"Test bundle missing: {BUNDLE_MUGELLO}")
        cls.track = parse_2d(BUNDLE_MUGELLO)

    def test_meta(self):
        m = self.track["meta"]
        self.assertEqual(m["VENUE"], "MUGELLO")
        self.assertEqual(m["SOURCE"], "2D")
        self.assertEqual(m["DATE"], "2023-07-01")
        self.assertEqual(m["FASTEST_LAP"], "2:01.540")
        self.assertEqual(m["LAP_COUNT"], 10)  # after filtering out the 79s inlap
        self.assertEqual(m["LAPMETER_M"], "19245")

    def test_time_axis_100Hz(self):
        t = self.track["time"]
        # Expect roughly 1706 seconds at 100 Hz = 170,624 samples
        self.assertGreater(len(t), 170_000)
        self.assertLess(len(t), 171_000)
        dt = np.median(np.diff(t))
        self.assertAlmostEqual(dt, 0.01, places=4)  # 100 Hz

    def test_gps_at_mugello(self):
        lat = self.track["lat"]
        lon = self.track["lon"]
        # Mugello GP coordinates: 43.997°N, 11.371°E
        # After our spike filter, all samples should be near the track.
        self.assertAlmostEqual(np.median(lat), 43.998, places=2)
        self.assertAlmostEqual(np.median(lon), 11.372, places=2)
        self.assertLess(lat.max() - lat.min(), 0.05)  # track fits in <5km
        self.assertLess(lon.max() - lon.min(), 0.05)

    def test_speed_realistic(self):
        s = self.track["speed"]
        self.assertGreaterEqual(s.min(), 0.0)
        self.assertGreater(s.max(), 250.0)  # superbike should crack 250+
        self.assertLess(s.max(), 350.0)     # but not >350

    def test_80_channels(self):
        self.assertEqual(len(self.track["channels"]), 80)

    def test_rpm_channel(self):
        rpm = self.track["channels"]["RPM"]
        self.assertEqual(rpm["unit"], "1/min")
        self.assertEqual(rpm["rate"], 100)
        self.assertGreater(rpm["data"].max(), 12000)  # S1000RR redlines high
        self.assertLess(rpm["data"].max(), 16000)

    def test_throttle_channel(self):
        t = self.track["channels"]["Throttle"]
        self.assertEqual(t["unit"], "%")
        self.assertGreater(t["data"].max(), 98.0)  # full throttle reached
        self.assertLess(t["data"].max(), 102.0)

    def test_bank_realistic(self):
        # Bank_abs is computed (always positive), Bank_dtc can be signed.
        bank = self.track["channels"]["Bank_abs"]["data"]
        self.assertLess(bank.max(), 65.0)   # not impossible lean
        self.assertGreater(bank.max(), 40.0)  # racing leans hard

    def test_v_gps_scaled(self):
        # Regression: V_GPS was previously reading as raw int16 (max 26530)
        # because we didn't apply scaling to "computed" fmt 101 channels.
        v = self.track["channels"]["V_GPS"]["data"]
        self.assertLess(v.max(), 300.0)
        self.assertGreater(v.max(), 250.0)

    def test_suspension_scaled(self):
        # Regression: Susp_*_hi_2d had unscaled int values up to 1300+
        s = self.track["channels"]["Susp_fr_hi_2d"]["data"]
        self.assertLess(s.max(), 200.0)  # ~120 mm typical max
        self.assertGreater(s.max(), 50.0)

    def test_acceleration_scaled(self):
        # Regression: A_Lon/Lat_GPS were ±32768 raw int16
        # Sentinel values (int16 ±32768 = ±32.768 m/s²) are rare hardware
        # overflow markers — we expect <1% of samples to hit them and the
        # 99th percentile to be inside ±25 m/s² (real bike lateral is <2g).
        a_lat = self.track["channels"]["A_Lat_GPS"]["data"]
        p99 = np.percentile(np.abs(a_lat), 99)
        self.assertLess(p99, 25.0)
        self.assertGreater(abs(a_lat).max(), 10.0)  # peaks above 1g

    def test_lap_times_present(self):
        lt = self.track["lap_times"]
        self.assertGreater(len(lt), 5)
        # Sum of lap_times durations should be < total recording time
        total_lap_dur = sum(dur for (_, dur) in lt)
        total_recording = self.track["time"][-1]
        self.assertLess(total_lap_dur, total_recording + 5)

    def test_fastest_via_pipeline(self):
        from laps import detect_laps, fastest_lap
        laps = detect_laps(self.track)
        fl = fastest_lap(laps)
        self.assertAlmostEqual(fl["duration"], 121.540, places=2)


class Test2DHockenheim(unittest.TestCase):
    """Sanity checks for the Hockenheim bundle (different track, different
    file sizes — validates that the parser isn't accidentally hard-coded for
    Mugello-specific layouts)."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(BUNDLE_HHM):
            raise unittest.SkipTest(f"Test bundle missing: {BUNDLE_HHM}")
        cls.track = parse_2d(BUNDLE_HHM)

    def test_meta(self):
        m = self.track["meta"]
        self.assertEqual(m["VENUE"], "HHM-GP")
        self.assertEqual(m["FASTEST_LAP"], "1:51.190")
        self.assertEqual(m["DATE"], "2023-08-11")

    def test_gps_at_hockenheim(self):
        # Hockenheim GP: 49.328°N, 8.566°E. Use looser places=1 because the
        # track's GPS bbox is asymmetric — median lon is biased toward the
        # west side where the long straight sits.
        lat = self.track["lat"]
        lon = self.track["lon"]
        self.assertAlmostEqual(np.median(lat), 49.330, places=2)
        self.assertAlmostEqual(np.median(lon), 8.57, places=1)

    def test_fastest_via_pipeline(self):
        from laps import detect_laps, fastest_lap
        laps = detect_laps(self.track)
        fl = fastest_lap(laps)
        # HED says 1:51.190 = 111.190s
        self.assertAlmostEqual(fl["duration"], 111.190, places=2)

    def test_80_channels(self):
        self.assertEqual(len(self.track["channels"]), 80)


BUNDLE_VALENCIA = "/mnt/user-data/uploads/2D_Measurements_from_VALENCIA6D_26.zip"


class Test2DValenciaRace2025(unittest.TestCase):
    """Sanity checks for the Race2025-variant Valencia bundle.

    Diese Variante kommt aus dem BMW M1000RR Race2025-Track-Tool und hat
    folgende strukturelle Unterschiede zum klassischen BMW-HP-Bundle:

      • ZIP enthält ein Wrapper-Verzeichnis mit EVENT.INI/RING.INI/<track>.line
        statt .MES direkt im Root
      • DDD benutzt fmt-codes 2/102 (statt 1/4/101/104)
      • DDD field 5 ist Sample-Periode in ms hex (statt Teiler von 100Hz)
      • Multi-rate: Channels von 1 Hz (TrackID) bis 250 Hz (Suspension)
      • Fast alle Channels float32 ohne Skalierung
      • Channel-Namen sind generisch (RPM, ThrottleGrip, LeanAngle, SUSF/SUSR)

    Die Pipeline soll alles selbst erkennen, dasselbe Output-Schema liefern
    und mit detect_laps()/fastest_lap() funktionieren.
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(BUNDLE_VALENCIA):
            raise unittest.SkipTest(f"Test bundle missing: {BUNDLE_VALENCIA}")
        cls.track = parse_2d(BUNDLE_VALENCIA)

    def test_variant_detected(self):
        self.assertEqual(self.track["meta"]["VARIANT"], "race2025")
        self.assertEqual(self.track["meta"]["SOURCE"], "2D")

    def test_meta_from_event_ini(self):
        m = self.track["meta"]
        # VENUE / TRACK kommen aus EVENT.INI [MAIN]/[Track], nicht aus dem
        # nichtssagenden Bundle-Stem.
        self.assertEqual(m["VENUE"], "VALENCIA")
        self.assertIn("Comunitat Valenciana", m["TRACK"])
        self.assertEqual(m["DATE"], "2026-03-24")
        self.assertEqual(m["FASTEST_LAP"], "1:44.040")
        # Nach Out-/In-Lap-Filterung mit Fastest-Anchor=104.04s
        # bleiben 15 vollständige Laps von 18 declared.
        self.assertEqual(m["LAP_COUNT"], 15)

    def test_finish_line_from_dotline_file(self):
        # Valencia.line liefert die Start-Ziel-Linie als (lat, lon).
        fl = self.track["finish_line"]
        self.assertIsNotNone(fl)
        lat, lon = fl
        self.assertAlmostEqual(lat, 39.4836, places=3)
        self.assertAlmostEqual(lon, -0.6311, places=3)

    def test_time_axis_100Hz(self):
        # Race ist 3527s lang → ~352700 Samples bei 100 Hz.
        t = self.track["time"]
        self.assertGreater(len(t), 350_000)
        self.assertLess(len(t), 360_000)
        dt = np.median(np.diff(t))
        self.assertAlmostEqual(dt, 0.01, places=4)

    def test_gps_at_valencia(self):
        # Valencia GP: 39.484°N, -0.630°E
        lat = self.track["lat"]
        lon = self.track["lon"]
        self.assertAlmostEqual(np.median(lat), 39.484, places=2)
        self.assertAlmostEqual(np.median(lon), -0.630, places=2)
        # GPS-Spike-Filter muss die Pre-Fix-0.0-Samples entfernt haben:
        self.assertGreater(lat.min(), 39.0)
        self.assertLess(lon.max(), -0.5)

    def test_speed_realistic(self):
        s = self.track["speed"]
        self.assertGreaterEqual(s.min(), 0.0)
        self.assertGreater(s.max(), 250.0)
        self.assertLess(s.max(), 320.0)

    def test_81_channels(self):
        # Race2025 hat einen Channel mehr als BMW HP (Sim4/Sim5 oder GPS-Spezifika).
        self.assertEqual(len(self.track["channels"]), 81)

    def test_rpm_float32_direct(self):
        # Im race2025-Dialekt ist RPM ein float32 mit scale=1, offset=0 —
        # die Werte stehen unmittelbar im File ohne Skalierung.
        rpm = self.track["channels"]["RPM"]
        self.assertEqual(rpm["rate"], 100)
        self.assertGreater(rpm["data"].max(), 14000)  # M1000RR redlines hoch
        self.assertLess(rpm["data"].max(), 16500)

    def test_throttle_grip_0_to_100(self):
        t = self.track["channels"]["ThrottleGrip"]
        self.assertGreaterEqual(t["data"].min(), 0.0)
        self.assertLessEqual(t["data"].max(), 100.1)
        self.assertGreater(t["data"].max(), 95.0)

    def test_lean_angle_signed(self):
        la = self.track["channels"]["LeanAngle"]["data"]
        # LeanAngle ist signed (negativ = links, positiv = rechts)
        self.assertGreater(la.max(), 40.0)
        self.assertLess(la.min(), -40.0)
        self.assertLess(la.max(), 65.0)

    def test_suspension_high_rate(self):
        # SUSF/SUSR laufen mit 250 Hz nativ (höher als die 100 Hz Output-Basis).
        s = self.track["channels"]["SUSF"]
        self.assertEqual(s["rate"], 250)
        # ... aber die Daten sind auf die 100-Hz-Time-Axis resampled.
        self.assertEqual(len(s["data"]), len(self.track["time"]))

    def test_gps_low_rate(self):
        # GPS_Latitude ist 25 Hz nativ in race2025 (nicht 12.5 Hz wie bmw_hp).
        g = self.track["channels"]["GPS_Latitude"]
        self.assertEqual(g["rate"], 25)

    def test_lap_times_filtered(self):
        # 18 declared laps in HED, davon Lap 0 (799s, sightseeing out-lap),
        # Lap 11 (995s, box-stop) und Lap 17 (55s, in-lap unvollständig)
        # müssen rausgefiltert werden → 15 echte Laps.
        lt = self.track["lap_times"]
        self.assertEqual(len(lt), 15)
        # Erste echte Runde ist Lap 1 (Index 1 in HED) bei 798.84s und 109.4s lang
        self.assertAlmostEqual(lt[0][0], 798.84, places=1)
        self.assertAlmostEqual(lt[0][1], 109.4, places=1)

    def test_fastest_via_pipeline(self):
        from laps import detect_laps, fastest_lap
        laps = detect_laps(self.track)
        fl = fastest_lap(laps)
        # HED: Fastest lap=1:44.040 = 104.040s
        self.assertAlmostEqual(fl["duration"], 104.040, places=2)


class Test2DRijekaQ1_400Hz(unittest.TestCase):
    """Regression suite for the v23.3 bug — MainSamplingRate=400 bundles.

    Vor dem Fix: Der Parser hatte 100 Hz hardcodiert und interpretierte den
    bmw_hp-Rate-Divisor als Dezimal. Folgen für dieses Bundle:
      • time.max() = 2201 s (Faktor 4 zu lang gegen Time2D=550 s)
      • Gear-Channel: 3.57 Hz statt 10 Hz
      • Lap-Boundaries zeigen auf falsche Sample-Indizes → GPS-Trace pro
        Runde nicht geschlossen (Stefans Symptom „kein Rundkurs im Viewer").

    Nach dem Fix (HED [DOWNLOAD]/MainSamplingRate + hex(rate_str)):
      • time.max() ≈ 550.3 s (matcht Time2D)
      • Native Rates clean: 100/50/10 Hz statt 25/12.5/3.57 Hz
      • Lap 2 (1:32.398) GPS-Trace schließt sich auf < 5 m.
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(BUNDLE_RIJEKA_Q1):
            raise unittest.SkipTest(f"Test bundle missing: {BUNDLE_RIJEKA_Q1}")
        cls.track = parse_2d(BUNDLE_RIJEKA_Q1)

    def test_meta(self):
        m = self.track["meta"]
        self.assertEqual(m["SOURCE"], "2D")
        self.assertEqual(m["VARIANT"], "bmw_hp")
        self.assertEqual(m["DATE"], "2025-08-09")
        # Lap 0 in der HED ist '0:00.000' (Outlap-Platzhalter, fällt im
        # Filter raus); verbleiben 5 sinnvolle Laps (Out-Lap, 3× Flying,
        # In-Lap).
        self.assertEqual(m["LAP_COUNT"], 5)

    def test_time_axis_matches_time2d(self):
        """Der schärfste Regression-Check: ohne den Fix war time.max() ≈ 2201 s,
        also exakt 4× zu lang. Mit Fix sollte es mit dem Time2D-Channel
        übereinstimmen, der vom Logger als Ground-Truth-Wallclock geführt wird."""
        t = self.track["time"]
        time2d = self.track["channels"]["Time2D"]["data"]
        # Output ist auf 100 Hz resampled.
        dt = np.median(np.diff(t))
        self.assertAlmostEqual(dt, 0.01, places=4)
        # Time2D ist die Logger-eigene Uhr — sollte mit unserer Zeitachse
        # übereinstimmen, sonst rechnen wir auf falscher Skala.
        self.assertAlmostEqual(t.max(), float(time2d.max()), delta=0.1)
        # Sanity: 8–10 Minuten Q1-Session, nicht 30+ Minuten.
        self.assertLess(t.max(), 700.0,
                        "time.max() suspiciously long — bist Du sicher dass "
                        "MainSamplingRate aus der HED gelesen wird?")
        self.assertGreater(t.max(), 400.0)

    def test_hex_rate_divisor(self):
        """rate_str='28' aus DDD entspricht 0x28=40, also 400/40=10 Hz.
        Vor dem Fix wurde das als dezimal=28 gelesen → 100/28=3.57 Hz."""
        chans = self.track["channels"]
        # Gear ist ein 10-Hz-Channel (rate_str='28' in [30D]).
        self.assertEqual(chans["Gear"]["rate"], 10)
        # Speed ist 100 Hz (rate_str='4' — hex==dec, fängt diesen Pfad aber
        # trotzdem ab).
        self.assertEqual(chans["Speed"]["rate"], 100)

    def test_laps_within_recording(self):
        """Letzte Runde muss innerhalb der Daten enden. Vor dem Fix endete
        Lap 4 bei t=513 s, der Datenstream ging aber bis t=2201 s — d.h.
        nach den Runden lagen >1500 s 'leerer' Datenraum, der den Viewer
        verwirrte."""
        t = self.track["time"]
        last_lap_end = max(s + d for s, d in self.track["lap_times"])
        # Letzte Runde darf den Datenstream nicht überschreiten…
        self.assertLessEqual(last_lap_end, t.max() + 1.0)
        # …und darf nicht in den ersten 25% liegen (klassisches Symptom des
        # 4×-Stretches).
        self.assertGreater(last_lap_end, t.max() * 0.7)

    def test_fastest_lap_closes_loop(self):
        """Stefans eigentliches Symptom: 'im Viewer kein Rundkurs'. Wenn
        Lap-Boundaries auf falsche Sample-Indizes zeigen, ist die GPS-Trace
        pro Runde ein offener Bogen. Wir prüfen die schnellste Flying Lap
        explizit auf Schließung."""
        t = self.track["time"]
        lat = self.track["lat"]
        lon = self.track["lon"]
        # Bei den 5 lap_times-Einträgen ist Lap 2 (idx=2 nach Filter) die
        # 1:32.398-Flying-Lap. Egal — wir suchen einfach die kürzeste, die
        # ist immer eine Flying Lap.
        laps = self.track["lap_times"]
        flying = min(laps, key=lambda sd: sd[1])
        i_start = int(round(flying[0] * 100))
        i_end = int(round((flying[0] + flying[1]) * 100))
        # Haversine-Näherung in m (Rijeka liegt bei lat≈45.4°)
        d_lat_m = (lat[i_end] - lat[i_start]) * 111_000
        d_lon_m = (lon[i_end] - lon[i_start]) * 111_000 * \
                  np.cos(np.radians(lat[i_start]))
        gap_m = np.hypot(d_lat_m, d_lon_m)
        # Start und Ende einer Runde müssen quasi identisch sein. >50 m
        # heißt ein offener Bogen — der Bug von vor v23.3.
        self.assertLess(gap_m, 50.0,
                        f"Flying-Lap GPS-Trace schließt sich nicht "
                        f"({gap_m:.1f} m Abstand) — vermutlich Time-Axis-"
                        f"Skalierung wieder falsch.")

    def test_gps_at_rijeka(self):
        """Verifiziert dass GPS-Filter & Skalierung der breiteren v21.30er
        Schutzmechanismen weiter funktionieren — Rijeka liegt bei
        45.383°N, 14.506°E."""
        lat = self.track["lat"]
        lon = self.track["lon"]
        self.assertAlmostEqual(np.median(lat), 45.383, places=2)
        self.assertAlmostEqual(np.median(lon), 14.506, places=2)



class Test2DErrors(unittest.TestCase):
    """Edge-case error handling."""

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            parse_2d("/nonexistent/path.zip")

    def test_non_2d_zip(self):
        # Build a dummy zip that doesn't contain a .MES directory
        import tempfile, zipfile
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            with zipfile.ZipFile(f.name, "w") as zf:
                zf.writestr("hello.txt", "not a 2D bundle")
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                parse_2d(path)
            self.assertIn("No 2D bundle", str(ctx.exception))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
