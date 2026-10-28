#!/usr/bin/env bash
# Build KiaseCut into an executable on Linux: app-build-exec/kiasecut/kiasecut (a folder
# with the program and its Python, Qt, numpy... beside it, and the render engine in
# engine/; copy the whole folder). What goes in: packaging/kiasecut.spec.
# MLT 7 and ffmpeg are not built in: the machine running it needs them installed
# (sudo apt install libmlt7 melt ffmpeg), as when run from source.
#   ./build_exec.sh
cd "$(dirname "$(readlink -f "$0")")" || exit 1

if [ ! -x .venv/bin/python ]; then
    echo "No .venv yet: run ./start_kiasecut.sh once first."
    exit 1
fi
PY=.venv/bin/python
if ! "$PY" -c "import PySide6, numpy, PIL, moderngl" 2>/dev/null; then
    "$PY" -m pip install PySide6 numpy Pillow moderngl || exit 1
fi
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
    "$PY" -m pip install pyinstaller || exit 1
fi

OUT=app-build-exec
WORK=.cache/pyinstaller
rm -rf "$OUT/kiasecut" "$OUT/kiasecut-engine" "$WORK"
"$PY" -m PyInstaller --noconfirm --clean --distpath "$OUT" --workpath "$WORK" \
    packaging/kiasecut.spec || exit 1
mv "$OUT/kiasecut-engine" "$OUT/kiasecut/engine"

command -v ffmpeg >/dev/null 2>&1 || echo "Warning: ffmpeg not found here (needed to run it)"
ldconfig -p 2>/dev/null | grep -q "libmlt-7" || echo "Warning: MLT 7 not found here (needed to run it)"
echo "Built: $PWD/$OUT/kiasecut/kiasecut"
