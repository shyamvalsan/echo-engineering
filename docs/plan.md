# Composed Echo — implementation plan

**Spec:** `SPEC.md` (repo root). The spec is the binding authority. This plan adds the
architecture rulings and interfaces the spec leaves open. Every implementer reads `SPEC.md`
in full before starting, then its own task.

The repo root is this repository's top folder (the spec calls it `composed-echo/`). Developed on an 8-core Linux
machine. `espeak-ng` is not installed.

## Global Constraints

Binding on every task. Values are exact.

**Process**
- Nobody is awake. Never ask the human. Pick the simplest option and append one line to
  `DECISIONS.md` (`- [task N] <choice> — <reason>`). Append with `cat >> DECISIONS.md`, never rewrite the file.
- Commit your own paths only: `git add <paths> && git commit -m "..." -- <paths>`. Other agents
  may be committing in parallel in other directories; if `index.lock` exists, wait and retry. Never
  `git add -A`, never touch files outside your task's list without saying so in your report.
- Do not add dependencies outside Task 1 unless unavoidable; if you must, `uv add` and report it.
- Long computations: run in the background with output to a log file and poll; a foreground
  command dies at 10 minutes.
- Integrity (spec): pass thresholds are fixed and live in one place (`echo/metrics.py::THRESHOLDS`),
  copied verbatim from the spec's stage table. The pitch tracker, note segmenter, formant tracker,
  ESTOI and the speech recognizer are judges only and never appear in any optimization loss or
  search objective. Fixed seeds. Every reported number comes from a `metrics.json` written by code.
- Report failures plainly. A failed stage with a cause is a result. Never weaken a check.
- Time boxes are real. At 150% of the box, stop, record state, report.

**Conventions**
- SI units. `C0 = 343.0` m/s. Audio/sample rate for all signals and echoes `FS = 16000` Hz.
  Design band 500–4000 Hz.
- Coordinates: source `S = (0, 0)`. Listener `L = (0, 0.3)`. Wedge axis is +x, half-angle 20°,
  posts start at range 3 m. Radius catalog `(0.01, 0.02, 0.04, 0.08)` m. Min surface gap 0.05 m.
- **Bistatic range.** Source and listener are 0.3 m apart, so a circular arc is not an
  equal-delay curve (path varies by up to ±10 cm ≈ one period at 3.5 kHz). Everywhere the spec
  says "range" for delay purposes use `rho(P) = (|P−S| + |P−L|) / 2`; echo delay is `2·rho/C0`.
  Equal-delay "arcs" are confocal ellipses with foci S and L. Profiles are indexed by `rho`.
- **Time axis.** `t = 0` is clap emission. Direct sound reaches the listener at `|SL|/C0` (0.875 ms).
  A post at bistatic range `rho` echoes at `2·rho/C0`.
- **Clap definition and normalization.** A clap variant is a waveform `clap[k]` at `FS`, defined as
  the pressure the listener receives directly (the direct arrival, delay removed), peak-normalized
  to 1. Every forward model returns echoes in the same units: pressure relative to that direct clap.
  Formally `Echo_k(f) = C_k(f) · H_scat(f) / H_direct(f) · exp(−i2πf·|SL|/C0)`, where `H_scat` and
  `H_direct` are the source→listener transfer functions of the model (scattered part, and free-field
  direct). An echo peak of 0.01 therefore means −40 dB re the direct clap at the listener.
- **Linearity trick (Tier 1).** Never run the full-wave solver once per clap. Run it once per
  design with a broadband band-limited pulse, run the empty scene once per grid (cached), form
  `H = (P_scene − P_empty) / P_empty` in band (regularized), and derive every clap variant's echo
  by multiplication. Extra listener positions are extra sensors in the same run.
- **Spreading modes.** `mode="2d"` (line source, matches Tier 1; used for cross-checks, design
  search and the tier gap) and `mode="3d"` (point source + vertical posts; used only for loudness).
