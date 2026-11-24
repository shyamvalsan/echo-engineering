"""Inverse design, step 2: realize a reflectivity profile as discrete posts from the radius catalog.

Profile convention (Tier 0): profile[i] = equivalent number of reference posts (radius a_ref) in bistatic-range bin
rho_i = r0 + i*dr. A post of radius a counts as w_a reference posts, where w_a is its backscatter amplitude relative
to a_ref averaged over the design band (`radius_weights`, from Tier 0's analytic `cylinder_response`).

Along range: the profile's mass, spread uniformly inside each bin, is integrated to a continuous cumulative mass
M(rho); post k (weight w_k) is placed at the exact continuous rho where M crosses the midpoint of its mass interval
(error diffusion / inverse CDF), never snapped to bin centres. The profile oscillates with a 4.9 cm period at 3.5 kHz,
so sub-centimetre placement matters.

Radius choice: the reference radius a_ref is preferred (it matches the profile model's spectral shape, and among the
catalog it is the smallest one that does not need 3-4x more posts for the same strength); a larger radius is used
only where the local demand exceeds what a_ref posts can supply on that arc with the minimum gap.

Across the arc: each post sits on its equal-delay ellipse (`ellipse_point`) at a polar angle drawn from a golden-ratio
(low-discrepancy) sequence across the wedge, with a seeded random offset. Candidates are tried in sequence; the first
one that keeps the minimum surface gap (hard) and is not in the shadow of a nearer post (angular separation as seen
from the source at least the sum of the two posts' angular half-sizes, for nearer posts within `shadow_depth` in range)
is taken. If no candidate is shadow-free, the first gap-respecting one is taken and counted as a shadow violation; if no
candidate respects the gap, the post is dropped and counted.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from echo.scene import BAND, HALF_ANGLE_DEG, MIN_GAP, RADII, R_MIN, Scene, bistatic_range, ellipse_point, in_wedge
from echo.tier0 import DR_PROFILE, cylinder_response

GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0
POLISH_MAX_POSTS = 20000  # above this the range polish is skipped (time ~ N x bins x steps)
POLISH_MAX_WORK = 2.5e7  # posts x in-band FFT bins per step (~8 s/step at 1e4 posts x 3200 bins on 8 threads)
PACKING = 0.35  # usable fraction of the arc area for random sequential placement with the gap (capacity estimate)


def radius_weights(radii=RADII, a_ref=0.02, band=BAND, c=343.0, n_f=64):
    """w_a = mean over band of |T_a(pi)| / |T_aref(pi)| (backscatter amplitude relative to the reference post)."""
    f = np.linspace(band[0], band[1], n_f)
    tref = np.abs(cylinder_response(a_ref, f, np.pi, c))
    return {float(a): float(np.mean(np.abs(cylinder_response(a, f, np.pi, c)) / tref)) for a in radii}


def wedge_area(r_lo, r_hi, half_angle_deg=HALF_ANGLE_DEG):
    return math.radians(half_angle_deg) * (r_hi**2 - r_lo**2)


def scale_profile(profile, target_fill, r0, dr=DR_PROFILE, a_ref=0.02, r_min=R_MIN, half_angle_deg=HALF_ANGLE_DEG):
    """Rescale a profile so that, realized with a_ref posts, the post area fills target_fill of the wedge between
    r_min and the end of the profile."""
    p = np.asarray(profile, dtype=float)
    r_end = r0 + (len(p) - 1) * dr
    n_posts = target_fill * wedge_area(r_min, r_end, half_angle_deg) / (math.pi * a_ref**2)
    return p * (n_posts / p.sum())


def _polish_bins(rho_max, band, c=343.0, n_clap=128, fs=16000):
    from echo.tier0 import choose_n_fft

    md = 2 * (rho_max + 0.05) / c
    n_fft = choose_n_fft(int(np.ceil(md * fs)), md, n_clap)
    return int((band[1] - band[0]) / (fs / n_fft)) + 1


def _arc_len(rho, half_angle_deg):
    return 2.0 * math.radians(half_angle_deg) * rho


def realize(profile, scene_cfg: Scene | None = None, seed=0, *, r0, dr=DR_PROFILE, a_ref=0.02, radii=RADII,
            band=BAND, gap=MIN_GAP, shadow_depth=0.5, n_try=48, smooth_m=0.10, claps=None, refine_steps=0,
            polish_max_posts=POLISH_MAX_POSTS, angle_jitter=0.15):
    """Turn a profile into posts. Returns (posts ndarray[N, 3] (x, y, radius), stats dict).

    stats: n_posts, by_radius, requested_mass, realized_mass, dropped (posts), shadow_violations, min_gap_m,
    profile_rel_err (relative L2 error of the realized vs requested profile, both smoothed over smooth_m),
    weights (radius -> strength), realized_profile (per bin, in reference-post units), refine_* (the range polish:
    skipped, and logged in refine_skipped, when there are more than polish_max_posts posts).
    Angles: golden-ratio sequence plus seeded Gaussian jitter (angle_jitter, as a fraction of the wedge width) per
    candidate, so the layout is irregular (no lateral lattice) yet deterministic per seed.
    """
    scene = scene_cfg if scene_cfg is not None else Scene()
    rng = np.random.default_rng(seed)
    p = np.clip(np.asarray(profile, dtype=float), 0.0, None)
    n = len(p)
    w = radius_weights(radii, a_ref, band, scene.c)
    order = [a for a in sorted(radii) if a >= a_ref - 1e-12]  # a_ref first, then larger ones only when needed
    half = scene.half_angle_deg
    th_max = math.radians(half) - 1e-6

    # Continuous cumulative mass: bin i spans [rho_i - dr/2, rho_i + dr/2].
    edges = r0 + (np.arange(n + 1) - 0.5) * dr
    M = np.concatenate([[0.0], np.cumsum(p)])
    total = M[-1]

    # Local demand (reference posts per metre of rho), smoothed, for the radius choice.
    k = max(1, int(round(smooth_m / dr)))
    demand = np.convolve(p, np.ones(k) / k, mode="same") / dr

    def pick_radius(rho):
        i = min(n - 1, max(0, int(round((rho - r0) / dr))))
        area_per_m = _arc_len(rho, half) * PACKING
        for a in order:
            cap = area_per_m / (2 * a + gap) ** 2  # posts of radius a per metre of rho
            if demand[i] / w[a] <= cap:
                return a
        return order[-1]

    # Phase A: ranges and radii by error diffusion on the continuous cumulative mass.
    rhos, rads = [], []
    m_next = 0.0
    while True:
        rho_guess = float(np.interp(min(m_next, total), M, edges))
        a = pick_radius(rho_guess)
        m_mid = m_next + 0.5 * w[a]
        if m_mid > total:
            break
        rhos.append(float(np.interp(m_mid, M, edges)))
        rads.append(a)
        m_next += w[a]
    rhos, rads = np.asarray(rhos), np.asarray(rads)
    refine_db = None
    refine_skipped = None
    dropped = 0
    work = len(rhos) * _polish_bins(r0 + n * dr, band, scene.c)
    if refine_steps and len(rhos) > polish_max_posts:
        refine_skipped = f"{len(rhos)} posts > polish_max_posts={polish_max_posts}"
    elif refine_steps and work > POLISH_MAX_WORK:
        refine_skipped = f"posts x in-band bins = {work:.3g} > POLISH_MAX_WORK={POLISH_MAX_WORK:.3g}"
    elif refine_steps and len(rhos):
        rhos, refine_db = refine_ranges(rhos, rads, p, scene, r0=r0, dr=dr, a_ref=a_ref, band=band,
                                        claps=claps, steps=refine_steps)
        keep = rhos >= r0 - dr / 2
        dropped += int(np.sum(~keep))  # polished below the first bin edge: removed
        rhos, rads = rhos[keep], rads[keep]
        o = np.argsort(rhos)
        rhos, rads = rhos[o], rads[o]

    # Phase C: angular placement along each equal-delay ellipse.
    placed_rho, placed = [], []  # sorted by rho
    shadow_viol = 0
    g = rng.random()
    a_max = max(radii)
    for rho, a in zip(rhos, rads):
        rho, a = float(rho), float(a)
        u = (g + GOLDEN * np.arange(1, n_try + 1) + angle_jitter * rng.standard_normal(n_try)) % 1.0
        th = (2.0 * u - 1.0) * th_max
        xy = ellipse_point(rho, th, scene.source, scene.listener)
        ok_w = in_wedge(xy, half, rho_min=r0 - dr, source=scene.source, listener=scene.listener)
        # neighbours: rho is 1-Lipschitz, so gap conflicts lie within rho - (a + a_max + gap). "Nearer" (shadowing)
        # is measured in rho, the placement order, consistently with the window.
        j0 = bisect.bisect_left(placed_rho, rho - max(shadow_depth, a + a_max + gap))
        nb = np.asarray(placed[j0:]) if j0 < len(placed) else np.zeros((0, 3))
        rho_nb = np.asarray(placed_rho[j0:])
        if len(nb):
            d = np.linalg.norm(xy[:, None, :] - nb[None, :, :2], axis=-1) - nb[None, :, 2] - a
            ok_gap = np.all(d >= gap, axis=1)
            v = nb[:, :2] - scene.source
            r_nb = np.hypot(v[:, 0], v[:, 1])
            th_nb = np.arctan2(v[:, 1], v[:, 0])
            xv = xy - scene.source
            r_c = np.hypot(xv[:, 0], xv[:, 1])
            th_c = np.arctan2(xv[:, 1], xv[:, 0])
            nearer = ((rho_nb < rho) & (rho_nb >= rho - shadow_depth))[None, :]
            need = nb[None, :, 2] / r_nb[None, :] + a / r_c[:, None]
            ok_sh = ~np.any(nearer & (np.abs(th_c[:, None] - th_nb[None, :]) < need), axis=1)
        else:
            ok_gap = np.ones(n_try, bool)
            ok_sh = np.ones(n_try, bool)
        good = ok_w & ok_gap & ok_sh
        fallback = ok_w & ok_gap
        if good.any():
            c = int(np.argmax(good))
        elif fallback.any():
            c = int(np.argmax(fallback))
            shadow_viol += 1
        else:
            dropped += 1
            g = (g + GOLDEN * n_try) % 1.0
            continue
        g = u[c]
        placed_rho.append(rho)
        placed.append([xy[c, 0], xy[c, 1], a])

    posts = np.asarray(placed, dtype=float).reshape(-1, 3)
    # realized profile on the bin grid (linear split between the two nearest bin centres)
    real = np.zeros(n)
    if len(posts):
        rr = bistatic_range(posts[:, :2], scene.source, scene.listener)
        x = (rr - r0) / dr
        i0 = np.clip(np.floor(x).astype(int), 0, n - 1)
        fr = np.clip(x - i0, 0, 1)
        wt = np.array([w[float(a)] for a in posts[:, 2]])
        np.add.at(real, i0, wt * (1 - fr))
        np.add.at(real, np.clip(i0 + 1, 0, n - 1), wt * fr)
    ks = np.ones(k) / k
    ps, rs = np.convolve(p, ks, "same"), np.convolve(real, ks, "same")
    from echo.scene import check_gaps

    stats = {
        "n_posts": int(len(posts)),
        "by_radius": {f"{a:.2f}": int(np.sum(np.isclose(posts[:, 2], a))) for a in radii},
        "weights": {f"{a:.2f}": w[a] for a in radii},
        "requested_mass": float(total),
        "realized_mass": float(real.sum()),
        "dropped": int(dropped),
        "shadow_violations": int(shadow_viol),
        "shadow_depth_m": float(shadow_depth),
        "min_gap_m": float(check_gaps(posts)),
        "profile_rel_err": float(np.linalg.norm(rs - ps) / (np.linalg.norm(ps) + 1e-30)),
        "realized_profile": real,
        "refine_steps": int(refine_steps),
        "refine_transfer_err_db": refine_db,
        "refine_skipped": refine_skipped,
    }
    return posts, stats


def refine_ranges(rhos, rads, profile, scene: Scene, *, r0, dr=DR_PROFILE, a_ref=0.02, band=BAND, claps=None,
                  steps=100, lr=5e-4, n_fft=None, chunk=2048):
    """Polish post ranges so the posts' Tier 0 transfer matches the profile's transfer in band.

    Minimizes sum_f W(f) |H_posts(f) - H_profile(f)|^2 / sum_f W(f) |H_profile(f)|^2 (2D, posts on the wedge axis,
    which differs from their final off-axis placement by < -80 dB), W = family-mean clap power spectrum. This is a
    realization-fidelity objective against the solved profile (not against the target). n_fft defaults to
    tier0.choose_n_fft over the largest delay (no time aliasing). The gradient is exact and chunked over posts
    (dL/dH is fixed by the residual), so memory is bounded by `chunk` posts. Returns (rhos, (err_db before,
    err_db after)), both on that non-aliased grid.
    """
    import torch

    from echo.tier0 import choose_n_fft, post_transfer, profile_transfer

    s, l = scene.source, scene.listener
    if not (np.allclose(s, 0) and np.isclose(l[0], 0)):
        raise NotImplementedError("refine_ranges assumes S = (0,0) and L on the y axis")
    d2 = float(l[1] ** 2)
    n_rho = len(profile)
    max_delay = 2 * (max(r0 + (n_rho - 1) * dr, float(np.max(rhos))) + 0.05) / float(scene.c)
    n_clap = 128 if claps is None else np.atleast_2d(claps).shape[-1]
    if n_fft is None:
        n_fft = choose_n_fft(int(np.ceil(max_delay * 16000)), max_delay, n_clap)
    cl = np.atleast_2d(np.asarray(claps)) if claps is not None else None
    W = (torch.as_tensor(np.mean(np.abs(np.fft.rfft(cl, n_fft, axis=-1)) ** 2, axis=0)) if cl is not None
         else torch.ones(n_fft // 2 + 1, dtype=torch.float64))
    sc0 = Scene(source=s, listener=l, c=scene.c)
    Hp = profile_transfer(torch.as_tensor(profile), sc0, n_fft=n_fft, a_ref=a_ref, r0=r0, dr=dr, band=band).detach()
    den = float((W * Hp.abs() ** 2).sum())
    rho = torch.tensor(np.asarray(rhos, dtype=float))
    rad = torch.as_tensor(np.asarray(rads, dtype=float))
    N = len(rho)

    def transfer(r, a):
        x = (4 * r**2 - d2) / (4 * r)  # on-axis point of the ellipse |P-S| + |P-L| = 2 rho
        return post_transfer(torch.stack([x, torch.zeros_like(x), a], 1), sc0, n_fft=n_fft, band=band)

    rho.requires_grad_(True)
    opt = torch.optim.Adam([rho], lr=lr)
    best = (np.inf, rho.detach().clone())
    first = None
    for _ in range(steps + 1):
        with torch.no_grad():
            H = sum(transfer(rho[i:i + chunk], rad[i:i + chunk]) for i in range(0, N, chunk))
        R = H - Hp
        lv = float((W * R.abs() ** 2).sum() / den)
        first = lv if first is None else first
        if lv < best[0]:
            best = (lv, rho.detach().clone())
        opt.zero_grad()
        G = (2 * W / den) * R  # dL/dH* : L = sum W |R|^2 / den, dL = 2 Re(sum W conj(R) dH) / den
        for i in range(0, N, chunk):
            Hc = transfer(rho[i:i + chunk], rad[i:i + chunk])
            (G.conj() * Hc).real.sum().backward()
        opt.step()
    return best[1].numpy(), (10 * math.log10(first), 10 * math.log10(best[0]))
