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
    for m in b["model"]:  # 1:10: 2 m posts -> 200 mm above the ground plane, diameters / 10
        assert m["diameter_mm"] in (2.0, 4.0)
        a, c = m["options"]["A_laser_plates"], m["options"]["B_cnc_board"]
        assert a["pin_length_mm"] == pytest.approx(256.0)  # 200 + 3 + 50 + 3 mm plate stack, resting on the base
        assert c["pin_length_mm"] == pytest.approx(215.0)  # 200 + 15 mm hole depth
        assert c["total_length_m"] == pytest.approx(m["count"] * 0.215, abs=0.06)
        assert c["pieces_per_stock"] == 4 and a["pieces_per_stock"] == 3


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
    doc.write_text(f"intro\n{bp.SUMMARY_BEGIN}\nold s\n{bp.SUMMARY_END}\nmid\n{bp.BEGIN}\nold\n{bp.END}\noutro\n")
    bp.refresh_doc(doc, f"{bp.BEGIN}\nnew\n{bp.END}")
    assert doc.read_text() == (f"intro\n{bp.SUMMARY_BEGIN}\nold s\n{bp.SUMMARY_END}\nmid\n{bp.BEGIN}\nnew\n{bp.END}"
                               f"\noutro\n")
    bp.refresh_doc(doc, f"{bp.BEGIN}\nnew2\n{bp.END}", f"{bp.SUMMARY_BEGIN}\nnew s\n{bp.SUMMARY_END}")
    assert doc.read_text() == (f"intro\n{bp.SUMMARY_BEGIN}\nnew s\n{bp.SUMMARY_END}\nmid\n{bp.BEGIN}\nnew2\n"
                               f"{bp.END}\noutro\n")


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


def test_bom_markdown_has_no_hand_tolerance():
    sc = _scene(10)
    md = bk.bom_markdown(bk.bom(sc), {"stage": "s", "run_id": "r"})
    assert "budget is about" not in md and "generated block" in md


def test_coherent_factor_hand_calc():
    # sigma 2 mm at 2.6 kHz: sigma_phi = 4 pi 0.002 2600 / 343 = 0.1905; A = exp(-0.1905^2 / 2) = 0.9820
    assert bk.coherent_factor(0.002, 2600.0) == pytest.approx(0.9820, abs=2e-4)
    assert bk.coherent_factor(0.0, 2600.0) == pytest.approx(1.0)


def test_residual_split_sums_and_reconciles():
    rng = np.random.default_rng(0)
    ref = rng.normal(size=(3, 1001))
    e = 0.7 * ref + 0.2 * rng.normal(size=(3, 1001))
    for c in bk.residual_split(ref, e, 1000.0, 1750.0):
        # the four bands partition 0..fs/2, so they sum to the total residual energy / nominal energy
        assert sum(c["res_bands"]) == pytest.approx(c["res_total"], rel=1e-9)
        assert sum(c["nominal_bands"]) == pytest.approx(1.0, rel=1e-9)
        # |r|^2 / |e|^2 = 1 - corr^2 once the common gain is removed
        assert c["res_over_e"] == pytest.approx(c["one_minus_corr2"], rel=1e-9)
    # a pure tone at 1.4 kHz plus a 3 kHz perturbation puts the residual in the "above" band
    t = np.arange(4000) / 16000
    a = np.sin(2 * np.pi * 1400 * t)
    b = a + 0.1 * np.sin(2 * np.pi * 3000 * t)
    (c,) = bk.residual_split(a, b, 1000.0, 1750.0)
    assert c["res_bands"][2] / c["res_total"] > 0.999


def test_bias_to_signal():
    x = 2.0 + np.sin(np.linspace(0, 20 * np.pi, 1000))  # mean 2, RMS modulation 1/sqrt(2)
    b = bk.bias_to_signal({"reflectivity": list(x)})
    assert b["ratio_amp"] == pytest.approx(2 * math.sqrt(2), rel=1e-2)


def test_cached_json_invalidates_on_params_and_sources(tmp_path):
    calls = []

    def compute():
        calls.append(1)
        return {"v": len(calls)}

    p = tmp_path / "c.json"
    assert bk.cached_json(p, {"seeds": [0, 1]}, compute)["v"] == 1
    assert bk.cached_json(p, {"seeds": [0, 1]}, compute)["v"] == 1  # cached
    assert bk.cached_json(p, {"seeds": [0, 1, 2]}, compute)["v"] == 2  # params changed
    assert bk.cached_json(p, {"seeds": [0, 1, 2]}, compute, sources=("def f(): pass",))["v"] == 3  # code changed
    assert len(calls) == 3


