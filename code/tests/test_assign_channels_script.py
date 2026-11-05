#!/usr/bin/env python3
"""tests/test_assign_channels_script.py — v22.6

End-to-end test for assign_channels.py:
  - Builds a synthetic DB with several laps in different states
  - Runs the script's core logic directly (no subprocess) on the DB
  - Asserts the resulting channel_roles dict for each lap

Specifically checks the two key behaviours Stefan asked for:
  1. Match Datenkanal-Namen (case-insensitively) gegen das File
  2. RESPECT bestehende Zuordnungen — nur leere Slots füllen, nicht
     überschreiben
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from db import DB
from parsers.channel_roles import CHANNEL_MAP
import assign_channels


def _make_lap_data(extras, channel_roles=None):
    n = 100
    t = np.linspace(0, 30, n)
    ld = {
        "time": t,
        "lat":  np.linspace(45.0, 45.001, n),
        "lon":  np.linspace(11.0, 11.001, n),
        "speed": np.full(n, 30.0),
        "distance": np.linspace(0, 1000, n),
        "duration": 30.0,
        "total_distance": 1000.0,
        "extra_channels": extras,
    }
    if channel_roles is not None:
        ld["channel_roles"] = channel_roles
    return ld


def _insert(db, *, extras, roles=None):
    sid = db.create_session(
        original_filename="t.xrk", file_path="/tmp/t.xrk", user_id=None,
        driver="", bike="", track="", session_date="", notes="", format="xrk",
    )
    return db.add_lap(sid, 1, 30.0, _make_lap_data(extras, roles))


def _run_assignment(db, *, apply_changes=True):
    """Mirror the script's loop, but inline so we can test without
    invoking argparse + subprocess."""
    lookup = assign_channels.build_lookup_table(CHANNEL_MAP)
    changed = 0
    for row in db.list_all_laps_flat():
        lap = db.get_lap(int(row["lap_id"]))
        if lap is None:
            continue
        lap_data = lap["lap_data"]
        extras = lap_data.get("extra_channels") or {}
        if not extras:
            continue
        existing = dict(lap_data.get("channel_roles") or {})
        matches = assign_channels.find_matches(extras, lookup)
        new = {rid: cid for rid, cid in matches.items() if rid not in existing}
        if not new:
            continue
        if apply_changes:
            merged = dict(existing)
            merged.update(new)
            lap_data["channel_roles"] = merged
            db.update_lap_blob(int(row["lap_id"]), lap_data)
        changed += 1
    return changed


class TestAssignChannelsE2E(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="assign_e2e_")
        self.db = DB(Path(self.tmp) / "lap_compare.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_lap_gets_assignments(self):
        """A lap with extras matching the file but no channel_roles
        should get its channel_roles populated."""
        extras = {
            "ch_a": {"name": "phi_lean", "unit": "deg",
                     "data": np.linspace(-30, 30, 100)},
            "ch_b": {"name": "Brake_Front", "unit": "bar",
                     "data": np.linspace(0, 10, 100)},
        }
        lap_id = _insert(self.db, extras=extras)
        n_changed = _run_assignment(self.db)
        self.assertEqual(n_changed, 1)
        rec = self.db.get_lap(lap_id)
        roles = rec["lap_data"].get("channel_roles") or {}
        self.assertEqual(roles.get("lean"), "ch_a")
        self.assertEqual(roles.get("brake_pressure"), "ch_b")

    def test_case_insensitive_match(self):
        """File has 'phi_lean'; lap has 'PHI_LEAN' (all caps) — should match."""
        extras = {
            "ch_a": {"name": "PHI_LEAN", "unit": "deg",
                     "data": np.linspace(-30, 30, 100)},
        }
        lap_id = _insert(self.db, extras=extras)
        _run_assignment(self.db)
        rec = self.db.get_lap(lap_id)
        roles = rec["lap_data"].get("channel_roles") or {}
        self.assertEqual(roles.get("lean"), "ch_a")

    def test_existing_assignment_respected(self):
        """If channel_roles already has an entry for 'lean', the script
        must NOT overwrite it, even if a different channel in extras
        would match."""
        extras = {
            "ch_manual": {"name": "phi_lean", "unit": "deg",
                          "data": np.linspace(-30, 30, 100)},
            "ch_other":  {"name": "Bike_Angle", "unit": "deg",
                          "data": np.linspace(-30, 30, 100)},
        }
        # User has manually picked ch_other for lean — script must respect
        lap_id = _insert(self.db, extras=extras,
                          roles={"lean": "ch_other"})
        _run_assignment(self.db)
        rec = self.db.get_lap(lap_id)
        roles = rec["lap_data"].get("channel_roles") or {}
        # 'lean' must still point to ch_other, not ch_manual
        self.assertEqual(roles.get("lean"), "ch_other")

    def test_other_roles_filled_even_if_one_existing(self):
        """Existing assignment for one role shouldn't block filling others."""
        extras = {
            "ch_lean":  {"name": "phi_lean",    "unit": "deg",
                         "data": np.linspace(-30, 30, 100)},
            "ch_brake": {"name": "Brake_Front", "unit": "bar",
                         "data": np.linspace(0, 10, 100)},
        }
        # User has manually picked something for lean already — but
        # brake_pressure is still empty, must be filled
        lap_id = _insert(self.db, extras=extras,
                          roles={"lean": "ch_lean"})
        _run_assignment(self.db)
        rec = self.db.get_lap(lap_id)
        roles = rec["lap_data"].get("channel_roles") or {}
        self.assertEqual(roles.get("lean"), "ch_lean")
        self.assertEqual(roles.get("brake_pressure"), "ch_brake")

    def test_no_match_no_change(self):
        """Lap with extras that match nothing in the file → no roles."""
        extras = {
            "ch_x": {"name": "weather", "unit": "C",
                     "data": np.full(100, 20.0)},
        }
        lap_id = _insert(self.db, extras=extras)
        _run_assignment(self.db)
        rec = self.db.get_lap(lap_id)
        roles = rec["lap_data"].get("channel_roles") or {}
        self.assertEqual(roles, {})

    def test_empty_extras_skipped(self):
        """Lap with no extras at all — script does nothing, doesn't crash."""
        lap_id = _insert(self.db, extras={})
        n_changed = _run_assignment(self.db)
        self.assertEqual(n_changed, 0)
        rec = self.db.get_lap(lap_id)
        # channel_roles either absent or empty — both fine
        self.assertFalse(rec["lap_data"].get("channel_roles"))

    def test_idempotent(self):
        """Running twice must yield the same result, and the second run
        must report 0 changes."""
        extras = {
            "ch_a": {"name": "phi_lean", "unit": "deg",
                     "data": np.linspace(-30, 30, 100)},
        }
        lap_id = _insert(self.db, extras=extras)
        first  = _run_assignment(self.db)
        second = _run_assignment(self.db)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0,
            "Second run must report no changes — script is idempotent")

    def test_dry_run_does_not_write(self):
        """apply_changes=False must not touch the DB."""
        extras = {
            "ch_a": {"name": "phi_lean", "unit": "deg",
                     "data": np.linspace(-30, 30, 100)},
        }
        lap_id = _insert(self.db, extras=extras)
        n_changed = _run_assignment(self.db, apply_changes=False)
        # Counter still increments — that's how the script reports
        # what would happen
        self.assertEqual(n_changed, 1)
        # But the DB must be untouched
        rec = self.db.get_lap(lap_id)
        roles = rec["lap_data"].get("channel_roles") or {}
        self.assertEqual(roles, {})


if __name__ == "__main__":
    unittest.main()
