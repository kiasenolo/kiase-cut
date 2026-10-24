"""Golden test: import a Jianying draft, export it with KiaseCut, compare with Jianying's export.

  python tools/golden.py DRAFT.json REFERENCE.mp4 OUT_DIR [--remap OLD=NEW] [--max-mean 3]
  python tools/golden.py --compare-only EXPORT.mp4 REFERENCE.mp4 OUT_DIR

Frames are sampled every 1.5 s plus densely around animated masks and compound clips;
each sample's score is the mean over pixels of the max channel difference (0-255).
Exits non-zero when any frame exceeds --max-mean.
"""
import argparse
import os
import statistics
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def grab(src, frame, fps, dst):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{frame / fps - 0.005:.4f}", "-i", src,
                    "-frames:v", "1", dst], check=True)
    return np.asarray(Image.open(dst).convert("RGB")).astype(np.int16)


def sample_times(duration_s, dense=()):
    ts = {round(0.4 + 1.5 * i, 2) for i in range(int((duration_s - 0.4) / 1.5) + 1)}
    for a, b in dense:
        ts |= {round(t, 2) for t in np.arange(a, b, 0.1)}
    return sorted(t for t in ts if t < duration_s)


def compare(export, ref, out, fps, times):
    os.makedirs(out, exist_ok=True)
    rows = []
    for t in times:
        f = round(t * fps)
        r = grab(ref, f, fps, os.path.join(out, f"r_{f:05d}.png"))
        m = grab(export, f, fps, os.path.join(out, f"m_{f:05d}.png"))
        d = np.abs(r - m).max(axis=2)
        rows.append((float(d.mean()), t))
        Image.fromarray(np.concatenate([r, m, np.stack([d] * 3, 2)], 1).astype(np.uint8)) \
            .resize((1920, 360)).save(os.path.join(out, f"cmp_{t:07.2f}.png"))
    return rows


def dense_windows(proj):
    """Time windows worth checking every 0.1 s: masked and compound clips."""
    from kiasecut import project
    out = []
    for c in project.walk_clips(proj["tracks"]):
        if c.get("mask") or c["type"] == "compound":
            a = c["start_us"] / 1e6
            out.append((a, a + min(c["duration_us"] / 1e6, 4)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("reference")
    ap.add_argument("out")
    ap.add_argument("--remap", action="append", default=[])
    ap.add_argument("--max-mean", type=float, default=3.0)
    ap.add_argument("--compare-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.compare_only:
        export, fps = a.source, 60.0
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", export], capture_output=True, text=True).stdout)
        times = sample_times(dur)
    else:
        from kiasecut import build, project
        from kiasecut.client import EngineClient
        from kiasecut.importers import jianying
        proj, warnings = jianying.import_draft(a.source, [r.split("=", 1) for r in a.remap])
        for w in sorted(set(warnings)):
            print("WARN", w)
        project.save(proj, os.path.join(a.out, "golden.kiasecut.json"))
        xml = build.build(proj, os.path.join(a.out, "golden.kiasecut-cache"), os.path.join(a.out, "golden.mlt"))
        export, fps = os.path.join(a.out, "golden.mp4"), proj["fps"]
        eng = EngineClient(16, 16)
        try:
            r = eng.export(xml, export, crf=12, preset="veryfast", threads=os.cpu_count() or 4)
        finally:
            eng.close()
        print(f"export {r['elapsed']:.0f}s")
        times = sample_times(proj["duration_us"] / 1e6, dense_windows(proj))
    rows = compare(export, a.reference, os.path.join(a.out, "frames"), fps, times)
    worst = sorted(rows, reverse=True)
    for m, t in worst[:8]:
        print(f"  t={t:7.2f}s  mean={m:5.2f}")
    vals = [m for m, _ in rows]
    print(f"frames {len(vals)}  median {statistics.median(vals):.2f}  max {max(vals):.2f}")
    sys.exit(0 if max(vals) <= a.max_mean else 1)


if __name__ == "__main__":
    main()
