"""Stage 1 diagnostic: decompose the Tier 1 - Tier 0 difference of a run folder (same posts) into
(a) a coherent time stretch (range-proportional extra delay: effective-medium slowing by the post field, or grid
dispersion), (b) a coherent linear filter (33-tap Wiener fit after the stretch), and (c) the incoherent residue, and
find the Tier 0 radial jitter sigma whose residue (against unjittered Tier 0, after the same fit) matches (c).

    uv run python -m stages.s1_tierdiff runs/s1_bird/<run_id> [...]   # writes runs/s1_bird/tier_diff.json (by run)

Uses clap 0 (the exported echo_tier0.wav / echo_tier1.wav). Diagnostic only: nothing is chosen from it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from scipy.interpolate import CubicSpline

from echo import export
from echo.clap import clap_family
from echo.inverse import clap_band
from echo.scene import FS, Scene
from echo.tier0 import post_echo
from stages.s1_study import radial_jitter

R0 = 3.06
SIGMAS = (0.001, 0.002, 0.003, 0.004, 0.006)


def _fit(x_full, y, n0, n1):
    """Best (eps, tau) with y(t) ~ g x(t (1 + eps) + tau); then residues (dB re y) after gain only, after stretch,
    after stretch + 33-tap FIR."""
    t = np.arange(len(x_full)) / FS
    cs = CubicSpline(t, x_full)
    tt = t[n0:n1]

    def corr(a, b):
        return float(np.dot(a, b) / np.sqrt(np.dot(a, a) * np.dot(b, b)))

    best = (0.0, 0.0, -2.0)
    for eps in np.linspace(-0.006, 0.002, 81):
        for tau in np.linspace(-150e-6, 150e-6, 31):
            c = corr(cs(tt * (1 + eps) + tau), y)
            if c > best[2]:
                best = (eps, tau, c)
    e0, t0_, _ = best
    for eps in np.linspace(e0 - 1e-4, e0 + 1e-4, 11):
        for tau in np.linspace(t0_ - 10e-6, t0_ + 10e-6, 11):
            c = corr(cs(tt * (1 + eps) + tau), y)
            if c > best[2]:
                best = (eps, tau, c)
    eps, tau, c = best
    x = cs(tt * (1 + eps) + tau)
    h = 16
    X = np.stack([np.roll(x, k) for k in range(-h, h + 1)], 1)[h:-h]
    Y = y[h:-h]
    w, *_ = np.linalg.lstsq(X, Y, rcond=None)
    r = Y - X @ w
    c0 = corr(x_full[n0:n1], y)
    return {"stretch_eps": float(eps), "offset_s": float(tau), "corr_raw": c0, "corr_stretched": float(c),
            "residue_db_gain_only": float(10 * np.log10(max(1 - c0 ** 2, 1e-12))),
            "residue_db_stretched": float(10 * np.log10(max(1 - c ** 2, 1e-12))),
            "residue_db_stretched_fir33": float(10 * np.log10(np.dot(r, r) / np.dot(Y, Y)))}


def analyse(run_dir: Path) -> dict:
    sc = json.loads((run_dir / "scene.json").read_text())
    posts = np.asarray(sc["posts"], dtype=float)
    a, _ = sf.read(run_dir / "echo_tier0.wav")
    b, _ = sf.read(run_dir / "echo_tier1.wav")
    n0 = int(round(2 * R0 / sc["c"] * FS))
    n1 = n0 + int(0.080 * FS) + 10
    out = {"run": run_dir.name, "n_posts": int(len(posts)), "tier1_vs_tier0": _fit(a, b[n0:n1], n0, n1)}
    claps = clap_family(5, seed=0)[:1]
    band = clap_band(clap_family(5, seed=0))
    scene = Scene(posts=posts, half_angle_deg=sc["wedge"]["half_angle_deg"])
    e0 = post_echo(posts, torch.as_tensor(claps), scene, mode="2d", n_out=len(a), band=band).numpy()[0]
    jit = []
    for s in SIGMAS:
        rows = []
        for seed in (31, 32):
            pj = radial_jitter(posts, s, seed)
            ej = post_echo(pj, torch.as_tensor(claps), Scene(posts=pj, half_angle_deg=scene.half_angle_deg),
                           mode="2d", n_out=len(a), band=band).numpy()[0]
            rows.append(_fit(e0, ej[n0:n1], n0, n1)["residue_db_stretched_fir33"])
        jit.append({"sigma_m": s, "residue_db_stretched_fir33": float(np.mean(rows))})
    out["tier0_jitter_residue"] = jit
    r = out["tier1_vs_tier0"]["residue_db_stretched_fir33"]
    xs = [j["residue_db_stretched_fir33"] for j in jit]
    out["equivalent_radial_jitter_m"] = float(np.interp(r, xs, SIGMAS)) if xs[0] <= r <= xs[-1] else None
    return out


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    path = export.RUNS / "s1_bird" / "tier_diff.json"
    d = json.loads(path.read_text()) if path.exists() else {
        "what": "Tier 1 - Tier 0 decomposition on the same posts (clap 0): stretch, linear filter, incoherent residue, "
                "and the Tier 0 radial jitter giving the same residue", "selection": "diagnostic only", "rows": []}
    for a in args:
        res = analyse(Path(a))
        d["rows"] = [r for r in d["rows"] if r["run"] != res["run"]] + [res]
        print(json.dumps(res, indent=1))
    path.write_text(json.dumps(d, indent=1))


if __name__ == "__main__":
    main()
