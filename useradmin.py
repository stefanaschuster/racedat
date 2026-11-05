#!/usr/bin/env python3
"""useradmin — minimal CLI for user management on the server.

Run on the server (alongside webserver.py).

Examples:
  python3 useradmin.py add stefan@example.com
  python3 useradmin.py add admin@example.com --admin
  python3 useradmin.py list
  python3 useradmin.py promote stefan@example.com
  python3 useradmin.py demote admin@example.com
  python3 useradmin.py passwd stefan@example.com
  python3 useradmin.py delete stefan@example.com

The default data directory is /var/lap_compare, matching webserver.py.
Override with --data.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# Make sibling modules importable
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from db import DB


def _prompt_password(prompt: str = "Passwort") -> str:
    """Prompt the user twice for a password and return it.
    Aborts (SystemExit) if the two don't match or it's too short."""
    p1 = getpass.getpass(f"{prompt}: ")
    if len(p1) < 6:
        print("Passwort muss mindestens 6 Zeichen haben.", file=sys.stderr)
        sys.exit(2)
    p2 = getpass.getpass(f"{prompt} (Wiederholung): ")
    if p1 != p2:
        print("Passwörter stimmen nicht überein.", file=sys.stderr)
        sys.exit(2)
    return p1


def _open_db(data_dir: Path) -> DB:
    db_path = data_dir / "sessions.db"
    if not db_path.exists():
        print(f"Datenbank existiert noch nicht ({db_path}). "
              f"Sie wird beim Anlegen des ersten Users automatisch erzeugt.",
              file=sys.stderr)
    return DB(db_path)


def cmd_add(args):
    db = _open_db(args.data)
    email = args.email.strip().lower()
    if db.get_user_by_email(email):
        print(f"User '{email}' existiert bereits.", file=sys.stderr)
        sys.exit(1)
    password = _prompt_password()
    uid = db.create_user(email=email, password=password, is_admin=args.admin)
    role = "Admin" if args.admin else "User"
    print(f"✓ {role} '{email}' angelegt (id={uid}).")


def cmd_list(args):
    db = _open_db(args.data)
    users = db.list_users()
    if not users:
        print("(keine User vorhanden)")
        return
    # Pretty list
    w_email = max(len(u["email"]) for u in users)
    print(f"  {'ID':>4}  {'EMAIL'.ljust(w_email)}  ROLE   CREATED")
    print("  ---- " + "-" * (w_email + 2) + "------ -------------------")
    for u in users:
        role = "ADMIN" if u["is_admin"] else "user "
        print(f"  {u['id']:>4}  {u['email'].ljust(w_email)}  {role}  {u['created_at']}")


def _resolve_user_id(db: DB, email: str) -> int:
    rec = db.get_user_by_email(email)
    if not rec:
        print(f"User '{email}' nicht gefunden.", file=sys.stderr)
        sys.exit(1)
    return rec["id"]


def cmd_promote(args):
    db = _open_db(args.data)
    uid = _resolve_user_id(db, args.email)
    if db.set_admin(uid, True):
        print(f"✓ '{args.email}' ist jetzt Admin.")
    else:
        print("Keine Änderung.", file=sys.stderr)


def cmd_demote(args):
    db = _open_db(args.data)
    uid = _resolve_user_id(db, args.email)
    if db.set_admin(uid, False):
        print(f"✓ '{args.email}' ist nicht mehr Admin.")
    else:
        print("Keine Änderung.", file=sys.stderr)


def cmd_passwd(args):
    db = _open_db(args.data)
    uid = _resolve_user_id(db, args.email)
    password = _prompt_password("Neues Passwort")
    if db.update_user_password(uid, password):
        print(f"✓ Passwort für '{args.email}' geändert.")
    else:
        print("Keine Änderung.", file=sys.stderr)


def cmd_delete(args):
    db = _open_db(args.data)
    uid = _resolve_user_id(db, args.email)
    if not args.yes:
        confirm = input(f"User '{args.email}' wirklich löschen? [y/N] ").strip().lower()
        if confirm not in ("y", "j", "yes", "ja"):
            print("Abgebrochen.")
            return
    # v22.12 — Profil-/Bike-Bilder vor dem User-Delete auf Disk räumen.
    # Die FK-Cascade in der DB löscht die Rows, lässt aber Dateien stehen.
    # Wir sammeln die Filenames zuerst und löschen sie nach dem User-DELETE,
    # damit ein DB-Crash dazwischen nicht zu Waisen auf Disk führt.
    img_dir = args.data / "profile_images"
    to_unlink = []
    try:
        prof = db.get_profile(uid)
        if prof.get("image_path"):
            to_unlink.append(prof["image_path"])
        for b in db.list_bikes(uid):
            if b.get("image_path"):
                to_unlink.append(b["image_path"])
    except Exception as e:
        print(f"  Warnung: konnte Bilder nicht erfassen: {e}", file=sys.stderr)
    if db.delete_user(uid):
        # Erst nach erfolgreichem DB-Delete die Dateien anfassen
        unlinked = 0
        for fname in to_unlink:
            p = img_dir / fname
            try:
                p.unlink()
                unlinked += 1
            except (FileNotFoundError, OSError):
                pass
        print(f"✓ User '{args.email}' gelöscht.")
        if to_unlink:
            print(f"  {unlinked}/{len(to_unlink)} Profil-/Bike-Bild(er) entfernt.")
        print("  Hinweis: hochgeladene Sessions des Users sind jetzt verwaist "
              "(nur Admins können sie löschen).")
    else:
        print("Keine Änderung.", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="User-Verwaltung für den Lap-Compare-Webserver.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--data", type=Path, default=Path("/var/lap_compare"),
                    help="Daten-Verzeichnis (default: /var/lap_compare)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add", help="Neuen User anlegen")
    s.add_argument("email")
    s.add_argument("--admin", action="store_true", help="Als Admin anlegen")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("list", help="Alle User auflisten")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("promote", help="User zum Admin machen")
    s.add_argument("email")
    s.set_defaults(func=cmd_promote)

    s = sub.add_parser("demote", help="Admin-Rechte entziehen")
    s.add_argument("email")
    s.set_defaults(func=cmd_demote)

    s = sub.add_parser("passwd", help="Passwort eines Users ändern")
    s.add_argument("email")
    s.set_defaults(func=cmd_passwd)

    s = sub.add_parser("delete", help="User löschen")
    s.add_argument("email")
    s.add_argument("-y", "--yes", action="store_true",
                   help="Ohne Rückfrage löschen")
    s.set_defaults(func=cmd_delete)

    args = ap.parse_args()
    args.data = args.data.expanduser().resolve()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
