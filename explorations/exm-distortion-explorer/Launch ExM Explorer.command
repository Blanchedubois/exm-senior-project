#!/bin/bash
# ============================================================================
# Double-click to install the required libraries (first run) and open the
# ExM Distortion Explorer.
#
# This project lives in iCloud Drive, and Qt is unreliable when its binaries
# live in iCloud (files get evicted -> "Abort trap: 6"). So the Python
# environment is created in a LOCAL folder (~/Library/Application Support);
# only the .py source is read from iCloud.
#
# Optional argument: a scenario JSON to open, e.g.
#   ./"Launch ExM Explorer.command" my_scenario.json
# ============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || { echo "Cannot enter $DIR"; read -n1 -s -p "Press any key…"; exit 1; }

echo "======================================================"
echo " ExM Distortion Explorer"
echo "======================================================"

# prefer the native arm64 Homebrew Python (3.11 or newer)
PY=""
for c in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    PY="$c"; break
  fi
done
[ -z "$PY" ] && { echo "Python 3.11+ not found. Install it with: brew install python@3.12"; read -n1 -s -p "Press any key…"; exit 1; }
echo "Python: $($PY --version 2>&1)  ($PY)"

VENV="$HOME/Library/Application Support/HydrogelMarkerGUI/exm_explorer"
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
  if ! python -m pip install -e ".[test]"; then
    echo "Library installation failed (check your internet connection)."
    read -n1 -s -p "Press any key…"; exit 1
  fi
else
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

echo ""
echo "Launching…  (close the window to quit)"
python -m exm_explorer "$@"
status=$?
if [ $status -ne 0 ]; then
  echo ""
  echo "The explorer exited with an error (code $status)."
  echo "If it crashed on start (Abort trap: 6): copy this project folder OUT of"
  echo "iCloud Drive (e.g. to ~/Desktop), run it from there, and delete"
  echo "$VENV so it rebuilds."
  read -n1 -s -p "Press any key to close…"
fi
