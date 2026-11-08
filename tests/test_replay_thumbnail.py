from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from replay_thumbnail import ensure_thumbnail, valid_thumbnail


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = str(ROOT / 'ffmpeg.exe') if (ROOT / 'ffmpeg.exe').exists() else shutil.which('ffmpeg')


@unittest.skipUnless(FFMPEG, 'FFmpeg unavailable')
class ThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='thumbnail_test_')
        cls.root = Path(cls.workspace.name)
        cls.video = cls.root / 'short replay.mp4'
        subprocess.run([
            FFMPEG, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
            'testsrc2=s=320x180:r=10', '-t', '0.6', '-c:v', 'libx264',
            '-preset', 'ultrafast', str(cls.video),
        ], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.folder.cleanup)
        self.destination = Path(self.folder.name) / 'thumb.jpg'

    def test_reproduces_old_seek_without_output(self):
        result = subprocess.run([
            FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-ss', '15',
            '-i', str(self.video), '-frames:v', '1', '-vf', 'scale=640:-2',
            '-q:v', '3', str(self.destination),
        ], capture_output=True)
        self.assertFalse(valid_thumbnail(self.destination))

    def test_short_video_falls_back_to_first_frame(self):
        messages = []
        result = ensure_thumbnail(FFMPEG, self.video, self.destination, 30, log=messages.append)
        self.assertEqual(result, str(self.destination))
        self.assertTrue(valid_thumbnail(result))
        self.assertTrue(any('0s:' in message for message in messages))
        self.assertEqual(list(self.destination.parent.glob('thumbnail_*')), [])

    def test_corrupt_cached_jpeg_is_replaced(self):
        self.destination.write_bytes(b'incomplete JPEG')
        ensure_thumbnail(FFMPEG, self.video, self.destination, 0)
        self.assertTrue(valid_thumbnail(self.destination))

    def test_valid_cached_jpeg_is_reused(self):
        ensure_thumbnail(FFMPEG, self.video, self.destination, 0)
        before = self.destination.stat().st_mtime_ns
        ensure_thumbnail('nonexistent-ffmpeg', self.video, self.destination)
        self.assertEqual(before, self.destination.stat().st_mtime_ns)

    def test_invalid_duration(self):
        ensure_thumbnail(FFMPEG, self.video, self.destination, 'invalid')
        self.assertTrue(valid_thumbnail(self.destination))

    def test_invalid_video_keeps_source_and_cleans_temporary_files(self):
        source = self.destination.parent / 'invalid.mp4'
        source.write_bytes(b'invalid video')
        with self.assertRaisesRegex(RuntimeError, 'Falha ao extrair thumbnail'):
            ensure_thumbnail(FFMPEG, source, self.destination)
        self.assertEqual(source.read_bytes(), b'invalid video')
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.glob('thumbnail_*')), [])

    def test_missing_video(self):
        with self.assertRaisesRegex(RuntimeError, 'Video ausente'):
            ensure_thumbnail(FFMPEG, 'missing.mp4', self.destination)
