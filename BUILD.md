# BUILD: from simulation to a real echo structure

This is the plan for building a Composed Echo structure: a field of vertical posts that returns a hand clap as a
chosen sound. It is built around the one sound that works in simulation, a falling bird whistle from rings of thin
posts, and says what to build first, what to buy, how to measure it, and the number that decides each next step.

**How to read the numbers.** Every number that comes from simulation sits in one of two generated blocks: the summary
block in section 1 and the detailed block at the end ([Generated results](#generated-results-do-not-edit)). Both are
rewritten by code from the run folders (`uv run python -m stages.build_pack --refresh-doc`), and every number in them
names its source file. The prose holds no simulated number; where a rule depends on one, it points at a line of a block.
Costs are **estimates** with their basis (date 2026-11-25), never supplier quotes: "(searched)" marks the few prices a
web search confirmed, "(est.)" the rest.

---

## 1. The thing that works: a ring-layout whistle from thin posts

**What it is.** A clap at a marked spot, a few hundred to about a thousand thin vertical posts (1 cm radius: 20 mm
smooth steel bar) standing in a fan in front of it, and a falling bird whistle coming back. The posts stand in
**rings**: each ring lies on one equal-delay curve (an ellipse around clap point and ear), and successive rings are
one period of the note apart in range, so each ring adds one cycle of the whistle; the ring spacing shrinks along
the field and the pitch falls. It is a generalization of a familiar effect: a clap in front of a long flight of
stairs or a picket fence comes back as a pitched chirp, because each step or picket returns a copy of the clap one
period later. A uniform grating gives one note; the rings here give a glide.

**It is audibly a whistle in simulation.** The owner listened to the full-wave (Tier 1) echoes on 25 Nov 2026 and
heard recognizable bird whistles (owner, knowing the target; not blind). The revised, listening-calibrated thresholds
confirm the whistle, with all 26 of 26 control sounds rejected
([criteria](docs/report/criteria.md#stage-1-bird-whistle)). Play them yourself (paths in the summary block below, "Audio to play"): the
stage-1 run's `echo_tier1.wav` (the echo alone) and `as_heard.wav` (the clap, then the echo at its predicted level),
and the same two files for the build pilot (also copied into the pilot's build pack, `listening/run_*.wav`).

**What the automated checks say, exactly as the files have them.** The spec's automated pass marks are strict, and
the design narrowly misses them (summary block, verdict column): the pitch-track error is just above the 3 % mark,
where even a physically perfect echo scores close to it (the judge floor printed beside the value); and the
spectrogram-match score, which compares over a 60 dB range and is pulled down by a faint hiss well below the whistle,
is short of 0.8. These are recorded as FAILED and stay so. The spec itself names a person listening as the final judge,
and by the owner's ear (not a blind test) the whistle is there; the build path is designed to settle that in the real world, cheaply.

**Size, posts, loudness** (numbers in the summary block): about 13 m deep (the note is 80 ms long; 1 ms of echo is
17 cm of range), a fan of ±20° (stage 1) or ±10° (pilot), about a thousand posts (stage 1) or a few hundred (pilot),
covering a fraction of a per cent of the ground. The echo peak ("Level" lines) is tens of dB below the clap itself,
but above the spec's 35 dB line and above a quiet site's background.

<!-- BEGIN GENERATED SUMMARY: stages/build_pack.py --refresh-doc. Do not edit by hand. -->

**The ring-layout whistle** (stage-1 design family and the build pilot; every final run, newest first; the verdict column is the spec's automated pass marks on the full-wave solver, exactly as the files have them, with the judge floor -- the score of a physically perfect echo -- beside each value):

| stage | run | full-wave verdict (spec thresholds) | gating values [judge floor] | echo dB SPL, 100 dB clap (margin over 35 dB) | depth (m) | posts | fill | tier gap (dB) | robustness | source |
|---|---|---|---|---|---|---|---|---|---|---|
| build_pilot | 20261125-150605-pilot_whistle80 | FAILED | pitch_err_pct 5.39 (<= 3, fail) [floor 2.53]; spec_corr 0.611 (>= 0.8, fail) [floor 0.976] | 55.8 (+20.8) | 13.1 | 500 | 0.338 % | -1.4 | fails everywhere | `runs/build_pilot/20261125-150605-pilot_whistle80/metrics.json` |
| s1_bird | 20261125-104529-s1 | FAILED | pitch_err_pct 3.36 (<= 3, fail) [floor 2.53]; spec_corr 0.728 (>= 0.8, fail) [floor 0.976] | 61.6 (+26.6) | 13.2 | 1060 | 0.360 % | -3.0 | fails everywhere | `runs/s1_bird/20261125-104529-s1/metrics.json` |
| s1_bird | 20261125-095837-s1 | FAILED | pitch_err_pct 3.3 (<= 3, fail) [floor 2.53]; spec_corr 0.72 (>= 0.8, fail) [floor 0.976] | 61.3 (+26.3) | 13.4 | 1060 | 0.355 % | -3.1 | - | `runs/s1_bird/20261125-095837-s1/metrics.json` |
| s1_bird | 20261125-033940-s1 | FAILED | pitch_err_pct 5.59 (<= 3, fail) [floor 2.53]; spec_corr 0.64 (>= 0.8, fail) [floor 0.976] | 57.4 (+22.4) | 13.5 | 1060 | 0.351 % | -1.0 | - | `runs/s1_bird/20261125-033940-s1/metrics.json` |

Audio to play (full-wave echo alone, and as heard after the clap at its predicted level): `runs/build_pilot/20261125-150605-pilot_whistle80/echo_tier1.wav`, `runs/build_pilot/20261125-150605-pilot_whistle80/as_heard.wav`; `runs/build_pilot/20261125-150605-pilot_whistle80/echo_tier1.wav`, `runs/build_pilot/20261125-150605-pilot_whistle80/as_heard.wav`.
- Level, build_pilot 20261125-150605-pilot_whistle80: echo peak 55.8 dB SPL for a 100 dB clap at 1 m (-54.6 dB re the direct clap at the ear, mean over the clap variants; clap variant 0 alone, the value REPORT.md quotes: -55.4 dB, `manifest.json` `audio.as_heard_echo_level_db`); +20.8 dB over the spec's 35 dB line; against a quiet rural / suburban / urban-park background of 25 / 35 / 45 dB(A): +31 / +21 / +11 dB (peak against a background level: optimistic). Source `runs/build_pilot/20261125-150605-pilot_whistle80/metrics.json` `headline`.
- Level, s1_bird 20261125-104529-s1: echo peak 61.6 dB SPL for a 100 dB clap at 1 m (-48.9 dB re the direct clap at the ear, mean over the clap variants; clap variant 0 alone, the value REPORT.md quotes: -49.7 dB, `manifest.json` `audio.as_heard_echo_level_db`); +26.6 dB over the spec's 35 dB line; against a quiet rural / suburban / urban-park background of 25 / 35 / 45 dB(A): +37 / +27 / +17 dB (peak against a background level: optimistic). Source `runs/s1_bird/20261125-104529-s1/metrics.json` `headline`.

**Other stages** (not on the build path; one line each, verdicts exactly as in the files):

- s2_motif 20261125-145628-s2v2: FAILED; notes_in_order 0.4 (>= 1, fail) [floor 1]; note_cents_max 726 (<= 30, fail) [floor 8.99]; 29.3 m deep, 1543 posts, 47.5 dB SPL; robustness partial. `runs/s2_motif/20261125-145628-s2v2/metrics.json`.
- s4_speech (4a) "ah" 20261125-142346-s4_4a_ah: FAILED; formant_err_pct none (judge found no value) (<= 10, fail) [floor 10.3]; 25.4 m deep, 1499 posts, 58.6 dB SPL; robustness fails everywhere. `runs/s4_speech/20261125-142346-s4_4a_ah/metrics.json`.
- s4_speech (4b) "om" 20261125-135718-s4_4b_om: FAILED; closed_set_correct 1 (>= 1, pass) [floor 1]; estoi 0.47 (>= 0.5, fail) [floor 0.818]; 42.0 m deep, 1808 posts, 43.1 dB SPL; robustness fragile. `runs/s4_speech/20261125-135718-s4_4b_om/metrics.json`.
- s4_speech (4b) "ba" 20261125-134325-s4_4b_ba: FAILED; closed_set_correct 1 (>= 1, pass) [floor 1]; estoi 0.0746 (>= 0.5, fail) [floor 0.726]; 40.5 m deep, 1751 posts, 44.7 dB SPL; robustness fails everywhere. `runs/s4_speech/20261125-134325-s4_4b_ba/metrics.json`.
- s3_melody 20261125-133244-s3_60ms: FAILED; notes_in_order 0 (>= 1, fail) [floor 1]; note_cents_max 1.2e+03 (<= 50, fail) [floor 6]; 80.5 m deep, 2500 posts, 41.8 dB SPL; robustness fails everywhere. `runs/s3_melody/20261125-133244-s3_60ms/metrics.json`.
- s4_speech (4b) "ma" 20261125-132102-s4_4b_ma: FAILED; closed_set_correct 0 (>= 1, fail) [floor 1]; estoi 0.159 (>= 0.5, fail) [floor 0.788]; 38.0 m deep, 1655 posts, 46.0 dB SPL; robustness fails everywhere. `runs/s4_speech/20261125-132102-s4_4b_ma/metrics.json`.
- s3_melody 20261125-131152-s3: FAILED; notes_in_order 0 (>= 1, fail) [floor 1]; note_cents_max 1.2e+03 (<= 50, fail) [floor 5]; 133.6 m deep, 2500 posts, 37.2 dB SPL; robustness fails everywhere. `runs/s3_melody/20261125-131152-s3/metrics.json`.
- s4_speech (4c) "hello" 20261125-124137-s4_4c_hello: **PASSED**; hello_count 5 (>= 3, pass); 68.1 m deep, 3899 posts, 44.1 dB SPL; robustness partial. `runs/s4_speech/20261125-124137-s4_4c_hello/metrics.json`.
- s2_motif 20261125-122003-s2: FAILED; notes_in_order 0 (>= 1, fail) [floor 1]; note_cents_max 1.2e+03 (<= 30, fail) [floor 8.99]; 29.9 m deep, 2538 posts, 67.6 dB SPL; robustness fails everywhere. `runs/s2_motif/20261125-122003-s2/metrics.json`.

**Key numbers for the whistle** (generated; each with its source file):

- Latest stage-1 whistle 20261125-104529-s1 against the automated marks: pitch_err_pct 3.36 (<= 3, fail) [floor 2.53]; spec_corr 0.728 (>= 0.8, fail) [floor 0.976]; listener moved 1 m: listener_side_1m fail; listener_back_1m fail. Source `runs/s1_bird/20261125-104529-s1/metrics.json`.

Listening spot (stage-1 design study, Tier 0, 1060 posts; waveform correlation of the echo heard at a moved listener against the design listener, delay change removed; source `runs/s1_bird/_studies/design_study_tier0.json` key `sweet_spot`):

| fan half-angle | 10 cm sideways | 25 cm sideways | 50 cm sideways | 1 m sideways | 50 cm back | 1 m back | sideways extent with correlation >= 0.95 |
|---|---|---|---|---|---|---|---|
| +-20 deg | 0.86 | -0.35 | 0.21 | -0.02 | 0.97 | 0.37 | < 10 cm |
| +-10 deg | 0.95 | 0.59 | -0.24 | 0.08 | 0.98 | 0.80 | < 10 cm |
| +-5 deg | 0.97 | 0.74 | 0.61 | -0.21 | 0.96 | 0.89 | 10 cm |

- Placement error (random, radial, Tier 0, latest stage-1 design 20261125-104529-s1): 1 mm: spectrogram correlation 0.828 (threshold >= 0.8, floor 0.976), waveform correlation 0.999; 2 mm: spectrogram correlation 0.764 (threshold >= 0.8, floor 0.976), waveform correlation 0.993; 5 mm: spectrogram correlation 0.650 (threshold >= 0.8, floor 0.976), waveform correlation 0.960. Hear it: `build/s1_bird-20261125-104529-s1/listening/`. Source `build/s1_bird-20261125-104529-s1/pack.json` key `physics.jitter`.
- Temperature: the whole echo's pitch scales with the speed of sound: 0 C -3.4 %, 10 C -1.7 %, 20 C +0.1 %, 30 C +1.8 % against the 343 m/s design. Source `build/s1_bird-20261125-104529-s1/pack.json` key `physics.temperature`.
- Thin posts, low coverage: the stage-1 design (run 20261125-104529-s1), 1060 posts of 1 cm at 0.36 % ground coverage, leaves an incoherent full-wave residue of -16.1 dB against the fast model (stretch -0.24 %); 420 posts of 4 cm (about 2.3 % coverage) leave -0.8 dB, i.e. the full-wave echo no longer resembles the designed one. Source `runs/s1_bird/_studies/tier_diff.json`.
- Unresolved: the full-wave echo differs from the fast model of the same posts by an incoherent residue. Whether it is real forward scattering in the post field or the full-wave solver's rasterization of 1 cm posts (validated against exact theory for single-post backscatter only; see `runs/validation/metrics.json` `caveats`) is not settled. Per design (clap 0; these residues are the two ends of the phase-2c residue test, the fast-model end read at the board's placement accuracy, a fraction of a millimetre at full scale for a CNC-drilled 1:10 board): stage-1 design run 20261125-104529-s1: full-wave residue -16.1 dB, matching 3.8 mm of random radial placement error on the fast model, whose own residue at 1 mm is -28.0 dB, 2 mm is -21.9 dB; build pilot run 20261125-150605-pilot_whistle80: full-wave residue -10.0 dB, matching 4.4 mm of random radial placement error on the fast model, whose own residue at 1 mm is -22.7 dB, 2 mm is -16.6 dB. Source `runs/s1_bird/_studies/tier_diff.json`.
- Dense field extinguishes the echo (stage 2 first design, run 20261125-122003-s2): full-wave minus fast-model level per note 1047 Hz -9.5 dB, 1319 Hz -18.3 dB, 1568 Hz -33.0 dB, 2093 Hz -48.2 dB. Source `runs/s2_motif/_studies/v1_extinction.json`.
- Build pilot (run 20261125-150605-pilot_whistle80): pitch_err_pct 5.39 (<= 3, fail) [floor 2.53]; spec_corr 0.611 (>= 0.8, fail) [floor 0.976]; 500 posts, minimum clear gap 5.3 cm, coverage 0.338 %; echo 55.8 dB SPL. Details: section Pilot design. Source `runs/build_pilot/20261125-150605-pilot_whistle80/metrics.json`.

<!-- END GENERATED SUMMARY -->

### The organizing question: can a person hear it after their own clap?

The owner reports (25 Nov 2026) that the echo-only files sound like the intended whistles, but that in `as_heard.wav`
(the clap followed by the echo at the true ratio) only the clap is heard. That is the central real-world problem, and
this document is organized around it.

1. **What the playback file does and does not show.** The echo is tens of dB below the clap that triggers it (the
   "Level" lines; per test in `listen/README.md`). Played at a comfortable volume, a sound that far below the clap
   falls under the room's own noise, so `as_heard.wav` under-represents absolute audibility. On site, a 100 dB clap
   gives an echo near the dB SPL in the "Level" line: for the whistle, about the level of quiet conversation.
2. **What simulation does not cover: hearing.** A loud sound raises the ear's threshold for tens of milliseconds
   afterwards (forward masking). The whistle's echo starts only about 20 ms after the clap, because the field begins
   about 3 m away (the pilot: 20.2 ms, first row of its audibility table; the stage-1 design, whose first posts stand
   a little closer, slightly under 20 ms). Whether the masking from a clap 50 dB louder
   hides the start of the whistle, or all of it, is **an open perceptual risk, not a computed result**. No masking
   numbers are given here; the experiment below measures it.
3. **The levers, and what each costs** (pilot section of the detailed block, "Audibility levers", fast model):
   - *More posts per ring*: +6 dB per doubling of ring population in the ideal coherent case, but coverage doubles too,
     and coverage is what brings extinction (point 5 below). Within the stage-1 coverage there is little room.
   - *Start the field further away*: the echo arrives later (the table gives first-arrival time for the as-designed
     start and for 6, 10 and 15 m), further from the clap's masking, at a cost in level (spreading) and reach (far edge); the
     table's last column is the post count that would buy the level back.
   - *A quieter site*: the "Level" line compares the echo with 25 / 35 / 45 dB(A) backgrounds and with the 35 dB line.
   - *A sharper trigger than a hand clap*: a clapper board is louder and shorter, which helps the echo (it scales 1:1
     with the source) but does nothing for the ratio between trigger and echo at the ear.
   - *Separate clapper and listener, or a listener further back*: moving the listener away from the clapper lowers
     the clap at the ear faster than the echo, but the listening spot is centimetres wide sideways and somewhat longer
     backwards (the listening-spot table's "back" columns and the pilot's map give the echo's shape there).
   - *Post height*: below about 2 m the echo loses level (detailed block, finite-height table, Fresnel zone).
4. **Therefore the first full-scale experiment is the cheapest one that answers audibility by ear** (phase 3a): a
   small uniform ring grating, or the first few metres of the pilot whistle, on a quiet site, listened to by several
   people, with the clapper wearing and not wearing ear protection, and with listener and clapper as one and as two
   people. It costs a few hundred euros and comes before any large build. **The 1:10 model answers fidelity, not
   audibility:** masking happens in the human ear and does not scale with the model (the model's echo is heard only
   after slowing it down, without the real clap's loudness).

**The other things that decide whether a visitor actually hears it** (each with its line in the summary block or the
detailed block):
1. **The listening spot is centimetres wide.** Moving the ear a few centimetres sideways changes the echo more than
   any build error does (listening-spot table; the pilot's map in the detailed block). The ear position must be fixed
   by a jig, like a chin rest. A narrower fan widens the spot only a little, returns less sound per post and packs the
   posts closer (more extinction): the pilot's ±10° fan was chosen for this trade.
2. **Placement tolerance.** A couple of millimetres of random range error lowers the strict spectrogram score while
   the waveform stays almost unchanged ("Placement error" line). Whether you can hear that difference is a listening
   test you can do today (`build/<pack>/listening/`). Range matters; position along the ring hardly at all.
3. **Temperature** shifts the whole whistle's pitch with the speed of sound ("Temperature" line), as for any
   instrument. Correct measurements for it; tune a permanent piece for the season.
4. **Thin posts, low ground coverage.** Thick or dense fields swallow the echo ("Thin posts, low coverage"; "Dense field
   extinguishes the echo"). Never substitute thicker stock to make it louder.
5. **One open fidelity question:** the full-wave echo carries a faint hiss against the designed one, the size of a few
   millimetres of placement error ("Unresolved"). It is either real scattering between posts or the solver drawing
   1 cm posts on a ~1 cm grid. The 1:10 scale model answers it.

**What to build first, cheapest first** (decision ladder, section 2):
- **Today, free:** listen to the echo-only and boosted files (`listen/`, the pilot pack's `listening/`) and to the
  placement-error set.
- **Phase 3a, a few hundred euros, first:** the audibility test above, on the candidate site: one 20 mm bar, then a
  30-post grating (or the pilot's first few metres), several listeners, by ear.
- **Phase 2, about €1–2k (est.), in parallel, tabletop 1:10 ultrasonic model:** one pin, a uniform grating, then every
  post of the pilot whistle in a CNC-drilled board, played back 10× slower: fidelity in 3D with ground, and the
  residue question. Not audibility.
- **Phase 3b, about €5–10k (est.):** the pilot whistle at full scale, only after 3a says people hear a tone after their
  clap and 2c says the design is faithful.

**Rules.**
- **R1. Ear first, then model, then steel.** 3a (audibility by ear) and 2 (fidelity) before any build beyond 3a; 3b
  only when both say go.
- **R2. Fix the ear** within the sideways extent of the listening-spot table for the fan you build.
- **R3. Thin and sparse:** 1 cm radius posts at the coverage of the runs in the table.
- **R4. Short first:** the whistle is the shortest piece; longer pieces lose level and coherence with depth.
- **R5. Place in range, loosely in bearing** (the detailed block's "range gradient" line gives how little a bearing
  error matters).
- **R6. Correct temperature:** every acceptance measurement is resampled by c(T)/343 before scoring.
- **R7. Automated checks stay strict:** simulation verdicts use the spec thresholds as recorded; physical measurements
  use the measurement margins in the detailed block (from measurement repeatability and thermometer accuracy), applied
  symmetrically; the forced-choice listening test is the human gate.

### What did not work in simulation, and why it is not on the build path

The four-note motif, the Ode-to-Joy melody and the speech targets (vowel, syllables, "hello") all ran on the
full-wave solver (one line each in the summary block, "Other stages"). The longer tonal pieces lost their later notes
to **extinction**: sound fading as it passes through long, narrow or thick-post fields (30–130 m deep). Speech is
limited by **weak scattering at low pitch** from thin posts and by a clap that carries little low-frequency energy;
"hello" passed its recogniser test, with low intelligibility and only at one listening spot. All of these need far
more posts and land (cost) than the whistle. Details and causes: `REPORT.md`. No phase below is built on them.

---

## 2. Decision ladder (one page)

| Phase | What is built | Cost (order of magnitude) | Time | What it proves | Go / no-go number |
|---|---|---|---|---|---|
| 1. Desk (done) | Simulations, build packs, listening files | 0 | done | What the models support (section 1) | **Go to 2:** always (R1). Listen to the files first (phase 1). |
| 2a. Rig check, 1:10 | Ultrasonic rig plus one pin | ~€0.7–1.5k (est.) | 1 week | The rig measures what the fast model predicts for one post, with 3D, the board as hard ground and real post height | Single pin: echo level within ±2 dB of the fast-model rigid-ground prediction at the same heights. |
| 2b. One note, 1:10 | A uniform grating of pins (rings at one spacing) | +€50–100 (est.) | days | A tone comes back at the predicted pitch; the precedent reproduced in the rig | Tone frequency within ±0.5 % of c/(2Δρ) at the measured c. |
| 2c. The pilot whistle, 1:10 | Every post of the pilot design as 2 mm pins in a CNC-drilled or laser-cut board | +€0.3–0.6k (est.) | 1–2 weeks | Whether the full-wave residue is physics or solver (section 1, "The other things that decide whether a visitor actually hears it", point 5, "One open fidelity question"), and whether the design sounds right in 3D | First: in-band SNR ≥ the detailed block's **SNR gate**. Then the **residue test**: the measured echo (temperature-corrected, scaled to full size) against the fast-model echo of the as-built pin positions, after the same stretch-and-filter fit the solver comparison used. Residue within the measurement repeatability of the fast model's residue at the board's placement accuracy → the solver was the cause → go to 3b. Residue near the full-wave residue of the same design (summary block, "Unresolved", the pilot's row) → physics → redesign before any full-scale build. Then the stage-1 judges, read with the **Measurement margins**. |
| 3a. Audibility by ear, full scale (do first, alongside 2) | 1 post, then a 30-post grating (or the pilot's first few metres), on a quiet candidate site | ~€0.2–0.5k (est.) | 2 days | **Whether a person hears a tone after their own clap** (forward masking is not simulated and does not scale to 1:10); real ground, wind, background | Grating tone heard after the clap by at least 8 of 10 listeners at the marked ear position, reported separately for clapper = listener and clapper ≠ listener, with and without ear protection on the clapper. Single-post level within ±3 dB of the rigid-ground prediction on hard ground (state the offset on grass). If nobody hears it: try the levers (later start range, quieter site, separate clapper) before any larger build. |
| 3b. Full-scale pilot (only after 3a and 2c say go) | The pilot design (section Pilot design) | ~€5–10k (est.: BOM count × per-post cost, plus survey and labour) | 3–8 weeks | A clap returns the whistle outdoors | In-band SNR ≥ the SNR gate. Judges against the stage-1 thresholds with the **Measurement margins**, on the measured echo resampled to c = 343 m/s. Level within ±3 dB of prediction. 8 of 10 naive listeners name the sound (bird) from a forced choice of 4. |
| 4. Permanent installation | Durable version; longer pieces only after a short one works | €50–500k (est.) | months | That it lasts, is safe and can be visited | Permissions, safety review, maintenance plan. The 3b result repeated across seasons. |

**On failure, check in this order:** noise (SNR below the gate: a noise result, not a structure result), temperature
(was c(T) applied with a measured temperature?), rig or site (does the single post match?), placement (photograph or
re-survey the as-built positions and recompute the fast model on them), and only then the design.

---

## 3. Phases

### Phase 1: desk (done)

**Established** (section 1 and the generated blocks): the verdict of every stage on the full-wave solver; echo levels;
the listening spot; placement, temperature, height and ground sensitivity of the stage-1 design and the pilot on the
fast model; the pilot's full-wave score.

**Left open:** whether the full-wave residue is physics or solver (phase 2c); real ground impedance (grass), ground
roughness, wind and turbulence, and human hearing next to a 110 dB clap (phases 2–3).

**Free desk listening test, do it today.** On headphones, at a level where the clap is loud but comfortable:
- `runs/<stage>/<run_id>/as_heard.wav` of the stage-1 run and of the pilot run: the echo at its predicted level after
  the clap. If the note cannot be heard through the clap's after-effect, no build fixes that (loudness budget).
- `build/<pack>/listening/`: the same design with 0, 1, 2, 5 and 10 mm random radial placement error, echo alone at
  one common gain, plus as-heard versions. If several listeners, blind, cannot tell 2 mm from 0 mm, the judge failure
  at small sigma is not a practical limit, and the tolerance budget can be set by ear (tolerance budget section).

### Phase 2: 1:10 ultrasonic scale model (tabletop)

**Why it works.** Wave physics has no length scale of its own, apart from absorption and viscosity. Divide every
length by 10 and multiply every frequency by 10, and the pressure field is the same, with time running 10× faster.
- The 500 Hz–4 kHz design band becomes 5–40 kHz.
- A 1 cm-radius post becomes a 1 mm-radius (2 mm diameter) pin. The catalog of 1, 2, 4 and 8 cm becomes pins of
  2, 4, 8 and 16 mm diameter.
- 3 m becomes 0.3 m. The board size for a design is in the block's build-pack line ("1:10 hole field extent").
- A clap at 1.5 m height becomes an emitter 150 mm above the board, and the ear becomes a mic 150 mm up.
- The baseboard is a rigid ground, so the model includes ground reflection, finite post height and full 3D
  multiple scattering. Those are exactly the effects Tier 0 and Tier 1 leave out.

**What does not scale, and what to do about it.**
- *Air absorption.* It rises roughly with f² in this range, so at 10× frequency it is far stronger per metre. The
  model path is 10× shorter, but the loss is still not equal. The block's "1:10 model air absorption" table gives the
  excess, computed with `echo.scene.alpha_db_per_m` (ISO 9613-1, 20 °C, 50 % RH). It is negligible at 5–10 kHz and
  reaches a few dB at 40 kHz on the far rows: the model's echo loses its top end towards the end of the note.
  - Correct it in post-processing: multiply the measured spectrum in short time windows by 10^(+Δα(f)·c·t/20), using
    Δα from the measured temperature and humidity.
  - Or compare against a prediction that includes model-scale absorption.
  - Log temperature and RH for every measurement. Above 20 kHz, absorption depends strongly on humidity.
- *Viscous boundary layer.* δ = √(2ν/ω) is about 12 µm at 35 kHz against a 1 mm pin radius. The block lists the
  ratio (boundary-layer line). Its effect on scattering is of the order of that ratio, well below 0.1 dB. Ignore it.
- *Pin surface.* Rods are smooth to well under 0.1 mm, far below 1/10 of the 8.6 mm model wavelength at 40 kHz.
  Copper-coated welding rod is fine.

**What is built, in order (cheapest first).**
- *2a, one pin.* One 2 mm pin at 0.5 m model range (5 m full scale) on the bare board. Proves the rig.
- *2b, one note.* The 30-post grating of phase 3a at 1:10: `echo.buildkit.grating_scene()` gives the full-scale
  coordinates; the pilot's build pack carries it as `grating/` (stake-out and 1:10 template). About 30 holes.
- *2c, the pilot whistle.* Every post of the pilot design (section Pilot design) as a pin, from the pilot pack's
  `template_1to10.dxf`. The pilot's rings are phase-locked to the note, so 2b is literally its simplest special case.
- *Baseboard (option A, laser).* Two identical guide plates of 3 mm acrylic or birch plywood, cut from
  `template_1to10.dxf` / `panels_1to10/*.dxf`. Stock is 600 × 400 mm (a common laser bed); the pack says how many
  panels. Mount them 50 mm apart on spacers, over an 18 mm MDF base that the pins rest on. Two plates 50 mm apart
  hold a pin vertical to about (hole clearance)/50 mm. With 0.05 mm clearance, that is 1 mrad.
  **The top face of the upper plate is the model's ground.** The pins pass through the whole 56 mm stack, so they are
  longer than in option B (`bom.md`, option A_laser_plates). The emitter and mic heights are measured from the upper
  plate too, and the upper plate must continue to the S and L marks.
- *Baseboard (option B, CNC).* One 18–25 mm MDF or birch-ply board, CNC-drilled 15 mm deep at nominal diameter for a
  press fit. Same DXF.
- Butt the panels together and align them on the engraved crosshairs (REG layer, 100 mm model grid = 1 m at full
  scale). Holes that cross a joint are cut on both panels (layer HOLES_SPLIT) and close up when the panels are butted.
  The DXF is drawn as seen from the top face, not mirrored.
- *Pins.* One per post. Length = post height ÷ 10 + 56 mm for option A (plate stack), or + 15 mm for option B (hole
  depth) (`bom.md`, model table). A pin cut to the option-B length and used in option A would stand 56 − 15 = 41 mm short of the
  design height (H/10 − 41 mm; for 2 m posts, 159 mm instead of 200 mm). Check the block's height table for what that
  costs.
- *Surround.* The board's own top surface must continue to the clap and mic marks (the S and L marks on the
  template). Put acoustic foam or a heavy blanket on the table edges.
- *Space.* An echo from any surface at distance d arrives at 2d/c. Keep every hard surface (walls, ceiling, a person)
  farther from the emitter than the model clearance in the block's "Design geometry" line, so the
  room echoes arrive after the structure's echo has ended and can be time-gated out.

**Parts list (phase 2, ordering list).**

| Item | Spec | Qty | Cost (est.) | Notes |
|---|---|---|---|---|
| Pins, 2 mm | Ø2.0 mm mild-steel TIG/gas filler rod, 1 m lengths (sold in 5 kg tubes, about 200 m each), or Ø2 mm silver steel / brass / carbon-fibre rod | `bom.md` model table (×1.05 spare) | €15–35 per 5 kg tube (est.) | Cut 4 pins per metre with a bench-mounted cutter and a length stop. Roll each on glass and reject any that rock (bow > 0.1 mm). |
| Pins, 4 / 8 / 16 mm | silver steel, brass or aluminium rod; hardwood dowel for 8 and 16 mm | as `bom.md` | €1–5 per metre (est.) | Only if the design uses larger radii (stage 1 does not). |
| Guide plates | 3 mm cast acrylic or birch ply, 600 × 400 mm | 2 × panel count | €8–20 per acrylic sheet, €3–8 per ply sheet (est.) | Or a laser-cutting service: €50–150 per hour (est.); cutting time scales with the hole count of the pack's template. |
| Base | 18 mm MDF, the block's "1:10 hole field extent" plus 100 mm all round, plus spacers | 1 | €30–60 (est.) | |
| Emitter, broadband (pick one) | **(c) preferred:** a spark source, either a gas-lighter piezo igniter or a small HV spark gap. It gives a 20–50 µs impulse, broadband past 100 kHz, from a source a few mm across, so it is close to omnidirectional and can sit 30–50 mm above the board. (a) Avisoft Vifa ultrasonic dynamic speaker, 1–120 kHz ±12 dB, 92 dB SPL at 50 kHz (searched: spec only, price not found; ask Avisoft). (b) An air-motion-transformer or ribbon tweeter specified to 40 kHz. | 1 | (c) €5–50 (est.); (a) a few hundred € (est.); (b) €50–150 (est.) | (a) and (b) are several cm across. At 20–40 kHz (ka ≫ 1) they beam strongly, differ by tens of dB at 90° off axis, and their bodies scatter next to the mic. They cannot put an acoustic centre 30–50 mm above the board, so they are usable only for the 150 mm-height case and only with the on-axis calibration in step 3. A 40 kHz ultrasonic transducer (€2) is narrowband (±1–2 kHz): a single-frequency check only. Spark: HV safety, eye protection, no flammables; shot-to-shot level varies by a few dB, so normalize each shot by its own direct sound (valid for a spark, which is nearly omnidirectional, with a small MEMS capsule). |
| Microphone (pick one) | (a) USB ultrasonic mic sampling at 384 kHz, e.g. Dodotronic Ultramic 384K EVO, €280 incl. VAT (searched, veldshop.nl, 2026-11-25); (b) Knowles SPU0410LR5H-class analog MEMS mic on a breakout (to about 80 kHz), into the interface; (c) a ¼-inch measurement mic rated to ≥50 kHz (several hundred €, est.) | 1 | see left | Prefer a bare MEMS capsule (port about 1 mm) on a thin stalk: small enough to be nearly omnidirectional at 40 kHz, and it barely scatters. MEMS capsules have a resonance above 20 kHz; step 3 calibrates it out. A USB mic's housing is a scatterer, so mount it with its capsule end towards S on a thin rod. |
| Audio interface | 2 in / 2 out at ≥192 kHz (e.g. a Focusrite Scarlett 4th gen or similar) | 1 | €150–250 (est.) | At 192 kHz, Nyquist is 96 kHz. Check the response to 40 kHz with an output-to-input loopback cable on day 1. |
| Small power amplifier | Class-D board, 10–20 W | 1 | €15–40 (est.) | For emitter (a) or (b). |
| Thermometer / hygrometer | ±0.5 °C, ±3 % RH | 1 | €15–30 (est.) | Needed for c and absorption. |
| Tools | Laser cutter or CNC (or a service), rod cutter with length stop, calipers, square, level | | | |

Total for phases 2a–2c: about €0.7–2k (est.), set mostly by the emitter and mic choice.

**Measurement procedure.**
1. Place the emitter's acoustic centre at S and the mic at L, 30 mm from S, at the same height above the ground
   plane. Use the height named in the block's **Phase-2c measurement height** line (pilot section). Then also
   measure at 150 mm (the standing-ear case). There the block predicts a judge failure from ground combing, and
   seeing that failure tests the ground model.
2. *Stimulus.* Either a logarithmic sine sweep from 4 to 48 kHz over 1–2 s, repeated 8–16 times, deconvolved by the
   inverse sweep (Farina method), or repeated impulses (spark or a 20 µs click), 32–64 shots, aligned on their direct
   sound and averaged. Averaging N shots gains 10·log10(N) dB of SNR (+15 dB for 32).
   *SNR requirement:* in-band SNR at least the block's **SNR gate** over the echo window. The gate is derived from the
   block's noise table (the judges on the nominal echo with added in-band noise) plus a stated margin. Measure SNR as
   the echo-window energy against the same window of a recording with the stimulus off. Starting from a single-shot
   SNR₁, the number of shots needed is N = 10^((gate − SNR₁)/10). The block's field-test levels give the echo level to expect for 3a.
3. *Calibration and normalization.* The project's convention is the echo relative to the free-field direct sound at
   the listener. The direct path in the rig leaves the emitter and enters the mic about 90° off the directions of the
   echoes, and the mic sits in the emitter's near field (a²/λ ≈ 26 mm at 40 kHz for a 15 mm-radius driver). So
   dividing by the direct arrival does **not** cancel a loudspeaker's or a large mic's response. Instead:
   - in free field (everything ≥ 1 m away), measure the emitter→mic response on the emitter's axis towards the
     structure, at a known distance d_cal;
   - correct the echo by that response and by spherical spreading (1/r).

   Only with a spark and a bare MEMS capsule, both nearly omnidirectional and tiny, is the direct-sound division an
   acceptable shortcut. Check that by comparing it with the on-axis calibration once.
4. *Time gate.* Keep from (first echo delay − 3 ms) ÷ 10 to (last echo delay + 10 ms) ÷ 10. The block's "Design
   geometry" line gives both ends in model and full-scale time. Check that no room reflection lands inside the gate:
   run once with the pins removed, which is also the empty-scene baseline.
5. *Scale to full size.* Resample the measured impulse response so model time ×10 = full-scale time, and model
   frequency ÷10 = full-scale frequency. In practice, relabel the 192 kHz recording as 19.2 kHz, then resample to
   16 kHz. **Temperature:** the measured echo is stretched by 343/c(T). Before scoring, resample the measured
   (full-scale) response in time by c(T)/343, with c(T) = 331.3·√(1 + T/273.15) from the measured air temperature;
   correcting the prediction instead would leave the judges comparing a shifted echo with the fixed target. How much
   an uncorrected temperature moves the judges is in the block's temperature rows (0, 10 and 30 °C, with the judge
   floor). Those rows set how much an omitted correction would bias a gate. The correction costs nothing, so apply it
   whatever they show. Then convolve with the 5 claps
   of `echo.clap.clap_family` and score with the stage's judges.
   *(Tooling: a small `score_measurement` script is still to be written. It is not part of this task; see the report.)*
6. *Listen.* Play the raw 192 kHz recording at 19.2 kHz (10× slower). You hear the full-scale event: a clap and its
   echo, exactly as the full-size structure would return them. Do this before believing any number.
7. Report every judged result next to the block's judge floor: the same judges on a physically perfect echo. Pitch
   in particular has a floor not far below its threshold.
8. *Residue test (2c; the reason the model is built first).* Photograph the board from above (or measure the drilled
   positions on the CNC's own log) and compute the fast-model echo of the **as-built** pin positions. Fit the
   measured, scaled echo to it with the same range-proportional stretch and 33-tap filter the solver comparison used
   (`stages/s1_tierdiff.py` does this for two simulated echoes; the measured-echo front end is part of the
   `score_measurement` script still to be written). The incoherent residue left over is the number:
   - near the fast model's own residue at the board's placement accuracy (summary block, "Unresolved": residue at
     1 mm), within the repeatability of two repeated measurements: the full-wave residue was the solver's drawing of
     small posts, not physics. The design is better than the full-wave verdict says; go to 3b;
   - near the full-wave residue (same line): forward scattering between posts is real. Every many-thin-post design
     carries it; redesign (fewer rings at higher signal per post, lower coverage, or a shorter piece) before any
     full-scale build;
   - in between: report both numbers; the judges with the measurement margins decide 3b.

**Pass / fail, and what to do on failure.** Check the failure branches in this order.
- Noise first: if the in-band SNR is below the block's SNR gate, the run is not a result. Average more shots, use a quieter room,
  or use a louder source. Do not blame placement.
- Temperature second: check that the c(T) resampling was applied with a measured temperature.
- 2a: if the single pin is off by more than 2 dB, the rig is wrong, not the physics. Check the mic and emitter
  positions, gating, and the absorption correction.
- 2b: if the grating tone is off by more than 0.5 %, check the temperature reading and the pin spacing first.
- 2c: run the residue test before the judges (below). If the judges fail but the level matches, it is a placement or design-tolerance problem. Photograph the board
  from above, measure where the pins actually stand, and rerun Tier 0 on the measured positions. If that also fails,
  the design is too fragile and goes back to the desk with the tolerance in the loss. If the level is far below
  prediction, multiple scattering or shadowing is stronger than the models assume. Report it, compare with Tier 1,
  and redesign at lower density.

---

### Phase 3: full scale outdoors

#### 3a. Field calibration (do alongside phase 2)
- On the candidate site, drive **one** 20 mm steel bar 2 m tall at 5 m from a marked clap point. Measure its echo with
  a loudspeaker sweep, or with 20 claps or clapper-board hits, at ear heights 0.3, 0.5, 1.0 and 1.5 m. Compare with
  Tier 0 rigid-ground predictions for one post.
- Then set a 30-post grating: 30 posts at bistatic range 5 m + i·c/(2·3000 Hz) (5.7 cm steps). Their bearings cycle
  through −10, −6, −2, +2, +6 and +10°, each post on its own equal-delay ellipse, so no post stands in the forward
  shadow of the previous one. `echo.buildkit.grating_scene()` gives the coordinates. It should return a 3 kHz tone
  about 10 ms long. Listen and record.
- *Expected level and SNR.* The block's "Field-test echo levels" table gives the Tier 0 level of the single post and
  of the grating. The block's "Phase-3a SNR estimate" table turns them into single-hit SNR and the number of averaged
  hits needed for the SNR gate, at 25, 35 and 45 dB background.
- *Parts.* 30 × Ø20 mm bars of 2.5 m (one 12 m bar cuts into 4), a steel tape, a sledge or post driver, a
  measurement mic (class-2 omni, about €40–100, est.), a 48 kHz recorder, a small PA speaker, a thermometer, and an
  anemometer (about €20–40, est.). Roughly €200–500 (est.).
- This retires the ground question (grass against hard ground), the wind question and the "can I hear it next to
  the clap" question at about 1/100 of the cost of a pilot.

#### 3b. Pilot structure

**Site requirements.**
- *Background.* LA90 during measurements at least 20 dB below the predicted echo peak SPL (summary block, run table). Rural
  quiet sites run about 25–35 dB(A), suburban 35–45, urban parks 45–55 (typical ranges, est.). Measure before
  choosing a site: one evening with a sound-level meter app or a class-2 meter.
- *Ground.* Flat to ±2 cm over the field. Hard ground (asphalt, concrete, rolled compacted gravel or a plywood deck)
  makes the image-method rows of the block apply. On grass, the ground reflection near grazing incidence is weaker
  and phase-shifted. Expect results between the free-space and rigid-ground rows, and measure it in 3a.
- *Clearance.* Every hard object (wall, car, tree trunk, fence) farther from the clap point than the far edge of the
  site clearance in the block's "Design geometry" line (pilot section), so its echo lands after the analysis
  window. Nothing reflective behind the clapper within the same distance.
- *Wind.* Acceptance measurements only at mean wind ≤ 3 m/s at 2 m height, and air temperature logged at 1.5 m.
- *Access.* The site must be closed to the public during the build (trip and impalement hazard).

**Post material and height.**
- Height comes from the block, not from rules of thumb: use the *Readout* line "Post height". The physics is in
  [Fresnel zone](#post-height-fresnel-zone-argument). Choose the shortest height whose row passes the judges and
  stays within 1 dB of infinite posts.
- If a rigid-ground row with a low ear passes at a short height, a hard deck with short posts and a crouching
  listener is the cheaper build. Lower ears also relax the plumb tolerance.
- Material: the post must not move under wind by more than a fraction of the radial budget. `bom.md` gives the
  static tip deflection at 10 m/s for each stock item. At 2 m, a 20 mm solid steel bar deflects about 2 mm, PVC
  conduit about 250 mm. Deflection scales as H⁴, so at 1 m every option deflects 16× less.
- Nearest stock to the catalog (full list in `bom.md`):

  | Catalog | Stock |
  |---|---|
  | 2 cm | Ø20 mm smooth round bar, or DN15 tube 21.3 mm. Not ribbed rebar: B500 measures about 22–23 mm over the ribs. |
  | 4 cm | DN32 tube 42.4 mm, or Ø40 bar |
  | 8 cm | 76.1 mm tube |
  | 16 cm | 160 mm PVC over a steel stake, or a 168.3 mm tube |

- Radius errors up to 1 mm match the spec's 1 mm radius-jitter case. Above that, rerun the realization with the stock
  radius before building.
- *Cost basis.* European rebar was about €700–750 per tonne ex-works in 2026 (searched, gmk.center, Oct 2026). Smooth
  round bar costs somewhat more. Merchant cut-length prices run about 1.5–2× that, so €1.1–1.8 per kg (est.). Ø20 bar weighs 2.47 kg/m, so a
  2.6 m post (2 m above ground plus 0.6 m driven) is about €7–10 (est.) in steel, plus a €0.2–0.5 safety cap
  (est.). Multiply by the BOM count. The pilot's BOM count (Pilot design) sets the sum; a design of thousands of posts would be a five-figure
  sum, which is why the pilot is capped at a few hundred.

**Foundations.**
- *Firm soil.* Drive bar 0.5–0.6 m through a guide (a steel tube on a tripod, plumbed). Driven bar stays where it is
  driven. Check plumb in two directions and the radial position at ear height after driving, not before.
- *Hard surface or soft soil.* Use the deck, below.
- *Deck option.* Exterior plywood sheets (18 mm, 2440 × 1220 mm), CNC-cut from `template_1to1.dxf` /
  `panels_1to1/*.dxf`, laid on a levelled sub-base. Posts sit in the holes and in a second, lower batten frame cut
  from the same file. The factory sets the post positions (CNC accuracy about ±0.2 mm), not the crew. The deck is
  also the hard ground that the rigid-ground rows assume. Cost: €50–90 per sheet (est.) plus CNC time.

**Survey and stake-out.**
- `stakeout.csv` lists every post in build order (far range bands first, so tapes from the clap point never cross
  posts already set).
- *Polar method (preferred).* A total station (hire about €100–200 per day, est.) or a theodolite over S, zeroed on
  the +x baseline. Set the bearing `bearing_deg` and the distance `dist_S_m`. The distance from S is nearly the range
  itself (block: range gradient ≈ 1) and is the critical number. A bearing error moves the post sideways, which becomes range error at only the fraction given in the block's "range gradient" line
  (block: "range gradient" line), so the angle can be set much more loosely (see the tolerance budget).
- *Two-tape method.* Set the tape from S (`dist_S_m`) and the tape from the side control point `ctrl`
  (`dist_ctrl_m`). The second tape crosses the first near 90°. Use a steel tape at 50 N tension, never fibreglass
  (it stretches 0.1–0.5 %).
- *Baseline offsets.* `along_m` / `across_m` are for a quick check.
- Mark S and the controls B+ / B− with survey nails in concrete blocks. Check them every day.
- *Progress check while building.* The far bands carry the end of the note. After each 1 m of range is built, an
  impulse-response measurement shows the echo growing from its tail. A wrong band shows up at once at its own delay
  (`delay_ms`).

**Acceptance measurement.**
- The same procedure as the model, at full scale: a sweep at 0.3–8 kHz from a compact loudspeaker at S, or 30
  clapper-board hits, with a class-1 or class-2 mic at L. Use a 48 kHz recorder and log temperature and wind.
- Pass:
  - in-band SNR at least the block's SNR gate over the echo window (otherwise: more averaging or a louder source;
    not a structure result);
  - the judges pass on the measured response after resampling it in time by c(T)/343 (measured temperature) and
    convolving with the clap family, read against the block's judge floor;
  - the level is within ±3 dB of prediction;
  - a forced-choice listening test with 10 naive listeners (target sound among 4 options) gets ≥ 8 correct.
- Fail (check in this order):
  - noise: SNR below the gate; see above;
  - judges fail and the level matches: placement. Re-survey 50 random posts at ear height. If σ is over budget,
    fix those posts.
  - level low: compare with the 3a single post. If that was also low, it is the ground or the site, not the
    structure.

### Pilot design

The pilot is designed for building, not for the spec's judges, using what the stages learned. Its numbers, the
candidate study it was chosen from and its full-wave score are in the detailed block, section **Pilot design**
(generated from `runs/build_pilot/<run_id>/metrics.json` and `build/build_pilot-<run_id>/`).

**Design rules applied** (`stages/build_pilot.py`):
- *Phase-locked rings* (one ring of posts per period of the note, every post of a ring on one equal-delay ellipse),
  not scattered posts: stage 1 found them louder and less sensitive to placement at equal post count, and they are a
  generalization of the grating that is known to work.
- *1 cm-radius posts*, built as 20 mm smooth round bar (BOM; not ribbed rebar, which measures over the ribs well
  above the catalog radius).
- *Narrow fan, ±10°*, for a wider listening spot than ±20°.
- *A post cap a small team can install* (a few hundred) and *ground coverage at or below the stage-1 design's*: thick
  or dense fields extinguish the echo.
- *Stretch pre-compensation on*: ring ranges shrink by the measured slowing of sound through the post field.
- *Walkable spacing where feasible*: it is not feasible here. Rings one period apart are a few centimetres apart in
  range, so the minimum clear gap between posts (block) is set by the spec's minimum surface gap, not by a person.
  Visitors stand at the marked listening position; the field is a no-walk area (phase 4, safety).

**How the target was chosen.** Three targets were compared on the fast model with a selection rule written before the
results (block: candidate study): stage 1's whistle at ±10°, the same glide compressed to 40 ms (fewer rings), and a
single-pitch 2.5 kHz ping (uniform rings). The rule ranks the listening-spot width, then the waveform correlation under
2 mm placement error, then level. The shorter targets lose on all three at the coverage limit: with fewer posts, each
post's placement error is a larger share of the echo. The stage-1 whistle at ±10° won, which has a useful side effect:
the pilot is judged against the stage-1 pass marks directly, so its verdict is a real pass or fail, not a reference.

**How it scored on the full-wave solver** (block: pilot rows, exactly as recorded): FAILED on both automated stage-1
marks, and by more than the stage-1 design (about a thousand posts, ±20°) does. Fewer posts carry the incoherent
residue as a larger share of the echo (summary block, "Unresolved": the pilot's residue against the stage-1 design's), which the fast-model study already showed as lower waveform correlation under
placement error at lower post counts. Its echo is also a few dB quieter. Listen to it next to the stage-1 echo (pilot
pack `listening/`: `run_echo_tier1.wav`, `echo_only.wav`, `clap_then_echo_boosted.wav`, `run_as_heard.wav`).

**So which whistle goes to full scale?** Decide at 1:10, where pins are cheap: drill both the stage-1 design and the
pilot (two boards), run the residue test and listen to both slowed down. If the residue turns out to be the solver
(phase 2c), the pilot's cheaper build is the candidate for 3b; if it is physics, the larger stage-1 design is the better
whistle, at about twice the posts. The pilot's audibility table (start range, ring population) applies to both.

**Tier 1 budget used**: the nominal solve (with the field) and one jitter solve; no third solve was spent on a later
start range: the trade it would test (later arrival against level) is computed on the fast model in the block, and
audibility itself is a hearing question the solver cannot answer. The speed-of-sound cases were not run
on the full-wave solver; temperature is an exact time-scaling and is covered by the fast-model temperature rows.

**What the pilot would prove, built at full scale:** that a few hundred posts set out with ordinary survey tools return
a clap as a recognizable falling whistle at a fixed listening position, at the level the block predicts; how large the
real listening spot is; how the real ground and wind change it.

**What it would not prove:** anything about the longer pieces (motif, melody: their failures are extinction and
residue over 30–130 m, not post count); that the sound survives a moving listener (it will not, by design); that the
spec's judges pass (read the block's verdict, and the residue test of phase 2c, which decides whether the full-wave
verdict is pessimistic).

**Go / no-go for building it at full scale (3b):** phase 2c's residue test says "solver" or "in between", and the 2c
judges, read with the measurement margins, do not FAIL. If the residue test says "physics" and the judges fail, do not
build the pilot; build the 3a grating as the outdoor demonstrator and return to the desk.

### Does a lower target pitch buy tolerance? (Tier 0 hypothesis, unverified)

Inside the target band the allowed placement error scales with the range period c/(2f), so a lower note should be
more tolerant. The detailed block's "Lower-pitch variant" section tests this with the bird glide shifted down to
1.75 → 1.0 kHz (same pipeline, judges, multi-seed jitter and a like-for-like residual split). On the spec's judges
**the lower-pitched variant was not more tolerant.** Candidate causes:
- (i) its weaker signal relative to the structure's bias (the block compares the two bias-to-modulation ratios);
- (ii) the clap exciting scatter above the variant's target band, which the design must keep silent and which,
  relative to the weaker low note, dominates (the residual split shows per band where the residual lands);
- (iii) the spectrogram judge's sensitivity to residuals around −20 dB.

Reading rule: if the two bias ratios are close, (i) can act only through the clap's spectrum; if the variant's
residual lands almost entirely above its band while the stage-1 residual stays inside its band, that favours (ii).
The block's **Reading-rule outcome** line applies this rule by code and states the result. It also states, in the
variant's favour, how much smaller its in-band residual is than stage 1's (the note itself is better preserved), and
the per-clap waveform correlations: **sensitivity depends strongly on which clap is used** (claps whose energy lies
above the variant's band are hit hardest), so a single-clap test can mislead in either direction.

None of this separates (iii), and none of it is verified beyond the fast model. Direct tests: the variant excited by a
band-limited source (tests ii); a variant re-scaled to the stage-1 bias ratio (tests i); a blind listening comparison
(tests iii). Until then: do not choose a lower target pitch for buildability alone. Low notes also cost level (posts
scatter weakly below ka ≈ 1, the clap is weaker there) and height (the Fresnel zone grows as 1/√f).

---

### Phase 4: permanent installation (outline)

- **Durability.** Hot-dip galvanized steel or stainless posts. Concrete footings or ground screws, set with templates
  as above. Expect a re-survey after the first winter: frost heave moves posts by centimetres, which is far beyond
  the radial budget. Use footings below the frost line, or a deck on screw piles.
- **Safety.** No exposed bar ends (capped or welded domes). Posts visible at night. Spacing that a fall does not
  trap a limb in. Check whether a fenced or raised viewing area is needed.
- **Access.** A marked clap spot and a marked listening spot at the design heights (a fixed stool or a "kneel here"
  plate if the low-ear option is used). A signboard that explains the echo.
- **Permissions.** Landowner, planning (for structures over a local height limit, often about 1–2 m), and public
  liability insurance. Noise is not an issue: the structure is passive.
- **Maintenance.** An annual impulse-response check against the acceptance recording. Re-plumb posts that moved more
  than the budget. Vegetation control on grass sites, because growth changes the ground.
- **Longer pieces.** The motif, melody and speech are not on the build path (section 1, "What did not work").

---

## The physics behind the rules

### Post height: Fresnel-zone argument
- A vertical post reflects most strongly from the region around the ear height where source-to-post-to-ear path
  lengths are within λ/2 of the shortest one: the first Fresnel zone.
- Its half-height is h_F = √(λ·r₁r₂/(r₁+r₂)) ≈ √(λρ/2) when r₁ ≈ r₂ ≈ ρ.
- Hand example: at 2 kHz (λ = 17.2 cm) and ρ = 16 m, h_F ≈ 1.17 m. At 3.5 kHz and ρ = 3 m, h_F ≈ 0.38 m.
- So the far, low notes need the most height. A post that covers the ear height ± h_F returns about the
  infinite-post echo; the first zone alone can return slightly more (Fresnel overshoot). A post whose top is at ear
  height loses about half the zone, roughly −6 dB.
- The block's height table computes this per post and per frequency for the actual design, with
  `echo.tier0.post_echo(mode="3d", post_height=H, ear_height=1.5)`. It is free space, with the posts starting at
  z = 0.

### Ground reflection
- A hard flat ground acts as a mirror. By the image method, posts standing on rigid ground behave like posts twice
  as tall, centred on the ground, lit by the source and by its mirror image at −z.
- The echo is a direct term (source → post → ear) plus a cross term via the image (source → ground → post → ear).
  The cross path is longer by Δ = √(L² + 4z²) − L ≈ 2z²/L, with L = r₁ + r₂ and z the clap/ear height.
- The two terms add as |1 + e^(−i2πfΔ/c)|:
  - with **fΔ/c ≪ ½**, they add in phase: up to +6 dB, and the lower half of the Fresnel zone comes for free, so
    short posts suffice;
  - when fΔ/c reaches ½, a notch: the spectrum is combed, and because Δ changes with range, the notch sweeps through
    the note in time.
- Hand example: z = 1.5 m and ρ = 3 m (L = 6 m) give Δ ≈ 0.75 m, so notches every 460 Hz: a dense comb. z = 0.3 m
  and ρ = 3 m give Δ = 3 cm, with the first notch at 5.7 kHz, above the band: clean +6 dB.
- *Rule:* keep z < √(λ_min·ρ_min/4) for coherent gain. That is about 0.27 m at 3.5 kHz and 3 m.
- The block's rigid-ground table computes this with `echo.buildkit.echo_rigid_ground` (image method on top of the
  Tier 0 finite-height model). Read the "worst 10 ms" column for comb notches, and the judges column for whether the
  sound survives.
- **Real ground.** Grass and soil are porous. At grazing angles of a few degrees, their reflection coefficient at
  2–4 kHz is well below 1 and phase-shifted towards −1, which turns the cross term from help into partial
  cancellation (the "ground dip"). Only hard surfaces (asphalt, concrete, deck) behave like the rigid rows. Phase 3a
  measures the real site.
- The direct clap also gets a ground reflection, which is negligible for z ≥ 0.5 m and up to +6 dB when the hands
  are at the ground. Echo SPLs in this file refer to the free-field direct clap.

### The 1:10 scale model
Frequencies ×10 (5–40 kHz), lengths ÷10, pins of 2–16 mm. Air absorption and viscosity do not scale. The excess
absorption and the boundary-layer ratio are in the block, and the phase-2 section says how to correct for them. The
board is a perfect hard ground, so the model tests the rigid-ground rows directly. It does not model grass.

### Temperature
- c(T) = 331.3·√(1 + T/273.15) m/s. Every echo delay is 2ρ/c, so the whole echo is time-compressed or stretched by
  c(T)/343: **every pitch shifts by the same factor**.
- 0 °C gives −3.4 % and 30 °C gives +1.8 %. That is the same size as stage 1's 3 % pitch tolerance, so the structure
  is "tuned" for a temperature, like any acoustic instrument.
- Intervals between notes are preserved (a tune is transposed, not distorted).
- What the detailed block's temperature rows show: the design as drawn, heard at 0, 10 and 30 °C without any
  correction, scored by the stage judges next to the judge floor. Its *Readout* "Temperature" bullet states per
  temperature whether the judges still pass; that is the cost of skipping the c(T) correction, which costs nothing.
- Acceptance tests therefore compare against the prediction rescaled to the measured c, and report the absolute pitch
  offset separately.
- A permanent piece can be designed for the site's typical visiting temperature. The block's temperature table shows
  whether the design as drawn passes the judges at 0, 10 and 30 °C.

### Wind and turbulence
- *Steady wind along the path.* Out and back over nearly the same path, the delay is L/(c+v) + L/(c−v) =
  2Lc/(c²−v²). The first-order effect cancels, leaving (v/c)². At 5 m/s that is 0.02 %, negligible. Cross-wind is
  also second order.
- *Turbulence* is the real problem. Random gusts and temperature eddies give each post's path a random, time-varying
  phase. The phase variance grows with frequency and path length, so a coherent pattern that works at 30 m of round
  trip can wash out at 300 m.
- That is why short structures (stage 1: block, "Design geometry", longest round trip) come first, why acceptance tests run in light wind,
  and why the melody's depth (spec size table) is a separate risk. The 3a grating repeated on calm and windy days measures it.
- Wind also bends posts. See `bom.md` for deflection, and pick stiff sections.

### Positional tolerance
- *Range is what matters.* A post's echo phase is 4πρ/λ. At 3.5 kHz the range period (one cycle of echo) is
  c/(2f) = 4.9 cm, so a 5 mm range error is a 37° phase error.
- Random errors of σ (in range) reduce the coherent echo by exp(−σφ²/2), where σφ = 4πσ/λ. Hand value: σ = 5 mm at
  3.5 kHz gives −1.8 dB.
- The lost coherent power reappears as scatter. Where it lands is measured, not assumed: the block's residual split
  takes, per clap, the jittered echo minus the nominal echo (common gain removed) and splits its energy into the
  bands below, inside and above the target band (to 4 kHz, and above 4 kHz; the columns sum to the total). It checks that the split reconciles with 1 − corr².
  - *Physical view:* the block's jitter tables give the measured waveform correlation next to the parameter-free
    coherent factor A = exp(−σφ²/2) at the target band's centre. A says how much coherent amplitude survives in the
    band, and nothing about the scatter.
  - *Judge view:* the spec's spectrogram correlation compares log-mel spectrograms over a 60 dB range. A residual
    tens of dB below the echo can fill empty time-frequency bins and pull the score down. The noise table in
    the block shows how sensitive the judges are to an added residual.
- *Direction matters.* The gradient of ρ = (|P−S|+|P−L|)/2 is the mean of the two unit vectors from S and L to the
  post. Its magnitude is cos(β/2), with β the bistatic angle (block: "range gradient" line). So a radial error
  becomes a range error one for one.
- An error **along** the equal-delay ellipse changes the range only to second order (δ²/2r: 1 cm at 3 m is 0.02 mm).
  Tangential placement can be loose (the block tests 50 mm). Only the no-shadow and minimum-gap rules limit it.
  A sideways error measured from the clap point (a bearing error) is not quite along the ellipse, because S and L are
  0.3 m apart. It leaks into range at sin(β/2), largest on the near rows (the block's "range gradient" line gives the fraction).
- The jitter rows use several random draws per sigma (mean and range). Treat a pass/fail within the seed range of a
  threshold as uncertain, and read every judged value against the judge floor (the same judges on a perfect echo).
- *Lean.* The echo comes from the post near ear height. A post leaning by angle θ in the radial direction puts its
  ear-height section z·tanθ off. At z = 1.5 m, 1 mrad (0.06°) is 1.5 mm. At z = 0.3 m it is 0.3 mm. Low ears relax
  plumb tolerance 5×.
- *Systematic scale error* (tape calibration, temperature of the tape) scales all ranges and shifts pitch by the
  same fraction. A class-II steel tape is good to about ±4 mm over 20 m (0.02 %), and steel expands 0.023 % over
  20 K: negligible against 3 %.

---

## Tolerance budget

Radial (range) budget σ_total = the largest radial sigma up to which the block's *Readout* says the judges pass
(judge view). If the blind listening test of phase 1 finds the judge failures at small sigma inaudible, use the ear
instead and log the deviation in DECISIONS.md: σ_total = the largest sigma in the `listening/` set that the listeners
could not tell from 0 mm. Split the budget by root-sum-square:

| Contribution | Method that controls it | Typical σ achievable (est.) | Share of budget |
|---|---|---|---|
| Set-out of the mark | Total station from S / CNC deck | 1–2 mm / ≤0.5 mm | ≤ 50 % |
| Driving or setting the post off the mark | guide tube / deck hole | 2–5 mm / ≤0.5 mm | ≤ 50 % |
| Lean at ear height | plumb in 2 axes, z·tanθ | 1.5 mm per mrad at z = 1.5 m | ≤ 30 % |
| Wind deflection during use | stiff section (`bom.md`) | 0.5–2 mm at 10 m/s for Ø20 steel bar at 2 m | ≤ 30 % |
| Frost / settlement (permanent) | footings below frost line | cm without, mm with | re-survey yearly |
| Systematic scale | steel tape, calibrated instrument | < 0.05 % | negligible |
| Tangential | any | 20–50 mm | separate, loose |
| Radius (stock section) | nearest stock size | ≤ 1 mm (radius) | as spec sweep |

**Rule.** If the block's budget is below about 3 mm, a driven-post build cannot hold it. Only a CNC deck (posts in
factory-cut holes) or a redesign with tolerance in the loss can. If it is below 1 mm, redesign first.

## Loudness budget

| Step | Value | Source |
|---|---|---|
| Hand clap, peak at 1 m | 100 dB | spec assumption; real claps range about 90–110 dB peak |
| Direct clap at the listener, 0.3 m | 110.5 dB | +20·log10(1/0.3) |
| Echo relative to direct (free space, infinite posts) | summary block: run table | 3D estimate corrected by the full-wave tier gap |
| Finite post height | block: height table | Tier 0 3D finite height |
| Ground | block: rigid-ground table (hard ground); 0 to −6 dB worse on grass (est.) | image method; 3a measures it |
| Turbulence (≤ 40 m round trip, light wind) | 0 to −3 dB (est.) | 3a measures it |
| **Echo peak SPL** | block readout "Loudness" ± the rows above | |
| Must exceed | 35 dB (spec line); site LA90 + 20 dB; the forward-masked threshold just after a 110 dB clap | see below |

- **The clap masks its own echo.** The echo starts a couple of tens of ms after a 110 dB click at the same ear (block:
  "echo from ... ms").
  Forward masking from a loud broadband sound raises the threshold by tens of dB for the first 10–50 ms and decays
  over about 100–200 ms. That is a psychoacoustic range, not a computed number. The first part of the note is the
  most exposed.
- Test it with the free desk test (as_heard.wav) and in 3a.
- If it is a problem, start the structure farther away. Each extra metre of start range delays the echo by 5.8 ms,
  and the echo loses only a little level.

**Gain options, in order of cost.**
1. A quieter site or a quieter time of day: free, 10–20 dB relative to a suburban daytime background.
2. Clap and ear near hard ground: up to +6 dB, if the low-ear rows pass.
3. A louder impulsive source for testing and demos (the echo scales 1:1 with the source):
   - clapper board, about 110–120 dB peak at 1 m (est.);
   - starter pistol with blanks, about 130–150 dB peak (est.). That is a hearing hazard, so use ear protection,
     take the reading at the mic and observe local firearm rules.
4. More posts across each arc (wider wedge, ±40° doubles the arc): about +6 dB per doubling, coherently. Shadowing
   and multiple scattering rise, so Tier 1 must confirm.
5. Larger posts: per post, an 8 cm post returns roughly √(8/1) more amplitude than a 1 cm one in the geometric-optics
   limit, and more than that at low ka (Rayleigh-like rise). Fewer, larger posts
   sample the waveform more coarsely and shadow more, so redesign is needed.

---

## Risk register (ranked by what would kill the project)

| # | Risk | Kills because | Cheapest test that retires it | Status / rule |
|---|---|---|---|---|
| 0 | **Nobody hears the echo after their own clap** (forward masking by a clap tens of dB louder, first arrival only about 20 ms later: 20.2 ms for the pilot, slightly less for the stage-1 design) | The structure is silent in practice even if the echo is right | 3a by ear, several listeners (a few hundred euros) | Open; not simulated; does not scale to 1:10. Levers: later start range, quieter site, separate clapper and listener, clapper board (detailed block, Audibility levers). |
| 1 | **The full-wave residue is physics** (forward scattering between thin posts), not the solver | Every many-post design carries a residue that fails the spectrogram judge, whatever the build accuracy | 2c residue test on the 1:10 model (about €1–2k) | Open; the reason the model comes first (R1). |
| 2 | **The listening spot is centimetres wide** | Visitors move; the sound is only right at one point | Free: the pilot's listening-spot map; then 2c with the mic moved, and 3a | Known (summary). Rule R2: fix the ear with a jig; a narrow fan helps at a cost in level. |
| 3 | **Placement tolerance against the spec's judges** | If the judges' millimetre budget stands (and is audible), driven posts outdoors cannot hold it | Free: the `listening/` files, judged blind by ear | If the listening test confirms it: CNC deck or 1:10-template setting out. A lower target pitch is not shown to help. If it is inaudible: set the budget by ear and log the deviation. |
| 4 | 3D, finite height and ground differ from the models | The real echo is not the designed sound | 1:10 model, 2a–2c | Open; the solver is 2D. |
| 5 | Echo inaudible next to the clap (forward masking) or in site noise | Nobody hears it even if it is right | Free desk listening test; then 3a on site | Open. Mitigation: start the structure farther away, a quieter site, a low ear over hard ground. |
| 6 | Dense or thick fields extinguish the echo | Late parts of the sound vanish | Known (summary, stages 1–2) | Rule R3: thin posts, low coverage. |
| 7 | Real ground (grass) combs or cancels the echo | Pitch or level wrong at the ear | 3a single post at 4 ear heights (about €100) | Open. Hard surface or deck removes it. |
| 8 | Temperature drift of pitch | Absolute pitch fails off the design temperature | Desk (temperature rows) | Rule R6; design for the site's season. |
| 9 | Turbulence decorrelates the far rows | Long pieces (motif, melody) smear | 3a grating on calm against windy days | Rule R4: short pieces first. |
| 10 | Cost and labour scale with post count | Unaffordable or too slow | BOM (done) | Pilot capped at a few hundred posts. |
| 11 | Safety and permissions | Cannot open to the public | A conversation with the landowner and the planning office | Phase 4. |

## Rough schedule and budget (estimates)

| Weeks | Work | Spend (est.) |
|---|---|---|
| 0–2 | 2a rig and pin, 2b grating at 1:10; 3a field calibration in parallel | €1–2k |
| 2–4 | 2c pilot whistle at 1:10; the `score_measurement` / residue script | €0.3–0.6k |
| 4–10, only if 2c says go | 3b pilot: site survey, driven posts or deck, build, acceptance | €5–10k plus labour (a few hundred posts at 2–5 min each with a 2-person crew: tens of crew-hours, est.) |
| later | Phase 4 | €50–500k |

---

## Ways to make it smaller or louder (speculative, not designed tonight)

- **Negative reflectivity from resonators or absorbers.** Helmholtz resonators or quarter-wave tubes tuned in band
  reflect with an inverted sign near resonance. That would remove the positive bias, which costs half the
  reflectivity and is the source of the tolerance sensitivity above. Absorbing elements (porous cylinders) could
  shape the envelope instead of adding bias.
- **Panels or slats instead of cylinders.** A flat slat facing the clap point reflects specularly and far more
  strongly than a cylinder of the same width (it is a mirror rather than a scatterer). Fewer elements give the same
  level, but they are more directional, so the listening spot becomes sharper.
- **A wall or terraces.** A stepped wall (risers at the range period) is a "grating" that echoes a tone, the way
  stepped pyramid staircases chirp. Its heights and depths could encode a short glide. It is cheap per decibel, but
  it is a single-angle device and is fixed.
- **Folded paths.** A reflecting wall behind the structure sends sound through it twice, halving the depth for the
  same delay span. Both passes scatter, so the design model needs to include it.
- **Two-sided or circular layouts.** Using more of the 360° around the clap point multiplies the post count per arc
  (louder) without adding depth.
- **Scaling the source instead of the structure.** A fixed impulsive source (a striker plate the visitor hits) is
  louder and more repeatable than a clap, and it narrows the clap family the design must cover.

---

## Regenerating this file's numbers

```
uv run python -m stages.build_pack --refresh-doc          # build packs for the build candidates (latest stage-1 run,
                                                          # every build_* stage), then rewrite both generated blocks
uv run python -m stages.build_pack --doc-only             # rewrite both blocks from the existing packs (fast)
uv run python -m stages.build_pack runs/<stage>/<run_id>  # one build pack -> build/<stage>-<run_id>/
uv run python -m stages.build_pilot --study               # pilot candidate study (Tier 0, about a minute)
uv run python -m stages.build_pilot                       # pilot run with Tier 1 (2 solves; waits for the solver lock)
```

## Generated results (do not edit)

<!-- BEGIN GENERATED: stages/build_pack.py --refresh-doc. Do not edit by hand. -->

Build physics are computed for the build candidates only (the latest stage-1 design and the build pilot); every other run is summarized in the table at the top of this file.


#### Pilot design: build_pilot / 20261125-150605-pilot_whistle80

Verdict wording: passed computed against the stage-1 thresholds (the target is stage 1's whistle). Judges: the s1_bird judges. Source `runs/build_pilot/20261125-150605-pilot_whistle80/metrics.json` keys `metrics`, `headline`, `robustness`, `pilot`.

Candidate study (Tier 0, fan +-10 deg, cap 500 posts, coverage <= 0.35 %; radial Gaussian sigma (1.0, 2.0, 5.0) mm, seeds (11, 12, 13); source `runs/build_pilot/_studies/design_study_tier0.json`). Selection rule, written before the results: judge-free: among candidates with fill <= 0.35 % and posts <= cap, the target with the widest sideways listening spot (largest offset with waveform corr >= 0.95 vs the nominal listener), ties broken by the waveform correlation under 2 mm radial jitter, then by 3D level; within that target the count with the lowest Tier 0 spectrogram loss under 2 mm jitter. Judges are recorded for information only.

| candidate | posts | coverage | min clear gap (cm) | depth (m) | Tier 0 loss | loss at 2 mm jitter | 3D level (dB re direct) | waveform corr at 1 / 2 / 5 mm | sideways extent, corr >= 0.95 | info: judges |
|---|---|---|---|---|---|---|---|---|---|---|
| whistle80 | 301 | 0.203 % | 5.0 | 13.0 | 3.85 | 5.37 | -55.1 | 0.993 / 0.972 / 0.848 | < 5 cm | pitch_err_pct 6.26, spec_corr 0.609 |
| whistle80 | 500 | 0.337 % | 5.3 | 13.1 | 2.86 | 4.41 | -53.3 | 0.996 / 0.982 / 0.894 | 5 cm | pitch_err_pct 2.5, spec_corr 0.814 |
| whistle40 | 100 | 0.217 % | 6.4 | 6.0 | 5.20 | 5.58 | -56.0 | 0.990 / 0.961 / 0.802 | < 5 cm | pitch_err_pct 20.8, spec_corr 0.526 |
| whistle40 | 170 | 0.368 % | 5.0 | 6.1 | 3.35 | 4.49 | -53.4 | 0.992 / 0.970 / 0.848 | < 5 cm | pitch_err_pct 12.9, spec_corr 0.712 |
| ping40 | 101 | 0.212 % | 5.2 | 6.3 | 6.92 | 7.52 | -55.7 | 0.989 / 0.957 / 0.786 | < 5 cm | pitch_err_pct 4.15, spec_corr 0.499 |
| ping40 | 170 | 0.356 % | 5.8 | 6.3 | 3.87 | 6.37 | -53.4 | 0.986 / 0.949 / 0.761 | < 5 cm | pitch_err_pct 0.916, spec_corr 0.703 |

Chosen: **whistle80** at 500 posts (coverage 0.337 %).

Full-wave result: pitch_err_pct 5.39 (<= 3, fail) [floor 2.53]; spec_corr 0.611 (>= 0.8, fail) [floor 0.976]; echo 55.8 dB SPL (-54.6 dB re direct; with 2.0 m posts -53.7 dB); tier gap -1.4 dB; depth 13.10 m; 500 posts; coverage 0.338 %; minimum clear gap between post surfaces 5.3 cm; robustness summary fails everywhere.

Robustness cases (full-wave; listener cases are extra sensors of the same solve, the jitter case is a second solve):

| case | pitch_err_pct | spec_corr | meets the reference thresholds |
|---|---|---|---|
| Nominal design | 5.39 | 0.611 | no |
| Listener moved 1 m sideways | 49.1 | 0.353 | no |
| Listener moved 1 m back | 10 | 0.564 | no |
| Posts jittered 5 mm, radii 1 mm (uniform) | 10.2 | 0.586 | no |
| Clap variant 0 alone | 1.86 | 0.617 | no |
| Clap variant 1 alone | 10.5 | 0.637 | no |
| Clap variant 2 alone | 3.25 | 0.61 | no |
| Clap variant 3 alone | 8.04 | 0.612 | no |
| Clap variant 4 alone | 3.3 | 0.581 | no |

**Audibility levers** (`runs/build_pilot/20261125-150605-pilot_whistle80/metrics.json` key `pilot.audibility`; Tier 0 3D, free field, infinite posts, clap family mean peak, dB re the direct clap at the ear; fast model only (no extinction: coverage above the stage-1 value adds extinction the fast model does not see)). Moving the whole ring field outward delays the echo after the clap but costs level; the last column is the post count that would restore the as-designed level at 6 dB per doubling of ring population:

| field starts at (bistatic range, m) | first echo after the clap (ms) | last echo (ms) | far edge (m) | level (dB re direct) | change (dB) | dB SPL, 100 dB clap | posts to restore level |
|---|---|---|---|---|---|---|---|
| 3.46 | 20.2 | 96.5 | 16.6 | -53.2 | +0.0 | 57.2 | 500 |
| 6.00 | 35.0 | 111.4 | 19.1 | -58.2 | -5.0 | 52.3 | 888 |
| 10.00 | 58.3 | 134.7 | 23.1 | -62.6 | -9.4 | 47.9 | 1467 |
| 15.00 | 87.5 | 163.8 | 28.1 | -66.4 | -13.2 | 44.0 | 2284 |

Ring population (each post duplicated at a small bearing offset on its own ellipse; fast model, so the extra extinction of the higher coverage is NOT included):

| population | posts | coverage | level (dB re direct) | change (dB) |
|---|---|---|---|---|
| x1 | 500 | 0.34 % | -53.2 | +0.0 |
| x2 | 1000 | 0.68 % | -47.2 | +6.0 |
| x4 | 2000 | 1.35 % | -41.2 | +12.0 |

Listening-spot map (tier0 2d: waveform correlation (clap-family mean) of the echo at a moved listener vs the nominal listener, after removing the on-axis delay change); rows: metres back from the design listener, columns: metres sideways:

| back \ side | -0.3 | -0.2 | -0.1 | -0.05 | +0 | +0.05 | +0.1 | +0.2 | +0.3 |
|---|---|---|---|---|---|---|---|---|---|
| -1 | 0.15 | 0.48 | 0.58 | 0.68 | 0.76 | 0.83 | 0.86 | 0.79 | 0.51 |
| -0.5 | 0.15 | 0.51 | 0.83 | 0.93 | 0.97 | 0.94 | 0.86 | 0.67 | 0.39 |
| -0.25 | 0.15 | 0.50 | 0.71 | 0.82 | 0.90 | 0.93 | 0.90 | 0.66 | 0.31 |
| 0 | - | 0.50 | 0.86 | 0.96 | 1.00 | 0.96 | 0.86 | 0.55 | 0.23 |

Bill of materials (`build/build_pilot-20261125-150605-pilot_whistle80/bom.md`): 500 posts of 20 mm (525 with 5 % spare), 2 m above ground + 0.6 m embedded = 2.6 m each, 1365 m of stock: first choice S235 smooth round bar, dia 20 mm (driven direct, cap the top), 263 stock lengths of 6 m (tip deflection 1.8 mm at 10 m/s). Stake-out: `build/build_pilot-20261125-150605-pilot_whistle80/stakeout.csv` (ring by ring, far ring first).

#### Build physics for build_pilot / 20261125-150605-pilot_whistle80 (Tier 0 3D (design verified on Tier 1; these tables are Tier 0))

Source: `build/build_pilot-20261125-150605-pilot_whistle80/pack.json` key `physics`, computed by `echo.buildkit.physics_tables` from `runs/build_pilot/20261125-150605-pilot_whistle80/scene.json`. Levels are the clap-family mean echo peak in dB re the free-field direct clap at the listener (add 110.5 for dB SPL with a 100 dB clap at 1 m). Infinite free-space posts: -53.2 dB. Target band 1919-3553 Hz, echo from 20.2 to 96.5 ms.

Stage judges on the Tier 0 3D echo of the design as drawn: pitch_err_pct 2.91 [floor 2.53], spec_corr 0.784 [floor 0.976]. judge floor (the same judges on a physically perfect echo): pitch_err_pct 2.53 (single claps 1.86-3.86; threshold <= 3), spec_corr 0.976 (single claps 0.958-0.987; threshold >= 0.8). Every judged row below should be read against this floor, not against a perfect score.

**Readout** (evaluated by code from the tables below against the stage thresholds in metrics.json):

- Loudness: echo peak 55.8 dB SPL for a 100 dB clap; margin over the spec's 35 dB line +20.8 dB; over a 30 / 40 / 50 dB(A) background +26 / +16 / +6 dB (peak against background level: an optimistic comparison).
- Design as drawn on Tier 0 3D, free space: FAIL on Spectrogram correlation, log-mel [spec_corr] (pitch_err_pct 2.91 [floor 2.53], spec_corr 0.784 [floor 0.976]). judge floor (the same judges on a physically perfect echo): pitch_err_pct 2.53 (single claps 1.86-3.86; threshold <= 3), spec_corr 0.976 (single claps 0.958-0.987; threshold >= 0.8).
- Radial placement (seed-mean of 3 seeds): the spec's judges fail already at the smallest sigma tried; first failure at 1 mm on Pitch error along the note, worst frame [pitch_err_pct] 3.01 (2.96-3.07) [floor 2.53], Spectrogram correlation, log-mel [spec_corr] 0.717 (0.714-0.72) [floor 0.976], while the echo waveform is still 0.995 correlated with the nominal echo and its level changes +0.11 dB; where the residual lands is in the residual split below. Whether that judge failure is audible is a listening question (pack `listening/`).
- Tangential placement (along the equal-delay curve), sigma 50 mm: FAIL on Spectrogram correlation, log-mel [spec_corr] (pitch_err_pct 2.91 (2.91-2.91) [floor 2.53], spec_corr 0.774 (0.771-0.777) [floor 0.976]); waveform correlation 0.999.
- Post height, free space, ear 1.5 m: no finite height tried both passes the judges and stays within 1 dB of infinite posts.
- Rigid ground, clap and ear at 1.5 m: judges pass for 0 of 6 judged post heights; level change +0.4 to +4.4 dB, worst 10 ms window -4.5 dB.
- Rigid ground, clap and ear at 1 m: judges pass for 0 of 6 judged post heights; level change +1.9 to +4.7 dB, worst 10 ms window -12.1 dB.
- Rigid ground, clap and ear at 0.5 m: judges pass for 5 of 6 judged post heights (shortest 1 m); level change +1.8 to +2.3 dB, worst 10 ms window -5.1 dB.
- Rigid ground, clap and ear at 0.3 m: judges pass for 0 of 6 judged post heights; level change +4.3 to +5.2 dB, worst 10 ms window +2.9 dB.
- Partial wedge: no narrower slice tried passes the judges; fail at +-10, +-5, +-2.5 deg.
- Temperature (design tuned for c = 343 m/s): 0 C: FAIL on Pitch error along the note, worst frame [pitch_err_pct], Spectrogram correlation, log-mel [spec_corr] (pitch_err_pct 3.52 [floor 2.53], spec_corr 0.77 [floor 0.976]); 10 C: FAIL on Spectrogram correlation, log-mel [spec_corr] (pitch_err_pct 2.45 [floor 2.53], spec_corr 0.787 [floor 0.976]); 30 C: FAIL on Pitch error along the note, worst frame [pitch_err_pct], Spectrogram correlation, log-mel [spec_corr] (pitch_err_pct 4.07 [floor 2.53], spec_corr 0.769 [floor 0.976]).

Design geometry for the build: bistatic range 3.46-16.56 m; longest round trip 33.1 m; far edge 16.59 m from the clap point. 1:10 model: far edge 1.66 m from the emitter, keep hard surfaces beyond 2.16 m; time gate 1.72-10.65 ms model time (17.2-106.5 ms full scale: first echo - 3 ms to last echo + 10 ms). Site: a hard reflector at distance d from the clap point echoes at about 2d/c, so keep hard reflectors beyond c (last echo + 10 ms) / 2 = 18.3 m, so their echoes land after the analysis window. Board: see the template extent in the build pack line below.

Field-test (phase 3a) echo levels, Tier 0 3D, free space, ear 1.5 m:

| case | post height | dB re direct | dB SPL peak (100 dB clap) |
|---|---|---|---|
| single 20 mm post at 5 m | infinite | -61.0 | 49.4 |
| single 20 mm post at 5 m | 2 m | -59.9 | 50.5 |
| 30-post 3 kHz grating from 5 m, staggered | infinite | -54.4 | 56.1 |
| 30-post 3 kHz grating from 5 m, staggered | 2 m | -53.2 | 57.3 |

Echo level against post height, free space (no ground), clap and ear at 1.5 m:

| post height (m) | level (dB) | change (dB) | judges |
|---|---|---|---|
| 0.5 | -70.0 | -16.7 | pitch_err_pct 4.99 [floor 2.53], spec_corr 0.776 [floor 0.976] |
| 1 | -66.6 | -13.4 | pitch_err_pct 3.64 [floor 2.53], spec_corr 0.776 [floor 0.976] |
| 1.5 | -58.9 | -5.6 | pitch_err_pct 2.82 [floor 2.53], spec_corr 0.781 [floor 0.976] |
| 2 | -52.3 | +0.9 | pitch_err_pct 2.9 [floor 2.53], spec_corr 0.774 [floor 0.976] |
| 3 | -52.8 | +0.4 | pitch_err_pct 2.82 [floor 2.53], spec_corr 0.781 [floor 0.976] |
| infinite | -53.2 | +0.0 | pitch_err_pct 2.91 [floor 2.53], spec_corr 0.784 [floor 0.976] |

Echo level with a perfectly rigid flat ground (image method; posts stand on the ground, clap and ear at the same height):

| ear height (m) | post height (m) | level (dB) | change (dB) | worst / best 10 ms window (dB) | judges |
|---|---|---|---|---|---|
| 1.5 | 0.5 | -51.7 | +1.5 | -2.5 / +2.6 | pitch_err_pct 5.78 [floor 2.53], spec_corr 0.722 [floor 0.976] |
| 1.5 | 1 | -52.8 | +0.4 | -2.6 / +3.2 | pitch_err_pct 5.62 [floor 2.53], spec_corr 0.746 [floor 0.976] |
| 1.5 | 1.5 | -51.6 | +1.6 | -2.4 / +2.7 | pitch_err_pct 5.15 [floor 2.53], spec_corr 0.755 [floor 0.976] |
| 1.5 | 2 | -48.9 | +4.4 | -3.6 / +5.6 | pitch_err_pct 5.26 [floor 2.53], spec_corr 0.764 [floor 0.976] |
| 1.5 | 3 | -49.3 | +3.9 | -4.5 / +5.6 | pitch_err_pct 5.18 [floor 2.53], spec_corr 0.76 [floor 0.976] |
| 1.5 | infinite | -49.3 | +4.0 | -4.1 / +5.9 | pitch_err_pct 5.01 [floor 2.53], spec_corr 0.772 [floor 0.976] |
| 1 | 0.5 | -51.3 | +1.9 | -0.9 / +2.8 | pitch_err_pct 4.31 [floor 2.53], spec_corr 0.759 [floor 0.976] |
| 1 | 1 | -51.3 | +1.9 | -1.6 / +2.8 | pitch_err_pct 4.01 [floor 2.53], spec_corr 0.766 [floor 0.976] |
| 1 | 1.5 | -48.5 | +4.7 | -12.1 / +5.6 | pitch_err_pct 5.53 [floor 2.53], spec_corr 0.709 [floor 0.976] |
| 1 | 2 | -49.2 | +4.0 | -9.5 / +4.7 | pitch_err_pct 5.14 [floor 2.53], spec_corr 0.731 [floor 0.976] |
| 1 | 3 | -49.0 | +4.2 | -7.6 / +5.2 | pitch_err_pct 4.88 [floor 2.53], spec_corr 0.726 [floor 0.976] |
| 1 | infinite | -49.2 | +4.1 | -8.9 / +5.1 | pitch_err_pct 4.98 [floor 2.53], spec_corr 0.729 [floor 0.976] |
| 0.5 | 0.5 | -51.4 | +1.8 | -1.4 / +4.1 | pitch_err_pct 2.95 [floor 2.53], spec_corr 0.796 [floor 0.976] |
| 0.5 | 1 | -51.3 | +1.9 | -5.1 / +5.3 | pitch_err_pct 2.64 [floor 2.53], spec_corr 0.83 [floor 0.976] |
| 0.5 | 1.5 | -50.9 | +2.3 | -4.4 / +6.5 | pitch_err_pct 2.6 [floor 2.53], spec_corr 0.821 [floor 0.976] |
| 0.5 | 2 | -51.0 | +2.2 | -4.4 / +5.8 | pitch_err_pct 2.91 [floor 2.53], spec_corr 0.826 [floor 0.976] |
| 0.5 | 3 | -51.0 | +2.3 | -4.5 / +5.4 | pitch_err_pct 2.71 [floor 2.53], spec_corr 0.817 [floor 0.976] |
| 0.5 | infinite | -51.2 | +2.0 | -4.5 / +5.5 | pitch_err_pct 2.69 [floor 2.53], spec_corr 0.829 [floor 0.976] |
| 0.3 | 0.5 | -48.9 | +4.3 | +2.9 / +5.9 | pitch_err_pct 3.07 [floor 2.53], spec_corr 0.783 [floor 0.976] |
| 0.3 | 1 | -48.3 | +4.9 | +3.9 / +7.0 | pitch_err_pct 3.02 [floor 2.53], spec_corr 0.794 [floor 0.976] |
| 0.3 | 1.5 | -48.0 | +5.2 | +4.1 / +5.9 | pitch_err_pct 2.88 [floor 2.53], spec_corr 0.786 [floor 0.976] |
| 0.3 | 2 | -48.4 | +4.8 | +4.1 / +6.2 | pitch_err_pct 3.01 [floor 2.53], spec_corr 0.786 [floor 0.976] |
| 0.3 | 3 | -48.3 | +4.9 | +4.1 / +6.1 | pitch_err_pct 2.97 [floor 2.53], spec_corr 0.782 [floor 0.976] |
| 0.3 | infinite | -48.4 | +4.8 | +4.1 / +6.0 | pitch_err_pct 2.91 [floor 2.53], spec_corr 0.787 [floor 0.976] |

(in brackets: change against infinite free-space posts; 'worst 10 ms': the largest drop of any 10 ms window of the echo against the same window with infinite free-space posts, which shows comb notches that the peak hides)

Building only part of the wedge (posts with |bearing| up to the half-angle):

| half-angle (deg) | posts | level (dB) | change (dB) | judges |
|---|---|---|---|---|
| 20 | 500 | -53.2 | +0.0 | pitch_err_pct 2.91 [floor 2.53], spec_corr 0.784 [floor 0.976] |
| 10 | 500 | -53.2 | +0.0 | pitch_err_pct 2.91 [floor 2.53], spec_corr 0.784 [floor 0.976] |
| 5 | 247 | -50.3 | +2.9 | pitch_err_pct 22.8 [floor 2.53], spec_corr 0.482 [floor 0.976] |
| 2.5 | 117 | -53.9 | -0.7 | pitch_err_pct 32.5 [floor 2.53], spec_corr 0.444 [floor 0.976] |

Random placement error (Gaussian, every post, 3 seeds per sigma: mean and range), free-space infinite posts. Judge view: the spec's judges (with the judge floor). Physical view: measured waveform correlation with the nominal echo (clap-family mean of per-clap correlations), next to the parameter-free coherent-loss factor A = exp(-(4 pi sigma f / c)^2 / 2) at f = 2611 Hz (the fraction of coherent amplitude kept in the target band for RANGE errors; it says nothing about where the lost power goes, and it is not defined for tangential moves, printed '-'):

| direction | sigma (mm) | level change (dB) | waveform corr, measured | coherent factor A | judges (mean, range) |
|---|---|---|---|---|---|
| radial | 1 | +0.11 | 0.995 (0.994-0.996) | 0.995 | pitch_err_pct 3.01 (2.96-3.07) [floor 2.53], spec_corr 0.717 (0.714-0.72) [floor 0.976] |
| radial | 2 | +0.79 | 0.975 (0.971-0.979) | 0.982 | pitch_err_pct 3.45 (3.31-3.61) [floor 2.53], spec_corr 0.661 (0.653-0.67) [floor 0.976] |
| radial | 3 | +1.90 | 0.938 (0.929-0.945) | 0.960 | pitch_err_pct 4.88 (4.31-5.17) [floor 2.53], spec_corr 0.622 (0.616-0.629) [floor 0.976] |
| radial | 5 | +1.88 | 0.863 (0.846-0.877) | 0.892 | pitch_err_pct 13.2 (9.93-16.9) [floor 2.53], spec_corr 0.565 (0.54-0.589) [floor 0.976] |
| radial | 10 | +4.51 | 0.532 (0.441-0.650) | 0.633 | pitch_err_pct 26.5 (24.8-28.2) [floor 2.53], spec_corr 0.464 (0.449-0.473) [floor 0.976] |
| radial | 20 | +6.07 | 0.213 (0.149-0.248) | 0.160 | pitch_err_pct 47.4 (46.2-48.2) [floor 2.53], spec_corr 0.369 (0.351-0.38) [floor 0.976] |
| tangential | 50 | +0.06 | 0.999 (0.999-0.999) | - | pitch_err_pct 2.91 (2.91-2.91) [floor 2.53], spec_corr 0.774 (0.771-0.777) [floor 0.976] |

Residual split, this design: jitter-induced residual r = jittered echo - g x nominal (common gain g removed), energy split into four bands that partition 0-8 kHz: below the target band (< 1919 Hz), the target band (1919-3553 Hz, the same band as this section's 'Target band' line), above it to 4000 Hz, and above 4000 Hz; as % of the nominal echo energy; clap-family mean of per-clap values, mean over 3 seeds. The four columns sum to the total column. Check: residual/jittered energy equals 1 - corr^2 per clap.

| sigma (mm) | corr (clap mean) | below | in target band | above, to 4 kHz | above 4 kHz | total | above to 4 kHz, worst clap | max abs(1 - corr^2 - residual/jittered) |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.995 | 0.03 % | 0.91 % | 0.13 % | 0.01 % | 1.08 % | 0.37 % | 5.6e-16 |
| 2 | 0.975 | 0.18 % | 4.39 % | 0.55 % | 0.02 % | 5.14 % | 1.67 % | 7.2e-16 |
| 3 | 0.938 | 0.36 % | 10.62 % | 1.51 % | 0.07 % | 12.56 % | 4.46 % | 5.4e-16 |
| 5 | 0.863 | 0.96 % | 21.30 % | 2.95 % | 0.12 % | 25.34 % | 8.98 % | 2.5e-16 |
| 10 | 0.532 | 3.09 % | 62.74 % | 6.26 % | 0.26 % | 72.36 % | 17.45 % | 3.3e-16 |
| 20 | 0.213 | 7.07 % | 88.93 % | 11.66 % | 0.24 % | 107.90 % | 36.43 % | 4.4e-16 |

Nominal echo, per clap: share of energy in the target band 100 %, 100 %, 100 %, 99 %, 99 %; above it 0 %, 0 %, 0 %, 1 %, 0 %; peak level -53.9, -54.1, -54.8, -49.6, -53.7 dB re direct (claps 0-4).

Bias against modulation of the reflectivity profile (profile.json, active span): mean 0.3652, RMS modulation 0.2884, amplitude ratio 1.27, energy ratio 1.60.

Measurement noise: the judges on the nominal echo plus in-band white noise (band-limited to the design loss band), SNR = echo energy / noise energy over 20.1-106.5 ms, 3 seeds:

| SNR (dB) | judges (mean, seed range) |
|---|---|
| 10 | pitch_err_pct 5.22 (4-6.62) [floor 2.53], spec_corr 0.649 (0.645-0.652) [floor 0.976] |
| 15 | pitch_err_pct 3.47 (3.11-4.04) [floor 2.53], spec_corr 0.706 (0.704-0.709) [floor 0.976] |
| 20 | pitch_err_pct 3.02 (2.99-3.07) [floor 2.53], spec_corr 0.742 (0.741-0.745) [floor 0.976] |
| 25 | pitch_err_pct 2.94 (2.91-2.95) [floor 2.53], spec_corr 0.764 (0.762-0.766) [floor 0.976] |
| 30 | pitch_err_pct 2.89 (2.86-2.91) [floor 2.53], spec_corr 0.776 (0.776-0.777) [floor 0.976] |
| 40 | pitch_err_pct 2.9 (2.86-2.91) [floor 2.53], spec_corr 0.784 (0.784-0.784) [floor 0.976] |

**SNR gate**: no SNR in the table passes on every seed; measure at the highest SNR achievable.

**Phase-2c measurement height**: emitter and mic 50 mm above the model ground plane (= 0.5 m at full scale), the highest clap/ear height whose rigid-ground row with 2 m posts passes the judges; passing heights: 0.5 m. Also measure at 150 mm (1.5 m) as the ground-model check; its predicted verdict is in the ground table.

The built structure heard at other air temperatures (Tier 0 3D with c(T) = 331.3 sqrt(1 + T/273.15)):

| T (C) | c (m/s) | level (dB) | judges |
|---|---|---|---|
| 0 | 331.3 | -53.3 | pitch_err_pct 3.52 [floor 2.53], spec_corr 0.77 [floor 0.976] |
| 10 | 337.3 | -53.3 | pitch_err_pct 2.45 [floor 2.53], spec_corr 0.787 [floor 0.976] |
| 30 | 349.0 | -53.2 | pitch_err_pct 4.07 [floor 2.53], spec_corr 0.769 [floor 0.976] |

Range gradient |grad rho| over the posts: 0.9991-1.0000 (a radial error becomes that fraction of range error). A sideways error perpendicular to the line from the clap point (a bearing error) becomes range error at up to 0.043 of its size (median 0.014), largest on the near rows. Range period at 3553 Hz: 4.83 cm.

First Fresnel zone half-height sqrt(lambda rho / 2) at the target band edges:

| f (Hz) | rho (m) | half-height (m) |
|---|---|---|
| 1919 | 3.46 | 0.56 |
| 1919 | 16.56 | 1.22 |
| 3553 | 3.46 | 0.41 |
| 3553 | 16.56 | 0.89 |

1:10 model air absorption (ISO 9613-1, 20 C, 50 % RH) along the round trip 2 rho:

| model f (kHz) | full-scale rho (m) | model path (m) | model loss (dB) | full-scale loss at f/10 (dB) | excess (dB) |
|---|---|---|---|---|---|
| 5 | 3.46 | 0.69 | 0.03 | 0.02 | 0.01 |
| 5 | 16.56 | 3.31 | 0.15 | 0.09 | 0.06 |
| 10 | 3.46 | 0.69 | 0.11 | 0.03 | 0.08 |
| 10 | 16.56 | 3.31 | 0.53 | 0.15 | 0.37 |
| 20 | 3.46 | 0.69 | 0.36 | 0.07 | 0.29 |
| 20 | 16.56 | 3.31 | 1.74 | 0.33 | 1.41 |
| 30 | 3.46 | 0.69 | 0.65 | 0.13 | 0.52 |
| 30 | 16.56 | 3.31 | 3.10 | 0.60 | 2.50 |
| 40 | 3.46 | 0.69 | 0.91 | 0.21 | 0.71 |
| 40 | 16.56 | 3.31 | 4.37 | 0.98 | 3.38 |

Viscous boundary layer sqrt(2 nu / omega) against the smallest post radius: full scale at 3.55298 kHz: 37 um, 0.37 % of 10 mm; 1:10 model at 35.5298 kHz: 12 um, 1.16 % of 1 mm.

Temperature (pitch of the whole echo scales with c): 0 C: c = 331.3 m/s, -3.4 %; 10 C: c = 337.3 m/s, -1.7 %; 20 C: c = 343.2 m/s, +0.1 %; 30 C: c = 349.0 m/s, +1.8 %.

Build pack: `build/build_pilot-20261125-150605-pilot_whistle80/` (stakeout.csv, plan at 1:50 on A3, 1:10 template in 5 panels of 600 x 400 mm, full-size deck/template sheets: 24 of 2440 x 1220 mm, bom.md). BOM at 2.0 m posts: 500 posts of 20 mm, 1300 m of stock; model: 500 pins of 2 mm, 256 mm long (A_laser_plates, 128 m of rod) or 215 mm long (B_cnc_board, 108 m of rod). 1:10 hole field extent 1.64 m x 0.52 m (from the emitter mark).

#### Build physics for s1_bird / 20261125-104529-s1 (Tier 0 3D (design verified on Tier 1; these tables are Tier 0))

Source: `build/s1_bird-20261125-104529-s1/pack.json` key `physics`, computed by `echo.buildkit.physics_tables` from `runs/s1_bird/20261125-104529-s1/scene.json`. Levels are the clap-family mean echo peak in dB re the free-field direct clap at the listener (add 110.5 for dB SPL with a 100 dB clap at 1 m). Infinite free-space posts: -45.9 dB. Target band 1919-3553 Hz, echo from 19.6 to 96.6 ms.

Stage judges on the Tier 0 3D echo of the design as drawn: pitch_err_pct 2.91 [floor 2.53], spec_corr 0.873 [floor 0.976]. judge floor (the same judges on a physically perfect echo): pitch_err_pct 2.53 (single claps 1.86-3.86; threshold <= 3), spec_corr 0.976 (single claps 0.958-0.987; threshold >= 0.8). Every judged row below should be read against this floor, not against a perfect score.

**Readout** (evaluated by code from the tables below against the stage thresholds in metrics.json):

- Loudness: echo peak 61.6 dB SPL for a 100 dB clap; margin over the spec's 35 dB line +26.6 dB; over a 30 / 40 / 50 dB(A) background +32 / +22 / +12 dB (peak against background level: an optimistic comparison).
- Design as drawn on Tier 0 3D, free space: pass (pitch_err_pct 2.91 [floor 2.53], spec_corr 0.873 [floor 0.976]). judge floor (the same judges on a physically perfect echo): pitch_err_pct 2.53 (single claps 1.86-3.86; threshold <= 3), spec_corr 0.976 (single claps 0.958-0.987; threshold >= 0.8).
- Radial placement (seed-mean of 3 seeds): the spec's judges pass for every sigma up to 1 mm; first failure at 2 mm on Pitch error along the note, worst frame [pitch_err_pct] 3.11 (3.09-3.12) [floor 2.53], Spectrogram correlation, log-mel [spec_corr] 0.764 (0.763-0.765) [floor 0.976], while the echo waveform is still 0.993 correlated with the nominal echo and its level changes +0.23 dB; where the residual lands is in the residual split below. Whether that judge failure is audible is a listening question (pack `listening/`).
- Tangential placement (along the equal-delay curve), sigma 50 mm: pass (pitch_err_pct 2.93 (2.91-2.96) [floor 2.53], spec_corr 0.868 (0.868-0.869) [floor 0.976]); waveform correlation 1.000.
- Post height, free space, ear 1.5 m: shortest height within 1 dB of infinite posts with judges passing: 2 m.
- Rigid ground, clap and ear at 1.5 m: judges pass for 0 of 6 judged post heights; level change +1.2 to +4.6 dB, worst 10 ms window -4.0 dB.
- Rigid ground, clap and ear at 1 m: judges pass for 0 of 6 judged post heights; level change +1.0 to +5.3 dB, worst 10 ms window -12.9 dB.
- Rigid ground, clap and ear at 0.5 m: judges pass for 6 of 6 judged post heights (shortest 0.5 m); level change +2.3 to +3.2 dB, worst 10 ms window -4.6 dB.
- Rigid ground, clap and ear at 0.3 m: judges pass for 3 of 6 judged post heights (shortest 1.5 m); level change +4.9 to +5.8 dB, worst 10 ms window +2.4 dB.
- Partial wedge: no narrower slice tried passes the judges; fail at +-10, +-5, +-2.5 deg.
- Temperature (design tuned for c = 343 m/s): 0 C: FAIL on Pitch error along the note, worst frame [pitch_err_pct] (pitch_err_pct 3.52 [floor 2.53], spec_corr 0.854 [floor 0.976]); 10 C: pass (pitch_err_pct 2.45 [floor 2.53], spec_corr 0.872 [floor 0.976]); 30 C: FAIL on Pitch error along the note, worst frame [pitch_err_pct] (pitch_err_pct 4.07 [floor 2.53], spec_corr 0.859 [floor 0.976]).

Design geometry for the build: bistatic range 3.36-16.57 m; longest round trip 33.1 m; far edge 16.56 m from the clap point. 1:10 model: far edge 1.66 m from the emitter, keep hard surfaces beyond 2.16 m; time gate 1.66-10.66 ms model time (16.6-106.6 ms full scale: first echo - 3 ms to last echo + 10 ms). Site: a hard reflector at distance d from the clap point echoes at about 2d/c, so keep hard reflectors beyond c (last echo + 10 ms) / 2 = 18.3 m, so their echoes land after the analysis window. Board: see the template extent in the build pack line below.

Field-test (phase 3a) echo levels, Tier 0 3D, free space, ear 1.5 m:

| case | post height | dB re direct | dB SPL peak (100 dB clap) |
|---|---|---|---|
| single 20 mm post at 5 m | infinite | -61.0 | 49.4 |
| single 20 mm post at 5 m | 2 m | -59.9 | 50.5 |
| 30-post 3 kHz grating from 5 m, staggered | infinite | -54.4 | 56.1 |
| 30-post 3 kHz grating from 5 m, staggered | 2 m | -53.2 | 57.3 |

Echo level against post height, free space (no ground), clap and ear at 1.5 m:

| post height (m) | level (dB) | change (dB) | judges |
|---|---|---|---|
| 0.5 | -61.3 | -15.5 | pitch_err_pct 4.99 [floor 2.53], spec_corr 0.858 [floor 0.976] |
| 1 | -58.4 | -12.6 | pitch_err_pct 3.64 [floor 2.53], spec_corr 0.869 [floor 0.976] |
| 1.5 | -51.1 | -5.3 | pitch_err_pct 2.99 [floor 2.53], spec_corr 0.868 [floor 0.976] |
| 2 | -45.1 | +0.8 | pitch_err_pct 2.95 [floor 2.53], spec_corr 0.862 [floor 0.976] |
| 3 | -45.1 | +0.7 | pitch_err_pct 2.99 [floor 2.53], spec_corr 0.868 [floor 0.976] |
| infinite | -45.9 | +0.0 | pitch_err_pct 2.91 [floor 2.53], spec_corr 0.873 [floor 0.976] |

Echo level with a perfectly rigid flat ground (image method; posts stand on the ground, clap and ear at the same height):

| ear height (m) | post height (m) | level (dB) | change (dB) | worst / best 10 ms window (dB) | judges |
|---|---|---|---|---|---|
| 1.5 | 0.5 | -44.7 | +1.2 | -2.5 / +2.6 | pitch_err_pct 5.8 [floor 2.53], spec_corr 0.793 [floor 0.976] |
| 1.5 | 1 | -44.4 | +1.5 | -2.2 / +3.2 | pitch_err_pct 5.72 [floor 2.53], spec_corr 0.824 [floor 0.976] |
| 1.5 | 1.5 | -43.5 | +2.3 | -2.4 / +2.8 | pitch_err_pct 5.2 [floor 2.53], spec_corr 0.837 [floor 0.976] |
| 1.5 | 2 | -41.2 | +4.6 | -2.8 / +5.6 | pitch_err_pct 5.26 [floor 2.53], spec_corr 0.849 [floor 0.976] |
| 1.5 | 3 | -41.4 | +4.4 | -4.0 / +5.6 | pitch_err_pct 5.18 [floor 2.53], spec_corr 0.844 [floor 0.976] |
| 1.5 | infinite | -41.5 | +4.4 | -3.6 / +5.9 | pitch_err_pct 5.01 [floor 2.53], spec_corr 0.857 [floor 0.976] |
| 1 | 0.5 | -44.8 | +1.0 | -0.9 / +2.8 | pitch_err_pct 4.31 [floor 2.53], spec_corr 0.841 [floor 0.976] |
| 1 | 1 | -43.7 | +2.1 | -1.6 / +2.7 | pitch_err_pct 4.19 [floor 2.53], spec_corr 0.853 [floor 0.976] |
| 1 | 1.5 | -40.6 | +5.3 | -12.9 / +5.8 | pitch_err_pct 4.87 [floor 2.53], spec_corr 0.806 [floor 0.976] |
| 1 | 2 | -41.6 | +4.3 | -8.9 / +4.7 | pitch_err_pct 4.71 [floor 2.53], spec_corr 0.828 [floor 0.976] |
| 1 | 3 | -41.3 | +4.5 | -7.6 / +5.3 | pitch_err_pct 4.56 [floor 2.53], spec_corr 0.823 [floor 0.976] |
| 1 | infinite | -41.6 | +4.3 | -9.5 / +5.3 | pitch_err_pct 4.66 [floor 2.53], spec_corr 0.826 [floor 0.976] |
| 0.5 | 0.5 | -43.5 | +2.3 | -1.6 / +4.1 | pitch_err_pct 2.95 [floor 2.53], spec_corr 0.88 [floor 0.976] |
| 0.5 | 1 | -42.9 | +3.0 | -4.6 / +5.3 | pitch_err_pct 2.64 [floor 2.53], spec_corr 0.904 [floor 0.976] |
| 0.5 | 1.5 | -42.7 | +3.2 | -4.2 / +6.5 | pitch_err_pct 2.6 [floor 2.53], spec_corr 0.901 [floor 0.976] |
| 0.5 | 2 | -42.7 | +3.2 | -4.0 / +5.8 | pitch_err_pct 2.74 [floor 2.53], spec_corr 0.902 [floor 0.976] |
| 0.5 | 3 | -42.6 | +3.2 | -4.1 / +5.4 | pitch_err_pct 2.71 [floor 2.53], spec_corr 0.896 [floor 0.976] |
| 0.5 | infinite | -42.9 | +3.0 | -4.0 / +5.5 | pitch_err_pct 2.69 [floor 2.53], spec_corr 0.907 [floor 0.976] |
| 0.3 | 0.5 | -40.9 | +4.9 | +2.4 / +5.9 | pitch_err_pct 3.05 [floor 2.53], spec_corr 0.87 [floor 0.976] |
| 0.3 | 1 | -40.0 | +5.8 | +3.9 / +7.0 | pitch_err_pct 3.02 [floor 2.53], spec_corr 0.879 [floor 0.976] |
| 0.3 | 1.5 | -40.1 | +5.8 | +3.9 / +5.9 | pitch_err_pct 2.88 [floor 2.53], spec_corr 0.875 [floor 0.976] |
| 0.3 | 2 | -40.5 | +5.3 | +3.9 / +6.2 | pitch_err_pct 3.01 [floor 2.53], spec_corr 0.873 [floor 0.976] |
| 0.3 | 3 | -40.3 | +5.5 | +4.0 / +6.1 | pitch_err_pct 2.97 [floor 2.53], spec_corr 0.87 [floor 0.976] |
| 0.3 | infinite | -40.5 | +5.3 | +3.9 / +5.9 | pitch_err_pct 2.96 [floor 2.53], spec_corr 0.876 [floor 0.976] |

(in brackets: change against infinite free-space posts; 'worst 10 ms': the largest drop of any 10 ms window of the echo against the same window with infinite free-space posts, which shows comb notches that the peak hides)

Building only part of the wedge (posts with |bearing| up to the half-angle):

| half-angle (deg) | posts | level (dB) | change (dB) | judges |
|---|---|---|---|---|
| 20 | 1060 | -45.9 | +0.0 | pitch_err_pct 2.91 [floor 2.53], spec_corr 0.873 [floor 0.976] |
| 10 | 532 | -48.0 | -2.1 | pitch_err_pct 7.78 [floor 2.53], spec_corr 0.579 [floor 0.976] |
| 5 | 268 | -50.8 | -5.0 | pitch_err_pct 20.6 [floor 2.53], spec_corr 0.527 [floor 0.976] |
| 2.5 | 129 | -54.0 | -8.2 | pitch_err_pct 28 [floor 2.53], spec_corr 0.472 [floor 0.976] |

Random placement error (Gaussian, every post, 3 seeds per sigma: mean and range), free-space infinite posts. Judge view: the spec's judges (with the judge floor). Physical view: measured waveform correlation with the nominal echo (clap-family mean of per-clap correlations), next to the parameter-free coherent-loss factor A = exp(-(4 pi sigma f / c)^2 / 2) at f = 2611 Hz (the fraction of coherent amplitude kept in the target band for RANGE errors; it says nothing about where the lost power goes, and it is not defined for tangential moves, printed '-'):

| direction | sigma (mm) | level change (dB) | waveform corr, measured | coherent factor A | judges (mean, range) |
|---|---|---|---|---|---|
| radial | 1 | +0.00 | 0.999 (0.998-0.999) | 0.995 | pitch_err_pct 2.99 (2.95-3.02) [floor 2.53], spec_corr 0.828 (0.826-0.829) [floor 0.976] |
| radial | 2 | +0.23 | 0.993 (0.993-0.994) | 0.982 | pitch_err_pct 3.11 (3.09-3.12) [floor 2.53], spec_corr 0.764 (0.763-0.765) [floor 0.976] |
| radial | 3 | +0.28 | 0.985 (0.982-0.987) | 0.960 | pitch_err_pct 3.3 (3.14-3.43) [floor 2.53], spec_corr 0.723 (0.709-0.733) [floor 0.976] |
| radial | 5 | +0.08 | 0.960 (0.955-0.966) | 0.892 | pitch_err_pct 4.53 (4.32-4.66) [floor 2.53], spec_corr 0.65 (0.633-0.659) [floor 0.976] |
| radial | 10 | -0.59 | 0.822 (0.796-0.850) | 0.633 | pitch_err_pct 18.7 (16.7-20.2) [floor 2.53], spec_corr 0.556 (0.55-0.569) [floor 0.976] |
| radial | 20 | +0.59 | 0.272 (0.240-0.324) | 0.160 | pitch_err_pct 41.9 (36.3-49.3) [floor 2.53], spec_corr 0.41 (0.4-0.419) [floor 0.976] |
| tangential | 50 | -0.02 | 1.000 (1.000-1.000) | - | pitch_err_pct 2.93 (2.91-2.96) [floor 2.53], spec_corr 0.868 (0.868-0.869) [floor 0.976] |

Residual split, this design: jitter-induced residual r = jittered echo - g x nominal (common gain g removed), energy split into four bands that partition 0-8 kHz: below the target band (< 1919 Hz), the target band (1919-3553 Hz, the same band as this section's 'Target band' line), above it to 4000 Hz, and above 4000 Hz; as % of the nominal echo energy; clap-family mean of per-clap values, mean over 3 seeds. The four columns sum to the total column. Check: residual/jittered energy equals 1 - corr^2 per clap.

| sigma (mm) | corr (clap mean) | below | in target band | above, to 4 kHz | above 4 kHz | total | above to 4 kHz, worst clap | max abs(1 - corr^2 - residual/jittered) |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.999 | 0.01 % | 0.24 % | 0.03 % | 0.00 % | 0.28 % | 0.09 % | 3.9e-16 |
| 2 | 0.993 | 0.05 % | 1.12 % | 0.11 % | 0.01 % | 1.29 % | 0.35 % | 8.6e-16 |
| 3 | 0.985 | 0.08 % | 2.42 % | 0.37 % | 0.02 % | 2.90 % | 1.08 % | 5.3e-16 |
| 5 | 0.960 | 0.22 % | 5.27 % | 0.95 % | 0.03 % | 6.47 % | 2.95 % | 4.7e-16 |
| 10 | 0.822 | 0.64 % | 14.48 % | 1.42 % | 0.06 % | 16.60 % | 4.16 % | 5.0e-16 |
| 20 | 0.272 | 1.62 % | 23.73 % | 2.36 % | 0.06 % | 27.77 % | 6.83 % | 3.3e-16 |

Nominal echo, per clap: share of energy in the target band 100 %, 100 %, 100 %, 100 %, 100 %; above it 0 %, 0 %, 0 %, 0 %, 0 %; peak level -46.7, -45.5, -46.2, -41.9, -49.0 dB re direct (claps 0-4).

Bias against modulation of the reflectivity profile (profile.json, active span): mean 0.7742, RMS modulation 0.6107, amplitude ratio 1.27, energy ratio 1.61.

Measurement noise: the judges on the nominal echo plus in-band white noise (band-limited to the design loss band), SNR = echo energy / noise energy over 19.6-106.6 ms, 3 seeds:

| SNR (dB) | judges (mean, seed range) |
|---|---|
| 10 | pitch_err_pct 5.17 (4.25-6.36) [floor 2.53], spec_corr 0.686 (0.684-0.69) [floor 0.976] |
| 15 | pitch_err_pct 3.42 (3.12-3.92) [floor 2.53], spec_corr 0.757 (0.755-0.759) [floor 0.976] |
| 20 | pitch_err_pct 3.06 (3.04-3.07) [floor 2.53], spec_corr 0.804 (0.803-0.806) [floor 0.976] |
| 25 | pitch_err_pct 2.98 (2.95-3) [floor 2.53], spec_corr 0.835 (0.834-0.838) [floor 0.976] |
| 30 | pitch_err_pct 2.89 (2.85-2.91) [floor 2.53], spec_corr 0.855 (0.854-0.856) [floor 0.976] |
| 40 | pitch_err_pct 2.9 (2.86-2.91) [floor 2.53], spec_corr 0.871 (0.87-0.871) [floor 0.976] |

**SNR gate**: every seed passes from 25 dB up; with a 6 dB margin the measurement must reach **31 dB in-band SNR** over the echo window.

**Measurement margins** (physical-measurement gates only -- phases 2c and 3b; simulation verdicts use the spec thresholds with no margin): pitch_err_pct (threshold <= 3): m = 0.12 = noise repeatability 0.0344 (half the seed range at 30 dB SNR, 3 seeds) + c(T) error 0.0852 (thermometer +-0.5 C) -> PASS < 2.88; REPEAT 2.88 to 3.12; FAIL > 3.12; spec_corr (threshold >= 0.8): m = 0.00114 = noise repeatability 0.00114 (half the seed range at 30 dB SNR, 3 seeds) -> PASS > 0.801; REPEAT 0.799 to 0.801; FAIL < 0.799. REPEAT: average more, re-log temperature, measure again; a second REPEAT is reported as such, not rounded to a pass.

**Phase-2c measurement height**: emitter and mic 50 mm above the model ground plane (= 0.5 m at full scale), the highest clap/ear height whose rigid-ground row with 2 m posts passes the judges; passing heights: 0.5 m. Also measure at 150 mm (1.5 m) as the ground-model check; its predicted verdict is in the ground table.

Phase-3a SNR estimate (single hit of a 100 dB clap; peak echo SPL against a background level, an optimistic comparison; hits to average for the 31 dB gate = 10^((gate - SNR1)/10)):

| case | post height | echo peak dB SPL | background 25 dB: SNR1 / hits | 35 dB | 45 dB |
|---|---|---|---|---|---|
| single 20 mm post at 5 m | infinite | 49.4 | 24 dB / 5 | 14 dB / 46 | 4 dB / 453 |
| single 20 mm post at 5 m | 2 m | 50.5 | 26 dB / 4 | 16 dB / 36 | 6 dB / 353 |
| 30-post 3 kHz grating from 5 m, staggered | infinite | 56.1 | 31 dB / 1 | 21 dB / 10 | 11 dB / 98 |
| 30-post 3 kHz grating from 5 m, staggered | 2 m | 57.3 | 32 dB / 1 | 22 dB / 8 | 12 dB / 75 |

The built structure heard at other air temperatures (Tier 0 3D with c(T) = 331.3 sqrt(1 + T/273.15)):

| T (C) | c (m/s) | level (dB) | judges |
|---|---|---|---|
| 0 | 331.3 | -45.7 | pitch_err_pct 3.52 [floor 2.53], spec_corr 0.854 [floor 0.976] |
| 10 | 337.3 | -45.8 | pitch_err_pct 2.45 [floor 2.53], spec_corr 0.872 [floor 0.976] |
| 30 | 349.0 | -46.0 | pitch_err_pct 4.07 [floor 2.53], spec_corr 0.859 [floor 0.976] |

Range gradient |grad rho| over the posts: 0.9991-1.0000 (a radial error becomes that fraction of range error). A sideways error perpendicular to the line from the clap point (a bearing error) becomes range error at up to 0.043 of its size (median 0.013), largest on the near rows. Range period at 3553 Hz: 4.83 cm.

First Fresnel zone half-height sqrt(lambda rho / 2) at the target band edges:

| f (Hz) | rho (m) | half-height (m) |
|---|---|---|
| 1919 | 3.36 | 0.55 |
| 1919 | 16.57 | 1.22 |
| 3553 | 3.36 | 0.40 |
| 3553 | 16.57 | 0.89 |

1:10 model air absorption (ISO 9613-1, 20 C, 50 % RH) along the round trip 2 rho:

| model f (kHz) | full-scale rho (m) | model path (m) | model loss (dB) | full-scale loss at f/10 (dB) | excess (dB) |
|---|---|---|---|---|---|
| 5 | 3.36 | 0.67 | 0.03 | 0.02 | 0.01 |
| 5 | 16.57 | 3.31 | 0.15 | 0.09 | 0.06 |
| 10 | 3.36 | 0.67 | 0.11 | 0.03 | 0.08 |
| 10 | 16.57 | 3.31 | 0.53 | 0.15 | 0.37 |
| 20 | 3.36 | 0.67 | 0.35 | 0.07 | 0.29 |
| 20 | 16.57 | 3.31 | 1.74 | 0.33 | 1.41 |
| 30 | 3.36 | 0.67 | 0.63 | 0.12 | 0.51 |
| 30 | 16.57 | 3.31 | 3.10 | 0.60 | 2.50 |
| 40 | 3.36 | 0.67 | 0.89 | 0.20 | 0.69 |
| 40 | 16.57 | 3.31 | 4.37 | 0.98 | 3.39 |

Viscous boundary layer sqrt(2 nu / omega) against the smallest post radius: full scale at 3.55298 kHz: 37 um, 0.37 % of 10 mm; 1:10 model at 35.5298 kHz: 12 um, 1.16 % of 1 mm.

Temperature (pitch of the whole echo scales with c): 0 C: c = 331.3 m/s, -3.4 %; 10 C: c = 337.3 m/s, -1.7 %; 20 C: c = 343.2 m/s, +0.1 %; 30 C: c = 349.0 m/s, +1.8 %.

Build pack: `build/s1_bird-20261125-104529-s1/` (stakeout.csv, plan at 1:75 on A3, 1:10 template in 8 panels of 600 x 400 mm, full-size deck/template sheets: 42 of 2440 x 1220 mm, bom.md). BOM at 2.0 m posts: 1060 posts of 20 mm, 2756 m of stock; model: 1060 pins of 2 mm, 256 mm long (A_laser_plates, 271 m of rod) or 215 mm long (B_cnc_board, 228 m of rod). 1:10 hole field extent 1.65 m x 1.07 m (from the emitter mark).

#### Lower-pitch variant: placement tolerance (Tier 0, unverified, build variant, not a spec stage)

The stage-1 pipeline run on the same glide shifted down to 1750 -> 1000 Hz (80 ms): `build/variants/s1_bird/20261125-015144-s1low/` (3029 posts, depth 13.67 m, echo -51.9 dB re direct on Tier 0 3D). Judges with the stage-1 thresholds against the shifted target. Range period c/(2 f_top): 9.8 cm here against 4.8 cm for the stage-1 design.

- Design as drawn on Tier 0 3D, free space: pass (pitch_err_pct 2.06 [floor 1.65], spec_corr 0.825 [floor 0.971]). judge floor (the same judges on a physically perfect echo): pitch_err_pct 1.65 (single claps 0.503-3.09; threshold <= 3), spec_corr 0.971 (single claps 0.949-0.992; threshold >= 0.8).
- Radial placement (seed-mean of 3 seeds): the spec's judges fail already at the smallest sigma tried; first failure at 1 mm on Pitch error along the note, worst frame [pitch_err_pct] 21.4 (17.3-23.5) [floor 1.65], Spectrogram correlation, log-mel [spec_corr] 0.487 (0.481-0.497) [floor 0.971], while the echo waveform is still 0.933 correlated with the nominal echo and its level changes +1.31 dB; where the residual lands is in the residual split below. Whether that judge failure is audible is a listening question (pack `listening/`).
- Tangential placement (along the equal-delay curve), sigma 50 mm: FAIL on Spectrogram correlation, log-mel [spec_corr] (pitch_err_pct 2.28 (2.24-2.32) [floor 1.65], spec_corr 0.711 (0.707-0.718) [floor 0.971]); waveform correlation 0.989.

Random placement error (Gaussian, every post, 3 seeds per sigma: mean and range), free-space infinite posts. Judge view: the spec's judges (with the judge floor). Physical view: measured waveform correlation with the nominal echo (clap-family mean of per-clap correlations), next to the parameter-free coherent-loss factor A = exp(-(4 pi sigma f / c)^2 / 2) at f = 1323 Hz (the fraction of coherent amplitude kept in the target band for RANGE errors; it says nothing about where the lost power goes, and it is not defined for tangential moves, printed '-'):

| direction | sigma (mm) | level change (dB) | waveform corr, measured | coherent factor A | judges (mean, range) |
|---|---|---|---|---|---|
| radial | 1 | +1.31 | 0.933 (0.932-0.933) | 0.999 | pitch_err_pct 21.4 (17.3-23.5) [floor 1.65], spec_corr 0.487 (0.481-0.497) [floor 0.971] |
| radial | 2 | +4.14 | 0.811 (0.805-0.817) | 0.995 | pitch_err_pct 31.2 (29.5-34.3) [floor 1.65], spec_corr 0.326 (0.318-0.331) [floor 0.971] |
| radial | 3 | +5.03 | 0.731 (0.722-0.740) | 0.989 | pitch_err_pct 38.6 (37.5-39.9) [floor 1.65], spec_corr 0.237 (0.227-0.251) [floor 0.971] |
| radial | 5 | +7.38 | 0.611 (0.604-0.616) | 0.971 | pitch_err_pct 44 (38.7-46.7) [floor 1.65], spec_corr 0.122 (0.102-0.134) [floor 0.971] |
| radial | 10 | +10.10 | 0.437 (0.429-0.441) | 0.889 | pitch_err_pct 51.9 (51.9-51.9) [floor 1.65], spec_corr -0.025 (-0.0367--0.00926) [floor 0.971] |
| radial | 20 | +10.33 | 0.241 (0.228-0.250) | 0.625 | pitch_err_pct 51.9 (51.9-51.9) [floor 1.65], spec_corr -0.144 (-0.162--0.129) [floor 0.971] |
| tangential | 50 | +0.50 | 0.989 (0.989-0.990) | - | pitch_err_pct 2.28 (2.24-2.32) [floor 1.65], spec_corr 0.711 (0.707-0.718) [floor 0.971] |

Residual split, low-pitch variant: jitter-induced residual r = jittered echo - g x nominal (common gain g removed), energy split into four bands that partition 0-8 kHz: below the target band (< 924 Hz), the target band (924-1811 Hz, the same band as this section's 'Target band' line), above it to 4000 Hz, and above 4000 Hz; as % of the nominal echo energy; clap-family mean of per-clap values, mean over 3 seeds. The four columns sum to the total column. Check: residual/jittered energy equals 1 - corr^2 per clap.

| sigma (mm) | corr (clap mean) | below | in target band | above, to 4 kHz | above 4 kHz | total | above to 4 kHz, worst clap | max abs(1 - corr^2 - residual/jittered) |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.933 | 0.00 % | 0.05 % | 17.70 % | 0.04 % | 17.80 % | 60.96 % | 9.9e-16 |
| 2 | 0.811 | 0.00 % | 0.22 % | 85.26 % | 0.24 % | 85.72 % | 297.08 % | 5.9e-16 |
| 3 | 0.731 | 0.00 % | 0.68 % | 177.49 % | 0.46 % | 178.64 % | 625.75 % | 4.5e-16 |
| 5 | 0.611 | 0.00 % | 1.70 % | 414.92 % | 0.88 % | 417.50 % | 1361.28 % | 5.1e-16 |
| 10 | 0.437 | 0.00 % | 4.51 % | 1138.22 % | 1.56 % | 1144.29 % | 3864.64 % | 6.1e-16 |
| 20 | 0.241 | 0.00 % | 10.54 % | 1529.68 % | 1.99 % | 1542.22 % | 4882.36 % | 3.3e-16 |

Nominal echo, per clap: share of energy in the target band 97 %, 97 %, 99 %, 92 %, 100 %; above it 3 %, 3 %, 0 %, 7 %, 0 %; peak level -51.0, -57.4, -47.7, -59.4, -44.0 dB re direct (claps 0-4).

Bias against modulation of the reflectivity profile (profile.json, active span): mean 2.207, RMS modulation 1.807, amplitude ratio 1.22, energy ratio 1.49.

Bias-to-modulation amplitude ratio: stage-1 design 1.27, low-pitch variant 1.22.

**Reading-rule outcome at 1 mm** (generated): bias-to-modulation ratios 1.27 vs 1.22 (close: differ by 4 % against a 10 % rule), so (i) can act only through the clap spectrum. The variant's residual lies almost entirely above its target band (17.70 % above against 0.051 % in band) while the stage-1 residual stays mainly inside its band (0.24 % in band, 0.03 % above): this favours (ii). In-band, the variant's residual is 5x smaller than stage 1's. Sensitivity depends strongly on which clap is used: waveform correlation per clap (claps 0-4) at 1 mm, variant 0.969, 0.914, 0.994, 0.790, 0.997; stage-1 design 0.999, 0.999, 0.999, 0.998, 0.999.

<!-- END GENERATED -->
