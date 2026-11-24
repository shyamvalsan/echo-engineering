"""Run-folder writer: contract fields (as the viewer reads them), no NaN/Infinity, index rebuild."""

import json

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
