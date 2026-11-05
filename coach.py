"""coach — AI Analyse und Coach SPA.

A second single-lap SPA, like the Datenviewer (report_single.py), but
focused on the analytical / coaching layer:

  - Tab "Basis · Speed": assessment headline + per-phase pills,
    core-stats cards, brake-table, accel-table.
  - Tab "Fortgeschritten · Bremsen": role-assignment + COMING-SOON.
  - Tab "Fortgeschritten · Beschleunigen": role-assignment + COMING-SOON.

Public API mirrors report_single:
  - compute_coach_payload(track, lap_meta, lap_data)  -> dict
  - build_coach_html(track, lap_meta, lap_data)       -> HTML
  - build_coach_empty_html()                          -> HTML for empty SPA

The payload is the SAME shape that compute_single_lap_payload produces,
so future "AI" features can ingest the existing analysis dict directly.

Cross-link conventions (v20.3):
  - The header carries a "→ DATENVIEWER" link when a lap is loaded,
    pointing at /analyze?lap_id=N for the same lap.
  - The Datenviewer template carries a matching "→ AI COACH" link
    pointing at /coach?lap_id=N.

This file lives next to report_single.py so they can share helpers if
needed in the future; for now the templates are independent on purpose
(easier to evolve each SPA without breaking the other).
"""
from __future__ import annotations

import json
from typing import Any, Dict

# Re-use the data-shaping work already done by report_single.
# The payload format is identical; we just present a different slice.
from report_single import compute_single_lap_payload, _fmt_lap
from trackmap_helpers import (
    TILE_HELPERS_JS as _TILE_HELPERS_JS,
    TILE_SPINNER_CSS as _TILE_SPINNER_CSS,
    tile_provider_js as _tile_provider_js,
    tile_provider_button_class as _tile_btn_cls,
)


def compute_coach_payload(*, track, lap_meta, lap_data) -> Dict[str, Any]:
    """Same payload shape as the Datenviewer.

    Kept as a separate symbol so future Coach-specific fields can be added
    without touching the Datenviewer payload contract.
    """
    return compute_single_lap_payload(
        track=track, lap_meta=lap_meta, lap_data=lap_data,
    )


def build_coach_html(*, track, lap_meta, lap_data,
                     title_extra: str = "",
                     viewer_href: str = "",
                     maptiler_key: str = "") -> str:
    """Render the full AI-Coach SPA with data for one lap.

    viewer_href: optional URL to the Datenviewer for the same lap (v20.3).
                 If non-empty, a cross-link button appears in the header.
    """
    payload = compute_coach_payload(
        track=track, lap_meta=lap_meta, lap_data=lap_data,
    )
    data_json = json.dumps(payload, separators=(",", ":"))
    # v22.10 — Detector thresholds embedded into the page. Single JSON
    # blob next to DATA so the JS detectors can read them via
    # window.THRESHOLDS without needing a second HTTP request.
    from thresholds import get_thresholds
    thresholds_json = json.dumps(get_thresholds(), separators=(",", ":"))
    h = payload["header"]
    return _PAGE_TEMPLATE.replace("{{DATA_JSON}}", data_json) \
        .replace("{{THRESHOLDS_JSON}}", thresholds_json) \
        .replace("{{LAP_TIME}}", h["lap_time"]) \
        .replace("{{LAP_NO}}", h["lap_no"]) \
        .replace("{{DRIVER}}", h["driver"]) \
        .replace("{{BIKE}}", h["bike"]) \
        .replace("{{TRACK}}", h["track"]) \
        .replace("{{SRC}}", h["src"]) \
        .replace("{{TITLE_EXTRA}}", title_extra) \
        .replace("{{VIEWER_HREF}}", viewer_href) \
        .replace("{{TILE_HELPERS_JS}}", _TILE_HELPERS_JS) \
        .replace("{{TILE_SPINNER_CSS}}", _TILE_SPINNER_CSS) \
        .replace("{{TILE_PROVIDER_JS}}", _tile_provider_js(maptiler_key)) \
        .replace("{{TM_BG_BTN_CLS}}", _tile_btn_cls(maptiler_key))


def build_coach_empty_html(*, title_extra: str = "", maptiler_key: str = "") -> str:
    """The Coach SPA shell, no lap loaded yet."""
    from thresholds import get_thresholds
    thresholds_json = json.dumps(get_thresholds(), separators=(",", ":"))
    return _PAGE_TEMPLATE.replace("{{DATA_JSON}}", "null") \
        .replace("{{THRESHOLDS_JSON}}", thresholds_json) \
        .replace("{{LAP_TIME}}", "—:—.—") \
        .replace("{{LAP_NO}}", "—") \
        .replace("{{DRIVER}}", "—") \
        .replace("{{BIKE}}", "—") \
        .replace("{{TRACK}}", "—") \
        .replace("{{SRC}}", "keine Runde geladen") \
        .replace("{{TITLE_EXTRA}}", title_extra) \
        .replace("{{VIEWER_HREF}}", "") \
        .replace("{{TILE_HELPERS_JS}}", _TILE_HELPERS_JS) \
        .replace("{{TILE_SPINNER_CSS}}", _TILE_SPINNER_CSS) \
        .replace("{{TILE_PROVIDER_JS}}", _tile_provider_js(maptiler_key)) \
        .replace("{{TM_BG_BTN_CLS}}", _tile_btn_cls(maptiler_key))


_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Analyse und Coach · {{TITLE_EXTRA}}</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0a0a0a; --bg-2:#141414;
  --ink:#f5f5f0; --ink-dim:#a0a0a0; --ink-faint:#888;
  --line:#262626;
  --accel:#3aff7a;   /* green for accelerating */
  --brake:#ff3d3d;   /* red for braking */
  /* v21.10 — Coach durchgängig lila statt cyan. */
  --accent:#c77dff;
  --accent-hover:#d18fff;
  --accent-glow:rgba(199,125,255,.12);
  --accent-glow-strong:rgba(199,125,255,.35);
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:var(--bg);color:var(--ink);font-family:'Space Grotesk',sans-serif;line-height:1.5;min-height:100vh}
.mono{font-family:'JetBrains Mono',monospace;font-feature-settings:'tnum'}
.page{max-width:1280px;margin:0 auto;padding:48px 32px 80px}

