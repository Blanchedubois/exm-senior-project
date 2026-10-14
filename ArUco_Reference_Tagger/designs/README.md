# Design registry

Copies of the four spacing-workshop designs from `ArUco_Tracker_V2/designs/`, so the app does
not depend on that folder being present. Each holds `reference_tags.json` (every printed
feature's tag and design position), `spec_sheet.json` and `ids.json`. Byte-identical to the
originals as of 2026-10-14; the app records each file's SHA-256 with every detection.

| folder | design | dot | spacing | dots |
|---|---|---|---|---|
| `1_optimistic` | Optimistic | 2.125 µm | 5.0 µm | 17,825 |
| `2_medium` | Medium | 2.125 µm | 6.0 µm | 11,700 |
| `3_conservative` | Conservative | 2.125 µm | 7.0 µm | 8,000 |
| `4_spectrum` | Spectrum test print | 2.125–4 µm, per box | 5–8.875 µm, per box | 9,244 |

Any other design folder with a `reference_tags.json` can be loaded from the Detect tab.
