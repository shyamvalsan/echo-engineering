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


EXTRA_LISTENERS = {"forward": (6.0, 0.0), "bistatic_90": (3.0, 3.0)}  # scattering angle 0 and 90 deg


def check_cylinder(f_max, offsets, radii=RADII, rng_x=3.0, extra_angles_for=(0.01, 0.02)):
    """Backscatter for every radius and offset. For radii in extra_angles_for (at offset 0) also forward scatter
    (listener behind the post) and a 90-degree bistatic angle, as extra sensors of the same run."""
    rows = []
    for a in radii:
        for k, (ox, oy) in enumerate(offsets):
            post = [rng_x + ox, oy, a]
            names = ["back"]
            lst = [(0.0, 0.3)]
            if a in extra_angles_for and k == 0:
                names += list(EXTRA_LISTENERS)
                lst += list(EXTRA_LISTENERS.values())
            tend = 2 * rng_x / C0 + 0.02
            r = t1.run_tier1(Scene(posts=np.array([post])), f_max, tend, listeners=np.array(lst))
            for li, (nm, L) in enumerate(zip(names, lst)):
                edges, err = band_errors_db(r.ir[li], lambda f: analytic_cylinder_ir_spectrum(f, post, listener=L),
                                            f_max)
                rows.append({"radius_m": a, "offset_m": [ox, oy], "angle": nm, "listener": list(L), "dx": r.dx,
                             "r_over_dx": a / r.dx, "area_scale": t1.area_scale(a, r.dx),
                             "band_edges_hz": [round(e, 1) for e in edges], "err_db": [round(e, 3) for e in err],
                             "max_abs_err_db": round(max(map(abs, err)), 3), "wall_s": round(r.wall_s, 1)})
                print(f"  cyl f_max={f_max} a={a} off={ox:.4f},{oy:.4f} {nm}: max |err| "
                      f"{rows[-1]['max_abs_err_db']} dB", flush=True)
    per_radius = {}
    for a in radii:
        mx = max(rw["max_abs_err_db"] for rw in rows if rw["radius_m"] == a)
        per_radius[str(a)] = {"max_abs_err_db": mx, "pass": mx <= 1.0}
    return rows, per_radius


def check_heldout(f_max=4000.0, radius=0.01, n=10, seed=123):
    """Backscatter of one post at n random sub-cell offsets that were not used to fit AREA_CAL."""
    dx = t1.plan(Scene(posts=np.array([[3.0, 0.0, radius]])), f_max, 0.04)["dx"]
    offs = np.random.default_rng(seed).uniform(0, dx, (n, 2))
    rows, pr = check_cylinder(f_max, [tuple(o) for o in offs], radii=(radius,), extra_angles_for=())
    return {"radius_m": radius, "f_max": f_max, "offsets_m": offs.round(5).tolist(),
            "max_abs_err_db": [r["max_abs_err_db"] for r in rows], "err_db": [r["err_db"] for r in rows],
            "pass": pr[str(radius)]["pass"]}


def sparse_design():
    """Eight posts of the validated radii, well separated in bistatic range (>= 1.4 m) and angle."""
    rho = np.array([3.6, 5.0, 6.4, 7.8, 9.2, 10.6, 12.0, 13.4])
    ang = np.radians([-12, 9, -4, 15, -16, 3, 11, -8])
    xy = ellipse_point(rho, ang)
    return np.c_[xy, [0.01, 0.02] * 4]


def echo_windows(delays, n, pre=0.0005, max_len=0.008):
    """Boolean masks [d - pre, d + min(max_len, gap to the next echo - pre)) per post, at FS, length n."""
    t = np.arange(n) / FS
    d = np.asarray(delays, float)
    order = np.argsort(d)
    nxt = np.full(len(d), np.inf)
    nxt[order[:-1]] = d[order[1:]]
    return [(t >= di - pre) & (t < di + min(max_len, ni - di - pre)) for di, ni in zip(d, nxt)]


def echo_levels(E, delays):
    """Energy level (dB) of each post's own echo window [K, n_posts] and of the whole echo [K]."""
    win = echo_windows(delays, E.shape[1])
    per = np.array([[10 * np.log10(np.sum(e[w] ** 2) + 1e-30) for w in win] for e in E])
    tot = 10 * np.log10(np.sum(E ** 2, axis=1) + 1e-30)
    return per, tot


def xcorr_lag(a, b, up=32):
    """Lag (s) of a relative to b (positive: a later), parabolic peak of the band-limited cross-correlation."""
    n = len(a) + len(b)
    nfft = 1 << int(np.ceil(np.log2(n)))
    X = np.fft.rfft(a, nfft) * np.conj(np.fft.rfft(b, nfft))
    cc = np.fft.irfft(X, nfft * up)
    k = int(np.argmax(cc))
    y0, y1, y2 = cc[k - 1], cc[k], cc[(k + 1) % len(cc)]
    den = y0 - 2 * y1 + y2
    frac = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    lag = (k + frac) / (FS * up)
    if lag > nfft / (2 * FS):
        lag -= nfft / FS
    return lag


