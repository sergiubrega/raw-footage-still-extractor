"""Build a static, self-contained two-pane HTML gallery from an extracted stills directory.

Reads the flat output directory produced by :mod:`still_extractor`
and writes a single ``index.html`` next to the JPEGs: a fixed sidebar listing
every folder (a media-bin style navigator) and a scrollable gallery pane, with
inline vanilla JS doing the filtering. Standard library only — no frameworks.

Filename schema consumed (see the extractor):

    {parent}_{stem}_{digest}_frame_{1-5}.jpg

``{parent}`` and ``{stem}`` are joined with ``_``, and ``_`` is legal inside
both, so the pair cannot be split reliably from the filename alone. The
``{digest}`` (``sha1(relative_path)[:DISAMBIGUATOR_LENGTH]``) is what makes exact
recovery possible: pass ``--source-root`` and the tool re-walks the footage tree,
recomputes each hash, and restores the true parent folder / stem / relative path.
Without ``--source-root`` the gallery still groups the five frames per clip, but
lists them in a single flat group instead of inventing a hierarchy it cannot know.
"""

import argparse
import hashlib
import html
import re
import sys
from pathlib import Path
from urllib.parse import quote

from .extractor import DISAMBIGUATOR_LENGTH, FRAME_FRACTIONS

FRAME_COUNT = len(FRAME_FRACTIONS)

# Folder key for clips whose hierarchy could not be recovered.
FLAT_KEY = "__flat__"

# Sentinel the sidebar's "Show All" item filters on.
ALL_KEY = "__all__"

_FRAME_PATTERN = re.compile(
    rf"^(?P<prefix>.+)_(?P<digest>[0-9a-f]{{{DISAMBIGUATOR_LENGTH}}})"
    rf"_frame_(?P<frame>\d+)\.jpg$"
)

