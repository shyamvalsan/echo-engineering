"""Tier 1: full-wave 2D solver (the referee).

Engine (DECISIONS.md, task 3): our own staggered-grid FDTD for linear acoustics. It uses 8th-order spatial stencils
in free air, leapfrog time stepping and numba kernels (CPU, float32, all cores). In a thin band around every post the
stencil blends to the 2nd-order (Yee) one, so a zero face velocity is an exact rigid wall and no wide stencil reaches
across a solid. Split-field PML on every edge.

Dispersion: the scheme carries physical wavenumber k at a slightly lower frequency w', where
2 sin(w' dt/2)/dt = c k_fd(k) and k_fd is the 8th-order modified wavenumber along a grid axis. Spectra are read at
w'(w) (`sim_frequency`), so the timing of every path is that of the physical medium. The wedge axis and the
source-listener line are grid axes. The off-axis residual is < 4e-5 at 5 points per wavelength (ppw).

Rigid posts, with sub-cell (area-fraction) rasterization. phi is the covered area fraction of a cell (or face cell),
supersampled and renormalized per post so that sum(phi) dx^2 = pi r^2 * area_scale.
  velocity faces: (1/rho)/(1/rho0) = (1 - phi)/(1 + phi)   (0 when fully covered: immovable)
  pressure nodes: K/K0 = 1/(1 - phi), capped at K_MAX        (0 when fully covered: no interior field)
The time step shrinks by sqrt(max local K*B) when sub-cell posts raise the local sound speed.

Linearity trick (global constraints): one run per design with a broadband band-limited pulse, one cached run of
the empty scene on the same grid, H = (P_scene - P_empty) / P_empty in band, every clap by multiplication.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import numba as nb
import numpy as np
from numba import njit, prange

from echo.scene import C0, FS, Scene, alpha_db_per_m

RHO0 = 1.2  # kg/m^3; only ratios matter for the echo
K_MAX = 3.0  # cap on the sub-cell bulk-modulus contrast
FIELD_DTYPE = np.float32  # field precision
PHI_SOLID = 0.9  # nodes/faces covered at least this much are solid (no weakly coupled trapped pockets)
PPW_DEFAULT = 10.0  # grid points per wavelength at f_max (spec minimum for finite differences)
CFL_DEFAULT = 0.45  # c dt / dx (2D 8th-order staggered stability limit is 0.55)
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "tier1"
SENSOR_HALF = 8  # windowed-sinc sensor interpolation half width (16 x 16 taps)
SNAP_M = 0.25  # bounding box snapped outward to this quantum so the empty-scene cache hits across designs
H = 4  # halo width of the padded field arrays
FD8 = (1225 / 1024, -245 / 3072, 49 / 5120, -5 / 7168)  # 8th-order staggered first-derivative coefficients
ENGINE_VERSION = "fd8-3"  # fd8-3: per-point stencil order (widest stencil reading no solid point)
# Effective-area calibration of sub-cell posts, {r/dx: area factor}, linearly interpolated, 1 outside the
# table's range above it. Values are measured and validated in stages/validate.py (check 1); see DECISIONS.md.
AREA_CAL: dict = {0.01 / 0.0085714285714: 0.908, 0.02 / 0.0085714285714: 1.0}  # r/dx -> area factor (fd8-3, ppw 10)


# ----------------------------------------------------------------------------------------------------------------
# Results


@dataclass
class Tier1Result:
    fs: int
    ir: np.ndarray  # [n_listeners, n]: scattered impulse response, clap-normalized, band-limited, t=0 = emission
    listeners: np.ndarray  # [n_listeners, 2]
    dx: float
    dt: float
    grid: tuple  # (nx, ny) including PML
    f_lo: float
    f_max: float
    ppw: float
    wall_s: float
    solver: str = "fdtd"
    device: str = "cpu"
    c: float = C0
    field: dict | None = None  # {frames [T,H,W] float16 (row 0 = ymax), t0, dt_frame, extent [xmin,xmax,ymin,ymax]}
    extra: dict = dc_field(default_factory=dict)  # raw sensor traces, timings, grid geometry


# ----------------------------------------------------------------------------------------------------------------
# Grid and medium


@dataclass
class Grid:
    dx: float
    nx: int
    ny: int
    x0: float  # x of node 0 (inside the PML)
    y0: float
    npml: int

    @property
    def x(self):
        return self.x0 + self.dx * np.arange(self.nx)

    @property
    def y(self):
        return self.y0 + self.dx * np.arange(self.ny)

    def interior_extent(self):
        """[xmin, xmax, ymin, ymax] of the non-PML nodes, as cell edges (node +- dx/2)."""
        d, n = self.dx, self.npml
        return [self.x0 + (n - 0.5) * d, self.x0 + (self.nx - n - 0.5) * d,
                self.y0 + (n - 0.5) * d, self.y0 + (self.ny - n - 0.5) * d]


def make_grid(scene: Scene, listeners, dx, margin=0.5, wedge_margin=0.5, npml=24) -> Grid:
    """Tight bounding box of source, listeners (+ margin) and posts (+ wedge_margin), snapped outward to SNAP_M,
    surrounded by npml PML cells. The source sits exactly on a node."""
    pts = np.concatenate([np.asarray(scene.source, float)[None], np.asarray(listeners, float).reshape(-1, 2)])
    lo, hi = pts.min(axis=0) - margin, pts.max(axis=0) + margin
    if len(scene.posts):
        p = scene.posts
        lo = np.minimum(lo, (p[:, :2] - p[:, 2:3] - wedge_margin).min(axis=0))
        hi = np.maximum(hi, (p[:, :2] + p[:, 2:3] + wedge_margin).max(axis=0))
    lo = np.floor(lo / SNAP_M + 1e-9) * SNAP_M
    hi = np.ceil(hi / SNAP_M - 1e-9) * SNAP_M
    sx, sy = scene.source
    i_lo = int(np.floor((lo[0] - sx) / dx)) - npml
    j_lo = int(np.floor((lo[1] - sy) / dx)) - npml
    nx = int(np.ceil((hi[0] - sx) / dx)) + npml + 1 - i_lo
    ny = int(np.ceil((hi[1] - sy) / dx)) + npml + 1 - j_lo
    return Grid(dx=dx, nx=nx, ny=ny, x0=sx + i_lo * dx, y0=sy + j_lo * dx, npml=npml)


def area_scale(r, dx):
    """Calibrated area factor for a post of radius r at spacing dx (1 when uncalibrated)."""
    if not AREA_CAL:
        return 1.0
    q = np.array(sorted(AREA_CAL))
    return float(np.interp(r / dx, q, [AREA_CAL[k] for k in q], right=1.0))


def coverage(posts, xg, yg, dx, ss=10):
    """Covered area fraction phi[nx, ny] of the cells centred on (xg[i], yg[j]).

    Supersampled (ss x ss per cell), renormalized per post so sum(phi) dx^2 = pi r^2 * area_scale(r, dx).
    """
    phi = np.zeros((len(xg), len(yg)), dtype=np.float64)
    sub = (np.arange(ss) + 0.5) / ss - 0.5
    for x, y, r in np.asarray(posts, dtype=float).reshape(-1, 3):
        h = int(np.ceil(r / dx)) + 2
        i0 = int(np.round((x - xg[0]) / dx))
        j0 = int(np.round((y - yg[0]) / dx))
        ii = np.arange(max(i0 - h, 0), min(i0 + h + 1, len(xg)))
        jj = np.arange(max(j0 - h, 0), min(j0 + h + 1, len(yg)))
        if len(ii) == 0 or len(jj) == 0:
            continue
        X = xg[ii][:, None, None, None] + sub[None, None, :, None] * dx - x
        Y = yg[jj][None, :, None, None] + sub[None, None, None, :] * dx - y
        f = ((X * X + Y * Y) <= r * r).mean(axis=(2, 3))
        tot = f.sum() * dx * dx
        if tot > 0:
            f = f * (np.pi * r * r * area_scale(r, dx) / tot)
        phi[np.ix_(ii, jj)] += np.minimum(f, 1.0)
    return np.clip(phi, 0.0, 1.0)


def medium(posts, grid: Grid, kmax=K_MAX):
    """(K/K0 on p nodes, (1/rho)/(1/rho0) on ux faces, on uy faces), float32 [nx, ny] each."""
    xg, yg, d = grid.x, grid.y, grid.dx
    phi_p = coverage(posts, xg, yg, d)
    phi_x = coverage(posts, xg + d / 2, yg, d)
    phi_y = coverage(posts, xg, yg + d / 2, d)
    bx = (1 - phi_x) / (1 + phi_x)
    by = (1 - phi_y) / (1 + phi_y)
    ks = np.minimum(1.0 / np.maximum(1.0 - phi_p, 1e-9), kmax)
    solid = phi_p >= PHI_SOLID
    ks[solid] = 0.0
    bx[phi_x >= PHI_SOLID] = 0.0
    by[phi_y >= PHI_SOLID] = 0.0
    # Faces touching a solid node are closed, so the solid node is isolated. Otherwise its p = 0 would act as a
    # pressure-release sink.
    bx[solid | np.roll(solid, -1, 0)] = 0.0
    by[solid | np.roll(solid, -1, 1)] = 0.0
    return ks.astype(np.float32), bx.astype(np.float32), by.astype(np.float32)


def stable_cfl_factor(ks, bx, by):
    """sqrt(max K/K0 * B) over each p node and its 4 faces: the local sound-speed bound (>= 1)."""
    b = np.maximum.reduce([bx, np.roll(bx, 1, 0), by, np.roll(by, 1, 1)])
    return float(np.sqrt(max(1.0, float(np.max(ks * b)))))


def _pml_profile(n, npml, dx, dt, c, alpha, shift):
    """k-Wave style PML factor exp(-a dt/2), a = alpha (c/dx) (depth/npml)^4, at node positions i + shift."""
    i = np.arange(n) + shift
    depth = np.maximum(np.maximum(npml - i, i - (n - 1 - npml)), 0.0)
    a = alpha * (c / dx) * (depth / npml) ** 4
    return np.exp(-a * dt / 2.0).astype(np.float32)


def _sinc_weights(u, half=SENSOR_HALF):
    """Kaiser-windowed (beta 6) sinc taps for fractional node coordinate u: (first index, weights)."""
    if abs(u - round(u)) < 1e-9:  # on a node: exact
        return int(round(u)), np.ones(1)
    i0 = int(np.floor(u)) - half + 1
    d = u - (i0 + np.arange(2 * half))
    return i0, np.sinc(d) * np.i0(6.0 * np.sqrt(np.clip(1 - (d / half) ** 2, 0, 1))) / np.i0(6.0)


# ----------------------------------------------------------------------------------------------------------------
# Excitation and band


def source_pulse(fs_sim, n, f_lo, f_max, t0):
    """Band-limited pulse centred at t0: spectrum sin^2 rise 0 -> f_lo, flat to f_max, cos^2 fall to 1.25 f_max."""
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfftfreq(nfft, 1 / fs_sim)
    m = np.sin(0.5 * np.pi * np.clip(f / f_lo, 0, 1)) ** 2
    m *= np.cos(0.5 * np.pi * np.clip((f - f_max) / (0.25 * f_max), 0, 1)) ** 2
    s = np.fft.irfft(m * np.exp(-2j * np.pi * f * t0), nfft)[:n]
    return s / np.abs(s).max()


def band_mask(f, f_lo, f_hi, trans_hz=None):
    """The raised-cosine band mask of echo.clap.band_limit (and echo.tier0.band_mask), at frequencies f."""
    f = np.asarray(f, dtype=float)
    m = np.ones_like(f)
    if f_lo is not None and f_lo > 0:
        w = trans_hz if trans_hz is not None else max(50.0, 0.25 * f_lo)
        m *= 0.5 - 0.5 * np.cos(np.pi * np.clip((f - (f_lo - w / 2)) / w, 0.0, 1.0))
    if f_hi is not None:
        w = trans_hz if trans_hz is not None else max(50.0, 0.25 * f_hi)
        m *= 0.5 - 0.5 * np.cos(np.pi * np.clip(((f_hi + w / 2) - f) / w, 0.0, 1.0))
    return m


# ----------------------------------------------------------------------------------------------------------------
# Kernels: one leapfrog step = velocity update then pressure update (padded arrays, halo H, zero outside).


@njit(parallel=True, fastmath=True, cache=True)
def _step_u(P, UX, UY, Bx, By, pxs, pys, ox, oy, T, inv):
    nx = P.shape[0] - 2 * H
    ny = P.shape[1] - 2 * H
    for i in prange(nx):
        ip = i + H
        for j in range(ny):
            jp = j + H
            o = ox[i, j]
            d = (T[o, 0] * (P[ip + 1, jp] - P[ip, jp]) + T[o, 1] * (P[ip + 2, jp] - P[ip - 1, jp])
                 + T[o, 2] * (P[ip + 3, jp] - P[ip - 2, jp]) + T[o, 3] * (P[ip + 4, jp] - P[ip - 3, jp]))
            UX[ip, jp] = pxs[i] * (pxs[i] * UX[ip, jp] - Bx[i, j] * d * inv)
            o = oy[i, j]
            d = (T[o, 0] * (P[ip, jp + 1] - P[ip, jp]) + T[o, 1] * (P[ip, jp + 2] - P[ip, jp - 1])
                 + T[o, 2] * (P[ip, jp + 3] - P[ip, jp - 2]) + T[o, 3] * (P[ip, jp + 4] - P[ip, jp - 3]))
            UY[ip, jp] = pys[j] * (pys[j] * UY[ip, jp] - By[i, j] * d * inv)


@njit(parallel=True, fastmath=True, cache=True)
def _step_p(P, UX, UY, PX, PY, K, px_, py_, ox, oy, T, inv):
    nx = P.shape[0] - 2 * H
    ny = P.shape[1] - 2 * H
    for i in prange(nx):
        ip = i + H
        for j in range(ny):
            jp = j + H
            o = ox[i, j]
            gx = (T[o, 0] * (UX[ip, jp] - UX[ip - 1, jp]) + T[o, 1] * (UX[ip + 1, jp] - UX[ip - 2, jp])
                  + T[o, 2] * (UX[ip + 2, jp] - UX[ip - 3, jp]) + T[o, 3] * (UX[ip + 3, jp] - UX[ip - 4, jp])) * inv
            o = oy[i, j]
            gy = (T[o, 0] * (UY[ip, jp] - UY[ip, jp - 1]) + T[o, 1] * (UY[ip, jp + 1] - UY[ip, jp - 2])
                  + T[o, 2] * (UY[ip, jp + 2] - UY[ip, jp - 3]) + T[o, 3] * (UY[ip, jp + 3] - UY[ip, jp - 4])) * inv
            vx = px_[i] * (px_[i] * PX[i, j] - K[i, j] * gx)
            vy = py_[j] * (py_[j] * PY[i, j] - K[i, j] * gy)
            PX[i, j] = vx
            PY[i, j] = vy
            P[ip, jp] = vx + vy


# staggered first-derivative coefficients by order index o (stencil half-width o+1): 2nd, 4th, 6th, 8th
STENCILS = np.array([[1.0, 0, 0, 0], [9 / 8, -1 / 24, 0, 0], [75 / 64, -25 / 384, 3 / 640, 0], list(FD8)])


def stencil_orders(solid, closed_x, closed_y):
    """Per-point order index (0..3 = 2nd..8th) of the four derivatives: the widest staggered stencil that reads
    no solid node (velocity updates) or closed face (divergence). Returns (oux, ouy, opx, opy) int64 [nx, ny]."""
    def order(bad, axis, faces_from_nodes):
        n = bad.shape[axis]
        o = np.full(bad.shape, 3, dtype=np.int64)
        hit = np.zeros(bad.shape, dtype=bool)
        for m in range(1, 5):
            # stencil half-width m: velocity face i reads nodes i-m+1 .. i+m; node i reads faces i-m .. i+m-1
            lo_off, hi_off = (-(m - 1), m) if faces_from_nodes else (-m, m - 1)
            for off in (lo_off, hi_off):
                sh = np.zeros_like(bad)
                src = [slice(None)] * 2
                dst = [slice(None)] * 2
                if off >= 0:
                    src[axis], dst[axis] = slice(off, n), slice(0, n - off)
                else:
                    src[axis], dst[axis] = slice(0, n + off), slice(-off, n)
                sh[tuple(dst)] = bad[tuple(src)]
                hit |= sh
            o = np.where(hit & (o > m - 2), max(m - 2, 0), o)
        return o
    return (order(solid, 0, True), order(solid, 1, True), order(closed_x, 0, False), order(closed_y, 1, False))


def simulate(grid: Grid, c, dt, n_steps, src_xy, src_signal, sensors_xy, posts=None, kmax=K_MAX, pml_alpha=2.0,
             record_every=0, field_stride=1, threads=None, progress=None):
    """Run the solver. Returns (sensor traces [n_sensors, n_steps] float64, frames list or None, timings).

    Sensor sample n is p after step n (source sample n is injected at step n).
    """
    t_setup = time.time()
    nb.set_num_threads(threads or nb.config.NUMBA_NUM_THREADS)
    nx, ny, d = grid.nx, grid.ny, grid.dx
    f32 = FIELD_DTYPE
    K0 = RHO0 * c * c
    posts = np.zeros((0, 3)) if posts is None else np.asarray(posts, float).reshape(-1, 3)
    if len(posts):
        ks, bx, by = medium(posts, grid, kmax)
        oux, ouy, opx, opy = stencil_orders(ks == 0, bx == 0, by == 0)
    else:
        ks = np.ones((nx, ny), f32)
        bx = by = ks
        oux = ouy = opx = opy = np.full((nx, ny), 3, dtype=np.int64)
    TAB = STENCILS.astype(f32)
    Kd = (ks * (dt * K0)).astype(f32)
    Bx = (bx * (dt / RHO0)).astype(f32)
    By = (by * (dt / RHO0)).astype(f32)
    npml = grid.npml
    pml_x = _pml_profile(nx, npml, d, dt, c, pml_alpha, 0.0)
    pml_xs = _pml_profile(nx, npml, d, dt, c, pml_alpha, 0.5)
    pml_y = _pml_profile(ny, npml, d, dt, c, pml_alpha, 0.0)
    pml_ys = _pml_profile(ny, npml, d, dt, c, pml_alpha, 0.5)
    inv = f32(1.0 / d)

    si = int(round((src_xy[0] - grid.x0) / d))
    sj = int(round((src_xy[1] - grid.y0) / d))
    assert abs(grid.x0 + si * d - src_xy[0]) < 1e-6 and abs(grid.y0 + sj * d - src_xy[1]) < 1e-6
    src = np.asarray(src_signal, dtype=f32) * f32(0.5)

    nyp = ny + 2 * H
    idx, wts = [], []
    for (sx, sy) in np.asarray(sensors_xy, dtype=float).reshape(-1, 2):
        i0, wx = _sinc_weights((sx - grid.x0) / d)
        j0, wy = _sinc_weights((sy - grid.y0) / d)
        ii, jj = np.meshgrid(i0 + H + np.arange(len(wx)), j0 + H + np.arange(len(wy)), indexing="ij")
        idx.append((ii * nyp + jj).ravel())
        wts.append(np.outer(wx, wy).ravel())
    n_s = len(idx)
    rec = np.zeros((n_s, n_steps), dtype=np.float64)

    P = np.zeros((nx + 2 * H, ny + 2 * H), f32)
    UX = np.zeros_like(P)
    UY = np.zeros_like(P)
    PX = np.zeros((nx, ny), f32)
    PY = np.zeros((nx, ny), f32)
    Pf = P.ravel()
    frames = None
    if record_every:
        a, b = nx - 2 * npml, ny - 2 * npml
        s_ = max(1, field_stride)
        frames = np.zeros((n_steps // record_every, b // s_, a // s_), dtype=np.float16)  # preallocated, bounded
    n_fr = 0
    lo = npml
    t_setup = time.time() - t_setup
    t0 = time.time()
    for n in range(n_steps):
        _step_u(P, UX, UY, Bx, By, pml_xs, pml_ys, oux, ouy, TAB, inv)
        _step_p(P, UX, UY, PX, PY, Kd, pml_x, pml_y, opx, opy, TAB, inv)
        if n < len(src) and src[n] != 0:
            PX[si, sj] += src[n]
            PY[si, sj] += src[n]
            P[si + H, sj + H] = PX[si, sj] + PY[si, sj]
        for k in range(n_s):
            rec[k, n] = Pf[idx[k]] @ wts[k]
        if record_every and (n + 1) % record_every == 0:
            fr = P[H + lo:H + nx - lo, H + lo:H + ny - lo]
            if field_stride > 1:
                s = field_stride
                a, b = fr.shape[0] // s * s, fr.shape[1] // s * s
                fr = fr[:a, :b].reshape(a // s, s, b // s, s).mean(axis=(1, 3))
            if n_fr < len(frames):
                frames[n_fr] = fr[:, ::-1].T  # row 0 = ymax
                n_fr += 1
        if progress and n % 2000 == 0:
            progress(n, n_steps, time.time() - t0)
    return rec, frames, {"setup_s": t_setup, "loop_s": time.time() - t0}


# ----------------------------------------------------------------------------------------------------------------
# Spectra


def sim_frequency(f, c, dt, dx):
    """Frequency at which the scheme carries the physical wavenumber k = 2 pi f / c (along a grid axis)."""
    k = 2 * np.pi * np.asarray(f, dtype=float) / c
    kfd = (2 / dx) * sum(cm * np.sin((2 * m + 1) * k * dx / 2) for m, cm in enumerate(FD8))
    return np.arcsin(np.clip(c * dt * kfd / 2, -1, 1)) * 2 / dt / (2 * np.pi)


def _dft_at(x, fs, freqs, chunk=128):
    """X(f) = sum_n x[n] exp(-i 2 pi f n / fs) at arbitrary frequencies; x [S, N] -> [S, F] complex128."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    n = np.arange(x.shape[1], dtype=np.float64)
    out = np.zeros((x.shape[0], len(freqs)), dtype=np.complex128)
    for i in range(0, len(freqs), chunk):
        ph = np.outer(np.asarray(freqs[i:i + chunk], dtype=np.float64) * (-2 * np.pi / fs), n)
        out[:, i:i + chunk] = x @ np.cos(ph).T + 1j * (x @ np.sin(ph).T)
    return out


