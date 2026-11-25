"""Stage 3: melody, the opening 8 notes of Ode to Joy (E6 E6 F6 G6 G6 F6 E6 D6), 100 ms per note (800 ms, 137 m)
and the spec's 60 ms-note variant (480 ms, 82 m).

    uv run python -m stages.s3_melody                    # 100 ms: Tier 0 design, Tier 1 run(s), field, robustness
    uv run python -m stages.s3_melody --note-ms 60       # 60 ms variant (own run folder <id>_60ms; free robustness only)
    uv run python -m stages.s3_melody --tier0-only       # Tier 0 only (status tier0_only)
    uv run python -m stages.s3_melody --study            # Tier 0 design study + note-length sweep -> runs/s3_melody/_studies/

Grid and domain (spec: Tier 1 grid from the highest target frequency; budget 20 min per run, narrow the wedge if over):
the top note is G6 = 1568 Hz, so f_max = 2 kHz (dx 16.7 mm, ppw 10), the validated stage-3 grid where 2 cm posts are
validated for backscatter and at all angles. Excitation and every Tier 0 <-> Tier 1 comparison are band-limited to
f_max (band_max_hz): the clap's 2-4 kHz content and the comb's 2nd harmonics (2350-3136 Hz) are invisible to Tier 1;
the Tier 0 full-band echo is reported next to it (metrics.s3_extra.tier0_full_band). The wedge is narrowed to
+-HALF_ANGLE_DEG so one 100 ms run fits ~15 min on an idle 8-thread machine (cost table in the study json).

Selection rule (also in the study json): candidates are compared by the Tier 0 spectrogram loss (echo.inverse.window_loss)
in the Tier 1 band; the note judge is recorded for information only and never used to choose. The harmonic-to-
fundamental ratio per note and the per-note level are physics of the realization, not judges.
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import torch

from echo import export
from echo.clap import band_limit, clap_family
from echo.inverse import clap_band, solve_profile, window_loss
from echo.metrics import echo_level_db, stage_values
from echo.realize import realize, scale_profile
from echo.scene import C0, FS, fill_fraction
from echo.targets import melody
from echo.tier0 import cylinder_response, post_echo
from stages.common import StageConfig, run_stage, stage_main, stage_scene

STAGE = "s3_melody"
STUDY = Path(export.RUNS) / STAGE / "_studies"
HALF_ANGLE_DEG = 20.0  # the spec wedge; posts are clipped to a constant-width strip (HALF_WIDTH_M) inside it
HALF_WIDTH_M = 1.0  # strip |y| <= 1 m: Tier 1 domain ~3.3 m wide (see tier1_cost in the study json)
N_POSTS = 2500  # post count (max_posts); extinction budget in the study json
A_REF = 0.01  # thinnest post: extinction per unit echo ~ k a^2; validated for backscatter on the 2.5 kHz grid only
TARGET_FILL = 0.01  # nominal: the post count is set by max_posts=N_POSTS (wedge-area fill is meaningless for a strip)
SPREAD_UNDO = 0.5  # profile_transform: undo half of the 2D spreading compensation (posts ~ rho^0.5, not rho^1)
POSTS_PER_PERIOD = 1
# study outputs (runs/s3_melody/_studies/), copied into metrics.design_study (note_length_sweep is Tier 0 ONLY)
STUDY_FILES = ("design_study_tier0.json", "note_length_sweep_tier0.json", "strip_density_tier0.json",
               "wedge_density_tier0.json",
               "design_study_tier0_wedge1deg_2cm.json", "fullwedge_tier0.json")  # the last two: the first (abandoned) +-1 deg 2 cm design


def note_s_of(note_ms):
    return note_ms / 1000.0


def duration_of(note_ms):
    # 2 r0 / c = 17.5 ms to the first echo + 8 notes + 8 ms clap + 10 ms margin
    return round(2 * 3.0 / C0 + 8 * note_ms / 1000.0 + 0.008 + 0.010, 4)


def make_config(note_ms=100, **kw) -> StageConfig:
    cfg = StageConfig(
        stage=STAGE,
        title=f"Melody, Ode to Joy opening (E6 E6 F6 G6 G6 F6 E6 D6), {note_ms} ms notes",
        tag="s3" if note_ms == 100 else f"s3_{note_ms}ms",
        make_target=lambda: melody(note_ms=note_ms),
        duration_s=duration_of(note_ms),
        note_s=note_s_of(note_ms),
        f_max=2500.0,
        band_max_hz=2500.0,
        half_angle_deg=HALF_ANGLE_DEG,
        max_half_width_m=HALF_WIDTH_M,
        catalog=(A_REF,),
        a_ref=A_REF,
        target_fill=TARGET_FILL,
        # profile solve: the analytic initial profile (the target waveform laid out along range, + bias) already has
        # a lower loss than Adam reaches at lr 0.05 (60 ms log: 1.28 at step 0 -> 2.14 at step 25); the solve keeps
        # its best iterate. 800 ms targets cost ~4-7 s per step on the shared machine, so a short, gentle solve.
        steps=0,
        lr=0.005,
        realization="phase_locked",
        posts_per_period=POSTS_PER_PERIOD,
        fill_candidates=None,  # no Tier 1 density sweep (budget: <= 5 Tier 1 runs for the whole stage)
        # extinction pre-compensation (extinction_precomp) is available but OFF: at the chosen fill the estimated loss
        # (~200 dB at the last note, wedge_density_tier0.json) is far beyond any pre-compensation (capped at 18 dB)
        profile_transform=lambda c, p: strip_transform(c, p),
        tier0_equalize_rounds=3,  # flatten the per-note Tier 0 levels toward the perfect echo (judge-free window gains)
        correction_rounds=1,  # one stretch-compensated run, field recorded in it (budget: <= 5 Tier 1 runs in total)
        threads=8,
        max_posts=N_POSTS,
        robustness=True,
        robustness_c_cases=(),  # not run (cost): each needs a ~10 min empty-scene run plus a ~15 min full run
        robustness_jitter=False,  # not run (time: the 100 ms run alone is ~35 min on the 2.5 kHz grid); free cases only
        field_dt=0.6e-3,  # 0.835 s at 0.6 ms per frame -> ~1,390 frames (<= ~1,500; strip video stays small)
        design_study_files=STUDY_FILES,
        notes=(f"Stage 3 ({note_ms} ms notes). Tier 1 grid f_max 2 kHz from the top note G6 1568 Hz; the clap's 2-4 kHz "
               f"content and comb harmonics above 2 kHz are invisible to Tier 1 at this grid (Tier 0 full band reported "
               f"alongside). Wedge narrowed to +-{HALF_ANGLE_DEG} deg for the Tier 1 budget."),
    )
    return replace(cfg, **kw)


CONFIG = make_config(100)


# ------------------------------------------------------------------------------------------------ physics helpers
def sigma_total_m(a, f, c=C0, n_ang=721):
    """2D total scattering width of a rigid cylinder (m): (2 / (pi k)) * integral |T(phi)|^2 dphi (cylinder_response
    is T with p_s = sqrt(2/(pi k r)) e^{i(kr - pi/4)} T)."""
    k = 2 * math.pi * f / c
    ph = np.linspace(0, 2 * math.pi, n_ang, endpoint=False)
    T = np.asarray(cylinder_response(a, f, angle=ph, c=c))
    return float(2.0 / (math.pi * k) * np.mean(np.abs(T) ** 2) * 2 * math.pi)


def extinction_estimate_db(posts, scene, f, rho_eval, half_width_m="strip"):
    """Single-scatterer optical-depth estimate of the two-way coherent loss (dB) of the echo from bistatic range
    rho_eval: each post at range r < rho_eval removes sigma / (2 r tan(half-angle)) of the wedge's rays, out and back.
    Rough: ignores forward scattering refill; stage 1 measured ~7 dB fade across its note where this gives ~10 dB."""
    if len(posts) == 0:
        return 0.0
    s = sigma_total_m(float(np.median(posts[:, 2])), f)
    r = np.linalg.norm(posts[:, :2], axis=1)
    m = r < rho_eval
    w = 2 * r[m] * math.tan(math.radians(scene.half_angle_deg))
    hw = HALF_WIDTH_M if half_width_m == "strip" else half_width_m  # None: the full wedge
    if hw is not None:
        w = np.minimum(w, 2 * hw)
    tau = np.sum(s / w)  # one-way intensity optical depth
    return float(8.686 * tau)  # two-way amplitude: exp(-tau/2) each way -> 20 log10 e^{-tau} = 8.686 tau dB


EXT_PRECOMP_MAX_DB = 18.0  # cap on the extinction pre-compensation gain (runaway guard)


def _note_freq_at(rho, cfg, target):
    """Frequency of the target note whose echo comes from bistatic range rho (t = 2 (rho - r0) / c into the melody)."""
    t = 2.0 * (np.asarray(rho) - cfg.r0) / C0
    f = np.full(np.shape(t), float(target.notes[0][0]))
    for fn, a, b in target.notes:
        f = np.where(t >= a, fn, f)
    return f


def extinction_profile_db(profile, cfg, target):
    """Estimated two-way coherent loss (dB) of the echo from every profile bin, from the profile's own post density
    (profile units: a_ref posts per bin): 8.686 * sum_{bins nearer} p_i sigma(f) / (2 rho_i tan(half-angle)).
    The same estimate reproduced stage 1's measured Tier 1 fade (7.2 dB across the note) as 7.4 dB."""
    p = np.clip(np.asarray(profile, dtype=float), 0, None)
    rho = cfg.r0 + cfg.dr * np.arange(len(p))
    f = _note_freq_at(rho, cfg, target)
    sig = {float(x): sigma_total_m(cfg.a_ref, float(x)) for x in np.unique(f)}
    s = np.array([sig[float(x)] for x in f])
    width = 2 * rho * math.tan(math.radians(cfg.half_angle_deg))
    if cfg.max_half_width_m is not None:
        width = np.minimum(width, 2 * cfg.max_half_width_m)
    dens = p / width  # posts per bin per metre of lateral width
    tau = np.concatenate([[0.0], np.cumsum(dens)[:-1]]) * s
    return 8.686 * tau


