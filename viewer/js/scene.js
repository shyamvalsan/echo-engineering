// Scene + Wave panel: plan view to scale, the Tier 1 pressure video registered underneath,
// equal-delay range rings, posts, and the live wavefront. Zoom with the wheel, pan by dragging.
import { AutoCanvas, colors, el, niceStep, num, fmtRadius } from "./util.js";

const DEG = Math.PI / 180;
const MIN_POST_PX = 0.9;   // posts never vanish when zoomed out
const SEEK_EPS = 0.5;      // seek to the middle of a frame

export class ScenePanel {
  constructor(host, { onHover, compact = false } = {}) {
    this.onHover = onHover; this.compact = compact;
    this.layers = { field: true, rings: true };
    this.root = el("section", { class: "panel scene" + (compact ? " compact" : "") });
    this.fitBtn = el("button", { class: "tool", title: "Fit the whole structure (double-click also fits)", onclick: () => { this.fit(); } }, "Fit");
    this.fieldBtn = el("button", { class: "tool toggle on", "aria-pressed": "true", title: "Show the Tier 1 pressure field", onclick: () => this.toggle("field") }, "Field");
    this.ringBtn = el("button", { class: "tool toggle on", "aria-pressed": "true", title: "Show equal-delay range rings", onclick: () => this.toggle("rings") }, "Rings");
    this.title = el("span", { class: "sub" }, "plan view, to scale");
    // field gain: stretches the frame about its zero colour so faint scattering shows next to the direct front
    this.gain = 1;
    this.gainBtn = el("button", { class: "tool", title: "Field gain: amplify faint pressure (stretch about zero)", onclick: () => this.cycleGain() }, "Gain \u00d71");
    this.fitHBtn = el("button", { class: "tool", hidden: true, title: "Fill the height with the strip and follow the front along it", onclick: () => this.fitHeight() }, "Fit height");
    this.followBtn = el("button", { class: "tool toggle", "aria-pressed": "false", title: "Keep the outgoing front centred while zoomed in", onclick: () => this.toggleFollow() }, "Follow");
    this.root.append(el("header", {}, el("h2", {}, "Scene"), this.title, el("div", { class: "tools" }, this.fieldBtn, this.gainBtn, this.ringBtn, this.followBtn, this.fitHBtn, this.fitBtn)));
    this.stage = el("div", { class: "stage" });
    this.canvas = el("canvas", { "aria-label": "Plan view of the source, listener and posts" });
    this.tip = el("div", { class: "tip", hidden: true });
    this.readout = el("div", { class: "readout" });
    this.fieldNote = el("div", { class: "fieldnote" });
    this.stage.append(this.canvas, this.tip, this.readout, this.fieldNote);
    this.root.append(this.stage);
    host.append(this.root);

    this.video = el("video", { muted: true, playsinline: true, preload: "auto" }); this.video.muted = true;
    this.video.addEventListener("loadeddata", () => { this.videoReady = true; this._seekFor(this.t, true); this.ac.request(); });
    this.video.addEventListener("seeked", () => { if (this.native) return; this.shownFrame = this.seekingFrame; this.seekingFrame = null; this.ac.request();
      if (this.wantFrame != null && this.wantFrame !== this.shownFrame) this._seek(this.wantFrame); });

    this.t = 0; this.view = null; this.hover = null; this.mouse = null; this.staticDirty = true;
    this.off = document.createElement("canvas");
    this.ac = new AutoCanvas(this.canvas, (ctx, w, h) => this.draw(ctx, w, h));
    this.ac.onResize = () => { if (!this.userView) this.view = null; this.staticDirty = true; };
    this._bindPointer();
  }

  toggle(k) {
    this.layers[k] = !this.layers[k];
    const b = k === "field" ? this.fieldBtn : this.ringBtn; b.classList.toggle("on", this.layers[k]); b.setAttribute("aria-pressed", String(this.layers[k]));
    this.staticDirty = true; this.ac.request();
  }

