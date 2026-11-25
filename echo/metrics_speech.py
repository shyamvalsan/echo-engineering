"""Stage-4 judges: formants (4a), ESTOI (4b, 4c), closed-set nearest target (4b), recognized word (4c).

Every judge is a plain function of arrays (echo, target, fs) and knows nothing about tiers. They are judges only:
never import them into echo/inverse.py or any loss / search objective. No differentiable variants are provided.

Importing this module registers stage 4 into the metrics seam of echo/metrics.py (STAGE_METRICS, METRIC_INFO,
STAGE_AGGREGATORS); thresholds come from metrics.THRESHOLDS unchanged.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from echo import metrics as M
from echo.scene import FS

ROOT = Path(__file__).resolve().parent.parent
WHISPER_DIR = ROOT / ".cache" / "whisper-small"
BAND = (500.0, 4000.0)

# ------------------------------------------------------------------------------------------------------- alignment
ALIGN_MAX_LAG_S = 0.020


def _envelope(x, fs, smooth_s=0.005):
    k = max(1, int(round(smooth_s * fs)))
    return np.sqrt(np.convolve(np.asarray(x, float) ** 2, np.ones(k) / k, mode="same"))


def align(echo, target, fs=FS, max_lag_s=ALIGN_MAX_LAG_S):
    """Shift `echo` so its energy envelope best matches the target's (lag search within +-max_lag_s), and cut/zero-pad
    it to len(target). Returns (aligned echo, lag in samples; positive = echo was late)."""
    e = np.asarray(echo, float)
    t = np.asarray(target, float)
    n = len(t)
    ee, et = _envelope(e, fs), _envelope(t, fs)
    L = int(round(max_lag_s * fs))
    best, best_lag = -np.inf, 0
    for lag in range(-L, L + 1):  # small search (<= 641 dot products of a few thousand samples)
        if lag >= 0:
            a, b = ee[lag: lag + n], et[: len(ee[lag: lag + n])]
        else:
            a, b = ee[: n + lag], et[-lag: -lag + len(ee[: n + lag])]
        m = min(len(a), len(b))
        if m < n // 2:
            continue
        c = float(np.dot(a[:m], b[:m]) / (np.linalg.norm(a[:m]) * np.linalg.norm(b[:m]) + 1e-30))
        if c > best + 1e-12:
            best, best_lag = c, lag
    out = np.zeros(n)
    if best_lag >= 0:
        seg = e[best_lag: best_lag + n]
        out[: len(seg)] = seg
    else:
        seg = e[: n + best_lag]
        out[-best_lag: -best_lag + len(seg)] = seg
    return out, best_lag


# -------------------------------------------------------------------------------------------------------- formants
LPC_FS = 10000  # analysis rate (Praat convention for a male voice: formants searched up to 5 kHz)
LPC_ORDER = 10  # 2 * 5 formants below 5 kHz
LPC_WIN_S = 0.025
LPC_HOP_S = 0.005
FORMANT_MIN_HZ = 250.0  # roots below are the low-cut skirt of the band-limit, not formants
FORMANT_MAX_BW_HZ = 400.0
STEADY = (0.2, 0.8)  # frames whose centre lies in the middle 60 % of the signal


def _lpc(frame, order):
    r = np.correlate(frame, frame, "full")[len(frame) - 1: len(frame) + order]
    if r[0] <= 0:
        return None
    a = np.zeros(order + 1)
    a[0] = 1.0
    err = r[0]
    for i in range(1, order + 1):  # Levinson-Durbin
        k = -(r[i] + np.dot(a[1:i], r[i - 1:0:-1])) / err
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        err *= 1.0 - k * k
        if err <= 0:
            return None
    return a


def formant_frames(x, fs=FS):
    """Per-frame F1, F2 (Hz) by linear prediction. Returns (frame centre times s, F1, F2); NaN where not found.

    Resample to 10 kHz, pre-emphasis 1 - 0.97 z^-1, 25 ms Hamming frames every 5 ms, order-10 autocorrelation LPC,
    roots with positive angle, keep 250 Hz < f < 4.95 kHz and bandwidth < 400 Hz, F1/F2 = the two lowest.
    """
    y = resample_poly(np.asarray(x, float), LPC_FS, fs) if fs != LPC_FS else np.asarray(x, float)
    y = np.append(y[0], y[1:] - 0.97 * y[:-1])
    w = int(round(LPC_WIN_S * LPC_FS))
    h = int(round(LPC_HOP_S * LPC_FS))
    win = np.hamming(w)
    ts, f1, f2 = [], [], []
    for s in range(0, len(y) - w + 1, h):
        fr = y[s: s + w] * win
        a = _lpc(fr, LPC_ORDER)
        ts.append((s + w / 2) / LPC_FS)
        if a is None:
            f1.append(np.nan), f2.append(np.nan)
            continue
        roots = np.roots(a)
        roots = roots[np.imag(roots) > 0]
        f = np.angle(roots) * LPC_FS / (2 * np.pi)
        bw = -np.log(np.abs(roots)) * LPC_FS / np.pi
        keep = (f > FORMANT_MIN_HZ) & (f < LPC_FS / 2 - 50) & (bw < FORMANT_MAX_BW_HZ)
        f = np.sort(f[keep])
        f1.append(f[0] if len(f) > 0 else np.nan)
        f2.append(f[1] if len(f) > 1 else np.nan)
    return np.array(ts), np.array(f1), np.array(f2)


def formants(x, fs=FS, steady=STEADY, energy_db=-10.0):
    """(F1, F2) in Hz: median over the steady frames (centre in the middle 60 % of the signal and frame energy within
    10 dB of the loudest such frame), ignoring frames where the formant was not found. NaN if none."""
    x = np.asarray(x, float)
    t, f1, f2 = formant_frames(x, fs)
    dur = len(x) / fs
    w = int(round(LPC_WIN_S * fs))
    en = np.array([np.sum(x[max(0, int((ti - LPC_WIN_S / 2) * fs)): int((ti - LPC_WIN_S / 2) * fs) + w] ** 2)
                   for ti in t]) + 1e-30
    m = (t >= steady[0] * dur) & (t <= steady[1] * dur)
    if not m.any():
        return float("nan"), float("nan")
    m &= 10 * np.log10(en / en[m].max()) >= energy_db
    out = []
    for f in (f1, f2):
        v = f[m & np.isfinite(f)]
        out.append(float(np.median(v)) if len(v) else float("nan"))
    return out[0], out[1]


def formant_errors(echo, target, fs=FS):
    """Formant judge (4a). Both measured by `formants` (the target on the clean band-limited target).
    Returns dict: F1/F2 of echo and target, per-formant error %, formant_err_pct = max of the two (NaN -> fail)."""
    e1, e2 = formants(echo, fs)
    t1, t2 = formants(target, fs)
    err1 = abs(e1 / t1 - 1.0) * 100.0
    err2 = abs(e2 / t2 - 1.0) * 100.0
    worst = max(err1, err2) if np.isfinite(err1) and np.isfinite(err2) else float("nan")
    return {"formant_err_pct": worst, "f1_err_pct": err1, "f2_err_pct": err2, "f1_hz": e1, "f2_hz": e2,
            "f1_target_hz": t1, "f2_target_hz": t2}


# ----------------------------------------------------------------------------------------------------------- ESTOI
ESTOI_MIN_S = 1.0  # tile the (faded) signal until it lasts at least this long


def _tile(x, fs, min_s=ESTOI_MIN_S, fade_s=0.005):
    k = min(int(round(fade_s * fs)), len(x) // 2)
    w = np.ones(len(x))
    ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(k) + 0.5) / k)
    w[:k], w[len(x) - k:] = ramp, ramp[::-1]
    reps = int(np.ceil(min_s * fs / len(x)))
    return np.tile(x * w, reps), reps


def estoi(echo, target, fs=FS, min_s=ESTOI_MIN_S):
    """ESTOI (pystoi, extended=True) of the echo against its target.

    The echo is time-aligned to the target (`align`). pystoi needs >= 30 frames of 25.6 ms at 10 kHz (384 ms) after
    removing silent frames, so a 200-400 ms utterance cannot be scored as-is (pystoi returns 1e-5). Both signals get
    the same 5 ms end fades and are tiled back-to-back to >= 1 s (ceil(1 s / duration) repetitions); the score is
    the mean over the 384 ms ESTOI segments of the tiled pair. Same procedure for target and echo (DECISIONS.md).
    """
    from pystoi import stoi

    t = np.asarray(target, float)
    e, _ = align(echo, t, fs)
    tt, _ = _tile(t, fs, min_s)
    et, _ = _tile(e, fs, min_s)
    return float(stoi(tt, et, fs, extended=True))


# ----------------------------------------------------------------------------------------------- closed-set test
MEL = dict(n_fft=512, win_length=400, hop_length=160, n_mels=40, fmin=BAND[0], fmax=BAND[1])
MEL_FLOOR_DB = -60.0


def _logmel_cmn(x, fs):
    """Log-mel (dB re own max, floored at -60 dB) in the design band, with the per-band mean over time removed
    (cepstral-mean-style normalisation: removes a fixed convolutive colouring such as the clap spectrum)."""
    import librosa

    S = librosa.feature.melspectrogram(y=np.asarray(x, float), sr=fs, power=2.0, **MEL)
    D = 10 * np.log10(S + 1e-30)
    D = np.maximum(D - D.max(), MEL_FLOOR_DB)
    return D - D.mean(axis=1, keepdims=True)


def _dtw(A, B):
    """DTW over frames (columns) with Euclidean frame distance; steps (1,0),(0,1),(1,1); normalised by n + m."""
    d = np.sqrt(((A[:, :, None] - B[:, None, :]) ** 2).sum(axis=0))
    n, m = d.shape
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = d[i - 1, j - 1] + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
    return float(D[n, m] / (n + m))


def closed_set(echo, own, candidates, fs=FS):
    """Closed-set judge (4b). DTW distance between the mean-normalised log-mel of the echo and of each clean
    candidate target. correct = own target is strictly nearest; margin = (nearest other) - (own), > 0 when correct.
    The echo is aligned to the own target first (same lag search as ESTOI)."""
    e, _ = align(echo, candidates[own], fs)
    E = _logmel_cmn(e, fs)
    dist = {k: _dtw(E, _logmel_cmn(v, fs)) for k, v in candidates.items()}
    other = min(v for k, v in dist.items() if k != own)
    return {"correct": bool(dist[own] < other), "margin": float(other - dist[own]), "distances": dist}


# ----------------------------------------------------------------------------------------------------- recognizer
WORD = "hello"
PAD_S = 0.25  # leading and trailing silence added before recognition
WHISPER_OPTS = dict(language="en", task="transcribe", beam_size=5, best_of=1, temperature=0.0,
                    condition_on_previous_text=False, initial_prompt=None, vad_filter=False,
                    without_timestamps=True)


@lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel

    return WhisperModel(str(WHISPER_DIR), device="cpu", compute_type="int8",
                        cpu_threads=int(os.environ.get("ECHO_WHISPER_THREADS", "2")), num_workers=1)


def normalize_text(s):
    """Lowercase, non-letters -> space, collapse whitespace."""
    return " ".join(re.sub(r"[^a-z']+", " ", s.lower()).replace("'", "").split())


def is_hit(text, word=WORD):
    """Hit rule: `word` appears as a whole token of the normalised transcript (e.g. "Hello." / "hello there")."""
    return word in normalize_text(text).split()


_TRANSCRIPTS: dict = {}


def transcribe(x, fs=FS):
    """faster-whisper small (local, int8, CPU), deterministic settings (WHISPER_OPTS). Input: the signal alone,
    peak-normalized, 0.25 s of zeros each side, resampled to 16 kHz; no denoising. Memoised by content hash."""
    x = np.asarray(x, float)
    if fs != 16000:
        x = resample_poly(x, 16000, fs)
    peak = np.max(np.abs(x))
    x = x / peak if peak > 0 else x
    pad = np.zeros(int(round(PAD_S * 16000)))
    audio = np.concatenate([pad, x, pad]).astype(np.float32)
    key = hashlib.sha1(audio.tobytes()).hexdigest()
    if key not in _TRANSCRIPTS:
        segs, _ = _whisper().transcribe(audio, **WHISPER_OPTS)
        _TRANSCRIPTS[key] = "".join(s.text for s in segs).strip()
    return _TRANSCRIPTS[key]


def recognize(echo, fs=FS, word=WORD):
    """Recognizer judge (4c): (hit, transcript)."""
    text = transcribe(echo, fs)
    return is_hit(text, word), text


# ------------------------------------------------------------------------------------------- seam registration
def _m_vowel(seg, target, fs, band):
    return formant_errors(seg, target.audio, fs)


def _m_syllable(seg, target, fs, band):
    cs = closed_set(seg, target.name, target.candidates, fs)
    return {"closed_set_correct": cs["correct"], "closed_set_margin": cs["margin"],
            "estoi": estoi(seg, target.audio, fs)}


def _m_word(seg, target, fs, band):
    hit, _ = recognize(seg, fs)
    return {"hello_hit": hit, "estoi": estoi(seg, target.audio, fs)}


def _agg_word(stage, per_clap, tier, gating):
    """4c: hello_count = number of clap variants whose echo is recognised as "hello"; pass when >= threshold.
    Other per-clap metrics (estoi, hello_hit fraction) use the default mean entries (no threshold, informational)."""
    thr = M.THRESHOLDS[stage]["hello_count"]
    count = int(sum(bool(pc["hello_hit"]) for pc in per_clap))
    entry = {"id": "hello_count", "label": M.METRIC_INFO["hello_count"][0], "value": float(count), "unit": "claps",
             "threshold": thr, "comparator": ">=", "pass": bool(count >= thr), "tier": tier, "gating": bool(gating)}
    return [entry] + M._entries(stage, per_clap, tier, gating)


M.METRIC_INFO.update({
    "formant_err_pct": ("Worst of F1, F2 error vs target", "%", "<="),
    "f1_err_pct": ("F1 error vs target", "%", "<="),
    "f2_err_pct": ("F2 error vs target", "%", "<="),
    "f1_hz": ("F1 of echo (LPC)", "Hz", None),
    "f2_hz": ("F2 of echo (LPC)", "Hz", None),
    "f1_target_hz": ("F1 of target (LPC)", "Hz", None),
    "f2_target_hz": ("F2 of target (LPC)", "Hz", None),
    "closed_set_correct": ("Nearest to own target (fraction of claps)", "", ">="),
    "closed_set_margin": ("Closed-set margin, DTW log-mel distance", "dB", ">="),
    "estoi": ("ESTOI vs target", "", ">="),
    "hello_hit": ("Recognized as \"hello\" (fraction of claps)", "", ">="),
    "hello_count": ("Clap variants recognized as \"hello\"", "claps", ">="),
})
M.STAGE_METRICS.update({"s4a_vowel": _m_vowel, "s4b_syllables": _m_syllable, "s4c_word": _m_word})
M.STAGE_AGGREGATORS["s4c_word"] = _agg_word


def judge_sanity(out_path=ROOT / "artifacts" / "speech" / "judge_sanity.json"):
    """Every judge on (a) the clean band-limited target, (b) the perfect echo target * clap (band-limited) for each
    of the 5 clap variants, (c) obvious negatives. Writes JSON (the numbers in the task report come from it)."""
    import json

    import soundfile as sf

    from echo.clap import band_limit, clap_family
    from echo.targets_speech import SPEECH, SYLLABLES, shape_clean, speech_target, synth_raw

    claps = clap_family(5)

    def perfect(a, c):
        return band_limit(np.convolve(a, c)[: len(a)], BAND[0], BAND[1], fs=FS)

    def noisy(a, seed=0):
        n = np.random.default_rng(seed).standard_normal(len(a))
        return a + n * np.sqrt(np.mean(a**2) / np.mean(n**2))  # 0 dB SNR

    out = {"fs": FS, "band": list(BAND), "note": "perfect = band_limit(target * clap[k]); noise = white, 0 dB SNR"}
    ah = speech_target("ah")
    rows = {"clean": formant_errors(ah.audio, ah.audio)}
    for k, c in enumerate(claps):
        rows[f"perfect_clap{k}"] = formant_errors(perfect(ah.audio, c), ah.audio)
    rows["negative_om"] = formant_errors(speech_target("om").audio, ah.audio)
    rows["negative_noise_0db"] = formant_errors(noisy(ah.audio), ah.audio)
    f_unbl = formants(shape_clean("ah")[0])
    out["s4a_vowel"] = {"target_f1_hz": rows["clean"]["f1_target_hz"], "target_f2_hz": rows["clean"]["f2_target_hz"],
                        "unbandlimited_f1_hz": f_unbl[0], "unbandlimited_f2_hz": f_unbl[1], "rows": rows,
                        "threshold_pct": M.THRESHOLDS["s4a_vowel"]["formant_err_pct"]}
    syl = {s: speech_target(s) for s in SYLLABLES}
    s4b = {}
    for s, t in syl.items():
        r = {"clean": {"estoi": estoi(t.audio, t.audio), **closed_set(t.audio, s, t.candidates)}}
        for k, c in enumerate(claps):
            p = perfect(t.audio, c)
            r[f"perfect_clap{k}"] = {"estoi": estoi(p, t.audio), **closed_set(p, s, t.candidates)}
        r["negative_noise_0db"] = {"estoi": estoi(noisy(t.audio), t.audio),
                                   **closed_set(noisy(t.audio), s, t.candidates)}
        for o in SYLLABLES:
            if o != s:
                oa = syl[o].audio
                oa = np.pad(oa, (0, max(0, len(t.audio) - len(oa))))[: len(t.audio)]
                r[f"negative_other_{o}"] = {"estoi": estoi(oa, t.audio)}
        s4b[s] = r
    out["s4b_syllables"] = {"rows": s4b, "threshold_estoi": M.THRESHOLDS["s4b_syllables"]["estoi"]}
    h = speech_target("hello")
    s4c = {"clean_unbandlimited": shape_clean("hello")[0], "clean": h.audio}
    for k, c in enumerate(claps):
        s4c[f"perfect_clap{k}"] = perfect(h.audio, c)
    s4c["negative_ma"] = syl["ma"].audio
    s4c["negative_noise"] = np.random.default_rng(0).standard_normal(len(h.audio))
    s4c["negative_noise_0db"] = noisy(h.audio)
    try:
        import tempfile  # "yellow" is only a negative control, synthesized like a target (same voice and speed)

        with tempfile.TemporaryDirectory() as d:
            synth_raw("yellow", SPEECH["hello"][1], Path(d) / "y.wav")
            y, fs_raw = sf.read(Path(d) / "y.wav")
        s4c["negative_yellow"] = band_limit(resample_poly(y, 320, 441), BAND[0], BAND[1], fs=FS)
    except FileNotFoundError:
        pass
    rows = {}
    for k, x in s4c.items():
        hit, text = recognize(x)
        rows[k] = {"hit": hit, "transcript": text}
        if k == "clean" or k.startswith("perfect"):
            rows[k]["estoi"] = estoi(x, h.audio)
    out["s4c_word"] = {"rows": rows, "threshold_hello_count": M.THRESHOLDS["s4c_word"]["hello_count"],
                       "whisper_opts": WHISPER_OPTS, "pad_s": PAD_S}
    out_path = Path(out_path)
    out_path.write_text(json.dumps(out, indent=1, default=float))
    return out


if __name__ == "__main__":
    judge_sanity()
