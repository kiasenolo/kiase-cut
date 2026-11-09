"""Draw the 說明 Wiki's demo pictures (kiasecut/wikiimg/): every node run on a sample picture by the real filter engine.

    python tools/make_wiki_demos.py [filter ref ...]      (no refs: all of them)
    python tools/make_wiki_demos.py --sheet out.png ...   (also one picture of all that were drawn, to look them over)

Needs OpenGL (as the program does). Run it again after a filter changes."""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402

from kiasecut import fx, wiki, wikidemo  # noqa: E402


def main(argv):
    fx.BIG = 1 << 60                                      # (no precompile on a second context: in a program with no window it leaves the next compile failing)
    sheet = None
    if argv[:1] == ["--sheet"]:
        sheet, argv = argv[1], argv[2:]
    refs = argv or sorted(wiki.known_refs())
    eng = fx.Engine()
    os.makedirs(os.path.join(wikidemo.DIR, "_in"), exist_ok=True)
    for name, make in wikidemo.SAMPLES.items():
        wikidemo.tile(wikidemo.shown(wikidemo.premultiplied(make()))).save(os.path.join(wikidemo.DIR, "_in", name + ".jpg"), quality=86)
    rows = []
    index_path = os.path.join(wikidemo.DIR, "index.json")
    try:
        with open(index_path, encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError):
        index = {}
    for ref in refs:
        if ref == "builtin:nodes/picture":
            continue
        try:
            tiles = wikidemo.make(eng, ref)
        except Exception as exc:                          # (one filter that does not run must not stop the rest)
            print("!", ref, exc)
            continue
        folder = os.path.join(wikidemo.DIR, wikidemo.slug(ref))
        shutil.rmtree(folder, ignore_errors=True)
        index.pop(wikidemo.slug(ref), None)
        if not tiles:
            continue
        os.makedirs(folder)
        for i, (caption, img, _kind) in enumerate(tiles):
            wikidemo.tile(img).save(os.path.join(folder, f"{i}.jpg"), quality=86)
        index[wikidemo.slug(ref)] = [[c, k] for c, _img, k in tiles]
        rows.append((ref, [(c, img) for c, img, _k in tiles]))
        print(ref, len(tiles))
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=0, sort_keys=True)
    if sheet and rows:
        tw, th = 100, 56
        w = 8 * (tw + 4) + 6
        img = Image.new("RGB", (w, len(rows) * (th + 18) + 6), (30, 30, 30))
        d = ImageDraw.Draw(img)
        for r, (ref, tiles) in enumerate(rows):
            y = 6 + r * (th + 18)
            d.text((6, y), ref.replace("builtin:", ""), fill=(255, 255, 255))
            for i, (_c, t) in enumerate(tiles[:8]):
                img.paste(t.resize((tw, th)), (6 + i * (tw + 4), y + 14))
        img.save(sheet)


if __name__ == "__main__":
    main(sys.argv[1:])
