# clipping

Live-stream highlight clipper. Watches a target Twitch channel, captures the stream as it airs, detects highlight moments, and outputs short-form vertical clips ready for social platforms.

Status: scaffolding. Pipeline below is planned, not built.

## Pipeline (planned)

1. **Live monitor.** Poll Twitch Helix `GET /streams?user_login=…` per channel. On state transition `offline -> live`, start the capture job.
2. **Ingest.** Use `streamlink` to pull the HLS stream into a rolling on-disk buffer (segmented MP4, 30-60 second segments, ~1-2 hour rolling retention).
3. **Highlight detection.** Score each window of the buffer. Phase 1 uses simple signals:
   - Audio loudness deltas (sudden volume spikes).
   - Optional Twitch chat velocity if we expose the IRC firehose (`KICK` / chat-message-per-second).
4. **Cut.** ffmpeg cuts a configurable window around each detected highlight (default: -8s, +20s).
5. **Reformat for short-form.** Center-crop or pad to 9:16. Optional auto-captions (Whisper). Optional intro/outro brand frames.
6. **Publish.** Manual review queue by default. Optional auto-publish to TikTok / YouTube Shorts / Instagram Reels via each platform's official API. Disabled by default; requires explicit per-account opt-in.

## Layout

```
clipping/
├── pyproject.toml
├── src/clipping/
│   ├── monitor.py      live-state poller
│   ├── ingest.py       streamlink capture loop
│   ├── detect.py       highlight scoring
│   ├── cut.py          ffmpeg clip extraction + 9:16 reformat
│   ├── publish.py      per-platform upload adapters
│   └── cli.py          entry point
└── tests/
```

## Config

A single `config.yaml` lists target channels, detection thresholds, output directory, and (per channel, optional) social-platform credentials. Credentials are read from `.env` at runtime; never committed.

## What this is not

- Not a tool to evade platform rate limits or fingerprinting. Each output platform's official API is used directly. If an account gets a strike, that's information; the tool does not try to hide.
- Not a tool that operates without per-channel opt-in for publishing. Capture is local; publish is gated.
