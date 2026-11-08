"""Render actual time-coded segments and verify which frames were exported."""
import ast
import glob
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import traceback
import unittest

from replay_branding import build_branding
from replay_timeline import MediaClock, read_segments, select_interval
from replay_thumbnail import validate_video

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = str(ROOT / 'ffmpeg.exe') if (ROOT / 'ffmpeg.exe').exists() else shutil.which('ffmpeg')


@unittest.skipUnless(FFMPEG, 'FFmpeg unavailable')
class ReplayVideoIntervalTests(unittest.TestCase):
    def test_actual_thirty_and_sixty_second_windows(self):
        import cv2
        tree = ast.parse((ROOT / 'sports_replay_v4.py').read_text(encoding='utf-8-sig'))
        video_filter = ast.literal_eval(next(
            node.value for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'REPLAY_VIDEO_FILTER' for target in node.targets)
        ))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FFmpegRecorder')
        cls.bases = []
        with tempfile.TemporaryDirectory(prefix='replay_interval_') as folder:
            root = Path(folder)
            index = root / 'segments.csv'
            # At 2 fps, each frame's luma increases by 1: image content encodes time.
            subprocess.run([
                FFMPEG, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                "nullsrc=s=320x180:r=2,geq=lum='16+N':cb=128:cr=128",
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                '-t', '75', '-map', '0:v', '-map', '1:a', '-c:v', 'libx264',
                '-preset', 'ultrafast', '-g', '10', '-bf', '0', '-c:a', 'aac',
                '-f', 'segment', '-segment_time', '5', '-reset_timestamps', '1',
                '-segment_list', str(index), '-segment_list_type', 'csv',
                str(root / 'live_buffer_%03d.ts'),
            ], check=True, capture_output=True)
            logs = []
            namespace = dict(
                os=os, time=time, glob=glob, shutil=shutil, math=math,
                tempfile=tempfile, subprocess=subprocess, traceback=traceback,
                pyqtSignal=lambda *args: None, log_error=logs.append,
                get_ffmpeg_path=lambda: FFMPEG, build_branding=build_branding,
                CONFIG_DIR=str(ROOT / 'config'), REPLAY_VIDEO_FILTER=video_filter,
                SEGMENT_SECONDS=5, MediaClock=MediaClock,
                read_segments=read_segments, select_interval=select_interval,
                validate_video=validate_video,
            )
            exec(compile(ast.Module(body=[cls], type_ignores=[]), '<recorder>', 'exec'), namespace)
            recorder = object.__new__(namespace['FFmpegRecorder'])
            recorder.buffer_dir, recorder.segment_index, recorder.running = folder, str(index), True
            for seconds, end in [(30, 37), (60, 67)]:
                with self.subTest(seconds=seconds):
                    output = str(root / f'replay_{seconds}.mp4')
                    self.assertTrue(recorder.extract_replay(seconds, output, end_time=end), logs)
                    cap = cv2.VideoCapture(output)
                    fps, frames = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    self.assertAlmostEqual(frames / fps, seconds, delta=.1)
                    ok, first = cap.read()
                    self.assertTrue(ok)
                    self.assertEqual(first.shape[:2], (1080, 1920))
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frames - 1)
                    ok, last = cap.read()
                    cap.release()
                    self.assertTrue(ok)
                    # Account for MPEG/encoder range conversion and one source frame.
                    self.assertAlmostEqual(float(first[200, 200].mean()), (end-seconds)*2*255/219, delta=4)
                    self.assertAlmostEqual(float(last[200, 200].mean()), (end-.5)*2*255/219, delta=4)
                    decoded = subprocess.run([
                        FFMPEG, '-hide_banner', '-i', output, '-f', 'null', '-'
                    ], capture_output=True, text=True)
                    self.assertEqual(decoded.returncode, 0)
                    self.assertIn('Audio: aac', decoded.stderr)
