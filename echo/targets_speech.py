"""Stage-4 speech targets from espeak-ng: sustained "ah" (4a), "ma" / "ba" / "om" (4b), "hello" (4c).

Pipeline per target (deterministic):
  1. espeak-ng (voice en-us, default pitch, a per-target speed) -> raw WAV at 22050 Hz, cached under
     artifacts/speech/raw/<name>.wav (committed). The loader prefers the cached WAV, so stage 4 does not need
     espeak-ng on the PATH; `synth_raw` is the only place that runs the binary.
  2. Resample to FS (polyphase 320/441).
  3. Crop to the voiced extent (envelope above -40 dB re its peak, 10 ms smoothing) plus 5 ms each side. Durations
     come from the espeak speed setting, chosen so the natural utterance fits the spec duration; there is no time
     stretching. Only "ah" (sustained vowel, fixed 150 ms) is cut: its steady vowel is cropped to 150 ms.
  4. 5 ms raised-cosine fades at both ends, band-limit to the design band 500-4000 Hz (zero-phase,
     `echo.clap.band_limit`), peak-normalize to 1.

What band-limiting removes: the voice fundamental (~100-130 Hz for the en-us voice) and its first harmonics, all
nasal murmur energy below 500 Hz (the "m" of "ma"/"om" is mostly below 500 Hz), and the lower skirt of F1 for
back vowels. The "ah" vowel is used for 4a because its F1 and F2 lie in band (measured values are in the report).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from echo.clap import band_limit
from echo.scene import FS
from echo.targets import Target

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "artifacts" / "speech" / "raw"
ESPEAK_LOCAL = ROOT / ".cache" / "espeak" / "root"  # dpkg -x of the Ubuntu focal espeak-ng 1.50 packages
BAND = (500.0, 4000.0)
FADE_S = 0.005
VOICE = "en-us"

# name -> (espeak input, words-per-minute, target duration or None = keep natural length)
# espeak input uses [[...]] phoneme mnemonics where plain text is ambiguous: "om" is not in espeak's en dictionary
# and its letter rules give /Am/ ("ahm"); the dictionary word "om" is /oUm/ ("ohm"), so the phonemes are given.
# Speeds were chosen so the natural voiced extent lands in the spec range (measured, see the report).
SPEECH = {
    "ah": ("[[A:]]", 240, 0.150),  # natural ~165 ms at 240 wpm; steady vowel cut to 150 ms
    "ma": ("[[mA:]]", 250, None),  # spec 200-250 ms
    "ba": ("[[bA:]]", 230, None),
    "om": ("[[oUm]]", 250, None),
    "hello": ("hello", 195, None),  # spec 400 ms
}
SYLLABLES = ("ma", "ba", "om")


@dataclass
class SpeechTarget(Target):
    """A Target with the stage-4 extras the judges need (the seam passes only the target object).

    candidates: the closed set for 4b, name -> clean band-limited audio (includes this target).
    """

    candidates: dict = field(default_factory=dict)
    source: str = ""  # "cache" or "espeak-ng"


def espeak_cmd() -> tuple[list[str], dict]:
    """Resolve the espeak-ng binary and data path in one place: system binary first, else the local dpkg-x copy."""
    exe = shutil.which("espeak-ng")
    if exe:
        return [exe], dict(os.environ)
    lib = ESPEAK_LOCAL / "usr" / "lib" / "x86_64-linux-gnu"
    exe = ESPEAK_LOCAL / "usr" / "bin" / "espeak-ng"
    if not exe.exists():
        raise FileNotFoundError("espeak-ng not found on PATH nor in .cache/espeak/root, and no cached WAV")
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = str(lib) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return [str(exe), f"--path={lib}"], env


def synth_raw(text: str, wpm: int, out: Path) -> None:
    """Run espeak-ng once: `text` at `wpm`, voice en-us, default pitch/amplitude, 16-bit WAV at 22050 Hz."""
    cmd, env = espeak_cmd()
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd + ["-v", VOICE, "-s", str(wpm), "-w", str(out), text], env=env, check=True,
                   capture_output=True)


def load_raw(name: str, refresh: bool = False) -> tuple[np.ndarray, int, str]:
    """Raw espeak audio for `name`; uses the committed cache when present (says so via the returned source)."""
    text, wpm, _ = SPEECH[name]
    path = RAW_DIR / f"{name}.wav"
    src = "cache"
    if refresh or not path.exists():
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "x.wav"
            synth_raw(text, wpm, tmp)
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp, path)
        src = "espeak-ng"
    x, fs = sf.read(path, dtype="float64")
    return x, fs, src


def _voiced_extent(x, fs, floor_db=-40.0, smooth_s=0.010):
    k = max(1, int(round(smooth_s * fs)))
    env = np.sqrt(np.convolve(x**2, np.ones(k) / k, mode="same"))
    on = np.where(env > env.max() * 10 ** (floor_db / 20))[0]
    return int(on[0]), int(on[-1]) + 1


def _fade(n, fs, fade_s=FADE_S):
    k = min(int(round(fade_s * fs)), n // 2)
    w = np.ones(n)
    ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(k) + 0.5) / k)
    w[:k] = ramp
    w[n - k:] = ramp[::-1]
    return w


def shape_clean(name: str, refresh: bool = False, fs: int = FS) -> tuple[np.ndarray, str]:
    """Resampled, cropped, faded audio before band-limiting (peak 1). Returns (audio, source)."""
    x, fs_raw, src = load_raw(name, refresh)
    g = gcd(fs, fs_raw)
    y = resample_poly(x, fs // g, fs_raw // g)  # 22050 -> 16000: up 320, down 441
    i0, i1 = _voiced_extent(y, fs)
    pad = int(round(FADE_S * fs))
    dur = SPEECH[name][2]
    if dur is None:
        y = y[max(0, i0 - pad): min(len(y), i1 + pad)]
    else:
        # Sustained vowel: keep the central `dur` of the voiced extent (cuts only steady vowel, not a phoneme edge).
        n = int(round(dur * fs))
        c = (i0 + i1) // 2
        a = max(0, c - n // 2)
        y = y[a: a + n]
    y = y * _fade(len(y), fs)
    return y / np.max(np.abs(y)), src


def speech_target(name: str, refresh: bool = False, fs: int = FS, with_candidates: bool = True) -> SpeechTarget:
    """Band-limited (500-4000 Hz), peak-normalized stage-4 target. `name` in SPEECH."""
    y, src = shape_clean(name, refresh, fs)
    a = band_limit(y, BAND[0], BAND[1], fs)
    a = a / np.max(np.abs(a))
    cands = {}
    if with_candidates and name in SYLLABLES:
        cands = {s: (a if s == name else speech_target(s, refresh, fs, with_candidates=False).audio)
                 for s in SYLLABLES}
    return SpeechTarget(name=name, audio=a, duration_s=len(a) / fs, f_top_hz=BAND[1], candidates=cands,
                        source=src)


def vowel_ah() -> SpeechTarget:
    return speech_target("ah")


def syllables() -> dict[str, SpeechTarget]:
    return {s: speech_target(s) for s in SYLLABLES}


def word_hello() -> SpeechTarget:
    return speech_target("hello")


def write_artifacts(out_dir: Path = ROOT / "artifacts" / "speech") -> None:
    """Band-limited target WAVs (FS, float) and spectrogram PNGs (raw shaped vs band-limited) for every target."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    for name in SPEECH:
        t = speech_target(name, with_candidates=False)
        clean, _ = shape_clean(name)
        sf.write(out_dir / f"{name}.wav", t.audio, FS, subtype="FLOAT")
        fig, ax = plt.subplots(1, 2, figsize=(9, 3.4), sharey=True)
        for a, (lab, y) in zip(ax, (("espeak-ng, 16 kHz, cropped", clean), ("band-limited 500-4000 Hz", t.audio))):
            a.specgram(y, NFFT=256, Fs=FS, noverlap=224, cmap="magma", vmin=-110)
            a.set_title(f"{name}: {lab}", fontsize=9)
            a.set_xlabel("time (s)")
            a.axhline(500, color="w", lw=0.5, ls="--")
            a.axhline(4000, color="w", lw=0.5, ls="--")
        ax[0].set_ylabel("frequency (Hz)")
        ax[0].set_ylim(0, 5000)
        fig.tight_layout()
        fig.savefig(out_dir / f"{name}_spectrogram.png", dpi=110)
        plt.close(fig)


if __name__ == "__main__":
    write_artifacts()
