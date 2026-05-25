from extract_frames import extract_frames
from analyze_frames import analyze_frames
from generate_reactions import generate_reactions
from text_to_speech import text_to_speech
from combine_audio_video import combine_audio_video

video_path = "input_video.mp4"
audio_path = "output_audio.mp3"
output_path = "output_video.mp4"

# Step 1: Extract frames
frames = extract_frames(video_path)

# Step 2: Analyze frames
analysis_results = analyze_frames(frames)

# Step 3: Generate reactions
reactions = generate_reactions(analysis_results)

# Step 4: Synthesize speech
reaction_text = " ".join(reactions)
text_to_speech(reaction_text, audio_path)

# Step 5: Combine audio and video
combine_audio_video(video_path, audio_path, output_path)