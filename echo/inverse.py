"""Inverse design, step 1: solve a non-negative reflectivity profile on the 1 cm bistatic-range grid (Tier 0, 2D).

profile[i] >= 0 is Tier 0's convention: the equivalent number of reference posts (radius a_ref) in bistatic-range
bin rho = r0 + i*dr (echo time 2 rho / c). The profile is softplus-parameterized and optimized with Adam against a
multi-resolution STFT loss (auraloss) plus a log-mel L1 term, both on band-limited signals (clap band intersected with
the design band) inside the echo's time window only, averaged over the clap family. No raw waveform error.

Levels are normalized out: every echo and the target are divided by their own RMS inside the window before the loss
(scale-invariant; absolute echo level is set by physics and by the realization density, not by the loss). The
profile's overall scale is therefore free; `solve_profile` returns it normalized to mean 1 and the realization step
sets the physical scale (`echo.realize.scale_profile`).

The Tier 1 correction loop (Task 6) extends this module; it is not here yet.
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
        lo, hi = band
        f = np.fft.rfftfreq(MEL_N_FFT, 1.0 / fs)
        self._ok = None

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


def _bandlimit_torch(x, band, fs=FS):
    """Same zero-phase mask as echo.clap.band_limit, in torch (differentiable, batched over the first axis)."""
    n = x.shape[-1]
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    from echo.tier0 import band_mask

    f = np.fft.rfftfreq(nfft, 1.0 / fs)
    m = torch.as_tensor(band_mask(f, band[0], band[1], fs), dtype=x.dtype)
    return torch.fft.irfft(torch.fft.rfft(x, nfft, dim=-1) * m, nfft, dim=-1)[..., :n]


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
