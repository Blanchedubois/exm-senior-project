# Lab notebook

Raw records of bench sessions, exported from the Memo Notebooks app on the
phone used at the bench. One folder per session, newest first. The blog posts
linked in the right-hand column interpret each session.

| Session | What happened | Write-up |
|---|---|---|
| [2026-11-24 Magnify tissue gels: silicone and sticker moulds](2026-11-24-magnify-tissue-gels-silicone-and-sticker-moulds/) | The 20 November gels had not fully polymerised, so a new batch was cast two ways: five in the kit's sticker moulds and two in thick silicone rings as a control. Each mould got dried 2 µm Nile Red beads (1:100 stock) before the gelling solution. Clamping the sticker moulds introduced bubbles and was abandoned; two or three of the five have bubbles. Dishes sealed with parafilm, 15 min in the fridge, then 37 °C for 1.5 h, then 4 °C overnight. Bubbles in one silicone-ring gel still moved at the end, so it may not be fully set. Homogenisation and expansion planned for 25 November | not yet written up |
| [2026-11-20 Magnify tissue kit: gels preparation](2026-11-20-magnify-tissue-kit-gels-preparation/) | Cast four thin gels from the Magnify tissue kit on its adhesive spacers, sandwiched between coverslips; incubated and refrigerated for expansion on 23 November | [Thin-spacer gels post](../blog/2026-11-20-magnify-tissue-kit-gels-thin-spacers.md) |
| [2026-11-19 Magnify kit: expansion to 11× with de-ionised water](2026-11-19-magnify-kit-expansion-to-11x-with-di-water/) | Planned PBS then de-ionised water expansion of the three leftover gels; found them dried out, cleaned up | [Dried gels post](../blog/2026-11-19-magnify-di-water-attempt-gels-dried.md) |
| [2026-11-16 Magnify gels: homogenisation and expansion](2026-11-16-magnify-gels-homogenization-and-expansion/) | Homogenised three of the second-batch gels and expanded them in PBS and water; ruler measurements | [Second batch post](../blog/2026-11-17-magnify-second-batch-coverslip-sandwich.md) |
| [2026-11-10 Magnify gels: preparation](2026-11-10-magnify-gels-preparation/) | Cast six bead gels from the Magnify kit, each sandwiched between coverslips | [Second batch post](../blog/2026-11-17-magnify-second-batch-coverslip-sandwich.md) |
| [2026-11-04 Magnify kit: preparation and imaging](2026-11-04-magnify-kit-preparation-and-imaging/) | First four Magnify bead gels, homogenised and not, 1× and nominal 11×; imaged on the IX83 at 561 nm | [First batch post](../blog/2026-11-09-magnify-kit-bead-gels.md) |

## What is in a session folder

- `entry.md`: the notes in reading order, with timestamps. Start here.
- `entry.json`: the authoritative record: sections, clips, wall-clock times, place, markers.
- `transcript.draft.txt` and `transcripts/*.draft.json`: the phone's speech-to-text
  of each voice clip, uncorrected. `transcript.pasted.txt` is a cleaned transcript where one was made.
- `images/`: photos taken during the session.
- `manifest.json`, `checksums.txt`, `README.txt`: the export's own bookkeeping.

The raw voice recordings (`audio/` and `page.m4a`) are not committed; they stay
with the original exports. The checksums file still lists them.
