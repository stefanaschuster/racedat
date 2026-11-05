"""Parser for I2M motorcycle data-logger files (.dat).

I2M is an Italian motorcycle data-logger system (Chrome / DataLog Pro).
Two ASCII record dialects are handled:

LEGACY dialect ($VALUE records, fixed 14-column layout):
    $NEW SESSION
    $DATE,DDMMYY,
    $SETTINGS,<calibration constants for the analog channels>
    $GPS,<ts>,A,<lat_NMEA>,N,<lon_NMEA>,E,<speed_KNOTS>,<utc_hhmmss.sss>,<heading>
    $VALUE,<ts>,<14 sensor columns>,<counter>

SELF-DESCRIBING dialect (v23.17 — e.g. Danas/Corsa loggers on Ducati V4,
observed 2026; $VAL records with declared channel tables):
    $PILOTA,<bike/rider name>,
    $BEST,<m:ss.mmm>,              best-lap hint from the logger
    $CANALI,<rate_hz>,<id>,<id>,...        one line PER RATE GROUP
    $SETTAGGICANALI,<id>;<name>;<cal_lo>;<cal_hi>,...
    $VAL,<rate_hz>,<ts>,<one value per id in that rate's $CANALI>,
    $GPS,...                               identical to legacy dialect

Calibration ($SETTAGGICANALI): raw values are 10-bit ADC counts; the
physical value is  cal_lo + raw/1023*(cal_hi-cal_lo).  The pair
(0.0, 1023.0) is the logger's "no calibration" placeholder — those
channels stay raw (verified: Spd1/Spd2 are wheel-sensor pulse rates whose
km/h factor varies with tire circumference between files, and "Rpm" raw
does not track engine speed plausibly — no scaling is invented for them;
GPS carries the authoritative speed). Verified calibrations on real
files: FrontSusp/RearSusp → mm travel, LAMBDA INT. → AFR 12..15,
APS → 0..100 %, Atm. pressure → ~101 kPa, Lean Angle → ±56°.

Shared facts (both dialects):
Coordinates: NMEA DDMM.MMMM format
    e.g. "5031.1799" = 50° 31.1799' = 50.519665°
Speed: NMEA RMC convention — KNOTS, converted to km/h via × 1.852
Timestamps: integer counter in 10-ms units (NOT milliseconds despite the
    field name suggesting otherwise — we verified by cross-checking UTC
    time diffs vs ts diffs). 1 ts unit = 0.01 s.
Sentinel 65535 (= 0xFFFF) = "invalid sample" → masked to NaN.

A single file can contain multiple sessions (multiple `$NEW SESSION`
markers); we pick the one with the fastest detected lap.

Returns the same dict shape as the other parsers in this package.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Any, List, Optional, Tuple

import numpy as np


# Best-effort name + unit for the data columns of $VALUE records.
# (column-index in VALUE row after the timestamp; 0..12 — col 13 is a
# wraparound counter and is dropped).
#
# Sentinel value 65535 (= 0xFFFF) is the logger's "invalid sample" marker
# for the analog channels — we mask those to NaN at parse time so they
# don't break min/max ranges.
VALUE_COL_MAP = [
    ("TPS",           "raw"),    # 0  — throttle position, ~270..590
    ("Fork",          "raw"),    # 1  — fork travel,       ~85..330
    ("Shock",         "raw"),    # 2  — shock travel,      ~365..30000 (with 65535 sentinels)
    ("Brake",         "raw"),    # 3  — brake pressure,    ~1000..30000 (with 65535 sentinels)
    ("Front Susp",    "raw"),    # 4  — front suspension derived, ~2600..30000 (with 65535)
    ("Aux1",          ""),       # 5  — (always 0 in example file → dropped by const-filter)
    ("Aux2",          ""),       # 6  — (always 0 in example file)
    ("DTC Spin",      "raw"),    # 7  — traction-control spin counter
    ("DTC SPN",       "raw"),    # 8  — traction-control SPN
    ("DTC TOT",       "raw"),    # 9  — traction-control total
    ("Misc1",         "raw"),    # 10 — analog channel
    ("Misc2",         "raw"),    # 11 — analog channel (often saturated at 1023)
    ("Misc3",         "raw"),    # 12 — analog channel (often saturated at 1023)
    # col 13 is a wraparound counter / CRC, NOT exposed as a channel
]

# Sentinel value to mask out per column (None = no masking)
# These appear in the analog channels as "no data this sample".
SENTINEL = 65535.0

# v23.17 — Units for calibrated $SETTAGGICANALI channels where the physical
# meaning was verified against real files (see module docstring). Channels
# not listed get "" (calibrated, unit unknown) or "raw" (uncalibrated).
CALIBRATED_UNITS = {
    "FrontSusp": "mm",
    "RearSusp": "mm",
    "LAMBDA INT.": "AFR",
    "APS": "%",
    "Lean Angle": "°",
    "Pitch Angle": "°",
    "Atm. pressure": "kPa",
}

# The logger's "no calibration" placeholder pair in $SETTAGGICANALI.
_CAL_DUMMY = (0.0, 1023.0)


def _parse_nmea_lat(token: str, hemisphere: str) -> float:
    """Convert NMEA DDMM.MMMM latitude to decimal degrees."""
    token = token.strip()
    if not token:
        return float("nan")
    # The "minutes" part starts at position -7 from the end (MM.MMMM)
    # so degrees is everything before that.
    try:
        dot = token.index(".")
        deg_len = dot - 2  # MM.MMMM after the degree part
        deg = float(token[:deg_len])
        minutes = float(token[deg_len:])
        val = deg + minutes / 60.0
        if hemisphere in ("S", "s"):
            val = -val
        return val
    except (ValueError, IndexError):
        return float("nan")


def _parse_nmea_lon(token: str, hemisphere: str) -> float:
    """Convert NMEA DDDMM.MMMM longitude to decimal degrees."""
    token = token.strip()
    if not token:
        return float("nan")
    try:
        dot = token.index(".")
        deg_len = dot - 2
        deg = float(token[:deg_len])
        minutes = float(token[deg_len:])
        val = deg + minutes / 60.0
        if hemisphere in ("W", "w"):
            val = -val
        return val
    except (ValueError, IndexError):
        return float("nan")


def _split_sessions(lines: List[str]) -> List[Tuple[int, int]]:
    """Return list of (start_line_idx, end_line_idx_exclusive) for each
    session in the file. A session starts at the line AFTER a `$NEW SESSION`
    record (or at line 0 if there's no marker before the first data)."""
    bounds = []
    starts = [i for i, ln in enumerate(lines) if ln.startswith("$NEW SESSION")]
    if not starts:
        return [(0, len(lines))]
    # Sessions are bracketed by consecutive starts
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        bounds.append((s, end))
    # v23.17 — file prelude: self-describing files carry header records
    # ($BEST, $DIST, $TIPO) BEFORE the first $NEW SESSION marker. Fold
    # them into the first session so its meta sees them; the prelude
    # never contains $GPS/$VAL data rows.
    if bounds and bounds[0][0] > 0:
        bounds[0] = (0, bounds[0][1])
    return bounds


def _parse_session(lines: List[str], start: int, end: int) -> Optional[Dict[str, Any]]:
    """Parse one session worth of lines. Returns None if there's not
    enough GPS data to be useful."""
    date_str = None
    settings_str = None
    gps_records = []   # (ts_ms, lat, lon, speed_kmh, utc_seconds)
    value_records = [] # (ts_ms, col0, col1, ..., col13)
    # v23.17 — self-describing dialect state
    pilota = None                  # $PILOTA,<name>
    best_hint = None               # $BEST,<m:ss.mmm>
    canali = {}                    # rate_hz -> [channel_id, ...]
    cal_table = {}                 # channel_id -> (name, cal_lo, cal_hi)
    val_records = {}               # rate_hz -> list of (ts, v0, v1, ...)

    for ln_idx in range(start, end):
        ln = lines[ln_idx]
        if not ln or ln[0] != "$":
            continue
        # Split robustly — records often end with a trailing comma
        parts = ln.rstrip("\n\r ,").split(",")
        head = parts[0]

        if head == "$DATE" and len(parts) >= 2:
            date_str = parts[1].strip()

        elif head == "$SETTINGS":
            settings_str = ln.rstrip("\n\r ,")

        elif head == "$PILOTA" and len(parts) >= 2:
            pilota = parts[1].strip()

        elif head == "$BEST" and len(parts) >= 2:
            best_hint = parts[1].strip()

        elif head == "$CANALI" and len(parts) >= 3:
            try:
                rate = int(parts[1])
                canali[rate] = [int(x) for x in parts[2:] if x.strip()]
            except ValueError:
                pass

        elif head == "$SETTAGGICANALI":
            for ent in ln.rstrip("\n\r ,").split(",")[1:]:
                q = ent.split(";")
                if len(q) >= 4:
                    try:
                        cal_table[int(q[0])] = (
                            q[1].strip(), float(q[2]), float(q[3]))
                    except ValueError:
                        continue

        elif head == "$VAL" and len(parts) >= 4:
            try:
                rate = int(parts[1])
                ts = float(parts[2])
                vals = [float(x) for x in parts[3:]]
            except ValueError:
                continue
            val_records.setdefault(rate, []).append((ts, vals))

        elif head == "$GPS" and len(parts) >= 9:
            try:
                # v23.20 — some loggers write a fractional ts (34811458.4)
                ts = float(parts[1])
                status = parts[2].strip()
                if status != "A":
                    # 'V' = NMEA "void/invalid fix" — skip
                    continue
                lat = _parse_nmea_lat(parts[3], parts[4])
                lon = _parse_nmea_lon(parts[5], parts[6])
                # NMEA RMC convention: speed is in KNOTS. Convert to km/h.
                speed_kn = float(parts[7])
                speed_kmh = speed_kn * 1.852
                # UTC time as HHMMSS.sss → seconds since midnight
                utc_raw = parts[8].strip()
                utc_s = float("nan")
                if utc_raw and "." in utc_raw:
                    hms = utc_raw.split(".")[0]
                    frac = utc_raw.split(".")[1]
                    if len(hms) == 6:
                        h = int(hms[0:2]); m = int(hms[2:4]); s = int(hms[4:6])
                        utc_s = h * 3600 + m * 60 + s + float("0." + frac)
                if not (np.isfinite(lat) and np.isfinite(lon)):
                    continue
                gps_records.append((ts, lat, lon, speed_kmh, utc_s))
            except (ValueError, IndexError):
                continue

        elif head == "$VALUE" and len(parts) >= 15:
            try:
                ts = int(parts[1])
                cols = []
                # Read 13 data columns (parts[2] through parts[14]).
                # parts[15] is a wraparound counter, not a sensor channel.
                for i in range(2, 15):
                    try:
                        v = float(parts[i])
                        # Mask the logger's "invalid sample" sentinel
                        if v == SENTINEL:
                            v = float("nan")
                        cols.append(v)
                    except ValueError:
                        cols.append(float("nan"))
                value_records.append((ts, *cols))
            except (ValueError, IndexError):
                continue

    if len(gps_records) < 10:
        return None

    gps_arr = np.array(gps_records, dtype=np.float64)
    ts_gps_units = gps_arr[:, 0]
    utc_s = gps_arr[:, 4]
    # IMPORTANT: the logger's `ts` field is NOT in milliseconds — it counts
    # in 10-ms units (1/100th of a second). We verified this by comparing
    # the GPS sentences:
    #   - UTC field steps in 100 ms increments (the GPS module's native rate)
    #   - the corresponding ts diffs are ~10 units → 10 × 10 ms = 100 ms
    #   - VALUE records have dt=5 units → 50 ms → 20 Hz
    # Convert ts to seconds with the right factor.
    TS_UNIT_S = 0.01  # 1 ts unit = 10 ms = 0.01 s

    # UTC is the authoritative GPS clock (the logger's `ts` is monotonic
    # but slightly noisy because of write-buffering bursts). Use UTC for
    # the GPS time axis and derive a logger-clock offset so VALUE records
    # (which use ts) can be aligned to the same axis.
    #
    # Drop records with non-finite UTC (rare; safety).
    valid_utc = np.isfinite(utc_s)
    if valid_utc.sum() < 10:
        return None
    gps_arr = gps_arr[valid_utc]
    ts_gps_units = ts_gps_units[valid_utc]
    utc_s = utc_s[valid_utc]

    # Sort by UTC just in case (some loggers write out-of-order at burst
    # boundaries)
    order = np.argsort(utc_s, kind="stable")
    gps_arr = gps_arr[order]
    ts_gps_units = ts_gps_units[order]
    utc_s = utc_s[order]

    # Handle a midnight rollover: if UTC seconds suddenly drop by ~86400,
    # add a day to subsequent samples.
    if len(utc_s) > 1:
        d = np.diff(utc_s)
        wrap_at = np.where(d < -3600)[0]
        for idx in wrap_at:
            utc_s[idx+1:] += 86400.0

    t0_utc = utc_s[0]
    time_s = utc_s - t0_utc
    lat = gps_arr[:, 1]
    lon = gps_arr[:, 2]
    speed_kmh = gps_arr[:, 3]

    # Offset to convert logger ts (in 10ms units) → same-axis-as-GPS seconds:
    #   gps_time_s ≈ ts * TS_UNIT_S + offset
    # Compute offset from the first GPS record. We use the median of the
    # first few records to be robust against burst aliasing.
    n_sync = min(50, len(ts_gps_units))
    offset_s = float(np.median(time_s[:n_sync] - ts_gps_units[:n_sync] * TS_UNIT_S))

    out = {
        "meta": {
            "DATE": date_str or "",
            "VENUE": "",  # I2M files don't include the track name
            "SOURCE": "I2M",
        },
        "time": time_s,
        "lat": lat,
        "lon": lon,
        "speed": speed_kmh,
        "finish_line": None,
        "source_format": "I2M",
        "running_lap_time": None,
        "all_channels": ["lat", "lon", "speed"],
    }
    # v23.17 — self-describing dialect: bike/rider name + logger best-lap
    # hint land in meta (upload step offers VEHICLE as bike suggestion).
    if pilota:
        out["meta"]["PILOTA"] = pilota
        out["meta"]["VEHICLE"] = pilota
    if best_hint:
        out["meta"]["BEST_LAP_HINT"] = best_hint

    # Build channels dict (XRK-style) from VALUE rows, so the extras pipeline
    # in laps.py picks them up. Drop entirely-constant columns (the constant
    # filter in laps.py will catch them too, but doing it here saves work).
    if value_records:
        val_arr = np.array(value_records, dtype=np.float64)
        ts_val_units = val_arr[:, 0]
        # Align with the GPS time axis via the offset computed above.
        val_time_s = ts_val_units * TS_UNIT_S + offset_s

        channels = {}
        for col_idx, (name, unit) in enumerate(VALUE_COL_MAP):
            data = val_arr[:, 1 + col_idx]  # +1 to skip ts column
            if not np.any(np.isfinite(data)):
                continue
            finite = data[np.isfinite(data)]
            if len(finite) == 0:
                continue
            # Drop fully-constant or all-zero columns
            if float(finite.max() - finite.min()) < 1e-9:
                continue
            # Sample rate from median diff (20 Hz expected)
            if len(val_time_s) > 1:
                dt = np.median(np.diff(val_time_s))
                rate = int(round(1.0 / dt)) if dt > 0 else 20
            else:
                rate = 20
            channels[name] = {
                "time": val_time_s.copy(),
                "data": data,
                "rate": rate,
                "unit": unit,
            }
        if channels:
            out["channels"] = channels
            out["all_channels"].extend(channels.keys())

    # v23.17 — Self-describing dialect: build channels from the $VAL
    # streams, one per declared rate group. Channel identity comes from
    # $CANALI (column order) + $SETTAGGICANALI (name + calibration).
    if val_records:
        channels = out.get("channels") or {}
        for rate, recs in sorted(val_records.items()):
            ids = canali.get(rate) or []
            if not ids or len(recs) < 2:
                continue
            # Keep only rows whose column count matches the declaration
            # (truncated last lines after a hard power-off are common).
            rows = [(ts, v) for ts, v in recs if len(v) == len(ids)]
            if len(rows) < 2:
                continue
            ts_units = np.array([r[0] for r in rows], dtype=np.float64)
            data_arr = np.array([r[1] for r in rows], dtype=np.float64)
            # Sentinel → NaN before calibration.
            data_arr[data_arr == SENTINEL] = np.nan
            chan_time_s = ts_units * TS_UNIT_S + offset_s
            for col, cid in enumerate(ids):
                name, cal_lo, cal_hi = cal_table.get(
                    cid, (f"CH{cid}", *_CAL_DUMMY))
                data = data_arr[:, col]
                finite = data[np.isfinite(data)]
                if len(finite) == 0:
                    continue
                # Fully-constant channels carry no information — drop
                # (same policy as the legacy path).
                if float(finite.max() - finite.min()) < 1e-9:
                    continue
                if (cal_lo, cal_hi) != _CAL_DUMMY:
                    data = cal_lo + data / 1023.0 * (cal_hi - cal_lo)
                    unit = CALIBRATED_UNITS.get(name, "")
                else:
                    unit = "raw"
                # Name collisions across rate groups (or with legacy
                # columns): suffix with the channel id, never overwrite.
                key = name if name not in channels else f"{name} #{cid}"
                channels[key] = {
                    "time": chan_time_s.copy(),
                    "data": data,
                    "rate": int(rate),
                    "unit": unit,
                }
        if channels:
            out["channels"] = channels
            out["all_channels"] = (["lat", "lon", "speed"]
                                   + list(channels.keys()))

    return out


def parse_i2m(filepath: str) -> Dict[str, Any]:
    """Parse an I2M .dat file. A single .dat may contain many sessions
    (track-day workflows often have warmup + real sessions + box-stops in
    one file). We pick the session with the FASTEST detected lap — that's
    almost always the one the user wants to analyse. If no session has
    detectable laps, fall back to the longest session by GPS sample count.
    """
    # Imports here (not at module top) to avoid a circular dep — laps.py
    # may import from this package in the future.
    from laps import detect_laps

    with open(filepath, "r", encoding="latin-1", errors="replace") as f:
        lines = f.readlines()

    bounds = _split_sessions(lines)
    candidates = []  # list of (fastest_lap_s or None, n_samples, idx, session_dict)
    for idx, (s, e) in enumerate(bounds):
        sess = _parse_session(lines, s, e)
        if sess is None:
            continue
        # Try to detect laps. Use the fastest-lap duration as the primary
        # selection key. If detection fails or returns nothing, fall back
        # to None which sorts after any real lap-time.
        try:
            laps = detect_laps(sess)
        except Exception:
            laps = []
        fastest = None
        if laps:
            fastest = min(lap["duration"] for lap in laps)
        candidates.append((fastest, len(sess["time"]), idx, sess))

    if not candidates:
        raise ValueError(
            "I2M file contains no usable session (need at least 10 valid "
            "GPS records with status='A'). The file may be empty, corrupt, "
            "or only contain non-fix data."
        )

    # Sort: sessions WITH a detected lap first (ascending by lap time so
    # the fastest comes first); sessions without laps last, sorted by
    # sample count desc.
    def _sort_key(c):
        fast, n, idx, _ = c
        if fast is None:
            return (1, -n, idx)        # group "no laps" together, longest first
        return (0, fast, idx)          # group "has laps", fastest first

    candidates.sort(key=_sort_key)
    chosen = candidates[0][3]
    chosen["meta"]["TOTAL_SESSIONS"] = len(candidates)
    chosen["meta"]["CHOSEN_SESSION_SAMPLES"] = len(chosen["time"])
    chosen["source_file"] = filepath
    return chosen
    chosen["meta"]["TOTAL_SESSIONS"] = len(sessions)
    chosen["meta"]["CHOSEN_SESSION_SAMPLES"] = len(chosen["time"])
    chosen["source_file"] = filepath
    return chosen
