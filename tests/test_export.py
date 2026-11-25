"""Run-folder writer: contract fields (as the viewer reads them), no NaN/Infinity, index rebuild."""

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from contract_check import check_index, check_run_folder
from echo.clap import clap_family
from echo.export import EXPORT_DIRS_SKIPPED, clean_json, update_index, write_json, write_run
from echo.metrics import score_stage
from echo.scene import FS, Scene
from echo.targets import bird_note


def _fake_run(tmp_path, tag="t"):
    tgt = bird_note()
    claps = clap_family(5)
    n = int(0.12 * FS)
    t0 = 2 * 3.06 / 343.0
    i0 = int(round(t0 * FS))
    e2 = np.zeros((5, n))
    e2[:, i0:i0 + len(tgt.audio)] = 0.05 * tgt.audio
    e3 = 0.01 * e2
    metrics = score_stage("s1_bird", tgt, t0, e2, e3, depth_m=13.7, post_count=3, fill_fraction=0.01)
    metrics["headline"]["tier_gap_db"] = float("nan")  # must come out as null
    posts = np.array([[3.5, 0.0, 0.01], [4.0, 0.2, 0.02], [5.0, -0.5, 0.01]])
    hist = {"phases": [{"name": "Profile solve", "x_label": "Adam step", "iters": [0, 1], "loss": [1.0, float("inf")]}]}
    iters = [("solve_000", Scene(posts=posts), {"r0_m": 3.06, "dr_m": 0.01, "reflectivity": [0.0, 1.0], "units": "x"},
              e2[0], metrics, 0)]
    return write_run("s1_bird", tag, "test run", scene=Scene(posts=posts),
                     profile={"r0_m": 3.06, "dr_m": 0.01, "reflectivity": [0.0, 1.0, 2.0], "units": "x"},
                     target_audio=tgt.audio, t_echo0=t0, claps=claps, echo_t0=e2, metrics=metrics, history=hist,
                     seed=0, command="pytest", duration_s=0.12, runs_root=tmp_path, iters=iters)


def test_write_run_contract_and_no_nan(tmp_path):
    d = _fake_run(tmp_path)
    check_run_folder(d)
    m = json.loads((d / "metrics.json").read_text())
    assert m["headline"]["tier_gap_db"] is None
    assert m["passed"] is False and m["verified"] is False  # Tier 0 never passes
    man = json.loads((d / "manifest.json").read_text())
    assert man["status"] == "tier0_only" and man["solver"]["tier1"] == "none"
    h = json.loads((d / "history.json").read_text())
    assert h["phases"][0]["loss"][1] is None and h["phases"][0]["saved"][0]["dir"] == "iters/solve_000"
    check_index(tmp_path)


def test_as_heard_levels(tmp_path):
    d = _fake_run(tmp_path)
    x, fs = sf.read(d / "as_heard.wav")
    i_d = int(round(0.3 / 343 * FS))
    direct = np.max(np.abs(x[: i_d + 128]))
    assert abs(20 * np.log10(direct) - (-1.0)) < 0.01  # direct clap peak at -1 dBFS
    lvl = json.loads((d / "manifest.json").read_text())["audio"]["as_heard_echo_level_db"]
    echo = np.max(np.abs(x[i_d + 200:]))
    assert abs(20 * np.log10(echo / direct) - lvl) < 0.01
    for w in ("target.wav", "echo_tier0.wav"):
        y, _ = sf.read(d / w)
        assert abs(20 * np.log10(np.max(np.abs(y))) + 1.0) < 0.01


def test_update_index_skips_validation_and_underscore(tmp_path):
    _fake_run(tmp_path, "a")
    for sk in EXPORT_DIRS_SKIPPED:
        (tmp_path / sk / "x").mkdir(parents=True)
        write_json(tmp_path / sk / "x" / "manifest.json", {"stage": sk, "created": "9999"})
    (tmp_path / "s1_bird" / "_scratch").mkdir()
    write_json(tmp_path / "s1_bird" / "_scratch" / "manifest.json", {"stage": "s1_bird", "created": "9999"})
    runs = update_index(tmp_path)
    assert len(runs) == 1 and runs[0]["stage"] == "s1_bird"


def test_clean_json():
    assert clean_json({"a": [np.float64("nan"), np.inf, np.int64(3), np.bool_(True)]}) == {"a": [None, None, 3, True]}


def test_committed_stage1_run_folders_follow_contract():
    from echo.export import RUNS

    folders = sorted((RUNS / "s1_bird").glob("*/manifest.json"))
    for mf in folders:
        check_run_folder(mf.parent)
    if (RUNS / "index.json").exists():
        check_index(RUNS)


