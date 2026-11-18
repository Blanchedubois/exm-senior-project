#!/bin/bash
# Launcher script for Strain Gauge Analyzer

echo "Starting Strain Gauge Analyzer..."
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Check if required packages are installed
echo "Checking dependencies..."
python3 -c "import numpy, pandas, matplotlib, scipy" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing required packages..."
    pip3 install -r requirements.txt
fi

echo ""
echo "Launching application..."
python3 strain_gauge_analyzer.py
