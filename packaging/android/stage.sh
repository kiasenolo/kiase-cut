#!/bin/bash
# The files of the APK's python side, copied to $1/src (default /mnt/kstore/kiasecut-android): main.py and the kiasecut
# package without its caches and tests - buildozer packs what is in that folder.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="${1:-/mnt/kstore/kiasecut-android}"
rm -rf "$BUILD/src"
mkdir -p "$BUILD/src"
cp "$HERE/main.py" "$BUILD/src/main.py"
cp "$ROOT/Icon.svg" "$BUILD/src/Icon.svg"
rsvg-convert -w 512 -h 512 "$ROOT/Icon.svg" -o "$BUILD/src/Icon.png"
(cd "$ROOT" && find kiasecut -type f \( -name '*.py' -o -name '*.glsl' -o -name '*.svg' -o -name '*.md' \) -not -path '*/__pycache__/*' |
    tar -cf - -T -) | tar -xf - -C "$BUILD/src"
echo "staged $(find "$BUILD/src" -type f | wc -l) files in $BUILD/src"
