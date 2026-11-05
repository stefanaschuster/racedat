"""Parser for 2D Datenrecorder bundles (.MES directories or .zip).

2D-Datenrecorder kommen in zwei großen Varianten ins Haus:

  • BMW HP / Werksrennteam ("bmw_hp"-Dialekt, v21.30):
        80 Channels, base aus HED [DOWNLOAD]/MainSamplingRate (100 Hz bei
        älteren Loggern, 400 Hz bei BMW M1000RR ab Saison 2025).
        Mix int16/float32/float64 mit scale+offset+mask in DDD line 3.
        ZIP enthält *.MES/-Verzeichnis(se) direkt im Root. *.HED in
        UPPERCASE, [LAPTIMES]-Sektion. Format-Codes: 1, 4, 101, 104,
        10001, 10004.

  • Race2025-Software (BMW M1000RR Track-Tool, "race2025"-Dialekt, v21.31):
        81 Channels, multi-rate (5/10/25/50/100/250 Hz), fast alles
        float32 ohne Skalierung. ZIP enthält ein Wrapper-Verzeichnis
        mit EVENT.INI/RING.INI + <bundle>.MES/-Unterverzeichnis. *.hed
        lowercase, [Laptimes]-Sektion. EVENT.INI listet [SPECIAL CHANNELS]
        als Alias-Tabelle, <track>.line liefert Start-Ziel-Linie.
        Format-Codes: 2, 102.

Variant-Erkennung (robust, struktur-basiert):
    EVENT.INI im Wrapper-Verzeichnis → race2025
    sonst (kein Wrapper, .MES direkt) → bmw_hp

Beide Varianten liefern dasselbe Output-Schema.

Gemeinsamer Aufbau pro .MES-Verzeichnis:
    <BUNDLE>.HED|.hed   INI mit Lap-Zeiten, Strecke, Logger-Info
    <BUNDLE>.DDD        INI mit ~80 Channel-Definitionen
    <BUNDLE>.A01..A50   Analog-Channels (int16 oder float32, LE)
    <BUNDLE>.C00..C1B   Computed-Channels (bmw_hp only)
    <BUNDLE>.lap        binärer Lap-Trigger-Dump (race2025 only)
    <BUNDLE>.rdf        komprimiertes Backup-Rohformat (ignoriert)

DDD-Format pro Channel ([3xx]-Sektion, 7 nummerierte Zeilen):
    1=fmt_code,?,?,?,rate_code,word_bits,...   ← Layout
    3=?,?,?,scale,offset,?,divisor,?,mask,     ← IEEE-754 hex-floats
    4=Name,Unit,...
    6=?,?,?,FileExt,...

bmw_hp: rate_code (line 1 feld 5) = HEX-Teiler der HED-MainSamplingRate.
        Bei MainSamplingRate=100 (alt): Werte 1/2/4/8 → 100/50/25/12.5 Hz.
        Bei MainSamplingRate=400 (M1000RR 2025): "4"→100Hz, "8"→50Hz,
        "28" (=0x28=40)→10Hz.
race2025: rate_code (hex) = Sample-Periode in ms; Hz = 1000/period.

Skalierung wird primär an word_bits festgemacht (v21.30-Bugfix):
    16-bit → immer (raw & mask) * scale + offset
    32-bit → als float32; scale+offset nur wenn != 1.0/0.0
    64-bit → als float64; scale+offset nur wenn != 1.0/0.0

Race2025-Floats haben scale=1.0/offset=0.0 → identity, bmw_hp-Floats teilweise
auch Skalierung im 32-bit-Pfad (z.B. RPM ×5, Bank-Encoding).
"""
from __future__ import annotations

import os
import re
import struct
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Format constants
# ---------------------------------------------------------------------------

# Word-bit codes from DDD line 1 field 6 (hex). Maps to bytes-per-sample.
# 0x10=16-bit, 0x20=32-bit, 0x40=64-bit. RAW channels with 16-bit width are
# int16 in the file (needing scale+offset); 32/64-bit are IEEE-754 floats.
_BITS_TO_BYTES = {
    "10": 2,   # 0x10 = 16 bits
    "20": 4,   # 0x20 = 32 bits
    "40": 8,   # 0x40 = 64 bits
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex32_to_float(s: str) -> float:
    """Decode an 8-char hex string as IEEE-754 32-bit float (big-endian-text,
    little-endian byte order — i.e. how 2D writes IEEE-754 in their INI)."""
    try:
        n = int(s, 16) & 0xFFFFFFFF
        return struct.unpack("<f", struct.pack("<I", n))[0]
    except (ValueError, struct.error):
        return 0.0


def _parse_ini(path: Path, encoding: str = "latin-1") -> Dict[str, Dict[str, str]]:
    """Parse a 2D-style INI file. Sections like [300], keys like 1=...,2=....

    2D uses Windows line endings and embeds 0x7F bytes as placeholders in
    string values (which we replace with '?'). Comments are not supported in
    this dialect.
    """
    raw = path.read_bytes()
    # 0x7F (DEL) is used as a literal placeholder; replace before decoding.
    text = raw.replace(b"\x7f", b"?").decode(encoding, errors="replace")

    sections: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\[([^\]]+)\]$", line)
        if m:
            current = m.group(1)
            sections.setdefault(current, {})
            continue
        if current is None:
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            sections[current][k.strip()] = v.rstrip(",").strip()
    return sections


