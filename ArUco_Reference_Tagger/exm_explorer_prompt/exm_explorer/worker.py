"""Latest-request-wins compute threads.

Each LatestWorker owns one QThread and one pending slot. submit() overwrites
the slot (stale requests are dropped, never queued) and returns a generation
number. The job function receives the payload and an is_stale() callable it
may check between stages to abandon work early. Results of a job that became
stale while running are not emitted.
"""

import threading
import traceback

from PySide6.QtCore import QThread, Signal


class LatestWorker(QThread):
    done = Signal(int, object)          # generation, result
    failed = Signal(int, str)           # generation, traceback text

    def __init__(self, fn, name="worker", parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self._fn = fn
        self._cv = threading.Condition()
        self._pending = None            # (gen, payload)
        self._gen = 0
        self._running = True

    # ------------------------------------------------------------ UI thread
    def submit(self, payload):
        with self._cv:
            self._gen += 1
            self._pending = (self._gen, payload)
            self._cv.notify()
            return self._gen

    def latest(self):
        with self._cv:
            return self._gen

    def stop(self, wait_ms=3000):
        with self._cv:
            self._running = False
            self._pending = None
            self._cv.notify()
        self.wait(wait_ms)

    # ------------------------------------------------------------ worker thread
    def run(self):
        while True:
            with self._cv:
                while self._running and self._pending is None:
                    self._cv.wait()
                if not self._running:
                    return
                gen, payload = self._pending
                self._pending = None

            def is_stale(g=gen):
                return g != self._gen or not self._running

            try:
                result = self._fn(payload, is_stale)
            except Exception:
                if not is_stale():
                    self.failed.emit(gen, traceback.format_exc())
                continue
            if result is not None and not is_stale():
                self.done.emit(gen, result)
