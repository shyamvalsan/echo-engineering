"""owner_v2 judges: accept perfect echoes, reject controls built from perfect echoes, determinism, one threshold home,
and rescore's read-modify-write of metrics.json."""

import json
import shutil

import numpy as np
import pytest

import echo.metrics_v2 as V
from echo.clap import clap_family
from echo.targets import bird_note, motif

CLAPS = clap_family(5)
BAND = (500.0, 4000.0)


def _set():
    """Two tonal tests with the closed set the rescore builds (other test's target + own transforms)."""
    tg = {"s1_bird": bird_note(), "s2_motif": motif()}
    others = {k: v.audio for k, v in tg.items()}
    return tg, {k: V.distractors(k, tg[k], others) for k in tg}


def _perfect(t):
    return np.stack([V.perfect_echo(t.audio, c, BAND) for c in CLAPS])


@pytest.fixture(scope="module")
def tonal():
    tg, cands = _set()
    out = {}
    for k, t in tg.items():
        per = _perfect(t)
        out[k] = (t, cands[k], per, V.clap_values(k, per, t, cands[k]))
    return out


def test_perfect_echoes_pass_every_clap(tonal):
    for k, (t, cands, per, pc) in tonal.items():
        assert all(v["id_correct"] for v in pc), k
        assert all(v["pitch_cents"] < 25.0 for v in pc), (k, [v["pitch_cents"] for v in pc])
        thr = {"pitch_cents": 50.0}  # the nearest-semitone bound; any calibrated threshold must lie above the floor
        assert all(V.clap_passes(k, v, thr) for v in pc)
        assert V.verdict(k, pc, thr)[1]


def test_controls_from_perfect_echoes_fail(tonal):
    thr = {"pitch_cents": 50.0}
    for k, (t, cands, per, pc) in tonal.items():
        n = per.shape[-1]
        other = [u for u in tonal if u != k][0]
        ctrls = {"reversed": V.time_reversed(per),
                 "scrambled": np.stack([V.phase_scrambled(s, BAND, seed=i) for i, s in enumerate(per)]),
                 "clap": np.stack([V.clap_alone(c, n) for c in CLAPS]),
                 "noise": np.stack([V.noise_burst(n, c, BAND, seed=i) for i, c in enumerate(CLAPS)]),
                 "wrong": V.fit(tonal[other][2], n)}
        ctrls.update({f"shift{s:+.0f}": V.pitch_shifted(per, s) for s in V.SHIFTS_SEMI})
        if k in V.MULTI_NOTE:
            ctrls["swap"] = V.notes_swapped(per, t.notes)
        for name, segs in ctrls.items():
            assert not V.verdict(k, V.clap_values(k, segs, t, cands), thr)[1], (k, name)


def test_control_builders():
    x = np.random.default_rng(1).standard_normal((2, 1600))
    assert np.array_equal(V.time_reversed(V.time_reversed(x)), x)
    s = V.phase_scrambled(x, (0.0, 8000.0), seed=3)
    assert np.allclose(np.abs(np.fft.rfft(s)), np.abs(np.fft.rfft(x)), rtol=1e-6, atol=1e-6)
    tone = np.sin(2 * np.pi * 1000.0 * np.arange(1600) / 16000)
    up = V.pitch_shifted(tone, 12.0)
    f = np.fft.rfftfreq(1600, 1 / 16000)[np.argmax(np.abs(np.fft.rfft(up[:800], 1600)))]
    assert abs(f - 2000.0) <= 10.0
    m = motif()
    sw = V.notes_swapped(m.audio, m.notes)
    i0, i1 = int(round(m.notes[2][1] * 16000)), int(round(m.notes[2][2] * 16000))
    j0 = int(round(m.notes[3][1] * 16000))
    assert np.array_equal(sw[i0:i1], m.audio[j0:j0 + (i1 - i0)])


def test_dtw_matches_reference():
    from echo.metrics_speech import _dtw

    rng = np.random.default_rng(0)
    A, B = rng.standard_normal((4, 9)), rng.standard_normal((4, 13))
    assert V.dtw(A, B) == pytest.approx(_dtw(A, B), rel=1e-12)


def test_deterministic(tonal):
    t, cands, per, pc = tonal["s1_bird"]
    assert V.clap_values("s1_bird", per, t, cands) == pc
    n = per.shape[-1]
    assert np.array_equal(V.noise_burst(n, CLAPS[0], BAND, seed=0), V.noise_burst(n, CLAPS[0], BAND, seed=0))


def test_threshold_rule_and_single_home():
    assert V.calibrate_pitch([10.0, 14.0], [68.0, 80.0]) == (40.0, 14.0, 68.0)
    assert V.calibrate_pitch([70.0], [68.0])[0] is None
    assert V.calibrate_pitch([30.0], [60.0])[0] is None  # midpoint 45 is only 15 c from each side
    assert V.calibrate_pitch([225.0, 5.0], [260.0, 300.0])[0] is None  # the r1 stage-2 case: above half a semitone
    assert V.calibrate_pitch([225.0, 5.0], [96.0, 260.0])[0] is None  # perfect-echo mistunings included
    assert V.majority_value([5, 1, 4, 2, 3]) == 3.0
    assert set(V.THRESHOLDS_V2) == {"s1_bird", "s2_motif", "s3_melody_100ms", "s3_melody_60ms", "s4a_ah", "s4b_ma",
                                    "s4b_ba", "s4b_om", "s4c_hello"}
    # clap_passes reads THRESHOLDS_V2 when no override is given
    v = {"id_correct": True, "id_margin": 1.0, "nearest": "s1_bird", "pitch_cents": 1.0}
    assert V.clap_passes("s1_bird", v) == (V.THRESHOLDS_V2["s1_bird"]["pitch_cents"] is not None)


