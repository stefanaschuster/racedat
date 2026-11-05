"""Parser for RaceBox Fastlap CSV exports (used by RaceBox / Fastlap app).

File layout:
  - Header lines as "Key, Value" pairs (Format, Date, Track, Laps, ...)
  - Per-lap summary lines: "Lap N, totalSec, sectors, s1,s2,s3,s4,s5"
  - Blank line
  - Data table header: "Time,Latitude,Longitude,Altitude,Speed,GForceX,...,Lap,GyroX,..."
  - Data rows at ~25 Hz with ISO-8601 timestamps.

Speed is in km/h. Lap is an integer column (0 = out-/in-lap, 1..N = lap N).

Output dict matches the contract used by the other parsers:
  meta, time, lat, lon, speed, finish_line, source_format, source_file
plus optional:
  altitude, gforce_x/y/z, gyro_x/y/z, lap_times
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import numpy as np


# Regex for the per-lap summary lines:
#   "Lap 1, 106.794, sectors, 18.53,26.465,45.261,0,16.538"
#   "Incomplete lap, 116.413, sectors, ..."
_LAP_LINE_RE = re.compile(
    r"^(Lap\s+\d+|Incomplete lap)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*sectors\s*,\s*(.+)$",
    re.IGNORECASE,
)


def _parse_iso_timestamp(s: str) -> float:
    """Parse a timestamp like '2025-03-17T09:59:00.040Z' into a POSIX float seconds."""
    s = s.strip()
    # Replace trailing Z with +00:00 so fromisoformat handles it on older Pythons
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


def parse_racebox_csv(filepath: str) -> Dict[str, Any]:
    """Parse a RaceBox Fastlap CSV export and return the standard track dict."""
    meta: Dict[str, Any] = {}
    lap_summaries: List[Tuple[str, float, List[float]]] = []  # (label, total_s, sectors)
    incomplete_first: float = 0.0  # leading "Incomplete lap" duration (out-lap)

    with open(filepath, "r", encoding="utf-8", newline="") as fh:
        # Phase 1: pre-data header — read line-by-line until we find the
        # CSV data table header. The data header starts with "Time,Latitude"
        # (uniquely identifying it vs. the meta "Time, HH/MM/SS" line).
        data_header_pos = None
        lines = []
        for raw in fh:
            line = raw.rstrip("\r\n")
            if line.startswith("Time,Latitude"):
                data_header_pos = line
                break
            if line.strip() == "":
                continue
            lines.append(line)

        if data_header_pos is None:
            raise ValueError(
                "RaceBox Fastlap CSV: data header (line starting 'Time,...') not found"
            )

        # Parse header key/value lines + lap-summary lines
        for line in lines:
            m = _LAP_LINE_RE.match(line)
            if m:
                label = m.group(1).strip()
                total_s = float(m.group(2))
                sectors = [float(x.strip()) for x in m.group(3).split(",")
                           if x.strip()]
                lap_summaries.append((label, total_s, sectors))
                continue
            # Regular Key, Value
            if "," in line:
                key, _, value = line.partition(",")
                meta[key.strip()] = value.strip()

        # Phase 2: data rows
        header_cols = [c.strip() for c in data_header_pos.split(",")]
        reader = csv.reader(fh)
        col_index = {name: i for i, name in enumerate(header_cols)}

        required = ["Time", "Latitude", "Longitude", "Speed", "Lap"]
        for col in required:
            if col not in col_index:
                raise ValueError(f"RaceBox Fastlap CSV: required column '{col}' missing")

        # Pre-allocate lists; sample count typically a few thousand to ~30k.
        times_iso: List[str] = []
        lats: List[float] = []
        lons: List[float] = []
        speeds: List[float] = []
        alts: List[float] = []
        gx: List[float] = []
        gy: List[float] = []
        gz: List[float] = []
        gyx: List[float] = []
        gyy: List[float] = []
        gyz: List[float] = []
        laps: List[int] = []

        has_alt = "Altitude" in col_index
        has_g = all(c in col_index for c in ("GForceX", "GForceY", "GForceZ"))
        has_gy = all(c in col_index for c in ("GyroX", "GyroY", "GyroZ"))

        iT = col_index["Time"]
        iLat = col_index["Latitude"]
        iLon = col_index["Longitude"]
        iSpd = col_index["Speed"]
        iLap = col_index["Lap"]
        iAlt = col_index.get("Altitude")
        iGX = col_index.get("GForceX")
        iGY = col_index.get("GForceY")
        iGZ = col_index.get("GForceZ")
        iGyX = col_index.get("GyroX")
        iGyY = col_index.get("GyroY")
        iGyZ = col_index.get("GyroZ")

        for row in reader:
            if not row or len(row) < len(header_cols):
                continue
            try:
                times_iso.append(row[iT])
                lats.append(float(row[iLat]))
                lons.append(float(row[iLon]))
                speeds.append(float(row[iSpd]))
                laps.append(int(row[iLap]))
                if has_alt:
                    alts.append(float(row[iAlt]))
                if has_g:
                    gx.append(float(row[iGX]))
                    gy.append(float(row[iGY]))
                    gz.append(float(row[iGZ]))
                if has_gy:
                    gyx.append(float(row[iGyX]))
                    gyy.append(float(row[iGyY]))
                    gyz.append(float(row[iGyZ]))
            except (ValueError, IndexError):
                # Skip malformed row, keep going
                continue

    if not times_iso:
        raise ValueError("RaceBox Fastlap CSV: no data rows parsed")

    # Convert times to seconds-from-start
    t0 = _parse_iso_timestamp(times_iso[0])
    time_arr = np.array(
        [_parse_iso_timestamp(t) - t0 for t in times_iso],
        dtype=np.float64,
    )

    lat_arr = np.asarray(lats, dtype=np.float64)
    lon_arr = np.asarray(lons, dtype=np.float64)
    speed_arr = np.asarray(speeds, dtype=np.float64)  # km/h
    lap_arr = np.asarray(laps, dtype=np.int32)

    # Compute lap-start times and durations from the Lap column transitions.
    # `lap_times` for the standard contract = list of (start_t, duration).
    # We trust the per-row Lap values: a contiguous run of N corresponds to
    # lap N. The header's "Lap N, totalSec" gives us the authoritative duration
    # if available.
    lap_times: List[Tuple[float, float]] = []
    if lap_arr.size:
        # Find indices where lap value changes
        changes = np.where(np.diff(lap_arr) != 0)[0] + 1
        edges = np.concatenate([[0], changes, [len(lap_arr)]])
        # Map lap_num → authoritative duration from header summary if present
        header_durations = {}
        for label, dur, _ in lap_summaries:
            m = re.match(r"Lap\s+(\d+)$", label, re.IGNORECASE)
            if m:
                header_durations[int(m.group(1))] = dur

        for s, e in zip(edges[:-1], edges[1:]):
            n = int(lap_arr[s])
            if n <= 0:
                continue  # skip out-/in-lap segments
            start_t = float(time_arr[s])
            # Prefer header duration when available (millisecond-precise),
            # otherwise compute from the timestamp span.
            duration = header_durations.get(n)
            if duration is None:
                duration = float(time_arr[e - 1] - time_arr[s])
            lap_times.append((start_t, duration))

    # Build a meta dict that downstream code expects (RACER, VEHICLE, TRACK, DATE)
    out_meta: Dict[str, Any] = {}
    if meta.get("Track"):
        out_meta["TRACK"] = meta["Track"]
        out_meta["VENUE"] = meta["Track"]
    if meta.get("Configuration"):
        out_meta["TRACK_CONFIG"] = meta["Configuration"]
    if meta.get("Date"):
        # Convert "17/03/2025" → "2025-03-17"
        try:
            d, mo, y = meta["Date"].split("/")
            out_meta["DATE"] = f"{y}-{mo}-{d}"
        except (ValueError, AttributeError):
            out_meta["DATE"] = meta["Date"]
    if meta.get("Date UTC"):
        out_meta["DATE_UTC"] = meta["Date UTC"]
    if meta.get("Data Source"):
        out_meta["LOGGER"] = meta["Data Source"]
    if meta.get("Best Lap Time"):
        out_meta["BEST_LAP_S"] = meta["Best Lap Time"]
    # RaceBox Fastlap CSV doesn't have explicit racer/vehicle — leave empty for the user
    # to fill at upload time
    out_meta["RACER"] = ""
    out_meta["VEHICLE"] = ""

    result: Dict[str, Any] = {
        "meta": out_meta,
        "time": time_arr,
        "lat": lat_arr,
        "lon": lon_arr,
        "speed": speed_arr,          # km/h
        "lap_index_per_sample": lap_arr,  # raw Lap-column (for completeness)
        "finish_line": None,         # will be auto-detected if needed
        "source_format": "RACEBOX_CSV",
        "source_file": filepath,
    }
    if lap_times:
        result["lap_times"] = lap_times
    if has_alt:
        result["altitude"] = np.asarray(alts, dtype=np.float64)
    if has_g:
        result["gforce_x"] = np.asarray(gx, dtype=np.float64)
        result["gforce_y"] = np.asarray(gy, dtype=np.float64)
        result["gforce_z"] = np.asarray(gz, dtype=np.float64)
    if has_gy:
        result["gyro_x"] = np.asarray(gyx, dtype=np.float64)
        result["gyro_y"] = np.asarray(gyy, dtype=np.float64)
        result["gyro_z"] = np.asarray(gyz, dtype=np.float64)

    return result