def _impulse_response(rec_s, rec_e, fs_sim, m, f_lo, f_max, n_out, source, listeners, c, dt, dx, eps=1e-8):
    """ir = irfft( (Ps - Pe)/Pe * band * exp(-i w |S L_l|/c) ) at FS per listener; spectra are read at the
    dispersion-corrected frequencies."""
    n = rec_s.shape[1]
    nfft = 2 * int(math.ceil(n / m))
    f = np.fft.rfftfreq(nfft, 1 / FS)
    band = band_mask(f, f_lo, f_max)
    use = band > 0
    X = _dft_at(np.concatenate([rec_s, rec_e]), fs_sim, sim_frequency(f[use], c, dt, dx))
    Ps, Pe = X[:len(rec_s)], X[len(rec_s):]
    Pe2 = np.abs(Pe) ** 2
    Hu = (Ps - Pe) * np.conj(Pe) / (Pe2 + eps * Pe2.max(axis=1, keepdims=True))
    Hf = np.zeros((len(rec_s), len(f)), dtype=np.complex128)
    Hf[:, use] = Hu * band[use][None]
    d_sl = np.linalg.norm(np.asarray(listeners) - np.asarray(source)[None], axis=1)
    Hf *= np.exp(-2j * np.pi * f[None, :] * (d_sl[:, None] / c))
    return np.fft.irfft(Hf, nfft, axis=1)[:, :n_out]


