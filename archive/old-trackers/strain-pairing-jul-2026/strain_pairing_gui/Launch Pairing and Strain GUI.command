#!/bin/bash
# ============================================================================
# Double-click to install the required libraries (first run) and open the
# Point-Tracking GUI.
#
# IMPORTANT: this project lives in iCloud Drive. Qt (the GUI toolkit) is
# unreliable when its binaries live in iCloud (files get evicted to
# placeholders and fail to load -> "Abort trap: 6"). So the Python environment
# is created in a LOCAL folder (~/Library/Application Support), while your code
# stays here. Only the .py source is read from iCloud, which is fine.
# ============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || { echo "Cannot enter $DIR"; read -n1 -s -p "Press any key…"; exit 1; }

echo "======================================================"
echo " Pairing & Strain GUI"
echo "======================================================"

# prefer the native arm64 Homebrew Python (avoids universal2 / arch issues)
PY=""
for c in /opt/homebrew/bin/python3 python3 /usr/local/bin/python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "Python 3 not found. Install from https://www.python.org/downloads/"; read -n1 -s -p "Press any key…"; exit 1; }
echo "Python: $($PY --version 2>&1)  ($PY)"

# LOCAL virtual environment (outside iCloud); own dir so it never collides with
# the main project's point_tracking_gui environment.
VENV="$HOME/Library/Application Support/HydrogelMarkerGUI/strain_pairing_gui"
mkdir -p "$(dirname "$VENV")"

if [ ! -d "$VENV" ]; then
  echo ""
  echo "First run — creating a local environment and installing libraries."
  echo "  location: $VENV"
  echo "  (a few minutes; only happens once)"
  "$PY" -m venv "$VENV" || { echo "venv creation failed."; read -n1 -s -p "Press any key…"; exit 1; }
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  python -m pip install --upgrade pip
  if ! python -m pip install -r requirements.txt; then
    echo "Library installation failed (check your internet connection)."
    read -n1 -s -p "Press any key…"; exit 1
  fi
else
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

echo ""
echo "Launching the GUI…  (close the window to quit)"
python run.py
status=$?
if [ $status -ne 0 ]; then
  echo ""
  echo "The GUI exited with an error (code $status)."
  echo "If it crashed on start (Abort trap: 6): the surest fix is to copy this whole"
  echo "project folder OUT of iCloud Drive (e.g. to ~/Desktop) and run it from there,"
  echo "then delete $VENV so it rebuilds."
  read -n1 -s -p "Press any key to close…"
fi
