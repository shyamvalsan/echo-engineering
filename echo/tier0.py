"""Tier 0: single-scattering forward model (fast, differentiable, PyTorch, CPU, float64).

Every post returns a delayed, scaled, filtered copy of the clap. No shadowing, no multiple scattering.

Conventions
-----------
* Physics is derived with time dependence e^{-i w t} (outgoing waves e^{+ikr}, Hankel H^(1)). Signals use the
  DSP convention of numpy/torch rfft (X(f) = sum x[n] e^{-i 2 pi f n/fs}, so a delay tau is e^{-i w tau}).
  A physics phasor P(w) maps to the DSP spectrum conj(P(w)) for f > 0. Every transfer function returned here is
  in the DSP convention: irfft of it is a causal impulse response with t = 0 at clap emission.
* Normalization (global constraints): Echo_k(f) = C_k(f) * H(f) with
  H(f) = conj(H_scat / H_direct) * exp(-i 2 pi f |SL| / c),  C_k = rfft of clap k (direct arrival, delay removed).
  So echoes are pressure relative to the direct clap at the listener, and a post at bistatic range rho echoes at
  2 rho / c. Air absorption (ISO 9613-1, 20 C, 50 % RH) is applied per path, over the extra path L - |SL|.
* Cylinder: rigid, radius a, incident plane wave of unit amplitude. Scattered far field
  p_s = sqrt(2/(pi k r)) e^{i(kr - pi/4)} T(phi),  T(phi) = sum_n eps_n A_n cos(n phi),  A_n = -J_n'(ka)/H_n'(ka),
  eps_0 = 1, eps_n = 2, phi = scattering angle from the forward direction (pi = backscatter).
  Limits: ka -> 0: T(pi) = -i (3 pi/4) (ka)^2 (Rayleigh); ka >> 1: |T(pi)| = sqrt(pi ka)/2 (geometric optics).
  The incident field is treated as a plane wave at the post (posts are >= 3 m away, ka <= ~6 in band).

mode="2d" (line source, matches the 2D full-wave solver)
  H_direct = (i/4) H0(k d),  H_scat = (i/4) H0(k r1) T(phi) H0(k r2), exact Hankel functions for both legs and
  the direct path (r1 = |P-S|, r2 = |P-L|, d = |SL|). Writing H0(x) = sqrt(2/(pi x)) e^{i(x - pi/4)} Q(x)
  (Q -> 1 for large x; tabulated exactly below):
      H(f) = sqrt(2 d / (pi k r1 r2)) e^{i pi/4} conj(Q(kr1) Q(kr2) T / Q(kd)) e^{-ik(r1+r2)}.
mode="3d" (point source, vertical post much taller than the first Fresnel zone, listener in the same plane)
  Expand the point-source field over axial wavenumbers: e^{ikR}/(4 pi R) = (1/2pi) int dkz e^{i kz z} (i/4) H0(kt rho),
  kt = sqrt(k^2 - kz^2). Each kz is a 2D problem, so with S and L at z = 0
      p_s = (1/2pi) int dkz (i/4) H0(kt r1) T(kt a, phi) H0(kt r2).
  Large-argument Hankels give the phase kt (r1 + r2) ~ kL - kz^2 L/(2k), L = r1 + r2; stationary phase at kz = 0,
  int e^{-i kz^2 L/(2k)} dkz = sqrt(2 pi k/L) e^{-i pi/4}, gives
      p_s = (1/4pi) sqrt(2/(pi k)) T(ka, phi) e^{i(kL - pi/4)} / sqrt(r1 r2 L),
  i.e. the 2D angular form function with a 3D spreading factor. Divided by H_direct = e^{ikd}/(4 pi d):
      H(f) = d sqrt(2 / (pi k r1 r2 L)) e^{i pi/4} conj(T) e^{-ikL}.
  Check (geometric optics, ka >> 1, backscatter, r1 = r2 = r): |H| = d sqrt(a) / (2 r^1.5), which is the convex
  mirror result: wavefront radii 2r (vertical, flat mirror) and r + a/2 (horizontal, focal length a/2) give
  |p_s| = (1/(4 pi r)) sqrt(r (a/2) / (2r (r + a/2))). Both modes are frequency-flat in that limit.

Public functions
  cylinder_response(radius, f, angle=pi, c=C0)            T(phi), numpy (scipy series)
  post_transfer(posts, scene, mode, n_fft, ...)            H(f) summed over posts, complex Tensor[n_fft//2+1]
  post_echo(posts, claps, scene, mode, n_out, ...)         Tensor[K, n_out]
  profile_echo(profile, claps, scene, mode, n_out, ...)    Tensor[K, n_out], 1D model on the wedge axis
Gradients flow to post positions (x, y) and to the profile; radii are treated as constants.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import scipy.special as sp
import torch

from echo.scene import C0, FS, R_MIN, alpha_db_per_m, ellipse_point

DTYPE = torch.float64
CDTYPE = torch.complex128
DR_PROFILE = 0.01  # m, profile bin width in bistatic range
_E_IPI4 = complex(math.cos(math.pi / 4), math.sin(math.pi / 4))
_RADIUS_QUANT = 1e-5  # m, radii are grouped to 0.01 mm when building partial-wave tables
_NODE_RATIO = 1.01  # profile model: geometric spacing of the rho nodes the transfer is interpolated between


# ----------------------------------------------------------------------------------------------- cylinder


def _n_terms(ka_max: float) -> int:
    return int(ka_max + 4.05 * max(ka_max, 1e-9) ** (1.0 / 3.0) + 10)


def _partial_wave_coeffs(ka: np.ndarray, n_max: int) -> np.ndarray:
    """eps_n * A_n(ka), shape ka.shape + (n_max + 1,). A_n = -J_n'(ka) / H_n^(1)'(ka); zero at ka = 0."""
    ka = np.asarray(ka, dtype=float)
    n = np.arange(n_max + 1)
    x = np.where(ka > 0, ka, 1.0)[..., None]
    with np.errstate(all="ignore"):
        a = -sp.jvp(n, x) / sp.h1vp(n, x)
    a = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
    a = np.where(ka[..., None] > 0, a, 0.0)
    eps = np.where(n == 0, 1.0, 2.0)
    return a * eps


def cylinder_response(radius, f, angle=np.pi, c=C0):
    """Far-field form function T of a rigid cylinder (incident plane wave of unit amplitude), e^{-iwt} convention.

    p_s = sqrt(2/(pi k r)) e^{i(kr - pi/4)} T. `angle` is the scattering angle (pi = backscatter). Broadcasts.
    """
    ka = 2 * np.pi * np.asarray(f, dtype=float) * np.asarray(radius, dtype=float) / c
    angle = np.asarray(angle, dtype=float)
    ka, angle = np.broadcast_arrays(ka, angle)
    coef = _partial_wave_coeffs(ka, _n_terms(float(ka.max(initial=0.0))))
    n = np.arange(coef.shape[-1])
    return np.sum(coef * np.cos(n * angle[..., None]), axis=-1)


def _backscatter_table(radius_q: float, c: float, fs: float, n_fft: int, k0: int, k1: int) -> torch.Tensor:
    """B[f, n] = (-1)^n eps_n A_n(k a) on rfft bins k0..k1-1, so that T(pi - delta) = sum_n B_n cos(n delta)."""
    return _backscatter_table_full(radius_q, c, fs, n_fft)[k0:k1]


@lru_cache(maxsize=512)
def _backscatter_table_full(radius_q: float, c: float, fs: float, n_fft: int) -> torch.Tensor:
    f = np.arange(n_fft // 2 + 1) * fs / n_fft
    ka = 2 * np.pi * f * radius_q / c
    coef = _partial_wave_coeffs(ka, _n_terms(float(ka.max(initial=0.0))))
    coef = coef * (-1.0) ** np.arange(coef.shape[-1])
    return torch.as_tensor(coef, dtype=CDTYPE)


# ------------------------------------------------------------------------------------------------ Hankel H0

# H0^(1)(x) = sqrt(2/(pi x)) e^{i(x - pi/4)} Q(x). Q is smooth; large x: Hankel's asymptotic series,
# small x: a dense table in log x (linear interpolation, relative error ~1e-7).
_X_ASY = 12.0
_LOGX = np.linspace(np.log(1e-5), np.log(_X_ASY), 40001)
_xt = np.exp(_LOGX)
_QT = sp.hankel1(0, _xt) * np.sqrt(np.pi * _xt / 2) * np.exp(-1j * (_xt - np.pi / 4))
_Q_RE = torch.as_tensor(_QT.real, dtype=DTYPE)
_Q_IM = torch.as_tensor(_QT.imag, dtype=DTYPE)
_DU = float(_LOGX[1] - _LOGX[0])
# Q(x) = sum_k i^k a_k / x^k,  a_k = prod_{j=1..k} (-(2j-1)^2) / (k! 8^k); terms to k = 7 (error < 2e-8 at x >= 12).
# Even k are real, odd k imaginary: Q = sum_j (-1)^j a_2j z^j + i y sum_j (-1)^j a_2j+1 z^j, y = 1/x, z = y^2.
_ASY = [1.0]
for _k in range(1, 8):
    _ASY.append(_ASY[-1] * (-((2 * _k - 1) ** 2)) / (_k * 8.0))
_ASY_RE = [_ASY[2 * j] * (-1) ** j for j in range(4)]
_ASY_IM = [_ASY[2 * j + 1] * (-1) ** j for j in range(4)]


def _poly(coefs, z):
    out = torch.full_like(z, coefs[-1])
    for c_ in reversed(coefs[:-1]):
        out = out * z + c_
    return out


def hankel_q(x: torch.Tensor) -> torch.Tensor:
    """Q(x) = H0^(1)(x) sqrt(pi x/2) e^{-i(x - pi/4)} for real x > 0, differentiable in x."""
    y = 1.0 / x.clamp(min=1e-5)
    z = y * y
    out = torch.complex(_poly(_ASY_RE, z), y * _poly(_ASY_IM, z))
    small = x < _X_ASY
    if bool(small.any()):
        xs = x[small].clamp(min=1e-5, max=_X_ASY)
        u = (torch.log(xs) - float(_LOGX[0])) / _DU
        i0 = u.detach().floor().long().clamp(0, len(_LOGX) - 2)
        w = u - i0.to(DTYPE)
        re = _Q_RE[i0] + w * (_Q_RE[i0 + 1] - _Q_RE[i0])
        im = _Q_IM[i0] + w * (_Q_IM[i0 + 1] - _Q_IM[i0])
        out = out.masked_scatter(small, torch.complex(re, im))
    return out


# ----------------------------------------------------------------------------------------------- helpers


def band_mask(f, f_lo, f_hi, fs=FS):
    """Zero-phase band mask on frequencies f (Hz): the same raised-cosine edges as echo.clap.band_limit."""
    f = np.asarray(f, dtype=float)
    mask = np.ones_like(f)
    if f_lo is not None and f_lo > 0:
        w = max(50.0, 0.25 * f_lo)
        mask *= 0.5 - 0.5 * np.cos(np.pi * np.clip((f - (f_lo - w / 2)) / w, 0.0, 1.0))
    if f_hi is not None and f_hi < fs / 2:
        w = max(50.0, 0.25 * f_hi)
        mask *= 0.5 - 0.5 * np.cos(np.pi * np.clip(((f_hi + w / 2) - f) / w, 0.0, 1.0))
    return mask


def choose_n_fft(n_out: int, max_delay_s: float, n_clap: int, fs=FS) -> int:
    """FFT length covering the output, the last echo plus the clap, and a 1024-sample tail margin."""
    n_need = max(int(n_out), int(math.ceil(max_delay_s * fs)) + int(n_clap))
    return int(2 ** math.ceil(math.log2(n_need + 1024)))


def _bins(n_fft, fs, band):
    """rfft bins (k0, k1) where the model is evaluated (DC excluded), and the band mask on them."""
    n_freq = n_fft // 2 + 1
    f = np.arange(n_freq) * fs / n_fft
    mask = band_mask(f, *band, fs=fs) if band is not None else np.ones(n_freq)
    mask[0] = 0.0
    nz = np.nonzero(mask > 0)[0]
    if len(nz) == 0:
        return 1, 1, mask
    return int(nz[0]), int(nz[-1]) + 1, mask


def _as_posts(posts):
    if isinstance(posts, torch.Tensor):
        return posts.to(DTYPE)
    return torch.as_tensor(np.asarray(posts, dtype=float).reshape(-1, 3), dtype=DTYPE)


def _geometry(xy, source, listener):
    """r1 = |P-S|, r2 = |P-L|, delta = angle at P between the directions to S and to L (pi - scattering angle)."""
    s = torch.as_tensor(np.asarray(source, dtype=float), dtype=DTYPE)
    l = torch.as_tensor(np.asarray(listener, dtype=float), dtype=DTYPE)
    v1, v2 = s - xy, l - xy
    r1 = torch.linalg.norm(v1, dim=-1)
    r2 = torch.linalg.norm(v2, dim=-1)
    cross = v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0]
    dot = (v1 * v2).sum(-1)
    return r1, r2, torch.atan2(cross, dot)


def _form_function(delta, radius, c, fs, n_fft, k0, k1):
    """T(pi - delta) per post on bins k0..k1-1: [N, F] complex, partial-wave tables grouped by (quantized) radius."""
    rq = np.round(np.asarray(radius, dtype=float) / _RADIUS_QUANT) * _RADIUS_QUANT
    T = torch.zeros(len(delta), k1 - k0, dtype=CDTYPE)
    for a in np.unique(rq):
        idx = torch.as_tensor(np.nonzero(rq == a)[0])
        B = _backscatter_table(float(a), float(c), float(fs), int(n_fft), int(k0), int(k1))
        cosn = torch.cos(delta[idx, None] * torch.arange(B.shape[1], dtype=DTYPE))
        T[idx] = cosn.to(CDTYPE) @ B.T
    return T


def _sl_dist(scene):
    return float(np.linalg.norm(np.asarray(scene.listener, float) - np.asarray(scene.source, float)))


def _reduced_transfer(r1, r2, delta, radius, scene, mode, n_fft, fs, k0, k1, absorption):
    """H(f) e^{+ik(r1+r2)} for each post on bins k0..k1-1: [N, F] complex (everything except the pure delay).

    Reference implementation (exact Q table for every element). post_transfer uses an equivalent fast path.
    """
    c = float(scene.c)
    d = _sl_dist(scene)
    f = torch.arange(k0, k1, dtype=DTYPE) * (fs / n_fft)
    k = 2 * math.pi * f / c
    T = _form_function(delta, radius, c, fs, n_fft, k0, k1)
    L = r1 + r2
    if mode == "2d":
        x1, x2 = k * r1[:, None], k * r2[:, None]
        qd = hankel_q(k * d)
        amp = torch.sqrt(2 * d / (math.pi * x1 * r2[:, None]))
        R = amp * _E_IPI4 * torch.conj(hankel_q(x1) * hankel_q(x2) * T / qd)
    elif mode == "3d":
        amp = d * torch.sqrt(2.0 / (math.pi * k * (r1 * r2 * L)[:, None]))
        R = amp * _E_IPI4 * torch.conj(T)
    else:
        raise ValueError(f"mode must be '2d' or '3d', got {mode!r}")
    if absorption:
        alpha = torch.as_tensor(alpha_db_per_m(f.numpy()), dtype=DTYPE)
        R = R * torch.pow(10.0, -alpha * (L - d)[:, None] / 20.0)
    return R


# log Q(x) = sum_k l_k / x^k for x >= _X_ASY (power-series logarithm of Hankel's series), used by the fast path.
_QS = [(1j) ** k * a for k, a in enumerate(_ASY)]
_LOGQ = [0j]
for _k in range(1, len(_QS)):
    _LOGQ.append(_QS[_k] - sum(_j * _LOGQ[_j] * _QS[_k - _j] for _j in range(1, _k)) / _k)


def _post_sum_fast(r1, r2, delta, radius, scene, mode, n_fft, fs, k0, k1, absorption):
    """sum_p H_p(f) on bins k0..k1-1, requires k r >= _X_ASY on both legs (2d). Same maths as _reduced_transfer
    times the delay, but every (post, frequency) exponent -ikL - alpha (L-d) ln10/20 + conj(log Q1 + log Q2) is a
    sum of outer products, so it is one real matmul per part and a single complex exp per element."""
    c = float(scene.c)
    d = _sl_dist(scene)
    f = torch.arange(k0, k1, dtype=DTYPE) * (fs / n_fft)
    k = 2 * math.pi * f / c
    T = _form_function(delta, radius, c, fs, n_fft, k0, k1)
    L = r1 + r2
    a_re, b_re = [], []
    a_im, b_im = [L[:, None]], [-k[None, :]]
    if absorption:
        alpha = torch.as_tensor(alpha_db_per_m(f.numpy()), dtype=DTYPE)
        a_re.append((L - d)[:, None])
        b_re.append(-alpha[None, :] * (math.log(10.0) / 20.0))
    if mode == "2d":
        qd = hankel_q(k * d)
        w = torch.sqrt(2 * d / (math.pi * k)) * _E_IPI4 * torch.conj(1.0 / qd)  # per-frequency factor
        amp_p = 1.0 / torch.sqrt(r1 * r2)
        for j in range(1, len(_LOGQ)):
            a_j = (r1 ** (-j) + r2 ** (-j))[:, None]
            kj = k[None, :] ** (-j)
            lc = _LOGQ[j].conjugate()
            if lc.real != 0.0:
                a_re.append(a_j)
                b_re.append(lc.real * kj)
            if lc.imag != 0.0:
                a_im.append(a_j)
                b_im.append(lc.imag * kj)
    elif mode == "3d":
        w = (d * torch.sqrt(2.0 / (math.pi * k))).to(CDTYPE) * _E_IPI4
        amp_p = 1.0 / torch.sqrt(r1 * r2 * L)
    else:
        raise ValueError(f"mode must be '2d' or '3d', got {mode!r}")
    e_im = torch.cat(a_im, 1) @ torch.cat(b_im, 0)
    e_re = torch.cat(a_re, 1) @ torch.cat(b_re, 0) if a_re else torch.zeros_like(e_im)
    terms = torch.conj(T) * torch.exp(torch.complex(e_re, e_im))
    return w * (amp_p.to(CDTYPE) @ terms)


# ------------------------------------------------------------------------------------------------- posts


def post_transfer(posts, scene, mode="2d", n_fft=4096, fs=FS, band=None, absorption=True, chunk=4096):
    """Sum over posts of H(f) = conj(H_scat/H_direct) e^{-i 2 pi f |SL|/c}, on the rfft grid of length n_fft.

    posts: [N, 3] (x, y, radius), tensor (gradients flow to x, y) or array. Returns complex Tensor[n_fft//2 + 1];
    irfft(H, n_fft) is the impulse response re the direct clap, t = 0 at emission. `band` = (f_lo, f_hi) applies the
    zero-phase mask of echo.clap.band_limit.
    """
    if mode not in ("2d", "3d"):
        raise ValueError(f"mode must be '2d' or '3d', got {mode!r}")
    p = _as_posts(posts)
    k0, k1, mask = _bins(n_fft, fs, band)
    H = torch.zeros(n_fft // 2 + 1, dtype=CDTYPE)
    if len(p) == 0 or k1 <= k0:
        return H
    c = float(scene.c)
    radius = p[:, 2].detach().numpy()
    acc = torch.zeros(k1 - k0, dtype=CDTYPE)
    for s in range(0, len(p), chunk):
        xy = p[s : s + chunk, :2]
        r1, r2, delta = _geometry(xy, scene.source, scene.listener)
        rad = radius[s : s + chunk]
        # Bins where some leg has k r < _X_ASY (2d only) go through the exact-table reference path.
        ks = k0
        if mode == "2d":
            r_min = float(torch.minimum(r1, r2).detach().min())
            ks = min(k1, max(k0, int(math.ceil(_X_ASY * c / (2 * math.pi * r_min) * n_fft / fs))))
        parts = []
        if ks > k0:
            f = torch.arange(k0, ks, dtype=DTYPE) * (fs / n_fft)
            R = _reduced_transfer(r1, r2, delta, rad, scene, mode, n_fft, fs, k0, ks, absorption)
            phase = torch.polar(torch.ones_like(R.real), -2 * math.pi * f[None, :] * ((r1 + r2) / c)[:, None])
            parts.append((R * phase).sum(0))
        if k1 > ks:
            parts.append(_post_sum_fast(r1, r2, delta, rad, scene, mode, n_fft, fs, ks, k1, absorption))
        acc = acc + torch.cat(parts)
    H = torch.cat([H[:k0], acc, H[k1:]])
    return H * torch.as_tensor(mask, dtype=DTYPE)


def _as_claps(claps):
    c = claps if isinstance(claps, torch.Tensor) else torch.as_tensor(np.asarray(claps, dtype=float))
    c = c.to(DTYPE)
    return c[None, :] if c.ndim == 1 else c


def _default_n_out(max_delay_s, n_clap, fs):
    return int(math.ceil(max_delay_s * fs)) + n_clap + int(0.01 * fs)


def post_echo(posts, claps, scene, mode="2d", n_out=None, band=None, absorption=True, fs=FS, n_fft=None):
    """Echo of every clap variant from the posts: Tensor[K, n_out], pressure re the direct clap, t = 0 at emission.

    posts: [N, 3] tensor or array (None: scene.posts). claps: [K, Nc] (or [Nc]). n_out None: last echo + clap + 10 ms.
    """
    p = _as_posts(scene.posts if posts is None else posts)
    cl = _as_claps(claps)
    if len(p):
        r1, r2, _ = _geometry(p[:, :2].detach(), scene.source, scene.listener)
        max_delay = float((r1 + r2).max()) / float(scene.c)
    else:
        max_delay = 0.0
    if n_out is None:
        n_out = _default_n_out(max_delay, cl.shape[-1], fs)
    if n_fft is None:
        n_fft = choose_n_fft(n_out, max_delay, cl.shape[-1], fs)
    H = post_transfer(p, scene, mode=mode, n_fft=n_fft, fs=fs, band=band, absorption=absorption)
    C = torch.fft.rfft(cl, n=n_fft, dim=-1)
    return torch.fft.irfft(C * H, n=n_fft, dim=-1)[:, :n_out]


# ----------------------------------------------------------------------------------------------- profile


def _czt(x, t0, dt, df, k0, n_freq):
    """X[m, j] = sum_n x[m, n] exp(-i 2 pi f_j t_n), f_j = (k0 + j) df, t_n = t0 + n dt (Bluestein, exact)."""
    n_in = x.shape[-1]
    theta = 2 * math.pi * df * dt
    n = torch.arange(n_in, dtype=DTYPE)
    j = torch.arange(n_freq, dtype=DTYPE)
    a = x * torch.polar(torch.ones_like(n), -(2 * math.pi * k0 * df * dt) * n - 0.5 * theta * n * n)
    n_conv = int(2 ** math.ceil(math.log2(n_in + n_freq - 1)))
    m = torch.cat([torch.arange(n_freq, dtype=DTYPE), torch.arange(-(n_in - 1), 0, dtype=DTYPE)])
    b = torch.zeros(n_conv, dtype=CDTYPE)
    b[:n_freq] = torch.polar(torch.ones(n_freq, dtype=DTYPE), 0.5 * theta * m[:n_freq] ** 2)
    if n_in > 1:
        b[n_conv - (n_in - 1) :] = torch.polar(torch.ones(n_in - 1, dtype=DTYPE), 0.5 * theta * m[n_freq:] ** 2)
    y = torch.fft.ifft(torch.fft.fft(a, n=n_conv, dim=-1) * torch.fft.fft(b), dim=-1)[..., :n_freq]
    fj = (k0 + j) * df
    return y * torch.polar(torch.ones_like(j), -0.5 * theta * j * j - 2 * math.pi * fj * t0)


@lru_cache(maxsize=32)
def _profile_plan(mode, a_ref, r0, dr, n_rho, n_fft, fs, c, src, lst, k0, k1, absorption):
    """Low-rank factorization of the on-axis reduced transfer: R(rho_i, f) = sum_m U[m, i] V[m, f].

    R is evaluated exactly at geometric rho nodes (ratio 1.01), factored by SVD (relative cutoff 1e-9) and the
    left factors are interpolated linearly in rho to the profile bins.
    """
    from echo.scene import Scene

    sc = Scene(source=np.array(src), listener=np.array(lst), c=c)
    rho_end = max(r0 + (n_rho - 1) * dr, r0 + dr)
    n_nodes = max(2, int(math.ceil(math.log(rho_end / r0) / math.log(_NODE_RATIO))) + 1)
    rho_nodes = r0 * (rho_end / r0) ** np.linspace(0.0, 1.0, n_nodes)
    xy = torch.as_tensor(ellipse_point(rho_nodes, 0.0, sc.source, sc.listener), dtype=DTYPE)
    r1, r2, delta = _geometry(xy, sc.source, sc.listener)
    R = _reduced_transfer(r1, r2, delta, np.full(n_nodes, a_ref), sc, mode, n_fft, fs, k0, k1, absorption).numpy()
    u, s, vh = np.linalg.svd(R, full_matrices=False)
    m = int(np.sum(s > 1e-9 * s[0])) if s[0] > 0 else 1
    uf = u[:, :m] * s[:m]
    rho = r0 + np.arange(n_rho) * dr
    U = np.stack([np.interp(rho, rho_nodes, uf[:, i].real) + 1j * np.interp(rho, rho_nodes, uf[:, i].imag) for i in range(m)])
    return torch.as_tensor(U, dtype=CDTYPE), torch.as_tensor(vh[:m], dtype=CDTYPE)


def profile_transfer(profile, scene, mode="2d", n_fft=4096, a_ref=0.02, r0=R_MIN, dr=DR_PROFILE, fs=FS, band=None,
                     absorption=True):
    """H(f) of a reflectivity profile: profile[i] >= 0 reference posts (radius a_ref) at bistatic range r0 + i dr
    on the wedge axis. Same units and convention as post_transfer. Differentiable in profile."""
    prof = profile if isinstance(profile, torch.Tensor) else torch.as_tensor(np.asarray(profile, dtype=float))
    prof = prof.to(DTYPE)
    k0, k1, mask = _bins(n_fft, fs, band)
    H = torch.zeros(n_fft // 2 + 1, dtype=CDTYPE)
    if k1 <= k0 or len(prof) == 0:
        return H
    c = float(scene.c)
    U, V = _profile_plan(mode, float(a_ref), float(r0), float(dr), len(prof), int(n_fft), float(fs), c,
                         tuple(map(float, scene.source)), tuple(map(float, scene.listener)), k0, k1, bool(absorption))
    X = _czt(prof.to(CDTYPE)[None, :] * U, 2 * r0 / c, 2 * dr / c, fs / n_fft, k0, k1 - k0)
    acc = (V * X).sum(0)
    H = torch.cat([H[:k0], acc, H[k1:]])
    return H * torch.as_tensor(mask, dtype=DTYPE)


def profile_echo(profile, claps, scene, mode="2d", n_out=None, a_ref=0.02, r0=R_MIN, dr=DR_PROFILE, band=None,
                 absorption=True, fs=FS, n_fft=None):
    """Fast 1D model for the profile solve: Tensor[K, n_out], same units as post_echo.

    profile[i] >= 0 is the equivalent number of reference posts of radius a_ref in bistatic-range bin r0 + i dr,
    on the wedge axis (equals post_echo of those posts placed with ellipse_point(rho, 0)).
    """
    cl = _as_claps(claps)
    n_rho = int(profile.shape[-1]) if isinstance(profile, torch.Tensor) else len(profile)
    max_delay = 2 * (r0 + (n_rho - 1) * dr) / float(scene.c)
    if n_out is None:
        n_out = _default_n_out(max_delay, cl.shape[-1], fs)
    if n_fft is None:
        n_fft = choose_n_fft(n_out, max_delay, cl.shape[-1], fs)
    H = profile_transfer(profile, scene, mode=mode, n_fft=n_fft, a_ref=a_ref, r0=r0, dr=dr, fs=fs, band=band,
                         absorption=absorption)
    C = torch.fft.rfft(cl, n=n_fft, dim=-1)
    return torch.fft.irfft(C * H, n=n_fft, dim=-1)[:, :n_out]
