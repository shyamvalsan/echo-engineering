// Fixture run folders for developing the viewer before real runs exist.
// Follows the run-folder contract in .superpowers/sdd/plan/global-constraints.md exactly.
//
//   node viewer/fixtures/make_fixtures.mjs        (from the repo root; needs ffmpeg on PATH)
//
// Physics is simplified but consistent: posts in a ±20° wedge from 3 m, bistatic range
// rho = (|P-S| + |P-L|)/2, an echo from a post at rho arrives at 2·rho/c, the profile is a
// positive bias plus the target, and the echo is the clap convolved with that profile.
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "runs");
const C = 343.0, FS = 16000;
const S = [0, 0], L = [0, 0.3];
const HALF = 20, R_MIN = 3.0, DR = 0.01;
const CATALOG = [0.01, 0.02, 0.04, 0.08];
const T_DIRECT = 0.3 / C;

// ---------- small numeric helpers ----------
function rng(seed) { // mulberry32
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const gauss = (r) => { let u = 0, v = 0; while (u === 0) u = r(); v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
const peak = (x) => x.reduce((m, v) => Math.max(m, Math.abs(v)), 0);
const scale = (x, g) => x.map((v) => v * g);
const round = (v, d = 4) => Math.round(v * 10 ** d) / 10 ** d;

function biquadBandpass(x, f0, q) {
  const w = 2 * Math.PI * f0 / FS, al = Math.sin(w) / (2 * q), a0 = 1 + al;
  const b0 = al / a0, b2 = -al / a0, a1 = -2 * Math.cos(w) / a0, a2 = (1 - al) / a0;
  const y = new Float64Array(x.length); let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let n = 0; n < x.length; n++) { const v = b0 * x[n] + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = x[n]; y2 = y1; y1 = v; y[n] = v; }
  return y;
}
function convolve(a, b, n) {
  const y = new Float64Array(n);
  for (let i = 0; i < a.length; i++) { const ai = a[i]; if (ai === 0) continue;
    for (let j = 0; j < b.length && i + j < n; j++) y[i + j] += ai * b[j]; }
  return y;
}
function fft(re, im) { // in place radix-2
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) { let bit = n >> 1; for (; j & bit; bit >>= 1) j ^= bit; j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; } }
  for (let len = 2; len <= n; len <<= 1) { const ang = -2 * Math.PI / len;
    for (let i = 0; i < n; i += len) for (let k = 0; k < len / 2; k++) {
      const wr = Math.cos(ang * k), wi = Math.sin(ang * k);
      const ur = re[i + k], ui = im[i + k];
      const vr = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi, vi = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr;
      re[i + k] = ur + vr; im[i + k] = ui + vi; re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi; } }
}
function spectrogram(x) { // returns {freqs, times, db[F][T]} dB re own max, clipped to -60, 0.5 dB steps
  const N = 256, hop = 32, nb = Math.floor(5000 / (FS / N));
  const win = Array.from({ length: N }, (_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / N));
  const nT = Math.floor((x.length - N) / hop) + 1, mag = [];
  for (let t = 0; t < nT; t++) { const re = new Float64Array(N), im = new Float64Array(N);
    for (let i = 0; i < N; i++) re[i] = x[t * hop + i] * win[i]; fft(re, im);
    mag.push(Array.from({ length: nb + 1 }, (_, k) => Math.hypot(re[k], im[k]))); }
  let mx = 1e-12; for (const c of mag) for (const v of c) mx = Math.max(mx, v);
  const db = Array.from({ length: nb + 1 }, (_, k) => mag.map((c) => {
    const d = 20 * Math.log10(c[k] / mx + 1e-12); return Math.round(Math.max(-60, d) * 2) / 2; }));
  return { freqs: Array.from({ length: nb + 1 }, (_, k) => k * FS / N), times: Array.from({ length: nT }, (_, t) => round((t * hop + N / 2) / FS, 5)), db };
}