def strip_transform(cfg, profile):
    """Stage-3 profile shaping (judge-free physics): (1) undo SPREAD_UNDO of the solve's 2D spreading compensation
    (posts ~ rho^(1 - SPREAD_UNDO) instead of rho: a constant-width strip cannot hold rho-proportional rings without
    making the far field opaque; the echo then falls ~ 12.8 dB from the first to the last note, inside the judge's
    25 dB activity window), (2) extinction pre-compensation; total post count kept."""
    p = np.clip(np.asarray(profile, dtype=float), 0, None)
    rho = cfg.r0 + cfg.dr * np.arange(len(p))
    q = p * (rho / rho.mean()) ** (-SPREAD_UNDO)
    q *= p.sum() / q.sum()
    return extinction_precomp(cfg, q)


def extinction_precomp(cfg, profile, iters=30, damp=0.5):
    """Physics pre-compensation (judge-free): scale the profile by the estimated two-way coherent loss so every note
    arrives at its designed level, keeping the total post count (fill). Fixed point p = p0 * g(p), g = 10^(L/20) of
    `extinction_profile_db` of p itself, capped at EXT_PRECOMP_MAX_DB, damped."""
    target = cfg.make_target()
    p0 = np.clip(np.asarray(profile, dtype=float), 0, None)
    mass = p0.sum()
    p = p0.copy()
    for _ in range(iters):
        g = 10 ** (np.minimum(extinction_profile_db(p, cfg, target), EXT_PRECOMP_MAX_DB) / 20)
        q = p0 * g
        q *= mass / q.sum()
        p = (1 - damp) * p + damp * q
    return p


def note_windows(t_echo0, notes, frac=(0.2, 0.8), lag=0.003):
    return [(t_echo0 + lag + a + frac[0] * (b - a), t_echo0 + lag + a + frac[1] * (b - a)) for _, a, b in notes]


def note_levels_db(echo, t_echo0, notes, fs=FS):
    """Per note: RMS level (dB, mean power over claps) of the echo over the middle 60 % of the note, re the echo's
    direct-clap units (20 log10 of RMS)."""
    e = np.atleast_2d(echo)
    out = []
    for t1, t2 in note_windows(t_echo0, notes):
        seg = e[:, int(t1 * fs):int(t2 * fs)]
        out.append(float(10 * np.log10(np.mean(seg ** 2) + 1e-30)))
    return out


def harmonic_ratios_db(echo, t_echo0, notes, fs=FS):
    """Per note: 20 log10(|E(2f)| / |E(f)|) (mean power over claps, Hann over the middle 60 % of the note)."""
    out = []
    for (f, _, _), (t1, t2) in zip(notes, note_windows(t_echo0, notes)):
        seg = np.atleast_2d(echo)[:, int(t1 * fs):int(t2 * fs)]
        n = 1 << 14
        S = np.mean(np.abs(np.fft.rfft(seg * np.hanning(seg.shape[1]), n, axis=1)) ** 2, axis=0)
        fr = np.fft.rfftfreq(n, 1 / fs)

        def pk(x):
            return S[(fr > x * 0.97) & (fr < x * 1.03)].max()

        out.append(float(10 * np.log10(pk(2 * f) / pk(f))))
    return out


def judge_info(echo, target, t_echo0, band):
    v = stage_values(STAGE, echo, target, t_echo0, band=band)
    return {"notes_in_order": float(np.mean([x["notes_in_order"] for x in v])),
            "note_cents_max": float(np.mean([x["note_cents_max"] for x in v])),
            "n_notes_detected": [int(x["n_notes_detected"]) for x in v],
            "per_clap_in_order": [float(x["notes_in_order"]) for x in v]}


# ------------------------------------------------------------------------------------------------ Tier 0 study
STUDY_FILLS = (TARGET_FILL,)  # post count = N_POSTS (max_posts)
STUDY_MODES = (("phase_locked", 1), ("phase_locked", 2), ("phase_locked_uniform", 4))
SWEEP_NOTE_MS = (100, 80, 60, 45, 30, 20)
SELECTION = ("K chosen by the Tier 0 spectrogram loss (window_loss) on the FULL clap band under 2 mm radial jitter "
             "(seed 11); the note judge (notes in order, cents) is recorded for information and never used to "
             "choose; extinction estimate and per-note levels are physics, reported to explain the fill choice")


def _design(cfg, prof_n, claps, band_cap, fill, mode, K, precomp=True):
    p = scale_profile(prof_n, fill, cfg.r0, cfg.dr, cfg.a_ref, half_angle_deg=cfg.half_angle_deg)
    p = p * min(1.0, cfg.max_posts / p.sum())  # as the driver: the post count cap
    if precomp and cfg.profile_transform is not None:
        p = cfg.profile_transform(cfg, p)
    posts, st = realize(p, stage_scene(cfg), cfg.seed, r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref, radii=(cfg.a_ref,),
                        band=band_cap, shadow_depth=cfg.shadow_depth, claps=claps, refine_steps=0, mode=mode,
                        posts_per_period=K, max_half_width_m=cfg.max_half_width_m)
    return posts, st


