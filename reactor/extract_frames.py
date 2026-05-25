import cv2

def extract_frames(video_path):
    cap = cv2.VideoCapture(video_path)
    frames = []
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    return frames

if __name__ == "__main__":
    video_path = "input_video.mp4"
    frames = extract_frames(video_path)
    print(f"Extracted {len(frames)} frames from {video_path}")