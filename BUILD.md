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
| 1. Desk (tonight) | Simulations and the build pack | 0 | done / ongoing | The design exists and scores in simulation. What tolerances, post height and ground it needs. | **Go to 2b:** the design passes on Tier 1, and the block's *Readout* shows the judges passing at radial sigma ≥ 2 mm (what the model can hold, ×10). **Otherwise** build 2a and 3a only, and let the robust pilot design (pending section) take the 2b slot. |
| 2a. Scale-model rig check (1:10) | Ultrasonic rig plus one pin, then a 40-row "grating" of pins | ~€0.7–1.5k (est.) | 1–2 weeks | The rig measures what Tier 0 predicts for a single post and for a pure tone, including 3D, the board as hard ground and real post height | Single pin: echo level within ±2 dB of Tier 0 (rigid ground, same heights). Grating: tone frequency within ±0.5 % of c/(2Δρ) at the measured c. |
| 2b. Full design at 1:10 | Every post of the design as 2 mm pins in laser-cut plates | +€0.3–0.6k (est.) | 1–2 weeks | The *design* works in 3D with ground, finite height and multiple scattering, and it can be heard (play back 10× slower) | Measured echo, scaled to full size and convolved with the clap family, **passes the stage's own thresholds** (stage 1: worst-frame pitch error ≤ 3 %, spectrogram correlation ≥ 0.8). Level within ±3 dB of prediction. |
| 3a. Field calibration (full scale) | 1 post, then a 30-post grating, on the candidate site | ~€0.2–0.5k (est.) | 2 days | Real ground (grass or hard), wind, background noise, the clap as heard | Single-post level within ±3 dB of the rigid-ground prediction on hard ground (state the offset on grass). Grating tone audible to 8 of 10 listeners at the planned ear height. |
| 3b. Full-scale pilot | The smallest worthwhile design (see the pending pilot section), on the site | ~€5–30k (est.: posts × per-post cost, see BOM) | 3–8 weeks | A clap returns the target sound outdoors | Judges pass on the measured echo at the measured air temperature. Level within ±3 dB of prediction. 8 of 10 naive listeners name the sound (bird / tune) from a forced choice of 4. |
| 4. Permanent installation | Durable version, longer pieces (motif, melody) | €50–500k (est.) | months | That it lasts, is safe and can be visited | Permissions, safety review and a maintenance plan in place. Phase-3b result repeated across seasons. |

**What to build first: 2a and 3a, in parallel, now.** Together they cost about €1–2k and take two weeks. They retire
the three risks that simulation cannot: 3D and ground physics, audibility next to a loud clap, and the real site. Neither
waits for the Tier 1 verdict, because neither depends on a particular design. 2b uses the same rig and needs only
laser-cut plates and rods, so the only thing that gates it is a design that is robust enough to build (rule above).
Do **not** buy full-scale posts for the current design. Its placement tolerance (block: *Readout*, "Radial placement")
decides whether it can be built at all. Section [Tolerance budget](#tolerance-budget) explains why.

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

**Free desk test, do it today.** Listen to `runs/<stage>/<run_id>/as_heard.wav` on headphones at a level where the clap
is loud but comfortable. The echo there is at its predicted level relative to the clap. If the note cannot be heard
clearly through the clap's after-effect, no build will fix that; see the loudness section.

---

## Phase 2: 1:10 ultrasonic scale model (tabletop)

**Why it works.** Wave physics has no length scale of its own, apart from absorption and viscosity. Divide every
length by 10 and multiply every frequency by 10, and the pressure field is the same, with time running 10× faster.
- The 500 Hz–4 kHz design band becomes 5–40 kHz.
- A 1 cm-radius post becomes a 1 mm-radius (2 mm diameter) pin. The catalog of 1, 2, 4 and 8 cm becomes pins of
  2, 4, 8 and 16 mm diameter.
- 3 m becomes 0.3 m, and the stage-1 structure fits on a 1.7 m × 1.2 m board.
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
  panels. Mount them 50–60 mm apart on spacers, over an 18 mm MDF base that the pins rest on. Two plates 50 mm apart
  hold a pin vertical to about (hole clearance)/50 mm. With 0.05 mm clearance, that is 1 mrad.
- *Baseboard (option B, CNC).* One 18–25 mm MDF or birch-ply board, CNC-drilled 15 mm deep at nominal diameter for a
  press fit. Same DXF.
- Butt the panels together and align them on the engraved crosshairs (REG layer, 100 mm model grid = 1 m at full
  scale). Holes that cross a joint are cut on both panels (layer HOLES_SPLIT) and close up when the panels are butted.
  The DXF is drawn as seen from the top face, not mirrored.
- *Pins.* One per post, length = post height ÷ 10 + 15 mm (`bom.md`, model table).
- *Surround.* The board's own top surface must continue to the clap and mic marks (the S and L marks on the
  template). Put acoustic foam or a heavy blanket on the table edges.