- **Levels.** `echo_level_db_re_direct` = 20·log10(peak echo / peak direct clap at listener), 3D mode,
  mean over the clap family, corrected by the tier gap: `L3d(Tier0) + (L2d(Tier1) − L2d(Tier0))`
  (report raw and corrected). `echo_spl_db` assumes 100 dB peak at 1 m, i.e. direct at the listener
  is 100 + 20·log10(1/0.3) = 110.46 dB. Below 35 dB is flagged "likely inaudible on site"
  (reported, never a pass condition).
- **Air absorption.** ISO 9613-1 at 20 °C, 50 % RH, 101.325 kPa, as a function `alpha_db_per_m(f)`
  in `echo/scene.py`. Tier 0 applies it per path. Tier 1 applies it after the solve as a
  time-varying filter on the impulse response (path length = `C0·t`).
- **Tier 1 grid.** Spacing per stage from the highest frequency kept (`f_max`): ≥4 points per
  wavelength pseudo-spectral, ≥10 finite-difference. The excitation and all Tier 0↔Tier 1
  comparisons are band-limited to `[f_lo, f_max]`. Budget 20 min wall-clock per run; if over,
  lower `f_max` or narrow the wedge and log it.

**Run-folder data contract** (the viewer depends on nothing else; all JSON is plain, no NaN/Infinity)

```
runs/<stage>/<run_id>/
  manifest.json scene.json profile.json target.wav echo_tier0.wav echo_tier1.wav
  as_heard.wav field.webm spectrograms.json metrics.json history.json
  iters/<name>/{scene.json,profile.json,echo.wav,metrics.json}   (optional saved iterations)
runs/index.json
```

- `manifest.json`: `{run_id, stage, title, created (ISO), seed, git_commit, status: "final"|"intermediate"|"tier0_only",
  verified: bool, fs, c, duration_s, t_direct_s, command,
  solver: {tier1: "kwave"|"fdtd"|"pstd"|"none", device, dx, dt, grid:[nx,ny], f_lo, f_max, ppw, wall_s},
  field: null | {file:"field.webm", fps, n_frames, t0_s, sim_seconds_per_frame, extent_m:[xmin,xmax,ymin,ymax], width, height},
  audio: {echo_gain_db: {tier0, tier1}, as_heard_echo_level_db},
  notes}`
- `scene.json`: `{units:"m", c, source:[x,y], listener:[x,y], wedge:{half_angle_deg, r_min, r_max}, posts:[[x,y,radius],...]}`
- `profile.json`: `{r0_m, dr_m, reflectivity:[...], units}` — index i ↔ `rho = r0_m + i·dr_m` ↔ echo time `2·rho/c`.
- WAVs: mono, `FS`. `target.wav`, `echo_tier0.wav`, `echo_tier1.wav` are peak-normalized to −1 dBFS (gain recorded
  in manifest). `as_heard.wav` is 32-bit float: direct clap then the Tier 1 echo (Tier 0 if no Tier 1) at the
  corrected 3D relative level, direct peak at −1 dBFS. All share `t = 0` = emission and the same length.
- `spectrograms.json`: `{fs, freqs_hz:[F], times_s:[T], db_floor:-60, panels:{target:[[..T]..F], tier0:[[...]], tier1:[[...]]|null}}`
  values in dB re each panel's own max, clipped to `[db_floor, 0]`, rounded to 0.5 dB. Linear-frequency STFT 0–5 kHz.
- `metrics.json`: `{stage, passed: bool, verified: bool, fragile: bool,
  headline:{echo_level_db_re_direct, echo_level_db_re_direct_raw3d, echo_spl_db, depth_m, post_count, fill_fraction, tier_gap_db},
  metrics:[{id, label, value, unit, threshold, comparator:"<="|">="|"=="|null, pass: bool|null, tier:"tier0"|"tier1", gating: bool}],
  per_clap:[{clap, metrics:{id:value}}],
  robustness:[{case, label, metrics:{id:value}, delta:{id:value}, pass: bool}],
  failure_cause: null|string}`
