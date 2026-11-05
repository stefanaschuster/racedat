"""Parser für Starlane CSV Exporte (Starlane LapTable Export).

Dateiformat (Semikolon-getrennt, doppelt-gequotete Zeit-Felder, CRLF):
  Zeile 1: Session-Header   "Event;Session;Run;Driver;Vehicle;Date;Time;Track;"
  Zeile 2: Session-Werte    "FR OSL;RACE;4;Uwe;Panigale V2;2023-07-18;"16:25";Oschersleben"
  Zeile 3: (leer)
  Zeile 4: Lap-Tabellen-Kopf "Lap;Lap Time;Split 1;...;Max RPM;Max Speed;Max H2O;Max TK;"
  Zeile 5+: Lap-Zeilen       "1;"01:36.00";"00:22.26";...;0;230;0;0;"

Anders als RaceBox/AIM ist die Starlane-Datei eine reine **Runden-Tabelle**
ohne GPS-Spur und ohne Per-Sample-Daten. Es gibt also keine `time`/`lat`/
`lon`/`speed`-Sample-Arrays — wir liefern leere Arrays plus `lap_times`.
`detect_laps` (Strategie 0) nutzt `lap_times` direkt; die leeren Arrays
befriedigen nur den unkonditionalen Zugriff am Funktionskopf.

Lap-Zeiten kommen als "MM:SS.ss"-Strings (auch "M:SS.ss" defensiv erlaubt).
Die erste Zeile (Lap 0) ist typischerweise der Out-Lap, die letzte ein
kurzer In-Lap — beide werden NICHT hier gefiltert, sondern fallen durch den
`30 < dur < 600`-Sanity-Filter in `detect_laps` (konsistent zu RaceBox/AIM,
die ihre Lap-Liste ebenfalls roh übergeben).

[NOTE] Datums-Feld ist bei Starlane bereits ISO ("2023-07-18") — wir
reichen es defensiv durch, normalisieren aber auch das DE/EU-Format
"DD.MM.YYYY" und "DD/MM/YYYY" falls es in anderen Exporten auftaucht.

Output-Format (Standard-Track-Dict, kompatibel mit den anderen Parsern):
  meta, time, lat, lon, speed, lap_times, finish_line,
  source_format, source_file
plus optional:
  lap_summaries (pro Runde: index, duration_s, splits, max_speed)
"""
from __future__ import annotations

import csv
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# Pflicht-Spalten im Session-Header (Block 1). Wird vom Sniff-Test genutzt.
_SESSION_HEADER_TOKENS = ("Event", "Session", "Driver", "Vehicle", "Track")
# Pflicht-Spalten im Lap-Tabellen-Kopf (Block 2).
_LAP_HEADER_TOKENS = ("Lap", "Lap Time")

# "MM:SS.ss" oder "M:SS.ss" — auch "H:MM:SS.ss" defensiv.
_LAPTIME_RE = re.compile(
    r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)\s*$"
)


def _strip_row(row: List[str]) -> List[str]:
    """Trim Zellen und entferne trailing empties (Starlane hängt ein ; an)."""
    cleaned = [c.strip() for c in row]
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return cleaned


def _parse_laptime(s: str) -> Optional[float]:
    """'01:36.00' → 96.0 Sekunden. 'H:MM:SS.ss' wird ebenfalls erkannt.
    Liefert None bei unparsebarem Input (z.B. leeres Feld)."""
    if not s:
        return None
    m = _LAPTIME_RE.match(s.strip().strip('"'))
    if not m:
        return None
    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2))
    seconds = float(m.group(3))
    return hours * 3600.0 + minutes * 60.0 + seconds


