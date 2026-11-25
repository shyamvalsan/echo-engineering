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


def _fl(floor, k):
    return f" [floor {floor[k]:.3g}]" if floor and k in floor else ""


def _j(j, ids, floor=None):
    """Judge values for the thresholded ids, each with the judge floor: 'pitch_err_pct 2.84 [floor 2.53]'."""
    if not j:
        return "not judged"
    return ", ".join(f"{k} {j[k]:.3g}{_fl(floor, k)}" for k in ids if k in j) or "not judged"


def _jstats(js, ids, floor=None):
    """Multi-seed judge stats {id: {mean,min,max}} -> 'spec_corr 0.77 (0.76-0.78) [floor 0.976]'."""
    if not js:
        return "not judged"
    return ", ".join(f"{k} {js[k]['mean']:.3g} ({js[k]['min']:.3g}-{js[k]['max']:.3g}){_fl(floor, k)}" for k in ids
                     if js.get(k)) or "not judged"


def gate_margins(floor, thr) -> list[str]:
    """Explicit pass / inconclusive / fail bands per judged gate, from the threshold and the judge floor.

    m = |threshold - floor| (how far a perfect echo sits from the threshold). PASS: on the pass side of the threshold.
    INCONCLUSIVE (repeat, average more, listen): on the fail side by less than m. FAIL: on the fail side by more than m."""
    out = []
    for k, (t, cmp) in thr.items():
        if not floor or k not in floor or cmp not in ("<=", ">="):
            continue
        m = abs(t - floor[k])
        if cmp == "<=":
            out.append(f"{k}: PASS <= {t:g}; INCONCLUSIVE {t:g} to {t + m:.3g}; FAIL > {t + m:.3g} (floor {floor[k]:.3g})")
        else:
            out.append(f"{k}: PASS >= {t:g}; INCONCLUSIVE {t - m:.3g} to {t:g}; FAIL < {t - m:.3g} (floor {floor[k]:.3g})")
    return out


def snr_gate(ex, thr, margin_db=6.0):
    """Lowest SNR in the table at which every seed's judges pass (seed minimum/maximum), plus margin_db."""
    tab = ex.get("snr_table") or []
    ok = []
    for row in sorted(tab, key=lambda r: r["snr_db"]):
        js = row["judges"] or {}
        good = bool(js)
        for k, (t, cmp) in thr.items():
            st = js.get(k)
            if not st:
                continue
            good &= (st["max"] <= t) if cmp == "<=" else (st["min"] >= t) if cmp == ">=" else True
        ok.append((row["snr_db"], good))
    # the lowest SNR from which every higher SNR also passes
    first = None
    for snr, good in reversed(ok):
        if good:
            first = snr
        else:
            break
    return None if first is None else {"snr_pass_db": first, "margin_db": margin_db, "gate_db": first + margin_db}


def _means(js):
    return {k: v["mean"] for k, v in js.items() if v} if js else None


def _verdict(j, thr):
    """('pass' | 'fail' | 'not judged', [failing ids]) for a {id: value} dict against {id: (threshold, cmp)}."""
    if not j or not any(k in j for k in thr):
        return "not judged", []
    bad = []
    for k, (t, cmp) in thr.items():
        if k not in j:
            continue
        v = j[k]
        ok = (v <= t) if cmp == "<=" else (v >= t) if cmp == ">=" else (v == t)
        if not ok:
            bad.append(k)
    return ("fail" if bad else "pass"), bad


def _passes(j, thr):
    """True / False, or None when not judged (never read None as a fail)."""
    v, _ = _verdict(j, thr)
    return None if v == "not judged" else v == "pass"


def _floor_txt(ph, thr):
    f = ph.get("judges_floor")
    if not f:
        return "judge floor not available"
    return "judge floor (the same judges on a physically perfect echo): " + ", ".join(
        f"{k} {f[k]:.3g} (single claps {f.get(k + '__clap_min', f[k]):.3g}-{f.get(k + '__clap_max', f[k]):.3g}; "
        f"threshold {thr[k][1]} {thr[k][0]:g})" for k in thr if k in f)