- `history.json`: `{phases:[{name, x_label, iters:[...], loss:[...], score:[...]|null, saved:[{iter, dir}]}]}`
- `runs/index.json`: `{runs:[{stage, run_id, path, title, created, status, passed, verified}]}` newest first; rewritten
  by `echo.export.update_index()` by scanning `runs/*/*/manifest.json`.

## Task 1: Scaffold, environment, clap family, targets for stages 1–3

Box 45 min. Files: `pyproject.toml`, `uv.lock`, `DECISIONS.md`, `README.md`, `echo/__init__.py`,
`echo/scene.py`, `echo/clap.py`, `echo/targets.py`, `tests/test_scene.py`, `tests/test_clap.py`,
`tests/test_targets.py`, empty package dirs `stages/`, `runs/`, `viewer/`.

- `uv` project, Python ≥3.11. Install every library in the spec's stack table now (numpy, scipy,
  torch, auraloss, k-wave-python, nevergrad or cmaes, librosa, soundfile, pystoi, faster-whisper,
  matplotlib, imageio-ffmpeg, pytest). CPU torch is fine; record in `DECISIONS.md` whether CUDA torch
  is usable (`torch.cuda.is_available()`), and do not spend more than 10 min on GPU setup — Task 3 owns that.
  Verify each import in a smoke test. If one library will not install in 10 min, log it and move on.
- `echo/scene.py`: constants (`C0`, `FS`, `SOURCE`, `LISTENER`, `RADII`, `MIN_GAP`, band), `Scene` dataclass
  (`source`, `listener`, `posts: np.ndarray[N,3]`, `half_angle_deg`, `r_min`, `r_max`, `c`), `bistatic_range(xy)`,
  `ellipse_point(rho, angle)` (point on the equal-delay ellipse at polar angle from +x), `in_wedge`,
  `check_gaps(posts)` (min surface gap), `fill_fraction(scene)`, `alpha_db_per_m(f, T=20, rh=50)` (ISO 9613-1),
  `to_json`/`from_json` matching the data contract.
- `echo/clap.py`: `clap_family(n=5, fs=FS, seed=0) -> np.ndarray[K, Nc]` — noise bursts 2–5 ms, energy mainly
  1–4 kHz, peak near 2.5 kHz, different durations and spectral peaks, peak-normalized, deterministic, negligible
  energy below 300 Hz and zero DC. Also `band_limit(x, f_lo, f_hi, fs)` (zero-phase).
- `echo/targets.py`: `Target` dataclass (`name`, `audio` at FS, `duration_s`, `notes: list[(f_hz, t_on, t_off)] | None`,
  `f_track: (t, f) | None`, `f_top_hz`). `bird_note()` (descending whistle 3.5→2.0 kHz, 80 ms),
  `motif()` (C6 E6 G6 C7 = 1047, 1319, 1568, 2093 Hz, 45 ms each, 180 ms), `melody(note_ms=100)` (E6 E6 F6 G6 G6 F6 E6 D6;
  also valid at 60), short raised-cosine fades between notes so repeated notes are separable.
- Write `artifacts/step1/*.wav` and spectrogram PNGs for every clap and target, and look at the PNGs yourself.
- Tests: wedge/ellipse geometry (delay of a point on `ellipse_point(rho, θ)` is `2·rho/C0` for several θ),
  absorption against two published ISO 9613-1 table values, clap band/duration/determinism, target pitch and length.

Done when: `uv run pytest` passes, audio and PNGs exist, committed.

## Task 2: Tier 0 single-scattering model

Box 45 min. Files: `echo/tier0.py`, `tests/test_tier0.py`.

- PyTorch, differentiable end to end, CPU, one evaluation well under a second for a few thousand posts.
- `cylinder_response(radius, f, angle, c)`: analytic far-field scattering amplitude of a rigid cylinder for an
  incident plane wave (Bessel/Hankel series, enough terms for ka up to ~6), `angle` = scattering angle
  (π = backscatter). Precompute per catalog radius on the rFFT grid; interpolating over the small bistatic
  angle is fine.
