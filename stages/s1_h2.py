"""Stage 1, hypothesis H2: how much of the Tier 1 vs Tier 0 disagreement is referee position error (rasterized
posts) and how much is multiple scattering? One Tier 1 run of a phase-locked design (same 7 sensors as the stage, so
the empty-scene cache is shared), compared with the Tier 0 echo of the same posts, and with Tier 0 echoes of the
same posts under radial jitter sigma = 0.5 / 1 / 1.5 / 2 mm (3 seeds): which jitter level reproduces the Tier 1
residue?

    uv run python -m stages.s1_h2 --posts 300 [--K 1]   # appends a row to runs/s1_bird/h2_tier1_vs_tier0.json
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

import numpy as np
import torch

from echo import export
from echo.clap import band_limit, clap_family
from echo.inverse import solve_profile, window_loss
from echo.metrics import echo_level_db, stage_values
from echo.scene import FS, fill_fraction
from stages.common import build_design, stage_listeners, stage_scene
from stages.s1_bird import CONFIG
from stages.s1_study import radial_jitter

SIGMAS = (0.0005, 0.001, 0.0015, 0.002, 0.003)
SEEDS = (21, 22, 23)


def _seg(e, n0, n):
    return np.asarray(e)[:, n0:n0 + n]


def _corr(a, b):
    a, b = a - a.mean(-1, keepdims=True), b - b.mean(-1, keepdims=True)
    return float(np.mean((a * b).sum(-1) / np.sqrt((a * a).sum(-1) * (b * b).sum(-1))))


def _residue_db(e, ref):
    """Residue of e against ref after the best scalar gain, dB re ref energy (mean over claps)."""
    out = []
    for a, b in zip(e, ref):
        g = np.dot(a, b) / np.dot(a, a)
        out.append(10 * np.log10(np.sum((g * a - b) ** 2) / np.sum(b ** 2)))
    return float(np.mean(out))


def fill_factor(d):
    return fill_fraction(d.scene)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", type=int, default=300)
    ap.add_argument("--K", type=int, default=1)
    ap.add_argument("--realization", default="phase_locked")
    ap.add_argument("--radius", type=float, default=None, help="post radius (also the profile's a_ref)")
    ap.add_argument("--tier0-only", action="store_true", help="print Tier 0 numbers, no Tier 1 run")
    a = ap.parse_args(argv)
    torch.set_num_threads(4)
    from echo.tier1 import echoes, run_tier1

    cfg = replace(CONFIG, realization=a.realization, posts_per_period=a.K)
    if a.radius is not None:
        cfg = replace(cfg, a_ref=a.radius, catalog=(a.radius,))
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                                steps=cfg.steps, lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out)
    band = res.band
    d = build_design(cfg, prof_n * (a.posts / prof_n.sum()), claps, band, n_out)
    if a.tier0_only:
        v = stage_values(cfg.stage, d.echo_t0_2d, target, res.n0 / FS, band=band)
        print(f"N={len(d.posts)} a={cfg.a_ref} L2d={np.mean(echo_level_db(d.echo_t0_2d)):.2f} "
              f"L3d={np.mean(echo_level_db(d.echo_t0_3d)):.2f} fill={fill_factor(d):.4f} "
              f"loss={window_loss(d.echo_t0_2d, target.audio, band, cfg.r0, 343.0, claps.shape[1]):.3f} "
              f"dropped={d.realize_stats['dropped']} [info pitch "
              f"{np.mean([x['pitch_err_pct'] for x in v]):.2f} corr {np.mean([x['spec_corr'] for x in v]):.3f}]")
        return
    t = time.time()
    r = run_tier1(d.scene, cfg.f_max, cfg.duration_s, listeners=stage_listeners(cfg, target), threads=4)
    e1 = band_limit(echoes(r, claps, listener=0), band[0], band[1])
    wall = time.time() - t
    n0, nw = res.n0, len(target.audio) + claps.shape[1]
    s0, s1 = _seg(d.echo_t0_2d, n0, nw), _seg(e1, n0, nw)

    def judges(e):
        v = stage_values(cfg.stage, e, target, n0 / FS, band=band)
        return {k: float(np.mean([x[k] for x in v])) for k in ("pitch_err_pct", "spec_corr")}

    def loss(e):
        return window_loss(e, target.audio, band, cfg.r0, 343.0, claps.shape[1])

    jit = []
    for sig in SIGMAS:
        acc = {"wave_corr_vs_tier0": [], "residue_db_vs_tier0": [], "loss": [], "spec_corr_info_only": []}
        for sd in SEEDS:
            pj = radial_jitter(d.posts, sig, sd)
            from echo.tier0 import post_echo

            ej = post_echo(pj, torch.as_tensor(claps), stage_scene(cfg, pj), mode="2d", n_out=n_out,
                           band=band).numpy()
            sj = _seg(ej, n0, nw)
            acc["wave_corr_vs_tier0"].append(_corr(sj, s0))
            acc["residue_db_vs_tier0"].append(_residue_db(sj, s0))
            acc["loss"].append(loss(ej))
            acc["spec_corr_info_only"].append(judges(ej)["spec_corr"])
        jit.append({"sigma_m": sig, **{k: float(np.mean(v)) for k, v in acc.items()}})
    row = {"label": f"{a.realization} K={a.K} N={len(d.posts)} a={cfg.a_ref}", "radius": cfg.a_ref, "realization": a.realization, "posts_per_period": a.K,
           "n_posts": int(len(d.posts)), "fill": fill_fraction(d.scene), "tier1_wall_s": wall,
           "loss_tier0": loss(d.echo_t0_2d), "loss_tier1": loss(e1),
           "tier_gap_db": float(np.mean(echo_level_db(e1) - echo_level_db(d.echo_t0_2d))),
           "wave_corr_tier1_vs_tier0": _corr(s1, s0), "residue_db_tier1_vs_tier0": _residue_db(s1, s0),
           "judges_tier0_info_only": judges(d.echo_t0_2d), "judges_tier1_info_only": judges(e1),
           "tier0_jitter_equivalents": jit,
           "per_window_level_db_tier1_minus_tier0": [
               float(10 * np.log10(np.sum(s1[:, i:i + 160] ** 2) / np.sum(s0[:, i:i + 160] ** 2)))
               for i in range(0, nw - 160 + 1, 160)]}
    np.savez_compressed(export.RUNS / cfg.stage / "_studies" / f"h2_echoes_{a.realization}_K{a.K}_N{len(d.posts)}_a{cfg.a_ref}.npz",
                        tier0=d.echo_t0_2d, tier1=e1, posts=d.posts, n0=n0)
    path = export.RUNS / cfg.stage / "_studies" / "h2_tier1_vs_tier0.json"
    out = json.loads(path.read_text()) if path.exists() else {
        "what": "H2: Tier 1 vs Tier 0 on the same posts, and the Tier 0 radial jitter that reproduces the residue",
        "selection": "diagnostic only; nothing is chosen from this file", "rows": []}
    out["rows"] = [x for x in out["rows"] if x["label"] != row["label"]] + [row]
    path.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in row.items() if k != "tier0_jitter_equivalents"}, indent=1))
    for j in jit:
        print(j)


if __name__ == "__main__":
    main()
