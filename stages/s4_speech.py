"""Stage 4: speech. 4a sustained "ah" (150 ms), 4b syllables "ma" / "ba" / "om" (223-247 ms), 4c word "hello" (399 ms).

    uv run python -m stages.s4_speech                    # everything: ablations, realization study, Tier 1 runs
    uv run python -m stages.s4_speech --only 4a          # one sub-stage (4a | 4b | 4c)
    uv run python -m stages.s4_speech --tier0-only       # no Tier 1 (runs are status tier0_only)
    uv run python -m stages.s4_speech --ablations-only   # Tier 0 ablations -> runs/s4_speech/_studies/ablations_<name>.json
    uv run python -m stages.s4_speech --study-only       # Tier 0 realization comparison -> _studies/realization_<name>.json

Run folders live in runs/s4_speech/<run_id> (run_id suffix _4a_ah, _4b_ma, _4b_ba, _4b_om, _4c_hello). The shared
driver (stages.common.run_stage) scores with the judge stage key (s4a_vowel / s4b_syllables / s4c_word, the keys of
echo.metrics.THRESHOLDS); it writes into a scratch root and the folder is moved here with `stage: s4_speech` and the
sub-stage id in the manifest and metrics.

Selection rules (integrity): every design choice (profile solve, realization, ablation optimum) is made by the
spectrogram loss (echo.inverse EchoLoss / window_loss) only. Judges (formants, closed set, ESTOI, whisper) are computed
for information and for the gating verdict on Tier 1, never inside a loss or a selection.

Band: the stage band is the speech targets' band, 500-4000 Hz (StageConfig.band_min_hz), not the clap band (898-4000
Hz, -20 dB re the clap peak): F1 of "ah" (744 Hz) lies below the clap band, and an echo band-limited to the clap band
cannot carry it. The profile solve therefore sees (and may pre-emphasize) 500-900 Hz, where the clap is 18-28 dB down.

Ablations (Tier 0, profile model, same optimizer and loss throughout): the forward model is
    E_k(f) = C_k(f) * W(f) * H_profile(f)       H_profile = echo.tier0.profile_transfer (2D, 1 cm reference posts)
(a) clap spectrum:  C_k -> an ideal flat-spectrum clap (band-limited delta over 500-4000 Hz, peak 1);
(b) positivity:     profile softplus(theta) >= 0 -> profile theta (signed reflectors allowed);
(c) post scattering: W = 1 -> |T_1cm(2.5 kHz)| / |T_1cm(f)| (frequency-flat scatterer, equal to the 1 cm post at the clap
                    peak; the phase of T is kept).
All 8 combinations are solved with the same Adam settings from the same two initializations (physics init and a
Wiener-deconvolved init); the lower final loss is kept (selection by loss only).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from echo import export
from echo.clap import band_limit, clap_family
from echo.inverse import EchoLoss, R0_PROFILE, echo_window, initial_profile, window_loss
from echo.metrics import echo_level_db, echo_segment
from echo.scene import C0, FS, Scene, fill_fraction
from echo.targets_speech import speech_target
from echo.tier0 import DR_PROFILE, choose_n_fft, cylinder_response, post_echo, profile_transfer
from stages.common import StageConfig, stage_scene

STAGE = "s4_speech"
BAND = (500.0, 4000.0)
CLAP_BAND = (898.4375, 4000.0)  # echo.inverse.clap_band(clap_family(5, seed=0)), for the informational clap-band loss
SUBSTAGES = {
    "4a": {"judge": "s4a_vowel", "names": ("ah",)},
    "4b": {"judge": "s4b_syllables", "names": ("ma", "ba", "om")},
    "4c": {"judge": "s4c_word", "names": ("hello",)},
}
SEED = 0
STUDY_DIR = export.RUNS / STAGE / "_studies"
TIER1_CELL_STEPS_PER_S = 55e9 / 260.0  # cost model (task 3/6): ~55e9 cell-steps in ~260 s on 8 idle threads
TIER1_BUDGET_S = 12 * 60.0

# ------------------------------------------------------------------------------------------------- Tier 1 settings
# Grid per sub-stage (validated grids only, runs/validation/metrics.json): 4 kHz (dx 8.6 mm) for the vowel and the
# syllables; 2.5 kHz (dx 13.7 mm) for the word, whose 4 kHz run would need a wedge narrower than the listener anchors
# allow within 12 min. Half-angles are the widest that keep the planned run under TIER1_BUDGET_S on an idle machine
# (computed by `wedge_for_budget`, logged in each run's metrics.tier1_plan).
TIER1 = {"4a": {"f_max": 4000.0}, "4b": {"f_max": 2500.0}, "4c": {"f_max": 2500.0}}
# 4b/4c (after the 4a run; coordinator evidence from stages 1-2: extinction in narrow dense fields): +-20 deg wedge
# clipped to a constant-width strip (StageConfig.max_half_width_m), 2.5 kHz grid so the strip can be wide, post counts
# chosen so the predicted two-way extinction at the far end (Tier 0 cylinder model, `predicted_extinction`, uniform
# estimate 8.686 N sigma / (2 hw)) stays at ~5-8 dB at 2.5 kHz: ma/ba/om 1,500 posts in +-7 m (5.4 dB; est. 400-474 s),
# hello 1,500 posts in +-5 m (7.6 dB; est. 833 s). At 4 kHz a strip wide enough for low extinction does not fit 12 min.
STRIP = {"ma": (7.0, 1500), "ba": (7.0, 1500), "om": (7.0, 1500), "hello": (5.0, 1500)}
# widest half-angle (0.5 deg steps) with a planned run <= 12 min on an idle machine (wedge_for_budget, 2026-11-25):
# ah 11.5 (704 s), ma 3.5 (689 s), ba 3.0 (713 s), om 2.5 (639 s), hello at 2.5 kHz 3.0 (628 s); hello at 4 kHz does
# not fit at any half-angle >= 1 deg (the listener anchors fix the domain width; 20 deg would take ~13,900 s).
HALF_ANGLE = {"ah": 11.5, "ma": 3.5, "ba": 3.0, "om": 2.5, "hello": 3.0}
POSTS_PER_100MS = 1000  # post count scale (stage 1: 1,060 posts for 80 ms at 1 cm worked best on Tier 1)


def target_of(name):
    return speech_target(name)


def duration_for(target, f_max=4000.0):
    """Exported timeline: first echo (2 r0 / c) + target + clap (8 ms) + 12 ms margin."""
    return round(2 * R0_PROFILE / C0 + len(target.audio) / FS + 0.008 + 0.012, 3)


def make_config(sub, name, **kw) -> StageConfig:
    spec = SUBSTAGES[sub]
    t1 = TIER1[sub]
    tgt = target_of(name)
    n_posts = STRIP[name][1] if name in STRIP else int(round(POSTS_PER_100MS * len(tgt.audio) / FS / 0.1))
    cfg = StageConfig(
        stage=spec["judge"],  # score key (THRESHOLDS); the folder is moved to runs/s4_speech afterwards
        title=f"Speech {sub}: \"{name}\" ({len(tgt.audio) / FS * 1e3:.0f} ms)",
        tag=f"s4_{sub}_{name}",
        make_target=lambda n=name: target_of(n),
        duration_s=duration_for(tgt),
        seed=SEED,
        a_ref=0.01,
        catalog=(0.01,),
        steps=1200 if sub == "4a" else 800,  # 4b/4c: 800 (time box on a shared CPU; loss 2.65 at 500 vs 2.52 at 825 on ah)
        lr=0.05,
        f_max=t1["f_max"],
        band_min_hz=BAND[0],
        band_max_hz=t1["f_max"],
        half_angle_deg=20.0 if name in STRIP else HALF_ANGLE[name],
        max_half_width_m=STRIP[name][0] if name in STRIP else None,
        # Tier 0 realization study (_studies/realization_ah.json, chosen by loss under 1-2 mm jitter only): sampling
        # 5.16 < quantile 5.31 < phase-locked 5.90 < half-wave 5.99 (1,500 posts, 1 cm)
        realization="sampling",
        correction_rounds=1,
        robustness=False,  # free cases (listener offsets, claps alone) are added by this module from the same run
        field=(sub == "4a"),
        threads=4,
        notes=f"Stage 4{sub[1]} target \"{name}\" (espeak-ng, band-limited 500-4000 Hz).",
    )
    cfg.target_fill = None  # set from n_posts by `fill_for_posts` once the half-angle is known
    cfg._n_posts = n_posts  # type: ignore[attr-defined]
    if os.environ.get("S4_STEPS"):  # time-box override of the driver's profile-solve steps (logged in the config)
        cfg.steps = int(os.environ["S4_STEPS"])
    for k, v in kw.items():
        setattr(cfg, k, v)
    if cfg.target_fill is None:
        cfg.target_fill = fill_for_posts(cfg, tgt, n_posts)
    return cfg


def fill_for_posts(cfg, target, n_posts):
    from echo.realize import wedge_area

    r_hi = cfg.r0 + C0 * len(target.audio) / FS / 2.0
    area = wedge_area(stage_scene(cfg).r_min, r_hi, cfg.half_angle_deg)
    hw = getattr(cfg, "max_half_width_m", None)
    if hw is not None:  # strip clipped to the wedge (same rule as stages.common for the stretch prior)
        area = min(area, 2.0 * hw * (r_hi - stage_scene(cfg).r_min))
    return float(n_posts * math.pi * cfg.a_ref ** 2 / area)


# --------------------------------------------------------------------------------------------------- Tier 1 planning
def tier1_plan(cfg, target, half_angle_deg=None):
    """Planned grid, steps and estimated wall time (idle machine) for this config's Tier 1 run (no solve)."""
    from echo import tier1
    from stages.common import stage_listeners

    c = replace(cfg, half_angle_deg=half_angle_deg or cfg.half_angle_deg)
    r_hi = c.r0 + C0 * len(target.audio) / FS / 2.0
    th = math.radians(c.half_angle_deg)
    hw = getattr(c, "max_half_width_m", None) or np.inf
    corners = np.array([[3.0 * math.cos(th), s * min(hw, 3.0 * math.sin(th)), 0.01] for s in (-1, 1)]
                       + [[r_hi * math.cos(th), s * min(hw, r_hi * math.sin(th)), 0.01] for s in (-1, 1)]
                       + [[r_hi, 0, 0.01]])
    sc = Scene(posts=corners, half_angle_deg=c.half_angle_deg)
    pl = tier1.plan(sc, c.f_max, c.duration_s, listeners=stage_listeners(c, target))
    cells = pl["grid"].nx * pl["grid"].ny
    return {"half_angle_deg": c.half_angle_deg, "f_max": c.f_max, "dx_m": pl["dx"], "dt_s": pl["dt"],
            "grid": [pl["grid"].nx, pl["grid"].ny], "n_steps": pl["n_steps"], "cell_steps": float(cells * pl["n_steps"]),
            "est_wall_s_idle_8_threads": float(cells * pl["n_steps"] / TIER1_CELL_STEPS_PER_S)}


