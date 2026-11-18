"""
refwarp.session
===============
Drive the whole reference-warp tagging over a series of expansion images and pair
them by tag. Processes in ascending-expansion order; each image is tagged by:

  1. direct — fit the reference->image warp from its own (read-based) registration;
  2. if that is invalid (wrong handedness, high residual) or shares too few tags
     with the already-tagged frames, AUTO-ALIGN to whichever lower good frame
     overlaps it most (coreg), transferring box numbers.

A candidate is accepted only if it shares >= MIN_SHARE tags with the union of
already-good frames — the check that catches a low-residual-but-mis-numbered fit
(the periodic dot lattice makes residual alone insufficient).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from . import detect, warp, tagmatch, coreg, reftags


@dataclass
class Frame:
    path: str
    label: float
    d: dict = None                    # detection
    warp: dict = None                 # warp model
    tags: dict = None                 # {tag: (x_px,y_px)}
    source: str = ""                  # "direct" | "auto<-2.0x" | ...
    ok: bool = False
    agreement: list = field(default_factory=list)   # [(lower_label, shared_tag_count)]
    n_frames: int = 0                 # # lower frames it independently agrees with
    confidence: str = ""              # "baseline" | "cross-validated" | "single-frame" | "rejected"


@dataclass
class TagSession:
    model_path: str
    max_resid: float = 10.0
    min_share: int = 40            # min shared tags with the good frames to accept
    support_min: int = 25          # per-frame overlap that counts as "supported by" a frame
    frames: list = field(default_factory=list)
    _clf: object = None
    _refdot: np.ndarray = None
    _records: list = None
    ref_sign: float = None

    def add(self, path, label):
        self.frames.append(Frame(path, float(label)))

    def _prep(self):
        if self._clf is None:
            self._clf = detect.load_classifier(self.model_path)
            self._records = reftags.load()["records"]
            self._refdot = np.array([[r["x_um"], r["y_um"]]
                                     for r in self._records if r["category"] == "dot"])

    def _valid(self, m):
        return (m.get("H") is not None and m.get("per_det_median", 9e9) < self.max_resid
                and coreg.homography_sign(m["H"]) == self.ref_sign)

    def _tagset(self, d, m):
        return tagmatch.tag_image(d, m, self._records)["tag_xy"]

    def process(self, progress=None):
        self._prep()
        good = []                                        # accepted Frames
        order = sorted(self.frames, key=lambda f: f.label)
        for k, f in enumerate(order):
            f.d = detect.detect(f.path, self._clf)
            pitch = f.d["basis"]["pitch"]
            md = warp.fit_warp(self._refdot, f.d["dots"], f.d["fit"],
                               f.d["model"]["reg"], pitch)

            if not good:                                 # baseline: the lowest-expansion frame.
                if md.get("H") is None:                  # sets the handedness everything else checks
                    f.confidence = "rejected"
                    if progress: progress(k + 1, len(order), f)
                    continue
                self.ref_sign = coreg.homography_sign(md["H"])
                f.tags, f.warp, f.source, f.ok, f.confidence = \
                    self._tagset(f.d, md), md, "baseline", True, "baseline"
                good.append(f)
                if progress: progress(k + 1, len(order), f)
                continue

            # Candidates: the direct (digit-read) registration, plus a geometric
            # auto-alignment to each lower good frame. Pick the one whose tags overlap the
            # already-good frames most; accept if that overlap clears min_share.
            lower_tags = set().union(*[set(g.tags) for g in good])
            cands = []                                   # (tags_dict, warp, source)
            if self._valid(md):
                cands.append((self._tagset(f.d, md), md, "direct"))
            for g in good:
                _, m2 = coreg.auto_register(f.d, g.d, self._refdot, self.ref_sign, pitch)
                if m2 is not None and self._valid(m2):
                    cands.append((self._tagset(f.d, m2), m2, f"auto<-{g.label:g}x"))
            if cands:
                tags, m, src = max(cands, key=lambda c: len(set(c[0]) & lower_tags))
                S = set(tags)
                per = [(g.label, len(S & set(g.tags))) for g in good]   # how many tags each lower frame shares
                f.agreement = per
                # NOTE: `per` is a support/overlap REPORT, not a rigorous validator — box-relative
                # dot tags repeat across boxes, so overlap can't by itself prove the numbering.
                # The reliable signal is auto_register's FOV-constrained design-overlap (internal).
                f.n_frames = sum(1 for _, c in per if c >= self.support_min)
                if len(S & lower_tags) >= self.min_share:
                    f.tags, f.warp, f.source, f.ok = tags, m, src, True
                    f.confidence = f"supported by {f.n_frames} frame(s)"
                    good.append(f)
                else:
                    f.confidence = "rejected (too little overlap)"
            if progress:
                progress(k + 1, len(order), f)
        return [f for f in order if f.ok]

    # ------------------------------------------------------------------ pairing
    def pair_table(self):
        """Wide pairing: {tag: {label: (x_px,y_px)}} over all accepted frames."""
        table = {}
        for f in self.frames:
            if not f.ok:
                continue
            for tag, xy in f.tags.items():
                table.setdefault(tag, {})[f.label] = xy
        return table
