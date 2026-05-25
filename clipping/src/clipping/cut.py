"""Cut a clip around a highlight timestamp and reformat to 9:16 vertical.

Inputs are the rolling segment files written by `ingest.Capture`. Each
segment is `segment_seconds` long and they're numbered seg_000000.mp4,
seg_000001.mp4, ...; ffmpeg writes them with -reset_timestamps 1 so the
PTS inside each file starts at 0.

We resolve a (start, end) range in capture-relative seconds back to a list
of segments plus in-segment offsets, then run ffmpeg twice:
  1. concat the relevant segments (stream-copy, lossless)
  2. cut, re-encode, and reformat 9:16 in a single pipeline

The reformat is a center-crop by default. The crop preserves the middle
9:16 column of the 16:9 source. This drops the sides; that's the standard
trade-off for short-form vertical content.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class CutResult:
    output_path: Path
    duration: float
    source_start: float    # capture-relative start
    source_end: float      # capture-relative end


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
    )
    return float(out.strip())


def _segments_covering(
    segments_dir: Path, start: float, end: float
) -> list[tuple[Path, float, float]]:
    """Return [(path, segment_start_in_capture, segment_duration)] for segments
    that overlap [start, end]. We assume segments are in chronological order
    and named seg_NNNNNN.mp4; we use their actual durations rather than the
    nominal segment_seconds so a final short segment is handled correctly."""
    # Live captures write .ts (mpegts); offline `process` mode symlinks .ts too.
    files = sorted(list(segments_dir.glob("seg_*.ts")) + list(segments_dir.glob("seg_*.mp4")))
    if not files:
        return []
    durations = [_ffprobe_duration(f) for f in files]
    cumulative = [0.0]
    for d in durations:
        cumulative.append(cumulative[-1] + d)
    out: list[tuple[Path, float, float]] = []
    for i, f in enumerate(files):
        seg_start = cumulative[i]
        seg_end = cumulative[i + 1]
        if seg_end <= start or seg_start >= end:
            continue
        out.append((f, seg_start, durations[i]))
    return out


def cut_clip(
    segments_dir: Path,
    source_start: float,
    source_end: float,
    output_path: Path,
    *,
    target_width: int = 1080,
    target_height: int = 1920,
    crf: int = 20,
    audio_bitrate: str = "128k",
) -> CutResult:
    """Cut [source_start, source_end] from the rolling segments, write a
    9:16 vertical mp4 to output_path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    covering = _segments_covering(segments_dir, source_start, source_end)
    if not covering:
        raise ValueError(f"no segments cover [{source_start:.1f}, {source_end:.1f}]")

    seg_start_global = covering[0][1]
    # Time inside the concatenated input where our clip begins
    in_offset = max(0.0, source_start - seg_start_global)
    duration = source_end - source_start

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for path, _, _ in covering:
            f.write(f"file '{path.resolve()}'\n")
        list_path = f.name

    # Vertical center-crop: from any landscape source, take the middle column
    # at the source's height, then scale to target. `force_original_aspect_ratio`
    # plus `pad` is the fallback for unusual aspect ratios.
    vf = (
        f"crop=ih*9/16:ih,"
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height}"
    )

    cmd = [
        "ffmpeg", "-y", "-loglevel", "warning",
        "-f", "concat", "-safe", "0",
        "-ss", f"{in_offset:.3f}",
        "-i", list_path,
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        str(output_path),
    ]

    log.info("cutting clip: %s -> %s (%.1fs)", source_start, output_path.name, duration)
    subprocess.run(cmd, check=True)
    Path(list_path).unlink(missing_ok=True)

    return CutResult(
        output_path=output_path,
        duration=duration,
        source_start=source_start,
        source_end=source_end,
    )


def cut_around(
    segments_dir: Path,
    highlight_ts: float,
    output_path: Path,
    *,
    pre: float = 8.0,
    post: float = 20.0,
    **kwargs,
) -> CutResult:
    return cut_clip(
        segments_dir,
        source_start=max(0.0, highlight_ts - pre),
        source_end=highlight_ts + post,
        output_path=output_path,
        **kwargs,
    )


def write_sidecar(output_path: Path, payload: dict) -> None:
    """Write a JSON sidecar next to the clip with whatever metadata the caller
    cares to record (score breakdown, source channel, captured-at timestamp)."""
    sidecar = output_path.with_suffix(".json")
    sidecar.write_text(json.dumps(payload, indent=2, default=str))
