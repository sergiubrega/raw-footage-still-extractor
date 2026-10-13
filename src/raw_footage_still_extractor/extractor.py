"""Extract still frames from raw video footage.

Recursively walks a directory tree, probes each video's duration with
``ffprobe``, and pulls five JPEG stills (at 10/30/50/70/90% of runtime) using
``ffmpeg`` fast-seek (``-ss`` before ``-i``) with inline scaling.

Standard library only. Requires ``ffmpeg`` and ``ffprobe`` on the system PATH.
"""

import argparse
import concurrent.futures
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Case-insensitive match is applied via Path.suffix.lower().
VIDEO_EXTENSIONS = {".mp4", ".mxf"}

# Fractions of total duration at which a still is captured.
FRAME_FRACTIONS = (0.10, 0.30, 0.50, 0.70, 0.90)

SCALE_FILTER = "scale=300:-1"
JPEG_QUALITY = "2"  # -q:v 2

# Hex chars of the relative-path digest used to disambiguate output filenames.
# 8 chars = 32 bits; collision probability stays negligible for tens of
# thousands of files.
DISAMBIGUATOR_LENGTH = 8


def ensure_tools() -> None:
    """Exit with a clear message if ffmpeg/ffprobe are not on the PATH."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        sys.exit(
            "Error: required tool(s) not found on PATH: "
            + ", ".join(missing)
            + ". Install FFmpeg (which bundles ffprobe) and retry."
        )


def discover_videos(root_dir: Path) -> list[Path]:
    """Recursively collect ``.mp4``/``.mxf`` files into a flat, sorted list."""
    return sorted(
        path
        for path in root_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def probe_duration(file_path: Path) -> float:
    """Return the media duration in seconds via ffprobe.

    Raises :class:`RuntimeError` if the probe fails, returns nothing, or yields
    a non-positive/unparsable duration (i.e. the file is corrupt/unreadable).
    """
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed (exit {exc.returncode})") from exc

    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError("ffprobe returned an empty duration")
    try:
        duration = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"unparsable duration: {raw!r}") from exc
    if duration <= 0:
        raise RuntimeError(f"non-positive duration: {duration}")
    return duration


def output_name(file_path: Path, root_dir: Path, frame_index: int) -> str:
    """Build ``{parent}_{stem}_{hash}_frame_{n}.jpg`` with spaces -> underscores.

    ``{hash}`` is a short digest of the file's path *relative to* ``root_dir``.
    That keeps output flat while guaranteeing distinct names for files that share
    both an immediate-parent name and a stem in different subtrees (e.g.
    ``CARD_01/DCIM/100MEDIA/A001_C001.MXF`` vs
    ``CARD_02/DCIM/100MEDIA/A001_C001.MXF``), and for same-stem files differing
    only by extension in one folder.
    """
    try:
        relative = file_path.resolve().relative_to(root_dir.resolve())
    except ValueError:  # not under root_dir (shouldn't happen via rglob)
        relative = file_path
    digest = hashlib.sha1(str(relative).encode("utf-8")).hexdigest()[:DISAMBIGUATOR_LENGTH]
    name = (
        f"{file_path.parent.name}_{file_path.stem}_{digest}"
        f"_frame_{frame_index}.jpg"
    )
    return name.replace(" ", "_")


def extract_frame(file_path: Path, timestamp: float, out_path: Path) -> None:
    """Capture one scaled JPEG at ``timestamp`` seconds using fast-seek."""
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp:.3f}",  # -ss BEFORE -i => fast seek
        "-i",
        str(file_path),
        "-vframes",
        "1",
        "-q:v",
        JPEG_QUALITY,
        "-vf",
        SCALE_FILTER,
        str(out_path),
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)


def process_video(
    file_path: Path, output_dir: Path, root_dir: Path
) -> tuple[Path, bool, str]:
    """Worker: probe one video and extract its five frames.

    Never raises, so the process pool keeps running the rest of the batch.
    Returns ``(path, ok, message)``.
    """
    try:
        duration = probe_duration(file_path)
    except RuntimeError as exc:
        return file_path, False, f"corrupt/unreadable ({exc})"

    failures: list[str] = []
    for index, fraction in enumerate(FRAME_FRACTIONS, start=1):
        timestamp = duration * fraction
        out_path = output_dir / output_name(file_path, root_dir, index)
        try:
            extract_frame(file_path, timestamp, out_path)
        except subprocess.CalledProcessError as exc:
            failures.append(f"frame {index} (exit {exc.returncode})")

    if failures:
        return file_path, False, "extraction failed: " + ", ".join(failures)
    return file_path, True, "ok"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="raw-footage-still-extractor",
        description="Extract 5 stills (10/30/50/70/90%) from every .mp4/.mxf "
        "file under a root directory, into a flat output directory.",
    )
    parser.add_argument("root_dir", type=Path, help="root folder to search recursively")
    parser.add_argument("output_dir", type=Path, help="flat folder for the JPEG stills")
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=os.cpu_count() or 1,
        help="number of worker processes (default: all CPU cores)",
    )
    args = parser.parse_args(argv)

    ensure_tools()
    root_dir = args.root_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    videos = discover_videos(root_dir)
    total = len(videos)
    print(f"Found {total} video file(s) under {root_dir}")
    if total == 0:
        return

    failed: list[tuple[Path, str]] = []
    done = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_video, video, args.output_dir, root_dir): video
            for video in videos
        }
        for future in concurrent.futures.as_completed(futures):
            done += 1
            path, ok, message = future.result()
            if not ok:
                failed.append((path, message))
                print(f"[FAIL] {path} -> {message}")
            print(f"Processed {done}/{total}")

    if failed:
        print(f"\n{len(failed)} file(s) failed:")
        for path, message in failed:
            print(f"  {path}: {message}")
    print(f"\nDone. {total - len(failed)}/{total} file(s) succeeded.")


if __name__ == "__main__":
    main()
