"""The stage driver end to end with a stand-in 'Tier 1' (Tier 0 per sensor), small settings: correction rounds are
saved, robustness runs, the run folder passes the contract checker and verification follows the validation file."""

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import torch

from contract_check import check_run_folder
from echo.scene import FS, Scene
from echo.tier0 import post_transfer
from stages.common import Tier1Hooks, run_stage, verify
from stages.s1_bird import CONFIG


def _fake_run(scene, f_max, t_end, listeners=None, c=343.0, record_field=False, field_dt=None, ppw=None,
              threads=None):
    n = int(np.ceil(t_end * FS))
    irs = []
    for L in listeners:
        sc = Scene(source=scene.source, listener=L, posts=scene.posts, c=c)
        H = post_transfer(scene.posts, sc, "2d", n_fft=4096, band=(300.0, f_max)).numpy()
        irs.append(np.fft.irfft(H, 4096)[:n])
    fld = None
    if record_field:
        fld = {"frames": np.random.default_rng(0).standard_normal((8, 20, 40)).astype(np.float16), "t0": 0.0,
               "dt_frame": field_dt, "extent": [0.0, 4.0, -1.0, 1.0]}
    return SimpleNamespace(ir=np.array(irs), listeners=np.asarray(listeners), solver="fdtd", device="cpu",
                           dx=0.009375, dt=7.8e-6, grid=(10, 10), f_lo=300.0, f_max=f_max, ppw=9.0, wall_s=0.0, c=c,
                           field=fld, extra={"empty_cached": True}, fs=FS)


def _fake_echoes(r, claps, listener=0):
    ir = r.ir[listener]
    cl = np.atleast_2d(claps)
    return np.array([np.convolve(c, ir)[: len(ir)] for c in cl])


def test_stage_driver_with_stand_in_tier1(tmp_path):
    cfg = replace(CONFIG, steps=10, refine_steps=0, n_claps=2, target_fill=0.002, correction_rounds=2, tag="drv",
                  threads=4, fill_candidates=(0.001, 0.002), status="intermediate")
    d, des, _ = run_stage(cfg, Tier1Hooks(run=_fake_run, echoes=_fake_echoes), command="pytest", verbose=False,
                          runs_root=tmp_path)
    check_run_folder(d)
    m = json.loads((d / "metrics.json").read_text())
    man = json.loads((d / "manifest.json").read_text())
    assert man["status"] == "intermediate" and man["solver"]["tier1"] == "fdtd" and man["field"]["file"] == "field.webm"
    assert m["verification"]["radii_used"] == [0.01] and man["solver"]["engine"]
    # verified iff the real validation file matches this engine and passed (true at the time of writing)
    assert m["verified"] == m["verification"]["validation_passed"]
    cases = [c["case"] for c in m["robustness"]]
    assert cases[:3] == ["nominal", "listener_side_1m", "listener_back_1m"] and "jitter" in cases
    assert {"c_331", "c_349", "clap_0", "clap_1"} <= set(cases)
    c331 = next(c for c in m["robustness"] if c["case"] == "c_331")
    assert abs(c331["pitch_shift_expected_pct"] - (331 / 343 - 1) * 100) < 1e-9
    h = json.loads((d / "history.json").read_text())
    ph = h["phases"][-1]
    assert ph["name"] == "tier1_correction" and len(ph["iters"]) >= 1 and len(ph["score"]) == len(ph["iters"])
    assert all((d / s["dir"] / "metrics.json").exists() for s in ph["saved"])
    assert isinstance(m["fragile"], bool) and m["fragile_reason"]
    assert m["tier1_correction"]["rounds"][0]["round"] == 0
    ds = m["tier1_correction"]["density_sweep"]
    assert [r["fill"] for r in ds["rows"]] == [0.001, 0.002]
    assert ds["picked_fill"] == min(ds["rows"], key=lambda r: r["loss_tier1"])["fill"]
    assert [p["name"] for p in h["phases"]] == ["Profile solve (Tier 0)", "density_sweep", "tier1_correction"]


def test_verify_requires_validated_radius_at_grid(tmp_path):
    v = tmp_path / "metrics.json"
    v.write_text(json.dumps({"passed": True, "solver": {"ppw": 9.0}, "checks": {"cylinder": {
        "g2": {"f_max": 2000, "per_radius": {"0.01": {"pass": False}, "0.02": {"pass": True}}}}}}))
    cfg = replace(CONFIG, f_max=2000.0)
    posts = np.array([[4.0, 0.0, 0.02], [5.0, 0.0, 0.01]])
    ok, info = verify(cfg, posts, 9.0, v)
    assert not ok and info["radii"] == [0.02] and info["radii_used"] == [0.01, 0.02]
    assert verify(cfg, posts[:1], 9.0, v)[0]
    assert not verify(cfg, posts[:1], 12.0, v)[0]  # other ppw: no entry, no config fallback
    assert verify(replace(cfg, validated_radii=(0.02,)), posts[:1], 12.0, v)[1]["source"].startswith("config")
    # engine version must match the validation's, and every check in the file must pass
    v.write_text(json.dumps({"passed": True, "solver": {"ppw": 9.0, "engine": "fd8-2"}, "checks": {"cylinder": {
        "g2": {"f_max": 2000, "per_radius": {"0.02": {"pass": True}}}, "pass": True},
        "dense_field": {"pass": False}}}))
    assert not verify(cfg, posts[:1], 9.0, v, engine="fd8-2")[0]
    v.write_text(json.dumps({"passed": True, "solver": {"ppw": 9.0, "engine": "fd8-2"}, "checks": {"cylinder": {
        "g2": {"f_max": 2000, "per_radius": {"0.02": {"pass": True}}}, "pass": True}}}))
    assert verify(cfg, posts[:1], 9.0, v, engine="fd8-2")[0]
    assert not verify(cfg, posts[:1], 9.0, v, engine="fd8-3")[0]
    v.write_text(json.dumps({"passed": False, "solver": {"ppw": 9.0}, "checks": {"cylinder": {
        "g2": {"f_max": 2000, "per_radius": {"0.02": {"pass": True}}}}}}))
    assert not verify(cfg, posts[:1], 9.0, v)[0]
