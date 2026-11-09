import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import replay_processing as processing


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        processing._failed_hardware.clear()

    def test_default_keeps_full_hd(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(processing, 'is_arm_linux', return_value=False):
            settings = processing.load_settings(folder)
            self.assertEqual((settings.width, settings.height), (1920, 1080))
            self.assertEqual(settings.parallel, 1)

    def test_raspberry_defaults_to_720p_and_allows_1080p(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(processing, 'is_arm_linux', return_value=True):
            self.assertEqual(processing.load_settings(folder).height, 720)
            (Path(folder) / 'replay_processing.json').write_text(json.dumps(dict(height=1080)))
            self.assertEqual(processing.load_settings(folder).height, 1080)

    def test_optional_720p_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'replay_processing.json'
            config.write_text(json.dumps(dict(height=720)))
            self.assertEqual(processing.load_settings(folder).width, 1280)
            config.write_text(json.dumps(dict(parallel=0)))
            with self.assertRaises(ValueError):
                processing.load_settings(folder)

    def command(self):
        settings = processing.ProcessingSettings()
        return ['ffmpeg', '-y', *processing.software_args(settings), *processing.compatibility_args(settings), 'output.mp4']

    def test_hardware_failure_falls_back_and_is_not_retried(self):
        commands = []
        def run(cmd, **kwargs):
            commands.append(cmd)
            return SimpleNamespace(returncode=1 if 'h264_v4l2m2m' in cmd else 0, stderr='driver unavailable')
        settings = processing.ProcessingSettings(encoder='h264_v4l2m2m')
        with patch.object(processing, 'hardware_works', return_value=True), patch.object(processing.subprocess, 'run', side_effect=run):
            self.assertEqual(processing.run_render(self.command(), settings, lambda msg: None).returncode, 0)
            self.assertEqual(processing.run_render(self.command(), settings, lambda msg: None).returncode, 0)
        self.assertEqual(len(commands), 3)
        self.assertIn('h264_v4l2m2m', commands[0])
        self.assertNotIn('-preset', commands[0])
        self.assertEqual(commands[0][commands[0].index('-profile:v') + 1], 'baseline')
        self.assertEqual(commands[0][commands[0].index('-tag:v') + 1], 'avc1')
        self.assertIn('libx264', commands[1])
        self.assertIn('libx264', commands[2])

    def test_only_one_render_runs_at_a_time(self):
        lock = threading.Lock()
        active, peak = [0], [0]
        def run(cmd, **kwargs):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(.03)
            with lock:
                active[0] -= 1
            return SimpleNamespace(returncode=0)
        settings = processing.ProcessingSettings(encoder='libx264')
        with patch.object(processing.subprocess, 'run', side_effect=run):
            workers = [threading.Thread(target=processing.run_render, args=(self.command(), settings, lambda msg: None)) for _ in range(3)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
        self.assertEqual(peak[0], 1)
