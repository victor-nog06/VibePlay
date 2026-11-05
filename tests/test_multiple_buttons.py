"""Test the actual joystick adapter and court routing without cameras or Qt."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from button_input import DebouncedButton


SOURCE = Path(__file__).resolve().parents[1] / 'sports_replay_v4.py'


class MultipleButtonTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
        cls = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == 'ArcadeInput')
        cls.bases = []
        cls.body = [n for n in cls.body if not isinstance(n, ast.FunctionDef) or n.name != '__init__']
        self.now = 0
        self.levels = [0, 0, 0]
        namespace = dict(
            DebouncedButton=DebouncedButton, time=SimpleNamespace(monotonic=lambda: self.now),
            pygame=SimpleNamespace(event=SimpleNamespace(pump=lambda: None)),
            pyqtSignal=lambda *args: None, log_error=lambda message: None,
        )
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        self.input = namespace['ArcadeInput']()
        self.input.joystick = SimpleNamespace(get_numbuttons=lambda: 3, get_button=lambda i: self.levels[i])
        self.input.button_states = {}
        self.input.debounce_seconds, self.input.pressed_level = .05, 1
        self.input.learning, self.input.capture_excluded_buttons = False, set()
        self.calls, self.captures = [], []
        self.input.trigger = SimpleNamespace(emit=lambda *args: self.calls.append(args))
        self.input.button_captured = SimpleNamespace(emit=lambda *args: self.captures.append(args))
        self.input._reset_button_states()
        self.sample([0, 0, 0], .06)

    def sample(self, levels, at):
        self.levels, self.now = levels, at
        self.input._read_button_edges()

    def test_simultaneous_buttons(self):
        self.sample([1, 1, 1], .1)
        self.sample([1, 1, 1], .16)
        self.sample([1, 1, 1], 5)
        self.assertEqual(self.calls, [(0, 30), (1, 30), (2, 30)])

    def test_one_held_does_not_block_another(self):
        self.sample([1, 0, 0], .1)
        self.sample([1, 0, 0], .16)
        self.sample([1, 1, 0], .2)
        self.sample([1, 1, 0], .26)
        self.sample([1, 0, 0], .3)
        self.sample([1, 0, 0], .36)
        self.sample([1, 1, 0], .4)
        self.sample([1, 1, 0], .46)
        self.assertEqual(self.calls, [(0, 30), (1, 30), (1, 30)])

    def test_noise_is_isolated(self):
        self.sample([1, 1, 0], .1)
        self.sample([0, 1, 0], .12)
        self.sample([1, 1, 0], .14)
        self.sample([0, 1, 0], .16)
        self.assertEqual(self.calls, [(1, 30)])

    def test_capture_skips_other_court_button(self):
        self.input.learn_button(excluded_buttons=[0])
        self.sample([0, 0, 0], .12)
        self.sample([1, 0, 0], .2)
        self.sample([1, 0, 0], .26)
        self.assertTrue(self.input.learning)
        self.assertEqual(self.captures, [])
        self.sample([1, 1, 0], .3)
        self.sample([1, 1, 0], .36)
        self.assertEqual(self.captures, [(1,)])
        self.assertEqual(self.calls, [])

    def test_routes_to_assigned_court_and_duration(self):
        cls = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_trigger_button')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        courts = [dict(name='A', button_index=0, replay_seconds=30), dict(name='B', button_index=1, replay_seconds=60)]
        routed, statuses = [], []
        app = SimpleNamespace(courts=courts, current_court=courts[0],
                              _trigger=lambda seconds, court, **kw: routed.append((seconds, court)),
                              _set_status=lambda *args: statuses.append(args))
        route = namespace['_trigger_button']
        route(app, 1, 30)
        route(app, 0, 30)
        route(app, 2, 30)
        self.assertEqual(routed, [(60, courts[1]), (30, courts[0])])
        self.assertEqual(len(statuses), 1)


if __name__ == '__main__':
    unittest.main()
