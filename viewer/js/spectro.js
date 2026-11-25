// Spectrograms: target, Tier 0 echo, Tier 1 echo on one frequency axis and one colour scale.
import { AutoCanvas, colors, el, num } from "./util.js";

const STOPS = [[0, "--ink"], [0.25, "--spec1"], [0.5, "--spec2"], [0.75, "--cool"], [1, "--spec4"]];
function lut() {
  const cs = getComputedStyle(document.documentElement);
  const hex = (v) => { v = cs.getPropertyValue(v).trim().replace("#", ""); return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16)); };
  const st = STOPS.map(([p, v]) => [p, hex(v)]), out = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) { const p = i / 255; let k = 0; while (k < st.length - 2 && p > st[k + 1][0]) k++;
    const [p0, c0] = st[k], [p1, c1] = st[k + 1], u = (p - p0) / (p1 - p0);
    for (let ch = 0; ch < 3; ch++) out[i * 3 + ch] = c0[ch] + (c1[ch] - c0[ch]) * u; }
  return out;
}

export class SpectroPanel {
  constructor(host, clock, { cells = [["target", "Target"], ["tier0", "Tier 0 echo"], ["tier1", "Tier 1 echo", "No Tier 1 run yet"]], sub = "0 to 5 kHz, design band marked" } = {}) {
    this.clock = clock; this.t = 0;
    this.root = el("section", { class: "panel spectro" });
    this.scale = el("div", { class: "cscale", title: "dB re each panel's own maximum" }, el("span", {}, "−60"), el("i"), el("span", {}, "0 dB"));
    this.root.append(el("header", {}, el("h2", {}, "Spectrograms"), this.subEl = el("span", { class: "sub" }, sub), el("div", { class: "tools" }, this.scale)));
    this.row = el("div", { class: "specrow" }); this.root.append(this.row); host.append(this.root);
    // cells: [[key, caption, empty text]]; the first one carries the frequency axis
    this.cells = cells.map(([k, cap, empty], ci) => {
      const canvas = el("canvas"), cell = el("figure", {}, el("figcaption", {}, cap), el("div", { class: "stage" }, canvas));
      this.row.append(cell);
      const ac = new AutoCanvas(canvas, (ctx, w, h) => this.draw(k, ctx, w, h));
      canvas.addEventListener("pointerdown", (e) => { const r = canvas.getBoundingClientRect(), [t0, t1] = this.trange(); const pl = ci === 0 ? 26 : 0;
        this.clock.seek(t0 + (e.clientX - r.left - pl) / (r.width - pl) * (t1 - t0)); });
      return { k, ac, img: null, first: ci === 0, empty };
    });
  }
  trange() { const T = this.sp?.times_s; return T?.length ? [0, Math.max(T[T.length - 1], this.duration)] : [0, this.duration || 0.1]; }
  setRun(run) {
    this.sp = run.spectro; this.duration = run.duration; const L = lut(), sp = this.sp;
    for (const cell of this.cells) {
      cell.img = null; const d = sp?.panels?.[cell.k];
      if (d?.length) { const F = d.length, T = d[0].length, floor = sp.db_floor ?? -60, cv = document.createElement("canvas"); cv.width = T; cv.height = F;
        const ctx = cv.getContext("2d"), im = ctx.createImageData(T, F);
        for (let f = 0; f < F; f++) for (let t = 0; t < T; t++) { const v = Math.max(0, Math.min(255, Math.round((d[f][t] - floor) / -floor * 255))), o = ((F - 1 - f) * T + t) * 4;
          im.data[o] = L[v * 3]; im.data[o + 1] = L[v * 3 + 1]; im.data[o + 2] = L[v * 3 + 2]; im.data[o + 3] = 255; }
        ctx.putImageData(im, 0, 0); cell.img = cv; }
      cell.ac.request();
    }
  }
  setTime(t) { this.t = t; for (const c of this.cells) c.ac.request(); }
  draw(k, ctx, w, h) {
    const C = colors(), font = getComputedStyle(document.body).fontFamily, cell = this.cells.find((c) => c.k === k), sp = this.sp;
    ctx.font = `10px ${font}`;
    const padL = cell.first ? 26 : 0, padB = 14, pw = w - padL, ph = h - padB;
    if (!cell.img) { ctx.strokeStyle = C.line; ctx.strokeRect(padL + 0.5, 0.5, pw - 1, ph - 1); ctx.fillStyle = C.dim; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.font = `12px ${font}`; ctx.fillText(cell.empty ?? "No spectrogram", padL + pw / 2, ph / 2); return; }
    const fmax = sp.freqs_hz[sp.freqs_hz.length - 1], T = sp.times_s, [t0, t1] = this.trange();
    // place image columns at their true times (frame centres)
    const dt = T.length > 1 ? T[1] - T[0] : t1, xa = padL + ((T[0] - dt / 2) - t0) / (t1 - t0) * pw, xb = padL + ((T[T.length - 1] + dt / 2) - t0) / (t1 - t0) * pw;
    ctx.fillStyle = C.ink; ctx.fillRect(padL, 0, pw, ph);
    ctx.imageSmoothingEnabled = true; ctx.drawImage(cell.img, xa, 0, xb - xa, ph);
    // design band 500 Hz to 4 kHz
    ctx.strokeStyle = C.text; ctx.globalAlpha = 0.25; ctx.setLineDash([2, 3]);
    for (const f of [500, 4000]) { const y = Math.round(ph - f / fmax * ph) + 0.5; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w, y); ctx.stroke(); }
    ctx.setLineDash([]); ctx.globalAlpha = 1;
    ctx.fillStyle = C.dim; ctx.textAlign = "right"; ctx.textBaseline = "middle";
    if (padL) for (const f of [0, 1000, 2000, 3000, 4000, 5000]) if (f <= fmax) { const y = ph - f / fmax * ph; ctx.fillText(f ? `${f / 1000}k` : "0", padL - 4, Math.min(ph - 5, Math.max(5, y))); }
    ctx.textAlign = "left"; ctx.textBaseline = "bottom"; ctx.fillStyle = C.faint;
    ctx.fillText(`${num(t0 * 1000, 0)}`, padL, h); ctx.textAlign = "right"; ctx.fillText(`${num(t1 * 1000, 0)} ms`, w, h);
    const x = padL + (this.t - t0) / (t1 - t0) * pw;
    if (x >= padL && x <= w) { ctx.fillStyle = C.accent; ctx.fillRect(Math.round(x) - 1, 0, 2, ph); }
  }
}
