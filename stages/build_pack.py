"""Build packs and the generated block of BUILD.md.

  uv run python -m stages.build_pack runs/s1_bird/<run_id>          # one pack -> build/<stage>-<run_id>/
  uv run python -m stages.build_pack --all                          # every final / tier0_only run in runs/index.json
  uv run python -m stages.build_pack --refresh-doc                  # --all, then rewrite BUILD.md's generated block
Options: --post-height 2.0 --embed 0.6 --panel 600x400 --paper A3 --out build --no-physics
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from echo.buildkit import ROOT, build_pack

BEGIN = "<!-- BEGIN GENERATED: stages/build_pack.py --refresh-doc. Do not edit by hand. -->"
END = "<!-- END GENERATED -->"
SUMMARY_BEGIN = "<!-- BEGIN GENERATED SUMMARY: stages/build_pack.py --refresh-doc. Do not edit by hand. -->"
SUMMARY_END = "<!-- END GENERATED SUMMARY -->"
DOC_STATUSES = ("final", "tier0_only")


PHYSICS_STAGES = ("s1_bird",)  # spec stages whose latest final run gets a build pack (plus every build_* stage)


def build_candidates(rows):
    """The runs that get a build pack with physics: the newest run of each PHYSICS_STAGES stage and of each build_*
    stage (rows are newest first, as runs/index.json)."""
    seen, out = set(), []
    for row, rd in rows:
        st = row["stage"]
        if (st in PHYSICS_STAGES or st.startswith("build_")) and st not in seen:
            seen.add(st)
            out.append((row, rd))
    return out


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


THERMOMETER_C = 0.5  # stated accuracy of the phase-2/3 thermometer (parts list: +-0.5 C)


def pitch_shift_pct_for_dT(dT=THERMOMETER_C, T=20.0):
    """Pitch error (percentage points) left by a c(T) correction made with a temperature off by dT: c ~ sqrt(T)."""
    return 100 * (math.sqrt((273.15 + T + dT) / (273.15 + T)) - 1)


def measurement_margins(ex, thr, gate) -> dict:
    """Symmetric margins for PHYSICAL-MEASUREMENT gates only (simulation verdicts use the spec thresholds, no margin).

    m = noise repeatability of the judge at the SNR gate (half the seed range of the SNR-table row at the highest
    tabulated SNR not above the gate) + for pitch judges the pitch error left by a c(T) correction with a temperature
    off by the thermometer accuracy. PASS: beats the threshold by more than m; FAIL: misses it by more than m;
    otherwise REPEAT (more averaging, re-measure temperature). Returns {id: {...}}; empty without an SNR gate."""
    if not ex or not gate or not ex.get("snr_table"):
        return {}
    rows = [r for r in ex["snr_table"] if r["snr_db"] <= gate["gate_db"]] or ex["snr_table"][:1]
    row = max(rows, key=lambda r: r["snr_db"])
    out = {}
    for k, (t, cmp) in thr.items():
        st = (row.get("judges") or {}).get(k)
        if not st or cmp not in ("<=", ">="):
            continue
        m_noise = (st["max"] - st["min"]) / 2
        m_temp = pitch_shift_pct_for_dT() if k.startswith("pitch_err") else 0.0
        m = m_noise + m_temp
        out[k] = {"threshold": t, "comparator": cmp, "snr_row_db": row["snr_db"], "m_noise": m_noise,
                  "m_temp": m_temp, "m": m, "n_seeds": st.get("n")}
    return out


def margin_lines(mm) -> list[str]:
    out = []
    for k, d in mm.items():
        t, m = d["threshold"], d["m"]
        lo, hi = (t - m, t + m)
        if d["comparator"] == "<=":
            band = f"PASS < {lo:.3g}; REPEAT {lo:.3g} to {hi:.3g}; FAIL > {hi:.3g}"
        else:
            band = f"PASS > {hi:.3g}; REPEAT {lo:.3g} to {hi:.3g}; FAIL < {lo:.3g}"
        out.append(f"{k} (threshold {d['comparator']} {t:g}): m = {m:.3g} = noise repeatability {d['m_noise']:.3g} "
                   f"(half the seed range at {d['snr_row_db']:g} dB SNR, {d['n_seeds']} seeds)"
                   + (f" + c(T) error {d['m_temp']:.3g} (thermometer +-{THERMOMETER_C:g} C)" if d["m_temp"] else "")
                   + f" -> {band}")
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
    fl = ph.get("judges_floor")
    out.append(f"Design as drawn on Tier 0 3D, free space: {vtxt(ph.get('judges_inf'))} "
               f"({_j(ph.get('judges_inf'), list(thr), fl)}). " + _floor_txt(ph, thr) + ".")
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
                f"{ff['judges'][k]['max']:.3g}){_fl(fl, k)}" for k in bad)
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
                   f"{vtxt(_means(j.get('judges')))} ({_jstats(j.get('judges'), list(thr), fl)}); waveform "
                   f"correlation {j['waveform_corr']['mean']:.3f}.")
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
        parts = [f"{t['T_c']:g} C: {vtxt(t.get('judges'))} ({_j(t.get('judges'), list(thr), fl)})" for t in tj]
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


def _thr(met):
    """{id: (threshold, cmp)} from a metrics.json; falls back to metrics['pilot']['reference_thresholds']."""
    thr = {m["id"]: (m["threshold"], m["comparator"]) for m in met.get("metrics", []) if m.get("threshold") is not None}
    if not thr and (met.get("pilot") or {}).get("reference_thresholds"):
        thr = {k: tuple(v) for k, v in met["pilot"]["reference_thresholds"].items()}
    return thr


def _floor_mean(met):
    return ((met.get("judge_floor") or {}).get("mean")) or {}


def _stage_label(row, met):
    sub = met.get("substage") or met.get("target_name")
    return f"{row['stage']}" + (f" ({sub})" if sub and row["stage"] == "s4_speech" else "")


def gating_text(met):
    """'pitch_err_pct 3.36 (<= 3, fail) [floor 2.53]; ...' for the gating metrics (spec thresholds only)."""
    fl = _floor_mean(met)
    out = []
    for m in met.get("metrics", []):
        if not m.get("gating"):
            continue
        v = m.get("value")
        vt = "none (judge found no value)" if v is None else f"{v:.3g}"
        f = fl.get(m["id"])
        ft = "" if not isinstance(f, (int, float)) or isinstance(f, bool) else f" [floor {f:.3g}]"
        out.append(f"{m['id']} {vt} ({m['comparator']} {m['threshold']:g}, {'pass' if m.get('pass') else 'fail'}){ft}")
    if not out and met.get("pilot"):
        how = ("fast model only, no full-wave verdict" if met["pilot"].get("target_is_stage1_whistle")
               else "reference only")
        for k, d in met["pilot"]["reference_values"].items():
            f = fl.get(k)
            ft = "" if not isinstance(f, (int, float)) else f" [floor {f:.3g}]"
            out.append(f"{k} {_f(d['value'], '{:.3g}')} ({how}: {d['comparator']} {d['threshold']:g}){ft}")
    return "; ".join(out) or "-"


def run_table(index_rows, runs_root=None) -> list[str]:
    """One row per final / tier0_only run: verdict against the spec thresholds only, judge floor beside each value."""
    L = ["| stage | run | full-wave verdict (spec thresholds) | gating values [judge floor] | echo dB SPL, 100 dB clap "
         "(margin over 35 dB) | depth (m) | posts | fill | tier gap (dB) | robustness | source |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row, rd in index_rows:
        met = json.loads((rd / "metrics.json").read_text())
        hl = met.get("headline", {})
        if not met.get("verified"):
            verdict = "not run on the full-wave solver (Tier 0 only)"
        elif met.get("pilot") and not met["pilot"].get("target_is_stage1_whistle"):
            verdict = "no pass mark (pilot; reference thresholds only)"
        else:
            verdict = "**PASSED**" if met.get("passed") else "FAILED"
        spl = hl.get("echo_spl_db")
        L.append(f"| {_stage_label(row, met)} | {row['run_id']} | {verdict} | {gating_text(met)} | "
                 f"{_f(spl)} ({_f(None if spl is None else spl - 35.0, '{:+.1f}')}) | {_f(hl.get('depth_m'))} | "
                 f"{hl.get('post_count')} | {_f(100 * hl['fill_fraction'] if hl.get('fill_fraction') is not None else None, '{:.3f} %')} "
                 f"| {_f(hl.get('tier_gap_db'))} | {met.get('robust_summary') or '-'} | `{_rel(rd / 'metrics.json')}` |")
    return L


def _clap0_level(rd):
    """Clap variant 0's echo level re the clap at the ear (manifest.audio.as_heard_echo_level_db), or None."""
    p = rd / "manifest.json"
    return ((json.loads(p.read_text()).get("audio") or {}).get("as_heard_echo_level_db")) if p.exists() else None


