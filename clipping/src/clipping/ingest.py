"""Capture a Twitch livestream into rolling MP4 segments on disk.

Shells out to streamlink (HLS pull) piped into ffmpeg (segment muxer). Both
must be installed and on PATH. streamlink also serves as the live-detector:
it exits non-zero with a recognizable message when the channel is offline.
"""
from __future__ import annotations

import logging
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

OFFLINE_TOKENS = ("no playable streams", "is offline", "no streams found")


@dataclass
class CaptureConfig:
    channel: str
    output_dir: Path
    quality: str = "480p,worst"           # streamlink quality selector
    segment_seconds: int = 30              # ffmpeg segment length
    retention_seconds: int = 3600          # delete segments older than this
    poll_offline_seconds: int = 60         # retry interval when channel offline


@dataclass
class Capture:
    config: CaptureConfig
    segments_dir: Path
    _proc: subprocess.Popen | None = None
    _gc_thread: threading.Thread | None = None
    _started_at: float = 0.0
    _stop_event: threading.Event = field(default_factory=threading.Event)

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def started_at(self) -> float:
        return self._started_at

    def iter_segments(self) -> Iterator[Path]:
        """Yield segment paths in creation order. Skips the most recent file
        (still being written by ffmpeg)."""
        files = sorted(self.segments_dir.glob("seg_*.ts"))
        if len(files) <= 1:
            return iter([])
        return iter(files[:-1])

    def stop(self) -> None:
        self._stop_event.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.send_signal(signal.SIGTERM)
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._gc_thread:
            self._gc_thread.join(timeout=2)


def _verify_tools() -> None:
    for tool in ("streamlink", "ffmpeg"):
        if not shutil.which(tool):
            raise RuntimeError(
                f"{tool} not found on PATH. Install it (brew install {tool} on macOS) and retry."
            )


def _gc_loop(capture: Capture) -> None:
    """Background thread: delete segments older than retention_seconds."""
    while not capture._stop_event.wait(timeout=30):
        cutoff = time.time() - capture.config.retention_seconds
        for f in capture.segments_dir.glob("seg_*.ts"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except FileNotFoundError:
                pass


def start_capture(config: CaptureConfig) -> Capture:
    """Start streamlink|ffmpeg capture pipeline. Returns a Capture handle.
    Blocks briefly to confirm streamlink could connect; raises ChannelOffline
    if the channel isn't live."""
    _verify_tools()

    config.output_dir.mkdir(parents=True, exist_ok=True)
    segments_dir = config.output_dir / "segments"
    if segments_dir.exists():
        # fresh capture: clear stale segments from a prior run
        for f in list(segments_dir.glob("seg_*.ts")) + list(segments_dir.glob("seg_*.mp4")):
            f.unlink(missing_ok=True)
    segments_dir.mkdir(parents=True, exist_ok=True)

    url = f"https://www.twitch.tv/{config.channel}"
    sl_cmd = ["streamlink", "--stdout", "--retry-streams", "0", "--retry-max", "0", url, config.quality]
    # MPEG-TS segments: no moov-atom problem (streaming-friendly container
    # designed for partial reads). Matches what HLS delivers anyway.
    ff_cmd = [
        "ffmpeg", "-y",
        "-loglevel", "warning",
        "-i", "pipe:0",
        "-c", "copy",
        "-map", "0",
        "-f", "segment",
        "-segment_format", "mpegts",
        "-segment_time", str(config.segment_seconds),
        "-reset_timestamps", "1",
        "-strftime", "0",
        str(segments_dir / "seg_%06d.ts"),
    ]

    log.info("starting capture: %s", " ".join(sl_cmd))
    sl = subprocess.Popen(sl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ff = subprocess.Popen(ff_cmd, stdin=sl.stdout, stderr=subprocess.PIPE)
    if sl.stdout:
        sl.stdout.close()  # let ffmpeg own the pipe

    capture = Capture(config=config, segments_dir=segments_dir, _proc=ff, _started_at=time.time())

    # Wait briefly to see if streamlink succeeds. If the channel is offline,
    # streamlink emits "no playable streams" on stderr and exits.
    deadline = time.time() + 8
    while time.time() < deadline:
        if sl.poll() is not None:
            stderr = sl.stderr.read().decode("utf-8", "ignore") if sl.stderr else ""
            ff.terminate()
            if any(tok in stderr.lower() for tok in OFFLINE_TOKENS):
                raise ChannelOffline(config.channel)
            raise RuntimeError(f"streamlink failed: {stderr.strip()[:300]}")
        if any(segments_dir.glob("seg_*.ts")):
            # ffmpeg produced its first segment, capture is live
            break
        time.sleep(0.4)

    gc = threading.Thread(target=_gc_loop, args=(capture,), daemon=True)
    gc.start()
    capture._gc_thread = gc

    log.info("capture live: segments going to %s", segments_dir)
    return capture


class ChannelOffline(RuntimeError):
    def __init__(self, channel: str):
        super().__init__(f"channel '{channel}' is offline")
        self.channel = channel


def wait_until_live(config: CaptureConfig) -> Capture:
    """Poll start_capture until the channel goes live. Returns the live Capture."""
    while True:
        try:
            return start_capture(config)
        except ChannelOffline:
            log.info("offline; retrying in %ds", config.poll_offline_seconds)
            time.sleep(config.poll_offline_seconds)
