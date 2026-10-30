import numpy as np, cv2
from PIL import Image
def detect(path, min_perim=0.01):
    im = np.array(Image.open(path)).astype(np.float32)
    lo, hi = np.percentile(im, [1, 99.9])
    g = np.clip((im - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    g = 255 - g                                   # printed bright -> black modules
    p = cv2.aruco.DetectorParameters(); p.minMarkerPerimeterRate = min_perim
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), p)
    corners, ids, _ = det.detectMarkers(g)
    return {int(i): c.reshape(4, 2).mean(0) for i, c in zip(ids.ravel(), corners)} if ids is not None else {}
if __name__ == "__main__":
    t = np.load("sim_out/truth.npz")
    for name, key in [("pre", "pre_px"), ("post", "post_px")]:
        d = detect(f"sim_out/{name}.png", 0.01 if name == "pre" else 0.003)
        tags = {int(i): t[key][k] for k, i in enumerate(t["aruco_id"]) if i >= 0}
        err = [np.hypot(*(d[i] - tags[i])) for i in d if i in tags]
        print(name, "decoded", len(d), "of 36; wrong ids", len(set(d) - set(tags)),
              "; centre error px mean %.2f max %.2f" % (np.mean(err), np.max(err)))
