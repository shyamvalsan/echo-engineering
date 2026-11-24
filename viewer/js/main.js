// App shell: run switcher, compare mode, transport (one clock for picture and sound).
import WaveSurfer from "../vendor/wavesurfer.esm.js";
import { Clock } from "./clock.js";
import { loadIndex, loadRun } from "./data.js";
import { RunView } from "./runview.js";
import { AutoCanvas, colors, el, niceStep, ticks, num } from "./util.js";

const params = new URLSearchParams(location.search);
const SPEEDS = [{ v: 1, label: "Real time" }, { v: 0.1, label: "10× slower" }, { v: 0.02, label: "50× slower" }];
const STAGE_NAMES = { s1_bird: "1 Bird note", s2_motif: "2 Motif", s3_melody: "3 Melody", s4_speech: "4 Speech",
  s4a_vowel: "4a Vowel", s4b_syllables: "4b Syllables", s4c_word: "4c Word" };
const words = (s) => s.replace(/[_-]+/g, " ").trim().replace(/^./, (c) => c.toUpperCase());
function stageName(s) {
  if (STAGE_NAMES[s]) return STAGE_NAMES[s];
  if (s.startsWith("build_")) return `Build pilot: ${words(s.slice(6)) || "unnamed"}`;
  const m = /^s(\d+)([a-z]?)_(.+)$/.exec(s); if (m) return `${m[1]}${m[2]} ${words(m[3])}`;
  return words(s);
}
// stages in run order, then build pilots, then anything else
const stageRank = (s) => { const m = /^s(\d+)([a-z]?)_/.exec(s); return m ? +m[1] * 10 + (m[2] ? m[2].charCodeAt(0) - 96 : 0) : s.startsWith("build_") ? 1000 : 2000; };
// default run of a stage: the newest final run, else the newest run (index is newest first)
const defaultRun = (runs) => runs.find((r) => r.status === "final") ?? runs[0];
const hhmm = (iso) => { const m = /T(\d\d:\d\d)/.exec(iso ?? ""); return m ? m[1] : ""; };

const state = { base: null, runs: [], a: null, b: null, views: [], kind: "as_heard", side: 0, cache: new Map() };
const clock = new Clock();
const $ = (id) => document.getElementById(id);

async function getRun(entry) {
  if (!state.cache.has(entry.path)) state.cache.set(entry.path, loadRun(state.base, entry));
  return state.cache.get(entry.path);
}

// ---------- header: stage and run switchers
function fillSwitcher(stageSel, runSel, current, onPick) {
  const stages = [...new Set(state.runs.map((r) => r.stage))].sort((a, b) => stageRank(a) - stageRank(b) || a.localeCompare(b));
  stageSel.replaceChildren(...stages.map((s) => el("option", { value: s, selected: s === current.stage }, stageName(s))));
  const runsOf = (s) => state.runs.filter((r) => r.stage === s);
  const fillRuns = (s, sel) => runSel.replaceChildren(...runsOf(s).map((r) => el("option", { value: r.path, selected: r.path === sel, title: r.path },
    `${r.title ?? r.run_id}, ${r.status === "intermediate" ? "intermediate" : !r.verified ? "unverified" : r.passed ? "passed" : "failed"}${hhmm(r.created) ? `, ${hhmm(r.created)}` : ""}`)));
  fillRuns(current.stage, current.path);
  stageSel.onchange = () => { const r = defaultRun(runsOf(stageSel.value)); fillRuns(stageSel.value, r.path); onPick(r); };
  runSel.onchange = () => onPick(state.runs.find((r) => r.path === runSel.value));
}

