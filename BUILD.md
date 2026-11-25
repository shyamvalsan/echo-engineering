# BUILD: from simulation to a real echo structure

This is the plan for building a Composed Echo structure: a field of vertical posts that returns a hand clap as a
chosen sound. It covers what to build first, what to buy, how to measure it, and the number that decides each next step.
Every number that comes from simulation sits in the **generated block** at the end of this file
([Generated results](#generated-results-do-not-edit)). That block is rewritten by code from the run folders, so the
prose above it holds whatever the results turn out to be. Where a recommendation depends on a result, it is written as a
rule that points at a row of the block.

> **Status, 2026-11-25 night.** One design exists: the stage-1 bird note. It has run on the fast single-scattering
> model only (Tier 0). It is **unverified**: the full-wave referee (Tier 1) has not scored it yet. Treat every
> simulated number as "unverified, Tier 0" until the run table in the block says "yes, Tier 1".
> Refresh the block with `uv run python -m stages.build_pack --refresh-doc` (about 1 to 2 minutes per run).

Costs are **estimates**. Each one gives its basis and the date 2026-11-25. None of them is a supplier quote. The prices
that a web search confirmed are marked "(searched)". The rest are ranges from general knowledge of European retail
prices, marked "(est.)".

---

## Decision ladder (one page)

| Phase | What is built | Cost (order of magnitude) | Time | What it proves | Go / no-go number |
|---|---|---|---|---|---|
| 1. Desk (tonight) | Simulations and the build pack | 0 | done / ongoing | The design exists and scores in simulation. What tolerances, post height and ground it needs. | **Go to 2b:** the design passes on Tier 1, and the block's *Readout* shows the judges passing at radial sigma ≥ 2 mm (what the model can hold, ×10). **Otherwise** build 2a and 3a only, and let the robust pilot design (pending section) take the 2b slot. All judged gates in this table mean "passes the threshold, with the measurement's own SNR ≥ 30 dB in band, read against the judge floor in the block". |
| 2a. Scale-model rig check (1:10) | Ultrasonic rig plus one pin, then a 40-row "grating" of pins | ~€0.7–1.5k (est.) | 1–2 weeks | The rig measures what Tier 0 predicts for a single post and for a pure tone, including 3D, the board as hard ground and real post height | Single pin: echo level within ±2 dB of Tier 0 (rigid ground, same heights). Grating: tone frequency within ±0.5 % of c/(2Δρ) at the measured c. |
| 2b. Full design at 1:10 | Every post of the design as 2 mm pins in laser-cut plates | +€0.3–0.6k (est.) | 1–2 weeks | The *design* works in 3D with ground, finite height and multiple scattering, and it can be heard (play back 10× slower) | First: in-band SNR ≥ 30 dB over the echo window (else it is a noise result, not a structure result). Then the measured echo, temperature-corrected to c = 343 m/s, scaled to full size and convolved with the clap family, **passes the stage's own thresholds** (stage 1: worst-frame pitch error ≤ 3 %, spectrogram correlation ≥ 0.8) at the emitter/mic height whose rigid-ground row in the block passes. The judge floor is close to the pitch threshold, so a pitch result between the floor and the threshold counts as a pass only with listening agreement. Level within ±3 dB of prediction. |
| 3a. Field calibration (full scale) | 1 post, then a 30-post grating, on the candidate site | ~€0.2–0.5k (est.) | 2 days | Real ground (grass or hard), wind, background noise, the clap as heard | Single-post level within ±3 dB of the rigid-ground prediction on hard ground (state the offset on grass). Grating tone audible to 8 of 10 listeners at the planned ear height. |
| 3b. Full-scale pilot | The smallest worthwhile design (see the pending pilot section), on the site | ~€5–30k (est.: posts × per-post cost, see BOM) | 3–8 weeks | A clap returns the target sound outdoors | In-band SNR ≥ 30 dB. Judges pass on the measured echo after resampling it to c = 343 m/s (measured temperature), read against the judge floor. Level within ±3 dB of prediction. 8 of 10 naive listeners name the sound (bird / tune) from a forced choice of 4. |
| 4. Permanent installation | Durable version, longer pieces (motif, melody) | €50–500k (est.) | months | That it lasts, is safe and can be visited | Permissions, safety review and a maintenance plan in place. Phase-3b result repeated across seasons. |

**What to build first: 2a and 3a, in parallel, now.** Together they cost about €1–2k and take two weeks. They retire
the three risks that simulation cannot: 3D and ground physics, audibility next to a loud clap, and the real site. Neither
waits for the Tier 1 verdict, because neither depends on a particular design. 2b uses the same rig and needs only
laser-cut plates and rods, so the only thing that gates it is a design that is robust enough to build (rule above).
Do **not** buy full-scale posts for the current design, for two reasons:
- it is unverified on the full-wave solver;
- on Tier 0 it fails the spec's own spectrogram-correlation judge at a few millimetres of random placement error
  (block: *Readout*, "Radial placement").

That second reason is a judge result, not proof that the echo is lost. At the first failing sigma, the same block
line shows the echo waveform still almost fully correlated with the nominal one. The judge compares log-mel spectrograms
over a 60 dB range, so for a narrowband whistle a residual 20 dB down fills the empty bins and pulls the score down.
Whether that residual is audible is a listening question. The pack's `listening/` folder answers it for free (phase 1).
Until it is answered, treat the judge as binding.

**Target pitch, and the clap's bandwidth, set the tolerance.** The range period c/(2f) is 4.9 cm at 3.5 kHz but
16 cm at 1047 Hz (the motif's lowest note). Inside the target band, the allowed placement error scales with it. But
the posts reflect every frequency the clap contains, and the design must stay quiet outside the target band: its
positive bias cancels only through exact spacing. So the tolerance is set by the highest frequency that is both in the
clap and required to stay silent, not by the target alone.

The block's "Lower-pitch variant" section tests this. It is the bird glide shifted down to 1.75 → 1.0 kHz, run through
the same pipeline, judges and multi-seed jitter. Read its rows as a rule:
- If its radial budget is materially larger than stage 1's, lower pitch is the lever, and a lower-pitched glide is the
  recommended candidate for the pending pilot section.
- If it is not, and its "corr inside the target band" stays near 1 while the "echo energy outside the target band"
  grows with sigma, the limit is the clap's top octave, not the target. Then lowering the target helps only together
  with a band-limited source (a loudspeaker or a padded striker instead of a hand clap), a design that is robust to
  jitter outside the target band (penalize out-of-band energy under jitter in the loss), or less bias (see "ways to
  make it smaller or louder").

Low notes cost something regardless: posts scatter more weakly below ka ≈ 1, the clap has less energy there, and the
Fresnel zone, and with it the needed post height, grows as 1/√f.
Section [Tolerance budget](#tolerance-budget) gives both views: what the judge sees, and the coherence physics.

---

## Phase 1: desk (done tonight, continuing)

**Established, on Tier 0, unverified.**
- A field of 1 cm-radius posts can shape a clap into a falling whistle, with the pitch and spectrogram judges passing
  (block: run table).
- Its loudness, structure depth and post count (block: run table). These set the scale of every later phase.
- How the echo level depends on post height, with and without a hard ground, how it depends on placement error,
  wedge slicing and temperature, and what a 1:10 model loses to air absorption (block: physics tables). All of these
  use the 3D finite-height mode of the fast model, so they are free-space estimates, plus an image-method estimate
  for a perfectly rigid ground.

**Left open.**
- Whether the full-wave solver agrees (the tier gap), and whether multiple scattering in the field changes the
  sound. Tier 1 is running.
- The robustness sweep of `metrics.json`. The "robustness" column of the run table reads "not run" until it exists.
- Real ground impedance (grass), ground roughness, wind and turbulence, and human hearing next to a 110 dB clap.
  Phases 2 and 3 answer these.

**Free desk listening test, do it today.** Listen on headphones, at a level where the clap is loud but comfortable, to:
- `runs/<stage>/<run_id>/as_heard.wav`, where the echo is at its predicted level relative to the clap. If the note
  cannot be heard clearly through the clap's after-effect, no build will fix that; see the loudness section.
- `build/<stage>-<run_id>/listening/`, the same design with 0, 1, 2, 5 and 10 mm random radial placement error.
  These are the echo alone at one common gain, plus as-heard versions. If you cannot tell 2 mm from 0 mm, the judge
  failure at small sigma is not a practical limit, and the tolerance budget can be set by ear, preferably by several
  listeners blind.

---

## Phase 2: 1:10 ultrasonic scale model (tabletop)

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
  ratio, about 1 %. Its effect on scattering is of that order, below 0.1 dB. Ignore it.
- *Pin surface.* Rods are smooth to well under 0.1 mm, far below 1/10 of the 8.6 mm model wavelength at 40 kHz.
  Copper-coated welding rod is fine.

**What is built.**
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
  depth) (`bom.md`, model table). A pin cut to the option-B length and used in option A would stand only about 3/4 of
  the design height: about 1.5 m instead of 2 m at full scale, which the block's height table shows to be a large loss.
- *Surround.* The board's own top surface must continue to the clap and mic marks (the S and L marks on the
  template). Put acoustic foam or a heavy blanket on the table edges.
- *Space.* An echo from any surface at distance d arrives at 2d/c. Keep every hard surface (walls, ceiling, a person)
  farther from the emitter than the model's far edge plus 0.5 m (block: "Design geometry", model clearance), so the
  room echoes arrive after the structure's echo has ended and can be time-gated out.

**Parts list (phase 2, ordering list).**

| Item | Spec | Qty | Cost (est.) | Notes |
|---|---|---|---|---|
| Pins, 2 mm | Ø2.0 mm mild-steel TIG/gas filler rod, 1 m lengths (sold in 5 kg tubes, about 200 m each), or Ø2 mm silver steel / brass / carbon-fibre rod | `bom.md` model table (×1.05 spare) | €15–35 per 5 kg tube (est.) | Cut 4 pins per metre with a bench-mounted cutter and a length stop. Roll each on glass and reject any that rock (bow > 0.1 mm). |
| Pins, 4 / 8 / 16 mm | silver steel, brass or aluminium rod; hardwood dowel for 8 and 16 mm | as `bom.md` | €1–5 per metre (est.) | Only if the design uses larger radii (stage 1 does not). |
| Guide plates | 3 mm cast acrylic or birch ply, 600 × 400 mm | 2 × panel count | €8–20 per acrylic sheet, €3–8 per ply sheet (est.) | Or a laser-cutting service: €50–150 per hour (est.); about 3,000 small circles is roughly 30–60 min of cutting per layer. |
| Base | 18 mm MDF, about 1.8 × 1.3 m, plus spacers | 1 | €30–60 (est.) | |
| Emitter, broadband (pick one) | **(c) preferred:** a spark source, either a gas-lighter piezo igniter or a small HV spark gap. It gives a 20–50 µs impulse, broadband past 100 kHz, from a source a few mm across, so it is close to omnidirectional and can sit 30–50 mm above the board. (a) Avisoft Vifa ultrasonic dynamic speaker, 1–120 kHz ±12 dB, 92 dB SPL at 50 kHz (searched: spec only, price not found; ask Avisoft). (b) An air-motion-transformer or ribbon tweeter specified to 40 kHz. | 1 | (c) €5–50 (est.); (a) a few hundred € (est.); (b) €50–150 (est.) | (a) and (b) are several cm across. At 20–40 kHz (ka ≫ 1) they beam strongly, differ by tens of dB at 90° off axis, and their bodies scatter next to the mic. They cannot put an acoustic centre 30–50 mm above the board, so they are usable only for the 150 mm-height case and only with the on-axis calibration in step 3. A 40 kHz ultrasonic transducer (€2) is narrowband (±1–2 kHz): a single-frequency check only. Spark: HV safety, eye protection, no flammables; shot-to-shot level varies by a few dB, so normalize each shot by its own direct sound (valid for a spark, which is nearly omnidirectional, with a small MEMS capsule). |
| Microphone (pick one) | (a) USB ultrasonic mic sampling at 384 kHz, e.g. Dodotronic Ultramic 384K EVO, €280 incl. VAT (searched, veldshop.nl, 2026-11-25); (b) Knowles SPU0410LR5H-class analog MEMS mic on a breakout (to about 80 kHz), into the interface; (c) a ¼-inch measurement mic rated to ≥50 kHz (several hundred €, est.) | 1 | see left | Prefer a bare MEMS capsule (port about 1 mm) on a thin stalk: small enough to be nearly omnidirectional at 40 kHz, and it barely scatters. MEMS capsules have a resonance above 20 kHz; step 3 calibrates it out. A USB mic's housing is a scatterer, so mount it with its capsule end towards S on a thin rod. |
| Audio interface | 2 in / 2 out at ≥192 kHz (e.g. a Focusrite Scarlett 4th gen or similar) | 1 | €150–250 (est.) | At 192 kHz, Nyquist is 96 kHz. Check the response to 40 kHz with an output-to-input loopback cable on day 1. |
| Small power amplifier | Class-D board, 10–20 W | 1 | €15–40 (est.) | For emitter (a) or (b). |
| Thermometer / hygrometer | ±0.5 °C, ±3 % RH | 1 | €15–30 (est.) | Needed for c and absorption. |
| Tools | Laser cutter or CNC (or a service), rod cutter with length stop, calipers, square, level | | | |

Total for phase 2a+2b: about €0.7–2k (est.), set mostly by the emitter and mic choice.

**Measurement procedure.**
1. Place the emitter's acoustic centre at S and the mic at L, 30 mm from S, at the same height above the ground
   plane. Use the height whose rigid-ground row in the block passes the judges (the low-ear rows, ÷10). Then also
   measure at 150 mm (the standing-ear case). There the block predicts a judge failure from ground combing, and
   seeing that failure tests the ground model.
2. *Stimulus.* Either a logarithmic sine sweep from 4 to 48 kHz over 1–2 s, repeated 8–16 times, deconvolved by the
   inverse sweep (Farina method), or repeated impulses (spark or a 20 µs click), 32–64 shots, aligned on their direct
   sound and averaged. Averaging N shots gains 10·log10(N) dB of SNR (+15 dB for 32).
   *SNR requirement:* in-band SNR ≥ 30 dB over the echo window. Measure it as the echo-window energy against the
   same window of a recording with the stimulus off. A noise floor only 17–20 dB below the echo already fails the
   spectrogram judge on a perfect structure. Starting from a single-shot SNR, the number of shots needed is
   N = 10^((30 − SNR₁)/10). The block's field-test levels give the echo level to expect for 3a.
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
   correcting the prediction instead would leave the judges comparing a shifted echo with the fixed target. A 22–25 °C
   room is already +0.4–0.9 % in c, which is a large share of the stage-1 pitch margin. Then convolve with the 5 claps
   of `echo.clap.clap_family` and score with the stage's judges.
   *(Tooling: a small `score_measurement` script is still to be written. It is not part of this task; see the report.)*
6. *Listen.* Play the raw 192 kHz recording at 19.2 kHz (10× slower). You hear the full-scale event: a clap and its
   echo, exactly as the full-size structure would return them. Do this before believing any number.
7. Report every judged result next to the block's judge floor: the same judges on a physically perfect echo. Pitch
   in particular has a floor not far below its threshold.

**Pass / fail, and what to do on failure.** Check the failure branches in this order.
- Noise first: if the in-band SNR is below 30 dB, the run is not a result. Average more shots, use a quieter room,
  or use a louder source. Do not blame placement.
- Temperature second: check that the c(T) resampling was applied with a measured temperature.
- 2a: if the single pin is off by more than 2 dB, the rig is wrong, not the physics. Check the mic and emitter
  positions, gating, and the absorption correction. If the grating tone is off by more than 0.5 %, check the
  temperature reading and the pin spacing.
- 2b: if the judges fail but the level matches, it is a placement or design-tolerance problem. Photograph the board
  from above, measure where the pins actually stand, and rerun Tier 0 on the measured positions. If that also fails,
  the design is too fragile and goes back to the desk with the tolerance in the loss. If the level is far below
  prediction, multiple scattering or shadowing is stronger than the models assume. Report it, compare with Tier 1,
  and redesign at lower density.

---

## Phase 3: full scale outdoors

### 3a. Field calibration (do alongside phase 2)
- On the candidate site, drive **one** 20 mm steel bar 2 m tall at 5 m from a marked clap point. Measure its echo with
  a loudspeaker sweep, or with 20 claps or clapper-board hits, at ear heights 0.3, 0.5, 1.0 and 1.5 m. Compare with
  Tier 0 rigid-ground predictions for one post.
- Then set a 30-post grating: 30 posts at bistatic range 5 m + i·c/(2·3000 Hz) (5.7 cm steps). Their bearings cycle
  through −10, −6, −2, +2, +6 and +10°, each post on its own equal-delay ellipse, so no post stands in the forward
  shadow of the previous one. `echo.buildkit.grating_scene()` gives the coordinates. It should return a 3 kHz tone
  about 10 ms long. Listen and record.
- *Expected level and SNR.* The block's "Field-test echo levels" table gives the Tier 0 level of the single post and
  of the grating. Compare it with the site background to pick the number of averaged hits for 30 dB SNR (formula in
  phase 2, step 2).
- *Parts.* 30 × Ø20 mm bars of 2.5 m (one 12 m bar cuts into 4), a steel tape, a sledge or post driver, a
  measurement mic (class-2 omni, about €40–100, est.), a 48 kHz recorder, a small PA speaker, a thermometer, and an
  anemometer (about €20–40, est.). Roughly €200–500 (est.).
- This retires the ground question (grass against hard ground), the wind question and the "can I hear it next to
  the clap" question at about 1/100 of the cost of a pilot.

### 3b. Pilot structure

**Site requirements.**
- *Background.* LA90 during measurements at least 20 dB below the predicted echo peak SPL (block, run table). Rural
  quiet sites run about 25–35 dB(A), suburban 35–45, urban parks 45–55 (typical ranges, est.). Measure before
  choosing a site: one evening with a sound-level meter app or a class-2 meter.
- *Ground.* Flat to ±2 cm over the field. Hard ground (asphalt, concrete, rolled compacted gravel or a plywood deck)
  makes the image-method rows of the block apply. On grass, the ground reflection near grazing incidence is weaker
  and phase-shifted. Expect results between the free-space and rigid-ground rows, and measure it in 3a.
- *Clearance.* Every hard object (wall, car, tree trunk, fence) farther from the clap point than the far edge of the
  structure plus 17 m. Its echo then arrives more than 100 ms after the last designed echo. Nothing reflective behind
  the clapper within the same distance.
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
  (est.). Multiply by the BOM count. A few thousand posts is a five-figure sum, which is why the pilot must be a
  build-optimized design.

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
  itself (block: range gradient ≈ 1) and is the critical number. A bearing error moves the post sideways, which becomes range error at only a few percent of its size
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
  - in-band SNR ≥ 30 dB over the echo window (otherwise: more averaging or a louder source; not a structure result);
  - the judges pass on the measured response after resampling it in time by c(T)/343 (measured temperature) and
    convolving with the clap family, read against the block's judge floor;
  - the level is within ±3 dB of prediction;
  - a forced-choice listening test with 10 naive listeners (target sound among 4 options) gets ≥ 8 correct.
- Fail (check in this order):
  - noise: SNR below 30 dB; see above;
  - judges fail and the level matches: placement. Re-survey 50 random posts at ear height. If σ is over budget,
    fix those posts.
  - level low: compare with the 3a single post. If that was also low, it is the ground or the site, not the
    structure.

### Pilot design — pending full-wave verification

*To be filled by the pilot-design agent (`stages/build_pilot.py`) once Tier 1 is validated. Until then, this section
is a placeholder, and nothing in it is a result.*

The agent fills in:
1. **The constraints used.** Stock diameters nearest the catalog (from `bom.md`), a cap on post count (set it from
   the 3b budget: cost ≈ posts × per-post cost), and a minimum walk/mow spacing if feasible. Placement tolerance goes
   into the objective, with radial jitter at the budget sigma in the loss and a penalty on echo energy outside the
   target band under that jitter. That is what the low-pitch variant shows a design must survive. Also the chosen clap/ear height and ground (free space, or rigid deck) from the block's height
   tables.
2. **Run folder and verdict.** `runs/build_*/<run_id>/` with Tier 1 metrics, the tier gap and the robustness sweep,
   then `uv run python -m stages.build_pack --refresh-doc` so the run appears in the generated block with its
   readout.
3. **The finite-height and ground estimate** for the chosen post height (the physics check the stages lack).
4. **A one-paragraph recommendation:** post count, post height, ear height, ground, BOM total and cost, and which
   *Readout* lines pass.
5. **The 3b go/no-go**, restated with that design's numbers by reference to the block.

---

## Phase 4: permanent installation (outline)

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
- **Longer pieces.** The motif (about 31 m deep) and the melody (about 137 m) scale cost and land with depth (spec
  table). They also run into turbulence (below). Build them only after a stage-1 pilot passes outdoors.

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
  and why the melody's 137 m depth is a separate risk. The 3a grating repeated on calm and windy days measures it.
- Wind also bends posts. See `bom.md` for deflection, and pick stiff sections.

### Positional tolerance
- *Range is what matters.* A post's echo phase is 4πρ/λ. At 3.5 kHz the range period (one cycle of echo) is
  c/(2f) = 4.9 cm, so a 5 mm range error is a 37° phase error.
- Random errors of σ (in range) reduce the coherent echo by exp(−σφ²/2), where σφ = 4πσ/λ. Hand value: σ = 5 mm at
  3.5 kHz gives −1.8 dB.
- The lost coherent power reappears as incoherent scatter, at every frequency the posts reflect and the clap
  contains. That includes frequencies where the design is meant to be silent, because the bias cancels there only
  through exact spacing.
  - *Physical view:* the correlation with the nominal echo is about A/√(A² + G(1−A²)), with A = exp(−σφ²/2) and
    G ≈ 0.5 (a fit, an estimate).
  - *Judge view:* the spec's spectrogram correlation compares log-mel spectrograms over a 60 dB range, so even scatter
    20 dB down fills the empty time-frequency bins and pulls the score down.
  - The block's jitter tables show both views, plus the correlation inside the target band and the share of echo
    energy outside it. Those two columns separate "the note is damaged" from "noise appeared around the note".
- *Direction matters.* The gradient of ρ = (|P−S|+|P−L|)/2 is the mean of the two unit vectors from S and L to the
  post. Its magnitude is cos(β/2), with β the bistatic angle (block: "range gradient" line). So a radial error
  becomes a range error one for one.
- An error **along** the equal-delay ellipse changes the range only to second order (δ²/2r: 1 cm at 3 m is 0.02 mm).
  Tangential placement can be loose (the block tests 50 mm). Only the no-shadow and minimum-gap rules limit it.
  A sideways error measured from the clap point (a bearing error) is not quite along the ellipse, because S and L are
  0.3 m apart. It leaks into range at sin(β/2), a few percent on the near rows (block: "range gradient" line).
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
(judge view). If the free listening test finds the judge failures at small sigma inaudible, use a physical criterion
instead and log the deviation in DECISIONS.md: the largest sigma at which the in-target-band correlation stays ≥ 0.99
and the out-of-band energy share rises by less than a few percent. Split the budget by root-sum-square:

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
| Echo relative to direct (free space, infinite posts) | block: run table | Tier 0 3D, unverified; plus tier gap when Tier 1 exists |
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
| 1 | **Placement tolerance against the spec's judges** | If the judges' millimetre-level budget stands (and is audible), driven posts outdoors cannot hold it | Free: the pack's `listening/` files, judged by ear; Tier 0 multi-seed rows (done) | If the listening test confirms it: CNC deck, a design robust to jitter outside the target band, or a lower-pitched target together with a band-limited source (see "Target pitch, and the clap's bandwidth"). If it is inaudible: set the budget by ear and log the deviation from the judge. |
| 2 | 3D, finite-height, multiple scattering and ground differ from the models | The real echo is not the designed sound | 1:10 model, 2a + 2b (about €1–2k) | Open; Tier 1 tonight covers 2D multiple scattering only. |
| 3 | Echo inaudible next to the clap (forward masking, precedence) or in site noise | Nobody hears it even if it is right | Free desk listening test; then 3a on site | Open. Mitigation: start the structure farther away, a quieter site, a low ear over hard ground. |
| 4 | Real ground (grass) combs or cancels the echo | Pitch or level wrong at the ear | 3a single post at 4 ear heights (about €100) | Open. Hard surface or deck removes it. |
| 5 | Temperature drift of pitch | Absolute pitch fails off the design temperature | Desk (block temperature rows) | Accept relative pitch; acceptance at the measured c; design for the site's season. |
| 6 | Turbulence decorrelates the far rows | Long pieces (melody) smear | 3a grating on calm against windy days | Short pieces first. |
| 7 | Cost and labour scale with post count | Unaffordable or too slow to build | BOM (done) | Pilot design caps post count. |
| 8 | Tier 1 disagrees with Tier 0 | All numbers here move | Tier 1 run (tonight) | Refresh the block when it lands. |
| 9 | Safety and permissions | Cannot open to the public | A conversation with the landowner and the planning office | Phase 4. |

## Rough schedule and budget (estimates)

| Weeks | Work | Spend (est.) |
|---|---|---|
| 0–2 | 2a rig and 3a field calibration in parallel; desk: Tier 1 verdict and the robust pilot design | €1–2k |
| 2–4 | 2b full design at 1:10; scoring script | €0.3–0.6k |
| 4–10 | 3b pilot: site survey, deck or driven posts, build, acceptance | €5–30k plus labour (a few thousand posts at 2–5 min each with a 2-person crew is about 100–250 crew-hours, est.) |
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
uv run python -m stages.build_pack --refresh-doc          # all final / tier0_only runs, rewrites the block below
uv run python -m stages.build_pack runs/<stage>/<run_id>  # one build pack -> build/<stage>-<run_id>/
uv run python -m stages.build_pack --all --post-height 1.0 --panel 600x400 --paper A3
```

## Generated results (do not edit)

<!-- BEGIN GENERATED: stages/build_pack.py --refresh-doc. Do not edit by hand. -->

#### Runs found in `runs/index.json` (status final or tier0_only)

| stage | run | verified | posts | depth (m) | fill | echo dB re direct | echo dB SPL peak | gating metrics | robustness (delta per case) | source |
|---|---|---|---|---|---|---|---|---|---|---|
| s1_bird | 20261125-013334-s1 | no (unverified, Tier 0) | 3029 | 13.65 | 1.00 % | -43.2 | 67.3 | pitch_err_pct 2.56 (tier0, thr <= 3.0, pass); spec_corr 0.961 (tier0, thr >= 0.8, pass) | not run | `runs/s1_bird/20261125-013334-s1/metrics.json` |

#### Build physics for s1_bird / 20261125-013334-s1 (Tier 0, unverified)

Source: `build/s1_bird-20261125-013334-s1/pack.json` key `physics`, computed by `echo.buildkit.physics_tables` from `runs/s1_bird/20261125-013334-s1/scene.json`. Levels are the clap-family mean echo peak in dB re the free-field direct clap at the listener (add 110.5 for dB SPL with a 100 dB clap at 1 m). Infinite free-space posts: -43.2 dB. Target band 1919-3553 Hz, echo from 18.2 to 97.8 ms.

Stage judges on the Tier 0 3D echo of the design as drawn: pitch_err_pct 2.78, spec_corr 0.944. judge floor (the same judges on a physically perfect echo): pitch_err_pct 2.53 (single claps 1.86-3.86; threshold <= 3), spec_corr 0.976 (single claps 0.958-0.987; threshold >= 0.8). Every judged row below should be read against this floor, not against a perfect score.

**Readout** (evaluated by code from the tables below against the stage thresholds in metrics.json):

- Loudness: echo peak 67.3 dB SPL for a 100 dB clap; margin over the spec's 35 dB line +32.3 dB; over a 30 / 40 / 50 dB(A) background +37 / +27 / +17 dB (peak against background level: an optimistic comparison).
- Design as drawn on Tier 0 3D, free space: pass. judge floor (the same judges on a physically perfect echo): pitch_err_pct 2.53 (single claps 1.86-3.86; threshold <= 3), spec_corr 0.976 (single claps 0.958-0.987; threshold >= 0.8).
- Radial placement (seed-mean of 3 seeds): the spec's judges pass for every sigma up to 1 mm; first failure at 2 mm on Spectrogram correlation, log-mel [spec_corr] 0.768 (0.764-0.774), while the echo waveform is still 0.991 correlated with the nominal echo and its level changes +0.47 dB; inside the target band the correlation is 0.9918, and the share of echo energy outside the target band goes from 0.0 % to 0.1 %. Whether that judge failure is audible is a listening question (pack `listening/`).
- Tangential placement (along the equal-delay curve), sigma 50 mm: pass; waveform correlation 1.000.
- Post height, free space, ear 1.5 m: shortest height within 1 dB of infinite posts with judges passing: 2 m.
- Rigid ground, clap and ear at 1.5 m: judges pass for 0 of 6 judged post heights; level change +1.3 to +4.7 dB, worst 10 ms window -2.5 dB.
- Rigid ground, clap and ear at 1 m: judges pass for 0 of 6 judged post heights; level change +1.1 to +5.4 dB, worst 10 ms window -14.6 dB.
- Rigid ground, clap and ear at 0.5 m: judges pass for 6 of 6 judged post heights (shortest 0.5 m); level change +2.4 to +3.3 dB, worst 10 ms window -5.3 dB.
- Rigid ground, clap and ear at 0.3 m: judges pass for 5 of 6 judged post heights (shortest 0.5 m); level change +5.0 to +5.9 dB, worst 10 ms window +2.1 dB.
- Partial wedge: no narrower slice tried passes the judges; fail at +-10, +-5, +-2.5 deg.
- Temperature (design tuned for c = 343 m/s): 0 C: FAIL on Pitch error along the note, worst frame [pitch_err_pct]; 10 C: pass; 30 C: FAIL on Pitch error along the note, worst frame [pitch_err_pct].

Design geometry for the build: bistatic range 3.12-16.77 m; longest round trip 33.5 m; far edge 16.80 m from the clap point. 1:10 model: far edge 1.68 m from the emitter, keep hard surfaces beyond 2.18 m; time gate 1.52-10.78 ms model time (15.2-107.8 ms full scale: first echo - 3 ms to last echo + 10 ms). Site: no hard reflector within 34 m of the clap point. Board: see the template extent in the build pack line below.

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
| 0.5 | -58.6 | -15.4 | pitch_err_pct 4.84, spec_corr 0.922 |
| 1 | -55.8 | -12.6 | pitch_err_pct 3.4, spec_corr 0.94 |
| 1.5 | -48.4 | -5.2 | pitch_err_pct 2.73, spec_corr 0.94 |
| 2 | -42.3 | +0.9 | pitch_err_pct 2.84, spec_corr 0.938 |
| 3 | -42.4 | +0.8 | pitch_err_pct 2.73, spec_corr 0.94 |
| infinite | -43.2 | +0.0 | pitch_err_pct 2.78, spec_corr 0.944 |

Echo level with a perfectly rigid flat ground (image method; posts stand on the ground, clap and ear at the same height):

| ear height (m) | post height (m) | level (dB) | change (dB) | worst / best 10 ms window (dB) | judges |
|---|---|---|---|---|---|
| 1.5 | 0.5 | -41.9 | +1.3 | -2.5 / +2.7 | pitch_err_pct 5.66, spec_corr 0.874 |
| 1.5 | 1 | -41.6 | +1.6 | -2.5 / +3.1 | pitch_err_pct 5.58, spec_corr 0.891 |
| 1.5 | 1.5 | -40.7 | +2.4 | -2.0 / +3.0 | pitch_err_pct 5.03, spec_corr 0.903 |
| 1.5 | 2 | -38.5 | +4.7 | -0.7 / +5.4 | pitch_err_pct 4.99, spec_corr 0.912 |
| 1.5 | 3 | -38.7 | +4.5 | -2.2 / +5.5 | pitch_err_pct 4.94, spec_corr 0.904 |
| 1.5 | infinite | -38.7 | +4.4 | -1.8 / +5.8 | pitch_err_pct 4.94, spec_corr 0.922 |
| 1 | 0.5 | -42.1 | +1.1 | -0.9 / +2.6 | pitch_err_pct 4.14, spec_corr 0.92 |
| 1 | 1 | -41.0 | +2.2 | -1.5 / +2.3 | pitch_err_pct 4.02, spec_corr 0.926 |
| 1 | 1.5 | -37.8 | +5.4 | -14.6 / +6.1 | pitch_err_pct 4.64, spec_corr 0.889 |
| 1 | 2 | -38.8 | +4.4 | -8.0 / +5.1 | pitch_err_pct 4.5, spec_corr 0.903 |
| 1 | 3 | -38.6 | +4.6 | -8.5 / +5.5 | pitch_err_pct 4.43, spec_corr 0.895 |
| 1 | infinite | -38.8 | +4.4 | -11.2 / +5.6 | pitch_err_pct 4.44, spec_corr 0.906 |
| 0.5 | 0.5 | -40.8 | +2.4 | -1.6 / +4.1 | pitch_err_pct 2.76, spec_corr 0.954 |
| 0.5 | 1 | -40.2 | +3.0 | -4.8 / +5.2 | pitch_err_pct 2.52, spec_corr 0.964 |
| 0.5 | 1.5 | -39.9 | +3.3 | -4.4 / +6.6 | pitch_err_pct 2.49, spec_corr 0.961 |
| 0.5 | 2 | -39.8 | +3.3 | -4.9 / +5.8 | pitch_err_pct 2.74, spec_corr 0.958 |
| 0.5 | 3 | -39.8 | +3.3 | -5.3 / +5.4 | pitch_err_pct 2.62, spec_corr 0.948 |
| 0.5 | infinite | -40.1 | +3.1 | -5.3 / +5.4 | pitch_err_pct 2.52, spec_corr 0.965 |
| 0.3 | 0.5 | -38.2 | +5.0 | +2.1 / +5.9 | pitch_err_pct 2.81, spec_corr 0.948 |
| 0.3 | 1 | -37.2 | +5.9 | +3.8 / +6.9 | pitch_err_pct 2.66, spec_corr 0.95 |
| 0.3 | 1.5 | -37.3 | +5.9 | +3.9 / +6.0 | pitch_err_pct 2.88, spec_corr 0.947 |
| 0.3 | 2 | -37.8 | +5.4 | +3.8 / +6.2 | pitch_err_pct 3.01, spec_corr 0.944 |
| 0.3 | 3 | -37.6 | +5.6 | +3.8 / +6.2 | pitch_err_pct 2.81, spec_corr 0.94 |
| 0.3 | infinite | -37.8 | +5.4 | +3.8 / +5.9 | pitch_err_pct 2.76, spec_corr 0.948 |

(in brackets: change against infinite free-space posts; 'worst 10 ms': the largest drop of any 10 ms window of the echo against the same window with infinite free-space posts, which shows comb notches that the peak hides)

Building only part of the wedge (posts with |bearing| up to the half-angle):

| half-angle (deg) | posts | level (dB) | change (dB) | judges |
|---|---|---|---|---|
| 20 | 3029 | -43.2 | +0.0 | pitch_err_pct 2.78, spec_corr 0.944 |
| 10 | 1507 | -46.7 | -3.5 | pitch_err_pct 12.2, spec_corr 0.569 |
| 5 | 754 | -47.7 | -4.5 | pitch_err_pct 24, spec_corr 0.497 |
| 2.5 | 373 | -50.4 | -7.3 | pitch_err_pct 26.9, spec_corr 0.448 |

Random placement error (Gaussian, every post, 3 seeds per sigma: mean and range), free-space infinite posts. Judge view: the spec's judges. Physical view: waveform correlation with the nominal echo, measured, and the coherence estimate A / sqrt(A^2 + 0.5 (1 - A^2)), A = exp(-sigma_phi^2 / 2), sigma_phi = 4 pi sigma f / c at f = 2611 Hz:

| direction | sigma (mm) | level change (dB) | waveform corr, measured | waveform corr, coherence estimate | corr inside the target band | echo energy outside the target band | judges (mean, range) |
|---|---|---|---|---|---|---|---|
| nominal | 0 | +0.00 | 1.000 (1.000-1.000) | - | 1.0000 | 0.0 % | as drawn (above) |
| radial | 1 | +0.11 | 0.998 (0.998-0.998) | 0.998 | 0.9981 | 0.1 % | pitch_err_pct 2.75 (2.67-2.81), spec_corr 0.852 (0.846-0.859) |
| radial | 2 | +0.47 | 0.991 (0.991-0.992) | 0.991 | 0.9918 | 0.1 % | pitch_err_pct 2.84 (2.83-2.86), spec_corr 0.768 (0.764-0.774) |
| radial | 3 | +0.43 | 0.981 (0.980-0.983) | 0.979 | 0.9824 | 0.3 % | pitch_err_pct 3.27 (3.22-3.32), spec_corr 0.716 (0.71-0.721) |
| radial | 5 | +1.10 | 0.943 (0.936-0.947) | 0.941 | 0.9473 | 0.8 % | pitch_err_pct 4.97 (4.51-5.39), spec_corr 0.64 (0.636-0.644) |
| radial | 10 | +0.82 | 0.767 (0.754-0.779) | 0.756 | 0.7774 | 2.7 % | pitch_err_pct 22.1 (21-22.9), spec_corr 0.541 (0.539-0.542) |
| radial | 20 | +2.50 | 0.194 (0.144-0.274) | 0.224 | 0.2012 | 5.6 % | pitch_err_pct 46.7 (42-49.3), spec_corr 0.401 (0.394-0.408) |
| tangential | 50 | +0.07 | 1.000 (1.000-1.000) | - | 0.9996 | 0.0 % | pitch_err_pct 2.77 (2.76-2.78), spec_corr 0.927 (0.925-0.928) |

The built structure heard at other air temperatures (Tier 0 3D with c(T) = 331.3 sqrt(1 + T/273.15)):

| T (C) | c (m/s) | level (dB) | judges |
|---|---|---|---|
| 0 | 331.3 | -43.0 | pitch_err_pct 3.6, spec_corr 0.908 |
| 10 | 337.3 | -43.1 | pitch_err_pct 2.63, spec_corr 0.934 |
| 30 | 349.0 | -43.3 | pitch_err_pct 3.71, spec_corr 0.935 |

Range gradient |grad rho| over the posts: 0.9989-1.0000 (a radial error becomes that fraction of range error). A sideways error perpendicular to the line from the clap point (a bearing error) becomes range error at up to 0.047 of its size (median 0.013), largest on the near rows. Range period at 3553 Hz: 4.83 cm.

First Fresnel zone half-height sqrt(lambda rho / 2) at the target band edges:

| f (Hz) | rho (m) | half-height (m) |
|---|---|---|
| 1919 | 3.12 | 0.53 |
| 1919 | 16.77 | 1.22 |
| 3553 | 3.12 | 0.39 |
| 3553 | 16.77 | 0.90 |

1:10 model air absorption (ISO 9613-1, 20 C, 50 % RH) along the round trip 2 rho:

| model f (kHz) | full-scale rho (m) | model path (m) | model loss (dB) | full-scale loss at f/10 (dB) | excess (dB) |
|---|---|---|---|---|---|
| 5 | 3.12 | 0.62 | 0.03 | 0.02 | 0.01 |
| 5 | 16.77 | 3.35 | 0.15 | 0.09 | 0.06 |
| 10 | 3.12 | 0.62 | 0.10 | 0.03 | 0.07 |
| 10 | 16.77 | 3.35 | 0.53 | 0.16 | 0.38 |
| 20 | 3.12 | 0.62 | 0.33 | 0.06 | 0.27 |
| 20 | 16.77 | 3.35 | 1.76 | 0.33 | 1.43 |
| 30 | 3.12 | 0.62 | 0.58 | 0.11 | 0.47 |
| 30 | 16.77 | 3.35 | 3.14 | 0.61 | 2.53 |
| 40 | 3.12 | 0.62 | 0.82 | 0.18 | 0.64 |
| 40 | 16.77 | 3.35 | 4.42 | 0.99 | 3.43 |

Viscous boundary layer sqrt(2 nu / omega) against the smallest post radius: full scale at 3.55298 kHz: 37 um, 0.37 % of 10 mm; 1:10 model at 35.5298 kHz: 12 um, 1.16 % of 1 mm.

Temperature (pitch of the whole echo scales with c): 0 C: c = 331.3 m/s, -3.4 %; 10 C: c = 337.3 m/s, -1.7 %; 20 C: c = 343.2 m/s, +0.1 %; 30 C: c = 349.0 m/s, +1.8 %.

Build pack: `build/s1_bird-20261125-013334-s1/` (stakeout.csv, plan at 1:75 on A3, 1:10 template in 8 panels of 600 x 400 mm, full-size deck/template sheets: 44 of 2440 x 1220 mm, bom.md). BOM at 2.0 m posts: 3029 posts of 20 mm, 7875 m of stock; model: 3029 pins of 2 mm, 256 mm long (A_laser_plates, 775 m of rod) or 215 mm long (B_cnc_board, 651 m of rod). 1:10 hole field extent 1.67 m x 1.12 m (from the emitter mark).

#### Lower-pitch variant: placement tolerance (Tier 0, unverified, build variant, not a spec stage)

The stage-1 pipeline run on the same glide shifted down to 1750 -> 1000 Hz (80 ms): `build/variants/s1_bird/20261125-015144-s1low/` (3029 posts, depth 13.67 m, echo -51.9 dB re direct on Tier 0 3D). Judges with the stage-1 thresholds against the shifted target. Range period c/(2 f_top): 9.8 cm here against 4.8 cm for the stage-1 design.

- Design as drawn on Tier 0 3D, free space: pass. judge floor (the same judges on a physically perfect echo): pitch_err_pct 1.65 (single claps 0.503-3.09; threshold <= 3), spec_corr 0.971 (single claps 0.949-0.992; threshold >= 0.8).
- Radial placement (seed-mean of 3 seeds): the spec's judges fail already at the smallest sigma tried; first failure at 1 mm on Pitch error along the note, worst frame [pitch_err_pct] 21.4 (17.3-23.5), Spectrogram correlation, log-mel [spec_corr] 0.487 (0.481-0.497), while the echo waveform is still 0.933 correlated with the nominal echo and its level changes +1.31 dB; inside the target band the correlation is 0.9996, and the share of echo energy outside the target band goes from 1.1 % to 3.4 %. Whether that judge failure is audible is a listening question (pack `listening/`).
- Tangential placement (along the equal-delay curve), sigma 50 mm: FAIL on Spectrogram correlation, log-mel [spec_corr]; waveform correlation 0.989.

Random placement error (Gaussian, every post, 3 seeds per sigma: mean and range), free-space infinite posts. Judge view: the spec's judges. Physical view: waveform correlation with the nominal echo, measured, and the coherence estimate A / sqrt(A^2 + 0.5 (1 - A^2)), A = exp(-sigma_phi^2 / 2), sigma_phi = 4 pi sigma f / c at f = 1323 Hz:

| direction | sigma (mm) | level change (dB) | waveform corr, measured | waveform corr, coherence estimate | corr inside the target band | echo energy outside the target band | judges (mean, range) |
|---|---|---|---|---|---|---|---|
| nominal | 0 | +0.00 | 1.000 (1.000-1.000) | - | 1.0000 | 1.1 % | as drawn (above) |
| radial | 1 | +1.31 | 0.933 (0.932-0.933) | 0.999 | 0.9996 | 3.4 % | pitch_err_pct 21.4 (17.3-23.5), spec_corr 0.487 (0.481-0.497) |
| radial | 2 | +4.14 | 0.811 (0.805-0.817) | 0.998 | 0.9982 | 11.5 % | pitch_err_pct 31.2 (29.5-34.3), spec_corr 0.326 (0.318-0.331) |
| radial | 3 | +5.03 | 0.731 (0.722-0.740) | 0.995 | 0.9943 | 20.5 % | pitch_err_pct 38.6 (37.5-39.9), spec_corr 0.237 (0.227-0.251) |
| radial | 5 | +7.38 | 0.611 (0.604-0.616) | 0.985 | 0.9877 | 38.8 % | pitch_err_pct 44 (38.7-46.7), spec_corr 0.122 (0.102-0.134) |
| radial | 10 | +10.10 | 0.437 (0.429-0.441) | 0.940 | 0.9510 | 69.3 % | pitch_err_pct 51.9 (51.9-51.9), spec_corr -0.025 (-0.0367--0.00926) |
| radial | 20 | +10.33 | 0.241 (0.228-0.250) | 0.750 | 0.7458 | 87.5 % | pitch_err_pct 51.9 (51.9-51.9), spec_corr -0.144 (-0.162--0.129) |
| tangential | 50 | +0.50 | 0.989 (0.989-0.990) | - | 0.9998 | 1.4 % | pitch_err_pct 2.28 (2.24-2.32), spec_corr 0.711 (0.707-0.718) |

<!-- END GENERATED -->
