# Phase 1 — ArUco recognition: id, position, rotation, confidence

*Goal: a headless package and a command-line script that take one microscope image and return
every ArUco tag in it with its id, centre, four corners, rotation, handedness and a confidence
record. No GUI, no grid, no dots yet. Plus the dummy-frame generator every later phase uses.*

## 1. What exists already

`reference-warp-tagger/rwtag/aruco/detect.py` has most of the maths, written and tested in the
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

### 2.4 `aruco-marker-design/tools/make_dummy_series.py` — dummy frames

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

Output: `aruco-marker-design/dummy/<design>/<run_name>/`. A `README.md` there lists the runs.

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

## 6. As built (2026-10-13)

What changed from the plan above once the code met the dummy frames, with the measured numbers.

**Files.** `rwtag/io.py` (loader + two 8-bit conversions), `rwtag/aruco/{design,tags,pose,fit}.py`,
`scripts/find_aruco.py`, `tests/test_phase1_aruco.py`, `tests/run_all.py`,
`aruco-marker-design/tools/make_dummy_series.py`. `rwtag/aruco/detect.py`'s dot and dash code was
**not** ported yet (Phase 3).

**Corner refinement: contour, not sub-pixel.** On the dummy frames OpenCV's
`CORNER_REFINE_CONTOUR` gave a median centre error of 0.18 px (max 0.45) against 0.42 px
(max 0.98) for `CORNER_REFINE_SUBPIX` at every window size tried. Contour is the default
(`ArucoParams.corner_refine`); the others remain selectable.

**Rotation from four edges.** The TL→TR edge alone gave rotation errors up to 5°. Averaging the
four edge directions gives a median error of 0.11° and a maximum of 0.45° per tag, and the
frame median tracks the applied rotation to 0.05°.

**Handedness cannot come from corner order.** OpenCV returns every tag's corners clockwise
whatever the image, so the V1 corner-order check always returned the expected sign. Handedness
now comes from (a) the bit pattern per tag — the Hamming distance of the mirrored bits to the
dictionary (`mirror_dist`) against that of the direct read; a mirrored frame reads better
mirrored — and (b) the determinant of the design → image affine when 3 or more tags fit it,
which overrides the vote. For `DICT_4X4_50` four ids (8, 9, 17, 47) have a mirror within one bit
of another id; only 17 is in the V2 design, so it abstains from the vote. On a mirrored dummy
frame the one tag that still decoded is reported as "undetermined", never as the expected
orientation.

**8-bit conversion for decoding.** The V1 percentile stretch (0.5–99.5 %) saturates the tags at
high expansion, where the printed features are a tiny fraction of the frame and the 99.5th
percentile sits near the noise floor; the dark modules then erode to thin strokes and the bits
misread (at λ = 4 only 1 of 4 in-frame tags decoded, one of them as a wrong id). `io.to_uint8_robust`
sets the black point at the median and the white point at the maximum of a 3×3-median-filtered
copy, and all four corner tags decode at λ = 4 and 6. The percentile stretch stays for display.

**Expansion from a raw frame is approximate.** The dummy camera's barrel distortion (k1 = −0.05)
magnifies the frame corners by up to 9 %, so an affine through the tag centres of an *uncorrected*
frame reports λ high by 1.8 % at λ = 1 and by 5.7 % at λ = 6, when only the four corner tags are
in view. On a lens-free run the same fit recovers λ to 0.03 % at every expansion (1, 1.5, 2, 3,
4, 6) with the handedness −1 throughout. The exact value therefore belongs to Phase 3, after the
Stage-1 correction; `find_aruco.py` prints the raw-frame value with that caveat.

**RANSAC gate.** The affine's inlier threshold is half a tag side (about 22 px) rather than a
fixed 12 px, so residual lens distortion and gel warp keep their tags while a misdecoded id, which
lands a whole box away, is still rejected.

**Dummy-frame generator.** Two corrections found by the tests: the simulator's `place()` warps
with whatever lobes it is given, so the unwarped reference frame now receives no lobes; and a
sixth preset `opt_nolens` (no lens distortion) exists for tests that need an exact affine.
Truth positions are given in both the raw (distorted) and the undistorted frame; the edge-band
flag in the detector is evaluated in raw coordinates, the truth's `in_frame` in undistorted ones,
so the two disagree for a tag straddling the band — expected, and irrelevant once Phase 2
detects on corrected frames.

**Measured on the standard runs**

| quantity | value |
|---|---|
| tags decoded, every frame of every run | all in-frame tags (36 / 36 at λ ≤ 1.5, 16 at λ = 2, 4 at λ ≥ 3) |
| centre error vs truth, λ = 1 | median 0.18 px, max 0.45 px |
| centre error, warped + lens, all λ | max 0.64 px |
| tag rotation error | median 0.11°, max 0.45° |
| frame rotation error | ≤ 0.05° |
| λ from the affine, lens-free frames | within 0.03 % at λ = 1 … 6 |
| wrong ids returned as usable | 0 (one misread at λ = 4 was classed ambiguous and excluded) |
| real V1 glyph frame | 0 tags, no error |

**Test gates as set:** centre < 0.6 px at λ = 1 and < 0.8 px on warped frames; tag rotation
median < 0.6°, max < 1.5°; frame rotation < 0.3°; λ < 0.5 % on lens-free frames and < 10 % on
raw distorted frames; mirrored frame never reported as the expected orientation.