def radial_budget(rows, thr):
    """(largest sigma with every sigma up to it passing, first failing row, list of not-judged sigmas).

    Pass/fail uses the seed-mean judge values. A pass above a failure does not extend the budget."""
    rad = sorted((r for r in rows if r["kind"] == "radial"), key=lambda r: r["sigma_mm"])
    budget, first_fail, unjudged = None, None, []
    for r in rad:
        v, _ = _verdict(_means(r.get("judges")), thr)
        if v == "not judged":
            unjudged.append(r["sigma_mm"])
            if first_fail is None:
                break
            continue
        if v == "fail":
            first_fail = first_fail or r
            break
        budget = r["sigma_mm"]
    return budget, first_fail, unjudged


def readout(ph, met, thr, labels=None) -> list[str]:
    """Plain-language bullets evaluated from the tables (so the prose never carries a hand-typed sim number).

    "not judged" is printed (with the reason) wherever judge values are missing; it is never read as a fail."""
    labels = labels or {}
    hl = met.get("headline", {})
    out = []
    why = ph.get("judge_status", "ok")
    nj = f"not judged ({why})" if why != "ok" else "not judged (judge error on this echo)"

    def vtxt(j):
        v, bad = _verdict(j, thr)
        if v == "not judged":
            return nj
        return "pass" if v == "pass" else "FAIL on " + ", ".join(f"{labels.get(k, k)} [{k}]" for k in bad)

    spl = hl.get("echo_spl_db")
    if spl is not None:
        out.append(f"Loudness: echo peak {spl:.1f} dB SPL for a 100 dB clap; margin over the spec's 35 dB line "
                   f"{spl - 35:+.1f} dB; over a 30 / 40 / 50 dB(A) background {spl - 30:+.0f} / {spl - 40:+.0f} / "
                   f"{spl - 50:+.0f} dB (peak against background level: an optimistic comparison).")
    out.append(f"Design as drawn on Tier 0 3D, free space: {vtxt(ph.get('judges_inf'))}. " + _floor_txt(ph, thr) + ".")
    rows = ph.get("jitter", [])
    budget, ff, unj = radial_budget(rows, thr)
    seeds = rows[0]["seeds"] if rows else []
    if ff is None and budget is None:
        out.append(f"Radial placement: {nj}.")
    else:
        t = "Radial placement (seed-mean of " + str(len(seeds)) + " seeds): "
        t += (f"the spec's judges pass for every sigma up to {budget:g} mm" if budget is not None else
              "the spec's judges fail already at the smallest sigma tried")
        if ff is not None:
            _, bad = _verdict(_means(ff["judges"]), thr)
            wc = ff["waveform_corr"]
            t += (f"; first failure at {ff['sigma_mm']:g} mm on " + ", ".join(
                f"{labels.get(k, k)} [{k}] {ff['judges'][k]['mean']:.3g} ({ff['judges'][k]['min']:.3g}-"
                f"{ff['judges'][k]['max']:.3g})" for k in bad)
                + f", while the echo waveform is still {wc['mean']:.3f} correlated with the nominal echo and its level "
                f"changes {ff['level_delta_db']['mean']:+.2f} dB")
            t += "; where the residual lands is in the residual split below"
        else:
            t += "; no failure among the sigmas tried"
        if unj:
            t += f"; not judged at {', '.join(f'{x:g}' for x in unj)} mm ({why})"
        out.append(t + ". Whether that judge failure is audible is a listening question (pack `listening/`).")
    for j in [r for r in rows if r["kind"] == "tangential"]:
        out.append(f"Tangential placement (along the equal-delay curve), sigma {j['sigma_mm']:g} mm: "
                   f"{vtxt(_means(j.get('judges')))}; waveform correlation {j['waveform_corr']['mean']:.3f}.")
    hf = ph.get("height_free", [])
    okh = [h["post_height_m"] for h in hf if h["post_height_m"] is not None
           and _passes(h.get("judges"), thr) and h["delta_db"] > -1.0]
    if all(_passes(h.get("judges"), thr) is None for h in hf):
        out.append(f"Post height, free space, ear 1.5 m: {nj}.")
    else:
        out.append("Post height, free space, ear 1.5 m: " + (
            f"shortest height within 1 dB of infinite posts with judges passing: {min(okh):g} m." if okh else
            "no finite height tried both passes the judges and stays within 1 dB of infinite posts."))
    for ze in sorted({g["ear_height_m"] for g in ph.get("height_rigid_ground", [])}, reverse=True):
        rs = [g for g in ph["height_rigid_ground"] if g["ear_height_m"] == ze]
        lv = (f"level change {min(g['delta_db'] for g in rs):+.1f} to {max(g['delta_db'] for g in rs):+.1f} dB, "
              f"worst 10 ms window {min(g['worst_10ms_delta_db'] for g in rs):+.1f} dB")
        judged = [g for g in rs if _passes(g.get("judges"), thr) is not None]
        if not judged:
            out.append(f"Rigid ground, clap and ear at {ze:g} m: {nj}; {lv}.")
            continue
        ok = [g for g in judged if _passes(g.get("judges"), thr)]
        out.append(f"Rigid ground, clap and ear at {ze:g} m: judges pass for {len(ok)} of {len(judged)} judged post "
                   f"heights" + (f" (shortest {min((g['post_height_m'] or 1e9) for g in ok):g} m)" if ok else "")
                   + f"; {lv}.")
    sl = [x for x in ph.get("slices", []) if x["half_angle_deg"] < max(y["half_angle_deg"] for y in ph["slices"])]
    vs = [(x["half_angle_deg"], _passes(x.get("judges"), thr)) for x in sl]
    if sl and all(v is None for _, v in vs):
        out.append(f"Partial wedge: {nj}.")
    elif sl:
        ok = [a for a, v in vs if v]
        bad = [a for a, v in vs if v is False]
        out.append("Partial wedge: " + (f"judges pass at +-{', +-'.join(f'{a:g}' for a in ok)} deg" if ok else
                                        "no narrower slice tried passes the judges")
                   + (f"; fail at +-{', +-'.join(f'{a:g}' for a in bad)} deg" if bad else "") + ".")
    tj = ph.get("temperature_judged", [])
    if tj:
        parts = [f"{t['T_c']:g} C: {vtxt(t.get('judges'))}" for t in tj]
        out.append("Temperature (design tuned for c = 343 m/s): " + "; ".join(parts) + ".")
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


