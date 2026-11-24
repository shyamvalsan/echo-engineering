"""Run-folder writer (data contract in .superpowers/sdd/plan/global-constraints.md and viewer/README.md).

All JSON is plain: NaN/Infinity become null. WAVs share t = 0 = emission and one length. target/echo WAVs are
peak-normalized to -1 dBFS (gain in the manifest); as_heard.wav is 32-bit float: direct clap (variant 0) at -1 dBFS
followed by the echo at its corrected 3D level relative to the direct sound.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from echo.scene import C0, FS, T_DIRECT, Scene

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
PEAK_DBFS = -1.0
EXPORT_DIRS_SKIPPED = ("validation", "_tmp")  # stage-level folders update_index ignores (plus any "_*")
SPEC_N_FFT, SPEC_HOP, SPEC_FMAX, SPEC_FLOOR = 256, 32, 5000.0, -60.0


def clean_json(obj):
    """Recursively convert numpy types to Python and NaN/inf to None."""
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean_json(obj.tolist())
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return v if math.isfinite(v) else None
    return obj


def write_json(path, obj, indent=None):
    text = json.dumps(clean_json(obj), indent=indent, allow_nan=False, separators=(",", ":") if indent is None else None)
    Path(path).write_text(text)
    return path


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def git_dirty_paths(untracked=False):
    """Paths under echo/ and stages/ that differ from the commit (git status --porcelain): tracked modifications, or
    with untracked=True the untracked files ('??'). [] when clean, None if git is unavailable."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", "echo", "stages"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    except Exception:
        return None
    return [ln[3:].strip() for ln in out.splitlines() if ln.strip() and ln.startswith("??") == untracked
            and not ln[3:].strip().endswith(".pyc") and "__pycache__" not in ln]


def make_run_id(tag, now=None):
    now = now or _dt.datetime.now()
    return f"{now:%Y%m%d-%H%M%S}-{tag}"


def write_wav_norm(path, x, fs=FS):
    """Peak-normalize to -1 dBFS, write 32-bit float; returns the gain applied in dB (None for silence)."""
    x = np.asarray(x, dtype=float)
    pk = float(np.max(np.abs(x))) if len(x) else 0.0
    if pk <= 0:
        sf.write(path, x.astype(np.float32), fs, subtype="FLOAT")
        return None
    g = 10 ** (PEAK_DBFS / 20) / pk
    sf.write(path, (x * g).astype(np.float32), fs, subtype="FLOAT")
    return float(20 * math.log10(g))


def as_heard(clap, echo_shape, level_db, n, fs=FS, t_direct=T_DIRECT):
    """Direct clap at t_direct (peak -1 dBFS) + echo_shape scaled so its peak is level_db below the direct peak."""
    out = np.zeros(n)
    c = np.asarray(clap, dtype=float)
    i0 = int(round(t_direct * fs))
    m = min(len(c), n - i0)
    out[i0:i0 + m] += c[:m] / np.max(np.abs(c))
    e = np.asarray(echo_shape, dtype=float)[:n]
    pk = np.max(np.abs(e))
    if pk > 0 and level_db is not None:
        out[: len(e)] += e / pk * 10 ** (level_db / 20)
    return out * 10 ** (PEAK_DBFS / 20)  # direct peak is 1 -> -1 dBFS (float WAV, the echo never clips)


def spectrogram_db(x, fs=FS):
    """Linear-frequency STFT magnitude in dB re its own max, clipped to [-60, 0], rounded to 0.5 dB: [F][T]."""
    from scipy.signal import stft

    f, t, Z = stft(np.asarray(x, dtype=float), fs=fs, nperseg=SPEC_N_FFT, noverlap=SPEC_N_FFT - SPEC_HOP,
                   window="hann", boundary="zeros", padded=True)
    keep = f <= SPEC_FMAX
    mag = np.abs(Z[keep])
    db = 20 * np.log10(mag / (mag.max() + 1e-30) + 1e-30)
    db = np.round(np.clip(db, SPEC_FLOOR, 0.0) * 2) / 2
    return f[keep], t, db


def spectrograms(target_wav, tier0_wav, tier1_wav=None, fs=FS):
    f, t, a = spectrogram_db(target_wav, fs)
    _, _, b = spectrogram_db(tier0_wav, fs)
    c = spectrogram_db(tier1_wav, fs)[2] if tier1_wav is not None else None
    return {"fs": fs, "freqs_hz": f, "times_s": t, "db_floor": SPEC_FLOOR,
            "panels": {"target": a, "tier0": b, "tier1": c}}


def write_iteration(run_dir, name, scene: Scene, profile: dict, echo, metrics: dict):
    d = Path(run_dir) / "iters" / name
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / "scene.json", scene.to_dict())
    write_json(d / "profile.json", profile)
    write_wav_norm(d / "echo.wav", echo)
    write_json(d / "metrics.json", metrics)
    return f"iters/{name}"


