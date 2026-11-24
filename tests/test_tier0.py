import time

import numpy as np
import pytest
import scipy.special as sp
import torch
from scipy.signal import hilbert

from echo.clap import band_limit, clap_family
from echo.scene import C0, FS, Scene, alpha_db_per_m, ellipse_point
from echo.tier0 import (
    cylinder_response,
    hankel_q,
    post_echo,
    post_transfer,
    profile_echo,
)

D = 0.3  # |SL|


@pytest.fixture(scope="module")
def claps():
    return clap_family(5)


def one_post(rho, theta, a):
    p = ellipse_point(rho, theta)
    return np.array([[p[0], p[1], a]])


def xcorr_lag(echo, clap):
    """Lag (samples) of the peak of the analytic cross-correlation envelope, with parabolic refinement."""
    n = len(echo) + len(clap)
    xc = np.fft.irfft(np.fft.rfft(echo, n) * np.conj(np.fft.rfft(clap, n)), n)[: len(echo)]
    env = np.abs(hilbert(xc))
    i = int(np.argmax(env))
    y0, y1, y2 = env[i - 1], env[i], env[i + 1]
    return i + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)


def frac_delay(x, tau_s, n_out):
    n = 4 * n_out
    f = np.fft.rfftfreq(n, 1 / FS)
    return np.fft.irfft(np.fft.rfft(x, n) * np.exp(-2j * np.pi * f * tau_s), n)[:n_out]


# ------------------------------------------------------------------------------------------- building blocks


def test_hankel_q_matches_scipy():
    x = np.logspace(-3, 5, 3000)
    q = hankel_q(torch.tensor(x)).numpy()
    ref = sp.hankel1(0, x) * np.sqrt(np.pi * x / 2) * np.exp(-1j * (x - np.pi / 4))
    assert np.max(np.abs(q - ref) / np.abs(ref)) < 1e-6


def test_cylinder_rayleigh_limit():
    # Hand: A0 = -J1/H1 ~ -i pi x^2/4, A1 = -J1'/H1' ~ +i pi x^2/4, T(phi) = A0 + 2 A1 cos(phi)
    # => T(pi) = -i (3 pi / 4) (ka)^2 for a rigid cylinder.
    ka = 0.01
    T = cylinder_response(1.0, ka * C0 / (2 * np.pi), np.pi)
    assert T == pytest.approx(-1j * 0.75 * np.pi * ka**2, rel=1e-3)


@pytest.mark.parametrize("ka", [30.0, 60.0])
def test_cylinder_geometric_optics_limit(ka):
    # Hand: specular reflection from a convex cylinder, plane wave, 2D: |p_s| = sqrt(a / (2 r)).
    # With p_s = sqrt(2/(pi k r)) T: |T| = sqrt(pi ka) / 2. Phase: path shorter by 2a -> T ~ |T| e^{-2ika} e^{i pi/4}.
    T = cylinder_response(1.0, ka * C0 / (2 * np.pi), np.pi)
    assert abs(T) == pytest.approx(np.sqrt(np.pi * ka) / 2, rel=0.01)
    assert np.angle(T * np.exp(2j * ka) * np.exp(-1j * np.pi / 4)) == pytest.approx(0.0, abs=0.05)


# ------------------------------------------------------------------------------------------------- timing


@pytest.mark.parametrize("mode", ["2d", "3d"])
@pytest.mark.parametrize("rho,theta,a", [(3.5, 0.0, 0.01), (10.0, 0.3, 0.01), (25.0, -0.3, 0.02), (40.0, 0.1, 0.08)])
def test_single_post_delay(claps, mode, rho, theta, a):
    # Hand: the echo arrives at 2 rho / C0 (t = 0 is emission), e.g. rho = 10 m -> 58.31 ms = 932.9 samples.
    # Echo of a post with ka <~ 6 is a filtered clap; the cross-correlation envelope peak gives its delay.
    # The specular point is a in front of the centre, so allow one sample plus 2a/C0.
    e = post_echo(one_post(rho, theta, a), claps, Scene(), mode, n_out=int(2 * rho / C0 * FS) + 400).numpy()
    expect = 2 * rho / C0 * FS
    for k in range(len(claps)):
        lag = xcorr_lag(e[k], claps[k])
        assert expect - 1.0 - 2 * a / C0 * FS <= lag <= expect + 1.0, (k, lag, expect)