- `post_echo(posts, claps, scene, mode="2d"|"3d", n_out, band=None, absorption=True) -> Tensor[K, n_out]`:
  frequency-domain sum over posts with the normalization in Global Constraints. `2d`: line source and 2D scattered
  cylindrical wave (Hankel functions, exact or large-argument with the correct phase), divided by the 2D direct
  transfer function. `3d`: point source and vertical post. Derive and document the 3D amplitude in a docstring and
  in `DECISIONS.md`; test it against a limit you can compute by hand (e.g. geometric-optics reflection from a large
  convex cylinder).
- `profile_echo(profile, claps, scene, mode, n_out, a_ref=0.02, ...) -> Tensor[K, n_out]`: the fast 1D model used by
  the profile solve. `profile[i] ≥ 0` is "equivalent number of reference posts of radius `a_ref`" in bistatic-range
  bin `r0 + i·0.01 m`, on the wedge axis. Must agree with `post_echo` of the equivalent posts placed on the axis.
- No shadowing, no multiple scattering (the known error of this tier).
- Tests: single-post delay equals `2·rho/C0` within one sample; single-post level equals a hand calculation
  (written out in the test) within 0.5 dB in both modes; `profile_echo` ↔ `post_echo` consistency; gradient flows
  to post positions and to the profile; timing of one evaluation.

Done when: tests pass, committed.

## Task 3: Tier 1 full-wave solver and the four validation checks

Box 90 min (hard stop 135). Files: `echo/tier1.py`, `echo/field_video.py`, `tests/test_tier1.py`,
`stages/validate.py`, `runs/validation/` outputs, `runs/_samples/`.

- Try `k-wave-python` first. If it is not producing a correct 2D run within 45 min of your start, switch to your
  own 2D solver in PyTorch (a k-space pseudo-spectral or FDTD scheme with PML) and log the switch. Use the GPU if
  `torch.cuda` or a k-Wave GPU backend works without a fight (it has ~2 GB free); otherwise CPU. Benchmark a
  stage-1-sized run (domain ≈ 17.5 m × 12.5 m, `f_max` 4 kHz, 110 ms) and record wall-clock in `DECISIONS.md`.
- Rigid posts rasterized onto the grid. The catalog's 1 and 2 cm radii are at or below one cell at 4 points per
  wavelength: use anti-aliased (area-fraction) rasterization or another sub-cell treatment, and **measure** the
  backscatter error per catalog radius against the analytic cylinder. Report the table. A radius that cannot meet
  1 dB at the stage grid is reported as such (later tasks may drop it from the catalog and log that).
- API:
  `run_tier1(scene, f_max, t_end, listeners=None, c=C0, f_lo=300.0, record_field=False, field_dt=None, ppw=None, wedge_margin=..., cache=True) -> Tier1Result`
  with `Tier1Result{fs, ir: np.ndarray[n_listeners, n] (scattered impulse response in the Global-Constraints
  normalization, band-limited, at FS, t=0 = emission), listeners, dx, dt, grid, f_lo, f_max, ppw, wall_s, solver,
  device, field: None | {frames: np.ndarray[T,H,W] float16 (downsampled), t0, dt_frame, extent}}` and
  `echoes(result, claps, listener=0, absorption=True) -> np.ndarray[K, n]`.
  The empty-scene reference is cached on disk under `.cache/` keyed by grid and medium.
- `echo/field_video.py`: `render_field_video(frames, extent, path, fps=30, max_width=1280)` → VP9 WebM, diverging
  palette centred on zero (dark at zero so it sits on a dark viewer), symmetric colour limits with gentle
  time-gain so late weak echoes stay visible, keyframe every ≤10 frames so the viewer can scrub. Returns the
  `field` block for `manifest.json`.
- `stages/validate.py` runs the four spec checks and writes `runs/validation/metrics.json` (values, thresholds, pass):
  1. Single rigid cylinder backscatter vs analytic within 1 dB across the design band (per catalog radius).
  2. Grid convergence: halving the spacing changes the echo of a reference design by < 1 dB.
  3. Empty scene: after the direct clap, nothing above −60 dB.
  4. Tier 0 (`mode="2d"`, same band) vs Tier 1 on a sparse design: echoes agree within 2 dB.
  Check 4 needs `echo/tier0.py` from Task 2, built in parallel; if it is not there yet, do 1–3 first.
