#!/usr/bin/env python3
"""lap_compare — compare the fastest laps from two race-data logger files.

Supports .ses (AiM/Racelogic), .ld (MoTeC), and .xrk/.xrz (AiM RaceStudio)
inputs. Generates a single-file HTML report.

Usage:
  lap_compare.py FILE_A FILE_B [--out report.html] [--lap-a N] [--lap-b N]
  lap_compare.py FILE [--lap-a N --lap-b N] [--out report.html]   # one file, two laps
  lap_compare.py FILE --list                                       # list laps and exit

Note: For .xrk/.xrz files you need to install libxrk:
  pip3 install --user --break-system-packages libxrk
"""
import argparse
import os
import sys
from pathlib import Path

# Make sibling modules importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as _numpy_check  # noqa: F401
except ImportError:
    print(
        "❌ Das Python-Modul 'numpy' fehlt.\n"
        "   Installation:\n"
        "     • Debian/Ubuntu:  sudo apt install python3-numpy\n"
        "     • Fedora:         sudo dnf install python3-numpy\n"
        "     • Arch:           sudo pacman -S python-numpy\n"
        "     • Per pip:        pip3 install --user numpy",
        file=sys.stderr,
    )
    sys.exit(2)

from parsers import parse_ses, parse_ld, parse_xrk, parse_racebox_csv, parse_i2m
from laps import detect_laps, fastest_lap, extract_lap_data
from compare import align_laps, hot_zones
from report import build_html_report