def _study(path):
    p = ROOT / path
    return (json.loads(p.read_text()), path) if p.exists() else (None, path)


def summary_block(index_rows, s1=None, pilot=None) -> str:
    """The one-screen evidence summary at the top of BUILD.md: every number generated, each with its source.

    index_rows: [(row, run_dir)]; s1 / pilot: (row, run_dir, pack_dir) or None."""
    mets = [(row, rd, json.loads((rd / "metrics.json").read_text())) for row, rd in index_rows]
    whistle = [(row, rd) for row, rd, m in mets if row["stage"] == "s1_bird" or row["stage"].startswith("build_")]
    # custom designs have no pass condition (stages.custom): not a stage result, so not listed here
    other = [(row, rd, m) for row, rd, m in mets if (row, rd) not in whistle and row.get("stage") != "custom"]
    L = [SUMMARY_BEGIN, "", "**The ring-layout whistle** (stage-1 design family and the build pilot; every final run, newest "
         "first; the verdict column is the spec's automated pass marks on the full-wave solver, exactly as the files have "
         "them, with the judge floor -- the score of a physically perfect echo -- beside each value):", ""]
    L += run_table(whistle)
    L += ["", "Audio to play (full-wave echo alone, and as heard after the clap at its predicted level): " + "; ".join(
        f"`{_rel(rd / 'echo_tier1.wav')}`, `{_rel(rd / 'as_heard.wav')}`" for row, rd in whistle[:1]
        + [w for w in whistle if w[0]["stage"].startswith("build_")][:1]) + "."]
    newest = {}
    for row, rd in whistle:
        newest.setdefault(row["stage"], (row, rd))
    for row, rd in newest.values():
        if True:
            m = json.loads((rd / "metrics.json").read_text())
            spl = m["headline"].get("echo_spl_db")
            if spl is not None:
                L.append(f"- Level, {row['stage']} {row['run_id']}: echo peak {spl:.1f} dB SPL for a 100 dB clap at 1 m "
                         f"({_f(m['headline'].get('echo_level_db_re_direct'))} dB re the direct clap at the ear, mean over "
                         f"the clap variants; clap variant 0 alone, the value REPORT.md quotes: "
                         f"{_f(_clap0_level(rd))} dB, `manifest.json` `audio.as_heard_echo_level_db`); "
                         f"{spl - 35:+.1f} dB over the spec's 35 dB line; against a quiet rural / suburban / urban-park "
                         f"background of 25 / 35 / 45 dB(A): {spl - 25:+.0f} / {spl - 35:+.0f} / {spl - 45:+.0f} dB "
                         f"(peak against a background level: optimistic). Source `{_rel(rd / 'metrics.json')}` `headline`.")
    L += ["", "**Other stages** (not on the build path; one line each, verdicts exactly as in the files):", ""]
    for row, rd, m in other:
        hl = m.get("headline", {})
        verdict = ("**PASSED**" if m.get("passed") else "FAILED") if m.get("verified") else "not run on Tier 1"
        tn = f' "{m["target_name"]}"' if m.get("target_name") else ""
        L.append(f"- {_stage_label(row, m)}{tn} "
                 f"{row['run_id']}: {verdict}; {gating_text(m)}; {_f(hl.get('depth_m'))} m deep, "
                 f"{hl.get('post_count')} posts, {_f(hl.get('echo_spl_db'))} dB SPL; robustness "
                 f"{m.get('robust_summary') or '-'}. `{_rel(rd / 'metrics.json')}`.")
    L += ["", "**Key numbers for the whistle** (generated; each with its source file):", ""]
    s1runs = [x for x in mets if x[0]["stage"] == "s1_bird" and x[2].get("verified")]
    if s1runs:
        row, rd, m = s1runs[0]
        L.append(f"- Latest stage-1 whistle {row['run_id']} against the automated marks: {gating_text(m)}; listener "
                 f"moved 1 m: " + "; ".join(
                     f"{r['case']} {'pass' if r.get('pass') else 'fail'}" for r in m.get("robustness", [])
                     if r["case"].startswith("listener")) + f". Source `{_rel(rd / 'metrics.json')}`.")
    ss, sp = _study("runs/s1_bird/_studies/design_study_tier0.json")
    if ss and ss.get("sweet_spot"):
        L += ["", f"Listening spot (stage-1 design study, Tier 0, {ss['sweet_spot'][0]['n_posts']} posts; waveform "
              f"correlation of the echo heard at a moved listener against the design listener, delay change removed; "
              f"source `{sp}` key `sweet_spot`):", "",
              "| fan half-angle | 10 cm sideways | 25 cm sideways | 50 cm sideways | 1 m sideways | 50 cm back | 1 m back "
              "| sideways extent with correlation >= 0.95 |", "|---|---|---|---|---|---|---|---|"]
        for ha in sorted({r["half_angle_deg"] for r in ss["sweet_spot"]}, reverse=True):
            rr = {tuple(r["offset_m"]): r["wave_corr_vs_nominal"] for r in ss["sweet_spot"] if r["half_angle_deg"] == ha}
            side = [y for (x, y), v in sorted(rr.items(), key=lambda kv: kv[0][1]) if x == 0.0 and y > 0]
            ext = 0.0
            for y in side:
                if rr[(0.0, y)] >= 0.95:
                    ext = y
                else:
                    break
            g = lambda o: _f(rr.get(o), "{:.2f}")  # noqa: E731
            L.append(f"| +-{ha:g} deg | {g((0.0, 0.1))} | {g((0.0, 0.25))} | {g((0.0, 0.5))} | {g((0.0, 1.0))} | "
                     f"{g((-0.5, 0.0))} | {g((-1.0, 0.0))} | " + (f"< 10 cm" if ext == 0 else f"{100 * ext:.0f} cm")
                     + " |")
        L.append("")
    if s1:
        row, rd, pd = s1
        ph = json.loads((pd / "pack.json").read_text()).get("physics") or {}
        rad = {j["sigma_mm"]: j for j in ph.get("jitter", []) if j["kind"] == "radial"}
        fl = ph.get("judges_floor") or {}
        bits = []
        for sgm in (1.0, 2.0, 5.0):
            j = rad.get(sgm)
            if j and j.get("judges") and j["judges"].get("spec_corr"):
                bits.append(f"{sgm:g} mm: spectrogram correlation {j['judges']['spec_corr']['mean']:.3f} "
                            f"(threshold >= 0.8, floor {_f(fl.get('spec_corr'), '{:.3f}')}), waveform correlation "
                            f"{j['waveform_corr']['mean']:.3f}")
        if bits:
            L.append(f"- Placement error (random, radial, Tier 0, latest stage-1 design {row['run_id']}): " + "; ".join(bits)
                     + f". Hear it: `{_rel(pd / 'listening')}/`. Source `{_rel(pd / 'pack.json')}` key `physics.jitter`.")
        tt = ph.get("temperature") or []
        if tt:
            L.append("- Temperature: the whole echo's pitch scales with the speed of sound: " + ", ".join(
                f"{t['T_c']} C {t['pitch_shift_pct']:+.1f} %" for t in tt) + f" against the 343 m/s design. Source "
                f"`{_rel(pd / 'pack.json')}` key `physics.temperature`.")
    td, tp = _study("runs/s1_bird/_studies/tier_diff.json")
    if td:
        rows = {}
        for r in td["rows"]:
            t1 = r["tier1_vs_tier0"]
            rows[r["run"]] = (r.get("n_posts"), r.get("radius", 0.01), t1["stretch_eps"], t1["residue_db_stretched_fir33"],
                              r.get("equivalent_radial_jitter_m"),
                              {round(1000 * x["sigma_m"], 1): x["residue_db_stretched_fir33"]
                               for x in r.get("tier0_jitter_residue") or []})
        # the residue rows of the designs on the build path: the latest stage-1 run and the pilot, each by run id
        s1_id = s1[0]["run_id"] if s1 else None
        pilot_id = pilot[0]["run_id"] if pilot else None
        thin = rows.get(s1_id)
        pil = rows.get(pilot_id)
        thick = next((v for k, v in rows.items() if v[1] and v[1] >= 0.04), None)
        if thin and thick:
            ff = json.loads((s1[1] / "metrics.json").read_text())["headline"].get("fill_fraction")
            L.append(f"- Thin posts, low coverage: the stage-1 design (run {s1_id}), {thin[0]} posts of 1 cm at "
                     f"{_f(100 * ff if ff is not None else None, '{:.2f}')} % ground coverage, leaves an incoherent full-wave residue of {thin[3]:.1f} dB against the "
                     f"fast model (stretch {100 * thin[2]:+.2f} %); {thick[0]} posts of {100 * thick[1]:g} cm (about 2.3 % "
                     f"coverage) leave {thick[3]:.1f} dB, i.e. the full-wave echo no longer resembles the designed one. "
                     f"Source `{tp}`.")

        def _res(rid, v):
            return (f"run {rid}: full-wave residue {v[3]:.1f} dB, matching {1000 * v[4]:.1f} mm of random radial "
                    f"placement error on the fast model, whose own residue at "
                    + ", ".join(f"{k:g} mm is {x:.1f} dB" for k, x in sorted(v[5].items()) if k <= 2.0)) if v[4] else None

        bits = [b for b in (_res(s1_id, thin) if thin else None,
                            _res(pilot_id, pil) if pil else None) if b]
        if bits:
            L.append("- Unresolved: the full-wave echo differs from the fast model of the same posts by an incoherent "
                     "residue. Whether it is real forward scattering in the post field or the full-wave solver's "
                     "rasterization of 1 cm posts (validated against exact theory for single-post backscatter only; see "
                     "`runs/validation/metrics.json` `caveats`) is not settled. Per design (clap 0; these residues are the "
                     "two ends of the phase-2c residue test, the fast-model end read at the board's placement accuracy, "
                     "a fraction of a millimetre at full scale for a CNC-drilled 1:10 board): stage-1 design "
                     + "; build pilot ".join(bits) + f". Source `{tp}`.")
    ext, ep = _study("runs/s2_motif/_studies/v1_extinction.json")
    if ext:
        L.append(f"- Dense field extinguishes the echo (stage 2 first design, run {ext['run']}): full-wave minus fast-model "
                 f"level per note " + ", ".join(f"{r['note_hz']:.0f} Hz {r['measured_tier1_minus_tier0_db_clap0']:+.1f} dB"
                                               for r in ext["rows"]) + f". Source `{ep}`.")
    if pilot:
        row, rd, pd = pilot
        m = json.loads((rd / "metrics.json").read_text())
        pl = m.get("pilot") or {}
        L.append(f"- Build pilot (run {row['run_id']}): {gating_text(m)}; {pl.get('post_count')} posts, minimum clear gap "
                 f"{_f(100 * pl['min_gap_m'] if pl.get('min_gap_m') is not None else None, '{:.1f}')} cm, coverage "
                 f"{_f(100 * pl['fill_fraction'] if pl.get('fill_fraction') is not None else None, '{:.3f}')} %; "
                 f"echo {_f(m['headline'].get('echo_spl_db'))} dB SPL. Details: section Pilot design. Source "
                 f"`{_rel(rd / 'metrics.json')}`.")
    L += ["", SUMMARY_END]
    return "\n".join(L)


