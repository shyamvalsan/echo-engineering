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


def _arc_len(rho, half_angle_deg):
    return 2.0 * math.radians(half_angle_deg) * rho


def realize(profile, scene_cfg: Scene | None = None, seed=0, *, r0, dr=DR_PROFILE, a_ref=0.02, radii=RADII,
            band=BAND, gap=MIN_GAP, shadow_depth=0.5, n_try=48, smooth_m=0.10):
    """Turn a profile into posts. Returns (posts ndarray[N, 3] (x, y, radius), stats dict).

    stats: n_posts, by_radius, requested_mass, realized_mass, dropped (posts), shadow_violations, min_gap_m,
    profile_rel_err (relative L2 error of the realized vs requested profile, both smoothed over smooth_m),
    weights (radius -> strength), realized_profile (per bin, in reference-post units).
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

    placed_rho, placed = [], []  # sorted by rho (posts are produced in increasing rho)
    shadow_viol = dropped = 0
    g = rng.random()
    m_next = 0.0
    a_max = max(radii)
    while True:
        rho_guess = float(np.interp(min(m_next, total), M, edges))
        a = pick_radius(rho_guess)
        wa = w[a]
        m_mid = m_next + 0.5 * wa
        if m_mid > total:
            break
        rho = float(np.interp(m_mid, M, edges))
        m_next += wa
        u = (g + GOLDEN * np.arange(1, n_try + 1)) % 1.0
        th = (2.0 * u - 1.0) * th_max
        xy = ellipse_point(rho, th, scene.source, scene.listener)
        ok_w = in_wedge(xy, half, rho_min=r0 - dr, source=scene.source, listener=scene.listener)
        # neighbours: rho is 1-Lipschitz, so gap conflicts lie within rho - (a + a_max + gap)
        j0 = bisect.bisect_left(placed_rho, rho - max(shadow_depth, a + a_max + gap))
        nb = np.asarray(placed[j0:]) if j0 < len(placed) else np.zeros((0, 3))
        if len(nb):
            d = np.linalg.norm(xy[:, None, :] - nb[None, :, :2], axis=-1) - nb[None, :, 2] - a
            ok_gap = np.all(d >= gap, axis=1)
            v = nb[:, :2] - scene.source
            r_nb = np.hypot(v[:, 0], v[:, 1])
            th_nb = np.arctan2(v[:, 1], v[:, 0])
            xv = xy - scene.source
            r_c = np.hypot(xv[:, 0], xv[:, 1])
            th_c = np.arctan2(xv[:, 1], xv[:, 0])
            nearer = (r_nb[None, :] < r_c[:, None]) & (r_nb[None, :] >= r_c[:, None] - shadow_depth)
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
    }
    return posts, stats
