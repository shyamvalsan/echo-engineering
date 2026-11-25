// Groove (target waveform over the reflectivity profile) and Echo (listener waveform drawing
// itself). Both share one time window, so a delay sits at the same x in both. Echo time t and
// bistatic range rho are the same axis: rho = c t / 2 (17.15 cm per ms).
import { AutoCanvas, colors, el, envelope, niceStep, ticks, num } from "./util.js";

// Shared x window, zoomable with the wheel over either panel; double-click resets.
export class TimeWindow {
  constructor() { this.t0 = 0; this.t1 = 0.1; this.full = [0, 0.1]; this.subs = new Set(); }
  reset(full) { if (full) this.full = full; [this.t0, this.t1] = this.full; this.emit(); }
  zoom(at, k) {
    const span = Math.min(this.full[1] - this.full[0], Math.max(0.002, (this.t1 - this.t0) * k));
    let a = at - (at - this.t0) * span / (this.t1 - this.t0); a = Math.max(this.full[0], Math.min(this.full[1] - span, a));
    this.t0 = a; this.t1 = a + span; this.emit();
  }
  pan(dt) { const span = this.t1 - this.t0; let a = Math.max(this.full[0], Math.min(this.full[1] - span, this.t0 + dt)); this.t0 = a; this.t1 = a + span; this.emit(); }
  x(t, w) { return (t - this.t0) / (this.t1 - this.t0) * w; }
  t(x, w) { return this.t0 + x / w * (this.t1 - this.t0); }
  on(fn) { this.subs.add(fn); }
  emit() { for (const f of this.subs) f(); }
}

export class TimePanel {
  constructor(host, cls, title, sub, win, clock) {
    this.win = win; this.clock = clock; this.t = 0; this.marker = null;
    this.root = el("section", { class: `panel ${cls}` });
    this.subEl = el("span", { class: "sub" }, sub);
    this.tools = el("div", { class: "tools" });
    this.root.append(el("header", {}, el("h2", {}, title), this.subEl, this.tools));
    this.canvas = el("canvas"); this.root.append(el("div", { class: "stage" }, this.canvas)); host.append(this.root);
    this.ac = new AutoCanvas(this.canvas, (ctx, w, h) => { if (this.run) this.draw(ctx, w, h, colors()); });
    win.on(() => this.ac.request());
    const c = this.canvas; let drag = null;
    c.addEventListener("wheel", (e) => { e.preventDefault(); const r = c.getBoundingClientRect();
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) win.pan(e.deltaX / r.width * (win.t1 - win.t0));
      else win.zoom(win.t(e.clientX - r.left, r.width), Math.exp(e.deltaY * 0.0015)); }, { passive: false });
    c.addEventListener("dblclick", () => win.reset());
    // click or drag scrubs the shared clock
    c.addEventListener("pointerdown", (e) => { drag = true; c.setPointerCapture(e.pointerId); this._scrub(e); });
    c.addEventListener("pointermove", (e) => { if (drag) this._scrub(e); });
    c.addEventListener("pointerup", () => { drag = false; });
  }
  _scrub(e) { const r = this.canvas.getBoundingClientRect(); this.clock.seek(this.win.t(e.clientX - r.left, r.width)); }
  setTime(t) { this.t = t; this.ac.request(); }
  setMarker(m) { this.marker = m; this.ac.request(); }

  // cursor (accent) and hover marker (dashed), common to both panels
  drawCursorAndMarker(ctx, w, h, C, top = 0) {
    const x = this.win.x(this.t, w);
    if (x >= 0 && x <= w) { ctx.fillStyle = C.accent; ctx.fillRect(Math.round(x) - 1, top, 2, h - top); }
    if (this.marker) { const mx = this.win.x(this.marker.delay, w); if (mx < 0 || mx > w) return;
      ctx.save(); ctx.setLineDash([3, 3]); ctx.strokeStyle = C.accent; ctx.globalAlpha = 0.9; ctx.beginPath(); ctx.moveTo(Math.round(mx) + 0.5, top); ctx.lineTo(Math.round(mx) + 0.5, h); ctx.stroke(); ctx.restore(); }
  }
  markerLabel(ctx, w, y, C) {
    if (!this.marker) return; const mx = this.win.x(this.marker.delay, w); if (mx < 0 || mx > w) return;
    const s = `${num(this.marker.delay * 1000, 2)} ms, ${num(this.marker.rho, 2)} m`;
    ctx.font = `500 11px ${getComputedStyle(document.body).fontFamily}`; const tw = ctx.measureText(s).width + 10;
    const lx = Math.min(w - tw, Math.max(0, mx - tw / 2));
    ctx.fillStyle = C.ink; ctx.fillRect(lx, y, tw, 16); ctx.fillStyle = C.accent; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(s, lx + 5, y + 8);
  }
}

