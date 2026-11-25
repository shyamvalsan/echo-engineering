// Impulse responses for Live mode. Preferred: the run's own ir_tier{0,1}.wav (manifest.ir), where
// source ⊛ ir is the echo at its true level relative to the source heard directly, sample 0 = emission.
// Fallback for runs written before that contract: derive the IR in the browser by a band-limited,
// regularized deconvolution of the stored echo by the stored clap (both clap variant 0), scaled so
// the clap's echo has the run's as-heard level.
import { parseWav } from "../data.js";
import { FS, deconvolve, peakOf, resample, convolve } from "./dsp.js";

const cache = new Map();

async function wav(url) { const r = await fetch(url, { cache: "no-cache" }); if (!r.ok) throw new Error(`${r.status} ${url}`); return parseWav(await r.arrayBuffer()); }
const to16k = async (t) => (t.fs === FS ? t.data : await resample(t.data, t.fs, FS));

// first-echo delay from the geometry: min over posts of 2 rho / c (rho bistatic)
export function firstDelay(run) {
  const sc = run.scene, c = run.c; if (!sc?.posts?.length) return sc?.wedge ? 2 * sc.wedge.r_min / c : 0.0;
  const [sx, sy] = sc.source ?? [0, 0], [lx, ly] = sc.listener ?? [0, 0.3]; let m = Infinity;
  for (const [x, y, r] of sc.posts) m = Math.min(m, (Math.hypot(x - sx, y - sy) + Math.hypot(x - lx, y - ly)) / 2 - (r ?? 0));
  return 2 * m / c;
}

// The run's clap (delay removed, peak 1) from as_heard.wav: the direct arrival before the first echo.
export async function runClap(run) {
  const ah = run.audio.asHeard; if (!ah) return null;
  const d = await to16k(ah), td = run.manifest.t_direct_s ?? 0.3 / run.c;
  const end = Math.min(Math.round(0.012 * FS), Math.round((firstDelay(run) - 0.001) * FS));
  const clap = d.slice(Math.round(td * FS), Math.max(Math.round(td * FS) + 16, end)), pk = peakOf(clap) || 1;
  return { data: clap.map((v) => v / pk), echoTail: d, end, peak: pk };
}

// -> {data, fs, lead, tDirect, key, origin: "file"|"derived", levelDb, note} or throws
export async function loadIR(run, tier) {
  const key = `${run.dir}|${tier}`;
  if (!cache.has(key)) cache.set(key, build(run, tier).catch((e) => { cache.delete(key); throw e; }));
  return cache.get(key);
}

async function build(run, tier) {
  const m = run.manifest, tDirect = m.t_direct_s ?? 0.3 / run.c, geo = firstDelay(run), irm = m.ir;
  const file = irm?.[tier] ?? (irm ? null : undefined);
  let data, origin, note;
  if (file) {
    const t = await wav(`${run.dir}/${typeof file === "string" ? file : `ir_${tier}.wav`}`);
    data = await to16k(t); if (t.fs !== FS) data = data.map((v) => v * t.fs / FS); // IR taps scale with 1/fs
    const t0 = irm.t0_s ?? 0; if (t0 > 0) { const pad = new Float32Array(Math.round(t0 * FS) + data.length); pad.set(data, Math.round(t0 * FS)); data = pad; }
    origin = "file"; note = `impulse response ir_${tier}.wav from the run${irm.band_hz ? `, band ${irm.band_hz[0]}–${irm.band_hz[1]} Hz` : ""}`;
  } else {
    if (irm && !file) throw new Error(`This run has no ${tier === "tier1" ? "Tier 1" : "Tier 0"} impulse response`);
    const clap = await runClap(run), echoT = run.audio[tier];
    if (!clap || !echoT) throw new Error(`This run has no ${tier === "tier1" ? "Tier 1 echo" : "echo"} or no as_heard.wav to derive a response from`);
    const echo = await to16k(echoT);
    // stored echo is peak-normalized: scale to the as-heard echo (direct clap peak = 1)
    const ah = clap.echoTail.slice(); ah.fill(0, 0, clap.end);
    const ahPk = peakOf(ah) / clap.peak, lvl = m.audio?.as_heard_echo_level_db;
    const scale = (lvl != null ? 10 ** (lvl / 20) : ahPk) / (peakOf(echo) || 1);
    const band = [Math.max(300, m.solver?.f_lo ?? 300), Math.min(4000, m.solver?.f_max ?? 4000)];
    data = deconvolve(echo.map((v) => v * scale), clap.data, FS, band, 3e-3);
    origin = "derived"; note = `derived in the browser: stored echo ÷ stored clap (regularized, ${band[0]}–${band[1]} Hz); this run has no ir_${tier}.wav yet`;
  }
  // leading silence: geometry, never past the data's own onset (1 % of peak)
  const pk = peakOf(data); let on = 0; while (on < data.length && Math.abs(data[on]) < 0.01 * pk) on++;
  const lead = Math.max(0, Math.min(geo, on / FS));
  // true level: the run's clap through this IR, re the clap (direct)
  let levelDb = m.audio?.as_heard_echo_level_db ?? null;
  if (origin === "file" || levelDb == null) { const clap = await runClap(run).catch(() => null);
    if (clap) levelDb = 20 * Math.log10(peakOf(convolve(clap.data, data)) + 1e-12); }
  return { data, fs: FS, lead, tDirect, key: `${run.dir}|${tier}|${origin}`, origin, levelDb, note, tier };
}
