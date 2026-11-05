"""Lap detection and extraction from GPS tracks.

Strategies (auto-selected):
  1. Running-lap-time channel resets (from MoTeC LD files)
  2. Finish-line crossings (when an FL coordinate is known, e.g. SES *FL field)
  3. Auto-detected pseudo-finish-line (densest 5m grid cell on the track)
"""
from typing import List, Dict, Any, Optional, Tuple
import numpy as np


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters."""
    R = 6371000.0
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def _detect_by_fl(lat, lon, time, fl_lat, fl_lon,
                  radius_m=50.0, min_lap_s=30.0, max_lap_s=600.0):
    dist_fl = haversine(lat, lon, fl_lat, fl_lon)
    near = dist_fl < radius_m

    crossings = []
    in_zone = False
    zone_start = 0
    for i in range(len(near)):
        if near[i] and not in_zone:
            in_zone = True; zone_start = i
        elif not near[i] and in_zone:
            in_zone = False
            zone_dists = dist_fl[zone_start:i]
            crossings.append(zone_start + int(np.argmin(zone_dists)))

    laps = []
    for i in range(len(crossings) - 1):
        s, e = crossings[i], crossings[i + 1]
        lap_time = float(time[e] - time[s])
        if min_lap_s < lap_time < max_lap_s:
            laps.append({
                "lap_index": i + 1,
                "start_idx": int(s),
                "end_idx": int(e),
                "start_time": float(time[s]),
                "end_time": float(time[e]),
                "duration": lap_time,
                "method": "finish_line",
            })
    return laps


def _detect_by_running_lap(rlt, rate_hz, min_lap_s=30.0, max_lap_s=600.0):
    dt = 1.0 / rate_hz
    diff = np.diff(rlt)
    resets = np.where(diff < -10)[0]
    starts = np.concatenate([[0], resets + 1])
    ends = np.concatenate([resets, [len(rlt) - 1]])

    laps = []
    for i, (s, e) in enumerate(zip(starts, ends)):
        duration = float(rlt[e])
        if not (min_lap_s < duration < max_lap_s):
            continue
        slot_dur = float((e - s) * dt)
        if abs(slot_dur - duration) > 5:
            continue
        laps.append({
            "lap_index": i,
            "start_idx_rlt": int(s),
            "end_idx_rlt": int(e),
            "start_time": float(s * dt),
            "end_time": float(e * dt),
            "duration": duration,
            "method": "running_lap_time",
        })
    return laps


def _auto_finish_line(lat, lon):
    """Pick the most-revisited point on the track as a pseudo-FL."""
    valid = (lat != 0) & (lon != 0)
    lat = lat[valid]; lon = lon[valid]
    if len(lat) < 100:
        raise ValueError("Not enough valid GPS points to auto-detect a finish line")
    cos_lat = np.cos(np.radians(lat.mean()))
    grid_lat = (lat * 111000 / 5).astype(np.int64)
    grid_lon = (lon * 111000 * cos_lat / 5).astype(np.int64)
    keys = grid_lat * 1_000_000 + grid_lon
    unique, counts = np.unique(keys, return_counts=True)
    best = unique[np.argmax(counts)]
    mask = keys == best
    return float(lat[mask].mean()), float(lon[mask].mean())


def detect_laps(track: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect laps in a parsed track. Tries strategies 0→3 in order."""
    lat, lon, time = track["lat"], track["lon"], track["time"]

    # 0) Pre-computed lap times (e.g., XRK from libxrk)
    if track.get("lap_times"):
        laps = []
        for i, (start_t, dur) in enumerate(track["lap_times"]):
            if 30 < dur < 600:  # sanity filter
                laps.append({
                    "lap_index": i + 1,
                    "start_time": float(start_t),
                    "end_time": float(start_t + dur),
                    "duration": float(dur),
                    "method": "running_lap_time",  # reuse this code-path for extract
                })
        if laps:
            return sorted(laps, key=lambda x: x["start_time"])

    # 1) running-lap-time channel
    if track.get("running_lap_time") is not None:
        rate = track.get("running_lap_rate", 10)
        laps = _detect_by_running_lap(track["running_lap_time"], rate)
        if laps:
            return sorted(laps, key=lambda x: x["start_time"])

    # 2) known finish-line
    fl = track.get("finish_line")
    if fl and fl[0] is not None:
        laps = _detect_by_fl(lat, lon, time, fl[0], fl[1])
        if laps:
            return sorted(laps, key=lambda x: x["start_time"])

    # 3) auto-detected finish-line
    try:
        fl_lat, fl_lon = _auto_finish_line(lat, lon)
        laps = _detect_by_fl(lat, lon, time, fl_lat, fl_lon)
        if laps:
            track["finish_line"] = (fl_lat, fl_lon)
            return sorted(laps, key=lambda x: x["start_time"])
    except ValueError:
        pass

    return []


