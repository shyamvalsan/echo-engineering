"""owner_v2: a second, listening-calibrated criterion set, kept side by side with the spec's (spec_v1).

spec_v1 is `echo/metrics.py::THRESHOLDS` with the judges in echo/metrics.py and echo/metrics_speech.py. It is not
touched; the top-level `passed` in every metrics.json keeps meaning spec_v1. owner_v2 exists because the owner listened
to every final echo (echo_tier1.wav) and judged all of them a pass, and asked for thresholds calibrated to that.
A calibrated criterion means something only if it also rejects echoes that should not pass, so every test carries a
fixed set of negative controls (built here, from saved audio only) that must fail.

The criterion family (fixed before any run was scored; the same rule for every test):

  C1 identification (every test). Closed-set nearest target: log-mel (n_fft 256, hop 64, 40 bands 500-4000 Hz),
     dB re own max floored at -30 dB (a listener's useful range, not the spec's 60 dB), per-band time mean removed
     (removes the clap colouring), DTW distance (steps (1,0),(0,1),(1,1), normalised by n + m). A clap passes when its
     echo window is strictly nearer to its own target than to every distractor. Distractors, fixed per test: every
     other test's target, the own target time-reversed, and for tonal tests the own target resampled by +-1 and +-2
     semitones, and for multi-note tests the own target with notes 3 and 4 swapped. All trimmed/zero-padded to the
     own target's length. No threshold: "nearest" is the threshold.
  C2 pitch (tonal tests: s1, s2, s3). Median over interior frames (more than 12 ms from every note boundary) of
     |cents| between the pyin track (search range 400-4200 Hz, the v1 note judge's range) and the target's intended
     pitch. Median, not worst frame. For multi-note targets (review fix r2) the median is taken per note and the value
     is the WORST note: every note's median pitch must be within T of its own target note, in its own time slot, so
     a wrong or misplaced note fails. Threshold by rule (below).
  C3 recognizer (4c only). The spec's recognizer, unchanged: transcript contains "hello".

  Clap family: a clap variant passes when it passes every criterion of its test; the echo passes when at least
  MAJORITY of the 5 clap variants pass (explicit majority rule, not a mean).

Threshold rule (C2, the only numeric threshold; r2): T = midway between the worst positive and the best mistuning
control, rounded to 5 cents. Values are majority values (the 3rd-best clap, the value that decides a 3-of-5 vote).
Worst positive = the worse of the owner-accepted echo and the perfect echo (target * clap, band-limited). Mistuning
controls = the accepted echo AND the perfect echo, each resampled by -2, -1, +1, +2 semitones. A threshold exists only
if it sits at least MIN_MARGIN_CENTS from both sides and below MAX_PITCH_T_CENTS (half a semitone: a tolerance of a
semitone or more would accept a wrong note). Otherwise no threshold exists and the test is null. Every other control
(including the near-miss negatives, which are NOT in the C1 distractor set) must be rejected by the conjunction; they
are checked, never used for calibration.

Judge-validity rule (POST HOC: added after the first scoring, because C1 rejected the perfect "hello" echo on 3 of 5
claps; it looks only at perfect echoes, never at the accepted echo). Stated once, applied to every criterion (C1, C2,
C3) of every test: a criterion that rejects the perfect echo (target * clap, band-limited) by majority is invalid for
that test and is not used there. A C2 with no threshold is not "invalid", it is "not separable": the test is null. If
no valid criterion remains, the test is null. Outcome: it drops only C1 for 4c (C2 and C3 accept every perfect echo),
so 4c's owner_v2 rests on the spec_v1 recognizer with the spec's 3-of-5 rule plus its rejected controls; it is not an
independent confirmation. Each test's block says what its pass rests on (`rests_on`).

On an accepted (calibration) run owner_v2 can only return PASS or null ("not established"): it cannot fail the echo it
was calibrated on, so null is not a soft pass and the tally is "N of 9 confirmed automatically".

Verdict: owner_v2.passed = true/false only when the criterion is established for that test (the accepted echo and
the perfect echo pass AND every control fails); otherwise null with the numbers shown ("accepted by ear; no automated
criterion separates this echo from the negative controls").

All functions are pure functions of arrays. They are judges only (never in a loss).
"""

