"""Morning report generator: `uv run python -m stages.report` rewrites REPORT.md entirely from files on disk.

Inputs (read-only): runs/index.json and the run folders it lists, runs/validation/metrics.json, DECISIONS.md,
BUILD.md (generated block), artifacts/speech/judge_sanity.json, artifacts/report/viewer-<stage>.png and the controller
ledger .superpowers/sdd/plan/progress.md. Every number in the output is read from one of these files (or from the
test-suite summary line). Hand-written text lives only in the commentary block, which is preserved between runs.

Options: --no-tests reuses the test summary already in REPORT.md instead of running `uv run pytest -q`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path(".superpowers/sdd/plan/progress.md")
COMMENT_BEGIN = "<!-- COMMENTARY:BEGIN (hand-written; preserved by stages/report.py) -->"
COMMENT_END = "<!-- COMMENTARY:END -->"
TESTS_BEGIN = "<!-- TESTS:BEGIN -->"
TESTS_END = "<!-- TESTS:END -->"

# Stage groups in spec order: (prefix, number, name, sub-stage ids the spec defines).
STAGES = [
    ("s1", 1, "Bird note", ["s1_bird"]),
    ("s2", 2, "Motif", ["s2_motif"]),
    ("s3", 3, "Melody", ["s3_melody"]),
    ("s4", 4, "Speech", ["s4a_vowel", "s4b_syllables", "s4c_word"]),
]
DEFAULT_COMMENTARY = """\
*Current best understanding (hand-written, no numbers; see the tables for values).*

- The stage-1 design realizes the reflectivity profile as a positive bias plus the signal, sampled into post
  positions. Most posts carry the bias rather than the note, so the post budget is largely spent on a component that
  adds nothing to the whistle, and the echo is hypersensitive to millimetre position errors (jitter row of the
  robustness table; BUILD.md's placement tables).
- A redesign of the realization (phase-locked placement: posts placed at the phase of the target so that each post
  adds coherently to the note) is in progress in a separate agent; its run will appear here as a newer stage-1 final
  run when it lands.
- The wedge is wide, so path lengths change quickly as the listener moves: the echo is specific to the listener
  position (see the listener rows of the robustness table). A narrower wedge or a design that is scored over several
  listener positions would trade echo level for a larger listening spot.
"""


# ------------------------------------------------------------------------------------------------------------ helpers
def _load(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def fmt(v, nd=2, signed=False):
    """Format a value for a Markdown table: never 'None' or 'NaN'."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:+d}" if signed else str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return "n/a"
        return f"{v:+.{nd}f}" if signed else f"{v:.{nd}f}"
    if isinstance(v, (list, tuple)):
        return ", ".join(fmt(x, nd) for x in v) if v else "—"
    s = str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def num(v, mid=""):
    """Value formatting by metric: percentages and dB with 2 decimals, correlations/fractions with 3."""
    if isinstance(v, float) and not isinstance(v, bool) and not (math.isnan(v) or math.isinf(v)):
        if mid.endswith(("_pct", "_db")) or abs(v) >= 10:
            return f"{v:.2f}"
        return f"{v:.3g}" if abs(v) < 0.1 and v != 0 else f"{v:.3f}"
    return fmt(v)


def pf(p):
    return "—" if p is None else ("PASS" if p else "FAIL")


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(fmt(c) if not isinstance(c, str) else c.replace("\n", " ") for c in r) + " |")
    return "\n".join(out)


def rel(root: Path, p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(root.resolve()))
    except ValueError:
        return str(p)


def stage_group(stage: str):
    for g in STAGES:
        if stage.startswith(g[0]):
            return g
    return None


def ranges_text(nums):
    """[2, 3, 4] -> 'stages 2–4'; [2] -> 'stage 2'; [2, 4] -> 'stages 2 and 4'."""
    nums = sorted(nums)
    if not nums:
        return ""
    if len(nums) == 1:
        return f"stage {nums[0]}"
    if nums == list(range(nums[0], nums[-1] + 1)):
        return f"stages {nums[0]}–{nums[-1]}"
    return "stages " + ", ".join(str(n) for n in nums[:-1]) + f" and {nums[-1]}"


def sanitize_caveat(text: str) -> str:
    """Drop the withdrawn 'effect bounded at X dB' inference (a review found self-convergence cannot bound a bias
    both grids share) wherever an older run file still carries it."""
    return re.sub(r"(its |the )?effect on dense-field echoes is bounded at [^;)]*(\([^)]*\))?",
                  "effect on dense-field echoes is not bounded (this run file states a bound; an independent review "
                  "found that inference invalid and it is withdrawn)", text)


# --------------------------------------------------------------------------------------------------------- data model
class Data:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.runs_dir = self.root / "runs"
        idx = _load(self.runs_dir / "index.json") or {}
        self.index = [r for r in idx.get("runs", []) if isinstance(r, dict)]
        self.validation = _load(self.runs_dir / "validation" / "metrics.json")
        self.val_path = "runs/validation/metrics.json"
        self.ledger = (self.root / LEDGER).read_text() if (self.root / LEDGER).exists() else ""
        self.decisions = (self.root / "DECISIONS.md").read_text() if (self.root / "DECISIONS.md").exists() else ""
        self.build_md = (self.root / "BUILD.md").read_text() if (self.root / "BUILD.md").exists() else ""
        self.speech = _load(self.root / "artifacts" / "speech" / "judge_sanity.json")
        # runs grouped by stage group; each run gets its metrics + manifest
        self.by_group = {g[0]: [] for g in STAGES}
        for r in sorted(self.index, key=lambda r: (r.get("created", ""), r.get("run_id", "")), reverse=True):
            g = stage_group(r.get("stage", ""))
            if g is None:
                continue
            d = self.runs_dir / r.get("path", "")
            run = dict(r)
            run["dir"] = d
            run["rel"] = rel(self.root, d)
            run["metrics"] = _load(d / "metrics.json") or {}
            run["manifest"] = _load(d / "manifest.json") or {}
            self.by_group[g[0]].append(run)

    @property
    def val_passed(self):
        return bool(self.validation and self.validation.get("passed") is True)

    def finals(self, prefix):
        return [r for r in self.by_group[prefix] if r.get("status") == "final"]

    def latest_by_stage(self, prefix):
        """Newest final run per sub-stage id (stage 4 has three)."""
        out = {}
        for r in self.finals(prefix):
            out.setdefault(r["stage"], r)
        return out