def timing_metrics(Ea, Eb, t_lo, t_hi, win_s=0.004):
    """Compare echo a with reference b: lags of sliding windows vs window time (a linear fit's slope is the
    time-scale error, i.e. the pitch error of anything the layout encodes), band-wise group delay of the late
    half, and the energy-weighted instantaneous-frequency ratio in 2-4 kHz."""
    from scipy.signal import hilbert

    from echo.clap import band_limit
    n = Ea.shape[-1]
    t = np.arange(n) / FS
    lags, tcs, wts = [], [], []
    for t0 in np.arange(t_lo, t_hi - win_s, win_s / 2):
        w = (t >= t0) & (t < t0 + win_s)
        for a, b in zip(Ea, Eb):
            e = np.sum(b[w] ** 2)
            if e <= 0:
                continue
            lags.append(xcorr_lag(a[w], b[w]))
            tcs.append(t0 + win_s / 2)
            wts.append(e)
    lags, tcs, wts = map(np.asarray, (lags, tcs, wts))
    A = np.c_[tcs, np.ones_like(tcs)] * np.sqrt(wts)[:, None]
    slope, icpt = np.linalg.lstsq(A, lags * np.sqrt(wts), rcond=None)[0]
    late = (t >= 0.5 * (t_lo + t_hi)) & (t < t_hi)
    gd = {}
    for lo, hi in ((500, 1000), (1000, 2000), (2000, 4000)):
        la = band_limit(Ea * late, lo, hi)
        lb = band_limit(Eb * late, lo, hi)
        gd[f"{lo}-{hi}"] = float(np.mean([xcorr_lag(x, y) for x, y in zip(la, lb)]))
    tmid = float(np.average(tcs, weights=wts))
    ifr = []
    for a, b in zip(Ea, Eb):
        za, zb = hilbert(band_limit(a, 2000, 4000)), hilbert(band_limit(b, 2000, 4000))
        fa = np.diff(np.unwrap(np.angle(za))) * FS / (2 * np.pi)
        fb = np.diff(np.unwrap(np.angle(zb))) * FS / (2 * np.pi)
        wa, wb = np.abs(za[1:]) ** 2, np.abs(zb[1:]) ** 2
        ifr.append(np.average(fa, weights=wa) / np.average(fb, weights=wb) - 1)
    return {"time_scale_error_pct": float(100 * slope), "lag_at_mid_ms": float(1e3 * (icpt + slope * tmid)),
            "t_mid_s": tmid, "lag_over_delay_pct": float(100 * (icpt + slope * tmid) / tmid),
            "group_delay_late_ms": {k: 1e3 * v for k, v in gd.items()},
            "group_delay_late_pct_of_delay": {k: 100 * v / (0.75 * t_hi + 0.25 * t_lo) for k, v in gd.items()},
            "inst_freq_ratio_2_4khz_pct": float(100 * np.mean(ifr))}


def _pair_runs(scene, t_end, claps, ppws, label):
    res = {}
    for ppw in ppws:
        r = t1.run_tier1(scene, 4000.0, t_end, ppw=ppw)
        res[ppw] = {"r": r, "E": t1.echoes(r, claps)}
        print(f"  {label} ppw={ppw} dx={r.dx:.4f} grid={r.grid} wall={r.wall_s:.0f}s", flush=True)
    return res


def check_convergence(claps):
    """(i) three isolated posts: per-post and total echo level; (ii) dense patch of the stage-1 design."""
    out = {}
    posts = sparse_design()[:3]
    rho = 0.5 * (np.hypot(posts[:, 0], posts[:, 1]) + np.hypot(posts[:, 0], posts[:, 1] - 0.3))
    pp = (t1.PPW_DEFAULT, 2 * t1.PPW_DEFAULT)
    res = _pair_runs(Scene(posts=posts), 2 * 7.0 / C0, claps, pp, "sparse")
    a, b = res[pp[0]], res[pp[1]]
    pa, ta = echo_levels(a["E"], 2 * rho / C0)
    pb, tb = echo_levels(b["E"], 2 * rho / C0)
    worst = float(max(np.max(np.abs(ta - tb)), np.max(np.abs(pa - pb))))
    out["sparse"] = {"posts": posts.tolist(), "dx": [a["r"].dx, b["r"].dx],
                     "wall_s": [a["r"].wall_s, b["r"].wall_s], "delta_total_db_per_clap": (ta - tb).tolist(),
                     "delta_per_post_db": (pa - pb).tolist(), "max_abs_delta_db": worst, "pass": worst < 1.0}
    out["dense"] = check_dense(claps)
    out["max_abs_delta_db"] = max(worst, out["dense"]["max_abs_level_delta_db"])
    out["pass"] = out["sparse"]["pass"] and out["dense"]["pass"]
    return out


