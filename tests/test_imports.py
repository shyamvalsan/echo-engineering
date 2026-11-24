import importlib

import pytest

MODULES = [
    "numpy", "scipy", "torch", "auraloss", "kwave", "nevergrad", "cmaes", "librosa", "soundfile",
    "pystoi", "faster_whisper", "matplotlib", "imageio_ffmpeg",
]


@pytest.mark.parametrize("name", MODULES)
def test_import(name):
    importlib.import_module(name)


def test_ffmpeg_binary():
    import os

    import imageio_ffmpeg

    assert os.path.exists(imageio_ffmpeg.get_ffmpeg_exe())
