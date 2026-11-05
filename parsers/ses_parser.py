"""Parser for AiM/Racelogic .SES session files.

Format (reverse-engineered):
  - ASCII header section terminated by a column-header line "TIME;LAT;LON;...;TEMP\\r\\n"
  - Binary data section: 52-byte fixed records, big-endian
    +0   int32   TIME      (centiseconds; 1 unit = 0.01s)
    +4   int32   LAT       (* 1e-7 = degrees)
    +8   int32   LON       (* 1e-7 = degrees)
    +24  int16   BAT       (/ 100 = volts)
    +46  int16   SPEED_GPS (/ 10  = km/h)
   (other fields are present but mostly empty in observed data)
"""
import struct
import re
from typing import Dict, Any
import numpy as np


def _parse_header(data: bytes):
    """Return (meta_dict, data_offset)."""
    # Find the column-header line
    col_pos = data.find(b"TIME;LAT;LON")
    if col_pos < 0:
        raise ValueError("Not a .SES file — column header line not found")
    col_end = data.find(b"\n", col_pos)
    if col_end < 0:
        raise ValueError("Malformed .SES header — no newline after column line")
    data_offset = col_end + 1

    header_text = data[:col_pos].decode("ascii", errors="replace")
    meta = {}
    for line in header_text.replace("\r", "").split("\n"):
        line = line.strip()
        if not line.startswith("*"):
            continue
        body = line[1:]
        # *NAME=Stefan   VEHICLE=CBR   DATE=...   may have multiple KEY=VAL on one line
        # But also single-key lines like *FL=lat/lon
        # Use a regex that catches KEY=VALUE, where KEY = uppercase/digits/space/underscore,
        # VALUE = anything until the next "  KEY=" boundary or end of line.
        for m in re.finditer(r"([A-Z][A-Z0-9_ ]*?)=([^=]*?)(?=(?:\s+[A-Z][A-Z0-9_ ]*=)|$)", body):
            key = m.group(1).strip()
            val = m.group(2).strip()
            meta[key] = val

    # Parse finish-line coordinate from *FL=lat/lon
    fl_lat = fl_lon = None
    fl_str = meta.get("FL")
    if fl_str:
        parts = fl_str.split("/")
        if len(parts) >= 2:
            try:
                fl_lat = float(parts[0])
                fl_lon = float(parts[1])
            except ValueError:
                pass
    meta["_finish_line"] = (fl_lat, fl_lon) if fl_lat is not None else None

    return meta, data_offset


def parse_ses(filepath: str) -> Dict[str, Any]:
    """Parse a .SES file. Returns a dict with arrays and metadata."""
    with open(filepath, "rb") as f:
        data = f.read()

    meta, data_offset = _parse_header(data)
    raw = data[data_offset:]
    rec_size = 52
    n_recs = len(raw) // rec_size
    if n_recs == 0:
        raise ValueError("No data records found in .SES file")

    # Vectorized parsing: read big-endian fields directly via numpy structured dtype
    # We only care about the fields we use; pad the rest.
    dtype = np.dtype([
        ("time", ">i4"),
        ("lat", ">i4"),
        ("lon", ">i4"),
        ("_pad1", "S12"),    # bytes 12..23 (unused channels)
        ("bat", ">i2"),
        ("_pad2", "S20"),    # bytes 26..45
        ("spd", ">i2"),
        ("_pad3", "S2"),     # bytes 48..49
        ("_pad4", "S2"),     # bytes 50..51
    ])
    assert dtype.itemsize == rec_size, f"struct size mismatch: {dtype.itemsize} != {rec_size}"

    arr = np.frombuffer(raw[: n_recs * rec_size], dtype=dtype)
    times = arr["time"].astype(np.float64) * 0.01
    lats = arr["lat"].astype(np.float64) / 1e7
    lons = arr["lon"].astype(np.float64) / 1e7
    speeds = arr["spd"].astype(np.float64) / 10.0
    bat = arr["bat"].astype(np.float64) / 100.0

    return {
        "meta": meta,
        "time": times,
        "lat": lats,
        "lon": lons,
        "speed": speeds,            # km/h
        "battery": bat,
        "finish_line": meta.get("_finish_line"),
        "source_format": "SES",
        "source_file": filepath,
    }
