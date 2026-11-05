"""v21.39 — Tests for the electronics-setup analysis additions to the
channel-role registry. Pure-Python; no server needed.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from parsers.channel_roles import (
    ROLES,
    ANALYSIS_TAB_IDS,
    roles_for_analyses,
    suggest_channel,
)

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


def main():
    print("\n== Registry includes electronics tab ==")
    check("'electronics' in ANALYSIS_TAB_IDS",
          "electronics" in ANALYSIS_TAB_IDS)

    print("\n== New electronics roles exist ==")
    by_id = {r["id"]: r for r in ROLES}
    for rid in ("wheel_speed_front", "wheel_speed_rear",
                "tc_status", "wc_status"):
        check(f"role '{rid}' present", rid in by_id)
        if rid in by_id:
            check(f"role '{rid}' has electronics in analyses",
                  "electronics" in by_id[rid]["analyses"])

    print("\n== Shared roles extended to electronics ==")
    check("lean → also for electronics",
          "electronics" in by_id["lean"]["analyses"])
    check("throttle → also for electronics",
          "electronics" in by_id["throttle"]["analyses"])

    print("\n== roles_for_analyses(['electronics']) ==")
    elec_roles = roles_for_analyses(["electronics"])
    elec_ids = {r["id"] for r in elec_roles}
    expected = {"wheel_speed_front", "wheel_speed_rear",
                "tc_status", "wc_status", "throttle", "lean"}
    check(f"returns exactly the 6 expected roles ({len(elec_ids)})",
          elec_ids == expected,
          f"got {sorted(elec_ids)}")
    check("brake_pressure NOT in electronics roles",
          "brake_pressure" not in elec_ids)
    check("throttle_butterfly NOT in electronics roles",
          "throttle_butterfly" not in elec_ids)

    print("\n== suggest_channel: BMW M1000RR Race2025 names ==")
    # The 2D race2025 parser exposes channels with these German/BMW names.
    # v22.6 — Stefan's channel_map.txt no longer has DWCwork; the WC
    # Datenkanäle are now md_tgt_whly + Wheely_active. Test with one
    # of those instead.
    available = [
        {"id": "ch_V_Front",       "name": "V_Front",         "unit": "km/h"},
        {"id": "ch_V_Rear",        "name": "V_Rear",          "unit": "km/h"},
        {"id": "ch_ThrottleGrip",  "name": "ThrottleGrip",    "unit": "%"},
        {"id": "ch_LeanAngle",     "name": "LeanAngle",       "unit": "deg"},
        {"id": "ch_DTCwork",       "name": "DTCwork",         "unit": ""},
        {"id": "ch_Wheely_active", "name": "Wheely_active",   "unit": ""},
        {"id": "ch_RPM",           "name": "RPM",             "unit": "rpm"},
    ]
    sug = lambda rid: suggest_channel(by_id[rid], available)
    check("wheel_speed_front → V_Front", sug("wheel_speed_front") == "ch_V_Front")
    check("wheel_speed_rear  → V_Rear",  sug("wheel_speed_rear")  == "ch_V_Rear")
    check("throttle → ThrottleGrip",     sug("throttle") == "ch_ThrottleGrip")
    check("lean → LeanAngle",            sug("lean") == "ch_LeanAngle")
    check("tc_status → DTCwork",         sug("tc_status") == "ch_DTCwork")
    check("wc_status → Wheely_active",   sug("wc_status") == "ch_Wheely_active")

    print("\n== suggest_channel: no electronics channels in lap ==")
    # XRK-style lap without any wheelspeed/TC/WC
    avail2 = [
        {"id": "ch_p_brake_fr", "name": "p_brake_fr", "unit": "bar"},
        {"id": "ch_phi_lean",   "name": "phi_lean",   "unit": "deg"},
        {"id": "ch_altitude",   "name": "altitude",   "unit": "m"},
    ]
    check("no wheelspeed → wheel_speed_front None",
          suggest_channel(by_id["wheel_speed_front"], avail2) is None)
    check("no TC → tc_status None",
          suggest_channel(by_id["tc_status"], avail2) is None)
    check("lean still matches phi_lean",
          suggest_channel(by_id["lean"], avail2) == "ch_phi_lean")

    print(f"\n{PASS} pass, {FAIL} fail")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
