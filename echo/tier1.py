"""Tier 1: full-wave 2D solver (the referee).

Engine: our own k-space pseudo-spectral time-domain (PSTD) solver in PyTorch (CPU, float32), the scheme of
k-Wave's `kspaceFirstOrder2D` (staggered grid, k-space corrected leapfrog, split-field PML), written here so we
control the rigid inclusions, the sub-cell rasterization, any number of sensors and field snapshots
(see DECISIONS.md, task 3, for why not the k-Wave binary).

Rigid posts are an inclusion of the same sound-speed class as air but (almost) incompressible and (almost)
immovable, with sub-cell area-fraction rasterization:
  compressibility  kappa = kappa0 * (1 - phi)                     (monopole: exact area, exact contrast)
  1 / density      1/rho = (1/rho0) * (1 - phi) / (1 + phi)       ("mg" mixing: per-cell dipole strength
                                                                    2*phi*A_cell, the rigid value for area phi)
phi in [0, PHI_MAX] is the cell's covered area fraction, computed on each staggered grid by supersampling and
renormalized per post so that sum(phi) * dx^2 = pi r^2 exactly. Full cells are rigid to 1 part in ~1e3.
The sound speed is c0 / sqrt(1 + phi) <= c0, so the k-space time step (c_ref = c0) stays stable.

Linearity trick (global constraints): one run per design with a broadband band-limited pulse, one cached run of
the empty scene on the same grid, H = (P_scene - P_empty) / P_empty in band, every clap by multiplication.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import numpy as np
import torch

from echo.scene import C0, FS, Scene, alpha_db_per_m

RHO0 = 1.2  # kg/m^3; only ratios matter for the echo
K_MAX = 3.0  # cap on the sub-cell bulk-modulus contrast (stability)
INTERIOR_K = None  # K/K0 in fully covered p cells (None: kmax)
B_MIN = 1e-3  # floor on (1/rho)/(1/rho0) in covered cells (an immovable, heavy inclusion)
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "tier1"
SENSOR_HALF = 8  # windowed-sinc sensor interpolation half width (16 x 16 taps)
SNAP_M = 0.25  # bounding box snapped outward to this quantum so the empty-scene cache hits across designs
ENGINE_VERSION = "pstd-1"


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
    solver: str = "pstd"
    device: str = "cpu"
    c: float = C0
    field: dict | None = None  # {frames [T,H,W] float16 (row 0 = ymax), t0, dt_frame, extent [xmin,xmax,ymin,ymax]}
    extra: dict = dc_field(default_factory=dict)  # raw sensor traces, timings, grid geometry


# ----------------------------------------------------------------------------------------------------------------
# Grid and medium


def _good_size(n: int) -> int:
    """Smallest m >= n whose prime factors are 2, 3, 5 (fast FFT)."""
    m = n
    while True:
        k = m
        for p in (2, 3, 5):
            while k % p == 0:
                k //= p
        if k == 1:
            return m
        m += 1


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
        """[xmin, xmax, ymin, ymax] of the non-PML region (cell-centred node extent)."""
        d, n = self.dx, self.npml
        return [self.x0 + (n - 0.5) * d, self.x0 + (self.nx - n - 0.5) * d,
                self.y0 + (n - 0.5) * d, self.y0 + (self.ny - n - 0.5) * d]


def make_grid(scene: Scene, listeners, dx, margin=0.5, wedge_margin=0.5, npml=24) -> Grid:
    """Tight bounding box of source, listeners and posts (plus margins), snapped outward to SNAP_M, plus PML.

    The source sits exactly on a node.
    """
    pts = [np.asarray(scene.source)[None], np.asarray(listeners).reshape(-1, 2)]
    lo = np.min(np.concatenate(pts), axis=0) - margin
    hi = np.max(np.concatenate(pts), axis=0) + margin
    if len(scene.posts):
        p = scene.posts
        lo = np.minimum(lo, (p[:, :2] - p[:, 2:3] - wedge_margin).min(axis=0))
        hi = np.maximum(hi, (p[:, :2] + p[:, 2:3] + wedge_margin).max(axis=0))
    lo = np.floor(lo / SNAP_M) * SNAP_M
    hi = np.ceil(hi / SNAP_M) * SNAP_M
    sx, sy = scene.source
    # node indices relative to the source node
    i_lo = int(np.floor((lo[0] - sx) / dx)) - npml
    j_lo = int(np.floor((lo[1] - sy) / dx)) - npml
    nx = _good_size(int(np.ceil((hi[0] - sx) / dx)) + npml + 1 - i_lo)
    ny = _good_size(int(np.ceil((hi[1] - sy) / dx)) + npml + 1 - j_lo)
    return Grid(dx=dx, nx=nx, ny=ny, x0=sx + i_lo * dx, y0=sy + j_lo * dx, npml=npml)


def coverage(posts, xg, yg, dx, ss=10):
    """Covered area fraction phi[nx, ny] of posts on the node set (xg[i], yg[j]) with cells of size dx.

    Supersampled (ss x ss per cell) and renormalized per post so that sum(phi) dx^2 = pi r^2 exactly.
    """
    phi = np.zeros((len(xg), len(yg)), dtype=np.float64)
    if len(posts) == 0:
        return phi
    sub = (np.arange(ss) + 0.5) / ss - 0.5  # sub-sample offsets in cells
    for x, y, r in np.asarray(posts, dtype=float):
        h = int(np.ceil(r / dx)) + 1
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
            f *= np.pi * r * r / tot
        phi[np.ix_(ii, jj)] += f
    return np.clip(phi, 0.0, 1.0)


def _medium(posts, grid: Grid, mixing="mg", kmax=K_MAX, bmin=0.0):
    """Return (bulk-modulus scale K/K0 on the p grid, (1/rho)/(1/rho0) on the ux grid and on the uy grid).

    Velocity: B = (1-phi)/(1+phi) ("mg") or 1-phi ("linear"); exactly 0 in fully covered cells (immovable).
    Bulk modulus: K/K0 = 1/(1-phi), clipped at kmax (sub-cell monopole; kmax=1 disables it). Clipping keeps the
    product K*B, which sets the pseudo-spectral stability limit, within a small factor of the air value.
    """
    xg, yg, d = grid.x, grid.y, grid.dx
    phi_p = coverage(posts, xg, yg, d)
    phi_x = coverage(posts, xg + d / 2, yg, d)
    phi_y = coverage(posts, xg, yg + d / 2, d)
    if mixing == "mg":
        rx, ry = (1 - phi_x) / (1 + phi_x), (1 - phi_y) / (1 + phi_y)
    elif mixing == "linear":
        rx, ry = 1 - phi_x, 1 - phi_y
    else:
        raise ValueError(mixing)
    rx, ry = np.maximum(rx, bmin), np.maximum(ry, bmin)
    ks = np.minimum(1.0 / np.maximum(1.0 - phi_p, 1e-6), kmax)
    if INTERIOR_K is not None:
        ks[phi_p >= 0.999] = INTERIOR_K
    return ks.astype(np.float32), rx.astype(np.float32), ry.astype(np.float32)


def _pml_profile(n, npml, dx, dt, c, alpha, shift):
    """k-Wave style PML: exp(-a(x) dt/2), a = alpha * (c/dx) * (dist/npml)^4, at node positions i + shift."""
    i = np.arange(n) + shift
    dist = np.maximum(np.maximum(npml - i, i - (n - 1 - npml)), 0.0)
    a = alpha * (c / dx) * (dist / npml) ** 4
    return np.exp(-a * dt / 2.0).astype(np.float32)


def _sinc_weights(u, half=SENSOR_HALF):
    """Kaiser-windowed sinc taps for fractional node coordinate u: (first index, weights[2*half])."""
    i0 = int(np.floor(u)) - half + 1
    j = i0 + np.arange(2 * half)
    d = u - j
    w = np.sinc(d) * np.i0(6.0 * np.sqrt(np.clip(1 - (d / half) ** 2, 0, 1))) / np.i0(6.0)  # Kaiser, beta 6
    if abs(u - round(u)) < 1e-9:  # on a node: exact delta
        w = (j == int(round(u))).astype(float)
    return i0, w


# ----------------------------------------------------------------------------------------------------------------
# Excitation


def source_pulse(fs_sim, n, f_lo, f_max, t0):
    """Band-limited pulse (zero-phase spectrum shape, delayed by t0): sin^2 rise 0 -> f_lo, flat to f_max,
    cos^2 fall to 1.25 f_max. Peak normalized to 1."""
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfftfreq(nfft, 1 / fs_sim)
    m = np.ones_like(f)
    lo = np.clip(f / f_lo, 0, 1)
    m *= np.sin(0.5 * np.pi * lo) ** 2
    hi = np.clip((f - f_max) / (0.25 * f_max), 0, 1)
    m *= np.cos(0.5 * np.pi * hi) ** 2
    s = np.fft.irfft(m * np.exp(-2j * np.pi * f * t0), nfft)[:n]
    return s / np.abs(s).max()


def band_mask(f, f_lo, f_hi, trans_hz=None):
    """The raised-cosine band mask of echo.clap.band_limit evaluated at frequencies f."""
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
# Core time stepping


FD8 = (1225 / 1024, -245 / 3072, 49 / 5120, -5 / 7168)  # 8th-order staggered first-derivative coefficients
HALO = 4


def simulate(grid: Grid, c, dt, n_steps, src_xy, src_signal, sensors_xy, posts=None, mixing="mg", kmax=K_MAX,
             pml_alpha=2.0, record_every=0, field_stride=1, threads=None, progress=None, scheme="fd8"):
    """Run the solver ("fd8": 8th-order staggered FDTD; "pstd": k-space pseudo-spectral). Returns (sensor traces [n_sensors, n_steps] float64, frames list or None, timings).

    Sensor sample n is p at time (n+1)*dt, after source sample n has been injected at step n.
    """
    if threads:
        torch.set_num_threads(threads)
    nx, ny, d = grid.nx, grid.ny, grid.dx
    t_setup = time.time()
    K0 = RHO0 * c * c
    kscale, rx, ry = _medium(posts if posts is not None else np.zeros((0, 3)), grid, mixing, kmax,
                             bmin=B_MIN if scheme == "pstd" else 0.0)
    heterog = posts is not None and len(posts) > 0
    if scheme == "fd8":
        return _simulate_fd8(grid, c, dt, n_steps, src_xy, src_signal, sensors_xy, kscale, rx, ry, heterog, pml_alpha,
                             record_every, field_stride, progress, t_setup, posts_xyr=posts)

    kx = 2 * np.pi * np.fft.fftfreq(nx, d)
    ky = 2 * np.pi * np.fft.rfftfreq(ny, d)
    KX, KY = np.meshgrid(kx, ky, indexing="ij")
    kmag = np.sqrt(KX**2 + KY**2)
    kappa = np.sinc(c * kmag * dt / (2 * np.pi))  # sinc(x)=sin(pi x)/(pi x) -> sin(c k dt/2)/(c k dt/2)
    cdt = lambda a: torch.from_numpy(a.astype(np.complex64))
    Dxp = cdt(1j * KX * np.exp(1j * KX * d / 2) * kappa)
    Dxm = cdt(1j * KX * np.exp(-1j * KX * d / 2) * kappa)
    Dyp = cdt(1j * KY * np.exp(1j * KY * d / 2) * kappa)
    Dym = cdt(1j * KY * np.exp(-1j * KY * d / 2) * kappa)
    del KX, KY, kmag, kappa

    npml = grid.npml
    t = lambda a: torch.from_numpy(np.ascontiguousarray(a))
    pml_x = t(_pml_profile(nx, npml, d, dt, c, pml_alpha, 0.0)[:, None])
    pml_xs = t(_pml_profile(nx, npml, d, dt, c, pml_alpha, 0.5)[:, None])
    pml_y = t(_pml_profile(ny, npml, d, dt, c, pml_alpha, 0.0)[None, :])
    pml_ys = t(_pml_profile(ny, npml, d, dt, c, pml_alpha, 0.5)[None, :])

    cx = torch.tensor(dt / RHO0, dtype=torch.float32)
    if heterog:
        Bx = t(rx) * (dt / RHO0)
        By = t(ry) * (dt / RHO0)
        Kp = t(kscale) * (dt * K0)
    else:
        Bx = By = cx
        Kp = torch.tensor(dt * K0, dtype=torch.float32)

    # source node
    si = int(round((src_xy[0] - grid.x0) / d))
    sj = int(round((src_xy[1] - grid.y0) / d))
    assert abs(grid.x0 + si * d - src_xy[0]) < 1e-6 * d + 1e-9 and abs(grid.y0 + sj * d - src_xy[1]) < 1e-6 * d + 1e-9
    src = torch.from_numpy(np.asarray(src_signal, dtype=np.float32) * 0.5)

    # sensors: separable windowed sinc over a 16 x 16 patch
    IX, IY, W = [], [], []
    for (sx, sy) in np.asarray(sensors_xy, dtype=float).reshape(-1, 2):
        i0, wx = _sinc_weights((sx - grid.x0) / d)
        j0, wy = _sinc_weights((sy - grid.y0) / d)
        ii, jj = np.meshgrid(i0 + np.arange(len(wx)), j0 + np.arange(len(wy)), indexing="ij")
        IX.append(ii), IY.append(jj), W.append(np.outer(wx, wy))
    IX = torch.from_numpy(np.stack(IX).reshape(-1))
    IY = torch.from_numpy(np.stack(IY).reshape(-1))
    flat_idx = IX * ny + IY
    Wt = torch.from_numpy(np.stack(W).astype(np.float32))
    n_s = Wt.shape[0]
    rec = torch.zeros((n_steps, n_s), dtype=torch.float32)

    frames = [] if record_every else None
    lo, hix, hiy = npml, nx - npml, ny - npml

    shape = (nx, ny)
    p = torch.zeros(shape)
    px = torch.zeros(shape)
    py = torch.zeros(shape)
    ux = torch.zeros(shape)
    uy = torch.zeros(shape)
    rfft2, irfft2 = torch.fft.rfft2, torch.fft.irfft2
    t_setup = time.time() - t_setup
    t0 = time.time()
    with torch.inference_mode():
        for n in range(n_steps):
            P = rfft2(p)
            ux.mul_(pml_xs).sub_(Bx * irfft2(P * Dxp, s=shape)).mul_(pml_xs)
            uy.mul_(pml_ys).sub_(By * irfft2(P * Dyp, s=shape)).mul_(pml_ys)
            px.mul_(pml_x).sub_(Kp * irfft2(rfft2(ux) * Dxm, s=shape)).mul_(pml_x)
            py.mul_(pml_y).sub_(Kp * irfft2(rfft2(uy) * Dym, s=shape)).mul_(pml_y)
            if n < len(src):
                px[si, sj] += src[n]
                py[si, sj] += src[n]
            torch.add(px, py, out=p)
            rec[n] = (p.view(-1)[flat_idx].view(n_s, -1) * Wt.view(n_s, -1)).sum(1)
            if record_every and (n + 1) % record_every == 0:
                fr = p[lo:hix, lo:hiy]
                if field_stride > 1:
                    fr = torch.nn.functional.avg_pool2d(fr[None, None], field_stride, ceil_mode=True)[0, 0]
                frames.append(fr.flip(1).T.contiguous().to(torch.float16).numpy())  # row 0 = ymax
            if progress and n % 500 == 0:
                progress(n, n_steps, time.time() - t0)
    return rec.numpy().T.astype(np.float64), frames, {"setup_s": t_setup, "loop_s": time.time() - t0}


# ----------------------------------------------------------------------------------------------------------------
# Public API


def _plan(scene, f_max, t_end, listeners, c, f_lo, ppw, margin, wedge_margin, npml, cfl, scheme="fd8", kmax=K_MAX,
          mixing="mg"):
    ppw = (5.0 if scheme == "fd8" else 4.0) if ppw is None else float(ppw)
    cfl = (0.45 if scheme == "fd8" else 0.35) if cfl is None else float(cfl)
    sl = float(np.linalg.norm(np.asarray(scene.listener) - np.asarray(scene.source)))
    dx_t = c / (f_max * ppw)
    dx = sl / math.ceil(sl / dx_t) if sl > 0 else dx_t  # the default listener sits exactly on a node
    grid = make_grid(scene, listeners, dx, margin=margin, wedge_margin=wedge_margin, npml=npml)
    if scheme == "fd8" and len(scene.posts) and np.any(scene.posts[:, 2] < 1.5 * dx):
        cfl = cfl / stable_cfl_factor(*_medium(_local_posts(scene.posts), grid, mixing, kmax))
    m = max(1, math.ceil(c / (cfl * dx * FS)))  # dt = 1/(m FS): exact resampling to FS
    dt = 1.0 / (m * FS)
    t_src0 = 3.0 / f_lo + 2.0 / f_max  # source pulse centre (emission time inside the simulation)
    n_out = int(math.ceil(t_end * FS))
    n_steps_fs = int(math.ceil((t_src0 + t_end) * FS)) + int(0.004 * FS)
    n_steps = n_steps_fs * m
    return ppw, dx, m, dt, grid, t_src0, n_out, n_steps


def _local_posts(posts):
    """One post of each distinct radius (the CFL factor of sub-cell posts depends only on radius and offset);
    several offsets per radius so the worst rasterization is seen."""
    out = []
    for r in np.unique(posts[:, 2]):
        sel = posts[posts[:, 2] == r][:8]
        out.append(sel)
    return np.concatenate(out)


def _cache_key(d: dict) -> str:
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def run_tier1(scene: Scene, f_max, t_end, listeners=None, c=C0, f_lo=300.0, record_field=False, field_dt=None,
              ppw=None, wedge_margin=0.5, cache=True, margin=0.5, npml=24, cfl=None, mixing="mg", kmax=K_MAX,
              scheme="fd8",
              field_max_bytes=600e6, field_max_px=1280, verbose=False) -> Tier1Result:
    """Full-wave 2D run of `scene` (posts rigid) plus the cached empty-scene run on the same grid.

    ir[l] = band-limited scattered impulse response at listener l in the global normalization
    (echo of clap k = clap_k convolved with ir), at FS, t = 0 = emission, length ceil(t_end * FS).
    """
    T0 = time.time()
    listeners = np.asarray(scene.listener if listeners is None else listeners, dtype=float).reshape(-1, 2)
    ppw, dx, m, dt, grid, t_src0, n_out, n_steps = _plan(scene, f_max, t_end, listeners, c, f_lo, ppw, margin,
                                                         wedge_margin, npml, cfl, scheme, kmax, mixing)
    fs_sim = m * FS
    sig = source_pulse(fs_sim, n_steps, f_lo, f_max, t_src0)
    # The direct-path reference sensor (scene listener) is always sensor 0 internally.
    log = (lambda n, N, s: print(f"  step {n}/{N}  {s:.0f}s", flush=True)) if verbose else None

    record_every, stride = 0, 1
    if record_field:
        ext = grid.interior_extent()
        long_side = max(grid.nx, grid.ny) - 2 * npml
        stride = max(1, math.ceil(long_side / field_max_px))
        fdt = field_dt if field_dt is not None else 0.25e-3
        record_every = max(1, int(round(fdt / dt)))
        h = math.ceil((grid.ny - 2 * npml) / stride)
        w = math.ceil((grid.nx - 2 * npml) / stride)
        n_frames = n_steps // record_every
        if n_frames * h * w * 2 > field_max_bytes:  # keep memory bounded on long runs
            record_every = math.ceil(n_steps * h * w * 2 / field_max_bytes)

    # empty scene (cached)
    key = _cache_key({"v": ENGINE_VERSION, "scheme": scheme, "c": c, "dx": dx, "dt": dt, "grid": [grid.nx, grid.ny, grid.x0, grid.y0,
                      grid.npml], "src": list(map(float, scene.source)), "sens": listeners.round(9).tolist(),
                      "n": n_steps, "f": [f_lo, f_max], "t_src0": t_src0})
    cpath = CACHE_DIR / f"empty_{key}.npz"
    t_empty = 0.0
    if cache and cpath.exists():
        rec_e = np.load(cpath)["rec"]
    else:
        te = time.time()
        rec_e, _, _ = simulate(grid, c, dt, n_steps, scene.source, sig, listeners, posts=None, progress=log,
                               scheme=scheme)
        t_empty = time.time() - te
        if cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.savez(cpath, rec=rec_e)
    ts = time.time()
    rec_s, frames, tim = simulate(grid, c, dt, n_steps, scene.source, sig, listeners, posts=scene.posts,
                                  mixing=mixing, kmax=kmax, record_every=record_every, field_stride=stride, progress=log,
                                  scheme=scheme)
    t_scene = time.time() - ts

    ir = _impulse_response(rec_s, rec_e, fs_sim, m, t_src0, f_lo, f_max, n_out, scene, listeners, c, dt=dt, dx=dx,
                          scheme=scheme)

    fld = None
    if record_field and frames:
        ext = grid.interior_extent()
        if stride > 1:  # avg-pool cells grow; the extent grows to whole pooled cells
            h, w = frames[0].shape
            ext = [ext[0], ext[0] + w * stride * dx, ext[3] - h * stride * dx, ext[3]]
        fld = {"frames": np.stack(frames), "t0": record_every * dt - t_src0, "dt_frame": record_every * dt,
               "extent": [float(v) for v in ext]}
    return Tier1Result(fs=FS, ir=ir, listeners=listeners, dx=dx, dt=dt, grid=(grid.nx, grid.ny), f_lo=f_lo,
                       f_max=f_max, ppw=ppw, wall_s=time.time() - T0, solver="fdtd" if scheme == "fd8" else "pstd", device="cpu", c=c, field=fld,
                       extra={"rec_scene": rec_s, "rec_empty": rec_e, "fs_sim": fs_sim, "t_src0": t_src0,
                              "grid": grid, "t_scene_s": t_scene, "t_empty_s": t_empty, "n_steps": n_steps,
                              "setup_s": tim["setup_s"], "empty_cached": t_empty == 0.0})


def sim_frequency(f, c, dt, dx, scheme):
    """Frequency at which the discrete scheme carries the physical wavenumber k = 2 pi f / c (axis direction).

    fd8: 2 sin(w' dt / 2) / dt = c k_fd(k), with k_fd the 8th-order staggered modified wavenumber along an axis.
    pstd: the k-space corrected scheme is exact (w' = w).
    """
    f = np.asarray(f, dtype=float)
    if scheme == "pstd":
        return f
    k = 2 * np.pi * f / c
    kfd = (2 / dx) * sum(cm * np.sin((2 * m + 1) * k * dx / 2) for m, cm in enumerate(FD8))
    return np.arcsin(np.clip(c * dt * kfd / 2, -1, 1)) * 2 / dt / (2 * np.pi)


def _dft_at(x, fs, freqs, chunk=256):
    """X(f) = sum_n x[n] exp(-i 2 pi f n / fs) at arbitrary frequencies; x [S, N] -> [S, F] complex128."""
    x = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float64))
    n = torch.arange(x.shape[1], dtype=torch.float64)
    out = np.zeros((x.shape[0], len(freqs)), dtype=np.complex128)
    for i in range(0, len(freqs), chunk):
        fr = torch.from_numpy(np.asarray(freqs[i:i + chunk], dtype=np.float64))
        ph = -2 * np.pi * fr[:, None] * n[None, :] / fs
        out[:, i:i + chunk] = (torch.complex(x @ torch.cos(ph).T, x @ torch.sin(ph).T)).numpy()
    return out


def _impulse_response(rec_s, rec_e, fs_sim, m, t_src0, f_lo, f_max, n_out, scene, listeners, c, dt=None, dx=None,
                      scheme="fd8", eps=1e-8):
    """ir = irfft( (Ps - Pe)/Pe * band * exp(-i w |S L_l|/c) ) at FS, per listener.

    Ps, Pe are evaluated at the scheme's dispersion-corrected frequencies (see sim_frequency), so the timing of
    every path is that of the physical medium.
    """
    n = rec_s.shape[1]
    nfft = 2 * int(math.ceil(n / m))  # output FFT length at FS (zero-padded 2x)
    f = np.fft.rfftfreq(nfft, 1 / FS)
    band = band_mask(f, f_lo, f_max)
    use = band > 0
    fsim = sim_frequency(f[use], c, dt, dx, scheme)
    X = _dft_at(np.concatenate([rec_s, rec_e]), fs_sim, fsim)
    Ps, Pe = X[:len(rec_s)], X[len(rec_s):]
    Pe2 = np.abs(Pe) ** 2
    Hu = (Ps - Pe) * np.conj(Pe) / (Pe2 + eps * Pe2.max(axis=1, keepdims=True))
    H = np.zeros((len(rec_s), len(f)), dtype=np.complex128)
    H[:, use] = Hu * band[use][None]
    d_sl = np.linalg.norm(listeners - np.asarray(scene.source)[None], axis=1)
    H *= np.exp(-2j * np.pi * f[None, :] * (d_sl[:, None] / c))
    ir = np.fft.irfft(H, nfft, axis=1)
    return ir[:, :n_out]


def absorb(ir, fs=FS, c=C0, block_s=0.004):
    """Air absorption as a time-varying zero-phase filter on an impulse response (path length = c t).

    Overlap-add of Hann-windowed blocks (50 % overlap), each filtered by 10^(-alpha(f) c t_centre / 20).
    """
    ir = np.atleast_2d(np.asarray(ir, dtype=float))
    n = ir.shape[1]
    L = int(round(block_s * fs))
    hop = L // 2
    win = np.hanning(L + 1)[:L]  # periodic Hann: sums to 1 at 50 % overlap
    nfft = 1 << int(np.ceil(np.log2(2 * L)))
    f = np.fft.rfftfreq(nfft, 1 / fs)
    a = alpha_db_per_m(f)
    out = np.zeros((ir.shape[0], n + nfft))
    pad = np.zeros((ir.shape[0], n + L))
    pad[:, hop:hop + n] = ir  # leading half block so the first samples are covered by two windows
    for s in range(0, n + hop, hop):
        seg = pad[:, s:s + L]
        if seg.shape[1] < L or not np.any(seg):
            continue
        tc = (s - hop + L / 2) / fs
        g = 10 ** (-a * c * max(tc, 0.0) / 20)
        y = np.fft.irfft(np.fft.rfft(seg * win, nfft, axis=1) * g, nfft, axis=1)
        # zero-phase: shift by nfft/2 wraparound handled by placing the full nfft result centred
        y = np.roll(y, nfft // 2, axis=1)
        start = s - hop - nfft // 2
        lo = max(start, 0)
        out[:, lo:start + nfft] += y[:, lo - start:]
    return out[:, :n]


def echoes(result: Tier1Result, claps, listener=0, absorption=True) -> np.ndarray:
    """Echo of every clap variant at one listener, [K, n] at FS, t = 0 = emission, relative to the direct clap."""
    ir = result.ir[listener]
    if absorption:
        ir = absorb(ir, result.fs, result.c)[0]
    claps = np.atleast_2d(np.asarray(claps, dtype=float))
    n = len(ir)
    nfft = 1 << int(np.ceil(np.log2(n + claps.shape[1])))
    E = np.fft.irfft(np.fft.rfft(claps, nfft, axis=1) * np.fft.rfft(ir, nfft)[None], nfft, axis=1)
    return E[:, :n]


def _sensor_taps(grid: Grid, sensors_xy, halo=0):
    """Flat gather indices into a (nx+2h, ny+2h) array and windowed-sinc weights, per sensor."""
    d, ny = grid.dx, grid.ny + 2 * halo
    idx, W = [], []
    for (sx, sy) in np.asarray(sensors_xy, dtype=float).reshape(-1, 2):
        i0, wx = _sinc_weights((sx - grid.x0) / d)
        j0, wy = _sinc_weights((sy - grid.y0) / d)
        ii, jj = np.meshgrid(i0 + halo + np.arange(len(wx)), j0 + halo + np.arange(len(wy)), indexing="ij")
        idx.append(ii * ny + jj)
        W.append(np.outer(wx, wy))
    return torch.from_numpy(np.stack(idx).reshape(-1)), torch.from_numpy(np.stack(W).astype(np.float32))


def stable_cfl_factor(kscale, rx, ry):
    """sqrt(max K/K0 * (1/rho)/(1/rho0)) over each p node and its 4 neighbouring faces (local sound-speed bound)."""
    b = np.maximum.reduce([rx, np.roll(rx, 1, 0), ry, np.roll(ry, 1, 1)])
    return float(np.sqrt(max(1.0, np.max(kscale * b))))


LOCAL_ORDER2 = True  # 2nd-order stencil within BLEND_CELLS of a post (rigid staircase is exact for Yee cells)
BLEND_CELLS = 5


def _near_post_mask(grid: Grid, posts):
    """1 within r + BLEND_CELLS*dx of a post centre, cosine taper to 0 over the next 3 cells."""
    w = np.zeros((grid.nx, grid.ny))
    d = grid.dx
    xg, yg = grid.x, grid.y
    for x, y, r in posts:
        R0 = r + BLEND_CELLS * d
        R1 = R0 + 3 * d
        i = np.where(np.abs(xg - x) <= R1)[0]
        j = np.where(np.abs(yg - y) <= R1)[0]
        if len(i) == 0 or len(j) == 0:
            continue
        dist = np.hypot(xg[i][:, None] - x, yg[j][None, :] - y)
        v = 0.5 + 0.5 * np.cos(np.pi * np.clip((dist - R0) / (R1 - R0), 0, 1))
        w[np.ix_(i, j)] = np.maximum(w[np.ix_(i, j)], v)
    return w


def _simulate_fd8(grid, c, dt, n_steps, src_xy, src_signal, sensors_xy, kscale, rx, ry, heterog, pml_alpha,
                  record_every, field_stride, progress, t_setup0, posts_xyr=None):
    nx, ny, d, h = grid.nx, grid.ny, grid.dx, HALO
    t_setup = time.time()
    K0 = RHO0 * c * c
    T = lambda a: torch.from_numpy(np.ascontiguousarray(a, dtype=np.float32))
    npml = grid.npml
    pml_x = T(_pml_profile(nx, npml, d, dt, c, pml_alpha, 0.0)[:, None])
    pml_xs = T(_pml_profile(nx, npml, d, dt, c, pml_alpha, 0.5)[:, None])
    pml_y = T(_pml_profile(ny, npml, d, dt, c, pml_alpha, 0.0)[None, :])
    pml_ys = T(_pml_profile(ny, npml, d, dt, c, pml_alpha, 0.5)[None, :])
    cs = [cm / d for cm in FD8]
    if heterog:
        Bx, By, Kp = T(rx * (dt / RHO0)), T(ry * (dt / RHO0)), T(kscale * (dt * K0))
    else:
        Bx = By = dt / RHO0
        Kp = dt * K0
    si = int(round((src_xy[0] - grid.x0) / d))
    sj = int(round((src_xy[1] - grid.y0) / d))
    assert abs(grid.x0 + si * d - src_xy[0]) < 1e-6 and abs(grid.y0 + sj * d - src_xy[1]) < 1e-6
    src = torch.from_numpy(np.asarray(src_signal, dtype=np.float32) * 0.5)
    blend = T(_near_post_mask(grid, posts_xyr)) if heterog and LOCAL_ORDER2 else None
    flat_idx, Wt = _sensor_taps(grid, sensors_xy, halo=h)
    n_s = Wt.shape[0]
    Wf = Wt.view(n_s, -1)
    rec = torch.zeros((n_steps, n_s), dtype=torch.float32)
    frames = [] if record_every else None

    P = torch.zeros((nx + 2 * h, ny + 2 * h))  # pressure with a zero halo
    UX = torch.zeros((nx + 2 * h, ny))  # ux at (i+1/2, j), halo along x
    UY = torch.zeros((nx, ny + 2 * h))  # uy at (i, j+1/2), halo along y
    ux, uy = UX[h:h + nx], UY[:, h:h + ny]
    p = P[h:h + nx, h:h + ny]
    px = torch.zeros((nx, ny))
    py = torch.zeros((nx, ny))
    acc = torch.empty((nx, ny))
    tmp = torch.empty((nx, ny))
    Pflat = P.view(-1)
    lo, hix, hiy = npml, nx - npml, ny - npml

    def dxp(out):  # d/dx of p at (i+1/2, j)
        Pc = P[:, h:h + ny]
        torch.sub(Pc[h + 1:h + 1 + nx], Pc[h:h + nx], out=out).mul_(cs[0])
        for m in range(2, 5):
            torch.sub(Pc[h + m:h + m + nx], Pc[h + 1 - m:h + 1 - m + nx], out=tmp)
            out.add_(tmp, alpha=cs[m - 1])
        if blend is not None:
            torch.sub(Pc[h + 1:h + 1 + nx], Pc[h:h + nx], out=tmp)
            out.add_(tmp.mul_(1 / d).sub_(out).mul_(blend))
        return out

    def dyp(out):
        Pc = P[h:h + nx]
        torch.sub(Pc[:, h + 1:h + 1 + ny], Pc[:, h:h + ny], out=out).mul_(cs[0])
        for m in range(2, 5):
            torch.sub(Pc[:, h + m:h + m + ny], Pc[:, h + 1 - m:h + 1 - m + ny], out=tmp)
            out.add_(tmp, alpha=cs[m - 1])
        if blend is not None:
            torch.sub(Pc[:, h + 1:h + 1 + ny], Pc[:, h:h + ny], out=tmp)
            out.add_(tmp.mul_(1 / d).sub_(out).mul_(blend))
        return out

    def dxm(out):  # d/dx of ux at node (i, j)
        torch.sub(UX[h:h + nx], UX[h - 1:h - 1 + nx], out=out).mul_(cs[0])
        for m in range(2, 5):
            torch.sub(UX[h + m - 1:h + m - 1 + nx], UX[h - m:h - m + nx], out=tmp)
            out.add_(tmp, alpha=cs[m - 1])
        if blend is not None:
            torch.sub(UX[h:h + nx], UX[h - 1:h - 1 + nx], out=tmp)
            out.add_(tmp.mul_(1 / d).sub_(out).mul_(blend))
        return out

    def dym(out):
        torch.sub(UY[:, h:h + ny], UY[:, h - 1:h - 1 + ny], out=out).mul_(cs[0])
        for m in range(2, 5):
            torch.sub(UY[:, h + m - 1:h + m - 1 + ny], UY[:, h - m:h - m + ny], out=tmp)
            out.add_(tmp, alpha=cs[m - 1])
        if blend is not None:
            torch.sub(UY[:, h:h + ny], UY[:, h - 1:h - 1 + ny], out=tmp)
            out.add_(tmp.mul_(1 / d).sub_(out).mul_(blend))
        return out

    t_setup = t_setup0 + time.time() - t_setup
    t0 = time.time()
    with torch.inference_mode():
        for n in range(n_steps):
            ux.mul_(pml_xs).sub_(dxp(acc).mul_(Bx)).mul_(pml_xs)
            uy.mul_(pml_ys).sub_(dyp(acc).mul_(By)).mul_(pml_ys)
            px.mul_(pml_x).sub_(dxm(acc).mul_(Kp)).mul_(pml_x)
            py.mul_(pml_y).sub_(dym(acc).mul_(Kp)).mul_(pml_y)
            if n < len(src):
                px[si, sj] += src[n]
                py[si, sj] += src[n]
            torch.add(px, py, out=p)
            rec[n] = (Pflat[flat_idx].view(n_s, -1) * Wf).sum(1)
            if record_every and (n + 1) % record_every == 0:
                fr = p[lo:hix, lo:hiy]
                if field_stride > 1:
                    fr = torch.nn.functional.avg_pool2d(fr[None, None], field_stride, ceil_mode=True)[0, 0]
                frames.append(fr.flip(1).T.contiguous().to(torch.float16).numpy())  # row 0 = ymax
            if progress and n % 500 == 0:
                progress(n, n_steps, time.time() - t0)
    return rec.numpy().T.astype(np.float64), frames, {"setup_s": t_setup, "loop_s": time.time() - t0}
