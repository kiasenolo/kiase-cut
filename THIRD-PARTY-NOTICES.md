# Third-party notices / 第三方授權

KiaseCut itself is free software under GPL-3.0-or-later (`LICENSE`). This file lists what an
executable or AppImage of KiaseCut carries besides its own code, and what it uses without
carrying. Hand this file and the `LICENSES/` folder on with every build.
KiaseCut 本身是 GPL-3.0-or-later（見 `LICENSE`）。這份清單列出打包版（執行檔 / AppImage）裡一起帶著的第三方元件，
以及只是「使用、沒有帶著」的元件。發行打包版時請連同 `LICENSES/` 資料夾一起附上。

## Carried inside the executable / AppImage 打包進去的

| Component | Version built with (Linux / Windows) | License | Text |
|---|---|---|---|
| PySide6 / shiboken6 (Qt for Python) | 6.12 | LGPL-3.0-only (or GPL-2.0 / GPL-3.0) | `LICENSES/LGPL-3.0-or-later.txt` |
| Qt 6 (its libraries and plugins, inside the PySide6 wheels) | 6.12 | LGPL-3.0 | same |
| FFmpeg libraries inside Qt (libavcodec, libavformat, libswscale ...) | by Qt | LGPL-2.1-or-later | `LICENSES/LGPL-3.0-or-later.txt` (LGPL-2.1 allows LGPL-3) |
| ICU (inside Qt, Linux build) | 73 | Unicode License (ICU) | <https://github.com/unicode-org/icu/blob/main/icu4c/LICENSE> |
| Python (the interpreter and standard library) | 3.14 / 3.15 | PSF-2.0 | `LICENSES/third-party/Python-PSF-2.0.txt` |
| numpy (with the libraries in its wheel) | 2.5 | BSD-3-Clause and others | `LICENSES/third-party/numpy/` |
| Pillow | 13.0 | MIT-CMU | `LICENSES/third-party/Pillow-LICENSE.txt` |
| moderngl | 5.13 | MIT | `LICENSES/third-party/moderngl-LICENSE.txt` |
| glcontext | 3.1 | MIT | `LICENSES/third-party/glcontext-LICENSE.txt` |
| Breeze icons (`kiasecut/look/icons/`, KDE) | 6.30 | LGPL-3.0-or-later | `LICENSES/LGPL-3.0-or-later.txt` |
| Shaders from Blender (`kiasecut/filters/`) | 5.2 | GPL-2.0-or-later / CC0 (Blender Studio assets) | `LICENSES/GPL-2.0-or-later.txt`, `LICENSES/CC0-1.0.txt` |
| KiaseCut's hand-drawn logo, icons, demo pictures | — | CC-BY-4.0, © 2026 KIASENOLO | `LICENSES/CC-BY-4.0.txt` |

### Qt and LGPL: replacing the library 更換 Qt 函式庫

Qt and PySide6 are LGPL-3.0 and are carried as separate shared libraries (`.so` / `.dll`), not
merged into the program. You may replace them with another build of the same Qt / PySide6
version: unpack the AppImage (`./KiaseCut.AppImage --appimage-extract`) or open the Windows
folder, and swap the files in `PySide6/`. The source of Qt and PySide6 is at
<https://code.qt.io/> and <https://pypi.org/project/PySide6/>.
Qt 與 PySide6 是以獨立的動態函式庫帶著，可以自行換成同版本的其他建置；原始碼見上面的連結。

## Used, not carried 使用但沒有帶著

These are not part of KiaseCut's download. The user installs them, and KiaseCut loads or runs them
as they are; their own licenses apply to them.
這些不在 KiaseCut 的下載裡，由使用者自己安裝，KiaseCut 載入或呼叫它們。

| Program | Used for | License |
|---|---|---|
| MLT 7 (`libmlt-7`) | the render engine | LGPL-2.1-or-later (some plugins GPL) |
| FFmpeg (`ffmpeg`) | export, video previews | LGPL-2.1+ or GPL, by build |
| Kdenlive / Shotcut | on Windows, the usual source of MLT and FFmpeg | GPL |

An executable built with `build_exec.bat --bundle-mlt` also carries Kdenlive's MLT, Qt and
FFmpeg: its licenses (Kdenlive's `share/` folder) must go with it, and if that FFmpeg is a GPL
build, the whole download is GPL (KiaseCut already is).
