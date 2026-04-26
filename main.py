import cv2
import numpy as np
import time
import os
import smtplib
import requests
import threading
from datetime import datetime
from email.message import EmailMessage
from flask import Flask, Response
from pyngrok import ngrok

# ================= CONFIG =================
TELEGRAM_TOKEN = "8490765768:AAFU-Vpi0HAiS5_2V2mcboWYeiG8W4neiVE"
CHAT_ID = "7175315173"

EMAIL_ADDRESS = "growpfiveim312@gmail.com"
EMAIL_APP_PASSWORD = "qerlwnbhfcaprcll"
RECEIVER_EMAIL = "ocmaikreedvejee6@gmail.com"

NGROK_AUTH_TOKEN = "3CNooZSFRM64UqMFHQhvjL167bU_4RZuEZf7oztKsnwVyVcHJ"

CONFIDENCE_THRESHOLD = 70
PERSON_DETECT_INTERVAL = 3
VIDEO_TIMEOUT = 5
TELEGRAM_COOLDOWN = 30

# ================= GLOBALS =================
frame_global = None
lock = threading.Lock()

cap = None
recording = False
video_writer = None

last_intruder_time = 0
last_telegram_time = 0

frame_count = 0
STREAM_URL = None

# ================= NGROK =================
ngrok.set_auth_token(NGROK_AUTH_TOKEN)

# ================= MODELS =================
recognizer = cv2.face.LBPHFaceRecognizer_create()
recognizer.read("trainer1.yml")
label_map = np.load("labels1.npy", allow_pickle=True).item()

face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

# ================= CAMERA =================
def connect_camera():
    global cap
    while True:
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
            print("✅ Camera connected")
            return
        time.sleep(2)

# ================= ALERTS =================
def send_telegram(image_path, message):
    global last_telegram_time, STREAM_URL

    now = time.time()
    if now - last_telegram_time < TELEGRAM_COOLDOWN:
        return

    try:
        with open(image_path, "rb") as photo:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": photo},
                data={
                    "chat_id": CHAT_ID,
                    "caption": f"{message}\n\nLive Stream:\n{STREAM_URL}"
                }
            )

        last_telegram_time = now
        print("✅ Telegram sent")

    except Exception as e:
        print("Telegram error:", e)

def send_email(image_path):
    try:
        msg = EmailMessage()
        msg["Subject"] = "🚨 Intruder Alert"
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = RECEIVER_EMAIL
        msg.set_content(f"Intruder detected.\nLive: {STREAM_URL}")

        with open(image_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="image", subtype="jpeg")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)

        print("📧 Email sent")

    except Exception as e:
        print("Email error:", e)

# ================= RECORDING =================
def start_recording(frame):
    global recording, video_writer

    os.makedirs("videos", exist_ok=True)

    timestamp_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"videos/intruder_{timestamp_file}.avi"

    fourcc = cv2.VideoWriter_fourcc(*"XVID")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or fps is None:
        fps = 20

    h, w, _ = frame.shape
    video_writer = cv2.VideoWriter(path, fourcc, fps, (w, h))

    recording = True

    snap = path.replace(".avi", ".jpg")
    cv2.imwrite(snap, frame)

    threading.Thread(target=send_telegram, args=(snap, "🚨 INTRUDER DETECTED")).start()
    threading.Thread(target=send_email, args=(snap,)).start()

    print("🎥 Recording started")

def stop_recording():
    global recording, video_writer

    if video_writer:
        video_writer.release()

    recording = False
    print("🛑 Recording stopped")

# ================= FLASK STREAM =================
app = Flask(__name__)

def generate_frames():
    global frame_global

    while True:
        with lock:
            if frame_global is None:
                continue
            frame = frame_global.copy()

        _, buffer = cv2.imencode(".jpg", frame)

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" +
               buffer.tobytes() + b"\r\n")

@app.route("/")
def video_feed():
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# ================= MAIN LOOP =================
def main():
    global frame_global, frame_count, recording, last_intruder_time, cap, STREAM_URL

    print("🚀 System Running...")

    connect_camera()

    # ngrok public URL
    tunnel = ngrok.connect(5000, "http")
    STREAM_URL = tunnel.public_url
    print("🌍 Live Stream:", STREAM_URL)

    while True:
        ret, frame = cap.read()

        if not ret:
            cap.release()
            time.sleep(2)
            connect_camera()
            continue

        frame = cv2.resize(frame, (640, 360))

        # ================= CCTV TIMESTAMP =================
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0), 2)

        with lock:
            frame_global = frame.copy()

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # FACE DETECTION
        faces = face_cascade.detectMultiScale(gray, 1.2, 6)
        face_detected = len(faces) > 0

        # PERSON DETECTION
        person_detected = False
        boxes = []

        frame_count += 1
        if frame_count % PERSON_DETECT_INTERVAL == 0:
            boxes, _ = hog.detectMultiScale(frame, winStride=(8, 8))
            person_detected = len(boxes) > 0

        intruder = False

        # FACE RECOGNITION
        for (x, y, w, h) in faces:
            face = gray[y:y+h, x:x+w]

            try:
                label, conf = recognizer.predict(face)
                name = label_map.get(label, "Unknown") if conf < CONFIDENCE_THRESHOLD else "Unknown"
            except:
                name = "Unknown"

            if name == "Unknown":
                intruder = True

        if person_detected and not face_detected:
            intruder = True

        now = time.time()

        # ================= RECORDING =================
        if intruder:
            last_intruder_time = now
            if not recording:
                start_recording(frame)

        if recording:
            video_writer.write(frame)

        if recording and (now - last_intruder_time > VIDEO_TIMEOUT):
            stop_recording()

        time.sleep(0.03)

# ================= START =================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main()
