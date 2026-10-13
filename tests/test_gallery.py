"""Tests for the gallery renderer."""

import hashlib
import re

from still_extractor.constants import ALL_KEY, DISAMBIGUATOR_LENGTH, FLAT_KEY
from still_extractor.extractor import output_name
from still_extractor.gallery import (
    attach_hierarchy,
    build_gallery,
    build_sections,
    collect_clips,
    index_from_videos,
    parse_still_name,
    render_html,
)


def _write_still(directory, name: str):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(b"jpeg")


def test_parse_still_name_valid_and_invalid():
    assert parse_still_name("100MEDIA_A001_C001_2c740e9fad5f_frame_1.jpg") == (
        "100MEDIA_A001_C001",
        "2c740e9fad5f",
        1,
    )
    assert parse_still_name("nope.jpg") is None
    assert parse_still_name("a_2c740e9fad5f_frame_9.jpg") is None  # frame out of range
    assert parse_still_name("a_ZZZZZZZZZZZZ_frame_1.jpg") is None  # not hex
    assert parse_still_name("a_2c740e9fad5f_frame_1.png") is None  # wrong suffix


def test_collect_clips_groups_the_five_frames(tmp_path):
    for index in range(1, 6):
        _write_still(tmp_path, f"100MEDIA_A001_C001_2c740e9fad5f_frame_{index}.jpg")

    clips = collect_clips(tmp_path)

    assert len(clips) == 1
    assert sorted(next(iter(clips.values()))["frames"]) == [1, 2, 3, 4, 5]


def test_index_from_videos_maps_the_relative_path(tmp_path):
    root = tmp_path / "root"
    clip = root / "DAY_1" / "clip.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")

    index = index_from_videos([clip], root)

    digest = hashlib.sha1(b"DAY_1/clip.mp4").hexdigest()[:DISAMBIGUATOR_LENGTH]
    assert set(index) == {digest}
    assert index[digest]["parent"] == "DAY_1"
    assert index[digest]["parent_rel"] == "DAY_1"
    assert index[digest]["name"] == "clip.mp4"


def test_index_from_videos_skips_paths_outside_the_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"x")

    assert index_from_videos([outside], root) == {}


def test_hierarchy_recovery_separates_identically_named_folders(tmp_path):
    """The whole point of the path hash: two `100MEDIA` folders stay distinct."""
    root = tmp_path / "root"
    stills = tmp_path / "stills"
    stills.mkdir()

    videos = []
    for card in ("CARD_01", "CARD_02"):
        clip = root / card / "DCIM" / "100MEDIA" / "A001_C001.MXF"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"x")
        videos.append(clip)
        for index in range(1, 6):
            _write_still(stills, output_name(clip, root, index))

    clips = collect_clips(stills)
    attach_hierarchy(clips, index_from_videos(videos, root))
    sections = build_sections(list(clips.values()))

    assert [key for key, _, _ in sections] == [
        "CARD_01/DCIM/100MEDIA",
        "CARD_02/DCIM/100MEDIA",
    ]


def test_unresolved_clips_land_in_one_flat_group(tmp_path):
    stills = tmp_path / "stills"
    for index in range(1, 6):
        _write_still(stills, f"DAY_1_clip_aaaaaaaaaaaa_frame_{index}.jpg")

    clips = collect_clips(stills)
    attach_hierarchy(clips, {})
    sections = build_sections(list(clips.values()))

    assert [key for key, _, _ in sections] == [FLAT_KEY]
    _, title, _ = sections[0]
    assert "no hierarchy" in title


def test_render_html_has_two_pane_wiring(tmp_path):
    stills = tmp_path / "stills"
    for index in range(1, 6):
        _write_still(stills, f"DAY_1_clip_aaaaaaaaaaaa_frame_{index}.jpg")

    clips = collect_clips(stills)
    attach_hierarchy(clips, {})
    html = render_html(
        build_sections(list(clips.values())), title="Test", image_prefix="stills/"
    )

    assert 'class="folder-group"' in html
    assert f'data-target="{ALL_KEY}"' in html
    assert ">Show All<" in html
    assert html.count('loading="lazy"') == 5
    assert 'src="stills/' in html
    assert "height: 100%" in html and "overflow: hidden" in html
    assert ".sidebar {" in html and ".main {" in html

    # the injected script must sit immediately before </body>
    assert re.search(r"<script>.*?</script>\s*</body>\s*</html>\s*$", html, re.S)

    # every sidebar target must match a folder group
    targets = set(re.findall(r'class="nav-item[^"]*" data-target="([^"]*)"', html))
    folders = set(re.findall(r'data-folder="([^"]*)"', html))
    assert targets - {ALL_KEY} == folders


def test_build_gallery_writes_html_beside_the_stills_folder(tmp_path):
    out = tmp_path / "out"
    stills = out / "stills"
    for index in range(1, 6):
        _write_still(stills, f"DAY_1_clip_aaaaaaaaaaaa_frame_{index}.jpg")

    written = build_gallery(stills, out / "index.html", image_prefix="stills/")

    assert written is not None
    assert written == out / "index.html"
    text = written.read_text(encoding="utf-8")
    assert 'src="stills/' in text
    assert "Show All" in text


def test_build_gallery_returns_none_when_there_are_no_stills(tmp_path):
    stills = tmp_path / "out" / "stills"
    stills.mkdir(parents=True)

    assert build_gallery(stills, tmp_path / "out" / "index.html") is None
