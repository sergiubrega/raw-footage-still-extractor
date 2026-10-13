"""Tests for the gallery builder."""

import hashlib
import re

from still_extractor.extractor import DISAMBIGUATOR_LENGTH, output_name
from still_extractor.gallery import (
    ALL_KEY,
    FLAT_KEY,
    attach_hierarchy,
    build_sections,
    collect_clips,
    main,
    parse_still_name,
    render_html,
    source_index,
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
    clip = next(iter(clips.values()))
    assert sorted(clip["frames"]) == [1, 2, 3, 4, 5]


def test_source_index_keeps_only_wanted_digests(tmp_path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    (root / "a" / "x.mp4").write_bytes(b"x")
    (root / "a" / "y.mp4").write_bytes(b"x")

    wanted = {hashlib.sha1(b"a/x.mp4").hexdigest()[:DISAMBIGUATOR_LENGTH]}
    index = source_index(root, wanted)

    assert set(index) == wanted
    assert index[next(iter(wanted))]["name"] == "x.mp4"


def test_hierarchy_recovery_separates_identically_named_folders(tmp_path):
    """The whole point of the path hash: two `100MEDIA` folders stay distinct."""
    root = tmp_path / "root"
    stills = tmp_path / "stills"
    stills.mkdir()

    for card in ("CARD_01", "CARD_02"):
        clip = root / card / "DCIM" / "100MEDIA" / "A001_C001.MXF"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"x")
        for index in range(1, 6):
            _write_still(stills, output_name(clip, root, index))

    clips = collect_clips(stills)
    attach_hierarchy(clips, source_index(root, set(clips)))
    sections = build_sections(list(clips.values()))

    assert [key for key, _, _ in sections] == [
        "CARD_01/DCIM/100MEDIA",
        "CARD_02/DCIM/100MEDIA",
    ]


def test_without_source_root_clips_land_in_one_flat_group(tmp_path):
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
    html = render_html(build_sections(list(clips.values())), title="Test", note="")

    assert 'class="folder-group"' in html
    assert f'data-target="{ALL_KEY}"' in html
    assert ">Show All<" in html
    assert html.count('loading="lazy"') == 5
    assert "height: 100%" in html and "overflow: hidden" in html
    assert ".sidebar {" in html and ".main {" in html

    # the injected script must sit immediately before </body>
    assert re.search(r"<script>.*?</script>\s*</body>\s*</html>\s*$", html, re.S)

    # every sidebar target must match a folder group
    targets = set(re.findall(r'class="nav-item[^"]*" data-target="([^"]*)"', html))
    folders = set(re.findall(r'data-folder="([^"]*)"', html))
    assert targets - {ALL_KEY} == folders


def test_main_writes_index_html_into_the_stills_dir(tmp_path):
    stills = tmp_path / "stills"
    for index in range(1, 6):
        _write_still(stills, f"DAY_1_clip_aaaaaaaaaaaa_frame_{index}.jpg")

    main([str(stills)])

    output = stills / "index.html"
    assert output.is_file()
    assert "Show All" in output.read_text(encoding="utf-8")