def generated_block(packs, lowpitch=None) -> str:
    """packs: list of (index_row, run_dir, pack_dir); lowpitch: lowpitch_tolerance() result or None."""
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
        fl = ph.get("judges_floor")
        ver = "Tier 0, unverified" if not ph["verified"] else "Tier 0 3D (design verified on Tier 1; these tables are Tier 0)"
        L += ["", f"#### Build physics for {row['stage']} / {row['run_id']} ({ver})", "",
              f"Source: `{_rel(pd / 'pack.json')}` key `physics`, computed by `echo.buildkit.physics_tables` from "
              f"`{_rel(rd / 'scene.json')}`. Levels are the clap-family mean echo peak in dB re the free-field direct "
              f"clap at the listener (add 110.5 for dB SPL with a 100 dB clap at 1 m). Infinite free-space posts: "
              f"{ph['level_inf_db']:.1f} dB. Target band {ph['target_band_hz'][0]:.0f}-{ph['target_band_hz'][1]:.0f} Hz, "
              f"echo from {ph['timing']['t_first_echo_ms']:.1f} to {ph['timing']['t_last_echo_ms']:.1f} ms.", "",
              f"Stage judges on the Tier 0 3D echo of the design as drawn: {_j(ph.get('judges_inf'), ids, fl)}. "
              f"{_floor_txt(ph, thr)}. Every judged row below should be read against this floor, not against a "
              f"perfect score." + ("" if ph.get("judge_status", "ok") == "ok" else
                                   f" Judges unavailable: {ph.get('judge_status')}."), "",
              "**Readout** (evaluated by code from the tables below against the stage thresholds in metrics.json):", ""]
        labels = {m["id"]: m.get("label", m["id"]) for m in met.get("metrics", [])}
        L += [f"- {b}" for b in readout(ph, met, thr, labels)]
        gm = ph.get("geometry")
        if gm:
            L += ["", "Design geometry for the build: bistatic range "
                  f"{gm['rho_min_m']:.2f}-{gm['rho_max_m']:.2f} m; longest round trip {gm['round_trip_max_m']:.1f} m; "
                  f"far edge {gm['far_edge_from_S_m']:.2f} m from the clap point. 1:10 model: far edge "
                  f"{gm['model_far_edge_m']:.2f} m from the emitter, keep hard surfaces beyond "
                  f"{gm['model_clearance_m']:.2f} m; time gate {gm['gate_model_ms'][0]:.2f}-{gm['gate_model_ms'][1]:.2f} ms "
                  f"model time ({gm['gate_full_ms'][0]:.1f}-{gm['gate_full_ms'][1]:.1f} ms full scale: first echo - 3 ms "
                  f"to last echo + 10 ms). Site: a hard reflector at distance d from the clap point echoes at about "
                  f"2d/c, so keep hard reflectors beyond c (last echo + 10 ms) / 2 = "
                  f"{343.0 * (ph['timing']['t_last_echo_ms'] + 10.0) / 2000:.1f} m, so their echoes land after the "
                  f"analysis window. Board: see the template extent in the build pack line below."]
        if ph.get("rig_levels"):
            L += ["", "Field-test (phase 3a) echo levels, Tier 0 3D, free space, ear 1.5 m:", "",
                  "| case | post height | dB re direct | dB SPL peak (100 dB clap) |", "|---|---|---|---|"]
            for r in ph["rig_levels"]:
                h = r["post_height_m"]
                L.append(f"| {r['case']} | {'infinite' if h is None else f'{h:g} m'} | {r['level_db']:.1f} | "
                         f"{110.46 + r['level_db']:.1f} |")
        L += ["",
              "Echo level against post height, free space (no ground), clap and ear at 1.5 m:", "",
              "| post height (m) | level (dB) | change (dB) | judges |", "|---|---|---|---|"]
        for hf in ph["height_free"]:
            h = hf["post_height_m"]
            L.append(f"| {'infinite' if h is None else f'{h:g}'} | {hf['level_db']:.1f} | {hf['delta_db']:+.1f} | "
                     f"{_j(hf.get('judges'), ids, fl)} |")
        L += ["", "Echo level with a perfectly rigid flat ground (image method; posts stand on the ground, clap and ear "
              "at the same height):", "", "| ear height (m) | post height (m) | level (dB) | change (dB) | "
              "worst / best 10 ms window (dB) | judges |", "|---|---|---|---|---|---|"]
        for g in ph["height_rigid_ground"]:
            h = g["post_height_m"]
            L.append(f"| {g['ear_height_m']:g} | {'infinite' if h is None else f'{h:g}'} | {g['level_db']:.1f} | "
                     f"{g['delta_db']:+.1f} | {g['worst_10ms_delta_db']:+.1f} / {g['best_10ms_delta_db']:+.1f} | "
                     f"{_j(g.get('judges'), ids, fl)} |")
        L += ["", "(in brackets: change against infinite free-space posts; 'worst 10 ms': the largest drop of any 10 ms "
              "window of the echo against the same window with infinite free-space posts, which shows comb notches "
              "that the peak hides)", "", "Building only part of the wedge (posts with |bearing| up to the half-angle):",
              "", "| half-angle (deg) | posts | level (dB) | change (dB) | judges |", "|---|---|---|---|---|"]
        for s in ph["slices"]:
            L.append(f"| {s['half_angle_deg']:g} | {s['posts']} | {_f(s['level_db'])} | {_f(s['delta_db'], '{:+.1f}')} | "
                     f"{_j(s.get('judges'), ids, fl)} |")
        L += jitter_lines(ph["jitter"], ids, ph.get("jitter_f_center_hz"), fl)
        exf = pd / "extras.json"
        ex = json.loads(exf.read_text()) if exf.exists() else None
        if ex:
            L += residual_lines(ex, "Residual split, this design")
        L += measurement_lines(ph, ex, thr, fl, ids, b_height=json.loads((pd / "bom.json").read_text())["post_height_m"])
        L += ["", "The built structure heard at other air temperatures (Tier 0 3D with c(T) = 331.3 sqrt(1 + T/273.15)):",
              "", "| T (C) | c (m/s) | level (dB) | judges |", "|---|---|---|---|"]
        for t in ph.get("temperature_judged", []):
            L.append(f"| {t['T_c']:g} | {t['c']:.1f} | {t['level_db']:.1f} | {_j(t.get('judges'), ids, fl)} |")
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
                  f"{m['count']} pins of {m['diameter_mm']:g} mm, " + " or ".join(
                      f"{o['pin_length_mm']:.0f} mm long ({k}, {o['total_length_m']:.0f} m of rod)"
                      for k, o in m["options"].items()) for m in b["model"]) + f". 1:10 hole field extent "
              f"{(tm['extent_mm'][1] - min(0, tm['extent_mm'][0])) / 1000:.2f} m x "
              f"{(tm['extent_mm'][3] - tm['extent_mm'][2]) / 1000:.2f} m (from the emitter mark)."]
    if lowpitch and packs:
        row, rd, pd = packs[0]
        met = json.loads((rd / "metrics.json").read_text())
        ph = json.loads((pd / "pack.json").read_text()).get("physics")
        thr = {m["id"]: (m["threshold"], m["comparator"]) for m in met.get("metrics", [])
               if m.get("threshold") is not None}
        exf = pd / "extras.json"
        if ph is not None and exf.exists():
            ph["_extras"] = json.loads(exf.read_text())
        if ph and row["stage"] == "s1_bird":
            labels = {m["id"]: m.get("label", m["id"]) for m in met.get("metrics", [])}
            L += lowpitch_lines(lowpitch, ph, thr, list(dict.fromkeys(thr)), labels)
    L += ["", END]
    return "\n".join(L)


