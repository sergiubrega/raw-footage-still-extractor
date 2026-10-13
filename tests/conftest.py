"""Shared pytest fixtures.

Anything needing real media generation is skipped when ffmpeg/ffprobe are absent,
so the pure-logic tests still run on a bare machine.
"""

import shutil
import subprocess

import pytest

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def ffmpeg_required():
    """Skip the requesting test when ffmpeg/ffprobe are not on the PATH."""
    if not FFMPEG_AVAILABLE:
        pytest.skip("ffmpeg/ffprobe not found on PATH")


@pytest.fixture
def make_video(tmp_path):
    """Factory that renders a short synthetic test clip with ffmpeg."""

    def _make(name: str = "clip.mp4", duration: int = 2):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc=duration={duration}:size=320x240:rate=25",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
        )
        return path

    return _make


@pytest.fixture
def image_width():
    """Return a callable that reads a JPEG's pixel width via ffprobe."""

    def _width(path) -> int:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip().splitlines()[0])

    return _width
