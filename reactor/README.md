# reactor

Auto-generate a reaction voiceover for any video clip.

## The problem

Reaction videos are a high-volume content format, but recording one requires
sitting down, watching the source, and improvising commentary in real time.
This project skips the human and produces a passable reaction track from a
video file alone, end to end, on local models.

## The pipeline

Five stages, all local, no API keys required.

1. **Extract frames** with OpenCV (`cv2.VideoCapture`). Every frame is decoded
   into memory as a NumPy array.
2. **Analyze frames** with Facebook's DETR ResNet-50 (`facebook/detr-resnet-50`
   via `transformers`). Each frame goes through object detection and returns
   class logits and bounding boxes.
3. **Generate reactions** with GPT-2 (`transformers`). The detection output is
   serialized into a prompt and GPT-2 produces a short caption per frame.
4. **Text to speech** with gTTS. All captions are concatenated and synthesized
   into a single MP3.
5. **Combine audio and video** with MoviePy. The original video is muxed with
   the new audio track and written as H.264 / AAC MP4.

## What it does

- Decodes every frame of an input video into memory.
- Runs DETR object detection per frame and keeps logits plus bounding boxes.
- Feeds detection tensors into GPT-2 as a text prompt to produce per-frame
  commentary.
- Concatenates commentary and synthesizes it as a single gTTS audio file.
- Muxes the synthesized audio over the original video into `output_video.mp4`.

## Run locally

```bash
pip install -r requirements.txt

# Place your source clip at ./input_video.mp4, then:
python main.py
```

The entry point currently uses hardcoded paths defined at the top of
`main.py`:

```python
video_path = "input_video.mp4"
audio_path = "output_audio.mp3"
output_path = "output_video.mp4"
```

Edit those constants to point at a different input or output. Each module
also runs standalone for debugging, e.g. `python extract_frames.py`.

First run downloads the DETR and GPT-2 weights from Hugging Face (~250 MB
combined) and caches them locally.

## What I learned

- Frame-by-frame inference scales linearly in the worst way. A 30-second
  1080p clip at 30 fps is 900 DETR forward passes. Sampling every Nth frame
  is the obvious next step.
- Loading every frame into a Python list before processing blows up memory
  on anything longer than a short clip. Streaming through a generator is the
  right shape.
- GPT-2 prompted with raw tensor reprs produces incoherent text. The honest
  fix is to map logits to top-k class labels before prompting.
- gTTS is a network call to Google Translate's TTS endpoint, so the "local
  only" claim has one asterisk on it.
- MoviePy's `set_audio` truncates to the shorter of the two streams, which
  matters when synthesized speech is longer than the source video.
