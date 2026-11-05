#!/usr/bin/env python3
"""reparse_laps.py — Re-parse all stored laps from their on-disk originals.

Use this to backfill richer per-lap data (e.g. the extra channels added in
v17 — RPM, throttle, lean angle, GForce, etc.) into the existing DB without
re-uploading anything.

What it does, for every row in the `laps` table:
  1. Look up the parent session's original file (`sessions.file_path`)
  2. Re-parse the original with the current parser (loads all channels)
  3. Detect laps, find the one matching `laps.lap_number`
  4. Run extract_lap_data() — produces the modern lap_data dict including
     extra_channels for SES/LD/CSV (and XRK).
  5. Replace the lap_blob in the DB. Everything else (session_id, owner,
     metadata, lap_number, duration_s) stays untouched.

Use --dry-run first to see what would happen. Use --apply to actually write.

Examples:
    python3 reparse_laps.py --data /var/lap_compare --dry-run
    python3 reparse_laps.py --data /var/lap_compare --apply
    python3 reparse_laps.py --data /var/lap_compare --apply --only-lap-id 42
    python3 reparse_laps.py --data /var/lap_compare --apply --verbose

The script is idempotent — running it twice on the same DB just rewrites
the same blobs. It does NOT modify session rows, the events table, the
user table, or any file on disk.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

# Make package imports work whether the script is run from the repo root
# or from inside the package directory.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from db import DB
from laps import detect_laps, extract_lap_data
from parsers import parse_ses, parse_ld, parse_xrk, parse_racebox_csv


def parse_track(filepath: str):
    """Same dispatcher logic as webserver.py — kept here so this script
    is standalone and doesn't import the webserver module."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".ses":
        return parse_ses(filepath)
    if ext == ".ld":
        return parse_ld(filepath)
    if ext in (".xrk", ".xrz"):
        return parse_xrk(filepath)
    if ext == ".csv":
        return parse_racebox_csv(filepath)
    raise ValueError(f"Unsupported extension: {ext}")


# Match the field shape used by the webserver's lap-flat listing
def _list_target_laps(db: DB, only_lap_id):
    """Return [(lap_id, session_id, lap_number, file_path, original_filename,
                old_duration, fmt)]"""
    laps = db.list_all_laps_flat()
    if only_lap_id is not None:
        laps = [lp for lp in laps if lp["lap_id"] == only_lap_id]
    return laps


