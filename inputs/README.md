# Your own sounds

Two folders, both read by the lab server (`uv run python -m echo.lab`, then <http://127.0.0.1:8000/viewer/>):

- `targets/`: sounds you want the post field to echo back. Each one becomes a design.
- `sources/`: sounds to excite a finished design with, i.e. things to "clap" with. The Lab page convolves a source
  with a run's impulse response (`ir_tier0.wav` / `ir_tier1.wav`) to play its echo.

`GET /api/inputs` lists both folders as `{"targets": [{"name", "url"}], "sources": [{"name", "url"}]}`. The URLs are
plain static files under `/inputs/...`.

## Designing for a target

Command line (same result as an upload on the Lab page):

    uv run python -m stages.custom --target inputs/targets/rising_two_note.wav --name "rising two-note"
    uv run python -m stages.custom --target inputs/targets/my.wav --name "my sound" --tier1 --max-duration 1.0

Or upload the file on the Lab page (`POST /api/design`, which needs the header `X-Echo-Lab: 1`; the viewer sends it).
From the shell:

    curl -H "X-Echo-Lab: 1" -F target=@inputs/targets/rising_two_note.wav -F name="rising two-note" \
         http://127.0.0.1:8000/api/design

Either way you get a normal run folder, `runs/custom/<run_id>/`, and the viewer lists it under the "custom" stage.
Uploaded files are kept in `runs/custom/_uploads/` (named by job id; the server never serves or lists that folder)
until you delete them by hand.

What happens to the file: it is mixed to mono, resampled to 16 kHz, stripped of leading and trailing silence, cut to
`--max-duration` seconds (default 1.0, at most 2.0, with a 10 ms fade-out), band-limited to the design band
500-4000 Hz and normalized. A sound with one dominant pitch at a time (whistle, pure notes, glide) gets the
phase-locked ring layout. Anything else (speech, noise, rich harmonics) gets the sampling layout. The choice and the
numbers behind it are stored in `manifest.json` under `custom.classification`.

Formats and lengths that work:

- Formats: wav, flac and ogg (anything libsndfile reads), and mp3. Any sample rate, mono or stereo, at most 20 MB;
  only the first 30 s of a longer file are read.
- Length: at least 30 ms of sound after silence is trimmed. A useful range is 50-500 ms. The field gets deeper by
  about 17 cm for every millisecond of sound (340 m/s, there and back), so a 1 s target needs a field about 170 m
  deep.
- Content: some energy has to fall in 500-4000 Hz. Anything outside that band is removed.
- Refused, with a message saying why: files that are not audio, silent files, files shorter than 30 ms after
  trimming, and files with nothing in the band.

These are fast-model (Tier 0) designs. They are marked "UNVERIFIED - Tier 0 only" (`status: tier0_only`) unless a
`--tier1` run completes (then `status: final`, `verified: true`), and there
is no pass or fail for an arbitrary sound. `metrics.json` reports information only: echo level, field depth, post
count, ground coverage, and how closely the echo's spectrogram and envelope match the target.

`--tier1` (or `tier1=1` in the upload) also runs ONE full-wave simulation of the design, then updates the same
folder to `status: final` with a field video. It is refused, with the estimate, if the solve is estimated at more
than 20 minutes. In practice that means targets of roughly 150 ms or less: the 120 ms example is about 3 minutes on
the 2.5 kHz grid, while a 300 ms target would take about 1.8 hours on the 4 kHz grid.

## Examples in this folder

Generated from the project's own code:

- `targets/rising_two_note.wav`: E6 then A6, 60 ms each (`echo.targets.note_sequence`). Its full-wave run is in
  `runs/custom/`.
- `sources/clap_0.wav`, `sources/clap_1.wav`: two variants of the project's clap family (`echo.clap.clap_family`).
- `sources/click.wav`: a 500-4000 Hz band-limited click. Its echo is the impulse response itself.
- `sources/chirp.wav`: a 50 ms exponential chirp from 500 Hz to 4000 Hz.
