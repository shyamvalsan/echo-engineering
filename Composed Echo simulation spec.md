# Composed Echo: simulation spec

Nov 24, 2026 · @Shyam Sreevalsan

## Summary

Build a simulator and inverse designer for a passive structure that returns a hand clap as a chosen sound. All four targets run end to end in simulation: a bird note, a multi-note motif, a recognizable melody, then spoken syllables, in that order. A browser viewer shows the scene, the wave, the audio and the scores for every run.

This spec is written for an autonomous agent working unattended for one night. It is self-contained. Where it leaves a choice open, the agent picks the simplest option and logs it in `DECISIONS.md`.

**What simulation covers.** Wave propagation, scattering, multiple reflections, the inverse design, clap variability, tolerance to build errors, and an estimate of echo loudness. Audio files come out of every run, so the result can be judged by ear.

**What simulation does not cover.** Wind, temperature gradients, site background noise, real ground and finite reflector height (approximated only), and human perception. Pitch trackers and speech recognizers stand in for a listener. The final judge is a person listening to the exported audio.

**The one idea to hold on to.** An echo is the impulse response of the structure. Reflector layout along range is the waveform. Sound travels out and back, so 1 ms of echo is 17.15 cm of range.

## Physics and scene

The scene is a 2D plan view: a clapper, a listener, and a fan of rigid vertical posts in open air.

**Geometry**

- Source at the origin. Listener 0.3 m from the source, at the same range.
- Reflectors are rigid cylinders (posts) placed inside a wedge of plus or minus 20 degrees, starting 3 m from the source.
- Echo delay depends only on range, so posts at the same range can sit anywhere on the arc. Use the arc to avoid posts shadowing each other and to add loudness.
- Post radii come from a catalog of 1, 2, 4 and 8 cm. Minimum gap between post surfaces is 5 cm.
- Open boundaries on all sides (absorbing layers in the full-wave solver).

**Constants**

| Quantity | Value |
| --- | --- |
| Speed of sound | 343 m/s (20 C) |
| Range per ms of echo | 17.15 cm |
| Design band | 500 Hz to 4 kHz |
| Wavelength across the band | 69 cm to 8.6 cm |
| Air absorption | Apply as a frequency-dependent filter, ISO 9613-1, 20 C, 50% humidity |

**The clap**

A clap is not an impulse. Model it as a short noise burst: 2 to 5 ms long, energy mainly between 1 and 4 kHz, peak near 2.5 kHz. Build a family of at least 5 clap variants with different durations and spectral peaks. Every design is optimized and scored against the whole family, never a single clap.

**The constraint that shapes everything**

Rigid posts reflect with one sign. Reflectivity along range cannot go negative. So the design represents the target as a positive bias plus the signal. The bias varies slowly, and the clap has almost no energy at very low frequencies, so the bias mostly drops out of the echo. This costs about half the available reflectivity and is the reason a smooth density of small posts beats a few large ones: a sinusoidal density gives a clean tone, while evenly spaced single posts add harmonics.

**Size of the structure**

| Echo duration | Range depth needed |
| --- | --- |
| 80 ms | 13.7 m |
| 180 ms | 30.9 m |
| 400 ms | 68.6 m |
| 800 ms | 137 m |

Length is free in simulation. Record it for every design, because it decides what could ever be built.

## Forward models

Two models, used together. The fast one drives the design search. The full-wave one is the only source of reported results.

**Tier 0: single-scattering model (fast, differentiable)**

- Each post returns a delayed, scaled, filtered copy of the clap. Delay is the path from source to post to listener divided by the speed of sound.
- Per-post frequency response comes from the analytic solution for scattering by a rigid cylinder.
- Spreading loss has two modes: 2D (matches Tier 1, used for cross-checks) and 3D point scatterer (used for loudness estimates).
- No shadowing and no multiple scattering. That is the known error of this tier.
- Written in PyTorch so gradients flow from the echo back to the design. One evaluation should take well under a second.

