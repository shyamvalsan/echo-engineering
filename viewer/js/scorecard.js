// Scorecard: verdict, the two feasibility numbers large, each metric against its threshold,
// robustness below. Every number shown comes from metrics.json as written by the run.
import { el, num } from "./util.js";

const CMP = { "<=": "≤", ">=": "≥", "==": "=" };
const dec = (v) => (v == null ? 0 : Number.isInteger(v) ? 0 : Math.abs(v) < 10 ? 2 : Math.abs(v) < 100 ? 1 : 0);
const unitStr = (u) => (u ? (u === "%" ? "\u2009%" : ` ${u}`) : "");
// null = the judge returned nothing (e.g. a formant not found); strings and booleans are shown as given
const withUnit = (v, u) => (v == null ? "not found" : typeof v === "number" ? (Number.isFinite(v) ? `${num(v, dec(v))}${unitStr(u)}` : "not found")
  : typeof v === "boolean" ? (v ? "yes" : "no") : String(v));
const thrUnit = (v, u) => (v == null ? "\u2014" : withUnit(v, u));

// Tier 1 results say pass/fail in colour; Tier 0 or unverified results only "meets"/"misses".
function markFor(pass, provisional) {
  if (pass == null) return el("span", { class: "info" }, "info");
  if (provisional) return el("span", { class: "prov", title: "Tier 0 result, not a pass" }, pass ? "meets" : "misses");
  return el("span", { class: pass ? "pass" : "fail" }, pass ? "pass" : "fail");
}

// long failure text: first two clauses visible, the rest one click away
function longText(cls, text) {
  const parts = String(text).split(/;\s+/);
  if (text.length < 260 || parts.length < 3) return el("p", { class: cls }, text);
  return el("div", { class: cls }, el("p", {}, parts.slice(0, 2).join("; ") + ";"),
    el("details", {}, el("summary", {}, `${parts.length - 2} more clauses`), el("p", {}, parts.slice(2).join("; "))));
}

export function verdictOf(run, metrics = run.metrics) {
  const m = run.manifest, verified = (metrics?.verified ?? m.verified) && m.status !== "tier0_only";
  if (!verified) return { cls: "unverified", text: "UNVERIFIED — Tier 0 only" };
  // custom designs have no pass condition: say so instead of "failed"
  if (metrics && !metrics.passed && !(metrics.metrics ?? []).some((x) => x.gating) && !metrics.criteria) return { cls: "basis", text: "Verified on Tier 1, no pass criterion" };
  if (metrics?.passed) return { cls: "pass", text: metrics.fragile ? "Passed on Tier 1, fragile" : "Passed on Tier 1" };
  return { cls: "fail", text: metrics?.fragile ? "Failed on Tier 1, fragile" : "Failed on Tier 1" };
}

