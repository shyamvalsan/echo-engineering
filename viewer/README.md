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
| `run` | stage 1's newest final run | Run path as listed in `index.json`, e.g. `s1_bird/20261125-002316-s1`. Without it the first stage's (stage 1, the representative result) newest `status: "final"` run is opened. Switching stage picks that stage's newest final run that passed, else its newest final run. |
| `mode` | `review` | `live` opens Live mode. |
| `liverate` | none | Live mode only: build the AudioContext at this rate (e.g. `16000`) instead of the device rate. Default resamples the 16 kHz impulse response instead, which Firefox needs (it refuses a microphone in a context at another rate). |
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

## Live mode

The Live tab plays the selected structure's echo of your own sound, live from the microphone, and lets you replay
every sound you made with the waves. Same stage/run switcher as Review; switching run keeps the microphone on.

- **Start listening** (a user gesture creates and resumes the AudioContext, then asks for the microphone with
  echo cancellation, noise suppression and auto gain off). Path: mic -> AudioWorklet tap (meter, clap detector,
  takes; `js/live/worklet.js`) and mic -> `ConvolverNode` (`normalize = false`, the run's impulse response) ->
  echo gain -> soft clipper (exactly linear below -3 dBFS; a DynamicsCompressorNode was rejected because it delays
  by 6 ms and adds make-up gain) -> speakers. The real clap is heard in the room; the speaker adds only the echo.
- **Echo level**: 0 dB = true level (the IR as is); default boost = the clap's echo 12 dB under the clap (the
  `listen/` convention), i.e. `-(true level) - 12` dB, capped at +60. The boost is always shown in dB next to
  the slider, with the true level and "usually inaudible on speakers" beside the true-level mark.
- **Timing**: the mic hears the clap `t_direct` after emission and the system adds input + output latency
  (`baseLatency + outputLatency + track.getSettings().latency` where reported). That much is trimmed from the
  IR's leading silence (never more than the silence: geometric first-post delay, bounded by the IR's own onset)
  and the panel says "compensated" or "partly compensated, echo about N ms late". With typical laptop output
  latency (20-40 ms) and a first post at ~19 ms, the echo comes late by the excess; the panel says so.
- **Feedback guard**: without headphones, if the output stays above -30 dBFS rms for 0.7 s after the echo should
  have ended (IR length + 0.5 s since the last clap) and is not falling, the echo is turned down 18 dB with a
  notice; moving the slider restores it. **Headphones** mixes the dry mic in at an adjustable level.
- **Takes**: every detected clap (0.6 s from 20 ms of pre-roll, silent tail trimmed) and Record 2 s become takes,
  as do sound files (dropped or chosen; anything the browser decodes, first 4 s, mixed to mono, decoded at 16 kHz)
  and built-ins (`inputs/sources/*` via `/api/inputs` when the lab server runs, else this run's clap from
  `as_heard.wav`; plus a click and a 0.5-4 kHz chirp when the server offers none). Takes live in memory only, at
  most 12 (oldest dropped), one cached echo each. Download: take, echo (true level), take + echo (boosted), 32-bit
  float WAV at 16 kHz.
- **Replay**: selecting a take makes it the timeline source: Echo panel (the take at t = 0, its echo = take ⊛ IR
  computed in an OfflineAudioContext), spectrograms (target and the take's echo, computed in JS on one grid), the
  scene with the field video ("wave from an ideal short pulse": the video is the solver's own pulse) or the
  geometric front, and a band behind the front as long as your sound (c x duration, 34 cm per ms). Listen:
  Take + echo (take at the direct arrival plus the boosted echo, scaled down together if it would clip), Echo, Take.
- **Design from a sound** (lab server only): file + name + "also verify on full-wave" -> `POST /api/design`,
  progress from `/api/jobs/<id>`, then `runs/index.json` is re-read and the new run opens in Live. Custom runs are
  listed with "fast model only, not verified" unless verified; Hide removes one from the list (browser storage),
  never from disk. Without the server the panel shows `uv run python -m echo.lab` and the CLI alternative
  `uv run python -m stages.custom --target <file> --name "<label>"`.

Contracts used (Live):

- `manifest.ir = {tier0, tier1|null, fs, band_hz, t0_s, units, source, peak}` and `ir_tier0.wav` / `ir_tier1.wav`
  (mono float, sample 0 = emission, `source ⊛ ir` = echo at true level re the direct sound). An IR at another rate
  is resampled and scaled by `fs_in / fs_out` (taps are a density per sample; the same scaling is applied when the
  16 kHz IR is resampled to the device rate).
- Level: IRs are stored at the 2D model level (`manifest.ir.model_level`); the viewer multiplies by
  `manifest.ir.gain_to_true_level[tier]` and shows "stored at the 2D model level; shown at the true 3D level using the
  run's stated factor". True level shown = `ir.level_db.true_3d`. Only for IR files without that factor does it fall
  back to rescaling the IR so the run's clap echo has `audio.as_heard_echo_level_db` (when off by more than 3 dB).
- When `manifest.ir.source[tier]` says "deconvolved", the Response box adds "reconstructed from the stored echo;
  trustworthy only inside the clap's band (band_hz)" and points to Tier 0.
- Runs without `manifest.ir` (written before that contract): the IR is derived in the browser by a regularized,
  band-limited deconvolution of `echo_tier{0,1}.wav` by the clap (`as_heard.wav` from `t_direct` to the first echo or
  12 ms), scaled so the clap's echo has `audio.as_heard_echo_level_db`. On the stage-1 run this reconstructs the
  stored echo to -39 dB error and the level to 0.0 dB. The UI says "derived in the browser" for such runs.
- Lab server: `GET /api/health`, `GET /api/inputs`, `POST /api/design`, `GET /api/jobs/<id>` (see the brief in
  `echo/lab.py`). Detected once at load; on a static server the only console line is the 404 of `/api/health`.
- `metrics.json` verdict keys, shown side by side in the scorecard when present: `criteria.spec_v1` ("Original spec
  thresholds"), `criteria.owner_v2` ("Revised thresholds (listening-calibrated)", `passed: null` reads "no automated
  criterion"), `listening_verdict` ("Owner's ear, 25 Nov").

Testing Live mode (Chrome via Playwright, headless): `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream
--use-file-for-fake-audio-capture=<48 kHz wav with silence and claps>`. A second AudioWorklet recorded mic and
output together; the output matched an offline replica (mic ⊛ the convolver's buffer x boost) with lag 0 ms,
correlation 1.000 and 0.00 dB level difference, at 44.1 kHz and with `?liverate=16000`.

Limitations: latency can only be compensated within the IR's leading silence (about 19 ms minus t_direct for a
3 m start); Bluetooth outputs add 100-200 ms and the echo then comes late (the panel says by how much). Speakers
and an open mic can feed back at high boosts; the guard ducks, headphones avoid it. Boosted levels are not what a
real structure would return: the true level is shown beside the slider. Firefox was not tested here (no Firefox
in this environment); the code avoids Chrome-only APIs.

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
    js/live/view.js           Live mode layout, takes, sources, design panel
    js/live/engine.js         microphone -> convolver -> speakers, meters, latency trim, feedback guard
    js/live/worklet.js        AudioWorklet: input level, clap detection, take capture with pre-roll
    js/live/irs.js            impulse responses: run files, or derived in the browser
    js/live/dsp.js            FFT, deconvolution, resampling, offline convolution, STFT, WAV writer
    js/live/lab.js            optional lab server client
    vendor/                   wavesurfer.js 7.8.16, uPlot 1.6.31, IBM Plex Sans Condensed
