// Live mode: your microphone through the selected structure, takes you can replay with the waves,
// sound files as sources, and "design from a sound" through the optional lab server.
import { ScenePanel } from "../scene.js";
import { TimePanel, TimeWindow } from "../timepanels.js";
import { SpectroPanel } from "../spectro.js";
import { el, num, envelope, niceStep, ticks } from "../util.js";
import { LiveEngine, gainToDb } from "./engine.js";
import { loadIR, runClap, firstDelay } from "./irs.js";
import { FS, convolveOffline, peakOf, resample, spectrogram, wavBlob, makeClick, makeChirp, onsetIndex } from "./dsp.js";
import { lab, LAB_CMD, CLI_CMD } from "./lab.js";

const MAX_TAKES = 12, MAX_TAKE_S = 4;
const tierName = (t) => (t === "tier1" ? "Tier 1 full-wave" : "Tier 0 fast model");
const dB = (v, d = 0) => `${v >= 0 ? "+" : ""}${num(v, d)} dB`;

// ---------- the echo panel for a take: your sound at t = 0, its echo through the structure
class TakeEchoPanel extends TimePanel {
  constructor(host, win, clock) { super(host, "echo", "Echo of your sound", "select a take to see it here", win, clock); }
  setData(run, take, echo, firstEcho) { this.run = run; this.take = take; this.echoData = echo; this.firstEcho = firstEcho; this.ac.request(); }
  draw(ctx, w, h, C) {
    const win = this.win, font = getComputedStyle(document.body).fontFamily; ctx.font = `11px ${font}`;
    const step = niceStep((win.t1 - win.t0) * 1000, Math.max(3, w / 90)) / 1000;
    ctx.strokeStyle = C.grid; ctx.fillStyle = C.faint; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    for (const t of ticks(win.t0, win.t1, step)) { const x = Math.round(win.x(t, w)) + 0.5; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h - 14); ctx.stroke(); ctx.fillText(num(t * 1000, step < 0.001 ? 1 : 0), x, h); }
    const hh = h - 16, rowH = hh / 2, lane = (data, y0, col, label, drawnToCursor) => {
      const cy = y0 + rowH / 2, cols = Math.max(1, Math.floor(w)), { mn, mx } = envelope(data, FS, win.t0, win.t1, cols), pk = peakOf(data) || 1, a = (rowH / 2 - 4) / pk, xc = win.x(this.t, w);
      ctx.strokeStyle = C.line; ctx.beginPath(); ctx.moveTo(0, cy + 0.5); ctx.lineTo(w, cy + 0.5); ctx.stroke();
      for (let i = 0; i < cols; i++) { const on = !drawnToCursor || i <= xc; ctx.fillStyle = on ? col : C.faint; ctx.globalAlpha = on ? 1 : 0.35; ctx.fillRect(i, cy - mx[i] * a, 1, Math.max(1, (mx[i] - mn[i]) * a)); }
      ctx.globalAlpha = 1; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillStyle = C.dim; ctx.fillText(label, 8, y0 + 3);
    };
    if (!this.take) { ctx.fillStyle = C.dim; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = `13px ${font}`;
      ctx.fillText("Clap, press Record 2 s, or pick a sound: each one becomes a take you can replay here", w / 2, hh / 2); return; }
    lane(this.take.data, 0, C.text, "your sound, emitted at 0 ms", false);
    if (this.echoData) lane(this.echoData.data, rowH, C.accent, `echo at the listener, drawn ${num(-this.echoData.levelDb, 0)} dB larger than it is`, true);
    if (this.firstEcho != null) { const x = win.x(this.firstEcho, w); if (x > 0 && x < w) { ctx.fillStyle = C.faint; ctx.fillRect(Math.round(x), rowH, 1, rowH);
      ctx.textAlign = "left"; ctx.textBaseline = "bottom"; ctx.fillText("first post", x + 3, hh - 2); } }
    this.drawCursorAndMarker(ctx, w, hh, C, 0); this.markerLabel(ctx, w, hh - 18, C);
  }
}

