"""Build-optimized pilot design (Task 13b): a structure chosen for buildability, scored on the full-wave solver.

    uv run python -m stages.build_pilot --study          # Tier 0 candidate study -> runs/build_pilot/_studies/
    uv run python -m stages.build_pilot                  # Tier 1 run of the chosen pilot -> runs/build_pilot/<run_id>/
    uv run python -m stages.build_pilot --tier0-only     # same, without Tier 1 (status tier0_only)
    uv run python -m stages.build_pilot --checks <run>   # (re)compute the pilot's build checks into its metrics.json

Design rules (what the stages learned, BUILD.md "Pilot design"): phase-locked rings (K = 1) of 1 cm-radius posts
(nearest stock: 20 mm smooth round bar), a narrow fan (+-10 deg) for a wider listening spot, a post-count cap a small
team can install, ground coverage <= 0.35 % (thick or dense fields extinguish the echo), stretch pre-compensation on.

The spec has no pass mark for a pilot. The run is judged by the stage-1 judges with the stage-1 thresholds shown for
reference. `passed` is computed against them only when the target is stage 1's own whistle (THRESHOLDS["s1_bird"]);
for any other target the gating list is empty, so the contract's `passed` is false by construction and
metrics["pilot"]["verdict"] says "no pass mark (reference thresholds only)".

Selection (stated before results, written into the study json): the candidate target is chosen by judge-free numbers
only -- the listening-spot width (waveform correlation >= 0.95 against the nominal listener, sideways), then the
waveform correlation under 2 mm radial jitter, then the level -- among candidates with fill <= 0.35 % and posts <= cap.
Within the chosen target, the post count is the one with the lowest Tier 0 spectrogram loss under 2 mm jitter.
"""

from __future__ import annotations

import argparse
import json
import math
import shlex
import sys
import time
from pathlib import Path

import numpy as np

from echo import metrics as M
from echo.scene import FS, RADII
from echo.targets import Target, _fade, _track, bird_note
from stages.common import StageConfig, Tier1Hooks, run_stage

STAGE = "build_pilot"
JUDGE_STAGE = "s1_bird"  # the yardstick: stage-1 judges (pitch track along the note, log-mel correlation)
HALF_ANGLE = 10.0
POST_CAP = 500
FILL_MAX = 0.0035
JITTER_MM = (1.0, 2.0, 5.0)
JITTER_SEEDS = (11, 12, 13)
SIDE_OFFSETS = (0.05, 0.1, 0.2, 0.3)
BACK_OFFSETS = (0.5, 1.0)
SELECTION = ("judge-free: among candidates with fill <= 0.35 % and posts <= cap, the target with the widest sideways "
             "listening spot (largest offset with waveform corr >= 0.95 vs the nominal listener), ties broken by the "
             "waveform correlation under 2 mm radial jitter, then by 3D level; within that target the count with the "
             "lowest Tier 0 spectrogram loss under 2 mm jitter. Judges are recorded for information only.")

# The pilot is judged by the stage-1 judge function (registered under this stage id; thresholds are not copied).
M.STAGE_METRICS.setdefault(STAGE, M.STAGE_METRICS[JUDGE_STAGE])


def ping(duration_s=0.04, f_hz=2500.0, fs=FS) -> Target:
    """Single-pitch ping: a pure tone with faded ends (uniform rings: the 'picket-fence' echo)."""
    n = int(round(duration_s * fs))
    audio = np.sin(2 * np.pi * f_hz * np.arange(n) / fs) * _fade(n, fs)
    return Target(name="ping", audio=audio / np.max(np.abs(audio)), duration_s=duration_s, notes=None,
                  f_track=_track(lambda t: f_hz + 0.0 * t, duration_s), f_top_hz=f_hz)


def short_whistle():
    return bird_note(duration_s=0.04)


# name -> (make_target, duration_s of the exported timeline, counts to try, is stage 1's own whistle)
CANDIDATES = {
    "whistle80": (bird_note, 0.12, (300, 500), True),  # stage 1's whistle, 3.5 -> 2.0 kHz, 80 ms
    "whistle40": (short_whistle, 0.08, (100, 170), False),  # same glide in 40 ms (fewer rings)
    "ping40": (ping, 0.08, (100, 170), False),  # 2.5 kHz, 40 ms
}
CHOSEN_FILE = "chosen.json"  # written by --study: {"candidate", "n_posts", "fill"}