export class GroovePanel extends TimePanel {
  constructor(host, win, clock) { super(host, "groove", "Groove", "the layout is the waveform: target above, post density below", win, clock); }
  setRun(run, profile = run.profile, note = null) {
    this.run = run; this.profile = profile; this.c = run.c;
    this.subEl.textContent = note ? `target above, reflectivity profile below, ${note}` : "the layout is the waveform: target above, reflectivity profile below";
    // slowly varying bias: running mean over ~2 ms of echo (one period at 500 Hz)
    const p = profile?.reflectivity ?? [], half = Math.max(1, Math.round((0.002 * this.c / 2) / (profile?.dr_m ?? 0.01) / 2));
    const cs = new Float64Array(p.length + 1); for (let i = 0; i < p.length; i++) cs[i + 1] = cs[i] + p[i];
    this.bias = Float32Array.from(p, (_, i) => { const a = Math.max(0, i - half), b = Math.min(p.length, i + half + 1); return (cs[b] - cs[a]) / (b - a); });
    this.pmax = p.reduce((m, v) => Math.max(m, v), 1e-9);
    this.ac.request();
  }
  draw(ctx, w, h, C) {
    const font = getComputedStyle(document.body).fontFamily, win = this.win, c = this.c, axisH = 16;
    const top = axisH, bottom = h - axisH, mid = top + (bottom - top) * 0.44, gap = 6;
    const tA = [top + 4, mid - gap], pA = [mid + gap, bottom - 2];
    ctx.font = `11px ${font}`;
    // grid + axes: ms along the top, metres of range along the bottom; same positions
    const span = win.t1 - win.t0, step = niceStep(span * 1000, Math.max(3, w / 90)) / 1000;
    ctx.strokeStyle = C.grid; ctx.lineWidth = 1; ctx.fillStyle = C.dim; ctx.textBaseline = "middle"; ctx.textAlign = "center";
    for (const t of ticks(win.t0, win.t1, step)) { const x = Math.round(win.x(t, w)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
      ctx.fillStyle = C.dim; ctx.fillText(`${num(t * 1000, step * 1000 < 1 ? 1 : 0)}`, x, axisH / 2);
      ctx.fillStyle = C.faint; ctx.fillText(`${num(c * t / 2, step * c / 2 < 0.1 ? 2 : 1)}`, x, h - axisH / 2); }
    ctx.textAlign = "left"; ctx.fillStyle = C.dim; ctx.fillRect(0, 0, 0, 0);
    ctx.fillStyle = C.ink; ctx.fillRect(0, 0, 26, axisH); ctx.fillRect(0, h - axisH, 20, axisH);
    ctx.fillStyle = C.dim; ctx.fillText("ms", 2, axisH / 2); ctx.fillStyle = C.faint; ctx.fillText("m", 2, h - axisH / 2);
    // target waveform
    const tg = this.run.audio.target;
    if (tg) { const { mn, mx } = envelope(tg.data, tg.fs, win.t0, win.t1, Math.max(1, Math.floor(w)));
      let pk = 1e-9; for (let i = 0; i < tg.data.length; i++) pk = Math.max(pk, Math.abs(tg.data[i]));
      const cy = (tA[0] + tA[1]) / 2, a = (tA[1] - tA[0]) / 2 / pk;
      ctx.fillStyle = C.text; ctx.globalAlpha = 0.9;
      for (let i = 0; i < mn.length; i++) { const y0 = cy - mx[i] * a, y1 = cy - mn[i] * a; ctx.fillRect(i, y0, 1, Math.max(1, y1 - y0)); }
      ctx.globalAlpha = 1; }
    // reflectivity profile: bias floor dim, signal on top, bias line dashed
    const P = this.profile;
    if (P?.reflectivity?.length) {
      const r = P.reflectivity, n = r.length, base = pA[1], ah = (pA[1] - pA[0]) / this.pmax;
      const idx = (t) => (c * t / 2 - P.r0_m) / P.dr_m;
      for (let x = 0; x < w; x++) {
        let a = Math.floor(idx(win.t(x, w))), b = Math.floor(idx(win.t(x + 1, w)));
        if (b < 0 || a >= n) continue; a = Math.max(0, a); b = Math.min(n - 1, Math.max(a, b));
        let lo = Infinity, hi = -Infinity; for (let i = a; i <= b; i++) { if (r[i] < lo) lo = r[i]; if (r[i] > hi) hi = r[i]; }
        ctx.fillStyle = C.cool; ctx.globalAlpha = 0.22; ctx.fillRect(x, base - lo * ah, 1, lo * ah);
        ctx.globalAlpha = 1; ctx.fillRect(x, base - hi * ah, 1, Math.max(1, (hi - lo) * ah));
      }
      ctx.strokeStyle = C.text; ctx.globalAlpha = 0.55; ctx.setLineDash([2, 3]); ctx.beginPath(); let started = false;
      for (let x = 0; x < w; x += 2) { const i = Math.round(idx(win.t(x, w))); if (i < 0 || i >= n) { started = false; continue; }
        const y = base - this.bias[i] * ah; if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y); }
      ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
      ctx.strokeStyle = C.line; ctx.beginPath(); ctx.moveTo(0, base + 0.5); ctx.lineTo(w, base + 0.5); ctx.stroke();
    }
    if (!tg && !P?.reflectivity?.length) { ctx.fillStyle = C.dim; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = `12px ${font}`;
      ctx.fillText("No target audio or reflectivity profile in this run", w / 2, mid); }
    // in-panel labels
    ctx.font = `11px ${font}`; ctx.textBaseline = "top"; ctx.textAlign = "left";
    const tag = (s, x, y, col) => { const tw = ctx.measureText(s).width; ctx.fillStyle = C.panel; ctx.globalAlpha = 0.85; ctx.fillRect(x - 3, y - 1, tw + 6, 14); ctx.globalAlpha = 1; ctx.fillStyle = col; ctx.fillText(s, x, y); };
    if ((tg || P?.reflectivity?.length) && tA[1] - tA[0] > 40) { tag("target waveform", 4, tA[0], C.dim); tag("reflectivity along range", 4, pA[0], C.dim); }
    if (P?.reflectivity?.length && pA[1] - pA[0] > 70) tag("dashed: slowly varying positive bias", 4, pA[0] + 14, C.faint);
    ctx.strokeStyle = C.line; ctx.beginPath(); ctx.moveTo(0, mid + 0.5); ctx.lineTo(w, mid + 0.5); ctx.stroke();
    this.drawCursorAndMarker(ctx, w, bottom, C, top);
    this.markerLabel(ctx, w, top + 2, C);
  }
}