- Write one sample field video of the sparse design to `runs/_samples/field.webm` with `runs/_samples/field.json`
  (its manifest `field` block) and `runs/_samples/scene.json`, for the viewer task.
- `tests/test_tier1.py`: fast versions (small domain) of checks 1 and 3; mark slow ones `@pytest.mark.slow`.

Done when: all four checks pass in `runs/validation/metrics.json`, or the failing ones are recorded with numbers
and a cause. If validation cannot pass at all, say so loudly in your report — the whole project then switches to
"unverified" mode per the spec.

## Task 4: Design pipeline on Tier 0 — profile solve, realization, metrics, export

Box 75 min. Files: `echo/inverse.py`, `echo/realize.py`, `echo/metrics.py`, `echo/export.py`,
`stages/common.py`, `stages/s1_bird.py`, tests for each, first run folder `runs/s1_bird/<run_id>/` (status `tier0_only`).

- `inverse.solve_profile(target, claps, scene_cfg, ...) -> (profile, history)`: Adam on a softplus-parameterized
  profile on the 1 cm bistatic-range grid; loss = auraloss multi-resolution STFT + log-mel term, computed inside the
  clap band only, averaged over the clap family, `mode="2d"`. The model compensates spreading by itself. No raw
  waveform error. Initialize from the physics (positive bias + target laid out along range, `rho = C0·t/2`).
- `realize.realize(profile, scene_cfg, seed) -> posts[N,3]`: discrete posts from the catalog approximating the
  profile bin by bin (error-diffusion or similar), spread along each equal-delay ellipse inside the wedge, min gap
  respected, angular positions randomized so no post sits directly behind another as seen from the source.
  Prefer many small posts over few large ones (spec). Returns posts plus realized-vs-requested profile error.
- `metrics.py`: `THRESHOLDS` (verbatim from the spec table), pitch track (`librosa.pyin`), note segmentation and
  sequence comparison in cents, log-mel spectrogram correlation, echo level and SPL, tier gap, a `score_stage(...)`
  that returns the `metrics.json` structure. Stage 4 metrics (formants, ESTOI, whisper) are added later in
  `echo/metrics_speech.py` — leave a clean seam.
- `export.py`: `write_run(...)` producing the full run folder per the data contract (Tier 1 pieces optional/null),
  `update_index()`, `spectrograms(...)`, WAV writers with the normalization rules, manifest with git commit and the
  reproducing command.
- `stages/common.py`: the shared stage driver (target → solve → realize → Tier 0 post echo → score → export), with a
  hook where Task 6 adds the Tier 1 correction loop. `uv run python -m stages.s1_bird --tier0-only` writes a run.
- Tests: profile solve recovers a known sinusoidal profile's pitch; realization respects gap/wedge/no-shadow and its
  post echo matches the profile echo within a stated tolerance on a dilute profile; metrics on synthetic signals
  with known answers (pitch off by 5 % must fail, 1 % must pass; a wrong note order must fail); JSON round-trips
  with no NaN.

Done when: the stage-1 Tier 0 run folder exists, Tier 0 metrics computed (they do not count as a pass), committed.

## Task 5: Viewer

Box 75 min for the first complete version. Files: everything under `viewer/` only.

Read the spec's "Visualization layer" section twice — it is the requirement, panel by panel and behaviour by
behaviour. Static files, plain JS modules, no framework, no build step, served from the repo root with
`uv run python -m http.server 8000` and opened at `/viewer/`. Vendor `wavesurfer.js` and `uPlot` (or Plotly) into
`viewer/vendor/` so it works offline. Reads `../runs/index.json` and the run folders per the data contract in
Global Constraints, and must tolerate `field: null`, `tier1: null`, missing `iters`, and failed/unverified runs
(show an "UNVERIFIED — Tier 0 only" mark).