def wedge_for_budget(cfg, target, budget_s=TIER1_BUDGET_S, lo=1.0, hi=20.0):
    """Widest half-angle (0.5 deg steps) whose planned Tier 1 run fits the budget; None if even `lo` does not."""
    best = None
    for ha in np.arange(lo, hi + 1e-9, 0.5):
        p = tier1_plan(cfg, target, float(ha))
        if p["est_wall_s_idle_8_threads"] <= budget_s:
            best = p
        else:
            break
    return best


# ------------------------------------------------------------------------------------------------------ ablations
ABLATION_KEYS = ("flat_clap", "signed", "flat_scatter")
COMBOS = [dict(zip(ABLATION_KEYS, bits)) for bits in
          [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1)]]
ABL_STEPS = 500
ABL_LR = 0.05
ABL_WIENER_LAMBDA = 1e-4  # Wiener init regularization, relative to the peak of sum_k |C_k W V|^2
SHOT_MASS = None  # per target: number of equivalent posts for the shot-noise column (set from POSTS_PER_100MS)
SHOT_SEEDS = (1, 2, 3)


def combo_name(cb):
    off = [k for k in ABLATION_KEYS if cb[k]]
    return "baseline (all constraints)" if not off else ("ceiling (none)" if len(off) == 3 else "removed: " + "+".join(off))


def flat_clap_spectrum(n_fft, K):
    """Ideal flat clap: a constant spectrum A (the transfer is already masked to 500-4000 Hz with the raised-cosine
    edges of echo.tier0.band_mask), with A set so that the band-limited delta irfft(A * mask) has peak 1 (the claps
    are peak-normalized). Returns ([K, F] complex, the band-limited time signal)."""
    from echo.tier0 import band_mask

    f = np.fft.rfftfreq(n_fft, 1.0 / FS)
    x = np.fft.irfft(band_mask(f, BAND[0], BAND[1]), n_fft)
    A = 1.0 / np.max(np.abs(x))
    return torch.full((K, len(f)), A, dtype=torch.complex128), x * A


def scatter_weight(n_fft, a_ref, flat):
    f = np.fft.rfftfreq(n_fft, 1.0 / FS)
    if not flat:
        return torch.ones(len(f), dtype=torch.float64)
    T = np.abs(cylinder_response(a_ref, np.maximum(f, 1.0)))
    w = np.abs(cylinder_response(a_ref, 2500.0)) / T
    w[f < 0.5 * BAND[0]] = 0.0
    return torch.as_tensor(w, dtype=torch.float64)


class AblationModel:
    """E_k = irfft(C_k * W * H_profile) on a fixed grid; differentiable in the profile."""

    def __init__(self, target_audio, claps, *, flat_clap, flat_scatter, a_ref=0.01, r0=R0_PROFILE, dr=DR_PROFILE):
        self.audio = np.asarray(target_audio, float)
        self.claps = np.atleast_2d(claps)
        K, n_clap = self.claps.shape
        self.r0, self.dr, self.a_ref = r0, dr, a_ref
        dur = len(self.audio) / FS
        self.n_rho = int(round(C0 * dur / 2.0 / dr)) + 1
        self.n0, self.n_win = echo_window(r0, dur, n_clap, C0)
        self.n_out = self.n0 + self.n_win + 16
        self.n_fft = choose_n_fft(self.n_out, 2 * (r0 + self.n_rho * dr) / C0, n_clap)
        self.scene = Scene()
        if flat_clap:
            self.Cf, self.flat_clap_signal = flat_clap_spectrum(self.n_fft, K)
        else:
            self.Cf = torch.fft.rfft(torch.as_tensor(self.claps), n=self.n_fft, dim=-1)
        self.W = scatter_weight(self.n_fft, a_ref, flat_scatter)
        tgt = np.zeros(self.n_win)
        tgt[: len(self.audio)] = self.audio[: self.n_win]
        self.tgt = torch.as_tensor(band_limit(tgt, BAND[0], BAND[1]))

    def echo(self, p):
        p = p if isinstance(p, torch.Tensor) else torch.as_tensor(np.asarray(p, float))
        H = profile_transfer(p, self.scene, mode="2d", n_fft=self.n_fft, a_ref=self.a_ref, r0=self.r0, dr=self.dr,
                             band=BAND)
        return torch.fft.irfft(self.Cf * (H * self.W)[None], n=self.n_fft, dim=-1)[:, : self.n_out]

    def wiener_init(self, lam=ABL_WIENER_LAMBDA):
        """Signed profile whose echo approximates the target: Wiener deconvolution of the target by the family's
        clap x scatterer x on-axis transfer (taken at the middle bin, delay removed), laid out along range and
        spreading-compensated (rho / rho_mid)."""
        i_mid = self.n_rho // 2
        e = np.zeros(self.n_rho)
        e[i_mid] = 1.0
        H = profile_transfer(torch.as_tensor(e), self.scene, mode="2d", n_fft=self.n_fft, a_ref=self.a_ref, r0=self.r0,
                             dr=self.dr, band=BAND).numpy()
        f = np.fft.rfftfreq(self.n_fft, 1.0 / FS)
        rho_mid = self.r0 + i_mid * self.dr
        V = H * np.exp(1j * 2 * np.pi * f * 2 * rho_mid / C0) * self.W.numpy()
        G = self.Cf.numpy() * V[None]  # [K, F]
        T = np.fft.rfft(np.pad(self.tgt.numpy(), (0, self.n_fft - self.n_win)))
        den = np.sum(np.abs(G) ** 2, 0)
        Q = np.sum(np.conj(G), 0) * T / (den + lam * den.max())
        q = np.fft.irfft(Q, self.n_fft)  # profile as a function of echo time t = 2 (rho - r0) / c
        t_bins = 2 * np.arange(self.n_rho) * self.dr / C0
        s = np.interp(t_bins, np.arange(self.n_fft) / FS, q)
        rho = self.r0 + np.arange(self.n_rho) * self.dr
        return s * rho / rho_mid


def positive_from_signed(s):
    """Bias + signal: s plus its smoothed envelope (4 ms), floored at 2 % of the peak (as echo.inverse.initial_profile)."""
    from scipy.ndimage import uniform_filter1d
    from scipy.signal import hilbert

    env = uniform_filter1d(np.abs(hilbert(s)), size=max(1, int(0.004 * C0 / 2 / DR_PROFILE)))
    env = np.maximum(env, np.abs(s))
    p = np.maximum(env + s, 0.0)
    return p + 0.02 * p.max()


def solve_ablation(model: AblationModel, signed, init, steps=ABL_STEPS, lr=ABL_LR):
    """Adam on the profile (softplus or identity parameterization), loss = EchoLoss over 500-4000 Hz on the echo
    window, mean over the clap rows. Returns (best profile normalized to mean |p| = 1, best loss, loss history)."""
    loss_fn = EchoLoss(BAND, n_win=model.n_win)
    p0 = np.asarray(init, float)
    p0 = p0 / np.mean(np.abs(p0))
    if signed:
        theta = torch.as_tensor(p0, dtype=torch.float64).requires_grad_(True)
        param = lambda th: th  # noqa: E731
    else:
        theta = torch.as_tensor(np.log(np.expm1(np.maximum(p0, 1e-4))), dtype=torch.float64).requires_grad_(True)
        param = F.softplus
    opt = torch.optim.Adam([theta], lr=lr)
    best, hist = (np.inf, None), []
    for it in range(steps + 1):
        p = param(theta)
        e = model.echo(p)
        loss, _, _ = loss_fn(e[:, model.n0:model.n0 + model.n_win], model.tgt)
        lv = float(loss.detach())
        if lv < best[0]:
            best = (lv, p.detach().numpy().copy())
        if it % 50 == 0 or it == steps:
            hist.append([it, lv])
        if it == steps:
            break
        opt.zero_grad()
        loss.backward()
        opt.step()
    p = best[1] / np.mean(np.abs(best[1]))
    return p, best[0], hist


