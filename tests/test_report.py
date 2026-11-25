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


def _run(root: Path, run_id: str, passed: bool, created: str, status="final", stage="s1_bird", extra=None,
         config=None):
    d = root / "runs" / stage / run_id
    metrics = {
        "stage": stage, "passed": passed, "verified": True, "fragile": False,
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
    metrics.update(extra or {})
    # NaN is allowed by json.dumps; the generator must still never print it
    _write(d / "metrics.json", metrics)
    _write(d / "manifest.json", {"run_id": run_id, "stage": stage, "status": status, "seed": 0,
                                 "command": f"uv run python -m stages.{stage}", "git_commit": "abc",
                                 "solver": {"tier1": "fdtd", "engine": "fd8-3", "f_max": 4000.0},
                                 "design": {"config": config or {}}, "audio": {}, "field": None,
                                 "substage": (extra or {}).get("substage")})
    for f in ("target.wav", "echo_tier1.wav", "as_heard.wav"):
        (d / f).write_bytes(b"")
    return {"stage": stage, "run_id": run_id, "path": f"{stage}/{run_id}", "title": "Bird",
            "created": created, "status": status, "passed": passed, "verified": True}


def _tree(tmp_path, runs=(), validation=True):
    if validation is not None:
        _write(tmp_path / "runs" / "validation" / "metrics.json", _validation(validation))
    _write(tmp_path / "runs" / "index.json", {"runs": list(runs)})
    return tmp_path


def test_real_tree():
    text = report.build_report(ROOT, run_test_suite=False)
    assert text.splitlines()[0].startswith(("**INTERIM", "**RESULTS", "UNVERIFIED"))
    assert "### Stage 1" in text and "### Stage 4a" in text and "### Stage 4c" in text
    assert "bounded at 0.36" not in text
    assert not [ln for ln in _table_lines(text) if BAD.search(ln)]


def test_no_runs(tmp_path):
    text = report.build_report(_tree(tmp_path), run_test_suite=False)
    assert text.splitlines()[0] == ("**INTERIM — 0 of 6 passed on the full-wave solver, 6 not run: Stage 1 not run · "
                                     "Stage 2 not run · Stage 3 not run · Stage 4a not run · 4b not run · 4c not run.**")
    assert "No final stage-1 run exists yet." in text
    assert "Not yet answered" in text


def test_no_validation_file_is_unverified(tmp_path):
    text = report.build_report(_tree(tmp_path, validation=None), run_test_suite=False)
    assert text.startswith("UNVERIFIED")


def test_passed_run(tmp_path):
    root = _tree(tmp_path, [_run(tmp_path, "r1", True, "2026-11-25T05:00")])
    text = report.build_report(root, run_test_suite=False)
    first = text.splitlines()[0]
    assert "1 of 6 passed" in first and "Stage 1 passed · Stage 2 not run" in first
    assert "No final run exists yet for this stage." in text  # not gated once stage 1 passes
    assert "#### Stage 1 — PASSED" in text
    assert not [ln for ln in _table_lines(text) if BAD.search(ln)]


def test_failed_run_newest_final_wins(tmp_path):
    older = _run(tmp_path, "r_old", True, "2026-11-25T03:00", config={"target_fill": 0.01})
    newer = _run(tmp_path, "r_new", False, "2026-11-25T04:00", config={"target_fill": 0.0035})
    t0 = _run(tmp_path, "r_t0", False, "2026-11-25T06:00", status="tier0_only")
    text = report.build_report(_tree(tmp_path, [t0, newer, older]), run_test_suite=False)
    assert "Stage 1 failed" in text.splitlines()[0]
    assert "#### Stage 1 — FAILED" in text and "runs/s1_bird/r_new` (Bird)" in text
    att = text.split("Earlier attempts, Stage 1")[1].split("####")[0]
    assert "`r_new` (result)" in att and "`r_old`" in att and "first attempt" in att
    assert "target_fill: 0.01 → 0.0035" in att  # what changed, from manifest.design.config
    hist = text.split("not final (history only)")[1].split("####")[0]
    assert "r_t0" in hist
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


def _s4(tmp_path, sub, target, passed, created, extra=None):
    e = {"substage": sub, "target_name": target, **(extra or {})}
    return _run(tmp_path, f"x-s4_{sub}_{target}", passed, created, stage="s4_speech", extra=e)


def test_substages_grouped_and_pass_inside_failed_stage(tmp_path):
    runs = [_run(tmp_path, "s1", False, "2026-11-25T04:00"),
            _s4(tmp_path, "4c", "hello", True, "2026-11-25T12:00",
                {"pass_weight": "judges are lenient", "band_hz": [500.0, 2500.0],
                 "recognized_text": [{"clap": 0, "transcript": "Hello.", "hit": True}],
                 "recognizer_controls": {"cases": {"ma_echo": {"hello_count": 0, "estoi_vs_hello_mean": 0.01,
                                                                "recognized_text": [{"transcript": "you"}]}}},
                 "robustness_not_run": [{"case": "c_331", "label": "Speed of sound 331 m/s",
                                         "status": "not run (cost)"}]}),
            _s4(tmp_path, "4b", "ma", False, "2026-11-25T13:00",
                {"closed_set_3x3": {"distances": {"ma": {"ma": 3.0, "ba": 2.0}, "ba": {"ma": 4.0, "ba": 1.0}},
                                    "correct_fraction": {"ma": 0.0, "ba": 1.0}}}),
            _s4(tmp_path, "4b", "ba", True, "2026-11-25T13:30"),
            # newest run overall is 4a: it must not summarize stage 4
            _s4(tmp_path, "4a", "ah", False, "2026-11-25T14:00")]
    text = report.build_report(_tree(tmp_path, runs[::-1]), run_test_suite=False)
    first = text.splitlines()[0]
    assert "Stage 4a failed · 4b failed (ma and ba) · 4c passed" in first
    assert "1 of 6 passed" in first
    card = text.split("### Stage 4c")[1].split("## 5.")[0]
    assert "#### 4c — PASSED" in card and "Weight of this pass" in card and "judges are lenient" in card
    assert card.index("Weight of this pass") < card.index("**Metrics**")  # beside the pass, not after it
    assert "Controls" in card and "ma_echo" in card and "500, 2500 Hz" in card
    assert "| not run (cost) |" in card  # robustness case not run shown as such, not as a failure
    b4 = text.split("### Stage 4b")[1].split("### Stage 4c")[0]
    assert "#### 4b — ma — FAILED" in b4 and "#### 4b — ba — PASSED" in b4 and "closed_set_3x3" in b4
    assert not [ln for ln in _table_lines(text) if BAD.search(ln)]


def test_stage3_note_lengths_are_members(tmp_path):
    r100 = _run(tmp_path, "x-s3", False, "2026-11-25T13:00", stage="s3_melody", extra={"s3_extra": {"note_ms": 100}})
    r60 = _run(tmp_path, "x-s3_60ms", False, "2026-11-25T13:30", stage="s3_melody")
    text = report.build_report(_tree(tmp_path, [r60, r100]), run_test_suite=False)
    assert "Stage 3 failed (100 ms and 60 ms)" in text.splitlines()[0]
    assert "#### Stage 3 — 100 ms — FAILED" in text and "#### Stage 3 — 60 ms — FAILED" in text


def test_build_pilot_not_counted_as_stage(tmp_path):
    pil = _run(tmp_path, "p1", True, "2026-11-25T15:00", stage="build_pilot")
    text = report.build_report(_tree(tmp_path, [pil]), run_test_suite=False)
    assert "0 of 6 passed" in text.splitlines()[0]
    assert "runs/build_pilot/p1" in text.split("### Build pilot")[1]