- Panels: Scene (to scale, range rings labelled in metres and ms, posts sized by radius), Wave (the `field.webm`
  drawn under the scene overlay, synced), Groove (profile directly under the target waveform on a shared
  range/time axis), Echo (drawing itself in step with the timeline), Spectrograms (target / Tier 0 / Tier 1, same
  axes and colour scale, cursor), Scorecard (metric, value, threshold, pass/fail; echo level and depth large;
  robustness below), History (loss vs iteration; click a saved iteration to load its scene/profile/echo).
- One timeline drives everything. Speeds: real time, 10× and 50× slower. Audio follows the slow-down (pitch drops)
  or is muted — user's choice. Audio buttons: target, echo alone, as heard. Stage/run switcher. Compare mode (two
  runs side by side). Hovering a post shows range, delay and radius and marks that delay on the echo and groove.
- Look: dark, one accent colour for the wave, diverging pressure palette centred on zero, restrained type; an
  instrument, not a dashboard. Main panels fit a 1440×900 laptop without scrolling. If the `frontend-design` skill
  is available to you, load it first.
- A real run folder appears at `runs/s1_bird/` when Task 4 finishes (in parallel with you), and a sample field
  video at `runs/_samples/` when Task 3 finishes. Until then build against a fixture you generate into
  `viewer/fixtures/` that follows the contract exactly. Before reporting, drive the viewer in a real browser
  (Playwright is available), fix console errors, and save screenshots to `artifacts/viewer/`.

Done when: every panel renders a run folder, the behaviours above work, screenshots saved, committed.

## Task 6: Stage 1 bird note — full loop on Tier 1, robustness, gate

Box 60 min (gate: up to 3 h total before the project stops adding stages). Files: `echo/inverse.py` (correction
loop), `echo/robustness.py`, `echo/export.py` (field video + iterations), `stages/common.py`, `stages/s1_bird.py`, tests.

- Correction loop (spec, Inverse design step 3): run Tier 1, compare echo to target in short time windows, scale the
  profile up where weak and down where strong, re-realize, rerun; stop after 5 rounds or when the score stops
  improving. Each round is saved under `iters/` and in `history.json`. Gradient-free fallback (one gain per 10 ms
  window, nevergrad/cmaes) only if it stalls, and never with a judge metric as objective.
- Final design: Tier 0 and Tier 1 both run, tier gap reported, field video rendered, full `metrics.json`.
- `robustness.py`: listener +1 m sideways and +1 m back (extra sensors), c = 331 and 349 m/s, posts jittered 5 mm and
  radii 1 mm, each clap variant on its own. Report metric deltas; set `fragile`.
- Pass condition (Tier 1, mean over clap family): pitch track within 3 % of target along the note; spectrogram
  correlation ≥ 0.8.

Done when: `uv run python -m stages.s1_bird` reproduces a final run folder end to end and stage 1 passes on Tier 1 —
or the box is spent and the cause analysis is written.

## Task 7: Stage 2 motif

Box 60 min. Files: `stages/s2_motif.py` (+ shared modules only if needed, without breaking stage 1).
Target C6 E6 G6 C7, 45 ms each, 180 ms, 30.9 m. Pass: all four notes detected in order, each within 30 cents
(Tier 1, mean over clap family). Full loop, robustness, final run folder. Re-run the stage-1 tests before committing.

## Task 8: Stage 3 melody at 100 ms and 60 ms notes

Box 90 min. Files: `stages/s3_melody.py`. Ode to Joy opening, 8 notes, 100 ms each, 800 ms, 137 m. Pass: transcribed
sequence matches exactly, each note within 50 cents. The domain is huge: narrow the wedge and set `f_max` from the
target per the spec, log both. Also run the 60 ms-note variant and report whether transcription still passes
(separate run folder `runs/s3_melody/<id>_60ms`). If time allows, bracket the shortest note length that still
transcribes using Tier 0, and state clearly that it is Tier 0.

## Task 9: Speech targets and speech metrics

