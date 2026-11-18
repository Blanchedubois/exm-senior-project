#!/usr/bin/env python3
"""Launch the point-tracking GUI:  python run.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.main import main

if __name__ == "__main__":
    main()
