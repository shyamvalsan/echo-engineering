*Appendix of [REPORT.md](../../REPORT.md); generated 2026-11-25T17:53+02:00 by `uv run python -m stages.report`.*

# Deviations from the spec

**Stage gate.** The spec's gate says stage 1 must pass on Tier 1 before stage 2 starts. Stage 1 has not passed and later stages were run anyway (a gate deviation, ruled by the controller): owner asked for all four targets and "try again"; foundation (solver, pipeline) is validated and the stage-1 failure has identified causes; stage 2 is less mm-sensitive with a note-based judge.

**Full-wave runs over the spec's 20-minute budget:** `20261125-131152-s3` (29.78 min; `manifest.solver.wall_s` / `tier1_wall_s`); `20261125-124137-s4_4c_hello` (21.64 min; `manifest.solver.wall_s` / `tier1_wall_s`).

**Robustness cases not run:**

- `20261125-142346-s4_4a_ah`: c_331 (not run (cost)), c_349 (not run (cost)), jitter (not run (cost))
- `20261125-135718-s4_4b_om`: c_331 (not run (cost)), c_349 (not run (cost)), jitter (not run (cost))
- `20261125-134325-s4_4b_ba`: c_331 (not run (cost)), c_349 (not run (cost)), jitter (not run (cost))
- `20261125-133244-s3_60ms`: c_331 (not run (cost)), c_349 (not run (cost)), jitter (not run (time/cost: the 100 ms run alone took ~30 min on the 2.5 kHz grid with the Tier 1 lock shared by three stages; free cases only))
- `20261125-132102-s4_4b_ma`: c_331 (not run (cost)), c_349 (not run (cost)), jitter (not run (cost))
- `20261125-131152-s3`: c_331 (not run (cost)), c_349 (not run (cost)), jitter (not run (time/cost: the 100 ms run alone took ~30 min on the 2.5 kHz grid with the Tier 1 lock shared by three stages; free cases only))
- `20261125-124137-s4_4c_hello`: c_331 (not run (cost)), c_349 (not run (cost)), jitter (not run (cost))

Departures from the spec's letter and per-stage domain choices, short form of the matching `DECISIONS.md` lines (first clause; superseded lines dropped):

**Solver (Tier 1)**

- Tier 1 engine is our own 2D staggered-grid FDTD (8th-order stencils in free air, leapfrog, numba-compiled, float32, 8 CPU cores, split-field PML of 24 cells), logged as solver "fdtd". It is not k-Wave.
- Tier 1 air absorption uses the extra path c t - |SL|, the same as Tier 0 (global constraints say c t; the difference is 0.3 m of path, negligible).
- Grid is now 10 points per wavelength at f_max (spec minimum for finite differences).
- Validation finding (fd8-3, ppw 10): check 1 FAILS for 1 cm and 2 cm at non-backscatter angles.
- Validation verdict follows the spec's check 1 (backscatter); forward/90° results reported as an extended check with a caveat; separate monopole/dipole calibration left as future work
- CORRECTION to the line above about the 1 cm area factor: it is validated for backscatter only (held-out offsets ≤ 0.35 dB); forward and 90° scattering FAIL the 1 dB extended check (1.04 / 1.77 dB); the factor is fitted to backscatter and masks a …
- Third validation grid for stage 2: f_max 2.5 kHz, ppw 10 (dx 13.6 mm), engine fd8-3, key checks.cylinder.stage2_grid.

**Single-scattering model (Tier 0)**

- Tier 0 form function: one master partial-wave table on a ka grid (step 0.004, grown on demand) replaces per-radius tables cached by lru_cache; radii sit on a 0.5 mm grid with linear blending between neighbouring grid radii (catalog radii exact)

**Design pipeline, judges and stage 1**

