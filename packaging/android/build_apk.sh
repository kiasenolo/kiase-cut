#!/bin/bash
# Build the KiaseCut debug APK: stage the python side, then buildozer (not pyside6-android-deploy, which overwrites the
# requirements). The toolchain lives on /mnt/kstore (see the notes in the project's memory); the build folder must stay
# at that path, python-for-android writes absolute paths into its build.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD=/mnt/kstore/kiasecut-android
"$HERE/stage.sh" "$BUILD"
cp "$HERE/buildozer.spec" "$BUILD/buildozer.spec"
mkdir -p "$BUILD/deployment" && rm -rf "$BUILD/deployment/recipes" && cp -r "$HERE/recipes" "$BUILD/deployment/recipes"     # (p4a.local_recipes: PySide6 + shiboken6 from the wheels in /mnt/kstore/wheels, numpy 2.3.5)
export VIRTUAL_ENV=/mnt/kstore/venv-android PATH=/mnt/kstore/venv-android/bin:$PATH
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk GRADLE_USER_HOME=/mnt/kstore/gradle-home PIP_CACHE_DIR=/mnt/kstore/pip-cache
export ANDROID_SDK_ROOT=/mnt/kstore/android-sdk ANDROID_HOME=/mnt/kstore/android-sdk
# what the spec points at inside the build folder: Qt's Java side (jars out of the PySide6 wheel) and the ffmpeg programs
[ -f "$BUILD/deployment/jar/PySide6/jar/Qt6AndroidBindings.jar" ] || unzip -o -q /mnt/kstore/wheels/pyside6-*.whl 'PySide6/jar/*' -d "$BUILD/deployment/jar"
mkdir -p "$BUILD/libs/arm64-v8a" && cp /mnt/kstore/ffmpeg-build/out/arm64-v8a/*.so "$BUILD/libs/arm64-v8a/"
# the sound effects' C library, with the NDK's compiler (loaded as "libkcdsp.so": kiasecut/dsp)
NDK=$(sed -n 's/^android.ndk_path = //p' "$HERE/buildozer.spec")
CLANG=$(ls "$NDK"/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android28-clang)
"$CLANG" -std=c11 -O3 -fno-math-errno -shared -fPIC -fvisibility=hidden -Wl,-z,max-page-size=16384 \
    -o "$BUILD/libs/arm64-v8a/libkcdsp.so" "$HERE"/../../kiasecut/dsp/src/*.c -lm
rm -rf "$BUILD/javasrc" && cp -r "$HERE/java" "$BUILD/javasrc"          # (android.add_src: the Java side, SystemBars)
cd "$BUILD"
buildozer -v android debug < /dev/null
echo "BUILD EXIT: $?"