export class LiveView {
  constructor(host, run, { clock, onTrackChange, switcher, reloadRuns, openRun, notify }) {
    Object.assign(this, { run, clock, onTrackChange, reloadRuns, openRun, notify });
    this.takes = LiveView.takes; this.sel = LiveView.sel; this.tier = run.audio.tier1 ? "tier1" : "tier0";
    this.root = el("div", { class: "liveview" }); host.append(this.root);
    const colA = el("div", { class: "col live-console" }), colB = el("div", { class: "col col-scene" }), colC = el("div", { class: "col live-time" });
    this.root.append(colA, colB, colC);
    this.engine = new LiveEngine({ onLevel: (l) => this._levels(l), onClap: () => this._flash(), onTake: (m) => this._takeFromMic(m), onDuck: () => this._ducked(), onState: () => this._syncStart() });
    this._buildConsole(colA);
    this.scene = new ScenePanel(colB, { onHover: (p) => this.echoP.setMarker(p) });
    this.win = new TimeWindow();
    this.echoP = new TakeEchoPanel(colC, this.win, clock);
    this.spectro = new SpectroPanel(colC, clock, { cells: [["target", "Target (what the structure was designed to say)"], ["echo", "Echo of your take", "Select a take"]], sub: "0 to 5 kHz, dB re each panel's max" });
    this.spectro.root.classList.add("two");
    this._buildTakes(colC);
    this._renderTakes(); this._syncStart();
    this.setRun(run);
  }

  // ---------------------------------------------------------------- console
  _buildConsole(host) {
    const p = el("section", { class: "panel console" }); host.append(p);
    const body = el("div", { class: "consolebody" }); p.append(body);
    this.howto = el("ol", { class: "howto" });
    this.honesty = el("p", { class: "honesty" });
    this.startBtn = el("button", { class: "listen", onclick: () => this.toggleListen() },
      this.meterFill = el("span", { class: "lfill" }), this.startLbl = el("span", { class: "llbl" }, "Start listening"));
    this.status = el("p", { class: "lstatus", role: "status", "aria-live": "polite" }, "Microphone off. Nothing is recorded until you press Start listening.");
    this.notice = el("p", { class: "lnotice", role: "alert", hidden: true });
    // response tier
    this.tierBtns = { tier1: el("button", { class: "seg", onclick: () => this.setTier("tier1") }, "Tier 1 full-wave"), tier0: el("button", { class: "seg", onclick: () => this.setTier("tier0") }, "Tier 0 fast") };
    this.irNote = el("p", { class: "irnote" });
    // echo level
    this.boost = el("input", { type: "range", min: 0, max: 80, step: 1, value: 0, "aria-label": "Echo level boost in dB", oninput: () => this._setBoost(+this.boost.value, true) });
    this.boostVal = el("span", { class: "boostval" });
    this.marks = el("div", { class: "marks" });
    this.trueNote = el("p", { class: "truenote" });
    // meters
    this.inMeter = el("i"); this.outMeter = el("i"); this.clapLed = el("span", { class: "led" }, "clap"); this.clipLed = el("span", { class: "led warnled" }, "limiting");
    this.latency = el("p", { class: "latency" });
    // headphones
    this.hpBtn = el("button", { class: "tool toggle", "aria-pressed": "false", onclick: () => this._setHeadphones(!this.engine.headphones) }, "Headphones");
    this.dry = el("input", { type: "range", min: -40, max: 0, step: 1, value: -6, "aria-label": "Your own sound in the headphones, dB", oninput: () => this._setHeadphones(true) });
    this.dryVal = el("span", { class: "dryval" }, "−6 dB");
    this.recBtn = el("button", { class: "tool rec", onclick: () => this.record() }, "Record 2 s");
    body.append(
      el("div", { class: "lhead" }, el("h2", {}, "Live"), el("span", { class: "sub" }, "clap at your computer, hear the structure answer")),
      this.howto, this.startBtn, this.status, this.notice,
      el("div", { class: "row meters" }, el("span", { class: "mlbl" }, "In"), el("div", { class: "meter" }, this.inMeter), this.clapLed),
      el("div", { class: "row meters" }, el("span", { class: "mlbl" }, "Out"), el("div", { class: "meter" }, this.outMeter), this.clipLed),
      this.latency,
      el("h3", {}, "Echo level"),
      el("div", { class: "boostrow" }, this.boost, this.boostVal), this.marks, this.trueNote,
      el("h3", {}, "Response"), el("div", { class: "segs" }, this.tierBtns.tier1, this.tierBtns.tier0), this.irNote,
      el("h3", {}, "Speakers or headphones"),
      el("div", { class: "row" }, this.hpBtn, el("label", { class: "dry" }, "your sound in them", this.dry, this.dryVal)),
      el("p", { class: "hint" }, "Speakers: you hear your real clap in the room and the speaker adds only the echo. Headphones block the room, so your own sound is mixed in; use them for boosts above about +40 dB, where speakers can feed back into the mic."),
      el("h3", {}, "Takes"), el("div", { class: "row" }, this.recBtn, el("span", { class: "hint" }, "or just clap: every detected clap becomes a take")),
      this.honesty);
    this._buildSources(body);
    this._buildDesign(body);
  }