def run_passed(run):
    m = run.get("metrics") or {}
    return bool(m.get("passed", run.get("passed")))


def run_verified(run):
    m = run.get("metrics") or {}
    return bool(m.get("verified", run.get("verified")))


def gating(run, tier=None):
    ms = (run.get("metrics") or {}).get("metrics") or []
    return [m for m in ms if m.get("gating") and (tier is None or m.get("tier") == tier)]


def group_state(data: Data, g):
    """'pass' | 'fail' | 'fail_unverified' | 'pass_unverified' | 'not_run'."""
    latest = data.latest_by_stage(g[0])
    if not latest:
        return "not_run"
    ok = all(run_passed(r) for r in latest.values())
    ver = all(run_verified(r) for r in latest.values())
    return ("pass" if ok else "fail") + ("" if ver else "_unverified")


# ------------------------------------------------------------------------------------------------------------ sections
def banner(data: Data):
    states = {g[1]: group_state(data, g) for g in STAGES}
    run = [n for n, s in states.items() if s != "not_run"]
    not_run = [n for n, s in states.items() if s == "not_run"]
    all_done = len(run) == len(STAGES)
    head = "FINAL" if all_done else "INTERIM"
    parts = [f"{len(run)} of {len(STAGES)} stages run"]
    for n in run:
        s = states[n]
        if s == "pass":
            parts.append(f"stage {n} passed on the full-wave solver")
        elif s == "fail":
            parts.append(f"stage {n} failed on the full-wave solver")
        elif s == "pass_unverified":
            parts.append(f"stage {n} met its thresholds but is unverified")
        else:
            parts.append(f"stage {n} failed and is unverified")
    if not_run:
        parts.append(f"{ranges_text(not_run)} not yet run")
    line = f"**{head} — " + "; ".join(parts) + ".**"
    if not data.val_passed:
        line = "UNVERIFIED — the full-wave solver has not passed validation; every result below is unverified. " + line
    return line


def verdict(data: Data):
    s = []
    v = data.validation
    if v is None:
        s.append("No solver validation file exists, so no result is verified.")
    elif data.val_passed:
        eng = (v.get("solver") or {}).get("engine")
        s.append(f"The full-wave solver (engine {fmt(eng)}) passes the spec's four validation checks, with limits "
                 "listed in the validation section: it is checked against exact theory only for single-post "
                 "backscatter, and dense-field effects are checked only by self-convergence.")
    else:
        s.append("The full-wave solver did not pass validation, so every result is unverified.")
    for g in STAGES:
        latest = data.latest_by_stage(g[0])
        for stage, r in latest.items():
            m = r["metrics"]
            h = m.get("headline") or {}
            verdict_word = "passed" if run_passed(r) else "failed"
            where = "on the full-wave solver (Tier 1)" if run_verified(r) else "(unverified)"
            sent = f"Stage {g[1]} ({fmt(r.get('title'))}, run `{r['run_id']}`) {verdict_word} {where}"
            if m.get("failure_cause"):
                sent += f": {m['failure_cause'].rstrip('.')}."
            else:
                gm = gating(r, "tier1") or gating(r)
                sent += ": " + "; ".join(f"{x.get('label')} {fmt(x.get('value'))} vs {x.get('comparator')} "
                                         f"{fmt(x.get('threshold'))}" for x in gm) + "."
            s.append(sent)
            t0 = [x for x in (m.get("metrics") or []) if x.get("tier") == "tier0" and x.get("threshold") is not None]
            if t0 and run_verified(r):
                ok0 = all(x.get("pass") for x in t0)
                s.append("The same design on the single-scattering model (Tier 0) " + ("meets" if ok0 else "misses")
                         + " those thresholds (" + "; ".join(f"{x.get('id')} {fmt(x.get('value'), 3)}" for x in t0)
                         + ")" + (", so the shortfall appears between the single-scattering model and the full-wave "
                                  "solver." if ok0 else " as well."))
            s.append(f"It uses {fmt(h.get('post_count'))} posts over {fmt(h.get('depth_m'), 1)} m of range "
                     f"(fill {fmt(100 * h['fill_fraction'] if h.get('fill_fraction') is not None else None)} % of "
                     f"the wedge); the 3D echo estimate is {fmt(h.get('echo_level_db_re_direct'), 1)} dB re the "
                     f"direct clap, about {fmt(h.get('echo_spl_db'), 0)} dB SPL for a 100 dB clap"
                     + (" (flagged likely inaudible)." if h.get("likely_inaudible_on_site") else "."))
            if m.get("fragile_reason"):
                s.append(f"Robustness: {m['fragile_reason']} (fragile flag in the file: {fmt(m.get('fragile'))}).")
    not_run = [g for g in STAGES if group_state(data, g) == "not_run"]
    if not_run:
        s.append(f"{ranges_text([g[1] for g in not_run]).capitalize()}: not run. " + not_run_reason(data, not_run[0]))
    return " ".join(s)


def not_run_reason(data: Data, g):
    if g[1] == 1:
        return "No final stage-1 run exists yet."
    s1 = group_state(data, STAGES[0])
    if s1 != "pass":
        return ("The spec's gate says stage 1 must pass on Tier 1 before any work starts on stage 2; stage 1 has "
                "not passed, so later stages wait.")
    return "No final run exists yet for this stage."


