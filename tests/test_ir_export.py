"""Impulse-response export: ir_tier0.wav reproduces echo_tier0.wav, the deconvolution route's error bound, the
manifest `ir` block, and the backfill on a run folder without IRs."""

import json

import numpy as np
import soundfile as sf
import torch

from contract_check import check_run_folder
from echo import export
from echo.clap import band_limit, clap_family
from echo.metrics import score_stage
from echo.scene import FS, Scene
from echo.targets import bird_note
from echo.tier0 import post_echo

BAND = (898.4375, 4000.0)
POSTS = np.array([[3.4, 0.0, 0.01], [4.1, 0.3, 0.01], [5.2, -0.6, 0.02], [6.0, 0.9, 0.04], [7.5, 0.1, 0.01]])


def _run(tmp_path, with_ir=True, tier1=False):
    tgt, claps = bird_note(), clap_family(5)
    n = int(0.06 * FS)
    sc = Scene(posts=POSTS)
    e2 = post_echo(POSTS, torch.as_tensor(claps), sc, mode="2d", n_out=n, band=BAND).numpy()
    e3 = post_echo(POSTS, torch.as_tensor(claps), sc, mode="3d", n_out=n, band=BAND).numpy()
    e1 = None
    if tier1:  # stand-in "Tier 1": the same echo, slightly altered (a known IR)
        ir1 = export.tier0_ir(sc, BAND, n) * 0.8
        e1 = np.array([export.convolve_trunc(c, ir1, n) for c in claps])
    m = score_stage("s1_bird", tgt, 2 * 3.06 / 343, e2, e3, e1, depth_m=4.5, post_count=5, fill_fraction=0.001)
    ir = {"tier0": export.tier0_ir(sc, BAND, n), "tier1": None, "band": BAND, "source_t1": None} if with_ir else None
    return export.write_run("s1_bird", "irt", "ir test", scene=sc, profile={"r0_m": 3.06, "dr_m": 0.01,
                            "reflectivity": [1.0], "units": "x"}, target_audio=tgt.audio, t_echo0=2 * 3.06 / 343,
                            claps=claps, echo_t0=e2, echo_t1=e1, metrics=m, history={"phases": []}, seed=0,
                            command="pytest", duration_s=0.06, runs_root=tmp_path, ir=ir, solver=None if not tier1 else
                            {"tier1": "fdtd", "device": "cpu", "dx": 0.01, "dt": 1e-5, "grid": [10, 10], "f_lo": 300.0,
                             "f_max": 4000.0, "ppw": 9, "wall_s": 1.0},
                            extra={"design": {"loss_band_hz": list(BAND), "config": {"n_claps": 5}}})


def _true(d, name, key):
    man = json.loads((d / "manifest.json").read_text())
    x, _ = sf.read(d / name, dtype="float64")
    return x * 10 ** (-man["audio"]["echo_gain_db"][key] / 20)


def test_ir_tier0_reproduces_echo(tmp_path):
    d = _run(tmp_path)
    check_run_folder(d)
    ir, fs = sf.read(d / "ir_tier0.wav", dtype="float64")
    info = sf.info(d / "ir_tier0.wav")
    assert fs == FS and info.subtype == "FLOAT" and info.channels == 1
    e0 = _true(d, "echo_tier0.wav", "tier0")
    assert len(ir) == len(e0)
    rec = export.convolve_trunc(clap_family(5)[0], ir, len(e0))
    err = 10 * np.log10(np.sum((rec - e0) ** 2) / np.sum(e0 ** 2))
    assert err < -80.0, err  # float32 storage limits it (~-125 dB measured on real runs)
    # first non-negligible sample sits at the first post's echo delay (2 rho / c), not at t = 0
    rho = (np.linalg.norm(POSTS[0, :2]) + np.linalg.norm(POSTS[0, :2] - [0, 0.3])) / 2
    first = np.nonzero(np.abs(ir) > 1e-2 * np.abs(ir).max())[0][0]
    assert abs(first / FS - 2 * rho / 343.0) < 1.5e-3
    assert 1e-5 < np.abs(ir).max() < 0.1  # model units, not normalized


