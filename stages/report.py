"""Report generator: `uv run python -m stages.report` rewrites REPORT.md and the appendices under docs/report/
entirely from files on disk.

Inputs (read-only): runs/index.json and the run folders it lists (plus each stage's `_studies/*.json`),
runs/_criteria/summary.json (three verdicts per test: spec_v1, owner_v2, the owner's listening verdict),
runs/validation/metrics.json, listen/README.md, BUILD.md, build/*/pack.json, DECISIONS.md,
artifacts/speech/judge_sanity.json, artifacts/report/*.png and the controller ledger
.superpowers/sdd/plan/progress.md. Every number in the output is read from one of these files (or from the test-suite
summary line). Hand-written text lives only in the commentary block, which is preserved between runs.

REPORT.md is short and leads with what works; the full per-test scorecards, validation, design studies, criteria,
timeline with every ruling, and deviations go to docs/report/*.md. The three verdicts are never merged into one tally:
spec_v1 (original spec thresholds) is pass/fail; owner_v2 (revised, listening-calibrated thresholds) is PASS or
"not established" on the runs it was calibrated on; the listening verdict is a human judgment and always carries
"not blind" when it was not blind.

Results are grouped into units of the spec's stage table (1, 2, 3, 4a, 4b, 4c); inside a unit runs are grouped by
member (stage 3: note length; stage 4b: syllable). The newest final run of a member is its result in the scorecards;
the run the owner listened to (summary.json `accepted_runs`) is the run the three verdicts are about.

Options: --no-tests reuses the test summary already in REPORT.md instead of running `uv run pytest -q`;
--reset-commentary replaces the preserved commentary block with the default text in this file.
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
MAX_ROWS = 12

# Units of the spec's stage table: (unit id, title, stage prefix, sub-stage or None, label in the banner)
UNITS = [
    ("1", "Stage 1 — Bird note", "s1", None, "Stage 1"),
    ("2", "Stage 2 — Motif", "s2", None, "Stage 2"),
    ("3", "Stage 3 — Melody", "s3", None, "Stage 3"),
    ("4a", "Stage 4a — Vowel", "s4", "4a", "Stage 4a"),
    ("4b", "Stage 4b — Syllables", "s4", "4b", "4b"),
    ("4c", "Stage 4c — Word", "s4", "4c", "4c"),
]
DEFAULT_COMMENTARY = """\
*Commentary (hand-written, no numbers; the generated sections carry the values and their sources).*

**What to take away.** One design family works in simulation and is worth building toward: the ring-layout whistle.
It is the only result that a listener (the owner, knowing the target) accepted and that an automated test also
confirms against negative controls. It still misses the spec's original strict marks, narrowly, next to judges that
score a perfect echo close to those marks too. The other results were accepted by ear (not blind) but no automated test confirms
them; they are recorded, not chased.

**Why the verdicts differ.** The original thresholds measure fidelity strictly (worst-frame pitch, spectrogram
match over a wide dynamic range). The revised criteria ask a narrower question: is the echo nearer its own target than
to plausible wrong answers, and is its pitch right, on most claps? The owner's ear asks the widest one, with the
target in mind. No single verdict replaces the others, and a blind listening test has not been run yet.

**What decides the real thing.** Whether a person hears an echo that arrives tens of dB under their own clap is a
question about hearing, not acoustics; simulation cannot answer it. The build path therefore starts with a cheap
outdoor hearing test and a tabletop scale model, before any full-size structure.
"""

NEXT_STEPS = [
    "Build the 1:10 ultrasonic scale model (BUILD.md phase 2a): it measures the real broadband residue and extinction "
    "of thin posts, which is the open question behind the stage-1 near miss.",
    "Solver: separate monopole/dipole calibration for sub-cell posts and an exact multi-cylinder check, so dense "
    "fields are validated against theory, not only self-convergence.",
    "Solver speed: use the CFL margin a reviewer measured (about twice the time step), then a GPU or 3D-aware solver "
    "for the long stages, so melody and speech can be simulated in the full fan instead of a strip.",
    "Optimize post positions directly: first on the fast model with the real posts, then against the full-wave "
    "solver, instead of solving a continuous profile and realizing it afterwards.",
    "For demonstrations, a narrow-band or shaped excitation instead of a clap removes the spectrum tilt.",
    "Idea only (spec non-goal): resonant or absorbing elements would allow signed reflectivity and shorter "
    "structures.",
]


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
    """Value formatting by metric: percentages and dB with 2 decimals, correlations/fractions with 3.
    note_cents_max = 1200 is echo.metrics.note_sequence_score's sentinel for "notes not matched", not a measurement."""
    if mid == "note_cents_max" and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 1200.0:
        return "1200 (sentinel: notes not matched)"
    if isinstance(v, float) and not (math.isnan(v) or math.isinf(v)):
        if mid.endswith(("_pct", "_db", "_m", "_s", "_hz", "cents")) or abs(v) >= 10:
            return f"{v:.2f}"
        return f"{v:.3g}" if abs(v) < 0.1 and v != 0 else f"{v:.3f}"
    if isinstance(v, (list, tuple)):
        if v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            head = ", ".join(num(float(x), mid) if isinstance(x, float) else str(x) for x in v[:8])
            return head + (f", … ({len(v)} values)" if len(v) > 8 else "")
        return fmt(list(v[:8])) + (f", … ({len(v)} values)" if len(v) > 8 else "")
    return fmt(v)


def pf(p):
    return "—" if p is None else ("PASS" if p else "FAIL")


