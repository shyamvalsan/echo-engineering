"""Build kit: turn a run folder into fabrication data, and compute the build-physics tables BUILD.md quotes.

Outputs of `build_pack(run_dir)` into `build/<stage>-<run_id>/`:
  stakeout.csv            one row per post, in build order (far rows first), with polar and baseline set-out data
  plan.svg / plan.pdf     to-scale site plan (ISO A paper, standard scale), title block, equal-delay curves
  template_1to10.svg/.dxf 1:10 scale-model drilling / laser template, tiled into stock-size panels (+ panels/*.dxf)
  bom.json / bom.md       count and length per stock diameter, full scale and 1:10 model; wind deflection check
  physics.json            echo level vs post height (free space and rigid ground), wedge slices, placement jitter,
                          scale-model air absorption, Fresnel zones, temperature drift (all from Tier 0, unverified)
  README.md               what each file is and how it was made

Coordinates: the run's own frame. Clap point S = (0, 0), listener L = (0, 0.3), wedge axis = +x (the "baseline").
Bistatic range rho = (|P-S| + |P-L|)/2, echo delay 2 rho / c (global constraints). Nothing here imports Tier 1.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from echo.scene import C0, FS, Scene, alpha_db_per_m, bistatic_range, ellipse_point, fill_fraction

SCALE = 10  # scale-model ratio: lengths / 10, frequencies x 10
ROOT = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------------------------------------------ loading


def load_run(run_dir) -> dict:
    """Read a run folder (data contract). Returns dict(scene, manifest, metrics, profile, stage, run_id, path)."""
    d = Path(run_dir)
    man = json.loads((d / "manifest.json").read_text())
    met = json.loads((d / "metrics.json").read_text()) if (d / "metrics.json").exists() else {}
    prof = json.loads((d / "profile.json").read_text()) if (d / "profile.json").exists() else {}
    scene = Scene.from_dict(json.loads((d / "scene.json").read_text()))
    return {"scene": scene, "manifest": man, "metrics": met, "profile": prof, "stage": man["stage"],
            "run_id": man["run_id"], "path": d}


def pack_name(run: dict) -> str:
    return f"{run['stage']}-{run['run_id']}"


# ------------------------------------------------------------------------------------------------ stake-out

CSV_FIELDS = ["id", "seq", "scene_index", "x_m", "y_m", "radius_m", "diameter_mm", "dist_S_m", "bearing_deg",
              "rho_m", "delay_ms", "along_m", "across_m", "ctrl", "dist_ctrl_m"]


def control_points(scene: Scene) -> dict:
    """Two side control points for tape intersection, outside the field, level with its middle."""
    p = scene.posts
    xm = float(np.round((p[:, 0].min() + p[:, 0].max()) / 2, 1))
    w = float(np.ceil(np.abs(p[:, 1]).max() + 1.0))
    return {"S": (0.0, 0.0), "B+": (xm, w), "B-": (xm, -w)}


def stakeout_rows(scene: Scene, band_m: float = 0.5) -> list[dict]:
    """One dict per post, sorted in build order.

    Build order: by bistatic-range band of `band_m`, farthest band first (the tape from S to the next post never
    crosses posts already set), sweeping across the band in alternating direction (boustrophedon) so the crew walks
    the shortest path. Each row carries
      - polar set-out from the clap point: dist_S_m (tape, the critical number: it sets the range) and bearing_deg
        (angle from the +x baseline, counter-clockwise, positive towards the listener side; tangential, not critical);
      - baseline offsets: along_m (chainage along the +x baseline from S) and across_m (perpendicular, + left);
      - a second tape distance dist_ctrl_m from the side control point `ctrl` (B+ or B-) whose tape crosses the S
        tape closest to 90 degrees, for a two-tape intersection without an instrument.
    """
    p = np.asarray(scene.posts, float)
    s = np.asarray(scene.source, float)
    rho = bistatic_range(p[:, :2], scene.source, scene.listener)
    v = p[:, :2] - s
    dist = np.hypot(v[:, 0], v[:, 1])
    bearing = np.degrees(np.arctan2(v[:, 1], v[:, 0]))
    band = np.floor((rho - rho.min()) / band_m).astype(int)
    nb = band.max()
    # far bands first; within band sweep bearing, direction alternating
    key_dir = np.where((nb - band) % 2 == 0, bearing, -bearing)
    order = np.lexsort((key_dir, -band))
    ctrl = control_points(scene)
    rows = []
    for seq, i in enumerate(order, 1):
        x, y, r = (float(t) for t in p[i])
        best = None
        u = v[i] / max(dist[i], 1e-12)
        for name in ("B+", "B-"):
            c = np.asarray(ctrl[name])
            w = np.array([x, y]) - c
            dw = float(np.hypot(*w))
            cosang = abs(float(u @ (w / dw)))  # 0 = perpendicular (best intersection)
            if best is None or cosang < best[0]:
                best = (cosang, name, dw)
        rows.append({
            "id": f"P{seq:05d}", "seq": seq, "scene_index": int(i),
            "x_m": round(x, 4), "y_m": round(y, 4), "radius_m": round(r, 4), "diameter_mm": round(2000 * r, 1),
            "dist_S_m": round(float(dist[i]), 4), "bearing_deg": round(float(bearing[i]), 4),
            "rho_m": round(float(rho[i]), 4), "delay_ms": round(float(2000 * rho[i] / scene.c), 4),
            "along_m": round(x - float(s[0]), 4), "across_m": round(y - float(s[1]), 4),
            "ctrl": best[1], "dist_ctrl_m": round(best[2], 4),
        })
    return rows


def write_stakeout_csv(rows, path, scene: Scene | None = None):
    path = Path(path)
    with path.open("w", newline="") as f:
        if scene is not None:
            ctrl = control_points(scene)
            f.write(f"# Composed Echo stake-out. Units m, ms, deg. Clap point S=(0,0), listener L=({scene.listener[0]:g},"
                    f"{scene.listener[1]:g}), baseline = +x axis from S. c={scene.c:g} m/s. Controls: "
                    + ", ".join(f"{k}=({v[0]:g},{v[1]:g})" for k, v in ctrl.items()) + "\n")
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_stakeout_csv(path) -> np.ndarray:
    """Posts [N, 3] (x, y, radius) in the original scene order (by scene_index)."""
    with Path(path).open() as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    rows.sort(key=lambda r: int(r["scene_index"]))
    return np.array([[float(r["x_m"]), float(r["y_m"]), float(r["radius_m"])] for r in rows])


def posts_from_polar(rows) -> np.ndarray:
    """Reconstruct (x, y) from the polar set-out columns (dist_S_m, bearing_deg), scene order. For tests/checks."""
    rows = sorted(rows, key=lambda r: int(r["scene_index"]))
    d = np.array([float(r["dist_S_m"]) for r in rows])
    b = np.radians([float(r["bearing_deg"]) for r in rows])
    return np.stack([d * np.cos(b), d * np.sin(b)], axis=1)


# ------------------------------------------------------------------------------------------------ plan drawing

PAPER_MM = {"A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0), "A0": (1189.0, 841.0)}
SCALES = (10, 20, 25, 50, 75, 100, 125, 200, 250, 500, 1000, 2000)
TITLE_H_MM = 48.0
MARGIN_MM = 12.0


def plan_extent(scene: Scene, pad=0.6):
    p = scene.posts
    cp = np.array(list(control_points(scene).values()))
    xs = np.concatenate([p[:, 0] - p[:, 2], p[:, 0] + p[:, 2], [scene.source[0], scene.listener[0]], cp[:, 0]])
    ys = np.concatenate([p[:, 1] - p[:, 2], p[:, 1] + p[:, 2], [scene.source[1], scene.listener[1]], cp[:, 1]])
    return float(xs.min() - pad - 0.6), float(xs.max() + pad), float(ys.min() - pad), float(ys.max() + pad)


def choose_scale(extent, paper="A3"):
    """Largest standard drawing scale (1:n) at which the extent fits the paper's drawing area."""
    W, H = PAPER_MM[paper]
    aw, ah = W - 2 * MARGIN_MM, H - 2 * MARGIN_MM - TITLE_H_MM
    dx, dy = (extent[1] - extent[0]) * 1000, (extent[3] - extent[2]) * 1000
    for n in SCALES:
        if dx / n <= aw and dy / n <= ah:
            return n
    raise ValueError("structure too large for the paper at 1:2000")