def test_farther_post_echoes_later_and_causal(claps):
    n_out = 3000
    e1 = post_echo(one_post(5.0, 0.0, 0.04), claps[:1], Scene(), "2d", n_out=n_out).numpy()[0]
    e2 = post_echo(one_post(15.0, 0.0, 0.04), claps[:1], Scene(), "2d", n_out=n_out).numpy()[0]
    assert xcorr_lag(e2, claps[0]) - xcorr_lag(e1, claps[0]) == pytest.approx(2 * 10.0 / C0 * FS, abs=1.0)
    # Nothing (above -60 dB re the echo peak) arrives more than 1 ms before 2 rho / C0.
    for e, rho in ((e1, 5.0), (e2, 15.0)):
        i0 = int(2 * rho / C0 * FS) - FS // 1000
        assert np.max(np.abs(e[:i0])) < 1e-3 * np.max(np.abs(e))


def test_speed_of_sound_parameter(claps):
    sc = Scene(c=331.0)
    rho = 10.0
    e = post_echo(one_post(rho, 0.0, 0.02), claps[:1], sc, "2d", n_out=1400).numpy()[0]
    assert xcorr_lag(e, claps[0]) == pytest.approx(2 * rho / 331.0 * FS, abs=1.0)


# -------------------------------------------------------------------------------------------------- level


def go_check(claps, mode, hand_gain):
    """Large post (a = 0.5 m, ka = 9-37 over 1-4 kHz) at rho = 20 m on axis, no absorption.

    Geometric optics: the echo is the clap scaled by a frequency-flat gain and delayed by (r1 + r2 - 2a) / C0.
    """
    a, rho = 0.5, 20.0
    posts = one_post(rho, 0.0, a)
    r1 = np.linalg.norm(posts[0, :2])
    r2 = np.linalg.norm(posts[0, :2] - np.array([0, D]))
    g = hand_gain(a, r1, r2)
    n_out = int(2 * rho / C0 * FS) + 300
    band = (1000.0, 6000.0)
    e = post_echo(posts, claps, Scene(), mode, n_out=n_out, band=band, absorption=False).numpy()
    ref = band_limit(np.stack([frac_delay(c, (r1 + r2 - 2 * a) / C0, n_out) for c in claps]), *band)
    lvl = 10 * np.log10(np.sum(e**2, -1) / np.sum(ref**2, -1))
    assert np.all(np.abs(lvl - 20 * np.log10(g)) < 0.5), (lvl, 20 * np.log10(g))
    corr = np.sum(e * ref, -1) / np.sqrt(np.sum(e**2, -1) * np.sum(ref**2, -1))
    assert np.all(corr > 0.98), corr  # same waveform: pure delay, no phase rotation, right sign


def mirror_q(a, r1):
    # Convex mirror, focal length a/2 in the horizontal plane: 1/q = 1/r1 + 2/a (virtual source behind the surface).
    return 1.0 / (1.0 / r1 + 2.0 / a)


def test_single_post_level_2d_geometric_optics(claps):
    # Hand, 2D: line source amplitude ~ 1/sqrt(r). Relative to the direct path the incident field at the post is
    # sqrt(d/r1); the reflected cylindrical wavefront starts with radius q and spreads as sqrt(q/(q + r2)).
    # rho = 20 m: r1 = 19.998, r2 = 20.000, q = 0.2469 -> gain = sqrt(0.3/20) * sqrt(0.2469/20.247) = 0.01352
    # (-37.4 dB).
    go_check(claps, "2d", lambda a, r1, r2: np.sqrt(D / r1) * np.sqrt(mirror_q(a, r1) / (mirror_q(a, r1) + r2)))