# ----------------------------------------------------------------------------------------------------------------
# Public API


def plan(scene, f_max, t_end, listeners=None, c=C0, f_lo=300.0, ppw=None, margin=0.5, wedge_margin=0.5, npml=24,
         cfl=None, kmax=K_MAX):
    """Grid, time step and step count of a run (no solve). Returns a dict."""
    listeners = np.asarray(scene.listener if listeners is None else listeners, dtype=float).reshape(-1, 2)
    ppw = PPW_DEFAULT if ppw is None else float(ppw)
    cfl = CFL_DEFAULT if cfl is None else float(cfl)
    sl = float(np.linalg.norm(np.asarray(scene.listener) - np.asarray(scene.source)))
    dx_t = c / (f_max * ppw)
    dx = sl / math.ceil(sl / dx_t) if sl > 0 else dx_t  # the default listener sits exactly on a node
    grid = make_grid(scene, listeners, dx, margin=margin, wedge_margin=wedge_margin, npml=npml)
    if len(scene.posts) and np.any(scene.posts[:, 2] < 2 * dx):
        # local sound-speed bound of sub-cell posts: probe each small radius at 16 rasterization offsets
        probe = []
        off = np.linspace(0, dx, 4, endpoint=False)
        for r in np.unique(scene.posts[:, 2]):
            if r < 2 * dx:
                probe += [[1.0 + 8 * dx * k + ox, oy, r] for k, (ox, oy) in
                          enumerate([(a, b) for a in off for b in off])]
        probe = np.array(probe)
        pg = make_grid(Scene(source=[0, 0], listener=[0, 0], posts=probe), np.zeros((1, 2)), dx, npml=1)
        fac = stable_cfl_factor(*medium(probe, pg, kmax))
        # the real scene's own bound, in case some rasterization is worse than every probe offset
        fac = max(fac, stable_cfl_factor(*medium(scene.posts[scene.posts[:, 2] < 2 * dx], grid, kmax)))
        cfl = cfl / fac
    m = max(1, math.ceil(c / (cfl * dx * FS)))  # dt = 1/(m FS): exact resampling to FS
    dt = 1.0 / (m * FS)
    t_src0 = 3.0 / f_lo + 2.0 / f_max  # source pulse centre = emission time inside the simulation
    n_out = int(math.ceil(t_end * FS))
    n_steps = (int(math.ceil((t_src0 + t_end) * FS)) + int(0.004 * FS)) * m
    return {"ppw": ppw, "dx": dx, "m": m, "dt": dt, "grid": grid, "t_src0": t_src0, "n_out": n_out,
            "n_steps": n_steps, "listeners": listeners, "cfl": c * dt / dx}


