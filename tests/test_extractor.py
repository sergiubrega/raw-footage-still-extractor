"""Tests for the extractor module."""

import hashlib
from pathlib import Path

import pytest

from still_extractor.extractor import (
    DISAMBIGUATOR_LENGTH,
    VIDEO_EXTENSIONS,
    discover_videos,
    main,
    normalize_extensions,
    output_name,
    probe_duration,
    process_video,
)


def test_default_extensions_cover_common_formats():
    for ext in (".mp4", ".mov", ".mxf", ".avi", ".mkv", ".mts", ".m2ts", ".webm", ".wmv"):
        assert ext in VIDEO_EXTENSIONS


def test_default_extensions_exclude_vendor_raw():
    # ffmpeg cannot demux these without vendor SDKs; listing them would only
    # produce guaranteed probe failures.
    for ext in (".braw", ".r3d", ".ari", ".crm", ".dng"):
        assert ext not in VIDEO_EXTENSIONS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mp4,mov", {".mp4", ".mov"}),
        (".MP4, .MOV ", {".mp4", ".mov"}),
        ("mp4,,mov", {".mp4", ".mov"}),
        ("", set()),
    ],
)
def test_normalize_extensions(raw, expected):
    assert normalize_extensions(raw) == expected


def test_discover_videos_is_case_insensitive_and_flat(tmp_path):
    (tmp_path / "sub").mkdir()
    for name in ("a.mp4", "b.MP4", "sub/c.MXF", "notes.txt", "thumb.jpg"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in discover_videos(tmp_path)] == ["a.mp4", "b.MP4", "c.MXF"]


def test_discover_videos_honours_custom_extensions(tmp_path):
    for name in ("a.mp4", "b.mov", "c.mkv"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in discover_videos(tmp_path, {".mov"})] == ["b.mov"]


def test_output_name_is_unique_across_identically_named_folders(tmp_path):
    card_a = tmp_path / "CARD_01" / "DCIM" / "100MEDIA" / "A001_C001.MXF"
    card_b = tmp_path / "CARD_02" / "DCIM" / "100MEDIA" / "A001_C001.MXF"
    for path in (card_a, card_b):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    name_a = output_name(card_a, tmp_path, 1)
    name_b = output_name(card_b, tmp_path, 1)

    assert name_a != name_b
    assert name_a.startswith("100MEDIA_A001_C001_")
    assert name_b.startswith("100MEDIA_A001_C001_")


def test_output_name_is_deterministic_and_hash_is_the_relative_path(tmp_path):
    clip = tmp_path / "DAY_1" / "clip one.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")

    name = output_name(clip, tmp_path, 3)
    assert name == output_name(clip, tmp_path, 3)
    assert name.endswith("_frame_3.jpg")
    assert " " not in name

    digest = name.split("_")[-3]
    expected = hashlib.sha1("DAY_1/clip one.mp4".encode("utf-8")).hexdigest()
    assert len(digest) == DISAMBIGUATOR_LENGTH
    assert digest == expected[:DISAMBIGUATOR_LENGTH]


def test_probe_duration_reads_real_clip(make_video, ffmpeg_required):
    clip = make_video("clip.mp4", duration=3)
    assert probe_duration(clip) == pytest.approx(3.0, abs=0.2)


def test_probe_duration_rejects_corrupt_file(tmp_path, ffmpeg_required):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x01\x02not a video")
    with pytest.raises(RuntimeError):
        probe_duration(bad)


def test_process_video_extracts_five_scaled_frames(
    make_video, ffmpeg_required, image_width, tmp_path
):
    clip = make_video("clip.mp4", duration=3)
    out = tmp_path / "out"
    out.mkdir()

    path, ok, message = process_video(clip, out, tmp_path)

    assert ok, message
    frames = sorted(out.glob("*.jpg"))
    assert len(frames) == 5
    assert all(image_width(frame) == 300 for frame in frames)


def test_process_video_reports_corrupt_without_raising(tmp_path, ffmpeg_required):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"garbage")
    out = tmp_path / "out"
    out.mkdir()

    path, ok, message = process_video(bad, out, tmp_path)

    assert ok is False
    assert "corrupt" in message
    assert not list(out.glob("*.jpg"))


def test_main_writes_index_html_and_a_stills_subdir(make_video, ffmpeg_required, tmp_path):
    root = tmp_path / "root"
    make_video("root/DAY_1/clip.mp4", duration=2)
    out = tmp_path / "out"

    main([str(root), str(out)])

    assert (out / "index.html").is_file()
    assert len(sorted((out / "stills").glob("*.jpg"))) == 5

    text = (out / "index.html").read_text(encoding="utf-8")
    assert 'src="stills/' in text
    assert "DAY_1" in text


def test_repeated_runs_into_one_output_accumulate(
    make_video, ffmpeg_required, tmp_path
):
    root = tmp_path / "root"
    make_video("root/DAY_1/one.mp4", duration=2)
    out = tmp_path / "out"
    main([str(root), str(out)])

    # footage added later, same root, same output folder
    make_video("root/DAY_2/two.mp4", duration=2)
    main([str(root), str(out)])

    assert len(sorted((out / "stills").glob("*.jpg"))) == 10

    text = (out / "index.html").read_text(encoding="utf-8")
    assert text.count('class="folder-group"') == 2
    assert "DAY_1" in text and "DAY_2" in text
