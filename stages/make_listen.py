import json, glob, os, sys
import numpy as np, soundfile as sf
root = sys.argv[1]; out = os.path.join(root, 'listen'); os.makedirs(out, exist_ok=True)
runs = json.load(open(os.path.join(root, 'runs/index.json')))['runs']
seen = {}; rows = []
for r in runs:  # newest first
    if r.get('status') != 'final': continue
    R = os.path.join(root, 'runs', r['path'])
    man = json.load(open(R + '/manifest.json')); met = json.load(open(R + '/metrics.json'))
    key = (r['stage'], man.get('substage'), r['run_id'].split('-')[-1])
    if key in seen: continue
    seen[key] = 1
    tag = r['run_id'].split('-', 2)[-1]
    ah, fs = sf.read(R + '/as_heard.wav'); echo, fs2 = sf.read(R + '/echo_tier1.wav'); tgt, _ = sf.read(R + '/target.wav')
    assert fs == fs2
    n = min(len(ah), len(echo))
    clap = np.zeros(n); k = int(0.012 * fs); clap[:k] = ah[:k]
    cp = np.max(np.abs(clap)); true_db = man.get('audio', {}).get('as_heard_echo_level_db')
    e = echo[:n] / (np.max(np.abs(echo[:n])) + 1e-12)
    for rel in (-12,):
        y = clap + e * cp * 10 ** (rel / 20)
        y = y / np.max(np.abs(y)) * 0.89
        pad = np.zeros(int(0.3 * fs))
        sf.write(f'{out}/{tag}_clap_then_echo_boosted.wav', np.concatenate([pad, y, pad]), fs, subtype='PCM_16')
    pad = np.zeros(int(0.2 * fs))
    sf.write(f'{out}/{tag}_echo_only.wav', np.concatenate([pad, e * 0.89, pad]), fs, subtype='PCM_16')
    sf.write(f'{out}/{tag}_target.wav', np.concatenate([pad, tgt / (np.max(np.abs(tgt)) + 1e-12) * 0.89, pad]), fs, subtype='PCM_16')
    boost = None if true_db is None else round(-12 - true_db, 1)
    rows.append((r['stage'], man.get('substage') or '', man.get('title', ''), tag, true_db, boost, met.get('headline', {}).get('echo_spl_db')))
rows.sort()
with open(out + '/README.md', 'w') as f:
    f.write('# Listen\n\nGenerated from the newest final full-wave run of each test. For each run:\n\n'
            '- `<tag>_target.wav`: the sound we aimed for.\n- `<tag>_echo_only.wav`: the simulated echo alone, turned up to full volume.\n'
            '- `<tag>_clap_then_echo_boosted.wav`: the clap, then the echo raised so it sits 12 dB under the clap. '
            'In reality it is much fainter than that: see the "true level" column. '
            'The run folder\'s own `as_heard.wav` keeps the true ratio, which is why only the clap is audible there.\n\n'
            '| stage | sub | run tag | true echo level re clap (dB) | boost applied here (dB) | estimated echo loudness for a 100 dB clap (dB SPL) | title |\n|---|---|---|---|---|---|---|\n')
    for s, sub, title, tag, t, b, spl in rows:
        f.write(f'| {s} | {sub} | `{tag}` | {t if t is None else round(t,1)} | {b} | {spl if spl is None else round(spl,1)} | {title} |\n')
print(open(out + '/README.md').read())