**Tier 1: full-wave 2D solver (the referee)**

- Use `k-wave-python`. If it cannot be installed or run in the first 45 minutes, fall back to a plain 2D finite-difference time-domain solver in NumPy or PyTorch and log the switch.
- Posts are rigid inclusions rasterized onto the grid. Absorbing layers on every edge.
- Grid spacing is set per stage from the highest frequency in the target: at least 4 points per wavelength for a pseudo-spectral solver, at least 10 for finite differences.
- Record pressure at the listener for the echo, and a downsampled pressure field over time for the viewer.
- Budget: 20 minutes of wall-clock per run. If a run would exceed it, lower the top frequency or narrow the wedge, and log the change.

**Rules**

- A design passes a stage only on Tier 1 results.
- Tier 0 and Tier 1 must both be run on every final design, and their disagreement reported.
- 3D effects are out of scope for the solver. The 3D spreading mode in Tier 0 is the only 3D correction.

## Inverse design

The design runs in three steps: solve for a reflectivity profile, turn it into posts, then correct against the full-wave solver.

1. **Solve the profile.** The unknown is reflectivity along range on a 1 cm grid, constrained to be zero or positive. Minimize the difference between the Tier 0 echo and the target, averaged over the clap family. Compensate for spreading so far reflectors are stronger.
2. **Realize as posts.** Convert the profile into discrete posts from the radius catalog. Spread posts along each arc inside the wedge, respect the minimum gap, and randomize arc positions so no post sits directly behind another.
3. **Correct against Tier 1.** Run the full-wave solver. Compare its echo with the target in short time windows. Scale the profile up where the echo is weak and down where it is strong. Realize again and rerun. Stop after 5 rounds or when the score stops improving.

**Loss**

- Multi-resolution spectrogram loss (the `auraloss` library provides it) plus a log-mel spectrogram term.
- Compare only inside the clap band. The echo cannot contain energy the clap does not have.
- Do not use raw waveform error. Phase does not matter to the ear here and it makes the problem much harder.

**Optimizer**

- Adam on the profile, with the positivity constraint enforced by a softplus parameterization.
- If step 3 stalls, a gradient-free search with `nevergrad` or `cmaes` over a low-dimensional correction (one gain per 10 ms window) is allowed.

**Outputs of a design**

A list of posts (x, y, radius), the profile, total range depth, post count, and the fraction of wedge area filled.

## The four stages

Stages run in this order. Each one reuses the machinery of the one before and raises the difficulty of the target.

| Stage | Target | Echo length | Range depth | Passes when (Tier 1, mean over the clap family) |
| --- | --- | --- | --- | --- |
| 1. Bird note | Synthesized descending whistle, 3.5 kHz to 2.0 kHz | 80 ms | 13.7 m | Pitch track within 3% of target along the note. Spectrogram correlation at least 0.8. |
| 2. Motif | Four notes: C6, E6, G6, C7 (1047, 1319, 1568, 2093 Hz), 45 ms each | 180 ms | 30.9 m | All four notes detected in order. Each within 30 cents. |
| 3. Melody | Opening 8 notes of Ode to Joy: E6 E6 F6 G6 G6 F6 E6 D6, 100 ms each | 800 ms | 137 m | Transcribed note sequence matches exactly. Each note within 50 cents. |
| 4a. Vowel | A sustained "ah" | 150 ms | 25.7 m | First two formants within 10% of target. |
| 4b. Syllables | "ma", "ba", "om" | 200 to 250 ms | 34 to 43 m | Closed-set test: the echo is closest to its own target among all three. ESTOI at least 0.5. |
| 4c. Word | "hello" | 400 ms | 68.6 m | Speech recognizer returns "hello" for at least 3 of 5 clap variants. |

**Notes on the targets**

