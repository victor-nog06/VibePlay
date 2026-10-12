import sys
import os
import cv2
import time
import json
import collections
import pygame
import threading
import subprocess
import re
import shutil
import glob
import math
import tempfile
import traceback
import faulthandler
import requests
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QLineEdit, QListWidget, QFrame, 
    QGraphicsDropShadowEffect, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer, QSize
from PyQt6.QtGui import QImage, QPixmap, QColor, QFont

# Performance settings for RTSP and OpenCV
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
os.environ["OPENCV_LOG_LEVEL"] = "OFF"

def get_app_dir():
    """Returns the absolute directory of the script or the frozen executable."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_ffmpeg_path():
    """Returns the FFmpeg path on Windows or Linux."""
    executable_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        ffmpeg_bundle = os.path.join(sys._MEIPASS, executable_name)
        if os.path.exists(ffmpeg_bundle):
            return ffmpeg_bundle

    app_dir = get_app_dir()
    ffmpeg_local = os.path.join(app_dir, executable_name)
    if os.path.exists(ffmpeg_local):
        return ffmpeg_local

    # Uses FFmpeg installed through apt/dnf/pacman or available in PATH.
    return shutil.which("ffmpeg") or "ffmpeg"

def sanitize_folder_name(name):
    """Sanitizes court name for filesystem safety."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return clean if clean else "Quadra_Geral"

# --- SETTINGS ---
APP_DIR = get_app_dir()
BASE_REPLAYS_DIR = os.path.join(APP_DIR, "replays")
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
PENDING_DIR = os.path.join(UPLOAD_DIR, "pendentes")
TEMP_DIR = os.path.join(APP_DIR, "temp")
CONFIG_DIR = os.path.join(APP_DIR, "config")
LOG_DIR = os.path.join(APP_DIR, "logs")
AUTH_DIR = os.path.join(APP_DIR, "auth")
CONFIG_FILE = os.path.join(CONFIG_DIR, "vibe_config.json")
UPLOAD_CONFIG_FILE = os.path.join(CONFIG_DIR, "supabase_upload.json")
QUEUE_FILE = os.path.join(UPLOAD_DIR, "vibe_upload_queue.json")
SEGMENT_SECONDS = 5
SEGMENT_COUNT = 16  # Mantém aproximadamente 80 segundos em buffer circular.

# Ensure base folders exist
for folder in [BASE_REPLAYS_DIR, UPLOAD_DIR, PENDING_DIR, TEMP_DIR, CONFIG_DIR, LOG_DIR, AUTH_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

CRASH_LOG_FILE = os.path.join(LOG_DIR, "vibe_crash_log.txt")
try:
    _crash_log_handle = open(CRASH_LOG_FILE, "a", encoding="utf-8", buffering=1)
    faulthandler.enable(_crash_log_handle, all_threads=True)
except Exception:
    _crash_log_handle = None

def get_court_dir(court_name):
    """Gets or creates folder specific to a court."""
    clean_name = sanitize_folder_name(court_name)
    court_path = os.path.join(BASE_REPLAYS_DIR, clean_name)
    if not os.path.exists(court_path):
        os.makedirs(court_path)
    return court_path, clean_name

def log_error(msg):
    """Logs errors to a file for diagnostics."""
    log_path = os.path.join(LOG_DIR, "vibe_erro_log.txt")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] {msg}\n")
    except Exception:
        pass

