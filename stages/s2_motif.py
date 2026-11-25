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

CONFIG_V1 = StageConfig(  # first design ("2 cm, 10 deg"): failed on Tier 1 by extinction (task-7 report)
    stage="s2_motif",
    title="Motif C6 E6 G6 C7, 45 ms each (v1: 2 cm posts, 10 deg)",
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
    target_fill=0.016,  # picked on Tier 1 by spectrogram loss: 0.8 % -> 5.637, 1.6 % -> 5.568 (sweep log in _studies)
    steps=1200,  # profile solve: 1200 Adam steps at lr 0.05 (lower window loss than 300 at 0.02; see the study)
    lr=0.05,
    # Realization, radius and fill chosen on Tier 0 (runs/s2_motif/_studies/design_study_tier0.json) by the spectrogram
    # loss under 2 and 5 mm radial jitter (stage 1 measured its Tier 1 residue as ~3.5 mm-equivalent jitter): the pure
    # comb K = 1 of 2 cm posts has the lowest jittered loss at every fill (its 2nd harmonics are coherent: they keep the
    # fundamental's periodicity); K = 2 quantile, uniform K = 4/6 and sampling trade them for incoherent noise.
    realization="phase_locked",
    posts_per_period=1,
    # Tier 1 density sweep (0.008, 0.016) was run once (runs/s2_motif/_studies/tier1_density_sweep.log, Tier 1 loss
    # only); its pick is fixed here so the final run spends its Tier 1 budget on a correction round instead.
    fill_candidates=None,
    correction_rounds=2,  # round 0 + one window-gain correction round (extinction: round-0 gains 0.5 -> 2.0)
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
    cfg = CONFIG_V1
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




# ======================================================================================= v2: designed around extinction
# Thin-post scaling: backscatter amplitude ~ (ka)^2, total scattering width sigma ~ a (ka)^3, so extinction per unit of
# echo ~ k a^2 / (lateral width). v1 used 2 cm posts in a 10 deg wedge; v2 uses 1 cm posts in the full 20 deg wedge
# and budgets the two-way optical depth tau = 2 int n_A sigma d rho (Tier 0's rigid-cylinder partial-wave series)
# before any solve, then pre-compensates the predicted amplitude loss exp(tau/2) along range (profile_transform).


def scattering_width(radius, f, c=343.0, n_theta=2048):
    """Total scattering width (m) of a rigid cylinder: sigma = int (2 / (pi k)) |T(theta)|^2 d theta (T from
    echo.tier0.cylinder_response). Rayleigh check: (3 pi^2 / 4) k^3 a^4 (0.52 mm for 1 cm at 1047 Hz)."""
    from echo.tier0 import cylinder_response

    th = (np.arange(n_theta) + 0.5) * 2 * np.pi / n_theta
    k = 2 * np.pi * np.asarray(f, dtype=float) / c
    T = cylinder_response(radius, np.asarray(f, dtype=float)[..., None], th)
    return 2.0 / (np.pi * k) * np.mean(np.abs(T) ** 2, axis=-1) * 2 * np.pi


def local_frequency(rho, r0, target, c=343.0):
    """Target frequency (Hz) of the echo from bistatic range rho (t = 2 (rho - r0) / c into the target)."""
    tt, ff = target.f_track
    return np.interp(2.0 * (np.asarray(rho) - r0) / c, tt, ff)


def optical_depth(cfg, profile, f_hz, c=343.0):
    """One-way optical depth int_r0^rho n_A sigma(f) d rho' (nepers of intensity) for a profile in a_ref posts per bin:
    n_A = posts per metre of range / arc width 2 rho theta. f_hz scalar or per-bin array (sigma(f) of the wave whose
    echo returns from rho). Two-way intensity loss at rho, dB = 10 log10(e) * 2 * value."""
    rho = cfg.r0 + cfg.dr * np.arange(len(profile))
    n_a = np.asarray(profile, dtype=float) / cfg.dr / (2 * rho * np.radians(cfg.half_angle_deg))
    f = np.broadcast_to(np.asarray(f_hz, dtype=float), rho.shape)
    fu = np.unique(np.round(f, 0))
    sig = np.interp(f, fu, scattering_width(cfg.a_ref, fu)) if len(fu) > 1 else np.full(rho.shape, scattering_width(cfg.a_ref, fu[0]))
    if f.ndim and len(np.unique(f)) > 1:  # per-bin frequency: tau(rho) = int_r0^rho n_A(rho') sigma(f(rho)) d rho'
        return np.cumsum(n_a * cfg.dr) * sig
    return np.cumsum(n_a * sig * cfg.dr)


def extinction_precomp(cfg, profile, iterations=3):
    """profile_transform: pre-compensate the predicted extinction. sigma is a power cross-section, so the coherent
    pressure falls by exp(-tau1 / 2) per pass and by exp(-tau1) out and back (tau1 = one-way optical depth at the
    local target frequency, `optical_depth`). The profile is multiplied by exp(+tau1(rho)); tau1 depends on the
    compensated profile, so the fixed point is iterated `iterations` times. Judge-free (geometry + cylinder model)."""
    target = cfg.make_target()
    p0 = np.asarray(profile, dtype=float)
    rho = cfg.r0 + cfg.dr * np.arange(len(p0))
    f = local_frequency(rho, cfg.r0, target)
    p = p0.copy()
    for _ in range(iterations):
        tau1 = optical_depth(cfg, p, f)
        p = p0 * np.exp(tau1)
    return p


def note_levels_3d(echo3d, t_echo0, notes, fs=FS):
    """Per note: 20 log10 (peak |echo| in the note window), mean over claps, dB re the direct clap (3D Tier 0)."""
    out = []
    for f, a, b in notes:
        seg = echo3d[:, int((t_echo0 + a) * fs):int((t_echo0 + b + 0.004) * fs)]
        out.append(float(np.mean(20 * np.log10(np.max(np.abs(seg), axis=-1) + 1e-30))))
    return out


CONFIG = replace(
    CONFIG_V1,
    title="Motif C6 E6 G6 C7, 45 ms each (v2: 1 cm posts, 20 deg, extinction-budgeted)",
    tag="s2v2",
    half_angle_deg=20.0,
    catalog=(0.01,),
    a_ref=0.01,
    target_fill=0.001,  # study v2 pick: predicted two-way extinction at C7 (far end) 3.4 dB; K=1 lowest jittered loss
    posts_per_period=1,
    profile_transform=extinction_precomp,
    fill_candidates=None,
    correction_rounds=2,  # round 0 + at most one correction round
    correction_clip=(0.25, 4.0),  # widened from (0.5, 2): v1's round-0 gains hit both clip ends
    threads=8,
    robustness_c_cases=(),  # not run (cost): c alone shifts pitch by -61 / +30 cents (331 / 349 m/s)
    design_study_files=("_studies/design_study_tier0.json", "_studies/design_study_v2_tier0.json"),
)

V2_FILLS = (0.001, 0.002, 0.004)
V2_K = (1, 2, 3)


def study_v2():
    """Tier 0 study for v2: sigma(f) table, optical-depth budget vs fill, K at each fill (jittered loss, full band to
    4 kHz), harmonic ratios and per-note 3D levels. Selection: lowest mean jittered loss among fills whose predicted
    two-way loss at C7 (far end) is <= 6 dB. Judge columns are information only."""
    torch.set_num_threads(2)  # the machine is shared (load 30+): oversubscribed torch threads stall
    cfg = CONFIG
    t_all = time.time()
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    band_full = clap_band(claps)
    band_cap = (band_full[0], min(band_full[1], cfg.band_max_hz))
    t_echo0 = 2 * cfg.r0 / 343.0
    cl = torch.as_tensor(claps)
    freqs = list(MOTIF_HZ) + [2500.0]
    sig_rows = [{"f_hz": f, "sigma_mm": float(scattering_width(cfg.a_ref, f) * 1e3),
                 "ka": float(2 * np.pi * f * cfg.a_ref / 343.0)} for f in freqs]
    print("sigma", sig_rows, flush=True)
    prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref, steps=cfg.steps,
                                lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out, band=band_cap, verbose=True, log_every=100)
    print(f"profile loss {res.info['best_loss']:.3f}", flush=True)
    from echo.realize import scale_profile
    from echo.scene import fill_fraction

    rho = cfg.r0 + cfg.dr * np.arange(len(prof_n))
    rows = []
    for fill in V2_FILLS:
        p = scale_profile(prof_n, fill, cfg.r0, cfg.dr, cfg.a_ref, half_angle_deg=cfg.half_angle_deg)
        tau_c7 = optical_depth(cfg, p, 2093.0)
        f_loc = local_frequency(rho, cfg.r0, target)
        tau_loc = optical_depth(cfg, p, f_loc)
        budget = {"two_way_loss_db_at_end_C7": float(10 * np.log10(np.e) * 2 * tau_c7[-1]),
                  "two_way_loss_db_per_note_local_f": [float(10 * np.log10(np.e) * 2 * np.interp(
                      cfg.r0 + 343.0 * (0.5 * (a + b)) / 2, rho, tau_loc)) for _, a, b in target.notes]}
        for K in V2_K:
            posts, st = realize(p, stage_scene(cfg), cfg.seed, r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                                radii=(cfg.a_ref,), band=band_cap, shadow_depth=cfg.shadow_depth, claps=claps,
                                refine_steps=0, mode="phase_locked", posts_per_period=K)
            sc = stage_scene(cfg, posts)
            e_full = post_echo(posts, cl, sc, mode="2d", n_out=n_out, band=band_full).numpy()
            e_cap = band_limit(e_full, band_cap[0], band_cap[1])
            e3 = post_echo(posts, cl, sc, mode="3d", n_out=n_out, band=band_full).numpy()
            jit = []
            for sgm in JITTER_M:
                ls = []
                for sd in JITTER_SEEDS:
                    pj = radial_jitter(posts, sgm, sd)
                    ej = post_echo(pj, cl, stage_scene(cfg, pj), mode="2d", n_out=n_out, band=band_full).numpy()
                    ls.append(window_loss(ej, target.audio, band_full, cfg.r0, 343.0, claps.shape[1]))
                jit.append({"sigma_m": sgm, "loss_mean": float(np.mean(ls))})
            lv = note_levels_3d(e3, t_echo0, target.notes)
            r = {"fill_target": fill, "posts_per_period": K, "n_posts": int(len(posts)),
                 "fill_realized": float(fill_fraction(sc)), "dropped": int(st["dropped"]),
                 "loss_tier0_full_band": window_loss(e_full, target.audio, band_full, cfg.r0, 343.0, claps.shape[1]),
                 "loss_tier0_capped_band": window_loss(e_cap, target.audio, band_cap, cfg.r0, 343.0, claps.shape[1]),
                 "jitter": jit, "jitter_loss_mean": float(np.mean([j["loss_mean"] for j in jit])),
                 "echo_level_db_3d": float(np.mean(echo_level_db(e3))),
                 "note_level_db_3d": lv, "note_spl_db": [110.46 + x for x in lv],
                 "harmonic_to_fundamental_db": harmonic_ratios_db(e_full, t_echo0, target.notes),
                 "extinction_budget": budget,
                 "info_only_note_judge_capped_band": note_judge_info(cfg, e_cap, target, t_echo0, band_cap),
                 "label": f"1cm 20deg fill={fill * 100:.2f}% K={K}"}
            r["loss"] = r["jitter_loss_mean"]
            rows.append(r)
            j = r["info_only_note_judge_capped_band"]
            print(f"{r['label']:28s} N={r['n_posts']:5d} drop={r['dropped']} loss {r['loss_tier0_full_band']:.3f} "
                  f"jit {r['jitter_loss_mean']:.3f} ext C7 end {budget['two_way_loss_db_at_end_C7']:.1f} dB "
                  f"notes {[round(x, 1) for x in budget['two_way_loss_db_per_note_local_f']]} "
                  f"SPL/note {[round(x, 1) for x in r['note_spl_db']]} H2/H1 "
                  f"{[round(x, 1) for x in r['harmonic_to_fundamental_db']]} "
                  f"[info: {j['notes_in_order']:.1f} / {j['note_cents_max']:.0f}]", flush=True)
    ok = [r for r in rows if r["extinction_budget"]["two_way_loss_db_at_end_C7"] <= 6.0]
    pick = min(ok or rows, key=lambda r: r["jitter_loss_mean"])
    out = {"what": "Tier 0 design study v2 (1 cm posts, 20 deg): optical-depth budget, K, levels",
           "selection": "lowest mean Tier 0 loss under 2/5 mm radial jitter (full band 898-4000 Hz) among fills whose "
                        "predicted two-way extinction at C7 at the far end is <= 6 dB; judges information only",
           "sigma": sig_rows, "profile_solve_loss": res.info["best_loss"], "rows": rows,
           "pick": {"fill": pick["fill_target"], "posts_per_period": pick["posts_per_period"]},
           "wall_s": time.time() - t_all}
    path = export.RUNS / cfg.stage / "_studies" / "design_study_v2_tier0.json"
    path.write_text(json.dumps(out, indent=1))
    print("pick", out["pick"], "wrote", path, f"{time.time() - t_all:.0f} s", flush=True)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--study" in argv:
        study_v2() if "v2" in argv else study()
    elif "--design" in argv:
        i = argv.index("--design")
        which = argv[i + 1]
        rest = argv[:i] + argv[i + 2:]
        stage_main({"v1": CONFIG_V1, "v2": CONFIG}[which], rest)
    else:
        stage_main(CONFIG)
