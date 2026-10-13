# Phase 1 — ArUco recognition: id, position, rotation, confidence

*Goal: a headless package and a command-line script that take one microscope image and return
every ArUco tag in it with its id, centre, four corners, rotation, handedness and a confidence
record. No GUI, no grid, no dots yet. Plus the dummy-frame generator every later phase uses.*

## 1. What exists already

`Reference_Warp_Tagger/rwtag/aruco/detect.py` has most of the maths, written and tested in the
V2 workshop:

| function | does | port |
|---|---|---|
| `ArucoParams` | detector settings (µm/px, PSF, error-correction rate, edge band, refinement) | **keep** as the settings dataclass |
| `detector()` | builds `cv2.aruco.ArucoDetector` with `errorCorrectionRate = 1.0` | keep |
| `decode_tags()` | plain inversion (no CLAHE), decode, drop duplicates and edge-band tags | keep; extend the return with the per-tag record below |
| `tag_handedness()` | sign from corner order vs the design | keep |
| `_rot_scale()`, `fit_affine()` | design → image affine from tag centres | keep, used in Phase 3 |
| `Design` | design loader | keep and extend (Phase 3 adds per-box table) |
| dot / dash detection, `refine_gauss`, `refine_fit`, `detect()` | the rest of Stage 2 | Phase 3 |

`tests/test_aruco.py` has unit tests for handedness, the affine paths and refinement. They port
with the code.

## 2. New in this phase

### 2.1 `rwtag/aruco/tags.py` — the per-tag record

`decode_tags` returns `{id: {centre, corners}}`. Extend it to return a `TagObservation` per id:

| field | type | meaning |
|---|---|---|
| `aruco_id` | int | decoded id |
| `centre_px` | (2,) | mean of the four refined corners |
| `corners_px` | (4,2) | TL, TR, BR, BL in ArUco's canonical order, sub-pixel refined |
| `rot_deg` | float | angle of the TL→TR edge in the image, ccw positive in the y-down frame |
| `handedness` | ±1 | sign of the corner-order cross product |
| `side_px` | float | mean edge length (the tag is rigid, so this is the print scale) |
| `n_bits_corrected` | int | Hamming distance between the read bits and the matched id |
| `margin_bits` | int | Hamming distance from the read bits to the nearest *other* id in the dictionary; 0 means the id is ambiguous |
| `contrast` | float | mean black-module minus mean white-module intensity, in image units |
| `in_edge_band` | bool | touches the un-distortion band; the tag is reported but flagged |
| `duplicate` | bool | another detection claimed the same id; both are flagged and neither trusted |

Corner refinement: `cv2.cornerSubPix` on the inverted frame with a window scaled to the module
size, after OpenCV's own corner estimate. `n_bits_corrected` and `margin_bits` come from
re-reading the module grid with `cv2.aruco` helpers (`Dictionary.identify` returns the
corrected id and rotation; the bits are sampled from the warped tag patch). The rotation that
`identify` reports (0–3 quarter turns) is folded into `rot_deg` so the corner order is canonical.

The decode confidence used downstream is the pair `(n_bits_corrected, margin_bits)`: a tag with
`margin_bits >= 2` and `n_bits_corrected == 0` is clean; `n_bits_corrected == 1` is accepted
(the dictionary allows one) but flagged; `margin_bits <= 1` is rejected as ambiguous.

### 2.2 `rwtag/aruco/pose.py` — rotation and frame pose

Per tag, the rotation above. Per frame:

- `frame_rot_deg`: median of all accepted tags' `rot_deg` (the tags are rigid and share the
  gel's rotation), with its median absolute deviation as a spread.
- `frame_handedness`: majority sign; any disagreeing tag is flagged.
- `scale_px_per_um_print`: median `side_px` divided by the design tag size. This is the **print**
  scale (tags do not expand), not the gel scale; the expansion factor comes from the tag
  centres in Phase 3.

Both are returned in a `FramePose` dataclass.

### 2.3 `scripts/find_aruco.py` — the command-line entry point

```
python scripts/find_aruco.py IMAGE [--design PATH] [--um-per-px 0.51] [--psf 2.5]
                             [--edge-band-um 48] [--invert/--no-invert] [--out DIR]
```

Loads the image (16-bit TIFF via the Phase-2 loader, or any 8-bit image), optionally applies
nothing else, decodes, prints one line per tag and one for the frame, and writes
`<image>_tags.csv` (one row per tag with every field in §2.1) and `<image>_tags.png` (the
image with tags drawn: id, corner order arrows, rotation). With `--design` it also reports which
decoded ids are not in the design and which design nodes were not seen.

