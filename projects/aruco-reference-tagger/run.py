#!/usr/bin/env python3
"""Launch the ArUco Reference Tagger:  python run.py [project.rwproj.json]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gui.app import main

if __name__ == "__main__":
    main()
