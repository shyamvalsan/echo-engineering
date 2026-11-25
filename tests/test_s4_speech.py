"""Stage 4 (speech): configs build within the Tier 1 budget, targets load from the committed cache, the ablation
harness orders correctly on a toy case, and a --tier0-only 4a run folder passes the contract checker."""

import json

import numpy as np
import pytest
import torch

from contract_check import check_run_folder
from echo.clap import clap_family
from echo.inverse import initial_profile
from echo.metrics import THRESHOLDS
from stages import s4_speech as S

pytestmark = pytest.mark.filterwarnings("ignore:Empty filters detected in mel frequency basis")


@pytest.mark.parametrize("sub,name", [("4a", "ah"), ("4b", "ma"), ("4b", "ba"), ("4b", "om"), ("4c", "hello")])
def test_configs_build_and_fit_budget(sub, name):
    cfg = S.make_config(sub, name)
    assert cfg.stage == S.SUBSTAGES[sub]["judge"] and cfg.stage in THRESHOLDS
    assert cfg.band_min_hz == 500.0 and cfg.band_max_hz == cfg.f_max
    assert cfg.tag.endswith(f"_{sub}_{name}") and cfg.a_ref in cfg.catalog
    t = S.target_of(name)
    # timeline covers first echo (2 * 3.06 / 343 = 17.8 ms) + target + 8 ms clap
    assert cfg.duration_s >= 2 * cfg.r0 / 343.0 + len(t.audio) / 16000 + 0.008
    plan = S.tier1_plan(cfg, t)
    assert plan["est_wall_s_idle_8_threads"] <= S.TIER1_BUDGET_S
    # posts ~ 1000 per 100 ms of target at 1 cm: fill = N pi a^2 / wedge area
    assert abs(cfg.target_fill / S.fill_for_posts(cfg, t, cfg._n_posts) - 1) < 1e-9


@pytest.mark.parametrize("name", ["ah", "ma", "ba", "om", "hello"])
def test_targets_load_from_committed_cache(name):
    t = S.target_of(name)
    assert t.source == "cache"
    assert abs(np.max(np.abs(t.audio)) - 1.0) < 1e-9
    if name in ("ma", "ba", "om"):
        assert set(t.candidates) == {"ma", "ba", "om"}


def test_flat_clap_and_flat_scatter_hand_values():
    """Flat clap: |C(f)| constant in band (within the raised-cosine edges), peak 1. Flat scatterer: W(f) |T(f)| equals
    |T(2.5 kHz)| at every in-band f; Rayleigh check by hand: |T| ~ (3 pi / 4)(ka)^2, so W(1 kHz)/W(2 kHz) ~ 4."""
    Cf, x = S.flat_clap_spectrum(4096, 2)
    f = np.fft.rfftfreq(4096, 1 / 16000)
    m = (f > 800) & (f < 3500)
    A = np.abs(Cf.numpy())
    assert np.max(np.abs(x)) == pytest.approx(1.0) and A.std() < 1e-12
    # by hand: a band-limited delta of bandwidth B = 3.5 kHz on n bins peaks at 2 B / fs * A (= 1 here), so A ~ 2.3
    assert A[0, 0] == pytest.approx(16000 / (2 * 3500), rel=0.05)
    W = S.scatter_weight(4096, 0.01, True).numpy()
    from echo.tier0 import cylinder_response

    T = np.abs(cylinder_response(0.01, f[m]))
    assert np.allclose(W[m] * T, np.abs(cylinder_response(0.01, 2500.0)), rtol=1e-9)
    i1, i2 = np.argmin(np.abs(f - 1000)), np.argmin(np.abs(f - 2000))
    assert 3.0 < W[i1] / W[i2] < 4.5


def test_ablation_toy_ordering():
    """Toy case (40 ms of "ah", 120 Adam steps): removing all three constraints never increases the optimized loss
    beyond optimizer noise (0.05), and each single removal does not either. The ceiling (flat clap, signed, flat
    scatterer) reproduces the target nearly exactly."""
    torch.manual_seed(0)
    audio = S.target_of("ah").audio[:640]
    audio = audio * np.hanning(len(audio))
    claps = clap_family(5, seed=0)
    loss = {}
    for cb in S.COMBOS:
        m = S.AblationModel(audio, claps, flat_clap=bool(cb["flat_clap"]), flat_scatter=bool(cb["flat_scatter"]))
        w = m.wiener_init()
        inits = [initial_profile(audio, m.n_rho, m.r0, m.dr), w if cb["signed"] else S.positive_from_signed(w)]
        loss[tuple(cb.values())] = min(S.solve_ablation(m, bool(cb["signed"]), p0, steps=120)[1] for p0 in inits)
    base, ceil = loss[(0, 0, 0)], loss[(1, 1, 1)]
    assert ceil <= base + 0.05
    for k in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
        assert loss[k] <= base + 0.05, (k, loss[k], base)
    assert ceil < 0.6 * base


def test_tier0_only_4a_run_contract(tmp_path):
    d, met, des, res = S.run_one("4a", "ah", tier0_only=True, runs_root=tmp_path, overrides={"steps": 30},
                                 abl={"attribution": None, "note": "test"}, study={"note": "test"}, verbose=False)
    check_run_folder(d)
    man = json.loads((d / "manifest.json").read_text())
    assert man["stage"] == "s4_speech" and man["substage"] == "4a" and man["status"] == "tier0_only"
    assert met["judge_stage"] == "s4a_vowel" and met["verified"] is False and met["passed"] is False
    assert met["band_hz"][0] == 500.0
    assert d.name.endswith("_4a_ah")
    assert any(m["id"] == "formant_err_pct" for m in met["metrics"])
