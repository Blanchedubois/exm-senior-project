"""Scale bar that labels itself in µm and resizes with zoom."""

from __future__ import annotations

import pyqtgraph as pg

from ..core.display import format_um, nice_scale_length

TARGET_FRACTION = 0.2  # bar aims for ~20% of the visible width


class MicronScaleBar(pg.ScaleBar):
    def __init__(self, view_box: pg.ViewBox):
        super().__init__(size=100, width=6, brush="w", pen=pg.mkPen("k", width=0.5), suffix="")
        self.text.setColor("w")
        self.text.fill = pg.mkBrush(0, 0, 0, 150)  # readable on bright images
        self._vb = view_box
        self.pixel_size_um: float | None = None
        self.expansion: float | None = None  # set to show pre-expansion (biological) size
        self.enabled = True
        self.setParentItem(view_box)
        self.anchor((1, 1), (1, 1), offset=(-24, -24))
        view_box.sigRangeChanged.connect(self.refresh)

    def set_pixel_size(self, um_per_px: float | None):
        self.pixel_size_um = um_per_px
        self.refresh()

    def set_expansion(self, factor: float | None):
        self.expansion = factor
        self.refresh()

    def set_enabled(self, on: bool):
        self.enabled = on
        self.refresh()

    def refresh(self, *_):
        show = self.enabled and bool(self.pixel_size_um)
        self.setVisible(show)
        if not show:
            return
        (x0, x1), _ = self._vb.viewRange()
        f = self.expansion or 1.0
        # choose a round length in the units being labelled
        length_um = nice_scale_length((x1 - x0) * self.pixel_size_um / f * TARGET_FRACTION)
        self.size = length_um * f / self.pixel_size_um
        self.text.setText(format_um(length_um) + (f" pre-exp. (÷{f:g})" if self.expansion else ""))
        self.updateBar()
