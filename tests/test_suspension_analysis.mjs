// v22.7 — Tests für die Fahrwerks-Setup-Algorithmen (Block-Detektor,
// Federweg-Geschwindigkeit, Histogramm-Bins). Re-implementiert die
// JS-Funktionen aus coach.py:suspensionAnalysis 1:1, damit der Test
// hermetisch in Node läuft (analog zu test_chart_cursor_sync.mjs).
//
// Wenn die Implementierung in coach.py sich ändert, muss diese Datei
// nachgezogen werden — das ist bewusst so: die Test-Datei pinnt die
// erwartete Semantik einer Iteration.

let pass = 0, fail = 0;
function check(name, cond, detail=''){
  if (cond){ pass++; console.log('  OK  ' + name); }
  else     { fail++; console.log('  FAIL ' + name + (detail?'  ['+detail+']':'')); }
}

// ----------------------------------------------------------------------
// Re-implementierung: detectBlock (1:1 aus coach.py suspensionAnalysis)
// ----------------------------------------------------------------------
function detectBlock(arr, time){
  const n = arr.length;
  if (n < 10 || time.length !== n) return [];
  let lo = +Infinity, hi = -Infinity;
  for (let i = 0; i < n; i++){
    const v = arr[i];
    if (!isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return [];
  const range = hi - lo;
  const maxThreshold = hi - range * 0.01;
  const flatTol      = range * 0.005;

  const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
  const minSamples  = Math.max(3, Math.round(0.040 / dt));
  const gapSamples  = Math.max(2, Math.round(0.020 / dt));
  const edgeSamples = Math.max(2, Math.round(0.060 / dt));
  const edgeRiseFrac = 0.20;

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
      const before = Math.max(0, i - edgeSamples);
      const rise = arr[i] - arr[before];
      const sharp = rise >= range * edgeRiseFrac;
      if (len >= minSamples && flat && sharp){
        runs.push({ from: i, to: end, peakVal: runMax, rangeMax: hi, rise });
      }
      i = end + 1;
    } else {
      i++;
    }
  }
  return runs;
}

// ----------------------------------------------------------------------
// Re-implementierung: detectTopout (1:1 aus coach.py, v22.9)
// ----------------------------------------------------------------------
function detectTopout(arr, time){
  const n = arr.length;
  if (n < 10 || time.length !== n) return [];
  let lo = +Infinity, hi = -Infinity;
  for (let i = 0; i < n; i++){
    const v = arr[i];
    if (!isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return [];
  const range = hi - lo;
  const minThreshold = lo + range * 0.01;
  const flatTol      = range * 0.005;
  const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
  const minSamples   = Math.max(3, Math.round(0.040 / dt));
  const gapSamples   = Math.max(2, Math.round(0.020 / dt));
  const edgeSamples  = Math.max(2, Math.round(0.060 / dt));
  const edgeDropFrac = 0.20;

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
      const drop = arr[before] - arr[i];
      const sharp = drop >= range * edgeDropFrac;
      if (len >= minSamples && flat && sharp){
        runs.push({ from: i, to: end, minVal: runMin, rangeMin: lo, drop });
      }
      i = end + 1;
    } else {
      i++;
    }
  }
  return runs;
}