def reparse_one_lap(db: DB, lap_row: dict, *,
                    apply: bool, verbose: bool) -> dict:
    """Reparse a single lap. Returns a result dict for the summary."""
    lap_id = lap_row["lap_id"]
    session_id = lap_row["session_id"]
    lap_number = lap_row["lap_number"]
    file_path = lap_row["file_path"]
    fname = lap_row.get("original_filename") or ""
    old_dur = lap_row.get("duration_s")

    result = {
        "lap_id": lap_id,
        "session_id": session_id,
        "lap_number": lap_number,
        "file_path": file_path,
        "filename": fname,
        "status": "skip",
        "reason": "",
        "old_duration": old_dur,
        "new_duration": None,
        "extra_channels": 0,
    }

    if not file_path:
        result["reason"] = "no file_path in session row"
        return result
    p = Path(file_path)
    if not p.is_file():
        result["reason"] = f"file missing on disk: {file_path}"
        return result

    try:
        track = parse_track(str(p))
    except Exception as e:
        result["status"] = "error"
        result["reason"] = f"parse failed: {type(e).__name__}: {e}"
        if verbose:
            traceback.print_exc()
        return result

    try:
        laps = detect_laps(track)
    except Exception as e:
        result["status"] = "error"
        result["reason"] = f"lap-detect failed: {type(e).__name__}: {e}"
        return result

    if not laps:
        result["reason"] = "no laps detected in re-parse"
        return result

    # Find the lap with the matching lap_number
    target = next((lp for lp in laps if lp["lap_index"] == lap_number), None)
    if target is None:
        avail = ", ".join(str(lp["lap_index"]) for lp in laps)
        result["status"] = "error"
        result["reason"] = (f"lap {lap_number} not found after re-parse "
                            f"(available: {avail})")
        return result

    try:
        lap_data = extract_lap_data(track, target)
    except Exception as e:
        result["status"] = "error"
        result["reason"] = f"extract failed: {type(e).__name__}: {e}"
        return result

    extras = lap_data.get("extra_channels") or {}
    result["extra_channels"] = len(extras)
    result["new_duration"] = float(lap_data.get("duration") or 0.0)

    if apply:
        # IMPORTANT: keep the existing duration_s — that's the authoritative
        # value from the original upload (picker). Only the blob changes.
        ok = db.update_lap_blob(lap_id, lap_data, duration_s=None)
        if not ok:
            result["status"] = "error"
            result["reason"] = "DB update returned 0 rows"
            return result
        result["status"] = "updated"
    else:
        result["status"] = "would-update"
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Re-parse all stored laps from their on-disk originals "
                    "and refresh the in-DB lap data (with all channels).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--data", required=True,
                    help="Path to the data directory (contains sessions.db)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write the changes. Without this flag the "
                         "script runs in dry-run mode and only prints what "
                         "WOULD be done.")
    ap.add_argument("--only-lap-id", type=int, default=None,
                    help="Process only the lap with this ID (useful for "
                         "testing a single entry).")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Print full tracebacks on parse errors.")
    args = ap.parse_args()

    if args.apply and args.only_lap_id is None:
        print(
            "  ⚠  --apply will rewrite ALL lap blobs in the database.\n"
            "      The originals on disk are untouched, but the DB blob will\n"
            "      be replaced by the new extract. Press Ctrl-C now to abort,\n"
            "      otherwise this starts in 3 seconds…", flush=True,
        )
        try:
            time.sleep(3)
        except KeyboardInterrupt:
            print("\nAborted.")
            return 1

    data_dir = Path(args.data).expanduser().resolve()
    db_path = data_dir / "sessions.db"
    if not db_path.is_file():
        sys.stderr.write(f"ERROR: sessions.db not found in {data_dir}\n")
        return 2

    db = DB(db_path)
    targets = _list_target_laps(db, args.only_lap_id)
    if not targets:
        print("No laps found." +
              (f" (--only-lap-id={args.only_lap_id})" if args.only_lap_id else ""))
        return 0

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== reparse_laps · {mode} · {len(targets)} lap(s) to process ===\n")

    n_updated = 0
    n_skipped = 0
    n_errors = 0
    t0 = time.time()

    for i, lap_row in enumerate(targets, 1):
        # Compact log line per lap
        prefix = f"[{i:>3}/{len(targets)}] lap#{lap_row['lap_id']:<4}"
        result = reparse_one_lap(db, lap_row, apply=args.apply,
                                 verbose=args.verbose)
        st = result["status"]
        fname = result["filename"][:40] if result["filename"] else "?"
        extra = f"extras={result['extra_channels']}"
        if st in ("updated", "would-update"):
            n_updated += 1
            marker = "→" if args.apply else "·"
            print(f"  {prefix} {marker} {st:<14} {fname:<42} {extra}")
        elif st == "error":
            n_errors += 1
            print(f"  {prefix} ✗ ERROR          {fname:<42} {result['reason']}")
        else:
            n_skipped += 1
            print(f"  {prefix} – {st:<14} {fname:<42} {result['reason']}")

    dt = time.time() - t0
    print()
    print(f"=== Done in {dt:.1f}s ===")
    print(f"  {'Updated' if args.apply else 'Would update'}: {n_updated}")
    print(f"  Skipped:        {n_skipped}")
    print(f"  Errors:         {n_errors}")
    if not args.apply and n_updated > 0:
        print()
        print("  ↪ Re-run with --apply to write the changes.")
    return 0 if n_errors == 0 else 3


if __name__ == "__main__":
    sys.exit(main() or 0)
