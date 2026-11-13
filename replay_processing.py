"""Bound replay resource usage and use working Raspberry H.264 hardware when available."""
from dataclasses import dataclass
from functools import lru_cache
import json
import sys
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import threading
import time


@dataclass(frozen=True)
class ProcessingSettings:
    height: int = 1080
    threads: int = 0
    parallel: int = 1
    encoder: str = 'auto'
    filter_threads: int = 0

    def __post_init__(self):
        if self.height != 1080:
            raise ValueError('Replay requer Full HD 1920x1080')

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
        # Migrate the previous local 720p setting: new exports must be Full HD.
        height=1080, threads=int(values.get('threads', 0)),
        parallel=int(values.get('parallel', 1)), encoder=values.get('encoder', 'auto'),
        filter_threads=int(values.get('filter_threads', 0)),
    )
    if not 0 <= settings.threads <= 8 or not 1 <= settings.parallel <= 4:
        raise ValueError('Replay: threads 0..8 (0=auto), parallel 1..4')
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
        with tempfile.TemporaryDirectory(prefix='replay_encoder_') as folder:
            output = str(Path(folder) / 'probe.mp4')
            graph, video = normalize_video('[0:v]setsar=1[probe]', '[probe]')
            result = subprocess.run([
                ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                '-f', 'lavfi', '-i', f'color=s={width}x{height}:r=25',
                '-filter_complex', graph, '-map', video, '-t', '0.1',
                '-c:v', 'h264_v4l2m2m', '-b:v', '6000k',
                *compatibility_args(ProcessingSettings()), output,
            ], capture_output=True, timeout=10)
            return result.returncode == 0 and compatible_h264(ffmpeg, output)
    except (OSError, subprocess.TimeoutExpired):
        return False


def compatible_h264(ffmpeg, output):
    """Do not trust drivers that accept but ignore profile/level/timing options."""
    try:
        result = subprocess.run([
            ffmpeg, '-hide_banner', '-loglevel', 'info', '-i', output,
            '-map', '0:v:0', '-c:v', 'copy', '-bsf:v', 'trace_headers',
            '-frames:v', '1', '-f', 'null', '-',
        ], capture_output=True, text=True, timeout=15)
        expected = dict(profile_idc=66, level_idc=41, num_units_in_tick=1,
                        time_scale=60, fixed_frame_rate_flag=1, frame_mbs_only_flag=1,
                        pic_width_in_mbs_minus1=119, pic_height_in_map_units_minus1=67,
                        frame_crop_bottom_offset=4)
        references = re.search(r'\bmax_num_ref_frames\s+[01]+\s+=\s+(\d+)', result.stderr)
        return result.returncode == 0 and references is not None and int(references[1]) <= 4 and all(
            (match := re.search(r'\b' + key + r'\s+[01]+\s+=\s+(\d+)', result.stderr))
            and int(match[1]) == value for key, value in expected.items()
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def software_args(settings):
    return ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-x264-params', 'force-cfr=1', '-threads', str(settings.threads)]


def normalize_video(graph, video):
    # Overlay framesync can restore a 90 kHz input timebase. Normalize AFTER
    # every overlay, not just before it. fps resamples without changing speed;
    # settb/setpts give the encoder integer CFR timestamps in units of 1/30 s.
    return graph + f';{video}fps=fps=30:start_time=0:round=near,' + 'settb=expr=1/30,setpts=N[replay_cfr]', '[replay_cfr]'


def compatibility_args(settings):
    # Keep these AFTER -pix_fmt so hardware fallback retains the same MP4 contract.
    rate = '8000k'
    buffer = '16000k'
    return [
        '-pix_fmt', 'yuv420p', '-profile:v', 'baseline',
        '-level:v', '41', '-tag:v', 'avc1',
        '-r:v', '30', '-fps_mode:v', 'cfr', '-enc_time_base:v', '1:30',
        '-maxrate', rate, '-bufsize', buffer,
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
            hardware = command[:start] + ['-c:v', 'h264_v4l2m2m', '-b:v', '6000k'] + command[end:]
            began = time.monotonic()
            log('Codificacao: h264_v4l2m2m (hardware)')
            result = subprocess.run(hardware, **kwargs)
            log(f'Codificacao por hardware: {time.monotonic()-began:.2f}s')
            if result.returncode == 0 and compatible_h264(command[0], command[-1]):
                return result
            _failed_hardware.add(hardware_key)
            log(f'Hardware falhou ou SPS incompativel; repetindo o mesmo trecho por software: {result.stderr[-1000:]}')
        began = time.monotonic()
        log(f'Codificacao: libx264 ultrafast, threads={settings.threads}, resolucao={settings.width}x{settings.height}')
        result = subprocess.run(command, **kwargs)
        log(f'Codificacao por software: {time.monotonic()-began:.2f}s')
        return result