  setRun(run, scene = run.scene, label = null) {
    const keepView = this.run === run && this.view;
    this.run = run; this.scene = scene; this.c = run.c;
    // posts confined to |y| <= max_half_width_m inside the wedge (long stages): draw and fit that strip
    const mhw = run.manifest?.design?.config?.max_half_width_m, wdg = scene?.wedge;
    this.strip = mhw && wdg && mhw < wdg.r_max * Math.sin(wdg.half_angle_deg * DEG) ? mhw : null;
    this.title.textContent = label ? `plan view, to scale, ${label}` : "plan view, to scale";
    const posts = scene?.posts ?? [], n = posts.length;
    const S = scene?.source ?? [0, 0], L = scene?.listener ?? [0, 0.3];
    this.S = S; this.L = L;
    const px = new Float32Array(n), py = new Float32Array(n), pr = new Float32Array(n), rho = new Float32Array(n), dist = new Float32Array(n);
    for (let i = 0; i < n; i++) { const [x, y, r] = posts[i]; px[i] = x; py[i] = y; pr[i] = r;
      dist[i] = Math.hypot(x - S[0], y - S[1]); rho[i] = (dist[i] + Math.hypot(x - L[0], y - L[1])) / 2; }
    this.P = { n, px, py, pr, rho, dist };
    this.byRho = Uint32Array.from({ length: n }, (_, i) => i).sort((a, b) => rho[a] - rho[b]);
    this.byDist = Uint32Array.from({ length: n }, (_, i) => i).sort((a, b) => dist[a] - dist[b]);
    // spatial hash for hover
    this.cell = 0.25; this.grid = new Map();
    for (let i = 0; i < n; i++) { const k = this._key(Math.floor(px[i] / this.cell), Math.floor(py[i] / this.cell));
      let a = this.grid.get(k); if (!a) this.grid.set(k, (a = [])); a.push(i); }
    this.maxR = n ? pr.reduce((m, v) => Math.max(m, v), 0) : 0;
    // field video
    const f = run.manifest.field;
    if (run.fieldUrl !== this.fieldUrl) {
      this.native = false; if (!this.video.paused) this.video.pause();
      this.fieldUrl = run.fieldUrl; this.videoReady = false; this.fieldError = false; this.shownFrame = null; this.seekingFrame = null; this.wantFrame = null;
      if (this.blobUrl) { URL.revokeObjectURL(this.blobUrl); this.blobUrl = null; }
      this.video.removeAttribute("src");
      // python -m http.server ignores Range requests, and Chrome cannot seek a video served
      // without them, so the whole file is fetched once and played from a blob URL.
      this.zero = null; this.gainKey = null;
      if (run.fieldUrl) { const url = run.fieldUrl;
        fetch(url).then((r) => { if (!r.ok) throw new Error(`${r.status} ${url}`); return r.blob(); }).then((b) => {
          if (this.fieldUrl !== url) return;
          this.blobUrl = URL.createObjectURL(b); this.video.src = this.blobUrl; this.video.load();
        }).catch((e) => { console.warn("field video unavailable:", e.message); this.fieldError = true; this.ac.request(); }); }
    }
    this.field = f || null;
    this.fieldBtn.disabled = !f; this.gainBtn.hidden = !f; this.fieldBtn.title = f ? "Show the Tier 1 pressure field" : "No pressure field in this run";
    if (!keepView) { this.view = null; this.userView = false; }
    this.hover = null; this.tip.hidden = true; this.staticDirty = true; this.ac.request();
  }

  // playing: drive the video natively at a matched playbackRate when the browser allows it (0.0625..16),
  // re-seeking only when it drifts by more than a frame; otherwise (and when paused) seek exact frames.
  setTime(t, playing = false, speed = 1) {
    this.t = t;
    const f = this.field;
    if (f && this.videoReady && playing && this.layers.field) {
      const rate = speed / (f.sim_seconds_per_frame * f.fps), vt = (t - f.t0_s) / f.sim_seconds_per_frame / f.fps;
      const inRange = vt >= 0 && vt < f.n_frames / f.fps;
      // native only where the decoder can keep up: playbackRate within the browser's 0.0625..16 and at most
      // ~120 decoded frames per second; above that, exact-frame seeks (dropping frames) are no worse
      if (rate >= 0.0625 && rate <= 16 && rate * f.fps <= 120 && inRange) {
        this.native = true; this.wantFrame = null; this.seekingFrame = null;
        if (Math.abs(this.video.playbackRate - rate) > 1e-6) this.video.playbackRate = rate;
        if (Math.abs(this.video.currentTime - vt) > 1 / f.fps && !this.video.seeking) this.video.currentTime = vt;
        if (this.video.paused) this.video.play().catch(() => {});
      } else this._stopNative();
    } else this._stopNative();
    if (!this.native) this._seekFor(t);
    if (this.follow) this._follow(); this.ac.request();
  }
  _stopNative() {
    if (!this.native) return;
    this.native = false; if (!this.video.paused) this.video.pause();
    this.shownFrame = null; this.seekingFrame = null; this._seekFor(this.t, true);
  }

