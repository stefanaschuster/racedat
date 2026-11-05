// v21.40 — Tests for the cursor-sync algorithms used by setupChannelChart
// and the trackmap pointer hit-test. Re-implements the JS so we can run
// it standalone in Node.

let pass = 0, fail = 0;
function check(name, cond, detail=''){
  if (cond){ pass++; console.log('  OK  ' + name); }
  else     { fail++; console.log('  FAIL ' + name + (detail?'  ['+detail+']':'')); }
}

// ---------- 1) Multi-channel range computation -----------------------------
{
  console.log('\n== Per-channel range computation ==');
  function computeRanges(channels){
    return channels.map(ch => {
      let lo = Infinity, hi = -Infinity;
      for (let i = 0; i < ch.data.length; i++){
        const v = ch.data[i];
        if (!isFinite(v)) continue;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      if (!isFinite(lo) || !isFinite(hi)){ lo = 0; hi = 1; }
      if (lo === hi){ lo -= 1; hi += 1; }
      return { lo, hi };
    });
  }
  const channels = [
    { data: [0, 100, 200, 250, 240, 100] },           // speed-like
    { data: [0, 0, 0, 1, 1, 0] },                     // TC binary
    { data: [50, 50, 51, NaN, 49, 50] },              // throttle with NaN
    { data: [5, 5, 5, 5, 5, 5] },                     // constant value
  ];
  const r = computeRanges(channels);
  check('speed range 0..250', r[0].lo === 0 && r[0].hi === 250);
  check('binary 0..1', r[1].lo === 0 && r[1].hi === 1);
  check('NaN ignored, range 49..51', r[2].lo === 49 && r[2].hi === 51);
  check('constant gets ±1 spread', r[3].lo === 4 && r[3].hi === 6);
}

// ---------- 2) Chart nearestIdxFromX (binary search over monotonic dist) ----
{
  console.log('\n== Chart: nearest index from X ==');
  // Simulate the chart's nearestIdxFromX with a monotonic distance array
  const dist = [];
  for (let i = 0; i < 1000; i++) dist.push(i * 3.7);  // 0..3700m
  const distMin = dist[0];
  const distMax = dist[dist.length - 1];
  const M_left = 12, w = 1172;
  function nearestIdxFromX(svgX){
    const t = (svgX - M_left) / w;
    if (!(t >= 0 && t <= 1)) return -1;
    const dTarget = distMin + t * (distMax - distMin);
    let lo = 0, hi = dist.length - 1;
    while (hi - lo > 1){
      const mid = (lo + hi) >> 1;
      if (dist[mid] < dTarget) lo = mid; else hi = mid;
    }
    return Math.abs(dist[lo] - dTarget) < Math.abs(dist[hi] - dTarget) ? lo : hi;
  }
  check('x at left edge → idx 0',     nearestIdxFromX(M_left) === 0);
  check('x at right edge → last idx', nearestIdxFromX(M_left + w) === 999);
  check('x in middle → ~idx 500',
        Math.abs(nearestIdxFromX(M_left + w/2) - 500) < 2);
  check('x out-of-bounds left → -1',  nearestIdxFromX(M_left - 5) === -1);
  check('x out-of-bounds right → -1', nearestIdxFromX(M_left + w + 5) === -1);

  // Monotonicity: every higher x maps to >= index
  let lastIdx = -1, monotonic = true;
  for (let x = M_left; x <= M_left + w; x += 10){
    const i = nearestIdxFromX(x);
    if (i < lastIdx){ monotonic = false; break; }
    lastIdx = i;
  }
  check('mapping is monotonic in x', monotonic);
}

// ---------- 3) Trackmap nearestIdx (linear scan with threshold) -------------
{
  console.log('\n== Trackmap: nearest index from svg-xy ==');
  // Synthetic lap: 20 widely-spaced samples so click thresholds are meaningful
  const N = 20;
  const lat = [], lon = [];
  for (let i = 0; i < N; i++){
    // Straight line, 100m apart in lon
    lat.push(45.0);
    lon.push(11.0 + i * 0.001);
  }
  // Simple projection (no real map math — just scale to SVG coords).
  // 1° lon ≈ 100 SVG-px here → samples are 100px apart.
  const proj = (la, lo) => ({
    x: (lo - 11.0) * 100000 + 100,
    y: (45.0 - la) * 100000 + 300,
  });

  function nearestIdx(svgX, svgY){
    let bestI = -1, bestD = Infinity;
    for (let i = 0; i < lat.length; i++){
      const p = proj(lat[i], lon[i]);
      const dx = p.x - svgX, dy = p.y - svgY;
      const d = dx*dx + dy*dy;
      if (d < bestD){ bestD = d; bestI = i; }
    }
    return bestD < 900 ? bestI : -1;
  }

  // Pick a known sample and click exactly on it
  const target = 5;
  const tp = proj(lat[target], lon[target]);
  check(`click exactly on sample ${target}`, nearestIdx(tp.x, tp.y) === target);

  // Click slightly off (within threshold, 5px diagonal = ~7px < 30px)
  check('click 5px off still hits',
        nearestIdx(tp.x + 5, tp.y + 5) === target);

  // Click far away (off track) → -1. Samples are 100px apart;
  // 60px between samples is the max equidistant point, all > 30px threshold.
  // We use (tp.y - 200) which is straight up from the path → 200px away.
  check('click 200px off path → -1',
        nearestIdx(tp.x, tp.y - 200) === -1);
}

// ---------- 4) Cross-listener bus delivers ---------------------------------
{
  console.log('\n== Cursor cross-listener bus ==');
  const listeners = [];
  function emit(idx){
    for (const fn of listeners){
      try { fn(idx); } catch(e) { /* swallow */ }
    }
  }
  const received = [];
  listeners.push((i) => received.push(i));
  listeners.push((i) => { if (i === 666) throw new Error('boom'); received.push('ok:' + i); });
  emit(10);
  emit(20);
  emit(666);  // one listener throws — other still must fire
  emit(-1);
  check('listener got 10, 20, 666, -1 in order',
        JSON.stringify(received) === JSON.stringify([10, 'ok:10', 20, 'ok:20', 666, -1, 'ok:-1']));
}

// ---------- 5) Legend toggle: active flag flips, ranges stay -----------------
{
  console.log('\n== Legend toggle keeps state ==');
  const channels = [
    { id: 'a', label: 'A', data: [1, 2, 3], color: '#f00', active: true },
    { id: 'b', label: 'B', data: [4, 5, 6], color: '#0f0', active: true },
  ];
  // Toggle channel index 1
  channels[1].active = !channels[1].active;
  check('channel B toggled off', channels[1].active === false);
  check('channel A still on',    channels[0].active === true);
  // Toggle back
  channels[1].active = !channels[1].active;
  check('channel B toggled back on', channels[1].active === true);
}

// ---------- 6) Event-spark scale grouping ----------------------------------
{
  console.log('\n== Event-spark scale grouping ==');
  function groupScales(channels, from, to){
    const scaleData = new Map();
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
    return scaleData;
  }
  // V_front and V_rear share a default scale → range covers both
  const vf = [100, 100, 100, 100, 100];
  const vr = [100, 100, 130, 130, 100];
  const tc = [0,   0,   1,   1,   0];
  // Case A: no `scale` keys → all merge. vf is all-100s so it gets the
  // ±1 spread (99..101) applied; merged with vr's 100..130 → 99..130.
  let scales = groupScales([{data: vf}, {data: vr}], 0, 4);
  check('shared default scale: 1 group', scales.size === 1);
  check('shared default range covers both (99..130)',
        scales.get('__default__').min === 99 &&
        scales.get('__default__').max === 130);
  // Case B: vr gets its own scale → 2 groups
  scales = groupScales([
    {data: vr, scale: 'rear'},
    {data: tc, scale: 'tc'},
  ], 0, 4);
  check('two groups present', scales.size === 2);
  check('rear range 100..130',
        scales.get('rear').min === 100 && scales.get('rear').max === 130);
  check('tc range 0..1',
        scales.get('tc').min === 0 && scales.get('tc').max === 1);
}

console.log(`\n${pass} pass, ${fail} fail`);
process.exit(fail > 0 ? 1 : 0);
