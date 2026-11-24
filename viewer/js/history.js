// History: loss against iteration per design phase (uPlot), saved iterations loadable.
import uPlot from "../vendor/uPlot.esm.js";
import { colors, el, num } from "./util.js";

export class HistoryPanel {
  constructor(host, { onLoad }) {
    this.onLoad = onLoad;
    this.root = el("section", { class: "panel history" });
    this.tabs = el("div", { class: "tools" });
    this.root.append(el("header", {}, el("h2", {}, "History"), this.sub = el("span", { class: "sub" }, "loss per iteration"), this.tabs));
    this.plotEl = el("div", { class: "plot" }); this.chips = el("div", { class: "chips" });
    this.root.append(this.plotEl, this.chips); host.append(this.root);
    this.ro = new ResizeObserver(() => this._size()); this.ro.observe(this.plotEl);
    this.active = null;
  }
  setRun(run, activeDir = null) {
    this.run = run; this.activeDir = activeDir; const ph = run.history?.phases ?? [];
    if (this.phaseIdx == null || this.lastRun !== run) this.phaseIdx = Math.max(0, ph.length - 1);
    this.lastRun = run; this._render();
  }
  setActive(dir) { this.activeDir = dir; this._chips(); }
  _render() {
    const ph = this.run.history?.phases ?? [];
    this.sub.hidden = ph.length > 1;
    this.tabs.replaceChildren(...(ph.length > 1 ? ph.map((p, i) => el("button", { class: "tool toggle" + (i === this.phaseIdx ? " on" : ""), "aria-pressed": String(i === this.phaseIdx),
      onclick: () => { this.phaseIdx = i; this._render(); } }, p.name)) : []));
    this.u?.destroy(); this.u = null; this.plotEl.replaceChildren();
    const p = ph[this.phaseIdx];
    if (!p || !p.iters?.length) { this.plotEl.append(el("p", { class: "empty" }, "No history.json in this run.")); this._chips(); return; }
    const C = colors(), font = getComputedStyle(document.body).fontFamily, savedSet = new Map((p.saved ?? []).map((s) => [s.iter, s]));
    const pos = p.loss.every((v) => v > 0), hasScore = Array.isArray(p.score);
    const data = [p.iters, p.loss, p.iters.map((it, i) => (savedSet.has(it) ? p.loss[i] : null))];
    if (hasScore) data.push(p.score);
    const axis = { stroke: C.dim, grid: { stroke: C.grid, width: 1 }, ticks: { stroke: C.grid, width: 1, size: 4 }, font: `10px ${font}`, labelFont: `11px ${font}` };
    const opts = {
      width: 300, height: 120, legend: { show: false }, cursor: { y: false, points: { size: 6, fill: C.accent } },
      scales: { x: { time: false }, y: { distr: pos ? 3 : 1 }, ...(hasScore ? { s: { range: [0, 1] } } : {}) },
      axes: [{ ...axis, label: p.x_label ?? "iteration", labelSize: 14, size: 22 },
        { ...axis, size: 38, values: (u, v) => v.map((x) => (x == null ? "" : num(x, x < 1 ? 2 : 1))) },
        ...(hasScore ? [{ ...axis, side: 1, scale: "s", size: 30, grid: { show: false }, values: (u, v) => v.map((x) => num(x, 1)) }] : [])],
      series: [{}, { label: "loss", stroke: C.cool, width: 1.25 },
        { label: "saved", stroke: "transparent", paths: () => null, points: { show: true, size: 7, fill: C.accent, stroke: C.accent } },
        ...(hasScore ? [{ label: "score", scale: "s", stroke: C.text, width: 1, dash: [3, 3] }] : [])],
    };
    this.u = new uPlot(opts, data, this.plotEl);
    this.u.over.addEventListener("click", () => { const i = this.u.cursor.idx; if (i == null) return;
      const it = p.iters[i], near = (p.saved ?? []).reduce((b, s) => (b == null || Math.abs(s.iter - it) < Math.abs(b.iter - it) ? s : b), null);
      if (near && Math.abs(near.iter - it) <= (p.iters[p.iters.length - 1] - p.iters[0]) * 0.04) this.onLoad({ phase: p.name, xLabel: p.x_label, ...near }); });
    this._size(); this._chips();
  }
  _chips() {
    const p = this.run?.history?.phases?.[this.phaseIdx], saved = p?.saved ?? [];
    const chip = (label, dir, s) => el("button", { class: "chip" + ((this.activeDir ?? null) === dir ? " on" : ""), "aria-pressed": String((this.activeDir ?? null) === dir),
      onclick: () => this.onLoad(s) }, label);
    const items = [chip("Final", null, null), ...saved.map((s) => chip(`${p.x_label ?? "iter"} ${s.iter}`, s.dir, { phase: p.name, xLabel: p.x_label, ...s }))];
    this.chips.replaceChildren(el("span", { class: "lbl" }, saved.length ? "Load" : "No saved iterations"), ...(saved.length ? items : []));
  }
  _size() { if (!this.u) return; const r = this.plotEl.getBoundingClientRect(); if (r.width > 10 && r.height > 10) this.u.setSize({ width: Math.floor(r.width), height: Math.floor(r.height) }); }
}
