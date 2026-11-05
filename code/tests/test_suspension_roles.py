"""v22.7 — Tests for the suspension-setup analysis additions to the
channel-role registry. Analog zu test_electronics_roles.py; pure
Python, no server needed.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from parsers.channel_roles import (
    ROLES,
    ANALYSIS_TAB_IDS,
    STANDARDKANAL_TO_ROLE_ID,
    CHANNEL_MAP,
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
    print("\n== Registry includes suspension tab ==")
    check("'suspension' in ANALYSIS_TAB_IDS",
          "suspension" in ANALYSIS_TAB_IDS)

    print("\n== New suspension roles exist ==")
    by_id = {r["id"]: r for r in ROLES}
    for rid in ("suspension_fork", "suspension_shock"):
        check(f"role '{rid}' present", rid in by_id)
        if rid in by_id:
            check(f"role '{rid}' has suspension in analyses",
                  "suspension" in by_id[rid]["analyses"])
            # Suspension-Rollen werden nur von der Fahrwerks-Analyse
            # genutzt — sie tauchen nicht in anderen Tabs auf.
            check(f"role '{rid}' only in suspension analysis",
                  by_id[rid]["analyses"] == ["suspension"])

    print("\n== Standardkanal-Labels for suspension roles ==")
    check("'Federweg Gabel' maps to suspension_fork",
          STANDARDKANAL_TO_ROLE_ID.get("Federweg Gabel") == "suspension_fork")
    check("'Federweg Federbein' maps to suspension_shock",
          STANDARDKANAL_TO_ROLE_ID.get("Federweg Federbein") == "suspension_shock")
    check("'Federweg Gabel' in CHANNEL_MAP",
          "Federweg Gabel" in CHANNEL_MAP)
    check("'Federweg Federbein' in CHANNEL_MAP",
          "Federweg Federbein" in CHANNEL_MAP)

    print("\n== roles_for_analyses(['suspension']) ==")
    susp_roles = roles_for_analyses(["suspension"])
    susp_ids = {r["id"] for r in susp_roles}
    expected = {"suspension_fork", "suspension_shock"}
    check(f"returns exactly the 2 expected roles ({len(susp_ids)})",
          susp_ids == expected,
          f"got {sorted(susp_ids)}")
    check("brake_pressure NOT in suspension roles",
          "brake_pressure" not in susp_ids)
    check("throttle NOT in suspension roles",
          "throttle" not in susp_ids)
    check("wheel_speed_front NOT in suspension roles",
          "wheel_speed_front" not in susp_ids)

    print("\n== suggest_channel: Datenkanäle aus channel_map.txt ==")
    # Aus channel_map.txt (Stefan-gepflegt): Federweg Gabel = s_susp_fr,
    # ACC_SuspTravel_F, SUSF, Travel_Front, Susp_fr_ddc.  Federbein analog
    # mit s_susp_rr / ACC_SuspTravel_R / SUSR / Travel_Rear / Susp_rr_ddc.
    available = [
        {"id": "ch_s_susp_fr",       "name": "s_susp_fr",        "unit": "mm"},
        {"id": "ch_s_susp_rr",       "name": "s_susp_rr",        "unit": "mm"},
        {"id": "ch_other",           "name": "RPM",              "unit": "rpm"},
    ]
    sug = lambda rid: suggest_channel(by_id[rid], available)
    check("suspension_fork → s_susp_fr",
          sug("suspension_fork") == "ch_s_susp_fr")
    check("suspension_shock → s_susp_rr",
          sug("suspension_shock") == "ch_s_susp_rr")

    print("\n== suggest_channel: alternative names from same file ==")
    # Die anderen Aliase aus der Datei müssen ebenfalls matchen.
    available2 = [
        {"id": "ch_ACC_F",        "name": "ACC_SuspTravel_F", "unit": "mm"},
        {"id": "ch_ACC_R",        "name": "ACC_SuspTravel_R", "unit": "mm"},
        {"id": "ch_SUSF",         "name": "SUSF",             "unit": "mm"},
        {"id": "ch_SUSR",         "name": "SUSR",             "unit": "mm"},
    ]
    # First-match-Reihenfolge gemäß pattern_hints-Liste: ACC_SuspTravel_F
    # ist Index 1, SUSF ist Index 2 — suggest_channel iteriert die patterns
    # und nimmt den ersten Treffer. Wir akzeptieren beides.
    check("suspension_fork → einer der Aliase",
          suggest_channel(by_id["suspension_fork"], available2)
            in ("ch_ACC_F", "ch_SUSF"))
    check("suspension_shock → einer der Aliase",
          suggest_channel(by_id["suspension_shock"], available2)
            in ("ch_ACC_R", "ch_SUSR"))

    print("\n== suggest_channel: case-insensitive exact match ==")
    available3 = [
        {"id": "ch_lower", "name": "s_susp_fr", "unit": "mm"},   # already lowercase
        {"id": "ch_upper", "name": "SUSR",      "unit": "mm"},   # uppercase
    ]
    check("suspension_fork → 's_susp_fr'",
          suggest_channel(by_id["suspension_fork"], available3) == "ch_lower")
    check("suspension_shock → 'SUSR'",
          suggest_channel(by_id["suspension_shock"], available3) == "ch_upper")

    # Case-insensitive im engeren Sinne: Datenkanal mit anderer Case-Schreibung
    # als in der Datei trotzdem matchen.
    available3b = [
        {"id": "ch_susf_lower", "name": "susf", "unit": "mm"},   # file hat "SUSF"
    ]
    check("suspension_fork → 'susf' (case-insensitive vs file 'SUSF')",
          suggest_channel(by_id["suspension_fork"], available3b) == "ch_susf_lower")

    print("\n== suggest_channel: substring should NOT match (v22.6 anchored) ==")
    # 's_susp_fr_filtered' enthält 's_susp_fr', darf aber nicht matchen
    # weil pattern_hints jetzt anker-basiert sind (^name$).
    available4 = [
        {"id": "ch_substr", "name": "s_susp_fr_filtered", "unit": "mm"},
        {"id": "ch_other",  "name": "SUSR_raw",           "unit": "mm"},
    ]
    check("suspension_fork: no substring match for 's_susp_fr_filtered'",
          suggest_channel(by_id["suspension_fork"], available4) is None)
    check("suspension_shock: no substring match for 'SUSR_raw'",
          suggest_channel(by_id["suspension_shock"], available4) is None)

    print("\n== suggest_channel: no suspension channels in lap ==")
    available5 = [
        {"id": "ch_speed", "name": "Speed", "unit": "km/h"},
        {"id": "ch_rpm",   "name": "RPM",   "unit": "rpm"},
    ]
    check("no fork channel → suspension_fork None",
          suggest_channel(by_id["suspension_fork"], available5) is None)
    check("no shock channel → suspension_shock None",
          suggest_channel(by_id["suspension_shock"], available5) is None)

    print(f"\n{PASS} pass, {FAIL} fail")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
