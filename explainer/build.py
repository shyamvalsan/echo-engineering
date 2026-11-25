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


def run_entry(runs_dir: Path, rec: dict, problems: list) -> dict:
    d = runs_dir / rec.get("path", f"{rec.get('stage')}/{rec.get('run_id')}")
    man = read_json(d / "manifest.json") or {}
    met = read_json(d / "metrics.json")
    scene = read_json(d / "scene.json")
    if met is None:
        problems.append(f"{d}: metrics.json missing or unreadable")
    head = (met or {}).get("headline") or {}
    metrics = [
        {k: m.get(k) for k in ("id", "label", "value", "unit", "threshold", "comparator", "pass", "tier")}
        for m in (met or {}).get("metrics", [])
        if m.get("gating")
    ]
    robust = (met or {}).get("robustness") or []
    gating_ids = [m["id"] for m in metrics]
    shape = {m.get("tier"): m.get("value") for m in (met or {}).get("metrics", []) if m.get("id") == "spec_corr"}
    floor = ((met or {}).get("judge_floor") or {}).get("mean") or {}
    posts = (scene or {}).get("posts") or []
    step = max(1, -(-len(posts) // MAX_POSTS))
    audio = {}
    for key, fname in (("target", "target.wav"), ("echo", "echo_tier1.wav"), ("echo0", "echo_tier0.wav"),
                       ("as_heard", "as_heard.wav")):
        b = wav_b64(d / fname)
        if b:
            audio[key] = b
    if "echo" not in audio and "echo0" in audio:
        audio["echo"], audio["echo_is_tier0"] = audio["echo0"], True
    audio.pop("echo0", None)
    return {
        "stage": rec.get("stage"),
        "run_id": rec.get("run_id"),
        "title": man.get("title") or rec.get("title"),
        "created": man.get("created") or rec.get("created"),
        "has_metrics": met is not None,
        "passed": (met or {}).get("passed", rec.get("passed")),
        "verified": (met or {}).get("verified", man.get("verified", rec.get("verified"))),
        "fragile": (met or {}).get("fragile"),
        "failure_cause": (met or {}).get("failure_cause"),
        "tier1": (man.get("solver") or {}).get("tier1"),
        "headline": {k: head.get(k) for k in ("echo_level_db_re_direct", "echo_spl_db", "depth_m", "post_count",
                                              "tier_gap_db")},
        "metrics": metrics,
        "shape": {"tier0": shape.get("tier0"), "tier1": shape.get("tier1")},
        "judge_floor": {k: floor.get(k) for k in gating_ids if isinstance(floor.get(k), (int, float))},
        "caveats": [str(c) for c in ((met or {}).get("caveats") or [])],
        "fragile_reason": (met or {}).get("fragile_reason"),
        "robust": [{"case": r.get("case"), "label": r.get("label"), "pass": r.get("pass"),
                    "m": {k: (r.get("metrics") or {}).get(k) for k in gating_ids}} for r in robust],
        "scene": None if scene is None else {
            "wedge": scene.get("wedge"),
            "source": scene.get("source"),
            "listener": scene.get("listener"),
            "posts": [[round(p[0], 3), round(p[1], 3), p[2]] for p in posts[::step]],
        },
        "audio": audio,
    }


def results(runs_dir: Path):
    problems: list[str] = []
    index = read_json(runs_dir / "index.json")
    recs = (index or {}).get("runs") or []
    finals: dict[str, dict] = {}  # newest final per stage id
    older: dict[str, list] = {}  # earlier finals per stage id, newest first
    for rec in sorted(recs, key=lambda r: str(r.get("created", "")), reverse=True):
        if rec.get("status") != "final" or not rec.get("stage"):
            continue
        if rec["stage"] in finals:
            older.setdefault(rec["stage"], []).append(rec)
        else:
            finals[rec["stage"]] = rec

    def entry(s):
        e = run_entry(runs_dir, finals[s], problems)
        e["earlier"] = []
        for rec in older.get(s, []):
            o = run_entry(runs_dir, rec, problems)
            e["earlier"].append({k: o[k] for k in ("title", "created", "has_metrics", "passed", "verified",
                                                   "failure_cause", "metrics", "headline")})
        return e
    groups = []
    claimed = set()
    for prefix, sid, name, blurb in STAGES:
        ids = sorted(s for s in finals if s == sid or (s.startswith(prefix) and s not in claimed))
        claimed.update(ids)
        others = [r for r in recs if r.get("status") != "final" and str(r.get("stage", "")).startswith(prefix)]
        latest = max(others, key=lambda r: str(r.get("created", "")), default=None)
        groups.append({"key": sid, "name": name, "blurb": blurb,
                       "latest_other": latest.get("status") if latest else None,
                       "runs": [entry(s) for s in ids]})
    for s in sorted(set(finals) - claimed):
        groups.append({"key": s, "name": s, "blurb": "", "runs": [entry(s)]})
    return {"index_found": index is not None, "groups": groups, "problems": problems}


def status_line(res) -> str:
    """One quiet line for the top of the page, from the newest final runs."""
    if not res["index_found"]:
        return "Interim: the simulations are still running; no stage has a result yet."
    main4 = res["groups"][:4]
    done = sum(1 for g in main4 if g["runs"])
    head = "Interim" if done < len(main4) else "Results"
    bird = main4[0]["runs"][0] if main4[0]["runs"] else None
    if bird is None:
        tail = "the bird whistle is still being simulated."
    elif bird.get("passed") and bird.get("verified"):
        tail = "the bird whistle passed on the careful simulator."
    elif bird.get("passed"):
        tail = "the bird whistle passed on the fast simulator only, not yet on the careful one."
    elif bird.get("earlier"):
        tail = f"the bird whistle has not passed yet ({len(bird['earlier']) + 1} attempts so far)."
    else:
        tail = "the bird whistle has not passed yet."
    return f"{head}: {done} of {len(main4)} stages simulated; {tail}"


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
    data["status"] = status_line(data["results"])
    data = clean(data)
    src = HERE / "src"
    html = (src / "template.html").read_text()
    blob = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    html = (html.replace("/*__CSS__*/", (src / "style.css").read_text())
                .replace("/*__DATA__*/", "window.ECHO_DATA=" + blob + ";")
                .replace("/*__JS__*/", (src / "main.js").read_text()))
    out.write_text(html)
    n_final = sum(len(g["runs"]) for g in data["results"]["groups"])
    print(data["status"])
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB), {n_final} final run(s) from {runs_dir}")
    for p in data["results"]["problems"]:
        print("  problem:", p)


if __name__ == "__main__":
    main()