def _parse_starlane_date(date_str: str) -> str:
    """Normalisiere das Datum nach ISO 'YYYY-MM-DD'.
    Starlane liefert meist schon ISO; DD.MM.YYYY und DD/MM/YYYY defensiv.
    Bei Failure: Originalstring (gestrippt)."""
    s = (date_str or "").strip().strip('"')
    if not s:
        return ""
    # Schon ISO?
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{1,2})[.\/](\d{1,2})[.\/](\d{4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except (ValueError, TypeError):
            return s
    return s


def is_starlane_csv(filepath: str) -> bool:
    """Sniff-Test: Erste nicht-leere Zeile ist der Starlane-Session-Header
    (Semikolon-getrennt, beginnt mit 'Event' und enthält 'Driver'+'Vehicle'
    +'Track'). Wird vom Dispatcher genutzt um Starlane von AIM/RaceBox CSV
    zu unterscheiden (alle drei haben Extension .csv)."""
    try:
        with open(filepath, "r", encoding="utf-8", newline="") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                if ";" not in line:
                    return False
                cells = [c.strip() for c in line.split(";") if c.strip()]
                # Header muss mit 'Event' starten und die Kern-Tokens haben.
                if not cells or cells[0] != "Event":
                    return False
                cellset = set(cells)
                return all(tok in cellset for tok in _SESSION_HEADER_TOKENS)
    except (OSError, UnicodeDecodeError):
        return False
    return False


def parse_starlane_csv(filepath: str) -> Dict[str, Any]:
    """Parse eine Starlane LapTable CSV und return das Standard-Track-Dict."""
    session_header: List[str] = []
    session_values: List[str] = []
    lap_header: List[str] = []
    lap_rows: List[List[str]] = []

    with open(filepath, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")

        # Phase 1: Session-Header + Session-Werte (Block 1).
        for row in reader:
            cells = _strip_row(row)
            if not cells:
                continue
            if cells[0] == "Event":
                session_header = cells
                continue
            if session_header and not session_values:
                session_values = cells
                continue
            # Phase 2: Lap-Tabellen-Kopf (Block 2).
            if cells[0] == "Lap":
                lap_header = cells
                break

        if not session_header:
            raise ValueError("Starlane CSV: Session-Header (Zeile 'Event;...') nicht gefunden")
        if not lap_header:
            raise ValueError("Starlane CSV: Lap-Tabellen-Kopf (Zeile 'Lap;Lap Time;...') nicht gefunden")

        # Phase 3: Lap-Datenzeilen.
        for row in reader:
            cells = _strip_row(row)
            if not cells:
                continue
            lap_rows.append(cells)

    # --- Session-Meta aus Block 1 ------------------------------------------
    smeta: Dict[str, str] = {}
    for i, key in enumerate(session_header):
        if i < len(session_values):
            smeta[key] = session_values[i].strip().strip('"')

    # --- Lap-Spalten-Index aus Block 2 -------------------------------------
    col_index = {name: i for i, name in enumerate(lap_header)}
    for col in _LAP_HEADER_TOKENS:
        if col not in col_index:
            raise ValueError(f"Starlane CSV: Pflichtspalte '{col}' im Lap-Kopf fehlt")

    iLap = col_index["Lap"]
    iTime = col_index["Lap Time"]
    iMaxSpeed = col_index.get("Max Speed")
    split_cols = [(name, idx) for name, idx in col_index.items()
                  if name.lower().startswith("split")]
    split_cols.sort(key=lambda kv: kv[1])

    # --- Lap-Zeilen parsen -------------------------------------------------
    # Wir bauen `lap_times` als (start_t, duration) — start_t ist die
    # kumulative Summe der bisherigen Dauern (es gibt keine Absolutzeit pro
    # Runde in der Datei, nur Dauern). Das reicht für detect_laps Strategie 0.
    lap_times: List[Tuple[float, float]] = []
    lap_summaries: List[Dict[str, Any]] = []
    cumulative_t = 0.0

    for cells in lap_rows:
        if len(cells) <= max(iLap, iTime):
            continue
        dur = _parse_laptime(cells[iTime])
        if dur is None or dur <= 0:
            continue
        try:
            lap_idx = int(cells[iLap])
        except (ValueError, IndexError):
            lap_idx = len(lap_summaries)

        start_t = cumulative_t
        lap_times.append((start_t, dur))
        cumulative_t += dur

        splits: List[float] = []
        for _, sidx in split_cols:
            if sidx < len(cells):
                sv = _parse_laptime(cells[sidx])
                splits.append(sv if sv is not None else 0.0)

        max_speed = None
        if iMaxSpeed is not None and iMaxSpeed < len(cells):
            try:
                max_speed = float(cells[iMaxSpeed])
            except ValueError:
                max_speed = None

        lap_summaries.append({
            "lap_index": lap_idx,
            "duration_s": dur,
            "splits": splits,
            "max_speed": max_speed,
        })

    if not lap_times:
        raise ValueError("Starlane CSV: keine gültigen Runden geparst")

    # --- Standard-Meta ------------------------------------------------------
    out_meta: Dict[str, Any] = {
        "SOURCE": "STARLANE",
        "LOGGER": "STARLANE",
    }
    if smeta.get("Track"):
        out_meta["TRACK"] = smeta["Track"]
        out_meta["VENUE"] = smeta["Track"]
    if smeta.get("Vehicle"):
        out_meta["VEHICLE"] = smeta["Vehicle"]
    if smeta.get("Driver"):
        out_meta["RACER"] = smeta["Driver"]
    if smeta.get("Event"):
        out_meta["EVENT"] = smeta["Event"]
    if smeta.get("Session"):
        out_meta["SESSION"] = smeta["Session"]
    if smeta.get("Run"):
        out_meta["RUN"] = smeta["Run"]
    if smeta.get("Date"):
        parsed = _parse_starlane_date(smeta["Date"])
        if parsed:
            out_meta["DATE"] = parsed
    if smeta.get("Time"):
        out_meta["TIME_OF_DAY"] = smeta["Time"].strip().strip('"')

    out_meta["LAP_COUNT"] = len(lap_times)
    # FASTEST_LAP nur aus plausiblen Runden (gleiches Fenster wie der
    # 30<dur<600-Sanity-Filter in detect_laps), damit kurze In-/Out-Lap-
    # Trigger die angezeigte Bestzeit nicht verfälschen. Fallback auf alle
    # Runden falls keine im Plausibilitätsfenster liegt.
    plausible = [d for _, d in lap_times if 30 < d < 600]
    fastest_s = min(plausible) if plausible else min(d for _, d in lap_times)
    fmins = int(fastest_s // 60)
    fsecs = fastest_s - fmins * 60
    out_meta["FASTEST_LAP"] = f"{fmins}:{fsecs:06.3f}"

    # --- Leere Sample-Arrays (Starlane hat keine GPS-Spur) -----------------
    empty = np.zeros(0, dtype=np.float64)

    result: Dict[str, Any] = {
        "meta": out_meta,
        "time": empty,
        "lat": empty,
        "lon": empty,
        "speed": empty,            # km/h (keine Samples)
        "lap_times": lap_times,
        "lap_summaries": lap_summaries,
        "finish_line": None,
        "source_format": "STARLANE_CSV",
        "source_file": filepath,
    }
    return result
