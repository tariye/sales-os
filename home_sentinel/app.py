from flask import Flask, send_from_directory, send_file, redirect, request, jsonify, Response
from pathlib import Path
from datetime import datetime
from threading import Thread, Lock
from collections import deque
import json
import resource
import subprocess
import sqlite3
import time
import shutil
import os
import socket
import tempfile
import urllib.request

try:
    import cv2
    OPENCV_AVAILABLE = True
except Exception:
    OPENCV_AVAILABLE = False


app = Flask(__name__)

BASE_DIR = Path(os.environ.get("HOMESENTINEL_BASE_DIR", "/home/tariye/camera_project"))
RAW_DIR = BASE_DIR / "images" / "raw"
ANNOTATED_DIR = BASE_DIR / "images" / "annotated"
MODEL_DIR = BASE_DIR / "models"
DB_PATH = BASE_DIR / "db" / "home_sentinel.db"
BASELINE_PATH = BASE_DIR / "images" / "baseline.jpg"

PROTOTXT = MODEL_DIR / "MobileNetSSD_deploy.prototxt"
MODEL = MODEL_DIR / "MobileNetSSD_deploy.caffemodel"
CAMERA_PROFILES = {
    "arducam": {
        "label": "Arducam Day & Night",
        "device": os.environ.get("HOMESENTINEL_ARDUCAM_DEVICE", "/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._USB_Camera_SN0001-video-index0"),
    },
    "logitech": {
        "label": "Logitech C922",
        "device": os.environ.get("HOMESENTINEL_LOGITECH_DEVICE", "/dev/v4l/by-id/usb-046d_C922_Pro_Stream_Webcam_506AEDCF-video-index0"),
    },
}
DEFAULT_CAMERA_KEY = os.environ.get("HOMESENTINEL_DEFAULT_CAMERA", "arducam")
CAMERA_DEVICE = CAMERA_PROFILES.get(DEFAULT_CAMERA_KEY, CAMERA_PROFILES["arducam"])["device"]
CAMERA_PRESETS = {
    "arducam_day": {
        "camera_key": "arducam",
        "label": "Arducam Day",
        "controls": {
            "auto_exposure": 3,
            "brightness": -16,
            "contrast": 28,
            "saturation": 56,
            "gain": 0,
            "backlight_compensation": 0,
        },
    },
    "arducam_low_light": {
        "camera_key": "arducam",
        "label": "Arducam Low Light",
        "controls": {
            "auto_exposure": 1,
            "exposure_time_absolute": 60,
            "brightness": -16,
            "contrast": 28,
            "saturation": 56,
            "gain": 0,
            "backlight_compensation": 0,
        },
    },
    "arducam_dark": {
        "camera_key": "arducam",
        "label": "Arducam Dark",
        "controls": {
            "auto_exposure": 1,
            "exposure_time_absolute": 35,
            "brightness": -28,
            "contrast": 22,
            "saturation": 48,
            "gain": 0,
            "backlight_compensation": 0,
        },
    },
    "logitech_default": {
        "camera_key": "logitech",
        "label": "Logitech Default",
        "controls": {
            "brightness": 0,
            "contrast": 32,
            "saturation": 64,
            "gain": 0,
            "backlight_compensation": 0,
        },
    },
}

RAW_DIR.mkdir(parents=True, exist_ok=True)
ANNOTATED_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
CAMERA_CONFIG_DIR = BASE_DIR / "config"
CAMERA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CAMERA_AUTOTUNE_PATH = CAMERA_CONFIG_DIR / "camera_autotune.json"

start_time = time.time()

camera_lock = Lock()
monitor_thread = None
REQUEST_LOG = deque(maxlen=80)
ENDPOINT_COUNTS = {}
CAPTURE_HISTORY = deque(maxlen=30)
LAST_CAPTURE_SECONDS = None

MONITOR_INTERVAL_SECONDS = 5
STREAM_FPS = 5.0
APP_VERSION = "v0.5.0-event-clips"
APP_VERSION = "v0.5.1-arducam-autotune"

AUTO_CAPTURE_ENABLED = True
AUTO_CAPTURE_DIFF_PERCENT = 3.0
AUTO_CAPTURE_MIN_MOTION_PIXELS = 250
AUTO_CAPTURE_PERSISTENCE_FRAMES = 2
AUTO_CAPTURE_COOLDOWN_SECONDS = 20
AUTO_CAPTURE_BRIGHTNESS_DELTA = 18.0

EVENT_VIDEO_ENABLED = True
EVENT_VIDEO_SECONDS = 6
EVENT_VIDEO_FPS = 3.0
EVENT_VIDEO_KEEP = 10

MOTION_SETTINGS = {
    "diff_percent": AUTO_CAPTURE_DIFF_PERCENT,
    "min_motion_pixels": AUTO_CAPTURE_MIN_MOTION_PIXELS,
    "persistence_frames": AUTO_CAPTURE_PERSISTENCE_FRAMES,
    "cooldown_seconds": AUTO_CAPTURE_COOLDOWN_SECONDS,
    "brightness_delta": AUTO_CAPTURE_BRIGHTNESS_DELTA,
}

CAMERA_AUTOTUNE_DEFAULTS = {
    "enabled": True,
    "target_brightness": 112.0,
    "tolerance": 14.0,
    "cooldown_seconds": 4,
    "exposure_min": 4,
    "exposure_max": 2500,
    "exposure_step_up": 1.25,
    "exposure_step_down": 0.72,
    "gain_min": 0,
    "gain_max": 24,
    "gain_step": 1,
    "initial_exposure": 80,
    "initial_gain": 0,
}

CAMERA_AUTOTUNE_STATE = {
    "last_adjust_at": "Never",
    "last_brightness": None,
    "last_action": "idle",
    "last_exposure": None,
    "last_gain": None,
    "last_message": "Auto exposure assist not yet applied",
}

CLIPS_DIR = BASE_DIR / "videos" / "clips"
CLIPS_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

@app.before_request
def record_request_start():
    request._started_at = time.perf_counter()


@app.after_request
def record_request(response):
    try:
        if not request.path.startswith('/static/'):
            endpoint = request.endpoint or request.path
            ENDPOINT_COUNTS[endpoint] = ENDPOINT_COUNTS.get(endpoint, 0) + 1
            duration_ms = None
            started_at = getattr(request, '_started_at', None)
            if started_at is not None:
                duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
            REQUEST_LOG.appendleft({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'method': request.method,
                'path': request.path,
                'endpoint': endpoint,
                'client_ip': request.remote_addr or 'unknown',
                'status': response.status_code,
                'duration_ms': duration_ms,
            })
    except Exception:
        pass
    return response

DIFF_TRIGGER_PERCENT = 3.0
EVENT_COOLDOWN_SECONDS = 20

RESPONSIVE_STYLE = """
        <style>
            html, body {
                background: #05070b;
                color: #e7edf7;
            }
            body {
                font-family: Arial, sans-serif;
                padding: 16px;
                line-height: 1.45;
                max-width: 1100px;
                margin: 0 auto;
            }
            h1, h2, h3 {
                line-height: 1.2;
            }
            .top-links {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin-bottom: 12px;
            }
            .top-links a {
                color: #90b7ff;
                text-decoration: none;
                background: #111926;
                border: 1px solid #243048;
                padding: 7px 10px;
                border-radius: 6px;
            }
            .top-links a:hover {
                background: #182235;
                color: #d6e5ff;
            }

            .capture-controls form {
                margin-bottom: 10px;
            }
            .capture-controls button {
                width: 100%;
                max-width: 360px;
                padding: 14px;
                font-size: 18px;
            }
            .table-wrap {
                width: 100%;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }
            .metric-grid {
                display: grid;
                grid-template-columns: 1fr;
                gap: 12px;
            }
            .metric-card {
                border: 1px solid #243048;
                border-radius: 8px;
                padding: 14px;
                background: #101723;
                box-shadow: 0 0 0 1px rgba(255,255,255,0.02) inset;
            }
            .metric-card h3 {
                margin-top: 0;
                margin-bottom: 10px;
            }
            .metric-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            .metric-list li {
                padding: 4px 0;
                border-bottom: 1px solid #223047;
            }
            .metric-list li:last-child {
                border-bottom: 0;
            }
            .metric-label {
                font-weight: bold;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                color: #e7edf7;
                background: #0c111b;
                border: 1px solid #223047;
            }
            th, td {
                border-bottom: 1px solid #223047;
                background: #0c111b;
                padding: 8px;
            }
            th {
                color: #9bb8ff;
            }
            img {
                width: 100%;
                height: auto;
                display: block;
                border-radius: 8px;
            }
            td, th {
                white-space: nowrap;
            }
            hr {
                border: 0;
                border-top: 1px solid #223047;
            }
            a {
                color: #90b7ff;
            }
            code, pre {
                background: #0c111b;
                color: #e7edf7;
                border-color: #223047;
            }
            input, select, textarea {
                background: #0d1420;
                color: #e7edf7;
                border: 1px solid #243048;
            }
            button {
                background: #182235;
                color: #e7edf7;
                border: 1px solid #2d3c58;
            }
            button:hover {
                background: #223047;
            }
            img, video {
                background: #070b12;
            }
            .capture-controls, .metric-card, .annotation-card {
                color: #e7edf7;
            }
            @media (min-width: 900px) {
                .metric-grid {
                    grid-template-columns: 1fr 1fr;
                }
            }
            @media (min-width: 760px) {
                body {
                    padding: 20px;
                }
            }
        </style>
"""

monitor_state = {
    "enabled": False,
    "last_check": "Never",
    "last_diff_percent": 0.0,
    "last_motion_pixels": 0,
    "last_motion_bbox": None,
    "motion_streak": 0,
    "motion_trigger": "idle",
    "last_event": "None",
    "last_error": "",
    "last_event_time": 0
}

CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair", "cow",
    "diningtable", "dog", "horse", "motorbike", "person",
    "pottedplant", "sheep", "sofa", "train", "tvmonitor"
]

TARGET_CLASSES = {
    "person", "car", "bicycle", "dog", "cat", "bus", "motorbike"
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            raw_image TEXT,
            annotated_image TEXT,
            client_ip TEXT,
            notes TEXT,
            source TEXT,
            diff_percent REAL,
            light_level REAL,
            day_night TEXT,
            annotation_json TEXT,
            annotation_model TEXT
        )
    """)



    cur.execute("PRAGMA table_info(events)")
    event_columns = {row[1] for row in cur.fetchall()}

    if "source" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN source TEXT")

    if "diff_percent" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN diff_percent REAL")

    if "light_level" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN light_level REAL")

    if "day_night" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN day_night TEXT")

    if "annotation_json" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN annotation_json TEXT")

    if "annotation_model" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN annotation_model TEXT")

    if "clip_video" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN clip_video TEXT")

    if "clip_seconds" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN clip_seconds REAL")

    if "clip_fps" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN clip_fps REAL")

    if "clip_status" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN clip_status TEXT")

    if "clip_size_bytes" not in event_columns:
        cur.execute("ALTER TABLE events ADD COLUMN clip_size_bytes INTEGER")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            label TEXT,
            confidence REAL,
            x1 INTEGER,
            y1 INTEGER,
            x2 INTEGER,
            y2 INTEGER,
            review_status TEXT DEFAULT 'unreviewed',
            review_note TEXT,
            reviewed_at TEXT,
            FOREIGN KEY(event_id) REFERENCES events(id)
        )
    """)

    cur.execute("PRAGMA table_info(detections)")
    detection_columns = {row[1] for row in cur.fetchall()}

    if "review_status" not in detection_columns:
        cur.execute("ALTER TABLE detections ADD COLUMN review_status TEXT DEFAULT 'unreviewed'")

    if "review_note" not in detection_columns:
        cur.execute("ALTER TABLE detections ADD COLUMN review_note TEXT")

    if "reviewed_at" not in detection_columns:
        cur.execute("ALTER TABLE detections ADD COLUMN reviewed_at TEXT")

    conn.commit()
    conn.close()


