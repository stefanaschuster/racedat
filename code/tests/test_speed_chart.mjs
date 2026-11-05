// v21.46 — Smoke-Test für die speed_chart.js Factory.
//
// Lädt das Modul in einem Fake-DOM und stellt sicher dass:
//   - createSpeedChart auf window definiert ist
//   - Mit Minimal-Konfiguration eine API mit drawCursor/getActiveExtras/
//     isSpeedActive/render/destroy zurückgegeben wird
//   - initialActiveExtraIds richtig pre-selektiert
//   - cursorMode 'internal' vs 'external' richtig dispatcht
//
// Kein echtes Rendering — wir prüfen Verhalten der Public API.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

let pass = 0, fail = 0;
function ok(label, fn){
  try { fn(); pass++; console.log('  OK  ' + label); }
  catch (e){ fail++; console.log('FAIL  ' + label + ': ' + (e.message || e)); }
}

// ---- Minimal Fake DOM ------------------------------------------------------
function makeFakeEl(tag){
  const el = {
    tagName: (tag||'div').toUpperCase(),
    children: [],
    style: {},
    _listeners: {},
    dataset: {},
    classList: {
      _set: new Set(),
      add(c){this._set.add(c);}, remove(c){this._set.delete(c);},
      contains(c){return this._set.has(c);}, toggle(c, on){
        if (on === undefined) this._set.has(c) ? this._set.delete(c) : this._set.add(c);
        else if (on) this._set.add(c); else this._set.delete(c);
      },
    },
    hidden: false,
    addEventListener(t,fn){ (this._listeners[t]=this._listeners[t]||[]).push(fn); },
    removeEventListener(t,fn){ /* nop */ },
    appendChild(c){ this.children.push(c); return c; },
    querySelector(sel){
      if (sel === '.speed-cursor'){
        if (!this._speedCursor){ this._speedCursor = makeFakeEl('g'); this._speedCursor.innerHTML=''; }
        return this._speedCursor;
      }
      if (sel === '.zoom-pct') return this._zoomPct || (this._zoomPct = makeFakeEl('span'));
      return null;
    },
    matches(sel){ return false; },
    closest(sel){ return null; },
    set innerHTML(v){ this._inner = v; },
    get innerHTML(){ return this._inner || ''; },
    set textContent(v){ this._text = v; },
    get textContent(){ return this._text || ''; },
    // SVG bits used by chart
    createSVGPoint(){ return {x:0,y:0, matrixTransform(){ return {x:0,y:0}; }}; },
    getScreenCTM(){ return {inverse(){ return {}; }}; },
  };
  return el;
}

const docElements = {};
const fakeDocument = {
  getElementById(id){
    if (!docElements[id]) return null;
    return docElements[id];
  },
  addEventListener(){},
  removeEventListener(){},
};
const fakeWindow = {
  addEventListener(){},
  removeEventListener(){},
};

// All IDs the chart might look up — register them
const allIds = [
  'svg-test','legend-test','badge-test','zoom-test',
  'pick-test','modal-test','body-test','hint-test','search-test',
  'close-test','apply-test','clear-test',
];
allIds.forEach(id => { docElements[id] = makeFakeEl(); });

// ---- Load the module into a vm context -----------------------------------
const src = fs.readFileSync(new URL('../static/speed_chart.js', import.meta.url), 'utf-8');
const ctx = vm.createContext({
  window: fakeWindow,
  document: fakeDocument,
  console,
});
vm.runInContext(src, ctx);

// ---- Tests ----------------------------------------------------------------

ok('window.createSpeedChart is exported', () => {
  assert.equal(typeof ctx.window.createSpeedChart, 'function');
});

ok('returns null if svg id not found', () => {
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1], speed:[0,0], extras:[]},
    ids: {svg: 'no-such-id'},
  });
  assert.equal(inst, null);
});

ok('basic instance has expected API surface', () => {
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1,2], speed:[10,20,30], extras:[]},
    ids: {svg: 'svg-test', legend: 'legend-test', badge: 'badge-test'},
  });
  assert.ok(inst);
  assert.equal(typeof inst.drawCursor, 'function');
  assert.equal(typeof inst.getActiveExtras, 'function');
  assert.equal(typeof inst.isSpeedActive, 'function');
  assert.equal(typeof inst.render, 'function');
  assert.equal(typeof inst.destroy, 'function');
});

