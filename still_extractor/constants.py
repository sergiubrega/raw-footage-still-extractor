"""Constants shared by the extractor and the gallery renderer.

They live in their own module so ``extractor`` can import ``gallery`` (which needs
``FRAME_FRACTIONS`` and ``DISAMBIGUATOR_LENGTH``) without a circular import.
"""

# Extensions scanned for, matched case-insensitively via Path.suffix.lower().
#
# ffmpeg detects the container by CONTENT, so this list is only a *discovery*
# filter — it decides which files we bother to probe, not what we can read. That
# also means an unusual extension for a supported container can be added with
# --extensions. Deliberately excluded are camera-RAW formats ffmpeg cannot demux
# without vendor SDKs (.braw, .r3d, .ari, .crm, .dng, .mxf-wrapped vendor RAW):
# listing them would only produce guaranteed probe failures.
VIDEO_EXTENSIONS = frozenset(
    {
        ".3g2", ".3gp", ".asf", ".avi", ".divx", ".dv", ".f4v", ".flv",
        ".insv", ".lrv", ".m1v", ".m2t", ".m2ts", ".m2v", ".m4v", ".mkv",
        ".mod", ".mov", ".mp4", ".mpe", ".mpeg", ".mpg", ".mpv", ".mts",
        ".mxf", ".nuv", ".ogv", ".qt", ".rm", ".rmvb", ".tod", ".tp", ".trp",
        ".ts", ".vob", ".webm", ".wmv", ".y4m",
    }
)

# Human-readable default list, shown in --help.
DEFAULT_EXTENSIONS_LABEL = ", ".join(sorted(VIDEO_EXTENSIONS))

# Fractions of total duration at which a still is captured.
FRAME_FRACTIONS = (0.10, 0.30, 0.50, 0.70, 0.90)
FRAME_COUNT = len(FRAME_FRACTIONS)

SCALE_FILTER = "scale=300:-1"
JPEG_QUALITY = "2"  # -q:v 2

# Hex chars of the relative-path digest used to disambiguate output filenames.
# 12 chars = 48 bits; collisions are negligible even at millions of files.
DISAMBIGUATOR_LENGTH = 12

# Output layout:  <output_dir>/index.html  +  <output_dir>/stills/*.jpg
STILLS_SUBDIR = "stills"
INDEX_FILENAME = "index.html"

# Gallery grouping keys.
FLAT_KEY = "__flat__"  # clips whose folder could not be resolved in the source tree
ALL_KEY = "__all__"  # the sidebar's "Show All" sentinel
