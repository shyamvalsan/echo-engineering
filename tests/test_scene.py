import numpy as np
import pytest

from echo.scene import (
    C0,
    LISTENER,
    MIN_GAP,
    SOURCE,
    T_DIRECT,
    Scene,
    alpha_db_per_m,
    bistatic_range,
    check_gaps,
    echo_delay,
    ellipse_point,
    fill_fraction,
    from_json,
    in_wedge,
    to_json,
)


def test_direct_time():
    # |SL| = 0.3 m -> 0.3 / 343 = 0.8746 ms
    assert T_DIRECT == pytest.approx(0.3 / 343.0)


@pytest.mark.parametrize("rho", [3.0, 10.0, 68.6])
@pytest.mark.parametrize("theta_deg", [-20.0, -7.5, 0.0, 12.0, 20.0])
def test_ellipse_point_has_requested_delay(rho, theta_deg):
    th = np.radians(theta_deg)
    p = ellipse_point(rho, th)
    # Hand check: |P-S| + |P-L| must equal 2*rho, so delay = 2*rho/C0.
    path = np.linalg.norm(p - SOURCE) + np.linalg.norm(p - LISTENER)
    assert path == pytest.approx(2 * rho, abs=1e-9)
    assert echo_delay(p) == pytest.approx(2 * rho / C0, rel=1e-12)
    assert np.degrees(np.arctan2(p[1], p[0])) == pytest.approx(theta_deg, abs=1e-9)


def test_ellipse_on_axis_hand_value():
    # On +x: |P| = r, |P-L| = sqrt(r^2 + 0.09); r + sqrt(r^2+0.09) = 2*rho = 6
    # => r = (36 - 0.09)/12 = 2.9925 m.
    p = ellipse_point(3.0, 0.0)
    assert p[0] == pytest.approx(2.9925, abs=1e-12)
    assert p[1] == pytest.approx(0.0, abs=1e-12)


def test_ellipse_broadcast_and_bistatic_vs_polar():
    rho = np.full(5, 10.0)
    th = np.radians(np.linspace(-20, 20, 5))
    pts = ellipse_point(rho, th)
    assert pts.shape == (5, 2)
    np.testing.assert_allclose(bistatic_range(pts), 10.0, atol=1e-9)
    # Bistatic != polar radius: at +20 deg (towards L at +y) |P-L| is smaller, so |P| must be larger.
    r = np.linalg.norm(pts, axis=1)
    assert r[-1] > r[0]


def test_in_wedge():
    pts = np.array([[5.0, 0.0], [5.0 * np.cos(np.radians(21)), 5.0 * np.sin(np.radians(21))], [2.0, 0.0],
                    [4.0 * np.cos(np.radians(-19.9)), 4.0 * np.sin(np.radians(-19.9))]])
    np.testing.assert_array_equal(in_wedge(pts), [True, False, False, True])
    assert not in_wedge(np.array([50.0, 0.0]), r_max=40.0)


def test_in_wedge_rho_min():
    # On axis, rho = 3.0 lies at polar r = 2.9925 m (< r_min = 3.0): outside by default, inside with rho_min=3.0.
    th = np.radians(np.linspace(-20, 20, 41))
    pts = ellipse_point(3.0, th)
    assert np.all(in_wedge(pts, rho_min=3.0))
    assert not in_wedge(ellipse_point(3.0, 0.0))  # default (polar r_min) behaviour unchanged
    assert not np.any(in_wedge(ellipse_point(2.99, th), rho_min=3.0))
    assert not np.any(in_wedge(ellipse_point(5.0, np.radians([21.0, -21.0])), rho_min=3.0))


def test_check_gaps():
    # Centres 0.2 m apart, radii 0.04 and 0.08 -> gap 0.08; third post far away.
    posts = np.array([[5.0, 0.0, 0.04], [5.2, 0.0, 0.08], [9.0, 1.0, 0.01]])
    assert check_gaps(posts) == pytest.approx(0.08)
    assert check_gaps(posts[:1]) == np.inf
    # Overlap is negative.
    assert check_gaps(np.array([[0, 0, 0.08], [0.1, 0, 0.08]])) == pytest.approx(-0.06)


def test_check_gaps_matches_brute_force():
    rng = np.random.default_rng(1)
    from echo.scene import RADII

    posts = np.column_stack([rng.uniform(3, 8, 300), rng.uniform(-1, 1, 300), rng.choice(RADII, 300)])
    d = np.linalg.norm(posts[:, None, :2] - posts[None, :, :2], axis=-1) - posts[:, None, 2] - posts[None, :, 2]
    d[np.diag_indices(300)] = np.inf
    assert check_gaps(posts) == pytest.approx(d.min())
    assert MIN_GAP == 0.05


def test_alpha_iso9613_table_values():
    # ISO 9613-2:1996 Table 2 (values computed from ISO 9613-1), dB/km, rounded to 0.1:
    # 20 C / 70 % RH: 500 Hz 2.8, 1 kHz 5.0, 2 kHz 9.0, 4 kHz 22.9, 8 kHz 76.6
    # 10 C / 70 % RH: 1 kHz 3.7, 4 kHz 32.8
    a = alpha_db_per_m([500, 1000, 2000, 4000, 8000], T=20, rh=70) * 1000
    np.testing.assert_allclose(a, [2.8, 5.0, 9.0, 22.9, 76.6], rtol=0.03)
    a = alpha_db_per_m([1000, 4000], T=10, rh=70) * 1000
    np.testing.assert_allclose(a, [3.7, 32.8], rtol=0.03)


def test_alpha_default_conditions_monotone():
    f = np.linspace(100, 8000, 50)
    a = alpha_db_per_m(f)
    assert np.all(np.diff(a) > 0)
    # Sanity at the project conditions (20 C / 50 %): drier air absorbs more at 4 kHz than 70 % RH does.
    assert alpha_db_per_m(4000) > alpha_db_per_m(4000, rh=70)
    assert 0.02 < alpha_db_per_m(4000) < 0.04


def test_scene_json_roundtrip_and_fill():
    posts = np.array([[5.0, 0.0, 0.04], [6.0, 0.5, 0.02]])
    sc = Scene(posts=posts, r_max=10.0)
    s2 = from_json(to_json(sc))
    np.testing.assert_allclose(s2.posts, posts)
    np.testing.assert_allclose(s2.listener, LISTENER)
    assert s2.r_max == 10.0 and s2.half_angle_deg == 20.0 and s2.c == C0
    d = sc.to_dict()
    assert set(d) == {"units", "c", "source", "listener", "wedge", "posts"}
    assert set(d["wedge"]) == {"half_angle_deg", "r_min", "r_max"}
    # Hand: area = pi*(0.04^2 + 0.02^2) = 6.283e-3; wedge = (40 deg in rad)/2 * (100 - 9) = 31.765 m^2
    assert fill_fraction(sc) == pytest.approx(np.pi * 0.002 / (np.radians(20) * 91.0))
    empty = Scene()
    assert empty.to_dict()["wedge"]["r_max"] == 3.0 and fill_fraction(empty) == 0.0