def _evaluate(cfg, posts, target, claps, band_full, band_cap, t_echo0, n_out):
    sc = stage_scene(cfg, posts)
    cl = torch.as_tensor(claps)
    e_full = post_echo(posts, cl, sc, mode="2d", n_out=n_out, band=band_full).numpy()
    e_cap = band_limit(e_full, band_cap[0], band_cap[1])
    e3 = post_echo(posts, cl, sc, mode="3d", n_out=n_out, band=band_full).numpy()
    lv2 = note_levels_db(e_cap, t_echo0, target.notes)
    lv3 = note_levels_db(e3, t_echo0, target.notes)
    rho_last = cfg.r0 + C0 * target.notes[-1][2] / 2
    return {"n_posts": int(len(posts)), "fill_realized": float(fill_fraction(sc)), "depth_m": float(sc.depth_m),
            "loss_tier0_capped_band": window_loss(e_cap, target.audio, band_cap, cfg.r0, C0, claps.shape[1]),
            "loss_tier0_full_band": window_loss(e_full, target.audio, band_full, cfg.r0, C0, claps.shape[1]),
            "echo_level_db_2d": float(np.mean(echo_level_db(e_cap))),
            "echo_level_db_3d_full_band": float(np.mean(echo_level_db(e3))),
            "note_level_db_2d_capped": lv2, "note_level_db_3d": lv3,
            "harmonic_to_fundamental_db_full_band": harmonic_ratios_db(e_full, t_echo0, target.notes),
            "extinction_estimate_db_last_note": extinction_estimate_db(posts, sc, 1300.0, rho_last),
            "info_only_note_judge_capped_band": judge_info(e_cap, target, t_echo0, band_cap),
            "info_only_note_judge_full_band": judge_info(e_full, target, t_echo0, band_full)}


def study():
    torch.set_num_threads(8)
    t_all = time.time()
    STUDY.mkdir(parents=True, exist_ok=True)
    cfg = make_config(100)
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    band_full = clap_band(claps)
    band_cap = (band_full[0], min(band_full[1], cfg.band_max_hz))
    t_echo0 = 2 * cfg.r0 / C0
    t = time.time()
    prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                                steps=cfg.steps, lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out, band=band_cap)
    print(f"profile solve: loss {res.info['best_loss']:.3f} ({time.time() - t:.0f} s)", flush=True)
    if cfg.tier0_equalize_rounds:
        from stages.common import tier0_equalize

        prof_n, _ = tier0_equalize(cfg, prof_n, target, claps, band_cap, n_out, res.n0 / FS, cfg.tier0_equalize_rounds)
    rows = []
    for fill in STUDY_FILLS:
        for mode, K in STUDY_MODES:
            t = time.time()
            posts, st = _design(cfg, prof_n, claps, band_cap, fill, mode, K)
            r = {"fill_target": fill, "mode": mode, "posts_per_period": K, "radius_m": cfg.a_ref,
                 "half_angle_deg": cfg.half_angle_deg, "dropped": int(st["dropped"]), "n_rings": st.get("n_rings"),
                 "label": f"fill={fill * 100:.2f}% {mode} K={K}"}
            r.update(_evaluate(cfg, posts, target, claps, band_full, band_cap, t_echo0, n_out))
            from stages.s2_motif import radial_jitter

            pj = radial_jitter(posts, 0.002, 11)
            ej = post_echo(pj, torch.as_tensor(claps), stage_scene(cfg, pj), mode="2d", n_out=n_out,
                           band=band_full).numpy()
            r["loss_tier0_full_band_jitter_2mm"] = window_loss(ej, target.audio, band_full, cfg.r0, C0, claps.shape[1])
            r["extinction_estimate_db_per_note"] = [
                extinction_estimate_db(posts, stage_scene(cfg, posts), f, cfg.r0 + C0 * b / 2) for f, a_, b in target.notes]
            r["loss"] = r["loss_tier0_full_band_jitter_2mm"]
            r["wall_s"] = round(time.time() - t, 1)
            rows.append(r)
            j = r["info_only_note_judge_capped_band"]
            print(f"{r['label']:34s} N={r['n_posts']:5d} drop={r['dropped']:3d} loss cap {r['loss']:.3f} full "
                  f"{r['loss_tier0_full_band']:.3f} L2d/note {[round(x, 1) for x in r['note_level_db_2d_capped']]} "
                  f"H2/H1 {[round(x, 1) for x in r['harmonic_to_fundamental_db_full_band']]} ext~{r['extinction_estimate_db_last_note']:.1f} dB "
                  f"[info: order {j['notes_in_order']:.2f} cents {j['note_cents_max']:.1f}] ({r['wall_s']} s)", flush=True)
    # Tier 1 cost of the domain vs half-angle (no solve: echo.tier1.plan with a realized design's posts)
    from echo import tier1
    from stages.common import stage_listeners

    cost = []
    for nm in (100, 60):
        for hw in (0.75, 1.0, 1.5, 2.0):
            c_h = make_config(nm, max_half_width_m=hw)
            ha = hw
            tg = c_h.make_target()
            posts = np.array([[60.0, 0.0, A_REF]])  # a post of the design radius sets the CFL (sub-cell radius bound)
            pl = tier1.plan(stage_scene(c_h, posts), c_h.f_max, c_h.duration_s, stage_listeners(c_h, tg), ppw=10.0)
            g = pl["grid"]
            cs = g.nx * g.ny * pl["n_steps"]
            cost.append({"note_ms": nm, "strip_half_width_m": ha, "dx_m": pl["dx"], "dt_s": pl["dt"], "grid": [g.nx, g.ny],
                         "n_steps": pl["n_steps"], "cell_steps": float(cs),
                         "est_wall_s_idle_8_threads": cs / 55e9 * 260.0,
                         "f_max": c_h.f_max})
            print("cost", cost[-1], flush=True)
    out = {"what": "Tier 0 design study, stage 3 (100 ms notes); 2D for losses/judges/levels, 3D for level",
           "selection": SELECTION, "band_full_hz": list(band_full), "band_capped_hz": list(band_cap),
           "profile_solve": {"steps": cfg.steps, "lr": cfg.lr, "best_loss": res.info["best_loss"]},
           "extinction_model": "two-way coherent loss ~ 8.686 * sum_j sigma_tot / (2 r_j tan(half-angle)) dB over "
                               "posts nearer than the note (sigma_tot 2D rigid cylinder at 1.3 kHz); an estimate",
           "sigma_tot_m": {f"{f:.0f}": sigma_total_m(A_REF, f) for f in (1175.0, 1319.0, 1397.0, 1568.0, 2500.0)},
           "radius_m": A_REF, "strip_half_width_m": HALF_WIDTH_M, "n_posts_target": N_POSTS,
           "rows": rows, "tier1_cost": cost, "wall_s": time.time() - t_all}
    (STUDY / "design_study_tier0.json").write_text(json.dumps(out, indent=1))
    print("wrote design study", f"{time.time() - t_all:.0f} s", flush=True)


WEDGE_ROWS = ((1.0, 0.008), (1.0, 0.016), (20.0, 0.0002), (20.0, 0.0005), (20.0, 0.001))


