# Bill of materials: s1_bird 20261125-013334-s1

Post height above ground 2.0 m, embedment 0.6 m, spare 5 %. Quantities are computed from scene.json; stock items are suggestions (nearest standard sections), not quotes.

## Full scale

| dia (mm) | posts | +spare | length each (m) | total (m) | stock option | radius error (mm) | stock lengths | wind tip deflection at 10 m/s (mm) |
|---|---|---|---|---|---|---|---|---|
| 20 | 3029 | 3181 | 2.6 | 8270.6 | B500 rebar, nominal dia 20 mm (driven direct, cap the top) | 0.0 | 796 x 12.0 m | 1.75 |
| | | | | | steel tube DN15, 21.3 x 2.0 mm, galvanized | 0.65 | 1591 x 6.0 m | 2.56 |
| | | | | | PVC-U conduit 20 mm (too flexible unless guyed - see deflection) | 0.0 | 3181 x 3.0 m | 255.72 |

Wind deflection: steady 10 m/s, Cd 1.2, cantilever from a rigid foundation, static. The radial placement budget is about 5 mm (BUILD.md), so a post that deflects more than a few mm in the site's working wind needs a stiffer section or a top tie.

## 1:10 model (pins 200.0 mm above the board + 15.0 mm in the board)

| dia (mm) | pins | +spare | pin length (mm) | total (m) | stock | stock lengths |
|---|---|---|---|---|---|---|
| 2.0 | 3029 | 3181 | 215.0 | 651.2 | dia 2.0 mm mild-steel TIG/gas filler rod in 1 m lengths, or 2 mm silver steel / brass / carbon-fibre rod | 796 x 1000 mm (4 pins each) |
