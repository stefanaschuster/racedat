// Test für v21.45 setupMarkerRowLink Helper.
// Simuliert host (Tabellen-Container mit Rows) + mapHost (SVG-Container mit
// Marker-Groups), klickt Rows und Marker, prüft .is-selected Klassen.

import assert from 'node:assert/strict';

// ===== Mini DOM ============================================================
// Genug für: addEventListener('click'), querySelector(All), classList,
// dataset, parentNode, scrollIntoView. Keine echte Bubbling-Simulation —
// wir rufen den Handler direkt mit dem Ziel-Element auf.

let passed = 0;
let failed = 0;
function ok(label, fn){
  try { fn(); console.log('  OK  ' + label); passed++; }
  catch (e){ console.log('FAIL  ' + label + ': ' + (e.message || e)); failed++; }
}

class FakeClassList {
  constructor(el){ this.el = el; this._set = new Set(); }
  add(c){ this._set.add(c); }
  remove(c){ this._set.delete(c); }
  contains(c){ return this._set.has(c); }
  toString(){ return Array.from(this._set).join(' '); }
}

class FakeEl {
  constructor(tag, attrs = {}, children = []){
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.classList = new FakeClassList(this);
    this.dataset = {};
    this._listeners = {};
    this.scrolledIntoView = false;
    for (const [k, v] of Object.entries(attrs)){
      if (k.startsWith('data-')){
        this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(v);
      }
    }
    children.forEach(c => this.appendChild(c));
  }
  appendChild(c){ c.parentNode = this; this.children.push(c); return c; }
  addEventListener(type, fn){
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(fn);
  }
  scrollIntoView(){ this.scrolledIntoView = true; }
  // Recursively yield all descendants
  *_walk(){
    for (const c of this.children){
      yield c;
      yield* c._walk();
    }
  }
  querySelectorAll(selector){
    // We only support [data-idx="X"] and [data-idx].is-selected and similar.
    const m1 = selector.match(/^\[data-idx="([^"]+)"\]$/);
    if (m1){
      const want = m1[1];
      return Array.from(this._walk()).filter(el => el.dataset.idx === want);
    }
    const m2 = selector.match(/^\[data-idx\]\.is-selected$/);
    if (m2){
      return Array.from(this._walk()).filter(el =>
        el.dataset.idx != null && el.classList.contains('is-selected'));
    }
    throw new Error('selector not supported in fake DOM: ' + selector);
  }
  // Simulate a click event bubbling to a registered handler on this element.
  // We pass the deepest target; the helper walks up the parentNode chain.
  fireClick(target){
    const fns = this._listeners.click || [];
    fns.forEach(fn => fn({target}));
  }
}

// ===== Helper (kopiert aus coach.py, v22.0) ===============================
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
      try { fn(idx, lastSource); } catch (e){}
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

// ===== Setup ===============================================================
function makeFixture(){
  // host with 3 rows (idx 1, 2, 3)
  const rows = [1, 2, 3].map(i => {
    const inner = new FakeEl('div', {'data-idx': '_unused_'}); // child without data-idx
    delete inner.dataset.idx;
    return new FakeEl('div', {class: 'brake-zone', 'data-idx': String(i)},
                      [inner]);
  });
  const host = new FakeEl('div', {}, rows);
  // mapHost with 3 marker groups (idx 1, 2, 3), each with inner circle
  const markers = [1, 2, 3].map(i => {
    const circle = new FakeEl('circle', {class: 'mk-bubble'});
    return new FakeEl('g', {'data-idx': String(i)}, [circle]);
  });
  const mapHost = new FakeEl('svg', {}, markers);
  // mapWrap wraps mapHost (the container that holds the trackmap section)
  const mapWrap = new FakeEl('div', {class: 'brake-trackmap-wrap'}, [mapHost]);
  return {host, mapHost, mapWrap, rows, markers};
}

// ===== Tests ===============================================================

ok('basic: click row highlights row + marker', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  host.fireClick(rows[1]);
  assert.ok(rows[1].classList.contains('is-selected'), 'row 2 selected');
  assert.ok(markers[1].classList.contains('is-selected'), 'marker 2 selected');
  assert.ok(!rows[0].classList.contains('is-selected'), 'row 1 not selected');
  assert.ok(!rows[2].classList.contains('is-selected'), 'row 3 not selected');
});

ok('basic: click marker highlights row + marker', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  mapHost.fireClick(markers[2]);
  assert.ok(rows[2].classList.contains('is-selected'));
  assert.ok(markers[2].classList.contains('is-selected'));
});

ok('toggle: clicking same row deselects', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  host.fireClick(rows[0]);
  assert.ok(rows[0].classList.contains('is-selected'));
  host.fireClick(rows[0]);
  assert.ok(!rows[0].classList.contains('is-selected'));
  assert.ok(!markers[0].classList.contains('is-selected'));
});

