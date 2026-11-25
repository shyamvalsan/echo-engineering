"""Stage-4 judges. The judges must pass the targets themselves and must be able to fail."""

import os

import numpy as np
import pytest

from echo import metrics as M
from echo import metrics_speech as MS
from echo.clap import band_limit, clap_family
from echo.scene import FS
from echo.targets_speech import SYLLABLES, speech_target

slow = pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="loads faster-whisper; set RUN_SLOW=1")


def perfect(a, c):
    """Best physically possible echo: target convolved with the clap, band-limited (the judge floor)."""
    return band_limit(np.convolve(a, c)[: len(a)], 500.0, 4000.0)


@pytest.fixture(scope="module")
def claps():
    return clap_family(5)


@pytest.fixture(scope="module")
def syl():
    return {s: speech_target(s) for s in SYLLABLES}


def noisy(a, snr_db, seed=0):
    n = np.random.default_rng(seed).standard_normal(len(a))
    return a + n * np.sqrt(np.mean(a**2) / np.mean(n**2) / 10 ** (snr_db / 10))


# ---------------------------------------------------------------- formants
def test_formants_synthetic_vowel():
    # 120 Hz pulse train through resonators at 730 / 1090 / 2440 Hz (bandwidths 80 / 90 / 120 Hz), band-limited
    # like a target. Hand values: Peterson & Barney /a/ (male). LPC must recover F1, F2 within 3 %.
    from scipy.signal import lfilter

    n = int(0.15 * FS)
    x = np.zeros(n)
    x[:: FS // 120] = 1.0
    for f, bw in ((730, 80), (1090, 90), (2440, 120)):
        r = np.exp(-np.pi * bw / FS)
        x = lfilter([1.0], [1.0, -2 * r * np.cos(2 * np.pi * f / FS), r * r], x)
    x = band_limit(x, 500, 4000)
    f1, f2 = MS.formants(x)
    assert abs(f1 / 730 - 1) < 0.03 and abs(f2 / 1090 - 1) < 0.03, (f1, f2)


def test_formant_judge_self_zero_and_fails_other_vowel():
    ah = speech_target("ah").audio
    assert MS.formant_errors(ah, ah)["formant_err_pct"] == 0.0
    om = speech_target("om").audio  # /oU/ vowel: different F1/F2
    assert MS.formant_errors(om, ah)["formant_err_pct"] > M.THRESHOLDS["s4a_vowel"]["formant_err_pct"]


def test_formant_judge_noise_fails():
    ah = speech_target("ah").audio
    nz = band_limit(np.random.default_rng(1).standard_normal(len(ah)), 500, 4000)
    r = MS.formant_errors(nz, ah)
    assert not (r["formant_err_pct"] <= M.THRESHOLDS["s4a_vowel"]["formant_err_pct"])


# ---------------------------------------------------------------- alignment
def test_align_recovers_offset(syl, claps):
    a = syl["ma"].audio
    e = perfect(a, claps[0])
    for shift in (-48, 0, 48):  # +-3 ms
        sh = np.roll(np.pad(e, 100), shift)[100:-100]
        _, lag = MS.align(sh, a)
        _, lag0 = MS.align(e, a)
        assert abs(lag - lag0 - shift) <= 2, (shift, lag, lag0)


# ---------------------------------------------------------------- ESTOI
def test_pystoi_cannot_score_a_single_syllable(syl):
    from pystoi import stoi

    a = syl["ma"].audio
    with pytest.warns(RuntimeWarning, match="Not enough STFT frames"):
        assert stoi(a, a, FS, extended=True) == 1e-5  # why the tiling procedure exists (DECISIONS.md)


def test_estoi_self_noise_other(syl):
    for s, t in syl.items():
        a = t.audio
        assert MS.estoi(a, a) > 0.99
        assert MS.estoi(noisy(a, 0.0), a) < 0.35  # 0 dB SNR white noise
    assert MS.estoi(np.pad(syl["om"].audio, (0, 0))[: len(syl["ma"].audio)], syl["ma"].audio) < 0.2


def test_estoi_perfect_echo_passes(syl, claps):
    thr = M.THRESHOLDS["s4b_syllables"]["estoi"]
    for s, t in syl.items():
        for c in claps:
            assert MS.estoi(perfect(t.audio, c), t.audio) > thr, s


# ---------------------------------------------------------------- closed set
def test_closed_set_perfect_echo_every_clap(syl, claps):
    for s, t in syl.items():
        assert MS.closed_set(t.audio, s, t.candidates)["correct"]
        for k, c in enumerate(claps):
            r = MS.closed_set(perfect(t.audio, c), s, t.candidates)
            assert r["correct"] and r["margin"] > 0, (s, k, r)


def test_closed_set_wrong_label_fails(syl, claps):
    e = perfect(syl["ba"].audio, claps[0])
    assert not MS.closed_set(e, "ma", syl["ma"].candidates)["correct"]


# ---------------------------------------------------------------- recognizer rule (no model)
def test_hit_rule():
    for t in ("Hello.", "hello", " Hello? ", "Hello there!", "oh, hello"):
        assert MS.is_hit(t), t
    for t in ("Yellow.", "Hallo.", "hellos", "", "Ma-", "hell o"):
        assert not MS.is_hit(t), t


def test_no_answer_in_prompt():
    assert MS.WHISPER_OPTS["initial_prompt"] is None
    assert MS.WHISPER_OPTS["temperature"] == 0.0 and MS.WHISPER_OPTS["condition_on_previous_text"] is False


# ---------------------------------------------------------------- seam
def test_seam_registration_and_aggregator():
    for st in ("s4a_vowel", "s4b_syllables", "s4c_word"):
        assert st in M.STAGE_METRICS
    pc = [{"hello_hit": h, "estoi": 0.4} for h in (True, True, True, False, False)]
    ents = M.aggregate("s4c_word", pc, "tier1", True)
    hc = [e for e in ents if e["id"] == "hello_count"][0]
    assert hc["value"] == 3 and hc["pass"] and hc["gating"] and hc["threshold"] == 3
    assert not [e for e in M.aggregate("s4c_word", pc[:2] + pc[3:], "tier1", True) if e["id"] == "hello_count"][0]["pass"]
    others = [e for e in ents if e["id"] != "hello_count"]
    assert all(not e["gating"] for e in others)


def test_judge_floor_through_seam(syl, claps):
    fl = M.judge_floor("s4b_syllables", syl["om"], claps)
    assert fl["mean"]["closed_set_correct"] == 1.0 and fl["mean"]["estoi"] > 0.5
    ents = M.aggregate("s4b_syllables", [p["metrics"] for p in fl["per_clap"]], "tier1", True)
    gating = {e["id"]: e["pass"] for e in ents if e["gating"]}
    assert gating == {"closed_set_correct": True, "estoi": True}
    ah = speech_target("ah")
    ents = M.aggregate("s4a_vowel", [MS._m_vowel(ah.audio, ah, FS, None)] * 5, "tier1", True)
    assert [e["id"] for e in ents if e["gating"]] == ["formant_err_pct"]


# ---------------------------------------------------------------- recognizer (slow)
@slow
def test_whisper_clean_and_perfect_echo_and_negatives(claps):
    h = speech_target("hello").audio
    assert MS.recognize(h)[0], MS.transcribe(h)
    hits = [MS.recognize(perfect(h, c))[0] for c in claps]
    assert sum(hits) >= M.THRESHOLDS["s4c_word"]["hello_count"], [MS.transcribe(perfect(h, c)) for c in claps]
    assert not MS.recognize(speech_target("ma").audio)[0]
    assert not MS.recognize(np.random.default_rng(0).standard_normal(len(h)))[0]
