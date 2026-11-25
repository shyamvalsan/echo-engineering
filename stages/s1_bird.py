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
    target_fill=0.0066,  # superseded by the density sweep below
    # Realization (task 6b): phase-locked comb, one ring per carrier period (K = 1; its 2nd harmonic lies at >= 4 kHz,
    # outside the clap/design band for this 3.5 -> 2.0 kHz note). Chosen on Tier 0 by the spectrogram loss under
    # radial jitter (runs/s1_bird/design_study_tier0.json): judges never used to choose.
    realization="phase_locked",
    posts_per_period=1,
    # Density sweep on Tier 1 (fd8-3), picked by Tier 1 spectrogram loss only (1060 / 2000 / 3030 posts of 1 cm).
    fill_candidates=(0.0035, 0.0066, 0.01),
    correction_rounds=2,  # Tier 1 runs in the loop (round 0 reuses the sweep's pick); budget: ~4.5 min per run
    design_study_files=("design_study_tier0.json", "h2_tier1_vs_tier0.json"),
    robustness=True,
)

if __name__ == "__main__":
    stage_main(CONFIG)
