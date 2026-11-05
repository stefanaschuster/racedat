#!/usr/bin/env python3
"""xrk2ld — Convert AiM RaceStudio .xrk files to MoTeC i2 .ld + .ldx pairs.

This tool uses AiM's official MatLabXRK DLL (loaded via ctypes) to read
.xrk files. The DLL is a Windows binary, so on Linux it must be run via
Wine + Windows Python. See parsers/xrk_reader.py for setup details.

Usage:
  xrk2ld.py FILE.xrk [FILE2.xrk ...] [-o OUT_DIR_OR_PREFIX]
                     [--driver NAME] [--vehicle ID] [--venue NAME]
                     [--event NAME] [--session SESSION]
                     [--rename-channels] [--raw-gps]

Example (Linux with Wine):
  # Set DLL location (one-time)
  export XRK_DLL_DIR=/path/to/aim_dlls

  # Run via Wine python
  wine python xrk2ld.py session.xrk

  # Or via wineprefix:
  WINEPREFIX=~/.xrk-wine wine python xrk2ld.py *.xrk -o /tmp/converted/

Example (native Windows):
  python xrk2ld.py session.xrk
  python xrk2ld.py *.xrk --rename-channels
"""
import argparse
import os
import sys
import datetime as _dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
except ImportError:
    print("ERROR: numpy required (pip install numpy)", file=sys.stderr)
    sys.exit(2)

from parsers import parse_xrk
from parsers.ld_writer import (
    write_ld, LDChannel,
    DTA_INT16, DTA_INT32, DTA_FLOAT,
    gps_lat_channel, gps_lon_channel, gps_speed_channel,
    beacon_channel, running_lap_time_channel,
)
from parsers.ldx_writer import write_ldx
from parsers.channel_names import map_name


# Channels that should always be written as int32/lat-precision
GPS_LAT_NAMES = {"GPS Latitude", "Latitude"}
GPS_LON_NAMES = {"GPS Longitude", "Longitude"}
GPS_SPEED_NAMES = {"GPS Speed", "Speed"}


def _pick_dtype(values: np.ndarray):
    """Pick a sensible (datatype_a, data_size, dec) for a channel based on its values.

    Goal: preserve precision while staying within int16 range when possible.
    Returns (datatype_a, data_size, dec).
    """
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return DTA_INT16, 2, 0
    max_abs = float(np.max(np.abs(finite)))
    if max_abs == 0:
        return DTA_INT16, 2, 0

    # Try increasingly precise int16 encodings: dec=0..3
    for dec in (0, 1, 2, 3):
        scaled = max_abs * (10 ** dec)
        if scaled < 32000:
            return DTA_INT16, 2, dec
    # Need more precision → int32
    for dec in (3, 4, 5, 6, 7):
        scaled = max_abs * (10 ** dec)
        if scaled < 2_000_000_000:
            return DTA_INT32, 4, dec
    return DTA_INT32, 4, 0


