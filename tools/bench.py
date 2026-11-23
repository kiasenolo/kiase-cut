"""Benchmarks of the live renderer: typical projects made up here, drawn frame by frame as the preview draws them.

    python tools/bench.py                     every scenario, 1920 wide, 120 frames each, at the project's pace
    python tools/bench.py --only video glare  the scenarios whose names hold these words
    python tools/bench.py --list              the scenarios and what they hold
    python tools/bench.py --breakdown         also where each frame's time goes (clips, effects, node graphs, filters)
    python tools/bench.py --json out.json     keep the numbers; --compare out.json shows the change against them
    python tools/bench.py --flat              as fast as it goes instead of at the project's pace (video can then not read ahead)

It needs no media of its own: pictures, a 1080p60 H.264 video and a sound are made the first time (ffmpeg for the last two;
the scenarios that need them are left out without it) and kept in --media (default: the system's cache folder,
kiasecut-bench, ~20 MB). Each scenario is a project of 1920 x 1080 at 60 fps; its first frame (shaders compiled, streams
started) is timed apart from the rest. The renderer is the one the preview uses: the GPU compositor (glrender.make) on the
card a context of its own gets, frames read back as the preview's are when it does not share Qt's.
"""
import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

from kiasecut import fx, glrender, gpusync, lfo, project, render, videoreader  # noqa: E402
from kiasecut.build import find_ffmpeg  # noqa: E402

S = 1_000_000
W, H, FPS, DUR = 1920, 1080, 60.0, 10 * S


# -- media ---------------------------------------------------------------------------------------------------------------
def make_media(folder):
    """{name: path} of the pictures, video and sound the scenarios use (made once into folder)."""
    os.makedirs(folder, exist_ok=True)
    out = {}
    for i in range(8):                                   # photo-like pictures: gradients, light spots, shapes, text
        path = os.path.join(folder, f"photo{i}.png")
        if not os.path.exists(path):
            w, h = (1920, 1080) if i < 2 else (800, 600)
            img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            g = QLinearGradient(0, 0, w, h)
            g.setColorAt(0, QColor.fromHsv((i * 47) % 360, 160, 90))
            g.setColorAt(1, QColor.fromHsv((i * 47 + 150) % 360, 200, 230))
            p.fillRect(img.rect(), g)
            for k in range(14):
                x, y, r = (k * 389 + i * 97) % w, (k * 241 + i * 53) % h, 20 + (k * 37) % (min(w, h) // 4)
                rg = QRadialGradient(QPointF(x, y), r)
                rg.setColorAt(0, QColor(255, 250, 230, 255))
                rg.setColorAt(1, QColor(255, 200, 120, 0))
                p.setBrush(rg)
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(x, y), r, r)
            p.setPen(QColor(20, 20, 30))
            p.setFont(QFont("Sans", max(12, h // 12)))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, f"KiaseCut {i}")
            p.end()
            img.save(path)
        out[f"photo{i}"] = path
    ff = find_ffmpeg()
    if ff:
        video = os.path.join(folder, "video1080p60.mp4")
        if not os.path.exists(video):
            subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60", "-t", "12",
                            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "12M", "-maxrate", "12M", "-bufsize", "24M",
                            "-pix_fmt", "yuv420p", video], check=True, timeout=600)
        out["video"] = video
        sound = os.path.join(folder, "sound.wav")
        if not os.path.exists(sound):
            subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=12:c=pink:a=0.3", "-f", "lavfi", "-i",
                            "sine=f=440:d=12", "-filter_complex", "amix=inputs=2", "-ar", "48000", "-ac", "2", sound],
                           check=True, timeout=120)
        out["sound"] = sound
    return out


# -- clips ---------------------------------------------------------------------------------------------------------------
_ids = [0]


def _id(prefix="c"):
    _ids[0] += 1
    return f"{prefix}{_ids[0]}"


def tf(**kw):
    t = {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}
    t.update(kw)
    return t


def anim(a, b, dur=DUR):
    """A number keyframed from a to b over dur (us), eased."""
    return {"keys": [[0, a, 0, 0, dur / 3, 0], [dur, b, -dur / 3, 0, 0, 0]]}


def pic(path, w, h, start=0, dur=DUR, **kw):
    c = {"id": _id(), "type": "image", "name": os.path.basename(path), "start_us": start, "duration_us": dur, "source_start_us": 0,
         "media": {"path": path, "width": w, "height": h}, "transform": tf()}
    c.update(kw)
    return c