def make_config(name: str, fill: float = 0.003, **kw) -> StageConfig:
    make_target, dur, _, _ = CANDIDATES[name]
    base = dict(threads=4)
    base.update(kw)
    return StageConfig(
        stage=STAGE, title=f"Build pilot: {name}, +-{HALF_ANGLE:g} deg, phase-locked rings of 1 cm posts",
        tag=f"pilot_{name}", make_target=make_target, duration_s=dur, f_max=4000.0, half_angle_deg=HALF_ANGLE,
        catalog=RADII, a_ref=0.01, realization="phase_locked", posts_per_period=1, target_fill=fill,
        fill_candidates=None, correction_rounds=1, robustness=True, robustness_c_cases=(),
        robustness_jitter=True, max_posts=POST_CAP, stretch_comp=True,
        notes=("Build-optimized pilot (Task 13b), not a spec stage. Judged with the stage-1 judges; thresholds "
               "shown for reference. Temperature is covered by the Tier 0 c(T) rows of the build pack (c cases not "
               "run on Tier 1: an exact time-scaling, and the Tier 1 budget is 3 solves)."), **base)


def _chosen(root=None):
    from echo import export

    p = Path(root or export.RUNS) / STAGE / "_studies" / CHOSEN_FILE
    return json.loads(p.read_text()) if p.exists() else {"candidate": "whistle80", "fill": 0.003}


def _cfg_from_chosen(root=None):
    ch = _chosen(root)
    return make_config(ch["candidate"], fill=ch["fill"])


CONFIG = _cfg_from_chosen()  # buildkit's judges import stages.<stage>.CONFIG.make_target()


def min_gap_m(posts) -> float:
    """Smallest clear distance between post surfaces (m)."""
    from scipy.spatial import cKDTree

    p = np.asarray(posts)
    if len(p) < 2:
        return float("inf")
    d, i = cKDTree(p[:, :2]).query(p[:, :2], k=2)
    return float(np.min(d[:, 1] - p[:, 2] - p[i[:, 1], 2]))