- *Space.* An echo from any surface at distance d arrives at 2d/c. Keep every hard surface (walls, ceiling, a person)
  farther from the emitter than the model's far edge plus 0.5 m. That is about 2.2 m for stage 1, so the room echoes
  arrive after the structure's echo has ended and can be time-gated out.

**Parts list (phase 2, ordering list).**

| Item | Spec | Qty | Cost (est.) | Notes |
|---|---|---|---|---|
| Pins, 2 mm | Ø2.0 mm mild-steel TIG/gas filler rod, 1 m lengths (sold in 5 kg tubes, about 200 m each), or Ø2 mm silver steel / brass / carbon-fibre rod | `bom.md` model table (×1.05 spare) | €15–35 per 5 kg tube (est.) | Cut 4 pins per metre with a bench-mounted cutter and a length stop. Roll each on glass and reject any that rock (bow > 0.1 mm). |
| Pins, 4 / 8 / 16 mm | silver steel, brass or aluminium rod; hardwood dowel for 8 and 16 mm | as `bom.md` | €1–5 per metre (est.) | Only if the design uses larger radii (stage 1 does not). |
| Guide plates | 3 mm cast acrylic or birch ply, 600 × 400 mm | 2 × panel count | €8–20 per acrylic sheet, €3–8 per ply sheet (est.) | Or a laser-cutting service: €50–150 per hour (est.); about 3,000 small circles is roughly 30–60 min of cutting per layer. |
| Base | 18 mm MDF, about 1.8 × 1.3 m, plus spacers | 1 | €30–60 (est.) | |
| Emitter, broadband (pick one) | (a) Avisoft Vifa ultrasonic dynamic speaker, 1–120 kHz ±12 dB, 92 dB SPL at 50 kHz (searched: spec only, price not found; ask Avisoft); (b) an air-motion-transformer or ribbon tweeter specified to 40 kHz; (c) a spark source: a gas-lighter piezo igniter or a small HV spark gap. It gives a 20–50 µs impulse, broadband past 100 kHz. | 1 | (a) a few hundred € (est.); (b) €50–150 (est.); (c) €5–50 (est.) | A 40 kHz ultrasonic transducer (€2) is narrowband (±1–2 kHz). It is usable only as a single-frequency check, never for the impulse response. Spark: HV safety, eye protection, no flammables. Shot-to-shot level varies by a few dB, so normalize each shot by its own direct sound. |
| Microphone (pick one) | (a) USB ultrasonic mic sampling at 384 kHz, e.g. Dodotronic Ultramic 384K EVO, €280 incl. VAT (searched, veldshop.nl, 2026-11-25); (b) Knowles SPU0410LR5H-class analog MEMS mic on a breakout (to about 80 kHz), into the interface; (c) a ¼-inch measurement mic rated to ≥50 kHz (several hundred €, est.) | 1 | see left | MEMS capsules have a resonance above 20 kHz. Calibrate it out by measuring the free direct sound at a fixed distance and dividing by it. |
| Audio interface | 2 in / 2 out at ≥192 kHz (e.g. a Focusrite Scarlett 4th gen or similar) | 1 | €150–250 (est.) | At 192 kHz, Nyquist is 96 kHz. Check the response to 40 kHz with an output-to-input loopback cable on day 1. |
| Small power amplifier | Class-D board, 10–20 W | 1 | €15–40 (est.) | For emitter (a) or (b). |
| Thermometer / hygrometer | ±0.5 °C, ±3 % RH | 1 | €15–30 (est.) | Needed for c and absorption. |
| Tools | Laser cutter or CNC (or a service), rod cutter with length stop, calipers, square, level | | | |

Total for phase 2a+2b: about €0.7–2k (est.), set mostly by the emitter and mic choice.

**Measurement procedure.**
1. Place the emitter's acoustic centre at S, at the chosen height (150 mm for a standing ear, 30–50 mm for the
   low-ear option). Place the mic at L, 30 mm from S at the same height.
2. *Stimulus.* Either a logarithmic sine sweep from 4 to 48 kHz over 1–2 s, repeated 8–16 times, deconvolved by the
   inverse sweep (Farina method), or repeated impulses (spark or a 20 µs click), 32–64 shots, aligned on their direct
   sound and averaged. Averaging N shots gains 10·log10(N) dB of SNR (+15 dB for 32).
