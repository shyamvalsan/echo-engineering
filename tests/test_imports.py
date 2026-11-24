import importlib
import importlib.util
from pathlib import Path

import pytest

MODULES = [
    "numpy", "scipy", "torch", "auraloss", "nevergrad", "cmaes", "librosa", "soundfile",
    "pystoi", "faster_whisper", "matplotlib", "imageio_ffmpeg",
]


@pytest.mark.parametrize("name", MODULES)
def test_import(name):
    importlib.import_module(name)


def _kwave_binaries_ready() -> bool:
    # `import kwave` downloads its OMP and CUDA binaries (~300 MB) on first use and blocks until done.
    # Only import it once the download has completed (each binary gets a *_metadata.json when finished),
    # so the test suite never hangs or starts a second, competing download.
    spec = importlib.util.find_spec("kwave")
    if spec is None:
        return False
    bindir = Path(spec.origin).parent / "bin" / "linux"
    return all((bindir / f"kspaceFirstOrder-{a}_metadata.json").exists() for a in ("OMP", "CUDA"))


def test_import_kwave():
    assert importlib.util.find_spec("kwave") is not None, "k-wave-python not installed"
    if not _kwave_binaries_ready():
        pytest.skip("k-wave binaries still downloading (see DECISIONS.md); import would block")
    importlib.import_module("kwave")


def test_ffmpeg_binary():
    import os

    import imageio_ffmpeg

    assert os.path.exists(imageio_ffmpeg.get_ffmpeg_exe())