def generated_block(packs, lowpitch=None, s1_pack=None) -> str:
    """packs: list of (index_row, run_dir, pack_dir) with physics; lowpitch: lowpitch_tolerance() result or None;
    s1_pack: the stage-1 pack the low-pitch variant is compared with (default: the first s1_bird pack)."""
    L = [BEGIN, "", "Build physics are computed for the build candidates only (the latest stage-1 design and the build "
         "pilot); every other run is summarized in the table at the top of this file.", ""]
    for row, rd, pd in packs:
        pk = json.loads((pd / "pack.json").read_text())
        ph = pk.get("physics")
        met = json.loads((rd / "metrics.json").read_text())
        thr = _thr(met)
        ids = list(thr)
        if not ph:
            continue
        fl = ph.get("judges_floor")
        if met.get("pilot"):
            L += pilot_lines(row, rd, pd, met)
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
    s1_pack = s1_pack or next((p for p in packs if p[0]["stage"] == "s1_bird"), None)
    if lowpitch and s1_pack:
        row, rd, pd = s1_pack
        met = json.loads((rd / "metrics.json").read_text())
        ph = json.loads((pd / "pack.json").read_text()).get("physics")
        thr = _thr(met)
        exf = pd / "extras.json"
        if ph is not None and exf.exists():
            ph["_extras"] = json.loads(exf.read_text())
        if ph and row["stage"] == "s1_bird":
            labels = {m["id"]: m.get("label", m["id"]) for m in met.get("metrics", [])}
            L += lowpitch_lines(lowpitch, ph, thr, list(dict.fromkeys(thr)), labels)
    L += ["", END]
    return "\n".join(L)


