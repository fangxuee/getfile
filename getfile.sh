#!/usr/bin/env bash
set -e

# Check for Python 3
if ! command -v python3 &>/dev/null; then
  echo "Python 3 is not installed. Please install Python 3."
  exit 1
fi

# Check for pip
if ! command -v pip3 &>/dev/null; then
  echo "pip is not installed. Please install pip for Python 3."
  exit 1
fi

echo "Checking dependencies..."
if ! python3 -m pip show requests >/dev/null 2>&1 || ! python3 -m pip show rich >/dev/null 2>&1; then
  echo "Installing dependencies..."
  python3 -m pip install --quiet --upgrade pip >/dev/null 2>&1
  python3 -m pip install --quiet -r requirements.txt >/dev/null 2>&1
fi

# Run the script (output visible)
exec python3 getfile.py "$@"