def how_to_look(data: Data):
    out = ["Serve the repo and open the viewer (it reads the run folders directly):", "",
           "```", "uv run python -m http.server 8000      # from the repo root", "```", "",
           "- Viewer: <http://localhost:8000/viewer/> (opens the newest final run; pick runs in the header).",
           "- Lay explainer: <http://localhost:8000/explainer/> (`explainer/index.html`, rebuilt by "
           "`uv run python explainer/build.py`).",
           "- Build path: [`BUILD.md`](BUILD.md).", ""]
    rows = []
    for g in STAGES:
        for r in data.finals(g[0]):
            d = r["dir"]
            echo = "echo_tier1.wav" if (d / "echo_tier1.wav").exists() else "echo_tier0.wav"
            files = [f"`{r['rel']}/{f}`" if (d / f).exists() else f"{f} missing"
                     for f in ("target.wav", echo, "as_heard.wav")]
            lvl = ((r.get("manifest") or {}).get("audio") or {}).get("as_heard_echo_level_db")
            rows.append([f"{g[1]} {r['stage']}", f"`{r['run_id']}`", *files, f"{fmt(lvl, 1)} dB"])
    if rows:
        out.append("Audio for every final run (target / echo / as heard: the direct clap followed by the echo at its "
                   "true relative level, which is why the echo is barely audible in that file):")
        out.append("")
        out.append(table(["stage", "run", "target", "echo", "as heard", "echo level in as-heard"], rows))
    else:
        out.append("No final runs yet, so no audio to list.")
    shots = sorted((data.root / "artifacts" / "report").glob("viewer-*.png"))
    for p in shots:
        pre = p.stem.removeprefix("viewer-")
        taken = _dt.datetime.fromtimestamp(p.stat().st_mtime).astimezone()
        newest = [r for r in data.finals(pre[:2])] if pre[:2] in data.by_group else []
        note = ""
        if newest:
            try:
                if _dt.datetime.fromisoformat(newest[0].get("created", "")) > taken:
                    note = f" **Older than the newest final run `{newest[0]['run_id']}`: retake it.**"
            except ValueError:
                pass
        out += ["", f"Viewer, {pre} (screenshot taken {taken.isoformat(timespec='minutes')}).{note}", "",
                f"![viewer screenshot, {pre}]({rel(data.root, p)})"]
    ex = data.root / "artifacts" / "report" / "explainer-results.png"
    if ex.exists():
        out += ["", f"![explainer results section]({rel(data.root, ex)})"]
    return "\n".join(out)


def validation_section(data: Data):
    v = data.validation
    if v is None:
        return "UNVERIFIED: `runs/validation/metrics.json` does not exist."
    c = v.get("checks") or {}
    cyl = c.get("cylinder") or {}
    g1 = cyl.get("stage1_grid") or {}
    pr1 = g1.get("per_radius") or {}
    worst_back = max((x.get("max_abs_err_db") for x in pr1.values() if x.get("max_abs_err_db") is not None),
                     default=None)
    gc = c.get("grid_convergence") or {}
    es = c.get("empty_scene") or {}
    tt = c.get("tier0_vs_tier1") or {}
    rows = [
        ["1. Single rigid cylinder, backscatter vs analytic (stage-1 grid, all catalog radii)",
         f"worst {fmt(worst_back)} dB", f"≤ {fmt(cyl.get('threshold_db'), 1)} dB", pf(cyl.get("pass")),
         "checks.cylinder.stage1_grid.per_radius.*.max_abs_err_db"],
        ["2. Grid convergence (halve dx), sparse reference design", f"{fmt((gc.get('sparse') or {}).get('max_abs_delta_db'))} dB",
         "< 1 dB", pf((gc.get("sparse") or {}).get("pass")), "checks.grid_convergence.sparse.max_abs_delta_db"],
        ["2b. Grid convergence, dense patch (self-convergence only)",
         f"{fmt((gc.get('dense') or {}).get('max_abs_level_delta_db'))} dB", "< 1 dB",
         pf((gc.get("dense") or {}).get("pass")), "checks.grid_convergence.dense.max_abs_level_delta_db"],
        ["3. Empty scene: nothing after the direct clap", f"{fmt(es.get('max_after_direct_db'), 1)} dB",
         f"< {fmt(es.get('threshold_db'), 0)} dB", pf(es.get("pass")), "checks.empty_scene.max_after_direct_db"],
        ["4. Tier 0 vs Tier 1, sparse design", f"{fmt(tt.get('max_abs_delta_db'))} dB",
         f"≤ {fmt(tt.get('threshold_db'), 1)} dB", pf(tt.get("pass")), "checks.tier0_vs_tier1.max_abs_delta_db"],
    ]
    solver = v.get("solver") or {}
    out = [f"Source: `{data.val_path}` (engine `{fmt(solver.get('engine'))}`, {fmt(solver.get('ppw'), 0)} points "
           f"per wavelength). Overall `passed`: **{fmt(v.get('passed'))}**.", "",
           table(["check", "value", "threshold", "result", "key"], rows), ""]
    # per-radius table for both grids
    prow = []
    ext = (v.get("extended_checks") or {}).get("angular_scattering") or {}
    for gname in ("stage1_grid", "stage3_grid"):
        g = cyl.get(gname) or {}
        eg = (ext.get(gname) or {}).get("per_radius") or {}
        for r, x in (g.get("per_radius") or {}).items():
            e = eg.get(r) or {}
            prow.append([f"{fmt(g.get('f_max'), 0)} Hz", f"{float(r) * 100:.0f} cm", fmt(x.get("max_abs_err_db")),
                         pf(x.get("pass")), fmt(e.get("forward")), fmt(e.get("bistatic_90")),
                         fmt(x.get("max_abs_err_db_all_angles")), pf(x.get("pass_all_angles"))])
    out += ["Per post radius (error vs the analytic cylinder, dB; forward and 90° are an extended check beyond the "
            "spec):", "",
            table(["grid f_max", "radius", "backscatter err", "spec check", "forward err", "90° err",
                   "worst any angle", "all angles"], prow), ""]
    # caveats in plain words, values from the file
    cav = ["**What this validation does and does not show:**", "",
           "- Tier 1 is validated against exact theory only for single-post backscatter."]
    all1 = g1.get("validated_radii_all_angles") or []
    bad = [r for r in pr1 if float(r) not in [float(a) for a in all1]]
    eg1 = (ext.get("stage1_grid") or {}).get("per_radius") or {}
    if all1:
        det = "; ".join(f"{float(r) * 100:.0f} cm: forward {fmt((eg1.get(r) or {}).get('forward'))} dB, 90° "
                        f"{fmt((eg1.get(r) or {}).get('bistatic_90'))} dB off" for r in bad)
        cav.append(f"- At the {fmt(g1.get('f_max'), 0)} Hz grid only "
                   + ", ".join(f"{float(r) * 100:.0f} cm" for r in all1)
                   + " posts match the analytic cylinder at all angles" + (f" ({det})." if det else "."))
    ac = solver.get("area_cal") or {}
    facs = [x for x in ac.values() if isinstance(x, (int, float)) and x != 1.0]
    cav.append("- The 1 cm backscatter match relies on an area factor fitted to backscatter"
               + (f" (factor {fmt(facs[0], 3)}, `solver.area_cal`)" if facs else "") + "; held-out offsets confirm "
               "backscatter only.")
    dn = gc.get("dense") or {}
    cav.append("- Shadowing and multiple scattering in dense fields are checked by self-convergence only (production "
               f"grid vs twice as fine, {fmt(dn.get('n_posts'))} posts from `{fmt(dn.get('source_scene'))}`), not "
               "against an exact solution. A bias shared by both grids would not show, so the effect of the "
               "angular errors above on dense-field echoes is not bounded.")
    g3 = cyl.get("stage3_grid") or {}
    not3 = [r for r in (g3.get("per_radius") or {}) if not (g3["per_radius"][r] or {}).get("pass")]
    if not3:
        cav.append(f"- At the {fmt(g3.get('f_max'), 0)} Hz grid (needed for stage 3) "
                   + ", ".join(f"{float(r) * 100:.0f} cm" for r in not3) + " posts are not validated.")
    cav += ["", "Caveats as recorded in the file (`caveats`):", ""]
    cav += [f"- {sanitize_caveat(fmt(x))}" for x in (v.get("caveats") or [])]
    return "\n".join(out + cav)


