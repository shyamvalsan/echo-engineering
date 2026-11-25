"""Stretch pre-compensation: fit_stretch recovers a known range-proportional warp from a synthetic "Tier 1" (Tier 0
with a known stretch), and scaling the ranges by (1 + eps) removes it in one round."""

import numpy as np
import pytest
import torch

from echo.clap import clap_family
from echo.inverse import compose_stretch, fit_stretch
from echo.realize import realize
from echo.scene import FS, Scene
from echo.tier0 import post_echo

R0, DR, BAND = 3.06, 0.01, (900.0, 4000.0)


def _design(scale):
    n = int(round(343.0 * 0.04 / 2 / DR)) + 1
    rho = R0 + DR * np.arange(n)
    p = (2.0 + np.cos(2 * np.pi * (2 * 2800.0 / 343.0) * (rho - R0))) * rho / R0
    p = p * (300 / p.sum())
    posts, _ = realize(p, Scene(), seed=0, r0=R0, dr=DR, a_ref=0.01, band=BAND, mode="phase_locked",
                       range_scale=scale)
    return posts


def _echo(posts, claps, n_out, c=343.0):
    return post_echo(posts, torch.as_tensor(claps), Scene(posts=posts, c=c), mode="2d", n_out=n_out,
                     band=BAND).numpy()


def test_fit_stretch_recovers_known_eps_and_one_round_removes_it():
    claps = clap_family(2)
    n_out = int(0.08 * FS)
    n0, n1 = int(2 * R0 / 343 * FS), int(2 * R0 / 343 * FS) + int(0.04 * FS) + 128
    eps_true = -0.0025
    # synthetic Tier 1 = Tier 0 in a medium slower by |eps|: c (1 + eps) stretches every delay by 1 / (1 + eps)
    posts = _design(1.0)
    e0 = _echo(posts, claps, n_out)
    e1 = _echo(posts, claps, n_out, c=343.0 * (1 + eps_true))
    fit = fit_stretch(e1, e0, n0, n1)
    assert fit["eps"] == pytest.approx(eps_true, rel=0.10)
    assert fit["corr"] > 0.97
    # one round: ranges scaled by (1 + eps); the slow medium now returns (nearly) the uncompensated design's echo
    eps = compose_stretch(0.0, fit["eps"])
    p2 = _design(1.0 + eps)
    e1b = _echo(p2, claps, n_out, c=343.0 * (1 + eps_true))
    fit2 = fit_stretch(e1b, e0, n0, n1)
    assert abs(fit2["eps"]) < 0.1 * abs(eps_true) + 1e-4


def test_compose_stretch():
    assert compose_stretch(-0.002, -0.001) == pytest.approx((1 - 0.002) * (1 - 0.001) - 1)
