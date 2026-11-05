"""Parser for MoTeC .ld telemetry files.

Format (based on public reverse engineering — same as ldparser by gotzl on GitHub):
  - File header (64 bytes)
      +0   u32   magic (0x40)
      +8   u32   channel_meta_offset (head of linked list)
      +12  u32   channel_data_offset
  - Channel metadata records (linked list of fixed-size structures):
      +0   u32   prev_addr
      +4   u32   next_addr
      +8   u32   data_addr
      +12  u32   data_count
      +18  u16   datatype  (0,3 = int16; 5 = int32; 7 = float32)
      +20  u16   data_size (2 or 4 bytes per sample)
      +22  u16   sample_rate (Hz)
      +26  u16   multiplier
      +28  u16   scale
      +30  u16   decimals
      +32  32B   channel name
      +64  8B    short name
      +72  12B   unit
  - Channel data: arrays at data_addr

Decoded value = raw * scale / multiplier / 10^decimals
"""
import struct
from typing import Dict, Any, List, Optional
import numpy as np


def _read_chan_record(data: bytes, offset: int) -> Optional[Dict[str, Any]]:
    if offset == 0 or offset >= len(data) - 100:
        return None
    try:
        prev_addr, next_addr, data_addr, data_count = struct.unpack(
            "<IIII", data[offset : offset + 16]
        )
        _, datatype, data_size, sample_rate = struct.unpack(
            "<HHHH", data[offset + 16 : offset + 24]
        )
        # shift/mul/scale/dec are SIGNED 16-bit (per gotzl)
        shift, multiplier, scale, decimals = struct.unpack(
            "<hhhh", data[offset + 24 : offset + 32]
        )
        name = data[offset + 32 : offset + 64].split(b"\x00")[0].decode("latin-1", errors="replace")
        short = data[offset + 64 : offset + 72].split(b"\x00")[0].decode("latin-1", errors="replace")
        unit = data[offset + 72 : offset + 84].split(b"\x00")[0].decode("latin-1", errors="replace")
    except (struct.error, IndexError):
        return None

    return {
        "next": next_addr, "data_addr": data_addr, "count": data_count,
        "datatype": datatype, "data_size": data_size, "rate": sample_rate,
        "shift": shift,
        "mult": multiplier, "scale": scale, "dec": decimals,
        "name": name, "short": short, "unit": unit,
    }


def _read_chan_data(data: bytes, ch: Dict[str, Any]) -> Optional[np.ndarray]:
    dt, sz, n, addr = ch["datatype"], ch["data_size"], ch["count"], ch["data_addr"]
    if n == 0 or addr == 0:
        return None
    if dt in (0, 3) and sz == 2:
        np_dtype = "<i2"; size = 2 * n
    elif dt == 5 and sz == 4:
        np_dtype = "<i4"; size = 4 * n
    elif dt == 7 and sz == 4:
        np_dtype = "<f4"; size = 4 * n
    else:
        return None
    if addr + size > len(data):
        return None
    raw = np.frombuffer(data[addr : addr + size], dtype=np_dtype).astype(np.float64)
    # Per gotzl/ldparser:  real = (raw / scale * 10^(-dec) + shift) * mul
    if ch["mult"] != 0 and ch["scale"] != 0:
        dec = 0 if ch["dec"] == 65535 else ch["dec"]
        raw = (raw / ch["scale"] * (10 ** -dec) + ch.get("shift", 0)) * ch["mult"]
    return raw


def _walk_chain(data: bytes, start: int) -> List[Dict[str, Any]]:
    channels = []
    seen = set()
    off = start
    while off and off not in seen:
        seen.add(off)
        ch = _read_chan_record(data, off)
        if ch is None:
            break
        channels.append(ch)
        off = ch["next"]
    return channels


