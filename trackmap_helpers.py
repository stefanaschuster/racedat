"""Shared JavaScript helpers for trackmap features:

- Web-Mercator tile math for Esri World Imagery
- Spinner overlay
- Zoom (mouse wheel, pinch, dblclick reset) and pan (drag) via viewBox

The Python side exposes these as string constants. Each consumer JS module
embeds them once and wraps its trackMap-specific render logic around them.

Usage pattern in the JS module:

  // After computing svg, W, H, proj (lat,lon → {x,y}), latMin/latMax/etc:
  const tile = makeTileLayer({ svg, W, H, proj,
      latMin, latMax, lonMin, lonMax, padding: 0.10 });

  function rerender(){
    let html = '';
    if (tile.active) html += tile.buildLayer();
    // ... your track lines, markers, cursor group ...
    svg.innerHTML = html;
    tile.bindLoad(svg);  // attaches load listeners to <image> elements
  }
  tile.onChange = rerender;

  const zoomCtl = makeZoomPan({ svg, W, H, onPan: ()=>{}, onZoom: ()=>{} });
  // dblclick on svg resets; wheel/pinch zoom; drag pans.

The "active" state, attribution element toggling, and re-rendering on
mapview-on is the consumer's responsibility.
"""

# ---------------------------------------------------------------------------
# JS code injected into each consumer template.
# ---------------------------------------------------------------------------