def write_plan(run: dict, rows, out_dir, paper="A3"):
    """plan.svg and plan.pdf: to-scale plan with posts as true-size circles. Returns dict(scale, paper)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Circle, Rectangle

    scene = run["scene"]
    ext = plan_extent(scene)
    n = choose_scale(ext, paper)
    W, H = PAPER_MM[paper]
    dw, dh = (ext[1] - ext[0]) * 1000 / n, (ext[3] - ext[2]) * 1000 / n
    fig = plt.figure(figsize=(W / 25.4, H / 25.4))
    left = MARGIN_MM
    bottom = MARGIN_MM + TITLE_H_MM + (H - 2 * MARGIN_MM - TITLE_H_MM - dh) / 2
    ax = fig.add_axes([left / W, bottom / H, dw / W, dh / H])
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_axis_off()
    fig.add_artist(Rectangle((MARGIN_MM / 2 / W, MARGIN_MM / 2 / H), 1 - MARGIN_MM / W, 1 - MARGIN_MM / H,
                             transform=fig.transFigure, fill=False, lw=0.8))
    p = scene.posts
    rho = bistatic_range(p[:, :2], scene.source, scene.listener)
    half = math.radians(scene.half_angle_deg)
    # wedge edges
    rmax = float(np.hypot(p[:, 0], p[:, 1]).max()) + 0.3
    for sgn in (-1, 1):
        ax.plot([0, rmax * math.cos(half)], [0, sgn * rmax * math.sin(half)], color="0.6", lw=0.4, ls="--")
    # equal-delay curves every 1 m of bistatic range (confocal ellipses, foci S and L)
    ang = np.linspace(-half - 0.03, half + 0.03, 200)
    for r in np.arange(math.ceil(rho.min()), math.floor(rho.max()) + 1, 1.0):
        e = ellipse_point(r, ang, scene.source, scene.listener)
        ax.plot(e[:, 0], e[:, 1], color="#4a7fb5", lw=0.35)
        lab = ellipse_point(r, half + 0.05, scene.source, scene.listener)
        ax.text(lab[0], lab[1], f"{r:.0f} m\n{2000 * r / scene.c:.1f} ms", fontsize=4.5, color="#2a5f95",
                ha="center", va="bottom")
    # baseline (+x axis) with 1 m chainage ticks
    ax.plot([0, rmax], [0, 0], color="k", lw=0.6)
    for ch in range(0, int(rmax) + 1):
        ax.plot([ch, ch], [-0.08, 0.08], color="k", lw=0.5)
        if ch % 2 == 0:
            ax.text(ch, -0.12, f"{ch}", fontsize=4, ha="center", va="top")
    ax.text(rmax, 0.12, "baseline (+x, wedge axis)\nchainage m", fontsize=4.5, ha="right", va="bottom")
    # posts, true size
    ax.add_collection(PatchCollection([Circle((x, y), r) for x, y, r in p], facecolor="k", edgecolor="none"))
    # control points, clap point, listener
    for name, (cx, cy) in control_points(scene).items():
        if name == "S":
            continue
        ax.plot([cx], [cy], marker="^", color="#b5534a", ms=4)
        ax.text(cx, cy + 0.15, f"control {name}\n({cx:g}, {cy:g})", fontsize=4.5, ha="center", va="bottom")
    ax.plot([scene.source[0]], [scene.source[1]], marker="o", color="#c0392b", ms=4)
    ax.text(scene.source[0] - 0.1, scene.source[1] - 0.15, "S clap point (0, 0)", fontsize=5, ha="right", va="top")
    ax.plot([scene.listener[0]], [scene.listener[1]], marker="s", color="#2c7a3f", ms=3.5)
    ax.text(scene.listener[0] - 0.1, scene.listener[1] + 0.1,
            f"L listener ({scene.listener[0]:g}, {scene.listener[1]:g})", fontsize=5, ha="right", va="bottom")
    # axis arrow (site north is not fixed by the design)
    ax.annotate("", xy=(ext[0] + 1.6, ext[3] - 0.5), xytext=(ext[0] + 0.4, ext[3] - 0.5),
                arrowprops=dict(arrowstyle="->", lw=0.8))
    ax.text(ext[0] + 0.4, ext[3] - 0.35, "+x = wedge axis. Site north: draw on site ->  N", fontsize=5, va="bottom")
    # scale bar: 5 m in 1 m blocks
    sb = 5 if (ext[1] - ext[0]) > 8 else 1
    x0, y0 = ext[0] + 0.4, ext[2] + 0.35
    for k in range(sb):
        ax.add_patch(Rectangle((x0 + k, y0), 1, 0.12, facecolor="k" if k % 2 == 0 else "w", edgecolor="k", lw=0.4))
    ax.text(x0, y0 + 0.2, f"0", fontsize=5, ha="center")
    ax.text(x0 + sb, y0 + 0.2, f"{sb} m", fontsize=5, ha="center")
    ax.text(x0, y0 - 0.1, f"scale 1:{n} on {paper}  (1 m = {1000 / n:.1f} mm). Check this bar before scaling off.",
            fontsize=5, va="top")
    # title block
    man, met = run["manifest"], run["metrics"]
    hl = met.get("headline", {})
    verified = bool(met.get("verified", man.get("verified", False)))
    tb_w = 190.0
    tx, ty = (W - MARGIN_MM - tb_w) / W, (MARGIN_MM) / H
    fig.add_artist(Rectangle((tx, ty), tb_w / W, (TITLE_H_MM - 4) / H, transform=fig.transFigure, fill=False, lw=0.8))
    counts = {}
    for r in p[:, 2]:
        counts[round(2000 * r)] = counts.get(round(2000 * r), 0) + 1
    lines = [
        f"COMPOSED ECHO - site plan - {man.get('title', run['stage'])}",
        f"stage {run['stage']}   run {run['run_id']}   status {man.get('status')}   "
        + ("VERIFIED (Tier 1)" if verified else "UNVERIFIED, Tier 0 only - do not build full scale from this alone"),
        f"posts: {len(p)}  (" + ", ".join(f"{c} x dia {d} mm" for d, c in sorted(counts.items())) + ")",
        f"bistatic range {rho.min():.2f}-{rho.max():.2f} m, depth {rho.max() - rho.min():.2f} m, wedge +-{scene.half_angle_deg:g} deg",
        f"echo level {hl.get('echo_level_db_re_direct', float('nan')):.1f} dB re direct, "
        f"{hl.get('echo_spl_db', float('nan')):.1f} dB SPL peak (100 dB clap at 1 m), c = {scene.c:g} m/s",
        f"scale 1:{n}, {paper} landscape. Units m. Coordinates in stakeout.csv (build order, far rows first).",
        f"source: runs/{run['stage']}/{run['run_id']}/scene.json   git {man.get('git_commit')}",
    ]
    for k, s in enumerate(lines):
        fig.text(tx + 3 / W, ty + (TITLE_H_MM - 9 - 5.5 * k) / H, s, fontsize=6.5 if k else 8,
                 weight="bold" if k == 0 else "normal", color="#b00" if (k == 1 and not verified) else "k")
    out = Path(out_dir)
    fig.savefig(out / "plan.svg")
    fig.savefig(out / "plan.pdf")
    plt.close(fig)
    return {"scale": n, "paper": paper}


# ------------------------------------------------------------------------------------------------ 1:10 template


def model_holes(scene: Scene, scale=SCALE) -> np.ndarray:
    """Hole centres and diameters for the 1:scale model in mm: [N, 3] = (X, Y, D), same order as scene.posts."""
    p = np.asarray(scene.posts, float)
    k = 1000.0 / scale
    return np.stack([p[:, 0] * k, p[:, 1] * k, 2 * p[:, 2] * k], axis=1)


@dataclass
class Panel:
    row: int
    col: int
    x0: float  # global model mm of the panel's lower-left corner
    y0: float
    w: float
    h: float
    holes: list  # indices whose centre lies in this panel (each hole in exactly one panel)
    split: list  # indices of holes owned by a neighbour whose circle crosses into this panel

    @property
    def name(self):
        return f"R{self.row}C{self.col}"


def tile_panels(holes, panel_w=600.0, panel_h=400.0, margin=20.0, extra_pts=()):
    """Tile hole centres (mm) into a grid of stock panels. Returns (panels, origin).

    Grid origin = min corner of holes (and `extra_pts`, e.g. the clap point and mic) less `margin`. A hole belongs to
    the panel containing its centre (half-open cells, so exactly one); if its circle crosses a cell edge it is also
    listed in that neighbour's `split` so both pieces are cut and the hole closes when the panels are butted.
    Panels that would hold nothing are dropped.
    """
    h = np.asarray(holes, float)
    pts = np.concatenate([h[:, :2], np.asarray(extra_pts, float).reshape(-1, 2)]) if len(extra_pts) else h[:, :2]
    ox, oy = pts[:, 0].min() - margin, pts[:, 1].min() - margin
    col = np.floor((h[:, 0] - ox) / panel_w).astype(int)
    row = np.floor((h[:, 1] - oy) / panel_h).astype(int)
    nx = int(np.floor((pts[:, 0].max() + margin - ox) / panel_w)) + 1
    ny = int(np.floor((pts[:, 1].max() + margin - oy) / panel_h)) + 1
    xp = (pts[:, 0] - ox) // panel_w
    yp = (pts[:, 1] - oy) // panel_h
    used = {(int(r), int(c)) for r, c in zip(row, col)} | {(int(b), int(a)) for a, b in zip(xp, yp)}
    panels = {}
    for r in range(ny):
        for c in range(nx):
            panels[(r, c)] = Panel(r, c, ox + c * panel_w, oy + r * panel_h, panel_w, panel_h, [], [])
    for i, (r, c) in enumerate(zip(row, col)):
        panels[(r, c)].holes.append(i)
        rad = h[i, 2] / 2
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if (dr, dc) == (0, 0) or (r + dr, c + dc) not in panels:
                    continue
                q = panels[(r + dr, c + dc)]
                nxp = min(max(h[i, 0], q.x0), q.x0 + q.w)
                nyp = min(max(h[i, 1], q.y0), q.y0 + q.h)
                if math.hypot(h[i, 0] - nxp, h[i, 1] - nyp) < rad:
                    q.split.append(i)
                    used.add((r + dr, c + dc))
    return [panels[k] for k in sorted(panels) if k in used], (ox, oy)


def _dxf_entities(holes, panels, marks, local: Panel | None = None, reg_step=100.0):
    """DXF entity strings. Global model mm, or panel-local (origin at the panel's lower-left) when `local`."""
    ox, oy = (local.x0, local.y0) if local else (0.0, 0.0)
    out = []

    def circle(x, y, r, layer):
        out.append(f"0\nCIRCLE\n8\n{layer}\n10\n{x - ox:.3f}\n20\n{y - oy:.3f}\n30\n0.0\n40\n{r:.3f}\n")

    def line(x1, y1, x2, y2, layer):
        out.append(f"0\nLINE\n8\n{layer}\n10\n{x1 - ox:.3f}\n20\n{y1 - oy:.3f}\n30\n0.0\n"
                   f"11\n{x2 - ox:.3f}\n21\n{y2 - oy:.3f}\n31\n0.0\n")

    def text(x, y, s, hgt, layer):
        out.append(f"0\nTEXT\n8\n{layer}\n10\n{x - ox:.3f}\n20\n{y - oy:.3f}\n30\n0.0\n40\n{hgt:.2f}\n1\n{s}\n")

    sel = panels if local is None else [local]
    for q in sel:
        for a, b, c, d in ((q.x0, q.y0, q.x0 + q.w, q.y0), (q.x0 + q.w, q.y0, q.x0 + q.w, q.y0 + q.h),
                           (q.x0 + q.w, q.y0 + q.h, q.x0, q.y0 + q.h), (q.x0, q.y0 + q.h, q.x0, q.y0)):
            line(a, b, c, d, "OUTLINE")
        for i in q.holes:
            circle(holes[i, 0], holes[i, 1], holes[i, 2] / 2, "HOLES")
        for i in q.split:
            circle(holes[i, 0], holes[i, 1], holes[i, 2] / 2, "HOLES_SPLIT")
        # registration: crosshairs on the global reg_step grid, 15 mm clear of the panel edge
        gx = np.arange(math.ceil((q.x0 + 15) / reg_step) * reg_step, q.x0 + q.w - 15 + 1e-9, reg_step)
        gy = np.arange(math.ceil((q.y0 + 15) / reg_step) * reg_step, q.y0 + q.h - 15 + 1e-9, reg_step)
        for x in gx:
            for y in gy:
                if np.any(np.hypot(holes[:, 0] - x, holes[:, 1] - y) < 6 + holes[:, 2] / 2):
                    continue
                line(x - 4, y, x + 4, y, "REG")
                line(x, y - 4, x, y + 4, "REG")
        text(q.x0 + 5, q.y0 + 5, f"{q.name} origin ({q.x0:.0f},{q.y0:.0f}) mm TOP FACE not mirrored", 4, "TEXT")
    for name, (x, y) in marks.items():
        if local is not None and not (local.x0 <= x < local.x0 + local.w and local.y0 <= y < local.y0 + local.h):
            continue
        line(x - 6, y, x + 6, y, "MARKS")
        line(x, y - 6, x, y + 6, "MARKS")
        text(x + 3, y + 3, name, 4, "TEXT")
    return out


def write_dxf(path, entities):
    """Minimal ASCII DXF R12 (AC1009): HEADER + ENTITIES. Units mm (stated in the README; R12 has no unit flag)."""
    body = "".join(entities)
    Path(path).write_text("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n"
                          f"0\nSECTION\n2\nENTITIES\n{body}0\nENDSEC\n0\nEOF\n")


def read_dxf_circles(path) -> list[tuple[str, float, float, float]]:
    """(layer, x, y, r) of every CIRCLE in a DXF written by write_dxf. For tests and checks."""
    t = Path(path).read_text().split("\n")
    pairs = list(zip(t[0::2], t[1::2]))
    out, cur = [], None
    for code, val in pairs:
        code = code.strip()
        if code == "0":
            if cur and cur.get("type") == "CIRCLE":
                out.append((cur["8"], float(cur["10"]), float(cur["20"]), float(cur["40"])))
            cur = {"type": val.strip()}
        elif cur is not None:
            cur[code] = val.strip()
    return out


def write_template(run: dict, out_dir, panel_w=600.0, panel_h=400.0, scale=SCALE):
    """template_1to<scale>.svg/.dxf (global) and panels_1to<scale>/<RrCc>.dxf (panel-local). Returns a summary dict.

    scale 10: the tabletop model's baseboard / guide plates. scale 1: full-size CNC-cut deck or template sheets.
    """
    scene = run["scene"]
    out = Path(out_dir)
    tag = f"template_1to{scale}"
    pdir = out / f"panels_1to{scale}"
    reg = 1000.0 / scale
    holes = model_holes(scene, scale)
    k = 1000.0 / scale
    marks = {"S clap/emitter": (scene.source[0] * k, scene.source[1] * k),
             "L mic": (scene.listener[0] * k, scene.listener[1] * k)}
    panels, origin = tile_panels(holes, panel_w, panel_h, extra_pts=list(marks.values()))
    write_dxf(out / f"{tag}.dxf", _dxf_entities(holes, panels, marks, reg_step=reg))
    pdir.mkdir(exist_ok=True)
    for q in panels:
        write_dxf(pdir / f"{q.name}.dxf", _dxf_entities(holes, panels, marks, local=q, reg_step=reg))
    # SVG, global, 1 user unit = 1 mm, y flipped so the drawing reads like the plan (+y up)
    xs = [q.x0 for q in panels] + [q.x0 + q.w for q in panels]
    ys = [q.y0 for q in panels] + [q.y0 + q.h for q in panels]
    x0, x1, y0, y1 = min(xs) - 10, max(xs) + 10, min(ys) - 10, max(ys) + 30
    W, H = x1 - x0, y1 - y0
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}mm" height="{H:.1f}mm" viewBox="0 0 {W:.1f} {H:.1f}">',
         f'<g transform="translate({-x0:.3f},{y1:.3f}) scale(1,-1)">']
    for q in panels:
        s.append(f'<rect x="{q.x0:.2f}" y="{q.y0:.2f}" width="{q.w:.2f}" height="{q.h:.2f}" fill="none" '
                 f'stroke="#888" stroke-width="0.5"/>')
    for i, (x, y, d) in enumerate(holes):
        s.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{d / 2:.3f}" fill="none" stroke="#000" stroke-width="0.1"/>')
    for name, (x, y) in marks.items():
        s.append(f'<path d="M{x - 6:.2f},{y:.2f}H{x + 6:.2f}M{x:.2f},{y - 6:.2f}V{y + 6:.2f}" stroke="#c00" '
                 f'stroke-width="0.4"/>')
    s.append("</g>")
    for q in panels:
        s.append(f'<text x="{q.x0 - x0 + 5:.1f}" y="{y1 - q.y0 - 5:.1f}" font-size="8" fill="#888">{q.name}</text>')
    for name, (x, y) in marks.items():
        s.append(f'<text x="{x - x0 + 4:.1f}" y="{y1 - y - 4:.1f}" font-size="6" fill="#c00">{name}</text>')
    s.append(f'<text x="5" y="{H - 8:.1f}" font-size="7">Composed Echo 1:{scale} template, {run["stage"]} '
             f'{run["run_id"]}. 1 unit = 1 mm at 1:1 print. Viewed from the TOP face (pins come out towards you), '
             f'NOT mirrored. Hole circles at nominal rod diameter; apply kerf/fit offset on the machine.</text>')
    s.append(f'<path d="M5,{H - 20:.1f}h100" stroke="#000" stroke-width="0.6"/>'
             f'<text x="5" y="{H - 22:.1f}" font-size="5">100 mm check bar</text>')
    s.append("</svg>")
    (out / f"{tag}.svg").write_text("\n".join(s))
    diam = {}
    for d in holes[:, 2]:
        diam[f"{d:.1f}"] = diam.get(f"{d:.1f}", 0) + 1
    return {"scale": scale, "files": [f"{tag}.svg", f"{tag}.dxf", f"{pdir.name}/"], "panel_mm": [panel_w, panel_h], "origin_mm": [round(origin[0], 3), round(origin[1], 3)],
            "n_panels": len(panels), "panels": [{"name": q.name, "x0_mm": round(q.x0, 3), "y0_mm": round(q.y0, 3),
                                                 "holes": len(q.holes), "split_holes": len(q.split)} for q in panels],
            "n_holes": int(len(holes)), "n_split": int(sum(len(q.split) for q in panels)), "hole_diameters_mm": diam,
            "mirrored": False,
            "extent_mm": [round(float(holes[:, 0].min()), 1), round(float(holes[:, 0].max()), 1),
                          round(float(holes[:, 1].min()), 1), round(float(holes[:, 1].max()), 1)]}