  cycleGain() { this.gain = { 1: 2, 2: 4, 4: 8, 8: 1 }[this.gain]; this.gainBtn.textContent = `Gain \u00d7${this.gain}`;
    this.gainBtn.classList.toggle("on", this.gain > 1); this.gainKey = null; this.ac.request(); }
  toggleFollow() { this.follow = !this.follow; this.followBtn.classList.toggle("on", this.follow); this.followBtn.setAttribute("aria-pressed", String(this.follow));
    if (this.follow) this._follow(); this.ac.request(); }
  // centre the view on the outgoing front (clamped to the structure), keeping the zoom
  _follow() {
    if (!this.view || !this.scene) return; const wd = this.scene.wedge ?? { r_min: 3, r_max: 15 };
    const x = Math.max(0, Math.min(wd.r_max, this.c * this.t));
    this.view.ox = this.ac.w / 2 - x * this.view.s; this.userView = true; this.staticDirty = true;
  }
  // frame with gain applied: out = zero + g (in - zero), zero = the frame's background colour
  _gainFrame() {
    const f = this.field, key = `${this.shownFrame}|${this.gain}`;
    if (this.gainKey === key) return this.gainCanvas;
    const W = this.video.videoWidth, H = this.video.videoHeight; if (!W || !H) return this.video;
    const cv = this.gainCanvas ?? (this.gainCanvas = document.createElement("canvas")); cv.width = W; cv.height = H;
    const x = cv.getContext("2d", { willReadFrequently: true }); x.drawImage(this.video, 0, 0, W, H);
    const im = x.getImageData(0, 0, W, H), d = im.data;
    if (!this.zero) { // median of the four corners and the top/bottom centres, taken once per video
      const px = [[0, 0], [W - 1, 0], [0, H - 1], [W - 1, H - 1], [W >> 1, 0], [W >> 1, H - 1]].map(([a, b]) => (b * W + a) * 4);
      this.zero = [0, 1, 2].map((c) => px.map((o) => d[o + c]).sort((p, q) => p - q)[2]);
    }
    const [z0, z1, z2] = this.zero, g = this.gain;
    for (let i = 0; i < d.length; i += 4) { d[i] = z0 + g * (d[i] - z0); d[i + 1] = z1 + g * (d[i + 1] - z1); d[i + 2] = z2 + g * (d[i + 2] - z2); }
    x.putImageData(im, 0, 0); this.gainKey = key; return cv;
  }

  // ---- video sync: frame = (t - t0) / sim_seconds_per_frame, currentTime = frame / fps
  frameFor(t) { const f = this.field; return Math.max(0, Math.min(f.n_frames - 1, Math.floor((t - f.t0_s) / f.sim_seconds_per_frame + 1e-6))); }
  _seekFor(t, force = false) {
    if (!this.field || !this.videoReady) return;
    const fr = this.frameFor(t); this.wantFrame = fr;
    if (this.seekingFrame == null && (fr !== this.shownFrame || force)) this._seek(fr);
  }
  _seek(fr) { this.seekingFrame = fr; this.video.currentTime = (fr + SEEK_EPS) / this.field.fps; }

  // ---- view
  _key(ix, iy) { return (ix + 30000) * 60000 + (iy + 30000); }
  fit() {
    const w = this.ac.w, h = this.ac.h, wd = this.scene?.wedge ?? { half_angle_deg: 20, r_min: 3, r_max: 15 };
    const rmax = Math.max(wd.r_max, ...(this.P?.n ? [this.P.dist[this.byDist[this.P.n - 1]]] : [0]));
    const ys = Math.min(rmax * Math.sin(wd.half_angle_deg * DEG), this.strip ?? Infinity);
    this.fitHBtn.hidden = !(rmax / (2 * ys) > 8);
    // pixel margins: room for the clap/listener labels on the left and ring labels on the right
    const x0 = -0.3, x1 = rmax + 0.3, y0 = -ys - 0.3, y1 = ys + 0.3, padL = 64, padR = 70, padY = this.compact ? 16 : 30;
    const s = Math.min((w - padL - padR) / (x1 - x0), (h - 2 * padY) / (y1 - y0));
    this.view = { s, ox: padL + (w - padL - padR - s * (x1 - x0)) / 2 - x0 * s, oy: h / 2 + ((y0 + y1) / 2) * s };
    this.fitScale = s; this.userView = false; this.staticDirty = true; this.ac.request();
  }
  // long strips: fill the panel height with the strip and follow the front along it
  fitHeight() {
    if (!this.view) this.fit();
    const wd = this.scene?.wedge ?? { half_angle_deg: 20, r_max: 15 }, ys = Math.min(wd.r_max * Math.sin(wd.half_angle_deg * DEG), this.strip ?? Infinity);
    const s = (this.ac.h - 60) / (2 * ys + 0.6); this.view = { s, ox: 0, oy: this.ac.h / 2 }; this.userView = true;
    if (!this.follow) this.toggleFollow(); else this._follow();
    this.staticDirty = true; this.ac.request();
  }
  toScreen(x, y) { const v = this.view; return [v.ox + x * v.s, v.oy - y * v.s]; }
  toWorld(sx, sy) { const v = this.view; return [(sx - v.ox) / v.s, (v.oy - sy) / v.s]; }