def wedge_study():
    """Tier 0: the configured realization (phase_locked K=1, 2 cm, no extinction pre-compensation) at denser fills in
    the +-1 deg Tier 1 wedge and at sparse fills in the spec's +-20 deg wedge, with the stage-1-calibrated extinction
    estimate. Explains what limits the stage (density needed for a tone vs opacity of a narrow wedge). The judge is
    recorded for information; nothing is chosen here."""
    torch.set_num_threads(8)
    t_all = time.time()
    cfg0 = make_config(100)
    target = cfg0.make_target()
    claps = clap_family(cfg0.n_claps, seed=cfg0.seed)
    n_out = int(round(cfg0.duration_s * FS))
    band_full = clap_band(claps)
    band_cap = (band_full[0], min(band_full[1], cfg0.band_max_hz))
    t_echo0 = 2 * cfg0.r0 / C0
    prof_n, res = solve_profile(target, claps, stage_scene(cfg0), r0=cfg0.r0, dr=cfg0.dr, a_ref=cfg0.a_ref, steps=0,
                                lr=cfg0.lr, w_mel=cfg0.w_mel, n_out=n_out, band=band_cap)
    rows = []
    for ha, fill in WEDGE_ROWS:
        t = time.time()
        cfg = make_config(100, half_angle_deg=ha)
        posts, st = _design(cfg, prof_n, claps, band_cap, fill, "phase_locked", 1, precomp=False)
        r = {"half_angle_deg": ha, "fill_target": fill, "dropped": int(st["dropped"]), "n_rings": st.get("n_rings"),
             "label": f"+-{ha:g} deg fill={fill * 100:.2f}% phase_locked K=1"}
        r.update(_evaluate(cfg, posts, target, claps, band_full, band_cap, t_echo0, n_out))
        r["loss"] = r["loss_tier0_capped_band"]
        r["wall_s"] = round(time.time() - t, 1)
        rows.append(r)
        j = r["info_only_note_judge_capped_band"]
        print(f"{r['label']:40s} N={r['n_posts']:5d} rings={r['n_rings']} drop={r['dropped']} loss {r['loss']:.3f} "
              f"ext~{r['extinction_estimate_db_last_note']:.1f} dB L2d/note {[round(x, 1) for x in r['note_level_db_2d_capped']]} "
              f"[info: order {j['notes_in_order']:.2f} n {j['n_notes_detected']}] ({r['wall_s']} s)", flush=True)
    out = {"what": "Tier 0 wedge/density study (100 ms): denser fills at +-1 deg, sparse fills at the spec's +-20 deg; "
                   "profile = the solve's analytic initial profile (steps=0); no extinction pre-compensation",
           "selection": "none (explanatory); judge recorded for information only", "rows": rows,
           "wall_s": time.time() - t_all}
    (STUDY / "wedge_density_tier0.json").write_text(json.dumps(out, indent=1))
    print("wrote wedge study", f"{time.time() - t_all:.0f} s", flush=True)


FW_CANDIDATES = ((0.0005, "phase_locked", 1), (0.001, "phase_locked", 1), (0.001, "phase_locked", 2),
                 (0.001, "phase_locked_uniform", 4), (0.002, "phase_locked", 1))


def make_fullwedge_config(note_ms=100, **kw):
    """Fast-model-only design in the FULL +-20 deg wedge (no strip clip): ring populations grow with range as the
    2D spreading compensation asks; full clap band (no Tier 1 grid cap). Never verified (Tier 1 cost, see study)."""
    base = dict(title=f"Melody, full +-20 deg wedge, {note_ms} ms notes, fast model only - NOT verified",
                tag="s3fw" if note_ms == 100 else f"s3fw_{note_ms}ms", max_half_width_m=None, profile_transform=None,
                band_max_hz=None, max_posts=60000, robustness=False, field=False, target_fill=FW_FILL,
                posts_per_period=FW_K[1], realization=FW_K[0],
                design_study_files=("fullwedge_tier0.json", "note_length_sweep_tier0.json"),
                notes="Fast model (Tier 0) only, NOT verified: the full-wave cost of the full wedge is prohibitive "
                      "(fullwedge_tier0.json tier1_cost_full_wedge).")
    base.update(kw)
    return make_config(note_ms, **base)


FW_FILL = 0.001
FW_K = ("phase_locked", 1)


def fullwedge_study():
    """Tier 0: candidates in the full +-20 deg wedge, chosen by the FULL-band 2D spectrogram loss under 2 mm radial
    jitter (seed 11); judges informational. Per note: harmonic and clutter (non-note power) ratios, predicted
    extinction. Then 1/2/5 mm jitter of the pick and the Tier 1 cost of the full wedge."""
    from echo import tier1
    from stages.common import stage_listeners, tier0_equalize
    from stages.s2_motif import radial_jitter

    torch.set_num_threads(4)
    t_all = time.time()
    cfg = make_fullwedge_config(100)
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    bf = clap_band(claps)
    t0 = 2 * cfg.r0 / C0
    prof, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref, steps=0,
                              n_out=n_out, band=bf)
    prof, _ = tier0_equalize(cfg, prof, target, claps, bf, n_out, res.n0 / FS, cfg.tier0_equalize_rounds)
    cl = torch.as_tensor(claps)

    def jl(posts, sig, seed):
        pj = radial_jitter(posts, sig, seed)
        ej = post_echo(pj, cl, stage_scene(cfg, pj), mode="2d", n_out=n_out, band=bf).numpy()
        return window_loss(ej, target.audio, bf, cfg.r0, C0, claps.shape[1]), ej

    rows, picks = [], {}
    for fill, mode, K in FW_CANDIDATES:
        t = time.time()
        c = replace(cfg, target_fill=fill, realization=mode, posts_per_period=K)
        posts, st = _design(c, prof, claps, bf, fill, mode, K, precomp=False)
        r = {"fill_target": fill, "mode": mode, "posts_per_period": K, "dropped": int(st["dropped"]),
             "n_rings": st.get("n_rings"), "label": f"full wedge fill={fill * 100:.2f}% {mode} K={K}"}
        r.update(_evaluate(c, posts, target, claps, bf, bf, t0, n_out))
        e_full = post_echo(posts, cl, stage_scene(c, posts), mode="2d", n_out=n_out, band=bf).numpy()
        r["tonal_fraction_db"] = tonal_fraction_db(e_full, t0, target.notes)
        r["extinction_estimate_db_per_note"] = [extinction_estimate_db(posts, stage_scene(c, posts), f,
                                                                       cfg.r0 + C0 * (a + b) / 4, None)
                                                for f, a, b in target.notes]
        r["loss_full_band_jitter_2mm"], _ = jl(posts, 0.002, 11)
        r["loss"] = r["loss_full_band_jitter_2mm"]
        r["wall_s"] = round(time.time() - t, 1)
        rows.append(r)
        picks[len(rows) - 1] = posts
        j = r["info_only_note_judge_full_band"]
        print(f"{r['label']:44s} N={r['n_posts']:6d} drop={r['dropped']} loss {r['loss_tier0_full_band']:.3f} "
              f"jit2 {r['loss']:.3f} tonal {[round(x, 1) for x in r['tonal_fraction_db']]} "
              f"H2 {[round(x, 1) for x in r['harmonic_to_fundamental_db_full_band']]} "
              f"ext {[round(x, 1) for x in r['extinction_estimate_db_per_note']]} "
              f"[info: order {j['per_clap_in_order']} n {j['n_notes_detected']}] ({r['wall_s']} s)", flush=True)
    ib = min(range(len(rows)), key=lambda i: rows[i]["loss"])
    jit = []
    for sig in (0.001, 0.002, 0.005):
        ls, ords = [], []
        for sd in (11, 12, 13):
            l, ej = jl(picks[ib], sig, sd)
            ls.append(l)
            ords.append(judge_info(ej, target, t0, bf)["notes_in_order"])
        jit.append({"sigma_m": sig, "loss_mean": float(np.mean(ls)), "info_only_notes_in_order_mean": float(np.mean(ords))})
        print("jitter", jit[-1], flush=True)
    # full-wave cost of the full wedge at the 2.5 kHz grid (plan only)
    tg = target
    c25 = make_fullwedge_config(100)
    pl = tier1.plan(stage_scene(c25, np.array([[60.0, 0.0, A_REF]])), 2500.0, c25.duration_s,
                    stage_listeners(c25, tg), ppw=10.0)
    g = pl["grid"]
    cs = float(g.nx * g.ny * pl["n_steps"])
    cost = {"grid": [g.nx, g.ny], "n_steps": pl["n_steps"], "cell_steps": cs,
            "est_hours_idle_8_threads": cs / 55e9 * 260 / 3600, "est_hours_incl_empty_scene": 2 * cs / 55e9 * 260 / 3600}
    print("cost", cost, flush=True)
    out = {"what": "Tier 0 ONLY (unverified): 100 ms melody in the full +-20 deg wedge, 1 cm posts, full clap band",
           "selection": "lowest full-band 2D window_loss under 2 mm radial jitter (seed 11); judges informational",
           "band_hz": list(bf), "rows": rows, "picked": ib, "picked_label": rows[ib]["label"],
           "jitter_of_pick": jit, "tier1_cost_full_wedge": cost, "wall_s": time.time() - t_all}
    (STUDY / "fullwedge_tier0.json").write_text(json.dumps(export_clean(out), indent=1))
    print("wrote fullwedge study; pick", rows[ib]["label"], f"{time.time() - t_all:.0f} s", flush=True)


