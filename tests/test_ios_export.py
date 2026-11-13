"""Real production path: concat TS -> trim -> three logos -> CFR -> MP4."""
import ast
import glob
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import traceback
import unittest
from types import SimpleNamespace

import cv2
from replay_branding import build_branding
from replay_timeline import MediaClock, read_segments, select_interval
from replay_thumbnail import validate_video, ensure_thumbnail, valid_thumbnail
import replay_processing as processing

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = str(ROOT / 'ffmpeg.exe') if (ROOT / 'ffmpeg.exe').exists() else shutil.which('ffmpeg')


def trace_fields(output):
    result = subprocess.run([
        FFMPEG, '-hide_banner', '-i', str(output), '-map', '0:v:0', '-c:v', 'copy',
        '-bsf:v', 'trace_headers', '-frames:v', '1', '-f', 'null', '-',
    ], capture_output=True, text=True, check=True)
    return {key: int(value) for key, value in re.findall(
        r'\b(\w+)\s+[01]+\s+=\s+(\d+)', result.stderr)}, result.stderr


@unittest.skipUnless(FFMPEG, 'FFmpeg unavailable')
class IOSExportTests(unittest.TestCase):
    def test_production_sources_and_sps_timing(self):
        tree = ast.parse((ROOT / 'sports_replay_v4.py').read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FFmpegRecorder')
        cls.bases = []
        with tempfile.TemporaryDirectory(prefix='ios_production_') as folder:
            root = Path(folder)
            config = root / 'config'
            config.mkdir()
            logo = str(ROOT / 'assets/branding/vibe.png')
            (config / 'branding.json').write_text(json.dumps(dict(
                vibe_logo=logo, sponsors_left=[logo], sponsors_right=[logo])))
            logs, commands = [], []
            def render(command, settings, log, **kwargs):
                commands.append(command)
                if explicit_timebase is True:
                    # Reconstruct the former graph/encoder contract, using the
                    # same snapshots. Never touch a published replay.
                    old = command.copy()
                    graph_index = old.index('-filter_complex') + 1
                    old[graph_index] = old[graph_index].rsplit(';', 1)[0]
                    old[old.index('-map')+1] = '[base3]'
                    x264 = old.index('-x264-params')
                    del old[x264:x264+2]
                    old = old[:old.index('-pix_fmt')] + [
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
                        '-movflags', '+faststart', str(root / 'before.mp4')]
                    before = subprocess.run(old, capture_output=True, text=True, timeout=60)
                    self.assertEqual(before.returncode, 0, before.stderr)
                    fields, _ = trace_fields(root / 'before.mp4')
                    print('Former production contract: ' + str({key: fields.get(key) for key in
                        ('profile_idc', 'level_idc', 'time_scale', 'num_units_in_tick')}))
                return processing.run_render(command, settings, log, **kwargs)
            api = SimpleNamespace(load_settings=lambda _: processing.ProcessingSettings(encoder='libx264'),
                normalize_video=processing.normalize_video, software_args=processing.software_args,
                compatibility_args=processing.compatibility_args, run_render=render)
            namespace = dict(os=os, time=time, glob=glob, shutil=shutil, math=math,
                tempfile=tempfile, subprocess=subprocess, traceback=traceback,
                pyqtSignal=lambda *args: None, log_error=logs.append,
                get_ffmpeg_path=lambda: FFMPEG, build_branding=build_branding,
                CONFIG_DIR=str(config), REPLAY_VIDEO_FILTER='', SEGMENT_SECONDS=2,
                MediaClock=MediaClock, read_segments=read_segments, select_interval=select_interval,
                validate_video=validate_video, replay_processing=api)
            exec(compile(ast.Module(body=[cls], type_ignores=[]), '<production-recorder>', 'exec'), namespace)
            for fps, explicit_timebase in [(25, False), (30, False), (60, False), (30, True), (30, 'bad_vui')]:
                with self.subTest(fps=fps, timebase_90k=explicit_timebase):
                    source = root / f'source_{fps}_{explicit_timebase}'
                    source.mkdir()
                    index = source / 'segments.csv'
                    subprocess.run([
                        FFMPEG, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        f"nullsrc=s=640x360:r={fps},geq=lum='32+T*10':cb=128:cr=128",
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                        '-t', '6', '-map', '0:v', '-map', '1:a', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-g', str(fps*2), '-bf', '0',
                        *(['-vf', 'settb=expr=1/90000', '-enc_time_base:v', '1:90000',
                           '-fps_mode:v', 'passthrough'] if explicit_timebase else []),
                        *(['-x264-params', 'fps=90000/1'] if explicit_timebase == 'bad_vui' else []),
                        '-c:a', 'aac', '-f', 'segment', '-segment_time', '2', '-reset_timestamps', '1',
                        '-segment_list', str(index), '-segment_list_type', 'csv', str(source / '%03d.ts'),
                    ], check=True, capture_output=True)
                    if explicit_timebase == 'bad_vui':
                        source_fields, _ = trace_fields(source / '000.ts')
                        self.assertEqual(source_fields['time_scale'], 180000)
                        self.assertEqual(source_fields['num_units_in_tick'], 1)
                        print('Adversarial source SPS: ' + str({key: source_fields[key] for key in
                            ('profile_idc', 'level_idc', 'time_scale', 'num_units_in_tick')}))
                    recorder = object.__new__(namespace['FFmpegRecorder'])
                    recorder.buffer_dir, recorder.segment_index, recorder.running = str(source), str(index), True
                    output = source / 'replay.mp4'
                    self.assertTrue(recorder.extract_replay(3, str(output), end_time=4.5), logs)
                    fields, trace = trace_fields(output)
                    for key, expected in dict(profile_idc=66, level_idc=41,
                        num_units_in_tick=1, time_scale=60, fixed_frame_rate_flag=1,
                        frame_mbs_only_flag=1).items():
                        self.assertEqual(fields.get(key), expected, key)
                    self.assertTrue(processing.compatible_h264(FFMPEG, str(output)))
                    self.assertEqual(fields['constraint_set1_flag'], 1)
                    self.assertLessEqual(fields['max_num_ref_frames'], 4)
                    cap = cv2.VideoCapture(str(output))
                    self.assertEqual((cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), (1920, 1080))
                    self.assertAlmostEqual(cap.get(cv2.CAP_PROP_FPS), 30, places=3)
                    self.assertEqual(cap.get(cv2.CAP_PROP_FRAME_COUNT), 90)
                    ok, first = cap.read()
                    self.assertTrue(ok)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 89)
                    ok, last = cap.read()
                    cap.release()
                    self.assertTrue(ok)
                    # Source luma timestamps prove the requested [1.5, 4.5] interval.
                    self.assertAlmostEqual(float(first[100,100].mean()), (32+15-16)*255/219, delta=4)
                    self.assertAlmostEqual(float(last[100,100].mean()), (32+44.67-16)*255/219, delta=4)
                    self.assertLess(first[900:1020,900:1020].min(), first[100,100].mean()-5)
                    self.assertIn('SAR 1:1 DAR 16:9', trace)
                    self.assertIn('yuv420p', trace)
                    self.assertIn('avc1', trace)
                    self.assertRegex(trace, r'Audio: aac \(LC\).*48000 Hz, stereo')
                    boxes = []
                    with output.open('rb') as stream:
                        while header := stream.read(8):
                            size, kind = struct.unpack('>I4s', header)
                            self.assertGreaterEqual(size, 8)
                            boxes.append(kind)
                            stream.seek(size-8, 1)
                    self.assertLess(boxes.index(b'moov'), boxes.index(b'mdat'))
                    decoded = subprocess.run([FFMPEG, '-v', 'error', '-xerror', '-i', str(output),
                        '-f', 'null', '-'], capture_output=True, text=True)
                    self.assertEqual(decoded.returncode, 0, decoded.stderr)
                    self.assertEqual(decoded.stderr, '')
                    timing = subprocess.run([FFMPEG, '-hide_banner', '-i', str(output),
                        '-vf', 'showinfo', '-af', 'ashowinfo', '-f', 'null', '-'], capture_output=True, text=True, check=True)
                    video_pts = [float(v) for v in re.findall(r'Parsed_showinfo_.*?\bn:\s*\d+\s+pts:.*?pts_time:([\d.]+)', timing.stderr)]
                    audio_pts = [float(v) for v in re.findall(r'Parsed_ashowinfo_.*?pts_time:([\d.]+)', timing.stderr)]
                    self.assertEqual(len(video_pts), 90)
                    self.assertIn('time_base: 1/90000', timing.stderr)
                    for n, pts in enumerate(video_pts):
                        self.assertAlmostEqual(pts, n/30, delta=.00001)
                    self.assertAlmostEqual(audio_pts[0], 0, delta=.022)
                    self.assertAlmostEqual(audio_pts[-1], 3, delta=.04)
                    thumbnail = source / 'thumb.jpg'
                    ensure_thumbnail(FFMPEG, str(output), str(thumbnail), duration_seconds=3)
                    self.assertTrue(valid_thumbnail(str(thumbnail)))
                    print(f'Validated production: source={fps}fps/90kHz explicit={explicit_timebase}; 1920x1080 30fps; SPS=60/1 level=41; video=3s AAC=3s; decode/moov/thumbnail OK')