- Stages 1 to 3 use synthesized tones with short fades between notes. No external recordings are needed.
- Stage 3 notes are 100 ms because a tune stops being recognizable when notes run much faster. That is what makes the structure 137 m deep. The simulation should confirm or correct this by also trying 60 ms notes and reporting whether the transcription still passes.
- Stage 4 targets come from `espeak-ng`, an offline open-source speech synthesizer. Band-limit them to the design band before use.
- Stage 4 is the stretch. Low speech frequencies reflect weakly from small posts and the clap carries little energy there. A clear negative result with the cause identified counts as a completed stage.

**Gate**

Stage 1 must pass on Tier 1 before any work starts on stage 2. If it has not passed after 3 hours, stop adding stages and spend the rest of the night finding out why. Stages 2 to 4 are time-boxed. A stage that fails its box is recorded as failed, with the best result so far, and the agent moves on.

## Scoring and verification

Every number in the final report must trace to a `metrics.json` written by code. Nothing is estimated by hand.

**Solver validation (before any design work)**

- Single rigid cylinder: Tier 1 backscatter matches the analytic solution within 1 dB across the design band.
- Grid convergence: halving the grid spacing changes the echo of a reference design by less than 1 dB.
- Empty scene: with no posts, the listener records the direct clap and nothing after it above -60 dB.
- Tier 0 against Tier 1 on a sparse design (posts far apart): echoes agree within 2 dB. This confirms both models share the same geometry and timing.

**Metrics per run**

| Metric | How | Used for |
| --- | --- | --- |
| Pitch track | `librosa.pyin` | Stages 1 to 3 |
| Note sequence | Segment the pitch track into notes, compare with target | Stages 2 and 3 |
| Spectrogram correlation | Log-mel, target against echo | All stages |
| Formants | Linear prediction on the echo | Stage 4a |
| ESTOI | `pystoi` | Stage 4b and 4c |
| Recognized text | `faster-whisper`, small model, run locally | Stage 4c |
| Echo level | Echo peak relative to the direct clap at the listener, in dB, 3D spreading mode | All stages |
| Tier gap | Level difference between Tier 0 and Tier 1 echoes | All stages |

**Echo level is the feasibility number.** Report it for every design, and convert it to an estimated sound level assuming a clap of 100 dB peak at 1 m. An echo below about 35 dB would be lost at most real sites. This is reported, not a pass condition.

**Robustness sweep (final design of each stage)**

- Listener moved 1 m sideways and 1 m back.
- Speed of sound at 331 and 349 m/s (0 C and 30 C).
- Post positions jittered by 5 mm, radii by 1 mm.
- Each clap variant on its own.

Report how far each metric moves. A design that only works for one clap or one listener position is marked fragile.

**Integrity rules**

- Pass thresholds in this spec are fixed. Do not change them to make a stage pass.
- The speech recognizer and pitch tracker are judges only. Never include them in the optimization loss.
- Fixed random seeds. Every run can be reproduced from its manifest.

## Visualization layer

A single-page viewer that makes the experiment legible in one look: where things are, what the wave does, what comes back, and whether it passed. It reads run folders from disk and needs no backend.

**Layout**

| Panel | Shows |
| --- | --- |
| Scene | Plan view of source, listener and posts, drawn to scale. Range rings labelled in both metres and milliseconds of echo. Posts sized by radius. |
| Wave | The Tier 1 pressure field animated over the scene. The clap wavefront travels out, and each post lights up as it scatters. |
| Groove | The reflectivity profile along range, drawn directly under the target waveform on a shared axis. This is the picture of the core idea: the layout is the waveform. |
| Echo | The listener's waveform, drawing itself in step with the wave animation. |
| Spectrograms | Target, Tier 0 echo and Tier 1 echo side by side, same frequency axis and colour scale. |
| Scorecard | Each metric with its value, threshold and pass or fail. Echo level and structure depth shown large. Robustness results below. |
| History | Loss against iteration for the design run, with the ability to load any saved iteration. |