ok('toggle: clicking different row switches selection', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  host.fireClick(rows[0]);
  host.fireClick(rows[2]);
  assert.ok(!rows[0].classList.contains('is-selected'), 'row 1 deselected');
  assert.ok(!markers[0].classList.contains('is-selected'), 'marker 1 deselected');
  assert.ok(rows[2].classList.contains('is-selected'), 'row 3 selected');
  assert.ok(markers[2].classList.contains('is-selected'), 'marker 3 selected');
});

ok('cross: row then marker of same idx toggles off', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  host.fireClick(rows[1]);
  mapHost.fireClick(markers[1]);
  assert.ok(!rows[1].classList.contains('is-selected'));
  assert.ok(!markers[1].classList.contains('is-selected'));
});

ok('cross: marker then row of different idx switches', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  mapHost.fireClick(markers[0]);
  host.fireClick(rows[2]);
  assert.ok(!rows[0].classList.contains('is-selected'));
  assert.ok(!markers[0].classList.contains('is-selected'));
  assert.ok(rows[2].classList.contains('is-selected'));
  assert.ok(markers[2].classList.contains('is-selected'));
});

ok('autoscroll v21.46: marker-Klick scrollt Row ins Viewport', () => {
  const {host, mapHost, mapWrap, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost, mapWrap);
  mapHost.fireClick(markers[2]);
  assert.ok(rows[2].scrolledIntoView, 'row 3 was scrolled into view');
  assert.ok(!mapWrap.scrolledIntoView, 'mapWrap NOT scrolled (klick war auf map)');
});

ok('autoscroll v21.46: row-Klick scrollt mapWrap ins Viewport (NICHT die Row)', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  setupMarkerRowLink(host, mapHost, mapWrap);
  host.fireClick(rows[0]);
  assert.ok(mapWrap.scrolledIntoView, 'mapWrap scrolled into view');
  assert.ok(!rows[0].scrolledIntoView, 'row 1 NOT scrolled (klick war auf row)');
});

ok('autoscroll v21.46: row-Klick ohne mapWrap → kein scroll, kein crash', () => {
  const {host, mapHost, rows} = makeFixture();
  setupMarkerRowLink(host, mapHost); // mapWrap fehlt
  host.fireClick(rows[1]);
  assert.ok(rows[1].classList.contains('is-selected'),
            'selection geht trotz fehlendem mapWrap');
});

ok('autoscroll v21.46: clear() macht keinen Scroll', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const api = setupMarkerRowLink(host, mapHost, mapWrap);
  host.fireClick(rows[1]); // erzeugt scroll auf mapWrap
  mapWrap.scrolledIntoView = false; // reset für saubere Messung
  api.clear();
  assert.ok(!mapWrap.scrolledIntoView, 'clear() löst keinen Scroll aus');
  assert.ok(!rows[1].scrolledIntoView, 'clear() scrollt auch nicht die Row');
});

ok('autoscroll v21.46: programmatisches highlight() scrollt nicht', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const api = setupMarkerRowLink(host, mapHost, mapWrap);
  api.highlight('2');
  assert.ok(rows[1].classList.contains('is-selected'));
  assert.ok(!mapWrap.scrolledIntoView, 'API-highlight scrollt nichts');
  assert.ok(!rows[1].scrolledIntoView);
});

ok('click on inner child bubbles up to find data-idx', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  // markers[1] has an inner <circle> child without data-idx
  const innerCircle = markers[1].children[0];
  assert.equal(innerCircle.dataset.idx, undefined,
               'precondition: inner circle has no data-idx');
  mapHost.fireClick(innerCircle);
  assert.ok(markers[1].classList.contains('is-selected'),
            'parent marker should still be selected');
  assert.ok(rows[1].classList.contains('is-selected'),
            'row 2 should also be selected');
});

ok('click on stray element (no data-idx anywhere) is a no-op', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  const stray = new FakeEl('text');
  mapHost.appendChild(stray);
  mapHost.fireClick(stray);
  // Nothing should be selected
  const anySel = [...rows, ...markers].some(el => el.classList.contains('is-selected'));
  assert.ok(!anySel, 'no selection should appear');
});

ok('clear(): wipes selection programmatically', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  const api = setupMarkerRowLink(host, mapHost);
  host.fireClick(rows[1]);
  api.clear();
  assert.ok(!rows[1].classList.contains('is-selected'));
  assert.ok(!markers[1].classList.contains('is-selected'));
  // After clear, the same row clicked again should highlight (not toggle off)
  host.fireClick(rows[1]);
  assert.ok(rows[1].classList.contains('is-selected'),
            'after clear, clicking selects fresh');
});

ok('idempotent binding: second setup returns same API, no duplicate listeners', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  const api1 = setupMarkerRowLink(host, mapHost);
  const api2 = setupMarkerRowLink(host, mapHost);
  assert.equal(api1, api2, 'same API object returned');
  // Only one click handler should fire — otherwise toggle would fire twice
  // and immediately undo itself.
  host.fireClick(rows[0]);
  assert.ok(rows[0].classList.contains('is-selected'),
            'single click selects (no double-fire / toggle race)');
});