def test_manifest_ir_block_shape(tmp_path):
    d = _run(tmp_path)
    b = json.loads((d / "manifest.json").read_text())["ir"]
    assert b["tier0"] == "ir_tier0.wav" and b["tier1"] is None and b["fs"] == 16000 and b["t0_s"] == 0.0
    assert b["band_hz"] == list(BAND) and b["units"] == "pressure re direct sound at listener"
    assert b["source"] == {"tier0": "computed from scene.json", "tier1": None}
    assert set(b["peak"]) == {"tier0", "tier1"} and b["peak"]["tier1"] is None and b["peak"]["tier0"] > 0
    assert b["check"]["tier0_reconstruction_error_db"] < -80


def test_deconvolution_error_bound_synthetic():
    """Sparse random IR (5 taps, 18-60 ms), echo = band-limited clap_0 (*) ir. Hand bound: inside the clap band the
    Tikhonov factor |C|^2 / (|C|^2 + 1e-3 max|C|^2) differs from 1 by < 1e-3 / 10^(-20/10) = 0.1 (-20 dB) at the band's
    weakest bin (clap -20 dB re its peak) and far less near the peak, so the echo reconstruction is better than -20 dB;
    the energy-weighted error is far smaller (measured about -40 dB)."""
    rng = np.random.default_rng(1)
    n = 1200
    ir = np.zeros(n)
    ir[rng.integers(300, 960, 5)] = rng.standard_normal(5) * 1e-3
    ir = band_limit(ir, *BAND)
    clap = clap_family(5)[0]
    echo = export.convolve_trunc(clap, ir, n)
    ir_d, err = export.deconvolve_ir(echo, clap, BAND)
    assert err < -30.0, err
    assert err == export.ir_error_db(ir_d, clap, echo)
    # the recovered IR filtered by the clap's own spectrum equals the true one: error in the IR itself, clap-weighted
    w = 10 * np.log10(np.sum((export.convolve_trunc(clap, ir_d - ir, n)) ** 2) / np.sum(echo ** 2))
    assert w < -30.0


def test_backfill_routes(tmp_path):
    from stages.backfill_ir import backfill

    d = _run(tmp_path, with_ir=False, tier1=True)
    man = json.loads((d / "manifest.json").read_text())
    assert "ir" not in man
    row = backfill(d)
    b = json.loads((d / "manifest.json").read_text())["ir"]
    assert b["source"]["tier0"] == export.IR_SRC_T0 and b["source"]["tier1"] == export.IR_SRC_T1_DECONV
    assert b["tier1"] == "ir_tier1.wav" and (d / "ir_tier1.wav").exists()
    assert row["tier0_reconstruction_error_db"] < -80 and row["tier1_reconstruction_error_db"] < -30
    # only the ir key changed
    man2 = json.loads((d / "manifest.json").read_text())
    man2.pop("ir")
    assert man2 == man
    check_run_folder(d)


def test_gain_to_true_level_reproduces_as_heard_level(tmp_path):
    """(clap_0 (*) ir) * gain_to_true_level has the echo level heard in as_heard.wav (independent read of the file:
    echo peak after the direct clap over the direct peak), within 0.5 dB, for both tiers; and after a backfill."""
    from stages.backfill_ir import backfill

    for i, with_ir in enumerate((True, False)):
        d = _run(tmp_path / str(i), with_ir=with_ir, tier1=True)
        if not with_ir:
            backfill(d)
        b = json.loads((d / "manifest.json").read_text())["ir"]
        x, _ = sf.read(d / "as_heard.wav", dtype="float64")
        i_d = int(round(0.3 / 343 * FS))
        heard = 20 * np.log10(np.max(np.abs(x[i_d + 200:])) / np.max(np.abs(x[: i_d + 128])))
        clap0 = clap_family(5)[0]
        for tier in ("tier0", "tier1"):
            if b[tier] is None:
                continue
            ir, _ = sf.read(d / b[tier], dtype="float64")
            lvl = 20 * np.log10(np.max(np.abs(export.convolve_trunc(clap0, ir) * b["gain_to_true_level"][tier])))
            assert abs(lvl - heard) < 0.5, (tier, lvl, heard)
            assert abs(b["level_db"]["as_stored"][tier] + 20 * np.log10(b["gain_to_true_level"][tier])
                       - b["level_db"]["true_3d"]) < 1e-6
        assert b["model_level"] == "2d"
