"""Field video colour mapping: zero pressure is exactly the viewer background; direct pulse excluded from the limit."""

import json

import numpy as np

from echo.field_video import BACKGROUND, _lut, color_index, render_field_video


def test_zero_maps_to_viewer_background():
    lut = _lut()
    assert lut.shape == (256, 3)
    assert color_index(0.0) == 128
    assert tuple(lut[128]) == (0x0e, 0x16, 0x20) and BACKGROUND == "#0e1620"
    assert color_index(1.0) == 255 and color_index(-1.0) == 1
    # monotone brightness away from zero on the positive side
    lum = lut.astype(float) @ [0.299, 0.587, 0.114]
    assert np.all(np.diff(lum[128:]) >= -1.0)


def test_limit_ignores_direct_pulse(tmp_path):
    # field: a strong ring at r = c t (the direct pulse, amplitude 100) plus a weak uniform pattern (amplitude 1).
    T, H, W = 20, 40, 80
    ext = [0.0, 8.0, -2.0, 2.0]
    xs = 0.05 + 0.1 * np.arange(W)
    ys = 1.95 - 0.1 * np.arange(H)
    r = np.hypot(xs[None, :], ys[:, None])
    dtf = 0.001
    frames = np.zeros((T, H, W), np.float32)
    for i in range(T):
        t = (i + 1) * dtf
        frames[i] = np.sin(7 * xs)[None, :] * np.ones((H, 1)) + 100 * (np.abs(r - 343 * t) < 0.15)
    blk = render_field_video(frames.astype(np.float16), ext, tmp_path / "f.webm", t0=dtf, dt_frame=dtf,
                             gain_exponent=0.0)
    lim = blk["colour"]["limit"]
    assert 0.5 < lim < 1.5  # set by the weak field, not by the 100x direct ring
    json.dumps(blk)