def _study_one(name, threads=4, log=print):
    import torch

    from echo.clap import clap_family
    from echo.inverse import solve_profile
    from echo.metrics import echo_level_db
    from echo.robustness import listener_shift_s
    from echo.scene import Scene, fill_fraction
    from stages.common import stage_scene
    from stages.s1_study import Evaluator, _wave_corr, design, radial_jitter

    torch.set_num_threads(threads)
    make_target, dur, counts, _ = CANDIDATES[name]
    cfg = make_config(name)
    target = make_target()
    claps = clap_family(cfg.n_claps, seed=cfg.seed)
    n_out = int(round(dur * FS))
    prof_n, res = solve_profile(target, claps, stage_scene(cfg), r0=cfg.r0, dr=cfg.dr, a_ref=cfg.a_ref,
                                steps=cfg.steps, lr=cfg.lr, w_mel=cfg.w_mel, n_out=n_out)
    band = res.band
    ev = Evaluator(cfg, target, claps, band, res.n0 / FS, n_out)
    rows = []
    for N in counts:
        posts, st, sc, _ = design(cfg, prof_n, N, "phase_locked", 1, band, claps)
        e2, e3 = ev.echo(posts, sc), ev.echo(posts, sc, "3d")
        s0 = ev.seg(e2)
        row = {"candidate": name, "n_request": N, "n_posts": int(len(posts)), "dropped": st["dropped"],
               "n_rings": st.get("n_rings"), "fill": fill_fraction(sc), "min_gap_m": min_gap_m(posts),
               "depth_m": sc.depth_m, "loss_tier0": ev.loss(e2),
               "echo_level_db_3d": float(np.mean(echo_level_db(e3))),
               "judges_tier0_info_only": ev.judges(e2), "jitter": [], "sweet_spot": []}
        for sig in JITTER_MM:
            loss, wc = [], []
            for sd in JITTER_SEEDS:
                pj = radial_jitter(posts, sig / 1000, sd)
                ej = ev.echo(pj, stage_scene(cfg, pj))
                loss.append(ev.loss(ej))
                wc.append(_wave_corr(ev.seg(ej), s0))
            row["jitter"].append({"sigma_mm": sig, "loss": float(np.mean(loss)), "wave_corr": float(np.mean(wc)),
                                  "wave_corr_min": float(np.min(wc))})
        offs = [(0.0, y) for y in SIDE_OFFSETS] + [(-x, 0.0) for x in BACK_OFFSETS]
        for off in offs:
            Lp = sc.listener + np.asarray(off)
            sc2 = Scene(source=sc.source, listener=Lp, posts=posts, half_angle_deg=HALF_ANGLE)
            shift = listener_shift_s(sc, Lp, cfg.r0 + 343.0 * len(target.audio) / FS / 4.0)
            e = ev.echo(posts, sc2)
            wc = _wave_corr(ev.seg(np.roll(e, -int(round(shift * FS)), -1)), s0)
            row["sweet_spot"].append({"offset_m": list(off), "wave_corr_vs_nominal": wc,
                                      "loss_tier0": ev.loss(e, shift)})
        side_ok = [o["offset_m"][1] for o in row["sweet_spot"] if o["offset_m"][0] == 0.0
                   and o["wave_corr_vs_nominal"] >= 0.95]
        # contiguous from the centre: the largest tested sideways offset below which every offset keeps >= 0.95
        sw = 0.0
        for y in SIDE_OFFSETS:
            if y in side_ok:
                sw = y
            else:
                break
        row["sweet_spot_side_m"] = sw
        rows.append(row)
        log(f"{name:10s} N={row['n_posts']:4d} fill={100 * row['fill']:.3f}% gap={100 * row['min_gap_m']:.1f}cm "
            f"loss={row['loss_tier0']:.3f} L3d={row['echo_level_db_3d']:.1f} "
            f"wc@1/2/5mm={'/'.join(format(j['wave_corr'], '.3f') for j in row['jitter'])} side={sw:g} m "
            f"[info {row['judges_tier0_info_only']}]")
    return {"candidate": name, "band": list(band), "profile_best_loss": res.info["best_loss"], "rows": rows}


def select(rows):
    """Apply SELECTION to the study rows. Returns (chosen row, reason)."""
    ok = [r for r in rows if r["fill"] <= FILL_MAX + 1e-9 and r["n_posts"] <= POST_CAP]
    if not ok:
        raise SystemExit("no candidate meets the fill and post-count limits")

    def j2(r):
        return next(j for j in r["jitter"] if j["sigma_mm"] == 2.0)

    best_per = {}
    for r in ok:
        k = r["candidate"]
        if k not in best_per or j2(r)["loss"] < j2(best_per[k])["loss"]:
            best_per[k] = r
    ranked = sorted(best_per.values(), key=lambda r: (-r["sweet_spot_side_m"], -j2(r)["wave_corr"],
                                                       -r["echo_level_db_3d"]))
    return ranked[0], [(r["candidate"], r["n_posts"], r["sweet_spot_side_m"], j2(r)["wave_corr"],
                        r["echo_level_db_3d"]) for r in ranked]


def study(threads=4, root=None):
    from echo import export

    t = time.time()
    out = {"what": "Tier 0 pilot candidate study (2D for losses / waveform correlation, 3D for level)",
           "selection": SELECTION, "half_angle_deg": HALF_ANGLE, "post_cap": POST_CAP, "fill_max": FILL_MAX,
           "jitter": f"radial Gaussian sigma {JITTER_MM} mm, seeds {JITTER_SEEDS}", "candidates": []}
    rows = []
    for name in CANDIDATES:
        r = _study_one(name, threads)
        out["candidates"].append(r)
        rows += r["rows"]
    ch, ranking = select(rows)
    out["chosen"] = {"candidate": ch["candidate"], "n_posts": ch["n_posts"], "fill": ch["fill"],
                     "ranking": ranking}
    out["wall_s"] = time.time() - t
    d = Path(root or export.RUNS) / STAGE / "_studies"
    d.mkdir(parents=True, exist_ok=True)
    (d / "design_study_tier0.json").write_text(json.dumps(out, indent=1))
    (d / CHOSEN_FILE).write_text(json.dumps({"candidate": ch["candidate"], "fill": round(ch["fill"], 6),
                                             "n_posts": ch["n_posts"]}, indent=1))
    print("chosen:", out["chosen"], f"({out['wall_s']:.0f} s)")
    return out


