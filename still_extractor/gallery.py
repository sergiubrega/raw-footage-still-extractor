"""Render a self-contained, two-pane HTML gallery over an extracted stills directory.

Called by :mod:`still_extractor` after extraction; there is no separate command.
Produces ``<output_dir>/index.html`` — a fixed sidebar listing every source folder
(a media-bin style navigator) plus a scrollable gallery pane — with inline vanilla
JS doing the filtering. Standard library only, no frameworks, no build step.

Filename schema consumed (see :mod:`still_extractor.extractor`):

    {parent}_{stem}_{digest}_frame_{1-5}.jpg

``{parent}`` and ``{stem}`` are joined with ``_`` and ``_`` is legal inside both,
so the pair cannot be split reliably from the filename alone. The ``{digest}``
(``sha1(relative_path)[:DISAMBIGUATOR_LENGTH]``) is what makes exact recovery
possible: :func:`index_from_videos` recomputes each hash from the video list the
extractor already discovered, and joins it back to the stills. That costs no extra
directory walk — unlike re-walking the footage tree to rebuild the hierarchy.
"""

import hashlib
import html
import re
from pathlib import Path
from urllib.parse import quote

from .constants import (
    ALL_KEY,
    DISAMBIGUATOR_LENGTH,
    FLAT_KEY,
    FRAME_COUNT,
    FRAME_FRACTIONS,
)

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


def index_from_videos(videos: list[Path], root_dir: Path) -> dict[str, dict[str, str]]:
    """Map ``digest -> {parent, parent_rel, name, relative}`` for discovered videos.

    The extractor already has the video list in hand, so recovering the hierarchy
    this way costs no extra directory walk. ``relative`` is the path relative to
    ``root_dir``, which is exactly what the output-name digest was derived from.
    """
    root = root_dir.resolve()
    index: dict[str, dict[str, str]] = {}
    for path in videos:
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:  # not under root_dir
            continue
        digest = hashlib.sha1(str(relative).encode("utf-8")).hexdigest()[:DISAMBIGUATOR_LENGTH]
        index[digest] = {
            "parent": path.parent.name,
            "parent_rel": str(relative.parent),
            "name": path.name,
            "relative": str(relative),
        }
    return index


def collect_clips(stills_dir: Path) -> dict[str, dict]:
    """Group every still in ``stills_dir`` by digest into clips (one per video)."""
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


def _clip_html(clip: dict, image_prefix: str) -> str:
    frames = clip["frames"]
    figures = []
    for index in range(1, FRAME_COUNT + 1):
        name = frames.get(index)
        if name is None:
            continue
        percent = f"{int(FRAME_FRACTIONS[index - 1] * 100)}%"
        figures.append(
            '<figure class="frame">'
            f'<img src="{image_prefix}{quote(name)}"'
            f' alt="{html.escape(clip["title"])} @ {percent}"'
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


def render_html(
    sections: list[tuple[str, str, list[dict]]],
    *,
    title: str,
    note: str = "",
    image_prefix: str = "",
) -> str:
    """Render the full HTML document. ``image_prefix`` is prepended to each src."""
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
            f"{''.join(_clip_html(c, image_prefix) for c in clips)}"
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


def build_gallery(
    stills_dir: Path,
    output_html: Path,
    *,
    index: dict[str, dict[str, str]] | None = None,
    image_prefix: str = "",
    title: str | None = None,
) -> Path | None:
    """Write ``output_html`` covering every still in ``stills_dir``.

    Covering the whole directory (not just the current run) is what lets repeated
    extractions into the same output folder accumulate into one gallery. Returns
    the written path, or ``None`` when there are no stills to show.
    """
    clips = collect_clips(stills_dir)
    if not clips:
        return None

    attach_hierarchy(clips, index or {})
    sections = build_sections(list(clips.values()))

    unresolved = sum(len(c) for key, _, c in sections if key == FLAT_KEY)
    note = ""
    if unresolved:
        note = (
            f'<p class="note">{unresolved} clip(s) could not be matched to a folder in the '
            "source tree, so they are listed flat. They were probably extracted from a "
            "different root, or the source file has since moved.</p>"
        )

    output_html.write_text(
        render_html(
            sections,
            title=title or f"Stills \u2014 {output_html.parent.name}",
            note=note,
            image_prefix=image_prefix,
        ),
        encoding="utf-8",
    )
    return output_html
