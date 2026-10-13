"""
rwtag.aruco.design
==================
The V2 reference map, loaded from a design folder's `reference_tags.json` (plus
`spec_sheet.json` / `ids.json` when present). Nothing about the print is
hard-coded anywhere else: node pitch, node origin, dictionary, tag size and the
per-box dot size / pitch / phase all come from here.

Design frame: origin bottom-left, x right, y UP, micrometres. Design -> image is
a reflection (det < 0).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import os
import numpy as np


@dataclass
class BoxSpec:
    N: int                 # V1 numbering: N = col*grid_n + row + 1, from the bottom-left
    col: int
    row: int
    x0_um: float           # lower-left node of the box (design frame)
    y0_um: float
    side_um: float         # node pitch
    dot_um: float
    pitch_um: float
    phase_um: float        # first dot at x0 + phase
    count: int = 0
    corner_tag_ids: tuple = ()
    tag_keepout_um: float = 0.0
    dash_clear_um: float = 0.0


@dataclass
class Design:
    records: list
    box_um: float                     # node pitch, (field - tag) / grid_n for fit "inside"
    origin_um: float                  # design coordinate of node (0,0) (= tag/2 for "inside")
    dot_pitch_um: float               # global (designs 1-3) / the conservative value (spectrum)
    dot_side_um: float
    tag_um: float
    dict_name: str
    grid_n: int
    field_um: float = 750.0
    dashes_per_edge: int = 10
    boxes: list = field(default_factory=list)      # list[BoxSpec], one per box
    node_ids: list = field(default_factory=list)   # [(i, j, id)]
    name: str = ""
    folder: str = ""
    file_sha256: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_dict(cls, data, name="", folder=""):
        cfg = data.get("config", {})
        tag = float(cfg.get("tag_um", 0.0))
        origin = tag / 2.0 if cfg.get("fit", "inside") == "inside" else 0.0
        box = float(data["box_um"])
        grid_n = int(data.get("grid_n", cfg.get("grid_n", 5)))
        d = cls(records=data["records"], box_um=box, origin_um=origin,
                dot_pitch_um=float(data["dot_pitch"]),
                dot_side_um=float(data.get("dot_side_um", cfg.get("dot_side_um", 2.125))),
                tag_um=tag, dict_name=cfg.get("dict_name", "DICT_4X4_50"), grid_n=grid_n,
                field_um=float(cfg.get("field_um", 750.0)),
                dashes_per_edge=int(cfg.get("dashes_per_edge", 10)),
                name=name or cfg.get("variant", ""), folder=folder)
        d.node_ids = [(int(i), int(j), int(v)) for i, j, v in cfg.get("ids", [])]
        if not d.node_ids:
            d.node_ids = [(int(r["meta"]["node_i"]), int(r["meta"]["node_j"]),
                           int(r["meta"]["aruco_id"])) for r in d.tag_records()]
        d.boxes = d._boxes_from(data)
        return d

    def _boxes_from(self, data):
        """Per-box table: the spectrum file carries one; designs 1-3 get one
        synthesised row per box from the global values."""
        rows = data.get("boxes")
        out = []
        if rows:
            for b in rows:
                out.append(BoxSpec(N=int(b["box"]), col=int(b["col"]), row=int(b["row"]),
                                   x0_um=float(b["x0_um"]), y0_um=float(b["y0_um"]),
                                   side_um=self.box_um, dot_um=float(b["dot_um"]),
                                   pitch_um=float(b["pitch_um"]), phase_um=float(b["phase_um"]),
                                   count=int(b.get("count", 0)),
                                   tag_keepout_um=float(b.get("tag_keepout_um", 0.0)),
                                   dash_clear_um=float(b.get("dash_clear_um", 0.0))))
        else:
            phase = float(data.get("dot_phase", 0.0))
            counts = {}
            for r in self.records:
                if r["category"] == "dot":
                    counts[int(r["meta"]["box"])] = counts.get(int(r["meta"]["box"]), 0) + 1
            for col in range(self.grid_n):
                for row in range(self.grid_n):
                    N = col * self.grid_n + row + 1
                    out.append(BoxSpec(N=N, col=col, row=row,
                                       x0_um=self.origin_um + col * self.box_um,
                                       y0_um=self.origin_um + row * self.box_um,
                                       side_um=self.box_um, dot_um=self.dot_side_um,
                                       pitch_um=self.dot_pitch_um, phase_um=phase,
                                       count=counts.get(N, 0)))
        by_n = {b.N: b for b in out}
        # corner tags per box from the node ids
        idmap = {(i, j): v for i, j, v in self.node_ids}
        for b in by_n.values():
            ids = [idmap.get((b.col + a, b.row + c)) for a in (0, 1) for c in (0, 1)]
            b.corner_tag_ids = tuple(int(x) for x in ids if x is not None)
        return [by_n[k] for k in sorted(by_n)]

    @classmethod
    def load(cls, path, name=""):
        with open(path) as f:
            data = json.load(f)
        d = cls.from_dict(data, name=name, folder=os.path.dirname(os.path.abspath(path)))
        d.file_sha256["reference_tags.json"] = _sha256(path)
        return d

    @classmethod
    def load_folder(cls, folder, name=""):
        """A design folder: reference_tags.json (+ spec_sheet.json, ids.json)."""
        folder = os.path.abspath(folder)
        rt = os.path.join(folder, "reference_tags.json")
        if not os.path.exists(rt):
            cands = [f for f in os.listdir(folder) if f.endswith(".reference_tags.json")]
            if not cands:
                raise FileNotFoundError(f"no reference_tags.json in {folder}")
            rt = os.path.join(folder, sorted(cands)[0])
        d = cls.load(rt, name=name or os.path.basename(folder))
        for extra in ("spec_sheet.json", "ids.json"):
            p = os.path.join(folder, extra)
            if os.path.exists(p):
                d.file_sha256[extra] = _sha256(p)
                if extra == "spec_sheet.json":
                    with open(p) as f:
                        sp = json.load(f)
                    by_n = {b.N: b for b in d.boxes}
                    for b in sp.get("boxes", []):
                        if int(b["box"]) in by_n and b.get("corner_tag_ids"):
                            by_n[int(b["box"])].corner_tag_ids = tuple(int(x) for x in b["corner_tag_ids"])
        return d

    # ---------------------------------------------------------------- queries
    def tag_records(self):
        return [r for r in self.records if r["category"] == "aruco"]

    def id_to_node(self):
        return {v: (i, j) for i, j, v in self.node_ids}

    def node_xy_um(self, i, j):
        return np.array([self.origin_um + i * self.box_um, self.origin_um + j * self.box_um])

    def design_corners(self, rec):
        """Design-frame (y-UP) corners of a tag record in ArUco's canonical order
        TL, TR, BR, BL. The generator draws the marker with its canonical top row
        at the HIGHEST design y, and the image flips y, so corner k of the
        detection is corner k here."""
        s = float(rec["meta"].get("size_um", self.tag_um)) / 2.0
        x, y = float(rec["x_um"]), float(rec["y_um"])
        return np.array([[x - s, y + s], [x + s, y + s], [x + s, y - s], [x - s, y - s]])

    @property
    def design_corner_sign(self):
        """Sign of cross(TR-TL, BL-TL) in the design frame (-1 for y-up)."""
        r = self.tag_records()[0]
        c = self.design_corners(r)
        a, b = c[1] - c[0], c[3] - c[0]
        return float(np.sign(a[0] * b[1] - a[1] * b[0]))

    def box(self, N) -> BoxSpec:
        for b in self.boxes:
            if b.N == N:
                return b
        raise KeyError(N)

    def box_of_design_xy(self, x_um, y_um):
        col = int(np.floor((x_um - self.origin_um) / self.box_um))
        row = int(np.floor((y_um - self.origin_um) / self.box_um))
        if 0 <= col < self.grid_n and 0 <= row < self.grid_n:
            return col * self.grid_n + row + 1
        return None

    def summary(self):
        cats = {}
        for r in self.records:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        return (f"{self.name or 'design'}: field {self.field_um:g} um · {self.grid_n}x{self.grid_n} boxes "
                f"· node pitch {self.box_um:.1f} um · tag {self.tag_um:g} um {self.dict_name} · "
                + " · ".join(f"{k} {v}" for k, v in sorted(cats.items())))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
