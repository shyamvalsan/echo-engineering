"""Shared stage driver: target -> profile solve -> realize -> Tier 0 -> Tier 1 correction loop -> final Tier 1 run
with the field -> robustness sweep -> score -> export. Every stage is a `StageConfig` (see `stages/s1_bird.py`).

Tier 1 is imported lazily (only when a stage runs it): `run_stage(cfg, tier1=Tier1Hooks())`. `--tier0-only`
writes a tier0_only run without importing it.

Verification rule: a run is `verified` only if `runs/validation/metrics.json` says `passed: true` at run time AND
it was produced by the same Tier 1 engine version (`echo.tier1.ENGINE_VERSION`, recorded as
`manifest.solver.engine`) with every check in it passing, AND every radius the design uses is validated at the
Tier 1 grid used (same f_max and ppw as a validated grid there; if
the validation file has no entry for that grid, `cfg.validated_radii` is used and the manifest says so).
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import torch

from echo import export
from echo.clap import clap_family
from echo.inverse import R0_PROFILE, solve_profile
from echo.metrics import echo_level_db, score_stage
from echo.realize import realize, scale_profile
from echo.scene import C0, FS, RADII, Scene, fill_fraction
from echo.tier0 import DR_PROFILE, post_echo, profile_echo


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
    a_ref: float = 0.01  # reference (and preferred) post radius: small posts (spec), realized 1:1 with the model
    target_fill: float = 0.01  # post area / wedge area: the profile's free overall scale (density vs multiple scattering)
    steps: int = 300
    lr: float = 0.02
    w_mel: float = 1.0
    shadow_depth: float = 0.5
    refine_steps: int = 100  # post-range polish against the profile transfer (realize.refine_ranges)
    max_posts: int = 40000  # cap on post count: the profile is scaled down (and logged) if target_fill needs more
    threads: int = 8  # torch.set_num_threads, applied in run_stage
    notes: str = ""
    # --- Tier 1 and the stages after stage 1 (all configuration; the driver code is shared) ---
    f_max: float = 4000.0  # Tier 1 top frequency (grid: ppw points per wavelength at f_max)
    ppw: float | None = None  # None: echo.tier1.PPW_DEFAULT (the validated 9)
    half_angle_deg: float = 20.0  # wedge half-angle (narrow it to shrink the Tier 1 domain)
    catalog: tuple = RADII  # radii the realization may use (a_ref must be one of them)
    validated_radii: tuple | None = None  # fallback when runs/validation/metrics.json has no entry for this grid
    note_s: float | None = None  # note length the note judge is told; None = median of target.notes (judge default)
    correction_rounds: int = 5  # max Tier 1 runs in the correction loop (spec: stop after 5 rounds)
    correction_power: float = 1.0  # damping exponent on the per-window gains (1 = full step)
    robustness: bool = True  # run the robustness sweep on the final design
    field: bool = True  # record the Tier 1 field of the final design and render field.webm
    field_dt: float = 0.25e-3  # s of simulation per field frame
    post_height_m: float = 2.0  # finite post height for the informational 3D level (Tier 0 post_height)
    fill_candidates: tuple | None = None  # optional density sweep on Tier 1 before the loop: pick the fill with the
    #   lowest Tier 1 spectrogram loss (window_loss; never a judge). None: use target_fill as is.
    status: str | None = None  # None: "final" with Tier 1, "tier0_only" without; "intermediate" for provisional runs


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


def stage_scene(cfg: StageConfig, posts=None, c=C0) -> Scene:
    return Scene(posts=np.zeros((0, 3)) if posts is None else posts, half_angle_deg=cfg.half_angle_deg, c=c)


def build_design(cfg: StageConfig, profile, claps, band, n_out, seed=None) -> Design:
    """Realize a physical-scale profile and evaluate Tier 0 (2D post echo, 3D post echo, 2D profile echo)."""
    sc = stage_scene(cfg)
    posts, st = realize(profile, sc, cfg.seed if seed is None else seed, r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                        radii=tuple(cfg.catalog), band=band, shadow_depth=cfg.shadow_depth, claps=claps,
                        refine_steps=cfg.refine_steps)
    sc = stage_scene(cfg, posts)
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


VALIDATION_FILE = export.RUNS / "validation" / "metrics.json"


def validated_radii(cfg: StageConfig, ppw, path=None, engine=None) -> dict:
    """Read the solver validation at run time. Returns {validation_passed, radii (validated at this grid) or None,
    source ("runs/validation/metrics.json:<grid key>" | "config" | None), path, engine, validation_engine}.

    validation_passed requires: top-level `passed: true`, every check present with a `pass` flag passing (this
    includes a dense-field check when the file has one), and -- when `engine` is given -- the file's
    `solver.engine` equal to it (a validation made with another engine version does not count)."""
    path = Path(path or VALIDATION_FILE)
    out = {"validation_passed": False, "radii": None, "source": None, "path": str(path), "engine": engine,
           "validation_engine": None}
    try:
        d = json.loads(path.read_text())
    except Exception:
        d = None
    if d is not None:
        v_eng = (d.get("solver") or {}).get("engine")
        out["validation_engine"] = v_eng
        checks = d.get("checks") or {}
        failed = [k for k, v in checks.items() if isinstance(v, dict) and "pass" in v and not v["pass"]]
        out["failed_checks"] = failed
        out["validation_passed"] = bool(d.get("passed", False)) and not failed and (engine is None or v_eng == engine)
        v_ppw = (d.get("solver") or {}).get("ppw")
        cyl = (d.get("checks") or {}).get("cylinder") or {}
        for key, g in cyl.items():
            if isinstance(g, dict) and "per_radius" in g and g.get("f_max") is not None \
                    and abs(float(g["f_max"]) - cfg.f_max) < 1e-6 and v_ppw is not None \
                    and abs(float(v_ppw) - float(ppw)) < 1e-9:
                out["radii"] = sorted(float(r) for r, v in g["per_radius"].items() if v.get("pass"))
                out["source"] = f"{path.name}:checks.cylinder.{key} (f_max {g['f_max']} Hz, ppw {v_ppw})"
    if out["radii"] is None and cfg.validated_radii is not None:
        out["radii"] = sorted(float(r) for r in cfg.validated_radii)
        out["source"] = "config (StageConfig.validated_radii): no validation entry for this grid"
    return out


def verify(cfg: StageConfig, posts, ppw, path=None, engine=None) -> tuple[bool, dict]:
    """The verification rule (module docstring). Returns (verified, info)."""
    info = validated_radii(cfg, ppw, path, engine)
    used = sorted({round(float(r), 4) for r in np.asarray(posts).reshape(-1, 3)[:, 2]})
    ok_r = info["radii"] is not None and all(any(abs(u - v) < 1e-6 for v in info["radii"]) for u in used)
    info["radii_used"] = used
    info["radii_ok"] = bool(ok_r)
    return bool(info["validation_passed"] and ok_r), info


def failure_cause_text(metrics: dict) -> str | None:
    """Plain statement of which gating metrics failed, with the judge floor next to them (None if passed)."""
    if metrics.get("passed"):
        return None
    if not metrics.get("verified"):
        return "not verified: " + str(metrics.get("verification", {}).get("reason", "no Tier 1 or unvalidated radii"))
    fl = (metrics.get("judge_floor") or {}).get("mean") or {}
    parts = []
    for m in metrics["metrics"]:
        if m["gating"] and not m["pass"]:
            floor = fl.get(m["id"])
            parts.append(f"Tier 1 {m['label'].lower()} = {m['value']:.3g}{m['unit']} misses {m['comparator']} "
                         f"{m['threshold']}{m['unit']}" + (f" (judge floor on a perfect echo: {floor:.3g}{m['unit']})"
                                                           if floor is not None else ""))
    return "; ".join(parts) or None


@dataclass
class Tier1Hooks:
    """Tier 1 entry points (defaults: echo.tier1.run_tier1 / echoes, imported lazily)."""
    run: Callable | None = None  # run(scene, f_max, t_end, listeners=, c=, record_field=, field_dt=, ppw=, threads=)
    echoes: Callable | None = None  # echoes(result, claps, listener=0) -> ndarray[K, n]

    def resolve(self):
        if self.run is None or self.echoes is None:
            from echo import tier1

            self.run = self.run or tier1.run_tier1
            self.echoes = self.echoes or tier1.echoes
        return self


def tier1_engine():
    from echo import tier1

    return getattr(tier1, "ENGINE_VERSION", None)


def _say(verbose):
    return (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)


def run_stage(cfg: StageConfig, tier1: Tier1Hooks | None = None, command=None, verbose=True, runs_root=None):
    """Run a stage end to end and write its run folder. Returns (run_dir, design, solve_result)."""
    from echo.inverse import clap_centroid_s, correction_loop, reference_echo, stage_score, window_gains, window_loss
    from echo.clap import band_limit

    say = _say(verbose)
    t_all = time.time()
    wall = {}
    torch.set_num_threads(cfg.threads)
    target = cfg.make_target()
    if cfg.note_s is not None and target.notes:
        med = float(np.median([b - a for _, a, b in target.notes]))
        if abs(med - cfg.note_s) > 1e-6:
            raise ValueError(f"cfg.note_s={cfg.note_s} but the target's notes are {med} s long (the judge reads them)")
    if cfg.a_ref not in tuple(cfg.catalog):
        raise ValueError(f"a_ref {cfg.a_ref} not in catalog {cfg.catalog}")
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    t = time.time()
    prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                                steps=cfg.steps, lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out, verbose=verbose,
                                log_every=25)
    wall["profile_solve_s"] = time.time() - t
    band = res.band
    profile = scale_profile(prof_n, cfg.target_fill, cfg.r0, cfg.dr, cfg.a_ref, half_angle_deg=cfg.half_angle_deg)
    capped = None
    if profile.sum() > cfg.max_posts:  # mass in reference posts ~ post count (a_ref posts preferred)
        capped = f"profile scaled by {cfg.max_posts / profile.sum():.4f} to respect max_posts={cfg.max_posts}"
        profile = profile * (cfg.max_posts / profile.sum())
    t_echo0 = res.n0 / FS
    history = {"phases": [{"name": "Profile solve (Tier 0)", "x_label": "Adam step", "iters": res.history["iters"],
                           "loss": res.history["loss"], "score": None, "saved": []}]}
    iters, solver, field_block, robust, fragile, fragile_why = None, None, None, [], False, None
    t1_info = {}

    def t0_metrics(des, e1=None, claps_floor=None):
        return score_stage(cfg.stage, target, t_echo0, des.echo_t0_2d, des.echo_t0_3d, e1, band=band,
                           depth_m=des.scene.depth_m, post_count=int(len(des.posts)),
                           fill_fraction=fill_fraction(des.scene), claps=claps_floor)

    if tier1 is None:
        t = time.time()
        des = build_design(cfg, profile, claps, band, n_out)
        wall["realize_s"] = time.time() - t
        e1_final, best_res = None, None
    else:
        from echo.robustness import robustness_listeners, sweep
        from echo.tier1 import PPW_DEFAULT

        hooks = tier1.resolve()
        ppw = cfg.ppw or PPW_DEFAULT
        # sensors: [nominal, 1 m sideways, 1 m back] + 4 passive anchor sensors at the wedge corners. Tier 1's domain
        # is the bounding box of posts and sensors (snapped to 0.25 m), so the anchors fix the domain for every design
        # of the stage and the cached empty-scene run is reused across correction rounds (sensors only record).
        r_hi = cfg.r0 + C0 * len(target.audio) / FS / 2.0 + 0.1
        th = np.radians(cfg.half_angle_deg)
        anchors = np.array([[r * np.cos(a), r * np.sin(a)] for r in (stage_scene(cfg).r_min, r_hi) for a in (-th, th)])
        lis = np.vstack([robustness_listeners(stage_scene(cfg)), anchors])

        def t1(scene, c=C0, record_field=False):
            return hooks.run(scene, cfg.f_max, cfg.duration_s, listeners=lis, c=c, record_field=record_field,
                             field_dt=cfg.field_dt, ppw=ppw, threads=cfg.threads)

        def e1_of(r, li=0):
            return band_limit(hooks.echoes(r, claps, listener=li), band[0], band[1])

        ref = reference_echo(target.audio, claps, t_echo0, n_out, band)
        t_stop = t_echo0 + len(target.audio) / FS + claps.shape[1] / FS
        t_loop = time.time()
        wall["realize_s"], wall["tier1_loop_s"] = 0.0, 0.0

        def build(p):
            t = time.time()
            d = build_design(cfg, p, claps, band, n_out)
            wall["realize_s"] += time.time() - t
            say(f"  realized {len(d.posts)} posts ({time.time() - t:.0f} s)")
            return d

        def run1(d):
            t = time.time()
            r = t1(d.scene)
            wall["tier1_loop_s"] += time.time() - t
            say(f"  tier1 {r.wall_s:.0f} s (empty cached: {r.extra.get('empty_cached')})")
            return r, e1_of(r)

        def evaluate(d, e1):
            m = t0_metrics(d, e1)
            return m, window_loss(e1, target.audio, band, cfg.r0, C0, claps.shape[1]), stage_score(m)

        if cfg.fill_candidates:
            t = time.time()
            sweep_rows = []
            for fill in cfg.fill_candidates:
                p_f = scale_profile(prof_n, fill, cfg.r0, cfg.dr, cfg.a_ref, half_angle_deg=cfg.half_angle_deg)
                p_f = p_f * min(1.0, cfg.max_posts / p_f.sum())
                d_f = build(p_f)
                _, e_f = run1(d_f)
                loss_f = window_loss(e_f, target.audio, band, cfg.r0, C0, claps.shape[1])
                sweep_rows.append({"fill": float(fill), "posts": int(len(d_f.posts)), "loss_tier1": loss_f,
                                   "loss_tier0": window_loss(d_f.echo_t0_2d, target.audio, band, cfg.r0, C0,
                                                             claps.shape[1]),
                                   "tier_gap_db": float(np.mean(echo_level_db(e_f) - echo_level_db(d_f.echo_t0_2d))),
                                   "profile": p_f})
                say(f"  density sweep fill {fill}: {len(d_f.posts)} posts, Tier 1 loss {loss_f:.4f}")
            pick = min(range(len(sweep_rows)), key=lambda i: sweep_rows[i]["loss_tier1"])
            profile = sweep_rows[pick]["profile"]
            history["phases"].append({"name": "density_sweep", "x_label": "candidate", "iters":
                                      list(range(len(sweep_rows))), "loss": [r["loss_tier1"] for r in sweep_rows],
                                      "score": None, "saved": [], "fills": [r["fill"] for r in sweep_rows],
                                      "selection": "lowest Tier 1 spectrogram loss (window_loss), no judge"})
            t1_info["density_sweep"] = {"rows": [{k: v for k, v in r.items() if k != "profile"} for r in sweep_rows],
                                        "picked_fill": sweep_rows[pick]["fill"],
                                        "selection": "lowest Tier 1 spectrogram loss (window_loss); judges not used"}
            wall["density_sweep_s"] = time.time() - t
        rounds, ib = correction_loop(profile, build, run1, evaluate, ref, t_echo0, t_stop, r0=cfg.r0, dr=cfg.dr,
                                     c=C0, t_offset=clap_centroid_s(claps), rounds=cfg.correction_rounds,
                                     power=cfg.correction_power, log=say)
        wall["correction_loop_s"] = time.time() - t_loop
        best = rounds[ib]
        des = best.design
        des.echo_t1_2d = best.echo_t1
        best_res = best.tier1
        history["phases"].append({
            "name": "tier1_correction", "x_label": "correction round", "iters": [r.k for r in rounds],
            "loss": [r.loss for r in rounds], "score": [r.score for r in rounds], "saved": [],
            "best": ib, "score_definition": "min relative margin over the gating metrics (positive = all pass)",
            "loss_definition": "MR-STFT + log-mel loss (echo.inverse.window_loss) of the Tier 1 echo vs the target"})
        iters = [(f"r{r.k}", r.design.scene, profile_dict(r.design.profile, cfg.r0, cfg.dr), r.echo_t1[0], r.metrics,
                  r.k) for r in rounds]
        t1_info["rounds"] = [{"round": r.k, "loss": r.loss, "score": r.score, "posts": int(len(r.design.posts)),
                              "gains_next": None if r.gains is None else [float(g) for g in r.gains],
                              "tier_gap_db": r.metrics["headline"]["tier_gap_db"], "wall_s": r.wall_s,
                              "gating": {m["id"]: m["value"] for m in r.metrics["metrics"] if m["gating"]}}
                             for r in rounds]
        t1_info["best_round"] = ib
        if cfg.field:  # the final design once more, recording the field (deterministic: same ir)
            t = time.time()
            fres = t1(des.scene, record_field=True)
            wall["tier1_field_run_s"] = time.time() - t
            t1_info["field_run_ir_max_abs_diff"] = float(np.max(np.abs(fres.ir - best_res.ir)))
            best_res = fres
        e1_final = e1_of(best_res)
        des.echo_t1_2d = e1_final
        solver = {"tier1": best_res.solver, "device": best_res.device, "dx": best_res.dx, "dt": best_res.dt,
                  "grid": list(best_res.grid), "f_lo": best_res.f_lo, "f_max": best_res.f_max, "ppw": best_res.ppw,
                  "wall_s": best_res.wall_s, "listeners": np.asarray(best_res.listeners).tolist(),
                  "engine": getattr(best_res, "engine", None) or best_res.extra.get("engine") or tier1_engine()}
        if cfg.robustness:
            t = time.time()

            def tier0_echo(sc):
                return post_echo(sc.posts, torch.as_tensor(claps), sc, mode="2d", n_out=n_out, band=band).numpy()

            rho_mid = cfg.r0 + C0 * len(target.audio) / FS / 4.0
            robust, fragile, fragile_why, tim = sweep(
                cfg.stage, target, claps, band, des.scene, t_echo0, cfg.r0, best_res,
                run_t1=lambda sc, c: t1(sc, c), echoes=lambda r, cl, li: hooks.echoes(r, cl, listener=li),
                tier0_echo=tier0_echo, seed=cfg.seed, rho_mid=rho_mid, log=say)
            wall["robustness_s"] = time.time() - t
            wall["robustness_detail_s"] = tim

    sc = des.scene
    st = des.realize_stats
    metrics = score_stage(cfg.stage, target, t_echo0, des.echo_t0_2d, des.echo_t0_3d, e1_final, band=band,
                          depth_m=sc.depth_m, post_count=int(len(des.posts)), fill_fraction=fill_fraction(sc),
                          claps=claps, robustness=robust)
    gap = metrics["headline"]["tier_gap_db"] or 0.0
    # informational: finite post height (Tier 0 3D with post_height), corrected by the same tier gap
    e3h = post_echo(des.posts, torch.as_tensor(claps), sc, mode="3d", n_out=n_out, band=band,
                    post_height=cfg.post_height_m).numpy()
    raw_h = float(np.mean(echo_level_db(e3h)))
    metrics["headline"]["echo_level_db_re_direct_finite_height"] = raw_h + gap
    metrics["headline"]["finite_height_m"] = cfg.post_height_m
    if tier1 is not None:
        verified, vinfo = verify(cfg, des.posts, solver["ppw"], engine=solver.get("engine"))
        vinfo["reason"] = ("validation passed and every radius used is validated at this grid" if verified else
                           (f"solver validation not passed for engine {solver.get('engine')} (validation file: engine "
                            f"{vinfo['validation_engine']}, failed checks {vinfo.get('failed_checks')})"
                            if not vinfo["validation_passed"] else
                            f"radii used {vinfo['radii_used']} not all validated at this grid ({vinfo['radii']})"))
        metrics["verified"] = verified
        metrics["passed"] = bool(metrics["passed"] and verified)
        metrics["verification"] = vinfo
        metrics["fragile"] = bool(fragile)
        metrics["fragile_reason"] = fragile_why
        metrics["tier1_correction"] = t1_info
        metrics["failure_cause"] = failure_cause_text(metrics)
    des.metrics = metrics
    lvl0 = float(echo_level_db(des.echo_t0_3d)[0]) + gap
    notes = (f"{cfg.notes} Exported audio uses clap variant 0; metrics average {cfg.n_claps} clap variants. "
             f"Echoes band-limited to the loss band {band[0]:.0f}-{band[1]:.0f} Hz (clap band within the design band). "
             f"Profile solve: {res.history['wall_s']:.1f} s, {cfg.steps} Adam steps, loss {res.info['init_loss']:.3f} -> "
             f"{res.info['best_loss']:.3f}. Realization: {st['n_posts']} posts, {st['shadow_violations']} shadow "
             f"violations, {st['dropped']} dropped, post-vs-profile echo mismatch {st['post_vs_profile_mismatch_db']:.1f} dB."
             + (f" Tier 1 correction: {len(t1_info['rounds'])} rounds, best r{t1_info['best_round']}."
                if t1_info else "")).strip()
    rs = {k: v for k, v in st.items() if k != "realized_profile"}
    kw = {} if runs_root is None else {"runs_root": runs_root}
    run_id = export.make_run_id(cfg.tag)
    run_dir = Path(runs_root or export.RUNS) / cfg.stage / run_id
    if tier1 is not None and cfg.field and best_res is not None and best_res.field is not None:
        from echo.field_video import render_field_video

        t = time.time()
        f = best_res.field
        field_block = render_field_video(f["frames"], f["extent"], run_dir / "field.webm", t0=f["t0"],
                                         dt_frame=f["dt_frame"], scene=sc)
        t1_info["field_colour"] = field_block.pop("colour", None)  # manifest field block stays exactly the contract's
        wall["field_video_s"] = time.time() - t
    wall["total_s"] = time.time() - t_all
    extra = {"design": {"config": {k: v for k, v in asdict(cfg).items() if k != "make_target"},
                        "loss_band_hz": list(band), "t_echo0_s": t_echo0, "realization": rs,
                        "max_posts_applied": capped,
                        "solve_wall_s": res.history["wall_s"], "realize_wall_s": wall.get("realize_s"),
                        "total_wall_s": wall["total_s"]},
             "wall_s": wall}
    run_dir = export.write_run(cfg.stage, cfg.tag, cfg.title, scene=sc, profile=profile_dict(des.profile, cfg.r0, cfg.dr),
                               target_audio=target.audio, t_echo0=t_echo0, claps=claps, echo_t0=des.echo_t0_2d,
                               echo_t1=des.echo_t1_2d, metrics=metrics, history=history, seed=cfg.seed,
                               command=command or " ".join(["uv run python -m", f"stages.{cfg.stage}"] + sys.argv[1:]),
                               notes=notes, as_heard_level_db=lvl0, duration_s=cfg.duration_s, extra=extra,
                               solver=solver, field=field_block, iters=iters, run_id=run_id,
                               status=cfg.status or (None if tier1 is None else "final"), **kw)
    if verbose:
        print_summary(run_dir, metrics, wall)
    return run_dir, des, res


def print_summary(run_dir, metrics, wall):
    h = metrics["headline"]
    print(f"\n=== {metrics['stage']}  {'PASSED' if metrics['passed'] else 'FAILED'}  verified={metrics['verified']}"
          f"  fragile={metrics['fragile']} ===")
    print(f"run: {run_dir}")
    for m in metrics["metrics"]:
        if m["threshold"] is not None or m["tier"] == "tier1":
            print(f"  [{m['tier']}{'*' if m['gating'] else ' '}] {m['id']:<22} {m['value']!s:<22.22} "
                  f"thr {m['comparator'] or ''}{m['threshold']}  pass {m['pass']}")
    fl = (metrics.get("judge_floor") or {}).get("mean") or {}
    print("  judge floor (perfect echo):", {k: round(v, 3) for k, v in fl.items() if v is not None})
    print(f"  echo level {h['echo_level_db_re_direct']:.1f} dB re direct (raw 3D {h['echo_level_db_re_direct_raw3d']:.1f}, "
          f"{h.get('finite_height_m')} m posts {h.get('echo_level_db_re_direct_finite_height', float('nan')):.1f}), "
          f"SPL {h['echo_spl_db']:.1f} dB, tier gap {h['tier_gap_db']}, depth {h['depth_m']:.2f} m, "
          f"{h['post_count']} posts, fill {h['fill_fraction']:.4f}")
    for c in metrics.get("robustness") or []:
        print(f"  robust {c['case']:<18} pass {c['pass']!s:<5} " +
              " ".join(f"{k}={v:.3g}" for k, v in c["metrics"].items() if v is not None and k in ("pitch_err_pct", "spec_corr", "notes_in_order", "note_cents_max")))
    if metrics.get("failure_cause"):
        print("  failure cause:", metrics["failure_cause"])
    print("  wall:", {k: round(v, 1) for k, v in wall.items() if isinstance(v, float)})


def stage_main(cfg: StageConfig, argv=None):
    ap = argparse.ArgumentParser(description=f"Run stage {cfg.stage}")
    ap.add_argument("--tier0-only", action="store_true", help="skip Tier 1 (writes a tier0_only run)")
    ap.add_argument("--steps", type=int, default=cfg.steps)
    ap.add_argument("--fill", type=float, default=cfg.target_fill, help="target fill fraction (profile scale)")
    ap.add_argument("--seed", type=int, default=cfg.seed)
    ap.add_argument("--tag", default=cfg.tag)
    ap.add_argument("--rounds", type=int, default=cfg.correction_rounds, help="max Tier 1 correction rounds")
    ap.add_argument("--no-robustness", action="store_true")
    ap.add_argument("--no-field", action="store_true")
    ap.add_argument("--intermediate", action="store_true", help="write status 'intermediate' (provisional run)")
    a = ap.parse_args(argv)
    cfg.steps, cfg.target_fill, cfg.seed, cfg.tag = a.steps, a.fill, a.seed, a.tag
    cfg.correction_rounds = a.rounds
    cfg.robustness = cfg.robustness and not a.no_robustness
    cfg.field = cfg.field and not a.no_field
    if a.intermediate:
        cfg.status = "intermediate"
    tier1 = None if a.tier0_only else Tier1Hooks()
    args = list(argv if argv is not None else sys.argv[1:])
    cmd = " ".join(["uv run python -m", f"stages.{cfg.stage}"] + [shlex.quote(x) for x in args])
    return run_stage(cfg, tier1, command=cmd)
