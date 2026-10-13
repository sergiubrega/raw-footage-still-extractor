# Raw Footage Still Extractor

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![CI](https://github.com/sergiubrega/raw-footage-still-extractor/actions/workflows/ci.yml/badge.svg)

A fast, parallel CLI tool built in Python to extract 5 representative low-resolution JPEGs (300px) from raw video files across deep directory structures using FFmpeg fast-seeking, then build a browsable two-pane HTML gallery.

## Prerequisites

- **Python 3.10+** (declared as `requires-python = ">=3.10"` in `pyproject.toml`)
- **FFmpeg & FFprobe** available in `PATH`

> On macOS, Homebrew's build bundles both: `brew install ffmpeg`. Note the
> `.pkg` installer only updates `PATH` for *new* shells — an already-open
> terminal needs `eval "$(/opt/homebrew/bin/brew shellenv)"` or a new tab.

## Supported formats

The default scan covers 38 common video extensions, matched case-insensitively
(`.MP4` == `.mp4`):

```
.3g2 .3gp .asf .avi .divx .dv .f4v .flv .insv .lrv .m1v .m2t .m2ts .m2v
.m4v .mkv .mod .mov .mp4 .mpe .mpeg .mpg .mpv .mts .mxf .nuv .ogv .qt .rm
.rmvb .tod .tp .trp .ts .vob .webm .wmv .y4m
```

Override the set with `--extensions` (dots optional, commas separate):

```bash
uv run raw-footage-still-extractor "<ROOT>" "<OUT>" --extensions ".mp4,.mov,.mxf"
```

Because ffmpeg identifies containers by **content**, this list is only a *discovery* filter — it decides which files get probed, not what can be read. An unusual extension still probes fine once it is listed.

**Deliberately excluded:** camera-RAW formats ffmpeg cannot demux without vendor SDKs — `.braw` (Blackmagic), `.r3d` (RED), `.ari` (ARRI), `.crm` (Canon), `.dng` (CinemaDNG). Listing them would only produce guaranteed probe failures; transcode/proxy those first.

## Installation & Setup

The project is managed with [uv](https://docs.astral.sh/uv/), which provisions
Python 3.10 and the package into a local `.venv` automatically — **no manual
activation required**. `uv run` syncs the environment on first use and reuses it
afterwards.

```bash
uv run python -m raw_footage_still_extractor --help
```

You can also invoke the installed console script directly:

```bash
uv run raw-footage-still-extractor --help
```

<details>
<summary>Alternative: activate the virtualenv manually</summary>

To use a shell where `python` resolves to the project environment:

```bash
uv sync                    # create/update .venv from uv.lock
source .venv/bin/activate
python -m raw_footage_still_extractor --help
deactivate
```

Without `uv run` or activation, a bare `python -m raw_footage_still_extractor`
fails with `No module named raw_footage_still_extractor`: this is a `src/`-layout
package, so it is only importable once installed into the environment.
</details>

```
usage: raw-footage-still-extractor [-h] [-w WORKERS] [-e LIST]
                                   root_dir output_dir

Extract 5 stills (10/30/50/70/90%) from every video file under a root
directory, into a flat output directory.

positional arguments:
  root_dir              root folder to search recursively
  output_dir            flat folder for the JPEG stills

options:
  -h, --help            show this help message and exit
  -w WORKERS, --workers WORKERS
                        number of worker processes (default: all CPU cores)
  -e LIST, --extensions LIST
                        comma-separated extensions to scan, replacing the
                        default set (e.g. ".mp4,.mov,.mxf"). Default: .3g2,
                        .3gp, .asf, .avi, .divx, .dv, .f4v, .flv, .insv, .lrv,
                        .m1v, .m2t, .m2ts, .m2v, .m4v, .mkv, .mod, .mov, .mp4,
                        .mpe, .mpeg, .mpg, .mpv, .mts, .mxf, .nuv, .ogv, .qt,
                        .rm, .rmvb, .tod, .tp, .trp, .ts, .vob, .webm, .wmv,
                        .y4m
```

## Usage

### Basic Extraction

Extract stills from a raw footage directory into a flat output folder:

```bash
uv run python -m raw_footage_still_extractor /path/to/630GB_raw_footage /path/to/output_stills
```

### Custom Worker Count

By default, the script saturates all available CPU cores (`os.cpu_count()`). To limit core usage during background execution:

```bash
uv run python -m raw_footage_still_extractor /path/to/raw_footage /path/to/output_stills --workers 4
```

## Output Naming Schema

Files are dumped into a flat directory following a collision-resistant structure:

```
{parent_folder}_{file_stem}_{path_hash}_frame_{1-5}.jpg
```

- `{parent_folder}` — the video's immediate parent directory name.
- `{file_stem}` — the filename without its extension.
- `{path_hash}` — the first 12 hex chars of `sha1(path relative to root_dir)`. This guarantees uniqueness for files that share both a parent name and a stem across different subtrees (e.g. `CARD_01/DCIM/100MEDIA/A001_C001.MXF` vs `CARD_02/DCIM/100MEDIA/A001_C001.MXF`).
- `{1-5}` — the frame index, corresponding to 10%, 30%, 50%, 70%, and 90% of duration.
- Spaces in any component are replaced with underscores.

## Static HTML Gallery

Build a browsable, self-contained `index.html` from an extracted stills folder:

```bash
uv run raw-footage-still-gallery /path/to/output_stills
```

This writes `index.html` directly into the stills directory and prints its absolute path (⌘-click it to open). Every `<img>` carries `loading="lazy"`, so thousands of stills load without freezing the browser.

### Layout: a two-pane media bin

![The generated gallery: a folder sidebar on the left, grouped clip stills on the right](docs/gallery.png)

The page is a self-contained app (no frameworks, no build step, no network):

- **Left sidebar** — fixed 280px, independently scrolling, lists **Show All** plus one entry per folder (full relative path, so folders that merely share a basename stay distinguishable).
- **Right gallery pane** — fills the remaining space and scrolls on its own; each folder is a `<div class="folder-group" data-folder="…">` containing its `<h2>` and clip cards.
- **Filtering** — inline vanilla JS matches the clicked item's `data-target` against each group's `data-folder` (`display: block/none`) and moves the `.active` highlight.

### Grouping: why `--source-root` exists

The naming schema joins parent and stem with `_`, and `_` is legal inside both — so `100MEDIA_A001_C001_2c740e9fad5f_frame_1.jpg` **cannot** be split back into `parent` + `stem` from the filename alone (it could be `100MEDIA`/`A001_C001` or `100MEDIA_A001`/`C001`). Two modes:

- **Default** — groups the five frames per clip and lists clips flat. No hierarchy is invented.
- **`--source-root /path/to/raw_footage`** — re-walks the footage tree (file names only, no decoding), recomputes each clip's path hash, and restores the **exact** hierarchy, rendering an `<h2>` per parent folder. Requires no re-extraction.

```bash
uv run raw-footage-still-gallery /path/to/output_stills --source-root /path/to/raw_footage
```

## Key Implementation Details

- **Fast-Seeking (`-ss` before `-i`):** Seeks directly to keyframes near 10%, 30%, 50%, 70%, and 90% of duration without decoding whole streams. Tradeoff: the extracted frame snaps to the nearest preceding keyframe, so it can land up to one GOP *before* the exact mark.
- **Resiliency:** Skips corrupt files (ffprobe failure) and logs them to stdout without halting the batch process.
- **Parallel Processing:** Uses Python `ProcessPoolExecutor` to bypass the GIL and utilize all CPU cores on Apple Silicon.

## Development

```bash
uv sync          # create the env (includes the dev group: pytest)
uv run pytest    # 21 tests; media tests auto-skip if ffmpeg/ffprobe are absent
```

## Releasing

1. Bump `version` in `pyproject.toml`.
2. Tag and push the tag:

   ```bash
   git tag -a v0.1.0 -m "v0.1.0"
   git push origin v0.1.0
   ```

3. Publish a GitHub Release for that tag. `.github/workflows/publish.yml` then builds the sdist + wheel and uploads them to PyPI using **Trusted Publishing** (OIDC) — no API token is stored in the repo.

**One-time PyPI setup** — on PyPI go to *Account → Publishing → Add a pending publisher* and enter:

| Field | Value |
| --- | --- |
| PyPI project name | `raw-footage-still-extractor` |
| Owner | `sergiubrega` |
| Repository name | `raw-footage-still-extractor` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

## License

MIT © 2026 Sergiu Brega — see [LICENSE](LICENSE).
