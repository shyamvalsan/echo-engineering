"""Judges on synthetic signals with known answers; the clean targets must pass their own stage's metrics."""

import numpy as np
import pytest

from echo.metrics import (THRESHOLDS, echo_level_db, note_sequence_score, pitch_error_pct, score_stage, spec_corr,
                          spl_db, tier_gap_db)
from echo.scene import FS
from echo.targets import bird_note, melody, motif, note_sequence

T0 = 2 * 3.06 / 343.0


def _as_echo(audio, k=5, n=int(0.12 * FS), level=0.01):
    i0 = int(round(T0 * FS))
    e = np.zeros((k, n))
    m = min(len(audio), n - i0)
    e[:, i0:i0 + m] = level * audio[:m]
    return e


def test_thresholds_verbatim_from_spec():
    assert THRESHOLDS["s1_bird"] == {"pitch_err_pct": 3.0, "spec_corr": 0.8}
    assert THRESHOLDS["s2_motif"]["note_cents_max"] == 30.0 and THRESHOLDS["s2_motif"]["notes_in_order"] == 1.0
    assert THRESHOLDS["s3_melody"]["note_cents_max"] == 50.0 and THRESHOLDS["s3_melody"]["notes_in_order"] == 1.0
    assert THRESHOLDS["s4a_vowel"]["formant_err_pct"] == 10.0
    assert THRESHOLDS["s4b_syllables"]["estoi"] == 0.5
    assert THRESHOLDS["s4c_word"]["hello_count"] == 3


def test_clean_bird_passes_and_pitch_offsets_judged():
    b = bird_note()
    assert pitch_error_pct(b.audio, b.f_track)[0] < 3.0
    assert spec_corr(b.audio, b.audio) > 0.999
    # 1 % sharp passes, 5 % sharp fails (worst-frame criterion)
    assert pitch_error_pct(bird_note(f_start=3535, f_end=2020).audio, b.f_track)[0] < 3.0
    assert pitch_error_pct(bird_note(f_start=3675, f_end=2100).audio, b.f_track)[0] > 3.0


def test_score_stage_tier0_never_passes_and_tier1_gates():
    b = bird_note()
    e = _as_echo(b.audio)
    m0 = score_stage("s1_bird", b, T0, e, e * 0.1)
    assert m0["passed"] is False and m0["verified"] is False
    assert all(not x["gating"] for x in m0["metrics"]) and all(x["tier"] == "tier0" for x in m0["metrics"])
    assert all(x["pass"] for x in m0["metrics"] if x["threshold"] is not None)  # the clean target passes
    assert abs(m0["headline"]["echo_level_db_re_direct"] - (-60.0)) < 1e-6
    m1 = score_stage("s1_bird", b, T0, e, e * 0.1, tier1_2d=e * 2)
    assert m1["verified"] and m1["passed"]
    assert abs(m1["headline"]["tier_gap_db"] - 20 * np.log10(2)) < 1e-9
    assert abs(m1["headline"]["echo_level_db_re_direct"] - (-60 + 6.0206)) < 1e-3
    bad = _as_echo(bird_note(f_start=3675, f_end=2100).audio)
    m2 = score_stage("s1_bird", b, T0, e, e * 0.1, tier1_2d=bad)
    assert m2["verified"] and not m2["passed"]
    assert len(m2["per_clap"]) == 10


def test_level_and_spl():
    e = np.zeros((2, 100))
    e[0, 10], e[1, 20] = 0.01, -0.1
    assert np.allclose(echo_level_db(e), [-40, -20])
    assert abs(spl_db(0.0) - 110.457) < 1e-3
    assert abs(tier_gap_db(e * 0.5, e) + 6.0206) < 1e-3


@pytest.mark.parametrize("tgt", [motif(), melody(100), melody(60)], ids=["motif", "melody100", "melody60"])
def test_clean_note_targets_pass(tgt):
    r = note_sequence_score(tgt.audio, tgt.notes)
    assert r["in_order"] == 1.0 and r["n_detected"] == len(tgt.notes)
    stage = "s2_motif" if tgt.name.startswith("motif") else "s3_melody"
    assert r["cents_max"] < THRESHOLDS[stage]["note_cents_max"]


def test_wrong_note_order_fails():
    tgt = motif()
    rev = note_sequence(list(reversed([n[0] for n in tgt.notes])), 0.045, "rev")
    assert note_sequence_score(rev.audio, tgt.notes)["in_order"] == 0.0
    m = score_stage("s2_motif", tgt, T0, _as_echo(tgt.audio), _as_echo(tgt.audio), tier1_2d=_as_echo(rev.audio))
    assert not m["passed"]


