from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import cv2
from replay_processing import ProcessingSettings, software_args, compatibility_args


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = str(ROOT / 'ffmpeg.exe') if (ROOT / 'ffmpeg.exe').exists() else shutil.which('ffmpeg')


@unittest.skipUnless(FFMPEG, 'FFmpeg unavailable')
class IOSExportTests(unittest.TestCase):
    def test_mp4_codec_profile_level_faststart_and_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            for height, fps in [(720, 60), (1080, 2)]:
                with self.subTest(height=height, source_fps=fps):
                    settings = ProcessingSettings(height=height)
                    output = str(Path(folder) / f'{height}.mp4')
                    result = subprocess.run([
                        FFMPEG, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        f'color=c=gray:s={settings.width}x{height}:r={fps}',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=8000',
                        '-t', '1', *software_args(settings), *compatibility_args(settings), output,
                    ], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    boxes, moov = [], b''
                    with open(output, 'rb') as stream:
                        while True:
                            header = stream.read(8)
                            if not header:
                                break
                            size, kind = struct.unpack('>I4s', header)
                            self.assertGreaterEqual(size, 8)
                            boxes.append(kind)
                            data = stream.read(size - 8)
                            if kind == b'moov':
                                moov = data
                    self.assertLess(boxes.index(b'moov'), boxes.index(b'mdat'))
                    self.assertIn(b'avc1', moov)
                    avcc = moov.index(b'avcC')
                    self.assertEqual(moov[avcc + 5], 66)  # H.264 Baseline profile_idc
                    self.assertEqual(moov[avcc + 7], 31 if height == 720 else 41)
                    cap = cv2.VideoCapture(output)
                    self.assertAlmostEqual(cap.get(cv2.CAP_PROP_FPS), min(fps, 30), delta=.1)
                    self.assertAlmostEqual(cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS), 1, delta=.1)
                    cap.release()
                    decoded = subprocess.run([FFMPEG, '-hide_banner', '-i', output, '-f', 'null', '-'], capture_output=True, text=True)
                    self.assertEqual(decoded.returncode, 0)
                    self.assertIn('yuv420p', decoded.stderr)
                    self.assertRegex(decoded.stderr, r'Audio: aac \(LC\).*48000 Hz, stereo')
