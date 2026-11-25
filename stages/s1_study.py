"""Stage 1 design study on Tier 0 (seconds per design, no Tier 1): sampling vs phase-locked realization at equal
post counts, radial-jitter sensitivity, and the listener sweet spot vs wedge half-angle.

    uv run python -m stages.s1_study            # writes runs/s1_bird/_studies/design_study_tier0.json

Selection rule (stated in the output): designs are compared by the Tier 0 spectrogram loss (echo.inverse.window_loss)
and its robustness to radial jitter. The judge values (pitch error, log-mel correlation) are recorded for information
only and never used to choose.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace

import numpy as np
import torch

from echo import export
from echo.clap import clap_family
from echo.inverse import solve_profile, window_loss
from echo.metrics import echo_level_db, stage_values
from echo.realize import realize
from echo.robustness import listener_shift_s
from echo.scene import FS, Scene
from echo.tier0 import post_echo
from stages.common import stage_scene
from stages.s1_bird import CONFIG

COUNTS = (300, 600, 1060, 2000)
MODES = (("sampling", 1), ("phase_locked", 1), ("phase_locked", 2))
JITTER_M = (0.001, 0.002, 0.005)
JITTER_SEEDS = (11, 12, 13)
HALF_ANGLES = (20.0, 10.0, 5.0)
LISTENER_OFFSETS = ((0.0, 0.0), (0.0, 0.1), (0.0, 0.25), (0.0, 0.5), (0.0, 1.0), (-0.5, 0.0), (-1.0, 0.0))
SELECTION = ("designs compared by Tier 0 spectrogram loss (window_loss) and its jitter robustness only; pitch error "
             "and log-mel correlation (judges) are recorded for information and never used to choose")


def radial_jitter(posts, sigma, seed, source=(0.0, 0.0)):
    """Move each post along its ray from the source by N(0, sigma) (range error), radius unchanged."""
    p = np.array(posts, dtype=float)
    rng = np.random.default_rng(seed)
    v = p[:, :2] - np.asarray(source)
    u = v / np.linalg.norm(v, axis=1, keepdims=True)
    p[:, :2] += u * rng.normal(0.0, sigma, size=(len(p), 1))
    return p


def _wave_corr(a, b):
    a, b = a - a.mean(-1, keepdims=True), b - b.mean(-1, keepdims=True)
    return float(np.mean((a * b).sum(-1) / np.sqrt((a * a).sum(-1) * (b * b).sum(-1))))


class Evaluator:
    def __init__(self, cfg, target, claps, band, t_echo0, n_out):
        self.cfg, self.target, self.claps, self.band, self.t0, self.n_out = cfg, target, claps, band, t_echo0, n_out
        self.cl = torch.as_tensor(claps)

    def echo(self, posts, scene, mode="2d"):
        return post_echo(posts, self.cl, scene, mode=mode, n_out=self.n_out, band=self.band).numpy()

    def seg(self, e, t0=None):
        n0 = int(round((self.t0 if t0 is None else t0) * FS))
        return e[:, n0:n0 + len(self.target.audio) + self.claps.shape[1]]

    def judges(self, e, t0=None):
        v = stage_values(self.cfg.stage, e, self.target, self.t0 if t0 is None else t0, band=self.band)
        return {k: float(np.mean([x[k] for x in v])) for k in ("pitch_err_pct", "spec_corr")}

    def loss(self, e, shift_s=0.0):
        if shift_s:
            e = np.roll(e, -int(round(shift_s * FS)), axis=-1)
        return window_loss(e, self.target.audio, self.band, self.cfg.r0, self.cfg.c if hasattr(self.cfg, "c") else 343.0,
                           self.claps.shape[1])


def design(cfg, prof_n, n_posts, mode, K, band, claps, half_angle=None, seed=None):
    c2 = cfg if half_angle is None else replace(cfg, half_angle_deg=half_angle)
    sc = stage_scene(c2)
    p = prof_n * (n_posts / prof_n.sum())
    t = time.time()
    posts, st = realize(p, sc, cfg.seed if seed is None else seed, r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                        radii=tuple(cfg.catalog), band=band, shadow_depth=cfg.shadow_depth, claps=claps,
                        refine_steps=cfg.refine_steps if mode == "sampling" else 0, mode=mode, posts_per_period=K,
                        n_posts=n_posts)
    return posts, st, stage_scene(c2, posts), time.time() - t


def main():
    torch.set_num_threads(8)
    cfg = CONFIG
    t_all = time.time()
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                                steps=cfg.steps, lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out)
    band = res.band
    ev = Evaluator(cfg, target, claps, band, res.n0 / FS, n_out)
    rows = []
    for N in COUNTS:
        for mode, K in MODES:
            posts, st, sc, t_real = design(cfg, prof_n, N, mode, K, band, claps)
            e2 = ev.echo(posts, sc)
            e3 = ev.echo(posts, sc, "3d")
            row = {"n_request": N, "mode": mode, "posts_per_period": K, "n_posts": int(len(posts)),
                   "dropped": st["dropped"], "shadow_violations": st["shadow_violations"],
                   "n_rings": st.get("n_rings"), "max_posts_per_ring": st.get("max_posts_per_ring"),
                   "realize_s": round(t_real, 2),
                   "loss_tier0": ev.loss(e2), "echo_level_db_2d": float(np.mean(echo_level_db(e2))),
                   "echo_level_db_3d": float(np.mean(echo_level_db(e3))),
                   "judges_tier0_info_only": ev.judges(e2), "jitter": []}
            s0 = ev.seg(e2)
            for sig in JITTER_M:
                acc = {"loss": [], "wave_corr": [], "spec_corr_info_only": [], "pitch_err_pct_info_only": []}
                for sd in JITTER_SEEDS:
                    pj = radial_jitter(posts, sig, sd)
                    ej = ev.echo(pj, stage_scene(cfg, pj))
                    j = ev.judges(ej)
                    acc["loss"].append(ev.loss(ej))
                    acc["wave_corr"].append(_wave_corr(ev.seg(ej), s0))
                    acc["spec_corr_info_only"].append(j["spec_corr"])
                    acc["pitch_err_pct_info_only"].append(j["pitch_err_pct"])
                row["jitter"].append({"sigma_m": sig, **{k: float(np.mean(v)) for k, v in acc.items()},
                                      "loss_max": float(np.max(acc["loss"]))})
            rows.append(row)
            jl = {f"{j['sigma_m'] * 1e3:.0f}mm": round(j["loss"], 3) for j in row["jitter"]}
            print(f"N={N:5d} {mode:13s} K={K} posts={len(posts):5d} loss={row['loss_tier0']:.3f} "
                  f"L3d={row['echo_level_db_3d']:.1f} jitter-loss {jl} "
                  f"[info: corr {row['judges_tier0_info_only']['spec_corr']:.3f}, "
                  f"corr@2mm {row['jitter'][1]['spec_corr_info_only']:.3f}, wave@2mm {row['jitter'][1]['wave_corr']:.3f}]",
                  flush=True)
    # H5: listener sweet spot vs wedge half-angle (phase-locked K=1, 1060 posts)
    sweet = []
    for ha in HALF_ANGLES:
        posts, st, sc, _ = design(cfg, prof_n, 1060, "phase_locked", 1, band, claps, half_angle=ha)
        nominal = ev.echo(posts, sc)
        for off in LISTENER_OFFSETS:
            L = sc.listener + np.asarray(off)
            sc2 = Scene(source=sc.source, listener=L, posts=posts, half_angle_deg=ha)
            shift = listener_shift_s(sc, L, cfg.r0 + 343.0 * len(target.audio) / FS / 4.0)
            e = ev.echo(posts, sc2)
            j = ev.judges(e, t0=ev.t0 + shift)
            wc = _wave_corr(ev.seg(np.roll(e, -int(round(shift * FS)), -1)), ev.seg(nominal))
            sweet.append({"half_angle_deg": ha, "offset_m": list(off), "n_posts": int(len(posts)),
                          "dropped": st["dropped"], "loss_tier0": ev.loss(e, shift),
                          "echo_level_db_2d": float(np.mean(echo_level_db(e))), "wave_corr_vs_nominal": wc,
                          "spec_corr_info_only": j["spec_corr"], "pitch_err_pct_info_only": j["pitch_err_pct"]})
            print(f"half {ha:4.1f} offset {off} posts {len(posts)} drop {st['dropped']} loss {sweet[-1]['loss_tier0']:.3f} "
                  f"wave {wc:.3f} [info corr {j['spec_corr']:.3f} pitch {j['pitch_err_pct']:.2f}]", flush=True)
    out = {"what": "Tier 0 design study, stage 1 (2D mode for losses/judges, 3D for level)", "selection": SELECTION,
           "profile_solve": {"steps": cfg.steps, "best_loss": res.info["best_loss"], "band": list(band)},
           "jitter": "radial (along the ray from the source), Gaussian sigma, seeds " + str(JITTER_SEEDS),
           "rows": rows, "sweet_spot": sweet, "wall_s": time.time() - t_all}
    path = export.RUNS / cfg.stage / "_studies" / "design_study_tier0.json"
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path, f"{time.time() - t_all:.0f} s")


if __name__ == "__main__":
    main()
