"""Debounce of logical input states, independent of USB, Qt and recording."""
class DebouncedButton:
    def __init__(self, debounce_seconds=0.05, pressed_level=1, log=None):
        if debounce_seconds <= 0 or pressed_level not in (0, 1):
            raise ValueError('Invalid debounce or pressed level')
        self.debounce_seconds = debounce_seconds
        self.pressed_level = pressed_level
        self.log = log or (lambda message: None)
        self.raw = None
        self.since = None
        self.stable = None
        self.armed = False
        self.discarded = 0
        self.last_discard_log = float('-inf')

    def update(self, level, now):
        pressed = int(level) == self.pressed_level
        if pressed != self.raw:
            if self.raw is not None and self.raw != self.stable:
                self.discarded += 1
            self.raw, self.since = pressed, now
        if self.discarded and now - self.last_discard_log >= 1:
            self.log(f'pulso descartado: {self.discarded} mudança(s) sem estabilidade')
            self.discarded = 0
            self.last_discard_log = now
        if now - self.since + 1e-9 < self.debounce_seconds or self.stable == pressed:
            return False
        self.stable = pressed
        self.log('estado estável: pressionado' if pressed else 'estado estável: solto')
        if not pressed:
            self.armed = True
            return False
        if not self.armed:
            self.log('pressionado ignorado: aguardando soltura estável')
            return False
        self.armed = False
        self.log('clique aceito')
        return True