class FFmpegRecorder(QObject):
    """Background thread that keeps a continuous recording with audio via FFmpeg."""
    status_msg = pyqtSignal(str, str)

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.process = None
        self.running = False
        self.segment_pattern = os.path.join(TEMP_DIR, "live_buffer_%03d.ts")
        self.started_at = None

    def start_recording(self):
        self.running = True
        self.started_at = time.monotonic()
        for old_segment in glob.glob(os.path.join(TEMP_DIR, "live_buffer_*.ts")):
            try:
                os.remove(old_segment)
            except OSError:
                pass
        threading.Thread(target=self._run_ffmpeg, daemon=True).start()

    def stop_recording(self):
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _run_ffmpeg(self):
        cmd = [
            get_ffmpeg_path(), '-y', '-rtsp_transport', 'tcp',
            '-i', self.url,
            '-map', '0:v:0', '-map', '0:a?', '-c', 'copy',
            '-f', 'segment',
            '-segment_time', str(SEGMENT_SECONDS),
            '-segment_wrap', str(SEGMENT_COUNT),
            '-reset_timestamps', '1',
            '-segment_format', 'mpegts',
            self.segment_pattern
        ]
        
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.process = subprocess.Popen(
                cmd,
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = self.process.communicate()
            if self.running and self.process.returncode != 0:
                log_error(f"FFmpeg stopped ({self.process.returncode}): {stderr[-2000:]}")
                self.status_msg.emit("Erro FFmpeg / Câmera", "#ef4444")
        except Exception as e:
            log_error(f"FFmpeg Recorder Error: {str(e)}")
            self.status_msg.emit("Erro FFmpeg (Audio)", "#ef4444")

    def extract_replay(self, seconds, output_path):
        """Creates an exact-duration replay from the circular segment buffer."""
        if not self.started_at or time.monotonic() - self.started_at < seconds:
            log_error(f"Replay requested before {seconds}s of buffer were available")
            return False

        try:
            segments = sorted(
                glob.glob(os.path.join(TEMP_DIR, "live_buffer_*.ts")),
                key=os.path.getmtime
            )
            needed = math.ceil(seconds / SEGMENT_SECONDS) + 2
            segments = segments[-needed:]
            if not segments:
                return False

            snapshot_dir = tempfile.mkdtemp(prefix="replay_", dir=TEMP_DIR)
            concat_file = os.path.join(snapshot_dir, "segments.txt")
            snapshot_segments = []
            for index, segment in enumerate(segments):
                snapshot = os.path.join(snapshot_dir, f"segment_{index:03d}.ts")
                shutil.copy2(segment, snapshot)
                snapshot_segments.append(snapshot)

            with open(concat_file, "w", encoding="utf-8") as file_list:
                for segment in snapshot_segments:
                    safe_path = segment.replace("'", "'\\''")
                    file_list.write(f"file '{safe_path}'\n")

            cmd = [
                get_ffmpeg_path(), '-y',
                '-sseof', f'-{seconds}',
                '-f', 'concat', '-safe', '0', '-i', concat_file,
                '-t', str(seconds),
                '-map', '0:v:0', '-map', '0:a?',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                output_path
            ]

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            proc = subprocess.run(
                cmd,
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )
            if proc.returncode != 0:
                log_error(f"Replay extraction FFmpeg error ({proc.returncode}): {proc.stderr[-2000:]}")
                return False
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            log_error(f"Replay extraction error: {traceback.format_exc()}")
            return False
        finally:
            if 'snapshot_dir' in locals():
                shutil.rmtree(snapshot_dir, ignore_errors=True)

class CameraWorker(QObject):
    """Live Preview thread using OpenCV (Video only for UI)."""
    frame_changed = pyqtSignal(QImage)
    status_changed = pyqtSignal(str, str)
    finished = pyqtSignal()

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.running = True

    def _safe_emit(self, signal_name, *args):
        """Emite um sinal de forma segura prevenindo erro caso o objeto tenha sido deletado."""
        try:
            from PyQt6.sip import isdeleted
            if not isdeleted(self):
                signal = getattr(self, signal_name)
                signal.emit(*args)
        except Exception:
            pass

    def run(self):
        try:
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                self._safe_emit("status_changed", "Câmera Offline", "#ef4444")
                self._safe_emit("finished")
                return

            self._safe_emit("status_changed", "Vibe Online", "#22c55e")

            while self.running:
                try:
                    from PyQt6.sip import isdeleted
                    if isdeleted(self):
                        break
                except Exception:
                    break

                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue
                
                frame_resized = cv2.resize(frame, (854, 480))
                rgb_image = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                qt_img = QImage(rgb_image.data, w, h, ch * w, QImage.Format.Format_RGB888)
                self._safe_emit("frame_changed", qt_img.copy())

            cap.release()
        except Exception as e:
            log_error(f"UI Preview Error: {str(e)}")
        self._safe_emit("finished")

class SupabaseUploader(QObject):
    """Uploads replays through the authenticated backend into Supabase."""
    status_signal = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.queue_file = QUEUE_FILE
        self.is_processing = False
        self.lock = threading.Lock()

        # Background retry timer (checks queue every 15 seconds)
        self.retry_timer = QTimer()
        self.retry_timer.timeout.connect(self.process_queue)
        self.retry_timer.start(15000)

        # On startup, index any unqueued local files across all court directories
        QTimer.singleShot(2000, self._scan_local_unuploaded)

    def _load_upload_config(self):
        try:
            with open(UPLOAD_CONFIG_FILE, 'r', encoding='utf-8') as config_file:
                config = json.load(config_file)
            backend_url = str(config.get('backend_url', '')).rstrip('/')
            device_token = str(config.get('device_token', '')).strip()
            arena_id = str(config.get('arena_id', '')).strip()
            if not backend_url or len(device_token) < 40 or not arena_id:
                return None
            return {"backend_url": backend_url, "device_token": device_token, "arena_id": arena_id}
        except Exception:
            return None

    def _court_metadata_for_path(self, file_path):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as config_file:
                courts = json.load(config_file)
            folder_name = os.path.basename(os.path.dirname(file_path))
            court = next((item for item in courts if sanitize_folder_name(item.get('name', '')) == folder_name), None)
            if not court or not court.get('court_id'):
                return None
            duration_match = re.search(r'_(30|60)s_', os.path.basename(file_path))
            return {
                "court_id": court['court_id'],
                "duration_seconds": int(duration_match.group(1)) if duration_match else 30,
            }
        except Exception:
            return None

    def _load_queue(self):
        with self.lock:
            if os.path.exists(self.queue_file):
                try:
                    with open(self.queue_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    return []
            return []

    def _save_queue(self, queue):
        with self.lock:
            try:
                with open(self.queue_file, 'w', encoding='utf-8') as f:
                    json.dump(queue, f, indent=2, ensure_ascii=False)
            except Exception as e:
                log_error(f"Error saving upload queue: {e}")

    def add_to_queue(self, file_path, court_id, duration_seconds, replay_timestamp=None):
        """Adds a video file to the persistent upload queue."""
        queue = self._load_queue()
        if not any(item['file_path'] == file_path for item in queue):
            queue.append({
                "file_path": file_path,
                "court_id": court_id,
                "duration_seconds": duration_seconds,
                "replay_timestamp": replay_timestamp or datetime.now().astimezone().isoformat(),
                "added_at": datetime.now().isoformat(),
                "status": "pending",
                "retries": 0,
                "last_error": ""
            })
            self._save_queue(queue)
            log_error(f"File queued for upload: {file_path}")
        
        self.process_queue()

    def _scan_local_unuploaded(self):
        """Scans all court subdirectories for files that were generated previously but not completed."""
        try:
            queue = self._load_queue()
            known_files = {item['file_path']: item for item in queue}
            
            changed = False
            for root_dir in [BASE_REPLAYS_DIR, PENDING_DIR]:
                if not os.path.exists(root_dir): continue
                for root, _, files in os.walk(root_dir):
                    for fname in files:
                        if fname.endswith(".mp4"):
                            fpath = os.path.join(root, fname)
                            if fpath not in known_files:
                                metadata = self._court_metadata_for_path(fpath)
                                if not metadata:
                                    log_error(f"Replay sem court_id, upload ignorado: {fpath}")
                                    continue
                                queue.append({
                                    "file_path": fpath,
                                    "court_id": metadata["court_id"],
                                    "duration_seconds": metadata["duration_seconds"],
                                    "replay_timestamp": datetime.fromtimestamp(os.path.getmtime(fpath)).astimezone().isoformat(),
                                    "added_at": datetime.now().isoformat(),
                                    "status": "pending",
                                    "retries": 0,
                                    "last_error": "Recovered on startup"
                                })
                                changed = True
            
            if changed:
                self._save_queue(queue)
                self.process_queue()
        except Exception as e:
            log_error(f"Local scan error: {e}")

    def process_queue(self):
        """Processes all pending files in the upload queue asynchronously."""
        if self.is_processing:
            return
        
        queue = self._load_queue()
        pending = [item for item in queue if item.get('status') != 'completed']
        
        if not pending:
            return

        threading.Thread(target=self._worker_process_queue, daemon=True).start()

    def _worker_process_queue(self):
        if self.is_processing:
            return
        self.is_processing = True

        try:
            upload_config = self._load_upload_config()
            if not upload_config:
                self.status_signal.emit("Configure config/supabase_upload.json", "#fbbf24")
                return

            queue = self._load_queue()
            pending_items = [item for item in queue if item.get('status') != 'completed']
            
            total_pending = len(pending_items)
            for idx, item in enumerate(pending_items, 1):
                file_path = item['file_path']
                
                if not os.path.exists(file_path):
                    item['status'] = 'completed'
                    item['last_error'] = 'Arquivo não encontrado'
                    self._save_queue(queue)
                    continue

                self.status_signal.emit(f"Enviando ({idx}/{total_pending})...", "#3b82f6")

                try:
                    if not item.get('court_id'):
                        metadata = self._court_metadata_for_path(file_path)
                        if metadata:
                            item.update(metadata)
                    if not item.get('court_id'):
                        raise ValueError('court_id ausente na configuração da quadra')

                    endpoint = f"{upload_config['backend_url']}/api/replay-control/device/upload"
                    with open(file_path, 'rb') as video_file:
                        response = requests.post(
                            endpoint,
                            headers={"Authorization": f"Bearer {upload_config['device_token']}"},
                            data={
                                "arena_id": upload_config['arena_id'],
                                "court_id": item['court_id'],
                                "duration_seconds": str(item.get('duration_seconds', 30)),
                                "replay_timestamp": item.get('replay_timestamp') or datetime.now().astimezone().isoformat(),
                            },
                            files={"video": (os.path.basename(file_path), video_file, "video/mp4")},
                            timeout=(15, 300),
                        )
                    if response.status_code not in (200, 201):
                        try:
                            error_message = response.json().get('error', response.text)
                        except Exception:
                            error_message = response.text
                        raise RuntimeError(f"HTTP {response.status_code}: {error_message[:500]}")

                    item['status'] = 'completed'
                    item['completed_at'] = datetime.now().isoformat()
                    self._save_queue(queue)
                    self.status_signal.emit(f"Supabase: OK ({idx}/{total_pending})", "#22c55e")
                except Exception as e:
                    err_msg = str(e)
                    log_error(f"Upload failure ({file_path}): {err_msg}")
                    item['status'] = 'failed'
                    item['retries'] = item.get('retries', 0) + 1
                    item['last_error'] = err_msg
                    self._save_queue(queue)

                    queue_current = self._load_queue()
                    rem_count = len([i for i in queue_current if i.get('status') != 'completed'])
                    self.status_signal.emit(f"Sem Conexão - {rem_count} Vídeo(s) Salvo(s) Localmente", "#fbbf24")
                    break

        except Exception as global_err:
            log_error(f"Worker queue exception: {global_err}")
        finally:
            self.is_processing = False

class ArcadeInput(QObject):
    """Monitors Arcade USB board / Joystick buttons and handles click counting reliably."""
    trigger = pyqtSignal(int)
    hw_status = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.joystick = None
        self.click_count = 0
        
        self.click_timer = QTimer()
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self._check_clicks)
        
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll)
        self.last_reconnect_attempt = 0

    def start(self):
        try:
            if "SDL_VIDEODRIVER" not in os.environ:
                os.environ["SDL_VIDEODRIVER"] = "dummy"
            if "SDL_AUDIODRIVER" not in os.environ:
                os.environ["SDL_AUDIODRIVER"] = "dummy"

            try:
                pygame.init()
            except Exception as e:
                log_error(f"Pygame init warning: {e}")
                pygame.joystick.init()
            
            self._try_connect_joystick()
            self.poll_timer.start(50)
            return self.joystick is not None
        except Exception as e:
            log_error(f"ArcadeInput start failed: {e}")
            return False

    def _try_connect_joystick(self):
        try:
            pygame.joystick.init()
            count = pygame.joystick.get_count()
            if count > 0:
                self.joystick = pygame.joystick.Joystick(0)
                self.joystick.init()
                self.hw_status.emit("ARCADE: CONECTADO", "#22c55e")
                return True
            else:
                self.joystick = None
                self.hw_status.emit("ARCADE: OFF", "#ef4444")
                return False
        except Exception as e:
            log_error(f"Joystick connect error: {e}")
            return False

    def _poll(self):
        now = time.time()
        if not self.joystick and (now - self.last_reconnect_attempt > 3):
            self.last_reconnect_attempt = now
            self._try_connect_joystick()

        if not self.joystick:
            return

        try:
            pygame.event.pump()
            for event in pygame.event.get():
                if event.type in (pygame.JOYBUTTONDOWN, pygame.KEYDOWN):
                    self.click_count += 1
                    self.click_timer.stop()
                    self.click_timer.start(350)
        except Exception as e:
            log_error(f"Poll error: {e}")

    def _check_clicks(self):
        if self.click_count == 1:
            self.trigger.emit(30)
        elif self.click_count >= 2:
            self.trigger.emit(60)
        self.click_count = 0

