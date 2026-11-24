"""All scoring for stages 1-3 (stage 4 judges live in echo/metrics_speech.py and register into STAGE_METRICS).

Metric functions take plain arrays (echo, target, fs) and know nothing about tiers, so the same code scores Tier 0
and Tier 1 echoes. The pitch tracker, note segmenter and correlation are judges only: never use them in a loss.

Alignment: an echo array starts at t = 0 = clap emission; the target is compared against the echo window that
starts at the first echo arrival `t_echo0 = 2 r0 / c` (`echo_segment`).

Aggregation over the clap family ("mean over the clap family", spec): every metric is computed per clap variant and
the per-clap values are averaged; the threshold is applied to that mean. Boolean metrics (note sequence correct)
are averaged as fractions, and their thresholds require the fraction to be 1.0 (every clap). Per-clap values are
always reported alongside (`per_clap` in metrics.json).
"""

from __future__ import annotations

import math

import numpy as np

from echo.scene import FS

# Pass thresholds, verbatim from the SPEC stage table. Fixed: never change them to make a stage pass.
THRESHOLDS = {
    "s1_bird": {"pitch_err_pct": 3.0, "spec_corr": 0.8},  # pitch track within 3 % along the note; corr >= 0.8
    "s2_motif": {"notes_in_order": 1.0, "note_cents_max": 30.0},  # all four notes in order; each within 30 cents
    "s3_melody": {"notes_in_order": 1.0, "note_cents_max": 50.0},  # exact sequence; each within 50 cents
    "s4a_vowel": {"formant_err_pct": 10.0},  # first two formants within 10 %
    "s4b_syllables": {"closed_set_correct": 1.0, "estoi": 0.5},  # closest to own target; ESTOI >= 0.5
    "s4c_word": {"hello_count": 3},  # recognizer returns "hello" for >= 3 of 5 clap variants
}
DIRECT_SPL_DB = 100.0 + 20.0 * math.log10(1.0 / 0.3)  # 110.46 dB: 100 dB peak at 1 m, listener 0.3 m away
INAUDIBLE_SPL_DB = 35.0

# pyin settings for short, high-pitched signals at 16 kHz.
PYIN_FRAME = 256  # 16 ms
PYIN_HOP = 32  # 2 ms
# pyin's estimate for frame i sits ~frame/8 before the nominal centre i*hop (YIN difference window is the first half
# of the frame); calibrated on the clean bird glide (d ln f/dt = ln(1.75)/80 ms): max error 2.15 % -> 1.23 %.
PYIN_T_OFFSET = -PYIN_FRAME / 8
MEL_N_FFT, MEL_HOP, MEL_N = 256, 64, 40
SPEC_DB_RANGE = 60.0


# ---------------------------------------------------------------------------------------------------------------- utils
def echo_segment(echo, t0_s, n, fs=FS):
    """echo[..., n0 : n0 + n] with n0 = round(t0_s * fs), zero-padded if the echo is short."""
    echo = np.asarray(echo, dtype=float)
    n0 = int(round(t0_s * fs))
    out = np.zeros(echo.shape[:-1] + (n,))
    seg = echo[..., n0:n0 + n]
    out[..., : seg.shape[-1]] = seg
    return out


def pitch_track(x, fs=FS, fmin=None, fmax=None, f_range=None):
    """librosa.pyin track: (t_s frame centres, f0_hz with no NaN (best guess everywhere), voiced_prob).

    f_range=(lo, hi) of the expected pitch sets fmin = lo/1.3, fmax = hi*1.3 unless given explicitly.
    """
    import librosa

    if f_range is not None:
        fmin = fmin or f_range[0] / 1.3
        fmax = fmax or min(f_range[1] * 1.3, fs / 2 - 100)
    x = np.asarray(x, dtype=float)
    pk = np.max(np.abs(x)) or 1.0
    f0, vflag, vprob = librosa.pyin(x / pk, fmin=fmin, fmax=fmax, sr=fs, frame_length=PYIN_FRAME,
                                    hop_length=PYIN_HOP, fill_na=None, center=True)
    t = (np.arange(len(f0)) * PYIN_HOP + PYIN_T_OFFSET) / fs
    return t, np.asarray(f0, dtype=float), np.asarray(vprob, dtype=float)