# ---------------------------------------------------------------------------------------------------- build checks
SWEET_X = (-1.0, -0.5, -0.25, 0.0)  # back (m, along -x from the nominal listener)
SWEET_Y = (-0.3, -0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2, 0.3)  # sideways


def sweet_spot_map(run_dir):
    """Tier 0 2D waveform correlation of the echo at moved listeners against the nominal one (delay-aligned)."""
    import torch

    from echo.buildkit import _design_inputs, load_run
    from echo.robustness import listener_shift_s
    from echo.scene import Scene
    from echo.tier0 import post_echo
    from stages.s1_study import _wave_corr

    run = load_run(run_dir)
    claps, band, n_out = _design_inputs(run)
    sc = run["scene"]
    cl = torch.as_tensor(claps)
    nom = post_echo(sc.posts, cl, sc, mode="2d", n_out=n_out, band=band).numpy()
    rho_mid = 0.5 * (sc.r_min + sc.effective_r_max)
    grid = []
    for x in SWEET_X:
        row = []
        for y in SWEET_Y:
            Lp = sc.listener + np.array([x, y])
            sc2 = Scene(source=sc.source, listener=Lp, posts=sc.posts, half_angle_deg=sc.half_angle_deg)
            e = post_echo(sc.posts, cl, sc2, mode="2d", n_out=n_out, band=band).numpy()
            sh = int(round(listener_shift_s(sc, Lp, rho_mid) * FS))
            with np.errstate(invalid="ignore", divide="ignore"):
                wc = _wave_corr(np.roll(e, -sh, -1), nom)
            row.append(round(wc, 3) if np.isfinite(wc) else None)  # None: correlation undefined (a zero-energy row)
        grid.append(row)
    return {"x_back_m": list(SWEET_X), "y_side_m": list(SWEET_Y), "wave_corr": grid, "mode": "tier0 2d",
            "what": "waveform correlation (clap-family mean) of the echo at a moved listener vs the nominal listener, "
                    "after removing the on-axis delay change"}


def pilot_checks(run_dir, cand: str):
    """metrics['pilot']: reference thresholds, verdict wording, geometry facts and the sweet-spot map."""
    from echo.buildkit import load_run
    from echo.scene import fill_fraction

    run = load_run(run_dir)
    met = json.loads((Path(run_dir) / "metrics.json").read_text())
    sc = run["scene"]
    own = CANDIDATES[cand][3]
    thr = M.THRESHOLDS[JUDGE_STAGE]
    vals = {m["id"]: m["value"] for m in met["metrics"] if m["tier"] == ("tier1" if met["verified"] else "tier0")}
    ref = {}
    for k, t in thr.items():
        comp = M.METRIC_INFO[k][2]
        v = vals.get(k)
        ref[k] = {"threshold": t, "comparator": comp, "value": v,
                  "meets": None if v is None else bool(v <= t if comp == "<=" else v >= t)}
    aud = audibility_table(run_dir)
    return {"audibility": aud, "candidate": cand, "target_is_stage1_whistle": own, "judge_stage": JUDGE_STAGE,
            "reference_thresholds": {k: [t, M.METRIC_INFO[k][2]] for k, t in thr.items()},
            "reference_values": ref,
            "verdict": ("passed computed against the stage-1 thresholds (the target is stage 1's whistle)" if own else
                        "no pass mark: the spec has none for a pilot and the target is not stage 1's; the stage-1 "
                        "thresholds are shown for reference only and `passed` is false by construction"),
            "post_count": int(len(sc.posts)), "fill_fraction": fill_fraction(sc), "min_gap_m": min_gap_m(sc.posts),
            "half_angle_deg": sc.half_angle_deg, "sweet_spot_map": sweet_spot_map(run_dir)}


def write_checks(run_dir, cand):
    p = Path(run_dir) / "metrics.json"
    met = json.loads(p.read_text())
    met["pilot"] = pilot_checks(run_dir, cand)
    if met["pilot"]["target_is_stage1_whistle"] is False:
        met["passed"] = False
    p.write_text(json.dumps(met, indent=1))
    return met["pilot"]