ok('returns null on missing host or mapHost', () => {
  assert.equal(setupMarkerRowLink(null, {}), null);
  assert.equal(setupMarkerRowLink({}, null), null);
});

ok('mismatched data-idx (e.g., extra marker without row) does not crash', () => {
  const {host, mapHost, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  // Add a stray marker with idx=99 (no matching row)
  const stray = new FakeEl('g', {'data-idx': '99'});
  mapHost.appendChild(stray);
  mapHost.fireClick(stray);
  // Marker should be selected, but no row exists to highlight or scroll
  assert.ok(stray.classList.contains('is-selected'));
});

ok('multiple selects in a row: only one is_selected at a time', () => {
  const {host, mapHost, rows, markers} = makeFixture();
  setupMarkerRowLink(host, mapHost);
  host.fireClick(rows[0]);
  host.fireClick(rows[1]);
  host.fireClick(rows[2]);
  const sel = rows.filter(r => r.classList.contains('is-selected'));
  assert.equal(sel.length, 1, 'exactly one row selected');
  assert.equal(sel[0], rows[2], 'last clicked is the selected one');
});

// ===== v22.0 onSelect callback tests ======================================

ok('onSelect v22.0: row click fires callback with idx + source=row', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const calls = [];
  setupMarkerRowLink(host, mapHost, mapWrap, (idx, src) => calls.push({idx, src}));
  host.fireClick(rows[1]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].idx, '2');
  assert.equal(calls[0].src, 'row');
});

ok('onSelect v22.0: marker click fires callback with idx + source=map', () => {
  const {host, mapHost, mapWrap, markers} = makeFixture();
  const calls = [];
  setupMarkerRowLink(host, mapHost, mapWrap, (idx, src) => calls.push({idx, src}));
  mapHost.fireClick(markers[2]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].idx, '3');
  assert.equal(calls[0].src, 'map');
});

ok('onSelect v22.0: deselect fires callback with null', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const calls = [];
  setupMarkerRowLink(host, mapHost, mapWrap, (idx) => calls.push(idx));
  host.fireClick(rows[0]);  // select
  host.fireClick(rows[0]);  // toggle off
  assert.deepEqual(calls, ['1', null]);
});

ok('onSelect v22.0: switching selection fires deselect then select', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const calls = [];
  setupMarkerRowLink(host, mapHost, mapWrap, (idx) => calls.push(idx));
  host.fireClick(rows[0]);
  host.fireClick(rows[2]);
  // first select -> '1', then clearAll wipes, highlight('3') notifies '3'
  // Note: depending on implementation we may see ['1', '3'] or ['1', null, '3'].
  // Our impl: in toggle's else-branch highlight() is called which itself
  // calls notifySelect(idx). clearAll() inside highlight does NOT notify.
  assert.deepEqual(calls, ['1', '3']);
});

ok('onSelect v22.0: clear() fires null only when something was selected', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const calls = [];
  const api = setupMarkerRowLink(host, mapHost, mapWrap, (idx) => calls.push(idx));
  api.clear();           // nothing selected → no callback
  assert.equal(calls.length, 0);
  host.fireClick(rows[1]);
  assert.deepEqual(calls, ['2']);
  api.clear();           // now selected → callback with null
  assert.deepEqual(calls, ['2', null]);
});

ok('onSelect v22.0: multiple listeners can be registered via addSelectListener', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const a = [], b = [];
  const api = setupMarkerRowLink(host, mapHost, mapWrap, (idx) => a.push(idx));
  api.addSelectListener((idx) => b.push(idx));
  host.fireClick(rows[0]);
  assert.deepEqual(a, ['1']);
  assert.deepEqual(b, ['1']);
});

ok('onSelect v22.0: failing listener does not break others', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const calls = [];
  const api = setupMarkerRowLink(host, mapHost, mapWrap, () => { throw new Error('boom'); });
  api.addSelectListener((idx) => calls.push(idx));
  host.fireClick(rows[0]);
  assert.deepEqual(calls, ['1'],
                   'second listener still fires despite first one throwing');
});

ok('onSelect v22.0: idempotent setup also adds the second onSelect', () => {
  const {host, mapHost, mapWrap, rows} = makeFixture();
  const a = [], b = [];
  setupMarkerRowLink(host, mapHost, mapWrap, (idx) => a.push(idx));
  // Re-init with a NEW onSelect — should stack, not replace.
  setupMarkerRowLink(host, mapHost, mapWrap, (idx) => b.push(idx));
  host.fireClick(rows[1]);
  assert.deepEqual(a, ['2']);
  assert.deepEqual(b, ['2']);
});

console.log('');
console.log(passed + ' pass, ' + failed + ' fail');
if (failed > 0) process.exit(1);