**Behaviour**

- One timeline controls everything. Scrubbing it moves the wave, the echo cursor and the spectrogram cursor together.
- Playback speeds: real time, and slowed 10 and 50 times so the wavefront can be followed by eye. Audio pitch follows the slow-down or is muted, user's choice.
- Audio buttons: target, echo alone, and "as heard" (the direct clap followed by the echo at their true relative levels).
- Stage and run switcher at the top. A compare mode puts two runs next to each other.
- Hovering a post shows its range, its echo delay and its radius, and marks that delay on the echo and groove panels.

**Look**

Dark background, one accent colour for the wave, a diverging palette for pressure centred on zero, restrained type. It should read as an instrument, not a dashboard. Works at laptop width without scrolling the main panels.

**Build**

- Static files only: plain JavaScript modules, no framework. Served with `python -m http.server`.
- Existing libraries: `wavesurfer.js` for audio and waveform, `Plotly` or `uPlot` for spectrograms and curves, the canvas API for the scene.
- The pressure field is pre-rendered by Python to a WebM or MP4 per run and synced to the timeline. Do not ship raw field arrays to the browser.
- Build the viewer against Tier 0 output first, so it exists and is useful before the first full-wave run finishes.

**Data contract**

Each run writes one folder. The viewer depends on nothing else.

```
runs/<stage>/<run_id>/
  manifest.json     stage, seed, solver, grid, timings, git commit
  scene.json        source, listener, posts (x, y, radius), wedge, units
  profile.json      reflectivity against range
  target.wav
  echo_tier0.wav
  echo_tier1.wav
  as_heard.wav
  field.webm        pressure animation, with its time scale in the manifest
  spectrograms.json
  metrics.json      values, thresholds, pass or fail, robustness
  history.json      loss per iteration
runs/index.json     list of all runs, newest first
```

## Stack and repo layout

Python for everything numerical, static JavaScript for the viewer, and existing libraries wherever one exists.

| Need | Library |
| --- | --- |
| Environment | `uv`, Python 3.11 or newer |
| Arrays, signal processing | `numpy`, `scipy` |
| Differentiable model and optimizer | `torch` (CPU is enough for Tier 0) |
| Spectrogram loss | `auraloss` |
| Full-wave solver | `k-wave-python` |
| Gradient-free search | `nevergrad` or `cmaes` |
| Pitch and audio analysis | `librosa`, `soundfile` |
| Intelligibility | `pystoi` |
| Speech recognition | `faster-whisper` |
| Speech targets | `espeak-ng` |
| Field video | `matplotlib`, `imageio-ffmpeg` |
| Tests | `pytest` |
| Viewer | `wavesurfer.js`, `Plotly` or `uPlot` |

Assume a CPU-only machine unless a GPU is detected. If a GPU is present, use it for Tier 1 and note it in the manifest.

```
composed-echo/
  SPEC.md              this document, exported
  DECISIONS.md         every choice and deviation, with the reason
  REPORT.md            morning report
  pyproject.toml
  echo/
    scene.py           geometry, wedge, post catalog
    clap.py            clap family
    targets.py         whistle, notes, melody, speech targets
    tier0.py           single-scattering model
    tier1.py           full-wave wrapper and fallback solver
    inverse.py         profile solve and Tier 1 correction loop
    realize.py         profile to posts
    metrics.py         all scoring
    robustness.py      sweeps
    export.py          run folder writer, field video
  stages/
    s1_bird.py  s2_motif.py  s3_melody.py  s4_speech.py
  tests/
  runs/
  viewer/
```

One command per stage, for example `uv run python -m stages.s1_bird`. One command to serve the viewer.

## Overnight run plan

Nine steps in order, with a time box on each. The boxes add up to about 10 hours.

