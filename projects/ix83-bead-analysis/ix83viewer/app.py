"""GUI entry point: python3 -m ix83viewer gui [folder]"""

from __future__ import annotations

import sys


def run(path: str | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("IX83 Bead Analysis")
    win = MainWindow()
    from .beads.refbeads_window import safe_gc

    safe_gc(win)  # avoid garbage collection inside Qt events (PySide6 segfaults)
    win.show()
    if path:
        win.open_path(path)
    else:
        win.restore_last_session()  # reopen where you left off
    return app.exec()
