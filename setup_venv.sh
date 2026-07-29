#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Error: Python is not installed or not on PATH." >&2
  exit 1
fi

# Create the virtual environment in .venv
$PYTHON -m venv .venv

# Activate and install dependencies
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cat <<'EOF'
Virtual environment created successfully.
Activate it with:
  source .venv/bin/activate
Run the crawler with:
  python main.py
EOF
