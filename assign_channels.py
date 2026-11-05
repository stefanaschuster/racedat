#!/usr/bin/env python3
"""assign_channels.py — v22.6 — Bulk-Zuordnung Standardkanäle ↔ Datenkanäle.

Für jeden Lap in der DB:
  1. Lese das Lap-Blob.
  2. Schaue, welche Datenkanäle (`extra_channels`) im Lap vorhanden sind.
  3. Vergleiche gegen die Mapping-Datei `parsers/channel_map.txt`. Trifft
     einer der Datenkanal-Namen aus der Datei auf einen Channel im Lap
     (case-insensitiver Exakt-Match auf `name`-Feld), wird die zugehörige
     Standardkanal-Rolle dem Channel zugewiesen.
  4. **Respektiert bestehende Zuordnungen**: ist eine Rolle schon belegt
     (Stefan hat manuell zugewiesen, oder ein voriger Upload-Suggest war
     korrekt), wird sie NICHT überschrieben — nur leere Slots werden
     gefüllt.
  5. Schreibt den Lap-Blob nur, wenn sich tatsächlich etwas geändert hat.

Standard-Modus ist `--dry-run` (zeigt nur was passieren würde). Erst
`--apply` schreibt in die DB.

Beispiele:
    python3 assign_channels.py --data /var/lap_compare                # dry-run
    python3 assign_channels.py --data /var/lap_compare --apply
    python3 assign_channels.py --data /var/lap_compare --apply --only-lap-id 42
    python3 assign_channels.py --data /var/lap_compare --apply --verbose

Wichtige Designentscheidungen:
  - Match ist case-insensitiv und exakt (auf `name`-Feld). Substring-
    oder Regex-Match wäre verwirrend für eine vom User gepflegte Liste.
  - Wenn mehrere Channels im Lap zur selben Rolle matchen: der erste
    Treffer in der Reihenfolge der Datei gewinnt. Reihenfolge der
    Channels innerhalb des Laps ist nicht deterministisch.
  - Wenn mehrere Rollen denselben Channel beanspruchen würden: jede
    Rolle wird unabhängig vergeben. Der Channel kann mehrfach
    zugewiesen werden — das ist OK, semantisch sind verschiedene
    Rollen auch verschiedene Wendungen desselben Signals.
  - Skript modifiziert NUR `lap_data['channel_roles']`. Alles andere
    (session-meta, lap_blob-Größe, original_file etc.) bleibt unangefasst.

Idempotent: zweites Mal laufen ändert nichts mehr.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from db import DB
from parsers.channel_roles import (
    CHANNEL_MAP,
    STANDARDKANAL_TO_ROLE_ID,
    ROLES,
)


def build_lookup_table(channel_map):
    """Build a flat list of (datenkanal_name_lower, role_id) tuples in
    file-order. Used to match channels case-insensitively.

    File-order matters: if a lap has BOTH 'phi_lean' and 'LeanAngle',
    we pick the one listed first in the file.
    """
    out = []
    for label, names in channel_map.items():
        rid = STANDARDKANAL_TO_ROLE_ID.get(label)
        if not rid:
            continue
        for n in names:
            out.append((n.lower(), rid, n))   # (key, role_id, original)
    return out


def find_matches(extras, lookup):
    """Given a lap's extra_channels dict and the flat lookup table,
    return {role_id: channel_id} for every matched role. Earlier
    entries in `lookup` win.

    `extras` is {channel_id: {name, unit, data}}.
    """
    # Index extras by lowercased name for fast lookup
    extras_by_lname = {}
    for cid, ch in (extras or {}).items():
        name = (ch.get("name") or "").strip()
        if name:
            # First channel with this name wins — duplicates in
            # extras are unlikely but possible (different source files)
            extras_by_lname.setdefault(name.lower(), cid)

    out = {}
    for key, rid, _orig in lookup:
        if rid in out:
            continue   # already matched earlier in file order
        cid = extras_by_lname.get(key)
        if cid:
            out[rid] = cid
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True,
        help="Datenverzeichnis (enthält sessions.db)")
    ap.add_argument("--apply", action="store_true",
        help="Wirklich schreiben. Ohne --apply nur Dry-Run.")
    ap.add_argument("--only-lap-id", type=int, default=None,
        help="Nur diesen einen Lap behandeln (zum Debuggen)")
    ap.add_argument("--verbose", "-v", action="store_true",
        help="Pro-Lap-Output, auch wenn nichts geändert wird")
    args = ap.parse_args()

    data_dir = Path(args.data)
    db_path = data_dir / "sessions.db"
    if not db_path.is_file():
        print(f"ERROR: sessions.db nicht gefunden: {db_path}", file=sys.stderr)
        sys.exit(2)

    if not CHANNEL_MAP:
        print("ERROR: CHANNEL_MAP ist leer (parsers/channel_map.txt fehlt "
              "oder ist leer). Skript kann nichts tun.", file=sys.stderr)
        sys.exit(2)

    db = DB(db_path)
    lookup = build_lookup_table(CHANNEL_MAP)

    # Welche Laps untersuchen?
    if args.only_lap_id is not None:
        rows = [r for r in db.list_all_laps_flat()
                if int(r["lap_id"]) == args.only_lap_id]
        if not rows:
            print(f"ERROR: Lap {args.only_lap_id} nicht gefunden",
                  file=sys.stderr)
            sys.exit(2)
    else:
        rows = db.list_all_laps_flat()

    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Laps zu prüfen: {len(rows)}")
    print(f"Standardkanäle in Map: "
          f"{', '.join(CHANNEL_MAP.keys())}")
    print()

    n_changed = 0
    n_unchanged = 0
    n_no_extras = 0
    role_id_to_label = {r["id"]: r["label"] for r in ROLES}

    for row in rows:
        lap_id = int(row["lap_id"])
        try:
            lap = db.get_lap(lap_id)
            if lap is None:
                continue
            lap_data = lap["lap_data"]
        except Exception as e:
            print(f"  lap_id={lap_id}: FEHLER beim Laden: {e}",
                  file=sys.stderr)
            continue

        extras = lap_data.get("extra_channels") or {}
        if not extras:
            n_no_extras += 1
            if args.verbose:
                print(f"  lap_id={lap_id}: keine Datenkanäle — skip")
            continue

        existing = dict(lap_data.get("channel_roles") or {})
        matches = find_matches(extras, lookup)

        # NUR leere Slots füllen — bestehende Zuordnungen respektieren
        # (Stefan: "respektieren").
        new_assignments = {
            rid: cid for rid, cid in matches.items()
            if rid not in existing
        }

        if not new_assignments:
            n_unchanged += 1
            if args.verbose:
                already = ", ".join(f"{role_id_to_label.get(r,r)}={c}"
                                     for r, c in existing.items())
                print(f"  lap_id={lap_id}: nichts neu zuzuordnen "
                      f"(bereits: {already or 'keine'})")
            continue

        # Zeige was wir tun würden
        added = ", ".join(
            f"{role_id_to_label.get(rid, rid)} → {extras[cid].get('name', cid)}"
            for rid, cid in new_assignments.items()
        )
        prefix = "WOULD ADD" if not args.apply else "ADD"
        print(f"  lap_id={lap_id}: {prefix}: {added}")

        if args.apply:
            merged = dict(existing)
            merged.update(new_assignments)
            lap_data["channel_roles"] = merged
            try:
                db.update_lap_blob(lap_id, lap_data)
                n_changed += 1
            except Exception as e:
                print(f"  lap_id={lap_id}: FEHLER beim Schreiben: {e}",
                      file=sys.stderr)
        else:
            n_changed += 1

    print()
    print(f"Ergebnis:")
    print(f"  Laps mit neuen Zuordnungen: {n_changed}")
    print(f"  Laps unverändert (schon ok oder keine Treffer): {n_unchanged}")
    print(f"  Laps ohne Datenkanäle: {n_no_extras}")
    if not args.apply:
        print()
        print("Dies war ein DRY-RUN. Mit --apply tatsächlich schreiben.")


if __name__ == "__main__":
    main()