def band_energy_db(x, lo, hi, fs=FS):
    X = np.abs(np.fft.rfft(x, axis=-1)) ** 2
    f = np.fft.rfftfreq(x.shape[-1], 1.0 / fs)
    a = X[..., (f >= lo) & (f < hi)].sum(-1)
    b = X[..., (f >= BAND[0]) & (f <= BAND[1])].sum(-1)
    return 10 * np.log10(a / b + 1e-30)


def judge_info(judge_stage, echo, target, t0):
    """Informational judge values (never used to choose): per-clap list and means."""
    import echo.metrics_speech as _ms  # noqa: F401  (registers stage 4)
    from echo.metrics import stage_values

    v = stage_values(judge_stage, echo, target, t0)
    out = {"mean": {k: float(np.mean([float(x[k]) for x in v])) for k in v[0]},
           "per_clap": [{k: float(x[k]) for k in x} for x in v]}
    if judge_stage == "s4c_word":
        out["recognized_text"] = _ms.recognized_text(echo_segment(np.atleast_2d(echo), t0, len(target.audio)))
        out["hello_count"] = int(sum(r["hit"] for r in out["recognized_text"]))
    return out


def shot_noise_loss(model, p, mass, seeds=SHOT_SEEDS):
    """Loss of the profile echo when the profile is built from `mass` discrete unit reflectors placed at random
    (Poisson counts per bin, sign kept for signed profiles): the shot noise of a finite post count."""
    q = np.abs(p) / np.sum(np.abs(p)) * mass
    ls = []
    for sd in seeds:
        rng = np.random.default_rng(sd)
        n = rng.poisson(q) * np.sign(p)
        e = model.echo(torch.as_tensor(n.astype(float))).detach().numpy()
        ls.append(window_loss(e, model.audio, BAND, model.r0, C0, model.claps.shape[1]))
    return float(np.mean(ls))


def run_ablations(name, judge_stage, steps=ABL_STEPS, radii_extra=(0.02, 0.04), log=print,
                  init_names=("physics", "wiener")):
    """All 8 constraint combinations (plus larger reference radii with all constraints on) for one target."""
    torch.manual_seed(SEED)
    target = target_of(name)
    claps = clap_family(5, seed=SEED)
    mass = POSTS_PER_100MS * len(target.audio) / FS / 0.1
    rows = []
    t_all = time.time()
    plan = [(cb, 0.01) for cb in COMBOS] + [(COMBOS[0], a) for a in radii_extra]
    for cb, a_ref in plan:
        t = time.time()
        model = AblationModel(target.audio, claps, flat_clap=bool(cb["flat_clap"]), flat_scatter=bool(cb["flat_scatter"]),
                              a_ref=a_ref)
        inits = {}
        if "physics" in init_names:
            inits["physics"] = initial_profile(target.audio, model.n_rho, model.r0, model.dr, C0)
        if "wiener" in init_names:
            w = model.wiener_init()
            inits["wiener"] = w if cb["signed"] else positive_from_signed(w)
        sols = {}
        for k, p0 in inits.items():
            sols[k] = solve_ablation(model, bool(cb["signed"]), p0, steps=steps)
        pick = min(sols, key=lambda k: sols[k][1])
        p, loss, hist = sols[pick]
        e = model.echo(torch.as_tensor(p)).detach().numpy()
        t0 = model.n0 / FS
        seg = echo_segment(e, t0, len(target.audio))
        p_m = p / np.sum(np.abs(p)) * 1000.0  # 1000 equivalent reference posts
        e_m = model.echo(torch.as_tensor(p_m)).detach().numpy()
        row = {"combo": combo_name(cb), **{k: bool(v) for k, v in cb.items()}, "a_ref_m": a_ref,
               "loss": window_loss(e, target.audio, BAND, model.r0, C0, claps.shape[1]),
               "loss_solver_best": loss, "init_picked": pick,
               "loss_by_init": {k: v[1] for k, v in sols.items()},
               "loss_clap_band_info": window_loss(e, target.audio, CLAP_BAND, model.r0, C0, claps.shape[1]),
               "loss_shot_noise": shot_noise_loss(model, p, mass),
               "shot_noise_posts": mass,
               "level_db_2d_per_1000_posts": float(np.mean(echo_level_db(e_m))),
               "low_band_500_1000_db_re_target": float(np.mean(band_energy_db(seg, 500, 1000)
                                                               - band_energy_db(target.audio, 500, 1000))),
               "negative_mass_fraction": float(np.sum(np.clip(-p, 0, None)) / np.sum(np.abs(p))),
               "history": hist,
               "info_only_judges": judge_info(judge_stage, e, target, t0),
               "wall_s": time.time() - t}
        rows.append(row)
        log(f"[{name}] {row['combo']:<36} a={a_ref:.2f} loss {row['loss']:.3f} (init {pick}; "
            f"{', '.join(f'{k} {v:.3f}' for k, v in row['loss_by_init'].items())}) shot {row['loss_shot_noise']:.3f} "
            f"L2d/1000 {row['level_db_2d_per_1000_posts']:.1f} dB lowband {row['low_band_500_1000_db_re_target']:+.1f} dB "
            f"[info {fmt_judges(row['info_only_judges'])}] {row['wall_s']:.0f} s")
    out = {"target": name, "judge_stage": judge_stage, "band_hz": list(BAND), "steps": steps, "lr": ABL_LR,
           "inits": list(init_names), "radii_extra_m": list(radii_extra),
           "model": "E_k = irfft(C_k * W * profile_transfer(profile)) (2D, Tier 0 profile model, on-axis)",
           "ablations": {"flat_clap": "ideal flat-spectrum clap: band-limited delta 500-4000 Hz, peak 1 (one shape, "
                                      "all 5 rows identical)",
                         "signed": "signed reflectivity allowed (identity parameterization instead of softplus)",
                         "flat_scatter": "frequency-flat scatterers: transfer divided by |T_1cm(f)| / |T_1cm(2.5 kHz)|"},
           "selection": "per combination: lower final EchoLoss (500-4000 Hz) of two inits; judges informational only",
           "rows": rows, "attribution": attribute(rows), "wall_s": time.time() - t_all}
    return out


def fmt_judges(j):
    m = j["mean"]
    keys = [k for k in ("formant_err_pct", "f1_err_pct", "f2_err_pct", "closed_set_correct", "closed_set_margin", "estoi",
                        "hello_hit") if k in m]
    s = " ".join(f"{k} {m[k]:.2f}" for k in keys)
    if "hello_count" in j:
        s += f" hello {j['hello_count']}/5"
    return s


def attribute(rows):
    """Attribution of the baseline-to-ceiling loss to the three constraints (1 cm rows only): the gain of removing each
    constraint alone from the baseline, and the cost of restoring each alone onto the ceiling."""
    by = {(r["flat_clap"], r["signed"], r["flat_scatter"]): r for r in rows if r["a_ref_m"] == 0.01}
    base, ceil = by[(False, False, False)], by[(True, True, True)]
    out = {"baseline_loss": base["loss"], "ceiling_loss": ceil["loss"], "metric_columns": {}}
    names = {"flat_clap": "clap spectrum", "signed": "positivity", "flat_scatter": "small-post scattering"}
    for col in ("loss", "loss_shot_noise", "low_band_500_1000_db_re_target"):
        d = {}
        for i, k in enumerate(ABLATION_KEYS):
            rm = tuple(j == i for j in range(3))
            only = tuple(j != i for j in range(3))
            d[names[k]] = {"gain_when_removed_alone": base[col] - by[rm][col],
                           "cost_when_restored_alone_on_ceiling": by[only][col] - ceil[col]}
        out["metric_columns"][col] = d
    jcols = {}
    for k in base["info_only_judges"]["mean"]:
        jcols[k] = {combo: by[key]["info_only_judges"]["mean"][k] for key, combo in
                    [(kk, by[kk]["combo"]) for kk in by]}
    out["info_only_judge_means_by_combo"] = jcols
    d = out["metric_columns"]["loss"]
    out["largest_single_cost_by_loss"] = max(d, key=lambda k: max(d[k]["gain_when_removed_alone"],
                                                                  d[k]["cost_when_restored_alone_on_ceiling"]))
    return out


# --------------------------------------------------------------------------------------- realization comparison
JITTER_M = (0.001, 0.002)
JITTER_SEEDS = (11, 12, 13)


def radial_jitter(posts, sigma, seed):
    p = np.array(posts, dtype=float)
    rng = np.random.default_rng(seed)
    u = p[:, :2] / np.linalg.norm(p[:, :2], axis=1, keepdims=True)
    p[:, :2] += u * rng.normal(0.0, sigma, size=(len(p), 1))
    return p


