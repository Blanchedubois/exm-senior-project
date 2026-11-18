"""
fieldkit.pipeline
=================
Run the five gridtrack stages on ONE image and write its per-stage CSVs.
A thin, headless wrapper over the exact calls validated in the single-image tool.
"""
from __future__ import annotations
from dataclasses import dataclass

from gridtrack import io, correct, address, reference as refmod, measure, filters
from . import markers, io_csv


@dataclass
class ImageResult:
    path: str
    detection: object        # MarkerDetection
    grid: object             # GridModel
    features: object         # filtered feature table (pd.DataFrame)
    markers: object          # unified tags+dots table (pd.DataFrame)


def process_image(path: str, project) -> ImageResult:
    """Stages 1-5 on `path`, using the project's SHARED correction + params +
    reference. Writes CSVs and returns an ImageResult."""
    ref = project.reference
    dict_name = getattr(ref, "aruco_dict", "DICT_6X6_1000")
    ip = project.params_for(path)                                        # per-image Stage 2-5

    img = io.load_tiff(path)                                              # load
    corr = correct.apply(img, project.correction)                        # Stage 1 shared optics
    corr = correct.levels(corr, ip.levels)                               # Stage 1 per-image contrast
    det = address.detect_and_orient(corr, dict_name, project.correction)  # Stage 2
    # dots feed Stage 3's few-tag tiers + region-grow (and refine the global tier)
    dots_xy = measure.detect_dots(det.image, ip.measure)[["x", "y"]].to_numpy() \
        if len(det.ids) else None
    grid = refmod.map_grid(det, ref, model=ip.transform_model,
                           ransac_thresh=ip.ransac_px, dots_xy=dots_xy)   # Stage 3
    feats4 = measure.detect_features(det.image, grid, ref, ip.measure)              # Stage 4
    feats5 = filters.apply_filters(feats4, grid, ref, ip.filters, det.image.shape)  # Stage 5
    mk = markers.build(det, grid, feats5)                                # unify tags+dots

    d = io_csv.image_dir(project.out_dir, path)
    io_csv.write_all(d, project.correction, det, grid, feats4, feats5, mk)
    return ImageResult(path, det, grid, feats5, mk)
