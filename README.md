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
a colour (double-click a track name to rename).

Navigation (timeline and curve editor alike): the wheel moves up and down, Shift+wheel
left and right, Ctrl+wheel zooms time around the mouse, the middle button drags the view.

Selection: Ctrl / Shift + click adds or removes clips, dragging on empty track space draws
a selection box, Ctrl+A selects every clip of the open timeline, Ctrl+D clears the
selection. Dragging any selected clip moves the whole selection (one undo step); Delete and
Ctrl+B act on all of it. The inspector shows what the selected clips have in common: a
value they share is shown, one that differs shows "--", and typing a value (or a colour,
mask, keyframe ◆, curve) sets it on every selected clip as one undo step.

Track height: Alt+wheel or the 軌道高度 slider scales every track; drag the line under a
track name to size that track alone (double-click it to reset).

Compound clips: double-click one (or right-click > 編輯複合片段) to edit its content;
the breadcrumb above the timeline shows where you are, Esc / 返回上一層 goes back.
The 複合片段 tab beside the media library lists every compound clip, nested ones under
their parent: click one to select it on its timeline, double-click to open it.

Media library (left): import files (Ctrl+Shift+I), organise them in folders by dragging,
and drag media onto the timeline (or double-click to add at the playhead). Importing a
Jianying draft fills the library with the media it uses.

Preview: click a clip on the canvas to select it and drag it to move it; it snaps to the
canvas centre lines and edges and to other clips' centres and edges (hold Alt to move
freely). Drag a corner square to scale it about its centre, the round handle above it to
rotate it (it settles on right angles; Shift turns in 15° steps). 編輯遮罩 (on by itself
when a mask is chosen) shows the mask on the clip: drag inside it to move it, the squares
to size it, the round handle to turn it and the arrow below it for the feather. Every drag
shows live and is one undo step; keyframed values get their keyframe at the playhead.
Ctrl+wheel zooms the preview (to reach handles of clips bigger than the canvas), the
middle button drags it. F or double-click toggles fullscreen.

Keyframes and masks: every animatable value in the inspector (position, scale, rotation,
opacity, volume, text size / colour / letter and line spacing / italic, mask centre / size /
rotation / feather) has a ◆ button that adds or removes a keyframe at the playhead;
changing a value that already has keyframes edits or adds the keyframe at the playhead, as
in Jianying. ◀/▶ jump between keyframes, and the curve menu sets linear / ease-in /
ease-out / ease-in-out from the keyframe at the playhead to the next. Pictures, videos and
compound clips take line, mirror, circle or rectangle masks, optionally inverted. The
mouse wheel never changes a number field.

Curve editor (the 關鍵幀曲線 tab beside 屬性): tick any parameters of the selected clip and
their keyframes show together as value-over-time curves, each in its own colour (colours
as R/G/B lines). 正規化 gives every curve the same height; untick it to read them on one
axis. Click a keyframe to select it, Ctrl / Shift + click or a selection box for several,
Ctrl+A for all, Ctrl+D for none; dragging moves the whole selection (time snaps to frames, Shift keeps to
one direction). Drag the bezier handles to shape a curve, double-click to add a keyframe
to the nearest curve, Delete to remove the selection. Alt+wheel zooms values, 全部顯示
fits again; a click on the time ruler moves the playhead. The preview follows every drag. The segment
after each selected keyframe takes a CSS `cubic-bezier(x1, y1, x2, y2)` typed in (y may
overshoot, for bounces) or a preset (linear, ease in / out / in-out, back). Time and value
can be typed too: with several keyframes selected they show "--" where they differ, and a
typed number goes to all of them.

Sound and tracks: audio and video clips show their waveform on the timeline (following
the clip volume and fades). Audio track headers have mute and solo buttons, picture
tracks an eye to hide them (and mute, when they hold videos or compound clips); muted /
hidden tracks are dimmed. The track menu (right-click a header) sets a track volume in dB,
moves tracks up or down, adds video / text / audio tracks and deletes them. Drag a picture
clip above the top row, or a sound clip below the bottom row, to put it on a new track.
分離音訊 in a video clip's menu moves its sound onto an audio track. Preview and export
follow the same rules (a solo track silences the others on its level).

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
| `render.py`, `audiomix.py` | live preview: frames drawn with QPainter, audio mixed with numpy |
| `waveform.py` | cached audio peaks for timeline waveforms |
| `build.py` | project → MLT XML for export (cached text images) |
| `mltlib.py`, `engine.py`, `client.py` | MLT through ctypes, in its own process |
| `ui/` | PySide6 window, timeline, preview player |

Preview and export read the same project but render it differently. The preview draws
each frame straight from the project model (render.py, audiomix.py), so edits and drags
show on the next frame and playback runs at 60 fps; it was checked frame by frame against
the MLT output. Exports build an MLT document (build.py) and render it in a separate
engine process: an MLT crash cannot take the editor down, and MLT's Qt never shares a
process with PySide6's Qt. The engine also supplies video pictures to the preview.

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
python tools/smoke_curves.py PROJECT.tesetoa.json out/ # curve editor: drag, cubic-bezier, presets
python tools/smoke_audio.py PROJECT.tesetoa.json out/  # waveforms, mute / solo / hide, new tracks
python tools/smoke_select.py PROJECT.tesetoa.json out/ # multi-select, track heights, compound list
python tools/smoke_handles.py PROJECT.tesetoa.json out/ # scale / rotate / mask handles on the preview
python tools/smoke_features.py PROJECT.tesetoa.json out/ IMAGE AUDIO   # library, compounds, preview drag, range export
python tools/stress_drag.py PROJECT.tesetoa.json      # rapid preview drags + playback fps
```

## Status

Milestones 1 (import → preview → export), 2 (move, trim, split, text editing) and
3 (keyframes, easing, masks) work, plus the media library, compound editing, preview
dragging with snapping, range export, a curve editor with cubic-bezier input, waveforms and per-track
mute / solo / hide / volume. Edits and drags show on the next preview frame.
Masks are drawn by MLT's rotoscoping filter before the clip transform, so they follow the
clip like Jianying's and need no pre-rendering (`build.build(..., mask_mode="baked")`
still renders the screen-space mattes they were verified against).

Known: on the first frame of a clip that starts exactly on a frame boundary, Jianying can
show a slightly different picture (max frame difference 4.9 at two such frames).

## Other converters

`tools/converters/` holds the standalone converters this project grew from:
`jianying_to_blender.py` (+ `jy_build.py`) builds a Blender VSE project, and `jy_mlt.py`
turns its `timeline.json` into plain MLT XML or a `.kdenlive` project with editable titles.
