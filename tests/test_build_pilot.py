"""Build pilot: config, selection rule, a Tier 0 pilot run folder passing the contract, build-pack round trip."""

import json
import math

import numpy as np
import pytest

from contract_check import check_run_folder
from echo import buildkit as bk
from stages import build_pilot as bp


def test_config_builds_for_every_candidate():
    for name, (make_target, dur, counts, own) in bp.CANDIDATES.items():
        cfg = bp.make_config(name, fill=0.003)
        assert cfg.stage == "build_pilot" and cfg.half_angle_deg == bp.HALF_ANGLE == 10.0
        assert cfg.realization == "phase_locked" and cfg.posts_per_period == 1 and cfg.a_ref == 0.01
        assert cfg.max_posts == bp.POST_CAP and cfg.stretch_comp and cfg.robustness_c_cases == ()
        t = make_target()
        assert len(t.audio) / 16000 + 0.02 < dur  # the timeline covers the note
        assert own == (name == "whistle80")
    p = bp.ping()
    assert np.allclose(p.f_track[1], 2500.0) and p.f_top_hz == 2500.0
    # the pilot is judged with the stage-1 judge function (registered under its own stage id)
    from echo.metrics import STAGE_METRICS

    assert STAGE_METRICS["build_pilot"] is STAGE_METRICS["s1_bird"]


def test_min_gap_hand_calc():
    posts = np.array([[0.0, 0.0, 0.01], [0.12, 0.0, 0.01], [0.0, 0.5, 0.02]])
    assert bp.min_gap_m(posts) == pytest.approx(0.12 - 0.02)  # centre distance minus both radii


def _row(cand, n, fill, side, wc2, loss2, lvl):
    return {"candidate": cand, "n_posts": n, "fill": fill, "sweet_spot_side_m": side, "echo_level_db_3d": lvl,
            "jitter": [{"sigma_mm": 2.0, "wave_corr": wc2, "loss": loss2}]}


def test_selection_rule_is_judge_free_and_respects_limits():
    rows = [_row("a", 300, 0.002, 0.05, 0.97, 4.0, -55.0), _row("a", 500, 0.0034, 0.05, 0.98, 3.5, -53.0),
            _row("b", 170, 0.0037, 0.30, 0.99, 1.0, -40.0),  # best on everything but over the coverage limit
            _row("c", 100, 0.002, 0.0, 0.99, 3.0, -50.0)]
    ch, ranking = bp.select(rows)
    assert (ch["candidate"], ch["n_posts"]) == ("a", 500)  # widest spot first; within "a" the lowest 2 mm loss
    assert [r[0] for r in ranking] == ["a", "c"]


@pytest.fixture(scope="module")
def pilot_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs")
    d = bp.run_pilot(tier1=False, runs_root=root, command="pytest")
    return d


def test_tier0_pilot_run_folder_contract(pilot_run):
    d = pilot_run
    check_run_folder(d)
    man = json.loads((d / "manifest.json").read_text())
    met = json.loads((d / "metrics.json").read_text())
    assert man["status"] == "tier0_only" and man["stage"] == "build_pilot"
    pl = met["pilot"]
    assert pl["post_count"] <= bp.POST_CAP and pl["fill_fraction"] <= 0.0035 + 1e-4
    assert pl["min_gap_m"] >= 0.05 - 1e-6  # the spec's minimum surface gap holds
    assert set(pl["reference_thresholds"]) == {"pitch_err_pct", "spec_corr"}
    sm = pl["sweet_spot_map"]
    assert np.array(sm["wave_corr"]).shape == (len(bp.SWEET_X), len(bp.SWEET_Y))
    i0, j0 = bp.SWEET_X.index(0.0), bp.SWEET_Y.index(0.0)
    assert sm["wave_corr"][i0][j0] == pytest.approx(1.0, abs=1e-3)  # the design listener against itself
    assert met["passed"] is False  # Tier 0 only: never a pass


def test_pilot_build_pack_round_trip(pilot_run, tmp_path):
    out = bk.build_pack(pilot_run, tmp_path / "build", physics=False)
    run = bk.load_run(pilot_run)
    back = bk.read_stakeout_csv(out / "stakeout.csv")
    np.testing.assert_allclose(back, run["scene"].posts, atol=0.6e-4)
    import csv

    with (out / "stakeout.csv").open() as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    rings = [int(r["ring"]) for r in rows]
    assert rings == sorted(rings, reverse=True)  # ring by ring, far ring first
    # each ring lies on one equal-delay ellipse (bistatic range within the 3 mm ring tolerance chain)
    for k in set(rings[:20]):
        rr = [float(r["rho_m"]) for r in rows if int(r["ring"]) == k]
        assert max(rr) - min(rr) < 0.01
    b = json.loads((out / "bom.json").read_text())
    assert b["full_scale"][0]["count"] == len(run["scene"].posts) and b["full_scale"][0]["diameter_mm"] == 20
    assert math.isclose(json.loads((out / "pack.json").read_text())["posts"], len(back))
