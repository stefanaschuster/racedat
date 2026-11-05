#!/usr/bin/env python3
"""ses2ld — Convert AiM/Racelogic .SES files to MoTeC i2 .ld + .ldx pairs.

The output `.ld` and `.ldx` files can be opened directly in MoTeC i2 for
side-by-side comparison with native MoTeC logs.

Usage:
  ses2ld.py FILE.SES [FILE2.SES ...] [-o OUT_DIR_OR_PREFIX]
                     [--driver NAME] [--vehicle ID] [--venue NAME]
                     [--event NAME] [--session SESSION] [--comment TEXT]

Examples:
  # Convert one file (output next to input, same basename)
  ses2ld.py session.ses

  # Convert multiple files
  ses2ld.py *.ses

  # Specify output base path (single file)
  ses2ld.py session.ses -o /tmp/converted

  # Override metadata
  ses2ld.py session.ses --driver "Stefan" --vehicle "CBR" --session "FP1"
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
    print("ERROR: numpy is required. Install with: sudo apt install python3-numpy",
          file=sys.stderr)
    sys.exit(2)

from parsers import parse_ses
from parsers.ld_writer import (
    write_ld,
    gps_lat_channel, gps_lon_channel, gps_speed_channel,
    battery_channel, beacon_channel, running_lap_time_channel,
)
from parsers.ldx_writer import write_ldx
from laps import detect_laps


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _ses_date_to_motec(ses_meta):
    """Convert SES DATE/TIME to MoTeC i2 friendly format."""
    date_in = ses_meta.get("DATE", "")
    time_in = ses_meta.get("TIME", "")
    motec_date = ""
    if date_in:
        for fmt in ("%d/%m/%y", "%y/%m/%d", "%d/%m/%Y"):
            try:
                d = _dt.datetime.strptime(date_in, fmt)
                if 1990 < d.year < 2100:
                    motec_date = d.strftime("%d/%m/%Y")
                    break
            except ValueError:
                continue
        if not motec_date:
            motec_date = date_in
    return motec_date, (time_in or "")


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert_ses(
    ses_path,
    out_base=None,
    driver=None, vehicle=None, venue=None,
    event=None, session="", comment="",
    quiet=False,
):
    """Convert one .SES file → .ld + .ldx pair.

    Returns (ld_path, ldx_path).
    """
    def log(msg):
        if not quiet:
            print(msg)

    log(f"Reading {ses_path} …")
    track = parse_ses(ses_path)
    meta = track["meta"]
    n = len(track["time"])
    duration = float(track["time"][-1] - track["time"][0]) if n > 1 else 0.0
    log(f"  Records: {n}, duration: {duration:.1f}s ({duration/60:.1f}min)")
    if n > 0:
        log(f"  GPS speed: {track['speed'].min():.1f} – {track['speed'].max():.1f} km/h")

    # Determine sample rate
    if n > 1:
        dt_median = float(np.median(np.diff(track["time"])))
        rate_hz = int(round(1.0 / dt_median)) if dt_median > 0 else 50
    else:
        rate_hz = 50
    log(f"  Sample rate: {rate_hz} Hz")

    # Detect laps
    laps = detect_laps(track)
    log(f"  Laps detected: {len(laps)}")
    for lap in laps[:3]:
        mm = int(lap['duration'] // 60)
        ss = lap['duration'] % 60
        log(f"    Lap {lap['lap_index']}: {mm}:{ss:06.3f}")
    if len(laps) > 3:
        log(f"    … and {len(laps)-3} more")

    # Build channels
    channels = []
    channels.append(gps_lat_channel(track["lat"], rate_hz))
    channels.append(gps_lon_channel(track["lon"], rate_hz))
    channels.append(gps_speed_channel(track["speed"], rate_hz))

    if track.get("battery") is not None and np.any(track["battery"] > 0.1):
        channels.append(battery_channel(track["battery"], rate_hz))

    # Beacon and running-lap-time channels
    beacon_session_times = []  # absolute seconds since session start
    if laps:
        beacon_session_times.append(laps[0]["start_time"])
        for lap in laps:
            beacon_session_times.append(lap["end_time"])

        time_arr = track["time"]
        beacon_idx = [int(np.searchsorted(time_arr, t)) for t in beacon_session_times]
        channels.append(beacon_channel(n, rate_hz, beacon_idx))
        channels.append(running_lap_time_channel(time_arr, beacon_session_times, rate_hz))

    # Output paths
    if out_base is None:
        out_base = os.path.splitext(ses_path)[0]
    ld_path = out_base + ".ld"
    ldx_path = out_base + ".ldx"

    # Metadata defaults from SES header
    if driver is None:
        driver = meta.get("NAME", "")
    if vehicle is None:
        vehicle = meta.get("VEHICLE", "")
    if venue is None:
        venue = meta.get("TRACK", "")
        venue = {"CATALUNY": "Catalunya"}.get(venue, venue)
    if event is None:
        event = venue if venue else "Session"

    motec_date, motec_time = _ses_date_to_motec(meta)

    # Write LD
    log(f"Writing {ld_path} …")
    write_ld(
        ld_path,
        channels,
        driver=driver,
        vehicle=vehicle,
        venue=venue,
        event_name=event,
        session=session,
        comment=comment,
        date=motec_date,
        time=motec_time,
    )
    ld_size = os.path.getsize(ld_path)
    log(f"  OK ({ld_size:,} bytes, {len(channels)} channels)")

    # Write LDX — uses lap DURATIONS (not absolute times)
    log(f"Writing {ldx_path} …")
    lap_durations = [lap["duration"] for lap in laps]
    write_ldx(
        ldx_path,
        lap_durations,
        event=event, venue=venue,
        driver=driver, vehicle=vehicle,
        session=session,
        log_date=motec_date, log_time=motec_time,
    )
    log(f"  OK ({len(lap_durations)} lap markers)")

    return ld_path, ldx_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        prog="ses2ld",
        description="Convert .SES race-data files to MoTeC i2 .ld + .ldx pairs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('\n', 2)[2] if __doc__ else None,
    )
    ap.add_argument("inputs", nargs="+", metavar="FILE",
                    help="One or more .SES input files")
    ap.add_argument("-o", "--out", default=None,
                    help="Output base path or directory. "
                         "For one input: full base path (e.g. -o /tmp/foo "
                         "produces /tmp/foo.ld + /tmp/foo.ldx). "
                         "For multiple inputs: target directory (filenames preserved).")
    ap.add_argument("--driver", default=None, help="Override driver name")
    ap.add_argument("--vehicle", default=None, help="Override vehicle id")
    ap.add_argument("--venue", default=None, help="Override venue/track name")
    ap.add_argument("--event", default=None, help="Override event name")
    ap.add_argument("--session", default="", help="Session label (e.g. 'FP1', 'Q1')")
    ap.add_argument("--comment", default="", help="Short comment")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="Only output errors and final paths")
    args = ap.parse_args()

    # Validate inputs
    for path in args.inputs:
        if not os.path.exists(path):
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            return 2
        if os.path.splitext(path)[1].lower() != ".ses":
            print(f"ERROR: not a .SES file: {path}", file=sys.stderr)
            return 2

    # Resolve output strategy
    multi = len(args.inputs) > 1
    if multi and args.out and not os.path.isdir(args.out):
        # If user gave -o for multiple inputs, it must be a directory
        if os.path.exists(args.out):
            print(f"ERROR: -o must be a directory when multiple inputs given: {args.out}",
                  file=sys.stderr)
            return 2
        os.makedirs(args.out, exist_ok=True)

    results = []
    for ses_path in args.inputs:
        if args.out:
            if multi or os.path.isdir(args.out):
                # Use args.out as directory, preserve filename
                base = os.path.splitext(os.path.basename(ses_path))[0]
                out_base = os.path.join(args.out, base)
            else:
                # Single file with explicit -o
                out_base = args.out
        else:
            out_base = None

        try:
            ld_path, ldx_path = convert_ses(
                ses_path, out_base=out_base,
                driver=args.driver, vehicle=args.vehicle,
                venue=args.venue, event=args.event,
                session=args.session, comment=args.comment,
                quiet=args.quiet,
            )
            results.append((ses_path, ld_path, ldx_path, None))
        except (ValueError, FileNotFoundError) as e:
            print(f"ERROR converting {ses_path}: {e}", file=sys.stderr)
            results.append((ses_path, None, None, str(e)))
        if not args.quiet:
            print()

    # Summary
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
