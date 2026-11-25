# Composed Echo viewer

A static, single-page instrument for one run folder (or two side by side). No backend, no build step.

## Serve

From the repo root:

    uv run python -m http.server 8000      # or: python3 -m http.server 8000

then open <http://localhost:8000/viewer/>. Everything it needs is in `viewer/` (libraries and the font are
vendored in `viewer/vendor/`), so it works offline.

## URL parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| `runs` | `../runs` | Folder holding `index.json` and the run folders, relative to `viewer/`. `?runs=fixtures/runs` opens the fixture set. If `../runs/index.json` is missing or lists no runs, the viewer falls back to `fixtures/runs` and says so in the header. |
| `run` | newest final run | Run path as listed in `index.json`, e.g. `s1_bird/20261125-002316-s1`. Without it the newest `status: "final"` run is opened, else the newest run; switching stage picks that stage's newest final run the same way. |
| `compare` | none | A second run path; opens compare mode. |
| `speed` | `0.1` | `1`, `0.1` or `0.02` (real time, 10x and 50x slower). |
| `t` | `0` | Initial timeline position in simulation seconds. |

The URL is kept up to date as runs are picked, so a view can be shared by copying it.

After the viewer code changes, reload with Ctrl+Shift+R: `http.server` sends no cache headers, so a browser
may keep serving the old JavaScript modules.

## Controls

- Header: stage and run switchers (known stages get names such as "1 Bird note" and "4 Speech"; `build_*`
  stages appear as "Build pilot: ..."; anything else is shown with underscores as spaces), Compare, the run's
  reproduce command (`manifest.command`) with a Copy button, and links to `../explainer/` and `../BUILD.md`.
- Next to the Listen buttons: the true level of the echo in "As heard" (`manifest.audio.as_heard_echo_level_db`),
  because at a true -44 dB the echo is very quiet by design.
- Unverified runs (Tier 0 only) carry the "UNVERIFIED — Tier 0 only" mark and a note; their metrics read
  "meets"/"misses" in neutral colours, never "pass". Tier 0 rows of verified runs read the same way.

- One timeline (simulation seconds, 0 = clap emission) drives the wave video, the echo cursor, the groove
  cursor and the spectrogram cursors. Scrub with the waveform strip in the footer, or click/drag in the groove,
  echo or spectrogram panels. Space plays/pauses, arrow keys step one field frame (shift: ten), 1/2/3 pick the speed.
- Sound: "Pitch follows" plays audio at the timeline speed through Web Audio `playbackRate` (slowing down lowers
  the pitch); "Muted" silences it. Picture time is derived from `AudioContext.currentTime`, the same clock as
  the audio; when no audio device is running the wall clock is used instead.
