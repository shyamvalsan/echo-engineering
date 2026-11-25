"""Stage-4 speech targets: cached espeak-ng audio, durations, band, normalisation, measured "ah" formants."""

import numpy as np
import pytest

from echo.metrics_speech import formants
from echo.scene import FS
from echo.targets_speech import RAW_DIR, SPEECH, SYLLABLES, speech_target


@pytest.fixture(scope="module")
def targets():
    return {n: speech_target(n) for n in SPEECH}


def test_raw_cache_committed_and_used(targets):
    for n in SPEECH:
        assert (RAW_DIR / f"{n}.wav").exists()
        assert targets[n].source == "cache"  # stage 4 does not need espeak-ng on the PATH


def test_durations_match_spec(targets):
    assert abs(targets["ah"].duration_s - 0.150) < 1e-9
    for s in SYLLABLES:
        assert 0.200 <= targets[s].duration_s <= 0.250, s
    assert abs(targets["hello"].duration_s - 0.400) < 0.015


def test_peak_normalised_band_limited_and_faded(targets):
    for n, t in targets.items():
        a = t.audio
        assert t.f_top_hz == 4000.0
        assert abs(np.max(np.abs(a)) - 1.0) < 1e-12
        X = np.abs(np.fft.rfft(a, 1 << 15)) ** 2
        f = np.fft.rfftfreq(1 << 15, 1 / FS)
        out = X[(f < 350) | (f > 4600)].sum() / X.sum()  # outside the 500-4000 Hz band and its cosine edges
        assert out < 1e-4, (n, out)  # -40 dB; the residue is leakage of the finite-length output
        assert abs(a[0]) < 0.05 and abs(a[-1]) < 0.05


def test_deterministic():
    a, b = speech_target("ma"), speech_target("ma")
    assert np.array_equal(a.audio, b.audio)
    assert set(a.candidates) == set(SYLLABLES) and np.array_equal(a.candidates["ma"], a.audio)


def test_ah_formants_in_band(targets):
    # "ah" (/A:/) was chosen because its first two formants lie in the 500-4000 Hz band: F1 ~ 700-800, F2 ~ 1100-1300.
    f1, f2 = formants(targets["ah"].audio)
    assert 650 < f1 < 850 and 1050 < f2 < 1350, (f1, f2)