from __future__ import annotations

import numpy as np

from echo.scene import FS

LABEL = "owner_v2 (listening-calibrated, 2026-11-25)"
SPEC_V1_LABEL = "spec_v1 (original spec thresholds)"
MAJORITY = 3  # of 5 clap variants
MEL_V2 = dict(n_fft=256, hop_length=64, n_mels=40, fmin=500.0, fmax=4000.0)
FLOOR_DB_V2 = 30.0
PITCH_RANGE = (400.0, 4200.0)  # = echo.metrics.JUDGE_F_RANGE
PITCH_EDGE_S = 0.012
SHIFTS_SEMI = (-2.0, -1.0, 1.0, 2.0)
SWAP = (2, 3)  # 0-based: notes 3 and 4
MIN_MARGIN_CENTS = 20.0  # T must sit at least this far from the worst positive and from the best mistuning control
MAX_PITCH_T_CENTS = 50.0  # T must be below half a semitone
NULL_NOTE = "accepted by ear; no automated criterion separates this echo from the negative controls"

# The runs the owner listened to on 2026-11-25 (statement at about 14:55: the newest final run of each test in the
# index at that time). Stage 2: 20261125-145628-s2v2 was written at 14:57:45 (committed 14:58), after the statement,
# so the stage-2 run the owner judged is 20261125-122003-s2. These are the owner_v2 calibration positives and the only
# runs that carry a listening_verdict. Never follow "newest": a later run gets no verdict until the owner listens.
ACCEPTED_RUNS = {
    "s1_bird": "20261125-104529-s1",
    "s2_motif": "20261125-122003-s2",
    "s3_melody_100ms": "20261125-131152-s3",
    "s3_melody_60ms": "20261125-133244-s3_60ms",
    "s4a_ah": "20261125-142346-s4_4a_ah",
    "s4b_ma": "20261125-132102-s4_4b_ma",
    "s4b_ba": "20261125-134325-s4_4b_ba",
    "s4b_om": "20261125-135718-s4_4b_om",
    "s4c_hello": "20261125-124137-s4_4c_hello",
}

# Calibrated by stages/rescore.py with the rule above (its output is frozen here and re-checked on every rescore).
# None: no C2 for this test (speech) or no threshold exists (see the test's margin block).
THRESHOLDS_V2 = {
    "s1_bird": {"pitch_cents": 40.0},  # worst positive 14 c, best mistuning control 69 c
    "s2_motif": {"pitch_cents": None},  # r2: no threshold (accepted 20261125-122003-s2 worst note ~1144 c); r1's 240 c withdrawn
    "s3_melody_100ms": {"pitch_cents": None},  # no threshold exists: worst positive >= best mistuning control
    "s3_melody_60ms": {"pitch_cents": None},  # idem
    "s4a_ah": {},
    "s4b_ma": {},
    "s4b_ba": {},
    "s4b_om": {},
    "s4c_hello": {"c1": False},  # C1 fails the perfect echo (2/5 claps): judge-validity rule; C3 alone decides
}
TONAL = ("s1_bird", "s2_motif", "s3_melody_100ms", "s3_melody_60ms")
MULTI_NOTE = ("s2_motif", "s3_melody_100ms", "s3_melody_60ms")


# ------------------------------------------------------------------------------------------------------ helpers
def fit(x, n):
    """Trim or zero-pad the last axis to n samples (as the judges do)."""
    x = np.asarray(x, float)
    out = np.zeros(x.shape[:-1] + (n,))
    m = min(n, x.shape[-1])
    out[..., :m] = x[..., :m]
    return out


def logmel_v2(x, fs=FS):
    import librosa

    S = librosa.feature.melspectrogram(y=np.asarray(x, float), sr=fs, power=2.0, **MEL_V2)
    D = 10 * np.log10(S + 1e-30)
    D = np.maximum(D - D.max(), -FLOOR_DB_V2)
    return D - D.mean(axis=1, keepdims=True)


