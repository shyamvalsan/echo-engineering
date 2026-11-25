# Bill of materials: build_pilot 20261125-150605-pilot_whistle80

Post height above ground 2.0 m, embedment 0.6 m, spare 5 %. Quantities are computed from scene.json; stock items are suggestions (nearest standard sections), not quotes.

## Full scale

| dia (mm) | posts | +spare | length each (m) | total (m) | stock option | radius error (mm) | stock lengths | wind tip deflection at 10 m/s (mm) |
|---|---|---|---|---|---|---|---|---|
| 20 | 500 | 525 | 2.6 | 1365.0 | S235 smooth round bar, dia 20 mm (driven direct, cap the top) | 0.0 | 263 x 6.0 m | 1.75 |
| | | | | | B500 rebar, nominal 20 mm (ribs make it ~22-23 mm: prefer smooth bar) | 1.25 | 132 x 12.0 m | 1.23 |
| | | | | | steel tube DN15, 21.3 x 2.0 mm, galvanized | 0.65 | 263 x 6.0 m | 2.56 |
| | | | | | PVC-U conduit 20 mm (too flexible unless guyed - see deflection) | 0.0 | 525 x 3.0 m | 255.72 |

Wind deflection: steady 10 m/s, Cd 1.2, cantilever from a rigid foundation, static. Compare it with the radial placement budget in BUILD.md's generated block (Readout, 'Radial placement'); a post that deflects a sizeable fraction of that budget in the site's working wind needs a stiffer section or a top tie.

## 1:10 model (pins stand 200.0 mm above the ground plane)

Option A (laser): the ground plane is the top face of the upper guide plate; pins pass a 56 mm plate stack and rest on the base. Option B (CNC): ground = board top, holes 15 mm deep.

| dia (mm) | pins | +spare | option | pin length (mm) | total (m) | stock | stock lengths |
|---|---|---|---|---|---|---|---|
| 2.0 | 500 | 525 | A_laser_plates | 256.0 | 128.0 | dia 2.0 mm mild-steel TIG/gas filler rod in 1 m lengths, or 2 mm silver steel / brass / carbon-fibre rod | 175 x 1000 mm (3 pins each) |
| | | | B_cnc_board | 215.0 | 107.5 | dia 2.0 mm mild-steel TIG/gas filler rod in 1 m lengths, or 2 mm silver steel / brass / carbon-fibre rod | 132 x 1000 mm (4 pins each) |