def table(header, rows):
    out = ["| " + " | ".join(fmt(h) for h in header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(fmt(c) if not isinstance(c, str) else c.replace("\n", " ").replace("|", "\\|")
                                     for c in r) + " |")
    return "\n".join(out)


def rel(root: Path, p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(p)


def sanitize_caveat(text: str) -> str:
    """Drop the withdrawn 'effect bounded at X dB' inference (a review found self-convergence cannot bound a bias
    both grids share) wherever an older run file still carries it."""
    return re.sub(r"(its |the )?effect on dense-field echoes is bounded at [^;)]*(\([^)]*\))?",
                  "effect on dense-field echoes is not bounded (this run file states a bound; an independent review "
                  "found that inference invalid and it is withdrawn)", text)


def flatten(d, prefix=""):
    """One-level flatten of a dict for table columns: nested scalar dicts become 'a.b' columns; lists of scalars
    stay (shortened by num); lists of dicts are dropped."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if not isinstance(v2, (dict, list)) or (isinstance(v2, list) and v2 and not isinstance(v2[0], dict)):
                    out[f"{prefix}{k}.{k2}"] = v2
        elif isinstance(v, list) and v and isinstance(v[0], (dict, list)):
            continue
        else:
            out[prefix + k] = v
    return out


def rows_table(rows, src="", key="", max_rows=MAX_ROWS, max_cols=12, cols=None):
    rows = [flatten(r) for r in rows if isinstance(r, dict)]
    if not rows:
        return ""
    keys = cols or []
    if not keys:
        for r in rows:
            keys += [k for k in r if k not in keys and not k.startswith("history")]
    keys = keys[:max_cols]
    out = table(keys, [[num(r.get(k), k) for k in keys] for r in rows[:max_rows]])
    extra = []
    if len(rows) > max_rows:
        extra.append(f"{len(rows) - max_rows} more rows")
    if cols is None and len({k for r in rows for k in r}) > max_cols:
        extra.append("more columns")
    if extra and src:
        out += f"\n\n*({' and '.join(extra)} in `{src}`" + (f" key `{key}`" if key else "") + ".)*"
    return out


def parallel_table(d, src="", key=""):
    """A dict of equal-length scalar lists (≤ 24 long) as a table, one row per index."""
    lists = {k: v for k, v in d.items() if isinstance(v, list) and v and not isinstance(v[0], (dict, list))}
    if not lists:
        return ""
    n = max(len(v) for v in lists.values())
    cols = [k for k, v in lists.items() if len(v) == n]
    if n > 24 or len(cols) < 2:
        return ""
    return table(["#"] + cols, [[str(i + 1)] + [num(d[c][i], c) for c in cols] for i in range(n)])


def render_block(obj, src, key, depth=0):
    """Compact generic rendering of a metrics block: text, scalars as a list, lists of dicts as capped tables,
    parallel arrays as a table, long arrays summarized. Never dumps more than MAX_ROWS rows."""
    if isinstance(obj, str):
        return fmt(obj)
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            return rows_table(obj, src, key)
        return num(obj)
    if not isinstance(obj, dict):
        return num(obj, key)
    out, scal = [], []
    par = parallel_table(obj, src, key)
    used = set()
    if par:
        n = max(len(v) for v in obj.values() if isinstance(v, list))
        used = {k for k, v in obj.items() if isinstance(v, list) and len(v) == n and v and not isinstance(v[0], (dict, list))}
    for k, v in obj.items():
        if k in used:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            scal.append(f"- {k}: {num(v, k)}")
        elif isinstance(v, list) and (not v or not isinstance(v[0], (dict, list))):
            scal.append(f"- {k}: {num(v, k)}")
    out += scal
    if par:
        out += ["", par]
    for k, v in obj.items():
        if k in used or isinstance(v, (str, int, float, bool)) or v is None:
            continue
        if isinstance(v, list) and (not v or not isinstance(v[0], (dict, list))):
            continue
        if depth >= 2:
            out.append(f"- {k}: see `{src}` key `{key}.{k}`")
            continue
        out += ["", f"*{k}:*", "", render_block(v, src, f"{key}.{k}", depth + 1)]
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------- data model
def parse_listen(path: Path):
    """listen/README.md table -> {run tag: {true_db, boost_db, spl_db, title}} (empty when missing)."""
    out = {}
    try:
        text = Path(path).read_text()
    except OSError:
        return out
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 7 or not cells[2].startswith("`"):
            continue
        tag = cells[2].strip("`")

        def f(x):
            try:
                return float(x)
            except ValueError:
                return None
        out[tag] = {"true_db": f(cells[3]), "boost_db": f(cells[4]), "spl_db": f(cells[5]), "title": cells[6]}
    return out


def run_tag(run_id: str) -> str:
    """'20261125-104529-s1' -> 's1' (the tag used by listen/)."""
    parts = run_id.split("-", 2)
    return parts[2] if len(parts) == 3 else run_id


def unit_of(run):
    m = re.match(r"s(\d)", run.get("stage", ""))
    if not m:
        return None
    n = m.group(1)
    if n != "4":
        return n
    sub = (run["metrics"].get("substage") or run["manifest"].get("substage")
           or (re.search(r"_(4[abc])", run.get("run_id", "")) or [None, None])[1])
    return sub or "4"


def member_of(run):
    u = unit_of(run)
    met, man = run["metrics"], run["manifest"]
    if u == "3":
        ms = (met.get("s3_extra") or {}).get("note_ms")
        if ms is None:
            mm = re.search(r"_(\d+)ms", run.get("run_id", ""))
            ms = int(mm.group(1)) if mm else 100
        return f"{ms} ms"
    if u == "4b":
        return met.get("target_name") or man.get("target_name") or run.get("run_id", "").rsplit("_", 1)[-1]
    return ""


class Data:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.runs_dir = self.root / "runs"
        idx = _load(self.runs_dir / "index.json") or {}
        self.index = [r for r in idx.get("runs", []) if isinstance(r, dict)]
        self.validation = _load(self.runs_dir / "validation" / "metrics.json")
        self.val_path = "runs/validation/metrics.json"
        self.ledger = (self.root / LEDGER).read_text() if (self.root / LEDGER).exists() else ""
        # no machine-specific paths in the published documents (the ledger is a local file)
        self.ledger = self.ledger.replace(str(self.root.resolve()) + "/", "").replace(str(self.root.resolve()), "this repository's folder")
        self.decisions = (self.root / "DECISIONS.md").read_text() if (self.root / "DECISIONS.md").exists() else ""
        self.build_md = (self.root / "BUILD.md").read_text() if (self.root / "BUILD.md").exists() else ""
        self.speech = _load(self.root / "artifacts" / "speech" / "judge_sanity.json")
        self.criteria = _load(self.runs_dir / "_criteria" / "summary.json")
        self.listen = parse_listen(self.root / "listen" / "README.md")
        self.prefix = ""  # path prefix for links written into appendices (docs/report/ -> "../../")
        self.runs, self.other, self.seen = [], [], {}
        for r in sorted(self.index, key=lambda r: (r.get("created", ""), r.get("run_id", "")), reverse=True):
            d = self.runs_dir / r.get("path", "")
            run = dict(r, dir=d, rel=rel(self.root, d), metrics=_load(d / "metrics.json") or {},
                       manifest=_load(d / "manifest.json") or {})
            u = unit_of(run)
            if u is None:
                self.other.append(run)  # e.g. build_pilot: never counted as a stage
                continue
            run["unit"], run["member"] = u, member_of(run)
            self.runs.append(run)
        self.by_id = {r["run_id"]: r for r in self.runs + self.other if r.get("run_id")}

    @property
    def val_passed(self):
        return bool(self.validation and self.validation.get("passed") is True)

    def unit_runs(self, uid, final=True):
        return [r for r in self.runs if r["unit"] == uid and (not final or r.get("status") == "final")]

    def members(self, uid):
        """{member: [final runs, newest first]}; members ordered by their first run (oldest first), except stage 3
        which lists the longest note first (the spec's pass condition)."""
        out = {}
        for r in self.unit_runs(uid):
            out.setdefault(r["member"], []).append(r)
        if uid == "3":
            def ms(k):
                d = re.match(r"(\d+)", k)
                return -int(d.group(1)) if d else 0
            return dict(sorted(out.items(), key=lambda kv: ms(kv[0])))
        return dict(sorted(out.items(), key=lambda kv: kv[1][-1].get("created", "")))

    def results(self, uid):
        return {m: rs[0] for m, rs in self.members(uid).items()}

    def units(self):
        ids = [u[0] for u in UNITS]
        has4 = any(r["unit"] == "4" for r in self.runs)
        out = [u for u in UNITS]
        if has4:
            out.append(("4", "Stage 4 — Speech (no sub-stage recorded)", "s4", None, "Stage 4"))
        return [u for u in out if u[0] in ids or u[0] == "4"]


def run_passed(run):
    return bool((run.get("metrics") or {}).get("passed", run.get("passed")))


def run_verified(run):
    return bool((run.get("metrics") or {}).get("verified", run.get("verified")))


def gating(run, tier=None):
    ms = (run.get("metrics") or {}).get("metrics") or []
    return [m for m in ms if m.get("gating") and (tier is None or m.get("tier") == tier)]


def unit_state(data: Data, uid):
    """'pass' | 'fail' | 'not_run', plus '_unverified' when any result run is unverified."""
    res = data.results(uid)
    if not res:
        return "not_run"
    decisive = [res["100 ms"]] if uid == "3" and "100 ms" in res else list(res.values())
    ok = all(run_passed(r) for r in decisive)
    ver = all(run_verified(r) for r in res.values())
    return ("pass" if ok else "fail") + ("" if ver else "_unverified")


def unit_label(data, u):
    mem = [m for m in data.members(u[0]) if m]
    tail = ""
    if len(mem) > 1:
        tail = " (" + ", ".join(mem[:-1]) + f" and {mem[-1]})"
    return u[4], tail


# ------------------------------------------------------------------------------------------------------------ sections
def banner(data: Data):
    parts, npass, nrun = [], 0, 0
    for u in data.units():
        st = unit_state(data, u[0])
        lab, tail = unit_label(data, u)
        if st == "not_run":
            parts.append(f"{lab} not run")
            continue
        nrun += 1
        word = "passed" if st.startswith("pass") else "failed"
        npass += word == "passed"
        parts.append(f"{lab} {word}{tail}" + (" (unverified)" if st.endswith("_unverified") else ""))
    n = len(data.units())
    head = "RESULTS" if nrun == n else "INTERIM"
    tally = f"{npass} of {n} passed on the full-wave solver" + ("" if nrun == n else f", {n - nrun} not run")
    line = f"**{head} — {tally}: " + " · ".join(parts) + ".**"
    if not data.val_passed:
        line = "UNVERIFIED — the full-wave solver has not passed validation; every result below is unverified. " + line
    return line


def gate_note(data: Data):
    st1 = unit_state(data, "1")
    later = [u for u in data.units() if u[0] != "1" and unit_state(data, u[0]) != "not_run"]
    if st1 != "pass" and later:
        rul = [m.group(1) for m in re.finditer(r"Ruling:\s*(.+)$", data.ledger, re.M)
               if re.search(r"stage 1 has not passed|without a stage-1 pass", m.group(1))]
        txt = ("The spec's gate says stage 1 must pass on Tier 1 before stage 2 starts. Stage 1 has not passed and "
               "later stages were run anyway (a gate deviation, ruled by the controller)")
        return txt + (": " + fmt(rul[0].split(" — ")[1]) + "." if rul and " — " in rul[0] else ".")
    return ""


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
    for u in data.units():
        res = data.results(u[0])
        if not res:
            s.append(f"{u[1]}: not run. {not_run_reason(data, u)}")
            continue
        st = unit_state(data, u[0])
        bits = []
        for mem, r in res.items():
            m = r["metrics"]
            h = m.get("headline") or {}
            gm = gating(r, "tier1") or gating(r)
            vals = "; ".join(f"{x.get('id')} {num(x.get('value'), x.get('id') or '')} (needs {x.get('comparator')} "
                             f"{num(x.get('threshold'), x.get('id') or '')})" for x in gm)
            bits.append((f"{mem}: " if mem else "") + ("passed" if run_passed(r) else "failed")
                        + f" ({vals}); echo {num(h.get('echo_level_db_re_direct'), '_db')} dB re direct, "
                          f"{num(h.get('echo_spl_db'), '_db')} dB SPL, {fmt(h.get('post_count'))} posts over "
                          f"{num(h.get('depth_m'), '_m')} m")
            if run_passed(r) and m.get("pass_weight"):
                bits[-1] += f" — weight: {fmt(m['pass_weight'])}"
        word = "PASSED" if st.startswith("pass") else "FAILED"
        s.append(f"**{u[1]} {word}** on the full-wave solver: " + " · ".join(bits) + ".")
    g = gate_note(data)
    if g:
        s.append(g)
    return "\n\n".join(s)


def not_run_reason(data: Data, u):
    if u[0] == "1":
        return "No final stage-1 run exists yet."
    if unit_state(data, "1") != "pass" and not any(r for r in data.runs if r["unit"] != "1"):
        return ("The spec's gate says stage 1 must pass on Tier 1 before any work starts on stage 2; stage 1 has "
                "not passed, so later stages wait.")
    return "No final run exists yet for this stage."


def _shot_key(r):
    return r["unit"] + (f"-{r['member'].replace(' ', '')}" if r["member"] else "")


def how_to_look(data: Data):
    out = ["Serve the repo with the lab server (`uv run python -m echo.lab`, default port 8000; `--port` to change) "
           "and open `/viewer/` (`?run=<stage>/<run_id>` opens a given run) or `/explainer/`.", ""]
    rows = []
    for u in data.units():
        for mem, rs in data.members(u[0]).items():
            for r in rs:
                d = r["dir"]
                echo = "echo_tier1.wav" if (d / "echo_tier1.wav").exists() else "echo_tier0.wav"
                files = [f"`{r['rel']}/{f}`" if (d / f).exists() else f"{f} missing"
                         for f in ("target.wav", echo, "as_heard.wav")]
                lvl = ((r.get("manifest") or {}).get("audio") or {}).get("as_heard_echo_level_db")
                role = "result" if r is rs[0] else "earlier attempt"
                rows.append([u[0] + (f" {mem}" if mem else ""), f"`{r['run_id']}`", role, pf(run_passed(r)), *files,
                             f"{num(lvl, '_db')} dB"])
    if rows:
        out += ["Audio for every final run (target / echo / as heard: the direct clap followed by the echo at its "
                "true relative level, which is why the echo is barely audible in that file):", "",
                table(["unit", "run", "role", "result", "target", "echo", "as heard", "echo level in as-heard"], rows)]
    else:
        out.append("No final runs yet, so no audio to list.")
    keys = {_shot_key(rs[0]): rs[0] for u in data.units() for rs in data.members(u[0]).values()}
    shots = sorted((data.root / "artifacts" / "report").glob("viewer-*.png"))
    for p in shots:
        k = p.stem.removeprefix("viewer-")
        taken = _dt.datetime.fromtimestamp(p.stat().st_mtime).astimezone()
        r = keys.get(k)
        note = ""
        if r is None:
            note = " (no current result run has this key)"
        else:
            try:
                if _dt.datetime.fromisoformat(r.get("created", "")) > taken:
                    note = f" **Older than the result run `{r['run_id']}`: retake it.**"
            except ValueError:
                pass
            if not (r.get("manifest") or {}).get("field"):
                note += " This run has no field video (`manifest.field` is null)."
        out += ["", f"Viewer, {k}" + (f" — run `{r['run_id']}`" if r else "") +
                f" (screenshot taken {taken.isoformat(timespec='minutes')}).{note}", "",
                f"![viewer screenshot, {k}]({data.prefix}{rel(data.root, p)})"]
    missing = [k for k in keys if not (data.root / "artifacts" / "report" / f"viewer-{k}.png").exists()]
    if missing:
        out += ["", "No viewer screenshot yet for: " + ", ".join(f"`{k}`" for k in missing) + "."]
    ex = data.root / "artifacts" / "report" / "explainer-results.png"
    if ex.exists():
        out += ["", "Explainer, results section:", "", f"![explainer results section]({data.prefix}{rel(data.root, ex)})"]
    return "\n".join(out)


def _grids(v):
    cyl = ((v or {}).get("checks") or {}).get("cylinder") or {}
    return {k: g for k, g in cyl.items() if k.endswith("_grid") and isinstance(g, dict)}


def _radii_used(r):
    ver = r["metrics"].get("verification") or {}
    if ver.get("radii_used"):
        return [float(x) for x in ver["radii_used"]]
    sc = _load(r["dir"] / "scene.json") or {}
    return sorted({round(float(p[2]), 4) for p in sc.get("posts") or [] if len(p) > 2})


def validation_section(data: Data):
    v = data.validation
    if v is None:
        return "UNVERIFIED: `runs/validation/metrics.json` does not exist."
    c = v.get("checks") or {}
    cyl = c.get("cylinder") or {}
    grids = _grids(v)
    g1 = grids.get("stage1_grid") or {}
    pr1 = g1.get("per_radius") or {}
    worst_back = max((x.get("max_abs_err_db") for x in pr1.values() if x.get("max_abs_err_db") is not None),
                     default=None)
    gc = c.get("grid_convergence") or {}
    es = c.get("empty_scene") or {}
    tt = c.get("tier0_vs_tier1") or {}
    rows = [
        ["1. Single rigid cylinder, backscatter vs analytic (stage-1 grid, all catalog radii)",
         f"worst {num(worst_back, '_db')} dB", f"≤ {fmt(cyl.get('threshold_db'), 1)} dB", pf(cyl.get("pass")),
         "checks.cylinder.stage1_grid.per_radius.*.max_abs_err_db"],
        ["2. Grid convergence (halve dx), sparse reference design",
         f"{num((gc.get('sparse') or {}).get('max_abs_delta_db'), '_db')} dB", "< 1 dB",
         pf((gc.get("sparse") or {}).get("pass")), "checks.grid_convergence.sparse.max_abs_delta_db"],
        ["2b. Grid convergence, dense patch (self-convergence only)",
         f"{num((gc.get('dense') or {}).get('max_abs_level_delta_db'), '_db')} dB", "< 1 dB",
         pf((gc.get("dense") or {}).get("pass")), "checks.grid_convergence.dense.max_abs_level_delta_db"],
        ["3. Empty scene: nothing after the direct clap", f"{fmt(es.get('max_after_direct_db'), 1)} dB",
         f"< {fmt(es.get('threshold_db'), 0)} dB", pf(es.get("pass")), "checks.empty_scene.max_after_direct_db"],
        ["4. Tier 0 vs Tier 1, sparse design", f"{num(tt.get('max_abs_delta_db'), '_db')} dB",
         f"≤ {fmt(tt.get('threshold_db'), 1)} dB", pf(tt.get("pass")), "checks.tier0_vs_tier1.max_abs_delta_db"],
    ]
    solver = v.get("solver") or {}
    out = [f"Source: `{data.val_path}` (engine `{fmt(solver.get('engine'))}`, {fmt(solver.get('ppw'), 0)} points "
           f"per wavelength). Overall `passed`: **{fmt(v.get('passed'))}**.", "",
           table(["check", "value", "threshold", "result", "key"], rows), ""]
    prow = []
    ext = (v.get("extended_checks") or {}).get("angular_scattering") or {}
    for gname, g in sorted(grids.items(), key=lambda kv: -(kv[1].get("f_max") or 0)):
        eg = (ext.get(gname) or {}).get("per_radius") or {}
        for r, x in (g.get("per_radius") or {}).items():
            e = eg.get(r) or {}
            prow.append([f"{fmt(g.get('f_max'), 0)} Hz (`{gname}`)", f"{float(r) * 100:.0f} cm",
                         num(x.get("max_abs_err_db"), "_db"), pf(x.get("pass")), num(e.get("forward"), "_db"),
                         num(e.get("bistatic_90"), "_db"), num(x.get("max_abs_err_db_all_angles"), "_db"),
                         pf(x.get("pass_all_angles"))])
    out += ["Per grid and post radius (error vs the analytic cylinder, dB; forward and 90° are an extended check "
            "beyond the spec):", "",
            table(["grid f_max", "radius", "backscatter err", "spec check", "forward err", "90° err",
                   "worst any angle", "all angles"], prow), ""]
    # per stage: grid and radius used
    srows = []
    for u in data.units():
        for mem, r in data.results(u[0]).items():
            fmax = ((r["manifest"].get("solver") or {}).get("f_max"))
            g = next((g for g in grids.values() if fmax and abs((g.get("f_max") or 0) - fmax) < 1), None)
            for rad in _radii_used(r) or [None]:
                key = None if rad is None or g is None else next(
                    (k for k in (g.get("per_radius") or {}) if abs(float(k) - rad) < 1e-6), None)
                pr = (g or {}).get("per_radius", {}).get(key) if key else None
                srows.append([u[0] + (f" {mem}" if mem else ""), f"{fmt(fmax, 0)} Hz",
                              f"{rad * 100:.0f} cm" if rad else "—",
                              pf(pr.get("pass")) if pr else "no validated grid",
                              pf(pr.get("pass_all_angles")) if pr else "—"])
    if srows:
        out += ["Grid and post radius each result used, and whether those posts are validated there:", "",
                table(["unit", "grid f_max", "post radius", "backscatter-validated", "all-angle-validated"], srows),
                ""]
    cav = ["**What this validation does and does not show:**", "",
           "- Tier 1 is validated against exact theory only for single-post backscatter."]
    for gname, g in sorted(grids.items(), key=lambda kv: -(kv[1].get("f_max") or 0)):
        all_r = [float(a) for a in g.get("validated_radii_all_angles") or []]
        bad = [r for r in (g.get("per_radius") or {}) if float(r) not in all_r]
        eg = (ext.get(gname) or {}).get("per_radius") or {}
        det = "; ".join(f"{float(r) * 100:.0f} cm: forward {num((eg.get(r) or {}).get('forward'), '_db')} dB, 90° "
                        f"{num((eg.get(r) or {}).get('bistatic_90'), '_db')} dB off" for r in bad if r in eg)
        notb = [r for r in (g.get("per_radius") or {}) if not (g["per_radius"][r] or {}).get("pass")]
        cav.append(f"- At the {fmt(g.get('f_max'), 0)} Hz grid only "
                   + (", ".join(f"{a * 100:.0f} cm" for a in all_r) or "no")
                   + " posts match the analytic cylinder at all angles" + (f" ({det})" if det else "")
                   + (f"; {', '.join(f'{float(r) * 100:.0f} cm' for r in notb)} posts are not validated even in "
                      "backscatter" if notb else "") + ".")
    ac = solver.get("area_cal") or {}
    facs = [x for x in ac.values() if isinstance(x, (int, float)) and x != 1.0]
    cav.append("- The 1 cm backscatter match relies on an area factor fitted to backscatter"
               + (f" (factor {fmt(facs[0], 3)}, `solver.area_cal`)" if facs else "") + "; held-out offsets confirm "
               "backscatter only.")
    dn = gc.get("dense") or {}
    cav.append("- Shadowing and multiple scattering in dense fields are checked by self-convergence only (production "
               f"grid vs twice as fine, {fmt(dn.get('n_posts'))} posts), not against an exact solution. A bias shared "
               "by both grids would not show, so the effect of the angular errors above on dense-field echoes is "
               "not bounded.")
    src = dn.get("source_scene")
    if src:
        gone = not (data.root / src).exists()
        cav.append(f"- Reproducibility of the dense-patch check: `stages/validate.py` takes the latest stage-1 scene at "
                   f"the time it runs; the scene it used is `{src}` (`checks.grid_convergence.dense.source_scene`)"
                   + (", a run folder that was later deleted, so this check cannot be re-run exactly on the same posts "
                      "(the solver and the validation file are frozen; the check was not re-run)." if gone else "."))
    cav += ["", "Caveats as recorded in the file (`caveats`):", ""]
    cav += [f"- {sanitize_caveat(fmt(x))}" for x in (v.get("caveats") or [])]
    return "\n".join(out + cav)


# ----------------------------------------------------------------------------------------------------------- run card
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


# Gating metrics whose threshold counts claps across the family (hello_count >= 3 of 5). echo.robustness judges each
# "clap variant alone" case against the same rule, which one clap can never meet: presented as "not applicable".
COUNT_RULES = {"hello_count"}
NA_CLAP = "not applicable (the rule counts claps: at least 3 of 5; one clap alone cannot meet it)"


def count_rule(run):
    return any(x.get("id") in COUNT_RULES for x in gating(run, "tier1") or gating(run))


def fragile_text(run):
    """metrics.fragile_reason, with the per-clap count replaced by "not applicable" for count rules."""
    fr = (run.get("metrics") or {}).get("fragile_reason")
    if fr and count_rule(run):
        fr = re.sub(r"\d+/\d+ clap variants pass on their own", "clap variants alone: not applicable (count rule)", fr)
    return fr


def _robust_table(run):
    m = run["metrics"]
    ids = [x["id"] for x in gating(run, "tier1") or gating(run)]
    cr = count_rule(run)
    if not ids:
        ids = sorted({k for r in m.get("robustness") or [] for k in (r.get("metrics") or {})})
    rows = []
    for r in m.get("robustness") or []:
        mm, dd = r.get("metrics") or {}, r.get("delta") or {}
        rows.append([fmt(r.get("label")) + f" (`{r.get('case')}`)"] +
                    [f"{num(mm.get(i), i)} ({fmt(dd.get(i), 2 if i.endswith('_pct') else 3, signed=True)})"
                     for i in ids] + [NA_CLAP if cr and re.fullmatch(r"clap_\d+", str(r.get("case"))) else pf(r.get("pass"))])
    nr = list(m.get("robustness_not_run") or []) + list((m.get("s3_extra") or {}).get("robustness_not_run") or [])
    for r in nr:
        rows.append([fmt(r.get("label")) + f" (`{r.get('case')}`)"] + [fmt(r.get("status") or "not run")] * len(ids)
                    + [fmt(r.get("status") or "not run")])
    out = table(["case"] + [f"{i} (delta)" for i in ids] + ["passes"], rows)
    if m.get("robustness_not_run_reason"):
        out += f"\n\nNot run, reason recorded in the file: {fmt(m['robustness_not_run_reason'])}"
    return out


def _pass_weight(data: Data, run):
    """Everything that weighs a pass, beside it."""
    m = run["metrics"]
    src = f"{run['rel']}/metrics.json"
    out = [f"**Weight of this pass** (`pass_weight`): {fmt(m.get('pass_weight') or 'not recorded')}", ""]
    floor = (m.get("judge_floor") or {}).get("mean") or {}
    vals = {x["id"]: x for x in m.get("metrics") or [] if x.get("tier") == "tier1"}
    rows = [[f"`{i}`", num(x.get("value"), i), num(floor.get(i), i)] for i, x in vals.items() if i in floor]
    if rows:
        out += ["Tier 1 values next to the same judges on a physically perfect echo (`judge_floor.mean`):", "",
                table(["metric", "this echo", "perfect echo"], rows), ""]
    if m.get("band_hz"):
        out.append(f"- Referee band: {fmt(m['band_hz'], 0)} Hz (`band_hz`); full-band Tier 0 of the same posts is "
                   "in `tier0_full_band_info`.")
    rt = m.get("recognized_text")
    if rt:
        out.append("- Recognized text per clap (`recognized_text`): " + "; ".join(
            f"clap {x.get('clap')}: “{fmt(x.get('transcript'))}”" for x in rt) + ".")
    rob = {x.get("case"): x for x in m.get("robustness") or []}
    for c in ("listener_side_1m", "listener_back_1m"):
        if c in rob:
            out.append(f"- {fmt(rob[c].get('label'))}: {pf(rob[c].get('pass'))} (`robustness[case={c}]`).")
    ctl = (m.get("recognizer_controls") or {}).get("cases") or {}
    if ctl:
        out += ["", "Controls — the same recognizer on wrong echoes (`recognizer_controls.cases`):", "",
                table(["control", "\"hello\" count", "ESTOI vs hello (mean)", "transcripts"],
                      [[k, fmt(c.get("hello_count")), num(c.get("estoi_vs_hello_mean")),
                        "; ".join(fmt(t.get("transcript")) for t in c.get("recognized_text") or [])]
                       for k, c in ctl.items()])]
    sp = ((data.speech or {}).get("s4c_word") or {}).get("rows") or {}
    n0 = sp.get("target_plus_noise_0db")
    if n0 and m.get("judge_stage") == "s4c_word":
        out += ["", f"- Preparation finding (not a stage-4 result): on the clean target plus white noise at 0 dB SNR "
                f"the recognizer also returned “{fmt(n0.get('transcript'))}” (hit: {fmt(n0.get('hit'))}) — "
                "`artifacts/speech/judge_sanity.json` key `s4c_word.rows.target_plus_noise_0db`. It is lenient."]
    return "\n".join(out)


def _config_diff(newer, older):
    a = ((older["manifest"].get("design") or {}).get("config")) or {}
    b = ((newer["manifest"].get("design") or {}).get("config")) or {}
    skip = {"threads", "design_study_files", "notes", "title", "status"}
    d = [f"{k}: {num(a.get(k), k)} → {num(b.get(k), k)}" for k in sorted(set(a) | set(b))
         if k not in skip and a.get(k) != b.get(k)]
    return "; ".join(d) or "—"


def attempts_table(rs):
    """All final runs of one member, newest first; 'what changed' = design-config keys that differ from the
    previous attempt (manifest.design.config)."""
    rows = []
    for i, r in enumerate(rs):
        h = r["metrics"].get("headline") or {}
        g = "; ".join(f"{x.get('id')} {num(x.get('value'), x.get('id') or '')}" for x in gating(r, "tier1"))
        ch = _config_diff(r, rs[i + 1]) if i + 1 < len(rs) else "first attempt"
        rows.append([f"`{r['run_id']}`" + (" (result)" if i == 0 else ""), pf(run_passed(r)), g or "—",
                     num(h.get("echo_level_db_re_direct"), "_db"), fmt(h.get("post_count")),
                     num(100 * h["fill_fraction"] if h.get("fill_fraction") is not None else None, "_pct"),
                     num(h.get("tier_gap_db"), "_db"), ch])
    return table(["run", "result", "gating (Tier 1)", "echo dB re direct", "posts", "fill %", "tier gap dB",
                  "what changed vs the previous attempt (design config)"], rows)


def _studies(run):
    d = run["dir"].parent / "_studies"
    return sorted(d.glob("*.json")) if d.exists() else []


def run_card(data: Data, r, heading):
    m, mf = r["metrics"], r["manifest"]
    h = m.get("headline") or {}
    src = f"{r['rel']}/metrics.json"
    out = [heading, "",
           f"Run `{r['rel']}` ({fmt(r.get('title'))}), created {fmt(r.get('created'))}, solver "
           f"`{fmt((mf.get('solver') or {}).get('tier1'))}` engine `{fmt((mf.get('solver') or {}).get('engine'))}`, "
           f"grid f_max {fmt((mf.get('solver') or {}).get('f_max'), 0)} Hz, verified: {fmt(run_verified(r))}. "
           f"Source: `{src}`.", ""]
    if run_passed(r):
        out += [_pass_weight(data, r), ""]
    spl = h.get("echo_spl_db")
    flag = " — **below 35 dB: likely inaudible on site**" if h.get("likely_inaudible_on_site") else ""
    fill = h.get("fill_fraction")
    hrows = [
        ["Echo level, 3D estimate, tier-gap corrected", f"{num(h.get('echo_level_db_re_direct'), '_db')} dB re direct",
         "headline.echo_level_db_re_direct"],
        ["Echo level, raw 3D (Tier 0)", f"{num(h.get('echo_level_db_re_direct_raw3d'), '_db')} dB re direct",
         "headline.echo_level_db_re_direct_raw3d"],
        ["Echo level for a 100 dB clap", f"{num(spl, '_db')} dB SPL{flag}", "headline.echo_spl_db"],
        ["Structure depth (bistatic range)", f"{num(h.get('depth_m'), '_m')} m", "headline.depth_m"],
        ["Post count", fmt(h.get("post_count")), "headline.post_count"],
        ["Fill fraction of the wedge", f"{num(100 * fill if fill is not None else None, '_pct')} %",
         "headline.fill_fraction"],
        ["Tier gap (Tier 1 − Tier 0 level, 2D)", f"{num(h.get('tier_gap_db'), '_db')} dB", "headline.tier_gap_db"],
        ["Fragile (spec: works for only one clap or one listener)", fmt(m.get("fragile")), "fragile"],
    ]
    if m.get("fragile_reason"):
        hrows.append(["Robustness summary", fmt(fragile_text(r)), "fragile_reason"])
    if m.get("robust_summary"):
        hrows.append(["Robustness verdict", fmt(m["robust_summary"]), "robust_summary"])
    if h.get("echo_level_db_re_direct_finite_height") is not None:
        hrows.append([f"Echo level with {fmt(h.get('finite_height_m'), 1)} m posts (info)",
                      f"{num(h['echo_level_db_re_direct_finite_height'], '_db')} dB re direct",
                      "headline.echo_level_db_re_direct_finite_height"])
    out += [table(["quantity", "value", "key"], hrows), ""]
    if m.get("failure_cause"):
        out += [f"**Failure cause** (`failure_cause`): {fmt(m['failure_cause'])}", ""]
    if m.get("failure_mechanism"):
        out += ["**Failure mechanism** (`failure_mechanism`):", "", render_block(m["failure_mechanism"], src,
                                                                                 "failure_mechanism"), ""]
    out += ["**Metrics** (mean over the clap family; gating rows decide pass/fail; the judge floor is what the same "
            "judge gives a physically perfect echo, `judge_floor.mean`):", "", _metric_table(r), "",
            "**Per clap variant** (with the judge floor per clap):", "", _per_clap_table(r), ""]
    if m.get("robustness") or m.get("robustness_not_run"):
        out += ["**Robustness** (Tier 1 value, change from nominal in brackets; cases not run are marked so):", "",
                _robust_table(r), ""]
    diag = m.get("diagnosis")
    if diag:
        out += ["**Diagnosis** (`diagnosis`):", ""]
        if isinstance(diag, dict) and diag.get("summary"):
            out += [fmt(diag["summary"]), ""]
        et = diag.get("extinction_table") if isinstance(diag, dict) else None
        if et:
            out += ["Predicted vs measured extinction (`diagnosis.extinction_table`; model: "
                    f"{fmt(et.get('model'))}):", "", parallel_table(et) or render_block(et, src, "diagnosis.extinction_table"), ""]
        lt = diag.get("level_two_ways") if isinstance(diag, dict) else None
        if lt:
            out += ["Level two ways (`diagnosis.level_two_ways`; full-wedge columns are UNVERIFIED Tier 0 scaling):", "",
                    parallel_table(lt) or render_block(lt, src, "diagnosis.level_two_ways"), ""]
        out += [f"*(Further diagnosis keys in `{src}` key `diagnosis`.)*", ""]
    s3 = m.get("s3_extra") or {}
    la = s3.get("level_along_melody")
    if la:
        notes = la.get("notes_hz") or []
        rowsl = []
        for i in range(len(notes)):
            def at(k):
                v = la.get(k) or []
                return v[i] if i < len(v) else None
            spl_i = at("spl_db")
            rowsl.append([str(i + 1), num(notes[i], "_hz"), num(at("tier1_2d_db"), "_db"),
                          num(at("corrected_3d_db"), "_db"), num(spl_i, "_db"),
                          num(at("spl_finite_height_db"), "_db"),
                          "below 35 dB" if isinstance(spl_i, (int, float)) and spl_i < 35 else "—"])
        out += ["**Level along the melody** (`s3_extra.level_along_melody`; 35 dB SPL is the spec's audibility line):",
                "", table(["note", "Hz", "Tier 1 2D dB", "corrected 3D dB", "dB SPL", "dB SPL, 2 m posts", "flag"],
                          rowsl), ""]
    if s3.get("grid_and_domain"):
        out += ["Grid and domain (`s3_extra.grid_and_domain`):", "", render_block(s3["grid_and_domain"], src,
                                                                                 "s3_extra.grid_and_domain"), ""]
    tc = m.get("tier1_correction") or {}
    if tc.get("stretch"):
        out += ["**Stretch compensation** (`tier1_correction.stretch`: the post field slows sound; ε is the echo's "
                "time-axis stretch, the prior is ε per unit fill):", "",
                render_block(tc["stretch"], src, "tier1_correction.stretch"), ""]
    ds = tc.get("density_sweep") or {}
    if ds.get("rows"):
        out += [f"**Design study — Tier 1 density sweep** (picked fill {num(ds.get('picked_fill'))}; selection: "
                f"{fmt(ds.get('selection'))}):", "", rows_table(ds["rows"], src, "tier1_correction.density_sweep.rows"),
                ""]
    if tc.get("rounds"):
        rr = [{"round": x.get("round"), "posts": x.get("posts"), "loss": x.get("loss"), "score": x.get("score"),
               "tier_gap_db": x.get("tier_gap_db"), "stretch_eps_applied": x.get("stretch_eps_applied"),
               **{k: v for k, v in (x.get("gating") or {}).items()}} for x in tc["rounds"]]
        out += [f"**Tier 1 correction rounds** (best round {fmt(tc.get('best_round'))}):", "", rows_table(rr), ""]
    def once(key, b):
        """Render a block the first time its content appears in the report; later copies point back."""
        h = json.dumps(b, sort_keys=True, default=str)
        if h in data.seen:
            return f"*Same content as `{data.seen[h]}`.*"
        data.seen[h] = f"{src}` key `{key}"
        return None

    for blk in ("design_study", "ablations", "realization_study", "count_sweep", "loss_chain"):
        b = m.get(blk)
        if not b:
            continue
        if blk == "design_study" and isinstance(b, dict):
            for k, v in b.items():
                out += [f"**Design study — `{k}`**" + (f": {fmt(v.get('what'))}" if isinstance(v, dict) and
                                                        v.get("what") else ""), ""]
                if isinstance(v, dict):
                    v = {kk: vv for kk, vv in v.items() if kk != "what"}
                out += [once(f"design_study.{k}", v) or render_block(v, src, f"design_study.{k}"), ""]
        elif once(blk, b):
            out += [f"**`{blk}`:** {once(blk, b)}", ""]
        elif blk == "ablations":
            out += [ablations_block(b, src), ""]
        else:
            out += [f"**`{blk}`:**", "", render_block(b, src, blk), ""]
    cav = m.get("caveats") or (m.get("verification") or {}).get("caveats") or []
    if cav:
        out += ["**Caveats recorded in this run:**", ""] + [f"- {sanitize_caveat(fmt(c))}" for c in cav] + [""]
    out += [f"Reproduce: `{fmt(mf.get('command'))}` (seed {fmt(mf.get('seed'))}, commit `{fmt(mf.get('git_commit'))}`).",
            ""]
    return "\n".join(out)


def ablations_block(b, src):
    att = b.get("attribution") or {}
    cols = ["combo", "a_ref_m", "loss", "loss_shot_noise", "low_band_500_1000_db_re_target", "level_db_2d_per_1000_posts"]
    out = [f"**Speech-limit ablations** (`ablations`; model: {fmt(b.get('model'))}; selection: "
           f"{fmt(b.get('selection'))}):", "", rows_table(b.get("rows") or [], src, "ablations.rows", cols=cols), "",
           f"Conclusion in plain words (`ablations.attribution`): with every constraint the loss is "
           f"{num(att.get('baseline_loss'))}; with none of them it is {num(att.get('ceiling_loss'))}; the largest "
           f"single cost by loss is the **{fmt(att.get('largest_single_cost_by_loss'))}**."]
    return "\n".join(out)


def closed_set_block(data, results):
    cs = next((r["metrics"].get("closed_set_3x3") for r in results.values() if r["metrics"].get("closed_set_3x3")),
              None)
    if not cs:
        return ""
    d = cs.get("distances") or {}
    cand = list(d)
    rows = []
    for echo in cand:
        row = d.get(echo) or {}
        best = min(row, key=lambda k: row[k]) if row else None
        rows.append([f"echo of “{echo}”"] + [(f"**{num(row.get(c))}**" if c == best else num(row.get(c)))
                                            for c in cand] + [fmt(best), num((cs.get("correct_fraction") or {}).get(echo))])
    return ("Closed set across the three syllables (`closed_set_3x3`; DTW distance, lower is closer; bold = nearest):"
            "\n\n" + table(["", *[f"target “{c}”" for c in cand], "nearest", "correct fraction"], rows))


def scorecard(data: Data, u):
    out = [f"### {u[1]}", ""]
    mem = data.members(u[0])
    if not mem:
        out.append(f"**Not run.** {not_run_reason(data, u)}")
        if u[0].startswith("4") and data.speech:
            out += ["", speech_prep(data, u[0])]
        return "\n".join(out)
    st = unit_state(data, u[0])
    out += [f"**{u[4]}, original spec thresholds (newest final run of each part): "
            f"{'passed' if st.startswith('pass') else 'missed'}**"
            + (" (unverified)" if st.endswith("_unverified") else "")
            + (f" — {len(mem)} parts: " + ", ".join(mem) if len(mem) > 1 else "") + ". The three verdicts "
            "(original thresholds, revised thresholds, owner's ear) are kept apart in the table below.", ""]
    if u[0] == "3" and "100 ms" in mem:
        out += ["The spec's pass condition is the 100 ms melody; the 60 ms run answers an open question.", ""]
    if u[0] == "4b":
        out += ["The 4b pass condition spans all three syllables (closed set correct AND ESTOI ≥ 0.5 for each).", ""]
        res = data.results("4b")
        rows = []
        for s, r in res.items():
            vals = {x["id"]: x for x in gating(r, "tier1")}
            rows.append([s, f"`{r['run_id']}`", pf(run_passed(r))] +
                        [f"{num(x.get('value'), i)} ({pf(x.get('pass'))})" for i, x in vals.items()])
        ids = list({x["id"]: 1 for r in res.values() for x in gating(r, "tier1")})
        out += [table(["syllable", "run", "result"] + ids, rows), "", closed_set_block(data, res), ""]
    for mname, rs in mem.items():
        lab = f"{u[4]}" + (f" — {mname}" if mname else "")
        out += [f"**Three verdicts, {lab}** (every final run, newest first):", "", verdict_table(data, rs), ""]
        if len(rs) > 1:
            out += [f"**Earlier attempts, {lab}** (newest first; the first row is the result):", "",
                    attempts_table(rs), ""]
        out += [run_card(data, rs[0], f"#### {lab} — newest run, original thresholds: "
                         f"{'passed' if run_passed(rs[0]) else 'missed'}"
                         + ("" if run_verified(rs[0]) else " (UNVERIFIED)")), ""]
        heard = [r for r in rs[1:] if r["run_id"] in accepted_ids(data)]
        for r in heard:
            out += [run_card(data, r, f"#### {lab} — run the owner listened to, original thresholds: "
                             f"{'passed' if run_passed(r) else 'missed'}"), ""]
    nonfinal = [r for r in data.unit_runs(u[0], final=False) if r.get("status") != "final"]
    if nonfinal:
        out += ["Other runs of this stage that are not final (history only):", "",
                table(["run", "status", "result", "verified"],
                      [[f"`{r['rel']}`", fmt(r.get("status")), pf(run_passed(r)), fmt(run_verified(r))]
                       for r in nonfinal]), ""]
    studies = _studies(mem[next(iter(mem))][0])
    if studies:
        out += [f"Study files for this stage (`{rel(data.root, studies[0].parent)}`): "
                + ", ".join(f"`{p.name}`" for p in studies) + "."]
        for p in studies:
            if "extinction" in p.name or p.name in ("tier_diff.json",):
                j = _load(p) or {}
                out += ["", f"**`{p.name}`**" + (f": {fmt(j.get('what'))}" if j.get("what") else ""), "",
                        render_block({k: v for k, v in j.items() if k != "what"}, rel(data.root, p), "")]
    if u[0].startswith("4") and data.speech:
        out += ["", speech_prep(data, u[0])]
    return "\n".join(out)


def speech_prep(data: Data, uid):
    sp = data.speech
    out = ["*Preparation findings (judges run on a physically perfect echo, target ⊛ clap; not stage-4 results). "
           "Source: `artifacts/speech/judge_sanity.json`.*", ""]
    rows = []
    v = (sp.get("s4a_vowel") or {}).get("rows") or {}
    errs = [x.get("formant_err_pct") for k, x in v.items() if k.startswith("perfect_clap")]
    if errs and uid in ("4a", "4"):
        rows.append(["4a vowel: worst formant error, perfect echo", f"{num(sum(errs) / len(errs), '_pct')} % mean ("
                     f"{num(min(errs), '_pct')}–{num(max(errs), '_pct')} % per clap)",
                     f"≤ {fmt((sp.get('s4a_vowel') or {}).get('threshold_pct'), 0)} %",
                     "s4a_vowel.rows.perfect_clap*.formant_err_pct"])
    syl = (sp.get("s4b_syllables") or {}).get("rows") or {}
    est = [x.get("estoi") for s in syl.values() for k, x in s.items() if k.startswith("perfect_clap")]
    cor = [x.get("correct") for s in syl.values() for k, x in s.items() if k.startswith("perfect_clap")]
    if est and uid in ("4b", "4"):
        rows.append(["4b syllables: ESTOI / closed-set correct, perfect echo",
                     f"{num(min(est))}–{num(max(est))}; {sum(bool(c) for c in cor)} of {len(cor)} correct",
                     f"ESTOI ≥ {fmt((sp.get('s4b_syllables') or {}).get('threshold_estoi'), 1)}",
                     "s4b_syllables.rows.*.perfect_clap*"])
    w = (sp.get("s4c_word") or {}).get("rows") or {}
    hits = [x.get("hit") for k, x in w.items() if k.startswith("perfect_clap")]
    if hits and uid in ("4c", "4"):
        rows.append(["4c word: recognizer says \"hello\", perfect echo", f"{sum(bool(h) for h in hits)} of {len(hits)}",
                     f"≥ {fmt((sp.get('s4c_word') or {}).get('threshold_hello_count'))} of 5",
                     "s4c_word.rows.perfect_clap*.hit"])
        n0 = w.get("target_plus_noise_0db")
        if n0:
            rows.append(["4c word: target + white noise at 0 dB SNR", f"“{fmt(n0.get('transcript'))}”, hit "
                         f"{fmt(n0.get('hit'))}", "—", "s4c_word.rows.target_plus_noise_0db"])
    if not rows:
        return ""
    return "\n".join(out + [table(["judge check", "value", "threshold", "key"], rows)])


# ---------------------------------------------------------------------------------------------------- open questions
def open_questions(data: Data):
    out = []
    rows = []
    for u in data.units():
        for mem, r in data.results(u[0]).items():
            h = r["metrics"].get("headline") or {}
            spl = h.get("echo_spl_db")
            rows.append([u[0] + (f" {mem}" if mem else ""), num(h.get("echo_level_db_re_direct"), "_db"),
                         num(spl, "_db"), num(h.get("echo_level_db_re_direct_finite_height"), "_db"),
                         "below 35 dB" if isinstance(spl, (int, float)) and spl < 35 else "above 35 dB"
                         if isinstance(spl, (int, float)) else "—", f"`{r['rel']}/metrics.json`"])
    q1 = ["1. **How loud is the echo for each stage, in the 3D estimate?**", ""]
    if rows:
        q1 += [table(["unit", "dB re direct (`headline.echo_level_db_re_direct`)", "dB SPL, 100 dB clap "
                      "(`headline.echo_spl_db`)", "dB re direct, 2 m posts (`…_finite_height`)", "vs 35 dB",
                      "file"], rows)]
        for mem, r in data.results("3").items():
            la = (r["metrics"].get("s3_extra") or {}).get("level_along_melody") or {}
            s = la.get("spl_db") or []
            if s:
                below = [i + 1 for i in la.get("notes_below_35_db_spl") or []]
                q1 += ["", f"Melody {mem}: the headline is the loudest note; first note {num(s[0], '_db')} dB SPL, "
                       f"last note {num(s[-1], '_db')} dB SPL; **{len(below)} of {len(s)} notes are below 35 dB** "
                       f"(notes {fmt(below)}, counting from 1) — `{r['rel']}/metrics.json` key "
                       "`s3_extra.level_along_melody.notes_below_35_db_spl` (0-based there)."]
        missing = [u[0] for u in data.units() if not data.results(u[0])]
        if missing:
            q1 += ["", "Not yet answered for " + ", ".join(missing) + " (no final run)."]
    else:
        q1.append("Not yet answered: no final run.")
    out.append("\n".join(q1))
    # Q2
    q2 = "2. **How short can notes get before the melody stops transcribing?** "
    ans = None
    for r in data.unit_runs("3"):
        a = ((r["metrics"].get("design_study") or {}).get("note_length_sweep") or {}).get("answer")
        if a:
            ans = (r, a)
            break
    if ans:
        r, a = ans
        q2 += (f"Tier 0 only (the fast single-scattering model): a physically perfect echo transcribes for every clap "
               f"down to {fmt(a.get('shortest_note_ms_perfect_echo_transcribes_all_claps'))} ms notes; the realized "
               f"post design transcribes for every clap at "
               + ("no tested length" if a.get("shortest_note_ms_realized_design_transcribes_all_claps") is None else
                  f"{fmt(a['shortest_note_ms_realized_design_transcribes_all_claps'])} ms")
               + f" (`{r['rel']}/metrics.json` key `design_study.note_length_sweep.answer`).")
        pl = a.get("per_length") or []
        if pl:
            q2 += "\n\n" + rows_table(pl)
    else:
        q2 += "Not yet answered: no note-length sweep in a stage-3 metrics file."
    s3 = data.results("3")
    if s3:
        passed = [m for m, r in s3.items() if run_passed(r)]
        q2 += ("\n\nOn the full-wave solver: " + ("; ".join(f"{m} {pf(run_passed(r))} (`{r['rel']}`, key `passed`)"
                                                         for m, r in s3.items()))
               + ("." if passed else " — no realized design transcribes on Tier 1 at any tested note length."))
    out.append(q2)
    # Q3
    q3 = ["3. **Which is the limit on speech: the clap spectrum, the positivity constraint, or small-post "
          "scattering?**", ""]
    rows = []
    for uid in ("4a", "4b", "4c", "4"):
        for mem, r in data.results(uid).items():
            m = r["metrics"]
            att = (m.get("ablations") or {}).get("attribution") or {}
            lc = m.get("loss_chain") or {}
            if att or lc:
                rows.append([uid + (f" {mem}" if mem else ""), num(att.get("baseline_loss")),
                             num(att.get("ceiling_loss")), fmt(att.get("largest_single_cost_by_loss")),
                             num(lc.get("profile_model")), num(lc.get("realized_tier0")), num(lc.get("realized_tier1")),
                             f"`{r['rel']}/metrics.json`"])
    if rows:
        q3 += ["Spectrogram loss (lower is better). Ablations on the profile model (`ablations.attribution`), then "
               "the loss chain from the continuous profile to realized posts on Tier 0 and on the full-wave solver "
               "(`loss_chain`):", "",
               table(["unit", "all constraints", "none", "largest single cost", "profile model", "realized, Tier 0",
                      "realized, Tier 1", "file"], rows), "",
               "Reading: the ablations rank the three named constraints; the loss chain shows how much more the "
               "realization with a finite number of thin posts and the full-wave physics add on top of the profile "
               "model's own fit (per-run `failure_cause` states the same in words)."]
    else:
        q3.append("Not yet answered: no stage-4 run with an `ablations` block.")
    out.append("\n".join(q3))
    # Q4
    q4 = ["4. **How much do build tolerances of 5 mm matter?**", ""]
    rows = []
    for u in data.units():
        for mem, r in data.results(u[0]).items():
            for x in r["metrics"].get("robustness") or []:
                if x.get("case") == "jitter":
                    rows.append([u[0] + (f" {mem}" if mem else ""), fmt(x.get("label")),
                                 ", ".join(f"{k} {fmt(v, 3, signed=True)}" for k, v in (x.get("delta") or {}).items()),
                                 pf(x.get("pass")), f"`{r['rel']}/metrics.json` `robustness[case=jitter]`"])
            for x in list(r["metrics"].get("robustness_not_run") or []) + \
                    list((r["metrics"].get("s3_extra") or {}).get("robustness_not_run") or []):
                if x.get("case") == "jitter":
                    rows.append([u[0] + (f" {mem}" if mem else ""), fmt(x.get("label")), fmt(x.get("status")), "—",
                                 f"`{r['rel']}/metrics.json` `robustness_not_run`"])
    if rows:
        q4 += ["Full-wave robustness case (posts jittered, radii jittered; change from nominal):", "",
               table(["unit", "case", "change", "jittered design passes", "file"], rows), ""]
    for r in data.results("1").values():
        dst = ((r["metrics"].get("design_study") or {}).get("design_study_tier0")) or {}
        jr = []
        for row in dst.get("rows") or []:
            for j in row.get("jitter") or []:
                jr.append({"realization": f"{row.get('mode')} K={fmt(row.get('posts_per_period'))}",
                           "n_posts": row.get("n_posts"), "sigma_mm": 1000 * j["sigma_m"] if j.get("sigma_m") else None,
                           "wave_corr": j.get("wave_corr"), "loss": j.get("loss")})
        if jr:
            q4 += [f"Stage-1 Tier 0 radial-jitter study ({fmt(dst.get('jitter'))}; `{r['rel']}/metrics.json` key "
                   "`design_study.design_study_tier0.rows[*].jitter`; waveform correlation with the unjittered echo):",
                   "", rows_table(jr, f"{r['rel']}/metrics.json", "design_study.design_study_tier0.rows", max_rows=24), ""]
        break
    q4.append("BUILD.md's placement-tolerance tables give the same question for the build (by reference).")
    out.append("\n".join(q4))
    return "\n\n".join(out)


def next_steps(data: Data, commentary: str):
    out = ["**What limited each stage (from `failure_cause` / `diagnosis` / `failure_mechanism`):**", ""]
    for u in data.units():
        res = data.results(u[0])
        if not res:
            out.append(f"- {u[1]}: not run — {not_run_reason(data, u)}")
        for mem, r in res.items():
            m = r["metrics"]
            why = m.get("failure_mechanism") or ((m.get("diagnosis") or {}).get("summary") if isinstance(
                m.get("diagnosis"), dict) else None) or m.get("failure_cause")
            if isinstance(why, dict):
                why = why.get("summary") or json.dumps(why)[:300]
            if run_passed(r):
                why = f"passed — {fmt(m.get('pass_weight') or 'see its weight statement')}"
            txt = fmt(why or "—")
            if len(txt) > 700:
                txt = txt[:697].rsplit(" ", 1)[0] + " …"
            ext = [p.name for p in _studies(r) if "extinction" in p.name]
            if ext and not run_passed(r) and "MECHANISM" not in txt and not m.get("diagnosis"):
                txt += " — mechanism evidence: " + ", ".join(f"`_studies/{x}` (rendered in the scorecard)" for x in ext)
            out.append(f"- {u[4]}" + (f" {mem}" if mem else "") + f" (`{r['run_id']}`): {txt}")
    out += ["", "**Commentary** (hand-written, preserved between runs of the generator):", "",
            COMMENT_BEGIN, commentary.strip("\n"), COMMENT_END, "",
            "**What to try next, ranked by information per unit cost:**", ""]
    out += [f"{i}. {s}" for i, s in enumerate(NEXT_STEPS, 1)]
    return "\n".join(out)


def build_section(data: Data):
    if not data.build_md:
        return "`BUILD.md` does not exist yet.\n\n" + build_pilot_section(data)
    out = [f"[`BUILD.md`]({data.prefix}BUILD.md) is the plan from simulation to a real structure: a decision ladder (desk → 1:10 "
           "ultrasonic scale model → full-scale calibration posts → pilot), with a fabrication pack under `build/`. "
           "Its simulated numbers live in a generated block refreshed by "
           "`uv run python -m stages.build_pack --refresh-doc`."]
    m = re.search(r"<!-- BEGIN GENERATED.*?-->(.*?)<!-- END GENERATED", data.build_md, re.S)
    block_runs = sorted(set(re.findall(r"^\| (s\d\w*|build\w*) \| (\S+) \|", m.group(1) if m else "", re.M)))
    newest = {}
    for r in data.runs:  # newest first
        if r.get("status") == "final":
            newest.setdefault(r["stage"], r["run_id"])
    if block_runs:
        out += ["", "Its generated block was computed from: " + ", ".join(f"`{s}/{r}`" for s, r in block_runs) + "."]
        stale = [s for s, r in block_runs if s in newest and newest[s] != r]
        if stale:
            out.append("**That block is stale**: newer final runs exist for " + ", ".join(
                f"`{s}` (`{newest[s]}`)" for s in stale) + ".")
    packs = sorted(p.name for p in (data.root / "build").glob("*") if p.is_dir()) if (data.root / "build").exists() else []
    if packs:
        out.append("Fabrication packs on disk: " + ", ".join(f"`build/{p}`" for p in packs) + ".")
    lines = [ln for ln in data.ledger.splitlines() if re.search(r"Task 13[ab]?", ln)]
    rev = [ln for ln in lines if "re-review" in ln]
    out += ["", "**Status: reviewed draft with open items.** The last independent re-review recorded in the ledger:",
            ""]
    if rev:
        out.append("> " + fmt(rev[-1].lstrip("- ").strip()))
    late = [ln for ln in lines if "Task 13b" in ln and re.match(r"- \d\d:\d\d", ln)]
    if late:
        out += ["", "Latest build-path entry in the ledger:", "", "> " + fmt(late[-1].lstrip("- ").strip())]
    return "\n".join(out + ["", build_pilot_section(data)])


def build_pilot_section(data: Data):
    pil = [r for r in data.other if r.get("stage", "").startswith("build")]
    out = ["### Build pilot (not one of the four stages)", ""]
    if pil:
        rows = []
        for r in pil:
            mm = r["metrics"]
            h = mm.get("headline") or {}
            g = "; ".join(f"{x.get('id')} {num(x.get('value'), x.get('id') or '')} ({pf(x.get('pass'))})"
                          for x in gating(r, "tier1") or gating(r))
            rows.append([f"`{r['rel']}`", r.get("status"), pf(run_passed(r)), fmt(run_verified(r)), g or "—",
                         num(h.get("echo_spl_db"), "_db"), fmt(h.get("post_count")), num(h.get("depth_m"), "_m")])
        out.append(table(["run", "status", "result", "verified", "gating", "dB SPL", "posts", "depth m"], rows))
        r0 = pil[0]
        if r0["metrics"].get("failure_cause"):
            out += ["", f"Failure cause of `{r0['run_id']}`: {fmt(r0['metrics']['failure_cause'])}"]
    else:
        out.append("No `build_pilot` run folder yet.")
    return "\n".join(out)


def _split_ruling(text):
    parts = [p.strip() for p in re.split(r"\s+—\s+", text)]
    cost_i = next((i for i, p in enumerate(parts) if i > 0 and re.search(r"\bcost|if wrong|risk is|cosmetic", p, re.I)),
                  None)
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
            if len(first) > 200:
                first = first[:197].rsplit(" ", 1)[0] + " …"
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
    ("Design pipeline, judges and stage 1", r"\[task (4|6)"),
    ("Stage 2", r"\[task 7"),
    ("Stage 3", r"\[task 8"),
    ("Stage 4 and speech judges", r"\[task (9|10)"),
    ("Clap, targets, environment", r"\[task 1\b|\[task 1,"),
    ("Viewer", r"\[task 5"),
    ("Build path", r"\[task 13"),
]
DEVIATION = re.compile(r"It is not k-Wave|unlogged deviation|instead of|skipped|[Ss]witched|CPU index|"
                       r"global constraints say|CORRECTION|raised from|^\[task 6\] fragile =|FAILS|"
                       r"not validated|Validation verdict follows|validation grid")
# per-stage domain/budget choices (wedge or strip, grid f_max, reduced solve steps, cases not run, time boxes)
DEVIATION_STAGE = re.compile(r"wedge|[Ss]trip|f_max|not run|Adam steps|solve steps|time box|budget|lock")


def deviations(data: Data):
    lines = [ln[2:].strip() for ln in data.decisions.splitlines() if ln.startswith("- [")]
    text = data.decisions
    drop = set()
    if "supersedes the task-9 formant line" in text:
        drop |= {i for i, ln in enumerate(lines) if ln.startswith("[task 9] Formant judge")}
    if "SUPERSEDED: the earlier task-3 lines" in text:
        drop |= {i for i, ln in enumerate(lines) if ln.startswith("[task 3]") and
                 re.search(r"ppw 9 at|Within r \+ 5 dx|0\.912 at r/dx|^\[task 3\] SUPERSEDED", ln)}
    kept = [ln for i, ln in enumerate(lines) if i not in drop]
    out = ["**Stage gate.** " + (gate_note(data) or "No gate deviation recorded."), ""]
    # runs over the 20-minute Tier 1 budget, and robustness cases not run, from the run files
    over, notrun = [], []
    for r in data.runs:
        if r.get("status") != "final":
            continue
        w = (r["manifest"].get("solver") or {}).get("wall_s")
        tw = r["metrics"].get("tier1_wall_s")
        ws = [x for x in ([w] + (tw if isinstance(tw, list) else [])) if isinstance(x, (int, float))]
        if ws and max(ws) > 1200:
            over.append(f"`{r['run_id']}` ({num(max(ws) / 60, '_m')} min; `manifest.solver.wall_s` / `tier1_wall_s`)")
        nr = list(r["metrics"].get("robustness_not_run") or []) + list(
            (r["metrics"].get("s3_extra") or {}).get("robustness_not_run") or [])
        if nr:
            notrun.append(f"`{r['run_id']}`: " + ", ".join(f"{x.get('case')} ({fmt(x.get('status'))})" for x in nr))
    if over:
        out += ["**Full-wave runs over the spec's 20-minute budget:** " + "; ".join(over) + ".", ""]
    if notrun:
        out += ["**Robustness cases not run:**", ""] + [f"- {x}" for x in notrun] + [""]
    out += ["Departures from the spec's letter and per-stage domain choices, short form of the matching "
            "`DECISIONS.md` lines (first clause; superseded lines dropped):", ""]
    seen, others = set(), []
    for name, pat in GROUPS:
        items, n_other = [], 0
        for ln in kept:
            if not re.match(pat, ln):
                continue
            if not (DEVIATION.search(ln) or (re.match(r"\[task (6b|7|8|10)", ln) and DEVIATION_STAGE.search(ln))):
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
        out.append(f"Other choices logged in [`DECISIONS.md`]({data.prefix}DECISIONS.md) — " + "; ".join(others) + ".")
    return "\n".join(out)


def run_tests(root: Path):
    try:
        p = subprocess.run(["uv", "run", "pytest", "-q"], cwd=root, capture_output=True, text=True, timeout=1800)
        tail = [ln for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()]
        summary = tail[-1] if tail else "no output"
    except (OSError, subprocess.TimeoutExpired) as e:
        summary = f"could not run: {e}"
    return (f"`uv run pytest -q` (default fast suite) on "
            f"{_dt.datetime.now().astimezone().isoformat(timespec='minutes')}: `{summary.strip('= ')}`")


def _between(text, a, b):
    m = re.search(re.escape(a) + r"\n?(.*?)\n?" + re.escape(b), text, re.S)
    return m.group(1) if m else None


# ------------------------------------------------------------------------------------------- three verdicts per test
# criteria test key -> (unit, member) of the spec's stage table, in report order
TESTS = [("s1_bird", "1", ""), ("s2_motif", "2", ""), ("s3_melody_100ms", "3", "100 ms"),
         ("s3_melody_60ms", "3", "60 ms"), ("s4a_ah", "4a", ""), ("s4b_ma", "4b", "ma"), ("s4b_ba", "4b", "ba"),
         ("s4b_om", "4b", "om"), ("s4c_hello", "4c", "")]
MISSING = "missing"  # no owner_v2 block in the file at all (distinct from null = not established)
APPENDIX_DIR = Path("docs/report")
APPENDICES = [("scorecards.md", "Per-test scorecards"), ("criteria.md", "Criteria: original, revised, by ear"),
              ("validation.md", "Solver validation"), ("design-studies.md", "Design studies and open questions"),
              ("timeline-and-rulings.md", "Timeline and rulings"), ("deviations.md", "Deviations from the spec")]


def slug(heading: str) -> str:
    """GitHub-style anchor of a Markdown heading."""
    h = re.sub(r"^#+\s*", "", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", h).replace(" ", "-")


def app(name, heading=None, prefix="docs/report/"):
    return prefix + name + (f"#{slug(heading)}" if heading else "")


def accepted_ids(data: Data):
    return set(((data.criteria or {}).get("accepted_runs") or {}).values())


def v1_of(run):
    if run is None:
        return None
    c = ((run.get("metrics") or {}).get("criteria") or {}).get("spec_v1") or {}
    return c.get("passed", run_passed(run)) if c else run_passed(run)


def v2_of(run):
    if run is None:
        return MISSING
    c = ((run.get("metrics") or {}).get("criteria") or {})
    if "owner_v2" not in c:
        return MISSING
    return c["owner_v2"].get("passed")


def ear_of(run):
    return (run or {}).get("metrics", {}).get("listening_verdict") if run else None


def v1_word(x):
    return {True: "passed", False: "missed"}.get(x, "not scored")


def v2_word(x):
    if x is MISSING or x == MISSING:
        return "not scored"
    return {True: "PASS", False: "fail"}.get(x, "not established")


def ear_word(lv, short=False):
    """The owner's listening verdict; always says whether it was blind."""
    if not lv:
        return "not heard by the owner"
    blind = "blind" if lv.get("blind") else "not blind"
    word = "accepted by ear" if lv.get("verdict") == "pass" else f"{fmt(lv.get('verdict'))} by ear"
    if short:
        return f"{word} ({blind})"
    return f"{word} ({fmt(lv.get('by'))}, {fmt(lv.get('date'))}, {blind})"


def verdict_rows(data: Data):
    """One row per test: the run the three verdicts are about and the three verdicts, never merged."""
    crit = data.criteria or {}
    acc = crit.get("accepted_runs") or {}
    tests = crit.get("tests") or {}
    rows = []
    if acc:
        keys = [k for k, _, _ in TESTS if k in acc] + [k for k in acc if k not in {t[0] for t in TESTS}]
        for k in keys:
            unit, member = next(((u, m) for kk, u, m in TESTS if kk == k), ("?", ""))
            run = data.by_id.get(acc[k])
            t = tests.get(k) or {}
            rows.append({"key": k, "title": t.get("title") or k, "unit": unit, "member": member, "run": run,
                         "run_id": acc[k], "v1": v1_of(run), "v2": v2_of(run), "ear": ear_of(run), "test": t})
        return rows
    for u in data.units():
        for mem, r in data.results(u[0]).items():
            rows.append({"key": f"{u[0]}{mem}", "title": u[1] + (f" — {mem}" if mem else ""), "unit": u[0],
                         "member": mem, "run": r, "run_id": r["run_id"], "v1": v1_of(r), "v2": v2_of(r),
                         "ear": ear_of(r), "test": {}})
    return rows


def short_title(row):
    return row["title"]


def counts(rows):
    n = len(rows)
    ear_rows = [r for r in rows if r["ear"] and r["ear"].get("verdict") == "pass"]
    v2_pass = [r for r in rows if r["v2"] is True]
    v2_null = [r for r in rows if r["v2"] is None]
    v2_fail = [r for r in rows if r["v2"] is False]
    v2_none = [r for r in rows if r["v2"] is MISSING or r["v2"] == MISSING]
    by_ear_only = [r for r in ear_rows if r["v1"] is not True and r["v2"] is not True]
    return {"n": n, "v1": [r for r in rows if r["v1"] is True], "ear": ear_rows, "v2": v2_pass, "v2_null": v2_null,
            "v2_fail": v2_fail, "v2_none": v2_none, "ear_only": by_ear_only}


def independence_note(row):
    ro = ((row.get("test") or {}).get("rests_on") or "") + " " + str(
        ((((row.get("run") or {}).get("metrics") or {}).get("criteria") or {}).get("owner_v2") or {}).get(
            "rests_on") or "")
    return ", same recognizer as the original test, so not independent" if "independent" in ro else ""


def status_line(data: Data, rows):
    c = counts(rows)
    n = c["n"]
    if not n:
        line = "**Status: no final results yet.**"
    else:
        lv = next((r["ear"] for r in c["ear"]), None)
        def names(rs, note=False):
            return "; ".join(r["title"] + (independence_note(r) if note else "") for r in rs)
        parts = [f"original spec thresholds: {len(c['v1'])} of {n} passed" + (f" ({names(c['v1'])})" if c["v1"] else "")]
        if lv:
            parts.append(f"owner's ear ({fmt(lv.get('date'))}, {'blind' if lv.get('blind') else 'not blind'}): "
                         f"{len(c['ear'])} of {n} accepted")
        else:
            parts.append(f"owner's ear: 0 of {n} heard")
        if c["v2_none"] and len(c["v2_none"]) == n:
            parts.append("revised thresholds: not scored")
        else:
            v2 = f"revised thresholds: {len(c['v2'])} of {n} confirmed automatically"
            if c["v2"]:
                v2 += f" ({names(c['v2'], True)})"
            if c["v2_fail"]:
                v2 += f", {len(c['v2_fail'])} failed"
            v2 += f", {len(c['v2_null'])} not established"
            parts.append(v2)
        if lv:
            parts.append(f"{len(c['ear_only'])} of {n} accepted by ear (not blind) and not confirmed by any automated "
                         "test")
        line = f"**Status, {n} tests, three separate verdicts (simulated, full-wave solver):** " + " · ".join(parts) + "."
    if not data.val_passed:
        line = "UNVERIFIED — the full-wave solver has not passed validation; every result below is unverified. " + line
    return line


def verdict_table(data: Data, rs):
    """Three verdicts for a list of runs of one test (used in the scorecards appendix)."""
    acc = accepted_ids(data)
    rows = []
    for i, r in enumerate(rs):
        role = ("newest" if i == 0 else "earlier") + (", heard by the owner" if r["run_id"] in acc else "")
        g = "; ".join(f"{x.get('id')} {num(x.get('value'), x.get('id') or '')} (needs {x.get('comparator')} "
                      f"{num(x.get('threshold'), x.get('id') or '')})"
                      for x in (((r["metrics"].get("criteria") or {}).get("spec_v1") or {}).get("gating")
                                or gating(r, "tier1") or gating(r)))
        rows.append([f"`{r['run_id']}`", role, v1_word(v1_of(r)) + (f": {g}" if g else ""), v2_word(v2_of(r)),
                     ear_word(ear_of(r))])
    return table(["run", "role", "original spec thresholds", "revised thresholds (owner_v2)", "owner's ear"], rows)


# ------------------------------------------------------------------------------------------------- main sections
def _h(run):
    return (run or {}).get("metrics", {}).get("headline") or {}


def true_level(data, run):
    """True echo level re the clap at the ear (dB): manifest.audio.as_heard_echo_level_db, else listen/README."""
    if not run:
        return None
    v = ((run.get("manifest") or {}).get("audio") or {}).get("as_heard_echo_level_db")
    if v is None:
        v = (data.listen.get(run_tag(run["run_id"])) or {}).get("true_db")
    return v


def v1_values(run, with_floor=True):
    m = (run or {}).get("metrics") or {}
    gm = ((m.get("criteria") or {}).get("spec_v1") or {}).get("gating") or gating(run or {"metrics": m}, "tier1")
    floor = (m.get("judge_floor") or {}).get("mean") or {}
    out = []
    for x in gm:
        i = x.get("id") or ""
        v = x.get("value")
        s = f"{i} {num(v, i) if v is not None else 'no value'} (needs {x.get('comparator')} {num(x.get('threshold'), i)}"
        if with_floor and i in floor:
            s += f"; perfect echo {num(floor[i], i)}"
        out.append(s + ")")
    return "; ".join(out)


def stored_other_words(metrics):
    """The 4c run's stored other-word study (metrics.json controls.other_words): (heard as hello, total claps,
    {word: hits}) over the control words (not "hello"), or None."""
    rows = (((metrics or {}).get("controls") or {}).get("other_words") or {}).get("rows") or {}
    words = {w: r for w, r in rows.items() if w != "hello" and r.get("tier0_hello_count") is not None}
    if not words:
        return None
    hits = {w: int(r["tier0_hello_count"]) for w, r in words.items()}
    total = sum(len(r.get("tier0_recognized_text") or []) or 5 for r in words.values())
    return sum(hits.values()), total, hits


def other_words_caveat(metrics, short=False):
    """One sentence: the stored other-word study disagrees with the rescore's regenerated controls (I1)."""
    ow = stored_other_words(metrics)
    if not ow or not ow[0]:
        return ""
    n, tot, hits = ow
    if short:
        return (f" (the stored study from the same pipeline heard {n} of {tot} other-word control echoes as "
                "\"hello\"; the regenerated controls disagree, cause unknown)")
    return (f"The stored study from the same 4c pipeline (`metrics.json` `controls.other_words`) heard {n} of {tot} "
            "other-word control echoes as \"hello\" (" + ", ".join(f"{w} {k}/5" for w, k in hits.items())
            + "); the rescore regenerated these controls and heard \"hello\" in none of them, and why the two "
            "disagree was not found (`runs/_criteria/summary.md`).")


def residue_rows(data, td):
    """((final stage-1 run id, its tier_diff row), (build pilot run id, its row)); a row is None when the study has
    no row for that run. The final stage-1 run is the newest final stage-1 run in the index."""
    rows = {str(r.get("run")): r for r in (td or {}).get("rows") or []}
    s1 = next((r["run_id"] for r in data.unit_runs("1")), None)
    pil = next((r["run_id"] for r in data.other if str(r.get("stage", "")).startswith("build")), None)
    return (s1, rows.get(s1)), (pil, rows.get(pil))


def _ow_metrics(data, t):
    """metrics.json of a criteria test's accepted run (for the stored other-word study), or None."""
    return (data.by_id.get(str((t or {}).get("accepted_run"))) or {}).get("metrics")


def v2_values(row):
    """The numbers an owner_v2 verdict rests on, in a phrase."""
    t = row.get("test") or {}
    run = row.get("run") or {}
    ov = ((run.get("metrics") or {}).get("criteria") or {}).get("owner_v2") or {}
    mets = {x.get("id"): x for x in ov.get("metrics") or []}
    bits = []
    idc = mets.get("id_claps")
    if idc and idc.get("used", True) is not False:
        bits.append(f"nearest its own target on {fmt(int(idc['value']) if idc.get('value') is not None else None)} "
                    "of 5 claps")
    pc = mets.get("pitch_cents")
    if pc and pc.get("value") is not None:
        thr = pc.get("threshold")
        bits.append(f"median pitch off by {n0(pc['value'])} cents" + (
            f" (threshold {n0(thr)})" if thr is not None else " (no threshold exists)"))
    hc = mets.get("hello_claps")
    if hc:
        bits.append(f"recognizer says \"hello\" on {fmt(int(hc['value']))} of 5 claps")
    if t.get("controls_total") is not None:
        bits.append(f"controls rejected {fmt(t.get('controls_rejected'))}/{fmt(t.get('controls_total'))}"
                    + (other_words_caveat(run.get("metrics"), short=True) if hc else ""))
    elif ov.get("controls"):
        bits.append(f"controls rejected {sum(1 for c in ov['controls'] if c.get('pass') is False)}/{len(ov['controls'])}")
    return "; ".join(bits)


def came_back(row):
    """What came back, in a phrase, from the run's own judges."""
    run = row.get("run") or {}
    m = run.get("metrics") or {}
    g = {x.get("id"): x.get("value") for x in ((m.get("criteria") or {}).get("spec_v1") or {}).get("gating") or []}
    if "pitch_err_pct" in g:
        return f"a falling whistle; worst-frame pitch error {num(g['pitch_err_pct'], '_pct')} %"
    if "notes_in_order" in g:
        k = g["notes_in_order"]
        cm = g.get("note_cents_max")
        tail = ("notes not matched on any clap (the judge's 1200-cent sentinel)" if isinstance(cm, (int, float))
                and cm >= 1200 else f"worst note {n0(cm)} cents off (mean over claps; a clap whose notes are not "
                "matched counts as 1200)")
        return f"notes in the right order on {fmt(round(5 * k)) if k is not None else '—'} of 5 claps; {tail}"
    if "hello_count" in g:
        rt = m.get("recognized_text") or []
        tr = sorted({fmt(x.get("transcript")) for x in rt})
        return f"the recognizer heard {', '.join(f'“{t}”' for t in tr) or '—'} on {fmt(int(g['hello_count']))} of 5 claps"
    if "estoi" in g:
        cs = g.get("closed_set_correct")
        return (f"intelligibility (ESTOI) {num(g['estoi'])}; picked out from the other two syllables: "
                f"{'yes' if cs else 'no'}")
    if "formant_err_pct" in g:
        return ("formant judge found no first formant" if g["formant_err_pct"] is None
                else f"worst formant error {num(g['formant_err_pct'], '_pct')} %")
    return "—"


def n1(v):
    """One decimal for the main report (dB, m); never None/NaN."""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and not (math.isnan(v) or math.isinf(v)):
        return f"{v:.1f}"
    return "—"


def n0(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool) and not (math.isnan(v) or math.isinf(v)):
        return f"{v:.0f}"
    return "—"


def _row(rows, key):
    return next((r for r in rows if r["key"] == key), None)


def what_works(data: Data, rows):
    out = []
    w = _row(rows, "s1_bird") or next((r for r in rows if r["unit"] == "1"), None)
    if not w or not w["run"]:
        return "No final stage-1 run yet."
    run = w["run"]
    mf, h = run["manifest"], _h(run)
    cfg = (mf.get("design") or {}).get("config") or {}
    real = (mf.get("design") or {}).get("realization") or {}
    t = w.get("test") or {}
    lvl = true_level(data, run)
    out += [f"### The ring-layout whistle (stage 1: {fmt(cfg.get('title') or run.get('title'))})", "",
            "A clap at a marked spot, thin vertical posts standing in a fan in front of it, and a falling bird "
            "whistle coming back. Each ring of posts lies on one equal-delay curve, and successive rings are one "
            "period of the note apart, so each ring adds one cycle of the whistle and the shrinking ring spacing makes "
            "the pitch fall (like the chirp from a clap in front of a long flight of stairs).", "",
            f"- **Design** (run `{run['rel']}`): {fmt(h.get('post_count'))} posts of "
            f"{fmt(100 * float(cfg['a_ref']), 0) if cfg.get('a_ref') else '—'} cm radius in "
            f"{fmt(real.get('n_rings'))} rings, {n1(h.get('depth_m'))} m deep, fan "
            f"±{fmt(cfg.get('half_angle_deg'), 0)}°, covering "
            f"{num(100 * h['fill_fraction'] if h.get('fill_fraction') is not None else None, '_pct')} % of the ground "
            f"(`metrics.json` `headline`, `manifest.json` `design`).",
            f"- **How loud** (simulated): the echo is {n1(lvl)} dB re the clap at the ear for clap variant 0 "
            f"(`manifest.audio.as_heard_echo_level_db`; mean over the clap variants "
            f"{n1(h.get('echo_level_db_re_direct'))} dB, `headline.echo_level_db_re_direct`, the value BUILD.md "
            f"quotes); for a 100 dB clap about {n1(h.get('echo_spl_db'))} dB "
            "SPL (`headline.echo_spl_db`), roughly quiet conversation.", "",
            "**Three verdicts, kept apart:**", ""]
    v1 = v1_word(w["v1"])
    out.append(f"1. **Original spec thresholds: {v1}**, narrowly: {v1_values(run)}. The \"perfect echo\" value is "
               "what the same judge gives a physically perfect echo (target ⊛ clap), so the pitch mark sits close to "
               "the judge's own floor (`criteria.spec_v1`, `judge_floor.mean`).")
    mt = (t.get("margin") or {}).get("pitch") or {}
    extra = ""
    if mt:
        extra = (f" The pitch threshold sits between the worst accepted or perfect echo "
                 f"({n0(mt.get('worst_positive'))} cents) and the best mistuned control "
                 f"({n0(mt.get('best_mistuning_control'))} cents).")
    out.append(f"2. **Revised thresholds (owner_v2): {v2_word(w['v2'])}**: {v2_values(w)}.{extra} Rests on: "
               f"{fmt(t.get('rests_on') or '—')} (`runs/_criteria/summary.json`).")
    lv = w["ear"]
    out.append(f"3. **Owner's ear: {ear_word(lv)}**" + (f": “{fmt(lv.get('quote'))}” — basis "
                                                       f"{fmt(lv.get('basis'))}." if lv else "."))
    others = [x for x in ((data.criteria or {}).get("runs") or [])
              if x.get("test") == w["key"] and x.get("run_id") != w["run_id"]]
    if others:
        out += ["", "Earlier whistle designs scored with the same frozen revised criterion: " + "; ".join(
            f"`{x['run_id']}` {v2_word(x.get('owner_v2'))}" for x in others) + "."]
    tag = run_tag(run["run_id"])
    files = [f for f in (f"listen/{tag}_echo_only.wav", f"listen/{tag}_clap_then_echo_boosted.wav",
                         f"listen/{tag}_target.wav") if (data.root / f).exists()]
    out += ["", "**Play:** " + ", ".join(f"[`{f}`]({f})" for f in files)
            + (f" (echo alone; clap then echo raised {n1((data.listen.get(tag) or {}).get('boost_db'))} dB; "
               "the target)" if files else "no files in `listen/` yet")
            + f", and the run's own `{run['rel']}/echo_tier1.wav`.", ""]
    # hello
    hrow = _row(rows, "s4c_hello")
    if hrow and hrow["run"]:
        hm = hrow["run"]["metrics"]
        est = next((x.get("value") for x in hm.get("metrics") or [] if x.get("id") == "estoi" and x.get("tier") == "tier1"),
                   None)
        fl = ((hm.get("judge_floor") or {}).get("mean") or {}).get("estoi")
        ctl = (hm.get("recognizer_controls") or {}).get("cases") or {}
        rob = {x.get("case"): x.get("pass") for x in hm.get("robustness") or []}
        out += ["### \"hello\" (stage 4c)", "",
                f"- What came back: {came_back(hrow)} (`recognized_text`). Wrong echoes given to the same "
                f"recognizer: {sum(1 for c in ctl.values() if c.get('hello_count') == 0)} of {len(ctl)} never heard "
                f"\"hello\" (`recognizer_controls`).",
                f"- Intelligibility is low: ESTOI {num(est)} against {num(fl)} for a perfect echo; with the listener "
                f"1 m sideways the original test {'passes' if rob.get('listener_side_1m') else 'fails'} "
                "(`robustness`).",
                f"- Verdicts: original thresholds {v1_word(hrow['v1'])}; revised thresholds {v2_word(hrow['v2'])}, "
                f"but that pass rests on the same recognizer and 3-of-5 rule as the original test plus "
                f"{fmt((hrow['test'] or {}).get('controls_rejected'))}/{fmt((hrow['test'] or {}).get('controls_total'))}"
                " rejected controls, so it is not an independent confirmation; owner's ear "
                f"{ear_word(hrow['ear'])}. " + other_words_caveat(((hrow.get('run') or {}).get('metrics'))),
                f"- Play: `listen/{run_tag(hrow['run_id'])}_echo_only.wav`. Details: "
                f"[scorecard]({app('scorecards.md', '### Stage 4c — Word')}).", ""]
    return "\n".join(out)


def hear_and_try(data: Data):
    lv = [v.get("true_db") for v in data.listen.values() if v.get("true_db") is not None]
    rng = f"{n1(max(lv))} to {n1(min(lv))} dB" if lv else "tens of dB"
    blind = data.root / "runs" / "_criteria" / "blind_test"
    nsamp = len(list(blind.glob("sample_*.wav"))) if blind.exists() else 0
    results = [p for p in blind.glob("*result*")] if blind.exists() else []
    out = ["**Listen** ([`listen/`](listen/), [`listen/README.md`](listen/README.md)): for each test, "
           "`<tag>_target.wav` (the aim), `<tag>_echo_only.wav` (the simulated echo alone, at full volume) and "
           "`<tag>_clap_then_echo_boosted.wav` (the clap, then the echo raised to sit 12 dB under it). "
           f"In reality the echo is {rng} re the clap (true level per test in the README), which is why a run "
           "folder's `as_heard.wav`, kept at the true ratio, sounds like only a clap. Whether a person hears the echo "
           "right after their own clap is a question about hearing that simulation does not cover.", "",
           "**Live mode** (microphone in, echo out):", "", "```", "uv run python -m echo.lab        # then open "
           "http://127.0.0.1:8000/viewer/?mode=live", "```", "",
           "Clap or whistle at the microphone and the speakers play the chosen structure's echo of it, live "
           "(convolution with the run's impulse response, `manifest.json` `ir`); every sound is kept as a take you "
           "can replay with the waves moving through the posts. Default echo boost puts it 12 dB under the clap; "
           "0 dB is the true level. Tested in headless Chrome with a fake microphone only: **not tested with a real "
           "microphone and speakers, not tested in Firefox, and system latency can only be compensated up to the "
           "first post's delay** (beyond that the echo comes late, and the panel says so). Structure responses of "
           "the full-wave runs are reconstructed from the clap-0 echo and are accurate only inside the clap's band "
           "([`viewer/README.md`](viewer/README.md#live-mode)).", "",
           "**Design from your own sound:** upload a file on the Live page (lab server), or run "
           "`uv run python -m stages.custom --target inputs/targets/<file>.wav --name \"my sound\"` (add `--tier1` "
           "for one full-wave check of short targets). These are fast-model designs, marked unverified unless the "
           "`--tier1` full-wave run completes (then `verified: true`, as for the example in `runs/custom/`), with no "
           "pass or fail ([`inputs/README.md`](inputs/README.md)).", "",
           "**Look:** the [viewer](viewer/) (review mode: scene, wave video, echo, spectrograms and the three "
           "verdicts per run), the lay [explainer](explainer/index.html), and the [build path](BUILD.md).", "",
           f"**Blind test kit** ([`runs/_criteria/blind_test/`](runs/_criteria/blind_test/README.md)): {nsamp} "
           "shuffled echo-only samples of equal length and the target choices, with the key kept in a separate "
           "folder. " + ("A results file exists in the folder." if results else
                         "It has not been run: no blind result exists, so the owner's verdict remains the only "
                         "listening verdict, and it is not blind.")]
    return "\n".join(out)


def _unit_heading(data, unit):
    u = next((u for u in data.units() if u[0] == unit), None)
    return f"### {u[1]}" if u else None


def glance(data: Data, rows):
    t = []
    for r in rows:
        run = r["run"]
        h = _h(run)
        lvl = true_level(data, run)
        hd = _unit_heading(data, r["unit"])
        t.append([short_title(r), came_back(r), v1_word(r["v1"]) + (f": {v1_values(run, False)}" if run else ""),
                  v2_word(r["v2"]) + (f": {v2_values(r)}" if r["v2"] is True else ""),
                  ear_word(r["ear"], short=True),
                  f"{n1(lvl)} dB / {n1(h.get('echo_spl_db'))} dB SPL",
                  f"{n1(h.get('depth_m'))} m / {fmt(h.get('post_count'))}",
                  f"[card]({app('scorecards.md', hd)})" if hd else "—"])
    out = ["One row per test; the run is the one the owner listened to (`runs/_criteria/summary.json` "
           "`accepted_runs`). \"Not established\" means no automated criterion separates the echo from the negative "
           "controls: it is neither a pass nor a fail. Level: true echo level re the clap at the ear for clap variant 0 "
           "(`manifest.audio.as_heard_echo_level_db`; BUILD.md quotes the mean over the clap variants, "
           "`headline.echo_level_db_re_direct`, which differs by up to about a dB) / estimated level for a "
           "100 dB clap (simulated).", "",
           table(["test", "what came back", "original spec thresholds", "revised thresholds", "owner's ear",
                  "level", "depth / posts", "details"], t)]
    s2 = _row(rows, "s2_motif")
    if s2:
        later = [r for r in data.unit_runs("2") if r["run_id"] != s2["run_id"]]
        if later:
            out += ["", f"**To be confirmed by the owner:** for stage 2 the files attach the listening verdict to the "
                    f"first design `{s2['run_id']}`; a second design "
                    + ", ".join(f"`{r['run_id']}` (created {fmt(r.get('created'))})" for r in later)
                    + " existed by the time the listening files were made, and the record does not establish which "
                    "of the two the owner heard (`listening_verdict.note` in the run's `metrics.json`)."]
    # earlier attempts: whistle and motif
    for unit, label in (("1", "The whistle's redesign history"), ("2", "The motif's two designs")):
        rs = sorted(data.unit_runs(unit), key=lambda r: r.get("created", ""))
        if unit == "1":
            rs += sorted([r for r in data.other if r.get("stage", "").startswith("build")],
                         key=lambda r: r.get("created", ""))
        if len(rs) < 2:
            continue
        tr = []
        for r in rs:
            cfg = (r["manifest"].get("design") or {}).get("config") or {}
            h = _h(r)
            what = (f"{fmt(cfg.get('realization') or 'density sampling')}, ±{fmt(cfg.get('half_angle_deg'), 0)}°, "
                    f"{fmt(100 * float(cfg['a_ref']), 0) if cfg.get('a_ref') else '—'} cm posts"
                    + (", stretch compensated" if cfg.get("stretch_comp") else ""))
            if r.get("stage", "").startswith("build"):
                what = "build pilot: " + what
            tr.append([f"`{r['run_id']}`", what, v1_values(r, False) or "—", v2_word(v2_of(r)),
                       ear_word(ear_of(r), short=True), f"{n1(_h(r).get('echo_spl_db'))} dB SPL",
                       fmt(h.get("post_count")),
                       num(100 * h["fill_fraction"] if h.get("fill_fraction") is not None else None, "_pct") + " %"])
        out += ["", f"**{label}** (oldest first):", "",
                table(["run", "design", "original thresholds (values)", "revised", "owner's ear", "level", "posts",
                       "coverage"], tr)]
    return "\n".join(out)


def _jitter(data, run):
    p = data.root / "build" / f"{run['stage']}-{run['run_id']}" / "pack.json" if run else None
    pk = _load(p) if p else None
    return pk, (rel(data.root, p) if p else "")


def learned(data: Data, rows, commentary):
    out = []
    w = (_row(rows, "s1_bird") or {}).get("run")
    s1 = sorted(data.unit_runs("1"), key=lambda r: r.get("created", ""))
    n = 0

    def item(txt):
        nonlocal n
        n += 1
        out.append(f"{n}. {txt}")
    if len(s1) >= 2:
        a, b = s1[0], s1[1]
        ca = (a["manifest"].get("design") or {}).get("config") or {}
        cb = (b["manifest"].get("design") or {}).get("config") or {}
        item(f"**Exact rings beat scattered posts.** Same {fmt(_h(a).get('post_count'))} posts: "
             f"{fmt(ca.get('realization') or 'density sampling')} gave {v1_values(a, False)}; "
             f"{fmt(cb.get('realization') or 'density sampling')} rings gave {v1_values(b, False)} "
             f"(`{a['rel']}`, `{b['rel']}`).")
    if w:
        st = ((w["metrics"].get("tier1_correction") or {}).get("stretch")) or {}
        item(f"**The post field slows sound (compensable) and extinguishes it (not).** The slowing stretches the echo's "
             f"time axis (prior {num(st.get('stretch_per_fill_prior'))} × coverage; applied "
             f"{num(100 * st['final_applied'] if st.get('final_applied') is not None else None, '_pct')} % for the "
             "whistle) and is undone by scaling the ranges. Extinction removes sound and grows with frequency, with "
             "post radius squared and with how narrowly the posts are confined sideways. Predicted vs measured for the "
             "motif (two-way, dB):")
        rows_e = []
        for f in ("v1_extinction.json", "v2_extinction.json"):
            j = _load(data.runs_dir / "s2_motif" / "_studies" / f) or {}
            for x in j.get("rows") or []:
                rows_e.append([f"`{fmt(j.get('run'))}`", f"{n0(x.get('note_hz'))} Hz",
                               n1(x.get("predicted_two_way_extinction_db")),
                               n1(x.get("measured_tier1_minus_tier0_db_clap0"))])
        if rows_e:
            out += ["", "   " + table(["run", "note", "predicted", "measured (full-wave − fast model)"], rows_e)
                    .replace("\n", "\n   "), "",
                    "   The first design (2 cm posts, narrow fan) lost its upper notes; the second (1 cm, wide fan) "
                    "kept them. Sources: `runs/s2_motif/_studies/v*_extinction.json`."]
    td = _load(data.runs_dir / "s1_bird" / "_studies" / "tier_diff.json") or {}
    thick = [x for x in td.get("rows") or [] if x.get("radius")]
    (s1_id, x), (pil_id, xp) = residue_rows(data, td)
    if x:
        def mm(r):
            return n1(1000 * r['equivalent_radial_jitter_m'] if r.get('equivalent_radial_jitter_m') else None)

        item(f"**A broadband residue sits under the whistle.** The full-wave echo of the final stage-1 design "
             f"(run `{s1_id}`, {fmt(x.get('n_posts'))} posts) differs from the fast model of the same posts by an "
             f"incoherent residue {n1((x.get('tier1_vs_tier0') or {}).get('residue_db_stretched_fir33'))} dB below "
             f"it, the size of {mm(x)} mm of random placement error"
             + (f"; for the {fmt(xp.get('n_posts'))}-post build pilot (run `{pil_id}`) it is "
                f"{n1((xp.get('tier1_vs_tier0') or {}).get('residue_db_stretched_fir33'))} dB ({mm(xp)} mm)"
                if xp else "")
             + (f"; with {fmt(thick[0].get('n_posts'))} posts of {fmt(100 * thick[0]['radius'], 0)} cm it is "
                f"{n1((thick[0].get('tier1_vs_tier0') or {}).get('residue_db_stretched_fir33'))} dB"
                if thick else "")
             + ". Whether it is real scattering between posts or the solver drawing 1 cm posts on a ~1 cm grid is "
             "not settled; the 1:10 model would settle it (`runs/s1_bird/_studies/tier_diff.json`).")
    att = [((r["metrics"].get("ablations") or {}).get("attribution") or {}).get("largest_single_cost_by_loss")
           for uid in ("4a", "4b", "4c") for r in data.results(uid).values()]
    att = [a for a in att if a]
    if att:
        top = max(set(att), key=att.count)
        item(f"**The clap's spectrum and weak low-frequency scattering tilt everything toward 2–3 kHz.** In the speech "
             f"ablations the largest single cost is the {top} on {att.count(top)} of {len(att)} speech runs "
             f"(`ablations.attribution`); low notes, the melody's lower notes and vowels suffer most "
             f"([design studies]({app('design-studies.md')})).")
    dst = _load(data.runs_dir / "s1_bird" / "_studies" / "design_study_tier0.json") or {}
    ss = [x for x in dst.get("sweet_spot") or [] if (x.get("offset_m") or [None])[0] == 0.0]
    if ss:
        fan = ss[0].get("half_angle_deg")
        side = [x for x in ss if x.get("half_angle_deg") == fan and (x.get("offset_m") or [0, 0])[1] in (0.1, 0.25)]
        item(f"**The listening spot is centimetres wide.** For the ±{fmt(fan, 0)}° fan the echo heard "
             + " and ".join(f"{n0(100 * x['offset_m'][1])} cm sideways correlates {fmt(x.get('wave_corr_vs_nominal'))}"
                            for x in side)
             + " with the design listener's (1 = identical; fast model, `runs/s1_bird/_studies/design_study_tier0.json` "
             "`sweet_spot`).")
    pk, pkp = _jitter(data, w)
    if pk:
        jt = {x.get("sigma_mm"): x for x in (pk.get("physics") or {}).get("jitter") or [] if x.get("kind") == "radial"}
        bits = []
        for sg in (1.0, 2.0, 5.0):
            x = jt.get(sg)
            if x:
                sc = ((x.get("judges") or {}).get("spec_corr") or {}).get("mean")
                bits.append(f"{fmt(sg, 0)} mm: spectrogram score {num(sc)}, waveform correlation "
                            f"{num((x.get('waveform_corr') or {}).get('mean'))}")
        if bits:
            item("**Millimetre placement moves the strict score, not the waveform.** Random radial error, fast model: "
                 + "; ".join(bits) + f" (`{pkp}` `physics.jitter`; the original mark is ≥ 0.8).")
        tp = (pk.get("physics") or {}).get("temperature") or []
        if tp:
            item("**Temperature retunes it.** The whole whistle's pitch follows the speed of sound: "
                 + ", ".join(f"{fmt(x.get('T_c'))} °C {fmt(x.get('pitch_shift_pct'), 1, signed=True)} %" for x in tp)
                 + f" (`{pkp}` `physics.temperature`).")
    lv = [v.get("true_db") for v in data.listen.values() if v.get("true_db") is not None]
    if lv:
        item(f"**The echo is {n1(-max(lv))} to {n1(-min(lv))} dB below the clap** (`listen/README.md`). "
             "A loud sound raises the ear's threshold for tens of milliseconds afterwards (forward masking); whether a "
             "person hears the echo right after their own clap is not something this simulation covers.")
    out += ["", "**Commentary** (hand-written, preserved between runs of the generator):", "",
            COMMENT_BEGIN, commentary.strip("\n"), COMMENT_END]
    return "\n".join(out)


def dead_ends(data: Data, rows):
    out = ["Recorded, not chased (owner, afternoon of 25 Nov: focus on what works). Every number is in the "
           f"[scorecards]({app('scorecards.md')})."]
    s2 = sorted(data.unit_runs("2"), key=lambda r: r.get("created", ""))
    if s2:
        bits = "; ".join(f"`{r['run_id']}` ({fmt(_h(r).get('post_count'))} posts, "
                         f"{n1(_h(r).get('depth_m'))} m): {came_back({'run': r})}" for r in s2)
        out.append(f"- **Motif (stage 2).** {bits}. The first design's thick posts in a narrow fan extinguished the "
                   "upper notes; the thin-post redesign kept them but not the balance between notes "
                   f"([card]({app('scorecards.md', '### Stage 2 — Motif')})).")
    s3 = data.results("3")
    if s3:
        bits = []
        for mem, r in s3.items():
            la = (r["metrics"].get("s3_extra") or {}).get("level_along_melody") or {}
            below = la.get("notes_below_35_db_spl") or []
            bits.append(f"{mem}: {came_back({'run': r})}, {n1(_h(r).get('depth_m'))} m deep, "
                        f"{len(below)} of {len(la.get('notes_hz') or [])} notes below 35 dB SPL")
        out.append("- **Melody (stage 3).** " + "; ".join(bits) + ". The structure is a long strip; the sound fades "
                   "along it, and on the fast model no realized design transcribes for every clap "
                   f"([card]({app('scorecards.md', '### Stage 3 — Melody')})).")
    for uid, name in (("4a", "Vowel (4a)"), ("4b", "Syllables (4b)")):
        res = data.results(uid)
        if not res:
            continue
        bits = "; ".join((f"“{mem}”: " if mem else "") + came_back({"run": r}) for mem, r in res.items())
        out.append(f"- **{name}.** {bits}. Thin posts scatter little at low frequency and the clap carries little "
                   "there, so the low formants are weak; the speech ablations put the clap spectrum first "
                   f"([card]({app('scorecards.md', _unit_heading(data, uid))})).")
    return "\n".join(out)


def build_brief(data: Data):
    b = data.build_md
    out = []
    if not b:
        return "`BUILD.md` does not exist yet."
    cost = {}
    for ph in ("2a", "2b", "2c", "3a", "3b"):
        mm = re.search(rf"^\| {re.escape(ph)}\.[^|]*\|[^|]*\| ([^|]*?) \|", b, re.M)
        if mm:
            cost[ph] = re.sub(r"\s*\(est[^)]*\)?\)?", "", mm.group(1)).strip().lstrip("+~").strip()
    listeners = re.search(r"at least (\d+ of \d+) listeners", b)
    td = _load(data.runs_dir / "s1_bird" / "_studies" / "tier_diff.json") or {}

    def res(rid, r):
        if not r:
            return None
        j = {round(1000 * y["sigma_m"], 1): y["residue_db_stretched_fir33"] for y in r.get("tier0_jitter_residue") or []}
        return (f"`{rid}`: fast model {n1(j.get(1.0))} dB at 1 mm, full wave "
                f"{n1((r.get('tier1_vs_tier0') or {}).get('residue_db_stretched_fir33'))} dB")
    rr = [y for y in (res(*q) for q in residue_rows(data, td)[::-1]) if y]
    out.append(
        "From [`BUILD.md`](BUILD.md): **first**, an outdoor hearing test on a quiet site — one 20 mm bar, then a small "
        f"grating of posts — listened to by several people (estimated {cost.get('3a', 'a few hundred euros')}), because the "
        "simulations cannot say whether anyone hears an echo that far under their own clap. **In parallel**, the 1:10 "
        "ultrasonic tabletop model (estimated " + ", then ".join(cost[p] for p in ("2a", "2b", "2c") if p in cost)
        + " more), which answers fidelity and whether the residue is physics or solver, but not audibility. **Full scale** "
        f"(estimated {cost.get('3b', '—')}) only if at least {listeners.group(1) if listeners else '8 of 10'} listeners hear the "
        "grating's tone after the clap and the 1:10 model's residue, measured on the design drilled into the board, "
        "lands near the fast model's residue at the board's placement accuracy rather than near that design's "
        "full-wave residue (BUILD.md phase 2c; the numbers are per design"
        + (": pilot " + "; stage-1 design ".join(rr) if rr else "") + ", `runs/s1_bird/_studies/tier_diff.json`).")
    pil = [r for r in data.other if r.get("stage", "").startswith("build")]
    w = next((r for r in data.unit_runs("1")), None)
    if pil:
        p = pil[0]
        out += ["", f"Build pilot `{p['run_id']}` ({fmt(_h(p).get('post_count'))} posts, a narrower fan, "
                f"{n1(_h(p).get('echo_spl_db'))} dB SPL): original thresholds {v1_word(run_passed(p))} — "
                f"{v1_values(p)}"
                + (f"; it did worse than the {fmt(_h(w).get('post_count'))}-post design ({v1_values(w, False)})"
                   if w else "") + ". Fabrication packs: `build/`."]
    return "\n".join(out)


def validation_rows(v):
    c = (v or {}).get("checks") or {}
    cyl = c.get("cylinder") or {}
    g1 = _grids(v).get("stage1_grid") or {}
    worst = max((x.get("max_abs_err_db") for x in (g1.get("per_radius") or {}).values()
                 if x.get("max_abs_err_db") is not None), default=None)
    gc = c.get("grid_convergence") or {}
    es = c.get("empty_scene") or {}
    tt = c.get("tier0_vs_tier1") or {}
    return [
        ["Single post, backscatter vs exact theory", f"worst {num(worst, '_db')} dB", f"≤ {fmt(cyl.get('threshold_db'), 1)} dB",
         pf(cyl.get("pass")), "exact theory, backscatter only"],
        ["Grid convergence, sparse design", f"{num((gc.get('sparse') or {}).get('max_abs_delta_db'), '_db')} dB", "< 1 dB",
         pf((gc.get("sparse") or {}).get("pass")), "self-convergence"],
        ["Grid convergence, dense patch", f"{num((gc.get('dense') or {}).get('max_abs_level_delta_db'), '_db')} dB",
         "< 1 dB", pf((gc.get("dense") or {}).get("pass")), "self-convergence only"],
        ["Empty scene: nothing after the clap", f"{fmt(es.get('max_after_direct_db'), 1)} dB",
         f"< {fmt(es.get('threshold_db'), 0)} dB", pf(es.get("pass")), "—"],
        ["Fast model vs full-wave, sparse design", f"{num(tt.get('max_abs_delta_db'), '_db')} dB",
         f"≤ {fmt(tt.get('threshold_db'), 1)} dB", pf(tt.get("pass")), "model agreement"],
    ]


def trust(data: Data, tests_line):
    v = data.validation
    out = []
    if v is None:
        out.append("UNVERIFIED: `runs/validation/metrics.json` does not exist.")
    else:
        out += [f"Solver validation (`runs/validation/metrics.json`, engine `{fmt((v.get('solver') or {}).get('engine'))}`,"
                f" overall `passed`: **{fmt(v.get('passed'))}**):", "",
                table(["check", "value", "threshold", "result", "what it compares against"], validation_rows(v)), ""]
        ext = (v.get("extended_checks") or {}).get("angular_scattering") or {}
        bad = []
        for gname, g in _grids(v).items():
            for r, x in (g.get("per_radius") or {}).items():
                if x.get("pass_all_angles") is False:
                    e = (ext.get(gname) or {}).get("per_radius", {}).get(r) or {}
                    bad.append(f"{float(r) * 100:.0f} cm at {fmt(g.get('f_max'), 0)} Hz (forward "
                               f"{num(e.get('forward'), '_db')} dB, 90° {num(e.get('bistatic_90'), '_db')} dB)")
        back = [f"{float(r) * 100:.0f} cm at {fmt(g.get('f_max'), 0)} Hz ({num(x.get('max_abs_err_db'), '_db')} dB)"
                for gname, g in _grids(v).items() for r, x in (g.get("per_radius") or {}).items()
                if x.get("pass") is False]
        out += ["In plain words:", "",
                "- The solver is checked against exact theory only for one post scattering straight back.",
                "- Thin posts are off at other angles (error against exact theory; threshold 1 dB): "
                + ("; ".join(bad) if bad else "none recorded") + ".",
                "- Backscatter itself fails for: " + ("; ".join(back) if back else "none recorded")
                + " (threshold 1 dB; the overall pass is judged on the 4 kHz stage-1 grid only).",
                "- Dense fields are checked only by comparing the solver with itself on a finer grid; a bias both "
                "grids share would not show.",
                "- Live mode's structure responses for full-wave runs are reconstructed from one echo and are "
                "accurate only inside the clap's band.",
                f"- Full detail: [validation appendix]({app('validation.md')}).", ""]
    out += ["**Automated versus human.** The original and revised thresholds are automated judges on simulated audio. "
            "The owner's verdict is a human judgment by ear, not blind; the blind kit has not been run.", "",
            "**What was reviewed independently.** The solver, the fast model, the design pipeline, the speech judges, "
            "the first build-path plan and the first version of the revised criteria each had an independent review "
            "recorded in the ledger (the revised-criteria review withdrew the motif's revised pass; see the "
            f"[criteria appendix]({app('criteria.md')})). **Not separately reviewed:** the criteria fix round that "
            "produced every current revised-threshold number (no re-review), the BUILD.md rewrite and the build "
            "pilot, the custom designer, this report generator, the third round of stage-1 work, the stage scripts "
            "for stages 2–4, the viewer, the explainer and the lab server. The final review of the whole repository "
            "was read-only spot-checking (about 40 numbers checked against the files), not a re-derivation.", "",
            "**Tests.**", "", TESTS_BEGIN, tests_line, TESTS_END]
    return "\n".join(out)


def questions_short(data: Data, rows):
    out = []
    lv = [(r["title"], _h(r["run"]).get("echo_spl_db")) for r in rows if r["run"]]
    lv = [(t, x) for t, x in lv if isinstance(x, (int, float))]
    if lv:
        lo, hi = min(lv, key=lambda x: x[1]), max(lv, key=lambda x: x[1])
        mel = []
        for mem, r in data.results("3").items():
            la = (r["metrics"].get("s3_extra") or {}).get("level_along_melody") or {}
            if la.get("notes_hz"):
                mel.append(f"{len(la.get('notes_below_35_db_spl') or [])} of {len(la['notes_hz'])} notes at {mem}")
        out.append(f"1. **How loud?** For a 100 dB clap the simulated echoes peak between {n1(lo[1])} dB SPL "
                   f"({lo[0]}) and {n1(hi[1])} dB SPL ({hi[0]}); {sum(1 for _, x in lv if x < 35)} of "
                   f"{len(lv)} peaks are below the spec's 35 dB line (`headline.echo_spl_db`)"
                   + (f", but along the melody {', '.join(mel)} fall below it "
                      "(`s3_extra.level_along_melody`)" if mel else "") + ".")
    else:
        out.append("1. **How loud?** Not yet answered: no final run.")
    ans = None
    for r in data.unit_runs("3"):
        a = ((r["metrics"].get("design_study") or {}).get("note_length_sweep") or {}).get("answer")
        if a:
            ans = (r, a)
            break
    if ans:
        r, a = ans
        real = a.get("shortest_note_ms_realized_design_transcribes_all_claps")
        out.append(f"2. **How short can notes get?** A perfect echo transcribes down to "
                   f"{fmt(a.get('shortest_note_ms_perfect_echo_transcribes_all_claps'))} ms notes; the realized design "
                   + ("at no tested length" if real is None else f"at {fmt(real)} ms") + " (fast model only, "
                   f"`{r['rel']}/metrics.json` `design_study.note_length_sweep`).")
    else:
        out.append("2. **How short can notes get?** Not yet answered.")
    att = [((r["metrics"].get("ablations") or {}).get("attribution") or {}).get("largest_single_cost_by_loss")
           for uid in ("4a", "4b", "4c") for r in data.results(uid).values()]
    att = [a for a in att if a]
    if att:
        top = max(set(att), key=att.count)
        out.append(f"3. **What limits speech?** The {top}: the largest single cost on {att.count(top)} of {len(att)} "
                   "speech runs' ablations, ahead of positivity and small-post scattering (`ablations.attribution`).")
    else:
        out.append("3. **What limits speech?** Not yet answered.")
    w = (_row(rows, "s1_bird") or {}).get("run")
    pk, pkp = _jitter(data, w)
    jt = {x.get("sigma_mm"): x for x in ((pk or {}).get("physics") or {}).get("jitter") or [] if x.get("kind") == "radial"}
    if 5.0 in jt:
        x = jt[5.0]
        out.append(f"4. **Do 5 mm build tolerances matter?** Yes for the strict score: at 5 mm random radial error the "
                   f"whistle's spectrogram score falls to {num(((x.get('judges') or {}).get('spec_corr') or {}).get('mean'))}"
                   f" while its waveform still correlates {num((x.get('waveform_corr') or {}).get('mean'))} with the "
                   f"exact design (`{pkp}`); whether a listener hears the difference is a listening test.")
    else:
        out.append("4. **Do 5 mm build tolerances matter?** See the design-studies appendix.")
    out.append(f"\nFull answers with tables: [design studies]({app('design-studies.md', '## The spec' + chr(39) + 's four open questions')}).")
    return "\n".join(out)


def _ledger_line(data, pat, n=1, cap=240):
    for i, ln in enumerate(data.ledger.splitlines()):
        mm = re.match(r"^- (\d\d:\d\d) (.*)$", ln)
        if mm and re.search(pat, mm.group(2)):
            first = " ".join(re.split(r"(?<=[a-z0-9)%][.])\s+(?=[A-Z])", mm.group(2))[:n])
            if len(first) > cap:
                first = first[:cap - 3].rsplit(" ", 1)[0] + " …"
            return i, f"**{mm.group(1)}** {first}"
    return None


def process(data: Data):
    nrul = len(re.findall(r"Ruling:\s*(.+)$", data.ledger, re.M))
    picks = [(r"slow downloads", 1, 120), (r"Task 3 review: Needs fixes", 2, 240),
             (r"Task 3: fix round 1/5 done", 1, 200), (r"USAGE LIMIT", 1, 200), (r"SESSION STALLED", 1, 200),
             (r"OWNER STEER", 1, 300)]
    found = sorted(x for x in (_ledger_line(data, p, n, c) for p, n, c in picks) if x)
    out = [f"- {t}" for _, t in found]
    out += ["", f"The controller made **{nrul} rulings** on the owner's behalf; every one, in order, with its "
            f"cost-if-wrong, is in [timeline and rulings]({app('timeline-and-rulings.md')}), with the full timeline. "
            f"Deviations from the spec's letter: [deviations]({app('deviations.md')})."]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------------- appendices
def criteria_appendix(data: Data, rows):
    crit = data.criteria
    out = ["# Criteria: original thresholds, revised thresholds, and the owner's ear", "",
           "Generated by `stages/report.py` from `runs/_criteria/summary.json`, each run's `metrics.json` "
           "(`criteria.spec_v1`, `criteria.owner_v2`, `listening_verdict`), `echo/metrics_v2.py` and the ledger.", ""]
    if not crit:
        return "\n".join(out + ["`runs/_criteria/summary.json` does not exist: only the original thresholds are scored."])
    out += ["## The three verdicts", "",
            f"- **{fmt(crit.get('label_v1'))}**: the spec's thresholds and judges, unchanged; top-level `passed`.",
            f"- **{fmt(crit.get('label_v2'))}**: calibrated afterwards to the owner's listening and required to "
            "reject every negative control. On a run it was calibrated on it can only return PASS or null "
            "(\"not established\"); null is neither a pass nor a fail.",
            f"- **Listening verdict**: {ear_word(crit.get('listening_verdict'))}: "
            f"“{fmt((crit.get('listening_verdict') or {}).get('quote'))}”. "
            f"{fmt((crit.get('listening_verdict') or {}).get('note'))}", "",
            "## The rule (docstring of `echo/metrics_v2.py`)", ""]
    try:
        import ast
        doc = ast.get_docstring(ast.parse((data.root / "echo" / "metrics_v2.py").read_text())) or ""
    except (OSError, SyntaxError):
        doc = ""
    out += (["```", doc, "```", ""] if doc else ["(`echo/metrics_v2.py` not found.)", ""])
    thr = crit.get("thresholds_v2") or {}
    out += ["## Frozen thresholds (`thresholds_v2`)", "",
            table(["test", "thresholds"], [[k, ", ".join(f"{kk} {fmt(vv)}" for kk, vv in v.items()) or "—"]
                                          for k, v in thr.items()]), ""]
    out += ["## Per test: what a pass rests on, and the controls", ""]
    for k, t in (crit.get("tests") or {}).items():
        ctl = t.get("controls") or []
        kinds = {}
        for c in ctl:
            kinds.setdefault(c.get("kind"), [0, 0])
            kinds[c.get("kind")][0] += c.get("pass") is False
            kinds[c.get("kind")][1] += 1
        out += [f"### {fmt(t.get('title'))}", "",
                f"- Run the owner heard: `{fmt(t.get('accepted_run'))}`; established: {fmt(t.get('established'))}.",
                f"- A pass rests on: {fmt(re.sub(r'within None c', 'within (no threshold exists)', t.get('rests_on') or ''))}.",
                f"- Accepted echo: {fmt(json.dumps((t.get('accepted') or {}).get('values')))}; perfect echo: "
                f"{fmt(json.dumps((t.get('perfect_echo') or {}).get('values')))}.",
                f"- Controls rejected {fmt(t.get('controls_rejected'))}/{fmt(t.get('controls_total'))}: "
                + "; ".join(f"{kk} {a}/{b}" for kk, (a, b) in kinds.items()) + "."
                + ((" " + other_words_caveat(_ow_metrics(data, t))) if any("other word" in str(k) for k in kinds) else "")]
        mp = (t.get("margin") or {}).get("pitch") or {}
        if mp:
            out.append(f"- Pitch threshold derivation: worst positive {n0(mp.get('worst_positive'))} cents, best "
                       f"mistuned control {n0(mp.get('best_mistuning_control'))} cents → threshold "
                       f"{n0(mp.get('derived_threshold')) if mp.get('derived_threshold') is not None else 'none'} "
                       f"(frozen {n0(mp.get('frozen_threshold')) if mp.get('frozen_threshold') is not None else 'none'};"
                       f" rule: {fmt(mp.get('rule'))}).")
        if t.get("note"):
            out.append("- Note: " + fmt(t["note"]).replace("accepted by ear", "accepted by ear (owner, not blind)"))
        out.append("")
    out += ["## Every scored run", "",
            table(["test", "run", "heard by owner", "original", "revised", "owner's ear", "controls rejected"],
                  [[x.get("test"), f"`{x.get('run_id')}`", fmt(x.get("accepted")), v1_word(x.get("spec_v1")),
                    v2_word(x.get("owner_v2")),
                    (x.get("listening") or "not heard") + ("" if not x.get("listening") or "not blind" in
                                                           x.get("listening", "") else " (not blind)"),
                    f"{fmt(x.get('controls_rejected'))}/{fmt(x.get('controls_total'))}"]
                   for x in crit.get("runs") or []]), ""]
    rev = [ln for ln in data.ledger.splitlines() if re.search(r"T14|Task 14|OWNER LISTENING|OWNER REQUESTS", ln)]
    rev += [ln for ln in data.ledger.splitlines() if ln.startswith("- Ruling: thresholds")]
    if rev:
        out += ["## History from the ledger (including the review that withdrew the motif's revised pass)", ""]
        out += ["> " + fmt(ln.lstrip("- ").strip()) + "\n" for ln in rev]
    return "\n".join(out)


def scorecards_appendix(data: Data, rows):
    out = ["# Per-test scorecards", "",
           "Generated by `stages/report.py`. Each unit of the spec's stage table, with the three verdicts per run, "
           "earlier attempts, and the full metric, per-clap and robustness tables of the newest run (and of the run "
           "the owner heard, when that differs). Paths are relative to the repository root.", "",
           "## Audio and screenshots", "", how_to_look(data), "",
           "## Scorecards", "", "\n\n".join(scorecard(data, u) for u in data.units())]
    return "\n".join(out)


def design_appendix(data: Data):
    out = ["# Design studies and open questions", "",
           "Generated by `stages/report.py` from the run files and `_studies/*.json`.", "",
           "## The spec's four open questions", "", open_questions(data), "",
           "## What limited each stage", "",
           next_steps(data, "").split("**Commentary**")[0].strip(), "",
           "## What to try next (ranked by information per unit cost)", ""]
    out += [f"{i}. {s}" for i, s in enumerate(NEXT_STEPS, 1)]
    out += ["", "## Build path detail", "", build_section(data)]
    return "\n".join(out)


def appendices(data: Data, rows):
    data.prefix = "../../"
    try:
        data.seen = {}
        return {
            "scorecards.md": scorecards_appendix(data, rows),
            "criteria.md": criteria_appendix(data, rows),
            "validation.md": "# Solver validation\n\n" + validation_section(data),
            "design-studies.md": design_appendix(data),
            "timeline-and-rulings.md": "# Timeline and rulings\n\n" + overnight(data),
            "deviations.md": "# Deviations from the spec\n\n" + deviations(data),
        }
    finally:
        data.prefix = ""


def _shot(data, name, alt):
    p = data.root / "artifacts" / "report" / name
    return f"![{alt}](artifacts/report/{name})" if p.exists() else ""


# ------------------------------------------------------------------------------------------------------------ assemble
def build_all(root: Path = ROOT, run_test_suite: bool = True, reset_commentary: bool = False):
    """{relative path: text} for REPORT.md and every appendix."""
    root = Path(root)
    old = (root / "REPORT.md").read_text() if (root / "REPORT.md").exists() else ""
    commentary = None if reset_commentary else _between(old, COMMENT_BEGIN, COMMENT_END)
    if commentary is None:
        commentary = DEFAULT_COMMENTARY
    data = Data(root)
    if run_test_suite:
        tests = run_tests(root)
    else:
        prev = _between(old, TESTS_BEGIN, TESTS_END)
        prev = re.sub(r"\s*\*\(Not re-run.*$", "", prev or "", flags=re.S)
        now = _dt.datetime.now().astimezone().isoformat(timespec="minutes")
        tests = ((prev + " " if prev else "") + f"*(Not re-run by the generation at {now} (`--no-tests`); "
                 "the line before is the last recorded run.)*")
    stamp = _dt.datetime.now().astimezone().isoformat(timespec="minutes")
    rows = verdict_rows(data)
    status = status_line(data, rows)
    links = ("[Viewer](viewer/) · [Live mode](viewer/?mode=live) · [Explainer](explainer/index.html) · "
             "[Build path](BUILD.md) · [Listen](listen/) · [Repository](https://github.com/shyamvalsan/echo-engineering)")
    head = [status, "", "# Composed Echo — report"] if status.startswith("UNVERIFIED") else \
        ["# Composed Echo — report", "", status]
    shot1 = _shot(data, "shot-viewer-review-s1.png", "viewer, review mode, stage-1 whistle with the three verdicts")
    shot2 = _shot(data, "shot-viewer-live.png", "viewer, Live mode")
    parts = head + [
        "", links, "",
        f"*Generated {stamp} by `uv run python -m stages.report` from the files on disk. A passive field of rigid posts "
        "is designed so that a hand clap comes back as a chosen sound; everything here is simulated. Detailed tables: "
        + " · ".join(f"[{t}]({app(n)})" for n, t in APPENDICES) + ".*", "",
        "## 1. What works", "", what_works(data, rows), ""]
    if shot1:
        parts += [shot1, ""]
    parts += ["## 2. Hear it and try it", "", hear_and_try(data), ""]
    if shot2:
        parts += [shot2, ""]
    parts += [
        "## 3. All results at a glance", "", glance(data, rows), "",
        "## 4. What we learned", "", learned(data, rows, commentary), "",
        "## 5. What did not work, briefly", "", dead_ends(data, rows), "",
        "## 6. Build path", "", build_brief(data), "",
        "## 7. How far to trust this", "", trust(data, tests), "",
        "## 8. The spec's four open questions", "", questions_short(data, rows), "",
        "## 9. Process notes", "", process(data), "",
    ]
    files = {"REPORT.md": "\n".join(parts)}
    for name, text in appendices(data, rows).items():
        files[str(APPENDIX_DIR / name)] = (
            f"*Appendix of [REPORT.md](../../REPORT.md); generated {stamp} by `uv run python -m stages.report`.*\n\n"
            + text + "\n")
    return files


def build_report(root: Path = ROOT, run_test_suite: bool = True, reset_commentary: bool = False) -> str:
    return build_all(root, run_test_suite, reset_commentary)["REPORT.md"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--no-tests", action="store_true", help="reuse the test summary already in REPORT.md")
    ap.add_argument("--reset-commentary", action="store_true", help="replace the commentary block with the default")
    a = ap.parse_args(argv)
    root = Path(a.root)
    files = build_all(root, run_test_suite=not a.no_tests, reset_commentary=a.reset_commentary)
    for rp, text in files.items():
        p = root / rp
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    print(files["REPORT.md"].splitlines()[0])


if __name__ == "__main__":
    main()
