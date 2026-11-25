// Signal helpers for Live mode: FFT, band-limited deconvolution (IR fallback), resampling and
// offline convolution through OfflineAudioContext, a small STFT in the spectrograms.json format,
// and a WAV writer. Everything works on {fs, data: Float32Array} tracks, t = 0 = emission.

export const FS = 16000;

// in-place radix-2 complex FFT (n a power of two); inverse when inv
export function fft(re, im, inv = false) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) { let b = n >> 1; for (; j & b; b >>= 1) j ^= b; j ^= b;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; } }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (inv ? 2 : -2) * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) { let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) { const a = i + k, b = a + len / 2;
        const xr = re[b] * cr - im[b] * ci, xi = re[b] * ci + im[b] * cr;
        re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi;
        const t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t; } }
  }
  if (inv) for (let i = 0; i < n; i++) { re[i] /= n; im[i] /= n; }
}
const pow2 = (n) => 2 ** Math.ceil(Math.log2(Math.max(2, n)));
export const peakOf = (d) => { let p = 0; for (let i = 0; i < d.length; i++) p = Math.max(p, Math.abs(d[i])); return p; };

// Regularized deconvolution ir = echo / clap within [f_lo, f_hi] (raised-cosine edges), zero outside.
// lambda is relative to the clap's peak power in band. Returns Float32Array of echo.length.
export function deconvolve(echo, clap, fs, band = [300, 4000], lambda = 1e-2) {
  const n = pow2(echo.length + clap.length);
  const er = new Float64Array(n), ei = new Float64Array(n), cr = new Float64Array(n), ci = new Float64Array(n);
  er.set(echo); cr.set(clap); fft(er, ei); fft(cr, ci);
  let pmax = 0; const kb = (f) => Math.round(f / fs * n);
  for (let k = kb(band[0]); k <= kb(band[1]); k++) pmax = Math.max(pmax, cr[k] ** 2 + ci[k] ** 2);
  const reg = lambda * pmax, edge = 150;
  for (let k = 0; k <= n / 2; k++) {
    const f = k * fs / n;
    let w = f < band[0] - edge || f > band[1] + edge ? 0 : f < band[0] ? 0.5 - 0.5 * Math.cos(Math.PI * (f - band[0] + edge) / edge)
      : f > band[1] ? 0.5 + 0.5 * Math.cos(Math.PI * (f - band[1]) / edge) : 1;
    const den = cr[k] ** 2 + ci[k] ** 2 + reg;
    const hr = w * (er[k] * cr[k] + ei[k] * ci[k]) / den, hi = w * (ei[k] * cr[k] - er[k] * ci[k]) / den;
    er[k] = hr; ei[k] = hi; if (k > 0 && k < n / 2) { er[n - k] = hr; ei[n - k] = -hi; }
  }
  fft(er, ei, true);
  return Float32Array.from(er.subarray(0, echo.length));
}

// direct linear convolution in the frequency domain (both at one rate)
export function convolve(a, b) {
  const n = pow2(a.length + b.length), ar = new Float64Array(n), ai = new Float64Array(n), br = new Float64Array(n), bi = new Float64Array(n);
  ar.set(a); br.set(b); fft(ar, ai); fft(br, bi);
  for (let k = 0; k < n; k++) { const r = ar[k] * br[k] - ai[k] * bi[k]; ai[k] = ar[k] * bi[k] + ai[k] * br[k]; ar[k] = r; }
  fft(ar, ai, true);
  return Float32Array.from(ar.subarray(0, a.length + b.length - 1));
}

// resample a mono Float32Array with the browser's own resampler (OfflineAudioContext)
export async function resample(data, fsIn, fsOut) {
  if (fsIn === fsOut) return Float32Array.from(data);
  const len = Math.max(1, Math.ceil(data.length * fsOut / fsIn));
  const oc = new OfflineAudioContext(1, len, fsOut), buf = oc.createBuffer(1, data.length, fsIn);
  buf.copyToChannel(data, 0);
  const src = oc.createBufferSource(); src.buffer = buf; src.connect(oc.destination); src.start();
  return (await oc.startRendering()).getChannelData(0).slice();
}

