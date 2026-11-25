*Appendix of [REPORT.md](../../REPORT.md); generated 2026-11-25T17:15+02:00 by `uv run python -m stages.report`.*

# Solver validation

Source: `runs/validation/metrics.json` (engine `fd8-3`, 10 points per wavelength). Overall `passed`: **yes**.

| check | value | threshold | result | key |
|---|---|---|---|---|
| 1. Single rigid cylinder, backscatter vs analytic (stage-1 grid, all catalog radii) | worst 0.93 dB | ≤ 1.0 dB | PASS | checks.cylinder.stage1_grid.per_radius.*.max_abs_err_db |
| 2. Grid convergence (halve dx), sparse reference design | 0.75 dB | < 1 dB | PASS | checks.grid_convergence.sparse.max_abs_delta_db |
| 2b. Grid convergence, dense patch (self-convergence only) | 0.36 dB | < 1 dB | PASS | checks.grid_convergence.dense.max_abs_level_delta_db |
| 3. Empty scene: nothing after the direct clap | -85.4 dB | < -60 dB | PASS | checks.empty_scene.max_after_direct_db |
| 4. Tier 0 vs Tier 1, sparse design | 1.05 dB | ≤ 2.0 dB | PASS | checks.tier0_vs_tier1.max_abs_delta_db |

Per grid and post radius (error vs the analytic cylinder, dB; forward and 90° are an extended check beyond the spec):

| grid f_max | radius | backscatter err | spec check | forward err | 90° err | worst any angle | all angles |
|---|---|---|---|---|---|---|---|
| 4000 Hz (`stage1_grid`) | 1 cm | 0.77 | PASS | 1.04 | 1.77 | 1.77 | FAIL |
| 4000 Hz (`stage1_grid`) | 2 cm | 0.62 | PASS | 1.47 | 0.43 | 1.47 | FAIL |
| 4000 Hz (`stage1_grid`) | 4 cm | 0.93 | PASS | — | — | 0.93 | PASS |
| 4000 Hz (`stage1_grid`) | 8 cm | 0.64 | PASS | — | — | 0.64 | PASS |
| 2500 Hz (`stage2_grid`) | 1 cm | 0.74 | PASS | 2.61 | 0.51 | 2.61 | FAIL |
| 2500 Hz (`stage2_grid`) | 2 cm | 0.38 | PASS | 1.73 | 1.65 | 1.73 | FAIL |
| 2500 Hz (`stage2_grid`) | 4 cm | 0.62 | PASS | — | — | 0.62 | PASS |
| 2500 Hz (`stage2_grid`) | 8 cm | 0.96 | PASS | — | — | 0.96 | PASS |
| 2000 Hz (`stage3_grid`) | 1 cm | 2.54 | FAIL | 1.21 | 2.82 | 2.82 | FAIL |
| 2000 Hz (`stage3_grid`) | 2 cm | 0.30 | PASS | 0.89 | 0.66 | 0.89 | PASS |
| 2000 Hz (`stage3_grid`) | 4 cm | 0.75 | PASS | — | — | 0.75 | PASS |
| 2000 Hz (`stage3_grid`) | 8 cm | 0.74 | PASS | — | — | 0.74 | PASS |

Grid and post radius each result used, and whether those posts are validated there:

| unit | grid f_max | post radius | backscatter-validated | all-angle-validated |
|---|---|---|---|---|
| 1 | 4000 Hz | 1 cm | PASS | FAIL |
| 2 | 2500 Hz | 1 cm | PASS | FAIL |
| 3 100 ms | 2500 Hz | 1 cm | PASS | FAIL |
| 3 60 ms | 2500 Hz | 1 cm | PASS | FAIL |
| 4a | 4000 Hz | 1 cm | PASS | FAIL |
| 4b ma | 2500 Hz | 1 cm | PASS | FAIL |
| 4b ba | 2500 Hz | 1 cm | PASS | FAIL |
| 4b om | 2500 Hz | 1 cm | PASS | FAIL |
| 4c | 2500 Hz | 1 cm | PASS | FAIL |

**What this validation does and does not show:**

- Tier 1 is validated against exact theory only for single-post backscatter.
- At the 4000 Hz grid only 4 cm, 8 cm posts match the analytic cylinder at all angles (1 cm: forward 1.04 dB, 90° 1.77 dB off; 2 cm: forward 1.47 dB, 90° 0.43 dB off).
- At the 2500 Hz grid only 4 cm, 8 cm posts match the analytic cylinder at all angles (1 cm: forward 2.61 dB, 90° 0.51 dB off; 2 cm: forward 1.73 dB, 90° 1.65 dB off).
- At the 2000 Hz grid only 2 cm, 4 cm, 8 cm posts match the analytic cylinder at all angles (1 cm: forward 1.21 dB, 90° 2.82 dB off); 1 cm posts are not validated even in backscatter.
- The 1 cm backscatter match relies on an area factor fitted to backscatter (factor 0.908, `solver.area_cal`); held-out offsets confirm backscatter only.
- Shadowing and multiple scattering in dense fields are checked by self-convergence only (production grid vs twice as fine, 436 posts), not against an exact solution. A bias shared by both grids would not show, so the effect of the angular errors above on dense-field echoes is not bounded.

Caveats as recorded in the file (`caveats`):

- 1 cm and 2 cm posts: forward/side scattering off the analytic cylinder at the 4 kHz grid (1 cm forward 1.04 dB, 90-degree 1.77 dB; 2 cm forward 1.47 dB, 90-degree 0.43 dB) (backscatter within 1 dB; cause measured at the 4 kHz grid: dipole part ~10 % strong for sub-cell posts); effect on dense-field echoes is not bounded; shadowing and multiple scattering are checked by self-convergence only, not against an exact solution
- 1 cm and 2 cm posts: forward/side scattering off the analytic cylinder at the 2.5 kHz grid (1 cm forward 2.61 dB, 90-degree 0.51 dB; 2 cm forward 1.73 dB, 90-degree 1.65 dB) (backscatter within 1 dB; cause measured at the 4 kHz grid: dipole part ~10 % strong for sub-cell posts); effect on dense-field echoes is not bounded; shadowing and multiple scattering are checked by self-convergence only, not against an exact solution
- 1 cm posts at the 2.5 kHz grid (r/dx 0.73) pass backscatter at the 3 fixed offsets only: below the calibrated sub-cell range (area factor clamped), no held-out offsets checked there
- 1 cm posts fail backscatter at the 2 kHz grid: not validated there
- the 1 cm backscatter match depends on an area factor fitted to backscatter (area factor 0.908; held-out offsets confirm backscatter only)