def dense_patch(lo=6.0, hi=8.5):
    """Posts of the stage-1 design (latest runs/s1_bird/*/scene.json) with bistatic range in [lo, hi)."""
    from echo.scene import bistatic_range, from_json
    path = sorted((Path(__file__).resolve().parent.parent / "runs" / "s1_bird").glob("*/scene.json"))[-1]
    sc = from_json(path)
    rho = bistatic_range(sc.posts[:, :2])
    return sc.posts[(rho >= lo) & (rho < hi)], str(path.relative_to(path.parents[3])), (lo, hi)


def check_dense(claps):
    posts, src, (lo, hi) = dense_patch()
    pp = (t1.PPW_DEFAULT, 2 * t1.PPW_DEFAULT)
    res = _pair_runs(Scene(posts=posts), 2 * hi / C0 + 0.012, claps, pp, "dense")
    a, b = res[pp[0]], res[pp[1]]
    la = 10 * np.log10(np.sum(a["E"] ** 2, axis=1))
    lb = 10 * np.log10(np.sum(b["E"] ** 2, axis=1))
    tm = timing_metrics(a["E"], b["E"], 2 * lo / C0, 2 * hi / C0 + 0.006)
    worst_t = max(abs(tm["time_scale_error_pct"]), abs(tm["lag_over_delay_pct"]),
                  abs(tm["inst_freq_ratio_2_4khz_pct"]))
    return {"source_scene": src, "rho_range_m": [lo, hi], "n_posts": int(len(posts)),
            "radii": sorted(set(posts[:, 2].tolist())), "dx": [a["r"].dx, b["r"].dx],
            "grid": [list(a["r"].grid), list(b["r"].grid)], "wall_s": [a["r"].wall_s, b["r"].wall_s],
            "level_delta_db_per_clap": (la - lb).round(3).tolist(),
            "max_abs_level_delta_db": float(np.max(np.abs(la - lb))), "timing": tm,
            "max_abs_timing_pitch_error_pct": float(worst_t), "timing_target_pct": 0.2,
            "timing_meets_target": bool(worst_t <= 0.2),
            "pass": bool(np.max(np.abs(la - lb)) < 1.0),
            "note": "pass = spec level rule (< 1 dB); timing/pitch error reported against the 0.2 % target"}


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


def far_post_diagnostic(rng_m=13.0, radius=0.01, f_max=4000.0):
    """One post at 13 m on axis: Tier 1 and Tier 0 each against the analytic series (mean dB over 500-4000 Hz)."""
    import torch

    from echo.tier0 import post_transfer
    post = [rng_m, 0.0, radius]
    scene = Scene(posts=np.array([post]))
    r = t1.run_tier1(scene, f_max, 2 * rng_m / C0 + 0.02)
    _, e1 = band_errors_db(r.ir[0], lambda f: analytic_cylinder_ir_spectrum(f, post), f_max)
    nfft = 16384
    H0 = post_transfer(torch.as_tensor(np.array([post])), scene, mode="2d", n_fft=nfft, band=(F_LO, f_max),
                       absorption=False).numpy()
    _, e0 = band_errors_db(np.fft.irfft(H0, nfft), lambda f: analytic_cylinder_ir_spectrum(f, post), f_max)
    return {"post": post, "tier1_vs_analytic_db": np.round(e1, 3).tolist(), "tier0_vs_analytic_db":
            np.round(e0, 3).tolist(), "tier1_mean_db": round(float(np.mean(e1)), 3),
            "tier0_mean_db": round(float(np.mean(e0)), 3)}


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
    win = echo_windows(2 * rho / C0, n)
    lag_ms = [[1e3 * xcorr_lag(e1[w], e0[w]) for w in win] for e1, e0 in zip(E1, E0)]
    out = {"posts": posts.tolist(), "wall_s": round(r.wall_s, 1), "dx": r.dx, "grid": list(r.grid),
           "window": "[d - 0.5 ms, d + min(8 ms, next delay - d - 0.5 ms))",
           "tier1_minus_tier0_lag_ms_per_post": np.round(np.mean(lag_ms, 0), 4).tolist(),
           "tier1_minus_tier0_per_post_db": np.round(d, 3).tolist(),
           "mean_per_post_db": np.round(d.mean(0), 3).tolist(),
           "total_delta_db_per_clap": np.round(tot1 - tot0, 3).tolist(),
           "max_abs_delta_db": round(float(np.max(np.abs(d))), 3), "threshold_db": 2.0,
           "pass": bool(np.max(np.abs(d)) <= 2.0)}
    out["far_post_diagnostic"] = far_post_diagnostic()
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
    held = check_heldout()
    pr4["0.01"]["pass"] = pr4["0.01"]["pass"] and held["pass"]
    pr4["0.01"]["heldout_max_abs_err_db"] = max(held["max_abs_err_db"])
    validated = [float(a) for a in RADII if pr4[str(a)]["pass"]]
    m["checks"]["cylinder"] = {"threshold_db": 1.0, "band_hz": [500, 4000], "stage1_grid": {"f_max": 4000,
                               "per_radius": pr4, "rows": rows4},
                               "stage3_grid": {"f_max": 2000, "per_radius": pr2, "rows": rows2},
                               "heldout_1cm_4khz": held,
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
