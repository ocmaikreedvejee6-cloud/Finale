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

# ================= GOOGLE DRIVE =================
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

NGROK_AUTH_TOKEN = "3CNooZSFRM64UqMFHQhvjL167bU_4RZuEZf7oztKsnwVyVcHJ"

CONFIDENCE_THRESHOLD = 70
VIDEO_TIMEOUT = 5
TELEGRAM_COOLDOWN = 30

# ================= GLOBALS =================
frame_global = None
lock = threading.Lock()

cap = None
recording = False
video_writer = None
current_video_path = None

last_intruder_time = 0
last_telegram_time = 0

STREAM_URL = None

# ================= NGROK =================
ngrok.set_auth_token(NGROK_AUTH_TOKEN)

# ================= GOOGLE DRIVE AUTH =================
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

# ================= UPLOAD =================
def upload_to_gdrive(file_path):
    try:
        file_metadata = {'name': os.path.basename(file_path)}
        media = MediaFileUpload(file_path, resumable=True)

        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        print("☁️ Uploaded to Drive:", file.get('id'))

    except Exception as e:
        print("GDrive error:", e)

# ================= CAMERA =================
def connect_camera():
    global cap
    while True:
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.set(3, 640)
            cap.set(4, 360)
            print("✅ Camera connected")
            return
        time.sleep(2)

# ================= ALERTS =================
def send_telegram(image_path, message):
    global last_telegram_time, STREAM_URL

    if time.time() - last_telegram_time < TELEGRAM_COOLDOWN:
        return

    try:
        with open(image_path, "rb") as photo:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": photo},
                data={
                    "chat_id": CHAT_ID,
                    "caption": f"{message}\nLive: {STREAM_URL}"
                }
            )
        last_telegram_time = time.time()

    except Exception as e:
        print("Telegram error:", e)

def send_email(image_path):
    try:
        msg = EmailMessage()
        msg["Subject"] = "🚨 Intruder Alert"
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = RECEIVER_EMAIL
        msg.set_content(f"Intruder detected\nLive: {STREAM_URL}")

        with open(image_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="image", subtype="jpeg")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)

    except Exception as e:
        print("Email error:", e)

# ================= RECORDING =================
def start_recording(frame):
    global recording, video_writer, current_video_path

    os.makedirs("videos", exist_ok=True)
    os.makedirs("local_videos", exist_ok=True)
    os.makedirs("snapshots", exist_ok=True)

    filename = datetime.now().strftime("%Y%m%d_%H%M%S")

    current_video_path = f"videos/intruder_{filename}.avi"

    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    video_writer = cv2.VideoWriter(current_video_path, fourcc, 20, (640, 360))

    recording = True

    snap = f"snapshots/intruder_{filename}.jpg"
    cv2.imwrite(snap, frame)

    threading.Thread(target=send_telegram, args=(snap, "🚨 INTRUDER")).start()
    threading.Thread(target=send_email, args=(snap,)).start()

    print("🎥 Recording started")

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
    global frame_global, recording, last_intruder_time, STREAM_URL

    connect_camera()

    # ================= NGROK START =================
    tunnel = ngrok.connect(5000, "http")
    STREAM_URL = tunnel.public_url
    print("🌍 Live Stream URL:", STREAM_URL)

    while True:
        ret, frame = cap.read()
        if not ret:
            connect_camera()
            continue

        frame = cv2.resize(frame, (640, 360))

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

        with lock:
            frame_global = frame.copy()

        # ================= YOUR DETECTION LOGIC =================
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = []  # replace with your model output

        intruder = len(faces) > 0

        now = time.time()

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
