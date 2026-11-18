"""Background loading that keeps the UI responsive.

LatestOnlyLoader runs one job at a time and keeps only the newest pending
request, so dragging the frame slider never queues up dozens of reads.
"""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class _Job(QRunnable):
    def __init__(self, req_id, fn, signals):
        super().__init__()
        self.req_id, self.fn, self.signals = req_id, fn, signals

    def run(self):
        try:
            result = self.fn()
        except Exception as e:
            self.signals.failed.emit(self.req_id, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        else:
            self.signals.finished.emit(self.req_id, result)


class LatestOnlyLoader(QObject):
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._next_id = 0
        self._running = None  # (id, on_done, on_error)
        self._pending = None  # (fn, on_done, on_error)

    def request(self, fn, on_done, on_error=None):
        """Run fn() in the background; on_done(result) runs on the GUI thread.

        If a job is already running, this request replaces any older pending one.
        """
        if self._running:
            self._pending = (fn, on_done, on_error)
        else:
            self._start(fn, on_done, on_error)

    def _start(self, fn, on_done, on_error):
        self._next_id += 1
        self._running = (self._next_id, on_done, on_error)
        self.busy_changed.emit(True)
        self._pool.start(_Job(self._next_id, fn, self._signals))

    def _advance(self):
        self._running = None
        if self._pending:
            fn, on_done, on_error = self._pending
            self._pending = None
            self._start(fn, on_done, on_error)
        else:
            self.busy_changed.emit(False)

    def _on_finished(self, req_id, result):
        _, on_done, _ = self._running
        superseded = self._pending is not None
        self._advance()
        if not superseded:
            on_done(result)

    def _on_failed(self, req_id, message):
        _, _, on_error = self._running
        self._advance()
        if on_error:
            on_error(message)

    def wait(self, msecs: int = -1) -> bool:
        return self._pool.waitForDone(msecs)
