"""Build a scratch runs folder that exercises every verdict state and the build robustness cases.

Usage:
    uv run python explainer/make_fixture.py            # writes explainer/_fixture_runs/ (gitignored)
    uv run python explainer/build.py --runs explainer/_fixture_runs --out explainer/_test_verdicts.html

Starts from viewer/fixtures/runs (made-up numbers) and adds:
- s1 final: strict miss, revised True, listening verdict (featured card);
- s2 two finals: the older carries the listening verdict, the newer revised None ("not established");
- s4 "ma": strict True with revised False (the "passes" and "not passed" states);
- s4 "ah": no `criteria` and no `listening_verdict` keys at all (an old run);
- custom/ and build_pilot/ finals (must not show as tests); no listen/ folder.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "viewer" / "fixtures" / "runs"
OUT = HERE / "_fixture_runs"

LV = {"by": "owner", "date": "2026-11-25", "verdict": "pass", "blind": False, "quote": "fixture quote"}


def crit(strict, revised, metrics=None):
    return {"spec_v1": {"passed": strict, "gating": []},
            "owner_v2": {"passed": revised, "rests_on": "fixture", "metrics": metrics or [],
                         "controls": [{"name": "c1", "pass": False}, {"name": "c2", "pass": False}]}}


def clone(src_rel, stage, run_id, title, created, metrics_patch, man_patch=None):
    d = OUT / stage / run_id
    shutil.copytree(SRC / src_rel, d)
    m = json.loads((d / "metrics.json").read_text())
    m.update(metrics_patch)
    (d / "metrics.json").write_text(json.dumps(m))
    man = json.loads((d / "manifest.json").read_text())
    man.update({"title": title, "created": created, **(man_patch or {})})
    (d / "manifest.json").write_text(json.dumps(man))
    return {"stage": stage, "run_id": run_id, "path": f"{stage}/{run_id}", "title": title, "created": created,
            "status": "final", "passed": m.get("passed"), "verified": True}


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    bird, motif = "s1_bird/20261124-2310-fx-final", "s2_motif/20261125-0105-fx-failed"
    idx = [
        clone(bird, "s1_bird", "20261125-1000-fx-s1", "Bird (fixture)", "2026-11-25T10:00:00+02:00",
              {"passed": False, "criteria": crit(False, True, [{"id": "id_claps", "value": 5, "threshold": 3},
                                                                {"id": "pitch_cents", "value": 13, "threshold": 40}]),
               "listening_verdict": LV}),
        clone(motif, "s2_motif", "20261125-1100-fx-s2", "Motif v1 (fixture)", "2026-11-25T11:00:00+02:00",
              {"criteria": crit(False, None), "listening_verdict": LV}),
        clone(motif, "s2_motif", "20261125-1200-fx-s2v2", "Motif v2 (fixture)", "2026-11-25T12:00:00+02:00",
              {"criteria": crit(False, None)}),
        clone(motif, "s4_speech", "20261125-1300-fx-s4_4b_ma", "Speech 4b: ma (fixture)", "2026-11-25T13:00:00+02:00",
              {"criteria": crit(True, False), "listening_verdict": LV}, {"substage": "4b", "target_name": "ma"}),
        clone(motif, "s4_speech", "20261125-1400-fx-s4_4a_ah", "Speech 4a: ah (fixture)", "2026-11-25T14:00:00+02:00",
              {}, {"substage": "4a", "target_name": "ah"}),
        clone(bird, "custom", "20261125-1500-fx-custom", 'Custom: "beep" (fixture)', "2026-11-25T15:00:00+02:00", {}),
        clone(bird, "build_pilot", "20261125-1600-fx-pilot", "Pilot (fixture)", "2026-11-25T16:00:00+02:00", {}),
    ]
    for p in (OUT / "s4_speech" / "20261125-1400-fx-s4_4a_ah" / "metrics.json",):
        m = json.loads(p.read_text())
        m.pop("criteria", None)
        m.pop("listening_verdict", None)
        p.write_text(json.dumps(m))
    (OUT / "index.json").write_text(json.dumps({"runs": idx}))
    print(f"wrote {OUT} with {len(idx)} final runs")


if __name__ == "__main__":
    main()