def test_cache_key_covers_run_inputs_and_modules(tmp_path, monkeypatch):
    sc = _scene(10)
    d = _run_dir(tmp_path, sc)
    k0 = bk.cache_key({"inputs": bk.run_inputs_hash(d), "target": {"f": 1750}})
    assert bk.cache_key({"inputs": bk.run_inputs_hash(d), "target": {"f": 1750}}) == k0
    assert bk.cache_key({"inputs": bk.run_inputs_hash(d), "target": {"f": 1000}}) != k0  # variant target
    sc2 = _scene(10, seed=2)
    (d / "scene.json").write_text(json.dumps(sc2.to_dict()))  # moved posts -> new run-input hash
    assert bk.cache_key({"inputs": bk.run_inputs_hash(d), "target": {"f": 1750}}) != k0
    # a dependent module's source is part of the key
    mod = tmp_path / "echo"
    mod.mkdir()
    (mod / "tier0.py").write_text("a = 1\n")
    monkeypatch.setattr(bk, "ROOT", tmp_path)
    ka = bk.cache_key({"x": 1}, modules=("echo/tier0.py",))
    (mod / "tier0.py").write_text("a = 2\n")
    assert bk.cache_key({"x": 1}, modules=("echo/tier0.py",)) != ka


def test_snr_gate_and_margins():
    from stages.build_pack import measurement_margins, pitch_shift_pct_for_dT, snr_gate

    thr = {"spec_corr": (0.8, ">=")}
    tab = [{"snr_db": s, "judges": {"spec_corr": {"mean": v, "min": v - 0.01, "max": v + 0.01}}}
           for s, v in ((10, 0.5), (20, 0.85), (25, 0.79), (30, 0.9), (40, 0.95))]
    g = snr_gate({"snr_table": tab}, thr, margin_db=6.0)
    assert g == {"snr_pass_db": 30, "margin_db": 6.0, "gate_db": 36.0}  # the 20 dB pass is not a stable onset
    # margins come from measurement uncertainty only (never from the judge floor): half the seed range at the highest
    # tabulated SNR not above the gate, plus for pitch the c(T) error of a +-0.5 C thermometer
    # c ~ sqrt(T): 100 (sqrt(293.65 / 293.15) - 1) = 0.0853 % at 20 C
    assert pitch_shift_pct_for_dT(0.5, 20.0) == pytest.approx(0.0853, abs=2e-4)
    tab2 = [{"snr_db": 30, "judges": {"spec_corr": {"mean": 0.9, "min": 0.88, "max": 0.92, "n": 3},
                                      "pitch_err_pct": {"mean": 2.9, "min": 2.8, "max": 3.0, "n": 3}}},
            {"snr_db": 40, "judges": {"spec_corr": {"mean": 0.95, "min": 0.95, "max": 0.95, "n": 3},
                                      "pitch_err_pct": {"mean": 2.8, "min": 2.8, "max": 2.8, "n": 3}}}]
    mm = measurement_margins({"snr_table": tab2}, {"spec_corr": (0.8, ">="), "pitch_err_pct": (3.0, "<=")},
                             {"gate_db": 36.0})
    assert mm["spec_corr"]["m"] == pytest.approx(0.02) and mm["spec_corr"]["snr_row_db"] == 30
    assert mm["pitch_err_pct"]["m"] == pytest.approx(0.1 + 0.0853, abs=2e-4)
    lines = "; ".join(bp_margin_lines(mm))
    assert "REPEAT 0.78 to 0.82" in lines and "INCONCLUSIVE" not in lines
    assert measurement_margins({"snr_table": tab2}, {"spec_corr": (0.8, ">=")}, None) == {}  # no gate: no margin


def bp_margin_lines(mm):
    from stages.build_pack import margin_lines

    return margin_lines(mm)


def test_grating_scene_staggered_and_spaced():
    g = bk.grating_scene(3000.0, 30, 5.0)
    rho = bistatic_range(g.posts[:, :2])
    np.testing.assert_allclose(np.diff(rho), 343.0 / 6000.0, atol=1e-9)
    ang = np.degrees(np.arctan2(g.posts[:, 1], g.posts[:, 0]))
    assert np.all(np.abs(np.diff(ang)) > 3.0)  # no post directly behind the previous one


THR = {"pitch_err_pct": (3.0, "<="), "spec_corr": (0.8, ">=")}


def _st(v):
    return {"mean": v, "min": v, "max": v, "n": 1}


def _row(kind, s, judges):
    return {"kind": kind, "sigma_mm": s, "seeds": [0], "level_delta_db": _st(0.1), "waveform_corr": _st(0.99),
            "corr_coherence_estimate": 0.99, "judges": None if judges is None else {k: _st(v) for k, v in judges.items()}}


