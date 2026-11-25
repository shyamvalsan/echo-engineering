"""stages/report.py: REPORT.md generated from files, on the real runs/ tree and on synthetic trees."""
import json
import re
from pathlib import Path

from stages import report

ROOT = Path(__file__).resolve().parents[1]
BAD = re.compile(r"\bNone\b|\bNaN\b|\bnan\b|\binf\b")


def _table_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("|")]


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


def _validation(passed=True):
    return {"solver": {"engine": "fd8-3", "ppw": 10.0, "area_cal": {"1.17": 0.908, "2.3": 1.0}},
            "checks": {"cylinder": {"threshold_db": 1.0, "pass": passed,
                                    "stage1_grid": {"f_max": 4000.0, "validated_radii_all_angles": [0.04],
                                                    "per_radius": {"0.01": {"max_abs_err_db": 0.7, "pass": True,
                                                                            "max_abs_err_db_all_angles": 1.7,
                                                                            "pass_all_angles": False},
                                                                   "0.04": {"max_abs_err_db": 0.9, "pass": True,
                                                                            "max_abs_err_db_all_angles": 0.9,
                                                                            "pass_all_angles": True}}}},
                       "grid_convergence": {"pass": True, "sparse": {"max_abs_delta_db": 0.7, "pass": True},
                                            "dense": {"max_abs_level_delta_db": 0.3, "pass": True, "n_posts": 10,
                                                      "source_scene": "x"}},
                       "empty_scene": {"max_after_direct_db": -85.0, "threshold_db": -60.0, "pass": True},
                       "tier0_vs_tier1": {"max_abs_delta_db": 1.0, "threshold_db": 2.0, "pass": True}},
            "extended_checks": {"angular_scattering": {"stage1_grid": {"per_radius": {
                "0.01": {"forward": 1.0, "bistatic_90": 1.7}}}}},
            "passed": passed, "caveats": ["effect on dense-field echoes is bounded at 0.36 dB by the check (x)"]}


def _run(root: Path, run_id: str, passed: bool, created: str, status="final"):
    d = root / "runs" / "s1_bird" / run_id
    metrics = {
        "stage": "s1_bird", "passed": passed, "verified": True, "fragile": False,
        "headline": {"echo_level_db_re_direct": -53.0, "echo_level_db_re_direct_raw3d": None,
                     "echo_spl_db": 57.4, "depth_m": 13.5, "post_count": 1060, "fill_fraction": 0.0035,
                     "tier_gap_db": float("nan"), "likely_inaudible_on_site": False},
        "metrics": [{"id": "pitch_err_pct", "label": "Pitch error", "value": 2.0 if passed else 5.6, "unit": "%",
                     "threshold": 3.0, "comparator": "<=", "pass": passed, "tier": "tier1", "gating": True},
                    {"id": "pitch_err_pct", "label": "Pitch error", "value": 2.4, "unit": "%",
                     "threshold": 3.0, "comparator": "<=", "pass": True, "tier": "tier0", "gating": False}],
        "per_clap": [{"clap": 0, "tier": "tier1", "metrics": {"pitch_err_pct": None}}],
        "robustness": [{"case": "jitter", "label": "Jitter", "metrics": {"pitch_err_pct": 6.0},
                        "delta": {"pitch_err_pct": 0.4}, "pass": passed}],
        "failure_cause": None if passed else "pitch misses",
        "judge_floor": {"mean": {"pitch_err_pct": 2.53}, "per_clap": [{"clap": 0, "metrics": {"pitch_err_pct": 1.9}}]},
    }
    # NaN is allowed by json.dumps; the generator must still never print it
    _write(d / "metrics.json", metrics)
    _write(d / "manifest.json", {"run_id": run_id, "stage": "s1_bird", "status": status, "seed": 0,
                                 "command": "uv run python -m stages.s1_bird", "git_commit": "abc",
                                 "solver": {"tier1": "fdtd", "engine": "fd8-3"}, "audio": {}})
    for f in ("target.wav", "echo_tier1.wav", "as_heard.wav"):
        (d / f).write_bytes(b"")
    return {"stage": "s1_bird", "run_id": run_id, "path": f"s1_bird/{run_id}", "title": "Bird",
            "created": created, "status": status, "passed": passed, "verified": True}