export class ScorePanel {
  constructor(host, { compact = false } = {}) {
    this.compact = compact;
    this.root = el("section", { class: "panel score" + (compact ? " compact" : "") });
    this.verdict = el("span", { class: "verdict" });
    this.root.append(el("header", {}, el("h2", {}, "Scorecard"), el("div", { class: "tools" }, this.verdict)));
    this.body = el("div", { class: "scorebody" }); this.root.append(this.body); host.append(this.root);
  }
  setRun(run, metrics = run.metrics, note = null) {
    this.dir = run.dir;
    const v = verdictOf(run, metrics); this.verdict.className = `verdict ${v.cls}`; this.verdict.textContent = v.text;
    const b = this.body; b.replaceChildren();
    if (note) b.append(el("p", { class: "iternote" }, note));
    // Unverified runs never show a pass: Tier 0 results read "meets" / "misses", in neutral colours.
    const unverified = v.cls === "unverified";
    if (unverified) b.append(el("p", { class: "unvnote" }, "Tier 0 only: numbers from the fast single-scattering model. A stage passes only on the full-wave Tier 1 solver, which has not run on this design."));
    if (!metrics) { b.append(el("p", { class: "empty" }, "This run has no metrics.json yet.")); return; }
    const trio = verdicts(metrics);
    if (trio) { b.append(...trio); // the header stamp then states only what the numbers rest on, not a verdict
      this.verdict.className = `verdict ${v.cls === "unverified" ? "unverified" : "basis"}`; this.verdict.textContent = v.cls === "unverified" ? v.text : "Verified on Tier 1"; }
    const H = metrics.headline ?? {};
    const spl = H.echo_spl_db, quiet = H.likely_inaudible_on_site ?? (spl != null && spl < 35);
    b.append(el("div", { class: "headline" },
      el("div", { class: "big" }, el("div", { class: "num" }, num(H.echo_level_db_re_direct, 1), el("small", {}, "dB")),
        el("div", { class: "lbl" }, "echo re direct clap"),
        el("div", { class: "aux" + (quiet ? " warn" : "") }, spl == null ? "" : `${num(spl, 1)} dB SPL on site${quiet ? ", likely inaudible" : ""}`)),
      el("div", { class: "big" }, el("div", { class: "num" }, num(H.depth_m, 1), el("small", {}, "m")),
        el("div", { class: "lbl" }, "structure depth"),
        el("div", { class: "aux" }, H.post_count == null ? "" : `${H.post_count.toLocaleString("en-US")} posts`))));
    b.append(el("dl", { class: "facts" },
      el("dt", {}, "Tier gap"), el("dd", {}, H.tier_gap_db == null ? "no Tier 1" : `${num(H.tier_gap_db, 1)} dB`),
      el("dt", {}, "Raw 3D level"), el("dd", {}, H.echo_level_db_re_direct_raw3d == null ? "—" : `${num(H.echo_level_db_re_direct_raw3d, 1)} dB`),
      el("dt", {}, "Wedge filled"), el("dd", {}, H.fill_fraction == null ? "—" : `${num(H.fill_fraction * 100, 2)} %`)));
    if (metrics.failure_cause) b.append(longText("cause", metrics.failure_cause));
    if (metrics.failure_mechanism) b.append(longText("mechanism", typeof metrics.failure_mechanism === "string" ? metrics.failure_mechanism : JSON.stringify(metrics.failure_mechanism)));
    if (metrics.diagnosis) b.append(el("details", { class: "caveats" }, el("summary", {}, "Diagnosis"),
      el("p", { class: "diag" }, typeof metrics.diagnosis === "string" ? metrics.diagnosis : metrics.diagnosis.what ?? ""),
      el("a", { href: `${this.dir}/metrics.json`, target: "_blank", rel: "noopener" }, "Full diagnosis in metrics.json")));
    // stage 4c: the recognizer's transcript per clap
    if (Array.isArray(metrics.recognized_text) && metrics.recognized_text.length) b.append(el("div", { class: "asr" },
      el("div", { class: "sublbl" }, `Recognized text, Tier 1${metrics.target_name ? `, target "${metrics.target_name}"` : ""}`),
      el("table", {}, el("tbody", {}, metrics.recognized_text.map((r) => el("tr", {},
        el("td", { class: "mark" }, el("span", { class: r.hit ? "pass" : "fail" }, r.hit ? "hit" : "miss")),
        el("td", { class: "label" }, `clap ${r.clap}`), el("td", { class: "val" }, `\u201c${r.transcript ?? ""}\u201d`)))))));
    // stage 4b: closed-set distances, each echo against every target (lower is closer)
    const cs = metrics.closed_set_3x3?.distances;
    if (cs && typeof cs === "object") { const rowsK = Object.keys(cs), colsK = Object.keys(cs[rowsK[0]] ?? {});
      b.append(el("div", { class: "asr" }, el("div", { class: "sublbl" }, "Closed set: distance of each echo to each target (lower is closer, diagonal should win)"),
        el("table", { class: "cs" }, el("thead", {}, el("tr", {}, el("th", {}, "echo of"), colsK.map((c) => el("th", { class: "val" }, c)))),
          el("tbody", {}, rowsK.map((r) => { const vals = colsK.map((c) => cs[r][c]), mn = Math.min(...vals.filter((v) => v != null));
            return el("tr", {}, el("td", { class: "label" }, r), colsK.map((c, i) => el("td", { class: "val" + (vals[i] === mn ? (c === r ? " win" : " lose") : "") }, vals[i] == null ? "\u2014" : num(vals[i], 1)))); }))))); }
    if (metrics.caveats?.length) b.append(el("details", { class: "caveats" }, el("summary", {}, `Caveats (${metrics.caveats.length})`),
      el("ul", {}, metrics.caveats.map((c) => el("li", {}, c)))));
    // judge floor: what the judge scores on a perfect echo (target * clap), mean over the clap family
    const floor = metrics.judge_floor?.mean ?? null;
    const rows = (metrics.metrics ?? []).map((m) => el("tr", { class: m.gating ? "gating" : "secondary" },
      el("td", { class: "mark" }, markFor(m.pass, unverified || m.tier !== "tier1")),
      el("td", { class: "label" }, m.label ?? m.id, el("span", { class: "tier" }, m.tier === "tier1" ? "T1" : "T0"),
        m.gating && floor?.[m.id] != null ? el("div", { class: "floor", title: metrics.judge_floor.note ?? "" }, `judge floor on a perfect echo: ${num(floor[m.id], Math.abs(floor[m.id]) < 1 ? 3 : 2)}${m.unit ? (m.unit === "%" ? "\u2009%" : ` ${m.unit}`) : ""}`) : null),
      el("td", { class: "val" }, withUnit(m.value, m.unit)),
      el("td", { class: "thr" }, m.comparator ? `${CMP[m.comparator] ?? m.comparator} ${thrUnit(m.threshold, m.unit)}` : "")));
    b.append(el("table", { class: "metrics" }, el("caption", {}, "Metrics: gating rows in bold, information rows dimmed"), el("tbody", {}, rows)));
    if (this.compact) return;
    const rob = metrics.robustness ?? [];
    b.append(el("h3", {}, "Robustness", metrics.fragile ? el("span", { class: "fragile" }, "fragile") : null,
      metrics.robust_summary ? el("span", { class: "rsum" }, String(metrics.robust_summary)) : null));
    if (metrics.fragile_reason) b.append(el("p", { class: metrics.fragile ? "fragnote warn" : "fragnote" }, metrics.fragile_reason));
    const notRun = metrics.robustness_not_run ?? [];
    if (!rob.length && !notRun.length) { b.append(el("p", { class: "empty" }, "No robustness sweep in this run.")); this._links(b, metrics); return; }
    // one column per gating metric (else every metric in the deltas), showing how far it moved
    const seen = new Map(); for (const m of metrics.metrics ?? []) if (m.gating && !seen.has(m.id)) seen.set(m.id, m);
    const inDelta = new Set(rob.flatMap((r) => Object.keys(r.delta ?? {})));
    let ids = [...seen.keys()].filter((id) => inDelta.has(id)); if (!ids.length) ids = [...inDelta].slice(0, 3);
    const short = (id) => (seen.get(id)?.label ?? id).split(",")[0].replace(/_/g, " ");
    b.append(el("table", { class: "robust" },
      el("thead", {}, el("tr", {}, el("th", {}), el("th", {}, "Case"), ids.map((id) => el("th", { class: "val", title: seen.get(id)?.label ?? id }, `\u0394 ${short(id)}`)))),
      el("tbody", {}, rob.map((r) => el("tr", {}, el("td", { class: "mark" }, markFor(r.pass, unverified)),
        el("td", { class: "label" }, r.label ?? r.case),
        ids.map((id) => { const d = r.delta?.[id]; return el("td", { class: "val" }, d == null ? "\u2014" : `${d > 0 ? "+" : ""}${withUnit(d, seen.get(id)?.unit ?? "")}`); }))),
        notRun.map((r) => el("tr", { class: "notrun", title: metrics.robustness_not_run_reason ?? "" }, el("td", { class: "mark" }, el("span", { class: "info" }, "\u2014")),
          el("td", { class: "label" }, r.label ?? r.case), el("td", { class: "val", colspan: Math.max(1, ids.length) }, r.status ?? "not run"))))));
    if (notRun.length && metrics.robustness_not_run_reason) b.append(el("p", { class: "fragnote" }, `Not run: ${metrics.robustness_not_run_reason}`));
    this._links(b, metrics);
  }
  _links(b, metrics) {
    if (!metrics.design_study) return;
    b.append(el("p", { class: "links2" }, el("a", { href: `${this.dir}/metrics.json`, target: "_blank", rel: "noopener" }, "Design study (JSON, in metrics.json)")));
  }
}