def note_length_sweep():
    """Tier 0 ONLY: the configured realization at each note length (same geometry, fill and seed), judge on the
    band-capped (Tier 1 band) and full-band echo, and the judge on the physically perfect echo (floor)."""
    from echo.inverse import reference_echo

    torch.set_num_threads(2)  # runs beside the Tier 1 solves
    t_all = time.time()
    rows = []
    for nm in SWEEP_NOTE_MS:
        t = time.time()
        cfg = make_config(nm)
        target = cfg.make_target()
        claps = clap_family(cfg.n_claps, seed=cfg.seed)
        n_out = int(round(cfg.duration_s * FS))
        band_full = clap_band(claps)
        band_cap = (band_full[0], min(band_full[1], cfg.band_max_hz))
        t_echo0 = 2 * cfg.r0 / C0
        prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                                    steps=cfg.steps, lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out, band=band_cap)
        if cfg.tier0_equalize_rounds:
            from stages.common import tier0_equalize

            prof_n, _ = tier0_equalize(cfg, prof_n, target, claps, band_cap, n_out, res.n0 / FS, cfg.tier0_equalize_rounds)
        posts, st = _design(cfg, prof_n, claps, band_cap, cfg.target_fill, cfg.realization, cfg.posts_per_period)
        ev = _evaluate(cfg, posts, target, claps, band_full, band_cap, t_echo0, n_out)
        perf_cap = reference_echo(target.audio, claps, t_echo0, n_out, band_cap)
        perf_full = reference_echo(target.audio, claps, t_echo0, n_out, band_full)
        r = {"note_ms": nm, "depth_m": ev["depth_m"], "n_posts": ev["n_posts"], "fill_realized": ev["fill_realized"],
             "loss": ev["loss_tier0_capped_band"],
             "tier0_judge_capped_band": ev["info_only_note_judge_capped_band"],
             "tier0_judge_full_band": ev["info_only_note_judge_full_band"],
             "perfect_echo_judge_capped_band": judge_info(perf_cap, target, t_echo0, band_cap),
             "perfect_echo_judge_full_band": judge_info(perf_full, target, t_echo0, band_full),
             "note_level_db_2d_capped": ev["note_level_db_2d_capped"], "wall_s": round(time.time() - t, 1),
             "label": f"{nm} ms notes"}
        rows.append(r)
        print(f"{nm:3d} ms: depth {r['depth_m']:.1f} m N={r['n_posts']} T0 cap {r['tier0_judge_capped_band']} | "
              f"full {r['tier0_judge_full_band']['notes_in_order']} | perfect cap "
              f"{r['perfect_echo_judge_capped_band']['notes_in_order']} full "
              f"{r['perfect_echo_judge_full_band']['notes_in_order']} ({r['wall_s']} s)", flush=True)
    passing = [r["note_ms"] for r in rows if r["tier0_judge_capped_band"]["notes_in_order"] == 1.0]
    out = {"what": "TIER 0 ONLY note-length sweep (not a Tier 1 result): shortest note length whose realized Tier 0 "
                   "echo still transcribes for every clap (notes_in_order = 1.0 mean over claps), and the judge on the "
                   "physically perfect echo (the judge's own floor) at each length",
           "geometry": {"half_angle_deg": HALF_ANGLE_DEG, "radius_m": A_REF, "target_fill": TARGET_FILL,
                        "realization": f"phase_locked K={POSTS_PER_PERIOD}"},
           "shortest_passing_note_ms_tier0_capped_band": min(passing) if passing else None,
           "rows": rows, "wall_s": time.time() - t_all,
           "selection": "none (a sweep; the judge is the quantity being measured, nothing is chosen by it)"}
    (STUDY / "note_length_sweep_tier0.json").write_text(json.dumps(out, indent=1))
    print("wrote note-length sweep", f"{time.time() - t_all:.0f} s", flush=True)


# ------------------------------------------------------------------------------------------------ run post-processing
C_NOT_RUN = (331.0, 349.0)
JITTER_NOT_RUN = ("not run (time/cost: the 100 ms run alone took ~30 min on the 2.5 kHz grid with the Tier 1 lock "
                  "shared by three stages; free cases only)")
EXTINCTION_CAVEAT = ("1 cm posts on the 2.5 kHz grid: forward scattering is 2.6 dB off the exact cylinder, and forward "
                     "scattering sets extinction, so the referee's extinction (and the multiple-scattering residue) for "
                     "this design is uncertain by roughly that much")


def _peaks_per_note(echo, t_echo0, notes, fs=FS, lag=0.003):
    """Per note: mean over claps of 20 log10(peak |echo|) inside the note's window (whole note, + clap lag)."""
    e = np.atleast_2d(echo)
    out = []
    for _, a, b in notes:
        seg = e[:, int((t_echo0 + lag + a) * fs):int((t_echo0 + lag + b) * fs)]
        out.append(float(np.mean(20 * np.log10(np.max(np.abs(seg), axis=1) + 1e-30))))
    return out


