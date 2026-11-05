"""HTML report for a single-lap analysis (not a comparison).

Renders:
  - hero with lap time, track/bike/driver
  - track map coloured by acceleration sign:
      green spectrum where speed is rising (accelerating)
      red spectrum where speed is falling (braking)
      grey for ~constant
  - speed-vs-distance chart
  - placeholder section for future analysis
"""
from __future__ import annotations

import json
from typing import Any, Dict

import numpy as np

from trackmap_helpers import (
    TILE_HELPERS_JS as _TILE_HELPERS_JS,
    TILE_SPINNER_CSS as _TILE_SPINNER_CSS,
    tile_provider_js as _tile_provider_js,
    tile_provider_button_class as _tile_btn_cls,
)


def _fmt_lap(seconds: float) -> str:
    if seconds is None:
        return "—"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:06.3f}"


def _downsample(arr, n):
    """Take ~n samples evenly along arr."""
    a = np.asarray(arr)
    if len(a) <= n:
        return a
    idx = np.linspace(0, len(a) - 1, n).astype(int)
    return a[idx]


def compute_single_lap_payload(
    *, track: Dict[str, Any], lap_meta: Dict[str, Any],
    lap_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute the data payload for one lap (no HTML, no template).

    This is the pure data half of the analysis: arrays + analysis dict
    + header strings, ready for either JSON serialisation (API) or
    template substitution (legacy HTML render).

    Returns a dict with keys: distance, speed, lat, lon, time, accel_norm,
    lap_distance_m, analysis, extras, header (with driver/bike/track/src/...).
    """
    meta = track.get("meta") or {}
    src_file = track.get("source_file") or "—"
    driver = meta.get("RACER") or meta.get("DRIVER") or ""
    bike = meta.get("VEHICLE") or ""
    track_name = meta.get("TRACK") or meta.get("VENUE") or ""
    lap_no = lap_meta.get("lap_index", "—")
    duration = float(lap_meta.get("duration") or lap_data.get("duration") or 0)

    # Lap-summary-only sources (e.g. Starlane CSV) carry no per-sample GPS
    # trace — speed/lat/lon/time arrays are empty. There's no chart to draw
    # and no analysis to run; return a structurally-valid payload with empty
    # data arrays so the SPA renders the header (lap time / driver / bike /
    # track) instead of the server erroring out.
    if len(lap_data.get("speed", [])) == 0:
        return {
            "distance": [], "speed": [], "lat": [], "lon": [], "time": [],
            "accel_norm": [],
            "lap_distance_m": 0.0,
            "analysis": {
                "braking_zones": [], "accel_zones": [], "core_stats": {},
                "assessment": {
                    "headline": "Nur Rundenzeiten verfügbar "
                                "(keine GPS-/Kanaldaten in dieser Datei).",
                    "points": [],
                },
                "thresholds": {},
            },
            "extras": [],
            "channel_roles": dict(lap_data.get("channel_roles") or {}),
            "header": {
                "lap_time": _fmt_lap(duration),
                "lap_no": str(lap_no),
                "driver": driver or "—",
                "bike": bike or "—",
                "track": track_name or "—",
                "src": src_file if src_file else "",
                "duration_s": duration,
            },
        }

    # Resample to a manageable size (~500 samples)
    N = 500
    distance = _downsample(lap_data["distance"], N).astype(float)
    speed = _downsample(lap_data["speed"], N).astype(float)
    lat = _downsample(lap_data["lat"], N).astype(float)
    lon = _downsample(lap_data["lon"], N).astype(float)
    time_arr = _downsample(lap_data["time"], N).astype(float)

    # Compute per-sample acceleration sign (smoothed derivative of speed)
    # accel > 0 → accelerating (green), accel < 0 → braking (red)
    win = max(3, len(distance) // 50)
    if win % 2 == 0:
        win += 1
    pad = win // 2
    # Simple boxcar smoothing on speed
    padded = np.concatenate([
        np.full(pad, speed[0]),
        speed,
        np.full(pad, speed[-1]),
    ])
    kern = np.ones(win) / win
    speed_smooth = np.convolve(padded, kern, mode="valid")
    # Speed-change per metre (rough acceleration proxy)
    seg_d = np.diff(distance)
    seg_d = np.where(seg_d > 1e-3, seg_d, 1e-3)
    accel = np.concatenate([[0.0], np.diff(speed_smooth) / seg_d])
    # Normalise: clip to robust range so colours saturate nicely
    a_abs = np.abs(accel)
    a_max = np.percentile(a_abs, 95) if a_abs.size else 1.0
    if a_max <= 0:
        a_max = 1.0
    accel_norm = np.clip(accel / a_max, -1.0, 1.0)

    # ---- Run analysis on the FULL-resolution lap data (better precision),
    # then translate the resulting distance positions into indices on our
    # resampled (N-point) display grid so the frontend can highlight cursors.
    try:
        from single_lap_analysis import analyse_lap
        analysis = analyse_lap(lap_data)
    except Exception as e:
        # If anything goes wrong, fail gracefully — we still want the charts.
        import traceback as _tb
        _tb.print_exc()
        analysis = {
            "braking_zones": [], "accel_zones": [], "core_stats": {},
            "assessment": {"headline": f"Auswertung fehlgeschlagen: {e}", "points": []},
            "thresholds": {},
        }

    # Add display-grid indices to each zone (so the JS can move the cursor)
    def _dist_to_display_idx(d_m: float) -> int:
        return int(np.argmin(np.abs(distance - d_m)))
    for z in analysis.get("braking_zones", []):
        z["disp_start"] = _dist_to_display_idx(z["start_dist_m"])
        z["disp_end"]   = _dist_to_display_idx(z["end_dist_m"])
        z["disp_apex"]  = _dist_to_display_idx(z["apex_dist_m"])
    for z in analysis.get("accel_zones", []):
        z["disp_start"] = _dist_to_display_idx(z["start_dist_m"])
        z["disp_end"]   = _dist_to_display_idx(z["end_dist_m"])
        z["disp_apex"]  = _dist_to_display_idx(z["apex_dist_m"])

    # Extra channels (GForce, gyro, altitude, battery, XRK ch_*, ...)
    # Reduce to scalar-arrays + display metadata for the client.
    extras_payload = []
    for key, ch in (lap_data.get("extra_channels") or {}).items():
        try:
            arr = np.asarray(ch["data"], dtype=np.float64)
        except Exception:
            continue
        if len(arr) != len(distance):
            # Different sample grid — interpolate onto the display grid (by index)
            try:
                arr = np.interp(np.linspace(0, len(arr)-1, len(distance)),
                                 np.arange(len(arr)), arr)
            except Exception:
                continue
        finite = arr[np.isfinite(arr)]
        if len(finite) == 0:
            continue
        extras_payload.append({
            "id": key,
            "name": ch.get("name") or key,
            "unit": ch.get("unit") or "",
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "n":   int(len(arr)),
            "data": arr.round(3).tolist(),
        })

    return {
        "distance": distance.round(1).tolist(),
        "speed": speed.round(1).tolist(),
        "lat": lat.round(6).tolist(),
        "lon": lon.round(6).tolist(),
        "time": time_arr.round(3).tolist(),
        "accel_norm": accel_norm.round(4).tolist(),
        "lap_distance_m": float(lap_data.get("total_distance", distance[-1])),
        "analysis": analysis,
        "extras": extras_payload,
        # v21.34 — Persisted role→channel assignment (set at upload time
        # in the session-upload picker, see channel_roles registry).
        # Empty dict if the lap was uploaded before v21.34 or the user
        # skipped the assignment. Coach uses this to pre-fill its slot
        # state so users don't have to re-pick.
        "channel_roles": dict(lap_data.get("channel_roles") or {}),
        # Header strings — used by both the SPA (to fill the header) and the
        # legacy template substitution. Kept in a sub-dict so JSON consumers
        # can find them in one place.
        "header": {
            "lap_time": _fmt_lap(duration),
            "lap_no": str(lap_no),
            "driver": driver or "—",
            "bike": bike or "—",
            "track": track_name or "—",
            "src": src_file if src_file else "",
            "duration_s": duration,
        },
    }


def build_single_lap_html(
    *, track: Dict[str, Any], lap_meta: Dict[str, Any],
    lap_data: Dict[str, Any], title_extra: str = "",
    coach_href: str = "", compare_href: str = "", maptiler_key: str = "",
) -> str:
    """Build a standalone HTML page for one lap (legacy /analysis/<uuid>).

    Kept for backward compatibility with pre-existing analysis URLs. New
    analyses go through compute_single_lap_payload() + the SPA at /analyze.

    track:   the track dict from a parser (or a synthetic one for library laps)
    lap_meta: dict with 'lap_index', 'duration'
    lap_data: dict from extract_lap_data with distance/speed/lat/lon arrays
    coach_href: optional URL to the AI Coach for the same lap (v20.3).
                If non-empty, a cross-link button appears in the header.
    compare_href: optional URL to /compare with this lap pre-loaded as
                  slot A (v21.33). If non-empty, a second cross-link button
                  appears alongside the AI Coach button.
    """
    payload = compute_single_lap_payload(
        track=track, lap_meta=lap_meta, lap_data=lap_data,
    )
    data_json = json.dumps(payload, separators=(",", ":"))
    h = payload["header"]

    return _PAGE_TEMPLATE.replace("{{DATA_JSON}}", data_json) \
        .replace("{{LAP_TIME}}", h["lap_time"]) \
        .replace("{{LAP_NO}}", h["lap_no"]) \
        .replace("{{DRIVER}}", h["driver"]) \
        .replace("{{BIKE}}", h["bike"]) \
        .replace("{{TRACK}}", h["track"]) \
        .replace("{{SRC}}", h["src"]) \
        .replace("{{TITLE_EXTRA}}", title_extra) \
        .replace("{{COACH_HREF}}", coach_href) \
        .replace("{{COMPARE_HREF}}", compare_href) \
        .replace("{{TILE_HELPERS_JS}}", _TILE_HELPERS_JS) \
        .replace("{{TILE_SPINNER_CSS}}", _TILE_SPINNER_CSS) \
        .replace("{{TILE_PROVIDER_JS}}", _tile_provider_js(maptiler_key)) \
        .replace("{{TM_BG_BTN_CLS}}", _tile_btn_cls(maptiler_key))


def build_single_lap_empty_html(*, title_extra: str = "", maptiler_key: str = "") -> str:
    """Build the SPA shell with no lap loaded yet.

    Same template as build_single_lap_html, but with DATA=null. The
    render JS in the template detects the null state and shows empty
    placeholder sections plus a "Runde laden" prompt. Selecting a lap
    in the picker modal navigates to /analyze?lap_id=N which then
    re-renders the same template with real data.

    v20.1: this is the new default landing for /analyze.
    """
    return _PAGE_TEMPLATE.replace("{{DATA_JSON}}", "null") \
        .replace("{{LAP_TIME}}", "—:—.—") \
        .replace("{{LAP_NO}}", "—") \
        .replace("{{DRIVER}}", "—") \
        .replace("{{BIKE}}", "—") \
        .replace("{{TRACK}}", "—") \
        .replace("{{SRC}}", "keine Runde geladen") \
        .replace("{{TITLE_EXTRA}}", title_extra) \
        .replace("{{COACH_HREF}}", "") \
        .replace("{{COMPARE_HREF}}", "") \
        .replace("{{TILE_HELPERS_JS}}", _TILE_HELPERS_JS) \
        .replace("{{TILE_SPINNER_CSS}}", _TILE_SPINNER_CSS) \
        .replace("{{TILE_PROVIDER_JS}}", _tile_provider_js(maptiler_key)) \
        .replace("{{TM_BG_BTN_CLS}}", _tile_btn_cls(maptiler_key))


_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Datenviewer · {{TITLE_EXTRA}}</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0a0a0a; --bg-2:#141414;
  --ink:#f5f5f0; --ink-dim:#a0a0a0; --ink-faint:#888;
  --line:#262626;
  --accel:#3aff7a;   /* green for accelerating */
  --brake:#ff3d3d;   /* red for braking */
  --accent:#00d4ff;
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:var(--bg);color:var(--ink);font-family:'Space Grotesk',sans-serif;line-height:1.5;min-height:100vh}
.mono{font-family:'JetBrains Mono',monospace;font-feature-settings:'tnum'}
.page{max-width:1280px;margin:0 auto;padding:48px 32px 80px}
.page::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:99;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E");opacity:.05;mix-blend-mode:overlay}

/* v21.1 — Header is the normal page heading (eyebrow + h1). Below it sits
   the lap-card with the big time + metadata + picker button. */
header{
  padding-bottom:24px;margin-bottom:0;
}
.eyebrow{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.2em;color:var(--ink-dim);text-transform:uppercase;margin-bottom:16px}
h1{font-family:'Bebas Neue',sans-serif;font-size:clamp(36px,5vw,56px);line-height:.9;letter-spacing:.01em;background:linear-gradient(180deg,var(--ink) 0%,#888 100%);-webkit-background-clip:text;background-clip:text;color:transparent}

/* v21.1 — Lap-Card: big lap time on top, metadata below, action button at the bottom.
   Not sticky. Lives inside .page (1280px max-width).
   Empty state: time shows "—:—.—" and the button becomes a pulsing "+ RUNDE WÄHLEN". */
.dv-lap-card{
  background:#0a0a0a;border:1px solid #262626;
  padding:32px 28px;margin-bottom:32px;
  display:grid;grid-template-columns:auto 1fr;gap:24px 36px;align-items:end;
}
.dv-lc-time{
  font-family:'Bebas Neue',sans-serif;font-size:clamp(64px,9vw,112px);
  line-height:.85;color:#00d4ff;font-feature-settings:'tnum';
  letter-spacing:.01em;
  grid-row:1;grid-column:1;
}
.dv-lap-card.empty .dv-lc-time{color:#444}
.dv-lc-meta{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px 24px;
  grid-row:1;grid-column:2;
  font-family:'JetBrains Mono',monospace;
}
.dv-lc-row{display:flex;flex-direction:column;gap:2px;min-width:0}
.dv-lc-row .k{font-size:10px;color:#888;letter-spacing:.15em;text-transform:uppercase}
.dv-lc-row .v{font-size:14px;color:#f5f5f0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dv-lap-card.empty .dv-lc-row .v{color:#666}
.dv-lc-actions{
  grid-row:2;grid-column:1 / -1;
  display:flex;gap:12px;align-items:center;flex-wrap:wrap;
  padding-top:20px;border-top:1px solid #262626;
}
.dv-lc-change{
  background:transparent;border:1px solid #262626;color:#a0a0a0;
  font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:500;
  letter-spacing:.12em;padding:12px 20px;cursor:pointer;text-transform:uppercase;
  transition:border-color .12s,color .12s;
}
.dv-lc-change:hover{border-color:#a0a0a0;color:#f5f5f0}
.dv-lap-card.empty .dv-lc-change{
  background:#00d4ff;color:#000;border:none;font-weight:600;font-size:13px;
  padding:14px 22px;
  animation:dv-lc-pulse 2s ease-in-out infinite;
}
.dv-lap-card.empty .dv-lc-change:hover{background:#1ee4ff}
@keyframes dv-lc-pulse{
  0%,100%{box-shadow:0 0 0 0 rgba(0,212,255,.6)}
  50%{box-shadow:0 0 0 10px rgba(0,212,255,0)}
}
.dv-lc-cross{
  color:#a0a0a0;text-decoration:none;font-size:11px;letter-spacing:.15em;
  text-transform:uppercase;padding:12px 16px;border:1px solid #262626;
  transition:color .12s,border-color .12s;
}
.dv-lc-cross:hover{color:#f5f5f0;border-color:#a0a0a0}
.dv-lc-cross[hidden]{display:none}
@media (max-width:780px){
  .dv-lap-card{grid-template-columns:1fr;padding:24px 20px;}
  .dv-lc-time{font-size:64px;grid-row:1;grid-column:1}
  .dv-lc-meta{grid-row:2;grid-column:1}
  .dv-lc-actions{grid-row:3}
}

/* Old .hero is gone — keep its rules so a legacy snapshot still renders */
.hero{display:none}

/* Empty-state placeholder for chart/map sections (no lap loaded) */
.empty-placeholder{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-height:240px;border:1px dashed var(--line);background:var(--bg-2);
  color:var(--ink-dim);font-family:'JetBrains Mono',monospace;font-size:12px;
  letter-spacing:.15em;text-transform:uppercase;gap:8px;padding:24px;
}
.empty-placeholder .ep-icon{font-size:32px;color:var(--ink-faint);font-family:'Bebas Neue',sans-serif}
.empty-placeholder .ep-hint{font-size:10px;color:var(--ink-faint);letter-spacing:.1em}
body.empty-mode .cursor-info{opacity:.4}
body.empty-mode .chart-toolbar{opacity:.4;pointer-events:none}

.section-title{margin:56px 0 16px;display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--line);padding-bottom:12px}
.section-title h2{font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:.02em}
.section-title .num{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-faint);letter-spacing:.15em}

.legend{display:flex;gap:24px;align-items:center;margin:16px 0;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);letter-spacing:.1em}
.legend-swatch{display:inline-block;width:32px;height:8px;margin-right:8px;vertical-align:middle}

.map-wrap{background:var(--bg-2);border:1px solid var(--line);padding:16px;overflow:hidden;position:relative}
.map-svg{width:100%;height:auto;display:block}
.chart-svg{width:100%;height:auto;display:block;background:var(--bg-2);border:1px solid var(--line)}

/* ----- Chart toolbar (channel picker button + legend) ----- */
.chart-toolbar{display:flex;align-items:center;gap:16px;margin:0 0 8px;flex-wrap:wrap}
.chart-btn{
  font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.15em;
  background:var(--bg-2);border:1px solid var(--line);color:var(--ink);
  padding:7px 12px;cursor:pointer;text-transform:uppercase;
}
.chart-btn:hover{border-color:var(--accent);color:var(--accent)}
.chart-btn.primary{background:var(--accent);color:#000;border-color:var(--accent)}
.chart-btn.primary:hover{background:#1ee4ff;color:#000}
.chart-btn.primary .badge{background:#000;color:var(--accent)}
.chart-btn.ghost{background:transparent}
/* Accent variant for the channel-picker button — same shape as .primary
   so the cyan fill matches the rest of the brand. */
.chart-btn.accent{background:var(--accent);color:#000;border-color:var(--accent);font-weight:600}
.chart-btn.accent:hover{background:#1ee4ff;color:#000}
.chart-btn.accent .badge{background:#000;color:var(--accent)}
.chart-btn .badge{
  display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;
  background:var(--accent);color:#000;font-size:10px;font-weight:600;
}
.chart-legend{display:flex;gap:10px;flex-wrap:wrap;font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.1em;color:var(--ink-dim);text-transform:uppercase}
.chart-legend .lg{display:inline-flex;gap:6px;align-items:center}
.chart-legend .swatch{display:inline-block;width:14px;height:2px}
.chart-hint{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.08em;color:var(--ink-dim);text-transform:uppercase}
/* v21.22 — Segmented Toggle für Trackmap-Modus (FARBKANAL | FAHRLINIE) */
/* v21.25 — Mapview-Button rechts (margin-left:auto), seg-switch links */
/* v22.0 — Außenrahmen (#262626 → #4a4a4a) und inaktive Buttons (--ink-dim
   → #c8c8c8) heller, damit der Toggle besser sichtbar ist. Aktiv-Style
   (Akzent-Hintergrund, schwarzer Text) unverändert. */
.seg-switch{display:inline-flex;border:1px solid #4a4a4a;background:var(--bg-2)}
.chart-toolbar .seg-switch:first-of-type{margin-left:auto}
.chart-toolbar .tm-bg-btn{margin-left:auto}
.seg-switch .seg-opt{
  font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.15em;
  background:transparent;border:0;color:#c8c8c8;
  padding:7px 14px;cursor:pointer;text-transform:uppercase;
}
.seg-switch .seg-opt:hover{color:var(--ink)}
.seg-switch .seg-opt.active{background:var(--accent);color:#000;font-weight:600}
/* Im FAHRLINIE-Modus: Farb-Kanal-Button + Farb-Legende ausgrauen */
#track-toolbar.line-mode #btn-pick-track-color,
#track-toolbar.line-mode #track-legend{opacity:.35;pointer-events:none}
/* v21.23 — Attribution für Tile-Provider */
.map-attribution{
  position:absolute;bottom:6px;right:10px;
  font-family:'JetBrains Mono',monospace;font-size:9px;
  color:rgba(245,245,240,.7);background:rgba(0,0,0,.4);
  padding:2px 6px;border-radius:2px;letter-spacing:.05em;
  pointer-events:auto;z-index:2;
}
.map-attribution a{color:inherit;text-decoration:none;border-bottom:1px dotted rgba(245,245,240,.5)}
.map-attribution a:hover{color:var(--accent)}
.chart-svg{cursor:crosshair}
.chart-svg:active{cursor:grabbing}

/* ----- Channel picker modal ----- */
.modal-back{
  position:fixed;inset:0;background:rgba(0,0,0,.72);
  z-index:1000;display:flex;align-items:center;justify-content:center;
  padding:24px;
}
.modal-back[hidden]{display:none}
.modal{
  background:var(--bg-2);border:1px solid var(--line);
  width:100%;max-width:760px;max-height:80vh;display:flex;flex-direction:column;
}
.modal-head{display:flex;align-items:center;justify-content:space-between;
  padding:18px 24px;border-bottom:1px solid var(--line)}
.modal-head h3{font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:.04em;margin:0}
.modal-close{background:none;border:none;color:var(--ink-dim);font-size:24px;cursor:pointer;line-height:1;padding:0 6px}
.modal-close:hover{color:var(--ink)}
.modal-toolbar{padding:14px 24px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center}
.modal-toolbar input{
  flex:1;background:var(--bg);border:1px solid var(--line);color:var(--ink);
  font-family:'JetBrains Mono',monospace;font-size:12px;padding:8px 10px;outline:none;
}
.modal-toolbar input:focus{border-color:var(--accent)}
.modal-hint{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.1em}
.modal-body{flex:1 1 auto;overflow:auto;padding:0 24px}
.modal-foot{display:flex;gap:8px;padding:14px 24px;border-top:1px solid var(--line)}

.ch-table-head, .ch-row{
  display:grid;
  grid-template-columns: 56px minmax(0,1fr) 80px 90px 90px 90px;
  gap:10px;align-items:center;
}
.ch-table-head{
  padding:12px 0;border-bottom:1px solid var(--line);
  font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.15em;
  position:sticky;top:0;background:var(--bg-2);
}
.ch-row{padding:10px 0;border-bottom:1px solid #1a1a1a;cursor:pointer}
.ch-row:hover{background:#181818}
.ch-row.active{background:#0e2128}
.ch-row .ch-col-on{display:flex;justify-content:center}
.ch-row .ch-col-on input{width:16px;height:16px;accent-color:var(--accent);cursor:pointer}
.ch-row .ch-col-name{font-size:13px;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ch-row .ch-col-name .swatch{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:8px;vertical-align:middle}
.ch-row .ch-col-unit,
.ch-row .ch-col-min,
.ch-row .ch-col-max,
.ch-row .ch-col-mean{
  font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);text-align:right;
}
.ch-row .ch-col-unit{text-align:left}
.ch-empty{padding:40px 0;text-align:center;color:var(--ink-faint);font-family:'JetBrains Mono',monospace;font-size:11px}
.chart-tick{font-family:'JetBrains Mono',monospace;font-size:10px;fill:var(--ink-faint);letter-spacing:.05em}
.chart-label{font-family:'JetBrains Mono',monospace;font-size:10px;fill:var(--ink-dim);letter-spacing:.1em}

/* Interactive cursor system */
.map-svg, .chart-svg{cursor:crosshair}
.cursor-info{
  /* v21.4 — Sticky below the rd-header so the cursor read-out stays visible
     when scrolling through the charts. Background is fully opaque so the
     content scrolling underneath doesn't bleed through. */
  position:sticky;top:68px;z-index:50;
  background:#0a0a0a;
  border:1px solid var(--line); border-left:3px solid var(--accent);
  padding:14px 20px; margin-bottom:24px;
  font-family:'JetBrains Mono',monospace; color:var(--ink);
  display:flex; flex-wrap:wrap; gap:6px 28px; align-items:baseline;
}
@media (max-width:780px){.cursor-info{top:60px}}
.cursor-info .cell{display:flex; flex-direction:column; gap:2px; min-width:60px}
.cursor-info .k{font-size:10px; color:var(--ink-faint); letter-spacing:.15em; text-transform:uppercase}
.cursor-info .v{font-size:15px; font-weight:500; font-feature-settings:'tnum'}
.cursor-info .v.muted{color:var(--ink-dim)}
.cursor-info .hint{
  width:100%; color:var(--ink-faint); font-size:10px;
  margin-top:4px; letter-spacing:.1em
}

/* Assessment text block */
.assessment{
  background:var(--bg-2); border-left:3px solid var(--accent);
  padding:20px 28px; margin-bottom:24px;
}
.assessment .headline{
  font-family:'Bebas Neue',sans-serif; font-size:24px;
  letter-spacing:.02em; color:var(--ink); margin-bottom:12px;
}
.assessment ul{list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:8px}
.assessment li{
  display:flex; gap:12px; align-items:baseline;
  font-size:14px; color:var(--ink); line-height:1.5;
}
.assessment li.clickable{cursor:pointer; transition:background .15s; padding:4px 8px; margin:-4px -8px; border-radius:2px}
.assessment li.clickable:hover{background:#1a1a1a}
.assessment .pill{
  flex:0 0 auto; font-family:'JetBrains Mono',monospace; font-size:9px;
  padding:3px 8px; letter-spacing:.15em; text-transform:uppercase;
}
.assessment .pill.good{background:rgba(58,255,122,.15); color:var(--accel); border:1px solid var(--accel)}
.assessment .pill.warn{background:rgba(255,170,0,.15); color:#ffaa00; border:1px solid #ffaa00}
.assessment .pill.bad{background:rgba(255,61,61,.15);  color:var(--brake); border:1px solid var(--brake)}
.assessment .pill.neutral{background:transparent; color:var(--ink-faint); border:1px solid var(--line)}

/* Core stats cards */
.core-stats{
  display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr));
  gap:12px; margin-bottom:32px;
}
.stat-card{
  background:var(--bg-2); border:1px solid var(--line);
  padding:14px 18px; display:flex; flex-direction:column; gap:4px;
}
.stat-card .k{font-family:'JetBrains Mono',monospace; font-size:9px;
  letter-spacing:.15em; color:var(--ink-faint); text-transform:uppercase}
.stat-card .v{font-family:'JetBrains Mono',monospace; font-size:18px;
  font-weight:500; color:var(--ink); font-feature-settings:'tnum'}
.stat-card .sub{font-family:'JetBrains Mono',monospace; font-size:10px;
  color:var(--ink-dim); letter-spacing:.05em}

/* Analysis tabs (section 03) — file-folder style with a clear content frame */
.an-tabs-wrap{margin:8px 0 28px}
.an-tabs{
  display:flex; gap:6px;
  font-family:'JetBrains Mono',monospace;
  position:relative; z-index:2;
  padding-left:4px; /* slight indent so the first tab doesn't kiss the page edge */
}
.an-tab{
  flex:0 0 auto;
  background:var(--bg-2);
  border:1px solid var(--line);
  border-bottom:none;
  color:var(--ink-dim);
  padding:14px 22px 16px;
  font-family:inherit; font-size:13px; font-weight:600;
  letter-spacing:.18em; text-transform:uppercase;
  cursor:pointer;
  transition:background .15s, color .15s, border-color .15s, transform .12s;
  position:relative;
  text-align:left;
  min-width:180px;
}
.an-tab:hover{
  background:#1a1a1a; color:var(--ink);
}
.an-tab.active{
  background:var(--accent); color:#000;
  border-color:var(--accent);
  /* visually "lift" the active tab and let it overlap the content frame's top border */
  transform:translateY(1px);
  z-index:3;
  /* slight shadow above the panel */
  box-shadow:0 -2px 0 var(--accent);
}
.an-tab .small{
  font-size:9px; color:var(--ink-faint);
  letter-spacing:.2em; display:block; margin-bottom:4px;
  font-weight:500;
}
.an-tab.active .small{color:#000; opacity:.65}

/* Content panel sits inside a thick cyan-tinted frame to make the tab/content
   relationship visually obvious */
.an-content{
  border:2px solid var(--accent);
  background:var(--bg);
  padding:28px 28px 24px;
  position:relative; z-index:1;
}
.an-panel{display:none}
.an-panel.active{display:block}

/* Channel-assignment cards (advanced tabs) */
.channel-assign-block{
  background:var(--bg-2); border:1px solid var(--line);
  padding:18px 22px; margin-bottom:20px;
}
.channel-assign-title{
  font-family:'JetBrains Mono',monospace; font-size:10px;
  letter-spacing:.2em; color:var(--ink-faint); text-transform:uppercase;
  margin-bottom:14px;
}
.channel-assign-grid{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:12px;
}
.channel-slot{
  background:var(--bg); border:1px solid var(--line);
  padding:12px 14px;
  display:flex; flex-direction:column; gap:8px;
}
.channel-slot .role{
  font-family:'Bebas Neue',sans-serif; font-size:14px;
  letter-spacing:.05em; color:var(--ink);
}
.channel-slot .role .req{color:var(--accent); margin-left:4px}
.channel-slot .picker{
  display:flex; align-items:center; gap:10px;
  background:var(--bg-2); border:1px solid var(--line);
  padding:8px 10px; cursor:pointer; transition:border-color .15s;
}
.channel-slot .picker:hover{border-color:var(--accent)}
.channel-slot .picker .name{
  font-family:'JetBrains Mono',monospace; font-size:12px;
  color:var(--ink); flex:1;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.channel-slot .picker .name.empty{color:var(--ink-faint); font-style:italic}
.channel-slot .picker .unit{
  font-family:'JetBrains Mono',monospace; font-size:10px;
  color:var(--ink-faint); letter-spacing:.1em;
}
.channel-slot .picker .arrow{color:var(--ink-dim); font-size:14px}
.channel-slot .picker.auto-detected{border-left:2px solid var(--accent)}
.channel-slot .hint{
  font-family:'JetBrains Mono',monospace; font-size:9px;
  color:var(--ink-faint); letter-spacing:.1em;
}

/* Coming-soon placeholder */
.coming-soon{
  background:var(--bg-2); border:1px dashed var(--line);
  padding:80px 24px; text-align:center;
  font-family:'JetBrains Mono',monospace; color:var(--ink-faint);
  letter-spacing:.2em; font-size:13px;
}
.coming-soon .big{
  font-family:'Bebas Neue',sans-serif; font-size:32px;
  color:var(--ink-dim); letter-spacing:.05em;
  display:block; margin-bottom:8px;
}

.phase-h{
  font-family:'Bebas Neue',sans-serif; font-size:18px;
  letter-spacing:.05em; margin:24px 0 8px; color:var(--ink-dim);
}

/* Phase tables (brakes / accels) */
.phase-table{
  display:flex; flex-direction:column;
  border-top:1px solid var(--line);
  margin-bottom:8px;
  font-family:'JetBrains Mono',monospace;
}
.phase-row{
  display:grid;
  grid-template-columns: 32px 1fr 1fr 1fr 1fr 1fr 1fr 1fr;
  gap:12px; align-items:center;
  padding:10px 8px; border-bottom:1px solid var(--line);
  font-size:12px; cursor:pointer; transition:background .15s;
}
.phase-row.head{
  cursor:default;
  font-size:9px; color:var(--ink-faint); letter-spacing:.15em;
  text-transform:uppercase;
  border-bottom:1px solid var(--line); padding-bottom:6px;
}
.phase-row:not(.head):hover, .phase-row.hover-from-chart{background:#1a1a1a}
.phase-row.active{background:#0a2128; border-left:3px solid var(--accent); padding-left:5px}
.phase-row .idx{color:var(--ink-faint); text-align:right}
.phase-row .v{color:var(--ink)}
.phase-row .v.fast{color:var(--accent); font-weight:500}
.phase-row .v.brake-num{color:var(--brake)}
.phase-row .v.accel-num{color:var(--accel)}
.phase-row .badge{
  display:inline-block; font-size:9px; padding:3px 6px;
  letter-spacing:.1em; text-transform:uppercase;
  border:1px solid currentColor;
}
.phase-row .badge.ok{color:var(--accel)}
.phase-row .badge.warn{color:#ffaa00}
.phase-row .badge.bad{color:var(--brake)}
@media (max-width:880px){
  .phase-row{grid-template-columns: 32px 1fr 1fr 1fr 1fr; gap:8px; font-size:11px}
  .phase-row .hide-narrow{display:none}
}

footer{margin-top:80px;padding-top:32px;border-top:1px solid var(--line);color:var(--ink-faint);font-family:'JetBrains Mono',monospace;font-size:11px;display:flex;justify-content:space-between;letter-spacing:.05em;flex-wrap:wrap;gap:16px}
</style>
</head>
<body>
<div class="page">
  <header>
    <div class="eyebrow">Einzelrunde · Tiefenanalyse</div>
    <h1>DATENVIEWER</h1>
  </header>

  <!-- v21.1 — Lap card: time + metadata, picker button below. Not sticky. -->
  <div class="dv-lap-card" id="dv-lap-card">
    <div class="dv-lc-time mono" id="dv-lc-time">{{LAP_TIME}}</div>
    <div class="dv-lc-meta">
      <div class="dv-lc-row"><span class="k">STRECKE</span><span class="v" id="dv-lc-track">{{TRACK}}</span></div>
      <div class="dv-lc-row"><span class="k">LAP</span><span class="v" id="dv-lc-lapno">#{{LAP_NO}}</span></div>
      <div class="dv-lc-row"><span class="k">BIKE</span><span class="v" id="dv-lc-bike">{{BIKE}}</span></div>
      <div class="dv-lc-row"><span class="k">FAHRER</span><span class="v" id="dv-lc-driver">{{DRIVER}}</span></div>
    </div>
    <div class="dv-lc-actions">
      <button type="button" class="dv-lc-change" id="btn-load-lap">
        <span class="bll-label">↻ ANDERE RUNDE LADEN</span>
      </button>
      <a class="dv-lc-cross" id="btn-cross-link" href="{{COACH_HREF}}" hidden>→ AI COACH</a>
      <a class="dv-lc-cross" id="btn-cross-link-compare" href="{{COMPARE_HREF}}" hidden>→ VERGLEICH</a>
    </div>
  </div>

  <div class="cursor-info" id="cursor-info">
    <div class="cell"><div class="k">Position</div><div class="v" id="ci-dist">—</div></div>
    <div class="cell"><div class="k">Time</div><div class="v" id="ci-time">—</div></div>
    <div class="cell"><div class="k">Speed</div><div class="v" id="ci-speed">—</div></div>
    <div id="ci-extras" style="display:contents"></div>
    <div class="hint" id="ci-hint">Hover oder Klick auf Map/Chart → Werte an der Cursor-Position · Klick: Marker fest · ESC: lösen</div>
  </div>

  <div class="section-title">
    <h2>01 · STRECKE · BESCHLEUNIGEN / BREMSEN</h2>
    <span class="num" id="track-color-label">FARBE = LÄNGSBESCHLEUNIGUNG</span>
  </div>
  <div class="chart-toolbar" id="track-toolbar">
    <button type="button" id="btn-pick-track-color" class="chart-btn accent">FARB-KANAL: <span id="track-color-current">Längsbeschleunigung</span></button>
    <div class="legend" id="track-legend">
      <div><span class="legend-swatch" style="background:linear-gradient(90deg,#103,#3aff7a)"></span>BESCHLEUNIGEN</div>
      <div><span class="legend-swatch" style="background:#666"></span>KONSTANT</div>
      <div><span class="legend-swatch" style="background:linear-gradient(90deg,#666,#ff3d3d)"></span>BREMSEN</div>
    </div>
    <!-- v21.22 — Modus-Schalter: FARBKANAL (geschwindigkeits-/g-codiert) vs FAHRLINIE (eine dünne Linie in Rundenfarbe) -->
    <div class="seg-switch" role="tablist" aria-label="Trackmap-Modus">
      <button type="button" class="seg-opt active" id="tm-mode-color" role="tab" aria-selected="true">FARBKANAL</button>
      <button type="button" class="seg-opt" id="tm-mode-line" role="tab" aria-selected="false">FAHRLINIE</button>
    </div>
    <!-- v21.23 — Mapview-Schalter: Esri World Imagery Satelliten-Hintergrund -->
    <!-- v21.25 — Single-Button (vorher zweiteilig) -->
    <button type="button" class="tm-bg-btn {{TM_BG_BTN_CLS}}" id="tm-bg-toggle" aria-pressed="false">
      <span class="tm-bg-dot"></span>MAPVIEW
    </button>
  </div>
  <div class="map-wrap">
    <svg class="map-svg" id="track-map" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMid meet"></svg>
    <!-- v21.23 — Esri-Attribution (nur sichtbar wenn Mapview aktiv) -->
    <!-- v21.26 — Attribution wird zur Laufzeit gefüllt -->
    <div class="map-attribution" id="tm-attribution" style="display:none"></div>
  </div>

  <!-- Track color picker dialog (single-select) -->
  <div class="modal-back" id="tc-modal" hidden>
    <div class="modal" role="dialog" aria-labelledby="tc-modal-title">
      <div class="modal-head">
        <h3 id="tc-modal-title">FARB-KANAL FÜR TRACK-MAP</h3>
        <button type="button" class="modal-close" id="tc-modal-close" aria-label="Schließen">×</button>
      </div>
      <div class="modal-toolbar">
        <input type="text" id="tc-search" placeholder="Kanäle durchsuchen…">
        <span class="modal-hint">EIN Kanal bestimmt die Streckenfarbe</span>
      </div>
      <div class="modal-body">
        <div class="ch-table-head">
          <div class="ch-col-on">SEL</div>
          <div class="ch-col-name">NAME</div>
          <div class="ch-col-unit">EINHEIT</div>
          <div class="ch-col-min">MIN</div>
          <div class="ch-col-max">MAX</div>
          <div class="ch-col-mean">⌀</div>
        </div>
        <div class="ch-table-body" id="tc-table-body"></div>
      </div>
      <div class="modal-foot">
        <span style="flex:1"></span>
        <button type="button" class="chart-btn primary" id="tc-apply">FERTIG</button>
      </div>
    </div>
  </div>

  <div class="section-title">
    <h2>02 · DATEN VS. DISTANZ</h2>
    <span class="num" id="chart-header-extra">SPEED · KANÄLE · ZOOM</span>
  </div>
  <div class="chart-toolbar" id="chart-toolbar">
    <button type="button" id="btn-pick-channels" class="chart-btn accent">+ KANÄLE WÄHLEN <span id="active-chan-count"></span></button>
    <button type="button" id="btn-zoom-reset" class="chart-btn ghost" hidden title="Doppelklick im Chart resetted ebenfalls">ZOOM <span class="zoom-pct">100%</span> · RESET</button>
    <div class="chart-legend" id="chart-legend"></div>
    <span class="chart-hint">Mausrad zoomen · ziehen pannen · doppelklick reset</span>
  </div>
  <svg class="chart-svg" id="speed-chart" viewBox="0 0 1200 480" preserveAspectRatio="none"></svg>

  <!-- Channel picker dialog -->
  <div class="modal-back" id="ch-modal" hidden>
    <div class="modal" role="dialog" aria-labelledby="ch-modal-title">
      <div class="modal-head">
        <h3 id="ch-modal-title">WEITERE KANÄLE</h3>
        <button type="button" class="modal-close" id="ch-modal-close" aria-label="Schließen">×</button>
      </div>
      <div class="modal-toolbar">
        <input type="text" id="ch-search" placeholder="Kanäle durchsuchen…">
        <span class="modal-hint" id="ch-modal-hint"></span>
      </div>
      <div class="modal-body">
        <div class="ch-table-head">
          <div class="ch-col-on">AN</div>
          <div class="ch-col-name">NAME</div>
          <div class="ch-col-unit">EINHEIT</div>
          <div class="ch-col-min">MIN</div>
          <div class="ch-col-max">MAX</div>
          <div class="ch-col-mean">⌀</div>
        </div>
        <div class="ch-table-body" id="ch-table-body"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="chart-btn ghost" id="ch-clear">ALLE AUS</button>
        <span style="flex:1"></span>
        <button type="button" class="chart-btn primary" id="ch-apply">FERTIG</button>
      </div>
    </div>
  </div>

  <footer>
    <span>RACEDAT · SINGLE-LAP DATENVIEWER</span>
    <span>N=500 SAMPLES</span>
  </footer>
</div>

<!-- v20.1: Lap-Picker modal — load another lap without leaving the SPA -->
<div class="lp-modal" id="lp-modal" hidden>
  <div class="lp-modal-box">
    <div class="lp-modal-head">
      <h3>RUNDE LADEN</h3>
      <button type="button" class="lp-close" id="lp-modal-close" aria-label="Schließen">×</button>
    </div>
    <div class="lp-tabs">
      <button type="button" class="lp-tab active" data-lp-tab="library">AUS BIBLIOTHEK</button>
      <button type="button" class="lp-tab" data-lp-tab="upload">LOKALE DATEI</button>
    </div>

    <!-- TAB: library -->
    <div class="lp-panel" id="lp-panel-library">
      <div class="lp-prefilter" id="lp-prefilter" hidden>
        <span class="lp-pf-label">VORFILTER STRECKE:</span>
        <span class="lp-pf-value" id="lp-pf-track"></span>
        <button type="button" class="lp-pf-clear" id="lp-pf-clear">× ENTFERNEN</button>
      </div>
      <div class="lp-filter">
        <div class="lp-field lp-span2">
          <label>SUCHE</label>
          <input type="text" id="lp-f-search" placeholder="Fahrer, Bike, Strecke, Notizen, Datei…">
        </div>
        <div class="lp-field">
          <label>FAHRER</label>
          <select id="lp-f-driver"><option value="">— alle —</option></select>
        </div>
        <div class="lp-field">
          <label>BIKE</label>
          <select id="lp-f-bike"><option value="">— alle —</option></select>
        </div>
        <div class="lp-field">
          <label>STRECKE</label>
          <select id="lp-f-track"><option value="">— alle —</option></select>
        </div>
        <div class="lp-field">
          <label>MAX RUNDENZEIT</label>
          <input type="text" id="lp-f-max" placeholder="z.B. 1:55.0" pattern="[0-9]+:[0-5][0-9](\.[0-9]+)?">
        </div>
      </div>
      <div class="lp-results" id="lp-results">
        <div class="lp-empty">LADE…</div>
      </div>
      <div class="lp-foot">
        <span id="lp-count">0 RUNDEN</span>
        <span>KLICK ZUM LADEN</span>
      </div>
    </div>

    <!-- TAB: upload -->
    <div class="lp-panel" id="lp-panel-upload" hidden>
      <form method="POST" action="/analyze" enctype="multipart/form-data" class="lp-upload-form" id="lp-upload-form">
        <input type="hidden" name="mode" value="upload">
        <div class="lp-upload-drop">
          <div class="lp-upload-icon">⇪</div>
          <div class="lp-upload-title">DATEI WÄHLEN</div>
          <div class="lp-upload-hint">.ses · .ld · .xrk/.xrz · .csv · .dat (I2M) · .zip (2D) — max 70 MB</div>
          <input type="file" name="file" id="lp-file-input" required
                 accept=".ses,.SES,.ld,.LD,.xrk,.XRK,.xrz,.XRZ,.csv,.CSV,.dat,.DAT,.zip,.ZIP">
          <div class="lp-upload-name" id="lp-upload-name"></div>
        </div>
        <input type="hidden" name="adhoc_token" id="lp-adhoc-token" value="">
        <input type="hidden" name="lap" id="lp-lap-choice" value="auto">
        <div class="lp-upload-options">
          <div class="lp-lapchoice-status" id="lp-lapchoice-status" hidden></div>
          <div class="lp-lapchoice" id="lp-lapchoice" hidden>
            <div class="k">RUNDE WÄHLEN</div>
            <div class="lp-lapchoice-list" id="lp-lapchoice-list"></div>
          </div>
        </div>
        <div class="lp-upload-actions">
          <button type="submit" class="lp-upload-submit">ANALYSIEREN →</button>
        </div>
      </form>
    </div>
  </div>
</div>

<!-- v20.1: Empty-state hint overlay (shown over chart sections when no lap loaded) -->
<style>
/* v20.1 — Lap-picker modal styling */
.lp-modal{
  position:fixed;inset:0;background:rgba(0,0,0,.72);
  display:flex;align-items:flex-start;justify-content:center;
  padding:48px 24px;z-index:1200;overflow-y:auto;
  backdrop-filter:blur(6px);
}
.lp-modal[hidden]{display:none}
.lp-modal-box{
  background:var(--bg);border:1px solid var(--line);
  width:min(1100px, 100%);max-height:calc(100vh - 96px);
  display:flex;flex-direction:column;
}
.lp-modal-head{
  display:flex;justify-content:space-between;align-items:center;
  padding:20px 28px;border-bottom:1px solid var(--line);
}
.lp-modal-head h3{
  font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:.04em;
}
.lp-close{
  background:none;border:none;color:var(--ink-dim);font-size:28px;
  cursor:pointer;width:36px;height:36px;line-height:1;
}
.lp-close:hover{color:var(--ink)}
.lp-tabs{
  display:flex;gap:8px;padding:14px 20px 0;
  border-bottom:1px solid var(--line);background:var(--bg-2);
}
.lp-tab{
  background:var(--bg);border:1px solid var(--line);border-bottom:none;
  color:var(--ink-dim);
  font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:.08em;
  padding:14px 28px;cursor:pointer;text-transform:uppercase;
  position:relative;top:1px;
  transition:background .12s,color .12s,border-color .12s;
}
.lp-tab:hover{color:var(--ink);border-color:var(--ink-dim)}
.lp-tab.active{
  background:var(--accent);color:#000;border-color:var(--accent);font-weight:600;
  box-shadow:0 -2px 0 0 var(--accent);
}
.lp-tab.active:hover{background:#1ee4ff;border-color:#1ee4ff;color:#000}
.lp-tab::before{
  content:'';display:inline-block;width:8px;height:8px;
  margin-right:10px;border-radius:50%;
  background:var(--ink-faint);vertical-align:middle;
  transition:background .12s;
}
.lp-tab.active::before{background:#000}
.lp-panel{flex:1 1 auto;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.lp-panel[hidden]{display:none}

.lp-prefilter{
  display:flex;align-items:center;gap:12px;padding:12px 28px;
  background:rgba(0,212,255,.06);border-bottom:1px solid rgba(0,212,255,.2);
  font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em;
}
.lp-prefilter[hidden]{display:none}
.lp-pf-label{color:var(--ink-dim);text-transform:uppercase}
.lp-pf-value{color:var(--accent);font-weight:500}
.lp-pf-clear{
  background:transparent;border:1px solid var(--line);color:var(--ink-dim);
  font-family:inherit;font-size:10px;letter-spacing:.1em;padding:4px 10px;
  cursor:pointer;text-transform:uppercase;
}
.lp-pf-clear:hover{border-color:var(--ink-dim);color:var(--ink)}

.lp-filter{
  display:grid;grid-template-columns:repeat(auto-fit, minmax(160px, 1fr));
  gap:12px;padding:20px 28px;border-bottom:1px solid var(--line);
  background:var(--bg-2);
}
.lp-field{display:flex;flex-direction:column;gap:4px;min-width:0}
.lp-field.lp-span2{grid-column:span 2}
.lp-field label{
  font-family:'JetBrains Mono',monospace;font-size:9px;
  color:var(--ink-faint);letter-spacing:.15em;text-transform:uppercase;
}
.lp-field input, .lp-field select{
  background:var(--bg);border:1px solid var(--line);color:var(--ink);
  font-family:'JetBrains Mono',monospace;font-size:12px;padding:8px 10px;outline:none;
}
.lp-field input:focus, .lp-field select:focus{border-color:var(--accent)}

.lp-results{overflow-y:auto;padding:0 28px;flex:1 1 auto;min-height:200px;max-height:50vh}
.lp-results .lp-empty{padding:48px 16px;text-align:center;color:var(--ink-dim);
  font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:.1em}
.lp-row{
  display:grid;grid-template-columns:90px minmax(0,1fr) minmax(0,1fr) minmax(0,1fr) 80px;
  gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid var(--line);cursor:pointer;
}
.lp-row:hover{background:var(--bg-2)}
.lp-row .lp-time{font-family:'JetBrains Mono',monospace;font-feature-settings:'tnum';
  font-size:18px;font-weight:500;color:var(--accent)}
.lp-row .lp-meta{display:flex;flex-direction:column;gap:1px;min-width:0}
.lp-row .lp-meta .k{font-family:'JetBrains Mono',monospace;font-size:9px;
  color:var(--ink-faint);letter-spacing:.1em;text-transform:uppercase}
.lp-row .lp-meta .v{font-size:13px;color:var(--ink);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lp-row .lp-meta .v.dim{color:var(--ink-dim);font-style:italic}
/* v22.4 — Per-role channel-status icons in the lap-picker row (Datenviewer).
   One inline SVG per registry role, grey if not assigned, green if
   assigned. SVGs use currentColor so we only switch `color:` on the
   wrapper. Tooltip on the wrapper shows the role label. Matches the
   exact same scheme used by the Coach picker. */
.lp-row .lp-ch-dots{
  display:inline-flex;gap:5px;margin-top:6px;
  align-items:center;line-height:1;
}
.lp-row .lp-ch-icon-wrap{
  display:inline-flex;width:14px;height:14px;line-height:1;
}
.lp-row .lp-ch-icon-wrap .ch-icon{
  width:14px;height:14px;display:block;
}
.lp-row .lp-ch-icon-wrap.off{color:#6a6a6a}
.lp-row .lp-ch-icon-wrap.on {color:#3aff7a}
.lp-row .lp-no{font-family:'JetBrains Mono',monospace;font-size:11px;
  color:var(--ink-dim);letter-spacing:.1em;text-align:right}

.lp-foot{
  padding:14px 28px;border-top:1px solid var(--line);background:var(--bg-2);
  display:flex;justify-content:space-between;align-items:center;
  font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-faint);
  letter-spacing:.1em;text-transform:uppercase;
}

/* Upload panel */
.lp-upload-form{padding:28px;display:flex;flex-direction:column;gap:20px;flex:1 1 auto;min-height:0;overflow-y:auto}
.lp-upload-drop{
  border:2px dashed var(--line);padding:32px;text-align:center;
  display:flex;flex-direction:column;gap:8px;cursor:pointer;
  transition:border-color .15s,background .15s;
}
.lp-upload-drop:hover{border-color:var(--accent);background:var(--bg-2)}
.lp-upload-drop.has-file{border-color:var(--accent);background:rgba(0,212,255,.05)}
.lp-upload-icon{font-size:48px;color:var(--accent);line-height:1}
.lp-upload-title{font-family:'Bebas Neue',sans-serif;font-size:24px;letter-spacing:.05em}
.lp-upload-hint{font-family:'JetBrains Mono',monospace;font-size:10px;
  color:var(--ink-faint);letter-spacing:.1em}
.lp-upload-drop input[type="file"]{display:none}
.lp-upload-name{
  font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--accent);
  margin-top:8px;word-break:break-all;
}
.lp-lapchoice-status{font-family:'JetBrains Mono',monospace;font-size:11px;
  letter-spacing:.1em;color:#a0a0a0;padding:10px 4px}
.lp-lapchoice .k{font-family:'JetBrains Mono',monospace;font-size:10px;
  letter-spacing:.15em;color:#888;text-transform:uppercase;margin-bottom:8px}
.lp-lapchoice-list{display:flex;flex-direction:column;border-top:1px solid #262626;
  max-height:min(260px,32vh);overflow-y:auto}
.lp-lc-row{display:grid;grid-template-columns:110px 1fr 24px;gap:12px;
  align-items:center;padding:10px 8px;border-bottom:1px solid #262626;
  cursor:pointer}
.lp-lc-row:hover{background:#141414}
.lp-lc-row.selected{background:#0a2128}
.lp-lc-time{font-family:'JetBrains Mono',monospace;font-feature-settings:'tnum';
  font-size:16px;color:#f5f5f0;font-weight:500}
.lp-lc-row.selected .lp-lc-time{color:var(--lp-accent,#00d4ff)}
.lp-lc-sub{font-family:'JetBrains Mono',monospace;font-size:11px;color:#888;
  letter-spacing:.1em}
.lp-lc-badge{color:var(--lp-accent,#00d4ff);font-size:14px;text-align:center}
/* v23.16 — Picker-Modal auf Phone: Modal randlos, Bibliotheksliste als
   2-Spalten-Karte statt 5-Spalten-Grid, größere Tap-Flächen. */
@media (max-width:640px){
  .lp-modal{padding:8px}
  .lp-modal-box{max-height:calc(100dvh - 16px)}
  .lp-modal-head{padding:14px 16px}
  .lp-tabs{padding:10px 12px 0}
  .lp-prefilter{padding:10px 16px}
  .lp-results{padding:0 16px;max-height:none}
  .lp-filter{grid-template-columns:1fr 1fr;padding:12px 16px}
  .lp-field input,.lp-field select{font-size:16px}
  .lp-row{
    grid-template-columns:minmax(0,1fr) auto;
    grid-auto-rows:auto;gap:2px 12px;padding:12px 0;
  }
  .lp-row .lp-time{grid-column:1;font-size:20px}
  .lp-row .lp-no{grid-column:2;grid-row:1;text-align:right}
  .lp-row .lp-meta{grid-column:1 / -1}
  .lp-upload-form{padding:16px}
  .lp-upload-drop{padding:20px 12px}
}

.lp-upload-options{display:flex;gap:16px;flex-wrap:wrap}
.lp-upload-opt{display:flex;flex-direction:column;gap:6px}
.lp-upload-opt .k{font-family:'JetBrains Mono',monospace;font-size:10px;
  color:var(--ink-faint);letter-spacing:.15em;text-transform:uppercase}
.lp-upload-opt input{
  background:var(--bg-2);border:1px solid var(--line);color:var(--ink);
  font-family:'JetBrains Mono',monospace;font-size:13px;padding:8px 10px;
  width:120px;outline:none;
}
.lp-upload-opt input:focus{border-color:var(--accent)}
.lp-upload-actions{display:flex;justify-content:flex-end;padding-top:8px;
  border-top:1px solid var(--line);position:sticky;bottom:0;
  background:var(--bg);padding-bottom:4px;margin-top:auto}
.lp-upload-submit{
  font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:.05em;
  background:var(--accent);color:#000;border:none;padding:12px 28px;cursor:pointer;
}
.lp-upload-submit:hover{background:#1ee4ff}
{{TILE_SPINNER_CSS}}
</style>

<!-- v21.46 — Geteiltes Chart-Modul (Section 02 nutzt die Factory) -->
<script src="/static/speed_chart.js"></script>

<script>
const DATA = {{DATA_JSON}};

{{TILE_PROVIDER_JS}}

{{TILE_HELPERS_JS}}
// v20.4: expose DATA on window so the picker can read the current
// lap's track for pre-filtering (the picker IIFE has its own scope).
window.DATA = DATA;

// ============================================================================
// v20.1 — Lap-picker modal: load any lap from the library, or upload a file,
// without leaving the SPA. Wired once, regardless of DATA state.
// ============================================================================
(function lapPicker(){
  const modal = document.getElementById('lp-modal');
  const btnOpen = document.getElementById('btn-load-lap');
  const btnClose = document.getElementById('lp-modal-close');
  if (!modal || !btnOpen) return;

  // Tab switching
  const tabs = modal.querySelectorAll('.lp-tab');
  tabs.forEach(t => t.addEventListener('click', () => {
    tabs.forEach(x => x.classList.toggle('active', x === t));
    const key = t.dataset.lpTab;
    document.getElementById('lp-panel-library').hidden = (key !== 'library');
    document.getElementById('lp-panel-upload').hidden  = (key !== 'upload');
  }));

  function openModal(){
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    // v20.4: pre-fill track filter from currently-loaded lap so the
    // user, when picking another lap, sees same-track laps first.
    const trackSel = document.getElementById('lp-f-track');
    const pfBar = document.getElementById('lp-prefilter');
    const pfVal = document.getElementById('lp-pf-track');
    // eslint-disable-next-line no-undef
    const curTrack = (window.DATA && window.DATA.header && window.DATA.header.track) || '';
    if (curTrack && curTrack !== '—'){
      pfBar.hidden = false;
      pfVal.textContent = curTrack;
      trackSel.dataset.prefilled = curTrack;
    } else {
      pfBar.hidden = true;
      delete trackSel.dataset.prefilled;
    }
    loadLapsDebounced(true);
    setTimeout(() => document.getElementById('lp-f-search')?.focus(), 30);
  }
  function closeModal(){
    modal.hidden = true;
    document.body.style.overflow = '';
  }
  btnOpen.addEventListener('click', openModal);
  btnClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', (e) => {
    if (!modal.hidden && e.key === 'Escape') closeModal();
  });

  // Filters — debounced reload
  let loadDebounce = null, distinctLoaded = false;
  // v22.4 — Cached channel-role registry for the per-row status icons.
  // Loaded once on first picker open, reused on subsequent filter changes.
  let rolesRegistry = null;
  async function loadRolesRegistry(){
    if (rolesRegistry !== null) return rolesRegistry;
    try {
      const r = await fetch('/api/channel-roles-registry');
      rolesRegistry = await r.json();
    } catch (e){ rolesRegistry = []; }
    return rolesRegistry;
  }
  function loadLapsDebounced(immediate){
    clearTimeout(loadDebounce);
    if (immediate){ loadLaps(); return; }
    loadDebounce = setTimeout(loadLaps, 200);
  }
  ['lp-f-search','lp-f-driver','lp-f-bike','lp-f-track','lp-f-max'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => loadLapsDebounced(false));
    el.addEventListener('change', () => {
      // v20.4: if user manually changes the track filter, drop the
      // prefilter pill — they took control.
      if (id === 'lp-f-track'){
        const sel = document.getElementById('lp-f-track');
        if (sel.dataset.prefilled && sel.value !== sel.dataset.prefilled){
          document.getElementById('lp-prefilter').hidden = true;
          delete sel.dataset.prefilled;
        }
      }
      loadLapsDebounced(false);
    });
  });
  // v20.4: × ENTFERNEN — drop the prefilter pill and reload
  document.getElementById('lp-pf-clear')?.addEventListener('click', () => {
    const sel = document.getElementById('lp-f-track');
    document.getElementById('lp-prefilter').hidden = true;
    delete sel.dataset.prefilled;
    sel.value = '';
    loadLapsDebounced(true);
  });

  function populateDropdown(id, values, preferred){
    const sel = document.getElementById(id);
    if (!sel) return;
    while (sel.options.length > 1) sel.remove(1);
    values.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      sel.appendChild(opt);
    });
    if (preferred){
      // v20.4: ensure prefilled track is selectable even if not yet in distinct list
      if (!values.includes(preferred)){
        const opt = document.createElement('option');
        opt.value = preferred; opt.textContent = preferred;
        sel.appendChild(opt);
      }
      sel.value = preferred;
    }
  }
  async function loadDistinct(){
    if (distinctLoaded){
      // Re-apply prefilter on subsequent opens (distinct cached)
      const trackSel = document.getElementById('lp-f-track');
      if (trackSel.dataset.prefilled) trackSel.value = trackSel.dataset.prefilled;
      return;
    }
    try {
      const r = await fetch('/api/distinct');
      const d = await r.json();
      const trackSel = document.getElementById('lp-f-track');
      const prefer = trackSel.dataset.prefilled || '';
      populateDropdown('lp-f-driver', d.driver || []);
      populateDropdown('lp-f-bike',   d.bike   || []);
      populateDropdown('lp-f-track',  d.track  || [], prefer);
      distinctLoaded = true;
    } catch (e){ /* fail open */ }
  }

  function parseTime(s){
    if (!s) return null;
    s = String(s).trim();
    if (!s) return null;
    if (s.includes(':')){
      const p = s.split(':');
      if (p.length !== 2) return null;
      const m = parseInt(p[0], 10), sec = parseFloat(p[1]);
      if (isNaN(m) || isNaN(sec)) return null;
      return m*60 + sec;
    }
    const v = parseFloat(s);
    return isNaN(v) ? null : v;
  }
  function escapeHTML(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function fmtSec(s){
    const m = Math.floor(s / 60);
    const sec = s - m*60;
    return `${m}:${sec.toFixed(3).padStart(6,'0')}`;
  }

  async function loadLaps(){
    await loadDistinct();
    await loadRolesRegistry();
    const box = document.getElementById('lp-results');
    const cnt = document.getElementById('lp-count');
    const params = new URLSearchParams();
    const s = (document.getElementById('lp-f-search')?.value || '').trim();
    const drv = (document.getElementById('lp-f-driver')?.value || '').trim();
    const bk  = (document.getElementById('lp-f-bike')?.value   || '').trim();
    const tr  = (document.getElementById('lp-f-track')?.value  || '').trim();
    const mx  = parseTime(document.getElementById('lp-f-max')?.value);
    if (s) params.set('search', s);
    if (drv) params.set('driver', drv);
    if (bk) params.set('bike', bk);
    if (tr) params.set('track', tr);
    if (mx !== null) params.set('max', mx);
    box.innerHTML = '<div class="lp-empty">LADE…</div>';
    try {
      const r = await fetch('/api/laps?' + params.toString());
      const laps = await r.json();
      cnt.textContent = laps.length + ' RUNDE' + (laps.length === 1 ? '' : 'N');
      if (!laps.length){
        box.innerHTML = '<div class="lp-empty">KEINE PASSENDEN RUNDEN GEFUNDEN.</div>';
        return;
      }
      let html = '';
      // v22.4 — Per-role status icons. One inline SVG per registry
      // role, grey if not assigned for this lap, green if assigned.
      // SVG comes from role.icon (via /api/channel-roles-registry)
      // and uses currentColor — wrapper .on/.off flips the colour.
      // Empty when the lap has no extra channels.
      function chDots(lp){
        const ex = +(lp.extras_count || 0);
        if (ex === 0) return '';
        const assigned = new Set(lp.assigned_role_ids || []);
        const parts = ['<span class="lp-ch-dots" aria-label="Standardkanal-Zuordnung">'];
        for (const role of (rolesRegistry || [])){
          const on = assigned.has(role.id);
          parts.push(
            `<span class="lp-ch-icon-wrap ${on ? 'on' : 'off'}" ` +
            `title="${escapeHTML(role.label || role.id)}">${role.icon || ''}</span>`
          );
        }
        parts.push('</span>');
        return parts.join('');
      }
      laps.forEach(lp => {
        html += `<div class="lp-row" data-lap-id="${lp.lap_id}">
          <div class="lp-time">${fmtSec(lp.duration_s)}</div>
          <div class="lp-meta"><div class="k">STRECKE · DATUM</div>
            <div class="v ${lp.track ? '' : 'dim'}">${escapeHTML(lp.track || '—')}${lp.session_date ? ' · ' + escapeHTML(lp.session_date) : ''}</div></div>
          <div class="lp-meta"><div class="k">BIKE · FAHRER</div>
            <div class="v ${lp.bike ? '' : 'dim'}">${escapeHTML(lp.bike || '—')} · ${escapeHTML(lp.driver || '—')}</div></div>
          <div class="lp-meta"><div class="k">SESSION</div>
            <div class="v" style="font-size:12px;color:var(--ink-dim);font-family:JetBrains Mono">${escapeHTML(lp.original_filename || '')}</div>
            ${chDots(lp)}</div>
          <div class="lp-no">LAP ${lp.lap_number}</div>
        </div>`;
      });
      box.innerHTML = html;
      // Click → navigate. Page-refresh re-renders with the new lap_id;
      // simpler than tearing down/rebuilding all charts in place, and
      // gives bookmarkable URLs for free.
      box.querySelectorAll('.lp-row').forEach(row => {
        row.addEventListener('click', () => {
          const id = row.dataset.lapId;
          if (id) window.location.href = '/analyze?lap_id=' + encodeURIComponent(id);
        });
      });
    } catch (e){
      box.innerHTML = '<div class="lp-empty">FEHLER BEIM LADEN: ' + escapeHTML(e.message || e) + '</div>';
    }
  }

  // Upload tab: show selected filename, otherwise just submit the form
  const fileInput = document.getElementById('lp-file-input');
  const dropZone = document.querySelector('.lp-upload-drop');
  const fileName = document.getElementById('lp-upload-name');
  if (fileInput && dropZone){
    dropZone.addEventListener('click', (e) => {
      if (e.target.tagName !== 'INPUT') fileInput.click();
    });
    fileInput.addEventListener('change', () => {
      const f = fileInput.files[0];
      if (f){
        dropZone.classList.add('has-file');
        fileName.textContent = f.name + ' · ' + (f.size/1024/1024).toFixed(2) + ' MB';
        stashAndListLaps(f);
      } else {
        dropZone.classList.remove('has-file');
        fileName.textContent = '';
        resetLapChoice();
      }
    });
  }

  // v23.12 — Zwei-Phasen-Upload: Datei sofort einlagern, Rundenliste
  // anzeigen, Auswahl als hidden fields (adhoc_token + lap) mitschicken.
  const tokenInput  = document.getElementById('lp-adhoc-token');
  const lapInput    = document.getElementById('lp-lap-choice');
  const choiceBox   = document.getElementById('lp-lapchoice');
  const choiceList  = document.getElementById('lp-lapchoice-list');
  const choiceStat  = document.getElementById('lp-lapchoice-status');
  const uploadForm  = document.getElementById('lp-upload-form');
  const submitBtn   = uploadForm ? uploadForm.querySelector('.lp-upload-submit') : null;

  function resetLapChoice(){
    if (tokenInput) tokenInput.value = '';
    if (lapInput) lapInput.value = 'auto';
    if (choiceBox) choiceBox.hidden = true;
    if (choiceList) choiceList.innerHTML = '';
    if (choiceStat){ choiceStat.hidden = true; choiceStat.textContent = ''; }
    if (submitBtn) submitBtn.disabled = false;
    if (fileInput) fileInput.disabled = false;
  }

  async function stashAndListLaps(file){
    resetLapChoice();
    if (!choiceStat) return;
    choiceStat.hidden = false;
    choiceStat.textContent = 'DATEI WIRD GEPARST …';
    if (submitBtn) submitBtn.disabled = true;
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await fetch('/api/adhoc/laps', { method: 'POST', body: fd });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.ok){
        throw new Error(data.error || ('HTTP ' + resp.status));
      }
      tokenInput.value = data.token;
      renderLapChoice(data.laps || []);
      choiceStat.hidden = true;
      if (submitBtn) submitBtn.disabled = false;
    } catch (e){
      choiceStat.textContent = 'FEHLER: ' + (e.message || e);
      if (submitBtn) submitBtn.disabled = false; // Fallback: Direkt-Upload (auto)
    }
  }

  function renderLapChoice(laps){
    if (!choiceBox || !choiceList || !laps.length) return;
    const fastest = laps[0];
    let html = `<div class="lp-lc-row selected" data-lap="auto">
      <span class="lp-lc-time">AUTO</span>
      <span class="lp-lc-sub">SCHNELLSTE · ${fastest.duration_fmt}</span>
      <span class="lp-lc-badge">✓</span>
    </div>`;
    laps.forEach(lp => {
      html += `<div class="lp-lc-row" data-lap="${lp.lap_number}">
        <span class="lp-lc-time">${lp.duration_fmt}</span>
        <span class="lp-lc-sub">LAP ${lp.lap_number}</span>
        <span class="lp-lc-badge"></span>
      </div>`;
    });
    choiceList.innerHTML = html;
    choiceBox.hidden = false;
    choiceList.querySelectorAll('.lp-lc-row').forEach(row => {
      row.addEventListener('click', () => {
        choiceList.querySelectorAll('.lp-lc-row').forEach(r => {
          r.classList.remove('selected');
          r.querySelector('.lp-lc-badge').textContent = '';
        });
        row.classList.add('selected');
        row.querySelector('.lp-lc-badge').textContent = '✓';
        lapInput.value = row.dataset.lap;
      });
    });
  }

  if (uploadForm){
    uploadForm.addEventListener('submit', () => {
      // Datei ist schon eingelagert — nicht nochmal mitschicken.
      if (tokenInput && tokenInput.value && fileInput){
        fileInput.disabled = true;
      }
    });
  }
})();

// ============================================================================
// Empty-mode detection — if no lap is loaded, swap out the chart/map
// sections for placeholder messages and skip the rest of the script.
// We use a top-level early-return-via-throw because the existing render
// JS expects DATA to be non-null in many places. The throw is caught
// silently by the browser (one console line, no UI impact).
// ============================================================================
if (DATA !== null){
  // A lap is loaded — server-rendered template already filled the lap-card.
  // Just relabel the button and reveal the AI Coach cross-link.
  const lbl = document.getElementById('btn-load-lap')?.querySelector('.bll-label');
  if (lbl) lbl.textContent = '↻ ANDERE RUNDE LADEN';
  const cl = document.getElementById('btn-cross-link');
  if (cl){
    const href = cl.getAttribute('href');
    if (href && href !== '' && href !== '{' + '{COACH_HREF}}') cl.hidden = false;
  }
  // v21.33 — VERGLEICH cross-link analogous to AI COACH.
  const cl2 = document.getElementById('btn-cross-link-compare');
  if (cl2){
    const href2 = cl2.getAttribute('href');
    if (href2 && href2 !== '' && href2 !== '{' + '{COMPARE_HREF}}') cl2.hidden = false;
  }
}
if (DATA === null){
  document.body.classList.add('empty-mode');

  // v21.1 — Empty lap-card: time "—:—.—", meta dim, button pulsing.
  const card = document.getElementById('dv-lap-card');
  if (card) card.classList.add('empty');
  const timeEl = document.getElementById('dv-lc-time');
  if (timeEl) timeEl.textContent = '—:—.—';
  for (const [id, val] of Object.entries({
      'dv-lc-track':'—','dv-lc-lapno':'—','dv-lc-bike':'—','dv-lc-driver':'—'})){
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }
  const btn = document.getElementById('btn-load-lap');
  if (btn){
    const lbl = btn.querySelector('.bll-label');
    if (lbl) lbl.textContent = '+ RUNDE WÄHLEN';
  }
  // Cross-Link stays hidden by default; no-op.

  // Replace chart/map containers with placeholders
  const swap = (id, label) => {
    const el = document.getElementById(id);
    if (!el) return;
    const ph = document.createElement('div');
    ph.className = 'empty-placeholder';
    ph.innerHTML = '<div class="ep-icon">∅</div>'
                 + '<div>' + label + '</div>'
                 + '<div class="ep-hint">→ KLICK „+ RUNDE WÄHLEN“ OBEN</div>';
    el.parentNode.replaceChild(ph, el);
  };
  swap('track-map',   'KEINE STRECKE GELADEN');
  swap('speed-chart', 'KEINE DATEN');

  // Stop here — the rest of the script touches DATA.* and would crash.
  // (Browser will log "Uncaught EmptyMode" once. Harmless.)
  throw new Error('EmptyMode');
}

// ============================================================================
// Shared cursor state
// ============================================================================
const cursorInfo = document.getElementById('cursor-info');
const ciDist  = document.getElementById('ci-dist');
const ciTime  = document.getElementById('ci-time');
const ciSpeed = document.getElementById('ci-speed');
const ciExtras = document.getElementById('ci-extras');
const ciHint = document.getElementById('ci-hint');

let currentIdx = -1;
let stickyIdx = -1;

function fmtTime(s){
  if (s == null || !isFinite(s)) return '—';
  const m = Math.floor(s / 60);
  const sec = s - m*60;
  return `${m}:${sec.toFixed(2).padStart(5,'0')}`;
}

// Format a number with sensible precision based on its magnitude
function fmtChannelValue(v){
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

// Lap-summary helpers — cached on first use
let _lapMeanSpeed = null;
function lapMeanSpeed(){
  if (_lapMeanSpeed != null) return _lapMeanSpeed;
  let s = 0, n = 0;
  for (let i = 0; i < DATA.speed.length; i++){
    if (isFinite(DATA.speed[i])){ s += DATA.speed[i]; n++; }
  }
  _lapMeanSpeed = n ? (s/n) : 0;
  return _lapMeanSpeed;
}
function lapTotalDistance(){ return DATA.distance[DATA.distance.length-1]; }
function lapTotalTime(){ return DATA.time[DATA.time.length-1]; }

function updateInfoBox(idx){
  // Pull the list of active extras from speedChart so we know which to show.
  const active = (typeof speedChart !== 'undefined' && speedChart.getActiveExtras)
                  ? speedChart.getActiveExtras() : [];
  const spOn = (typeof speedChart !== 'undefined' && speedChart.isSpeedActive)
                  ? speedChart.isSpeedActive() : true;

  if (idx < 0 || idx >= DATA.distance.length){
    // No cursor — show LAP SUMMARY (means / totals)
    ciDist.textContent = `${(lapTotalDistance()/1000).toFixed(3)} km`;
    ciDist.classList.add('muted');
    ciTime.textContent = fmtTime(lapTotalTime());
    ciTime.classList.add('muted');
    ciSpeed.textContent = `Ø ${lapMeanSpeed().toFixed(1)} km/h`;
    ciSpeed.classList.add('muted');
    ciSpeed.style.opacity = spOn ? '' : '0.45';
    if (ciHint) ciHint.textContent = 'Ø-WERTE FÜR DIE RUNDE · Hover über Map/Chart für Cursor-Werte';

    // Per-channel means (already pre-computed server-side as ch.mean)
    let extraHtml = '';
    active.forEach(ch => {
      extraHtml += `<div class="cell">
        <div class="k" style="color:${ch.color}">${ch.name}${ch.unit?(' ('+ch.unit+')'):''}</div>
        <div class="v muted">Ø ${fmtChannelValue(ch.mean)}</div>
      </div>`;
    });
    ciExtras.innerHTML = extraHtml;
    return;
  }

  // Cursor active — show values AT the cursor position
  ciDist.textContent = `${(DATA.distance[idx]/1000).toFixed(3)} km`;
  ciDist.classList.remove('muted');
  ciTime.textContent = fmtTime(DATA.time[idx]);
  ciTime.classList.remove('muted');
  ciSpeed.textContent = `${DATA.speed[idx].toFixed(1)} km/h`;
  ciSpeed.classList.remove('muted');
  ciSpeed.style.opacity = spOn ? '' : '0.45';
  if (ciHint){
    ciHint.textContent = (stickyIdx >= 0)
      ? 'MARKER FEST · ESC oder erneut klicken → lösen'
      : 'CURSOR-POSITION · Klick: Marker fest setzen';
  }

  let extraHtml = '';
  active.forEach(ch => {
    const v = ch.data[idx];
    extraHtml += `<div class="cell">
      <div class="k" style="color:${ch.color}">${ch.name}${ch.unit?(' ('+ch.unit+')'):''}</div>
      <div class="v">${fmtChannelValue(v)}</div>
    </div>`;
  });
  ciExtras.innerHTML = extraHtml;
}

function setCursor(idx, sticky){
  if (sticky === true) stickyIdx = idx;
  if (sticky === false) stickyIdx = -1;
  currentIdx = idx;
  updateInfoBox(idx);
  trackMap.drawCursor(idx);
  speedChart.drawCursor(idx);
}

function clearLiveCursor(){
  if (stickyIdx >= 0) setCursor(stickyIdx, undefined);
  else {
    currentIdx = -1;
    updateInfoBox(-1);
    trackMap.drawCursor(-1);
    speedChart.drawCursor(-1);
  }
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && stickyIdx >= 0){
    stickyIdx = -1;
    clearLiveCursor();
  }
});

// ============================================================================
// Track map (with selectable color channel)
// ============================================================================
const trackMap = (function(){
  const svg = document.getElementById('track-map');
  const W = 1200, H = 600, PAD = 40;

  const lat = DATA.lat, lon = DATA.lon;
  const latMin = Math.min(...lat), latMax = Math.max(...lat);
  const lonMin = Math.min(...lon), lonMax = Math.max(...lon);
  const latRange = latMax - latMin, lonRange = lonMax - lonMin;
  const cosLat = Math.cos((latMin+latMax)/2 * Math.PI/180);
  const wMeters = lonRange * 111000 * cosLat;
  const hMeters = latRange * 111000;
  const aspectMap = hMeters > 0 ? wMeters/hMeters : 1;
  const aspectVp = (W - 2*PAD)/(H - 2*PAD);
  let scaleX, scaleY, ox, oy;
  if (aspectMap > aspectVp){
    scaleX = (W - 2*PAD)/lonRange;
    scaleY = scaleX / cosLat;
    ox = PAD;
    oy = PAD + ((H - 2*PAD) - latRange*scaleY)/2;
  } else {
    scaleY = (H - 2*PAD)/latRange;
    scaleX = scaleY * cosLat;
    oy = PAD;
    ox = PAD + ((W - 2*PAD) - lonRange*scaleX)/2;
  }
  const proj = (la, lo) => ({
    x: ox + (lo - lonMin)*scaleX,
    y: oy + (latMax - la)*scaleY
  });

  // ----- Color sources -----
  // The default 'accel' source uses DATA.accel_norm (already in [-1, 1]).
  // Other sources use raw channel data — we auto-detect "diverging vs
  // sequential" from the value range: if min<0<max and the magnitudes are
  // roughly balanced, treat it as diverging (zero is the neutral midpoint
  // and we use the green/red palette). Otherwise sequential (low→high).
  const ACCEL_SOURCE = {
    id: 'accel',
    name: 'Längsbeschleunigung',
    unit: 'g',
    isDiverging: true,
    values: DATA.accel_norm,
    min: -1, max: 1,
  };

  function makeSource(extra){
    const arr = extra.data;
    const mn = extra.min, mx = extra.max;
    // Diverging if it straddles zero with reasonable balance
    const isDiv = (mn < -0.05 && mx > 0.05 && Math.min(-mn, mx) > Math.max(-mn, mx) * 0.15);
    return {
      id: extra.id, name: extra.name, unit: extra.unit,
      isDiverging: isDiv,
      values: arr,
      min: mn, max: mx,
    };
  }
  const trackSources = [ACCEL_SOURCE, ...(DATA.extras || []).map(makeSource)];
  let currentSource = ACCEL_SOURCE;

  // Color mapping
  function colorDiverging(v, src){
    // Normalize to [-1, 1] within the symmetric range
    const m = Math.max(-src.min, src.max);
    if (m <= 0) return 'rgb(110,110,110)';
    const a = Math.max(-1, Math.min(1, v / m));
    if (a > 0.05){
      const t = Math.min(1, a);
      const g = Math.round(120 + t * 135);
      return `rgb(40, ${g}, ${Math.round(80 - t * 30)})`;
    }
    if (a < -0.05){
      const t = Math.min(1, -a);
      const r = Math.round(180 + t * 75);
      return `rgb(${r}, ${Math.round(60 - t * 40)}, ${Math.round(60 - t * 40)})`;
    }
    return 'rgb(110, 110, 110)';
  }
  function colorSequential(v, src){
    const span = src.max - src.min;
    if (span <= 0) return 'rgb(110,110,110)';
    const t = Math.max(0, Math.min(1, (v - src.min) / span));
    // Cyan → magenta gradient (low → high), passing through purple
    const r = Math.round( 40 + t * 215);
    const g = Math.round(210 - t * 170);
    const b = Math.round(255 - t * 100);
    return `rgb(${r}, ${g}, ${b})`;
  }
  function colorFor(v, src){
    if (!Number.isFinite(v)) return 'rgb(70,70,70)';
    return src.isDiverging ? colorDiverging(v, src) : colorSequential(v, src);
  }

  // v21.22 — Trackmap-Modus: 'color' (Farbkanal, dicke gefärbte Linie) oder
  // 'line' (Fahrlinie, eine dünne Linie in Rundenfarbe = --accent / cyan).
  // v21.23 — Mapview: optionaler Satelliten-Hintergrund (Esri World Imagery).
  // v21.24 — Tile-Helfer + Spinner + Zoom/Pan kommen aus der zentralen Helper-Lib.
  let mode = 'color';

  const _latMin = Math.min.apply(null, lat), _latMax = Math.max.apply(null, lat);
  const _lonMin = Math.min.apply(null, lon), _lonMax = Math.max.apply(null, lon);

  const tile = makeTileLayer({
    svg, W: 1200, H: 600, proj,
    latMin: _latMin, latMax: _latMax,
    lonMin: _lonMin, lonMax: _lonMax,
    padding: 0.10,
  });
  const mapWrap = svg.parentElement;

  function render(){
    const N = lat.length;
    let html = '';
    if (tile.active) html += tile.buildLayer();
    if (mode === 'line'){
      // Eine dünne Linie in der Rundenfarbe (Single-Lap = --accent).
      let path = '';
      for (let i = 0; i < N; i++){
        const p = proj(lat[i], lon[i]);
        path += (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
      }
      html += `<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
    } else {
      const src = currentSource;
      const values = src.values || [];
      for (let i = 1; i < N; i++){
        const p1 = proj(lat[i-1], lon[i-1]);
        const p2 = proj(lat[i], lon[i]);
        const v = values[i];
        html += `<line x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${p2.x.toFixed(1)}" y2="${p2.y.toFixed(1)}" stroke="${colorFor(v, src)}" stroke-width="6" stroke-linecap="round"/>`;
      }
    }
    const p0 = proj(lat[0], lon[0]);
    html += `<g>
      <circle cx="${p0.x}" cy="${p0.y}" r="9" fill="none" stroke="#fff" stroke-width="2"/>
      <circle cx="${p0.x}" cy="${p0.y}" r="3" fill="#fff"/>
      <text x="${p0.x+14}" y="${p0.y+4}" font-family="JetBrains Mono" font-size="11" fill="#fff" letter-spacing="1">START</text>
    </g>`;
    html += `<g id="track-cursor"></g>`;
    svg.innerHTML = html;
    updateLegend();
    // v21.24 — Spinner während Tile-Load
    if (tile.active) tile.bindLoadEvents(mapWrap);
    else tile.hideSpinner();
  }

  function setMode(newMode){
    if (newMode !== 'color' && newMode !== 'line') return;
    if (newMode === mode) return;
    mode = newMode;
    render();
    if (stickyIdx >= 0) drawCursor(stickyIdx);
  }

  function setMapview(on){
    on = !!on;
    if (on === tile.active) return;
    tile.active = on;
    render();
    if (stickyIdx >= 0) drawCursor(stickyIdx);
  }

  function updateLegend(){
    const src = currentSource;
    const cur = document.getElementById('track-color-current');
    if (cur) cur.textContent = src.name + (src.unit ? ` (${src.unit})` : '');
    const lbl = document.getElementById('track-color-label');
    if (lbl){
      // v21.22 — Im FAHRLINIE-Modus zeigt die Label-Überschrift den aktiven Modus.
      lbl.textContent = (mode === 'line') ? 'MODUS = FAHRLINIE' : 'FARBE = ' + (src.name || '').toUpperCase();
    }
    const legend = document.getElementById('track-legend');
    if (!legend) return;
    if (src.isDiverging){
      legend.innerHTML = `
        <div><span class="legend-swatch" style="background:linear-gradient(90deg,#103,#3aff7a)"></span>HOCH (+)</div>
        <div><span class="legend-swatch" style="background:#666"></span>NULL</div>
        <div><span class="legend-swatch" style="background:linear-gradient(90deg,#666,#ff3d3d)"></span>TIEF (−)</div>
      `;
    } else {
      const lo = src.min.toFixed(1), hi = src.max.toFixed(1);
      legend.innerHTML = `
        <div><span class="legend-swatch" style="background:linear-gradient(90deg,rgb(40,210,255),rgb(255,40,155))"></span>${lo} → ${hi}${src.unit ? ' ' + src.unit : ''}</div>
      `;
    }
  }

  function drawCursor(idx){
    const cursorG = document.getElementById('track-cursor');
    if (!cursorG) return;
    if (idx < 0 || idx >= lat.length){ cursorG.innerHTML = ''; return; }
    const p = proj(lat[idx], lon[idx]);
    cursorG.innerHTML = `
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="9" fill="none" stroke="#fff" stroke-width="2.5"/>
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3" fill="#fff"/>
    `;
  }

  function findIndexFromEvent(evt){
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return -1;
    const local = pt.matrixTransform(ctm.inverse());
    const N = lat.length;
    let bestI = -1, bestD = 1e18;
    for (let i = 0; i < N; i++){
      const p = proj(lat[i], lon[i]);
      const dx = p.x - local.x, dy = p.y - local.y;
      const d = dx*dx + dy*dy;
      if (d < bestD){ bestD = d; bestI = i; }
    }
    return bestI;
  }

  svg.addEventListener('mousemove', (e) => {
    if (stickyIdx >= 0) return;
    const i = findIndexFromEvent(e);
    if (i >= 0) setCursor(i, undefined);
  });
  svg.addEventListener('mouseleave', () => { if (stickyIdx < 0) clearLiveCursor(); });
  svg.addEventListener('click', (e) => {
    if (zoomCtl && zoomCtl.didDrag()) return;
    const i = findIndexFromEvent(e);
    if (i < 0) return;
    if (stickyIdx === i) setCursor(-1, false);
    else setCursor(i, true);
  });

  // v21.24 — Zoom/Pan
  const zoomCtl = makeZoomPan({ svg, W: 1200, H: 600, minZoom: 1, maxZoom: 8 });

  render();

  // ----- Track-color picker modal -----
  const tcModal = document.getElementById('tc-modal');
  const tcTbody = document.getElementById('tc-table-body');
  const tcSearch = document.getElementById('tc-search');
  const btnTcOpen = document.getElementById('btn-pick-track-color');
  const btnTcClose = document.getElementById('tc-modal-close');
  const btnTcApply = document.getElementById('tc-apply');

  // Hide the picker if there are NO extras (then only "accel" is available
  // and there's nothing to pick anyway)
  if (!DATA.extras || DATA.extras.length === 0){
    if (btnTcOpen) btnTcOpen.style.display = 'none';
  }

  function tcBuildTable(query){
    query = (query || '').toLowerCase();
    const filtered = trackSources.filter(s =>
      !query || (s.name + ' ' + (s.unit||'')).toLowerCase().includes(query)
    );
    if (!filtered.length){
      tcTbody.innerHTML = '<div class="ch-empty">KEINE TREFFER</div>';
      return;
    }
    let rows = '';
    filtered.forEach(src => {
      const isCurrent = (src.id === currentSource.id);
      const mn = (src.min != null) ? src.min.toFixed(2) : '—';
      const mx = (src.max != null) ? src.max.toFixed(2) : '—';
      // Mean — we don't have it for accel, fake "0"
      let mean = '—';
      const ex = (DATA.extras || []).find(e => e.id === src.id);
      if (ex) mean = ex.mean.toFixed(2);
      else if (src.id === 'accel') mean = '0.00';
      rows += `<label class="ch-row ${isCurrent?'active':''}" data-id="${src.id}">
        <span class="ch-col-on"><input type="radio" name="tc-pick" data-id="${src.id}" ${isCurrent?'checked':''}></span>
        <span class="ch-col-name">${src.name}</span>
        <span class="ch-col-unit">${src.unit || '—'}</span>
        <span class="ch-col-min">${mn}</span>
        <span class="ch-col-max">${mx}</span>
        <span class="ch-col-mean">${mean}</span>
      </label>`;
    });
    tcTbody.innerHTML = rows;
  }

  function tcOpen(){
    tcBuildTable(tcSearch.value || '');
    tcModal.hidden = false;
    setTimeout(() => tcSearch.focus(), 0);
  }
  function tcClose(){ tcModal.hidden = true; }

  if (btnTcOpen) btnTcOpen.addEventListener('click', tcOpen);
  btnTcClose.addEventListener('click', tcClose);
  btnTcApply.addEventListener('click', tcClose);
  tcModal.addEventListener('click', (e) => { if (e.target === tcModal) tcClose(); });
  document.addEventListener('keydown', (e) => {
    if (!tcModal.hidden && e.key === 'Escape') tcClose();
  });
  tcSearch.addEventListener('input', () => tcBuildTable(tcSearch.value));
  tcTbody.addEventListener('change', (e) => {
    const r = e.target;
    if (!r.matches('input[type="radio"]')) return;
    const id = r.dataset.id;
    const src = trackSources.find(s => s.id === id);
    if (!src) return;
    currentSource = src;
    // Refresh row highlight
    tcTbody.querySelectorAll('.ch-row').forEach(rw => {
      rw.classList.toggle('active', rw.dataset.id === id);
    });
    render();
    if (stickyIdx >= 0) drawCursor(stickyIdx);
  });

  return { drawCursor, setMode, setMapview };
})();

// v21.22 — Trackmap-Modus-Toggle (FARBKANAL | FAHRLINIE)
// v21.23 — Mapview-Toggle (Esri World Imagery)
// v21.25 — Mapview als single-button (vorher zwei-Optionen seg-switch)
(function(){
  const btnColor = document.getElementById('tm-mode-color');
  const btnLine  = document.getElementById('tm-mode-line');
  const toolbar  = document.getElementById('track-toolbar');
  const btnBg    = document.getElementById('tm-bg-toggle');
  if (!btnColor || !btnLine) return;
  function applyMode(modeName){
    trackMap.setMode(modeName);
    const isColor = (modeName === 'color');
    btnColor.classList.toggle('active', isColor);
    btnColor.setAttribute('aria-selected', isColor ? 'true' : 'false');
    btnLine.classList.toggle('active', !isColor);
    btnLine.setAttribute('aria-selected', !isColor ? 'true' : 'false');
    if (toolbar) toolbar.classList.toggle('line-mode', !isColor);
  }
  function applyBg(on){
    trackMap.setMapview(on);
    if (btnBg){
      btnBg.classList.toggle('active', on);
      btnBg.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    const attr = document.getElementById('tm-attribution');
    if (attr) attr.style.display = on ? '' : 'none';
  }
  btnColor.addEventListener('click', () => applyMode('color'));
  btnLine.addEventListener('click',  () => applyMode('line'));
  if (btnBg){
    btnBg.addEventListener('click', () => {
      applyBg(!btnBg.classList.contains('active'));
    });
  }
})();


// ============================================================================
// v21.46 — Speed + extras chart over /static/speed_chart.js factory.
// External API stays the same (drawCursor / getActiveExtras / isSpeedActive),
// so the existing setCursor/clearLiveCursor/updateInfoBox call sites work
// without changes. Cursor sync into the chart is fed by setCursor(); the
// factory pushes back via onCursor/onClearLive when the user interacts with
// the chart itself.
// ============================================================================
const speedChart = window.createSpeedChart({
  data: {
    distance: DATA.distance,
    speed:    DATA.speed,
    extras:   DATA.extras || [],
    speedUnit: 'km/h',
  },
  ids: {
    svg:     'speed-chart',
    legend:  'chart-legend',
    badge:   'active-chan-count',
    zoomBtn: 'btn-zoom-reset',
    picker: {
      btnOpen:  'btn-pick-channels',
      modal:    'ch-modal',
      body:     'ch-table-body',
      hint:     'ch-modal-hint',
      search:   'ch-search',
      btnClose: 'ch-modal-close',
      btnApply: 'ch-apply',
      btnClear: 'ch-clear',
    },
  },
  // Datenviewer-Default: keine Extras vorgewählt, Speed an.
  initialActiveExtraIds: [],
  initialSpeedActive: true,
  cursorMode: 'external',
  onCursor: (idx, sticky) => setCursor(idx, sticky),
  onClearLive: () => clearLiveCursor(),
  onChannelChange: () => updateInfoBox(currentIdx),
  externalStickyIdx: () => stickyIdx,
});


// Initial render of the info box with the lap summary (no cursor yet)
updateInfoBox(-1);

</script>
</body>
</html>
"""
