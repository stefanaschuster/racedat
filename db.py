"""SQLite persistence for users, sessions and laps.

Schema (v2):
  users:    minimal user account (email + password hash + admin flag)
  sessions: one row per uploaded source file, owned by a user (or NULL for
            sessions from before the auth system was added)
  laps:     one row per user-selected lap from a session

The original uploaded file lives on disk at `file_path` (under the data
directory's `originals/` subfolder). Only the lap data itself (numpy
arrays needed for comparison) is stored in the DB as a pickled blob.

When the DB file is opened, missing tables/columns are added (migration).
"""
import hashlib
import hmac
import json
import os
import pickle
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class EmailNotVerifiedError(Exception):
    """Raised by DB.verify_login() when credentials are correct but the
    account's e-mail hasn't been confirmed yet."""
    def __init__(self, user_id: int, email: str):
        self.user_id = user_id
        self.email = email
        super().__init__(f"E-Mail von User {email!r} ist noch nicht bestätigt.")


# ---------- Password hashing ------------------------------------------------
# Format: "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>"

PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with random salt."""
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    pwd_bytes = password.encode("utf-8")
    digest = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time check of a password against a stored hash."""
    if not stored_hash:
        return False
    try:
        algo, iter_str, salt_hex, hash_hex = stored_hash.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    pwd_bytes = password.encode("utf-8")
    actual = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt, iterations)
    return hmac.compare_digest(actual, expected)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    email                   TEXT NOT NULL UNIQUE,
    password_hash           TEXT NOT NULL,
    is_admin                INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT NOT NULL,
    -- v23.4 — Self-service registration + e-mail verification (Brevo).
    -- Default 1 so CLI-created accounts (useradmin.py) and pre-existing
    -- users from before this feature stay usable without any action;
    -- only the new self-registration path explicitly sets 0.
    email_verified          INTEGER NOT NULL DEFAULT 1,
    verify_token            TEXT,
    verify_token_expires    TEXT,
    verify_sent_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    created_at          TEXT NOT NULL,
    user_id             INTEGER,
    original_filename   TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    driver              TEXT NOT NULL DEFAULT '',
    bike                TEXT NOT NULL DEFAULT '',
    track               TEXT NOT NULL DEFAULT '',
    session_date        TEXT NOT NULL DEFAULT '',
    notes               TEXT NOT NULL DEFAULT '',
    format              TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_driver  ON sessions(driver);
CREATE INDEX IF NOT EXISTS idx_sessions_bike    ON sessions(bike);
CREATE INDEX IF NOT EXISTS idx_sessions_track   ON sessions(track);
CREATE INDEX IF NOT EXISTS idx_sessions_date    ON sessions(session_date);
-- idx_sessions_user_id is created in _migrate() because old DBs may not
-- have the user_id column yet when executescript runs.

CREATE TABLE IF NOT EXISTS laps (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    lap_number   INTEGER NOT NULL,
    duration_s   REAL NOT NULL,
    lap_blob     BLOB NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    UNIQUE(session_id, lap_number)
);

CREATE INDEX IF NOT EXISTS idx_laps_session ON laps(session_id);
CREATE INDEX IF NOT EXISTS idx_laps_duration ON laps(duration_s);

-- Audit log: logins, uploads, ad-hoc uploads.
-- For uploads, file_path points to the persisted file on disk.
-- Reports/analyses are not stored here; they live in their own folders
-- with sidecar meta.json files (see list_all_artefacts() in webserver.py).
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    kind         TEXT NOT NULL,    -- 'login', 'login_fail', 'upload_session', 'upload_adhoc'
    user_id      INTEGER,
    user_email   TEXT,             -- captured at time of event for resilience
    ip_address   TEXT,
    detail       TEXT,             -- free-form: filename, target, error, ...
    file_path    TEXT,             -- persisted file path (only for upload events)
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_created  ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_kind     ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_user     ON events(user_id);