Box 45 min. Files: `echo/targets_speech.py`, `echo/metrics_speech.py`, tests, `artifacts/speech/`.
Starts only after stage 1 has passed. `espeak-ng` targets ("ah" sustained 150 ms, "ma", "ba", "om" 200–250 ms,
"hello" 400 ms), band-limited to the design band. Get espeak-ng from a user-space package; if none works, log
it and use another synthesis route. Metrics: formants by linear
prediction (F1, F2), ESTOI via `pystoi`, closed-set nearest-target test, `faster-whisper` small model run locally
(download it now). Tests on the clean targets: the judges must pass the targets themselves — if whisper does not
return "hello" for the clean band-limited target, that is a finding to report, not something to tune.

## Task 10: Stage 4 — vowel, syllables, word

Box 120 min. Files: `stages/s4_speech.py`. 4a "ah": F1 and F2 within 10 %. 4b "ma"/"ba"/"om": closed-set test (echo
closest to its own target among the three) and ESTOI ≥ 0.5. 4c "hello": recognizer returns "hello" for ≥ 3 of 5 clap
variants. This is the stretch stage: a clear negative result with the cause identified counts. For every failure,
run the ablations that separate the three candidate limits and write the numbers to `metrics.json`: (a) clap
spectrum (ideal flat-spectrum clap), (b) positivity constraint (signed reflectivity allowed in Tier 0),
(c) small-post scattering (frequency-flat scatterers in Tier 0).

## Task 11: Report, screenshots, reproduction, cleanup

Box 30 min. Files: `REPORT.md`, `README.md`, `artifacts/report/`. One-paragraph verdict; one scorecard per stage
(pass/fail, echo level, depth, post count, tier gap); solver validation table; answers to the four open questions,
each citing a `metrics.json` path and key; ranked next steps; a viewer screenshot per stage; one reproduce command
per stage and one to serve the viewer. Re-run `uv run python explainer/build.py` so the explainer carries the real results and audio, link the explainer, viewer and `BUILD.md` from `README.md` and the top of `REPORT.md`, and summarize the build path in the report. Full test suite passing. Every number generated from the metrics files by a
script (`stages/report.py`), not typed by hand. If Tier 1 validation failed, "UNVERIFIED" is the first word of the report.

## Task 12: Interactive lay-person explainer

Added by the owner mid-run: "we also need lay person explanation of the project, an interactive write up".
Box 90 min. Files: everything under `explainer/` only (plus `artifacts/explainer/` screenshots).

A single scrolling page that a curious non-specialist can read in ten minutes and come away understanding what this
project is, why it should work, what the simulation found, and what stands between it and a real structure. It is
an explanation first and a demo second: plain words, short paragraphs, no jargon without a one-line gloss, every
idea paired with something to see, hear or drag.

- Output: `explainer/index.html`, fully self-contained (inline CSS and JS, no framework, no build tooling beyond the
  Python script below; any audio or data embedded as base64/JSON). It must open by double-click from disk and from
  `http.server`, work at phone width (16 px side gutter, no horizontal scroll), define colours as tokens on `:root`
  with both light and dark themes (`@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`,
  plus `:root[data-theme="dark"]`), set an explicit `body` background, have a 2–4 word `<title>`, and load external
  scripts from nowhere (inline everything) so it can also be published as a hosted page later.
- `explainer/build.py` assembles `index.html` from `explainer/src/` (template, css, js) plus a results block read
  from the real run folders (`runs/index.json`, each final run's `metrics.json`, `manifest.json`, `scene.json`,
  `profile.json`, and its short WAVs embedded as base64). When no real runs exist yet it builds with the results
  sections showing "simulation still running" and everything else working. Task 11 re-runs it at the end.
