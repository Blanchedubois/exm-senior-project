"""
Headless tests for rwtag.project (multi-image workspace model). No Qt.
"""
from __future__ import annotations
import os
import sys
import glob
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rwtag import project as P

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL = os.path.join(_ROOT, "reference", "glyph_knn.yml")
_STITCHED = os.path.join(_ROOT, "Stitched Images")


def test_initial_auto_lowest_and_override():
    proj = P.Project(folder="/tmp")
    a = proj.add("/tmp/2.0Xb.tif", 2.0)
    b = proj.add("/tmp/1.5Xa.tif", 1.5)
    c = proj.add("/tmp/3.0Xc.tif", 3.0)
    assert proj.initial() is b and b.role == "initial"          # lowest label wins
    assert [e.label for e in proj.expanded()] == [2.0, 3.0]
    proj.set_initial(c)                                          # manual override
    assert proj.initial() is c and b.role == "expanded"
    proj.remove(c)                                               # falls back to lowest
    assert proj.initial() is b


def test_project_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        img = os.path.join(d, "1.5Xx.tif")
        open(img, "w").close()
        proj = P.Project(folder=d)
        e = proj.add(img, 1.5)
        e.glyph_manual["numbers"].append(((2, 3), 13))
        e.glyph_manual["letters"].append({"box": [1, 1], "x": 5.0, "y": 6.0, "char": "A"})
        path = proj.save()
        assert os.path.basename(path) == P.PROJECT_NAME
        p2 = P.Project.load(path)
        assert len(p2.images) == 1
        e2 = p2.images[0]
        assert e2.label == 1.5 and e2.role == "initial"
        assert os.path.abspath(e2.path) == os.path.abspath(img)   # relative path resolved
        assert e2.glyph_manual["numbers"] == [((2, 3), 13)]


def test_stage_status_progression():
    e = P.ImageEntry(path="/nonexistent/2.0X.tif", label=2.0)
    assert e.stage_status() == (False, False, False, False)


def test_run_stages_real_frame():
    files = sorted(glob.glob(os.path.join(_STITCHED, "2.0X*.tif")))
    if not files or not os.path.exists(_MODEL):
        print("  SKIP  test_run_stages_real_frame (no data/model)"); return
    from rwtag.glyph import detect as D
    clf = D.load_classifier(_MODEL)
    e = P.ImageEntry(path=files[0], label=2.0)
    ok, msg = P.run_stages(e, clf)
    assert ok, msg
    s1, s2, s3, s4 = e.stage_status()
    assert s1 and s2 and s3 and s4, e.stage_status()
    assert len(e.pipeline.tagging.tags) > 1000
    assert e.pipeline.tagging.label == 2.0
    # unload drops heavy arrays but keeps results; ensure_loaded restores images
    e.unload_images()
    assert e.pipeline.raw_image is None and e.pipeline.tagging is not None
    e.ensure_loaded()
    assert e.pipeline.corrected_image is not None
    print(f"  info  run_stages: {msg}")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            fails += 1; print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:
            fails += 1; print(f"  ERR   {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
