"""Phase detection and rule-based assessment for a single lap.

Inputs: lap_data dict with 'distance', 'time', 'speed', 'lat', 'lon'.
        (Standard output of laps.extract_lap_data.)

Outputs: dict with
  - braking_zones:    list of dicts (one per detected brake phase)
  - accel_zones:      list of dicts (one per detected accel phase)
  - core_stats:       top-speed, full-throttle stretch, sector times, etc.
  - assessment:       short German-language coaching text built from rules
  - thresholds:       constants used (for the UI to show consistent badges)

The detection is intentionally simple and CPU-cheap — no AI, no scipy.
It works on the speed signal only (plus its derivative).

Phase definition:
  We compute a smoothed acceleration signal a(d) = dv/dt (m/s per second).
  Phases:
    BRAKING:        a <= -BRAKE_THRESHOLD m/s² for at least MIN_PHASE_DUR
    ACCELERATING:   a >=  ACCEL_THRESHOLD  m/s² for at least MIN_PHASE_DUR
    NEUTRAL:        between the two (rolling / steady throttle)

  Local Speed minima between two phases are the "apex" of a corner.
  Apex-positions: scan for minima where surrounding speed is higher
  (used for distance-to-apex measurements).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import numpy as np


# -------- Thresholds (tweakable; sent to the frontend for consistent badges)

# Detection thresholds (m/s²)
BRAKE_THRESHOLD = 1.5   # > this much deceleration → braking phase
ACCEL_THRESHOLD = 1.0   # > this much acceleration → accelerating phase
MIN_PHASE_DUR_S = 0.5   # min duration to count as a real phase
MIN_PHASE_DV    = 8.0   # min speed change (km/h) in the phase

# Rating thresholds — "Roll-Phase" between braking end and apex, or apex and
# accel start. Distance in metres.
ROLL_OK    = 10.0
ROLL_WARN  = 30.0

# Rating thresholds — smoothness. Relative std-dev of the per-sample
# accel/decel rate within the phase (dimensionless ratio).
SMOOTH_OK    = 0.30
SMOOTH_WARN  = 0.60


def _smooth(arr: np.ndarray, win: int) -> np.ndarray:
    """Cheap boxcar smoother."""
    if win <= 1 or len(arr) <= win:
        return arr.astype(np.float64).copy()
    if win % 2 == 0:
        win += 1
    pad = win // 2
    padded = np.concatenate([
        np.full(pad, arr[0], dtype=np.float64),
        arr.astype(np.float64),
        np.full(pad, arr[-1], dtype=np.float64),
    ])
    kern = np.ones(win) / win
    return np.convolve(padded, kern, mode="valid")


def _grade(value: float, ok: float, warn: float) -> str:
    """Return 'ok' / 'warn' / 'bad'."""
    if value <= ok:
        return "ok"
    if value <= warn:
        return "warn"
    return "bad"


def _phase_runs(mask: np.ndarray):
    """Return list of (start_idx, end_idx_inclusive) where mask is True."""
    runs = []
    in_run = False
    start = 0
    for i, m in enumerate(mask):
        if m and not in_run:
            in_run = True
            start = i
        elif not m and in_run:
            in_run = False
            runs.append((start, i - 1))
    if in_run:
        runs.append((start, len(mask) - 1))
    return runs


def analyse_lap(lap_data: Dict[str, Any]) -> Dict[str, Any]:
    """Main entry point. Returns the analysis dict for the report template."""
    distance = np.asarray(lap_data["distance"], dtype=np.float64)
    time = np.asarray(lap_data["time"], dtype=np.float64)
    speed_kmh = np.asarray(lap_data["speed"], dtype=np.float64)
    speed_ms = speed_kmh / 3.6

    if len(distance) < 10:
        return _empty_result()

    # ---- Smoothed acceleration signal ------------------------------------
    # Sample-rate is roughly len/(time[-1]-time[0]); use a small time-window
    total_time = float(time[-1] - time[0]) if time[-1] > time[0] else 1.0
    dt_typical = total_time / len(time)
    win = max(3, int(round(0.4 / max(dt_typical, 1e-3))))  # ~0.4s smoother
    if win % 2 == 0:
        win += 1
    speed_smooth_ms = _smooth(speed_ms, win)

    # dv/dt using central differences in time
    accel = np.gradient(speed_smooth_ms, time)  # m/s²

    # ---- Detect phases ----------------------------------------------------
    brake_mask = accel <= -BRAKE_THRESHOLD
    accel_mask = accel >= ACCEL_THRESHOLD

    brake_runs = _phase_runs(brake_mask)
    accel_runs = _phase_runs(accel_mask)

    def _filter_runs(runs):
        out = []
        for s, e in runs:
            dur = float(time[e] - time[s])
            dv = abs(float(speed_kmh[e] - speed_kmh[s]))
            if dur >= MIN_PHASE_DUR_S and dv >= MIN_PHASE_DV:
                out.append((s, e))
        return out

    brake_runs = _filter_runs(brake_runs)
    accel_runs = _filter_runs(accel_runs)

    # ---- Find apexes (speed minima) between brakes and accelerations ------
    # Strategy: after each braking phase, walk forward until speed starts
    # rising again (next sample where speed_smooth_ms increases for a few
    # consecutive samples). That index is the apex.
    apex_for_brake = []
    for s, e in brake_runs:
        # Apex is the speed minimum on or shortly after the brake-end
        search_start = e
        search_end = min(len(speed_smooth_ms) - 1, e + max(5, win))
        # Also extend search until we see a clear rise OR run out of room
        # Take the local minimum of speed_smooth_ms in [e, search_end]
        seg = speed_smooth_ms[search_start:search_end + 1]
        apex_idx = search_start + int(np.argmin(seg))
        apex_for_brake.append(apex_idx)

    # Similarly: each acceleration phase has an apex right before it
    apex_for_accel = []
    for s, e in accel_runs:
        search_start = max(0, s - max(5, win))
        search_end = s
        seg = speed_smooth_ms[search_start:search_end + 1]
        apex_idx = search_start + int(np.argmin(seg))
        apex_for_accel.append(apex_idx)

    # ---- Build braking zone records ---------------------------------------
    braking_zones = []
    for (s, e), apex_idx in zip(brake_runs, apex_for_brake):
        # Roll-phase distance: between brake-end and apex
        roll_dist_m = float(max(0.0, distance[apex_idx] - distance[e]))
        # Smoothness: relative std of |accel| during the phase (lower = smoother)
        seg_accel = -accel[s:e + 1]  # positive numbers for deceleration
        seg_mean = float(np.mean(seg_accel)) if len(seg_accel) else 0.0
        seg_std = float(np.std(seg_accel)) if len(seg_accel) else 0.0
        smooth_rel = seg_std / seg_mean if seg_mean > 0.1 else 0.0
        # Decel rate
        avg_decel = seg_mean
        # Trail vs constant: is the late half softer than the early half?
        if (e - s) >= 4:
            half = (e - s) // 2
            early = float(np.mean(seg_accel[:half]))
            late = float(np.mean(seg_accel[half:]))
            trail_off = (early - late) / early if early > 0.1 else 0.0
        else:
            trail_off = 0.0

        braking_zones.append({
            "start_idx": int(s),
            "end_idx": int(e),
            "apex_idx": int(apex_idx),
            "start_dist_m": float(distance[s]),
            "end_dist_m": float(distance[e]),
            "apex_dist_m": float(distance[apex_idx]),
            "v_in_kmh":  float(speed_kmh[s]),
            "v_out_kmh": float(speed_kmh[e]),
            "v_apex_kmh": float(speed_kmh[apex_idx]),
            "dv_kmh":    float(speed_kmh[s] - speed_kmh[e]),
            "duration_s": float(time[e] - time[s]),
            "roll_distance_m": roll_dist_m,
            "roll_grade": _grade(roll_dist_m, ROLL_OK, ROLL_WARN),
            "smoothness": float(smooth_rel),
            "smoothness_grade": _grade(smooth_rel, SMOOTH_OK, SMOOTH_WARN),
            "avg_decel_ms2": float(avg_decel),
            "trail_off_ratio": float(trail_off),
        })

    # ---- Build acceleration zone records ----------------------------------
    accel_zones = []
    for (s, e), apex_idx in zip(accel_runs, apex_for_accel):
        # Apex-to-gas distance: between apex and start of accel phase
        apex_gas_m = float(max(0.0, distance[s] - distance[apex_idx]))
        seg_accel = accel[s:e + 1]
        seg_mean = float(np.mean(seg_accel)) if len(seg_accel) else 0.0
        seg_std = float(np.std(seg_accel)) if len(seg_accel) else 0.0
        smooth_rel = seg_std / seg_mean if seg_mean > 0.1 else 0.0
        avg_accel = seg_mean

        accel_zones.append({
            "start_idx": int(s),
            "end_idx": int(e),
            "apex_idx": int(apex_idx),
            "start_dist_m": float(distance[s]),
            "end_dist_m": float(distance[e]),
            "apex_dist_m": float(distance[apex_idx]),
            "v_in_kmh":  float(speed_kmh[s]),
            "v_out_kmh": float(speed_kmh[e]),
            "v_apex_kmh": float(speed_kmh[apex_idx]),
            "dv_kmh":    float(speed_kmh[e] - speed_kmh[s]),
            "duration_s": float(time[e] - time[s]),
            "apex_gas_distance_m": apex_gas_m,
            "apex_gas_grade": _grade(apex_gas_m, ROLL_OK, ROLL_WARN),
            "smoothness": float(smooth_rel),
            "smoothness_grade": _grade(smooth_rel, SMOOTH_OK, SMOOTH_WARN),
            "avg_accel_ms2": float(avg_accel),
        })

    # ---- Core stats --------------------------------------------------------
    top_speed = float(np.max(speed_kmh))
    top_speed_idx = int(np.argmax(speed_kmh))
    top_speed_dist = float(distance[top_speed_idx])

    # Sector times (3 equal-distance sectors)
    sector_times = []
    total_dist = float(distance[-1])
    for k in range(3):
        d0 = k * total_dist / 3
        d1 = (k + 1) * total_dist / 3
        i0 = int(np.searchsorted(distance, d0))
        i1 = int(np.searchsorted(distance, d1))
        i0 = max(0, min(i0, len(time) - 1))
        i1 = max(i0 + 1, min(i1, len(time) - 1))
        sector_times.append(float(time[i1] - time[i0]))

    # Longest stretch with neutral-or-positive acceleration ("vollgas-ish")
    # i.e. accel >= 0 continuously
    pos_mask = accel >= -0.3
    longest = 0.0
    cur = None
    for i, m in enumerate(pos_mask):
        if m:
            if cur is None:
                cur = i
        else:
            if cur is not None:
                longest = max(longest, distance[i - 1] - distance[cur])
                cur = None
    if cur is not None:
        longest = max(longest, distance[-1] - distance[cur])
    longest_full_throttle_m = float(longest)

    core_stats = {
        "top_speed_kmh": top_speed,
        "top_speed_distance_m": top_speed_dist,
        "sector_times_s": sector_times,
        "longest_full_throttle_m": longest_full_throttle_m,
        "n_brake_zones": len(braking_zones),
        "n_accel_zones": len(accel_zones),
    }

    # ---- Rule-based assessment --------------------------------------------
    assessment = _build_assessment(braking_zones, accel_zones, core_stats)

    return {
        "braking_zones": braking_zones,
        "accel_zones": accel_zones,
        "core_stats": core_stats,
        "assessment": assessment,
        "thresholds": {
            "roll_ok_m": ROLL_OK,
            "roll_warn_m": ROLL_WARN,
            "smooth_ok": SMOOTH_OK,
            "smooth_warn": SMOOTH_WARN,
        },
    }


def _empty_result():
    return {
        "braking_zones": [],
        "accel_zones": [],
        "core_stats": {
            "top_speed_kmh": 0.0,
            "top_speed_distance_m": 0.0,
            "sector_times_s": [0.0, 0.0, 0.0],
            "longest_full_throttle_m": 0.0,
            "n_brake_zones": 0,
            "n_accel_zones": 0,
        },
        "assessment": {
            "headline": "Zu wenige Daten für eine Auswertung.",
            "points": [],
        },
        "thresholds": {
            "roll_ok_m": ROLL_OK,
            "roll_warn_m": ROLL_WARN,
            "smooth_ok": SMOOTH_OK,
            "smooth_warn": SMOOTH_WARN,
        },
    }


def _build_assessment(braking_zones, accel_zones, core_stats) -> Dict[str, Any]:
    """Build a short German assessment from the detected phases.

    Pure rule-based, no ML. Counts ✓/⚠/✗ per category, formulates
    headline + a few bullet hints. The user emphasised:
      - Bremsen sollte bis zum Scheitelpunkt durchgehen
      - Beschleunigen sollte gleichmäßig ab Apex sein
      - Rollphasen + unstete Verläufe sind schlecht
    """
    n_b = len(braking_zones)
    n_a = len(accel_zones)

    def _count_grades(zones, key):
        c = {"ok": 0, "warn": 0, "bad": 0}
        for z in zones:
            c[z[key]] += 1
        return c

    b_roll = _count_grades(braking_zones, "roll_grade")
    b_smooth = _count_grades(braking_zones, "smoothness_grade")
    a_roll = _count_grades(accel_zones, "apex_gas_grade")
    a_smooth = _count_grades(accel_zones, "smoothness_grade")

    points = []

    # --- Headline based on overall picture ---
    total_zones = max(1, n_b + n_a)
    bad_count = (b_roll["bad"] + b_smooth["bad"]
                 + a_roll["bad"] + a_smooth["bad"])
    warn_count = (b_roll["warn"] + b_smooth["warn"]
                  + a_roll["warn"] + a_smooth["warn"])
    bad_ratio = bad_count / (4 * total_zones)
    warn_ratio = (warn_count + bad_count) / (4 * total_zones)

    if bad_ratio < 0.05 and warn_ratio < 0.20:
        headline = (f"Saubere Runde. {n_b} Bremszone(n) und {n_a} Beschleunigungs"
                    f"phase(n) sehen gut aus.")
    elif bad_ratio < 0.15:
        headline = (f"Solide Runde mit ein paar Verbesserungspunkten "
                    f"({warn_count} Warnung(en), {bad_count} grobe(r) Fehler).")
    else:
        headline = (f"Deutliche Verbesserungspunkte: {bad_count} Probleme über "
                    f"{n_b + n_a} Phasen verteilt.")

    # --- Bremsen-Punkte ---
    if n_b == 0:
        points.append({
            "kind": "neutral",
            "text": "Keine klaren Bremszonen erkannt – evtl. sehr flüssige Strecke."
        })
    else:
        # Rollphase nach Bremsen
        if b_roll["bad"] >= 1:
            worst_b_roll = max(braking_zones,
                               key=lambda z: z["roll_distance_m"])
            points.append({
                "kind": "bad",
                "text": (f"Beim Bremsen wird {b_roll['bad']}× nicht bis zum "
                         f"Scheitelpunkt durchgezogen — "
                         f"längste Rollphase {worst_b_roll['roll_distance_m']:.0f} m "
                         f"bei Bremszone #{braking_zones.index(worst_b_roll) + 1}."),
                "zone_kind": "brake",
                "zone_idx": braking_zones.index(worst_b_roll),
            })
        elif b_roll["warn"] >= 1:
            points.append({
                "kind": "warn",
                "text": (f"In {b_roll['warn']} von {n_b} Bremszone(n) entsteht eine "
                         f"kleine Rollphase vor dem Scheitelpunkt — versuche bis zur "
                         f"Kurvenmitte am Bremshebel zu bleiben."),
            })
        else:
            points.append({
                "kind": "good",
                "text": "Bremsung geht in allen Zonen bis zum Scheitelpunkt durch — sauberes Trail Braking.",
            })

        # Glättung der Verzögerung
        if b_smooth["bad"] >= 1:
            worst_b_sm = max(braking_zones, key=lambda z: z["smoothness"])
            points.append({
                "kind": "bad",
                "text": (f"Verzögerungsverlauf ist {b_smooth['bad']}× unruhig — "
                         f"in Bremszone #{braking_zones.index(worst_b_sm) + 1} "
                         f"wird der Bremshebel sichtbar moduliert."),
                "zone_kind": "brake",
                "zone_idx": braking_zones.index(worst_b_sm),
            })
        elif b_smooth["warn"] >= 1:
            points.append({
                "kind": "warn",
                "text": f"In {b_smooth['warn']} Bremszone(n) leicht ruckelige Verzögerung.",
            })

    # --- Beschleunigungs-Punkte ---
    if n_a == 0:
        points.append({
            "kind": "neutral",
            "text": "Keine klaren Beschleunigungsphasen erkannt."
        })
    else:
        if a_roll["bad"] >= 1:
            worst_a_roll = max(accel_zones,
                               key=lambda z: z["apex_gas_distance_m"])
            points.append({
                "kind": "bad",
                "text": (f"Nach dem Scheitelpunkt wird {a_roll['bad']}× zu spät "
                         f"ans Gas gegangen — längste Rollphase "
                         f"{worst_a_roll['apex_gas_distance_m']:.0f} m "
                         f"in Phase #{accel_zones.index(worst_a_roll) + 1}."),
                "zone_kind": "accel",
                "zone_idx": accel_zones.index(worst_a_roll),
            })
        elif a_roll["warn"] >= 1:
            points.append({
                "kind": "warn",
                "text": (f"In {a_roll['warn']} von {n_a} Phase(n) entsteht eine "
                         f"kleine Rollphase zwischen Scheitelpunkt und Gas-Auf."),
            })
        else:
            points.append({
                "kind": "good",
                "text": "Direkt nach dem Scheitelpunkt geht es überall ans Gas — gutes Timing.",
            })

        if a_smooth["bad"] >= 1:
            worst_a_sm = max(accel_zones, key=lambda z: z["smoothness"])
            points.append({
                "kind": "bad",
                "text": (f"Gasaufzug ist {a_smooth['bad']}× unstet — "
                         f"in Phase #{accel_zones.index(worst_a_sm) + 1} "
                         f"sieht das nach mehrfachem Gas-Auf-Zu aus."),
                "zone_kind": "accel",
                "zone_idx": accel_zones.index(worst_a_sm),
            })
        elif a_smooth["warn"] >= 1:
            points.append({
                "kind": "warn",
                "text": f"In {a_smooth['warn']} Beschleunigungsphase(n) leicht unstetiger Speed-Anstieg.",
            })

    # --- Kurz-Note zur Top-Speed --------
    top = core_stats["top_speed_kmh"]
    if top > 0:
        points.append({
            "kind": "neutral",
            "text": f"Höchstgeschwindigkeit: {top:.0f} km/h bei "
                    f"{core_stats['top_speed_distance_m']/1000:.2f} km."
        })

    return {
        "headline": headline,
        "points": points,
    }
