from transformers import GPT2LMHeadModel, GPT2Tokenizer

# Load a pre-trained model for text generation
model_name = "gpt2"
model = GPT2LMHeadModel.from_pretrained(model_name)
tokenizer = GPT2Tokenizer.from_pretrained(model_name)

def generate_reactions(analysis_results):
    reactions = []
    for logits, bboxes in analysis_results:
        input_text = f"Detected objects with confidence scores: {logits}"
        inputs = tokenizer.encode(input_text, return_tensors="pt")
        outputs = model.generate(inputs, max_length=50)
        reaction = tokenizer.decode(outputs[0], skip_special_tokens=True)
        reactions.append(reaction)
    return reactions

if __name__ == "__main__":
    from analyze_frames import analyze_frames
    from extract_frames import extract_frames
    video_path = "input_video.mp4"
    frames = extract_frames(video_path)
    analysis_results = analyze_frames(frames)
    reactions = generate_reactions(analysis_results)
    print(f"Generated reactions: {reactions}")