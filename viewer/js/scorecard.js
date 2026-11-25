// Scorecard: verdict, the two feasibility numbers large, each metric against its threshold,
// robustness below. Every number shown comes from metrics.json as written by the run.
import { el, num } from "./util.js";

const CMP = { "<=": "≤", ">=": "≥", "==": "=" };
const dec = (v) => (v == null ? 0 : Number.isInteger(v) ? 0 : Math.abs(v) < 10 ? 2 : Math.abs(v) < 100 ? 1 : 0);
const withUnit = (v, u) => (v == null ? "—" : `${num(v, dec(v))}${u ? (u === "%" ? " %" : ` ${u}`) : ""}`);

// Tier 1 results say pass/fail in colour; Tier 0 or unverified results only "meets"/"misses".
function markFor(pass, provisional) {
  if (pass == null) return el("span", { class: "info" }, "info");
  if (provisional) return el("span", { class: "prov", title: "Tier 0 result, not a pass" }, pass ? "meets" : "misses");
  return el("span", { class: pass ? "pass" : "fail" }, pass ? "pass" : "fail");
}

export function verdictOf(run, metrics = run.metrics) {
  const m = run.manifest, verified = (metrics?.verified ?? m.verified) && m.status !== "tier0_only";
  if (!verified) return { cls: "unverified", text: "UNVERIFIED — Tier 0 only" };
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
    const v = verdictOf(run, metrics); this.verdict.className = `verdict ${v.cls}`; this.verdict.textContent = v.text;
    const b = this.body; b.replaceChildren();
    if (note) b.append(el("p", { class: "iternote" }, note));
    // Unverified runs never show a pass: Tier 0 results read "meets" / "misses", in neutral colours.
    const unverified = v.cls === "unverified";
    if (unverified) b.append(el("p", { class: "unvnote" }, "Tier 0 only: numbers from the fast single-scattering model. A stage passes only on the full-wave Tier 1 solver, which has not run on this design."));
    if (!metrics) { b.append(el("p", { class: "empty" }, "This run has no metrics.json yet.")); return; }
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
    if (metrics.failure_cause) b.append(el("p", { class: "cause" }, metrics.failure_cause));
    if (metrics.caveats?.length) b.append(el("details", { class: "caveats" }, el("summary", {}, `Caveats (${metrics.caveats.length})`),
      el("ul", {}, metrics.caveats.map((c) => el("li", {}, c)))));
    // judge floor: what the judge scores on a perfect echo (target * clap), mean over the clap family
    const floor = metrics.judge_floor?.mean ?? null;
    const rows = (metrics.metrics ?? []).map((m) => el("tr", { class: m.gating ? "gating" : "secondary" },
      el("td", { class: "mark" }, markFor(m.pass, unverified || m.tier !== "tier1")),
      el("td", { class: "label" }, m.label ?? m.id, el("span", { class: "tier" }, m.tier === "tier1" ? "T1" : "T0"),
        m.gating && floor?.[m.id] != null ? el("div", { class: "floor", title: metrics.judge_floor.note ?? "" }, `judge floor on a perfect echo: ${num(floor[m.id], Math.abs(floor[m.id]) < 1 ? 3 : 2)}${m.unit ? (m.unit === "%" ? "\u2009%" : ` ${m.unit}`) : ""}`) : null),
      el("td", { class: "val" }, withUnit(m.value, m.unit)),
      el("td", { class: "thr" }, m.comparator ? `${CMP[m.comparator] ?? m.comparator} ${withUnit(m.threshold, m.unit)}` : "")));
    b.append(el("table", { class: "metrics" }, el("caption", {}, "Metrics: gating rows in bold, information rows dimmed"), el("tbody", {}, rows)));
    if (this.compact) return;
    const rob = metrics.robustness ?? [];
    b.append(el("h3", {}, "Robustness", metrics.fragile ? el("span", { class: "fragile" }, "fragile") : null));
    if (metrics.fragile_reason) b.append(el("p", { class: metrics.fragile ? "fragnote warn" : "fragnote" }, metrics.fragile_reason));
    if (!rob.length) { b.append(el("p", { class: "empty" }, "No robustness sweep in this run.")); return; }
    // one column per gating metric (else every metric in the deltas), showing how far it moved
    const seen = new Map(); for (const m of metrics.metrics ?? []) if (m.gating && !seen.has(m.id)) seen.set(m.id, m);
    let ids = [...seen.keys()]; if (!ids.length) ids = [...new Set(rob.flatMap((r) => Object.keys(r.delta ?? {})))];
    const short = (id) => (seen.get(id)?.label ?? id).split(",")[0].replace(/_/g, " ");
    b.append(el("table", { class: "robust" },
      el("thead", {}, el("tr", {}, el("th", {}), el("th", {}, "Case"), ids.map((id) => el("th", { class: "val", title: seen.get(id)?.label ?? id }, `\u0394 ${short(id)}`)))),
      el("tbody", {}, rob.map((r) => el("tr", {}, el("td", { class: "mark" }, markFor(r.pass, unverified)),
        el("td", { class: "label" }, r.label ?? r.case),
        ids.map((id) => { const d = r.delta?.[id]; return el("td", { class: "val" }, d == null ? "\u2014" : `${d > 0 ? "+" : ""}${withUnit(d, seen.get(id)?.unit ?? "")}`); }))))));
  }
}