| Step | Work | Box | Done when |
| --- | --- | --- | --- |
| 1 | Scaffold repo, environment, clap family, targets for stages 1 to 3 | 45 min | Target and clap audio files exist and sound right in a spectrogram |
| 2 | Tier 0 model with tests | 45 min | Single-post delay and level match hand calculation |
| 3 | Tier 1 solver and the four validation checks | 90 min | All validation checks pass |
| 4 | Viewer, driven by Tier 0 output | 75 min | All panels render a run folder |
| 5 | Stage 1 bird note, full loop, robustness sweep | 60 min | Passes on Tier 1 |
| 6 | Stage 2 motif | 60 min | Passes or recorded as failed |
| 7 | Stage 3 melody, at 100 ms and 60 ms notes | 90 min | Passes or recorded as failed |
| 8 | Stage 4 vowel, syllables, word | 120 min | Each sub-stage passes or is recorded as failed with a cause |
| 9 | Report, screenshots of the viewer for each stage, cleanup | 30 min | `REPORT.md` complete |

**Rules for the agent**

- Commit after every step. A working earlier stage must never be broken by a later one.
- If a step overruns its box by half, stop it, record the state, and move on. The exception is the stage 1 gate described above.
- Log every choice this spec left open, and every deviation from it, in `DECISIONS.md` with one line of reasoning.
- Report failures plainly. A failed stage with a clear cause is a useful result. A passing score reached by weakening a check is not.
- Do not ask questions. Nobody is awake. Pick the simplest option and log it.
- Keep every final run folder. Delete intermediate field videos if disk runs short, never audio or metrics.
- If the full-wave solver cannot be made to pass validation at all, do not proceed on Tier 0 alone and call it done. Finish the viewer and Tier 0 stages, mark every result as unverified, and say so at the top of the report.

## Risks, non-goals, open questions

**Risks, most likely first**

- **Multiple scattering.** Dense post fields scatter sound between posts, which Tier 0 ignores. Expect the Tier 0 and Tier 1 gap to grow with density. The correction loop exists for this.
- **Weak low frequencies.** Posts much smaller than a wavelength reflect little, and the clap is weak below 1 kHz. Speech will sound thin. This is the main threat to stage 4.
- **Quiet echo.** Spreading loss over tens of metres may leave the echo too quiet to matter in practice, even when the shape is right. The echo level metric answers this.
- **Length.** A recognizable melody may need over 100 m. That is fine in simulation and decisive for a real build.
- **Judges that mislead.** A speech recognizer can guess a word from little evidence, or fail on clean but unusual audio. Treat its output as a hint and listen to the files.
- **2D against 3D.** The full-wave solver is 2D. Levels in a real 3D scene fall off faster. Timing and pitch carry over, loudness needs the 3D estimate.

**Non-goals for tonight**

- Any physical build, including the 1:10 ultrasonic scale model.
- 3D full-wave simulation, ground reflection and finite post height.
- Wind, temperature gradients and site noise.
- Resonant or absorbing reflectors, which could give negative reflectivity and shorter structures. Note ideas in the report, do not build them.
- Folded sound paths that would shorten the structure.

**Open questions the run should answer**

- How loud is the echo for each stage, in the 3D estimate?
- How short can notes get before the melody stops transcribing?
- Which is the limit on speech: the clap spectrum, the positivity constraint, or small-post scattering?
- How much do build tolerances of 5 mm matter?

## Morning deliverables

By morning the repo holds a report, audio for every stage, and a viewer that opens with one command.

- `REPORT.md`: a one-paragraph verdict, then one scorecard per stage with pass or fail, echo level, structure depth, post count and the Tier 0 to Tier 1 gap.
- Audio for every stage: target, echo, and "as heard". These are the real result.
- The viewer, with at least one final run per stage, and a screenshot of each in the report.
- Answers to the four open questions, each backed by a number from a metrics file.
- `DECISIONS.md` with every choice and deviation.
- A short list of what to try next, ranked, based on what limited each stage.
- All tests passing, and one command to reproduce each stage from scratch.
