// Live echo engine: microphone -> tap (meter, clap detection, takes) and -> convolver (the selected
// structure's impulse response, normalize = false) -> echo gain -> limiter -> speakers.
// The real sound is heard directly in the room; the speaker adds only the echo. With "headphones"
// on, the dry mic is mixed in too, because the room sound is then blocked.
import { resample } from "./dsp.js";

const dbToGain = (db) => 10 ** (db / 20);
const KNEE = 0.708; // -3 dBFS
function softClipCurve(n = 4097) {
  const c = new Float32Array(n), room = 1 - KNEE;
  for (let i = 0; i < n; i++) { const x = (i / (n - 1)) * 2 - 1, a = Math.abs(x); // the curve spans inputs -1..1; beyond that it holds its end value
    c[i] = Math.sign(x) * (a <= KNEE ? a : KNEE + room * Math.tanh((a - KNEE) / room)); }
  return c;
}
export const gainToDb = (g) => 20 * Math.log10(Math.max(g, 1e-12));

export class LiveEngine {
  constructor({ onLevel, onClap, onTake, onDuck, onState }) {
    Object.assign(this, { onLevel, onClap, onTake, onDuck, onState });
    this.ctx = null; this.stream = null; this.running = false;
    this.boostDb = 0; this.dryDb = -6; this.headphones = false; this.ir = null; this.trimS = 0;
    this.lastClap = 0; this.ducked = false; this.hot = 0;
  }

