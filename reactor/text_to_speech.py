from gtts import gTTS

def text_to_speech(text, output_path):
    tts = gTTS(text)
    tts.save(output_path)

if __name__ == "__main__":
    reaction_text = "This is a test reaction."
    audio_path = "output_audio.mp3"
    text_to_speech(reaction_text, audio_path)
    print(f"Saved synthesized speech to {audio_path}")