def postprocess(run_dir, cfg, des):
    """Add stage-3 facts to the run's metrics.json (all computed here from the run's own design and echoes):
    level along the melody (per note, 3D tier-gap corrected per note, 2 m finite height, SPL, the 35 dB line), the
    Tier 0 full-band echo (judge per clap, 2nd-harmonic ratio) that the 2 kHz Tier 1 grid cannot see, the robustness
    cases not run for cost (expected pitch shift from c alone), the grid / wedge log and the Tier 1 lock wait."""
    from echo.metrics import DIRECT_SPL_DB
    from stages.common import TIER1_LOCK_STATS

    run_dir = Path(run_dir)
    mp = run_dir / "metrics.json"
    m = json.loads(mp.read_text())
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    band_full = clap_band(claps)
    band_cap = (band_full[0], min(band_full[1], cfg.band_max_hz))
    t0 = 2 * cfg.r0 / C0
    cl = torch.as_tensor(claps)
    sc = des.scene
    e_full = post_echo(des.posts, cl, sc, mode="2d", n_out=n_out, band=band_full).numpy()
    e3h = post_echo(des.posts, cl, sc, mode="3d", n_out=n_out, band=band_cap, post_height=cfg.post_height_m).numpy()
    p0_2d = _peaks_per_note(des.echo_t0_2d, t0, target.notes)
    p0_3d = _peaks_per_note(des.echo_t0_3d, t0, target.notes)
    p0_3dh = _peaks_per_note(e3h, t0, target.notes)
    lvl = {"definition": "per note: mean over claps of 20 log10(peak |echo|) in the note's window, re the direct clap at "
                         "the listener; 3D corrected per note = L3d(Tier 0) + (L2d(Tier 1) - L2d(Tier 0)) of that note; "
                         f"SPL = {DIRECT_SPL_DB:.2f} dB + level (100 dB peak at 1 m clap); 35 dB = likely inaudible",
           "notes_hz": [float(f) for f, _, _ in target.notes],
           "tier0_2d_db": p0_2d, "tier0_3d_db": p0_3d, f"tier0_3d_finite_height_{cfg.post_height_m:g}m_db": p0_3dh}
    lvl["tier0_3d_spl_db"] = [DIRECT_SPL_DB + v for v in p0_3d]
    lvl[f"tier0_3d_finite_height_{cfg.post_height_m:g}m_spl_db"] = [DIRECT_SPL_DB + v for v in p0_3dh]
    lvl["tier0_notes_below_35_db_spl"] = [i for i, v in enumerate(p0_3d) if DIRECT_SPL_DB + v < 35.0]
    if des.echo_t1_2d is not None:
        p1 = _peaks_per_note(des.echo_t1_2d, t0, target.notes)
        gap = [a - b for a, b in zip(p1, p0_2d)]
        c3 = [a + g for a, g in zip(p0_3d, gap)]
        c3h = [a + g for a, g in zip(p0_3dh, gap)]
        spl = [DIRECT_SPL_DB + v for v in c3]
        splh = [DIRECT_SPL_DB + v for v in c3h]
        lvl.update({"tier1_2d_db": p1, "tier_gap_per_note_db": gap, "corrected_3d_db": c3,
                    "corrected_3d_finite_height_db": c3h, "spl_db": spl, "spl_finite_height_db": splh,
                    "first_minus_last_note_db_tier1_2d": p1[0] - p1[-1],
                    "first_minus_last_note_db_corrected_3d": c3[0] - c3[-1],
                    "notes_below_35_db_spl": [i for i, v in enumerate(spl) if v < 35.0],
                    "notes_below_35_db_spl_finite_height": [i for i, v in enumerate(splh) if v < 35.0]})
    full = stage_values(STAGE, e_full, target, t0, band=band_full)
    extra = {
        "level_along_melody": lvl,
        "tier0_full_band": {
            "what": f"Tier 0 2D echo over the whole clap band {band_full[0]:.0f}-{band_full[1]:.0f} Hz (what the 2 kHz "
                    "Tier 1 referee cannot see: the clap's 2-4 kHz content and the comb's 2nd harmonics)",
            "per_clap": [{"clap": k, "notes_in_order": float(v["notes_in_order"]), "note_cents_max":
                          float(v["note_cents_max"]), "n_notes_detected": int(v["n_notes_detected"])}
                         for k, v in enumerate(full)],
            "notes_in_order_mean": float(np.mean([v["notes_in_order"] for v in full])),
            "harmonic_to_fundamental_db": harmonic_ratios_db(e_full, t0, target.notes),
            "loss": window_loss(e_full, target.audio, band_full, cfg.r0, C0, claps.shape[1])},
        "grid_and_domain": {"f_max_hz": cfg.f_max, "band_max_hz": cfg.band_max_hz, "half_angle_deg": cfg.half_angle_deg,
                            "reason": "Tier 1 budget (spec: <= 20 min per run; narrowed so one 100 ms run fits ~15 "
                                      "min on an idle machine); f_max from the top note G6 1568 Hz",
                            "invisible_to_tier1": "clap content and comb harmonics above 2 kHz"},
        "robustness_not_run": [{"case": f"c_{c:.0f}", "label": f"Speed of sound {c:.0f} m/s", "status": "not run (cost)",
                                "pitch_shift_expected_pct": (c / C0 - 1) * 100,
                                "pitch_shift_expected_cents": 1200 * math.log2(c / C0),
                                "alone_breaks_50_cent_limit": abs(1200 * math.log2(c / C0)) > 50.0}
                               for c in C_NOT_RUN] + ([] if cfg.robustness_jitter else
                                                      [{"case": "jitter", "status": JITTER_NOT_RUN}]),
        "tier1_lock": dict(TIER1_LOCK_STATS),
        "note_ms": int(round(cfg.note_s * 1000)),
    }
    m["s3_extra"] = extra
    m["design_study"] = studies_from_disk()
    mp.write_text(json.dumps(export_clean(m), indent=1))
    print("stage 3 extras:", json.dumps({k: extra["level_along_melody"].get(k) for k in
                                         ("corrected_3d_db", "spl_db", "notes_below_35_db_spl")}), flush=True)
    print("tier0 full band in order:", extra["tier0_full_band"]["notes_in_order_mean"],
          "H2/H1:", [round(x, 1) for x in extra["tier0_full_band"]["harmonic_to_fundamental_db"]], flush=True)


def studies_from_disk():
    """metrics.design_study: every STUDY_FILES json as written by the study commands (missing ones say so)."""
    out = {}
    for name in STUDY_FILES:
        fp = STUDY / name
        out[Path(name).stem] = json.loads(fp.read_text()) if fp.exists() else {"missing": str(fp)}
    nl = out.get("note_length_sweep_tier0")
    if isinstance(nl, dict) and "rows" in nl:
        rows = nl["rows"]
        perf_ok = [r["note_ms"] for r in rows if r["perfect_echo_judge_capped_band"]["notes_in_order"] == 1.0]
        des_ok = [r["note_ms"] for r in rows if r["tier0_judge_capped_band"]["notes_in_order"] == 1.0]
        nl = dict(nl, answer={
            "TIER_0_ONLY": True,
            "shortest_note_ms_perfect_echo_transcribes_all_claps": min(perf_ok) if perf_ok else None,
            "shortest_note_ms_realized_design_transcribes_all_claps": min(des_ok) if des_ok else None,
            "per_length": [{"note_ms": r["note_ms"],
                            "perfect_echo_in_order_frac": r["perfect_echo_judge_capped_band"]["notes_in_order"],
                            "design_tier0_in_order_frac": r["tier0_judge_capped_band"]["notes_in_order"]}
                           for r in rows]})
        out["note_length_sweep"] = nl  # the name the task brief uses (design_study.note_length_sweep); Tier 0 only
        out.pop("note_length_sweep_tier0", None)
    return out


def attach_studies(run_dir):
    """Refresh metrics.design_study of a finished run from the study files on disk (they may finish after the run)."""
    mp = Path(run_dir) / "metrics.json"
    m = json.loads(mp.read_text())
    m["design_study"] = studies_from_disk()
    ex = m.setdefault("s3_extra", {})
    for r in ex.get("robustness_not_run", []):
        if r.get("case") == "jitter":
            r["status"] = JITTER_NOT_RUN
    for key in ("caveats",):
        if EXTINCTION_CAVEAT not in (m.get(key) or []):
            m[key] = list(m.get(key) or []) + [EXTINCTION_CAVEAT]
    mp.write_text(json.dumps(export_clean(m), indent=1))
    man = Path(run_dir) / "manifest.json"
    mf = json.loads(man.read_text())
    if EXTINCTION_CAVEAT not in (mf.get("caveats") or []):
        mf["caveats"] = list(mf.get("caveats") or []) + [EXTINCTION_CAVEAT]
        man.write_text(json.dumps(export_clean(mf), indent=1))
    print("attached studies to", mp)


def _notes_named(det, target):
    """Judge output [(f, on, off)] -> [{hz, on_s, off_s, nearest target note, cents to it}] (reporting only)."""
    tf = sorted({float(f) for f, _, _ in target.notes})
    out = []
    for f, a, b in det:
        near = min(tf, key=lambda x: abs(math.log2(f / x)))
        out.append({"hz": round(float(f), 1), "on_s": round(float(a), 4), "off_s": round(float(b), 4),
                    "nearest_target_hz": round(near, 1), "cents": round(1200 * math.log2(f / near), 1)})
    return out


