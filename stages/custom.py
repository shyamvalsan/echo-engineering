"""Custom targets: design a post field for any user-supplied sound (fast model; optional single full-wave run).

    uv run python -m stages.custom --target inputs/targets/rising_two_note.wav --name "rising two-note"
    uv run python -m stages.custom --target my.wav --name "my sound" --tier1 --max-duration 1.0

Pipeline (`design_custom`): load (soundfile, else librosa) -> mono (channel mean) -> resample to 16 kHz
(scipy resample_poly) -> trim silence (5 ms RMS frames below -40 dB re the loudest frame, 5 ms kept each side) ->
trim to max_duration_s with a 10 ms fade (reported) -> band-limit to the design band 500-4000 Hz -> peak-normalize ->
design on Tier 0 with the settings that worked in stages 1-4 (1 cm posts only, full +-20 deg fan, low coverage,
stretch pre-compensation prior on ranges) -> run folder runs/custom/<run_id>/ (status tier0_only, verified false;
after a completed --tier1 run: status final, verified true).

Rejected inputs (CustomInputError, message for the user): not decodable, empty, non-finite samples, silent
(peak < 1e-5 FS), no energy in 500-4000 Hz (in-band energy < -30 dB of the total), shorter than 30 ms after
trimming silence.

Realization rule (judge-free, documented, recorded in manifest.custom.classification): on 32 ms Hann frames of the
band-limited target, `tonal_ratio` = the fraction of a frame's in-band power within +-50 Hz of its strongest bin,
medianed over active frames (frame power within 30 dB of the loudest). tonal_ratio >= 0.5 (one dominant partial at a
time: whistles, pure-tone notes, glides) -> "phase_locked" ring realization, K = 1 (stages 1-2: s1_bird, s2 v2);
otherwise (harmonic-rich, noisy, speech-like) -> "sampling" (stage 4's choice for speech: inverse-CDF sampling with
range polish). Spectral flatness is recorded for information. No pitch tracker or other judge is used.

Settings: tonal = stage 2 v2 (1 cm posts, +-20 deg, fill 0.1 % for low extinction, phase-locked K = 1); broadband =
stage 4 (1 cm posts, sampling, 1,000 posts per 100 ms of target, range polish cut to 20 steps). Both: 250 Adam steps at
lr 0.05 (stages used 300-1200; cut for an interactive turnaround), torch on 2 threads (see SOLVE_THREADS). Both use the 500-4000 Hz band (StageConfig
band_min_hz=500, as stage 4: the clap band starts at 898 Hz, user targets may not).

Metrics: there is no pass condition for an arbitrary target. metrics.json carries generic information only (echo
level, depth, post count, coverage, log-mel spectrogram correlation and envelope correlation with the target), no
thresholds, `pass: null` on every row, `passed: false` / `verified: false` per the contract's unverified convention
(`verified: true` once a --tier1 full-wave run of the design has completed),
`pass_condition: null`, and `failure_cause` = "no pass condition defined for custom targets".

Full-wave (--tier1 / tier1=1): ONE run of the design through the stage driver (stages.common.run_stage with Tier 1,
one correction round, field recorded in that run, no robustness sweep), holding the machine-wide solver lock. Grid:
2.5 kHz if the target's top frequency (highest frequency within 20 dB of the target's spectral peak) is <= 2.4 kHz,
else 4 kHz (both validated for 1 cm posts). Refused, with the estimate, if the estimated solve exceeds 20 minutes
(cost model of stage 4: 55e9 cell-steps in 260 s on 8 threads). On completion the same run folder is replaced by the
full-wave result (status "final") and keeps its run_id.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import re
import shlex
import shutil
import sys
import time
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

from echo import export
from echo.clap import band_limit
from echo.metrics import METRIC_INFO, STAGE_METRICS, spec_corr
from echo.scene import C0, FS
from echo.targets import Target, _fade

STAGE = "custom"
CUSTOM_DIR = export.RUNS / STAGE
BAND = (500.0, 4000.0)
MIN_DURATION_S = 0.03
MAX_DURATION_CAP_S = 2.0
# Decoding reads at most this much of a file (silence is trimmed after decoding, so some lead-in is allowed beyond
# MAX_DURATION_CAP_S). Bounds memory for highly compressible files: 20 MB of FLAC near-silence can hold ~40 h.
MAX_READ_S = 30.0
MAX_CHANNELS = 8
SR_RANGE = (1000, 384000)
TONAL_RATIO_MIN = 0.5
TIER1_BUDGET_S = 20 * 60.0
TIER1_CELL_STEPS_PER_S = 55e9 / 260.0  # stage 4's cost model (8 idle threads)
TIER1_GRIDS = (2500.0, 4000.0)  # validated grids for 1 cm posts (runs/validation/metrics.json)
NO_PASS = "no pass condition defined for custom targets"
# torch threads for the profile solve: 2. Measured on the shared 8-core machine (load ~11), 0.3 s target, 51 Adam steps:
# 2 threads 1.4-1.7 s, 4 threads 1.8 s, 8 threads 48 s (oversubscribed thread pools spin); the solve is small.
SOLVE_THREADS = 2
REFINE_STEPS = 20  # sampling realization's range polish (stage 4 used the driver default 100: 71 s of a 79 s design
#   for a 0.3 s broadband target); phase-locked designs skip the polish anyway
STEPS = 250  # profile-solve Adam steps at lr 0.05: the example's loss plateaus by ~250-300 (1.98 -> 1.71 at 300,
#   1.72 at 600); the solve is ~all of the design time (MR-STFT loss + backward per step, plus a one-off SVD plan)


class CustomInputError(ValueError):
    """An input the custom designer refuses; the message is meant for the user."""


# ------------------------------------------------------------------------------------------------ metrics (info)
def _env_corr(seg, target, fs=FS, hop_s=0.005):
    h = int(hop_s * fs)
    n = min(len(seg), len(target)) // h * h
    if n < 2 * h:
        return None
    a = np.sqrt(np.mean(np.asarray(seg[:n]).reshape(-1, h) ** 2, axis=1))
    b = np.sqrt(np.mean(np.asarray(target[:n]).reshape(-1, h) ** 2, axis=1))
    a, b = a - a.mean(), b - b.mean()
    den = np.sqrt(np.sum(a * a) * np.sum(b * b))
    return float(np.sum(a * b) / den) if den > 0 else None


def _m_custom(seg, target, fs, band):
    return {"spec_corr": spec_corr(seg, target.audio, fs, band), "env_corr": _env_corr(seg, target.audio, fs)}


STAGE_METRICS[STAGE] = _m_custom  # registry (echo.metrics); no THRESHOLDS entry: every row is information only
METRIC_INFO.setdefault("env_corr", ("Envelope correlation, 5 ms RMS (info)", "", None))


# ------------------------------------------------------------------------------------------------------- input
def load_audio(src, warnings=None):
    """Decode an audio file (path or bytes). Returns (x [n, ch] float64, sr). Raises CustomInputError.
    Reads at most the first MAX_READ_S seconds (a note is appended to `warnings`, if given, when the file is longer)."""
    data = Path(src).read_bytes() if not isinstance(src, (bytes, bytearray)) else bytes(src)
    if not data:
        raise CustomInputError("empty file")
    truncated = False
    try:
        with sf.SoundFile(io.BytesIO(data)) as f:
            sr, ch = int(f.samplerate), int(f.channels)
            if not (SR_RANGE[0] <= sr <= SR_RANGE[1]) or not (1 <= ch <= MAX_CHANNELS):
                raise CustomInputError(f"unsupported audio: {sr} Hz, {ch} channels (allowed {SR_RANGE[0]}-"
                                       f"{SR_RANGE[1]} Hz, 1-{MAX_CHANNELS} channels)")
            cap = int(MAX_READ_S * sr)
            x = f.read(frames=cap, dtype="float64", always_2d=True)
            truncated = len(x) >= cap and (f.frames > cap if f.frames > 0 else bool(len(f.read(1))))
    except CustomInputError:
        raise
    except Exception:  # noqa: BLE001 - fall back to librosa (audioread) for formats libsndfile cannot read
        try:
            import tempfile
            import warnings as _w

            with _w.catch_warnings(), tempfile.NamedTemporaryFile(suffix=".bin") as tf:  # generated name
                _w.simplefilter("ignore")
                import librosa

                tf.write(data)
                tf.flush()
                y, sr = librosa.load(tf.name, sr=None, mono=False, duration=MAX_READ_S)
            x = np.atleast_2d(y).T.astype(np.float64)
            truncated = len(x) >= int(MAX_READ_S * sr)
        except Exception as exc:  # noqa: BLE001
            raise CustomInputError(f"not a decodable audio file (wav/flac/ogg/mp3): {type(exc).__name__}") from None
    if x.size == 0 or sr <= 0:
        raise CustomInputError("no audio samples in the file")
    if truncated and warnings is not None:
        warnings.append(f"file longer than {MAX_READ_S:.0f} s: only the first {MAX_READ_S:.0f} s were read")
    return x, int(sr)


def _resample(x, sr, fs=FS):
    if sr == fs:
        return x
    from scipy.signal import resample_poly

    fr = Fraction(fs, sr).limit_denominator(1000)
    return resample_poly(x, fr.numerator, fr.denominator)


def _trim_silence(x, fs=FS, frame_s=0.005, rel_db=-40.0, keep_s=0.005):
    h = max(1, int(frame_s * fs))
    nf = int(math.ceil(len(x) / h))
    pad = np.zeros(nf * h)
    pad[: len(x)] = x
    rms = np.sqrt(np.mean(pad.reshape(nf, h) ** 2, axis=1))
    act = np.nonzero(rms >= rms.max() * 10 ** (rel_db / 20))[0]
    a = max(0, act[0] * h - int(keep_s * fs))
    b = min(len(x), (act[-1] + 1) * h + int(keep_s * fs))
    return x[a:b], a / fs


def prepare_target(x, sr, max_duration_s=1.0):
    """(x [n, ch], sr) -> (audio at FS, peak 1, band-limited to BAND; info dict; warnings list)."""
    warnings = []
    x = np.asarray(x, dtype=float)
    x = x.reshape(len(x), -1)
    info = {"input_sr": int(sr), "input_channels": int(x.shape[1]), "input_duration_s": len(x) / sr}
    if not np.all(np.isfinite(x)):
        raise CustomInputError("the file contains non-finite samples")
    if x.shape[1] > 1:
        warnings.append(f"{x.shape[1]} channels mixed down to mono (channel mean)")
    m = x.mean(axis=1)
    pk_in = float(np.max(np.abs(x)))
    if pk_in < 1e-5:
        raise CustomInputError("the file is silent (peak below -100 dBFS)")
    clip = float(np.mean(np.abs(x) >= 0.999 * pk_in)) if pk_in >= 0.99 else 0.0
    if clip > 1e-3:
        warnings.append(f"input looks clipped ({clip * 100:.1f} % of samples at full scale); designed as is")
    info["clipped_fraction"] = clip
    if sr != FS:
        warnings.append(f"resampled {sr} Hz -> {FS} Hz")
    y = _resample(m, sr)
    y, t_cut = _trim_silence(y)
    info["leading_silence_trimmed_s"] = t_cut
    cap = float(max_duration_s)
    if not (cap > 0):
        raise CustomInputError("max_duration_s must be positive")
    if cap > MAX_DURATION_CAP_S:
        warnings.append(f"max_duration_s {cap} capped at {MAX_DURATION_CAP_S} s")
        cap = MAX_DURATION_CAP_S
    if len(y) / FS > cap:
        warnings.append(f"target trimmed from {len(y) / FS:.3f} s to {cap:.3f} s (10 ms fade-out)")
        n = int(round(cap * FS))
        y = y[:n].copy()
        k = int(0.010 * FS)
        y[-k:] *= 0.5 + 0.5 * np.cos(np.pi * (np.arange(k) + 0.5) / k)
        info["trimmed_to_s"] = cap
    if len(y) / FS < MIN_DURATION_S:
        raise CustomInputError(f"the sound is too short: {len(y) / FS * 1e3:.0f} ms after trimming silence "
                               f"(minimum {MIN_DURATION_S * 1e3:.0f} ms)")
    y = y * _fade(len(y), FS, 0.002)
    yb = band_limit(y, BAND[0], BAND[1])
    frac = float(np.sum(yb ** 2) / np.sum(y ** 2))
    info["in_band_energy_fraction"] = frac
    if frac < 1e-3:
        raise CustomInputError(f"no usable energy in the design band 500-4000 Hz ({10 * np.log10(max(frac, 1e-30)):.0f} dB "
                               "of the sound's energy is in band)")
    if frac < 0.1:
        warnings.append(f"only {frac * 100:.1f} % of the sound's energy is in 500-4000 Hz; the rest is removed")
    yb = yb / np.max(np.abs(yb))
    info["duration_s"] = len(yb) / FS
    return yb, info, warnings


def classify(audio, fs=FS):
    """Judge-free realization rule (module docstring). Returns (realization, stats)."""
    n = 512
    hop = 128
    w = np.hanning(n)
    if len(audio) < n:
        audio = np.concatenate([audio, np.zeros(n - len(audio))])
    fr = np.lib.stride_tricks.sliding_window_view(audio, n)[::hop] * w
    P = np.abs(np.fft.rfft(fr, axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1 / fs)
    inb = (f >= BAND[0]) & (f <= BAND[1])
    Pb = P[:, inb]
    tot = Pb.sum(axis=1)
    act = tot >= tot.max() * 1e-3
    k = Pb.argmax(axis=1)
    half = int(round(50.0 / (fs / n)))
    near = np.array([Pb[i, max(0, k[i] - half):k[i] + half + 1].sum() for i in range(len(Pb))])
    ratio = near[act] / tot[act]
    flat = np.exp(np.mean(np.log(Pb[act] + 1e-30), axis=1)) / (np.mean(Pb[act], axis=1) + 1e-30)
    spec = P[act].mean(axis=0)
    sb = np.where(inb, spec, 0)
    f_top = float(f[np.nonzero(sb >= sb.max() * 0.01)[0].max()])
    tr = float(np.median(ratio))
    real = "phase_locked" if tr >= TONAL_RATIO_MIN else "sampling"
    return real, {"tonal_ratio": tr, "spectral_flatness": float(np.median(flat)), "f_top_hz": f_top,
                  "f_peak_hz": float(f[np.argmax(sb)]), "rule": f"phase_locked if tonal_ratio >= {TONAL_RATIO_MIN} "
                  "(median fraction of in-band frame power within +-50 Hz of the frame's strongest bin) else sampling",
                  "realization": real}


# ------------------------------------------------------------------------------------------------- configuration
def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", (name or "custom").lower()).strip("_")
    return (s or "custom")[:24]


def duration_for(audio):
    from echo.inverse import R0_PROFILE

    return round(2 * R0_PROFILE / C0 + len(audio) / FS + 0.008 + 0.012, 3)


def make_config(target: Target, realization, name):
    from stages.common import StageConfig, stage_scene

    tonal = realization == "phase_locked"
    cfg = StageConfig(
        stage=STAGE, title=f"Custom: \"{name}\" ({len(target.audio) / FS * 1e3:.0f} ms, "
                           f"{'tonal' if tonal else 'broadband'})",
        tag=f"custom_{slug(name)}", make_target=lambda: target, duration_s=duration_for(target.audio),
        a_ref=0.01, catalog=(0.01,), half_angle_deg=20.0, band_min_hz=BAND[0], band_max_hz=BAND[1],
        realization=realization, posts_per_period=1, steps=STEPS, lr=0.05, refine_steps=REFINE_STEPS, threads=SOLVE_THREADS,
        correction_rounds=1, robustness=False, field=True, stretch_prior_tier0=True,
        notes=f"Custom target \"{name}\" (user input, band-limited {BAND[0]:.0f}-{BAND[1]:.0f} Hz). {NO_PASS}.")
    if tonal:
        cfg.target_fill = 0.001  # stage 2 v2: low coverage, small extinction
    else:  # stage 4: 1,000 posts of 1 cm per 100 ms of target over the wedge
        from echo.realize import wedge_area

        r_hi = cfg.r0 + C0 * len(target.audio) / FS / 2.0
        n_posts = 1000 * len(target.audio) / FS / 0.1
        cfg.target_fill = float(n_posts * math.pi * cfg.a_ref ** 2 / wedge_area(stage_scene(cfg).r_min, r_hi, 20.0))
    return cfg


def tier1_grid(f_top):
    return TIER1_GRIDS[0] if f_top <= 0.96 * TIER1_GRIDS[0] else TIER1_GRIDS[1]


def tier1_estimate(cfg, target, scene=None):
    """Planned grid and estimated wall time of the one full-wave design run (idle machine, 8 threads), without
    allocating the grid: dx and the time-step ratio come from echo.tier1.plan on a one-post scene (same radius, same
    f_max), the cell count from echo.tier1.make_grid on the design's extent (wedge corners or the posts)."""
    from echo import tier1
    from echo.scene import Scene
    from stages.common import stage_listeners

    r_hi = cfg.r0 + C0 * len(target.audio) / FS / 2.0
    th = math.radians(cfg.half_angle_deg)
    corners = np.array([[3.0 * math.cos(th), s * 3.0 * math.sin(th), cfg.a_ref] for s in (-1, 1)]
                       + [[r_hi * math.cos(th), s * r_hi * math.sin(th), cfg.a_ref] for s in (-1, 1)]
                       + [[r_hi, 0, cfg.a_ref]])
    sc = scene if scene is not None and len(scene.posts) else Scene(posts=corners, half_angle_deg=cfg.half_angle_deg)
    lis = stage_listeners(cfg, target)
    probe = tier1.plan(Scene(posts=np.array([[3.5, 0.0, cfg.a_ref]])), cfg.f_max, cfg.duration_s, ppw=cfg.ppw)
    g = tier1.make_grid(sc, lis, probe["dx"])
    cells = g.nx * g.ny
    return {"f_max": cfg.f_max, "dx_m": probe["dx"], "grid": [g.nx, g.ny], "n_steps": probe["n_steps"],
            "est_solve_s": float(cells * probe["n_steps"] / TIER1_CELL_STEPS_PER_S),
            "note": "one design solve; an uncached empty-scene run on a new grid costs about as much again"}


