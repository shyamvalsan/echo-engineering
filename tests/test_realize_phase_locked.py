"""Phase-locked ("comb") realization: rings on the carrier phase, counts follow the envelope, gap/wedge constraints,
determinism, exact fractional ring amplitudes, and the K-quantile mode suppressing the comb's 2nd harmonic."""

import math

import numpy as np
import pytest

from echo.realize import (analytic_profile, phase_locked_ranges, quantile_phases, realize, ring_detuning)
from echo.scene import MIN_GAP, Scene, bistatic_range, check_gaps, in_wedge

R0, DR, BAND, C = 3.06, 0.01, (900.0, 4000.0), 343.0


def _chirp_profile(f0=3500.0, f1=2000.0, dur=0.06, ramp=True):
    """bias + A(rho) cos(phi(rho)) with a known phase: phi(rho) = 2 pi * integral f(t) dt at t = 2 (rho - r0)/c."""
    n = int(round(C * dur / 2 / DR)) + 1
    rho = R0 + DR * np.arange(n)
    t = 2 * (rho - R0) / C
    k = math.log(f1 / f0) / dur
    phi = 2 * np.pi * f0 * (np.exp(k * t) - 1) / k
    A = (0.5 + rho / rho[-1]) if ramp else np.ones(n)
    win = np.clip(np.minimum(t, dur - t) / 0.005, 0, 1)  # 5 ms fades (no edge steps)
    return 1.5 * A * win + A * win * np.cos(phi), rho, phi, A * win


def test_quantile_phases_hand_values():
    # K = 1: the peak; K = 2: CDF(x) = (x + pi + sin x)/(2 pi) = 3/4 -> x + sin x = pi/2 -> x = 0.8317 (hand Newton)
    assert quantile_phases(1) == pytest.approx([0.0], abs=1e-12)
    assert quantile_phases(2) == pytest.approx([-0.83171, 0.83171], abs=1e-4)
    q3 = quantile_phases(3)
    assert q3[1] == pytest.approx(0.0, abs=1e-9) and q3[2] == pytest.approx(-q3[0])


def test_ring_detuning_exact_amplitude():
    for a in (0.3, 0.9, 1.0, 1.4, 2.0, 3.7, 11.2):
        n, d = ring_detuning(a)
        assert n - 2 * (d > 0) + 2 * math.cos(d) * (d > 0) == pytest.approx(a, abs=1e-12)
        assert d <= math.pi / 2 and (a < 1 or d <= math.pi / 3 + 1e-12)