- Range polish uses the non-aliased FFT length (choose_n_fft over the largest delay) with an exact, post-chunked gradient; skipped (and logged) above 20,000 posts or 2.5e7 posts x in-band bins.
- fragile = (exactly one clap variant passes on its own) or (exactly one of {nominal, 1 m sideways, 1 m back} passes)
- Stage 1 realization switched to `phase_locked` (K = 1 comb: one ring of 1 cm posts per carrier period at the band-passed profile's analytic phase 2*pi*j, ring amplitude = envelope x period; fractional amplitudes made exact by detuning one symmetric pair …
- Profile band-pass for the phase-locked realization removes the slow bias with a Gaussian low-pass (sigma = 0.8 of the longest carrier period) before zero padding
- Rings weaker than 0.5 post (fades, very sparse designs) get 0/1 post by error diffusion instead of an exact detuned pair (EXACT_MIN)
- Stage 1 Tier 1 density sweep now (0.35 %, 0.66 %, 1 % fill = 1060 / 2000 / 3030 posts, phase-locked) with correction_rounds = 2

**Stage 2**

- Stage 2 Tier 1 grid f_max 2.5 kHz (ppw 10, dx 13.7 mm; validated for backscatter at all radii) and the stage band capped at 2.5 kHz (`StageConfig.band_max_hz`, clap band 898-2500 Hz for solve, echoes and all comparisons)
- Stage 2 wedge half-angle 10 deg
- Stage 2 profile solve 1200 Adam steps at lr 0.05 (Tier 0 profile-echo window loss 2.039 vs 2.100 at 300/0.02); Tier 0 equalization (`tier0_equalize_rounds`, added) left off: it lowers the loss of the 300-step solve (2.100 -> 2.052) but raises it for the …
- Stage 2 realization: 2 cm posts, phase_locked K = 1
- Stage 2 Tier 1 runs: density sweep (0.8 %, 1.6 % fill) picked by Tier 1 loss, correction_rounds = 1 (no correction round: time box on a shared CPU), field rerun, 3 robustness reruns; NUMBA_NUM_THREADS=4.
- Correction to the line above: the Tier 1 density sweep ran once (0.8 % -> Tier 1 loss 5.637, 1.6 % -> 5.568; runs/s2_motif/_studies/tier1_density_sweep.log); round 0 at 1.6 % showed extinction (window gains 0.5 early -> 2.0 late), so that run was stopped …
- Stage 2 default is now v2 (1 cm posts, 20 deg, fill 0.1 %, phase-locked K = 1, extinction pre-compensation exp(+tau1) via profile_transform, correction clip (0.25, 4), one correction round, c cases not run for cost); v1 (2 cm, 10 deg) stays reachable with …

**Stage 3**

- Shared infra: machine-wide Tier 1 lock (`stages.common.tier1_lock`, fcntl.flock on .cache/tier1.lock) around every driver Tier 1 solve, 8 numba threads (capped by NUMBA_NUM_THREADS) while held
- Shared infra (additive, defaults unchanged): `StageConfig.robustness_c_cases` / `robustness_jitter` (echo.robustness.sweep c_cases / jitter) so stage 3 can skip the two speed-of-sound cases for cost and record them as "not run (cost)"; …
- Stage 3 Tier 1 grid f_max 2 kHz (top note G6 1568 Hz; validated stage-3 grid, 2 cm validated at all angles); band capped at 2 kHz (band_max_hz)
- Stage 3 wedge +-1 deg
- Stage 3 profile solve 40 Adam steps at lr 0.005
- Stage 3 fill 1.6 % at +-1 deg, phase_locked K=1, 2 cm, tier0_equalize_rounds=3
- Stage 3 Tier 1 budget: 100 ms = 1 design run (field recorded in it) + jitter rerun; 60 ms = 1 design run, free robustness cases only; speed-of-sound cases not run (cost), expected pitch shift from c alone recorded (331 m/s: -61.6 cents, alone breaks the …
- Stage 3 redesign after the coordinator's extinction guidance: 1 cm posts on the 2.5 kHz grid (validated for backscatter; forward scattering 2.6 dB off -> referee extinction uncertain, in caveats), +-1 m strip inside the +-20 deg wedge (`max_half_width_m`), …
- Tier 1 lock taken only for the real solver (`echo.tier1.run_tier1`); injected fake solvers (driver tests) no longer block on a stage's running solve.

**Stage 4 and speech judges**

- Stage 4 Tier 1 wedges: widest half-angle (0.5 deg steps) with a planned run <= 12 min on an idle machine (tier1.plan cell-steps x 260 s / 55e9): ah 11.5 deg, ma 3.5, ba 3.0, om 2.5 at 4 kHz; hello at 2.5 kHz, 3.0 deg (no half-angle >= 1 deg fits at 4 kHz: …
- Stage 4 realization: sampling (inverse CDF + polish), 1 cm posts, ~1000 posts per 100 ms of target
- Stage 4 robustness: driver sweep off; the free cases (listener 1 m sideways / back as extra sensors, each clap alone) are computed from the design run; c = 331/349 m/s and jitter recorded "not run (cost)" (7-solve budget).
- Stage 4 ablations: Tier 0 profile model E = C x W x profile_transfer, same Adam (500 steps, lr 0.05) and loss (EchoLoss 500-4000 Hz) for all 8 combinations; per combination the lower final loss of two inits (physics, Wiener) is kept for "ah"; …
- Stage 4 driver solve steps: 1200 for 4a, 800 for 4b/4c (time box on a shared CPU).
- Stage 4b/4c after the coordinator's extinction evidence: +-20 deg wedge clipped to a strip (`max_half_width_m`; sampling mode support added additively in echo/realize.py), 2.5 kHz grid, ma/ba/om +-7 m, hello +-5 m; realized post counts 1,655 / 1,751 / …
- Stage 4 driver profile solve 300 Adam steps for every final run (S4_STEPS=300; time box on a shared CPU at 2-6 s/step): best loss 2.55-2.64 vs 2.42 at 1200 steps on "ah".

**Clap, targets, environment**

- Torch switched to the PyTorch CPU index (`[tool.uv.sources]`, torch 2.15.0+cpu)
- Shortest clap variant raised from 2.0 to 2.3 ms nominal so every variant's -40 dB extent is within the spec's 2-5 ms (measured 2.1-4.8 ms over seeds 0-3); 0.3 ms raised-cosine onset ramp added so clips start at 0 (cropped pre-ringing had left a step of …

Other choices logged in [`DECISIONS.md`](../../DECISIONS.md) — solver (tier 1): 6; single-scattering model (tier 0): 8; design pipeline, judges and stage 1: 18; stage 3: 1; stage 4 and speech judges: 11; clap, targets, environment: 17; viewer: 5; build path: 16.
