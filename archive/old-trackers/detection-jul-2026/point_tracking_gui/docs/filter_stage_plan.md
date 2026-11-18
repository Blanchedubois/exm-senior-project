# Stage 4 — Dot Filter (implemented)

Filters the fill dots (the tracking points) with three toggleable, adjustable rules.
Headless: `glyphtrack/dotfilter.py` (`DotFilterParams`, `filter_dots`); GUI:
`stageui/stage_filter.py` (Stage **4 Filter dots**).

## The three filters
1. **Too close to a neighbour.** Drop a dot whose nearest neighbour is closer than
   `min_sep_frac × dot_pitch`. The **dot pitch = box pitch / 18.75** (the grid-to-dot ratio, measured
   from the refined lattice), so the threshold is set by the grid/dot ratio as requested. Default 0.55.
2. **On a number/letter.** Drop a dot within `glyph_radius_frac × glyph_height` of a detected glyph.
   Default 0.80.
3. **Off its ideal lattice node (adjustable).** Each dot's ideal position is the nearest node of the
   refined dot lattice; drop it if the deviation exceeds `max_dev_frac × dot_pitch`. Default 0.35 —
   the primary "adjustable" knob (all three are sliders).

## GUI
Each filter has an enable checkbox + a slider. **Filter dots** runs it (re-filters live as sliders
move). Overlay: kept dots green; dropped coloured by reason — red = too close, orange = on glyph,
magenta = off-lattice — with a "Show dropped dots" toggle. Summary shows the counts + the dot pitch.
**Export filtered dots…** writes `dots_filtered.csv`:
`dot_id, x_px, y_px, keep, reason, box_i, box_j, box_number, local_fx, local_fy`
(the box tags come from the solved grid when available; filtering itself doesn't require registration).

## Validation
2.0× frame: dot pitch 40.8 px; of ~1567 dots → kept 1474, too_close 10, on_glyph 17, off_lattice 66.
The dropped dots sit on/next to glyphs and off the regular lattice; the kept set is a clean grid.
Offscreen GUI: 4 stages present, filter runs, export writes the CSV with box tags.
