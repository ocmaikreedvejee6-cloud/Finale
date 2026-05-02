import cv2
import numpy as np
import time
import os
import smtplib
import requests
import threading
import pickle
from datetime import datetime
from email.message import EmailMessage
from flask import Flask, Response
from pyngrok import ngrok

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ================= CONFIG =================
SCOPES = ['https://www.googleapis.com/auth/drive.file']

TELEGRAM_TOKEN = "8490765768:AAFU-Vpi0HAiS5_2V2mcboWYeiG8W4neiVE"
CHAT_ID = "7175315173"

EMAIL_ADDRESS = "growpfiveim312@gmail.com"
EMAIL_APP_PASSWORD = "qerlwnbhfcaprcll"
RECEIVER_EMAIL = "ocmaikreedvejee6@gmail.com"

NGROK_AUTH_TOKEN = "3CuyBmODW6s830X8lYEvc1Hnh7O_GxAh2wGfQpMeayQ5jKfG"

GDRIVE_FOLDER_ID = "1UsVEk8AbZZjS8bonWxDp5M2_PQykhEx5"

VIDEO_TIMEOUT = 7
ALERT_INTERVAL = 3  # ✅ SEND EVERY 3 SECONDS

# ================= GLOBALS =================
frame_global = None
lock = threading.Lock()

cap = None

recording = False
video_writer = None
current_video_path = None

last_intruder_time = 0
last_alert_time = 0

STREAM_URL = None

# ================= DETECTORS =================
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

fgbg = cv2.createBackgroundSubtractorMOG2()

# ================= NGROK =================
ngrok.set_auth_token(NGROK_AUTH_TOKEN)

# ================= CAMERA =================
def connect_camera():
    global cap
    while True:
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.set(3, 640)
            cap.set(4, 360)
            print("Camera connected")
            return
        time.sleep(2)

# ================= RECORDING =================
def start_recording(frame):
    global recording, video_writer, current_video_path

    os.makedirs("videos", exist_ok=True)
    os.makedirs("local_videos", exist_ok=True)
    os.makedirs("snapshots", exist_ok=True)

    filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    current_video_path = f"videos/intruder_{filename}.avi"

    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    video_writer = cv2.VideoWriter(current_video_path, fourcc, 20, (640, 360))

    recording = True
    print("🎥 Recording started:", current_video_path)

def stop_recording():
    global recording, video_writer, current_video_path

    if video_writer:
        video_writer.release()
        video_writer = None

    recording = False
    print("🛑 Recording stopped")

    if current_video_path and os.path.exists(current_video_path):

        local_copy = current_video_path.replace("videos/", "local_videos/")
        os.replace(current_video_path, local_copy)

        threading.Thread(
            target=upload_to_gdrive,
            args=(local_copy,),
            daemon=True
        ).start()

        current_video_path = None

# ================= GOOGLE DRIVE =================
def authenticate_gdrive():
    creds = None

    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            'client_secrets.json', SCOPES
        )
        creds = flow.run_local_server(port=0)

        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('drive', 'v3', credentials=creds)

drive_service = authenticate_gdrive()

def upload_to_gdrive(file_path):
    try:
        file_metadata = {
            'name': os.path.basename(file_path),
            'parents': [GDRIVE_FOLDER_ID]
        }

        media = MediaFileUpload(file_path, resumable=True)

        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        print("☁️ Uploaded to Drive:", file.get('id'))

    except Exception as e:
        print("GDrive error:", e)

# ================= ALERTS =================
def save_snapshot(frame):
    filename = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = f"snapshots/alert_{filename}.jpg"
    cv2.imwrite(path, frame)
    return path

def send_telegram(image_path, message):
    try:
        with open(image_path, "rb") as photo:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": photo},
                data={
                    "chat_id": CHAT_ID,
                    "caption": f"{message}\n🌍 Live: {STREAM_URL}"
                }
            )
    except Exception as e:
        print("Telegram error:", e)

def send_email(image_path):
    try:
        msg = EmailMessage()
        msg["Subject"] = "🚨 CCTV Intruder Alert"
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = RECEIVER_EMAIL

        msg.set_content(f"""
Intruder detected

🌍 Live Stream:
{STREAM_URL}
""")

        with open(image_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="image", subtype="jpeg")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)

    except Exception as e:
        print("Email error:", e)

# ================= FLASK =================
app = Flask(__name__)

def generate_frames():
    global frame_global

    while True:
        with lock:
            if frame_global is None:
                continue
            frame = frame_global.copy()

        _, buffer = cv2.imencode(".jpg", frame)

        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')

@app.route('/')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ================= MAIN =================
def main():
    global frame_global, recording, video_writer, last_intruder_time, last_alert_time, STREAM_URL

    connect_camera()

    tunnel = ngrok.connect(5000, "http")
    STREAM_URL = tunnel.public_url

    print("🌍 LIVE LINK:", STREAM_URL)

    while True:
        ret, frame = cap.read()
        if not ret:
            connect_camera()
            continue

        frame = cv2.resize(frame, (640, 360))

        # ================= CCTV TIMESTAMP =================
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

        # ================= MOTION =================
        fgmask = fgbg.apply(frame)
        _, fgmask = cv2.threshold(fgmask, 250, 255, cv2.THRESH_BINARY)
        fgmask = cv2.erode(fgmask, None, iterations=2)
        fgmask = cv2.dilate(fgmask, None, iterations=2)

        motion_pixels = cv2.countNonZero(fgmask)

        faces = []
        person_detected = False

        if motion_pixels > 500:

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)

            boxes, weights = hog.detectMultiScale(
                frame,
                winStride=(8, 8),
                padding=(16, 16),
                scale=1.1,
                hitThreshold=0.1
            )

            for i, (x, y, w, h) in enumerate(boxes):
                if weights[i] > 0.3:
                    person_detected = True
                    cv2.rectangle(frame, (x,y), (x+w,y+h), (255,0,0), 2)

        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x,y), (x+w,y+h), (0,0,255), 2)

        # ================= DETECTION =================
        detected_now = (motion_pixels > 500) and (len(faces) > 0 or person_detected)

        now = time.time()

        # ================= RECORDING =================
        if detected_now:
            last_intruder_time = now

            if not recording:
                start_recording(frame)

        if recording:
            video_writer.write(frame)

        if recording and (now - last_intruder_time > VIDEO_TIMEOUT):
            stop_recording()

        # ================= ALERT SYSTEM (3 SECONDS ONLY) =================
        if detected_now and (now - last_alert_time >= ALERT_INTERVAL):

            last_alert_time = now

            snap = save_snapshot(frame)

            threading.Thread(
                target=send_telegram,
                args=(snap, "🚨 INTRUDER DETECTED"),
                daemon=True
            ).start()

            threading.Thread(
                target=send_email,
                args=(snap,),
                daemon=True
            ).start()

        with lock:
            frame_global = frame.copy()

        time.sleep(0.03)

# ================= START =================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main()