This script is the deliverable the user can run on the first real image of the coupon or the
spectrum print before any GUI exists.

### 2.4 `ArUco_Tracker_V2/tools/make_dummy_series.py` — dummy frames

Builds on `simulate_v2.py` and `phase_d_end_to_end.py` (which already renders a reference plus
warped expanded frames and keeps the truth). Adds what those lack:

- `--design {optimistic,medium,conservative,spectrum}` reads the design folder's
  `reference_tags.json` and builds the island list from it, so the spectrum's per-box dot sizes
  render correctly. (`simulate_v2.place()` takes islands; the spectrum's `features.csv` has one
  row per feature with size, so islands can be built from that directly.)
- `--lams 1,1.5,2,3,4,6`, `--rot 2,-3,5,...` (per-frame rotation, degrees), `--drift`, `--warp`
  on/off with amplitude and lobe count, `--psf`, `--um-per-px`, `--noise {L1,L2,L3}`,
  `--seeds N` (N noise realisations of each state, same geometry).
- Writes 16-bit TIFFs through `tifffile` with an OME-XML header (`PhysicalSizeX/Y`,
  `AcquisitionDate`, `Objective`, `ExposureTime`, `Channel/ExcitationWavelength`) so the Phase-2
  metadata reader has something real to parse.
- Writes `truth.json`: per frame, every feature's tag → true `raw` px position (after lens
  distortion and vignette, i.e. where it lands in the file), every tag's true rotation and
  corners, the frame's λ, rotation, drift, exposure, the warp description, and the lens
  coefficients applied. Also the truth in the **undistorted** frame, so Phase 2's correction can
  be checked.
- Writes `truth_meta.json` with the header values.

Output: `ArUco_Tracker_V2/dummy/<design>/<run_name>/`. A `README.md` there lists the runs.

Standard runs made in this phase and reused by every later phase:

| run | design | λ | rot | warp | seeds | purpose |
|---|---|---|---|---|---|---|
| `opt_clean` | optimistic | 1, 1.5, 2, 3, 4, 6 | 0 | off | 1 | pure expansion, no distortion |
| `opt_warp` | optimistic | same | 2, −3, 5, 1, −4, 3 | on, 2 µm, 14 lobes | 1 | the Phase-D set-up |
| `opt_noise` | optimistic | 1, 2, 4 | 2 | off | 10 | repeat frames for the error model |
| `spectrum_clean` | spectrum | 1, 1.5 | 0 | off | 1 | per-box pitch and size |
| `cons_dim` | conservative | 1, 3, 6 | 1 | on | 1 | sparse, dim, high-λ edge case |

## 3. Tests (`tests/test_phase1_aruco.py`)

- Every unit test from V1's `test_aruco.py` that touches decode, handedness and affine.
- `test_dummy_decode_all_ids`: on `opt_clean` λ = 1, all 36 ids decode, zero duplicates, every
  centre within 0.5 px of truth, every rotation within 0.5° of truth, handedness −1 on every tag.
- `test_rotation_tracks_frame`: on `opt_warp`, the frame rotation matches the injected rotation
  within 0.3° at every λ.
- `test_edge_band_flagging`: a tag placed within the band is flagged, not dropped silently.
- `test_margin_rejects_ambiguous`: a synthetically damaged tag (one border module erased) is
  either not decoded or has `margin_bits` reported; it is never returned as clean.
- `test_cli_runs`: `find_aruco.py` on one dummy frame writes the CSV and PNG with the expected
  row count.
- `test_mirrored_frame`: a horizontally flipped dummy frame decodes no tag or reports
  handedness +1 on every tag that does decode.

Tolerances come from the W-series findings: corner refinement at this PSF is good to roughly
0.2 px, so 0.5 px on centres is loose enough to pass and tight enough to catch an off-by-one.

## 4. Acceptance

- `find_aruco.py` runs on every frame of the five standard runs and on the six real V1 frames
  (which hold no ArUco tags; it must report zero tags cleanly, not crash).
- All tests pass under the V1 venv with OpenCV 5.
- The user has run the script on one dummy frame and read the CSV.

## 5. How this serves the end goal

The `tags_pose.csv` export in Phase 7 is exactly the §2.1 record per image, plus the Phase-5
uncertainties. Getting the record right here, with the decode-margin fields that make a wrong id
visible, is what lets identity be trusted everywhere downstream.