3. *Normalization.* The direct arrival at 0.03 m is the reference. Divide the echo by the direct sound's spectrum.
   That is exactly the project's convention (echo relative to the direct clap at the listener), and it cancels the
   emitter and mic responses.
4. *Time gate.* Keep from 1.5 × the first echo delay ÷ 10 to the last echo delay ÷ 10 plus 1 ms. For stage 1 that is
   about 1.6–11 ms of model time (the block gives the full-scale echo window). Check that no room reflection lands
   inside the gate: run once with the pins removed, which is also the empty-scene baseline.
5. *Scale to full size.* Resample the measured impulse response so model time ×10 = full-scale time, and model
   frequency ÷10 = full-scale frequency. In practice, relabel the 192 kHz recording as 19.2 kHz, then resample to
   16 kHz. Convolve with the 5 claps of `echo.clap.clap_family` and score with the stage's judges.
   *(Tooling: a small `score_measurement` script is still to be written. It is not part of this task; see the report.)*
6. *Listen.* Play the raw 192 kHz recording at 19.2 kHz (10× slower). You hear the full-scale event: a clap and its
   echo, exactly as the full-size structure would return them. Do this before believing any number.
7. Repeat with the emitter and mic at 150 mm and at 30–50 mm, to test the ground predictions in the block.

**Pass / fail, and what to do on failure.**
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
- Then set a 30-post grating: 30 rows, 1 post per row on the axis, at range spacing c/(2·3000 Hz) = 5.7 cm, starting
  at 5 m. It should return a 3 kHz tone about 10 ms long. Listen and record.
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
  | 2 cm | Ø20 mm B500 rebar or smooth bar, or DN15 tube 21.3 mm |
  | 4 cm | DN32 tube 42.4 mm, or Ø40 bar |
  | 8 cm | 76.1 mm tube |
  | 16 cm | 160 mm PVC over a steel stake, or a 168.3 mm tube |

- Radius errors up to 1 mm match the spec's 1 mm radius-jitter case. Above that, rerun the realization with the stock
  radius before building.
- *Cost basis.* European rebar was about €700–750 per tonne ex-works in 2026 (searched, gmk.center, Oct 2026).
  Merchant cut-length prices run about 1.5–2× that, so €1.1–1.6 per kg (est.). Ø20 bar weighs 2.47 kg/m, so a
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
  - the judges pass on the measured response convolved with the clap family, after rescaling the predicted time
    axis by 343/c(T) (see temperature);
  - the level is within ±3 dB of prediction;
  - a forced-choice listening test with 10 naive listeners (target sound among 4 options) gets ≥ 8 correct.
- Fail:
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
   into the objective, with radial jitter at the budget sigma in the loss, so the design does not rely on exact bias
   cancellation. Also the chosen clap/ear height and ground (free space, or rigid deck) from the block's height
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
- That is why short structures (stage 1, about 34 m round trip) come first, why acceptance tests run in light wind,
  and why the melody's 137 m depth is a separate risk. The 3a grating repeated on calm and windy days measures it.
- Wind also bends posts. See `bom.md` for deflection, and pick stiff sections.

### Positional tolerance
- *Range is what matters.* A post's echo phase is 4πρ/λ. At 3.5 kHz the range period (one cycle of echo) is
  c/(2f) = 4.9 cm, so a 5 mm range error is a 37° phase error.
- Random errors of σ (in range) reduce the coherent echo by exp(−σφ²/2), where σφ = 4πσ/λ. Hand value: σ = 5 mm at
  3.5 kHz gives −1.8 dB.
- More importantly, they break the cancellation of the slowly varying positive bias. The design relies on that bias
  cancelling (spec: "the constraint that shapes everything"). Its scattered remainder becomes noise that fills the
  spectrogram. The block's jitter rows show both effects through the judges, and the waveform correlation shows how
  much of the echo survives.
- *Direction matters.* The gradient of ρ = (|P−S|+|P−L|)/2 is the mean of the two unit vectors from S and L to the
  post. Its magnitude is cos(β/2), with β the bistatic angle (block: "range gradient" line). So a radial error
  becomes a range error one for one.
- An error **along** the equal-delay ellipse changes the range only to second order (δ²/2r: 1 cm at 3 m is 0.02 mm).
  Tangential placement can be loose (the block tests 50 mm). Only the no-shadow and minimum-gap rules limit it.
  A sideways error measured from the clap point (a bearing error) is not quite along the ellipse, because S and L are
  0.3 m apart. It leaks into range at sin(β/2), a few percent on the near rows (block: "range gradient" line).
