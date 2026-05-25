"""Score a capture window for highlight-worthiness and pick clips to cut.

Two signals in Phase 1:
- audio loudness: RMS-in-dB over short windows extracted from the captured
  segments' audio track.
- chat velocity: messages-per-bin from a `ChatMonitor` (optional; offline mode
  has no chat data and degrades gracefully).

We z-score both signals against their recent baseline and combine with
configurable weights, then run non-maximum suppression so two highlights
can't sit within `min_gap_seconds` of each other.
"""
from __future__ import annotations

import logging
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)


@dataclass
class Highlight:
    timestamp: float       # seconds from start of capture
    score: float           # combined z-score
    audio_z: float
    chat_z: float
    chat_count: int        # raw chat messages in the bin (for debugging)


# ---- Audio loudness ---------------------------------------------------------

def extract_audio_to_wav(video_paths: Sequence[Path], output_wav: Path, sample_rate: int = 16000) -> None:
    """Concatenate the audio tracks of the given video files into a single
    mono wav at sample_rate Hz. Uses ffmpeg's concat demuxer."""
    if not video_paths:
        raise ValueError("no video paths given")

    # ffmpeg concat demuxer wants a file list, one path per line, escaped.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in video_paths:
            f.write(f"file '{p.resolve()}'\n")
        list_path = f.name

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        str(output_wav),
    ]
    subprocess.run(cmd, check=True)
    Path(list_path).unlink(missing_ok=True)


def loudness_curve(wav_path: Path, window_seconds: float = 1.0) -> list[tuple[float, float]]:
    """Return [(timestamp, loudness_dbfs)] sampled at `window_seconds`.
    Loudness is RMS in dBFS (so silence = -inf, full-scale sine = ~-3 dB)."""
    data, sr = sf.read(str(wav_path), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    samples_per_window = max(1, int(window_seconds * sr))
    n_windows = len(data) // samples_per_window
    curve: list[tuple[float, float]] = []
    for i in range(n_windows):
        chunk = data[i * samples_per_window : (i + 1) * samples_per_window]
        rms = float(np.sqrt(np.mean(chunk * chunk) + 1e-12))
        db = 20.0 * math.log10(rms + 1e-9)
        t = (i + 0.5) * window_seconds
        curve.append((t, db))
    return curve


# ---- Combined scoring -------------------------------------------------------

def _zscore(values: list[float]) -> list[float]:
    if not values:
        return []
    arr = np.asarray(values, dtype=np.float64)
    mu = float(arr.mean())
    sigma = float(arr.std())
    if sigma < 1e-6:
        return [0.0] * len(values)
    return ((arr - mu) / sigma).tolist()


def _resample_to_grid(
    pairs: list[tuple[float, float]], grid: list[float]
) -> list[float]:
    """Nearest-neighbor resample a (t, v) curve onto the given timestamps.
    `pairs` must be sorted by t."""
    if not pairs:
        return [0.0] * len(grid)
    ts = [p[0] for p in pairs]
    vs = [p[1] for p in pairs]
    out: list[float] = []
    j = 0
    for t in grid:
        while j + 1 < len(ts) and abs(ts[j + 1] - t) <= abs(ts[j] - t):
            j += 1
        out.append(vs[j])
    return out


def detect_highlights(
    audio_curve: list[tuple[float, float]],
    chat_curve: list[tuple[float, int]] | None,
    *,
    bin_seconds: float = 2.0,
    alpha: float = 0.6,
    beta: float = 0.4,
    min_score: float = 1.2,
    min_gap_seconds: float = 30.0,
    max_highlights: int | None = None,
) -> list[Highlight]:
    """Combine audio + chat signals, return ranked highlights.

    `alpha` weights audio z-score; `beta` weights chat z-score. When chat is
    None we fall back to alpha=1, beta=0 automatically.
    """
    if not audio_curve:
        return []

    # Build a common time grid at bin_seconds resolution
    start_t = audio_curve[0][0]
    end_t = audio_curve[-1][0]
    grid = []
    t = start_t
    while t <= end_t:
        grid.append(t)
        t += bin_seconds

    audio_on_grid = _resample_to_grid(audio_curve, grid)
    audio_z = _zscore(audio_on_grid)

    chat_pairs_f: list[tuple[float, float]] = (
        [(t, float(c)) for t, c in chat_curve] if chat_curve else []
    )
    if chat_pairs_f:
        chat_on_grid = _resample_to_grid(chat_pairs_f, grid)
        chat_z = _zscore(chat_on_grid)
        chat_raw = [int(round(v)) for v in chat_on_grid]
        weights = (alpha, beta)
    else:
        chat_z = [0.0] * len(grid)
        chat_raw = [0] * len(grid)
        weights = (1.0, 0.0)

    a_w, c_w = weights
    combined = [a_w * a + c_w * c for a, c in zip(audio_z, chat_z)]

    # Build candidate highlights above threshold
    candidates = [
        Highlight(
            timestamp=grid[i],
            score=combined[i],
            audio_z=audio_z[i],
            chat_z=chat_z[i],
            chat_count=chat_raw[i],
        )
        for i in range(len(grid))
        if combined[i] >= min_score
    ]
    candidates.sort(key=lambda h: -h.score)

    # Non-maximum suppression: drop any candidate within min_gap of a kept one
    kept: list[Highlight] = []
    for c in candidates:
        if all(abs(c.timestamp - k.timestamp) >= min_gap_seconds for k in kept):
            kept.append(c)
        if max_highlights and len(kept) >= max_highlights:
            break

    # Return in chronological order for consistent cut order
    kept.sort(key=lambda h: h.timestamp)
    return kept