def _per_note_residue_db(sig, model, t_echo0, notes, fs=FS):
    """Per note window: least-squares gain g of `model` onto `sig`, residue 10 log10(|sig - g model|^2 / |sig|^2)."""
    out = []
    for t1, t2 in note_windows(t_echo0, notes):
        a, b = sig[int(t1 * fs):int(t2 * fs)], model[int(t1 * fs):int(t2 * fs)]
        g = float(np.dot(a, b) / max(np.dot(b, b), 1e-300))
        out.append(float(10 * np.log10(np.sum((a - g * b) ** 2) / max(np.sum(a ** 2), 1e-300))))
    return out


def tonal_fraction_db(echo, t_echo0, notes, fs=FS, rel=0.03):
    """Per note (phase-insensitive): 10 log10 of the echo's power within +-3 % of the note frequency over its power
    in the whole spectrum, Hann over the middle 60 % of the note, mean power over claps. A clean tone is near 0 dB."""
    e = np.atleast_2d(echo)
    out = []
    for (f, _, _), (t1, t2) in zip(notes, note_windows(t_echo0, notes)):
        seg = e[:, int(t1 * fs):int(t2 * fs)]
        S = np.mean(np.abs(np.fft.rfft(seg * np.hanning(seg.shape[1]), 1 << 14, axis=1)) ** 2, axis=0)
        fr = np.fft.rfftfreq(1 << 14, 1 / fs)
        out.append(float(10 * np.log10(S[(fr > f * (1 - rel)) & (fr < f * (1 + rel))].sum() / max(S.sum(), 1e-300))))
    return out


def diagnose(run_dir):
    """Failure diagnosis of a finished run, recomputed from its own files (scene.json posts, echo_tier1.wav with the
    manifest gain = Tier 1 echo of clap 0; Tier 0 recomputed for every clap): what the judge detected, whether the
    design transcribes on Tier 0, Tier 1 vs Tier 0 (stretch, residue per note), the design's own residue against
    the perfect echo, predicted vs measured extinction per note, and the level two ways. Writes metrics.diagnosis
    and appends a summary to failure_cause. Judges are only read, never used to choose anything."""
    import soundfile as sf
    from scipy.interpolate import CubicSpline

    from echo.inverse import fit_stretch, reference_echo
    from echo.metrics import echo_segment, segment_notes
    from echo.scene import Scene

    run_dir = Path(run_dir)
    m = json.loads((run_dir / "metrics.json").read_text())
    man = json.loads((run_dir / "manifest.json").read_text())
    note_ms = int(m.get("s3_extra", {}).get("note_ms") or (60 if run_dir.name.endswith("_60ms") else 100))
    cfg = make_config(note_ms)
    target = cfg.make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(cfg.duration_s * FS))
    bf = clap_band(claps)
    bc = (bf[0], min(bf[1], cfg.band_max_hz))
    t0 = 2 * cfg.r0 / C0
    posts = np.asarray(json.loads((run_dir / "scene.json").read_text())["posts"], dtype=float)
    sc = Scene(posts=posts, half_angle_deg=cfg.half_angle_deg)
    cl = torch.as_tensor(claps)
    e0 = post_echo(posts, cl, sc, mode="2d", n_out=n_out, band=bc).numpy()
    w1, _ = sf.read(run_dir / "echo_tier1.wav")
    e1 = np.zeros(n_out)
    e1[:min(n_out, len(w1))] = (w1 / 10 ** (man["audio"]["echo_gain_db"]["tier1"] / 20))[:n_out]
    perf = reference_echo(target.audio, claps, t0, n_out, bc)
    n = len(target.audio)
    note_s = cfg.note_s

    def det(e):
        return _notes_named(segment_notes(echo_segment(e, t0, n), FS, note_s=note_s), target)

    judge = {"target_hz": [round(float(f), 1) for f, _, _ in target.notes],
             "tier1_clap0": det(e1), "perfect_clap0": det(perf[0]),
             "tier0_per_clap": [det(e0[k]) for k in range(len(claps))]}
    n0w, n1w = int(t0 * FS), int(t0 * FS) + n + claps.shape[1]
    fit = fit_stretch(e1[None], e0[:1], n0w, n1w)
    t = np.arange(n_out) / FS
    e0w = CubicSpline(t, e0[0])(np.clip(t * (1 + fit["eps"]) + fit["tau_s"], 0, t[-1]))
    res_t1 = _per_note_residue_db(e1, e0w, t0, target.notes)
    res_t0 = [float(np.mean([_per_note_residue_db(e0[k], perf[k], t0, target.notes)[i] for k in range(len(claps))]))
              for i in range(len(target.notes))]
    tonal = {"perfect_echo": tonal_fraction_db(perf, t0, target.notes),
             "tier0_design": tonal_fraction_db(e0, t0, target.notes),
             "tier1_clap0": tonal_fraction_db(e1, t0, target.notes),
             "definition": "per note, power within +-3 % of the note frequency / total power, dB (0 = pure tone); "
                           "phase-insensitive, so the stretch pre-warp does not affect it"}
    seg = slice(n0w, n1w)
    corr_raw = float(np.corrcoef(e1[seg], e0[0][seg])[0, 1])
    corr_st = float(np.corrcoef(e1[seg], e0w[seg])[0, 1])
    lvl = m.get("s3_extra", {}).get("level_along_melody", {})
    mid = [cfg.r0 + C0 * (a + b) / 4 for _, a, b in target.notes]
    pred = [extinction_estimate_db(posts, sc, f, r) for (f, _, _), r in zip(target.notes, mid)]
    gap = lvl.get("tier_gap_per_note_db")
    # level two ways: (ii) every ring's population scaled from the strip (2 hw wide) to the full +-20 deg wedge
    # (2 rho tan 20 wide) at the same areal density: coherent single scattering, amplitude x width ratio (unverified)
    scale_db = [20 * math.log10(max(1.0, 2 * r * math.tan(math.radians(cfg.half_angle_deg)) / (2 * HALF_WIDTH_M)))
                for r in mid]
    c3 = lvl.get("corrected_3d_db") or []
    from echo.metrics import DIRECT_SPL_DB

    full_wedge = [v + d for v, d in zip(lvl.get("tier0_3d_db") or [], scale_db)]
    posts_per_period = len(posts) / max(1.0, sum((b - a) * f for f, a, b in target.notes))
    d = {
        "what": "recomputed from this run's scene.json and echo_tier1.wav (clap 0; per-clap Tier 1 echoes are not "
                "saved) and Tier 0 of the same posts for every clap; no new solve",
        "tier0_design_transcribes": {"tier0_metric_notes_in_order": next((x["value"] for x in m["metrics"] if
                                                                          x["id"] == "notes_in_order" and x["tier"] == "tier0"), None),
                                     "tier0_full_band_in_order": m.get("s3_extra", {}).get("tier0_full_band", {}).get("notes_in_order_mean")},
        "judge_detected": judge,
        "tier1_vs_tier0_clap0": {"stretch_eps": fit["eps"], "tau_s": fit["tau_s"], "corr_raw": corr_raw,
                                 "corr_after_stretch": corr_st, "residue_db_per_note_after_stretch_and_gain": res_t1},
        "tier0_design_vs_perfect_echo_residue_db_per_note": res_t0,
        "residue_note": "waveform residues are phase-sensitive: the design's ranges are pre-warped by the stretch "
                        "compensation, so Tier 0 drifts against the unwarped perfect echo by ~0.2 % of the delay "
                        "(a period or more late in the melody) and its residue reads ~0 dB; tonal_fraction_db is the "
                        "phase-insensitive measure",
        "tonal_fraction_db": tonal,
        "posts_per_carrier_period_mean": posts_per_period,
        "extinction_table": {"note_hz": judge["target_hz"], "range_mid_m": mid, "predicted_two_way_db": pred,
                             "measured_tier_gap_per_note_db": gap,
                             "model": "8.686 * sum over nearer posts of sigma_tot(f) / strip width (stage-1 calibrated: "
                                      "7.4 dB predicted vs 7.2 dB measured)"},
        "level_two_ways": {
            "strip_as_simulated_corrected_3d_db": c3, "strip_as_simulated_spl_db": lvl.get("spl_db"),
            "full_wedge_tier0_3d_db_UNVERIFIED": full_wedge,
            "full_wedge_spl_db_UNVERIFIED": [DIRECT_SPL_DB + v for v in full_wedge],
            "full_wedge_definition": "Tier 0 3D per-note peak of the strip design + 20 log10(wedge width 2 rho tan 20 deg"
                                     " / strip width 2 m) at the note's mid range: ring populations scaled to the full "
                                     "wedge at the strip's areal density, coherent single scattering; not simulated"},
    }
    t0m = next((x["value"] for x in m["metrics"] if x["id"] == "notes_in_order" and x["tier"] == "tier0"), None)
    tn0, tn1 = tonal["tier0_design"], tonal["tier1_clap0"]
    inner = slice(1, len(target.notes) - 1)
    gap_in = float(np.median(gap[inner])) if gap else float("nan")
    summ = (f"(1) the design is imperfect already on Tier 0 (notes in order for {t0m:.1f} of claps): the inner notes "
            f"are clean tones (median {np.median(tn0[inner]):.1f} dB of note power at the note frequency) but the first "
            f"and last notes are not ({tn0[0]:.1f} / {tn0[-1]:.1f} dB: the ends of the {len(posts)}-post comb, "
            f"{posts_per_period:.1f} posts per carrier period) and the segmenter merges or drops notes (clap 0: "
            f"{len(judge['tier0_per_clap'][0])} detected); (2) on Tier 1 a broadband residue dominates: the inner notes "
            f"carry only {np.median(tn1[inner]):.1f} dB of their power at the note frequency, the Tier 1 inner-note level "
            f"is {gap_in:+.1f} dB ABOVE Tier 0 (median) although coherent extinction predicts {np.median(pred[inner]):.1f} dB "
            f"below, and the pitch tracker locks to {min(x['hz'] for x in judge['tier1_clap0']):.0f}-"
            f"{max(x['hz'] for x in judge['tier1_clap0']):.0f} Hz (the top of the 2.5 kHz band where the clap x "
            f"(ka)^2 scattering residue is strongest; interpretation) instead of the 1175-1568 Hz notes; Tier 1 stretch {fit['eps'] * 100:+.3f} % "
            f"(corr {corr_raw:.2f} -> {corr_st:.2f} after it). Coherent extinction is not the binding cause "
            f"(predicted {pred[-1]:.1f} dB at the last note, mean tier gap {m['headline']['tier_gap_db']:.1f} dB); the "
            f"incoherent residue of a sparse comb of weak (ka ~ 0.2-0.3) posts is the binding cause on Tier 1, and the "
            f"comb's ends on Tier 0")
    d["summary"] = summ
    m["diagnosis"] = d
    fc = m.get("failure_cause") or ""
    m["failure_cause"] = fc.split(" | diagnosis: ")[0] + " | diagnosis: " + summ
    (run_dir / "metrics.json").write_text(json.dumps(export_clean(m), indent=1))
    print(json.dumps({"summary": summ, "pred": [round(x, 1) for x in pred], "gap": gap and [round(x, 1) for x in gap],
                      "tonal": {k: [round(x, 1) for x in v] for k, v in tonal.items() if k != "definition"},
                      "t0c0": [(x["hz"], x["on_s"]) for x in judge["tier0_per_clap"][0]],
                      "t1c0": [(x["hz"], x["on_s"]) for x in judge["tier1_clap0"]],
                      "full_wedge_spl": [round(DIRECT_SPL_DB + v, 1) for v in full_wedge]}, indent=0), flush=True)
    return d