def jitter_lines(rows, ids, f_center, floor=None):
    import math

    seeds = rows[0]["seeds"] if rows else []
    L = ["", f"Random placement error (Gaussian, every post, {len(seeds)} seeds per sigma: mean and range), free-space "
         "infinite posts. Judge view: the spec's judges (with the judge floor). Physical view: measured waveform "
         "correlation with the nominal echo (clap-family mean of per-clap correlations), next to the parameter-free "
         f"coherent-loss factor A = exp(-(4 pi sigma f / c)^2 / 2) at f = {f_center or float('nan'):.0f} Hz (the "
         "fraction of coherent amplitude kept in the target band; it says nothing about where the lost power goes):", "",
         "| direction | sigma (mm) | level change (dB) | waveform corr, measured | coherent factor A | judges (mean, range) |",
         "|---|---|---|---|---|---|"]
    for j in rows:
        if j["kind"] == "nominal":
            continue
        wc = j["waveform_corr"]
        A = math.exp(-((4 * math.pi * j["sigma_mm"] / 1000 * (f_center or 0) / 343.0) ** 2) / 2)
        L.append(f"| {j['kind']} | {j['sigma_mm']:g} | {j['level_delta_db']['mean']:+.2f} | {wc['mean']:.3f} "
                 f"({wc['min']:.3f}-{wc['max']:.3f}) | {A:.3f} | {_jstats(j.get('judges'), ids, floor)} |")
    return L