// ---------- audio ----------
function writeWav(file, x, float = false) {
  const n = x.length, bps = float ? 4 : 2, buf = Buffer.alloc(44 + n * bps);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * bps, 4); buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(float ? 3 : 1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(FS, 24); buf.writeUInt32LE(FS * bps, 28); buf.writeUInt16LE(bps, 32); buf.writeUInt16LE(bps * 8, 34);
  buf.write("data", 36); buf.writeUInt32LE(n * bps, 40);
  for (let i = 0; i < n; i++) { if (float) buf.writeFloatLE(x[i], 44 + i * 4);
    else buf.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(x[i] * 32767))), 44 + i * 2); }
  fs.writeFileSync(file, buf);
}
const DBFS1 = 10 ** (-1 / 20);
const normalize = (x) => { const p = peak(x) || 1; return { y: scale(x, DBFS1 / p), gain_db: round(20 * Math.log10(DBFS1 / p), 2) }; };

function clap(seed, durMs = 3.5, f0 = 2500) {
  const r = rng(seed), n = Math.round(durMs * 1e-3 * FS);
  const x = Array.from({ length: n }, (_, i) => gauss(r) * Math.sin(Math.PI * i / n) ** 2);
  const y = biquadBandpass(biquadBandpass(x, f0, 0.9), f0, 0.9);
  return scale(Array.from(y.slice(0, n + 64)), 1 / peak(y));
}

function fade(env, i, n, f) { return Math.min(1, i / f, (n - 1 - i) / f) * env; }
const targets = {
  bird: { len: 0.08, sig(tau) { if (tau < 0 || tau > 0.08) return 0; const f0 = 3500, f1 = 2000, T = 0.08;
    const ph = 2 * Math.PI * (f0 * tau + (f1 - f0) * tau * tau / (2 * T)); return Math.sin(ph) * Math.min(1, tau / 0.006, (T - tau) / 0.006); } },
  motif: { len: 0.18, notes: [1047, 1319, 1568, 2093], dur: 0.045 },
  melody: { len: 0.8, notes: [1318.5, 1318.5, 1396.9, 1568.0, 1568.0, 1396.9, 1318.5, 1174.7], dur: 0.1 },
};
for (const k of ["motif", "melody"]) { const t = targets[k];
  t.sig = (tau) => { if (tau < 0 || tau >= t.len) return 0; const i = Math.floor(tau / t.dur), u = tau - i * t.dur;
    return Math.sin(2 * Math.PI * t.notes[i] * u) * Math.min(1, u / 0.005, (t.dur - u) / 0.005); }; }

// ---------- geometry ----------
const rhoOf = (x, y) => (Math.hypot(x - S[0], y - S[1]) + Math.hypot(x - L[0], y - L[1])) / 2;
// point at bistatic range rho, bearing th from the source: r(4rho - 0.6 sin th) = 4rho^2 - 0.09
const pointAt = (rho, th) => { const r = (4 * rho * rho - 0.09) / (4 * rho - 0.6 * Math.sin(th)); return [r * Math.cos(th), r * Math.sin(th)]; };