# ------------------------------------------------------------------------------------------------ bill of materials

# Nearest common stock to each catalog diameter (full scale). Sizes are standard European sections; check locally.
FULL_STOCK = {
    20: [("B500 rebar, nominal dia 20 mm (driven direct, cap the top)", 20.0, 0.0, 210e9, 12.0),
         ("steel tube DN15, 21.3 x 2.0 mm, galvanized", 21.3, 2.0, 210e9, 6.0),
         ("PVC-U conduit 20 mm (too flexible unless guyed - see deflection)", 20.0, 1.5, 3e9, 3.0)],
    40: [("steel tube DN32, 42.4 x 2.6 mm, galvanized", 42.4, 2.6, 210e9, 6.0),
         ("B500 rebar dia 40 mm", 40.0, 0.0, 210e9, 12.0),
         ("PVC-U pipe 40 x 1.9 mm (needs a steel core stake)", 40.0, 1.9, 3e9, 3.0)],
    80: [("steel tube 76.1 x 2.9 mm (DN65), galvanized", 76.1, 2.9, 210e9, 6.0),
         ("PVC-U pipe 75 or 90 mm over a steel stake", 75.0, 1.9, 3e9, 3.0)],
    160: [("PVC-U sewer pipe 160 mm SN4 over a steel stake", 160.0, 4.0, 3e9, 3.0),
          ("steel tube 168.3 x 4.0 mm (DN150)", 168.3, 4.0, 210e9, 6.0)],
}
MODEL_STOCK = {
    2: "dia 2.0 mm mild-steel TIG/gas filler rod in 1 m lengths, or 2 mm silver steel / brass / carbon-fibre rod",
    4: "dia 4 mm silver steel, brass or aluminium rod, 1 m lengths",
    8: "dia 8 mm aluminium or brass rod, or hardwood dowel (+-0.1 mm)",
    16: "dia 16 mm aluminium tube/rod or hardwood dowel",
}


