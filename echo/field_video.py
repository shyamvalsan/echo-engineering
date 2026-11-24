"""Pressure-field animation for the viewer: frames [T, H, W] (row 0 = ymax) -> VP9 WebM + manifest `field` block."""

from __future__ import annotations

import math
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

# Diverging, dark at zero (sits on the viewer's dark background): cool blue for rarefaction, the viewer's
# accent amber (#f0a848) for compression.
_CMAP = LinearSegmentedColormap.from_list(
    "echo_div", ["#bfe4ff", "#3b8fd9", "#14304f", "#0b0d10", "#4a2e10", "#f0a848", "#fff1d6"], N=256)


def _lut():
    return (np.asarray(_CMAP(np.linspace(0, 1, 256)))[:, :3] * 255).astype(np.uint8)


def render_field_video(frames, extent, path, fps=30, max_width=1280, t0=0.0, dt_frame=None, gain_exponent=0.5,
                       crf=34):
    """Encode `frames` [T, H, W] (pressure, row 0 = ymax) as a VP9 WebM with a keyframe every 5 frames.

    Colour: symmetric limits around zero from a robust percentile of the time-gained field; the time gain
    (t / t_ref)^gain_exponent compensates 2D cylindrical spreading in part so late weak echoes stay visible.
    Returns the manifest `field` block: {file, fps, n_frames, t0_s, sim_seconds_per_frame, extent_m, width, height}.
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
    gain = (np.maximum(t, dtf) / t_ref) ** gain_exponent
    # robust colour limit over a subsample of frames
    sample = frames[:: max(1, T // 40)].astype(np.float32) * gain[:: max(1, T // 40), None, None]
    lim = float(np.percentile(np.abs(sample), 99.7)) or 1.0
    lut = _lut()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio_ffmpeg.write_frames(
        str(path), (Wp, Hp), fps=fps, codec="libvpx-vp9", pix_fmt_in="rgb24", pix_fmt_out="yuv420p",
        macro_block_size=1, quality=None,
        output_params=["-g", "5", "-keyint_min", "1", "-crf", str(crf), "-b:v", "0", "-deadline", "realtime",
                       "-cpu-used", "8", "-row-mt", "1"])
    writer.send(None)
    for i in range(T):
        v = frames[i].astype(np.float32) * gain[i] / lim
        idx = np.clip(np.round((v * 0.5 + 0.5) * 255), 0, 255).astype(np.uint8)
        if Wp != W or Hp != H:
            idx = np.pad(idx, ((0, Hp - H), (0, Wp - W)), mode="edge")
        writer.send(np.ascontiguousarray(lut[idx]))
    writer.close()
    return {"file": path.name, "fps": int(fps), "n_frames": int(T), "t0_s": float(t0),
            "sim_seconds_per_frame": dtf, "extent_m": [float(v) for v in ext], "width": int(Wp), "height": int(Hp)}
