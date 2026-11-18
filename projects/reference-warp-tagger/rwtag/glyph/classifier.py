"""
glyphtrack.classifier
=====================
Recognise a single glyph crop as one of '0'..'9','A'..'D'.

HOG features + a k-NN classifier (OpenCV `ml.KNearest` — no extra deps), trained
on glyphs auto-mined from the STL (`stl_glyphs`) and heavily AUGMENTED to look
like the real microscopy prints (blur, rotation, scale, shift, noise, contrast).
k-NN gives a natural confidence (neighbour agreement) for the detector's reject
option.
"""
from __future__ import annotations
import numpy as np
import cv2
from skimage.feature import hog

from .types import CLASSES

NEG_CLASSES = ["dash", "dot"]               # reject classes (non-glyph structures)
ALL_LABELS = CLASSES + NEG_CLASSES          # what the classifier is trained over
CROP = 28                                   # glyph crops are CROP x CROP, grayscale


def is_glyph(label: str) -> bool:
    return label in CLASSES


# ---------------------------------------------------------------- features
def normalize_crop(g: np.ndarray) -> np.ndarray:
    """Grayscale glyph -> CROP x CROP, min-max stretched to [0,1] float32.
    Same for training and prediction so features are comparable."""
    if g.shape != (CROP, CROP):
        g = cv2.resize(g, (CROP, CROP), interpolation=cv2.INTER_AREA)
    g = g.astype(np.float32)
    lo, hi = float(g.min()), float(g.max())
    return (g - lo) / (hi - lo) if hi > lo else g * 0.0


def hog_feat(g: np.ndarray) -> np.ndarray:
    """HOG descriptor of a normalised crop."""
    f = hog(normalize_crop(g), orientations=9, pixels_per_cell=(7, 7),
            cells_per_block=(2, 2), block_norm="L2-Hys", feature_vector=True)
    return f.astype(np.float32)


# ---------------------------------------------------------------- augmentation
def _augment_one(base: np.ndarray, rng, blur, rot, scale, shift, noise):
    """One realistic variant of a (binary) template glyph: blur it into a
    grayscale blob like the PSF, jitter geometry + intensity + noise."""
    h, w = base.shape
    ang = rng.uniform(-rot, rot)
    sc = rng.uniform(1 - scale, 1 + scale)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, sc)
    M[0, 2] += rng.uniform(-shift, shift)
    M[1, 2] += rng.uniform(-shift, shift)
    g = cv2.warpAffine(base.astype(np.float32), M, (w, h), flags=cv2.INTER_LINEAR)
    sig = rng.uniform(*blur)
    g = cv2.GaussianBlur(g, (0, 0), sig)
    g = g / max(g.max(), 1e-6)
    lo = rng.uniform(0.0, 0.35); hi = rng.uniform(0.6, 1.0)     # contrast/brightness
    g = lo + (hi - lo) * g
    g = g + rng.normal(0, noise, g.shape)                        # sensor noise
    return np.clip(g * 255.0, 0, 255).astype(np.uint8)


def build_dataset(labeled: dict, n_aug=40, seed=0, blur=(0.6, 2.6),
                  rot=18.0, scale=0.12, shift=2.5, noise=0.05, labels=ALL_LABELS):
    """{label:[templates]} -> (feats NxD float32, labels Nx1 int32) with
    `n_aug` augmented samples per template, over the given label list."""
    rng = np.random.default_rng(seed)
    X, y = [], []
    for ci, ch in enumerate(labels):
        for tmpl in labeled.get(ch, []):
            base = cv2.resize(tmpl, (CROP, CROP), interpolation=cv2.INTER_AREA)
            X.append(hog_feat(base)); y.append(ci)              # the clean template too
            for _ in range(n_aug):
                aug = _augment_one(base, rng, blur, rot, scale, shift, noise)
                X.append(hog_feat(aug)); y.append(ci)
    return np.asarray(X, np.float32), np.asarray(y, np.int32).reshape(-1, 1)


