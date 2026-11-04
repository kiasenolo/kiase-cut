#!/bin/bash
# Build the KiaseCut debug APK: stage the python side, then buildozer (not pyside6-android-deploy, which overwrites the
# requirements). The toolchain lives on /mnt/kstore (see the notes in the project's memory); the build folder must stay
# at that path, python-for-android writes absolute paths into its build.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD=/mnt/kstore/kiasecut-android
"$HERE/stage.sh" "$BUILD"
cp "$HERE/buildozer.spec" "$BUILD/buildozer.spec"
export VIRTUAL_ENV=/mnt/kstore/venv-android PATH=/mnt/kstore/venv-android/bin:$PATH
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk GRADLE_USER_HOME=/mnt/kstore/gradle-home PIP_CACHE_DIR=/mnt/kstore/pip-cache
export ANDROID_SDK_ROOT=/mnt/kstore/android-sdk ANDROID_HOME=/mnt/kstore/android-sdk
cd "$BUILD"
buildozer -v android debug < /dev/null
echo "BUILD EXIT: $?"