def test_single_post_level_3d_geometric_optics(claps):
    # Hand, 3D: point source, incident amplitude re direct = d/r1. Reflected wavefront radii at the post: r1 in the
    # vertical (flat mirror) and q in the horizontal plane; at the listener the ray tube factor is
    # sqrt(r1 q / ((r1 + r2)(q + r2))). rho = 20 m: 0.3/20 * sqrt(20*0.2469/(40*20.247)) = 1.17e-3 (-58.6 dB).
    go_check(
        claps,
        "3d",
        lambda a, r1, r2: D / r1 * np.sqrt(r1 * mirror_q(a, r1) / ((r1 + r2) * (mirror_q(a, r1) + r2))),
    )


@pytest.mark.parametrize("rho,tol_db", [(3.0, 0.5), (10.0, 0.1)])
@pytest.mark.parametrize("a", [0.01, 0.08])
def test_2d_transfer_matches_exact_cylinder_series(rho, tol_db, a):
    # Exact 2D single-cylinder solution for a line source (Graf addition theorem, no plane-wave approximation):
    # H_scat / H_direct = sum_n eps_n A_n H_n(k r1) H_n(k r2) cos(n gamma) / H0(k d), gamma = angle at the post
    # between S and L. Tier 0 uses plane-wave incidence; at >= 3 m it must agree within 0.5 dB, at 10 m 0.1 dB.
    posts = one_post(rho + 0.01, 0.3, a)
    n_fft = 4096
    H = post_transfer(posts, Scene(), "2d", n_fft=n_fft, absorption=False).numpy()
    P = posts[0, :2]
    r1, r2 = np.linalg.norm(P), np.linalg.norm(P - np.array([0, D]))
    gam = np.arccos(np.dot(-P, np.array([0, D]) - P) / (r1 * r2))
    n = np.arange(40)
    eps = np.where(n == 0, 1, 2)
    for f0 in (500.0, 1000.0, 2000.0, 4000.0):
        kk = int(round(f0 * n_fft / FS))
        k = 2 * np.pi * kk * FS / n_fft / C0
        A = -sp.jvp(n, k * a) / sp.h1vp(n, k * a)
        hs = np.sum(eps * A * sp.hankel1(n, k * r1) * sp.hankel1(n, k * r2) * np.cos(n * gam))
        h_exact = np.conj(hs / sp.hankel1(0, k * D)) * np.exp(-1j * k * D)
        assert abs(20 * np.log10(abs(H[kk]) / abs(h_exact))) < tol_db
        assert abs(np.angle(H[kk] / h_exact)) < 0.05


def test_absorption_per_path():
    # Hand: amplitude factor 10^(-alpha (r1 + r2 - d) / 20). At 4 kHz alpha(20 C, 50 %) ~ 0.033 dB/m (ISO 9613-1).
    posts = one_post(50.0, 0.0, 0.04)
    n_fft = 8192
    h1 = post_transfer(posts, Scene(), "3d", n_fft=n_fft, absorption=True).numpy()
    h0 = post_transfer(posts, Scene(), "3d", n_fft=n_fft, absorption=False).numpy()
    kk = int(4000 * n_fft / FS)
    path = 2 * 50.0 - D
    assert abs(h1[kk] / h0[kk]) == pytest.approx(10 ** (-alpha_db_per_m(4000.0) * path / 20), rel=1e-9)


def test_band_matches_band_limit(claps):
    posts = np.concatenate([one_post(r, t, 0.04) for r, t in ((4.0, 0.1), (6.0, -0.2))])
    e_full = post_echo(posts, claps, Scene(), "2d", n_out=900).numpy()
    e_band = post_echo(posts, claps, Scene(), "2d", n_out=900, band=(500.0, 3000.0)).numpy()
    ref = band_limit(e_full, 500.0, 3000.0)
    assert np.max(np.abs(e_band - ref)) < 1e-3 * np.max(np.abs(ref))