def vid(path, start=0, dur=DUR, src=0, **kw):
    c = {"id": _id(), "type": "video", "name": "video", "start_us": start, "duration_us": dur, "source_start_us": src,
         "media": {"path": path, "width": 1920, "height": 1080, "duration_us": 12 * S}, "volume": 0.0, "transform": tf()}
    c.update(kw)
    return c


def text(content, size=10.0, dur=DUR, **kw):
    c = {"id": _id(), "type": "text", "name": content, "start_us": 0, "duration_us": dur, "source_start_us": 0,
         "text": {"content": content, "font_path": project.DEFAULT_FONT, "size": size, "color": [1.0, 1.0, 1.0],
                  "letter_spacing": 0.0, "line_spacing": 0.0, "italic_deg": 0}, "transform": tf()}
    c.update(kw)
    return c


def effect(ref, **params):
    return {"id": _id("e"), "filter": ref, "enabled": True, "params": params}


def graph_effect(nodes, links, **params):
    """A node effect: nodes {id: ref}, links [(from, to, socket, out)]; params {"node.param": value}."""
    g = {"nodes": {"input": {"type": "input", "x": 0.0, "y": 0.0}, "output": {"type": "output", "x": 900.0, "y": 0.0}},
         "links": []}
    for k, (nid, ref) in enumerate(nodes.items()):
        g["nodes"][nid] = {"type": "filter", "ref": ref, "x": 200.0 + 150 * k, "y": 0.0}
    for f, t, socket, out in links:
        link = {"from": f, "to": t, "socket": socket}
        if out:
            link["out"] = out
        g["links"].append(link)
    return {"id": _id("e"), "filter": fx.GRAPH, "enabled": True, "params": params, "graph": g}


def tracks(*layers):
    return [{"id": _id("t"), "kind": "video", "name": f"v{i}", "clips": list(cl)} for i, cl in enumerate(layers)]


def project_of(trs, extra_tracks=(), compounds=None):
    p = project.new(W, H, FPS)
    p["compounds"].update(compounds or {})
    p["timelines"][0]["tracks"][:] = list(trs) + list(extra_tracks)
    p["duration_us"] = DUR
    return p


# -- scenarios -----------------------------------------------------------------------------------------------------------
SCENARIOS = []


def scenario(name, needs=(), about=""):
    def put(f):
        SCENARIOS.append((name, needs, about, f))
        return f
    return put


@scenario("pictures_still", about="兩張 1080p 圖片疊在一起（基準：最簡單的情況）")
def _(m):
    return project_of(tracks([pic(m["photo0"], 1920, 1080)], [pic(m["photo1"], 1920, 1080, transform=tf(scale=0.5, opacity=0.8))]))


@scenario("pictures_200_moving", about="複合片段裡 200 張圖片，各自有關鍵幀動畫（像 PastRedemption 的素材牆）")
def _(m):
    clips = []
    for i in range(200):
        a, b = ((i * 0.137) % 2 - 1), ((i * 0.291) % 2 - 1)
        clips.append([pic(m[f"photo{2 + i % 6}"], 800, 600, transform=tf(x=anim(a, -a), y=anim(b, b * 0.5),
                                                                              scale=anim(0.15, 0.25), rotation=anim(0, 30 * (i % 5))))])
    comp = {"name": "wall", "width": W, "height": H, "duration_us": DUR, "tracks": tracks(*clips)}
    c = {"id": _id(), "type": "compound", "name": "wall", "start_us": 0, "duration_us": DUR, "source_start_us": 0,
         "compound_id": "k_wall", "compound": comp, "transform": tf()}
    return project_of(tracks([c]), compounds={"k_wall": comp})


@scenario("text_30_moving", about="30 段文字，位置 / 旋轉關鍵幀")
def _(m):
    layers = [[text(f"標題文字 Title {i}", size=6 + i % 5, transform=tf(x=anim(-0.8, 0.8), y=-0.9 + i * 0.06, rotation=anim(0, 10)))]
              for i in range(30)]
    return project_of(tracks([pic(m["photo0"], 1920, 1080)], *layers))


@scenario("text_size_animated", about="10 段文字字號每幀變（每幀重新排字、上傳貼圖）")
def _(m):
    layers = [[text(f"放大縮小的字 {i}", size=anim(4, 18), transform=tf(y=-0.8 + i * 0.17))] for i in range(10)]
    return project_of(tracks([pic(m["photo0"], 1920, 1080)], *layers))


