"""Inverse design, step 1: solve a non-negative reflectivity profile on the 1 cm bistatic-range grid (Tier 0, 2D).

profile[i] >= 0 is Tier 0's convention: the equivalent number of reference posts (radius a_ref) in bistatic-range
bin rho = r0 + i*dr (echo time 2 rho / c). The profile is softplus-parameterized and optimized with Adam against a
multi-resolution STFT loss (auraloss) plus a log-mel L1 term, both on band-limited signals (clap band intersected with
the design band) inside the echo's time window only, averaged over the clap family. No raw waveform error.

Levels are normalized out: every echo and the target are divided by their own RMS inside the window before the loss
(scale-invariant; absolute echo level is set by physics and by the realization density, not by the loss). The
profile's overall scale is therefore free; `solve_profile` returns it normalized to mean 1 and the realization step
sets the physical scale (`echo.realize.scale_profile`).

Step 3, the Tier 1 correction loop (`correction_loop`, `window_gains`, `apply_window_gains`), is at the end.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn.functional as F

from echo.clap import band_limit
from echo.scene import BAND, C0, FS, Scene
from echo.tier0 import DR_PROFILE, profile_echo

R0_PROFILE = 3.06  # m, first profile bin (bistatic). Posts on rho = 3.0 can fail the polar r_min test.
LOSS_FFT_SIZES = (64, 128, 256, 512)  # STFT sizes suited to 80 ms+ signals at 16 kHz
LOSS_HOPS = (16, 32, 64, 128)
MEL_N_FFT, MEL_HOP, MEL_N = 256, 32, 40


def clap_band(claps, fs=FS, rel_db=-20.0, design_band=BAND):
    """Band where the family-mean clap power spectrum is within rel_db of its peak, intersected with design_band."""
    c = np.atleast_2d(np.asarray(claps, dtype=float))
    n = 4096
    P = np.mean(np.abs(np.fft.rfft(c, n, axis=-1)) ** 2, axis=0)
    f = np.fft.rfftfreq(n, 1.0 / fs)
    keep = f[10 * np.log10(P / P.max() + 1e-30) >= rel_db]
    lo, hi = float(keep.min()), float(keep.max())
    return (max(lo, design_band[0]), min(hi, design_band[1]))


def echo_window(r0, duration_s, n_clap, c=C0, fs=FS):
    """(n0, n_win): first sample of the echo window (first echo arrival 2 r0/c) and its length (target + clap)."""
    n0 = int(round(2.0 * r0 / c * fs))
    return n0, int(round(duration_s * fs)) + int(n_clap)


def _rms_norm(x, eps=1e-12):
    return x / (x.pow(2).mean(dim=-1, keepdim=True).sqrt() + eps)


class EchoLoss:
    """MR-STFT (auraloss) + log-mel L1, on band-limited, RMS-normalized signals [K, n_win] vs a target [n_win]."""

    def __init__(self, band, fs=FS, n_win=None, w_mel=1.0):
        import auraloss
        import librosa

        self.band, self.fs, self.w_mel = band, fs, w_mel
        self.mrstft = auraloss.freq.MultiResolutionSTFTLoss(
            fft_sizes=list(LOSS_FFT_SIZES), hop_sizes=list(LOSS_HOPS), win_lengths=list(LOSS_FFT_SIZES))
        fb = librosa.filters.mel(sr=fs, n_fft=MEL_N_FFT, n_mels=MEL_N, fmin=band[0], fmax=band[1])
        self.mel = torch.as_tensor(fb, dtype=torch.float32)
        self.win = torch.hann_window(MEL_N_FFT)

    def logmel(self, x):
        X = torch.stft(x, MEL_N_FFT, MEL_HOP, window=self.win, return_complex=True, center=True)
        m = torch.einsum("mf,kft->kmt", self.mel, X.abs() ** 2)
        return torch.log10(m + 1e-6)

    def __call__(self, echo_win, target_win):
        e = _rms_norm(echo_win.float())
        t = _rms_norm(target_win.float()).expand_as(e)
        l_stft = self.mrstft(e[:, None, :], t[:, None, :])
        l_mel = (self.logmel(e) - self.logmel(t)).abs().mean()
        return l_stft + self.w_mel * l_mel, float(l_stft.detach()), float(l_mel.detach())


def initial_profile(target_audio, n_rho, r0=R0_PROFILE, dr=DR_PROFILE, c=C0, fs=FS):
    """Physics initialization: smooth positive bias (the target's envelope) plus the target laid out along range
    (rho = r0 + c t / 2), times a 2D spreading compensation rho / r0. Normalized to mean 1."""
    from scipy.signal import hilbert
    from scipy.ndimage import uniform_filter1d

    a = np.asarray(target_audio, dtype=float)
    a = a / np.max(np.abs(a))
    rho = r0 + dr * np.arange(n_rho)
    t = 2.0 * (rho - r0) / c
    tt = np.arange(len(a)) / fs
    s = np.interp(t, tt, a, left=0.0, right=0.0)
    env = uniform_filter1d(np.abs(hilbert(a)), size=max(1, int(0.004 * fs)))
    env = np.maximum(env, np.abs(a))
    e = np.interp(t, tt, env, left=0.0, right=0.0)
    p = (e + s) * (rho / r0)
    p = np.maximum(p, 0.0) + 0.02 * p.max()
    return p / p.mean()


@dataclass
class SolveResult:
    profile: np.ndarray  # mean-normalized, >= 0
    r0: float
    dr: float
    band: tuple
    history: dict  # {"iters", "loss", "l_stft", "l_mel", "wall_s"}
    n0: int
    n_win: int
    n_out: int
    a_ref: float
    info: dict = field(default_factory=dict)


def solve_profile(target, claps, scene_cfg: Scene | None = None, *, duration_s=None, r0=R0_PROFILE, dr=DR_PROFILE,
                  a_ref=0.02, steps=300, lr=0.05, band=None, w_mel=1.0, n_out=None, log_every=5, init=None,
                  verbose=False):
    """Solve the profile. Returns (profile ndarray[n_rho] mean 1, SolveResult with history).

    target: echo.targets.Target or 1D audio at FS. claps: [K, Nc]. scene_cfg: Scene (geometry, c); its posts are
    ignored. The profile spans rho in [r0, r0 + c*duration/2]. Loss on mode="2d" profile_echo with band = clap band
    intersected with the design band. Grid, band and n_out stay fixed so Tier 0's profile plan is cached.
    """
    scene = scene_cfg if scene_cfg is not None else Scene()
    c = float(scene.c)
    audio = np.asarray(getattr(target, "audio", target), dtype=float)
    if duration_s is None:
        duration_s = len(audio) / FS
    cl = torch.as_tensor(np.atleast_2d(claps), dtype=torch.float64)
    band = tuple(band) if band is not None else clap_band(cl.numpy())
    n_rho = int(round(c * duration_s / 2.0 / dr)) + 1
    n0, n_win = echo_window(r0, duration_s, cl.shape[-1], c)
    if n_out is None:
        n_out = n0 + n_win + 16
    tgt = np.zeros(n_win)
    tgt[: len(audio)] = audio[:n_win]
    tgt = band_limit(tgt, band[0], band[1])
    tgt_t = torch.as_tensor(tgt, dtype=torch.float64)

    p0 = initial_profile(audio, n_rho, r0, dr, c) if init is None else np.asarray(init, float) / np.mean(init)
    theta = torch.as_tensor(np.log(np.expm1(np.maximum(p0, 1e-4))), dtype=torch.float64).requires_grad_(True)
    opt = torch.optim.Adam([theta], lr=lr)
    loss_fn = EchoLoss(band, n_win=n_win, w_mel=w_mel)

    hist = {"iters": [], "loss": [], "l_stft": [], "l_mel": []}
    best = (np.inf, None)
    t_start = time.time()
    for it in range(steps + 1):
        p = F.softplus(theta)
        e = profile_echo(p, cl, scene, mode="2d", n_out=n_out, a_ref=a_ref, r0=r0, dr=dr, band=band)
        loss, ls, lm = loss_fn(e[:, n0:n0 + n_win], tgt_t)
        lv = float(loss.detach())
        if lv < best[0]:
            best = (lv, p.detach().numpy().copy())
        if it % log_every == 0 or it == steps:
            hist["iters"].append(it)
            hist["loss"].append(lv)
            hist["l_stft"].append(ls)
            hist["l_mel"].append(lm)
            if verbose:
                print(f"step {it:4d} loss {lv:.4f} (stft {ls:.4f} mel {lm:.4f}) {time.time() - t_start:.1f}s",
                      flush=True)
        if it == steps:
            break
        opt.zero_grad()
        loss.backward()
        opt.step()
    hist["wall_s"] = time.time() - t_start
    prof = best[1] / best[1].mean()
    res = SolveResult(profile=prof, r0=r0, dr=dr, band=band, history=hist, n0=n0, n_win=n_win, n_out=n_out,
                      a_ref=a_ref, info={"best_loss": best[0], "init_loss": hist["loss"][0], "steps": steps,
                                         "lr": lr, "w_mel": w_mel,
                                         "normalization": "RMS per signal inside the echo window (scale-invariant)"})
    return prof, res


def window_loss(echo, target_audio, band, r0=R0_PROFILE, c=C0, n_clap=128):
    """Evaluate the solve loss on arbitrary echoes [K, n] (e.g. a realized post echo) for comparison."""
    audio = np.asarray(target_audio, dtype=float)
    n0, n_win = echo_window(r0, len(audio) / FS, n_clap, c)
    tgt = np.zeros(n_win)
    tgt[: len(audio)] = audio[:n_win]
    tgt = torch.as_tensor(band_limit(tgt, band[0], band[1]))
    e = torch.as_tensor(np.atleast_2d(np.asarray(echo)))[:, n0:n0 + n_win]
    e = torch.as_tensor(band_limit(e.numpy(), band[0], band[1]))
    with torch.no_grad():
        return float(EchoLoss(band)(e, tgt)[0])


# ------------------------------------------------------------------------------------- step 3: Tier 1 correction loop
CORR_WIN_S = 0.010  # correction window length (spec: "short time windows"; the spec's fallback uses 10 ms)
CORR_CLIP = (0.5, 2.0)  # per-window gain limits per round
CORR_FLOOR_DB = -25.0  # windows whose reference energy is below max - 25 dB keep gain 1 (fades, no information)


def reference_echo(target_audio, claps, t_echo0, n, band, fs=FS):
    """The physically perfect echo: target convolved with each clap, band-limited, placed at t_echo0. [K, n]."""
    a = np.asarray(target_audio, dtype=float)
    cl = np.atleast_2d(np.asarray(claps, dtype=float))
    i0 = int(round(t_echo0 * fs))
    out = np.zeros((len(cl), n))
    for k, c in enumerate(cl):
        y = np.convolve(a, c)[: max(0, n - i0)]
        out[k, i0:i0 + len(y)] = y
    return band_limit(out, band[0], band[1])


def window_gains(echo, reference, t_start, t_stop, win_s=CORR_WIN_S, fs=FS, clip=CORR_CLIP, floor_db=CORR_FLOOR_DB):
    """Per-window level correction (in band): g_w = sqrt(E_ref(w) / E_echo(w)) after scaling the reference to the
    echo's total energy over [t_start, t_stop), so only the shape over time is corrected, never the overall level.

    echo, reference: [K, n] (t = 0 emission), both already band-limited; energies are summed over the clap family.
    Windows tile [t_start, t_stop) with length win_s. Returns (t_centres_s, gains, info).
    """
    e = np.atleast_2d(np.asarray(echo, dtype=float))
    r = np.atleast_2d(np.asarray(reference, dtype=float))
    n0, n1 = int(round(t_start * fs)), int(round(t_stop * fs))
    L = int(round(win_s * fs))
    nw = max(1, int(np.ceil((n1 - n0) / L)))
    Ee, Er = np.zeros(nw), np.zeros(nw)
    for w in range(nw):
        a, b = n0 + w * L, min(n0 + (w + 1) * L, n1)
        Ee[w] = np.sum(e[:, a:b] ** 2)
        Er[w] = np.sum(r[:, a:b] ** 2)
    Er = Er * (Ee.sum() / max(Er.sum(), 1e-300))
    g = np.sqrt(Er / np.maximum(Ee, 1e-300))
    weak = Er < Er.max() * 10 ** (floor_db / 10)
    g[weak] = 1.0
    g = np.clip(g, clip[0], clip[1])
    tc = (n0 + (np.arange(nw) + 0.5) * L) / fs
    return tc, g, {"E_echo": Ee, "E_ref": Er, "weak": weak}


def apply_window_gains(profile, r0, dr, t_centres, gains, c=C0, t_offset=0.0, power=1.0):
    """Rescale a profile by per-window gains: bin rho echoes at 2 rho / c + t_offset (t_offset: the clap's energy
    centroid, where a bin's energy lands). Gains are interpolated linearly between window centres (held flat at the
    ends) and raised to `power` (damping, 1 = full step). Total mass (the post count / fill) is preserved."""
    p = np.asarray(profile, dtype=float)
    rho = r0 + dr * np.arange(len(p))
    tb = 2.0 * rho / c + t_offset
    g = np.interp(tb, t_centres, np.asarray(gains, dtype=float)) ** power
    q = p * g
    return q * (p.sum() / max(q.sum(), 1e-300))


def clap_centroid_s(claps, fs=FS):
    """Mean over the family of each clap's energy centroid time (s)."""
    cl = np.atleast_2d(np.asarray(claps, dtype=float))
    t = np.arange(cl.shape[1]) / fs
    return float(np.mean((cl ** 2 @ t) / np.sum(cl ** 2, axis=1)))


def stage_score(metrics: dict) -> float:
    """The stage's own score for the correction loop's keep-best / stop rule (spec step 3: "stop when the score
    stops improving"): the smallest relative margin over the GATING metrics, (thr - v)/thr for "<=" and
    (v - thr)/thr for ">="; positive means every gating metric passes. Used only to select among correction
    rounds, never inside a loss or a search objective."""
    m = [x for x in metrics["metrics"] if x["gating"] and x["threshold"] not in (None, 0)]
    if not m:
        return float("-inf")
    out = []
    for x in m:
        v, t = x["value"], float(x["threshold"])
        if v is None:
            return float("-inf")
        out.append((t - v) / abs(t) if x["comparator"] == "<=" else (v - t) / abs(t))
    return float(min(out))


@dataclass
class CorrectionRound:
    k: int
    profile: np.ndarray
    design: object  # stages.common.Design (kept generic here)
    tier1: object  # Tier1Result
    echo_t1: np.ndarray  # [K, n] band-limited
    metrics: dict
    loss: float
    score: float
    gains: np.ndarray | None = None
    wall_s: float = 0.0


def correction_loop(profile, build, run_t1, evaluate, reference, t_start, t_stop, *, r0, dr, c=C0, t_offset=0.0,
                    rounds=5, power=1.0, win_s=CORR_WIN_S, verbose=True, log=print, clip=CORR_CLIP):
    """Spec step 3. Round k: realize `profile_k` (build), run Tier 1 (run_t1), score it (evaluate), then rescale the
    profile per window against `reference` and go on. Stops after `rounds` Tier 1 runs or at the first round whose
    score does not improve on the best so far. Returns (rounds list, index of the best round by score).

    build(profile) -> design; run_t1(design) -> (Tier1Result, echo_t1 [K, n] band-limited);
    evaluate(design, echo_t1) -> (metrics dict, loss float, score float).
    The gains are computed from levels only (window energies in band) -- no judge is involved; the score only picks
    the round to keep and decides when to stop.
    """
    out, best = [], None
    p = np.asarray(profile, dtype=float)
    for k in range(rounds):
        t = time.time()
        des = build(p)
        res, e1 = run_t1(des)
        met, loss, score = evaluate(des, e1)
        tc, g, _ = window_gains(e1, reference, t_start, t_stop, win_s, clip=clip)
        rd = CorrectionRound(k, p, des, res, e1, met, loss, score, g, time.time() - t)
        out.append(rd)
        if verbose:
            log(f"correction round {k}: loss {loss:.4f} score {score:+.4f} gains {np.round(g, 2).tolist()} "
                f"({rd.wall_s:.0f} s)")
        if best is not None and score <= out[best].score:
            break
        if best is None or score > out[best].score:
            best = k
        p = apply_window_gains(p, r0, dr, tc, g, c, t_offset, power)
    return out, best


# ---------------------------------------------------------------- range-proportional stretch (effective-medium slowing)
def fit_stretch(echo_t1, echo_t0, n0, n1, fs=FS, eps_range=(-0.008, 0.004), tau_max=150e-6):
    """Judge-free fit of a range-proportional time warp between two echoes of the SAME posts:
    echo_t1(t) ~ g * echo_t0(t (1 + eps) + tau) on samples [n0, n1) (t = 0 at emission), summed over claps.

    eps < 0: Tier 1 arrives late in proportion to delay (the post field acts as a slower effective medium).
    Coarse grid (eps step 1e-4, tau step 10 us) then a fine grid around the best. Returns dict(eps, tau_s, corr)."""
    from scipy.interpolate import CubicSpline

    a = np.atleast_2d(np.asarray(echo_t0, dtype=float))
    b = np.atleast_2d(np.asarray(echo_t1, dtype=float))[:, n0:n1]
    t = np.arange(a.shape[-1]) / fs
    cs = CubicSpline(t, a, axis=-1)
    tt = t[n0:n1]
    bb = np.sqrt(np.sum(b * b))

    def corr(eps, tau):
        x = cs(tt * (1 + eps) + tau)
        return float(np.sum(x * b) / (np.sqrt(np.sum(x * x)) * bb + 1e-30))

    best = (0.0, 0.0, -2.0)
    for eps in np.arange(eps_range[0], eps_range[1] + 1e-12, 1e-4):
        for tau in np.linspace(-tau_max, tau_max, 31):
            c = corr(eps, tau)
            if c > best[2]:
                best = (float(eps), float(tau), c)
    e0, t0 = best[0], best[1]
    for eps in np.linspace(e0 - 1e-4, e0 + 1e-4, 11):
        for tau in np.linspace(t0 - 10e-6, t0 + 10e-6, 11):
            c = corr(eps, tau)
            if c > best[2]:
                best = (float(eps), float(tau), c)
    return {"eps": best[0], "tau_s": best[1], "corr": best[2]}


def compose_stretch(eps_applied, eps_residual):
    """Compose two warps: ranges scaled by (1 + eps_applied), then by (1 + eps_residual). Use it with a residual
    measured against the intended timing (e.g. Tier 1 vs Tier 0 of the UNWARPED design); a fit of Tier 1 against
    Tier 0 of the same warped posts is the medium's stretch itself and replaces, not composes."""
    return (1.0 + eps_applied) * (1.0 + eps_residual) - 1.0
