import cv2
import numpy as np
import time
import os
import smtplib
import requests
import threading
import pickle
import queue
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

EMAIL_ADDRESS = "ocmaikreedvejee1@gmail.com"
EMAIL_APP_PASSWORD = "zpakcoctznasrirq"
RECEIVER_EMAIL = "ocmaikreedvejee6@gmail.com"

NGROK_AUTH_TOKEN = "3CuyBmODW6s830X8lYEvc1Hnh7O_GxAh2wGfQpMeayQ5jKfG"

GDRIVE_FOLDER_ID = "1UsVEk8AbZZjS8bonWxDp5M2_PQykhEx5"

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1503263695474790452/xWJgceQHECBZPy9SO2pzjqd9E1EJeDD3e8y5W-8xS2uU_DUGsbHUtIVwCkAsHY3CXJnb"

VIDEO_TIMEOUT = 10
TELEGRAM_COOLDOWN = 5
EMAIL_COOLDOWN = 15

# 🔥 ADDED DISCORD COOLDOWN
DISCORD_COOLDOWN = 5

# ================= GLOBALS =================
frame_global = None
lock = threading.Lock()

cap = None
recording = False
video_writer = None
current_video_path = None

last_intruder_time = 0
last_telegram_time = 0
last_email_time = 0

# 🔥 ADDED DISCORD TIMER
last_discord_time = 0

STREAM_URL = None

# ================= STABLE TRACKING =================
last_boxes = []
last_box_time = 0
box_timeout = 1.0

# ================= QUEUES =================
task_queue = queue.Queue()
upload_queue = queue.Queue()
discord_queue = queue.Queue()

# ================= DETECTORS =================
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

fgbg = cv2.createBackgroundSubtractorMOG2()

# ================= NGROK =================
ngrok.set_auth_token(NGROK_AUTH_TOKEN)

# ================= GOOGLE DRIVE AUTH =================
def authenticate_google_drive():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('drive', 'v3', credentials=creds)

# ================= WORKERS =================
def worker_discord():
    while True:
        try:
            image_path, message = discord_queue.get(timeout=1)

            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    files = {"file": f}
                    data = {"content": message}

                    requests.post(DISCORD_WEBHOOK_URL, data=data, files=files, timeout=10)

                os.remove(image_path)

        except queue.Empty:
            continue

# ================= CAMERA =================
def connect_camera():
    global cap
    while True:
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.set(3, 640)
            cap.set(4, 360)
            return
        time.sleep(2)

# ================= RECORDING =================
def start_recording(frame):
    global recording, video_writer, current_video_path

    os.makedirs("videos", exist_ok=True)
    os.makedirs("snapshots", exist_ok=True)

    filename = datetime.now().strftime("%Y%m%d_%H%M%S")

    current_video_path = f"videos/intruder_{filename}.avi"

    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    video_writer = cv2.VideoWriter(current_video_path, fourcc, 20, (640, 360))

    recording = True

    snap = f"snapshots/intruder_{filename}.jpg"
    cv2.imwrite(snap, frame)

    return snap

def stop_recording():
    global recording, video_writer, current_video_path

    if video_writer:
        video_writer.release()

    recording = False

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
    global frame_global
    global last_intruder_time, last_telegram_time, last_email_time, last_discord_time

    threading.Thread(target=worker_discord, daemon=True).start()

    connect_camera()

    ngrok.connect(5000, "http")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        frame = cv2.resize(frame, (640, 360))
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        fgmask = fgbg.apply(frame)
        motion = cv2.countNonZero(fgmask)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        boxes, weights = hog.detectMultiScale(frame)
        person_detected = len(boxes) > 0

        intruder = motion > 500 and (len(faces) > 0 or person_detected)

        with lock:
            frame_global = frame.copy()

        now = time.time()

        if intruder and (now - last_intruder_time > 3):
            last_intruder_time = now

            if not recording:
                snap = start_recording(frame)

                # ================= DISCORD WITH COOLDOWN =================
                if now - last_discord_time >= DISCORD_COOLDOWN:
                    discord_queue.put((snap, f"🚨 INTRUDER DETECTED {timestamp}"))
                    last_discord_time = now

        # ================= CONTINUOUS ALERTS =================
        if recording and intruder:
            temp_snap = f"snapshots/temp_{datetime.now().strftime('%H%M%S')}.jpg"
            cv2.imwrite(temp_snap, frame)

            # DISCORD COOLDOWN APPLIED HERE TOO
            if now - last_discord_time >= DISCORD_COOLDOWN:
                discord_queue.put((temp_snap, f"⚠️ Intruder still present {timestamp}"))
                last_discord_time = now

        if recording and (now - last_intruder_time > VIDEO_TIMEOUT):
            stop_recording()

        time.sleep(0.03)

# ================= START =================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main()