def _build_channels(track: dict, rename: bool):
    """Build a list of LDChannel objects from a parsed XRK track."""
    channels = []
    skipped = []

    def _safe_rate(rate, name, fallback=10):
        """Validate sample rate is in usable range (1..65535)."""
        try:
            r = int(rate)
        except (TypeError, ValueError):
            r = fallback
        if r <= 0 or r > 65535:
            print(f"  [xrk2ld] dropping channel '{name}' — implausible rate {rate} Hz",
                  file=sys.stderr)
            return None
        return r

    # GPS coordinates — always int32 with dec=7
    if "lat" in track and track["lat"] is not None:
        lat_data = track["lat"]
        lat_time = track["time"]
        span = float(lat_time[-1] - lat_time[0]) if len(lat_time) > 1 else 0.0
        if span > 0:
            lat_rate_calc = int(round(len(lat_data) / span))
        else:
            lat_rate_calc = 10
        lat_rate = _safe_rate(lat_rate_calc, "GPS Latitude") or 10
        channels.append(gps_lat_channel(lat_data, lat_rate))
        channels.append(gps_lon_channel(track["lon"], lat_rate))

    # Speed (GPS)
    if track.get("speed") is not None and len(track["speed"]) > 0:
        if np.any(track["speed"] != 0):
            spd = track["speed"]
            span = float(track["time"][-1] - track["time"][0]) if len(track["time"]) > 1 else 0.0
            rate_calc = int(round(len(spd) / span)) if span > 0 else 10
            rate = _safe_rate(rate_calc, "GPS Speed")
            if rate:
                channels.append(gps_speed_channel(spd, rate))

    # Other GPS channels (heading, altitude, satellites, etc.)
    for name, ch in track.get("gps_channels", {}).items():
        if name in GPS_LAT_NAMES or name in GPS_LON_NAMES or name in GPS_SPEED_NAMES:
            continue
        data = ch["data"]
        if len(data) == 0 or not np.any(np.isfinite(data)):
            continue
        rate = _safe_rate(ch.get("rate", 10) or 10, name)
        if rate is None:
            skipped.append(name)
            continue
        out_name, out_short = (map_name(name) if rename else (name, name[:8]))
        dta, sz, dec = _pick_dtype(data)
        channels.append(LDChannel(
            out_name, ch.get("unit", "") or "", rate, data,
            short_name=out_short,
            datatype_a=dta, data_size=sz, dec=dec,
        ))

    # All regular channels
    for name, ch in track.get("channels", {}).items():
        data = ch["data"]
        if len(data) == 0 or not np.any(np.isfinite(data)):
            continue
        rate = _safe_rate(ch.get("rate", 10) or 10, name)
        if rate is None:
            skipped.append(name)
            continue
        out_name, out_short = (map_name(name) if rename else (name, name[:8]))
        dta, sz, dec = _pick_dtype(data)
        channels.append(LDChannel(
            out_name, ch.get("unit", "") or "", rate, data,
            short_name=out_short,
            datatype_a=dta, data_size=sz, dec=dec,
        ))

    return channels


