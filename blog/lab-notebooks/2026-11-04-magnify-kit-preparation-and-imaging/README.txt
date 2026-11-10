Memo Notebooks bundle
=====================

manifest.json lists every page in this bundle. Each page folder has entry.json (the
authoritative record: sections in order, every clip with wall-clock start/end, time zone,
place, markers), the original clips under audio/ in page order, page.m4a (all clips of the
page joined into one recording) and page.segments.json, which maps any second of page.m4a
back to the clip and wall-clock time it came from. entry.md is a human-readable rendering.

Transcribe page.m4a and use page.segments.json to attach timestamps; or transcribe the
clips one by one. Put your transcript next to entry.json as transcript.json and the app
will import it the next time this bundle is opened on the phone. Either shape works:

  { "engine": "whisper-large-v3", "segments": [ { "start": 0.0, "end": 2.8, "text": "…" } ] }
    times in seconds of page.m4a; the app maps them back to clips.
  { "clips": [ { "clipId": "<id from entry.json>", "segments": [ … ] } ] }
    times in seconds of each clip file.

Imported transcripts replace the phone's draft on screen; the draft is kept.

transcripts/*.draft.json are the phone's own drafts. transcripts/*.corrected.json are
transcripts the user corrected on the phone: "corrected": true, and every changed phrase keeps
what was heard in "original". transcript.corrected.txt replaces transcript.draft.txt when a
page has corrections. The app never imports either kind as a desktop transcript.

vocabulary.json (notebook exports) lists the words the user corrects: each "term" is the
right spelling and "heardAs" what the recogniser wrote instead. A desktop transcriber can
pass the terms as hints or apply the same corrections.