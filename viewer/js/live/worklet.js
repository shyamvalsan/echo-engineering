// AudioWorklet for Live mode: input level, clap (transient) detection and take capture.
// Keeps the last ~3 s of dry input in a ring so every take starts PRE seconds before its onset.
// Messages out: {type:"level", peak, rms}, {type:"clap", peak}, {type:"take", data, fs, onset, reason}.
// Messages in: {type:"record", seconds}, {type:"config", threshold, auto}.
class LiveTap extends AudioWorkletProcessor {
  constructor() {
    super();
    this.fs = sampleRate; this.ring = new Float32Array(Math.round(3 * this.fs)); this.w = 0; this.n = 0;
    this.slow = 1e-4; this.hold = 0; this.threshold = 0.08; this.auto = true;
    this.PRE = 0.02; this.capture = null; this.blockPeak = 0; this.blockSq = 0; this.blockN = 0;
    this.port.onmessage = (e) => {
      const m = e.data;
      if (m.type === "record" && !this.capture) this.capture = { left: Math.round(m.seconds * this.fs), onset: this._pre(), reason: "record" };
      if (m.type === "config") { if (m.threshold != null) this.threshold = m.threshold; if (m.auto != null) this.auto = m.auto; }
    };
  }
  _pre() { return Math.round(this.PRE * this.fs); }
  process(inputs) {
    const x = inputs[0]?.[0]; if (!x) return true;
    const ring = this.ring, R = ring.length;
    if (this.capture && !this.capture.buf) this._startFromRing(this._pre());
    for (let i = 0; i < x.length; i++) {
      const v = x[i], a = Math.abs(v);
      ring[this.w] = v; this.w = (this.w + 1) % R; this.n++;
      if (a > this.blockPeak) this.blockPeak = a; this.blockSq += v * v; this.blockN++;
      // transient: sample well above the slow envelope and above an absolute floor
      const isClap = this.auto && !this.capture && this.hold <= 0 && a > this.threshold && a > 8 * this.slow;
      this.slow += (a - this.slow) * (a > this.slow ? 0.0005 : 0.00005);
      if (this.hold > 0) this.hold--;
      if (isClap) { this.port.postMessage({ type: "clap", peak: a }); this.hold = Math.round(0.8 * this.fs);
        this.capture = { left: Math.round(0.6 * this.fs), onset: this._pre(), reason: "clap" }; this._startFromRing(this._pre() + 1); continue; }
      if (this.capture?.buf) { const c = this.capture; c.buf[c.i++] = v; if (--c.left <= 0 || c.i >= c.buf.length) this._finish(); }
    }
    if (this.blockN >= 1024) { this.port.postMessage({ type: "level", peak: this.blockPeak, rms: Math.sqrt(this.blockSq / this.blockN) }); this.blockPeak = 0; this.blockSq = 0; this.blockN = 0; }
    return true;
  }
  // begin a capture with the last k samples already in the ring
  _startFromRing(k) {
    const c = this.capture, R = this.ring.length; k = Math.min(k, this.n, R);
    c.buf = new Float32Array(k + c.left + 1); c.i = 0;
    for (let j = k; j > 0; j--) c.buf[c.i++] = this.ring[(this.w - j + R) % R];
  }
  _finish() {
    const c = this.capture; this.capture = null;
    const data = c.buf.subarray(0, c.i);
    this.port.postMessage({ type: "take", data, fs: this.fs, onset: c.onset, reason: c.reason }, [c.buf.buffer]);
  }
}
registerProcessor("live-tap", LiveTap);
