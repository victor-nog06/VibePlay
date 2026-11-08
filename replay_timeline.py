"""Select a fixed replay interval independently of rendering delay or file mtimes."""
import csv
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import threading


class MediaClock:
    def __init__(self):
        self.samples = deque(maxlen=200)
        self.lock = threading.Lock()

    def record(self, media_seconds, monotonic_seconds):
        with self.lock:
            if media_seconds >= 0:
                self.samples.append((monotonic_seconds, media_seconds))

    def at(self, clicked_at):
        with self.lock:
            samples = list(self.samples)
        earlier = [sample for sample in samples if sample[0] <= clicked_at]
        if not earlier:
            raise ValueError('Sem referencia de video anterior ao clique')
        observed_at, media_seconds = earlier[-1]
        if clicked_at - observed_at > 1:
            raise ValueError('Camera sem progresso recente no instante do clique')
        return media_seconds + clicked_at - observed_at


@dataclass(frozen=True)
class Segment:
    path: Path
    start: float
    end: float


def read_segments(index_file):
    index_file = Path(index_file)
    with index_file.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.reader(stream))
    result = []
    for row in rows:
        if len(row) != 3:
            continue
        path = Path(row[0])
        if not path.is_absolute():
            path = index_file.parent / path
        result.append(Segment(path, float(row[1]), float(row[2])))
    return sorted(result, key=lambda segment: segment.start)


def select_interval(segments, end, seconds):
    start = end - seconds
    if start < 0:
        raise ValueError('Buffer anterior ao clique insuficiente')
    selected = [segment for segment in segments if segment.end > start and segment.start < end]
    if not selected or selected[0].start > start + .001 or selected[-1].end < end:
        raise ValueError('Intervalo do clique ainda indisponivel ou fora do buffer')
    for previous, following in zip(selected, selected[1:]):
        if abs(following.start - previous.end) > .1:
            raise ValueError('Descontinuidade no buffer da camera')
    return selected, start - selected[0].start
