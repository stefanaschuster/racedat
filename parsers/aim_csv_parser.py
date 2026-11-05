"""Parser für AIM CSV Exporte (AIM RaceStudio Logger).

Dateiformat (alle Felder doppelt-gequotet, CRLF-Zeilenenden):
  Zeile  1: "Format","AiM CSV File"
  Zeile  2: "Session","<Track>"
  Zeile  3: "Vehicle","<Bike>"
  Zeile  4: "Racer","<Name>"
  Zeile  5: "Championship","<...>"
  Zeile  6: "Comment","<...>"
  Zeile  7: "Date","Wednesday, December 31, 2025"
  Zeile  8: "Time","11:45 AM"
  Zeile  9: "Sample Rate","20"             # Hz
  Zeile 10: "Duration","14062"             # Session-Ende in Sekunden
  Zeile 11: "Segment","Session"
  Zeile 12: "Beacon Markers","T1","T2",...,"Duration"  # Sekunden seit Start
  Zeile 13: "Segment Times","M:SS.mmm",...,"H:MM:SS"   # Dauer pro Beacon-Segment
  Zeile 14: (leer)
  Zeile 15: "Time","GPS Speed","GPS Nsat",...,"<Bike-Kanal-1>",...,"Distance on GPS Speed"
  Zeile 16: "s","km/h"," ","g","g",..., "%", "m"       # Einheiten
  Zeile 17: (leer)
  Zeile 18+: Daten

[NOTE] Beacon Markers enthalten oft Box-/Split-Trigger mit <60s Abstand
zueinander. Wir filtern diese als "keine echte Runde" raus (Stefan-Decision
v23.6). Der letzte Beacon ist immer == Duration und markiert das Session-Ende,
nicht einen echten Runden-Trigger.

[NOTE] Datums-Parsing ist robust gegen Locale: wir verwenden eine eigene
Lookup-Table für englische Monatsnamen statt strptime mit %B (das wäre
Locale-abhängig). Bei Failure bleibt DATE einfach leer — kein Crash.

Output-Format (Standard-Track-Dict, kompatibel mit den anderen Parsern):
  meta, time, lat, lon, speed, lap_times, channels, finish_line,
  source_format, source_file
"""
from __future__ import annotations

import csv
import re
from typing import Any, Dict, List, Tuple

import numpy as np


# Englische Monatsnamen für robustes Datumsparsing (kein Locale-Dependency).
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# AIM-Datums-Pattern: "Wednesday, December 31, 2025"
_DATE_RE = re.compile(
    r"^[A-Za-z]+,\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s*$"
)

# Minimale Rundenlänge in Sekunden — alles darunter sind Box-/Split-Trigger,
# keine echten Runden (Stefan-Decision v23.6).
MIN_LAP_DURATION_S = 60.0


def _parse_aim_date(date_str: str) -> str:
    """'Wednesday, December 31, 2025' → '2025-12-31'. Bei Failure: ''."""
    if not date_str:
        return ""
    m = _DATE_RE.match(date_str.strip())
    if not m:
        return ""
    month_name, day_str, year_str = m.group(1).lower(), m.group(2), m.group(3)
    month = _MONTHS.get(month_name)
    if not month:
        return ""
    try:
        return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"
    except (ValueError, TypeError):
        return ""


def _unquote_row(row: List[str]) -> List[str]:
    """csv.reader strippt Quotes schon, aber wir kriegen manchmal Leerwerte
    am Ende durch trailing commas. Trim & drop trailing empties."""
    cleaned = [c.strip() for c in row]
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return cleaned


def is_aim_csv(filepath: str) -> bool:
    """Sniff-Test: Erste nicht-leere Zeile beginnt mit "Format","AiM CSV File"?
    Wird vom Dispatcher genutzt um zwischen AIM CSV und RaceBox CSV zu
    unterscheiden (beide haben Extension .csv)."""
    try:
        with open(filepath, "r", encoding="utf-8", newline="") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                # Akzeptiere beide Quoting-Varianten defensiv
                return (
                    line.startswith('"Format","AiM CSV File"')
                    or line.startswith("Format,AiM CSV File")
                )
    except (OSError, UnicodeDecodeError):
        return False
    return False


