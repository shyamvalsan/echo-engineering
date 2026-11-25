"""Stage 1: bird note (descending whistle 3.5 -> 2.0 kHz, 80 ms).

    uv run python -m stages.s1_bird               # full loop: Tier 0 design, Tier 1 correction, field, robustness
    uv run python -m stages.s1_bird --tier0-only  # Tier 0 only (status tier0_only)
"""

from echo.scene import RADII
from echo.targets import bird_note
from stages.common import StageConfig, stage_main

CONFIG = StageConfig(
    stage="s1_bird",
    title="Bird note, 3.5 to 2.0 kHz whistle, 80 ms",
    tag="s1",
    make_target=bird_note,
    duration_s=0.12,  # 2*3.06/343 = 17.8 ms to first echo + 80 ms note + 8 ms clap + margin
    f_max=4000.0,  # Tier 1 grid: ppw 9 at 4 kHz (dx 9.4 mm), where all four radii are validated
    half_angle_deg=20.0,
    catalog=RADII,
    a_ref=0.01,
    target_fill=0.01,
    correction_rounds=5,
    robustness=True,
)

if __name__ == "__main__":
    stage_main(CONFIG)