  _bindPointer() {
    const c = this.canvas; let drag = null;
    c.addEventListener("wheel", (e) => { e.preventDefault(); if (!this.view) return;
      const k = Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015)), v = this.view, r = c.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top, s = Math.min(6000, Math.max(this.fitScale * 0.5, v.s * k)), f = s / v.s;
      v.ox = sx - (sx - v.ox) * f; v.oy = sy - (sy - v.oy) * f; v.s = s; this.userView = true; this.staticDirty = true; this.ac.request(); }, { passive: false });
    c.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, ox: this.view?.ox, oy: this.view?.oy, moved: false }; c.setPointerCapture(e.pointerId); });
    c.addEventListener("pointermove", (e) => {
      const r = c.getBoundingClientRect(); this.mouse = [e.clientX - r.left, e.clientY - r.top];
      if (drag && this.view) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        if (drag.moved) { this.view.ox = drag.ox + dx; this.view.oy = drag.oy + dy; this.userView = true; this.staticDirty = true; c.classList.add("panning"); } }
      if (!drag?.moved) this._hoverAt(...this.mouse);
      this.ac.request();
    });
    const end = () => { drag = null; c.classList.remove("panning"); };
    c.addEventListener("pointerup", end); c.addEventListener("pointercancel", end);
    c.addEventListener("pointerleave", () => { this.mouse = null; this._setHover(null); this.ac.request(); });
    c.addEventListener("dblclick", () => this.fit());
  }
  _hoverAt(sx, sy) {
    if (!this.view || !this.P?.n) return this._setHover(null);
    const [x, y] = this.toWorld(sx, sy), s = this.view.s, reach = Math.max(7 / s, 0);
    const R = Math.ceil((reach + this.maxR) / this.cell), cx = Math.floor(x / this.cell), cy = Math.floor(y / this.cell);
    let best = -1, bd = Infinity; const { px, py, pr } = this.P;
    for (let i = -R; i <= R; i++) for (let j = -R; j <= R; j++) {
      const a = this.grid.get(this._key(cx + i, cy + j)); if (!a) continue;
      for (const k of a) { const d = Math.hypot(px[k] - x, py[k] - y) - Math.max(pr[k], MIN_POST_PX / s); if (d < reach && d < bd) { bd = d; best = k; } }
    }
    this._setHover(best < 0 ? null : best);
  }
  _setHover(i) {
    if (i === this.hover) { this._placeTip(); return; }
    this.hover = i;
    if (i == null) { this.tip.hidden = true; this.onHover?.(null); return; }
    const { px, py, pr, rho } = this.P, delay = 2 * rho[i] / this.c;
    this.tip.replaceChildren(
      el("div", { class: "tip-h" }, `Post ${i + 1} of ${this.P.n.toLocaleString("en-US")}`),
      el("dl", {}, el("dt", {}, "Range"), el("dd", {}, `${num(rho[i], 3)} m`),
        el("dt", {}, "Echo delay"), el("dd", {}, `${num(delay * 1000, 2)} ms`),
        el("dt", {}, "Radius"), el("dd", {}, fmtRadius(pr[i])),
        el("dt", {}, "Position"), el("dd", {}, `${num(px[i], 2)}, ${num(py[i], 2)} m`)));
    this.tip.hidden = false; this._placeTip();
    this.onHover?.({ index: i, rho: rho[i], delay, radius: pr[i] });
  }
  _placeTip() {
    if (this.tip.hidden || !this.mouse) return;
    const [mx, my] = this.mouse, tw = this.tip.offsetWidth, th = this.tip.offsetHeight;
    this.tip.style.left = `${mx + 16 + tw > this.ac.w ? mx - tw - 12 : mx + 16}px`;
    this.tip.style.top = `${Math.max(4, Math.min(this.ac.h - th - 4, my - th / 2))}px`;
  }

  // ---- drawing
  draw(ctx, w, h) {
    if (!this.scene) return;
    if (!this.view) this.fit();
    const C = colors(); this.C = C;
    if (this.staticDirty || this.off.width !== this.canvas.width || this.off.height !== this.canvas.height) this._drawStatic(w, h);
    // 1. pressure field
    const f = this.field;
    if (f && this.native) this.shownFrame = Math.min(f.n_frames - 1, Math.floor(this.video.currentTime * f.fps + 1e-6));
    const showField = f && this.layers.field && this.videoReady && this.shownFrame != null;
    if (showField) {
      const [x0, x1, y0, y1] = f.extent_m, [sx, sy] = this.toScreen(x0, y1);
      // plain source-over, full opacity: nothing dims the frame except outside the video's time span
      const tEnd = f.t0_s + f.n_frames * f.sim_seconds_per_frame, outside = this.t < f.t0_s || this.t > tEnd;
      ctx.imageSmoothingEnabled = true; ctx.globalAlpha = outside ? 0.35 : 1;
      ctx.drawImage(this.gain > 1 ? this._gainFrame() : this.video, sx, sy, (x1 - x0) * this.view.s, (y1 - y0) * this.view.s);
      ctx.globalAlpha = 1;
    }
    // 2. static geometry
    ctx.drawImage(this.off, 0, 0, w, h);
    // 3. live overlay
    this._drawLive(ctx, w, h, showField);
    this.fieldNote.textContent = (f ? (this.layers.field ? (showField ? this._fieldLabel(f) : this.fieldError ? "Pressure field video could not be loaded" : "Loading pressure field") : "Pressure field hidden")
      : "No pressure field in this run: geometric wavefront shown") + (this.pulse && showField ? `; wave from an ideal short pulse; shaded band = your sound's length, ${num(this.pulse * 1000, this.pulse < 0.01 ? 1 : 0)} ms = ${num(this.c * this.pulse, 2)} m` : this.pulse ? `; shaded band = your sound's length, ${num(this.pulse * 1000, this.pulse < 0.01 ? 1 : 0)} ms = ${num(this.c * this.pulse, 2)} m` : "");
    this._readout();
  }

  setPulse(seconds) { this.pulse = seconds || null; this.ac.request(); }
  _fieldLabel(f) {
    const tEnd = f.t0_s + f.n_frames * f.sim_seconds_per_frame;
    if (this.t > tEnd) return `Tier 1 pressure ends at ${num(tEnd * 1000, 1)} ms: last frame shown dimmed`;
    if (this.t < f.t0_s) return `Tier 1 pressure starts at ${num(f.t0_s * 1000, 1)} ms: first frame shown dimmed`;
    return `Tier 1 pressure, frame ${this.shownFrame + 1} of ${f.n_frames}${this.gain > 1 ? `, gain \u00d7${this.gain}` : ""}`;
  }

  _drawStatic(w, h) {
    const dpr = this.ac.dpr, off = this.off; off.width = this.canvas.width; off.height = this.canvas.height;
    const ctx = off.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    const C = this.C ?? colors(), s = this.view.s, wd = this.scene.wedge ?? { half_angle_deg: 20, r_min: 3, r_max: 15 };
    const ha = wd.half_angle_deg * DEG, [Sx, Sy] = this.toScreen(...this.S);
    const fieldOn = this.field && this.layers.field;
    ctx.font = `11px ${getComputedStyle(document.body).fontFamily}`;
    // wedge (cut to the strip when posts are confined to one)
    ctx.save(); this._clipStrip(ctx, w);
    ctx.strokeStyle = C.faint; ctx.lineWidth = 1; ctx.setLineDash([]);
    ctx.beginPath();
    for (const a of [-ha, ha]) { const [ax, ay] = this.toScreen(wd.r_min * Math.cos(a), wd.r_min * Math.sin(a)), [bx, by] = this.toScreen(wd.r_max * Math.cos(a), wd.r_max * Math.sin(a)); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); }
    ctx.moveTo(...this.toScreen(wd.r_min * Math.cos(ha), wd.r_min * Math.sin(ha))); ctx.arc(Sx, Sy, wd.r_min * s, -ha, ha);
    ctx.moveTo(...this.toScreen(wd.r_max * Math.cos(ha), wd.r_max * Math.sin(ha))); ctx.arc(Sx, Sy, wd.r_max * s, -ha, ha);
    ctx.stroke(); ctx.restore();
    if (this.strip) { const x0 = Math.max(wd.r_min, this.strip / Math.tan(ha)), x1 = Math.sqrt(wd.r_max ** 2 - this.strip ** 2);
      ctx.strokeStyle = C.faint; ctx.beginPath();
      for (const y of [-this.strip, this.strip]) { ctx.moveTo(...this.toScreen(x0, y)); ctx.lineTo(...this.toScreen(x1, y)); } ctx.stroke(); }
    // equal-delay rings: confocal ellipses with foci S and L, sum of distances = 2 rho
    if (this.layers.rings) this._drawRings(ctx, w, h, wd, C);
    // posts
    const { n, px, py, pr } = this.P, small = new Path2D(), big = new Path2D();
    for (let i = 0; i < n; i++) {
      const sx = this.view.ox + px[i] * s, sy = this.view.oy - py[i] * s, rr = Math.max(pr[i] * s, MIN_POST_PX);
      if (sx < -rr || sy < -rr || sx > w + rr || sy > h + rr) continue;
      if (rr < 1.6) small.rect(sx - rr, sy - rr, 2 * rr, 2 * rr); else { big.moveTo(sx + rr, sy); big.arc(sx, sy, rr, 0, 2 * Math.PI); }
    }
    ctx.globalAlpha = fieldOn ? 0.55 : 0.85; ctx.fillStyle = C.cool; ctx.fill(small); ctx.fill(big);
    ctx.globalAlpha = 1;
    // source and listener
    const [Lx, Ly] = this.toScreen(...this.L);
    ctx.fillStyle = C.text; ctx.beginPath(); ctx.arc(Sx, Sy, 3.5, 0, 2 * Math.PI); ctx.fill();
    ctx.strokeStyle = C.text; ctx.lineWidth = 1.25; ctx.beginPath(); ctx.arc(Lx, Ly, 4.5, 0, 2 * Math.PI); ctx.stroke();
    ctx.fillStyle = C.dim; ctx.textAlign = "right"; ctx.textBaseline = "middle";
    const sep = Math.abs(Ly - Sy) < 16;
    ctx.lineWidth = 3; ctx.strokeStyle = C.ink; ctx.lineJoin = "round"; // knock out of the field video
    for (const [txt, x, y] of [["clap", Sx - 9, sep ? Sy + 7 : Sy], ["listener", Lx - 9, sep ? Ly - 7 : Ly]]) { ctx.strokeText(txt, x, y); ctx.fillText(txt, x, y); }
    // scale bar
    const bar = niceStep(120 / s, 1), bl = bar * s, bx = 14, by = h - 16;
    ctx.strokeStyle = C.dim; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(bx, by - 4); ctx.lineTo(bx, by); ctx.lineTo(bx + bl, by); ctx.lineTo(bx + bl, by - 4); ctx.stroke();
    ctx.fillStyle = C.dim; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
    ctx.fillText(bar >= 1 ? `${bar} m` : `${Math.round(bar * 100)} cm`, bx + bl + 6, by + 1);
    this.staticDirty = false;
  }

  _clipStrip(ctx, w) {
    if (!this.strip) return; const [, y0] = this.toScreen(0, this.strip);
    ctx.beginPath(); ctx.rect(-10, y0, w + 20, 2 * this.strip * this.view.s); ctx.clip();
  }

  _drawRings(ctx, w, h, wd, C) {
    const s = this.view.s, ha = wd.half_angle_deg * DEG, step = niceStep(110 / s, 1);
    const fx = (this.S[0] + this.L[0]) / 2, fy = (this.S[1] + this.L[1]) / 2, fc = Math.hypot(this.L[0] - this.S[0], this.L[1] - this.S[1]) / 2;
    const rot = Math.atan2(this.L[1] - this.S[1], this.L[0] - this.S[0]); // major axis along S->L
    const [cx, cy] = this.toScreen(fx, fy), [Sx, Sy] = this.toScreen(...this.S), reach = wd.r_max + 0.6 * step;
    ctx.save();
    this._clipStrip(ctx, w);
    ctx.beginPath(); ctx.moveTo(Sx, Sy); ctx.arc(Sx, Sy, reach * s, -ha - 0.02, ha + 0.02); ctx.closePath(); ctx.clip();
    const fieldOn = this.field && this.layers.field;
    ctx.strokeStyle = fieldOn ? C.dim : C.grid; ctx.globalAlpha = fieldOn ? 0.45 : 1; ctx.lineWidth = 1;
    const dec = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
    // visible rho window, to keep the loop short when zoomed in
    const corners = [[0, 0], [w, 0], [0, h], [w, h]].map(([a, b]) => this.toWorld(a, b));
    const ds = corners.map(([x, y]) => Math.hypot(x - fx, y - fy));
    const inside = (() => { const [x, y] = this.toWorld(0, 0), [x2, y2] = this.toWorld(w, h); return fx >= x && fx <= x2 && fy <= y && fy >= y2; })();
    const lo = inside ? step : Math.max(step, Math.floor((Math.min(...ds) - 1) / step) * step), hi = Math.min(reach, Math.max(...ds) + step);
    const labels = [];
    for (let rho = lo; rho <= hi + 1e-9; rho += step) {
      if (rho <= fc) continue;
      const a = rho * s, b = Math.sqrt(rho * rho - fc * fc) * s;
      ctx.beginPath(); ctx.ellipse(cx, cy, a, b, -rot, 0, 2 * Math.PI); ctx.stroke();
      if (rho <= wd.r_max + 1e-9) labels.push(rho);
    }
    ctx.restore(); ctx.globalAlpha = 1;
    // labels just outside the upper wedge edge, metres over ms of echo
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
    // point at bearing th from S on the ellipse: r = (4 rho^2 - |SL|^2) / (4 rho - 2 u.SL)
    const at = (rho, th) => { const ud = Math.cos(th) * (this.L[0] - this.S[0]) + Math.sin(th) * (this.L[1] - this.S[1]);
      const r = (4 * rho * rho - 4 * fc * fc) / (4 * rho - 2 * ud); return this.toScreen(this.S[0] + r * Math.cos(th), this.S[1] + r * Math.sin(th)); };
    const ok = ([x, y]) => x >= -20 && x <= w - 40 && y >= 24 && y <= h - 4;
    for (const rho of labels) {
      const dth = 6 / (this.view.s * rho); // about 6 px outside the wedge edge at any zoom
      let [lx, ly] = this.strip ? [NaN, NaN] : at(rho, ha + dth);
      if (!ok([lx, ly])) {
        // strip: label where the ring meets the strip's upper edge; zoomed in: where it crosses the top of the view
        const ySt = this.strip ? this.toScreen(0, this.strip)[1] - 2 : -Infinity;
        let lo = -ha - dth, hi = ha + dth; const yTop = Math.max(44, ySt);
        if ((at(rho, lo)[1] - yTop) * (at(rho, hi)[1] - yTop) > 0) continue;
        for (let k = 0; k < 40; k++) { const mid = (lo + hi) / 2; if ((at(rho, mid)[1] - yTop) * (at(rho, lo)[1] - yTop) <= 0) hi = mid; else lo = mid; }
        [lx, ly] = at(rho, (lo + hi) / 2); lx += 4; if (yTop !== ySt) ly += 14;
        if (!ok([lx, ly])) continue;
      }
      // outward of the wedge edge, knocked out of whatever is behind
      ctx.lineWidth = 3; ctx.strokeStyle = C.ink; ctx.lineJoin = "round";
      const a = `${num(rho, dec)} m`, b = `${num(2 * rho / this.c * 1000, dec + 1)} ms`;
      ctx.strokeText(a, lx - 2, ly - 16); ctx.fillStyle = C.text; ctx.fillText(a, lx - 2, ly - 16);
      ctx.strokeText(b, lx - 2, ly - 4); ctx.fillStyle = C.dim; ctx.fillText(b, lx - 2, ly - 4);
    }
  }

  _drawLive(ctx, w, h, showField) {
    const C = this.C, s = this.view.s, t = this.t, c = this.c, { px, py, pr, rho, dist } = this.P;
    const [Sx, Sy] = this.toScreen(...this.S);
    const dot = (i, ring) => { const sx = this.view.ox + px[i] * s, sy = this.view.oy - py[i] * s, rr = Math.max(pr[i] * s, ring ? 2.2 : 1.4);
      if (sx < -9 || sy < -9 || sx > w + 9 || sy > h + 9) return; ctx.moveTo(sx + rr, sy); ctx.arc(sx, sy, rr, 0, 2 * Math.PI); };
    // outgoing wavefront |P - S| = c t; posts it is passing light up
    const R = c * t, band = Math.max(0.06, 2.5 / s);
    // Live mode: the user's sound occupies c × duration behind the front (34 cm per ms)
    if (this.pulse && t > 0) { const r0 = Math.max(0, R - c * this.pulse) * s; ctx.save(); ctx.fillStyle = C.accent; ctx.globalAlpha = 0.13;
      ctx.beginPath(); ctx.arc(Sx, Sy, R * s, 0, 2 * Math.PI); ctx.arc(Sx, Sy, r0, 0, 2 * Math.PI, true); ctx.fill("evenodd"); ctx.restore(); }
    if (!showField && t > 0) { ctx.strokeStyle = C.accent; ctx.globalAlpha = 0.75; ctx.lineWidth = 1.25; ctx.beginPath(); ctx.arc(Sx, Sy, R * s, 0, 2 * Math.PI); ctx.stroke(); ctx.globalAlpha = 1; }
    const lit = new Path2D(); let k = lowerBound(dist, this.byDist, R - band);
    let count = 0; for (; k < this.byDist.length && dist[this.byDist[k]] <= R && count < 4000; k++, count++) { const i = this.byDist[k];
      const sx = this.view.ox + px[i] * s, sy = this.view.oy - py[i] * s, rr = Math.max(pr[i] * s, 1.6); lit.moveTo(sx + rr, sy); lit.arc(sx, sy, rr, 0, 2 * Math.PI); }
    ctx.fillStyle = C.accent; ctx.fill(lit);
    // the posts being heard now: bistatic range rho = c t / 2
    const rh = c * t / 2, wd = this.scene.wedge;
    if (rh > (wd?.r_min ?? 0) - 0.5 && rh < (wd?.r_max ?? 1e9) + 0.5) {
      const fx = (this.S[0] + this.L[0]) / 2, fy = (this.S[1] + this.L[1]) / 2, fc = Math.hypot(this.L[0] - this.S[0], this.L[1] - this.S[1]) / 2;
      const [cx, cy] = this.toScreen(fx, fy), ha = (wd?.half_angle_deg ?? 20) * DEG;
      ctx.save(); this._clipStrip(ctx, w); ctx.beginPath(); ctx.moveTo(Sx, Sy); ctx.arc(Sx, Sy, (rh + 1) * s, -ha - 0.03, ha + 0.03); ctx.closePath(); ctx.clip();
      ctx.setLineDash([4, 4]); ctx.strokeStyle = C.text; ctx.globalAlpha = 0.6; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.ellipse(cx, cy, rh * s, Math.sqrt(Math.max(0, rh * rh - fc * fc)) * s, -Math.atan2(this.L[1] - this.S[1], this.L[0] - this.S[0]), 0, 2 * Math.PI); ctx.stroke();
      ctx.restore(); ctx.setLineDash([]);
      const heard = new Path2D(), hb = Math.max(0.02, 1.5 / s); let j = lowerBound(rho, this.byRho, rh - hb);
      for (let m = 0; j < this.byRho.length && rho[this.byRho[j]] <= rh + hb && m < 4000; j++, m++) { const i = this.byRho[j];
        const sx = this.view.ox + px[i] * s, sy = this.view.oy - py[i] * s, rr = Math.max(pr[i] * s, 1.8) + 1.5; heard.moveTo(sx + rr, sy); heard.arc(sx, sy, rr, 0, 2 * Math.PI); }
      ctx.strokeStyle = C.text; ctx.lineWidth = 1; ctx.stroke(heard);
    }
    // hovered post
    if (this.hover != null) { const i = this.hover, sx = this.view.ox + px[i] * s, sy = this.view.oy - py[i] * s, rr = Math.max(pr[i] * s, 2) + 4;
      ctx.strokeStyle = C.accent; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(sx, sy, rr, 0, 2 * Math.PI); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(sx - rr - 6, sy); ctx.lineTo(sx - rr - 2, sy); ctx.moveTo(sx + rr + 2, sy); ctx.lineTo(sx + rr + 6, sy);
      ctx.moveTo(sx, sy - rr - 6); ctx.lineTo(sx, sy - rr - 2); ctx.moveTo(sx, sy + rr + 2); ctx.lineTo(sx, sy + rr + 6); ctx.stroke(); }
  }

  _readout() {
    const t = this.t, c = this.c;
    let s = `outgoing front ${num(c * t, 2)} m, now hearing range ${num(c * t / 2, 2)} m`;
    if (this.mouse && this.view) { const [x, y] = this.toWorld(...this.mouse), r = (Math.hypot(x - this.S[0], y - this.S[1]) + Math.hypot(x - this.L[0], y - this.L[1])) / 2;
      s = `cursor ${num(x, 2)}, ${num(y, 2)} m, range ${num(r, 2)} m, echo ${num(2 * r / c * 1000, 2)} ms`; }
    this.readout.textContent = s;
  }
  destroy() { this.ac.destroy(); this.video.removeAttribute("src"); this.video.load(); this.root.remove(); }
}

function lowerBound(vals, order, x) { let lo = 0, hi = order.length; while (lo < hi) { const m = (lo + hi) >> 1; if (vals[order[m]] < x) lo = m + 1; else hi = m; } return lo; }
