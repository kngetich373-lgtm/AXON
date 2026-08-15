#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [[ "${1:-}" == "--setup-venv" ]]; then
    PYTHON_BIN="${AXON_PYTHON:-$(command -v python3 || true)}"
    if [[ -z "$PYTHON_BIN" ]]; then
        echo "Python 3 is required. Install Python 3 and its venv support, then retry." >&2
        exit 1
    fi
    "$PYTHON_BIN" -m venv venv
    venv/bin/python -m pip install --upgrade pip
    venv/bin/python -m pip install -r requirements.txt
    echo "AXON virtual environment created. Start AXON with: ./run.sh"
    exit 0
fi

if [[ -n "${AXON_PYTHON:-}" ]]; then
    PYTHON_BIN="$AXON_PYTHON"
elif [[ -x venv/bin/python ]]; then
    PYTHON_BIN="venv/bin/python"
else
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
    echo "Python 3 was not found. Install it, or run ./run.sh --setup-venv after installing Python 3." >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c 'import requests, psutil, dotenv, tkinter' 2>/dev/null; then
    echo "AXON dependencies are missing for: $PYTHON_BIN" >&2
    echo "Create the documented environment with: ./run.sh --setup-venv" >&2
    echo "Or install them into this interpreter with: $PYTHON_BIN -m pip install -r requirements.txt" >&2
    exit 1
fi

exec "$PYTHON_BIN" main.py