- Interactive pieces (all computed in the browser with a small single-scattering model in plain JS + Web Audio, so
  the reader hears what they build):
  1. "An echo is a recording played back by geometry": clap at a wall, drag the wall, hear and see the delay
     (17.15 cm of range per millisecond of echo).
  2. "Many posts, many echoes": add a row of posts, hear clicks merge into a pitch as spacing shrinks; spacing ↔ pitch
     readout (spacing = c / 2f).
  3. "The layout is the waveform": draw or pick a sound (falling whistle, four-note motif) and watch it turn into a
     density of posts along range; play the clap and the echo. Show the positivity problem honestly: posts cannot
     reflect negatively, so the design is bias + signal, and show what the bias costs.
  4. "Why the clap matters": swap an ideal click for a real clap burst and hear the difference.
  5. "How big is it?": a slider from 80 ms to 800 ms of sound showing structure depth against familiar lengths
     (a bus, a tennis court, a football pitch), and how loud the echo is expected to be.
  6. Results: one card per stage with target / echo / as-heard audio buttons, pass or fail in plain words, depth,
     post count, echo loudness in everyday terms, and a small plan-view drawing of the real design from `scene.json`.
  7. "What a simulation cannot tell us" and "How it could be built" — a short honest summary that links to
     `BUILD.md` and the full viewer (`../viewer/`).
- Tone: confident, concrete, never hype. State plainly what is simulated and what is not. No emoji.
- Verify in a real browser (Playwright): desktop 1440×900 and phone 390×844, both themes, no console errors, every
  interactive piece exercised, audio graph starts on user gesture. Screenshots to `artifacts/explainer/`. Look at
  them critically and iterate on the design and the wording at least twice.

Done when: the page builds, reads well, every interactive piece works, screenshots saved, committed.

## Task 13: Real-world build path

Added by the owner mid-run: "importantly we need a clear path to actually create the structure in the real world".
The spec's non-goal is a physical build tonight; this task delivers the plan and the fabrication data, not hardware.
Box 120 min. Starts after stages 1 and 2 have final runs. Files: `BUILD.md`, `echo/buildkit.py`, `stages/build_pilot.py`,
`tests/test_buildkit.py`, `build/` outputs, `runs/build_*/` run folders.

- `BUILD.md`: a staged path a small team could follow, each phase with goal, what is built, bill of materials with
  cost range, tools, what is measured, the pass/fail number that unlocks the next phase, and what to do on failure:
  1. Desk phase (done tonight): what simulation established and what it left open, with numbers from `metrics.json`.
  2. 1:10 ultrasonic scale model on a tabletop (5–40 kHz, structure about 1.4–3 m, pins/rods on a CNC-drilled or
     laser-cut board): the cheapest test of the whole idea including 3D effects. Give the concrete rig: emitter,
     microphone, sampling rate, how to record the impulse response and slow it down 10× to listen.
  3. Full-scale pilot of the smallest worthwhile design outdoors: site requirements (background noise, ground, wind,
     clearance), post material and height (from the Fresnel-zone/finite-height argument), foundations, survey and
     stake-out method that meets the tolerance the robustness sweep demands, build sequence, acceptance measurement.
  4. Permanent installation: durability, safety, access, permissions, maintenance, and the longer pieces.
  Include a tolerance budget (from the robustness sweeps), a loudness budget (from the echo-level metric, with the
  35 dB audibility line), a risk register ranked by what would kill the project, and a rough schedule and budget.
  Label every cost and material figure as an estimate with its basis; do not invent supplier quotes.
- `echo/buildkit.py`: turn a final design into fabrication data — stake-out table (CSV: id, x, y, radius, distance and
  bearing from the clap point, bistatic range, echo delay), a to-scale printable plan (SVG and PDF) with the clap
  point, listener, baseline and post rows, a DXF or SVG drilling template for the 1:10 model, and a bill of materials
  (count and total length per stock diameter for a stated post height). Tests on geometry round-trip and scaling.
- `stages/build_pilot.py`: design a **build-optimized pilot** with the existing pipeline under practical constraints
  (stock pipe diameters nearest the catalog, a cap on post count, a minimum spacing a person can walk and mow between
  if feasible, maximum loudness) for the bird note, and if time allows the motif. Score it with the same Tier 1
  referee and thresholds as its stage, add a physics check the stages do not have — the finite-height / ground
  correction estimate for the chosen post height — and write its run folder and its build pack to `build/<design>/`.
- Every number in `BUILD.md` that comes from simulation cites its `metrics.json` path and key.

Done when: `BUILD.md` is complete and specific, the build pack exists for at least the pilot design, tests pass, committed.
