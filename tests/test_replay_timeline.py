import tempfile
from pathlib import Path
import unittest

from replay_timeline import MediaClock, Segment, read_segments, select_interval


class TimelineTests(unittest.TestCase):
    def segments(self):
        return [Segment(Path(f'{i}.ts'), i, i + 5) for i in range(0, 80, 5)]

    def test_thirty_seconds_before_click_not_buffer_end(self):
        segments, seek = select_interval(self.segments(), 37, 30)
        self.assertEqual(segments[0].start, 5)
        self.assertEqual(segments[-1].end, 40)
        self.assertEqual(seek, 2)

    def test_sixty_seconds(self):
        segments, seek = select_interval(self.segments(), 67.5, 60)
        self.assertEqual(segments[0].start, 5)
        self.assertEqual(segments[-1].end, 70)
        self.assertEqual(seek, 2.5)

    def test_exact_boundary_excludes_next_segment(self):
        segments, _ = select_interval(self.segments(), 40, 30)
        self.assertEqual(segments[-1].end, 40)

    def test_unclosed_segment_does_not_fall_back_to_earlier_video(self):
        with self.assertRaises(ValueError):
            select_interval(self.segments()[:7], 37, 30)

    def test_overwritten_buffer_fails(self):
        with self.assertRaises(ValueError):
            select_interval(self.segments()[4:], 37, 30)

    def test_gap_fails(self):
        with self.assertRaises(ValueError):
            select_interval([s for s in self.segments() if s.start != 20], 37, 30)

    def test_media_clock_ignores_camera_connection_delay(self):
        clock = MediaClock()
        clock.record(35, 200)
        self.assertAlmostEqual(clock.at(200.2), 35.2)
        frozen = clock.at(200.2)
        clock.record(50, 215)
        self.assertAlmostEqual(frozen, 35.2)
        self.assertAlmostEqual(clock.at(200.2), 35.2)

    def test_stalled_camera_fails(self):
        clock = MediaClock()
        clock.record(35, 200)
        with self.assertRaises(ValueError):
            clock.at(205)

    def test_csv_preserves_timestamps_after_ring_wrap(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'segments.csv'
            path.write_text('live_buffer_015.ts,75,80\nlive_buffer_000.ts,80,85\n')
            segments = read_segments(path)
            self.assertEqual([(s.start, s.end) for s in segments], [(75, 80), (80, 85)])


if __name__ == '__main__':
    unittest.main()
