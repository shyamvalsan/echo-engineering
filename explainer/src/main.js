(() => {
  'use strict';
  const D = window.ECHO_DATA;
  const S = D.signals;
  const FS = S.fs;
  const C = 343; // m/s
  const R0 = 3; // posts start 3 m out
  const DR = C / (2 * FS); // metres of range per sample of echo (1.07 cm)
  const CLAPS = S.claps.map((a) => Float32Array.from(a));
  const TARGETS = { bird: Float32Array.from(S.targets.bird), motif: Float32Array.from(S.targets.motif) };
  const root = document.documentElement;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = (sel, el = document) => el.querySelector(sel);
  const fmt = (x, d = 1) => x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

  // ---------- theme ----------
  const themeBtn = $('#themeToggle');
  const isDark = () => (root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches);
  try { const t = localStorage.getItem('echo-theme'); if (t) root.dataset.theme = t; } catch (e) { /* storage unavailable */ }
  const syncThemeBtn = () => { themeBtn.textContent = isDark() ? 'Light' : 'Dark'; };
  themeBtn.addEventListener('click', () => {
    root.dataset.theme = isDark() ? 'light' : 'dark';
    try { localStorage.setItem('echo-theme', root.dataset.theme); } catch (e) { /* ignore */ }
    syncThemeBtn(); redrawAll();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { syncThemeBtn(); redrawAll(); });
  syncThemeBtn();
  let palette = {};
  function readPalette() {
    const cs = getComputedStyle(root);
    for (const k of ['bg', 'fig', 'ink', 'muted', 'rule', 'accent', 'warn', 'ok']) palette[k] = cs.getPropertyValue('--' + k).trim();
  }

  // ---------- canvas ----------
  function setup(cv) {
    const w = cv.clientWidth || 300;
    const h = +cv.dataset.h;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); cv.style.height = h + 'px';
    }
    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    g.font = '12px ' + getComputedStyle(document.body).getPropertyValue('--sans');
    g.font = '12px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
    return { g, w, h };
  }
  // min/max envelope of x[i0..i1) drawn into the box (x0, y0, w, h), centred, scaled by amp
  function wave(g, x, i0, i1, bx, by, bw, bh, amp, color) {
    g.strokeStyle = color; g.fillStyle = color; g.lineWidth = 1;
    const mid = by + bh / 2;
    const per = (i1 - i0) / bw;
    g.beginPath();
    for (let px = 0; px < bw; px++) {
      const a = Math.floor(i0 + px * per), b = Math.max(a + 1, Math.floor(i0 + (px + 1) * per));
      let lo = 0, hi = 0;
      for (let i = a; i < b; i++) { const v = i >= 0 && i < x.length ? x[i] : 0; if (v < lo) lo = v; if (v > hi) hi = v; }
      g.moveTo(bx + px + 0.5, mid - hi * amp * bh / 2 - 0.5);
      g.lineTo(bx + px + 0.5, mid - lo * amp * bh / 2 + 0.5);
    }
    g.stroke();
  }
  function text(g, s, x, y, color, align = 'left', base = 'alphabetic') {
    g.fillStyle = color; g.textAlign = align; g.textBaseline = base; g.fillText(s, x, y);
  }
  function rng(seed) { // mulberry32
    return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }

  // ---------- audio ----------
  let actx = null, current = null;
  window.__echoPlays = 0;
  function ac() {
    if (!actx) { const AC = window.AudioContext || window.webkitAudioContext; actx = new AC(); window.__echoCtx = actx; }
    if (actx.state === 'suspended') actx.resume();
    return actx;
  }
  function playBuffer(b) {
    const c = ac();
    if (current) { try { current.stop(); } catch (e) { /* already stopped */ } }
    const s = c.createBufferSource(); s.buffer = b;
    const gain = c.createGain(); gain.gain.value = 0.85;
    s.connect(gain); gain.connect(c.destination); s.start();
    current = s; window.__echoPlays++;
    return b.duration;
  }
  function play(x) {
    const b = ac().createBuffer(1, x.length, FS); b.getChannelData(0).set(x); return playBuffer(b);
  }

  // ---------- signal helpers (the "Tier 0" idea: echo = clap convolved with a train of delayed copies) ----------
  function conv(x, h) {
    const y = new Float32Array(x.length + h.length - 1);
    for (let i = 0; i < x.length; i++) { const a = x[i]; if (a === 0) continue; for (let j = 0; j < h.length; j++) y[i + j] += a * h[j]; }
    return y;
  }
  const peak = (x) => { let m = 0; for (let i = 0; i < x.length; i++) { const a = Math.abs(x[i]); if (a > m) m = a; } return m; };
  const energy = (x) => { let e = 0; for (let i = 0; i < x.length; i++) e += x[i] * x[i]; return e; };
  const LEAD = Math.round(0.03 * FS);
  // clap at LEAD, echo starting delay samples later, echo scaled to peak echoPeak. Returns {buf, echoGainDb}.
  function mix(clap, echo, delay, trueRel, echoPeak = 0.55) {
    const n = LEAD + delay + echo.length + Math.round(0.12 * FS);
    const out = new Float32Array(n);
    const cp = peak(clap) || 1;
    for (let i = 0; i < clap.length; i++) out[LEAD + i] += 0.9 * clap[i] / cp;
    const g = echoPeak / (peak(echo) || 1);
    for (let i = 0; i < echo.length; i++) out[LEAD + delay + i] += echo[i] * g;
    return { buf: out, boostDb: trueRel ? 20 * Math.log10((echoPeak / 0.9) / trueRel) : null };
  }
  function movingMax(a, half) {
    const o = new Float32Array(a.length);
    for (let i = 0; i < a.length; i++) { let m = 0; for (let j = Math.max(0, i - half); j <= Math.min(a.length - 1, i + half); j++) if (a[j] > m) m = a[j]; o[i] = m; }
    return o;
  }
  function movingAvg(a, half) {
    const o = new Float32Array(a.length);
    for (let i = 0; i < a.length; i++) { let s = 0, n = 0; for (let j = i - half; j <= i + half; j++) { s += j >= 0 && j < a.length ? a[j] : 0; n++; } o[i] = s / n; }
    return o;
  }
  // Real posts: profile = smooth bias + signal, never negative. Bias >= |signal| everywhere by construction.
  const designs = {};
  function design(name) {
    if (designs[name]) return designs[name];
    const t = TARGETS[name];
    const bias = movingAvg(movingMax(t.map(Math.abs), Math.round(0.003 * FS)), Math.round(0.0015 * FS));
    const prof = new Float32Array(t.length);
    let sumAbs = 0, sumP = 0;
    for (let i = 0; i < t.length; i++) { prof[i] = bias[i] + t[i]; sumAbs += Math.abs(t[i]); sumP += prof[i]; }
    designs[name] = { t, bias, prof, useful: sumAbs / sumP };
    return designs[name];
  }
  // band-limited ideal click, 500 Hz to 4 kHz (windowed-sinc band-pass), so the comparison is fair within the band
  const IDEAL = (() => {
    const n = 129, m = 64, h = new Float32Array(n);
    const sinc = (x) => (x === 0 ? 1 : Math.sin(Math.PI * x) / (Math.PI * x));
    for (let i = 0; i < n; i++) {
      const k = i - m, w = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1));
      h[i] = w * (2 * 4000 / FS * sinc(2 * 4000 / FS * k) - 2 * 500 / FS * sinc(2 * 500 / FS * k));
    }
    const p = peak(h); for (let i = 0; i < n; i++) h[i] /= p;
    return h;
  })();
  const D0 = Math.round(2 * R0 / C * FS); // delay of the first post, samples
  const NOTE = ['C', 'C sharp', 'D', 'E flat', 'E', 'F', 'F sharp', 'G', 'G sharp', 'A', 'B flat', 'B'];
  function noteName(f) { const m = Math.round(69 + 12 * Math.log2(f / 440)); return NOTE[((m % 12) + 12) % 12]; }

  // posts realised from a profile for drawing: a dot count per range bin proportional to reflectivity
  function realise(prof, total, seed, wedge, bin = 6) {
    const r = rng(seed), posts = [];
    let sum = 0; for (let i = 0; i < prof.length; i++) sum += Math.max(0, prof[i]);
    let carry = 0;
    for (let i0 = 0; i0 < prof.length; i0 += bin) {
      let s = 0; for (let i = i0; i < Math.min(prof.length, i0 + bin); i++) s += Math.max(0, prof[i]);
      carry += s / sum * total;
      while (carry >= 1) {
        carry -= 1;
        const rho = R0 + (i0 + r() * bin) * DR;
        posts.push({ rho, th: wedge ? (r() * 2 - 1) * 20 * Math.PI / 180 : r(), i: i0 });
      }
    }
    return posts;
  }

  const drawers = [];
  function redrawAll() { readPalette(); drawers.forEach((f) => f()); }

  // ---------- hero: the bird field from above ----------
  (function hero() {
    const fig = $('#hero'), cv = $('canvas', fig);
    const d = design('bird');
    const echo = conv(d.prof, CLAPS[0]);
    const posts = realise(d.prof, 900, 7, true);
    const rMax = R0 + d.prof.length * DR;
    let t0 = null;
    const SLOW = 40;
    function draw(now) {
      const { g, w, h } = setup(cv);
      const xMin = -1.2, xMax = rMax + 2.2, yHalf = rMax * Math.sin(20 * Math.PI / 180) + 0.9;
      const sc = Math.min(w / (xMax - xMin), h / (2 * yHalf));
      const ox = (w - (xMax - xMin) * sc) / 2 - xMin * sc, oy = h / 2;
      const X = (x) => ox + x * sc, Y = (y) => oy - y * sc;
      // range rings, labelled in metres and milliseconds of echo
      g.strokeStyle = palette.rule; g.lineWidth = 1;
      for (const r of [5, 10, 15]) {
        g.beginPath(); g.arc(X(0), Y(0), r * sc, -0.42, 0.42); g.stroke();
        if (w >= 500 || r > 5) text(g, `${r} m, ${fmt(2 * r / C * 1000, 0)} ms`, X(r * Math.cos(0.42)) + 4, Y(-r * Math.sin(0.42)) + 2, palette.muted, 'left', 'top');
      }
      const ringR = t0 === null ? -1 : (Math.max(0, now - t0) / 1000 / SLOW) * C;
      for (const p of posts) {
        const x = p.rho * Math.cos(p.th), y = p.rho * Math.sin(p.th);
        const since = ringR - p.rho;
        const lit = since > 0 && since < 1.6;
        g.fillStyle = lit ? palette.accent : palette.ink;
        g.globalAlpha = lit ? 1 : 0.55;
        g.beginPath(); g.arc(X(x), Y(y), lit ? 2.2 : 1.3, 0, 2 * Math.PI); g.fill();
      }
      g.globalAlpha = 1;
      if (ringR > 0 && ringR < rMax + 2) {
        g.strokeStyle = palette.accent; g.lineWidth = 2;
        g.beginPath(); g.arc(X(0), Y(0), ringR * sc, -0.5, 0.5); g.stroke();
      }
      g.fillStyle = palette.ink; g.beginPath(); g.arc(X(0), Y(0), 5, 0, 2 * Math.PI); g.fill();
      text(g, 'you', X(0), Y(0) + 20, palette.ink, 'center');
      text(g, `${posts.length} posts drawn, ${fmt(rMax - R0, 1)} m deep`, w - 4, h - 6, palette.muted, 'right');
      if (t0 !== null && ringR < rMax + 2) requestAnimationFrame(draw); else t0 = null;
    }
    drawers.push(() => draw(performance.now()));
    $('[data-act="clap"]', fig).addEventListener('click', () => {
      const m = mix(CLAPS[0], echo, D0, null);
      play(m.buf);
      $('[data-out="note"]', fig).textContent = 'That is a bird-note field answering one clap: the clap, then about 18 ms later the whistle. The echo is turned up so you can hear it; how loud it would really be is covered further down. The ring is slowed 40 times.';
      if (reduceMotion) return;
      t0 = performance.now(); requestAnimationFrame(draw);
    });
  })();

  // ---------- 1. one wall ----------
  (function wall() {
    const fig = $('#wall'), cv = $('canvas', fig), sl = $('[data-in="dist"]', fig);
    const MAXD = 60, SLOW = 10;
    let t0 = null;
    const dist = () => +sl.value;
    function draw(now) {
      const { g, w, h } = setup(cv);
      const R = dist(), sceneH = 110, x0 = 30, xw = w - 50;
      const X = (m) => x0 + m / MAXD * xw;
      // ground line and person
      g.strokeStyle = palette.rule; g.beginPath(); g.moveTo(10, sceneH - 15); g.lineTo(w - 10, sceneH - 15); g.stroke();
      g.fillStyle = palette.ink; g.beginPath(); g.arc(X(0), sceneH - 60, 6, 0, 7); g.fill();
      g.fillRect(X(0) - 2, sceneH - 54, 4, 39);
      // wall
      g.fillStyle = palette.accent; g.fillRect(X(R) - 3, 18, 6, sceneH - 33);
      text(g, `${fmt(R, 1)} m`, X(R), 12, palette.accent, 'center');
      for (const m of [0, 10, 20, 30, 40, 50, 60]) text(g, m + ' m', X(m), sceneH, palette.muted, 'center', 'top');
      // sound ring out and back, slowed
      if (t0 !== null) {
        const travelled = (Math.max(0, now - t0) / 1000 / SLOW) * C;
        if (travelled < 2 * R) {
          g.strokeStyle = palette.accent; g.lineWidth = 2;
          g.beginPath();
          const rad = Math.max(1, travelled / MAXD * xw), span = Math.min(0.6, 45 / rad);
          // outgoing front centred on you; the reflected front is centred on your mirror image behind the wall
          if (travelled <= R) g.arc(X(0), sceneH - 50, rad, -span, span);
          else g.arc(X(2 * R), sceneH - 50, rad, Math.PI - span, Math.PI + span);
          g.stroke(); g.lineWidth = 1;
          requestAnimationFrame(draw);
        } else t0 = null;
      }
      // what reaches the ear: time axis 0..2*MAXD/C
      const ty = sceneH + 26, th = h - ty - 20, tMax = 2 * MAXD / C;
      const delay = 2 * R / C;
      const TX = (t) => x0 + t / tMax * xw;
      g.strokeStyle = palette.rule; g.beginPath(); g.moveTo(x0, ty + th / 2); g.lineTo(x0 + xw, ty + th / 2); g.stroke();
      const cl = CLAPS[0], span = cl.length / FS / tMax * xw;
      wave(g, cl, 0, cl.length, TX(0), ty, Math.max(2, span), th, 1, palette.ink);
      wave(g, cl, 0, cl.length, TX(delay), ty, Math.max(2, span), th, 0.6, palette.accent);
      text(g, 'your clap', TX(0) + 6, ty + 10, palette.ink);
      text(g, `echo, ${fmt(delay * 1000, 1)} ms later`, Math.min(TX(delay) + 6, w - 4), ty + 10, palette.accent, TX(delay) + 130 > w ? 'right' : 'left');
      for (const ms of [0, 100, 200, 300]) text(g, ms + ' ms', TX(ms / 1000), h - 4, palette.muted, 'center');
    }
    function update() {
      const R = dist(), ms = 2 * R / C * 1000;
      $('[data-out="readout"]', fig).innerHTML = `Wall <b>${fmt(R, 1)} m</b> away: the echo arrives <b>${fmt(ms, 1)} ms</b> after the clap. That is ${fmt(R * 100, 0)} cm ÷ ${fmt(ms, 1)} ms = 17.15 cm per millisecond.`;
      const rel = 0.3 / (2 * R);
      $('[data-out="loud"]', fig).textContent = `a real flat wall ${fmt(R, 0)} m away would return the clap about ${fmt(-20 * Math.log10(rel), 0)} decibels quieter than you hear it directly (from 30 cm).`;
      draw(performance.now());
    }
    sl.addEventListener('input', update);
    // drag the wall directly on the picture
    let dragging = false;
    const setFromX = (e) => { const r = cv.getBoundingClientRect(); const m = (e.clientX - r.left - 30) / (r.width - 50) * MAXD; sl.value = Math.max(3, Math.min(MAXD, Math.round(m * 2) / 2)); update(); };
    cv.addEventListener('pointerdown', (e) => { if (e.offsetY < 110) { dragging = true; cv.setPointerCapture(e.pointerId); setFromX(e); } });
    cv.addEventListener('pointermove', (e) => { if (dragging) setFromX(e); });
    cv.addEventListener('pointerup', () => { dragging = false; });
    $('[data-act="clap"]', fig).addEventListener('click', () => {
      const R = dist(), delay = Math.round(2 * R / C * FS);
      play(mix(CLAPS[0], CLAPS[0], delay, 0.3 / (2 * R), 0.5).buf);
      if (!reduceMotion) { t0 = performance.now(); requestAnimationFrame(draw); }
    });
    drawers.push(update);
  })();

  // ---------- 2. a row of posts ----------
  (function row() {
    const fig = $('#row'), cv = $('canvas', fig), sl = $('[data-in="spacing"]', fig);
    const DEPTH = 10;
    const spacing = () => 0.04 * Math.pow(2.5 / 0.04, +sl.value / 1000);
    function train(s) {
      const n = Math.floor(DEPTH / s) + 1, x = new Float32Array(Math.ceil(2 * DEPTH / C * FS) + 4);
      for (let k = 0; k < n; k++) { const d = 2 * k * s / C * FS, i = Math.floor(d), f = d - i; x[i] += 1 - f; x[i + 1] += f; }
      return { x, n };
    }
    function draw() {
      const { g, w, h } = setup(cv);
      const s = spacing(), { x, n } = train(s);
      const x0 = 8, xw = w - 16, X = (m) => x0 + (m + 0.4) / (DEPTH + 0.8) * xw;
      g.fillStyle = palette.ink;
      g.beginPath(); g.arc(X(-R0 + R0 - 0.2), 30, 5, 0, 7); g.fill();
      for (let k = 0; k < n; k++) { g.beginPath(); g.arc(X(k * s), 30, n > 120 ? 1.2 : 2.2, 0, 7); g.fill(); }
      text(g, `${n} posts, ${fmt(s * 100, s < 0.1 ? 1 : 0)} cm apart, in a row 10 m deep`, x0, 62, palette.muted);
      const echo = conv(x, CLAPS[0]);
      const ty = 78, th = h - ty - 18;
      wave(g, echo, 0, echo.length, x0, ty, xw, th, 1 / (peak(echo) || 1), palette.accent);
      text(g, 'echo, first post', x0, h - 3, palette.muted);
      text(g, `${fmt(2 * DEPTH / C * 1000, 0)} ms later`, x0 + xw, h - 3, palette.muted, 'right');
    }
    function update() {
      const s = spacing(), f = C / (2 * s), dt = 2 * s / C * 1000;
      let what;
      if (f < 20) what = 'far enough apart to hear as separate ticks, a rattle';
      else if (f < 300) what = 'a low buzz: the ticks have merged, but the clap carries almost nothing this low';
      else if (f < 1000) what = 'a tone, but faint and hollow: the clap is weak this low';
      else if (f <= 4000) what = 'a clear tone, right where the clap is strongest';
      else what = 'a thin, high tone above most of the clap\'s energy';
      $('[data-out="readout"]', fig).innerHTML = `A tick every <b>${fmt(dt, dt < 1 ? 2 : 1)} ms</b>, ${fmt(1000 / dt, 0)} per second: ${f >= 20 ? `a pitch of about <b>${fmt(f, 0)} Hz</b> (close to ${noteName(f)}), ` : ''}${what}.`;
      draw();
    }
    sl.addEventListener('input', update);
    $('[data-act="clap"]', fig).addEventListener('click', () => {
      const { x } = train(spacing());
      play(mix(CLAPS[0], conv(x, CLAPS[0]), D0, null).buf);
    });
    drawers.push(update);
  })();

  // ---------- 3. the layout is the waveform ----------
  (function groove() {
    const fig = $('#groove'), cv = $('canvas', fig);
    let name = 'bird', mode = 'real';
    function echoOf(clap) { const d = design(name); return conv(mode === 'real' ? d.prof : d.t, clap); }
    function draw() {
      const { g, w, h } = setup(cv);
      const d = design(name), n = d.t.length;
      const x0 = 8, xw = w - 16, X = (i) => x0 + i / n * xw;
      // band 1: target waveform with time axis
      const b1 = 24, h1 = 90;
      text(g, 'the sound we want back', x0, 14, palette.muted);
      wave(g, d.t, 0, n, x0, b1, xw, h1, 0.95, palette.ink);
      for (let ms = 0; ms <= n / FS * 1000 + 1; ms += name === 'bird' ? 20 : 45) { const xx = X(ms / 1000 * FS); text(g, ms + ' ms', xx, b1 + h1 + 12, palette.muted, ms === 0 ? 'left' : xx > w - 30 ? 'right' : 'center'); }
      // band 2: reflectivity needed at each distance
      const b2 = b1 + h1 + 40, h2 = 110, zero = mode === 'real' ? b2 + h2 : b2 + h2 / 2, sc = mode === 'real' ? h2 / 2 : h2 / 2;
      text(g, mode === 'real' ? 'reflection needed: bias (dashed) plus the sound' : 'reflection needed, if posts could reflect negatively (red)', x0, b2 - 8, palette.muted);
      const p = mode === 'real' ? d.prof : d.t;
      const per = n / xw;
      for (let px = 0; px < xw; px++) {
        const a = Math.floor(px * per), b = Math.max(a + 1, Math.floor((px + 1) * per));
        let lo = 0, hi = 0; for (let i = a; i < b; i++) { if (p[i] < lo) lo = p[i]; if (p[i] > hi) hi = p[i]; }
        if (hi > 0) { g.fillStyle = palette.accent; g.fillRect(x0 + px, zero - hi * sc, 1, hi * sc); }
        if (lo < 0) { g.fillStyle = palette.warn; g.fillRect(x0 + px, zero, 1, -lo * sc); }
      }
      g.strokeStyle = palette.ink; g.lineWidth = 1; g.beginPath(); g.moveTo(x0, zero + 0.5); g.lineTo(x0 + xw, zero + 0.5); g.stroke();
      if (mode === 'real') {
        g.setLineDash([4, 3]); g.strokeStyle = palette.ink; g.beginPath();
        for (let px = 0; px <= xw; px++) { const v = d.bias[Math.min(n - 1, Math.floor(px * per))]; px ? g.lineTo(x0 + px, zero - v * sc) : g.moveTo(x0, zero - v * sc); }
        g.stroke(); g.setLineDash([]);
      }
      // band 3: posts on the ground
      const zw = Math.min(260, xw * 0.4), b3 = b2 + h2 + 18, h3 = h - b3 - 18, bw3 = xw - zw - 16;
      const X3 = (i) => x0 + i / n * bw3;
      const posts = realise(mode === 'real' ? d.prof : d.t.map((v) => Math.max(0, v)), name === 'bird' ? 420 : 700, 3, false);
      g.fillStyle = palette.ink;
      for (const q of posts) { g.beginPath(); g.arc(X3(q.i + 3), b3 + 3 + q.th * (h3 - 6), 1.1, 0, 7); g.fill(); }
      const depth = n * DR;
      for (let m = 0; m <= depth + 0.01; m += (name === 'bird' ? 4 : 10) * (bw3 < 300 ? 2 : 1)) text(g, `${R0 + m} m`, X3(m / DR), h - 2, palette.muted, m === 0 ? 'left' : 'center');
      // magnified: 30 cm of the field, where single wiggles are visible as bands of posts
      const zn = Math.round(0.3 / DR), zi = Math.round(n * 0.35), zx = x0 + xw - zw;
      const zprof = (mode === 'real' ? d.prof : d.t).slice(zi, zi + zn).map((v) => Math.max(0, v));
      g.strokeStyle = palette.rule; g.strokeRect(zx + 0.5, b3 + 0.5, zw, h3);
      g.strokeStyle = palette.muted; g.beginPath(); g.moveTo(X3(zi), b3 - 4); g.lineTo(X3(zi), b3 + h3 + 4); g.stroke();
      const zp = realise(zprof, mode === 'real' ? 160 : 90, 5, false, 1);
      g.fillStyle = palette.ink;
      for (const q of zp) { g.beginPath(); g.arc(zx + (q.rho - R0) / DR / zn * zw, b3 + 4 + q.th * (h3 - 8), 1.6, 0, 7); g.fill(); }
      if (mode === 'neg') {
        g.fillStyle = palette.warn; g.globalAlpha = 0.2;
        for (let i = 0; i < zn; i++) if (d.t[zi + i] < 0) g.fillRect(zx + i / zn * zw, b3, zw / zn + 0.5, h3);
        g.globalAlpha = 1;
      }
      text(g, bw3 < 300 ? '30 cm, magnified' : `30 cm of it, magnified (${fmt(R0 + zi * DR, 1)} m out)`, zx + zw, b3 - 5, palette.muted, 'right');
    }
    function update() {
      fig.querySelectorAll('[data-target]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.target === name));
      fig.querySelectorAll('[data-mode]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.mode === mode));
      const d = design(name), depth = d.t.length * DR;
      let msg = `${fmt(d.t.length / FS * 1000, 0)} ms of sound becomes <b>${fmt(depth, 1)} m</b> of posts. `;
      if (mode === 'real') {
        const sig = conv(d.t, CLAPS[0]), leak = conv(d.bias, CLAPS[0]);
        msg += `Only <b>${fmt(100 * d.useful, 0)}%</b> of the reflecting material carries the sound; the rest is bias. The bias comes back as a faint thump about ${fmt(-10 * Math.log10(energy(leak) / energy(sig)), 0)} dB below the sound.`;
      } else {
        msg += 'Half the waveform is below zero. No post can do that.';
      }
      $('[data-out="readout"]', fig).innerHTML = msg;
      draw();
    }
    fig.querySelectorAll('[data-target]').forEach((b) => b.addEventListener('click', () => { name = b.dataset.target; update(); }));
    fig.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => { mode = b.dataset.mode; update(); }));
    $('[data-act="target"]', fig).addEventListener('click', () => { const t = design(name).t; const x = new Float32Array(t.length + 2 * LEAD); x.set(t.map((v) => 0.7 * v), LEAD); play(x); });
    $('[data-act="clap"]', fig).addEventListener('click', () => play(mix(CLAPS[0], echoOf(CLAPS[0]), D0, null).buf));
    drawers.push(update);
  })();

  // ---------- 4. why the clap matters ----------
  (function clapFig() {
    const fig = $('#clap'), cv = $('canvas', fig), segs = $('[data-out="claps"]', fig);
    const P = S.clap_params;
    const opts = [{ label: 'Ideal click', x: IDEAL }].concat(CLAPS.map((x, k) => ({ label: `Clap ${k + 1}`, x, p: P[k] })));
    let sel = 1;
    opts.forEach((o, k) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'seg-b'; b.textContent = o.label; b.dataset.k = k;
      b.addEventListener('click', () => { sel = k; update(); });
      segs.appendChild(b);
    });
    function spectrum(x) { // magnitude in dB, 0..5 kHz, 100 bins
      const out = [];
      for (let f = 50; f <= 5000; f += 50) {
        let re = 0, im = 0; for (let i = 0; i < x.length; i++) { const a = 2 * Math.PI * f * i / FS; re += x[i] * Math.cos(a); im -= x[i] * Math.sin(a); }
        out.push(Math.hypot(re, im));
      }
      const m = Math.max(...out); return out.map((v) => Math.max(-40, 20 * Math.log10(v / m + 1e-9)));
    }
    function draw() {
      const { g, w, h } = setup(cv);
      const o = opts[sel], half = (w - 24) / 2, top = 18, th = 90;
      text(g, 'the clap (8 ms)', 8, 12, palette.muted);
      wave(g, o.x, 0, 128, 8, top, half, th, 0.95, palette.ink);
      text(g, 'its pitch content, 0 to 5 kHz', 16 + half, 12, palette.muted);
      const sp = spectrum(o.x), sx = 16 + half;
      // shade the bird note's range, 2 to 3.5 kHz
      g.fillStyle = palette.accent; g.globalAlpha = 0.15; g.fillRect(sx + 2000 / 5000 * half, top, 1500 / 5000 * half, th); g.globalAlpha = 1;
      g.strokeStyle = palette.ink; g.lineWidth = 1.5; g.beginPath();
      sp.forEach((v, i) => { const x = sx + (i + 1) * 50 / 5000 * half, y = top + (-v / 40) * th; i ? g.lineTo(x, y) : g.moveTo(x, y); });
      g.stroke(); g.lineWidth = 1;
      text(g, 'bird note', sx + 2750 / 5000 * half, top + th + 12, palette.accent, 'center');
      const ey = top + th + 34, eh = h - ey - 4;
      text(g, 'echo of the bird-note field for this clap', 8, ey - 4, palette.muted);
      const echo = conv(design('bird').prof, o.x);
      wave(g, echo, 0, echo.length, 8, ey, w - 16, eh, 1 / (peak(echo) || 1), palette.accent);
    }
    function update() {
      segs.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', +b.dataset.k === sel));
      const o = opts[sel];
      $('[data-out="readout"]', fig).innerHTML = o.p
        ? `${o.label}: <b>${fmt(o.p.duration_ms, 1)} ms</b> of noise, brightest near <b>${fmt(o.p.peak_hz / 1000, 1)} kHz</b>.`
        : 'A perfect instant click, trimmed to the 500 Hz to 4 kHz band the project designs for. It returns the bird note almost exactly.';
      draw();
    }
    $('[data-act="solo"]', fig).addEventListener('click', () => { const x = new Float32Array(opts[sel].x.length + 2 * LEAD); x.set(opts[sel].x.map((v) => 0.9 * v), LEAD); play(x); });
    $('[data-act="clap"]', fig).addEventListener('click', () => play(mix(opts[sel].x, conv(design('bird').prof, opts[sel].x), D0, null).buf));
    drawers.push(update);
  })();

  // ---------- 5. how big ----------
  const REFS = [
    { name: 'a city bus', m: 12 },
    { name: 'a tennis court', m: 23.8 },
    { name: 'an Olympic pool', m: 50 },
    { name: 'a football pitch', m: 105 },
  ];
  (function size() {
    const fig = $('#size'), cv = $('canvas', fig), sl = $('[data-in="ms"]', fig);
    const dl = document.createElement('datalist'); dl.id = 'stage-ms';
    for (const v of [80, 180, 400, 800]) { const o = document.createElement('option'); o.value = v; dl.appendChild(o); }
    fig.appendChild(dl); sl.setAttribute('list', 'stage-ms');
    const MAXM = 140;
    function draw() {
      const { g, w, h } = setup(cv);
      const depth = +sl.value * 0.1715, x0 = 8, xw = w - 16, X = (m) => x0 + m / MAXM * xw;
      g.fillStyle = palette.accent; g.fillRect(X(0), 10, X(depth) - X(0), 26);
      text(g, `the post field, ${fmt(depth, 1)} m`, Math.min(X(depth) - 4, w - 8), 52, palette.accent, X(depth) > 160 ? 'right' : 'left');
      if (X(depth) <= 160) g.textAlign = 'left';
      REFS.forEach((r, k) => {
        const y = 70 + k * 36;
        g.strokeStyle = palette.ink; g.lineWidth = 1; g.strokeRect(X(0) + 0.5, y + 0.5, X(r.m) - X(0), 14);
        const fits = depth / r.m;
        text(g, `${r.name}, ${r.m} m`, X(r.m) + 6 < w - 150 ? X(r.m) + 6 : X(0) + 4, X(r.m) + 6 < w - 150 ? y + 11 : y + 28, palette.muted);
        void fits;
      });
      g.strokeStyle = palette.rule; g.beginPath(); g.moveTo(X(0), h - 16); g.lineTo(X(MAXM), h - 16); g.stroke();
      for (let m = 0; m <= MAXM; m += w < 500 ? 40 : 20) text(g, m + ' m', X(m), h - 2, palette.muted, m === 0 ? 'left' : X(m) > w - 30 ? 'right' : 'center');
    }
    function update() {
      const ms = +sl.value, depth = ms * 0.1715;
      const near = REFS.reduce((a, r) => (Math.abs(Math.log(depth / r.m)) < Math.abs(Math.log(depth / a.m)) ? r : a));
      const ratio = depth / near.m;
      const cmp = Math.abs(ratio - 1) < 0.15 ? `about the length of ${near.name}` : `about ${fmt(ratio, 1)} times the length of ${near.name}`;
      $('[data-out="readout"]', fig).innerHTML = `${ms} ms of sound needs a field <b>${fmt(depth, 1)} m</b> deep, ${cmp}.`;
      draw();
    }
    sl.addEventListener('input', update);
    drawers.push(update);
  })();

  // ---------- results cards ----------
  const wavCache = {};
  async function playWav(key, b64) {
    const c = ac();
    if (!wavCache[key]) {
      const bin = atob(b64), buf = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      wavCache[key] = await c.decodeAudioData(buf.buffer);
    }
    playBuffer(wavCache[key]);
  }
  // ---------- results data ----------
  const G = D.results.groups;
  const heads = [];
  G.forEach((gp, gi) => gp.subs.forEach((s, si) => s.entries.forEach((e, ei) => heads.push({ e, gp, s, id: `${gi}-${si}-${ei}` }))));
  const SHORT = { s1_bird: 'whistle', s2_motif: 'four notes', s3_melody: 'tune', s4_speech: 'speech' };
  function shortName(x) {
    if (x.e.target_name) return `"${x.e.target_name}"`;
    if (x.s.key === '100ms' || x.s.key === '60ms') return `tune, ${x.s.key.replace('ms', ' ms')}`;
    return SHORT[x.gp.key] || x.gp.name;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
  function num(v, d = 1, unit = '') { return v == null || Number.isNaN(+v) ? 'not recorded' : fmt(+v, d) + unit; }
  function cmpWord(c) { return c === '<=' ? 'at most' : c === '>=' ? 'at least' : c === '==' ? 'exactly' : ''; }
  const nv = (v) => typeof v === 'number' && isFinite(v);
  const t1 = (e, id) => ((e.allm || []).find((m) => m.id === id && m.tier === 'tier1') || {}).value;
  const gate = (e, id) => (e.metrics || []).find((m) => m.id === id && m.tier !== 'tier0');
  const listJoin = (a) => (a.length > 1 ? a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1] : a[0] || '');
  const cleanLabel = (s) => String(s).replace(/\bTier 1\b/g, 'careful simulator').replace(/\bTier 0\b/g, 'fast simulator');

  function loudWords(db) {
    if (db == null) return null;
    if (db < 20) return 'quieter than rustling leaves: almost certainly inaudible outdoors';
    if (db < 35) return 'about a whisper: likely lost in outdoor background noise';
    if (db < 50) return 'about a quiet room: audible on a calm, quiet site';
    if (db < 65) return 'about normal conversation';
    if (db < 80) return 'about a busy street';
    return 'louder than a busy street';
  }
  function valWord(id, v) {
    if (id === 'formant_err_pct' && v == null) return 'no vowel resonance found';
    if (!nv(v)) return null;
    if (/^pitch_err(_max)?_pct$/.test(id)) return `pitch off by up to ${fmt(v, 1)}%`;
    if (id === 'spec_corr') return `spectrogram match ${fmt(v, 2)}`;
    if (id === 'hello_hit') return v >= 1 ? 'heard as "hello"' : 'not heard as "hello"';
    if (id === 'hello_count') return `heard as "hello" for ${fmt(v, 0)} claps`;
    if (id === 'estoi') return `clarity ${fmt(v, 2)}`;
    if (id === 'closed_set_correct') return v >= 1 ? 'closest to the right syllable' : 'closest to a wrong syllable';
    if (id === 'notes_in_order') return `notes in order for ${fmt(100 * v, 0)}% of claps`;
    if (id === 'note_cents_max') return v >= 1200 ? 'some notes missing altogether' : `worst note off by ${fmt(v, 0)} cents`;
    if (id === 'formant_err_pct') return `vowel resonances off by ${fmt(v, 1)}%`;
    return `${id.replace(/_/g, ' ')} ${fmt(v, Math.abs(v) < 10 ? 2 : 1)}`;
  }
  const valWords = (m) => Object.entries(m || {}).map(([k, v]) => valWord(k, v)).filter(Boolean).join(', ');
  const gateWords = (e) => (e.metrics || []).map((m) => valWord(m.id, m.value)).filter(Boolean).join(', ');
  function designWords(e) {
    const d = e.design || {}, bits = [];
    if (d.radius_m) bits.push(`posts ${fmt(d.radius_m * 200, 0)} cm across`);
    if (d.strip_half_width_m) bits.push(`in a strip ${fmt(2 * d.strip_half_width_m, 0)} m wide inside the fan`);
    else if (d.half_angle_deg) bits.push(`in a fan of plus or minus ${fmt(d.half_angle_deg, d.half_angle_deg % 1 ? 1 : 0)} degrees`);
    let how = d.realization === 'phase_locked' ? 'posts in exact rings' : d.realization ? 'posts scattered by density' : '';
    if (d.stretch) how += ', with the layout stretched to cancel the slowing of sound in the field';
    return [how, bits.join(' ')].filter(Boolean).join('; ');
  }
  function verdictOf(e) {
    if (!e.has_metrics) return ['A final run exists, but its scores could not be read.', ''];
    if (e.passed && e.verified) return ['Passed on the careful simulator.', 'pass'];
    if (e.passed) return ['Passed on the fast simulator only, so treat it as provisional.', ''];
    return [e.verified === false ? 'Did not pass (and not checked by the careful simulator).' : 'Did not pass.', 'fail'];
  }
  const fl = (e, id) => (e.judge_floor || e.floor || {})[id];

  // ---------- the three verdicts, always kept apart ----------
  const TESTS = D.scoreboard || [];
  const testOf = (e) => TESTS.find((t) => t.run_id === e.run_id);
  const featured = (t) => !!t && (t.revised === true || t.strict === true);
  const LEVELS = (D.listen && D.listen.levels) || {};
  const rmet = (e, id) => ((e.crit || {}).revised_metrics || []).find((m) => m.id === id);
  function dateWords(s) { const d = new Date(s); return isNaN(d) ? '' : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long' }); }
  function strictSentence(e, rich) {
    const c = e.crit || {};
    if (c.strict === true) return 'Passes the marks fixed before the experiment.';
    if (c.strict !== false) return 'No strict score recorded.';
    if (!rich) return `Misses the marks fixed before the experiment${gateWords(e) ? ` (${gateWords(e)})` : ''}.`;
    const p = gate(e, 'pitch_err_pct'), sc = gate(e, 'spec_corr');
    if (p && nv(p.value)) {
      const f = fl(e, p.id);
      return `Misses narrowly: the pitch wanders by up to ${fmt(p.value, 2)}% where the limit is ${p.threshold}%${nv(f) ? `, and even a perfect echo of a real clap scores ${fmt(f, 2)}%` : ''}${sc && nv(sc.value) ? `; the spectrogram match is ${fmt(sc.value, 2)} against a mark of ${sc.threshold}, pulled down by a faint hiss well below the whistle` : ''}.`;
    }
    return `Misses the marks fixed before the experiment${gateWords(e) ? ` (${gateWords(e)})` : ''}.`;
  }
  function revisedSentence(e, rich) {
    const c = e.crit || {};
    if (!c.revised_scored) return 'Not scored with the revised tests yet.';
    const ctl = nv(c.controls_total) && c.controls_total ? `${c.controls_rejected} of ${c.controls_total} deliberately wrong echoes rejected` : '';
    if (c.revised === true) {
      if (/same judge/i.test(c.revised_rests_on || '')) return `Confirmed, but not independently: it relies on the same speech recognizer as the strict test${ctl ? `, with ${ctl}` : ''}.`;
      const id = rmet(e, 'id_claps'), pc = rmet(e, 'pitch_cents');
      if (rich && id && nv(id.value) && pc && nv(pc.value) && nv(pc.threshold)) return `Confirmed: picked out as the whistle among other sounds for ${fmt(id.value, 0)} of 5 claps, with its pitch about ${fmt(pc.value, 0)} cents off (the limit is ${fmt(pc.threshold, 0)}; a semitone is 100 cents)${nv(c.controls_total) && c.controls_total ? `, while ${c.controls_rejected === c.controls_total ? `all ${c.controls_total}` : `${c.controls_rejected} of ${c.controls_total}`} deliberately wrong echoes were rejected, including the whistle shifted by a semitone` : ''}.`;
      return `Confirmed${ctl ? `, with ${ctl}` : ''}.`;
    }
    if (c.revised === false) return 'Not passed.';
    return 'Not established: no automated measure could tell this echo from deliberately wrong ones. Neither a pass nor a fail.';
  }
  function earSentence(t) {
    if (!t || t.ear !== 'pass') return 'No listening verdict recorded.';
    const ear = D.listening || {};
    let s = `Accepted by the owner, listening${ear.date ? ` on ${dateWords(ear.date)}` : ''} and knowing what it was meant to be${t.ear_blind ? '' : ' (not a blind test)'}.`;
    if (!t.ear_on_newest && t.n_designs > 1) s += ' The files attach this verdict to the earlier design; it is not recorded which of the two designs the owner heard.';
    return s;
  }
  function vState(kind, e, t) {
    const c = e.crit || {};
    if (kind === 'strict') return c.strict === true ? ['pass', 'Passes'] : c.strict === false ? ['fail', 'Misses'] : ['none', 'No score'];
    if (kind === 'revised') return !c.revised_scored ? ['none', 'Not scored'] : c.revised === true ? ['pass', 'Confirmed'] : c.revised === false ? ['fail', 'Not passed'] : ['null', 'Not established'];
    return t && t.ear === 'pass' ? ['pass', 'Accepted'] : ['none', 'Not recorded'];
  }
  function vLines(e, rich) {
    const t = testOf(e);
    const c = e.crit || {};
    const compact = rich === 'compact';
    const rows = compact
      ? [['strict', 'Strict tests', c.strict === false ? esc(gateWords(e)) : ''],
        ['revised', 'Revised tests', ''],
        ['ear', 'By ear', t && t.ear === 'pass' ? `the owner, knowing the target${t.ear_blind ? '' : ' (not blind)'}${!t.ear_on_newest && t.n_designs > 1 ? '; recorded on the earlier design, and it is not recorded which of the two designs the owner heard' : ''}` : '']]
      : [['strict', 'Strict tests', strictSentence(e, rich)], ['revised', 'Revised tests', revisedSentence(e, rich)], ['ear', 'By ear', earSentence(t)]];
    return `<ul class="vlines${compact ? ' compact' : ''}">${rows.map(([k, label, sent]) => { const [cls, word] = vState(k, e, t); return `<li class="v v-${cls}" data-v="${k}:${cls}"><span class="vk">${label}</span><span class="vs">${word}</span><span class="vt">${sent}</span></li>`; }).join('')}</ul>`;
  }
  const trueLevel = (e) => (LEVELS[e.tag] || {}).true_db;

  // What came back, in plain words: generic templates keyed on the fields a run carries.
  function backSentence(e) {
    const out = [];
    const p = gate(e, 'pitch_err_pct') || (e.metrics || []).find((m) => /^pitch_err/.test(m.id));
    const c = gate(e, 'spec_corr');
    if (p && nv(p.value)) {
      const f = fl(e, p.id);
      out.push(`The whistle came back, but its pitch wandered by up to ${fmt(p.value, 1)}% (the limit is ${p.threshold}%${nv(f) ? `; even a perfect echo scores ${fmt(f, 1)}%` : ''})${c && nv(c.value) ? `, and its spectrogram matched the target's to ${fmt(c.value, 2)} (pass mark ${c.threshold}${nv(fl(e, 'spec_corr')) ? `; a perfect echo scores ${fmt(fl(e, 'spec_corr'), 2)}` : ''})` : ''}.`);
    }
    const order = gate(e, 'notes_in_order');
    if (order && nv(order.value)) {
      out.push(order.value <= 0 ? 'No clap brought the notes back in the right order.' : order.value >= 1 ? 'Every clap brought the notes back in order.' : `Only ${fmt(100 * order.value, 0)}% of claps brought the notes back in order.`);
      const sw = (e.design || {}).strip_half_width_m;
      if (sw) out.push(`The posts were confined to a strip ${fmt(2 * sw, 0)} m wide, because the full fan would have taken hours per run to simulate. Squeezed into a lane, the posts shade each other, and there is no room to add the extra posts the far end needs.`);
      if (e.heard_hz && e.want_hz) out.push(`The pitch tracker heard tones around ${fmt(e.heard_hz[0], 0)} to ${fmt(e.heard_hz[1], 0)} Hz instead of the tune's ${fmt(e.want_hz[0], 0)} to ${fmt(e.want_hz[1], 0)} Hz: a hiss of stray reflections, not the notes.`);
      if (e.extinction_last_db != null) out.push(`The sound died out along the field: the last note came back about ${fmt(e.extinction_last_db, 0)} dB weaker than the fast simulator, which ignores the fading, predicts.`);
      if (e.level_along && e.level_along.spl_db.length) {
        const s = e.level_along.spl_db;
        out.push(`The first note arrived at about ${fmt(s[0], 0)} dB and the last at about ${fmt(s[s.length - 1], 0)} dB; ${e.level_along.below_35} of ${s.length} notes fell below the 35 dB line.`);
      }
    }
    const cs = gate(e, 'closed_set_correct'), es = gate(e, 'estoi') || (nv(t1(e, 'estoi')) ? { value: t1(e, 'estoi') } : null);
    if (cs && nv(cs.value)) out.push(cs.value >= 1 ? 'Asked which of the three syllables the echo is closest to, the test picked the right one.' : 'Asked which of the three syllables the echo is closest to, the test picked a wrong one.');
    const fm = gate(e, 'formant_err_pct');
    if (fm) {
      const f2 = t1(e, 'f2_err_pct');
      out.push(fm.value == null && t1(e, 'f1_hz') == null
        ? `The vowel's first resonance, the part that makes "ah" sound like "ah", could not be found in the echo at all${nv(f2) ? `; the second came back within ${fmt(f2, 1)}%` : ''}.`
        : `The vowel's resonances came back off by up to ${fmt(fm.value, 1)}% (limit ${fm.threshold}%).`);
    }
    if (e.recognized && e.recognized.length) {
      const hits = e.recognized.filter((t) => /hello/i.test(t)).length, words = [...new Set(e.recognized.map((t) => t || '(nothing)'))];
      out.push(`The speech recognizer heard ${listJoin(words.map((w) => `"${esc(w)}"`))} for ${hits} of ${e.recognized.length} claps.`);
      if (e.controls) {
        const names = e.controls.names.map((n) => (/time_reversed/.test(n) ? 'this echo played backwards' : /phase/.test(n) ? 'this echo with its phases scrambled' : `the "${n.split('_')[0]}" echo`));
        out.push(`Deliberately wrong echoes (${listJoin(names)}) were heard as "hello" ${e.controls.hits === 0 ? 'zero times' : `${e.controls.hits} times`}.`);
      }
    }
    if (es && nv(es.value) && (cs || e.recognized && e.recognized.length)) {
      const f = fl(e, 'estoi');
      out.push(`Its clarity score is ${fmt(es.value, 2)}${es.threshold != null ? ` (pass mark ${es.threshold})` : ''}${nv(f) ? `, where a perfect echo of the same clap scores ${fmt(f, 2)}` : ''}${es.value < 0.5 ? ': low. Press play and judge for yourself' : ''}.`);
    }
    if (e.recognized && e.recognized.length) {
      if (e.f_top_hz) out.push(`The careful simulator covered pitches only up to ${fmt(e.f_top_hz / 1000, 1)} kHz for this run.`);
      const side = (e.robust || []).find((x) => x.case === 'listener_side_1m');
      if (side && side.m && side.m.hello_hit === 0) out.push('A listener a metre to the side does not hear "hello".');
    }
    if (e.largest_cost) out.push(`In the fast model, the biggest single handicap is the ${esc(e.largest_cost)}${e.largest_cost === 'clap spectrum' ? ': a clap carries little of the low pitch that speech leans on' : ''}.`);
    const lc = e.loss_chain;
    if (lc && nv(lc.profile_model) && nv(lc.realized_tier0) && lc.realized_tier0 > 1.3 * lc.profile_model) out.push('Building the ideal layout out of a limited number of thin posts adds more error than any one handicap: each post adds a little stray hiss.');
    return out.join(' ');
  }

  function robustHTML(e) {
    const all = e.robust || [], rows = all.filter((x) => x.case !== 'nominal');
    if (!rows.length) return '';
    const nominal = all.find((x) => x.case === 'nominal');
    const pf = (x) => (x.pass === true ? 'still passes' : x.pass === false ? 'fails' : 'not scored');
    const one = (name, x) => `${name}: ${pf(x)}${valWords(x.m) ? ` (${valWords(x.m)})` : ''}`;
    const used = new Set(), items = [];
    const pick = (test) => rows.filter((x) => test(x) && !used.has(x) && used.add(x));
    const lis = pick((x) => /^listener/.test(x.case));
    if (lis.length) items.push('<b>Listener moved.</b> ' + lis.map((x) => one({ listener_side_1m: 'A metre to the side', listener_back_1m: 'A metre back' }[x.case] || esc(x.label), x)).join('. ') + '.');
    const tmp = pick((x) => /^c_\d+/.test(x.case));
    if (tmp.length) items.push('<b>Colder or hotter air.</b> ' + tmp.map((x) => { const cc = +x.case.slice(2); return one(cc < 343 ? 'About 0 °C' : cc > 343 ? 'About 30 °C' : esc(x.label), x); }).join('. ') + '.');
    const jit = pick((x) => x.case === 'jitter');
    if (jit.length) items.push('<b>Built slightly wrong.</b> ' + jit.map((x) => one(esc(x.label), x)).join('. ') + '.');
    const cl = pick((x) => /^clap_\d+/.test(x.case));
    if (cl.length) {
      const ranges = Object.keys(cl[0].m || {}).map((k) => { const v = cl.map((x) => x.m[k]).filter(nv); if (!v.length) return null; const a = valWord(k, Math.min(...v)), b = valWord(k, Math.max(...v)); return a === b ? a : `${a} to ${b.replace(/^[^0-9]*/, '')}`; }).filter(Boolean);
      items.push(`<b>Each clap on its own.</b> ${cl.filter((x) => x.pass === true).length} of ${cl.length} pass every check${ranges.length ? ` (${ranges.join('; ')})` : ''}.`);
    }
    rows.filter((x) => !used.has(x)).forEach((x) => items.push(one(esc(x.label || x.case), x) + '.'));
    const intro = nominal && nominal.pass === false ? 'When conditions change (the design already misses at its home spot, so this shows how much further it moves):' : 'When conditions change:';
    return `<p class="small">${intro}</p><ul class="checks robust">${items.map((i) => `<li>${i}</li>`).join('')}</ul>`;
  }

  function earlierLine(o) {
    const when = new Date(o.created), dwo = designWords(o), c = o.crit || {};
    const st = c.strict === true ? 'strict tests passed' : c.strict === false ? 'strict tests missed' : 'no strict score';
    const rv = !c.revised_scored ? '' : `; revised tests: ${c.revised === true ? 'confirmed' : c.revised === false ? 'not passed' : 'not established'}`;
    const ear = c.ear ? '; this is the design the listening verdict is recorded on' : '';
    return `<p class="small earlier">Earlier design${isNaN(when) ? '' : ', ' + when.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}${dwo ? ` (${esc(dwo)})` : ''}: ${st}${gateWords(o) ? ` (${gateWords(o)})` : ''}${rv}${ear}.</p>`;
  }
  function audioButtons(x) {
    const a = x.e.audio || {}, out = ['<div class="controls">'];
    if (a.target) out.push(`<button class="btn" type="button" data-wav="${x.id}-target">Target</button>`);
    if (a.echo) out.push(`<button class="btn primary" type="button" data-wav="${x.id}-echo">Echo${a.echo_is_tier0 ? ' (fast simulator)' : ''}, turned up</button>`);
    if (a.as_heard) out.push(`<button class="btn" type="button" data-wav="${x.id}-as_heard">As heard, true loudness</button>`);
    if (!a.target && !a.echo && !a.as_heard) out.push('<span class="small">No audio files were written for this run.</span>');
    out.push('</div>');
    return out.join('');
  }
  // Two sentences for the sounds that came back less clearly: what came back, and why.
  function lessClearWhy(x) {
    const e = x.e, k = x.gp.key, hd = e.headline || {};
    if (k.startsWith('s2')) {
      const o = gate(e, 'notes_in_order');
      return `What came back: notes that are there for some claps and out of balance${o && nv(o.value) ? `; the strict note-tracker found all four in order for ${fmt(100 * o.value, 0)}% of claps` : ''}. Why: in the first design the field swallowed the higher notes before they could return; the redesign stopped most of that fading but left the notes unevenly loud.`;
    }
    if (k.startsWith('s3')) {
      const sw = (e.design || {}).strip_half_width_m;
      return `What came back: mostly a hiss of stray reflections${e.heard_hz ? `, heard by the pitch tracker as tones near ${fmt(e.heard_hz[0], 0)} to ${fmt(e.heard_hz[1], 0)} Hz` : ''}, with the tune faint inside it. Why: the field is ${num(hd.depth_m, 0, ' m')} deep${sw ? ` and was squeezed into a strip ${fmt(2 * sw, 0)} m wide to keep the careful simulation affordable` : ''}, so the posts shade each other and the later notes fade.`;
    }
    if (x.s.key === '4a') return 'What came back: a breathy vowel whose first resonance, the low one that makes "ah" sound like "ah", the test could not find. Why: a clap carries little low-pitched sound, and thin posts return low pitches weakly.';
    if (x.s.key === '4b') {
      const es = gate(e, 'estoi') || (nv(t1(e, 'estoi')) ? { value: t1(e, 'estoi') } : null), f = fl(e, 'estoi'), cs = gate(e, 'closed_set_correct');
      return `What came back: a blurred syllable${es && nv(es.value) ? `, with a clarity score of ${fmt(es.value, 2)}${nv(f) ? ` where a perfect echo scores ${fmt(f, 2)}` : ''}` : ''}${cs && nv(cs.value) ? `; asked which of three syllables it is closest to, the test picked ${cs.value >= 1 ? 'the right one' : 'a wrong one'}` : ''}. Why: the same low-pitch handicap as the vowel, in a field ${num(hd.depth_m, 0, ' m')} deep whose stray reflections smear the consonant.`;
    }
    return backSentence(e).split('. ').slice(0, 2).join('. ');
  }
  function lessClearHTML(x) {
    const e = x.e, hd = e.headline || {};
    const parts = ['<div class="run">'];
    if (e.target_name) parts.push(`<h5>"${esc(e.target_name)}"</h5>`);
    else if (x.s.heading) parts.push(`<h5>${esc(x.s.heading)}</h5>`);
    parts.push(e.has_metrics ? vLines(e, 'compact') : `<p class="verdict">${verdictOf(e)[0]}</p>`);
    parts.push(`<p class="back">${lessClearWhy(x)}</p>`);
    const tl = trueLevel(e);
    parts.push(`<p class="small">${num(hd.depth_m, 0, ' m')} deep, ${hd.post_count == null ? 'posts not recorded' : fmt(hd.post_count, 0) + ' posts'}; echo about ${num(hd.echo_spl_db, 0, ' dB')} for a 100 dB clap${nv(tl) ? `, ${fmt(-tl, 0)} dB below the clap` : ''}.</p>`);
    parts.push(audioButtons(x));
    for (const o of e.earlier || []) parts.push(earlierLine(o));
    parts.push('</div>');
    return parts.join('');
  }

  function entryHTML(x) {
    const e = x.e, hd = e.headline || {};
    const [verdict, cls] = verdictOf(e);
    const parts = [`<div class="run">`];
    if (e.target_name && x.s.entries.length > 1) parts.push(`<h5>"${esc(e.target_name)}"</h5>`);
    const dw = designWords(e);
    parts.push(`<p class="small">${dw ? 'Design: ' + esc(dw) + '.' : esc(e.title || e.stage)}</p>`, e.has_metrics ? vLines(e, true) : `<p class="verdict ${cls}">${verdict}</p>`);
    const back = x.gp.key.startsWith('s1') && e.has_metrics ? '' : backSentence(e);
    if (back) parts.push(`<p class="back">${back}</p>`);
    const depth = hd.depth_m, lw = loudWords(hd.echo_spl_db), sh = e.shape || {};
    parts.push('<dl class="facts">',
      `<dt>Depth</dt><dd>${num(depth, 1, ' m')}${depth != null ? ` (about ${fmt(depth / 12, 1)} bus lengths)` : ''}</dd>`,
      `<dt>Posts</dt><dd>${hd.post_count == null ? 'not recorded' : fmt(hd.post_count, 0)}</dd>`,
      `<dt>Echo loudness</dt><dd>${num(hd.echo_spl_db, 0, ' dB')}${lw ? ', ' + lw : ''}${nv(trueLevel(e)) ? `; ${fmt(-trueLevel(e), 0)} dB below the clap` : ''}</dd>`,
      `<dt>Loudness, fast vs careful</dt><dd>${hd.tier_gap_db == null ? 'no careful-simulator result' : `within ${fmt(Math.abs(hd.tier_gap_db), 1)} dB of each other`}</dd>`);
    if (sh.tier0 != null && sh.tier1 != null) parts.push(`<dt>Shape, fast vs careful</dt><dd>spectrogram match ${fmt(sh.tier0, 2)} vs ${fmt(sh.tier1, 2)}${Math.abs(sh.tier0 - sh.tier1) >= 0.05 ? ': they disagree' : ': they agree'}</dd>`);
    parts.push('</dl>');
    if (e.metrics.length) {
      parts.push('<p class="small">The strict tests, one by one:</p><ul class="checks">');
      for (const m of e.metrics) {
        const mk = m.pass === true ? '<span class="mark-ok">Pass</span>' : m.pass === false ? '<span class="mark-no">Fail</span>' : '<span>n/a</span>';
        const u = m.unit ? (m.unit === '%' ? '%' : ' ' + esc(m.unit)) : '';
        const val = nv(m.value) ? fmt(m.value, Math.abs(m.value) < 10 ? 2 : 1) + u : 'no value (the judge could not measure it)';
        const thr = m.threshold == null ? '' : ` (needs ${cmpWord(m.comparator)} ${esc(m.threshold)}${u})`;
        const f = fl(e, m.id);
        const floor = nv(f) ? `<br><span class="small">Even a perfect echo scores ${fmt(f, Math.abs(f) < 10 ? 2 : 1)}${u} on this test.</span>` : '';
        parts.push(`<li>${mk} ${esc(cleanLabel(m.label))}: ${val}${thr}${floor}</li>`);
      }
      parts.push('</ul>');
    }
    if (e.fragile) parts.push(`<p class="small">Fragile${e.fragile_reason ? ': ' + esc(e.fragile_reason) : ''}.</p>`);
    parts.push(robustHTML(e));
    parts.push(audioButtons(x));
    if (e.scene && e.scene.posts && e.scene.posts.length) parts.push(`<canvas class="plan cv" data-h="150" data-plan="${x.id}" aria-label="Plan view of the designed post field"></canvas><p class="small">The design from above, you at the left${e.scene.posts.length < (hd.post_count || 0) ? `; one in ${Math.round(hd.post_count / e.scene.posts.length)} posts drawn` : ''}.</p>`);
    const fine = [...(e.caveats || [])];
    if (e.failure_cause) fine.unshift("In the run's own words: " + e.failure_cause);
    if (fine.length) parts.push(`<details class="fine"><summary>Fine print (${fine.length})</summary><ul>${fine.map((c) => `<li>${esc(c)}</li>`).join('')}</ul></details>`);
    for (const o of e.earlier || []) parts.push(earlierLine(o));
    parts.push('</div>');
    return parts.join('');
  }

  // ---------- loudness yardstick, with every final design marked ----------
  (function loud() {
    const fig = $('#loud'), cv = $('canvas', fig);
    const marks = [
      { db: 20, name: 'rustling leaves', short: 'leaves' }, { db: 35, name: 'quiet library', short: 'library' },
      { db: 60, name: 'conversation', short: 'talking' }, { db: 80, name: 'busy street', short: 'street' },
      { db: 100, name: 'a clap, at 1 m', short: 'clap at 1 m' },
    ];
    const res = heads.filter((x) => nv(x.e.headline && x.e.headline.echo_spl_db));
    function draw() {
      const { g, w, h } = setup(cv);
      const x0 = 10, xw = w - 20, X = (db) => x0 + db / 110 * xw, axisY = 92;
      g.fillStyle = palette.warn; g.globalAlpha = 0.12; g.fillRect(X(0), axisY - 14, X(35) - X(0), 14); g.globalAlpha = 1;
      text(g, 'likely lost outdoors', X(1), axisY - 3, palette.warn);
      g.strokeStyle = palette.ink; g.beginPath(); g.moveTo(X(0), axisY + 0.5); g.lineTo(X(110), axisY + 0.5); g.stroke();
      marks.forEach((m, k) => {
        g.beginPath(); g.moveTo(X(m.db) + 0.5, axisY); g.lineTo(X(m.db) + 0.5, axisY + 6 + (k % 3) * 16); g.stroke();
        const label = `${w < 500 ? m.short : m.name}, ${m.db} dB`, tw = g.measureText(label).width;
        const cx = Math.max(2 + tw / 2, Math.min(w - 2 - tw / 2, X(m.db)));
        text(g, label, cx, axisY + 18 + (k % 3) * 16, palette.muted, 'center');
      });
      // stage markers; labels placed in the first free row
      const rowsEnd = [];
      res.slice().sort((a, b) => a.e.headline.echo_spl_db - b.e.headline.echo_spl_db).forEach((x) => {
        const xx = X(Math.max(0, Math.min(110, x.e.headline.echo_spl_db)));
        g.fillStyle = featured(testOf(x.e)) ? palette.ok : palette.accent;
        g.beginPath(); g.moveTo(xx, axisY - 15); g.lineTo(xx - 4, axisY - 23); g.lineTo(xx + 4, axisY - 23); g.fill();
        const lab = shortName(x), tw = g.measureText(lab).width;
        let row = rowsEnd.findIndex((end) => end < xx - tw / 2 - 4);
        if (row < 0) { row = rowsEnd.length; rowsEnd.push(-1e9); }
        if (row > 3) return;
        rowsEnd[row] = xx + tw / 2;
        text(g, lab, Math.max(tw / 2 + 2, Math.min(w - tw / 2 - 2, xx)), axisY - 28 - row * 14, featured(testOf(x.e)) ? palette.ok : palette.accent, 'center');
      });
      text(g, 'decibels at the listener', w - 10, h - 4, palette.muted, 'right');
    }
    $('[data-out="caption"]', fig).textContent = res.length
      ? 'Marked in colour: how loud each final design\'s echo is expected to be at the listener, from the simulation, for a 100 dB clap (green: the ones the automated tests confirm; every echo here was accepted by ear). These are three-dimensional estimates and could easily be off by several decibels. Remember that the clap itself is far louder still.'
      : 'When the simulation finishes, each design\'s expected echo loudness will be marked on this scale. Until then, it is a yardstick.';
    drawers.push(draw);
  })();

  // ---------- what the simulation actually built ----------
  (function sizeTable() {
    const el = $('[data-out="size-table"]');
    const rows = heads.filter((x) => x.e.headline && nv(x.e.headline.depth_m));
    if (!rows.length) { el.hidden = true; return; }
    el.innerHTML = `<table class="tbl"><caption>What the simulation actually designed</caption><thead><tr><th>Target</th><th>Depth</th><th>Posts</th><th>Echo</th></tr></thead><tbody>${rows.map((x) => {
      const h = x.e.headline, spl = h.echo_spl_db;
      const la = x.e.level_along;
      const loud = !nv(spl) ? '' : la && la.below_35 ? `${fmt(spl, 0)} dB at its loudest; ${la.below_35} of ${la.spl_db.length} notes below the 35 dB line` : `${fmt(spl, 0)} dB, ${spl >= 35 ? 'above' : 'below'} the 35 dB line`;
      return `<tr><td>${esc(shortName(x))}</td><td>${fmt(h.depth_m, 0)} m</td><td>${h.post_count == null ? '' : fmt(h.post_count, 0)}</td><td>${loud}</td></tr>`;
    }).join('')}</tbody></table>`;
  })();

  // ---------- the whole story: sentences generated from the run data ----------
  const CNT = D.counts || { n: 0, strict: [], revised_yes: [], revised_null: [], revised_no: [], ear: [], revised_scored: 0 };
  const cap = (q) => q.charAt(0).toUpperCase() + q.slice(1);
  const nWord = (n) => ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'][n] || String(n);
  const range = (a, d = 0, unit = '') => { const v = a.filter(nv); if (!v.length) return null; const lo = Math.min(...v), hi = Math.max(...v); return Math.round(lo) === Math.round(hi) ? fmt(lo, d) + unit : `${fmt(lo, d)} to ${fmt(hi, d)}${unit}`; };
  (function story() {
    $('[data-out="status"]').innerHTML = (D.status || '').split(/(?<=\.)\s+(?=[A-Z0-9])/).map((q) => `<span>${esc(q)}</span>`).join('');
    const put = (k, html) => { const el = $(`[data-out="${k}"]`); if (!el) return; if (html) { el.innerHTML = html; el.hidden = false; } else el.hidden = true; };
    const chron = (gp) => gp.subs.flatMap((s) => s.entries.flatMap((e) => [...(e.earlier || [])].reverse().concat([e])));
    const ORD = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth'];
    const [g1, g2, g3, g4] = G;
    const b0 = g1 && g1.subs[0] && g1.subs[0].entries[0];
    const pm = b0 && (gate(b0, 'pitch_err_pct') || {}), cm = b0 && (gate(b0, 'spec_corr') || {});
    put('story-marks', pm && cm && pm.threshold != null ? `For the whistle: pitch within ${pm.threshold}% of the target all along the note, and a spectrogram (a picture of which pitches sound when) matching the target's with a score of ${cm.threshold} or better, where 1 is perfect.` : null);
    if (g1 && g1.subs.length) {
      const all = chron(g1), cur = all[all.length - 1];
      const first = all[0], how = (e) => esc(designWords(e).split(';')[0] || 'a new design');
      const bits = all.length > 1 ? `The first design used ${how(first)} (${gateWords(first) || 'no scores'}); the last used ${how(cur)} (${gateWords(cur) || 'no scores'}).` : `It used ${how(cur)} (${gateWords(cur) || 'no scores'}).`;
      const f = fl(cur, 'pitch_err_pct'), p = gate(cur, 'pitch_err_pct');
      put('story-s1', `<strong>The whistle.</strong> We designed it ${all.length === 1 ? 'once' : `${nWord(all.length)} times`}. ${bits} ${(cur.crit || {}).strict ? 'The last one passed the strict tests.' : `On the strict tests that is a near miss${p && nv(f) ? `: the limit is ${p.threshold}%, and even a perfect echo of a real clap scores ${fmt(f, 2)}%` : ''}. To the ear it is a whistle.`}`);
    } else put('story-s1', null);
    const deep = (gp) => gp ? range(gp.subs.flatMap((s) => s.entries.map((e) => e.headline && e.headline.depth_m))) : null;
    if (g2 && g2.subs.length) {
      const all = chron(g2);
      put('story-s2', `<strong>Longer sounds need deeper fields.</strong> The four notes needed ${deep(g2) || 'tens of'} m, and in ${all.length > 1 ? 'the first design' : 'that design'} the higher notes faded away inside the field.`);
    } else put('story-s2', null);
    const t3 = [];
    if (g3 && g3.subs.length) {
      const e0 = g3.subs[0].entries[0], sw = (e0.design || {}).strip_half_width_m;
      t3.push(`The tune needed ${deep(g3)} m${sw ? `, squeezed into a strip ${fmt(2 * sw, 0)} m wide to keep the simulation affordable` : ''}, and it came back mostly as hiss.`);
    }
    if (g4 && g4.subs.length) {
      const hello = heads.find((x) => x.gp === g4 && x.e.recognized && x.e.recognized.length);
      const hits = hello ? hello.e.recognized.filter((q) => /hello/i.test(q)).length : null;
      t3.push(`Speech needed ${deep(g4)} m. ${hello ? `A speech recognizer heard "hello" for ${hits} of ${hello.e.recognized.length} claps; the vowel and syllables came back blurred.` : ''}`);
    }
    put('story-s3', t3.length ? `${t3.join(' ')}` : null);
    const pk = (S.clap_params || []).map((q) => q.peak_hz);
    put('story-lesson-c', pk.length ? `The project's claps are brightest between ${fmt(Math.min(...pk) / 1000, 1)} and ${fmt(Math.max(...pk) / 1000, 1)} kHz, and thin posts return high pitches far better than low ones, so low notes and the deep resonances of a vowel start at a disadvantage. The whistle sits right in the sweet spot.` : null);
    // the afternoon
    const lv = D.listening;
    const n = CNT.n, nEar = CNT.ear.length;
    put('story-listen', lv && n ? `On the afternoon of ${dateWords(lv.date) || 'the same day'} the owner listened to each echo on its own, knowing what it was meant to be, and accepted ${nEar === n ? `all ${nWord(n)}` : `${nWord(nEar)} of ${nWord(n)}`}: "${esc(lv.quote || '')}". The strict tests had clearly been stricter than the ear, so a second set was drawn up afterwards with two duties: pass what the ear accepted, and still reject deliberately wrong echoes, such as another target's echo, the clap alone, the echo backwards, or the right sound a semitone off.` : null);
    put('story-review', CNT.revised_scored ? `An independent reviewer checked the new tests and made us withdraw a pass we had claimed: for the four notes, the rule had been fitted so closely to the accepted echo that it would also have passed a version with a wrong note. It now reads "not established". So the revised tests confirm ${nWord(CNT.revised_yes.length)} of ${nWord(n)} automatically (${listJoin(CNT.revised_yes)}${CNT.revised_yes.includes('"hello"') ? ', which relies on the same speech recognizer as the strict test, so it is not an independent check' : ''}). For the other ${nWord(CNT.revised_null.length)}, no automated measure could tell the accepted echo from wrong ones. The strict tests stay on the record unchanged: ${nWord(CNT.strict.length)} of ${nWord(n)} pass${CNT.strict.length === 1 ? 'es' : ''}${CNT.strict.length ? ` (${listJoin(CNT.strict)})` : ''}.` : null);
    // practical points
    const s1all = g1 ? chron(g1) : [];
    const cur1 = s1all[s1all.length - 1];
    const side = cur1 && (cur1.robust || []).find((x) => x.case === 'listener_side_1m');
    const jit = cur1 && (cur1.robust || []).find((x) => x.case === 'jitter'), nom = cur1 && (cur1.robust || []).find((x) => x.case === 'nominal');
    const rg = D.listen && D.listen.range, wl = D.whistle && D.whistle.true_db;
    put('story-surprise', [
      side ? `<p><strong>The listening spot is tiny.</strong> A metre to the side, the whistle falls apart (${valWords(side.m)}); the sweet spot is a few centimetres wide, because every echo must reach your ear in step.</p>` : null,
      jit && nom ? `<p><strong>Millimetres matter to the strict tests.</strong> Posts nudged by a few millimetres moved the scores from ${valWords(nom.m)} to ${valWords(jit.m)}, though the echo sounds almost the same.</p>` : null,
      `<p><strong>The echo is far quieter than the clap that makes it.</strong> ${rg ? `At the listener, the simulated echoes sit ${fmt(-rg[1], 0)} to ${fmt(-rg[0], 0)} dB below the clap${nv(wl) ? `; the whistle about ${fmt(-wl, 0)} dB below` : ''}. ` : ''}It arrives a couple of hundredths of a second after the clap, while the ear is still recovering. Whether a person standing there hears it straight after their own clap is the first thing a real test must answer.</p>`,
    ].filter(Boolean).join(''));
    put('closing-shown', n ? `What the simulation does show: in a careful two-dimensional model, rings of thin posts return a clap as a falling whistle that a listener recognises and that the revised tests confirm, and every other target comes back as something an ear that knew the target accepted. What it does not show: that any of this survives wind, ground and real posts outdoors; that a listener who does not know the target would name each sound; or that a person hears the echo right after their own clap.` : null);
    put('ears-note', nEar ? `The owner's ear accepted ${nEar === n ? `all ${nWord(n)}` : nWord(nEar)} echoes, knowing each target${D.blind_kit ? '; a blind-test kit, with the echoes shuffled and unlabelled, is ready and has not been run yet' : ''}. The real test is people listening, which is why every result has a play button.` : 'The real test is a person listening, which is why every result has a play button.');
    put('blind-note', D.blind_kit ? '; a blind-test kit has been prepared, and has not been run yet' : '');
  })();

  // ---------- "thicker air": a cartoon of fading through a post field ----------
  (function thick() {
    const fig = $('#thick'); if (!fig) return;
    const cv = $('canvas', fig), sa = $('[data-in="radius"]', fig), sw = $('[data-in="half"]', fig), sd = $('[data-in="depth"]', fig);
    // loss per metre ~ a^2 / (local fan width); the fan widens with range, so integrate from the first row at 3 m
    const shape = (a, half, depth) => a * a * Math.log((3 + depth) / 3) / (2 * Math.tan(half * Math.PI / 180));
    const cal = (D.calibration || []).filter((c) => nv(c.loss_db));
    // calibrate K: geometric mean over the real designs, so both land roughly where the files say
    const K = cal.length ? Math.exp(cal.reduce((s, c) => s + Math.log(c.loss_db / shape(c.radius_m, c.half_angle_deg, c.depth_m)), 0) / cal.length) : 30000;
    const loss = (a, half, depth) => K * shape(a, half, depth);
    const radius = () => +sa.value / 200; // slider is thickness in cm
    function draw() {
      const { g, w, h } = setup(cv);
      const a = radius(), half = +sw.value, depth = +sd.value, L = loss(a, half, depth);
      const x0 = 52, xw = w - 64, top = 14, hh = h - 44, Y = (db) => top + Math.min(1, db / 60) * hh;
      g.strokeStyle = palette.rule; g.beginPath();
      for (const db of [0, 20, 40, 60]) { g.moveTo(x0, Y(db) + 0.5); g.lineTo(x0 + xw, Y(db) + 0.5); text(g, db ? `\u2212${db} dB` : '0 dB', x0 - 4, Y(db) + 4, palette.muted, 'right'); }
      g.stroke();
      g.fillStyle = palette.accent; g.globalAlpha = 0.18; g.beginPath(); g.moveTo(x0, top);
      for (let i = 0; i <= 100; i++) { const d = depth * i / 100; g.lineTo(x0 + i / 100 * xw, Y(loss(a, half, d) * (d ? 1 : 0))); }
      g.lineTo(x0 + xw, top); g.closePath(); g.fill(); g.globalAlpha = 1;
      g.strokeStyle = palette.accent; g.lineWidth = 2; g.beginPath();
      for (let i = 0; i <= 100; i++) { const d = depth * i / 100, y = Y(d ? loss(a, half, d) : 0); i ? g.lineTo(x0 + i / 100 * xw, y) : g.moveTo(x0, y); }
      g.stroke(); g.lineWidth = 1;
      text(g, 'near rows', x0, h - 16, palette.muted);
      text(g, `far end, ${fmt(depth, 0)} m deep`, x0 + xw, h - 16, palette.muted, 'right');
      text(g, 'how much of the echo survives, by depth', x0 + xw, h - 2, palette.muted, 'right');
      if (L > 60) text(g, `off the scale: ${fmt(L, 0)} dB`, x0 + xw - 4, Y(60) - 6, palette.warn, 'right');
    }
    function update() {
      const a = radius(), half = +sw.value, depth = +sd.value, L = loss(a, half, depth);
      $('[data-out="radius"]', fig).textContent = `${fmt(+sa.value, 0)} cm`;
      $('[data-out="half"]', fig).textContent = `±${half}°`;
      $('[data-out="depth"]', fig).textContent = `${depth} m`;
      const pct = 100 * Math.pow(10, -L / 20);
      $('[data-out="readout"]', fig).innerHTML = `The echo from the far end comes back <b>${fmt(L, L < 10 ? 1 : 0)} dB</b> weaker than from the front rows: ${pct >= 0.01 ? `<b>${pct >= 1 ? fmt(pct, 0) : fmt(pct, 2)}%</b> of it survives the trip` : 'essentially none of it survives the trip'}.`;
      draw();
    }
    [sa, sw, sd].forEach((el) => el.addEventListener('input', update));
    fig.querySelectorAll('[data-cal]').forEach((b) => {
      const c = cal[+b.dataset.cal];
      if (!c) { b.hidden = true; return; }
      b.textContent = `Set to ${c.name.toLowerCase()}, first design`;
      b.addEventListener('click', () => { sa.value = c.radius_m * 200; sw.value = c.half_angle_deg; sd.value = Math.round(c.depth_m); update(); });
    });
    $('[data-out="real"]', fig).innerHTML = cal.length
      ? 'From the run files: ' + cal.map((c) => `${esc(c.name)}, first design (${fmt(c.radius_m * 200, 0)} cm posts, ±${fmt(c.half_angle_deg, 0)}°, ${fmt(c.depth_m, 1)} m): <b>${c.at_least ? 'at least ' : ''}${fmt(c.loss_db, 1)} dB</b> (${esc(c.source)}); the cartoon says ${fmt(loss(c.radius_m, c.half_angle_deg, c.depth_m), 1)} dB.`).join(' ')
      : 'The real fades will be printed here once the run files carry them.';
    drawers.push(update);
  })();

  function planDrawer(cv, sc) {
    drawers.push(() => {
      const { g, w, h } = setup(cv);
      let xMax = 1, yMax = 1;
      for (const p of sc.posts) { xMax = Math.max(xMax, p[0]); yMax = Math.max(yMax, Math.abs(p[1])); }
      const k = Math.min((w - 16) / (xMax + 1), (h - 16) / (2 * yMax));
      const X = (x) => 8 + (x + 0.8) * k, Y = (y) => h / 2 - y * k;
      g.fillStyle = palette.accent;
      for (const p of sc.posts) { g.beginPath(); g.arc(X(p[0]), Y(p[1]), Math.max(0.7, p[2] * k), 0, 7); g.fill(); }
      g.fillStyle = palette.ink; g.beginPath(); g.arc(X(0), Y(0), 3.5, 0, 7); g.fill();
      text(g, 'you', X(0), Y(0) + 16, palette.ink, 'center');
      text(g, `${fmt(xMax, 0)} m`, X(xMax), h - 2, palette.muted, 'right');
    });
  }

  // ---------- what works: the whistle ----------
  (function works() {
    const fig = $('#whistle'); if (!fig) return;
    const W = D.whistle, x = W && heads.find((q) => q.e.run_id === W.run_id);
    const put = (k, html) => { const el = $(`[data-out="${k}"]`); if (el) el.innerHTML = html || ''; };
    if (!W || !x) {
      put('works-what', 'The whistle\'s careful-simulator result will appear here once its run files exist.');
      fig.hidden = true; return;
    }
    const e = x.e, hd = e.headline || {}, d = e.design || {}, A = W.audio || {};
    put('works-what', `In the careful simulator, the design drawn below, ${hd.post_count != null ? fmt(hd.post_count, 0) : 'about a thousand'} thin posts in rings, answers a clap with a falling whistle (${esc(x.gp.blurb.replace(/^A falling whistle,\s*/, '').replace(/\.$/, ''))}). Listen for yourself, from the clap alone to the echo at its true loudness.`);
    const cv = $('canvas', fig);
    if (e.scene && e.scene.posts && e.scene.posts.length) planDrawer(cv, e.scene); else cv.hidden = true;
    const boost = W.boost_db, tl = W.true_db;
    const btn = [['clap', 'The clap', false], ['target', 'The target', !!A.target], ['echo', 'The echo alone', !!A.echo],
      ['boosted', nv(boost) ? `Clap, then echo (+${fmt(boost, 1)} dB)` : 'Clap, then echo', !!A.boosted], ['true', 'Clap, then echo at true level', !!A.true]];
    put('works-buttons', btn.filter((b) => b[0] === 'clap' || b[2]).map(([k, label]) => `<button class="btn${k === 'boosted' ? ' primary' : ''}" type="button" data-whistle="${k}">${label}</button>`).join(''));
    const say = {
      clap: 'One of the project\'s five model claps: a short burst of noise.',
      target: 'The sound the field was designed to return: a whistle falling from 3.5 to 2 kHz in 80 ms.',
      echo: 'The echo alone, from the careful simulator, turned up to full volume.',
      boosted: `The clap, then the echo raised by ${nv(boost) ? fmt(boost, 1) + ' dB' : 'a lot'}${nv(boost) && nv(tl) ? `, so that it sits ${fmt(-(tl + boost), 0)} dB under the clap` : ''}. This is roughly how it would sound if your ear did not have to recover from the clap.`,
      true: `The clap, then the echo at its true level${nv(tl) ? `, about ${fmt(-tl, 0)} dB below the clap` : ''}. At a comfortable volume most speakers will only reproduce the clap: the echo falls below what they, and the room, let through. That is what the owner heard too.`,
    };
    fig.querySelectorAll('[data-whistle]').forEach((b) => b.addEventListener('click', () => {
      const k = b.dataset.whistle;
      put('works-readout', say[k]);
      if (k === 'clap') { const c = CLAPS[0], z = new Float32Array(c.length + 2 * LEAD); z.set(c.map((v) => 0.9 * v / (peak(c) || 1)), LEAD); play(z); return; }
      playWav('whistle-' + k, A[k]).catch((err) => { b.disabled = true; b.textContent += ' (could not play)'; console.warn(err); });
    }));
    put('works-caption', `The design from above, you at the left${e.scene && e.scene.posts.length < (hd.post_count || 0) ? `; one in ${Math.round(hd.post_count / e.scene.posts.length)} posts drawn` : ''}. Sounds from the careful simulator's files for this design${nv(tl) ? `; the true echo level, ${fmt(tl, 1)} dB relative to the clap, is from the project's listening folder` : ''}.`);
    const lw = loudWords(hd.echo_spl_db);
    put('works-facts', `<strong>Size, posts, loudness.</strong> The field is ${num(hd.depth_m, 1, ' m')} deep${nv(hd.depth_m) && hd.depth_m > 9 && hd.depth_m < 16 ? ', about the length of a city bus,' : ''} and fans out ${d.half_angle_deg ? `${fmt(d.half_angle_deg, 0)} degrees either side` : 'to the sides'}. It has ${hd.post_count != null ? fmt(hd.post_count, 0) : 'about a thousand'} posts${d.radius_m ? `, each ${fmt(d.radius_m * 200, 0)} cm across` : ''}, so it is mostly open ground. For a 100 dB clap at arm's length the echo reaches about ${num(hd.echo_spl_db, 0, ' dB')} at your ear${lw ? `, ${lw.split(':')[0]}` : ''}: plenty on a quiet site, yet ${nv(tl) ? `${fmt(-tl, 0)} dB` : 'far'} below the clap itself.`);
    put('works-verdicts', vLines(e, true));
  })();

  (function renderResults() {
    const box = $('#results');
    const html = [];
    if (D.test_data) html.push(`<div class="test-banner">Test build: the results below come from ${esc(D.source)} and may be made-up numbers, not simulation results.</div>`);
    const isFeat = (x) => featured(testOf(x.e));
    const feat = heads.filter(isFeat);
    if (feat.length) {
      html.push('<h3 class="res-h">Sounds that came back clearly</h3>');
      feat.forEach((x) => html.push(`<section class="card feat"><h3>${esc(x.e.target_name ? (x.s.key === '4c' ? `The word "${x.e.target_name}"` : `"${x.e.target_name}"`) : x.gp.name)}</h3><p class="blurb">${esc(x.e.target_name ? (x.e.title || '').replace(/^Speech \w+:\s*/, '') : x.gp.blurb)}</p>${entryHTML(x)}</section>`));
    }
    const rest = G.map((gp, gi) => ({ gp, gi, xs: heads.filter((x) => x.gp === gp && !isFeat(x)) })).filter((r) => r.xs.length || !r.gp.subs.length);
    if (rest.length) html.push(`<h3 class="res-h quiet">${feat.length ? 'Sounds that came back less clearly' : 'Results'}</h3>`);
    rest.forEach(({ gp, xs }) => {
      html.push(`<section class="card${gp.subs.length ? ' quiet' : ' pending'}"><h3>${esc(gp.name)}</h3><p class="blurb">${esc(gp.blurb)}</p>`);
      if (!gp.subs.length) {
        const lo = { tier0_only: 'scored with the fast simulator only', intermediate: 'still being designed' }[gp.latest_other] || gp.latest_other;
        html.push(D.results.index_found
          ? `<p>No final result yet${lo ? `: the newest run for this stage is ${esc(lo)}` : ''}. This fills in when the stage has a final, scored run.</p>`
          : '<p>Simulation still running. This fills in when the stage has a final, scored run.</p>');
      }
      html.push(`<div class="${xs.length > 1 ? 'sub' : ''}">${xs.map(lessClearHTML).join('')}</div>`);
      html.push('</section>');
    });
    box.innerHTML = html.join('');
    box.querySelectorAll('[data-wav]').forEach((b) => b.addEventListener('click', () => {
      const id = b.dataset.wav, key = id.split('-').pop(), x = heads.find((q) => id.startsWith(q.id + '-'));
      playWav(id, x.e.audio[key]).catch((err) => { b.disabled = true; b.textContent += ' (could not play)'; console.warn(err); });
    }));
    box.querySelectorAll('[data-plan]').forEach((cv) => planDrawer(cv, heads.find((q) => q.id === cv.dataset.plan).e.scene));
    const done = G.filter((g) => g.subs.length).length;
    const when = new Date(D.built);
    $('[data-out="results-note"]').textContent = (D.results.index_found ? `${done} of ${G.length} stages have a final run.` : 'No simulation results yet: the runs are still going.') +
      ` Page built ${isNaN(when) ? D.built : when.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}.` +
      ' Every number above is read from the run files the simulation writes; none is typed in by hand.';
    if (D.results.problems.length) console.warn('results problems', D.results.problems);
  })();

  (function build() {
    const C$ = D.costs || {}, P = D.pilot, c = (k) => (C$[k] ? ` <span class="cost">${esc(C$[k].replace(/\s*\(est\.[^)]*\)/, '').replace(/^[~+]/, 'about '))} (estimate)</span>` : '');
    const steps = [
      `<strong>Hear it outdoors.</strong>${c('3a')} Drive one 20 mm steel bar into a quiet field, then a small regular row of 30 posts that should return a single tone. Several people clap and listen. <em>Tells us</em> whether a person hears an echo straight after their own clap, and what real ground and wind do. <em>Cannot tell</em> whether the whistle's fine shape survives.`,
      `<strong>A tabletop model at one tenth scale, in ultrasound.</strong>${C$['2a'] ? ` <span class="cost">about ${esc(C$['2a'].replace(/\s*\(est\.[^)]*\)/, '').replace(/^[~+]/, ''))} for the rig, then ${esc((C$['2b'] || '').replace(/\s*\(est\.[^)]*\)/, '').replace(/^\+/, ''))} and ${esc((C$['2c'] || '').replace(/\s*\(est\.[^)]*\)/, '').replace(/^\+/, ''))} for two pin boards (estimates)</span>` : ''} The physics is the same at a tenth of the size and ten times the pitch, so pins on a board stand in for posts, with real ground and real height. <em>Tells us</em> whether real posts behave as the careful simulator says, including whether its faint hiss is real. <em>Cannot tell</em> anything about hearing: the ear's recovery after a clap does not scale down.`,
      `<strong>A full-size whistle, only if both go well.</strong>${c('3b')} ${P ? `The pilot design: ${P.post_count != null ? fmt(P.post_count, 0) + ' posts' : 'a few hundred posts'}${P.depth_m != null ? ` in a field ${fmt(P.depth_m, 1)} m deep` : ''}. ` : ''}<em>Tells us</em> whether a clap returns the whistle outdoors, judged by listeners who are not told what to expect. <em>Cannot tell</em> whether longer pieces would work; those come only after a short one does.`,
    ];
    $('[data-out="build-steps"]').innerHTML = steps.map((q) => `<li>${q}</li>`).join('');
    $('[data-out="build-link"]').innerHTML = `The full plan, with parts lists, go and no-go numbers and the physics behind each rule, is in <a href="../BUILD.md">the build path</a>${D.build_md ? '' : ' (being written)'}. The code and every run are on <a href="https://github.com/shyamvalsan/echo-engineering">GitHub</a>; each run's sound-field animation and full scores are in <a href="../viewer/">the project viewer</a>.`;
    // try it yourself
    const rg = D.listen && D.listen.range;
    const tl = $('[data-out="try-level"]'); if (tl) tl.textContent = rg ? `In reality the echoes shown on this page sit ${fmt(-rg[1], 0)} to ${fmt(-rg[0], 0)} dB below the clap.` : '';
    const cu = D.custom, tc = $('[data-out="try-custom"]');
    if (tc) tc.textContent = cu ? `An example made this way: ${String(cu.title || 'a custom sound').replace(/^Custom:\s*/, '')}, ${cu.post_count != null ? fmt(cu.post_count, 0) + ' posts' : 'a field of posts'}${cu.depth_m != null ? ` ${fmt(cu.depth_m, 0)} m deep` : ''}${cu.verified ? ', checked on the careful simulator' : ', fast simulator only'}.` : '';
    const shot = $('[data-out="live-shot"]');
    if (shot && D.live_img) {
      shot.innerHTML = `<img src="${D.live_img.uri}" width="${D.live_img.w}" height="${D.live_img.h}" alt="The viewer's Live mode: a clap replayed, its wave spreading through a field of posts, with the echo, its spectrogram and the list of recorded claps beside it" loading="lazy"><figcaption>Live mode, replaying a clap against a structure designed from a supplied two-note sound. Left: the echo boost in decibels, with the true level marked. Middle: the wave moving through the posts. Right: your sound and its echo.</figcaption>`;
      shot.hidden = false;
    }
  })();
  $('[data-out="built"]').textContent = `Source data: ${D.source === 'runs' ? 'the project\'s run folders' : D.source}.`;

  // ---------- scattered by density versus exact rings ----------
  (function rings() {
    const fig = $('#rings'), cv = $('canvas', fig), sl = $('[data-in="nudge"]', fig);
    const d = design('bird'), t = d.t, n = t.length, NP = 1000, r = rng(11);
    // scattered: draw NP positions from the density bias + signal (inverse CDF)
    const cdf = new Float64Array(n + 1);
    for (let i = 0; i < n; i++) cdf[i + 1] = cdf[i] + d.prof[i];
    const scat = [];
    for (let k = 0; k < NP; k++) {
      const u = r() * cdf[n]; let lo = 0, hi = n;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cdf[m] <= u) lo = m; else hi = m; }
      scat.push(lo + (u - cdf[lo]) / Math.max(1e-12, cdf[lo + 1] - cdf[lo]));
    }
    // rings: one ring per crest of the waveform, posts per ring in proportion to the local loudness
    const crests = [];
    for (let i = 1; i < n - 1; i++) if (t[i] > t[i - 1] && t[i] >= t[i + 1] && t[i] > 0.05) {
      const den = t[i - 1] - 2 * t[i] + t[i + 1];
      crests.push({ x: i + (den ? 0.5 * (t[i - 1] - t[i + 1]) / den : 0), a: d.bias[i] });
    }
    const asum = crests.reduce((s, c) => s + c.a, 0), ring = [];
    for (const c of crests) for (let k = Math.max(1, Math.round(c.a / asum * NP)); k > 0; k--) ring.push(c.x);
    const offS = scat.map(() => 2 * r() - 1), offR = ring.map(() => 2 * r() - 1);
    const yS = scat.map(() => r()), yR = ring.map(() => r());
    const ideal = conv(t, CLAPS[0]);
    const mmToSamples = (mm) => mm / 1000 * 2 / C * FS;
    function echo(pos, off, mm) {
      const x = new Float32Array(n + 8), sh = mmToSamples(mm);
      for (let k = 0; k < pos.length; k++) { const p = Math.min(n + 4, Math.max(0, pos[k] + off[k] * sh)), i = Math.floor(p), f = p - i; x[i] += 1 - f; x[i + 1] += f; }
      return conv(x, CLAPS[0]);
    }
    function match(e) {
      let xy = 0, xx = 0, yy = 0; const m = Math.min(e.length, ideal.length);
      for (let i = 0; i < m; i++) { xy += e[i] * ideal[i]; xx += e[i] * e[i]; yy += ideal[i] * ideal[i]; }
      return Math.max(0, xy / Math.sqrt(xx * yy || 1));
    }
    let cache = {};
    function echoes() {
      const mm = +sl.value;
      if (cache.mm !== mm) cache = { mm, s: echo(scat, offS, mm), r: echo(ring, offR, mm) };
      return cache;
    }
    function draw() {
      const { g, w, h } = setup(cv), mm = +sl.value, sh = mmToSamples(mm);
      const x0 = 8, xw = w - 16, zw = Math.min(320, xw * 0.42), fw = xw - zw - 16, zx = x0 + xw - zw;
      const zn = Math.round(0.2 / DR), zi = Math.round(n * 0.35);
      const strip = (label, pos, off, ys, top, hh) => {
        text(g, label, x0, top - 6, palette.muted);
        g.fillStyle = palette.ink;
        for (let k = 0; k < pos.length; k++) {
          const p = pos[k] + off[k] * sh;
          g.beginPath(); g.arc(x0 + p / n * fw, top + 3 + ys[k] * (hh - 6), 1, 0, 7); g.fill();
          if (p >= zi && p < zi + zn) { g.beginPath(); g.arc(zx + (p - zi) / zn * zw, top + 4 + ys[k] * (hh - 8), 2.4, 0, 7); g.fill(); }
        }
        g.strokeStyle = palette.rule; g.strokeRect(zx + 0.5, top + 0.5, zw, hh);
        g.strokeStyle = palette.muted; g.beginPath(); g.moveTo(x0 + zi / n * fw, top - 2); g.lineTo(x0 + zi / n * fw, top + hh + 2); g.stroke();
      };
      const hh = (h - 70) / 2;
      strip('Scattered by density', scat, offS, yS, 22, hh);
      const rt = 22 + hh + 28;
      g.strokeStyle = palette.accent; g.globalAlpha = 0.45;
      for (const c of crests) if (c.x >= zi && c.x < zi + zn) { const x = zx + (c.x - zi) / zn * zw; g.beginPath(); g.moveTo(x, rt + 1); g.lineTo(x, rt + hh - 1); g.stroke(); }
      g.globalAlpha = 1;
      strip('Exact rings, one per ripple of the whistle', ring, offR, yR, rt, hh);
      text(g, `${R0} m`, x0, h - 4, palette.muted);
      text(g, `${fmt(R0 + n * DR, 1)} m`, x0 + fw, h - 4, palette.muted, 'right');
      text(g, fw < 300 ? '20 cm, magnified' : '20 cm of each, magnified', zx + zw, h - 4, palette.muted, 'right');
    }
    function update() {
      const mm = +sl.value, e = echoes();
      $('[data-out="nudge"]', fig).textContent = `${mm} mm`;
      $('[data-out="readout"]', fig).innerHTML = `Scattered: match <b>${fmt(100 * match(e.s), 0)}%</b>. Rings: match <b>${fmt(100 * match(e.r), 0)}%</b>. ${fmt(scat.length, 0)} and ${fmt(ring.length, 0)} posts${mm ? `, each moved by up to ${mm} mm along the range` : ''}.`;
      draw();
    }
    sl.addEventListener('input', update);
    $('[data-act="scatter"]', fig).addEventListener('click', () => play(mix(CLAPS[0], echoes().s, D0, null).buf));
    $('[data-act="rings"]', fig).addEventListener('click', () => play(mix(CLAPS[0], echoes().r, D0, null).buf));
    $('[data-act="target"]', fig).addEventListener('click', () => { const x = new Float32Array(n + 2 * LEAD); x.set(t.map((v) => 0.7 * v), LEAD); play(x); });
    drawers.push(update);
  })();

  readPalette();
  redrawAll();
  let rz = 0;
  new ResizeObserver(() => { cancelAnimationFrame(rz); rz = requestAnimationFrame(redrawAll); }).observe(document.body);
})();