def _source_hash() -> str:
    """Hash of this module's source: any solver change invalidates cached empty-scene runs."""
    return hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:12]


def _cache_key(d: dict) -> str:
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def run_tier1(scene: Scene, f_max, t_end, listeners=None, c=C0, f_lo=300.0, record_field=False, field_dt=None,
              ppw=None, wedge_margin=0.5, cache=True, margin=0.5, npml=24, cfl=None, kmax=K_MAX,
              field_max_bytes=600e6, field_max_px=1280, threads=None, verbose=False) -> Tier1Result:
    """Full-wave 2D run of `scene` (rigid posts) plus the cached empty-scene run on the same grid.

    ir[l] is the band-limited ([f_lo, f_max], echo.clap.band_limit edges) scattered impulse response at listener l
    in the global normalization: the echo of clap k is clap_k convolved with ir[l]. It is sampled at FS, with
    t = 0 = emission and length ceil(t_end * FS). Air absorption is not in ir (see `echoes`).
    """
    T0 = time.time()
    pl = plan(scene, f_max, t_end, listeners, c, f_lo, ppw, margin, wedge_margin, npml, cfl, kmax)
    listeners, dx, m, dt, grid, n_steps = pl["listeners"], pl["dx"], pl["m"], pl["dt"], pl["grid"], pl["n_steps"]
    t_src0 = pl["t_src0"]
    fs_sim = m * FS
    sig = source_pulse(fs_sim, n_steps, f_lo, f_max, t_src0)
    log = (lambda n, N, s: print(f"  tier1 step {n}/{N}  {s:.0f}s", flush=True)) if verbose else None

    record_every, stride = 0, 1
    if record_field:
        long_side = max(grid.nx, grid.ny) - 2 * npml
        stride = max(1, math.ceil(long_side / field_max_px))
        record_every = max(1, int(round((field_dt if field_dt is not None else 0.25e-3) / dt)))
        hh = (grid.ny - 2 * npml) // stride
        ww = (grid.nx - 2 * npml) // stride
        if (n_steps // record_every) * hh * ww * 2 > field_max_bytes:  # bounded memory on long runs
            record_every = math.ceil(n_steps * hh * ww * 2 / field_max_bytes)

    key = _cache_key({"v": ENGINE_VERSION, "src_hash": _source_hash(), "c": c, "dx": dx, "dt": dt, "npml": npml,
                      "grid": [grid.nx, grid.ny, round(grid.x0, 9), round(grid.y0, 9)],
                      "src": [float(v) for v in scene.source], "sens": listeners.round(9).tolist(),
                      "n": n_steps, "f": [f_lo, f_max], "t_src0": t_src0})
    cpath = CACHE_DIR / f"empty_{key}.npz"
    t_empty, cached = 0.0, False
    if cache and cpath.exists():
        rec_e, cached = np.load(cpath)["rec"], True
    else:
        te = time.time()
        rec_e, _, _ = simulate(grid, c, dt, n_steps, scene.source, sig, listeners, threads=threads, progress=log)
        t_empty = time.time() - te
        if cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CACHE_DIR / f"tmp_{key}_{os.getpid()}.npz"
            np.savez(tmp, rec=rec_e)
            tmp.replace(cpath)
    ts = time.time()
    rec_s, frames, tim = simulate(grid, c, dt, n_steps, scene.source, sig, listeners, posts=scene.posts, kmax=kmax,
                                  record_every=record_every, field_stride=stride, threads=threads, progress=log)
    t_scene = time.time() - ts
    r_lo = min(AREA_CAL) if AREA_CAL else 0.0  # smallest validated r/dx (area_scale clamps below it)
    unval = sorted({float(r) for r in np.unique(scene.posts[:, 2]) if r / dx < r_lo - 1e-9}) if len(scene.posts) else []
    ir = _impulse_response(rec_s, rec_e, fs_sim, m, f_lo, f_max, pl["n_out"], scene.source, listeners, c, dt, dx)

    fld = None
    if record_field and frames is not None and len(frames):
        ext = grid.interior_extent()
        hh, ww = frames[0].shape
        ext = [ext[0], ext[0] + ww * stride * dx, ext[3] - hh * stride * dx, ext[3]]
        # frame i is p after step (i+1)*record_every - 1, i.e. sim time (i+1)*record_every*dt
        fld = {"frames": frames, "t0": record_every * dt - t_src0, "dt_frame": record_every * dt,
               "extent": [float(v) for v in ext]}
    return Tier1Result(fs=FS, ir=ir, listeners=listeners, dx=dx, dt=dt, grid=(grid.nx, grid.ny), f_lo=f_lo,
                       f_max=f_max, ppw=pl["ppw"], wall_s=time.time() - T0, solver="fdtd", device="cpu", c=c,
                       field=fld,
                       extra={"source": np.asarray(scene.source, float), "rec_scene": rec_s, "rec_empty": rec_e, "fs_sim": fs_sim, "t_src0": t_src0,
                              "grid": grid, "t_scene_s": t_scene, "t_empty_s": t_empty, "empty_cached": cached,
                              "n_steps": n_steps, "cfl": pl["cfl"], "setup_s": tim["setup_s"],
                              "unvalidated_radii": unval, "engine": ENGINE_VERSION})


def absorb(ir, fs=FS, c=C0, d_direct=0.3, block_s=0.004):
    """Air absorption (ISO 9613-1, 20 C, 50 % RH) as a time-varying zero-phase filter on an impulse response.

    Extra path over the direct one = c t - d_direct (as Tier 0). Overlap-add of periodic-Hann blocks (50 % overlap,
    sum to 1); each block is filtered by 10^(-alpha(f) (c t_centre - d_direct) / 20).
    """
    ir = np.atleast_2d(np.asarray(ir, dtype=float))
    n = ir.shape[1]
    L = int(round(block_s * fs))
    hop = L // 2
    win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(L) / L)
    nfft = 1 << int(np.ceil(np.log2(4 * L)))
    half = nfft // 2
    f = np.fft.rfftfreq(nfft, 1 / fs)
    a = alpha_db_per_m(f)
    pad = np.zeros((ir.shape[0], n + 2 * L))
    pad[:, L:L + n] = ir
    out = np.zeros_like(pad)
    for s in range(0, n + L, hop):  # block covers pad[s : s + L], i.e. ir times (s - L) .. (s - 1)
        seg = pad[:, s:s + L]
        if not np.any(seg):
            continue
        tc = (s - L + L / 2) / fs
        g = 10 ** (-a * max(c * tc - d_direct, 0.0) / 20)
        y = np.fft.irfft(np.fft.rfft(seg * win, nfft, axis=1) * g, nfft, axis=1)
        hi = min(s + half, out.shape[1])  # y[k], k < half, is lag +k
        out[:, s:hi] += y[:, :hi - s]
        lo = max(s - half, 0)  # y[nfft - q] is lag -q
        if lo < s:
            out[:, lo:s] += y[:, nfft - (s - lo):]
    return out[:, L:L + n]


def echoes(result: Tier1Result, claps, listener=0, absorption=True) -> np.ndarray:
    """Echo of every clap variant at one listener: [K, n] at FS, t = 0 = emission, relative to the direct clap
    (clap_k convolved with the scattered impulse response; air absorption as a time-varying filter)."""
    ir = np.asarray(result.ir[listener], dtype=float)
    if absorption:
        d = float(np.linalg.norm(result.listeners[listener] - result.extra.get("source", np.zeros(2))))
        ir = absorb(ir, result.fs, result.c, d_direct=d)[0]
    claps = np.atleast_2d(np.asarray(claps, dtype=float))
    n = len(ir)
    nfft = 1 << int(np.ceil(np.log2(n + claps.shape[1])))
    E = np.fft.irfft(np.fft.rfft(claps, nfft, axis=1) * np.fft.rfft(ir, nfft)[None], nfft, axis=1)
    return E[:, :n]
