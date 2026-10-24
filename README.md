# 前言 （這段是KILO自己加的）
簡單來説 我就是受不了剪映只能在windows上用這件事情 所以我覺得AI vibe出來了一個剪片軟體
基本上 我會嘗試讓AI還原該還原的東西 因爲我自己也需要用到
同時 我覺得FL的有些邏輯其實不錯 可以放進去 所以 我讓AI放了
這算是少數幾個我認真對待的AI生產的東西了

# KiaseCut

A small Jianying (剪映)-style video editor on top of the MLT engine. Goal: edit — and
reproduce frame-accurately — the kind of video made in Jianying, without its extras.

## Run

Needs Python 3.11+, `pip install PySide6 numpy Pillow moderngl` (moderngl runs the filters, in the
preview and the export), ffmpeg on PATH, and MLT 7:
on Windows the copy inside Kdenlive or Shotcut (found automatically, or set
`KIASECUT_MLT` to the install folder); on Linux the system package (`mlt` / `libmlt7`).

Or start it with `start_kiasecut.bat` (Windows: installs the packages if missing) or
`./start_kiasecut.sh` (Linux: installs them into `.venv` on the first run, warns when
ffmpeg or MLT is missing, passes its arguments on).

```
python -m kiasecut                         # empty window: File > Import Jianying draft
python -m kiasecut draft_content.dec.json  # import a decrypted Jianying draft
python -m kiasecut project.kiasecut.json   # open a saved project
```

Space play/pause · ←/→ step a frame · Home/End · Ctrl+I import · Ctrl+S save · Ctrl+E export.

Playback mode (播放, in the timeline toolbar): 停在暫停處 stops where playback is, 回到開始處
goes back to where it began (as in DAWs). The choice is remembered.

Timeline precision (精度, in the timeline toolbar): how many steps a second has while
editing - the playhead, ←/→, splits and keyframes move in them, and the ruler marks each one
when zoomed in (the zoom reaches 40 px per step). 跟專案 uses the project's frame rate. It
only changes editing: playback still shows the project's frame rate, and the export uses
the project's (or the export dialog's) frame rate, sampling the timeline at its own frames.
It is saved with the project.

Editing: drag a clip to move it (also onto another track of the same kind), drag its
edges to trim; moves and trims snap to the playhead and to other clips' starts, ends and
keyframes while 吸附 (N, in the timeline toolbar) is on, as Jianying's auto-snap; a yellow
line marks where the drag has snapped. Dragging the playhead snaps to the same clip edges,
keyframes and beats; it can be dragged on the ruler or by its line anywhere on the tracks
(the line lights up and the cursor changes when the mouse is on it). Clicking a clip only selects it: the
playhead and the view stay where they are (the view follows the playhead during playback
and for jumps such as Home / End / keyframes). Ctrl+B splits the
selected clip (or every clip under the playhead), Delete removes, Ctrl+T adds a text,
Ctrl+Up / Ctrl+Down move the selected clips to the track above / below (at the same time;
nothing moves when one would land on another clip), Ctrl+Z / Ctrl+Y undo and redo. Right-click a track header or clip to rename it or give it
a colour (double-click a track name to rename).

Time selection, as in FL Studio: drag with the right button anywhere on the timeline to
select a span (it snaps like clips do); playback starts at it and loops
inside it, and a marked export uses it. Ctrl+Shift+D (or Alt+X) clears it; a right click
without dragging opens the menu. I / O still set its ends at the playhead.

Volume line: every sound clip shows a line at its volume (in dB: 0 dB two thirds up, +20 dB
at the top), following its volume keyframes, which are points on it. Drag the line up or
down to change the clip's volume (keyframed clips: all keyframes together, in dB); drag a
point to change that keyframe (up / down) or its time (sideways). The value is shown
while dragging.

Output: right of the timeline a level meter shows the left / right peak of what is playing
(peak hold; red above 0 dB) and its fader sets the project's master volume (-60 … +12 dB,
double-click for 0 dB), used by the preview and the export.