TILE_HELPERS_JS = r"""
// ===== v21.23+ Shared tile helpers (Esri / MapTiler World Imagery) =====
// + v21.24: Spinner overlay & zoom/pan via viewBox.
// + v21.26: MapTiler-Provider mit Key (vorher: Esri ohne Key). Der Key wird
//   beim Page-Build vom Server in window.TILE_PROVIDER injiziert. Ist der
//   Key leer, exportiert makeTileLayer kein aktivierbares tile-Objekt
//   (toggle.disabled = true); der UI-Layer blendet den Mapview-Button dann aus.

function tileProviderUrl(z, x, y){
  const p = window.TILE_PROVIDER || {};
  if (!p.key) return null;
  // MapTiler-XYZ: /tiles/satellite-v2/{z}/{x}/{y}.jpg?key=...
  // (vs Esri-Reihenfolge {z}/{y}/{x} und ohne Key)
  return `https://api.maptiler.com/tiles/${encodeURIComponent(p.tileset || 'satellite-v2')}/${z}/${x}/${y}.${p.ext || 'jpg'}?key=${encodeURIComponent(p.key)}`;
}
function tileProviderAttributionHTML(){
  // Wird einmal pro Trackmap im Markup hingeschrieben; sichtbar erst wenn
  // Mapview aktiv (display-toggle vom UI-Layer).
  const p = window.TILE_PROVIDER || {};
  if (p.attribution_html) return p.attribution_html;
  return 'Imagery © <a href="https://www.maptiler.com" target="_blank" rel="noopener">MapTiler</a>'
       + ' © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
}
function tileProviderAvailable(){
  return !!((window.TILE_PROVIDER || {}).key);
}

// v21.26 — Attribution-Container werden zur Laufzeit vom Provider-Snippet
// befüllt. So bleibt die Attribution single source of truth (Default-Wert
// im tile_provider_js() in Python, override im Frontend möglich falls jemand
// TILE_PROVIDER.attribution_html überschreibt).
(function(){
  function fill(){
    const html = tileProviderAttributionHTML();
    document.querySelectorAll('.map-attribution').forEach(el => {
      if (!el.innerHTML.trim()) el.innerHTML = html;
    });
  }
  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', fill, { once: true });
  } else {
    fill();
  }
})();

function makeTileLayer(opts){
  // opts: { svg, W, H, proj, latMin, latMax, lonMin, lonMax, padding=0.10 }
  const TILE_SIZE = 256;
  const PAD = opts.padding != null ? opts.padding : 0.10;
  const latRange = opts.latMax - opts.latMin;
  const lonRange = opts.lonMax - opts.lonMin;
  const tLatMin = opts.latMin - latRange * PAD;
  const tLatMax = opts.latMax + latRange * PAD;
  const tLonMin = opts.lonMin - lonRange * PAD;
  const tLonMax = opts.lonMax + lonRange * PAD;

  function lon2wx(lon, z){ return (lon + 180)/360 * Math.pow(2,z); }
  function lat2wy(lat, z){
    const s = Math.sin(lat * Math.PI/180);
    return (0.5 - Math.log((1+s)/(1-s)) / (4*Math.PI)) * Math.pow(2,z);
  }
  function wx2lon(wx, z){ return wx/Math.pow(2,z)*360 - 180; }
  function wy2lat(wy, z){
    const n = Math.PI - 2*Math.PI*wy/Math.pow(2,z);
    return 180/Math.PI * Math.atan(0.5*(Math.exp(n) - Math.exp(-n)));
  }

  // Pick zoom level so the padded bbox fits in roughly W..1.5*W world-pixels.
  // baseZoom is the level used at viewBox-zoom = 1. When the user zooms in
  // (viewBoxZoom > 1), we step up to provide sharper imagery.
  function pickZoom(extraSteps){
    const target = 1.5;
    for (let z = 19; z >= 1; z--){
      const wxMin = lon2wx(tLonMin, z), wxMax = lon2wx(tLonMax, z);
      const wyMin = lat2wy(tLatMax, z), wyMax = lat2wy(tLatMin, z);
      const pxW = (wxMax - wxMin) * TILE_SIZE;
      const pxH = (wyMax - wyMin) * TILE_SIZE;
      if (pxW <= opts.W * target && pxH <= opts.H * target){
        return Math.min(19, z + (extraSteps|0));
      }
    }
    return 1;
  }
  const baseZoom = pickZoom(0);

  let active = false;
  let zoomBoost = 0;  // additional z-levels when user zooms in

  function buildLayer(){
    if (!tileProviderAvailable()) return '';  // kein Key → keine Tiles
    const z = Math.min(19, baseZoom + zoomBoost);
    const txMin = Math.floor(lon2wx(tLonMin, z));
    const txMax = Math.floor(lon2wx(tLonMax, z));
    const tyMin = Math.floor(lat2wy(tLatMax, z));
    const tyMax = Math.floor(lat2wy(tLatMin, z));
    let out = '';
    for (let tx = txMin; tx <= txMax; tx++){
      for (let ty = tyMin; ty <= tyMax; ty++){
        const nwLon = wx2lon(tx, z),     nwLat = wy2lat(ty, z);
        const seLon = wx2lon(tx + 1, z), seLat = wy2lat(ty + 1, z);
        const nw = opts.proj(nwLat, nwLon), se = opts.proj(seLat, seLon);
        const x = nw.x, y = nw.y;
        const w = se.x - nw.x, h = se.y - nw.y;
        const url = tileProviderUrl(z, tx, ty);
        out += `<image href="${url}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}" preserveAspectRatio="none"/>`;
      }
    }
    return `<g class="track-tiles" opacity="0.85">${out}</g>`;
  }

  // Spinner overlay management. spinnerHost is the .map-wrap (or whatever
  // wraps the svg). Spinner is shown while any <image> is still loading;
  // hidden once all loaded or errored.
  let spinnerEl = null;
  let pendingLoads = 0;
  let loadGen = 0;

  function ensureSpinner(host){
    if (spinnerEl && spinnerEl.parentNode === host) return spinnerEl;
    spinnerEl = host.querySelector(':scope > .tm-spinner');
    if (!spinnerEl){
      spinnerEl = document.createElement('div');
      spinnerEl.className = 'tm-spinner';
      spinnerEl.innerHTML = '<div class="tm-spinner-ring"></div>';
      spinnerEl.style.display = 'none';
      host.appendChild(spinnerEl);
    }
    return spinnerEl;
  }
  function showSpinner(host){ ensureSpinner(host).style.display = ''; }
  function hideSpinner(){
    if (spinnerEl) spinnerEl.style.display = 'none';
  }

  function bindLoadEvents(host){
    const gen = ++loadGen;
    const imgs = opts.svg.querySelectorAll('g.track-tiles image');
    if (!imgs.length){ hideSpinner(); return; }
    pendingLoads = imgs.length;
    showSpinner(host);
    imgs.forEach(img => {
      const done = () => {
        if (gen !== loadGen) return;
        pendingLoads--;
        if (pendingLoads <= 0) hideSpinner();
      };
      // Native SVGImageElement supports load/error.
      img.addEventListener('load',  done, { once: true });
      img.addEventListener('error', done, { once: true });
    });
    // Safety: if browser already has all images cached, the load event may
    // have fired before we attached. Force-check after a tick.
    setTimeout(() => {
      if (gen !== loadGen) return;
      let stillLoading = 0;
      imgs.forEach(img => {
        // SVG <image> doesn't have .complete; check if it has natural width
        // exposed (Chromium does via image.getBBox or via getBoundingClientRect width).
        // Cheap heuristic: nothing fires after timeout => assume done.
      });
      if (stillLoading === 0){ hideSpinner(); }
    }, 8000);  // hard timeout
  }

  return {
    get active(){ return active; },
    set active(v){ active = !!v; },
    get baseZoom(){ return baseZoom; },
    get zoomBoost(){ return zoomBoost; },
    setZoomBoost(b){ zoomBoost = Math.max(0, Math.min(4, b|0)); },
    buildLayer,
    bindLoadEvents,
    showSpinner, hideSpinner, ensureSpinner,
  };
}


// ===== Zoom & Pan via viewBox =====
// Constraints: vbZoom in [1, maxVbZoom]. At vbZoom=1 the full original
// viewBox is shown; at vbZoom>1 we narrow viewBox by 1/vbZoom around a
// center (cx, cy). cx/cy clamp so the view stays inside the original.
function makeZoomPan(opts){
  // opts: { svg, W, H, onChange (called after every viewBox update),
  //         minZoom=1, maxZoom=8 }
  const W = opts.W, H = opts.H;
  const minZ = opts.minZoom || 1;
  const maxZ = opts.maxZoom || 8;
  let vbZoom = 1;
  let cx = W/2, cy = H/2;

  function applyViewBox(){
    const w = W / vbZoom, h = H / vbZoom;
    // Clamp center so view stays inside [0,W]x[0,H]
    const hx = w/2, hy = h/2;
    cx = Math.max(hx, Math.min(W - hx, cx));
    cy = Math.max(hy, Math.min(H - hy, cy));
    const x = cx - hx, y = cy - hy;
    opts.svg.setAttribute('viewBox', `${x.toFixed(2)} ${y.toFixed(2)} ${w.toFixed(2)} ${h.toFixed(2)}`);
    if (opts.onChange) opts.onChange({ zoom: vbZoom, cx, cy });
  }

  function svgPointFromClient(clientX, clientY){
    // viewBox-basierte Inverse. Robust ohne createSVGPoint/getScreenCTM
    // (existieren in JSDOM nicht). Funktioniert in modernen Browsern.
    const vb = opts.svg.getAttribute('viewBox');
    let vx = 0, vy = 0, vw = opts.W, vh = opts.H;
    if (vb){
      const m = vb.trim().split(/[ ,]+/).map(parseFloat);
      if (m.length === 4 && m.every(Number.isFinite)){
        vx = m[0]; vy = m[1]; vw = m[2]; vh = m[3];
      }
    }
    const rect = opts.svg.getBoundingClientRect();
    if (rect && rect.width > 0 && rect.height > 0){
      return {
        x: vx + (clientX - rect.left) * vw / rect.width,
        y: vy + (clientY - rect.top)  * vh / rect.height,
      };
    }
    // Fallback (JSDOM ohne Layout, headless-Test): zentriere auf viewBox.
    return { x: vx + vw / 2, y: vy + vh / 2 };
  }

  function zoomAt(clientX, clientY, factor){
    const before = svgPointFromClient(clientX, clientY);
    if (!before) return;
    const newZ = Math.max(minZ, Math.min(maxZ, vbZoom * factor));
    if (newZ === vbZoom) return;
    vbZoom = newZ;
    // v21.27: Vorher wurde "after" mit der noch alten viewBox berechnet —
    // dadurch war before==after und das Zoom-around-Cursor war effektiv ein
    // Zoom-around-Center. Jetzt schreiben wir die viewBox SOFORT mit dem neuen
    // Zoom, damit svgPointFromClient die NEUE viewBox liest.
    const w = W / vbZoom, h = H / vbZoom;
    const hx = w/2, hy = h/2;
    const tmpCx = Math.max(hx, Math.min(W - hx, cx));
    const tmpCy = Math.max(hy, Math.min(H - hy, cy));
    opts.svg.setAttribute('viewBox',
      `${(tmpCx - hx).toFixed(2)} ${(tmpCy - hy).toFixed(2)} ${w.toFixed(2)} ${h.toFixed(2)}`);
    const after = svgPointFromClient(clientX, clientY);
    if (after){
      cx += before.x - after.x;
      cy += before.y - after.y;
    }
    applyViewBox();
  }

  function reset(){
    vbZoom = 1;
    cx = W/2; cy = H/2;
    applyViewBox();
  }

  // ----- Wheel zoom -----
  let dragging = false;
  let dragStartX = 0, dragStartY = 0;
  let dragMoved = false;
  let dragLastX = 0, dragLastY = 0;

  opts.svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : (1/1.15);
    zoomAt(e.clientX, e.clientY, factor);
  }, { passive: false });
  // v21.27 — Manche Browser-Setups liefern wheel-events nicht zuverlässig auf
  // SVG-Elementen. Zusätzlich auch am Wrapper registrieren — der wheel-Event
  // bubbelt nicht aufwärts wenn das innere e.preventDefault macht, aber wenn
  // der innere Listener nie feuert, fängt der äußere ihn ab.
  if (opts.svg.parentElement){
    opts.svg.parentElement.addEventListener('wheel', (e) => {
      // Nur wenn das Event noch nicht "defaulted" wurde (vom inneren Listener)
      if (e.defaultPrevented) return;
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : (1/1.15);
      zoomAt(e.clientX, e.clientY, factor);
    }, { passive: false });
  }

  // ----- Drag pan -----
  opts.svg.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    dragMoved = false;
    dragStartX = e.clientX; dragStartY = e.clientY;
    dragLastX  = e.clientX; dragLastY  = e.clientY;
  });
  // Pixel→svg-Skalierung: pro Client-Pixel sind das vw/rect.width svg-Einheiten
  // in x bzw. vh/rect.height in y. Funktioniert ohne CTM (für JSDOM).
  function clientToSvgScale(){
    const rect = opts.svg.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return null;
    const vb = opts.svg.getAttribute('viewBox');
    let vw = opts.W, vh = opts.H;
    if (vb){
      const m = vb.trim().split(/[ ,]+/).map(parseFloat);
      if (m.length === 4 && m.every(Number.isFinite)){
        vw = m[2]; vh = m[3];
      }
    }
    return { sx: vw / rect.width, sy: vh / rect.height };
  }

  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - dragLastX;
    const dy = e.clientY - dragLastY;
    if (!dragMoved){
      const totDx = e.clientX - dragStartX, totDy = e.clientY - dragStartY;
      if (totDx*totDx + totDy*totDy < 9) return;  // 3px threshold
      dragMoved = true;
    }
    const s = clientToSvgScale();
    if (!s) return;
    cx -= dx * s.sx;
    cy -= dy * s.sy;
    dragLastX = e.clientX; dragLastY = e.clientY;
    applyViewBox();
  });
  window.addEventListener('mouseup', () => {
    dragging = false;
    // dragMoved stays true for the upcoming click swallow
    setTimeout(() => { dragMoved = false; }, 0);
  });

  // ----- Double-click reset -----
  opts.svg.addEventListener('dblclick', (e) => {
    e.preventDefault();
    reset();
  });

  // ----- Touch pinch / pan -----
  // v21.29 — komplett neu für Touch-only Devices:
  //  • 2-Finger-Gesten zoomen UND pannen gleichzeitig (Pinch + Drag)
  //  • 1-Finger-Drag pannt (NUR wenn schon gezoomt, sonst kollidiert mit
  //    dem normalen Tap-um-Cursor-zu-setzen Pfad)
  //  • Doppel-Tap (zwei Taps < 300ms apart, < 30px) resettet wie Doppelklick
  //  • Pinch-Math korrigiert: viewBox wird zwischen Zoom und after-Berechnung
  //    aktualisiert (wie zoomAt seit v21.27)
  let touchStartDist = 0;
  let touchStartZoom = 1;
  let touchStartMidClient = null;  // {clientX, clientY} — Pinch-Mittelpunkt zum Start
  let touchStartCenterSvg = null;  // svg-Punkt am Pinch-Mittelpunkt zum Start
  let panTouchLastX = 0, panTouchLastY = 0;
  let panTouchActive = false;
  let lastTapTime = 0, lastTapX = 0, lastTapY = 0;

  function touchDist(a, b){
    const dx = a.clientX - b.clientX, dy = a.clientY - b.clientY;
    return Math.sqrt(dx*dx + dy*dy);
  }
  function touchMid(a, b){
    return { clientX: (a.clientX + b.clientX)/2, clientY: (a.clientY + b.clientY)/2 };
  }

  opts.svg.addEventListener('touchstart', (e) => {
    if (e.touches.length === 2){
      e.preventDefault();
      touchStartDist = touchDist(e.touches[0], e.touches[1]);
      touchStartZoom = vbZoom;
      touchStartMidClient = touchMid(e.touches[0], e.touches[1]);
      touchStartCenterSvg = svgPointFromClient(touchStartMidClient.clientX, touchStartMidClient.clientY);
      panTouchActive = false;
    } else if (e.touches.length === 1){
      // Doppel-Tap als Reset erkennen (zwei Taps < 300ms apart, < 30px).
      const now = Date.now();
      const tx = e.touches[0].clientX, ty = e.touches[0].clientY;
      if (now - lastTapTime < 300 &&
          Math.abs(tx - lastTapX) < 30 && Math.abs(ty - lastTapY) < 30){
        e.preventDefault();
        reset();
        lastTapTime = 0;
        return;
      }
      lastTapTime = now; lastTapX = tx; lastTapY = ty;
      // 1-Finger-Pan startet nur wenn schon gezoomt (sonst Tap = Cursor-Set)
      if (vbZoom > 1.01){
        panTouchActive = true;
        panTouchLastX = tx;
        panTouchLastY = ty;
      }
    }
  }, { passive: false });

  opts.svg.addEventListener('touchmove', (e) => {
    if (e.touches.length === 2){
      e.preventDefault();
      const d = touchDist(e.touches[0], e.touches[1]);
      if (touchStartDist <= 0) return;
      const ratio = d / touchStartDist;
      const newZ = Math.max(minZ, Math.min(maxZ, touchStartZoom * ratio));
      const midNow = touchMid(e.touches[0], e.touches[1]);
      // Zoom-Faktor anwenden, viewBox SOFORT setzen (siehe zoomAt-Fix v21.27)
      vbZoom = newZ;
      const w = W / vbZoom, h = H / vbZoom;
      const hx = w/2, hy = h/2;
      const tmpCx = Math.max(hx, Math.min(W - hx, cx));
      const tmpCy = Math.max(hy, Math.min(H - hy, cy));
      opts.svg.setAttribute('viewBox',
        `${(tmpCx - hx).toFixed(2)} ${(tmpCy - hy).toFixed(2)} ${w.toFixed(2)} ${h.toFixed(2)}`);
      // Jetzt mit NEUER viewBox: wo ist der Start-Mittelpunkt-SVG-Punkt jetzt?
      const after = svgPointFromClient(midNow.clientX, midNow.clientY);
      if (touchStartCenterSvg && after){
        cx += touchStartCenterSvg.x - after.x;
        cy += touchStartCenterSvg.y - after.y;
      }
      applyViewBox();
    } else if (e.touches.length === 1 && panTouchActive){
      e.preventDefault();
      const dx = e.touches[0].clientX - panTouchLastX;
      const dy = e.touches[0].clientY - panTouchLastY;
      const s = clientToSvgScale();
      if (s){
        cx -= dx * s.sx;
        cy -= dy * s.sy;
      }
      panTouchLastX = e.touches[0].clientX;
      panTouchLastY = e.touches[0].clientY;
      applyViewBox();
    }
  }, { passive: false });

  opts.svg.addEventListener('touchend', () => {
    panTouchActive = false;
  });

  // v21.29 — Zoom-Buttons-API: zoomIn/zoomOut/reset werden vom UI-Layer
  // an die Touch-Buttons gehängt. Zoomt um den Bildmittelpunkt.
  function zoomIn(){
    const rect = opts.svg.getBoundingClientRect();
    const cxClient = rect.left + rect.width / 2;
    const cyClient = rect.top + rect.height / 2;
    zoomAt(cxClient, cyClient, 1.5);
  }
  function zoomOut(){
    const rect = opts.svg.getBoundingClientRect();
    const cxClient = rect.left + rect.width / 2;
    const cyClient = rect.top + rect.height / 2;
    zoomAt(cxClient, cyClient, 1/1.5);
  }

  // v21.29 — Buttons-Overlay automatisch ins parent-Element einhängen.
  // Verhindert dass die UI-Templates jeweils einzeln Markup pflegen müssen.
  function attachButtons(){
    const parent = opts.svg.parentElement;
    if (!parent) return;
    // Schon vorhanden? (mehrfacher makeZoomPan-Aufruf)
    if (parent.querySelector(':scope > .tm-zoom-controls')) return;
    // Parent muss position:relative haben damit absolute-Children funktionieren.
    // Wenn das CSS das nicht ohnehin schon setzt, setzen wir es zumindest hier
    // als Inline-Style. (Compare/Analyze haben .map-wrap mit position:relative;
    // Coach hat das via .brake-trackmap-wrap{position:relative} im CSS.)
    const cs = (parent.ownerDocument.defaultView || window).getComputedStyle(parent);
    if (cs.position === 'static'){
      parent.style.position = 'relative';
    }
    const wrap = parent.ownerDocument.createElement('div');
    wrap.className = 'tm-zoom-controls';
    wrap.innerHTML =
      '<button type="button" class="tm-zoom-btn" data-act="in" aria-label="Reinzoomen" title="Reinzoomen">+</button>' +
      '<button type="button" class="tm-zoom-btn" data-act="out" aria-label="Rauszoomen" title="Rauszoomen">−</button>' +
      '<button type="button" class="tm-zoom-btn" data-act="reset" aria-label="Reset" title="Reset">↺</button>';
    parent.appendChild(wrap);

    const btnIn    = wrap.querySelector('[data-act="in"]');
    const btnOut   = wrap.querySelector('[data-act="out"]');
    const btnReset = wrap.querySelector('[data-act="reset"]');

    function updateState(){
      // Bei maxZoom: + deaktivieren. Bei minZoom (zoom=1): − und ↺ deaktivieren.
      btnIn.disabled    = (vbZoom >= maxZ - 0.001);
      btnOut.disabled   = (vbZoom <= minZ + 0.001);
      btnReset.disabled = (vbZoom <= minZ + 0.001);
    }
    btnIn.addEventListener('click', (e) => { e.stopPropagation(); zoomIn();  updateState(); });
    btnOut.addEventListener('click',(e) => { e.stopPropagation(); zoomOut(); updateState(); });
    btnReset.addEventListener('click',(e)=>{ e.stopPropagation(); reset();   updateState(); });
    // Wheel/Pinch/Doppelklick ändern auch den Zustand — über onChange hooken.
    const prevOnChange = opts.onChange;
    opts.onChange = function(state){
      updateState();
      if (prevOnChange) prevOnChange(state);
    };
    updateState();
  }
  attachButtons();

  return {
    get zoom(){ return vbZoom; },
    reset, zoomIn, zoomOut,
    didDrag(){ return dragMoved; },
  };
}
"""