def dtw(A, B):
    """DTW over frames (columns), Euclidean frame distance, steps (1,0),(0,1),(1,1), normalised by n + m.
    Same recursion as metrics_speech._dtw, vectorised along anti-diagonals."""
    d = np.sqrt(((A[:, :, None] - B[:, None, :]) ** 2).sum(axis=0))
    n, m = d.shape
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for k in range(2, n + m + 1):  # cells (i, j), i + j = k, 1 <= i <= n, 1 <= j <= m
        i = np.arange(max(1, k - m), min(n, k - 1) + 1)
        j = k - i
        D[i, j] = d[i - 1, j - 1] + np.minimum(np.minimum(D[i - 1, j], D[i, j - 1]), D[i - 1, j - 1])
    return float(D[n, m] / (n + m))


def identify(seg, own, candidates, fs=FS, feats=None):
    """C1: {correct, margin (nearest other - own), nearest, distances}. `feats` may hold precomputed candidate
    features (name -> logmel_v2)."""
    E = logmel_v2(seg, fs)
    feats = feats or {k: logmel_v2(v, fs) for k, v in candidates.items()}
    dist = {k: dtw(E, F) for k, F in feats.items()}
    other = min(v for k, v in dist.items() if k != own)
    return {"correct": bool(dist[own] < other), "margin": float(other - dist[own]),
            "nearest": min(dist, key=dist.get), "distances": dist}


def intended_pitch(target, t):
    """Target's intended pitch (Hz) at times t and the interior mask (> PITCH_EDGE_S from every note boundary)."""
    tt, ff = target.f_track
    f = np.interp(t, tt, ff)
    if target.notes:
        b = np.array(sorted({n[1] for n in target.notes} | {n[2] for n in target.notes}))
    else:
        b = np.array([0.0, target.duration_s])
    m = (t >= b[0]) & (t <= b[-1]) & (np.min(np.abs(t[:, None] - b[None, :]), axis=1) > PITCH_EDGE_S)
    return f, m


def pitch_cents(seg, target, fs=FS):
    """C2: median over interior frames of |cents| between the pyin track and the intended pitch."""
    from echo.metrics import pitch_track

    t, f0, _ = pitch_track(seg, fs, fmin=PITCH_RANGE[0], fmax=PITCH_RANGE[1])
    f, m = intended_pitch(target, t)
    dev = np.abs(1200.0 * np.log2(np.maximum(f0, 1.0) / f))
    if not target.notes or len(target.notes) < 2:
        return float(np.median(dev[m]))
    per = []  # multi-note: median per note (its interior frames), value = worst note
    for (_, on, off) in target.notes:
        mm = m & (t > on) & (t < off)
        per.append(float(np.median(dev[mm])) if mm.any() else 1200.0)
    return float(max(per))


# -------------------------------------------------------------------------------------------- control builders
def time_reversed(x):
    return np.asarray(x, float)[..., ::-1].copy()


def phase_scrambled(x, band, seed=0, fs=FS):
    """Same magnitude spectrum (so the same long-term spectrum), uniform random phase inside the band, zero outside."""
    x = np.asarray(x, float)
    n = x.shape[-1]
    X = np.fft.rfft(x, axis=-1)
    f = np.fft.rfftfreq(n, 1.0 / fs)
    rng = np.random.default_rng(seed)
    ph = np.exp(2j * np.pi * rng.random(X.shape))
    ph[..., 0] = np.sign(X[..., 0].real) + (X[..., 0].real == 0)  # DC (and Nyquist) bins are real: keep them
    if n % 2 == 0:
        ph[..., -1] = np.sign(X[..., -1].real) + (X[..., -1].real == 0)
    inb = (f >= band[0]) & (f <= band[1])
    return np.fft.irfft(np.abs(X) * ph * inb, n=n, axis=-1)


def pitch_shifted(x, semitones):
    """Resample so every frequency is multiplied by 2**(semitones/12) (duration divided by it), then trim/pad."""
    from scipy.signal import resample

    x = np.asarray(x, float)
    n = x.shape[-1]
    r = 2.0 ** (semitones / 12.0)
    return fit(resample(x, int(round(n / r)), axis=-1), n)