@scenario("masks_blends", about="12 張圖片，羽化遮罩 + 各種混合模式")
def _(m):
    modes = list(glrender.BLEND_INDEX)
    layers = []
    for i in range(12):
        mask = {"kind": ("circle", "rectangle", "line", "mirror")[i % 4], "invert": bool(i % 3 == 0), "cx": 0.1 * (i % 5) - 0.2,
                "cy": 0.0, "w": 0.6, "h": 0.5, "rotation": 15.0 * i, "feather": 0.3}
        layers.append([pic(m[f"photo{i % 8}"], 1920 if i % 8 < 2 else 800, 1080 if i % 8 < 2 else 600, mask=mask,
                           blend=modes[i % len(modes)], transform=tf(scale=0.9, rotation=anim(0, 20)))])
    return project_of(tracks(*layers))


@scenario("motion_blur_5", about="5 張移動的圖片開動態模糊（8 次取樣）")
def _(m):
    layers = [[pic(m[f"photo{2 + i}"], 800, 600, transform=tf(x=anim(-1, 1), y=-0.6 + 0.3 * i, scale=0.3),
                   effects=[effect(project.MOTION_BLUR_FILTER, shutter=180.0, samples=8)])] for i in range(5)]
    return project_of(tracks([pic(m["photo0"], 1920, 1080)], *layers))


