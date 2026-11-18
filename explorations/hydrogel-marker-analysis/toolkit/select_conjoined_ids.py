#!/usr/bin/env python3
"""
select_conjoined_ids.py  (Deliverable 1)
========================================
Produce the list of ArUco IDs (DICT_6X6_1000) that can be CONJOINED into a
single rigid marker, for the generator scripts to consume.

An ID is usable if its black is a single 8-connected component: every black
piece touches at least at a corner, so smooth diagonal struts bridge them into
one connected piece. IDs whose black is already single 4-connected need no
struts at all.

Writes conjoined_marker_ids.json:
  { dict, n_scanned,
    conjoinable_ids : [...]   # USE THESE (one rigid piece once strutted)
    solid_no_struts : [...]   # subset needing no struts
    needs_struts    : [...] } # subset that struts convert to one piece
"""
import json
from conjoined_lib import scan_conjoinable

if __name__ == "__main__":
    data = scan_conjoinable(1000)
    with open("conjoined_marker_ids.json", "w") as f:
        json.dump(data, f, indent=1)
    print(f"{data['dict']}: scanned {data['n_scanned']} IDs")
    print(f"  conjoinable (USE THESE): {len(data['conjoinable_ids'])}")
    print(f"  already solid (no struts): {len(data['solid_no_struts'])}")
    print(f"  need struts to conjoin   : {len(data['needs_struts'])}")
    print(f"  first 20 conjoinable IDs : {data['conjoinable_ids'][:20]}")
    print("  -> conjoined_marker_ids.json")