def _place(rhos, cfg, seed):
    from echo.realize import place_on_arcs

    rng = np.random.default_rng(seed)
    rads = np.full(len(rhos), cfg.a_ref)
    posts, viol, dropped = place_on_arcs(np.sort(rhos), rads, stage_scene(cfg), rng, r0=cfg.r0, dr=cfg.dr,
                                         radii=(cfg.a_ref,), shadow_depth=cfg.shadow_depth)
    return posts, {"n_posts": int(len(posts)), "dropped": int(dropped), "shadow_violations": int(viol)}


def realize_quantile(profile, n_posts, cfg, seed=SEED):
    """(iii) Deterministic quantile placement: post j at the range where the cumulative profile mass is (j + 1/2)/N."""
    p = np.clip(np.asarray(profile, float), 0, None)
    edges = cfg.r0 + (np.arange(len(p) + 1) - 0.5) * cfg.dr
    M = np.concatenate([[0.0], np.cumsum(p)])
    q = (np.arange(n_posts) + 0.5) / n_posts * M[-1]
    return _place(np.interp(q, M, edges), cfg, seed)


def realize_halfwave(profile, n_posts, cfg, band, seed=SEED):
    """(ii) Half-wave realization: band-pass the profile (range treated as echo time), keep its positive lobes; each
    lobe becomes one ring at its centroid with a post count proportional to its area (error diffusion), N in total."""
    fs_r = C0 / (2 * cfg.dr)  # profile samples per second of echo time
    s = band_limit(np.asarray(profile, float), band[0], band[1], fs=fs_r)
    pos = s > 0
    edges = np.flatnonzero(np.diff(np.concatenate([[0], pos.astype(int), [0]])))
    starts, ends = edges[::2], edges[1::2]
    rho = cfg.r0 + np.arange(len(s)) * cfg.dr
    areas = np.array([s[a:b].sum() for a, b in zip(starts, ends)])
    cents = np.array([np.sum(s[a:b] * rho[a:b]) / s[a:b].sum() for a, b in zip(starts, ends)])
    want = areas / areas.sum() * n_posts
    counts, acc = [], 0.0
    for w in want:
        acc += w
        k = int(round(acc))
        acc -= k
        counts.append(k)
    rhos = np.repeat(cents, counts)
    posts, st = _place(rhos, cfg, seed)
    st["n_lobes"] = int(len(areas))
    return posts, st


def realization_study(name, sub, log=print):
    """Tier 0 comparison of the realizations of the driver's own solved profile at equal post count: (i) sampling
    (inverse CDF + range polish, the driver's 'sampling' mode), (ii) phase-locked K=1 (the driver's mode: rings at the
    analytic-phase peaks of the band-passed profile), (ii-b) half-wave lobes, (iii) deterministic quantile placement.
    Chosen by the Tier 0 spectrogram loss and its mean under 1-2 mm radial jitter only."""
    from echo.inverse import solve_profile
    from echo.realize import realize, scale_profile

    torch.set_num_threads(int(os.environ.get("S4_THREADS", "4")))
    cfg = make_config(sub, name)
    target = target_of(name)
    claps = clap_family(5, seed=SEED)
    cl = torch.as_tensor(claps)
    n_out = int(round(cfg.duration_s * FS))
    band = (BAND[0], min(BAND[1], cfg.f_max))
    t_all = time.time()
    prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref, steps=cfg.steps,
                                lr=cfg.lr, n_out=n_out, band=band)
    log(f"[{name}] profile solve loss {res.info['init_loss']:.3f} -> {res.info['best_loss']:.3f} "
        f"({res.history['wall_s']:.0f} s)")
    prof = scale_profile(prof_n, cfg.target_fill, cfg.r0, cfg.dr, cfg.a_ref, half_angle_deg=cfg.half_angle_deg)
    n_posts = int(round(prof.sum()))
    t0 = res.n0 / FS
    rows = []

    def evaluate(label, posts, st):
        sc = stage_scene(cfg, posts)
        e2 = post_echo(posts, cl, sc, mode="2d", n_out=n_out, band=band).numpy()
        e3 = post_echo(posts, cl, sc, mode="3d", n_out=n_out, band=band).numpy()
        r = {"label": label, **st, "fill_realized": float(fill_fraction(sc)),
             "loss": window_loss(e2, target.audio, band, cfg.r0, C0, claps.shape[1]),
             "echo_level_db_3d": float(np.mean(echo_level_db(e3))),
             "echo_level_db_2d": float(np.mean(echo_level_db(e2)))}
        jit = []
        for sig in JITTER_M:
            ls = []
            for sd in JITTER_SEEDS:
                ej = post_echo(radial_jitter(posts, sig, sd), cl, sc, mode="2d", n_out=n_out, band=band).numpy()
                ls.append(window_loss(ej, target.audio, band, cfg.r0, C0, claps.shape[1]))
            jit.append({"sigma_m": sig, "loss_mean": float(np.mean(ls))})
        r["jitter"] = jit
        r["loss_jitter_mean"] = float(np.mean([j["loss_mean"] for j in jit]))
        r["info_only_judges"] = judge_info(SUBSTAGES[sub]["judge"], e2, target, t0)
        rows.append(r)
        log(f"[{name}] {label:<28} N={r['n_posts']:5d} loss {r['loss']:.3f} jit1/2mm "
            f"{jit[0]['loss_mean']:.3f}/{jit[1]['loss_mean']:.3f} L3d {r['echo_level_db_3d']:.1f} "
            f"[info {fmt_judges(r['info_only_judges'])}]")

    # profile echo itself (the model the solve sees), at the same scale
    from echo.tier0 import profile_echo

    ep = profile_echo(torch.as_tensor(prof), cl, stage_scene(cfg), mode="2d", n_out=n_out, a_ref=cfg.a_ref, r0=cfg.r0,
                      dr=cfg.dr, band=band).numpy()
    prof_row = {"label": "profile (continuous model)", "loss": window_loss(ep, target.audio, band, cfg.r0, C0, 128),
                "echo_level_db_2d": float(np.mean(echo_level_db(ep))),
                "info_only_judges": judge_info(SUBSTAGES[sub]["judge"], ep, target, t0)}
    log(f"[{name}] profile echo loss {prof_row['loss']:.3f} [info {fmt_judges(prof_row['info_only_judges'])}]")
    for mode, K, label in (("sampling", 1, "(i) sampling"), ("phase_locked", 1, "(ii) phase-locked K=1")):
        posts, st = realize(prof, stage_scene(cfg), cfg.seed, r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref, radii=(cfg.a_ref,),
                            band=band, shadow_depth=cfg.shadow_depth, claps=claps,
                            refine_steps=cfg.refine_steps if mode == "sampling" else 0, mode=mode, posts_per_period=K)
        evaluate(label, posts, {k: st[k] for k in ("n_posts", "dropped", "shadow_violations")})
    posts, st = realize_halfwave(prof, n_posts, cfg, band)
    evaluate("(ii-b) half-wave lobes", posts, st)
    posts, st = realize_quantile(prof, n_posts, cfg)
    evaluate("(iii) quantile (deterministic)", posts, st)
    pick = min(rows, key=lambda r: r["loss_jitter_mean"])
    out = {"target": name, "substage": sub, "half_angle_deg": cfg.half_angle_deg, "band_hz": list(band),
           "fill_target": cfg.target_fill, "n_posts_requested": n_posts, "a_ref_m": cfg.a_ref,
           "selection": "lowest mean Tier 0 spectrogram loss under 1 and 2 mm radial jitter (3 seeds); judges info only",
           "solve": {"init_loss": res.info["init_loss"], "best_loss": res.info["best_loss"], "steps": cfg.steps,
                     "wall_s": res.history["wall_s"]},
           "profile_row": prof_row, "rows": rows, "picked": pick["label"], "wall_s": time.time() - t_all}
    return out


