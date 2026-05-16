#!/usr/bin/env sh
# Install modeling dependencies into modeling/.venv using the interpreter's pip module
# (no global `pip` command required: python3 -m venv bundles pip inside .venv).

set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH. Install Python 3.9+ (e.g. from python.org or Homebrew) and retry." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# Upgrade pip inside the venv (venv ships with pip; `python -m pip` works even when `pip` is not global).
.venv/bin/python -m pip install -U pip wheel
.venv/bin/python -m pip install -r requirements.txt

echo "Done. Run modeling with:"
echo "  .venv/bin/python preakness_modeling.py"