# --------------------------------------------------------------------------------------------------- run folders
def _finish_folder(run_dir, cfg, name, info, cls, warnings, command, tier1_block):
    """Custom conventions on a run folder written by the stage driver (own folder; metrics.json is ours)."""
    d = Path(run_dir)
    mt = json.loads((d / "metrics.json").read_text())
    mt["passed"] = False  # contract: bool; there is no pass condition (pass_condition null)
    mt["pass_condition"] = None
    mt["failure_cause"] = NO_PASS
    for m in mt["metrics"]:
        m["threshold"], m["comparator"], m["pass"], m["gating"] = None, None, None, False
    mt["custom"] = {"note": "information metrics only (target-agnostic); no thresholds"}
    export.write_json(d / "metrics.json", mt, indent=1)
    man = json.loads((d / "manifest.json").read_text())
    man["passed"] = False
    man["command"] = command
    man["custom"] = {"name": name, "input": info, "classification": cls, "warnings": list(warnings),
                     "band_hz": list(BAND), "pass_condition": None, "tier1": tier1_block,
                     "settings": {"realization": cfg.realization, "target_fill": cfg.target_fill,
                                  "steps": cfg.steps, "lr": cfg.lr, "catalog": list(cfg.catalog),
                                  "half_angle_deg": cfg.half_angle_deg, "stretch_prior": True}}
    export.write_json(d / "manifest.json", man, indent=1)


