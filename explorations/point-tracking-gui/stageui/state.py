"""
app.state
=========
Wraps the headless PipelineState in a QObject so GUI widgets can react to changes
via signals. The GUI holds exactly one AppState.
"""
from __future__ import annotations
from PySide6 import QtCore

from gridtrack.types import PipelineState, CorrectionParams


class AppState(QtCore.QObject):
    imageLoaded = QtCore.Signal()          # a new raw image was loaded
    correctionChanged = QtCore.Signal()    # corrected_image / params updated
    detectionChanged = QtCore.Signal()     # Stage-2 marker detection updated
    gridChanged = QtCore.Signal()          # Stage-3 grid model updated
    featuresChanged = QtCore.Signal()      # Stage-4 feature table updated

    def __init__(self):
        super().__init__()
        self.pipeline = PipelineState()

    @property
    def correction(self) -> CorrectionParams:
        return self.pipeline.correction

    def set_raw(self, path, img):
        self.pipeline.source_path = path
        self.pipeline.raw_image = img
        self.pipeline.corrected_image = img
        self.imageLoaded.emit()

    def set_corrected(self, img):
        self.pipeline.corrected_image = img
        self.correctionChanged.emit()

    def set_detection(self, det):
        self.pipeline.detection = det
        self.detectionChanged.emit()

    def set_grid(self, grid):
        self.pipeline.grid = grid
        self.gridChanged.emit()

    def set_features(self, feats):
        self.pipeline.features = feats
        self.featuresChanged.emit()

    def working_image(self):
        """Best available image: corrected if Stage 1 ran, else raw."""
        return self.pipeline.corrected_image if self.pipeline.corrected_image is not None \
            else self.pipeline.raw_image