def parse_ld(filepath: str) -> Dict[str, Any]:
    """Parse a .ld file. Returns the same dict shape as parse_ses()."""
    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 64:
        raise ValueError("File too small to be a .ld file")

    chan_meta_off = struct.unpack("<I", data[8:12])[0]
    if chan_meta_off >= len(data):
        raise ValueError("Channel metadata offset out of bounds — not a valid .ld file")

    # Light metadata extraction (best-effort; fields aren't always at fixed offsets)
    meta = {}
    for off, key, length in [(0x9C, "DATE", 26), (0xB8, "TIME", 24)]:
        try:
            s = data[off : off + length].decode("latin-1", errors="replace").rstrip("\x00").strip()
            if s and s.isprintable():
                meta[key] = s
        except Exception:
            pass
    # Find venue string. The exact offset varies between MoTeC firmware versions,
    # so we scan a small region for the longest printable ASCII run.
    venue = None
    best_len = 0
    for off in range(0x140, 0x200, 2):
        s = data[off : off + 64].decode("latin-1", errors="replace").rstrip("\x00").strip()
        # Strip non-printables from the start (in case we land mid-string)
        s = "".join(c for c in s if c.isprintable())
        if len(s) > best_len and len(s) > 3 and s.replace(" ", "").isalnum():
            venue = s
            best_len = len(s)
    if venue:
        meta["VENUE"] = venue

    channels = _walk_chain(data, chan_meta_off)
    if not channels:
        raise ValueError("No channel metadata found — not a valid .ld file")

    by_name = {c["name"]: c for c in channels}

    def get(name):
        c = by_name.get(name)
        return _read_chan_data(data, c) if c else None

    gps_lat = get("GPS Latitude")
    gps_lon = get("GPS Longitude")
    gps_speed = get("GPS Speed")
    running_lap = get("Running Lap Time")

    if gps_lat is None or gps_lon is None or gps_speed is None:
        avail = ", ".join(sorted(by_name.keys())[:10])
        raise ValueError(
            f"LD file is missing required GPS channels (Latitude / Longitude / Speed). "
            f"First channels found: {avail}…"
        )

    gps_rate = by_name["GPS Latitude"]["rate"] or 20
    time_arr = np.arange(len(gps_lat)) / float(gps_rate)

    # Load every channel with data into a dict, keyed by channel name.
    # Shape matches what extract_lap_data() expects for XRK-style overlay
    # channels: {time, data, rate, unit}. Each channel gets its own time
    # base since rates vary (1 Hz..500 Hz). extract_lap_data interpolates
    # onto the lap's time grid when needed.
    #
    # Skip the channels we already surfaced as primary fields (GPS*).
    SKIP_AS_EXTRA = {"GPS Latitude", "GPS Longitude", "GPS Speed",
                     "GPS Time", "GPS Date", "GPS Sats Used", "GPS Quality",
                     "GPS HDOP", "GPS DOP", "GPS VDOP", "GPS Valid",
                     "GPS Heading", "Running Lap Time"}
    extra_chs = {}
    for c in channels:
        name = c["name"]
        if name in SKIP_AS_EXTRA or not name:
            continue
        arr = _read_chan_data(data, c)
        if arr is None or len(arr) == 0:
            continue
        rate = c["rate"] or 1
        ch_time = np.arange(len(arr)) / float(rate)
        extra_chs[name] = {
            "time": ch_time,
            "data": arr,
            "rate": rate,
            "unit": c["unit"],
        }

    return {
        "meta": meta,
        "time": time_arr,
        "lat": gps_lat,
        "lon": gps_lon,
        "speed": gps_speed,
        "running_lap_time": running_lap,
        "running_lap_rate": (by_name["Running Lap Time"]["rate"] if "Running Lap Time" in by_name else 10),
        "all_channels": [c["name"] for c in channels],
        # XRK-style dict — picked up by extract_lap_data() and exposed as
        # extra channels in the analysis chart.
        "channels": extra_chs,
        "finish_line": None,  # LD files don't carry an explicit FL coordinate
        "source_format": "LD",
        "source_file": filepath,
    }