def notes_swapped(x, notes, i=SWAP[0], j=SWAP[1], fs=FS):
    """Swap the time segments of notes i and j (equal-length notes; segments from the target's note timing)."""
    x = np.asarray(x, float).copy()
    a0, a1 = (int(round(notes[i][1] * fs)), int(round(notes[i][2] * fs)))
    b0, b1 = (int(round(notes[j][1] * fs)), int(round(notes[j][2] * fs)))
    sa, sb = x[..., a0:a1].copy(), x[..., b0:b1].copy()
    x[..., a0:a1], x[..., b0:b1] = sb, sa
    return x


def noise_burst(n, clap, band, seed=0, fs=FS):
    """'An echo with no structure in it': white noise coloured by the clap, band-limited, length n, 5 ms fades."""
    from echo.clap import band_limit
    from echo.targets import _fade

    w = np.random.default_rng(seed).standard_normal(n)
    y = band_limit(np.convolve(w, clap)[:n], band[0], band[1], fs=fs) * _fade(n, fs)
    return y / (np.max(np.abs(y)) or 1.0)


def clap_alone(clap, n):
    return fit(clap, n)


def perfect_echo(target_audio, clap, band, fs=FS):
    from echo.clap import band_limit

    return band_limit(np.convolve(target_audio, clap)[: len(target_audio)], band[0], band[1], fs=fs)


def near_miss_targets(test, target, seed=0, fs=FS):
    """Near-miss negatives (review r2), NOT in the C1 distractor set: altered versions of the target sound, to be
    played through each clap like a perfect echo. Tonal tests only."""
    from echo.clap import band_limit
    from echo.targets import _fade, bird_note, note_sequence

    n = len(target.audio)
    rng = np.random.default_rng(seed)
    out = {}
    env = np.sqrt(np.convolve(target.audio ** 2, np.ones(80) / 80, "same"))
    out["envelope_noise"] = band_limit(rng.standard_normal(n) * env, 500.0, 4000.0, fs=fs)
    if test == "s1_bird":
        d = target.duration_s
        gm = float(np.sqrt(3500.0 * 2000.0))
        out["steady_tone_mean_pitch"] = np.sin(2 * np.pi * gm * np.arange(n) / fs) * _fade(n, fs)
        out["rising_glide"] = bird_note(d, 2000.0, 3500.0, fs).audio
        out["partial_glide_upper"] = bird_note(d, 3500.0, gm, fs).audio
        out["partial_glide_lower"] = bird_note(d, gm, 2000.0, fs).audio
        out["time_compressed_glide"] = fit(bird_note(d / 2, 3500.0, 2000.0, fs).audio, n)
        return {k: fit(v / (np.max(np.abs(v)) or 1.0), n) for k, v in out.items()}
    freqs = [nt[0] for nt in target.notes]
    note_s = target.notes[0][2] - target.notes[0][1]
    i = next(k for k in range(len(freqs) - 1) if freqs[k] != freqs[k + 1])  # first adjacent distinct pair
    for c in (100, 300):
        f2 = list(freqs)
        f2[1] = f2[1] * 2 ** (c / 1200)
        out[f"wrong_note2_+{c}c"] = note_sequence(f2, note_s, "x", fs).audio
    f2 = list(freqs)
    f2[i], f2[i + 1] = f2[i + 1], f2[i]
    out[f"notes_{i + 1}_{i + 2}_swapped"] = note_sequence(f2, note_s, "x", fs).audio
    gm = float(np.exp(np.mean(np.log(freqs))))
    out["steady_tone_mean_pitch"] = note_sequence([gm], n / fs, "x", fs).audio
    lo, hi = 12 * np.log2(min(freqs) / 440.0) + 69, 12 * np.log2(max(freqs) / 440.0) + 69
    while True:
        midi = rng.integers(int(round(lo)) - 2, int(round(hi)) + 3, len(freqs))
        fr = [float(440.0 * 2 ** ((m - 69) / 12)) for m in midi]
        if any(abs(1200 * np.log2(a / b)) > 50 for a, b in zip(fr, freqs)):
            break
    out["random_sequence"] = note_sequence(fr, note_s, "x", fs).audio
    return {k: fit(v / (np.max(np.abs(v)) or 1.0), n) for k, v in out.items()}