def measurement_lines(ph, ex, thr, fl, ids, b_height=2.0):
    """SNR table and gate, gate margins, phase-2b measurement height, phase-3a SNR estimate (all generated)."""
    L = []
    gate = None
    if ex and ex.get("snr_table"):
        w = ex["snr_window_s"]
        L += ["", f"Measurement noise: the judges on the nominal echo plus in-band white noise (band-limited to the "
              f"design loss band), SNR = echo energy / noise energy over {1000 * w[0]:.1f}-{1000 * w[1]:.1f} ms, "
              f"{ex.get('snr_seeds_n', 3)} seeds:", "",
              "| SNR (dB) | judges (mean, seed range) |", "|---|---|"]
        for r in ex["snr_table"]:
            L.append(f"| {r['snr_db']:g} | {_jstats(r['judges'], ids, fl)} |")
        gate = snr_gate(ex, thr)
        if gate:
            L += ["", f"**SNR gate**: every seed passes from {gate['snr_pass_db']:g} dB up; with a {gate['margin_db']:g} dB "
                  f"margin the measurement must reach **{gate['gate_db']:g} dB in-band SNR** over the echo window."]
        else:
            L += ["", "**SNR gate**: no SNR in the table passes on every seed; measure at the highest SNR achievable."]
    gm = gate_margins(fl, thr)
    if gm:
        L += ["", "**Gate margins** (every judged gate; m = distance of the judge floor from the threshold): " + "; ".join(gm)
              + ". Inconclusive: repeat with more averaging and decide by listening."]
    ok = [g for g in ph.get("height_rigid_ground", []) if g["post_height_m"] == b_height
          and _passes(g.get("judges"), thr)]
    if ok:
        z = max(g["ear_height_m"] for g in ok)
        L += ["", f"**Phase-2b measurement height**: emitter and mic {1000 * z / 10:.0f} mm above the model ground plane "
              f"(= {z:g} m at full scale), the highest clap/ear height whose rigid-ground row with {b_height:g} m posts "
              f"passes the judges; passing heights: " + ", ".join(
                  f"{g['ear_height_m']:g} m" for g in sorted(ok, key=lambda g: g["ear_height_m"]))
              + ". Also measure at 150 mm (1.5 m) as the ground-model check; its predicted verdict is in the ground table."]
    elif ph.get("height_rigid_ground"):
        L += ["", f"**Phase-2b measurement height**: no rigid-ground row with {b_height:g} m posts passes the judges "
              "(or none is judged); measure at every tabulated height and compare with the table."]
    if ph.get("rig_levels") and gate:
        import math

        L += ["", f"Phase-3a SNR estimate (single hit of a 100 dB clap; peak echo SPL against a background level, an "
              f"optimistic comparison; hits to average for the {gate['gate_db']:g} dB gate = 10^((gate - SNR1)/10)):", "",
              "| case | post height | echo peak dB SPL | background 25 dB: SNR1 / hits | 35 dB | 45 dB |",
              "|---|---|---|---|---|---|"]
        for r in ph["rig_levels"]:
            spl = 110.46 + r["level_db"]
            cells = []
            for bg in (25.0, 35.0, 45.0):
                s1 = spl - bg
                n = max(1, math.ceil(10 ** ((gate["gate_db"] - s1) / 10)))
                cells.append(f"{s1:.0f} dB / {n}")
            h = r["post_height_m"]
            L.append(f"| {r['case']} | {'infinite' if h is None else f'{h:g} m'} | {spl:.1f} | " + " | ".join(cells) + " |")
    return L