def _metric_table(run):
    m = run["metrics"]
    floor = ((m.get("judge_floor") or {}).get("mean")) or {}
    rows = []
    for x in m.get("metrics") or []:
        i = x.get("id") or ""
        thr = "—" if x.get("threshold") is None else f"{x.get('comparator')} {num(x.get('threshold'), i)}"
        rows.append([x.get("tier"), fmt(x.get("label")) + f" (`{i}`)", f"{num(x.get('value'), i)} "
                     f"{x.get('unit') or ''}".strip(), thr, pf(x.get("pass")),
                     num(floor.get(i), i) if i in floor else "—", fmt(x.get("gating"))])
    return table(["tier", "metric", "value", "threshold", "result", "judge floor (perfect echo)", "gating"], rows)


def _per_clap_table(run):
    m = run["metrics"]
    ids = [x["id"] for x in gating(run, "tier1") or gating(run)] or sorted(
        {k for pc in m.get("per_clap") or [] for k in (pc.get("metrics") or {})})
    floor = {pc.get("clap"): pc.get("metrics") or {} for pc in (m.get("judge_floor") or {}).get("per_clap") or []}
    rows = []
    for pc in m.get("per_clap") or []:
        mm = pc.get("metrics") or {}
        rows.append([pc.get("clap"), pc.get("tier", "—")] + [num(mm.get(i), i) for i in ids]
                    + [num(floor.get(pc.get("clap"), {}).get(i), i) for i in ids])
    return table(["clap", "tier"] + ids + [f"{i} floor" for i in ids], rows)


def _robust_table(run):
    m = run["metrics"]
    ids = [x["id"] for x in gating(run, "tier1") or gating(run)]
    rows = []
    for r in m.get("robustness") or []:
        mm, dd = r.get("metrics") or {}, r.get("delta") or {}
        rows.append([fmt(r.get("label")) + f" (`{r.get('case')}`)"] +
                    [f"{num(mm.get(i), i)} ({fmt(dd.get(i), 2 if i.endswith('_pct') else 3, signed=True)})"
                     for i in ids] + [pf(r.get("pass"))])
    return table(["case"] + [f"{i} (delta)" for i in ids] + ["passes"], rows)


def _generic_rows_table(rows):
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return ""
    keys = []
    for r in rows:
        keys += [k for k, v in r.items() if k not in keys and not isinstance(v, (dict, list))]
    return table(keys, [[num(r.get(k), k) for k in keys] for r in rows])


