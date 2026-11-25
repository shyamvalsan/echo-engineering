# Composed Echo

A simulator and inverse designer for a passive field of rigid posts that returns a hand clap as a chosen sound
(a bird note, a motif, a melody, speech). `SPEC.md` is the authority; `DECISIONS.md` logs every choice and deviation.

## Open these

1. **[REPORT.md](REPORT.md)**: where things stand, scorecards, validation, open questions. Results live only there.
   Regenerate it from the files on disk with `uv run python -m stages.report` (add `--no-tests` to skip the test run).
2. **Viewer**: `uv run python -m http.server 8000` from the repo root, then open <http://localhost:8000/viewer/>.
3. **Explainer** for non-specialists: <http://localhost:8000/explainer/> (`explainer/index.html`; rebuild it after new
   runs with `uv run python explainer/build.py`).

Build path (from simulation to a real structure): [BUILD.md](BUILD.md), fabrication packs under `build/`
(`uv run python -m stages.build_pack --refresh-doc` refreshes its generated block).

## Commands

```
uv sync                                  # environment (Python >= 3.11, CPU torch)
uv run python -m stages.validate         # solver validation -> runs/validation/metrics.json (slow)
uv run python -m stages.s1_bird          # stage 1, bird note (stages 2-4 get their own module when built)
uv run python -m stages.report           # rewrite REPORT.md
uv run pytest -q                         # fast test suite
```

## Layout

`echo/` (scene, clap, targets, models, design, metrics, export), `stages/` (stage drivers, validation, report,
build pack), `tests/`, `runs/<stage>/<run_id>/` (run folders; `runs/index.json` lists them, newest first),
`viewer/` (static page), `explainer/`, `build/`, `artifacts/` (plots, speech targets, report screenshots).