def residual_lines(ex, title):
    """Like-for-like residual split (per clap, then clap-family mean over seeds) and its reconciliation."""
    import numpy as np

    lo, hi = ex["f_band_hz"]
    L = ["", f"{title}: jitter-induced residual r = jittered echo - g x nominal (common gain g removed), energy split "
         f"into fixed bands below the target band (< {lo:.0f} Hz), the target band ({lo:.0f}-{hi:.0f} Hz) and above it "
         f"({hi:.0f}-{ex['f_top_hz']:.0f} Hz), as % of the nominal echo energy; clap-family mean of per-clap values, "
         f"mean over {len(ex['seeds'])} seeds. Check: residual/jittered energy equals 1 - corr^2 per clap.", "",
         "| sigma (mm) | corr (clap mean) | residual below | in target band | above, to 4 kHz | above, worst clap "
         "| max abs(1 - corr^2 - residual/jittered) |", "|---|---|---|---|---|---|---|"]
    for row in ex["residual"]:
        cl = [c for seed in row["per_seed_per_clap"] for c in seed]
        rb = np.array([c["res_bands"] for c in cl])
        nc = len(row["per_seed_per_clap"][0])
        worst = max(np.mean([seed[k]["res_bands"][2] for seed in row["per_seed_per_clap"]]) for k in range(nc))
        chk = max(abs(c["one_minus_corr2"] - c["res_over_e"]) for c in cl)
        L.append(f"| {row['sigma_mm']:g} | {np.mean([c['corr'] for c in cl]):.3f} | {100 * rb[:, 0].mean():.2f} % | "
                 f"{100 * rb[:, 1].mean():.2f} % | {100 * rb[:, 2].mean():.2f} % | {100 * worst:.2f} % | {chk:.1e} |")
    nom = ex["nominal_per_clap"]
    L += ["", "Nominal echo, per clap: share of energy in the target band " + ", ".join(
        f"{100 * c['nominal_bands'][1]:.0f} %" for c in nom) + "; above it " + ", ".join(
        f"{100 * c['nominal_bands'][2]:.0f} %" for c in nom) + "; peak level " + ", ".join(
        f"{c['level_db']:.1f}" for c in nom) + " dB re direct (claps 0-4)."]
    bs = ex.get("bias_to_signal")
    if bs:
        L += ["", f"Bias against modulation of the reflectivity profile (profile.json, active span): mean "
              f"{bs['mean']:.4g}, RMS modulation {bs['rms_modulation']:.4g}, amplitude ratio {bs['ratio_amp']:.2f}, "
              f"energy ratio {bs['ratio_energy']:.2f}."]
    return L


def refresh_doc(doc: Path, block: str):
    text = doc.read_text()
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < 0 or j < i:
        raise SystemExit(f"{doc}: generated-block markers not found")
    doc.write_text(text[:i] + block + text[j + len(END):])