def _tree(tmp_path, runs=(), validation=True):
    if validation is not None:
        _write(tmp_path / "runs" / "validation" / "metrics.json", _validation(validation))
    _write(tmp_path / "runs" / "index.json", {"runs": list(runs)})
    return tmp_path


def test_real_tree():
    text = report.build_report(ROOT, run_test_suite=False)
    assert text.splitlines()[0].startswith(("**INTERIM", "**FINAL", "UNVERIFIED"))
    assert "### Stage 1" in text and "### Stage 4" in text
    assert "bounded at 0.36" not in text
    assert not [ln for ln in _table_lines(text) if BAD.search(ln)]


def test_no_runs(tmp_path):
    text = report.build_report(_tree(tmp_path), run_test_suite=False)
    assert text.splitlines()[0] == "**INTERIM — 0 of 4 stages run; stages 1–4 not yet run.**"
    assert "No final stage-1 run exists yet." in text
    assert "Not yet answered" in text


def test_no_validation_file_is_unverified(tmp_path):
    text = report.build_report(_tree(tmp_path, validation=None), run_test_suite=False)
    assert text.startswith("UNVERIFIED")


def test_passed_run(tmp_path):
    root = _tree(tmp_path, [_run(tmp_path, "r1", True, "2026-11-25T05:00")])
    text = report.build_report(root, run_test_suite=False)
    first = text.splitlines()[0]
    assert "stage 1 passed on the full-wave solver" in first and "stages 2–4 not yet run" in first
    assert "No final run exists yet for this stage." in text  # not gated once stage 1 passes
    assert "#### `s1_bird` — PASSED" in text
    assert not [ln for ln in _table_lines(text) if BAD.search(ln)]


def test_failed_run_newest_final_wins(tmp_path):
    older = _run(tmp_path, "r_old", True, "2026-11-25T03:00")
    newer = _run(tmp_path, "r_new", False, "2026-11-25T04:00")
    t0 = _run(tmp_path, "r_t0", False, "2026-11-25T06:00", status="tier0_only")
    text = report.build_report(_tree(tmp_path, [t0, newer, older]), run_test_suite=False)
    assert "stage 1 failed on the full-wave solver" in text.splitlines()[0]
    assert "#### `s1_bird` — FAILED" in text and "runs/s1_bird/r_new` (Bird)" in text
    hist = text.split("Earlier runs of this stage")[1].split("###")[0]
    assert "r_old" in hist and "r_t0" in hist
    assert "stage 1 must pass on Tier 1" in text  # stages 2-4 gated
    assert "pitch misses" in text
    assert "bounded at 0.36" not in text and "is not bounded" in text
    assert not [ln for ln in _table_lines(text) if BAD.search(ln)]


def test_validation_failed_is_unverified_first(tmp_path):
    root = _tree(tmp_path, [_run(tmp_path, "r1", True, "2026-11-25T05:00")], validation=False)
    text = report.build_report(root, run_test_suite=False)
    assert text.split()[0] == "UNVERIFIED"


def test_commentary_preserved(tmp_path):
    root = _tree(tmp_path)
    report.main(["--root", str(root), "--no-tests"])
    text = (root / "REPORT.md").read_text()
    edited = re.sub(re.escape(report.COMMENT_BEGIN) + r".*?" + re.escape(report.COMMENT_END),
                    report.COMMENT_BEGIN + "\nOwner note: keep this.\n" + report.COMMENT_END, text, flags=re.S)
    (root / "REPORT.md").write_text(edited)
    report.main(["--root", str(root), "--no-tests"])
    again = (root / "REPORT.md").read_text()
    assert "Owner note: keep this." in again
    assert again.count(report.COMMENT_BEGIN) == 1