def scorecard(data: Data, g):
    out = [f"### Stage {g[1]} — {g[2]}", ""]
    latest = data.latest_by_stage(g[0])
    if not latest:
        out.append(f"**Not run.** {not_run_reason(data, g)}")
        if g[1] == 4 and data.speech:
            out += ["", speech_prep(data)]
        return "\n".join(out)
    for stage, r in latest.items():
        m, mf = r["metrics"], r["manifest"]
        h = m.get("headline") or {}
        verdict_word = "PASSED" if run_passed(r) else "FAILED"
        out += [f"#### `{stage}` — {verdict_word}" + ("" if run_verified(r) else " (UNVERIFIED)"), "",
                f"Run `{r['rel']}` ({fmt(r.get('title'))}), created {fmt(r.get('created'))}, solver "
                f"`{fmt((mf.get('solver') or {}).get('tier1'))}` engine `{fmt((mf.get('solver') or {}).get('engine'))}`"
                f", verified: {fmt(run_verified(r))}. Source: `{r['rel']}/metrics.json`.", ""]
        spl = h.get("echo_spl_db")
        flag = " — **below 35 dB: likely inaudible on site**" if h.get("likely_inaudible_on_site") else ""
        fill = h.get("fill_fraction")
        hrows = [
            ["Echo level, 3D estimate, tier-gap corrected", f"{fmt(h.get('echo_level_db_re_direct'), 1)} dB re direct",
             "headline.echo_level_db_re_direct"],
            ["Echo level, raw 3D (Tier 0)", f"{fmt(h.get('echo_level_db_re_direct_raw3d'), 1)} dB re direct",
             "headline.echo_level_db_re_direct_raw3d"],
            ["Echo level for a 100 dB clap", f"{fmt(spl, 1)} dB SPL{flag}", "headline.echo_spl_db"],
            ["Structure depth (bistatic range)", f"{fmt(h.get('depth_m'), 2)} m", "headline.depth_m"],
            ["Post count", fmt(h.get("post_count")), "headline.post_count"],
            ["Fill fraction of the wedge", f"{fmt(100 * fill if fill is not None else None, 2)} %",
             "headline.fill_fraction"],
            ["Tier gap (Tier 1 − Tier 0 level, 2D)", f"{fmt(h.get('tier_gap_db'), 2)} dB", "headline.tier_gap_db"],
            ["Fragile (spec: works for only one clap or one listener)", fmt(m.get("fragile")), "fragile"],
        ]
        if m.get("fragile_reason"):
            hrows.append(["Robustness summary", fmt(m["fragile_reason"]), "fragile_reason"])
        hrows.append(["Failure cause", fmt(m.get("failure_cause")), "failure_cause"])
        if h.get("echo_level_db_re_direct_finite_height") is not None:
            hrows.append([f"Echo level with {fmt(h.get('finite_height_m'), 1)} m posts (info)",
                          f"{fmt(h['echo_level_db_re_direct_finite_height'], 1)} dB re direct",
                          "headline.echo_level_db_re_direct_finite_height"])
        out += [table(["quantity", "value", "key"], hrows), "",
                "**Metrics** (mean over the clap family; the gating rows decide pass/fail; the judge floor is what "
                "the same judge gives a physically perfect echo, `judge_floor.mean`):", "", _metric_table(r), "",
                "**Per clap variant** (with the judge floor per clap):", "", _per_clap_table(r), ""]
        if m.get("robustness"):
            out += ["**Robustness** (Tier 1 value, change from nominal in brackets):", "", _robust_table(r), ""]
        tc = m.get("tier1_correction") or {}
        ds = (tc.get("density_sweep") or {})
        if ds.get("rows"):
            out += [f"**Design study — density sweep** (picked fill {fmt(ds.get('picked_fill'), 4)}; selection: "
                    f"{fmt(ds.get('selection'))}):", "", _generic_rows_table(ds["rows"]), ""]
        if tc.get("rounds"):
            rr = [{"round": x.get("round"), "posts": x.get("posts"), "loss": x.get("loss"), "score": x.get("score"),
                   "tier_gap_db": x.get("tier_gap_db"), **{k: v for k, v in (x.get("gating") or {}).items()}}
                  for x in tc["rounds"]]
            out += [f"**Design study — Tier 1 correction rounds** (best round {fmt(tc.get('best_round'))}):", "",
                    _generic_rows_table(rr), ""]
        if isinstance(m.get("design_study"), dict):
            for k, v in m["design_study"].items():
                if isinstance(v, list):
                    out += [f"**Design study — {k}:**", "", _generic_rows_table(v), ""]
        cav = m.get("caveats") or (m.get("verification") or {}).get("caveats") or []
        if cav:
            out += ["**Caveats recorded in this run:**", ""] + [f"- {sanitize_caveat(fmt(c))}" for c in cav] + [""]
        out += [f"Reproduce: `{fmt(mf.get('command'))}` (seed {fmt(mf.get('seed'))}, commit "
                f"`{fmt(mf.get('git_commit'))}`).", ""]
    hist = [x for x in data.by_group[g[0]] if x not in latest.values()]
    if hist:
        out += ["Earlier runs of this stage (history; the scorecard above uses the newest final run):", "",
                table(["run", "status", "passed", "verified", "pitch/gating summary"],
                      [[f"`{x['rel']}`", x.get("status"), fmt(run_passed(x)), fmt(run_verified(x)),
                        "; ".join(f"{y.get('id')} {fmt(y.get('value'))} ({y.get('tier')})"
                                  for y in (x['metrics'].get('metrics') or []) if y.get('threshold') is not None)
                        or "—"] for x in hist]), ""]
    return "\n".join(out)


def speech_prep(data: Data):
    sp = data.speech
    out = ["*Preparation findings for stage 4 (judges run on a physically perfect echo, target ⊛ clap; these are "
           "not stage-4 results — those count only from a stage-4 `metrics.json`). Source: "
           "`artifacts/speech/judge_sanity.json`.*", ""]
    rows = []
    v = (sp.get("s4a_vowel") or {}).get("rows") or {}
    errs = [x.get("formant_err_pct") for k, x in v.items() if k.startswith("perfect_clap")]
    if errs:
        rows.append(["4a vowel: worst formant error, perfect echo", f"{fmt(sum(errs) / len(errs), 1)} % mean ("
                     f"{fmt(min(errs), 1)}–{fmt(max(errs), 1)} % per clap)",
                     f"≤ {fmt((sp.get('s4a_vowel') or {}).get('threshold_pct'), 0)} %",
                     "s4a_vowel.rows.perfect_clap*.formant_err_pct"])
    syl = (sp.get("s4b_syllables") or {}).get("rows") or {}
    est = [x.get("estoi") for s in syl.values() for k, x in s.items() if k.startswith("perfect_clap")]
    cor = [x.get("correct") for s in syl.values() for k, x in s.items() if k.startswith("perfect_clap")]
    if est:
        rows.append(["4b syllables: ESTOI / closed-set correct, perfect echo",
                     f"{fmt(min(est))}–{fmt(max(est))}; {sum(bool(c) for c in cor)} of {len(cor)} correct",
                     f"ESTOI ≥ {fmt((sp.get('s4b_syllables') or {}).get('threshold_estoi'), 1)}",
                     "s4b_syllables.rows.*.perfect_clap*"])
    w = (sp.get("s4c_word") or {}).get("rows") or {}
    hits = [x.get("hit") for k, x in w.items() if k.startswith("perfect_clap")]
    if hits:
        rows.append(["4c word: recognizer says \"hello\", perfect echo", f"{sum(bool(h) for h in hits)} of {len(hits)}",
                     f"≥ {fmt((sp.get('s4c_word') or {}).get('threshold_hello_count'))} of 5",
                     "s4c_word.rows.perfect_clap*.hit"])
    return "\n".join(out + [table(["judge check", "value", "threshold", "key"], rows)])


