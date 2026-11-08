"""Extract one valid JPEG, including replays shorter than their queued duration."""
import math
import os
from pathlib import Path
import subprocess
import tempfile

import cv2


class InvalidReplayError(RuntimeError):
    """A damaged MP4 must be retained locally and excluded from automatic retry."""


def validate_video(ffmpeg, video_path):
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    result = subprocess.run([
        str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-threads', '1', '-i', str(video_path), '-map', '0:v:0',
        '-frames:v', '1', '-an', '-sn', '-threads', '1', '-f', 'null', '-',
    ], startupinfo=startupinfo, capture_output=True, text=True, timeout=60)
    if result.returncode:
        if 'moov atom not found' in result.stderr.lower():
            raise InvalidReplayError(f'MP4 incompleto ou danificado (moov atom ausente): {video_path}')
        raise RuntimeError(f'Falha ao validar video: {result.stderr[-1500:]}')


def valid_thumbnail(path):
    path = Path(path)
    return path.is_file() and path.stat().st_size > 0 and cv2.imread(str(path)) is not None


def ensure_thumbnail(ffmpeg, video_path, thumbnail_path, duration_seconds=30, log=None):
    log = log or (lambda message: None)
    if valid_thumbnail(thumbnail_path):
        return str(thumbnail_path)
    if not Path(video_path).is_file():
        raise RuntimeError(f'Video ausente para extrair thumbnail: {video_path}')
    try:
        duration = float(duration_seconds)
        seek = duration / 2 if math.isfinite(duration) and duration > 0 else 0
    except (TypeError, ValueError):
        seek = 0
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    destination = Path(thumbnail_path)
    fd, temporary = tempfile.mkstemp(prefix='thumbnail_', suffix='.jpg', dir=destination.parent)
    os.close(fd)
    errors = []
    try:
        for position in dict.fromkeys((seek, 0)):
            command = [
                str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                '-threads', '1', '-filter_threads', '1', '-ss', str(position),
                '-i', str(video_path), '-map', '0:v:0', '-an', '-sn',
                '-frames:v', '1', '-vf', 'scale=640:-2', '-c:v', 'mjpeg',
                '-threads', '1', '-q:v', '3', '-f', 'image2', '-update', '1', temporary,
            ]
            Path(temporary).write_bytes(b'')
            try:
                result = subprocess.run(
                    command, startupinfo=startupinfo, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, text=True, timeout=60,
                )
                if result.returncode == 0 and valid_thumbnail(temporary):
                    os.replace(temporary, destination)
                    log(f'Thumbnail gerada no instante {position:g}s: {destination}')
                    return str(destination)
                detail = result.stderr[-1500:].strip() or 'FFmpeg nao produziu um quadro JPEG valido'
                if 'moov atom not found' in detail.lower():
                    raise InvalidReplayError(f'MP4 incompleto ou danificado (moov atom ausente): {video_path}')
            except subprocess.TimeoutExpired:
                detail = 'FFmpeg excedeu 60s ao extrair o quadro'
            errors.append(f'{position:g}s: {detail}')
            log(f'Tentativa de thumbnail descartada: {errors[-1]}')
        raise RuntimeError('Falha ao extrair thumbnail: ' + ' | '.join(errors))
    finally:
        Path(temporary).unlink(missing_ok=True)
