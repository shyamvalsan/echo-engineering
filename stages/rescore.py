"""Rescore every final run under two criterion sets, side by side, from saved audio (no full-wave solves).

    uv run python -m stages.rescore                    # writes criteria + listening_verdict into each final run's
                                                       # metrics.json, and runs/_criteria/{summary.json,summary.md}
    uv run python -m stages.rescore --regen-controls   # (once) regenerate the 4c other-word control echoes on Tier 0

spec_v1 is the original verdict (top-level `passed`, untouched); owner_v2 is echo/metrics_v2.py.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np

from echo import export
from echo.scene import FS

ROOT = export.ROOT
CRIT_DIR = ROOT / "runs" / "_criteria"
CONTROL_NPZ = CRIT_DIR / "control_words_tier0.npz"


def regen_control_words(out=CONTROL_NPZ, log=print):
    """Re-run the 4c other-word control (stages.s4_speech.control_words: same config, seed, Tier 0 only) and keep the
    per-clap Tier 0 echo windows, which the original study did not save. Saves {word: [5, n]} + targets."""
    import echo.metrics_speech  # noqa: F401  (registers the stage-4 judges the driver scores with)
    from echo.metrics import echo_segment
    from stages.common import run_stage
    from stages.s4_speech import (CONTROL_WORDS, control_target, duration_for, fill_for_posts, make_config,
                                  target_of)

    arrs = {}
    for w in ("hello",) + tuple(CONTROL_WORDS):
        t = target_of("hello") if w == "hello" else control_target(w)
        cfg = make_config("4c", "hello")
        cfg.make_target = (lambda tt=t: tt)
        cfg.duration_s = duration_for(t)
        cfg.target_fill = fill_for_posts(cfg, t, cfg._n_posts)
        cfg.field = False
        tmp = Path(tempfile.mkdtemp(prefix="s4c_", dir=str(ROOT / ".cache")))
        _, des, res = run_stage(cfg, None, command="rescore --regen-controls", verbose=False, runs_root=tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        arrs[f"echo_{w}"] = echo_segment(des.echo_t0_2d, res.n0 / FS, len(t.audio))
        arrs[f"target_{w}"] = t.audio
        arrs[f"posts_{w}"] = np.array(len(des.posts))
        log(f"[regen] {w}: {len(des.posts)} posts, window {len(t.audio)} samples")
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, **arrs)
    return arrs


# ------------------------------------------------------------------------------------------------- runs and tests
TEST_ORDER = ("s1_bird", "s2_motif", "s3_melody_100ms", "s3_melody_60ms", "s4a_ah", "s4b_ma", "s4b_ba", "s4b_om",
              "s4c_hello")
TEST_TITLE = {"s1_bird": "Stage 1 bird whistle", "s2_motif": "Stage 2 four-note motif",
              "s3_melody_100ms": "Stage 3 melody, 100 ms notes", "s3_melody_60ms": "Stage 3 melody, 60 ms notes",
              "s4a_ah": "4a vowel \"ah\"", "s4b_ma": "4b syllable \"ma\"", "s4b_ba": "4b syllable \"ba\"",
              "s4b_om": "4b syllable \"om\"", "s4c_hello": "4c word \"hello\""}
LISTENING = {"by": "owner", "date": "2026-11-25", "verdict": "pass",
             "basis": "echo_tier1.wav (echo alone, normalized) by ear", "scope": "all final runs' current results",
             "quote": "listening to the results, I think all of them are pass",
             "blind": False,
             "note": "A human judgment, recorded as such; not an automated pass. Not a blind test: the listener knew "
                     "each target, and knowing the target helps a listener hear it. A blind check is prepared in "
                     "runs/_criteria/blind_test/. Written only on the runs the owner heard (metrics_v2.ACCEPTED_RUNS, "
                     "pinned to the newest final run per test before the statement, which the ledger logs at 15:04). "
                     "Which of the two stage-2 designs the owner heard is not recorded; pinned to the first design "
                     "(20261125-122003-s2) pending confirmation."}
DECONV_EPS = 1e-5  # Tikhonov term re max |C0|^2; validated on the saved stage-4 per-clap echoes (<= 2.3 % error)


def test_of(stage, manifest):
    if stage == "s1_bird":
        return "s1_bird"
    if stage == "s2_motif":
        return "s2_motif"
    if stage == "s3_melody":
        return "s3_melody_60ms" if manifest["run_id"].endswith("60ms") else "s3_melody_100ms"
    if stage == "s4_speech":
        return {"4a": "s4a", "4b": "s4b", "4c": "s4c"}[manifest["substage"]] + "_" + manifest["target_name"]
    return None


def load_target(test):
    from echo import targets as T

    if test == "s1_bird":
        return T.bird_note()
    if test == "s2_motif":
        return T.motif()
    if test.startswith("s3_melody"):
        return T.melody(60 if test.endswith("60ms") else 100)
    from echo.targets_speech import speech_target

    return speech_target(test.split("_", 1)[1])


def final_runs(runs_root=None):
    """Final runs of the six tests (index order: newest first), each {test, run_id, dir, manifest, metrics}."""
    root = Path(runs_root or ROOT / "runs")
    out = []
    for r in json.loads((root / "index.json").read_text())["runs"]:
        if r["status"] != "final":
            continue
        d = root / r["path"]
        man = json.loads((d / "manifest.json").read_text())
        test = test_of(r["stage"], man)
        if test is None:
            continue
        out.append({"test": test, "run_id": r["run_id"], "dir": d, "manifest": man, "created": r["created"]})
    return out


def run_band(manifest):
    return (500.0, float(manifest["solver"]["f_max"]))


def _deconv(e0, claps, eps_rel=DECONV_EPS):
    n = len(e0)
    N = 1 << int(np.ceil(np.log2(n + claps.shape[1])))
    E0 = np.fft.rfft(e0, N)
    C = np.fft.rfft(claps, N, axis=-1)
    p = np.abs(C[0]) ** 2
    H = E0 * np.conj(C[0]) / (p + eps_rel * p.max())
    return np.fft.irfft(H[None] * C, N, axis=-1)[:, :n]


def clap_echoes(run, claps):
    """Per-clap Tier 1 echoes [K, n_file] on the run's time axis (t = 0 at emission; arbitrary common scale) and the
    route used. Routes, in order: the saved stage-4 per-clap Tier 1 echoes (runs/s4_speech/_studies/echoes_<name>.npz,
    run_id checked; exact); ir_tier1.wav in the run folder (echo_k = clap_k * ir); band-limited regularized
    deconvolution of echo_tier1.wav (clap 0) re-convolved with each clap."""
    import soundfile as sf

    d = run["dir"]
    e0, _ = sf.read(d / "echo_tier1.wav", dtype="float64")
    n = len(e0)
    ir = d / "ir_tier1.wav"
    npz = ROOT / "runs" / "s4_speech" / "_studies" / f"echoes_{run['test'].split('_', 1)[-1]}.npz"
    z = np.load(npz) if npz.exists() and run["test"].startswith("s4") else None
    if z is not None and str(z["run_id"]) == run["run_id"] and z["tier1"].shape[-1] == n:
        E = np.asarray(z["tier1"], float)
        route = f"saved per-clap Tier 1 echoes ({npz.relative_to(ROOT)})"
    elif ir.exists():
        h, _ = sf.read(ir, dtype="float64")
        E = np.stack([np.convolve(h, c)[:n] for c in claps])
        route = "ir_tier1.wav (echo_k = clap_k * ir)"
    else:
        E = _deconv(e0, claps)
        route = f"deconvolution of echo_tier1.wav by clap 0 (Tikhonov eps {DECONV_EPS:g} re max|C0|^2)"
    g = float(np.dot(E[0], e0) / np.dot(E[0], E[0]))
    err0 = float(np.linalg.norm(g * E[0] - e0) / np.linalg.norm(e0))
    return E, {"route": route, "clap0_rel_err_vs_echo_tier1_wav": err0}


def _check_target(run, target, n0):
    import soundfile as sf

    t, _ = sf.read(run["dir"] / "target.wav", dtype="float64")
    seg = t[n0: n0 + len(target.audio)]
    c = float(np.dot(seg, target.audio) / (np.linalg.norm(seg) * np.linalg.norm(target.audio) + 1e-30))
    if c < 0.999:
        raise RuntimeError(f"{run['run_id']}: target.wav does not match the rebuilt target (corr {c:.4f})")
    return c


def load_run(run, claps):
    from echo.metrics import echo_segment

    target = load_target(run["test"])
    pr = json.loads((run["dir"] / "profile.json").read_text())
    n0 = int(round(2 * pr["r0_m"] / run["manifest"]["c"] * FS))
    _check_target(run, target, n0)
    E, route = clap_echoes(run, claps)
    run.update(target=target, n0=n0, segs=echo_segment(E, n0 / FS, len(target.audio)), route=route,
               band=run_band(run["manifest"]))
    return run


# ------------------------------------------------------------------------------------------------- controls
def build_controls(test, acc, others, claps, words=None):
    """The fixed negative-control set of one test, from the accepted echo `acc` (its [5, n] window), the other tests'
    accepted windows `others` {test: [5, n_other]}, the clap family and (4c) the other-word Tier 0 echoes."""
    import echo.metrics_v2 as V

    n = acc["segs"].shape[-1]
    band = acc["band"]
    K = len(claps)
    C = [{"name": f"wrong_target:{u}", "kind": "a wrong target", "segs": V.fit(s, n)} for u, s in others.items()]
    C.append({"name": "clap_alone", "kind": "b no structure", "segs": np.stack([V.clap_alone(c, n) for c in claps])})
    C.append({"name": "noise_burst", "kind": "b no structure",
              "segs": np.stack([V.noise_burst(n, c, band, seed=k) for k, c in enumerate(claps)])})
    C.append({"name": "time_reversed", "kind": "c reversed", "segs": V.time_reversed(acc["segs"])})
    C.append({"name": "phase_scrambled", "kind": "d same long-term spectrum",
              "segs": np.stack([V.phase_scrambled(s, band, seed=k) for k, s in enumerate(acc["segs"])])})
    if test in V.TONAL:
        for s in V.SHIFTS_SEMI:
            C.append({"name": f"shift{s:+.0f}st", "kind": "e mistuned", "segs": V.pitch_shifted(acc["segs"], s)})
    if test in V.MULTI_NOTE:
        C.append({"name": "notes_3_4_swapped", "kind": "e notes swapped (segments of the accepted echo)",
                  "segs": V.notes_swapped(acc["segs"], acc["target"].notes)})
    if test in V.TONAL:  # the same transforms of the perfect echo: checked, never used for calibration
        per = np.stack([V.perfect_echo(acc["target"].audio, c, band) for c in claps])
        for s in V.SHIFTS_SEMI:
            C.append({"name": f"perfect_shift{s:+.0f}st", "kind": "e mistuned perfect echo",
                      "segs": V.pitch_shifted(per, s)})
        if test in V.MULTI_NOTE:
            C.append({"name": "perfect_notes_3_4_swapped", "kind": "e notes swapped (perfect echo)",
                      "segs": V.notes_swapped(per, acc["target"].notes)})
    if test in V.TONAL:  # near-miss negatives (review r2): altered targets through each clap, outside the C1 set
        for name, a in V.near_miss_targets(test, acc["target"]).items():
            C.append({"name": f"near_miss:{name}", "kind": "g near miss (altered target * clap)",
                      "segs": np.stack([V.perfect_echo(a, c, band) for c in claps])})
    if test == "s4c_hello" and words:
        for w, s in words.items():
            C.append({"name": f"other_word:{w}", "kind": "f other word (4c pipeline, Tier 0)", "segs": V.fit(s, n)})
    assert all(c["segs"].shape == (K, n) for c in C)
    return C


def load_words():
    if not CONTROL_NPZ.exists():
        return None
    z = np.load(CONTROL_NPZ)
    return {k[5:]: z[k] for k in z.files if k.startswith("echo_") and k != "echo_hello"}


# ------------------------------------------------------------------------------------------------- main study
def study(runs_root=None, log=print, tests=None, calibrate=False):
    """Score every final run under owner_v2. Returns (per-run blocks, per-test study)."""
    import echo.metrics_v2 as V
    from echo.clap import clap_family

    claps = clap_family(5)
    runs = [load_run(r, claps) for r in final_runs(runs_root)]
    newest = {}  # the pinned accepted run of each test (V.ACCEPTED_RUNS), never "the newest"
    for r in runs:
        if V.ACCEPTED_RUNS.get(r["test"]) == r["run_id"]:
            newest[r["test"]] = r
    other_t = {t: newest[t]["target"].audio for t in newest}
    words = load_words()
    blocks, tests_out = {}, {}
    problems = []
    for test in [t for t in TEST_ORDER if t in newest and (tests is None or t in tests)]:
        acc = newest[test]
        cands = V.distractors(test, acc["target"], other_t)
        feats = {k: V.logmel_v2(v) for k, v in cands.items()}

        def values(segs):
            return V.clap_values(test, segs, acc["target"], cands, feats=feats)

        pos = values(acc["segs"])
        perfect = values(np.stack([V.perfect_echo(acc["target"].audio, c, acc["band"]) for c in claps]))
        ctrls = build_controls(test, acc, {u: newest[u]["segs"] for u in newest if u != test}, claps, words)
        for c in ctrls:
            c["per_clap"] = values(c["segs"])
        log(f"[{test}] scored accepted, perfect and {len(ctrls)} controls")
        thr = dict(V.THRESHOLDS_V2[test])
        calib = None
        if test in V.TONAL:
            mist = [V.majority_value([v["pitch_cents"] for v in c["per_clap"]]) for c in ctrls
                    if c["kind"] in ("e mistuned", "e mistuned perfect echo")]
            posv = [V.majority_value([v["pitch_cents"] for v in pc]) for pc in (pos, perfect)]
            t_rule, worst, best = V.calibrate_pitch(posv, mist)
            if t_rule != thr.get("pitch_cents"):
                problems.append(f"{test}: derived C2 threshold {t_rule} != frozen {thr.get('pitch_cents')}")
            calib = {"rule": "midway between worst positive and best mistuning control (accepted and perfect echo "
                             "+-1, +-2 semitones; 3rd-best clap), 5-cent rounding, >= "
                             f"{V.MIN_MARGIN_CENTS:g} c from both sides, below {V.MAX_PITCH_T_CENTS:g} c",
                     "derived_threshold": t_rule, "frozen_threshold": thr.get("pitch_cents"),
                     "matches_frozen": t_rule == thr.get("pitch_cents"), "worst_positive": worst,
                     "best_mistuning_control": best,
                     "margin_positive": None if t_rule is None else t_rule - worst,
                     "margin_control": None if t_rule is None else best - t_rule}
        c1_valid = sum(bool(v["id_correct"]) for v in perfect) >= V.MAJORITY  # judge-validity rule
        if c1_valid != bool(thr.get("c1", True)):
            problems.append(f"{test}: C1 validity on the perfect echo {c1_valid} != frozen {thr.get('c1', True)}")
        if test == "s4c_hello" and sum(bool(v["hello_hit"]) for v in perfect) < V.MAJORITY:
            problems.append("s4c_hello: C3 rejects the perfect echo")
        acc_v, acc_ok = V.verdict(test, pos, thr)
        per_v, per_ok = V.verdict(test, perfect, thr)
        ctrl_res = [(c, V.verdict(test, c["per_clap"], thr)) for c in ctrls]
        n_rej = sum(not ok for _, (_, ok) in ctrl_res)
        best_ctrl = max(ctrl_res, key=lambda x: (x[1][0]["claps_pass"], x[1][0]["id_claps"], x[1][0]["id_margin_median"]))
        established = bool(acc_ok and per_ok and n_rej == len(ctrls))
        why = []
        if not acc_ok:
            why.append("the accepted echo fails the criterion")
        if not per_ok:
            why.append("the perfect echo fails the criterion")
        if n_rej < len(ctrls):
            why.append("controls that pass: " + ", ".join(c["name"] for c, (_, ok) in ctrl_res if ok))
        margin = {"id": {"c1_valid_on_perfect_echo": c1_valid, "c1_used": bool(thr.get("c1", True)),
                         "c1_matches_frozen": c1_valid == bool(thr.get("c1", True)),
                         "accepted_median_margin": acc_v["id_margin_median"],
                         "perfect_median_margin": per_v["id_margin_median"],
                         "accepted_id_claps": acc_v["id_claps"],
                         "strongest_control": best_ctrl[0]["name"], "strongest_control_values": best_ctrl[1][0]},
                  "pitch": calib}
        if not established and acc_ok is False and per_ok and n_rej == len(ctrls) and \
                (test not in V.TONAL or thr.get("pitch_cents") is not None):
            near = sorted({v["nearest"] for v in pos if not v["id_correct"]})
            note = ("accepted by ear; the criterion accepts a perfect echo and rejects every control, and it also "
                    f"rejects the accepted echo ({acc_v['claps_pass']}/5 claps pass; nearest distractor on the "
                    f"failing claps: {', '.join(near) or '-'}"
                    + ("; for speech echoes this is often a short tonal target padded with silence, a construction "
                       "effect of the closed set" if test.startswith("s4") else "") + ")")
        elif not established and calib is not None and calib["derived_threshold"] is None:
            note = (V.NULL_NOTE + f" (no C2 pitch threshold exists: worst positive {calib['worst_positive']:.0f} c "
                    f"(the accepted echo, 3rd-best clap, worst note) against best mistuned control "
                    f"{calib['best_mistuning_control']:.0f} c, so no automated criterion establishes the pass)")
        elif not established:
            note = V.NULL_NOTE + " (" + "; ".join(why) + ")"
        else:
            note = None
        if test == "s4c_hello" and words:
            from echo import metrics_speech as MS

            z = np.load(CONTROL_NPZ)
            own = {w: int(sum(MS.recognize(s)[0] for s in z[f"echo_{w}"])) for w in words}
            tests_out_extra = {"other_words_hello_claps_own_length": own,
                               "other_words_hello_claps_hello_length": {
                                   c["name"].split(":")[1]: v["hello_claps"] for c, (v, _) in ctrl_res
                                   if c["name"].startswith("other_word:")},
                               "other_words_stored_study": {"yellow": 1, "mellow": 2, "halo": 0}}
        else:
            tests_out_extra = {}
        tests_out[test] = {"title": TEST_TITLE[test], "accepted_run": acc["run_id"], "band_hz": list(acc["band"]),
                           "distractors": list(cands), "accepted": {"values": acc_v, "pass": acc_ok},
                           "perfect_echo": {"values": per_v, "pass": per_ok,
                                            "per_clap": perfect},
                           "controls": [{"name": c["name"], "kind": c["kind"], "values": v, "pass": ok}
                                        for c, (v, ok) in ctrl_res],
                           "controls_rejected": n_rej, "controls_total": len(ctrls), "established": established,
                           "margin": margin, "note": note, "rests_on": V.rests_on(test, thr), **tests_out_extra}
        for r in [r for r in runs if r["test"] == test]:
            pc = pos if r is acc else values(r["segs"])
            b = V.score_v2(test, pc, ctrls, established, margin, note=note, thr=thr)
            b.update(test=test, accepted_run=acc["run_id"], echo_source=r["route"],
                     perfect_echo={"values": per_v, "pass": per_ok})
            blocks[r["run_id"]] = {"run": r, "owner_v2": b, "accepted": r is acc}
            log(f"  {r['run_id']}: owner_v2 {b['passed']} ({V.verdict(test, pc, thr)[0]})")
    if problems and not calibrate:
        raise RuntimeError("frozen owner_v2 calibration differs from the re-derivation (thresholds must not re-fit "
                           "silently; update THRESHOLDS_V2 only deliberately, with a DECISIONS line):\n  "
                           + "\n  ".join(problems))
    for p_ in problems:
        log("[calibrate] " + p_)
    return blocks, tests_out


def write_run_blocks(blocks):
    import echo.metrics_v2 as V

    for rid, b in blocks.items():
        p = b["run"]["dir"] / "metrics.json"
        m = json.loads(p.read_text())
        m["criteria"] = {"spec_v1": V.spec_v1_block(m), "owner_v2": b["owner_v2"]}
        m["listening_verdict"] = dict(LISTENING, run_id=rid) if b["accepted"] else None
        export.write_json(p, m, indent=1)


def _fmt(x, nd=1):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def write_summary(blocks, tests_out, out_dir=CRIT_DIR):
    import echo.metrics_v2 as V

    rows = []
    for rid, b in blocks.items():
        r = b["run"]
        m = json.loads((r["dir"] / "metrics.json").read_text())
        o = b["owner_v2"]
        rows.append({"test": r["test"], "run_id": rid, "accepted": b["accepted"], "spec_v1": bool(m["passed"]),
                     "owner_v2": o["passed"], "listening": "pass (owner, not blind)" if b["accepted"] else None,
                     "controls_rejected": sum(not c["pass"] for c in o["controls"]), "controls_total": len(o["controls"]),
                     "rests_on": o["rests_on"], "echo_source": o["echo_source"]})
    rows.sort(key=lambda x: (TEST_ORDER.index(x["test"]), not x["accepted"], x["run_id"]))
    acc_rows = [r for r in rows if r["accepted"]]
    n_conf = sum(r["owner_v2"] is True for r in acc_rows)
    summary = {"label_v1": V.SPEC_V1_LABEL, "label_v2": V.LABEL, "thresholds_v2": V.THRESHOLDS_V2,
               "accepted_runs": V.ACCEPTED_RUNS, "majority": V.MAJORITY, "listening_verdict": LISTENING,
               "confirmed_automatically": f"{n_conf} of {len(acc_rows)}", "runs": rows, "tests": tests_out}
    out_dir.mkdir(parents=True, exist_ok=True)
    export.write_json(out_dir / "summary.json", summary, indent=1)
    L = ["# Criteria: spec_v1 vs owner_v2 vs the owner's listening verdict", "",
         "Generated by `uv run python -m stages.rescore`. spec_v1 = the spec's thresholds and judges (unchanged; "
         "top-level `passed`). owner_v2 = echo/metrics_v2.py, calibrated on the runs the owner listened to "
         "(`ACCEPTED_RUNS`). Listening = the owner's verdict by ear on echo_tier1.wav, knowing each target (not "
         "blind; see blind_test/).", "",
         "**How to read owner_v2.** On an accepted (calibration) run owner_v2 can only return PASS or null (\"not "
         "established\"): it cannot fail the echo it was calibrated on. Null is therefore not a soft pass: it means "
         "no automated criterion in the family confirms what the ear accepted. "
         f"**Confirmed automatically: {n_conf} of {len(acc_rows)} accepted echoes.** Earlier attempts are scored "
         "with the same frozen criterion and can fail.", "",
         "| test | run | spec_v1 | owner_v2 | listening | controls rejected | a pass rests on | numbers |",
         "|---|---|---|---|---|---|---|---|"]

    def v(x):
        return "null" if x is None else ("PASS" if x else "fail")

    for row in rows:
        t = tests_out[row["test"]]
        mg = t["margin"]
        acc = t["accepted"]["values"]
        parts = [f"accepted: {acc['claps_pass']}/5 claps pass; C1 {mg['id']['accepted_id_claps']}/5 identified "
                 f"(median margin {mg['id']['accepted_median_margin']:.2f}; perfect {mg['id']['perfect_median_margin']:.2f})"]
        if not mg["id"]["c1_used"]:
            parts[0] = "C1 not used (rejects the perfect echo); " + parts[0]
        if mg["pitch"]:
            pm = mg["pitch"]
            parts.append(f"C2 T {_fmt(pm['frozen_threshold'], 0)} c (worst positive {pm['worst_positive']:.0f} c, "
                         f"best mistuned control {pm['best_mistuning_control']:.0f} c); accepted {acc['pitch_cents']:.0f} c")
        if "hello_claps" in acc:
            parts.append(f"hello {acc['hello_claps']}/5 (perfect {t['perfect_echo']['values']['hello_claps']}/5), "
                         f"best control {max(c['values']['hello_claps'] for c in t['controls'])}/5")
        L.append(f"| {TEST_TITLE[row['test']]} | `{row['run_id']}`{' (heard by owner)' if row['accepted'] else ''} | "
                 f"{v(row['spec_v1'])} | {v(row['owner_v2'])} | {row['listening'] or '-'} | "
                 f"{row['controls_rejected']}/{row['controls_total']} | {row['rests_on'] if row['owner_v2'] else '-'} | "
                 f"{'; '.join(parts) if row['accepted'] else '(same frozen criterion)'} |")
    L += ["", "## Per test", ""]
    for test, t in tests_out.items():
        L.append(f"### {t['title']}  (accepted: `{t['accepted_run']}`)")
        L.append(f"- criterion established: {t['established']}" + (f" — {t['note']}" if t["note"] else ""))
        L.append(f"- a pass rests on: {t['rests_on']}")
        L.append(f"- accepted echo: {t['accepted']['values']}; perfect echo: {t['perfect_echo']['values']}")
        if "other_words_hello_claps_own_length" in t:
            L.append(f"- other words, claps heard as \"hello\": at the hello window length "
                     f"{t['other_words_hello_claps_hello_length']}; at each word's own length "
                     f"{t['other_words_hello_claps_own_length']}; stored study (own length, same pipeline) "
                     f"{t['other_words_stored_study']}")
        passing = [c["name"] for c in t["controls"] if c["pass"]]
        L.append(f"- controls rejected {t['controls_rejected']}/{t['controls_total']}"
                 + (f"; passing: {', '.join(passing)}" if passing else ""))
        for c in t["controls"]:
            L.append(f"  - {c['name']} ({c['kind']}): {'PASS' if c['pass'] else 'fail'} {c['values']}")
        L.append("")
    (out_dir / "summary.md").write_text("\n".join(L).rstrip("\n") + "\n")
    return summary


def _trim_silence(x, rel=1e-3):
    a = np.abs(x)
    idx = np.nonzero(a > rel * (a.max() or 1.0))[0]
    return x[idx[0]: idx[-1] + 1] if len(idx) else x


def make_blind_test(runs, out_dir=CRIT_DIR / "blind_test", key_dir=CRIT_DIR / "blind_test_key", seed=20261125,
                    lead_s=0.25):
    """Echo-only files of the accepted runs under shuffled neutral names, every sample and every reference target
    padded to one common length with the same lead-in (no duration cue), written fresh as
    plain 24-bit PCM WAV (fmt + data chunks only, no metadata); the key lives in a separate folder that is not handed to listeners."""
    import echo.metrics_v2 as V
    import soundfile as sf

    acc = {r["test"]: r for r in runs if V.ACCEPTED_RUNS.get(r["test"]) == r["run_id"]}
    tests = [t for t in TEST_ORDER if t in acc]
    order = np.random.default_rng(seed).permutation(len(tests))
    tag = {t: acc[t]["run_id"].split("-", 2)[2] for t in tests}
    sig = {}
    for t in tests:
        e, fs = sf.read(ROOT / "listen" / f"{tag[t]}_echo_only.wav", dtype="float64")
        g, _ = sf.read(ROOT / "listen" / f"{tag[t]}_target.wav", dtype="float64")
        sig[t] = (_trim_silence(e), _trim_silence(g))
    L = int(round(2 * lead_s * FS)) + max(max(len(a), len(b)) for a, b in sig.values())
    lead = int(round(lead_s * FS))

    def pad(x):  # same lead-in and length for every file, peak at -1 dBFS
        y = np.zeros(L)
        y[lead: lead + len(x)] = x / (np.max(np.abs(x)) or 1.0) * 10 ** (-1 / 20)
        return y

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "targets").mkdir(parents=True)
    key_dir.mkdir(parents=True, exist_ok=True)
    key = {"seed": seed, "length_samples": L, "lead_in_s": lead_s, "samples": {}}
    for i, j in enumerate(order):
        t = tests[j]
        name = f"sample_{i + 1:02d}.wav"
        sf.write(out_dir / name, pad(sig[t][0]), FS, subtype="PCM_24")  # PCM: no PEAK chunk
        key["samples"][name] = {"test": t, "title": TEST_TITLE[t], "run_id": acc[t]["run_id"],
                                "source": f"listen/{tag[t]}_echo_only.wav"}
    tnames = []
    for t in tests:  # target choices under descriptive names (no link to sample numbers)
        nm = TEST_TITLE[t].lower().replace('"', "").replace(",", "").replace(" ", "_") + ".wav"
        sf.write(out_dir / "targets" / nm, pad(sig[t][1]), FS, subtype="PCM_24")
        tnames.append(nm)
    export.write_json(key_dir / "key.json", key, indent=1)
    (key_dir / "README.md").write_text("# Blind test answer key\n\nKeep this folder away from listeners until the "
                                       "tally is done. `key.json` maps each sample to its test and run.\n")
    lines = ["# Blind listening test", "",
             f"{len(tests)} echoes (`sample_01.wav` ... `sample_{len(tests):02d}.wav`), the echo alone at full volume, "
             f"one per test (the runs the owner heard), shuffled with a fixed seed. Every sample and every target is "
             f"padded to the same length ({L / FS:.2f} s, {lead_s:g} s lead-in) so duration gives nothing away. "
             "The answer key is NOT in this folder: it is in `../blind_test_key/`. Do not hand that folder to "
             "listeners.", "",
             "Protocol. Play each sample to someone who has not seen or heard the targets. First ask \"what do you "
             "hear?\" and write the answer down verbatim. Then play the target sounds in "
             f"`targets/` ({len(tests)} files, listed alphabetically below) and ask \"which of these {len(tests)} "
             "sounds is it?\" (one choice; \"none\" allowed). Repeat for every sample in a fresh random order, with "
             "no feedback in between. Tally the open answers that name the target and the closed-set choices that "
             f"are correct (chance is 1/{len(tests)} per sample). The owner's earlier verdict was not blind: the "
             "listener knew each target.", "", "Targets:", ""] + [f"- `targets/{n}`" for n in sorted(tnames)]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n")
    return key


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--regen-controls", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the study, write nothing")
    ap.add_argument("--calibrate", action="store_true", help="tonal tests only: print derived vs frozen, write nothing")
    ap.add_argument("--runs-root", default=None)
    a = ap.parse_args(argv)
    if a.regen_controls:
        regen_control_words()
        return
    blocks, tests_out = study(a.runs_root, calibrate=a.calibrate,
                              tests=list(__import__("echo.metrics_v2").metrics_v2.TONAL) if a.calibrate else None)
    if a.dry_run or a.calibrate:
        for t, v in tests_out.items():
            print(t, v["established"], v["accepted"], v["perfect_echo"]["values"], v["margin"]["pitch"],
                  [(c["name"], c["pass"], c["values"]) for c in v["controls"]])
        return
    write_run_blocks(blocks)
    if a.runs_root is None:
        write_summary(blocks, tests_out)
        make_blind_test([b["run"] for b in blocks.values()])


if __name__ == "__main__":
    main()