// Three verdicts side by side, never merged: the spec's thresholds, the listening-calibrated revision, the owner's ear.
function verdicts(metrics) {
  const c = metrics.criteria ?? {}, s1 = c.spec_v1, o2 = c.owner_v2, lv = metrics.listening_verdict;
  if (!s1 && !o2 && !lv) return null; // custom / pilot runs: nothing, rather than a misleading empty verdict
  const cell = (title, cls, text, ...more) => el("div", { class: `vcell ${cls}` }, el("div", { class: "vt" }, title), el("div", { class: "vv" }, text), ...more);
  const cells = [];
  // strict: the spec's own thresholds
  if (s1) cells.push(cell("Original spec thresholds", s1.passed === true ? "pass" : s1.passed === false ? "fail" : "info",
    s1.passed === true ? "passed" : s1.passed === false ? "missed" : "not established",
    s1.gating?.length ? el("div", { class: "vd", title: s1.gating.map((g) => (typeof g === "string" ? g : `${g.label ?? g.id}: ${withUnit(g.value, g.unit)}`)).join("\n") },
      `${s1.gating.filter((g) => g.pass).length} of ${s1.gating.length} gating metrics met`) : null));
  // revised: listening-calibrated; null = no automated criterion established for this run
  if (o2) cells.push(cell("Revised thresholds (listening-calibrated)", o2.passed === true ? "pass" : o2.passed === false ? "fail" : "info",
    o2.passed === true ? "confirmed" : o2.passed === false ? "not confirmed" : "not established",
    o2.passed == null ? el("div", { class: "vd" }, "no automated criterion") : null,
    o2.controls?.length ? el("div", { class: "vd" }, o2.controls_all_fail ? `all ${o2.controls.length} controls rejected` : `${o2.controls.filter((x) => x.pass).length} of ${o2.controls.length} controls pass`) : null));
  // the owner's ear: always labelled not blind when it was not
  if (lv) { const acc = /^(pass|accept|yes|heard|recogni)/i.test(lv.verdict ?? ""), rej = /^(fail|reject|no|not)/i.test(lv.verdict ?? "");
    cells.push(cell("Owner's ear, 25 Nov", acc ? "pass" : rej ? "fail" : "info", el("span", {}, acc ? "accepted" : rej ? "rejected" : lv.verdict ?? "\u2014",
      lv.blind === false ? el("span", { class: "notblind", title: lv.note ?? "The listener knew each target" }, "not blind") : lv.blind === true ? el("span", { class: "notblind" }, "blind") : null),
      el("div", { class: "vd" }, [lv.date, lv.by ? `by the ${lv.by}` : null].filter(Boolean).join(", ")),
      lv.quote ? el("q", { class: "vq", title: lv.basis ?? "" }, lv.quote) : null)); }
  const out = [el("div", { class: `verdicts n${cells.length}` }, cells)];
  // what the revised verdict rests on, and its note (collapsed when long)
  if (o2?.rests_on) out.push(el("p", { class: "rests" }, `Revised verdict rests on: ${o2.rests_on}`));
  if (o2?.note) out.push(o2.note.length > 140 ? el("details", { class: "caveats v2" }, el("summary", {}, `Note: ${o2.note.slice(0, 90).replace(/[ ,;]+\S*$/, "")}\u2026`), el("p", { class: "diag" }, o2.note))
    : el("p", { class: "rests" }, `Note: ${o2.note}`));
  // the revised criterion's own numbers, one click away
  if (o2 && ((o2.metrics ?? []).length || o2.controls?.length)) out.push(el("details", { class: "caveats v2" }, el("summary", {}, "Revised thresholds: metrics and controls"),
    el("ul", { class: "vlist" }, (o2.metrics ?? []).map((m) => el("li", {}, el("span", { class: m.pass == null ? "info" : m.pass ? "pass" : "fail" }, m.pass == null ? "\u2014" : m.pass ? "met" : "missed"),
      ` ${m.label ?? m.id}: ${withUnit(m.value, m.unit)}${m.comparator ? ` (${CMP[m.comparator] ?? m.comparator} ${thrUnit(m.threshold, m.unit)})` : ""}${m.used === false ? " (not used)" : ""}`)),
      (o2.controls ?? []).map((c) => el("li", {}, el("span", { class: c.pass ? "fail" : "pass" }, c.pass ? "passes" : "rejected"), ` control ${c.name}${c.kind ? ` (${c.kind})` : ""}`)))));
  return out;
}
