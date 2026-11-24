// Scorecard: verdict, the two feasibility numbers large, each metric against its threshold,
// robustness below. Every number shown comes from metrics.json as written by the run.
import { el, num } from "./util.js";

const CMP = { "<=": "≤", ">=": "≥", "==": "=" };
const dec = (v) => (v == null ? 0 : Number.isInteger(v) ? 0 : Math.abs(v) < 1 ? 2 : Math.abs(v) < 100 ? 1 : 0);
const withUnit = (v, u) => (v == null ? "—" : `${num(v, dec(v))}${u ? (u === "%" ? " %" : ` ${u}`) : ""}`);

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
    if (!metrics) { b.append(el("p", { class: "empty" }, "This run has no metrics.json yet.")); return; }
    const H = metrics.headline ?? {};
    const spl = H.echo_spl_db, quiet = spl != null && spl < 35;
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
    const rows = (metrics.metrics ?? []).map((m) => el("tr", { class: m.gating ? "gating" : "" },
      el("td", { class: "mark" }, el("span", { class: m.pass == null ? "info" : m.pass ? "pass" : "fail" }, m.pass == null ? "info" : m.pass ? "pass" : "fail")),
      el("td", { class: "label" }, m.label ?? m.id, el("span", { class: "tier" }, m.tier === "tier1" ? "T1" : "T0")),
      el("td", { class: "val" }, withUnit(m.value, m.unit)),
      el("td", { class: "thr" }, m.comparator ? `${CMP[m.comparator] ?? m.comparator} ${withUnit(m.threshold, m.unit)}` : "")));
    b.append(el("table", { class: "metrics" }, el("caption", {}, "Metrics, gating rows in bold"), el("tbody", {}, rows)));
    if (this.compact) return;
    const rob = metrics.robustness ?? [];
    b.append(el("h3", {}, "Robustness", metrics.fragile ? el("span", { class: "fragile" }, "fragile") : null));
    if (!rob.length) { b.append(el("p", { class: "empty" }, "No robustness sweep in this run.")); return; }
    b.append(el("table", { class: "robust" }, el("tbody", {}, rob.map((r) => {
      const ds = Object.entries(r.delta ?? {}).map(([k, d]) => `${k} ${d >= 0 ? "+" : ""}${num(d, dec(d) || 2)}`).join(", ");
      return el("tr", {}, el("td", { class: "mark" }, el("span", { class: r.pass ? "pass" : "fail" }, r.pass ? "pass" : "fail")),
        el("td", { class: "label" }, r.label ?? r.case), el("td", { class: "val" }, ds));
    }))));
  }
}
