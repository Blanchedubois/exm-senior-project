# Blog draft: IX83 progress post

Draft for the project log in `MarkersTracker PythonScript/blog/` (GitHub: Blanchedubois/aruco-reference-tagger). Nothing here is in that repo until it's approved.

- `2026-11-03-learning-the-ix83.md`: the post.
- `images/`: placeholder images from a test export. Replace them with your own export:

```bash
# 0. In the viewer, select 488-Sample1-34.2x-100cts-400ms_1 and set Info ▸ Expansion to 4.2 (the name's "34.2x" is a typo)
# 1. Side by side ▸ Export panels… with everything ticked (single frame 0 for expanded sets, dark frame,
#    without 633, grayscale, inferno, comparison)
# 2. Convert your exported panels into the draft's images:
python3 tools/prepare_blog_images.py "../../Experimentation/IX83 Data/Exports/16Oct26/panels" blog_draft/images --date 2026-11-03 --extra E:gray
```

`images/2026-11-03-ix83-viewer.webp` is a screenshot of the viewer, not an export, so it is kept as is. The script also writes a few panels the post doesn't use (e.g. `set-b-1x-no633`); only the images the post links to will be copied into the blog.