# ---------------------------------------------------------------------------
# CSS for spinner. Keep small; placed next to existing trackmap CSS.
# ---------------------------------------------------------------------------

TILE_SPINNER_CSS = r"""
/* v21.24 — Spinner overlay shown while tiles are loading */
.tm-spinner{
  position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  background:rgba(10,10,10,.35);pointer-events:none;z-index:3;
}
.tm-spinner-ring{
  width:48px;height:48px;border:3px solid rgba(245,245,240,.18);
  border-top-color:#fff;border-radius:50%;
  animation: tm-spin .9s linear infinite;
}
@keyframes tm-spin { to { transform: rotate(360deg); } }
/* v21.27 — Cursor + touch-action für ALLE Trackmap-SVGs.
   Vorher nur .map-svg → Coach-Trackmaps (.brake-trackmap, .accel-trackmap)
   hatten kein touch-action:none und konnten nicht gepincht/gepannt werden. */
.map-svg, .brake-trackmap, .accel-trackmap{cursor:crosshair;touch-action:none}
.map-svg:active, .brake-trackmap:active, .accel-trackmap:active{cursor:grabbing}

/* v21.25 — Single Mapview-Toggle (vorher zwei-Optionen seg-switch)
   v22.0 — Hellerer Rahmen (#262626 → #4a4a4a) und Textfarbe (#a0a0a0 → #c8c8c8)
   für inaktive Buttons, damit sie besser sichtbar sind. Aktiv-Style (weißer
   Fill, schwarzer Text) unverändert. */
.tm-bg-btn{
  font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.15em;
  background:transparent;border:1px solid #4a4a4a;color:#c8c8c8;
  padding:7px 14px;cursor:pointer;text-transform:uppercase;
  display:inline-flex;align-items:center;gap:8px;
  transition:border-color .12s,color .12s,background .12s;
}
.tm-bg-btn:hover{border-color:#f5f5f0;color:#f5f5f0}
.tm-bg-btn.active{background:#f5f5f0;color:#000;border-color:#f5f5f0;font-weight:600}
.tm-bg-btn .tm-bg-dot{
  width:8px;height:8px;border-radius:50%;background:#262626;
  border:1px solid currentColor;
}
.tm-bg-btn.active .tm-bg-dot{background:#000;border-color:#000}
/* v21.26 — Wenn kein Tile-Provider konfiguriert ist (kein Key im config.json),
   bleibt der Button sichtbar aber inaktiv. So sieht der User dass die
   Funktion existiert, weiß aber dass sie aktuell nicht verfügbar ist.
   v21.27 fix: vorher display:none — das hat die Buttons unsichtbar gemacht
   wenn die config.json gefehlt hat, was wie ein Bug wirkte. */
.tm-bg-btn.tm-bg-disabled{
  opacity:.4;cursor:not-allowed;pointer-events:none;
}

/* v21.29 — Zoom-Buttons-Overlay direkt auf der Trackmap.
   Linke untere Ecke, drei kleine Buttons: +, -, ↺. Touch-freundlich (44px).
   Werden vom JS-Helper (makeZoomPan) automatisch ins parent-Element des SVG
   eingehängt sobald die Trackmap initialisiert ist. */
.tm-zoom-controls{
  position:absolute;left:10px;bottom:10px;z-index:4;
  display:flex;flex-direction:column;gap:4px;
}
.tm-zoom-btn{
  width:36px;height:36px;border:1px solid rgba(245,245,240,.4);
  background:rgba(10,10,10,.6);color:#f5f5f0;
  font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:600;
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  padding:0;line-height:1;border-radius:2px;
  transition:background .12s,border-color .12s;
  -webkit-tap-highlight-color:transparent;
  touch-action:manipulation;
}
.tm-zoom-btn:hover,.tm-zoom-btn:active{
  background:rgba(245,245,240,.15);border-color:#f5f5f0;
}
.tm-zoom-btn:disabled{
  opacity:.35;cursor:not-allowed;
}
"""


# ---------------------------------------------------------------------------
# Server-side helper: produce the small <script> snippet that sets
# window.TILE_PROVIDER before the rest of the JS runs. Keep this in lockstep
# with tileProviderUrl() / tileProviderAttributionHTML() in TILE_HELPERS_JS.
# ---------------------------------------------------------------------------

import json as _json

def tile_provider_js(maptiler_key: str) -> str:
    """Return a tiny <script> body that sets window.TILE_PROVIDER.

    Pass an empty string for `maptiler_key` to disable Mapview entirely
    (the Mapview button gets the .tm-bg-disabled class via the Python
    template substitution).
    """
    cfg = {
        "key":     (maptiler_key or "").strip(),
        "tileset": "satellite-v2",
        "ext":     "jpg",
        "attribution_html":
            'Imagery © <a href="https://www.maptiler.com" target="_blank" rel="noopener">MapTiler</a>'
            ' © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
    }
    return "window.TILE_PROVIDER = " + _json.dumps(cfg, separators=(",", ":")) + ";"


def tile_provider_button_class(maptiler_key: str) -> str:
    """Return the extra CSS class for the Mapview button(s)."""
    return "" if (maptiler_key or "").strip() else "tm-bg-disabled"