function buildRun(cfg) {
  const r = rng(cfg.seed), tg = targets[cfg.target];
  const depth = round(tg.len * C / 2, 3), nBins = Math.round(depth / DR) + 1;
  const tStart = 2 * R_MIN / C, duration = Math.ceil((tStart + tg.len + 0.022) * 100) / 100, nS = Math.round(duration * FS);
  // profile: spreading-compensated (bias + signal), 2D backscatter amplitude ~ 1/rho
  const prof = [], sig = [];
  for (let i = 0; i < nBins; i++) { const rho = R_MIN + i * DR, tau = 2 * rho / C - tStart;
    const s = tg.sig(tau) * (cfg.quality ?? 1); sig.push(s);
    const bias = 0.5 + 0.06 * Math.sin(2 * Math.PI * i / nBins) ; // slowly varying bias
    prof.push(Math.max(0, (bias + 0.45 * s) * (rho / R_MIN) ** 0.5 * (cfg.profileNoise ? 1 + cfg.profileNoise * gauss(r) : 1))); }
  const pm = Math.max(...prof); for (let i = 0; i < nBins; i++) prof[i] = round(prof[i] / pm, 5);
  // posts: density proportional to the profile, scattered along each equal-delay arc
  const posts = []; let acc = 0; const K = cfg.posts / prof.reduce((a, b) => a + b, 0);
  for (let i = 0; i < nBins; i++) { acc += prof[i] * K;
    while (acc >= 1) { acc -= 1; const th = (2 * r() - 1) * (HALF - 0.5) * Math.PI / 180;
      const rad = CATALOG[r() < 0.62 ? 0 : r() < 0.7 ? 1 : r() < 0.8 ? 2 : 3];
      const [x, y] = pointAt(R_MIN + i * DR + (r() - 0.5) * DR, th); posts.push([round(x, 4), round(y, 4), rad]); } }
  // target audio, aligned to where its echo should arrive
  const target = Array.from({ length: nS }, (_, n) => tg.sig(n / FS - tStart));
  // impulse response from the profile (2D spreading back in), fractional delay by linear interpolation
  const h = new Float64Array(nS);
  for (let i = 0; i < nBins; i++) { const rho = R_MIN + i * DR, d = 2 * rho / C * FS, k = Math.floor(d), f = d - k;
    const a = prof[i] / (rho / R_MIN) ** 0.5; if (k + 1 < nS) { h[k] += a * (1 - f); h[k + 1] += a * f; } }
  const claps = [1, 2, 3, 4, 5].map((k) => clap(cfg.seed * 10 + k, 2 + 0.7 * k, 2000 + 220 * k));
  const echo0 = convolve(h, claps[2], nS);
  // "Tier 1": same echo plus a multiple-scattering tail, a touch of level loss, optional smear
  let echo1 = null;
  if (cfg.tier1) { const tail = new Float64Array(400); for (let i = 0; i < 400; i++) tail[i] = (i === 0 ? 0.9 : 0) + cfg.tier1.tail * gauss(r) * Math.exp(-i / 90);
    echo1 = convolve(echo0, tail, nS); }
  const scaleDb = cfg.levelDb, dirPeak = DBFS1;
  const direct = new Float64Array(nS); const k0 = Math.round(T_DIRECT * FS); claps[2].forEach((v, j) => { if (k0 + j < nS) direct[k0 + j] = v * dirPeak; });
  const ref = echo1 ?? echo0, rp = peak(ref);
  const asHeard = Array.from(direct, (v, n) => v + ref[n] / rp * dirPeak * 10 ** (scaleDb / 20));
  return { depth, nBins, tStart, duration, prof, posts, target, echo0, echo1, asHeard, claps };
}

function field(run, dir) { // synthetic pressure animation: outgoing pulse + rings scattered by a sample of posts
  const W = 384, H = 264, ext = [-1.5, run.depth + R_MIN + 1.5, -6.6, 6.6];
  const xs = (ext[1] - ext[0]) / W, ys = (ext[3] - ext[2]) / H;
  const spf = 0.0004, nF = Math.round(run.duration / spf), fps = 25, lam = 0.22;
  const ricker = (u) => { const a = (Math.PI * u / lam) ** 2; return (1 - 2 * a) * Math.exp(-a); };
  const r = rng(7), sample = [];
  for (let i = 0; i < 160; i++) sample.push(run.posts[Math.floor(r() * run.posts.length)]);
  const frames = Buffer.alloc(W * H * 3 * nF), p = new Float64Array(W * H);
  const bg = [14, 22, 32], pos = [240, 168, 72], neg = [86, 150, 230];
  for (let f = 0; f < nF; f++) { const t = f * spf, R = C * t; p.fill(0);
    for (let j = 0; j < H; j++) { const y = ext[3] - (j + 0.5) * ys;
      for (let i = 0; i < W; i++) { const x = ext[0] + (i + 0.5) * xs, d = Math.hypot(x, y);
        let v = Math.abs(d - R) < 3 * lam ? ricker(d - R) / Math.sqrt(Math.max(d, 0.4)) : 0;
        for (const q of sample) { const tj = Math.hypot(q[0], q[1]) / C; if (t <= tj) continue; const Rq = C * (t - tj);
          const dq = Math.hypot(x - q[0], y - q[1]); if (Math.abs(dq - Rq) > 2 * lam) continue;
          v += 0.9 * ricker(dq - Rq) * Math.sqrt(q[2] / 0.02) / Math.sqrt(Math.hypot(q[0], q[1]) * Math.max(dq, 0.15)); }
        p[j * W + i] = v; } }
    for (let k = 0; k < W * H; k++) { const v = Math.sign(p[k]) * Math.min(1, Math.abs(p[k] / 0.55) ** 0.6), c = v >= 0 ? pos : neg, a = Math.abs(v);
      for (let ch = 0; ch < 3; ch++) frames[(f * W * H + k) * 3 + ch] = Math.round(bg[ch] + (c[ch] - bg[ch]) * a); } }
  const out = spawnSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", `${W}x${H}`, "-r", String(fps), "-i", "-",
    "-c:v", "libvpx-vp9", "-g", "1", "-b:v", "0", "-crf", "30", "-pix_fmt", "yuv420p", path.join(dir, "field.webm")], { input: frames });
  if (out.status !== 0) throw new Error("ffmpeg failed: " + out.stderr);
  return { file: "field.webm", fps, n_frames: nF, t0_s: 0, sim_seconds_per_frame: spf, extent_m: ext.map((v) => round(v, 3)), width: W, height: H };
}