- The jitter rows use one random draw (seed 0). Treat a pass/fail right at a threshold as uncertain.
- *Lean.* The echo comes from the post near ear height. A post leaning by angle θ in the radial direction puts its
  ear-height section z·tanθ off. At z = 1.5 m, 1 mrad (0.06°) is 1.5 mm. At z = 0.3 m it is 0.3 mm. Low ears relax
  plumb tolerance 5×.
- *Systematic scale error* (tape calibration, temperature of the tape) scales all ranges and shifts pitch by the
  same fraction. A class-II steel tape is good to about ±4 mm over 20 m (0.02 %), and steel expands 0.023 % over
  20 K: negligible against 3 %.

---

## Tolerance budget

Radial (range) budget σ_total = the largest radial sigma at which the block's *Readout* says the judges still pass.
Split it by root-sum-square:

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

- **The clap masks its own echo.** The echo starts about 18 ms after a 110 dB click at the same ear (stage 1).
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
5. Larger posts: per post, 8 cm against 1 cm gives about +11 dB (Task 2 report, 3D, 10 m). Fewer, larger posts
   sample the waveform more coarsely and shadow more, so redesign is needed.

---

## Risk register (ranked by what would kill the project)

| # | Risk | Kills because | Cheapest test that retires it | Status / rule |
|---|---|---|---|---|
| 1 | **Placement tolerance is millimetric** | Thousands of posts outdoors can't hold sub-3 mm range accuracy by driving them | Desk: the jitter rows in the block (done, Tier 0) | If budget < 3 mm: CNC deck or a robust redesign (pilot agent). If < 1 mm: redesign before any purchase. |
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

Stage judges on the Tier 0 3D echo of the design as drawn: pitch_err_pct 2.78, spec_corr 0.944.

**Readout** (evaluated by code from the tables below against the stage thresholds in metrics.json):

- Loudness: echo peak 67.3 dB SPL for a 100 dB clap; margin over the spec's 35 dB line +32.3 dB; over a 30 / 40 / 50 dB(A) background +37 / +27 / +17 dB (peak against background level: an optimistic comparison).
- Design as drawn on Tier 0 3D, free space: judges pass.
- Radial placement: judges still pass at sigma = 1 mm; failing sigmas: 2 mm, 5 mm, 10 mm, 20 mm.
- Tangential placement (along the equal-delay curve), sigma 50 mm: judges pass.
- Post height, free space, ear 1.5 m: shortest height within 1 dB of infinite posts with judges passing: 2 m.
- Rigid ground, clap and ear at 1.5 m: judges pass for 0 of 6 post heights; level change +1.3 to +4.7 dB, worst 10 ms window -2.5 dB.
- Rigid ground, clap and ear at 1 m: judges pass for 0 of 6 post heights; level change +1.1 to +5.4 dB, worst 10 ms window -14.6 dB.
- Rigid ground, clap and ear at 0.5 m: judges pass for 6 of 6 post heights (shortest 0.5 m); level change +2.4 to +3.3 dB, worst 10 ms window -5.3 dB.
- Rigid ground, clap and ear at 0.3 m: judges pass for 5 of 6 post heights (shortest 0.5 m); level change +5.0 to +5.9 dB, worst 10 ms window +2.1 dB.
- Partial wedge: every narrower slice tried FAILS the judges (the arcs are not separable).
- Temperature: judges FAIL at 0 C, 30 C (design tuned for c = 343 m/s, 20 C).

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

Random placement error (Gaussian, every post, seed 0), free-space infinite posts:

| direction | sigma (mm) | level change (dB) | waveform correlation with the nominal echo | judges |
|---|---|---|---|---|
| radial | 1 | +0.02 | 0.998 | pitch_err_pct 2.88, spec_corr 0.853 |
| radial | 2 | +0.24 | 0.990 | pitch_err_pct 3.03, spec_corr 0.765 |
| radial | 5 | +0.88 | 0.931 | pitch_err_pct 6.18, spec_corr 0.623 |
| radial | 10 | +0.52 | 0.753 | pitch_err_pct 23.9, spec_corr 0.52 |
| radial | 20 | +1.40 | 0.139 | pitch_err_pct 47.9, spec_corr 0.382 |
| tangential | 50 | +0.02 | 1.000 | pitch_err_pct 2.78, spec_corr 0.93 |

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

Build pack: `build/s1_bird-20261125-013334-s1/` (stakeout.csv, plan at 1:75 on A3, 1:10 template in 8 panels of 600 x 400 mm, full-size deck/template sheets: 44 of 2440 x 1220 mm, bom.md). BOM at 2.0 m posts: 3029 posts of 20 mm, 7875 m of stock; model: 3029 pins of 2 mm x 215 mm (651 m of rod).

<!-- END GENERATED -->