def count_sweep(name, sub, counts=(1500, 5000, 15000), radii=(0.01, 0.04), log=print):
    """Tier 0: loss of the driver's solved profile realized by deterministic quantile placement at several post
    counts and radii (1 cm: Rayleigh-weak; 4 cm: 12 dB stronger at 1 kHz), to separate realization (count) noise
    from the profile's own loss. Same selection rule (loss only); judges informational."""
    from echo.inverse import solve_profile
    from echo.realize import scale_profile
    from echo.tier0 import profile_echo

    cfg0 = make_config(sub, name)
    target = target_of(name)
    claps = clap_family(5, seed=SEED)
    cl = torch.as_tensor(claps)
    n_out = int(round(cfg0.duration_s * FS))
    band = (BAND[0], min(BAND[1], cfg0.f_max))
    rows = []
    for a in radii:
        cfg = replace(cfg0, a_ref=a, catalog=(a,))
        prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=a, steps=cfg.steps,
                                    lr=cfg.lr, n_out=n_out, band=band)
        t0 = res.n0 / FS
        ep = profile_echo(torch.as_tensor(prof_n), cl, stage_scene(cfg), mode="2d", n_out=n_out, a_ref=a, r0=cfg.r0,
                          dr=cfg.dr, band=band).numpy()
        lp = window_loss(ep, target.audio, band, cfg.r0, C0, 128)
        log(f"[{name}] a={a} profile loss {lp:.3f}")
        for n in counts:
            prof = prof_n / prof_n.sum() * n
            posts, st = realize_quantile(prof, n, cfg)
            sc = stage_scene(cfg, posts)
            e2 = post_echo(posts, cl, sc, mode="2d", n_out=n_out, band=band).numpy()
            e3 = post_echo(posts, cl, sc, mode="3d", n_out=n_out, band=band).numpy()
            r = {"a_ref_m": a, "n_requested": n, **st, "fill_realized": float(fill_fraction(sc)),
                 "profile_loss": lp, "loss": window_loss(e2, target.audio, band, cfg.r0, C0, 128),
                 "echo_level_db_3d": float(np.mean(echo_level_db(e3))),
                 "info_only_judges": judge_info(SUBSTAGES[sub]["judge"], e2, target, t0)}
            rows.append(r)
            log(f"[{name}] a={a} N={r['n_posts']} (drop {r['dropped']}) fill {r['fill_realized']:.4f} loss "
                f"{r['loss']:.3f} L3d {r['echo_level_db_3d']:.1f} [info {fmt_judges(r['info_only_judges'])}]")
    return {"target": name, "half_angle_deg": cfg0.half_angle_deg, "band_hz": list(band), "rows": rows,
            "realization": "(iii) deterministic quantile placement", "note": "Tier 0 ignores multiple scattering: "
            "high fill rows are optimistic (stage 1: 4 cm at 2.3 % fill had nothing in common with Tier 1)"}


def scattering_width(a, f, c=C0):
    """Total scattering width (m) of a rigid cylinder, plane wave: sigma = (4/k) sum_n eps_n |A_n|^2, from the
    partial-wave series of echo.tier0. Thin limit (hand check in tests): 3 pi^2 k^3 a^4 / 4."""
    from echo.tier0 import _n_terms, _partial_wave_coeffs

    k = 2 * np.pi * np.asarray(f, float) / c
    ka = k * a
    cn = _partial_wave_coeffs(ka, _n_terms(float(np.max(ka))))  # eps_n A_n
    eps = np.where(np.arange(cn.shape[-1]) == 0, 1.0, 2.0)
    return 4.0 / k * np.sum(np.abs(cn) ** 2 / eps, axis=-1)


def predicted_extinction(posts, scene_half_angle_deg=None, freqs=(1000.0, 2000.0, 4000.0), max_half_width_m=None,
                         drho=0.5, source=(0.0, 0.0), listener=(0.0, 0.3)):
    """Two-way coherent extinction along range from Tier 0's cylinder model (single-scattering estimate):
    tau(rho, f) = 2 int_0^rho n_A sigma(f) drho', n_A = posts per metre of range / lateral width of the field at that
    range (wedge arc 2 rho tan(half-angle), or the strip width if clipped); loss in dB = 4.343 tau (intensity).
    Returns {freqs_hz, rho_m[], extinction_db[f][], far_end_db{f}}."""
    from echo.scene import bistatic_range

    P = np.asarray(posts, float)
    rho = bistatic_range(P[:, :2], np.asarray(source), np.asarray(listener))
    edges = np.arange(np.floor(rho.min()), rho.max() + drho, drho)
    cnt, _ = np.histogram(rho, edges)
    rc = 0.5 * (edges[1:] + edges[:-1])
    if max_half_width_m is None:
        # lateral extent actually occupied by the posts in each range bin (at least 2 x 5 cm)
        width = np.array([max(0.1, np.ptp(P[(rho >= lo) & (rho < hi), 1]) if np.sum((rho >= lo) & (rho < hi)) > 1
                              else 0.1) for lo, hi in zip(edges[:-1], edges[1:])])
    else:
        width = np.minimum(2 * max_half_width_m, 2 * rc * np.tan(np.radians(scene_half_angle_deg or 20.0)))
    nA = cnt / drho / width
    out = {"freqs_hz": list(freqs), "rho_m": rc.tolist(), "extinction_db": {}, "far_end_db": {},
           "lateral_width_m": width.tolist(), "radius_m": float(np.median(P[:, 2])),
           "model": "4.343 x 2 int n_A sigma drho; sigma = total scattering width (partial waves); lateral width = "
                    "occupied post extent per 0.5 m range bin; single-scattering estimate"}
    for f in freqs:
        sig = scattering_width(float(np.median(P[:, 2])), f)
        tau = 2 * np.cumsum(nA * sig * drho)
        out["extinction_db"][str(int(f))] = (4.343 * tau).tolist()
        out["far_end_db"][str(int(f))] = float(4.343 * tau[-1])
    return out


