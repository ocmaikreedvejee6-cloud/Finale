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


VIDEO_TIMEOUT = 5
TELEGRAM_COOLDOWN = 5

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

# ================= STABLE TRACKING =================
last_boxes = []
last_box_time = 0
box_timeout = 1.0

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
    os.makedirs("snapshots", exist_ok=True)

    filename = datetime.now().strftime("%Y%m%d_%H%M%S")

    current_video_path = f"videos/intruder_{filename}.avi"

    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    video_writer = cv2.VideoWriter(current_video_path, fourcc, 20, (640, 360))

    recording = True

    snap = f"snapshots/intruder_{filename}.jpg"
    cv2.imwrite(snap, frame)

    print("Recording started")

def stop_recording():
    global recording, video_writer, current_video_path

    if video_writer:
        video_writer.release()
        video_writer = None

    recording = False
    print("Recording stopped")

    current_video_path = None

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
    global frame_global, recording, last_intruder_time, last_boxes, last_box_time, STREAM_URL

    connect_camera()

    tunnel = ngrok.connect(5000, "http")
    STREAM_URL = tunnel.public_url
    print("Live:", STREAM_URL)

    while True:
        ret, frame = cap.read()
        if not ret:
            connect_camera()
            continue

        frame = cv2.resize(frame, (640, 360))

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, timestamp, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

        fgmask = fgbg.apply(frame)
        _, fgmask = cv2.threshold(fgmask, 250, 255, cv2.THRESH_BINARY)
        fgmask = cv2.erode(fgmask, None, iterations=2)
        fgmask = cv2.dilate(fgmask, None, iterations=2)

        motion_pixels = cv2.countNonZero(fgmask)

        faces = []
        current_boxes = []
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

                if w < 60 or h < 120:
                    continue

                aspect_ratio = h / float(w)
                if aspect_ratio < 1.5:
                    continue

                if weights[i] > 0.3:
                    current_boxes.append((x, y, w, h))
                    person_detected = True

        now = time.time()

        if len(current_boxes) > 0:
            last_boxes = current_boxes
            last_box_time = now

        elif now - last_box_time < box_timeout:
            current_boxes = last_boxes

        for (x, y, w, h) in current_boxes:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)

        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x,y), (x+w,y+h), (0,0,255), 2)

        intruder = (motion_pixels > 500) and (len(faces) > 0 or person_detected)

        with lock:
            frame_global = frame.copy()

        if intruder and (now - last_intruder_time > 3):
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