def test_manifest_records_git_state_and_rejects_key_collisions(tmp_path):
    import pytest

    d = _fake_run(tmp_path)
    man = json.loads((d / "manifest.json").read_text())
    assert isinstance(man["git_dirty"], bool) and isinstance(man["git_dirty_paths"], list)
    assert man["git_dirty"] == bool(man["git_dirty_paths"])
    with pytest.raises(ValueError):
        write_run("s1_bird", "x", "t", scene=Scene(), profile={"r0_m": 3.06, "dr_m": 0.01, "reflectivity": [1.0],
                  "units": "x"}, target_audio=np.zeros(10), t_echo0=0.0178, claps=clap_family(5),
                  echo_t0=np.zeros((5, 1920)), metrics=json.loads((d / "metrics.json").read_text()),
                  history={"phases": []}, seed=0, command="c", runs_root=tmp_path, extra={"seed": 1})


def test_final_tier1_run_through_contract_checker(tmp_path):
    """A final (Tier 1) run with a field video, saved correction rounds and a robustness table passes the checker."""
    from echo.field_video import render_field_video

    tgt = bird_note()
    claps = clap_family(5)
    n = int(0.12 * FS)
    t0 = 2 * 3.06 / 343.0
    i0 = int(round(t0 * FS))
    e2 = np.zeros((5, n))
    e2[:, i0:i0 + len(tgt.audio)] = 0.05 * tgt.audio
    e1 = 0.9 * e2
    rob = [{"case": "nominal", "label": "Nominal", "metrics": {"spec_corr": 0.9}, "delta": {"spec_corr": 0.0},
            "pass": True}]
    metrics = score_stage("s1_bird", tgt, t0, e2, 0.01 * e2, e1, depth_m=13.7, post_count=3, fill_fraction=0.01,
                          robustness=rob, claps=claps)
    posts = np.array([[3.5, 0.0, 0.01], [4.0, 0.2, 0.02], [5.0, -0.5, 0.01]])
    run_id = "20990101-000000-t6"
    d = tmp_path / "s1_bird" / run_id
    frames = np.random.default_rng(0).standard_normal((10, 30, 50)).astype(np.float16)
    fld = render_field_video(frames, [0.0, 5.0, -1.5, 1.5], d / "field.webm", t0=0.0, dt_frame=0.00025)
    fld.pop("colour")
    prof = {"r0_m": 3.06, "dr_m": 0.01, "reflectivity": [0.0, 1.0], "units": "x"}
    hist = {"phases": [{"name": "Profile solve (Tier 0)", "x_label": "Adam step", "iters": [0], "loss": [1.0]},
                       {"name": "tier1_correction", "x_label": "correction round", "iters": [0, 1],
                        "loss": [1.2, 1.1], "score": [0.05, 0.07]}]}
    iters = [(f"r{k}", Scene(posts=posts), prof, e1[0], metrics, k) for k in (0, 1)]
    solver = {"tier1": "fdtd", "device": "cpu", "dx": 0.009375, "dt": 7.8e-6, "grid": [100, 80], "f_lo": 300.0,
              "f_max": 4000.0, "ppw": 9.0, "wall_s": 120.0}
    out = write_run("s1_bird", "t6", "final", scene=Scene(posts=posts), profile=prof, target_audio=tgt.audio,
                    t_echo0=t0, claps=claps, echo_t0=e2, echo_t1=e1, metrics=metrics, history=hist, seed=0,
                    command="pytest", duration_s=0.12, runs_root=tmp_path, iters=iters, solver=solver, field=fld,
                    run_id=run_id, status="final")
    check_run_folder(out)
    check_index(tmp_path)
    m = json.loads((out / "manifest.json").read_text())
    assert m["status"] == "final" and m["verified"] is True and m["solver"]["tier1"] == "fdtd"
    assert set(m["field"]) == {"file", "fps", "n_frames", "t0_s", "sim_seconds_per_frame", "extent_m", "width",
                               "height"}
    h = json.loads((out / "history.json").read_text())
    assert [s["dir"] for s in h["phases"][-1]["saved"]] == ["iters/r0", "iters/r1"]
    sp = json.loads((out / "spectrograms.json").read_text())
    assert sp["panels"]["tier1"] is not None
    for k in (0, 1):
        assert (out / "iters" / f"r{k}" / "echo.wav").exists()


def test_rel_path_strips_repo_root(tmp_path):
    from echo.export import ROOT, rel_path

    assert rel_path(ROOT / "runs" / "validation" / "metrics.json") == "runs/validation/metrics.json"
    assert rel_path(tmp_path / "x") == str(tmp_path / "x")  # outside the repo: unchanged


def test_build_pack_summary_run_path_relative():
    import inspect

    from echo import buildkit

    src = inspect.getsource(buildkit)
    assert '"run_path": rel_path(run_dir)' in src
    pack = json.loads((Path(__file__).resolve().parents[1] / "build" / "s1_bird-20261125-104529-s1" / "pack.json")
                      .read_text())
    assert not Path(pack["run_path"]).is_absolute()
