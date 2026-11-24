"""Shared stage driver: target -> profile solve -> realize -> Tier 0 post echo -> score -> export.

Tier 1 is optional and injected (never imported at module import time): `run_stage(cfg, tier1=Tier1Hooks(...))`.
Task 6 adds the Tier 1 correction loop through `correct` (see `run_stage`).
"""

from __future__ import annotations

import argparse
import shlex
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np
import torch

from echo import export
from echo.clap import clap_family
from echo.inverse import R0_PROFILE, solve_profile
from echo.metrics import echo_level_db, score_stage
from echo.realize import realize, scale_profile
from echo.scene import FS, Scene, fill_fraction
from echo.tier0 import DR_PROFILE, post_echo, profile_echo

torch.set_num_threads(4)


@dataclass
class StageConfig:
    stage: str  # e.g. "s1_bird"
    title: str
    tag: str  # short run-id tag
    make_target: Callable  # () -> echo.targets.Target
    duration_s: float  # exported timeline length (s), covers the whole echo
    n_claps: int = 5
    seed: int = 0
    r0: float = R0_PROFILE
    dr: float = DR_PROFILE
    a_ref: float = 0.02
    target_fill: float = 0.015  # post area / wedge area: the profile's free overall scale (density vs multiple scattering)
    steps: int = 300
    lr: float = 0.02
    w_mel: float = 1.0
    shadow_depth: float = 0.5
    notes: str = ""


@dataclass
class Design:
    """Everything one design iteration produces (Tier 0 parts always, Tier 1 parts when run)."""
    profile: np.ndarray  # physical scale (reference posts per bin)
    posts: np.ndarray
    scene: Scene
    realize_stats: dict
    echo_t0_2d: np.ndarray  # [K, n] post echo, band-limited to the loss band
    echo_t0_3d: np.ndarray
    echo_prof_2d: np.ndarray  # profile_echo (the model the solve sees)
    echo_t1_2d: np.ndarray | None = None
    metrics: dict | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Tier1Hooks:
    """Optional Tier 1 pieces wired in by a later task.

    run(scene, f_max, t_end, listeners=..., c=..., record_field=...) -> Tier1Result
    echoes(result, claps, listener=0) -> ndarray[K, n]
    correct(cfg, ctx, design) -> list[Design] (correction loop; may be None)
    """
    run: Callable | None = None
    echoes: Callable | None = None
    correct: Callable | None = None
    f_max: float = 4000.0


def profile_dict(profile, r0, dr):
    return {"r0_m": float(r0), "dr_m": float(dr), "reflectivity": [round(float(v), 5) for v in profile],
            "units": "equivalent reference posts (radius a_ref) per bistatic-range bin"}


def build_design(cfg: StageConfig, profile, claps, band, n_out, seed=None) -> Design:
    """Realize a physical-scale profile and evaluate Tier 0 (2D post echo, 3D post echo, 2D profile echo)."""
    sc = Scene()
    posts, st = realize(profile, sc, cfg.seed if seed is None else seed, r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                        band=band, shadow_depth=cfg.shadow_depth)
    sc = Scene(posts=posts)
    cl = torch.as_tensor(claps)
    e2 = post_echo(posts, cl, sc, mode="2d", n_out=n_out, band=band).numpy()
    e3 = post_echo(posts, cl, sc, mode="3d", n_out=n_out, band=band).numpy()
    ep = profile_echo(torch.as_tensor(profile), cl, sc, mode="2d", n_out=n_out, a_ref=cfg.a_ref, r0=cfg.r0,
                      dr=cfg.dr, band=band).numpy()
    mism = 10 * np.log10(np.sum((e2 - ep) ** 2) / np.sum(ep ** 2))
    lvl = float(np.mean(echo_level_db(e2) - echo_level_db(ep)))
    st = dict(st)
    st["post_vs_profile_mismatch_db"] = float(mism)
    st["post_vs_profile_level_db"] = lvl
    return Design(profile=profile, posts=posts, scene=sc, realize_stats=st, echo_t0_2d=e2, echo_t0_3d=e3,
                  echo_prof_2d=ep)


