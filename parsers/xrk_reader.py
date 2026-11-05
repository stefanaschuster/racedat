"""Reader for AiM RaceStudio .xrk and .xrz files using libxrk.

libxrk is a pure Python+Cython library that parses XRK/XRZ files directly
without needing AiM's proprietary Windows DLL or Wine.

Setup:
    pip3 install --user --break-system-packages libxrk

Or via venv:
    python3 -m venv ~/lapcomp-venv
    source ~/lapcomp-venv/bin/activate
    pip install libxrk numpy

Output format matches parse_ses() / parse_ld() so the rest of the toolchain
(laps.py, ld_writer, etc.) can use it transparently.

libxrk specifics observed (v0.11.x):
  - log.channels:  dict { name: pyarrow.Table with cols ['timecodes', name] }
  - log.laps:      pyarrow.Table with cols ['num', 'start_time', 'end_time']
  - log.metadata:  dict-like with vehicle/track/racer/etc.
  - timecodes & lap times are in MILLISECONDS (we convert to seconds)
  - Each channel has its own sample rate (varies from 1 Hz to 1 kHz+)
"""
import os
from typing import Dict, Any, List


def parse_xrk(filepath: str, **_kwargs) -> Dict[str, Any]:
    """Read an .xrk or .xrz file via libxrk and return our canonical track dict.

    Returns:
        {
            'meta':         {...metadata strings...},
            'time':         np.ndarray (seconds since session start, GPS rate)
            'lat':          np.ndarray (degrees)
            'lon':          np.ndarray (degrees)
            'speed':        np.ndarray (km/h or m/s — see notes)
            'lap_times':    list of (start_seconds, duration_seconds) tuples
            'channels':     dict { name: {'time': arr, 'data': arr,
                                          'rate': Hz, 'unit': str} }
            'gps_channels': dict (same shape, GPS-derived only)
            'finish_line':  None  (XRK has lap markers from logger)
            'source_format':'XRK',
            'source_file':  str,
        }
    """
    try:
        from libxrk import aim_xrk
    except ImportError as e:
        raise RuntimeError(
            "libxrk is not installed. Install with:\n"
            "  pip3 install --user --break-system-packages libxrk\n"
            "or in a virtualenv:\n"
            "  python3 -m venv ~/lapcomp-venv && source ~/lapcomp-venv/bin/activate\n"
            "  pip install libxrk numpy"
        ) from e

    import numpy as np

    if not os.path.isfile(filepath):
        raise FileNotFoundError(filepath)

    log = aim_xrk(filepath)

    # ---- Metadata ----------------------------------------------------------
    meta: Dict[str, str] = {}
    raw_meta = getattr(log, "metadata", None)
    if raw_meta:
        # libxrk's metadata may be dict, namedtuple, or object with attrs.
        if isinstance(raw_meta, dict):
            items = raw_meta.items()
        else:
            items = ((k, getattr(raw_meta, k)) for k in dir(raw_meta)
                     if not k.startswith("_") and not callable(getattr(raw_meta, k, None)))
        for k, v in items:
            if v is None or v == "":
                continue
            try:
                meta[str(k).upper()] = str(v)
            except Exception:
                pass

    # Common-case mappings (libxrk metadata keys vary by file)
    # We map flexibly so downstream code works whether the keys are
    # 'vehicle_name', 'vehicle', 'VehicleName', etc.
    def _grab(*candidates):
        for c in candidates:
            for k, v in meta.items():
                if k == c.upper():
                    return v
        return ""

    canonical = {
        "VEHICLE":     _grab("vehicle_name", "vehicle", "VehicleName"),
        "TRACK":       _grab("track_name", "track", "TrackName", "venue"),
        "RACER":       _grab("racer_name", "racer", "driver", "DriverName"),
        "CHAMPIONSHIP": _grab("championship", "championship_name"),
        "SESSION_TYPE": _grab("session_type", "session_type_name", "venue_type"),
        "DATE":        _grab("date", "session_date"),
        "TIME":        _grab("time", "session_time"),
    }
    canonical["VENUE"] = canonical["TRACK"]
    # Merge: keep raw metadata too, plus our canonical keys
    meta.update({k: v for k, v in canonical.items() if v})

    # ---- Lap times --------------------------------------------------------
    # libxrk: laps.column('num'/'start_time'/'end_time') — values in MILLISECONDS
    lap_times: List = []
    laps = getattr(log, "laps", None)
    if laps is not None and laps.num_rows > 0:
        for i in range(laps.num_rows):
            try:
                start_ms = laps.column("start_time")[i].as_py()
                end_ms = laps.column("end_time")[i].as_py()
            except Exception:
                continue
            start_s = float(start_ms) / 1000.0
            duration_s = float(end_ms - start_ms) / 1000.0
            if duration_s > 0:
                lap_times.append((start_s, duration_s))

    # ---- Channels ----------------------------------------------------------
    # libxrk: channels = dict { name: pyarrow Table }
    # The "normal" channel table has cols ['timecodes', <channel_name>] but
    # some logger configurations produce a COMPOUND GPS table where one
    # entry has multiple sub-columns (Latitude, Longitude, Speed, ...).
    # We handle both cases here.
    channels: Dict[str, Dict[str, Any]] = {}
    gps_channels: Dict[str, Dict[str, Any]] = {}

    # Names we treat as GPS-related (case-insensitive substring match)
    GPS_NAME_HINTS = ("GPS", "Latitude", "Longitude", "Lat", "Lon")

    def _column_names(table):
        """Return list of column names from a pyarrow Table, tolerating older APIs."""
        try:
            return list(table.column_names)
        except AttributeError:
            try:
                return list(table.schema.names)
            except Exception:
                return []

    def _to_numpy(col):
        """Convert a pyarrow column to a 1-D float64 numpy array, robustly."""
        try:
            return np.asarray(col.to_numpy(zero_copy_only=False), dtype=np.float64)
        except Exception:
            return np.asarray([v.as_py() for v in col], dtype=np.float64)

    debug_channel_listing: List[str] = []

    for name, table in log.channels.items():
        try:
            cols = _column_names(table)
        except Exception:
            continue
        debug_channel_listing.append(f"{name}({','.join(cols)})")

        # Identify the time column. libxrk uses 'timecodes' but be tolerant.
        t_name = None
        for cand in ("timecodes", "Time", "time", "t"):
            if cand in cols:
                t_name = cand
                break
        if t_name is None:
            continue
        try:
            time_ms = _to_numpy(table.column(t_name))
        except Exception:
            continue
        if len(time_ms) == 0:
            continue
        time_s = time_ms / 1000.0
        rate = _estimate_rate(time_s)

        # Value column(s): every column that isn't the time column.
        value_cols = [c for c in cols if c != t_name]

        # Decide whether this channel is GPS-related. Use the parent name
        # AND any sub-column name as hints.
        is_gps_parent = any(h.lower() in name.lower() for h in ("GPS", "Latitude", "Longitude"))

        if len(value_cols) == 1:
            # Simple channel: timecodes + 1 value column
            try:
                data = _to_numpy(table.column(value_cols[0]))
            except Exception:
                continue
            if len(data) == 0:
                continue
            ch = {"time": time_s, "data": data, "rate": rate, "unit": ""}
            if is_gps_parent:
                gps_channels[name] = ch
            else:
                channels[name] = ch
        else:
            # Compound channel — emit one virtual channel per sub-column.
            # This handles the case where a single 'GPS' entry contains
            # Latitude, Longitude, Speed, Altitude etc. in one table.
            for sub in value_cols:
                try:
                    data = _to_numpy(table.column(sub))
                except Exception:
                    continue
                if len(data) == 0:
                    continue
                ch = {"time": time_s, "data": data, "rate": rate, "unit": ""}
                key = sub
                sub_is_gps = (is_gps_parent
                              or any(h.lower() in sub.lower() for h in GPS_NAME_HINTS))
                if sub_is_gps:
                    # Normalise key to "GPS <SubName>" form when missing the prefix
                    if not key.lower().startswith("gps"):
                        key = f"GPS {sub}"
                    gps_channels[key] = ch
                else:
                    channels[key] = ch

    # ---- Build canonical lat/lon/speed/time arrays -----------------------
    # Search GPS channels by flexible name matching (case-insensitive).
    def _find_gps(*needles):
        """Return (key, ch) for the first gps_channels entry whose key
        contains any of `needles` as a case-insensitive substring."""
        low_keys = {k.lower(): k for k in gps_channels.keys()}
        for needle in needles:
            n = needle.lower()
            # Exact match (case-insensitive) first
            for k_low, k_orig in low_keys.items():
                if k_low == n:
                    return k_orig, gps_channels[k_orig]
            # Substring match second
            for k_low, k_orig in low_keys.items():
                if n in k_low:
                    return k_orig, gps_channels[k_orig]
        return None, None

    lat_key, lat_ch = _find_gps("GPS Latitude", "Latitude", "GPS Lat", "Lat")
    lon_key, lon_ch = _find_gps("GPS Longitude", "Longitude", "GPS Lon", "Lon")

    if lat_ch is None or lon_ch is None:
        raise RuntimeError(
            f"GPS Latitude/Longitude channels not found in {filepath}.\n"
            f"Found GPS channels: {list(gps_channels.keys())}\n"
            f"Found non-GPS channels: {list(channels.keys())[:20]}"
            f"{'...' if len(channels) > 20 else ''}\n"
            f"Raw libxrk listing: {debug_channel_listing[:40]}"
            f"{'...' if len(debug_channel_listing) > 40 else ''}"
        )

    lat = lat_ch["data"]
    lon = lon_ch["data"]
    time_arr = lat_ch["time"]

    # --- Time-base alignment ----------------------------------------------
    # libxrk reports channel `timecodes` in milliseconds since logger boot
    # (sometimes hours/days before the session), but `log.laps.start_time`
    # is in milliseconds since SESSION start. Without correcting this,
    # lap-extraction slices the wrong (empty) range of channel samples.
    #
    # Align by subtracting the first channel timestamp so time_arr starts
    # at ~0, matching the lap-time base.
    if len(time_arr) > 0 and time_arr[0] > 1.0:
        # Only adjust if there's a real offset (>1s)
        time_offset = float(time_arr[0])
        time_arr = time_arr - time_offset
        # Also adjust any other gps_channels we'd use later (speed)
        for ch in gps_channels.values():
            if "time" in ch and len(ch["time"]) > 0 and ch["time"][0] > time_offset - 1:
                ch["time"] = ch["time"] - time_offset
        for ch in channels.values():
            if "time" in ch and len(ch["time"]) > 0 and ch["time"][0] > time_offset - 1:
                ch["time"] = ch["time"] - time_offset

    # Sanity-check the GPS data — refuse to render an empty graph silently.
    if len(lat) == 0 or len(lon) == 0:
        raise RuntimeError(
            f"GPS Latitude/Longitude channels found but empty in {filepath} "
            f"(lat={len(lat)} samples, lon={len(lon)} samples). "
            f"The file may be corrupt or the export is incomplete."
        )
    # Lon and lat must have matching length — if not, interpolate lon onto lat's time-base
    if len(lon) != len(lat):
        lon = np.interp(time_arr, lon_ch["time"], lon)

    # --- Filter invalid GPS samples ----------------------------------------
    # libxrk can leave NaN/inf or out-of-range "no-fix" sentinel values in
    # latitude/longitude when the GPS receiver has no fix (e.g. bike standing
    # in the garage / paddock at the start of a session). The garbage values
    # then drag the track-map / speed-vs-distance plots into useless
    # rectangles. We construct a "valid" mask using:
    #   1. Finite values (no NaN/inf)
    #   2. Lat/Lon in physical range (-90..90 / -180..180)
    #   3. Lat *AND* Lon within 2° of the median (sanity guard against
    #      individual bad samples sitting far from the rest of the track —
    #      a real session never covers >220 km on the lon axis)
    #   4. Optional: quality flags GPS_Fix >= 2, GPS_pDOP < 10,
    #      GPS_Position_Accuracy < 100m when those channels are available
    mask = np.isfinite(lat) & np.isfinite(lon)
    mask &= (lat >= -90.0) & (lat <= 90.0)
    mask &= (lon >= -180.0) & (lon <= 180.0)

    if mask.sum() == 0:
        raise RuntimeError(
            f"GPS Latitude/Longitude in {filepath} contain only invalid values "
            f"(all NaN/inf or out of range). The recording may have no GPS fix."
        )

    # Use median of currently-valid samples as the track centre
    lat_med = float(np.nanmedian(lat[mask]))
    lon_med = float(np.nanmedian(lon[mask]))
    # A circuit is typically <5km wide. 2° = ~220 km, generous safety margin.
    mask &= np.abs(lat - lat_med) < 2.0
    mask &= np.abs(lon - lon_med) < 2.0

    # Quality-flag-based filtering — only apply when channels are present.
    # These are mild bounds: keep anything that "looks like" a fix.
    fix_key, fix_ch = _find_gps("GPS_Fix", "GPS Fix", "Fix")
    if fix_ch is not None and len(fix_ch["data"]) == len(lat):
        # 0 = no fix, 1 = 1D, 2 = 2D, 3 = 3D. Keep 2D+ samples.
        mask &= fix_ch["data"] >= 2
    pdop_key, pdop_ch = _find_gps("GPS_pDOP", "pDOP")
    if pdop_ch is not None and len(pdop_ch["data"]) == len(lat):
        # pDOP < 10 is "OK", 99.99 is libxrk's no-fix sentinel
        mask &= pdop_ch["data"] < 10.0
    pos_acc_key, pos_acc_ch = _find_gps("GPS_Position_Accuracy", "Position_Accuracy")
    if pos_acc_ch is not None and len(pos_acc_ch["data"]) == len(lat):
        # Accept up to 100m position accuracy
        mask &= pos_acc_ch["data"] < 100.0

    n_filtered = len(lat) - int(mask.sum())
    if mask.sum() == 0:
        raise RuntimeError(
            f"All {len(lat)} GPS samples in {filepath} failed quality checks. "
            f"The recording may have no GPS fix."
        )
    if n_filtered > 0:
        import sys as _sys
        _sys.stderr.write(
            f"[xrk_reader] {filepath}: filtered out {n_filtered} of {len(lat)} "
            f"GPS samples with no/poor fix.\n"
        )

    # Apply mask consistently to lat/lon/time
    lat = lat[mask]
    lon = lon[mask]
    time_arr = time_arr[mask]

    # Speed — prefer GPS Speed, fall back to a sensible non-GPS speed channel
    # libxrk's "GPS Speed" channel is in m/s. We convert to km/h for our
    # canonical output (matching SES/LD convention).
    speed_arr = None
    speed_unit_factor = 1.0  # multiply m/s value by this to get km/h
    spd_key, spd_ch = _find_gps("GPS Speed", "Speed")
    if spd_ch is not None:
        speed_arr = spd_ch["data"]
        speed_t = spd_ch["time"]
        # libxrk GPS Speed = m/s; convert to km/h
        speed_unit_factor = 3.6
        # Resample to GPS-Latitude time-base if needed
        if len(speed_arr) != len(lat):
            speed_arr = np.interp(time_arr, speed_t, speed_arr)
    if speed_arr is None:
        for try_key in ("SpeedVeh", "Ground Speed", "Speed", "Fr_Speed"):
            if try_key in channels:
                src = channels[try_key]
                speed_arr = np.interp(time_arr, src["time"], src["data"])
                # Heuristic: if max < 100, it's m/s; if >100, already km/h
                if np.nanmax(np.abs(speed_arr)) < 100:
                    speed_unit_factor = 3.6
                break
    if speed_arr is None:
        speed_arr = np.zeros_like(lat)
    speed_arr = speed_arr * speed_unit_factor

    return {
        "meta": meta,
        "time": time_arr,
        "lat": np.asarray(lat, dtype=np.float64),
        "lon": np.asarray(lon, dtype=np.float64),
        "speed": np.asarray(speed_arr, dtype=np.float64),
        "lap_times": lap_times,
        "channels": channels,
        "gps_channels": gps_channels,
        "finish_line": None,
        "source_format": "XRK",
        "source_file": filepath,
    }


def _estimate_rate(time_array) -> int:
    """Estimate sample rate (Hz) from a time array in seconds."""
    import numpy as np
    if time_array is None or len(time_array) < 2:
        return 0
    arr = np.asarray(time_array)
    dt = float(np.median(np.diff(arr)))
    if dt <= 0:
        return 0
    rate = int(round(1.0 / dt))
    # Clamp to plausible range. Channels above 65kHz are unreasonable for
    # vehicle telemetry and would also overflow uint16 in the LD writer.
    if rate < 1:
        return 1
    if rate > 65535:
        return 65535
    return rate
