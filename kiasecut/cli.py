"""Rendering from the command line, without the editor's window (for scripts and hooks).

    python -m kiasecut render PROJECT --out PATH [--from MARK] [--to MARK] [...]
    python -m kiasecut marks PROJECT [--compound NAME]

Drawn by the same renderer as the editor's export (renderexport.export). The project file is
only read. --from / --to take a marker's name: the frames from the first mark up to, not
including, the second one's, so ranges that share a mark neither overlap nor leave a gap.

The output is made in a folder beside it and put in place only when the whole render went
well: a failed one leaves what was there before. A picture sequence replaces the frames of
the same name (a shorter render leaves none of a longer one's behind) and nothing else.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile

from . import assets, formats, project, workspace

US = 1_000_000
COMMANDS = ("render", "marks")


class CliError(Exception):
    pass


def _size(text):
    m = re.fullmatch(r"(\d+)[x×](\d+)", text.strip())
    if not m or not all(int(v) > 0 for v in m.groups()):
        raise argparse.ArgumentTypeError("要寫成 寬x高，例如 1920x1080")
    return int(m[1]), int(m[2])


def _positive(text):
    v = float(text)
    if not 0 < v < float("inf"):
        raise argparse.ArgumentTypeError("要大於 0")
    return v


def parser():
    ap = argparse.ArgumentParser(prog="kiasecut", description="不開視窗的渲染")
    sub = ap.add_subparsers(dest="command", required=True)
    for name, text in (("render", "渲染到指定路徑"), ("marks", "列出標記")):
        p = sub.add_parser(name, help=text, description=text)
        p.add_argument("project", help="專案檔")
        p.add_argument("--compound", help="複合片段的名稱或 id（不給：目前的時間線）")
    p = sub.choices["render"]
    p.add_argument("--out", "-o", required=True, help="輸出檔案；圖片序列則是資料夾")
    p.add_argument("--format", "-f", default=formats.DEFAULT, choices=list(formats.BY_KEY), help="預設 %(default)s")
    p.add_argument("--from", dest="start", metavar="MARK", help="從這個標記開始（不給：開頭）")
    p.add_argument("--to", dest="end", metavar="MARK", help="到這個標記之前（不給：結尾）")
    p.add_argument("--size", type=_size, help="寬x高（不給：跟專案一樣）")
    p.add_argument("--fps", type=_positive, help="幀率（不給：跟專案一樣）")
    p.add_argument("--alpha", action=argparse.BooleanOptionalAction, help="透明背景（不給：看格式的預設）")
    p.add_argument("--no-audio", action="store_true", help="不要聲音")
    p.add_argument("--crf", type=int, default=18, help="畫質，越小越好，預設 %(default)s")
    p.add_argument("--allow-errors", action="store_true", help="素材找不到或有片段畫不出來也照樣輸出")
    return ap


def load(path):
    if not os.path.isfile(path):
        raise CliError(f"找不到專案檔：{path}")
    proj = project.load(path)
    # built-in assets are drawn again rather than looked for, as when the editor opens the project
    assets.restore(project.all_clips(proj), workspace.media_dir(workspace.root_of(path)))
    return proj


def level(proj, name=None):
    """(view of what is rendered, its markers): the open timeline, or the compound called name (or with that id)."""
    view = json.loads(json.dumps(proj))
    comps = view["compounds"]
    if name is None:
        comp = comps[view["active_timeline"]]
    else:
        found = [name] if name in comps else [k for k, c in comps.items() if c.get("name") == name]
        if len(found) != 1:
            names = "、".join(c.get("name") or k for k, c in comps.items() if not c.get("static")) or "（沒有）"
            why = "有不只一個複合片段叫" if found else "沒有複合片段叫"
            raise CliError(f"{why}「{name}」。可以選：{names}（重名時用 id：{'、'.join(found)}）" if found
                           else f"{why}「{name}」。可以選：{names}")
        comp = comps[found[0]]
        if comp.get("static"):
            raise CliError(f"「{name}」是靜態片段（一張圖片），不能當影片渲染")
        view["tracks"] = comp["tracks"]
        view["width"] = comp.get("width") or view["width"]
        view["height"] = comp.get("height") or view["height"]
        view["duration_us"] = project.end_us(comp["tracks"])
    marks = sorted(comp.get("markers") or [], key=lambda m: m["t_us"])
    return view, marks


def _mark(marks, name):
    found = [m for m in marks if m["name"] == name]
    if len(found) == 1:
        return found[0]["t_us"]
    if found:
        raise CliError(f"有不只一個標記叫「{name}」，請在編輯器裡改成不同的名稱")
    names = "、".join(m["name"] for m in marks) or "（沒有標記）"
    raise CliError(f"沒有標記叫「{name}」。這裡的標記：{names}")


def frame_range(view, marks, fps, start=None, end=None):
    """(first, last) frame, inclusive, at fps."""
    tracks = [t for t in view["tracks"] if project.present(t)]          # (參考 tracks are not exported)
    total = max(round(project.end_us(tracks or view["tracks"]) / US * fps), 1)
    first = 0 if start is None else round(_mark(marks, start) / US * fps)
    stop = total if end is None else round(_mark(marks, end) / US * fps)       # (the first frame left out)
    if stop <= first:
        raise CliError("範圍裡沒有任何畫格：--to 要在 --from 之後")
    return first, stop - 1


def missing_media(view):
    return sorted({c["media"]["path"] for c in project.all_clips(view)
                   if c.get("media") and not os.path.exists(c["media"]["path"])})


def _place(made, out, sequence):
    """Move the finished render from its staging folder to out."""
    if not sequence:
        os.replace(made, out)
        return
    stem = os.path.basename(out)
    os.makedirs(out, exist_ok=True)
    ours = re.compile(re.escape(stem) + r"_\d{5,}\.png")
    for f in os.listdir(out):
        if ours.fullmatch(f):
            os.remove(os.path.join(out, f))
    for f in os.listdir(made):
        os.replace(os.path.join(made, f), os.path.join(out, f))


def render(args, proj, say=lambda text: print(text, file=sys.stderr, flush=True)):
    from . import pathfollow, renderexport
    from .build import find_ffmpeg

    view, marks = level(proj, args.compound)
    fps = args.fps or float(view["fps"])
    first, last = frame_range(view, marks, fps, args.start, args.end)
    missing = missing_media(view)
    if missing:
        text = f"有 {len(missing)} 個素材檔案找不到：\n  " + "\n  ".join(missing[:5])
        if not args.allow_errors:
            raise CliError(text + "\n（要照樣輸出就加 --allow-errors）")
        say(text)
    pathfollow.resolve(view)

    fmt = formats.get(args.format)
    if not find_ffmpeg():
        raise CliError("找不到 ffmpeg")
    if not formats.usable(fmt):
        raise CliError(f"這台的 ffmpeg 沒辦法做 {fmt.key}")
    if args.alpha and not fmt.can_alpha:
        raise CliError(f"{fmt.key} 不支援透明背景")
    sequence = fmt.kind == "sequence"
    out = os.path.abspath(args.out)
    if sequence:
        if os.path.exists(out) and not os.path.isdir(out):
            raise CliError(f"圖片序列的 --out 要是資料夾：{out}")
    elif os.path.isdir(out):
        raise CliError(f"--out 是資料夾，這個格式要給檔名：{out}")
    elif os.path.splitext(out)[1].lower() != fmt.ext:
        raise CliError(f"{fmt.key} 的檔名要用 {fmt.ext} 結尾")

    size = args.size or (view["width"], view["height"])
    alpha = bool(fmt.alpha) if args.alpha is None else args.alpha
    parent = os.path.dirname(out)
    os.makedirs(parent, exist_ok=True)
    stage_dir = tempfile.mkdtemp(prefix=".kiasecut-render-", dir=parent)
    shown = [-1]

    def progress(p):
        tens = int(p * 10)
        if tens > shown[0]:
            shown[0] = tens
            say(f"  {tens * 10}%")

    try:
        cache = os.path.join(stage_dir, "cache")
        # (a sequence is asked for as <folder>.png: renderexport writes into <folder>/)
        target = os.path.join(stage_dir, os.path.basename(out) + (".png" if sequence else ""))
        result = renderexport.export(view, target, size, fps, first, last, {"crf": args.crf, "preset": "medium"},
                                     progress, cache, spec={"format": fmt.key, "alpha": alpha,
                                                            "audio": not args.no_audio},
                                     on_stage=say)
        if result["errors"]:
            text = "有片段畫不出來：\n  " + "\n  ".join(result["errors"])
            if not args.allow_errors:
                raise CliError(text + "\n（要照樣輸出就加 --allow-errors）")
            say(text)
        _place(result["done"], out, sequence)
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
    say(f"完成：{out}（{size[0]}×{size[1]}，{fps:g} fps，畫格 {first}–{last}，{result['elapsed']:.1f} 秒）")
    return out


def main(argv):
    """argv: what follows `kiasecut`. The exit code: 0 done, 1 failed, 2 wrong arguments."""
    args = parser().parse_args(argv)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"            # no display is needed (nor one of the user's, in a hook)
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(["kiasecut"])    # noqa: F841 (texts and pictures need it)
    try:
        proj = load(args.project)
        if args.command == "marks":
            view, marks = level(proj, args.compound)
            for m in marks:
                print(f"{m['t_us'] / US:10.3f} s  {m['name']}")
            if not marks:
                print("（沒有標記）", file=sys.stderr)
        else:
            render(args, proj)
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return 130
    except (CliError, OSError, ValueError, RuntimeError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    return 0
