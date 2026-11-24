// The single clock. Simulation time t (seconds, 0 = clap emission) advances at `speed`
// sim-seconds per wall-second. While playing, t is derived from AudioContext.currentTime, the
// same clock that drives the audio buffer, so picture and sound cannot drift apart.
// Audio uses AudioBufferSourceNode.playbackRate = speed: slowing down lowers the pitch.

export class Clock {
  constructor() {
    this.t = 0; this.duration = 0.1; this.speed = 0.1; this.playing = false; this.muted = false;
    this.track = null; // {fs, data}
    this.ctx = null; this.src = null; this.gain = null; this.listeners = new Set();
    this._raf = 0; this._t0 = 0; this._c0 = 0; this._useCtx = false;
  }
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit() { for (const fn of this.listeners) fn(this); }

  // Audio clock when the AudioContext runs; wall clock otherwise (no output device, autoplay
  // blocked). Chosen at each (re)start so a clock switch never jumps t.
  now() { return this._useCtx ? this.ctx.currentTime : performance.now() / 1000; }
  setDuration(d) { this.duration = Math.max(1e-3, d); if (this.t > this.duration) this.seek(this.duration); }
  setTrack(track) { if (this.playing) this.t = this._current(); this.track = track; if (this.playing) this._restart(); }
  setSpeed(s) { if (this.playing) this.t = this._current(); this.speed = s; if (this.playing) this._restart(); else this.emit(); }
  setMuted(m) { this.muted = m; if (this.gain) this.gain.gain.value = m ? 0 : 1; this.emit(); }

  seek(t) {
    this.t = Math.min(this.duration, Math.max(0, t));
    if (this.playing) this._restart(); else this.emit();
  }
  toggle() { this.playing ? this.pause() : this.play(); }
  play() {
    if (this.t >= this.duration - 1e-6) this.t = 0;
    this._ensureCtx(); this.playing = true; this._restart(); this._tick();
  }
  pause() {
    if (!this.playing) return;
    this.t = this._current(); this.playing = false; this._stopSrc(); cancelAnimationFrame(this._raf); this.emit();
  }

  _ensureCtx() {
    if (this.ctx) { if (this.ctx.state === "suspended") this.ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    this.ctx = new AC();
    this.ctx.onstatechange = () => { if (this.playing && this._useCtx !== (this.ctx.state === "running")) { this.t = this._current(); this._restart(); } };
    this.gain = this.ctx.createGain(); this.gain.gain.value = this.muted ? 0 : 1; this.gain.connect(this.ctx.destination);
  }
  _current() { return Math.min(this.duration, this._t0 + (this.now() - this._c0) * this.speed); }
  _stopSrc() { if (this.src) { try { this.src.stop(); } catch { /* already stopped */ } this.src.disconnect(); this.src = null; } }
  _restart() {
    this._stopSrc();
    this._useCtx = !!this.ctx && this.ctx.state === "running";
    this._t0 = this.t; this._c0 = this.now();
    if (this.ctx && this.track && this.t < this.track.data.length / this.track.fs) {
      const { fs, data } = this.track, buf = this.ctx.createBuffer(1, data.length, fs);
      buf.copyToChannel(data, 0);
      const src = this.ctx.createBufferSource(); src.buffer = buf; src.playbackRate.value = this.speed;
      src.connect(this.gain); src.start(0, this.t); this.src = src;
    }
    this.emit();
  }
  _tick() {
    cancelAnimationFrame(this._raf);
    const step = () => {
      if (!this.playing) return;
      this.t = this._current();
      if (this.t >= this.duration) { this.t = this.duration; this.playing = false; this._stopSrc(); this.emit(); return; }
      this.emit(); this._raf = requestAnimationFrame(step);
    };
    this._raf = requestAnimationFrame(step);
  }
}
