#!/usr/bin/env python3
"""tests/test_track_case_insensitive.py — v22.2

Verifies the two requirements:
  (1) Track filter in query_laps is case-insensitive.
  (2) canonical_track_name() returns the existing spelling when one with
      matching lower-case already exists; otherwise returns the input.
      Used at upload save + session edit so we don't fork the same track
      into multiple casing variants.

DB-level tests only — webserver wiring is exercised by manual run; the
behaviour we care about lives in canonical_track_name() + the SQL filter.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import db as db_mod


def _fresh_db():
    """Return a DB instance backed by a fresh tempfile path. Caller is
    responsible for cleaning up the tempdir (we keep the tempdir alive on
    the returned object for that)."""
    tmpdir = tempfile.mkdtemp()
    d = db_mod.DB(Path(tmpdir) / "test.db")
    d._test_tmpdir = tmpdir  # for cleanup
    return d


def _add_session(d, *, track, driver="X", bike="Y"):
    return d.create_session(
        original_filename=f"{track or 'none'}.xrk",
        file_path=f"/tmp/{track or 'none'}.xrk",
        user_id=None, driver=driver, bike=bike, track=track,
    )


def _add_lap(d, session_id, *, lap_number=1, duration=90.0):
    # Minimal lap_data — query_laps doesn't need anything in the blob.
    d.add_lap(session_id, lap_number, duration, {"placeholder": True})


class TestCanonicalTrackName(unittest.TestCase):
    def setUp(self):
        self.d = _fresh_db()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d._test_tmpdir, ignore_errors=True)

    def test_empty_returns_empty(self):
        self.assertEqual(self.d.canonical_track_name(""), "")
        self.assertEqual(self.d.canonical_track_name("   "), "")

    def test_no_match_returns_input(self):
        # Empty DB — input passes through (after strip).
        self.assertEqual(self.d.canonical_track_name("Hockenheim"), "Hockenheim")
        self.assertEqual(self.d.canonical_track_name("  Nürburgring  "),
                         "Nürburgring")

    def test_existing_session_snaps_casing(self):
        _add_session(self.d, track="Hockenheim")
        # Three different casings — all snap to the stored spelling.
        self.assertEqual(self.d.canonical_track_name("hockenheim"), "Hockenheim")
        self.assertEqual(self.d.canonical_track_name("HOCKENHEIM"), "Hockenheim")
        self.assertEqual(self.d.canonical_track_name("HoCkEnHeIm"), "Hockenheim")
        # Exact match: identity.
        self.assertEqual(self.d.canonical_track_name("Hockenheim"), "Hockenheim")

    def test_unrelated_track_not_affected(self):
        _add_session(self.d, track="Hockenheim")
        # Unrelated input is unchanged.
        self.assertEqual(self.d.canonical_track_name("Salzburgring"),
                         "Salzburgring")

    def test_first_inserted_wins(self):
        # If somehow two casings already exist (legacy data), the earliest
        # by created_at wins — deterministic.
        _add_session(self.d, track="Hockenheim")
        _add_session(self.d, track="HOCKENHEIM")
        self.assertEqual(self.d.canonical_track_name("hockenheim"), "Hockenheim")

    def test_empty_track_in_db_ignored(self):
        # Sessions without a track must not poison the lookup — otherwise
        # "" + LOWER("anything") would match? Actually no: LOWER('')!=LOWER('X').
        # But we still guard with `track != ''` for clarity; verify the
        # guard doesn't break the positive case.
        _add_session(self.d, track="")
        _add_session(self.d, track="Hockenheim")
        self.assertEqual(self.d.canonical_track_name("hockenheim"), "Hockenheim")


class TestQueryLapsCaseInsensitive(unittest.TestCase):
    def setUp(self):
        self.d = _fresh_db()
        # Three sessions, mixed casing, each with one lap.
        for i, name in enumerate(("Hockenheim", "hockenheim", "HOCKENHEIM")):
            sid = _add_session(self.d, track=name)
            _add_lap(self.d, sid, lap_number=i + 1, duration=90.0 + i)
        # One unrelated session — must not appear in track-filtered queries.
        sid = _add_session(self.d, track="Salzburgring")
        _add_lap(self.d, sid, lap_number=1, duration=85.0)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d._test_tmpdir, ignore_errors=True)

    def test_filter_lowercase_matches_all_casings(self):
        rows = self.d.query_laps(track="hockenheim")
        self.assertEqual(len(rows), 3)
        # All three casings present.
        tracks = sorted(r["track"] for r in rows)
        self.assertEqual(tracks, ["HOCKENHEIM", "Hockenheim", "hockenheim"])

    def test_filter_uppercase_matches_all_casings(self):
        rows = self.d.query_laps(track="HOCKENHEIM")
        self.assertEqual(len(rows), 3)

    def test_filter_titlecase_matches_all_casings(self):
        rows = self.d.query_laps(track="Hockenheim")
        self.assertEqual(len(rows), 3)

    def test_filter_excludes_unrelated_track(self):
        rows = self.d.query_laps(track="hockenheim")
        self.assertTrue(all(r["track"].lower() == "hockenheim" for r in rows))
        # The Salzburgring lap is gone.
        self.assertFalse(any(r["track"] == "Salzburgring" for r in rows))

    def test_filter_no_match_returns_empty(self):
        rows = self.d.query_laps(track="Nordschleife")
        self.assertEqual(rows, [])


class TestCanonicalThenStore(unittest.TestCase):
    """End-to-end at the DB-layer level: simulate what webserver does on
    upload save / session edit — canonicalise first, then store. After
    several casings the sessions table should contain only one spelling."""

    def setUp(self):
        self.d = _fresh_db()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d._test_tmpdir, ignore_errors=True)

    def test_subsequent_uploads_inherit_first_casing(self):
        first = "Hockenheim"
        # First upload sets the canonical spelling.
        canon = self.d.canonical_track_name(first)
        self.assertEqual(canon, first)
        _add_session(self.d, track=canon)
        # User types it differently three more times.
        for user_typed in ("hockenheim", "HOCKENHEIM", "hOcKeNhEiM"):
            canon = self.d.canonical_track_name(user_typed)
            self.assertEqual(canon, first)
            _add_session(self.d, track=canon)
        # All four sessions store the same spelling — exactly one distinct.
        sessions = self.d.list_sessions()
        distinct = {s["track"] for s in sessions}
        self.assertEqual(distinct, {"Hockenheim"})

    def test_distinct_values_collapses(self):
        # distinct_values() is what the dropdown is built from — after
        # canonicalisation it should show one entry, not three.
        for raw in ("Hockenheim", "hockenheim", "HOCKENHEIM"):
            canon = self.d.canonical_track_name(raw)
            _add_session(self.d, track=canon)
        dv = self.d.distinct_values()
        self.assertEqual(dv["track"], ["Hockenheim"])


if __name__ == "__main__":
    unittest.main()