_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  display: flex;
  overflow: hidden;
  background: #1e1e1e;
  color: #e6e6e6;
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* ---- left sidebar (media bin) ---- */
.sidebar {
  flex: 0 0 280px;
  width: 280px;
  overflow-y: auto;
  background: #181818;
  border-right: 1px solid #333;
  padding: 16px 12px 32px;
}
.brand { padding: 0 4px 12px; margin-bottom: 12px; border-bottom: 1px solid #2c2c2c; }
h1 { font-size: 15px; margin: 0 0 4px; font-weight: 600; }
.meta { margin: 0; color: #8a8a8a; font-size: 11px; }
.nav { display: flex; flex-direction: column; gap: 2px; }
.nav-item {
  padding: 7px 9px;
  border: 1px solid transparent;
  border-radius: 5px;
  cursor: pointer;
  font-size: 12px;
  color: #c8c8c8;
  user-select: none;
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.nav-item:hover { background: #2a2d2e; color: #fff; }
.nav-item.active { background: #0e639c; border-color: #1177bb; color: #fff; }
.nav-all { font-family: inherit; font-weight: 600; margin-bottom: 6px; }

/* ---- right gallery pane ---- */
.main { flex: 1 1 auto; overflow-y: auto; padding: 20px 24px 80px; }
.note {
  margin: 0 0 18px;
  padding: 10px 12px;
  color: #d7ba7d;
  font-size: 12px;
  max-width: 90ch;
  background: #2a2416;
  border: 1px solid #4a3f22;
  border-radius: 6px;
}
.note code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: #e6d7ae; }
.folder-group { margin-bottom: 10px; }
h2 {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #9cdcfe;
  margin: 24px 0 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid #333;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  word-break: break-all;
}
.folder-group:first-of-type h2 { margin-top: 0; }
.clip {
  background: #252526;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 14px;
}
.clip-title {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: #cecece;
  margin-bottom: 8px;
  word-break: break-all;
}
.frames { display: flex; flex-wrap: wrap; gap: 8px; }
.frame { margin: 0; }
.frame img {
  display: block;
  width: 300px;
  height: auto;
  border-radius: 4px;
  background: #000;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.frame img:hover {
  transform: scale(1.06);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.65);
  position: relative;
  z-index: 3;
}
.frame figcaption {
  text-align: center; color: #8a8a8a; font-size: 11px; margin-top: 4px;
}
"""

_JS = """
(function () {
  var items = Array.prototype.slice.call(document.querySelectorAll(".nav-item"));
  var groups = Array.prototype.slice.call(document.querySelectorAll(".folder-group"));

  function select(item) {
    var target = item.getAttribute("data-target");
    groups.forEach(function (group) {
      var match = target === "__all__" || group.getAttribute("data-folder") === target;
      group.style.display = match ? "block" : "none";
    });
    items.forEach(function (other) { other.classList.remove("active"); });
    item.classList.add("active");
  }

  items.forEach(function (item) {
    item.addEventListener("click", function () { select(item); });
  });
})();
"""


def parse_still_name(name: str) -> tuple[str, str, int] | None:
    """Split ``{prefix}_{digest}_frame_{n}.jpg``; return None if it doesn't match."""
    match = _FRAME_PATTERN.match(name)
    if match is None:
        return None
    frame = int(match.group("frame"))
    if not 1 <= frame <= FRAME_COUNT:
        return None
    return match.group("prefix"), match.group("digest"), frame


def source_index(source_root: Path, wanted: set[str]) -> dict[str, dict[str, str]]:
    """Map ``digest -> {parent, parent_rel, name, relative}`` for the wanted digests.

    Walks the footage tree and hashes every file's path relative to ``root``,
    keeping only the digests the stills actually need. Filtering on the wanted set
    (rather than on a video-extension list) keeps the gallery correct no matter
    which ``--extensions`` the extractor was run with. Only file names are read —
    no media decoding — so this is cheap even over a large tree.
    """
    root = source_root.resolve()
    index: dict[str, dict[str, str]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.resolve().relative_to(root)
        digest = hashlib.sha1(str(relative).encode("utf-8")).hexdigest()[:DISAMBIGUATOR_LENGTH]
        if digest not in wanted:
            continue
        index[digest] = {
            "parent": path.parent.name,
            "parent_rel": str(relative.parent),
            "name": path.name,
            "relative": str(relative),
        }
    return index


def collect_clips(stills_dir: Path) -> dict[str, dict]:
    """Group stills by digest into clips (one per video)."""
    clips: dict[str, dict] = {}
    for path in sorted(stills_dir.glob("*.jpg")):
        parsed = parse_still_name(path.name)
        if parsed is None:
            continue
        prefix, digest, frame = parsed
        clip = clips.setdefault(
            digest, {"digest": digest, "prefix": prefix, "frames": {}}
        )
        clip["frames"][frame] = path.name
    return clips


def attach_hierarchy(clips: dict[str, dict], index: dict[str, dict[str, str]]) -> None:
    """Fill in parent / stem / display title for each clip from the source index."""
    for clip in clips.values():
        meta = index.get(clip["digest"])
        if meta is None:
            clip.update(parent=None, parent_rel=None, title=clip["prefix"])
        else:
            clip.update(
                parent=meta["parent"],
                parent_rel=meta["parent_rel"],
                title=meta["name"],
            )


def build_sections(clips: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """Group clips into ``(folder_key, display_title, clips)`` triples for the UI.

    ``folder_key`` is the value written to ``data-folder`` / ``data-target``; the
    display title is what the sidebar and ``<h2>`` show. Grouping is by the
    *relative* parent path, not just the parent name, so two folders that merely
    share a basename (e.g. two ``100MEDIA`` dumps) stay separate.
    """
    known = [c for c in clips if c["parent_rel"] is not None]
    unknown = [c for c in clips if c["parent_rel"] is None]

    sections: list[tuple[str, str, list[dict]]] = []
    grouped: dict[str, list[dict]] = {}
    for clip in known:
        grouped.setdefault(clip["parent_rel"], []).append(clip)
    for parent_rel in sorted(grouped, key=str.lower):
        label = parent_rel if parent_rel != "." else "(root)"
        sections.append(
            (parent_rel, label, sorted(grouped[parent_rel], key=lambda c: c["title"].lower()))
        )
    if unknown:
        sections.append(
            (
                FLAT_KEY,
                "All clips (no hierarchy)",
                sorted(unknown, key=lambda c: c["title"].lower()),
            )
        )
    return sections


def _clip_html(clip: dict) -> str:
    frames = clip["frames"]
    figures = []
    for index in range(1, FRAME_COUNT + 1):
        name = frames.get(index)
        if name is None:
            continue
        percent = f"{int(FRAME_FRACTIONS[index - 1] * 100)}%"
        figures.append(
            '<figure class="frame">'
            f'<img src="{quote(name)}" alt="{html.escape(clip["title"])} @ {percent}"'
            ' loading="lazy" decoding="async">'
            f"<figcaption>{percent}</figcaption>"
            "</figure>"
        )
    return (
        '<article class="clip">'
        f'<div class="clip-title">{html.escape(clip["title"])}</div>'
        f'<div class="frames">{"".join(figures)}</div>'
        "</article>"
    )


def render_html(sections: list[tuple[str, str, list[dict]]], *, title: str, note: str) -> str:
    total_clips = sum(len(clips) for _, _, clips in sections)
    total_images = sum(len(c["frames"]) for _, _, clips in sections for c in clips)

    nav = [f'<div class="nav-item nav-all active" data-target="{ALL_KEY}">Show All</div>']
    body = []
    for folder_key, display_title, clips in sections:
        key_attr = html.escape(folder_key, quote=True)
        nav.append(
            f'<div class="nav-item" data-target="{key_attr}" '
            f'title="{html.escape(display_title, quote=True)}">{html.escape(display_title)}</div>'
        )
        body.append(
            f'<div class="folder-group" data-folder="{key_attr}">'
            f"<h2>{html.escape(display_title)}</h2>"
            f"{''.join(_clip_html(c) for c in clips)}"
            "</div>"
        )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        '<aside class="sidebar">\n'
        '<div class="brand">\n'
        f"<h1>{html.escape(title)}</h1>\n"
        f'<p class="meta">{total_clips} clip(s) &middot; {total_images} still(s)</p>\n'
        "</div>\n"
        f'<nav class="nav">\n{"".join(nav)}\n</nav>\n'
        "</aside>\n"
        '<main class="main">\n'
        f"{note}\n"
        f"{''.join(body)}\n"
        "</main>\n"
        f"<script>{_JS}</script>\n"
        "</body>\n</html>\n"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="raw-footage-still-gallery",
        description="Build a static two-pane index.html gallery from an extracted stills directory.",
    )
    parser.add_argument("stills_dir", type=Path, help="flat directory of extracted JPEG stills")
    parser.add_argument(
        "-s",
        "--source-root",
        type=Path,
        default=None,
        help="original footage root; recovers the exact parent/stem hierarchy via the path hash",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output HTML path (default: <stills_dir>/index.html)",
    )
    parser.add_argument("--title", default=None, help="page title (default: stills dir name)")
    args = parser.parse_args(argv)

    stills_dir = args.stills_dir.resolve()
    if not stills_dir.is_dir():
        sys.exit(f"Error: not a directory: {stills_dir}")

    clips = collect_clips(stills_dir)
    if not clips:
        sys.exit(f"Error: no stills matching the naming schema found in {stills_dir}")

    index: dict[str, dict[str, str]] = {}
    if args.source_root is not None:
        if not args.source_root.is_dir():
            sys.exit(f"Error: --source-root is not a directory: {args.source_root}")
        index = source_index(args.source_root, set(clips))
    attach_hierarchy(clips, index)

    sections = build_sections(list(clips.values()))
    title = args.title or f"Stills \u2014 {stills_dir.name}"

    note = ""
    if args.source_root is None:
        note = (
            '<p class="note">Folder hierarchy unavailable: a name like '
            "<code>100MEDIA_A001_C001_2c740e9fad5f_frame_1.jpg</code> cannot be split "
            "into parent + stem, because <code>_</code> is legal in both. Re-run with "
            "<code>--source-root /path/to/raw_footage</code> to restore the exact "
            "hierarchy from the path hash.</p>"
        )

    output = (args.output or (stills_dir / "index.html")).resolve()
    output.write_text(render_html(sections, title=title, note=note), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
