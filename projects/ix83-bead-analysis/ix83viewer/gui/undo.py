"""Undo/redo of channel adjustments.

Each edit is a SnapshotCommand holding the channel's state before and after.
Rapid edits of the same kind on the same channel (a slider or histogram drag)
merge into one step if they arrive within MERGE_SECONDS of each other.
"""

from __future__ import annotations

import time

from PySide6.QtGui import QUndoCommand, QUndoStack

MERGE_SECONDS = 1.0
_LABELS = {"levels": "contrast", "gamma": "gamma", "invert": "invert", "color": "colour",
           "opacity": "opacity", "processing": "processing", "region": "background region",
           "preset": "preset", "reset": "reset", "copy": "copy settings"}


class SnapshotCommand(QUndoCommand):
    def __init__(self, target, before, after, kind: str):
        super().__init__(f"{target.name} {_LABELS.get(kind, kind)}")
        self.target, self.before, self.after, self.kind = target, before, after, kind
        self.stamp = time.monotonic()
        self._first = True

    def id(self) -> int:
        return 1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if (not isinstance(other, SnapshotCommand) or other.target is not self.target
                or other.kind != self.kind or self.kind in ("processing", "preset", "reset", "copy")
                or other.stamp - self.stamp > MERGE_SECONDS):
            return False
        self.after, self.stamp = other.after, other.stamp
        return True

    def redo(self):
        if self._first:  # already applied when the user made the change
            self._first = False
            return
        self.target.apply_snapshot(self.after)

    def undo(self):
        self.target.apply_snapshot(self.before)


def connect_undo(target, stack: QUndoStack):
    target.edited.connect(lambda t, before, after, kind: stack.push(SnapshotCommand(t, before, after, kind)))