def pitch_error_pct(echo_seg, f_track, fs=FS, edge_s=0.012):
    """Worst relative pitch error (%) along the note: max over frames with centre in
    [edge_s, duration - edge_s] (excludes the 5 ms fades plus half a frame) of |f_est / f_target - 1|.
    The pyin best-guess f0 is used on every frame (an unvoiced frame is not excused). Returns (max_pct, mean_pct)."""
    tt, ff = f_track
    t, f0, _ = pitch_track(echo_seg, fs, f_range=(np.min(ff), np.max(ff)))
    dur = tt[-1] + (tt[1] - tt[0])
    m = (t >= edge_s) & (t <= dur - edge_s)
    ref = np.interp(t[m], tt, ff)
    err = np.abs(f0[m] / ref - 1.0) * 100.0
    return float(np.max(err)), float(np.mean(err))


def logmel_db(x, fs=FS, band=(500.0, 4000.0)):
    import librosa

    m = librosa.feature.melspectrogram(y=np.asarray(x, dtype=float), sr=fs, n_fft=MEL_N_FFT, hop_length=MEL_HOP,
                                       n_mels=MEL_N, fmin=band[0], fmax=band[1], power=2.0)
    db = 10 * np.log10(m + 1e-20)
    return np.maximum(db, db.max() - SPEC_DB_RANGE)


def spec_corr(echo_seg, target, fs=FS, band=(500.0, 4000.0)):
    """Pearson correlation of log-mel spectrograms (dB, each floored at its max - 60 dB), target vs echo window."""
    a, b = logmel_db(target, fs, band), logmel_db(echo_seg, fs, band)
    a, b = a.ravel() - a.mean(), b.ravel() - b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den > 0 else 0.0


def hz_to_cents(f, ref):
    return 1200.0 * np.log2(np.asarray(f, dtype=float) / ref)


JUDGE_F_RANGE = (400.0, 4200.0)  # pyin search range for the note judge: the design band, never the target's notes


def segment_notes(x, fs=FS, note_s=0.1, f_range=JUDGE_F_RANGE, active_db=-25.0, dip_db=3.0, jump_cents=70.0):
    """Transcribe notes from an echo window. Returns list of (f_hz, t_on, t_off).

    What the judge is told: only the stage's nominal note length `note_s` (and the fixed design-band pitch search
    range JUDGE_F_RANGE). It is not told the target's note count, boundaries or frequencies.

    Frames: pyin (frame 256, hop 32) best-guess f0, and a 64-sample RMS envelope in dB smoothed over 3 frames.
    Active frames are within active_db of the envelope max. Boundaries are (a) envelope dips: local minima with
    prominence >= dip_db, at least note_s/2 apart; (b) pitch changes: peaks >= jump_cents (at least note_s/2 apart)
    of |median log f0 over the next note_s/4 - median over the previous note_s/4|, unless within 0.3 note_s of a dip
    boundary. Segments shorter than 0.4 note_s are dropped. A note's pitch is the median f0 over the middle 60 % of
    its frames.
    """
    import librosa
    import scipy.signal as ss

    x = np.asarray(x, dtype=float)
    t, f0, _ = pitch_track(x, fs, fmin=f_range[0], fmax=f_range[1])
    hop_s = PYIN_HOP / fs
    rms = librosa.feature.rms(y=x, frame_length=64, hop_length=PYIN_HOP, center=True)[0]
    rms = np.pad(rms, (0, max(0, len(t) - len(rms))))[: len(t)]
    db = np.convolve(20 * np.log10(rms + 1e-12), np.ones(3) / 3, "same")
    active = db > db.max() + active_db
    dist = max(1, int(0.5 * note_s / hop_s))
    dips, _ = ss.find_peaks(-db, prominence=dip_db, distance=dist)
    bounds = {int(d) for d in dips if active[max(0, d - 1)] or active[min(len(t) - 1, d + 1)]}
    k = max(2, int(0.25 * note_s / hop_s))
    lf = np.log2(np.maximum(f0, 1.0))
    jump = np.zeros(len(t))
    for i in range(k, len(t) - k):
        jump[i] = abs(np.median(lf[i:i + k]) - np.median(lf[i - k:i])) * 1200.0
    pj, _ = ss.find_peaks(jump, height=jump_cents, distance=dist)
    for q in pj:
        if active[q] and all(abs(q - b) > 0.3 * note_s / hop_s for b in bounds):
            bounds.add(int(q))
    notes, cur = [], []

    def close():
        if cur and len(cur) * hop_s >= 0.4 * note_s:
            n = len(cur)
            mid = cur[int(0.2 * n):max(int(0.2 * n) + 1, int(0.8 * n))]
            notes.append((float(2 ** np.median(lf[mid])), float(t[cur[0]]), float(t[cur[-1]])))

    for i in range(len(t)):
        if not active[i] or i in bounds:
            close()
            cur = []
            if not active[i]:
                continue
        cur.append(i)
    close()
    return notes


