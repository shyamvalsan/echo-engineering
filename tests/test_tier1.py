"""Tier 1 solver: fast versions of validation checks 1 and 3, plus the absorption filter and the field video."""

import json
import os

import numpy as np
import pytest
from scipy.special import hankel2

from echo import tier1 as t1
from echo.clap import clap_family
from echo.scene import C0, FS, Scene
from stages.validate import analytic_cylinder_ir_spectrum, band_errors_db

# Slow tests (tens of seconds each) run only with RUN_SLOW=1; the default suite keeps checks 1 and 3 (fast versions).
slow = pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="slow Tier 1 test; set RUN_SLOW=1")


@slow
def test_free_field_matches_2d_greens_function():
    """Point mass source on the grid vs the exact 2D Green's function.

    Hand calculation: for dp/dt = -K div u + K q delta(x), the field is P = rho w Q H0^(2)(k r) / 4 (DSP
    convention). So |P(r1)/P(r2)| = |H0(k r1)| / |H0(k r2)|, about sqrt(r2/r1) for kr >> 1. Check the ratio
    between r = 0.3 m and r = 1.0 m at 1-3 kHz to 0.2 dB, and the arrival delay difference (0.7 m / c) to 1 %.
    """
    sc = Scene()
    L = np.array([[0.0, 0.3], [1.0, 0.0]])
    pl = t1.plan(sc, 3000.0, 0.01, listeners=L, ppw=6)
    fs_sim = pl["m"] * FS
    sig = t1.source_pulse(fs_sim, pl["n_steps"], 300.0, 3000.0, pl["t_src0"])
    rec, _, _ = t1.simulate(pl["grid"], C0, pl["dt"], pl["n_steps"], sc.source, sig, L)
    f = np.linspace(1000, 3000, 21)
    X = t1._dft_at(rec, fs_sim, t1.sim_frequency(f, C0, pl["dt"], pl["dx"]))
    k = 2 * np.pi * f / C0
    ratio_sim = X[0] / X[1]
    ratio_ana = hankel2(0, k * 0.3) / hankel2(0, k * 1.0)
    assert np.max(np.abs(20 * np.log10(np.abs(ratio_sim / ratio_ana)))) < 0.2
    dphi = np.unwrap(np.angle(ratio_sim / ratio_ana))
    assert np.max(np.abs(dphi - dphi.mean())) < 0.05  # rad: no residual delay between the two paths


def _cyl_err(radius, f_max, offset=(0.0, 0.0)):
    post = [3.0 + offset[0], offset[1], radius]
    r = t1.run_tier1(Scene(posts=np.array([post])), f_max, 2 * 3.0 / C0 + 0.02, cache=False)
    _, err = band_errors_db(r.ir[0], lambda f: analytic_cylinder_ir_spectrum(f, post), f_max)
    return max(map(abs, err)), r


def test_cylinder_2cm_within_1db_at_2khz():
    """Check 1 (fast): 2 cm post at 3 m, f_max 2 kHz (dx 1.67 cm, r/dx 1.2, calibrated). Analytic: exact series."""
    assert _cyl_err(0.02, 2000.0)[0] < 1.0


def test_cylinder_1cm_within_1db_at_4khz():
    """Check 1 (fast): 1 cm post at 3 m at the stage-1 grid (f_max 4 kHz, dx 8.6 mm, r/dx 1.17, calibrated)."""
    assert _cyl_err(0.01, 4000.0, (0.002, 0.004))[0] < 1.0


@slow
@pytest.mark.xfail(strict=True, reason="1 cm at f_max 2 kHz is r/dx 0.6: below the validated sub-cell range")
def test_cylinder_1cm_at_2khz_known_failure():
    err, r = _cyl_err(0.01, 2000.0)
    assert 0.01 in r.extra["unvalidated_radii"]
    assert err < 1.0


def test_empty_scene_reflections_below_60db_fast():
    """Check 3 (fast): small empty box, listener record vs the analytic free field after the direct clap."""
    sc = Scene()
    pl = t1.plan(sc, 2000.0, 0.03)
    fs_sim = pl["m"] * FS
    sig = t1.source_pulse(fs_sim, pl["n_steps"], 300.0, 2000.0, pl["t_src0"])
    rec, _, _ = t1.simulate(pl["grid"], C0, pl["dt"], pl["n_steps"], sc.source, sig, [[0.0, 0.3]])
    n = rec.shape[1]
    nfft = 2 * int(np.ceil(n / pl["m"]))
    f = np.fft.rfftfreq(nfft, 1 / FS)
    band = t1.band_mask(f, 300.0, 2000.0)
    use = band > 0
    fsim = t1.sim_frequency(f[use], C0, pl["dt"], pl["dx"])
    Pe = t1._dft_at(rec, fs_sim, fsim)[0]
    S = t1._dft_at(sig[None], fs_sim, fsim)[0] * np.exp(-2j * np.pi * fsim * pl["dt"])
    model = S * f[use] * hankel2(0, 2 * np.pi * f[use] / C0 * 0.3)
    g = np.vdot(model, Pe) / np.vdot(model, model)
    R = np.zeros(len(f), complex)
    R[use] = (Pe / (g * model) - 1) * band[use]
    claps = clap_family(2)
    res = np.fft.irfft(np.fft.rfft(claps, nfft, axis=1) * R[None], nfft, axis=1)
    t = np.arange(nfft) / FS
    after = (t > 0.3 / C0 + 0.008) & (t < 0.03)
    assert 20 * np.log10(np.abs(res[:, after]).max()) < -60.0


@slow
def test_echo_delay_and_absorption():
    """An echo arrives at 2 rho / c; absorption leaves early samples nearly intact and attenuates late ones."""
    post = [4.0, 0.0, 0.02]
    r = t1.run_tier1(Scene(posts=np.array([post])), 2000.0, 0.035, cache=False)
    rho = 0.5 * (4.0 + np.hypot(4.0, 0.3))
    E = t1.echoes(r, clap_family(1), absorption=False)[0]
    env = np.abs(E)
    t_peak = np.argmax(env) / FS
    assert 2 * rho / C0 < t_peak < 2 * rho / C0 + 0.004  # clap onset at the echo delay, peak within the burst
    ir = np.zeros(int(0.5 * FS))
    ir[100] = ir[int(0.45 * FS)] = 1.0
    a = t1.absorb(ir, d_direct=0.3)[0]
    assert abs(a[100] - 1.0) < 0.02
    assert a[int(0.45 * FS)] < 0.97  # 154 m of path: a few dB at high frequencies lowers the impulse peak


def test_field_video(tmp_path):
    from echo.field_video import render_field_video

    T, Hh, W = 12, 40, 64
    frames = np.random.default_rng(0).standard_normal((T, Hh, W)).astype(np.float16)
    blk = render_field_video(frames, [0.0, 6.4, -2.0, 2.0], tmp_path / "field.webm", t0=0.001, dt_frame=0.0005)
    assert (tmp_path / "field.webm").stat().st_size > 0
    assert blk["n_frames"] == T and blk["file"] == "field.webm" and blk["sim_seconds_per_frame"] == 0.0005
    assert blk["extent_m"][0] == 0.0 and blk["extent_m"][3] == 2.0
    json.dumps(blk)
