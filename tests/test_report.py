"""stages/report.py: REPORT.md + docs/report/*.md generated from files, on the real runs/ tree and on synthetic trees."""
import json
import re
from pathlib import Path

from stages import report

ROOT = Path(__file__).resolve().parents[1]
BAD = re.compile(r"\bNone\b|\bNaN\b|\bnan\b|\binf\b")
MAIN_LINE_LIMIT = 400
LV = {"by": "owner", "date": "2026-11-25", "verdict": "pass", "basis": "echo_tier1.wav by ear",
      "quote": "I think all of them are pass", "blind": False, "note": "not a blind test"}


def _table_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("|")]


def _no_commentary(text):
    return re.sub(re.escape(report.COMMENT_BEGIN) + r".*?" + re.escape(report.COMMENT_END), "", text, flags=re.S)


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


def _criteria(v1, v2, listening=True):
    c = {"criteria": {"spec_v1": {"label": "spec_v1", "passed": v1, "gating": [
        {"id": "pitch_err_pct", "label": "Pitch error", "value": 2.0 if v1 else 5.6, "unit": "%", "threshold": 3.0,
         "comparator": "<=", "pass": v1, "tier": "tier1"}]},
        "owner_v2": {"label": "owner_v2", "passed": v2, "rests_on": "C1; C2",
                     "metrics": [{"id": "id_claps", "value": 5.0 if v2 else 0.0, "threshold": 3, "pass": bool(v2)},
                                 {"id": "pitch_cents", "value": 13.4 if v2 else 800.0,
                                  "threshold": 40.0 if v2 else None, "pass": bool(v2)}],
                     "controls": [{"name": "clap_alone", "kind": "b", "pass": False}]}}}
    c["listening_verdict"] = dict(LV) if listening else None
    return c


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
                                 "design": {"config": config or {}}, "audio": {"as_heard_echo_level_db": -50.0},
                                 "field": None, "substage": (extra or {}).get("substage")})
    for f in ("target.wav", "echo_tier1.wav", "as_heard.wav"):
        (d / f).write_bytes(b"")
    return {"stage": stage, "run_id": run_id, "path": f"{stage}/{run_id}", "title": "Bird",
            "created": created, "status": status, "passed": passed, "verified": True}


def _tree(tmp_path, runs=(), validation=True, criteria=None):
    if validation is not None:
        _write(tmp_path / "runs" / "validation" / "metrics.json", _validation(validation))
    _write(tmp_path / "runs" / "index.json", {"runs": list(runs)})
    if criteria is not None:
        _write(tmp_path / "runs" / "_criteria" / "summary.json", criteria)
    return tmp_path


def _three_test_tree(tmp_path):
    """bird: v1 fail, v2 PASS; motif: v1 fail, v2 null; hello: v1 pass, v2 pass. All heard by the owner."""
    runs = [_run(tmp_path, "20261125-100000-s1", False, "2026-11-25T10:00", extra=_criteria(False, True)),
            _run(tmp_path, "20261125-110000-s2", False, "2026-11-25T11:00", stage="s2_motif",
                 extra=_criteria(False, None)),
            _run(tmp_path, "20261125-120000-s2v2", False, "2026-11-25T12:00", stage="s2_motif",
                 extra=_criteria(False, None, listening=False)),
            _run(tmp_path, "20261125-130000-s4_4c_hello", True, "2026-11-25T13:00", stage="s4_speech",
                 extra={"substage": "4c", "target_name": "hello", **_criteria(True, True)})]
    crit = {"label_v1": "spec_v1 (original)", "label_v2": "owner_v2 (revised)", "listening_verdict": LV,
            "accepted_runs": {"s1_bird": "20261125-100000-s1", "s2_motif": "20261125-110000-s2",
                              "s4c_hello": "20261125-130000-s4_4c_hello"},
            "tests": {"s1_bird": {"title": "Stage 1 bird whistle", "controls_rejected": 26, "controls_total": 26,
                                  "rests_on": "C1; C2", "established": True},
                      "s2_motif": {"title": "Stage 2 four-note motif", "controls_rejected": 28, "controls_total": 28,
                                   "rests_on": "C1; C2 pitch within None c", "established": False,
                                   "note": "accepted by ear; no automated criterion separates it"},
                      "s4c_hello": {"title": "4c word \"hello\"", "controls_rejected": 15, "controls_total": 15,
                                    "rests_on": "C3 = the spec_v1 recognizer (not an independent confirmation)",
                                    "established": True}},
            "runs": [{"test": "s1_bird", "run_id": "20261125-100000-s1", "accepted": True, "spec_v1": False,
                      "owner_v2": True, "listening": "pass (owner, not blind)", "controls_rejected": 26,
                      "controls_total": 26}]}
    return _tree(tmp_path, runs[::-1], criteria=crit)