// ---------- transport
const transport = {
  ws: null,
  build() {
    const speedBox = $("speeds"), kindBox = $("kinds");
    speedBox.replaceChildren(...SPEEDS.map((s) => el("button", { class: "seg", "data-v": s.v, onclick: () => { clock.setSpeed(s.v); this.sync(); } }, s.label)));
    const kinds = [["target", "Target"], ["echo", "Echo"], ["as_heard", "As heard"]];
    kindBox.replaceChildren(...kinds.map(([k, label]) => el("button", { class: "seg", "data-k": k, title: `Play the ${label.toLowerCase()} audio from the start`,
      onclick: () => { state.kind = k; setTrack(); clock.seek(0); clock.play(); this.sync(); } }, label)));
    $("play").onclick = () => clock.toggle();
    $("pitch").onclick = () => { clock.setMuted(false); this.sync(); };
    $("mute").onclick = () => { clock.setMuted(true); this.sync(); };
    this.ticks = new AutoCanvas($("ticks"), (ctx, w, h) => this.drawTicks(ctx, w, h));
  },
  sync() {
    for (const b of $("speeds").children) { const on = +b.dataset.v === clock.speed; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }
    for (const b of $("kinds").children) { const on = b.dataset.k === state.kind; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }
    $("pitch").classList.toggle("on", !clock.muted); $("mute").classList.toggle("on", clock.muted);
    $("pitch").setAttribute("aria-pressed", String(!clock.muted)); $("mute").setAttribute("aria-pressed", String(clock.muted));
    $("play").textContent = clock.playing ? "Pause" : "Play"; $("play").classList.toggle("on", clock.playing);
    const sideBox = $("sides"); sideBox.hidden = state.views.length < 2;
    for (const b of sideBox.querySelectorAll("button")) { const on = +b.dataset.s === state.side; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }
  },
  setOverview(track, duration) {
    this.ws?.destroy(); this.ws = null;
    const host = $("overview"); host.replaceChildren();
    if (!track) return;
    // level-compressed envelope (60 dB range) so a quiet echo is visible next to the direct clap
    const n = 3000, d = track.data, pk = d.reduce((m, v) => Math.max(m, Math.abs(v)), 1e-12), out = new Float32Array(n), len = Math.round(duration * track.fs);
    for (let i = 0; i < n; i++) { const a = Math.floor(i / n * len), b = Math.max(a + 1, Math.floor((i + 1) / n * len)); let m = 0;
      for (let j = a; j < b && j < d.length; j++) m = Math.max(m, Math.abs(d[j])); const db = 20 * Math.log10(m / pk + 1e-12);
      out[i] = (i % 2 ? -1 : 1) * Math.max(0, 1 + db / 60); }
    const C = colors();
    this.ws = WaveSurfer.create({ container: host, height: 34, peaks: [out], duration, normalize: false, waveColor: C.faint, progressColor: C.dim,
      cursorColor: C.accent, cursorWidth: 1, interact: true, dragToSeek: true, hideScrollbar: true, autoScroll: false });
    this.ws.on("interaction", (t) => clock.seek(t));
    this.ws.setTime(clock.t);
  },
  drawTicks(ctx, w, h) {
    const C = colors(), d = clock.duration, font = getComputedStyle(document.body).fontFamily, step = niceStep(d * 1000, w / 70) / 1000;
    ctx.font = `10px ${font}`; ctx.fillStyle = C.faint; ctx.strokeStyle = C.faint; ctx.textBaseline = "top";
    for (const t of ticks(0, d, step)) { const x = Math.round(t / d * w) + 0.5; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 3); ctx.stroke();
      ctx.textAlign = x < 10 ? "left" : x > w - 20 ? "right" : "center"; ctx.fillText(`${num(t * 1000, step < 0.001 ? 1 : 0)}`, x, 4); }
    // echo window of the first run: from the nearest to the farthest post
    const run = state.views[state.side]?.run, wd = run?.scene?.wedge;
    if (wd) { const x0 = 2 * wd.r_min / run.c / d * w, x1 = Math.min(w, 2 * wd.r_max / run.c / d * w);
      ctx.fillStyle = C.accent; ctx.globalAlpha = 0.5; ctx.fillRect(x0, 0, x1 - x0, 1.5); ctx.globalAlpha = 1; }
  },
  time(t) {
    this.ws?.setTime(t);
    $("tnow").textContent = num(t * 1000, 2);
    const run = state.views[0]?.run, f = run?.manifest.field;
    $("tsub").textContent = `of ${num(clock.duration * 1000, 1)} ms${f ? `, field frame ${Math.max(1, Math.min(f.n_frames, Math.floor((t - f.t0_s) / f.sim_seconds_per_frame) + 1))}` : ""}`;
  },
};

function setTrack() {
  const v = state.views[state.side] ?? state.views[0];
  const tr = v?.track(state.kind) ?? null;
  clock.setTrack(tr);
  transport.setOverview(tr, clock.duration);
  transport.sync();
}

// ---------- layout
async function show() {
  const main = $("main"); clock.pause();
  for (const v of state.views) v.destroy(); state.views = [];
  main.classList.toggle("compare", !!state.b);
  $("loading").hidden = false;
  try {
    const runs = await Promise.all([state.a, state.b].filter(Boolean).map(getRun));
    clock.setDuration(Math.max(...runs.map((r) => r.duration)));
    if (state.side >= runs.length) state.side = 0;
    state.views = runs.map((r, i) => new RunView(main, r, { clock, compact: runs.length > 1, side: runs.length > 1 ? (i ? "Right" : "Left") : null, onTrackChange: setTrack }));
    document.title = `${runs.map((r) => r.manifest.title ?? r.entry.run_id).join(" vs ")} — Composed Echo`;
    setTrack(); transport.ticks.request(); onTime(); runInfo();
    const u = new URL(location.href); u.searchParams.set("run", state.a.path);
    if (state.b) u.searchParams.set("compare", state.b.path); else u.searchParams.delete("compare");
    history.replaceState(null, "", u);
  } catch (e) {
    main.append(el("p", { class: "fatal" }, `Could not load the run: ${e.message}. Check that the folder holds manifest.json.`)); console.warn(e);
  } finally { $("loading").hidden = true; }
}