class _Progress(io.TextIOBase):
    """stdout sink for run_stage(verbose=True): turns its log lines into progress(stage, fraction) calls."""

    STEP = re.compile(r"^step\s+(\d+) loss ([0-9.]+)")

    def __init__(self, say, steps, lo, hi, echo=None):
        self.say, self.steps, self.lo, self.hi, self.echo, self.buf = say, steps, lo, hi, echo, ""

    def write(self, text):
        if self.echo is not None:
            self.echo.write(text)
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            m = self.STEP.match(line.strip())
            if m:
                k = int(m.group(1))
                self.say(f"profile solve: step {k}/{self.steps} (loss {float(m.group(2)):.3f})",
                         self.lo + (self.hi - self.lo) * 0.85 * k / self.steps)
            elif "realized" in line:
                self.say("realizing posts", self.lo + (self.hi - self.lo) * 0.88)
            elif line.startswith("=== "):
                self.say("writing run folder (echoes, IRs, spectrograms, index)", self.lo + (self.hi - self.lo) * 0.95)
        return len(text)


def _staged_run(cfg, tier1, cmd, runs_root, say, lo, hi, echo=None):
    from stages.common import run_stage

    say("building the Tier 0 range plan and starting the profile solve", lo)
    with contextlib.redirect_stdout(_Progress(say, cfg.steps, lo, hi, echo)):
        return run_stage(cfg, tier1, command=cmd, verbose=True, runs_root=runs_root)


