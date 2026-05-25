import moviepy.editor as mp

def combine_audio_video(video_path, audio_path, output_path):
    video = mp.VideoFileClip(video_path)
    audio = mp.AudioFileClip(audio_path)
    final_video = video.set_audio(audio)
    final_video.write_videofile(output_path, codec="libx264", audio_codec="aac")

if __name__ == "__main__":
    video_path = "input_video.mp4"
    audio_path = "output_audio.mp3"
    output_path = "output_video.mp4"
    combine_audio_video(video_path, audio_path, output_path)
    print(f"Saved final video to {output_path}")