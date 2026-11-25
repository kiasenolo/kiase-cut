#!/usr/bin/env python3
"""Make a ready-made sound library, for where there is no compiler:

    python tools/build_dsp.py windows      kiasecut/dsp/bin/windows-x86_64/kcdsp.dll (MinGW-w64; commit it)
    python tools/build_dsp.py              this computer's, into kiasecut/dsp/bin/<platform>/

Run it again after changing kiasecut/dsp/src/: a stamp beside the library says which sources
it was made from, and tests/test_dsp.py fails while the committed one is behind.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kiasecut import dsp  # noqa: E402


def main(argv):
    windows = argv == ["windows"] or (not argv and sys.platform == "win32")
    if argv not in ([], ["windows"]):
        print(__doc__)
        return 2
    cc = None
    if windows and sys.platform != "win32":
        cc = shutil.which("x86_64-w64-mingw32-gcc")
        if not cc:
            print("x86_64-w64-mingw32-gcc not found")
            return 1
    tag = "windows-x86_64" if windows else dsp.platform_tag()
    out = os.path.join(dsp.HERE, "bin", tag, "kcdsp" + (".dll" if windows else dsp.SUFFIX))
    dsp.compile_to(out, cc, windows)
    with open(out + ".stamp", "w", encoding="ascii") as f:
        f.write(dsp._stamp() + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
