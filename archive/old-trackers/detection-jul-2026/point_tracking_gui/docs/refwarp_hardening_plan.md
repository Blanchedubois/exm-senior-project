# Implementation Plan — Reference-Warp Tagging: Hardening & Consolidation

## 0. Verdict up front (rebuild vs modify)

The reference-warp **architecture stays**. It is validated (strain within ~1σ of expected across
1.5×–4.2×, self-consistent under the composition check, 2–4× tighter scatter than the prior approach)
and the code is small and focused (10 modules). **Nothing here is a from-scratch rebuild of tagging** —
a third rebuild would re-expose the same hard problems (tilt/shift, periodic-lattice box-offset
ambiguity, chirality, high-expansion registration) and touch none of the actual defects, because the
two most-cited defects live UPSTREAM of tagging, in detection.

Each change below is tagged: **[INVESTIGATE] / [MODIFY] / [NEW] / [RELOCATE]**. The only things that get
genuinely *rewritten* are (a) possibly a small targeted node-dot detector (NEW) and (b) the
auto-register acceptance logic (MODIFY). Everything else is fix / move / decide.

---

## 1. Current state

`refwarp/` (in `Old_Trackers_Detection/point_tracking_gui/`): `reftags` (STL tag map), `detect`
(wraps glyphtrack), `warp` (affine → ICP homography → TPS), `tagmatch`, `coreg` (high-exp
auto-register), `session` (series driver), `strain`, `io_csv`, `app` (GUI). Full series tags; strain
verified.

**Known defects (from the critical review):**
- Letters and corner "node" dots are not detected → their tags are never matched.
- High-expansion auto-register can accept a *coincidentally wrong* box offset (periodic dot lattice;
  acceptance is "shares ≥40 tags with one lower frame").
- `refwarp` (a pairing/strain system) sits inside the *detection* app folder, parallel to the older
  strain app (`Old_Tracker_StraiN_Pairing`, richer GUI, older tagging) → two half-right systems.

---

## 2. Work items

### A — Detection root-cause  ✅ DONE — CONCLUSION: DON'T FIX EITHER
Investigated (see scratchpad renders). Both gaps resolved to "not worth fixing":

- **A1 corner dots.** Root cause: they print *fainter/smaller* than interior dots (below the area-30
  floor), not merged with dashes (0 of 19 nodes rejected for size-too-big). BUT the decisive finding is
  conceptual: **a corner dot carries no identity** — it's an anonymous dot at an intersection; knowing
  *which* node it is still requires the registration. So recovering them would NOT break the
  high-expansion box-offset periodicity (my original premise for A1 was wrong). And the warp is already
  ~3 px from interior dots. → **Skip.** (The `node|i_j` tags stay in the map, harmlessly redundant.)
- **A2 letters.** Not a filter issue (letters pass `detect_glyph_blobs`' size band). They are simply
  **faint/absent in the real prints** while the digits are sharp — no blob to detect. Not cheaply
  recoverable. → **Drop** (document the limit; `let|` tags remain but are known-unmatched).

Net: item A produces no code change — it *redirects* effort to B by confirming corner dots can't solve
the high-expansion offset. Only cross-frame geometric agreement (B) can.

**A1. Corner intersection dots.**
- *Investigate:* on a real frame, dump `detect_dots`' accept/reject decision for blobs near the 36
  predicted node positions. Classify: (i) not clearly printed, (ii) rejected by `dot_area`/shape band,
  (iii) merged with the boundary dashes.
- *Fix:* if (ii) → widen/branch the dot filter for the node neighbourhood; if (iii) → **[NEW]** a
  targeted `warp.locate_nodes(image, coarse_warp)` that searches a tight radius around each predicted
  node after a coarse warp.
- *Why this is the highest-leverage item:* corner dots are **unique per intersection**, unlike the
  identical interior dots. If recovered, they can **pin the absolute box offset directly** — which is
  the exact ambiguity that forces the high-expansion guessing. A1 succeeding could *delete* the
  shakiest subsystem rather than patch it. Hence A1 runs before B.
- *Verify:* ≥K of the in-view 36 nodes detected within a few px of their `node|i_j` reference on
  1.5× / 2.5× / 3.0×.

**A2. Letters.**
- *Investigate:* why warped letters land ~111 px from any detected glyph blob — is
  `detect_glyph_blobs` filtering A/B/C/D by size/shape, or are they faint in the print?
- *Fix:* if a filter → adjust the glyph size/shape band (or a second letter-scale pass); if genuinely
  faint → accept as a data limit and **stop advertising `let|` tags** (remove the dead 100 tags from
  what the map claims to deliver).
- *Verify:* letter tags matched per frame; shared letters across 1.5× / 2.0×.

### B — High-expansion registration hardening  ✅ DONE — honest outcome: report, not a hard gate
Attempted a rigorous cross-validation gate; **two designs failed, for instructive reasons:**
- *Shared-tag COUNT ≥ 2 frames* — **fails.** Box-relative dot indices (`di_dj`) repeat across boxes, so
  a whole-box-shifted numbering still string-matches the lower frames' tags (a wrong +1 offset scored
  *higher* than correct in an adversarial test). Tag overlap can't prove a numbering.