def pilot_lines(row, rd, pd, met) -> list[str]:
    """The build pilot's own facts (generated): candidate study, selection, full-wave result, geometry, sweet spot."""
    pl = met["pilot"]
    hl = met.get("headline", {})
    L = ["", f"#### Pilot design: {row['stage']} / {row['run_id']}", "",
         f"Verdict wording: {pl['verdict']}. Judges: the {pl['judge_stage']} judges. Source `{_rel(rd / 'metrics.json')}` "
         f"keys `metrics`, `headline`, `robustness`, `pilot`.", ""]
    st, sp = _study("runs/build_pilot/_studies/design_study_tier0.json")
    if st:
        L += [f"Candidate study (Tier 0, fan +-{st['half_angle_deg']:g} deg, cap {st['post_cap']} posts, coverage <= "
              f"{100 * st['fill_max']:.2f} %; {st['jitter']}; source `{sp}`). Selection rule, written before the results: "
              f"{st['selection']}", "",
              "| candidate | posts | coverage | min clear gap (cm) | depth (m) | Tier 0 loss | loss at 2 mm jitter | 3D level "
              "(dB re direct) | waveform corr at 1 / 2 / 5 mm | sideways extent, corr >= 0.95 | info: judges |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for c in st["candidates"]:
            for r in c["rows"]:
                j = {x["sigma_mm"]: x for x in r["jitter"]}
                info = r.get("judges_tier0_info_only") or {}
                L.append(f"| {r['candidate']} | {r['n_posts']} | {100 * r['fill']:.3f} % | {100 * r['min_gap_m']:.1f} | "
                         f"{r['depth_m']:.1f} | {r['loss_tier0']:.2f} | {j[2.0]['loss']:.2f} | {r['echo_level_db_3d']:.1f} | "
                         f"{j[1.0]['wave_corr']:.3f} / {j[2.0]['wave_corr']:.3f} / {j[5.0]['wave_corr']:.3f} | "
                         + ("< 5 cm" if not r["sweet_spot_side_m"] else f"{100 * r['sweet_spot_side_m']:.0f} cm") + " | "
                         + ", ".join(f"{k} {v:.3g}" for k, v in info.items()) + " |")
        ch = st["chosen"]
        L += ["", f"Chosen: **{ch['candidate']}** at {ch['n_posts']} posts (coverage {100 * ch['fill']:.3f} %)."]
    L += ["", f"Full-wave result: {gating_text(met)}; echo {_f(hl.get('echo_spl_db'))} dB SPL "
          f"({_f(hl.get('echo_level_db_re_direct'))} dB re direct; with {hl.get('finite_height_m')} m posts "
          f"{_f(hl.get('echo_level_db_re_direct_finite_height'))} dB); tier gap {_f(hl.get('tier_gap_db'))} dB; depth "
          f"{_f(hl.get('depth_m'), '{:.2f}')} m; {pl['post_count']} posts; coverage {100 * pl['fill_fraction']:.3f} %; "
          f"minimum clear gap between post surfaces {100 * pl['min_gap_m']:.1f} cm; robustness summary "
          f"{met.get('robust_summary') or '-'}."]
    rob = met.get("robustness") or []
    if rob:
        L += ["", "Robustness cases (full-wave; listener cases are extra sensors of the same solve, the jitter case is a "
              "second solve):", "", "| case | " + " | ".join(_thr(met)) + " | meets the reference thresholds |",
              "|---|" + "---|" * len(_thr(met)) + "---|"]
        for r in rob:
            vals = r.get("metrics") or {}
            L.append(f"| {r.get('label') or r['case']} | " + " | ".join(_f(vals.get(k), "{:.3g}") for k in _thr(met))
                     + f" | {'yes' if r.get('pass') else 'no'} |")
    au = pl.get("audibility")
    if au:
        L += ["", f"**Audibility levers** (`{_rel(rd / 'metrics.json')}` key `pilot.audibility`; {au['what']}). Moving the "
              "whole ring field outward delays the echo after the clap but costs level; the last column is the post "
              "count that would restore the as-designed level at 6 dB per doubling of ring population:", "",
              "| field starts at (bistatic range, m) | first echo after the clap (ms) | last echo (ms) | far edge (m) | "
              "level (dB re direct) | change (dB) | dB SPL, 100 dB clap | posts to restore level |",
              "|---|---|---|---|---|---|---|---|"]
        for r in au["start_range"]:
            L.append(f"| {r['start_rho_m']:.2f} | {r['first_echo_ms']:.1f} | {r['last_echo_ms']:.1f} | "
                     f"{r['far_edge_m']:.1f} | {r['level_db']:.1f} | {r['delta_db']:+.1f} | {110.46 + r['level_db']:.1f} | "
                     f"{r['posts_to_recover_level']} |")
        L += ["", "Ring population (each post duplicated at a small bearing offset on its own ellipse; fast model, so the "
              "extra extinction of the higher coverage is NOT included):", "",
              "| population | posts | coverage | level (dB re direct) | change (dB) |", "|---|---|---|---|---|"]
        for r in au["population"]:
            L.append(f"| x{r['factor']} | {r['posts']} | {100 * r['fill']:.2f} % | {r['level_db']:.1f} | "
                     f"{r['delta_db']:+.1f} |")
    sm = pl.get("sweet_spot_map")
    if sm:
        L += ["", f"Listening-spot map ({sm['mode']}: {sm['what']}); rows: metres back from the design listener, columns: "
              "metres sideways:", "", "| back \\ side | " + " | ".join(f"{y:+g}" for y in sm["y_side_m"]) + " |",
              "|---|" + "---|" * len(sm["y_side_m"])]
        for x, rr in zip(sm["x_back_m"], sm["wave_corr"]):
            L.append(f"| {x:g} | " + " | ".join(_f(v, "{:.2f}") for v in rr) + " |")
    if (pd / "bom.json").exists():
        b = json.loads((pd / "bom.json").read_text())
        f0 = b["full_scale"][0]
        opt = f0["options"][0]
        L += ["", f"Bill of materials (`{_rel(pd / 'bom.md')}`): {f0['count']} posts of {f0['diameter_mm']} mm "
              f"({f0['count_with_spare']} with {100 * b['spare_fraction']:.0f} % spare), {b['post_height_m']:g} m above "
              f"ground + {b['embed_m']:g} m embedded = {f0['post_length_m']:g} m each, {f0['total_length_with_spare_m']:.0f} m "
              f"of stock: first choice {opt['item']}, {opt['stock_lengths']} stock lengths of {opt['stock_length_m']:g} m "
              f"(tip deflection {opt['wind_tip_deflection_mm_at_10ms']:.1f} mm at 10 m/s). Stake-out: "
              f"`{_rel(pd / 'stakeout.csv')}` (ring by ring, far ring first)."]
    return L


def jitter_lines(rows, ids, f_center, floor=None):
    import math

    seeds = rows[0]["seeds"] if rows else []
    L = ["", f"Random placement error (Gaussian, every post, {len(seeds)} seeds per sigma: mean and range), free-space "
         "infinite posts. Judge view: the spec's judges (with the judge floor). Physical view: measured waveform "
         "correlation with the nominal echo (clap-family mean of per-clap correlations), next to the parameter-free "
         f"coherent-loss factor A = exp(-(4 pi sigma f / c)^2 / 2) at f = {f_center or float('nan'):.0f} Hz (the "
         "fraction of coherent amplitude kept in the target band for RANGE errors; it says nothing about where the lost "
         "power goes, and it is not defined for tangential moves, printed '-'):", "",
         "| direction | sigma (mm) | level change (dB) | waveform corr, measured | coherent factor A | judges (mean, range) |",
         "|---|---|---|---|---|---|"]
    for j in rows:
        if j["kind"] == "nominal":
            continue
        wc = j["waveform_corr"]
        # A applies to range errors only; a tangential move changes range to second order, so no A there
        A = (f"{math.exp(-((4 * math.pi * j['sigma_mm'] / 1000 * (f_center or 0) / 343.0) ** 2) / 2):.3f}"
             if j["kind"] == "radial" else "-")
        L.append(f"| {j['kind']} | {j['sigma_mm']:g} | {j['level_delta_db']['mean']:+.2f} | {wc['mean']:.3f} "
                 f"({wc['min']:.3f}-{wc['max']:.3f}) | {A} | {_jstats(j.get('judges'), ids, floor)} |")
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
    mm = measurement_margins(ex, thr, gate)
    if mm:
        L += ["", "**Measurement margins** (physical-measurement gates only -- phases 2c and 3b; simulation verdicts use the "
              "spec thresholds with no margin): " + "; ".join(margin_lines(mm)) + ". REPEAT: average more, re-log "
              "temperature, measure again; a second REPEAT is reported as such, not rounded to a pass."]
    ok = [g for g in ph.get("height_rigid_ground", []) if g["post_height_m"] == b_height
          and _passes(g.get("judges"), thr)]
    if ok:
        z = max(g["ear_height_m"] for g in ok)
        L += ["", f"**Phase-2c measurement height**: emitter and mic {1000 * z / 10:.0f} mm above the model ground plane "
              f"(= {z:g} m at full scale), the highest clap/ear height whose rigid-ground row with {b_height:g} m posts "
              f"passes the judges; passing heights: " + ", ".join(
                  f"{g['ear_height_m']:g} m" for g in sorted(ok, key=lambda g: g["ear_height_m"]))
              + ". Also measure at 150 mm (1.5 m) as the ground-model check; its predicted verdict is in the ground table."]
    elif ph.get("height_rigid_ground"):
        L += ["", f"**Phase-2c measurement height**: no rigid-ground row with {b_height:g} m posts passes the judges "
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
    top = ex["f_top_hz"]
    L = ["", f"{title}: jitter-induced residual r = jittered echo - g x nominal (common gain g removed), energy split "
         f"into four bands that partition 0-8 kHz: below the target band (< {lo:.0f} Hz), the target band "
         f"({lo:.0f}-{hi:.0f} Hz, the same band as this section's 'Target band' line), above it to {top:.0f} Hz, and "
         f"above {top:.0f} Hz; as % of the nominal echo energy; clap-family mean of per-clap values, mean over "
         f"{len(ex['seeds'])} seeds. The four columns sum to the total column. Check: residual/jittered energy equals "
         f"1 - corr^2 per clap.", "",
         f"| sigma (mm) | corr (clap mean) | below | in target band | above, to {top / 1000:g} kHz | above "
         f"{top / 1000:g} kHz | total | above to {top / 1000:g} kHz, worst clap | max abs(1 - corr^2 - residual/jittered) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for row in ex["residual"]:
        cl = [c for seed in row["per_seed_per_clap"] for c in seed]
        rb = np.array([c["res_bands"] for c in cl])
        nc = len(row["per_seed_per_clap"][0])
        worst = max(np.mean([seed[k]["res_bands"][2] for seed in row["per_seed_per_clap"]]) for k in range(nc))
        chk = max(abs(c["one_minus_corr2"] - c["res_over_e"]) for c in cl)
        tot = np.mean([c["res_total"] for c in cl])
        L.append(f"| {row['sigma_mm']:g} | {np.mean([c['corr'] for c in cl]):.3f} | {100 * rb[:, 0].mean():.2f} % | "
                 f"{100 * rb[:, 1].mean():.2f} % | {100 * rb[:, 2].mean():.2f} % | {100 * rb[:, 3].mean():.2f} % | "
                 f"{100 * tot:.2f} % | {100 * worst:.2f} % | {chk:.1e} |")
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


def refresh_doc(doc: Path, block: str, summary: str | None = None):
    """Replace the generated block (and the generated summary block, when given) between their markers."""
    text = doc.read_text()
    for b, e, blk in ((BEGIN, END, block), (SUMMARY_BEGIN, SUMMARY_END, summary)):
        if blk is None:
            continue
        i, j = text.find(b), text.find(e)
        if i < 0 or j < 0 or j < i:
            raise SystemExit(f"{doc}: generated-block markers not found ({b[:40]}...)")
        text = text[:i] + blk + text[j + len(e):]
    doc.write_text(text)


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

    from echo.buildkit import run_inputs_hash

    params = {"seeds": list(seeds), "sigmas": list(sigmas), "target": LOWPITCH, "dir": _rel(variant_dir),
              "inputs": run_inputs_hash(variant_dir)}
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

    from echo.buildkit import run_inputs_hash

    tkey = None if target is None else {"name": target.name, "f_track_ends": None if target.f_track is None else
                                        [float(target.f_track[1][0]), float(target.f_track[1][-1])],
                                        "duration_s": target.duration_s}
    return cached_json(out_json, {"run": _rel(run_dir), "f_band": None if f_band is None else list(f_band),
                                  "inputs": run_inputs_hash(run_dir), "target": tkey}, compute,
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
            L += reading_rule_lines(mex, res["extras"])
    return L


def _res_summary(ex, sigma):
    """Clap-family means of the residual bands at one sigma, and the per-clap waveform correlation (seed mean)."""
    import numpy as np

    row = next((r for r in ex["residual"] if r["sigma_mm"] == sigma), None)
    if row is None:
        return None
    per = row["per_seed_per_clap"]
    rb = np.array([[c["res_bands"] for c in seed] for seed in per])  # [seed, clap, band]
    return {"bands": rb.mean(axis=(0, 1)).tolist(), "corr_per_clap": np.mean([[c["corr"] for c in seed] for seed in per],
                                                                             axis=0).tolist()}


def reading_rule_lines(main_ex, var_ex, sigma=1.0, close_rel=0.10):
    """The block's outcome against the reading rule of BUILD.md ("Does a lower target pitch buy tolerance?")."""
    a, b = _res_summary(main_ex, sigma), _res_summary(var_ex, sigma)
    if not a or not b:
        return []
    r1, r2 = main_ex["bias_to_signal"]["ratio_amp"], var_ex["bias_to_signal"]["ratio_amp"]
    close = abs(r1 - r2) / r1 <= close_rel
    ratio_in = a["bands"][1] / b["bands"][1] if b["bands"][1] > 0 else float("inf")
    var_above = b["bands"][2] > 10 * b["bands"][1]
    main_in = a["bands"][1] > a["bands"][2]
    pc = ", ".join(f"{c:.3f}" for c in b["corr_per_clap"])
    pc1 = ", ".join(f"{c:.3f}" for c in a["corr_per_clap"])
    return ["", f"**Reading-rule outcome at {sigma:g} mm** (generated): bias-to-modulation ratios {r1:.2f} vs {r2:.2f} "
            f"({'close' if close else 'not close'}: differ by {100 * abs(r1 - r2) / r1:.0f} % against a {100 * close_rel:.0f} % "
            f"rule), so (i) {'can act only through the clap spectrum' if close else 'is not excluded by the bias ratio'}. "
            f"The variant's residual lies {'almost entirely above' if var_above else 'not mainly above'} its target band "
            f"({100 * b['bands'][2]:.2f} % above against {100 * b['bands'][1]:.3f} % in band) while the stage-1 residual "
            f"{'stays mainly inside' if main_in else 'does not stay mainly inside'} its band ({100 * a['bands'][1]:.2f} % in "
            f"band, {100 * a['bands'][2]:.2f} % above): this {'favours' if (var_above and main_in) else 'does not favour'} "
            f"(ii). In-band, the variant's residual is {ratio_in:.0f}x smaller than stage 1's. Sensitivity depends "
            f"strongly on which clap is used: waveform correlation per clap (claps 0-4) at {sigma:g} mm, variant {pc}; "
            f"stage-1 design {pc1}."]


def with_variant_extras(vd):
    if vd is None:
        return None
    low = lowpitch_tolerance(vd)
    from echo.buildkit import load_run, target_band

    # one band definition everywhere: the target spectrum within -20 dB of its peak (buildkit.target_band)
    low["extras"] = ensure_extras(vd, vd / "extras.json", f_band=target_band(load_run(vd)), target=lowpitch_target())
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
    if a.doc_only or a.all or a.refresh_doc:
        from echo.buildkit import load_run, pack_name

        rows = index_runs()
        cands = build_candidates(rows)
        packs = []
        for row, rd in (rows if a.all else cands):
            pd = Path(a.out) / pack_name(load_run(rd))
            if not a.doc_only or not (pd / "pack.json").exists():
                pd = build_pack(rd, **kw)
                print(f"wrote {_rel(pd)}")
            packs.append((row, rd, pd))
        if a.doc_only or a.refresh_doc:
            phys = [p for p in packs if (p[2] / "pack.json").exists()
                    and json.loads((p[2] / "pack.json").read_text()).get("physics")]
            for row, rd, pd in phys:
                ph = json.loads((pd / "pack.json").read_text())["physics"]
                ensure_extras(rd, pd / "extras.json", f_band=tuple(ph["target_band_hz"]))
            low = with_variant_extras(latest_variant())
            s1 = next((p for p in phys if p[0]["stage"] == "s1_bird"), None)
            pilot = next((p for p in phys if p[0]["stage"].startswith("build_")), None)
            refresh_doc(Path(a.doc), generated_block(phys, low, s1), summary_block(rows, s1, pilot))
            print(f"refreshed {a.doc}")
    for rd in a.run_dirs:
        print(f"wrote {_rel(build_pack(rd, **kw))}")
    if not (a.run_dirs or a.all or a.refresh_doc or a.lowpitch or a.doc_only):
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
