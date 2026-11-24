"""Build kit: stake-out round trip, 1:10 scaling, panel tiling, BOM totals, ground image geometry, doc block."""

import json
import math

import numpy as np
import pytest
import torch

from echo import buildkit as bk
from echo.scene import Scene, bistatic_range, ellipse_point


def _scene(n=60, seed=1, radii=(0.01,)):
    rng = np.random.default_rng(seed)
    rho = rng.uniform(3.1, 9.0, n)
    ang = np.radians(rng.uniform(-19, 19, n))
    xy = ellipse_point(rho, ang)
    r = rng.choice(radii, n)
    return Scene(posts=np.column_stack([xy, r]))


def _run_dir(tmp_path, scene):
    d = tmp_path / "runs" / "s1_bird" / "rid"
    d.mkdir(parents=True)
    (d / "scene.json").write_text(json.dumps(scene.to_dict()))
    (d / "manifest.json").write_text(json.dumps({"run_id": "rid", "stage": "s1_bird", "title": "t", "status": "final",
                                                 "verified": False, "seed": 0, "duration_s": 0.08}))
    (d / "metrics.json").write_text(json.dumps({"verified": False, "headline": {"echo_level_db_re_direct": -40.0,
                                                                                "echo_spl_db": 70.5}}))
    return d


def test_stakeout_csv_round_trip(tmp_path):
    sc = _scene(radii=(0.01, 0.02, 0.04, 0.08))
    rows = bk.stakeout_rows(sc)
    p = tmp_path / "s.csv"
    bk.write_stakeout_csv(rows, p, sc)
    back = bk.read_stakeout_csv(p)
    assert back.shape == sc.posts.shape
    np.testing.assert_allclose(back, sc.posts, atol=0.6e-4)  # written to 0.1 mm
    # the polar set-out columns alone reproduce the positions (bearing to 1e-4 deg: 1.6e-5 m at 9 m)
    np.testing.assert_allclose(bk.posts_from_polar(rows), sc.posts[:, :2], atol=2e-4)
    # derived columns agree with the scene geometry
    for r in rows:
        x, y = r["x_m"], r["y_m"]
        assert r["rho_m"] == pytest.approx(float(bistatic_range([x, y])), abs=2e-4)
        assert r["delay_ms"] == pytest.approx(2000 * r["rho_m"] / 343.0, abs=2e-3)
        c = bk.control_points(sc)[r["ctrl"]]
        assert r["dist_ctrl_m"] == pytest.approx(math.hypot(x - c[0], y - c[1]), abs=2e-4)


def test_build_order_far_first_and_complete():
    sc = _scene(200)
    rows = bk.stakeout_rows(sc, band_m=0.5)
    assert sorted(r["scene_index"] for r in rows) == list(range(200))
    rho = np.array([r["rho_m"] for r in rows])
    band = np.floor((rho - rho.min()) / 0.5)
    assert np.all(np.diff(band) <= 0)  # bands never move outwards
    assert [r["id"] for r in rows][:2] == ["P00001", "P00002"]


def test_scale_factor_and_dxf(tmp_path):
    sc = _scene(radii=(0.01, 0.04))
    h = bk.model_holes(sc)
    # 1:10, metres -> mm: x_model_mm = 1000 x / 10 = 100 x; diameter = 2 r * 100 (1 cm radius -> 2 mm hole)
    np.testing.assert_allclose(h[:, 0], 100 * sc.posts[:, 0])
    np.testing.assert_allclose(h[:, 1], 100 * sc.posts[:, 1])
    np.testing.assert_allclose(h[:, 2], 200 * sc.posts[:, 2])
    assert set(np.round(h[:, 2], 6)) == {2.0, 8.0}
    run = {"scene": sc, "stage": "s1_bird", "run_id": "x", "manifest": {}, "metrics": {}}
    s = bk.write_template(run, tmp_path, 300.0, 200.0)
    circ = [c for c in bk.read_dxf_circles(tmp_path / "template_1to10.dxf") if c[0] == "HOLES"]
    assert len(circ) == len(sc.posts) == s["n_holes"]
    got = np.array(sorted((round(x, 3), round(y, 3), round(2 * r, 3)) for _, x, y, r in circ))
    want = np.array(sorted((round(x, 3), round(y, 3), round(d, 3)) for x, y, d in h))
    np.testing.assert_allclose(got, want, atol=1e-3)
    # panel-local files: owned holes summed over panels = every hole once, shifted by the panel origin
    tot = 0
    for p in s["panels"]:
        cl = [c for c in bk.read_dxf_circles(tmp_path / "panels_1to10" / f"{p['name']}.dxf") if c[0] == "HOLES"]
        assert len(cl) == p["holes"]
        for _, x, y, r in cl:
            assert -1e-6 <= x < 300.0 and -1e-6 <= y < 200.0
        tot += len(cl)
    assert tot == len(sc.posts)
    assert s["mirrored"] is False


