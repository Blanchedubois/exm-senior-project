"""Keep several aspect-locked ViewBoxes looking at the same place.

pyqtgraph's setXLink/setYLink copies ranges both ways; with aspect locking
and tiles of different shapes each view re-adjusts the other.  Worse, when a
tile shrinks (e.g. the Analysis dock opens) an aspect-locked view keeps its
vertical range by widening its horizontal one; passing that on to the other
tiles compounds on every resize step (observed: 776 px -> 2.5 million px).

So ViewSync owns one canonical view: centre (cx, cy) and scale (data pixels
per screen pixel).  A range change on a view whose size is unchanged is a
user or programmatic pan/zoom: it updates the canonical view, which is then
applied to every other view.  A range change caused by a resize is not
learned from; the canonical view is simply re-applied to that view.
"""

from __future__ import annotations


class ViewSync:
    def __init__(self):
        self.views: list = []
        self._sizes: dict[int, tuple[float, float]] = {}
        self.center: tuple[float, float] | None = None
        self.scale: float | None = None
        self._busy = False

    def set_views(self, views: list):
        for vb in self.views:
            try:
                vb.sigRangeChanged.disconnect(self._on_changed)
            except (RuntimeError, TypeError):
                pass
        self.views = list(views)
        self._sizes = {id(vb): (vb.width(), vb.height()) for vb in self.views}
        for vb in self.views:
            vb.sigRangeChanged.connect(self._on_changed)
        if self.views:
            self._learn(self.views[0])
            self._apply(exclude=None)

    def clear(self):
        self.set_views([])

    def adopt(self, vb):
        """Make vb's current range the shared view (after a programmatic zoom)."""
        if vb in self.views:
            self._sizes[id(vb)] = (vb.width(), vb.height())
            self._learn(vb)
            self._apply(exclude=vb)

    # ---- internals -----------------------------------------------------
    def _on_changed(self, vb, *_):
        if self._busy:
            return
        size = (vb.width(), vb.height())
        resized = self._sizes.get(id(vb)) != size
        self._sizes[id(vb)] = size
        if resized and self.scale is not None:
            self._apply_to(vb)  # restore the shared view at the new size
        else:
            self._learn(vb)
            self._apply(exclude=vb)

    def _learn(self, vb):
        w, h = vb.width(), vb.height()
        if w < 2 or h < 2:
            return
        (x0, x1), (y0, y1) = vb.viewRange()
        self.center = ((x0 + x1) / 2, (y0 + y1) / 2)
        # the smaller per-axis scale is the one the user asked for; the other
        # axis may have been widened by aspect locking
        self.scale = min((x1 - x0) / w, (y1 - y0) / h)

    def _apply(self, exclude):
        for vb in self.views:
            if vb is not exclude:
                self._apply_to(vb)

    def _apply_to(self, vb):
        if self.scale is None or vb.width() < 2 or vb.height() < 2:
            return
        cx, cy = self.center
        hw, hh = self.scale * vb.width() / 2, self.scale * vb.height() / 2
        self._busy = True
        try:
            vb.setRange(xRange=(cx - hw, cx + hw), yRange=(cy - hh, cy + hh), padding=0)
        finally:
            self._busy = False
