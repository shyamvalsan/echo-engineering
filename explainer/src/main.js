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

  // ---------- results ----------
  const allRuns = [];
  D.results.groups.forEach((gp) => gp.runs.forEach((r) => allRuns.push({ ...r, group: gp.name })));

  function loudWords(db) {
    if (db == null) return null;
    if (db < 20) return 'quieter than rustling leaves: almost certainly inaudible outdoors';
    if (db < 35) return 'about a whisper: likely lost in outdoor background noise';
    if (db < 50) return 'about a quiet room: audible on a calm, quiet site';
    if (db < 65) return 'about normal conversation';
    if (db < 80) return 'about a busy street';
    return 'louder than a busy street';
  }

  (function loud() {
    const fig = $('#loud'), cv = $('canvas', fig);
    const marks = [
      { db: 20, name: 'rustling leaves', short: 'leaves' }, { db: 35, name: 'quiet library', short: 'library' },
      { db: 60, name: 'conversation', short: 'talking' }, { db: 80, name: 'busy street', short: 'street' },
      { db: 100, name: 'a clap, at 1 m', short: 'clap at 1 m' },
    ];
    const results = allRuns.filter((r) => r.headline && r.headline.echo_spl_db != null);
    function draw() {
      const { g, w, h } = setup(cv);
      const x0 = 10, xw = w - 20, X = (db) => x0 + db / 110 * xw, axisY = 70;
      g.fillStyle = palette.warn; g.globalAlpha = 0.12; g.fillRect(X(0), axisY - 14, X(35) - X(0), 14); g.globalAlpha = 1;
      text(g, 'likely lost outdoors', X(1), axisY - 18, palette.warn);
      g.strokeStyle = palette.ink; g.beginPath(); g.moveTo(X(0), axisY + 0.5); g.lineTo(X(110), axisY + 0.5); g.stroke();
      marks.forEach((m, k) => {
        g.beginPath(); g.moveTo(X(m.db) + 0.5, axisY); g.lineTo(X(m.db) + 0.5, axisY + 6 + (k % 3) * 16); g.stroke();
        const label = `${w < 500 ? m.short : m.name}, ${m.db} dB`, tw = g.measureText(label).width;
        const cx = Math.max(2 + tw / 2, Math.min(w - 2 - tw / 2, X(m.db)));
        text(g, label, cx, axisY + 18 + (k % 3) * 16, palette.muted, 'center');
      });
      results.forEach((r, k) => {
        const x = X(Math.max(0, Math.min(110, r.headline.echo_spl_db)));
        g.fillStyle = palette.accent; g.beginPath(); g.moveTo(x, axisY - 2); g.lineTo(x - 5, axisY - 12); g.lineTo(x + 5, axisY - 12); g.fill();
        text(g, r.group, x, axisY - 30 - (k % 2) * 14, palette.accent, x > w - 50 ? 'right' : 'center');
      });
      text(g, 'decibels at the listener', w - 10, h - 4, palette.muted, 'right');
    }
    $('[data-out="caption"]', fig).textContent = results.length
      ? 'Marked in colour: how loud each finished design\'s echo is expected to be at the listener, from the simulation, for a 100 dB clap. These are three-dimensional estimates and could easily be off by several decibels.'
      : 'When the simulation finishes, each design\'s expected echo loudness will be marked on this scale. Until then, it is a yardstick.';
    drawers.push(draw);
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
  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
  function num(v, d = 1, unit = '') { return v == null || Number.isNaN(+v) ? 'not recorded' : fmt(+v, d) + unit; }
  function cmpWord(c) { return c === '<=' ? 'at most' : c === '>=' ? 'at least' : c === '==' ? 'exactly' : ''; }

  function runHTML(r, gi, ri) {
    const hd = r.headline || {};
    let verdict, cls = '';
    if (!r.has_metrics) verdict = 'A final run exists, but its scores could not be read.';
    else if (r.passed && r.verified) { verdict = 'Passed, confirmed by the full-wave referee.'; cls = 'pass'; }
    else if (r.passed) verdict = 'Passed in the fast model only. Not confirmed by the full-wave referee, so treat it as provisional.';
    else { verdict = r.verified === false ? 'Did not pass (and not checked by the full-wave referee).' : 'Did not pass.'; cls = 'fail'; }
    const parts = [`<div class="run">`, `<p class="small">${esc(r.title || r.stage)}</p>`, `<p class="verdict ${cls}">${verdict}</p>`];
    if (r.failure_cause) parts.push(`<p class="cause">Why: ${esc(r.failure_cause)}</p>`);
    if (r.fragile) parts.push(`<p>Fragile: it stops passing when ${r.robust_failed.length ? esc(r.robust_failed.join('; ').toLowerCase()) : 'conditions change'}.</p>`);
    else if (r.robust_total && r.robust_failed.length) parts.push(`<p class="small">Checked under ${r.robust_total} changed conditions (moved listener, hot and cold air, sloppy building, single claps); it slipped in: ${esc(r.robust_failed.join('; '))}.</p>`);
    const depth = hd.depth_m, bus = depth != null ? ` (about ${fmt(depth / 12, 1)} bus lengths)` : '';
    const lw = loudWords(hd.echo_spl_db);
    parts.push('<dl class="facts">',
      `<dt>Depth</dt><dd>${num(depth, 1, ' m')}${bus}</dd>`,
      `<dt>Posts</dt><dd>${hd.post_count == null ? 'not recorded' : fmt(hd.post_count, 0)}</dd>`,
      `<dt>Echo loudness</dt><dd>${num(hd.echo_spl_db, 0, ' dB')}${lw ? ', ' + lw : ''}</dd>`,
      `<dt>Models agree to</dt><dd>${hd.tier_gap_db == null ? 'no referee result' : `${fmt(Math.abs(hd.tier_gap_db), 1)} dB (fast model vs full-wave referee)`}</dd>`,
      '</dl>');
    if (r.metrics.length) {
      parts.push('<ul class="checks">');
      for (const m of r.metrics) {
        const mk = m.pass === true ? '<span class="mark-ok">Pass</span>' : m.pass === false ? '<span class="mark-no">Fail</span>' : '<span>n/a</span>';
        const val = typeof m.value === 'number' ? fmt(m.value, Math.abs(m.value) < 10 ? 2 : 1) : esc(m.value == null ? 'none' : JSON.stringify(m.value));
        const thr = m.threshold == null ? '' : ` (needs ${cmpWord(m.comparator)} ${esc(m.threshold)}${m.unit ? ' ' + esc(m.unit) : ''})`;
        parts.push(`<li>${mk} ${esc(m.label)}: ${val}${m.unit ? ' ' + esc(m.unit) : ''}${thr}</li>`);
      }
      parts.push('</ul>');
    }
    const a = r.audio || {};
    parts.push('<div class="controls">');
    if (a.target) parts.push(`<button class="btn" type="button" data-wav="${gi}-${ri}-target">Target</button>`);
    if (a.echo) parts.push(`<button class="btn primary" type="button" data-wav="${gi}-${ri}-echo">Echo${a.echo_is_tier0 ? ' (fast model)' : ''}, turned up</button>`);
    if (a.as_heard) parts.push(`<button class="btn" type="button" data-wav="${gi}-${ri}-as_heard">As heard, true loudness</button>`);
    if (!a.target && !a.echo && !a.as_heard) parts.push('<span class="small">No audio files were written for this run.</span>');
    parts.push('</div>');
    if (r.scene && r.scene.posts && r.scene.posts.length) parts.push(`<canvas class="plan cv" data-h="190" data-plan="${gi}-${ri}" aria-label="Plan view of the designed post field"></canvas><p class="small">The real design from above, you at the left${r.scene.posts.length < (hd.post_count || 0) ? `; one in ${Math.round(hd.post_count / r.scene.posts.length)} posts drawn` : ''}.</p>`);
    parts.push('</div>');
    return parts.join('');
  }

  (function renderResults() {
    const box = $('#results'), G = D.results.groups;
    const html = [];
    if (D.test_data) html.push(`<div class="test-banner">Test build: the results below come from ${esc(D.source)} and are made-up numbers, not simulation results.</div>`);
    G.forEach((gp, gi) => {
      html.push(`<section class="card${gp.runs.length ? '' : ' pending'}"><h3>${esc(gp.name)}</h3><p class="blurb">${esc(gp.blurb)}</p>`);
      if (!gp.runs.length) {
        const lo = { tier0_only: 'scored with the fast model only', intermediate: 'still being designed' }[gp.latest_other] || gp.latest_other;
        html.push(D.results.index_found
          ? `<p>No final result yet${lo ? `: the newest run for this stage is ${esc(lo)}` : ''}. This fills in when the stage has a final, scored run.</p>`
          : '<p>Simulation still running. This fills in when the stage has a final, scored run.</p>');
      }
      else html.push(`<div class="${gp.runs.length > 1 ? 'sub' : ''}">${gp.runs.map((r, ri) => runHTML(r, gi, ri)).join('')}</div>`);
      html.push('</section>');
    });
    box.innerHTML = html.join('');
    box.querySelectorAll('[data-wav]').forEach((b) => b.addEventListener('click', () => {
      const [gi, ri, key] = b.dataset.wav.split('-');
      playWav(b.dataset.wav, G[+gi].runs[+ri].audio[key]).catch((e) => { b.disabled = true; b.textContent += ' (could not play)'; console.warn(e); });
    }));
    box.querySelectorAll('[data-plan]').forEach((cv) => {
      const [gi, ri] = cv.dataset.plan.split('-').map(Number), sc = G[gi].runs[ri].scene;
      drawers.push(() => {
        const { g, w, h } = setup(cv);
        let xMax = 1, yMax = 1;
        for (const p of sc.posts) { xMax = Math.max(xMax, p[0]); yMax = Math.max(yMax, Math.abs(p[1])); }
        const k = Math.min((w - 16) / (xMax + 1), (h - 16) / (2 * yMax));
        const X = (x) => 8 + (x + 0.8) * k, Y = (y) => h / 2 - y * k;
        g.fillStyle = palette.accent;
        for (const p of sc.posts) { g.beginPath(); g.arc(X(p[0]), Y(p[1]), Math.max(0.7, p[2] * k), 0, 7); g.fill(); }
        g.fillStyle = palette.ink; g.beginPath(); g.arc(X(0), Y(0), 3.5, 0, 7); g.fill();
        text(g, `${fmt(xMax, 0)} m`, X(xMax), h - 2, palette.muted, 'right');
      });
    });
    const done = G.filter((g) => g.runs.length).length;
    const when = new Date(D.built);
    $('[data-out="results-note"]').textContent = (D.results.index_found ? `${done} of ${G.length} stages have a final run.` : 'No simulation results yet: the runs are still going.') +
      ` Page built ${isNaN(when) ? D.built : when.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}.` +
      ' Every number above is read from the run files the simulation writes; none is typed in by hand.';
    if (D.results.problems.length) console.warn('results problems', D.results.problems);
  })();

  $('[data-out="build-link"]').innerHTML = `The plan for each step is in <a href="../BUILD.md">the build path</a>${D.build_md ? '' : ' (being written)'}. Every run, its sound field animation and its full scores are in <a href="../viewer/">the project viewer</a>.`;
  $('[data-out="built"]').textContent = `Source data: ${D.source === 'runs' ? 'the project\'s run folders' : D.source}.`;

  readPalette();
  redrawAll();
  let rz = 0;
  new ResizeObserver(() => { cancelAnimationFrame(rz); rz = requestAnimationFrame(redrawAll); }).observe(document.body);
})();