// source ⊛ ir through a ConvolverNode (normalize = false) in an OfflineAudioContext, both at fs
export async function convolveOffline(source, ir, fs = FS) {
  const len = source.length + ir.length;
  const oc = new OfflineAudioContext(1, len, fs);
  const sb = oc.createBuffer(1, source.length, fs); sb.copyToChannel(source, 0);
  const ib = oc.createBuffer(1, ir.length, fs); ib.copyToChannel(ir, 0);
  const conv = oc.createConvolver(); conv.normalize = false; conv.buffer = ib;
  const src = oc.createBufferSource(); src.buffer = sb; src.connect(conv); conv.connect(oc.destination); src.start();
  return (await oc.startRendering()).getChannelData(0).slice();
}

// first sample whose magnitude exceeds rel × peak
export function onsetIndex(d, rel = 0.05) { const th = peakOf(d) * rel; for (let i = 0; i < d.length; i++) if (Math.abs(d[i]) >= th) return i; return 0; }

// STFT in the spectrograms.json shape: dB re own max, [F][T], 0..fmax, floor -60
export function spectrogram(data, fs, { tEnd = data.length / fs, nfft = 512, hop = 0.002, fmax = 5000, floor = -60 } = {}) {
  const win = new Float64Array(nfft).map((_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (nfft - 1)));
  const T = Math.max(1, Math.floor(tEnd / hop)), kmax = Math.floor(fmax / fs * nfft), out = Array.from({ length: kmax + 1 }, () => new Float32Array(T));
  const re = new Float64Array(nfft), im = new Float64Array(nfft); let mx = -Infinity;
  const times = []; for (let t = 0; t < T; t++) {
    const c = Math.round((t + 0.5) * hop * fs); re.fill(0); im.fill(0);
    for (let i = 0; i < nfft; i++) { const j = c - nfft / 2 + i; re[i] = j >= 0 && j < data.length ? data[j] * win[i] : 0; }
    fft(re, im);
    for (let k = 0; k <= kmax; k++) { const v = 10 * Math.log10(re[k] ** 2 + im[k] ** 2 + 1e-20); out[k][t] = v; if (v > mx) mx = v; }
    times.push((t + 0.5) * hop);
  }
  for (const row of out) for (let t = 0; t < T; t++) row[t] = Math.max(floor, row[t] - mx);
  return { fs, freqs_hz: out.map((_, k) => k * fs / nfft), times_s: times, db_floor: floor, panel: out };
}

// 32-bit float mono WAV
export function wavBlob(data, fs) {
  const n = data.length, buf = new ArrayBuffer(44 + n * 4), dv = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); dv.setUint32(4, 36 + n * 4, true); str(8, "WAVE"); str(12, "fmt "); dv.setUint32(16, 16, true);
  dv.setUint16(20, 3, true); dv.setUint16(22, 1, true); dv.setUint32(24, fs, true); dv.setUint32(28, fs * 4, true);
  dv.setUint16(32, 4, true); dv.setUint16(34, 32, true); str(36, "data"); dv.setUint32(40, n * 4, true);
  for (let i = 0; i < n; i++) dv.setFloat32(44 + i * 4, data[i], true);
  return new Blob([buf], { type: "audio/wav" });
}

// built-in sources at FS: a click, a chirp
export function makeClick() { const d = new Float32Array(Math.round(0.003 * FS)); for (let i = 0; i < d.length; i++) d[i] = Math.exp(-i / 6) * (i % 2 ? -1 : 1) * (i < 4 ? 1 : 0.6); return d; }
export function makeChirp(dur = 0.05, f0 = 500, f1 = 4000) {
  const n = Math.round(dur * FS), d = new Float32Array(n), k = (f1 - f0) / dur;
  for (let i = 0; i < n; i++) { const t = i / FS, w = Math.sin(Math.PI * i / (n - 1)) ** 2; d[i] = 0.9 * w * Math.sin(2 * Math.PI * (f0 * t + k * t * t / 2)); }
  return d;
}
