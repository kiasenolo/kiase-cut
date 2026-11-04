#!/bin/bash
# Build the KiaseCut APK and put it on the tablet - one command:
#     packaging/android/install.sh            build, install (keeps the app's data), start it
#     packaging/android/install.sh --no-start build and install only
#     packaging/android/install.sh --build    build only (the APK path is printed)
# The first build of a new toolchain is long (tens of minutes); a change in python only is about a minute.
# Needs: /mnt/kstore mounted (see below), the tablet on USB with debugging on (`adb devices` shows it).
APP=io.github.kiasenolo.kiasecut
HERE="$(cd "$(dirname "$0")" && pwd)"
APK=/mnt/kstore/kiasecut-android/kiasecut-0.1-arm64-v8a-debug.apk
LOG=/tmp/kiasecut-apk-build.log

if [ ! -d /mnt/kstore/android-sdk ]; then
    echo "The toolchain drive is not mounted at /mnt/kstore. With the drive plugged in, run:"
    echo '    sudo mount --bind "/run/media/kiasenolo/GAY CAT KILO/KIASE_LINUX_STORE" /mnt/kstore'
    exit 1
fi

echo "== building (log: $LOG)"
"$HERE/build_apk.sh" > "$LOG" 2>&1
if ! grep -q "BUILD EXIT: 0" "$LOG" || [ ! -f "$APK" ]; then
    echo "The build failed; the end of the log:"
    tail -30 "$LOG"
    exit 1
fi
echo "== built: $APK ($(du -h "$APK" | cut -f1))"
[ "$1" = "--build" ] && exit 0

if ! command -v adb > /dev/null; then
    echo "adb is not installed (the Android platform tools); the APK is at $APK"
    exit 1
fi
if ! adb get-state > /dev/null 2>&1; then
    echo "No tablet found: plug it in by USB, switch on USB debugging and allow this computer, then run again"
    echo "(or copy $APK to the tablet by hand)."
    exit 1
fi
echo "== installing on $(adb shell getprop ro.product.model | tr -d '\r')"
if ! adb install -r "$APK" 2>&1 | tee /tmp/kiasecut-adb-install.log | tail -1 | grep -q Success; then
    grep -q INSTALL_FAILED_USER_RESTRICTED /tmp/kiasecut-adb-install.log &&
        echo "The tablet asked to allow the install: tap allow on it, then run again."
    cat /tmp/kiasecut-adb-install.log
    exit 1
fi
if [ "$1" != "--no-start" ]; then
    adb shell am force-stop $APP
    adb shell am start -n $APP/org.kivy.android.PythonActivity > /dev/null
    echo "== started"
fi
echo "(files: the app needs 'all files access' in its settings page; log: packaging/android/run_on_tablet.sh log)"