  _buildSources(body) {
    this.file = el("input", { type: "file", accept: "audio/*,.wav,.mp3,.ogg,.flac,.m4a,.webm", hidden: true, onchange: () => { for (const f of this.file.files) this.addFile(f); this.file.value = ""; } });
    this.builtins = el("div", { class: "chips" });
    const drop = el("div", { class: "drop", tabindex: 0, role: "button", onclick: () => this.file.click(), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.file.click(); } } },
      el("strong", {}, "Use a sound file"), el("span", {}, "drop it here or choose one; any format the browser plays (first 4 s)"));
    for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
    for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, () => drop.classList.remove("over"));
    drop.addEventListener("drop", (e) => { e.preventDefault(); for (const f of e.dataTransfer.files) this.addFile(f); });
    body.append(el("h3", {}, "Sounds to send in"), drop, this.file, el("div", { class: "sublbl" }, "Built in"), this.builtins);
  }

  async _fillBuiltins() {
    const chips = [];
    const inp = await lab.inputs();
    const srcs = inp?.sources ?? [];
    if (srcs.length) for (const s of srcs) chips.push([s.name.replace(/\.wav$/, "").replace(/_/g, " "), async () => this.addUrl(lab.url(s.url), s.name)]);
    else chips.push(["this run's clap", async () => { const c = await runClap(this.run); if (!c) throw new Error("this run has no as_heard.wav"); return this.addTake(c.data, "clap (from this run)", "built-in"); }]);
    if (!srcs.some((x) => /click/i.test(x.name))) chips.push(["click", async () => this.addTake(makeClick(), "click", "built-in")]);
    if (!srcs.some((x) => /chirp/i.test(x.name))) chips.push(["chirp 0.5–4 kHz", async () => this.addTake(makeChirp(), "chirp 0.5–4 kHz, 50 ms", "built-in")]);
    this.builtins.replaceChildren(...chips.map(([label, fn]) => el("button", { class: "chip", onclick: async () => { try { await fn(); } catch (e) { this._notice(`Could not load ${label}: ${e.message}`); } } }, label)),
      el("span", { class: "hint" }, srcs.length ? "clap variants from inputs/sources/" : "claps from inputs/sources/ appear here when the lab server runs"));
  }

  _buildDesign(body) {
    this.design = el("section", { class: "design" }); body.append(el("h3", {}, "Design from a sound"), this.design);
  }
  _renderDesign() {
    const d = this.design; d.replaceChildren();
    if (!lab.present) {
      d.append(el("p", { class: "hint" }, "Turning a sound into a new structure needs the lab server, which is not running (this page is served statically). Start it from the repo root and reload:"),
        el("code", { class: "cmdline" }, LAB_CMD),
        el("p", { class: "hint" }, "or design from the command line:"), el("code", { class: "cmdline" }, CLI_CMD));
    } else {
      const file = el("input", { type: "file", accept: "audio/*,.wav", "aria-label": "Target sound file" });
      const name = el("input", { type: "text", placeholder: "name, e.g. snare", maxlength: 60, "aria-label": "Name for the new design" });
      const verify = el("input", { type: "checkbox" });
      const go = el("button", { class: "tool go" }, "Design it");
      const bar = el("div", { class: "bar", hidden: true }, el("i")), msg = el("p", { class: "hint", role: "status" });
      go.onclick = async () => {
        const f = file.files[0]; if (!f) { msg.textContent = "Choose the sound the structure should answer with."; return; }
        const nm = name.value.trim() || f.name.replace(/\.[^.]+$/, "");
        go.disabled = true; bar.hidden = false; msg.textContent = "Uploading";
        try {
          const { job_id } = await lab.design({ file: f, name: nm, tier1: verify.checked });
          await this._pollJob(job_id, bar, msg);
        } catch (e) { msg.textContent = `Design failed: ${e.message}`; }
        finally { go.disabled = false; }
      };
      d.append(el("div", { class: "row" }, file), el("div", { class: "row" }, name),
        el("label", { class: "row check" }, verify, "also verify on full-wave (slow, minutes to hours)"),
        el("div", { class: "row" }, go, el("span", { class: "hint" }, "fast model by default: under a minute; full-wave adds minutes to hours")), bar, msg);
      if (LiveView.designMsg) msg.textContent = LiveView.designMsg;
    }
    // custom runs, hide-from-view only
    const hidden = LiveView.hiddenCustom();
    const runs = (LiveView.allRuns ?? []).filter((r) => r.stage === "custom" && !hidden.has(r.path));
    if (runs.length) d.append(el("div", { class: "sublbl" }, "Your designs"), el("ul", { class: "customs" }, runs.map((r) => el("li", {},
      el("button", { class: "linkish", onclick: () => this.openRun(r) }, r.title ?? r.run_id),
      el("span", { class: r.verified ? "ok" : "unv" }, r.verified ? "verified on full-wave" : "fast model only, not verified"),
      el("button", { class: "tool x", title: "Hide from this list (the run stays on disk)", onclick: () => { hidden.add(r.path); LiveView.saveHidden(hidden); this._renderDesign(); } }, "Hide")))));
  }
  async _pollJob(id, bar, msg) {
    const t0 = performance.now();
    for (;;) {
      const j = await lab.job(id), el_s = Math.round((performance.now() - t0) / 1000);
      bar.firstChild.style.width = `${Math.round((j.progress ?? 0) * 100)}%`;
      msg.textContent = `${j.status === "queued" ? "queued" : `${Math.round((j.progress ?? 0) * 100)} %, ${j.stage ?? j.status}`}${j.message ? `: ${j.message}` : ""}${j.warnings?.length ? ` (${j.warnings.join("; ")})` : ""}, ${el_s < 60 ? `${el_s} s` : `${Math.floor(el_s / 60)} min ${el_s % 60} s`}`;
      if (j.status === "error") throw new Error(j.message ?? "the lab reported an error");
      if (j.status === "done") { bar.hidden = true;
        msg.textContent = LiveView.designMsg = `Done in ${el_s < 60 ? `${el_s} s` : `${Math.round(el_s / 60)} min`}${j.warnings?.length ? ` (${j.warnings.join("; ")})` : ""}: opened "${j.name ?? "the new design"}"${j.tier1 ? "" : " (fast model only, not verified)"}.`;
        await this.reloadRuns?.(j.run?.path); return; }
      await new Promise((r) => setTimeout(r, 500));
    }
  }

  _buildTakes(host) {
    const p = el("section", { class: "panel takes" });
    this.takeList = el("ul", { class: "takelist" });
    this.dlBtns = el("div", { class: "tools" });
    p.append(el("header", {}, el("h2", {}, "Takes"), el("span", { class: "sub", title: `Takes live in this tab's memory only (the newest ${MAX_TAKES}); download a WAV to keep one` }, `in memory only, newest ${MAX_TAKES}`), this.dlBtns), this.takeList);
    host.append(p);
  }

  // ---------------------------------------------------------------- run, tier, level
  async setRun(run) {
    this.run = run; this.clockRun = null;
    if (this.tier === "tier1" && !run.audio.tier1 && !run.manifest.ir?.tier1) this.tier = "tier0";
    this.scene.setRun(run);
    const has1 = !!run.audio.tier1 || !!run.manifest.ir?.tier1;
    this.tierBtns.tier1.disabled = !has1;
    this.firstEcho = firstDelay(run);
    // target spectrogram on the same grid as the take's echo
    this.targetSp = run.audio.target ? spectrogram(run.audio.target.data, run.audio.target.fs, { tEnd: Math.max(run.duration, 0.2) }) : null;
    if (!this.selTake()) this._idle();
    await this.setTier(this.tier, true);
    this._fillBuiltins(); this._renderDesign();
  }
  async setTier(t, force = false) {
    if (t === this.tier && !force) return;
    this.tier = t; for (const [k, b] of Object.entries(this.tierBtns)) { b.classList.toggle("on", k === t); b.setAttribute("aria-pressed", String(k === t)); }
    this.irNote.textContent = "Loading the impulse response"; this.ir = null;
    try {
      const run = this.run, ir = await loadIR(run, t); if (run !== this.run || t !== this.tier) return;
      this.ir = ir; await this.engine.setIR(ir);
      this.irNote.textContent = `${tierName(t)}: ${ir.note}.`;
      if (ir.unreliable) this.irNote.append(el("span", { class: "irwarn" }, ` Reconstructed from the stored echo; trustworthy only inside the clap's band${ir.band ? ` (${Math.round(ir.band[0])}–${Math.round(ir.band[1])} Hz)` : ""}.${t === "tier1" ? " Tier 0 is computed directly from the posts." : ""}`));
      this.irNote.classList.toggle("derived", ir.origin === "derived");
      this._levelUI(); this._latencyUI(); this._howto();
      if (this.selTake()) await this.select(this.selTake().id);
    } catch (e) { this.irNote.textContent = `No live echo for this run: ${e.message}.`; console.warn(e); }
  }
  // default boost: the clap's echo 12 dB under the clap (the listen/ pack's convention); never above +60
  defaultBoost() { const L = this.ir?.levelDb ?? -50; return Math.max(0, Math.min(60, Math.round(-L - 12))); }
  _levelUI() {
    const L = this.ir?.levelDb, def = this.defaultBoost(), max = Math.max(def + 12, 30);
    this.boost.max = String(max);
    if (this.userBoost == null || this.userBoost > max) this._setBoost(def, false); else this._setBoost(this.userBoost, false);
    const pos = (v) => `${(v / max) * 100}%`;
    this.marks.replaceChildren(el("span", { class: "mk", style: `left:${pos(0)}`, onclick: () => this._setBoost(0, true) }, "true level"),
      el("span", { class: "mk def", style: `left:${pos(def)}`, onclick: () => this._setBoost(def, true) }, `default ${dB(def)}`));
    this.trueNote.textContent = L == null ? "" : `At true level the echo is ${num(-L, 0)} dB below your clap (this run, ${tierName(this.tier)}); on laptop speakers that is usually inaudible. Anything above 0 dB is a boost, shown above.`;
  }
  _setBoost(db, user) {
    this.boost.value = String(db); if (user) this.userBoost = db;
    const L = this.ir?.levelDb;
    this.boostVal.replaceChildren(el("b", {}, db === 0 ? "true level" : `boosted ${dB(db)}`), L == null ? "" : el("small", {}, ` echo ${num(-(L + db), 0)} dB under your clap`));
    this.boostVal.classList.toggle("hot", db > 40);
    this.engine.setBoost(db); this._howto();
    if (this.selTake() && user) this._mixTrack();
  }
  _setHeadphones(on) {
    this.engine.setHeadphones(on, +this.dry.value); this.dryVal.textContent = `${num(+this.dry.value, 0)} dB`;
    this.hpBtn.classList.toggle("on", on); this.hpBtn.setAttribute("aria-pressed", String(on));
  }
  _howto() {
    const b = +this.boost.value;
    this.howto.replaceChildren(el("li", {}, "Press Start listening and allow the microphone."), el("li", {}, "Clap once, near the computer."),
      el("li", {}, `Hear the structure answer from the speaker, boosted by ${num(b, 0)} dB; use headphones for loud settings.`));
    const L = this.ir?.levelDb;
    this.honesty.textContent = `What you hear is the simulated response of the selected structure to your sound. A real structure's echo would be far quieter than your clap${L != null ? ` (true level: ${num(L, 0)} dB)` : ""}.`;
  }

  // ---------------------------------------------------------------- microphone
  async toggleListen() {
    if (this.engine.running) { this.engine.stop(); return; }
    this._notice(null); this.startLbl.textContent = "Starting";
    try {
      const rate = +new URLSearchParams(location.search).get("liverate") || null;
      await this.engine.start({ rate });
      this._setBoost(+this.boost.value, false); this._setHeadphones(this.engine.headphones);
      this._latencyUI();
      // output latency settles after the first callbacks: re-trim once
      setTimeout(async () => { if (this.engine.running) { await this.engine._loadConv(); this._latencyUI(); } }, 600);
    } catch (e) { this._notice(e.userMessage ?? `Could not start: ${e.message}`); if (!e.userMessage) console.warn(e); this.engine.stop(); }
    this._syncStart();
  }
  _syncStart() {
    const on = this.engine.running; this.startBtn.classList.toggle("on", on); this.startBtn.setAttribute("aria-pressed", String(on));
    this.startLbl.textContent = on ? "Listening: clap now (press to stop)" : "Start listening";
    this.status.textContent = on ? `Microphone on at ${this.engine.ctx?.sampleRate ?? "?"} Hz. The speaker plays only the echo.` : "Microphone off. Nothing is recorded until you press Start listening.";
    this.recBtn.disabled = !on; if (!on) { this.inMeter.style.width = "0"; this.outMeter.style.width = "0"; }
    this._latencyUI();
  }
  _latencyUI() {
    const l = this.engine.latency(), ir = this.ir; if (!l || !ir) { this.latency.textContent = ir ? `First echo ${num((this.firstEcho - ir.tDirect) * 1000, 1)} ms after you hear your clap.` : ""; return; }
    const lat = l.total * 1000, full = this.engine.trimS >= this.engine.wantTrimS - 1e-4;
    const unk = !l.known.input ? ", input latency not reported" : "";
    this.latency.textContent = `System latency ~${num(lat, 0)} ms (${l.known.output ? "" : "output not reported, "}base ${num(l.base * 1000, 0)}, out ${num(l.output * 1000, 0)}, in ${num(l.input * 1000, 0)}${unk}): ` +
      (full ? "compensated" : `partly compensated, echo about ${num((this.engine.wantTrimS - this.engine.trimS) * 1000, 0)} ms late`) +
      `. First echo ${num((this.firstEcho - ir.tDirect) * 1000, 1)} ms after your clap.`;
    this.latency.classList.toggle("warn", !full);
  }
  _levels(l) {
    const w = (v) => `${Math.max(0, Math.min(100, (1 + gainToDb(v) / 60) * 100))}%`;
    if (l.inPeak != null) this.inMeter.style.width = w(l.inPeak);
    if (l.outPeak != null) { this.outMeter.style.width = w(l.outPeak); this.clipLed.classList.toggle("on", l.limiting); this.meterFill.style.width = this.inMeter.style.width; }
  }
  _flash() { this.clapLed.classList.remove("on"); void this.clapLed.offsetWidth; this.clapLed.classList.add("on"); this.startBtn.classList.remove("clap"); void this.startBtn.offsetWidth; this.startBtn.classList.add("clap"); }
  _ducked() { this._notice("The echo kept sounding without a new clap, which is the speaker feeding back into the microphone: echo turned down by 18 dB. Lower the level or use headphones; moving the slider restores it."); }
  _notice(s) { this.notice.hidden = !s; this.notice.textContent = s ?? ""; }
  record() { if (!this.engine.running) return; this.engine.record(2); this.recBtn.textContent = "Recording"; setTimeout(() => { this.recBtn.textContent = "Record 2 s"; }, 2050); }

  // ---------------------------------------------------------------- takes
  async _takeFromMic(m) {
    let d = await resample(m.data, m.fs, FS);
    const on = Math.round(m.onset * FS / m.fs);
    // a detected clap starts 1 ms before its onset and loses its silent tail; a recording is kept whole
    d = m.reason === "clap" ? trimTail(d.subarray(Math.max(0, on - 16))) : d.slice(on);
    await this.addTake(d, m.reason === "clap" ? "clap" : "recording", "mic");
  }
  async addFile(f, kind = "file") {
    try {
      const buf = await f.arrayBuffer(), ab = await new OfflineAudioContext(1, 1, FS).decodeAudioData(buf);
      const n = Math.min(ab.length, MAX_TAKE_S * FS), d = new Float32Array(n);
      for (let c = 0; c < ab.numberOfChannels; c++) { const x = ab.getChannelData(c); for (let i = 0; i < n; i++) d[i] += x[i] / ab.numberOfChannels; }
      const s = Math.max(0, onsetIndex(d, 0.02) - 16);
      await this.addTake(trimTail(d.subarray(s)), f.name.replace(/\.[^.]+$/, ""), kind, ab.length > n ? `trimmed to ${MAX_TAKE_S} s` : null);
    } catch (e) { this._notice(`Could not use ${f.name}: the browser could not decode it (${e.message ?? e}).`); }
  }
  async addUrl(url, name) {
    const r = await fetch(url); if (!r.ok) throw new Error(`${r.status}`);
    return this.addFile(new File([await r.arrayBuffer()], name), "built-in");
  }
  async addTake(data, name, kind, note = null) {
    const pk = peakOf(data); if (!(pk > 0)) { this._notice("That sound is silent."); return; }
    const n = (LiveView.counter = (LiveView.counter ?? 0) + 1);
    const take = { id: `t${n}`, name: `${name} ${n}`, kind, data: Float32Array.from(data), note, created: new Date(), echoes: new Map(), dur95: energyDuration(data) };
    this.takes.unshift(take);
    while (this.takes.length > MAX_TAKES) this.takes.pop();
    this._renderTakes(); await this.select(take.id);
  }
  selTake() { return this.takes.find((t) => t.id === LiveView.sel); }
  async echoOf(take) {
    if (!this.ir) return null;
    const k = this.ir.key; if (!take.echoes.has(k)) {
      const data = await convolveOffline(take.data, this.ir.data, FS);
      take.echoes.clear(); // one cached echo per take: memory stays bounded
      take.echoes.set(k, { data, levelDb: gainToDb(peakOf(data) / peakOf(take.data)) });
    }
    return take.echoes.get(k);
  }
  async select(id) {
    LiveView.sel = id; const take = this.selTake(); this._renderTakes(); if (!take) return;
    const echo = await this.echoOf(take); if (LiveView.sel !== id) return;
    this.echo = echo;
    const dur = Math.min(3, Math.max(this.run.duration, (take.data.length + (this.ir?.data.length ?? 0)) / FS));
    this.duration = dur;
    this.win.reset([0, dur]);
    this.echoP.subEl.textContent = `${take.name}, ${num(take.dur95 * 1000, take.dur95 < 0.01 ? 1 : 0)} ms of sound, ${this.ir ? tierName(this.ir.tier) : "no response"}`;
    this.echoP.setData(this.run, take, echo ? { ...echo } : null, this.firstEcho);
    this.scene.setPulse(take.dur95);
    // spectrograms: target and the take's echo on one grid
    const es = echo ? spectrogram(echo.data, FS, { tEnd: dur }) : null, ts = this.targetSp;
    const T = es?.times_s ?? ts?.times_s ?? [];
    const pad = (p) => p && p.map((row) => Array.from({ length: T.length }, (_, i) => row[i] ?? -60));
    this.spectro.setRun({ spectro: { freqs_hz: (es ?? ts)?.freqs_hz ?? [0, 5000], times_s: T, db_floor: -60, panels: { target: pad(ts?.panel), echo: es?.panel ?? null } }, duration: dur });
    this._mixTrack();
  }
  // replay audio: the take at the direct arrival, plus the echo at the chosen boost
  _mixTrack() {
    const take = this.selTake(), echo = this.echo; if (!take) return;
    const g = 10 ** (+this.boost.value / 20), td = Math.round((this.ir?.tDirect ?? 0.000875) * FS), n = Math.round(this.duration * FS);
    const mix = new Float32Array(n), echoB = new Float32Array(n), dry = new Float32Array(n);
    for (let i = 0; i < take.data.length && i + td < n; i++) { dry[i + td] = take.data[i]; }
    if (echo) for (let i = 0; i < echo.data.length && i < n; i++) echoB[i] = echo.data[i] * g;
    for (let i = 0; i < n; i++) mix[i] = dry[i] + echoB[i];
    const pk = Math.max(1, peakOf(mix)); // never clip the replay: scale down together (relative level kept)
    if (pk > 1) for (const a of [mix, echoB, dry]) for (let i = 0; i < n; i++) a[i] /= pk * 1.12;
    this.tracks = { mix: { fs: FS, data: mix }, echo: { fs: FS, data: echoB }, take: { fs: FS, data: dry } };
    this.onTrackChange?.({ duration: this.duration });
  }
  track(kind) { return this.tracks?.[kind] ?? null; }
  // no take yet: empty echo panel with its invitation, the target spectrogram alone
  _idle() {
    this.tracks = null; this.scene.setPulse(null); this.duration = this.run.duration; this.win.reset([0, this.run.duration]);
    this.echoP.subEl.textContent = "select a take to see it here"; this.echoP.setData(this.run, null, null, null);
    const ts = this.targetSp; this.spectro.setRun({ spectro: ts ? { freqs_hz: ts.freqs_hz, times_s: ts.times_s, db_floor: -60, panels: { target: ts.panel, echo: null } } : null, duration: this.run.duration });
  }
  _renderTakes() {
    const sel = LiveView.sel;
    if (!this.takes.length) { this.takeList.replaceChildren(el("li", { class: "empty" }, "No takes yet. Clap with the microphone on, press Record 2 s, or use a sound file.")); this.dlBtns.replaceChildren(); return; }
    this.takeList.replaceChildren(...this.takes.map((t) => {
      const name = el("span", { class: "tname", title: "Double-click to rename" }, t.name);
      name.ondblclick = (e) => { e.stopPropagation(); this.rename(t); };
      return el("li", { class: t.id === sel ? "on" : "", tabindex: 0, onclick: () => this.select(t.id), onkeydown: (e) => { if (e.key === "Enter") this.select(t.id); } },
        el("span", { class: `tkind ${t.kind}` }, t.kind === "mic" ? "mic" : t.kind === "file" ? "file" : "built-in"), name,
        el("span", { class: "tlen", title: `${num(t.data.length / FS * 1000, 0)} ms kept` }, `${num(t.dur95 * 1000, t.dur95 < 0.01 ? 1 : 0)} ms`), t.note ? el("span", { class: "tnote" }, t.note) : null,
        el("button", { class: "tool", title: "Rename", onclick: (e) => { e.stopPropagation(); this.rename(t); } }, "Rename"),
        el("button", { class: "tool", title: "Delete this take", onclick: (e) => { e.stopPropagation(); this.remove(t); } }, "Delete"));
    }));
    const t = this.selTake();
    this.dlBtns.replaceChildren(...(t ? [["take", "Take"], ["echo", "Echo (true level)"], ["mix", "Take + echo (boosted)"]].map(([k, l]) => el("button", { class: "tool", title: `Download ${l.toLowerCase()} as a 16 kHz WAV`, onclick: () => this.download(t, k) }, l)) : []));
    if (t) this.dlBtns.prepend(el("span", { class: "dlbl" }, "Download"));
  }
  rename(t) { const n = prompt("Name for this take", t.name); if (n?.trim()) { t.name = n.trim(); this._renderTakes(); if (t.id === LiveView.sel) this.select(t.id); } }
  remove(t) { const i = this.takes.indexOf(t); if (i >= 0) this.takes.splice(i, 1); if (LiveView.sel === t.id) { LiveView.sel = this.takes[0]?.id ?? null; } this._renderTakes(); if (LiveView.sel) this.select(LiveView.sel); else { this._idle(); this.onTrackChange?.({ duration: this.run.duration }); } }
  async download(t, kind) {
    const echo = await this.echoOf(t), safe = t.name.replace(/[^\w.-]+/g, "_"), run = this.run.entry.run_id;
    let data = t.data, suffix = "take";
    if (kind === "echo") { data = echo.data; suffix = `echo_true_level_${this.ir.tier}_${run}`; }
    if (kind === "mix") { data = this.tracks.mix.data; suffix = `take_plus_echo_boost${+this.boost.value}dB_${this.ir.tier}_${run}`; }
    const a = el("a", { href: URL.createObjectURL(wavBlob(data, FS)), download: `${safe}_${suffix}.wav` }); document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ---------------------------------------------------------------- shared timeline
  setTime(t, playing, speed) { this.scene.setTime(t, playing, speed); this.echoP.setTime(t); this.spectro.setTime(t); }
  destroy() { this.engine.stop(); this.scene.destroy(); this.root.remove(); }

  static hiddenCustom() { try { return new Set(JSON.parse(localStorage.getItem("echo.hiddenCustom") ?? "[]")); } catch { return new Set(); } }
  static saveHidden(s) { try { localStorage.setItem("echo.hiddenCustom", JSON.stringify([...s])); } catch { /* storage unavailable */ } }
}
LiveView.takes = []; LiveView.sel = null;

// drop the silent tail: keep up to 30 ms past the last sample within 50 dB of the peak, at least 40 ms
function trimTail(d) {
  const th = peakOf(d) * 10 ** (-50 / 20); let e = d.length - 1; while (e > 0 && Math.abs(d[e]) < th) e--;
  return Float32Array.from(d.subarray(0, Math.min(d.length, Math.max(e + Math.round(0.03 * FS), Math.round(0.04 * FS)))));
}

// how long the sound is: the span holding the central 95 % of its energy (seconds)
function energyDuration(d) {
  let tot = 0; for (let i = 0; i < d.length; i++) tot += d[i] * d[i];
  let acc = 0, a = 0, b = d.length - 1;
  for (let i = 0; i < d.length; i++) { acc += d[i] * d[i]; if (acc >= 0.025 * tot) { a = i; break; } }
  acc = 0; for (let i = d.length - 1; i >= 0; i--) { acc += d[i] * d[i]; if (acc >= 0.025 * tot) { b = i; break; } }
  return Math.max(1, b - a + 1) / FS;
}