def test_detuned_notes_judged():
    tgt = motif()
    f = [n[0] for n in tgt.notes]
    sharp20 = note_sequence([x * 2 ** (20 / 1200) for x in f], 0.045, "s20")
    sharp40 = note_sequence([x * 2 ** (40 / 1200) for x in f], 0.045, "s40")
    assert note_sequence_score(sharp20.audio, tgt.notes)["cents_max"] < 30.0
    assert note_sequence_score(sharp40.audio, tgt.notes)["cents_max"] > 30.0


# --- note judge on perfect echoes (target convolved with each clap, band-limited to the loss band) -----------------
from echo.clap import band_limit, clap_family  # noqa: E402

CLAPS = clap_family(5)


def _perfect(audio, k):
    return band_limit(np.convolve(audio, CLAPS[k]), 898.4375, 4000.0)


def _stage_pass(stage, r):
    return r["in_order"] >= THRESHOLDS[stage]["notes_in_order"] and r["cents_max"] <= THRESHOLDS[stage]["note_cents_max"]


@pytest.mark.parametrize("k", range(5))
@pytest.mark.parametrize("stage,tgt", [("s2_motif", motif()), ("s3_melody", melody(100)), ("s3_melody", melody(60))],
                         ids=["motif", "melody100", "melody60"])
def test_perfect_echo_passes_per_clap(stage, tgt, k):
    assert _stage_pass(stage, note_sequence_score(_perfect(tgt.audio, k), tgt.notes))


def _variant(tgt, freqs):
    note_s = tgt.notes[0][2] - tgt.notes[0][1]
    return note_sequence(freqs, note_s, "variant")


@pytest.mark.parametrize("k", range(5))
def test_wrong_sequences_fail_per_clap(k):
    mel = melody(100)
    f = [n[0] for n in mel.notes]
    swapped = f.copy()
    swapped[2], swapped[3] = swapped[3], swapped[2]  # F6 <-> G6
    assert not _stage_pass("s3_melody", note_sequence_score(_perfect(_variant(mel, swapped).audio, k), mel.notes))
    det60 = f.copy()
    det60[5] *= 2 ** (60 / 1200)
    assert not _stage_pass("s3_melody", note_sequence_score(_perfect(_variant(mel, det60).audio, k), mel.notes))
    mo = motif()
    g = [n[0] for n in mo.notes]
    det40 = g.copy()
    det40[1] *= 2 ** (40 / 1200)
    assert not _stage_pass("s2_motif", note_sequence_score(_perfect(_variant(mo, det40).audio, k), mo.notes))
    missing = _variant(mo, g[:2] + g[3:])
    assert not _stage_pass("s2_motif", note_sequence_score(_perfect(missing.audio, k), mo.notes))


def test_stage_aggregator_hook_with_dummy_stage():
    from echo import metrics as M

    def judge(seg, target, fs, band):
        return {"hit": float(np.max(np.abs(seg)) > 0.005)}

    def count_hits(stage, per_clap, tier, gating):
        n = sum(pc["hit"] for pc in per_clap)
        return [{"id": "hits", "label": "claps judged a hit", "value": n, "unit": "", "threshold": 3,
                 "comparator": ">=", "pass": bool(n >= 3), "tier": tier, "gating": gating}]

    M.STAGE_METRICS["dummy"], M.STAGE_AGGREGATORS["dummy"] = judge, count_hits
    try:
        b = bird_note()
        e = _as_echo(b.audio)
        e[3:] = 0.0  # 3 of 5 claps carry the echo
        m = score_stage("dummy", b, T0, e, e, tier1_2d=e)
        t1 = [x for x in m["metrics"] if x["tier"] == "tier1"][0]
        assert t1["value"] == 3 and t1["pass"] and m["passed"]
        e[2:] = 0.0
        assert not score_stage("dummy", b, T0, e, e, tier1_2d=e)["passed"]
    finally:
        del M.STAGE_METRICS["dummy"], M.STAGE_AGGREGATORS["dummy"]


def test_judge_floor_and_info_metrics():
    b = bird_note()
    e = _as_echo(b.audio)
    m = score_stage("s1_bird", b, T0, e, e, claps=CLAPS)
    jf = m["judge_floor"]
    assert len(jf["per_clap"]) == 5 and set(jf["mean"]) >= {"pitch_err_pct", "pitch_err_median_pct", "spec_corr"}
    assert 1.0 < jf["mean"]["pitch_err_pct"] < 3.0  # the judge's own floor on a perfect echo
    med = [x for x in m["metrics"] if x["id"] == "pitch_err_median_pct"][0]
    assert med["threshold"] is None and med["gating"] is False and med["pass"] is None
    assert all(x["tier"] == "tier0" and x["gating"] is False for x in m["metrics"])
