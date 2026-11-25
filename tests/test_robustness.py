"""Robustness sweep: case generation (sensors, jitter), the fragile rule."""

import numpy as np

from echo.robustness import (LISTENER_OFFSETS, POS_JITTER_M, RAD_JITTER_M, case, fragile_rule, jitter_posts,
                             listener_shift_s, robustness_listeners)
from echo.scene import Scene


def test_listeners_nominal_side_back():
    L = robustness_listeners(Scene())
    assert np.allclose(L, [[0, 0.3], [0, 1.3], [-1.0, 0.3]])
    assert list(LISTENER_OFFSETS) == ["listener_side_1m", "listener_back_1m"]


def test_jitter_deterministic_and_bounded():
    rng = np.random.default_rng(5)
    posts = np.column_stack([rng.uniform(3, 15, 5000), rng.uniform(-2, 2, 5000), np.full(5000, 0.01)])
    a, b = jitter_posts(posts, seed=0), jitter_posts(posts, seed=0)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, jitter_posts(posts, seed=1))
    d = a - posts
    assert np.abs(d[:, :2]).max() <= POS_JITTER_M + 1e-15 and np.abs(d[:, 2]).max() <= RAD_JITTER_M + 1e-15
    # uniform on [-h, h]: standard deviation h / sqrt(3) (5 mm -> 2.89 mm; 1 mm -> 0.577 mm), mean 0
    assert abs(d[:, 0].std() - POS_JITTER_M / np.sqrt(3)) < 1e-4 and abs(d[:, 1].std() - POS_JITTER_M / np.sqrt(3)) < 1e-4
    assert abs(d[:, 2].std() - RAD_JITTER_M / np.sqrt(3)) < 2e-5
    assert abs(d[:, :2].mean()) < 2e-4


def test_listener_shift_back_is_about_one_metre():
    # moving the listener 1 m straight back (away from the posts along -x) lengthens the post->listener leg by
    # ~1 m for a far on-axis point: 1 / 343 s = 2.92 ms (slightly less: the leg is not exactly along x).
    sh = listener_shift_s(Scene(), [-1.0, 0.3], 10.0)
    assert 2.85e-3 < sh < 2.92e-3


def _c(name, ok):
    return {"case": name, "pass": ok}


def test_fragile_rule():
    claps = lambda n: [_c(f"clap_{k}", k < n) for k in range(5)]  # noqa: E731
    pos = lambda a, b, c: [_c("nominal", a), _c("listener_side_1m", b), _c("listener_back_1m", c)]  # noqa: E731
    assert fragile_rule(pos(True, True, True) + claps(5))[0] is False
    assert fragile_rule(pos(True, True, True) + claps(1))[0] is True  # works for one clap only
    assert fragile_rule(pos(True, False, False) + claps(5))[0] is True  # works at one listener position only
    assert fragile_rule(pos(True, True, False) + claps(2))[0] is False
    assert fragile_rule(pos(False, False, False) + claps(0))[0] is False  # failing, not fragile
    assert "1/5 clap" in fragile_rule(pos(True, True, True) + claps(1))[1]


def test_case_delta_and_pass():
    nominal = {"pitch_err_pct": 2.0, "spec_corr": 0.9}
    pc = [{"pitch_err_pct": 2.5, "spec_corr": 0.85}, {"pitch_err_pct": 3.1, "spec_corr": 0.95}]
    c = case("s1_bird", "x", "X", pc, nominal)
    assert abs(c["metrics"]["pitch_err_pct"] - 2.8) < 1e-12 and abs(c["delta"]["pitch_err_pct"] - 0.8) < 1e-12
    assert c["pass"] is True  # mean 2.8 <= 3, mean 0.9 >= 0.8
    assert case("s1_bird", "y", "Y", pc[1:], nominal)["pass"] is False