def parse_aim_csv(filepath: str) -> Dict[str, Any]:
    """Parse eine AIM CSV Datei und return das Standard-Track-Dict."""
    meta_raw: Dict[str, Any] = {}
    beacon_markers: List[float] = []

    with open(filepath, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)

        # Phase 1: Header bis zur Data-Tabelle (erkannt an "Time" + viele
        # weitere Spalten, kein einzelner Wert).
        data_header: List[str] = []
        units_row: List[str] = []
        for row in reader:
            cells = _unquote_row(row)
            if not cells:
                continue
            key = cells[0]

            if key == "Time" and len(cells) > 2:
                # Daten-Tabellenkopf gefunden.
                data_header = cells
                break

            if key == "Beacon Markers":
                # Werte 1..n-1 sind echte Beacons; letzter Wert == Duration
                # (Session-Ende-Sentinel, kein echter Beacon).
                for v in cells[1:]:
                    try:
                        beacon_markers.append(float(v))
                    except ValueError:
                        continue
            elif key == "Segment Times":
                # nicht benötigt — wir bauen Dauer aus Beacon-Differenzen
                pass
            elif len(cells) >= 2:
                meta_raw[key] = cells[1]

        if not data_header:
            raise ValueError("AIM CSV: Daten-Header (Zeile mit Spaltennamen) nicht gefunden")

        # Phase 2: Einheiten-Zeile (direkt nach Header)
        for row in reader:
            cells = _unquote_row(row)
            if not cells:
                continue
            units_row = cells
            break

        # Pad Units falls kürzer als Header
        while len(units_row) < len(data_header):
            units_row.append("")

        # Phase 3: Daten — Pre-Allocation per Spalte
        col_index = {name: i for i, name in enumerate(data_header)}
        required = ["Time", "GPS Speed", "GPS Latitude", "GPS Longitude"]
        for col in required:
            if col not in col_index:
                raise ValueError(f"AIM CSV: Pflichtspalte '{col}' fehlt")

        n_cols = len(data_header)
        cols_data: List[List[float]] = [[] for _ in range(n_cols)]

        iT = col_index["Time"]
        for row in reader:
            cells = _unquote_row(row)
            if not cells:
                continue
            if len(cells) < n_cols:
                # Defensiv: nicht crashen bei zerschossener Zeile
                continue
            try:
                # Time muss parsebar sein, sonst Zeile skippen
                float(cells[iT])
            except ValueError:
                continue
            for i in range(n_cols):
                try:
                    cols_data[i].append(float(cells[i]))
                except ValueError:
                    # Spalte unparsebar (z.B. nicht-numerisch) → 0.0 als
                    # Filler, damit alle Spalten gleich lang bleiben.
                    cols_data[i].append(0.0)

    if not cols_data[iT]:
        raise ValueError("AIM CSV: keine Datenzeilen geparst")

    # numpy-arrays bauen
    arrays = [np.asarray(c, dtype=np.float64) for c in cols_data]
    time_arr = arrays[iT]
    speed_arr = arrays[col_index["GPS Speed"]]
    lat_arr = arrays[col_index["GPS Latitude"]]
    lon_arr = arrays[col_index["GPS Longitude"]]

    # Sample-Rate aus Meta (für Channel-rate-Info)
    try:
        sample_rate_hz = int(float(meta_raw.get("Sample Rate", "0")))
    except (ValueError, TypeError):
        sample_rate_hz = 0
    if sample_rate_hz <= 0 and len(time_arr) > 1:
        dt = float(np.median(np.diff(time_arr)))
        sample_rate_hz = int(round(1.0 / dt)) if dt > 0 else 0

    # Distance-Spalte raussuchen für Hybrid-Trackmap (Stefan-Decision v23.7).
    # In manchen AIM-Exporten (z.B. wenn die GPS-Antenne ausfällt) sind
    # GPS Speed/Latitude/Longitude konstant 0 oder eingefroren, aber die
    # `Distance on GPS Speed`-Spalte läuft sauber weiter (intern via
    # Inertial-Sensoren oder Wheel-Speed berechnet). Wir exportieren daher
    # Lap-Distanzen ZUSÄTZLICH zu den Lap-Zeiten, damit der Datenviewer
    # bei tot-GPS auf Distance-basierte Trackmap zurückfallen kann.
    dist_arr: np.ndarray = None
    for dist_name in ("Distance on GPS Speed", "Distance"):
        if dist_name in col_index:
            dist_arr = arrays[col_index[dist_name]]
            break

    # Lap-Detection aus Beacon Markers.
    # AIM-Konvention: Marker[0..n-2] sind Lap-Endzeiten in Sekunden seit
    # Start, Marker[n-1] == Duration (Session-Ende, kein Trigger einer
    # echten Runde). Wir droppen den letzten Marker, sonst kriegen wir
    # einen Phantom-Lap von "letzter echter Beacon → Session-Ende"
    # (typisch mehrere tausend Sekunden, weil man nicht sofort den Logger
    # ausschaltet wenn man in die Box rollt).
    #
    # Filter: nur Dauer < MIN_LAP_DURATION_S = Box-/Split-Trigger, kein
    # echter Lap (in beiden Beispieldateien gibt es 0:10/0:20-Splits bei
    # Pit-Stops, die wollen wir nicht als "Runde" sehen). Beacon-Liste ist
    # ansonsten Source of Truth (Stefan-Decision v23.7: RS3-konform).
    #
    # [NOTE] Ein früherer Speed-Filter (v23.6, max_speed < 30 km/h) wurde
    # entfernt — er war eine Fehl-Diagnose. Bei der Aragon-Beispieldatei
    # ist GPS Speed ab Lap 6 konstant 0 weil die GPS-Antenne ausgefallen
    # ist, ABER die echten Runden laufen weiter (Distance-Spalte zeigt das
    # klar, RS3 zeigt die korrekt). Der Speed-Filter hätte 24 echte Runden
    # weggeworfen.
    lap_times: List[Tuple[float, float]] = []
    lap_distances: List[Tuple[float, float]] = []
    if len(beacon_markers) >= 2:
        # Duration-Sentinel droppen falls vorhanden (letzter Beacon == Duration)
        try:
            duration_s = float(meta_raw.get("Duration", "0"))
        except (ValueError, TypeError):
            duration_s = 0.0
        real_beacons = list(beacon_markers)
        if duration_s > 0 and abs(real_beacons[-1] - duration_s) < 0.5:
            real_beacons.pop()
        # Boundaries: [0, b1, b2, ..., b_last]; Lap i läuft von boundaries[i]
        # bis boundaries[i+1].
        boundaries = [0.0] + real_beacons
        for i in range(len(boundaries) - 1):
            start_t = boundaries[i]
            dur = boundaries[i + 1] - boundaries[i]
            # Filter: <60s ist Box-/Split-Trigger, nicht eine echte Runde.
            if dur < MIN_LAP_DURATION_S:
                continue
            lap_times.append((start_t, dur))
            # Distance-Boundaries dazu (falls Distance-Spalte vorhanden).
            if dist_arr is not None and len(dist_arr) > 0:
                end_t = start_t + dur
                i0 = int(np.searchsorted(time_arr, start_t, side="left"))
                i1 = int(np.searchsorted(time_arr, end_t, side="left"))
                i1 = min(i1, len(dist_arr) - 1)
                i0 = min(i0, len(dist_arr) - 1)
                d_start = float(dist_arr[i0])
                d_end = float(dist_arr[i1])
                lap_distances.append((d_start, d_end - d_start))

    # Channels-Dict bauen — alle Spalten außer Time/Lat/Lon/Speed (die im
    # Top-Level-Dict landen). Die übrigen GPS-Kanäle + Bike-spezifische
    # Kanäle gehen in `channels` rein, damit der Coach + Datenviewer sie
    # über die Channel-Role-Registry konsumieren können.
    top_level_cols = {"Time", "GPS Speed", "GPS Latitude", "GPS Longitude"}
    channels: Dict[str, Dict[str, Any]] = {}
    for i, name in enumerate(data_header):
        if name in top_level_cols:
            continue
        if not name:
            continue
        channels[name] = {
            "time": time_arr.copy(),
            "data": arrays[i],
            "rate": sample_rate_hz,
            "unit": units_row[i] if i < len(units_row) else "",
        }

    # Meta in Standard-Form übersetzen
    out_meta: Dict[str, Any] = {
        "SOURCE": "AIM",
        "LOGGER": "AIM",
    }
    if meta_raw.get("Session"):
        out_meta["VENUE"] = meta_raw["Session"]
        out_meta["TRACK"] = meta_raw["Session"]
    if meta_raw.get("Vehicle"):
        out_meta["VEHICLE"] = meta_raw["Vehicle"]
    if meta_raw.get("Racer"):
        out_meta["RACER"] = meta_raw["Racer"]
    if meta_raw.get("Championship") and meta_raw["Championship"] != "None":
        out_meta["CHAMPIONSHIP"] = meta_raw["Championship"]
    if meta_raw.get("Comment"):
        out_meta["COMMENT"] = meta_raw["Comment"]
    if meta_raw.get("Date"):
        parsed = _parse_aim_date(meta_raw["Date"])
        if parsed:
            out_meta["DATE"] = parsed
    if meta_raw.get("Time"):
        out_meta["TIME_OF_DAY"] = meta_raw["Time"]
    if sample_rate_hz > 0:
        out_meta["SAMPLE_RATE_HZ"] = sample_rate_hz
    if lap_times:
        out_meta["LAP_COUNT"] = len(lap_times)
        fastest_s = min(d for _, d in lap_times)
        mins = int(fastest_s // 60)
        secs = fastest_s - mins * 60
        out_meta["FASTEST_LAP"] = f"{mins}:{secs:06.3f}"

    result: Dict[str, Any] = {
        "meta": out_meta,
        "time": time_arr,
        "lat": lat_arr,
        "lon": lon_arr,
        "speed": speed_arr,  # km/h
        "channels": channels,
        "finish_line": None,
        "source_format": "AIM_CSV",
        "source_file": filepath,
    }
    if lap_times:
        result["lap_times"] = lap_times
    if lap_distances:
        # Hybrid-Trackmap: bei tot-GPS kann der Datenviewer Lap-Slices über
        # die Distance-Spalte definieren (Stefan-Decision v23.7).
        result["lap_distances"] = lap_distances

    return result
