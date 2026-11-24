"""Open a run folder the way the viewer does (viewer/README.md) and check every field it reads. Reusable helper."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf

NUM = (int, float)


def _load(p):
    text = Path(p).read_text()
    for bad in ("NaN", "Infinity"):
        assert bad not in text, f"{p}: contains {bad}"
    return json.loads(text)


def _num_or_none(v):
    return v is None or (isinstance(v, NUM) and not isinstance(v, bool) and math.isfinite(v))


def check_run_folder(d) -> list[str]:
    """Raise AssertionError on the first contract violation; return the list of files checked."""
    d = Path(d)
    checked = []
    m = _load(d / "manifest.json")
    checked.append("manifest.json")
    assert isinstance(m.get("git_dirty", False), bool)
    for k, t in (("run_id", str), ("stage", str), ("title", str), ("created", str), ("status", str),
                 ("verified", bool), ("fs", int), ("command", str), ("notes", str), ("git_commit", str)):
        assert isinstance(m.get(k), t), f"manifest.{k}: {m.get(k)!r}"
    assert m["status"] in ("final", "intermediate", "tier0_only")
    for k in ("c", "duration_s", "t_direct_s"):
        assert isinstance(m[k], NUM) and m[k] > 0, k
    assert isinstance(m["seed"], int)
    s = m["solver"]
    assert s["tier1"] in ("kwave", "fdtd", "pstd", "none")
    for k in ("device", "dx", "dt", "grid", "f_lo", "f_max", "ppw", "wall_s"):
        assert k in s, f"solver.{k}"
    f = m["field"]
    if f is not None:
        for k in ("file", "fps", "n_frames", "t0_s", "sim_seconds_per_frame", "extent_m"):
            assert k in f, f"field.{k}"
        assert len(f["extent_m"]) == 4 and (d / f["file"]).exists()
    a = m["audio"]
    assert "tier0" in a["echo_gain_db"] and "tier1" in a["echo_gain_db"]
    assert _num_or_none(a["as_heard_echo_level_db"])

    sc = _load(d / "scene.json")
    checked.append("scene.json")
    assert sc["units"] == "m" and isinstance(sc["c"], NUM)
    assert len(sc["source"]) == 2 and len(sc["listener"]) == 2
    for k in ("half_angle_deg", "r_min", "r_max"):
        assert isinstance(sc["wedge"][k], NUM), f"wedge.{k}"
    posts = np.asarray(sc["posts"], dtype=float).reshape(-1, 3)
    assert np.all(np.isfinite(posts)) and np.all(posts[:, 2] > 0)

    p = _load(d / "profile.json")
    checked.append("profile.json")
    assert isinstance(p["r0_m"], NUM) and isinstance(p["dr_m"], NUM) and p["dr_m"] > 0
    assert len(p["reflectivity"]) > 0 and all(isinstance(v, NUM) and v >= 0 for v in p["reflectivity"])

    n = None
    wavs = ["target.wav", "echo_tier0.wav", "as_heard.wav"] + (["echo_tier1.wav"] if s["tier1"] != "none" else [])
    for w in wavs:
        x, fs = sf.read(d / w)
        assert x.ndim == 1 and fs == m["fs"], w
        assert np.all(np.isfinite(x)), w
        n = len(x) if n is None else n
        assert len(x) == n, f"{w}: length {len(x)} != {n}"
        checked.append(w)
    assert abs(n / m["fs"] - m["duration_s"]) < 2.0 / m["fs"]
    info = sf.info(d / "as_heard.wav")
    assert info.subtype == "FLOAT", "as_heard.wav must be 32-bit float"

    sp = _load(d / "spectrograms.json")
    checked.append("spectrograms.json")
    F, T = len(sp["freqs_hz"]), len(sp["times_s"])
    assert isinstance(sp["db_floor"], NUM)
    for k in ("target", "tier0", "tier1"):
        assert k in sp["panels"]
        v = sp["panels"][k]
        if v is None:
            assert k == "tier1"
            continue
        arr = np.asarray(v, dtype=float)
        assert arr.shape == (F, T), (k, arr.shape, F, T)
        assert arr.max() <= 0 and arr.min() >= sp["db_floor"]

    mt = _load(d / "metrics.json")
    checked.append("metrics.json")
    for k in ("passed", "verified", "fragile"):
        assert isinstance(mt[k], bool), k
    assert mt["failure_cause"] is None or isinstance(mt["failure_cause"], str)
    for k in ("echo_level_db_re_direct", "echo_level_db_re_direct_raw3d", "echo_spl_db", "depth_m", "post_count",
              "fill_fraction", "tier_gap_db"):
        assert k in mt["headline"] and _num_or_none(mt["headline"][k]), k
    assert len(mt["metrics"]) > 0
    for e in mt["metrics"]:
        for k in ("id", "label", "value", "unit", "threshold", "comparator", "pass", "tier", "gating"):
            assert k in e, f"metric {e.get('id')}: {k}"
        assert e["comparator"] in ("<=", ">=", "==", None)
        assert e["pass"] in (True, False, None) and isinstance(e["gating"], bool)
        assert e["tier"] in ("tier0", "tier1") and _num_or_none(e["value"])
    for r in mt["robustness"]:
        for k in ("case", "label", "delta", "pass"):
            assert k in r
    for pc in mt["per_clap"]:
        assert "clap" in pc and isinstance(pc["metrics"], dict)
    if m["status"] == "tier0_only":
        assert mt["verified"] is False and mt["passed"] is False and m["verified"] is False

    h = _load(d / "history.json")
    checked.append("history.json")
    for ph in h["phases"]:
        for k in ("name", "x_label", "iters", "loss", "score", "saved"):
            assert k in ph, f"history phase {k}"
        assert len(ph["iters"]) == len(ph["loss"])
        for sv in ph["saved"]:
            it = d / sv["dir"] if (d / sv["dir"]).exists() else d / "iters" / sv["dir"]
            for fn in ("scene.json", "profile.json", "echo.wav", "metrics.json"):
                assert (it / fn).exists(), f"{it}/{fn}"
    return checked


def check_index(runs_root):
    idx = _load(Path(runs_root) / "index.json")
    created = []
    for r in idx["runs"]:
        for k in ("stage", "run_id", "path", "title", "created", "status", "passed", "verified"):
            assert k in r, k
        assert (Path(runs_root) / r["path"] / "manifest.json").exists()
        created.append(r["created"])
    assert created == sorted(created, reverse=True)
    return idx
