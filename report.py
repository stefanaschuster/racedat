"""Generate the standalone HTML comparison report."""
import json
import os
import numpy as np

from compare import theoretical_best, segment_track

from trackmap_helpers import (
    TILE_HELPERS_JS as _TILE_HELPERS_JS,
    TILE_SPINNER_CSS as _TILE_SPINNER_CSS,
    tile_provider_js as _tile_provider_js,
    tile_provider_button_class as _tile_btn_cls,
)


def _fmt_lap(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"


def _short(path: str, max_len: int = 38) -> str:
    base = os.path.basename(path)
    if len(base) <= max_len:
        return base
    return base[: max_len - 1] + "…"


# ---- HTML / CSS / JS template ----
# Two large placeholders kept distinct from JSON braces:
#   {{TOKEN}}  → replaced via str.replace
# CSS uses single { } so we don't use .format() at all.

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{TITLE}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0a0a0a; --bg-2:#141414;
    --ink:#f5f5f0; --ink-dim:#a0a0a0; --ink-faint:#888;
    --line:#262626;
    --a-color:#00d4ff; --a-glow:rgba(0,212,255,.35);
    --b-color:#ff3d00; --b-glow:rgba(255,61,0,.35);
    --loss:#00d4ff; --gain:#ff3d00; --neutral:#444;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{background:var(--bg);color:var(--ink);font-family:'Space Grotesk',sans-serif;font-weight:400;line-height:1.5}
  .mono{font-family:'JetBrains Mono',monospace;font-feature-settings:'tnum'}
  .page{max-width:1280px;margin:0 auto;padding:48px 32px 80px;position:relative}
  .page::before{
    content:'';position:fixed;inset:0;pointer-events:none;z-index:99;
    background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E");
    opacity:.05;mix-blend-mode:overlay
  }
  header{
    border-bottom:1px solid var(--line);
    padding-bottom:32px;margin-bottom:48px;
    display:grid;grid-template-columns:1fr auto;gap:32px;align-items:end
  }
  .eyebrow{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.2em;color:var(--ink-dim);text-transform:uppercase;margin-bottom:16px}
  h1{font-family:'Bebas Neue',sans-serif;font-size:clamp(36px,5vw,56px);line-height:.9;letter-spacing:.01em;background:linear-gradient(180deg,var(--ink) 0%,#888 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
  .subtitle{color:var(--ink-dim);font-size:14px;margin-top:12px;max-width:520px;line-height:1.6}
  .meta-grid{display:grid;grid-template-columns:repeat(2,auto);gap:4px 32px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);text-align:right}
  .meta-grid .k{color:var(--ink-faint)}
  .meta-grid .v{color:var(--ink)}
  .section-title{margin:64px 0 24px;display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--line);padding-bottom:12px}
  .section-title h2{font-family:'Bebas Neue',sans-serif;font-size:36px;letter-spacing:.02em;color:var(--ink)}
  .section-title .num{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ink-faint);letter-spacing:.15em}
  .map-wrap{background:var(--bg-2);border:1px solid var(--line);border-radius:2px;padding:24px;margin-bottom:24px;position:relative;overflow:hidden}
  .map-wrap::after{content:'{{VENUE_LABEL}}';position:absolute;bottom:16px;right:24px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.2em}
  .map-svg{width:100%;height:auto;display:block}
  .delta-wrap,.speed-wrap{background:var(--bg-2);border:1px solid var(--line);padding:24px;margin-bottom:24px;position:relative}
  .chart-svg{width:100%;height:auto;display:block;overflow:visible}
  .chart-label{font-family:'JetBrains Mono',monospace;font-size:10px;fill:var(--ink-faint);letter-spacing:.1em}
  .chart-tick{font-family:'JetBrains Mono',monospace;font-size:10px;fill:var(--ink-dim)}
  .legend{display:flex;gap:32px;align-items:center;margin-bottom:16px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);text-transform:uppercase;letter-spacing:.1em;flex-wrap:wrap}
  .legend-item{display:flex;align-items:center;gap:8px}
  .legend-swatch{width:20px;height:3px;display:inline-block}
  .zones{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:24px}
  .zone-card{background:var(--bg-2);border:1px solid var(--line);padding:24px;position:relative;overflow:hidden}
  .zone-card.loss{border-left:3px solid var(--loss)}
  .zone-card.gain{border-left:3px solid var(--gain)}
  .zone-card .header-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px}
  .zone-card .tag{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.2em;text-transform:uppercase}
  .zone-card.loss .tag{color:var(--loss)}
  .zone-card.gain .tag{color:var(--gain)}
  .zone-card .where{font-family:'Bebas Neue',sans-serif;font-size:36px;color:var(--ink)}
  .zone-card .desc{color:var(--ink-dim);font-size:13px;line-height:1.6;margin-top:12px}
  .zone-card .stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:16px;border-top:1px solid var(--line);padding-top:16px}
  .zone-card .stat .k{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.15em;text-transform:uppercase;margin-bottom:4px}
  .zone-card .stat .v{font-family:'JetBrains Mono',monospace;font-size:18px;color:var(--ink);font-weight:500}

  /* Interactive cursor system */
  .map-svg, .chart-svg{cursor:crosshair}
  .cursor-info{
    /* v21.4 — Sticky below the rd-header (~68px desktop / ~60px mobile),
       opaque background so content scrolling underneath doesn't bleed through.
       Same pattern as Datenviewer.cursor-info. */
    position:sticky; top:68px; z-index:50;
    background:#0a0a0a;
    border:1px solid var(--line); border-left:3px solid var(--ink);
    padding:14px 20px; margin-bottom:24px;
    font-family:'JetBrains Mono',monospace; color:var(--ink);
    display:flex; flex-wrap:wrap; gap:6px 28px; align-items:baseline;
  }
  @media (max-width:780px){.cursor-info{top:60px}}
  .cursor-info .cell{display:flex; flex-direction:column; gap:2px; min-width:60px}
  .cursor-info .k{font-size:10px; color:var(--ink-faint); letter-spacing:.15em; text-transform:uppercase}
  .cursor-info .v{font-size:15px; font-weight:500; font-feature-settings:'tnum'}
  .cursor-info .v.a{color:var(--a-color)}
  .cursor-info .v.b{color:var(--b-color)}
  .cursor-info .v.pos{color:var(--loss)}
  .cursor-info .v.neg{color:var(--gain)}
  .cursor-info .v.muted{color:var(--ink-dim)}
  /* v21.21 — Channel-Cells im Cursor-Info: dynamisch befüllt nach Auswahl
     im Multi-Channel-Chart. display:contents damit die Cells direkt in den
     Flex-Container der Box rutschen. */
  .cursor-info .ci-channels{display:contents}
  .cursor-info .cell.ch-pair{min-width:90px}
  .cursor-info .cell.ch-pair .ch-pair-vals{display:flex;flex-direction:column;gap:0;font-feature-settings:'tnum'}
  .cursor-info .cell.ch-pair .ch-pair-vals .va{font-size:14px;color:var(--a-color);font-weight:500}
  .cursor-info .cell.ch-pair .ch-pair-vals .vb{font-size:14px;color:var(--b-color);font-weight:500}
  .cursor-info .cell.ch-pair .ch-pair-vals .vmuted{color:var(--ink-faint)}
  .cursor-info .hint{
    width:100%; color:var(--ink-faint); font-size:10px;
    margin-top:4px; letter-spacing:.1em
  }

  footer{margin-top:80px;padding-top:32px;border-top:1px solid var(--line);color:var(--ink-faint);font-family:'JetBrains Mono',monospace;font-size:11px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:16px;letter-spacing:.05em}
  @media (max-width:768px){
    .page{padding:24px 16px 64px}
    .zones{grid-template-columns:1fr}
    header{grid-template-columns:1fr;gap:16px}
    .meta-grid{text-align:left}
  }

  /* v20.4 — Empty-mode (no data loaded) */
  .empty-placeholder{
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    min-height:280px;border:1px dashed var(--line);background:var(--bg-2);
    color:var(--ink-dim);font-family:'JetBrains Mono',monospace;font-size:13px;
    letter-spacing:.15em;text-transform:uppercase;gap:10px;padding:32px;
    margin-bottom:24px;
  }
  .empty-placeholder .ep-icon{font-size:40px;color:var(--ink-faint);
    font-family:'Bebas Neue',sans-serif}
  .empty-placeholder .ep-hint{font-size:10px;color:var(--ink-faint);letter-spacing:.1em}
  body.empty-mode .cursor-info{opacity:.35}
  body.empty-mode header .meta-grid{opacity:.5}
  body.empty-mode .legend{opacity:.4}
  /* v21.20 — Toolbar im Empty-Mode ausgrauen (sonst hängt der "Kanäle wählen"-
     Button irreführend aktiv über dem leeren Placeholder). */
  body.empty-mode .chart-toolbar{opacity:.4;pointer-events:none}

  /* v21.19 — Multi-Channel-Chart (Sektion 04): Toolbar + Modal + Trace-Stack */
  .chart-toolbar{display:flex;align-items:center;gap:16px;margin:0 0 8px;flex-wrap:wrap}
  .chart-btn{
    font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.15em;
    background:var(--bg-2);border:1px solid var(--line);color:var(--ink);
    padding:7px 12px;cursor:pointer;text-transform:uppercase;
  }
  .chart-btn:hover{border-color:var(--a-color);color:var(--a-color)}
  .chart-btn.primary{background:var(--a-color);color:#000;border-color:var(--a-color)}
  .chart-btn.primary:hover{background:#33dbff;color:#000}
  .chart-btn.ghost{background:transparent}
  .chart-btn.accent{background:var(--a-color);color:#000;border-color:var(--a-color);font-weight:600}
  .chart-btn.accent:hover{background:#33dbff;color:#000}
  .chart-btn .badge{
    display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;
    background:#000;color:var(--a-color);font-size:10px;font-weight:600;
  }
  .chart-legend{
    display:flex;gap:14px;flex-wrap:wrap;
    font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.1em;
    color:var(--ink-dim);text-transform:uppercase;
  }
  .chart-legend .lg{display:inline-flex;gap:6px;align-items:center}
  .chart-legend .swatch{display:inline-block;width:18px;height:0;border-top-width:2px;border-top-style:solid;align-self:center}
  .chart-hint{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.08em;color:var(--ink-dim);text-transform:uppercase}
  /* v21.22 — Segmented Toggle für Trackmap-Modus (FARBKANAL | FAHRLINIE) */
  /* v21.25 — seg-switch landet links, Mapview-Toggle rechts via margin-left:auto */
  .seg-switch{display:inline-flex;border:1px solid var(--line);background:var(--bg-2)}
  .chart-toolbar .tm-bg-btn{margin-left:auto}
  .seg-switch .seg-opt{
    font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.15em;
    background:transparent;border:0;color:var(--ink-dim);
    padding:7px 14px;cursor:pointer;text-transform:uppercase;
  }
  .seg-switch .seg-opt:hover{color:var(--ink)}
  .seg-switch .seg-opt.active{background:var(--a-color);color:#000;font-weight:600}
  /* v21.23 — Attribution für Tile-Provider (Esri etc.), bottom-right der Trackmap */
  .map-attribution{
    position:absolute;bottom:6px;right:10px;
    font-family:'JetBrains Mono',monospace;font-size:9px;
    color:rgba(245,245,240,.7);background:rgba(0,0,0,.4);
    padding:2px 6px;border-radius:2px;letter-spacing:.05em;
    pointer-events:auto;z-index:2;
  }
  .map-attribution a{color:inherit;text-decoration:none;border-bottom:1px dotted rgba(245,245,240,.5)}
  .map-attribution a:hover{color:var(--a-color)}
  .extras-wrap{margin-bottom:24px}

  .modal-back{
    position:fixed;inset:0;background:rgba(0,0,0,.72);
    z-index:1000;display:flex;align-items:center;justify-content:center;
    padding:24px;
  }
  .modal-back[hidden]{display:none}
  .modal{
    background:var(--bg-2);border:1px solid var(--line);
    width:100%;max-width:820px;max-height:80vh;display:flex;flex-direction:column;
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
  .modal-toolbar input:focus{border-color:var(--a-color)}
  .modal-hint{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.1em}
  .modal-body{flex:1 1 auto;overflow:auto;padding:0 24px}
  .modal-foot{display:flex;gap:8px;padding:14px 24px;border-top:1px solid var(--line);justify-content:flex-end}

  .ch-table-head, .ch-row{
    display:grid;
    /* A-Checkbox · NAME · B-Checkbox */
    grid-template-columns: 80px minmax(0,1fr) 80px;
    gap:10px;align-items:center;
  }
  .ch-table-head{
    padding:12px 0;border-bottom:1px solid var(--line);
    font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-faint);letter-spacing:.15em;
    position:sticky;top:0;background:var(--bg-2);
  }
  .ch-table-head .ch-col-a{text-align:center;color:var(--a-color)}
  .ch-table-head .ch-col-b{text-align:center;color:var(--b-color)}
  .ch-row{padding:10px 0;border-bottom:1px solid #1a1a1a}
  .ch-row:hover{background:#181818}
  .ch-row .ch-col-a, .ch-row .ch-col-b{
    display:flex;justify-content:center;align-items:center;
  }
  .ch-row .ch-col-a input, .ch-row .ch-col-b input{
    width:18px;height:18px;cursor:pointer;
  }
  .ch-row .ch-col-a input{accent-color:var(--a-color)}
  .ch-row .ch-col-b input{accent-color:var(--b-color)}
  .ch-row .ch-col-a.dim, .ch-row .ch-col-b.dim{opacity:0.18}
  .ch-row .ch-col-name{
    font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--ink);
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  }
  .ch-row .ch-col-name .swatch{
    display:inline-block;width:10px;height:10px;border-radius:2px;
    margin-right:8px;vertical-align:middle;
  }
  .ch-empty{padding:40px 0;text-align:center;color:var(--ink-faint);font-family:'JetBrains Mono',monospace;font-size:11px}
  .chart-tick{font-family:'JetBrains Mono',monospace;font-size:10px;fill:var(--ink-faint);letter-spacing:.05em}
  .chart-label{font-family:'JetBrains Mono',monospace;font-size:10px;fill:var(--ink-dim);letter-spacing:.1em}
  .extras-empty{
    background:var(--bg-2);border:1px dashed var(--line);
    padding:36px 20px;text-align:center;color:var(--ink-dim);
    font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em;text-transform:uppercase;
  }
  {{TILE_SPINNER_CSS}}
</style>
</head>
<body>
<div class="page">
  <header>
    <div>
      <div class="eyebrow">Telemetry · Race-data forensics</div>
      <h1>WHERE THE<br>SECONDS GO</h1>
      <p class="subtitle">
        Distanz-synchronisierter Vergleich der jeweils schnellsten Runde aus
        zwei Datenloggern. Rote Sektoren — A gewinnt dort Zeit, cyan-farbene
        Sektoren — B gewinnt dort Zeit.
      </p>
    </div>
    <div class="meta-grid">
      <span class="k">VENUE</span><span class="v">{{VENUE}}</span>
      <span class="k">FILE A</span><span class="v">{{A_FILE}}</span>
      <span class="k">FILE B</span><span class="v">{{B_FILE}}</span>
      <span class="k">REFERENCE</span><span class="v">DISTANCE-ALIGNED</span>
    </div>
  </header>

  <div class="cursor-info" id="cursor-info">
    <div class="cell"><div class="k">Position</div><div class="v" id="ci-dist">—</div></div>
    <div class="cell"><div class="k">Δ-T</div><div class="v" id="ci-delta">—</div></div>
    <div class="cell"><div class="k">Speed A</div><div class="v a" id="ci-sa">—</div></div>
    <div class="cell"><div class="k">Speed B</div><div class="v b" id="ci-sb">—</div></div>
    <div class="cell"><div class="k">Δ Speed</div><div class="v" id="ci-ds">—</div></div>
    <div class="cell"><div class="k">Time A</div><div class="v a" id="ci-ta">—</div></div>
    <div class="cell"><div class="k">Time B</div><div class="v b" id="ci-tb">—</div></div>
    <!-- v21.21 — Dynamische Cells für aktive Kanäle aus dem Multi-Channel-Chart -->
    <div class="ci-channels" id="ci-channels"></div>
    <div class="hint" id="ci-hint">Hover über Map/Chart → Werte an der Cursor-Position · Klick: Marker fest · ESC: lösen</div>
  </div>

  <div class="section-title">
    <h2>01 · STRECKE & ZEITGEWINN</h2>
    <span class="num">N=500 SAMPLES</span>
  </div>
  <!-- v21.22 — Trackmap-Modus-Schalter: Farbkanal (zeitgewinn-codiert) vs Fahrlinie (zwei dünne Linien in A/B-Farben) -->
  <!-- v21.23 — MAPVIEW-Toggle: blendet Satelliten-Hintergrund (Esri World Imagery) ein/aus -->
  <!-- v21.25 — MAPVIEW jetzt single button (vorher zweiteiliger seg-switch) -->
  <div class="chart-toolbar" id="tm-toolbar">
    <div class="seg-switch" role="tablist" aria-label="Trackmap-Modus">
      <button type="button" class="seg-opt active" id="tm-mode-color" role="tab" aria-selected="true">FARBKANAL</button>
      <button type="button" class="seg-opt" id="tm-mode-line" role="tab" aria-selected="false">FAHRLINIE</button>
    </div>
    <button type="button" class="tm-bg-btn {{TM_BG_BTN_CLS}}" id="tm-bg-toggle" aria-pressed="false">
      <span class="tm-bg-dot"></span>MAPVIEW
    </button>
  </div>
  <div class="map-wrap">
    <div class="legend" id="tm-legend">
      <div class="legend-item"><span class="legend-swatch" style="background:var(--loss)"></span>A GEWINNT ZEIT</div>
      <div class="legend-item"><span class="legend-swatch" style="background:var(--neutral)"></span>NEUTRAL</div>
      <div class="legend-item"><span class="legend-swatch" style="background:var(--gain)"></span>B GEWINNT ZEIT</div>
    </div>
    <svg class="map-svg" id="track-map" viewBox="0 0 1200 600" preserveAspectRatio="xMidYMid meet"></svg>
    <!-- v21.23 — Esri-Attribution (nur sichtbar wenn Mapview aktiv) -->
    <!-- v21.26 — Attribution wird zur Laufzeit vom Tile-Provider-Script gefüllt -->
    <div class="map-attribution" id="tm-attribution" style="display:none"></div>
  </div>

  <div class="section-title">
    <h2>02 · DELTA-T ÜBER DIE RUNDE</h2>
    <span class="num">B − A (S)</span>
  </div>
  <div class="delta-wrap">
    <div class="legend">
      <div class="legend-item">↑ HÖHER = A GEWINNT MEHR ZEIT</div>
      <div class="legend-item">↓ NIEDRIGER = B GEWINNT MEHR ZEIT</div>
    </div>
    <svg class="chart-svg" id="delta-chart" viewBox="0 0 1200 520" preserveAspectRatio="none"></svg>
  </div>

  <div class="section-title">
    <h2>03 · GESCHWINDIGKEITSPROFIL</h2>
    <span class="num">KM/H · DISTANZ</span>
  </div>
  <div class="speed-wrap">
    <div class="legend">
      <div class="legend-item"><span class="legend-swatch" style="background:var(--a-color)"></span>A</div>
      <div class="legend-item"><span class="legend-swatch" style="background:var(--b-color)"></span>B</div>
    </div>
    <svg class="chart-svg" id="speed-chart" viewBox="0 0 1200 480" preserveAspectRatio="none"></svg>
  </div>

  <!-- v21.19 — Multi-Channel-Chart über alle Telemetrie-Kanäle beider Runden.
       Linien-Stil: A = solid, B = gestrichelt. Jeder Trace bekommt eine
       eigene Y-Achse (gestackt links/rechts), Distanz teilen sich alle. -->
  <div class="section-title">
    <h2>04 · KANÄLE</h2>
    <span class="num">A=SOLID · B=DASHED · BEIDE RUNDEN</span>
  </div>
  <div class="chart-toolbar" id="ext-toolbar">
    <button type="button" id="ext-pick-btn" class="chart-btn accent">+ KANÄLE WÄHLEN <span id="ext-pick-count"></span></button>
    <div class="chart-legend" id="ext-legend"></div>
    <span class="chart-hint">A = durchgängig · B = gestrichelt</span>
  </div>
  <div class="extras-wrap">
    <svg class="chart-svg" id="extras-chart" viewBox="0 0 1200 480" preserveAspectRatio="none"></svg>
  </div>

  <!-- Channel-Picker-Modal -->
  <div class="modal-back" id="ext-modal" hidden>
    <div class="modal" role="dialog" aria-labelledby="ext-modal-title">
      <div class="modal-head">
        <h3 id="ext-modal-title">KANÄLE WÄHLEN</h3>
        <button type="button" class="modal-close" id="ext-modal-close" aria-label="Schließen">×</button>
      </div>
      <div class="modal-toolbar">
        <input type="text" id="ext-search" placeholder="Kanäle durchsuchen…">
        <span class="modal-hint" id="ext-modal-hint"></span>
      </div>
      <div class="modal-body">
        <div class="ch-table-head">
          <div class="ch-col-a">A</div>
          <div class="ch-col-name">NAME</div>
          <div class="ch-col-b">B</div>
        </div>
        <div class="ch-table-body" id="ext-table-body"></div>
      </div>
      <div class="modal-foot">
        <button type="button" class="chart-btn ghost" id="ext-clear">Alle aus</button>
        <button type="button" class="chart-btn primary" id="ext-apply">Übernehmen</button>
      </div>
    </div>
  </div>

  <div class="section-title">
    <h2>05 · WO DIE ZEIT FLIESST</h2>
    <span class="num">{{WIN_M}} M GLEITFENSTER</span>
  </div>
  <div class="zones">
    <div class="zone-card loss">
      <div class="header-row">
        <span class="tag">↑ GRÖSSTER ZEITGEWINN A</span>
        <span class="mono" style="color:var(--ink-dim);font-size:11px">@ {{LOSS_DIST}} M</span>
      </div>
      <div class="where">SEKTOR · A SCHNELLER</div>
      <div class="desc">
        Auf einem {{WIN_M}} m Fenster bei ca. {{LOSS_DIST}} m Renndistanz
        gewinnt Lap A rund
        <strong style="color:var(--ink)">{{LOSS_MS}} ms</strong> auf Lap B.
      </div>
      <div class="stats">
        <div class="stat"><div class="k">A GEWINNT</div><div class="v" style="color:var(--loss)">+{{LOSS_MS}} MS</div></div>
        <div class="stat"><div class="k">V A</div><div class="v">{{LOSS_VA}} KM/H</div></div>
        <div class="stat"><div class="k">V B</div><div class="v">{{LOSS_VB}} KM/H</div></div>
      </div>
    </div>
    <div class="zone-card gain">
      <div class="header-row">
        <span class="tag">↓ GRÖSSTER ZEITGEWINN B</span>
        <span class="mono" style="color:var(--ink-dim);font-size:11px">@ {{GAIN_DIST}} M</span>
      </div>
      <div class="where">SEKTOR · B SCHNELLER</div>
      <div class="desc">
        Auf einem {{WIN_M}} m Fenster bei ca. {{GAIN_DIST}} m gewinnt Lap B
        rund <strong style="color:var(--ink)">{{GAIN_MS}} ms</strong> auf Lap A.
      </div>
      <div class="stats">
        <div class="stat"><div class="k">B GEWINNT</div><div class="v" style="color:var(--gain)">−{{GAIN_MS}} MS</div></div>
        <div class="stat"><div class="k">V A</div><div class="v">{{GAIN_VA}} KM/H</div></div>
        <div class="stat"><div class="k">V B</div><div class="v">{{GAIN_VB}} KM/H</div></div>
      </div>
    </div>
  </div>

  {{THEO_BLOCK}}

  <footer>
    <span>{{A_FORMAT}} ↔ {{B_FORMAT}} · DISTANCE-ALIGNED</span>
    <span>WINDOW {{WIN_M}} M</span>
    <span>Δ TOTAL · {{DELTA_SIGN}}{{DELTA}} S</span>
  </footer>
</div>

<script>
const DATA = {{DATA_JSON}};

{{TILE_PROVIDER_JS}}

{{TILE_HELPERS_JS}}

// ============================================================================
// v20.4 — Empty-mode bail-out. When no data is loaded (one or both slots
// empty), swap out the chart/map containers for placeholder hints and
// stop the rest of the script before it touches DATA.*. The picker modal
// is wired up by the trailing IIFE that's injected outside this template.
// ============================================================================
if (DATA === null){
  document.body.classList.add('empty-mode');

  // Replace chart/map containers with placeholders
  const swap = (id, label) => {
    const el = document.getElementById(id);
    if (!el) return;
    const ph = document.createElement('div');
    ph.className = 'empty-placeholder';
    ph.innerHTML = '<div class="ep-icon">∅</div>'
                 + '<div>' + label + '</div>'
                 + '<div class="ep-hint">→ KLICK „RUNDE WÄHLEN“ OBEN</div>';
    el.parentNode.replaceChild(ph, el);
  };
  swap('track-map',    'BITTE ZWEI RUNDEN SELEKTIEREN');
  swap('delta-chart',  'KEIN VERGLEICH MÖGLICH');
  swap('speed-chart',  'KEIN VERGLEICH MÖGLICH');
  swap('extras-chart', 'KEIN VERGLEICH MÖGLICH');

  // Stop here — the rest of the script touches DATA.* and would crash.
  // (Browser logs "Uncaught EmptyMode" once. Harmless.)
  throw new Error('EmptyMode');
}

// ============================================================================
// Shared cursor state
// ============================================================================
const cursorInfo = document.getElementById('cursor-info');
const ciDist  = document.getElementById('ci-dist');
const ciDelta = document.getElementById('ci-delta');
const ciSa    = document.getElementById('ci-sa');
const ciSb    = document.getElementById('ci-sb');
const ciDs    = document.getElementById('ci-ds');
const ciTa    = document.getElementById('ci-ta');
const ciTb    = document.getElementById('ci-tb');
const ciHint  = document.getElementById('ci-hint');

let currentIdx = -1;     // currently displayed sample index, -1 = none
let stickyIdx = -1;      // index from last click; -1 if not sticky

function fmtTime(s){
  if (s == null || !isFinite(s)) return '—';
  const m = Math.floor(s / 60);
  const sec = s - m*60;
  return `${m}:${sec.toFixed(2).padStart(5,'0')}`;
}

// Lap-summary caches
let _meanA = null, _meanB = null;
function lapMeanA(){
  if (_meanA != null) return _meanA;
  let s = 0, n = 0;
  for (let i = 0; i < DATA.a_speed.length; i++){
    const v = DATA.a_speed[i];
    if (isFinite(v)){ s += v; n++; }
  }
  _meanA = n ? s/n : 0;
  return _meanA;
}
function lapMeanB(){
  if (_meanB != null) return _meanB;
  let s = 0, n = 0;
  for (let i = 0; i < DATA.b_speed.length; i++){
    const v = DATA.b_speed[i];
    if (isFinite(v)){ s += v; n++; }
  }
  _meanB = n ? s/n : 0;
  return _meanB;
}

function updateInfoBox(idx){
  if (idx < 0 || idx >= DATA.distance.length){
    // No cursor — show LAP SUMMARY (final values / means)
    const distMax = DATA.distance[DATA.distance.length-1];
    const finalDelta = DATA.delta[DATA.delta.length-1];
    const tA = DATA.a_time[DATA.a_time.length-1];
    const tB = DATA.b_time[DATA.b_time.length-1];
    const mA = lapMeanA(), mB = lapMeanB();
    const dsMean = mB - mA;

    ciDist.textContent = `${(distMax/1000).toFixed(3)} km`;
    ciDist.className = 'v muted';

    ciDelta.textContent = `${finalDelta>=0?'+':''}${finalDelta.toFixed(3)} s`;
    ciDelta.className = 'v ' + (finalDelta > 0.005 ? 'pos' : (finalDelta < -0.005 ? 'neg' : 'muted'));

    ciSa.textContent = `Ø ${mA.toFixed(1)} km/h`;
    ciSa.className = 'v a';
    ciSb.textContent = `Ø ${mB.toFixed(1)} km/h`;
    ciSb.className = 'v b';

    ciDs.textContent = `${dsMean>=0?'+':''}${dsMean.toFixed(1)} km/h`;
    ciDs.className = 'v ' + (dsMean > 0.5 ? 'b' : (dsMean < -0.5 ? 'a' : 'muted'));

    ciTa.textContent = fmtTime(tA);
    ciTa.className = 'v a';
    ciTb.textContent = fmtTime(tB);
    ciTb.className = 'v b';

    // v21.21 — Channel-Cells: ohne Cursor zeigen wir nichts (kein Mittelwert für Channels)
    renderChannelCells(-1);

    if (ciHint) ciHint.textContent =
      'RUNDE GESAMT · Δ-T = FINAL · Ø-SPEEDS · Hover für Cursor-Werte';
    return;
  }

  // Cursor active — values at the current position
  const d = DATA.distance[idx];
  const dt = DATA.delta[idx];
  const sa = DATA.a_speed[idx], sb = DATA.b_speed[idx];
  const ta = DATA.a_time[idx],  tb = DATA.b_time[idx];
  ciDist.textContent  = `${(d/1000).toFixed(3)} km`;
  ciDist.className    = 'v';
  ciDelta.textContent = `${dt>=0?'+':''}${dt.toFixed(3)} s`;
  ciDelta.className   = 'v ' + (dt > 0.005 ? 'pos' : (dt < -0.005 ? 'neg' : ''));
  ciSa.textContent    = `${sa.toFixed(1)} km/h`;
  ciSa.className      = 'v a';
  ciSb.textContent    = `${sb.toFixed(1)} km/h`;
  ciSb.className      = 'v b';
  const ds = sb - sa;
  ciDs.textContent    = `${ds>=0?'+':''}${ds.toFixed(1)} km/h`;
  ciDs.className      = 'v ' + (ds > 0.5 ? 'b' : (ds < -0.5 ? 'a' : ''));
  ciTa.textContent    = fmtTime(ta);
  ciTa.className      = 'v a';
  ciTb.textContent    = fmtTime(tb);
  ciTb.className      = 'v b';

  // v21.21 — Channel-Cells aus dem Multi-Channel-Chart
  renderChannelCells(idx);

  if (ciHint){
    ciHint.textContent = (stickyIdx >= 0)
      ? 'MARKER FEST · ESC oder erneut klicken → lösen'
      : 'CURSOR-POSITION · Klick: Marker fest setzen';
  }
}

// v21.21 — Channel-Cells in die Cursor-Info-Box einfügen.
// Liest die aktive Auswahl aus extrasChart.getCellsAt(idx) und rendert
// pro Channel-Name eine Cell mit A- und B-Wert.
function renderChannelCells(idx){
  const host = document.getElementById('ci-channels');
  if (!host) return;
  if (typeof extrasChart === 'undefined' || !extrasChart ||
      typeof extrasChart.getCellsAt !== 'function'){
    host.innerHTML = ''; return;
  }
  const cells = extrasChart.getCellsAt(idx);
  if (cells.length === 0){ host.innerHTML = ''; return; }
  host.innerHTML = cells.map(c => {
    const u = c.unit ? ` ${escapeForHtml(c.unit)}` : '';
    const a = c.hasA
      ? `<span class="va">${c.aVal != null ? c.aVal + u : '—'}</span>`
      : `<span class="va vmuted">—</span>`;
    const b = c.hasB
      ? `<span class="vb">${c.bVal != null ? c.bVal + u : '—'}</span>`
      : `<span class="vb vmuted">—</span>`;
    return `<div class="cell ch-pair">
      <div class="k" style="color:${c.color}">${escapeForHtml(c.name)}</div>
      <div class="ch-pair-vals">${a}${b}</div>
    </div>`;
  }).join('');
}

// Minimaler HTML-Escape für die Channel-Namen (kommen aus User-Daten).
function escapeForHtml(s){
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setCursor(idx, sticky){
  if (sticky === true) stickyIdx = idx;
  if (sticky === false) stickyIdx = -1;
  currentIdx = idx;
  updateInfoBox(idx);
  trackMap.drawCursor(idx);
  deltaChart.drawCursor(idx);
  speedChart.drawCursor(idx);
  // v21.19 — extrasChart wird später im Script-Block definiert; guard für Ladephase
  if (typeof extrasChart !== 'undefined' && extrasChart) extrasChart.drawCursor(idx);
}

function clearLiveCursor(){
  // Restore to sticky if any, otherwise hide
  if (stickyIdx >= 0) {
    setCursor(stickyIdx, undefined);
  } else {
    currentIdx = -1;
    updateInfoBox(-1);
    trackMap.drawCursor(-1);
    deltaChart.drawCursor(-1);
    speedChart.drawCursor(-1);
    if (typeof extrasChart !== 'undefined' && extrasChart) extrasChart.drawCursor(-1);
  }
}

// Convert a click/move event on an SVG into the viewBox X coordinate
function eventToSvgX(svg, evt){
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX; pt.y = evt.clientY;
  const ctm = svg.getScreenCTM();
  if (!ctm) return null;
  return pt.matrixTransform(ctm.inverse()).x;
}

// ESC key clears sticky
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && stickyIdx >= 0){
    stickyIdx = -1;
    clearLiveCursor();
  }
});

// ============================================================================
// Track Map
// ============================================================================
const trackMap = (function(){
  const svg = document.getElementById('track-map');
  const W = 1200, H = 600;
  const PAD = 40;

  const allLat = DATA.b_lat.concat(DATA.a_lat);
  const allLon = DATA.b_lon.concat(DATA.a_lon);
  const latMin = Math.min(...allLat), latMax = Math.max(...allLat);
  const lonMin = Math.min(...allLon), lonMax = Math.max(...allLon);
  const latRange = latMax - latMin, lonRange = lonMax - lonMin;
  const cosLat = Math.cos((latMin+latMax)/2 * Math.PI/180);

  // Equal-meters-per-pixel mapping (Mercator: lon_per_pixel = lat_per_pixel * cos(lat))
  const wMeters = lonRange * 111000 * cosLat;
  const hMeters = latRange * 111000;
  const aspectMap = hMeters > 0 ? wMeters / hMeters : 1;
  const aspectViewport = (W - 2*PAD) / (H - 2*PAD);
  let scaleX, scaleY, ox, oy;
  if (aspectMap > aspectViewport){
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
  const proj = (lat, lon) => ({
    x: ox + (lon - lonMin) * scaleX,
    y: oy + (latMax - lat) * scaleY
  });

  const N = DATA.distance.length;
  const win = Math.round(N / 20);
  const gains = new Array(N).fill(0);
  for (let i = win; i < N; i++) gains[i] = DATA.delta[i] - DATA.delta[i-win];
  const maxAbs = Math.max(...gains.map(Math.abs)) || 1;

  function colorAt(g){
    const t = g / maxAbs;
    if (t > 0.05){
      // A gewinnt → cyan
      const a = Math.min(1, t * 1.5);
      return `rgba(0, ${Math.round(212 - 30*a)}, 255, ${0.4 + 0.6*a})`;
    } else if (t < -0.05){
      // B gewinnt → rot
      const a = Math.min(1, -t * 1.5);
      return `rgba(255, ${Math.round(61 - 50*a)}, 0, ${0.4 + 0.6*a})`;
    }
    return 'rgba(80, 80, 80, 0.5)';
  }

  // Build base (static) content
  // v21.22 — Zwei Render-Modi: 'color' (Farbkanal, dicke B-Linie + dünne A-Strichlinie)
  //          und 'line' (Fahrlinie, beide Runden als dünne Linien in A/B-Farben).
  // v21.23 — Optional: Satelliten-Hintergrund via Esri World Imagery (mapview).
  // v21.24 — Tile-Helfer + Spinner + Zoom/Pan kommen aus der zentralen Helper-Lib.
  let mode = 'color';

  const tile = makeTileLayer({
    svg, W, H, proj,
    latMin, latMax, lonMin, lonMax,
    padding: 0.10,
  });

  function buildColorMode(){
    let html = '';
    let aPath = '';
    for (let i = 0; i < N; i++){
      const p = proj(DATA.a_lat[i], DATA.a_lon[i]);
      aPath += (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
    }
    html += `<path d="${aPath}Z" fill="none" stroke="#333" stroke-width="1" stroke-dasharray="2,3" opacity="0.5"/>`;
    for (let i = 1; i < N; i++){
      const p1 = proj(DATA.b_lat[i-1], DATA.b_lon[i-1]);
      const p2 = proj(DATA.b_lat[i], DATA.b_lon[i]);
      html += `<line x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${p2.x.toFixed(1)}" y2="${p2.y.toFixed(1)}" stroke="${colorAt(gains[i])}" stroke-width="6" stroke-linecap="round"/>`;
    }
    return html;
  }

  function buildLineMode(){
    // Beide Runden als dünne Linien in der jeweiligen Rundenfarbe.
    // Strichstärke 2.5px wie die Coach-Hintergrundlinie.
    let aPath = '', bPath = '';
    for (let i = 0; i < N; i++){
      const pA = proj(DATA.a_lat[i], DATA.a_lon[i]);
      aPath += (i === 0 ? 'M' : 'L') + pA.x.toFixed(1) + ',' + pA.y.toFixed(1);
      const pB = proj(DATA.b_lat[i], DATA.b_lon[i]);
      bPath += (i === 0 ? 'M' : 'L') + pB.x.toFixed(1) + ',' + pB.y.toFixed(1);
    }
    return `<path d="${aPath}" fill="none" stroke="var(--a-color)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`
         + `<path d="${bPath}" fill="none" stroke="var(--b-color)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
  }

  // mapWrap ist .map-wrap, der Container der Spinner aufnimmt.
  const mapWrap = svg.parentElement;

  function render(){
    let html = '';
    if (tile.active) html += tile.buildLayer();
    html += (mode === 'line') ? buildLineMode() : buildColorMode();
    // v21.21 — Start/Finish-Marker bleibt in beiden Modi.
    if (DATA.finish_line){
      const fl = proj(DATA.finish_line[0], DATA.finish_line[1]);
      html += `<g>
        <circle cx="${fl.x}" cy="${fl.y}" r="8" fill="none" stroke="#fff" stroke-width="2"/>
        <circle cx="${fl.x}" cy="${fl.y}" r="3" fill="#fff"/>
        <text x="${fl.x+14}" y="${fl.y+4}" font-family="JetBrains Mono" font-size="11" fill="#fff" letter-spacing="1">START / FINISH</text>
      </g>`;
    }
    // Reserve a group for the cursor overlay
    html += `<g id="track-cursor"></g>`;
    svg.innerHTML = html;
    cursorG = document.getElementById('track-cursor');
    // v21.24 — Spinner während Tile-Load
    if (tile.active) tile.bindLoadEvents(mapWrap);
    else tile.hideSpinner();
  }
  let cursorG = null;
  render();

  let lastIdx = -1;
  function drawCursor(idx){
    lastIdx = idx;
    if (!cursorG) return;
    if (idx < 0 || idx >= N){ cursorG.innerHTML = ''; return; }
    const pA = proj(DATA.a_lat[idx], DATA.a_lon[idx]);
    const pB = proj(DATA.b_lat[idx], DATA.b_lon[idx]);
    cursorG.innerHTML = `
      <line x1="${pA.x.toFixed(1)}" y1="${pA.y.toFixed(1)}" x2="${pB.x.toFixed(1)}" y2="${pB.y.toFixed(1)}" stroke="#fff" stroke-width="1" opacity="0.4"/>
      <circle cx="${pA.x.toFixed(1)}" cy="${pA.y.toFixed(1)}" r="6" fill="none" stroke="#00d4ff" stroke-width="2"/>
      <circle cx="${pA.x.toFixed(1)}" cy="${pA.y.toFixed(1)}" r="2" fill="#00d4ff"/>
      <circle cx="${pB.x.toFixed(1)}" cy="${pB.y.toFixed(1)}" r="6" fill="none" stroke="#ff3d00" stroke-width="2"/>
      <circle cx="${pB.x.toFixed(1)}" cy="${pB.y.toFixed(1)}" r="2" fill="#ff3d00"/>
    `;
  }

  function setMode(newMode){
    if (newMode !== 'color' && newMode !== 'line') return;
    if (newMode === mode) return;
    mode = newMode;
    render();
    // Cursor nach Re-Render wiederherstellen
    if (lastIdx >= 0) drawCursor(lastIdx);
  }

  function setMapview(on){
    on = !!on;
    if (on === tile.active) return;
    tile.active = on;
    render();
    if (lastIdx >= 0) drawCursor(lastIdx);
  }

  // Hit-test: nearest B-track point to (svgX, svgY)
  function findIndexFromEvent(evt){
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return -1;
    const local = pt.matrixTransform(ctm.inverse());
    let bestI = -1, bestD = 1e18;
    for (let i = 0; i < N; i++){
      const p = proj(DATA.b_lat[i], DATA.b_lon[i]);
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
    // v21.24 — Klick nach einem Pan-Drag nicht als Cursor-Set werten.
    if (zoomCtl && zoomCtl.didDrag()) return;
    const i = findIndexFromEvent(e);
    if (i < 0) return;
    if (stickyIdx === i){
      // Clicking the same point unsets sticky
      setCursor(-1, false);
    } else {
      setCursor(i, true);
    }
  });

  // v21.24 — Zoom/Pan (Mausrad + Pinch + Drag). Doppelklick resettet.
  const zoomCtl = makeZoomPan({ svg, W, H, minZoom: 1, maxZoom: 8 });

  return { drawCursor, setMode, setMapview };
})();

// v21.22 — Trackmap-Modus-Toggle (FARBKANAL | FAHRLINIE)
// v21.23 — Mapview-Toggle (Esri World Imagery Satellit ein/aus)
// v21.25 — Single-Button-Toggle (vorher: zwei-Optionen seg-switch)
(function(){
  const btnColor = document.getElementById('tm-mode-color');
  const btnLine  = document.getElementById('tm-mode-line');
  const legend   = document.getElementById('tm-legend');
  const btnBg    = document.getElementById('tm-bg-toggle');
  if (!btnColor || !btnLine) return;
  function applyMode(modeName){
    trackMap.setMode(modeName);
    const isColor = (modeName === 'color');
    btnColor.classList.toggle('active', isColor);
    btnColor.setAttribute('aria-selected', isColor ? 'true' : 'false');
    btnLine.classList.toggle('active', !isColor);
    btnLine.setAttribute('aria-selected', !isColor ? 'true' : 'false');
    // Legende (A GEWINNT / NEUTRAL / B GEWINNT) gehört zum Farbkanal-Modus.
    if (legend) legend.style.display = isColor ? '' : 'none';
  }
  function applyBg(on){
    trackMap.setMapview(on);
    if (btnBg){
      btnBg.classList.toggle('active', on);
      btnBg.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    // Attribution erscheint nur wenn Mapview aktiv.
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
// Delta chart
// ============================================================================
const deltaChart = (function(){
  const svg = document.getElementById('delta-chart');
  const W = 1200, H = 520;
  const M = {top: 24, right: 24, bottom: 36, left: 56};
  const w = W - M.left - M.right, h = H - M.top - M.bottom;
  const distMax = DATA.distance[DATA.distance.length-1];
  const dMin = Math.min(...DATA.delta), dMax = Math.max(...DATA.delta);
  const range = dMax - dMin || 1;
  const yMin = dMin - range*0.1, yMax = dMax + range*0.1;
  const xS = d => M.left + (d / distMax) * w;
  const yS = v => M.top + (1 - (v - yMin)/(yMax - yMin)) * h;

  let path = '';
  for (let i = 0; i < DATA.distance.length; i++){
    path += (i===0?'M':'L') + xS(DATA.distance[i]).toFixed(1) + ',' + yS(DATA.delta[i]).toFixed(1);
  }
  const yZero = yS(0);
  let posArea = '';
  for (let i = 0; i < DATA.distance.length; i++){
    posArea += (i===0?'M':'L') + xS(DATA.distance[i]).toFixed(1) + ',' + yS(Math.max(0, DATA.delta[i])).toFixed(1);
  }
  posArea += `L${xS(distMax).toFixed(1)},${yZero.toFixed(1)} L${xS(0).toFixed(1)},${yZero.toFixed(1)} Z`;

  let negArea = '';
  for (let i = 0; i < DATA.distance.length; i++){
    negArea += (i===0?'M':'L') + xS(DATA.distance[i]).toFixed(1) + ',' + yS(Math.min(0, DATA.delta[i])).toFixed(1);
  }
  negArea += `L${xS(distMax).toFixed(1)},${yZero.toFixed(1)} L${xS(0).toFixed(1)},${yZero.toFixed(1)} Z`;

  let yTicks = '';
  const yStep = Math.max(0.1, Math.round(range / 5 * 10) / 10);
  for (let v = Math.ceil(yMin/yStep)*yStep; v <= yMax; v += yStep){
    const y = yS(v);
    yTicks += `<line x1="${M.left}" y1="${y}" x2="${M.left+w}" y2="${y}" stroke="#1a1a1a" stroke-width="1"/>`;
    yTicks += `<text x="${M.left-8}" y="${y+3}" class="chart-tick" text-anchor="end">${v>=0?'+':''}${v.toFixed(1)}s</text>`;
  }
  let xTicks = '';
  for (let d = 0; d <= distMax; d += 1000){
    const x = xS(d);
    xTicks += `<line x1="${x}" y1="${M.top}" x2="${x}" y2="${M.top+h}" stroke="#1a1a1a" stroke-width="1"/>`;
    xTicks += `<text x="${x}" y="${M.top+h+18}" class="chart-tick" text-anchor="middle">${(d/1000).toFixed(1)} km</text>`;
  }

  const x_loss = xS(DATA.loss_dist), x_gain = xS(DATA.gain_dist);
  const x_finish = xS(DATA.lap_distance_m || distMax);
  svg.innerHTML = `
    <defs>
      <linearGradient id="lossGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#00d4ff" stop-opacity="0.4"/>
        <stop offset="100%" stop-color="#00d4ff" stop-opacity="0"/>
      </linearGradient>
      <linearGradient id="gainGrad" x1="0" y1="1" x2="0" y2="0">
        <stop offset="0%" stop-color="#ff3d00" stop-opacity="0.4"/>
        <stop offset="100%" stop-color="#ff3d00" stop-opacity="0"/>
      </linearGradient>
    </defs>
    ${yTicks}${xTicks}
    <path d="${posArea}" fill="url(#lossGrad)"/>
    <path d="${negArea}" fill="url(#gainGrad)"/>
    <line x1="${M.left}" y1="${yZero}" x2="${M.left+w}" y2="${yZero}" stroke="#444" stroke-width="1" stroke-dasharray="3,3"/>
    <line x1="${M.left}" y1="${M.top}" x2="${M.left}" y2="${M.top+h}" stroke="#888" stroke-width="1.5"/>
    <text x="${M.left+4}" y="${M.top+12}" class="chart-label" fill="#888">START</text>
    <line x1="${x_finish}" y1="${M.top}" x2="${x_finish}" y2="${M.top+h}" stroke="#888" stroke-width="1.5"/>
    <text x="${x_finish-4}" y="${M.top+12}" class="chart-label" text-anchor="end" fill="#888">ZIEL</text>
    <path d="${path}" fill="none" stroke="#f5f5f0" stroke-width="2" stroke-linejoin="round"/>
    <line x1="${x_loss}" y1="${M.top}" x2="${x_loss}" y2="${M.top+h}" stroke="#00d4ff" stroke-width="1" stroke-dasharray="2,4" opacity="0.6"/>
    <text x="${x_loss}" y="${M.top-6}" class="chart-label" text-anchor="middle" fill="#00d4ff">A GEWINNT</text>
    <line x1="${x_gain}" y1="${M.top}" x2="${x_gain}" y2="${M.top+h}" stroke="#ff3d00" stroke-width="1" stroke-dasharray="2,4" opacity="0.6"/>
    <text x="${x_gain}" y="${M.top-6}" class="chart-label" text-anchor="middle" fill="#ff3d00">B GEWINNT</text>
    <text x="${M.left-44}" y="${M.top+12}" class="chart-label" transform="rotate(-90 ${M.left-44},${M.top+12})">DELTA-T (S) →</text>
    <g id="delta-cursor"></g>
  `;
  const cursorG = document.getElementById('delta-cursor');

  function drawCursor(idx){
    if (idx < 0 || idx >= DATA.distance.length){ cursorG.innerHTML = ''; return; }
    const x = xS(DATA.distance[idx]);
    const y = yS(DATA.delta[idx]);
    cursorG.innerHTML = `
      <line x1="${x.toFixed(1)}" y1="${M.top}" x2="${x.toFixed(1)}" y2="${M.top+h}" stroke="#fff" stroke-width="1" opacity="0.7"/>
      <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" fill="#0a0a0a" stroke="#fff" stroke-width="2"/>
    `;
  }

  function indexFromEvent(evt){
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return -1;
    const local = pt.matrixTransform(ctm.inverse());
    if (local.x < M.left || local.x > M.left + w) return -1;
    const dist = (local.x - M.left) / w * distMax;
    // Find closest index in DATA.distance
    let lo = 0, hi = DATA.distance.length - 1;
    while (lo < hi){
      const mid = (lo + hi) >> 1;
      if (DATA.distance[mid] < dist) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(DATA.distance[lo-1] - dist) < Math.abs(DATA.distance[lo] - dist)) lo--;
    return lo;
  }

  svg.addEventListener('mousemove', (e) => {
    if (stickyIdx >= 0) return;
    const i = indexFromEvent(e);
    if (i >= 0) setCursor(i, undefined);
  });
  svg.addEventListener('mouseleave', () => { if (stickyIdx < 0) clearLiveCursor(); });
  svg.addEventListener('click', (e) => {
    const i = indexFromEvent(e);
    if (i < 0) return;
    if (stickyIdx === i){ setCursor(-1, false); } else { setCursor(i, true); }
  });

  return { drawCursor };
})();

// ============================================================================
// Speed chart
// ============================================================================
const speedChart = (function(){
  const svg = document.getElementById('speed-chart');
  const W = 1200, H = 480;
  const M = {top: 16, right: 24, bottom: 36, left: 56};
  const w = W - M.left - M.right, h = H - M.top - M.bottom;
  const distMax = DATA.distance[DATA.distance.length-1];
  const sMax = Math.ceil(Math.max(Math.max(...DATA.a_speed), Math.max(...DATA.b_speed)) / 50) * 50;
  const xS = d => M.left + (d / distMax) * w;
  const yS = v => M.top + (1 - v / sMax) * h;

  let aPath = '', bPath = '';
  for (let i = 0; i < DATA.distance.length; i++){
    const x = xS(DATA.distance[i]);
    aPath += (i===0?'M':'L') + x.toFixed(1) + ',' + yS(DATA.a_speed[i]).toFixed(1);
    bPath += (i===0?'M':'L') + x.toFixed(1) + ',' + yS(DATA.b_speed[i]).toFixed(1);
  }
  let yTicks = '';
  for (let v = 0; v <= sMax; v += 50){
    const y = yS(v);
    yTicks += `<line x1="${M.left}" y1="${y}" x2="${M.left+w}" y2="${y}" stroke="#1a1a1a" stroke-width="1"/>`;
    yTicks += `<text x="${M.left-8}" y="${y+3}" class="chart-tick" text-anchor="end">${v}</text>`;
  }
  let xTicks = '';
  for (let d = 0; d <= distMax; d += 1000){
    const x = xS(d);
    xTicks += `<line x1="${x}" y1="${M.top}" x2="${x}" y2="${M.top+h}" stroke="#1a1a1a" stroke-width="1"/>`;
    xTicks += `<text x="${x}" y="${M.top+h+18}" class="chart-tick" text-anchor="middle">${(d/1000).toFixed(1)} km</text>`;
  }
  svg.innerHTML = `
    ${yTicks}${xTicks}
    <path d="${aPath}" fill="none" stroke="#00d4ff" stroke-width="1.5" opacity="0.85"/>
    <path d="${bPath}" fill="none" stroke="#ff3d00" stroke-width="1.5" opacity="0.85"/>
    <text x="${M.left-44}" y="${M.top+12}" class="chart-label" transform="rotate(-90 ${M.left-44},${M.top+12})">SPEED (KM/H) →</text>
    <g id="speed-cursor"></g>
  `;
  const cursorG = document.getElementById('speed-cursor');

  function drawCursor(idx){
    if (idx < 0 || idx >= DATA.distance.length){ cursorG.innerHTML = ''; return; }
    const x = xS(DATA.distance[idx]);
    const yA = yS(DATA.a_speed[idx]);
    const yB = yS(DATA.b_speed[idx]);
    cursorG.innerHTML = `
      <line x1="${x.toFixed(1)}" y1="${M.top}" x2="${x.toFixed(1)}" y2="${M.top+h}" stroke="#fff" stroke-width="1" opacity="0.7"/>
      <circle cx="${x.toFixed(1)}" cy="${yA.toFixed(1)}" r="5" fill="#0a0a0a" stroke="#00d4ff" stroke-width="2"/>
      <circle cx="${x.toFixed(1)}" cy="${yB.toFixed(1)}" r="5" fill="#0a0a0a" stroke="#ff3d00" stroke-width="2"/>
    `;
  }

  function indexFromEvent(evt){
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return -1;
    const local = pt.matrixTransform(ctm.inverse());
    if (local.x < M.left || local.x > M.left + w) return -1;
    const dist = (local.x - M.left) / w * distMax;
    let lo = 0, hi = DATA.distance.length - 1;
    while (lo < hi){
      const mid = (lo + hi) >> 1;
      if (DATA.distance[mid] < dist) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(DATA.distance[lo-1] - dist) < Math.abs(DATA.distance[lo] - dist)) lo--;
    return lo;
  }

  svg.addEventListener('mousemove', (e) => {
    if (stickyIdx >= 0) return;
    const i = indexFromEvent(e);
    if (i >= 0) setCursor(i, undefined);
  });
  svg.addEventListener('mouseleave', () => { if (stickyIdx < 0) clearLiveCursor(); });
  svg.addEventListener('click', (e) => {
    const i = indexFromEvent(e);
    if (i < 0) return;
    if (stickyIdx === i){ setCursor(-1, false); } else { setCursor(i, true); }
  });

  return { drawCursor };
})();

// ============================================================================
// v21.19 — Multi-Channel-Chart (Sektion 04)
//
// Zeigt beliebig viele Telemetrie-Kanäle aus beiden Runden auf der gleichen
// Distanz-Achse. Linien-Stil: A = solid, B = dashed. Eine Y-Achse pro
// aktiver Trace, links/rechts wechselnd gestackt.
//
// State: extrasState.active = Liste von Trace-Keys ("a:tp_2", "b:phi_lean", ...).
// Default: nichts aktiv → Empty-State.
// ============================================================================
const extrasChart = (function(){
  const svg = document.getElementById('extras-chart');
  if (!svg) return { drawCursor: () => {} };
  const W = 1200, H = 480;
  const distArr = DATA.distance || [];
  const N = distArr.length;
  const distMax = N ? distArr[N - 1] : 0;

  const A_EX = DATA.a_extras || [];
  const B_EX = DATA.b_extras || [];

  // Trace-Key = "a:<id>" oder "b:<id>". Jeder Toggle ist ein Trace.
  // Lookup: { key: { src, id, name, unit, min, max, mean, data } }
  const traces = {};
  A_EX.forEach(e => { traces['a:' + e.id] = { src: 'a', ...e }; });
  B_EX.forEach(e => { traces['b:' + e.id] = { src: 'b', ...e }; });

  // Farb-Pool für die einzelnen Channel-Namen (gleicher Channel-Name → gleiche Farbe,
  // dann unterscheidet der Linien-Stil zwischen A und B).
  const COLOR_POOL = [
    '#ffd166','#06d6a0','#bb86fc','#ef476f','#f5a05c',
    '#7eaaff','#ffba49','#a0e8af','#ff8fc7','#9bf3f0',
  ];
  const nameColor = {};
  function colorFor(name){
    if (!(name in nameColor)){
      nameColor[name] = COLOR_POOL[Object.keys(nameColor).length % COLOR_POOL.length];
    }
    return nameColor[name];
  }

  // --- State ---------------------------------------------------------------
  const state = {
    active: [],          // Reihenfolge bestimmt Achsen-Stack
    search: '',
  };

  // --- DOM -----------------------------------------------------------------
  const legendHost = document.getElementById('ext-legend');
  const countSpan  = document.getElementById('ext-pick-count');
  const pickBtn    = document.getElementById('ext-pick-btn');
  const modal      = document.getElementById('ext-modal');
  const modalClose = document.getElementById('ext-modal-close');
  const search     = document.getElementById('ext-search');
  const tbody      = document.getElementById('ext-table-body');
  const hint       = document.getElementById('ext-modal-hint');
  const btnClear   = document.getElementById('ext-clear');
  const btnApply   = document.getElementById('ext-apply');

  // --- X-Axis (geteilt) ----------------------------------------------------
  // Y-Achsen werden gestapelt: für n aktive Traces brauchen wir
  // ceil(n/2) Stack-Spalten auf jeder Seite. Jede Spalte ist ~52px breit
  // (Achsen-Label + Tick-Beschriftung).
  function layout(nActive){
    const AX_W = 52;                     // Breite einer Y-Achsen-Spalte
    const perSide = Math.ceil(nActive / 2);
    const leftCols  = Math.min(perSide, Math.ceil(nActive / 2));
    const rightCols = nActive - leftCols;
    const M = {
      top: 16, bottom: 36,
      left:  AX_W * Math.max(leftCols, 1) + 10,
      right: AX_W * Math.max(rightCols, 0) + 16,
    };
    const w = W - M.left - M.right;
    const h = H - M.top - M.bottom;
    return { M, w, h, AX_W, leftCols, rightCols };
  }

  function niceTicks(min, max, n){
    if (!isFinite(min) || !isFinite(max) || max <= min){
      return [min, max];
    }
    const range = max - min;
    const rough = range / Math.max(1, n);
    const pow = Math.pow(10, Math.floor(Math.log10(rough)));
    const candidates = [1, 2, 2.5, 5, 10].map(c => c * pow);
    let step = candidates[0];
    for (const c of candidates){ if (c >= rough){ step = c; break; } }
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const out = [];
    for (let v = lo; v <= hi + step * 0.5; v += step){
      out.push(Math.round(v / step) * step);
    }
    return out;
  }

  // --- Render --------------------------------------------------------------
  function renderChart(){
    if (state.active.length === 0){
      svg.innerHTML = `<text x="${W/2}" y="${H/2}" text-anchor="middle"
        class="chart-tick" style="font-size:14px;letter-spacing:.1em">
        KEINE KANÄLE GEWÄHLT — KLICK „KANÄLE WÄHLEN“ ZUM HINZUFÜGEN
      </text>`;
      renderLegend();
      return;
    }

    const { M, w, h, AX_W, leftCols, rightCols } = layout(state.active.length);
    const xS = d => M.left + (d / distMax) * w;

    // X-Achse (Distanz) — gemeinsam für alle Traces
    let html = '';
    let xTicks = '';
    for (let d = 0; d <= distMax; d += 1000){
      const x = xS(d);
      xTicks += `<line x1="${x}" y1="${M.top}" x2="${x}" y2="${M.top+h}" stroke="#1a1a1a" stroke-width="1"/>`;
      xTicks += `<text x="${x}" y="${M.top+h+18}" class="chart-tick" text-anchor="middle">${(d/1000).toFixed(1)} km</text>`;
    }
    html += xTicks;

    // Pro aktivem Trace: eigene Y-Achse (links/rechts wechselnd) + Pfad
    state.active.forEach((key, idx) => {
      const tr = traces[key];
      if (!tr) return;
      const onLeft = (idx % 2 === 0);
      const colIdx = Math.floor(idx / 2);              // Stack-Position auf der Seite
      const axisX = onLeft
        ? (M.left - 8 - colIdx * AX_W)
        : (M.left + w + 8 + colIdx * AX_W);

      // Trace-Skalierung: per-trace min/max (mit 5% Padding)
      let mn = tr.min, mx = tr.max;
      if (!isFinite(mn) || !isFinite(mx) || mn === mx){
        mn = (mn ?? 0) - 1; mx = (mx ?? 0) + 1;
      }
      const pad = (mx - mn) * 0.05;
      mn -= pad; mx += pad;
      const yS = v => M.top + (1 - (v - mn) / (mx - mn)) * h;

      const color = colorFor(tr.name);
      const dash = (tr.src === 'a') ? '' : ' stroke-dasharray="6,4"';

      // Pfad
      const data = tr.data || [];
      let p = '';
      for (let i = 0; i < data.length; i++){
        const x = xS(distArr[i]);
        const y = yS(data[i]);
        p += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
      }
      html += `<path d="${p}" fill="none" stroke="${color}" stroke-width="1.4" opacity="0.92"${dash}/>`;

      // Y-Achse: 3 Ticks (min, mid, max)
      const ticks = niceTicks(mn, mx, 3);
      ticks.forEach(v => {
        if (v < mn || v > mx) return;
        const y = yS(v);
        const text = (Math.abs(v) >= 100 || v % 1 === 0)
          ? v.toFixed(0)
          : v.toFixed(2);
        html += `<text x="${axisX}" y="${y.toFixed(1) + 3}" class="chart-tick" text-anchor="${onLeft?'end':'start'}" fill="${color}">${text}</text>`;
      });
      // Achsen-Beschriftung (Name + Quelle)
      const labelX = axisX + (onLeft ? -2 : 2);
      const labelY = M.top - 2;
      const labelTxt = `${tr.name}${tr.unit ? ' ('+tr.unit+')' : ''} · ${tr.src.toUpperCase()}`;
      html += `<text x="${labelX}" y="${labelY}" class="chart-label" text-anchor="${onLeft?'end':'start'}" fill="${color}">${labelTxt}</text>`;
    });

    // Cursor-Layer
    html += `<g id="ext-cursor"></g>`;

    svg.innerHTML = html;
    renderLegend();
  }

  function renderLegend(){
    if (!legendHost) return;
    if (state.active.length === 0){
      legendHost.innerHTML = '';
    } else {
      legendHost.innerHTML = state.active.map(key => {
        const tr = traces[key]; if (!tr) return '';
        const color = colorFor(tr.name);
        const styleA = `border-top:2px solid ${color};`;
        const styleB = `border-top:2px dashed ${color};`;
        return `<span class="lg"><span class="swatch" style="${tr.src==='a'?styleA:styleB}"></span>${tr.src.toUpperCase()} · ${tr.name}${tr.unit?' ('+tr.unit+')':''}</span>`;
      }).join('');
    }
    if (countSpan){
      countSpan.textContent = state.active.length
        ? `(${state.active.length})` : '';
    }
  }

  // --- Cursor (koordiniert mit den anderen Charts) -------------------------
  function drawCursor(idx){
    const g = document.getElementById('ext-cursor');
    if (!g) return;
    if (idx < 0 || idx >= N || state.active.length === 0){
      g.innerHTML = ''; return;
    }
    const { M, w, h, AX_W } = layout(state.active.length);
    const xS = d => M.left + (d / distMax) * w;
    const x = xS(distArr[idx]);
    let html = `<line x1="${x.toFixed(1)}" y1="${M.top}" x2="${x.toFixed(1)}" y2="${M.top+h}" stroke="#fff" stroke-width="1" opacity="0.7"/>`;
    state.active.forEach((key, i) => {
      const tr = traces[key]; if (!tr) return;
      let mn = tr.min, mx = tr.max;
      if (!isFinite(mn) || !isFinite(mx) || mn === mx){
        mn = (mn ?? 0) - 1; mx = (mx ?? 0) + 1;
      }
      const pad = (mx - mn) * 0.05; mn -= pad; mx += pad;
      const yS = v => M.top + (1 - (v - mn) / (mx - mn)) * h;
      const v = tr.data[idx];
      if (v == null || !isFinite(v)) return;
      const color = colorFor(tr.name);
      const y = yS(v);
      html += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="#0a0a0a" stroke="${color}" stroke-width="2"/>`;
    });
    g.innerHTML = html;
  }

  // --- Modal ---------------------------------------------------------------
  function openModal(){
    if (!modal) return;
    state.search = '';
    if (search) search.value = '';
    rebuildTable();
    modal.hidden = false;
    setTimeout(() => search && search.focus(), 0);
  }
  function closeModal(){
    if (!modal) return;
    modal.hidden = true;
  }
  function rebuildTable(){
    if (!tbody) return;
    const q = (state.search || '').toLowerCase();

    // v21.20 — pro Channel-NAME eine Zeile, mit A- und B-Checkbox.
    // Mapping name → {aEntry, bEntry, aId, bId}.
    // Channels mit gleichem `name` werden also nebeneinander gestellt,
    // unabhängig davon ob ihre internen IDs gleich sind.
    const byName = {};
    A_EX.forEach(e => {
      const n = e.name || e.id;
      (byName[n] = byName[n] || {}).a = e;
    });
    B_EX.forEach(e => {
      const n = e.name || e.id;
      (byName[n] = byName[n] || {}).b = e;
    });

    // Sortierung: zuerst Channels die in beiden Runden vorkommen,
    // dann nur-A, dann nur-B; jeweils alphabetisch nach Name.
    const names = Object.keys(byName);
    const both = names.filter(n => byName[n].a && byName[n].b).sort();
    const onlyA = names.filter(n => byName[n].a && !byName[n].b).sort();
    const onlyB = names.filter(n => !byName[n].a && byName[n].b).sort();
    const sorted = [...both, ...onlyA, ...onlyB];

    const filtered = sorted.filter(n => !q || n.toLowerCase().includes(q));

    if (hint) hint.textContent =
      `${names.length} Kanäle · ${state.active.length} aktiv`;

    if (filtered.length === 0){
      tbody.innerHTML = '<div class="ch-empty">KEINE TREFFER</div>';
      return;
    }
    tbody.innerHTML = filtered.map(name => {
      const slot = byName[name];
      const color = colorFor(name);
      const aKey = slot.a ? ('a:' + slot.a.id) : null;
      const bKey = slot.b ? ('b:' + slot.b.id) : null;
      const aOn = aKey && state.active.includes(aKey);
      const bOn = bKey && state.active.includes(bKey);
      const aCell = slot.a
        ? `<span class="ch-col-a"><input type="checkbox" data-key="${aKey}" ${aOn?'checked':''} aria-label="A: ${name}"></span>`
        : `<span class="ch-col-a dim">—</span>`;
      const bCell = slot.b
        ? `<span class="ch-col-b"><input type="checkbox" data-key="${bKey}" ${bOn?'checked':''} aria-label="B: ${name}"></span>`
        : `<span class="ch-col-b dim">—</span>`;
      return `<div class="ch-row">
        ${aCell}
        <span class="ch-col-name"><span class="swatch" style="background:${color}"></span>${name}</span>
        ${bCell}
      </div>`;
    }).join('');
  }

  // --- Events --------------------------------------------------------------
  if (pickBtn)    pickBtn.addEventListener('click', openModal);
  if (modalClose) modalClose.addEventListener('click', closeModal);
  if (modal)      modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
  if (search)     search.addEventListener('input', () => {
    state.search = search.value; rebuildTable();
  });
  if (tbody)      tbody.addEventListener('change', e => {
    // v21.20 — Toggle pro Checkbox; jede Zeile hat zwei davon (A und B).
    const cb = e.target;
    if (!cb || cb.type !== 'checkbox') return;
    const key = cb.dataset.key;
    if (!key) return;
    const i = state.active.indexOf(key);
    if (cb.checked && i < 0) state.active.push(key);
    if (!cb.checked && i >= 0) state.active.splice(i, 1);
    // Counter/Hint live aktualisieren ohne ganze Tabelle neu zu bauen,
    // damit der Focus auf der Checkbox erhalten bleibt.
    if (hint){
      const total = (A_EX.length + B_EX.length);
      const names = new Set([...A_EX.map(e=>e.name||e.id), ...B_EX.map(e=>e.name||e.id)]);
      hint.textContent = `${names.size} Kanäle · ${state.active.length} aktiv`;
    }
  });
  if (btnClear)   btnClear.addEventListener('click', () => {
    state.active = []; rebuildTable();
  });
  if (btnApply)   btnApply.addEventListener('click', () => {
    closeModal();
    renderChart();
    // v21.21 — Cursor-Info aktualisieren damit neue Kanal-Cells sichtbar werden
    if (typeof updateInfoBox === 'function') updateInfoBox(currentIdx);
  });
  document.addEventListener('keydown', e => {
    if (modal && !modal.hidden && e.key === 'Escape') closeModal();
  });

  // --- Hover für Cursor-Coupling -------------------------------------------
  svg.addEventListener('mousemove', (e) => {
    if (stickyIdx >= 0) return;
    const i = indexFromEvent(e);
    if (i >= 0) setCursor(i, undefined);
  });
  svg.addEventListener('mouseleave', () => { if (stickyIdx < 0) clearLiveCursor(); });
  svg.addEventListener('click', (e) => {
    const i = indexFromEvent(e);
    if (i < 0) return;
    if (stickyIdx === i){ setCursor(-1, false); } else { setCursor(i, true); }
  });
  function indexFromEvent(evt){
    if (state.active.length === 0) return -1;
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return -1;
    const local = pt.matrixTransform(ctm.inverse());
    const { M, w } = layout(state.active.length);
    if (local.x < M.left || local.x > M.left + w) return -1;
    const dist = (local.x - M.left) / w * distMax;
    let lo = 0, hi = N - 1;
    while (lo < hi){
      const mid = (lo + hi) >> 1;
      if (distArr[mid] < dist) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  // --- Initial render ------------------------------------------------------
  renderChart();
  // Pick-Button ggf. ausblenden wenn keine Extras vorhanden sind
  if (A_EX.length === 0 && B_EX.length === 0){
    if (pickBtn) pickBtn.disabled = true;
    if (pickBtn) pickBtn.textContent = 'KEINE ZUSATZ-KANÄLE';
  }

  // v21.21 — Cursor-Info-Box braucht Zugriff auf die aktiven Channels +
  // Werte am aktuellen Cursor. Eine Cell pro Channel-NAME (gepaart wenn
  // sowohl A als auch B aktiv sind), sonst pro aktiver Trace eine.
  function getCellsAt(idx){
    if (state.active.length === 0) return [];
    // Gruppieren nach Channel-Name. Reihenfolge: erstes Auftauchen in state.active.
    const groups = []; const seen = {};
    state.active.forEach(key => {
      const tr = traces[key]; if (!tr) return;
      const n = tr.name;
      if (!(n in seen)){
        seen[n] = groups.length;
        groups.push({ name: n, color: colorFor(n), unit: tr.unit || '',
                      aTrace: null, bTrace: null });
      }
      const g = groups[seen[n]];
      if (tr.src === 'a') g.aTrace = tr;
      if (tr.src === 'b') g.bTrace = tr;
    });
    return groups.map(g => {
      const fmt = (tr) => {
        if (!tr) return null;
        if (idx < 0 || idx >= (tr.data || []).length) return null;
        const v = tr.data[idx];
        if (v == null || !isFinite(v)) return null;
        return (Math.abs(v) >= 100 || (v % 1 === 0)) ? v.toFixed(0) : v.toFixed(2);
      };
      return {
        name:  g.name,
        unit:  g.unit,
        color: g.color,
        aVal:  fmt(g.aTrace),
        bVal:  fmt(g.bTrace),
        hasA:  !!g.aTrace,
        hasB:  !!g.bTrace,
      };
    });
  }

  return { drawCursor, getCellsAt };
})();

// Initial render — show lap summary until the user hovers
updateInfoBox(-1);
</script>
</body>
</html>
"""


def _downsample(arr, n):
    """Resample a 1D array to length n via linear interpolation."""
    if len(arr) == n:
        return arr
    idx = np.linspace(0, len(arr) - 1, n).astype(int)
    return arr[idx]


def _downsample_extras(extras, keep_idx, expected_full_len):
    """v21.19 — Reduce the per-channel data arrays to the chart sample grid.

    Each entry is reshaped into the minimum JSON-friendly shape the SPA
    expects: {id, name, unit, min, max, mean, data}.
    `keep_idx` is the integer-index array we use for all other DATA arrays
    (so distance and channels line up 1:1). `expected_full_len` is the
    length of the un-downsampled aligned arrays — channels of that length
    are simply indexed, others are interpolated as a fallback.
    """
    n = len(keep_idx)
    out = []
    for e in (extras or []):
        data = e.get("data") or []
        if len(data) == 0:
            continue
        arr = np.asarray(data, dtype=np.float64)
        if len(arr) == expected_full_len:
            arr = arr[keep_idx]
        else:
            arr = np.interp(np.linspace(0, len(arr) - 1, n),
                            np.arange(len(arr)), arr)
        out.append({
            "id":   e.get("id"),
            "name": e.get("name"),
            "unit": e.get("unit") or "",
            "min":  e.get("min"),
            "max":  e.get("max"),
            "mean": e.get("mean"),
            "data": arr.round(3).tolist(),
        })
    return out


def _fmt_sector(s: float) -> str:
    """Sektorzeit kompakt: unter 60s als SS.sss, sonst M:SS.sss."""
    if s < 60:
        return f"{s:.3f}"
    m = int(s // 60)
    return f"{m}:{s - m*60:06.3f}"


def render_theo_block(theo) -> str:
    """v23.14/v23.15 — Kleine Extra-View 'Theoretical Best' unter den Hot
    Zones. Abschnitts-Tabelle (Kurven/Geraden aus segment_track, beste
    Zelle je Zeile im Slot-Akzent), darunter die kombinierte theoretische
    Bestzeit + Delta zur besten echten Runde."""
    if not theo:
        return ""
    kinds = {"kurve": "KURVE", "gerade": "GERADE", "sektor": "SEKTOR"}
    rows = []
    for sec in theo["sectors"]:
        a_cls = ' class="theo-best theo-a"' if sec["best"] == "a" else ""
        b_cls = ' class="theo-best theo-b"' if sec["best"] == "b" else ""
        label = sec.get("label") or f'S{sec["sector"]}'
        kind = kinds.get(sec.get("kind") or "sektor", "SEKTOR")
        kind_cls = "theo-kind-k" if sec.get("kind") == "kurve" else "theo-kind-g"
        rows.append(
            f'<tr>'
            f'<td class="theo-sec">{label}</td>'
            f'<td class="theo-kind {kind_cls}">{kind}</td>'
            f'<td class="theo-range">{int(round(sec["start_m"]))}–'
            f'{int(round(sec["end_m"]))} m</td>'
            f'<td{a_cls}>{_fmt_sector(sec["a_s"])}</td>'
            f'<td{b_cls}>{_fmt_sector(sec["b_s"])}</td>'
            f'</tr>'
        )
    n_k = sum(1 for s in theo["sectors"] if s.get("kind") == "kurve")
    n_g = sum(1 for s in theo["sectors"] if s.get("kind") == "gerade")
    if n_k or n_g:
        header_num = f"{n_k} KURVEN · {n_g} GERADEN"
    else:
        header_num = f'{theo["n_sectors"]} SEKTOREN'
    best_name = "A" if theo["best_lap"] == "a" else "B"
    vs = theo["vs_best_s"]
    vs_html = (f'−{abs(vs):.3f} s vs. Lap {best_name}'
               if vs < -0.0005 else
               f'Lap {best_name} ist bereits die theoretische Bestzeit')
    return f"""
  <div class="section-title">
    <h2>06 · THEORETICAL BEST</h2>
    <span class="num">{header_num}</span>
  </div>
  <div class="theo-card">
    <div class="theo-table-wrap">
    <table class="theo-table">
      <thead><tr><th></th><th></th><th>ABSCHNITT</th><th class="theo-h-a">LAP A</th>
        <th class="theo-h-b">LAP B</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </div>
    <div class="theo-result">
      <div class="theo-result-label">KOMBINIERTE BESTZEIT</div>
      <div class="theo-result-time">{_fmt_lap(theo["theoretical_s"])}</div>
      <div class="theo-result-delta">{vs_html}</div>
    </div>
  </div>
  <style>
  .theo-card{{background:var(--bg-2,#141414);border:1px solid var(--line,#262626);
    display:grid;grid-template-columns:1fr auto;gap:24px;align-items:start;
    padding:20px 24px;margin-bottom:32px}}
  .theo-table-wrap{{max-height:340px;overflow-y:auto}}
  .theo-table{{border-collapse:collapse;font-family:'JetBrains Mono',monospace;
    font-feature-settings:'tnum';font-size:12px;width:100%}}
  .theo-table th{{font-size:10px;letter-spacing:.15em;color:var(--ink-faint,#888);
    text-align:left;padding:4px 12px 8px 0;font-weight:400;position:sticky;
    top:0;background:var(--bg-2,#141414)}}
  .theo-table th.theo-h-a{{color:#00d4ff}}
  .theo-table th.theo-h-b{{color:#ff3d00}}
  .theo-table td{{padding:5px 12px 5px 0;color:var(--ink-dim,#a0a0a0);
    border-top:1px solid var(--line,#262626)}}
  .theo-table td.theo-sec{{color:var(--ink,#f5f5f0);letter-spacing:.1em}}
  .theo-table td.theo-kind{{font-size:9px;letter-spacing:.15em}}
  .theo-table td.theo-kind-k{{color:var(--ink-dim,#a0a0a0)}}
  .theo-table td.theo-kind-g{{color:var(--ink-faint,#888)}}
  .theo-table td.theo-range{{font-size:11px;color:var(--ink-faint,#888)}}
  .theo-table td.theo-best{{color:var(--ink,#f5f5f0);font-weight:500}}
  .theo-table td.theo-best.theo-a{{color:#00d4ff}}
  .theo-table td.theo-best.theo-b{{color:#ff3d00}}
  .theo-result{{text-align:right;min-width:220px;position:sticky;top:0}}
  .theo-result-label{{font-family:'JetBrains Mono',monospace;font-size:10px;
    letter-spacing:.2em;color:var(--ink-faint,#888);margin-bottom:6px}}
  .theo-result-time{{font-family:'Bebas Neue',sans-serif;font-size:44px;
    line-height:1;color:var(--ink,#f5f5f0)}}
  .theo-result-delta{{font-family:'JetBrains Mono',monospace;font-size:11px;
    color:#00d4ff;margin-top:6px}}
  @media (max-width:720px){{
    .theo-card{{grid-template-columns:1fr}}
    .theo-result{{text-align:left;position:static}}
  }}
  </style>
"""


def build_html_report(
    track_a, lap_a_meta, lap_a_data,
    track_b, lap_b_meta, lap_b_data,
    aligned, zones,
    n_samples_html=500,
    maptiler_key: str = "",
):
    """Render the HTML report and return it as a string."""

    # v23.14/v23.15 — Theoretical Best. Bevorzugt Kurven/Geraden-
    # Segmentierung; fällt bei flachem Speed-Profil auf gleiche
    # Distanz-Sektoren zurück. Scheitert auch das: Extra-View entfällt,
    # nie der ganze Report.
    try:
        try:
            segs = segment_track(aligned)
            _theo_block_html = render_theo_block(
                theoretical_best(aligned, segments=segs))
        except ValueError:
            _theo_block_html = render_theo_block(theoretical_best(aligned))
    except Exception:
        _theo_block_html = ""

    # Downsample arrays for embedding
    n = min(n_samples_html, len(aligned["distance"]))
    keep = np.linspace(0, len(aligned["distance"]) - 1, n).astype(int)
    full_len = len(aligned["distance"])

    payload = {
        "distance": aligned["distance"][keep].round(1).tolist(),
        "a_speed": aligned["a_speed"][keep].round(1).tolist(),
        "b_speed": aligned["b_speed"][keep].round(1).tolist(),
        "a_time": aligned["a_time"][keep].round(3).tolist(),
        "b_time": aligned["b_time"][keep].round(3).tolist(),
        "delta": aligned["delta"][keep].round(4).tolist(),
        "a_lat": aligned["a_lat"][keep].round(6).tolist(),
        "a_lon": aligned["a_lon"][keep].round(6).tolist(),
        "b_lat": aligned["b_lat"][keep].round(6).tolist(),
        "b_lon": aligned["b_lon"][keep].round(6).tolist(),
        "a_extras": _downsample_extras(aligned.get("a_extras"), keep, full_len),
        "b_extras": _downsample_extras(aligned.get("b_extras"), keep, full_len),
        "loss_dist": float(zones["max_loss"]["distance_m"]),
        "gain_dist": float(zones["max_gain"]["distance_m"]),
        "lap_distance_m": float(aligned.get("lap_distance_m",
                                            aligned["distance"][-1])),
        "finish_line": (
            list(track_b.get("finish_line"))
            if track_b.get("finish_line") and track_b["finish_line"][0] is not None
            else (list(track_a.get("finish_line"))
                  if track_a.get("finish_line") and track_a["finish_line"][0] is not None
                  else None)
        ),
    }

    delta_total = lap_b_meta["duration"] - lap_a_meta["duration"]
    delta_sign = "+" if delta_total >= 0 else "−"

    venue = (
        track_a.get("meta", {}).get("VENUE")
        or track_b.get("meta", {}).get("VENUE")
        or track_a.get("meta", {}).get("TRACK")
        or track_b.get("meta", {}).get("TRACK")
        or "TRACK"
    )
    # SES TRACK names are abbreviated (e.g. "CATALUNY") — prettify common ones
    venue_pretty = {
        "CATALUNY": "Catalunya",
    }.get(venue.upper(), venue)

    replacements = {
        "{{TITLE}}": f"Racedat — {venue_pretty}",
        "{{VENUE_LABEL}}": venue_pretty.upper(),
        "{{VENUE}}": venue_pretty.upper(),
        "{{A_FILE}}": _short(track_a["source_file"]).upper(),
        "{{B_FILE}}": _short(track_b["source_file"]).upper(),
        "{{A_FILE_FULL}}": _short(track_a["source_file"], 60),
        "{{B_FILE_FULL}}": _short(track_b["source_file"], 60),
        "{{A_FORMAT}}": track_a["source_format"],
        "{{B_FORMAT}}": track_b["source_format"],
        "{{A_TIME}}": _fmt_lap(lap_a_meta["duration"]),
        "{{B_TIME}}": _fmt_lap(lap_b_meta["duration"]),
        "{{A_LAP_NUM}}": str(lap_a_meta.get("lap_index", "?")),
        "{{B_LAP_NUM}}": str(lap_b_meta.get("lap_index", "?")),
        "{{A_DIST}}": f"{lap_a_data['total_distance']:.0f}",
        "{{B_DIST}}": f"{lap_b_data['total_distance']:.0f}",
        "{{A_VMAX}}": f"{int(round(lap_a_data['speed'].max()))}",
        "{{B_VMAX}}": f"{int(round(lap_b_data['speed'].max()))}",
        "{{DELTA}}": f"{abs(delta_total):.2f}",
        "{{DELTA_SIGN}}": delta_sign,
        "{{WIN_M}}": f"{int(round(aligned['window_distance_m']))}",
        "{{LOSS_DIST}}": f"{int(round(zones['max_loss']['distance_m']))}",
        "{{THEO_BLOCK}}": _theo_block_html,
        "{{GAIN_DIST}}": f"{int(round(zones['max_gain']['distance_m']))}",
        "{{LOSS_MS}}": f"{int(round(zones['max_loss']['value_s'] * 1000))}",
        "{{GAIN_MS}}": f"{int(round(abs(zones['max_gain']['value_s']) * 1000))}",
        "{{LOSS_VA}}": f"{int(round(zones['max_loss']['a_speed']))}",
        "{{LOSS_VB}}": f"{int(round(zones['max_loss']['b_speed']))}",
        "{{GAIN_VA}}": f"{int(round(zones['max_gain']['a_speed']))}",
        "{{GAIN_VB}}": f"{int(round(zones['max_gain']['b_speed']))}",
        "{{DATA_JSON}}": json.dumps(payload, separators=(",", ":")),
        "{{TILE_HELPERS_JS}}": _TILE_HELPERS_JS,
        "{{TILE_SPINNER_CSS}}": _TILE_SPINNER_CSS,
        "{{TILE_PROVIDER_JS}}": _tile_provider_js(maptiler_key),
        "{{TM_BG_BTN_CLS}}": _tile_btn_cls(maptiler_key),
    }

    html = _TEMPLATE
    for k, v in replacements.items():
        html = html.replace(k, v)
    return html


# ============================================================================
# v20.4 — Compare SPA support
#
# Three new entry points layered on top of build_html_report:
#   - compute_compare_payload(...)       — pure data shaping (no HTML)
#   - build_compare_html(...)            — full report + picker toolbar at top
#   - build_compare_empty_html()         — picker-only SPA (no laps yet)
#
# URL convention (handled by webserver.py):
#   /compare              → empty SPA, picker only
#   /compare?a=N&b=M      → live-render of two library laps
#   /compare?a=N          → picker SPA with slot A pre-filled
#   /compare?b=N          → picker SPA with slot B pre-filled
#   POST /compare         → ad-hoc upload (unchanged), one-shot render
#
# Cross-links: each loaded slot shows "→ DATENVIEWER" and "→ AI COACH"
# buttons that open /analyze?lap_id=X and /coach?lap_id=X respectively.
# ============================================================================

def compute_compare_payload(
    track_a, lap_a_meta, lap_a_data,
    track_b, lap_b_meta, lap_b_data,
    aligned, zones,
    n_samples_html: int = 500,
):
    """Pure data-shaping for the compare result. No HTML, no I/O.

    Returns a dict with a 'payload' (the JS-side DATA blob) and 'header'
    (the human-readable strings used in the meta-grid / lap cards). The
    webserver passes this through build_compare_html to render the final
    page, or uses it directly when feeding /api/compare in the future.
    """
    n = min(n_samples_html, len(aligned["distance"]))
    keep = np.linspace(0, len(aligned["distance"]) - 1, n).astype(int)
    full_len = len(aligned["distance"])

    payload = {
        "distance": aligned["distance"][keep].round(1).tolist(),
        "a_speed": aligned["a_speed"][keep].round(1).tolist(),
        "b_speed": aligned["b_speed"][keep].round(1).tolist(),
        "a_time": aligned["a_time"][keep].round(3).tolist(),
        "b_time": aligned["b_time"][keep].round(3).tolist(),
        "delta": aligned["delta"][keep].round(4).tolist(),
        "a_lat": aligned["a_lat"][keep].round(6).tolist(),
        "a_lon": aligned["a_lon"][keep].round(6).tolist(),
        "b_lat": aligned["b_lat"][keep].round(6).tolist(),
        "b_lon": aligned["b_lon"][keep].round(6).tolist(),
        "a_extras": _downsample_extras(aligned.get("a_extras"), keep, full_len),
        "b_extras": _downsample_extras(aligned.get("b_extras"), keep, full_len),
        "loss_dist": float(zones["max_loss"]["distance_m"]),
        "gain_dist": float(zones["max_gain"]["distance_m"]),
        "lap_distance_m": float(aligned.get("lap_distance_m",
                                            aligned["distance"][-1])),
        "finish_line": (
            list(track_b.get("finish_line"))
            if track_b.get("finish_line") and track_b["finish_line"][0] is not None
            else (list(track_a.get("finish_line"))
                  if track_a.get("finish_line") and track_a["finish_line"][0] is not None
                  else None)
        ),
    }

    delta_total = lap_b_meta["duration"] - lap_a_meta["duration"]
    venue = (
        track_a.get("meta", {}).get("VENUE")
        or track_b.get("meta", {}).get("VENUE")
        or track_a.get("meta", {}).get("TRACK")
        or track_b.get("meta", {}).get("TRACK")
        or "TRACK"
    )
    venue_pretty = {"CATALUNY": "Catalunya"}.get(venue.upper(), venue)

    return {
        "payload": payload,
        "header": {
            "venue": venue_pretty.upper(),
            "a_file": _short(track_a["source_file"]).upper(),
            "b_file": _short(track_b["source_file"]).upper(),
            "a_file_full": _short(track_a["source_file"], 60),
            "b_file_full": _short(track_b["source_file"], 60),
            "a_format": track_a["source_format"],
            "b_format": track_b["source_format"],
            "a_time": _fmt_lap(lap_a_meta["duration"]),
            "b_time": _fmt_lap(lap_b_meta["duration"]),
            "a_lap_num": str(lap_a_meta.get("lap_index", "?")),
            "b_lap_num": str(lap_b_meta.get("lap_index", "?")),
            "a_dist": f"{lap_a_data['total_distance']:.0f}",
            "b_dist": f"{lap_b_data['total_distance']:.0f}",
            "a_vmax": f"{int(round(lap_a_data['speed'].max()))}",
            "b_vmax": f"{int(round(lap_b_data['speed'].max()))}",
            "delta": f"{abs(delta_total):.2f}",
            "delta_sign": "+" if delta_total >= 0 else "−",
            "win_m": f"{int(round(aligned['window_distance_m']))}",
        },
    }


def build_compare_html(
    track_a, lap_a_meta, lap_a_data,
    track_b, lap_b_meta, lap_b_data,
    aligned, zones,
    a_lap_id="",
    b_lap_id="",
    n_samples_html: int = 500,
    maptiler_key: str = "",
):
    """Compare report + a slot-card region below the hero showing the two slots.

    Each slot card has the big lap-time on top, lap/bike/driver beneath, and a
    "↻ ANDERE RUNDE LADEN" button at the bottom (or "+ RUNDE WÄHLEN" when empty).

    a_lap_id, b_lap_id can be either:
      - int / str-int  (library lap_id)  → cross-links rendered
      - "ad-<hex>"     (adhoc token)     → cross-links suppressed
      - "" / 0         (empty slot)      → "+ RUNDE WÄHLEN" pulsing button
    """
    body = build_html_report(
        track_a, lap_a_meta, lap_a_data,
        track_b, lap_b_meta, lap_b_data,
        aligned, zones, n_samples_html=n_samples_html,
        maptiler_key=maptiler_key,
    )
    meta_a = track_a.get("meta") or {}
    meta_b = track_b.get("meta") or {}
    a_track = meta_a.get("TRACK") or meta_a.get("VENUE") or ""
    b_track = meta_b.get("TRACK") or meta_b.get("VENUE") or ""

    a_fields = {
        "time":   _fmt_lap(lap_a_meta["duration"]),
        "track":  a_track or "—",
        "lap_no": f"#{lap_a_meta.get('lap_index','?')}",
        "bike":   meta_a.get("VEHICLE", "") or "—",
        "driver": meta_a.get("RACER", "") or "—",
        "local":  False,  # build_compare_html is always live render
    }
    b_fields = {
        "time":   _fmt_lap(lap_b_meta["duration"]),
        "track":  b_track or "—",
        "lap_no": f"#{lap_b_meta.get('lap_index','?')}",
        "bike":   meta_b.get("VEHICLE", "") or "—",
        "driver": meta_b.get("RACER", "") or "—",
        "local":  False,
    }

    toolbar = _build_compare_toolbar(
        a_lap_id=str(a_lap_id) if a_lap_id else "",
        b_lap_id=str(b_lap_id) if b_lap_id else "",
        a_track=a_track, b_track=b_track,
        a_fields=a_fields, b_fields=b_fields,
    )
    modal = _build_compare_picker_modal()
    # Toolbar sits AFTER the page heading (<header>) so the title stays on top.
    body = body.replace('</header>', '</header>\n' + toolbar, 1)
    body = body.replace("</body>", modal + "\n</body>", 1)
    return body


def build_compare_empty_html(
    a_lap_id="", a_track: str = "", a_fields=None,
    b_lap_id="", b_track: str = "", b_fields=None,
    maptiler_key: str = "",
):
    """The compare SPA in empty/half-state.

    Renders the same full _TEMPLATE as build_compare_html, but with
    DATA_JSON = null and placeholder header strings. The script in the
    template detects DATA === null on load and swaps the chart/map
    containers for "BITTE ZWEI RUNDEN SELEKTIEREN" placeholders, then
    bails out before touching DATA.*.

    a_fields / b_fields are dicts with keys: time, track, lap_no, bike, driver, local.
    """
    if a_fields is None:
        a_fields = {"time":"—:—.—","track":"—","lap_no":"—","bike":"—","driver":"—","local":False}
    if b_fields is None:
        b_fields = {"time":"—:—.—","track":"—","lap_no":"—","bike":"—","driver":"—","local":False}
    # Placeholder values for the meta-grid / hero — kept readable but dim.
    replacements = {
        "{{TITLE}}": "Racedat — Vergleich",
        "{{VENUE_LABEL}}": "—",
        "{{VENUE}}": "—",
        "{{A_FILE}}": "—",
        "{{B_FILE}}": "—",
        "{{A_FILE_FULL}}": "noch nicht gewählt",
        "{{B_FILE_FULL}}": "noch nicht gewählt",
        "{{A_FORMAT}}": "—",
        "{{B_FORMAT}}": "—",
        "{{A_TIME}}": a_fields.get("time", "—:—.—"),
        "{{B_TIME}}": b_fields.get("time", "—:—.—"),
        "{{A_LAP_NUM}}": "?",
        "{{B_LAP_NUM}}": "?",
        "{{A_DIST}}": "0",
        "{{B_DIST}}": "0",
        "{{A_VMAX}}": "0",
        "{{B_VMAX}}": "0",
        "{{DELTA}}": "0.00",
        "{{DELTA_SIGN}}": "±",
        "{{WIN_M}}": "0",
        "{{LOSS_DIST}}": "0",
        "{{THEO_BLOCK}}": "",
        "{{GAIN_DIST}}": "0",
        "{{LOSS_MS}}": "0",
        "{{GAIN_MS}}": "0",
        "{{LOSS_VA}}": "0",
        "{{LOSS_VB}}": "0",
        "{{GAIN_VA}}": "0",
        "{{GAIN_VB}}": "0",
        "{{DATA_JSON}}": "null",
        "{{TILE_HELPERS_JS}}": _TILE_HELPERS_JS,
        "{{TILE_SPINNER_CSS}}": _TILE_SPINNER_CSS,
        "{{TILE_PROVIDER_JS}}": _tile_provider_js(maptiler_key),
        "{{TM_BG_BTN_CLS}}": _tile_btn_cls(maptiler_key),
    }

    html_doc = _TEMPLATE
    for k, v in replacements.items():
        html_doc = html_doc.replace(k, v)

    toolbar = _build_compare_toolbar(
        a_lap_id=str(a_lap_id) if a_lap_id else "",
        b_lap_id=str(b_lap_id) if b_lap_id else "",
        a_track=a_track, b_track=b_track,
        a_fields=a_fields, b_fields=b_fields,
    )
    modal = _COMPARE_PICKER_MODAL
    # Toolbar after </header> so the page heading stays at the top.
    html_doc = html_doc.replace('</header>', '</header>\n' + toolbar, 1)
    html_doc = html_doc.replace("</body>", modal + "\n</body>", 1)
    return html_doc


def _build_compare_toolbar(
    a_lap_id: str, b_lap_id: str,
    a_track: str, b_track: str,
    a_fields: dict, b_fields: dict,
):
    """Two slot-cards side by side, analog to Datenviewer's lap-card.

    Each slot card has the big lap-time on top, metadata (track / lap /
    bike / driver) beneath, and a "↻ ANDERE RUNDE LADEN" button at the
    bottom (or pulsing "+ RUNDE WÄHLEN" if empty).

    Slot A uses red accent (#00d4ff), Slot B uses cyan (#ff3d00).
    Not sticky — sits at the top of the page content.

    lap_id is a string:
      - ""           → empty slot (renders pulsing + RUNDE X WÄHLEN button)
      - "<int>"      → library lap (renders cross-links + ↻ ÄNDERN)
      - "ad-<hex>"   → ad-hoc upload (renders ↻ ÄNDERN; no cross-links)
    """
    import html as _html

    def slot_card(letter: str, lap_id: str, fields: dict):
        empty = not lap_id
        empty_cls = " empty" if empty else ""
        time_str = _html.escape(fields.get("time", "—:—.—"))
        track    = _html.escape(fields.get("track", "—"))
        lap_no   = _html.escape(fields.get("lap_no", "—"))
        bike     = _html.escape(fields.get("bike", "—"))
        driver   = _html.escape(fields.get("driver", "—"))
        local    = fields.get("local", False)
        # Button: empty → pulsing pick; filled → change
        if empty:
            btn = (
                f'<button type="button" class="cmp-tb-pick cmp-tb-pick-{letter}" '
                f'        data-slot="{letter}">'
                f'+ RUNDE {letter.upper()} WÄHLEN</button>'
            )
        else:
            btn = (
                f'<button type="button" class="cmp-tb-change" '
                f'        data-slot="{letter}">↻ ANDERE RUNDE LADEN</button>'
            )
        # Cross-links only for library laps (numeric id)
        is_numeric = lap_id.isdigit() if isinstance(lap_id, str) else False
        cross = ""
        if is_numeric:
            cross = (
                f'<a href="/analyze?lap_id={lap_id}" class="cmp-tb-cross">→ DATENVIEWER</a>'
                f'<a href="/coach?lap_id={lap_id}" class="cmp-tb-cross">→ AI COACH</a>'
            )
        local_badge = '<span class="cmp-tb-local">LOKAL</span>' if local else ''
        head_html = (
            f'<div class="cmp-tb-head">{local_badge}</div>' if local else ''
        )
        return (
            f'<div class="cmp-tb-card cmp-tb-card-{letter}{empty_cls}">'
            f'  {head_html}'
            f'  <div class="cmp-tb-time mono">{time_str}</div>'
            f'  <div class="cmp-tb-meta">'
            f'    <div class="cmp-tb-row"><span class="k">STRECKE</span><span class="v">{track}</span></div>'
            f'    <div class="cmp-tb-row"><span class="k">LAP</span><span class="v">{lap_no}</span></div>'
            f'    <div class="cmp-tb-row"><span class="k">BIKE</span><span class="v">{bike}</span></div>'
            f'    <div class="cmp-tb-row"><span class="k">FAHRER</span><span class="v">{driver}</span></div>'
            f'  </div>'
            f'  <div class="cmp-tb-actions">'
            f'    {btn}'
            f'    {cross}'
            f'  </div>'
            f'</div>'
        )

    return (
        f'<div class="cmp-toolbar" id="cmp-toolbar" '
        f'     data-a-lap-id="{_html.escape(str(a_lap_id))}" '
        f'     data-b-lap-id="{_html.escape(str(b_lap_id))}" '
        f'     data-a-track="{_html.escape(a_track)}" '
        f'     data-b-track="{_html.escape(b_track)}">'
        f'{slot_card("a", a_lap_id, a_fields)}'
        f'{slot_card("b", b_lap_id, b_fields)}'
        f'</div>'
        '<style>'
        '.cmp-toolbar{'
        ' display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:32px;'
        ' font-family:"JetBrains Mono",monospace;}'
        '.cmp-tb-card{background:#0a0a0a;border:1px solid #262626;padding:28px 24px;'
        ' display:grid;grid-template-columns:auto 1fr;gap:20px 28px;align-items:end;}'
        '.cmp-tb-card-a{border-top:3px solid #00d4ff}'
        '.cmp-tb-card-b{border-top:3px solid #ff3d00}'
        '.cmp-tb-head{grid-row:1;grid-column:1 / -1;display:flex;align-items:center;gap:10px;'
        ' margin-bottom:-8px}'
        '.cmp-tb-tag{font-family:"Bebas Neue",sans-serif;font-size:18px;letter-spacing:.06em;'
        ' padding:4px 10px;color:#000;display:inline-block}'
        '.cmp-tb-card-a .cmp-tb-tag{background:#00d4ff}'
        '.cmp-tb-card-b .cmp-tb-tag{background:#ff3d00}'
        '.cmp-tb-local{font-family:"JetBrains Mono",monospace;font-size:9px;color:#888;'
        ' letter-spacing:.15em;padding:3px 7px;border:1px solid #262626;text-transform:uppercase}'
        '.cmp-tb-time{font-family:"Bebas Neue",sans-serif;font-size:clamp(56px,7vw,88px);'
        ' line-height:.85;font-feature-settings:"tnum";letter-spacing:.01em;'
        ' grid-row:2;grid-column:1}'
        '.cmp-tb-card-a .cmp-tb-time{color:#00d4ff}'
        '.cmp-tb-card-b .cmp-tb-time{color:#ff3d00}'
        '.cmp-tb-card.empty .cmp-tb-time{color:#444}'
        '.cmp-tb-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));'
        ' gap:8px 20px;grid-row:2;grid-column:2}'
        '.cmp-tb-row{display:flex;flex-direction:column;gap:2px;min-width:0}'
        '.cmp-tb-row .k{font-size:10px;color:#888;letter-spacing:.15em;text-transform:uppercase}'
        '.cmp-tb-row .v{font-size:13px;color:#f5f5f0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'
        '.cmp-tb-card.empty .cmp-tb-row .v{color:#666}'
        '.cmp-tb-actions{grid-row:3;grid-column:1 / -1;display:flex;gap:10px;align-items:center;'
        ' flex-wrap:wrap;padding-top:18px;border-top:1px solid #262626}'
        '.cmp-tb-change{background:transparent;border:1px solid #262626;color:#a0a0a0;'
        ' font-family:"JetBrains Mono",monospace;font-size:11px;font-weight:500;'
        ' letter-spacing:.12em;padding:11px 18px;cursor:pointer;text-transform:uppercase;'
        ' transition:border-color .12s,color .12s}'
        '.cmp-tb-change:hover{border-color:#a0a0a0;color:#f5f5f0}'
        '.cmp-tb-pick{color:#000;border:none;'
        ' font-family:"JetBrains Mono",monospace;font-size:13px;font-weight:600;'
        ' letter-spacing:.12em;padding:14px 22px;cursor:pointer;text-transform:uppercase;}'
        '.cmp-tb-pick-a{background:#00d4ff;animation:cmp-pulse-a 2s ease-in-out infinite}'
        '.cmp-tb-pick-b{background:#ff3d00;animation:cmp-pulse-b 2s ease-in-out infinite}'
        '.cmp-tb-pick-a:hover{background:#1ee4ff;filter:brightness(1.1)}'
        '.cmp-tb-pick-b:hover{background:#ff5a1a}'
        '@keyframes cmp-pulse-a{0%,100%{box-shadow:0 0 0 0 rgba(0,212,255,.6)}'
        ' 50%{box-shadow:0 0 0 10px rgba(0,212,255,0)}}'
        '@keyframes cmp-pulse-b{0%,100%{box-shadow:0 0 0 0 rgba(255,61,0,.6)}'
        ' 50%{box-shadow:0 0 0 10px rgba(255,61,0,0)}}'
        '.cmp-tb-cross{color:#a0a0a0;text-decoration:none;font-size:10px;'
        ' letter-spacing:.15em;text-transform:uppercase;padding:11px 14px;'
        ' border:1px solid #262626;transition:color .12s,border-color .12s}'
        '.cmp-tb-cross:hover{color:#f5f5f0;border-color:#a0a0a0}'
        '@media (max-width:880px){.cmp-toolbar{grid-template-columns:1fr}'
        ' .cmp-tb-card{grid-template-columns:1fr;}'
        ' .cmp-tb-time{grid-row:2;grid-column:1;font-size:64px}'
        ' .cmp-tb-meta{grid-row:3;grid-column:1}'
        ' .cmp-tb-actions{grid-row:4}}'
        '</style>'
    )


def _build_compare_picker_modal():
    """The modal that lets the user re-pick a slot.

    Filters identical to the Datenviewer/Coach picker. Additional behavior:
    when opened for slot B and the toolbar has data-a-track set, the
    track filter pre-fills to that value (user can clear it).
    Selection navigates to /compare?a=N&b=M (one slot may be 0).
    """
    return _COMPARE_PICKER_MODAL


_COMPARE_PICKER_MODAL = r"""
<div class="lp-modal" id="lp-modal" hidden>
  <div class="lp-modal-box">
    <div class="lp-modal-head">
      <h3 id="lp-modal-title">RUNDE WÄHLEN</h3>
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
      <form method="POST" action="/compare" enctype="multipart/form-data" class="lp-upload-form" id="lp-upload-form">
        <input type="hidden" name="mode" value="single_upload">
        <input type="hidden" name="slot" id="lp-upload-slot" value="a">
        <input type="hidden" name="other_lap_id" id="lp-upload-other" value="">
        <div class="lp-upload-drop">
          <div class="lp-upload-icon">⇪</div>
          <div class="lp-upload-title">DATEI FÜR SLOT <span id="lp-upload-slot-label">A</span> WÄHLEN</div>
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
          <button type="submit" class="lp-upload-submit">UPLOAD →</button>
        </div>
      </form>
    </div>
  </div>
</div>
<style>
/* v21.3 — Picker accent colour follows the slot the modal was opened for.
   The trigger button's data-slot is mirrored to the .lp-modal-box and that
   drives --lp-accent / --lp-accent-hover / --lp-accent-glow via CSS. */
.lp-modal{position:fixed;inset:0;background:rgba(0,0,0,.72);
  display:flex;align-items:flex-start;justify-content:center;
  padding:48px 24px;z-index:1200;overflow-y:auto;backdrop-filter:blur(6px);}
.lp-modal[hidden]{display:none}
.lp-modal-box{
  /* Defaults to Slot A (cyan); overridden when data-slot="b" via selector below. */
  --lp-accent:#00d4ff;
  --lp-accent-hover:#1ee4ff;
  --lp-accent-glow:rgba(0,212,255,.06);
  --lp-accent-glow-strong:rgba(0,212,255,.2);
  --lp-accent-glow-soft:rgba(0,212,255,.05);
  background:#0a0a0a;border:1px solid #262626;
  width:min(1100px,100%);max-height:calc(100vh - 96px);
  display:flex;flex-direction:column;font-family:'Space Grotesk',sans-serif}
.lp-modal-box[data-slot="b"]{
  --lp-accent:#ff3d00;
  --lp-accent-hover:#ff5a1a;
  --lp-accent-glow:rgba(255,61,0,.06);
  --lp-accent-glow-strong:rgba(255,61,0,.2);
  --lp-accent-glow-soft:rgba(255,61,0,.05);
}
.lp-modal-head{display:flex;justify-content:space-between;align-items:center;
  padding:20px 28px;border-bottom:1px solid #262626;color:#f5f5f0}
.lp-modal-head h3{font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:.04em}
.lp-close{background:none;border:none;color:#a0a0a0;font-size:28px;
  cursor:pointer;width:36px;height:36px;line-height:1}
.lp-close:hover{color:#f5f5f0}
.lp-tabs{display:flex;gap:8px;padding:14px 20px 0;border-bottom:1px solid #262626;background:#141414}
.lp-tab{background:#0a0a0a;border:1px solid #262626;border-bottom:none;color:#a0a0a0;
  font-family:'Bebas Neue',sans-serif;font-size:18px;letter-spacing:.08em;
  padding:14px 28px;cursor:pointer;text-transform:uppercase;position:relative;top:1px;
  transition:background .12s,color .12s,border-color .12s}
.lp-tab:hover{color:#f5f5f0;border-color:#a0a0a0}
.lp-tab.active{background:var(--lp-accent);color:#000;border-color:var(--lp-accent);font-weight:600;box-shadow:0 -2px 0 0 var(--lp-accent)}
.lp-tab.active:hover{background:var(--lp-accent-hover);border-color:var(--lp-accent-hover)}
.lp-tab::before{content:'';display:inline-block;width:8px;height:8px;margin-right:10px;
  border-radius:50%;background:#888;vertical-align:middle;transition:background .12s}
.lp-tab.active::before{background:#000}
.lp-panel{flex:1 1 auto;display:flex;flex-direction:column;min-height:0;overflow:hidden;color:#f5f5f0}
.lp-panel[hidden]{display:none}
.lp-prefilter{display:flex;align-items:center;gap:12px;padding:12px 28px;background:var(--lp-accent-glow);
  border-bottom:1px solid var(--lp-accent-glow-strong);font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em}
.lp-prefilter[hidden]{display:none}
.lp-pf-label{color:#a0a0a0;text-transform:uppercase}
.lp-pf-value{color:var(--lp-accent);font-weight:500}
.lp-pf-clear{background:transparent;border:1px solid #262626;color:#a0a0a0;
  font-family:inherit;font-size:10px;letter-spacing:.1em;padding:4px 10px;cursor:pointer;text-transform:uppercase}
.lp-pf-clear:hover{border-color:#a0a0a0;color:#f5f5f0}
.lp-filter{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:12px;padding:20px 28px;border-bottom:1px solid #262626;background:#141414}
.lp-field{display:flex;flex-direction:column;gap:4px;min-width:0}
.lp-field.lp-span2{grid-column:span 2}
.lp-field label{font-family:'JetBrains Mono',monospace;font-size:9px;color:#888;letter-spacing:.15em;text-transform:uppercase}
.lp-field input,.lp-field select{background:#0a0a0a;border:1px solid #262626;color:#f5f5f0;
  font-family:'JetBrains Mono',monospace;font-size:12px;padding:8px 10px;outline:none}
.lp-field input:focus,.lp-field select:focus{border-color:var(--lp-accent)}
.lp-results{overflow-y:auto;padding:0 28px;flex:1 1 auto;min-height:200px;max-height:50vh}
.lp-results .lp-empty{padding:48px 16px;text-align:center;color:#a0a0a0;
  font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:.1em}
.lp-row{display:grid;grid-template-columns:90px minmax(0,1fr) minmax(0,1fr) minmax(0,1fr) 80px;
  gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid #262626;cursor:pointer}
.lp-row:hover{background:#141414}
.lp-row .lp-time{font-family:'JetBrains Mono',monospace;font-feature-settings:'tnum';
  font-size:18px;font-weight:500;color:var(--lp-accent)}
.lp-row .lp-meta{display:flex;flex-direction:column;gap:1px;min-width:0}
.lp-row .lp-meta .k{font-family:'JetBrains Mono',monospace;font-size:9px;color:#888;letter-spacing:.1em;text-transform:uppercase}
.lp-row .lp-meta .v{font-size:13px;color:#f5f5f0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lp-row .lp-meta .v.dim{color:#a0a0a0;font-style:italic}
/* v22.4 — Per-role channel-status icons (Compare picker). One inline
   SVG per registry role, grey if not assigned for this lap, green if
   assigned. SVGs use currentColor — wrapper .on/.off switches it.
   Same scheme as Coach + Datenviewer pickers. */
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
.lp-row .lp-no{font-family:'JetBrains Mono',monospace;font-size:11px;color:#a0a0a0;letter-spacing:.1em;text-align:right}
.lp-foot{padding:14px 28px;border-top:1px solid #262626;background:#141414;
  display:flex;justify-content:space-between;align-items:center;
  font-family:'JetBrains Mono',monospace;font-size:11px;color:#888;letter-spacing:.1em;text-transform:uppercase}
.lp-upload-form{padding:28px;display:flex;flex-direction:column;gap:20px;flex:1 1 auto;min-height:0;overflow-y:auto}
.lp-upload-drop{border:2px dashed #262626;padding:32px;text-align:center;
  display:flex;flex-direction:column;gap:8px;cursor:pointer;
  transition:border-color .15s,background .15s}
.lp-upload-drop:hover{border-color:var(--lp-accent);background:#141414}
.lp-upload-drop.has-file{border-color:var(--lp-accent);background:var(--lp-accent-glow-soft)}
.lp-upload-icon{font-size:48px;color:var(--lp-accent);line-height:1}
.lp-upload-title{font-family:'Bebas Neue',sans-serif;font-size:24px;letter-spacing:.05em}
.lp-upload-hint{font-family:'JetBrains Mono',monospace;font-size:10px;color:#888;letter-spacing:.1em}
.lp-upload-drop input[type="file"]{display:none}
.lp-upload-name{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--lp-accent);margin-top:8px;word-break:break-all}
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
.lp-upload-opt .k{font-family:'JetBrains Mono',monospace;font-size:10px;color:#888;letter-spacing:.15em;text-transform:uppercase}
.lp-upload-opt input{background:#141414;border:1px solid #262626;color:#f5f5f0;
  font-family:'JetBrains Mono',monospace;font-size:13px;padding:8px 10px;width:120px;outline:none}
.lp-upload-opt input:focus{border-color:var(--lp-accent)}
.lp-upload-actions{display:flex;justify-content:flex-end;padding-top:8px;border-top:1px solid #262626;position:sticky;bottom:0;background:#0a0a0a;padding-bottom:4px;margin-top:auto}
.lp-upload-submit{font-family:'Bebas Neue',sans-serif;font-size:20px;letter-spacing:.05em;
  background:var(--lp-accent);color:#000;border:none;padding:12px 28px;cursor:pointer}
.lp-upload-submit:hover{background:var(--lp-accent-hover)}
</style>
<script>
// ============================================================================
// Compare lap-picker — opens with data-slot attribute on the trigger button.
// Slot B pre-fills the track filter from data-a-track if present.
// Selection commits to /compare?a=N&b=M (keeps the other slot).
// ============================================================================
(function compareLapPicker(){
  const modal = document.getElementById('lp-modal');
  const btnClose = document.getElementById('lp-modal-close');
  const title = document.getElementById('lp-modal-title');
  if (!modal) return;

  let currentSlot = 'a';

  const tabs = modal.querySelectorAll('.lp-tab');
  tabs.forEach(t => t.addEventListener('click', () => {
    tabs.forEach(x => x.classList.toggle('active', x === t));
    const key = t.dataset.lpTab;
    document.getElementById('lp-panel-library').hidden = (key !== 'library');
    document.getElementById('lp-panel-upload').hidden  = (key !== 'upload');
  }));

  function getSlotData(slot){
    // Look up the toolbar lazily — in the empty SPA it's created by the
    // companion script after this IIFE runs.
    const toolbar = document.getElementById('cmp-toolbar');
    if (!toolbar) return {lapId: '', track: ''};
    return {
      // Keep lapId as a string — it might be "42" (library) or
      // "ad-<hex>" (ad-hoc upload token). Don't parseInt() or the
      // ad-hoc token gets clobbered to 0.
      lapId: toolbar.dataset[slot + 'LapId'] || '',
      track: toolbar.dataset[slot + 'Track'] || '',
    };
  }
  function openModal(slot){
    currentSlot = slot;
    title.textContent = (slot === 'a') ? 'RUNDE A WÄHLEN' : 'RUNDE B WÄHLEN';
    // v21.3 — propagate slot to the modal-box so its CSS variables pick the
    // right accent colour (A=cyan, B=rot).
    const box = modal.querySelector('.lp-modal-box');
    if (box) box.setAttribute('data-slot', slot);
    const slotInput = document.getElementById('lp-upload-slot');
    if (slotInput) slotInput.value = slot;
    const slotLabelEl = document.getElementById('lp-upload-slot-label');
    if (slotLabelEl) slotLabelEl.textContent = slot.toUpperCase();
    // Pre-filter: when picking the "other" slot and the already-loaded
    // slot has a track, default the track filter to it.
    const other = (slot === 'a') ? 'b' : 'a';
    const otherTrack = getSlotData(other).track;
    const otherLapId = getSlotData(other).lapId;
    const otherInput = document.getElementById('lp-upload-other');
    if (otherInput) otherInput.value = otherLapId ? String(otherLapId) : '';
    const trackSel = document.getElementById('lp-f-track');
    const pfBar = document.getElementById('lp-prefilter');
    const pfVal = document.getElementById('lp-pf-track');
    if (otherTrack){
      // Ensure the option exists (distinct list may not be loaded yet);
      // we add it lazily and select it.
      pfBar.hidden = false;
      pfVal.textContent = otherTrack;
      trackSel.dataset.prefilled = otherTrack;
    } else {
      pfBar.hidden = true;
      delete trackSel.dataset.prefilled;
      trackSel.value = '';
    }
    // Always switch back to library tab when opening — upload is the
    // secondary path. The tab can still be clicked once open.
    modal.querySelectorAll('.lp-tab').forEach(t =>
      t.classList.toggle('active', t.dataset.lpTab === 'library'));
    document.getElementById('lp-panel-library').hidden = false;
    document.getElementById('lp-panel-upload').hidden  = true;
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    loadLapsDebounced(true);
    setTimeout(() => document.getElementById('lp-f-search')?.focus(), 30);
  }
  function closeModal(){
    modal.hidden = true;
    document.body.style.overflow = '';
  }
  btnClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', (e) => {
    if (!modal.hidden && e.key === 'Escape') closeModal();
  });
  document.getElementById('lp-pf-clear').addEventListener('click', () => {
    document.getElementById('lp-prefilter').hidden = true;
    const sel = document.getElementById('lp-f-track');
    delete sel.dataset.prefilled;
    sel.value = '';
    loadLapsDebounced(true);
  });

  // Event delegation: works for buttons present at load AND for any
  // dynamically-rendered ones. Three button shapes can open the picker:
  //   .cmp-tb-pick    — empty slot in the toolbar
  //   .cmp-tb-change  — filled slot in the toolbar (↻ ÄNDERN)
  //   [data-cmp-pick] — legacy hook (kept for compatibility)
  document.addEventListener('click', (e) => {
    const pick = e.target.closest('.cmp-tb-pick');
    if (pick){ openModal(pick.dataset.slot); return; }
    const tb = e.target.closest('.cmp-tb-change');
    if (tb){ openModal(tb.dataset.slot); return; }
    const legacy = e.target.closest('[data-cmp-pick]');
    if (legacy){ openModal(legacy.dataset.cmpPick); return; }
  });

  let loadDebounce = null, distinctLoaded = false;
  // v22.4 — Cached channel-role registry for the per-row status icons.
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
      // If user manually changed the track filter, drop the prefilter pill
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
      // Ensure the preferred value exists as an option
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
      // Even if distinct is already loaded, re-apply the prefilter
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
      // v22.4 — Per-role status icons. role.icon is an inline SVG with
      // currentColor; wrapper .on/.off colours it grey or green. Empty
      // string when the lap has no extra channels.
      function chDots(lp){
        const ex = +(lp.extras_count || 0);
        if (ex === 0) return '';
        const assigned = new Set(lp.assigned_role_ids || []);
        const parts = ['<span class="lp-ch-dots" aria-label="Standardkanal-Zuordnung">'];
        for (const role of (rolesRegistry || [])){
          const on = assigned.has(role.id);
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
            <div class="v" style="font-size:12px;color:#a0a0a0;font-family:JetBrains Mono">${escHtml(lp.original_filename || '')}</div>
            ${chDots(lp)}</div>
          <div class="lp-no">LAP ${lp.lap_number}</div>
        </div>`;
      });
      box.innerHTML = html;
      box.querySelectorAll('.lp-row').forEach(row => {
        row.addEventListener('click', () => {
          const id = parseInt(row.dataset.lapId, 10);
          if (!id) return;
          // Determine the other slot's lap_id to keep
          const other = (currentSlot === 'a') ? 'b' : 'a';
          const otherId = getSlotData(other).lapId;
          const params = new URLSearchParams();
          if (currentSlot === 'a'){
            params.set('a', id);
            if (otherId) params.set('b', otherId);
          } else {
            if (otherId) params.set('a', otherId);
            params.set('b', id);
          }
          window.location.href = '/compare?' + params.toString();
        });
      });
    } catch (e){
      box.innerHTML = '<div class="lp-empty">FEHLER: ' + escHtml(e.message || e) + '</div>';
    }
  }

  // Upload tab — drop zone visuals
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
</script>
"""