def fastest_lap(laps):
    return min(laps, key=lambda x: x["duration"]) if laps else None


def extract_lap_data(track, lap):
    """Return time/lat/lon/speed/distance arrays for one lap, time relative
    to lap start.

    If the source track carries additional per-sample channels (e.g. RaceBox
    Fastlap CSV with altitude/gforce/gyro, or XRK with engine/throttle/brake
    channels), those are sliced to the lap window and added to the
    `extra_channels` dict in the result. Each entry has:
        {"name", "unit", "data": np.ndarray, "color": "#hex" (optional)}
    Consumers (report builder) can decide whether/how to show them.
    """
    t = track["time"]
    if lap["method"] == "finish_line":
        s, e = lap["start_idx"], lap["end_idx"]
    elif lap["method"] == "running_lap_time":
        s = int(np.searchsorted(t, lap["start_time"]))
        e = int(np.searchsorted(t, lap["end_time"]))
        s = max(0, min(s, len(t) - 1))
        e = max(s + 1, min(e, len(t) - 1))
    else:
        raise ValueError(f"Unknown lap method: {lap['method']}")

    # Include the end sample (inclusive slice) so the lap data duration
    # is as close as possible to the lap meta duration.
    e_inclusive = min(e + 1, len(t))

    lap_start_abs = float(lap["start_time"])
    lap_time = t[s:e_inclusive] - lap_start_abs
    lap_lat = track["lat"][s:e_inclusive]
    lap_lon = track["lon"][s:e_inclusive]
    lap_speed = track["speed"][s:e_inclusive]

    seg = haversine(lap_lat[:-1], lap_lon[:-1], lap_lat[1:], lap_lon[1:])
    lap_dist = np.concatenate([[0.0], np.cumsum(seg)])

    # Synthetic endpoint to match the meta duration (see docstring above)
    meta_duration = float(lap["duration"])
    appended_synthetic = False
    if len(lap_time) > 0 and meta_duration > lap_time[-1] + 1e-6:
        lap_time = np.concatenate([lap_time, [meta_duration]])
        lap_lat = np.concatenate([lap_lat, [lap_lat[-1]]])
        lap_lon = np.concatenate([lap_lon, [lap_lon[-1]]])
        lap_speed = np.concatenate([lap_speed, [lap_speed[-1]]])
        lap_dist = np.concatenate([lap_dist, [lap_dist[-1]]])
        appended_synthetic = True

    # --- Extra channels ----------------------------------------------------
    # Known top-level keys in the track dict that hold per-sample arrays
    # aligned to track["time"]. We slice them with the same indices.
    # Each entry: source-key in track → display label + unit.
    EXTRA_CHANNEL_CATALOG = [
        # RaceBox Fastlap CSV
        ("altitude",  "Höhe",         "m"),
        ("gforce_x",  "GForce X",     "g"),
        ("gforce_y",  "GForce Y",     "g"),
        ("gforce_z",  "GForce Z",     "g"),
        ("gyro_x",    "Gyro X",       "°/s"),
        ("gyro_y",    "Gyro Y",       "°/s"),
        ("gyro_z",    "Gyro Z",       "°/s"),
        # SES
        ("battery",   "Batterie",     "V"),
    ]
    extra_channels = {}
    n = len(track["time"])
    for key, label, unit in EXTRA_CHANNEL_CATALOG:
        arr = track.get(key)
        if arr is None:
            continue
        try:
            arr = np.asarray(arr, dtype=np.float64)
        except Exception:
            continue
        if len(arr) != n:
            # Length mismatch — channel sampled at a different rate. Skip
            # rather than risk misaligning indices. (Could interpolate but
            # for v1 we keep it simple.)
            continue
        sliced = arr[s:e_inclusive]
        if appended_synthetic:
            sliced = np.concatenate([sliced, [sliced[-1]] if len(sliced) else [0.0]])
        if len(sliced) == 0:
            continue
        if not np.any(np.isfinite(sliced)):
            continue
        extra_channels[key] = {
            "name": label,
            "unit": unit,
            "data": sliced,
        }

    # XRK-style: track["channels"] is a dict of {name: {time, data, rate, unit}}.
    # These can have their own time base — interpolate onto the lap time grid
    # so they line up with the canonical samples.
    #
    # Filter out channels that are useless on a chart:
    # - MoTeC diagnostic flags (E_*, ST_*, CAN_*, CAN1_*, CAN2_*, *_DIAG)
    # - GPS status fields (already shown via GPS Speed primary)
    # - Constant channels (min == max → flat line, no info)
    # - Channels whose name is empty or starts with "Comms"
    NOISE_PREFIXES = ("E_", "ST_", "CAN_", "CAN1_", "CAN2_", "CAN ",
                       "Comms ",
                       "Log ", "Logging ", "CPU ", "USB ", "RTC ", "X2_",
                       "Alarm ", "Display ", "Device ", "Button ",
                       "Up Shift Light", "Warning Light", "SLM ",
                       "Up Shift", "Dash Temp", "Engine Running",
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
                       "GPS ")  # GPS-Status channels: we already have lat/lon/speed
    NOISE_SUFFIXES = ("_DIAG", "_AV")  # _AV = raw analog voltage shadow, usually redundant
    NOISE_EXACT = {"idx_mode_veh", "idx_trqmap", "idx_trqlim",
                    "ST_killswitch", "ST_ignition",
                    "engbr_adj", "dtc_adj", "CAN2_CLAMP_STAT_DIAG",
                    "CAN1_CLAMP_STAT_DIAG"}

    def _is_noise(name):
        if not name or name in NOISE_EXACT:
            return True
        # Exceptions to the prefix rules — these channels are useful
        if name == "GPS Altitude":
            return False
        for p in NOISE_PREFIXES:
            if name.startswith(p):
                return True
        for s in NOISE_SUFFIXES:
            if name.endswith(s):
                return True
        return False

    xrk_channels = track.get("channels") or {}
    if isinstance(xrk_channels, dict) and xrk_channels and len(lap_time) > 0:
        # We need an absolute lap-time window (in track-time units, not
        # lap-relative) to interpolate against the channel's own time array.
        lap_time_abs = lap_time + lap_start_abs
        for ch_name, ch in xrk_channels.items():
            if _is_noise(ch_name):
                continue
            try:
                ch_t = np.asarray(ch.get("time"), dtype=np.float64)
                ch_d = np.asarray(ch.get("data"), dtype=np.float64)
            except Exception:
                continue
            if len(ch_t) == 0 or len(ch_d) == 0 or len(ch_t) != len(ch_d):
                continue
            try:
                sliced = np.interp(lap_time_abs, ch_t, ch_d)
            except Exception:
                continue
            finite = sliced[np.isfinite(sliced)]
            if len(finite) == 0:
                continue
            # Drop near-constant channels (min == max within the lap window)
            if float(finite.max() - finite.min()) < 1e-9:
                continue
            extra_channels[f"ch_{ch_name}"] = {
                "name": ch_name,
                "unit": ch.get("unit") or "",
                "data": sliced,
            }

    return {
        "time": lap_time,
        "lat": lap_lat,
        "lon": lap_lon,
        "speed": lap_speed,
        "distance": lap_dist,
        "duration": float(lap_time[-1]) if len(lap_time) > 0 else lap["duration"],
        "total_distance": float(lap_dist[-1]) if len(lap_dist) > 0 else 0.0,
        "extra_channels": extra_channels,
    }