@scenario("groups_lfo_30", about="30 個群組（每個 3 張圖），群組旋轉用 LFO")
def _(m):
    layers = []
    for i in range(30):
        inner = tracks(*[[pic(m[f"photo{2 + (i + k) % 6}"], 800, 600, transform=tf(x=0.1 * k, scale=0.2))] for k in range(3)])
        g = {"id": _id(), "type": "group", "name": f"g{i}", "start_us": 0, "duration_us": DUR, "source_start_us": 0,
             "tracks": inner, "transform": tf(x=(i % 6) / 3 - 0.8, y=(i // 6) / 2.5 - 0.8, scale=0.6),
             "expr": {"transform.rotation": lfo.make(rate=0.5 + 0.1 * i, amp=20.0)}}
        layers.append([g])
    return project_of(tracks(*layers))


@scenario("effects_stack", about="一張 1080p 圖片疊 6 個內建效果（光暈、模糊 30、色彩調整、暈影、顆粒、色差）")
def _(m):
    fxs = [effect("builtin:glow"), effect("builtin:blur", radius=30.0), effect("builtin:color_adjust"), effect("builtin:vignette"),
           effect("builtin:grain"), effect("builtin:rgb_shift")]
    return project_of(tracks([pic(m["photo0"], 1920, 1080, effects=fxs)]))


def _glare(kind):
    def make(m):
        e = graph_effect({"glare": "builtin:blender_glare"}, [("input", "glare", "src", None), ("glare", "output", "src", "image")],
                         **{"glare.type": kind, "glare.quality": "高", "glare.threshold": 0.5, "glare.size": 0.7,
                            "glare.sun_position": [-0.3, 0.6]})
        return project_of(tracks([pic(m["photo0"], 1920, 1080, transform=tf(scale=anim(1.0, 1.2)), effects=[e])]))
    return make


for _kind in ("Bloom", "Ghosts", "Streaks", "Fog Glow", "Simple Star", "Sun Beams"):
    scenario("glare_" + _kind.lower().replace(" ", "_"), about=f"[Blender] Glare（{_kind}，品質高）節點，在動態的圖上")(_glare(_kind))


@scenario("node_graph_mixed", about="節點圖：噪聲紋理、混合、5 個逐點節點、模糊、Bloom、Streaks、Lens Distortion")
def _(m):
    nodes = {"noise": "builtin:nodes/tex_noise", "mix": "builtin:nodes/mix", "exp": "builtin:nodes/exposure",
             "gam": "builtin:nodes/gamma", "hsv": "builtin:nodes/hue_sat_value", "bc": "builtin:nodes/bright_contrast",
             "cl": "builtin:nodes/clamp", "blur": "builtin:blur", "bloom": "builtin:blender_glare",
             "streaks": "builtin:blender_glare", "lens": "builtin:blender_lens_distortion"}
    links = [("input", "mix", "src", None), ("noise", "mix", "b", None), ("mix", "exp", "src", None), ("exp", "gam", "src", None),
             ("gam", "hsv", "src", None), ("hsv", "bc", "src", None), ("bc", "cl", "src", None), ("cl", "blur", "src", None),
             ("blur", "bloom", "src", None), ("bloom", "streaks", "src", "image"), ("streaks", "lens", "src", "image"),
             ("lens", "output", "src", None)]
    e = graph_effect(nodes, links, **{"mix.blend": "疊加", "mix.fac": 0.4, "exp.exposure": 0.3, "blur.radius": 6.0,
                                      "bloom.type": "Bloom", "streaks.type": "Streaks", "streaks.threshold": 0.8,
                                      "lens.distortion": -0.1, "lens.dispersion": 0.03})
    return project_of(tracks([pic(m["photo0"], 1920, 1080, transform=tf(x=anim(-0.05, 0.05)), effects=[e])]))


@scenario("video_1", needs=("video",), about="一段 1080p60 H.264 影片")
def _(m):
    return project_of(tracks([vid(m["video"])]))


@scenario("video_4_pip", needs=("video",), about="4 段 1080p60 影片：全螢幕 + 3 個子母畫面，混合模式")
def _(m):
    layers = [[vid(m["video"])]]
    for k in range(3):
        layers.append([vid(m["video"], src=(k + 1) * S, blend=("screen", "normal", "overlay")[k],
                           transform=tf(scale=0.33, x=-0.6 + 0.6 * k, y=0.55))])
    return project_of(tracks(*layers))


@scenario("video_effects", needs=("video",), about="1080p60 影片 + 光暈 + 模糊 + Bloom 節點")
def _(m):
    e = graph_effect({"glare": "builtin:blender_glare"}, [("input", "glare", "src", None), ("glare", "output", "src", "image")],
                     **{"glare.type": "Bloom", "glare.threshold": 0.6})
    return project_of(tracks([vid(m["video"], effects=[effect("builtin:glow"), effect("builtin:blur", radius=4.0), e])]))


@scenario("visualizer", needs=("sound",), about="聲音視覺化：頻譜圖（4096 欄、FFT 32768）+ 長條圖")
def _(m):
    sound = {"id": _id(), "type": "audio", "name": "sound", "start_us": 0, "duration_us": DUR, "source_start_us": 0,
             "media": {"path": m["sound"], "duration_us": 12 * S}, "volume": 1.0}
    aud = {"id": _id("t"), "kind": "audio", "name": "a1", "clips": [sound]}
    src = {"type": "track", "id": aud["id"]}
    gram = pic("viz", 1280, 420, viz={"kind": "spectrogram", "source": src, "gram_cols": 4096.0, "gram_rows": 512.0, "fft": 32768.0},
               transform=tf(y=-0.4))
    bars = pic("viz", 1280, 420, viz={"kind": "bars", "source": src}, transform=tf(y=0.5))
    return project_of(tracks([gram], [bars]), [aud])


# -- running -------------------------------------------------------------------------------------------------------------
class Breakdown:
    """Where a frame's time goes: the renderer's clip / effect / graph calls and each filter's passes, each waited for on
    the card (so the parts are exclusive and add up, a little slower than without)."""

    def __init__(self):
        self.tot, self.cnt, self.stack = {}, {}, []
        self.undo = []

    def wrap(self, owner, name, key):
        orig = getattr(owner, name)
        me = self

        def f(obj, *a, **k):
            ctx = obj.gl.ctx if hasattr(obj, "gl") else obj.ctx
            ctx.finish()
            label = key(a)
            t = time.perf_counter()
            me.stack.append(0.0)
            try:
                return orig(obj, *a, **k)
            finally:
                ctx.finish()
                dt = time.perf_counter() - t
                child = me.stack.pop()
                me.tot[label] = me.tot.get(label, 0.0) + dt - child
                me.cnt[label] = me.cnt.get(label, 0) + 1
                if me.stack:
                    me.stack[-1] += dt
        setattr(owner, name, f)
        self.undo.append((owner, name, orig))

    def install(self):
        nm = lambda c: f"{c.get('type')}:{(c.get('name') or '')[:24]}"
        self.wrap(glrender.GLRenderer, "gl_clip", lambda a: "clip " + nm(a[2]))
        self.wrap(glrender.GLRenderer, "gl_filter_clip", lambda a: "filter clip " + nm(a[2]))
        self.wrap(glrender.GLRenderer, "gl_blurred", lambda a: "motion blur " + nm(a[2]))
        self.wrap(fx.Engine, "run_outputs", lambda a: "filter " + (getattr(a[0], "name", "?") or "?"))

    def remove(self):
        for owner, name, orig in reversed(self.undo):
            setattr(owner, name, orig)
        self.undo.clear()

    def top(self, frames, n=6):
        return sorted(((v / frames * 1000, self.cnt[k] / frames, k) for k, v in self.tot.items()), reverse=True)[:n]


def run_one(r, p, frames, pace, cache_dir, size, readers):
    folder = tempfile.mkdtemp(dir=cache_dir)
    try:
        path = os.path.join(folder, "bench.kiasecut.json")
        project.save(p, path)
        v = project.load(path)
        v["play_fps"], v["editing"] = v["fps"], True
        r.cache_dir = cache_dir
        r.errors.clear()
        getattr(readers, "next_frame", lambda: None)()
        t = time.perf_counter()
        r.render(v, 0, *size)
        first = (time.perf_counter() - t) * 1000
        times = []
        t0 = time.perf_counter()
        for k in range(1, frames + 1):
            if pace:
                wait = t0 + k / FPS - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
            getattr(readers, "next_frame", lambda: None)()
            t = time.perf_counter()
            r.render(v, k, *size)
            times.append((time.perf_counter() - t) * 1000)
        return first, times, sorted(set(r.errors))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--width", type=int, default=1920, help="the width frames are drawn at (the preview's size; the project stays 1920 x 1080)")
    ap.add_argument("--flat", action="store_true")
    ap.add_argument("--breakdown", action="store_true")
    ap.add_argument("--media", default=os.path.join(tempfile.gettempdir() if os.name == "nt" else
                                                    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "kiasecut-bench"))
    ap.add_argument("--json")
    ap.add_argument("--compare")
    a = ap.parse_args()
    if a.list:
        for name, needs, about, _f in SCENARIOS:
            print(f"{name:22s} {about}" + (f"  (需要 {', '.join(needs)})" if needs else ""))
        return
    media = make_media(a.media)
    videoreader.ENGINE = False                       # (no engine here: a jump starts a stream)
    readers = videoreader.Readers()
    r = glrender.make(lambda path, us, w, h: readers.get(path, us, w, h))
    card = r.gl.ctx.info.get("GL_RENDERER", "?") if hasattr(r, "gl") else "CPU (QPainter)"
    budget = 1000.0 / FPS
    pw, ph = a.width, round(a.width * 9 / 16)
    print(f"顯示卡：{card}　畫面：{pw} x {ph}　每個情境 {a.frames} 幀，{'全速' if a.flat else f'照 {FPS:g} fps 的節奏'}")
    print(f"{'情境':22s} {'第一幀':>8s} {'中位數':>8s} {'p90':>8s} {'最慢':>8s}  {'fps':>6s}  超時")
    old = json.load(open(a.compare, encoding="utf-8")) if a.compare else {}
    results = {}
    cache_dir = tempfile.mkdtemp(prefix="kiasecut-bench-")
    try:
        for name, needs, about, make in SCENARIOS:
            if a.only and not any(w in name for w in a.only):
                continue
            if any(n not in media for n in needs):
                print(f"{name:22s} (略過：沒有 ffmpeg)")
                continue
            p = make(media)
            bd = Breakdown() if a.breakdown else None
            if bd:
                bd.install()
            try:
                first, times, errors = run_one(r, p, a.frames, not a.flat, cache_dir, (pw, ph), readers)
            finally:
                if bd:
                    bd.remove()
            med, p90 = statistics.median(times), sorted(times)[int(len(times) * 0.9) - 1]
            over = sum(t > budget for t in times) / len(times)
            line = (f"{name:22s} {first:8.1f} {med:8.1f} {p90:8.1f} {max(times):8.1f}  {1000 / statistics.mean(times):6.1f}  "
                    f"{over * 100:3.0f}%")
            if isinstance(old.get(name), dict):
                ch = (med - old[name]["median"]) / old[name]["median"] * 100 if old[name]["median"] else 0.0
                line += f"   中位數 {'+' if ch >= 0 else ''}{ch:.0f}%（之前 {old[name]['median']:.1f}）"
            print(line, flush=True)
            if errors:
                print("    錯誤：" + "；".join(errors)[:300])
            if bd:
                for ms, n, label in bd.top(a.frames + 1):
                    print(f"    {ms:7.2f} ms  x{n:4.1f}  {label}")
            results[name] = {"first": first, "median": med, "p90": p90, "max": max(times), "over": over}
    finally:
        readers.close()
        shutil.rmtree(cache_dir, ignore_errors=True)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"card": card, "width": pw, **results}, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)                                       # (GL contexts and stream threads: no slow teardown)
