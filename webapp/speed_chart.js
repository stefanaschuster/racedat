// ============================================================================
// speed_chart.js — Geteilter Multi-Channel-Chart für Datenviewer und Coach.
//
// v21.46 — Aus report_single.py extrahiert. Verschiedene Instanzen
// (Datenviewer-Section-02, Coach-Bremsen-Tab, Coach-Beschleunigung-Tab,
// Coach-Elektronik-Tab) konfigurieren über einen Config-Param eigene
// DOM-IDs, Daten, Vorselektion und Cursor-Sync-Callbacks.
//
// USAGE
// -----
// const chart = window.createSpeedChart({
//   data: {
//     distance: [...], speed: [...],
//     extras: [{id, name, unit, color, data, min, max, mean}, ...],
//     speedUnit: 'km/h',                 // optional, default 'km/h'
//   },
//   ids: {
//     svg:     'speed-chart',            // SVG element id
//     legend:  'chart-legend',           // legend container id
//     badge:   'active-chan-count',      // button badge slot id
//     zoomBtn: 'btn-zoom-reset',         // zoom reset button id
//     picker: {                          // channel picker modal IDs (optional)
//       btnOpen:  'btn-pick-channels',
//       modal:    'ch-modal',
//       body:     'ch-table-body',
//       hint:     'ch-modal-hint',
//       search:   'ch-search',
//       btnClose: 'ch-modal-close',
//       btnApply: 'ch-apply',
//       btnClear: 'ch-clear',
//     },
//   },
//   initialActiveExtraIds: ['phi_lean', 'tp_2'],  // pre-selected channels
//   initialSpeedActive: true,
//   onCursor:    (idx, sticky) => {...},    // cursor moved (hover/click)
//   onClearLive: () => {...},               // live cursor cleared
//   externalStickyIdx: () => -1,            // returns global sticky index
// });
//
// Returns:
//   { drawCursor(idx), getActiveExtras(), isSpeedActive(), destroy() }
//
// Multi-instance contract: each chart's clipPath gets a unique ID derived
// from the SVG element id, so multiple charts on the same page don't clash.
// ============================================================================
(function(){
  'use strict';

  function createSpeedChart(cfg){
    cfg = cfg || {};
    const data = cfg.data || {};
    const ids = cfg.ids || {};
    const picker = ids.picker || {};
    const onCursor    = cfg.onCursor    || function(){};
    const onClearLive = cfg.onClearLive || function(){};
    const onChannelChange = cfg.onChannelChange || function(){};
    const externalStickyIdx = cfg.externalStickyIdx || function(){ return -1; };
    // 'external': Datenviewer-Mode. onCursor entscheidet sticky/non-sticky,
    //   externer Code muss drawCursor zurückrufen (siehe report_single.py
    //   setCursor → trackMap.drawCursor + speedChart.drawCursor).
    // 'internal' (Default): Chart führt eigenen sticky-Index, zeichnet
    //   selbst, ruft onCursor nur als Broadcast-Hook.
    const cursorMode = cfg.cursorMode || 'internal';

    // ---- Element lookups -------------------------------------------------
    const svg = document.getElementById(ids.svg);
    if (!svg) return null;
    const speedUnit = data.speedUnit || 'km/h';

    // ---- Geometry constants ---------------------------------------------
    const W = 1200, H = 480;
    const SPEED_LEFT = 64;
    const AXIS_W = 60;
    const M_top = 16, M_right = 24, M_bottom = 36;
    const SPEED_COLOR = '#00d4ff';
    const PALETTE = ['#ffb000', '#ff3d00', '#52d671', '#c77dff', '#ffd166',
                     '#06d6a0', '#ef476f', '#118ab2', '#ff8500', '#7fc8a9'];

    // Stable, unique clipPath id per instance so multiple charts on the
    // same page don't collide.
    const clipId = (ids.svg || 'sc') + '-clip';

    // ---- State -----------------------------------------------------------
    // Each extra is shallow-cloned so multiple chart instances over the same
    // raw data can have independent .active / .color / scale state.
    const initialActive = new Set(cfg.initialActiveExtraIds || []);
    const extras = (data.extras || []).map((ch, i) => Object.assign({}, ch, {
      color: ch.color || PALETTE[i % PALETTE.length],
      active: initialActive.has(ch.id),
    }));

    let speedActive = (cfg.initialSpeedActive !== false);
    let zoom = null;  // {dMin, dMax} when active

    let M_left, w, h, xS, distMin, distMax, speedMax, yS_speed;

    function recomputeGeometry(){
      const nActive = extras.filter(c => c.active).length;
      const speedSlot = speedActive ? SPEED_LEFT : 0;
      M_left = speedSlot + nActive * AXIS_W;
      w = W - M_left - M_right;
      h = H - M_top - M_bottom;
      const dist = data.distance || [];
      const fullDistMax = dist[dist.length-1] || 1;
      if (zoom){
        distMin = zoom.dMin;
        distMax = zoom.dMax;
      } else {
        distMin = 0;
        distMax = fullDistMax;
      }
      const speedArr = data.speed || [];
      const sMax = speedArr.length ? Math.max.apply(null, speedArr) : 100;
      speedMax = Math.ceil(sMax / 50) * 50;
      xS = d => M_left + ((d - distMin)/(distMax - distMin || 1)) * w;
      yS_speed = v => M_top + (1 - v/(speedMax || 1)) * h;
      extras.forEach(ch => {
        ch.yScale = (v) => {
          const span = (ch.max - ch.min) || 1;
          return M_top + (1 - (v - ch.min) / span) * h;
        };
      });
    }

    // ---- Rendering -------------------------------------------------------
    function renderAxisColumn(right, width, color, label, ticks, drawDivider){
      let s = '';
      if (drawDivider){
        s += '<line x1="'+right+'" y1="'+M_top+'" x2="'+right+'" y2="'+(M_top+h)+'" stroke="#262626" stroke-width="1"/>';
      }
      ticks.forEach(t => {
        s += '<text x="'+(right-6)+'" y="'+(t.y+3)+'" class="chart-tick" text-anchor="end" fill="'+color+'">'+t.text+'</text>';
      });
      if (label){
        const labelX = right - width + 14;
        const labelY = M_top + h - 4;
        const shortLabel = label.length > 24 ? label.slice(0, 23) + '…' : label;
        s += '<text x="'+labelX+'" y="'+labelY+'" class="chart-label" fill="'+color+'" transform="rotate(-90 '+labelX+','+labelY+')">'+shortLabel+'</text>';
      }
      return s;
    }

    function staticBg(){
      let yGrid = '';
      const gridStep = 50;
      for (let v = 0; v <= speedMax; v += gridStep){
        const y = yS_speed(v);
        yGrid += '<line x1="'+M_left+'" y1="'+y+'" x2="'+(M_left+w)+'" y2="'+y+'" stroke="#1a1a1a" stroke-width="1"/>';
      }
      let yAxes = '';
      if (speedActive){
        const speedTicks = [];
        for (let v = 0; v <= speedMax; v += 50){
          speedTicks.push({value: v, y: yS_speed(v), text: String(v)});
        }
        yAxes += renderAxisColumn(
          M_left, SPEED_LEFT, '#a0a0a0',
          'SPEED (' + speedUnit.toUpperCase() + ')', speedTicks, false
        );
      }
      const speedSlot = speedActive ? SPEED_LEFT : 0;
      const activeExtras = extras.filter(c => c.active);
      activeExtras.forEach((ch, slot) => {
        const colRight = M_left - speedSlot - slot * AXIS_W;
        const span = ch.max - ch.min;
        const absMax = Math.max(Math.abs(ch.min), Math.abs(ch.max));
        let fmt;
        if (absMax >= 100) fmt = (v) => v.toFixed(0);
        else if (absMax >= 10) fmt = (v) => v.toFixed(1);
        else fmt = (v) => v.toFixed(2);
        const ticks = [];
        for (let k = 0; k <= 3; k++){
          const v = ch.min + (span * k / 3);
          ticks.push({value: v, y: ch.yScale(v), text: fmt(v)});
        }
        const label = (ch.name + (ch.unit ? (' (' + ch.unit + ')') : '')).toUpperCase();
        yAxes += renderAxisColumn(colRight, AXIS_W, ch.color, label, ticks, true);
      });

      let xTicks = '';
      const range = distMax - distMin;
      let xStep;
      if (range > 8000)      xStep = 2000;
      else if (range > 4000) xStep = 1000;
      else if (range > 2000) xStep = 500;
      else if (range > 800)  xStep = 200;
      else if (range > 300)  xStep = 100;
      else                   xStep = 50;
      const dStart = Math.ceil(distMin / xStep) * xStep;
      for (let d = dStart; d <= distMax; d += xStep){
        const x = xS(d);
        xTicks += '<line x1="'+x+'" y1="'+M_top+'" x2="'+x+'" y2="'+(M_top+h)+'" stroke="#1a1a1a" stroke-width="1"/>';
        const txt = (range >= 2000) ? ((d/1000).toFixed(1) + ' km') : (d.toFixed(0) + ' m');
        xTicks += '<text x="'+x+'" y="'+(M_top+h+18)+'" class="chart-tick" text-anchor="middle">'+txt+'</text>';
      }
      return yGrid + yAxes + xTicks;
    }

    function speedPath(){
      const dist = data.distance || [];
      const speed = data.speed || [];
      let p = '';
      let started = false;
      for (let i = 0; i < dist.length; i++){
        const d = dist[i];
        const inRange = d >= distMin && d <= distMax;
        const neighborIn =
          (i > 0 && dist[i-1] >= distMin && dist[i-1] <= distMax) ||
          (i < dist.length-1 && dist[i+1] >= distMin && dist[i+1] <= distMax);
        if (!inRange && !neighborIn) continue;
        const x = xS(d);
        p += (!started?'M':'L') + x.toFixed(1) + ',' + yS_speed(speed[i]).toFixed(1);
        started = true;
      }
      return p;
    }

    function extraPath(ch){
      const dist = data.distance || [];
      const arr = ch.data;
      let p = '';
      let started = false;
      for (let i = 0; i < dist.length; i++){
        const v = arr[i];
        if (!Number.isFinite(v)){ started = false; continue; }
        const d = dist[i];
        const inRange = d >= distMin && d <= distMax;
        const neighborIn =
          (i > 0 && dist[i-1] >= distMin && dist[i-1] <= distMax) ||
          (i < dist.length-1 && dist[i+1] >= distMin && dist[i+1] <= distMax);
        if (!inRange && !neighborIn) continue;
        const x = xS(d);
        p += (!started?'M':'L') + x.toFixed(1) + ',' + ch.yScale(v).toFixed(1);
        started = true;
      }
      return p;
    }

    function render(){
      recomputeGeometry();
      const clip = '<defs><clipPath id="'+clipId+'"><rect x="'+M_left+'" y="'+M_top+'" width="'+w+'" height="'+h+'"/></clipPath></defs>';
      let extraPaths = '';
      extras.filter(c => c.active).forEach(ch => {
        extraPaths += '<path d="'+extraPath(ch)+'" fill="none" stroke="'+ch.color+'" stroke-width="1.4" opacity="0.85" clip-path="url(#'+clipId+')"/>';
      });
      const speedLine = speedActive
        ? '<path d="'+speedPath()+'" fill="none" stroke="'+SPEED_COLOR+'" stroke-width="1.8" opacity="0.95" clip-path="url(#'+clipId+')"/>'
        : '';
      svg.innerHTML = clip + staticBg() + extraPaths + speedLine + '<g class="speed-cursor"></g>';
      updateLegend();
      updateZoomBadge();
    }

    function updateLegend(){
      const legend = ids.legend ? document.getElementById(ids.legend) : null;
      if (legend){
        let html = '';
        if (speedActive){
          html += '<span class="lg"><span class="swatch" style="background:'+SPEED_COLOR+'"></span>Speed</span>';
        }
        extras.filter(c => c.active).forEach(ch => {
          html += '<span class="lg"><span class="swatch" style="background:'+ch.color+'"></span>'+ch.name+(ch.unit?(' (' + ch.unit + ')'):'')+'</span>';
        });
        legend.innerHTML = html;
      }
      const n = extras.filter(c => c.active).length + (speedActive ? 1 : 0);
      const badge = ids.badge ? document.getElementById(ids.badge) : null;
      if (badge) badge.innerHTML = (n > 0) ? ('<span class="badge">'+n+'</span>') : '';
    }

    function updateZoomBadge(){
      const btn = ids.zoomBtn ? document.getElementById(ids.zoomBtn) : null;
      if (!btn) return;
      const dist = data.distance || [];
      if (zoom){
        const full = dist[dist.length-1] || 1;
        const pct = Math.max(1, Math.round((distMax - distMin) / full * 100));
        btn.hidden = false;
        const span = btn.querySelector('.zoom-pct');
        if (span) span.textContent = pct + '%';
      } else {
        btn.hidden = true;
      }
    }

    function drawCursor(idx){
      const cursorG = svg.querySelector('.speed-cursor');
      if (!cursorG) return;
      const dist = data.distance || [];
      if (idx < 0 || idx >= dist.length){ cursorG.innerHTML = ''; return; }
      const d = dist[idx];
      if (d < distMin || d > distMax){ cursorG.innerHTML = ''; return; }
      const x = xS(d);
      let html = '<line x1="'+x.toFixed(1)+'" y1="'+M_top+'" x2="'+x.toFixed(1)+'" y2="'+(M_top+h)+'" stroke="#fff" stroke-width="1" opacity="0.7"/>';
      if (speedActive){
        const y = yS_speed((data.speed || [])[idx]);
        html += '<circle cx="'+x.toFixed(1)+'" cy="'+y.toFixed(1)+'" r="5" fill="#0a0a0a" stroke="'+SPEED_COLOR+'" stroke-width="2"/>';
      }
      extras.filter(c => c.active).forEach(ch => {
        const v = ch.data[idx];
        if (!Number.isFinite(v)) return;
        const yy = ch.yScale(v);
        html += '<circle cx="'+x.toFixed(1)+'" cy="'+yy.toFixed(1)+'" r="4" fill="#0a0a0a" stroke="'+ch.color+'" stroke-width="2"/>';
      });
      cursorG.innerHTML = html;
    }

    // ---- Pointer / pan / zoom -------------------------------------------
    function svgPointFromEvent(evt){
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      return pt.matrixTransform(ctm.inverse());
    }
    function distFromSvgX(svgX){
      if (svgX < M_left || svgX > M_left + w) return null;
      return distMin + (svgX - M_left) / w * (distMax - distMin);
    }
    function indexFromEvent(evt){
      const local = svgPointFromEvent(evt);
      if (!local) return -1;
      const dist = distFromSvgX(local.x);
      if (dist == null) return -1;
      const arr = data.distance || [];
      let lo = 0, hi = arr.length - 1;
      while (lo < hi){
        const mid = (lo + hi) >> 1;
        if (arr[mid] < dist) lo = mid + 1; else hi = mid;
      }
      if (lo > 0 && Math.abs(arr[lo-1] - dist) < Math.abs(arr[lo] - dist)) lo--;
      return lo;
    }

    // Internes Sticky-State: damit der Chart selbst-stickify kann auch ohne
    // externen Sticky-Index. Externer Sticky (Datenviewer) hat Vorrang.
    let internalStickyIdx = -1;
    function effectiveSticky(){
      const ext = externalStickyIdx();
      return ext >= 0 ? ext : internalStickyIdx;
    }

    let panState = null;
    const PAN_THRESHOLD_PX = 4;

    svg.addEventListener('mousemove', (e) => {
      if (panState){
        const local = svgPointFromEvent(e);
        if (!local) return;
        const dx = local.x - panState.startSvgX;
        if (!panState.didPan && Math.abs(dx) >= PAN_THRESHOLD_PX){
          panState.didPan = true;
          svg.style.cursor = 'grabbing';
        }
        if (panState.didPan){
          const span = panState.startDistMax - panState.startDistMin;
          const dist = data.distance || [];
          const full = dist[dist.length-1] || 1;
          const dDist = -(dx / w) * span;
          let newMin = panState.startDistMin + dDist;
          let newMax = panState.startDistMax + dDist;
          if (newMin < 0){ newMax -= newMin; newMin = 0; }
          if (newMax > full){ newMin -= (newMax - full); newMax = full; }
          zoom = (newMax - newMin < full - 0.5) ? {dMin: newMin, dMax: newMax} : null;
          render();
          const sticky = effectiveSticky();
          if (sticky >= 0) drawCursor(sticky);
        }
        return;
      }
      const sticky = effectiveSticky();
      if (sticky >= 0) return;
      const i = indexFromEvent(e);
      if (i >= 0){
        // v21.46 — Im internal mode (Coach) zeichnet der Chart seinen
        // eigenen Cursor; im external mode (Datenviewer) zeichnet das
        // der Konsument via setCursor→drawCursor.
        if (cursorMode === 'internal') drawCursor(i);
        onCursor(i, undefined);
      }
    });
    svg.addEventListener('mouseleave', () => {
      const sticky = effectiveSticky();
      if (sticky < 0){
        // Kein sticky (weder extern noch intern) → live-cursor weg.
        if (cursorMode === 'internal') drawCursor(-1);
        onClearLive();
      } else if (cursorMode === 'internal'){
        // Sticky existiert — zurück zum sticky-Cursor zeichnen.
        drawCursor(sticky);
      }
    });
    svg.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      const local = svgPointFromEvent(e);
      if (!local) return;
      if (local.x < M_left || local.x > M_left + w) return;
      panState = {
        startSvgX: local.x,
        startDistMin: distMin,
        startDistMax: distMax,
        didPan: false,
      };
      svg.style.cursor = 'grab';
    });
    function onWindowMouseUp(e){
      if (!panState) return;
      const wasDrag = panState.didPan;
      panState = null;
      svg.style.cursor = '';
      if (wasDrag) return;
      const i = indexFromEvent(e);
      if (i < 0) return;
      // v21.46 — Sticky-Toggle. Mode-abhängig:
      //   external (Datenviewer): onCursor entscheidet, externer Code
      //     ruft drawCursor zurück über setCursor→speedChart.drawCursor.
      //   internal (Coach): eigener Sticky-Index, Chart zeichnet selbst,
      //     onCursor ist nur Broadcast für ev. Trackmap-Sync.
      if (cursorMode === 'external'){
        const extSticky = externalStickyIdx();
        if (extSticky === i) onCursor(-1, false);
        else onCursor(i, true);
      } else {
        if (internalStickyIdx === i){
          internalStickyIdx = -1;
          drawCursor(-1);
          onCursor(-1, false);
        } else {
          internalStickyIdx = i;
          drawCursor(i);
          onCursor(i, true);
        }
      }
    }
    window.addEventListener('mouseup', onWindowMouseUp);
    svg.addEventListener('wheel', (e) => {
      const local = svgPointFromEvent(e);
      if (!local) return;
      if (local.x < M_left || local.x > M_left + w) return;
      e.preventDefault();
      const dist = data.distance || [];
      const full = dist[dist.length-1] || 1;
      const curMin = distMin, curMax = distMax;
      const anchorDist = curMin + (local.x - M_left) / w * (curMax - curMin);
      const factor = (e.deltaY < 0) ? 0.8 : 1.25;
      let span = (curMax - curMin) * factor;
      const MIN_SPAN = Math.max(20, full * 0.005);
      if (span < MIN_SPAN) span = MIN_SPAN;
      if (span >= full){
        zoom = null; render();
        const sticky = externalStickyIdx();
        if (sticky >= 0) drawCursor(sticky);
        return;
      }
      const anchorFrac = (local.x - M_left) / w;
      let newMin = anchorDist - anchorFrac * span;
      let newMax = newMin + span;
      if (newMin < 0){ newMax -= newMin; newMin = 0; }
      if (newMax > full){ newMin -= (newMax - full); newMax = full; }
      zoom = {dMin: newMin, dMax: newMax};
      render();
      const sticky = externalStickyIdx();
      if (sticky >= 0) drawCursor(sticky);
    }, {passive: false});
    svg.addEventListener('dblclick', (e) => {
      if (!zoom) return;
      e.preventDefault();
      zoom = null;
      render();
      const sticky = externalStickyIdx();
      if (sticky >= 0) drawCursor(sticky);
    });

    render();

    // ---- Channel picker modal -------------------------------------------
    // The picker is optional; if any required id is missing we skip wiring
    // (the chart still works, just without a channel-selection UI).
    const modalEl  = picker.modal    ? document.getElementById(picker.modal)    : null;
    const tbodyEl  = picker.body     ? document.getElementById(picker.body)     : null;
    const hintEl   = picker.hint     ? document.getElementById(picker.hint)     : null;
    const searchEl = picker.search   ? document.getElementById(picker.search)   : null;
    const btnOpenEl  = picker.btnOpen  ? document.getElementById(picker.btnOpen)  : null;
    const btnCloseEl = picker.btnClose ? document.getElementById(picker.btnClose) : null;
    const btnApplyEl = picker.btnApply ? document.getElementById(picker.btnApply) : null;
    const btnClearEl = picker.btnClear ? document.getElementById(picker.btnClear) : null;

    if (modalEl && tbodyEl){
      if (hintEl){
        hintEl.textContent = (extras.length + 1) + ' Kanäle verfügbar';
      }
      function speedDescriptor(){
        const arr = data.speed || [];
        let mn = Infinity, mx = -Infinity, s = 0, n = 0;
        for (let i = 0; i < arr.length; i++){
          const v = arr[i];
          if (!isFinite(v)) continue;
          if (v < mn) mn = v;
          if (v > mx) mx = v;
          s += v; n++;
        }
        return {
          id: '__speed', name: 'Speed', unit: speedUnit,
          min: isFinite(mn) ? mn : 0,
          max: isFinite(mx) ? mx : 0,
          mean: n ? s/n : 0,
          color: SPEED_COLOR, isSpeed: true,
        };
      }
      function buildTable(query){
        query = (query || '').toLowerCase();
        const all = [speedDescriptor()].concat(extras);
        const filtered = all.filter(ch =>
          !query || (ch.name + ' ' + (ch.unit||'')).toLowerCase().includes(query)
        );
        if (!filtered.length){
          tbodyEl.innerHTML = '<div class="ch-empty">KEINE TREFFER</div>';
          return;
        }
        let rows = '';
        filtered.forEach(ch => {
          const isActive = ch.isSpeed ? speedActive : ch.active;
          const minV = (typeof ch.min === 'number') ? ch.min.toFixed(2) : '—';
          const maxV = (typeof ch.max === 'number') ? ch.max.toFixed(2) : '—';
          const meanV = (typeof ch.mean === 'number') ? ch.mean.toFixed(2) : '—';
          rows += '<label class="ch-row '+(isActive?'active':'')+'" data-id="'+ch.id+'">' +
            '<span class="ch-col-on"><input type="checkbox" data-id="'+ch.id+'" '+(isActive?'checked':'')+'></span>' +
            '<span class="ch-col-name"><span class="swatch" style="background:'+ch.color+'"></span>'+ch.name+'</span>' +
            '<span class="ch-col-unit">'+(ch.unit || '—')+'</span>' +
            '<span class="ch-col-min">'+minV+'</span>' +
            '<span class="ch-col-max">'+maxV+'</span>' +
            '<span class="ch-col-mean">'+meanV+'</span>' +
          '</label>';
        });
        tbodyEl.innerHTML = rows;
      }
      function openModal(){
        buildTable(searchEl ? searchEl.value : '');
        modalEl.hidden = false;
        if (searchEl) setTimeout(() => searchEl.focus(), 0);
      }
      function closeModal(){ modalEl.hidden = true; }
      if (btnOpenEl)  btnOpenEl.addEventListener('click', openModal);
      if (btnCloseEl) btnCloseEl.addEventListener('click', closeModal);
      if (btnApplyEl) btnApplyEl.addEventListener('click', closeModal);
      modalEl.addEventListener('click', (e) => { if (e.target === modalEl) closeModal(); });
      document.addEventListener('keydown', (e) => {
        if (!modalEl.hidden && e.key === 'Escape') closeModal();
      });
      if (searchEl){
        searchEl.addEventListener('input', () => buildTable(searchEl.value));
      }
      if (btnClearEl){
        btnClearEl.addEventListener('click', () => {
          extras.forEach(c => c.active = false);
          speedActive = false;
          buildTable(searchEl ? searchEl.value : '');
          render();
          const sticky = externalStickyIdx();
          if (sticky >= 0) drawCursor(sticky);
          onChannelChange();
        });
      }
      tbodyEl.addEventListener('change', (e) => {
        const cb = e.target;
        if (!cb.matches('input[type="checkbox"]')) return;
        const id = cb.dataset.id;
        if (id === '__speed'){
          speedActive = cb.checked;
        } else {
          const ch = extras.find(x => x.id === id);
          if (!ch) return;
          ch.active = cb.checked;
        }
        const row = cb.closest('.ch-row');
        if (row) row.classList.toggle('active', cb.checked);
        render();
        const sticky = externalStickyIdx();
        if (sticky >= 0) drawCursor(sticky);
        onChannelChange();
      });
    }

    // ---- Zoom reset button ----------------------------------------------
    if (ids.zoomBtn){
      const btnZoomReset = document.getElementById(ids.zoomBtn);
      if (btnZoomReset){
        btnZoomReset.addEventListener('click', () => {
          zoom = null;
          render();
          const sticky = externalStickyIdx();
          if (sticky >= 0) drawCursor(sticky);
        });
      }
    }

    function destroy(){
      window.removeEventListener('mouseup', onWindowMouseUp);
      // svg listeners die mit dem element; modal listeners gehören
      // ohnehin zum globalen document, sind hier ein bewusster Leak
      // (jeder Datenviewer/Coach hat genau ein lifetime).
    }

    // v22.0 — Externer Sticky-Setter: Marker/Row-Klick im Coach kann den
    // Chart-Cursor an einen Sample-Index pinnen. Im 'internal' Cursor-Mode
    // setzt das den lokalen Sticky-Index; im 'external' Mode delegieren wir
    // an onCursor (der Datenviewer-Konsument hat seinen eigenen
    // setCursor()-Pfad).
    function setStickyCursor(sampleIdx){
      if (cursorMode === 'external'){
        onCursor(sampleIdx, true);
        return;
      }
      if (sampleIdx == null || sampleIdx < 0){
        internalStickyIdx = -1;
        drawCursor(-1);
        return;
      }
      internalStickyIdx = sampleIdx;
      drawCursor(sampleIdx);
    }
    function clearStickyCursor(){
      if (cursorMode === 'external'){
        onCursor(-1, false);
        return;
      }
      internalStickyIdx = -1;
      drawCursor(-1);
    }

    return {
      drawCursor,
      setStickyCursor,
      clearStickyCursor,
      getActiveExtras: () => extras.filter(c => c.active),
      isSpeedActive:   () => speedActive,
      render,
      destroy,
    };
  }

  window.createSpeedChart = createSpeedChart;
})();