def test_spec_v1_block_is_a_mirror():
    m = {"passed": False, "metrics": [{"id": "a", "label": "A", "value": 1.0, "unit": "", "threshold": 2.0,
                                       "comparator": ">=", "pass": False, "tier": "tier1", "gating": True},
                                      {"id": "b", "gating": False}]}
    b = V.spec_v1_block(m)
    assert b["passed"] is False and [g["id"] for g in b["gating"]] == ["a"]


def test_rescore_temp_copy_adds_two_keys_only(tmp_path):
    """Rescore one stage-1 run on a temp copy: only `criteria` and `listening_verdict` are added, `passed` unchanged."""
    from echo import export
    from stages import rescore

    src = export.ROOT / "runs" / "s1_bird" / "20261125-104529-s1"
    if not src.exists():
        pytest.skip("stage-1 run not present")
    dst = tmp_path / "runs" / "s1_bird" / src.name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("field.webm", "iters"))
    before = json.loads((dst / "metrics.json").read_text())
    before.pop("criteria", None), before.pop("listening_verdict", None)
    (dst / "metrics.json").write_text(json.dumps(before, indent=1))
    other = {p.name: p.read_bytes() for p in dst.iterdir() if p.is_file() and p.name != "metrics.json"}
    (tmp_path / "runs" / "index.json").write_text(json.dumps({"runs": [
        {"stage": "s1_bird", "run_id": src.name, "path": f"s1_bird/{src.name}", "title": "", "created": "",
         "status": "final", "passed": False, "verified": True}]}))
    blocks, tests = rescore.study(tmp_path / "runs", log=lambda *a: None, tests=["s1_bird"])
    rescore.write_run_blocks(blocks)
    after = json.loads((dst / "metrics.json").read_text())
    assert set(after) - set(before) == {"criteria", "listening_verdict"}
    assert {k: after[k] for k in before} == before
    assert after["passed"] == before["passed"]
    assert after["criteria"]["spec_v1"]["passed"] == before["passed"]
    assert after["criteria"]["owner_v2"]["label"] == V.LABEL
    assert after["listening_verdict"]["verdict"] == "pass" and after["listening_verdict"]["blind"] is False
    assert {p.name: p.read_bytes() for p in dst.iterdir() if p.is_file() and p.name != "metrics.json"} == other
    rescore.write_run_blocks(blocks)  # idempotent
    assert json.loads((dst / "metrics.json").read_text()) == after


def test_frozen_thresholds_and_c1_path():
    """The frozen THRESHOLDS_V2 are what clap_passes uses by default; c1: False (4c) ignores identification."""
    v = {"id_correct": True, "id_margin": 1.0, "nearest": "s1_bird", "pitch_cents": 39.0}
    t1 = V.THRESHOLDS_V2["s1_bird"]["pitch_cents"]
    assert t1 is not None and t1 < V.MAX_PITCH_T_CENTS
    assert V.clap_passes("s1_bird", dict(v, pitch_cents=t1)) and not V.clap_passes("s1_bird", dict(v, pitch_cents=t1 + 1))
    assert not V.clap_passes("s1_bird", dict(v, id_correct=False))
    assert V.THRESHOLDS_V2["s4c_hello"].get("c1") is False
    h = {"id_correct": False, "id_margin": -5.0, "nearest": "s1_bird", "hello_hit": True}
    assert V.clap_passes("s4c_hello", h) and not V.clap_passes("s4c_hello", dict(h, hello_hit=False))
    assert V.clap_passes("s4c_hello", h, thr={}) is False  # with C1 used it would fail
    assert "spec_v1 recognizer" in V.rests_on("s4c_hello")
    assert set(V.ACCEPTED_RUNS) == set(V.THRESHOLDS_V2)


@pytest.mark.parametrize("test", ["s1_bird", "s2_motif", "s3_melody_60ms", "s3_melody_100ms"])
def test_near_miss_negatives_fail(test):
    """At least one near-miss negative per tonal test (perfect echo of an altered target) fails under the frozen
    criterion; for multi-note targets the per-note C2 rejects a single wrong note by itself."""
    from echo.targets import melody

    t = {"s1_bird": bird_note(), "s2_motif": motif(), "s3_melody_60ms": melody(60),
         "s3_melody_100ms": melody(100)}[test]
    others = {"s1_bird": bird_note().audio, "s2_motif": motif().audio}
    others[test] = t.audio
    cands = V.distractors(test, t, others)
    nm = V.near_miss_targets(test, t)
    name = "rising_glide" if test == "s1_bird" else "wrong_note2_+100c"
    segs = np.stack([V.perfect_echo(nm[name], c, BAND) for c in CLAPS[:3]])
    pc = V.clap_values(test, segs, t, cands)
    assert not any(V.clap_passes(test, x) for x in pc)
    if test in V.MULTI_NOTE:
        assert all(x["pitch_cents"] > 60.0 for x in pc)  # the wrong note is seen by the per-note pitch
