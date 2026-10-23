# tesetoa

A small Jianying (剪映)-style video editor on top of the MLT engine. Goal: edit — and
reproduce frame-accurately — the kind of video made in Jianying, without its extras.

## Run

Needs Python 3.11+, `pip install PySide6 numpy Pillow`, ffmpeg on PATH, and MLT 7:
on Windows the copy inside Kdenlive or Shotcut (found automatically, or set
`TESETOA_MLT` to the install folder); on Linux the system package (`mlt` / `libmlt7`).

```
python -m tesetoa                              # empty window: File > Import Jianying draft
python -m tesetoa draft_content.dec.json       # import a decrypted Jianying draft
python -m tesetoa project.tesetoa.json         # open a saved project
```

Space play/pause · ←/→ step a frame · Home/End · Ctrl+I import · Ctrl+S save · Ctrl+E export.
Click the timeline to seek or select a clip; Ctrl+wheel zooms.

## How it works

| module | role |
|---|---|
| `project.py` | project model (JSON); Jianying units and bezier keyframes |
| `importers/jianying.py` | draft_content.json → project |
| `curves.py` | keyframe evaluation (Jianying's bezier handles) |
| `textlayout.py` | text rendering calibrated to Jianying's layout |
| `masks.py` | line / circle / rectangle / mirror masks baked to mattes |
| `build.py` | project → MLT XML (cached text images and mattes) |
| `mltlib.py`, `engine.py`, `client.py` | MLT through ctypes, in its own process |
| `ui/` | PySide6 window, timeline, preview player |

The engine runs in a separate process: an MLT crash cannot take the editor down, and
MLT's Qt never shares a process with PySide6's Qt.

## Accuracy check

```
python tools/golden.py DRAFT.json JIANYING_EXPORT.mp4 out/golden --remap OLD_PREFIX=NEW_PREFIX
```

imports the draft, exports it, and compares ~430 frames with Jianying's own export.
For the AlianShit draft: median per-frame difference 0.25, max 2.42 (of 255);
audio within 1 ms and 0.5 dB.

## Status

Milestone 1 (import → preview → export) works. Editing in the UI (trim, move, text,
keyframes, masks) is next. Masks are baked mattes, so the first preview of a project
takes a few minutes; later loads use the cache.

## Other converters

`tools/converters/` holds the standalone converters this project grew from:
`jianying_to_blender.py` (+ `jy_build.py`) builds a Blender VSE project, and `jy_mlt.py`
turns its `timeline.json` into plain MLT XML or a `.kdenlive` project with editable titles.
