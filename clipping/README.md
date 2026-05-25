# clipping

Live-stream highlight clipper for Twitch. Watches a channel, captures the stream as it airs, scores windows for highlight-worthiness (audio loudness + chat velocity), and outputs 9:16 vertical clips ready for short-form social.

Status: Phase 1 (live monitor + capture + detect + cut + review queue). No auto-publish yet.

## Install

```bash
cd clipping
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

System dependencies (not Python packages):

```bash
brew install streamlink ffmpeg
```

## Usage

### Live

```bash
clipping monitor kaicenat
```

That's it. Chat is read anonymously over IRC (no token). Audio is pulled at 480p via streamlink. Clips land in `out/<channel>/`.

### Offline (no streaming)

```bash
clipping process recording.mp4
```

Runs detect + cut on an existing file. Used to validate the pipeline without waiting for a live stream.

## Pipeline

1. **Live monitor.** Streamlink is the live-detector: if the channel is offline it exits with a recognizable message; we retry every minute (configurable).
2. **Ingest.** Streamlink pipes HLS into ffmpeg's `-f segment` muxer, writing 30-second MPEG-TS segments into `<out>/<channel>/segments/`. A background thread deletes segments older than `retention_seconds`.
3. **Chat.** Anonymous IRC (`justinfanNNNN` nick) on `irc.chat.twitch.tv:6667`. PRIVMSG timestamps go into a bisect-indexed deque.
4. **Highlight detection.** Every `--detect-interval` seconds, audio is extracted from buffered segments and binned into RMS-in-dBFS. Chat is binned over the same grid. Both signals are z-scored against their own recent baselines and combined with `alpha * audio_z + beta * chat_z`. Non-max suppression keeps highlights at least `min_gap_seconds` apart.
5. **Cut.** ffmpeg concat-demuxes the segments overlapping the chosen window, cuts with `-ss/-t`, and reformats 9:16 via center-crop (`crop=ih*9/16:ih,scale=1080:1920`).
6. **Review queue.** MP4 plus a JSON sidecar with score breakdown lands in `out/<channel>/<timestamp>_z<score>.mp4`. You review and decide what to post.

## Layout

```
clipping/
├── pyproject.toml
├── src/clipping/
│   ├── ingest.py       streamlink subprocess + segment GC
│   ├── chat.py         Twitch IRC (anonymous read)
│   ├── score.py        audio loudness + chat velocity scoring with NMS
│   ├── cut.py          ffmpeg cut + 9:16 reformat
│   └── cli.py          monitor + process subcommands
└── tests/              10 tests, no network
```

## What this is not

Not a publisher. Phase 1 stops at MP4-on-disk by design. Auto-upload to YouTube Shorts / TikTok / Instagram Reels is Phase 2+ and will be opt-in per channel, behind each platform's official API.
