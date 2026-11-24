// Loading run folders (data contract: .superpowers/sdd/plan/global-constraints.md).
// Every optional piece resolves to null instead of throwing, so partial runs still render.

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}
const maybe = (p) => p.catch(() => null);

// Minimal WAV reader: PCM 16/24/32-bit and IEEE float 32/64, first channel only.
export function parseWav(buf) {
  const dv = new DataView(buf);
  const tag = (o) => String.fromCharCode(dv.getUint8(o), dv.getUint8(o + 1), dv.getUint8(o + 2), dv.getUint8(o + 3));
  if (tag(0) !== "RIFF" || tag(8) !== "WAVE") throw new Error("not a WAV file");
  let o = 12, fmt = null, data = null;
  while (o + 8 <= dv.byteLength) {
    const id = tag(o), size = dv.getUint32(o + 4, true), body = o + 8;
    if (id === "fmt ") {
      let format = dv.getUint16(body, true);
      if (format === 0xfffe && size >= 26) format = dv.getUint16(body + 24, true); // WAVE_FORMAT_EXTENSIBLE
      fmt = { format, ch: dv.getUint16(body + 2, true), fs: dv.getUint32(body + 4, true), bits: dv.getUint16(body + 14, true) };
    } else if (id === "data") data = { off: body, size: Math.min(size, dv.byteLength - body) };
    o = body + size + (size & 1);
  }
  if (!fmt || !data) throw new Error("WAV missing fmt or data chunk");
  const bps = fmt.bits / 8, n = Math.floor(data.size / (bps * fmt.ch)), out = new Float32Array(n), step = bps * fmt.ch;
  for (let i = 0, p = data.off; i < n; i++, p += step) {
    if (fmt.format === 3) out[i] = fmt.bits === 64 ? dv.getFloat64(p, true) : dv.getFloat32(p, true);
    else if (fmt.bits === 16) out[i] = dv.getInt16(p, true) / 32768;
    else if (fmt.bits === 24) { const v = dv.getUint8(p) | (dv.getUint8(p + 1) << 8) | (dv.getInt8(p + 2) << 16); out[i] = v / 8388608; }
    else if (fmt.bits === 32) out[i] = dv.getInt32(p, true) / 2147483648;
    else if (fmt.bits === 8) out[i] = (dv.getUint8(p) - 128) / 128;
  }
  return { fs: fmt.fs, data: out };
}
async function getWav(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return parseWav(await r.arrayBuffer());
}

// Returns {base, runs, fallback} where base is the folder that holds index.json.
export async function loadIndex(requested) {
  const tryBase = async (base) => { const idx = await getJSON(`${base}/index.json`); return Array.isArray(idx?.runs) && idx.runs.length ? idx.runs : null; };
  let runs = await tryBase(requested).catch(() => null);
  if (runs) return { base: requested, runs, fallback: false };
  if (requested !== "fixtures/runs") {
    runs = await tryBase("fixtures/runs").catch(() => null);
    if (runs) return { base: "fixtures/runs", runs, fallback: true, requested };
  }
  return { base: requested, runs: [], fallback: false };
}

export async function loadRun(base, entry) {
  const dir = `${base}/${entry.path}`;
  const manifest = await getJSON(`${dir}/manifest.json`);
  const [scene, profile, metrics, history, spectro, target, tier0, tier1, asHeard] = await Promise.all([
    maybe(getJSON(`${dir}/scene.json`)), maybe(getJSON(`${dir}/profile.json`)), maybe(getJSON(`${dir}/metrics.json`)),
    maybe(getJSON(`${dir}/history.json`)), maybe(getJSON(`${dir}/spectrograms.json`)),
    maybe(getWav(`${dir}/target.wav`)), maybe(getWav(`${dir}/echo_tier0.wav`)),
    manifest.solver?.tier1 && manifest.solver.tier1 !== "none" ? maybe(getWav(`${dir}/echo_tier1.wav`)) : Promise.resolve(null),
    maybe(getWav(`${dir}/as_heard.wav`)),
  ]);
  const fieldUrl = manifest.field?.file ? `${dir}/${manifest.field.file}` : null;
  return { entry, dir, manifest, scene, profile, metrics, history, spectro, audio: { target, tier0, tier1, asHeard }, fieldUrl,
    c: manifest.c ?? scene?.c ?? 343, duration: manifest.duration_s ?? (target ? target.data.length / target.fs : 0.1) };
}

// A saved iteration: iters/<name>/{scene.json, profile.json, echo.wav, metrics.json}
export async function loadIteration(run, dir) {
  const rel = dir.startsWith("iters/") ? dir : `iters/${dir}`, d = `${run.dir}/${rel}`;
  const [scene, profile, metrics, echo] = await Promise.all([maybe(getJSON(`${d}/scene.json`)), maybe(getJSON(`${d}/profile.json`)),
    maybe(getJSON(`${d}/metrics.json`)), maybe(getWav(`${d}/echo.wav`))]);
  return { scene, profile, metrics, echo };
}
