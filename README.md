# reactor

Two media-automation experiments in one repo. Each subdirectory is its own project with its own dependencies and entry points.

## Layout

- [`clipping/`](clipping/) — live-stream highlight clipper. Pulls a Twitch livestream as it airs, detects highlights, cuts vertical short-form clips, and (optionally) publishes them to social platforms. Active.
- [`reactor/`](reactor/) — auto-generate a reaction voiceover for an arbitrary video clip. Frames -> object detection -> caption -> TTS -> mux. Original project. Stable, on hold.

## Why both here

Both projects live in the same problem space (turn long-form video into short-form, automated) and share enough utilities (ffmpeg orchestration, vertical reformatting, caption rendering) that a single repo is cheaper to maintain than two. They don't share Python environments yet; each subproject has its own `pyproject.toml` or `requirements.txt`.
