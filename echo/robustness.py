"""Robustness sweep of a final design (spec, "Scoring and verification"), generic over stages.

Cases (every one is scored with the stage's own metrics on Tier 1, mean over the clap family unless it is a single
clap case; Tier 0 values are reported alongside):

- ``listener_side_1m`` / ``listener_back_1m``: the listener moved 1 m sideways (+y, across the wedge axis) and 1 m
  back (-x, away from the structure). Extra sensors in the same Tier 1 run as the nominal design (free). The
  evaluation window is shifted by the geometric change of the echo delay of the structure's mid-range point on the
  axis, (|P_mid - L'| - |P_mid - L|) / c, because a listener hears the echo relative to when it arrives; the
  remaining spread of the delay change across the structure is part of what the case measures.
- ``c_331`` / ``c_349``: speed of sound 331 and 349 m/s (0 C and 30 C), one Tier 1 rerun each (each needs its own
  empty-scene run, cached). The window starts at 2 r0 / c. Pitch scales with c: the expected shift from c alone,
  (c / 343 - 1) * 100 %, is reported next to the measured median shift; that part is physics, not design error.
- ``jitter``: every post centre moved by independent UNIFORM offsets in [-5, +5] mm on x and on y, every radius
  by a UNIFORM offset in [-1, +1] mm, seeded (``JITTER_SEED_OFFSET`` + stage seed). One Tier 1 rerun.
- ``clap_<k>``: each clap variant on its own (free: per-clap values of the nominal Tier 1 run).

Every case carries its metric values, the delta from the nominal values, and pass/fail on the stage's gating
thresholds (``echo.metrics.THRESHOLDS``; nothing here changes a threshold or a judge).
"""

from __future__ import annotations

import numpy as np

from echo import metrics as M
from echo.scene import C0, FS, Scene

LISTENER_OFFSETS = {"listener_side_1m": ((0.0, 1.0), "Listener moved 1 m sideways"),
                    "listener_back_1m": ((-1.0, 0.0), "Listener moved 1 m back")}
C_CASES = (331.0, 349.0)
POS_JITTER_M = 0.005  # half-width of the uniform per-axis position jitter
RAD_JITTER_M = 0.001  # half-width of the uniform radius jitter
JITTER_SEED_OFFSET = 1000


def robustness_listeners(scene: Scene) -> np.ndarray:
    """Sensor set for every Tier 1 run of a stage: [nominal listener, +1 m sideways, 1 m back] ([3, 2]). Using the
    same set in every run keeps the empty-scene cache shared."""
    L = np.asarray(scene.listener, dtype=float)
    return np.array([L] + [L + np.asarray(o) for o, _ in LISTENER_OFFSETS.values()])


def jitter_posts(posts, seed, pos=POS_JITTER_M, rad=RAD_JITTER_M):
    """Posts with uniform per-axis position jitter in [-pos, pos] and radius jitter in [-rad, rad]. Deterministic
    per seed (numpy default_rng(seed + JITTER_SEED_OFFSET))."""
    p = np.array(posts, dtype=float).reshape(-1, 3)
    rng = np.random.default_rng(int(seed) + JITTER_SEED_OFFSET)
    p[:, :2] += rng.uniform(-pos, pos, size=(len(p), 2))
    p[:, 2] += rng.uniform(-rad, rad, size=len(p))
    return p


def listener_shift_s(scene: Scene, listener_new, rho_mid, c=C0):
    """Echo-delay change at a moved listener for the on-axis point at bistatic range rho_mid."""
    from echo.scene import ellipse_point

    P = ellipse_point(rho_mid, 0.0, scene.source, scene.listener)
    return float((np.linalg.norm(P - np.asarray(listener_new)) - np.linalg.norm(P - scene.listener)) / c)


def _gating_pass(stage, per_clap, tier="tier1"):
    ent = M.aggregate(stage, per_clap, tier, True)
    g = [e for e in ent if e["gating"]]
    return bool(g) and all(bool(e["pass"]) for e in g), {e["id"]: e["value"] for e in ent}


def _mean(per_clap):
    return {k: M._clean(np.mean([pc[k] for pc in per_clap])) for k in per_clap[0]}