def note_sequence_score(echo_seg, target_notes, fs=FS, note_s=None):
    """Compare a transcribed note sequence with the target notes [(f_hz, t_on, t_off)].

    The target's frequencies are used only to compare, after transcription. Returns
    {"in_order": 1.0|0.0 (same count and every note on the same semitone, in order),
    "cents_max": max |cents| over notes (inf-free: 1200 if the sequence does not match), "n_detected", "cents"}.
    """
    fs_t = [n[0] for n in target_notes]
    if note_s is None:  # the stage's nominal note length is all the segmenter is told
        note_s = float(np.median([n[2] - n[1] for n in target_notes]))
    det = segment_notes(echo_seg, fs, note_s=note_s)
    cents = []
    ok = len(det) == len(fs_t)
    if ok:
        cents = [float(hz_to_cents(d[0], f)) for d, f in zip(det, fs_t)]
        ok = all(abs(c) < 50.0 for c in cents)  # same semitone
    return {"in_order": 1.0 if ok else 0.0, "cents_max": float(max(abs(c) for c in cents)) if ok else 1200.0,
            "n_detected": len(det), "cents": cents}


def echo_level_db(echo):
    """20 log10(peak |echo|) per clap: echoes are in units of the direct clap at the listener (peak 1)."""
    e = np.atleast_2d(np.asarray(echo, dtype=float))
    return 20 * np.log10(np.max(np.abs(e), axis=-1) + 1e-30)


def spl_db(level_db_re_direct):
    return float(DIRECT_SPL_DB + level_db_re_direct)


def tier_gap_db(echo_t1_2d, echo_t0_2d):
    """Mean over claps of L2d(Tier 1) - L2d(Tier 0)."""
    return float(np.mean(echo_level_db(echo_t1_2d) - echo_level_db(echo_t0_2d)))


# ------------------------------------------------------------------------------------------------- per-stage judges
def pitch_error_median_pct(echo_seg, f_track, fs=FS, edge_s=0.012):
    """Median over the same interior frames as pitch_error_pct (informational, never gating)."""
    tt, ff = f_track
    t, f0, _ = pitch_track(echo_seg, fs, f_range=(np.min(ff), np.max(ff)))
    dur = tt[-1] + (tt[1] - tt[0])
    m = (t >= edge_s) & (t <= dur - edge_s)
    return float(np.median(np.abs(f0[m] / np.interp(t[m], tt, ff) - 1.0) * 100.0))


def _m_bird(seg, target, fs, band):
    pmax, pmean = pitch_error_pct(seg, target.f_track, fs)
    return {"pitch_err_pct": pmax, "pitch_err_mean_pct": pmean,
            "pitch_err_median_pct": pitch_error_median_pct(seg, target.f_track, fs),
            "spec_corr": spec_corr(seg, target.audio, fs, band)}


def _m_notes(seg, target, fs, band):
    r = note_sequence_score(seg, target.notes, fs)
    return {"notes_in_order": r["in_order"], "note_cents_max": r["cents_max"], "n_notes_detected": r["n_detected"],
            "spec_corr": spec_corr(seg, target.audio, fs, band)}


# id -> (label, unit, threshold key or None, comparator)
METRIC_INFO = {
    "pitch_err_pct": ("Pitch error along the note, worst frame", "%", "<="),
    "pitch_err_mean_pct": ("Pitch error along the note, mean", "%", "<="),
    "pitch_err_median_pct": ("Pitch error along the note, median (info)", "%", "<="),
    "spec_corr": ("Spectrogram correlation, log-mel", "", ">="),
    "notes_in_order": ("Notes detected in order (fraction of claps)", "", ">="),
    "note_cents_max": ("Worst note pitch error", "cents", "<="),
    "n_notes_detected": ("Notes detected", "", None),
}
# stage -> function(echo_segment, target, fs, band) -> {metric id: value}. Stage 4 registers here (metrics_speech).
STAGE_METRICS = {"s1_bird": _m_bird, "s2_motif": _m_notes, "s3_melody": _m_notes}


def stage_values(stage, echoes, target, t0_s, fs=FS, band=(500.0, 4000.0)):
    """Per-clap metric values: list of dicts, one per row of echoes [K, n] (t = 0 at emission)."""
    n = len(target.audio)
    segs = echo_segment(np.atleast_2d(echoes), t0_s, n, fs)
    return [STAGE_METRICS[stage](s, target, fs, band) for s in segs]


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    v = float(v)
    return v if math.isfinite(v) else None