def parse_track(filepath: str):
    """Dispatch by file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".ses":
        return parse_ses(filepath)
    if ext == ".ld":
        return parse_ld(filepath)
    if ext in (".xrk", ".xrz"):
        return parse_xrk(filepath)
    if ext == ".csv":
        return parse_racebox_csv(filepath)
    if ext == ".dat":
        return parse_i2m(filepath)
    raise ValueError(
        f"Unsupported file extension: {ext} — "
        f"expected .ses, .ld, .xrk, .xrz, .csv (RaceBox Fastlap), or .dat (I2M)"
    )


def fmt_lap(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"


def print_lap_list(track, laps, label=""):
    print(f"\n--- Laps in {os.path.basename(track['source_file'])} {label} ---")
    print(f"  Format: {track['source_format']}, total samples: {len(track['time'])}")
    if not laps:
        print("  ⚠  No laps detected.")
        return
    fastest = fastest_lap(laps)
    for lap in laps:
        marker = "★" if lap is fastest else " "
        print(f"  {marker} Lap {lap['lap_index']:>3}: {fmt_lap(lap['duration'])}  "
              f"(t={lap['start_time']:.1f}s → {lap['end_time']:.1f}s, method={lap['method']})")
    print(f"  Fastest: Lap {fastest['lap_index']} = {fmt_lap(fastest['duration'])}")


def select_lap(laps, requested_idx):
    """Find the lap whose lap_index matches `requested_idx`. None means take the fastest."""
    if requested_idx is None:
        return fastest_lap(laps)
    for lap in laps:
        if lap["lap_index"] == requested_idx:
            return lap
    raise ValueError(
        f"Lap {requested_idx} not found. Available: "
        + ", ".join(str(l["lap_index"]) for l in laps)
    )


def main():
    ap = argparse.ArgumentParser(
        description="Compare fastest laps from two .ses, .ld or .xrk race-data files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("files", nargs="+",
                    help="One or two race-data files (.ses, .ld, .xrk, .xrz)")
    ap.add_argument("--out", "-o", default=None,
                    help="Output HTML path (default: lap_compare_report.html next to file A)")
    ap.add_argument("--lap-a", type=int, default=None,
                    help="Specific lap index in file A (default: fastest)")
    ap.add_argument("--lap-b", type=int, default=None,
                    help="Specific lap index in file B (default: fastest)")
    ap.add_argument("--list", action="store_true",
                    help="Just list all detected laps and exit")
    ap.add_argument("--no-gps-anchor", action="store_true",
                    help="Don't auto-shift lap B to align start position with lap A "
                         "(useful if both files were logged with the same S/F line)")
    args = ap.parse_args()

    if len(args.files) not in (1, 2):
        ap.error("Provide one or two input files.")

    # Single-file mode
    if len(args.files) == 1:
        path = args.files[0]
        track = parse_track(path)
        laps = detect_laps(track)

        if args.list:
            print_lap_list(track, laps)
            return 0

        if len(laps) < 2:
            print(f"❌ Need at least two laps in single-file mode, found {len(laps)}.")
            print_lap_list(track, laps)
            return 2

        # Default: fastest two laps
        sorted_laps = sorted(laps, key=lambda l: l["duration"])
        lap_a_meta = select_lap(laps, args.lap_a) if args.lap_a is not None else sorted_laps[0]
        lap_b_meta = select_lap(laps, args.lap_b) if args.lap_b is not None else sorted_laps[1]

        if lap_a_meta is lap_b_meta:
            print("❌ Lap A and Lap B are identical — pick different --lap-a / --lap-b values.")
            return 2

        track_a = track_b = track
    else:
        # Two-file mode
        track_a = parse_track(args.files[0])
        track_b = parse_track(args.files[1])
        laps_a = detect_laps(track_a)
        laps_b = detect_laps(track_b)

        if args.list:
            print_lap_list(track_a, laps_a, "(A)")
            print_lap_list(track_b, laps_b, "(B)")
            return 0

        if not laps_a:
            print(f"❌ No laps detected in file A: {args.files[0]}")
            return 2
        if not laps_b:
            print(f"❌ No laps detected in file B: {args.files[1]}")
            return 2

        lap_a_meta = select_lap(laps_a, args.lap_a)
        lap_b_meta = select_lap(laps_b, args.lap_b)

    # Print the laps we picked
    print(f"\nLap A: {os.path.basename(track_a['source_file'])} "
          f"({track_a['source_format']}) — Lap {lap_a_meta['lap_index']} = {fmt_lap(lap_a_meta['duration'])}")
    print(f"Lap B: {os.path.basename(track_b['source_file'])} "
          f"({track_b['source_format']}) — Lap {lap_b_meta['lap_index']} = {fmt_lap(lap_b_meta['duration'])}")

    # Extract & align
    lap_a_data = extract_lap_data(track_a, lap_a_meta)
    lap_b_data = extract_lap_data(track_b, lap_b_meta)
    aligned = align_laps(lap_a_data, lap_b_data, n_samples=1000,
                         gps_anchor=not args.no_gps_anchor)
    zones = hot_zones(aligned)

    # Surface alignment info to the user
    align_info = aligned.get("alignment", {})
    if align_info.get("gps_anchor_used"):
        shift_m = align_info.get("shift_distance_m", 0.0)
        match_m = align_info.get("anchor_match_distance_m", 0.0)
        if abs(shift_m) >= 1:
            print(f"\nGPS-Anchor: lap B shifted by {shift_m:.0f}m to align start "
                  f"(closest GPS point {match_m:.1f}m from lap A's start)")
        if align_info.get("anchor_warning"):
            print(f"⚠  {align_info['anchor_warning']}")

    # Build report
    html = build_html_report(
        track_a, lap_a_meta, lap_a_data,
        track_b, lap_b_meta, lap_b_data,
        aligned, zones,
    )

    # Decide output path
    if args.out:
        out_path = args.out
    else:
        out_dir = os.path.dirname(os.path.abspath(args.files[0]))
        a_base = os.path.splitext(os.path.basename(args.files[0]))[0]
        b_base = (os.path.splitext(os.path.basename(args.files[1]))[0]
                  if len(args.files) == 2 else "internal")
        out_path = os.path.join(out_dir, f"lap_compare_{a_base}_vs_{b_base}.html")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    delta = lap_b_meta["duration"] - lap_a_meta["duration"]
    print(f"\nΔ total: {delta:+.3f} s  (B {'slower' if delta > 0 else 'faster'} than A)")
    print(f"Largest loss: {zones['max_loss']['value_s']*1000:.0f} ms @ {zones['max_loss']['distance_m']:.0f} m")
    print(f"Largest gain: {abs(zones['max_gain']['value_s'])*1000:.0f} ms @ {zones['max_gain']['distance_m']:.0f} m")
    print(f"\n✓ Report written to: {out_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError as e:
        print(f"❌ Datei nicht gefunden: {e.filename}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        sys.exit(130)
