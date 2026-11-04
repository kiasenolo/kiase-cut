[app]
title = KiaseCut
package.name = kiasecut
package.domain = io.github.kiasenolo
source.dir = src
source.include_exts = py,glsl,svg,md
version = 0.1
requirements = python3,shiboken6,PySide6,numpy,pillow
orientation = landscape
fullscreen = 0
android.archs = arm64-v8a
android.add_libs_arm64_v8a = libs/arm64-v8a/*.so
android.allow_backup = True
android.ndk_path = /mnt/kstore/android-sdk/ndk/28.2.13676358
android.sdk_path = /mnt/kstore/android-sdk
android.api = 35
android.minapi = 28
android.ndk_api = 28
android.no-byte-compile-python = True
p4a.bootstrap = qt
p4a.local_recipes = /mnt/kstore/kiasecut-android/deployment/recipes
p4a.branch = master
p4a.commit = 58d21141f17c889bf8585f5665921d72028f8831
android.permissions = android.permission.MANAGE_EXTERNAL_STORAGE, android.permission.READ_EXTERNAL_STORAGE, android.permission.WRITE_EXTERNAL_STORAGE, android.permission.READ_MEDIA_VIDEO, android.permission.READ_MEDIA_IMAGES, android.permission.READ_MEDIA_AUDIO, android.permission.INTERNET, android.permission.VIBRATE
android.add_jars = /mnt/kstore/kiasecut-android/deployment/jar/PySide6/jar/Qt6AndroidBindings.jar,/mnt/kstore/kiasecut-android/deployment/jar/PySide6/jar/Qt6Android.jar,/mnt/kstore/kiasecut-android/deployment/jar/PySide6/jar/Qt6AndroidMultimedia.jar
p4a.extra_args = --qt-libs=Core,Widgets,Gui,Svg,Multimedia --load-local-libs=plugins_platforms_qtforandroid,plugins_imageformats_qjpeg,plugins_imageformats_qsvg,plugins_imageformats_qwebp,plugins_imageformats_qgif,plugins_multimedia_androidmediaplugin --init-classes=
icon.filename = /mnt/kstore/kiasecut-android/src/Icon.png

[buildozer]
log_level = 2
warn_on_root = 1
bin_dir = /mnt/kstore/kiasecut-android
