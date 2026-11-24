"""Profile solve: recovers a known sinusoidal profile's pitch from its echo."""

import numpy as np
import torch

from echo.clap import band_limit, clap_family
from echo.inverse import R0_PROFILE, clap_band, initial_profile, solve_profile
from echo.metrics import pitch_track
from echo.scene import FS, Scene
from echo.tier0 import profile_echo

F_TONE, DUR = 2500.0, 0.04


def test_clap_band_inside_design_band():
    lo, hi = clap_band(clap_family(5))
    assert 500 <= lo < 1200 and hi == 4000.0


def test_initial_profile_positive_and_mean_one():
    p = initial_profile(np.sin(np.linspace(0, 60, 640)), 700)
    assert p.min() > 0 and abs(p.mean() - 1) < 1e-12


def test_solve_recovers_sinusoidal_profile_pitch():
    c = 343.0
    n_rho = int(round(c * DUR / 2 / 0.01)) + 1
    rho = R0_PROFILE + 0.01 * np.arange(n_rho)
    known = (1 + np.sin(2 * np.pi * F_TONE * 2 * (rho - R0_PROFILE) / c)) * rho / R0_PROFILE
    claps = clap_family(5)
    band = clap_band(claps)
    n0 = int(round(2 * R0_PROFILE / c * FS))
    e = profile_echo(torch.as_tensor(known), claps[:1], Scene(), n_out=n0 + 800, a_ref=0.01, band=band).numpy()[0]
    target = e[n0:n0 + int(DUR * FS)]
    flat = 1.0 + 0.2 * np.random.default_rng(0).standard_normal(n_rho)  # uninformative start (no tone)
    prof, res = solve_profile(target, claps, Scene(), duration_s=DUR, a_ref=0.01, steps=120, lr=0.05, init=np.clip(flat, 0.05, None))
    assert res.info["best_loss"] < 0.6 * res.info["init_loss"]
    # the solved profile carries the known spatial frequency: k = 2 f / c cycles per metre
    x = prof - np.convolve(prof, np.ones(15) / 15, "same")
    k = np.fft.rfftfreq(4096, 0.01)
    k_peak = k[np.argmax(np.abs(np.fft.rfft(x * np.hanning(len(x)), 4096)))]
    assert abs(k_peak / (2 * F_TONE / c) - 1) < 0.02
    # and its echo has the tone's pitch
    ee = profile_echo(torch.as_tensor(prof), claps, Scene(), n_out=n0 + 800, a_ref=0.01, band=band).numpy()
    # reference: what the same judge reads on a clean tone of the known pitch (pyin reads 2500 Hz as ~2528 Hz)
    _, f_ref, _ = pitch_track(np.sin(2 * np.pi * F_TONE * np.arange(480) / FS), f_range=(2000, 3000))
    for row in ee:
        _, f0, vp = pitch_track(row[n0 + 80:n0 + int(DUR * FS) - 80], f_range=(2000, 3000))
        assert abs(np.median(f0) / np.median(f_ref) - 1) < 0.006