def distractors(test, own_target, other_targets: dict):
    """C1 candidate set: {own name: own, other tests' targets..., own transforms...}, all at the own length."""
    n = len(own_target.audio)
    c = {test: own_target.audio}
    for k, v in other_targets.items():
        if k != test:
            c[k] = fit(v, n)
    c[f"{test}:reversed"] = time_reversed(own_target.audio)
    if test in TONAL:
        for s in SHIFTS_SEMI:
            c[f"{test}:shift{s:+.0f}"] = pitch_shifted(own_target.audio, s)
    if test in MULTI_NOTE:
        c[f"{test}:swap34"] = notes_swapped(own_target.audio, own_target.notes)
    return c


# ---------------------------------------------------------------------------------------------------- scoring
def clap_values(test, segs, target, candidates, fs=FS, feats=None, recognize=None):
    """Per-clap raw values for one echo [K, n]: list of {id_correct, id_margin, nearest, pitch_cents?, hello_hit?}."""
    out = []
    feats = feats or {k: logmel_v2(v, fs) for k, v in candidates.items()}
    for s in np.atleast_2d(segs):
        r = identify(s, test, candidates, fs, feats)
        v = {"id_correct": r["correct"], "id_margin": r["margin"], "nearest": r["nearest"]}
        if test in TONAL:
            v["pitch_cents"] = pitch_cents(s, target, fs)
        if test == "s4c_hello":
            v["hello_hit"] = bool((recognize or _recognize)(s))
        out.append(v)
    return out


def _recognize(seg):
    from echo import metrics_speech as MS

    return MS.recognize(seg)[0]


def majority_value(vals):
    """The value that decides a 3-of-5 vote for a '<=' criterion: the MAJORITY-th smallest."""
    return float(np.sort(np.asarray(vals, float))[MAJORITY - 1])


def rests_on(test, thr=None):
    """Plain statement of what an owner_v2 pass of this test rests on."""
    thr = THRESHOLDS_V2[test] if thr is None else thr
    parts = []
    if thr.get("c1", True):
        parts.append("C1 closed-set identification")
    if test in TONAL:
        parts.append(f"C2 pitch within {thr.get('pitch_cents')} c" + (" per note" if test in MULTI_NOTE else ""))
    if test == "s4c_hello":
        parts.append("C3 = the spec_v1 recognizer with the spec's 3-of-5 rule (same judge as spec_v1; owner_v2 adds "
                     "only the rejected controls, not an independent confirmation)")
    return "; ".join(parts) + f" (each on >= {MAJORITY} of 5 claps)"


def clap_passes(test, v, thr=None):
    thr = THRESHOLDS_V2[test] if thr is None else thr
    ok = bool(v["id_correct"]) if thr.get("c1", True) else True
    if test in TONAL:
        t = thr.get("pitch_cents")
        ok = ok and t is not None and v["pitch_cents"] <= t
    if test == "s4c_hello":
        ok = ok and bool(v["hello_hit"])
    return ok


def verdict(test, per_clap, thr=None):
    """Summary values and pass for one echo under owner_v2 (pass = >= MAJORITY claps pass every criterion)."""
    n_pass = sum(clap_passes(test, v, thr) for v in per_clap)
    vals = {"claps_pass": n_pass, "id_claps": int(sum(bool(v["id_correct"]) for v in per_clap)),
            "id_margin_median": float(np.median([v["id_margin"] for v in per_clap]))}
    if test in TONAL:
        vals["pitch_cents"] = majority_value([v["pitch_cents"] for v in per_clap])
    if test == "s4c_hello":
        vals["hello_claps"] = int(sum(bool(v["hello_hit"]) for v in per_clap))
    return vals, bool(n_pass >= MAJORITY)


