"""Channel-role registry.

Single source of truth for the per-channel ROLES that the AI Coach
analyses need (Bremsdruck, Schräglage, Throttle, ...). Both the
session-upload UI (step 2) and coach.py read from this registry so
that adding a new analysis (or extending an existing one) only
requires a single edit here — the upload picker and the Coach SPA
adapt automatically.

Why this exists (v21.34):
    Stefan wants the role-to-channel mapping resolved ONCE at upload
    time. Before this module, each Coach tab had its own SPECS list,
    duplicated in 4 places, and the user had to re-pick the same
    channels in every Coach tab. Now:
      1. Upload step 2 shows ONE assignment block listing every role
         any analysis uses, the user picks (optional), and the
         choices are persisted in lap_data['channel_roles'].
      2. The Coach pre-fills its slot UI from that dict, so existing
         behaviour (per-tab override) is preserved but the default
         state is already populated for the user.

Adding a new analysis:
    - Append a tab id to the ANALYSIS_TAB_IDS constant.
    - For each role the new analysis consumes: either reuse an
      existing role in ROLES (just add the tab id to its 'analyses'
      list) or append a new entry to ROLES.
    - No edits needed in webserver.py or coach.py — both pull the
      registry at request time.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


# Stable identifiers of the Coach analysis tabs. New analyses get a
# new id appended here. The frontend Coach uses these exact strings
# as tab keys, so don't rename without also updating coach.py.
ANALYSIS_TAB_IDS: List[str] = ["brake", "accel", "adv-brake", "adv-accel",
                                "electronics", "suspension"]


# Channel roles consumed by one or more analyses. Each entry:
#   id            — stable role id (used as form-field key and in
#                   the lap_data['channel_roles'] dict)
#   label         — human-readable label shown in the upload UI
#   description   — one-liner explaining what the channel is used for
#   unit_hints    — list of unit strings (lowercase) considered good
#                   matches; empty list disables unit filtering
#   pattern_hints — list of regex pattern strings (case-insensitive,
#                   matched against the channel's *name* field — for
#                   XRK these are e.g. 'phi_lean', for 2D bundles
#                   'LeanAngle', etc.); used for auto-suggestion
#   analyses      — list of ANALYSIS_TAB_IDS that consume this role
#
# When the same physical channel feeds two analyses (e.g. Bremsdruck
# in both 'brake' and 'adv-brake'), it's one role here with both tab
# ids in 'analyses'.
ROLES: List[Dict[str, Any]] = [
    {
        "id":            "brake_pressure",
        "label":         "BREMSDRUCK",
        "description":   "Hydraulischer Bremsdruck vorne (für Bremsanalyse)",
        "unit_hints":    ["bar", "psi", "kpa"],
        "pattern_hints": [r"^p_brake(_fr)?$", r"brake.*press", r"brk.*press",
                          r"fbrakewheelpress", r"fbrakedriverpres"],
        "analyses":      ["brake", "adv-brake"],
    },
    {
        "id":            "lean",
        "label":         "SCHRÄGLAGE",
        "description":   "Roll-/Schräglagen-Winkel (Brems-, Beschleunigungs- "
                         "und Elektronik-Analyse)",
        "unit_hints":    ["deg", "°", "rad"],
        "pattern_hints": [r"^phi_lean$", r"lean.?angle", r"^roll$",
                          r"bank_abs", r"^banking$"],
        "analyses":      ["brake", "accel", "adv-brake", "adv-accel",
                          "electronics"],
    },
    {
        "id":            "throttle",
        "label":         "GASGRIFF",
        "description":   "Gasgriff-Position (für Beschleunigungs- und "
                         "Elektronik-Analyse)",
        "unit_hints":    ["%"],
        "pattern_hints": [r"^tp_2$", r"throttle.*grip", r"^thr_grip$",
                          r"^thr$", r"^throttle$", r"throttlegrip"],
        "analyses":      ["accel", "adv-accel", "electronics"],
    },
    {
        "id":            "throttle_butterfly",
        "label":         "DROSSELKLAPPE",
        "description":   "Stellung der Drosselklappe (nur Fortgeschritten-Beschleunigung)",
        "unit_hints":    ["%"],
        "pattern_hints": [r"^tpd$", r"throttle.*butterfly", r"^thr_pos$",
                          r"^tps$", r"throttleh", r"throttlev"],
        "analyses":      ["adv-accel"],
    },
    # v21.39 — Elektronik-Setup-Analyse Rollen
    {
        "id":            "wheel_speed_front",
        "label":         "DREHZAHL VORDERRAD",
        "description":   "Geschwindigkeit Vorderrad (Slip-/Lockup-Erkennung)",
        "unit_hints":    ["km/h", "kmh", "mph", "m/s", "rpm"],
        "pattern_hints": [r"^v_front$", r"vehiclespeed.*front", r"^wsf$",
                          r"wheel.*front", r"front.*wheel.*speed",
                          r"^v_vorne$", r"^vfront$", r"^speed_front$"],
        "analyses":      ["electronics"],
    },
    {
        "id":            "wheel_speed_rear",
        "label":         "DREHZAHL HINTERRAD",
        "description":   "Geschwindigkeit Hinterrad (Slip-/Lockup-Erkennung, "
                         "Schwankungs-Erkennung)",
        "unit_hints":    ["km/h", "kmh", "mph", "m/s", "rpm"],
        "pattern_hints": [r"^v_rear$", r"vehiclespeed.*rear", r"^wsr$",
                          r"wheel.*rear", r"rear.*wheel.*speed",
                          r"^v_hinten$", r"^vrear$", r"^speed_rear$"],
        "analyses":      ["electronics"],
    },
    {
        "id":            "tc_status",
        "label":         "STATUS TC",
        "description":   "Status Traction Control "
                         "(Aktivierungen werden als Eingriffe markiert)",
        "unit_hints":    [],
        "pattern_hints": [r"dtcwork", r"^tc_status$", r"^tc$",
                          r"traction.*control", r"^dtc$",
                          r"^tcstatus$", r"tc_active", r"tcwork"],
        "analyses":      ["electronics"],
    },
    {
        "id":            "wc_status",
        "label":         "STATUS WC",
        "description":   "Status Wheelie Control "
                         "(Aktivierungen werden als Eingriffe markiert)",
        "unit_hints":    [],
        "pattern_hints": [r"dwcwork", r"^wc_status$", r"^wc$",
                          r"wheelie.*control", r"^dwc$",
                          r"^wcstatus$", r"wc_active", r"wcwork"],
        "analyses":      ["electronics"],
    },
    # v22.7 — Fahrwerks-Setup-Analyse Rollen
    {
        "id":            "suspension_fork",
        "label":         "FEDERWEG GABEL",
        "description":   "Federweg-Sensor Gabel "
                         "(für Block-Erkennung und Geschwindigkeits-Histogramm)",
        "unit_hints":    ["mm", "cm", "%"],
        "pattern_hints": [r"^s_susp_fr$", r"^ACC_SuspTravel_F$", r"^SUSF$",
                          r"^Travel_Front$", r"^Susp_fr_ddc$"],
        "analyses":      ["suspension"],
    },
    {
        "id":            "suspension_shock",
        "label":         "FEDERWEG FEDERBEIN",
        "description":   "Federweg-Sensor Federbein hinten "
                         "(für Block-Erkennung und Geschwindigkeits-Histogramm)",
        "unit_hints":    ["mm", "cm", "%"],
        "pattern_hints": [r"^s_susp_rr$", r"^ACC_SuspTravel_R$", r"^SUSR$",
                          r"^Travel_Rear$", r"^Susp_rr_ddc$"],
        "analyses":      ["suspension"],
    },
]


# ---------------------------------------------------------------------------
# v22.6 — Standardkanal/Datenkanal-Mapping aus parsers/channel_map.txt
# ---------------------------------------------------------------------------
# Stefan: "Ab sofort nennen wir den Kanal in der Analyse immer 'Standardkanal'
# und die Kanäle in den Runden 'Datenkanal'." Die Datei `channel_map.txt`
# (Format: 'Standardkanal\tDatenkanal1, Datenkanal2, …' pro Zeile) ist die
# Quelle der Wahrheit für die pattern_hints der Rollen. Beim Modul-Import
# wird die Datei gelesen und die pattern_hints jeder Rolle entsprechend
# überschrieben — der Datei-Channel-Name `Lean_Angle` wird zu einem
# case-insensitiven Exakt-Match-Pattern `^Lean_Angle$`.
#
# Damit hat die alte regex-basierte Heuristik einen einfacheren, vom
# User pflegbaren Ersatz. Die ROLES-Liste oben behält ihre Werte als
# Fallback — wenn die Datei fehlt oder nicht parsebar ist, läuft alles
# wie vorher.

# Mapping: Standardkanal-Label (deutsch, wie in der Datei) → role_id.
# Stabil — neue Rollen müssen hier auftauchen, sonst werden sie aus der
# Datei ignoriert.
STANDARDKANAL_TO_ROLE_ID: Dict[str, str] = {
    "Schräglage":         "lean",
    "Bremsdruck":         "brake_pressure",
    "Gasgriff":           "throttle",
    "Drosselklappe":      "throttle_butterfly",
    "Drehzahl Vorderrad": "wheel_speed_front",
    "Drehzahl Hinterrad": "wheel_speed_rear",
    "Status TC":          "tc_status",
    "Status WC":          "wc_status",
    "Federweg Gabel":     "suspension_fork",
    "Federweg Federbein": "suspension_shock",
}


def parse_channel_map(text: str) -> Dict[str, List[str]]:
    """Parse the Standardkanal/Datenkanal mapping file.

    Format: tab- or multi-space-separated, first column is the German
    Standardkanal label, second column is a comma-separated list of
    Datenkanal names. Empty lines and the header row are skipped.

    Returns {standardkanal_label: [datenkanal_name, ...]}.

    Defensive against minor format issues — lines with only one column,
    extra whitespace, BOM, trailing commas all handled. Unknown labels
    (not in STANDARDKANAL_TO_ROLE_ID) are kept in the dict; the caller
    decides what to do with them.
    """
    result: Dict[str, List[str]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        # Header row: starts with "Standardkanal" (any case) — skip
        if line.lower().startswith("standardkanal"):
            continue
        # Split on first tab; if no tab, fall back to 2+ spaces
        if "\t" in line:
            label, rest = line.split("\t", 1)
        else:
            m = re.match(r"^(\S(?:[^\s]| (?! ))*)\s{2,}(.+)$", line)
            if not m:
                continue
            label, rest = m.group(1), m.group(2)
        label = label.strip()
        names = [n.strip() for n in rest.split(",") if n.strip()]
        if label and names:
            result[label] = names
    return result


def _apply_channel_map_to_roles(mapping: Dict[str, List[str]]) -> int:
    """Overwrite each role's pattern_hints with the names from the
    Standardkanal/Datenkanal mapping. Returns the number of roles
    updated. Roles whose Standardkanal-Label isn't in the mapping
    keep their original pattern_hints (fallback).

    Each Datenkanal name becomes a case-insensitive exact-match pattern
    `^name$` (regex special chars escaped). Exact matches are what the
    user expects from a hand-curated list — substring/regex was
    confusing and led to false positives.
    """
    role_by_id = {r["id"]: r for r in ROLES}
    updated = 0
    for label, names in mapping.items():
        rid = STANDARDKANAL_TO_ROLE_ID.get(label)
        if not rid or rid not in role_by_id:
            continue
        role_by_id[rid]["pattern_hints"] = [
            r"^" + re.escape(n) + r"$" for n in names
        ]
        updated += 1
    return updated


# Lade die Datei (best-effort, niemals krachen — Tests laufen sonst nicht
# aus tempdirs). Die Datei liegt im gleichen Verzeichnis wie dieses Modul.
import os as _os
_CHANNEL_MAP_PATH = _os.path.join(_os.path.dirname(__file__), "channel_map.txt")
try:
    with open(_CHANNEL_MAP_PATH, "r", encoding="utf-8") as _fh:
        _parsed_map = parse_channel_map(_fh.read())
    CHANNEL_MAP: Dict[str, List[str]] = _parsed_map
    _apply_channel_map_to_roles(_parsed_map)
except FileNotFoundError:
    CHANNEL_MAP = {}
except Exception:
    # Bei Parse-Fehlern still bleiben und mit den hardcoded patterns
    # weiterlaufen. Production-Operator wird's nicht merken; Test-Suite
    # tritt das eigene Modul mit eigenen Daten.
    CHANNEL_MAP = {}


def roles_for_analyses(tab_ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Return the roles required by the given analyses (or all if None).

    Filtering by analysis id makes it possible to render a subset of
    the registry (e.g. only the 'brake' tab's roles in a hypothetical
    per-tab picker), but the upload UI always passes None and shows
    every role across all analyses.
    """
    if tab_ids is None:
        return list(ROLES)
    wanted = set(tab_ids)
    return [r for r in ROLES if wanted & set(r.get("analyses") or [])]


