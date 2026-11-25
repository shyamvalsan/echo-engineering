"""Tier 1 correction loop arithmetic (spec, inverse design step 3) on a synthetic 'Tier 1'."""

import numpy as np
import torch

from echo.clap import clap_family
from echo.inverse import (R0_PROFILE, apply_window_gains, clap_centroid_s, correction_loop, initial_profile,
                          reference_echo, stage_score, window_gains)
from echo.scene import FS, Scene
from echo.targets import bird_note
from echo.tier0 import profile_echo

BAND = (898.4375, 4000.0)


def _setup():
    tgt = bird_note()
    claps = clap_family(5)
    c = 343.0
    n_rho = int(round(c * 0.08 / 2 / 0.01)) + 1
    p_true = initial_profile(tgt.audio, n_rho)
    n_out = int(0.12 * FS)
    t0 = 2 * R0_PROFILE / c
    t_stop = t0 + 0.08 + claps.shape[1] / FS
    return tgt, claps, c, p_true, n_out, t0, t_stop


def _echo(p, claps, n_out):
    return profile_echo(torch.as_tensor(p), torch.as_tensor(claps), Scene(), mode="2d", n_out=n_out, a_ref=0.01,
                        r0=R0_PROFILE, band=BAND).numpy()


def _window_db(e, ref, t0, t_stop):
    _, _, info = window_gains(e, ref, t0, t_stop, clip=(1e-6, 1e6))
    ok = ~info["weak"]
    return 10 * np.log10(info["E_echo"][ok] / info["E_ref"][ok])


def test_window_gains_hand_case():
    # Two 10 ms windows; echo has 4x the reference energy in window 1 relative to window 0 -> after normalizing the
    # reference to the echo's total energy, gains are sqrt(Er/Ee): window 0: Ee=1, window 1: Ee=4, Er=1 each,
    # scaled to total 5 -> Er=2.5 each -> g = sqrt(2.5/1)=1.581, sqrt(2.5/4)=0.791.
    n = 320
    e = np.zeros((1, n))
    r = np.zeros((1, n))
    e[0, 10], e[0, 170] = 1.0, 2.0
    r[0, 10], r[0, 170] = 1.0, 1.0
    tc, g, _ = window_gains(e, r, 0.0, n / FS, win_s=0.010)
    assert np.allclose(tc, [0.005, 0.015])
    assert np.allclose(g, [np.sqrt(2.5), np.sqrt(2.5 / 4)], atol=1e-9)


def test_apply_window_gains_preserves_mass_and_maps_time():
    p = np.ones(100)
    q = apply_window_gains(p, 3.0, 0.01, [2 * 3.0 / 343.0, 2 * 3.99 / 343.0], [1.0, 3.0], c=343.0)
    assert abs(q.sum() - p.sum()) < 1e-9
    assert q[-1] / q[0] > 2.9  # bin at rho 3.99 gets gain 3, bin at rho 3.0 gain 1


def test_synthetic_tier1_gain_error_corrected_in_three_rounds():
    tgt, claps, c, p_true, n_out, t0, t_stop = _setup()
    ref = _echo(p_true, claps, n_out)  # a perfect model: the reference is the true profile's echo
    rho = R0_PROFILE + 0.01 * np.arange(len(p_true))
    tb = 2 * rho / c
    # known per-window gain error of the synthetic "Tier 1" (piecewise constant in 10 ms windows, up to +-4 dB)
    err_db = np.array([3.0, -4.0, 2.0, -1.0, 4.0, -3.0, 1.0, -2.0, 0.0])
    w = np.clip(((tb - t0) / 0.010).astype(int), 0, len(err_db) - 1)
    err = 10 ** (err_db[w] / 20)

    def run_t1(p):
        return None, _echo(p * err, claps, n_out)

    def evaluate(p, e1):
        d = _window_db(e1, ref, t0, t_stop)
        loss = float(np.sqrt(np.mean(d ** 2)))
        return {"metrics": []}, loss, -loss

    before = _window_db(run_t1(p_true)[1], ref, t0, t_stop)
    rounds, best = correction_loop(p_true, lambda p: p, run_t1, evaluate, ref, t0, t_stop, r0=R0_PROFILE, dr=0.01,
                                   c=c, t_offset=clap_centroid_s(claps), rounds=4, verbose=False)
    assert np.max(np.abs(before)) > 2.5
    rms = [r.loss for r in rounds]
    k3 = min(3, len(rounds) - 1)
    assert min(rms[1:k3 + 1]) < 0.35 * rms[0], rms  # corrected within 3 rounds
    assert min(rms[1:k3 + 1]) < 0.75, rms  # per-window level error RMS under 0.75 dB
    assert best >= 1


def test_stage_score_margin():
    m = {"metrics": [
        {"id": "pitch_err_pct", "value": 2.7, "threshold": 3.0, "comparator": "<=", "gating": True},
        {"id": "spec_corr", "value": 0.9, "threshold": 0.8, "comparator": ">=", "gating": True},
        {"id": "spec_corr", "value": 0.1, "threshold": 0.8, "comparator": ">=", "gating": False}]}
    assert abs(stage_score(m) - 0.1) < 1e-12  # min(0.3/3, 0.1/0.8)


def test_reference_echo_placed_at_t_echo0():
    tgt = bird_note()
    claps = clap_family(5)
    r = reference_echo(tgt.audio, claps, 0.02, 2000, BAND)
    assert r.shape == (5, 2000)
    assert np.max(np.abs(r[:, :300])) < 1e-3 * np.max(np.abs(r))
