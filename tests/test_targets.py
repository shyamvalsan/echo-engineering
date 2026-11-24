import numpy as np
import pytest

from echo.scene import FS
from echo.targets import MOTIF_HZ, bird_note, melody, motif, note_hz


def _pitch(x):
    """Peak of a heavily zero-padded, Hann-windowed spectrum (accurate for a steady tone)."""
    nfft = 1 << 18
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)), nfft))
    return np.fft.rfftfreq(nfft, 1 / FS)[np.argmax(X)]


def _cents(a, b):
    return 1200 * np.log2(a / b)


def test_note_hz():
    assert note_hz("A4") == 440.0
    assert note_hz("E6") == pytest.approx(1318.51, abs=0.01)
    assert note_hz("C7") == pytest.approx(2093.00, abs=0.01)
    assert note_hz("D6") == pytest.approx(1174.66, abs=0.01)


def test_bird_note():
    tg = bird_note()
    assert len(tg.audio) == int(0.08 * FS) and tg.duration_s == 0.08
    assert np.max(np.abs(tg.audio)) == pytest.approx(1.0)
    assert tg.f_top_hz == 3500.0 and tg.notes is None
    t, f = tg.f_track
    assert f[0] == pytest.approx(3500) and f[-1] == pytest.approx(2000, rel=0.02)
    assert np.all(np.diff(f) < 0)
    # Instantaneous frequency of the audio (phase derivative of the analytic signal) follows f_track.
    from scipy.signal import hilbert

    ph = np.unwrap(np.angle(hilbert(tg.audio)))
    fi = np.diff(ph) * FS / (2 * np.pi)
    for ti in (0.01, 0.02, 0.04, 0.06, 0.07):
        i = int(ti * FS)
        expect = np.interp(ti, t, f)
        assert np.median(fi[i - 8 : i + 8]) == pytest.approx(expect, rel=0.01)


def test_motif():
    tg = motif()
    assert len(tg.audio) == int(0.18 * FS) and tg.duration_s == pytest.approx(0.18)
    assert [n[0] for n in tg.notes] == list(MOTIF_HZ)
    assert tg.f_top_hz == 2093.0
    for f0, t_on, t_off in tg.notes:
        seg = tg.audio[int(t_on * FS) : int(t_off * FS)]
        assert abs(_cents(_pitch(seg), f0)) < 5
    assert tg.notes[1][1] == pytest.approx(0.045) and tg.notes[-1][2] == pytest.approx(0.18)


@pytest.mark.parametrize("note_ms", [100, 60])
def test_melody(note_ms):
    tg = melody(note_ms)
    assert len(tg.audio) == int(round(8 * note_ms / 1000 * FS))
    assert tg.duration_s == pytest.approx(8 * note_ms / 1000)
    names_hz = [note_hz(n) for n in ("E6", "E6", "F6", "G6", "G6", "F6", "E6", "D6")]
    assert [n[0] for n in tg.notes] == pytest.approx(names_hz)
    for f0, t_on, t_off in tg.notes:
        seg = tg.audio[int(round(t_on * FS)) : int(round(t_off * FS))]
        assert abs(_cents(_pitch(seg), f0)) < 5
    # Repeated notes (E6 E6) are separable: the envelope dips at the boundary.
    b = int(round(note_ms / 1000 * FS))
    assert np.max(np.abs(tg.audio[b - 2 : b + 2])) < 0.05
    assert tg.f_top_hz == pytest.approx(note_hz("G6"))
