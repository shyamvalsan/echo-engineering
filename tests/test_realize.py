"""Realization: gap, wedge, no-shadow, exact (unsnapped) ranges, and post echo = profile echo on a dilute profile."""

import numpy as np
import pytest
import torch

from echo.clap import clap_family
from echo.realize import radius_weights, realize, scale_profile
from echo.scene import MIN_GAP, Scene, bistatic_range, check_gaps, in_wedge
from echo.tier0 import post_echo, profile_echo

R0, DR, BAND = 3.06, 0.01, (900.0, 4000.0)


def _tone_profile(f=2500.0, dur=0.04, c=343.0):
    rho = R0 + DR * np.arange(int(round(c * dur / 2 / DR)) + 1)
    t = 2 * (rho - R0) / c
    return (1.0 + np.sin(2 * np.pi * f * t)) * rho / R0  # bias + tone, 2D spreading compensated


def _mismatch_db(a, b):
    return 10 * np.log10(np.sum((a - b) ** 2) / np.sum(a ** 2))


@pytest.fixture(scope="module")
def dilute():
    p = scale_profile(_tone_profile(), 0.004, R0, DR, a_ref=0.01)
    claps = clap_family(5)
    posts, st = realize(p, Scene(), seed=1, r0=R0, dr=DR, a_ref=0.01, band=BAND, claps=claps, refine_steps=100)
    return p, posts, st, claps


def test_geometry_rules(dilute):
    p, posts, st, _ = dilute
    assert st["n_posts"] > 100 and st["dropped"] == 0
    assert check_gaps(posts) >= MIN_GAP - 1e-12
    assert np.all(in_wedge(posts[:, :2], rho_min=R0 - DR))
    assert st["shadow_violations"] == 0
    # explicit no-shadow check: nearer posts within 0.5 m do not overlap angularly as seen from the source
    r = np.hypot(posts[:, 0], posts[:, 1])
    th = np.arctan2(posts[:, 1], posts[:, 0])
    for i in range(len(posts)):
        near = (r < r[i]) & (r >= r[i] - 0.5)
        need = posts[near, 2] / r[near] + posts[i, 2] / r[i]
        assert np.all(np.abs(th[near] - th[i]) >= need - 1e-12)
    assert set(np.unique(posts[:, 2])) <= {0.01, 0.02, 0.04, 0.08}


def test_ranges_are_continuous_not_snapped(dilute):
    _, posts, _, _ = dilute
    x = (bistatic_range(posts[:, :2]) - R0) / DR
    assert np.mean(np.abs(x - np.round(x)) < 1e-3) < 0.05


def test_post_echo_matches_profile_echo_dilute(dilute):
    """Tolerance: band-limited (900-4000 Hz) waveform mismatch energy <= -20 dB re the profile echo, mean level
    within 0.5 dB, over all 5 claps (2D)."""
    p, posts, st, claps = dilute
    sc = Scene(posts=posts)
    n = 1200
    ep = profile_echo(torch.as_tensor(p), claps, sc, n_out=n, a_ref=0.01, r0=R0, dr=DR, band=BAND).numpy()
    eq = post_echo(posts, claps, sc, n_out=n, band=BAND).numpy()
    mm = _mismatch_db(ep, eq)
    assert mm <= -20.0, mm
    lv = 20 * np.log10(np.max(np.abs(eq), 1) / np.max(np.abs(ep), 1))
    assert np.all(np.abs(lv) < 0.5)
    assert st["realized_mass"] == pytest.approx(st["requested_mass"], abs=1.0)


def test_radius_weights_and_crowding_uses_larger_posts():
    w = radius_weights(a_ref=0.01, band=BAND)
    assert w[0.01] == pytest.approx(1.0) and w[0.01] < w[0.02] < w[0.04] < w[0.08]
    p = np.full(200, 6.0)  # 6 reference posts per cm at 3 m: more than 1 cm posts can supply on a 2 m arc
    posts, st = realize(p, Scene(), seed=0, r0=R0, dr=DR, a_ref=0.01, band=BAND)
    assert st["by_radius"]["0.01"] < st["n_posts"]
    assert check_gaps(posts) >= MIN_GAP - 1e-12