def compact_prototypes(feats, labels, per_class=60, seed=0):
    """Shrink a big training set to `per_class` k-means prototypes per class —
    a compact, fast k-NN model (tiny to save) that keeps the decision surface."""
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1e-3)
    PX, PY = [], []
    for ci in np.unique(labels):
        f = feats[labels.ravel() == ci]
        k = min(per_class, len(f))
        if k < 2:
            PX.append(f); PY += [ci] * len(f); continue
        _, _, centers = cv2.kmeans(f, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
        PX.append(centers); PY += [int(ci)] * k
    return np.vstack(PX).astype(np.float32), np.asarray(PY, np.int32).reshape(-1, 1)


# ---------------------------------------------------------------- classifier
class GlyphClassifier:
    def __init__(self, k=7):
        self.k = k
        self.knn = None

    def train(self, feats, labels):
        self.knn = cv2.ml.KNearest_create()
        self.knn.setDefaultK(self.k)
        self.knn.train(feats, cv2.ml.ROW_SAMPLE, labels)
        return self

    def predict(self, crop):
        """-> (label, confidence). label may be a glyph ('0'..'D') or a reject
        class ('dash'/'dot'). Confidence = fraction of the k neighbours agreeing."""
        f = hog_feat(crop).reshape(1, -1)
        _, res, neigh, _ = self.knn.findNearest(f, self.k)
        cls = int(res[0, 0])
        conf = float((neigh[0] == cls).mean())
        return ALL_LABELS[cls], conf

    def predict_restricted(self, crop, allowed, k=15):
        """Classify a crop but only among `allowed` labels (e.g. just 'ABCD' at a
        letter slot, or the digits at a number slot). Returns (label, confidence)
        from the agreement of the k nearest neighbours restricted to `allowed`."""
        from collections import Counter
        f = hog_feat(crop).reshape(1, -1)
        _, _, neigh, dist = self.knn.findNearest(f, k)
        labels = [ALL_LABELS[int(x)] for x in neigh[0]]
        cnt = Counter(l for l in labels if l in allowed)
        if cnt:
            ch, c = cnt.most_common(1)[0]
            return ch, c / len(labels)
        for idx in np.argsort(dist[0]):                  # fallback: nearest allowed
            l = ALL_LABELS[int(neigh[0][idx])]
            if l in allowed:
                return l, 0.2
        return allowed[0], 0.0

    def predict_batch(self, crops):
        if not crops:
            return []
        F = np.asarray([hog_feat(c) for c in crops], np.float32)
        _, res, neigh, _ = self.knn.findNearest(F, self.k)
        out = []
        for i in range(len(crops)):
            cls = int(res[i, 0]); conf = float((neigh[i] == cls).mean())
            out.append((ALL_LABELS[cls], conf))
        return out

    # persistence -------------------------------------------------------------
    def save(self, path):
        self.knn.save(path)

    @classmethod
    def load(cls, path, k=7):
        obj = cls(k=k)
        obj.knn = cv2.ml.KNearest_load(path)
        return obj


def synthetic_dashes(crop=CROP):
    """Fat rounded-capsule templates matching the REAL boundary dashes (which the
    thin STL dashes don't capture). Used only as reject examples."""
    out = []
    for L in range(14, 27, 2):
        for T in range(12, 26, 2):
            im = np.zeros((crop, crop), np.uint8)
            y = crop // 2; x0 = (crop - L) // 2; x1 = x0 + L
            cv2.line(im, (x0, y), (x1, y), 255, T)
            cv2.circle(im, (x0, y), T // 2, 255, -1)
            cv2.circle(im, (x1, y), T // 2, 255, -1)
            out.append(im)
    return out


def build_glyph_model(stl_path, px_per_um=3.0, n_aug=30, per_class=90,
                      blur=(0.4, 1.6), k=7):
    """One-call reproducible model build from the STL: mine glyphs + negatives,
    augment, compact, train. Returns a trained GlyphClassifier."""
    from . import stl_glyphs as sg
    lab = sg.extract_labeled_glyphs(stl_path, px_per_um)
    neg = sg.extract_negatives(stl_path, px_per_um)
    lab["dash"] = neg["dash"] + synthetic_dashes() * 6
    lab["dot"] = neg["dot"]
    X, y = build_dataset(lab, n_aug=n_aug, blur=blur)
    PX, PY = compact_prototypes(X, y, per_class=per_class)
    return GlyphClassifier(k=k).train(PX, PY)