def open_questions(data: Data):
    out = []
    # Q1 loudness
    ans = []
    for g in STAGES:
        for stage, r in data.latest_by_stage(g[0]).items():
            h = r["metrics"].get("headline") or {}
            ans.append(f"stage {g[1]} (`{stage}`): {fmt(h.get('echo_level_db_re_direct'), 1)} dB re the direct clap,"
                       f" {fmt(h.get('echo_spl_db'), 1)} dB SPL for a 100 dB clap"
                       + (" (below 35 dB: likely inaudible)" if h.get("likely_inaudible_on_site") else "")
                       + f" — `{r['rel']}/metrics.json` keys `headline.echo_level_db_re_direct`, "
                       "`headline.echo_spl_db`")
    missing = [g[1] for g in STAGES if not data.latest_by_stage(g[0])]
    q1 = "; ".join(ans) + "." if ans else "Not yet answered."
    if missing:
        q1 += f" Not yet answered for {ranges_text(missing)} (no final run)."
    out.append(f"1. **How loud is the echo for each stage, in the 3D estimate?** {q1}")
    # Q2 note length
    s3 = data.finals("s3")
    if s3:
        bits = []
        for r in s3:
            ns = (((r["manifest"].get("design") or {}).get("config")) or {}).get("note_s")
            bits.append(f"`{r['rel']}` note {fmt(ns * 1000 if ns else None, 0)} ms: {pf(run_passed(r))} "
                        "(key `passed`)")
        out.append("2. **How short can notes get before the melody stops transcribing?** " + "; ".join(bits) + ".")
    else:
        out.append("2. **How short can notes get before the melody stops transcribing?** Not yet answered: needs "
                   "stage-3 final runs at 100 ms and 60 ms notes (none exist).")
    # Q3 speech limit
    s4 = data.latest_by_stage("s4")
    if s4:
        bits = [f"`{st}`: {fmt(r['metrics'].get('failure_cause') or 'passed')} (`{r['rel']}/metrics.json` key "
                "`failure_cause`)" for st, r in s4.items()]
        out.append("3. **Which is the limit on speech?** " + "; ".join(bits) + ".")
    else:
        q3 = ("3. **Which is the limit on speech: the clap spectrum, the positivity constraint, or small-post "
              "scattering?** Not yet answered: no stage-4 run exists.")
        v = ((data.speech or {}).get("s4a_vowel") or {}).get("rows") or {}
        f1 = [x.get("f1_err_pct") for k, x in v.items() if k.startswith("perfect_clap")]
        if f1:
            q3 += (" Preparation finding only (not a stage-4 result): on a physically perfect echo the clap's spectrum "
                   f"alone moves the first formant by {fmt(min(f1), 1)}–{fmt(max(f1), 1)} % across clap variants "
                   "(`artifacts/speech/judge_sanity.json` key `s4a_vowel.rows.perfect_clap*.f1_err_pct`), against "
                   "a 10 % threshold, which points at the clap spectrum as one limit before any structure is built.")
        out.append(q3)
    # Q4 tolerance
    bits = []
    for g in STAGES:
        for stage, r in data.latest_by_stage(g[0]).items():
            for x in r["metrics"].get("robustness") or []:
                if x.get("case") == "jitter":
                    d = x.get("delta") or {}
                    bits.append(f"stage {g[1]} (`{stage}`, {fmt(x.get('label'))}): "
                                + ", ".join(f"{k} {fmt(v, 3, signed=True)}" for k, v in d.items())
                                + f"; jittered design passes: {fmt(x.get('pass'))} — `{r['rel']}/metrics.json` key "
                                "`robustness[case=jitter].delta`")
    q4 = "; ".join(bits) + "." if bits else "Not yet answered: no final run with a jitter case."
    if bits and any(not run_passed(r) for g in STAGES for r in data.latest_by_stage(g[0]).values()):
        q4 += (" Where the nominal design already fails, these deltas show sensitivity, not whether a passing design "
               "would survive; BUILD.md's placement tables (Tier 0) go further.")
    out.append(f"4. **How much do build tolerances of 5 mm matter?** {q4}")
    return "\n".join(out)


