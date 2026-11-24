# Decisions

Every choice the spec left open and every deviation from it, one line each with the reason.
Format: `- [task N] <choice> — <reason>`. Append only (`cat >> DECISIONS.md`); never rewrite.

- [task 1] Package layout: `echo/` and `stages/` are regular packages at the repo root, built by hatchling and installed editable by uv; pytest also gets `pythonpath = ["."]` — so `uv run python -m stages.s1_bird` and `uv run pytest` both work from the root.
- [task 1] Torch installed from the default PyPI wheel (CUDA-enabled build) rather than a CPU-only index — simplest; works on CPU and lets Task 3 try the GTX 1650.
- [task 1] Wedge membership (`in_wedge`) uses polar angle and distance about the source; delay-related quantities use bistatic range rho — the wedge is a placement region, rho is the delay coordinate.
- [task 1] `Scene.r_max = None` means "outermost post edge (or r_min if no posts)"; scene.json always writes a number — viewer needs a numeric r_max.
- [task 1] `Scene.depth_m` = max - min post bistatic range — "total range depth" of the structure.
- [task 1] Clap = Gaussian noise x (0.25 ms raised-cosine attack, exponential decay, cosine tail), shaped zero-phase by a log-Gaussian spectrum around its peak (sigma 0.45-0.6 octave) times a 300-600 Hz high-pass, stored in an 8 ms buffer (128 samples), residual DC removed with a Hann-shaped correction, peak-normalized — meets 2-5 ms, 1-4 kHz, peak ~2.5 kHz, zero DC.
- [task 1] Clap family: 7 defined variants (durations 2-5 ms, peaks 2.0-3.0 kHz), `clap_family(n=5)` default uses the first 5; noise seeded per variant with `default_rng([seed, k])` — deterministic, and adding variants does not change earlier ones.
- [task 1] `band_limit` is an FFT mask with raised-cosine edges (width max(50 Hz, 25 % of edge)), zero-padded to avoid wrap — exactly zero phase, no filter-order choices, works on batched arrays.
- [task 1] Air absorption implemented from ISO 9613-1 eqs. (3)-(5) with the Annex B saturation-pressure formula; tested against ISO 9613-2 Table 2 values (20 C/70 % and 10 C/70 %), which are the published ISO 9613-1 numbers I could cite exactly.
- [task 1] Bird whistle glides exponentially (constant octaves per second) from 3.5 to 2.0 kHz — a pitch glide sounds linear in log frequency; pure tone with 5 ms raised-cosine fades.
- [task 1] Note targets: pure tones, 5 ms raised-cosine fade in and out on every note (10 ms dip between notes) — keeps repeated notes (E6 E6, G6 G6) separable at 45-100 ms note lengths. Motif uses the spec's rounded Hz; melody uses equal temperament A4 = 440 Hz.
- [task 5] Viewer: Scene and Wave share one canvas (field video registered under the plan view by `field.extent_m`, toggle "Field") — the spec's Wave panel is "the pressure field animated over the scene"; two copies of the scene would halve its size at 1440x900.
- [task 5] Viewer: wavesurfer.js drives only the footer timeline strip (peaks + `setTime` from the shared clock, its clicks call `clock.seek`); Echo and Groove are hand-written canvas — they must share a zoomable time window and draw the echo up to the cursor, which wavesurfer's own media/zoom model fights. Audio plays through Web Audio (`playbackRate` = speed) so picture time comes from `AudioContext.currentTime`.
- [task 5] Viewer: uPlot for History only; spectrograms are canvas images from `spectrograms.json` (one shared colour LUT).
- [task 5] Viewer: field.webm is fetched whole and played from a blob URL — `python -m http.server` ignores Range requests and Chrome cannot seek a video served without them.
- [task 5] Viewer: falls back to `viewer/fixtures/runs` when `../runs/index.json` is missing or empty, and says so in the header; the one 404 for `../runs/index.json` in the console is that probe.
- [task 1] Torch switched to the PyTorch CPU index (`[tool.uv.sources]`, torch 2.15.0+cpu) — the default PyPI CUDA build pulled ~3 GB of nvidia wheels at ~0.5 MB/s (over an hour); brief allows CPU torch. `torch.cuda.is_available()` is False. GPU for Tier 1 stays with Task 3 (k-wave's CUDA binary does not need CUDA torch).
- [task 1] uv selected CPython 3.11.15 for the venv (requires-python >= 3.11) — left as is; spec allows 3.11+.
- [task 1] Clap "spectral peak" is measured as the energy-weighted geometric-mean frequency (log centroid) — a 2-5 ms noise burst has only a handful of spectral degrees of freedom, so argmax of its spectrum is random; each variant keeps the best of 16 seeded noise draws (closest log centroid to its design peak, most energy in 1-4 kHz, least below 300 Hz), so family properties hold for any seed.
- [task 1] Clap duration is the -40 dB extent of the burst (envelope 0.25 ms attack, exp decay tau = dur/2.5, cosine tail) — it lands at 0.85-0.95 x the nominal 2-5 ms.
- [task 1] k-wave-python downloads its C++ binaries (OMP + CUDA, GitHub release v1.4.1) into `.venv/.../kwave/bin/linux/` on first `import kwave`; on this network that took many minutes, so the first import can appear to hang.
