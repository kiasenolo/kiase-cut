#!/usr/bin/env bash
# Build KiaseCut into one file on Linux: app-build-exec/KiaseCut-<version>-x86_64.AppImage.
# It runs ./build_exec.sh first (unless --no-build: use the folder it made before), puts
# that folder into an AppDir and packs it with appimagetool.
# MLT 7 and ffmpeg are not inside: the machine running it needs them (as for the folder).
# appimagetool: found on PATH, or named in $APPIMAGETOOL; get it from
#   https://github.com/AppImage/appimagetool/releases  (AUR: appimagetool-bin)
# With no appimagetool the AppDir is still made (app-build-exec/KiaseCut.AppDir) and tested by hand.
#   ./build_appimage.sh [--no-build]
cd "$(dirname "$(readlink -f "$0")")" || exit 1

OUT=app-build-exec
APPDIR="$OUT/KiaseCut.AppDir"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' kiasecut/__init__.py)

if [ "$1" != "--no-build" ]; then
    ./build_exec.sh || exit 1
fi
if [ ! -x "$OUT/kiasecut/kiasecut" ]; then
    echo "No $OUT/kiasecut/kiasecut: run without --no-build."
    exit 1
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp -a "$OUT/kiasecut" "$APPDIR/usr/lib/kiasecut"
cp images/app-Icon.svg "$APPDIR/kiasecut.svg"
cp images/app-Icon.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/kiasecut.svg"
ln -s kiasecut.svg "$APPDIR/.DirIcon"

cat > "$APPDIR/kiasecut.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=KiaseCut
Comment=Video editor
Exec=kiasecut %f
Icon=kiasecut
Terminal=false
Categories=AudioVideo;Video;AudioVideoEditing;
StartupWMClass=kiasecut
EOF
cp "$APPDIR/kiasecut.desktop" "$APPDIR/usr/share/applications/"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/kiasecut/kiasecut" "$@"
EOF
chmod +x "$APPDIR/AppRun"

command -v ffmpeg >/dev/null 2>&1 || echo "Warning: ffmpeg not found here (needed to run it)"

TOOL="${APPIMAGETOOL:-$(command -v appimagetool)}"
if [ -z "$TOOL" ]; then
    echo "appimagetool not found: AppDir made at $PWD/$APPDIR (run it with $APPDIR/AppRun)."
    echo "Get appimagetool (see the top of this file), then: ./build_appimage.sh --no-build"
    exit 0
fi
FILE="$OUT/KiaseCut-$VERSION-x86_64.AppImage"
rm -f "$FILE"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$FILE" 2>&1 || ARCH=x86_64 "$TOOL" "$APPDIR" "$FILE" || exit 1
echo "Built: $PWD/$FILE"
