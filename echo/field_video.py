"""Pressure-field animation for the viewer: frames [T, H, W] (row 0 = ymax) -> VP9 WebM + manifest `field` block.

Colour mapping (chosen so the scattered field is legible next to the much stronger direct wave):
- symmetric limits +-lim, lim = a high percentile (99.97) of |gained p| over sampled frames EXCLUDING the first
  passage of the direct pulse (pixels within `direct_halfwidth_m` of the circle |x - S| = c t), so the scattered
  field, not the direct front, sets the scale;
- a gentle time gain (t / t_ref)^e: the per-frame level q(t) of that (non-direct) field is fitted as t^b after its peak and
  `gain_exponent` (0.6) of the decay is compensated, e = min(1, -b * gain_exponent), so late echoes stay visible
  without lifting the noise floor to full colour;
- a compressive signed asinh map y = asinh(k p/lim) / asinh(k) (k = `compress`), clipped to [-1, 1]: the direct
  front saturates only on its thin ring, and each post's weak scattered ring still shows;
- a diverging palette whose zero is exactly the viewer background #0e1620 (LUT entry 128).
"""

from __future__ import annotations

import math
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, to_rgb

BACKGROUND = "#0e1620"  # viewer background: zero pressure maps here exactly
_NEG = ["#bfe4ff", "#3b8fd9", "#173a5c"]  # rarefaction, strong -> weak
_POS = ["#4f3414", "#f0a848", "#fff1d6"]  # compression (viewer accent amber), weak -> strong


def _lut():
    """256-entry RGB LUT: index 128 is exactly BACKGROUND (p = 0); 1..127 negative, 129..255 positive."""
    neg = LinearSegmentedColormap.from_list("neg", _NEG + [BACKGROUND], N=128)(np.linspace(0, 1, 128))[:, :3]
    pos = LinearSegmentedColormap.from_list("pos", [BACKGROUND] + _POS, N=128)(np.linspace(0, 1, 128))[:, :3]
    lut = np.concatenate([neg[:1], neg, pos[1:]])  # 1 + 128 + 127 = 256; neg[-1] (index 128) is the background
    lut = (lut * 255).round().astype(np.uint8)
    lut[128] = (np.asarray(to_rgb(BACKGROUND)) * 255).round().astype(np.uint8)
    return lut


def color_index(v):
    """Map a normalized value in [-1, 1] to LUT indices 1..255 with 0 -> 128 exactly."""
    return np.clip(np.round(np.asarray(v, dtype=np.float32) * 127.0) + 128, 1, 255).astype(np.uint8)


def render_field_video(frames, extent, path, fps=30, max_width=1280, t0=0.0, dt_frame=None, gain_exponent=0.6,
                       crf=34, scene=None, c=None, direct_halfwidth_m=1.2, percentile=99.97, compress=2.0,
                       keyint=5):
    """Encode `frames` [T, H, W] (pressure, row 0 = ymax) as a VP9 WebM with a keyframe every `keyint` frames.

    t0: emission-relative sim time of frame 0; dt_frame: sim seconds per frame. scene (optional): its source and c
    locate the direct pulse to exclude from the colour limit (default source (0, 0), c 343).
    Returns the manifest `field` block: {file, fps, n_frames, t0_s, sim_seconds_per_frame, extent_m, width, height}
    plus `colour` (the mapping parameters, informational).
    """
    frames = np.asarray(frames)
    T, H, W = frames.shape
    step = max(1, math.ceil(W / max_width))
    if step > 1:
        frames = frames[:, ::step, ::step]
        T, H, W = frames.shape
    # even dimensions for yuv420p: pad bottom/right by edge replication (extent grows by at most one cell)
    Wp, Hp = W + (W % 2), H + (H % 2)
    xmin, xmax, ymin, ymax = [float(v) for v in extent]
    cell_x, cell_y = (xmax - xmin) / W, (ymax - ymin) / H
    ext = [xmin, xmax + (Wp - W) * cell_x, ymin - (Hp - H) * cell_y, ymax]
    dtf = float(dt_frame) if dt_frame else 1.0
    t = t0 + dtf * np.arange(T)
    t_ref = max(float(np.median(t[t > 0])) if np.any(t > 0) else 1.0, 1e-6)

    src = np.zeros(2) if scene is None else np.asarray(scene.source, dtype=float)
    cc = float(c if c is not None else (scene.c if scene is not None else 343.0))
    xs = xmin + (np.arange(W) + 0.5) * cell_x
    ys = ymax - (np.arange(H) + 0.5) * cell_y
    dist = np.hypot(xs[None, :] - src[0], ys[:, None] - src[1]).astype(np.float32)

    # scattered-field level per sampled frame, the direct pulse's first passage (|r - c t| <= halfwidth) excluded
    ts, qs, vals = [], [], []
    for i in range(0, T, max(1, T // 60)):
        if t[i] <= 0:
            continue
        keep = np.abs(dist - cc * t[i]) > direct_halfwidth_m
        v = np.abs(frames[i].astype(np.float32)[keep])
        if v.size and np.any(v > 0):
            ts.append(t[i])
            qs.append(float(np.percentile(v, percentile)))
            vals.append((t[i], v[:: max(1, v.size // 20000)]))
    # gentle time gain: compensate `gain_exponent` of the fitted power-law decay q ~ t^b of that level
    b = 0.0
    ipk = int(np.argmax(qs)) if qs else 0  # fit the decay after the scattered level peaks
    ok = [(a, q) for a, q in list(zip(ts, qs))[ipk:] if q > 0]
    if len(ok) >= 3:
        la, lq = np.log([a for a, _ in ok]), np.log([q for _, q in ok])
        b = float(np.polyfit(la, lq, 1)[0])
    expo = min(1.0, max(0.0, -b) * gain_exponent)  # gentle: never more than t^1
    gain = (np.maximum(t, dtf) / t_ref) ** expo
    if vals:
        lim = float(np.percentile(np.concatenate([v * (max(a, dtf) / t_ref) ** expo for a, v in vals]), percentile))
    else:
        lim = 0.0
    if not lim > 0:
        lim = float(np.max(np.abs(frames))) or 1.0
    norm = math.asinh(compress)
    lut = _lut()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio_ffmpeg.write_frames(
        str(path), (Wp, Hp), fps=fps, codec="libvpx-vp9", pix_fmt_in="rgb24", pix_fmt_out="yuv420p",
        macro_block_size=1, quality=None,
        output_params=["-g", str(int(keyint)), "-keyint_min", "1", "-crf", str(crf), "-b:v", "0", "-deadline",
                       "realtime", "-cpu-used", "8", "-row-mt", "1"])
    writer.send(None)
    for i in range(T):
        v = np.arcsinh(frames[i].astype(np.float32) * (gain[i] * compress / lim)) / norm
        idx = color_index(np.clip(v, -1.0, 1.0))
        if Wp != W or Hp != H:
            idx = np.pad(idx, ((0, Hp - H), (0, Wp - W)), mode="edge")
        writer.send(np.ascontiguousarray(lut[idx]))
    writer.close()
    return {"file": path.name, "fps": int(fps), "n_frames": int(T), "t0_s": float(t0),
            "sim_seconds_per_frame": dtf, "extent_m": [float(v) for v in ext], "width": int(Wp), "height": int(Hp),
            "colour": {"limit": lim, "percentile": percentile, "direct_excluded_halfwidth_m": direct_halfwidth_m,
                       "compress": "asinh", "compress_k": compress, "level_decay_exponent": b,
                       "time_gain_exponent": expo,
                       "t_ref_s": t_ref, "zero_rgb": BACKGROUND}}
