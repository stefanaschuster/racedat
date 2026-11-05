"""Distance-align two lap traces and compute per-segment time delta.

Two laps from the same track might have different start/finish-line positions
(e.g. one logger triggered at S/F line, another at sector marker). To make
a meaningful comparison, we circularly shift lap B's data so that the same
physical track location lines up with lap A's at the same distance value.

Alignment strategy: GPS-position anchor.
  - Take the GPS position at distance=0 of lap A (i.e. lap A's "start").
  - Find the sample in lap B whose GPS position is closest to that point.
  - Rotate lap B's per-sample arrays cyclically so that point becomes
    distance=0 in lap B.

The resulting two laps share the same notion of "kilometre 0", regardless
of where their respective S/F lines actually were.
"""
from typing import Tuple
import numpy as np


def _haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance between (lat1,lon1) and (lat2,lon2) arrays/scalars
    in metres. Inputs in degrees."""
    R = 6371000.0
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def _find_closest_gps_index(lap_b, anchor_lat, anchor_lon) -> Tuple[int, float]:
    """Find the index in lap_b whose GPS position is closest to (anchor_lat,
    anchor_lon). Returns (index, distance_in_metres)."""
    lat = np.asarray(lap_b["lat"], dtype=np.float64)
    lon = np.asarray(lap_b["lon"], dtype=np.float64)
    if len(lat) == 0:
        return 0, float("inf")
    d = _haversine_m(anchor_lat, anchor_lon, lat, lon)
    idx = int(np.argmin(d))
    return idx, float(d[idx])


def _shift_lap_to_index(lap, new_origin_idx: int):
    """Return a copy of `lap` with all per-sample arrays cyclically rotated
    so that `new_origin_idx` becomes the new index 0. Distance and time are
    re-zeroed accordingly."""
    if new_origin_idx <= 0:
        return lap

    distance = np.asarray(lap["distance"], dtype=np.float64)
    time = np.asarray(lap["time"], dtype=np.float64)
    speed = np.asarray(lap["speed"], dtype=np.float64)
    lat = np.asarray(lap["lat"], dtype=np.float64)
    lon = np.asarray(lap["lon"], dtype=np.float64)

    if new_origin_idx >= len(distance):
        return lap

    total_dist = float(lap["total_distance"])
    total_time = float(lap["duration"])

    # Distances: [origin..end] become [0..total - origin_dist],
    # [start..origin-1] become [total - origin_dist .. total]
    origin_dist = distance[new_origin_idx]
    new_distance = np.concatenate([
        distance[new_origin_idx:] - origin_dist,
        distance[:new_origin_idx] + (total_dist - origin_dist),
    ])

    # Time: same idea, so it stays cumulative within the (rotated) lap
    origin_time = time[new_origin_idx]
    new_time = np.concatenate([
        time[new_origin_idx:] - origin_time,
        time[:new_origin_idx] + (total_time - (origin_time - time[0])),
    ])

    new_speed = np.concatenate([speed[new_origin_idx:], speed[:new_origin_idx]])
    new_lat = np.concatenate([lat[new_origin_idx:], lat[:new_origin_idx]])
    new_lon = np.concatenate([lon[new_origin_idx:], lon[:new_origin_idx]])

    return {
        **lap,
        "distance": new_distance,
        "time": new_time,
        "speed": new_speed,
        "lat": new_lat,
        "lon": new_lon,
    }


def align_laps(lap_a, lap_b, n_samples=500, *, gps_anchor=True,
               anchor_warn_threshold_m: float = 50.0):
    """Resample both laps onto a common distance grid (0 .. min total distance).

    If `gps_anchor=True` (default), lap B is first rotated so that its
    GPS-closest point to lap A's start becomes its new origin. This corrects
    for different S/F line positions across loggers.

    Returns a dict with parallel arrays, the per-window time-loss rate, and
    diagnostic info about the alignment.
    delta = b_time - a_time, so positive means lap B is slower at that point.
    """
    alignment_info = {
        "gps_anchor_used": False,
        "shift_index": 0,
        "shift_distance_m": 0.0,
        "anchor_match_distance_m": 0.0,
        "anchor_warning": None,
    }

    if gps_anchor and len(lap_a["lat"]) > 0 and len(lap_b["lat"]) > 0:
        anchor_lat = float(lap_a["lat"][0])
        anchor_lon = float(lap_a["lon"][0])
        idx, match_dist = _find_closest_gps_index(lap_b, anchor_lat, anchor_lon)
        alignment_info["gps_anchor_used"] = True
        alignment_info["shift_index"] = idx
        alignment_info["anchor_match_distance_m"] = match_dist
        if idx > 0:
            alignment_info["shift_distance_m"] = float(lap_b["distance"][idx])
            lap_b = _shift_lap_to_index(lap_b, idx)
        if match_dist > anchor_warn_threshold_m:
            alignment_info["anchor_warning"] = (
                f"GPS anchor match is {match_dist:.0f}m away — laps may be from "
                f"different tracks or have very different paths."
            )

    # Use lap A's full distance as the reference axis. Lap B's data is
    # interpolated such that its 0..b_total range maps to 0..a_total — i.e.
    # we stretch B's distance proportionally. After GPS-anchor both laps
    # start at the same physical point and end at the same physical point
    # (it's a closed circuit), so this stretch is well-defined and small
    # (typically a few metres of GPS noise).
    #
    # Important consequences:
    #   - the delta curve at distance=a_total equals b.duration - a.duration
    #     (the total lap delta the user sees in the header)
    #   - the track map covers the full circuit (no clipping)
    a_total = float(lap_a["total_distance"])
    b_total = float(lap_b["total_distance"])
    if a_total <= 0 or b_total <= 0:
        raise ValueError("Cannot align: one lap has zero distance")

    distance = np.linspace(0, a_total, n_samples)
    # b's effective distance for the same chart position
    b_scaled_distance = distance * (b_total / a_total)

    a_time = np.interp(distance, lap_a["distance"], lap_a["time"])
    b_time = np.interp(b_scaled_distance, lap_b["distance"], lap_b["time"])
    a_speed = np.interp(distance, lap_a["distance"], lap_a["speed"])
    b_speed = np.interp(b_scaled_distance, lap_b["distance"], lap_b["speed"])
    a_lat = np.interp(distance, lap_a["distance"], lap_a["lat"])
    a_lon = np.interp(distance, lap_a["distance"], lap_a["lon"])
    b_lat = np.interp(b_scaled_distance, lap_b["distance"], lap_b["lat"])
    b_lon = np.interp(b_scaled_distance, lap_b["distance"], lap_b["lon"])

    delta = b_time - a_time

    win = max(1, n_samples // 20)
    gain_window = np.zeros(n_samples)
    gain_window[win:] = delta[win:] - delta[:-win]

    # v21.19 — Extras (Telemetrie-Zusatzkanäle) für den Multi-Channel-Chart.
    # Beide Runden werden auf die gemeinsame Distanz-Achse interpoliert.
    # A → distance (lap_a's eigene Distanz), B → b_scaled_distance (gestreckt
    # damit Lap-B-Distanz zur Lap-A-Distanz passt).
    def _bake_extras(lap, ref_dist_array, target_x):
        out = []
        for key, ch in (lap.get("extra_channels") or {}).items():
            try:
                raw = np.asarray(ch["data"], dtype=np.float64)
            except Exception:
                continue
            if len(raw) == 0:
                continue
            # Source x-axis: the channel might live on the canonical lap
            # time/distance grid (same length as ref_dist_array) — then we
            # interp by distance. Otherwise we treat it as evenly spaced
            # over the lap duration (index-based interp).
            if len(raw) == len(ref_dist_array):
                src_x = ref_dist_array
                dst_x = target_x
            else:
                src_x = np.linspace(0.0, 1.0, len(raw))
                dst_x = np.linspace(0.0, 1.0, n_samples)
            try:
                arr = np.interp(dst_x, src_x, raw)
            except Exception:
                continue
            finite = arr[np.isfinite(arr)]
            if len(finite) == 0:
                continue
            out.append({
                "id":   key,
                "name": ch.get("name") or key,
                "unit": ch.get("unit") or "",
                "min":  float(finite.min()),
                "max":  float(finite.max()),
                "mean": float(finite.mean()),
                "data": arr.round(3).tolist(),
            })
        return out

    a_extras = _bake_extras(lap_a, np.asarray(lap_a["distance"], dtype=np.float64), distance)
    b_extras = _bake_extras(lap_b, np.asarray(lap_b["distance"], dtype=np.float64), b_scaled_distance)

    return {
        "distance": distance,
        "a_time": a_time,
        "b_time": b_time,
        "a_speed": a_speed,
        "b_speed": b_speed,
        "a_lat": a_lat,
        "a_lon": a_lon,
        "b_lat": b_lat,
        "b_lon": b_lon,
        "delta": delta,
        "gain_window": gain_window,
        "window_distance_m": float(a_total / n_samples * win),
        "lap_distance_m": float(a_total),  # = chart x-axis max = finish-line position
        "alignment": alignment_info,
        "a_extras": a_extras,
        "b_extras": b_extras,
    }


def segment_track(aligned, *, smooth_m: float = 25.0,
                  min_corner_m: float = 25.0,
                  min_straight_m: float = 60.0):
    """v23.15 — Strecke in Kurven und Geraden zerlegen, anhand des
    Geschwindigkeitsprofils (Mittel beider Runden, damit die Segmentierung
    für A und B identisch ist).

    Verfahren:
      1. Speed glätten (Moving Average über ~smooth_m Meter).
      2. Adaptive Schwelle = Mitte zwischen 15.- und 85.-Perzentil.
         Darunter = Kurve, darüber = Gerade. Perzentile statt Min/Max,
         damit einzelne Ausreißer die Schwelle nicht verschieben.
      3. Mini-Segmente (< min_corner_m bzw. < min_straight_m) in den
         Nachbarn mergen — filtert Messrauschen und macht aus
         Schikanen mit Mini-Zwischenstück EINE Kurve.

    Returns: Liste von {"i0", "i1", "kind": "kurve"|"gerade", "label"},
    lückenlos von Index 0 bis n-1. Raises ValueError wenn das Profil zu
    flach für eine sinnvolle Trennung ist (Caller fällt dann auf gleich
    lange Sektoren zurück).
    """
    d = np.asarray(aligned["distance"], dtype=np.float64)
    sa = np.asarray(aligned["a_speed"], dtype=np.float64)
    sb = np.asarray(aligned["b_speed"], dtype=np.float64)
    n = len(d)
    if n < 20:
        raise ValueError("Zu wenige Samples für Segmentierung")
    s = (sa + sb) / 2.0

    step = float(d[-1] - d[0]) / max(1, n - 1)
    win = max(1, int(round(smooth_m / max(step, 1e-9))))
    if win > 1:
        kernel = np.ones(win) / win
        s = np.convolve(s, kernel, mode="same")

    p15, p85 = np.percentile(s, 15), np.percentile(s, 85)
    if (p85 - p15) < 10.0:  # km/h — praktisch konstantes Profil
        raise ValueError("Speed-Profil zu flach für Kurven/Geraden-Trennung")
    thr = (p15 + p85) / 2.0
    corner = s < thr

    # Zusammenhängende Regionen extrahieren: [i0, i1, is_corner]
    segs = []
    start = 0
    for i in range(1, n):
        if corner[i] != corner[i - 1]:
            segs.append([start, i, bool(corner[start])])
            start = i
    segs.append([start, n - 1, bool(corner[start])])

    def _len_m(sg):
        return float(d[sg[1]] - d[sg[0]])

    # Mini-Segmente absorbieren, dann gleichartige Nachbarn verschmelzen.
    # Iterativ bis stabil — terminiert, weil jede Runde die Anzahl senkt.
    min_len = {True: min_corner_m, False: min_straight_m}
    while True:
        if len(segs) <= 1:
            break
        # kleinstes zu kurzes Segment suchen
        idx = None
        for i, sg in enumerate(segs):
            if _len_m(sg) < min_len[sg[2]]:
                if idx is None or _len_m(sg) < _len_m(segs[idx]):
                    idx = i
        if idx is None:
            break
        sg = segs.pop(idx)
        # In den längeren angrenzenden Nachbarn kippen
        left = segs[idx - 1] if idx - 1 >= 0 else None
        right = segs[idx] if idx < len(segs) else None
        target = left if (right is None or
                          (left is not None and _len_m(left) >= _len_m(right))
                          ) else right
        if target is left:
            left[1] = sg[1]
        else:
            right[0] = sg[0]
        # Gleichartige Nachbarn verschmelzen
        merged = [segs[0]]
        for nxt in segs[1:]:
            if nxt[2] == merged[-1][2]:
                merged[-1][1] = nxt[1]
            else:
                merged.append(nxt)
        segs = merged

    if len(segs) < 2:
        raise ValueError("Segmentierung ergab weniger als 2 Abschnitte")

    # Labels: K1..Kn / G1..Gn in Streckenreihenfolge
    out = []
    k_count = g_count = 0
    for sg in segs:
        if sg[2]:
            k_count += 1
            label = f"K{k_count}"
            kind = "kurve"
        else:
            g_count += 1
            label = f"G{g_count}"
            kind = "gerade"
        out.append({"i0": int(sg[0]), "i1": int(sg[1]),
                    "kind": kind, "label": label})
    return out


def theoretical_best(aligned, n_sectors: int = 3, segments=None):
    """v23.14/v23.15 — Theoretical Best: Strecke in Abschnitte teilen, pro
    Abschnitt die schnellere der beiden Runden nehmen und die Bestzeiten
    aufsummieren ("theo. best lap").

    v23.15: `segments` kommt bevorzugt aus segment_track() (Kurven und
    Geraden statt starrer Distanz-Drittel) — dann tragen die Abschnitte
    Labels wie K1/G1 und einen "kind". Ohne segments (oder als Fallback,
    wenn die Segmentierung an flachen Daten scheitert): n gleich lange
    Distanz-Sektoren wie bisher.

    Arbeitet auf den distance-aligned Zeit-Arrays aus align_laps() —
    Abschnittszeit = time[Ende] - time[Anfang]. Da beide Runden auf
    derselben Distanz-Achse liegen, sind die Abschnitte physisch
    identische Streckenteile.
    """
    d = np.asarray(aligned["distance"], dtype=np.float64)
    at = np.asarray(aligned["a_time"], dtype=np.float64)
    bt = np.asarray(aligned["b_time"], dtype=np.float64)
    n = len(d)

    if segments is None:
        if n < n_sectors + 1:
            raise ValueError("Zu wenige Samples für Sektor-Aufteilung")
        bounds = [round(k * (n - 1) / n_sectors)
                  for k in range(n_sectors + 1)]
        segments = [{"i0": bounds[k], "i1": bounds[k + 1],
                     "kind": "sektor", "label": f"S{k + 1}"}
                    for k in range(n_sectors)]

    sectors = []
    theo = 0.0
    for k, seg in enumerate(segments):
        i0, i1 = int(seg["i0"]), int(seg["i1"])
        a_s = float(at[i1] - at[i0])
        b_s = float(bt[i1] - bt[i0])
        best = "a" if a_s <= b_s else "b"
        theo += min(a_s, b_s)
        sectors.append({
            "sector": k + 1,
            "label": seg.get("label") or f"S{k + 1}",
            "kind": seg.get("kind") or "sektor",
            "start_m": float(d[i0]),
            "end_m": float(d[i1]),
            "a_s": a_s,
            "b_s": b_s,
            "best": best,
        })
    a_total = float(at[-1] - at[0])
    b_total = float(bt[-1] - bt[0])
    best_lap = "a" if a_total <= b_total else "b"
    return {
        "n_sectors": len(sectors),
        "sectors": sectors,
        "a_total_s": a_total,
        "b_total_s": b_total,
        "theoretical_s": theo,
        "best_lap": best_lap,
        "vs_best_s": theo - min(a_total, b_total),
    }


def hot_zones(aligned):
    """Find the largest single-window time loss and gain."""
    g = aligned["gain_window"]
    d = aligned["distance"]
    worst_i = int(np.argmax(g))
    best_i = int(np.argmin(g))
    return {
        "max_loss": {
            "distance_m": float(d[worst_i]),
            "value_s": float(g[worst_i]),
            "a_speed": float(aligned["a_speed"][worst_i]),
            "b_speed": float(aligned["b_speed"][worst_i]),
            "index": worst_i,
        },
        "max_gain": {
            "distance_m": float(d[best_i]),
            "value_s": float(g[best_i]),
            "a_speed": float(aligned["a_speed"][best_i]),
            "b_speed": float(aligned["b_speed"][best_i]),
            "index": best_i,
        },
    }
