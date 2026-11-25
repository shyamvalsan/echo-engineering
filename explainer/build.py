"""Assemble the lay-person explainer: explainer/src/{template.html,style.css,main.js} + data -> explainer/index.html.

Usage:
    uv run python explainer/build.py                                  # real runs from runs/, writes explainer/index.html
    uv run python explainer/build.py --runs viewer/fixtures/runs      # test build from fixtures, writes
                                                                      # explainer/_test_index.html (gitignored)

The page is fully self-contained: CSS, JS, the project's real clap family and stage 1-3 targets, and the results
of final runs (headline numbers, gating metrics, post layout and short WAVs as base64) are embedded inline.
Missing or broken run folders never stop the build; the affected stage shows "simulation still running" or the
problem in plain words.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from echo.clap import clap_family, clap_params  # noqa: E402
from echo.targets import bird_note, melody, motif  # noqa: E402

# Display order and plain-language framing for the stages the spec defines. Run folders whose stage id starts
# with a key's prefix (e.g. "s4a_vowel" under "s4") are shown as that stage's sub-stages.
STAGES = [
    ("s1", "s1_bird", "A bird note", "A falling whistle, 3.5 kHz down to 2 kHz, 80 ms long."),
    ("s2", "s2_motif", "Four notes", "C, E, G, high C, 45 ms each: a bugle-like arpeggio."),
    ("s3", "s3_melody", "A tune", "The first eight notes of Ode to Joy, 100 ms each (and a faster 60 ms try)."),
    ("s4", "s4_speech", "Speech", "A sustained \"ah\", the syllables \"ma\", \"ba\", \"om\", then the word \"hello\"."),
]
MAX_POSTS = 4000  # posts drawn per card; more are subsampled evenly (count shown is the true count)
MAX_WAV_BYTES = 600_000


def rounded(x, nd=4):
    return [round(float(v), nd) for v in x]


def signals():
    claps = clap_family(5)
    return {
        "fs": 16000,
        "claps": [rounded(c) for c in claps],
        "clap_params": clap_params(5),
        "targets": {
            "bird": rounded(bird_note().audio),
            "motif": rounded(motif().audio),
            "melody": rounded(melody().audio),
        },
    }


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - any unreadable file is reported as missing
        return None


def wav_b64(path: Path):
    try:
        b = path.read_bytes()
    except OSError:
        return None
    if len(b) > MAX_WAV_BYTES:
        return None
    return base64.b64encode(b).decode("ascii")


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _fade_db(met):
    """Fade along the field, from the first correction round's per-window gains (clipped at 0.5 and 2)."""
    rounds = ((met or {}).get("tier1_correction") or {}).get("rounds") or []
    g = [v for v in ((rounds[0].get("gains_next") if rounds else None) or [])[:-1] if _num(v)]
    if len(g) < 2 or min(g) <= 0:
        return None
    return {"db": round(20 * math.log10(max(g) / min(g)), 1), "clipped": min(g) <= 0.5 and max(g) >= 2.0}


def _extinction_file(runs_dir: Path, stage: str, run_id: str):
    """Measured fade at the last note, from a stage's extinction study when it names this run."""
    for f in sorted((runs_dir / stage / "_studies").glob("*extinction*.json")) if stage else []:
        d = read_json(f) or {}
        if d.get("run") == run_id and d.get("rows"):
            v = _num(d["rows"][-1].get("measured_tier1_minus_tier0_db_clap0"))
            if v is not None:
                return round(-v, 1)
    return None


def run_tag(run_id) -> str:
    """'20261125-104529-s1' -> 's1' (the tag listen/ uses for a run)."""
    parts = str(run_id or "").split("-", 2)
    return parts[2] if len(parts) == 3 else str(run_id or "")


def _tri(x):
    return x if x is True or x is False else None


