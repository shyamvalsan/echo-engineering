"""Clap family: short band-shaped noise bursts, and a zero-phase band-limit helper.

A clap variant is the pressure the listener receives directly (direct arrival, delay removed),
peak-normalized to 1, sample 0 = onset. Every forward model returns echoes relative to it.
"""

from __future__ import annotations

import numpy as np

from echo.scene import FS

CLAP_LEN_S = 0.008  # every variant is stored in an 8 ms buffer (128 samples at 16 kHz)

# (duration ms, spectral peak Hz, log-bandwidth sigma in octaves) per variant; the first is the nominal clap.
CLAP_VARIANTS = (
    (3.0, 2500.0, 0.55),
    (2.3, 2800.0, 0.60),
    (5.0, 2200.0, 0.50),
    (2.5, 3000.0, 0.55),
    (4.0, 2000.0, 0.55),
    (3.5, 2600.0, 0.45),
    (4.5, 2350.0, 0.60),
)


def band_limit(x, f_lo, f_hi, fs=FS, trans_hz=None):
    """Zero-phase band-pass along the last axis (FFT mask with raised-cosine edges, zero-padded, no wrap).

    f_lo <= 0 or None: no high-pass. f_hi >= fs/2 or None: no low-pass. trans_hz is the full width of each
    cosine edge (default: 25 % of the edge frequency, at least 50 Hz). Output has the input's length.
    """
    x = np.asarray(x, dtype=float)
    n = x.shape[-1]
    nfft = int(2 ** np.ceil(np.log2(2 * n + 64)))
    pad = (nfft - n) // 2
    xp = np.zeros(x.shape[:-1] + (nfft,))
    xp[..., pad : pad + n] = x
    f = np.fft.rfftfreq(nfft, 1.0 / fs)
    mask = np.ones_like(f)

    def edge(f0):
        w = trans_hz if trans_hz is not None else max(50.0, 0.25 * f0)
        return f0, w

    if f_lo is not None and f_lo > 0:
        f0, w = edge(f_lo)
        lo = np.clip((f - (f0 - w / 2)) / w, 0.0, 1.0)
        mask *= 0.5 - 0.5 * np.cos(np.pi * lo)
    if f_hi is not None and f_hi < fs / 2:
        f0, w = edge(f_hi)
        hi = np.clip(((f0 + w / 2) - f) / w, 0.0, 1.0)
        mask *= 0.5 - 0.5 * np.cos(np.pi * hi)
    y = np.fft.irfft(np.fft.rfft(xp, axis=-1) * mask, n=nfft, axis=-1)
    return y[..., pad : pad + n]


ONSET_RAMP_S = 0.0003  # raised-cosine onset ramp, 0.3 ms
N_CANDIDATES = 32  # noise draws per variant; the one whose spectrum best matches the design is kept


def log_centroid_hz(y, fs):
    """Energy-weighted geometric-mean frequency (a robust 'spectral peak' for a noise burst)."""
    X = np.abs(np.fft.rfft(y, 4096)) ** 2
    f = np.fft.rfftfreq(4096, 1.0 / fs)
    m = f > 0
    return float(2 ** (np.sum(X[m] * np.log2(f[m])) / X[m].sum())), X, f


def _one_clap(dur_s, f_peak, sigma_oct, rng, fs):
    n_out = int(round(CLAP_LEN_S * fs))
    lead = 64  # room for zero-phase pre-ringing, cropped afterwards
    nfft = 1024
    n_burst = int(round(dur_s * fs))
    t = np.arange(n_burst) / fs
    # Envelope: 0.25 ms raised-cosine attack, exponential decay (tau = dur/2.5), cosine tail over the last 30 %.
    att = max(2, int(round(0.00025 * fs)))
    env = np.exp(-t / (dur_s / 2.5))
    env[:att] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(att) / att)
    tail = max(2, int(0.3 * n_burst))
    env[-tail:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(1, tail + 1) / tail)
    # Spectral shaping: log-Gaussian around f_peak, high-pass 300-600 Hz, low-pass taper 4-6 kHz (zero-phase).
    f = np.fft.rfftfreq(nfft, 1.0 / fs)
    with np.errstate(divide="ignore"):
        octs = np.log2(np.where(f > 0, f, 1e-9) / f_peak)
    shape = np.exp(-0.5 * (octs / sigma_oct) ** 2)
    shape *= np.clip((f - 300.0) / 300.0, 0.0, 1.0) ** 2
    shape *= 0.5 + 0.5 * np.cos(np.pi * np.clip((f - 4000.0) / 2000.0, 0.0, 1.0))
    k = int(0.001 * fs)
    ramp = max(2, int(round(ONSET_RAMP_S * fs)))
    onset = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)  # starts at exactly 0
    w = np.hanning(n_out)
    best, best_cost = None, np.inf
    for _ in range(N_CANDIDATES):
        buf = np.zeros(nfft)
        buf[lead : lead + n_burst] = rng.standard_normal(n_burst) * env
        y = np.fft.irfft(np.fft.rfft(buf) * shape, n=nfft)[lead : lead + n_out]
        # Onset ramp (cropping the zero-phase pre-ringing leaves a step at sample 0), fade the last 1 ms to
        # zero, then remove residual DC with a Hann-shaped correction (zero at both ends).
        y[:ramp] *= onset
        y[-k:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(1, k + 1) / k)
        y -= w * (y.sum() / w.sum())
        # A short burst has few degrees of freedom, so its spectrum is random; keep the draw closest to the design.
        lc, X, ff = log_centroid_hz(y, fs)
        in_band = X[(ff >= 1000) & (ff <= 4000)].sum() / X.sum()
        low = X[ff < 300].sum() / X.sum()
        cost = 3.0 * abs(np.log2(lc / f_peak)) + (1.0 - in_band) + 20.0 * low + (1.0 if low > 5e-4 else 0.0)
        if cost < best_cost:
            best, best_cost = y, cost
    return best / np.max(np.abs(best))


def clap_family(n=5, fs=FS, seed=0) -> np.ndarray:
    """K clap variants, array [n, Nc] at fs (Nc = 8 ms). Deterministic for a given seed.

    Noise bursts 2-5 ms long (-40 dB extent), 0.3 ms raised-cosine onset, energy mainly 1-4 kHz, spectral peaks 2.0-3.0 kHz (nominal 2.5 kHz),
    zero DC, negligible energy below 300 Hz, each peak-normalized to 1. Up to 7 distinct variants.
    """
    if not 1 <= n <= len(CLAP_VARIANTS):
        raise ValueError(f"n must be in 1..{len(CLAP_VARIANTS)}")
    out = []
    for k in range(n):
        dur_ms, f_peak, sigma = CLAP_VARIANTS[k]
        rng = np.random.default_rng([seed, k])
        out.append(_one_clap(dur_ms / 1000.0, f_peak, sigma, rng, fs))
    return np.stack(out)


def clap_params(n=5) -> list[dict]:
    """Human-readable parameters of the first n variants (for manifests and reports)."""
    return [
        {"index": k, "duration_ms": d, "peak_hz": p, "sigma_oct": s}
        for k, (d, p, s) in enumerate(CLAP_VARIANTS[:n])
    ]