def _ph(judged=True, pattern=(True, False, True)):
    good, bad = {"pitch_err_pct": 2.0, "spec_corr": 0.9}, {"pitch_err_pct": 2.0, "spec_corr": 0.7}
    j = (lambda ok: (good if ok else bad) if judged else None)
    return {"judges_inf": j(True), "judges_floor": j(True), "judge_status": "ok" if judged else "no target: test",
            "jitter": [_row("radial", s, j(ok)) for s, ok in zip((1.0, 2.0, 5.0), pattern)]
            + [_row("tangential", 50.0, j(True))],
            "height_free": [{"post_height_m": h, "level_db": -40.0, "delta_db": 0.0, "judges": j(True)}
                            for h in (1.0, None)],
            "height_rigid_ground": [{"ear_height_m": 0.5, "post_height_m": 1.0, "level_db": -39.0, "delta_db": 1.0,
                                     "worst_10ms_delta_db": -1.0, "best_10ms_delta_db": 2.0, "judges": j(False)}],
            "slices": [{"half_angle_deg": a, "posts": 9, "level_db": -41.0, "delta_db": -1.0, "judges": j(ok)}
                       for a, ok in ((20.0, True), (10.0, False))],
            "temperature_judged": [{"T_c": 0.0, "c": 331.3, "level_db": -40.0, "judges": j(False)}]}


def test_readout_non_monotone_budget():
    from stages.build_pack import readout

    r = readout(_ph(pattern=(True, False, True)), {"headline": {}}, THR)
    rad = next(b for b in r if b.startswith("Radial"))
    assert "up to 1 mm" in rad and "first failure at 2 mm" in rad and "5 mm" not in rad.split("first failure")[0]
    assert "spec_corr" in rad


def test_readout_not_judged_never_says_fail():
    from stages.build_pack import readout

    r = readout(_ph(judged=False), {"headline": {"echo_spl_db": 60.0}}, THR)
    text = "\n".join(r)
    assert "FAIL" not in text and "fail" not in text.replace("failure", "")
    assert "not judged (no target: test)" in text
    assert "0 of" not in text


def test_generated_block_no_judges(tmp_path):
    from stages import build_pack as bp

    sc = _scene(30)
    rd = _run_dir(tmp_path, sc)
    (rd / "metrics.json").write_text(json.dumps({"verified": False, "headline": {"echo_spl_db": 70.0},
                                                 "metrics": [{"id": "spec_corr", "label": "corr", "threshold": 0.8,
                                                              "comparator": ">=", "pass": True, "value": 0.9,
                                                              "tier": "tier0", "gating": False}]}))
    pd = bk.build_pack(rd, tmp_path / "build", physics=False)
    pk = json.loads((pd / "pack.json").read_text())
    ph = _ph(judged=False)
    ph.update({"verified": False, "level_inf_db": -40.0, "target_band_hz": [2000.0, 3500.0],
               "timing": {"t_first_echo_ms": 18.0, "t_last_echo_ms": 98.0},
               "range_gradient": {"min": 0.999, "max": 1.0, "bearing_to_range_max": 0.04,
                                  "bearing_to_range_median": 0.01},
               "range_period_m": {"f_hz": 3500.0, "period_m": 0.049}, "fresnel": [], "scale_absorption": [],
               "boundary_layer": [], "temperature": [], "jitter_f_center_hz": 2600.0})
    pk["physics"] = ph
    (pd / "pack.json").write_text(json.dumps(pk))
    blk = bp.generated_block([({"stage": "s1_bird", "run_id": "rid"}, rd, pd)])
    assert blk.startswith(bp.BEGIN) and blk.endswith(bp.END)
    assert "not judged" in blk and "FAIL" not in blk


def _met(stage, passed, verified=True, value=0.5, floor=0.9, sub=None, extra=None):
    m = {"stage": stage, "passed": passed, "verified": verified,
         "headline": {"echo_spl_db": 50.0, "echo_level_db_re_direct": -60.5, "depth_m": 10.0, "post_count": 100,
                      "fill_fraction": 0.003, "tier_gap_db": -1.0},
         "metrics": [{"id": "spec_corr", "label": "corr", "value": value, "threshold": 0.8, "comparator": ">=",
                      "pass": value >= 0.8, "tier": "tier1" if verified else "tier0", "gating": verified}],
         "judge_floor": {"mean": {"spec_corr": floor}}, "robustness": [], "robust_summary": "fails everywhere"}
    if sub:
        m.update({"substage": sub, "target_name": sub})
    m.update(extra or {})
    return m