def test_real_tree():
    files = report.build_all(ROOT, run_test_suite=False)
    text = files["REPORT.md"]
    assert text.startswith(("# Composed Echo", "UNVERIFIED"))
    assert len(text.splitlines()) <= MAIN_LINE_LIMIT
    status = text.splitlines()[2]
    assert "original spec thresholds:" in status and "owner's ear" in status and "revised thresholds:" in status
    assert "not blind" in status and "all passed" not in text.lower()
    for name, _ in report.APPENDICES:
        assert str(report.APPENDIX_DIR / name) in files
    assert "### Stage 1" in files["docs/report/scorecards.md"] and "### Stage 4c" in files["docs/report/scorecards.md"]
    assert "bounded at 0.36" not in "".join(files.values())
    # the rulings list is complete: one table row per Ruling: in the ledger, and the main report gives the count
    led = (ROOT / report.LEDGER).read_text() if (ROOT / report.LEDGER).exists() else ""
    n = len(re.findall(r"Ruling:\s*(.+)$", led, re.M))
    if n:
        tl = files["docs/report/timeline-and-rulings.md"]
        assert len([ln for ln in tl.split("Rulings the controller made")[1].splitlines() if re.match(r"\| \d+ \|", ln)]) == n
        assert f"**{n} rulings**" in text
    for t in files.values():
        assert not [ln for ln in _table_lines(t) if BAD.search(ln)]
    assert not BAD.search(_no_commentary(text))


def test_three_counts_never_merged(tmp_path):
    files = report.build_all(_three_test_tree(tmp_path), run_test_suite=False)
    text = files["REPORT.md"]
    status = text.splitlines()[2]
    assert "original spec thresholds: 1 of 3 passed" in status
    assert "owner's ear (2026-11-25, not blind): 3 of 3 accepted" in status
    assert "revised thresholds: 2 of 3 confirmed automatically" in status and "1 not established" in status
    assert "1 of 3 accepted by ear (not blind) and not confirmed by any automated test" in status
    assert "not independent" in status  # hello's revised pass rests on the original recognizer
    assert not re.search(r"\b3 of 3 passed\b|all passed|\b[23] of 3 passed\b", text)
    assert "To be confirmed by the owner" in text and "20261125-120000-s2v2" in text


