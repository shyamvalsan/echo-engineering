"""Stage 1: bird note (descending whistle 3.5 -> 2.0 kHz, 80 ms). `uv run python -m stages.s1_bird --tier0-only`."""

from echo.targets import bird_note
from stages.common import StageConfig, stage_main

CONFIG = StageConfig(
    stage="s1_bird",
    title="Bird note, 3.5 to 2.0 kHz whistle, 80 ms",
    tag="s1",
    make_target=bird_note,
    duration_s=0.12,  # 2*3.06/343 = 17.8 ms to first echo + 80 ms note + 8 ms clap + margin
)

if __name__ == "__main__":
    stage_main(CONFIG)