def run_stage(cfg: StageConfig, tier1: Tier1Hooks | None = None, command=None, verbose=True, runs_root=None):
    """Run a stage end to end and write its run folder. Returns (run_dir, design, solve_result)."""
    t_all = time.time()
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    prof_n, res = solve_profile(target, claps, Scene(), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref, steps=cfg.steps,
                                lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out, verbose=verbose, log_every=5)
    band = res.band
    profile = scale_profile(prof_n, cfg.target_fill, cfg.r0, cfg.dr, cfg.a_ref)
    t_r = time.time()
    des = build_design(cfg, profile, claps, band, n_out)
    t_r = time.time() - t_r
    t_echo0 = res.n0 / FS
    history = {"phases": [{"name": "Profile solve (Tier 0)", "x_label": "Adam step", "iters": res.history["iters"],
                           "loss": res.history["loss"], "score": None, "saved": []}]}
    designs = [des]
    if tier1 is not None and tier1.correct is not None:
        designs = tier1.correct(cfg, {"target": target, "claps": claps, "band": band, "n_out": n_out,
                                      "t_echo0": t_echo0, "res": res, "history": history}, des) or designs
        des = designs[-1]
    sc = des.scene
    st = des.realize_stats
    metrics = score_stage(cfg.stage, target, t_echo0, des.echo_t0_2d, des.echo_t0_3d, des.echo_t1_2d, band=band,
                          depth_m=sc.depth_m, post_count=int(len(des.posts)), fill_fraction=fill_fraction(sc))
    des.metrics = metrics
    lvl0 = float(echo_level_db(des.echo_t0_3d)[0]) + (metrics["headline"]["tier_gap_db"] or 0.0)
    notes = (f"{cfg.notes} Exported audio uses clap variant 0; metrics average {cfg.n_claps} clap variants. "
             f"Echoes band-limited to the loss band {band[0]:.0f}-{band[1]:.0f} Hz (clap band within the design band). "
             f"Profile solve: {res.history['wall_s']:.1f} s, {cfg.steps} Adam steps, loss {res.info['init_loss']:.3f} -> "
             f"{res.info['best_loss']:.3f}. Realization: {st['n_posts']} posts, {st['shadow_violations']} shadow "
             f"violations, {st['dropped']} dropped, post-vs-profile echo mismatch {st['post_vs_profile_mismatch_db']:.1f} dB."
             ).strip()
    rs = {k: v for k, v in st.items() if k != "realized_profile"}
    extra = {"design": {"config": {k: v for k, v in asdict(cfg).items() if k != "make_target"},
                        "loss_band_hz": list(band), "t_echo0_s": t_echo0, "realization": rs,
                        "solve_wall_s": res.history["wall_s"], "realize_wall_s": t_r,
                        "total_wall_s": time.time() - t_all}}
    kw = {} if runs_root is None else {"runs_root": runs_root}
    run_dir = export.write_run(cfg.stage, cfg.tag, cfg.title, scene=sc, profile=profile_dict(des.profile, cfg.r0, cfg.dr),
                               target_audio=target.audio, t_echo0=t_echo0, claps=claps, echo_t0=des.echo_t0_2d,
                               echo_t1=des.echo_t1_2d, metrics=metrics, history=history, seed=cfg.seed,
                               command=command or " ".join(["uv run python -m", f"stages.{cfg.stage}"] + sys.argv[1:]),
                               notes=notes, as_heard_level_db=lvl0, duration_s=cfg.duration_s, extra=extra, **kw)
    if verbose:
        print(f"wrote {run_dir}")
        for m in metrics["metrics"]:
            print(f"  [{m['tier']}] {m['id']}: {m['value']} (thr {m['threshold']}, pass {m['pass']})")
        print("  headline:", metrics["headline"])
        print("  realization:", {k: v for k, v in rs.items() if k not in ("weights",)})
    return run_dir, des, res


def stage_main(cfg: StageConfig, argv=None):
    ap = argparse.ArgumentParser(description=f"Run stage {cfg.stage}")
    ap.add_argument("--tier0-only", action="store_true", help="skip Tier 1 (writes a tier0_only run)")
    ap.add_argument("--steps", type=int, default=cfg.steps)
    ap.add_argument("--fill", type=float, default=cfg.target_fill, help="target fill fraction (profile scale)")
    ap.add_argument("--seed", type=int, default=cfg.seed)
    ap.add_argument("--tag", default=cfg.tag)
    a = ap.parse_args(argv)
    cfg.steps, cfg.target_fill, cfg.seed, cfg.tag = a.steps, a.fill, a.seed, a.tag
    tier1 = None
    if not a.tier0_only:
        print("Tier 1 is not wired in yet (Task 6); running Tier 0 only.")
    args = list(argv if argv is not None else sys.argv[1:])
    cmd = " ".join(["uv run python -m", f"stages.{cfg.stage}"] + [shlex.quote(x) for x in args])
    return run_stage(cfg, tier1, command=cmd)