- Listen: Target, Echo (the tier shown in the Echo panel, or a loaded iteration's echo), As heard.
- Scene: wheel zooms about the cursor, drag pans, Fit or double-click resets. Posts keep a 0.9 px minimum size
  when zoomed out and are true to scale when zoomed in. Hovering a post shows its range, echo delay and radius
  and marks that delay in the Groove and Echo panels.
- Field controls: Gain cycles x1/x2/x4/x8, stretching the drawn frame about its zero colour (taken from the
  frame corners) so faint scattering shows beside the direct front; Follow keeps the outgoing front centred while
  zoomed in, which is how a 140 m strip is best watched. Outside the video's time span the nearest frame is
  shown dimmed with a note.
- Long strips: when posts are confined by `manifest.design.config.max_half_width_m`, the wedge is cut to that
  strip and rings are labelled on its edge; "Fit height" fills the panel with the strip and turns on Follow.
- Playback: while playing, the field video plays natively with `playbackRate` matched to the timeline when the
  rate is within 0.0625..16 and needs at most about 120 decoded frames per second, re-seeking only when it drifts by
  more than a frame; otherwise, and when paused or scrubbing, exact frames are seeked.
- Run switcher: runs read "HH:MM, verdict, design tag: title" and are grouped by sub-stage (4a/4b/4c, from
  `manifest.substage` or the run_id). Default run: newest final run that passed, else newest final, else newest.
- Scorecard extras when present: `recognized_text` (per-clap transcripts), `closed_set_3x3.distances`,
  `failure_mechanism`, `diagnosis`, `robust_summary`, `robustness_not_run` (shown as "not run (cost)" rows, not
  failures), and a link to the run's metrics.json for `design_study`. Null metric values read "not found".
- Groove and Echo share one time window: wheel zooms it, double-click resets.
- History: phase tabs; click a saved iteration chip (or its marker on the curve) to load its scene, profile,
  echo and metrics; "Final" goes back.
- Compare: second run beside the first, compact panels, one shared timeline; "From" picks whose audio plays.

## What it reads (the run-folder contract)

The viewer reads exactly these fields and tolerates everything optional being absent.

`runs/index.json`: `runs[]` with `stage`, `run_id`, `path` (relative to the runs folder), `title`, `created`,
`status`, `passed`, `verified`. Order is kept (newest first); runs are grouped by `stage` for the switcher.

`manifest.json`: `title`, `command`, `audio.as_heard_echo_level_db`, `status` (`"tier0_only"` forces the UNVERIFIED mark), `verified`, `c`, `duration_s`
(timeline length), `t_direct_s` (direct-arrival tick in the Echo panel), `solver.tier1` (`"none"` means no
`echo_tier1.wav` is requested), and `field`:
`{file, fps, n_frames, t0_s, sim_seconds_per_frame, extent_m: [xmin, xmax, ymin, ymax]}` or `null`.
Frame for sim time t: `frame = floor((t - t0_s) / sim_seconds_per_frame)` clamped to `[0, n_frames-1]`, shown
by seeking the video to `(frame + 0.5) / fps`. The frame is drawn onto the scene with its top-left pixel at
`(xmin, ymax)` and bottom-right at `(xmax, ymin)` in metres, i.e. image rows run from +y (top) to -y.
Use frequent keyframes (e.g. `-g 1` or a small GOP) so seeking is frame-accurate and fast.

`scene.json`: `source [x,y]`, `listener [x,y]`, `wedge {half_angle_deg, r_min, r_max}`, `posts [[x, y, radius], ...]`
(metres), `c` (fallback). Range rings are equal-delay curves: confocal ellipses with foci at source and
listener, `rho = (|P-S| + |P-L|) / 2`, labelled in metres and in ms of echo (`2 rho / c`).

`profile.json`: `r0_m`, `dr_m`, `reflectivity[]`; bin i sits at `rho = r0_m + i dr_m`, drawn at echo time `2 rho / c`.

WAVs: `target.wav`, `echo_tier0.wav`, `echo_tier1.wav`, `as_heard.wav`, mono, PCM 8/16/24/32-bit or float 32/64,
any rate, all sharing t = 0 = emission. Parsed in JavaScript (no decodeAudioData resampling).

`spectrograms.json`: `freqs_hz`, `times_s`, `db_floor`, `panels.{target, tier0, tier1|null}` as `[F][T]` in dB.

`metrics.json`: `passed`, `verified`, `fragile`, `failure_cause`, `headline.{echo_level_db_re_direct,
echo_level_db_re_direct_raw3d, echo_spl_db, depth_m, post_count, fill_fraction, tier_gap_db, likely_inaudible_on_site?}`,
`metrics[] {id, label, value, unit, threshold, comparator, pass, tier, gating}`,
`robustness[] {case, label, delta, pass}`. `per_clap` is not shown yet.

`history.json`: `phases[] {name, x_label, iters[], loss[], score[]|null, saved[] {iter, dir}}`; `dir` may be
`iters/<name>` or `<name>`. A saved iteration folder holds `scene.json`, `profile.json`, `echo.wav`, `metrics.json`.

The field video is fetched whole and played from a blob URL, because `python -m http.server` does not answer
HTTP Range requests and Chrome cannot seek a video served without them.

## Fixtures

`fixtures/make_fixtures.mjs` writes four contract-following runs into `fixtures/runs/` (needs node and ffmpeg,
about 4 minutes, most of it the synthetic field video):

- `s1_bird/...-fx-final`: passed on Tier 1, field video, saved iterations, robustness sweep.
- `s1_bird/...-fx-tier0`: Tier 0 only, no field, no Tier 1.
- `s2_motif/...-fx-failed`: Tier 1, failed with a cause, fragile.
- `s3_melody/...-fx-tier0`: 137 m deep, 20,000 posts, for performance.
- `sample_field/real-tier1-sample`: written by `fixtures/wrap_sample.mjs`, which wraps the real full-wave sample in
  `runs/_samples/` (field video, its manifest block and scene) as a minimal run folder.

The physics is simplified (posts realized without the minimum-gap rule, field rings from a 160-post sample)
and every fixture says so in its manifest notes. They exist to exercise the viewer, not as results.

## Files

    index.html, style.css     page and tokens
    js/main.js                switcher, compare, transport, keyboard
    js/clock.js               the single clock and Web Audio playback
    js/data.js                index/run/iteration loading, WAV parser
    js/runview.js             lays out one run's panels
    js/scene.js               Scene + Wave (canvas, video underlay, rings, hover, zoom)
    js/timepanels.js          Groove and Echo (shared time window)
    js/spectro.js             spectrograms
    js/scorecard.js           scorecard
    js/history.js             history (uPlot)
    vendor/                   wavesurfer.js 7.8.16, uPlot 1.6.31, IBM Plex Sans Condensed