function runInfo() {
  const v = state.views[state.side] ?? state.views[0], m = v?.run.manifest;
  $("cmdBox").hidden = !m?.command; $("cmd").textContent = m?.command ?? "";
  const lv = m?.audio?.as_heard_echo_level_db;
  $("truelevel").textContent = lv == null ? "" : `as heard at true level: echo ${num(-lv, 0)} dB below the clap`;
}

function onTime() { const t = clock.t; for (const v of state.views) v.setTime(t); transport.time(t); }
let wasPlaying = null;
clock.on(() => { onTime(); if (wasPlaying !== clock.playing) { wasPlaying = clock.playing; transport.sync(); } });

function setupCompare() {
  const btn = $("compare"), box = $("compareBox");
  const sync = () => { btn.classList.toggle("on", !!state.b); btn.setAttribute("aria-pressed", String(!!state.b)); box.hidden = !state.b; };
  btn.onclick = () => {
    if (state.b) state.b = null;
    else state.b = state.runs.find((r) => r.path !== state.a.path && r.stage === state.a.stage) ?? state.runs.find((r) => r.path !== state.a.path) ?? state.a;
    if (state.b) fillSwitcher($("stageB"), $("runB"), state.b, (r) => { state.b = r; show(); });
    sync(); show();
  };
  sync();
  for (const b of $("sides").querySelectorAll("button")) b.onclick = () => { state.side = +b.dataset.s; setTrack(); transport.ticks.request(); runInfo(); };
  $("copy").onclick = async () => {
    const txt = $("cmd").textContent;
    try { await navigator.clipboard.writeText(txt); $("copy").textContent = "Copied"; }
    catch { const r = document.createRange(); r.selectNodeContents($("cmd")); getSelection().removeAllRanges(); getSelection().addRange(r); $("copy").textContent = "Selected"; }
    setTimeout(() => { $("copy").textContent = "Copy"; }, 1500);
  };
}

function keys() {
  window.addEventListener("keydown", (e) => {
    if (e.target.closest("select, input")) return;
    const f = state.views[0]?.run.manifest.field, step = (f ? f.sim_seconds_per_frame : 0.0005) * (e.shiftKey ? 10 : 1);
    if (e.code === "Space") { e.preventDefault(); clock.toggle(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); clock.pause(); clock.seek(clock.t + step); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); clock.pause(); clock.seek(clock.t - step); }
    else if (e.key === "Home") clock.seek(0);
    else if (["1", "2", "3"].includes(e.key)) { clock.setSpeed(SPEEDS[+e.key - 1].v); transport.sync(); }
  });
}

async function boot() {
  transport.build(); setupCompare(); keys();
  const sp = +params.get("speed"); clock.speed = SPEEDS.some((s) => s.v === sp) ? sp : 0.1; transport.sync();
  const idx = await loadIndex(params.get("runs") ?? "../runs");
  state.base = idx.base; state.runs = idx.runs;
  $("source").textContent = idx.fallback ? `Fixture data: no runs in ${idx.requested}/index.json yet` : idx.base === "fixtures/runs" ? "Fixture data" : "";
  $("source").title = `Runs read from ${idx.base}/index.json`;
  $("source").classList.toggle("warn", idx.base === "fixtures/runs");
  if (!state.runs.length) { $("loading").hidden = true; $("main").append(el("p", { class: "fatal" }, `No runs found. Run a stage (for example uv run python -m stages.s1_bird) to write ${idx.base}/index.json, or open ?runs=fixtures/runs.`)); return; }
  const find = (p) => state.runs.find((r) => r.path === p);
  state.a = find(params.get("run")) ?? defaultRun(state.runs);
  state.b = params.get("compare") ? find(params.get("compare")) ?? null : null;
  fillSwitcher($("stage"), $("run"), state.a, (r) => { state.a = r; show(); });
  if (state.b) { fillSwitcher($("stageB"), $("runB"), state.b, (r) => { state.b = r; show(); }); }
  $("compare").classList.toggle("on", !!state.b); $("compareBox").hidden = !state.b;
  const t = +params.get("t"); await show(); if (t > 0) clock.seek(t);
}
boot();
window.__echo = { clock, state };
