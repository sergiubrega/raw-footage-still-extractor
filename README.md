# Raw Footage Still Extractor

A fast, parallel CLI tool built in Python to extract 5 representative low-resolution JPEGs (300px) from raw video files (`.mp4`, `.mxf`) across deep directory structures using FFmpeg fast-seeking.

## Prerequisites

- **Python 3.10+** (declared as `requires-python = ">=3.10"` in `pyproject.toml`)
- **FFmpeg & FFprobe** available in `PATH`

> On macOS, Homebrew's build bundles both: `brew install ffmpeg`. Note the
> `.pkg` installer only updates `PATH` for *new* shells — an already-open
> terminal needs `eval "$(/opt/homebrew/bin/brew shellenv)"` or a new tab.

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
usage: raw-footage-still-extractor [-h] [-w WORKERS] root_dir output_dir

Extract 5 stills (10/30/50/70/90%) from every .mp4/.mxf file under a root
directory, into a flat output directory.

positional arguments:
  root_dir              root folder to search recursively
  output_dir            flat folder for the JPEG stills

options:
  -h, --help            show this help message and exit
  -w WORKERS, --workers WORKERS
                        number of worker processes (default: all CPU cores)
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

## Key Implementation Details

- **Fast-Seeking (`-ss` before `-i`):** Seeks directly to keyframes near 10%, 30%, 50%, 70%, and 90% of duration without decoding whole streams. Tradeoff: the extracted frame snaps to the nearest preceding keyframe, so it can land up to one GOP *before* the exact mark.
- **Resiliency:** Skips corrupt files (ffprobe failure) and logs them to stdout without halting the batch process.
- **Parallel Processing:** Uses Python `ProcessPoolExecutor` to bypass the GIL and utilize all CPU cores on Apple Silicon.