def write_grating_pack(out_dir, f_hz=3000.0, n=30):
    """Phases 2b and 3a: the uniform 'one note' grating (echo.buildkit.grating_scene) as stake-out CSV, 1:10 template
    (SVG + DXF) and a README, under <pack>/grating/."""
    from echo.buildkit import grating_scene, stakeout_rows, write_stakeout_csv, write_template

    d = Path(out_dir) / "grating"
    d.mkdir(parents=True, exist_ok=True)
    sc = grating_scene(f_hz, n)
    write_stakeout_csv(stakeout_rows(sc, by_ring=True), d / "stakeout.csv", sc)
    t = write_template({"scene": sc, "stage": "grating", "run_id": f"{f_hz:.0f}Hz-{n}posts"}, d, 600.0, 400.0)
    (d / "README.md").write_text(
        f"# One-note grating ({f_hz:.0f} Hz, {n} posts): phases 2b (1:10) and 3a (full scale)\n\n"
        f"Generated by `stages/build_pilot.py` from `echo.buildkit.grating_scene({f_hz:g}, {n})`: posts of 1 cm radius on "
        f"equal-delay ellipses c/(2 f) = {343.0 / (2 * f_hz) * 100:.2f} cm apart in bistatic range from 5 m, bearings "
        f"cycling so no post stands in the shadow of the previous one. A clap returns a {f_hz:.0f} Hz tone of about "
        f"{1000 * n / f_hz:.0f} ms. `stakeout.csv` (full scale, ring by ring, far first), `template_1to10.*` "
        f"({t['n_holes']} holes).\n")
    return d


def copy_listening(run_dir, pack_dir):
    """Put the run's own audio next to the jitter listening files: target, full-wave echo, as heard after the clap."""
    import shutil

    d = Path(pack_dir) / "listening"
    d.mkdir(parents=True, exist_ok=True)
    import soundfile as sf

    rd = Path(run_dir)
    for n in ("target.wav", "echo_tier1.wav", "echo_tier0.wav", "as_heard.wav"):
        if (rd / n).exists():
            shutil.copy2(rd / n, d / f"run_{n}")
    # same recipe as stages/make_listen.py: echo alone at full scale, and the clap then the echo boosted to 12 dB under it
    if (rd / "as_heard.wav").exists() and (rd / "echo_tier1.wav").exists():
        ah, fs = sf.read(rd / "as_heard.wav")
        echo, _ = sf.read(rd / "echo_tier1.wav")
        n = min(len(ah), len(echo))
        clap = np.zeros(n)
        k = int(0.012 * fs)
        clap[:k] = ah[:k]
        e = echo[:n] / (np.max(np.abs(echo[:n])) + 1e-12)
        y = clap + e * np.max(np.abs(clap)) * 10 ** (-12 / 20)
        y = y / np.max(np.abs(y)) * 0.89
        sf.write(d / "clap_then_echo_boosted.wav", np.concatenate([np.zeros(int(0.3 * fs)), y, np.zeros(int(0.3 * fs))]),
                 fs, subtype="PCM_16")
        sf.write(d / "echo_only.wav", np.concatenate([np.zeros(int(0.2 * fs)), 0.89 * e, np.zeros(int(0.2 * fs))]), fs,
                 subtype="PCM_16")
    return d


START_RANGES_M = (3.0, 6.0, 10.0, 15.0)
POP_FACTORS = (1, 2, 4)


