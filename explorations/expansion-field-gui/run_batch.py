#!/usr/bin/env python3
"""Headless batch runner. Example:

    python run_batch.py --initial init.tif --expansions e2.tif e3.tif --out OUT \
        --vig-strength 0.88 --vig-power 1.8 --k1 -0.05 --k2 -0.01
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fieldkit.cli import main

if __name__ == "__main__":
    main()
