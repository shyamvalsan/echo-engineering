"""Stage 2 (motif): the config builds, the target is the spec's motif, the realized Tier 0 echo of the chosen
configuration is transcribed correctly by the note judge for every clap (informational sanity of the design, never a
selection rule), and a --tier0-only run folder passes the contract checker."""

import json
from dataclasses import replace

import numpy as np
import pytest

from contract_check import check_run_folder
from echo.metrics import THRESHOLDS
from echo.targets import motif
from stages.common import run_stage
from stages.s2_motif import CONFIG

# The stage band is 898-2500 Hz: 40 mel filters at n_fft 256 (62.5 Hz bins) leave some filters empty in the loss's
# log-mel term (librosa warns). Empty channels are equal in echo and target, so they add nothing to the loss.
pytestmark = pytest.mark.filterwarnings("ignore:Empty filters detected in mel frequency basis")


def test_config_and_target():
    assert CONFIG.stage == "s2_motif" and CONFIG.stage in THRESHOLDS
    assert THRESHOLDS["s2_motif"] == {"notes_in_order": 1.0, "note_cents_max": 30.0}
    t = motif()
    # spec: C6 E6 G6 C7 = 1047, 1319, 1568, 2093 Hz, 45 ms each, 180 ms; depth c * 0.18 / 2 = 30.87 m
    assert [n[0] for n in t.notes] == [1047.0, 1319.0, 1568.0, 2093.0]
    assert np.allclose([b - a for _, a, b in t.notes], 0.045)
    assert abs(len(t.audio) / 16000 - 0.18) < 1e-3
    assert CONFIG.make_target is motif and CONFIG.note_s == 0.045
    assert CONFIG.realization in ("phase_locked", "phase_locked_uniform") and CONFIG.posts_per_period >= 1
    assert CONFIG.a_ref in CONFIG.catalog and CONFIG.band_max_hz >= 2093.0 * 1.1
    assert CONFIG.duration_s >= 2 * CONFIG.r0 / 343.0 + 0.18 + 0.008


def test_uniform_phase_locked_cancels_comb_harmonics():
    """K = 6 equally spaced ring phases weighted 1 + cos q = (2, 1.5, 0.5, 0, 0.5, 1.5): by hand, harmonic m sums to
    2 + 3 cos(m pi/3) + cos(2 m pi/3) = 3, 0, 0, 0, 3 for m = 1..5, so H2..H4 vanish (the pure comb K = 1 has
    H2 = H1). On a 1047 Hz carrier with 2400 integer posts the realized H2 and H3 are > 25 dB below H1."""
    from echo.realize import phase_locked_ranges

    q = np.arange(6) * np.pi / 3
    w = 1 + np.cos(q)
    assert np.allclose([np.sum(w * np.cos(m * q)) for m in range(1, 6)], [3, 0, 0, 0, 3], atol=1e-12)
    dr = 0.01
    rho = 3 + dr * np.arange(800)
    kap = 2 * 1047.0 / 343.0
    prof = 1 + np.cos(2 * np.pi * kap * (rho - 3)) * np.hanning(800)
    h = {}
    for K, u in ((1, False), (6, True)):
        r, _ = phase_locked_ranges(prof, 2400, (898.0, 4000.0), r0=3.0, dr=dr, posts_per_period=K, uniform=u,
                                   fractional=False)
        h[K] = [abs(np.exp(2j * np.pi * m * kap * r).sum()) for m in (1, 2, 3)]
    assert h[1][1] / h[1][0] > 0.9
    assert h[6][1] / h[6][0] < 0.056 and h[6][2] / h[6][0] < 0.056


@pytest.fixture(scope="module")
def tier0_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs")
    cfg = replace(CONFIG, field=False, robustness=False)
    d, des, res = run_stage(cfg, None, command="pytest", verbose=False, runs_root=root)
    return d, des


def test_tier0_echo_transcribed_for_every_clap(tier0_run):
    d, des = tier0_run
    m = json.loads((d / "metrics.json").read_text())
    rows = [r for r in m["per_clap"] if r["tier"] == "tier0"]
    assert len(rows) == CONFIG.n_claps
    for r in rows:
        assert r["metrics"]["notes_in_order"] == 1.0, r
        assert r["metrics"]["note_cents_max"] <= 30.0, r
    assert m["headline"]["post_count"] == len(des.posts) > 100
    assert m["headline"]["depth_m"] > 30.0


def test_tier0_only_run_folder_contract(tier0_run):
    d, _ = tier0_run
    check_run_folder(d)
    man = json.loads((d / "manifest.json").read_text())
    assert man["status"] == "tier0_only" and man["stage"] == "s2_motif"
