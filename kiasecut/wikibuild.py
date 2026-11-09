"""Draws the 說明 Wiki's demo pictures (wikidemo.DIR) with the real filter engine, in a process of its own (python -m kiasecut.wikibuild):
a big filter's first compile can freeze a process for a while (see fxthumbs), so the window must not be the one doing it.

    python -m kiasecut.wikibuild [--force] [filter ref ...]     (no refs: all of them; without --force it does nothing when the pictures are current)
    python -m kiasecut.wikibuild --sheet out.png ...            (also one picture of all that were drawn, to look them over)

The pictures go to a folder beside DIR first and replace it only when all are drawn, so the wiki never sees half of them."""
import json
import os
import shutil
import sys

from . import fx, wiki, wikidemo


def build(refs=None, log=print):
    """Draws the demos of `refs` (all when None) into wikidemo.DIR; returns [(ref, [(caption, picture)])] of what was drawn."""
    fx.BIG = 1 << 60                                      # (no precompile on a second context: in a program with no window it leaves the next compile failing)
    final = wikidemo.DIR
    work = final.rstrip("/\\") + ".new"
    shutil.rmtree(work, ignore_errors=True)
    if refs:                                              # (some only: start from what is there)
        if os.path.isdir(final):
            shutil.copytree(final, work)
    os.makedirs(os.path.join(work, "_in"), exist_ok=True)
    stamp = wikidemo.stamp()
    eng = fx.Engine()
    for name, make in wikidemo.SAMPLES.items():
        wikidemo.tile(wikidemo.shown(wikidemo.premultiplied(make()))).save(os.path.join(work, "_in", name + ".jpg"), quality=86)
    index_path = os.path.join(work, "index.json")
    try:
        with open(index_path, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError):
        index = {}
    rows = []
    for ref in refs or sorted(wiki.known_refs()):
        if ref == "builtin:nodes/picture":
            continue
        try:
            tiles = wikidemo.make(eng, ref)
        except Exception as exc:                          # (one filter that does not run must not stop the rest)
            log("!", ref, exc)
            continue
        folder = os.path.join(work, wikidemo.slug(ref))
        shutil.rmtree(folder, ignore_errors=True)
        index.pop(wikidemo.slug(ref), None)
        if not tiles:
            continue
        os.makedirs(folder)
        for i, (_caption, img, _kind) in enumerate(tiles):
            wikidemo.tile(img).save(os.path.join(folder, f"{i}.jpg"), quality=86)
        index[wikidemo.slug(ref)] = [[c, k] for c, _img, k in tiles]
        rows.append((ref, [(c, img) for c, img, _k in tiles]))
        log(ref, len(tiles))
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=0, sort_keys=True)
    with open(os.path.join(work, "stamp.txt"), "w", encoding="utf-8") as fh:
        fh.write(stamp)
    shutil.rmtree(final, ignore_errors=True)
    os.replace(work, final)
    return rows


def sheet(rows, path):
    from PIL import Image, ImageDraw
    tw, th = 100, 56
    img = Image.new("RGB", (8 * (tw + 4) + 6, len(rows) * (th + 18) + 6), (30, 30, 30))
    d = ImageDraw.Draw(img)
    for r, (ref, tiles) in enumerate(rows):
        y = 6 + r * (th + 18)
        d.text((6, y), ref.replace("builtin:", ""), fill=(255, 255, 255))
        for i, (_c, t) in enumerate(tiles[:8]):
            img.paste(t.resize((tw, th)), (6 + i * (tw + 4), y + 14))
    img.save(path)


def main(argv):
    out = None
    if argv[:1] == ["--sheet"]:
        out, argv = argv[1], argv[2:]
    force = "--force" in argv
    refs = [a for a in argv if a != "--force"]
    if not (force or refs or out) and wikidemo.current():
        return 0
    try:
        rows = build(refs or None, lambda *a: print(*a, flush=True))
    except fx.FilterError as exc:                         # (no OpenGL: the wiki is without demos)
        print(exc, file=sys.stderr)
        return 1
    if out and rows:
        sheet(rows, out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
