"""v21.36 — Tests for db.get_channel_summary() and the three-state
badge classification used by the sessions listing.

Builds synthetic laps directly via DB methods so the test doesn't
need bundle fixtures.
"""

import os
import sys
import tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from db import DB

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))


def make_lap_data(extras: dict, channel_roles: dict | None = None):
    """Build a lap_data dict shaped like extract_lap_data() output."""
    n = 200
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


def insert_lap(db: DB, extras: dict, roles: dict | None = None) -> int:
    sid = db.create_session(
        original_filename="x", file_path="/tmp/x",
        user_id=None, driver="", bike="", track="",
        session_date="", notes="", format="xrk",
    )
    return db.add_lap(sid, 1, 30.0, make_lap_data(extras, roles))


def main():
    tmp = tempfile.mkdtemp(prefix="lap36_")
    try:
        db = DB(os.path.join(tmp, "test.db"))

        # Lap A: no extra channels at all
        a = insert_lap(db, extras={})
        # Lap B: extras present, none assigned
        ch_B = {
            "ch_p_brake_fr": {"name": "p_brake_fr", "unit": "bar",
                              "data": np.linspace(0, 10, 200)},
            "ch_phi_lean":   {"name": "phi_lean",   "unit": "deg",
                              "data": np.linspace(-30, 30, 200)},
        }
        b = insert_lap(db, extras=ch_B)
        # Lap C: extras present + partial assignment (1 of 2 matchable)
        c = insert_lap(db, extras=ch_B, roles={"lean": "ch_phi_lean"})
        # Lap D: extras present + full assignment (2 of 2 matchable)
        d = insert_lap(db, extras=ch_B, roles={
            "lean": "ch_phi_lean",
            "brake_pressure": "ch_p_brake_fr",
        })
        # Lap E: extras present but none match any registry role
        #        (battery + altitude are not matched by patterns)
        ch_E = {
            "battery":  {"name": "Batterie", "unit": "V",
                         "data": np.full(200, 12.5)},
            "altitude": {"name": "Höhe", "unit": "m",
                         "data": np.linspace(50, 55, 200)},
        }
        e = insert_lap(db, extras=ch_E)

        # --- 1) Empty list returns empty dict ---
        print("\n== Empty input ==")
        check("empty list → empty dict", db.get_channel_summary([]) == {})

        # --- 2) Single lap lookups ---
        print("\n== Per-lap counts ==")
        s = db.get_channel_summary([a, b, c, d, e])
        check("all 5 laps present", len(s) == 5)

        # total_roles is the registry size (currently 4)
        from parsers.channel_roles import ROLES as _ROLES
        total = len(_ROLES)

        check("A: extras=0", s[a]["extras_count"] == 0)
        check("A: roles=0",  s[a]["roles_count"]  == 0)
        check("A: total_roles set", s[a]["total_roles"] == total)
        # v22.3 — assigned_role_ids: sorted list of role ids that have a
        # channel assigned. Empty for laps with no assignments.
        check("A: assigned_role_ids = []",
              s[a]["assigned_role_ids"] == [])

        check("B: extras=2", s[b]["extras_count"] == 2)
        check("B: roles=0",  s[b]["roles_count"]  == 0)
        check("B: total_roles set", s[b]["total_roles"] == total)
        check("B: assigned_role_ids = []",
              s[b]["assigned_role_ids"] == [])

        check("C: extras=2", s[c]["extras_count"] == 2)
        check("C: roles=1",  s[c]["roles_count"]  == 1)
        check("C: assigned_role_ids = ['lean']",
              s[c]["assigned_role_ids"] == ["lean"])

        check("D: extras=2", s[d]["extras_count"] == 2)
        check("D: roles=2",  s[d]["roles_count"]  == 2)
        # Sorted alphabetically — brake_pressure < lean.
        check("D: assigned_role_ids sorted",
              s[d]["assigned_role_ids"] == ["brake_pressure", "lean"])

        check("E: extras=2", s[e]["extras_count"] == 2)
        check("E: roles=0",  s[e]["roles_count"]  == 0)
        check("E: assigned_role_ids = []",
              s[e]["assigned_role_ids"] == [])

        # --- 3) Four-state badge classification ---
        # 'full'      iff roles_count >= total_roles
        # 'partial'   iff 0 < roles_count < total_roles
        # 'untouched' iff roles_count == 0 (but extras > 0)
        # 'none'      iff extras_count == 0
        # Pattern-matching is intentionally NOT part of the classification.
        print("\n== Badge classification ==")
        def classify(entry):
            ex = entry["extras_count"]; ro = entry["roles_count"]
            tot = entry["total_roles"]
            if ex == 0:
                return "none"
            if tot > 0 and ro >= tot:
                return "full"
            if ro == 0:
                return "untouched"
            return "partial"

        check("A (no extras) → none",            classify(s[a]) == "none")
        check("B (0 of 4) → untouched",          classify(s[b]) == "untouched")
        check("C (1 of 4) → partial",            classify(s[c]) == "partial")
        check("D (2 of 4) → partial",            classify(s[d]) == "partial")
        check("E (extras but 0 roles) → untouched",
              classify(s[e]) == "untouched")

        # Build a synthetic 'F': all 4 registry roles assigned (any
        # channel ids — pattern match is irrelevant for the badge).
        # We assign even to channels that don't match the role patterns
        # to confirm the simplified rule.
        all_roles_assigned = {r["id"]: "ch_p_brake_fr" for r in _ROLES}
        f = insert_lap(db, extras=ch_B, roles=all_roles_assigned)
        sf = db.get_channel_summary([f])[f]
        check("F: roles_count == total_roles", sf["roles_count"] == total)
        check("F → full", classify(sf) == "full")

        # And 'G': roles dict carries unknown role-ids — those would
        # have been sanitised at write time, but the DB just counts.
        # This verifies get_channel_summary is a pure counter, no
        # validation. Document the behaviour so a future caller knows.
        g = insert_lap(db, extras=ch_B,
                       roles={**all_roles_assigned, "made_up": "ch_x"})
        sg = db.get_channel_summary([g])[g]
        check("G: count includes any keys (no validation in DB)",
              sg["roles_count"] == total + 1)
        check("G → full (over-count still ≥ total)",
              classify(sg) == "full")

        # --- 4) Robustness: missing lap_id silently absent in result ---
        print("\n== Missing lap_id ==")
        s2 = db.get_channel_summary([a, 999999])
        check("known id present", a in s2)
        check("unknown id absent", 999999 not in s2)

        # --- 5) Result mutating roles_count must reflect blob change ---
        print("\n== Update reflects in summary ==")
        # Read the lap, mutate roles, write back
        row = db.get_lap(d)
        ld = row["lap_data"]
        del ld["channel_roles"]  # clear all
        db.update_lap_blob(d, ld)
        s3 = db.get_channel_summary([d])
        check("after clearing roles, roles_count=0",
              s3[d]["roles_count"] == 0)
        check("after clearing roles, assigned_role_ids=[]",
              s3[d]["assigned_role_ids"] == [])
        check("total_roles unchanged",
              s3[d]["total_roles"] == total)

        print(f"\n{PASS} pass, {FAIL} fail")
        return 0 if FAIL == 0 else 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
