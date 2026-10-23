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
Ctrl+Z / Ctrl+Y undo and redo. Right-click a track header or clip to rename it or give it
a colour (double-click a track name to rename). Ctrl+wheel zooms the timeline.

Compound clips: double-click one (or right-click > 編輯複合片段) to edit its content;
the breadcrumb above the timeline shows where you are, Esc / 返回上一層 goes back.

Media library (left): import files (Ctrl+Shift+I), organise them in folders by dragging,
and drag media onto the timeline (or double-click to add at the playhead). Importing a
Jianying draft fills the library with the media it uses.

Preview: click a clip on the canvas to select it and drag it to move it; it snaps to the
canvas centre lines and edges and to other clips' centres and edges (hold Alt to move
freely). F or double-click toggles fullscreen.

Keyframes and masks: every animatable value in the inspector (position, scale, rotation,
opacity, volume, text size / colour / letter and line spacing / italic, mask centre / size /
rotation / feather) has a ◆ button that adds or removes a keyframe at the playhead;
changing a value that already has keyframes edits or adds the keyframe at the playhead, as
in Jianying. ◀/▶ jump between keyframes, and the curve menu sets linear / ease-in /
ease-out / ease-in-out from the keyframe at the playhead to the next. Pictures, videos and
compound clips take line, mirror, circle or rectangle masks, optionally inverted. The
mouse wheel never changes a number field.

Export (Ctrl+E): the whole film or the range marked with I / O (Alt+X clears), at high,
standard or small-file quality.

## How it works

| module | role |
|---|---|
| `project.py` | project model (JSON); Jianying units and bezier keyframes |
| `importers/jianying.py` | draft_content.json → project |
| `curves.py` | keyframe evaluation (Jianying's bezier handles) |
| `edit.py` | move / trim / split / delete / keyframe / mask / name edits with undo |
| `library.py` | media library: folders, probing, placing media on a timeline |
| `textlayout.py` | text rendering calibrated to Jianying's layout |
| `masks.py` | line / mirror / circle / rectangle masks as MLT splines (or baked mattes) |
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
python tools/smoke_keys.py PROJECT.tesetoa.json out/   # keyframes and masks, headless
python tools/smoke_features.py PROJECT.tesetoa.json out/ IMAGE AUDIO   # library, compounds, preview drag, range export
```

## Status

Milestones 1 (import → preview → export), 2 (move, trim, split, text editing) and
3 (keyframes, easing, masks) work, plus the media library, compound editing, preview
dragging with snapping and range export. An edit reaches the preview in about 3 s.
The preview uses frame-sized proxies of large images; exports use the originals.
Masks are drawn by MLT's rotoscoping filter before the clip transform, so they follow the
clip like Jianying's and need no pre-rendering (`build.build(..., mask_mode="baked")`
still renders the screen-space mattes they were verified against).

Known: on the first frame of a clip that starts exactly on a frame boundary, Jianying can
show a slightly different picture (max frame difference 4.9 at two such frames).

## Other converters

`tools/converters/` holds the standalone converters this project grew from:
`jianying_to_blender.py` (+ `jy_build.py`) builds a Blender VSE project, and `jy_mlt.py`
turns its `timeline.json` into plain MLT XML or a `.kdenlive` project with editable titles.