def next_steps(data: Data, commentary: str):
    out = ["**What limited each stage (from `failure_cause`):**", ""]
    for g in STAGES:
        latest = data.latest_by_stage(g[0])
        if not latest:
            out.append(f"- Stage {g[1]}: not run — {not_run_reason(data, g)}")
        for stage, r in latest.items():
            out.append(f"- Stage {g[1]} (`{stage}`): {fmt(r['metrics'].get('failure_cause') or 'passed')}")
    steps = []
    for g in STAGES:
        for stage, r in data.latest_by_stage(g[0]).items():
            if run_passed(r):
                continue
            m = r["metrics"]
            t0 = [x for x in m.get("metrics") or [] if x.get("tier") == "tier0" and x.get("threshold") is not None]
            t1 = gating(r, "tier1")
            if t0 and t1 and all(x.get("pass") for x in t0) and not all(x.get("pass") for x in t1):
                steps.append(f"Stage {g[1]}: the design meets its thresholds on Tier 0 but not on Tier 1 — work on "
                             "how the profile becomes posts (realization) and on multiple scattering, not on the "
                             "profile solve (scorecard metric table, tier rows).")
            elif t0 and not all(x.get("pass") for x in t0):
                steps.append(f"Stage {g[1]}: the design misses on Tier 0 already — the profile solve or realization "
                             "itself must improve first.")
            rob = {x.get("case"): x for x in m.get("robustness") or []}
            lis = [rob[c] for c in ("listener_side_1m", "listener_back_1m") if c in rob]
            if lis and not any(x.get("pass") for x in lis):
                steps.append(f"Stage {g[1]}: no displaced listener passes (robustness table, listener rows) — score "
                             "designs over several listener positions, or narrow the wedge.")
            jit = rob.get("jitter")
            if jit and not jit.get("pass"):
                steps.append(f"Stage {g[1]}: 5 mm / 1 mm placement jitter fails (robustness table, jitter row) — "
                             "prefer realizations whose echo does not hinge on exact spacing.")
            floor = (m.get("judge_floor") or {}).get("mean") or {}
            for x in t1:
                f = floor.get(x.get("id"))
                if f is not None and x.get("threshold") and x.get("comparator") == "<=" and f > 0.75 * x["threshold"]:
                    steps.append(f"Stage {g[1]}: the `{x['id']}` judge floor uses most of its threshold "
                                 "(metric table, judge-floor column) — even a perfect echo has little headroom; "
                                 "keep the judge fixed (integrity rule) and treat near-threshold results with care.")
    gated = [g[1] for g in STAGES if group_state(data, g) == "not_run" and g[1] > 1]
    if gated and group_state(data, STAGES[0]) != "pass":
        steps.append(f"Pass stage 1 on Tier 1 to unblock {ranges_text(gated)} (spec gate).")
    out += ["", "**What to try next, ranked (generated from the data above):**", ""]
    out += [f"{i}. {s}" for i, s in enumerate(steps, 1)] or ["Nothing generated: every run stage passed."]
    out += ["", "**Commentary** (hand-written, preserved between runs of the generator):", "",
            COMMENT_BEGIN, commentary.strip("\n"), COMMENT_END]
    return "\n".join(out)


def build_section(data: Data):
    if not data.build_md:
        return "`BUILD.md` does not exist yet."
    out = ["[`BUILD.md`](BUILD.md) is the plan from simulation to a real structure: a decision ladder (desk → 1:10 "
           "ultrasonic scale model → full-scale calibration posts → pilot), with a fabrication pack under `build/` "
           "(stake-out tables, templates, bill of materials, listening files). Its simulated numbers live in a "
           "generated block refreshed by `uv run python -m stages.build_pack --refresh-doc`."]
    m = re.search(r"<!-- BEGIN GENERATED.*?-->(.*?)<!-- END GENERATED", data.build_md, re.S)
    block_runs = sorted(set(re.findall(r"^\| (s\d\w*) \| (\S+) \|", m.group(1) if m else "", re.M)))
    newest = {st: r["run_id"] for g in STAGES for st, r in data.latest_by_stage(g[0]).items()}
    if block_runs:
        out.append("")
        out.append("Its generated block was computed from: " + ", ".join(f"`{s}/{r}`" for s, r in block_runs) + ".")
        stale = [s for s, r in block_runs if s in newest and newest[s] != r]
        if stale:
            out.append("**That block is stale**: newer final runs exist for " + ", ".join(
                f"`{s}` (`{newest[s]}`)" for s in stale) + "; its numbers describe the older design.")
    packs = sorted(p.name for p in (data.root / "build").glob("*") if p.is_dir()) if (data.root / "build").exists() else []
    if packs:
        out.append("Fabrication packs on disk: " + ", ".join(f"`build/{p}`" for p in packs) + ".")
    # status from the ledger: latest re-review line of the build-path task, plus any later build-path entries
    lines = [ln for ln in data.ledger.splitlines() if re.search(r"Task 13[ab]?", ln)]
    rev = [ln for ln in lines if "re-review" in ln]
    out += ["", "**Status: reviewed draft with open items.** The last independent re-review recorded in the ledger:", ""]
    if rev:
        out.append("> " + rev[-1].lstrip("- ").strip())
    later = [ln for ln in lines if "13b" in ln]
    if later:
        out += ["", "Related ledger entries:", ""] + [f"- {ln.lstrip('- ').strip()}" for ln in later]
    return "\n".join(out)


def _split_ruling(text):
    parts = [p.strip() for p in re.split(r"\s+—\s+", text)]
    cost_i = next((i for i, p in enumerate(parts) if i > 0 and re.search(r"\bcost|if wrong|risk is|cosmetic", p, re.I)), None)
    if cost_i is None:
        return parts[0], " — ".join(parts[1:]) or "—", "not stated"
    cost = " — ".join(parts[cost_i:])
    cost = re.split(r"(?<=[.])\s+(?=Task \d|Agent |\d\d:\d\d)", cost)[0]
    return parts[0], " — ".join(parts[1:cost_i]) or "—", cost


WITHDRAWN = [(r"bounds the effect at", "Later withdrawn: an independent re-review found that self-convergence cannot "
              "bound a bias both grids share; the effect on dense fields is not bounded.")]


def overnight(data: Data):
    out = ["Timeline from the controller's ledger (`.superpowers/sdd/plan/progress.md`), first sentence of each "
           "timed entry:", ""]
    for ln in data.ledger.splitlines():
        mm = re.match(r"^- (\d\d:\d\d) (.*)$", ln)
        if mm and not mm.group(2).startswith("Agent ids"):
            txt = mm.group(2)
            first = re.split(r"(?<=[a-z0-9)%][.])\s+(?=[A-Z])", txt)[0]
            if len(first) > 170:
                first = first[:167].rsplit(" ", 1)[0] + " …"
            out.append(f"- **{mm.group(1)}** {first}")
    out += ["", "**Rulings the controller made on the owner's behalf** (every `Ruling:` in the ledger, in order):", ""]
    rows = []
    for i, mm in enumerate(re.finditer(r"Ruling:\s*(.+)$", data.ledger, re.M), 1):
        ruling, reason, cost = _split_ruling(mm.group(1).strip())
        for pat, note in WITHDRAWN:
            if re.search(pat, reason) or re.search(pat, ruling):
                reason += f" **[{note}]**"
        rows.append([str(i), fmt(ruling), fmt(reason), fmt(cost)])
    out.append(table(["#", "ruling", "reason", "cost if wrong"], rows) if rows else "No rulings found in the ledger.")
    return "\n".join(out)


