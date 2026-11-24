"""Scene geometry: constants, wedge, post catalog, bistatic range, air absorption, scene.json I/O.

Conventions (global constraints): SI units, source at the origin, listener at (0, 0.3), wedge axis +x.
Delay-relevant "range" is the bistatic range rho(P) = (|P-S| + |P-L|) / 2; echo delay is 2*rho/C0.
Equal-delay curves are confocal ellipses with foci S and L.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

C0 = 343.0  # m/s, 20 C
FS = 16000  # Hz, sample rate for every signal and echo
F_LO = 500.0  # Hz, design band low edge
F_HI = 4000.0  # Hz, design band high edge
BAND = (F_LO, F_HI)
SOURCE = np.array([0.0, 0.0])
LISTENER = np.array([0.0, 0.3])
SL_DIST = float(np.linalg.norm(LISTENER - SOURCE))  # 0.3 m
T_DIRECT = SL_DIST / C0  # direct-sound arrival at the listener, 0.875 ms
HALF_ANGLE_DEG = 20.0
R_MIN = 3.0  # m, posts start here (distance from the source)
RADII = (0.01, 0.02, 0.04, 0.08)  # m, post radius catalog
MIN_GAP = 0.05  # m, minimum gap between post surfaces


def bistatic_range(xy, source=SOURCE, listener=LISTENER, *, xp=np):
    """rho(P) = (|P-S| + |P-L|)/2 for points xy[..., 2]. Works with numpy, or torch via xp=torch."""
    if xp is np:
        xy = np.asarray(xy, dtype=float)
        s = np.asarray(source, dtype=float)
        l = np.asarray(listener, dtype=float)
        return 0.5 * (np.linalg.norm(xy - s, axis=-1) + np.linalg.norm(xy - l, axis=-1))
    s = xp.as_tensor(source, dtype=xy.dtype, device=xy.device)
    l = xp.as_tensor(listener, dtype=xy.dtype, device=xy.device)
    return 0.5 * (xp.linalg.norm(xy - s, dim=-1) + xp.linalg.norm(xy - l, dim=-1))


def echo_delay(xy, c=C0, source=SOURCE, listener=LISTENER):
    """Emission-to-arrival time (s) of the single-scattering path source -> P -> listener."""
    return 2.0 * bistatic_range(xy, source, listener) / c


def ellipse_point(rho, angle, source=SOURCE, listener=LISTENER):
    """Point on the equal-delay ellipse |P-S| + |P-L| = 2*rho at polar angle `angle` (rad) about S from +x.

    Broadcasts over rho and angle; returns array [..., 2]. Requires 2*rho > |SL|.
    Derivation: P = S + r*u, |P-L| = 2rho - r, d = L - S  =>  r = (4 rho^2 - |d|^2) / (4 rho - 2 u.d).
    """
    rho = np.asarray(rho, dtype=float)
    angle = np.asarray(angle, dtype=float)
    s = np.asarray(source, dtype=float)
    d = np.asarray(listener, dtype=float) - s
    ux, uy = np.cos(angle), np.sin(angle)
    r = (4.0 * rho**2 - d @ d) / (4.0 * rho - 2.0 * (ux * d[0] + uy * d[1]))
    return np.stack([s[0] + r * ux, s[1] + r * uy], axis=-1)


def in_wedge(xy, half_angle_deg=HALF_ANGLE_DEG, r_min=R_MIN, r_max=np.inf, source=SOURCE):
    """True where a point lies in the wedge: |polar angle about S from +x| <= half angle, r_min <= |P-S| <= r_max."""
    v = np.asarray(xy, dtype=float) - np.asarray(source, dtype=float)
    r = np.hypot(v[..., 0], v[..., 1])
    ang = np.degrees(np.abs(np.arctan2(v[..., 1], v[..., 0])))
    return (ang <= half_angle_deg + 1e-9) & (r >= r_min - 1e-9) & (r <= r_max + 1e-9)


def check_gaps(posts) -> float:
    """Minimum surface-to-surface gap (m) over all post pairs; +inf for fewer than two posts. Exact.

    posts: array [N, 3] of (x, y, radius). Compare the result against MIN_GAP.
    """
    p = np.asarray(posts, dtype=float).reshape(-1, 3)
    n = len(p)
    if n < 2:
        return float("inf")
    xy, rad = p[:, :2], p[:, 2]
    tree = cKDTree(xy)
    d, j = tree.query(xy, k=2)
    g_nn = float(np.min(d[:, 1] - rad - rad[j[:, 1]]))  # an upper bound on the true minimum
    # Any pair with gap < g_nn has centre distance < g_nn + 2*max radius.
    pairs = tree.query_pairs(r=max(g_nn, 0.0) + 2.0 * rad.max() + 1e-12, output_type="ndarray")
    if len(pairs) == 0:
        return g_nn
    a, b = pairs[:, 0], pairs[:, 1]
    gaps = np.linalg.norm(xy[a] - xy[b], axis=1) - rad[a] - rad[b]
    return float(min(g_nn, gaps.min()))


def alpha_db_per_m(f, T=20.0, rh=50.0, pa_kpa=101.325):
    """Atmospheric absorption coefficient (dB/m) per ISO 9613-1:1993, eqs. (3)-(5) and Annex B.

    f: frequency in Hz (array ok). T: air temperature in C. rh: relative humidity in %. pa_kpa: pressure.
    """
    f = np.asarray(f, dtype=float)
    pr = 101.325
    pa = pa_kpa / pr  # pa/pr
    TK = T + 273.15
    T0 = 293.15
    T01 = 273.16
    c_sat = -6.8346 * (T01 / TK) ** 1.261 + 4.6151
    h = rh * 10.0**c_sat / pa  # molar concentration of water vapour, %
    fr_o = pa * (24.0 + 4.04e4 * h * (0.02 + h) / (0.391 + h))
    fr_n = pa * (TK / T0) ** -0.5 * (9.0 + 280.0 * h * np.exp(-4.170 * ((TK / T0) ** (-1.0 / 3.0) - 1.0)))
    return 8.686 * f**2 * (
        1.84e-11 / pa * (TK / T0) ** 0.5
        + (TK / T0) ** -2.5
        * (
            0.01275 * np.exp(-2239.1 / TK) / (fr_o + f**2 / fr_o)
            + 0.1068 * np.exp(-3352.0 / TK) / (fr_n + f**2 / fr_n)
        )
    )


@dataclass
class Scene:
    """Source, listener and posts. posts is [N, 3] of (x, y, radius) in metres.

    r_max None means "derived from the posts" (outermost post edge, or r_min if there are none).
    """

    source: np.ndarray = field(default_factory=lambda: SOURCE.copy())
    listener: np.ndarray = field(default_factory=lambda: LISTENER.copy())
    posts: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    half_angle_deg: float = HALF_ANGLE_DEG
    r_min: float = R_MIN
    r_max: float | None = None
    c: float = C0

    def __post_init__(self):
        self.source = np.asarray(self.source, dtype=float).reshape(2)
        self.listener = np.asarray(self.listener, dtype=float).reshape(2)
        self.posts = np.asarray(self.posts, dtype=float).reshape(-1, 3)

    @property
    def effective_r_max(self) -> float:
        if self.r_max is not None:
            return float(self.r_max)
        if len(self.posts) == 0:
            return float(self.r_min)
        r = np.linalg.norm(self.posts[:, :2] - self.source, axis=1) + self.posts[:, 2]
        return float(max(self.r_min, r.max()))

    @property
    def depth_m(self) -> float:
        """Total range depth of the structure: outermost minus innermost bistatic range of the posts."""
        if len(self.posts) == 0:
            return 0.0
        rho = bistatic_range(self.posts[:, :2], self.source, self.listener)
        return float(rho.max() - rho.min())

    def to_dict(self) -> dict:
        return {
            "units": "m",
            "c": float(self.c),
            "source": [float(v) for v in self.source],
            "listener": [float(v) for v in self.listener],
            "wedge": {
                "half_angle_deg": float(self.half_angle_deg),
                "r_min": float(self.r_min),
                "r_max": self.effective_r_max,
            },
            "posts": [[float(x), float(y), float(r)] for x, y, r in self.posts],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        w = d.get("wedge", {})
        return cls(
            source=d.get("source", SOURCE),
            listener=d.get("listener", LISTENER),
            posts=np.asarray(d.get("posts", []), dtype=float).reshape(-1, 3),
            half_angle_deg=w.get("half_angle_deg", HALF_ANGLE_DEG),
            r_min=w.get("r_min", R_MIN),
            r_max=w.get("r_max"),
            c=d.get("c", C0),
        )


def fill_fraction(scene: Scene) -> float:
    """Total post cross-section area divided by the wedge area between r_min and r_max."""
    r0, r1 = scene.r_min, scene.effective_r_max
    wedge_area = np.radians(scene.half_angle_deg) * (r1**2 - r0**2)  # (2*half)/2 * (r1^2 - r0^2)
    if wedge_area <= 0:
        return 0.0
    return float(np.pi * np.sum(scene.posts[:, 2] ** 2) / wedge_area)


def to_json(scene: Scene, path=None) -> str:
    """Serialize to the scene.json data contract; write to `path` if given. Returns the JSON text."""
    text = json.dumps(scene.to_dict(), indent=1)
    if path is not None:
        Path(path).write_text(text)
    return text


def from_json(src) -> Scene:
    """Load a Scene from a scene.json path or a JSON string."""
    if isinstance(src, Path) or (isinstance(src, str) and not src.lstrip().startswith("{")):
        src = Path(src).read_text()
    return Scene.from_dict(json.loads(src))
