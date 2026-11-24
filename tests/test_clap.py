import numpy as np
import pytest

from echo.clap import log_centroid_hz, band_limit, clap_family, clap_params
from echo.scene import FS


def _spectrum(x, nfft=8192):
    X = np.abs(np.fft.rfft(x, nfft)) ** 2
    f = np.fft.rfftfreq(nfft, 1 / FS)
    return f, X


def test_shape_norm_determinism():
    c = clap_family()
    assert c.shape == (5, 128)  # 8 ms at 16 kHz
    np.testing.assert_allclose(np.max(np.abs(c), axis=1), 1.0)
    np.testing.assert_array_equal(c, clap_family())
    assert not np.allclose(c, clap_family(seed=1))
    # Variants are distinct.
    for i in range(5):
        for j in range(i + 1, 5):
            assert not np.allclose(c[i], c[j])


def test_band_energy_and_dc():
    for x in clap_family():
        f, X = _spectrum(x)
        tot = X.sum()
        assert abs(x.sum()) < 1e-9  # zero DC
        assert X[f < 300].sum() / tot < 1e-3  # negligible below 300 Hz
        assert X[(f >= 1000) & (f <= 4000)].sum() / tot > 0.75  # energy mainly 1-4 kHz


def test_spectral_peaks():
    # A 2-5 ms noise burst has a ragged spectrum, so the "peak" is measured as the energy-weighted
    # geometric-mean frequency, compared against each variant's designed peak.
    lcs = np.array([log_centroid_hz(x, FS)[0] for x in clap_family()])
    design = np.array([p["peak_hz"] for p in clap_params()])
    np.testing.assert_allclose(lcs, design, rtol=0.06)
    assert np.mean(lcs) == pytest.approx(2500, rel=0.05)  # family centred near 2.5 kHz
    assert np.ptp(lcs) > 700  # different spectral peaks (2.0-3.0 kHz designed)
    for seed in range(1, 4):  # holds for other seeds too
        lc = np.array([log_centroid_hz(x, FS)[0] for x in clap_family(seed=seed)])
        np.testing.assert_allclose(lc, design, rtol=0.06)


def test_durations():
    ext = []
    for x, p in zip(clap_family(), clap_params()):
        assert np.max(np.abs(x[: int(0.0005 * FS)])) > 0.05  # onset at sample 0, not delayed
        last = np.nonzero(np.abs(x) > 0.01)[0][-1] / FS * 1000  # end of the burst at -40 dB re peak
        ext.append(last)
        assert last == pytest.approx(p["duration_ms"], rel=0.25), (last, p)
    ext = np.array(ext)
    assert np.all((ext >= 1.5) & (ext <= 5.0)), ext  # 2-5 ms bursts
    assert np.ptp(ext) > 2.0, ext  # different durations


def test_band_limit_zero_phase_and_band():
    n = 4000
    t = np.arange(n) / FS
    x = np.sin(2 * np.pi * 200 * t) + np.sin(2 * np.pi * 1500 * t) + np.sin(2 * np.pi * 6000 * t)
    y = band_limit(x, 500, 4000)
    mid = slice(1000, 3000)
    ref = np.sin(2 * np.pi * 1500 * t)
    # Pass-band tone survives unchanged in amplitude and phase; out-of-band tones removed.
    assert np.max(np.abs(y[mid] - ref[mid])) < 0.02
    # Impulse response is symmetric (zero phase).
    imp = np.zeros(1001)
    imp[500] = 1
    h = band_limit(imp, 500, 4000)
    np.testing.assert_allclose(h, h[::-1], atol=1e-12)
    # Batched along the last axis.
    assert band_limit(np.stack([x, x]), 500, 4000).shape == (2, n)