  // Must be called from a user gesture. Throws an Error with a user-facing .userMessage on failure.
  async start({ rate = null } = {}) {
    if (this.running) return;
    if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error("no getUserMedia"), { userMessage: "This browser gives no microphone access here. Open the viewer over http://localhost (not a file:// page) in current Chrome or Firefox." });
    const AC = window.AudioContext || window.webkitAudioContext;
    // create (and resume) the context inside the gesture, before awaiting the permission prompt
    this.ctx = rate ? new AC({ sampleRate: rate, latencyHint: "interactive" }) : new AC({ latencyHint: "interactive" });
    if (this.ctx.state === "suspended") this.ctx.resume();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    } catch (e) {
      await this.ctx.close(); this.ctx = null;
      const msg = e.name === "NotAllowedError" || e.name === "SecurityError"
        ? "Microphone blocked. Allow the microphone for this page (the icon at the left of the address bar), then press Start listening again. You can still use sound files below."
        : e.name === "NotFoundError" || e.name === "OverconstrainedError" ? "No microphone found. Plug one in and press Start listening again, or use a sound file below."
        : e.name === "NotSupportedError" ? "This browser offers no microphone here (none found, or audio capture is not supported). Use a sound file below, or try current Chrome or Firefox."
        : e.name === "NotReadableError" ? "The microphone is in use by another program or could not be opened. Close it there and try again."
        : `The microphone could not be opened (${e.name}: ${e.message}).`;
      throw Object.assign(e, { userMessage: msg });
    }
    const ctx = this.ctx;
    await ctx.audioWorklet.addModule(new URL("./worklet.js", import.meta.url));
    this.src = ctx.createMediaStreamSource(this.stream);
    this.tap = new AudioWorkletNode(ctx, "live-tap", { numberOfInputs: 1, numberOfOutputs: 0 });
    this.tap.port.onmessage = (e) => this._msg(e.data);
    this.conv = ctx.createConvolver(); this.conv.normalize = false;
    this.echoGain = ctx.createGain();
    this.dryGain = ctx.createGain();
    this.preAn = ctx.createAnalyser(); this.preAn.fftSize = 1024;
    // limiter: a soft clipper, exactly linear below KNEE (-3 dBFS) and saturating smoothly to 1.0 above.
    // Not a DynamicsCompressorNode: that one delays by 6 ms (look-ahead) and adds make-up gain, which
    // would move the echo in time and misstate its level.
    this.lim = ctx.createWaveShaper(); this.lim.curve = softClipCurve(); this.lim.oversample = "none";
    this.out = ctx.createGain(); this.outAn = ctx.createAnalyser(); this.outAn.fftSize = 1024;
    this.src.connect(this.tap); this.src.connect(this.conv); this.conv.connect(this.echoGain); this.echoGain.connect(this.preAn);
    this.src.connect(this.dryGain); this.dryGain.connect(this.preAn);
    this.preAn.connect(this.lim); this.lim.connect(this.out); this.out.connect(this.outAn); this.out.connect(ctx.destination);
    this.running = true; this._applyGains();
    if (this.ir) await this._loadConv();
    this._watch();
    this.onState?.();
  }

  stop() {
    this.running = false; cancelAnimationFrame(this._raf);
    for (const n of [this.src, this.tap, this.conv, this.echoGain, this.dryGain, this.preAn, this.lim, this.out, this.outAn]) try { n?.disconnect(); } catch { /* not connected */ }
    if (this.tap) this.tap.port.onmessage = null;
    this.stream?.getTracks().forEach((t) => t.stop()); this.stream = null;
    this.ctx?.close().catch(() => {}); this.ctx = null; this.convKey = null;
    this.onState?.();
  }

  // system latency estimate (seconds): input (track settings, when the browser reports it) + base + output
  latency() {
    if (!this.ctx) return null;
    const tr = this.stream?.getAudioTracks()[0], set = tr?.getSettings?.() ?? {};
    const parts = { base: this.ctx.baseLatency ?? 0, output: this.ctx.outputLatency ?? 0, input: typeof set.latency === "number" ? set.latency : 0 };
    return { ...parts, total: parts.base + parts.output + parts.input, known: { output: this.ctx.outputLatency != null && this.ctx.outputLatency > 0, input: typeof set.latency === "number" } };
  }

  // ir: {data (16 kHz Float32Array, sample 0 = emission), fs, lead (s of leading silence), tDirect}
  async setIR(ir) { this.ir = ir; if (this.running) await this._loadConv(); }
  // The mic hears the direct sound t_direct after emission, and the system adds `latency` on top.
  // Both are trimmed from the IR's leading silence, never more than the silence itself.
  async _loadConv() {
    const ir = this.ir, ctx = this.ctx; if (!ir || !ctx) return;
    const lat = this.latency()?.total ?? 0, want = ir.tDirect + lat, can = Math.max(0, ir.lead - 0.0005);
    this.trimS = Math.min(want, can); this.wantTrimS = want;
    const key = `${ir.key}|${Math.round(this.trimS * 1e5)}|${ctx.sampleRate}`; if (key === this.convKey) return;
    const cut = ir.data.subarray(Math.round(this.trimS * ir.fs));
    // an impulse response is a density per sample: resampling to a higher rate must scale it by fs_in/fs_out
    const data = await resample(cut, ir.fs, ctx.sampleRate), k = ir.fs / ctx.sampleRate;
    for (let i = 0; i < data.length; i++) data[i] *= k;
    if (!this.ctx) return;
    const buf = ctx.createBuffer(1, data.length, ctx.sampleRate); buf.copyToChannel(data, 0);
    this.conv.normalize = false; this.conv.buffer = buf; this.convKey = key;
  }

  setBoost(db) { this.boostDb = db; this.ducked = false; this._applyGains(); }
  setHeadphones(on, dryDb = this.dryDb) { this.headphones = on; this.dryDb = dryDb; this._applyGains(); }
  _applyGains() {
    if (!this.ctx) return; const t = this.ctx.currentTime;
    this.echoGain.gain.setTargetAtTime(dbToGain(this.boostDb - (this.ducked ? 18 : 0)), t, 0.02);
    this.dryGain.gain.setTargetAtTime(this.headphones ? dbToGain(this.dryDb) : 0, t, 0.02);
  }
  record(seconds = 2) { this.tap?.port.postMessage({ type: "record", seconds }); }
  setDetect(cfg) { this.tap?.port.postMessage({ type: "config", ...cfg }); }

  _msg(m) {
    if (m.type === "level") { this.inPeak = m.peak; this.onLevel?.({ inPeak: m.peak, inRms: m.rms }); }
    else if (m.type === "clap") { this.lastClap = performance.now(); this.onClap?.(m.peak); }
    else if (m.type === "take") this.onTake?.(m);
  }

  // output meter, clip indicator and runaway (feedback) guard
  _watch() {
    const buf = new Float32Array(1024), pre = new Float32Array(1024);
    const irLen = (this.ir?.data.length ?? 16000) / (this.ir?.fs ?? 16000);
    let hotSince = 0, prevRms = 0;
    const step = () => {
      if (!this.running) return;
      this.outAn.getFloatTimeDomainData(buf); this.preAn.getFloatTimeDomainData(pre);
      let pk = 0, sq = 0, ppk = 0; for (let i = 0; i < buf.length; i++) { pk = Math.max(pk, Math.abs(buf[i])); sq += buf[i] ** 2; ppk = Math.max(ppk, Math.abs(pre[i])); }
      const rms = Math.sqrt(sq / buf.length), now = performance.now();
      // runaway: output stays loud (> -30 dBFS rms) longer than the echo itself lasts plus 0.5 s since the
      // last detected clap, and is not falling. Echo from the speaker re-entering the mic sustains itself.
      const sinceClap = (now - this.lastClap) / 1000;
      if (!this.headphones && rms > 0.03 && sinceClap > irLen + 0.5 && rms >= prevRms * 0.9) { hotSince ||= now; }
      else if (rms < 0.02) hotSince = 0;
      if (hotSince && now - hotSince > 700 && !this.ducked) { this.ducked = true; this._applyGains(); this.onDuck?.(); hotSince = 0; }
      prevRms = 0.8 * prevRms + 0.2 * rms;
      this.onLevel?.({ outPeak: pk, outRms: rms, prePeak: ppk, limiting: ppk > KNEE });
      this._raf = requestAnimationFrame(step);
    };
    this._raf = requestAnimationFrame(step);
  }
}