def suggest_channel(role: Dict[str, Any],
                    available: List[Dict[str, Any]]) -> Optional[str]:
    """Return the best-matching channel id from `available`, or None.

    `available` is a list of {'id', 'name', 'unit', ...} entries as
    produced by build_available_extras() (same shape the Coach SPA
    sees in DATA.extras). Selection rule:
        1. Among channels whose unit matches role.unit_hints (or any
           unit if no hints), prefer one whose name matches a
           pattern.
        2. Earlier patterns rank higher than later ones — patterns
           are ordered most-specific first.
        3. If no pattern matches, return None (no guess).
    """
    if not available:
        return None
    unit_hints = [u.lower() for u in (role.get("unit_hints") or [])]

    def unit_ok(ch: Dict[str, Any]) -> bool:
        if not unit_hints:
            return True
        u = (ch.get("unit") or "").lower().strip()
        return any(h in u or u in h for h in unit_hints if h)

    candidates = [c for c in available if unit_ok(c)]
    if not candidates:
        # Be permissive — units are missing on many parsers
        candidates = list(available)

    for pat_str in role.get("pattern_hints") or []:
        try:
            pat = re.compile(pat_str, re.IGNORECASE)
        except re.error:
            continue
        for ch in candidates:
            name = ch.get("name") or ""
            if pat.search(name):
                return ch.get("id")
    return None