def insert_event(event_type, raw_image=None, annotated_image=None, client_ip=None, notes=None, source=None, diff_percent=None, light_level=None, day_night=None, clip_video=None, clip_seconds=None, clip_fps=None, clip_status=None, clip_size_bytes=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO events (timestamp, event_type, raw_image, annotated_image, client_ip, notes, source, diff_percent, light_level, day_night, clip_video, clip_seconds, clip_fps, clip_status, clip_size_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (timestamp, event_type, raw_image, annotated_image, client_ip, notes, source, diff_percent, light_level, day_night, clip_video, clip_seconds, clip_fps, clip_status, clip_size_bytes))

    event_id = cur.lastrowid
    conn.commit()
    conn.close()

    return event_id


def update_event(event_id, annotated_image=None, notes=None, light_level=None, day_night=None, annotation_json=None, annotation_model=None, clip_video=None, clip_seconds=None, clip_fps=None, clip_status=None, clip_size_bytes=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if annotated_image is not None:
        cur.execute("""
            UPDATE events
            SET annotated_image = ?
            WHERE id = ?
        """, (annotated_image, event_id))

    if notes is not None:
        cur.execute("""
            UPDATE events
            SET notes = ?
            WHERE id = ?
        """, (notes, event_id))

    if light_level is not None:
        cur.execute("""
            UPDATE events
            SET light_level = ?
            WHERE id = ?
        """, (light_level, event_id))

    if day_night is not None:
        cur.execute("""
            UPDATE events
            SET day_night = ?
            WHERE id = ?
        """, (day_night, event_id))

    if annotation_json is not None:
        cur.execute("""
            UPDATE events
            SET annotation_json = ?
            WHERE id = ?
        """, (annotation_json, event_id))

    if annotation_model is not None:
        cur.execute("""
            UPDATE events
            SET annotation_model = ?
            WHERE id = ?
        """, (annotation_model, event_id))

    if clip_video is not None:
        cur.execute("""
            UPDATE events
            SET clip_video = ?
            WHERE id = ?
        """, (clip_video, event_id))

    if clip_seconds is not None:
        cur.execute("""
            UPDATE events
            SET clip_seconds = ?
            WHERE id = ?
        """, (clip_seconds, event_id))

    if clip_fps is not None:
        cur.execute("""
            UPDATE events
            SET clip_fps = ?
            WHERE id = ?
        """, (clip_fps, event_id))

    if clip_status is not None:
        cur.execute("""
            UPDATE events
            SET clip_status = ?
            WHERE id = ?
        """, (clip_status, event_id))

    if clip_size_bytes is not None:
        cur.execute("""
            UPDATE events
            SET clip_size_bytes = ?
            WHERE id = ?
        """, (clip_size_bytes, event_id))

    conn.commit()
    conn.close()


def insert_detection(event_id, label, confidence, x1, y1, x2, y2):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO detections (event_id, label, confidence, x1, y1, x2, y2, review_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (event_id, label, float(confidence), int(x1), int(y1), int(x2), int(y2), 'unreviewed'))

    conn.commit()
    conn.close()


def get_recent_events(limit=20):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, timestamp, event_type, raw_image, annotated_image, client_ip, notes
        FROM events
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()
    return rows


def get_recent_annotated_events(limit=10):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, timestamp, event_type, raw_image, annotated_image, clip_video,
               client_ip, notes, source, diff_percent, light_level, day_night,
               annotation_json, annotation_model, clip_status, clip_seconds, clip_fps, clip_size_bytes
        FROM events
        WHERE annotated_image IS NOT NULL
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [event_to_dict(row) for row in rows]


def prune_old_annotated_images(keep=10):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, annotated_image
        FROM events
        WHERE annotated_image IS NOT NULL
        ORDER BY id DESC
        LIMIT -1 OFFSET ?
    """, (keep,))
    rows = cur.fetchall()
    for event_id, annotated_image in rows:
        if annotated_image:
            try:
                (ANNOTATED_DIR / annotated_image).unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
        cur.execute("UPDATE events SET annotated_image = NULL WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def coerce_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, bytes):
        return int.from_bytes(value, byteorder='little', signed=True)
    try:
        return int(value)
    except Exception:
        return None


def get_detections_for_event(event_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, label, confidence, x1, y1, x2, y2, review_status, review_note, reviewed_at
        FROM detections
        WHERE event_id = ?
        ORDER BY confidence DESC
    """, (event_id,))

    rows = cur.fetchall()
    conn.close()
    return [
        {
            'id': row[0],
            'label': row[1],
            'confidence': row[2],
            'bbox': {
                'x1': coerce_int(row[3]),
                'y1': coerce_int(row[4]),
                'x2': coerce_int(row[5]),
                'y2': coerce_int(row[6]),
            },
            'review_status': row[7] or 'unreviewed',
            'review_note': row[8] or '',
            'reviewed_at': row[9] or None,
        }
        for row in rows
    ]


def latest_event_with_image():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, raw_image, annotated_image
        FROM events
        WHERE raw_image IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()
    return row


def resolve_camera_device(camera_key=None):
    key = str(camera_key or DEFAULT_CAMERA_KEY).strip().lower()
    if key not in CAMERA_PROFILES:
        key = DEFAULT_CAMERA_KEY
    return CAMERA_PROFILES[key]["device"]


def normalize_camera_key(camera_key=None):
    key = str(camera_key or DEFAULT_CAMERA_KEY).strip().lower()
    return key if key in CAMERA_PROFILES else DEFAULT_CAMERA_KEY


def capture_to_path(path, attempts=3, retry_delay=1.0, camera_key=None):
    global LAST_CAPTURE_SECONDS
    camera_key = normalize_camera_key(camera_key)
    if camera_key == "arducam" and not CAMERA_AUTOTUNE_SETTINGS.get("enabled", False):
        try:
            apply_camera_preset(camera_key, "arducam_dark")
        except Exception:
            pass
    device = resolve_camera_device(camera_key)

    command = [
        "fswebcam",
        "--device", device,
        "-r", "640x480",
        "--no-banner",
        str(path)
    ]

    last_message = "Unknown camera capture error"

    for attempt in range(1, attempts + 1):
        start_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.perf_counter()
        with camera_lock:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=20
                )
            except Exception as e:
                last_message = str(e)
                result = None

        elapsed = round(time.perf_counter() - started, 3)
        cpu_percent = None
        try:
            end_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu_seconds = (
                (end_usage.ru_utime - start_usage.ru_utime) +
                (end_usage.ru_stime - start_usage.ru_stime)
            )
            if elapsed > 0:
                cpu_percent = round((cpu_seconds / elapsed) * 100.0, 1)
        except Exception:
            pass

        if result is not None and result.returncode == 0 and path.exists():
            LAST_CAPTURE_SECONDS = elapsed
            try:
                maybe_autotune_arducam(camera_key, path)
            except Exception:
                pass
            CAPTURE_HISTORY.appendleft({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'path': str(path),
                'camera_key': camera_key,
                'seconds': elapsed,
                'cpu_percent': cpu_percent,
                'success': True,
            })
            return True, result.stdout

        if result is not None:
            last_message = result.stderr or result.stdout or last_message

        CAPTURE_HISTORY.appendleft({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'path': str(path),
            'camera_key': camera_key,
            'seconds': elapsed,
            'cpu_percent': cpu_percent,
            'success': False,
            'message': last_message,
        })

        if attempt < attempts:
            time.sleep(retry_delay)

    return False, last_message


def update_camera_autotune_settings(payload):
    enabled_raw = str(payload.get("enabled", "off")).strip().lower()
    CAMERA_AUTOTUNE_SETTINGS["enabled"] = enabled_raw in {"1", "true", "yes", "on", "enabled"}

    def parse_float(key, default):
        try:
            return float(payload.get(key, default))
        except Exception:
            return default

    def parse_int(key, default):
        try:
            return int(float(payload.get(key, default)))
        except Exception:
            return default

    CAMERA_AUTOTUNE_SETTINGS["target_brightness"] = clamp(parse_float("target_brightness", CAMERA_AUTOTUNE_SETTINGS["target_brightness"]), 0, 255)
    CAMERA_AUTOTUNE_SETTINGS["tolerance"] = clamp(parse_float("tolerance", CAMERA_AUTOTUNE_SETTINGS["tolerance"]), 1, 100)
    CAMERA_AUTOTUNE_SETTINGS["cooldown_seconds"] = max(0, parse_int("cooldown_seconds", CAMERA_AUTOTUNE_SETTINGS["cooldown_seconds"]))
    CAMERA_AUTOTUNE_SETTINGS["exposure_min"] = max(1, parse_int("exposure_min", CAMERA_AUTOTUNE_SETTINGS["exposure_min"]))
    CAMERA_AUTOTUNE_SETTINGS["exposure_max"] = max(CAMERA_AUTOTUNE_SETTINGS["exposure_min"], parse_int("exposure_max", CAMERA_AUTOTUNE_SETTINGS["exposure_max"]))
    CAMERA_AUTOTUNE_SETTINGS["gain_min"] = max(0, parse_int("gain_min", CAMERA_AUTOTUNE_SETTINGS["gain_min"]))
    CAMERA_AUTOTUNE_SETTINGS["gain_max"] = max(CAMERA_AUTOTUNE_SETTINGS["gain_min"], parse_int("gain_max", CAMERA_AUTOTUNE_SETTINGS["gain_max"]))
    CAMERA_AUTOTUNE_SETTINGS["gain_step"] = max(1, parse_int("gain_step", CAMERA_AUTOTUNE_SETTINGS["gain_step"]))
    CAMERA_AUTOTUNE_SETTINGS["exposure_step_up"] = clamp(parse_float("exposure_step_up", CAMERA_AUTOTUNE_SETTINGS["exposure_step_up"]), 1.0, 2.5)
    CAMERA_AUTOTUNE_SETTINGS["exposure_step_down"] = clamp(parse_float("exposure_step_down", CAMERA_AUTOTUNE_SETTINGS["exposure_step_down"]), 0.3, 0.99)
    CAMERA_AUTOTUNE_SETTINGS["initial_exposure"] = max(1, parse_int("initial_exposure", CAMERA_AUTOTUNE_SETTINGS["initial_exposure"]))
    CAMERA_AUTOTUNE_SETTINGS["initial_gain"] = max(0, parse_int("initial_gain", CAMERA_AUTOTUNE_SETTINGS["initial_gain"]))
    save_camera_autotune_settings(CAMERA_AUTOTUNE_SETTINGS)
    return CAMERA_AUTOTUNE_SETTINGS


def apply_camera_controls(camera_key, controls):
    camera_key = normalize_camera_key(camera_key)
    device = resolve_camera_device(camera_key)
    command = ['v4l2-ctl', '-d', device]
    for control, value in controls.items():
        if value is None or value == '':
            continue
        command.extend(['--set-ctrl', f'{control}={value}'])
    if len(command) == 2:
        return False, 'no camera controls supplied'
    ok, output = run_command(command, timeout=10)
    return ok, output or 'camera controls applied'


def get_camera_control_snapshot(camera_key):
    camera_key = normalize_camera_key(camera_key)
    device = resolve_camera_device(camera_key)
    controls = ['brightness', 'contrast', 'saturation', 'gain', 'backlight_compensation', 'auto_exposure', 'exposure_time_absolute']
    ok, output = run_command(['v4l2-ctl', '-d', device, '--get-ctrl=' + ','.join(controls)], timeout=10)
    values = {}
    if ok and output:
        for line in output.splitlines():
            if ': ' not in line:
                continue
            name, value = line.split(': ', 1)
            values[name.strip()] = value.strip().split(' ')[0]
    return values


def apply_camera_preset(camera_key, preset_name):
    camera_key = normalize_camera_key(camera_key)
    preset = CAMERA_PRESETS.get(preset_name)
    if not preset:
        return False, 'unknown preset'

    target_key = preset.get('camera_key') or camera_key
    return apply_camera_controls(target_key, preset.get('controls') or {})