-- v22.12 — Profiles: 1:1 with users. Driver name + optional driver photo.
-- The image_path is a filename only (no path traversal possible at read
-- time); the file lives under <data_dir>/profile_images/. Empty string =
-- no image (we never store NULL — keeps the rendering code branch-free).
CREATE TABLE IF NOT EXISTS profiles (
    user_id      INTEGER PRIMARY KEY,
    driver_name  TEXT NOT NULL DEFAULT '',
    image_path   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- v22.12 — Bikes: n:1 with users. Name + optional image. At most one bike
-- per user is "current" (enforced by UPDATE in set_current_bike — not a
-- partial unique index, since sqlite would otherwise need NULLs and we
-- prefer the simpler 0/1 column).
CREATE TABLE IF NOT EXISTS bikes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    name         TEXT NOT NULL,
    image_path   TEXT NOT NULL DEFAULT '',
    is_current   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bikes_user ON bikes(user_id);
"""


class DB:
    """Thread-safe SQLite connection wrapper.

    SQLite connections are not safe to share across threads by default, so we
    use a connection-per-thread pattern via threading.local. The DB file
    itself can be accessed concurrently in WAL mode.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # Initialise schema on first open
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            # WAL = better concurrent reads while writing
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            # Migrations: add user_id column to old sessions tables that
            # were created before auth existed.
            self._migrate(conn)
            conn.commit()

    def _migrate(self, conn):
        """Apply small schema migrations idempotently."""
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sessions)")
        cols = {row[1] for row in cur.fetchall()}
        if "user_id" not in cols:
            # Old DB from before the auth feature. Add the column.
            cur.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
        # Always ensure the index exists (idempotent)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id "
                    "ON sessions(user_id)")

        # v23.4 — Self-registration + e-mail verification columns. Existing
        # rows get email_verified=1 via the column DEFAULT, so pre-existing
        # users are unaffected.
        cur.execute("PRAGMA table_info(users)")
        user_cols = {row[1] for row in cur.fetchall()}
        if "email_verified" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN email_verified "
                        "INTEGER NOT NULL DEFAULT 1")
        if "verify_token" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN verify_token TEXT")
        if "verify_token_expires" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN verify_token_expires TEXT")
        if "verify_sent_at" not in user_cols:
            cur.execute("ALTER TABLE users ADD COLUMN verify_sent_at TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_verify_token "
                    "ON users(verify_token)")
        cur.close()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _cur(self):
        """Yield a cursor on a thread-local connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    # --- Session CRUD -------------------------------------------------------

    def canonical_track_name(self, track: str) -> str:
        """v22.2 — Return the canonical spelling of `track` if a session with
        a case-insensitively matching track name already exists, else return
        `track` unchanged. Empty input returns "" (no normalisation against
        the empty string). Used at upload/edit time so users picking
        "hockenheim" don't fork the existing "Hockenheim" bucket."""
        track = (track or "").strip()
        if not track:
            return ""
        with self._cur() as cur:
            cur.execute(
                "SELECT track FROM sessions "
                "WHERE LOWER(track) = LOWER(?) AND track != '' "
                "ORDER BY created_at ASC LIMIT 1",
                (track,),
            )
            row = cur.fetchone()
            if row is not None:
                return row[0]
        return track

    def create_session(self, *, original_filename: str, file_path: str,
                       user_id: Optional[int] = None,
                       driver: str = "", bike: str = "", track: str = "",
                       session_date: str = "", notes: str = "",
                       format: str = "") -> str:
        sid = str(uuid.uuid4())
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO sessions (id, created_at, user_id, "
                "original_filename, file_path, driver, bike, track, "
                "session_date, notes, format) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 user_id,
                 original_filename, file_path,
                 driver, bike, track, session_date, notes, format),
            )
        return sid

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._cur() as cur:
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._cur() as cur:
            cur.execute(
                "SELECT s.*, "
                "  u.email AS owner_email, "
                "  (SELECT COUNT(*) FROM laps WHERE session_id = s.id) AS lap_count, "
                "  (SELECT MIN(duration_s) FROM laps WHERE session_id = s.id) AS best_lap_s "
                "FROM sessions s "
                "LEFT JOIN users u ON s.user_id = u.id "
                "ORDER BY s.session_date DESC, s.created_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]

    def list_all_laps_flat(self) -> List[Dict[str, Any]]:
        """Return a flat list of all laps with their session metadata joined.
        One row per lap. Sorted by session_date / created_at descending,
        then by lap_number ascending so within a session the laps come in
        the order they were driven.

        Used by the lap library view (replaces the legacy 'sessions list',
        because each session is conceptually one lap now)."""
        with self._cur() as cur:
            cur.execute(
                "SELECT laps.id AS lap_id, laps.lap_number, laps.duration_s, "
                "  s.id AS session_id, s.driver, s.bike, s.track, "
                "  s.session_date, s.notes, s.original_filename, "
                "  s.file_path, s.format, s.user_id, s.created_at, "
                "  u.email AS owner_email "
                "FROM laps "
                "JOIN sessions s ON laps.session_id = s.id "
                "LEFT JOIN users u ON s.user_id = u.id "
                "ORDER BY s.session_date DESC, s.created_at DESC, laps.lap_number ASC"
            )
            return [dict(r) for r in cur.fetchall()]

    def delete_session(self, session_id: str) -> Optional[str]:
        """Delete session and its laps. Returns the file_path to clean up,
        or None if the session didn't exist."""
        with self._cur() as cur:
            cur.execute("SELECT file_path FROM sessions WHERE id = ?",
                        (session_id,))
            row = cur.fetchone()
            if not row:
                return None
            file_path = row["file_path"]
            # FK cascade deletes laps
            cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return file_path

    def update_session_meta(self, session_id: str, *,
                            driver: str, bike: str, track: str,
                            session_date: str, notes: str) -> bool:
        """Update editable metadata fields on a session.
        Returns True if a row was updated, False if session_id not found.
        Caller is responsible for authorisation (admin-only)."""
        with self._cur() as cur:
            cur.execute(
                "UPDATE sessions SET driver=?, bike=?, track=?, "
                "  session_date=?, notes=? "
                "WHERE id = ?",
                (driver, bike, track, session_date, notes, session_id),
            )
            return cur.rowcount > 0

    # --- Lap CRUD -----------------------------------------------------------

    def add_lap(self, session_id: str, lap_number: int,
                duration_s: float, lap_data: dict) -> int:
        """Persist one extracted lap to the DB. `lap_data` is the dict from
        extract_lap_data() — we pickle it as-is."""
        blob = pickle.dumps(lap_data, protocol=pickle.HIGHEST_PROTOCOL)
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO laps (session_id, lap_number, duration_s, lap_blob) "
                "VALUES (?, ?, ?, ?)",
                (session_id, lap_number, duration_s, blob),
            )
            return cur.lastrowid

    def update_lap_blob(self, lap_id: int, lap_data: dict,
                        duration_s: Optional[float] = None) -> bool:
        """Replace the pickled lap data for an existing lap. Used by the
        reparse script — metadata (session_id, lap_number, etc.) stays as is.
        If duration_s is None, the duration column is left untouched.
        Returns True if a row was updated."""
        blob = pickle.dumps(lap_data, protocol=pickle.HIGHEST_PROTOCOL)
        with self._cur() as cur:
            if duration_s is None:
                cur.execute(
                    "UPDATE laps SET lap_blob = ? WHERE id = ?",
                    (blob, int(lap_id)),
                )
            else:
                cur.execute(
                    "UPDATE laps SET lap_blob = ?, duration_s = ? WHERE id = ?",
                    (blob, float(duration_s), int(lap_id)),
                )
            return cur.rowcount > 0

    def get_lap(self, lap_id: int) -> Optional[Dict[str, Any]]:
        """Return lap with metadata joined from session.

        v21.37 — Includes sessions.user_id (renamed to 'session_user_id'
        to avoid clashing with any lap-level user_id should one ever be
        added). Callers use this for owner-or-admin permission checks
        without a second query.
        """
        with self._cur() as cur:
            cur.execute(
                "SELECT laps.*, sessions.driver, sessions.bike, sessions.track, "
                "  sessions.session_date, sessions.notes, sessions.original_filename, "
                "  sessions.user_id AS session_user_id "
                "FROM laps JOIN sessions ON laps.session_id = sessions.id "
                "WHERE laps.id = ?",
                (lap_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["lap_data"] = pickle.loads(d.pop("lap_blob"))
            return d

    def list_laps_for_session(self, session_id: str) -> List[Dict[str, Any]]:
        with self._cur() as cur:
            cur.execute(
                "SELECT id, session_id, lap_number, duration_s "
                "FROM laps WHERE session_id = ? ORDER BY lap_number",
                (session_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def delete_lap(self, lap_id: int) -> Optional[Dict[str, Any]]:
        """Delete a single lap. If this was the last lap of its session,
        also remove the session row (returns the session's file_path so the
        caller can clean the originals directory).

        Returns dict with {session_id, file_path_to_clean, session_removed}
        or None if the lap didn't exist.
        """
        with self._cur() as cur:
            cur.execute(
                "SELECT laps.session_id, sessions.file_path "
                "FROM laps JOIN sessions ON laps.session_id = sessions.id "
                "WHERE laps.id = ?",
                (lap_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            session_id = row["session_id"]
            file_path = row["file_path"]
            cur.execute("DELETE FROM laps WHERE id = ?", (lap_id,))
            # Check if session is now empty
            cur.execute("SELECT COUNT(*) AS n FROM laps WHERE session_id = ?",
                        (session_id,))
            remaining = cur.fetchone()["n"]
            session_removed = False
            if remaining == 0:
                cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                session_removed = True
            return {
                "session_id": session_id,
                "file_path_to_clean": file_path if session_removed else None,
                "session_removed": session_removed,
            }

    def get_channel_summary(self, lap_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Return {lap_id: {extras_count, roles_count, total_roles,
                            assigned_role_ids}} for the given laps.

        v21.36 — Drives the per-lap channel badges in the sessions list.
        Reads the pickled blob ONLY to extract two counts, never caches
        the result. Why no caching/persistence? Three places mutate the
        lap blob (upload step 2, admin edit modal, reparse script), plus
        Coach-side persistence will add a fourth — every cache would
        need invalidation everywhere. The depickle cost is ~0.06 ms per
        lap on a typical XRK blob, so a 200-row page adds ~12 ms — well
        below the user-perceptible threshold.

        Fields:
            extras_count — number of extra channels in the blob
            roles_count  — number of role→channel assignments
            total_roles  — total registry roles (stable across laps; here
                           so callers don't need to import the registry
                           themselves and the "full" decision is a pure
                           function of these three numbers)
            assigned_role_ids — v22.3: sorted list of role ids that have
                           a channel assigned for this lap. Drives the
                           per-role status-dot icons in the lap pickers
                           and the sessions list (grey if not present,
                           green if present). Sorted for deterministic
                           output (tests / cache-friendliness).
        """
        if not lap_ids:
            return {}
        # Local import to avoid cycles (channel_roles imports nothing from db)
        from parsers.channel_roles import ROLES as _ROLES
        total_roles = len(_ROLES)
        out: Dict[int, Dict[str, Any]] = {}
        # SQLite has a 999-param IN-list limit; chunk if needed.
        CHUNK = 500
        with self._cur() as cur:
            for i in range(0, len(lap_ids), CHUNK):
                chunk = lap_ids[i:i+CHUNK]
                placeholders = ",".join("?" * len(chunk))
                cur.execute(
                    f"SELECT id, lap_blob FROM laps WHERE id IN ({placeholders})",
                    chunk,
                )
                for row in cur.fetchall():
                    lid = int(row["id"])
                    try:
                        ld = pickle.loads(row["lap_blob"])
                    except Exception:
                        out[lid] = {"extras_count": 0, "roles_count": 0,
                                    "total_roles": total_roles,
                                    "assigned_role_ids": []}
                        continue
                    extras_dict = ld.get("extra_channels") or {}
                    roles_dict  = ld.get("channel_roles")  or {}
                    out[lid] = {
                        "extras_count": int(len(extras_dict)),
                        "roles_count":  int(len(roles_dict)),
                        "total_roles":  total_roles,
                        "assigned_role_ids": sorted(roles_dict.keys()),
                    }
        return out

    def query_laps(self, *, driver: str = "", bike: str = "", track: str = "",
                   date_from: str = "", date_to: str = "",
                   min_seconds: Optional[float] = None,
                   max_seconds: Optional[float] = None,
                   search: str = "",
                   limit: int = 200) -> List[Dict[str, Any]]:
        """Return laps with their session metadata, filtered & sorted by
        duration ascending (fastest first)."""
        sql = (
            "SELECT laps.id AS lap_id, laps.lap_number, laps.duration_s, "
            "  sessions.id AS session_id, sessions.driver, sessions.bike, "
            "  sessions.track, sessions.session_date, sessions.notes, "
            "  sessions.original_filename, sessions.user_id, "
            "  u.email AS owner_email "
            "FROM laps JOIN sessions ON laps.session_id = sessions.id "
            "LEFT JOIN users u ON sessions.user_id = u.id "
            "WHERE 1=1"
        )
        params: List[Any] = []
        if driver:
            sql += " AND sessions.driver = ?"; params.append(driver)
        if bike:
            sql += " AND sessions.bike = ?"; params.append(bike)
        if track:
            # v22.2 — case-insensitive track match so filter dropdowns
            # built from older inconsistently-cased data still group laps
            # under one entry.
            sql += " AND LOWER(sessions.track) = LOWER(?)"; params.append(track)
        if date_from:
            sql += " AND sessions.session_date >= ?"; params.append(date_from)
        if date_to:
            sql += " AND sessions.session_date <= ?"; params.append(date_to)
        if min_seconds is not None:
            sql += " AND laps.duration_s >= ?"; params.append(min_seconds)
        if max_seconds is not None:
            sql += " AND laps.duration_s <= ?"; params.append(max_seconds)
        if search:
            sql += (" AND (sessions.driver LIKE ? OR sessions.bike LIKE ? "
                    "OR sessions.track LIKE ? OR sessions.notes LIKE ? "
                    "OR sessions.original_filename LIKE ?)")
            wild = f"%{search}%"
            params.extend([wild] * 5)
        sql += " ORDER BY laps.duration_s ASC LIMIT ?"
        params.append(int(limit))
        with self._cur() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def best_lap_per_track_for_user(self, user_id: int
                                    ) -> List[Dict[str, Any]]:
        """v23.1 — Return one row per track for the given user: the
        fastest lap on each track they've uploaded, with the canonical
        track name (whatever spelling came first), duration, lap_id, and
        session_date. Sorted by duration ascending (best time first).

        Sessions with an empty track field are excluded — they'd group
        into a useless "(kein Track)"-bucket. Track-matching is case-
        insensitive (v22.2-Konvention via LOWER); the displayed name
        per bucket is the earliest-seen spelling for that bucket,
        matching the canonical_track_name() rule from v22.2 — so old
        data with mixed casing renders consistently.

        Why not in `query_laps` with a flag: that method returns one
        row per lap; this is one row per track. Different shape →
        different method.
        """
        with self._cur() as cur:
            # Schritt 1: pro Track-Bucket die Lap-ID der schnellsten
            # Runde holen, plus das canonical-Spelling (= das Spelling
            # der frühesten Session im Bucket).
            #
            # Wir machen das in zwei Aggregations-Pässen, weil SQLite
            # kein FIRST_VALUE() ohne Window-Functions hat und das
            # Subquery-min/lap_id-Pattern sonst ausartet.
            cur.execute(
                "SELECT "
                "  LOWER(sessions.track) AS track_key, "
                "  MIN(laps.duration_s) AS best_s "
                "FROM laps "
                "JOIN sessions ON laps.session_id = sessions.id "
                "WHERE sessions.user_id = ? AND sessions.track != '' "
                "GROUP BY LOWER(sessions.track)",
                (int(user_id),),
            )
            bucket_min = {row["track_key"]: row["best_s"]
                          for row in cur.fetchall()}
            if not bucket_min:
                return []
            # Schritt 2: für jeden Bucket die Lap-Row holen (Lap-ID +
            # Session-Date), und separat die canonical Spelling
            # (= früheste Session im Bucket).
            results = []
            for track_key, best_s in bucket_min.items():
                # Canonical Spelling: erste Session in diesem Bucket
                cur.execute(
                    "SELECT track FROM sessions "
                    "WHERE user_id = ? AND LOWER(track) = ? "
                    "ORDER BY created_at ASC LIMIT 1",
                    (int(user_id), track_key),
                )
                canon_row = cur.fetchone()
                canonical_track = canon_row["track"] if canon_row else track_key
                # Lap-Id + Datum der schnellsten Runde im Bucket. Wenn
                # zwei Runden ex-aequo MIN sind, gewinnt die ältere
                # (ORDER BY laps.id ASC).
                cur.execute(
                    "SELECT laps.id AS lap_id, laps.duration_s, "
                    "  sessions.session_date "
                    "FROM laps "
                    "JOIN sessions ON laps.session_id = sessions.id "
                    "WHERE sessions.user_id = ? "
                    "AND LOWER(sessions.track) = ? "
                    "AND laps.duration_s = ? "
                    "ORDER BY laps.id ASC LIMIT 1",
                    (int(user_id), track_key, best_s),
                )
                detail = cur.fetchone()
                if detail is None:
                    continue
                results.append({
                    "track": canonical_track,
                    "duration_s": float(detail["duration_s"]),
                    "lap_id": int(detail["lap_id"]),
                    "session_date": detail["session_date"] or "",
                })
            # Schnellste zuerst
            results.sort(key=lambda r: r["duration_s"])
            return results

    def global_top_n_per_track(self, n: int = 3) -> List[Dict[str, Any]]:
        """v23.2 — Liefert die globale Top-N-Rangliste pro Strecke,
        über alle Fahrer hinweg. Returns a list of
        `{track, entries: [{rank, lap_id, duration_s, user_id,
        owner_email, driver_name}, ...]}` — pro Track maximal n
        Einträge, sortiert nach `duration_s` aufsteigend.

        Strecken sind LOWER-grouped (Case-insensitive, v22.2-Konvention);
        Anzeige-Spelling ist die früheste Schreibweise im Bucket.
        Sessions mit leerem Track werden ausgeschlossen.

        Sortierung der äusseren Liste: nach Track-Name (alphabetisch,
        case-insensitive). Stefan-Stil: deterministisch, nicht nach
        "schnellste Bestzeit zuerst" — die Reihenfolge der Strecken
        soll stabil sein zwischen Page-Loads, sodass ein User der die
        Seite öfter besucht seine bevorzugte Strecke immer am selben
        Platz findet.

        Eine Lap-Row mit `lap_id=X` kann höchstens 1× pro Track-Bucket
        auftauchen. v23.10: Zusätzlich erscheint jeder FAHRER höchstens
        1× pro Track (mit seiner Bestzeit) — Identität via user_id,
        sonst driver-Name (case-insensitive). Wenn zwei Laps dieselbe
        Zeit haben, gewinnt die kleinere lap_id (deterministisch).
        """
        if n < 1:
            return []
        with self._cur() as cur:
            # Pass 1: alle Track-Buckets sammeln (LOWER + canonical
            # Spelling = first-seen).
            cur.execute(
                "SELECT DISTINCT LOWER(sessions.track) AS track_key "
                "FROM laps "
                "JOIN sessions ON laps.session_id = sessions.id "
                "WHERE sessions.track != ''"
            )
            track_keys = [row["track_key"] for row in cur.fetchall()]
            if not track_keys:
                return []
            results = []
            for tk in track_keys:
                # Canonical Spelling: erste Session überhaupt in diesem
                # Bucket (über alle User hinweg).
                cur.execute(
                    "SELECT track FROM sessions "
                    "WHERE LOWER(track) = ? AND track != '' "
                    "ORDER BY created_at ASC LIMIT 1",
                    (tk,),
                )
                canon_row = cur.fetchone()
                canonical_track = canon_row["track"] if canon_row else tk
                # v23.10 — Bugfix: EIN Eintrag pro Fahrer und Strecke
                # (seine Bestzeit), nicht die n schnellsten Runden
                # überhaupt. Vorher konnte ein Fahrer mit drei schnellen
                # Runden alle drei Podiumsplätze belegen.
                #
                # Fahrer-Identität fürs Dedupe:
                #   1. user_id, wenn die Session einem Account gehört
                #   2. sonst driver-Name (case-insensitive, getrimmt)
                #   3. sonst (verwaiste Session ohne Namen) die lap_id
                #      selbst — solche Runden bleiben einzeln sichtbar,
                #      weil wir sie niemandem zuordnen können.
                #
                # Query läuft unverändert sortiert (schnellste zuerst);
                # dedupliziert wird beim Durchlaufen, Abbruch sobald n
                # Fahrer gesammelt sind.
                cur.execute(
                    "SELECT laps.id AS lap_id, laps.duration_s, "
                    "  sessions.user_id, sessions.driver, sessions.bike, "
                    "  u.email AS owner_email "
                    "FROM laps "
                    "JOIN sessions ON laps.session_id = sessions.id "
                    "LEFT JOIN users u ON sessions.user_id = u.id "
                    "WHERE LOWER(sessions.track) = ? "
                    "ORDER BY laps.duration_s ASC, laps.id ASC",
                    (tk,),
                )
                entries = []
                seen_drivers = set()
                for row in cur:
                    if row["user_id"] is not None:
                        driver_key = ("u", int(row["user_id"]))
                    elif (row["driver"] or "").strip():
                        driver_key = ("d", row["driver"].strip().lower())
                    else:
                        driver_key = ("l", int(row["lap_id"]))
                    if driver_key in seen_drivers:
                        continue
                    seen_drivers.add(driver_key)
                    entries.append({
                        "rank": len(entries) + 1,
                        "lap_id": int(row["lap_id"]),
                        "duration_s": float(row["duration_s"]),
                        "user_id": (int(row["user_id"])
                                    if row["user_id"] is not None else None),
                        "owner_email": row["owner_email"] or "",
                        "driver_name": row["driver"] or "",
                        # v23.5 — Motorrad pro Top-Lap, für die Anzeige
                        # unter dem Fahrernamen auf der Podium-Karte.
                        "bike": row["bike"] or "",
                    })
                    if len(entries) >= n:
                        break
                if entries:
                    results.append({
                        "track": canonical_track,
                        "entries": entries,
                    })
            results.sort(key=lambda r: r["track"].lower())
            return results

    # --- User CRUD ----------------------------------------------------------

    def create_user(self, *, email: str, password: str,
                    is_admin: bool = False) -> int:
        """Create a user. Raises ValueError if email already exists.
        Returns the new user_id."""
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("E-Mail-Adresse ungültig.")
        if not password or len(password) < 6:
            raise ValueError("Passwort muss mindestens 6 Zeichen lang sein.")
        pwd_hash = hash_password(password)
        with self._cur() as cur:
            try:
                cur.execute(
                    "INSERT INTO users (email, password_hash, is_admin, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (email, pwd_hash, 1 if is_admin else 0,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"User mit E-Mail '{email}' existiert bereits.")
            return cur.lastrowid

    # v23.4 — Self-service registration -------------------------------------
    # Separate from create_user() (used by useradmin.py / admin flows, which
    # stay instantly verified via the column DEFAULT) so the CLI path is
    # untouched. Token generation happens inside the same DB call as the
    # insert so caller never has to juggle a half-created user.

    VERIFY_TOKEN_TTL_SECONDS = 24 * 3600

    def create_pending_user(self, *, email: str, password: str) -> tuple[int, str]:
        """Create an unverified user and return (user_id, verify_token).
        Raises ValueError on invalid input or if the e-mail is taken."""
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("E-Mail-Adresse ungültig.")
        if not password or len(password) < 6:
            raise ValueError("Passwort muss mindestens 6 Zeichen lang sein.")
        pwd_hash = hash_password(password)
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now.timestamp() + self.VERIFY_TOKEN_TTL_SECONDS
        with self._cur() as cur:
            try:
                cur.execute(
                    "INSERT INTO users (email, password_hash, is_admin, "
                    "  created_at, email_verified, verify_token, "
                    "  verify_token_expires, verify_sent_at) "
                    "VALUES (?, ?, 0, ?, 0, ?, ?, ?)",
                    (email, pwd_hash, now.isoformat(timespec="seconds"),
                     token, str(expires), now.isoformat(timespec="seconds")),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"User mit E-Mail '{email}' existiert bereits.")
            return cur.lastrowid, token

    def get_user_by_verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Return the user row for a verify token, regardless of expiry —
        caller checks verify_token_expires so it can tell an expired token
        apart from a bogus/unknown one (different error messages)."""
        token = (token or "").strip()
        if not token:
            return None
        with self._cur() as cur:
            cur.execute("SELECT * FROM users WHERE verify_token = ?", (token,))
            row = cur.fetchone()
            return dict(row) if row else None

    def confirm_email(self, user_id: int) -> bool:
        """Mark a user's e-mail verified and clear the token."""
        with self._cur() as cur:
            cur.execute(
                "UPDATE users SET email_verified = 1, verify_token = NULL, "
                "  verify_token_expires = NULL WHERE id = ?",
                (int(user_id),),
            )
            return cur.rowcount > 0

    def resend_verify_token(self, user_id: int) -> Optional[str]:
        """Generate a fresh verify token for an unverified user, replacing
        any existing one. Returns the new token, or None if the user
        doesn't exist or is already verified (nothing to resend)."""
        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(32)
        expires = now.timestamp() + self.VERIFY_TOKEN_TTL_SECONDS
        with self._cur() as cur:
            cur.execute(
                "UPDATE users SET verify_token = ?, verify_token_expires = ?, "
                "  verify_sent_at = ? "
                "WHERE id = ? AND email_verified = 0",
                (token, str(expires), now.isoformat(timespec="seconds"),
                 int(user_id)),
            )
            return token if cur.rowcount > 0 else None

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._cur() as cur:
            cur.execute("SELECT id, email, is_admin, created_at FROM users "
                        "WHERE id = ?", (int(user_id),))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Return full user record INCLUDING password_hash for login check."""
        email = (email or "").strip().lower()
        with self._cur() as cur:
            cur.execute("SELECT * FROM users WHERE email = ?", (email,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_users(self) -> List[Dict[str, Any]]:
        with self._cur() as cur:
            cur.execute("SELECT id, email, is_admin, created_at FROM users "
                        "ORDER BY email")
            return [dict(r) for r in cur.fetchall()]

    def update_user_password(self, user_id: int, password: str) -> bool:
        if not password or len(password) < 6:
            raise ValueError("Passwort muss mindestens 6 Zeichen lang sein.")
        pwd_hash = hash_password(password)
        with self._cur() as cur:
            cur.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                        (pwd_hash, int(user_id)))
            return cur.rowcount > 0

    def set_admin(self, user_id: int, is_admin: bool) -> bool:
        with self._cur() as cur:
            cur.execute("UPDATE users SET is_admin = ? WHERE id = ?",
                        (1 if is_admin else 0, int(user_id)))
            return cur.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        with self._cur() as cur:
            cur.execute("DELETE FROM users WHERE id = ?", (int(user_id),))
            return cur.rowcount > 0

    def verify_login(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Return user dict (without password_hash) if credentials match, else
        None. Raises EmailNotVerifiedError (credentials correct, but the
        account still needs e-mail confirmation) so the caller can show a
        distinct message with a resend link instead of "wrong password"."""
        rec = self.get_user_by_email(email)
        if not rec:
            return None
        if not verify_password(password, rec["password_hash"]):
            return None
        if not rec["email_verified"]:
            raise EmailNotVerifiedError(rec["id"], rec["email"])
        return {
            "id": rec["id"],
            "email": rec["email"],
            "is_admin": bool(rec["is_admin"]),
        }

    # --- Profile + Bikes CRUD (v22.12) -------------------------------------
    # A profile is 1:1 with a user (lazily created on first save). Bikes are
    # n:1; at most one bike per user is flagged is_current=1. Images live on
    # disk under <data_dir>/profile_images/ and we only store the filename
    # (no path) — keeps the DB portable and the read path branch-free.

    def get_profile(self, user_id: int) -> Dict[str, Any]:
        """Return the profile row for a user, or a synthetic empty profile if
        none has been saved yet. Callers can treat both cases identically —
        the dict has the same keys either way."""
        with self._cur() as cur:
            cur.execute(
                "SELECT user_id, driver_name, image_path, created_at, updated_at "
                "FROM profiles WHERE user_id = ?",
                (int(user_id),),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
        return {
            "user_id": int(user_id),
            "driver_name": "",
            "image_path": "",
            "created_at": "",
            "updated_at": "",
        }

    def upsert_profile(self, user_id: int, *, driver_name: str = "",
                       image_path: Optional[str] = None) -> Dict[str, Any]:
        """Create or update the profile row for a user. `image_path=None`
        leaves the existing image untouched (used when saving the form
        without uploading a new photo). Pass empty string to clear it.
        Returns the updated profile dict."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._cur() as cur:
            cur.execute("SELECT user_id, image_path FROM profiles WHERE user_id = ?",
                        (int(user_id),))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO profiles "
                    "  (user_id, driver_name, image_path, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (int(user_id), driver_name or "",
                     image_path or "", now, now),
                )
            else:
                final_img = row["image_path"] if image_path is None else image_path
                cur.execute(
                    "UPDATE profiles SET driver_name = ?, image_path = ?, "
                    "  updated_at = ? WHERE user_id = ?",
                    (driver_name or "", final_img, now, int(user_id)),
                )
        return self.get_profile(user_id)

    def list_all_profiles(self) -> List[Dict[str, Any]]:
        """Admin-Übersicht: alle Profile mit User-Email + Bike-Aggregaten,
        sortiert nach Zuletzt-Bearbeitet (neuste zuerst).

        Liefert pro Profil: user_id, email, is_admin, driver_name,
        image_path, bike_count, current_bike_name, created_at, updated_at.

        v23.4 — speist /admin?tab=profiles. Nur Rows aus `profiles`-Tabelle;
        Users ohne Profil tauchen NICHT auf. Falls Du das später auch
        brauchst (z.B. "wer hat noch keins?"), eine zweite Methode dafür.
        """
        with self._cur() as cur:
            cur.execute(
                "SELECT p.user_id, u.email, u.is_admin, "
                "       p.driver_name, p.image_path, "
                "       p.created_at, p.updated_at, "
                "       (SELECT COUNT(*) FROM bikes b "
                "          WHERE b.user_id = p.user_id) AS bike_count, "
                "       (SELECT b2.name FROM bikes b2 "
                "          WHERE b2.user_id = p.user_id AND b2.is_current = 1 "
                "          LIMIT 1) AS current_bike_name "
                "FROM profiles p "
                "JOIN users u ON u.id = p.user_id "
                "ORDER BY p.updated_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]

    def count_users(self) -> int:
        """Total user-row count — used by /admin?tab=profiles for the
        'X von Y Usern' info line. Cheap query, no caching needed."""
        with self._cur() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            row = cur.fetchone()
            return int(row["n"]) if row else 0

    def list_bikes(self, user_id: int) -> List[Dict[str, Any]]:
        """Return all bikes for a user, current-first then alphabetically by
        name. Each row: {id, user_id, name, image_path, is_current,
        created_at}."""
        with self._cur() as cur:
            cur.execute(
                "SELECT id, user_id, name, image_path, is_current, created_at "
                "FROM bikes WHERE user_id = ? "
                "ORDER BY is_current DESC, name COLLATE NOCASE",
                (int(user_id),),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_bike(self, bike_id: int) -> Optional[Dict[str, Any]]:
        with self._cur() as cur:
            cur.execute(
                "SELECT id, user_id, name, image_path, is_current, created_at "
                "FROM bikes WHERE id = ?",
                (int(bike_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_current_bike(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Return the bike currently flagged is_current=1 for a user.
        If multiple are flagged (shouldn't happen — set_current_bike is the
        only writer and clears the others), the most recently created one
        wins. Returns None if the user has no bikes or none flagged."""
        with self._cur() as cur:
            cur.execute(
                "SELECT id, user_id, name, image_path, is_current, created_at "
                "FROM bikes WHERE user_id = ? AND is_current = 1 "
                "ORDER BY created_at DESC LIMIT 1",
                (int(user_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def add_bike(self, user_id: int, *, name: str,
                 image_path: str = "",
                 is_current: bool = False) -> int:
        """Insert a bike. If is_current=True, clears the flag on the user's
        other bikes first. If this is the user's first bike, it is forced
        to current regardless of the flag (so the upload pre-fill has
        something to bind to even if the user forgot to tick)."""
        name = (name or "").strip()
        if not name:
            raise ValueError("Bike-Name darf nicht leer sein.")
        if len(name) > 200:
            raise ValueError("Bike-Name zu lang (max 200 Zeichen).")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._cur() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM bikes WHERE user_id = ?",
                        (int(user_id),))
            n_existing = cur.fetchone()["n"]
            force_current = (n_existing == 0)
            final_current = 1 if (is_current or force_current) else 0
            if final_current:
                cur.execute("UPDATE bikes SET is_current = 0 WHERE user_id = ?",
                            (int(user_id),))
            cur.execute(
                "INSERT INTO bikes "
                "  (user_id, name, image_path, is_current, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (int(user_id), name, image_path or "", final_current, now),
            )
            return cur.lastrowid

    def update_bike(self, bike_id: int, user_id: int, *,
                    name: Optional[str] = None,
                    image_path: Optional[str] = None) -> bool:
        """Update a bike's name and/or image. user_id is passed for an
        authorisation check (the row must belong to this user). image_path=
        None means "don't touch", "" means "clear". Returns True if a row
        was updated."""
        with self._cur() as cur:
            cur.execute("SELECT user_id, image_path FROM bikes WHERE id = ?",
                        (int(bike_id),))
            row = cur.fetchone()
            if row is None or row["user_id"] != int(user_id):
                return False
            new_name = name if name is not None else None
            new_img = row["image_path"] if image_path is None else image_path
            if new_name is not None:
                new_name = new_name.strip()
                if not new_name:
                    raise ValueError("Bike-Name darf nicht leer sein.")
                if len(new_name) > 200:
                    raise ValueError("Bike-Name zu lang (max 200 Zeichen).")
                cur.execute(
                    "UPDATE bikes SET name = ?, image_path = ? WHERE id = ?",
                    (new_name, new_img, int(bike_id)),
                )
            else:
                cur.execute(
                    "UPDATE bikes SET image_path = ? WHERE id = ?",
                    (new_img, int(bike_id)),
                )
            return cur.rowcount > 0

    def delete_bike(self, bike_id: int, user_id: int) -> Optional[str]:
        """Delete a bike. user_id is checked for authorisation. Returns the
        deleted bike's image_path so the caller can clean up the file on
        disk, or None if not found / not owned. If the deleted bike was
        the current one and other bikes remain, promotes the most recently
        created remaining bike to current."""
        with self._cur() as cur:
            cur.execute("SELECT user_id, image_path, is_current "
                        "FROM bikes WHERE id = ?", (int(bike_id),))
            row = cur.fetchone()
            if row is None or row["user_id"] != int(user_id):
                return None
            img_path = row["image_path"] or ""
            was_current = bool(row["is_current"])
            cur.execute("DELETE FROM bikes WHERE id = ?", (int(bike_id),))
            if was_current:
                cur.execute(
                    "SELECT id FROM bikes WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (int(user_id),),
                )
                next_row = cur.fetchone()
                if next_row is not None:
                    cur.execute("UPDATE bikes SET is_current = 1 WHERE id = ?",
                                (next_row["id"],))
            return img_path

    def set_current_bike(self, bike_id: int, user_id: int) -> bool:
        """Mark a bike as current and clear the flag on all of the user's
        other bikes. user_id is checked for authorisation. Returns False
        if the bike doesn't exist or doesn't belong to the user."""
        with self._cur() as cur:
            cur.execute("SELECT user_id FROM bikes WHERE id = ?", (int(bike_id),))
            row = cur.fetchone()
            if row is None or row["user_id"] != int(user_id):
                return False
            cur.execute("UPDATE bikes SET is_current = 0 WHERE user_id = ?",
                        (int(user_id),))
            cur.execute("UPDATE bikes SET is_current = 1 WHERE id = ?",
                        (int(bike_id),))
            return True

    # --- Distinct values for filter dropdowns ------------------------------

    def distinct_values(self) -> Dict[str, List[str]]:
        """Return distinct, non-empty values for the filter dropdowns."""
        out: Dict[str, List[str]] = {}
        with self._cur() as cur:
            for field in ("driver", "bike", "track"):
                cur.execute(
                    f"SELECT DISTINCT {field} FROM sessions "
                    f"WHERE {field} != '' ORDER BY {field}"
                )
                out[field] = [r[0] for r in cur.fetchall()]
        return out

    # --- Audit events ------------------------------------------------------

    def add_event(self, kind: str, *,
                  user_id: Optional[int] = None,
                  user_email: str = "",
                  ip_address: str = "",
                  detail: str = "",
                  file_path: str = "") -> int:
        """Record an audit event (login, upload, etc.). Returns the event id.
        Failures are swallowed-and-logged in the caller; the DB is not the
        critical path for auth or upload, just an observability log."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO events "
                "  (created_at, kind, user_id, user_email, ip_address, detail, file_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now, kind, user_id, user_email or "",
                 ip_address or "", detail or "", file_path or ""),
            )
            return cur.lastrowid

    def list_events(self, kinds: Optional[List[str]] = None,
                    limit: int = 500) -> List[Dict[str, Any]]:
        """Return audit events, newest first. Optionally filter by kind list."""
        sql = ("SELECT id, created_at, kind, user_id, user_email, "
               "  ip_address, detail, file_path "
               "FROM events")
        params: List[Any] = []
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            sql += f" WHERE kind IN ({placeholders})"
            params.extend(kinds)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        with self._cur() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def get_event(self, event_id: int) -> Optional[dict]:
        """Return one event row as dict, or None if not found."""
        with self._cur() as cur:
            cur.execute(
                "SELECT id, kind, created_at, user_id, user_email, "
                "ip_address, detail, file_path FROM events WHERE id = ?",
                (int(event_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_event(self, event_id: int) -> Optional[str]:
        """Delete an event row. For upload events, returns the file_path so
        the caller can also delete the file on disk. Returns None if not
        found."""
        with self._cur() as cur:
            cur.execute("SELECT file_path FROM events WHERE id = ?",
                        (int(event_id),))
            row = cur.fetchone()
            if not row:
                return None
            fp = row["file_path"]
            cur.execute("DELETE FROM events WHERE id = ?", (int(event_id),))
            return fp or ""
