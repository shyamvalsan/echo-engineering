"""Synthesized targets for stages 1-3: bird whistle, four-note motif, Ode to Joy opening.

Every target is audio at FS, t = 0 at the start of the sound, peak-normalized to 1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from echo.scene import FS

FADE_S = 0.005  # raised-cosine fade at each end of every note (makes repeated notes separable)

MOTIF_HZ = (1047.0, 1319.0, 1568.0, 2093.0)  # C6 E6 G6 C7, values verbatim from the spec
MELODY_NOTES = ("E6", "E6", "F6", "G6", "G6", "F6", "E6", "D6")  # Ode to Joy, opening 8 notes


@dataclass
class Target:
    name: str
    audio: np.ndarray  # mono, FS
    duration_s: float
    notes: list[tuple[float, float, float]] | None = None  # (f_hz, t_on_s, t_off_s)
    f_track: tuple[np.ndarray, np.ndarray] | None = None  # (t_s, f_hz), the intended pitch over time
    f_top_hz: float = 0.0  # highest fundamental in the target


def note_hz(name: str) -> float:
    """Equal-tempered frequency, A4 = 440 Hz. name like 'E6', 'F#5', 'Bb4'."""
    pc = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[name[0].upper()]
    rest = name[1:]
    if rest.startswith("#"):
        pc, rest = pc + 1, rest[1:]
    elif rest.startswith("b"):
        pc, rest = pc - 1, rest[1:]
    midi = 12 * (int(rest) + 1) + pc
    return float(440.0 * 2.0 ** ((midi - 69) / 12.0))


def _fade(n: int, fs: int, fade_s: float = FADE_S) -> np.ndarray:
    k = min(int(round(fade_s * fs)), n // 2)
    w = np.ones(n)
    ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(k) + 0.5) / k)
    w[:k] = ramp
    w[n - k :] = ramp[::-1]
    return w


def _track(fn, duration_s, hop_s=0.001):
    t = np.arange(0.0, duration_s, hop_s)
    return t, np.asarray([fn(ti) for ti in t], dtype=float)


def bird_note(duration_s=0.08, f_start=3500.0, f_end=2000.0, fs=FS) -> Target:
    """Descending whistle, exponential (constant octaves/s) glide f_start -> f_end, pure tone, faded ends."""
    n = int(round(duration_s * fs))
    t = np.arange(n) / fs
    k = np.log(f_end / f_start) / duration_s
    f_inst = lambda tt: f_start * np.exp(k * tt)  # noqa: E731
    phase = 2 * np.pi * f_start * (np.exp(k * t) - 1.0) / k  # integral of f_inst
    audio = np.sin(phase) * _fade(n, fs)
    return Target(
        name="bird",
        audio=audio / np.max(np.abs(audio)),
        duration_s=duration_s,
        notes=None,
        f_track=_track(f_inst, duration_s),
        f_top_hz=f_start,
    )


def note_sequence(freqs, note_s, name, fs=FS) -> Target:
    """Concatenated pure-tone notes, each with raised-cosine fades at both ends."""
    n_note = int(round(note_s * fs))
    parts, notes = [], []
    for i, f in enumerate(freqs):
        t = np.arange(n_note) / fs
        parts.append(np.sin(2 * np.pi * f * t) * _fade(n_note, fs))
        notes.append((float(f), i * note_s, (i + 1) * note_s))
    audio = np.concatenate(parts)
    duration_s = len(freqs) * note_s

    def f_at(tt):
        i = min(int(tt / note_s), len(freqs) - 1)
        return freqs[i]

    return Target(
        name=name,
        audio=audio / np.max(np.abs(audio)),
        duration_s=duration_s,
        notes=notes,
        f_track=_track(f_at, duration_s),
        f_top_hz=float(max(freqs)),
    )


def motif(note_ms=45, fs=FS) -> Target:
    """C6 E6 G6 C7 (1047, 1319, 1568, 2093 Hz), 45 ms each, 180 ms total."""
    return note_sequence(MOTIF_HZ, note_ms / 1000.0, "motif", fs)


def melody(note_ms=100, fs=FS) -> Target:
    """Ode to Joy opening: E6 E6 F6 G6 G6 F6 E6 D6, note_ms each (100 nominal; 60 also used)."""
    freqs = [note_hz(n) for n in MELODY_NOTES]
    return note_sequence(freqs, note_ms / 1000.0, f"melody_{note_ms}ms", fs)