export class EchoPanel extends TimePanel {
  constructor(host, win, clock, onTier) {
    super(host, "echo", "Echo", "at the listener", win, clock);
    this.tier = "tier1"; this.onTier = onTier;
    this.btns = { tier1: el("button", { class: "tool toggle", onclick: () => this.setTier("tier1") }, "Tier 1"),
      tier0: el("button", { class: "tool toggle", onclick: () => this.setTier("tier0") }, "Tier 0") };
    this.tools.append(this.btns.tier1, this.btns.tier0);
  }
  setRun(run, iterEcho = null, note = null) {
    this.run = run; this.iterEcho = iterEcho; this.c = run.c;
    const has1 = !!run.audio.tier1; this.btns.tier1.disabled = !has1 || !!iterEcho; this.btns.tier0.disabled = !!iterEcho;
    if (!has1) this.tier = "tier0";
    this.subEl.textContent = iterEcho ? `at the listener, ${note ?? "saved iteration"}` : "at the listener, drawn up to the cursor";
    this._syncBtns(); this.ac.request();
  }
  setTier(t) { if (t === "tier1" && !this.run?.audio.tier1) return; this.tier = t; this._syncBtns(); this.onTier?.(t); this.ac.request(); }
  _syncBtns() { for (const [k, b] of Object.entries(this.btns)) { const on = !this.iterEcho && k === this.tier; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); } }
  track() { return this.iterEcho ?? this.run?.audio[this.tier] ?? this.run?.audio.tier0; }
  draw(ctx, w, h, C) {
    const tr = this.track(), win = this.win, font = getComputedStyle(document.body).fontFamily;
    ctx.font = `11px ${font}`;
    const step = niceStep((win.t1 - win.t0) * 1000, Math.max(3, w / 90)) / 1000;
    ctx.strokeStyle = C.grid; for (const t of ticks(win.t0, win.t1, step)) { const x = Math.round(win.x(t, w)) + 0.5; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
    const cy = h / 2; ctx.strokeStyle = C.line; ctx.beginPath(); ctx.moveTo(0, cy + 0.5); ctx.lineTo(w, cy + 0.5); ctx.stroke();
    // direct arrival tick
    const td = this.run.manifest.t_direct_s; if (td != null) { const x = win.x(td, w); if (x >= 0 && x <= w) {
      ctx.fillStyle = C.faint; ctx.fillRect(Math.round(x), 4, 1, h - 8); ctx.textBaseline = "top"; ctx.textAlign = "left"; ctx.fillText("direct", x + 4, 4); } }
    if (!tr) { ctx.fillStyle = C.dim; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("No echo audio in this run", w / 2, cy); return; }
    const cols = Math.max(1, Math.floor(w)), { mn, mx } = envelope(tr.data, tr.fs, win.t0, win.t1, cols);
    let pk = 1e-9; for (let i = 0; i < tr.data.length; i++) pk = Math.max(pk, Math.abs(tr.data[i]));
    const a = (h / 2 - 6) / pk, xc = win.x(this.t, w);
    for (let i = 0; i < cols; i++) { const y0 = cy - mx[i] * a, y1 = cy - mn[i] * a;
      const drawn = i <= xc; ctx.fillStyle = drawn ? C.accent : C.faint; ctx.globalAlpha = drawn ? 1 : 0.35;
      ctx.fillRect(i, y0, 1, Math.max(1, y1 - y0)); }
    ctx.globalAlpha = 1;
    this.drawCursorAndMarker(ctx, w, h, C, 0);
    ctx.textAlign = "right"; ctx.textBaseline = "top"; ctx.fillStyle = C.dim;
    ctx.fillText(this.iterEcho ? "iteration echo" : this.tier === "tier1" ? "Tier 1 full-wave" : "Tier 0 single scattering", w - 6, 4);
    this.markerLabel(ctx, w, h - 18, C);
  }
}