def test_rings_on_carrier_phase_and_counts_follow_envelope():
    p, rho, phi, env = _chirp_profile()
    rhos, rings = phase_locked_ranges(p, 600, BAND, r0=R0, dr=DR, c=C)
    assert abs(len(rhos) - 600) <= 12
    # every ring sits where the true phase is 2 pi j: within 0.03 rad away from the 5 ms fades (band-pass and
    # interpolation error only), within 0.15 rad inside them (the envelope's own spectrum widens the carrier)
    rr = np.array([r[0] for r in rings])
    err = np.abs((np.interp(rr, rho, phi) + np.pi) % (2 * np.pi) - np.pi)
    core = (rr > rho[0] + C * 0.005 / 2) & (rr < rho[-1] - C * 0.005 / 2)
    assert np.max(err[core]) < 0.03 and np.max(err) < 0.15
    # ring amplitude ~ envelope x local carrier period in rho (2 pi / phi'): correlation with the truth
    lam = 2 * np.pi / np.interp(rr, rho, np.gradient(phi, rho))
    amp = np.array([r[2] for r in rings])
    truth = np.interp(rr, rho, env) * lam
    mid = slice(len(amp) // 6, -len(amp) // 6)  # away from the fades
    assert np.corrcoef(amp[mid], truth[mid])[0, 1] > 0.99


def test_posts_respect_gap_wedge_and_are_deterministic():
    p, *_ = _chirp_profile()
    p = p * (800 / p.sum())
    sc = Scene()
    posts, st = realize(p, sc, seed=3, r0=R0, dr=DR, a_ref=0.01, band=BAND, mode="phase_locked")
    posts2, _ = realize(p, sc, seed=3, r0=R0, dr=DR, a_ref=0.01, band=BAND, mode="phase_locked")
    assert np.array_equal(posts, posts2)
    assert st["mode"] == "phase_locked" and st["dropped"] == 0
    assert abs(st["n_posts"] - 800) <= 12
    assert check_gaps(posts) >= MIN_GAP - 1e-9
    assert np.all(in_wedge(posts[:, :2], sc.half_angle_deg, rho_min=R0 - DR, source=sc.source, listener=sc.listener))
    assert np.allclose(posts[:, 2], 0.01)
    # posts sit exactly on their requested equal-delay ellipses (no sampling noise)
    want = np.sort(phase_locked_ranges(p, 800, BAND, r0=R0, dr=DR, c=C)[0])
    assert np.allclose(np.sort(bistatic_range(posts[:, :2], sc.source, sc.listener)), want, atol=1e-9)


def _comb_harmonics(rhos, rho_mid, kappa0, half=0.3):
    """|sum exp(-i 2 pi n kappa rho)| for n = 1, 2 over posts within rho_mid +- half (Hann-weighted)."""
    r = rhos[np.abs(rhos - rho_mid) < half]
    w = 0.5 + 0.5 * np.cos(np.pi * (r - rho_mid) / half)
    return [abs(np.sum(w * np.exp(-2j * np.pi * n * kappa0 * r))) for n in (1, 2)]


def test_k_quantile_mode_reduces_second_harmonic():
    f = 2500.0
    n = int(round(C * 0.06 / 2 / DR)) + 1
    rho = R0 + DR * np.arange(n)
    p = 2.0 + np.cos(2 * np.pi * (2 * f / C) * (rho - R0))  # constant tone: kappa0 = 2 f / c cycles per metre
    k0 = 2 * f / C
    h = {}
    for K in (1, 2, 3):
        rhos, _ = phase_locked_ranges(p, 1200, BAND, r0=R0, dr=DR, c=C, posts_per_period=K)
        h1, h2 = _comb_harmonics(rhos, rho[n // 2], k0)
        h[K] = h2 / h1
    assert h[1] > 0.9  # pure comb: 2nd harmonic as strong as the fundamental
    assert h[2] < 0.25 * h[1] and h[3] < 0.25 * h[1]


def test_analytic_profile_envelope_of_a_tone():
    n = 1200
    rho = R0 + DR * np.arange(n)
    p = 1.0 + 0.5 * np.cos(2 * np.pi * 14.0 * (rho - R0))  # kappa 14 /m = 2401 Hz
    z = analytic_profile(p, BAND, DR, C)
    assert np.median(np.abs(z[200:-200])) == pytest.approx(0.5, rel=0.02)


def test_max_half_width_clips_to_a_strip_and_keeps_ellipse_ranges():
    """max_half_width_m: every post has |y| + a <= half-width (inside the wedge too) and still sits on its ring's
    equal-delay ellipse (bistatic range unchanged by the clip: same ring ranges as without it)."""
    import numpy as np

    from echo.realize import realize
    from echo.scene import Scene, bistatic_range

    rho = 3.0 + 0.01 * np.arange(2000)
    prof = 1.0 + np.sin(2 * np.pi * rho / 0.13)
    sc = Scene(half_angle_deg=20.0)
    kw = dict(r0=3.0, dr=0.01, a_ref=0.01, radii=(0.01,), mode="phase_locked", n_posts=400)
    p_w, _ = realize(prof, sc, 0, **kw)
    p_s, st = realize(prof, sc, 0, max_half_width_m=0.5, **kw)
    assert len(p_s) >= 0.95 * len(p_w)
    assert np.all(np.abs(p_s[:, 1]) + p_s[:, 2] <= 0.5 + 1e-9)
    assert np.abs(p_w[:, 1]).max() > 0.5  # without the clip the wedge (+-20 deg, ~7 m wide at 20 m) is used
    th = np.degrees(np.arctan2(p_s[:, 1], p_s[:, 0]))
    assert np.all(np.abs(th) <= 20.0)
    r_w = np.sort(bistatic_range(p_w[:, :2], sc.source, sc.listener))
    r_s = np.sort(bistatic_range(p_s[:, :2], sc.source, sc.listener))
    n = min(len(r_w), len(r_s))
    if len(r_w) == len(r_s):
        assert np.allclose(r_w[:n], r_s[:n], atol=1e-6)