def _entries(stage, per_clap, tier, gating):
    out = []
    thr = THRESHOLDS.get(stage, {})
    for mid in per_clap[0]:
        label, unit, comp = METRIC_INFO.get(mid, (mid, "", None))
        vals = [pc[mid] for pc in per_clap]
        value = float(np.mean(vals))
        t = thr.get(mid)
        ok = None
        if t is not None and comp is not None:
            ok = bool(value <= t) if comp == "<=" else bool(value >= t)
        out.append({"id": mid, "label": label, "value": _clean(value), "unit": unit, "threshold": t,
                    "comparator": comp if t is not None else None, "pass": ok, "tier": tier,
                    "gating": bool(gating and t is not None)})
    return out


# stage -> aggregator(stage, per_clap: list[dict], tier, gating) -> list of metric entries. Default: per-clap mean vs
# threshold (_entries). Stage-level judgements that are not a mean (e.g. "hello" for >= 3 of 5 claps, a closed-set
# test across targets) register their own aggregator here (echo/metrics_speech.py).
STAGE_AGGREGATORS: dict = {}


def aggregate(stage, per_clap, tier, gating):
    return STAGE_AGGREGATORS.get(stage, _entries)(stage, per_clap, tier, gating)


def judge_floor(stage, target, claps, fs=FS, band=(500.0, 4000.0)):
    """The stage's metrics on a physically perfect echo: target convolved with each clap, band-limited. Separates
    judge/clap limits from design error (reporting only)."""
    from echo.clap import band_limit

    segs = [band_limit(np.convolve(target.audio, c)[: len(target.audio)], band[0], band[1]) for c in np.atleast_2d(claps)]
    pc = [STAGE_METRICS[stage](s, target, fs, band) for s in segs]
    return {"per_clap": [{"clap": k, "metrics": {i: _clean(x) for i, x in v.items()}} for k, v in enumerate(pc)],
            "mean": {i: _clean(np.mean([v[i] for v in pc])) for i in pc[0]},
            "note": "metrics of target * clap (band-limited): the floor set by the judge and the clap, not the design"}


def score_stage(stage, target, t0_s, tier0_2d, tier0_3d, tier1_2d=None, *, fs=FS, band=(500.0, 4000.0),
                depth_m=None, post_count=None, fill_fraction=None, robustness=None, failure_cause=None, claps=None):
    """Assemble the metrics.json structure (data contract).

    Gating metrics are computed on Tier 1 when present (tier "tier1"); Tier 0 metrics are always reported and are
    never gating. Without Tier 1: verified False, passed False. Echo level: 3D Tier 0 mean over claps, corrected by
    the tier gap L2d(T1) - L2d(T0) when Tier 1 exists.
    """
    pc0 = stage_values(stage, tier0_2d, target, t0_s, fs, band)
    metrics = []
    per_clap = []
    verified = tier1_2d is not None
    if verified:
        pc1 = stage_values(stage, tier1_2d, target, t0_s, fs, band)
        metrics += aggregate(stage, pc1, "tier1", True)
        for k, v in enumerate(pc1):
            per_clap.append({"clap": k, "tier": "tier1", "metrics": {i: _clean(x) for i, x in v.items()}})
    metrics += aggregate(stage, pc0, "tier0", False)
    for k, v in enumerate(pc0):
        per_clap.append({"clap": k, "tier": "tier0", "metrics": {i: _clean(x) for i, x in v.items()}})
    raw3d = float(np.mean(echo_level_db(tier0_3d)))
    gap = tier_gap_db(tier1_2d, tier0_2d) if verified else None
    level = raw3d + (gap if gap is not None else 0.0)
    gating = [m for m in metrics if m["gating"]]
    passed = bool(verified and gating and all(m["pass"] for m in gating))
    spl = spl_db(level)
    headline = {"echo_level_db_re_direct": _clean(level), "echo_level_db_re_direct_raw3d": _clean(raw3d),
                "echo_spl_db": _clean(spl), "depth_m": _clean(depth_m), "post_count": post_count,
                "fill_fraction": _clean(fill_fraction), "tier_gap_db": _clean(gap),
                "likely_inaudible_on_site": bool(spl < INAUDIBLE_SPL_DB)}
    return {"stage": stage, "passed": passed, "verified": verified, "fragile": False, "headline": headline,
            "metrics": metrics, "per_clap": per_clap, "robustness": list(robustness or []),
            "failure_cause": failure_cause,
            "judge_floor": judge_floor(stage, target, claps, fs, band) if claps is not None else None}
