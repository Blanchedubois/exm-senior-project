#!/usr/bin/env python3
"""Launch the Reference-Warp Tagger (Stage 1):  python run.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gui.app import main

if __name__ == "__main__":
    main()