Keyframes on the timeline: the selected clip shows its keyframes as orange diamonds; drag
one sideways to move every keyframe at that time (snapping to frames, the playhead and other
clips' starts, ends and keyframes),
click it to go there.

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

Timelines: a project holds several timelines (as in DaVinci Resolve) sharing its media
and compounds; they are tabs above the timeline: click to open one, + for a new one (with
V1 / A1), double-click to rename, right-click to duplicate or delete. Each keeps its own
tracks; edits, playback and export work on the open one. A timeline can be used inside
another (nested, as in Resolve): drag its tab, or its ⧉ row in the 複合片段 tab, onto the
timeline. The clip shows that timeline live (editing it changes every place it is used);
a timeline can never end up inside itself, and one in use cannot be deleted. Older projects open as one
timeline.

Look: a DaVinci Resolve-like dark layout: the viewer has the timeline name and timecode
above it and icon transport controls below (start, previous frame, play, next frame, end,
fullscreen); the timeline toolbar uses icons (undo, redo, blade, delete, text, snapping,
track height); tracks are labelled V1… (from the bottom) and A1…. Clips are coloured by
type (pictures blue, compound violet, text mauve, sound green, or a colour you set); on a
light colour the clip's name turns dark so it stays readable. A
track's colour tints its row and header edge and leaves its clips alone.

Compound clips: double-click one (or right-click > 編輯複合片段) to edit its content;
the breadcrumb above the timeline shows where you are, Esc / 返回上一層 goes back.
Compounds are reusable: each one is stored once in the project and any number of compound
clips (on any timeline, nested too) show it, so editing it inside one clip changes every
clip that shows it. The 複合片段 tab beside the media library lists them with how often
they are used and where; drag one onto the timeline to use it again, click a use to select
it, double-click to open it, right-click to rename (or delete an unused one). A clip's
「設為獨立（不再共用）」 gives it its own copy. Older projects and Jianying drafts are
converted on opening: identical copies become one shared compound. Right-click selected
clips > 建立複合片段 puts them into a new compound (one clip takes their place).

Static clips (靜態片段, ◧): a picture built in the editor. Right-click selected picture
clips > 建立靜態片段 turns them into one, frozen as they look at the playhead; right-click
a free spot on a picture track > 新增空白靜態片段 starts an empty one. On the timeline it
behaves like a picture: any length, no sound, drawn once and reused. Double-click it to
edit its content (the playhead opens at its frozen moment); every clip that uses it
changes with it, as with compounds.

Media library (left): import files (Ctrl+Shift+I), organise them in folders by dragging,
and drag media onto the timeline (or double-click to add at the playhead). Importing a
Jianying draft fills the library with the media it uses. SVG files work like any picture
and are drawn at the size they are shown, so they stay sharp at any zoom (the MLT export
gets a PNG drawn at the clip's largest size).

Built-in assets (內建素材 tab): solid colours, gradients (presets, plus horizontal /
vertical / diagonal / radial ones, a subtitle backing and a vignette) and basic shapes
(rectangle, circle, triangle, star, heart, arrow, ring, frames, line…). The two colours at
the top of the tab paint the shapes and the 自訂 ones (alpha works too). Drag one onto the
timeline or double-click it (Alt + drop on a picture clip replaces its source). The clip
keeps its parameters: select it and the inspector's 素材參數 sets its size in canvas pixels
(寬 / 高), its colours and what its kind has: gradient type and angle, corner radius,
polygon sides, star points and inner radius, filled or outline and outline width. Every
one of them has a ◆ and keyframes like position or scale: sizes, angles and colours blend
between keyframes (sides and points step), choices hold until the next one; the numbers
also show in the curve editor. Unlike other pictures it is not fitted to the canvas but
drawn at that size, so resizing it keeps corners and outlines as they are (scaling
stretches them). On the preview its corner and edge squares change 寬 / 高 rather than
the scale: an edge one side, a corner both (Shift keeps their ratio), the opposite edge or
corner staying put (Alt: the centre). Solids and gradients start at the canvas's size,
shapes at 400 px (on a 1080-high canvas). The preview and the export draw it from its
parameters at every frame (an export with asset keyframes goes through KiaseCut's own
renderer); the SVG written into Media/.內建素材 when it is made (hidden from the media
library, drawn again if missing) only gives it a file like any picture.

Fonts across Windows and Linux (字體對應): texts name font files, and a project made on one
system names fonts the other does not have. When a project opens with such fonts, a window
lists them with a stand-in to pick for each (one is suggested: what was picked for it
before on this computer, a font with the same file name, or the usual equivalent, such as
Noto Sans CJK for 微軟正黑體 or Liberation Sans for Arial). It does not block the editor;
closing it (or 之後再說) leaves those texts in a default font, and it comes back the next
time the project opens. 編輯 > 字體對應… opens it any time, the fonts already given a
stand-in included. The choice is kept in the project per operating system: the clips keep
their own font, Linux uses its stand-in and Windows its own font (or its own stand-in for a
font picked on Linux). It is not an edit, so undo leaves it alone.

Replacing a clip's source (替換素材): hold Alt while dropping media (from the library, the
Library tab or the 複合片段 tab) on a clip: the clip lights up with 替換素材, and on release
it shows the new media in its place, keeping its position, length, transform, mask,
effects and keyframes. Pictures, videos and compounds replace pictures, videos and
compound clips; sounds replace sounds. A clip longer than a new video or sound is
shortened to it.

Preview: click a clip on the canvas to select it and drag it to move it; it snaps to the
canvas centre lines and edges and to other clips' centres and edges (hold Alt to move
freely). Drag a corner or edge square to scale it: the opposite corner or edge stays where
it is (hold Alt to scale about the centre). With X / Y scale linked, corners and edges keep
the clip's proportions; unlinked, a corner sets X and Y freely (Shift keeps the proportions)
and an edge changes only its own axis. Drag the round handle above it to rotate it (it
settles on right angles; Shift turns in 15° steps).

