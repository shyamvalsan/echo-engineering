# Listen

Generated from the newest final full-wave run of each test. For each run:

- `<tag>_target.wav`: the sound we aimed for.
- `<tag>_echo_only.wav`: the simulated echo alone, turned up to full volume.
- `<tag>_clap_then_echo_boosted.wav`: the clap, then the echo raised so it sits 12 dB under the clap. In reality it is much fainter than that: see the "true level" column. The run folder's own `as_heard.wav` keeps the true ratio, which is why only the clap is audible there.

| stage | sub | run tag | true echo level re clap (dB) | boost applied here (dB) | estimated echo loudness for a 100 dB clap (dB SPL) | title |
|---|---|---|---|---|---|---|
| s1_bird |  | `s1` | -49.7 | 37.7 | 61.6 | Bird note, 3.5 to 2.0 kHz whistle, 80 ms |
| s2_motif |  | `s2` | -40.3 | 28.3 | 67.6 | Motif C6 E6 G6 C7, 45 ms each |
| s2_motif |  | `s2v2` | -60.9 | 48.9 | 47.5 | Motif C6 E6 G6 C7, 45 ms each (v2: 1 cm posts, 20 deg, extinction-budgeted) |
| s3_melody |  | `s3` | -72.6 | 60.6 | 37.2 | Melody, Ode to Joy opening (E6 E6 F6 G6 G6 F6 E6 D6), 100 ms notes |
| s3_melody |  | `s3_60ms` | -67.9 | 55.9 | 41.8 | Melody, Ode to Joy opening (E6 E6 F6 G6 G6 F6 E6 D6), 60 ms notes |
| s4_speech | 4a | `s4_4a_ah` | -51.3 | 39.3 | 58.6 | Speech 4a: "ah" (150 ms) |
| s4_speech | 4b | `s4_4b_ba` | -63.4 | 51.4 | 44.7 | Speech 4b: "ba" (238 ms) |
| s4_speech | 4b | `s4_4b_ma` | -62.0 | 50.0 | 46.0 | Speech 4b: "ma" (223 ms) |
| s4_speech | 4b | `s4_4b_om` | -66.8 | 54.8 | 43.1 | Speech 4b: "om" (247 ms) |
| s4_speech | 4c | `s4_4c_hello` | -66.2 | 54.2 | 44.1 | Speech 4c: "hello" (399 ms) |
