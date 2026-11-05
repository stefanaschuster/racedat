"""v21.34 — Tests for the channel_roles registry and the upload→save
round-trip that persists role assignments into lap_data.

Runs without bundle fixtures: we build synthetic `track` dicts that
mirror what the parsers would produce, so the test suite stays
hermetic.
"""

import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from parsers.channel_roles import (
    ROLES,
    ANALYSIS_TAB_IDS,
    roles_for_analyses,
    suggest_channel,
    build_available_extras,
    sanitise_assignment,
)
from laps import extract_lap_data


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------

def test_registry_shape():
    print("\n== Registry shape ==")
    check("4+ roles in registry", len(ROLES) >= 4, f"got {len(ROLES)}")
    role_ids = [r["id"] for r in ROLES]
    check("role ids unique", len(role_ids) == len(set(role_ids)))
    for r in ROLES:
        for key in ("id", "label", "description",
                    "unit_hints", "pattern_hints", "analyses"):
            check(f"role {r.get('id','?')} has '{key}'", key in r)
        check(f"role {r['id']} analyses ⊂ ANALYSIS_TAB_IDS",
              set(r["analyses"]).issubset(set(ANALYSIS_TAB_IDS)))


def test_required_roles_filter():
    print("\n== roles_for_analyses() filter ==")
    all_roles = roles_for_analyses()
    check("default returns all roles", len(all_roles) == len(ROLES))
    brake_roles = roles_for_analyses(["brake"])
    brake_ids = {r["id"] for r in brake_roles}
    check("brake includes brake_pressure", "brake_pressure" in brake_ids)
    check("brake includes lean", "lean" in brake_ids)
    check("brake excludes throttle", "throttle" not in brake_ids)
    check("brake excludes throttle_butterfly",
          "throttle_butterfly" not in brake_ids)
    accel_roles = roles_for_analyses(["accel"])
    check("accel includes throttle",
          "throttle" in {r["id"] for r in accel_roles})
    check("accel excludes brake_pressure",
          "brake_pressure" not in {r["id"] for r in accel_roles})


# ---------------------------------------------------------------------------
# build_available_extras — both modes
# ---------------------------------------------------------------------------

def test_build_available_from_xrk_like_track():
    print("\n== build_available_extras (xrk-like track) ==")
    # Synthetic track with track['channels'] dict (xrk style)
    n = 100
    t = np.linspace(0, 10.0, n)
    track = {
        "time": t,
        "lat":  np.linspace(45.0, 45.1, n),
        "lon":  np.linspace(11.0, 11.1, n),
        "speed": np.linspace(0, 100, n),
        "channels": {
            "p_brake_fr":  {"time": t, "data": np.linspace(0, 10, n), "unit": "bar"},
            "phi_lean":    {"time": t, "data": np.linspace(-30, 30, n), "unit": "deg"},
            "tp_2":        {"time": t, "data": np.linspace(0, 100, n), "unit": "%"},
            "tpd":         {"time": t, "data": np.linspace(0, 100, n), "unit": "%"},
            "E_oilTemp":   {"time": t, "data": np.full(n, 90), "unit": "C"},  # noise
            "CAN_DME":     {"time": t, "data": np.zeros(n), "unit": ""},      # noise
        },
    }
    extras = build_available_extras(track)
    ids = [c["id"] for c in extras]
    check("p_brake_fr exposed as ch_p_brake_fr",
          "ch_p_brake_fr" in ids, f"ids={ids}")
    check("phi_lean exposed", "ch_phi_lean" in ids)
    check("tp_2 exposed", "ch_tp_2" in ids)
    check("tpd exposed", "ch_tpd" in ids)
    check("E_oilTemp filtered (noise prefix)", "ch_E_oilTemp" not in ids)
    check("CAN_DME filtered (noise prefix)", "ch_CAN_DME" not in ids)
    # Verify shape
    for c in extras:
        check(f"extra {c['id']} has name+unit",
              "name" in c and "unit" in c)