class App(QMainWindow):
    thread_status = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VIBE REPLAY PRO - Vibe Group")
        self.setMinimumSize(1100, 850)
        self.setStyleSheet("""
            QMainWindow { background-color: #05080f; }
            QFrame#SideBar { background-color: #0d121f; border-right: 1px solid #1e293b; }
            QLabel { color: #f1f5f9; font-family: 'Segoe UI', sans-serif; }
            QLineEdit { background-color: #1e293b; border: 1px solid #334155; color: white; padding: 10px; border-radius: 6px; }
            QPushButton { background-color: #2563eb; color: white; border-radius: 8px; padding: 12px; font-weight: bold; border: none; }
            QPushButton:hover { background-color: #3b82f6; }
            QListWidget { background-color: transparent; border: none; color: #94a3b8; }
            QListWidget::item { background-color: #161e2e; margin-bottom: 8px; padding: 12px; border-radius: 8px; }
            QListWidget::item:selected { background-color: #2563eb; color: white; }
            QTextEdit { background-color: #0a0e17; color: #64748b; border-radius: 8px; font-family: 'Consolas'; font-size: 11px; }
        """)

        self.courts = self._load()
        self.current_court = None
        self.camera_thread = None
        self.worker = None
        self.recorder = None
        self.uploader = SupabaseUploader()
        self.arcade = ArcadeInput()

        self._init_ui()
        self._init_arcade()
        self.thread_status.connect(self._set_status)
        self.uploader.status_signal.connect(self._set_status)

    def _init_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        layout = QHBoxLayout(central); layout.setContentsMargins(0,0,0,0)

        # Sidebar
        sidebar = QFrame(); sidebar.setObjectName("SideBar"); sidebar.setFixedWidth(320)
        side_layout = QVBoxLayout(sidebar); side_layout.setContentsMargins(20,30,20,20)
        
        logo = QLabel("VIBE REPLAY"); logo.setStyleSheet("font-size: 26px; font-weight: 900; color: #3b82f6; letter-spacing: 1px;")
        side_layout.addWidget(logo)
        side_layout.addWidget(QLabel("BY VIBE GROUP")); side_layout.addSpacing(20)
        
        self.name_in = QLineEdit(); self.name_in.setPlaceholderText("Identificação da Quadra")
        self.url_in = QLineEdit(); self.url_in.setPlaceholderText("URL RTSP")
        self.court_id_in = QLineEdit(); self.court_id_in.setPlaceholderText("ID da Quadra no sistema")
        side_layout.addWidget(self.name_in); side_layout.addWidget(self.url_in); side_layout.addWidget(self.court_id_in)
        
        btn_add = QPushButton("CADASTRAR QUADRA"); btn_add.clicked.connect(self._add)
        side_layout.addWidget(btn_add)
        
        side_layout.addSpacing(20); self.list_w = QListWidget()
        self.list_w.itemClicked.connect(self._select)
        side_layout.addWidget(self.list_w)
        
        btn_del = QPushButton("REMOVER QUADRA"); btn_del.setStyleSheet("background-color: #1e293b; color: #64748b;")
        btn_del.clicked.connect(self._del)
        side_layout.addWidget(btn_del)
        
        self._refresh(); side_layout.addStretch(); layout.addWidget(sidebar)

        # Main Area
        main_v = QVBoxLayout(); main_v.setContentsMargins(30,30,30,30)
        self.display = QLabel("VIBE STANDBY"); self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setStyleSheet("background-color: #000; border-radius: 15px; border: 1px solid #1e293b;")
        main_v.addWidget(self.display, 8)

        status_h = QHBoxLayout()
        self.status_tag = QLabel("SISTEMA PRONTO")
        self.status_tag.setStyleSheet("background-color: #1e293b; padding: 8px 15px; border-radius: 10px; font-weight: bold;")
        status_h.addWidget(self.status_tag)
        
        self.hw_tag = QLabel("ARCADE: OFF"); self.hw_tag.setStyleSheet("color: #ef4444; font-weight: bold;")
        status_h.addStretch(); status_h.addWidget(self.hw_tag)
        main_v.addLayout(status_h)

        self.log_area = QTextEdit(); self.log_area.setReadOnly(True); self.log_area.setFixedHeight(120)
        main_v.addWidget(self.log_area)

        btns = QHBoxLayout()
        b30 = QPushButton("REPLAY 30s (AUDIO)"); b30.clicked.connect(lambda: self._trigger(30)); b30.setStyleSheet("background-color: #059669; height: 50px;")
        b60 = QPushButton("REPLAY 60s (AUDIO)"); b60.clicked.connect(lambda: self._trigger(60)); b60.setStyleSheet("background-color: #7c3aed; height: 50px;")
        btns.addWidget(b30); btns.addWidget(b60); main_v.addLayout(btns)
        layout.addLayout(main_v)

    def _init_arcade(self):
        self.arcade.hw_status.connect(self._update_hw_status)
        self.arcade.trigger.connect(self._trigger)
        self.arcade.start()

    def _update_hw_status(self, text, color):
        self.hw_tag.setText(text)
        self.hw_tag.setStyleSheet(f"color: {color}; font-weight: bold;")

    def keyPressEvent(self, event):
        """Keyboard fallback for Arcade / USB Keypads (Space = 30s, Enter/Return = 60s)."""
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_1):
            self._trigger(30)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_2):
            self._trigger(60)
        else:
            super().keyPressEvent(event)

    def _select(self, item):
        court = next(c for c in self.courts if c["name"] == item.text())
        self.current_court = court
        
        # Stop previous tasks
        if self.recorder:
            self.recorder.stop_recording()
        if self.camera_thread and self.camera_thread.isRunning():
            self.worker.running = False
            try:
                self.worker.frame_changed.disconnect()
                self.worker.status_changed.disconnect()
                self.worker.finished.disconnect()
            except Exception:
                pass
            self.camera_thread.quit()
            
            if not hasattr(self, 'old_threads'):
                self.old_threads = []
            self.old_threads.append((self.camera_thread, self.worker))
        
        # Start FFmpeg recording (Audio + Video)
        self.recorder = FFmpegRecorder(court["url"])
        self.recorder.status_msg.connect(self._set_status)
        self.recorder.start_recording()

        # Start OpenCV Preview
        self.camera_thread = QThread()
        self.worker = CameraWorker(court["url"])
        self.worker.moveToThread(self.camera_thread)
        self.camera_thread.started.connect(self.worker.run)
        self.worker.frame_changed.connect(lambda img: self.display.setPixmap(QPixmap.fromImage(img)))
        self.worker.status_changed.connect(self._set_status)
        self.worker.finished.connect(self.camera_thread.quit)
        self.camera_thread.start()

    def _trigger(self, sec):
        if not self.recorder or not self.current_court:
            self._set_status("Câmera / Quadra Não Selecionada", "#ef4444")
            return
            
        court_name = self.current_court["name"]
        court_id = self.current_court.get("court_id", "")
        if not court_id:
            self._set_status("Cadastre novamente a quadra com o ID do sistema", "#ef4444")
            return
        court_dir, clean_court_name = get_court_dir(court_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        output_filename = f"REPLAY_{clean_court_name}_{sec}s_{timestamp}.mp4"
        output_path = os.path.join(court_dir, output_filename)
        
        def _process():
            self.thread_status.emit(f"[{court_name}] Cortando {sec}s com Áudio...", "#fbbf24")
            success = self.recorder.extract_replay(sec, output_path)
            
            if success:
                self.thread_status.emit(f"[{court_name}] Replay de {sec}s Gerado!", "#22c55e")
                self.uploader.add_to_queue(
                    output_path,
                    court_id,
                    sec,
                    datetime.now().astimezone().isoformat(),
                )
            else:
                self.thread_status.emit(f"[{court_name}] Buffer insuficiente ou erro no corte", "#ef4444")
        
        threading.Thread(target=_process, daemon=True).start()

    def _set_status(self, text, color):
        self.status_tag.setText(text.upper())
        self.status_tag.setStyleSheet(f"background-color: {color}; padding: 8px 15px; border-radius: 10px; color: white;")
        self.log_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

    def _add(self):
        n, u, court_id = self.name_in.text().strip(), self.url_in.text().strip(), self.court_id_in.text().strip()
        if n and u and court_id:
            self.courts.append({"name": n, "url": u, "court_id": court_id})
            self._save()
            self._refresh()
        else:
            self._set_status("Preencha nome, URL RTSP e ID da quadra", "#ef4444")
    def _del(self):
        it = self.list_w.currentItem()
        if it:
            deleted_court = it.text()
            self.courts = [c for c in self.courts if c["name"] != deleted_court]
            if self.current_court and self.current_court.get("name") == deleted_court:
                self.current_court = None
            self._save(); self._refresh()
    def _refresh(self):
        self.list_w.clear()
        for c in self.courts: self.list_w.addItem(c["name"])
    def _load(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return []
    def _save(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.courts, f)

if __name__ == "__main__":
    def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
        details = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        log_error(f"Unhandled exception:\n{details}")
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_uncaught_exception

    try:
        app = QApplication(sys.argv)
        window = App()
        window.show()
        sys.exit(app.exec())
    except Exception:
        log_error(f"Fatal startup error:\n{traceback.format_exc()}")
        raise
