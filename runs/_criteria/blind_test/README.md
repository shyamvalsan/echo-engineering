# Blind listening test

9 echoes (`sample_01.wav` ... `sample_09.wav`), the echo alone at full volume, one per test, shuffled with a fixed seed (20261125). The answer key is `key.json`: keep it closed until the tally is done.

Protocol. Play each sample to someone who has not seen or heard the targets and has not read the key. First ask "what do you hear?" and write the answer down verbatim. Then play the target sounds in `targets/` (9 files, listed alphabetically below) and ask "which of these 9 sounds is it?" (one choice; "none" allowed). Repeat for every sample in a fresh random order, with no feedback in between. Tally the open answers that name the target and the closed-set choices that are correct (chance is 1/9 per sample). The owner's earlier verdict was not blind: the listener knew each target.

Targets:

- `targets/4a_vowel_ah.wav`
- `targets/4b_syllable_ba.wav`
- `targets/4b_syllable_ma.wav`
- `targets/4b_syllable_om.wav`
- `targets/4c_word_hello.wav`
- `targets/stage_1_bird_whistle.wav`
- `targets/stage_2_four-note_motif.wav`
- `targets/stage_3_melody_100_ms_notes.wav`
- `targets/stage_3_melody_60_ms_notes.wav`