def load_camera_autotune_settings():
    settings = dict(CAMERA_AUTOTUNE_DEFAULTS)
    try:
        if CAMERA_AUTOTUNE_PATH.exists():
            with open(CAMERA_AUTOTUNE_PATH, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for key, default_value in CAMERA_AUTOTUNE_DEFAULTS.items():
                    if key in raw and raw[key] is not None:
                        settings[key] = raw[key]
    except Exception:
        pass
    return settings


def save_camera_autotune_settings(settings):
    try:
        with open(CAMERA_AUTOTUNE_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, sort_keys=True)
        return True
    except Exception:
        return False


CAMERA_AUTOTUNE_SETTINGS = load_camera_autotune_settings()


def clamp(value, minimum, maximum):
    try:
        value = float(value)
    except Exception:
        value = float(minimum)
    return max(float(minimum), min(float(maximum), value))


def estimate_image_brightness(image_path):
    if not OPENCV_AVAILABLE:
        return None
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return round(float(gray.mean()), 2)


def maybe_autotune_arducam(camera_key, image_path):
    camera_key = normalize_camera_key(camera_key)
    if camera_key != "arducam" or not CAMERA_AUTOTUNE_SETTINGS.get("enabled", False):
        return None
    try:
        cooldown_seconds = max(0, int(float(CAMERA_AUTOTUNE_SETTINGS.get("cooldown_seconds", 4))))
    except Exception:
        cooldown_seconds = 4
    now = time.time()
    last_adjust_at = CAMERA_AUTOTUNE_STATE.get("last_adjust_ts", 0.0) or 0.0
    if cooldown_seconds and (now - last_adjust_at) < cooldown_seconds:
        return CAMERA_AUTOTUNE_STATE

    brightness = estimate_image_brightness(image_path)
    if brightness is None:
        CAMERA_AUTOTUNE_STATE["last_message"] = "Brightness measurement unavailable"
        return CAMERA_AUTOTUNE_STATE

    current = get_camera_control_snapshot(camera_key)
    if not current:
        CAMERA_AUTOTUNE_STATE["last_message"] = "Camera control snapshot unavailable"
        return CAMERA_AUTOTUNE_STATE

    try:
        current_exposure = int(float(current.get("exposure_time_absolute") or CAMERA_AUTOTUNE_SETTINGS.get("initial_exposure", 80)))
    except Exception:
        current_exposure = int(CAMERA_AUTOTUNE_SETTINGS.get("initial_exposure", 80))
    try:
        current_gain = int(float(current.get("gain") or CAMERA_AUTOTUNE_SETTINGS.get("initial_gain", 0)))
    except Exception:
        current_gain = int(CAMERA_AUTOTUNE_SETTINGS.get("initial_gain", 0))

    target = float(CAMERA_AUTOTUNE_SETTINGS.get("target_brightness", 112.0))
    tolerance = float(CAMERA_AUTOTUNE_SETTINGS.get("tolerance", 14.0))
    exp_min = int(CAMERA_AUTOTUNE_SETTINGS.get("exposure_min", 4))
    exp_max = int(CAMERA_AUTOTUNE_SETTINGS.get("exposure_max", 2500))
    gain_min = int(CAMERA_AUTOTUNE_SETTINGS.get("gain_min", 0))
    gain_max = int(CAMERA_AUTOTUNE_SETTINGS.get("gain_max", 24))
    exposure_step_up = float(CAMERA_AUTOTUNE_SETTINGS.get("exposure_step_up", 1.25))
    exposure_step_down = float(CAMERA_AUTOTUNE_SETTINGS.get("exposure_step_down", 0.72))
    gain_step = int(CAMERA_AUTOTUNE_SETTINGS.get("gain_step", 1))

    message = "within target"
    new_exposure = current_exposure
    new_gain = current_gain

    if brightness > target + tolerance:
        if current_exposure > exp_min:
            new_exposure = max(exp_min, int(current_exposure * exposure_step_down))
            message = f"too bright -> exposure {current_exposure} -> {new_exposure}"
        elif current_gain > gain_min:
            new_gain = max(gain_min, current_gain - gain_step)
            message = f"too bright -> gain {current_gain} -> {new_gain}"
    elif brightness < target - tolerance:
        if current_exposure < exp_max:
            new_exposure = min(exp_max, max(exp_min, int(current_exposure * exposure_step_up)))
            message = f"too dark -> exposure {current_exposure} -> {new_exposure}"
        elif current_gain < gain_max:
            new_gain = min(gain_max, current_gain + gain_step)
            message = f"too dark -> gain {current_gain} -> {new_gain}"

    changed = (new_exposure != current_exposure) or (new_gain != current_gain)
    if not changed:
        CAMERA_AUTOTUNE_STATE.update({
            "last_adjust_ts": now,
            "last_adjust_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_brightness": brightness,
            "last_action": "hold",
            "last_exposure": current_exposure,
            "last_gain": current_gain,
            "last_message": f"brightness {brightness} within target {target}±{tolerance}",
        })
        return CAMERA_AUTOTUNE_STATE

    controls = {
        "auto_exposure": 1,
        "exposure_time_absolute": new_exposure,
        "gain": new_gain,
        "backlight_compensation": 0,
    }
    ok, output = apply_camera_controls(camera_key, controls)
    if not ok:
        CAMERA_AUTOTUNE_STATE.update({
            "last_adjust_ts": now,
            "last_adjust_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_brightness": brightness,
            "last_action": "error",
            "last_exposure": current_exposure,
            "last_gain": current_gain,
            "last_message": output or "camera auto-tune failed",
        })
        return CAMERA_AUTOTUNE_STATE

    CAMERA_AUTOTUNE_STATE.update({
        "last_adjust_ts": now,
        "last_adjust_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_brightness": brightness,
        "last_action": message,
        "last_exposure": new_exposure,
        "last_gain": new_gain,
        "last_message": output or message,
    })
    return CAMERA_AUTOTUNE_STATE


def capture_image(client_ip=None, prefix="snapshot", event_type="snapshot", notes="Manual snapshot captured", camera_key=None):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{prefix}_{timestamp}.jpg"
    raw_path = RAW_DIR / filename

    ok, message = capture_to_path(raw_path, camera_key=camera_key)

    if ok:
        event_id = insert_event(
            event_type=event_type,
            raw_image=filename,
            client_ip=client_ip,
            notes=notes,
            source=client_ip or "manual"
        )
        return event_id, filename, None

    insert_event(
        event_type="capture_error",
        client_ip=client_ip,
        notes=message,
        source=client_ip or "manual"
    )

    return None, None, message





def build_event_video_path(event_id, raw_filename):
    stem = Path(raw_filename).stem if raw_filename else f"event_{event_id}"
    return CLIPS_DIR / f"clip_{event_id}_{stem}.mp4"


def prune_old_event_clips(keep=10):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, clip_video
        FROM events
        WHERE clip_video IS NOT NULL AND clip_video != ''
        ORDER BY id DESC
        LIMIT -1 OFFSET ?
    """, (keep,))
    rows = cur.fetchall()
    for event_id, clip_video in rows:
        if clip_video:
            try:
                (CLIPS_DIR / clip_video).unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
        cur.execute("""
            UPDATE events
            SET clip_video = NULL, clip_seconds = NULL, clip_fps = NULL, clip_status = 'pruned', clip_size_bytes = NULL
            WHERE id = ?
        """, (event_id,))
    conn.commit()
    conn.close()


def record_event_video(event_id, raw_filename, clip_seconds=EVENT_VIDEO_SECONDS, clip_fps=EVENT_VIDEO_FPS, camera_key=None):
    if not EVENT_VIDEO_ENABLED:
        update_event(event_id, clip_status="disabled")
        return False, "video clips disabled"

    clip_path = build_event_video_path(event_id, raw_filename)
    update_event(
        event_id,
        clip_video=clip_path.name,
        clip_seconds=clip_seconds,
        clip_fps=clip_fps,
        clip_status="recording",
    )

    command = [
        FFMPEG_BIN,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-f", "v4l2",
        "-framerate", str(clip_fps),
        "-video_size", "640x480",
        "-i", resolve_camera_device(camera_key),
        "-t", str(clip_seconds),
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(clip_path),
    ]

    try:
        started = time.perf_counter()
        with camera_lock:
            result = subprocess.run(command, capture_output=True, text=True, timeout=int(clip_seconds) + 25)
        elapsed = round(time.perf_counter() - started, 3)
    except Exception as e:
        update_event(event_id, clip_status="failed", notes=f"Video clip error: {e}")
        return False, str(e)

    if result.returncode == 0 and clip_path.exists():
        try:
            size_bytes = clip_path.stat().st_size
        except Exception:
            size_bytes = None
        update_event(
            event_id,
            clip_status="ready",
            clip_size_bytes=size_bytes,
            notes=f"Video clip stored in {elapsed}s",
        )
        prune_old_event_clips(keep=EVENT_VIDEO_KEEP)
        return True, str(clip_path)

    error_message = (result.stderr or result.stdout or "ffmpeg failed").strip()
    update_event(event_id, clip_status="failed", notes=f"Video clip error: {error_message}")
    return False, error_message


def queue_event_video_capture(event_id, raw_filename, camera_key=None):
    if not EVENT_VIDEO_ENABLED:
        update_event(event_id, clip_status="disabled")
        return
    Thread(target=record_event_video, args=(event_id, raw_filename), kwargs={"camera_key": camera_key}, daemon=True).start()


def classify_light_level(image):
    if image is None:
        return None, 'unknown'
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    if brightness < 55:
        return round(brightness, 2), 'night'
    if brightness < 95:
        return round(brightness, 2), 'low_light'
    if brightness > 220:
        return round(brightness, 2), 'overexposed'
    return round(brightness, 2), 'day'


def prepare_detection_image(image, day_night):
    if image is None:
        return None
    if day_night in {'night', 'low_light'}:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    if day_night == 'overexposed':
        return cv2.convertScaleAbs(image, alpha=0.9, beta=-10)
    return image


def draw_detection_box(image, box, text, color):
    x1, y1, x2, y2 = box
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    (text_w, text_h), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
    label_top = max(y1 - text_h - baseline - 8, 0)
    label_bottom = max(y1, label_top + text_h + baseline + 8)
    label_right = min(x1 + text_w + 10, image.shape[1] - 1)
    cv2.rectangle(image, (x1, label_top), (label_right, label_bottom), color, -1)
    cv2.putText(image, text, (x1 + 4, label_bottom - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)


def classify_detection_validation(confidence, threshold):
    if confidence >= threshold:
        return 'validated'
    if confidence >= max(0.0, threshold - 0.10):
        return 'review_suggested'
    return 'review_required'


def summarize_primary_detection(detections, threshold):
    if not detections:
        return {
            'primary_label': None,
            'primary_confidence': 0.0,
            'validator': 'no_target_object',
            'validation_passed': False,
            'confidence_threshold': threshold,
        }
    primary = max(detections, key=lambda item: float(item.get('confidence', 0.0)))
    primary_confidence = float(primary.get('confidence', 0.0))
    validator = classify_detection_validation(primary_confidence, threshold)
    return {
        'primary_label': primary.get('label'),
        'primary_confidence': round(primary_confidence, 3),
        'validator': validator,
        'validation_passed': validator == 'validated',
        'confidence_threshold': threshold,
    }


def build_annotation_payload(event_id, model_name, day_night, light_level, threshold, detections, image_shape, perception=None):
    payload = {
        'event_id': event_id,
        'model': model_name,
        'day_night': day_night,
        'light_level': light_level,
        'confidence_threshold': threshold,
        'annotation_mode': 'label-centric',
        'image': {
            'width': int(image_shape[1]),
            'height': int(image_shape[0]),
        },
        'detection_count': len(detections),
        'detections': detections,
    }
    if perception is not None:
        payload['perception'] = perception
    return payload


def expand_motion_bbox(motion_bbox, width, height, padding=0.20):
    if not motion_bbox:
        return {'x1': 0, 'y1': 0, 'x2': int(width), 'y2': int(height)}
    x1 = int(motion_bbox.get('x1', 0))
    y1 = int(motion_bbox.get('y1', 0))
    x2 = int(motion_bbox.get('x2', width))
    y2 = int(motion_bbox.get('y2', height))
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    pad_x = int(box_w * padding)
    pad_y = int(box_h * padding)
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(width, x2 + pad_x)
    y2 = min(height, y2 + pad_y)
    return {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}


def select_detection_region(source_image, motion_metrics=None):
    h, w = source_image.shape[:2]
    if not motion_metrics:
        return source_image, {'x1': 0, 'y1': 0, 'x2': w, 'y2': h}
    motion_bbox = motion_metrics.get('motion_bbox') if isinstance(motion_metrics, dict) else None
    if not motion_bbox:
        return source_image, {'x1': 0, 'y1': 0, 'x2': w, 'y2': h}
    roi = expand_motion_bbox(motion_bbox, w, h)
    x1, y1, x2, y2 = roi['x1'], roi['y1'], roi['x2'], roi['y2']
    if x2 <= x1 or y2 <= y1:
        return source_image, {'x1': 0, 'y1': 0, 'x2': w, 'y2': h}
    return source_image[y1:y2, x1:x2], roi


def motion_bbox_union(boxes):
    if not boxes:
        return None
    x1 = min(box[0] for box in boxes)
    y1 = min(box[1] for box in boxes)
    x2 = max(box[2] for box in boxes)
    y2 = max(box[3] for box in boxes)
    return {'x1': int(x1), 'y1': int(y1), 'x2': int(x2), 'y2': int(y2)}


def compute_motion_metrics(current_path):
    if not OPENCV_AVAILABLE:
        return None, "OpenCV not available"

    if not BASELINE_PATH.exists():
        return None, "Baseline image does not exist"

    baseline = cv2.imread(str(BASELINE_PATH))
    current = cv2.imread(str(current_path))

    if baseline is None:
        return None, "Could not read baseline image"
    if current is None:
        return None, "Could not read current image"

    if baseline.shape != current.shape:
        baseline = cv2.resize(baseline, (current.shape[1], current.shape[0]))

    baseline_gray = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)

    baseline_gray = cv2.GaussianBlur(baseline_gray, (21, 21), 0)
    current_gray = cv2.GaussianBlur(current_gray, (21, 21), 0)

    baseline_mean = float(baseline_gray.mean())
    current_mean = float(current_gray.mean())
    brightness_delta = abs(current_mean - baseline_mean)

    diff = cv2.absdiff(baseline_gray, current_gray)
    _, threshold = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    threshold = cv2.dilate(threshold, None, iterations=2)
    threshold = cv2.erode(threshold, None, iterations=1)

    changed_pixels = cv2.countNonZero(threshold)
    total_pixels = threshold.shape[0] * threshold.shape[1]
    changed_percent = (changed_pixels / total_pixels) * 100 if total_pixels else 0.0

    contours_result = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = contours_result[0] if len(contours_result) == 2 else contours_result[1]
    boxes = []
    for contour in contours:
        if cv2.contourArea(contour) < AUTO_CAPTURE_MIN_MOTION_PIXELS:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        boxes.append((x, y, x + w, y + h))

    lighting_shift = brightness_delta >= MOTION_SETTINGS["brightness_delta"] and changed_percent >= 40.0
    if lighting_shift:
        boxes = []

    return {
        'changed_percent': round(changed_percent, 2),
        'changed_pixels': int(changed_pixels),
        'motion_bbox': motion_bbox_union(boxes),
        'motion_box_count': len(boxes),
        'brightness_delta': round(brightness_delta, 2),
        'lighting_shift': lighting_shift,
    }, None


def should_auto_capture(motion_metrics):
    if not AUTO_CAPTURE_ENABLED or not motion_metrics:
        monitor_state["motion_streak"] = 0
        monitor_state["motion_trigger"] = "disabled"
        return False, "auto capture disabled"

    if motion_metrics.get("lighting_shift"):
        monitor_state["motion_streak"] = 0
        monitor_state["last_motion_pixels"] = motion_metrics['changed_pixels']
        monitor_state["last_motion_bbox"] = None
        monitor_state["motion_trigger"] = "lighting shift"
        return False, "lighting shift"

    changed_percent = motion_metrics['changed_percent']
    motion_pixels = motion_metrics['changed_pixels']
    motion_bbox = motion_metrics['motion_bbox']
    diff_percent = float(MOTION_SETTINGS["diff_percent"])
    min_motion_pixels = int(MOTION_SETTINGS["min_motion_pixels"])
    persistence_frames = max(1, int(MOTION_SETTINGS["persistence_frames"]))

    if changed_percent < diff_percent or motion_pixels < min_motion_pixels or motion_bbox is None:
        monitor_state["motion_streak"] = 0
        monitor_state["last_motion_pixels"] = motion_pixels
        monitor_state["last_motion_bbox"] = motion_bbox
        monitor_state["motion_trigger"] = "below threshold"
        return False, "below threshold"

    monitor_state["motion_streak"] = monitor_state.get("motion_streak", 0) + 1
    monitor_state["last_motion_pixels"] = motion_pixels
    monitor_state["last_motion_bbox"] = motion_bbox
    monitor_state["motion_trigger"] = f"streak {monitor_state['motion_streak']}/{persistence_frames}"

    if monitor_state["motion_streak"] < persistence_frames:
        return False, monitor_state["motion_trigger"]

    return True, f"{changed_percent:.2f}% changed, bbox={motion_bbox}"

def analyze_image(event_id, raw_filename, confidence_threshold=0.50, motion_metrics=None):
    if not OPENCV_AVAILABLE:
        update_event(event_id, notes="OpenCV not available")
        return None, "OpenCV not available", 0

    if not PROTOTXT.exists() or not MODEL.exists():
        update_event(event_id, notes="Object detection model files missing")
        return None, "Object detection model files missing", 0

    raw_path = RAW_DIR / raw_filename

    if not raw_path.exists():
        update_event(event_id, notes="Raw image file missing")
        return None, "Raw image file missing", 0

    source_image = cv2.imread(str(raw_path))

    if source_image is None:
        update_event(event_id, notes="Could not read raw image")
        return None, "Could not read raw image", 0

    h, w = source_image.shape[:2]
    light_level, day_night = classify_light_level(source_image)
    update_event(event_id, light_level=light_level, day_night=day_night)

    if day_night in {'night', 'low_light', 'overexposed'}:
        confidence_threshold = max(confidence_threshold, 0.65)

    region_image, analysis_region = select_detection_region(source_image, motion_metrics)
    analysis_image = prepare_detection_image(region_image, day_night)
    if analysis_image is None:
        analysis_image = region_image
    annotated_image = source_image.copy()
    if analysis_region and (analysis_region['x1'] or analysis_region['y1'] or analysis_region['x2'] != w or analysis_region['y2'] != h):
        cv2.rectangle(
            annotated_image,
            (analysis_region['x1'], analysis_region['y1']),
            (analysis_region['x2'], analysis_region['y2']),
            (255, 165, 0),
            1,
        )
    model_name = 'opencv-dnn-mobilenetssd'
    net = cv2.dnn.readNetFromCaffe(str(PROTOTXT), str(MODEL))

    region_h, region_w = analysis_image.shape[:2]
    blob = cv2.dnn.blobFromImage(
        cv2.resize(analysis_image, (300, 300)),
        0.007843,
        (300, 300),
        127.5
    )

    net.setInput(blob)
    detections = net.forward()

    detection_count = 0
    detection_summaries = []
    annotation_detections = []
    palette = {
        'person': (0, 200, 255),
        'car': (0, 255, 0),
        'bicycle': (255, 180, 0),
        'dog': (255, 90, 90),
        'cat': (180, 120, 255),
        'bus': (255, 160, 0),
        'motorbike': (0, 180, 255),
    }

    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])

        if confidence < confidence_threshold:
            continue

        class_id = int(detections[0, 0, i, 1])

        if class_id >= len(CLASSES):
            continue

        label = CLASSES[class_id]

        if label not in TARGET_CLASSES:
            continue

        box = detections[0, 0, i, 3:7] * [region_w, region_h, region_w, region_h]
        x1, y1, x2, y2 = box.astype("int")
        x1 += analysis_region['x1']
        y1 += analysis_region['y1']
        x2 += analysis_region['x1']
        y2 += analysis_region['y1']

        x1 = int(max(0, x1))
        y1 = int(max(0, y1))
        x2 = int(min(w, x2))
        y2 = int(min(h, y2))

        text = f"{label}: {confidence:.2f}"
        color = palette.get(label, (0, 255, 0))

        draw_detection_box(annotated_image, (x1, y1, x2, y2), text, color)

        insert_detection(event_id, label, confidence, x1, y1, x2, y2)
        annotation_detections.append({
            'label': label,
            'confidence': round(confidence, 3),
            'validator': classify_detection_validation(confidence, confidence_threshold),
            'bbox': {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2},
        })
        detection_summaries.append(f"{label} {confidence:.2f}")
        detection_count += 1

    annotated_filename = f"annotated_{raw_filename}"
    annotated_path = ANNOTATED_DIR / annotated_filename

    cv2.imwrite(str(annotated_path), annotated_image)

    if detection_count == 0:
        message = "Baseline change detected; no target objects detected"
    else:
        message = "Detected: " + ", ".join(detection_summaries)

    message = f"{message}. Light: {day_night} ({light_level})"
    perception = summarize_primary_detection(annotation_detections, confidence_threshold)
    if annotation_detections:
        annotation_detections.sort(key=lambda item: float(item.get('confidence', 0.0)), reverse=True)
    annotation_payload = build_annotation_payload(
        event_id=event_id,
        model_name=model_name,
        day_night=day_night,
        light_level=light_level,
        threshold=confidence_threshold,
        detections=annotation_detections,
        image_shape=source_image.shape,
        perception=perception,
    )
    annotation_payload['analysis_region'] = analysis_region
    if motion_metrics is not None:
        annotation_payload['motion_metrics'] = motion_metrics
    update_event(
        event_id,
        annotated_image=annotated_filename,
        notes=message,
        light_level=light_level,
        day_night=day_night,
        annotation_json=json.dumps(annotation_payload),
        annotation_model=model_name,
    )
    prune_old_annotated_images(keep=10)

    return annotated_filename, message, detection_count


def compute_baseline_diff(current_path):
    if not OPENCV_AVAILABLE:
        return None, "OpenCV not available"

    if not BASELINE_PATH.exists():
        return None, "Baseline image does not exist"

    baseline = cv2.imread(str(BASELINE_PATH))
    current = cv2.imread(str(current_path))

    if baseline is None:
        return None, "Could not read baseline image"

    if current is None:
        return None, "Could not read current image"

    if baseline.shape != current.shape:
        baseline = cv2.resize(baseline, (current.shape[1], current.shape[0]))

    baseline_gray = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)

    baseline_gray = cv2.GaussianBlur(baseline_gray, (21, 21), 0)
    current_gray = cv2.GaussianBlur(current_gray, (21, 21), 0)

    diff = cv2.absdiff(baseline_gray, current_gray)
    _, threshold = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

    changed_pixels = cv2.countNonZero(threshold)
    total_pixels = threshold.shape[0] * threshold.shape[1]

    changed_percent = (changed_pixels / total_pixels) * 100

    return changed_percent, None


def monitor_loop():
    while True:
        if monitor_state["enabled"]:
            monitor_state["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if not BASELINE_PATH.exists():
                monitor_state["last_error"] = "Monitoring enabled, but no baseline is set"
                time.sleep(MONITOR_INTERVAL_SECONDS)
                continue

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"event_check_{timestamp}.jpg"
            current_path = RAW_DIR / filename

            ok, capture_message = capture_to_path(current_path)

            if not ok:
                monitor_state["last_error"] = capture_message
                time.sleep(MONITOR_INTERVAL_SECONDS)
                continue

            motion_metrics, diff_error = compute_motion_metrics(current_path)

            if diff_error or motion_metrics is None:
                monitor_state["last_error"] = diff_error or "Motion metrics unavailable"
                monitor_state["motion_streak"] = 0
                try:
                    current_path.unlink()
                except Exception:
                    pass
                time.sleep(MONITOR_INTERVAL_SECONDS)
                continue

            monitor_state["last_diff_percent"] = motion_metrics['changed_percent']
            monitor_state["last_error"] = ""

            now = time.time()
            should_capture, trigger_reason = should_auto_capture(motion_metrics)
            cooldown_passed = (now - monitor_state["last_event_time"]) >= AUTO_CAPTURE_COOLDOWN_SECONDS

            if should_capture and cooldown_passed:
                notes = (
                    f"Motion persisted across {AUTO_CAPTURE_PERSISTENCE_FRAMES} checks: "
                    f"{motion_metrics['changed_percent']:.2f}% changed pixels; "
                    f"motion bbox={motion_metrics['motion_bbox']}"
                )

                event_id = insert_event(
                    event_type="motion_persistent",
                    raw_image=filename,
                    client_ip="auto-monitor",
                    notes=notes,
                    source="auto-monitor",
                    diff_percent=round(motion_metrics['changed_percent'], 2),
                )

                annotated_filename, ai_message, detection_count = analyze_image(event_id, filename, motion_metrics=motion_metrics)
                queue_event_video_capture(event_id, filename)
                final_note = f"{notes}. Trigger: {trigger_reason}. {ai_message}"
                update_event(event_id, notes=final_note)

                monitor_state["last_event"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                monitor_state["last_event_time"] = now
                monitor_state["motion_streak"] = 0
            else:
                try:
                    current_path.unlink()
                except Exception:
                    pass

        time.sleep(MONITOR_INTERVAL_SECONDS)


def start_monitor_thread():
    global monitor_thread

    if monitor_thread is None or not monitor_thread.is_alive():
        monitor_thread = Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()




def run_command(command, timeout=3):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout
        )
    except Exception as e:
        return False, str(e)

    output = (result.stdout or result.stderr or '').strip()
    return result.returncode == 0, output


def count_events():
    if not DB_PATH.exists():
        return 0
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM events')
    count = cur.fetchone()[0]
    conn.close()
    return count


def get_last_client_ip():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT client_ip
        FROM events
        WHERE client_ip IS NOT NULL
          AND client_ip != ''
          AND client_ip != 'auto-monitor'
        ORDER BY id DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 'None recorded'


def get_journal_tail(limit=12):
    ok, output = run_command(['journalctl', '-u', 'home-sentinel.service', '-n', str(limit), '--no-pager'])
    if ok and output:
        return output.splitlines()[-limit:]
    return [f'journal unavailable: {output or "unknown error"}']


def get_service_details():
    ok_active, active_output = run_command(['systemctl', 'is-active', 'home-sentinel.service'])
    ok_restarts, restarts_output = run_command(['systemctl', 'show', '-p', 'NRestarts', '--value', 'home-sentinel.service'])
    ok_pid, pid_output = run_command(['systemctl', 'show', '-p', 'MainPID', '--value', 'home-sentinel.service'])
    ok_started, started_output = run_command(['systemctl', 'show', '-p', 'ActiveEnterTimestamp', '--value', 'home-sentinel.service'])

    return {
        'status': active_output.strip() if ok_active and active_output else 'unknown',
        'restart_count': int((restarts_output or '0').strip() or 0) if ok_restarts else 0,
        'main_pid': int((pid_output or '0').strip() or 0) if ok_pid else 0,
        'last_started': started_output.strip() if ok_started and started_output else 'unknown',
    }


def get_wifi_status():
    ok, output = run_command(['sh', '-c', "iw dev wlan0 link 2>/dev/null || iwconfig wlan0 2>/dev/null"])
    if ok and output:
        return output.strip().splitlines()
    return ['Wi-Fi status unavailable']


def get_request_summary():
    items = sorted(ENDPOINT_COUNTS.items(), key=lambda kv: kv[1], reverse=True)
    return [{'endpoint': k, 'count': v} for k, v in items[:12]]


def get_request_latency_summary():
    stats = {}
    for item in REQUEST_LOG:
        duration = item.get('duration_ms')
        endpoint = item.get('endpoint') or item.get('path') or 'unknown'
        if duration is None:
            continue
        bucket = stats.setdefault(endpoint, {'endpoint': endpoint, 'count': 0, 'total_ms': 0.0, 'max_ms': 0.0})
        bucket['count'] += 1
        bucket['total_ms'] += float(duration)
        bucket['max_ms'] = max(bucket['max_ms'], float(duration))
    rows = []
    for bucket in stats.values():
        rows.append({
            'endpoint': bucket['endpoint'],
            'count': bucket['count'],
            'avg_ms': round(bucket['total_ms'] / bucket['count'], 1) if bucket['count'] else 0,
            'max_ms': round(bucket['max_ms'], 1),
        })
    rows.sort(key=lambda r: (r['avg_ms'], r['count']), reverse=True)
    return rows[:12]


def get_cpu_temp_c():
    for candidate in ['/sys/class/thermal/thermal_zone0/temp', '/sys/class/thermal/thermal_zone1/temp']:
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                raw = f.read().strip()
            if raw.isdigit():
                return round(int(raw) / 1000.0, 1)
        except Exception:
            pass
    return 'unknown'


def get_interface_traffic():
    stats = {}
    try:
        with open('/proc/net/dev', 'r', encoding='utf-8') as f:
            for line in f.readlines()[2:]:
                if ':' not in line:
                    continue
                iface, data = line.split(':', 1)
                iface = iface.strip()
                fields = data.split()
                if len(fields) >= 16:
                    stats[iface] = {'rx_bytes': int(fields[0]), 'tx_bytes': int(fields[8])}
    except Exception:
        pass
    return stats


def summarize_interface_traffic():
    traffic = get_interface_traffic()
    summary = []
    for iface in ['wlan0', 'tailscale0', 'eth0']:
        if iface in traffic:
            rx = traffic[iface]['rx_bytes']
            tx = traffic[iface]['tx_bytes']
            summary.append({'interface': iface, 'rx_mb': round(rx / 1024 / 1024, 2), 'tx_mb': round(tx / 1024 / 1024, 2)})
    return summary


def get_client_history(limit=8):
    counts = {}
    for item in REQUEST_LOG:
        ip = item.get('client_ip') or 'unknown'
        counts[ip] = counts.get(ip, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{'client_ip': ip, 'count': count} for ip, count in rows]


def get_camera_health_summary():
    successes = [c for c in CAPTURE_HISTORY if c.get('success')]
    failures = [c for c in CAPTURE_HISTORY if not c.get('success')]
    last_failure = failures[0].get('message', '') if failures else 'None'
    avg_capture = None
    if successes:
        vals = [c['seconds'] for c in successes if isinstance(c.get('seconds'), (int, float))]
        if vals:
            avg_capture = round(sum(vals) / len(vals), 3)
    return {'success_count': len(successes), 'failure_count': len(failures), 'last_failure': last_failure, 'avg_capture_seconds': avg_capture}


def get_camera_cpu_summary():
    summary = []
    labels = [
        ('arducam', 'Arducam'),
        ('logitech', 'Logitech'),
    ]
    for camera_key, camera_label in labels:
        samples = [c for c in CAPTURE_HISTORY if c.get('success') and c.get('camera_key') == camera_key]
        cpu_values = [c['cpu_percent'] for c in samples if isinstance(c.get('cpu_percent'), (int, float))]
        seconds_values = [c['seconds'] for c in samples if isinstance(c.get('seconds'), (int, float))]
        summary.append({
            'camera_key': camera_key,
            'camera_label': camera_label,
            'samples': len(samples),
            'avg_cpu_percent': round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None,
            'avg_capture_seconds': round(sum(seconds_values) / len(seconds_values), 3) if seconds_values else None,
        })
    return summary


def get_stream_health_summary():
    stream = estimate_stream_metrics()
    cap = get_camera_health_summary()
    total = cap['success_count'] + cap['failure_count']
    success_rate = round((cap['success_count'] / total) * 100, 1) if total else 0
    return {'fps': STREAM_FPS, 'avg_frame_bytes': stream['average_frame_bytes'], 'estimated_mbps': stream['estimated_mbps'], 'capture_success_rate': success_rate, 'avg_capture_seconds': cap['avg_capture_seconds']}


def get_compute_metrics():
    loadavg = 'unknown'
    try:
        with open('/proc/loadavg', 'r', encoding='utf-8') as f:
            loadavg = f.read().strip().split()[:3]
    except Exception:
        pass

    mem_total = mem_available = mem_used_percent = 'unknown'
    try:
        meminfo = {}
        with open('/proc/meminfo', 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    key, value = line.split(':', 1)
                    meminfo[key.strip()] = value.strip().split()[0]
        mem_total_kb = float(meminfo.get('MemTotal', 0) or 0)
        mem_available_kb = float(meminfo.get('MemAvailable', 0) or 0)
        if mem_total_kb:
            mem_total = round(mem_total_kb / 1024, 1)
            mem_available = round(mem_available_kb / 1024, 1)
            mem_used_percent = round(((mem_total_kb - mem_available_kb) / mem_total_kb) * 100, 1)
    except Exception:
        pass

    disk_used_percent = 'unknown'
    disk_free_gb = 'unknown'
    ok_disk, disk_output = run_command(['df', '-P', '/'])
    if ok_disk and disk_output:
        lines = disk_output.splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 6:
                disk_used_percent = parts[4]
                try:
                    disk_free_gb = round(int(parts[3]) / 1024 / 1024, 2)
                except Exception:
                    pass
    boot_time = 'unknown'
    ok_boot, boot_output = run_command(['who', '-b'])
    if ok_boot and boot_output:
        boot_time = boot_output.strip()
    return {
        'loadavg': loadavg,
        'mem_total_gb': mem_total,
        'mem_available_gb': mem_available,
        'mem_used_percent': mem_used_percent,
        'disk_used_percent': disk_used_percent,
        'disk_free_gb': disk_free_gb,
        'boot_time': boot_time,
    }


def estimate_stream_metrics(sample_count=5):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT raw_image
        FROM events
        WHERE raw_image IS NOT NULL AND raw_image != ''
        ORDER BY id DESC
        LIMIT ?
    """, (sample_count,))
    rows = cur.fetchall()
    conn.close()

    sizes = []
    for (raw_image,) in rows:
        path = RAW_DIR / raw_image
        if path.exists():
            try:
                sizes.append(path.stat().st_size)
            except Exception:
                pass

    if not sizes:
        return {
            'sample_count': 0,
            'average_frame_bytes': 0,
            'estimated_mbps': 0,
        }

    avg_bytes = sum(sizes) / len(sizes)
    estimated_mbps = (avg_bytes * STREAM_FPS * 8) / 1_000_000
    return {
        'sample_count': len(sizes),
        'average_frame_bytes': round(avg_bytes, 1),
        'estimated_mbps': round(estimated_mbps, 3),
    }