def calibrate_pitch(pos_values, mistuning_values, step=5.0, min_margin=MIN_MARGIN_CENTS, cap=MAX_PITCH_T_CENTS):
    """Threshold rule for C2: midway between the worst positive and the best mistuning control (majority values),
    rounded to `step` cents; None unless it is >= min_margin from both sides and < cap.
    Returns (threshold or None, worst_positive, best_control)."""
    worst, best = float(max(pos_values)), float(min(mistuning_values))
    t = float(step * round((worst + best) / 2.0 / step))
    if t - worst < min_margin or best - t < min_margin or t >= cap:
        return None, worst, best
    return t, worst, best


def metric_entries(test, per_clap, thr=None):
    thr = THRESHOLDS_V2[test] if thr is None else thr
    pc = per_clap
    ents = [{"id": "id_claps", "label": "C1: claps whose echo is nearest its own target (closed set, log-mel DTW, 30 dB)",
             "value": float(sum(bool(v["id_correct"]) for v in pc)), "unit": "claps", "threshold": MAJORITY,
             "comparator": ">=", "pass": bool(sum(bool(v["id_correct"]) for v in pc) >= MAJORITY),
             "used": bool(thr.get("c1", True)),
             "per_clap": [{"clap": k, "correct": bool(v["id_correct"]), "margin": v["id_margin"],
                           "nearest": v["nearest"]} for k, v in enumerate(pc)]}]
    if test in TONAL:
        t = thr.get("pitch_cents")
        val = majority_value([v["pitch_cents"] for v in pc])
        ents.append({"id": "pitch_cents", "label": "C2: median pitch deviation (worst note for multi-note), 3rd-best clap",
                     "value": val, "unit": "cents", "threshold": t, "comparator": "<=",
                     "pass": None if t is None else bool(val <= t),
                     "per_clap": [v["pitch_cents"] for v in pc]})
    if test == "s4c_hello":
        h = int(sum(bool(v["hello_hit"]) for v in pc))
        ents.append({"id": "hello_claps", "label": "C3: claps recognized as \"hello\" (spec recognizer, unchanged)",
                     "value": float(h), "unit": "claps", "threshold": MAJORITY, "comparator": ">=",
                     "pass": bool(h >= MAJORITY), "per_clap": [bool(v["hello_hit"]) for v in pc]})
    n = sum(clap_passes(test, v, thr) for v in pc)
    ents.append({"id": "claps_pass", "label": "Claps passing every criterion (majority rule, verdict)",
                 "value": float(n), "unit": "claps", "threshold": MAJORITY, "comparator": ">=",
                 "pass": bool(n >= MAJORITY), "per_clap": [clap_passes(test, v, thr) for v in pc]})
    return ents


def score_v2(test, per_clap, controls, established, margin, note=None, thr=None):
    """The criteria.owner_v2 block for one run.

    per_clap: clap_values of the run's echo. controls: [{name, kind, per_clap}] (this test's fixed control set).
    established: the criterion separates (accepted + perfect echo pass, every control fails); if False -> null.
    """
    ctrl = []
    for c in controls:
        vals, ok = verdict(test, c["per_clap"], thr)
        ctrl.append({"name": c["name"], "kind": c["kind"], "values": vals, "pass": ok})
    _, ok = verdict(test, per_clap, thr)
    all_fail = not any(c["pass"] for c in ctrl)
    passed = ok if established else None
    return {"label": LABEL, "passed": passed, "rests_on": rests_on(test, thr), "metrics": metric_entries(test, per_clap, thr), "controls": ctrl,
            "controls_all_fail": bool(all_fail), "margin": margin,
            "note": note if note is not None else (None if established else NULL_NOTE)}


def spec_v1_block(metrics_json):
    """Compact mirror of the existing (spec) verdict; nothing recomputed."""
    return {"label": SPEC_V1_LABEL, "passed": bool(metrics_json["passed"]),
            "gating": [{k: m.get(k) for k in ("id", "label", "value", "unit", "threshold", "comparator", "pass", "tier")}
                       for m in metrics_json.get("metrics", []) if m.get("gating")]}
