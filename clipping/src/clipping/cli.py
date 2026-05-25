"""Command-line entry point for clipping.

Two commands:
  clipping monitor <channel>     live monitor + capture + detect + cut
  clipping process <video.mp4>   offline: detect + cut from an existing file

Both write clips to out/<channel>/<timestamp>_<score>.mp4 plus a JSON
sidecar with the score breakdown.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import tempfile
import time
from pathlib import Path

from . import ingest, chat, chat_kick, score, cut

log = logging.getLogger("clipping")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)-18s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )


def _slug(t: float) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(t))


# ---- monitor: live capture + detection loop --------------------------------

def cmd_monitor(args: argparse.Namespace) -> int:
    out_dir = Path(args.out) / f"{args.platform}_{args.channel}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = ingest.CaptureConfig(
        channel=args.channel,
        output_dir=out_dir,
        platform=args.platform,
        quality=args.quality,
        segment_seconds=args.segment_seconds,
    )

    log.info("waiting for %s/#%s to go live", args.platform, args.channel)
    capture = ingest.wait_until_live(cfg)

    chat_mon: chat.ChatMonitor | chat_kick.KickChatMonitor | None
    if args.platform == "twitch":
        chat_mon = chat.ChatMonitor(args.channel)
        chat_mon.start()
    elif args.platform == "kick":
        if not args.chatroom_id:
            log.warning("--chatroom-id not supplied for kick; scoring will be audio-only")
            chat_mon = None
        else:
            chat_mon = chat_kick.KickChatMonitor(args.channel, args.chatroom_id)
            chat_mon.start()
    else:
        raise ValueError(f"unknown platform {args.platform!r}")

    stop = {"flag": False}

    def _on_signal(*_):
        log.info("stop signal received, draining")
        stop["flag"] = True
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    cut_already: set[float] = set()    # highlight timestamps already cut
    detect_interval = args.detect_interval

    try:
        while not stop["flag"] and capture.is_running:
            time.sleep(detect_interval)
            try:
                _run_detection_pass(args, capture, chat_mon, out_dir, cut_already)
            except Exception:
                log.exception("detection pass failed; continuing")
    finally:
        if chat_mon is not None:
            chat_mon.stop()
        capture.stop()
        log.info("capture stopped")
    return 0


# Duck-typed monitor: both chat.ChatMonitor and chat_kick.KickChatMonitor expose
# .started_at(), .velocity_curve(start, end, bin_seconds), .stop().
ChatLike = "chat.ChatMonitor | chat_kick.KickChatMonitor | None"


def _run_detection_pass(
    args: argparse.Namespace,
    capture: ingest.Capture,
    chat_mon,
    out_dir: Path,
    cut_already: set[float],
) -> None:
    segments = list(capture.iter_segments())
    if len(segments) < 2:
        return

    capture_start = capture.started_at()
    elapsed = time.time() - capture_start

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = Path(f.name)
    try:
        score.extract_audio_to_wav(segments, wav_path)
        audio_curve = score.loudness_curve(wav_path)
    finally:
        wav_path.unlink(missing_ok=True)

    end = elapsed - args.detect_lag
    if chat_mon is not None:
        chat_offset = chat_mon.started_at() - capture_start
        chat_curve = chat_mon.velocity_curve(start=0.0, end=end, bin_seconds=args.bin_seconds)
        chat_curve = [(t + chat_offset, v) for t, v in chat_curve]
    else:
        chat_curve = None

    highlights = score.detect_highlights(
        audio_curve, chat_curve,
        bin_seconds=args.bin_seconds,
        alpha=args.alpha,
        beta=args.beta,
        min_score=args.min_score,
        min_gap_seconds=args.min_gap,
    )

    for h in highlights:
        # Skip ones we've already cut and ones too close to the live edge
        if h.timestamp + args.post > end - args.detect_lag:
            continue
        if any(abs(h.timestamp - t) < args.min_gap / 2 for t in cut_already):
            continue
        cut_already.add(h.timestamp)
        wall_ts = capture_start + h.timestamp
        out_path = out_dir / f"{_slug(wall_ts)}_z{h.score:+.2f}.mp4"
        try:
            cut.cut_around(
                capture.segments_dir, h.timestamp, out_path,
                pre=args.pre, post=args.post,
            )
            cut.write_sidecar(out_path, {
                "channel": args.channel,
                "captured_at": wall_ts,
                "highlight": {
                    "timestamp_in_capture_s": h.timestamp,
                    "score": h.score,
                    "audio_z": h.audio_z,
                    "chat_z": h.chat_z,
                    "chat_count": h.chat_count,
                },
            })
            log.info("clip %s  score=%.2f  audio_z=%.2f  chat_z=%.2f",
                     out_path.name, h.score, h.audio_z, h.chat_z)
        except Exception:
            log.exception("cut failed for highlight @ %.1f", h.timestamp)


# ---- process: offline mode -------------------------------------------------

def cmd_process(args: argparse.Namespace) -> int:
    video_path = Path(args.video_path)
    if not video_path.exists():
        log.error("no such file: %s", video_path)
        return 2

    out_dir = Path(args.out) / video_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # Treat the video as a single-segment "capture". cut_clip walks the
    # segments folder, so put a symlink there. Extension preserves the source.
    segments_dir = out_dir / "segments"
    segments_dir.mkdir(exist_ok=True)
    src_ext = video_path.suffix.lower() if video_path.suffix.lower() in {".ts", ".mp4"} else ".mp4"
    sym = segments_dir / f"seg_000000{src_ext}"
    if sym.exists() or sym.is_symlink():
        sym.unlink()
    sym.symlink_to(video_path.resolve())

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = Path(f.name)
    try:
        score.extract_audio_to_wav([sym], wav_path)
        audio_curve = score.loudness_curve(wav_path)
    finally:
        wav_path.unlink(missing_ok=True)

    highlights = score.detect_highlights(
        audio_curve, None,
        bin_seconds=args.bin_seconds,
        alpha=1.0,
        beta=0.0,
        min_score=args.min_score,
        min_gap_seconds=args.min_gap,
    )
    log.info("found %d highlights", len(highlights))

    for h in highlights:
        out_path = out_dir / f"clip_{int(h.timestamp):05d}_z{h.score:+.2f}.mp4"
        try:
            cut.cut_around(segments_dir, h.timestamp, out_path,
                           pre=args.pre, post=args.post)
            cut.write_sidecar(out_path, {
                "source": str(video_path),
                "highlight": {
                    "timestamp_in_source_s": h.timestamp,
                    "score": h.score,
                    "audio_z": h.audio_z,
                },
            })
            log.info("clip %s", out_path.name)
        except Exception:
            log.exception("cut failed at %.1f", h.timestamp)
    return 0


# ---- arg parsing -----------------------------------------------------------

def _add_detection_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--bin-seconds", type=float, default=2.0, help="scoring bin size")
    p.add_argument("--alpha", type=float, default=0.6, help="audio weight in combined score")
    p.add_argument("--beta", type=float, default=0.4, help="chat weight in combined score")
    p.add_argument("--min-score", type=float, default=1.2, help="z-score threshold for a highlight")
    p.add_argument("--min-gap", type=float, default=30.0, help="seconds between highlights (NMS)")
    p.add_argument("--pre", type=float, default=8.0, help="seconds of context before the peak")
    p.add_argument("--post", type=float, default=20.0, help="seconds after the peak")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipping", description="Live-stream highlight clipper.")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--out", default="out", help="output directory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    mon = sub.add_parser("monitor", help="live: monitor a channel and clip highlights as they happen")
    mon.add_argument("channel", help="channel handle (e.g. 'kaicenat' for twitch, 'adinross' for kick)")
    mon.add_argument("--platform", choices=["twitch", "kick"], default="twitch")
    mon.add_argument("--chatroom-id", type=int, default=None,
                     help="kick only: numeric chatroom_id from kick.com API. without it, scoring is audio-only.")
    mon.add_argument("--quality", default="480p,worst", help="streamlink quality selector")
    mon.add_argument("--segment-seconds", type=int, default=30)
    mon.add_argument("--detect-interval", type=int, default=30, help="run detection every N seconds")
    mon.add_argument("--detect-lag", type=float, default=15.0, help="don't score the most recent N seconds (still being written)")
    _add_detection_args(mon)
    mon.set_defaults(func=cmd_monitor)

    proc = sub.add_parser("process", help="offline: detect + cut on an existing video file")
    proc.add_argument("video_path")
    _add_detection_args(proc)
    proc.set_defaults(func=cmd_process)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
