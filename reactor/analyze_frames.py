from transformers import DetrImageProcessor, DetrForObjectDetection
import torch
import cv2

# Load a pre-trained model for object detection
processor = DetrImageProcessor.from_pretrained("facebook/detr-resnet-50")
model = DetrForObjectDetection.from_pretrained("facebook/detr-resnet-50")

def analyze_frames(frames):
    reactions = []
    for frame in frames:
        # Convert frame to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        inputs = processor(images=rgb_frame, return_tensors="pt")
        outputs = model(**inputs)
        # Process the outputs
        logits = outputs.logits
        bboxes = outputs.pred_boxes
        reactions.append((logits, bboxes))
    return reactions

if __name__ == "__main__":
    from extract_frames import extract_frames
    video_path = "input_video.mp4"
    frames = extract_frames(video_path)
    analysis_results = analyze_frames(frames)
    print(f"Analyzed {len(analysis_results)} frames")