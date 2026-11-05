"""Exercise the production input state machine without USB, Qt or cameras."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class ArcadeTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'sports_replay_v4.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ArcadeInput')
        cls.bases = []
        cls.body = [n for n in cls.body if not isinstance(n, ast.FunctionDef) or n.name != '__init__']
        self.now = 0
        self.buttons = [False, False]
        self.logs = []
        namespace = dict(
            time=SimpleNamespace(time=lambda: self.now, monotonic=lambda: self.now),
            pygame=SimpleNamespace(event=SimpleNamespace(pump=lambda: None, get=lambda: [])),
            pyqtSignal=lambda *args: None, log_error=self.logs.append,
        )
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), 'exec'), namespace)
        self.input = namespace['ArcadeInput']()
        self.input.joystick = SimpleNamespace(
            get_init=lambda: True, get_numbuttons=lambda: len(self.buttons),
            get_button=lambda i: self.buttons[i],
        )
        for name in ('button_states', 'button_candidates', 'pending_clicks', 'press_started', 'blocked_buttons'):
            setattr(self.input, name, {})
        self.input.learning = False
        self.input.trigger = Signal()
        self.input.button_captured = Signal()
        self.input._report_hardware = lambda *args: self.fail(str(args))
        self.input._reset_button_states()

    def advance(self, seconds):
        for _ in range(round(seconds * 100)):
            self.now = round(self.now + .01, 6)
            self.input._poll()

    def click(self, button=0):
        self.buttons[button] = True
        self.advance(.08)
        self.buttons[button] = False
        self.advance(.08)

    def test_idle_does_not_cut(self):
        self.advance(10)
        self.assertEqual(self.input.trigger.values, [])

    def test_hold_does_not_cut(self):
        self.buttons[0] = True
        self.advance(10)
        self.assertEqual(self.input.trigger.values, [])
        self.buttons[0] = False
        self.advance(1)
        self.assertEqual(self.input.trigger.values, [])

    def test_single_click(self):
        self.click()
        self.advance(1)
        self.assertEqual(self.input.trigger.values, [(0, 30)])

    def test_double_click(self):
        self.click()
        self.click()
        self.advance(1)
        self.assertEqual(self.input.trigger.values, [(0, 60)])

    def test_continuous_pulses_are_blocked_and_recover(self):
        for _ in range(30):
            self.click()
        self.assertEqual(self.input.trigger.values, [])
        self.advance(1.1)
        self.click()
        self.click()
        self.advance(1)
        self.assertEqual(self.input.trigger.values, [(0, 60)])

    def test_short_noise_does_not_cut(self):
        for _ in range(100):
            self.buttons[0] = not self.buttons[0]
            self.advance(.02)
        self.buttons[0] = False
        self.advance(1)
        self.assertEqual(self.input.trigger.values, [])

    def test_initially_closed_contact_is_ignored(self):
        self.buttons[0] = True
        self.input._reset_button_states()
        self.advance(1)
        self.buttons[0] = False
        self.advance(1)
        self.assertEqual(self.input.trigger.values, [])

    def test_capture_does_not_cut(self):
        self.input.learn_button()
        self.click()
        self.advance(1)
        self.assertEqual(self.input.button_captured.values, [(0,)])
        self.assertEqual(self.input.trigger.values, [])

    def test_courts_are_independent(self):
        self.click(0)
        self.click(1)
        self.click(1)
        self.advance(1)
        self.assertEqual(self.input.trigger.values, [(0, 30), (1, 60)])


if __name__ == '__main__':
    unittest.main()