const json = (dir, name, obj) => fs.writeFileSync(path.join(dir, name), JSON.stringify(obj));
const sceneJson = (run, posts = run.posts) => ({ units: "m", c: C, source: S, listener: L,
  wedge: { half_angle_deg: HALF, r_min: R_MIN, r_max: round(R_MIN + run.depth, 3) }, posts });
const profileJson = (prof) => ({ r0_m: R_MIN, dr_m: DR, reflectivity: prof, units: "relative (max = 1)" });
const M = (id, label, value, unit, threshold, comparator, tier, gating) => ({ id, label, value, unit, threshold, comparator,
  pass: comparator == null ? null : comparator === "<=" ? value <= threshold : comparator === ">=" ? value >= threshold : value === threshold, tier, gating });

function writeRun(cfg) {
  const run = buildRun(cfg), dir = path.join(OUT, cfg.stage, cfg.run_id);
  fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true });
  const t = normalize(run.target), e0 = normalize(run.echo0), e1 = run.echo1 ? normalize(run.echo1) : null;
  writeWav(path.join(dir, "target.wav"), t.y); writeWav(path.join(dir, "echo_tier0.wav"), e0.y);
  if (e1) writeWav(path.join(dir, "echo_tier1.wav"), e1.y);
  writeWav(path.join(dir, "as_heard.wav"), run.asHeard, true);
  json(dir, "scene.json", sceneJson(run)); json(dir, "profile.json", profileJson(run.prof));
  const sp = (x) => spectrogram(x), st = sp(run.target);
  json(dir, "spectrograms.json", { fs: FS, freqs_hz: st.freqs, times_s: st.times, db_floor: -60,
    panels: { target: st.db, tier0: sp(run.echo0).db, tier1: run.echo1 ? sp(run.echo1).db : null } });
  const fld = cfg.field ? field(run, dir) : null;
  const fill = run.posts.reduce((a, p) => a + Math.PI * p[2] * p[2], 0) / ((HALF * Math.PI / 180) * ((R_MIN + run.depth) ** 2 - R_MIN ** 2));
  const tier1 = !!cfg.tier1;
  json(dir, "manifest.json", { run_id: cfg.run_id, stage: cfg.stage, title: cfg.title, created: cfg.created, seed: cfg.seed,
    git_commit: "fixture", status: cfg.status, verified: cfg.verified, fs: FS, c: C, duration_s: run.duration, t_direct_s: round(T_DIRECT, 7),
    command: "node viewer/fixtures/make_fixtures.mjs",
    solver: tier1 ? { tier1: "fdtd", device: "cpu", dx: 0.0086, dt: 1.25e-5, grid: [2100, 1600], f_lo: 500, f_max: 4000, ppw: 10, wall_s: 812.4 }
      : { tier1: "none", device: "cpu", dx: null, dt: null, grid: null, f_lo: 500, f_max: 4000, ppw: null, wall_s: null },
    field: fld, audio: { echo_gain_db: { tier0: e0.gain_db, tier1: e1 ? e1.gain_db : null }, as_heard_echo_level_db: cfg.levelDb },
    notes: "Fixture generated for viewer development. Not a simulation result." });
  const lv = cfg.levelDb, gap = tier1 ? cfg.tierGap : null;
  json(dir, "metrics.json", { stage: cfg.stage, passed: cfg.passed, verified: cfg.verified, fragile: !!cfg.fragile,
    headline: { echo_level_db_re_direct: lv, echo_level_db_re_direct_raw3d: round(lv - (gap ?? 0), 2), echo_spl_db: round(110.46 + lv, 2),
      depth_m: run.depth, post_count: run.posts.length, fill_fraction: round(fill, 5), tier_gap_db: gap },
    metrics: cfg.metrics, per_clap: run.claps.map((_, k) => ({ clap: k, metrics: Object.fromEntries(cfg.metrics.filter((m) => m.unit !== "dB").map((m) => [m.id, round(m.value * (1 + 0.03 * (k - 2)), 3)])) })),
    robustness: cfg.robustness ?? [], failure_cause: cfg.failure_cause ?? null });
  // history and saved iterations
  const nI = cfg.iters ?? 300, iters = Array.from({ length: nI / 5 + 1 }, (_, i) => i * 5);
  const loss = iters.map((i) => round(0.18 + 2.4 * Math.exp(-i / 55) + 0.02 * Math.sin(i / 7), 4));
  const phases = [{ name: "Profile solve", x_label: "Adam step", iters, loss, score: null, saved: [] }];
  if (cfg.saveIters) {
    for (const [name, it, q] of [["solve_0000", 0, 0.1], ["solve_0150", 150, 0.6]]) {
      const ph = phases[0]; ph.saved.push({ iter: it, dir: `iters/${name}` });
      const sub = buildRun({ ...cfg, quality: q, profileNoise: 0.25 * (1 - q), posts: Math.round(cfg.posts * (0.7 + 0.3 * q)) });
      const idir = path.join(dir, "iters", name); fs.mkdirSync(idir, { recursive: true });
      json(idir, "scene.json", sceneJson(sub)); json(idir, "profile.json", profileJson(sub.prof));
      writeWav(path.join(idir, "echo.wav"), normalize(sub.echo0).y);
      json(idir, "metrics.json", { stage: cfg.stage, passed: false, verified: false, fragile: false,
        headline: { echo_level_db_re_direct: lv - 3, echo_level_db_re_direct_raw3d: lv - 3, echo_spl_db: round(110.46 + lv - 3, 2), depth_m: sub.depth, post_count: sub.posts.length, fill_fraction: null, tier_gap_db: null },
        metrics: cfg.metrics.map((m) => ({ ...m, value: round(m.unit === "%" ? m.value * (3.5 - 2.5 * q) : m.value * (0.5 + 0.5 * q), 3), pass: null, tier: "tier0" })), per_clap: [], robustness: [], failure_cause: null });
    }
  }
  if (tier1) { const rounds = [0, 1, 2, 3]; const sc = cfg.passed ? [0.71, 0.79, 0.84, 0.86] : [0.62, 0.66, 0.67, 0.67];
    phases.push({ name: "Tier 1 correction", x_label: "Round", iters: rounds, loss: sc.map((s) => round(1 - s, 3)), score: sc,
      saved: cfg.saveIters ? [{ iter: 3, dir: "iters/corr_3" }] : [] });
    if (cfg.saveIters) { const idir = path.join(dir, "iters", "corr_3"); fs.mkdirSync(idir, { recursive: true });
      json(idir, "scene.json", sceneJson(run)); json(idir, "profile.json", profileJson(run.prof));
      writeWav(path.join(idir, "echo.wav"), e1.y);
      json(idir, "metrics.json", JSON.parse(fs.readFileSync(path.join(dir, "metrics.json")))); } }
  json(dir, "history.json", { phases });
  console.log(`${cfg.stage}/${cfg.run_id}: ${run.posts.length} posts, depth ${run.depth} m, ${run.duration} s${fld ? `, field ${fld.n_frames} frames` : ""}`);
  return { stage: cfg.stage, run_id: cfg.run_id, path: `${cfg.stage}/${cfg.run_id}`, title: cfg.title, created: cfg.created, status: cfg.status, passed: cfg.passed, verified: cfg.verified };
}