def _delta(vals, nominal):
    return {k: (None if vals.get(k) is None or nominal.get(k) is None else M._clean(vals[k] - nominal[k]))
            for k in nominal}


def signed_pitch_shift_pct(segs, target, fs=FS, edge_s=0.012):
    """Median over interior frames and claps of (f_est / f_target - 1) * 100 (reporting only; None if the target
    has no pitch track)."""
    if getattr(target, "f_track", None) is None:
        return None
    tt, ff = target.f_track
    out = []
    for s in np.atleast_2d(segs):
        t, f0, _ = M.pitch_track(s, fs, f_range=(np.min(ff), np.max(ff)))
        dur = tt[-1] + (tt[1] - tt[0])
        m = (t >= edge_s) & (t <= dur - edge_s)
        out.append(f0[m] / np.interp(t[m], tt, ff) - 1.0)
    return float(np.median(np.concatenate(out)) * 100.0)


def case(stage, name, label, per_clap_t1, nominal, per_clap_t0=None, **info):
    ok, _ = _gating_pass(stage, per_clap_t1)
    vals = _mean(per_clap_t1)
    out = {"case": name, "label": label, "metrics": vals, "delta": _delta(vals, nominal), "pass": ok}
    if per_clap_t0 is not None:
        out["metrics_tier0"] = _mean(per_clap_t0)
    out.update(info)
    return out


def robust_summary(cases) -> str:
    """Three-state reading of the robustness cases next to the spec's boolean `fragile` (same counts as fragile_rule):
    "fails everywhere" (no clap variant and no listener position passes), "fragile" (fragile_rule is true), "robust"
    (otherwise: more than one clap variant and more than one listener position pass), "partial" (none of the above,
    e.g. passes at one listener position for no clap)."""
    by = {c["case"]: c for c in cases}
    n_clap = sum(bool(c["pass"]) for c in cases if c["case"].startswith("clap_"))
    n_lis = sum(bool(by[p]["pass"]) for p in ["nominal"] + list(LISTENER_OFFSETS) if p in by)
    if n_clap == 0 and n_lis == 0:
        return "fails everywhere"
    if fragile_rule(cases)[0]:
        return "fragile"
    return "robust" if n_clap > 1 and n_lis > 1 else "partial"


def fragile_rule(cases) -> tuple[bool, str]:
    """`fragile` (spec: "a design that only works for one clap or one listener position is marked fragile").

    Exact rule: let n_clap = number of ``clap_<k>`` cases that pass and n_listener = number of passing listener
    positions among {nominal, listener_side_1m, listener_back_1m} (the nominal position counts as passing when the
    nominal case passes). fragile = (n_clap == 1) or (n_listener == 1). A design that passes for no clap or no
    position is not "fragile" but failing; c, jitter and the per-clap count beyond one are reported, not part of the
    rule.
    """
    by = {c["case"]: c for c in cases}
    claps = [c for c in cases if c["case"].startswith("clap_")]
    n_clap = sum(bool(c["pass"]) for c in claps)
    pos = ["nominal"] + list(LISTENER_OFFSETS)
    n_lis = sum(bool(by[p]["pass"]) for p in pos if p in by)
    fragile = (n_clap == 1) or (n_lis == 1)
    return bool(fragile), (f"{n_clap}/{len(claps)} clap variants pass on their own; {n_lis}/{len(pos)} listener "
                           f"positions pass (nominal, 1 m sideways, 1 m back)")