GROUPS = [
    ("Solver (Tier 1)", r"\[task 3"),
    ("Single-scattering model (Tier 0)", r"\[task 2"),
    ("Design pipeline, judges and stage driver", r"\[task [46]"),
    ("Speech targets and judges (stage 4 prep)", r"\[task 9"),
    ("Clap, targets, environment", r"\[task 1\b|\[task 1,"),
    ("Viewer", r"\[task 5"),
    ("Build path", r"\[task 13"),
]
DEVIATION = re.compile(r"It is not k-Wave|unlogged deviation|instead of|skipped|[Ss]witched|CPU index|"
                       r"global constraints say|CORRECTION|raised from|^\[task 6\] fragile =|FAILS|"
                       r"not validated|Validation verdict follows")


def deviations(data: Data):
    lines = [ln[2:].strip() for ln in data.decisions.splitlines() if ln.startswith("- [")]
    # supersession: drop lines a later line declares replaced
    text = data.decisions
    drop = set()
    if "supersedes the task-9 formant line" in text:
        drop |= {i for i, ln in enumerate(lines) if ln.startswith("[task 9] Formant judge")}
    if "SUPERSEDED: the earlier task-3 lines" in text:
        drop |= {i for i, ln in enumerate(lines) if ln.startswith("[task 3]") and
                 re.search(r"ppw 9 at|Within r \+ 5 dx|0\.912 at r/dx|^\[task 3\] SUPERSEDED", ln)}
    kept = [ln for i, ln in enumerate(lines) if i not in drop]
    out = ["Departures from the spec's letter, short form of the matching `DECISIONS.md` lines (first clause; "
           "superseded lines dropped). The other lines there record choices the spec left open.", ""]
    seen, others = set(), []
    for name, pat in GROUPS:
        items, n_other = [], 0
        for ln in kept:
            if not re.match(pat, ln):
                continue
            if not DEVIATION.search(ln):
                n_other += 1
                continue
            body = re.sub(r"^\[[^\]]+\]\s*", "", ln)
            short = re.split(r"\s+—\s+|(?<=[a-z0-9)][.])\s+(?=[A-Z])", body)[0]
            if len(short) > 260:
                short = short[:257].rsplit(" ", 1)[0] + " …"
            key = short.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append(short)
        if items:
            out += [f"**{name}**", ""] + [f"- {x}" for x in items] + [""]
        if n_other:
            others.append(f"{name.lower()}: {n_other}")
    if others:
        out.append("Other choices logged in [`DECISIONS.md`](DECISIONS.md) — " + "; ".join(others) + ".")
    return "\n".join(out)


def run_tests(root: Path):
    try:
        p = subprocess.run(["uv", "run", "pytest", "-q"], cwd=root, capture_output=True, text=True, timeout=1800)
        tail = [ln for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()]
        summary = tail[-1] if tail else "no output"
    except (OSError, subprocess.TimeoutExpired) as e:
        summary = f"could not run: {e}"
    return f"`uv run pytest -q` (default fast suite) on {_dt.datetime.now().astimezone().isoformat(timespec='minutes')}: `{summary.strip('= ')}`"


def _between(text, a, b):
    m = re.search(re.escape(a) + r"\n?(.*?)\n?" + re.escape(b), text, re.S)
    return m.group(1) if m else None


# ------------------------------------------------------------------------------------------------------------ assemble
def build_report(root: Path = ROOT, run_test_suite: bool = True) -> str:
    root = Path(root)
    old = (root / "REPORT.md").read_text() if (root / "REPORT.md").exists() else ""
    commentary = _between(old, COMMENT_BEGIN, COMMENT_END)
    if commentary is None:
        commentary = DEFAULT_COMMENTARY
    data = Data(root)
    if run_test_suite:
        tests = run_tests(root)
    else:
        tests = _between(old, TESTS_BEGIN, TESTS_END) or "Test suite not run by this generation (`--no-tests`)."
    stamp = _dt.datetime.now().astimezone().isoformat(timespec="minutes")
    parts = [
        banner(data), "",
        "# Composed Echo — morning report", "",
        f"*Generated {stamp} by `uv run python -m stages.report` from the files on disk; re-run it as results land. "
        "Open: [viewer](viewer/) · [explainer](explainer/index.html) · [build path](BUILD.md) · "
        "[decisions](DECISIONS.md).*", "",
        "## 1. Verdict", "", verdict(data), "",
        "## 2. How to look at the results", "", how_to_look(data), "",
        "## 3. Solver validation", "", validation_section(data), "",
        "## 4. Scorecards", "", "\n\n".join(scorecard(data, g) for g in STAGES), "",
        "## 5. Open questions from the spec", "", open_questions(data), "",
        "## 6. What limited each stage, and what to try next", "", next_steps(data, commentary), "",
        "## 7. Build path", "", build_section(data), "",
        "## 8. What happened overnight", "", overnight(data), "",
        "## 9. Deviations from the spec", "", deviations(data), "",
        "## 10. Tests", "", TESTS_BEGIN, tests, TESTS_END, "",
    ]
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--no-tests", action="store_true", help="reuse the test summary already in REPORT.md")
    a = ap.parse_args(argv)
    root = Path(a.root)
    text = build_report(root, run_test_suite=not a.no_tests)
    (root / "REPORT.md").write_text(text)
    print(text.splitlines()[0])


if __name__ == "__main__":
    main()