const rob = (rows) => rows.map(([c, label, sc, d, pass]) => ({ case: c, label, metrics: { spec_corr: sc }, delta: { spec_corr: d }, pass }));
const runs = [
  writeRun({ stage: "s1_bird", run_id: "20261124-2310-fx-final", title: "Bird note, final (fixture)", created: "2026-11-24T23:10:00+02:00",
    seed: 11, target: "bird", posts: 3200, status: "final", verified: true, passed: true, levelDb: -31.4, tierGap: -1.3,
    tier1: { tail: 0.05 }, field: true, saveIters: true, iters: 300,
    metrics: [M("pitch_err_max_pct", "Pitch error along the note, worst point", 1.9, "%", 3, "<=", "tier1", true),
      M("spec_corr", "Spectrogram correlation, log-mel", 0.86, "", 0.8, ">=", "tier1", true),
      M("spec_corr_t0", "Spectrogram correlation, Tier 0", 0.91, "", 0.8, ">=", "tier0", false),
      M("echo_level", "Echo level re direct, 3D corrected", -31.4, "dB", null, null, "tier1", false)],
    robustness: rob([["listener_side_1m", "Listener 1 m sideways", 0.83, -0.03, true], ["listener_back_1m", "Listener 1 m back", 0.84, -0.02, true],
      ["c_331", "Speed of sound 331 m/s", 0.81, -0.05, true], ["c_349", "Speed of sound 349 m/s", 0.82, -0.04, true],
      ["jitter", "Posts jittered 5 mm, radii 1 mm", 0.85, -0.01, true], ["clap_0", "Clap variant 0 alone", 0.79, -0.07, false]]) }),
  writeRun({ stage: "s1_bird", run_id: "20261124-2240-fx-tier0", title: "Bird note, Tier 0 only (fixture)", created: "2026-11-24T22:40:00+02:00",
    seed: 12, target: "bird", posts: 2600, status: "tier0_only", verified: false, passed: false, levelDb: -30.1, tier1: null, field: false, iters: 200,
    metrics: [M("pitch_err_max_pct", "Pitch error along the note, worst point", 2.4, "%", 3, "<=", "tier0", false),
      M("spec_corr", "Spectrogram correlation, log-mel", 0.88, "", 0.8, ">=", "tier0", false)] }),
  writeRun({ stage: "s2_motif", run_id: "20261125-0105-fx-failed", title: "Motif, failed (fixture)", created: "2026-11-25T01:05:00+02:00",
    seed: 21, target: "motif", posts: 6500, status: "final", verified: true, passed: false, fragile: true, levelDb: -36.8, tierGap: -3.9,
    tier1: { tail: 0.22 }, field: false, iters: 400, profileNoise: 0.1,
    failure_cause: "G6 and C7 smeared by multiple scattering in the dense rear field; G6 detected at +46 cents (threshold 30).",
    metrics: [M("notes_in_order", "Notes detected in order", 2, "of 4", 4, "==", "tier1", true),
      M("max_cents", "Worst note error", 46, "cents", 30, "<=", "tier1", true),
      M("spec_corr", "Spectrogram correlation, log-mel", 0.67, "", null, null, "tier1", false)],
    robustness: rob([["listener_side_1m", "Listener 1 m sideways", 0.61, -0.06, false], ["c_331", "Speed of sound 331 m/s", 0.6, -0.07, false]]) }),
  writeRun({ stage: "s3_melody", run_id: "20261125-0230-fx-tier0", title: "Ode to Joy, 100 ms notes, Tier 0 only (fixture)", created: "2026-11-25T02:30:00+02:00",
    seed: 31, target: "melody", posts: 20000, status: "tier0_only", verified: false, passed: false, levelDb: -41.2, tier1: null, field: false, iters: 300,
    metrics: [M("notes_match", "Transcribed sequence matches", 8, "of 8", 8, "==", "tier0", false),
      M("max_cents", "Worst note error", 21, "cents", 50, "<=", "tier0", false)] }),
];
runs.sort((a, b) => b.created.localeCompare(a.created));
json(OUT, "index.json", { runs });
console.log(`wrote ${runs.length} runs to ${OUT}`);