def design_custom(src, name="custom", max_duration_s=1.0, tier1=False, progress=None, command=None,
                  runs_root=None):
    """Full custom pipeline. src: path or bytes. progress(stage_text, fraction) is called along the way.
    Returns {"run_dir", "run_id", "warnings", "timings", "classification", "tier1"}."""
    from stages.common import Tier1Hooks

    say = progress or (lambda *_: None)
    runs_root = Path(runs_root or export.RUNS)
    t_all = time.time()
    tim = {}
    say("loading audio", 0.02)
    read_notes = []
    x, sr = load_audio(src, read_notes)
    audio, info, warnings = prepare_target(x, sr, max_duration_s)
    warnings = read_notes + list(warnings)
    real, cls = classify(audio)
    target = Target(name=slug(name), audio=audio, duration_s=len(audio) / FS, f_top_hz=cls["f_top_hz"])
    cfg = make_config(target, real, name)
    tim["prepare_s"] = time.time() - t_all
    cmd = command or ("uv run python -m stages.custom " + " ".join(shlex.quote(a) for a in (
        ["--target", str(src) if not isinstance(src, (bytes, bytearray)) else "<upload>", "--name", name,
         "--max-duration", str(max_duration_s)] + (["--tier1"] if tier1 else []))))
    say(f"designing on the fast model ({'tonal: phase-locked rings' if real == 'phase_locked' else 'broadband: sampling'})", 0.1)
    t = time.time()
    run_dir, des, _ = _staged_run(cfg, None, cmd, runs_root, say, 0.1, 0.5 if tier1 else 0.97)
    tim["design_s"] = time.time() - t
    w = json.loads((run_dir / "manifest.json").read_text()).get("wall_s") or {}
    tim["profile_solve_s"] = w.get("profile_solve_s")
    tim["realize_s"] = w.get("realize_s")
    tim["score_export_index_s"] = tim["design_s"] - (w.get("profile_solve_s") or 0) - (w.get("realize_s") or 0)
    run_id = run_dir.name
    t1_block = {"requested": bool(tier1), "status": "not requested" if not tier1 else "queued"}
    if tier1:
        cfg1 = replace(cfg, f_max=tier1_grid(cls["f_top_hz"]))
        cfg1.band_max_hz = cfg1.f_max
        est = tier1_estimate(cfg1, target, des.scene)
        t1_block.update({"plan": est})
        if est["est_solve_s"] > TIER1_BUDGET_S:
            msg = (f"full-wave run refused: estimated {est['est_solve_s'] / 60:.0f} min on the {cfg1.f_max:.0f} Hz grid "
                   f"exceeds the {TIER1_BUDGET_S / 60:.0f} min limit (try a shorter target: cost grows with the square "
                   "of the echo depth)")
            t1_block.update({"status": "refused", "message": msg})
            warnings.append(msg)
    _finish_folder(run_dir, cfg, name, info, cls, warnings, cmd, t1_block)
    say("fast-model design written", 0.5 if tier1 and t1_block["status"] == "queued" else 1.0)
    if tier1 and t1_block["status"] == "queued":
        t = time.time()
        tmp_root = runs_root / STAGE / "_tmp" / run_id
        try:
            say(f"full-wave run (est. {est['est_solve_s'] / 60:.1f} min on an idle machine; waits for the solver lock)",
                0.55)
            def say1(s_, f_):
                if s_.startswith("realizing"):
                    s_, f_ = f"full-wave solve running (est. {est['est_solve_s'] / 60:.1f} min idle; field video after)", 0.62
                elif s_.startswith("profile solve"):
                    s_, f_ = "re-solving the profile in the full-wave band (" + s_ + ")", 0.55 + 0.05 * (f_ - 0.55) / 0.43
                say(s_, f_)

            d1, _, _ = _staged_run(cfg1, Tier1Hooks(), cmd, tmp_root, say1, 0.55, 0.98, echo=sys.__stdout__)
            tim["tier1_s"] = time.time() - t
            for p in run_dir.iterdir():  # replace the Tier 0 folder's contents, keep its run_id
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            for p in d1.iterdir():
                shutil.move(str(p), run_dir / p.name)
            man = json.loads((run_dir / "manifest.json").read_text())
            man["run_id"] = run_id
            export.write_json(run_dir / "manifest.json", man, indent=1)
            t1_block.update({"status": "done", "wall_s": tim["tier1_s"]})
            _finish_folder(run_dir, cfg1, name, info, cls, warnings, cmd, t1_block)
        except Exception as exc:  # noqa: BLE001
            t1_block.update({"status": "error", "message": f"{type(exc).__name__}: {exc}"})
            warnings.append(f"full-wave run failed: {type(exc).__name__}: {exc}")
            if (run_dir / "manifest.json").exists():
                _finish_folder(run_dir, cfg, name, info, cls, warnings, cmd, t1_block)
        finally:
            shutil.rmtree(runs_root / STAGE / "_tmp", ignore_errors=True)
    export.update_index(runs_root)
    tim["total_s"] = time.time() - t_all
    return {"run_dir": run_dir, "run_id": run_id, "warnings": warnings, "timings": tim, "classification": cls,
            "tier1": t1_block}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Design a post field for a user-supplied target sound")
    ap.add_argument("--target", required=True, help="audio file (wav/flac/ogg/mp3)")
    ap.add_argument("--name", default=None, help="label (default: file stem)")
    ap.add_argument("--tier1", action="store_true", help="also run ONE full-wave verification (<= 20 min estimate)")
    ap.add_argument("--max-duration", type=float, default=1.0, help="longer targets are trimmed (s, max 2)")
    a = ap.parse_args(argv)
    name = a.name or Path(a.target).stem
    args = list(argv if argv is not None else sys.argv[1:])
    cmd = "uv run python -m stages.custom " + " ".join(shlex.quote(x) for x in args)
    try:
        r = design_custom(a.target, name, a.max_duration, a.tier1, command=cmd,
                          progress=lambda s, f: print(f"[{f * 100:3.0f}%] {s}", flush=True))
    except CustomInputError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for w in r["warnings"]:
        print("warning:", w)
    print(f"run: {r['run_dir']}  ({r['classification']['realization']}, tonal_ratio "
          f"{r['classification']['tonal_ratio']:.2f}; timings {({k: round(v, 1) for k, v in r['timings'].items()})})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