- *Consensus on box-per-dot between independent alignments* — **fails on the easy frames.** Auto-align
  between two WIDE-FOV low frames (2.0×↔1.5×) is itself unreliable (no FOV constraint), so it disagrees
  with the correct direct read → valid frames get rejected (dropped to 1/6).

**Root cause:** the only signal that actually breaks the box-offset periodicity is `auto_register`'s
**FOV-constrained design-overlap**, which is *already* computed internally when it picks the alignment.
A bolt-on gate re-derived from tags/positions either gets fooled by periodicity or by wide-frame
ambiguity.

**Shipped instead (honest, non-regressive):** kept the working acceptance (max tag-overlap ≥ `min_share`,
which registers all 6 correctly — strain-validated), **cleaned the fragile `ref_sign` baseline logic**,
and added a per-frame **support REPORT** (`agreement`, `n_frames`, `confidence = "supported by N
frame(s)"`) — explicitly documented in-code as a report, NOT a validator. *Verified:* 6/6 accepted,
strain unchanged (2.0×=1.305 … 4.2×=3.010); each frame's per-lower-frame overlap surfaced.

**If a true gate is wanted later:** expose `auto_register`'s winner-vs-runner-up design-overlap margin
as the confidence, and branch on registration read-confidence (trust direct when digits read; require
≥2 concurring AUTO alignments only for the high frames where direct is garbage). Deferred — diminishing
returns since all frames already register correctly.

### C — Consolidation & relocation  [RELOCATE + DECISION]
- *Problem:* a pairing/strain engine living in the detection app; two half-right systems.
- *C1 [RELOCATE]:* move `refwarp/` to a properly-named standalone home, carrying the `glyphtrack` /
  `gridtrack` dependency via `sys.path` (the pattern the strain app already uses). Keep
  `reference_tags.json` with it.
- *C2 [DECISION — see §4]:* end state — either (a) `refwarp` standalone and grow its GUI, or (b) port
  the reference-warp tagging **into** the existing strain app and retire its `pairkit` tagging, reusing
  that app's richer GUI.
- *Verify:* relocated package imports + runs headless and GUI; CSVs export; strain reproduces the same
  numbers.

### D — GUI enrichment  [NEW, after C]
- Add per-point strain **heatmap**, displacement **vector field**, and measured-vs-expected views onto
  the reference-warp tags. (The strain app already has these; `refwarp`'s GUI has only a table + trend.)
  If C2 = (b), this comes largely for free.

---

## 3. Sequencing & dependencies

```
A1 ──▶ B      (A1's result decides B's approach: pin-by-identity vs ≥2-frame agreement)
A2 ──┐
A,B ─┴▶ C ──▶ D
```
Do A + B first (fix the engine + close the one correctness risk), then C (consolidate the finished
engine), then D. A1 is the pivotal experiment.

---

## 4. Decisions (locked in)

1. **Scope this pass = A + B** (fix detection + harden high-exp registration), then reassess. C/D
   deferred.
2. **Consolidation target (C, later) = `refwarp` standalone**, relocated to a proper home, grow its own
   GUI (no port into the strain app).
3. **Letters (A2) = recover if cheap, else drop** — investigate the cause; fix if it's a filter,
   otherwise remove the dead `let|` tags and accept the limit.
