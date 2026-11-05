import unittest
from button_input import DebouncedButton

class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.button = DebouncedButton(log=self.logs.append)
        self.now = 0.0
        self.clicks = 0
    def state(self, level, duration):
        self.clicks += self.button.update(level, self.now)
        for _ in range(round(duration * 1000)):
            self.now = round(self.now + .001, 6)
            self.clicks += self.button.update(level, self.now)
    def arm(self): self.state(0, .06)
    def test_short_pulse(self):
        self.arm(); self.state(1, .049); self.state(0, .1)
        self.assertEqual(self.clicks, 0)
        self.assertTrue(any('pulso descartado' in line for line in self.logs))
    def test_stable_press_before_release(self):
        self.arm(); self.state(1, .05)
        self.assertEqual(self.clicks, 1)
    def test_hold_and_duplicate_pressed_reports(self):
        self.arm(); self.state(1, 10)
        self.assertEqual(self.clicks, 1)
        self.assertLess(len(self.logs), 6)
    def test_press_bounce(self):
        self.arm()
        for _ in range(4): self.state(1, .01); self.state(0, .01)
        self.state(1, .1)
        self.assertEqual(self.clicks, 1)
    def test_release_bounce_and_new_press(self):
        self.arm(); self.state(1, .1)
        for _ in range(4): self.state(0, .02); self.state(1, .02)
        self.assertEqual(self.clicks, 1)
        self.state(0, .06); self.state(1, .06)
        self.assertEqual(self.clicks, 2)
    def test_initially_pressed(self):
        self.state(1, 5)
        self.assertEqual(self.clicks, 0)
        self.state(0, .06); self.state(1, .06)
        self.assertEqual(self.clicks, 1)
    def test_startup_requires_full_stable_release(self):
        self.state(0, .02); self.state(1, .1)
        self.assertEqual(self.clicks, 0)
    def test_reconnect_requires_stable_release(self):
        self.arm(); self.state(1, .1)
        self.button = DebouncedButton()
        self.state(1, 1)
        self.assertEqual(self.clicks, 1)
        self.state(0, .06); self.state(1, .06)
        self.assertEqual(self.clicks, 2)
    def test_inverted_level(self):
        self.button = DebouncedButton(pressed_level=0)
        self.state(1, .06); self.state(0, .06)
        self.assertEqual(self.clicks, 1)
    def test_configurable_debounce(self):
        self.button = DebouncedButton(debounce_seconds=.1)
        self.state(0, .11); self.state(1, .06); self.state(0, .11)
        self.assertEqual(self.clicks, 0)
        self.state(1, .11)
        self.assertEqual(self.clicks, 1)
    def test_logs_rate_limited(self):
        self.arm()
        for _ in range(100): self.state(1, .005); self.state(0, .005)
        self.assertEqual(self.clicks, 0)
        self.assertLessEqual(len(self.logs), 4)

if __name__ == '__main__': unittest.main()