def wind_deflection_mm(od_mm, wall_mm, E, height_m, v=10.0, cd=1.2, rho_air=1.2):
    """Tip deflection (mm) of a cantilever post under steady wind: q = 0.5 rho v^2 Cd D, delta = q H^4 / (8 E I).

    wall_mm 0 = solid bar. Static, uniform wind, rigid foundation; gusts and resonance not included.
    """
    D = od_mm / 1000
    d = 0.0 if wall_mm <= 0 else D - 2 * wall_mm / 1000
    I = math.pi / 64 * (D**4 - d**4)
    q = 0.5 * rho_air * v**2 * cd * D
    return 1000 * q * height_m**4 / (8 * E * I)


def bom(scene: Scene, post_height=2.0, embed=0.6, spare=0.05, scale=SCALE, model_embed_mm=15.0,
        model_stock_mm=1000.0) -> dict:
    """Count and total length per stock diameter, full scale and 1:scale model.

    Full scale: post length = post_height (above ground) + embed (driven or sleeved). Model: pin length =
    post_height/scale + model_embed_mm (into the baseboard). `spare` adds a fraction for breakage (rounded up).
    """
    r = np.round(np.asarray(scene.posts, float)[:, 2] * 2000).astype(int)  # catalog diameter in mm
    full, model = [], []
    L = post_height + embed
    lm = post_height * 1000 / scale + model_embed_mm
    for dmm in sorted(set(r.tolist())):
        n = int((r == dmm).sum())
        n_sp = int(math.ceil(n * (1 + spare)))
        opts = []
        for name, od, wall, E, stock in FULL_STOCK.get(dmm, []):
            per = max(1, int(stock // L))
            opts.append({"item": name, "od_mm": od, "radius_error_mm": round((od - dmm) / 2, 2),
                         "stock_length_m": stock, "pieces_per_stock": per, "stock_lengths": int(math.ceil(n_sp / per)),
                         "wind_tip_deflection_mm_at_10ms": round(wind_deflection_mm(od, wall, E, post_height), 2)})
        full.append({"diameter_mm": dmm, "count": n, "count_with_spare": n_sp, "post_length_m": round(L, 3),
                     "total_length_m": round(n * L, 1), "total_length_with_spare_m": round(n_sp * L, 1),
                     "options": opts})
        md = dmm / scale
        per = max(1, int(model_stock_mm // lm))
        model.append({"diameter_mm": round(md, 2), "count": n, "count_with_spare": n_sp, "pin_length_mm": round(lm, 1),
                      "total_length_m": round(n * lm / 1000, 1), "stock_length_mm": model_stock_mm,
                      "pieces_per_stock": per, "stock_lengths": int(math.ceil(n_sp / per)),
                      "item": MODEL_STOCK.get(int(round(md)), f"dia {md:g} mm rod")})
    return {"post_height_m": post_height, "embed_m": embed, "spare_fraction": spare, "scale": scale,
            "model_post_height_mm": round(post_height * 1000 / scale, 1), "model_embed_mm": model_embed_mm,
            "full_scale": full, "model": model}


def bom_markdown(b: dict, run: dict) -> str:
    L = [f"# Bill of materials: {run['stage']} {run['run_id']}", "",
         f"Post height above ground {b['post_height_m']} m, embedment {b['embed_m']} m, spare "
         f"{100 * b['spare_fraction']:.0f} %. Quantities are computed from scene.json; stock items are suggestions "
         "(nearest standard sections), not quotes.", "", "## Full scale", "",
         "| dia (mm) | posts | +spare | length each (m) | total (m) | stock option | radius error (mm) | "
         "stock lengths | wind tip deflection at 10 m/s (mm) |", "|---|---|---|---|---|---|---|---|---|"]
    for f in b["full_scale"]:
        for k, o in enumerate(f["options"] or [{}]):
            head = (f"| {f['diameter_mm']} | {f['count']} | {f['count_with_spare']} | {f['post_length_m']} | "
                    f"{f['total_length_with_spare_m']} " if k == 0 else "| | | | | ")
            L.append(head + f"| {o.get('item', '-')} | {o.get('radius_error_mm', '-')} | "
                     f"{o.get('stock_lengths', '-')} x {o.get('stock_length_m', '-')} m | "
                     f"{o.get('wind_tip_deflection_mm_at_10ms', '-')} |")
    L += ["", "Wind deflection: steady 10 m/s, Cd 1.2, cantilever from a rigid foundation, static. The radial "
          "placement budget is about 5 mm (BUILD.md), so a post that deflects more than a few mm in the site's working "
          "wind needs a stiffer section or a top tie.", "",
          f"## 1:{b['scale']} model (pins {b['model_post_height_mm']} mm above the board + {b['model_embed_mm']} mm "
          "in the board)", "", "| dia (mm) | pins | +spare | pin length (mm) | total (m) | stock | stock lengths |",
          "|---|---|---|---|---|---|---|"]
    for m in b["model"]:
        L.append(f"| {m['diameter_mm']} | {m['count']} | {m['count_with_spare']} | {m['pin_length_mm']} | "
                 f"{m['total_length_m']} | {m['item']} | {m['stock_lengths']} x {m['stock_length_mm']:.0f} mm "
                 f"({m['pieces_per_stock']} pins each) |")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------------------------------ physics tables


def _design_inputs(run: dict):
    from echo.clap import clap_family
    from echo.inverse import clap_band

    man = run["manifest"]
    cfg = man.get("design", {}).get("config", {})
    claps = clap_family(int(cfg.get("n_claps", 5)), seed=int(man.get("seed", 0)))
    band = tuple(man.get("design", {}).get("loss_band_hz") or clap_band(claps))
    n_out = int(round(float(man.get("duration_s", 0.12)) * FS))
    return claps, band, n_out


def _echo3d(posts, scene, claps, band, n_out, post_height=None, ear_height=1.5):
    import torch

    from echo.tier0 import post_echo

    return post_echo(np.asarray(posts, float), torch.as_tensor(claps), scene, mode="3d", n_out=n_out, band=band,
                     post_height=post_height, ear_height=ear_height).numpy()


def make_judge(run: dict, band):
    """Callable echo[K, n] -> {metric id: clap-family mean} using the stage's own judges (echo.metrics.stage_values).

    Judges only score here (never optimized). Returns None if the stage's target cannot be rebuilt.
    """
    import importlib

    from echo.metrics import stage_values

    try:
        target = importlib.import_module(f"stages.{run['stage']}").CONFIG.make_target()
    except (ImportError, AttributeError):
        return None
    t0 = float(run["manifest"].get("design", {}).get("t_echo0_s", 0.0))

    def judge(e):
        try:
            v = stage_values(run["stage"], e, target, t0, band=band)
        except Exception:  # noqa: BLE001 - a judge failure on a degraded echo is reported as missing
            return None
        keys = [k for k in v[0] if all(isinstance(d.get(k), (int, float)) for d in v)]
        return {k: float(np.mean([d[k] for d in v])) for k in keys}

    return judge


def _level_db(e):
    return float(np.mean(20 * np.log10(np.max(np.abs(e), axis=-1) + 1e-30)))


def _windowed_db(e, t0, t1, win_s=0.01):
    """RMS level (dB) of the clap-family echo in consecutive windows of win_s between t0 and t1 (s)."""
    i0, i1, w = int(t0 * FS), int(t1 * FS), int(win_s * FS)
    out = []
    for a in range(i0, max(i0 + 1, i1 - w + 1), w):
        seg = e[:, a:a + w]
        out.append(10 * np.log10(np.mean(seg**2) + 1e-30))
    return np.array(out)


def ground_cross_posts(posts, scene: Scene, ear_height):
    """Posts moved outwards so their path S'->P->L (image source under rigid ground) is the in-plane path.

    With S and L at height z, the image source is at -z: the cross path is sqrt(L^2 + (2z)^2) instead of L = r1 + r2.
    Moving the post along its ray from S onto the equal-delay ellipse rho + d/2 (d = the extra length) gives exactly
    that delay; the spreading change (d/L, under 1 %) is ignored.
    """
    p = np.asarray(posts, float).copy()
    v = p[:, :2] - scene.source
    r1 = np.hypot(v[:, 0], v[:, 1])
    r2 = np.hypot(*(p[:, :2] - scene.listener).T)
    L = r1 + r2
    d = np.sqrt(L**2 + (2 * ear_height) ** 2) - L
    p[:, :2] = ellipse_point((L + d) / 2, np.arctan2(v[:, 1], v[:, 0]), scene.source, scene.listener)
    return p


def echo_rigid_ground(posts, scene, claps, band, n_out, post_height=None, ear_height=1.5):
    """3D Tier 0 echo with a perfectly rigid flat ground (image method), source and ear both at ear_height.

    The posts stand on the ground (z in [0, h]); with their images they form posts on [-h, h]. The field is that of
    the source and its image (at -z_e) scattered by the doubled posts in free space: a direct term (both ends at z_e,
    i.e. post_height 2h with the ear h + z_e above the doubled post's foot) plus a cross term from the image source
    (path longer by sqrt(L^2 + 4 z_e^2) - L, stationary point near z = 0, i.e. the ear at the doubled post's middle).
    Infinite posts (h None): both terms use infinitely tall posts. Free-field direct clap as the reference.
    Not modelled: ground impedance (grass), ground roughness, the S'->L ground reflection of the direct clap.
    """
    if post_height is None:
        direct = _echo3d(posts, scene, claps, band, n_out)
        cross = _echo3d(ground_cross_posts(posts, scene, ear_height), scene, claps, band, n_out)
    else:
        h = float(post_height)
        direct = _echo3d(posts, scene, claps, band, n_out, 2 * h, h + ear_height)
        cross = _echo3d(ground_cross_posts(posts, scene, ear_height), scene, claps, band, n_out, 2 * h, h)
    return direct + cross


def target_band(run: dict, rel_db=-20.0):
    """Frequency band (Hz) where the target's spectrum is within rel_db of its peak (target.wav)."""
    import soundfile as sf

    p = run["path"] / "target.wav"
    if not p.exists():
        return None
    x, fs = sf.read(p)
    X = np.abs(np.fft.rfft(x, 1 << 16)) ** 2
    f = np.fft.rfftfreq(1 << 16, 1 / fs)
    ok = f[10 * np.log10(X / X.max() + 1e-30) >= rel_db]
    return float(ok.min()), float(ok.max())


def physics_tables(run: dict, heights=(0.5, 1.0, 1.5, 2.0, 3.0, None), ground_ears=(1.5, 1.0, 0.5, 0.3),
                   slices=(20.0, 10.0, 5.0, 2.5), radial_sigmas_mm=(1.0, 2.0, 5.0, 10.0, 20.0),
                   tangential_sigma_mm=50.0, seed=0) -> dict:
    """Every build-physics number BUILD.md quotes for a run, from Tier 0 3D (free-field reference, unverified)."""
    scene = run["scene"]
    posts = scene.posts
    claps, band, n_out = _design_inputs(run)
    c = scene.c
    rho = bistatic_range(posts[:, :2], scene.source, scene.listener)
    t0, t1 = 2 * rho.min() / c, 2 * rho.max() / c
    ref = _echo3d(posts, scene, claps, band, n_out)
    L_inf = _level_db(ref)
    judge = make_judge(run, band) or (lambda e: None)
    out = {"tier": "tier0", "verified": bool(run["metrics"].get("verified", False)), "band_hz": list(band),
           "level_inf_db": L_inf, "judges_inf": judge(ref),
           "judges_note": "stage judges (echo.metrics.stage_values) on the Tier 0 3D echo, clap-family mean"}
    # height, free space, ear 1.5 m
    hs = []
    for h in heights:
        e = ref if h is None else _echo3d(posts, scene, claps, band, n_out, h, 1.5)
        L = _level_db(e)
        hs.append({"post_height_m": h, "ear_height_m": 1.5, "level_db": L, "delta_db": L - L_inf, "judges": judge(e)})
    out["height_free"] = hs
    # rigid ground
    w_ref = _windowed_db(ref, t0, t1)
    gr = []
    for ze in ground_ears:
        for h in heights:
            e = echo_rigid_ground(posts, scene, claps, band, n_out, h, ze)
            w = _windowed_db(e, t0, t1)
            gr.append({"post_height_m": h, "ear_height_m": ze, "level_db": _level_db(e),
                       "delta_db": _level_db(e) - L_inf, "worst_10ms_delta_db": float(np.min(w - w_ref)),
                       "best_10ms_delta_db": float(np.max(w - w_ref)), "judges": judge(e)})
    out["height_rigid_ground"] = gr
    # wedge slices (build only |bearing| <= a)
    bearing = np.degrees(np.abs(np.arctan2(posts[:, 1] - scene.source[1], posts[:, 0] - scene.source[0])))
    sl = []
    for a in slices:
        m = bearing <= a + 1e-9
        e = _echo3d(posts[m], scene, claps, band, n_out) if m.any() else None
        L = None if e is None else _level_db(e)
        sl.append({"half_angle_deg": a, "posts": int(m.sum()), "level_db": L,
                   "delta_db": None if L is None else L - L_inf, "judges": None if e is None else judge(e)})
    out["slices"] = sl
    # placement jitter: radial (along the range gradient) and tangential (along the equal-delay curve)
    # "radial" = along grad rho (the range direction); "tangential" = along the equal-delay ellipse (perpendicular)
    rng = np.random.default_rng(seed)
    v = posts[:, :2] - scene.source
    uS = v / np.hypot(v[:, 0], v[:, 1])[:, None]
    r2v = posts[:, :2] - scene.listener
    g = 0.5 * (uS + r2v / np.hypot(r2v[:, 0], r2v[:, 1])[:, None])
    u = g / np.linalg.norm(g, axis=1, keepdims=True)
    t = np.stack([-u[:, 1], u[:, 0]], axis=1)
    refn = ref / np.linalg.norm(ref, axis=-1, keepdims=True)
    jit = []
    cases = [("radial", s) for s in radial_sigmas_mm] + [("tangential", tangential_sigma_mm)]
    for kind, s in cases:
        dirn = u if kind == "radial" else t
        p = posts.copy()
        p[:, :2] += dirn * rng.normal(0, s / 1000, size=(len(p), 1))
        e = _echo3d(p, scene, claps, band, n_out)
        corr = float(np.mean(np.sum(refn * e, axis=-1) / np.linalg.norm(e, axis=-1)))
        jit.append({"kind": kind, "sigma_mm": s, "level_delta_db": _level_db(e) - L_inf, "waveform_corr": corr,
                    "judges": judge(e)})
    out["jitter"] = jit
    # temperature: the built structure heard at another speed of sound (delays and wavenumbers follow c)
    tc = []
    for T in (0.0, 10.0, 30.0):
        cT = 331.3 * math.sqrt(1 + T / 273.15)
        sT = Scene(source=scene.source, listener=scene.listener, posts=posts, half_angle_deg=scene.half_angle_deg,
                   r_min=scene.r_min, r_max=scene.r_max, c=cT)
        e = _echo3d(posts, sT, claps, band, n_out)
        tc.append({"T_c": T, "c": cT, "level_db": _level_db(e), "judges": judge(e)})
    out["temperature_judged"] = tc
    # range-gradient magnitude: how much of a displacement becomes range error
    # a bearing error from S moves a post perpendicular to uS; the range picks up |g x uS| = sin of the angle between
    sin_b = np.abs(g[:, 0] * uS[:, 1] - g[:, 1] * uS[:, 0])
    out["range_gradient"] = {"min": float(np.linalg.norm(g, axis=1).min()), "max": float(np.linalg.norm(g, axis=1).max()),
                             "bearing_to_range_max": float(sin_b.max()), "bearing_to_range_median": float(np.median(sin_b))}
    # target band, Fresnel zones, range period
    tb = target_band(run) or band
    out["target_band_hz"] = list(tb)
    fz = []
    for f in (tb[0], tb[1]):
        lam = c / f
        for rr in (rho.min(), rho.max()):
            fz.append({"f_hz": f, "rho_m": float(rr), "half_height_m": math.sqrt(lam * rr / 2)})
    out["fresnel"] = fz
    out["range_period_m"] = {"f_hz": tb[1], "period_m": c / (2 * tb[1])}
    # scale model absorption: model path = full path / SCALE at SCALE x frequency
    ab = []
    for fm in (5e3, 10e3, 20e3, 30e3, 40e3):
        for rr in (rho.min(), rho.max()):
            Lf = 2 * rr
            a_model = float(alpha_db_per_m(fm)) * Lf / SCALE
            a_full = float(alpha_db_per_m(fm / SCALE)) * Lf
            ab.append({"f_model_hz": fm, "rho_full_m": float(rr), "path_model_m": Lf / SCALE,
                       "model_db": a_model, "full_db": a_full, "excess_db": a_model - a_full})
    out["scale_absorption"] = ab
    # viscous boundary layer vs post radius (nu = 1.5e-5 m^2/s)
    nu = 1.5e-5
    rmin = float(posts[:, 2].min())
    out["boundary_layer"] = [
        {"case": "full scale", "f_hz": tb[1], "radius_m": rmin,
         "delta_m": math.sqrt(2 * nu / (2 * math.pi * tb[1]))},
        {"case": f"1:{SCALE} model", "f_hz": tb[1] * SCALE, "radius_m": rmin / SCALE,
         "delta_m": math.sqrt(2 * nu / (2 * math.pi * tb[1] * SCALE))}]
    for b in out["boundary_layer"]:
        b["delta_over_radius"] = b["delta_m"] / b["radius_m"]
    # temperature: pitch scales with c
    out["temperature"] = [{"T_c": T, "c": 331.3 * math.sqrt(1 + T / 273.15),
                           "pitch_shift_pct": 100 * (331.3 * math.sqrt(1 + T / 273.15) / c - 1)}
                          for T in (0, 10, 20, 30)]
    out["timing"] = {"t_first_echo_ms": 1000 * t0, "t_last_echo_ms": 1000 * t1}
    return out


# ------------------------------------------------------------------------------------------------ pack


def build_pack(run_dir, out_root=None, post_height=2.0, embed=0.6, panel=(600.0, 400.0), paper="A3",
               physics=True, deck_panel=(2440.0, 1220.0)) -> Path:
    """Write the full build pack for a run folder into out_root/<stage>-<run_id>/. Returns the folder."""
    run = load_run(run_dir)
    out = Path(out_root or ROOT / "build") / pack_name(run)
    out.mkdir(parents=True, exist_ok=True)
    scene = run["scene"]
    rows = stakeout_rows(scene)
    write_stakeout_csv(rows, out / "stakeout.csv", scene)
    plan = write_plan(run, rows, out, paper)
    tmpl = write_template(run, out, *panel)
    deck = write_template(run, out, *deck_panel, scale=1)
    b = bom(scene, post_height, embed)
    (out / "bom.json").write_text(json.dumps(b, indent=1))
    (out / "bom.md").write_text(bom_markdown(b, run))
    summary = {"stage": run["stage"], "run_id": run["run_id"], "run_path": str(Path(run_dir)),
               "status": run["manifest"].get("status"), "verified": bool(run["metrics"].get("verified", False)),
               "posts": int(len(scene.posts)), "depth_m": scene.depth_m, "fill_fraction": fill_fraction(scene),
               "plan": plan, "template": tmpl, "template_full": deck, "control_points": control_points(scene)}
    if physics:
        summary["physics"] = physics_tables(run)
    (out / "pack.json").write_text(json.dumps(summary, indent=1))
    (out / "README.md").write_text(_pack_readme(run, summary, b))
    return out


def _pack_readme(run, s, b):
    t = s["template"]
    return f"""# Build pack: {run['stage']} / {run['run_id']}

Generated by `uv run python -m stages.build_pack {s['run_path']}` from the run folder. Do not edit by hand.
Status: {s['status']}, {'VERIFIED on Tier 1' if s['verified'] else 'UNVERIFIED (Tier 0 only)'}. See BUILD.md for the plan.

| File | What |
|---|---|
| stakeout.csv | one row per post in build order (far rows first). `dist_S_m` = tape from the clap point (critical: sets the range), `bearing_deg` = angle from the +x baseline (CCW +), `along_m`/`across_m` = baseline offsets, `ctrl`/`dist_ctrl_m` = second tape from side control point B+ or B- for a two-tape fix. `rho_m` = bistatic range, `delay_ms` = echo delay at c = {run['scene'].c:g} m/s. |
| plan.svg, plan.pdf | site plan at 1:{s['plan']['scale']} on {s['plan']['paper']} landscape, posts true size. Print at 100 %, check the scale bar. |
| template_1to10.svg/.dxf | 1:{t['scale']} model template, global model mm, all panels. Viewed from the top face, not mirrored. |
| template_1to1.svg/.dxf, panels_1to1/ | the same at full size on {s['template_full']['panel_mm'][0]:.0f} x {s['template_full']['panel_mm'][1]:.0f} mm sheets ({s['template_full']['n_panels']} sheets): CNC-cut deck or setting-out templates for the full-scale build; registration grid 1 m. |
| panels_1to10/RrCc.dxf | one DXF per {t['panel_mm'][0]:.0f} x {t['panel_mm'][1]:.0f} mm panel, panel-local mm (origin = panel lower-left). Layers: HOLES (owned, centre in panel), HOLES_SPLIT (neighbour's hole crossing the edge: cut it too, it closes when panels butt), OUTLINE (cut), REG (crosshairs on the global 100 mm model grid = 1 m full scale, engrave), MARKS (emitter S and mic L), TEXT (engrave). |
| bom.json, bom.md | counts and lengths for post height {b['post_height_m']} m (+{b['embed_m']} m embedded) and for the 1:{b['scale']} model. |
| pack.json | summary and the physics tables BUILD.md quotes. |

Template: {t['n_holes']} holes in {t['n_panels']} panels, {t['n_split']} split-hole copies; diameters (mm): {t['hole_diameters_mm']}.
Panel origin (model mm, global): {t['origin_mm']}. DXF is ASCII R12, units mm (R12 has no unit flag: import as mm).
Hole circles are at the nominal rod diameter; set the kerf / fit offset on the machine.
"""