def criteria_of(m: dict) -> dict:
    """The three separate verdicts of one run, tolerating runs scored before the criteria keys existed.

    strict: criteria.spec_v1.passed (else the top-level `passed`, which is spec_v1); revised: criteria.owner_v2.passed
    (True / False / None = "not established"), `revised_scored` False when the key is absent; ear: the recorded
    listening verdict on this run, if any."""
    crit = m.get("criteria") if isinstance(m.get("criteria"), dict) else {}
    v1 = crit.get("spec_v1") if isinstance(crit.get("spec_v1"), dict) else None
    v2 = crit.get("owner_v2") if isinstance(crit.get("owner_v2"), dict) else None
    lv = m.get("listening_verdict") if isinstance(m.get("listening_verdict"), dict) else None
    ctrl = (v2 or {}).get("controls") or []
    return {
        "strict": _tri(v1.get("passed")) if v1 else (_tri(m.get("passed")) if m else None),
        "revised_scored": v2 is not None,
        "revised": _tri(v2.get("passed")) if v2 else None,
        "revised_note": (v2 or {}).get("note"),
        "revised_rests_on": (v2 or {}).get("rests_on"),
        "revised_metrics": [{k: x.get(k) for k in ("id", "value", "threshold", "used")}
                            for x in ((v2 or {}).get("metrics") or [])],
        "controls_total": len(ctrl) if v2 else None,
        "controls_rejected": sum(1 for c in ctrl if c.get("pass") is False) if v2 else None,
        "ear": None if not lv else {"verdict": lv.get("verdict"), "by": lv.get("by"), "date": lv.get("date"),
                                    "blind": lv.get("blind"), "quote": lv.get("quote")},
    }