def test_build_available_from_top_level_track():
    print("\n== build_available_extras (racebox-like flat track) ==")
    n = 50
    track = {
        "time":     np.linspace(0, 5, n),
        "lat":      np.linspace(45.0, 45.1, n),
        "lon":      np.linspace(11.0, 11.1, n),
        "speed":    np.linspace(0, 100, n),
        "altitude": np.linspace(50, 55, n),
        "gforce_x": np.zeros(n),
        "gforce_y": np.zeros(n),
    }
    extras = build_available_extras(track)
    ids = {c["id"] for c in extras}
    check("altitude exposed", "altitude" in ids)
    check("gforce_x exposed", "gforce_x" in ids)
    check("gyro_x not present (absent in track)", "gyro_x" not in ids)


# ---------------------------------------------------------------------------
# suggest_channel — pattern matching
# ---------------------------------------------------------------------------

def test_suggest_brake_pressure():
    print("\n== suggest_channel for BREMSDRUCK ==")
    available = [
        {"id": "ch_p_brake_fr", "name": "p_brake_fr",  "unit": "bar"},
        {"id": "ch_phi_lean",   "name": "phi_lean",    "unit": "deg"},
        {"id": "ch_v_gps",      "name": "v_GPS",       "unit": "km/h"},
    ]
    role = next(r for r in ROLES if r["id"] == "brake_pressure")
    sug = suggest_channel(role, available)
    check("suggests p_brake_fr", sug == "ch_p_brake_fr", f"got {sug}")


def test_suggest_lean_from_2d_naming():
    print("\n== suggest_channel for SCHRÄGLAGE (2D-race2025 naming) ==")
    available = [
        {"id": "ch_RPM",         "name": "RPM",         "unit": "rpm"},
        {"id": "ch_LeanAngle",   "name": "LeanAngle",   "unit": "deg"},
        {"id": "ch_ThrottleGrip","name": "ThrottleGrip","unit": "%"},
    ]
    role = next(r for r in ROLES if r["id"] == "lean")
    check("LeanAngle matched",
          suggest_channel(role, available) == "ch_LeanAngle")


def test_suggest_throttle_grip_vs_butterfly():
    print("\n== suggest_channel disambiguates grip vs. butterfly ==")
    # v22.6 — Stefan's channel_map.txt has reassigned the throttle
    # name conventions: 'tpd' is now Gasgriff (grip), 'tp_1' is
    # Drosselklappe (butterfly). The disambiguation test still holds:
    # a lap with both channels must route them to different roles.
    available = [
        {"id": "ch_tpd",  "name": "tpd",  "unit": "%"},   # → throttle (grip)
        {"id": "ch_tp_1", "name": "tp_1", "unit": "%"},   # → throttle_butterfly
    ]
    role_t = next(r for r in ROLES if r["id"] == "throttle")
    role_b = next(r for r in ROLES if r["id"] == "throttle_butterfly")
    check("throttle (grip) → tpd",
          suggest_channel(role_t, available) == "ch_tpd")
    check("throttle_butterfly → tp_1",
          suggest_channel(role_b, available) == "ch_tp_1")


def test_suggest_none_when_no_match():
    print("\n== suggest_channel returns None for unmatched roles ==")
    available = [
        {"id": "ch_altitude", "name": "altitude", "unit": "m"},
        {"id": "ch_battery",  "name": "battery",  "unit": "V"},
    ]
    role = next(r for r in ROLES if r["id"] == "brake_pressure")
    check("no brake match → None", suggest_channel(role, available) is None)


def test_suggest_empty_available():
    print("\n== suggest_channel with empty available ==")
    role = next(r for r in ROLES if r["id"] == "lean")
    check("empty → None", suggest_channel(role, []) is None)


# ---------------------------------------------------------------------------
# sanitise_assignment
# ---------------------------------------------------------------------------

def test_sanitise_drops_unknown_roles():
    print("\n== sanitise_assignment filtering ==")
    out = sanitise_assignment(
        {"lean": "ch_phi_lean", "made_up_role": "ch_foo"},
        ["ch_phi_lean", "ch_foo"],
    )
    check("known role kept", out.get("lean") == "ch_phi_lean")
    check("unknown role dropped", "made_up_role" not in out)


def test_sanitise_drops_missing_channels():
    out = sanitise_assignment(
        {"lean": "ch_phi_lean", "throttle": "ch_does_not_exist"},
        ["ch_phi_lean"],
    )
    check("missing channel dropped", "throttle" not in out)
    check("present channel kept", out.get("lean") == "ch_phi_lean")