def test_null_rendered_not_established(tmp_path):
    files = report.build_all(_three_test_tree(tmp_path), run_test_suite=False)
    row = next(ln for ln in _table_lines(files["REPORT.md"]) if ln.startswith("| Stage 2 four-note motif"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[3] == "not established"  # revised-thresholds column: neither PASS nor fail
    assert "not established" in files["docs/report/criteria.md"]
    assert "None c" not in files["docs/report/criteria.md"]
    assert report.v2_word(None) == "not established" and report.v2_word(False) == "fail"
    assert report.v2_word(True) == "PASS" and report.v2_word(report.MISSING) == "not scored"


def test_listening_verdict_always_not_blind(tmp_path):
    assert "not blind" in report.ear_word(LV) and "not blind" in report.ear_word(LV, short=True)
    assert report.ear_word(None) == "not heard by the owner"
    files = report.build_all(_three_test_tree(tmp_path), run_test_suite=False)
    for name in ("REPORT.md", "docs/report/scorecards.md", "docs/report/criteria.md"):
        for ln in _no_commentary(files[name]).splitlines():
            if re.search(r"accepted by ear|Owner's ear: accepted|pass \(owner", ln):
                assert "not blind" in ln, (name, ln)


def test_appendices_written_and_linked(tmp_path):
    root = _three_test_tree(tmp_path)
    report.main(["--root", str(root), "--no-tests"])
    text = (root / "REPORT.md").read_text()
    for name, _ in report.APPENDICES:
        p = root / report.APPENDIX_DIR / name
        assert p.exists() and p.read_text().startswith("*Appendix of [REPORT.md](../../REPORT.md)")
        assert f"(docs/report/{name}" in text
    assert len(text.splitlines()) <= MAIN_LINE_LIMIT


def test_no_runs(tmp_path):
    files = report.build_all(_tree(tmp_path), run_test_suite=False)
    assert "**Status: no final results yet.**" in files["REPORT.md"]
    assert "No final stage-1 run exists yet." in files["docs/report/scorecards.md"]
    assert "Not yet answered" in files["docs/report/design-studies.md"]


def test_no_criteria_file_is_not_scored(tmp_path):
    root = _tree(tmp_path, [_run(tmp_path, "r1", True, "2026-11-25T05:00")])
    text = report.build_report(root, run_test_suite=False)
    status = text.splitlines()[2]
    assert "original spec thresholds: 1 of 1 passed" in status and "revised thresholds: not scored" in status
    assert "owner's ear: 0 of 1 heard" in status


def test_no_validation_file_is_unverified(tmp_path):
    text = report.build_report(_tree(tmp_path, validation=None), run_test_suite=False)
    assert text.startswith("UNVERIFIED")


def test_validation_failed_is_unverified_first(tmp_path):
    root = _tree(tmp_path, [_run(tmp_path, "r1", True, "2026-11-25T05:00")], validation=False)
    text = report.build_report(root, run_test_suite=False)
    assert text.split()[0] == "UNVERIFIED"


def test_failed_run_newest_final_wins(tmp_path):
    older = _run(tmp_path, "r_old", True, "2026-11-25T03:00", config={"target_fill": 0.01})
    newer = _run(tmp_path, "r_new", False, "2026-11-25T04:00", config={"target_fill": 0.0035})
    t0 = _run(tmp_path, "r_t0", False, "2026-11-25T06:00", status="tier0_only")
    files = report.build_all(_tree(tmp_path, [t0, newer, older]), run_test_suite=False)
    sc = files["docs/report/scorecards.md"]
    assert "#### Stage 1 — newest run, original thresholds: missed" in sc and "runs/s1_bird/r_new` (Bird)" in sc
    att = sc.split("Earlier attempts, Stage 1")[1].split("####")[0]
    assert "`r_new` (result)" in att and "`r_old`" in att and "first attempt" in att
    assert "target_fill: 0.01 → 0.0035" in att  # what changed, from manifest.design.config
    assert "r_t0" in sc.split("not final (history only)")[1]
    assert "pitch misses" in sc
    val = files["docs/report/validation.md"]
    assert "bounded at 0.36" not in val and "is not bounded" in val
    for t in files.values():
        assert not [ln for ln in _table_lines(t) if BAD.search(ln)]


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


def test_substages_grouped_in_scorecards(tmp_path):
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
            _s4(tmp_path, "4a", "ah", False, "2026-11-25T14:00")]
    files = report.build_all(_tree(tmp_path, runs[::-1]), run_test_suite=False)
    status = files["REPORT.md"].splitlines()[2]
    assert "original spec thresholds: 2 of 5 passed" in status  # one row per test (4b ma and ba separately)
    sc = files["docs/report/scorecards.md"]
    card = sc.split("### Stage 4c")[1]
    assert "#### 4c — newest run, original thresholds: passed" in card and "Weight of this pass" in card
    assert card.index("Weight of this pass") < card.index("**Metrics**")  # beside the pass, not after it
    assert "Controls" in card and "ma_echo" in card and "500, 2500 Hz" in card
    assert "| not run (cost) |" in card  # robustness case not run shown as such, not as a failure
    b4 = sc.split("### Stage 4b")[1].split("### Stage 4c")[0]
    assert "#### 4b — ma — newest run, original thresholds: missed" in b4 and "closed_set_3x3" in b4
    assert "#### 4b — ba — newest run, original thresholds: passed" in b4


def test_stage3_note_lengths_are_members(tmp_path):
    r100 = _run(tmp_path, "x-s3", False, "2026-11-25T13:00", stage="s3_melody", extra={"s3_extra": {"note_ms": 100}})
    r60 = _run(tmp_path, "x-s3_60ms", False, "2026-11-25T13:30", stage="s3_melody")
    sc = report.build_all(_tree(tmp_path, [r60, r100]), run_test_suite=False)["docs/report/scorecards.md"]
    assert "#### Stage 3 — 100 ms — newest run" in sc and "#### Stage 3 — 60 ms — newest run" in sc


def test_build_pilot_not_counted_as_stage(tmp_path):
    pil = _run(tmp_path, "p1", True, "2026-11-25T15:00", stage="build_pilot")
    files = report.build_all(_tree(tmp_path, [pil]), run_test_suite=False)
    assert "no final results yet" in files["REPORT.md"].splitlines()[2]
    assert "runs/build_pilot/p1" in files["docs/report/design-studies.md"].split("### Build pilot")[1]


def test_count_rule_per_clap_rows_not_applicable():
    """4c's pass rule counts claps (hello_count >= 3 of 5): a lone clap can never meet it, so the per-clap robustness
    rows read "not applicable" instead of FAIL (presentation only; the stored pass flags are unchanged)."""
    run = {"metrics": {
        "metrics": [{"id": "hello_count", "tier": "tier1", "gating": True, "value": 5, "comparator": ">=",
                     "threshold": 3}],
        "robustness": [{"case": "nominal", "label": "Nominal", "pass": True, "metrics": {"hello_count": 5},
                        "delta": {"hello_count": 0}},
                       {"case": "clap_0", "label": "Clap variant 0 alone", "pass": False,
                        "metrics": {"hello_count": 1}, "delta": {"hello_count": -4}}],
        "fragile_reason": "0/5 clap variants pass on their own; 2/3 listener positions pass"}}
    t = report._robust_table(run)
    row = next(ln for ln in t.splitlines() if "clap_0" in ln)
    assert "not applicable" in row and "FAIL" not in row
    assert "PASS" in next(ln for ln in t.splitlines() if "nominal" in ln)
    assert report.fragile_text(run).startswith("clap variants alone: not applicable")
    pitch = {"metrics": dict(run["metrics"], metrics=[{"id": "pitch_err_pct", "tier": "tier1", "gating": True}])}
    assert "FAIL" in next(ln for ln in report._robust_table(pitch).splitlines() if "clap_0" in ln)
    assert report.fragile_text(pitch).startswith("0/5")


def test_note_cents_sentinel_and_other_word_caveat():
    assert "not matched" in report.num(1200.0, "note_cents_max") and report.num(30.0, "note_cents_max") == "30.00"
    m = {"controls": {"other_words": {"rows": {
        "hello": {"tier0_hello_count": 5, "tier0_recognized_text": [{}] * 5},
        "yellow": {"tier0_hello_count": 1, "tier0_recognized_text": [{}] * 5},
        "mellow": {"tier0_hello_count": 2, "tier0_recognized_text": [{}] * 5},
        "halo": {"tier0_hello_count": 0, "tier0_recognized_text": [{}] * 5}}}}}
    assert report.stored_other_words(m)[:2] == (3, 15)
    assert "3 of 15" in report.other_words_caveat(m) and "not found" in report.other_words_caveat(m)
    assert report.other_words_caveat({}) == ""
