"""Tier 1 solver validation: the four checks of the spec, written to runs/validation/metrics.json.

  uv run python -m stages.validate            (about 10 minutes on 8 cores)

1. Single rigid cylinder: Tier 1 backscatter vs the exact 2D line-source series (Hankel functions) within 1 dB in
   every 1/6-octave band of 500-4000 Hz, per catalog radius, at two or more sub-cell offsets of the post centre.
   Measured at the stage-1 grid (f_max 4 kHz) and, for information, at the stage-3 grid (f_max 2 kHz).
2. Grid convergence: halving dx changes the echo level of a reference design by < 1 dB (every clap variant).
3. Empty scene: after the direct clap, the listener record minus the analytic free field stays below -60 dB.
4. Tier 0 (mode="2d", same band) vs Tier 1 on a sparse design: per-post echo levels agree within 2 dB.
Also writes the sample field video to runs/_samples/ (field.webm, field.json, scene.json).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.special import h2vp, hankel2, jvp

from echo import tier1 as t1
from echo.clap import clap_family
from echo.field_video import render_field_video
from echo.scene import C0, FS, RADII, Scene, ellipse_point, to_json

OUT = Path(__file__).resolve().parent.parent / "runs" / "validation"
SAMPLES = Path(__file__).resolve().parent.parent / "runs" / "_samples"
F_LO = 300.0
BAND = (500.0, 4000.0)


def analytic_cylinder_ir_spectrum(f, post, source=(0.0, 0.0), listener=(0.0, 0.3), c=C0, n_terms=40):
    """H_scat/H_direct * exp(-i w |SL|/c) for a rigid cylinder and a 2D line source (DSP convention, H^(2)).

    Exact Graf series: p_s = sum_n c_n H_n(k d_s) H_n(k d_l) cos(n dtheta) eps_n, c_n = -J_n'(ka)/H_n'(ka).
    """
    f = np.asarray(f, dtype=float)
    k = 2 * np.pi * f / c
    x0, a = np.asarray(post[:2], float), float(post[2])
    vs, vl = np.asarray(source, float) - x0, np.asarray(listener, float) - x0
    ds, dl = np.hypot(*vs), np.hypot(*vl)
    dth = np.arctan2(vl[1], vl[0]) - np.arctan2(vs[1], vs[0])
    tot = np.zeros_like(k, dtype=complex)
    for n in range(n_terms + 1):
        term = -jvp(n, k * a) / h2vp(n, k * a) * hankel2(n, k * ds) * hankel2(n, k * dl) * np.cos(n * dth)
        tot += term if n == 0 else 2 * term
    d = np.hypot(*(np.asarray(listener, float) - np.asarray(source, float)))
    return tot / hankel2(0, k * d) * np.exp(-2j * np.pi * f * d / c)


def band_errors_db(ir, Ha_fun, f_max, nfft=16384, f_lo_band=500.0):
    """Per 1/6-octave band (500 Hz .. f_max) energy ratio, dB, of the Tier 1 ir spectrum vs the analytic one."""
    f = np.fft.rfftfreq(nfft, 1 / FS)
    Ht = np.fft.rfft(ir, nfft)
    Ha = np.zeros(len(f), complex)
    Ha[1:] = Ha_fun(f[1:])
    Ha *= t1.band_mask(f, F_LO, f_max)
    edges = f_lo_band * 2 ** np.arange(0, np.log2(f_max / f_lo_band) + 1e-9, 1 / 6)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        b = (f >= lo) & (f < hi)
        out.append(float(10 * np.log10(np.sum(abs(Ht[b]) ** 2) / np.sum(abs(Ha[b]) ** 2))))
    return edges, out


def check_cylinder(f_max, offsets, radii=RADII, rng_x=3.0):
    rows = []
    for a in radii:
        for ox, oy in offsets:
            post = [rng_x + ox, oy, a]
            r = t1.run_tier1(Scene(posts=np.array([post])), f_max, 2 * rng_x / C0 + 0.02)
            edges, err = band_errors_db(r.ir[0], lambda f: analytic_cylinder_ir_spectrum(f, post), f_max)
            rows.append({"radius_m": a, "offset_m": [ox, oy], "dx": r.dx, "r_over_dx": a / r.dx,
                         "area_scale": t1.area_scale(a, r.dx), "band_edges_hz": [round(e, 1) for e in edges],
                         "err_db": [round(e, 3) for e in err], "max_abs_err_db": round(max(map(abs, err)), 3),
                         "wall_s": round(r.wall_s, 1)})
            print(f"  cyl f_max={f_max} a={a} off={ox:.4f},{oy:.4f}: max |err| {rows[-1]['max_abs_err_db']} dB",
                  flush=True)
    per_radius = {}
    for a in radii:
        mx = max(rw["max_abs_err_db"] for rw in rows if rw["radius_m"] == a)
        per_radius[str(a)] = {"max_abs_err_db": mx, "pass": mx <= 1.0}
    return rows, per_radius


def sparse_design():
    """Eight posts of the validated radii, well separated in bistatic range (>= 1.4 m) and angle."""
    rho = np.array([3.6, 5.0, 6.4, 7.8, 9.2, 10.6, 12.0, 13.4])
    ang = np.radians([-12, 9, -4, 15, -16, 3, 11, -8])
    xy = ellipse_point(rho, ang)
    return np.c_[xy, [0.01, 0.02] * 4]


def echo_levels(E, delays, half_w=0.002):
    """Energy level (dB) of each echo window [K, n_posts] and of the whole echo [K]."""
    t = np.arange(E.shape[1]) / FS
    win = [(t >= d - half_w) & (t < d + half_w + 0.008) for d in delays]
    per = np.array([[10 * np.log10(np.sum(e[w] ** 2) + 1e-30) for w in win] for e in E])
    tot = 10 * np.log10(np.sum(E ** 2, axis=1) + 1e-30)
    return per, tot


def check_convergence(claps):
    posts = sparse_design()[:3]
    scene = Scene(posts=posts)
    t_end = 2 * 7.0 / C0
    res = {}
    for ppw in (t1.PPW_DEFAULT, 2 * t1.PPW_DEFAULT):
        r = t1.run_tier1(scene, 4000.0, t_end, ppw=ppw)
        E = t1.echoes(r, claps)
        per, tot = echo_levels(E, 2 * np.array([0.5 * (np.hypot(*p[:2]) + np.hypot(p[0], p[1] - 0.3))
                                                for p in posts]) / C0)
        res[ppw] = {"dx": r.dx, "per": per, "tot": tot, "wall_s": r.wall_s}
        print(f"  convergence ppw={ppw} dx={r.dx:.4f} wall={r.wall_s:.0f}s", flush=True)
    a, b = res[t1.PPW_DEFAULT], res[2 * t1.PPW_DEFAULT]
    d_tot = (a["tot"] - b["tot"]).tolist()
    d_per = (a["per"] - b["per"]).tolist()
    worst = float(max(np.max(np.abs(d_tot)), np.max(np.abs(d_per))))
    return {"posts": posts.tolist(), "dx": [a["dx"], b["dx"]], "wall_s": [a["wall_s"], b["wall_s"]],
            "delta_total_db_per_clap": d_tot, "delta_per_post_db": d_per, "max_abs_delta_db": worst,
            "pass": worst < 1.0}


def check_empty(claps, f_max=4000.0):
    """Stage-1-sized empty box (17.5 m x 12.5 m region incl. margins); residual vs the analytic 2D free field."""
    probe = Scene(posts=np.array([[3.2, -5.3, 0.01], [16.4, 5.6, 0.01]]))  # only sets the box
    pl = t1.plan(probe, f_max, 0.110)
    g, dt, m, dx = pl["grid"], pl["dt"], pl["m"], pl["dx"]
    fs_sim = m * FS
    sig = t1.source_pulse(fs_sim, pl["n_steps"], F_LO, f_max, pl["t_src0"])
    t0 = time.time()
    rec, _, _ = t1.simulate(g, C0, dt, pl["n_steps"], [0.0, 0.0], sig, [[0.0, 0.3]])
    wall = time.time() - t0
    n = rec.shape[1]
    nfft = 2 * int(np.ceil(n / m))
    f = np.fft.rfftfreq(nfft, 1 / FS)
    band = t1.band_mask(f, F_LO, f_max)
    use = band > 0
    fsim = t1.sim_frequency(f[use], C0, dt, dx)
    Pe = t1._dft_at(rec, fs_sim, fsim)[0]
    S = t1._dft_at(sig[None], fs_sim, fsim)[0] * np.exp(-2j * np.pi * fsim * dt)  # source seen one step later
    k = 2 * np.pi * f[use] / C0
    model = S * f[use] * hankel2(0, k * 0.3)  # p = rho w Q H0^(2)(k r) / 4, up to a constant
    g_fit = np.vdot(model, Pe) / np.vdot(model, model)  # one complex constant
    R = np.zeros(len(f), complex)
    R[use] = (Pe / (g_fit * model) - 1.0) * band[use]
    R *= np.exp(-2j * np.pi * f * 0.3 / C0)
    res_ir = np.fft.irfft(R, nfft)
    C = np.fft.rfft(claps, nfft, axis=1)
    resid = np.fft.irfft(C * np.fft.rfft(res_ir)[None], nfft, axis=1)
    t = np.arange(nfft) / FS
    after = (t > 0.3 / C0 + claps.shape[1] / FS) & (t < 0.110)
    lvl = 20 * np.log10(np.max(np.abs(resid[:, after]), axis=1) + 1e-30)
    return {"box_m": g.interior_extent(), "grid": [g.nx, g.ny], "dx": dx, "wall_s": round(wall, 1),
            "fit_gain": [float(g_fit.real), float(g_fit.imag)],
            "max_after_direct_db_per_clap": [round(float(v), 2) for v in lvl],
            "max_after_direct_db": round(float(lvl.max()), 2), "threshold_db": -60.0,
            "pass": bool(lvl.max() < -60.0)}


def check_tier0(claps, sample=True):
    import torch

    from echo.tier0 import post_echo

    posts = sparse_design()
    scene = Scene(posts=posts)
    t_end = 2 * 14.0 / C0
    r = t1.run_tier1(scene, 4000.0, t_end, record_field=sample, field_dt=0.25e-3)
    E1 = t1.echoes(r, claps)
    n = E1.shape[1]
    E0 = post_echo(torch.as_tensor(posts), torch.as_tensor(claps), scene, mode="2d", n_out=n,
                   band=(F_LO, 4000.0)).numpy()
    rho = 0.5 * (np.hypot(posts[:, 0], posts[:, 1]) + np.hypot(posts[:, 0], posts[:, 1] - 0.3))
    p1, tot1 = echo_levels(E1, 2 * rho / C0)
    p0, tot0 = echo_levels(E0, 2 * rho / C0)
    d = p1 - p0
    out = {"posts": posts.tolist(), "wall_s": round(r.wall_s, 1), "dx": r.dx, "grid": list(r.grid),
           "tier1_minus_tier0_per_post_db": np.round(d, 3).tolist(),
           "mean_per_post_db": np.round(d.mean(0), 3).tolist(),
           "total_delta_db_per_clap": np.round(tot1 - tot0, 3).tolist(),
           "max_abs_delta_db": round(float(np.max(np.abs(d))), 3), "threshold_db": 2.0,
           "pass": bool(np.max(np.abs(d)) <= 2.0)}
    if sample and r.field is not None:
        SAMPLES.mkdir(parents=True, exist_ok=True)
        fld = r.field
        block = render_field_video(fld["frames"], fld["extent"], SAMPLES / "field.webm", fps=30,
                                   t0=fld["t0"], dt_frame=fld["dt_frame"])
        (SAMPLES / "field.json").write_text(json.dumps(block, indent=1))
        to_json(scene, SAMPLES / "scene.json")
        out["sample_field"] = block
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    T0 = time.time()
    claps = clap_family(5)
    OUT.mkdir(parents=True, exist_ok=True)
    m = {"solver": {"tier1": "fdtd", "engine": t1.ENGINE_VERSION, "ppw": t1.PPW_DEFAULT, "cfl": t1.CFL_DEFAULT,
                    "area_cal": {str(k): v for k, v in t1.AREA_CAL.items()}, "phi_solid": t1.PHI_SOLID,
                    "k_max": t1.K_MAX, "device": "cpu"}, "checks": {}}
    print("check 3: empty scene", flush=True)
    m["checks"]["empty_scene"] = check_empty(claps)
    print("check 1: rigid cylinder", flush=True)
    offs = [(0.0, 0.0), (0.0035, 0.0053), (0.0053, 0.0021)]
    rows4, pr4 = check_cylinder(4000.0, offs)
    rows2, pr2 = check_cylinder(2000.0, offs)
    validated = [float(a) for a in RADII if pr4[str(a)]["pass"]]
    m["checks"]["cylinder"] = {"threshold_db": 1.0, "band_hz": [500, 4000], "stage1_grid": {"f_max": 4000,
                               "per_radius": pr4, "rows": rows4},
                               "stage3_grid": {"f_max": 2000, "per_radius": pr2, "rows": rows2},
                               "validated_radii_stage1": validated,
                               "validated_radii_stage3": [float(a) for a in RADII if pr2[str(a)]["pass"]],
                               "pass": all(pr4[str(a)]["pass"] for a in (0.01, 0.02)),
                               "note": "pass = the radii the designs use (1 cm, 2 cm) meet 1 dB at the stage-1 "
                                       "grid; other radii are listed with their own pass flag"}
    print("check 2: grid convergence", flush=True)
    m["checks"]["grid_convergence"] = check_convergence(claps)
    print("check 4: tier0 vs tier1 sparse design (+ sample field video)", flush=True)
    m["checks"]["tier0_vs_tier1"] = check_tier0(claps)
    m["passed"] = all(c["pass"] for c in m["checks"].values())
    m["wall_s"] = round(time.time() - T0, 1)
    (OUT / "metrics.json").write_text(json.dumps(m, indent=1))
    for k, c in m["checks"].items():
        print(f"{k}: pass={c['pass']}")
    print("validation passed:", m["passed"], f"({m['wall_s']} s)")
    return m


if __name__ == "__main__":
    main()
