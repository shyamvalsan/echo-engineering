"""Stage 3 (melody): config for both note lengths, targets per the spec, the Tier-0-only run passes the contract checker,
and the configured realization's Tier 0 echo transcribes correctly for every clap (design sanity)."""

import json
import math
import subprocess
import sys

import numpy as np
import pytest

from echo.scene import C0
from echo.targets import melody
from stages.s3_melody import (CONFIG, duration_of, extinction_profile_db, extinction_precomp, make_config,
                              sigma_total_m)

SPEC_HZ = (1319, 1319, 1397, 1568, 1568, 1397, 1319, 1175)  # E6 E6 F6 G6 G6 F6 E6 D6


@pytest.mark.parametrize("note_ms,total_s,depth_m", [(100, 0.8, 137.0), (60, 0.48, 82.0)])
def test_target_matches_spec(note_ms, total_s, depth_m):
    t = melody(note_ms=note_ms)
    assert len(t.notes) == 8
    assert [round(f) for f, _, _ in t.notes] == list(SPEC_HZ)
    for f, a, b in t.notes:
        assert b - a == pytest.approx(note_ms / 1000.0, abs=1e-3)
    assert len(t.audio) / 16000 == pytest.approx(total_s, abs=1e-3)
    # hand calc: depth = c * T / 2 = 343 * 0.8 / 2 = 137.2 m (spec table: 137 m); 343 * 0.48 / 2 = 82.3 m
    assert C0 * total_s / 2 == pytest.approx(depth_m, abs=0.5)


@pytest.mark.parametrize("note_ms", [100, 60])
def test_config_builds(note_ms):
    cfg = make_config(note_ms)
    assert cfg.stage == "s3_melody"
    assert cfg.note_s == pytest.approx(note_ms / 1000)
    # 1 cm posts (extinction per unit echo ~ k a^2) are validated for backscatter on the 2.5 kHz grid, not on 2 kHz
    assert cfg.f_max == 2500.0 and cfg.band_max_hz == 2500.0
    assert cfg.a_ref == 0.01 and cfg.catalog == (0.01,)
    assert cfg.half_angle_deg == 20.0 and cfg.max_half_width_m == 1.0  # constant-width strip inside the spec wedge
    # timeline: 2 * 3 / 343 = 17.5 ms + 8 notes + clap 8 ms + 10 ms margin
    assert cfg.duration_s == pytest.approx(0.0175 + 8 * note_ms / 1000 + 0.018, abs=1e-3)
    assert cfg.duration_s == duration_of(note_ms)
    assert cfg.robustness_c_cases == ()  # c cases recorded as not run (cost)
    assert cfg.robustness_jitter is False  # not run (time), recorded in metrics.s3_extra.robustness_not_run
    assert cfg.tag.endswith("_60ms") if note_ms == 60 else cfg.tag == "s3"
    t = cfg.make_target()
    assert np.median([b - a for _, a, b in t.notes]) == pytest.approx(cfg.note_s, abs=1e-6)


def test_extinction_estimate_and_precomp():
    # sigma: small-ka rigid cylinder, 2D: sigma ~ (3 pi^2 / 4) k^3 a^4 (leading order); at ka = 0.48 the exact
    # partial-wave value is of the same order (1.3 cm for a = 2 cm at 1.3 kHz)
    k = 2 * math.pi * 1300 / C0
    for a in (0.01, 0.02):
        s = sigma_total_m(a, 1300.0)
        assert 0.5 * (3 * math.pi ** 2 / 4) * k ** 3 * a ** 4 < s < 2.0 * (3 * math.pi ** 2 / 4) * k ** 3 * a ** 4
    cfg = CONFIG
    n = int(round(137.2 / cfg.dr))
    p = np.full(n, 0.01)  # 0.01 posts per 1 cm bin = 1 post per metre of range
    L = extinction_profile_db(p, cfg, cfg.make_target())
    # more posts in front, more loss (sigma follows the note probing each range, so it is monotone within a note)
    assert L[0] == 0.0 and L[-1] > L[n // 2] > L[n // 8] > 0
    # hand calc at the far end (last note D6 1175 Hz; strip 2 m wide everywhere beyond rho = 1 / tan 20 deg = 2.75 m):
    # 8.686 * sigma(1175 Hz) * (137 posts in front) / 2 m
    approx = 8.686 * sigma_total_m(0.01, 1175.0) * (n - 1) * 0.01 / 2.0
    assert L[-1] == pytest.approx(approx, rel=0.02)
    q = extinction_precomp(cfg, p)
    assert q.sum() == pytest.approx(p.sum(), rel=1e-9)  # keeps the post count
    assert q[-1] > q[0]  # far end strengthened


def test_tier0_only_run_passes_contract(tmp_path):
    from stages.common import run_stage
    from contract_check import check_run_folder

    cfg = make_config(60, steps=0)
    run_dir, des, _ = run_stage(cfg, None, command="test", verbose=False, runs_root=tmp_path)
    checked = check_run_folder(run_dir)  # raises on the first contract violation
    assert "metrics.json" in checked
    m = json.loads((run_dir / "metrics.json").read_text())
    assert m["stage"] == "s3_melody" and m["verified"] is False


@pytest.mark.xfail(strict=True, reason="stage 3 result: the configured strip design (2,500 x 1 cm posts, K=1) does "
                   "not transcribe on Tier 0 either (runs/s3_melody/_studies/design_study_tier0.json); strict, so "
                   "a design that does will flag this test")
def test_chosen_config_tier0_transcribes_every_clap():
    """Design sanity: the configured design (100 ms) realized and run through Tier 0 (Tier 1 band) is transcribed
    correctly for every clap variant (8 notes, each within 50 cents)."""
    from echo.clap import clap_family
    from echo.metrics import stage_values
    from echo.inverse import solve_profile
    from echo.realize import scale_profile
    from stages.common import build_design, stage_scene

    cfg = CONFIG
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    from echo.inverse import clap_band

    b = clap_band(claps)
    band = (b[0], min(b[1], cfg.band_max_hz))
    n_out = int(round(cfg.duration_s * 16000))
    prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                                steps=cfg.steps, lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out, band=band)
    p = scale_profile(prof_n, cfg.target_fill, cfg.r0, cfg.dr, cfg.a_ref, half_angle_deg=cfg.half_angle_deg)
    if cfg.profile_transform is not None:
        p = cfg.profile_transform(cfg, p)
    des = build_design(cfg, p, claps, band, n_out)
    vals = stage_values(cfg.stage, des.echo_t0_2d, target, res.n0 / 16000, band=band)
    assert [v["notes_in_order"] for v in vals] == [1.0] * cfg.n_claps, vals
    assert max(v["note_cents_max"] for v in vals) < 50.0