def sweep(stage, target, claps, band, scene: Scene, t_echo0, r0, nominal_t1, *, run_t1, echoes, tier0_echo, seed,
          rho_mid, log=print):
    """Run the whole sweep for a final design. Returns (cases list, fragile bool, fragile_reason, timings dict).

    nominal_t1: the final design's Tier 1 result with sensors `robustness_listeners(scene)`.
    run_t1(scene, c) -> Tier1Result with the same sensors; echoes(result, claps, listener) -> [K, n] (band-limited
    by this function); tier0_echo(scene) -> [K, n] Tier 0 2D echo, band-limited.
    """
    import time

    from echo.clap import band_limit

    n = len(target.audio)
    tim = {}

    def vals(e, t0):
        return M.stage_values(stage, e, target, t0, FS, band)

    def e1(res, li=0):
        return band_limit(echoes(res, claps, li), band[0], band[1])

    nom_e1 = e1(nominal_t1, 0)
    pc_nom = vals(nom_e1, t_echo0)
    nominal = _mean(pc_nom)
    pc0_nom = vals(tier0_echo(scene), t_echo0)
    cases = [case(stage, "nominal", "Nominal design", pc_nom, nominal, pc0_nom)]

    for li, (name, (off, label)) in enumerate(LISTENER_OFFSETS.items(), start=1):
        Ln = nominal_t1.listeners[li]
        sh = listener_shift_s(scene, Ln, rho_mid, scene.c)
        sc_l = Scene(source=scene.source, listener=Ln, posts=scene.posts, half_angle_deg=scene.half_angle_deg,
                     r_min=scene.r_min, c=scene.c)
        cases.append(case(stage, name, label, vals(e1(nominal_t1, li), t_echo0 + sh), nominal,
                          vals(tier0_echo(sc_l), t_echo0 + sh), listener=[float(v) for v in Ln],
                          window_shift_ms=sh * 1e3))

    for c in C_CASES:
        t = time.time()
        sc_c = Scene(source=scene.source, listener=scene.listener, posts=scene.posts,
                     half_angle_deg=scene.half_angle_deg, r_min=scene.r_min, c=c)
        res = run_t1(sc_c, c)
        tim[f"c_{c:.0f}"] = time.time() - t
        t0c = 2.0 * r0 / c
        ec = e1(res, 0)
        segs = M.echo_segment(ec, t0c, n)
        cases.append(case(stage, f"c_{c:.0f}", f"Speed of sound {c:.0f} m/s", vals(ec, t0c), nominal,
                          vals(tier0_echo(sc_c), t0c), c=c,
                          pitch_shift_expected_pct=(c / C0 - 1.0) * 100.0,
                          pitch_shift_measured_pct=signed_pitch_shift_pct(segs, target),
                          pitch_shift_nominal_pct=signed_pitch_shift_pct(M.echo_segment(nom_e1, t_echo0, n), target),
                          tier1_wall_s=res.wall_s, empty_cached=bool(res.extra.get("empty_cached"))))
        log(f"robustness c={c:.0f}: {cases[-1]['metrics']} pass {cases[-1]['pass']} ({tim[f'c_{c:.0f}']:.0f} s)")

    t = time.time()
    pj = jitter_posts(scene.posts, seed)
    sc_j = Scene(source=scene.source, listener=scene.listener, posts=pj, half_angle_deg=scene.half_angle_deg,
                 r_min=scene.r_min, c=scene.c)
    res = run_t1(sc_j, scene.c)
    tim["jitter"] = time.time() - t
    d = pj - np.asarray(scene.posts)
    cases.append(case(stage, "jitter", "Posts jittered 5 mm, radii 1 mm (uniform)", vals(e1(res, 0), t_echo0), nominal,
                      vals(tier0_echo(sc_j), t_echo0),
                      jitter={"distribution": "uniform", "pos_half_width_m": POS_JITTER_M,
                              "rad_half_width_m": RAD_JITTER_M, "seed": int(seed) + JITTER_SEED_OFFSET,
                              "max_abs_dxy_m": float(np.abs(d[:, :2]).max()) if len(d) else 0.0,
                              "max_abs_dr_m": float(np.abs(d[:, 2]).max()) if len(d) else 0.0,
                              "min_gap_m": float(_min_gap(pj))},
                      tier1_wall_s=res.wall_s))
    log(f"robustness jitter: {cases[-1]['metrics']} pass {cases[-1]['pass']} ({tim['jitter']:.0f} s)")

    for k, pc in enumerate(pc_nom):
        cases.append(case(stage, f"clap_{k}", f"Clap variant {k} alone", [pc], nominal, [pc0_nom[k]]))
    fr, why = fragile_rule(cases)
    return cases, fr, why, tim


def _min_gap(posts):
    from echo.scene import check_gaps

    return check_gaps(posts)
