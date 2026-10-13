import numpy as np, cv2
from cv2 import aruco

def scan(dict_name, n_modules, n_ids):
    d = aruco.getPredefinedDictionary(getattr(aruco, dict_name))
    solid, conj = [], []
    for i in range(n_ids):
        img = aruco.generateImageMarker(d, i, n_modules, 1)
        m = (img < 128).astype(np.uint8)
        n4 = cv2.connectedComponents(m, connectivity=4)[0]-1
        n8 = cv2.connectedComponents(m, connectivity=8)[0]-1
        if n8 == 1:
            conj.append(i)
            if n4 == 1: solid.append(i)
    return conj, solid

print(f"{'dictionary':<18}{'modules':>8}{'IDs':>7}{'8-conn (strutted)':>20}{'4-conn (solid)':>17}")
for name, mods, n in (("DICT_4X4_50",6,50), ("DICT_4X4_100",6,100),
                      ("DICT_4X4_250",6,250), ("DICT_4X4_1000",6,1000),
                      ("DICT_5X5_250",7,250), ("DICT_6X6_1000",8,1000)):
    try:
        c, s = scan(name, mods, n)
        print(f"{name:<18}{mods:>8}{n:>7}{len(c):>20}{len(s):>17}")
    except Exception as e:
        print(f"{name:<18} ERROR {e}")
print("\nnodes needed: 5x5 boxes -> 36 ; 8x8 -> 81 ; 10x10 -> 121")
