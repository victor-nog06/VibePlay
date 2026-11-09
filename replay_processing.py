"""Bound replay resource usage and use working Raspberry H.264 hardware when available."""
from dataclasses import dataclass
from functools import lru_cache
import json
import sys
from pathlib import Path
import platform
import subprocess
import threading
import time


@dataclass(frozen=True)
class ProcessingSettings:
    height: int = 1080
    threads: int = 0
    parallel: int = 1
    encoder: str = 'auto'
    filter_threads: int = 0

    @property
    def width(self):
        return self.height * 16 // 9

    @property
    def video_filter(self):
        return (
            "crop=w='min(iw,ih*16/9)':h='min(ih,iw*9/16)',"
            f'scale={self.width}:{self.height}:flags=fast_bilinear,setsar=1'
        )


def load_settings(config_dir):
    path = Path(config_dir) / 'replay_processing.json'
    values = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    settings = ProcessingSettings(
        height=int(values.get('height', 720 if is_arm_linux() else 1080)), threads=int(values.get('threads', 0)),
        parallel=int(values.get('parallel', 1)), encoder=values.get('encoder', 'auto'),
        filter_threads=int(values.get('filter_threads', 0)),
    )
    if settings.height not in (720, 1080) or not 0 <= settings.threads <= 8 or not 1 <= settings.parallel <= 4:
        raise ValueError('Replay: height deve ser 720/1080, threads 0..8 (0=auto), parallel 1..4')
    if settings.encoder not in ('auto', 'libx264', 'h264_v4l2m2m'):
        raise ValueError('Replay: encoder deve ser auto, libx264 ou h264_v4l2m2m')
    if not 0 <= settings.filter_threads <= 8:
        raise ValueError('Replay: filter_threads deve ser 0..8 (0=auto)')
    return settings


def is_arm_linux():
    return sys.platform.startswith('linux') and platform.machine().lower().startswith(('arm', 'aarch64'))


_slots = {}
_slot_lock = threading.Lock()
_failed_hardware = set()


@lru_cache(maxsize=8)
def hardware_works(ffmpeg, width, height):
    try:
        result = subprocess.run([
            ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-f', 'lavfi', '-i', f'color=s={width}x{height}:r=25',
            '-frames:v', '1', '-c:v', 'h264_v4l2m2m', '-b:v', '4000k',
            '-pix_fmt', 'yuv420p', '-profile:v', 'baseline',
            '-level:v', '41' if height == 1080 else '31',
            '-f', 'null', '-',
        ], capture_output=True, timeout=10)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def software_args(settings):
    return ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-threads', str(settings.threads)]


def compatibility_args(settings):
    # Keep these AFTER -pix_fmt so hardware fallback retains the same MP4 contract.
    rate = '8000k' if settings.height == 1080 else '4000k'
    buffer = '16000k' if settings.height == 1080 else '8000k'
    return [
        '-pix_fmt', 'yuv420p', '-profile:v', 'baseline',
        '-level:v', '41' if settings.height == 1080 else '31', '-tag:v', 'avc1',
        '-fpsmax', '30', '-maxrate', rate, '-bufsize', buffer,
        '-metadata:s:v:0', 'rotate=0',
        '-c:a', 'aac', '-profile:a', 'aac_low', '-b:a', '128k', '-ar', '48000', '-ac', '2',
        '-movflags', '+faststart', '-video_track_timescale', '90000',
    ]


def run_render(command, settings, log, **kwargs):
    # Called only AFTER snapshots were copied, so waiting cannot shift the click.
    with _slot_lock:
        gate = _slots.setdefault(settings.parallel, threading.BoundedSemaphore(settings.parallel))
    waiting = time.monotonic()
    with gate:
        log(f'Fila de renderizacao: espera={time.monotonic()-waiting:.2f}s')
        arm_linux = is_arm_linux()
        hardware_key = (command[0], settings.width, settings.height)
        use_hardware = (
            settings.encoder != 'libx264' and (arm_linux or settings.encoder == 'h264_v4l2m2m')
            and hardware_key not in _failed_hardware and hardware_works(*hardware_key)
        )
        if use_hardware:
            start, end = command.index('-c:v'), command.index('-pix_fmt')
            hardware = command[:start] + ['-c:v', 'h264_v4l2m2m', '-b:v', '6000k' if settings.height == 1080 else '4000k'] + command[end:]
            began = time.monotonic()
            log('Codificacao: h264_v4l2m2m (hardware)')
            result = subprocess.run(hardware, **kwargs)
            log(f'Codificacao por hardware: {time.monotonic()-began:.2f}s')
            if result.returncode == 0:
                return result
            _failed_hardware.add(hardware_key)
            log(f'Hardware falhou; repetindo o mesmo trecho por software: {result.stderr[-1000:]}')
        began = time.monotonic()
        log(f'Codificacao: libx264 ultrafast, threads={settings.threads}, resolucao={settings.width}x{settings.height}')
        result = subprocess.run(command, **kwargs)
        log(f'Codificacao por software: {time.monotonic()-began:.2f}s')
        return result
