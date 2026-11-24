"""Build packs and the generated block of BUILD.md.

  uv run python -m stages.build_pack runs/s1_bird/<run_id>          # one pack -> build/<stage>-<run_id>/
  uv run python -m stages.build_pack --all                          # every final / tier0_only run in runs/index.json
  uv run python -m stages.build_pack --refresh-doc                  # --all, then rewrite BUILD.md's generated block
Options: --post-height 2.0 --embed 0.6 --panel 600x400 --paper A3 --out build --no-physics
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from echo.buildkit import ROOT, build_pack

BEGIN = "<!-- BEGIN GENERATED: stages/build_pack.py --refresh-doc. Do not edit by hand. -->"
END = "<!-- END GENERATED -->"
DOC_STATUSES = ("final", "tier0_only")


def index_runs(runs_root=None):
    root = Path(runs_root or ROOT / "runs")
    idx = json.loads((root / "index.json").read_text())
    return [(r, root / r["path"]) for r in idx.get("runs", []) if r.get("status") in DOC_STATUSES]


def _f(v, fmt="{:.1f}", none="-"):
    return none if v is None else fmt.format(v)


def _j(j, ids):
    """Judge values for the metric ids that have thresholds, e.g. 'pitch_err_pct 2.56, spec_corr 0.959'."""
    if not j:
        return "-"
    return ", ".join(f"{k} {j[k]:.3g}" for k in ids if k in j) or "-"


def _passes(j, thr):
    """True if every thresholded judge in j passes; None if no judge values."""
    if not j:
        return None
    ok = True
    for k, (t, cmp) in thr.items():
        if k not in j:
            continue
        v = j[k]
        ok &= (v <= t) if cmp == "<=" else (v >= t) if cmp == ">=" else (v == t)
    return bool(ok)


def readout(ph, met, thr) -> list[str]:
    """Plain-language bullets evaluated from the tables (so the prose never carries a hand-typed sim number)."""
    hl = met.get("headline", {})
    out = []
    spl = hl.get("echo_spl_db")
    if spl is not None:
        out.append(f"Loudness: echo peak {spl:.1f} dB SPL for a 100 dB clap; margin over the spec's 35 dB line "
                   f"{spl - 35:+.1f} dB; over a 30 / 40 / 50 dB(A) background {spl - 30:+.0f} / {spl - 40:+.0f} / "
                   f"{spl - 50:+.0f} dB (peak against background level: an optimistic comparison).")
    base = _passes(ph.get("judges_inf"), thr)
    out.append(f"Design as drawn on Tier 0 3D, free space: judges {'pass' if base else 'FAIL'}.")
    rad = [j for j in ph["jitter"] if j["kind"] == "radial"]
    okr = [j["sigma_mm"] for j in rad if _passes(j.get("judges"), thr)]
    out.append("Radial placement: " + (f"judges still pass at sigma = {max(okr):g} mm" if okr else
               f"judges FAIL already at the smallest sigma tried ({min(j['sigma_mm'] for j in rad):g} mm)")
               + "; failing sigmas: " + (", ".join(f"{j['sigma_mm']:g} mm" for j in rad
                                                  if _passes(j.get("judges"), thr) is False) or "none") + ".")
    tg = [j for j in ph["jitter"] if j["kind"] == "tangential"]
    for j in tg:
        out.append(f"Tangential placement (along the equal-delay curve), sigma {j['sigma_mm']:g} mm: judges "
                   f"{'pass' if _passes(j.get('judges'), thr) else 'FAIL'}.")
    okh = [h["post_height_m"] for h in ph["height_free"] if h["post_height_m"] is not None
           and _passes(h.get("judges"), thr) and h["delta_db"] > -1.0]
    out.append("Post height, free space, ear 1.5 m: " + (f"shortest height within 1 dB of infinite posts with judges "
               f"passing: {min(okh):g} m." if okh else "no finite height tried keeps the judges passing within 1 dB."))
    for ze in sorted({g["ear_height_m"] for g in ph["height_rigid_ground"]}, reverse=True):
        rows = [g for g in ph["height_rigid_ground"] if g["ear_height_m"] == ze]
        ok = [g for g in rows if _passes(g.get("judges"), thr)]
        out.append(f"Rigid ground, clap and ear at {ze:g} m: judges pass for {len(ok)} of {len(rows)} post heights"
                   + (f" (shortest {min((g['post_height_m'] or 1e9) for g in ok):g} m)" if ok else "")
                   + f"; level change {min(g['delta_db'] for g in rows):+.1f} to {max(g['delta_db'] for g in rows):+.1f} dB, "
                   f"worst 10 ms window {min(g['worst_10ms_delta_db'] for g in rows):+.1f} dB.")
    oks = [x["half_angle_deg"] for x in ph["slices"] if _passes(x.get("judges"), thr) and x["half_angle_deg"]
           < max(y["half_angle_deg"] for y in ph["slices"])]
    out.append("Partial wedge: " + (f"judges still pass down to +-{min(oks):g} deg." if oks else
                                    "every narrower slice tried FAILS the judges (the arcs are not separable)."))
    tj = ph.get("temperature_judged", [])
    bad = [t["T_c"] for t in tj if _passes(t.get("judges"), thr) is False]
    out.append("Temperature: judges " + ("pass at every temperature tried." if not bad else
               f"FAIL at {', '.join(f'{t:g} C' for t in bad)} (design tuned for c = 343 m/s, 20 C)."))
    return out


def _rel(p):
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def robustness_text(met):
    rob = met.get("robustness") or []
    if not rob:
        return "not run"
    parts = []
    for r in rob:
        d = ", ".join(f"{k} {v:+.2f}" for k, v in (r.get("delta") or {}).items() if isinstance(v, (int, float)))
        parts.append(f"{r.get('case')}: {'pass' if r.get('pass') else 'FAIL'}" + (f" ({d})" if d else ""))
    return "; ".join(parts)


def generated_block(packs) -> str:
    """packs: list of (index_row, run_dir, pack_dir). Markdown between the markers."""
    L = [BEGIN, "", "#### Runs found in `runs/index.json` (status final or tier0_only)", "",
         "| stage | run | verified | posts | depth (m) | fill | echo dB re direct | echo dB SPL peak | gating metrics "
         "| robustness (delta per case) | source |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row, rd, pd in packs:
        met = json.loads((rd / "metrics.json").read_text())
        hl = met.get("headline", {})
        ver = bool(met.get("verified"))
        tag = "**yes, Tier 1**" if ver else "no (unverified, Tier 0)"
        ms = [m for m in met.get("metrics", []) if m.get("threshold") is not None and (m.get("gating") or not ver)]
        mtxt = "; ".join(f"{m['id']} {m['value']:.3g} ({m['tier']}, thr {m['comparator']} {m['threshold']}, "
                         f"{'pass' if m['pass'] else 'fail'})" for m in ms)
        L.append(f"| {row['stage']} | {row['run_id']} | {tag} | {hl.get('post_count')} | {_f(hl.get('depth_m'), '{:.2f}')} "
                 f"| {_f(100 * hl['fill_fraction'] if hl.get('fill_fraction') is not None else None, '{:.2f} %')} "
                 f"| {_f(hl.get('echo_level_db_re_direct'))} | {_f(hl.get('echo_spl_db'))} | {mtxt} | "
                 f"{robustness_text(met)} | `{_rel(rd / 'metrics.json')}` |")
    for row, rd, pd in packs:
        pk = json.loads((pd / "pack.json").read_text())
        ph = pk.get("physics")
        met = json.loads((rd / "metrics.json").read_text())
        ids = [m["id"] for m in met.get("metrics", []) if m.get("threshold") is not None]
        ids = list(dict.fromkeys(ids))
        thr = {m["id"]: (m["threshold"], m["comparator"]) for m in met.get("metrics", [])
               if m.get("threshold") is not None}
        if not ph:
            continue
        ver = "Tier 0, unverified" if not ph["verified"] else "Tier 0 3D (design verified on Tier 1; these tables are Tier 0)"
        L += ["", f"#### Build physics for {row['stage']} / {row['run_id']} ({ver})", "",
              f"Source: `{_rel(pd / 'pack.json')}` key `physics`, computed by `echo.buildkit.physics_tables` from "
              f"`{_rel(rd / 'scene.json')}`. Levels are the clap-family mean echo peak in dB re the free-field direct "
              f"clap at the listener (add 110.5 for dB SPL with a 100 dB clap at 1 m). Infinite free-space posts: "
              f"{ph['level_inf_db']:.1f} dB. Target band {ph['target_band_hz'][0]:.0f}-{ph['target_band_hz'][1]:.0f} Hz, "
              f"echo from {ph['timing']['t_first_echo_ms']:.1f} to {ph['timing']['t_last_echo_ms']:.1f} ms.", "",
              f"Stage judges on the Tier 0 3D echo of the design as drawn: {_j(ph.get('judges_inf'), ids)}.", "",
              "**Readout** (evaluated by code from the tables below against the stage thresholds in metrics.json):", ""]
        L += [f"- {b}" for b in readout(ph, met, thr)]
        L += ["",
              "Echo level against post height, free space (no ground), clap and ear at 1.5 m:", "",
              "| post height (m) | level (dB) | change (dB) | judges |", "|---|---|---|---|"]
        for hf in ph["height_free"]:
            h = hf["post_height_m"]
            L.append(f"| {'infinite' if h is None else f'{h:g}'} | {hf['level_db']:.1f} | {hf['delta_db']:+.1f} | "
                     f"{_j(hf.get('judges'), ids)} |")
        L += ["", "Echo level with a perfectly rigid flat ground (image method; posts stand on the ground, clap and ear "
              "at the same height):", "", "| ear height (m) | post height (m) | level (dB) | change (dB) | "
              "worst / best 10 ms window (dB) | judges |", "|---|---|---|---|---|---|"]
        for g in ph["height_rigid_ground"]:
            h = g["post_height_m"]
            L.append(f"| {g['ear_height_m']:g} | {'infinite' if h is None else f'{h:g}'} | {g['level_db']:.1f} | "
                     f"{g['delta_db']:+.1f} | {g['worst_10ms_delta_db']:+.1f} / {g['best_10ms_delta_db']:+.1f} | "
                     f"{_j(g.get('judges'), ids)} |")
        L += ["", "(in brackets: change against infinite free-space posts; 'worst 10 ms': the largest drop of any 10 ms "
              "window of the echo against the same window with infinite free-space posts, which shows comb notches "
              "that the peak hides)", "", "Building only part of the wedge (posts with |bearing| up to the half-angle):",
              "", "| half-angle (deg) | posts | level (dB) | change (dB) | judges |", "|---|---|---|---|---|"]
        for s in ph["slices"]:
            L.append(f"| {s['half_angle_deg']:g} | {s['posts']} | {_f(s['level_db'])} | {_f(s['delta_db'], '{:+.1f}')} | "
                     f"{_j(s.get('judges'), ids)} |")
        L += ["", "Random placement error (Gaussian, every post, seed 0), free-space infinite posts:", "",
              "| direction | sigma (mm) | level change (dB) | waveform correlation with the nominal echo | judges |",
              "|---|---|---|---|---|"]
        for j in ph["jitter"]:
            L.append(f"| {j['kind']} | {j['sigma_mm']:g} | {j['level_delta_db']:+.2f} | {j['waveform_corr']:.3f} | "
                     f"{_j(j.get('judges'), ids)} |")
        L += ["", "The built structure heard at other air temperatures (Tier 0 3D with c(T) = 331.3 sqrt(1 + T/273.15)):",
              "", "| T (C) | c (m/s) | level (dB) | judges |", "|---|---|---|---|"]
        for t in ph.get("temperature_judged", []):
            L.append(f"| {t['T_c']:g} | {t['c']:.1f} | {t['level_db']:.1f} | {_j(t.get('judges'), ids)} |")
        rg = ph["range_gradient"]
        L += ["", f"Range gradient |grad rho| over the posts: {rg['min']:.4f}-{rg['max']:.4f} (a radial error becomes "
              f"that fraction of range error). A sideways error perpendicular to the line from the clap point (a "
              f"bearing error) becomes range error at up to {rg.get('bearing_to_range_max', float('nan')):.3f} of its "
              f"size (median {rg.get('bearing_to_range_median', float('nan')):.3f}), largest on the near rows. "
              f"Range period at {ph['range_period_m']['f_hz']:.0f} Hz: "
              f"{100 * ph['range_period_m']['period_m']:.2f} cm.", "",
              "First Fresnel zone half-height sqrt(lambda rho / 2) at the target band edges:", "",
              "| f (Hz) | rho (m) | half-height (m) |", "|---|---|---|"]
        for z in ph["fresnel"]:
            L.append(f"| {z['f_hz']:.0f} | {z['rho_m']:.2f} | {z['half_height_m']:.2f} |")
        L += ["", "1:10 model air absorption (ISO 9613-1, 20 C, 50 % RH) along the round trip 2 rho:", "",
              "| model f (kHz) | full-scale rho (m) | model path (m) | model loss (dB) | full-scale loss at f/10 (dB) "
              "| excess (dB) |", "|---|---|---|---|---|---|"]
        for a in ph["scale_absorption"]:
            L.append(f"| {a['f_model_hz'] / 1000:g} | {a['rho_full_m']:.2f} | {a['path_model_m']:.2f} | "
                     f"{a['model_db']:.2f} | {a['full_db']:.2f} | {a['excess_db']:.2f} |")
        L += ["", "Viscous boundary layer sqrt(2 nu / omega) against the smallest post radius: " + "; ".join(
            f"{b['case']} at {b['f_hz'] / 1000:g} kHz: {1e6 * b['delta_m']:.0f} um, {100 * b['delta_over_radius']:.2f} % "
            f"of {1000 * b['radius_m']:g} mm" for b in ph["boundary_layer"]) + ".", "",
              "Temperature (pitch of the whole echo scales with c): " + "; ".join(
                  f"{t['T_c']} C: c = {t['c']:.1f} m/s, {t['pitch_shift_pct']:+.1f} %" for t in ph["temperature"]) + "."]
        b = json.loads((pd / "bom.json").read_text())
        tm = pk["template"]
        L += ["", f"Build pack: `{_rel(pd)}/` (stakeout.csv, plan at 1:{pk['plan']['scale']} on {pk['plan']['paper']}, "
              f"1:10 template in {tm['n_panels']} panels of {tm['panel_mm'][0]:.0f} x {tm['panel_mm'][1]:.0f} mm, "
              f"full-size deck/template sheets: {pk['template_full']['n_panels']} of "
              f"{pk['template_full']['panel_mm'][0]:.0f} x {pk['template_full']['panel_mm'][1]:.0f} mm, "
              f"bom.md). BOM at {b['post_height_m']} m posts: " + "; ".join(
                  f"{f['count']} posts of {f['diameter_mm']} mm, {f['total_length_m']:.0f} m of stock"
                  for f in b["full_scale"]) + "; model: " + "; ".join(
                  f"{m['count']} pins of {m['diameter_mm']:g} mm x {m['pin_length_mm']:.0f} mm "
                  f"({m['total_length_m']:.0f} m of rod)" for m in b["model"]) + "."]
    L += ["", END]
    return "\n".join(L)


def refresh_doc(doc: Path, block: str):
    text = doc.read_text()
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < 0 or j < i:
        raise SystemExit(f"{doc}: generated-block markers not found")
    doc.write_text(text[:i] + block + text[j + len(END):])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build packs from run folders; refresh BUILD.md's generated block.")
    ap.add_argument("run_dirs", nargs="*", help="run folders (runs/<stage>/<run_id>)")
    ap.add_argument("--all", action="store_true", help="every final/tier0_only run in runs/index.json")
    ap.add_argument("--refresh-doc", action="store_true", help="--all, then rewrite the generated block of BUILD.md")
    ap.add_argument("--doc", default=str(ROOT / "BUILD.md"))
    ap.add_argument("--out", default=str(ROOT / "build"))
    ap.add_argument("--post-height", type=float, default=2.0)
    ap.add_argument("--embed", type=float, default=0.6)
    ap.add_argument("--panel", default="600x400", help="panel stock size in mm, WxH")
    ap.add_argument("--paper", default="A3", choices=["A3", "A2", "A1", "A0"])
    ap.add_argument("--no-physics", action="store_true", help="skip the Tier 0 physics tables (faster)")
    a = ap.parse_args(argv)
    pw, ph = (float(v) for v in a.panel.lower().split("x"))
    kw = dict(out_root=a.out, post_height=a.post_height, embed=a.embed, panel=(pw, ph), paper=a.paper,
              physics=not a.no_physics)
    if a.all or a.refresh_doc:
        packs = []
        for row, rd in index_runs():
            pd = build_pack(rd, **kw)
            print(f"wrote {pd}")
            packs.append((row, rd, pd))
        if a.refresh_doc:
            refresh_doc(Path(a.doc), generated_block(packs))
            print(f"refreshed {a.doc}")
    for rd in a.run_dirs:
        print(f"wrote {build_pack(rd, **kw)}")
    if not (a.run_dirs or a.all or a.refresh_doc):
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