# ------------------------------------------------------------------------------------------------ profile


@pytest.mark.parametrize("mode", ["2d", "3d"])
def test_profile_matches_posts(claps, mode):
    r0, dr = 3.0, 0.01
    n_rho = 2500  # 3 m .. 28 m
    prof = np.zeros(n_rho)
    idx = np.array([5, 333, 1200, 1201, 2499])
    prof[idx] = [1.0, 2.5, 0.7, 1.3, 3.0]
    a = 0.02
    rho = r0 + idx * dr
    xy = ellipse_point(rho, 0.0)
    posts = np.c_[xy, np.full(len(idx), a)]
    n_out = 3400
    e_prof = profile_echo(torch.tensor(prof), claps, Scene(), mode, n_out=n_out, a_ref=a, r0=r0, dr=dr).numpy()
    # post_echo of the equivalent posts: weight each post's echo by its count (linear model).
    e_post = sum(
        w * post_echo(posts[i : i + 1], claps, Scene(), mode, n_out=n_out, n_fft=8192).numpy()
        for i, w in enumerate(prof[idx])
    )
    err = np.sqrt(np.sum((e_prof - e_post) ** 2) / np.sum(e_post**2))
    assert err < 1e-3, err


# ---------------------------------------------------------------------------------------------- gradients


def test_gradient_to_post_positions(claps):
    posts = torch.tensor(np.concatenate([one_post(4.0, 0.1, 0.02), one_post(7.0, -0.2, 0.08)]), requires_grad=True)
    target = torch.tensor(np.random.default_rng(0).standard_normal((len(claps), 1000)))

    def loss(p):
        return ((post_echo(p, claps, Scene(), "2d", n_out=1000) - 0.001 * target) ** 2).sum()

    loss(posts).backward()
    g = posts.grad.numpy()
    assert np.all(np.isfinite(g)) and np.all(np.abs(g[:, :2]) > 0)
    # Finite-difference check on x of post 1.
    h = 1e-6
    p_plus, p_minus = posts.detach().clone(), posts.detach().clone()
    p_plus[1, 0] += h
    p_minus[1, 0] -= h
    fd = (loss(p_plus) - loss(p_minus)).item() / (2 * h)
    assert g[1, 0] == pytest.approx(fd, rel=1e-4)


@pytest.mark.parametrize("mode", ["2d", "3d"])
def test_gradient_to_profile(claps, mode):
    prof = torch.full((500,), 0.5, dtype=torch.float64, requires_grad=True)
    e = profile_echo(prof, claps, Scene(), mode, n_out=1000)
    (e[:, 400:500] ** 2).sum().backward()
    g = prof.grad.numpy()
    assert np.all(np.isfinite(g)) and np.abs(g).max() > 0


# -------------------------------------------------------------------------------------------------- speed


def test_evaluation_time(claps):
    rng = np.random.default_rng(1)
    n = 3000
    rho = rng.uniform(3.1, 30.0, n)
    th = rng.uniform(-0.3, 0.3, n)
    posts = np.c_[ellipse_point(rho, th), rng.choice([0.01, 0.02, 0.04, 0.08], n)]
    band = (500.0, 4000.0)  # the design band, as used by the design search and the Tier 1 comparison
    post_echo(posts[:10], claps, Scene(), "2d", n_out=3200, band=band)  # warm the partial-wave cache
    t = time.perf_counter()
    post_echo(posts, claps, Scene(), "2d", n_out=3200, band=band)
    t_post = time.perf_counter() - t
    prof = torch.rand(2700, dtype=torch.float64, requires_grad=True)
    profile_echo(prof, claps, Scene(), "2d", n_out=3200, band=band)  # build the plan
    t = time.perf_counter()
    profile_echo(prof, claps, Scene(), "2d", n_out=3200, band=band).sum().backward()
    t_prof = time.perf_counter() - t
    assert t_post < 1.0, t_post
    assert t_prof < 0.5, t_prof
