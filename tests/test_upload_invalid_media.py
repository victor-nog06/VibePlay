import ast
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from replay_thumbnail import InvalidReplayError


class InvalidMediaQueueTests(unittest.TestCase):
    def test_bad_video_is_preserved_and_next_video_uploads(self):
        path = Path(__file__).resolve().parents[1] / 'sports_replay_v4.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SupabaseUploader')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_worker_process_queue')
        with tempfile.TemporaryDirectory() as folder:
            bad, good = Path(folder) / 'bad.mp4', Path(folder) / 'good.mp4'
            bad.write_bytes(b'broken'); good.write_bytes(b'fixture')
            queue = [dict(file_path=str(p), court_id='court', replay_timestamp='2026-11-08', status='pending') for p in (bad, good)]
            uploaded = []
            def validate(ffmpeg, video):
                if video == str(bad):
                    raise InvalidReplayError('moov atom ausente')
            def post(url, **kwargs):
                if url.endswith('/authorize'):
                    return SimpleNamespace(status_code=200, json=lambda: dict(storage_path='good.mp4', signed_url='https://storage/video'))
                return SimpleNamespace(status_code=200)
            def complete(items, item):
                item['status'] = 'completed'
                uploaded.append(item['file_path'])
                return True
            ns = dict(os=os, validate_video=validate, get_ffmpeg_path=lambda: 'ffmpeg',
                      InvalidReplayError=InvalidReplayError, log_error=lambda msg: None,
                      requests=SimpleNamespace(post=post, put=lambda *args, **kwargs: SimpleNamespace(status_code=200)))
            exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), ns)
            worker = SimpleNamespace(is_processing=False, _load_upload_config=lambda: dict(backend_url='https://backend', device_token='test', arena_id='arena'),
                                     _load_queue=lambda: queue, _save_queue=lambda q: None,
                                     _delete_confirmed_file=complete,
                                     status_signal=SimpleNamespace(emit=lambda *args: None))
            ns['_worker_process_queue'](worker)
            self.assertEqual(queue[0]['status'], 'invalid_media')
            self.assertEqual(bad.read_bytes(), b'broken')
            self.assertEqual(uploaded, [str(good)])
            self.assertFalse(worker.is_processing)
            # A subsequent retry excludes the broken item rather than looping on it.
            ns['_worker_process_queue'](worker)
            self.assertEqual(uploaded, [str(good)])