LOWPITCH = {"f_start": 1750.0, "f_end": 1000.0, "duration_s": 0.08}
VARIANTS = ROOT / "build" / "variants"


def lowpitch_target():
    from echo.targets import bird_note

    return bird_note(**LOWPITCH)


def make_lowpitch_variant(out_root=VARIANTS, threads=1):
    """Stage-1 pipeline (Tier 0 only) on the bird glide shifted down an octave-ish (1.75 -> 1.0 kHz, 80 ms).

    Written under build/variants/, never runs/. Returns the run folder. Same config as stage 1 otherwise.
    """
    from dataclasses import replace

    from stages.common import run_stage
    from stages.s1_bird import CONFIG

    cfg = replace(CONFIG, title="Bird note shifted down, 1.75 to 1.0 kHz whistle, 80 ms (build variant)",
                  tag="s1low", make_target=lowpitch_target, threads=threads,
                  notes="Build-tolerance variant for BUILD.md (stages/build_pack.py --lowpitch); not a spec stage.")
    run_dir, _, _ = run_stage(cfg, command="uv run python -m stages.build_pack --lowpitch", verbose=False,
                              runs_root=out_root)
    return Path(run_dir)


def latest_variant(root=VARIANTS):
    ds = sorted((root / "s1_bird").glob("*/manifest.json")) if (root / "s1_bird").exists() else []
    return ds[-1].parent if ds else None


def lowpitch_tolerance(variant_dir, seeds=(0, 1, 2), sigmas=(1.0, 2.0, 3.0, 5.0, 10.0, 20.0)) -> dict:
    """Multi-seed placement tolerance of the low-pitch variant (same method as physics_tables), cached as JSON."""
    import math

    from echo.buildkit import Judge, _design_inputs, _echo3d, _level_db, jitter_table, load_run

    import inspect

    from echo.buildkit import cached_json

    params = {"seeds": list(seeds), "sigmas": list(sigmas), "target": LOWPITCH, "dir": _rel(variant_dir)}
    return cached_json(Path(variant_dir) / "tolerance.json", params,
                       lambda: _lowpitch_compute(variant_dir, seeds, sigmas),
                       sources=(inspect.getsource(_lowpitch_compute),))


def _lowpitch_compute(variant_dir, seeds, sigmas):
    import math

    from echo.buildkit import Judge, _design_inputs, _echo3d, _level_db, jitter_table, load_run

    run = load_run(variant_dir)
    claps, band, n_out = _design_inputs(run)
    sc = run["scene"]
    judge = Judge(run, band, target=lowpitch_target())
    ref = _echo3d(sc.posts, sc, claps, band, n_out)
    fc = math.sqrt(LOWPITCH["f_start"] * LOWPITCH["f_end"])
    res = {"run_dir": _rel(variant_dir), "target": LOWPITCH, "posts": int(len(sc.posts)), "depth_m": sc.depth_m,
           "level_inf_db": _level_db(ref), "judges_inf": judge(ref), "judge_status": judge.status,
           "judges_floor": judge(judge.ideal_echo(claps, n_out)) if judge.status == "ok" else None,
           "range_period_m": sc.c / (2 * LOWPITCH["f_start"]), "jitter_f_center_hz": fc,
           "jitter": jitter_table(sc.posts, sc, claps, band, n_out, judge, ref, fc, sigmas, (50.0,), seeds,
                                  tband=(LOWPITCH["f_end"], LOWPITCH["f_start"]))}
    return res


def ensure_extras(run_dir, out_json, f_band=None, target=None):
    """extras.json (residual split, bias ratio, SNR table) next to a pack or variant, cached by code and params."""
    import inspect

    from echo.buildkit import Judge, _design_inputs, cached_json, extra_tables, load_run

    run = load_run(run_dir)

    def compute():
        _, band, _ = _design_inputs(run)
        judge = Judge(run, band, target=target)
        fb = f_band
        if fb is None and judge.target is not None and judge.target.f_track is not None:
            fb = (float(min(judge.target.f_track[1])), float(max(judge.target.f_track[1])))
        d = extra_tables(run, fb, judge)
        d["snr_seeds_n"] = 3
        return d

    return cached_json(out_json, {"run": _rel(run_dir), "f_band": f_band}, compute,
                       sources=(inspect.getsource(ensure_extras),))


