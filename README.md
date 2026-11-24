# Composed Echo

Simulator and inverse designer for a passive structure of posts that returns a hand clap as a chosen sound.
`SPEC.md` is the authority; `DECISIONS.md` logs every choice and deviation.

```
uv sync                                  # environment (Python >= 3.11, CPU torch)
uv run pytest -q                         # tests
uv run python -m stages.s1_bird          # one command per stage (s1_bird, s2_motif, s3_melody, s4_speech)
```

Layout: `echo/` (scene, clap, targets, models, design, metrics, export), `stages/` (stage drivers),
`tests/`, `runs/` (run folders read by the viewer), `viewer/` (static page), `artifacts/` (plots and audio).
