// Shared helpers: formatting, canvas sizing, colours read from CSS tokens.

export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function colors() {
  return {
    ink: css("--ink"), panel: css("--panel"), line: css("--line"), grid: css("--grid"),
    text: css("--text"), dim: css("--dim"), faint: css("--faint"),
    accent: css("--accent"), cool: css("--cool"), pass: css("--pass"), fail: css("--fail"),
  };
}

// Canvas that tracks its CSS box and device pixel ratio. draw(ctx, w, h) is called in CSS pixels.
export class AutoCanvas {
  constructor(canvas, draw) {
    this.canvas = canvas; this.ctx = canvas.getContext("2d"); this.draw = draw;
    this.w = 0; this.h = 0; this.dpr = 1; this.pending = false;
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(canvas);
  }
  resize() {
    const r = this.canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
    if (w === this.w && h === this.h && dpr === this.dpr) return;
    this.w = w; this.h = h; this.dpr = dpr;
    this.canvas.width = Math.round(w * dpr); this.canvas.height = Math.round(h * dpr);
    this.onResize?.(); this.render();
  }
  request() { if (this.pending) return; this.pending = true; requestAnimationFrame(() => { this.pending = false; this.render(); }); }
  render() {
    if (!this.w) { this.resize(); if (!this.w) return; }
    const { ctx } = this; ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0); ctx.clearRect(0, 0, this.w, this.h);
    this.draw(ctx, this.w, this.h);
  }
  destroy() { this.ro.disconnect(); }
}

export function niceStep(span, target) { // step near span/target from 1-2-5 series
  const raw = span / Math.max(1, target), p = 10 ** Math.floor(Math.log10(raw)), m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}
export function ticks(lo, hi, step) { const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10)); return out; }

const MINUS = "−";
export function num(v, d = 1) {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  return (v < 0 && +s.replace(/,/g, "") !== 0 ? MINUS : "") + s;
}
export const ms = (t, d = 2) => `${num(t * 1000, d)} ms`;
export const metres = (m, d = 2) => `${num(m, d)} m`;
export function fmtRadius(r) { return r >= 0.01 ? `${num(r * 100, 0)} cm` : `${num(r * 1000, 0)} mm`; }

export function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else if (v != null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k instanceof Node ? k : document.createTextNode(k));
  return e;
}

// min/max envelope of samples over [t0, t1) for `cols` columns
export function envelope(data, fs, t0, t1, cols) {
  const mn = new Float32Array(cols), mx = new Float32Array(cols);
  for (let c = 0; c < cols; c++) {
    let a = Math.floor((t0 + (t1 - t0) * c / cols) * fs), b = Math.floor((t0 + (t1 - t0) * (c + 1) / cols) * fs);
    a = Math.max(0, a); b = Math.min(data.length, Math.max(b, a + 1));
    let lo = 0, hi = 0; for (let i = a; i < b; i++) { const v = data[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
    mn[c] = lo; mx[c] = hi;
  }
  return { mn, mx };
}
