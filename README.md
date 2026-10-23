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

Editing: drag a clip to move it (also onto another track of the same kind), drag its
edges to trim; moves and trims snap to the playhead and clip edges. Ctrl+B splits the
selected clip (or every clip under the playhead), Delete removes, Ctrl+T adds a text,
Ctrl+Z / Ctrl+Y undo and redo. The inspector edits text (content, size, colour, letter
and line spacing, italic) and position / scale / rotation / opacity; keyframed values are
shown at the playhead but locked. Ctrl+wheel zooms the timeline.

## How it works

| module | role |
|---|---|
| `project.py` | project model (JSON); Jianying units and bezier keyframes |
| `importers/jianying.py` | draft_content.json → project |
| `curves.py` | keyframe evaluation (Jianying's bezier handles) |
| `edit.py` | move / trim / split / delete / text edits with undo |
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

## Tests

```
python -m unittest discover tests            # edit operations
python tools/smoke_edit.py PROJECT.tesetoa.json out/   # drives the real window headless
```

## Status

Milestones 1 (import → preview → export) and 2 (move, trim, split, text editing) work.
An edit reaches the preview in about 3 s. Keyframe and mask editing are next.
Masks are baked mattes, so the first preview of a project takes a few minutes; later
loads use the cache.

Known: on the first frame of a clip that starts exactly on a frame boundary, Jianying can
show a slightly different picture (max frame difference 4.9 at two such frames).

## Other converters

`tools/converters/` holds the standalone converters this project grew from:
`jianying_to_blender.py` (+ `jy_build.py`) builds a Blender VSE project, and `jy_mlt.py`
turns its `timeline.json` into plain MLT XML or a `.kdenlive` project with editable titles.
