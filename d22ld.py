#!/usr/bin/env python3
"""d22ld — Convert 2D Datenrecorder bundles (.MES/.zip) to MoTeC i2 .ld + .ldx pairs.

Unterstützt beide 2D-Varianten transparent (Erkennung erfolgt im Parser):

  * **bmw_hp** — BMW HP / Werksrennteam-Bundles (80 Channels, 100 Hz Basis,
    int16/float32/float64 mit DDD-Skalierung). ZIP enthält *.MES-Verzeichnis(se)
    direkt im Root, *.HED in UPPERCASE, [LAPTIMES]-Sektion.
  * **race2025** — BMW M1000RR Race2025-Track-Tool (81 Channels, multi-rate
    5..250 Hz, fast alles float32 ohne Skalierung). ZIP enthält ein
    Wrapper-Verzeichnis mit EVENT.INI/<track>.line + .MES-Unterverzeichnis,
    *.hed lowercase, [Laptimes]-Sektion.

Beide Varianten werden vom Parser auf 100 Hz angeglichen und in dasselbe
Output-Schema überführt; dieses Konverter-Skript schreibt aus diesem Schema
das MoTeC-i2-Pärchen.

Usage:
  d22ld.py FILE.zip [FILE2.zip ...] [-o OUT_DIR_OR_PREFIX]
                    [--driver NAME] [--vehicle ID] [--venue NAME]
                    [--event NAME] [--session SESSION] [--comment TEXT]
                    [--rename-channels]

Beispiele:
  # Eine Datei (output: bundle.ld + bundle.ldx neben der Eingabe)
  python3 d22ld.py 2D_MUGELLO_20230701-1547-01_MES.zip

  # Mehrere Bundles in ein Ziel-Verzeichnis
  python3 d22ld.py *.zip -o /tmp/converted/

  # Race2025-Wrapper-ZIP — funktioniert genauso, Variant wird erkannt
  python3 d22ld.py 2D_Measurements_from_VALENCIA6D_26.zip

  # Mit AiM/MoTeC-Channel-Renaming (RPM → Engine RPM, VWheelFL → Wheel Speed FL …)
  python3 d22ld.py session.zip --rename-channels

  # Metadata überschreiben
  python3 d22ld.py session.zip --driver "Stefan" --session "FP1"

Hinweise:
  * `.MES`-Verzeichnisse direkt (nicht als ZIP) sind ebenfalls akzeptiert.
  * Die `.line`-Start-Ziel-Linie (race2025) wird im MoTeC-Format nicht
    abgebildet — i2 nutzt Beacons. Wir loggen sie nur informativ.
  * Bei Namens-Kollisionen im 2D-Bundle (z.B. zwei "Gear"-Channels — analog +
    computed) suffixt der Parser bereits mit der DDD-Section-ID, sodass beide
    Channels mit unterschiedlichen Namen geschrieben werden.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
except ImportError:
    print("ERROR: numpy required (sudo apt install python3-numpy)", file=sys.stderr)
    sys.exit(2)

from parsers import parse_2d
from parsers.ld_writer import (
    write_ld, LDChannel,
    DTA_INT16, DTA_INT32,
    gps_lat_channel, gps_lon_channel, gps_speed_channel,
    beacon_channel, running_lap_time_channel,
)
from parsers.ldx_writer import write_ldx
from parsers.channel_names import map_name


# 2D-spezifische GPS-Channel-Namen (mehrere Schreibweisen, vgl. d2_parser.py
# Zeilen 777-779). Diese müssen aus den "normalen" Channels rausgefiltert
# werden, damit sie nicht doppelt geschrieben werden — wir behandeln Lat/Lon/
# Speed mit den dedizierten gps_*-Buildern.
GPS_LAT_NAMES = {"Latitude", "GPS_Latitude", "Lat_dez"}
GPS_LON_NAMES = {"Longitude", "GPS_Longitude", "Lon_dez"}
GPS_SPEED_NAMES = {"Speed", "GPS_Speed_over_", "V_GPS"}
GPS_ALL_NAMES = GPS_LAT_NAMES | GPS_LON_NAMES | GPS_SPEED_NAMES


def _pick_dtype(values: np.ndarray):
    """Pick a sensible (datatype_a, data_size, dec) for a channel.

    Goal: preserve precision while staying within int16 range when possible.
    Returns (datatype_a, data_size, dec). Identisch zur xrk2ld-Heuristik.
    """
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return DTA_INT16, 2, 0
    max_abs = float(np.max(np.abs(finite)))
    if max_abs == 0:
        return DTA_INT16, 2, 0

    # Try increasingly precise int16 encodings: dec=0..3
    for dec in (0, 1, 2, 3):
        scaled = max_abs * (10 ** dec)
        if scaled < 32000:
            return DTA_INT16, 2, dec
    # Need more precision → int32
    for dec in (3, 4, 5, 6, 7):
        scaled = max_abs * (10 ** dec)
        if scaled < 2_000_000_000:
            return DTA_INT32, 4, dec
    return DTA_INT32, 4, 0


def _safe_rate(rate, name, fallback=100):
    """Validate sample rate is in usable range (1..65535)."""
    try:
        r = int(rate)
    except (TypeError, ValueError):
        r = fallback
    if r <= 0 or r > 65535:
        print(f"  [d22ld] dropping channel '{name}' — implausible rate {rate} Hz",
              file=sys.stderr)
        return None
    return r


def _build_channels(track: dict, rename: bool):
    """Build a list of LDChannel objects from a parsed 2D track.

    Der Parser hat alle Channels bereits auf 100 Hz angeglichen, sodass wir
    nicht zwischen unterschiedlichen Raten jonglieren müssen — wir nehmen
    einfach 100 Hz als globale Rate (entspricht len(track['time']) / dauer).
    Die im channels-dict gespeicherte native `rate` ist nur informativ.
    """
    channels = []

    # Globale Rate aus dem Zeitvektor herleiten — der Parser garantiert 100 Hz,
    # aber wir leiten's sauber ab, falls sich das je ändert.
    time_arr = track["time"]
    n = len(time_arr)
    if n > 1:
        dt_median = float(np.median(np.diff(time_arr)))
        rate_hz = int(round(1.0 / dt_median)) if dt_median > 0 else 100
    else:
        rate_hz = 100
    rate_hz = _safe_rate(rate_hz, "(global)", fallback=100) or 100

    # GPS-Channels: Latitude/Longitude/Speed mit den dedizierten Buildern, damit
    # sie korrekte dec/datatype (lat/lon: int32 dec=7, speed: int16 dec=1) und
    # die MoTeC-Standardnamen "GPS Latitude" / "GPS Longitude" / "GPS Speed"
    # bekommen — das ist Voraussetzung dafür, dass i2 die Track-Map zeichnet.
    lat = track["lat"]
    lon = track["lon"]
    speed = track["speed"]
    if lat is not None and len(lat) > 0 and np.any(np.isfinite(lat)):
        channels.append(gps_lat_channel(lat, rate_hz))
        channels.append(gps_lon_channel(lon, rate_hz))
    if speed is not None and len(speed) > 0 and np.any(speed != 0):
        channels.append(gps_speed_channel(speed, rate_hz))

    # Alle übrigen Channels — GPS-Quellen ausschließen, damit Lat/Lon/Speed
    # nicht doppelt landen.
    for name, ch in track.get("channels", {}).items():
        # Auch suffixed Varianten ("Latitude_311" etc.) ausschließen, falls der
        # Parser eine Kollision mit Section-ID-Suffix gespeichert hat. Wir
        # prüfen auf den Präfix-Match vor dem Underscore.
        base = name.split("_")[0] if "_" in name else name
        if name in GPS_ALL_NAMES:
            continue
        # Strikt: "Lat_dez", "Lon_dez", "GPS_Speed_over_" haben Underscores die
        # NICHT die Section-ID-Suffix-Konvention sind — die behandeln wir oben.
        # Hier prüfen wir nur ungesuffixte Konflikte.
        if base in {"Latitude", "Longitude", "Speed"} and name in GPS_ALL_NAMES:
            continue

        data = ch["data"]
        if len(data) == 0 or not np.any(np.isfinite(data)):
            continue

        # Beim 2D-Pipeline-Output ist `rate` die native Channel-Rate (z.B. 25
        # Hz für GPS oder 250 Hz für Suspension bei race2025), aber die `data`
        # selbst sind auf 100 Hz upsampled. Für MoTeC ist nur entscheidend,
        # dass alle Channels denselben Stream haben — also nehmen wir die
        # globale Rate.
        out_name, out_short = (map_name(name) if rename else (name, name[:8]))
        # i2 mag keine zu langen Namen — pragmatisch auf 32 Zeichen kürzen.
        out_name = out_name[:32]
        out_short = out_short[:8]
        dta, sz, dec = _pick_dtype(data)
        channels.append(LDChannel(
            out_name, ch.get("unit", "") or "", rate_hz, data,
            short_name=out_short,
            datatype_a=dta, data_size=sz, dec=dec,
        ))

    return channels, rate_hz


def _format_motec_date(date_str: str) -> str:
    """Parser liefert 'YYYY-MM-DD' (ISO), MoTeC i2 erwartet 'DD/MM/YYYY'."""
    if not date_str:
        return ""
    parts = date_str.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        # ISO → DD/MM/YYYY
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return date_str  # already DD/MM/YYYY or unknown shape, pass through


def convert_2d(bundle_path, out_base=None, *,
               driver=None, vehicle=None, venue=None,
               event=None, session="", comment="",
               rename=False, quiet=False):
    """Convert one 2D bundle (.zip or .MES dir) → .ld + .ldx pair.

    Returns (ld_path, ldx_path).
    """
    def log(msg):
        if not quiet:
            print(msg)

    log(f"Reading {bundle_path} …")
    track = parse_2d(bundle_path)
    meta = track["meta"]
    n = len(track["time"])
    duration = float(track["time"][-1] - track["time"][0]) if n > 1 else 0.0
    log(f"  Variant: {meta.get('VARIANT', '?')}, records: {n}, "
        f"duration: {duration:.1f}s ({duration/60:.1f}min)")
    log(f"  Venue: {meta.get('VENUE', '?')}, Date: {meta.get('DATE', '?')}")
    if n > 0:
        log(f"  GPS speed: {track['speed'].min():.1f} – "
            f"{track['speed'].max():.1f} km/h")
    log(f"  Channels available: {len(track['channels'])}")

    # Lap-Times kommen aus der HED-[LAPTIMES]-Sektion (oder dem Laptrigger-
    # Channel-Fallback) und sind im 2D-Parser bereits gefiltert (Out-/In-Lap
    # via Fastest-Anchor entfernt).
    lap_times_pairs = track.get("lap_times") or []
    log(f"  Laps: {len(lap_times_pairs)}"
        + (f" (fastest declared: {meta['FASTEST_LAP']})"
           if meta.get("FASTEST_LAP") else ""))
    for i, (st, dur) in enumerate(lap_times_pairs[:3]):
        mm = int(dur // 60); ss = dur % 60
        log(f"    Lap {i+1}: {mm}:{ss:06.3f}  (start {st:.1f}s)")
    if len(lap_times_pairs) > 3:
        log(f"    … and {len(lap_times_pairs)-3} more")

    # Build channels + ermittle die globale Rate.
    channels, rate_hz = _build_channels(track, rename=rename)

    if not channels:
        raise RuntimeError("No usable channels in 2D bundle")

    # Beacon + Running-Lap-Time. Beacons sind Sample-Indices an den
    # Lap-Start-Zeitpunkten + dem Ende der letzten Runde (sodass i2 die
    # letzte Runde sauber abschließen kann).
    if lap_times_pairs:
        beacon_session_times = [st for st, _ in lap_times_pairs]
        last_st, last_dur = lap_times_pairs[-1]
        beacon_session_times.append(last_st + last_dur)

        beacon_idx = [int(np.searchsorted(track["time"], t))
                      for t in beacon_session_times]
        channels.append(beacon_channel(len(track["time"]), rate_hz, beacon_idx))
        channels.append(running_lap_time_channel(
            track["time"], beacon_session_times, rate_hz))

    # Output paths
    bundle_str = str(bundle_path)
    if out_base is None:
        # Für .zip: neben der ZIP. Für .MES-Verzeichnis: neben dem Verzeichnis.
        out_base = os.path.splitext(bundle_str)[0]
        # Verzeichnis-Ende ".MES" hängen lassen wir nicht in der LD-Datei kleben.
        if out_base.endswith(".MES") or out_base.endswith(".mes"):
            out_base = out_base[:-4]
    ld_path = out_base + ".ld"
    ldx_path = out_base + ".ldx"

    # Metadata defaults aus HED / EVENT.INI (vom Parser bereits extrahiert)
    if driver is None:
        driver = meta.get("RACER", "")
    if vehicle is None:
        # BMW HP-Variant trägt's im Parser fest ein; race2025 lässt's leer.
        vehicle = meta.get("VEHICLE", "")
        # Logger-Bezeichnung als ergänzender Hinweis, wenn Vehicle leer ist.
        if not vehicle and meta.get("LOGGER"):
            vehicle = meta["LOGGER"]
    if venue is None:
        venue = meta.get("VENUE", "")
    if event is None:
        # Bevorzugt den langen Track-Namen aus race2025-EVENT.INI, sonst Venue.
        event = meta.get("TRACK") or venue or "2D Session"
    if not comment:
        # Variant + Logger-Info in den Kommentar, damit man die Quelle in i2
        # sieht. Halt kurz (max 64 chars im .ld-Format).
        variant = meta.get("VARIANT", "")
        bits = ["2D"]
        if variant:
            bits.append(variant)
        if meta.get("LAPMETER_M"):
            bits.append(f"{meta['LAPMETER_M']}m")
        comment = " · ".join(bits)[:64]

    motec_date = _format_motec_date(meta.get("DATE", ""))
    # 2D-HED hat keine eigene Uhrzeit als getrennten Wert — der Start-of-
    # download enthält's, wird aber vom Parser nicht aufgesplittet. Lassen wir
    # leer; i2 zeigt dann "00:00:00".
    motec_time = ""

    # Finish-Line aus race2025-.line nur informativ loggen — MoTeC nutzt nur
    # Beacons.
    fl = track.get("finish_line")
    if fl is not None:
        log(f"  Finish-line: {fl[0]:.5f}, {fl[1]:.5f} (informativ; i2 nutzt Beacons)")

    log(f"Writing {ld_path} …")
    write_ld(
        ld_path, channels,
        driver=driver, vehicle=vehicle, venue=venue,
        event_name=event, session=session, comment=comment,
        date=motec_date, time=motec_time,
    )
    ld_size = os.path.getsize(ld_path)
    log(f"  OK ({ld_size:,} bytes, {len(channels)} channels @ {rate_hz} Hz)")

    log(f"Writing {ldx_path} …")
    write_ldx(
        ldx_path,
        [dur for _, dur in lap_times_pairs],
        event=event, venue=venue,
        driver=driver, vehicle=vehicle, session=session,
        log_date=motec_date, log_time=motec_time,
    )
    log(f"  OK ({len(lap_times_pairs)} lap markers)")

    return ld_path, ldx_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        prog="d22ld",
        description="Convert 2D Datenrecorder bundles (.MES/.zip) to MoTeC i2 "
                    ".ld + .ldx pairs. Erkennt bmw_hp- und race2025-Varianten "
                    "automatisch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 2)[2] if __doc__ else None,
    )
    ap.add_argument("inputs", nargs="+", metavar="FILE",
                    help="One or more 2D bundles (.zip with .MES inside, "
                         "or a .MES directory directly)")
    ap.add_argument("-o", "--out", default=None,
                    help="Output base path or directory. "
                         "For one input: full base path (e.g. -o /tmp/foo "
                         "produces /tmp/foo.ld + /tmp/foo.ldx). "
                         "For multiple inputs: target directory.")
    ap.add_argument("--driver", default=None, help="Override driver name")
    ap.add_argument("--vehicle", default=None, help="Override vehicle id")
    ap.add_argument("--venue", default=None, help="Override venue/track name")
    ap.add_argument("--event", default=None, help="Override event name")
    ap.add_argument("--session", default="", help="Session label (e.g. 'FP1')")
    ap.add_argument("--comment", default="", help="Short comment (overrides "
                    "default '2D · <variant> · <lapmeter>m')")
    ap.add_argument("--rename-channels", action="store_true",
                    help="Map 2D/AiM channel names to MoTeC standard names "
                         "where known (RPM → Engine RPM etc.)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="Only output errors and final paths")
    args = ap.parse_args()

    # Validate inputs
    for path in args.inputs:
        if not os.path.exists(path):
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            return 2
        # Akzeptiert: .zip-Datei, .MES-Verzeichnis, oder allg. Verzeichnis
        # (das Parsing entscheidet dann anhand des Inhalts).
        p = Path(path)
        if p.is_file() and p.suffix.lower() != ".zip":
            print(f"ERROR: not a .zip or directory: {path}", file=sys.stderr)
            return 2

    # Resolve output strategy
    multi = len(args.inputs) > 1
    if multi and args.out and not os.path.isdir(args.out):
        if os.path.exists(args.out):
            print(f"ERROR: -o must be a directory for multiple inputs: {args.out}",
                  file=sys.stderr)
            return 2
        os.makedirs(args.out, exist_ok=True)

    results = []
    for src in args.inputs:
        if args.out:
            if multi or os.path.isdir(args.out):
                base = os.path.splitext(os.path.basename(src.rstrip("/")))[0]
                # Bei .MES-Verzeichnis-Inputs als Argument: Basename ohne
                # ".MES"-Suffix kürzen.
                if base.endswith(".MES") or base.endswith(".mes"):
                    base = base[:-4]
                out_base = os.path.join(args.out, base)
            else:
                out_base = args.out
        else:
            out_base = None

        try:
            ld_path, ldx_path = convert_2d(
                src, out_base=out_base,
                driver=args.driver, vehicle=args.vehicle,
                venue=args.venue, event=args.event,
                session=args.session, comment=args.comment,
                rename=args.rename_channels,
                quiet=args.quiet,
            )
            results.append((src, ld_path, ldx_path, None))
        except (RuntimeError, ValueError, FileNotFoundError) as e:
            print(f"ERROR converting {src}: {e}", file=sys.stderr)
            results.append((src, None, None, str(e)))
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
