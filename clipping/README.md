# clipping

Live-stream highlight clipper. Watches a Twitch or Kick channel, captures the stream as it airs, scores windows for highlight-worthiness (audio loudness + chat velocity), and outputs 9:16 vertical clips ready for short-form social.

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

For Kick capture only, streamlink's `kick` plugin needs a real web browser available to solve a Cloudflare JavaScript challenge on first connect; macOS Chrome / Firefox / Safari are all fine. Headless servers need Chromium installed (e.g. `brew install --cask chromium`).

## Usage

### Twitch

```bash
clipping monitor kaicenat
```

That's it. Chat is read anonymously over IRC (no token). Audio is pulled at 480p via streamlink. Clips land in `out/twitch_<channel>/`.

### Kick

```bash
# First, find the channel's chatroom_id by hand:
# 1. open kick.com/<channel> in your browser
# 2. open DevTools → Network → filter on /api/v2/channels
# 3. find the chatroom.id field in the response
clipping monitor adinross --platform kick --chatroom-id 668
```

Why manual chatroom_id? Kick's REST API for the slug-to-chatroom_id lookup sits behind Cloudflare bot protection. Working around that requires TLS-fingerprint spoofing, which I won't write. Looking it up once in your browser is the honest workaround.

You can also skip `--chatroom-id` entirely; the audio-only signal still produces highlights, just with less precision on chat-driven moments.

### Offline (no streaming)

```bash
clipping process recording.mp4
```

Runs detect + cut on an existing file. Used to validate the pipeline without waiting for a live stream.

## Pipeline

1. **Live monitor.** Streamlink is the live-detector: if the channel is offline it exits with a recognizable message; we retry every minute (configurable).
2. **Ingest.** Streamlink pipes HLS into ffmpeg's `-f segment` muxer, writing 30-second MP4 segments into `<out>/<platform>_<channel>/segments/`. A background thread deletes segments older than `retention_seconds`.
3. **Chat.**
   - Twitch: anonymous IRC (`justinfanNNNN` nick) on `irc.chat.twitch.tv:6667`. PRIVMSG timestamps go into a bisect-indexed deque.
   - Kick: Pusher WebSocket on `ws-us2.pusher.com`. Anonymous subscribe to `chatrooms.<chatroom_id>.v2`. Same timestamp interface as Twitch.
4. **Highlight detection.** Every `--detect-interval` seconds, audio is extracted from buffered segments and binned into RMS-in-dBFS. Chat is binned over the same grid. Both signals are z-scored against their own recent baselines and combined with `alpha * audio_z + beta * chat_z`. Non-max suppression keeps highlights at least `min_gap_seconds` apart.
5. **Cut.** ffmpeg concat-demuxes the segments overlapping the chosen window, cuts with `-ss/-t`, and reformats 9:16 via center-crop (`crop=ih*9/16:ih,scale=1080:1920`).
6. **Review queue.** MP4 plus a JSON sidecar with score breakdown lands in `out/<platform>_<channel>/<timestamp>_z<score>.mp4`. You review and decide what to post.

## Layout

```
clipping/
├── pyproject.toml
├── src/clipping/
│   ├── ingest.py       streamlink subprocess + segment GC
│   ├── chat.py         Twitch IRC (anonymous read)
│   ├── chat_kick.py    Kick Pusher WebSocket (anonymous read)
│   ├── score.py        audio loudness + chat velocity scoring with NMS
│   ├── cut.py          ffmpeg cut + 9:16 reformat
│   └── cli.py          monitor + process subcommands
└── tests/              16 tests, no network
```

## What this is not

- Not a tool to evade platform rate limits, TLS fingerprints, or any other detection. Streamlink's official plugins handle whatever each platform expects; chat is read over public anonymous endpoints. If Cloudflare blocks the REST API, that's the honest answer — look the value up in your browser.
- Not a publisher. Phase 1 stops at MP4-on-disk by design. Auto-upload to YouTube Shorts / TikTok / Instagram Reels is Phase 2+ and will be opt-in per channel, behind each platform's official API.