def network_snapshot(current_client_ip=None):
    ok_hostname, hostname_ips = run_command(['hostname', '-I'])
    all_ips = hostname_ips.split() if ok_hostname and hostname_ips else []
    lan_ips = [ip for ip in all_ips if ip.startswith('192.168.') or ip.startswith('10.') or ip.startswith('172.')]
    tailscale_ips = [ip for ip in all_ips if ip.startswith('100.')]

    ok_gateway, gateway_output = run_command(['sh', '-c', 'ip route | grep default | head -n 1'])
    default_gateway = gateway_output if ok_gateway and gateway_output else 'Unknown'

    ok_interfaces, interfaces_output = run_command(['ip', '-o', '-4', 'addr', 'show', 'scope', 'global'])
    interfaces = []
    if ok_interfaces and interfaces_output:
        for line in interfaces_output.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                interfaces.append({'name': parts[1], 'address': parts[3]})

    ok_ports, ports_output = run_command(['ss', '-tulnp'])
    listening_ports = []
    if ok_ports and ports_output:
        for line in ports_output.splitlines():
            if ':22' in line or ':5000' in line:
                listening_ports.append(line)

    service_details = get_service_details()
    camera_path = '/dev/video0'
    camera_status = 'present' if os.path.exists(camera_path) else 'missing'

    db_exists = DB_PATH.exists()
    db_size_bytes = DB_PATH.stat().st_size if db_exists else 0

    gateway_ping = 'not checked'
    if default_gateway != 'Unknown':
        gateway_ip = default_gateway.split()[-1]
        ok_ping, ping_output = run_command(['ping', '-c', '1', '-W', '1', gateway_ip])
        gateway_ping = 'reachable' if ok_ping else (ping_output.splitlines()[-1] if ping_output else 'unreachable')

    dns_lookup = 'not checked'
    ok_dns, dns_output = run_command(['getent', 'hosts', socket.gethostname()])
    if ok_dns and dns_output:
        dns_lookup = dns_output.splitlines()[0]
    else:
        dns_lookup = 'hostname lookup failed'

    wifi_status = get_wifi_status()
    journal_tail = get_journal_tail(12)
    request_summary = get_request_summary()
    request_latency_summary = get_request_latency_summary()
    stream_metrics = estimate_stream_metrics()
    compute_metrics = get_compute_metrics()
    cpu_temp_c = get_cpu_temp_c()
    interface_traffic = summarize_interface_traffic()
    client_history = get_client_history()
    camera_health = get_camera_health_summary()
    camera_cpu_summary = get_camera_cpu_summary()
    stream_health = get_stream_health_summary()

    recent_requests = list(REQUEST_LOG)[:20]

    return {
        'hostname': socket.gethostname(),
        'lan_ips': lan_ips,
        'tailscale_ips': tailscale_ips,
        'all_ips': all_ips,
        'default_gateway': default_gateway,
        'interfaces': interfaces,
        'listening_ports': listening_ports,
        'service_status': service_details['status'],
        'service_details': service_details,
        'current_client_ip': current_client_ip or 'Unknown',
        'last_recorded_client_ip': get_last_client_ip(),
        'uptime_seconds': int(time.time() - start_time),
        'camera_device': camera_path,
        'camera_status': camera_status,
        'database_path': str(DB_PATH),
        'database_exists': db_exists,
        'database_size_bytes': db_size_bytes,
        'event_count': count_events(),
        'stream_metrics': stream_metrics,
        'compute_metrics': compute_metrics,
        'cpu_temp_c': cpu_temp_c,
        'request_latency_summary': request_latency_summary,
        'interface_traffic': interface_traffic,
        'client_history': client_history,
        'camera_health': camera_health,
        'camera_cpu_summary': camera_cpu_summary,
        'stream_health': stream_health,
        'gateway_ping': gateway_ping,
        'dns_lookup': dns_lookup,
        'wifi_status': wifi_status,
        'request_summary': request_summary,
        'recent_requests': recent_requests,
        'journal_tail': journal_tail,
        'recent_captures': list(CAPTURE_HISTORY)[:10],
        'last_capture_seconds': LAST_CAPTURE_SECONDS,
        'network_plus_map': {
            'ip_addressing': 'LAN/Tailscale IPs show where the server lives.',
            'default_gateway': 'Default route shows where off-LAN traffic goes.',
            'ports': 'TCP 22 is SSH; TCP 5000 is the Flask dashboard.',
            'client_server': 'Current and last client IPs show who connected.',
            'services': 'systemd status shows whether Home Sentinel is running.',
            'local_device': 'USB camera is local /dev/video0, not a network camera yet.'
        }
    }
