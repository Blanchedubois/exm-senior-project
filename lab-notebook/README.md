# Lab notebook

Raw records of bench sessions, exported from the Memo Notebooks app on the
phone used at the bench. One folder per session, newest first. The blog posts
linked in the right-hand column interpret each session.

| Session | What happened | Write-up |
|---|---|---|
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
