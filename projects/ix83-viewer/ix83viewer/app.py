"""GUI entry point: python3 -m ix83viewer gui [folder]"""

from __future__ import annotations

import sys


def run(path: str | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("IX83 Viewer")
    win = MainWindow()
    win.show()
    if path:
        win.open_path(path)
    else:
        win.restore_last_session()  # reopen where you left off
    return app.exec()
