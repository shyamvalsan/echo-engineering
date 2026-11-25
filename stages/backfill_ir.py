"""Add impulse responses (ir_tier0.wav, ir_tier1.wav) and the manifest `ir` block to existing run folders, without
re-running any solve.

    uv run python -m stages.backfill_ir                 # every run folder under runs/ (skips _* and validation)
    uv run python -m stages.backfill_ir --only s1_bird  # one stage
    uv run python -m stages.backfill_ir --dry-run       # report routes and errors, write nothing

Tier 0: recomputed from the posts in scene.json (echo.export.tier0_ir: irfft of echo.tier0.post_transfer in the run
band), seconds per run. Tier 1: the solver cache (.cache/tier1) holds only EMPTY-scene runs (keyed by grid), never a
design's run, so a stored Tier 1 IR cannot be recovered from it; the Tier 1 IR is obtained by regularized in-band
deconvolution of echo_tier1.wav by clap variant 0 (echo.export.deconvolve_ir). Every run records its route and the
reconstruction error (clap 0 (*) ir vs the exported echo, dB). As a check of the deconvolution route on the same run,
the Tier 0 echo is also deconvolved and compared with the directly computed Tier 0 IR (`tier0_deconv_vs_direct_db`).
Only manifest['ir'] is changed (read-modify-write); metrics.json is not touched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from echo import export
from echo.clap import clap_family
from echo.scene import Scene


def true_echo(run_dir, name, gain_db):
    """Exported echo WAV back in model units (the writer applied `gain_db` to peak-normalize it)."""
    x, fs = sf.read(Path(run_dir) / name, dtype="float64")
    assert fs == export.FS, f"{name}: fs {fs}"
    return x * 10 ** (-float(gain_db) / 20.0)


def run_band(man):
    b = (man.get("design") or {}).get("loss_band_hz")
    if b:
        return float(b[0]), float(b[1])
    from echo.inverse import clap_band

    lo, hi = clap_band(clap_family(5, seed=int(man.get("seed") or 0)))
    s = man.get("solver") or {}
    return lo, min(hi, float(s.get("f_max") or hi))


def backfill(run_dir, dry_run=False):
    d = Path(run_dir)
    man = json.loads((d / "manifest.json").read_text())
    band = run_band(man)
    cfg = (man.get("design") or {}).get("config") or {}
    claps = clap_family(int(cfg.get("n_claps", 5)), seed=int(man.get("seed") or 0))
    clap0 = claps[int((man.get("audio") or {}).get("clap_variant", 0))]
    gains = (man.get("audio") or {}).get("echo_gain_db") or {}
    scene = Scene.from_dict(json.loads((d / "scene.json").read_text()))
    e0 = true_echo(d, "echo_tier0.wav", gains["tier0"])
    ir0 = export.tier0_ir(scene, band, len(e0))
    err0 = export.ir_error_db(ir0, clap0, e0)
    ir0_dec, err0_dec = export.deconvolve_ir(e0, clap0, band)
    agree0 = float(10 * np.log10(np.sum((ir0_dec - ir0) ** 2) / np.sum(ir0 ** 2)))
    ir1, src1, err1 = None, None, None
    has_t1 = (man.get("solver") or {}).get("tier1", "none") != "none" and (d / "echo_tier1.wav").exists()
    if has_t1 and gains.get("tier1") is not None:
        e1 = true_echo(d, "echo_tier1.wav", gains["tier1"])
        ir1, err1 = export.deconvolve_ir(e1, clap0, band)
        src1 = export.IR_SRC_T1_DECONV
    row = {"run": f"{d.parent.name}/{d.name}", "band_hz": band, "tier0_route": export.IR_SRC_T0,
           "tier0_reconstruction_error_db": err0, "tier0_deconv_vs_direct_db": agree0,
           "tier0_deconv_reconstruction_error_db": err0_dec, "tier1_route": src1,
           "tier1_reconstruction_error_db": err1}
    if not dry_run:
        export.write_ir(d, ir0, band, ir1, src1, extra={"check": {
            "tier0_reconstruction_error_db": err0, "tier1_reconstruction_error_db": err1,
            "tier0_deconv_vs_direct_db": agree0, "deconv_lambda": export.DECONV_LAMBDA,
            "definition": "error_db = 10 log10(|clap_0 (*) ir - echo|^2 / |echo|^2) over the echo file; "
                          "tier0_deconv_vs_direct_db = 10 log10(|ir_deconv - ir_direct|^2 / |ir_direct|^2) for Tier 0",
            "written_by": "stages.backfill_ir"}})
    return row


def run_dirs(runs_root=export.RUNS, only=None):
    for mf in sorted(Path(runs_root).glob("*/*/manifest.json")):
        st, rd = mf.parent.parent.name, mf.parent.name
        if st.startswith("_") or rd.startswith("_") or st in export.EXPORT_DIRS_SKIPPED:
            continue
        if only and st not in only:
            continue
        yield mf.parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="*", help="stage folders to process")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="also redo runs whose IR was stored at run time")
    a = ap.parse_args(argv)
    rows = []
    for d in run_dirs(only=a.only):
        man = json.loads((d / "manifest.json").read_text())
        if not a.force and ((man.get("ir") or {}).get("source") or {}).get("tier1") == export.IR_SRC_T1_STORED:
            print(f"{d.parent.name}/{d.name}: IR stored at run time, skipped")
            continue
        r = backfill(d, a.dry_run)
        rows.append(r)
        e1 = "-" if r["tier1_reconstruction_error_db"] is None else f"{r['tier1_reconstruction_error_db']:.1f}"
        print(f"{r['run']:<45} band {r['band_hz'][0]:.0f}-{r['band_hz'][1]:.0f}  T0 err "
              f"{r['tier0_reconstruction_error_db']:.1f} dB  T0 deconv vs direct {r['tier0_deconv_vs_direct_db']:.1f} dB"
              f"  T1 {r['tier1_route'] and 'deconv'} err {e1} dB", flush=True)
    return rows


if __name__ == "__main__":
    main()