def html_list(items):
    if not items:
        return '<li>None detected</li>'
    return ''.join([f'<li>{item}</li>' for item in items])


def event_to_dict(row):
    keys = [
        'id', 'timestamp', 'event_type', 'raw_image', 'annotated_image', 'clip_video',
        'client_ip', 'notes', 'source', 'diff_percent', 'light_level', 'day_night',
        'annotation_json', 'annotation_model', 'clip_status', 'clip_seconds', 'clip_fps', 'clip_size_bytes'
    ]
    data = dict(zip(keys, row))
    data['raw_url'] = f"/raw/{data['raw_image']}" if data.get('raw_image') else None
    data['annotated_url'] = f"/annotated/{data['annotated_image']}" if data.get('annotated_image') else None
    data['clip_url'] = f"/clips/{data['clip_video']}" if data.get('clip_video') else None
    data['detections'] = get_detections_for_event(data['id'])
    try:
        data['annotation'] = json.loads(data.get('annotation_json') or '{}')
    except Exception:
        data['annotation'] = {}
    return data


def search_events(q='', event_type='', label='', limit=50):
    try:
        limit = max(1, min(500, int(limit)))
    except Exception:
        limit = 50

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    where = []
    args = []

    if q:
        like = f"%{q.lower()}%"
        where.append("""
            (
                LOWER(e.event_type) LIKE ? OR
                LOWER(COALESCE(e.client_ip, '')) LIKE ? OR
                LOWER(COALESCE(e.source, '')) LIKE ? OR
                LOWER(COALESCE(e.notes, '')) LIKE ? OR
                LOWER(COALESCE(e.day_night, '')) LIKE ? OR
                LOWER(COALESCE(d.label, '')) LIKE ? OR
                LOWER(COALESCE(d.review_status, '')) LIKE ?
            )
        """)
        args.extend([like, like, like, like, like, like, like])

    if event_type:
        where.append('e.event_type = ?')
        args.append(event_type)

    if label:
        where.append('d.label = ?')
        args.append(label)

    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    cur.execute(f"""
        SELECT DISTINCT
            e.id, e.timestamp, e.event_type, e.raw_image, e.annotated_image, e.clip_video,
            e.client_ip, e.notes, e.source, e.diff_percent, e.light_level, e.day_night,
            e.annotation_json, e.annotation_model, e.clip_status, e.clip_seconds, e.clip_fps, e.clip_size_bytes
        FROM events e
        LEFT JOIN detections d ON d.event_id = e.id
        {where_sql}
        ORDER BY e.id DESC
        LIMIT ?
    """, args + [limit])
    rows = cur.fetchall()
    conn.close()
    return [event_to_dict(row) for row in rows]