@pytest.mark.parametrize("pw,ph", [(600.0, 400.0), (150.0, 90.0), (37.0, 23.0)])
def test_tiling_covers_every_hole_once(pw, ph):
    sc = _scene(400, seed=3, radii=(0.01, 0.08))
    h = bk.model_holes(sc)
    panels, (ox, oy) = bk.tile_panels(h, pw, ph)
    owned = [i for q in panels for i in q.holes]
    assert sorted(owned) == list(range(len(h)))  # exactly once
    for q in panels:
        for i in q.holes:  # centre inside its own panel (half-open)
            assert q.x0 <= h[i, 0] < q.x0 + q.w and q.y0 <= h[i, 1] < q.y0 + q.h
        for i in q.split:  # split copies really cross into this panel and are owned elsewhere
            assert i not in q.holes
            nx = min(max(h[i, 0], q.x0), q.x0 + q.w)
            ny = min(max(h[i, 1], q.y0), q.y0 + q.h)
            assert math.hypot(h[i, 0] - nx, h[i, 1] - ny) < h[i, 2] / 2
        assert (q.x0 - ox) / pw == pytest.approx(round((q.x0 - ox) / pw))  # on the grid
    # a hole whose circle crosses an edge has at least one split copy
    for q in panels:
        for i in q.holes:
            r = h[i, 2] / 2
            crosses = (h[i, 0] - q.x0 < r or q.x0 + q.w - h[i, 0] < r or h[i, 1] - q.y0 < r or q.y0 + q.h - h[i, 1] < r)
            if crosses:
                assert any(i in p.split for p in panels)


def test_bom_totals():
    sc = _scene(100, radii=(0.01, 0.02))
    b = bk.bom(sc, post_height=2.0, embed=0.6, spare=0.05)
    n = {f["diameter_mm"]: f["count"] for f in b["full_scale"]}
    assert sum(n.values()) == 100
    assert n[20] == int(np.sum(np.isclose(sc.posts[:, 2], 0.01)))
    for f in b["full_scale"]:
        assert f["post_length_m"] == pytest.approx(2.6)
        assert f["total_length_m"] == pytest.approx(f["count"] * 2.6, abs=0.06)
        assert f["count_with_spare"] == math.ceil(f["count"] * 1.05)
        for o in f["options"]:
            assert o["pieces_per_stock"] == int(o["stock_length_m"] // 2.6)
            assert o["stock_lengths"] * o["pieces_per_stock"] >= f["count_with_spare"]
    for m in b["model"]:  # 1:10: 2 m posts -> 200 mm pins + 15 mm embed, diameters / 10
        assert m["pin_length_mm"] == pytest.approx(215.0)
        assert m["diameter_mm"] in (2.0, 4.0)
        assert m["total_length_m"] == pytest.approx(m["count"] * 0.215, abs=0.06)
        assert m["pieces_per_stock"] == 4


def test_wind_deflection_hand_calc():
    # solid 20 mm steel bar, 2 m cantilever, 10 m/s, Cd 1.2:
    # q = 0.5*1.2*100*1.2*0.02 = 1.44 N/m; I = pi d^4/64 = 7.854e-9 m^4; EI = 1649.3 N m^2
    # delta = q L^4 / (8 EI) = 1.44*16 / 13194.7 = 1.746 mm
    assert bk.wind_deflection_mm(20.0, 0.0, 210e9, 2.0) == pytest.approx(1.746, abs=0.005)


def test_ground_cross_path_delay():
    sc = _scene(30)
    ze = 1.2
    moved = bk.ground_cross_posts(sc.posts, sc, ze)
    r1 = np.hypot(*sc.posts[:, :2].T)
    r2 = np.hypot(*(sc.posts[:, :2] - sc.listener).T)
    want = np.sqrt((r1 + r2) ** 2 + (2 * ze) ** 2)  # unfolded image path S' -> P -> L
    m1 = np.hypot(*moved[:, :2].T)
    m2 = np.hypot(*(moved[:, :2] - sc.listener).T)
    np.testing.assert_allclose(m1 + m2, want, atol=2e-4)  # 0.2 mm, under 2 % of a period at 4 kHz


def test_rigid_ground_low_ear_doubles_echo():
    # Ear and clap at 1 cm over rigid ground: the image source coincides with the source, so infinite posts
    # return twice the free-space echo: +20 log10(2) = +6.02 dB.
    from echo.clap import clap_family

    sc = _scene(20)
    claps = clap_family(2, seed=0)
    band = (900.0, 4000.0)
    free = bk._echo3d(sc.posts, sc, claps, band, 1200)
    gr = bk.echo_rigid_ground(sc.posts, sc, claps, band, 1200, None, 0.01)
    assert bk._level_db(gr) - bk._level_db(free) == pytest.approx(6.02, abs=0.1)


def test_refresh_doc_replaces_only_block(tmp_path):
    from stages import build_pack as bp

    doc = tmp_path / "B.md"
    doc.write_text(f"intro\n{bp.BEGIN}\nold\n{bp.END}\noutro\n")
    bp.refresh_doc(doc, f"{bp.BEGIN}\nnew\n{bp.END}")
    assert doc.read_text() == f"intro\n{bp.BEGIN}\nnew\n{bp.END}\noutro\n"


def test_build_pack_writes_all_files(tmp_path):
    sc = _scene(40)
    d = _run_dir(tmp_path, sc)
    out = bk.build_pack(d, tmp_path / "build", physics=False)
    for f in ("stakeout.csv", "plan.svg", "plan.pdf", "template_1to10.svg", "template_1to10.dxf", "template_1to1.dxf",
              "template_1to1.svg", "bom.json",
              "bom.md", "pack.json", "README.md"):
        assert (out / f).stat().st_size > 0, f
    assert out.name == "s1_bird-rid"
    pk = json.loads((out / "pack.json").read_text())
    assert pk["posts"] == 40 and pk["plan"]["scale"] in bk.SCALES
    svg = (out / "plan.svg").read_text()
    assert 'width="1190.' in svg  # A3 landscape: 420 mm = 1190.55 pt, so the drawing scale survives printing