def run_entry(runs_dir: Path, rec: dict, problems: list, light: bool = False) -> dict:
    d = runs_dir / rec.get("path", f"{rec.get('stage')}/{rec.get('run_id')}")
    man = read_json(d / "manifest.json") or {}
    met = read_json(d / "metrics.json")
    if met is None:
        problems.append(f"{d}: metrics.json missing or unreadable")
    m = met or {}
    head = m.get("headline") or {}
    metrics = [{k: x.get(k) for k in ("id", "label", "value", "unit", "threshold", "comparator", "pass", "tier")}
               for x in m.get("metrics", []) if x.get("gating")]
    gating_ids = [x["id"] for x in metrics]
    allm = [{"id": x.get("id"), "tier": x.get("tier"), "value": x.get("value")} for x in m.get("metrics", [])
            if x.get("tier") in ("tier0", "tier1") and (_num(x.get("value")) is not None or x.get("value") is None)]
    shape = {x.get("tier"): x.get("value") for x in m.get("metrics", []) if x.get("id") == "spec_corr"}
    floor = (m.get("judge_floor") or {}).get("mean") or {}
    cfg = ((man.get("design") or {}).get("config") or {})
    e = {
        "stage": rec.get("stage"),
        "run_id": rec.get("run_id"),
        "path": rec.get("path", f"{rec.get('stage')}/{rec.get('run_id')}"),
        "title": man.get("title") or rec.get("title"),
        "created": man.get("created") or rec.get("created"),
        "substage": man.get("substage") or m.get("substage"),
        "target_name": man.get("target_name") or m.get("target_name"),
        "has_metrics": met is not None,
        "passed": m.get("passed", rec.get("passed")),
        "verified": m.get("verified", man.get("verified", rec.get("verified"))),
        "failure_cause": m.get("failure_cause"),
        "metrics": metrics,
        "allm": allm,
        "headline": {k: head.get(k) for k in ("echo_level_db_re_direct", "echo_spl_db", "depth_m", "post_count",
                                              "tier_gap_db")},
        "crit": criteria_of(m),
        "tag": run_tag(rec.get("run_id")),
    }
    if light:
        e["design"] = {"realization": cfg.get("realization") or "sampling", "stretch": bool(cfg.get("stretch_comp"))}
        e["floor"] = {k: v for k, v in floor.items() if _num(v) is not None}
        return e
    robust = m.get("robustness") or []
    rid = [x["id"] for x in metrics] + [x["id"] for x in m.get("metrics", [])
                                        if x.get("tier") == "tier1" and x.get("id") in ("estoi", "hello_hit")]
    rid = list(dict.fromkeys(rid))
    s3 = m.get("s3_extra") or {}
    lam = s3.get("level_along_melody") or {}
    diag = m.get("diagnosis") or {}
    jd = diag.get("judge_detected") or {}
    heard = [_num(n.get("hz")) for n in (jd.get("tier1_clap0") or []) if _num(n.get("hz"))]
    want = [_num(h) for h in (jd.get("target_hz") or []) if _num(h)]
    ds = m.get("design_study") or {}
    nls = ((ds.get("note_length_sweep") or {}).get("answer")) or {}
    fw = ds.get("fullwedge_tier0") or {}
    fw_pick = None
    if isinstance(fw.get("picked"), int) and 0 <= fw["picked"] < len(fw.get("rows") or []):
        row = fw["rows"][fw["picked"]]
        judge = row.get("info_only_note_judge_full_band") or {}
        fw_pick = {"n_posts": _num(row.get("n_posts")), "in_order": _num(judge.get("notes_in_order")),
                   "n_claps": len(judge.get("per_clap_in_order") or [])}
    attr = (((m.get("ablations") or {}).get("attribution") or {}).get("metric_columns") or {}).get("loss") or {}
    largest = max(attr, key=lambda k: attr[k].get("gain_when_removed_alone") or 0) if attr else None
    ctrl = (m.get("recognizer_controls") or {}).get("cases") or {}
    band = m.get("band_hz") or [None, (s3.get("grid_and_domain") or {}).get("f_max_hz")
                                or (man.get("solver") or {}).get("f_max")]
    e.update({
        "fragile": m.get("fragile"),
        "fragile_reason": m.get("fragile_reason"),
        "robust_summary": m.get("robust_summary"),
        "shape": {"tier0": shape.get("tier0"), "tier1": shape.get("tier1")},
        "judge_floor": {k: v for k, v in floor.items() if _num(v) is not None},
        "caveats": [str(c) for c in (m.get("caveats") or man.get("caveats") or [])],
        "robust": [{"case": r.get("case"), "label": r.get("label"), "pass": r.get("pass"),
                    "m": {k: (r.get("metrics") or {}).get(k) for k in rid}} for r in robust],
        "design": {"radius_m": _num(cfg.get("a_ref")), "half_angle_deg": _num(cfg.get("half_angle_deg")),
                   "catalog": cfg.get("catalog"), "realization": cfg.get("realization") or "sampling",
                   "strip_half_width_m": _num(cfg.get("max_half_width_m")),
                   "stretch": bool(cfg.get("stretch_comp"))},
        "f_top_hz": _num(band[1]) if len(band) > 1 else None,
        "fade": _fade_db(m),
        "extinction_last_db": _extinction_file(runs_dir, rec.get("stage"), rec.get("run_id")),
        "level_along": None if not lam.get("spl_db") else {
            "spl_db": [round(v, 1) for v in lam["spl_db"] if _num(v) is not None],
            "below_35": len(lam.get("notes_below_35_db_spl") or [])},
        "heard_hz": [min(heard), max(heard)] if heard else None,
        "want_hz": [min(want), max(want)] if want else None,
        "note_sweep": None if not nls else {"perfect_ms": nls.get("shortest_note_ms_perfect_echo_transcribes_all_claps"),
                                           "design_ms": nls.get("shortest_note_ms_realized_design_transcribes_all_claps")},
        "full_fan": fw_pick,
        "largest_cost": largest,
        "loss_chain": m.get("loss_chain"),
        "recognized": [str(t.get("transcript", "")) for t in (m.get("recognized_text") or [])],
        "controls": None if not ctrl else {"n": len(ctrl), "names": list(ctrl),
                                           "hits": sum(int(c.get("hello_count") or 0) for c in ctrl.values())},
    })
    scene = read_json(d / "scene.json")
    posts = (scene or {}).get("posts") or []
    step = max(1, -(-len(posts) // MAX_POSTS))
    e["scene"] = None if scene is None else {"posts": [[round(p[0], 3), round(p[1], 3), p[2]] for p in posts[::step]]}
    audio = {}
    for key, fname in (("target", "target.wav"), ("echo", "echo_tier1.wav"), ("echo0", "echo_tier0.wav"),
                       ("as_heard", "as_heard.wav")):
        b = wav_b64(d / fname)
        if b:
            audio[key] = b
    if "echo" not in audio and "echo0" in audio:
        audio["echo"], audio["echo_is_tier0"] = audio["echo0"], True
    audio.pop("echo0", None)
    e["audio"] = audio
    return e


SUB_HEADINGS = {"4a": 'A vowel, "ah"', "4b": 'Three syllables: "ma", "ba", "om"', "4c": 'A word: "hello"',
                "100ms": "100 ms notes", "60ms": "60 ms notes"}


def _variant(rec, man):
    """(sub-stage key, target key) of a run: speech sub-stage and target, or the melody's note length."""
    sub = man.get("substage")
    if sub:
        return str(sub), str(man.get("target_name") or "")
    rid = str(rec.get("run_id", ""))
    if rec.get("stage", "").startswith("s3"):
        return ("60ms" if rid.endswith("_60ms") else "100ms"), ""
    return "", ""


def is_test_stage(stage: str) -> bool:
    """Stages shown as tests. Build pilots, custom designs, validation and helper folders are not tests."""
    st = str(stage)
    return not (st.startswith(("_", "build", "custom", "validation")))


def results(runs_dir: Path):
    problems: list[str] = []
    index = read_json(runs_dir / "index.json")
    recs = (index or {}).get("runs") or []
    keyed: dict[tuple, list] = {}  # (stage id, sub, target) -> finals, newest first
    for rec in sorted(recs, key=lambda r: str(r.get("created", "")), reverse=True):
        if rec.get("status") != "final" or not rec.get("stage") or not is_test_stage(rec["stage"]):
            continue
        man = read_json(runs_dir / rec.get("path", "") / "manifest.json") or {}
        sub, tgt = _variant(rec, man)
        keyed.setdefault((rec["stage"], sub, tgt), []).append(rec)

    def entry(recs_newest_first):
        e = run_entry(runs_dir, recs_newest_first[0], problems)
        e["earlier"] = [run_entry(runs_dir, r, problems, light=True) for r in recs_newest_first[1:]]
        return e

    def subs_for(keys):
        subs = {}
        for k in sorted(keys, key=lambda k: (k[1] != "100ms", k[1], k[2] not in ("ma",), k[2])):
            subs.setdefault(k[1], []).append(entry(keyed[k]))
        order = sorted(subs, key=lambda s: ({"100ms": 0, "60ms": 1}.get(s, 2), s))
        return [{"key": s, "heading": SUB_HEADINGS.get(s, s), "entries": subs[s]} for s in order]

    groups, claimed = [], set()
    for prefix, sid, name, blurb in STAGES:
        keys = [k for k in keyed if k[0] == sid or (k[0].startswith(prefix) and k not in claimed)]
        claimed.update(keys)
        others = [r for r in recs if r.get("status") != "final" and str(r.get("stage", "")).startswith(prefix)
                  and is_test_stage(r.get("stage", ""))]
        latest = max(others, key=lambda r: str(r.get("created", "")), default=None)
        groups.append({"key": sid, "name": name, "blurb": blurb,
                       "latest_other": latest.get("status") if latest else None, "subs": subs_for(keys)})
    for k in sorted(set(keyed) - claimed):
        groups.append({"key": k[0], "name": k[0], "blurb": "", "subs": subs_for([k])})
    return {"index_found": index is not None, "groups": groups, "problems": problems}


def calibration(runs_dir: Path, res, problems):
    """The two real fades for the 'thicker air' cartoon: the first final design of stage 1 and of stage 2.

    Fade = the measured last-note loss from the stage's extinction study when there is one for that run,
    else the spread of the first correction round's per-window gains (a lower bound when clipped)."""
    pts = []
    for g in res["groups"][:2]:
        runs = [x for s in g["subs"] for e in s["entries"] for x in [e] + e["earlier"]]
        if not runs:
            continue
        first = min(runs, key=lambda x: str(x.get("created", "")))
        e = run_entry(runs_dir, {"stage": first["stage"], "run_id": first["run_id"], "path": first["path"]}, problems)
        ext = e.get("extinction_last_db")
        fade = e.get("fade") or {}
        loss = ext if ext is not None else fade.get("db")
        des, hd = e.get("design") or {}, e.get("headline") or {}
        if loss is None or not des.get("radius_m") or not des.get("half_angle_deg") or not hd.get("depth_m"):
            continue
        pts.append({"stage": g["key"], "name": g["name"], "run_id": e["run_id"], "loss_db": loss,
                    "source": "last-note loss measured against the fast model" if ext is not None
                    else "fade across the echo, from the first correction round",
                    "at_least": ext is None and bool(fade.get("clipped")),
                    "radius_m": des["radius_m"], "half_angle_deg": des["half_angle_deg"], "depth_m": hd["depth_m"]})
    return pts


def build_pilot(runs_dir: Path):
    """Headline numbers of the newest build_pilot run, if one exists."""
    best = None
    for f in sorted((runs_dir / "build_pilot").glob("*/manifest.json")):
        man = read_json(f) or {}
        if best is None or str(man.get("created", "")) > str(best[0].get("created", "")):
            best = (man, read_json(f.parent / "metrics.json") or {})
    if best is None:
        return None
    man, met = best
    h = met.get("headline") or {}
    return {"title": man.get("title"), "created": man.get("created"), "passed": met.get("passed"),
            "verified": met.get("verified"), "depth_m": h.get("depth_m"), "post_count": h.get("post_count"),
            "echo_spl_db": h.get("echo_spl_db")}


TEST_NAMES = {"s1_bird": "the whistle", "s2_motif": "the four notes", "100ms": "the tune (100 ms notes)",
              "60ms": "the tune (60 ms notes)", "4a": 'the vowel "ah"', "4c": '"hello"'}


def scoreboard(res):
    """One test per designed target: the whistle, the four notes, each note length of the tune, and each speech target.

    Each test carries three separate verdicts, never merged: strict (spec_v1, on the newest final run), revised
    (owner_v2, on the newest final run: True / False / None = not established; `revised_scored` False when no run of
    the test has the key) and ear (the listening verdict recorded on any final run of the test, with the run it is on)."""
    out = []
    for g in res["groups"][:4]:
        for s in g["subs"]:
            for e in s["entries"]:
                runs = [e] + list(e.get("earlier") or [])
                key = s["key"] if s["key"] else g["key"]
                tname = e.get("target_name")
                if s["key"] == "4b" and tname:
                    name = f'the syllable "{tname}"'
                else:
                    name = TEST_NAMES.get(key) or (f'"{tname}"' if tname else (s["heading"] or g["name"]))
                c = e.get("crit") or {}
                ear_run = next((r for r in runs if (r.get("crit") or {}).get("ear")), None)
                ear = (ear_run or {}).get("crit", {}).get("ear") if ear_run else None
                out.append({
                    "key": key, "group": g["key"], "run_id": e.get("run_id"), "name": name,
                    "strict": c.get("strict") if e.get("has_metrics") else None,
                    "revised_scored": bool(c.get("revised_scored")),
                    "revised": c.get("revised"),
                    "ear": None if not ear else ear.get("verdict"),
                    "ear_blind": None if not ear else ear.get("blind"),
                    "ear_run": None if not ear_run else ear_run.get("run_id"),
                    "ear_on_newest": bool(ear_run) and ear_run is e,
                    "n_designs": len(runs),
                })
    return out


def verdict_counts(tests):
    n = len(tests)
    strict = [t for t in tests if t["strict"] is True]
    scored = [t for t in tests if t["revised_scored"]]
    rev_yes = [t for t in scored if t["revised"] is True]
    rev_no = [t for t in scored if t["revised"] is False]
    rev_null = [t for t in scored if t["revised"] is None]
    ear = [t for t in tests if t["ear"] == "pass"]
    blind = any(t["ear_blind"] for t in ear)
    return {"n": n, "strict": [t["name"] for t in strict], "revised_scored": len(scored),
            "revised_yes": [t["name"] for t in rev_yes], "revised_no": [t["name"] for t in rev_no],
            "revised_null": [t["name"] for t in rev_null], "ear": [t["name"] for t in ear], "ear_blind": blind}


def _join(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def status_line(res, counts) -> str:
    """One quiet line for the top of the page: the three verdicts, each in its own words."""
    if not res["index_found"]:
        return "Interim: the simulations are still running; no test has a result yet."
    n = counts["n"]
    if not n:
        return "Interim: no test has a final result yet."
    bits = [f"{n} echoes designed and simulated."]
    ear = counts["ear"]
    if ear:
        who = "all" if len(ear) == n else f"{len(ear)} of"
        bits.append(f"By ear: {who} {n} accepted ({'blind' if counts['ear_blind'] else 'the owner, who knew each target; not a blind test'}).")
    st = counts["strict"]
    bits.append(f"Strict tests set beforehand: {len(st)} of {n} pass{'es' if len(st) == 1 else ''}"
                f"{' (' + _join(st) + ')' if st and len(st) < 4 else ''}.")
    if counts["revised_scored"]:
        y, nn, no = counts["revised_yes"], counts["revised_null"], counts["revised_no"]
        tail = [f"{len(y)} confirmed" + (f" ({_join(y)})" if y and len(y) < 4 else "")]
        if no:
            tail.append(f"{len(no)} not passed")
        if nn:
            tail.append(f"{len(nn)} not established")
        if counts["revised_scored"] < n:
            tail.append(f"{n - counts['revised_scored']} not scored yet")
        bits.append("Revised tests: " + ", ".join(tail) + ".")
    return " ".join(bits)


def listen_levels(root: Path):
    """listen/README.md table: run tag -> true echo level re clap (dB) and the boost used in the boosted file."""
    try:
        text = (root / "listen" / "README.md").read_text()
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not cells[2].startswith("`"):
            continue
        try:
            out[cells[2].strip("`")] = {"true_db": float(cells[3]), "boost_db": float(cells[4])}
        except ValueError:
            continue
    return out


def whistle_audio(root: Path, runs_dir: Path, res, levels):
    """The featured whistle: the newest final stage-1 run, with listen/ files when they exist (else the run's own)."""
    g = next((g for g in res["groups"] if g["key"] == "s1_bird"), None)
    if not g or not g["subs"] or not g["subs"][0]["entries"]:
        return None
    e = g["subs"][0]["entries"][0]
    tag = e.get("tag") or ""
    run_dir = runs_dir / e["path"]
    audio = {}
    for key, f in (("target", root / "listen" / f"{tag}_target.wav"), ("echo", root / "listen" / f"{tag}_echo_only.wav"),
                   ("boosted", root / "listen" / f"{tag}_clap_then_echo_boosted.wav"), ("true", run_dir / "as_heard.wav")):
        b = wav_b64(f)
        if b:
            audio[key] = b
    for key, fallback in (("target", "target.wav"), ("echo", "echo_tier1.wav")):
        if key not in audio:
            b = wav_b64(run_dir / fallback)
            if b:
                audio[key] = b
    lv = levels.get(tag) or {}
    return {"run_id": e.get("run_id"), "audio": audio, "true_db": lv.get("true_db"),
            "boost_db": lv.get("boost_db") if "boosted" in audio else None}


def custom_example(runs_dir: Path):
    """The newest structure designed from a supplied sound (runs/custom), if any."""
    best = None
    for f in sorted((runs_dir / "custom").glob("*/manifest.json")):
        man = read_json(f) or {}
        if best is None or str(man.get("created", "")) > str(best[0].get("created", "")):
            best = (man, read_json(f.parent / "metrics.json") or {})
    if best is None:
        return None
    man, met = best
    h = met.get("headline") or {}
    return {"title": man.get("title"), "verified": man.get("verified", met.get("verified")),
            "depth_m": _num(h.get("depth_m")), "post_count": _num(h.get("post_count")),
            "echo_spl_db": _num(h.get("echo_spl_db"))}


def build_costs(root: Path):
    """Cost column of BUILD.md's decision ladder, by phase id (e.g. '3a' -> '~€0.2–0.5k (est.)')."""
    try:
        text = (root / "BUILD.md").read_text()
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and cells[0][:2] in ("2a", "2b", "2c", "3a", "3b", "4.") and "€" in cells[2]:
            out[cells[0][:2].rstrip(".")] = cells[2]
    return out


def live_image(root: Path):
    """One Live-mode screenshot as an inline JPEG data URI (about 1000 px wide), or None."""
    src = root / "artifacts" / "viewer" / "live-lab-replay.png"
    if not src.exists():
        cands = sorted((root / "artifacts" / "viewer").glob("live-*replay*.png"))
        if not cands:
            return None
        src = cands[0]
    try:
        import io

        from PIL import Image
        im = Image.open(src).convert("RGB")
        w = 1100
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=72, optimize=True, progressive=True)
        return {"uri": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"),
                "w": im.width, "h": im.height}
    except Exception:  # noqa: BLE001 - the page works without the picture
        return None


def clean(x):
    """Replace non-finite floats with None so the embedded JSON is always valid."""
    if isinstance(x, float):
        return x if x == x and abs(x) != float("inf") else None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    return x


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", default="runs", help="runs directory (default: runs)")
    ap.add_argument("--out", default=None, help="output HTML (default: explainer/index.html for real runs, "
                                                "explainer/_test_index.html for any other runs dir)")
    a = ap.parse_args(argv)
    runs_dir = (ROOT / a.runs).resolve()
    real = runs_dir == (ROOT / "runs").resolve()
    out = Path(a.out) if a.out else HERE / ("index.html" if real else "_test_index.html")

    data = {
        "built": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        "source": "runs" if real else f"TEST DATA from {a.runs}",
        "test_data": not real,
        "build_md": (ROOT / "BUILD.md").exists(),
        "signals": signals(),
        "results": results(runs_dir),
    }
    data["scoreboard"] = scoreboard(data["results"])
    data["counts"] = verdict_counts(data["scoreboard"])
    data["status"] = status_line(data["results"], data["counts"])
    levels = listen_levels(ROOT) if real else {}
    data["listen"] = {"levels": levels,
                      "range": [min(v["true_db"] for v in levels.values()), max(v["true_db"] for v in levels.values())]
                      if levels else None}
    data["whistle"] = whistle_audio(ROOT, runs_dir, data["results"], levels)
    data["custom"] = custom_example(runs_dir)
    data["costs"] = build_costs(ROOT)
    data["blind_kit"] = (runs_dir / "_criteria" / "blind_test").is_dir()
    data["listening"] = next((x.get("crit", {}).get("ear") for g in data["results"]["groups"] for s in g["subs"]
                              for e in s["entries"] for x in [e] + e.get("earlier", []) if x.get("crit", {}).get("ear")), None)
    data["live_img"] = live_image(ROOT)
    data["calibration"] = calibration(runs_dir, data["results"], data["results"]["problems"])
    data["pilot"] = build_pilot(runs_dir)
    data = clean(data)
    src = HERE / "src"
    html = (src / "template.html").read_text()
    blob = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    html = (html.replace("/*__CSS__*/", (src / "style.css").read_text())
                .replace("/*__DATA__*/", "window.ECHO_DATA=" + blob + ";")
                .replace("/*__JS__*/", (src / "main.js").read_text()))
    out.write_text(html)
    n_final = sum(len(s["entries"]) for g in data["results"]["groups"] for s in g["subs"])
    print(data["status"])
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB), {n_final} final run(s) from {runs_dir}")
    for p in data["results"]["problems"]:
        print("  problem:", p)


if __name__ == "__main__":
    main()