def measured_extinction(e1, e0, t_echo0, win_s=0.02, fs=FS):
    """Tier 1 / Tier 0 level ratio per window along the echo (same posts): the measured tier gap vs echo time."""
    n0, w = int(t_echo0 * fs), int(win_s * fs)
    e1, e0 = np.atleast_2d(e1), np.atleast_2d(e0)
    rows = []
    i = n0
    while i + w <= e0.shape[-1]:
        a, b = np.sum(e1[:, i:i + w] ** 2), np.sum(e0[:, i:i + w] ** 2)
        if b > 1e-3 * np.max(np.sum(e0[:, n0:].reshape(e0.shape[0], -1) ** 2) / max(1, (e0.shape[-1] - n0) // w)):
            rows.append({"t_s": (i + w / 2) / fs, "rho_m": C0 * (i + w / 2) / fs / 2, "gap_db": float(10 * np.log10(a / b))})
        i += w
    return rows


# ----------------------------------------------------------------------------------------------- Tier 1 / driver
def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    export.write_json(path, obj, indent=1)


def load_study(kind, name):
    fp = STUDY_DIR / f"{kind}_{name}.json"
    return json.loads(fp.read_text()) if fp.exists() else None


def free_robustness(cfg, target, claps, band, des, t1_res, hooks, t_echo0):
    """The robustness cases that need no extra Tier 1 run: listener offsets (extra sensors of the same run) and each
    clap variant on its own. Speed-of-sound and jitter cases are recorded as not run (cost)."""
    from echo import metrics as M
    from echo.robustness import LISTENER_OFFSETS, case, listener_shift_s

    def vals(e, t0):
        return M.stage_values(cfg.stage, e, target, t0, FS, band)

    def e1(li):
        return band_limit(hooks.echoes(t1_res, claps, listener=li), band[0], band[1])

    def t0e(sc):
        return post_echo(sc.posts, torch.as_tensor(claps), sc, mode="2d", n_out=int(round(cfg.duration_s * FS)),
                         band=band).numpy()

    sc = des.scene
    pc_nom = vals(e1(0), t_echo0)
    nominal = {k: float(np.mean([float(v[k]) for v in pc_nom])) for k in pc_nom[0]}
    pc0 = vals(t0e(sc), t_echo0)
    cases = [case(cfg.stage, "nominal", "Nominal design", pc_nom, nominal, pc0)]
    rho_mid = cfg.r0 + C0 * len(target.audio) / FS / 4.0
    for li, (name, (off, label)) in enumerate(LISTENER_OFFSETS.items(), start=1):
        Ln = t1_res.listeners[li]
        sh = listener_shift_s(sc, Ln, rho_mid, sc.c)
        sc_l = Scene(source=sc.source, listener=Ln, posts=sc.posts, half_angle_deg=sc.half_angle_deg, r_min=sc.r_min,
                     c=sc.c)
        cases.append(case(cfg.stage, name, label, vals(e1(li), t_echo0 + sh), nominal, vals(t0e(sc_l), t_echo0 + sh),
                          listener=[float(v) for v in Ln], window_shift_ms=sh * 1e3))
    for k, pc in enumerate(pc_nom):
        cases.append(case(cfg.stage, f"clap_{k}", f"Clap variant {k} alone", [pc], nominal, [pc0[k]]))
    not_run = [{"case": "c_331", "label": "Speed of sound 331 m/s", "status": "not run (cost)"},
               {"case": "c_349", "label": "Speed of sound 349 m/s", "status": "not run (cost)"},
               {"case": "jitter", "label": "Posts jittered 5 mm, radii 1 mm", "status": "not run (cost)"}]
    return cases, not_run, [e1(li) for li in range(3)]


def run_one(sub, name, tier0_only=False, log=print, runs_root=None, half_angle=None, abl=None, study=None,
            overrides=None, verbose=True):
    """One sub-stage target through the shared driver, then: move to runs/s4_speech, sub-stage ids, free robustness,
    ablations and realization study in metrics, transcripts (4c), mechanism-level failure cause."""
    import echo.metrics_speech as MS
    from stages.common import Tier1Hooks, run_stage

    target = target_of(name)
    cfg = make_config(sub, name, **(overrides or {}))
    if half_angle is not None:
        cfg.half_angle_deg = float(half_angle)
        cfg.target_fill = fill_for_posts(cfg, target, cfg._n_posts)
    plan = tier1_plan(cfg, target)
    if tier0_only:
        cfg.field = False
    log(f"[{sub} {name}] half-angle {cfg.half_angle_deg} deg, f_max {cfg.f_max}, fill {cfg.target_fill:.4f} "
        f"(~{cfg._n_posts} posts), plan {plan}")
    results = []
    hooks = None
    if not tier0_only:
        hooks = Tier1Hooks().resolve()
        orig = hooks.run

        def rec(*a, **k):
            r = orig(*a, **k)
            results.append(r)
            return r

        hooks.run = rec
    tmp = Path(tempfile.mkdtemp(prefix="s4_", dir=str(export.ROOT / ".cache")))
    cmd = f"uv run python -m stages.s4_speech --only {sub}" + (" --tier0-only" if tier0_only else "")
    run_dir, des, res = run_stage(cfg, hooks, command=cmd, runs_root=tmp, verbose=verbose)
    dest_root = Path(runs_root or export.RUNS) / STAGE
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / run_dir.name
    shutil.move(str(run_dir), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    band = res.band
    t_echo0 = res.n0 / FS
    mf = json.loads((dest / "manifest.json").read_text())
    met = json.loads((dest / "metrics.json").read_text())
    mf.update({"stage": STAGE, "substage": sub, "judge_stage": cfg.stage, "target_name": name})
    met.update({"stage": STAGE, "substage": sub, "judge_stage": cfg.stage, "target_name": name})
    met["band_hz"] = list(band)
    met["tier1_plan"] = plan
    if not tier0_only and results:
        # the Tier 1 result of the final design: the run whose echo equals the exported one
        e_fin = des.echo_t1_2d
        t1_res = min(results, key=lambda r: float(np.abs(band_limit(hooks.echoes(r, claps, listener=0), band[0], band[1])
                                                         - e_fin).max()))
        cases, not_run, e_lis = free_robustness(cfg, target, claps, band, des, t1_res, hooks, t_echo0)
        from echo.robustness import fragile_rule, robust_summary

        met["robustness"] = cases
        met["robustness_not_run"] = not_run
        met["robustness_not_run_reason"] = ("each speed-of-sound or jitter case is one more full Tier 1 solve (~10 min "
                                            "under the machine-wide lock); stage 4's budget is 7 solves in total, "
                                            "spent on the designs")
        met["fragile"], met["fragile_reason"] = fragile_rule(cases)
        met["robust_summary"] = robust_summary(cases)
        met["tier1_solves"] = len(results)
        met["tier1_wall_s"] = [float(r.wall_s) for r in results]
        if cfg.stage == "s4c_word":
            met["recognized_text"] = MS.recognized_text(echo_segment(e_fin, t_echo0, len(target.audio)))
    if cfg.stage == "s4c_word":
        met["recognized_text_tier0"] = MS.recognized_text(echo_segment(des.echo_t0_2d, t_echo0, len(target.audio)))
        if cfg.f_max < BAND[1]:
            # what the 2.5 kHz referee cannot see: the same posts' Tier 0 echo over the full 500-4000 Hz band
            e_full = post_echo(des.posts, torch.as_tensor(claps), des.scene, mode="2d",
                               n_out=int(round(cfg.duration_s * FS)), band=BAND).numpy()
            met["tier0_full_band_info"] = {"band_hz": list(BAND), "judges": judge_info(cfg.stage, e_full, target,
                                                                                         t_echo0),
                                           "loss": window_loss(e_full, target.audio, BAND, cfg.r0, C0, 128)}
    ext = {"predicted": predicted_extinction(des.posts, cfg.half_angle_deg,
                                             max_half_width_m=getattr(cfg, "max_half_width_m", None))}
    if des.echo_t1_2d is not None:
        ext["measured_tier1_over_tier0_db"] = measured_extinction(des.echo_t1_2d, des.echo_t0_2d, t_echo0)
    met["design_study"] = {"extinction": ext, "full_wedge_level": full_wedge_level(cfg, des, claps, band,
                                                                                    met["headline"])}
    # per-clap echoes (Tier 1 if run, else Tier 0) for the 4b 3x3 closed-set table and the report
    sdir = Path(runs_root) / STAGE / "_studies" if runs_root else STUDY_DIR
    sdir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(sdir / f"echoes_{name}.npz",
                        tier0=des.echo_t0_2d, tier1=(des.echo_t1_2d if des.echo_t1_2d is not None else np.zeros(0)),
                        t_echo0=t_echo0, run_id=dest.name)
    abl = abl if abl is not None else load_study("ablations", name)
    study = study if study is not None else load_study("realization", name)
    met["ablations"] = abl
    met["realization_study"] = study
    met["failure_cause"] = failure_cause(met, abl) if not met.get("passed") else None
    if met.get("passed"):
        met["pass_weight"] = pass_weight(met)
    export.write_json(dest / "metrics.json", met, indent=1)
    export.write_json(dest / "manifest.json", mf, indent=1)
    export.update_index(runs_root or export.RUNS)
    log(f"[{sub} {name}] wrote {dest}: passed {met['passed']} verified {met['verified']}")
    return dest, met, des, res


def full_wedge_level(cfg, des, claps, band, headline, n_groups=12):
    """Unverified single-scattering estimate: Tier 0 3D level if every range band's posts were scaled to the full
    +-20 deg wedge at the same areal density (amplitude weight = wedge arc / occupied width, per range group)."""
    from echo.scene import bistatic_range

    hw = getattr(cfg, "max_half_width_m", None)
    P = np.asarray(des.posts)
    rho = bistatic_range(P[:, :2], des.scene.source, des.scene.listener)
    edges = np.quantile(rho, np.linspace(0, 1, n_groups + 1))
    n_out = int(round(cfg.duration_s * FS))
    tot = 0.0
    for i in range(n_groups):
        m = (rho >= edges[i]) & ((rho < edges[i + 1]) if i < n_groups - 1 else (rho <= edges[i + 1]))
        if not m.any():
            continue
        rc = float(np.mean(rho[m]))
        width = min(2 * hw, 2 * rc * math.tan(math.radians(cfg.half_angle_deg))) if hw else \
            2 * rc * math.tan(math.radians(cfg.half_angle_deg))
        wgt = 2 * rc * math.tan(math.radians(20.0)) / width
        tot = tot + wgt * post_echo(P[m], torch.as_tensor(claps), des.scene, mode="3d", n_out=n_out, band=band).numpy()
    raw = float(np.mean(echo_level_db(tot)))
    return {"echo_level_db_re_direct_3d_full_wedge_tier0": raw,
            "echo_level_db_re_direct_3d_as_simulated_tier0": headline.get("echo_level_db_re_direct_raw3d"),
            "label": "unverified single-scattering estimate (Tier 0, no extinction); ring populations scaled to the "
                     "full +-20 deg wedge at the same areal density"}


def _gating(met):
    return [m for m in met["metrics"] if m["gating"]]


def failure_cause(met, abl):
    """Mechanism-level failure statement with the separating numbers (ablations, Tier 0 vs Tier 1, stretch)."""
    parts = []
    lc = met.get("loss_chain") or {}
    if "realized_tier0" in lc:
        parts.append("MECHANISM: the profile model fits (loss %.2f) but realizing it with a finite number of weak 1 cm "
                     "posts raises the loss to %.2f on Tier 0%s; the clap spectrum is the largest of the three "
                     "ablated constraints (numbers below), none of which explains the realized error"
                     % (lc["profile_model"], lc["realized_tier0"],
                        "" if "realized_tier1" not in lc else
                        " and the full-wave field to %.2f (incoherent residue; see design_study.extinction)"
                        % lc["realized_tier1"]))
    fl = (met.get("judge_floor") or {}).get("mean") or {}
    for m in _gating(met):
        if not m["pass"]:
            f = fl.get(m["id"])
            v = "n/a (judge returned no value)" if m["value"] is None else f"{m['value']:.3g}"
            parts.append(f"Tier 1 {m['id']} = {v} vs {m['comparator']} {m['threshold']}"
                         + (f" (judge floor on a perfect echo {f:.3g})" if f is not None else ""))
    if not met.get("verified"):
        parts.append("not verified (no Tier 1 run)")
    t0 = {m["id"]: m["value"] for m in met["metrics"] if m["tier"] == "tier0"}
    if t0:
        parts.append("Tier 0 of the same posts: " + ", ".join(f"{k} {v:.3g}" for k, v in t0.items() if v is not None))
    tc = met.get("tier1_correction") or {}
    st = tc.get("stretch") or {}
    if st.get("final_measured") is not None:
        r0 = (tc.get("rounds") or [{}])[0]
        parts.append(f"stretch measured {st['final_measured'] * 100:+.3f} % (applied {st['final_applied'] * 100:+.3f} %, "
                     f"Tier1-vs-Tier0 corr after stretch {((r0.get('stretch_fit') or {}).get('corr') or float('nan')):.3f}), "
                     f"tier gap {met['headline'].get('tier_gap_db')} dB")
    if tc.get("rounds"):
        parts.append(f"Tier 1 spectrogram loss {tc['rounds'][tc.get('best_round', 0)]['loss']:.3f}")
    rs = met.get("realization_study")
    if rs and rs.get("profile_row"):
        best = min(rs["rows"], key=lambda r: r["loss"])
        parts.append(f"realization (Tier 0, {rs['target']}): continuous profile echo loss {rs['profile_row']['loss']:.3f} "
                     f"vs best realized {best['loss']:.3f} ({best['label']}, {best['n_posts']} posts): the discrete posts "
                     f"add more error than the profile's own fit")
    cs = met.get("count_sweep")
    if cs and cs.get("rows"):
        parts.append("count sweep (quantile, Tier 0, ah): " + ", ".join(
            f"{r['a_ref_m'] * 100:.0f} cm x {r['n_posts']}: {r['loss']:.2f}" for r in cs["rows"]))
    if abl and abl.get("attribution"):
        a = abl["attribution"]
        d = a["metric_columns"]["loss"]
        parts.append(f"ablations (Tier 0 profile model, loss 500-4000 Hz): baseline {a['baseline_loss']:.3f}, ceiling "
                     f"{a['ceiling_loss']:.3f}; removing alone: " + ", ".join(
                         f"{k} {v['gain_when_removed_alone']:+.3f}" for k, v in d.items())
                     + "; restoring alone onto the ceiling: " + ", ".join(
                         f"{k} {v['cost_when_restored_alone_on_ceiling']:+.3f}" for k, v in d.items())
                     + f"; largest single cost: {a['largest_single_cost_by_loss']}")
    return "; ".join(parts)


def pass_weight(met):
    return ("passed on Tier 1; weight: judges are lenient (see judge floor and controls in the report)")


def closed_set_table(names=("ma", "ba", "om"), study_dir=None):
    """4b: every syllable's echo (Tier 1 when run, per clap) scored against all three targets with the reviewed judge
    (echo.metrics_speech.closed_set: the echo is aligned to each candidate separately, so distances are label-free).
    Returns {distances[echo][target] (mean over claps), per_clap, correct_fraction, tier}."""
    import echo.metrics_speech as MS

    sd = Path(study_dir or STUDY_DIR)
    cands = {s: target_of(s).audio for s in names}
    out = {"distances": {}, "per_clap": {}, "correct_fraction": {}, "tier": {}, "run_id": {},
           "judge": "echo.metrics_speech.closed_set (DTW of mean-removed log-mel, 500-4000 Hz)"}
    for s in names:
        z = np.load(sd / f"echoes_{s}.npz")
        e = z["tier1"] if z["tier1"].size else z["tier0"]
        out["tier"][s] = "tier1" if z["tier1"].size else "tier0"
        out["run_id"][s] = str(z["run_id"])
        segs = echo_segment(np.atleast_2d(e), float(z["t_echo0"]), len(cands[s]))
        rows = [MS.closed_set(seg, s, cands) for seg in segs]
        out["per_clap"][s] = [{"distances": {k: float(v) for k, v in r["distances"].items()},
                               "correct": bool(r["correct"]), "margin": float(r["margin"])} for r in rows]
        out["distances"][s] = {c: float(np.mean([r["distances"][c] for r in rows])) for c in names}
        out["correct_fraction"][s] = float(np.mean([r["correct"] for r in rows]))
    return out


def latest_runs(runs_root=None):
    """target name -> newest run folder under runs/s4_speech (by run_id)."""
    out = {}
    for d in sorted((Path(runs_root or export.RUNS) / STAGE).glob("*-s4_4*")):
        if (d / "metrics.json").exists():
            out[d.name.rsplit("_", 1)[-1]] = d
    return out


def attach_studies(runs_root=None):
    """Re-attach the finished Tier 0 studies (ablations, realization, count sweep) to the newest run of each target
    and recompute its mechanism-level failure cause (studies may finish after the Tier 1 run)."""
    for name, d in latest_runs(runs_root).items():
        met = json.loads((d / "metrics.json").read_text())
        met["ablations"] = load_study("ablations", name)
        met["realization_study"] = load_study("realization", "ah") if name != "ah" and load_study(
            "realization", name) is None else load_study("realization", name)
        if name != "ah" and load_study("realization", name) is None:
            met["realization_study_note"] = "realization chosen on the 4a study (realization_ah.json), applied here"
        met["count_sweep"] = load_study("count_sweep", "ah")
        if not (met.get("design_study") or {}).get("extinction"):
            met.setdefault("design_study", {})["extinction"] = extinction_from_folder(d)
        met["loss_chain"] = loss_chain(d, name, met)
        met["failure_cause"] = failure_cause(met, met["ablations"]) if not met.get("passed") else None
        export.write_json(d / "metrics.json", met, indent=1)
        print("attached studies to", d)


def loss_chain(d, name, met):
    """Spectrogram loss at each step of the design chain (judge-free): profile model (the run's solve) -> realized
    posts on Tier 0 -> the same posts on Tier 1."""
    h = json.loads((Path(d) / "history.json").read_text())
    out = {"profile_model": float(min(h["phases"][0]["loss"]))}
    fz = STUDY_DIR / f"echoes_{name}.npz"
    if fz.exists():
        z = np.load(fz)
        if str(z["run_id"]) == Path(d).name:
            band = tuple(met.get("band_hz") or BAND)
            t = target_of(name)
            out["realized_tier0"] = window_loss(z["tier0"], t.audio, band, R0_PROFILE, C0, 128)
            if z["tier1"].size:
                out["realized_tier1"] = window_loss(z["tier1"], t.audio, band, R0_PROFILE, C0, 128)
    return out


def extinction_from_folder(d):
    """Predicted (Tier 0 cylinder model on the run's posts) and measured (Tier 1 / Tier 0 level per 20 ms window of
    the exported clap-0 echoes, wav gains undone) extinction for a finished run folder."""
    import soundfile as sf

    d = Path(d)
    sc = json.loads((d / "scene.json").read_text())
    man = json.loads((d / "manifest.json").read_text())
    posts = np.asarray(sc["posts"], float)
    out = {"predicted": predicted_extinction(posts, sc["wedge"]["half_angle_deg"])}
    g = man["audio"]["echo_gain_db"]
    if g.get("tier1") is not None:
        e1 = sf.read(d / "echo_tier1.wav")[0] / 10 ** (g["tier1"] / 20)
        e0 = sf.read(d / "echo_tier0.wav")[0] / 10 ** (g["tier0"] / 20)
        out["measured_tier1_over_tier0_db"] = measured_extinction(e1, e0, 2 * R0_PROFILE / C0)
        out["measured_note"] = "clap variant 0 only (exported wavs)"
    return out


def recognizer_controls(study_dir=None, seed=SEED):
    """4c weight check: what whisper returns for obviously wrong echoes of the same kind and level (it peak-normalizes,
    so level is matched by construction): the 4b "ma" and "ba" Tier 1 echoes, the 4c Tier 1 echo time-reversed, and the
    4c Tier 1 echo with its phase randomized (same magnitude spectrum, speech structure destroyed). ESTOI vs "hello"
    alongside. Judges only; nothing is selected by these numbers."""
    import echo.metrics_speech as MS

    sd = Path(study_dir or STUDY_DIR)
    hello = target_of("hello")
    n = len(hello.audio)

    def segs(name):
        z = np.load(sd / f"echoes_{name}.npz")
        e = z["tier1"] if z["tier1"].size else z["tier0"]
        return echo_segment(np.atleast_2d(e), float(z["t_echo0"]), len(target_of(name).audio)), str(z["run_id"])

    h, rid = segs("hello")
    rng = np.random.default_rng(seed)
    cases = {}
    for nm in ("ma", "ba"):
        try:
            x, r = segs(nm)
            cases[f"{nm}_tier1_echo"] = (x, r)
        except FileNotFoundError:
            pass
    cases["hello_tier1_time_reversed"] = (h[:, ::-1].copy(), rid)
    ph = []
    for x in h:
        X = np.fft.rfft(x)
        ph.append(np.fft.irfft(np.abs(X) * np.exp(2j * np.pi * rng.random(len(X))), len(x)))
    cases["hello_tier1_phase_randomized"] = (np.array(ph), rid)
    out = {"what": "whisper (same settings as the 4c judge) on wrong echoes; transcripts per clap variant", "cases": {}}
    for k, (x, r) in cases.items():
        rt = MS.recognized_text(x)
        xe = np.zeros((x.shape[0], n))
        xe[:, : min(n, x.shape[1])] = x[:, :n]
        out["cases"][k] = {"source_run": r, "recognized_text": rt, "hello_count": int(sum(t["hit"] for t in rt)),
                           "estoi_vs_hello_mean": float(np.mean([MS.estoi(e, hello.audio) for e in xe]))}
        print(k, out["cases"][k]["hello_count"], [t["transcript"] for t in rt], out["cases"][k]["estoi_vs_hello_mean"])
    return out


CONTROL_WORDS = ("yellow", "mellow", "halo")
CONTROL_DIR = export.ROOT / "artifacts" / "speech" / "control_words"


def control_target(word, wpm=195):
    """A 4c control word through the same espeak route and shaping chain as the stage-4 targets (en-us, `wpm` as
    "hello", resample to 16 kHz, crop to the voiced extent + 5 ms, 5 ms fades, band-limit 500-4000 Hz, peak 1). The
    raw espeak WAV is cached in artifacts/speech/control_words/raw/. The committed stage-4 targets are untouched."""
    from math import gcd

    import soundfile as sf
    from scipy.signal import resample_poly

    from echo.targets_speech import FADE_S, SpeechTarget, _voiced_extent, fade_window, synth_raw

    raw = CONTROL_DIR / "raw" / f"{word}.wav"
    src = "cache"
    if not raw.exists():
        synth_raw(word, wpm, raw)
        src = "espeak-ng"
    x, fs_raw = sf.read(raw, dtype="float64")
    g = gcd(FS, fs_raw)
    y = resample_poly(x, FS // g, fs_raw // g)
    i0, i1 = _voiced_extent(y, FS)
    pad = int(round(FADE_S * FS))
    y = y[max(0, i0 - pad): min(len(y), i1 + pad)]
    y = y * fade_window(len(y), FS)
    a = band_limit(y / np.max(np.abs(y)), BAND[0], BAND[1])
    a = a / np.max(np.abs(a))
    return SpeechTarget(name=word, audio=a, duration_s=len(a) / FS, f_top_hz=BAND[1], candidates={}, source=src)


def control_words(words=CONTROL_WORDS, log=print):
    """4c envelope control (fast model only, no Tier 1): each control word is designed with exactly the 4c pipeline
    and settings (stage driver, Tier 0 path: same profile-solve steps, realization, post budget, strip, band) and its
    Tier 0 echo is given to the unchanged recognizer for all five clap variants; "hello" itself is the reference row.
    Also the recognizer on each clean band-limited target. Informational; no threshold, judge or design choice."""
    import echo.metrics_speech as MS
    from stages.common import run_stage

    rows = {}
    for w in ("hello",) + tuple(words):
        t = target_of("hello") if w == "hello" else control_target(w)
        cfg = make_config("4c", "hello")
        cfg.make_target = (lambda tt=t: tt)
        cfg.duration_s = duration_for(t)
        cfg.target_fill = fill_for_posts(cfg, t, cfg._n_posts)
        cfg.field = False
        tmp = Path(tempfile.mkdtemp(prefix="s4c_", dir=str(export.ROOT / ".cache")))
        _, des, res = run_stage(cfg, None, command="control_words", verbose=False, runs_root=tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        segs = echo_segment(des.echo_t0_2d, res.n0 / FS, len(t.audio))
        rt = MS.recognized_text(segs)
        clean = MS.transcribe(t.audio)
        rows[w] = {"duration_s": len(t.audio) / FS, "source": getattr(t, "source", ""), "steps": cfg.steps,
                   "posts": int(len(des.posts)), "max_half_width_m": cfg.max_half_width_m, "band_hz": list(res.band),
                   "clean_target_transcript": clean, "tier0_recognized_text": rt,
                   "tier0_hello_count": int(sum(r["hit"] for r in rt)),
                   "tier0_transcripts": [r["transcript"] for r in rt],
                   "loss_tier0": window_loss(des.echo_t0_2d, t.audio, res.band, cfg.r0, C0, 128)}
        log(f"[control] {w}: clean '{clean}', Tier 0 echo -> {rows[w]['tier0_transcripts']} "
            f"(hello {rows[w]['tier0_hello_count']}/5), {rows[w]['posts']} posts, loss {rows[w]['loss_tier0']:.3f}")
    reading = control_reading(rows, words)
    return {"what": "4c envelope control: other two-syllable words designed with the 4c pipeline on Tier 0 (no Tier 1), "
                    "unchanged recognizer, 5 clap variants; reference row hello", "rows": rows,
            "settings": {"steps": rows["hello"]["steps"], "strip_half_width_m": rows["hello"]["max_half_width_m"],
                         "band_hz": rows["hello"]["band_hz"], "posts_target": make_config("4c", "hello")._n_posts,
                         "espeak": "en-us, 195 wpm (as hello), artifacts/speech/control_words/raw/"},
            "reading": reading}


def control_reading(rows, words=CONTROL_WORDS):
    """Plain reading of the other-word control from its rows (counts only)."""
    n_hello = sum(rows[w]["tier0_hello_count"] for w in words)
    own = sum(sum(rows[w]["clean_target_transcript"].lower().strip(" .!?") == t.lower().strip(" .!?")
                  for t in rows[w]["tier0_transcripts"]) for w in words)
    per = ", ".join(f"{w} {rows[w]['tier0_hello_count']}/5" for w in words)
    ref = rows["hello"]["tier0_hello_count"] if "hello" in rows else None
    if n_hello >= 3 * len(words):
        return (f"other words' echoes come back as \"hello\" ({n_hello}/{5 * len(words)}: {per}; hello itself {ref}/5): "
                "the 4c pass reflects envelope-level cueing, not the word")
    return (f"other two-syllable words designed the same way are mostly not heard as \"hello\" ({n_hello}/"
            f"{5 * len(words)}: {per}) while the hello design is ({ref}/5), so the recognizer hears more than the "
            f"two-syllable envelope and the 4c pass carries more weight; but the false-\"hello\" rate on these "
            f"degraded echoes is not zero ({n_hello}/{5 * len(words)}), and no control echo is heard as its own word "
            f"({own}/{5 * len(words)} clap-echoes match the clean target's transcript): the echoes keep word-level "
            "identity only weakly")


def attach_closed_set_table(dests):
    """Write the 3x3 table into each 4b run's metrics.json (closed_set_3x3) and the studies folder."""
    tab = closed_set_table(tuple(dests))
    _write_json(STUDY_DIR / "closed_set_3x3.json", tab)
    for s, d in dests.items():
        met = json.loads((Path(d) / "metrics.json").read_text())
        met["closed_set_3x3"] = tab
        export.write_json(Path(d) / "metrics.json", met, indent=1)
    return tab


# --------------------------------------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Stage 4: speech")
    ap.add_argument("--only", choices=list(SUBSTAGES), default=None)
    ap.add_argument("--tier0-only", action="store_true")
    ap.add_argument("--ablations-only", action="store_true")
    ap.add_argument("--study-only", action="store_true")
    ap.add_argument("--names", default=None, help="comma-separated target names (default: the sub-stage's)")
    ap.add_argument("--skip-studies", action="store_true", help="reuse _studies/*.json")
    ap.add_argument("--control-words-reattach", action="store_true", help="re-read saved control_words.json -> 4c run")
    ap.add_argument("--control-words", action="store_true", help="4c other-word envelope control (Tier 0) -> 4c run")
    ap.add_argument("--controls", action="store_true", help="4c recognizer controls -> the newest 4c run and exit")
    ap.add_argument("--closed-set", action="store_true", help="4b 3x3 closed-set table -> the newest 4b runs and exit")
    ap.add_argument("--attach", action="store_true", help="re-attach finished studies to the newest runs and exit")
    ap.add_argument("--count-sweep", action="store_true", help="Tier 0 post-count/radius sweep -> _studies/count_sweep_<name>.json")
    a = ap.parse_args(argv)
    torch.set_num_threads(int(os.environ.get("S4_THREADS", "4")))
    if a.attach:
        attach_studies()
        return
    if a.control_words or a.control_words_reattach:
        if a.control_words:
            cw = control_words()
        else:  # recompute the reading from the saved rows (no new designs) and attach
            cw = json.loads((STUDY_DIR / "control_words.json").read_text())
            cw["reading"] = control_reading(cw["rows"])
        _write_json(STUDY_DIR / "control_words.json", cw)
        d = latest_runs()["hello"]
        met = json.loads((d / "metrics.json").read_text())
        met.setdefault("controls", {})["other_words"] = cw
        export.write_json(d / "metrics.json", met, indent=1)
        print(cw["reading"])
        return
    if a.controls:
        rc = recognizer_controls()
        _write_json(STUDY_DIR / "recognizer_controls.json", rc)
        d = latest_runs()["hello"]
        met = json.loads((d / "metrics.json").read_text())
        met["recognizer_controls"] = rc
        export.write_json(d / "metrics.json", met, indent=1)
        return
    if a.closed_set:
        lr = latest_runs()
        attach_closed_set_table({k: lr[k] for k in ("ma", "ba", "om")})
        return
    subs = [a.only] if a.only else list(SUBSTAGES)
    for sub in subs:
        dests = {}
        names = a.names.split(",") if a.names else SUBSTAGES[sub]["names"]
        for name in names:
            if a.count_sweep:
                _write_json(STUDY_DIR / f"count_sweep_{name}.json", count_sweep(name, sub))
                continue
            if not a.skip_studies and not a.study_only:
                # ah: both inits and the radius rows; the longer targets use the Wiener init only (it won every 'ah'
                # combination by loss) and no radius rows, to fit the box on a shared CPU (logged in the json)
                full = name == "ah"
                _write_json(STUDY_DIR / f"ablations_{name}.json", run_ablations(
                    name, SUBSTAGES[sub]["judge"], radii_extra=(0.02, 0.04) if full else (),
                    init_names=("physics", "wiener") if full else ("wiener",)))
            if not a.skip_studies and not a.ablations_only:
                _write_json(STUDY_DIR / f"realization_{name}.json", realization_study(name, sub))
            if a.ablations_only or a.study_only:
                continue
            dests[name] = run_one(sub, name, tier0_only=a.tier0_only)[0]
        if sub == "4b" and not (a.ablations_only or a.study_only) and len(dests) == 3:
            attach_closed_set_table(dests)


if __name__ == "__main__":
    main()
