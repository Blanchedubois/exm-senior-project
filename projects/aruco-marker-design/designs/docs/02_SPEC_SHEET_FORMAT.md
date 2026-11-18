# 02 — Spec-sheet format

*What goes in each design folder so that recognition code can be written — or configured —
from the folder alone, without reading the generator.*

---

## 1. Files in every design folder

```
designs/<n>_<name>/
  <name>.stl                   the print (box mesh)
  <name>_merged.stl            same geometry, no internal faces (use whichever DeScribe slices cleanly)
  DESIGN_SPEC.md               human-readable design specification                      (phase S6)
  spec_sheet.json              machine-readable parameters — THIS DOCUMENT, §2          (phase S1/S2)
  features.csv                 every printed feature, one row each — §3
  reference_tags.json          the same features in the rwtag schema (what the existing pipeline loads)
  ids.json                     which ArUco id sits at which node
  verify.json                  the gate record (what was checked, and that it passed)
  render.png                   top-down render of the STL
  recognition.png              the S3 test figure
```

## 2. `spec_sheet.json`

Everything is in **micrometres in the design frame** unless the key ends in `_px`. Pixel values
are given for convenience at the stated `um_per_px` and are always accompanied by the µm value
they came from, so a recalibrated pixel size means recomputing, not re-measuring.

```jsonc
{
  "name": "medium",
  "revision": "spacing-workshop S2",
  "units": "um",

  "frame": {
    "origin": "bottom-left corner of the print",
    "x": "right", "y": "UP",
    "note": "images are y-DOWN: design -> image is a REFLECTION. Any fit between the two
             must allow det = -1 (or flip y first) and should assert the sign it finds."
  },

  "envelope": { "x": 750.0, "y": 750.0, "z": 2.0 },

  "grid": {
    "boxes": [5, 5], "nodes": [6, 6],
    "node_origin": 11.5,          // design coordinate of node (0,0) = tag/2
    "node_pitch": 145.4,          // node (i,j) is at origin + i*pitch, origin + j*pitch
    "box_numbering": "N = col*5 + row + 1, column-major, col/row from the bottom-left"
  },

  "tags": {
    "dictionary": "DICT_4X4_50", "modules": 6, "size": 23.0, "module": 3.833,
    "polarity": "printed material = the tag's BLACK modules; in fluorescence they are BRIGHT,
                 so invert the image before cv2.aruco",
    "corner_order": "cv2.aruco order TL,TR,BR,BL = design (x-s,y+s),(x+s,y+s),(x+s,y-s),(x-s,y-s)",
    "rigid": true,                // a tag keeps its printed size at every expansion
    "rounding": { "neck_width": 0.20, "neck_length_modules": 0.72, "fillet_radius": 0.30 },
    "ids": [ { "node": [0,0], "id": 3, "x": 11.5, "y": 11.5 }, ... 36 entries ]
  },

  "dashes": { "length": 8.125, "width": 2.125, "per_box_edge": 10, "count": 480,
              "on": "grid lines x = origin + i*pitch and y = origin + j*pitch" },

  "dots": {
    "shape": "square", "side": 2.125, "height": 2.0,
    "pitch": 6.0, "gap": 3.875,
    "lattice": "square, axis-aligned, centred in each box",
    "per_box_row": 24, "phase_in_box": 3.7,      // first dot centre, from the box's min corner
    "clearance_from_tag": 3.875, "clearance_from_dash": 3.875,
    "count": 11700,
    "tag_format": "dot|B{N}|{di}_{dj}   (di, dj = lattice index inside box N)"
  },

  "optics_assumed": {
    "um_per_px": 0.510,
    "psf_fwhm_design": 2.69,          // the blur this spacing was sized for
    "psf_fwhm_max_measured": null     // filled by phase S3
  },

  "expected_in_image": {              // what the recognition code should look for
    "at_expansion_1": {
      "dot_pitch_px": 11.76, "dot_fwhm_px": 6.7, "dot_area_px2": [12, 220],
      "tag_side_px": 45.1, "tag_module_px": 7.5, "node_pitch_px": 285.1 },
    "scaling_with_expansion": {
      "dot_pitch_px":  "x lambda",
      "node_pitch_px": "x lambda",
      "dot_fwhm_px":   "constant (rigid islands)",
      "tag_side_px":   "constant (rigid islands)",
      "signal":        "x lambda^-1.84  ->  exposure must rise as lambda^2" }
  },

  "detector_settings": {              // rwtag.aruco.ArucoParams, ready to pass
    "error_correction_rate": 1.0, "clahe": false,
    "tophat_px": 15, "dot_area_px2": [12, 220], "noise_k": 5.0,
    "refine": "gauss", "edge_band_um": "abs(k1) * FOV/2 * 1.4",
    "match_gate_pitch_fraction": 0.45 },

  "registration": {
    "rule": "affine through decoded tag CENTRES (>= 3 tags), similarity (2), or one tag's
             corners for rotation + dot-lattice pitch for scale (1). Never through tag corners
             across tags: they are rigid and do not follow the expansion.",
    "handedness_expected": -1 },

  "files": { "stl": "medium.stl", "features": "features.csv", "tag_map": "reference_tags.json" },
  "gate": { "passed": true, "checked": "2026-..", "record": "verify.json" }
}
```

(`jsonc` above is for the comments; the file written is plain JSON with the same keys and a
`"_notes"` object holding the explanatory strings.)

## 3. `features.csv`

One row per printed feature, in the design frame:

| column | meaning |
|---|---|
| `tag` | unique name — `aruco\|N{i}_{j}\|{id}`, `dash\|H{j}\|{m}` / `dash\|V{i}\|{m}`, `dot\|B{N}\|{di}_{dj}` |
| `category` | `aruco` · `dash` · `dot` |
| `x_um`, `y_um` | centre |
| `w_um`, `h_um` | footprint |
| `box` | box number N (dots), blank otherwise |
| `node_i`, `node_j`, `aruco_id` | tags only |
| `di`, `dj` | lattice index within the box (dots only) |

The spectrum print adds `dot_um`, `pitch_um`, `gap_um` per row and a second file,
`boxes.csv`, one row per box (see `03_SPECTRUM_PRINT.md` §4).

## 4. Reading it

```python
import json, csv
spec  = json.load(open("designs/2_medium/spec_sheet.json"))
pitch = spec["dots"]["pitch"]                       # 6.0 um
ids   = {t["id"]: (t["x"], t["y"]) for t in spec["tags"]["ids"]}
feats = list(csv.DictReader(open("designs/2_medium/features.csv")))

# or straight into the existing pipeline:
from rwtag.aruco import Design, ArucoParams, series
design = Design.load("designs/2_medium/reference_tags.json")
params = ArucoParams(um_per_px=spec["optics_assumed"]["um_per_px"],
                     psf_fwhm_um=spec["optics_assumed"]["psf_fwhm_design"])
```

## 5. Rules the emitter follows (phase S1)

1. Every number is **written by the generator from the same objects it builds the STL from** —
   never typed by hand — and the gate re-reads the spec sheet and checks it against the rendered
   STL (dot count, pitch, tag positions, ids).
2. µm is the truth; `_px` values are derived and carry the `um_per_px` they assumed.
3. The frame, the polarity, the corner order and the handedness are stated in words in every
   sheet. Those four are where recognition code goes wrong (five times in this workspace).
