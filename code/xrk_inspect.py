#!/usr/bin/env python3
"""xrk_inspect — dump the channel structure of an .xrk file via libxrk.

Useful for diagnosing files where the lap-time is detected but the graphs
appear empty. Run on the server where libxrk is installed:

    python3 xrk_inspect.py path/to/file.xrk

Output shows:
  - metadata fields
  - laps (start_time / end_time / duration)
  - each channel: name, columns, sample count, time range, value range
  - explicit check for GPS Latitude / Longitude / Speed presence
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="Path to .xrk or .xrz file")
    ap.add_argument("--values", action="store_true",
                    help="Also print first 5 samples of each channel")
    args = ap.parse_args()

    try:
        from libxrk import aim_xrk
    except ImportError:
        print("ERROR: libxrk not installed. "
              "pip3 install --user --break-system-packages libxrk",
              file=sys.stderr)
        sys.exit(1)

    import numpy as np

    print(f"=== Opening {args.file} ===")
    log = aim_xrk(args.file)

    print()
    print("--- Metadata ---")
    md = getattr(log, "metadata", None)
    if md is None:
        print("  (no metadata)")
    else:
        if isinstance(md, dict):
            items = md.items()
        else:
            items = ((k, getattr(md, k)) for k in dir(md)
                     if not k.startswith("_")
                     and not callable(getattr(md, k, None)))
        for k, v in items:
            print(f"  {k!r}: {v!r}")

    print()
    print("--- Laps ---")
    laps = getattr(log, "laps", None)
    if laps is None:
        print("  (no laps)")
    elif laps.num_rows == 0:
        print("  (0 laps)")
    else:
        try:
            print(f"  Columns: {list(laps.column_names)}")
        except Exception:
            pass
        for i in range(min(laps.num_rows, 20)):
            try:
                num = laps.column("num")[i].as_py()
            except Exception:
                num = "?"
            try:
                st = laps.column("start_time")[i].as_py()
                et = laps.column("end_time")[i].as_py()
                dur_ms = et - st
                print(f"  Lap {num}: start={st} end={et}  duration={dur_ms/1000:.3f}s")
            except Exception as e:
                print(f"  Lap {num}: <error reading: {e}>")
        if laps.num_rows > 20:
            print(f"  ... and {laps.num_rows - 20} more")

    print()
    print("--- Channels ---")
    chs = log.channels
    print(f"Total: {len(chs)} channels")
    print()

    gps_found = []
    for name, table in chs.items():
        try:
            cols = list(table.column_names)
        except Exception:
            cols = "<no column_names attr>"
        nrows = getattr(table, "num_rows", "?")
        print(f"  {name!r}")
        print(f"    columns:    {cols}")
        print(f"    rows:       {nrows}")

        # Time range
        if isinstance(cols, list):
            t_col = None
            for cand in ("timecodes", "Time", "time", "t"):
                if cand in cols:
                    t_col = cand
                    break
            if t_col:
                try:
                    arr = np.asarray(table.column(t_col).to_numpy(zero_copy_only=False))
                    if len(arr):
                        print(f"    time range: {float(arr.min())} .. {float(arr.max())} (ms)")
                except Exception as e:
                    print(f"    time error: {e}")

            # Value cols
            value_cols = [c for c in cols if c != t_col]
            for vc in value_cols:
                try:
                    arr = np.asarray(table.column(vc).to_numpy(zero_copy_only=False), dtype=np.float64)
                    if len(arr):
                        amin, amax = float(np.nanmin(arr)), float(np.nanmax(arr))
                        print(f"    '{vc}' values: {amin:.4g} .. {amax:.4g} ({len(arr)} samples)")
                        if args.values:
                            print(f"      first 5: {arr[:5].tolist()}")
                        # Flag potential lat/lon
                        if -90 <= amin and amax <= 90 and 'lat' in vc.lower():
                            gps_found.append((name, vc, "Latitude-like"))
                        if -180 <= amin and amax <= 180 and 'lon' in vc.lower():
                            gps_found.append((name, vc, "Longitude-like"))
                except Exception as e:
                    print(f"    '{vc}' error: {e}")
        print()

    print("--- Summary ---")
    if gps_found:
        print("  GPS-like channels found:")
        for parent, sub, kind in gps_found:
            print(f"    {kind}: parent={parent!r}, sub={sub!r}")
    else:
        print("  ⚠ NO obvious latitude/longitude channels found.")
        print("    The XRK reader expects channels containing 'Lat'/'Lon' in")
        print("    their names. Send this output to the developer to add support.")


if __name__ == "__main__":
    main()