Beat alignment (節拍 tab, for a selected sound clip): switch on BPM 對齊 and enter the
BPM and the start offset (the first beat's time in the sound); 細分 splits each beat into
1, 1/2, 1/3, 1/4 or 1/6, or thins it to a line every 2 or 4 beats (BPM ÷2 / ÷4: 180 → 90,
the BPM typed in stays as it is).
The grid shows as ticks along the clip's top, coloured by where in the beat they fall
(yellow beat, orange half, pink third, cyan quarter, violet sixth; lines too close at the
zoom are left out), and everything that snaps (clips, trims, keyframes, the playhead)
lands on them. Switching it off keeps the numbers; 重置 deletes them (after asking) and
switches it off.

Saving also stores the view: the playhead, the open compound clip, the timeline's scroll
and zoom and the track heights of each timeline come back when the project is opened.

Masks have their own tab (遮罩, beside 屬性): switch the mask on or off (off keeps its
settings; on for a clip without one adds a rectangle), pick its shape, invert it, remove
it, and set its centre, size, rotation and feather with keyframes. While that tab is open
the preview is the mask editor and only masks can be changed there: drag inside the mask
to move it, the squares to size it, the round handle to turn it and the arrow below it for
the feather (a switched-off mask is drawn dimmed). Back on 屬性 the preview edits the clip
again. Every drag
shows live and is one undo step; keyframed values get their keyframe at the playhead.
Ctrl+wheel zooms the preview (to reach handles of clips bigger than the canvas), the
middle button drags it. F or double-click toggles fullscreen.

Scale has an X and a Y value with a link button between them: linked (the default), changing
one changes the other in the same proportion and their keyframes are added and removed
together; unlinked, each changes alone (the curve editor then shows 縮放 Y on its own).

Keyframes and masks: every animatable value in the inspector (position, scale, rotation,
opacity, volume, text size / colour / letter and line spacing / italic, mask centre / size /
rotation / feather) has a ◆ button that adds or removes a keyframe at the playhead;
changing a value that already has keyframes edits or adds the keyframe at the playhead, as
in Jianying. ◀/▶ jump between keyframes, and the curve menu sets linear / ease-in /
ease-out / ease-in-out from the keyframe at the playhead to the next. Pictures, videos and
compound clips take line, mirror, circle or rectangle masks (see the 遮罩 tab). The
mouse wheel never changes a number field. Number fields work like Resolve's: press and
drag up / down to change the value (Shift for fine steps, Ctrl for big ones), click to type
one. Position X / Y (and a mask's centre and size) sit side by side on one row. The
previous / next keyframe buttons (◀ ▶) are in the curve editor.

Choices keyframe too: the font, the blend mode, a mask's shape and invert, and a filter's
on / off parameters and range shape have ◆ buttons like the numbers. Their keyframes hold
(a step, no blending or curve) until the next keyframe; picking another value at the
playhead edits or adds the keyframe there.

Blend modes (混合模式, under 畫面 for pictures, videos, texts and compound clips): normal,
multiply, screen, overlay, darken, lighten, colour dodge / burn, hard / soft light,
difference, exclusion and add, mixing the clip with what the tracks below show. The
preview draws them; a project that uses a blend mode (or a keyframed mask shape /
invert) exports through the preview renderer, as projects with filters do.

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

Sound and tracks: audio and video clips show their waveform on the timeline (white, the
highest and lowest sample of every millisecond, so zooming in shows detail; following
the clip volume and fades). Audio track headers have mute and solo buttons, picture
tracks an eye to hide them (and mute, when they hold videos or compound clips); muted /
hidden tracks are dimmed. The track menu (right-click a header) sets a track volume in dB,
moves tracks up or down, adds video / text / audio tracks and deletes them. Drag a picture
clip above the top row, or a sound clip below the bottom row, to put it on a new track.
分離音訊 in a video clip's menu moves its sound onto an audio track. Preview and export
follow the same rules (a solo track silences the others on its level).

GPU acceleration (設定 > GPU 加速, on by default): frames are composited on the graphics
card (glrender.py, any OpenGL 3.3 card): every clip is a textured quad whose transform,
opacity, mask, feather and blend mode are worked out per pixel, compounds and static clips
are drawn into layers there and filters run on them without leaving the card; only the
finished frame is read back. A busy scene (feathered masks, blend modes, a filter) went
from 3 to 250 fps at preview size and from 0.7 to 92 fps at 1080p; the two renderers are
compared frame by frame in tests/test_glrender.py (within 1/255 on average). Without
OpenGL, or with the switch off, the QPainter renderer (render.py) does it. With an NVIDIA
card, exports are also encoded with NVENC (several times faster than x264 on real footage;
pictures larger than 4096 px, or a card that refuses, fall back to x264), and HEVC / AV1 /
VP9 videos are decoded and scaled on the card. Videos play from ffmpeg streams
(videoreader.py) that read the file front to back instead of seeking for every frame: a 4K
clip went from ~15 to 30 fps in the preview.

Export (Ctrl+E): the whole film or the range marked with I / O (Alt+X clears), at high,
standard or small-file quality, at any frame rate (10 / 25 / 30 / 40 / 60 / 100 fps or a
custom one) and any size as a multiple of the project's resolution (0.25× / 0.5× / 1× / 2× /
4× or custom; sizes are rounded to even numbers). A project is not tied to a frame rate or
a pixel size: times are microseconds and positions, text sizes and masks are fractions of
the canvas, so every rate and size renders the same picture. The project's own fps only
sets the timeline's frame grid, and its width and height the canvas shape.

## Project folder

A project is a folder, as in FL Studio (File > New project asks for a name and a place):

```
My Video/
    My Video.kiasecut.json   the project file (media paths are stored relative to the folder)
    Media/                  the media library: its sub-folders are the library folders
    Cache/                  waveforms, proxies
    Exports/                rendered videos (the export dialog starts here)
    Backup/                 earlier copies of the project file, one per save; autosave
```

The media library is the Media folder: imports (dialog, or files dragged in from the file
manager) are copied into it, new folders / renaming / moving / deleting in the library do the
same to the files (deleting uses the recycle bin), and files added or removed in Media by hand
show up in the library. Clips follow renamed or moved files. Because of that, these are not
part of Ctrl+Z. File > Project info (F11) holds title, author, genre, URL, comments and the
project's history: when it was started, last opened and saved, and the time spent on it.
Older projects (and Jianying drafts) are offered to be tidied into a project folder; File >
Collect media into the project folder does it any time. Several project files can share one
folder (File > Save as).

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
| `glrender.py` | the same frames composited with OpenGL (GPU) |
| `waveform.py` | cached audio peaks for timeline waveforms |
| `videoreader.py`, `gpu.py` | streamed video pictures for the preview; GPU decoding / NVENC |
| `svgimage.py` | SVG pictures drawn at the size they are shown |
| `build.py` | project → MLT XML for export (cached text images) |
| `mltlib.py`, `engine.py`, `client.py` | MLT through ctypes, in its own process |
| `ui/` | PySide6 window, timeline, preview player |

Preview and export read the same project but render it differently. The preview draws
each frame straight from the project model (render.py, audiomix.py), so edits and drags
show on the next frame and playback runs at 60 fps; it was checked frame by frame against
the MLT output. Exports build an MLT document (build.py) and render it in a separate
engine process: an MLT crash cannot take the editor down, and MLT's Qt never shares a
process with PySide6's Qt. The engine also supplies single video pictures to the preview
(after a jump); while playing, they come from ffmpeg streams (videoreader.py).

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
python tools/smoke_edit.py PROJECT.kiasecut.json out/   # drives the real window headless
python tools/smoke_keys.py PROJECT.kiasecut.json out/   # keyframes and masks, headless
python tools/smoke_curves.py PROJECT.kiasecut.json out/ # curve editor: drag, cubic-bezier, presets
python tools/smoke_audio.py PROJECT.kiasecut.json out/  # waveforms, mute / solo / hide, new tracks
python tools/smoke_select.py PROJECT.kiasecut.json out/ # multi-select, track heights, compound list
python tools/smoke_handles.py PROJECT.kiasecut.json out/ # scale / rotate / mask handles on the preview
python tools/smoke_reuse.py PROJECT.kiasecut.json out/  # shared compounds, timeline ◆ drag, time selection
python tools/smoke_volume.py PROJECT.kiasecut.json out/ # volume line, 吸附, clip clicks, meter, master volume
python tools/smoke_inspector.py PROJECT.kiasecut.json out/ # number dragging, X / Y row, nested timelines
python tools/smoke_features.py PROJECT.kiasecut.json out/ IMAGE AUDIO # library, compounds, preview drag, range export
python tools/stress_drag.py PROJECT.kiasecut.json       # rapid preview drags + playback fps
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

`extra/compositor_to_hyprshade.py` is a Blender add-on (Compositor > Node menu > Export as
Shader / Filter): it turns a compositor node tree or node group into a one-pass GLSL screen
shader (Hyprshade, OBS, ShaderGlass) or a KiaseCut filter whose group inputs become
keyframeable parameters.
