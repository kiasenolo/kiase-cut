#!/bin/bash
# Build the APK, install it on the connected device, start KiaseCut and show what python says. Without arguments the
# build is the quick one (python-only changes are about a minute); `log` only shows the log again.
APP=io.github.kiasenolo.kiasecut
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "$1" != "log" ]; then
    "$HERE/build_apk.sh" > /tmp/kiasecut-apk-build.log 2>&1 || { tail -30 /tmp/kiasecut-apk-build.log; exit 1; }
    grep -q "BUILD EXIT: 0" /tmp/kiasecut-apk-build.log || { tail -30 /tmp/kiasecut-apk-build.log; exit 1; }
    adb install -r /mnt/kstore/kiasecut-android/kiasecut-0.1-arm64-v8a-debug.apk | tail -1
    adb logcat -c
    adb shell am force-stop $APP
    adb shell am start -n $APP/org.kivy.android.PythonActivity > /dev/null
    sleep "${WAIT:-12}"
fi
adb logcat -d -s python:I | sed 's/^.*python  : //' | tail -"${LINES_SHOWN:-60}"
adb logcat -d | grep "F libc\|AndroidRuntime" | tail -5