def get_event_detail(event_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, timestamp, event_type, raw_image, annotated_image, clip_video,
               client_ip, notes, source, diff_percent, light_level, day_night,
               annotation_json, annotation_model, clip_status, clip_seconds, clip_fps, clip_size_bytes
        FROM events
        WHERE id = ?
    """, (event_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return event_to_dict(row)


@app.route('/api/events')
def api_events():
    init_db()
    return jsonify({
        'events': search_events(
            q=request.args.get('q', '').strip(),
            event_type=request.args.get('event_type', '').strip(),
            label=request.args.get('label', '').strip(),
            limit=request.args.get('limit', 50)
        )
    })


@app.route('/api/events/<int:event_id>')
def api_event_detail(event_id):
    init_db()
    event = get_event_detail(event_id)
    if event is None:
        return jsonify({'error': 'event not found'}), 404
    return jsonify(event)


@app.route('/api/events/<int:event_id>/annotation')
def api_event_annotation(event_id):
    init_db()
    event = get_event_detail(event_id)
    if event is None:
        return jsonify({'error': 'event not found'}), 404
    return jsonify({
        'event_id': event_id,
        'timestamp': event['timestamp'],
        'annotation': event.get('annotation') or {},
        'detections': event.get('detections') or [],
        'annotated_url': event.get('annotated_url'),
        'raw_url': event.get('raw_url'),
        'clip_url': event.get('clip_url'),
        'clip_status': event.get('clip_status'),
        'clip_seconds': event.get('clip_seconds'),
        'clip_fps': event.get('clip_fps'),
        'clip_size_bytes': event.get('clip_size_bytes'),
        'annotation_model': event.get('annotation_model'),
    })


@app.route('/annotations')
def annotations_page():
    init_db()
    events = get_recent_annotated_events(10)
    cards = []
    for event in events:
        annotation = event.get('annotation') or {}
        perception = annotation.get('perception') or {}
        detections = annotation.get('detections') or event.get('detections') or []
        detection_text = ", ".join([
            f"{d.get('label', '')} {float(d.get('confidence', 0)):.2f}"
            for d in detections
        ]) or "No detections"
        image_html = ""
        clip_html = ""
        if event.get('annotated_url'):
            image_html = '<img src="{src}?t={ts}" style="width:100%;height:auto;border:1px solid #243048;border-radius:6px;" />'.format(
                src=event["annotated_url"],
                ts=int(__import__("time").time()),
            )
        if event.get('clip_url'):
            clip_html = '<video controls preload="metadata" style="width:100%;max-width:100%;border:1px solid #243048;border-radius:6px;margin-top:8px;" src="{src}?t={ts}"></video>'.format(
                src=event["clip_url"],
                ts=int(__import__("time").time()),
            )
        bbox_rows = "".join([
            f"<tr><td>{d.get('label', '')}</td><td>{float(d.get('confidence', 0)):.2f}</td><td>{d.get('validator', 'unknown')}</td><td>{d.get('bbox', {})}</td></tr>"
            for d in detections
        ]) or '<tr><td colspan="4">No detections</td></tr>'
        cards.append(f"""
        <section class="annotation-card">
            <div class="annotation-media">{image_html}{clip_html}</div>
            <div class="annotation-meta">
                <p><strong>ID:</strong> {event['id']} | <strong>Time:</strong> {event['timestamp']}</p>
                <p><strong>Model:</strong> {event.get('annotation_model') or annotation.get('model') or 'unknown'}</p>
                <p><strong>Light:</strong> {event.get('light_level') if event.get('light_level') is not None else annotation.get('light_level', 'unknown')} | <strong>Day/Night:</strong> {event.get('day_night') or annotation.get('day_night') or 'unknown'}</p>
                <p><strong>Primary Label:</strong> {perception.get('primary_label') or 'none'}</p>
                <p><strong>Primary Confidence:</strong> {perception.get('primary_confidence', 0):.2f}</p>
                <p><strong>Confidence Validator:</strong> {perception.get('validator') or 'unknown'}</p>
                <p><strong>Detections:</strong> {detection_text}</p>
                <p><a href="/api/events/{event['id']}/annotation">Annotation JSON</a> | <a href="/api/events/{event['id']}">Event JSON</a></p>
                <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
                    <tr><th>Label</th><th>Confidence</th><th>Validator</th><th>BBox</th></tr>
                    {bbox_rows}
                </table></div>
            </div>
        </section>
        """)
    gallery = "".join(cards) or "<p>No annotated images yet.</p>"
    page = """
    <html>
    <head>
        <title>Home Sentinel Annotations</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {style}
        <style>
            .annotation-grid {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
            .annotation-card {{ border: 1px solid #243048; border-radius: 8px; padding: 12px; background: #101723; }}
            .annotation-meta p {{ margin: 0 0 8px 0; }}
            .annotation-media {{ margin-bottom: 10px; }}
            @media (min-width: 900px) {{
                .annotation-grid {{ grid-template-columns: 1fr 1fr; }}
            }}
        </style>
    </head>
    <body>
        <div class="top-links"><a href="/">Back to Dashboard</a><a href="/live?camera=arducam">Arducam View</a><a href="/live?camera=logitech">Logitech View</a><a href="/network">Network Status / Network+ Lab</a><a href="/api/events">Events API</a><a href="/annotations">Labeling</a><a href="/videos">Video Clips</a></div>
        <h1>Home Sentinel Label Review</h1>
        <h2>Last 10 Label-Validated Images</h2>
        <div class="annotation-grid">{gallery}</div>
    </body>
    </html>
    """.format(style=RESPONSIVE_STYLE, gallery=gallery)
    return page


@app.route('/videos')
def videos_page():
    init_db()
    events = [event for event in get_recent_annotated_events(25) if event.get('clip_url')]
    cards = []
    for event in events[:10]:
        annotation = event.get('annotation') or {}
        perception = annotation.get('perception') or {}
        detections = annotation.get('detections') or event.get('detections') or []
        detection_text = ", ".join([
            f"{d.get('label', '')} {float(d.get('confidence', 0)):.2f}"
            for d in detections
        ]) or "No detections"
        clip_html = '<video controls preload="metadata" playsinline style="width:100%;max-width:100%;border:1px solid #243048;border-radius:6px;" src="{src}?t={ts}"></video>'.format(
            src=event["clip_url"],
            ts=int(time.time()),
        )
        cards.append(f"""
        <section class="annotation-card">
            <div class="annotation-media">{clip_html}</div>
            <div class="annotation-meta">
                <p><strong>ID:</strong> {event['id']} | <strong>Time:</strong> {event['timestamp']}</p>
                <p><strong>Clip Status:</strong> {event.get('clip_status') or 'unknown'}</p>
                <p><strong>Clip Duration:</strong> {event.get('clip_seconds') or 'unknown'} s | <strong>FPS:</strong> {event.get('clip_fps') or 'unknown'}</p>
                <p><strong>Model:</strong> {event.get('annotation_model') or annotation.get('model') or 'unknown'}</p>
                <p><strong>Primary Label:</strong> {perception.get('primary_label') or 'none'}</p>
                <p><strong>Primary Confidence:</strong> {perception.get('primary_confidence', 0):.2f}</p>
                <p><strong>Detections:</strong> {detection_text}</p>
                <p><a href="/api/events/{event['id']}/annotation">Annotation JSON</a> | <a href="/api/events/{event['id']}">Event JSON</a> | <a href="/clips/{event['clip_video']}">Raw Clip</a></p>
            </div>
        </section>
        """)
    gallery = "".join(cards) or "<p>No clips yet.</p>"
    return f"""
    <html>
    <head>
        <title>Home Sentinel Video Clips</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
{RESPONSIVE_STYLE}        <style>
            .annotation-grid {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
            .annotation-card {{ border: 1px solid #243048; border-radius: 8px; padding: 12px; background: #101723; }}
            .annotation-meta p {{ margin: 0 0 8px 0; }}
            .annotation-media {{ margin-bottom: 10px; }}
            @media (min-width: 900px) {{
                .annotation-grid {{ grid-template-columns: 1fr 1fr; }}
            }}
        </style>
    </head>
    <body>
        <div class="top-links"><a href="/">Back to Dashboard</a><a href="/live">Live View</a><a href="/annotations">Annotations</a><a href="/network">Network Status</a><a href="/api/events">Events API</a></div>
        <h1>Home Sentinel Video Clips</h1>
        <h2>Last 10 Stored Event Clips</h2>
        <div class="annotation-grid">{gallery}</div>
    </body>
    </html>
    """

@app.route('/motion/settings', methods=['POST'])
def motion_settings():
    payload = request.form if request.form else (request.get_json(silent=True) or {})
    def parse_float(key, default):
        try:
            return float(payload.get(key, default))
        except Exception:
            return default
    def parse_int(key, default):
        try:
            return int(float(payload.get(key, default)))
        except Exception:
            return default
    MOTION_SETTINGS["diff_percent"] = max(0.1, parse_float("diff_percent", MOTION_SETTINGS["diff_percent"]))
    MOTION_SETTINGS["min_motion_pixels"] = max(1, parse_int("min_motion_pixels", MOTION_SETTINGS["min_motion_pixels"]))
    MOTION_SETTINGS["persistence_frames"] = max(1, parse_int("persistence_frames", MOTION_SETTINGS["persistence_frames"]))
    MOTION_SETTINGS["cooldown_seconds"] = max(0, parse_int("cooldown_seconds", MOTION_SETTINGS["cooldown_seconds"]))
    MOTION_SETTINGS["brightness_delta"] = max(0.0, parse_float("brightness_delta", MOTION_SETTINGS["brightness_delta"]))
    return redirect("/")


@app.route('/api/detections/<int:detection_id>/review', methods=['POST', 'PATCH'])
def api_review_detection(detection_id):
    init_db()
    payload = request.get_json(silent=True) or {}
    status = str(payload.get('review_status') or '').strip().lower()
    allowed = {'unreviewed', 'true_positive', 'false_positive', 'unsure'}
    if status not in allowed:
        return jsonify({'error': 'review_status must be unreviewed, true_positive, false_positive, or unsure'}), 400
    note = str(payload.get('review_note') or '').strip()
    reviewed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        UPDATE detections
        SET review_status = ?, review_note = ?, reviewed_at = ?
        WHERE id = ?
    """, (status, note, reviewed_at, detection_id))
    changed = cur.rowcount
    conn.commit()
    conn.close()

    if changed == 0:
        return jsonify({'error': 'detection not found'}), 404
    return jsonify({'success': True, 'detection_id': detection_id, 'review_status': status, 'review_note': note, 'reviewed_at': reviewed_at})


@app.route('/api/retrieve')
def api_retrieve_events():
    init_db()
    q = request.args.get('q', '').strip()
    events = search_events(q=q, limit=request.args.get('limit', 20))
    return jsonify({
        'query': q,
        'retrieved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'mode': 'home-sentinel-event-retrieval',
        'events': events,
        'analysis_prompt': 'Analyze retrieved Home Sentinel evidence. Separate direct evidence from inference. Summarize event types, detections, client/source, image links, and likely next troubleshooting or security actions.'
    })


def mjpeg_frames(delay_seconds=1/5, camera_key=None):
    camera_key = normalize_camera_key(camera_key)
    while True:
        frame_path = Path(tempfile.gettempdir()) / f'home_sentinel_stream_{camera_key}.jpg'
        ok, message = capture_to_path(frame_path, camera_key=camera_key)
        if ok and frame_path.exists():
            try:
                frame = frame_path.read_bytes()
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
                )
            except Exception:
                pass
        time.sleep(delay_seconds)


@app.route('/stream.mjpg')
def stream_mjpg():
    camera_key = normalize_camera_key(request.args.get('camera'))
    return Response(
        mjpeg_frames(delay_seconds=1/5, camera_key=camera_key),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/camera/preset', methods=['POST'])
def camera_preset():
    camera_key = normalize_camera_key((request.form.get('camera') or request.args.get('camera') or DEFAULT_CAMERA_KEY).strip())
    preset_name = str(request.form.get('preset') or '').strip()
    ok, message = apply_camera_preset(camera_key, preset_name)
    if not ok:
        return jsonify({'success': False, 'error': message}), 400
    return redirect(f"/live?camera={camera_key}")


@app.route('/camera/settings', methods=['POST'])
def camera_settings():
    camera_key = normalize_camera_key((request.form.get('camera') or request.args.get('camera') or DEFAULT_CAMERA_KEY).strip())
    controls = {
        'brightness': request.form.get('brightness'),
        'contrast': request.form.get('contrast'),
        'saturation': request.form.get('saturation'),
        'gain': request.form.get('gain'),
        'backlight_compensation': request.form.get('backlight_compensation'),
        'auto_exposure': request.form.get('auto_exposure'),
        'exposure_time_absolute': request.form.get('exposure_time_absolute'),
    }
    ok, message = apply_camera_controls(camera_key, controls)
    if not ok:
        return jsonify({'success': False, 'error': message}), 400
    return redirect(f"/live?camera={camera_key}")


@app.route('/camera/autotune', methods=['POST'])
def camera_autotune():
    camera_key = normalize_camera_key((request.form.get('camera') or request.args.get('camera') or DEFAULT_CAMERA_KEY).strip())
    settings = update_camera_autotune_settings(request.form if request.form else (request.get_json(silent=True) or {}))
    if camera_key == "arducam" and settings.get("enabled"):
        try:
            apply_camera_controls(camera_key, {
                "auto_exposure": 1,
                "exposure_time_absolute": settings.get("initial_exposure", 80),
                "gain": settings.get("initial_gain", 0),
                "backlight_compensation": 0,
            })
        except Exception:
            pass
    return redirect(f"/live?camera={camera_key}")


@app.route('/live')
def live_view():
    camera_key = normalize_camera_key(request.args.get('camera'))
    camera_label = CAMERA_PROFILES[camera_key]["label"]
    if camera_key == "arducam":
        try:
            apply_camera_preset(camera_key, "arducam_dark")
        except Exception:
            pass
    camera_device = resolve_camera_device(camera_key)
    camera_values = get_camera_control_snapshot(camera_key)
    stream_src = f"/stream.mjpg?camera={camera_key}&t={int(time.time())}"
    preset_buttons = ""
    camera_sliders = ""
    if camera_key == "arducam":
        current_auto = str(camera_values.get('auto_exposure', ''))
        selected_auto = ' selected' if current_auto == '3' else ''
        selected_manual = ' selected' if current_auto == '1' else ''
        preset_buttons = f"""
        <form action="/camera/preset" method="post" style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;">
            <input type="hidden" name="camera" value="{camera_key}">
            <button type="submit" name="preset" value="arducam_day" style="padding:10px 14px;">Day Preset</button>
            <button type="submit" name="preset" value="arducam_low_light" style="padding:10px 14px;">Low Light Preset</button>
            <button type="submit" name="preset" value="arducam_dark" style="padding:10px 14px;">Dark Preset</button>
            <button type="submit" name="preset" value="logitech_default" style="padding:10px 14px;">Reset Defaults</button>
        </form>
        """
        camera_sliders = f"""
        <form action="/camera/settings" method="post" style="margin:12px 0;">
            <input type="hidden" name="camera" value="{camera_key}">
            <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
                <tr><th>Control</th><th>Value</th><th>Range</th></tr>
                <tr><td>Brightness</td><td><input name="brightness" type="range" min="-64" max="64" step="1" value="{camera_values.get('brightness', '0')}" oninput="this.nextElementSibling.value=this.value"></td><td><output>{camera_values.get('brightness', '0')}</output></td></tr>
                <tr><td>Contrast</td><td><input name="contrast" type="range" min="0" max="64" step="1" value="{camera_values.get('contrast', '32')}" oninput="this.nextElementSibling.value=this.value"></td><td><output>{camera_values.get('contrast', '32')}</output></td></tr>
                <tr><td>Saturation</td><td><input name="saturation" type="range" min="0" max="128" step="1" value="{camera_values.get('saturation', '64')}" oninput="this.nextElementSibling.value=this.value"></td><td><output>{camera_values.get('saturation', '64')}</output></td></tr>
                <tr><td>Gain</td><td><input name="gain" type="range" min="0" max="100" step="1" value="{camera_values.get('gain', '0')}" oninput="this.nextElementSibling.value=this.value"></td><td><output>{camera_values.get('gain', '0')}</output></td></tr>
                <tr><td>Backlight</td><td><input name="backlight_compensation" type="range" min="0" max="160" step="1" value="{camera_values.get('backlight_compensation', '0')}" oninput="this.nextElementSibling.value=this.value"></td><td><output>{camera_values.get('backlight_compensation', '0')}</output></td></tr>
                <tr><td>Auto Exposure</td><td>
                    <select name="auto_exposure">
                        <option value=""{"" if current_auto not in ("1", "3") else ""}>Keep current</option>
                        <option value="1"{selected_manual}>Manual Mode</option>
                        <option value="3"{selected_auto}>Aperture Priority</option>
                    </select>
                </td><td>menu</td></tr>
                <tr><td>Exposure Time</td><td><input name="exposure_time_absolute" type="range" min="1" max="5000" step="1" value="{camera_values.get('exposure_time_absolute', '157')}" oninput="this.nextElementSibling.value=this.value"></td><td><output>{camera_values.get('exposure_time_absolute', '157')}</output></td></tr>
            </table></div>
            <button type="submit" style="padding: 12px; font-size: 18px; margin-top: 10px;">Apply Camera Settings</button>
        </form>
        """
        autotune = CAMERA_AUTOTUNE_SETTINGS
        autotune_state = CAMERA_AUTOTUNE_STATE
        camera_sliders += f"""
        <form action="/camera/autotune" method="post" style="margin:12px 0;">
            <input type="hidden" name="camera" value="{camera_key}">
            <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
                <tr><th>Auto Tune</th><th>Value</th><th>Notes</th></tr>
                <tr><td>Enabled</td><td><input type="checkbox" name="enabled" value="on" {"checked" if autotune.get('enabled') else ""}></td><td>Measure each successful capture and adjust exposure/gain</td></tr>
                <tr><td>Target Brightness</td><td><input name="target_brightness" type="number" step="0.1" min="0" max="255" value="{autotune.get('target_brightness', 112)}"></td><td>Average grayscale brightness</td></tr>
                <tr><td>Tolerance</td><td><input name="tolerance" type="number" step="0.1" min="1" max="100" value="{autotune.get('tolerance', 14)}"></td><td>Do not adjust inside this band</td></tr>
                <tr><td>Cooldown Seconds</td><td><input name="cooldown_seconds" type="number" step="1" min="0" value="{autotune.get('cooldown_seconds', 4)}"></td><td>Throttle control changes</td></tr>
                <tr><td>Exposure Min</td><td><input name="exposure_min" type="number" step="1" min="1" value="{autotune.get('exposure_min', 4)}"></td><td>Lower bound for exposure time</td></tr>
                <tr><td>Exposure Max</td><td><input name="exposure_max" type="number" step="1" min="1" value="{autotune.get('exposure_max', 2500)}"></td><td>Upper bound for exposure time</td></tr>
                <tr><td>Exposure Up</td><td><input name="exposure_step_up" type="number" step="0.01" min="1" max="2.5" value="{autotune.get('exposure_step_up', 1.25)}"></td><td>How fast to brighten</td></tr>
                <tr><td>Exposure Down</td><td><input name="exposure_step_down" type="number" step="0.01" min="0.3" max="0.99" value="{autotune.get('exposure_step_down', 0.72)}"></td><td>How fast to darken</td></tr>
                <tr><td>Gain Min</td><td><input name="gain_min" type="number" step="1" min="0" value="{autotune.get('gain_min', 0)}"></td><td>Lower bound for gain</td></tr>
                <tr><td>Gain Max</td><td><input name="gain_max" type="number" step="1" min="0" value="{autotune.get('gain_max', 24)}"></td><td>Upper bound for gain</td></tr>
                <tr><td>Gain Step</td><td><input name="gain_step" type="number" step="1" min="1" value="{autotune.get('gain_step', 1)}"></td><td>How much to move gain per step</td></tr>
                <tr><td>Initial Exposure</td><td><input name="initial_exposure" type="number" step="1" min="1" value="{autotune.get('initial_exposure', 80)}"></td><td>Used when enabling assist</td></tr>
                <tr><td>Initial Gain</td><td><input name="initial_gain" type="number" step="1" min="0" value="{autotune.get('initial_gain', 0)}"></td><td>Used when enabling assist</td></tr>
            </table></div>
            <button type="submit" style="padding: 12px; font-size: 18px; margin-top: 10px;">Save Auto Tune</button>
        </form>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th colspan="2">Auto Tune State</th></tr>
            <tr><td>Last Adjust</td><td>{autotune_state.get('last_adjust_at') or 'Never'}</td></tr>
            <tr><td>Last Brightness</td><td>{autotune_state.get('last_brightness') if autotune_state.get('last_brightness') is not None else 'unknown'}</td></tr>
            <tr><td>Last Exposure</td><td>{autotune_state.get('last_exposure') if autotune_state.get('last_exposure') is not None else 'unknown'}</td></tr>
            <tr><td>Last Gain</td><td>{autotune_state.get('last_gain') if autotune_state.get('last_gain') is not None else 'unknown'}</td></tr>
            <tr><td>Last Action</td><td>{autotune_state.get('last_action') or 'idle'}</td></tr>
            <tr><td>Message</td><td>{autotune_state.get('last_message') or ''}</td></tr>
        </table></div>
        """
    elif camera_key == "logitech":
        preset_buttons = f"""
        <form action="/camera/preset" method="post" style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;">
            <input type="hidden" name="camera" value="{camera_key}">
            <button type="submit" name="preset" value="logitech_default" style="padding:10px 14px;">Reset Defaults</button>
        </form>
        """
    return f"""
    <html>
    <head>
        <title>Home Sentinel Live View</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
{RESPONSIVE_STYLE}    </head>
    <body>
        <div class="top-links"><a href="/">Back to Dashboard</a><a href="/network">Network Status</a><a href="/api/events">Events API</a><a href="/videos">Video Clips</a><a href="/live?camera=arducam">Arducam View</a><a href="/live?camera=logitech">Logitech View</a></div>
        <h1>Home Sentinel Live View</h1>
        <h2>Low-frame MJPEG feed</h2>
        <p>This live feed uses repeated camera captures through the same USB camera path as the event pipeline. Keep only one live viewer open while monitoring is active.</p>

        <div class="capture-controls">
        <h3>Capture Controls</h3>
        <form action="/capture_analyze" method="post" style="margin-bottom: 10px;">
            <input type="hidden" name="camera" value="{camera_key}">
            <button type="submit" style="padding: 12px; font-size: 18px;">
                Capture Image + Analyze ({camera_label})
            </button>
        </form>
        <form action="/set_baseline" method="post" style="margin-bottom: 10px;">
            <button type="submit" style="padding: 12px; font-size: 18px;">
                Set / Reset Baseline
            </button>
        </form>
        {preset_buttons}
        {camera_sliders}
        </div>

        <img src="{stream_src}" style="width:100%; max-width:720px; border:1px solid #243048;">

        <hr>
        <p><strong>Active Camera:</strong> {camera_label}</p>
        <p><strong>Device:</strong> {camera_device}</p>
        <p><strong>Expected rate:</strong> about 5 frames per second</p>
    </body>
    </html>
    """


@app.route('/api/network')
def api_network():
    return jsonify(network_snapshot(request.remote_addr))


@app.route('/network')
def network_status():
    s = network_snapshot(request.remote_addr)

    interface_rows = ''.join([
        f"<tr><td>{iface['name']}</td><td>{iface['address']}</td></tr>"
        for iface in s['interfaces']
    ]) or '<tr><td colspan="2">No active IPv4 interfaces detected</td></tr>'

    port_rows = ''.join([
        f'<tr><td><code>{line}</code></td></tr>'
        for line in s['listening_ports']
    ]) or '<tr><td>No SSH/Home Sentinel listening ports detected</td></tr>'

    request_rows = ''.join([
        f"<tr><td>{r['timestamp']}</td><td>{r['method']}</td><td>{r['path']}</td><td>{r['client_ip']}</td><td>{r['status']}</td><td>{r.get('duration_ms', '')}</td></tr>"
        for r in s['recent_requests']
    ]) or '<tr><td colspan="6">No request history yet</td></tr>'

    capture_rows = ''.join([
        f"<tr><td>{c['timestamp']}</td><td>{c['success']}</td><td>{c['seconds']}</td><td>{c.get('message', '')}</td></tr>"
        for c in s['recent_captures']
    ]) or '<tr><td colspan="4">No capture history yet</td></tr>'

    journal_rows = ''.join([f'<tr><td><code>{line}</code></td></tr>' for line in s['journal_tail']]) or '<tr><td>No journal entries</td></tr>'

    request_summary_rows = ''.join([
        f"<tr><td>{item['endpoint']}</td><td>{item['count']}</td></tr>"
        for item in s['request_summary']
    ]) or '<tr><td colspan="2">No endpoint counts yet</td></tr>'

    request_latency_rows = ''.join([
        f"<tr><td>{item['endpoint']}</td><td>{item['count']}</td><td>{item['avg_ms']}</td><td>{item['max_ms']}</td></tr>"
        for item in s['request_latency_summary']
    ]) or '<tr><td colspan="4">No latency samples yet</td></tr>'

    wifi_rows = ''.join([f'<li><code>{line}</code></li>' for line in s['wifi_status']]) or '<li>Wi-Fi status unavailable</li>'

    compute_items = [
        ('Load Average', ' '.join(s['compute_metrics']['loadavg']) if isinstance(s['compute_metrics']['loadavg'], list) else s['compute_metrics']['loadavg']),
        ('CPU Temperature', f"{s['cpu_temp_c']} C"),
        ('Memory Used', f"{s['compute_metrics']['mem_used_percent']}%"),
        ('Memory Available', f"{s['compute_metrics']['mem_available_gb']} GB"),
        ('Memory Total', f"{s['compute_metrics']['mem_total_gb']} GB"),
        ('Disk Used', s['compute_metrics']['disk_used_percent']),
        ('Disk Free', f"{s['compute_metrics']['disk_free_gb']} GB"),
        ('Boot Time', s['compute_metrics']['boot_time']),
    ]

    network_items = [
        ('Hostname', s['hostname']),
        ('LAN IPs', ', '.join(s['lan_ips']) or 'none'),
        ('Tailscale IPs', ', '.join(s['tailscale_ips']) or 'none'),
        ('Default Gateway', s['default_gateway']),
        ('Gateway Ping', s['gateway_ping']),
        ('DNS Lookup', s['dns_lookup']),
        ('Service', s['service_status']),
        ('Restart Count', str(s['service_details']['restart_count'])),
        ('Current Client IP', s['current_client_ip']),
        ('Last Client IP', s['last_recorded_client_ip']),
        ('Stream FPS', str(STREAM_FPS)),
        ('Average Frame Size', f"{s['stream_metrics']['average_frame_bytes']} bytes"),
        ('Estimated Stream Bandwidth', f"{s['stream_metrics']['estimated_mbps']} Mbps"),
        ('Capture Success Rate', f"{s['stream_health']['capture_success_rate']}%"),
        ('Avg Capture Time', f"{s['stream_health']['avg_capture_seconds'] if s['stream_health']['avg_capture_seconds'] is not None else 'unknown'} s"),
        ('Last Capture Time', f"{s['last_capture_seconds'] if s['last_capture_seconds'] is not None else 'unknown'} s"),
    ]

    compute_rows = ''.join([f'<li><span class="metric-label">{k}:</span> {v}</li>' for k, v in compute_items])
    network_rows = ''.join([f'<li><span class="metric-label">{k}:</span> {v}</li>' for k, v in network_items])
    traffic_rows = ''.join([f'<tr><td>{item["interface"]}</td><td>{item["rx_mb"]}</td><td>{item["tx_mb"]}</td></tr>' for item in s['interface_traffic']]) or '<tr><td colspan="3">No interface traffic data</td></tr>'
    client_rows = ''.join([f'<tr><td>{item["client_ip"]}</td><td>{item["count"]}</td></tr>' for item in s['client_history']]) or '<tr><td colspan="2">No clients yet</td></tr>'
    camera_rows = ''.join([f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in [('Success Count', s['camera_health']['success_count']), ('Failure Count', s['camera_health']['failure_count']), ('Last Failure', s['camera_health']['last_failure'])]])

    return f"""
    <html>
    <head>
        <title>Home Sentinel Network and Computer Metrics</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
{RESPONSIVE_STYLE}    </head>
    <body>
        <div class="top-links"><a href="/">Back to Dashboard</a><a href="/live?camera=arducam">Arducam View</a><a href="/live?camera=logitech">Logitech View</a><a href="/api/network">JSON API</a><a href="/live">Live View</a><a href="/videos">Video Clips</a></div>
        <h1>Home Sentinel Network and Computer Metrics</h1>
        <h2>v0.5-network-compute — Compute, Network, and Camera Telemetry</h2>
        <p><strong>Version:</strong> v0.5-network-compute</p>

        <div class="metric-grid">
            <section class="metric-card">
                <h3>Compute</h3>
                <ul class="metric-list">{compute_rows}</ul>
            </section>
            <section class="metric-card">
                <h3>Network + Throughput</h3>
                <ul class="metric-list">{network_rows}</ul>
            </section>
            <section class="metric-card">
                <h3>Camera Load</h3>
                <ul class="metric-list">
                    {''.join([
                        f'<li><span class="metric-label">{item["camera_label"]} CPU:</span> {item["avg_cpu_percent"] if item["avg_cpu_percent"] is not None else "unknown"}%</li>'
                        f'<li><span class="metric-label">{item["camera_label"]} Avg Capture:</span> {item["avg_capture_seconds"] if item["avg_capture_seconds"] is not None else "unknown"} s</li>'
                        f'<li><span class="metric-label">{item["camera_label"]} Samples:</span> {item["samples"]}</li>'
                        for item in s['camera_cpu_summary']
                    ])}
                </ul>
            </section>
        </div>

        <hr>
        <h3>Interface Traffic</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Interface</th><th>RX MB</th><th>TX MB</th></tr>
            {traffic_rows}
        </table></div>

        <hr>
        <h3>Camera Health</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Metric</th><th>Value</th></tr>
            {camera_rows}
        </table></div>

        <hr>
        <h3>Client Access History</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Client IP</th><th>Requests</th></tr>
            {client_rows}
        </table></div>

        <hr>
        <h3>Interfaces</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Interface</th><th>IPv4 Address</th></tr>
            {interface_rows}
        </table></div>

        <hr>
        <h3>Listening Ports</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Socket</th></tr>
            {port_rows}
        </table></div>

        <hr>
        <h3>Request Latency</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Endpoint</th><th>Count</th><th>Avg (ms)</th><th>Max (ms)</th></tr>
            {request_latency_rows}
        </table></div>

        <hr>
        <h3>Recent Requests</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Time</th><th>Method</th><th>Path</th><th>Client</th><th>Status</th><th>ms</th></tr>
            {request_rows}
        </table></div>

        <hr>
        <h3>Endpoint Counts</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Endpoint</th><th>Count</th></tr>
            {request_summary_rows}
        </table></div>

        <hr>
        <h3>Recent Capture Attempts</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Time</th><th>Success</th><th>Seconds</th><th>Message</th></tr>
            {capture_rows}
        </table></div>

        <hr>
        <h3>Journal Tail</h3>
        <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Line</th></tr>
            {journal_rows}
        </table></div>

        <hr>
        <h3>Wi-Fi Status</h3>
        <ul>{wifi_rows}</ul>

        <hr>
        <h3>Network+ Map</h3>
        <ul>
            <li><strong>IP addressing:</strong> {s['network_plus_map']['ip_addressing']}</li>
            <li><strong>Default gateway:</strong> {s['network_plus_map']['default_gateway']}</li>
            <li><strong>Ports:</strong> {s['network_plus_map']['ports']}</li>
            <li><strong>Client/server:</strong> {s['network_plus_map']['client_server']}</li>
            <li><strong>Services:</strong> {s['network_plus_map']['services']}</li>
            <li><strong>Local device:</strong> {s['network_plus_map']['local_device']}</li>
        </ul>
    </body>
    </html>
    """


@app.route("/")
def home():
    init_db()

    uptime_seconds = int(time.time() - start_time)
    recent_events = get_recent_events(20)
    latest = latest_event_with_image()

    latest_raw_html = "<p>No event image captured yet.</p>"
    latest_annotated_html = "<p>No annotated image yet.</p>"
    latest_annotation_html = "<p>No annotation payload yet.</p>"

    latest_event = None
    if latest:
        latest_event_id, raw_image, annotated_image = latest
        latest_event = get_event_detail(latest_event_id)

        if raw_image:
            latest_raw_html = f"""
            <img src="/raw/{raw_image}?t={int(time.time())}"
                 style="width:100%; max-width:640px; border:1px solid #243048;">
            """

        if annotated_image:
            latest_annotated_html = f"""
            <img src="/annotated/{annotated_image}?t={int(time.time())}"
                 style="width:100%; max-width:640px; border:1px solid #243048;">
            """

        if latest_event:
            annotation = latest_event.get('annotation') or {}
            perception = annotation.get('perception') or {}
            ann_detections = annotation.get('detections') or latest_event.get('detections') or []
            ann_rows = ''.join([
                f"<tr><td>{d.get('label', '')}</td><td>{float(d.get('confidence', 0)):.2f}</td><td>{d.get('validator', 'unknown')}</td><td>{d.get('bbox', {})}</td></tr>"
                for d in ann_detections
            ]) or '<tr><td colspan="4">No detections in annotation payload</td></tr>'
            latest_annotation_html = f"""
            <p><strong>Model:</strong> {latest_event.get('annotation_model') or annotation.get('model') or 'unknown'}</p>
            <p><strong>Primary Label:</strong> {perception.get('primary_label') or 'none'}</p>
            <p><strong>Primary Confidence:</strong> {perception.get('primary_confidence', 0):.2f}</p>
            <p><strong>Confidence Validator:</strong> {perception.get('validator') or 'unknown'}</p>
            <p><strong>Day/Night:</strong> {latest_event.get('day_night') or annotation.get('day_night') or 'unknown'}</p>
            <p><strong>Light Level:</strong> {latest_event.get('light_level') if latest_event.get('light_level') is not None else annotation.get('light_level', 'unknown')}</p>
            <p><strong>Clip Status:</strong> {latest_event.get('clip_status') or annotation.get('clip_status') or 'none'}</p>
            <p><strong>Clip Duration:</strong> {latest_event.get('clip_seconds') or annotation.get('clip_seconds') or 'unknown'} s</p>
            <p><a href="/api/events/{latest_event_id}/annotation">Open Annotation JSON</a></p>
            <div class="table-wrap"><table border="1" cellpadding="6" cellspacing="0">
                <tr><th>Label</th><th>Confidence</th><th>Validator</th><th>BBox</th></tr>
                {ann_rows}
            </table></div>
            """

    baseline_html = "<p>No baseline set.</p>"
    if BASELINE_PATH.exists():
        baseline_html = f"""
        <img src="/baseline?t={int(time.time())}"
             style="width:100%; max-width:320px; border:1px solid #243048;">
        """

    event_rows = ""

    for event_id, timestamp, event_type, raw_image, annotated_image, client_ip, notes in recent_events:
        detections = get_detections_for_event(event_id)

        detection_text = ""
        if detections:
            detection_text = ", ".join([f"{label} {confidence:.2f}" for label, confidence in detections])

        raw_link = f"<a href='/raw/{raw_image}'>raw</a>" if raw_image else ""
        annotated_link = f"<a href='/annotated/{annotated_image}'>annotated</a>" if annotated_image else ""

        event_rows += f"""
        <tr>
            <td>{event_id}</td>
            <td>{timestamp}</td>
            <td>{event_type}</td>
            <td>{client_ip or ""}</td>
            <td>{raw_link}</td>
            <td>{annotated_link}</td>
            <td>{detection_text}</td>
            <td>{notes or ""}</td>
        </tr>
        """

    monitoring_status = "ON" if monitor_state["enabled"] else "OFF"
    baseline_status = "SET" if BASELINE_PATH.exists() else "NOT SET"

    return f"""
    <html>
    <head>
        <title>Home Sentinel v0.3-alpha</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
{RESPONSIVE_STYLE}    </head>

    <body>
        <div class="top-links"><a href="/live">Live View</a><a href="/live?camera=arducam">Arducam View</a><a href="/live?camera=logitech">Logitech View</a><a href="/network">Network Status / Network+ Lab</a><a href="/api/events">Events API</a><a href="/annotations">Annotations</a><a href="/videos">Video Clips</a></div>
        <h1>Home Sentinel</h1>
        <h2>v0.4.2-label-validator — Label-First Perception Review</h2>
        <div class="top-links"><a href="/live">Live View</a><a href="/live?camera=arducam">Arducam View</a><a href="/live?camera=logitech">Logitech View</a><a href="/network">Network Status / Network+ Lab</a><a href="/api/events">Events API</a><a href="/annotations">Annotations</a><a href="/videos">Video Clips</a></div>

        <hr>

        <h3>System Status</h3>
        <p><strong>Service:</strong> Online</p>
        <p><strong>Uptime:</strong> {uptime_seconds} seconds</p>
        <p><strong>OpenCV Available:</strong> {OPENCV_AVAILABLE}</p>
        <p><strong>Baseline:</strong> {baseline_status}</p>
        <p><strong>Auto Monitoring:</strong> {monitoring_status}</p>
        <p><strong>Check Interval:</strong> {MONITOR_INTERVAL_SECONDS} seconds</p>
        <p><strong>Diff Trigger:</strong> {MOTION_SETTINGS['diff_percent']}% changed pixels</p>
        <p><strong>Cooldown:</strong> {MOTION_SETTINGS['cooldown_seconds']} seconds</p>
        <p><strong>Last Check:</strong> {monitor_state["last_check"]}</p>
        <p><strong>Last Difference:</strong> {monitor_state["last_diff_percent"]}%</p>
        <p><strong>Last Auto Event:</strong> {monitor_state["last_event"]}</p>
        <p><strong>Last Error:</strong> {monitor_state["last_error"]}</p>

        <hr>

        <h3>Controls</h3>

        <form action="/set_baseline" method="post" style="margin-bottom: 10px;">
            <button type="submit" style="padding: 12px; font-size: 18px;">
                Set / Reset Baseline
            </button>
        </form>

        <form action="/monitor/start" method="post" style="margin-bottom: 10px;">
            <button type="submit" style="padding: 12px; font-size: 18px;">
                Start Auto Monitoring
            </button>
        </form>

        <form action="/monitor/stop" method="post" style="margin-bottom: 10px;">
            <button type="submit" style="padding: 12px; font-size: 18px;">
                Stop Auto Monitoring
            </button>
        </form>

        <form action="/capture_analyze" method="post" style="margin-bottom: 10px;">
            <button type="submit" style="padding: 12px; font-size: 18px;">
                Manual Capture + Analyze
            </button>
        </form>

        <form action="/motion/settings" method="post" style="margin-bottom: 10px;">
            <div class="table-wrap">
                <table border="1" cellpadding="6" cellspacing="0">
                    <tr><th>Setting</th><th>Value</th></tr>
                    <tr><td>Motion Threshold %</td><td><input name="diff_percent" type="number" step="0.1" min="0" max="100" value="{MOTION_SETTINGS['diff_percent']}" /></td></tr>
                    <tr><td>Min Motion Pixels</td><td><input name="min_motion_pixels" type="number" step="1" min="1" value="{MOTION_SETTINGS['min_motion_pixels']}" /></td></tr>
                    <tr><td>Persistence Frames</td><td><input name="persistence_frames" type="number" step="1" min="1" value="{MOTION_SETTINGS['persistence_frames']}" /></td></tr>
                    <tr><td>Cooldown Seconds</td><td><input name="cooldown_seconds" type="number" step="1" min="0" value="{MOTION_SETTINGS['cooldown_seconds']}" /></td></tr>
                    <tr><td>Brightness Delta</td><td><input name="brightness_delta" type="number" step="0.1" min="0" value="{MOTION_SETTINGS['brightness_delta']}" /></td></tr>
                </table>
            </div>
            <button type="submit" style="padding: 12px; font-size: 18px; margin-top: 8px;">
                Save Motion Settings
            </button>
        </form>

        <hr>

        <h3>Baseline Image</h3>
        {baseline_html}

        <h3>Latest Raw Event Image</h3>
        {latest_raw_html}

        <h3>Annotations</h3>
        <p>Open the <a href="/annotations">Annotations tab</a> to view the latest 10 annotated images and annotation JSON.</p>

        <hr>

        <h3>Database Event Log</h3>
        <table border="1" cellpadding="6" cellspacing="0">
            <tr>
                <th>ID</th>
                <th>Timestamp</th>
                <th>Event Type</th>
                <th>Client IP</th>
                <th>Raw</th>
                <th>Annotated</th>
                <th>Detections</th>
                <th>Notes</th>
            </tr>
            {event_rows}
        </table>
    </body>
    </html>
    """


@app.route("/set_baseline", methods=["GET", "POST"])
def set_baseline():
    client_ip = request.remote_addr

    event_id, filename, error = capture_image(
        client_ip=client_ip,
        prefix="baseline",
        event_type="baseline_set",
        notes="Baseline image set/reset"
    )

    if filename:
        shutil.copy2(RAW_DIR / filename, BASELINE_PATH)

    return redirect("/")


@app.route("/monitor/start", methods=["GET", "POST"])
def monitor_start():
    monitor_state["enabled"] = True
    monitor_state["last_error"] = ""
    return redirect("/")


@app.route("/monitor/stop", methods=["GET", "POST"])
def monitor_stop():
    monitor_state["enabled"] = False
    return redirect("/")


@app.route("/capture_analyze", methods=["GET", "POST"])
def capture_analyze():
    client_ip = request.remote_addr
    camera_key = normalize_camera_key((request.form.get("camera") or request.args.get("camera") or DEFAULT_CAMERA_KEY).strip())

    event_id, raw_filename, error = capture_image(
        client_ip=client_ip,
        prefix="manual",
        event_type="manual_capture_analyze",
        notes="Manual capture and analysis",
        camera_key=camera_key
    )

    if event_id and raw_filename:
        motion_metrics, _ = compute_motion_metrics(RAW_DIR / raw_filename)
        analyze_image(event_id, raw_filename, motion_metrics=motion_metrics)
        queue_event_video_capture(event_id, raw_filename, camera_key=camera_key)

    return redirect(f"/live?camera={camera_key}")


@app.route("/raw/<path:filename>")
def raw_image(filename):
    return send_from_directory(RAW_DIR, filename)


@app.route("/annotated/<path:filename>")
def annotated_image(filename):
    return send_from_directory(ANNOTATED_DIR, filename)


@app.route("/clips/<path:filename>")
def clip_video(filename):
    return send_from_directory(CLIPS_DIR, filename)


@app.route("/baseline")
def baseline_image():
    return send_file(BASELINE_PATH, mimetype="image/jpeg")


if __name__ == "__main__":
    init_db()
    start_monitor_thread()
    app.run(host="0.0.0.0", port=5000)
