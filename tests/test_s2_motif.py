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
from stages.s2_motif import CONFIG, CONFIG_V1, optical_depth, scattering_width

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


def test_scattering_width_and_optical_depth():
    """Rigid cylinder, thin-post limit: sigma -> (3 pi^2 / 4) k^3 a^4. By hand, a = 1 cm at 1047 Hz:
    k = 19.18 /m, k^3 a^4 = 7.06e-5 m, sigma = 7.402 * 7.06e-5 = 0.522 mm; the series gives 0.513 mm (ka = 0.19).
    Optical depth of a uniform profile: 1 post per 1 cm bin = 100 posts/m of range across an arc 2 rho theta wide
    (20 deg: 0.698 rho), so d tau/d rho = 100 sigma / (0.698 rho) and tau(rho) = 143.2 sigma ln(rho / r0)."""
    k = 2 * np.pi * 1047.0 / 343.0
    ray = 3 * np.pi ** 2 / 4 * k ** 3 * 0.01 ** 4
    sig = float(scattering_width(0.01, 1047.0))
    assert abs(ray - 5.22e-4) < 2e-6 and abs(sig / ray - 1) < 0.03
    cfg = replace(CONFIG, a_ref=0.01, half_angle_deg=20.0)
    prof = np.ones(2000)
    tau = optical_depth(cfg, prof, 1047.0)
    rho = cfg.r0 + cfg.dr * np.arange(2000)
    hand = 100 * sig / (2 * np.radians(20.0)) * np.log(rho[-1] / cfg.r0)
    assert abs(tau[-1] / hand - 1) < 0.01


@pytest.fixture(scope="module")
def tier0_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs")
    cfg = replace(CONFIG, field=False, robustness=False)
    d, des, res = run_stage(cfg, None, command="pytest", verbose=False, runs_root=root)
    return d, des


def test_v1_tier0_echo_transcribed_for_every_clap(tmp_path):
    """The first design (2 cm, 10 deg) is the one whose Tier 0 echo transcribes for every clap (it failed on Tier 1 by
    extinction). The v2 default's Tier 0 transcription is reported in its run, not asserted (task-7 report)."""
    cfg = replace(CONFIG_V1, field=False, robustness=False)
    d, des, _ = run_stage(cfg, None, command="pytest", verbose=False, runs_root=tmp_path)
    m = json.loads((d / "metrics.json").read_text())
    rows = [r for r in m["per_clap"] if r["tier"] == "tier0"]
    assert len(rows) == CONFIG.n_claps
    for r in rows:
        assert r["metrics"]["notes_in_order"] == 1.0, r
        assert r["metrics"]["note_cents_max"] <= 30.0, r
    assert m["headline"]["post_count"] == len(des.posts) > 100
    assert m["headline"]["depth_m"] > 29.5  # 30.9 m of echo less the fades (stretch warp off on Tier 0 only)


def test_tier0_only_run_folder_contract(tier0_run):
    d, _ = tier0_run
    check_run_folder(d)
    man = json.loads((d / "manifest.json").read_text())
    assert man["status"] == "tier0_only" and man["stage"] == "s2_motif"