def audibility_table(run_dir):
    """Tier 0 3D levers on audibility after the clap (fast model, free field, infinite posts):
    (a) the same rings moved outward so the field starts at r (every post's bistatic range + (r - rho_min), same
        bearing): first-arrival delay, last arrival, far edge, level, and the posts needed to recover the as-designed level at
        6 dB per doubling (coherent ring population);
    (b) ring population x1, x2, x4 (each post duplicated at a bearing offset on its own ellipse): level per doubling
        and the resulting ground coverage."""
    import torch

    from echo.buildkit import _design_inputs, _echo3d, _level_db, load_run
    from echo.scene import Scene, bistatic_range, ellipse_point, fill_fraction

    run = load_run(run_dir)
    claps, band, n_out0 = _design_inputs(run)
    sc = run["scene"]
    p = sc.posts
    rho = bistatic_range(p[:, :2], sc.source, sc.listener)
    th = np.arctan2(p[:, 1] - sc.source[1], p[:, 0] - sc.source[0])  # polar angle about S (ellipse_point)
    rows = []
    base = None
    for r0 in (float(rho.min()),) + tuple(r for r in START_RANGES_M if r > rho.min() + 0.5):  # as designed first
        d = r0 - rho.min()
        xy = ellipse_point(rho + d, th, sc.source, sc.listener)
        q = np.column_stack([xy, p[:, 2]])
        n_out = n_out0 + int(np.ceil(2 * max(d, 0) / sc.c * FS))
        s2 = Scene(source=sc.source, listener=sc.listener, posts=q, half_angle_deg=sc.half_angle_deg, c=sc.c)
        L = _level_db(_echo3d(q, s2, claps, band, n_out))
        base = L if base is None else base
        rows.append({"start_rho_m": float(r0), "first_echo_ms": 1000 * 2 * r0 / sc.c,
                     "last_echo_ms": 1000 * 2 * (rho.max() + d) / sc.c, "far_edge_m": float(np.max(np.hypot(*q[:, :2].T))),
                     "level_db": L, "delta_db": L - base,
                     "posts_to_recover_level": int(round(len(p) * 10 ** ((base - L) / 20)))})
    pop = []
    for k in POP_FACTORS:
        qs = []
        for j in range(k):
            dth = np.radians(0.6) * (j - (k - 1) / 2)  # small bearing offsets on the same ellipse
            xy = ellipse_point(rho, th + dth, sc.source, sc.listener)
            qs.append(np.column_stack([xy, p[:, 2]]))
        q = np.vstack(qs)
        s2 = Scene(source=sc.source, listener=sc.listener, posts=q, half_angle_deg=sc.half_angle_deg, c=sc.c)
        L = _level_db(_echo3d(q, s2, claps, band, n_out0))
        pop.append({"factor": k, "posts": int(len(q)), "level_db": L, "fill": fill_fraction(s2)})
    for x in pop:
        x["delta_db"] = x["level_db"] - pop[0]["level_db"]
    return {"what": "Tier 0 3D, free field, infinite posts, clap family mean peak, dB re the direct clap at the ear; "
                    "fast model only (no extinction: coverage above the stage-1 value adds extinction the fast model "
                    "does not see)", "start_range": rows, "population": pop}



def run_pilot(tier1=True, runs_root=None, command=None, threads=4):
    ch = _chosen(runs_root)
    cfg = make_config(ch["candidate"], fill=ch["fill"], threads=threads)
    own = CANDIDATES[ch["candidate"]][3]
    if own:  # the stage-1 whistle: judged against the stage-1 thresholds (same values, same single source)
        M.THRESHOLDS.setdefault(STAGE, M.THRESHOLDS[JUDGE_STAGE])
    run_dir, _, _ = run_stage(cfg, Tier1Hooks() if tier1 else None, command=command, runs_root=runs_root)
    write_checks(run_dir, ch["candidate"])
    return Path(run_dir)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build-optimized pilot design")
    ap.add_argument("--study", action="store_true", help="Tier 0 candidate study (writes _studies/chosen.json)")
    ap.add_argument("--tier0-only", action="store_true")
    ap.add_argument("--checks", default=None, help="recompute metrics['pilot'] for an existing run folder")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--pack", default=None, help="write the build pack (physics + grating) for a pilot run folder")
    a = ap.parse_args(argv)
    if a.study:
        study(a.threads)
        return 0
    if a.pack:
        import torch

        from echo.buildkit import build_pack

        torch.set_num_threads(a.threads)
        pd = build_pack(a.pack)
        print("wrote", pd, write_grating_pack(pd), copy_listening(a.pack, pd))
        return 0
    if a.checks:
        print(write_checks(a.checks, _chosen()["candidate"]))
        return 0
    args = list(argv if argv is not None else sys.argv[1:])
    cmd = " ".join(["uv run python -m", f"stages.{STAGE}"] + [shlex.quote(x) for x in args])
    rd = run_pilot(tier1=not a.tier0_only, command=cmd, threads=a.threads)
    print("wrote", rd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