/* v21.1 — Header: normal page heading (eyebrow + h1). Lap-card below. */
header{
  padding-bottom:24px;margin-bottom:0;
}
.eyebrow{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.2em;color:var(--ink-dim);text-transform:uppercase;margin-bottom:16px}
h1{font-family:'Bebas Neue',sans-serif;font-size:clamp(36px,5vw,56px);line-height:.9;letter-spacing:.01em;background:linear-gradient(180deg,var(--ink) 0%,#888 100%);-webkit-background-clip:text;background-clip:text;color:transparent}

/* v21.1 — Lap-Card: big lap time on top, metadata below, action button at the bottom.
   Not sticky. Lila accent for Coach (vs cyan for Datenviewer). */
.dv-lap-card{
  background:#0a0a0a;border:1px solid #262626;
  padding:32px 28px;margin-bottom:32px;
  display:grid;grid-template-columns:auto 1fr;gap:24px 36px;align-items:end;
}
.dv-lc-time{
  font-family:'Bebas Neue',sans-serif;font-size:clamp(64px,9vw,112px);
  line-height:.85;color:#c77dff;font-feature-settings:'tnum';
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
  background:#c77dff;color:#000;border:none;font-weight:600;font-size:13px;
  padding:14px 22px;
  animation:dv-lc-pulse 2s ease-in-out infinite;
}
.dv-lap-card.empty .dv-lc-change:hover{background:#d18fff}
@keyframes dv-lc-pulse{
  0%,100%{box-shadow:0 0 0 0 rgba(199,125,255,.6)}
  50%{box-shadow:0 0 0 10px rgba(199,125,255,0)}
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

.hero{display:none}

.empty-placeholder{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-height:240px;border:1px dashed var(--line);background:var(--bg-2);
  color:var(--ink-dim);font-family:'JetBrains Mono',monospace;font-size:12px;
  letter-spacing:.15em;text-transform:uppercase;gap:8px;padding:24px;
}
.empty-placeholder .ep-icon{font-size:32px;color:var(--ink-faint);font-family:'Bebas Neue',sans-serif}
.empty-placeholder .ep-hint{font-size:10px;color:var(--ink-faint);letter-spacing:.1em}

.section-title{margin:56px 0 16px;display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--line);padding-bottom:12px}
.section-title h2{font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:.02em}
.section-title .num{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-faint);letter-spacing:.15em}

/* ----- Analysis tab strip + content -----
   v21.41 — Tabs replace the old 2×2 card chooser. Each tab is a button
   with a small status label (VERFÜGBAR/BALD) above its name. The active
   tab keeps the same accent fill as the chooser used to have. */
.an-tabs-wrap{margin:8px 0 0}
.an-tabs{
  display:flex;gap:4px;align-items:flex-end;flex-wrap:wrap;
  position:relative;z-index:1;
}
.an-tab{
  flex:1 1 160px;min-width:0;
  font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:.04em;
  background:var(--bg-2);border:2px solid var(--accent);border-bottom:none;
  color:var(--ink-dim);
  padding:14px 18px;cursor:pointer;text-transform:uppercase;
  display:flex;flex-direction:column;align-items:flex-start;gap:2px;
  transition:background .12s,color .12s;
  text-align:left;
}
.an-tab .small{
  font-family:'JetBrains Mono',monospace;font-size:9px;
  letter-spacing:.18em;color:var(--ink-faint);font-weight:400;
}
.an-tab:not(.soon):hover{color:var(--ink);background:var(--bg)}
.an-tab.active{
  background:var(--accent);color:#000;
  transform:translateY(1px);box-shadow:0 -4px 0 0 var(--accent);
}
.an-tab.active .small{color:#000;font-weight:500}
/* v21.41 — Disabled "BALD" tabs: dim border + dim text, no hover, default cursor. */
.an-tab.soon{
  border-color:var(--line);color:var(--ink-faint);
  cursor:default;opacity:.78;
}
.an-tab.soon:hover{background:var(--bg-2)}
.an-tab.soon .small{color:var(--ink-faint)}

.an-content{
  background:var(--bg);border:2px solid var(--accent);
  padding:28px;min-height:240px;
}
/* v21.41 — Panel visibility lives directly on .an-panel inside .an-content
   (was nested in .an-panel-body before). */
.an-content .an-panel{display:none}
.an-content .an-panel.active{display:block}

/* v21.41 — Removed: .an-choice-grid / .an-choice* / .an-panel-wrap / .an-panel-head
   styles. The card chooser was replaced by the tab strip (see .an-tabs above),
   and the panel container is now plain .an-content. */

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
  gap:8px; margin-bottom:24px;
}
.stat-card{
  background:var(--bg-2); border:1px solid var(--line);
  padding:14px 16px; display:flex; flex-direction:column; gap:2px;
}
.stat-card .k{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.15em;color:var(--ink-faint);text-transform:uppercase}
.stat-card .v{font-family:'Bebas Neue',sans-serif;font-size:32px;line-height:1.05;color:var(--ink);font-feature-settings:'tnum'}
.stat-card .sub{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-dim);letter-spacing:.05em}

/* Phase tables (brake / accel) */
.phase-h{
  font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:.04em;
  color:var(--ink);margin:24px 0 12px;
}
.phase-table{display:flex;flex-direction:column;gap:0;font-family:'JetBrains Mono',monospace;font-size:12px;border-top:1px solid var(--line)}
.phase-row{
  display:grid;grid-template-columns:36px minmax(0,1.5fr) minmax(0,1.5fr) 60px 70px 80px 90px 80px;
  gap:10px;padding:10px 0;border-bottom:1px solid var(--line);align-items:center;
}
.phase-row.head{color:var(--ink-faint);font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.phase-row .idx{color:var(--ink-faint)}
.phase-row .v{color:var(--ink);font-feature-settings:'tnum'}
.phase-row .v .fast{color:var(--accent)}
.phase-row .v.brake-num{color:var(--brake)}
.phase-row.active{background:rgba(199,125,255,.08)}
.phase-row .badge{
  display:inline-block;padding:2px 8px;font-size:10px;letter-spacing:.05em;
  background:var(--bg-2);border:1px solid var(--line);
}
.phase-row .badge.good{color:var(--accel);border-color:var(--accel);background:rgba(58,255,122,.12)}
.phase-row .badge.warn{color:#ffaa00;border-color:#ffaa00;background:rgba(255,170,0,.12)}
.phase-row .badge.bad{color:var(--brake);border-color:var(--brake);background:rgba(255,61,61,.12)}
@media (max-width:980px){
  .phase-row{grid-template-columns:30px 1fr 1fr 50px 60px 70px}
  .phase-row .hide-narrow{display:none}
}

/* Channel-role assignment */
.channel-assign-block{margin-bottom:24px}
.channel-assign-title{
  font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:.04em;
  margin-bottom:6px;color:var(--ink);
}
.channel-assign-hint{
  font-size:12px;color:var(--ink-dim);margin-bottom:14px;line-height:1.5;
}
.channel-assign-grid{display:flex;flex-direction:column;gap:8px}
.channel-slot{
  display:grid;grid-template-columns:160px 1fr auto;gap:14px;align-items:center;
  background:var(--bg-2);border:1px solid var(--line);padding:12px 16px;
  position:relative;cursor:pointer;transition:border-color .15s;
}
.channel-slot:hover{border-color:var(--ink-dim)}
.channel-slot .cs-role{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.12em;color:var(--ink-dim);text-transform:uppercase}
.channel-slot .cs-current{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--ink)}
.channel-slot .cs-current.none{color:var(--ink-faint);font-style:italic}
.channel-slot .cs-arrow{color:var(--ink-faint);font-size:18px}

.coming-soon{
  background:var(--bg-2);border:1px dashed var(--line);
  padding:28px;text-align:center;color:var(--ink-dim);
  font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:.1em;text-transform:uppercase;
  display:flex;flex-direction:column;gap:10px;
}
.coming-soon .big{font-family:'Bebas Neue',sans-serif;font-size:24px;letter-spacing:.04em;color:var(--ink-faint)}

/* v21.11 — Bremsanalyse: pro Bremszone eine Karte mit Sparkline + Bewertung */
.brake-analysis,
.accel-analysis,
.elec-analysis,
.susp-analysis{display:flex;flex-direction:column;gap:14px}
.brake-analysis .ba-empty,
.accel-analysis .ba-empty,
.elec-analysis .ba-empty,
.susp-analysis .ba-empty{
  background:var(--bg-2);border:1px dashed var(--line);padding:28px;
  text-align:center;color:var(--ink-dim);font-family:'JetBrains Mono',monospace;
  font-size:12px;letter-spacing:.1em;text-transform:uppercase;
}
.brake-analysis .ba-summary,
.accel-analysis .ba-summary,
.elec-analysis .ba-summary,
.susp-analysis .ba-summary{
  background:var(--bg-2);border-left:3px solid var(--accent);
  padding:18px 24px;margin-bottom:8px;
}
.brake-analysis .ba-summary .bas-headline,
.accel-analysis .ba-summary .bas-headline,
.elec-analysis .ba-summary .bas-headline,
.susp-analysis .ba-summary .bas-headline{
  font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:.02em;
  color:var(--ink);margin-bottom:10px;
}
.brake-analysis .ba-summary .bas-counts,
.accel-analysis .ba-summary .bas-counts,
.elec-analysis .ba-summary .bas-counts,
.susp-analysis .ba-summary .bas-counts{
  display:flex;gap:16px;flex-wrap:wrap;font-family:'JetBrains Mono',monospace;
  font-size:11px;color:var(--ink-dim);letter-spacing:.08em;
}
.brake-analysis .ba-summary .bas-counts .n,
.accel-analysis .ba-summary .bas-counts .n,
.elec-analysis .ba-summary .bas-counts .n,
.susp-analysis .ba-summary .bas-counts .n{color:var(--ink);font-weight:500}
/* v21.17 — Warn-Banner in der Analyse (z.B. fehlender optionaler Kanal) */
.brake-analysis .ba-note-warn,
.accel-analysis .ba-note-warn,
.elec-analysis .ba-note-warn,
.susp-analysis .ba-note-warn{
  background:rgba(255,170,0,.08);border-left:3px solid #ffaa00;
  padding:12px 18px;margin-bottom:8px;
  font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ink);
  letter-spacing:.04em;line-height:1.6;
}
/* v21.39 — Elektronik-Event-Tabelle. Eine Zeile pro erkanntem Event mit
   Index, Typ-Badge, Ort/Dauer, kurzer Erklärung, Sparkline. */
.elec-event-table{
  display:grid;
  grid-template-columns:46px 160px 1fr 100px 220px;
  gap:14px;align-items:center;
  background:var(--bg-2);border:1px solid var(--line);
  padding:16px 20px;
}
.elec-event-table.head{
  font-family:'JetBrains Mono',monospace;font-size:10px;
  color:var(--ink-faint);letter-spacing:.15em;text-transform:uppercase;
  border-bottom:1px solid var(--line);padding-bottom:8px;
}
.elec-event-row{
  display:grid;grid-template-columns:46px 160px 1fr 100px 220px;
  gap:14px;align-items:center;
  background:var(--bg-2);border:1px solid var(--line);
  padding:14px 20px;
}
.elec-event-row .eer-idx{
  font-family:'Bebas Neue',sans-serif;font-size:30px;line-height:1;
  color:var(--ink-faint);
}
.elec-event-row .eer-type{
  font-family:'JetBrains Mono',monospace;font-size:10px;
  letter-spacing:.08em;text-transform:uppercase;padding:5px 8px;
  border:1px solid var(--line);text-align:center;
  white-space:nowrap;
}
.elec-event-row.spike   .eer-type{color:#ff3d3d;border-color:#ff3d3d}
.elec-event-row.osc     .eer-type{color:#ff9933;border-color:#ff9933}
.elec-event-row.slip    .eer-type{color:#ffcc33;border-color:#ffcc33}
.elec-event-row.tc      .eer-type{color:#3aff7a;border-color:#3aff7a}
.elec-event-row.wc      .eer-type{color:#00d4ff;border-color:#00d4ff}
.elec-event-row .eer-text{
  font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ink);
  line-height:1.5;
}
.elec-event-row .eer-text .nh{color:var(--ink-dim)}
.elec-event-row .eer-where{
  font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);
  text-align:right;letter-spacing:.05em;
}
/* v21.40 — Mini-Sparkline pro Event-Zeile. Zeigt die für den Event-Typ
   relevanten Kanäle (z.B. V_rear für Spike, V_front+V_rear für Slip,
   tc_status mit V_rear im Hintergrund für TC-Events). */
.elec-event-row .eer-spark{
  display:flex;flex-direction:column;align-items:flex-end;gap:4px;
  min-width:0;
}
.elec-event-row .eer-spark svg{display:block}
.elec-event-row .eer-spark .sp-label{
  font-family:'JetBrains Mono',monospace;font-size:9px;
  letter-spacing:.1em;color:var(--ink-faint);text-transform:uppercase;
}

/* v21.40/v21.46 — Multi-Channel-Graph wurde entfernt; ersetzt durch den
   Datenviewer-Chart als letzten Abschnitt jeder Analyse (kommt separat dazu).
   Der elec-cursor-dot bleibt: er ist für den Trackmap-Cursor-Sync zuständig
   (gleiche Mechanik, neuer Konsument). */

/* v21.40 — Cursor-Sync: blinkender Punkt auf der Trackmap an der
   Stelle, die der Chart-Hover ausgewählt hat. */
.elec-trackmap-wrap .elec-cursor-dot{
  pointer-events:none;
}
/* v22.7 — Fahrwerks-Setup-Analyse: Event-Tabelle (analog .elec-event-table)
   und Histogramm-Sektion. Eigene Klassen, gleiche Grid-Spalten wie Elektronik. */
.susp-event-table{
  display:grid;
  grid-template-columns:46px 160px 1fr 100px 220px;
  gap:14px;align-items:center;
  background:var(--bg-2);border:1px solid var(--line);
  padding:16px 20px;
}
.susp-event-table.head{
  font-family:'JetBrains Mono',monospace;font-size:10px;
  color:var(--ink-faint);letter-spacing:.15em;text-transform:uppercase;
  border-bottom:1px solid var(--line);padding-bottom:8px;
}
.susp-event-row{
  display:grid;grid-template-columns:46px 160px 1fr 100px 220px;
  gap:14px;align-items:center;
  background:var(--bg-2);border:1px solid var(--line);
  padding:14px 20px;
}
.susp-event-row .eer-idx{
  font-family:'Bebas Neue',sans-serif;font-size:30px;line-height:1;
  color:var(--ink-faint);
}
.susp-event-row .eer-type{
  font-family:'JetBrains Mono',monospace;font-size:10px;
  letter-spacing:.08em;text-transform:uppercase;padding:5px 8px;
  border:1px solid var(--line);text-align:center;
  white-space:nowrap;
}
.susp-event-row.block-fork    .eer-type{color:#ff3d3d;border-color:#ff3d3d}
.susp-event-row.block-shock   .eer-type{color:#ff9933;border-color:#ff9933}
.susp-event-row.topping-fork  .eer-type{color:#33ccff;border-color:#33ccff}
.susp-event-row.topping-shock .eer-type{color:#3aff7a;border-color:#3aff7a}
.susp-event-row.bump-fork     .eer-type{color:#ffcc33;border-color:#ffcc33}
.susp-event-row.bump-shock    .eer-type{color:#cc88ff;border-color:#cc88ff}
.susp-event-row .eer-text{
  font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ink);
  line-height:1.5;
}
.susp-event-row .eer-text .nh{color:var(--ink-dim)}
.susp-event-row .eer-where{
  font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);
  text-align:right;letter-spacing:.05em;
}
.susp-event-row .eer-spark{
  display:flex;flex-direction:column;align-items:flex-end;gap:4px;
  min-width:0;
}
.susp-event-row .eer-spark svg{display:block}
.susp-event-row .eer-spark .sp-label{
  font-family:'JetBrains Mono',monospace;font-size:9px;
  letter-spacing:.1em;color:var(--ink-faint);text-transform:uppercase;
}
/* v22.7 — Histogramm-Sektion: zwei Karten Side-by-Side (Gabel | Federbein) */
.susp-hist-section{
  background:var(--bg-2);border:1px solid var(--line);
  padding:18px 22px;margin-bottom:18px;
}
.susp-hist-section[hidden]{display:none}
.susp-hist-section .chart-section-title{margin:0 0 6px}
.susp-hist-hint{
  font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);
  letter-spacing:.04em;line-height:1.6;margin-bottom:14px;
}
.susp-hist-grid{
  display:grid;grid-template-columns:1fr 1fr;gap:18px;
}
@media (max-width:780px){
  .susp-hist-grid{grid-template-columns:1fr}
}
.susp-hist-card{
  background:var(--bg);border:1px solid var(--line);padding:14px 16px;
}
.susp-hist-title{
  font-family:'JetBrains Mono',monospace;font-size:11px;
  color:var(--ink-faint);letter-spacing:.12em;text-transform:uppercase;
  margin-bottom:10px;
}
.susp-hist-svg{display:block;width:100%;height:auto;max-height:280px}
.susp-hist-svg .hb-bar{fill:var(--accent)}
.susp-hist-svg .hb-bar-out{fill:#ff9933}  /* ausfedern (rebound) */
.susp-hist-svg .hb-bar-in{fill:#3aff7a}   /* einfedern (compression) */
.susp-hist-svg .hb-axis{stroke:var(--ink-faint);stroke-width:1}
.susp-hist-svg .hb-tick{stroke:var(--ink-faint);stroke-width:0.5}
.susp-hist-svg .hb-tick-label,
.susp-hist-svg .hb-axis-label{
  font-family:'JetBrains Mono',monospace;font-size:9px;
  fill:var(--ink-dim);letter-spacing:.06em;
}
.susp-hist-svg .hb-zero-line{stroke:var(--ink-dim);stroke-width:1;stroke-dasharray:2 3}
.brake-zone{
  background:var(--bg-2);border:1px solid var(--line);padding:16px 20px;
  display:grid;grid-template-columns:auto 1fr 200px;gap:18px;align-items:center;
}
.brake-zone .bz-idx{
  font-family:'Bebas Neue',sans-serif;font-size:36px;line-height:1;
  color:var(--ink-faint);min-width:46px;
}
.brake-zone .bz-mid{display:flex;flex-direction:column;gap:6px;min-width:0}
.brake-zone .bz-where{
  font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em;
  color:var(--ink-faint);text-transform:uppercase;
}
.brake-zone .bz-pills{display:flex;gap:6px;flex-wrap:wrap}
.brake-zone .bz-pill{
  display:inline-flex;align-items:center;gap:4px;
  font-family:'JetBrains Mono',monospace;font-size:10px;
  letter-spacing:.08em;padding:3px 8px;text-transform:uppercase;
  border:1px solid var(--line);
}
.brake-zone .bz-pill.good{color:var(--accel);border-color:var(--accel);background:rgba(58,255,122,.08)}
.brake-zone .bz-pill.warn{color:#ffaa00;border-color:#ffaa00;background:rgba(255,170,0,.08)}
.brake-zone .bz-pill.bad{color:var(--brake);border-color:var(--brake);background:rgba(255,61,61,.08)}
.brake-zone .bz-notes{
  font-size:13px;color:var(--ink-dim);line-height:1.55;
}
.brake-zone .bz-notes .nh{color:var(--ink)}
.brake-zone .bz-spark{
  display:flex;flex-direction:column;gap:4px;align-items:flex-end;
}
.brake-zone .bz-spark svg{display:block}
.brake-zone .bz-spark .sp-label{
  font-family:'JetBrains Mono',monospace;font-size:9px;
  color:var(--ink-faint);letter-spacing:.12em;
}
@media (max-width:780px){
  .brake-zone{grid-template-columns:auto 1fr;}
  .brake-zone .bz-spark{grid-column:1/-1;align-items:flex-start}
}

/* v21.45 — Marker ↔ Row Verlinkung (Bremsen, Beschleunigung, Elektronik).
   Klick auf einen Marker auf der Trackmap highlighted die zugehörige Zeile
   und umgekehrt. Sticky-Auswahl; nochmaliger Klick toggelt aus. */
.brake-zone[data-idx],
.elec-event-row[data-idx]{cursor:pointer}
.brake-zone.is-selected{
  border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset;
}
.elec-event-row.is-selected{
  border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset;
}
.brake-trackmap [data-idx],
.accel-trackmap [data-idx],
.elec-trackmap  [data-idx]{cursor:pointer}
.brake-trackmap [data-idx].is-selected circle,
.accel-trackmap [data-idx].is-selected circle,
.elec-trackmap  [data-idx].is-selected circle{
  filter:drop-shadow(0 0 4px #f5f5f0);
}
/* Outline-Ring um die selektierte Marker-Bubble (an den ersten <circle> mit r=11 angesetzt) */
.brake-trackmap [data-idx].is-selected .mk-bubble,
.accel-trackmap [data-idx].is-selected .mk-bubble,
.elec-trackmap  [data-idx].is-selected .mk-bubble{
  stroke:#f5f5f0;stroke-width:2.5;
}

/* v21.12/15 — Coach Track-Maps (Bremsen + Beschleunigung) — shared styles */
/* v21.24 — position:relative damit Spinner/Attribution sich absolut platzieren */
.brake-trackmap-wrap,
.accel-trackmap-wrap,
.elec-trackmap-wrap,
.susp-trackmap-wrap{
  background:var(--bg-2);border:1px solid var(--line);
  padding:18px 22px;margin-bottom:18px;
  position:relative;
}
.brake-trackmap-wrap[hidden],
.accel-trackmap-wrap[hidden],
.elec-trackmap-wrap[hidden],
.susp-trackmap-wrap[hidden]{display:none}
.brake-trackmap-wrap .bt-head,
.accel-trackmap-wrap .bt-head,
.elec-trackmap-wrap .bt-head,
.susp-trackmap-wrap .bt-head{
  display:flex;justify-content:space-between;align-items:center;
  flex-wrap:wrap;gap:12px;margin-bottom:12px;
}
.brake-trackmap-wrap .phase-h,
.accel-trackmap-wrap .phase-h,
.elec-trackmap-wrap .phase-h,
.susp-trackmap-wrap .phase-h{margin:0}
/* v21.25 — Mapview-Toggle (single-button .tm-bg-btn) rechts in .bt-head.
   Die alten seg-switch-Regeln für Coach-Trackmaps wurden entfernt — der
   Toggle benutzt nun die zentralen .tm-bg-btn-Styles aus TILE_SPINNER_CSS. */
.brake-trackmap-wrap .bt-head .tm-bg-btn,
.accel-trackmap-wrap .bt-head .tm-bg-btn,
.elec-trackmap-wrap .bt-head .tm-bg-btn{margin-left:auto}
.brake-trackmap-wrap .map-attribution,
.accel-trackmap-wrap .map-attribution,
.elec-trackmap-wrap .map-attribution{
  position:absolute;bottom:6px;right:10px;
  font-family:'JetBrains Mono',monospace;font-size:9px;
  color:rgba(245,245,240,.7);background:rgba(0,0,0,.4);
  padding:2px 6px;border-radius:2px;letter-spacing:.05em;
  pointer-events:auto;z-index:2;
}
.brake-trackmap-wrap .map-attribution a,
.accel-trackmap-wrap .map-attribution a,
.elec-trackmap-wrap .map-attribution a{
  color:inherit;text-decoration:none;
  border-bottom:1px dotted rgba(245,245,240,.5);
}
.brake-trackmap-wrap .map-attribution a:hover,
.accel-trackmap-wrap .map-attribution a:hover,
.elec-trackmap-wrap .map-attribution a:hover{color:var(--accent)}
.brake-trackmap-wrap .bt-legend,
.accel-trackmap-wrap .bt-legend,
.elec-trackmap-wrap .bt-legend{
  display:flex;gap:14px;flex-wrap:wrap;
  font-family:'JetBrains Mono',monospace;font-size:10px;
  color:var(--ink-dim);letter-spacing:.1em;text-transform:uppercase;
}
.brake-trackmap-wrap .bt-leg-item,
.accel-trackmap-wrap .bt-leg-item,
.elec-trackmap-wrap .bt-leg-item{
  display:inline-flex;align-items:center;gap:6px;
}
.brake-trackmap-wrap .bt-leg-swatch,
.accel-trackmap-wrap .bt-leg-swatch{
  display:inline-block;width:18px;height:3px;
}
.brake-trackmap-wrap .bt-leg-off,
.accel-trackmap-wrap .bt-leg-off { background:#444 }
.brake-trackmap-wrap .bt-leg-low,
.accel-trackmap-wrap .bt-leg-low { background:rgba(199,125,255,.45) }
.brake-trackmap-wrap .bt-leg-high,
.accel-trackmap-wrap .bt-leg-high{ background:var(--accent) }
.brake-trackmap-wrap .bt-leg-marker,
.accel-trackmap-wrap .bt-leg-marker{
  font-size:14px;color:var(--ink);line-height:1;
}
.brake-trackmap-wrap .bt-leg-marker.err,
.accel-trackmap-wrap .bt-leg-marker.err{color:var(--brake)}
/* v21.17 — Zone/Phase Index-Marker in der Legende, Farbe nach Score. */
.brake-trackmap-wrap .bt-leg-zone,
.accel-trackmap-wrap .bt-leg-zone{
  display:inline-flex;align-items:center;justify-content:center;
  width:18px;height:18px;border-radius:50%;
  font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;
  color:#0a0a0a;border:1px solid #0a0a0a;line-height:1;
}
.brake-trackmap-wrap .bt-leg-zone.good,
.accel-trackmap-wrap .bt-leg-zone.good{ background:#7dd17d }
.brake-trackmap-wrap .bt-leg-zone.warn,
.accel-trackmap-wrap .bt-leg-zone.warn{ background:#ffaa00 }
.brake-trackmap-wrap .bt-leg-zone.bad,
.accel-trackmap-wrap .bt-leg-zone.bad{ background:#ff3d3d }
.brake-trackmap,
.accel-trackmap{width:100%;height:auto;display:block}
.brake-trackmap .bt-track-bg,
.accel-trackmap .bt-track-bg{stroke:#f5f5f0;fill:none}

/* Generic modal styles (channel-role picker reuses these) */
.modal-back{
  position:fixed;inset:0;background:rgba(0,0,0,.72);
  display:flex;align-items:flex-start;justify-content:center;padding:48px 24px;z-index:400;
  overflow-y:auto;backdrop-filter:blur(6px);
}
.modal-back[hidden]{display:none}
.modal{
  background:var(--bg);border:1px solid var(--line);
  width:min(1000px, 100%);max-height:calc(100vh - 96px);
  display:flex;flex-direction:column;
}
.modal-head{display:flex;justify-content:space-between;align-items:center;padding:18px 24px;border-bottom:1px solid var(--line)}
.modal-head h3{font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:.03em}
.modal-close{background:none;border:none;color:var(--ink-dim);font-size:24px;cursor:pointer;width:32px;height:32px}
.modal-close:hover{color:var(--ink)}
.modal-toolbar{display:flex;gap:12px;padding:14px 24px;border-bottom:1px solid var(--line);background:var(--bg-2);align-items:center}
.modal-toolbar input{flex:1;background:var(--bg);border:1px solid var(--line);color:var(--ink);font-family:'JetBrains Mono',monospace;font-size:12px;padding:8px 10px;outline:none}
.modal-toolbar input:focus{border-color:var(--accent)}
.modal-hint{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.12em;color:var(--ink-faint);text-transform:uppercase}
.modal-body{overflow-y:auto;padding:8px 24px;flex:1 1 auto;min-height:200px;max-height:60vh}
.modal-foot{display:flex;justify-content:space-between;gap:12px;padding:14px 24px;border-top:1px solid var(--line);background:var(--bg-2)}

/* v21.46 — Chart-Section am Ende jeder Analyse (Bremsen/Beschl/Elektronik).
   Geteilte SVG-Chart-Komponente aus /static/speed_chart.js. Eigenständige
   Klassen `chart-svg`, `chart-toolbar`, `chart-legend`, `chart-tick`,
   `chart-label`, `chart-hint`, `zoom-pct`, `modal-toolbar`, `.chart-btn.accent`.
   Die anderen Modal-Klassen (.modal-back/.modal/.modal-head/.modal-foot,
   .ch-table-head, .ch-row, .ch-empty) sind bereits oben definiert. */
.chart-section{margin-top:28px}
.chart-section-title{
  font-family:'Bebas Neue',sans-serif;font-size:22px;letter-spacing:.04em;
  margin:0 0 12px;border-bottom:1px solid var(--line);padding-bottom:8px;
}
.chart-svg{
  width:100%;height:auto;display:block;
  background:var(--bg-2);border:1px solid var(--line);
  cursor:crosshair;
}
.chart-svg:active{cursor:grabbing}
.chart-toolbar{display:flex;align-items:center;gap:14px;margin:0 0 8px;flex-wrap:wrap}
.chart-btn.accent{background:var(--accent);color:#000;border-color:var(--accent);font-weight:600}
.chart-btn.accent:hover{background:#d18fff;color:#000}
.chart-btn.accent .badge{background:#000;color:var(--accent)}
.chart-btn .badge{
  display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;
  background:var(--accent);color:#000;font-size:10px;font-weight:600;
}
.chart-btn .zoom-pct{margin-left:6px}
.chart-legend{
  display:flex;gap:10px;flex-wrap:wrap;
  font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.1em;
  color:var(--ink-dim);text-transform:uppercase;
}
.chart-legend .lg{display:inline-flex;gap:6px;align-items:center}
.chart-legend .swatch{display:inline-block;width:14px;height:2px}
.chart-hint{
  margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10px;
  letter-spacing:.08em;color:var(--ink-faint);text-transform:uppercase;
}
.chart-tick{font-family:'JetBrains Mono',monospace;font-size:10px;fill:var(--ink-faint);letter-spacing:.05em}
.chart-label{font-family:'JetBrains Mono',monospace;font-size:10px;fill:var(--ink-dim);letter-spacing:.1em}
.modal-toolbar{padding:14px 24px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center}
.modal-toolbar input{
  flex:1;background:var(--bg);border:1px solid var(--line);color:var(--ink);
  font-family:'JetBrains Mono',monospace;font-size:12px;padding:8px 10px;outline:none;
}
.modal-toolbar input:focus{border-color:var(--accent)}
.modal-hint{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.1em}
/* Speed-Chart Channel-Picker Modal: erweiterten Grid für min/max/mean Spalten.
   Coach's Default-Channel-Slot-Picker hat schon ein 6-Spalten-Grid; das passt
   auch für unseren Speed-Chart-Picker (Bild ähnlich), aber wir lassen die
   Spaltenbreiten unverändert. */

.ch-table-head, .ch-row{
  display:grid;grid-template-columns:50px minmax(0,2fr) 80px 80px 80px 80px;
  gap:10px;align-items:center;padding:8px 0;font-family:'JetBrains Mono',monospace;font-size:12px;
}
.ch-table-head{color:var(--ink-faint);font-size:10px;letter-spacing:.12em;text-transform:uppercase;border-bottom:1px solid var(--line)}
.ch-row{cursor:pointer;border-bottom:1px solid #181818}
.ch-row:hover{background:var(--bg-2)}
.ch-row.active{background:rgba(199,125,255,.08)}
.ch-row .ch-col-name{display:flex;gap:8px;align-items:center;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ch-row .swatch{display:inline-block;width:10px;height:10px}
.ch-empty{padding:32px;text-align:center;color:var(--ink-dim);font-family:'JetBrains Mono',monospace}

.chart-btn{
  font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.15em;
  background:var(--bg-2);border:1px solid var(--line);color:var(--ink);
  padding:7px 12px;cursor:pointer;text-transform:uppercase;
}
.chart-btn:hover{border-color:var(--accent);color:var(--accent)}
.chart-btn.primary{background:var(--accent);color:#000;border-color:var(--accent)}
.chart-btn.primary:hover{background:#d18fff;color:#000}
.chart-btn.ghost{background:transparent}

/* ----- Lap-Picker modal (same as Datenviewer) ----- */
.lp-modal{
  position:fixed;inset:0;background:rgba(0,0,0,.72);
  display:flex;align-items:flex-start;justify-content:center;
  padding:48px 24px;z-index:500;overflow-y:auto;backdrop-filter:blur(6px);
}
.lp-modal[hidden]{display:none}
.lp-modal-box{
  background:var(--bg);border:1px solid var(--line);
  width:min(1100px, 100%);max-height:calc(100vh - 96px);
  display:flex;flex-direction:column;
}
.lp-modal-head{display:flex;justify-content:space-between;align-items:center;padding:20px 28px;border-bottom:1px solid var(--line)}
.lp-modal-head h3{font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:.04em}
.lp-close{background:none;border:none;color:var(--ink-dim);font-size:28px;cursor:pointer;width:36px;height:36px;line-height:1}
.lp-close:hover{color:var(--ink)}
.lp-tabs{display:flex;gap:8px;padding:14px 20px 0;border-bottom:1px solid var(--line);background:var(--bg-2)}
.lp-tab{
  background:var(--bg);border:1px solid var(--line);border-bottom:none;
  color:var(--ink-dim);font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:.08em;
  padding:14px 28px;cursor:pointer;text-transform:uppercase;position:relative;top:1px;
  transition:background .12s,color .12s,border-color .12s;
}
.lp-tab:hover{color:var(--ink);border-color:var(--ink-dim)}
.lp-tab.active{background:var(--accent);color:#000;border-color:var(--accent);font-weight:600;box-shadow:0 -2px 0 0 var(--accent)}
.lp-tab.active:hover{background:#d18fff;border-color:#d18fff;color:#000}
.lp-tab::before{content:'';display:inline-block;width:8px;height:8px;margin-right:10px;border-radius:50%;background:var(--ink-faint);vertical-align:middle;transition:background .12s}
.lp-tab.active::before{background:#000}
.lp-panel{flex:1 1 auto;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.lp-panel[hidden]{display:none}
.lp-prefilter{display:flex;align-items:center;gap:12px;padding:12px 28px;
  background:rgba(199,125,255,.06);border-bottom:1px solid rgba(199,125,255,.2);
  font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em}
.lp-prefilter[hidden]{display:none}
.lp-pf-label{color:var(--ink-dim);text-transform:uppercase}
.lp-pf-value{color:var(--accent);font-weight:500}
.lp-pf-clear{background:transparent;border:1px solid var(--line);color:var(--ink-dim);
  font-family:inherit;font-size:10px;letter-spacing:.1em;padding:4px 10px;
  cursor:pointer;text-transform:uppercase}
.lp-pf-clear:hover{border-color:var(--ink-dim);color:var(--ink)}
.lp-filter{display:grid;grid-template-columns:repeat(auto-fit, minmax(160px, 1fr));gap:12px;padding:20px 28px;border-bottom:1px solid var(--line);background:var(--bg-2)}
.lp-field{display:flex;flex-direction:column;gap:4px;min-width:0}
.lp-field.lp-span2{grid-column:span 2}
.lp-field label{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--ink-faint);letter-spacing:.15em;text-transform:uppercase}
.lp-field input, .lp-field select{background:var(--bg);border:1px solid var(--line);color:var(--ink);font-family:'JetBrains Mono',monospace;font-size:12px;padding:8px 10px;outline:none}
.lp-field input:focus, .lp-field select:focus{border-color:var(--accent)}
.lp-results{overflow-y:auto;padding:0 28px;flex:1 1 auto;min-height:200px;max-height:50vh}
.lp-results .lp-empty{padding:48px 16px;text-align:center;color:var(--ink-dim);font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:.1em}
.lp-row{display:grid;grid-template-columns:90px minmax(0,1fr) minmax(0,1fr) minmax(0,1fr) 80px;gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid var(--line);cursor:pointer}
.lp-row:hover{background:var(--bg-2)}
.lp-row .lp-time{font-family:'JetBrains Mono',monospace;font-feature-settings:'tnum';font-size:18px;font-weight:500;color:var(--accent)}
.lp-row .lp-meta{display:flex;flex-direction:column;gap:1px;min-width:0}
.lp-row .lp-meta .k{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--ink-faint);letter-spacing:.1em;text-transform:uppercase}
.lp-row .lp-meta .v{font-size:13px;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lp-row .lp-meta .v.dim{color:var(--ink-dim);font-style:italic}
/* v22.3/v22.4 — Per-role channel-status icons in the lap-picker row.
   One inline SVG per registry role, grey if not assigned, green if
   assigned. SVGs use currentColor so we only switch `color:` on the
   wrapper. Tooltip on the wrapper shows the role label. */
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
.lp-row .lp-no{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);letter-spacing:.1em;text-align:right}
.lp-foot{padding:14px 28px;border-top:1px solid var(--line);background:var(--bg-2);display:flex;justify-content:space-between;align-items:center;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-faint);letter-spacing:.1em;text-transform:uppercase}
.lp-upload-form{padding:28px;display:flex;flex-direction:column;gap:20px}
.lp-upload-drop{border:2px dashed var(--line);padding:32px;text-align:center;display:flex;flex-direction:column;gap:8px;cursor:pointer;transition:border-color .15s,background .15s}
.lp-upload-drop:hover{border-color:var(--accent);background:var(--bg-2)}
.lp-upload-drop.has-file{border-color:var(--accent);background:rgba(199,125,255,.05)}
.lp-upload-icon{font-size:48px;color:var(--accent);line-height:1}
.lp-upload-title{font-family:'Bebas Neue',sans-serif;font-size:24px;letter-spacing:.05em}
.lp-upload-hint{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.1em}
.lp-upload-drop input[type="file"]{display:none}
.lp-upload-name{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--accent);margin-top:8px;word-break:break-all}
.lp-upload-options{display:flex;gap:16px;flex-wrap:wrap}
.lp-upload-opt{display:flex;flex-direction:column;gap:6px}
.lp-upload-opt .k{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.15em;text-transform:uppercase}
.lp-upload-opt input{background:var(--bg-2);border:1px solid var(--line);color:var(--ink);font-family:'JetBrains Mono',monospace;font-size:13px;padding:8px 10px;width:120px;outline:none}
.lp-upload-opt input:focus{border-color:var(--accent)}
.lp-upload-actions{display:flex;justify-content:flex-end;padding-top:8px;border-top:1px solid var(--line)}
.lp-upload-submit{font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:.05em;background:var(--accent);color:#000;border:none;padding:12px 28px;cursor:pointer}
.lp-upload-submit:hover{background:#d18fff}

footer{margin-top:80px;padding-top:32px;border-top:1px solid var(--line);color:var(--ink-faint);font-family:'JetBrains Mono',monospace;font-size:11px;display:flex;justify-content:space-between;letter-spacing:.05em;flex-wrap:wrap;gap:16px}
{{TILE_SPINNER_CSS}}
</style>
</head>
<body>
<div class="page">
  <header>
    <div class="eyebrow">AI Analyse und Coach</div>
    <h1>COACH</h1>
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
      <a class="dv-lc-cross" id="btn-cross-link" href="{{VIEWER_HREF}}" hidden>→ DATENVIEWER</a>
    </div>
  </div>

  <div class="section-title">
    <h2>ANALYSE</h2>
    <span class="num" id="an-section-sub">Tab wählen</span>
  </div>

  <!-- v21.41 — Analyse-Auswahl als Tab-Strip (vorher: 2×2-Karten-Grid).
       Aktiver Tab wird hervorgehoben, der zugehörige Panel-Inhalt
       erscheint im an-content darunter. "BALD"-Tabs sind nicht klickbar
       und visuell gedimmt. -->
  <div class="an-tabs-wrap" id="an-tabs-wrap">
    <div class="an-tabs" role="tablist">
      <button class="an-tab" data-an="brake" type="button" role="tab" aria-selected="false">
        <span class="small">VERFÜGBAR</span>
        <span>⏸ BREMSEN</span>
      </button>
      <button class="an-tab" data-an="accel" type="button" role="tab" aria-selected="false">
        <span class="small">VERFÜGBAR</span>
        <span>⏵ BESCHLEUNIGEN</span>
      </button>
      <button class="an-tab" data-an="electronics" type="button" role="tab" aria-selected="false">
        <span class="small">VERFÜGBAR</span>
        <span>⚡ ELEKTRONIK-SETUP</span>
      </button>
      <button class="an-tab" data-an="suspension" type="button" role="tab" aria-selected="false">
        <span class="small">VERFÜGBAR</span>
        <span>↕ FAHRWERKS-SETUP</span>
      </button>
      <button class="an-tab soon" data-an="mistakes" type="button" role="tab" aria-disabled="true" aria-selected="false">
        <span class="small">BALD</span>
        <span>⚠ FAHRFEHLER</span>
      </button>
      <button class="an-tab soon" data-an="technique" type="button" role="tab" aria-disabled="true" aria-selected="false">
        <span class="small">BALD</span>
        <span>✦ TECHNIK</span>
      </button>
    </div>
  </div>

  <!-- v21.41 — Panel-Container: einer pro Tab, jeweils mit .an-panel.
       Der aktive Tab schaltet die zugehörige Panel-id 'panel-<key>' aktiv. -->
  <div class="an-content" id="an-content">
    <div class="an-panel" id="panel-brake" role="tabpanel" hidden>
        <!-- v21.17 — Bremsanalyse mit Bremsdruck und Schräglage.
             Kanäle müssen manuell zugeordnet werden (kein Auto-Detect mehr).
             Dann zeigt eine Track-Map die Strecke eingefärbt nach Bremsdruck,
             und pro Bremszone wird bewertet:
               - Wie schnell wird Druck aufgebaut?
               - Wird der Druck graduell mit zunehmender Schräglage abgebaut?
               - Schwankt der Druck stark? (Pumpen / Modulationsfehler)
               - Wird bis zum Scheitelpunkt der Kurve gebremst?
                 (Scheitel via Track-Geometrie, validiert durch Lean-Maxima) -->
        <div class="channel-assign-block">
          <div class="channel-assign-title">STANDARDKANAL-ZUORDNUNG</div>
          <div class="channel-assign-hint">
            Wähle die Telemetrie-Kanäle für Bremsdruck und Schräglage.
            Geschwindigkeit kommt aus dem Standard-Kanal.
          </div>
          <div class="channel-assign-grid" id="brake-slots"></div>
        </div>
        <div class="brake-trackmap-wrap" id="brake-trackmap-wrap" hidden>
          <div class="bt-head">
            <h3 class="phase-h">TRACK · BREMSDRUCK</h3>
            <div class="bt-legend">
              <span class="bt-leg-item"><span class="bt-leg-swatch bt-leg-off"></span>kein Druck</span>
              <span class="bt-leg-item"><span class="bt-leg-swatch bt-leg-low"></span>leicht</span>
              <span class="bt-leg-item"><span class="bt-leg-swatch bt-leg-high"></span>voll</span>
              <span class="bt-leg-item"><span class="bt-leg-marker">●</span>Scheitel</span>
              <span class="bt-leg-item"><span class="bt-leg-zone good">N</span>Zone OK</span>
              <span class="bt-leg-item"><span class="bt-leg-zone warn">N</span>Zone Hinweis</span>
              <span class="bt-leg-item"><span class="bt-leg-zone bad">N</span>Zone Fokus</span>
              <span class="bt-leg-item"><span class="bt-leg-marker err">⚠</span>Bremse zu früh gelöst</span>
            </div>
            <!-- v21.24 — Mapview-Schalter (Esri World Imagery) -->
            <!-- v21.25 — Single-Button (vorher zweiteilig) -->
            <button type="button" class="tm-bg-btn {{TM_BG_BTN_CLS}}" id="tm-bg-toggle-brake" aria-pressed="false">
              <span class="tm-bg-dot"></span>MAPVIEW
            </button>
          </div>
          <svg class="brake-trackmap" id="brake-trackmap" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMid meet"></svg>
          <div class="map-attribution" id="tm-attribution-brake" style="display:none"></div>
        </div>
        <div class="brake-analysis" id="brake-analysis"></div>
        <!-- v21.46 — Speed+Kanäle Chart am Tab-Ende. Vorselektion = die
             dieser Analyse zugeordneten Channels. Picker erlaubt jederzeit
             andere Channels zu wählen wie im Datenviewer. -->
        <section class="chart-section" id="brake-chart-section">
          <h3 class="chart-section-title">DATEN VS. DISTANZ</h3>
          <div class="chart-toolbar">
            <button type="button" id="csb-pick" class="chart-btn accent">+ KANÄLE WÄHLEN <span id="csb-count"></span></button>
            <button type="button" id="csb-zoom-reset" class="chart-btn ghost" hidden title="Doppelklick im Chart resetted ebenfalls">ZOOM <span class="zoom-pct">100%</span> · RESET</button>
            <div class="chart-legend" id="csb-legend"></div>
            <span class="chart-hint">Mausrad zoomen · ziehen pannen · doppelklick reset</span>
          </div>
          <svg class="chart-svg" id="csb-svg" viewBox="0 0 1200 480" preserveAspectRatio="none"></svg>
          <div class="modal-back" id="csb-modal" hidden>
            <div class="modal" role="dialog">
              <div class="modal-head">
                <h3>WEITERE KANÄLE</h3>
                <button type="button" class="modal-close" id="csb-modal-close" aria-label="Schließen">×</button>
              </div>
              <div class="modal-toolbar">
                <input type="text" id="csb-search" placeholder="Kanäle durchsuchen…">
                <span class="modal-hint" id="csb-hint"></span>
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
                <div class="ch-table-body" id="csb-body"></div>
              </div>
              <div class="modal-foot">
                <button type="button" class="chart-btn ghost" id="csb-clear">ALLE AUS</button>
                <span style="flex:1"></span>
                <button type="button" class="chart-btn primary" id="csb-apply">FERTIG</button>
              </div>
            </div>
          </div>
        </section>
      </div>
      <div class="an-panel" id="panel-accel" role="tabpanel" hidden>
        <!-- v21.15 — Beschleunigungs-Analyse mit Throttle und Schräglage.
             Gleiche Struktur wie Bremsen:
             - Kanal-Picker (Gas, Schräglage)
             - Track-Map eingefärbt nach Throttle
             - Pro Beschleunigungsphase (nach Apex bis Geradeneinfahrt):
               - Aufzieh-Glättung: keine Pumper, keine Ausreißer
               - Apex→Vollgas Zeit (wie schnell wird ab Scheitel aufgezogen)
               - Vollgas-Anteil auf Geraden -->
        <div class="channel-assign-block">
          <div class="channel-assign-title">STANDARDKANAL-ZUORDNUNG</div>
          <div class="channel-assign-hint">
            Wähle die Telemetrie-Kanäle für Gasgriff und Schräglage.
            Geschwindigkeit kommt aus dem Standard-Kanal.
          </div>
          <div class="channel-assign-grid" id="accel-slots"></div>
        </div>
        <div class="accel-trackmap-wrap" id="accel-trackmap-wrap" hidden>
          <div class="bt-head">
            <h3 class="phase-h">TRACK · GASGRIFF</h3>
            <div class="bt-legend">
              <span class="bt-leg-item"><span class="bt-leg-swatch bt-leg-off"></span>kein Gas</span>
              <span class="bt-leg-item"><span class="bt-leg-swatch bt-leg-low"></span>Teilgas</span>
              <span class="bt-leg-item"><span class="bt-leg-swatch bt-leg-high"></span>Vollgas</span>
              <span class="bt-leg-item"><span class="bt-leg-marker">●</span>Scheitel</span>
              <span class="bt-leg-item"><span class="bt-leg-zone good">N</span>Phase OK</span>
              <span class="bt-leg-item"><span class="bt-leg-zone warn">N</span>Phase Hinweis</span>
              <span class="bt-leg-item"><span class="bt-leg-zone bad">N</span>Phase Fokus</span>
              <span class="bt-leg-item"><span class="bt-leg-marker err">⚠</span>Aufzieh-Fehler</span>
            </div>
            <!-- v21.24 — Mapview-Schalter (Esri World Imagery) -->
            <!-- v21.25 — Single-Button (vorher zweiteilig) -->
            <button type="button" class="tm-bg-btn {{TM_BG_BTN_CLS}}" id="tm-bg-toggle-accel" aria-pressed="false">
              <span class="tm-bg-dot"></span>MAPVIEW
            </button>
          </div>
          <svg class="accel-trackmap" id="accel-trackmap" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMid meet"></svg>
          <div class="map-attribution" id="tm-attribution-accel" style="display:none"></div>
        </div>
        <div class="accel-analysis" id="accel-analysis"></div>
        <!-- v21.46 — Speed+Kanäle Chart am Tab-Ende -->
        <section class="chart-section" id="accel-chart-section">
          <h3 class="chart-section-title">DATEN VS. DISTANZ</h3>
          <div class="chart-toolbar">
            <button type="button" id="csa-pick" class="chart-btn accent">+ KANÄLE WÄHLEN <span id="csa-count"></span></button>
            <button type="button" id="csa-zoom-reset" class="chart-btn ghost" hidden title="Doppelklick im Chart resetted ebenfalls">ZOOM <span class="zoom-pct">100%</span> · RESET</button>
            <div class="chart-legend" id="csa-legend"></div>
            <span class="chart-hint">Mausrad zoomen · ziehen pannen · doppelklick reset</span>
          </div>
          <svg class="chart-svg" id="csa-svg" viewBox="0 0 1200 480" preserveAspectRatio="none"></svg>
          <div class="modal-back" id="csa-modal" hidden>
            <div class="modal" role="dialog">
              <div class="modal-head">
                <h3>WEITERE KANÄLE</h3>
                <button type="button" class="modal-close" id="csa-modal-close" aria-label="Schließen">×</button>
              </div>
              <div class="modal-toolbar">
                <input type="text" id="csa-search" placeholder="Kanäle durchsuchen…">
                <span class="modal-hint" id="csa-hint"></span>
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
                <div class="ch-table-body" id="csa-body"></div>
              </div>
              <div class="modal-foot">
                <button type="button" class="chart-btn ghost" id="csa-clear">ALLE AUS</button>
                <span style="flex:1"></span>
                <button type="button" class="chart-btn primary" id="csa-apply">FERTIG</button>
              </div>
            </div>
          </div>
        </section>
      </div>
      <!-- v21.39 — Elektronik-Setup-Analyse. Sechs Pflicht-/Optional-Kanäle
           werden zugeordnet, dann werden folgende Events markiert:
             - Wheelspeed-Abweichung Front/Rear (Slip oder Lockup)
             - TC- oder WC-Eingriffe (Status weicht vom Ruhewert ab)
             - Rear-Wheel Spike (plötzliches Hochdrehen)
             - Rear-Wheel Oscillation (Pumpen) -->
      <div class="an-panel" id="panel-electronics" role="tabpanel" hidden>
        <div class="channel-assign-block">
          <div class="channel-assign-title">STANDARDKANAL-ZUORDNUNG</div>
          <div class="channel-assign-hint">
            Pflicht-Kanäle: Drehzahl Vorderrad, Drehzahl Hinterrad.
            Optional: Gasgriff, Schräglage, Status TC, Status WC —
            ohne diese werden die jeweiligen Eingriffs-Marker ausgelassen.
          </div>
          <div class="channel-assign-grid" id="electronics-slots"></div>
        </div>
        <div class="elec-trackmap-wrap" id="elec-trackmap-wrap" hidden>
          <div class="bt-head">
            <h3 class="phase-h">TRACK · ELEKTRONIK-EREIGNISSE</h3>
            <div class="bt-legend">
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#ff3d3d">●</span>Hinterrad-Spike</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#ff9933">●</span>Hinterrad-Schwankung</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#ffcc33">●</span>Slip / Lockup Vorderrad</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#3aff7a">●</span>TC-Eingriff</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#00d4ff">●</span>WC-Eingriff</span>
            </div>
            <button type="button" class="tm-bg-btn {{TM_BG_BTN_CLS}}" id="tm-bg-toggle-elec" aria-pressed="false">
              <span class="tm-bg-dot"></span>MAPVIEW
            </button>
          </div>
          <svg class="brake-trackmap" id="elec-trackmap" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMid meet"></svg>
          <div class="map-attribution" id="tm-attribution-elec" style="display:none"></div>
        </div>
        <!-- v21.40 — Multi-Channel-Graph entfernt in v21.46 (wird ersetzt
             durch den Datenviewer-Chart als letzten Abschnitt der Analyse). -->
        <div class="elec-analysis" id="electronics-analysis"></div>
        <!-- v21.46 — Speed+Kanäle Chart am Tab-Ende. Ersetzt den entfernten
             Multi-Channel-Chart aus v21.40 — diesmal gleiche UX wie im
             Datenviewer und vorselektiert mit den zugeordneten Channels. -->
        <section class="chart-section" id="elec-chart-section">
          <h3 class="chart-section-title">DATEN VS. DISTANZ</h3>
          <div class="chart-toolbar">
            <button type="button" id="cse-pick" class="chart-btn accent">+ KANÄLE WÄHLEN <span id="cse-count"></span></button>
            <button type="button" id="cse-zoom-reset" class="chart-btn ghost" hidden title="Doppelklick im Chart resetted ebenfalls">ZOOM <span class="zoom-pct">100%</span> · RESET</button>
            <div class="chart-legend" id="cse-legend"></div>
            <span class="chart-hint">Mausrad zoomen · ziehen pannen · doppelklick reset</span>
          </div>
          <svg class="chart-svg" id="cse-svg" viewBox="0 0 1200 480" preserveAspectRatio="none"></svg>
          <div class="modal-back" id="cse-modal" hidden>
            <div class="modal" role="dialog">
              <div class="modal-head">
                <h3>WEITERE KANÄLE</h3>
                <button type="button" class="modal-close" id="cse-modal-close" aria-label="Schließen">×</button>
              </div>
              <div class="modal-toolbar">
                <input type="text" id="cse-search" placeholder="Kanäle durchsuchen…">
                <span class="modal-hint" id="cse-hint"></span>
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
                <div class="ch-table-body" id="cse-body"></div>
              </div>
              <div class="modal-foot">
                <button type="button" class="chart-btn ghost" id="cse-clear">ALLE AUS</button>
                <span style="flex:1"></span>
                <button type="button" class="chart-btn primary" id="cse-apply">FERTIG</button>
              </div>
            </div>
          </div>
        </section>
      </div>
      <!-- v22.7 — Fahrwerks-Setup-Analyse: Block-Erkennung (Federweg auf Maximum
           mit scharfer Kante = flache Linie am Top) für Gabel und Federbein,
           plus zwei Histogramme der Federweg-Geschwindigkeit (symmetrisch um 0). -->
      <div class="an-panel" id="panel-suspension" role="tabpanel" hidden>
        <div class="channel-assign-block">
          <div class="channel-assign-title">STANDARDKANAL-ZUORDNUNG</div>
          <div class="channel-assign-hint">
            Pflicht-Kanäle: Federweg Gabel und Federweg Federbein.
            Die Analyse zeigt Stellen wo das Fahrwerk auf Block geht
            (= flache Linie am Maximum) und gibt ein Geschwindigkeits-Histogramm
            pro Element aus.
          </div>
          <div class="channel-assign-grid" id="suspension-slots"></div>
        </div>
        <!-- v22.7 — Histogramme der Federweg-Geschwindigkeit (Side-by-Side).
             v22.8 — Über die Trackmap verschoben: die Verteilung gibt den
             grundlegenden Setup-Eindruck (symmetrisch/asymmetrisch um 0)
             und steht jetzt direkt nach der Kanal-Zuordnung. Die Trackmap
             mit ihren Event-Markern bleibt nahe der Event-Liste, weil
             Marker und Zeilen interaktiv verlinkt sind. -->
        <section class="susp-hist-section" id="susp-hist-section" hidden>
          <h3 class="chart-section-title">FEDERWEG-GESCHWINDIGKEIT (HISTOGRAMM)</h3>
          <div class="susp-hist-hint">
            Verteilung der Federweg-Geschwindigkeit: links = ausfedern,
            rechts = einfedern. Höhere Balken = mehr Zeitanteil bei dieser
            Geschwindigkeit. Symmetrische Verteilung um 0 ist ein gutes Zeichen.
          </div>
          <div class="susp-hist-grid">
            <div class="susp-hist-card">
              <div class="susp-hist-title">FEDERWEG GABEL</div>
              <svg class="susp-hist-svg" id="susp-hist-fork" viewBox="0 0 600 280" preserveAspectRatio="none"></svg>
            </div>
            <div class="susp-hist-card">
              <div class="susp-hist-title">FEDERWEG FEDERBEIN</div>
              <svg class="susp-hist-svg" id="susp-hist-shock" viewBox="0 0 600 280" preserveAspectRatio="none"></svg>
            </div>
          </div>
        </section>
        <div class="susp-trackmap-wrap" id="susp-trackmap-wrap" hidden>
          <div class="bt-head">
            <h3 class="phase-h">TRACK · FEDERWEG-EREIGNISSE</h3>
            <div class="bt-legend">
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#ff3d3d">●</span>Gabel Block</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#ff9933">●</span>Federbein Block</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#33ccff">●</span>Gabel Top-Out</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#3aff7a">●</span>Federbein Top-Out</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#ffcc33">●</span>Gabel Bump</span>
              <span class="bt-leg-item"><span class="bt-leg-marker" style="color:#cc88ff">●</span>Federbein Bump</span>
            </div>
            <button type="button" class="tm-bg-btn {{TM_BG_BTN_CLS}}" id="tm-bg-toggle-susp" aria-pressed="false">
              <span class="tm-bg-dot"></span>MAPVIEW
            </button>
          </div>
          <svg class="brake-trackmap" id="susp-trackmap" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMid meet"></svg>
          <div class="map-attribution" id="tm-attribution-susp" style="display:none"></div>
        </div>
        <div class="susp-analysis" id="suspension-analysis"></div>
        <!-- v22.7 — Daten-vs-Distanz Chart als letzter Abschnitt analog zu
             den anderen Analysen. Eigenes Prefix 'css-' für die DOM-IDs. -->
        <section class="chart-section" id="susp-chart-section">
          <h3 class="chart-section-title">DATEN VS. DISTANZ</h3>
          <div class="chart-toolbar">
            <button type="button" id="css-pick" class="chart-btn accent">+ KANÄLE WÄHLEN <span id="css-count"></span></button>
            <button type="button" id="css-zoom-reset" class="chart-btn ghost" hidden title="Doppelklick im Chart resetted ebenfalls">ZOOM <span class="zoom-pct">100%</span> · RESET</button>
            <div class="chart-legend" id="css-legend"></div>
            <span class="chart-hint">Mausrad zoomen · ziehen pannen · doppelklick reset</span>
          </div>
          <svg class="chart-svg" id="css-svg" viewBox="0 0 1200 480" preserveAspectRatio="none"></svg>
          <div class="modal-back" id="css-modal" hidden>
            <div class="modal" role="dialog">
              <div class="modal-head">
                <h3>WEITERE KANÄLE</h3>
                <button type="button" class="modal-close" id="css-modal-close" aria-label="Schließen">×</button>
              </div>
              <div class="modal-toolbar">
                <input type="text" id="css-search" placeholder="Kanäle durchsuchen…">
                <span class="modal-hint" id="css-hint"></span>
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
                <div class="ch-table-body" id="css-body"></div>
              </div>
              <div class="modal-foot">
                <button type="button" class="chart-btn ghost" id="css-clear">ALLE AUS</button>
                <span style="flex:1"></span>
                <button type="button" class="chart-btn primary" id="css-apply">FERTIG</button>
              </div>
            </div>
          </div>
        </section>
      </div>
      <div class="an-panel" id="panel-mistakes" role="tabpanel" hidden>
        <div class="coming-soon">
          <span class="big">COMING SOON</span>
          Automatische Erkennung von Fahrfehlern aus Telemetrie-Anomalien.
        </div>
      </div>
      <div class="an-panel" id="panel-technique" role="tabpanel" hidden>
        <div class="coming-soon">
          <span class="big">COMING SOON</span>
          Schräglagen-Profil, Trail-Braking-Anteil, Gasgriff-Smoothness.
        </div>
      </div>
  </div>

  <!-- Channel-role picker modal (shared between both advanced tabs) -->
  <div class="modal-back" id="cr-modal" hidden>
    <div class="modal" role="dialog" aria-labelledby="cr-modal-title">
      <div class="modal-head">
        <h3 id="cr-modal-title">KANAL WÄHLEN</h3>
        <button type="button" class="modal-close" id="cr-modal-close" aria-label="Schließen">×</button>
      </div>
      <div class="modal-toolbar">
        <input type="text" id="cr-search" placeholder="Kanäle durchsuchen…">
        <span class="modal-hint" id="cr-modal-hint"></span>
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
        <div class="ch-table-body" id="cr-table-body"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="chart-btn ghost" id="cr-clear">ZURÜCKSETZEN</button>
        <span style="flex:1"></span>
        <button type="button" class="chart-btn primary" id="cr-apply">FERTIG</button>
      </div>
    </div>
  </div>

  <footer>
    <span>RACEDAT · AI ANALYSE UND COACH</span>
    <span>SINGLE-LAP</span>
  </footer>
</div>

<!-- Lap-Picker modal -->
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
    <div class="lp-panel" id="lp-panel-library">
      <div class="lp-prefilter" id="lp-prefilter" hidden>
        <span class="lp-pf-label">VORFILTER STRECKE:</span>
        <span class="lp-pf-value" id="lp-pf-track"></span>
        <button type="button" class="lp-pf-clear" id="lp-pf-clear">× ENTFERNEN</button>
      </div>
      <div class="lp-filter">
        <div class="lp-field lp-span2"><label>SUCHE</label>
          <input type="text" id="lp-f-search" placeholder="Fahrer, Bike, Strecke, Notizen, Datei…"></div>
        <div class="lp-field"><label>FAHRER</label>
          <select id="lp-f-driver"><option value="">— alle —</option></select></div>
        <div class="lp-field"><label>BIKE</label>
          <select id="lp-f-bike"><option value="">— alle —</option></select></div>
        <div class="lp-field"><label>STRECKE</label>
          <select id="lp-f-track"><option value="">— alle —</option></select></div>
        <div class="lp-field"><label>MAX RUNDENZEIT</label>
          <input type="text" id="lp-f-max" placeholder="z.B. 1:55.0" pattern="[0-9]+:[0-5][0-9](\.[0-9]+)?"></div>
      </div>
      <div class="lp-results" id="lp-results">
        <div class="lp-empty">LADE…</div>
      </div>
      <div class="lp-foot">
        <span id="lp-count">0 RUNDEN</span>
        <span>KLICK ZUM LADEN</span>
      </div>
    </div>
    <div class="lp-panel" id="lp-panel-upload" hidden>
      <form method="POST" action="/coach" enctype="multipart/form-data" class="lp-upload-form" id="lp-upload-form">
        <input type="hidden" name="mode" value="upload">
        <div class="lp-upload-drop">
          <div class="lp-upload-icon">⇪</div>
          <div class="lp-upload-title">DATEI WÄHLEN</div>
          <div class="lp-upload-hint">.ses · .ld · .xrk/.xrz · .csv · .dat (I2M) · .zip (2D) — max 70 MB</div>
          <input type="file" name="file" id="lp-file-input" required
                 accept=".ses,.SES,.ld,.LD,.xrk,.XRK,.xrz,.XRZ,.csv,.CSV,.dat,.DAT,.zip,.ZIP">
          <div class="lp-upload-name" id="lp-upload-name"></div>
        </div>
        <div class="lp-upload-options">
          <label class="lp-upload-opt">
            <span class="k">LAP-NR (leer = schnellste)</span>
            <input type="number" name="lap_num" min="1" placeholder="auto">
          </label>
        </div>
        <div class="lp-upload-actions">
          <button type="submit" class="lp-upload-submit">ANALYSIEREN →</button>
        </div>
      </form>
    </div>
  </div>
</div>

<!-- v21.46 — Geteiltes Chart-Modul (jeder Analyse-Tab hat einen unten) -->
<script src="/static/speed_chart.js"></script>

<script>
const DATA = {{DATA_JSON}};
// v20.4: expose DATA on window so the picker can read the current
// lap's track for pre-filtering (the picker IIFE has its own scope).
window.DATA = DATA;

// v22.10 — Detector thresholds, loaded from thresholds.json server-side
// and embedded into the page. Every detector reads its config from here
// (e.g. THRESHOLDS.suspension_block.edge_rise_frac). Fallback handling:
// if THRESHOLDS is missing or a section is incomplete, each detector
// has hardcoded defaults via the `?? value` operator at the call site.
const THRESHOLDS = {{THRESHOLDS_JSON}};
window.THRESHOLDS = THRESHOLDS;

{{TILE_PROVIDER_JS}}

{{TILE_HELPERS_JS}}

// ============================================================================
// Lap-picker modal — load any lap from the library, or upload a file.
// Same UX as the Datenviewer. On selection, navigates to /coach?lap_id=N.
// ============================================================================
(function lapPicker(){
  const modal = document.getElementById('lp-modal');
  const btnOpen = document.getElementById('btn-load-lap');
  const btnClose = document.getElementById('lp-modal-close');
  if (!modal || !btnOpen) return;

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
    // v20.4: pre-fill track filter from current lap
    const trackSel = document.getElementById('lp-f-track');
    const pfBar = document.getElementById('lp-prefilter');
    const pfVal = document.getElementById('lp-pf-track');
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

  let loadDebounce = null, distinctLoaded = false;
  // v22.3 — Cached channel-role registry for the per-row status dots.
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
    } catch (e){}
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
  function escHtml(s){
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
      // v22.3/v22.4 — Per-role status icons. One inline SVG per
      // registry role, grey if not assigned for this lap, green if
      // assigned. The SVG comes from `role.icon` (served by
      // /api/channel-roles-registry) and uses currentColor, so the
      // .on/.off wrapper class is what flips the colour. Tooltip = role
      // label. No icons row if the lap has zero extra channels.
      function chDots(lp){
        const ex = +(lp.extras_count || 0);
        if (ex === 0) return '';
        const assigned = new Set(lp.assigned_role_ids || []);
        const parts = ['<span class="lp-ch-dots" aria-label="Standardkanal-Zuordnung">'];
        for (const role of (rolesRegistry || [])){
          const on = assigned.has(role.id);
          // role.icon is a complete inline SVG string. We trust it
          // because it comes from our own server (no user input).
          parts.push(
            `<span class="lp-ch-icon-wrap ${on ? 'on' : 'off'}" ` +
            `title="${escHtml(role.label || role.id)}">${role.icon || ''}</span>`
          );
        }
        parts.push('</span>');
        return parts.join('');
      }
      laps.forEach(lp => {
        html += `<div class="lp-row" data-lap-id="${lp.lap_id}">
          <div class="lp-time">${fmtSec(lp.duration_s)}</div>
          <div class="lp-meta"><div class="k">STRECKE · DATUM</div>
            <div class="v ${lp.track ? '' : 'dim'}">${escHtml(lp.track || '—')}${lp.session_date ? ' · ' + escHtml(lp.session_date) : ''}</div></div>
          <div class="lp-meta"><div class="k">BIKE · FAHRER</div>
            <div class="v ${lp.bike ? '' : 'dim'}">${escHtml(lp.bike || '—')} · ${escHtml(lp.driver || '—')}</div></div>
          <div class="lp-meta"><div class="k">SESSION</div>
            <div class="v" style="font-size:12px;color:var(--ink-dim);font-family:JetBrains Mono">${escHtml(lp.original_filename || '')}</div>
            ${chDots(lp)}</div>
          <div class="lp-no">LAP ${lp.lap_number}</div>
        </div>`;
      });
      box.innerHTML = html;
      box.querySelectorAll('.lp-row').forEach(row => {
        row.addEventListener('click', () => {
          const id = row.dataset.lapId;
          if (id) window.location.href = '/coach?lap_id=' + encodeURIComponent(id);
        });
      });
    } catch (e){
      box.innerHTML = '<div class="lp-empty">FEHLER BEIM LADEN: ' + escHtml(e.message || e) + '</div>';
    }
  }

  // Upload tab
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
      } else {
        dropZone.classList.remove('has-file');
        fileName.textContent = '';
      }
    });
  }
})();

// ============================================================================
// v21.10 — Analyse-Auswahl. v21.41 — Umgestellt von Karten-Grid auf Tabs.
//   Klick auf einen Tab aktiviert dessen Panel im .an-content darunter.
//   "BALD"-Tabs sind nicht klickbar (aria-disabled). Standardmäßig ist
//   BREMSEN aktiv, damit beim Laden kein leerer Panel-Container zu sehen ist.
// ============================================================================
(function setupAnalysisChoice(){
  const tabs    = Array.from(document.querySelectorAll('.an-tab'));
  const content = document.getElementById('an-content');
  const panels  = content ? Array.from(content.querySelectorAll('.an-panel')) : [];
  if (!tabs.length || !content) return;

  function activate(key){
    tabs.forEach(t => {
      const on = (t.dataset.an === key);
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    panels.forEach(p => {
      const on = (p.id === 'panel-' + key);
      p.classList.toggle('active', on);
      p.hidden = !on;
    });
  }

  tabs.forEach(t => {
    if (t.classList.contains('soon')) return;  // BALD-Tabs nicht binden
    t.addEventListener('click', () => activate(t.dataset.an));
  });

  // Default-Tab beim Seitenladen: erster verfügbarer (= nicht .soon).
  const firstAvail = tabs.find(t => !t.classList.contains('soon'));
  if (firstAvail) activate(firstAvail.dataset.an);
})();

// Empty-mode: if no lap is loaded, mark the lap-card empty and show placeholders.
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

  const phHtml = '<div class="empty-placeholder">'
    + '<div class="ep-icon">∅</div>'
    + '<div>NOCH KEINE DATEN</div>'
    + '<div class="ep-hint">→ KLICK „+ RUNDE WÄHLEN" OBEN</div>'
    + '</div>';
  // v21.10 — hide the choice grid in empty mode and show a single placeholder
  // where the panel would normally appear.
  // v21.41 — Tabs statt Karten: blende den Tab-Strip aus und ersetze den
  //   Inhalt des .an-content durch den Placeholder.
  const tabsWrap = document.getElementById('an-tabs-wrap');
  if (tabsWrap) tabsWrap.hidden = true;
  const content = document.getElementById('an-content');
  if (content) content.innerHTML = phHtml;
  // Stop here — the rest of the script touches DATA.* and would crash.
  throw new Error('EmptyMode');
}

// A lap is loaded — server-rendered lap-card has the values, just relabel + reveal cross-link.
{
  const lbl = document.getElementById('btn-load-lap')?.querySelector('.bll-label');
  if (lbl) lbl.textContent = '↻ ANDERE RUNDE LADEN';
  const cl = document.getElementById('btn-cross-link');
  if (cl){
    const href = cl.getAttribute('href');
    if (href && href !== '' && href !== '{' + '{VIEWER_HREF}}') cl.hidden = false;
  }
}

function escapeHTML(s){
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ============================================================================
// Render the Basis tab (assessment + core stats + phase tables).
// In the Coach SPA we don't have a Track-Map or Speed-Chart, so we don't
// hook up cursor events — the tables are purely informational here.
// (A user who wants to dig into a specific zone clicks the cross-link to
// jump to /analyze?lap_id=N which has Map+Chart+cursor.)
// ============================================================================
(function renderBasis(){
  const A = DATA.analysis;
  if (!A) return;

  function pillClass(kind){
    return ({good:'good', warn:'warn', bad:'bad', neutral:'neutral'})[kind] || 'neutral';
  }
  function pillLabel(kind){
    return ({good:'OK', warn:'Hinweis', bad:'Fokus', neutral:'Info'})[kind] || 'Info';
  }
  let aHtml = `<div class="headline">${escapeHTML(A.assessment.headline)}</div>`;
  aHtml += '<ul>';
  A.assessment.points.forEach(p => {
    aHtml += `<li><span class="pill ${pillClass(p.kind)}">${pillLabel(p.kind)}</span><span>${escapeHTML(p.text)}</span></li>`;
  });
  aHtml += '</ul>';
  // v21.10 — Assessment lives in both Bremsen+Beschleunigen panels (same
  // bewertung is relevant for either lens). Core-Stats werden für jetzt
  // weggelassen, weil die Lap-Card oben schon Track/Lap/Bike/Driver+Zeit
  // zeigt.
  const brakeAss = document.getElementById('assessment-brake');
  const accelAss = document.getElementById('assessment-accel');
  if (brakeAss) brakeAss.innerHTML = aHtml;
  if (accelAss) accelAss.innerHTML = aHtml;

  const cs = A.core_stats || {};
  const fmtKm = (m) => (m/1000).toFixed(2) + ' km';
  const fmtT  = (s) => {
    if (!s) return '—';
    const min = Math.floor(s/60), sec = s - min*60;
    return min > 0 ? `${min}:${sec.toFixed(2).padStart(5,'0')}` : `${sec.toFixed(2)}s`;
  };
  let csHtml = '';
  if (cs.top_speed_kmh){
    csHtml += `<div class="stat-card"><span class="k">TOP-SPEED</span>
      <span class="v">${cs.top_speed_kmh.toFixed(0)} km/h</span>
      <span class="sub">bei ${fmtKm(cs.top_speed_distance_m)}</span></div>`;
  }
  if (cs.longest_full_throttle_m){
    csHtml += `<div class="stat-card"><span class="k">LÄNGSTE VOLLGAS-PHASE</span>
      <span class="v">${cs.longest_full_throttle_m.toFixed(0)} m</span>
      <span class="sub">am Stück</span></div>`;
  }
  if (Array.isArray(cs.sector_times_s) && cs.sector_times_s.length === 3){
    cs.sector_times_s.forEach((t, i) => {
      csHtml += `<div class="stat-card"><span class="k">SEKTOR ${i+1}</span>
        <span class="v">${fmtT(t)}</span>
        <span class="sub">Drittel der Runde</span></div>`;
    });
  }
  csHtml += `<div class="stat-card"><span class="k">PHASEN</span>
    <span class="v">${cs.n_brake_zones||0} / ${cs.n_accel_zones||0}</span>
    <span class="sub">Brems- / Beschl.</span></div>`;
  // v21.10 — Core-Stats Element wurde mit dem neuen Layout entfernt; falls
  // jemand das später wieder einbaut, hier in beide Panels rendern.
  const csEl = document.getElementById('core-stats');
  if (csEl) csEl.innerHTML = csHtml;

  function renderBrakeTable(){
    const head = `
      <div class="phase-row head">
        <span class="idx">#</span>
        <span>POSITION</span>
        <span>SPEED v→a→aus</span>
        <span>Δ KM/H</span>
        <span class="hide-narrow">DAUER</span>
        <span class="hide-narrow">∅ DECEL</span>
        <span>ROLLPHASE</span>
        <span>GLÄTTUNG</span>
      </div>`;
    let rows = '';
    A.braking_zones.forEach((z, i) => {
      rows += `
        <div class="phase-row" data-kind="brake" data-idx="${i}">
          <span class="idx">${i+1}</span>
          <span class="v">${(z.start_dist_m/1000).toFixed(2)}–${(z.end_dist_m/1000).toFixed(2)} km</span>
          <span class="v">${z.v_in_kmh.toFixed(0)}→<span class="fast">${z.v_apex_kmh.toFixed(0)}</span>→${z.v_out_kmh.toFixed(0)}</span>
          <span class="v brake-num">−${z.dv_kmh.toFixed(0)}</span>
          <span class="v hide-narrow">${z.duration_s.toFixed(2)} s</span>
          <span class="v hide-narrow">${z.avg_decel_ms2.toFixed(1)} m/s²</span>
          <span><span class="badge ${z.roll_grade}">${z.roll_distance_m.toFixed(0)} m</span></span>
          <span><span class="badge ${z.smoothness_grade}">${(z.smoothness*100).toFixed(0)} %</span></span>
        </div>`;
    });
    return head + rows;
  }
  function renderAccelTable(){
    const head = `
      <div class="phase-row head">
        <span class="idx">#</span>
        <span>POSITION</span>
        <span>SPEED a→aus</span>
        <span>Δ KM/H</span>
        <span class="hide-narrow">DAUER</span>
        <span class="hide-narrow">∅ ACCEL</span>
        <span class="hide-narrow"></span>
        <span></span>
      </div>`;
    let rows = '';
    A.accel_zones.forEach((z, i) => {
      rows += `
        <div class="phase-row" data-kind="accel" data-idx="${i}">
          <span class="idx">${i+1}</span>
          <span class="v">${(z.start_dist_m/1000).toFixed(2)}–${(z.end_dist_m/1000).toFixed(2)} km</span>
          <span class="v"><span class="fast">${z.v_apex_kmh.toFixed(0)}</span>→${z.v_out_kmh.toFixed(0)}</span>
          <span class="v">+${z.dv_kmh.toFixed(0)}</span>
          <span class="v hide-narrow">${z.duration_s.toFixed(2)} s</span>
          <span class="v hide-narrow">${z.avg_accel_ms2.toFixed(1)} m/s²</span>
          <span class="v hide-narrow"></span>
          <span></span>
        </div>`;
    });
    return head + rows;
  }
  // v21.11 — brake-table existiert nicht mehr im neuen Bremsen-Panel (das hat
  // jetzt Channel-Picker + dedicated Bremsanalyse). accel-table bleibt vorerst.
  const bt = document.getElementById('brake-table');
  if (bt) bt.innerHTML = renderBrakeTable();
  const at = document.getElementById('accel-table');
  if (at) at.innerHTML = renderAccelTable();
})();

// ============================================================================
// Channel-role assignment for the two advanced tabs.
// Identical behavior to the Datenviewer's implementation.
// ============================================================================
const channelRoles = (function(){
  const extras = DATA.extras || [];
  const SPECS = {
    // v21.11 — Bremsanalyse: Bremsdruck + Schräglage. Geschwindigkeit ist
    // immer DATA.speed, daher nicht zu konfigurieren.
    'brake': [
      {id: 'brake_pressure', label: 'BREMSDRUCK',
       patterns: [/^p_brake(_fr)?$/i, /brake.*press/i, /brk.*press/i],
       units: ['bar','psi','kpa']},
      {id: 'lean', label: 'SCHRÄGLAGE',
       patterns: [/^phi_lean$/i, /lean.?angle/i, /^roll$/i],
       units: ['deg','°','rad']},
    ],
    // v21.15 — Beschleunigungs-Analyse: Gasgriff + Schräglage
    'accel': [
      {id: 'throttle', label: 'GASGRIFF',
       patterns: [/^tp_2$/i, /^tpd$/i, /^tps$/i, /throttle/i, /^thr/i, /gas/i],
       units: ['%']},
      {id: 'lean', label: 'SCHRÄGLAGE',
       patterns: [/^phi_lean$/i, /lean.?angle/i, /^roll$/i],
       units: ['deg','°','rad']},
    ],
    'adv-brake': [
      {id: 'brake_pressure', label: 'BREMSDRUCK',
       patterns: [/^p_brake(_fr)?$/i, /brake.*press/i, /brk.*press/i],
       units: ['bar','psi','kpa']},
      {id: 'lean', label: 'SCHRÄGLAGE',
       patterns: [/^phi_lean$/i, /lean.?angle/i, /^roll$/i],
       units: ['deg','°','rad']},
    ],
    'adv-accel': [
      {id: 'throttle_grip', label: 'GASGRIFF',
       patterns: [/^tp_2$/i, /throttle.*grip/i, /^thr_grip$/i],
       units: ['%']},
      {id: 'throttle_butterfly', label: 'DROSSELKLAPPE',
       patterns: [/^tpd$/i, /throttle.*butterfly/i, /^thr_pos$/i, /^tps$/i],
       units: ['%']},
      {id: 'lean', label: 'SCHRÄGLAGE',
       patterns: [/^phi_lean$/i, /lean.?angle/i, /^roll$/i],
       units: ['deg','°','rad']},
    ],
    // v21.39 — Elektronik-Setup: Drehzahlen Front/Rear, Gasgriff, Lean,
    // TC-Status, WC-Status. Aus diesen Kanälen werden Slip-/Lockup-Events,
    // Hinterrad-Schlupf und TC/WC-Eingriffe abgeleitet.
    'electronics': [
      {id: 'wheel_speed_front', label: 'DREHZAHL VORDERRAD',
       patterns: [/^v_front$/i, /vehiclespeed.*front/i, /wheel.*front/i,
                  /front.*wheel.*speed/i, /^wsf$/i],
       units: ['km/h','kmh','mph','m/s','rpm']},
      {id: 'wheel_speed_rear', label: 'DREHZAHL HINTERRAD',
       patterns: [/^v_rear$/i, /vehiclespeed.*rear/i, /wheel.*rear/i,
                  /rear.*wheel.*speed/i, /^wsr$/i],
       units: ['km/h','kmh','mph','m/s','rpm']},
      {id: 'throttle', label: 'GASGRIFF',
       patterns: [/^tp_2$/i, /throttle.*grip/i, /^thr_grip$/i,
                  /^throttle$/i, /throttlegrip/i],
       units: ['%']},
      {id: 'lean', label: 'SCHRÄGLAGE',
       patterns: [/^phi_lean$/i, /lean.?angle/i, /^roll$/i],
       units: ['deg','°','rad']},
      {id: 'tc_status', label: 'STATUS TC',
       patterns: [/dtcwork/i, /^tc_status$/i, /^tc$/i, /traction.*control/i,
                  /^dtc$/i, /tcwork/i],
       units: []},
      {id: 'wc_status', label: 'STATUS WC',
       patterns: [/dwcwork/i, /^wc_status$/i, /^wc$/i, /wheelie.*control/i,
                  /^dwc$/i, /wcwork/i],
       units: []},
    ],
    // v22.7 — Fahrwerks-Setup: Federweg Gabel und Federweg Federbein.
    // Block-Detektor (flache Linie am Maximum mit scharfer Kante) + Histogramm
    // der Federweg-Geschwindigkeit (symmetrisch um 0).
    'suspension': [
      {id: 'suspension_fork', label: 'FEDERWEG GABEL',
       patterns: [/^s_susp_fr$/i, /^ACC_SuspTravel_F$/i, /^SUSF$/i,
                  /^Travel_Front$/i, /^Susp_fr_ddc$/i],
       units: ['mm','cm','%']},
      {id: 'suspension_shock', label: 'FEDERWEG FEDERBEIN',
       patterns: [/^s_susp_rr$/i, /^ACC_SuspTravel_R$/i, /^SUSR$/i,
                  /^Travel_Rear$/i, /^Susp_rr_ddc$/i],
       units: ['mm','cm','%']},
    ],
  };

  // v21.17 — Auto-Detect entfernt: Stefan möchte jede Rolle manuell zuordnen,
  // damit es keine Verwechslung mit "falsch geratenem" Kanal gibt.
  // v21.34 — Pre-fill aus persistierter Zuordnung (beim Upload gewählt).
  //   DATA.channel_roles = {role_id: channel_id, ...}. Jedes Tab das diese
  //   Rolle führt, übernimmt den Channel als Default. User kann weiterhin
  //   pro Tab überschreiben — Pre-Fill ist nur Startwert, keine Sperre.
  //   Wenn der persistierte Channel nicht in extras existiert (z.B. nach
  //   Re-Parse), bleibt der Slot leer wie zuvor.

  const state = { 'brake': {}, 'accel': {}, 'adv-brake': {}, 'adv-accel': {},
                  'electronics': {}, 'suspension': {} };

  // Mapping role_id → list of {tab, slotId}: tells us which slots to
  // pre-fill when a persisted role is set. Kept in sync with the SPECS
  // structure above (same role appears in multiple tabs under the same
  // slot-id; the 'throttle' role fills BOTH 'accel'/'throttle' and
  // 'adv-accel'/'throttle_grip' because both refer to the same sensor).
  const ROLE_TO_SLOTS = {
    'brake_pressure': [
      {tab: 'brake',     slotId: 'brake_pressure'},
      {tab: 'adv-brake', slotId: 'brake_pressure'},
    ],
    'lean': [
      {tab: 'brake',       slotId: 'lean'},
      {tab: 'accel',       slotId: 'lean'},
      {tab: 'adv-brake',   slotId: 'lean'},
      {tab: 'adv-accel',   slotId: 'lean'},
      {tab: 'electronics', slotId: 'lean'},
    ],
    'throttle': [
      {tab: 'accel',       slotId: 'throttle'},
      {tab: 'adv-accel',   slotId: 'throttle_grip'},
      {tab: 'electronics', slotId: 'throttle'},
    ],
    'throttle_butterfly': [
      {tab: 'adv-accel', slotId: 'throttle_butterfly'},
    ],
    // v21.39 — Elektronik-Rollen
    'wheel_speed_front': [
      {tab: 'electronics', slotId: 'wheel_speed_front'},
    ],
    'wheel_speed_rear': [
      {tab: 'electronics', slotId: 'wheel_speed_rear'},
    ],
    'tc_status': [
      {tab: 'electronics', slotId: 'tc_status'},
    ],
    'wc_status': [
      {tab: 'electronics', slotId: 'wc_status'},
    ],
    // v22.7 — Fahrwerks-Rollen
    'suspension_fork': [
      {tab: 'suspension', slotId: 'suspension_fork'},
    ],
    'suspension_shock': [
      {tab: 'suspension', slotId: 'suspension_shock'},
    ],
  };
  const persistedRoles = (DATA && DATA.channel_roles) || {};
  for (const roleId in persistedRoles){
    const chId = persistedRoles[roleId];
    if (!chId) continue;
    // Verify the channel still exists in extras (lap might have been
    // re-parsed since upload; cheap safety check).
    if (!extras.find(e => e.id === chId)) continue;
    const slots = ROLE_TO_SLOTS[roleId] || [];
    for (const s of slots){
      // Only set if the tab actually defines this slot — defensive
      // against schema drift between channel_roles.py and SPECS.
      const specHasSlot = (SPECS[s.tab] || []).some(r => r.id === s.slotId);
      if (!specHasSlot) continue;
      state[s.tab][s.slotId] = chId;
    }
  }

  function findExtra(id){ return extras.find(e => e.id === id) || null; }

  function renderTab(tab){
    const host = document.getElementById(tab + '-slots');
    if (!host) return;
    let html = '';
    SPECS[tab].forEach(role => {
      const cur = state[tab][role.id];
      const ch = cur ? findExtra(cur) : null;
      const cls = 'channel-slot';
      const curHtml = ch
        ? `<span class="cs-current">${escapeHTML(ch.name)}${ch.unit?(' ('+escapeHTML(ch.unit)+')'):''}</span>`
        : `<span class="cs-current none">— nicht zugeordnet —</span>`;
      html += `<div class="${cls}" data-tab="${tab}" data-role="${role.id}">
        <div class="cs-role">${role.label}</div>
        ${curHtml}
        <div class="cs-arrow">›</div>
      </div>`;
    });
    host.innerHTML = html;
    host.querySelectorAll('.channel-slot').forEach(el => {
      el.addEventListener('click', () => openRolePicker(el.dataset.tab, el.dataset.role));
    });
  }

  // --- Shared single-select modal
  const modal = document.getElementById('cr-modal');
  const tbody = document.getElementById('cr-table-body');
  const title = document.getElementById('cr-modal-title');
  const hint = document.getElementById('cr-modal-hint');
  const btnClose = document.getElementById('cr-modal-close');
  const btnClear = document.getElementById('cr-clear');
  const btnApply = document.getElementById('cr-apply');
  const search = document.getElementById('cr-search');
  let editing = null;

  function openRolePicker(tab, roleId){
    editing = {tab, roleId};
    const role = SPECS[tab].find(r => r.id === roleId);
    title.textContent = role ? ('KANAL FÜR ' + role.label) : 'KANAL WÄHLEN';
    hint.textContent = extras.length + ' verfügbar';
    search.value = '';
    buildTable('');
    modal.hidden = false;
    setTimeout(() => search.focus(), 0);
  }
  function close(){
    modal.hidden = true;
    editing = null;
  }
  function buildTable(q){
    q = (q || '').toLowerCase();
    const filtered = extras.filter(c =>
      !q || (c.name + ' ' + (c.unit||'')).toLowerCase().includes(q)
    );
    if (!filtered.length){
      tbody.innerHTML = '<div class="ch-empty">KEINE TREFFER</div>';
      return;
    }
    const cur = editing && state[editing.tab][editing.roleId];
    let rows = '';
    filtered.forEach(c => {
      const isAct = (c.id === cur);
      rows += `<label class="ch-row ${isAct?'active':''}" data-id="${c.id}">
        <span class="ch-col-on">
          <input type="radio" name="cr-pick" ${isAct?'checked':''} data-id="${c.id}">
        </span>
        <span class="ch-col-name">${escapeHTML(c.name)}</span>
        <span class="ch-col-unit">${escapeHTML(c.unit||'—')}</span>
        <span class="ch-col-min">${c.min.toFixed(2)}</span>
        <span class="ch-col-max">${c.max.toFixed(2)}</span>
        <span class="ch-col-mean">${c.mean.toFixed(2)}</span>
      </label>`;
    });
    tbody.innerHTML = rows;
  }
  const listeners = [];
  function notify(tab){
    listeners.forEach(fn => { try{ fn(tab); }catch(e){} });
  }

  btnClose.addEventListener('click', close);
  modal.addEventListener('click', e => { if (e.target === modal) close(); });
  document.addEventListener('keydown', e => {
    if (!modal.hidden && e.key === 'Escape') close();
  });
  search.addEventListener('input', () => buildTable(search.value));
  tbody.addEventListener('change', e => {
    const rb = e.target;
    if (!rb.matches('input[type="radio"]')) return;
    if (!editing) return;
    const id = rb.dataset.id;
    state[editing.tab][editing.roleId] = id;
    buildTable(search.value);
  });
  btnClear.addEventListener('click', () => {
    if (!editing) return;
    delete state[editing.tab][editing.roleId];
    buildTable(search.value);
  });
  btnApply.addEventListener('click', () => {
    const tab = editing && editing.tab;
    if (editing) renderTab(editing.tab);
    close();
    if (tab) notify(tab);
  });

  renderTab('brake');
  renderTab('accel');
  renderTab('adv-brake');
  renderTab('adv-accel');
  renderTab('electronics');
  renderTab('suspension');

  return {
    getAssignment: (tab, roleId) => {
      const id = state[tab] && state[tab][roleId];
      return id ? findExtra(id) : null;
    },
    getAllAssignments: (tab) => {
      const out = {};
      (SPECS[tab] || []).forEach(r => {
        const id = state[tab][r.id];
        out[r.id] = id ? findExtra(id) : null;
      });
      return out;
    },
    onChange: (fn) => { listeners.push(fn); },
  };
})();

// ============================================================================
// v21.45 — Marker ↔ Row Verlinkung (geteilt zwischen Bremsen-, Beschleunigung-
// und Elektronik-Analyse). Klick auf einen Trackmap-Marker highlighted die
// passende Tabellenzeile und scrollt sie in den Sichtbereich; Klick auf eine
// Zeile highlighted den Marker. Nochmaliger Klick auf das gleiche Element
// toggelt die Auswahl aus.
//
// v21.46 — Beidseitiger Autoscroll: Row-Klick scrollt zusätzlich den
// Trackmap-Wrap-Container ins Viewport. Marker-Klick scrollt die Row wie
// bisher. Auf welcher Seite der Klick startet, wird die jeweils ANDERE Seite
// ins Viewport gebracht (die Klickseite ist ohnehin sichtbar).
//
// Beide Seiten setzen `data-idx="<n>"` auf den jeweiligen Container (Row-DIV
// bzw. SVG-Gruppe). Der Helper bindet Click-Delegation an Host + SVG und
// toggelt die `.is-selected` Klasse auf allen Elementen mit gleichem data-idx.
// ============================================================================
// v22.0 — Vierter Parameter `onSelect`: Callback (eventIdx|null, source)
// wird bei jedem toggle aufgerufen. eventIdx = die geklickte data-idx (String)
// bei Selektion, null bei Deselektion. source = 'row' | 'map' | 'api'.
// Konsumenten (z.B. die Coach-Chart-Cursor-Sync) registrieren sich hier um
// auf Marker/Row-Klicks zu reagieren. Mehrfach-Registrierung wird gestackt;
// Re-Init des Helpers gibt dieselbe API zurück und der Callback wird auf
// die bereits laufende Instanz angehängt.
function setupMarkerRowLink(host, mapHost, mapWrap, onSelect){
  if (!host || !mapHost) return host && host._mrlApi || null;
  if (host._mrlBound){
    if (mapWrap) host._mrlMapWrap = mapWrap;
    if (typeof onSelect === 'function') host._mrlSelectListeners.push(onSelect);
    return host._mrlApi;
  }
  host._mrlMapWrap = mapWrap || null;
  host._mrlSelectListeners = [];
  if (typeof onSelect === 'function') host._mrlSelectListeners.push(onSelect);

  let selectedIdx = null;
  // Welche Seite die letzte Aktion ausgelöst hat — bestimmt, wohin wir scrollen.
  // 'map' = Klick auf einen Marker, Row ins Viewport scrollen.
  // 'row' = Klick auf eine Tabellenzeile, Trackmap-Wrap ins Viewport scrollen.
  // 'api' = programmatisch (clear/highlight ohne Klick) — nicht scrollen.
  let lastSource = 'api';

  function clearAll(){
    host.querySelectorAll('[data-idx].is-selected').forEach(el =>
      el.classList.remove('is-selected'));
    mapHost.querySelectorAll('[data-idx].is-selected').forEach(el =>
      el.classList.remove('is-selected'));
  }

  function notifySelect(idx){
    const listeners = host._mrlSelectListeners || [];
    for (const fn of listeners){
      try { fn(idx, lastSource); }
      catch (e){ console.error('mrl onSelect listener failed', e); }
    }
  }

  function highlight(idx){
    clearAll();
    if (idx == null) { selectedIdx = null; notifySelect(null); return; }
    const sel = '[data-idx="' + String(idx) + '"]';
    const rowEls = host.querySelectorAll(sel);
    rowEls.forEach(el => el.classList.add('is-selected'));
    mapHost.querySelectorAll(sel).forEach(el => el.classList.add('is-selected'));
    selectedIdx = idx;
    if (lastSource === 'map' && rowEls.length){
      rowEls[0].scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } else if (lastSource === 'row'){
      const wrap = host._mrlMapWrap;
      if (wrap) wrap.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    }
    notifySelect(idx);
  }

  function toggle(idx, source){
    if (idx == null) return;
    lastSource = source || 'api';
    if (String(idx) === String(selectedIdx)){
      clearAll();
      selectedIdx = null;
      notifySelect(null);
    } else {
      highlight(idx);
    }
  }

  function findIdxFromTarget(target, root){
    let el = target;
    while (el && el !== root){
      if (el.dataset && el.dataset.idx != null) return el.dataset.idx;
      el = el.parentNode;
    }
    return null;
  }

  host.addEventListener('click', (e) => {
    const idx = findIdxFromTarget(e.target, host);
    if (idx != null) toggle(idx, 'row');
  });
  mapHost.addEventListener('click', (e) => {
    const idx = findIdxFromTarget(e.target, mapHost);
    if (idx != null) toggle(idx, 'map');
  });

  host._mrlBound = true;
  host._mrlApi = {
    clear: () => {
      lastSource = 'api';
      const wasSelected = selectedIdx != null;
      clearAll();
      selectedIdx = null;
      if (wasSelected) notifySelect(null);
    },
    highlight: (idx) => { lastSource = 'api'; highlight(idx); },
    toggle:    (idx) => { toggle(idx, 'api'); },
    addSelectListener: (fn) => {
      if (typeof fn === 'function') host._mrlSelectListeners.push(fn);
    },
  };
  return host._mrlApi;
}


// ============================================================================
// v21.12 — Bremsanalyse.
//
// Drei Schritte:
//   1) Apex-Detection aus Track-Geometrie (lat/lon), validiert mit Lean.
//   2) Bremszonen finden (pressure > 5% peak, min 8 samples).
//   3) Pro Zone bewerten: Aufbau / Trail-Brake / Glätte / Brems-bis-Apex.
//
// Plus: Track-Map mit Bremsdruck-Einfärbung + Apex-Markern + Fehler-Markern
//       für "Bremse vor Apex zu früh gelöst".
// ============================================================================
const brakeAnalysis = (function(){
  const host = document.getElementById('brake-analysis');
  if (!host) return null;
  const mapHost  = document.getElementById('brake-trackmap');
  const mapWrap  = document.getElementById('brake-trackmap-wrap');

  // -- Track-Geometrie: Krümmung pro Distanz -----------------------------------
  //
  // Heading-Änderung pro Distanz ist die Krümmung (1/m). Wir glätten
  // kräftig (~30m window) damit GPS-Noise nicht zu lokalen Maxima
  // führt. Lokale Maxima > 50% des Run-Maxes sind Kurvenkandidaten.
  function detectApices(lat, lon, dist, lData){
    const n = lat.length;
    if (n < 50) return [];

    // Heading aus dlat/dlon (klein-Winkel-Approximation reicht: wir wollen
    // nur Änderungen, keine absoluten Winkel)
    const heading = new Array(n).fill(0);
    for (let i = 1; i < n; i++){
      const dy = lat[i] - lat[i-1];
      const dx = lon[i] - lon[i-1];
      heading[i] = Math.atan2(dy, dx);
    }
    heading[0] = heading[1];

    // Unwrap heading (kontinuierlich machen)
    for (let i = 1; i < n; i++){
      let d = heading[i] - heading[i-1];
      while (d > Math.PI)  { heading[i] -= 2*Math.PI; d = heading[i] - heading[i-1]; }
      while (d < -Math.PI) { heading[i] += 2*Math.PI; d = heading[i] - heading[i-1]; }
    }

    // Lokales Krümmungs-Maß: |dheading / ddist| über ein gleitendes Fenster
    // Fenster ~ 20 m
    const lapLen = dist[n-1] - dist[0];
    const avgStep = lapLen / Math.max(1, n - 1);
    const win = Math.max(3, Math.round(20 / avgStep));

    const curv = new Array(n).fill(0);
    for (let i = win; i < n - win; i++){
      const dh = heading[i + win] - heading[i - win];
      const dd = dist[i + win] - dist[i - win];
      curv[i] = dd > 0 ? Math.abs(dh / dd) : 0;
    }

    // Glättung über ~30 m (Boxcar)
    const sm = Math.max(2, Math.round(30 / avgStep));
    const smoothed = new Array(n).fill(0);
    for (let i = 0; i < n; i++){
      let s = 0, c = 0;
      for (let k = Math.max(0, i - sm); k <= Math.min(n - 1, i + sm); k++){
        s += curv[k]; c++;
      }
      smoothed[i] = c ? s / c : 0;
    }

    // Lokale Maxima finden über Track-Distanz; Mindestabstand 50m
    const maxC = smoothed.reduce((a, b) => Math.max(a, b), 0);
    if (maxC <= 0) return [];
    const TH = maxC * 0.40;  // 40% des Runden-Maximums
    const minApart = Math.round(50 / avgStep);

    const candidates = [];
    for (let i = win; i < n - win; i++){
      if (smoothed[i] < TH) continue;
      // Lokales Maximum: höher als ±minApart/2 Nachbarn
      let isMax = true;
      const r = Math.max(1, Math.floor(minApart / 2));
      for (let k = Math.max(0, i - r); k <= Math.min(n - 1, i + r); k++){
        if (k !== i && smoothed[k] > smoothed[i]) { isMax = false; break; }
      }
      if (!isMax) continue;
      // Mindestabstand zum letzten Kandidaten
      if (candidates.length && (i - candidates[candidates.length - 1].i) < minApart) {
        // Falls neuer Kandidat höher ist: ersetze
        if (smoothed[i] > smoothed[candidates[candidates.length - 1].i]){
          candidates[candidates.length - 1] = { i, curv: smoothed[i] };
        }
        continue;
      }
      candidates.push({ i, curv: smoothed[i] });
    }

    // Lean-Validation: jeder Geometrie-Apex muss ein lokales |lean|-Maximum
    // innerhalb ±15 m haben (falls Lean-Kanal vorhanden).
    let validated = candidates;
    if (lData && lData.length === n){
      validated = candidates.filter(c => {
        const halfWin = Math.max(1, Math.round(15 / avgStep));
        const lo = Math.max(0, c.i - halfWin);
        const hi = Math.min(n - 1, c.i + halfWin);
        let leanPeak = 0;
        for (let k = lo; k <= hi; k++) leanPeak = Math.max(leanPeak, Math.abs(lData[k]));
        // mindestens 15° Schräglage erwartet — sonst war's eine "Gerade mit Bumps"
        return leanPeak >= 15;
      });
    }

    return validated.map(c => ({
      idx: c.i,
      distance_m: dist[c.i] || 0,
    }));
  }

  function render(){
    // Defensive: wrap everything so a single bad data point doesn't kill the panel
    try {
      renderInner();
    } catch (e){
      host.innerHTML = `<div class="ba-empty" style="color:#ffaa00">
        FEHLER IN DER BREMSANALYSE — ${escapeHTML(e.message || String(e))}
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
    }
  }

  function renderInner(){
    const extras = DATA.extras || [];
    if (!extras.length){
      host.innerHTML = '<div class="ba-empty">' +
        '→ DIESE RUNDE HAT KEINE ZUSATZ-KANÄLE (Bremsdruck/Schräglage). ' +
        'Die Bremsanalyse braucht mindestens einen Bremsdruck-Kanal.</div>';
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    const assignment = channelRoles.getAllAssignments('brake');
    const press = assignment.brake_pressure;
    const lean  = assignment.lean;
    if (!press){
      // v21.17 — Pflicht-Kanal Gate. Ohne Bremsdruck keine Analyse, kein Track-Map.
      // v21.44 — Channel-Liste entfernt, die Channels stehen schon im Picker oben.
      host.innerHTML = `<div class="ba-empty" style="text-align:left;line-height:1.7">
        <div style="color:var(--accent);font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:.04em;margin-bottom:8px">
          BREMSDRUCK-KANAL FEHLT
        </div>
        <div style="color:var(--ink-dim);text-transform:none;letter-spacing:0;font-size:13px">
          Klick oben auf <strong style="color:var(--ink)">BREMSDRUCK</strong> und wähle den passenden Kanal aus.
          Die Analyse startet, sobald der Bremsdruck-Kanal zugeordnet ist.
        </div>
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    const pData = press.data || [];
    const lData = lean ? (lean.data || []) : null;
    const dist  = DATA.distance || [];
    const time  = DATA.time     || [];
    const lat   = DATA.lat      || [];
    const lon   = DATA.lon      || [];
    if (pData.length < 10 || dist.length !== pData.length){
      host.innerHTML = `<div class="ba-empty">
        BREMSDRUCK-KANAL HAT KEINE VERWERTBAREN DATEN
        (${pData.length} Samples, erwartet ${dist.length})
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    const peakAll = pData.reduce((a, b) => Math.max(a, b), 0);
    if (peakAll <= 0){
      host.innerHTML = '<div class="ba-empty">BREMSDRUCK BLEIBT NULL — KEINE BREMSZONEN ERKENNBAR</div>';
      if (mapWrap) mapWrap.hidden = true;
      return;
    }
    // v22.10 — Schwellen aus THRESHOLDS.brake.
    const brCfg = (window.THRESHOLDS && window.THRESHOLDS.brake) || {};
    const TH = peakAll * (brCfg.zone_threshold_fraction ?? 0.05);
    const zoneMinSamples = brCfg.zone_min_samples ?? 8;

    // Bremszonen
    const zones = [];
    let i = 0;
    while (i < pData.length){
      if (pData[i] > TH){
        let j = i;
        while (j < pData.length && pData[j] > TH) j++;
        if (j - i >= zoneMinSamples) zones.push({ from: i, to: j - 1 });
        i = j;
      } else {
        i++;
      }
    }
    if (!zones.length){
      host.innerHTML = '<div class="ba-empty">KEINE BREMSZONEN OBERHALB 5% PEAK GEFUNDEN</div>';
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    // Apex-Detection (Geometrie + Lean-Validation)
    const apices = (lat.length === pData.length && lat.length >= 50)
      ? detectApices(lat, lon, dist, lData)
      : [];

    // Jede Bremszone bekommt ihren "Folge-Apex" zugeordnet:
    // Apex muss im Bereich [z.from, z.to + apex_search_distance_m] liegen
    // (auch innerhalb der Bremszone — bei sauberem Trail-Braking ist der
    // Apex genau dort, wo der Druck noch nicht ganz weg ist).
    const apexSearchDist = brCfg.apex_search_distance_m ?? 200;
    zones.forEach(z => {
      const zEndDist = dist[z.to] || 0;
      let nextApex = null;
      for (const a of apices){
        if (a.idx >= z.from && (a.distance_m - zEndDist) < apexSearchDist){
          nextApex = a; break;
        }
      }
      z.apex = nextApex;
    });

    const results = zones.map((z, idx) => analyseZone(idx + 1, z, pData, lData, dist, time, peakAll));

    // Summary
    const sumGood = results.filter(r => r.overall === 'good').length;
    const sumWarn = results.filter(r => r.overall === 'warn').length;
    const sumBad  = results.filter(r => r.overall === 'bad').length;
    let summaryHl = '';
    if (sumBad >= 2 || (sumBad >= 1 && sumWarn >= 2)){
      summaryHl = 'FOKUS — Bei mehreren Bremszonen ist Aufbau oder Modulation auffällig.';
    } else if (sumGood === results.length){
      summaryHl = 'GUT — Saubere Bremsmanöver durch die ganze Runde.';
    } else if (sumWarn + sumBad >= 1){
      summaryHl = 'HINWEISE — Einzelne Bremszonen mit Verbesserungspotential.';
    } else {
      summaryHl = 'OK — Insgesamt solide Bremstechnik.';
    }
    // v21.17 — Lean-Hinweis als eigener Banner, deutlich sichtbar.
    const leanBanner = lean ? '' :
      `<div class="ba-note-warn">
         ⚠ SCHRÄGLAGEN-KANAL NICHT ZUGEORDNET —
         Trail-Brake-Korrelation und Apex-Validierung werden ausgelassen.
         Die übrige Bewertung (Aufbau, Glättung, Apex über GPS-Geometrie) bleibt gültig.
       </div>`;

    let html = `
      <div class="ba-summary">
        <div class="bas-headline">${escapeHTML(summaryHl)}</div>
        <div class="bas-counts">
          <span>${results.length} BREMSZONEN</span>
          <span class="n" style="color:var(--accel)">${sumGood} OK</span>
          <span class="n" style="color:#ffaa00">${sumWarn} HINWEIS</span>
          <span class="n" style="color:var(--brake)">${sumBad} FOKUS</span>
          ${apices.length ? `<span>${apices.length} APICES</span>` : ''}
        </div>
      </div>
      ${leanBanner}`;

    results.forEach(r => { html += renderZoneCard(r); });
    host.innerHTML = html;

    // Track-Map
    if (mapHost && lat.length === pData.length && lat.length >= 10){
      renderTrackMap(lat, lon, pData, peakAll, apices, results);
      mapWrap.hidden = false;
    } else {
      if (mapWrap) mapWrap.hidden = true;
    }

    // v22.0 — Index-Mapping aus Event-Idx (1..N) zu Sample-Index. Identische
    // Anchor-Logik wie im renderTrackMap (Apex falls vorhanden, sonst Zonen-
    // Ende). Wird beim Selektions-Callback unten gelesen.
    const idxToSample = {};
    results.forEach(r => {
      const anchor = (r.apex && r.apex.idx != null) ? r.apex.idx : r.to;
      if (anchor != null && anchor >= 0 && anchor < (DATA.distance || []).length){
        idxToSample[String(r.idx)] = anchor;
      }
    });

    // v21.45 — Marker ↔ Row Verlinkung (sticky, klickbar)
    // v22.0 — onSelect-Callback setzt zusätzlich den Chart-Cursor.
    const mrl = setupMarkerRowLink(host, mapHost, mapWrap, (eventIdx) => {
      const chart = window._coachCharts && window._coachCharts.brake;
      if (!chart) return;
      if (eventIdx == null){
        chart.clearStickyCursor();
      } else {
        const sample = idxToSample[String(eventIdx)];
        if (sample != null) chart.setStickyCursor(sample);
      }
    });
    if (mrl) mrl.clear();
  }

  // -- Per-zone metrics + scoring ----------------------------------------------
  function analyseZone(idx, z, pData, lData, dist, time, peakAll){
    const from = z.from, to = z.to;
    const slice = pData.slice(from, to + 1);
    const peakLocal = slice.reduce((a, b) => Math.max(a, b), 0);
    const peakIdxLocal = slice.indexOf(peakLocal);
    const peakIdx = from + peakIdxLocal;
    // v22.10 — Schwellen aus THRESHOLDS.brake.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.brake) || {};
    const lowFrac      = cfg.build_low_frac      ?? 0.10;
    const highFrac     = cfg.build_high_frac     ?? 0.90;
    const goodSec      = cfg.build_good_seconds  ?? 0.30;
    const warnSec      = cfg.build_warn_seconds  ?? 0.60;

    // Aufbau-Phase
    const buildSlice = pData.slice(from, peakIdx + 1);
    let i10 = 0, i90 = buildSlice.length - 1;
    for (let k = 0; k < buildSlice.length; k++){
      if (buildSlice[k] >= lowFrac * peakLocal){ i10 = k; break; }
    }
    for (let k = buildSlice.length - 1; k >= i10; k--){
      if (buildSlice[k] >= highFrac * peakLocal){ i90 = k; break; }
    }
    const t10 = time[from + i10] || 0;
    const t90 = time[from + i90] || 0;
    const buildTime = Math.max(0, t90 - t10);

    let buildScore;
    if (buildTime < goodSec)      buildScore = 'good';
    else if (buildTime < warnSec) buildScore = 'warn';
    else                          buildScore = 'bad';

    // Abbau-Phase
    const fadeFrom = peakIdx, fadeTo = to;
    const fadeP = pData.slice(fadeFrom, fadeTo + 1);
    const fadeL = lData ? lData.slice(fadeFrom, fadeTo + 1) : null;

    // Trail-Brake-Korrelation
    let leanScore = null, leanCorr = null;
    if (fadeL && fadeL.length >= 5){
      const absL = fadeL.map(Math.abs);
      const negP = fadeP.map(v => -v);
      leanCorr = pearson(absL, negP);
      const trailGood = cfg.trail_corr_good ?? 0.4;
      const trailWarn = cfg.trail_corr_warn ?? 0.1;
      if (leanCorr === null)            leanScore = null;
      else if (leanCorr > trailGood)    leanScore = 'good';
      else if (leanCorr > trailWarn)    leanScore = 'warn';
      else                              leanScore = 'bad';
    }

    // Smoothness (Pumps im Abbau)
    let pumps = 0;
    let trough = peakLocal;
    let lastWasUp = false;
    const pumpFrac = cfg.smooth_pump_threshold_frac ?? 0.10;
    for (let k = 1; k < fadeP.length; k++){
      const prev = fadeP[k-1], cur = fadeP[k];
      if (cur < prev){
        trough = Math.min(trough, cur);
        lastWasUp = false;
      } else if (cur > prev && !lastWasUp){
        lastWasUp = true;
      }
      if (cur > trough + pumpFrac * peakLocal){
        pumps++;
        trough = cur;
        lastWasUp = false;
      }
    }
    let smoothScore;
    if (pumps === 0)      smoothScore = 'good';
    else if (pumps === 1) smoothScore = 'warn';
    else                  smoothScore = 'bad';

    // v21.12 — "Bremse bis Scheitel" (apexScore)
    // Mittel: Druck fällt < 10% peakLocal UND bleibt < 10% für > 0.2s VOR dem Scheitel.
    let apexScore = null;       // null = unbestimmt (kein Apex)
    let apexReleaseGap_m = null; // Distanz vom Brems-Ende bis Apex (m), falls vorhanden
    let earlyReleaseHits = [];   // {idx_start, idx_end, durationS} für Track-Map-Marker
    if (z.apex){
      const apexI = z.apex.idx;
      apexReleaseGap_m = (dist[apexI] || 0) - (dist[to] || 0);

      // Scan vom Zone-Anfang bis Apex: finde zusammenhängende Bereiche
      // wo p < apex_release_low_frac und dauer > apex_release_min_seconds —
      // falls einer komplett VOR dem Apex liegt, ist das ein "release before apex".
      const lowFracApex = cfg.apex_release_low_frac     ?? 0.10;
      const minSecApex  = cfg.apex_release_min_seconds  ?? 0.2;
      const priorPeakFrac = cfg.apex_release_requires_prior_peak_frac ?? 0.50;
      const lowTH = lowFracApex * peakLocal;
      const sIdx = from;
      const eIdx = Math.min(apexI, pData.length - 1);
      let runStart = -1;
      for (let k = sIdx; k <= eIdx; k++){
        if (pData[k] < lowTH){
          if (runStart < 0) runStart = k;
        } else {
          if (runStart >= 0){
            const dur = (time[k - 1] || 0) - (time[runStart] || 0);
            // Run muss > minSecApex sein UND vor dem Apex liegen (k-1 < apexI)
            if (dur > minSecApex && (k - 1) < apexI){
              // Aber: nur "echte Bremse-gelöst" Vorfälle.
              // Ein Run am Anfang der Zone (vor dem ersten richtigen Aufbau)
              // ist kein Fehler. Wir verlangen: davor MUSS schon mal
              // p > priorPeakFrac * peakLocal erreicht worden sein.
              let hadPeak = false;
              for (let m = sIdx; m < runStart; m++){
                if (pData[m] > priorPeakFrac * peakLocal){ hadPeak = true; break; }
              }
              if (hadPeak){
                earlyReleaseHits.push({
                  idx_start: runStart,
                  idx_end: k - 1,
                  durationS: dur,
                });
              }
            }
            runStart = -1;
          }
        }
      }
      // Auch ein offener Run der bis vor Apex anhält
      if (runStart >= 0 && runStart < apexI){
        const dur = (time[eIdx] || 0) - (time[runStart] || 0);
        if (dur > minSecApex){
          let hadPeak = false;
          for (let m = sIdx; m < runStart; m++){
            if (pData[m] > priorPeakFrac * peakLocal){ hadPeak = true; break; }
          }
          if (hadPeak){
            earlyReleaseHits.push({
              idx_start: runStart,
              idx_end: eIdx,
              durationS: dur,
            });
          }
        }
      }

      if (earlyReleaseHits.length === 0){
        // Druck wird konsequent bis (nahe) Apex gehalten → gut
        apexScore = 'good';
      } else {
        // Einmal kurz gelöst = warn, mehrfach oder lange = bad
        const longest = Math.max(...earlyReleaseHits.map(h => h.durationS));
        if (earlyReleaseHits.length >= 2 || longest > 0.5) apexScore = 'bad';
        else                                                apexScore = 'warn';
      }
    }

    // Overall
    const scores = [buildScore, smoothScore];
    if (leanScore) scores.push(leanScore);
    if (apexScore) scores.push(apexScore);
    let overall;
    if (scores.includes('bad'))      overall = 'bad';
    else if (scores.includes('warn')) overall = 'warn';
    else                              overall = 'good';

    return {
      idx,
      from, to,
      distStart: dist[from] || 0,
      distEnd:   dist[to]   || 0,
      peakLocal,
      buildTime, buildScore,
      leanCorr,  leanScore,
      pumps,     smoothScore,
      apex:      z.apex || null,
      apexReleaseGap_m,
      apexScore,
      earlyReleaseHits,
      overall,
      sparkData: slice,
      sparkLean: lData ? lData.slice(from, to + 1).map(Math.abs) : null,
    };
  }

  function pearson(xs, ys){
    const n = xs.length;
    if (n < 3 || ys.length !== n) return null;
    let sx = 0, sy = 0;
    for (let i = 0; i < n; i++){ sx += xs[i]; sy += ys[i]; }
    const mx = sx / n, my = sy / n;
    let num = 0, dx2 = 0, dy2 = 0;
    for (let i = 0; i < n; i++){
      const dx = xs[i] - mx, dy = ys[i] - my;
      num += dx * dy; dx2 += dx*dx; dy2 += dy*dy;
    }
    const den = Math.sqrt(dx2 * dy2);
    if (!isFinite(den) || den === 0) return null;
    return num / den;
  }

  // -- Render one zone card ----------------------------------------------------
  function renderZoneCard(r){
    const fmtM = (m) => Math.round(m) + ' m';
    const where = fmtM(r.distStart) + ' → ' + fmtM(r.distEnd);

    let pills = '';
    pills += `<span class="bz-pill ${r.buildScore}">AUFBAU ${r.buildTime.toFixed(2)}s</span>`;
    if (r.leanScore){
      const corrStr = (r.leanCorr >= 0 ? '+' : '') + r.leanCorr.toFixed(2);
      pills += `<span class="bz-pill ${r.leanScore}">SCHRÄGLAGE r=${corrStr}</span>`;
    }
    pills += `<span class="bz-pill ${r.smoothScore}">GLÄTTUNG ${r.pumps===0?'sauber':r.pumps+'× pump'}</span>`;
    if (r.apexScore){
      let apexLabel = '';
      if (r.apexScore === 'good'){
        apexLabel = `BIS APEX`;
      } else {
        const longest = Math.max(...r.earlyReleaseHits.map(h => h.durationS));
        apexLabel = `VOR APEX GELÖST ${longest.toFixed(2)}s`;
      }
      pills += `<span class="bz-pill ${r.apexScore}">${apexLabel}</span>`;
    }

    let notes = '';
    if (r.buildScore === 'bad'){
      notes += `<div><span class="nh">Aufbau zu langsam:</span> ${r.buildTime.toFixed(2)}s vom Anbremsen bis Spitzendruck. Knackiger anbremsen, mehr Vertrauen in den Reifen.</div>`;
    } else if (r.buildScore === 'warn'){
      notes += `<div><span class="nh">Aufbau okay, geht aber schneller:</span> ${r.buildTime.toFixed(2)}s. Ideal: unter 0.3s.</div>`;
    } else {
      notes += `<div><span class="nh">Aufbau gut:</span> ${r.buildTime.toFixed(2)}s — knackiger Druckaufbau.</div>`;
    }
    if (r.leanScore === 'bad'){
      notes += `<div><span class="nh">Trail-Brake-Korrelation schwach:</span> Druck wird nicht synchron mit der Schräglage zurückgenommen. Bei zunehmendem Lean weiter modulieren.</div>`;
    } else if (r.leanScore === 'warn'){
      notes += `<div><span class="nh">Trail-Brake okay:</span> Korrelation positiv, aber nicht stark ausgeprägt.</div>`;
    } else if (r.leanScore === 'good'){
      notes += `<div><span class="nh">Sauberes Trail-Braking:</span> Druck wird mit zunehmender Schräglage konsequent abgebaut.</div>`;
    }
    if (r.smoothScore === 'bad'){
      notes += `<div><span class="nh">Pumpen erkannt:</span> ${r.pumps} signifikante Druckspitzen im Abbau. Konsequenter modulieren statt nachgreifen.</div>`;
    } else if (r.smoothScore === 'warn'){
      notes += `<div><span class="nh">Eine Korrektur im Abbau:</span> einmal nachgreifen ist okay, aber prüfe ob's vermeidbar war.</div>`;
    }
    if (r.apexScore === 'bad'){
      const longest = Math.max(...r.earlyReleaseHits.map(h => h.durationS));
      notes += `<div><span class="nh">Bremse zu früh gelöst:</span> Druck fiel ${r.earlyReleaseHits.length}× unter 10% Peak vor dem Scheitelpunkt — längste Lücke ${longest.toFixed(2)}s. Trail-Brake bis in den Apex tragen, das Bike braucht Druck auf dem Vorderrad fürs Einlenken.</div>`;
    } else if (r.apexScore === 'warn'){
      const longest = Math.max(...r.earlyReleaseHits.map(h => h.durationS));
      notes += `<div><span class="nh">Kurze Brems-Lücke vor Apex:</span> Druck war ${longest.toFixed(2)}s unter 10%. Geht knackiger — weiter modulieren bis ins Einlenken.</div>`;
    } else if (r.apexScore === 'good'){
      notes += `<div><span class="nh">Bis zum Scheitel gebremst:</span> Druck wird konsequent in den Apex getragen.</div>`;
    }

    const spark = renderSparkline(r.sparkData, r.sparkLean);

    return `
      <div class="brake-zone" data-idx="${r.idx}" data-overall="${r.overall}">
        <div class="bz-idx">#${r.idx}</div>
        <div class="bz-mid">
          <div class="bz-where">${where}</div>
          <div class="bz-pills">${pills}</div>
          <div class="bz-notes">${notes}</div>
        </div>
        <div class="bz-spark">
          ${spark}
          <span class="sp-label">DRUCK${r.sparkLean ? ' + LEAN' : ''}</span>
        </div>
      </div>`;
  }

  function renderSparkline(p, lean){
    const W = 200, H = 60;
    const n = p.length;
    const maxP = p.reduce((a, b) => Math.max(a, b), 0) || 1;
    const pPath = p.map((v, i) => {
      const x = (i / (n - 1)) * W;
      const y = H - (v / maxP) * (H - 4) - 2;
      return (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
    }).join('');
    let leanPath = '';
    if (lean){
      const maxL = lean.reduce((a, b) => Math.max(a, b), 0) || 1;
      leanPath = lean.map((v, i) => {
        const x = (i / (n - 1)) * W;
        const y = H - (v / maxL) * (H - 4) - 2;
        return (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
      }).join('');
    }
    return `
      <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
        ${leanPath ? `<path d="${leanPath}" stroke="#666" stroke-width="1" fill="none" opacity="0.7"/>` : ''}
        <path d="${pPath}" stroke="var(--accent)" stroke-width="2" fill="none"/>
      </svg>`;
  }

  // -- Track-Map: track-Pfad eingefärbt nach Bremsdruck ------------------------
  // v21.24 — tile/zoomCtl werden lazy beim ersten Aufruf erzeugt und persistieren
  // über folgende renderTrackMap-Aufrufe (z.B. wenn Channel-Slots umgesetzt werden).
  let tile = null, zoomCtl = null;
  let _lastBgState = { args: null };

  function renderTrackMap(lat, lon, pData, peakAll, apices, results){
    _lastBgState.args = [lat, lon, pData, peakAll, apices, results];
    const W = 1200, H = 600, PAD = 40;
    const n = lat.length;
    const latMin = Math.min.apply(null, lat), latMax = Math.max.apply(null, lat);
    const lonMin = Math.min.apply(null, lon), lonMax = Math.max.apply(null, lon);
    const latRange = latMax - latMin, lonRange = lonMax - lonMin;
    const cosLat = Math.cos((latMin + latMax) / 2 * Math.PI / 180);
    const wMeters = lonRange * 111000 * cosLat;
    const hMeters = latRange * 111000;
    const aspectMap = hMeters > 0 ? wMeters / hMeters : 1;
    const aspectVp = (W - 2*PAD) / (H - 2*PAD);
    let scaleX, scaleY, ox, oy;
    if (aspectMap > aspectVp){
      scaleX = (W - 2*PAD) / lonRange;
      scaleY = scaleX / cosLat;
      ox = PAD;
      oy = PAD + ((H - 2*PAD) - latRange * scaleY) / 2;
    } else {
      scaleY = (H - 2*PAD) / latRange;
      scaleX = scaleY * cosLat;
      oy = PAD;
      ox = PAD + ((W - 2*PAD) - lonRange * scaleX) / 2;
    }
    const proj = (la, lo) => ({
      x: ox + (lo - lonMin) * scaleX,
      y: oy + (latMax - la) * scaleY,
    });

    // Lazy init für Tile-Helfer und Zoom-Pan (überlebt re-renders).
    if (!tile){
      tile = makeTileLayer({
        svg: mapHost, W, H, proj,
        latMin, latMax, lonMin, lonMax, padding: 0.10,
      });
    }
    if (!zoomCtl){
      zoomCtl = makeZoomPan({ svg: mapHost, W, H, minZoom: 1, maxZoom: 8 });
    }

    // Hintergrund-Track — durchgehende Linie, gut sichtbar.
    // v21.18: vorher dünn-gestrichelt und kaum erkennbar; jetzt 2.5px solid.
    let html = '';
    if (tile.active) html += tile.buildLayer();
    let bgPath = '';
    for (let i = 0; i < n; i++){
      const p = proj(lat[i], lon[i]);
      bgPath += (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
    }
    html += `<path class="bt-track-bg" d="${bgPath}" stroke-width="2.5" fill="none" stroke-linejoin="round"/>`;

    // Bremsdruck-Farbsegmente. Wir zeichnen jeden Segment einzeln mit
    // der Farbe abhängig von p[i] / peakAll.
    for (let i = 1; i < n; i++){
      const intensity = Math.max(0, Math.min(1, pData[i] / peakAll));
      if (intensity < 0.05) continue;  // off-brake: nur Hintergrund-Linie
      const alpha = 0.35 + 0.65 * intensity;
      const w = 3 + 5 * intensity;  // 3..8 px
      const p1 = proj(lat[i-1], lon[i-1]);
      const p2 = proj(lat[i],   lon[i]);
      const color = `rgba(199,125,255,${alpha.toFixed(2)})`;
      html += `<line x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${p2.x.toFixed(1)}" y2="${p2.y.toFixed(1)}" stroke="${color}" stroke-width="${w.toFixed(1)}" stroke-linecap="round"/>`;
    }

    // Apex-Marker (weiße Punkte für ALLE erkannten Apices)
    apices.forEach(a => {
      const p = proj(lat[a.idx], lon[a.idx]);
      html += `<g><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="6" fill="none" stroke="#f5f5f0" stroke-width="2"/><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.5" fill="#f5f5f0"/></g>`;
    });

    // v21.17 — Pro Zone EIN farbiger Index-Marker (#N) am Anchor-Punkt
    // (zugeordneter Apex, sonst Zonen-Ende). Farbe = Overall-Score.
    // Damit ist jede Zone aus der Liste unten auch oben auf der Map zu sehen.
    const scoreColor = {
      good: '#7dd17d',  // grün
      warn: '#ffaa00',  // orange
      bad:  '#ff3d3d',  // rot
    };
    results.forEach(r => {
      const anchorIdx = (r.apex && r.apex.idx != null) ? r.apex.idx : r.to;
      if (anchorIdx == null || anchorIdx < 0 || anchorIdx >= lat.length) return;
      const p = proj(lat[anchorIdx], lon[anchorIdx]);
      const color = scoreColor[r.overall] || '#888';
      // Offset oben-rechts damit Apex-Punkt darunter sichtbar bleibt
      const cx = p.x + 16, cy = p.y - 16;
      html += `<g data-idx="${r.idx}">
        <line x1="${p.x.toFixed(1)}" y1="${p.y.toFixed(1)}" x2="${cx.toFixed(1)}" y2="${cy.toFixed(1)}" stroke="${color}" stroke-width="1" opacity="0.6"/>
        <circle class="mk-bubble" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="11" fill="${color}" stroke="#0a0a0a" stroke-width="1.5"/>
        <text x="${cx.toFixed(1)}" y="${(cy + 4).toFixed(1)}" font-family="JetBrains Mono" font-size="11" font-weight="600" fill="#0a0a0a" text-anchor="middle">${r.idx}</text>
      </g>`;
    });

    // Fehler-Marker für "Bremse zu früh gelöst" — kleiner als der Zone-Marker,
    // sitzt am Ort des Druck-Drops (nicht am Apex), damit der Fahrer sieht
    // wo genau auf der Strecke der Fehler passiert ist.
    results.forEach(r => {
      if (!r.apexScore || (r.apexScore !== 'bad' && r.apexScore !== 'warn')) return;
      r.earlyReleaseHits.forEach(h => {
        const i = h.idx_start;
        if (i == null || i < 0 || i >= lat.length) return;
        const p = proj(lat[i], lon[i]);
        const color = r.apexScore === 'bad' ? '#ff3d3d' : '#ffaa00';
        html += `<g>
          <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="8" fill="none" stroke="${color}" stroke-width="2"/>
          <text x="${p.x.toFixed(1)}" y="${(p.y + 4).toFixed(1)}" font-family="Bebas Neue" font-size="12" fill="${color}" text-anchor="middle">⚠</text>
        </g>`;
      });
    });

    mapHost.innerHTML = html;
    // v21.24 — Spinner während Tile-Load
    if (tile.active) tile.bindLoadEvents(mapWrap);
    else tile.hideSpinner();
  }

  // v21.24 — Helper: rerender mit gemerkter args (für Toggle ohne Slot-Change)
  function rerenderMap(){
    if (_lastBgState.args) renderTrackMap.apply(null, _lastBgState.args);
  }
  function setMapview(on){
    if (!tile){ rerenderMap(); }  // erst rendern damit tile existiert
    if (!tile) return;
    on = !!on;
    if (on === tile.active) return;
    tile.active = on;
    rerenderMap();
  }

  channelRoles.onChange(tab => {
    if (tab === 'brake') render();
  });
  render();
  // v21.15 — detectApices wird auch von der Beschleunigungs-Analyse genutzt
  // v21.24 — setMapview für Toggle
  return { render, detectApices, setMapview };
})();

// ============================================================================
// v21.15 — Beschleunigungs-Analyse.
//
// Anforderung (Stefan): "Gleichmäßiges Aufziehen ab dem Scheitel sehen
//   und auf den Geraden Vollgas. Schlecht wäre ungleichmäßiges Schwanken,
//   zu spätes Aufziehen nach dem Scheitel oder Geraden ohne Vollgas."
//
// Algorithmus:
//   1) Apex-Detection: dieselbe Funktion wie brakeAnalysis (Geometrie + Lean).
//   2) Pro Apex: eine Beschleunigungs-Phase vom Apex bis kurz vor der
//      nächsten Bremszone (oder Lap-Ende).
//   3) Pro Phase bewerten:
//        a) Apex→Vollgas-Zeit: vom Apex bis Throttle ≥ 95% das erste Mal.
//             good   < 1.0s
//             warn   < 2.0s
//             bad    ≥ 2.0s (oder gar nicht erreicht)
//        b) Aufzieh-Glättung: Anzahl signifikanter Throttle-Rücknahmen
//           (>10% Drop nach lokalem Maximum) im Anstiegs-Abschnitt.
//             good 0 · warn 1 · bad ≥ 2
//        c) Vollgas-Anteil auf Geraden: Innerhalb der Phase Samples mit
//           |lean| < 10° identifizieren ("Gerade"). Davon Anteil mit
//           throttle ≥ 95%.
//             good   > 80%
//             warn   > 50%
//             bad    ≤ 50%
//           (Wird übersprungen wenn keine "Gerade" in der Phase liegt
//            oder Lean-Kanal fehlt.)
//
// Track-Map: Strecke eingefärbt nach Throttle (lila wie Brakes, aber
//   höhere Intensität = mehr Gas). Apex-Marker plus rote ⚠-Marker an
//   Stellen wo Throttle eingebrochen ist trotz aufrechtem Bike.
// ============================================================================
const accelAnalysis = (function(){
  const host = document.getElementById('accel-analysis');
  if (!host) return null;
  const mapHost = document.getElementById('accel-trackmap');
  const mapWrap = document.getElementById('accel-trackmap-wrap');

  // Channel auto-detect → Apex-Threshold heuristic für Throttle in 0..100% range.
  // Wenn der Channel in 0..1 läuft, normalisieren wir.
  function normalizeThrottle(raw){
    const peak = raw.reduce((a, b) => Math.max(a, b), 0);
    if (peak <= 1.5) return raw.map(v => v * 100);  // 0..1 → 0..100
    return raw;
  }

  function render(){
    try { renderInner(); }
    catch (e){
      host.innerHTML = `<div class="ba-empty" style="color:#ffaa00">
        FEHLER IN DER BESCHLEUNIGUNGS-ANALYSE — ${escapeHTML(e.message || String(e))}
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
    }
  }

  function renderInner(){
    const extras = DATA.extras || [];
    if (!extras.length){
      host.innerHTML = '<div class="ba-empty">' +
        '→ DIESE RUNDE HAT KEINE ZUSATZ-KANÄLE. ' +
        'Die Beschleunigungs-Analyse braucht mindestens einen Gasgriff-Kanal.</div>';
      if (mapWrap) mapWrap.hidden = true;
      return;
    }
    const assignment = channelRoles.getAllAssignments('accel');
    const thr = assignment.throttle;
    const lean = assignment.lean;
    if (!thr){
      // v21.17 — Pflicht-Kanal Gate. Ohne Gasgriff keine Analyse, kein Track-Map.
      // v21.44 — Channel-Liste entfernt, die Channels stehen schon im Picker oben.
      host.innerHTML = `<div class="ba-empty" style="text-align:left;line-height:1.7">
        <div style="color:var(--accent);font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:.04em;margin-bottom:8px">
          GASGRIFF-KANAL FEHLT
        </div>
        <div style="color:var(--ink-dim);text-transform:none;letter-spacing:0;font-size:13px">
          Klick oben auf <strong style="color:var(--ink)">GASGRIFF</strong> und wähle den passenden Kanal aus.
          Die Analyse startet, sobald der Gasgriff-Kanal zugeordnet ist.
        </div>
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    const tRaw = thr.data || [];
    const tData = normalizeThrottle(tRaw);  // 0..100
    const lData = lean ? (lean.data || []) : null;
    const dist  = DATA.distance || [];
    const time  = DATA.time     || [];
    const lat   = DATA.lat      || [];
    const lon   = DATA.lon      || [];
    if (tData.length < 10 || dist.length !== tData.length){
      host.innerHTML = `<div class="ba-empty">
        GASGRIFF-KANAL HAT KEINE VERWERTBAREN DATEN
        (${tData.length} Samples, erwartet ${dist.length})
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    // Apex-Detection (gleiche Funktion wie brakeAnalysis)
    const apices = (lat.length === tData.length && lat.length >= 50 && brakeAnalysis)
      ? brakeAnalysis.detectApices(lat, lon, dist, lData)
      : [];

    if (!apices.length){
      host.innerHTML = '<div class="ba-empty">KEINE KURVEN-SCHEITEL ERKANNT — Track scheint größtenteils Gerade zu sein.</div>';
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    // v22.10 — Schwellen aus THRESHOLDS.accel.
    const aCfg = (window.THRESHOLDS && window.THRESHOLDS.accel) || {};
    const phaseMaxDist = aCfg.phase_max_distance_m       ?? 800;
    const phaseMin     = aCfg.phase_min_samples          ?? 10;
    const dropLookback = aCfg.sharp_drop_lookback_samples ?? 10;
    const dropRecentMin = aCfg.sharp_drop_recent_max_min  ?? 30;
    const dropAmount   = aCfg.sharp_drop_amount          ?? 30;

    // Pro Apex: Phase vom Apex bis kurz vor dem nächsten "scharfen
    // Throttle-Drop" (= nächstes Anbremsen) oder bis phase_max_distance_m
    // nach dem Apex oder bis zum Lap-Ende.
    const phases = [];
    for (let a = 0; a < apices.length; a++){
      const apexI = apices[a].idx;
      let endI = tData.length - 1;
      // Look-ahead: max phase_max_distance_m oder nächster Apex
      const distMax = (dist[apexI] || 0) + phaseMaxDist;
      const nextApex = (a + 1 < apices.length) ? apices[a + 1].idx : null;
      for (let i = apexI + 5; i < tData.length; i++){
        if ((dist[i] || 0) > distMax) { endI = i; break; }
        if (nextApex && i >= nextApex - 10) { endI = i; break; }
        // Scharfer Drop = Anbremsen erkannt
        if (i > apexI + dropLookback){
          const recentMax = Math.max(...tData.slice(Math.max(apexI, i - dropLookback), i));
          if (recentMax > dropRecentMin && tData[i] < recentMax - dropAmount){
            endI = i; break;
          }
        }
      }
      if (endI - apexI >= phaseMin){
        phases.push({ apex: apices[a], from: apexI, to: endI });
      }
    }

    if (!phases.length){
      host.innerHTML = '<div class="ba-empty">KEINE AUSWERTBAREN BESCHLEUNIGUNGSPHASEN GEFUNDEN</div>';
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    const results = phases.map((p, idx) => analysePhase(idx + 1, p, tData, lData, dist, time));

    // Summary
    const sumGood = results.filter(r => r.overall === 'good').length;
    const sumWarn = results.filter(r => r.overall === 'warn').length;
    const sumBad  = results.filter(r => r.overall === 'bad').length;
    let summaryHl;
    if (sumBad >= 2 || (sumBad >= 1 && sumWarn >= 2)){
      summaryHl = 'FOKUS — Bei mehreren Beschleunigungsphasen ist Aufziehen oder Vollgas-Anteil auffällig.';
    } else if (sumGood === results.length){
      summaryHl = 'GUT — Sauberes Aufziehen durch die ganze Runde.';
    } else if (sumWarn + sumBad >= 1){
      summaryHl = 'HINWEISE — Einzelne Phasen mit Verbesserungspotential.';
    } else {
      summaryHl = 'OK — Insgesamt solide Beschleunigungstechnik.';
    }
    // v21.17 — Lean-Hinweis als eigener Banner.
    const leanBanner = lean ? '' :
      `<div class="ba-note-warn">
         ⚠ SCHRÄGLAGEN-KANAL NICHT ZUGEORDNET —
         Vollgas-auf-Geraden-Bewertung wird ausgelassen.
         Ramp-Zeit und Aufzieh-Glättung bleiben gültig.
       </div>`;

    let html = `
      <div class="ba-summary">
        <div class="bas-headline">${escapeHTML(summaryHl)}</div>
        <div class="bas-counts">
          <span>${results.length} PHASEN</span>
          <span class="n" style="color:var(--accel)">${sumGood} OK</span>
          <span class="n" style="color:#ffaa00">${sumWarn} HINWEIS</span>
          <span class="n" style="color:var(--brake)">${sumBad} FOKUS</span>
        </div>
      </div>
      ${leanBanner}`;

    results.forEach(r => { html += renderPhaseCard(r); });
    host.innerHTML = html;

    // Track-Map
    if (mapHost && lat.length === tData.length && lat.length >= 10){
      renderTrackMap(lat, lon, tData, apices, results);
      mapWrap.hidden = false;
    } else {
      if (mapWrap) mapWrap.hidden = true;
    }

    // v22.0 — idx → Sample-Mapping (Anchor = Apex falls vorhanden, sonst
    // Phase-Start; identisch zum renderTrackMap der Accel-Analyse).
    const idxToSample = {};
    results.forEach(r => {
      const anchor = (r.apex && r.apex.idx != null) ? r.apex.idx : r.from;
      if (anchor != null && anchor >= 0 && anchor < (DATA.distance || []).length){
        idxToSample[String(r.idx)] = anchor;
      }
    });

    // v21.45 — Marker ↔ Row Verlinkung
    // v22.0 — onSelect setzt Chart-Cursor.
    const mrl = setupMarkerRowLink(host, mapHost, mapWrap, (eventIdx) => {
      const chart = window._coachCharts && window._coachCharts.accel;
      if (!chart) return;
      if (eventIdx == null){
        chart.clearStickyCursor();
      } else {
        const sample = idxToSample[String(eventIdx)];
        if (sample != null) chart.setStickyCursor(sample);
      }
    });
    if (mrl) mrl.clear();
  }

  function analysePhase(idx, p, tData, lData, dist, time){
    const from = p.from, to = p.to;
    const slice = tData.slice(from, to + 1);
    const slLean = lData ? lData.slice(from, to + 1).map(Math.abs) : null;
    // v22.10 — Schwellen aus THRESHOLDS.accel.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.accel) || {};
    const fullThr      = cfg.full_throttle_threshold ?? 95;
    const rampGood     = cfg.ramp_good_seconds       ?? 1.0;
    const rampWarn     = cfg.ramp_warn_seconds       ?? 2.0;
    const smoothMinMax = cfg.smooth_min_running_max  ?? 20;
    const smoothDrop   = cfg.smooth_pump_drop_amount ?? 10;
    const straightLean = cfg.straight_lean_max_deg   ?? 10;
    const straightMin  = cfg.straight_min_samples    ?? 5;
    const straightGood = cfg.straight_good_pct       ?? 0.80;
    const straightWarn = cfg.straight_warn_pct       ?? 0.50;
    const errThr       = cfg.error_marker_throttle_max ?? 90;
    const errMinSec    = cfg.error_marker_min_seconds  ?? 0.3;

    // (a) Apex→Vollgas-Zeit: wann fällt Throttle das erste Mal ≥ fullThr%
    let fullThrottleIdx = -1;
    for (let k = 0; k < slice.length; k++){
      if (slice[k] >= fullThr){ fullThrottleIdx = k; break; }
    }
    const tApex = time[from] || 0;
    let apexToFullS = null;
    if (fullThrottleIdx >= 0){
      apexToFullS = (time[from + fullThrottleIdx] || 0) - tApex;
    }
    let rampScore;
    if (apexToFullS === null){
      rampScore = 'bad';  // Vollgas nie erreicht in dieser Phase
    } else if (apexToFullS < rampGood) rampScore = 'good';
    else if (apexToFullS < rampWarn)   rampScore = 'warn';
    else                               rampScore = 'bad';

    // (b) Aufzieh-Glättung: zähle signifikante Rücknahmen (> smoothDrop Drop
    //     nach lokalem Max) im Anstiegs-Abschnitt (vom Apex bis erstes Vollgas).
    const upTo = fullThrottleIdx >= 0 ? fullThrottleIdx : slice.length - 1;
    let pumpDrops = 0;
    let runningMax = slice[0] || 0;
    for (let k = 1; k <= upTo; k++){
      runningMax = Math.max(runningMax, slice[k]);
      if (runningMax >= smoothMinMax && slice[k] < runningMax - smoothDrop){
        pumpDrops++;
        runningMax = slice[k];  // reset
      }
    }
    let smoothScore;
    if (pumpDrops === 0)      smoothScore = 'good';
    else if (pumpDrops === 1) smoothScore = 'warn';
    else                      smoothScore = 'bad';

    // (c) Vollgas-Anteil auf Geraden — nur wenn Lean-Kanal da
    let straightScore = null;
    let straightPct = null;
    let straightSamples = 0;
    if (slLean){
      let nStraight = 0, nFullOnStraight = 0;
      const straightMarkers = [];  // {idx_in_slice}
      for (let k = 0; k < slice.length; k++){
        if (slLean[k] < straightLean){
          nStraight++;
          if (slice[k] >= fullThr) nFullOnStraight++;
        }
      }
      straightSamples = nStraight;
      if (nStraight >= straightMin){
        straightPct = nFullOnStraight / nStraight;
        if (straightPct > straightGood)      straightScore = 'good';
        else if (straightPct > straightWarn) straightScore = 'warn';
        else                                 straightScore = 'bad';
      }
      // Markers für not-full-on-straight (für Track-Map)
    }

    // Track-Map-Marker: Stellen wo throttle < errThr% bei lean < straightLean
    // UND bereits > 5 samples nach Apex (also nicht direkt im Aus-Apex-Aufziehen).
    const errorHits = [];
    if (slLean){
      let k = 5;
      while (k < slice.length){
        if (slLean[k] < straightLean && slice[k] < errThr){
          // Run-Anfang
          const runStart = k;
          while (k < slice.length && slLean[k] < straightLean && slice[k] < errThr) k++;
          const runEnd = k - 1;
          const dur = (time[from + runEnd] || 0) - (time[from + runStart] || 0);
          if (dur > errMinSec){
            errorHits.push({
              idx_start: from + runStart,
              idx_end:   from + runEnd,
              durationS: dur,
            });
          }
        } else {
          k++;
        }
      }
    }

    // Overall
    const scores = [rampScore, smoothScore];
    if (straightScore) scores.push(straightScore);
    let overall;
    if (scores.includes('bad'))      overall = 'bad';
    else if (scores.includes('warn')) overall = 'warn';
    else                              overall = 'good';

    return {
      idx,
      from, to,
      apex: p.apex,
      distStart: dist[from] || 0,
      distEnd:   dist[to]   || 0,
      apexToFullS, rampScore,
      pumpDrops,   smoothScore,
      straightPct, straightScore, straightSamples,
      errorHits,
      overall,
      sparkData: slice,
      sparkLean: slLean,
    };
  }

  function renderPhaseCard(r){
    const fmtM = (m) => Math.round(m) + ' m';
    const where = fmtM(r.distStart) + ' → ' + fmtM(r.distEnd);

    let pills = '';
    if (r.apexToFullS === null){
      pills += `<span class="bz-pill ${r.rampScore}">KEIN VOLLGAS</span>`;
    } else {
      pills += `<span class="bz-pill ${r.rampScore}">AB APEX ${r.apexToFullS.toFixed(2)}s → VOLLGAS</span>`;
    }
    pills += `<span class="bz-pill ${r.smoothScore}">AUFZIEHEN ${r.pumpDrops===0?'sauber':r.pumpDrops+'× Rücknahme'}</span>`;
    if (r.straightScore){
      pills += `<span class="bz-pill ${r.straightScore}">GERADE ${Math.round(r.straightPct*100)}% VOLLGAS</span>`;
    }

    let notes = '';
    if (r.rampScore === 'bad'){
      if (r.apexToFullS === null){
        notes += `<div><span class="nh">Vollgas nicht erreicht:</span> In dieser Phase wurde kein voller Gasgriff aufgezogen. Vertrauen — am Kurvenausgang aggressiv aufmachen wenn das Bike aufrichtet.</div>`;
      } else {
        notes += `<div><span class="nh">Zu spätes Aufziehen:</span> ${r.apexToFullS.toFixed(2)}s vom Apex bis Vollgas — sollte unter 1.0s liegen. Früher aufmachen, das Heck stabilisiert sich mit Gas.</div>`;
      }
    } else if (r.rampScore === 'warn'){
      notes += `<div><span class="nh">Aufziehen okay, geht aber schneller:</span> ${r.apexToFullS.toFixed(2)}s bis Vollgas. Ideal: unter 1.0s.</div>`;
    } else {
      notes += `<div><span class="nh">Aufziehen knackig:</span> ${r.apexToFullS.toFixed(2)}s vom Apex bis Vollgas — sauber.</div>`;
    }
    if (r.smoothScore === 'bad'){
      notes += `<div><span class="nh">Schwankendes Aufziehen:</span> ${r.pumpDrops} Rücknahmen über 10% im Anstieg. Linear durchziehen statt nachgreifen.</div>`;
    } else if (r.smoothScore === 'warn'){
      notes += `<div><span class="nh">Eine Korrektur im Aufziehen:</span> einmal zurückgenommen — vermeidbar?</div>`;
    }
    if (r.straightScore === 'bad'){
      notes += `<div><span class="nh">Gerade nicht voll genutzt:</span> Nur ${Math.round(r.straightPct*100)}% der Geraden-Samples mit Vollgas. Gas konsequent durchziehen wenn das Bike aufrichtet.</div>`;
    } else if (r.straightScore === 'warn'){
      notes += `<div><span class="nh">Gerade okay, geht voller:</span> ${Math.round(r.straightPct*100)}% Vollgas-Anteil. Ziel: > 80%.</div>`;
    } else if (r.straightScore === 'good'){
      notes += `<div><span class="nh">Gerade gut genutzt:</span> ${Math.round(r.straightPct*100)}% Vollgas auf der Geraden.</div>`;
    }

    const spark = renderSparkline(r.sparkData, r.sparkLean);
    return `
      <div class="brake-zone" data-idx="${r.idx}" data-overall="${r.overall}">
        <div class="bz-idx">#${r.idx}</div>
        <div class="bz-mid">
          <div class="bz-where">${where}</div>
          <div class="bz-pills">${pills}</div>
          <div class="bz-notes">${notes}</div>
        </div>
        <div class="bz-spark">
          ${spark}
          <span class="sp-label">GAS${r.sparkLean ? ' + LEAN' : ''}</span>
        </div>
      </div>`;
  }

  function renderSparkline(p, lean){
    const W = 200, H = 60;
    const n = p.length;
    const maxP = 100;  // Throttle ist 0..100%
    const pPath = p.map((v, i) => {
      const x = (i / (n - 1)) * W;
      const y = H - (Math.min(maxP, v) / maxP) * (H - 4) - 2;
      return (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
    }).join('');
    let leanPath = '';
    if (lean){
      const maxL = lean.reduce((a, b) => Math.max(a, b), 0) || 1;
      leanPath = lean.map((v, i) => {
        const x = (i / (n - 1)) * W;
        const y = H - (v / maxL) * (H - 4) - 2;
        return (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
      }).join('');
    }
    return `
      <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
        ${leanPath ? `<path d="${leanPath}" stroke="#666" stroke-width="1" fill="none" opacity="0.7"/>` : ''}
        <path d="${pPath}" stroke="var(--accent)" stroke-width="2" fill="none"/>
      </svg>`;
  }

  // v21.24 — tile/zoomCtl lazy lifecycle wie bei brake.
  let tile = null, zoomCtl = null;
  let _lastBgState = { args: null };

  function renderTrackMap(lat, lon, tData, apices, results){
    _lastBgState.args = [lat, lon, tData, apices, results];
    const W = 1200, H = 600, PAD = 40;
    const n = lat.length;
    const latMin = Math.min.apply(null, lat), latMax = Math.max.apply(null, lat);
    const lonMin = Math.min.apply(null, lon), lonMax = Math.max.apply(null, lon);
    const latRange = latMax - latMin, lonRange = lonMax - lonMin;
    const cosLat = Math.cos((latMin + latMax) / 2 * Math.PI / 180);
    const wMeters = lonRange * 111000 * cosLat;
    const hMeters = latRange * 111000;
    const aspectMap = hMeters > 0 ? wMeters / hMeters : 1;
    const aspectVp = (W - 2*PAD) / (H - 2*PAD);
    let scaleX, scaleY, ox, oy;
    if (aspectMap > aspectVp){
      scaleX = (W - 2*PAD) / lonRange;
      scaleY = scaleX / cosLat;
      ox = PAD;
      oy = PAD + ((H - 2*PAD) - latRange * scaleY) / 2;
    } else {
      scaleY = (H - 2*PAD) / latRange;
      scaleX = scaleY * cosLat;
      oy = PAD;
      ox = PAD + ((W - 2*PAD) - lonRange * scaleX) / 2;
    }
    const proj = (la, lo) => ({
      x: ox + (lo - lonMin) * scaleX,
      y: oy + (latMax - la) * scaleY,
    });

    if (!tile){
      tile = makeTileLayer({
        svg: mapHost, W, H, proj,
        latMin, latMax, lonMin, lonMax, padding: 0.10,
      });
    }
    if (!zoomCtl){
      zoomCtl = makeZoomPan({ svg: mapHost, W, H, minZoom: 1, maxZoom: 8 });
    }

    let html = '';
    if (tile.active) html += tile.buildLayer();

    // Hintergrund-Track — durchgehend, gut sichtbar (v21.18).
    let bgPath = '';
    for (let i = 0; i < n; i++){
      const p = proj(lat[i], lon[i]);
      bgPath += (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
    }
    html += `<path class="bt-track-bg" d="${bgPath}" stroke-width="2.5" fill="none" stroke-linejoin="round"/>`;

    // Throttle 0..100 → alpha + width
    for (let i = 1; i < n; i++){
      const intensity = Math.max(0, Math.min(1, tData[i] / 100));
      if (intensity < 0.05) continue;
      const alpha = 0.30 + 0.70 * intensity;
      const w = 3 + 5 * intensity;
      const p1 = proj(lat[i-1], lon[i-1]);
      const p2 = proj(lat[i],   lon[i]);
      const color = `rgba(199,125,255,${alpha.toFixed(2)})`;
      html += `<line x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${p2.x.toFixed(1)}" y2="${p2.y.toFixed(1)}" stroke="${color}" stroke-width="${w.toFixed(1)}" stroke-linecap="round"/>`;
    }

    // Apex-Marker (weiße Punkte für ALLE Apices)
    apices.forEach(a => {
      const p = proj(lat[a.idx], lon[a.idx]);
      html += `<g><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="6" fill="none" stroke="#f5f5f0" stroke-width="2"/><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.5" fill="#f5f5f0"/></g>`;
    });

    // v21.17 — Pro Phase EIN farbiger Index-Marker (#N) am Apex.
    // Farbe = Overall-Score. Damit ist jede Phase aus der Liste unten auch
    // oben auf der Map zu sehen — unabhängig vom Score.
    const scoreColor = {
      good: '#7dd17d',  // grün
      warn: '#ffaa00',  // orange
      bad:  '#ff3d3d',  // rot
    };
    results.forEach(r => {
      const anchorIdx = (r.apex && r.apex.idx != null) ? r.apex.idx : r.from;
      if (anchorIdx == null || anchorIdx < 0 || anchorIdx >= lat.length) return;
      const p = proj(lat[anchorIdx], lon[anchorIdx]);
      const color = scoreColor[r.overall] || '#888';
      const cx = p.x + 16, cy = p.y - 16;
      html += `<g data-idx="${r.idx}">
        <line x1="${p.x.toFixed(1)}" y1="${p.y.toFixed(1)}" x2="${cx.toFixed(1)}" y2="${cy.toFixed(1)}" stroke="${color}" stroke-width="1" opacity="0.6"/>
        <circle class="mk-bubble" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="11" fill="${color}" stroke="#0a0a0a" stroke-width="1.5"/>
        <text x="${cx.toFixed(1)}" y="${(cy + 4).toFixed(1)}" font-family="JetBrains Mono" font-size="11" font-weight="600" fill="#0a0a0a" text-anchor="middle">${r.idx}</text>
      </g>`;
    });

    // Fehler-Marker pro errorHit (Stelle wo's auf der Geraden nicht voll wurde).
    // Kleiner als der Phase-Marker; sitzt am konkreten Fehler-Punkt.
    results.forEach(r => {
      if (r.overall !== 'bad' && r.overall !== 'warn') return;
      r.errorHits.forEach(h => {
        const i = h.idx_start;
        if (i == null || i < 0 || i >= lat.length) return;
        const p = proj(lat[i], lon[i]);
        const color = r.overall === 'bad' ? '#ff3d3d' : '#ffaa00';
        html += `<g>
          <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="8" fill="none" stroke="${color}" stroke-width="2"/>
          <text x="${p.x.toFixed(1)}" y="${(p.y + 4).toFixed(1)}" font-family="Bebas Neue" font-size="12" fill="${color}" text-anchor="middle">⚠</text>
        </g>`;
      });
    });

    mapHost.innerHTML = html;
    if (tile.active) tile.bindLoadEvents(mapWrap);
    else tile.hideSpinner();
  }

  // v21.24 — rerender + setMapview wie brake
  function rerenderMap(){
    if (_lastBgState.args) renderTrackMap.apply(null, _lastBgState.args);
  }
  function setMapview(on){
    if (!tile){ rerenderMap(); }
    if (!tile) return;
    on = !!on;
    if (on === tile.active) return;
    tile.active = on;
    rerenderMap();
  }

  channelRoles.onChange(tab => {
    if (tab === 'accel') render();
  });
  render();
  // v21.24 — setMapview für Toggle
  return { render, setMapview };
})();

// ============================================================================
// v21.39 — Elektronik-Setup-Analyse.
//
// Zweck: Visualisierung der Eingriffe von Traction-Control / Wheelie-Control
// und der Wheelspeed-Auffälligkeiten, um Setup-Entscheidungen (Reifen, TC-
// Stufe, Federbein-Vorspannung) datenbasiert zu treffen.
//
// Sechs Kanäle:
//   PFLICHT:  wheel_speed_front, wheel_speed_rear
//   OPTIONAL: throttle, lean, tc_status, wc_status
//
// Erkannte Event-Typen (jeweils mit Index auf der Trackmap):
//   1. SLIP        — |V_rear - V_front| über Schwellwert relativ zu max(V)
//                    (positive Differenz = Hinterrad-Schlupf, negative =
//                    Vorderrad-Lockup beim Bremsen)
//   2. SPIKE       — Hinterrad-Drehzahl steigt extrem schnell (dV/dt > TH)
//   3. OSC         — Hinterrad-Drehzahl schwankt stark (rolling std/mean)
//   4. TC          — TC-Status weicht vom Ruhewert ab (Mode-Detection)
//   5. WC          — WC-Status weicht vom Ruhewert ab (Mode-Detection)
//
// Events werden zeitlich verschmolzen (Mindest-Abstand 0.5s, sonst eine Zone),
// auf der Map mit farbigem Punkt markiert (Index + Typ-Farbe), und in einer
// Tabelle darunter mit Ort, Dauer und Begründung erklärt.
// ============================================================================
const electronicsAnalysis = (function(){
  const host = document.getElementById('electronics-analysis');
  if (!host) return null;
  const mapHost = document.getElementById('elec-trackmap');
  const mapWrap = document.getElementById('elec-trackmap-wrap');
  const _lastBgState = { args: null };
  let tile = null;
  let zoomCtl = null;

  // -- Hilfsfunktionen ---------------------------------------------------------

  // Schätze den "Ruhewert" eines diskreten Status-Kanals (TC/WC). Wir nehmen
  // den häufigsten Wert (Modus), abgerundet auf 1 Dezimalstelle damit
  // float-Rauschen nicht zu Singleton-Bins führt. Fallback: 0.
  function estimateRest(arr){
    if (!arr || arr.length === 0) return 0;
    const counts = new Map();
    for (let i = 0; i < arr.length; i++){
      const v = Math.round(arr[i] * 10) / 10;
      counts.set(v, (counts.get(v) || 0) + 1);
    }
    let bestV = 0, bestN = -1;
    for (const [v, n] of counts){
      if (n > bestN){ bestN = n; bestV = v; }
    }
    return bestV;
  }

  // Sucht zusammenhängende Indizes wo predicate(i) === true und liefert
  // {from, to} Tupel (inclusive). Lücken kleiner als gap_samples werden
  // gemerged. Sequenzen kürzer als min_samples werden verworfen.
  function findRuns(predicate, n, minSamples, gapSamples){
    const runs = [];
    let i = 0;
    while (i < n){
      if (predicate(i)){
        let j = i;
        while (j < n && predicate(j)) j++;
        // Versuche zu erweitern wenn die nächste Sequenz nahe ist
        let end = j - 1;
        let k = j;
        while (k < n - gapSamples){
          // Suche das nächste True in den nächsten gapSamples
          let found = -1;
          for (let m = k; m < Math.min(n, k + gapSamples); m++){
            if (predicate(m)){ found = m; break; }
          }
          if (found < 0) break;
          // Wenn nahe genug, erweitere
          if (found - end <= gapSamples){
            let p = found;
            while (p < n && predicate(p)) p++;
            end = p - 1;
            k = p;
          } else break;
        }
        if (end - i + 1 >= minSamples){
          runs.push({ from: i, to: end });
        }
        i = end + 1;
      } else {
        i++;
      }
    }
    return runs;
  }

  // -- Eventserkennung ---------------------------------------------------------

  // 1) Wheelspeed-Slip: |Vr - Vf| / Vref > 0.10 für >= 0.10s
  //    Vref = max(Vf, Vr, 5) damit wir bei niedrigen Speeds nicht alarmieren.
  function detectSlip(vf, vr, time){
    const n = vf.length;
    if (n === 0 || vr.length !== n) return [];
    // v22.10 — Schwellen aus THRESHOLDS.electronics.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.electronics) || {};
    const slipRatio   = cfg.slip_ratio         ?? 0.10;
    const minRef      = cfg.slip_min_ref_speed ?? 5;
    const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
    const minSamples = Math.max(3, Math.round((cfg.slip_min_seconds ?? 0.10) / dt));
    const gapSamples = Math.max(2, Math.round((cfg.slip_gap_seconds ?? 0.05) / dt));
    const pred = (i) => {
      const vref = Math.max(vf[i], vr[i], minRef);
      const slip = Math.abs(vr[i] - vf[i]) / vref;
      return slip > slipRatio;
    };
    const runs = findRuns(pred, n, minSamples, gapSamples);
    return runs.map(r => {
      // Bestimme Richtung (rear schneller = Schlupf hinten, front schneller =
      // Lockup vorne) anhand des Vorzeichens am Peak.
      let peakDelta = 0, peakIdx = r.from;
      for (let k = r.from; k <= r.to; k++){
        const d = vr[k] - vf[k];
        if (Math.abs(d) > Math.abs(peakDelta)){ peakDelta = d; peakIdx = k; }
      }
      return { ...r, peakDelta, peakIdx, type: 'slip' };
    });
  }

  // 2) Hinterrad-Spike: dV/dt > 30 km/h pro Sekunde, in einer Phase < 200ms
  function detectSpikes(vr, time){
    const n = vr.length;
    if (n < 5) return [];
    // v22.10 — Schwellen aus THRESHOLDS.electronics.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.electronics) || {};
    const winSeconds   = cfg.spike_window_seconds  ?? 0.15;
    const rateThresh   = cfg.spike_rate_threshold  ?? 30;
    const continueRate = cfg.spike_continue_rate   ?? 15;
    const mergeSeconds = cfg.spike_merge_seconds   ?? 0.5;
    const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
    const winSamples = Math.max(2, Math.round(winSeconds / dt));
    const runs = [];
    let i = winSamples;
    while (i < n){
      const dv = vr[i] - vr[i - winSamples];
      const dvPerS = dv / (winSamples * dt);
      if (dvPerS > rateThresh){
        let j = i;
        // Erweitere solange Rate hoch bleibt
        while (j < n){
          const dv2 = j + winSamples < n ?
              vr[j + winSamples] - vr[j] : 0;
          const r2 = dv2 / (winSamples * dt);
          if (r2 > continueRate) j += winSamples; else break;
        }
        const from = Math.max(0, i - winSamples);
        const to   = Math.min(n - 1, j);
        // Merge mit vorherigem Spike falls < mergeSeconds entfernt
        if (runs.length){
          const last = runs[runs.length - 1];
          if (from - last.to < Math.round(mergeSeconds / dt)){
            last.to = to;
            last.peakRate = Math.max(last.peakRate || 0, dvPerS);
            i = j + 1; continue;
          }
        }
        runs.push({ from, to, peakRate: dvPerS, type: 'spike' });
        i = j + 1;
      } else {
        i++;
      }
    }
    return runs;
  }

  // 3) Hinterrad-Oszillation: rolling std / |mean| > 0.05 für >= 0.30s
  //    Fenster 250ms, schaut auf relative Schwankung.
  function detectOscillation(vr, time){
    const n = vr.length;
    if (n < 10) return [];
    // v22.10 — Schwellen aus THRESHOLDS.electronics.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.electronics) || {};
    const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
    const win = Math.max(5, Math.round((cfg.osc_window_seconds ?? 0.25) / dt));
    const minMean = cfg.osc_min_mean ?? 5;
    const threshold = cfg.osc_threshold ?? 0.05;
    const half = Math.floor(win / 2);
    // Rolling std + mean
    const score = new Array(n).fill(0);
    for (let i = half; i < n - half; i++){
      let sum = 0;
      for (let k = i - half; k <= i + half; k++) sum += vr[k];
      const mean = sum / win;
      if (Math.abs(mean) < minMean) continue;  // bei niedrigen Speeds skippen
      let sq = 0;
      for (let k = i - half; k <= i + half; k++){
        const d = vr[k] - mean; sq += d * d;
      }
      const std = Math.sqrt(sq / win);
      score[i] = std / Math.abs(mean);
    }
    const minSamples = Math.max(5, Math.round((cfg.osc_min_seconds ?? 0.30) / dt));
    const gapSamples = Math.max(3, Math.round((cfg.osc_gap_seconds ?? 0.10) / dt));
    const pred = (i) => score[i] > threshold;
    const runs = findRuns(pred, n, minSamples, gapSamples);
    return runs.map(r => {
      let maxScore = 0;
      for (let k = r.from; k <= r.to; k++) maxScore = Math.max(maxScore, score[k]);
      return { ...r, peakScore: maxScore, type: 'osc' };
    });
  }

  // 4+5) Status-Channel-Eingriffe: Wert weicht vom Ruhewert ab für >= 0.05s
  function detectStatusEvents(status, time, type){
    const n = status.length;
    if (n === 0) return [];
    // v22.10 — Schwellen aus THRESHOLDS.electronics.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.electronics) || {};
    const deviation = cfg.status_deviation ?? 0.5;
    const rest = estimateRest(status);
    const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
    const minSamples = Math.max(2, Math.round((cfg.status_min_seconds ?? 0.05) / dt));
    const gapSamples = Math.max(2, Math.round((cfg.status_gap_seconds ?? 0.10) / dt));
    const pred = (i) => Math.abs(status[i] - rest) > deviation;
    const runs = findRuns(pred, n, minSamples, gapSamples);
    return runs.map(r => {
      let peakVal = status[r.from];
      for (let k = r.from; k <= r.to; k++){
        if (Math.abs(status[k] - rest) > Math.abs(peakVal - rest)) peakVal = status[k];
      }
      return { ...r, restVal: rest, peakVal, type };
    });
  }

  // -- Render ------------------------------------------------------------------

  function render(){
    try { renderInner(); }
    catch (e){
      host.innerHTML = `<div class="ba-empty" style="color:#ffaa00">
        FEHLER IN DER ELEKTRONIK-ANALYSE — ${escapeHTML(e.message || String(e))}
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
    }
  }

  function renderInner(){
    const extras = DATA.extras || [];
    if (!extras.length){
      host.innerHTML = '<div class="ba-empty">' +
        '→ DIESE RUNDE HAT KEINE ZUSATZ-KANÄLE. ' +
        'Die Elektronik-Analyse braucht mindestens Vorder- und Hinterrad-Drehzahl.</div>';
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    const a = channelRoles.getAllAssignments('electronics');
    const vfCh = a.wheel_speed_front;
    const vrCh = a.wheel_speed_rear;
    const thrCh = a.throttle;
    const leanCh = a.lean;
    const tcCh = a.tc_status;
    const wcCh = a.wc_status;

    if (!vfCh || !vrCh){
      // Pflicht-Channels fehlen — zeige Auswahl-Hinweis wie in Bremsen/Beschleunigen.
      // v21.44 — Channel-Liste entfernt, die Channels stehen schon im Picker oben.
      const missing = [];
      if (!vfCh) missing.push('DREHZAHL VORDERRAD');
      if (!vrCh) missing.push('DREHZAHL HINTERRAD');
      host.innerHTML = `<div class="ba-empty" style="text-align:left;line-height:1.7">
        <div style="color:var(--accent);font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:.04em;margin-bottom:8px">
          PFLICHT-KANAL FEHLT: ${missing.join(' + ')}
        </div>
        <div style="color:var(--ink-dim);text-transform:none;letter-spacing:0;font-size:13px">
          Klick oben auf den Standardkanal und wähle den passenden Datenkanal aus.
          Die Analyse startet, sobald Vorderrad- und Hinterrad-Drehzahl zugeordnet sind.
        </div>
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    const vf = vfCh.data || [];
    const vr = vrCh.data || [];
    const dist = DATA.distance || [];
    const time = DATA.time || [];
    const lat  = DATA.lat || [];
    const lon  = DATA.lon || [];

    if (vf.length < 10 || vf.length !== vr.length){
      host.innerHTML = `<div class="ba-empty">
        VORDER-/HINTERRAD-DREHZAHL HABEN UNTERSCHIEDLICHE GRIDS
        (${vf.length} vs ${vr.length} Samples)
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      return;
    }
    if (dist.length !== vf.length){
      host.innerHTML = `<div class="ba-empty">
        DREHZAHL-KANÄLE PASSEN NICHT ZUM DISTANZ-GRID
        (${vf.length} vs ${dist.length} Samples)
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      return;
    }

    // Run detectors
    const slips  = detectSlip(vf, vr, time);
    const spikes = detectSpikes(vr, time);
    const oscs   = detectOscillation(vr, time);
    const tcs    = tcCh ? detectStatusEvents(tcCh.data || [], time, 'tc') : [];
    const wcs    = wcCh ? detectStatusEvents(wcCh.data || [], time, 'wc') : [];

    const allEvents = [...slips, ...spikes, ...oscs, ...tcs, ...wcs]
      .sort((a, b) => a.from - b.from)
      .map((e, idx) => ({ ...e, idx: idx + 1 }));

    // Summary
    const optMissing = [];
    if (!thrCh)  optMissing.push('GASGRIFF');
    if (!leanCh) optMissing.push('SCHRÄGLAGE');
    if (!tcCh)   optMissing.push('STATUS TC');
    if (!wcCh)   optMissing.push('STATUS WC');
    let optBanner = '';
    if (optMissing.length){
      optBanner = `<div class="ba-note-warn">
        ⚠ Optionale Kanäle nicht zugeordnet: ${escapeHTML(optMissing.join(', '))} —
        die zugehörigen Ereignisse werden ausgelassen.
        Pflicht-Kanäle (Drehzahl Vorder- + Hinterrad) reichen für Slip-/Spike-Erkennung.
      </div>`;
    }

    const cntSlip  = slips.length;
    const cntSpike = spikes.length;
    const cntOsc   = oscs.length;
    const cntTC    = tcs.length;
    const cntWC    = wcs.length;
    const total    = allEvents.length;

    let summary;
    if (total === 0){
      summary = 'OK — Keine auffälligen Elektronik-Eingriffe oder Wheelspeed-Anomalien.';
    } else if (total <= 3){
      summary = `HINWEISE — ${total} Ereignis${total===1?'':'se'} erkannt. Sieh dir die Details an.`;
    } else {
      summary = `FOKUS — ${total} Ereignisse erkannt. Setup-Anpassung wahrscheinlich sinnvoll.`;
    }

    let html = `
      <div class="ba-summary">
        <div class="bas-headline">${escapeHTML(summary)}</div>
        <div class="bas-counts">
          <span>${total} EVENTS</span>
          ${cntSpike ? `<span class="n" style="color:#ff3d3d">${cntSpike} SPIKE</span>` : ''}
          ${cntOsc   ? `<span class="n" style="color:#ff9933">${cntOsc} SCHWANKUNG</span>` : ''}
          ${cntSlip  ? `<span class="n" style="color:#ffcc33">${cntSlip} SLIP/LOCK</span>` : ''}
          ${cntTC    ? `<span class="n" style="color:#3aff7a">${cntTC} TC</span>` : ''}
          ${cntWC    ? `<span class="n" style="color:#00d4ff">${cntWC} WC</span>` : ''}
        </div>
      </div>
      ${optBanner}`;

    if (allEvents.length){
      // v21.40 — Build a channel context that the row renderer uses to pick
      // the right sparkline (event-type-specific). Optional channels (thr,
      // lean, tc, wc) may be null — the renderer falls back accordingly.
      const ctx = {
        dist, time, vf, vr,
        thr:  thrCh  ? (thrCh.data  || null) : null,
        lean: leanCh ? (leanCh.data || null) : null,
        tc:   tcCh   ? (tcCh.data   || null) : null,
        wc:   wcCh   ? (wcCh.data   || null) : null,
      };
      html += `
        <div class="elec-event-table head">
          <div>#</div><div>TYP</div><div>BESCHREIBUNG</div><div>POSITION</div><div>VERLAUF</div>
        </div>`;
      allEvents.forEach(ev => { html += renderEventRow(ev, ctx); });
    } else {
      html += `<div class="ba-empty">KEINE EREIGNISSE — SAUBERE RUNDE.</div>`;
    }
    host.innerHTML = html;

    // Trackmap
    if (mapHost && lat.length === vf.length && lat.length >= 10){
      renderTrackMap(lat, lon, allEvents);
      mapWrap.hidden = false;
    } else {
      if (mapWrap) mapWrap.hidden = true;
    }

    // v22.0 — idx → Sample-Mapping. Anchor = ev.from (Event-Start).
    const idxToSample = {};
    allEvents.forEach(ev => {
      if (ev.from != null && ev.from >= 0 && ev.from < (DATA.distance || []).length){
        idxToSample[String(ev.idx)] = ev.from;
      }
    });

    // v21.45 — Marker ↔ Row Verlinkung
    // v22.0 — onSelect setzt Chart-Cursor (Datenviewer-Chart-Sektion).
    const mrl = setupMarkerRowLink(host, mapHost, mapWrap, (eventIdx) => {
      const chart = window._coachCharts && window._coachCharts.electronics;
      if (!chart) return;
      if (eventIdx == null){
        chart.clearStickyCursor();
      } else {
        const sample = idxToSample[String(eventIdx)];
        if (sample != null) chart.setStickyCursor(sample);
      }
    });
    if (mrl) mrl.clear();

    // v21.40 — Multi-Channel-Chart wurde in v21.46 entfernt; siehe Datenviewer-
    // Chart-Sektion am Ende des Tabs.
  }

  // -- Event-Zeile -------------------------------------------------------------

  function renderEventRow(ev, ctx){
    const { dist, time, vf, vr, thr, lean, tc, wc } = ctx;
    const fmtM = (m) => Math.round(m) + ' m';
    const startD = dist[ev.from] || 0;
    const endD   = dist[ev.to]   || 0;
    const durS   = (time[ev.to] || 0) - (time[ev.from] || 0);

    let typeLabel = '', desc = '', cls = '';
    let sparkChannels = [];  // [{data, color, opacity, width}]
    let sparkLabel = '';
    if (ev.type === 'spike'){
      cls = 'spike'; typeLabel = '⚡ SPIKE';
      const rate = ev.peakRate || 0;
      desc = `<span class="nh">Hinterrad-Drehzahl steigt sehr schnell:</span> ` +
             `Peak-Rate ${rate.toFixed(0)} (V-Einheit/s). ` +
             `Mögliche Ursache: Schlupf beim Herausbeschleunigen, TC-Lücke oder Wheelie. ` +
             `Setup-Hinweis: TC-Stufe oder Wheelie-Control prüfen.`;
      sparkChannels = [{data: vr, color: '#ff3d3d', width: 2}];
      sparkLabel = 'V_REAR';
    } else if (ev.type === 'osc'){
      cls = 'osc'; typeLabel = '∿ SCHWANKUNG';
      const pct = Math.round((ev.peakScore || 0) * 100);
      desc = `<span class="nh">Hinterrad-Drehzahl schwankt stark:</span> ` +
             `relative Streuung bis ${pct}%. ` +
             `Mögliche Ursache: Hopping/Chatter, ungünstige Federabstimmung am Hinterrad, ` +
             `oder ein zu aggressives TC-Eingriffsverhalten (pumpen).`;
      sparkChannels = [{data: vr, color: '#ff9933', width: 2}];
      sparkLabel = 'V_REAR';
    } else if (ev.type === 'slip'){
      cls = 'slip';
      if ((ev.peakDelta || 0) > 0){
        typeLabel = '↑ SCHLUPF HINTEN';
        desc = `<span class="nh">Hinterrad schneller als Vorderrad:</span> ` +
               `Peak-Differenz ${ev.peakDelta.toFixed(1)}. ` +
               `Antriebs-Schlupf — Reifen kommt nicht durch, oder TC greift zu spät.`;
      } else {
        typeLabel = '↓ LOCKUP VORN';
        desc = `<span class="nh">Vorderrad langsamer als Hinterrad:</span> ` +
               `Peak-Differenz ${Math.abs(ev.peakDelta).toFixed(1)}. ` +
               `Typisch beim sehr harten Anbremsen — wenn das öfter passiert, ` +
               `evtl. ABS- oder Bremsdruck-Setup anschauen.`;
      }
      // Both wheel speeds, share the Y-axis (gleiche Einheit).
      sparkChannels = [
        {data: vf, color: '#7fc8a9', width: 1.5},
        {data: vr, color: '#ffcc33', width: 2},
      ];
      sparkLabel = 'V_FRONT / V_REAR';
    } else if (ev.type === 'tc'){
      cls = 'tc'; typeLabel = '◉ TC AKTIV';
      desc = `<span class="nh">Traction Control greift ein:</span> ` +
             `Status-Wert wechselt von ${ev.restVal} auf ${ev.peakVal}. ` +
             `Dauer ${durS.toFixed(2)}s. ` +
             `Häufige TC-Eingriffe deuten auf zu viel Schlupf — Reifen, ` +
             `Setup oder eine niedrigere TC-Stufe testen.`;
      // TC-Status primary (eigene Skala), V_rear im Hintergrund als Kontext
      sparkChannels = [
        {data: vr, color: '#666',    width: 1, opacity: 0.6, scale: 'rear'},
        {data: tc, color: '#3aff7a', width: 2, scale: 'tc'},
      ];
      sparkLabel = 'TC + V_REAR';
    } else if (ev.type === 'wc'){
      cls = 'wc'; typeLabel = '◉ WC AKTIV';
      desc = `<span class="nh">Wheelie Control greift ein:</span> ` +
             `Status-Wert wechselt von ${ev.restVal} auf ${ev.peakVal}. ` +
             `Dauer ${durS.toFixed(2)}s. ` +
             `Wenn die WC oft greift, lohnt es sich, die Stufe zu reduzieren, ` +
             `um nicht Leistung zu verschenken.`;
      sparkChannels = [
        {data: thr || vr, color: '#666',    width: 1, opacity: 0.6, scale: 'thr'},
        {data: wc,        color: '#00d4ff', width: 2, scale: 'wc'},
      ];
      sparkLabel = (thr ? 'WC + GASGRIFF' : 'WC + V_REAR');
    }

    // Render a tight ±10-sample buffer around the event window so the
    // viewer can see the lead-in / lead-out around the marked region.
    const buf = Math.max(5, Math.round((ev.to - ev.from) * 0.4));
    const sFrom = Math.max(0, ev.from - buf);
    const sTo   = Math.min((dist.length || 0) - 1, ev.to + buf);
    const spark = renderEventSpark(sparkChannels, sFrom, sTo, ev.from, ev.to);

    const where = `${fmtM(startD)}<br>${durS.toFixed(2)}s`;
    return `
      <div class="elec-event-row ${cls}" data-idx="${ev.idx}">
        <div class="eer-idx">${ev.idx}</div>
        <div class="eer-type">${typeLabel}</div>
        <div class="eer-text">${desc}</div>
        <div class="eer-where">${where}</div>
        <div class="eer-spark">
          ${spark}
          <span class="sp-label">${sparkLabel}</span>
        </div>
      </div>`;
  }

  // Sparkline für eine Event-Zeile. channels = [{data, color, width, opacity, scale}].
  // scale ist ein opaker String — Channels mit dem gleichen scale-Wert (oder
  // ohne scale-Wert) teilen sich eine Y-Skala. So bleibt V_front/V_rear in
  // einer gemeinsamen Skala, aber TC-Status hat seine eigene.
  function renderEventSpark(channels, from, to, hiFrom, hiTo){
    const W = 200, H = 60;
    if (!channels.length || to <= from) return '';
    // Determine y-scales per unique scale key
    const scaleData = new Map();  // key → {min, max}
    channels.forEach(ch => {
      const key = ch.scale || '__default__';
      const arr = ch.data || [];
      if (!arr.length) return;
      let lo = Infinity, hi = -Infinity;
      for (let i = from; i <= to && i < arr.length; i++){
        const v = arr[i];
        if (!isFinite(v)) continue;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      if (!isFinite(lo) || !isFinite(hi)) return;
      if (lo === hi){ lo -= 1; hi += 1; }
      const ex = scaleData.get(key);
      if (!ex){
        scaleData.set(key, {min: lo, max: hi});
      } else {
        ex.min = Math.min(ex.min, lo);
        ex.max = Math.max(ex.max, hi);
      }
    });
    const xS = (i) => ((i - from) / Math.max(1, to - from)) * W;
    const paths = channels.map(ch => {
      const arr = ch.data || [];
      if (!arr.length) return '';
      const sk = ch.scale || '__default__';
      const sc = scaleData.get(sk);
      if (!sc) return '';
      const span = sc.max - sc.min || 1;
      const yS = (v) => H - ((v - sc.min) / span) * (H - 4) - 2;
      let d = '';
      let started = false;
      for (let i = from; i <= to && i < arr.length; i++){
        const v = arr[i];
        if (!isFinite(v)) { started = false; continue; }
        d += (started ? 'L' : 'M') + xS(i).toFixed(1) + ',' + yS(v).toFixed(1);
        started = true;
      }
      const op = (ch.opacity != null) ? ch.opacity : 1;
      return `<path d="${d}" stroke="${ch.color}" stroke-width="${ch.width || 2}" fill="none" opacity="${op}"/>`;
    }).join('');
    // Event-Window Highlight (dünner halbtransparenter Streifen)
    const hx1 = xS(hiFrom), hx2 = xS(hiTo);
    const highlight = `<rect x="${hx1.toFixed(1)}" y="0" width="${Math.max(1,(hx2-hx1)).toFixed(1)}" height="${H}" fill="#ffffff" opacity="0.08"/>`;
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${highlight}${paths}</svg>`;
  }

  // -- Trackmap ----------------------------------------------------------------
  // v21.40 — Trackmap cached state for the cursor-sync feature. After every
  // render we store the projection, lat/lon arrays and the relative pixel
  // bbox so:
  //   • setMapCursor(idx) can place the cursor dot from an external signal
  //     (the chart hover/click sends an index here)
  //   • the SVG-level pointer handlers can hit-test the lap path and emit
  //     the matching index back out to the chart.
  const _mapCache = { proj: null, lat: null, lon: null, w: 1200, h: 600 };
  let _cursorListeners = [];

  function _emitCursor(idx){
    for (const fn of _cursorListeners) {
      try { fn(idx); } catch(e) { /* never let one listener kill the bus */ }
    }
  }

  // Place a small marker on the trackmap at sample index `idx`. Negative or
  // out-of-range = clear the marker. Called by the chart hover handler.
  function setMapCursor(idx){
    if (!mapHost) return;
    let dot = mapHost.querySelector('.elec-cursor-dot');
    const { proj, lat, lon } = _mapCache;
    if (idx == null || idx < 0 || !proj || !lat || idx >= lat.length){
      if (dot) dot.setAttribute('opacity', '0');
      return;
    }
    const p = proj(lat[idx], lon[idx]);
    if (!dot){
      // Append a cursor group lazily; survives map re-renders since we
      // re-append it from renderTrackMap below.
      const ns = 'http://www.w3.org/2000/svg';
      dot = document.createElementNS(ns, 'g');
      dot.setAttribute('class', 'elec-cursor-dot');
      dot.innerHTML =
        '<circle r="9" fill="none" stroke="#ffffff" stroke-width="2"/>' +
        '<circle r="3" fill="#ffffff"/>';
      mapHost.appendChild(dot);
    }
    dot.setAttribute('transform', `translate(${p.x.toFixed(1)},${p.y.toFixed(1)})`);
    dot.setAttribute('opacity', '1');
  }

  function _bindMapPointerSync(){
    if (!mapHost || mapHost.__elecBound) return;
    mapHost.__elecBound = true;
    // Find the nearest sample index for a given SVG-coordinate click.
    // Uses the cached projection — for a typical 100Hz lap (~3000 points)
    // this is fast enough as a linear scan.
    function nearestIdx(svgX, svgY){
      const { lat, lon, proj } = _mapCache;
      if (!lat || !lon || !proj) return -1;
      let bestI = -1, bestD = Infinity;
      for (let i = 0; i < lat.length; i++){
        const p = proj(lat[i], lon[i]);
        const dx = p.x - svgX, dy = p.y - svgY;
        const d = dx*dx + dy*dy;
        if (d < bestD){ bestD = d; bestI = i; }
      }
      // Threshold: only emit when within ~30 SVG px (roughly the path width)
      return bestD < 900 ? bestI : -1;
    }
    function svgPointFromEvent(ev){
      const r = mapHost.getBoundingClientRect();
      const vb = mapHost.viewBox.baseVal;
      const cx = (ev.clientX - r.left) / r.width  * vb.width;
      const cy = (ev.clientY - r.top)  / r.height * vb.height;
      return { x: cx, y: cy };
    }
    mapHost.addEventListener('pointermove', (ev) => {
      // Don't fire while the user is panning the zoom — the brake/accel
      // helpers set a class on the SVG during drag; we just check buttons.
      if (ev.buttons) return;
      const p = svgPointFromEvent(ev);
      const i = nearestIdx(p.x, p.y);
      if (i >= 0){
        setMapCursor(i);
        _emitCursor(i);
      }
    });
    mapHost.addEventListener('pointerleave', () => {
      setMapCursor(-1);
      _emitCursor(-1);
    });
  }

  function renderTrackMap(lat, lon, events){
    _lastBgState.args = [lat, lon, events];
    const W = 1200, H = 600, PAD = 40;
    const n = lat.length;
    const latMin = Math.min.apply(null, lat), latMax = Math.max.apply(null, lat);
    const lonMin = Math.min.apply(null, lon), lonMax = Math.max.apply(null, lon);
    const latRange = latMax - latMin, lonRange = lonMax - lonMin;
    const cosLat = Math.cos((latMin + latMax) / 2 * Math.PI / 180);
    const wMeters = lonRange * 111000 * cosLat;
    const hMeters = latRange * 111000;
    const aspectMap = hMeters > 0 ? wMeters / hMeters : 1;
    const aspectVp = (W - 2*PAD) / (H - 2*PAD);
    let scaleX, scaleY, ox, oy;
    if (aspectMap > aspectVp){
      scaleX = (W - 2*PAD) / lonRange;
      scaleY = scaleX / cosLat;
      ox = PAD;
      oy = PAD + ((H - 2*PAD) - latRange * scaleY) / 2;
    } else {
      scaleY = (H - 2*PAD) / latRange;
      scaleX = scaleY * cosLat;
      oy = PAD;
      ox = PAD + ((W - 2*PAD) - lonRange * scaleX) / 2;
    }
    const proj = (la, lo) => ({
      x: ox + (lo - lonMin) * scaleX,
      y: oy + (latMax - la) * scaleY,
    });

    if (!tile){
      tile = makeTileLayer({
        svg: mapHost, W, H, proj,
        latMin, latMax, lonMin, lonMax, padding: 0.10,
      });
    }
    if (!zoomCtl){
      zoomCtl = makeZoomPan({ svg: mapHost, W, H, minZoom: 1, maxZoom: 8 });
    }

    let html = '';
    if (tile.active) html += tile.buildLayer();

    // Hintergrund-Pfad
    let bgPath = '';
    for (let i = 0; i < n; i++){
      const p = proj(lat[i], lon[i]);
      bgPath += (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
    }
    html += `<path class="bt-track-bg" d="${bgPath}" stroke-width="2.5" fill="none" stroke-linejoin="round"/>`;

    // Event-Bereiche: dickere Linie über den Event-Indizes
    const typeColor = {
      spike: '#ff3d3d', osc: '#ff9933', slip: '#ffcc33',
      tc: '#3aff7a', wc: '#00d4ff',
    };
    events.forEach(ev => {
      const color = typeColor[ev.type] || '#ffffff';
      let segPath = '';
      for (let i = ev.from; i <= ev.to; i++){
        if (i < 0 || i >= n) continue;
        const p = proj(lat[i], lon[i]);
        segPath += (i === ev.from ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
      }
      if (segPath){
        html += `<path d="${segPath}" stroke="${color}" stroke-width="6" stroke-opacity="0.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
      }
    });

    // Index-Marker (analog zu brake/accel-Analyse). Anker = Start des Events,
    // mit Linie zum Marker-Kreis oben-rechts.
    events.forEach(ev => {
      const anchor = ev.from;
      if (anchor == null || anchor < 0 || anchor >= lat.length) return;
      const p = proj(lat[anchor], lon[anchor]);
      const color = typeColor[ev.type] || '#888';
      const cx = p.x + 16, cy = p.y - 16;
      html += `<g data-idx="${ev.idx}">
        <line x1="${p.x.toFixed(1)}" y1="${p.y.toFixed(1)}" x2="${cx.toFixed(1)}" y2="${cy.toFixed(1)}" stroke="${color}" stroke-width="1" opacity="0.6"/>
        <circle class="mk-bubble" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="11" fill="${color}" stroke="#0a0a0a" stroke-width="1.5"/>
        <text x="${cx.toFixed(1)}" y="${(cy + 4).toFixed(1)}" font-family="JetBrains Mono" font-size="11" font-weight="600" fill="#0a0a0a" text-anchor="middle">${ev.idx}</text>
      </g>`;
    });

    mapHost.innerHTML = html;
    // v21.40 — Cache projection + arrays so the chart can drive setMapCursor.
    _mapCache.proj = proj;
    _mapCache.lat = lat;
    _mapCache.lon = lon;
    _mapCache.w = W; _mapCache.h = H;
    _bindMapPointerSync();
    if (tile.active) tile.bindLoadEvents(mapWrap);
    else tile.hideSpinner();
  }

  function rerenderMap(){
    if (_lastBgState.args) renderTrackMap.apply(null, _lastBgState.args);
  }
  function setMapview(on){
    if (!tile){ rerenderMap(); }
    if (!tile) return;
    on = !!on;
    if (on === tile.active) return;
    tile.active = on;
    rerenderMap();
  }

  // v21.40 — Multi-Channel-Chart unter der Trackmap entfernt in v21.46.
  // Ersetzt durch den Datenviewer-Chart als letzten Abschnitt jeder Analyse
  // (siehe gemeinsame speedChart-Sektion). `_mapCache`, `_cursorListeners`
  // und `setMapCursor` bleiben verfügbar, der neue Chart wird sie als
  // Cursor-Sync-Schnittstelle wieder konsumieren.

  channelRoles.onChange(tab => {
    if (tab === 'electronics') render();
  });
  render();
  return { render, setMapview };
})();

// ============================================================================
// v22.7 — Fahrwerks-Setup-Analyse.
//
// Pflicht-Kanäle: FEDERWEG GABEL + FEDERWEG FEDERBEIN.
// Erkennt ein Event-Typ: "auf Block" — flache Linie am Maximum mit
// scharfer Kante davor. Erkennung pro Element separat.
//
// Zusätzlich zwei Histogramme der Federweg-Geschwindigkeit (numerisch
// abgeleitet via zentralen Differenzen). Symmetrisch um 0: links Ausfedern
// (rebound), rechts Einfedern (compression). Höhe = Zeitanteil pro Bin.
// Auto-Skala — der Achsen-Range orientiert sich am Datenmaximum.
// ============================================================================
const suspensionAnalysis = (function(){
  const host = document.getElementById('suspension-analysis');
  if (!host) return null;
  const mapHost = document.getElementById('susp-trackmap');
  const mapWrap = document.getElementById('susp-trackmap-wrap');
  const histSection = document.getElementById('susp-hist-section');
  const histForkEl  = document.getElementById('susp-hist-fork');
  const histShockEl = document.getElementById('susp-hist-shock');
  const _lastBgState = { args: null };
  let tile = null;
  let zoomCtl = null;

  // -- Eventerkennung ---------------------------------------------------------
  //
  // Block-Detektor: Federweg ist "auf Block" wenn die Werte konstant am
  // (lokalen) Maximum hängen. Erkennen über zwei Bedingungen:
  //   1) Wert >= maxThreshold = max(arr) - tol  (tol = 1% der Spannweite)
  //   2) Werte-Spannweite innerhalb des Fensters < flatTol (sehr flach)
  // Für eine "scharfe Kante" prüfen wir, dass die Anstiegsrate kurz vor dem
  // Plateau-Anfang hoch war (steiler Anstieg) — sonst ist es nur ein langes,
  // gemächliches Halten an der oberen Grenze und kein echtes "auf Block".
  function detectBlock(arr, time){
    const n = arr.length;
    if (n < 10 || time.length !== n) return [];
    // v22.10 — Schwellen aus THRESHOLDS.suspension_block, ?? für Fallbacks
    // bei fehlender oder unvollständiger Config.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.suspension_block) || {};
    // Spannweite und Schwellen
    let lo = +Infinity, hi = -Infinity;
    for (let i = 0; i < n; i++){
      const v = arr[i];
      if (!isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return [];
    const range = hi - lo;
    const topBandFrac     = cfg.top_band_frac     ?? 0.01;
    const plateauFlatFrac = cfg.plateau_flat_frac ?? 0.005;
    const maxThreshold = hi - range * topBandFrac;
    const flatTol      = range * plateauFlatFrac;

    const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
    const minSamples  = Math.max(3, Math.round((cfg.plateau_min_seconds ?? 0.040) / dt));
    const gapSamples  = Math.max(2, Math.round((cfg.gap_seconds         ?? 0.020) / dt));
    const edgeSamples = Math.max(2, Math.round((cfg.edge_window_seconds ?? 0.060) / dt));
    const edgeRiseFrac = cfg.edge_rise_frac ?? 0.20;

    const runs = [];
    let i = 0;
    while (i < n){
      if (arr[i] >= maxThreshold){
        let j = i;
        let runMin = arr[i], runMax = arr[i];
        while (j < n && arr[j] >= maxThreshold){
          if (arr[j] < runMin) runMin = arr[j];
          if (arr[j] > runMax) runMax = arr[j];
          j++;
        }
        // Versuche kleine Lücken zu mergen (Sampling-Rauschen)
        let end = j - 1;
        let k = j;
        while (k < n){
          let found = -1;
          for (let m = k; m < Math.min(n, k + gapSamples); m++){
            if (arr[m] >= maxThreshold){ found = m; break; }
          }
          if (found < 0) break;
          let p = found;
          while (p < n && arr[p] >= maxThreshold){
            if (arr[p] < runMin) runMin = arr[p];
            if (arr[p] > runMax) runMax = arr[p];
            p++;
          }
          end = p - 1;
          k = p;
        }
        const len = end - i + 1;
        const flat = (runMax - runMin) <= flatTol;
        // Edge-Test: Wert am Plateaubeginn minus Wert edgeSamples davor
        const before = Math.max(0, i - edgeSamples);
        const rise = arr[i] - arr[before];
        const sharp = rise >= range * edgeRiseFrac;
        if (len >= minSamples && flat && sharp){
          runs.push({
            from: i, to: end,
            peakVal: runMax,
            rangeMax: hi,
            rise: rise,
          });
        }
        i = end + 1;
      } else {
        i++;
      }
    }
    return runs;
  }

  // -- Top-Out-Detektor (v22.9) ------------------------------------------------
  //
  // Spiegelbild von detectBlock: flache Linie am MINIMUM mit scharfer Kante
  // (steiler ABFALL) davor. Wert hängt am unteren 1%-Band der Spannweite,
  // Plateau-Streuung ≤ 0.5%, Plateau ≥ 40ms, und in den 60ms vor dem
  // Plateau-Beginn ist der Wert um ≥ 20% der Spannweite GEFALLEN.
  //
  // Top-Out an der Gabel = vorne komplett ausgefedert (z.B. nach starkem
  // Bremsen + Lastwechsel, oder wenn der Reifen vom Boden abhebt).
  // Top-Out am Federbein = Wheelie typisch — Hinterrad federt voll aus.
  function detectTopout(arr, time){
    const n = arr.length;
    if (n < 10 || time.length !== n) return [];
    // v22.10 — Schwellen aus THRESHOLDS.suspension_topout.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.suspension_topout) || {};
    let lo = +Infinity, hi = -Infinity;
    for (let i = 0; i < n; i++){
      const v = arr[i];
      if (!isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return [];
    const range = hi - lo;
    const minThreshold = lo + range * (cfg.bottom_band_frac    ?? 0.01);
    const flatTol      = range * (cfg.plateau_flat_frac        ?? 0.005);

    const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
    const minSamples   = Math.max(3, Math.round((cfg.plateau_min_seconds ?? 0.040) / dt));
    const gapSamples   = Math.max(2, Math.round((cfg.gap_seconds         ?? 0.020) / dt));
    const edgeSamples  = Math.max(2, Math.round((cfg.edge_window_seconds ?? 0.060) / dt));
    const edgeDropFrac = cfg.edge_drop_frac ?? 0.20;

    const runs = [];
    let i = 0;
    while (i < n){
      if (arr[i] <= minThreshold){
        let j = i;
        let runMin = arr[i], runMax = arr[i];
        while (j < n && arr[j] <= minThreshold){
          if (arr[j] < runMin) runMin = arr[j];
          if (arr[j] > runMax) runMax = arr[j];
          j++;
        }
        let end = j - 1;
        let k = j;
        while (k < n){
          let found = -1;
          for (let m = k; m < Math.min(n, k + gapSamples); m++){
            if (arr[m] <= minThreshold){ found = m; break; }
          }
          if (found < 0) break;
          let p = found;
          while (p < n && arr[p] <= minThreshold){
            if (arr[p] < runMin) runMin = arr[p];
            if (arr[p] > runMax) runMax = arr[p];
            p++;
          }
          end = p - 1;
          k = p;
        }
        const len = end - i + 1;
        const flat = (runMax - runMin) <= flatTol;
        const before = Math.max(0, i - edgeSamples);
        const drop = arr[before] - arr[i];   // gespiegelt: vorher höher
        const sharp = drop >= range * edgeDropFrac;
        if (len >= minSamples && flat && sharp){
          runs.push({
            from: i, to: end,
            minVal: runMin,
            rangeMin: lo,
            drop: drop,
          });
        }
        i = end + 1;
      } else {
        i++;
      }
    }
    return runs;
  }

  // -- Bump-Detektor (v22.9) ---------------------------------------------------
  //
  // Einzelner harter Schlag: hoher kurzer Spike in der Federweg-Geschwindigkeit,
  // nicht anhaltend. Wir gehen davon aus dass die Geschwindigkeits-Reihe schon
  // vorberechnet ist (travelVelocity), damit wir den Median-Absolut-Abweichungs-
  // Schwellwert (MAD) einmalig pro Kanal berechnen können.
  //
  // Definition:
  //   - |v[i]| > kMAD * MAD wo MAD = Median(|v - Median(v)|), kMAD = 6.0
  //     (= robuste Outlier-Schwelle, unempfindlich gegen Gauss-Verteilung des
  //      normalen Federwegs)
  //   - Spike-Dauer (zusammenhängende Indizes über der Schwelle) ≤ 100ms
  //     → längere Phasen sind absichtliche Federbewegung (Bremsen, Wheelie),
  //       kein Schlag.
  //   - Mindest-Peak-Wert |v_peak| > 200 mm/s (Safety-Floor: bei sehr
  //     ruhigen Sessions ist MAD klein und 6×MAD könnte normales Rauschen
  //     treffen; ein echter Bump bewegt die Federung mind. so schnell).
  //   - Spikes die direkt aneinander grenzen (< 50ms Abstand) werden zu einem
  //     Event gemerged — eine hektische Curb-Folge ist ein Event.
  function detectBump(velocities, time){
    const n = velocities.length;
    if (n < 10 || time.length !== n) return [];
    // v22.10 — Schwellen aus THRESHOLDS.suspension_bump.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.suspension_bump) || {};
    const kMAD            = cfg.k_mad                ?? 6.0;
    const safetyFloor     = cfg.safety_floor_mm_s    ?? 200;
    const maxDurSec       = cfg.max_duration_seconds ?? 0.100;
    const mergeGapSec     = cfg.merge_gap_seconds    ?? 0.050;

    // Robust median + MAD
    const finiteAbs = [];
    for (let i = 0; i < n; i++){
      const v = velocities[i];
      if (isFinite(v)) finiteAbs.push(v);
    }
    if (finiteAbs.length === 0) return [];
    const sortedV = finiteAbs.slice().sort((a, b) => a - b);
    const median = sortedV[Math.floor(sortedV.length / 2)];
    const abs_dev = finiteAbs.map(v => Math.abs(v - median)).sort((a, b) => a - b);
    const mad = abs_dev[Math.floor(abs_dev.length / 2)] || 1;
    const threshold = Math.max(kMAD * mad, safetyFloor);

    const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
    const maxDurSamples = Math.max(3, Math.round(maxDurSec   / dt));
    const mergeGap      = Math.max(2, Math.round(mergeGapSec / dt));

    const events = [];
    let i = 0;
    while (i < n){
      if (Math.abs(velocities[i]) > threshold){
        let j = i;
        let peakAbs = Math.abs(velocities[i]);
        let peakIdx = i;
        while (j < n && Math.abs(velocities[j]) > threshold){
          const av = Math.abs(velocities[j]);
          if (av > peakAbs){ peakAbs = av; peakIdx = j; }
          j++;
        }
        const dur = j - i;
        // Spike darf nicht zu lang sein (sonst Federbewegung statt Schlag).
        if (dur > 0 && dur <= maxDurSamples){
          // Merging mit vorherigem Event prüfen
          const last = events[events.length - 1];
          if (last && (i - last.to) <= mergeGap){
            last.to = j - 1;
            if (peakAbs > last.peakAbs){
              last.peakAbs = peakAbs;
              last.peakIdx = peakIdx;
              last.peakSigned = velocities[peakIdx];
            }
          } else {
            events.push({
              from: i,
              to: j - 1,
              peakAbs,
              peakIdx,
              peakSigned: velocities[peakIdx],
              threshold,
            });
          }
        }
        i = j;
      } else {
        i++;
      }
    }
    return events;
  }

  // -- Histogramm-Berechnung ---------------------------------------------------
  //
  // Federweg-Geschwindigkeit via zentrale Differenzen: v[i] = (x[i+1] - x[i-1])
  // / (t[i+1] - t[i-1]). Einheit identisch wie der Federweg-Kanal pro Sekunde
  // (typisch mm/s).
  function travelVelocity(arr, time){
    const n = arr.length;
    if (n < 3 || time.length !== n) return [];
    const out = new Array(n).fill(0);
    for (let i = 1; i < n - 1; i++){
      const dt = time[i+1] - time[i-1];
      out[i] = dt > 0 ? (arr[i+1] - arr[i-1]) / dt : 0;
    }
    out[0] = out[1];
    out[n-1] = out[n-2];
    return out;
  }

  // Histogramm-Bins berechnen, symmetrisch um 0. range = max(|v|) auto-skaliert.
  // numBins ungerade ist nicht zwingend, aber wir wählen 41 (≈ 20 Bins pro
  // Seite + zentraler Bin um 0), was bei typischen Federwegs-Geschwindigkeiten
  // gut lesbare Balken ergibt.
  function buildHistogram(velocities){
    const n = velocities.length;
    if (n === 0) return { bins: [], range: 0, binWidth: 0, totalPct: 0 };
    // v22.10 — Schwellen aus THRESHOLDS.suspension_histogram.
    const cfg = (window.THRESHOLDS && window.THRESHOLDS.suspension_histogram) || {};
    const numBins         = cfg.num_bins          ?? 41;
    const outlierQuantile = cfg.outlier_quantile  ?? 0.995;
    const safetyFloorFrac = cfg.safety_floor_frac ?? 0.1;
    let absMax = 0;
    for (let i = 0; i < n; i++){
      const a = Math.abs(velocities[i]);
      if (a > absMax) absMax = a;
    }
    if (absMax === 0) return { bins: [], range: 0, binWidth: 0, totalPct: 0 };
    // Robust: trimme das obere Quantil, damit Ausreißer (Sampling-Spikes)
    // nicht die ganze Skala dominieren. (n-1) als Basis weil ein einzelner
    // Wert bei n=101 sonst den Maximum-Index 100 ergibt → kein Trimming.
    const sortedAbs = velocities.map(Math.abs).sort((a, b) => a - b);
    const q99 = sortedAbs[Math.max(0, Math.floor((n - 1) * outlierQuantile))] || absMax;
    const range = Math.max(q99, absMax * safetyFloorFrac);  // safety floor
    const binWidth = (2 * range) / numBins;
    const counts = new Array(numBins).fill(0);
    let inRange = 0;
    for (let i = 0; i < n; i++){
      const v = velocities[i];
      // Werte außerhalb der Range gehen in den Rand-Bin
      let idx = Math.floor((v + range) / binWidth);
      if (idx < 0) idx = 0;
      if (idx >= numBins) idx = numBins - 1;
      counts[idx]++;
      inRange++;
    }
    // In Prozent der Zeit umrechnen
    const bins = counts.map((c, idx) => ({
      from: -range + idx * binWidth,
      to:   -range + (idx + 1) * binWidth,
      pct:  (c / n) * 100,
    }));
    return { bins, range, binWidth, totalPct: 100 };
  }

  // SVG-Histogramm rendern. side='fork' oder 'shock' (nur für die Farbe).
  function renderHistogram(svgEl, hist, label){
    if (!svgEl) return;
    if (!hist || hist.bins.length === 0){
      svgEl.innerHTML = `<text x="300" y="140" text-anchor="middle" font-family="JetBrains Mono" font-size="12" fill="#6a6a6a">KEINE DATEN</text>`;
      return;
    }
    const W = 600, H = 280;
    const PAD_L = 36, PAD_R = 12, PAD_T = 12, PAD_B = 36;
    const plotW = W - PAD_L - PAD_R;
    const plotH = H - PAD_T - PAD_B;
    const { bins, range } = hist;
    const maxPct = Math.max.apply(null, bins.map(b => b.pct)) || 1;
    const barW = plotW / bins.length;

    let html = '';
    // Achsen-Linien
    html += `<line class="hb-axis" x1="${PAD_L}" y1="${PAD_T + plotH}" x2="${PAD_L + plotW}" y2="${PAD_T + plotH}"/>`;
    html += `<line class="hb-axis" x1="${PAD_L}" y1="${PAD_T}" x2="${PAD_L}" y2="${PAD_T + plotH}"/>`;

    // Balken — links (Ausfedern, v<0) anders färben als rechts (Einfedern, v>0)
    bins.forEach((b, i) => {
      const x = PAD_L + i * barW;
      const h = (b.pct / maxPct) * plotH;
      const y = PAD_T + plotH - h;
      const center = (b.from + b.to) / 2;
      const cls = center < 0 ? 'hb-bar-out' : 'hb-bar-in';
      html += `<rect class="${cls}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(0.5, barW - 0.5).toFixed(1)}" height="${h.toFixed(1)}"/>`;
    });

    // Mittellinie bei v=0 (gestrichelt)
    const xZero = PAD_L + plotW / 2;
    html += `<line class="hb-zero-line" x1="${xZero}" y1="${PAD_T}" x2="${xZero}" y2="${PAD_T + plotH}"/>`;

    // X-Achse Ticks: -range, -range/2, 0, +range/2, +range
    const ticks = [-range, -range/2, 0, range/2, range];
    ticks.forEach(v => {
      const x = PAD_L + ((v + range) / (2 * range)) * plotW;
      html += `<line class="hb-tick" x1="${x.toFixed(1)}" y1="${PAD_T + plotH}" x2="${x.toFixed(1)}" y2="${PAD_T + plotH + 4}"/>`;
      const sign = v > 0 ? '+' : '';
      html += `<text class="hb-tick-label" x="${x.toFixed(1)}" y="${PAD_T + plotH + 16}" text-anchor="middle">${sign}${v.toFixed(0)}</text>`;
    });

    // Y-Achse Ticks: 0, maxPct/2, maxPct (als %)
    [0, maxPct/2, maxPct].forEach(p => {
      const y = PAD_T + plotH - (p / maxPct) * plotH;
      html += `<line class="hb-tick" x1="${PAD_L - 4}" y1="${y.toFixed(1)}" x2="${PAD_L}" y2="${y.toFixed(1)}"/>`;
      html += `<text class="hb-tick-label" x="${PAD_L - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end">${p.toFixed(1)}%</text>`;
    });

    // Achsen-Beschriftungen
    html += `<text class="hb-axis-label" x="${PAD_L + plotW/2}" y="${H - 6}" text-anchor="middle">${label} (links: AUSFEDERN · rechts: EINFEDERN)</text>`;
    html += `<text class="hb-axis-label" x="${PAD_L - 28}" y="${PAD_T + plotH/2}" text-anchor="middle" transform="rotate(-90 ${PAD_L - 28} ${PAD_T + plotH/2})">ZEITANTEIL</text>`;

    svgEl.innerHTML = html;
  }

  // -- Render ------------------------------------------------------------------

  function render(){
    try { renderInner(); }
    catch (e){
      host.innerHTML = `<div class="ba-empty" style="color:#ffaa00">
        FEHLER IN DER FAHRWERKS-ANALYSE — ${escapeHTML(e.message || String(e))}
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      if (histSection) histSection.hidden = true;
    }
  }

  function renderInner(){
    const extras = DATA.extras || [];
    if (!extras.length){
      host.innerHTML = '<div class="ba-empty">' +
        '→ DIESE RUNDE HAT KEINE ZUSATZ-KANÄLE. ' +
        'Die Fahrwerks-Analyse braucht Federweg-Sensoren an Gabel und Federbein.</div>';
      if (mapWrap) mapWrap.hidden = true;
      if (histSection) histSection.hidden = true;
      return;
    }

    const a = channelRoles.getAllAssignments('suspension');
    const forkCh  = a.suspension_fork;
    const shockCh = a.suspension_shock;

    if (!forkCh || !shockCh){
      const missing = [];
      if (!forkCh)  missing.push('FEDERWEG GABEL');
      if (!shockCh) missing.push('FEDERWEG FEDERBEIN');
      host.innerHTML = `<div class="ba-empty" style="text-align:left;line-height:1.7">
        <div style="color:var(--accent);font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:.04em;margin-bottom:8px">
          PFLICHT-KANAL FEHLT: ${missing.join(' + ')}
        </div>
        <div style="color:var(--ink-dim);text-transform:none;letter-spacing:0;font-size:13px">
          Klick oben auf den Standardkanal und wähle den passenden Datenkanal aus.
          Die Analyse startet, sobald Gabel- und Federbein-Federweg zugeordnet sind.
        </div>
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      if (histSection) histSection.hidden = true;
      return;
    }

    const fork  = forkCh.data  || [];
    const shock = shockCh.data || [];
    const dist  = DATA.distance || [];
    const time  = DATA.time || [];
    const lat   = DATA.lat || [];
    const lon   = DATA.lon || [];

    if (fork.length < 10 || fork.length !== shock.length){
      host.innerHTML = `<div class="ba-empty">
        GABEL-/FEDERBEIN-FEDERWEG HABEN UNTERSCHIEDLICHE GRIDS
        (${fork.length} vs ${shock.length} Samples)
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      if (histSection) histSection.hidden = true;
      return;
    }
    if (dist.length !== fork.length){
      host.innerHTML = `<div class="ba-empty">
        FEDERWEG-KANÄLE PASSEN NICHT ZUM DISTANZ-GRID
        (${fork.length} vs ${dist.length} Samples)
      </div>`;
      if (mapWrap) mapWrap.hidden = true;
      if (histSection) histSection.hidden = true;
      return;
    }

    // Federweg-Geschwindigkeit (für Bump-Detektor + Histogramm wiederverwendet).
    const vFork  = travelVelocity(fork,  time);
    const vShock = travelVelocity(shock, time);

    // Event-Detektoren — 6 Typen, pro Element separat.
    const forkBlocks  = detectBlock(fork,  time).map(r => ({ ...r, type: 'block-fork' }));
    const shockBlocks = detectBlock(shock, time).map(r => ({ ...r, type: 'block-shock' }));
    const forkTops    = detectTopout(fork,  time).map(r => ({ ...r, type: 'topping-fork' }));
    const shockTops   = detectTopout(shock, time).map(r => ({ ...r, type: 'topping-shock' }));
    const forkBumps   = detectBump(vFork,  time).map(r => ({ ...r, type: 'bump-fork' }));
    const shockBumps  = detectBump(vShock, time).map(r => ({ ...r, type: 'bump-shock' }));

    const allEvents = [...forkBlocks, ...shockBlocks,
                       ...forkTops,   ...shockTops,
                       ...forkBumps,  ...shockBumps]
      .sort((a, b) => a.from - b.from)
      .map((e, idx) => ({ ...e, idx: idx + 1 }));

    // Summary — sortiert nach Severity: Block > Topping > Bump.
    const cntBlockFork  = forkBlocks.length;
    const cntBlockShock = shockBlocks.length;
    const cntTopFork    = forkTops.length;
    const cntTopShock   = shockTops.length;
    const cntBumpFork   = forkBumps.length;
    const cntBumpShock  = shockBumps.length;
    const cntBlock = cntBlockFork + cntBlockShock;
    const cntTop   = cntTopFork   + cntTopShock;
    const cntBump  = cntBumpFork  + cntBumpShock;
    const total    = allEvents.length;

    let summary;
    if (total === 0){
      summary = 'OK — Fahrwerk arbeitet im erwarteten Bereich. Keine Auffälligkeiten.';
    } else if (cntBlock > 0){
      summary = `FOKUS — ${cntBlock} BLOCK-Ereignis${cntBlock===1?'':'se'} erkannt. ` +
                `Federweg reicht hier nicht — Vorspannung / Druckstufe anpassen.`;
    } else if (cntTop > 0){
      summary = `HINWEISE — ${cntTop} TOP-OUT-Ereignis${cntTop===1?'':'se'} erkannt. ` +
                `Federung schlägt voll aus — Rebound-Dämpfung / Vorspannung prüfen.`;
    } else {
      summary = `HINWEISE — ${cntBump} BUMP-Treffer erkannt. ` +
                `Punkte auf der Trackmap markieren harte Stöße (Curbs, Bumps).`;
    }

    let html = `
      <div class="ba-summary">
        <div class="bas-headline">${escapeHTML(summary)}</div>
        <div class="bas-counts">
          <span>${total} EVENTS</span>
          ${cntBlockFork  ? `<span class="n" style="color:#ff3d3d">${cntBlockFork} GABEL BLOCK</span>` : ''}
          ${cntBlockShock ? `<span class="n" style="color:#ff9933">${cntBlockShock} FEDERBEIN BLOCK</span>` : ''}
          ${cntTopFork    ? `<span class="n" style="color:#33ccff">${cntTopFork} GABEL TOP-OUT</span>` : ''}
          ${cntTopShock   ? `<span class="n" style="color:#3aff7a">${cntTopShock} FEDERBEIN TOP-OUT</span>` : ''}
          ${cntBumpFork   ? `<span class="n" style="color:#ffcc33">${cntBumpFork} GABEL BUMP</span>` : ''}
          ${cntBumpShock  ? `<span class="n" style="color:#cc88ff">${cntBumpShock} FEDERBEIN BUMP</span>` : ''}
        </div>
      </div>`;

    if (allEvents.length){
      const ctx = { dist, time, fork, shock, vFork, vShock };
      html += `
        <div class="susp-event-table head">
          <div>#</div><div>TYP</div><div>BESCHREIBUNG</div><div>POSITION</div><div>VERLAUF</div>
        </div>`;
      allEvents.forEach(ev => { html += renderEventRow(ev, ctx); });
    } else {
      html += `<div class="ba-empty">KEINE EREIGNISSE — FAHRWERK ARBEITET UNAUFFÄLLIG.</div>`;
    }
    host.innerHTML = html;

    // Histogramme — immer rendern wenn Pflicht-Kanäle da sind
    const histFork  = buildHistogram(vFork);
    const histShock = buildHistogram(vShock);
    renderHistogram(histForkEl,  histFork,  'GESCHWINDIGKEIT (mm/s)');
    renderHistogram(histShockEl, histShock, 'GESCHWINDIGKEIT (mm/s)');
    if (histSection) histSection.hidden = false;

    // Trackmap
    if (mapHost && lat.length === fork.length && lat.length >= 10){
      renderTrackMap(lat, lon, allEvents);
      mapWrap.hidden = false;
    } else {
      if (mapWrap) mapWrap.hidden = true;
    }

    // v22.0 — idx → Sample-Mapping für Chart-Cursor-Sync.
    const idxToSample = {};
    allEvents.forEach(ev => {
      if (ev.from != null && ev.from >= 0 && ev.from < (DATA.distance || []).length){
        idxToSample[String(ev.idx)] = ev.from;
      }
    });

    const mrl = setupMarkerRowLink(host, mapHost, mapWrap, (eventIdx) => {
      const chart = window._coachCharts && window._coachCharts.suspension;
      if (!chart) return;
      if (eventIdx == null){
        chart.clearStickyCursor();
      } else {
        const sample = idxToSample[String(eventIdx)];
        if (sample != null) chart.setStickyCursor(sample);
      }
    });
    if (mrl) mrl.clear();
  }

  // -- Event-Zeile -------------------------------------------------------------

  function renderEventRow(ev, ctx){
    const { dist, time, fork, shock } = ctx;
    const startD = dist[ev.from] || 0;
    const endD   = dist[ev.to]   || 0;
    const durS   = (time[ev.to] || 0) - (time[ev.from] || 0);

    let typeLabel = '', desc = '', cls = '';
    let sparkData = null, sparkColor = '#ffffff', sparkLabel = '';
    if (ev.type === 'block-fork'){
      cls = 'block-fork';
      typeLabel = '↑ GABEL AUF BLOCK';
      desc = `<span class="nh">Federweg Gabel hängt am Maximum:</span> ` +
             `Peak ${ev.peakVal.toFixed(1)} (max ${ev.rangeMax.toFixed(1)}), ` +
             `Anstieg ${ev.rise.toFixed(1)} zuvor. ` +
             `Setup-Hinweis: Druckstufe vorne stärker, Vorspannung prüfen, ` +
             `evtl. härtere Feder.`;
      sparkData = fork;
      sparkColor = '#ff3d3d';
      sparkLabel = 'FEDERWEG GABEL';
    } else if (ev.type === 'block-shock'){
      cls = 'block-shock';
      typeLabel = '↑ FEDERBEIN AUF BLOCK';
      desc = `<span class="nh">Federweg Federbein hängt am Maximum:</span> ` +
             `Peak ${ev.peakVal.toFixed(1)} (max ${ev.rangeMax.toFixed(1)}), ` +
             `Anstieg ${ev.rise.toFixed(1)} zuvor. ` +
             `Setup-Hinweis: Druckstufe hinten stärker, Vorspannung prüfen, ` +
             `evtl. härtere Feder.`;
      sparkData = shock;
      sparkColor = '#ff9933';
      sparkLabel = 'FEDERWEG FEDERBEIN';
    } else if (ev.type === 'topping-fork'){
      cls = 'topping-fork';
      typeLabel = '↓ GABEL TOP-OUT';
      desc = `<span class="nh">Federweg Gabel komplett ausgefedert:</span> ` +
             `Minimum ${ev.minVal.toFixed(1)} (Range-Min ${ev.rangeMin.toFixed(1)}), ` +
             `Abfall ${ev.drop.toFixed(1)} zuvor. ` +
             `Setup-Hinweis: Rebound (Zugstufe) Gabel verlangsamen, ` +
             `Vorspannung erhöhen.`;
      sparkData = fork;
      sparkColor = '#33ccff';
      sparkLabel = 'FEDERWEG GABEL';
    } else if (ev.type === 'topping-shock'){
      cls = 'topping-shock';
      typeLabel = '↓ FEDERBEIN TOP-OUT';
      desc = `<span class="nh">Federweg Federbein komplett ausgefedert:</span> ` +
             `Minimum ${ev.minVal.toFixed(1)} (Range-Min ${ev.rangeMin.toFixed(1)}), ` +
             `Abfall ${ev.drop.toFixed(1)} zuvor. ` +
             `Häufig bei Wheelies. Setup-Hinweis: Rebound (Zugstufe) ` +
             `hinten verlangsamen, Vorspannung erhöhen.`;
      sparkData = shock;
      sparkColor = '#3aff7a';
      sparkLabel = 'FEDERWEG FEDERBEIN';
    } else if (ev.type === 'bump-fork'){
      cls = 'bump-fork';
      typeLabel = '⚡ GABEL BUMP';
      const direction = ev.peakSigned > 0 ? 'Einfeder' : 'Ausfeder';
      desc = `<span class="nh">Harter Schlag auf die Gabel:</span> ` +
             `${direction}-Peak ${Math.abs(ev.peakSigned).toFixed(0)} mm/s ` +
             `(Schwelle ${ev.threshold.toFixed(0)} mm/s). ` +
             `Streckenunebenheit oder Curb. Wiederholt sich das hier immer: ` +
             `Druckstufe / Highspeed-Compression prüfen.`;
      sparkData = fork;
      sparkColor = '#ffcc33';
      sparkLabel = 'FEDERWEG GABEL';
    } else if (ev.type === 'bump-shock'){
      cls = 'bump-shock';
      typeLabel = '⚡ FEDERBEIN BUMP';
      const direction = ev.peakSigned > 0 ? 'Einfeder' : 'Ausfeder';
      desc = `<span class="nh">Harter Schlag auf das Federbein:</span> ` +
             `${direction}-Peak ${Math.abs(ev.peakSigned).toFixed(0)} mm/s ` +
             `(Schwelle ${ev.threshold.toFixed(0)} mm/s). ` +
             `Streckenunebenheit oder Curb. Wiederholt sich das hier immer: ` +
             `Druckstufe / Highspeed-Compression prüfen.`;
      sparkData = shock;
      sparkColor = '#cc88ff';
      sparkLabel = 'FEDERWEG FEDERBEIN';
    }

    const where = `${Math.round(startD)} – ${Math.round(endD)} m<br>${durS.toFixed(2)} s`;

    // Sparkline: Fenster um das Event mit 0.5s Padding davor/danach
    const dt = (time[time.length-1] - time[0]) / Math.max(1, time.length-1);
    const pad = Math.max(1, Math.round(0.5 / dt));
    const from = Math.max(0, ev.from - pad);
    const to   = Math.min(time.length - 1, ev.to + pad);
    const sparkSvg = buildSparkline(sparkData, from, to, ev.from, ev.to, sparkColor);

    return `
      <div class="susp-event-row ${cls}" data-idx="${ev.idx}" data-anchor="${ev.from}">
        <div class="eer-idx">${ev.idx}</div>
        <div class="eer-type">${typeLabel}</div>
        <div class="eer-text">${desc}</div>
        <div class="eer-where">${where}</div>
        <div class="eer-spark">
          ${sparkSvg}
          <span class="sp-label">${sparkLabel}</span>
        </div>
      </div>`;
  }

  // Mini-Sparkline (single channel) für die Event-Zeile.
  function buildSparkline(arr, from, to, hiFrom, hiTo, color){
    const W = 220, H = 40;
    if (!arr || !arr.length || to <= from) return `<svg width="${W}" height="${H}"></svg>`;
    let lo = +Infinity, hi = -Infinity;
    for (let i = from; i <= to && i < arr.length; i++){
      const v = arr[i];
      if (!isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (!isFinite(lo) || !isFinite(hi) || lo === hi){ lo -= 1; hi += 1; }
    const span = hi - lo;
    const xS = (i) => ((i - from) / Math.max(1, to - from)) * W;
    const yS = (v) => H - ((v - lo) / span) * (H - 4) - 2;
    let d = '';
    let started = false;
    for (let i = from; i <= to && i < arr.length; i++){
      const v = arr[i];
      if (!isFinite(v)){ started = false; continue; }
      d += (started ? 'L' : 'M') + xS(i).toFixed(1) + ',' + yS(v).toFixed(1);
      started = true;
    }
    const hx1 = xS(hiFrom), hx2 = xS(hiTo);
    const highlight = `<rect x="${hx1.toFixed(1)}" y="0" width="${Math.max(1,(hx2-hx1)).toFixed(1)}" height="${H}" fill="#ffffff" opacity="0.08"/>`;
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${highlight}<path d="${d}" stroke="${color}" stroke-width="2" fill="none"/></svg>`;
  }

  // -- Trackmap ----------------------------------------------------------------
  // Cursor-Sync-Schnittstelle identisch zu electronicsAnalysis.
  const _mapCache = { proj: null, lat: null, lon: null, w: 1200, h: 600 };
  let _cursorListeners = [];

  function _emitCursor(idx){
    for (const fn of _cursorListeners){
      try { fn(idx); } catch(e) { /* never let one listener kill the bus */ }
    }
  }

  function setMapCursor(idx){
    if (!mapHost) return;
    let dot = mapHost.querySelector('.elec-cursor-dot');
    const { proj, lat, lon } = _mapCache;
    if (idx == null || idx < 0 || !proj || !lat || idx >= lat.length){
      if (dot) dot.setAttribute('opacity', '0');
      return;
    }
    const p = proj(lat[idx], lon[idx]);
    if (!dot){
      const ns = 'http://www.w3.org/2000/svg';
      dot = document.createElementNS(ns, 'g');
      dot.setAttribute('class', 'elec-cursor-dot');
      dot.innerHTML =
        '<circle r="9" fill="none" stroke="#ffffff" stroke-width="2"/>' +
        '<circle r="3" fill="#ffffff"/>';
      mapHost.appendChild(dot);
    }
    dot.setAttribute('transform', `translate(${p.x.toFixed(1)},${p.y.toFixed(1)})`);
    dot.setAttribute('opacity', '1');
  }

  function _bindMapPointerSync(){
    if (!mapHost || mapHost.__suspBound) return;
    mapHost.__suspBound = true;
    function nearestIdx(svgX, svgY){
      const { lat, lon, proj } = _mapCache;
      if (!lat || !lon || !proj) return -1;
      let bestI = -1, bestD = Infinity;
      for (let i = 0; i < lat.length; i++){
        const p = proj(lat[i], lon[i]);
        const dx = p.x - svgX, dy = p.y - svgY;
        const d = dx*dx + dy*dy;
        if (d < bestD){ bestD = d; bestI = i; }
      }
      return bestD < 900 ? bestI : -1;
    }
    function svgPointFromEvent(ev){
      const r = mapHost.getBoundingClientRect();
      const vb = mapHost.viewBox.baseVal;
      const cx = (ev.clientX - r.left) / r.width  * vb.width;
      const cy = (ev.clientY - r.top)  / r.height * vb.height;
      return { x: cx, y: cy };
    }
    mapHost.addEventListener('pointermove', (ev) => {
      if (ev.buttons) return;
      const p = svgPointFromEvent(ev);
      const i = nearestIdx(p.x, p.y);
      if (i >= 0){ setMapCursor(i); _emitCursor(i); }
    });
    mapHost.addEventListener('pointerleave', () => {
      setMapCursor(-1); _emitCursor(-1);
    });
  }

  function renderTrackMap(lat, lon, events){
    _lastBgState.args = [lat, lon, events];
    const W = 1200, H = 600, PAD = 40;
    const n = lat.length;
    const latMin = Math.min.apply(null, lat), latMax = Math.max.apply(null, lat);
    const lonMin = Math.min.apply(null, lon), lonMax = Math.max.apply(null, lon);
    const latRange = latMax - latMin, lonRange = lonMax - lonMin;
    const cosLat = Math.cos((latMin + latMax) / 2 * Math.PI / 180);
    const wMeters = lonRange * 111000 * cosLat;
    const hMeters = latRange * 111000;
    const aspectMap = hMeters > 0 ? wMeters / hMeters : 1;
    const aspectVp = (W - 2*PAD) / (H - 2*PAD);
    let scaleX, scaleY, ox, oy;
    if (aspectMap > aspectVp){
      scaleX = (W - 2*PAD) / lonRange;
      scaleY = scaleX / cosLat;
      ox = PAD;
      oy = PAD + ((H - 2*PAD) - latRange * scaleY) / 2;
    } else {
      scaleY = (H - 2*PAD) / latRange;
      scaleX = scaleY * cosLat;
      oy = PAD;
      ox = PAD + ((W - 2*PAD) - lonRange * scaleX) / 2;
    }
    const proj = (la, lo) => ({
      x: ox + (lo - lonMin) * scaleX,
      y: oy + (latMax - la) * scaleY,
    });

    if (!tile){
      tile = makeTileLayer({
        svg: mapHost, W, H, proj,
        latMin, latMax, lonMin, lonMax, padding: 0.10,
      });
    }
    if (!zoomCtl){
      zoomCtl = makeZoomPan({ svg: mapHost, W, H, minZoom: 1, maxZoom: 8 });
    }

    let html = '';
    if (tile.active) html += tile.buildLayer();

    let bgPath = '';
    for (let i = 0; i < n; i++){
      const p = proj(lat[i], lon[i]);
      bgPath += (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
    }
    html += `<path class="bt-track-bg" d="${bgPath}" stroke-width="2.5" fill="none" stroke-linejoin="round"/>`;

    const typeColor = {
      'block-fork':    '#ff3d3d',
      'block-shock':   '#ff9933',
      'topping-fork':  '#33ccff',
      'topping-shock': '#3aff7a',
      'bump-fork':     '#ffcc33',
      'bump-shock':    '#cc88ff',
    };
    events.forEach(ev => {
      const color = typeColor[ev.type] || '#ffffff';
      let segPath = '';
      for (let i = ev.from; i <= ev.to; i++){
        if (i < 0 || i >= n) continue;
        const p = proj(lat[i], lon[i]);
        segPath += (i === ev.from ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
      }
      if (segPath){
        html += `<path d="${segPath}" stroke="${color}" stroke-width="6" stroke-opacity="0.75" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
      }
    });

    events.forEach(ev => {
      const anchor = ev.from;
      if (anchor == null || anchor < 0 || anchor >= lat.length) return;
      const p = proj(lat[anchor], lon[anchor]);
      const color = typeColor[ev.type] || '#888';
      const cx = p.x + 16, cy = p.y - 16;
      html += `<g data-idx="${ev.idx}">
        <line x1="${p.x.toFixed(1)}" y1="${p.y.toFixed(1)}" x2="${cx.toFixed(1)}" y2="${cy.toFixed(1)}" stroke="${color}" stroke-width="1" opacity="0.6"/>
        <circle class="mk-bubble" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="11" fill="${color}" stroke="#0a0a0a" stroke-width="1.5"/>
        <text x="${cx.toFixed(1)}" y="${(cy + 4).toFixed(1)}" font-family="JetBrains Mono" font-size="11" font-weight="600" fill="#0a0a0a" text-anchor="middle">${ev.idx}</text>
      </g>`;
    });

    mapHost.innerHTML = html;
    _mapCache.proj = proj;
    _mapCache.lat = lat;
    _mapCache.lon = lon;
    _mapCache.w = W; _mapCache.h = H;
    _bindMapPointerSync();
    if (tile.active) tile.bindLoadEvents(mapWrap);
    else tile.hideSpinner();
  }

  function rerenderMap(){
    if (_lastBgState.args) renderTrackMap.apply(null, _lastBgState.args);
  }
  function setMapview(on){
    if (!tile){ rerenderMap(); }
    if (!tile) return;
    on = !!on;
    if (on === tile.active) return;
    tile.active = on;
    rerenderMap();
  }

  channelRoles.onChange(tab => {
    if (tab === 'suspension') render();
  });
  render();
  return { render, setMapview };
})();

// v21.24 — MAPVIEW-Toggle für Coach-Trackmaps (Brake + Accel)
// v21.25 — Single-Button-Toggle (vorher zwei-Optionen seg-switch)
// v21.39 — auch für Elektronik-Trackmap (elec)
// v22.7 — auch für Fahrwerks-Trackmap (susp)
(function(){
  function wire(prefix, mod){
    const btn  = document.getElementById('tm-bg-toggle-' + prefix);
    const attr = document.getElementById('tm-attribution-' + prefix);
    if (!btn || !mod) return;
    function apply(on){
      if (mod.setMapview) mod.setMapview(on);
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (attr) attr.style.display = on ? '' : 'none';
    }
    btn.addEventListener('click', () => {
      apply(!btn.classList.contains('active'));
    });
  }
  if (typeof brakeAnalysis !== 'undefined')      wire('brake', brakeAnalysis);
  if (typeof accelAnalysis !== 'undefined')      wire('accel', accelAnalysis);
  if (typeof electronicsAnalysis !== 'undefined') wire('elec',  electronicsAnalysis);
  if (typeof suspensionAnalysis !== 'undefined') wire('susp',  suspensionAnalysis);
})();


// ============================================================================
// v21.46 — Speed+Channels Chart pro Analyse-Tab (Bremsen, Beschleunigung,
// Elektronik). Vorselektion = die per channelRoles dieser Analyse
// zugeordneten Channels. Der Picker im Chart erlaubt jederzeit weitere
// Channels zu wählen, identisch zum Datenviewer.
//
// Jede Instanz hat eigene DOM-IDs (`csb-`/`csa-`/`cse-` Prefix). Vorselektion
// wird beim ersten Render gesetzt; danach behält jeder Chart seine eigene
// Auswahl beim Tab-Switch (DOM bleibt erhalten).
// ============================================================================
(function(){
  if (typeof window === 'undefined' || !window.createSpeedChart) return;
  if (typeof channelRoles === 'undefined') return;

  // Mapping Analyse-Tab → Picker-/Chart-IDs + zugeordnete Rollen-Slots.
  const SPECS = [
    {
      tab:    'brake',
      roles:  ['brake_pressure', 'lean'],
      ids: {
        svg:     'csb-svg',
        legend:  'csb-legend',
        badge:   'csb-count',
        zoomBtn: 'csb-zoom-reset',
        picker: {
          btnOpen:  'csb-pick',
          modal:    'csb-modal',
          body:     'csb-body',
          hint:     'csb-hint',
          search:   'csb-search',
          btnClose: 'csb-modal-close',
          btnApply: 'csb-apply',
          btnClear: 'csb-clear',
        },
      },
    },
    {
      tab:    'accel',
      roles:  ['throttle', 'lean'],
      ids: {
        svg:     'csa-svg',
        legend:  'csa-legend',
        badge:   'csa-count',
        zoomBtn: 'csa-zoom-reset',
        picker: {
          btnOpen:  'csa-pick',
          modal:    'csa-modal',
          body:     'csa-body',
          hint:     'csa-hint',
          search:   'csa-search',
          btnClose: 'csa-modal-close',
          btnApply: 'csa-apply',
          btnClear: 'csa-clear',
        },
      },
    },
    {
      tab:    'electronics',
      roles:  ['wheel_speed_front', 'wheel_speed_rear', 'throttle', 'lean',
               'tc_status', 'wc_status'],
      ids: {
        svg:     'cse-svg',
        legend:  'cse-legend',
        badge:   'cse-count',
        zoomBtn: 'cse-zoom-reset',
        picker: {
          btnOpen:  'cse-pick',
          modal:    'cse-modal',
          body:     'cse-body',
          hint:     'cse-hint',
          search:   'cse-search',
          btnClose: 'cse-modal-close',
          btnApply: 'cse-apply',
          btnClear: 'cse-clear',
        },
      },
    },
    // v22.7 — Fahrwerks-Setup: Federweg Gabel + Federbein als Vorselektion.
    {
      tab:    'suspension',
      roles:  ['suspension_fork', 'suspension_shock'],
      ids: {
        svg:     'css-svg',
        legend:  'css-legend',
        badge:   'css-count',
        zoomBtn: 'css-zoom-reset',
        picker: {
          btnOpen:  'css-pick',
          modal:    'css-modal',
          body:     'css-body',
          hint:     'css-hint',
          search:   'css-search',
          btnClose: 'css-modal-close',
          btnApply: 'css-apply',
          btnClear: 'css-clear',
        },
      },
    },
  ];

  function initial(spec){
    // Vorselektion: alle Channel-IDs aus den zur Analyse zugeordneten Rollen.
    const a = channelRoles.getAllAssignments(spec.tab);
    const ids = [];
    spec.roles.forEach(role => {
      const slot = a[role];
      if (slot && slot.id) ids.push(slot.id);
    });
    return ids;
  }

  const charts = {};
  SPECS.forEach(spec => {
    // Wenn das SVG nicht im DOM ist (z.B. Tab leer), Factory-Aufruf macht
    // null zurück und wir überspringen still.
    const initialIds = initial(spec);
    const inst = window.createSpeedChart({
      data: {
        distance: DATA.distance,
        speed:    DATA.speed,
        extras:   DATA.extras || [],
        speedUnit: DATA.speed_unit || 'km/h',
      },
      ids: spec.ids,
      initialActiveExtraIds: initialIds,
      initialSpeedActive: true,
      // Cursor-Sync mit der jeweiligen Trackmap kommt nicht in dieser
      // Iteration; v21.40 _cursorListeners + setMapCursor bleiben verfügbar
      // und können später angedockt werden.
      onCursor: () => {},
      onClearLive: () => {},
      onChannelChange: () => {},
      externalStickyIdx: () => -1,
    });
    if (inst) charts[spec.tab] = inst;
  });

  // v22.0 — Charts global verfügbar machen, damit die Analyse-Module
  // (brakeAnalysis/accelAnalysis/electronicsAnalysis) ihre Marker-/Row-
  // Selektion an den Chart-Cursor weiterleiten können. Der Schlüssel ist
  // der Tab-Name ('brake'|'accel'|'electronics').
  window._coachCharts = charts;

  // Wenn der User die Channel-Rollen-Zuordnung anpasst, aktualisieren wir
  // nicht die Pre-Selection des Charts — der User hat ja bewusst sein
  // Channel-Set im Chart-Picker gesetzt. Sticky.
  // (Falls das später anders gewünscht ist: über channelRoles.onChange
  // Zuordnungen neu lesen und die Chart-Instanz mit neuer Vorselektion
  // re-initialisieren.)
})();
</script>
</body>
</html>
"""