def lowpitch_lines(res, main_ph, thr, ids, labels):
    L = ["", f"#### Lower-pitch variant: placement tolerance (Tier 0, unverified, build variant, not a spec stage)", "",
         f"The stage-1 pipeline run on the same glide shifted down to {res['target']['f_start']:.0f} -> "
         f"{res['target']['f_end']:.0f} Hz ({1000 * res['target']['duration_s']:.0f} ms): `{res['run_dir']}/` "
         f"({res['posts']} posts, depth {res['depth_m']:.2f} m, echo {res['level_inf_db']:.1f} dB re direct on Tier 0 "
         f"3D). Judges with the stage-1 thresholds against the shifted target. Range period c/(2 f_top): "
         f"{100 * res['range_period_m']:.1f} cm here against {100 * main_ph['range_period_m']['period_m']:.1f} cm for "
         f"the stage-1 design.", ""]
    ph = {"jitter": res["jitter"], "judges_inf": res["judges_inf"], "judges_floor": res["judges_floor"],
          "judge_status": res["judge_status"]}
    met = {"headline": {}}
    rb = [b for b in readout(ph, met, thr, labels) if b.startswith(("Design as drawn", "Radial", "Tangential"))]
    L += [f"- {b}" for b in rb]
    L += jitter_lines(res["jitter"], ids, res["jitter_f_center_hz"], res.get("judges_floor"))
    if res.get("extras"):
        L += residual_lines(res["extras"], "Residual split, low-pitch variant")
        mex = main_ph.get("_extras")
        if mex and mex.get("bias_to_signal") and res["extras"].get("bias_to_signal"):
            L += ["", f"Bias-to-modulation amplitude ratio: stage-1 design {mex['bias_to_signal']['ratio_amp']:.2f}, "
                  f"low-pitch variant {res['extras']['bias_to_signal']['ratio_amp']:.2f}."]
    return L


def with_variant_extras(vd):
    if vd is None:
        return None
    low = lowpitch_tolerance(vd)
    low["extras"] = ensure_extras(vd, vd / "extras.json", f_band=(LOWPITCH["f_end"], LOWPITCH["f_start"]),
                                  target=lowpitch_target())
    return low


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
    ap.add_argument("--lowpitch", action="store_true",
                    help="(re)build the low-pitch tolerance variant under build/variants/ (Tier 0, ~1-2 min)")
    ap.add_argument("--threads", type=int, default=1, help="torch threads (default 1)")
    ap.add_argument("--doc-only", action="store_true",
                    help="rewrite BUILD.md's block from the existing build packs without recomputing them")
    ap.add_argument("--no-physics", action="store_true", help="skip the Tier 0 physics tables (faster)")
    a = ap.parse_args(argv)
    import torch

    torch.set_num_threads(a.threads)
    pw, ph = (float(v) for v in a.panel.lower().split("x"))
    kw = dict(out_root=a.out, post_height=a.post_height, embed=a.embed, panel=(pw, ph), paper=a.paper,
              physics=not a.no_physics)
    if a.lowpitch:
        print(f"wrote {make_lowpitch_variant(threads=a.threads)}")
    if a.doc_only:
        from echo.buildkit import load_run, pack_name

        packs = [(row, rd, Path(a.out) / pack_name(load_run(rd))) for row, rd in index_runs()]
        for row, rd, pd in packs:
            if (pd / "pack.json").exists():
                ensure_extras(rd, pd / "extras.json")
        vd = latest_variant()
        low = with_variant_extras(vd)
        refresh_doc(Path(a.doc), generated_block([p for p in packs if (p[2] / "pack.json").exists()], low))
        print(f"refreshed {a.doc} (from existing packs)")
        return 0
    if a.all or a.refresh_doc:
        packs = []
        for row, rd in index_runs():
            pd = build_pack(rd, **kw)
            print(f"wrote {pd}")
            packs.append((row, rd, pd))
        if a.refresh_doc:
            for row, rd, pd in packs:
                ensure_extras(rd, pd / "extras.json")
            vd = latest_variant()
            low = with_variant_extras(vd)
            refresh_doc(Path(a.doc), generated_block(packs, low))
            print(f"refreshed {a.doc}")
    for rd in a.run_dirs:
        print(f"wrote {build_pack(rd, **kw)}")
    if not (a.run_dirs or a.all or a.refresh_doc or a.lowpitch):
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
