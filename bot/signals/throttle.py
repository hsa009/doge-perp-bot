import threading
import time


class ProviderThrottle:
    def __init__(self, min_delay_ms: int):
        self.min_delay = min_delay_ms / 1000.0
        self._lock = threading.Lock()
        self._last_call: float = 0.0

    def acquire(self) -> float:
        with self._lock:
            now = time.time()
            wait = max(0.0, self._last_call + self.min_delay - now)
            self._last_call = now + wait
            return wait