def build_available_extras(track: Dict[str, Any],
                           lap_data: Optional[Dict[str, Any]] = None
                           ) -> List[Dict[str, Any]]:
    """Mirror laps.extract_lap_data's extra_channels output as a flat
    list of {id, name, unit} entries.

    Two input modes:
        - With lap_data (post-extraction): use lap_data['extra_channels']
          directly. Most accurate — same dict the Coach sees.
        - Without lap_data: synthesise from the track-level channel
          dict (xrk-style track['channels']) and known top-level
          keys. Used at upload step 1 where we don't want to extract
          every lap just to populate a picker.
    """
    out: List[Dict[str, Any]] = []
    seen_ids: set = set()

    if lap_data is not None:
        for key, ch in (lap_data.get("extra_channels") or {}).items():
            cid = str(key)
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            out.append({
                "id":   cid,
                "name": ch.get("name") or cid,
                "unit": ch.get("unit") or "",
            })
        return out

    # No lap_data — build from the track directly. Mirror the catalog
    # in extract_lap_data() so ids match what the Coach will later
    # see for any lap from this file.
    TOP_LEVEL = [
        ("altitude", "Höhe", "m"),
        ("gforce_x", "GForce X", "g"),
        ("gforce_y", "GForce Y", "g"),
        ("gforce_z", "GForce Z", "g"),
        ("gyro_x", "Gyro X", "°/s"),
        ("gyro_y", "Gyro Y", "°/s"),
        ("gyro_z", "Gyro Z", "°/s"),
        ("battery", "Batterie", "V"),
    ]
    for key, label, unit in TOP_LEVEL:
        if track.get(key) is None:
            continue
        if key in seen_ids:
            continue
        seen_ids.add(key)
        out.append({"id": key, "name": label, "unit": unit})

    # XRK / 2D channel dict — mirror the noise filter from
    # laps._is_noise() in spirit, but kept minimal here (full
    # filtering happens at extraction time; for the upload picker
    # we just suppress empty names and the obviously useless ones).
    NOISE_PREFIXES = ("E_", "ST_", "CAN_", "CAN1_", "CAN2_", "CAN ",
                      "Comms ", "Log ", "Logging ", "CPU ", "USB ",
                      "RTC ", "X2_", "Alarm ", "Display ", "Device ",
                      "Button ", "Up Shift", "Warning Light", "SLM ",
                      "Dash Temp", "Engine Running",
                      "id_tire_sensor", "Comms",
                      "5V Aux Supply", "8V Aux Supply",
                      "Fastest Lap Time", "Reference Lap Time",
                      "Lap Number", "Lap Distance", "Lap Time",
                      "Lap Time Predicted", "Lap Gain/Loss",
                      "Trip Distance", "Odometer", "Event Mileage",
                      "Total Fuel Used", "Beacon",
                      "Max Straight Speed", "Min Corner Speed",
                      "Fuel Used", "Fuel Usage", "Fuel Used per Lap",
                      "Fuel Remaining",
                      "CAN_DME", "CAN_SEB", "CAN_SWCL", "CAN_X2",
                      "GPS ")
    NOISE_SUFFIXES = ("_DIAG", "_AV")

    def is_noise(name: str) -> bool:
        if not name:
            return True
        if name == "GPS Altitude":
            return False
        if any(name.startswith(p) for p in NOISE_PREFIXES):
            return True
        if any(name.endswith(s) for s in NOISE_SUFFIXES):
            return True
        return False

    channels = track.get("channels") or {}
    if isinstance(channels, dict):
        for ch_name, ch in channels.items():
            if is_noise(ch_name):
                continue
            cid = f"ch_{ch_name}"
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            out.append({
                "id":   cid,
                "name": ch_name,
                "unit": ch.get("unit") or "" if isinstance(ch, dict) else "",
            })
    return out


def sanitise_assignment(raw: Dict[str, Any],
                        available_ids: Iterable[str]) -> Dict[str, str]:
    """Filter a user-supplied {role_id: channel_id} dict.

    - drops empty channel ids (means "not assigned")
    - drops role_ids unknown to ROLES
    - drops channel ids not in `available_ids`
    Returns a fresh dict safe to persist into lap_data['channel_roles'].
    """
    known_role_ids = {r["id"] for r in ROLES}
    valid_chs = set(available_ids)
    out: Dict[str, str] = {}
    for rid, cid in (raw or {}).items():
        if rid not in known_role_ids:
            continue
        if not cid:
            continue
        cid_str = str(cid).strip()
        if not cid_str or cid_str not in valid_chs:
            continue
        out[str(rid)] = cid_str
    return out
