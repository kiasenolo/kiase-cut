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
# Adaptive icon: 108 dp layers at xxxhdpi (432 px); the logo is scaled so its outer radius (240 of 512) fills 4/5 of the 66 dp safe circle
rsvg-convert -w 225 "$ROOT/Icon.svg" -b none | magick png:- -background none -gravity center -extent 432x432 "$BUILD/src/Icon-fg.png"
rsvg-convert -w 432 -h 432 "$ROOT/Icon-bg.svg" -o "$BUILD/src/Icon-bg.png"
# p4a's qt bootstrap has no mipmap-anydpi-v26 folder for the adaptive icon's xml: an (empty) added resource makes it
mkdir -p "$BUILD/res-anydpi"
(cd "$ROOT" && find kiasecut -type f \( -name '*.py' -o -name '*.glsl' -o -name '*.svg' -o -name '*.md' \) -not -path '*/__pycache__/*' |
    tar -cf - -T -) | tar -xf - -C "$BUILD/src"
echo "staged $(find "$BUILD/src" -type f | wc -l) files in $BUILD/src"
