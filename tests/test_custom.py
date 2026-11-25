"""Custom-target designer: odd inputs are handled or refused with a message, the realization rule, and the CLI
pipeline on the example target writes a contract-valid run folder with IRs."""

import io
import json
import time

import numpy as np
import pytest
import soundfile as sf

from contract_check import check_index, check_run_folder
from echo.scene import FS
from stages.custom import CustomInputError, classify, load_audio, main, prepare_target

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "inputs" / "targets" / "rising_two_note.wav"


def _wav(x, sr, subtype="PCM_16"):
    b = io.BytesIO()
    sf.write(b, x, sr, format="WAV", subtype=subtype)
    return b.getvalue()


def _tone(f, dur, sr, ch=1):
    t = np.arange(int(dur * sr)) / sr
    x = 0.5 * np.sin(2 * np.pi * f * t)
    return np.stack([x] * ch, axis=1) if ch > 1 else x


def test_stereo_44k1_and_48k():
    for sr in (44100, 48000):
        x, s = load_audio(_wav(_tone(1500, 0.2, sr, ch=2), sr))
        y, info, warns = prepare_target(x, s)
        assert info["input_channels"] == 2 and abs(len(y) / FS - 0.2) < 0.02
        assert np.isclose(np.max(np.abs(y)), 1.0)
        assert any("mono" in w for w in warns) and any("resampled" in w for w in warns)


def test_rejections():
    with pytest.raises(CustomInputError, match="short"):
        prepare_target(*load_audio(_wav(_tone(1500, 0.02, FS), FS)))
    with pytest.raises(CustomInputError, match="silent"):
        prepare_target(*load_audio(_wav(np.zeros(8000), FS)))
    with pytest.raises(CustomInputError, match="500-4000"):
        prepare_target(*load_audio(_wav(_tone(60, 0.3, FS), FS)))
    with pytest.raises(CustomInputError, match="decodable"):
        load_audio(b"this is not audio at all" * 50)
    with pytest.raises(CustomInputError, match="empty"):
        load_audio(b"")


def test_clipping_and_long_file_trimmed():
    x = np.clip(3 * np.sin(2 * np.pi * 1000 * np.arange(3 * FS) / FS), -1, 1)
    y, info, warns = prepare_target(*load_audio(_wav(x, FS, "FLOAT")), max_duration_s=1.0)
    assert any("clipped" in w for w in warns) and any("trimmed" in w for w in warns)
    assert abs(len(y) / FS - 1.0) < 1e-3 and abs(y[-1]) < 0.05  # faded out


def test_realization_rule():
    tone, _, _ = prepare_target(_tone(2000, 0.15, FS), FS)
    assert classify(tone)[0] == "phase_locked"
    noise = np.random.default_rng(0).standard_normal(int(0.15 * FS))
    y, _, _ = prepare_target(noise, FS)
    r, st = classify(y)
    assert r == "sampling" and st["tonal_ratio"] < 0.5
    harm = sum(np.sin(2 * np.pi * 220 * k * np.arange(int(0.15 * FS)) / FS) for k in range(3, 18))
    assert classify(prepare_target(harm, FS)[0])[0] == "sampling"  # harmonic-rich (vowel-like)


def test_cli_example_target(tmp_path, monkeypatch, capsys):
    import stages.custom as cm

    real = cm.design_custom
    monkeypatch.setattr(cm, "design_custom", lambda *a, **k: real(*a, **{**k, "runs_root": tmp_path}))
    t = time.time()
    assert main(["--target", str(EXAMPLE), "--name", "rising two-note"]) == 0
    wall = time.time() - t
    runs = list((tmp_path / "custom").glob("*/manifest.json"))
    assert len(runs) == 1
    d = runs[0].parent
    check_run_folder(d)
    check_index(tmp_path)
    man = json.loads((d / "manifest.json").read_text())
    mt = json.loads((d / "metrics.json").read_text())
    assert man["status"] == "tier0_only" and man["verified"] is False and man["stage"] == "custom"
    assert man["custom"]["classification"]["realization"] == "phase_locked"
    assert man["ir"]["tier0"] == "ir_tier0.wav" and (d / "ir_tier0.wav").exists() and man["ir"]["band_hz"] == [500.0, 4000.0]
    assert mt["failure_cause"] == "no pass condition defined for custom targets" and mt["pass_condition"] is None
    assert all(m["threshold"] is None and m["pass"] is None and not m["gating"] for m in mt["metrics"])
    assert {m["id"] for m in mt["metrics"]} == {"spec_corr", "env_corr"}
    assert "stages.custom" in man["command"]
    assert wall < 600, wall  # ~32 s on an idle machine (report); generous for a shared, loaded one
