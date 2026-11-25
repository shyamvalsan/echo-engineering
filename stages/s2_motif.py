"""Stage 2: four-note motif C6 E6 G6 C7 (1047, 1319, 1568, 2093 Hz), 45 ms each, 180 ms, 30.9 m deep.

    uv run python -m stages.s2_motif               # full loop: Tier 0 design, Tier 1 sweep/correction, field, robustness
    uv run python -m stages.s2_motif --tier0-only  # Tier 0 only (status tier0_only)
    uv run python -m stages.s2_motif --study       # Tier 0 design study -> runs/s2_motif/_studies/design_study_tier0.json

Design study selection rule (also written into the study json): designs are compared by the Tier 0 spectrogram loss
(echo.inverse.window_loss) in the physical clap band and its robustness to radial jitter. The note judge (notes in
order, cents) is recorded for information only and never used to choose. The harmonic-to-fundamental ratio per note
(physics of the comb realization, not a judge) is reported to explain the choice of posts_per_period K.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace

import numpy as np
import torch

from echo import export
from echo.clap import band_limit, clap_family
from echo.inverse import clap_band, solve_profile, window_loss
from echo.metrics import echo_level_db, stage_values
from echo.realize import realize
from echo.scene import FS
from echo.targets import MOTIF_HZ, motif
from echo.tier0 import post_echo
from stages.common import StageConfig, stage_main, stage_scene

CONFIG = StageConfig(
    stage="s2_motif",
    title="Motif C6 E6 G6 C7, 45 ms each",
    tag="s2",
    make_target=motif,
    duration_s=0.215,  # 2*3.0/343 = 17.5 ms to first echo + 180 ms motif + 8 ms clap + margin
    note_s=0.045,
    # Tier 1 grid: f_max 2.5 kHz (top note C7 = 2093 Hz; the spec sets the grid from the highest target frequency).
    # The stage band (profile solve, Tier 0 and Tier 1 echoes, all comparisons) is capped at f_max (band_max_hz).
    f_max=2500.0,
    band_max_hz=2500.0,
    half_angle_deg=10.0,  # narrower wedge: cheaper Tier 1 domain, larger sweet spot (s1 study: +-10 cm at 10 deg)
    catalog=(0.02,),
    a_ref=0.02,
    target_fill=0.016,  # superseded by the Tier 1 density sweep below
    steps=1200,  # profile solve: 1200 Adam steps at lr 0.05 (lower window loss than 300 at 0.02; see the study)
    lr=0.05,
    # Realization, radius and fill chosen on Tier 0 (runs/s2_motif/_studies/design_study_tier0.json) by the spectrogram
    # loss under 2 and 5 mm radial jitter (stage 1 measured its Tier 1 residue as ~3.5 mm-equivalent jitter): the pure
    # comb K = 1 of 2 cm posts has the lowest jittered loss at every fill (its 2nd harmonics are coherent: they keep the
    # fundamental's periodicity); K = 2 quantile, uniform K = 4/6 and sampling trade them for incoherent noise.
    realization="phase_locked",
    posts_per_period=1,
    fill_candidates=(0.008, 0.016),  # Tier 1 density sweep, picked by Tier 1 spectrogram loss only
    correction_rounds=1,  # round 0 = the sweep's pick (time budget on a shared CPU)
    threads=4,  # shared CPU (NUMBA_NUM_THREADS=4)
    design_study_files=("_studies/design_study_tier0.json",),
    robustness=True,
)

# ------------------------------------------------------------------------------------------------ Tier 0 design study
STUDY_RADII = (0.02, 0.04)
STUDY_FILLS = (0.004, 0.008, 0.016)
STUDY_MODES = (("phase_locked", 1), ("phase_locked", 2), ("phase_locked_uniform", 4), ("phase_locked_uniform", 6),
               ("sampling", 1))
STUDY_HALF_ANGLES = (8.0, 10.0, 12.0)
JITTER_M = (0.002, 0.005)
JITTER_SEEDS = (11, 12, 13)
SELECTION = ("designs compared by the Tier 0 spectrogram loss (window_loss, physical clap band 898-4000 Hz) and its "
             "mean under radial jitter only; the note judge (notes in order, cents) is recorded for information and "
             "never used to choose")


def radial_jitter(posts, sigma, seed):
    p = np.array(posts, dtype=float)
    rng = np.random.default_rng(seed)
    u = p[:, :2] / np.linalg.norm(p[:, :2], axis=1, keepdims=True)
    p[:, :2] += u * rng.normal(0.0, sigma, size=(len(p), 1))
    return p


def harmonic_ratios_db(echo, t_echo0, notes, fs=FS):
    """Per note: 20 log10(|E(2f)| / |E(f)|) of the echo (mean over claps of the power), Hann window over the middle
    60 % of the note (plus the clap's ~3 ms centroid delay). Physics of the realization, not a judge."""
    out = []
    for f, a, b in notes:
        t1, t2 = t_echo0 + 0.003 + a + 0.2 * (b - a), t_echo0 + 0.003 + a + 0.8 * (b - a)
        seg = echo[:, int(t1 * fs):int(t2 * fs)]
        w = np.hanning(seg.shape[1])
        n = 1 << 14
        S = np.mean(np.abs(np.fft.rfft(seg * w, n, axis=1)) ** 2, axis=0)
        fr = np.fft.rfftfreq(n, 1 / fs)

        def pk(x):
            m = (fr > x * 0.97) & (fr < x * 1.03)
            return S[m].max()

        out.append(float(10 * np.log10(pk(2 * f) / pk(f))) if 2 * f < fs / 2 else None)
    return out


def note_judge_info(cfg, echo, target, t_echo0, band):
    v = stage_values(cfg.stage, echo, target, t_echo0, band=band)
    return {"notes_in_order": float(np.mean([x["notes_in_order"] for x in v])),
            "note_cents_max": float(np.mean([x["note_cents_max"] for x in v])),
            "n_notes_detected": [int(x["n_notes_detected"]) for x in v]}


def study():
    torch.set_num_threads(4)
    cfg = CONFIG
    t_all = time.time()
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    band_full = clap_band(claps)
    band_cap = (band_full[0], min(band_full[1], cfg.band_max_hz))
    t_echo0 = 2 * cfg.r0 / 343.0
    cl = torch.as_tensor(claps)
    profiles = {}
    rows, angle_rows = [], []

    def evaluate(posts, sc, with_jitter=True):
        e_full = post_echo(posts, cl, sc, mode="2d", n_out=n_out, band=band_full).numpy()
        e_cap = band_limit(e_full, band_cap[0], band_cap[1])
        e3 = post_echo(posts, cl, sc, mode="3d", n_out=n_out, band=band_full).numpy()
        r = {"loss_tier0_full_band": window_loss(e_full, target.audio, band_full, cfg.r0, 343.0, claps.shape[1]),
             "loss_tier0_capped_band": window_loss(e_cap, target.audio, band_cap, cfg.r0, 343.0, claps.shape[1]),
             "echo_level_db_2d": float(np.mean(echo_level_db(e_full))),
             "echo_level_db_3d": float(np.mean(echo_level_db(e3))),
             "harmonic_to_fundamental_db": harmonic_ratios_db(e_full, t_echo0, target.notes),
             "info_only_note_judge_full_band": note_judge_info(cfg, e_full, target, t_echo0, band_full),
             "info_only_note_judge_capped_band": note_judge_info(cfg, e_cap, target, t_echo0, band_cap)}
        if with_jitter:
            jit = []
            for sig in JITTER_M:
                ls = []
                for sd in JITTER_SEEDS:
                    pj = radial_jitter(posts, sig, sd)
                    ej = post_echo(pj, cl, stage_scene(cfg, pj), mode="2d", n_out=n_out, band=band_full).numpy()
                    ls.append(window_loss(ej, target.audio, band_full, cfg.r0, 343.0, claps.shape[1]))
                jit.append({"sigma_m": sig, "loss_mean": float(np.mean(ls)), "loss_max": float(np.max(ls))})
            r["jitter"] = jit
        return r

    # profile solve settings (2 cm): window loss of the profile echo, with/without Tier 0 equalization (judge-free)
    from stages.common import tier0_equalize

    solve_rows = []
    for steps, lr in ((300, 0.02), (1200, 0.05)):
        pr, rs = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=0.02, steps=steps, lr=lr,
                               w_mel=cfg.w_mel, n_out=n_out, band=band_cap)
        _, eqh = tier0_equalize(replace(cfg, a_ref=0.02), pr, target, claps, band_cap, n_out, rs.n0 / FS, 2)
        solve_rows.append({"steps": steps, "lr": lr, "solve_best_loss": rs.info["best_loss"],
                           "loss_after_equalize_rounds_0_1_2": eqh["loss"], "label": f"solve {steps} steps lr {lr}",
                           "loss": eqh["loss"][0]})
        print("solve", solve_rows[-1], flush=True)
    for a in STUDY_RADII:
        c_a = replace(cfg, a_ref=a, catalog=(a,))
        prof_n, res = solve_profile(target, claps, stage_scene(c_a), r0=cfg.r0, dr=cfg.dr, a_ref=a, steps=cfg.steps,
                                    lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out, band=band_cap)
        profiles[a] = prof_n
        print(f"profile a={a}: loss {res.info['best_loss']:.3f} ({res.history['wall_s']:.0f} s)", flush=True)
        for fill in STUDY_FILLS:
            from echo.realize import scale_profile
            from echo.scene import fill_fraction

            p = scale_profile(prof_n, fill, cfg.r0, cfg.dr, a, half_angle_deg=cfg.half_angle_deg)
            for mode, K in STUDY_MODES:
                sc0 = stage_scene(c_a)
                t = time.time()
                posts, st = realize(p, sc0, cfg.seed, r0=cfg.r0, dr=cfg.dr, a_ref=a, radii=(a,), band=band_cap,
                                    shadow_depth=cfg.shadow_depth, claps=claps, refine_steps=0, mode=mode,
                                    posts_per_period=K)
                sc = stage_scene(c_a, posts)
                r = {"radius_m": a, "fill_target": fill, "mode": mode, "posts_per_period": K, "half_angle_deg": cfg.half_angle_deg,
                     "n_posts": int(len(posts)), "fill_realized": float(fill_fraction(sc)),
                     "dropped": int(st["dropped"]), "n_rings": st.get("n_rings"),
                     "max_posts_per_ring": st.get("max_posts_per_ring"), "realize_s": round(time.time() - t, 1),
                     "label": f"a={a * 100:.0f}cm fill={fill * 100:.1f}% {mode} K={K}"}
                r.update(evaluate(posts, sc))
                r["loss"] = r["loss_tier0_full_band"]
                rows.append(r)
                j = r["info_only_note_judge_full_band"]
                print(f"{r['label']:44s} N={r['n_posts']:5d} drop={r['dropped']:3d} loss full {r['loss']:.3f} "
                      f"cap {r['loss_tier0_capped_band']:.3f} L3d {r['echo_level_db_3d']:.1f} "
                      f"H2/H1 {[None if x is None else round(x, 1) for x in r['harmonic_to_fundamental_db']]} "
                      f"jit {[round(x['loss_mean'], 3) for x in r['jitter']]} "
                      f"[info: order {j['notes_in_order']:.2f} cents {j['note_cents_max']:.1f}]", flush=True)
    # half-angle at the configured radius / fill / K: level, loss, and the 10 cm sideways listener (sweet spot)
    from echo.realize import scale_profile
    from echo.robustness import listener_shift_s
    from echo.scene import Scene, fill_fraction

    for ha in STUDY_HALF_ANGLES:
        c_h = replace(cfg, half_angle_deg=ha)
        p = scale_profile(profiles[cfg.a_ref], cfg.target_fill, cfg.r0, cfg.dr, cfg.a_ref, half_angle_deg=ha)
        posts, st = realize(p, stage_scene(c_h), cfg.seed, r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref, radii=(cfg.a_ref,),
                            band=band_cap, shadow_depth=cfg.shadow_depth, claps=claps, refine_steps=0,
                            mode=cfg.realization, posts_per_period=cfg.posts_per_period)
        sc = stage_scene(c_h, posts)
        r = {"half_angle_deg": ha, "n_posts": int(len(posts)), "fill_realized": float(fill_fraction(sc)),
             "dropped": int(st["dropped"])}
        r.update(evaluate(posts, sc, with_jitter=False))
        for off in ((0.0, 0.1), (0.0, 0.2)):
            L = sc.listener + np.asarray(off)
            sc2 = Scene(source=sc.source, listener=L, posts=posts, half_angle_deg=ha)
            sh = listener_shift_s(sc, L, cfg.r0 + 343.0 * len(target.audio) / FS / 4.0)
            e = post_echo(posts, cl, sc2, mode="2d", n_out=n_out, band=band_full).numpy()
            e = np.roll(e, -int(round(sh * FS)), -1)
            r[f"loss_side_{off[1] * 100:.0f}cm"] = window_loss(e, target.audio, band_full, cfg.r0, 343.0,
                                                               claps.shape[1])
        # Tier 1 cost proxy: bounding box of the wedge at f_max with ppw 10 (cells), plus a fixed 1 m margin
        r_hi = cfg.r0 + 343.0 * 0.18 / 2 + 0.1
        dx = 343.0 / cfg.f_max / 10
        r["tier1_cells_est"] = int((r_hi - cfg.r0 * np.cos(np.radians(ha)) + 1.0) / dx
                                   * (2 * r_hi * np.sin(np.radians(ha)) + 1.0) / dx)
        r["loss"] = r["loss_tier0_full_band"]
        r["label"] = f"half-angle {ha:.0f} deg"
        angle_rows.append(r)
        print(f"half {ha:4.1f}: N={r['n_posts']} fill {r['fill_realized']:.4f} loss {r['loss']:.3f} L3d "
              f"{r['echo_level_db_3d']:.1f} side10 {r['loss_side_10cm']:.3f} side20 {r['loss_side_20cm']:.3f} "
              f"cells {r['tier1_cells_est']:.3g}", flush=True)
    out = {"what": "Tier 0 design study, stage 2 (2D for losses/judges, 3D for level); phase-locked realization",
           "selection": SELECTION, "band_full_hz": list(band_full), "band_capped_hz": list(band_cap),
           "jitter": f"radial Gaussian sigma {JITTER_M} m, seeds {JITTER_SEEDS}",
           "solve_rows": solve_rows, "rows": rows, "half_angle_rows": angle_rows, "wall_s": time.time() - t_all}
    path = export.RUNS / cfg.stage / "_studies" / "design_study_tier0.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path, f"{time.time() - t_all:.0f} s")


if __name__ == "__main__":
    if "--study" in sys.argv[1:]:
        study()
    else:
        stage_main(CONFIG)