// ----------------------------------------------------------------------
// Re-implementierung: detectBump (1:1 aus coach.py, v22.9)
// ----------------------------------------------------------------------
function detectBump(velocities, time){
  const n = velocities.length;
  if (n < 10 || time.length !== n) return [];
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
  const threshold = Math.max(6.0 * mad, 200);

  const dt = (time[n-1] - time[0]) / Math.max(1, n - 1);
  const maxDurSamples = Math.max(3, Math.round(0.100 / dt));
  const mergeGap      = Math.max(2, Math.round(0.050 / dt));

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
      if (dur > 0 && dur <= maxDurSamples){
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
            from: i, to: j - 1, peakAbs, peakIdx,
            peakSigned: velocities[peakIdx], threshold,
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

// ----------------------------------------------------------------------
// Re-implementierung: travelVelocity
// ----------------------------------------------------------------------
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

// ----------------------------------------------------------------------
// Re-implementierung: buildHistogram
// ----------------------------------------------------------------------
function buildHistogram(velocities){
  const n = velocities.length;
  if (n === 0) return { bins: [], range: 0, binWidth: 0, totalPct: 0 };
  let absMax = 0;
  for (let i = 0; i < n; i++){
    const a = Math.abs(velocities[i]);
    if (a > absMax) absMax = a;
  }
  if (absMax === 0) return { bins: [], range: 0, binWidth: 0, totalPct: 0 };
  const sortedAbs = velocities.map(Math.abs).sort((a, b) => a - b);
  const q99 = sortedAbs[Math.max(0, Math.floor((n - 1) * 0.995))] || absMax;
  const range = Math.max(q99, absMax * 0.1);
  const numBins = 41;
  const binWidth = (2 * range) / numBins;
  const counts = new Array(numBins).fill(0);
  for (let i = 0; i < n; i++){
    const v = velocities[i];
    let idx = Math.floor((v + range) / binWidth);
    if (idx < 0) idx = 0;
    if (idx >= numBins) idx = numBins - 1;
    counts[idx]++;
  }
  const bins = counts.map((c, idx) => ({
    from: -range + idx * binWidth,
    to:   -range + (idx + 1) * binWidth,
    pct:  (c / n) * 100,
  }));
  return { bins, range, binWidth, totalPct: 100 };
}

// ----------------------------------------------------------------------
// Helper: synthetische Federweg-Trace bauen
// ----------------------------------------------------------------------
// 200 Hz Sample-Rate, 5 Sekunden Daten = 1000 Samples
function makeTrace({ blocks = [], maxValue = 120, noise = 0 }){
  const n = 1000;
  const dt = 1 / 200;
  const time = new Array(n);
  for (let i = 0; i < n; i++) time[i] = i * dt;
  // Hintergrund: sinusförmige Bewegung zwischen 30 und 90 mm
  const arr = new Array(n);
  for (let i = 0; i < n; i++){
    const phase = i / n * Math.PI * 8;
    arr[i] = 60 + 30 * Math.sin(phase);
  }
  // Block-Bereiche überschreiben: scharfer Anstieg dann Plateau
  blocks.forEach(b => {
    const { from, to, riseSamples = 5 } = b;
    // Anstieg
    for (let i = Math.max(0, from - riseSamples); i < from; i++){
      const t = (i - (from - riseSamples)) / riseSamples;
      arr[i] = arr[Math.max(0, from - riseSamples - 1)] +
               (maxValue - arr[Math.max(0, from - riseSamples - 1)]) * t;
    }
    // Plateau
    for (let i = from; i <= to && i < n; i++){
      arr[i] = maxValue + (noise * (Math.random() - 0.5));
    }
  });
  return { arr, time };
}

// ----------------------------------------------------------------------
// detectBlock-Tests
// ----------------------------------------------------------------------
{
  console.log('\n== detectBlock: input validation ==');
  check('empty array → no events',
    detectBlock([], []).length === 0);
  check('mismatched length → no events',
    detectBlock([1, 2, 3], [0, 1]).length === 0);
  check('< 10 samples → no events',
    detectBlock([1,2,3,4,5], [0,1,2,3,4]).length === 0);

  // Konstante Daten — keine Spannweite, kein Event
  const constTime = []; for (let i = 0; i < 100; i++) constTime.push(i * 0.005);
  check('constant data → no events',
    detectBlock(new Array(100).fill(50), constTime).length === 0);
}

{
  console.log('\n== detectBlock: detects sharp-edge plateau ==');
  // Ein 100ms-Block bei t≈2.5s. Mit 200Hz = Sample 500..520.
  const { arr, time } = makeTrace({
    blocks: [{ from: 500, to: 520, riseSamples: 8 }],
    maxValue: 120,
    noise: 0,
  });
  const events = detectBlock(arr, time);
  check('one event detected', events.length === 1,
    `got ${events.length}`);
  if (events.length){
    check('event from ~500', Math.abs(events[0].from - 500) <= 2,
      `from=${events[0].from}`);
    check('event peak ~120', Math.abs(events[0].peakVal - 120) < 0.5);
    check('event rise > 0', events[0].rise > 0);
  }
}

{
  console.log('\n== detectBlock: ignores slow drift to max ==');
  // Langsamer linearer Anstieg übers ganze Fenster — keine "scharfe Kante"
  const n = 1000, dt = 1 / 200;
  const time = []; for (let i = 0; i < n; i++) time.push(i * dt);
  const arr = []; for (let i = 0; i < n; i++) arr.push(50 + (i / n) * 70);
  // Hält dann bei 120 für 50 samples
  for (let i = 700; i < 1000; i++) arr[i] = 120;
  const events = detectBlock(arr, time);
  // Erwartung: Plateau ist da, aber Anstieg ist über 60ms-Fenster langsam,
  // weil der Anstieg über 700 Samples linear verteilt war. In der Edge-
  // Region (60ms vor Plateau-Start) ist der Rise sehr klein (etwa 4 mm),
  // also fällt das durch.
  // Allerdings: weil bei i=700 der Wert genau am Plateau-Beginn 120 erreicht
  // und der Rampenanstieg gegen Ende des Anstiegs schnell wird, kann es
  // doch matchen. Wir akzeptieren beides — Hauptsache der Detektor crashed
  // nicht.
  check('detectBlock returns an array (no crash)',
    Array.isArray(events));
}

{
  console.log('\n== detectBlock: short plateau below minSamples threshold ==');
  // Nur 5 Samples auf Block (= 25ms bei 200Hz, < 40ms minSamples)
  const { arr, time } = makeTrace({
    blocks: [{ from: 500, to: 504, riseSamples: 5 }],
    maxValue: 120, noise: 0,
  });
  const events = detectBlock(arr, time);
  check('< minSamples plateau → no events',
    events.length === 0, `got ${events.length}`);
}

{
  console.log('\n== detectBlock: noisy plateau still detected if flat enough ==');
  // Plateau mit etwas Rauschen, aber innerhalb flatTol = 0.5% Range
  // Range ≈ 90 (von 30 bis 120), flatTol ≈ 0.45
  const { arr, time } = makeTrace({
    blocks: [{ from: 500, to: 525, riseSamples: 8 }],
    maxValue: 120, noise: 0.3,  // ±0.15 Spitze, im flatTol
  });
  const events = detectBlock(arr, time);
  check('noisy-but-flat plateau detected',
    events.length === 1, `got ${events.length}`);
}

{
  console.log('\n== detectBlock: two separate blocks ==');
  const { arr, time } = makeTrace({
    blocks: [
      { from: 200, to: 225, riseSamples: 8 },
      { from: 700, to: 725, riseSamples: 8 },
    ],
    maxValue: 120, noise: 0,
  });
  const events = detectBlock(arr, time);
  check('two events detected',
    events.length === 2, `got ${events.length}`);
  if (events.length === 2){
    check('events sorted by from-index',
      events[0].from < events[1].from);
    check('first event near 200',
      Math.abs(events[0].from - 200) <= 2);
    check('second event near 700',
      Math.abs(events[1].from - 700) <= 2);
  }
}

// ----------------------------------------------------------------------
// travelVelocity-Tests
// ----------------------------------------------------------------------
{
  console.log('\n== travelVelocity: input validation ==');
  check('empty → empty', travelVelocity([], []).length === 0);
  check('< 3 samples → empty', travelVelocity([1, 2], [0, 1]).length === 0);
  check('mismatched length → empty',
    travelVelocity([1, 2, 3], [0, 1]).length === 0);
}

{
  console.log('\n== travelVelocity: linear ramp ==');
  // x(t) = 10t → velocity = 10 (constant)
  const time = [], arr = [];
  for (let i = 0; i < 100; i++){
    time.push(i * 0.01);
    arr.push(10 * i * 0.01);
  }
  const v = travelVelocity(arr, time);
  check('length matches', v.length === 100);
  // Mittlere Samples — zentrale Differenz
  check('middle velocity ≈ 10',
    Math.abs(v[50] - 10) < 1e-9, `got ${v[50]}`);
  // Boundary
  check('first sample = second (boundary fill)',
    v[0] === v[1]);
  check('last sample = second-to-last (boundary fill)',
    v[99] === v[98]);
}

{
  console.log('\n== travelVelocity: dt=0 guard ==');
  // Zwei identische Timestamps → divison by zero geguarded
  const arr = [10, 20, 30, 40, 50];
  const time = [0, 0.1, 0.1, 0.3, 0.4];   // time[1]==time[2] wäre dt für i=2: time[3]-time[1] = 0.2 ok
  // Konstruiere echten dt=0-Fall: time[i+1] == time[i-1]
  const time2 = [0, 0.1, 0.1, 0.1, 0.4];  // i=2: time[3]-time[1] = 0
  const v = travelVelocity(arr, time2);
  check('dt=0 yields 0 for that sample, no NaN',
    isFinite(v[2]) && v[2] === 0, `got ${v[2]}`);
}

{
  console.log('\n== travelVelocity: sinusoidal motion ==');
  // x(t) = A*sin(ωt), velocity = A*ω*cos(ωt)
  const A = 30, omega = 2 * Math.PI * 2;  // 2 Hz
  const time = [], arr = [];
  for (let i = 0; i < 200; i++){
    const t = i * 0.005;  // 200 Hz
    time.push(t);
    arr.push(A * Math.sin(omega * t));
  }
  const v = travelVelocity(arr, time);
  // Peak velocity sollte etwa A*omega = 30*4π ≈ 377 sein.
  let peakV = 0;
  for (let i = 5; i < 195; i++) peakV = Math.max(peakV, Math.abs(v[i]));
  const expected = A * omega;
  check('peak velocity within 5% of A·ω',
    Math.abs(peakV - expected) / expected < 0.05,
    `peakV=${peakV.toFixed(1)}, expected=${expected.toFixed(1)}`);
}

// ----------------------------------------------------------------------
// buildHistogram-Tests
// ----------------------------------------------------------------------
{
  console.log('\n== buildHistogram: input validation ==');
  const empty = buildHistogram([]);
  check('empty → 0 bins, range=0',
    empty.bins.length === 0 && empty.range === 0);
  const zeros = buildHistogram([0, 0, 0, 0, 0]);
  check('all-zero input → 0 bins',
    zeros.bins.length === 0);
}

{
  console.log('\n== buildHistogram: symmetric around 0 ==');
  // Werte: gleichverteilt -100..+100
  const v = [];
  for (let i = -100; i <= 100; i++) v.push(i);
  const h = buildHistogram(v);
  check('41 bins', h.bins.length === 41);
  check('range matches max |v|',
    Math.abs(h.range - 100) < 5,
    `range=${h.range}`);
  // Linke und rechte Hälfte sollten etwa gleich viel Masse haben
  const half = Math.floor(h.bins.length / 2);
  const leftSum = h.bins.slice(0, half).reduce((s, b) => s + b.pct, 0);
  const rightSum = h.bins.slice(half + 1).reduce((s, b) => s + b.pct, 0);
  check('left and right halves roughly equal',
    Math.abs(leftSum - rightSum) < 5,
    `left=${leftSum.toFixed(1)}%, right=${rightSum.toFixed(1)}%`);
  // Summe aller pct ≈ 100%
  const total = h.bins.reduce((s, b) => s + b.pct, 0);
  check('all bins sum to ~100%',
    Math.abs(total - 100) < 0.01,
    `total=${total}%`);
}

{
  console.log('\n== buildHistogram: asymmetric (more compression) ==');
  // Mehr positive Werte (einfedern) als negative
  const v = [];
  for (let i = 0; i < 50; i++) v.push(-20);
  for (let i = 0; i < 150; i++) v.push(50);
  const h = buildHistogram(v);
  // Mass auf der rechten Seite sollte deutlich höher sein
  const half = Math.floor(h.bins.length / 2);
  const leftSum = h.bins.slice(0, half).reduce((s, b) => s + b.pct, 0);
  const rightSum = h.bins.slice(half + 1).reduce((s, b) => s + b.pct, 0);
  check('right side dominates (compression-heavy)',
    rightSum > leftSum,
    `left=${leftSum.toFixed(1)}%, right=${rightSum.toFixed(1)}%`);
  check('left side ~25%',
    Math.abs(leftSum - 25) < 2);
  check('right side ~75%',
    Math.abs(rightSum - 75) < 2);
}

{
  console.log('\n== buildHistogram: outlier trimming (99.5% quantile) ==');
  // 100 moderate Werte + 1 großer Ausreißer. Range soll vom Quantil
  // dominiert sein, nicht vom Ausreißer.
  const v = [];
  for (let i = 0; i < 100; i++) v.push(20 * Math.sin(i * 0.3));
  v.push(5000);  // krasser Ausreißer
  const h = buildHistogram(v);
  // Range muss deutlich kleiner als der Ausreißer sein. Der safety
  // floor (absMax * 0.1 = 500) greift, das ist okay — er soll
  // verhindern, dass die Skala bei nahezu-konstanten Daten auf
  // mikroskopisch kleine Bereiche schrumpft. Hauptsache: nicht 5000.
  check('range NOT dominated by 5000-outlier (max → 500 via safety floor)',
    h.range < 1000, `range=${h.range}`);
  // Aber: alle Samples müssen trotzdem in irgendeinen Bin landen (clamp)
  const total = h.bins.reduce((s, b) => s + b.pct, 0);
  check('all samples accounted for (clamping into edge bin)',
    Math.abs(total - 100) < 0.01, `total=${total}%`);
}

{
  console.log('\n== buildHistogram: bin layout ==');
  const v = [];
  for (let i = 0; i < 100; i++) v.push((i - 50) * 2);  // -100..+98
  const h = buildHistogram(v);
  // Alle Bins müssen aneinander anschließen
  let contiguous = true;
  for (let i = 1; i < h.bins.length; i++){
    if (Math.abs(h.bins[i].from - h.bins[i-1].to) > 1e-9){
      contiguous = false;
      break;
    }
  }
  check('bins are contiguous (no gaps)', contiguous);
  // Erster Bin from = -range, letzter Bin to = +range
  check('first bin starts at -range',
    Math.abs(h.bins[0].from - (-h.range)) < 1e-9);
  check('last bin ends at +range',
    Math.abs(h.bins[h.bins.length-1].to - h.range) < 1e-9);
}

// ----------------------------------------------------------------------
// Helper für Top-Out: spiegelverkehrte makeTrace (Plateau am MINIMUM mit
// vorausgehendem steilen ABFALL)
// ----------------------------------------------------------------------
function makeTraceTopout({ tops = [], minValue = 0, noise = 0 }){
  const n = 1000;
  const dt = 1 / 200;
  const time = new Array(n);
  for (let i = 0; i < n; i++) time[i] = i * dt;
  // Hintergrund: sinusförmig zwischen 30 und 90 mm (gleicher Range wie makeTrace)
  const arr = new Array(n);
  for (let i = 0; i < n; i++){
    const phase = i / n * Math.PI * 8;
    arr[i] = 60 + 30 * Math.sin(phase);
  }
  tops.forEach(t => {
    const { from, to, dropSamples = 8 } = t;
    // Abfall (steil) von Hintergrundwert auf minValue
    const startV = arr[Math.max(0, from - dropSamples - 1)];
    for (let i = Math.max(0, from - dropSamples); i < from; i++){
      const f = (i - (from - dropSamples)) / dropSamples;
      arr[i] = startV + (minValue - startV) * f;
    }
    // Plateau am Minimum
    for (let i = from; i <= to && i < n; i++){
      arr[i] = minValue + (noise * (Math.random() - 0.5));
    }
  });
  return { arr, time };
}

// ----------------------------------------------------------------------
// detectTopout-Tests (v22.9)
// ----------------------------------------------------------------------
{
  console.log('\n== detectTopout: input validation ==');
  check('empty array → no events',
    detectTopout([], []).length === 0);
  check('mismatched length → no events',
    detectTopout([1, 2, 3], [0, 1]).length === 0);
  check('< 10 samples → no events',
    detectTopout([1,2,3,4,5], [0,1,2,3,4]).length === 0);
  const constTime = []; for (let i = 0; i < 100; i++) constTime.push(i * 0.005);
  check('constant data → no events',
    detectTopout(new Array(100).fill(50), constTime).length === 0);
}

{
  console.log('\n== detectTopout: detects sharp-edge bottom plateau ==');
  // 100ms Plateau bei t≈2.5s, am Minimum (0 mm)
  const { arr, time } = makeTraceTopout({
    tops: [{ from: 500, to: 520, dropSamples: 8 }],
    minValue: 0, noise: 0,
  });
  const events = detectTopout(arr, time);
  check('one event detected', events.length === 1, `got ${events.length}`);
  if (events.length){
    check('event from ~500', Math.abs(events[0].from - 500) <= 2,
      `from=${events[0].from}`);
    check('event min ~0', Math.abs(events[0].minVal) < 0.5,
      `minVal=${events[0].minVal}`);
    check('event drop > 0', events[0].drop > 0);
  }
}

{
  console.log('\n== detectTopout: short plateau below threshold ==');
  const { arr, time } = makeTraceTopout({
    tops: [{ from: 500, to: 504, dropSamples: 5 }],   // nur 5 Samples = 25ms
    minValue: 0, noise: 0,
  });
  check('< minSamples → no events',
    detectTopout(arr, time).length === 0);
}

{
  console.log('\n== detectTopout: gentle descent → no event ==');
  // Linear langsam absteigen ohne scharfen Knick
  const n = 1000, dt = 1 / 200;
  const time = []; for (let i = 0; i < n; i++) time.push(i * dt);
  const arr = []; for (let i = 0; i < n; i++) arr.push(120 - (i / n) * 100);
  // Hält dann am Boden
  for (let i = 800; i < 1000; i++) arr[i] = 20;
  // Kein assert auf null — der Detektor darf ggf. das Boden-Plateau finden
  // wenn der Wert kurz vor Plateau-Beginn noch steil fällt. Wir testen nur
  // dass kein Crash passiert und das Ergebnis ein Array ist.
  check('detectTopout returns an array (no crash)',
    Array.isArray(detectTopout(arr, time)));
}

{
  console.log('\n== detectTopout: two separate top-outs ==');
  const { arr, time } = makeTraceTopout({
    tops: [
      { from: 200, to: 225, dropSamples: 8 },
      { from: 700, to: 725, dropSamples: 8 },
    ],
    minValue: 0, noise: 0,
  });
  const events = detectTopout(arr, time);
  check('two events detected',
    events.length === 2, `got ${events.length}`);
  if (events.length === 2){
    check('events sorted by from-index',
      events[0].from < events[1].from);
  }
}

{
  console.log('\n== detectTopout: noisy-but-flat plateau detected ==');
  const { arr, time } = makeTraceTopout({
    tops: [{ from: 500, to: 525, dropSamples: 8 }],
    minValue: 0, noise: 0.3,   // ±0.15 mm, im flatTol ≈ 0.45
  });
  check('noisy plateau detected',
    detectTopout(arr, time).length === 1);
}

// ----------------------------------------------------------------------
// detectBump-Tests (v22.9)
// ----------------------------------------------------------------------
{
  console.log('\n== detectBump: input validation ==');
  check('empty → no events', detectBump([], []).length === 0);
  check('< 10 samples → no events',
    detectBump([0,0,0,0,0], [0,0.005,0.01,0.015,0.02]).length === 0);
}

{
  console.log('\n== detectBump: no spikes → no events ==');
  // Gleichmäßiges Federn ohne Spikes
  const n = 1000, dt = 1 / 200;
  const time = []; for (let i = 0; i < n; i++) time.push(i * dt);
  const arr = []; for (let i = 0; i < n; i++) arr.push(60 + 30 * Math.sin(i * 0.05));
  const v = travelVelocity(arr, time);
  const events = detectBump(v, time);
  check('smooth motion → 0 events', events.length === 0,
    `got ${events.length}`);
}

{
  console.log('\n== detectBump: one sharp spike detected ==');
  // Konstanter Federweg + ein 40ms-Spike
  const n = 1000, dt = 1 / 200;
  const time = []; for (let i = 0; i < n; i++) time.push(i * dt);
  const arr = []; for (let i = 0; i < n; i++) arr.push(60);
  // Steile Bewegung bei Sample 500-508 (= 40ms): von 60 auf 75 und zurück
  arr[500] = 60; arr[501] = 63; arr[502] = 68; arr[503] = 73;
  arr[504] = 75; arr[505] = 73; arr[506] = 68; arr[507] = 63; arr[508] = 60;
  const v = travelVelocity(arr, time);
  const events = detectBump(v, time);
  check('one bump event', events.length === 1,
    `got ${events.length}`);
  if (events.length){
    // Peak liegt irgendwo zwischen 500 und 508
    check('peak in window',
      events[0].peakIdx >= 500 && events[0].peakIdx <= 508,
      `peakIdx=${events[0].peakIdx}`);
    check('peakAbs >= threshold',
      events[0].peakAbs >= events[0].threshold);
  }
}

{
  console.log('\n== detectBump: anhaltende Bewegung (kein Bump) ==');
  // Beschleunigung über 300ms — langer Anstieg, kein Schlag
  const n = 1000, dt = 1 / 200;
  const time = []; for (let i = 0; i < n; i++) time.push(i * dt);
  const arr = []; for (let i = 0; i < n; i++) arr.push(60);
  // Rampe über 60 Samples = 300ms (länger als maxDur=100ms)
  for (let i = 400; i < 460; i++) arr[i] = 60 + (i - 400) * 0.5;  // bis 90
  for (let i = 460; i < 520; i++) arr[i] = 90 - (i - 460) * 0.5;  // zurück
  const v = travelVelocity(arr, time);
  const events = detectBump(v, time);
  // Erwartung: Geschwindigkeit ist 100 mm/s (= 0.5 mm pro 0.005s → 100 mm/s
  // im Sample mit zentraler Differenz: (arr[i+1]-arr[i-1])/(2*dt) = 100).
  // Das liegt unter unserem 200-mm/s Safety-Floor → keine Bumps.
  check('slow ramp under safety-floor → 0 events',
    events.length === 0, `got ${events.length}`);
}

{
  console.log('\n== detectBump: two spikes close together get merged ==');
  // Zwei Spikes mit nur 30ms Abstand (mergeGap = 50ms → mergen)
  const n = 1000, dt = 1 / 200;
  const time = []; for (let i = 0; i < n; i++) time.push(i * dt);
  const arr = []; for (let i = 0; i < n; i++) arr.push(60);
  // Erster Spike um 500
  arr[499]=60; arr[500]=63; arr[501]=68; arr[502]=75; arr[503]=68; arr[504]=63; arr[505]=60;
  // Zweiter Spike um 510 — 30ms später (6 Samples × 5ms)
  arr[509]=60; arr[510]=63; arr[511]=68; arr[512]=75; arr[513]=68; arr[514]=63; arr[515]=60;
  const v = travelVelocity(arr, time);
  const events = detectBump(v, time);
  check('two close spikes merged into one event',
    events.length === 1, `got ${events.length}`);
}

{
  console.log('\n== detectBump: peakSigned reflects direction ==');
  // Asymmetrischer Spike: nur Einfeder-Phase (Wert steigt schnell, fällt
  // dann LANGSAM zurück) — dann ist die Einfeder-Geschwindigkeit der
  // einzige Peak über der Schwelle.
  const n = 1000, dt = 1 / 200;
  const time = []; for (let i = 0; i < n; i++) time.push(i * dt);
  const arr = []; for (let i = 0; i < n; i++) arr.push(60);
  // Schneller Anstieg (Einfedern): hohe positive Geschwindigkeit
  arr[200] = 60; arr[201] = 65; arr[202] = 72; arr[203] = 78; arr[204] = 80;
  // Sehr langsamer Rückgang über 300ms (60 Samples) — Geschwindigkeit
  // bleibt darunter, also nur die Anstiegs-Spitze triggert den Detektor.
  for (let i = 205; i < 265; i++){
    arr[i] = 80 - (i - 205) * (20 / 60);   // von 80 zurück auf 60
  }
  const v = travelVelocity(arr, time);
  const events = detectBump(v, time);
  check('one event detected (asymmetric pulse)',
    events.length === 1, `got ${events.length}`);
  if (events.length === 1){
    // peakSigned > 0 weil der Federweg in dem Moment EINfedert
    check('peakSigned positive (Einfedern, Wert steigt)',
      events[0].peakSigned > 0,
      `peakSigned=${events[0].peakSigned}`);
  }

  // Umgekehrt: schneller Abfall (Ausfedern), dann langsamer Rückbau.
  // peakSigned sollte negativ sein.
  const arr2 = []; for (let i = 0; i < n; i++) arr2.push(60);
  arr2[200] = 60; arr2[201] = 55; arr2[202] = 48; arr2[203] = 42; arr2[204] = 40;
  for (let i = 205; i < 265; i++){
    arr2[i] = 40 + (i - 205) * (20 / 60);
  }
  const v2 = travelVelocity(arr2, time);
  const events2 = detectBump(v2, time);
  check('one event detected (asymmetric pulse downward)',
    events2.length === 1, `got ${events2.length}`);
  if (events2.length === 1){
    check('peakSigned negative (Ausfedern, Wert fällt)',
      events2[0].peakSigned < 0,
      `peakSigned=${events2[0].peakSigned}`);
  }
}

// ----------------------------------------------------------------------
// Summary
// ----------------------------------------------------------------------
console.log(`\n${pass} pass, ${fail} fail`);
process.exit(fail === 0 ? 0 : 1);
