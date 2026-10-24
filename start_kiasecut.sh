#!/usr/bin/env bash
# Start KiaseCut on Linux. The first run installs the Python packages into .venv beside
# this file (system Pythons refuse a plain pip install). Arguments go on to the program:
#   ./start_kiasecut.sh [project.kiasecut.json | draft_content.dec.json]
cd "$(dirname "$(readlink -f "$0")")" || exit 1

PY=""
for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        PY="$c"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Python 3.11+ not found. Install it, e.g.: sudo apt install python3 python3-venv"
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Setting up .venv (first run only)..."
    if ! "$PY" -m venv .venv; then
        echo "Could not make a virtual environment. Install venv, e.g.: sudo apt install python3-venv"
        rm -rf .venv
        exit 1
    fi
fi
if ! .venv/bin/python -c "import PySide6, numpy, PIL, moderngl" 2>/dev/null; then
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install PySide6 numpy Pillow moderngl || exit 1
fi

# needed for export and video previews: say so now rather than at the first export
command -v ffmpeg >/dev/null 2>&1 || echo "Warning: ffmpeg not found (sudo apt install ffmpeg)"
if [ -z "$KIASECUT_MLT" ] && ! ldconfig -p 2>/dev/null | grep -q "libmlt-7"; then
    echo "Warning: MLT 7 not found (sudo apt install libmlt7 / melt, or set KIASECUT_MLT)"
fi

exec .venv/bin/python -m kiasecut "$@"