def test_summary_block_multiple_runs_substages_and_floor(tmp_path):
    from stages import build_pack as bp

    rows = []
    for stage, rid, met in (("s4_speech", "20261125-140000-s4_4b_ma", _met("s4_speech", False, sub="4b")),
                            ("s1_bird", "20261125-120000-s1", _met("s1_bird", False, value=0.73)),
                            ("s1_bird", "20261125-100000-s1", _met("s1_bird", False, value=0.64)),
                            ("s1_bird", "20261125-090000-s1", _met("s1_bird", False, verified=False))):
        d = tmp_path / stage / rid
        d.mkdir(parents=True)
        (d / "metrics.json").write_text(json.dumps(met))
        rows.append(({"stage": stage, "run_id": rid}, d))
    blk = bp.summary_block(rows)
    assert blk.startswith(bp.SUMMARY_BEGIN) and blk.endswith(bp.SUMMARY_END)
    # every final run is listed, newest first, with the judge floor beside the judged value
    assert blk.index("120000-s1") < blk.index("100000-s1") < blk.index("090000-s1")
    assert "spec_corr 0.73 (>= 0.8, fail) [floor 0.9]" in blk
    assert "not run on the full-wave solver" in blk  # the Tier-0-only stage-1 run, in the whistle table
    # other stages are one line each, below the whistle table, with their verdict as recorded
    assert blk.index("**Other stages**") < blk.index("s4_speech (4b)") and "FAILED" in blk.split("**Other stages**")[1]
    assert "Latest stage-1 whistle 20261125-120000-s1" in blk  # the newest stage-1 run
    # simulation verdicts use the spec thresholds only: no margin bands anywhere
    assert "INCONCLUSIVE" not in blk and "REPEAT" not in blk


def test_run_table_pilot_reference_thresholds(tmp_path):
    from stages import build_pack as bp

    pilot = {"target_is_stage1_whistle": False, "reference_thresholds": {"spec_corr": [0.8, ">="]},
             "reference_values": {"spec_corr": {"threshold": 0.8, "comparator": ">=", "value": 0.75, "meets": False}}}
    met = _met("build_pilot", False, extra={"pilot": pilot})
    met["metrics"][0].update({"threshold": None, "comparator": None, "pass": None, "gating": False})
    d = tmp_path / "build_pilot" / "rid"
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps(met))
    t = "\n".join(bp.run_table([({"stage": "build_pilot", "run_id": "rid"}, d)]))
    assert "no pass mark (pilot; reference thresholds only)" in t and "reference only: >= 0.8" in t
    assert bp._thr(met) == {"spec_corr": (0.8, ">=")}


def test_jitter_lines_no_coherent_factor_for_tangential():
    from stages.build_pack import jitter_lines

    rows = [_row("radial", 2.0, None), _row("tangential", 50.0, None)]
    L = [x for x in jitter_lines(rows, [], 2600.0) if x.startswith("| radial") or x.startswith("| tangential")]
    assert L[0].split("|")[5].strip() == "0.982"  # hand value: exp(-(4 pi 0.002 2600 / 343)^2 / 2)
    assert L[1].split("|")[5].strip() == "-"


def test_residual_lines_columns_sum_to_total():
    from stages.build_pack import residual_lines

    rng = np.random.default_rng(3)
    ref = rng.normal(size=(2, 2001))
    per = [bk.residual_split(ref, ref + 0.3 * rng.normal(size=ref.shape), 1900.0, 3500.0) for _ in range(2)]
    ex = {"f_band_hz": [1900.0, 3500.0], "f_top_hz": 4000.0, "seeds": [0, 1],
          "residual": [{"sigma_mm": 1.0, "per_seed_per_clap": per}], "nominal_per_clap": bk.residual_split(ref, ref,
                                                                                                         1900, 3500)}
    row = next(x for x in residual_lines(ex, "t") if x.startswith("| 1 |"))
    cells = [float(c.strip().rstrip(" %")) for c in row.split("|")[3:8]]
    assert sum(cells[:4]) == pytest.approx(cells[4], abs=0.03)  # rounding of four 2-decimal cells
    assert "above 4 kHz" in "\n".join(residual_lines(ex, "t"))


def test_stakeout_ring_order():
    # three rings on equal-delay ellipses, three posts each: built ring by ring, far ring first
    pts = []
    for rho in (3.2, 3.3, 3.4):
        for a in (-5.0, 0.0, 5.0):
            pts.append(ellipse_point(rho, math.radians(a)))
    sc = Scene(posts=np.column_stack([np.array(pts), np.full(9, 0.01)]))
    rows = bk.stakeout_rows(sc, by_ring=True)
    assert [r["ring"] for r in rows] == [3, 3, 3, 2, 2, 2, 1, 1, 1]
    assert rows[0]["ring_rho_m"] == pytest.approx(3.4, abs=1e-3)
    b = [r["bearing_deg"] for r in rows]
    assert b[0:3] == sorted(b[0:3]) and b[3:6] == sorted(b[3:6], reverse=True)  # boustrophedon within rings