def fullwedge_extra(run_dir, cfg, des):
    """Facts of the fast-model full-wedge design: fill along range, predicted extinction per note, jitter (from the
    study), full-wave cost that prevented verification."""
    run_dir = Path(run_dir)
    mp = run_dir / "metrics.json"
    m = json.loads(mp.read_text())
    target = cfg.make_target()
    P = des.posts
    rho = np.linalg.norm(P[:, :2], axis=1)
    edges = np.arange(cfg.r0, rho.max() + 10.0, 10.0)
    cnt, _ = np.histogram(rho, edges)
    th = math.radians(cfg.half_angle_deg)
    area = th * (edges[1:] ** 2 - edges[:-1] ** 2)
    fill = cnt * math.pi * cfg.a_ref ** 2 / area
    mid = [cfg.r0 + C0 * (a + b) / 4 for _, a, b in target.notes]
    st = json.loads((STUDY / "fullwedge_tier0.json").read_text()) if (STUDY / "fullwedge_tier0.json").exists() else {}
    m["fullwedge"] = {
        "label": "FAST MODEL (Tier 0) ONLY - NOT VERIFIED on the full-wave solver",
        "post_count": int(len(P)),
        "fill_along_range": {"range_m": [float(x) for x in edges[:-1]], "posts": [int(x) for x in cnt],
                             "areal_fill_fraction": [float(x) for x in fill], "band_m": 10.0},
        "predicted_two_way_extinction_db_per_note": [extinction_estimate_db(P, des.scene, f, r, None)
                                                     for (f, _, _), r in zip(target.notes, mid)],
        "jitter_tier0": st.get("jitter_of_pick"), "tier1_cost_full_wedge": st.get("tier1_cost_full_wedge"),
        "selection": st.get("selection")}
    mp.write_text(json.dumps(export_clean(m), indent=1))
    print("fullwedge:", json.dumps({k: m["fullwedge"][k] for k in ("post_count", "predicted_two_way_extinction_db_per_note")}))


def export_clean(o):
    """Plain JSON (no NaN / Infinity), as the data contract requires."""
    if isinstance(o, dict):
        return {k: export_clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [export_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


# ------------------------------------------------------------------------------------------------ main
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--study" in argv:
        return study()
    if "--sweep" in argv:
        return note_length_sweep()
    if "--wedge-study" in argv:
        return wedge_study()
    if "--fullwedge-study" in argv:
        return fullwedge_study()
    if "--diagnose" in argv:
        return [diagnose(d) for d in argv[argv.index("--diagnose") + 1:]]
    if "--attach-studies" in argv:
        return [attach_studies(d) for d in argv[argv.index("--attach-studies") + 1:]]
    design = None
    if "--design" in argv:
        i = argv.index("--design")
        design = argv[i + 1]
        del argv[i:i + 2]
        if design != "fullwedge" or "--tier0-only" not in argv:
            raise SystemExit("--design fullwedge is a fast-model design: use it with --tier0-only")
    note_ms = 100
    if "--note-ms" in argv:
        i = argv.index("--note-ms")
        note_ms = int(argv[i + 1])
        del argv[i:i + 2]
    cfg = make_config(note_ms) if design is None else make_fullwedge_config(note_ms)
    out = stage_main(cfg, argv)
    postprocess(out[0], cfg, out[1])
    attach_studies(out[0])
    if design == "fullwedge":
        fullwedge_extra(out[0], cfg, out[1])
    if out[1].echo_t1_2d is not None and not json.loads((Path(out[0]) / "metrics.json").read_text())["passed"]:
        diagnose(out[0])
    return out


if __name__ == "__main__":
    main()