def _parse_lap_duration(text: str) -> Optional[float]:
    """Decode a 2D lap-time string into seconds.

    Formats seen across both dialects:
      "2:01.540"          → 121.540 (bmw_hp, race2025 long laps)
      "1:44.040"          → 104.040 (race2025)
      "0:55.120"          → 55.120  (race2025 inlap)
      "55.120 sec"        → 55.120  (race2025 partial-lap shortform)
      "16:34.920"         → 994.920 (race2025 box-stop)
      "121.540"           → 121.540 (defensive plain-seconds)
    """
    s = text.strip().rstrip(",")
    if not s:
        return None
    # MM:SS.mmm
    m = re.match(r"^(\d+):(\d+)\.(\d+)$", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 1000.0
    # "SS.mmm sec" oder "SS.mmm s"
    m = re.match(r"^(\d+)\.(\d+)\s*(?:sec|s)$", s, re.IGNORECASE)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 1000.0
    # Pure seconds float
    m = re.match(r"^(\d+(?:\.\d+)?)$", s)
    if m:
        return float(m.group(1))
    return None


def _parse_laptimes(hed_section: Dict[str, str]) -> List[float]:
    """Parse the [LAPTIMES]/[Laptimes] section into a list of lap durations
    in seconds.

    Format (bmw_hp):
        Fastest lap=2:01.540
        0=2:58.840
        1=2:04.460
        ...

    Format (race2025) — exakt dieselbe Struktur, nur mit Klein-Schreibung
    der Sektion und gelegentlich "0:55.120" / "55.120 sec" für unvollständige
    Laps am Ende.

    Numeric keys (0, 1, 2, ...) are the actual lap durations in order.
    """
    laps: List[Tuple[int, float]] = []
    for k, v in hed_section.items():
        if not k.isdigit():
            continue
        dur = _parse_lap_duration(v)
        if dur is None:
            continue
        laps.append((int(k), dur))
    laps.sort(key=lambda t: t[0])
    return [t[1] for t in laps]


# ---------------------------------------------------------------------------
# Channel descriptor extraction
# ---------------------------------------------------------------------------

class ChannelDef:
    """One channel descriptor parsed from DDD.

    `rate_hz` is the canonical native sample rate in Hertz (set per variant
    by _parse_channel_def). `rate_div` is the legacy bmw_hp divisor against
    100 Hz; kept for repr/back-compat but the loader uses rate_hz.
    """
    __slots__ = ("sec_id", "name", "unit", "file_ext", "fmt_code",
                 "rate_div", "rate_hz", "word_bytes", "scale", "offset",
                 "mask", "is_raw")

    def __init__(self, sec_id: str, name: str, unit: str, file_ext: str,
                 fmt_code: str, rate_div: int, rate_hz: float, word_bytes: int,
                 scale: float, offset: float, mask: int, is_raw: bool):
        self.sec_id = sec_id
        self.name = name
        self.unit = unit
        self.file_ext = file_ext
        self.fmt_code = fmt_code
        self.rate_div = rate_div
        self.rate_hz = rate_hz
        self.word_bytes = word_bytes
        self.scale = scale
        self.offset = offset
        self.mask = mask
        self.is_raw = is_raw

    def __repr__(self):
        return (f"<Channel {self.name!r} ext={self.file_ext} "
                f"fmt={self.fmt_code} bytes={self.word_bytes} "
                f"rate={self.rate_hz:.1f}Hz raw={self.is_raw}>")


# Format-Codes pro Variante. bmw_hp benutzt 1/4/101/104 (+10001/10004 für ältere
# Hardware), race2025 benutzt 2/102. Alle anderen Codes überspringen wir.
_FMT_RAW_BMW = {"1", "4", "10001", "10004"}
_FMT_COMP_BMW = {"101", "104"}
_FMT_RAW_R25 = {"2"}
_FMT_COMP_R25 = {"102"}


def _parse_channel_def(sec_id: str, section: Dict[str, str],
                       variant: str,
                       main_rate_hz: float = 100.0) -> Optional[ChannelDef]:
    """Build a ChannelDef from a single [3xx] section of the DDD INI.

    Variant-spezifische Interpretation:

      bmw_hp:   line1[4] = rate-divisor (HEX) der HED-MainSamplingRate.
                Beispiele bei MainSamplingRate=400:
                  "4"  → 0x4  =  4 → 100 Hz
                  "8"  → 0x8  =  8 →  50 Hz
                  "28" → 0x28 = 40 →  10 Hz
                Bei MainSamplingRate=100 (älteres Hardware-Modell) sind die
                Werte typischerweise "1"/"2"/"4"/"8", wo dec==hex ist, deshalb
                fiel das früher nicht auf. Source: HED [DOWNLOAD]/MainSamplingRate.
                line1[0] = 1/4/101/104/10001/10004
      race2025: line1[4] = Sample-Periode in MILLISEKUNDEN (hex)
                          → rate_hz = 1000.0 / period_ms
                line1[0] = 2 (analog) oder 102 (computed)
    """
    line1 = section.get("1", "").split(",")
    line3 = section.get("3", "").split(",")
    line4 = section.get("4", "").split(",")
    line6 = section.get("6", "").split(",")
    if len(line1) < 6 or len(line4) < 2 or len(line6) < 4:
        return None
    fmt_code = line1[0].strip()
    # word-bits is field 6 (index 5), hex string. 10=16, 20=32, 40=64.
    bits_hex = line1[5].strip()
    if bits_hex not in _BITS_TO_BYTES:
        return None
    word_bytes = _BITS_TO_BYTES[bits_hex]

    # Rate-Code: in bmw_hp ein Hex-Teiler der HED-MainSamplingRate
    # (default 100 Hz für ältere Bundles); in race2025 eine Periode in ms (hex).
    # Beide Dialekte sehen verschiedene Werte, also entscheidet `variant` allein.
    rate_str = line1[4].strip() if len(line1) > 4 else ""
    if variant == "race2025":
        try:
            period_ms = int(rate_str, 16) if rate_str else 10
        except ValueError:
            period_ms = 10
        if period_ms <= 0:
            period_ms = 10
        rate_hz = 1000.0 / period_ms
        rate_div = max(1, int(round(100.0 / rate_hz))) if rate_hz <= 100 else 1
    else:
        try:
            rate_div = int(rate_str, 16) if rate_str else 1
        except ValueError:
            rate_div = 1
        if rate_div <= 0:
            rate_div = 1
        rate_hz = main_rate_hz / rate_div

    name = line4[0].strip()
    unit = line4[1].strip() if len(line4) > 1 else ""
    # File extension is field 4 (index 3) of line 6. bmw_hp schreibt ".A01",
    # race2025 schreibt "A01" (ohne führenden Punkt).
    file_ext = line6[3].strip().lstrip(".")
    if not file_ext:
        return None

    # Skalierung. Bei race2025 fast immer scale=1/offset=0, aber wir lesen
    # die Werte trotzdem und der Loader entscheidet (per word_bytes) wann
    # er sie anwendet.
    scale = 1.0
    offset = 0.0
    mask = 0xFFFFFFFF
    if len(line3) >= 9:
        try:
            scale = _hex32_to_float(line3[3]) if line3[3] else 1.0
            offset = _hex32_to_float(line3[4]) if line3[4] else 0.0
            mask = int(line3[8], 16) if line3[8] else 0xFFFFFFFF
        except ValueError:
            pass
        # Some channels use scale=0 (meaning unused / pass-through).
        if scale == 0.0:
            scale = 1.0

    # Format-Code-Whitelist: alles ausserhalb der bekannten Codes verwerfen.
    if variant == "race2025":
        if fmt_code not in (_FMT_RAW_R25 | _FMT_COMP_R25):
            return None
        is_raw = fmt_code in _FMT_RAW_R25
    else:
        if fmt_code not in (_FMT_RAW_BMW | _FMT_COMP_BMW):
            return None
        is_raw = fmt_code in _FMT_RAW_BMW

    return ChannelDef(sec_id=sec_id, name=name, unit=unit, file_ext=file_ext,
                      fmt_code=fmt_code, rate_div=rate_div, rate_hz=rate_hz,
                      word_bytes=word_bytes, scale=scale, offset=offset,
                      mask=mask, is_raw=is_raw)


# ---------------------------------------------------------------------------
# Raw data loading
# ---------------------------------------------------------------------------

def _load_channel(bundle_dir: Path, bundle_stem: str, ch: ChannelDef) -> Optional[np.ndarray]:
    """Read a single channel's data file and apply scaling. Returns float64.

    Returns None if the file doesn't exist or the byte count doesn't divide
    by the expected word size (corrupt / partial).

    v21.30: the scaling formula is applied based on WORD SIZE, not format code.
    16-bit channels (word_bytes=2) are always raw ints needing scale+offset,
    regardless of whether the fmt code is RAW (1, 4, 10001, 10004) or
    COMPUTED (101, 104) — many "computed" channels like V_GPS still store
    the value as int16/100 (km/h) and provide the scale=0.01 in DDD line 3.
    32-bit and 64-bit channels are interpreted as IEEE-754 floats and the
    DDD scale/offset is only applied if non-trivial (rare for floats).
    """
    fname = bundle_dir / f"{bundle_stem}.{ch.file_ext}"
    if not fname.is_file():
        return None
    raw = fname.read_bytes()
    if len(raw) == 0 or len(raw) % ch.word_bytes != 0:
        return None

    n_samples = len(raw) // ch.word_bytes
    if ch.word_bytes == 2:
        # 16-bit ints. Always apply scale+offset+mask.
        arr_i = np.frombuffer(raw, dtype="<u2").astype(np.int64)
        if ch.mask and ch.mask != 0xFFFFFFFF:
            arr_i = arr_i & ch.mask
        out = arr_i.astype(np.float64) * ch.scale + ch.offset
        return out
    elif ch.word_bytes == 4:
        # 32-bit values. Interpret as float32 — but if the channel declared
        # a non-trivial scale (rare; some "computed" channels still want it),
        # apply it as well.
        arr_f = np.frombuffer(raw, dtype="<f4").astype(np.float64)
        if abs(ch.scale - 1.0) > 1e-9 or abs(ch.offset) > 1e-9:
            arr_f = arr_f * ch.scale + ch.offset
        return arr_f
    elif ch.word_bytes == 8:
        # 64-bit (GPS doubles, Laptrigger). Always raw float64 — the GPS
        # channels declare scale=1, offset=0 anyway.
        arr_f = np.frombuffer(raw, dtype="<f8").astype(np.float64)
        if abs(ch.scale - 1.0) > 1e-9 or abs(ch.offset) > 1e-9:
            arr_f = arr_f * ch.scale + ch.offset
        return arr_f
    else:
        return None


# ---------------------------------------------------------------------------
# Bundle discovery
# ---------------------------------------------------------------------------

def _detect_variant(root: Path, mes_dir: Path) -> str:
    """Decide which 2D dialect this bundle is.

    Diskriminator: ein EVENT.INI im Wrapper-Verzeichnis (eine Ebene über
    der .MES) ist der eindeutige Race2025-Marker. Die alten BMW-HP-Bundles
    haben keine EVENT.INI; deren ZIP enthält .MES direkt im Root.

    `root` = top-level (was im ZIP entpackt wurde / das Verzeichnis das
             der User reingereicht hat)
    `mes_dir` = das gefundene .MES-Verzeichnis selbst
    """
    # 1) EVENT.INI im Wrapper-Verzeichnis ist Race2025-Marker.
    #    .MES liegt typischerweise in <root>/<wrapper>/<bundle>.MES; suche
    #    die EVENT.INI parallel zur .MES-Direktory (case-insensitiv).
    wrapper = mes_dir.parent
    for cand in (wrapper, root):
        try:
            for entry in cand.iterdir():
                if entry.is_file() and entry.name.lower() == "event.ini":
                    return "race2025"
        except (OSError, FileNotFoundError):
            continue
    # 2) Sonst: klassisches BMW-HP-Bundle.
    return "bmw_hp"


def _find_bundle_in_dir(d: Path) -> Optional[Tuple[Path, str, str, Path]]:
    """Return (mes_dir, stem, variant, top_root) for the .MES directory.

    Sucht rekursiv bis zu zwei Ebenen tief, da Race2025-ZIPs ein
    Wrapper-Verzeichnis um die .MES legen. Erkennt sowohl `*.HED`
    (BMW HP) als auch `*.hed` (Race2025).

    Der Bundle-"stem" ist der Dateiname ohne .HED/.hed-Endung und dient
    als Präfix aller per-Channel-Datendateien im selben Verzeichnis.

    `top_root` ist das Wurzelverzeichnis (für Race2025: dort liegen
    EVENT.INI/<track>.line, die wir später noch lesen wollen).
    """
    if not d.is_dir():
        return None

    # Sammle alle möglichen .MES-Verzeichnisse bis Tiefe 2.
    candidates: List[Tuple[Path, str]] = []
    seen: set = set()

    def _scan(parent: Path, depth: int):
        if depth > 2:
            return
        try:
            entries = list(parent.iterdir())
        except (OSError, PermissionError):
            return
        # Erst .HED-Dateien im aktuellen Verzeichnis suchen.
        for entry in entries:
            if not entry.is_file():
                continue
            ext = entry.suffix.lower()
            if ext == ".hed":
                key = (parent.resolve(), entry.stem)
                if key not in seen:
                    seen.add(key)
                    candidates.append((parent, entry.stem))
        # Dann in Unterverzeichnisse absteigen.
        for entry in entries:
            if entry.is_dir():
                _scan(entry, depth + 1)

    _scan(d, 0)
    if not candidates:
        return None

    # Bevorzuge den längsten Stem (deskriptivster Bundle-Name) und das
    # tiefste .MES (falls Wrapper vorhanden).
    candidates.sort(key=lambda t: (-len(t[1]), -len(t[0].parts)))
    mes_dir, stem = candidates[0]
    variant = _detect_variant(d, mes_dir)
    return mes_dir, stem, variant, d


# ---------------------------------------------------------------------------
# Lap-boundary detection
# ---------------------------------------------------------------------------

def _laps_from_hed(lap_durations: List[float], dt: float = 0.01
                   ) -> List[Tuple[int, int, float]]:
    """Convert HED lap durations to (start_idx, end_idx, duration_s) tuples
    on the 100 Hz time axis (dt = 0.01 s).

    The HED [LAPTIMES] section gives clean durations and is the most reliable
    source if available. start_idx of lap N = sum of durations of laps 0..N-1.
    """
    laps = []
    cursor = 0.0
    for dur in lap_durations:
        start_idx = int(round(cursor / dt))
        end_idx   = int(round((cursor + dur) / dt))
        laps.append((start_idx, end_idx, dur))
        cursor += dur
    return laps


def _laps_from_trigger(time_s: np.ndarray, trigger: np.ndarray
                       ) -> List[Tuple[int, int, float]]:
    """Fallback lap detection from a Laptrigger channel. The 2D Laptrigger
    channel is a 0..1 (or similar) signal that pulses at each finish-line
    crossing. We detect rising edges (low → high transitions) and use them
    as lap boundaries.

    Returns [] if fewer than 2 triggers are detected.
    """
    if trigger is None or len(trigger) < 10:
        return []
    # Normalise into 0/1.
    thr = (trigger.max() + trigger.min()) / 2.0 if trigger.max() > trigger.min() else 0.5
    above = trigger > thr
    # Rising edges
    edges = np.where((~above[:-1]) & (above[1:]))[0] + 1
    if len(edges) < 2:
        return []
    laps = []
    for i in range(len(edges) - 1):
        s, e = int(edges[i]), int(edges[i+1])
        if s >= len(time_s) or e >= len(time_s):
            continue
        dur = float(time_s[e] - time_s[s])
        if dur < 5.0 or dur > 600.0:
            continue  # noise / pit stop
        laps.append((s, e, dur))
    return laps


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_2d(filepath: str) -> Dict[str, Any]:
    """Parse a 2D BMW HP Race Datalogger bundle.

    Accepts either:
      • A .zip file containing a .MES directory at the top level
      • A path to a .MES directory directly
      • A path to a directory that contains *.HED + per-channel files

    Returns the standard track dict shape used by the rest of the toolchain:
        {meta, time, lat, lon, speed, channels, all_channels, source_format,
         source_file, finish_line, running_lap_time}
    """
    fp = Path(filepath)
    if not fp.exists():
        raise FileNotFoundError(f"2D bundle not found: {filepath}")

    tmpdir = None
    try:
        if fp.is_file() and fp.suffix.lower() == ".zip":
            tmpdir = Path(tempfile.mkdtemp(prefix="2d_bundle_"))
            with zipfile.ZipFile(fp, "r") as zf:
                zf.extractall(tmpdir)
            bundle = _find_bundle_in_dir(tmpdir)
        elif fp.is_dir():
            bundle = _find_bundle_in_dir(fp)
        else:
            raise ValueError(
                f"2D parser expects a .zip or .MES directory, got: {filepath}"
            )

        if bundle is None:
            raise ValueError(
                f"No 2D bundle (.HED file) found under {filepath}. The .zip "
                "should contain a .MES directory at the top level."
            )
        bundle_dir, stem, variant, top_root = bundle
        return _parse_bundle(bundle_dir, stem, variant, top_root, str(fp))
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _parse_bundle(bundle_dir: Path, stem: str, variant: str, top_root: Path,
                  source_file: str) -> Dict[str, Any]:
    """Core: read HED + DDD, load all channels, build the standard dict.

    `variant` is "bmw_hp" or "race2025" — determines how rate_code and
    fmt_code are interpreted and which fallback channel names apply.
    `top_root` is the directory level where wrapper files (EVENT.INI,
    <track>.line) live in the race2025 layout.
    """
    # HED-Datei case-insensitiv suchen (bmw_hp: .HED, race2025: .hed).
    hed_path = None
    for ext in (".HED", ".hed"):
        p = bundle_dir / f"{stem}{ext}"
        if p.is_file():
            hed_path = p
            break
    if hed_path is None:
        for cand in list(bundle_dir.glob("*.HED")) + list(bundle_dir.glob("*.hed")):
            hed_path = cand
            break
    if hed_path is None:
        raise FileNotFoundError(f"HED missing in {bundle_dir}")

    ddd_path = bundle_dir / f"{stem}.DDD"
    if not ddd_path.is_file():
        # Some bundles only ship the .ldd; that has the same channel defs.
        ddd_path = bundle_dir / f"Data{stem.split('-')[-1][:4]}.ldd"
        if not ddd_path.is_file():
            # Try any .ldd in the directory
            ldds = list(bundle_dir.glob("*.ldd"))
            if not ldds:
                ddd_cands = list(bundle_dir.glob("*.DDD")) + list(bundle_dir.glob("*.ddd"))
                if not ddd_cands:
                    raise FileNotFoundError(
                        f"Neither DDD nor LDD found in {bundle_dir}"
                    )
                ddd_path = ddd_cands[0]
            else:
                ddd_path = ldds[0]

    # --- Meta from HED -----------------------------------------------------
    hed = _parse_ini(hed_path)
    # Sektion-Namen variieren zwischen den Dialekten (LAPTIMES vs. Laptimes
    # etc.). Lookup case-insensitiv.
    def _hed_section(*names):
        lower = {k.lower(): v for k, v in hed.items()}
        for n in names:
            v = lower.get(n.lower())
            if v is not None:
                return v
        return {}

    dl_section   = _hed_section("DOWNLOAD")
    info_section = _hed_section("INFO_2D")
    lap_section  = _hed_section("LAPTIMES", "Laptimes")
    gps_section  = _hed_section("GPS")

    # MainSamplingRate aus HED [DOWNLOAD]. Bei den 2025er BMW-M1000RR-Loggern
    # steht 400; ältere BMW-HP-Logger schreiben den Key entweder nicht oder
    # 100. Fallback auf 100 hält den Code für die alten Mugello/Hockenheim-
    # Bundles bit-identisch (rate_str-Werte 1/2/4/8 sind hex==dec, und
    # 100/divisor war dort schon korrekt).
    main_rate_raw = dl_section.get("MainSamplingRate", "").strip()
    try:
        main_rate_hz = float(main_rate_raw) if main_rate_raw else 100.0
    except ValueError:
        main_rate_hz = 100.0
    if main_rate_hz <= 0:
        main_rate_hz = 100.0

    # VENUE is encoded in the bundle name itself (e.g. "MUGELLO_20230701-..."),
    # or sometimes carried in [INFO_2D] but typically blank.
    venue = ""
    parts = stem.split("_")
    if parts and parts[0]:
        venue = parts[0]

    # DATE/TIME from "Start of download" — DD.MM.YYYY HH:MM:SS
    start_str = dl_section.get("Start of download", "").strip()
    date_str = ""
    if start_str:
        m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})", start_str)
        if m:
            date_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    # --- Race2025: EVENT.INI / <track>.line --------------------------------
    # EVENT.INI liefert:
    #   [SPECIAL CHANNELS]  Alias-Map für Standard-Channelnamen
    #   [MAIN] TRACK=...    saubere Track-Bezeichnung
    #   [MAIN] DATE=...     DD.MM.YYYY
    #   [Track] Name=...    Long-name ("Circuit de la Comunitat Valenciana ...")
    # <track>.line enthält zwei Zeilen mit "lat lon" (Start-Ziel-Linie).
    event_aliases: Dict[str, str] = {}
    finish_line_latlon: Optional[Tuple[float, float]] = None
    track_long_name = ""
    if variant == "race2025":
        for cand in (bundle_dir.parent, top_root):
            if not cand.is_dir():
                continue
            try:
                entries = list(cand.iterdir())
            except OSError:
                continue
            for entry in entries:
                low = entry.name.lower()
                if entry.is_file() and low == "event.ini":
                    try:
                        ev = _parse_ini(entry)
                    except (OSError, UnicodeError):
                        continue
                    ev_lower = {k.lower(): v for k, v in ev.items()}
                    sc = ev_lower.get("special channels", {})
                    event_aliases.update({k.strip(): v.strip() for k, v in sc.items()})
                    main = ev_lower.get("main", {})
                    track_main = main.get("TRACK", "").strip()
                    if track_main:
                        venue = track_main  # "VALENCIA" überschreibt Stem-Default
                    date_main = main.get("DATE", "").strip()
                    if date_main and not date_str:
                        m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})", date_main)
                        if m:
                            date_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                    track_sec = ev_lower.get("track", {})
                    track_long_name = track_sec.get("Name", "").strip()
                elif entry.is_file() and entry.suffix.lower() == ".line":
                    try:
                        raw = entry.read_text(encoding="latin-1").strip().splitlines()
                    except (OSError, UnicodeError):
                        continue
                    if raw:
                        toks = raw[0].split()
                        if len(toks) >= 2:
                            try:
                                finish_line_latlon = (float(toks[0]), float(toks[1]))
                            except ValueError:
                                pass
            if event_aliases or finish_line_latlon:
                break

    lap_durations = _parse_laptimes(lap_section)

    # --- Channel definitions from DDD --------------------------------------
    ddd = _parse_ini(ddd_path)
    channel_defs: List[ChannelDef] = []
    for sec_id, section in ddd.items():
        # Channel sections are 3-digit hex (300, 301, ..., 34F).
        if not re.match(r"^[0-9A-F]{3}$", sec_id):
            continue
        cdef = _parse_channel_def(sec_id, section, variant, main_rate_hz)
        if cdef is not None:
            channel_defs.append(cdef)

    if not channel_defs:
        raise ValueError(
            f"No valid channel definitions in {ddd_path} — file may be "
            "corrupt or a different 2D-format variant."
        )

    # --- Load channels -----------------------------------------------------
    # First pass: load each channel's raw array (at its native rate).
    raw_channels: Dict[str, Tuple[ChannelDef, np.ndarray]] = {}
    for cdef in channel_defs:
        arr = _load_channel(bundle_dir, stem, cdef)
        if arr is None or len(arr) == 0:
            continue
        # Disambiguate name collisions (e.g. two "Gear" channels — analog and
        # computed). Suffix with the channel-section id.
        key = cdef.name if cdef.name not in raw_channels else f"{cdef.name}_{cdef.sec_id}"
        raw_channels[key] = (cdef, arr)

    if not raw_channels:
        raise ValueError(
            f"Channel definitions found but no data files readable in "
            f"{bundle_dir}. Bundle may be empty or partially uploaded."
        )

    # --- Determine base sample count and time axis -------------------------
    # Standard-Ausgabe ist 100 Hz für beide Dialekte. Bei bmw_hp ist 100 Hz
    # die native Maximalrate; bei race2025 gibt es Channels bis 250 Hz, die
    # auf 100 Hz herunter-interpoliert werden (für die Compare-Pipeline
    # ausreichend; Coach/Reports verarbeiten 100 Hz problemlos).
    base_rate_hz = 100.0
    dt = 1.0 / base_rate_hz

    # Ermittle die Race-Dauer in Sekunden. Vorgehen pro Variante:
    #   bmw_hp:   Channels mit rate_hz == 100 Hz geben unmittelbar Sample-
    #             Count = Dauer × 100.
    #   race2025: einer der 100-Hz-Channels (z.B. RPM) liefert dasselbe;
    #             als Fallback nehmen wir aus jedem Channel `len(arr) /
    #             native_hz` und mitteln.
    durations: List[float] = []
    for cdef, arr in raw_channels.values():
        if cdef.rate_hz > 0:
            durations.append(len(arr) / cdef.rate_hz)
    if not durations:
        # extrem unwahrscheinlich, aber Fallback: längstes Array bei 100Hz
        durations.append(max(len(arr) for _, arr in raw_channels.values()) / 100.0)
    duration_s = float(np.median(durations))
    base_count = int(round(duration_s * base_rate_hz))
    time_s = np.arange(base_count, dtype=np.float64) * dt

    # --- Resample each channel to 100 Hz -----------------------------------
    # Channels mit rate_hz == 100 (bmw_hp meist, race2025 ~ Mehrheit) sind
    # bereits aligned. Andere Raten werden via np.interp angepasst (linear).
    # Das funktioniert sowohl für Up- als auch für Downsampling und ist im
    # Gegensatz zu einfachem Stride-Slicing robust gegenüber Off-by-One bei
    # nicht-ganzzahligen Verhältnissen (z.B. 12.5 Hz bei bmw_hp GPS).
    upsampled: Dict[str, Tuple[ChannelDef, np.ndarray]] = {}
    for key, (cdef, arr) in raw_channels.items():
        if cdef.rate_hz == base_rate_hz and len(arr) == base_count:
            upsampled[key] = (cdef, arr)
            continue
        native_dt = 1.0 / cdef.rate_hz
        native_t = np.arange(len(arr), dtype=np.float64) * native_dt
        if len(arr) == base_count and abs(cdef.rate_hz - base_rate_hz) < 1e-6:
            upsampled[key] = (cdef, arr)
            continue
        # np.interp clamps outside-of-range to nearest valid sample.
        interp = np.interp(time_s, native_t, arr)
        upsampled[key] = (cdef, interp)

    # --- Channel-Suche-Helper (mit race2025 [SPECIAL CHANNELS]-Aliases) ----
    def _ch(*names: str) -> Optional[np.ndarray]:
        """Suche nach erstem existierenden Channel; case-insensitiv und
        zusätzlich über die race2025 [SPECIAL CHANNELS]-Aliase."""
        # Direkt-Hits zuerst (Reihenfolge zählt: erste Übereinstimmung gewinnt)
        for n in names:
            if n in upsampled:
                return upsampled[n][1]
        # Über Aliase
        for n in names:
            actual = event_aliases.get(n)
            if actual and actual in upsampled:
                return upsampled[actual][1]
        # Case-insensitiv (letzter Versuch — manche Channels haben Tippfehler)
        lower_map = {k.lower(): k for k in upsampled}
        for n in names:
            real = lower_map.get(n.lower())
            if real:
                return upsampled[real][1]
        return None

    # --- Extract top-level fields (lat/lon/speed) --------------------------
    # Fallback-Reihenfolge umfasst beide Dialekte; das erste Match gewinnt.
    lat = _ch("Latitude", "GPS_Latitude", "Lat_dez")
    lon = _ch("Longitude", "GPS_Longitude", "Lon_dez")
    speed = _ch("Speed", "GPS_Speed_over_", "V_GPS", "V_Rear", "V_Front")

    if lat is None or lon is None:
        raise ValueError(
            "2D bundle is missing GPS channels (Latitude/GPS_Latitude/Lat_dez "
            "or Longitude/GPS_Longitude/Lon_dez). Cannot build lap analysis "
            "without coordinate data."
        )
    if speed is None:
        # Synthesize from GPS if Speed wasn't logged for some reason.
        speed = np.zeros_like(lat)

    # v21.30 — GPS outlier filter. The 2D GPS channel occasionally emits
    # garbage spikes (huge lat/lon jumps to nonsense values) during fix
    # acquisition or signal loss. Detect samples that are more than a few
    # km away from the local median and patch them via linear interpolation.
    # Race2025 GPS-Float32 hat dazu noch genau-0.0-Samples vor dem Fix; die
    # sind in den meisten Tracks ebenfalls "garbage" und werden mitgefiltert.
    lat = lat.copy()
    lon = lon.copy()
    # Compute the "race location" from the densest cluster (last 10% — by
    # then the GPS should be locked).
    tail_n = max(100, len(lat) // 10)
    ref_lat = float(np.median(lat[-tail_n:]))
    ref_lon = float(np.median(lon[-tail_n:]))
    # 1 deg lat ≈ 111 km. A race track fits in ~10 km, so anything >0.5 deg
    # away from the reference is definitely garbage. Exakt-0.0-Samples (vor
    # Fix-Acquisition bei race2025) werden ebenfalls als bad markiert.
    bad = (np.abs(lat - ref_lat) > 0.5) | (np.abs(lon - ref_lon) > 0.5) \
          | ((lat == 0.0) & (lon == 0.0))
    if bad.any() and (~bad).any():
        # Linear interpolation over bad spans; if first/last sample is bad,
        # np.interp clamps to nearest good value.
        good_idx = np.where(~bad)[0]
        x_all = np.arange(len(lat))
        lat = np.interp(x_all, good_idx, lat[good_idx])
        lon = np.interp(x_all, good_idx, lon[good_idx])

    # --- Channels dict (everything else, including duplicates of top-level) -
    channels: Dict[str, Dict[str, Any]] = {}
    for key, (cdef, arr) in upsampled.items():
        # "rate" ist die NATIVE Sample-Rate des Channels (zur Info / fürs UI).
        # Die Daten selbst sind auf 100 Hz resampled, aber das UI zeigt ggf.
        # die ursprüngliche Auflösung an (z.B. 12.5 Hz für GPS bei bmw_hp,
        # 250 Hz für Suspension bei race2025).
        rate = int(round(cdef.rate_hz))
        channels[key] = {
            "time": time_s.copy(),
            "data": arr,
            "rate": rate,
            "unit": cdef.unit,
        }

    # --- Lap detection -----------------------------------------------------
    # 2D HED carries clean lap timings; convert them into the format that
    # laps.detect_laps() consumes directly (strategy 0: pre-computed). When
    # HED has no LAPTIMES, fall back to the Laptrigger channel via auto-
    # detection through detect_laps' strategies 1-3.
    lap_times: List[Tuple[float, float]] = []
    if lap_durations:
        # HED's [LAPTIMES] also reports the fastest lap explicitly. Use that
        # as an anchor: any lap shorter than 95% of the declared fastest is
        # definitely a partial lap (out- or in-lap), and anything > 3× longer
        # is a box-stop lap. Without an anchor, fall back to median-based
        # heuristics.
        fastest_str = lap_section.get("Fastest lap", "").strip()
        anchor_sec = _parse_lap_duration(fastest_str)
        if anchor_sec is not None and anchor_sec > 0:
            min_real = anchor_sec * 0.95
            max_real = anchor_sec * 4.0   # box-stop can be ~3× normal
        elif len(lap_durations) >= 3:
            sorted_dur = sorted(lap_durations)
            mid = sorted_dur[len(sorted_dur)//4 : 3*len(sorted_dur)//4 + 1]
            median = mid[len(mid)//2] if mid else lap_durations[0]
            min_real = max(30.0, median * 0.5)
            max_real = max(600.0, median * 3.0)
        else:
            min_real, max_real = 30.0, 600.0

        cursor = 0.0
        for i, dur in enumerate(lap_durations):
            if min_real <= dur <= max_real:
                lap_times.append((cursor, dur))
            cursor += dur
    else:
        # Fallback: derive lap boundaries from a trigger-like channel.
        #
        #   bmw_hp:   "Laptrigger" pulses zwischen 0 und 1 bei jedem Finish-
        #             Line-Überflug (rising-edge-Detection).
        #   race2025: kein expliziter Laptrigger, aber "Laps" zählt ganzzahlig
        #             hoch und "LapMeter" resettet sich pro Runde. Wir nutzen
        #             beide: rising edges in "Laps" sind Lap-Anfänge.
        trigger = None
        for key in ("Laptrigger", "Laptrigger_311", "Laptrigger_33F"):
            if key in upsampled:
                trigger = upsampled[key][1]
                break
        if trigger is None and "Laps" in upsampled:
            laps_counter = upsampled["Laps"][1]
            # Rising edges des integer-Zählers; np.diff > 0.5 reicht (Zähler
            # springt um genau 1).
            trigger = np.diff(laps_counter, prepend=laps_counter[0])
        if trigger is not None:
            boundaries = _laps_from_trigger(time_s, trigger)
            for (s, e, dur) in boundaries:
                lap_times.append((float(time_s[s]), float(dur)))

    # --- Assemble result ---------------------------------------------------
    # --- Assemble result ---------------------------------------------------
    vehicle = "BMW HP" if variant == "bmw_hp" else ""
    out = {
        "meta": {
            "DATE": date_str,
            "VENUE": venue,
            "TRACK": track_long_name or venue,
            "RACER": info_section.get("Computer user", "").strip() or "",
            "VEHICLE": vehicle,
            "SOURCE": "2D",
            "VARIANT": variant,
            "LAPMETER_M": dl_section.get("LapMeter [m]", "").strip(),
            "LOGGER": dl_section.get("Loggername", "").strip(),
            "FASTEST_LAP": lap_section.get("Fastest lap", "").strip(),
            "LAP_COUNT": len(lap_times),
        },
        "time": time_s,
        "lat": lat,
        "lon": lon,
        "speed": speed,
        "finish_line": finish_line_latlon,  # (lat, lon) wenn .line vorhanden
        "source_format": "2D",
        "source_file": source_file,
        "running_lap_time": None,
        "channels": channels,
        "all_channels": ["lat", "lon", "speed"] + list(channels.keys()),
        # 2D-specific: pre-detected laps from HED (or Laptrigger fallback).
        # The standard laps.detect_laps() picks this up as strategy 0.
        "lap_times": lap_times,
    }
    return out
