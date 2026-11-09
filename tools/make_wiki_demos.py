"""Draw the 說明 Wiki's demo pictures now (the program does it by itself when they are missing or out of date; see kiasecut/wikibuild.py).

    python tools/make_wiki_demos.py [--sheet out.png] [filter ref ...]      (no refs: all of them)

Needs OpenGL (as the program does). The pictures go to wikidemo.cache_dir()."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import wikibuild  # noqa: E402

if __name__ == "__main__":
    sys.exit(wikibuild.main(["--force"] + sys.argv[1:]))
