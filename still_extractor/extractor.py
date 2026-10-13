"""Extract still frames from raw video footage and build a browsable HTML gallery.

Recursively walks a directory tree, probes each video's duration with ``ffprobe``,
and pulls five JPEG stills (at 10/30/50/70/90% of runtime) using ``ffmpeg``
fast-seek (``-ss`` before ``-i``) with inline scaling. When extraction finishes it
renders ``index.html`` over everything in the stills folder, so the whole job is a
single command::

    <output_dir>/
        index.html          the two-pane gallery
        stills/             the extracted JPEGs

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

from .constants import (
    DEFAULT_EXTENSIONS_LABEL,
    DISAMBIGUATOR_LENGTH,
    FRAME_FRACTIONS,
    INDEX_FILENAME,
    JPEG_QUALITY,
    SCALE_FILTER,
    STILLS_SUBDIR,
    VIDEO_EXTENSIONS,
)
from .gallery import build_gallery, index_from_videos

__all__ = [
    "DEFAULT_EXTENSIONS_LABEL",
    "DISAMBIGUATOR_LENGTH",
    "FRAME_FRACTIONS",
    "JPEG_QUALITY",
    "SCALE_FILTER",
    "VIDEO_EXTENSIONS",
    "discover_videos",
    "ensure_tools",
    "extract_frame",
    "is_metadata_file",
    "main",
    "normalize_extensions",
    "output_name",
    "probe_duration",
    "process_video",
]


def ensure_tools() -> None:
    """Exit with a clear message if ffmpeg/ffprobe are not on the PATH."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        sys.exit(
            "Error: required tool(s) not found on PATH: "
            + ", ".join(missing)
            + ". Install FFmpeg (which bundles ffprobe) and retry."
        )


def normalize_extensions(raw: str) -> set[str]:
    """Parse a comma-separated extension list into a lowercased dotted set."""
    extensions = set()
    for part in raw.split(","):
        part = part.strip().lower()
        if part:
            extensions.add(part if part.startswith(".") else "." + part)
    return extensions


# macOS writes an AppleDouble sidecar named ``._<original>`` beside every file on
# volumes without native APFS/HFS+ metadata (exFAT, FAT32, SMB shares). The
# sidecar *inherits the real file's extension*, so an extension filter alone
# treats ``._C0168.MP4`` as a video and reports it as corrupt. It is pure
# metadata — never media — so it is skipped before any probe.
MACOS_METADATA_PREFIX = "._"
MACOS_METADATA_NAMES = frozenset({".DS_Store"})


def is_metadata_file(path: Path) -> bool:
    """True for macOS metadata companions, which are never real media."""
    return path.name.startswith(MACOS_METADATA_PREFIX) or path.name in MACOS_METADATA_NAMES


def discover_videos(
    root_dir: Path, extensions: set[str] | frozenset[str] = VIDEO_EXTENSIONS
) -> tuple[list[Path], int]:
    """Collect video files under ``root_dir`` into a flat, sorted list.

    Returns ``(videos, ignored)``, where ``ignored`` counts the macOS metadata
    companions (see :func:`is_metadata_file`) that were skipped. Matching is
    case-insensitive (``.MP4`` == ``.mp4``) because the comparison is on
    ``Path.suffix.lower()``.
    """
    videos: list[Path] = []
    ignored = 0
    for path in root_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        if is_metadata_file(path):
            ignored += 1
            continue
        videos.append(path)
    return sorted(videos), ignored


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
    file_path: Path, stills_dir: Path, root_dir: Path
) -> tuple[Path, bool, str]:
    """Worker: probe one video and extract its five frames into ``stills_dir``.

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
        out_path = stills_dir / output_name(file_path, root_dir, index)
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
        description="Extract 5 stills (10/30/50/70/90%) from every video file "
        f"under a root directory into <output_dir>/{STILLS_SUBDIR}/, then build "
        f"<output_dir>/{INDEX_FILENAME} — a browsable gallery grouped by source folder.",
    )
    parser.add_argument("root_dir", type=Path, help="root folder to search recursively")
    parser.add_argument(
        "output_dir",
        type=Path,
        help=f"output folder; receives {INDEX_FILENAME} and a {STILLS_SUBDIR}/ folder",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=os.cpu_count() or 1,
        help="number of worker processes (default: all CPU cores)",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        default=None,
        metavar="LIST",
        help='comma-separated extensions to scan, replacing the default set '
        '(e.g. ".mp4,.mov,.mxf"). Default: ' + DEFAULT_EXTENSIONS_LABEL,
    )
    args = parser.parse_args(argv)

    ensure_tools()
    root_dir = args.root_dir.resolve()
    output_dir = args.output_dir.resolve()
    stills_dir = output_dir / STILLS_SUBDIR
    stills_dir.mkdir(parents=True, exist_ok=True)

    extensions = normalize_extensions(args.extensions) if args.extensions else VIDEO_EXTENSIONS
    videos, ignored_metadata = discover_videos(root_dir, extensions)
    total = len(videos)
    ignored_note = (
        f" (ignored {ignored_metadata} macOS metadata file(s))" if ignored_metadata else ""
    )
    print(f"Found {total} video file(s) under {root_dir}{ignored_note}")

    failed: list[tuple[Path, str]] = []
    if total:
        done = 0
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(process_video, video, stills_dir, root_dir): video
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

    # Built over the whole stills folder, not just this run, so repeated
    # extractions into the same output directory accumulate into one gallery.
    html_path = build_gallery(
        stills_dir,
        output_dir / INDEX_FILENAME,
        index=index_from_videos(videos, root_dir),
        image_prefix=f"{STILLS_SUBDIR}/",
    )
    if html_path is None:
        print(f"\nNo stills in {stills_dir} — no gallery written.")
    else:
        print(f"\nGallery: {html_path}")


if __name__ == "__main__":
    main()
