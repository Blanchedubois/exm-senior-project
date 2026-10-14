"""
gui.state
=========
Wraps the headless PipelineState in a QObject so GUI widgets react to changes via
signals. The GUI holds exactly one AppState (one active image at a time).
"""
from __future__ import annotations
from PySide6 import QtCore

from rwtag.types import PipelineState, CorrectionParams, LevelsParams


class AppState(QtCore.QObject):
    imageLoaded = QtCore.Signal()          # a new raw image was loaded (results cleared)
    imageActivated = QtCore.Signal()       # switched to another project image (results KEPT)
    correctionChanged = QtCore.Signal()    # corrected_image / params updated
    detectionChanged = QtCore.Signal()     # Stage-2 DetectResult updated
    featuresChanged = QtCore.Signal()      # Stage-3 FilterResult updated
    taggingChanged = QtCore.Signal()       # Stage-4 TagResult updated

    metaChanged = QtCore.Signal()          # the active image's metadata record changed

    def __init__(self):
        super().__init__()
        self.pipeline = PipelineState()

    def activate(self, pipeline):
        """Point the state at another image's pipeline (project selection change).
        Unlike set_raw this KEEPS the pipeline's existing results — panels restore
        from state instead of clearing."""
        self.pipeline = pipeline
        self.imageActivated.emit()

    @property
    def meta(self):
        return self.pipeline.meta

    @property
    def correction(self) -> CorrectionParams:
        return self.pipeline.correction

    @property
    def levels(self) -> LevelsParams:
        return self.pipeline.levels

    def set_raw(self, path, img):
        self.pipeline.source_path = path
        self.pipeline.raw_image = img
        self.pipeline.corrected_image = img
        self.pipeline.detection = None          # detection is per-image; invalidate on new frame
        self.imageLoaded.emit()

    def set_corrected(self, img):
        self.pipeline.corrected_image = img
        self.correctionChanged.emit()

    def set_detection(self, det):
        self.pipeline.detection = det
        self.pipeline.features = None       # a new detection invalidates the old filter
        self.detectionChanged.emit()

    def set_features(self, fr):
        self.pipeline.features = fr
        self.featuresChanged.emit()

    def set_tagging(self, tr):
        self.pipeline.tagging = tr
        self.taggingChanged.emit()

    def working_image(self):
        return self.pipeline.working_image()