def test_sanitise_drops_empty():
    out = sanitise_assignment({"lean": "", "throttle": None}, ["ch_x"])
    check("empty value dropped", out == {})


def test_sanitise_handles_none_input():
    check("None input → {}", sanitise_assignment(None, ["ch_x"]) == {})


# ---------------------------------------------------------------------------
# Round-trip — synthetic upload → save → reload
# ---------------------------------------------------------------------------

def test_round_trip_assignment_persists():
    print("\n== Round-trip: assignment persists in lap_data ==")
    # Build a synthetic XRK-like track with two laps via finish_line method
    n = 1000
    t = np.linspace(0.0, 60.0, n)
    track = {
        "time": t,
        "lat":  np.linspace(45.0, 45.001, n),
        "lon":  np.linspace(11.0, 11.001, n),
        "speed": np.full(n, 30.0),
        "channels": {
            "p_brake_fr": {"time": t, "data": np.linspace(0, 12, n), "unit": "bar"},
            "phi_lean":   {"time": t, "data": np.linspace(-30, 30, n), "unit": "deg"},
        },
        "meta": {"DATE": "2026-05-15", "RACER": "Stefan",
                 "VEHICLE": "M1000RR", "TRACK": "Test"},
        "source_file": "synthetic.xrk",
    }
    # Synthetic lap entry (finish_line method)
    lap = {
        "lap_index": 1,
        "method": "finish_line",
        "start_idx": 0,
        "end_idx": n - 2,
        "start_time": 0.0,
        "duration": 59.94,  # close to t[-1]
    }
    lap_data = extract_lap_data(track, lap)
    check("lap_data has extra_channels with phi_lean",
          "ch_phi_lean" in (lap_data.get("extra_channels") or {}))
    # Simulate user assignment from upload form
    raw = {"brake_pressure": "ch_p_brake_fr", "lean": "ch_phi_lean",
           "throttle": ""}
    available_ids = [c["id"] for c in
                     build_available_extras(track, lap_data=lap_data)]
    san = sanitise_assignment(raw, available_ids)
    check("brake_pressure persisted", san.get("brake_pressure") == "ch_p_brake_fr")
    check("lean persisted", san.get("lean") == "ch_phi_lean")
    check("empty throttle dropped", "throttle" not in san)
    # Stuff into lap_data the way step2_save_session does
    lap_data["channel_roles"] = san
    # Now the Coach payload should expose it
    from report_single import compute_single_lap_payload
    payload = compute_single_lap_payload(
        track=track, lap_meta=lap, lap_data=lap_data,
    )
    check("payload exposes channel_roles",
          payload.get("channel_roles") == san)


def test_legacy_lap_no_channel_roles():
    print("\n== Round-trip: legacy lap without channel_roles still works ==")
    n = 500
    t = np.linspace(0.0, 30.0, n)
    track = {
        "time": t, "lat": np.linspace(45.0, 45.001, n),
        "lon": np.linspace(11.0, 11.001, n),
        "speed": np.full(n, 30.0),
        "channels": {},
        "meta": {}, "source_file": "x",
    }
    lap = {"lap_index": 1, "method": "finish_line",
           "start_idx": 0, "end_idx": n - 2,
           "start_time": 0.0, "duration": float(t[-1])}
    lap_data = extract_lap_data(track, lap)
    # No channel_roles key — must default to empty dict, no crash
    from report_single import compute_single_lap_payload
    payload = compute_single_lap_payload(
        track=track, lap_meta=lap, lap_data=lap_data,
    )
    check("legacy lap → empty channel_roles",
          payload.get("channel_roles") == {})


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_registry_shape()
    test_required_roles_filter()
    test_build_available_from_xrk_like_track()
    test_build_available_from_top_level_track()
    test_suggest_brake_pressure()
    test_suggest_lean_from_2d_naming()
    test_suggest_throttle_grip_vs_butterfly()
    test_suggest_none_when_no_match()
    test_suggest_empty_available()
    test_sanitise_drops_unknown_roles()
    test_sanitise_drops_missing_channels()
    test_sanitise_drops_empty()
    test_sanitise_handles_none_input()
    test_round_trip_assignment_persists()
    test_legacy_lap_no_channel_roles()
    print(f"\n{PASS} pass, {FAIL} fail")
    sys.exit(0 if FAIL == 0 else 1)