def convert_xrk(xrk_path, out_base=None, *,
                driver=None, vehicle=None, venue=None,
                event=None, session="", comment="",
                rename=False, raw_gps=False, quiet=False):
    """Convert one .xrk file → .ld + .ldx pair."""
    def log(msg):
        if not quiet:
            print(msg)

    log(f"Reading {xrk_path} …")
    track = parse_xrk(xrk_path, use_raw_gps=raw_gps)
    meta = track["meta"]
    n = len(track["lat"])
    duration = float(track["time"][-1] - track["time"][0]) if n > 1 else 0.0
    log(f"  Records: {n}, duration: {duration:.1f}s ({duration/60:.1f}min)")
    log(f"  GPS speed: {track['speed'].min():.1f} – {track['speed'].max():.1f}")
    log(f"  Channels found: {len(track['channels'])} regular, "
        f"{len(track['gps_channels'])} GPS")

    # Lap times come directly from the DLL
    lap_times_pairs = track.get("lap_times", [])
    log(f"  Laps: {len(lap_times_pairs)}")
    for i, (st, dur) in enumerate(lap_times_pairs[:3]):
        mm = int(dur // 60); ss = dur % 60
        log(f"    Lap {i+1}: {mm}:{ss:06.3f} (start {st:.1f}s)")
    if len(lap_times_pairs) > 3:
        log(f"    … and {len(lap_times_pairs)-3} more")

    # Build channels
    channels = _build_channels(track, rename=rename)

    # Beacon + Running Lap Time channels
    if lap_times_pairs:
        beacon_session_times = [st for st, _ in lap_times_pairs]
        # Also add session-end as final beacon if last lap has full duration
        last_st, last_dur = lap_times_pairs[-1]
        beacon_session_times.append(last_st + last_dur)

        # Choose a rate — typically GPS rate
        rate_hz = max(1, int(round(len(track["lat"]) / max(0.001, duration))))

        beacon_idx = [int(np.searchsorted(track["time"], t))
                      for t in beacon_session_times]
        channels.append(beacon_channel(len(track["time"]), rate_hz, beacon_idx))
        channels.append(running_lap_time_channel(
            track["time"], beacon_session_times, rate_hz))

    if not channels:
        raise RuntimeError("No usable channels found in XRK")

    # Output paths
    if out_base is None:
        out_base = os.path.splitext(xrk_path)[0]
    ld_path = out_base + ".ld"
    ldx_path = out_base + ".ldx"

    # Metadata defaults
    if driver is None:
        driver = meta.get("RACER", "")
    if vehicle is None:
        vehicle = meta.get("VEHICLE", "")
    if venue is None:
        venue = meta.get("TRACK", "")
    if event is None:
        event = meta.get("CHAMPIONSHIP", "") or venue or "Session"
    if not session:
        session = meta.get("SESSION_TYPE", "")

    motec_date = meta.get("DATE", "")
    motec_time = meta.get("TIME", "")

    log(f"Writing {ld_path} …")
    write_ld(
        ld_path, channels,
        driver=driver, vehicle=vehicle, venue=venue,
        event_name=event, session=session, comment=comment,
        date=motec_date, time=motec_time,
    )
    ld_size = os.path.getsize(ld_path)
    log(f"  OK ({ld_size:,} bytes, {len(channels)} channels)")

    log(f"Writing {ldx_path} …")
    write_ldx(
        ldx_path,
        [dur for _, dur in lap_times_pairs],
        event=event, venue=venue,
        driver=driver, vehicle=vehicle, session=session,
        log_date=motec_date, log_time=motec_time,
    )
    log(f"  OK ({len(lap_times_pairs)} lap markers)")

    return ld_path, ldx_path


def main():
    ap = argparse.ArgumentParser(
        prog="xrk2ld",
        description="Convert .xrk AiM race-data files to MoTeC i2 .ld + .ldx pairs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 2)[2] if __doc__ else None,
    )
    ap.add_argument("inputs", nargs="+", metavar="FILE",
                    help="One or more .xrk input files")
    ap.add_argument("-o", "--out", default=None,
                    help="Output base path or directory")
    ap.add_argument("--driver", default=None, help="Override driver name")
    ap.add_argument("--vehicle", default=None, help="Override vehicle id")
    ap.add_argument("--venue", default=None, help="Override venue/track name")
    ap.add_argument("--event", default=None, help="Override event name")
    ap.add_argument("--session", default="", help="Session label")
    ap.add_argument("--comment", default="", help="Short comment")
    ap.add_argument("--rename-channels", action="store_true",
                    help="Convert AiM channel names to MoTeC standard names")
    ap.add_argument("--raw-gps", action="store_true",
                    help="Use raw GPS data instead of processed")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="Only output errors and final paths")
    args = ap.parse_args()

    # Validate inputs
    for path in args.inputs:
        if not os.path.exists(path):
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            return 2
        if os.path.splitext(path)[1].lower() != ".xrk":
            print(f"ERROR: not an .xrk file: {path}", file=sys.stderr)
            return 2

    multi = len(args.inputs) > 1
    if multi and args.out and not os.path.isdir(args.out):
        if os.path.exists(args.out):
            print(f"ERROR: -o must be a directory for multiple inputs: {args.out}",
                  file=sys.stderr)
            return 2
        os.makedirs(args.out, exist_ok=True)

    results = []
    for xrk_path in args.inputs:
        if args.out:
            if multi or os.path.isdir(args.out):
                base = os.path.splitext(os.path.basename(xrk_path))[0]
                out_base = os.path.join(args.out, base)
            else:
                out_base = args.out
        else:
            out_base = None

        try:
            ld_path, ldx_path = convert_xrk(
                xrk_path, out_base=out_base,
                driver=args.driver, vehicle=args.vehicle,
                venue=args.venue, event=args.event,
                session=args.session, comment=args.comment,
                rename=args.rename_channels, raw_gps=args.raw_gps,
                quiet=args.quiet,
            )
            results.append((xrk_path, ld_path, ldx_path, None))
        except (RuntimeError, ValueError, FileNotFoundError) as e:
            print(f"ERROR converting {xrk_path}: {e}", file=sys.stderr)
            results.append((xrk_path, None, None, str(e)))
        if not args.quiet:
            print()

    ok = sum(1 for r in results if r[3] is None)
    fail = len(results) - ok
    if not args.quiet or fail > 0:
        print(f"--- {ok}/{len(results)} converted successfully ---")
        for src, ld_path, ldx_path, err in results:
            if err is None:
                print(f"  OK  {src}  →  {ld_path}")
            else:
                print(f"  FAIL  {src}: {err}", file=sys.stderr)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
