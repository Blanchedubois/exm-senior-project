#!/usr/bin/env python3
"""Launch the Pairing & Strain GUI:  python run.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # our packages win
from app.main import main

if __name__ == "__main__":
    main()
