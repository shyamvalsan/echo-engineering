// One run laid out as panels. Full layout for a single run, compact for compare mode.
import { ScenePanel } from "./scene.js";
import { GroovePanel, EchoPanel, TimeWindow } from "./timepanels.js";
import { SpectroPanel } from "./spectro.js";
import { ScorePanel } from "./scorecard.js";
import { HistoryPanel } from "./history.js";
import { loadIteration } from "./data.js";
import { el } from "./util.js";

export class RunView {
  constructor(host, run, { clock, compact = false, side = null, onTrackChange }) {
    this.run = run; this.clock = clock; this.compact = compact; this.onTrackChange = onTrackChange; this.iter = null;
    this.root = el("div", { class: compact ? "runview compact" : "runview" });
    if (side) this.root.append(el("div", { class: "sidehead" }, el("span", { class: "side" }, side), el("span", { class: "rtitle" }, run.manifest.title ?? run.entry.path), el("span", { class: "rpath" }, run.entry.path)));
    host.append(this.root);
    this.win = new TimeWindow();
    const colA = el("div", { class: "col col-scene" }), colB = el("div", { class: "col col-time" }), colC = el("div", { class: "col col-score" });
    this.root.append(colA, colB, colC);
    const hover = (p) => { this.groove.setMarker(p); this.echo.setMarker(p); };
    this.scene = new ScenePanel(colA, { onHover: hover, compact });
    this.groove = new GroovePanel(colB, this.win, clock);
    this.echo = new EchoPanel(colB, this.win, clock, () => this.onTrackChange?.());
    if (!compact) this.spectro = new SpectroPanel(colB, clock);
    this.score = new ScorePanel(colC, { compact });
    if (!compact) this.history = new HistoryPanel(colC, { onLoad: (s) => this.loadIter(s) });
    this.render();
  }
  render() {
    const run = this.run, it = this.iter;
    this.win.reset([0, run.duration]);
    const note = it ? `saved iteration, ${it.label}` : null;
    this.scene.setRun(run, it?.scene ?? run.scene, note);
    this.groove.setRun(run, it?.profile ?? run.profile, note);
    this.echo.setRun(run, it?.echo ?? null, note);
    this.spectro?.setRun(run);
    this.score.setRun(run, it?.metrics ?? run.metrics, it ? `Showing ${note}. Spectrograms and audio buttons other than Echo stay on the final design.` : null);
    this.history?.setRun(run, it?.dir ?? null);
  }
  async loadIter(s) {
    if (!s) { this.iter = null; this.render(); this.onTrackChange?.(); return; }
    const d = await loadIteration(this.run, s.dir);
    this.iter = { ...d, dir: s.dir, label: `${s.phase}, ${(s.xLabel ?? "iteration").toLowerCase()} ${s.iter}` };
    this.render(); this.onTrackChange?.();
  }
  track(kind) {
    const a = this.run.audio;
    if (kind === "target") return a.target;
    if (kind === "as_heard") return a.asHeard;
    return this.echo.track();
  }
  setTime(t) { this.scene.setTime(t); this.groove.setTime(t); this.echo.setTime(t); this.spectro?.setTime(t); }
  destroy() { this.scene.destroy(); this.root.remove(); }
}
