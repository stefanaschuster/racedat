#!/usr/bin/env python3
"""Daten vom alten Racedat-Server in eine nativeAI-App übernehmen.

Übernimmt: sessions.db (konsistent per SQLite-Backup-API, WAL-sicher),
originals/, reports/, analyses/, profile_images/, server_secret (damit
Login-Cookies/Tokens gültig bleiben) und optional adhoc_uploads/.
Dateipfade in der DB (sessions.file_path, events.file_path) werden auf das
neue Datenverzeichnis umgeschrieben.

Schutzregeln:
  * Zielverzeichnis wird nie ungefragt überschrieben: bestehende Dateien
    mit anderem Inhalt bleiben unangetastet und werden gemeldet.
  * sessions.db im Ziel wird nur ersetzt, wenn sie leer ist (keine Nutzer
    und keine Sessions) — außer mit --replace-db (dann Sicherung als
    sessions.db.bak-<zeit>).
  * Quelle wird nur gelesen.

Ablauf:
  1. Neue App in nativeAI anlegen, einmal starten lassen (legt data/ an),
     dann App STOPPEN.
  2. python3 migrate_data.py --src /var/lap_compare --dst <App>/data --dry-run
  3. gleiches ohne --dry-run
  4. App starten, mit altem Login testen.

Die Konfiguration (config.json) wird NICHT kopiert; sie gehört jetzt in die
.env der App (BASE_URL, BREVO_API_KEY, MAIL_SENDER_EMAIL, MAIL_SENDER_NAME,
MAPTILER_KEY). Das Skript zeigt die passenden Zeilen an.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

DIRS = ["originals", "reports", "analyses", "profile_images"]
OPTIONAL_DIRS = ["adhoc_uploads"]
QUOTA_WARN = 1_800_000_000  # nativeAI: 2 GB Platte


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def db_is_empty(path: Path) -> bool:
    if not path.is_file():
        return True
    con = sqlite3.connect(str(path))
    try:
        for tbl in ("users", "sessions"):
            try:
                if con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]:
                    return False
            except sqlite3.OperationalError:
                pass
        return True
    finally:
        con.close()


def copy_tree(src: Path, dst: Path, dry: bool, stats: dict):
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        target = dst / rel
        if target.exists():
            if target.stat().st_size == f.stat().st_size:
                stats["skipped"] += 1
            else:
                stats["conflicts"].append(str(target))
            continue
        stats["copied"] += 1
        stats["bytes"] += f.stat().st_size
        if not dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)


def remap(value, old_prefixes, new_root: Path):
    """Alten absoluten Pfad auf neues Datenverzeichnis abbilden."""
    if not value:
        return value
    v = str(value)
    for pre in old_prefixes:
        if v.startswith(pre.rstrip("/") + "/"):
            return str(new_root / v[len(pre.rstrip("/")) + 1:])
    for d in DIRS + OPTIONAL_DIRS:
        marker = f"/{d}/"
        if marker in v:
            return str(new_root / d / v.split(marker, 1)[1])
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="altes Datenverzeichnis (enthält sessions.db)")
    ap.add_argument("--dst", required=True, help="neues Datenverzeichnis (APP_DATA, z. B. <App>/data)")
    ap.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts schreiben")
    ap.add_argument("--with-adhoc", action="store_true", help="auch adhoc_uploads/ kopieren (meist unnötig)")
    ap.add_argument("--replace-db", action="store_true",
                    help="nicht-leere Ziel-DB ersetzen (Sicherung wird angelegt)")
    a = ap.parse_args()

    src = Path(a.src).expanduser().resolve()
    dst = Path(a.dst).expanduser().resolve()
    dry = a.dry_run
    if not (src / "sessions.db").is_file():
        print(f"FEHLER: {src}/sessions.db nicht gefunden", file=sys.stderr)
        return 1
    if src == dst:
        print("FEHLER: Quelle und Ziel sind identisch", file=sys.stderr)
        return 1

    dirs = DIRS + (OPTIONAL_DIRS if a.with_adhoc else [])
    total = sum(dir_size(src / d) for d in dirs if (src / d).is_dir())
    total += (src / "sessions.db").stat().st_size
    print(f"Quelle: {src}\nZiel:   {dst}\nDatenmenge ca. {total/1e6:.0f} MB"
          + ("  [DRY-RUN]" if dry else ""))
    if total > QUOTA_WARN:
        print("WARNUNG: über 1,8 GB — nativeAI-Standardgrenze sind 2 GB Platte.")

    # --- 1. Datenbank
    dst_db = dst / "sessions.db"
    if not db_is_empty(dst_db) and not a.replace_db:
        print("ABBRUCH: Ziel-DB enthält bereits Nutzer/Sessions. "
              "Mit --replace-db ersetzen (Sicherung wird angelegt).",
              file=sys.stderr)
        return 2
    old_prefixes = {str(src), str(Path(a.src))}
    if not dry:
        dst.mkdir(parents=True, exist_ok=True)
        tmp = dst / "sessions.db.migrating"
        if tmp.exists():
            tmp.unlink()
        s = sqlite3.connect(f"file:{src/'sessions.db'}?mode=ro", uri=True)
        d = sqlite3.connect(str(tmp))
        try:
            s.backup(d)
        finally:
            s.close()
        # Pfade umschreiben
        for tbl, col in (("sessions", "file_path"), ("events", "file_path")):
            try:
                rows = d.execute(f"SELECT rowid, {col} FROM {tbl} "
                                 f"WHERE {col} IS NOT NULL AND {col} != ''").fetchall()
            except sqlite3.OperationalError:
                continue
            for rid, val in rows:
                nv = remap(val, old_prefixes, dst)
                if nv != val:
                    d.execute(f"UPDATE {tbl} SET {col}=? WHERE rowid=?", (nv, rid))
        d.commit()
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
        n_users = d.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        n_sess = d.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        n_laps = d.execute("SELECT COUNT(*) FROM laps").fetchone()[0]
        d.close()
        if ok != "ok":
            tmp.unlink()
            print(f"ABBRUCH: integrity_check meldet: {ok}", file=sys.stderr)
            return 3
        if dst_db.exists() and not db_is_empty(dst_db):
            bak = dst / f"sessions.db.bak-{time.strftime('%Y%m%d-%H%M%S')}"
            shutil.copy2(dst_db, bak)
            print(f"Sicherung der Ziel-DB: {bak.name}")
        for ext in ("-wal", "-shm"):
            p = Path(str(dst_db) + ext)
            if p.exists():
                p.unlink()
        os.replace(tmp, dst_db)
        print(f"DB übernommen: {n_users} Nutzer, {n_sess} Sessions, {n_laps} Runden (integrity_check ok)")
    else:
        con = sqlite3.connect(f"file:{src/'sessions.db'}?mode=ro", uri=True)
        for t in ("users", "sessions", "laps"):
            print(f"  {t}: {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]} Zeilen")
        con.close()

    # --- 2. server_secret
    sec_s, sec_d = src / "server_secret", dst / "server_secret"
    if sec_s.is_file():
        if sec_d.exists() and sec_d.read_bytes() != sec_s.read_bytes():
            if dry:
                print("server_secret: Ziel hat anderes Secret -> würde ersetzt (Original-Secret hält Logins gültig)")
            else:
                shutil.copy2(sec_d, dst / f"server_secret.bak-{time.strftime('%Y%m%d-%H%M%S')}")
                shutil.copyfile(sec_s, sec_d)
                os.chmod(sec_d, 0o600)
                print("server_secret übernommen (altes gesichert)")
        elif not sec_d.exists():
            if not dry:
                shutil.copyfile(sec_s, sec_d)
                os.chmod(sec_d, 0o600)
            print("server_secret übernommen")

    # --- 3. Dateibäume
    for name in dirs:
        sd = src / name
        if not sd.is_dir():
            continue
        stats = {"copied": 0, "skipped": 0, "bytes": 0, "conflicts": []}
        copy_tree(sd, dst / name, dry, stats)
        print(f"{name+'/':<16} {stats['copied']:>5} kopiert, {stats['skipped']:>5} vorhanden, "
              f"{stats['bytes']/1e6:8.1f} MB" + (f", {len(stats['conflicts'])} KONFLIKTE" if stats["conflicts"] else ""))
        for c in stats["conflicts"][:10]:
            print(f"   Konflikt (nicht überschrieben): {c}")

    # --- 4. Hinweis auf .env
    cfg_path = src / "config.json"
    print("\nKonfiguration -> .env der App (config.json wird nicht kopiert):")
    lines = []
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        if cfg.get("maptiler_key"):
            lines.append(f"MAPTILER_KEY={cfg['maptiler_key']}")
        smtp = cfg.get("smtp") or {}
        if smtp.get("sender_email"):
            lines.append(f"MAIL_SENDER_EMAIL={smtp['sender_email']}")
        if smtp.get("sender_name"):
            lines.append(f"MAIL_SENDER_NAME={smtp['sender_name']}")
    lines.append("BASE_URL=https://<appname>.nativeai.digitalsandkasten.de")
    lines.append("BREVO_API_KEY=<API-Key aus Brevo, nicht der SMTP-Key>")
    print("\n".join("  " + l for l in lines))
    if dry:
        print("\nDRY-RUN: nichts geschrieben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