def write_run(stage, tag, title, *, scene: Scene, profile: dict, target_audio, t_echo0, claps, echo_t0, metrics,
              history, seed, command, echo_t1=None, solver=None, field=None, notes="", status=None,
              as_heard_level_db=None, duration_s=None, runs_root=RUNS, run_id=None, iters=None, extra=None):
    """Write a full run folder. Returns its path.

    profile: {r0_m, dr_m, reflectivity, units}. target_audio: target at FS starting at its own t = 0; it is placed
    at t_echo0 (first echo arrival). echo_t0 / echo_t1: [K, n] 2D echoes (t = 0 emission); clap variant 0 is
    exported. as_heard_level_db: echo peak re direct for clap 0 (corrected 3D); defaults to metrics' headline level.
    iters: optional list of (name, scene, profile, echo, metrics) saved under iters/<name>/.
    """
    run_id = run_id or make_run_id(tag)
    d = Path(runs_root) / stage / run_id
    d.mkdir(parents=True, exist_ok=True)
    e0 = np.atleast_2d(np.asarray(echo_t0, dtype=float))
    e1 = None if echo_t1 is None else np.atleast_2d(np.asarray(echo_t1, dtype=float))
    n = e0.shape[-1] if duration_s is None else int(round(duration_s * FS))
    duration_s = n / FS

    def fit(x):
        y = np.zeros(n)
        x = np.asarray(x, dtype=float)[:n]
        y[: len(x)] = x
        return y

    tgt = np.zeros(n)
    i0 = int(round(t_echo0 * FS))
    ta = np.asarray(target_audio, dtype=float)[: max(0, n - i0)]
    tgt[i0:i0 + len(ta)] = ta
    w_t0, w_t1 = fit(e0[0]), (fit(e1[0]) if e1 is not None else None)
    gain_t = write_wav_norm(d / "target.wav", tgt)
    gain0 = write_wav_norm(d / "echo_tier0.wav", w_t0)
    gain1 = write_wav_norm(d / "echo_tier1.wav", w_t1) if w_t1 is not None else None
    if as_heard_level_db is None:
        as_heard_level_db = metrics["headline"]["echo_level_db_re_direct"]
    ah = as_heard(claps[0], w_t1 if w_t1 is not None else w_t0, as_heard_level_db, n)
    sf.write(d / "as_heard.wav", ah.astype(np.float32), FS, subtype="FLOAT")

    scene_d = scene.to_dict()
    write_json(d / "scene.json", scene_d, indent=1)
    write_json(d / "profile.json", profile)
    write_json(d / "spectrograms.json", spectrograms(tgt, w_t0, w_t1))
    write_json(d / "metrics.json", metrics, indent=1)

    hist = {"phases": [dict(ph) for ph in history.get("phases", [])]}
    if iters:
        saved = []
        for name, sc_i, prof_i, echo_i, met_i, it in iters:
            saved.append({"iter": it, "dir": write_iteration(d, name, sc_i, prof_i, echo_i, met_i)})
        if hist["phases"]:
            hist["phases"][-1].setdefault("saved", []).extend(saved)
    for ph in hist["phases"]:
        ph.setdefault("saved", [])
        ph.setdefault("score", None)
    write_json(d / "history.json", hist)

    verified = bool(metrics.get("verified", False))
    if status is None:
        status = "final" if verified else "tier0_only"
    solver = solver or {"tier1": "none", "device": "cpu", "dx": None, "dt": None, "grid": None, "f_lo": None,
                        "f_max": None, "ppw": None, "wall_s": None}
    dirty = git_dirty_paths()
    manifest = {
        "run_id": run_id, "stage": stage, "title": title,
        "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "seed": seed, "git_commit": git_commit(), "git_dirty": bool(dirty), "git_dirty_paths": dirty or [],
        "git_untracked_paths": git_dirty_paths(untracked=True) or [],
        "status": status, "verified": verified,
        "passed": bool(metrics.get("passed", False)),
        "fs": FS, "c": float(scene.c), "duration_s": duration_s, "t_direct_s": float(np.linalg.norm(
            scene.listener - scene.source) / scene.c),
        "command": command, "solver": solver, "field": field,
        "audio": {"echo_gain_db": {"tier0": gain0, "tier1": gain1}, "target_gain_db": gain_t,
                  "as_heard_echo_level_db": as_heard_level_db, "clap_variant": 0},
        "notes": notes,
    }
    if extra:
        clash = set(extra) & set(manifest)
        if clash:
            raise ValueError(f"extra manifest keys collide with contract keys: {sorted(clash)}")
        manifest.update(extra)
    write_json(d / "manifest.json", manifest, indent=1)
    update_index(runs_root)
    return d


def update_index(runs_root=RUNS):
    """Rewrite runs/index.json from runs/*/*/manifest.json, newest first. Skips folders starting with '_' and the
    'validation' folder."""
    root = Path(runs_root)
    runs = []
    for mf in sorted(root.glob("*/*/manifest.json")):
        stage_dir, run_dir = mf.parent.parent.name, mf.parent.name
        if stage_dir.startswith("_") or run_dir.startswith("_") or stage_dir in EXPORT_DIRS_SKIPPED:
            continue
        try:
            m = json.loads(mf.read_text())
        except Exception:
            continue
        passed = m.get("passed")
        if passed is None:
            try:
                passed = json.loads((mf.parent / "metrics.json").read_text()).get("passed", False)
            except Exception:
                passed = False
        runs.append({"stage": m.get("stage", stage_dir), "run_id": m.get("run_id", run_dir),
                     "path": f"{stage_dir}/{run_dir}", "title": m.get("title", run_dir),
                     "created": m.get("created", ""), "status": m.get("status", ""), "passed": bool(passed),
                     "verified": bool(m.get("verified", False))})
    runs.sort(key=lambda r: (r["created"], r["run_id"]), reverse=True)
    write_json(root / "index.json", {"runs": runs}, indent=1)
    return runs