ok('initialActiveExtraIds pre-selects channels', () => {
  // Reset fake document state for a clean instance
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const inst = ctx.window.createSpeedChart({
    data: {
      distance:[0,1,2], speed:[10,20,30],
      extras: [
        {id:'A', name:'A', unit:'', data:[1,2,3], min:1, max:3, mean:2},
        {id:'B', name:'B', unit:'', data:[4,5,6], min:4, max:6, mean:5},
        {id:'C', name:'C', unit:'', data:[7,8,9], min:7, max:9, mean:8},
      ],
    },
    ids: {svg: 'svg-test', legend: 'legend-test', badge: 'badge-test'},
    initialActiveExtraIds: ['A', 'C'],
  });
  assert.ok(inst);
  const active = inst.getActiveExtras();
  assert.equal(active.length, 2);
  assert.deepEqual(active.map(c => c.id).sort(), ['A','C']);
});

ok('initialSpeedActive=false starts with speed off', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1], speed:[10,20], extras:[]},
    ids: {svg: 'svg-test'},
    initialSpeedActive: false,
  });
  assert.ok(inst);
  assert.equal(inst.isSpeedActive(), false);
});

ok('initialSpeedActive defaults to true', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1], speed:[10,20], extras:[]},
    ids: {svg: 'svg-test'},
  });
  assert.ok(inst);
  assert.equal(inst.isSpeedActive(), true);
});

ok('drawCursor with out-of-range index clears (no throw)', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1,2], speed:[10,20,30], extras:[]},
    ids: {svg: 'svg-test'},
  });
  inst.drawCursor(-1);
  inst.drawCursor(99);
  inst.drawCursor(0);
});

ok('cursorMode option is accepted (no throw)', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const i1 = ctx.window.createSpeedChart({
    data: {distance:[0,1], speed:[10,20], extras:[]},
    ids: {svg: 'svg-test'}, cursorMode: 'internal',
  });
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const i2 = ctx.window.createSpeedChart({
    data: {distance:[0,1], speed:[10,20], extras:[]},
    ids: {svg: 'svg-test'}, cursorMode: 'external',
  });
  assert.ok(i1);
  assert.ok(i2);
});

ok('multiple instances can co-exist (independent state)', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  docElements['svg-A'] = makeFakeEl();
  docElements['svg-B'] = makeFakeEl();
  const a = ctx.window.createSpeedChart({
    data: {distance:[0,1], speed:[10,20],
           extras: [{id:'X', name:'X', unit:'', data:[1,2], min:1, max:2, mean:1.5}]},
    ids: {svg: 'svg-A'},
    initialActiveExtraIds: ['X'],
  });
  const b = ctx.window.createSpeedChart({
    data: {distance:[0,1], speed:[10,20],
           extras: [{id:'X', name:'X', unit:'', data:[1,2], min:1, max:2, mean:1.5}]},
    ids: {svg: 'svg-B'},
    initialActiveExtraIds: [],
  });
  assert.equal(a.getActiveExtras().length, 1);
  assert.equal(b.getActiveExtras().length, 0);
});

ok('clipPath id derives from svg id (multi-instance safe)', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  docElements['svg-foo'] = makeFakeEl();
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1], speed:[10,20], extras:[]},
    ids: {svg: 'svg-foo'},
  });
  inst.render();
  const html = docElements['svg-foo'].innerHTML || '';
  assert.ok(html.includes('svg-foo-clip'),
            'innerHTML should reference unique clipPath id');
});

// ===== v22.0 setStickyCursor / clearStickyCursor =========================

ok('v22.0: setStickyCursor exists in API', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1,2], speed:[10,20,30], extras:[]},
    ids: {svg: 'svg-test'},
  });
  assert.equal(typeof inst.setStickyCursor, 'function');
  assert.equal(typeof inst.clearStickyCursor, 'function');
});

ok('v22.0: setStickyCursor(idx) in internal mode does not throw', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1,2], speed:[10,20,30], extras:[]},
    ids: {svg: 'svg-test'},
    cursorMode: 'internal',
  });
  inst.setStickyCursor(1);
  inst.setStickyCursor(0);
  inst.clearStickyCursor();
  inst.setStickyCursor(-1);   // negative → treated as clear
  inst.setStickyCursor(null); // null → treated as clear
});

ok('v22.0: external mode setStickyCursor delegates to onCursor', () => {
  Object.keys(docElements).forEach(k => { docElements[k] = makeFakeEl(); });
  const calls = [];
  const inst = ctx.window.createSpeedChart({
    data: {distance:[0,1,2], speed:[10,20,30], extras:[]},
    ids: {svg: 'svg-test'},
    cursorMode: 'external',
    onCursor: (idx, sticky) => calls.push({idx, sticky}),
  });
  inst.setStickyCursor(1);
  assert.deepEqual(calls, [{idx: 1, sticky: true}]);
  inst.clearStickyCursor();
  assert.deepEqual(calls, [{idx: 1, sticky: true}, {idx: -1, sticky: false}]);
});

console.log('');
console.log(pass + ' pass, ' + fail + ' fail');
if (fail > 0) process.exit(1);
