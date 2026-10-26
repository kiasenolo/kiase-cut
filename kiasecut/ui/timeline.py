"""Timeline view and its mouse editing.

Layout follows Jianying: the topmost layer is drawn at the top, audio tracks at the bottom.
Click to seek or select; Ctrl / Shift + click adds to or removes from the selection, dragging
on empty track space draws a selection box, and a selection moves together. Drag a clip to move it (also to another track of the same kind),
drag its edges to trim. Moves and trims snap to the playhead and to other clips' starts,
ends and keyframes, and to the beat grid of sound clips with BPM alignment on (drawn as
ticks along the clip's top, coloured by where in the beat they fall: BEAT_COLORS; lines
too close together at the zoom are neither drawn nor snapped to); a yellow line shows
where a drag has snapped. Dragging the playhead (on the ruler, or by its line anywhere
on the tracks) snaps to the same places.

Times are counted in frames of `fps`, the editor's rate (時間線精度: it can be finer than
the project's frame rate, which only the export uses); the ruler marks each of them once
they are far enough apart, and the zoom reaches 40 px per frame.
The drag is only drawn while it happens; the edit is requested when the mouse is released.
The wheel scrolls the tracks up and down, Shift+wheel scrolls left and right, Ctrl+wheel
zooms time around the mouse, the middle button drags the view. Ctrl+middle-drag zooms around
where the drag started, as in the curve editor: sideways the time, up and down the track
height (right / up: in). Alt+wheel or the toolbar slider changes the track height; dragging the line under a track header resizes that track
alone. Ctrl+D clears the selection. Dragging a picture clip above the top row, or a sound clip
below the bottom row, puts it on a new track. Holding Alt while dragging clips leaves them
where they are and drops copies there instead (dupMoveRequested). Media dropped on a clip with Alt held replaces
that clip's source (the clip lights up while it would).

Time selection (as in FL Studio): drag with the right button anywhere on the timeline to
select a span of time (it snaps like clips do); playback then starts at its beginning and
loops inside it, and it is the range a marked export uses. Ctrl+Shift+D clears it. A right
click without dragging opens the menu.

The selected clip shows its keyframes as diamonds along its bottom edge; drag one sideways
to move every keyframe at that time (it snaps to frames, the playhead and other clips'
starts, ends and keyframes), click it to go there.

Sound clips have a volume line (as in Jianying): drag it up or down to change the clip's
volume. With volume keyframes only a level stretch can be dragged - between two points of
the same volume (both move), or before the first / after the last point (that point moves);
a sloping stretch cannot. Alt+drag anywhere on the line moves all of it (every keyframe);
the keyframes are points on the line that can be dragged up / down (value) and sideways
(time). The line's height is
in dB: the top is +20 dB (1000 %), 0 dB (100 %) two thirds of the way up.

Groups (群組) show as a clip with a ▸ / ▾ at its left: click it (or double-click the group) to
open or fold it. An open group's tracks lie under its track's row as lanes, its clips on them
at their times; the track grows by the most lanes any open group on it needs (nested groups
add theirs), whether the playhead is on that group or not, so heights do not jump while
playing. A lane's clips are picked, dragged (along their lane or onto another lane of the
same group, never out of it) and trimmed like any clip. Clips of the level dragged onto an
open group's lane, and media dropped there, go into that group (移入群組: intoGroupRequested,
groupDropped; the lane lights up while they would).

編輯區域 (set_matte_region): while a clip's compound mask is edited that way, the mask's
compound shows as a ghost over the clip, placed where its time runs along the clip; dragging
it sideways picks which part of the compound cuts the clip (matteOffsetLive while dragging,
matteOffsetEdited on release: the compound's time at the clip's start).

Audio and video clips show their waveform (scaled by the clip volume and fades). Track
headers have mute / solo buttons (sound), a hide button (pictures) and a padlock: a locked
track (hatched) cannot have its clips selected or grabbed, and moves and drops skip it.
Click a track header to select the track (Ctrl+click: in or out of the selection, Shift+click:
every track from the last one picked); selected tracks are deleted together (Delete, or the
header's menu), and the menu's 清除空軌道 removes every track with nothing on it. Drag a
header up or down to move its track (a picked one: every picked track of its kind, pictures
among pictures and sound among sound; a line shows where: tracksReordered); the menu's
上移 / 下移 still move one row. Picking
tracks clears the clip selection and picking clips clears the tracks'.
Drag the headers' right edge to make them wider (longer track names) or narrower; the
width (header_w) is kept in view_state with the scroll and zoom. On the ruler that edge is
left to the playhead.
"""
import copy
import math
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QMenu, QScrollBar, QWidget

from .. import components, curves, edit, project, waveform
from .params import param_menu

US = 1_000_000
MEDIA_MIME = "application/x-kiasecut-media"
FX_MIME = "application/x-kiasecut-fx"                # a filter dragged from the VFX tab: its ref
COLORS = {"video": "#3f6585", "image": "#3f6585", "compound": "#5d5488",    # by type, muted as in
          "text": "#7c5574", "audio": "#3e7055", "filter": "#8a6f2e", "static": "#3f7378", "group": "#7a5c96",
          "component": "#4d5fa8"}                              # DaVinci Resolve
ROW_BG = QColor("#1f1f21")
WAVE_TILE = 256                                      # waveforms are drawn in pixmaps this wide,
WAVE_BYTES = 64 << 20                                # kept up to about this much memory


# a clip is filled with its colour at this alpha and outlined in the colour itself, so even a
# light colour leaves its name readable
FILL_ALPHA = 0x50


ROW_SHADE = 0.3                                      # a coloured row's brightness, of its colour's


def row_color(track):
    """A track's row background: a deep shade of its colour (its hue and saturation at
    ROW_SHADE of its brightness), the dark row grey without one."""
    if not track.get("color"):
        return ROW_BG
    c = QColor(track["color"])
    return QColor.fromHsv(max(0, c.hsvHue()), c.hsvSaturation(), max(ROW_BG.value(), round(c.value() * ROW_SHADE)))


def clip_color(c, track=None):
    """A clip's colour: its own, else its track's (a coloured track colours the clips that
    keep the default), else the default for its kind."""
    return QColor(c.get("color") or (track or {}).get("color") or COLORS.get(clip_kind(c), "#555"))


def clip_kind(c):
    """What a clip is for its colour: its type, or "static" / "component" (元件)."""
    return "component" if components.of_clip(c) else "static" if project.is_static(c) else c["type"]
RULER_H, TRACK_H, AUDIO_H, HEADER_W = 26, 34, 52, 140   # HEADER_W: the track headers' default width
HEADER_MIN, HEADER_MAX = 110, 520                          # how narrow / wide dragging makes them
BTN = 18                                             # header button size
MIN_H, MAX_H = 22, 240                               # track heights
EDGE_PX, SNAP_PX, DRAG_PX = 6, 8, 3
PLAYHEAD_PX = 4                 # how near the playhead line the mouse grabs it
BEAT_PX = 5                                          # beat grid lines at least this far apart show
# beat grid lines by their place in the beat (edit.beat_grid; 0: a bar's first beat): colour,
# tick length - a bar's first beat reaches about half way down, the other beats less
BEAT_COLORS = {0: "#ffd34d", 1: "#ffd34d", 2: "#ff8a3d", 3: "#ff6bd5", 4: "#4dd2ff", 6: "#b48cff"}
BEAT_TICKS = {0: (0.55, 12, 2.5), 1: (0.3, 8, 1.8), 2: (0.24, 7, 1.5), 3: (0.2, 6, 1.4), 4: (0.2, 6, 1.4),
              6: (0.15, 5, 1.2)}                    # share of the clip's height, at least px; pen width


def level_stretch(keys, t, tol_db=0.05):
    """Indices of the keys bounding a level stretch of a volume line at clip time t: the two
    around t when they have the same volume, the first / last alone before / after them;
    None on a sloping stretch."""
    after = next((i for i, k in enumerate(keys) if k[0] > t), len(keys))
    if after == 0:
        return (0,)
    if after == len(keys):
        return (len(keys) - 1,)
    a, b = keys[after - 1][1], keys[after][1]
    db = lambda g: 20 * math.log10(g) if g > 1e-5 else -100.0
    return (after - 1, after) if abs(db(a) - db(b)) <= tol_db else None


def timecode(us, fps):
    """mm:ss.ff, the frame number as wide as the largest one (240 per second: .000 - .239)."""
    s = us / US
    n = max(1, int(fps))
    return f"{int(s // 60):02d}:{int(s % 60):02d}.{int(round((s % 1) * fps)) % n:0{max(2, len(str(n - 1)))}d}"


class Timeline(QWidget):
    seekRequested = Signal(int)                      # frame
    clipSelected = Signal(object)                    # clip dict or None (the primary selection)
    groupMoveRequested = Signal(list, int, int)      # clip ids, shift us, rows down (negative: up)
    dupMoveRequested = Signal(list, int, int)        # the same with Alt held: copies go there, the clips stay
    matteOffsetLive = Signal(str, int)               # clip id, its compound mask's t_off: while dragged
    matteOffsetEdited = Signal(str, int)             # the same on release
    keyMoveRequested = Signal(str, int, int)         # clip id, keyframe clip time from, to (us)
    marksChanged = Signal()                          # the time selection (mark_in / mark_out) changed
    volumeEdited = Signal(str, object)               # clip id, new volume (number or {"keys": ...})
    moveRequested = Signal(str, int, str)            # clip id, start us, track id
    trimRequested = Signal(str, str, int)            # clip id, "start" | "end", time us
    trackAction = Signal(str, str)                   # action, track id
    tracksReordered = Signal(list)                   # every track id of the level, in the new order on screen
    intoGroupRequested = Signal(list, str, str, int)  # clip ids, group id, its track id, start (level time)
    groupDropped = Signal(list, list, str, str, int)  # media idents, file paths, group id, its track id, start
    clipAction = Signal(str, str)                    # action, clip id
    paramBind = Signal(str, str, list)               # inside a component: parameter id ("": new), prop, clip ids
    paramUnbind = Signal(list)                       # inside a component: [(clip id, prop)] let go
    mediaDropped = Signal(str, str, int)             # library item id, track id or "", start us
    mediaManyDropped = Signal(list, str, int, bool)  # library item ids, track id or "", start us, across (Alt)
    compoundDropped = Signal(str, str, int)          # compound id, track id or "", start us
    assetDropped = Signal(str, str, int)             # built-in asset ("asset:…"), track id or "", start us
    filterDropped = Signal(str, str, str, int)       # filter ref, clip id or "", track id or "", start us
    filesDropped = Signal(list, str, int, bool)      # file manager paths, track id or "", start us, across (Alt)
    replaceDropped = Signal(str, str)                # media id (library item, "cmp:<id>" or "asset:…"), clip id: Alt + drop
    newTrackRequested = Signal(str, int, bool)       # clip id, start us, on top (else bottom)
    clipDragging = Signal(str, int, int)             # clip id, start us, duration us: while dragging
    peaksReady = Signal(str)                         # emitted from the waveform thread
    vzoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proj = None
        self.fps = 60.0
        self.edit_fps = None                       # 時間線精度 (frames per second), None: the project's
        self.pos = 0
        self.px_per_s = 40.0
        self.scroll_s = 0.0
        self.header_w = HEADER_W                   # width of the track headers: drag their right edge
        self._primary = None
        self.selected_ids = set()
        self.selected_tracks = set()               # ids of the tracks picked by their headers
        self.track_anchor = None                   # the track a Shift+click selects from
        self.band = None                           # selection box (QRectF) while dragging
        self.snapping = True                       # 自動吸附: moves / trims snap to edges and the playhead
        self.rows = []
        self.drag = None
        self.mark_in = self.mark_out = None        # export range, frames
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setAcceptDrops(True)
        self.drop_at = None                        # (row, us) while library media hovers
        self.hover_playhead = False                # the mouse is on the playhead line (it can be dragged)
        self.drop_clip = None                      # clip a filter from the VFX tab would go onto
        self.drop_replace = False                  # drop_clip would get the dragged media as its source (Alt)
        self.matte_region = None                   # 編輯區域: {clip, t_off, duration, name} or None
        self.open_groups = set()                   # ids of the groups shown open (their lanes)
        self.into_lane = None                      # the open group's lane a drag or drop would go into
        self.drop_many = None                      # (count, across) while several media items hover
        self.tops = []                             # y of each row (on screen)
        self.vzoom = 1.0                           # track height factor
        self.heights = {}                          # track id -> height set by dragging its edge
        self.scroll_y = 0
        self.vbar = QScrollBar(Qt.Vertical, self)
        self.vbar.hide()
        self.vbar.valueChanged.connect(self._on_vscroll)
        self.rows_end = RULER_H
        self.peaks = None                          # waveform.Peaks
        self._waves = OrderedDict()                # waveform tiles, least recently drawn first
        self._wave_bytes = 0
        self.peaksReady.connect(self._on_peaks)

    def set_peaks(self, peaks):
        self.peaks = peaks
        self._waves.clear()
        self._wave_bytes = 0
        self.update()

    def _on_peaks(self, _path):
        self.update()

    # -- data -----------------------------------------------------------------------------------
    def _bound(self):
        """{clip id: [(param, prop)]} the open component's parameters set (none outside one)."""
        comp = (self.proj or {}).get("open_component")
        return components.bound(comp) if comp is not None else {}

    def set_project(self, proj, keep_view=False):
        self.proj = proj
        self.fps = self.edit_fps or proj["fps"]
        visual = [t for t in proj["tracks"] if t["kind"] != "audio"]
        audio = [t for t in proj["tracks"] if t["kind"] == "audio"]
        self.rows = list(reversed(visual)) + audio
        self.selected_tracks &= {t["id"] for t in self.rows}
        self._layout()
        self.drag = None
        if not keep_view:
            self.selected_id = None
            self.zoom_fit()
        self._layout()
        self.update()

    def zoom_fit(self):
        """Shift+Z: the whole timeline in view."""
        if self.proj is None:
            return
        dur = max(self.proj["duration_us"] / US, 1)
        self.px_per_s = min(self.max_zoom(), max(2.0, (self.width() - self.header_w - 20) / dur))
        self.scroll_s = 0
        self.update()

    def zoom_by(self, k, at_s):
        """Ctrl+= / Ctrl+-: zoom the time by k, at_s (seconds) staying where it is on screen -
        or, out of view, put a fifth of the way in."""
        x = self._x(at_s)
        if not self.header_w <= x <= self.width():
            x = self.header_w + (self.width() - self.header_w) * 0.2
        self.px_per_s = min(self.max_zoom(), max(1.0, self.px_per_s * k))
        self.scroll_s = max(0.0, at_s - (x - self.header_w) / self.px_per_s)
        self.update()

    @property
    def selected_id(self):
        """The primary selected clip (shown in the inspector); setting it selects only it."""
        return self._primary

    @selected_id.setter
    def selected_id(self, cid):
        self._primary = cid
        self.selected_ids = {cid} if cid else set()

    def level_clips(self):
        """Every clip of the open level, those inside groups included."""
        return [c for t in project.all_tracks(self.rows) for c in t["clips"]]

    def selected_clips(self):
        return [c for c in self.level_clips() if c["id"] in self.selected_ids]

    def selected_clips_primary_first(self):
        return sorted(self.selected_clips(), key=lambda c: c["id"] != self._primary)

    def locked_ids(self):
        """Clips on locked tracks: they can never be selected."""
        return {c["id"] for t in self.rows if project.locked(t) for c in project.walk_clips([t])
                if c["id"] in {k["id"] for k in self.level_clips()}}

    def set_selection(self, ids, primary=None):
        ids = set(ids) - self.locked_ids()
        if primary not in ids:
            primary = next((c["id"] for c in self.selected_clips() if c["id"] in ids), None) \
                or next((c["id"] for c in self.level_clips() if c["id"] in ids), None)
        self._primary = primary
        self.selected_ids = ids if primary else set()
        if self.selected_ids:
            self.selected_tracks = set()
        self.clipSelected.emit(self.selected)
        self.update()

    def select_all(self):
        ids = {c["id"] for t in self.rows if not project.locked(t) for c in t["clips"]}
        self.set_selection(ids, self._primary if self._primary in ids else None)

    @property
    def selected(self):
        return next((c for c in self.level_clips() if c["id"] == self.selected_id), None)

    def select(self, clip):
        if clip and clip["id"] in self.locked_ids():
            clip = None
        self.selected_id = clip["id"] if clip else None
        if clip:
            self.selected_tracks = set()
        self.clipSelected.emit(clip)
        self.update()

    def select_tracks(self, ids, anchor=None):
        """Pick tracks (by id) by their headers; the clip selection goes."""
        self.selected_tracks = {t["id"] for t in self.rows if t["id"] in set(ids)}
        if anchor is not None:
            self.track_anchor = anchor
        if self.selected_ids:
            self.set_selection(set())
        self.update()

    def _click_header(self, row, mods):
        tid = self.rows[row]["id"]
        if mods & Qt.ShiftModifier and self.track_anchor in [t["id"] for t in self.rows]:
            a = next(i for i, t in enumerate(self.rows) if t["id"] == self.track_anchor)
            lo, hi = sorted((a, row))
            self.select_tracks({t["id"] for t in self.rows[lo:hi + 1]} | (
                self.selected_tracks if mods & Qt.ControlModifier else set()))
        elif mods & Qt.ControlModifier:
            self.select_tracks(self.selected_tracks ^ {tid}, tid)
        else:
            self.select_tracks({tid}, tid)

    def view_state(self):
        """Where the view is (scroll, zoom, track heights, header width), to save with the project."""
        return {"scroll_s": round(self.scroll_s, 4), "px_per_s": round(self.px_per_s, 4),
                "scroll_y": self.scroll_y, "heights": dict(self.heights), "header_w": self.header_w,
                "open_groups": sorted(self.open_groups)}

    def max_zoom(self):
        """Px per second at the closest zoom: 40 px per frame, at least 2000."""
        return max(2000.0, 40.0 * self.fps)

    def set_view_state(self, v):
        """Put the view back where view_state() was (missing parts stay as they are)."""
        if not v:
            return
        self.scroll_s = max(0.0, float(v.get("scroll_s", self.scroll_s)))
        self.px_per_s = min(self.max_zoom(), max(1.0, float(v.get("px_per_s", self.px_per_s))))
        if isinstance(v.get("heights"), dict):
            self.heights = {k: min(MAX_H, max(MIN_H, int(h))) for k, h in v["heights"].items()
                            if isinstance(h, (int, float))}
        self.scroll_y = int(v.get("scroll_y", self.scroll_y))
        if isinstance(v.get("open_groups"), list):
            self.open_groups = {str(g) for g in v["open_groups"]}
        if isinstance(v.get("header_w"), (int, float)):
            self.header_w = int(min(HEADER_MAX, max(HEADER_MIN, v["header_w"])))
        self._layout()
        self.update()

    def _on_header_edge(self, pos):
        """Whether pos is on the right edge of the track headers (drag it to widen them)."""
        return abs(pos.x() - self.header_w) <= 4 and pos.y() >= RULER_H

    def set_position(self, frame, follow=True):
        """Move the playhead; with follow, scroll so it stays in view (playback, keys)."""
        self.pos = frame
        x = self._x(frame / self.fps)
        if follow and (x > self.width() - 30 or x < self.header_w):
            self.scroll_s = max(0.0, frame / self.fps - (self.width() - self.header_w) * 0.2 / self.px_per_s)
        self.update()

    # -- geometry -------------------------------------------------------------------------------
    def _x(self, sec):
        return self.header_w + (sec - self.scroll_s) * self.px_per_s

    def _sec(self, x):
        return (x - self.header_w) / self.px_per_s + self.scroll_s

    def base_h(self, i):
        """A row's own height (its clips' bars), without the lanes of open groups."""
        t = self.rows[i]
        h = self.heights.get(t["id"])
        return h or round((AUDIO_H if t["kind"] == "audio" else TRACK_H) * self.vzoom)

    def row_h(self, i):
        return self.base_h(i) + self.extra_lanes(self.rows[i]) * self.lane_h()

    # -- groups: open ones show their tracks as lanes under their track ------------------------
    def lane_h(self):
        return max(MIN_H, round(TRACK_H * 0.85 * self.vzoom))

    def is_open(self, c):
        return project.is_group(c) and c["id"] in self.open_groups

    def extra_lanes(self, track):
        """Lanes a track needs under it: the most any of its open groups takes."""
        return max((self.group_lanes(c) for c in track["clips"] if self.is_open(c)), default=0)

    def group_lanes(self, g):
        return sum(1 + self.extra_lanes(ct) for ct in g["tracks"])

    def lanes(self, i):
        """[{group, track, y, h, abs0}] of row i's open groups (nested ones too): each group's
        tracks, top one first, each followed by the lanes of the open groups on it; abs0 is
        where the group's time 0 is on the timeline."""
        out, lh = [], self.lane_h()

        def walk(g, y, abs0):
            for ct in reversed(g["tracks"]):
                out.append({"group": g, "track": ct, "y": y, "h": lh, "abs0": abs0})
                y += lh
                sub = 0
                for k in ct["clips"]:
                    if self.is_open(k):
                        walk(k, y, abs0 + k["start_us"])
                        sub = max(sub, self.group_lanes(k))
                y += sub * lh
        for c in self.rows[i]["clips"]:
            if self.is_open(c):
                walk(c, self.tops[i] + self.base_h(i), c["start_us"])
        return out

    def _lane_hit(self, pos):
        """(lane, clip, zone) under pos in the lanes of open groups, or (lane / None, None, None)."""
        row = self._row_at(pos.y())
        if row is None or pos.y() < self.tops[row] + self.base_h(row) or project.locked(self.rows[row]):
            return None, None, None
        sec = self._sec(pos.x()) * US
        for ln in self.lanes(row):
            g = ln["group"]
            if not (ln["y"] <= pos.y() < ln["y"] + ln["h"]) or not (ln["abs0"] <= sec <= ln["abs0"] + g["duration_us"]):
                continue
            for c in ln["track"]["clips"]:
                x0 = self._x((ln["abs0"] + c["start_us"]) / US)
                x1 = self._x((ln["abs0"] + c["start_us"] + c["duration_us"]) / US)
                if x0 - EDGE_PX / 2 <= pos.x() <= x1 + EDGE_PX / 2:
                    if x1 - x0 > 3 * EDGE_PX and pos.x() <= x0 + EDGE_PX:
                        return ln, c, "start"
                    if x1 - x0 > 3 * EDGE_PX and pos.x() >= x1 - EDGE_PX:
                        return ln, c, "end"
                    if x0 <= pos.x() <= x1:
                        return ln, c, "body"
            return ln, None, None
        return None, None, None

    def _into_lane(self, pos, ids=()):
        """The lane of an open group under pos that clips ids (none: new media) could go into."""
        ln = self._lane_hit(pos)[0]
        if ln is None or ln["track"]["kind"] == "audio":
            return None
        g = ln["group"]
        inside = {g["id"]} | {k["id"] for k in project.walk_clips(g["tracks"])}
        if ids and (set(ids) & inside or any(project.is_group(c) and any(k is g for k in project.walk_clips(c["tracks"]))
                                             for c in self.level_clips() if c["id"] in ids)):
            return None
        return ln

    def _track_slot(self, y, sound):
        """Where dragged tracks would go: before the row at the returned index, among the rows
        of their kind (pictures / sound)."""
        mine = [i for i, t in enumerate(self.rows) if (t["kind"] == "audio") == sound]
        if not mine:
            return None
        for i in mine:
            if y < self.tops[i] + self.row_h(i) / 2:
                return i
        return mine[-1] + 1

    def _paint_track_drag(self, p):
        d = self.drag
        if not d or d["mode"] != "tracks" or not d["moved"] or d["slot"] is None:
            return
        for i, t in enumerate(self.rows):                # the tracks being moved: dimmed in place
            if t["id"] in d["ids"]:
                p.fillRect(QRectF(0, self.tops[i], self.width(), self.row_h(i) - 1), QColor(0, 0, 0, 90))
        i = d["slot"]
        y = self.tops[i] if i < len(self.rows) else self.tops[i - 1] + self.row_h(i - 1)
        p.fillRect(QRectF(0, y - 1.5, self.width(), 3), QColor("#e6e6e6"))

    def _paint_into(self, p):
        ln = self.into_lane
        if ln is None:
            return
        x0 = max(self._x(ln["abs0"] / US), self.header_w)
        x1 = self._x((ln["abs0"] + ln["group"]["duration_us"]) / US)
        r = QRectF(x0, ln["y"], max(2.0, x1 - x0), ln["h"] - 1)
        p.fillRect(r, QColor(122, 92, 150, 70))
        p.setPen(QPen(QColor("#b48ee0"), 1.5))
        p.drawRect(r)
        p.drawText(r.adjusted(6, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "移入群組：" + (ln["group"].get("name") or ""))

    def _fold_hit(self, pos):
        """The group whose ▸ / ▾ is under pos, or None."""
        row = self._row_at(pos.y())
        if row is None:
            return None
        spots = [(c, self.tops[row], c["start_us"]) for c in self.rows[row]["clips"] if project.is_group(c)]
        spots += [(c, ln["y"], ln["abs0"] + c["start_us"]) for ln in self.lanes(row) for c in ln["track"]["clips"]
                  if project.is_group(c)]
        for c, y, s in spots:
            x = max(self._x(s / US), self.header_w)
            if QRectF(x + 2, y + 3, 16, 16).contains(pos):
                return c
        return None

    def toggle_group(self, g):
        """Open or fold a group (not an edit: kept with the view)."""
        self.open_groups ^= {g["id"]}
        self._layout()
        self.update()

    def _draw_lanes(self, p, i, dim):
        w = self.width()
        for ln in self.lanes(i):
            g = ln["group"]
            x0 = max(self._x(ln["abs0"] / US), self.header_w)
            x1 = min(self._x((ln["abs0"] + g["duration_us"]) / US), w)
            if x1 <= x0:
                continue
            p.fillRect(QRectF(x0, ln["y"], x1 - x0, ln["h"] - 1), QColor(0, 0, 0, 70))
            p.fillRect(QRectF(x0, ln["y"], 2, ln["h"] - 1), QColor(COLORS["group"]))
            for c in ln["track"]["clips"]:
                d = self.drag
                if d and d.get("mode", "").startswith("lane_") and d.get("moved") and d["clip"] is c:
                    continue                             # (drawn where it is being dragged)
                self._draw_clip(p, c, ln["y"], ln["abs0"] + c["start_us"], c["duration_us"],
                                track=ln["track"], h=ln["h"], dim=dim)
        d = self.drag
        if d and d.get("mode", "").startswith("lane_") and d.get("moved") and d.get("row") == i:
            ln = d["lane_to"]
            self._draw_clip(p, d["clip"], ln["y"], ln["abs0"] + d["start"], d["end"] - d["start"], ghost=True,
                            track=ln["track"], h=ln["h"])

    def _layout(self):
        """Row positions for the current heights and vertical scroll; updates the scroll bar."""
        view = max(1, self.height() - RULER_H)
        content = sum(self.row_h(i) for i in range(len(self.rows))) + AUDIO_H   # room to drop below
        top = max(0, content - view)
        self.scroll_y = min(max(0, self.scroll_y), top)
        self.vbar.blockSignals(True)
        self.vbar.setRange(0, top)
        self.vbar.setPageStep(view)
        self.vbar.setSingleStep(20)
        self.vbar.setValue(self.scroll_y)
        self.vbar.blockSignals(False)
        self.vbar.setGeometry(self.width() - 12, RULER_H, 12, view)
        self.vbar.setVisible(top > 0)
        self.tops, y = [], RULER_H - self.scroll_y
        for i in range(len(self.rows)):
            self.tops.append(y)
            y += self.row_h(i)
        self.rows_end = y

    def _on_vscroll(self, v):
        self.scroll_y = v
        self._layout()
        self.update()

    def set_vzoom(self, z):
        """Scale every track's height (tracks resized by hand keep their proportion)."""
        z = min(MAX_H / TRACK_H, max(MIN_H / TRACK_H, z))
        k = z / self.vzoom
        self.heights = {tid: min(MAX_H, max(MIN_H, round(h * k))) for tid, h in self.heights.items()}
        self.vzoom = z
        self._layout()
        self.vzoomChanged.emit(z)
        self.update()

    def _row_part(self, y):
        """(row, fraction of its height) at widget y, to keep in place while zooming; below the
        rows: (row count, px below them)."""
        for i, top in enumerate(self.tops):
            if y < top + self.row_h(i):
                return i, min(1.0, max(0.0, (y - top) / self.row_h(i)))
        return len(self.rows), y - self.rows_end

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    def _edge_at(self, pos):
        """Row whose bottom edge is under pos in the header (for resizing), or None."""
        if pos.x() >= self.header_w:
            return None
        for i, top in enumerate(self.tops):
            if abs(pos.y() - (top + self.row_h(i) - 1)) <= 3 and pos.y() > RULER_H:
                return i
        return None

    def _row_at(self, y):
        """The row at y; none on the ruler (rows scrolled up under it must not be grabbed
        through it: dragging there always moves the playhead)."""
        if y < RULER_H:
            return None
        for i, top in enumerate(self.tops):
            if top <= y < top + self.row_h(i):
                return i
        return None

    def header_buttons(self, i):
        """[(flag, rect)] of a track header's toggle buttons, right-aligned."""
        tr = self.rows[i]
        if tr["kind"] == "audio":
            flags = ["locked", "muted", "solo"]
        else:
            flags = ["locked", "hidden"]
            if any(c["type"] in ("video", "compound") for c in tr["clips"]):
                flags.append("muted")
        y = self.tops[i] + (self.row_h(i) - 2 - BTN) / 2
        return [(f, QRectF(self.header_w - 6 - (len(flags) - k) * (BTN + 3), y, BTN, BTN))
                for k, f in enumerate(flags)]

    def _hit(self, pos):
        """(row, clip, zone) under pos; zone is 'start', 'end' or 'body'."""
        row = self._row_at(pos.y())
        if row is None:
            return None, None, None
        if project.locked(self.rows[row]):                  # its clips cannot be grabbed
            return row, None, None
        if pos.y() >= self.tops[row] + self.base_h(row):    # (the lanes of open groups)
            return row, None, None
        for c in self.rows[row]["clips"]:
            x0 = self._x(c["start_us"] / US)
            x1 = self._x((c["start_us"] + c["duration_us"]) / US)
            if x0 - EDGE_PX / 2 <= pos.x() <= x1 + EDGE_PX / 2:
                if x1 - x0 > 3 * EDGE_PX:
                    if pos.x() <= x0 + EDGE_PX:
                        return row, c, "start"
                    if pos.x() >= x1 - EDGE_PX:
                        return row, c, "end"
                if x0 <= pos.x() <= x1:
                    return row, c, "body"
        return row, None, None

    def _snap_targets(self, exclude, playhead=True):
        """Times a drag snaps to: 0, the playhead (unless it is what moves), and every other
        clip's start, end, keyframes and beats (BPM alignment); exclude is a clip or a set of
        clip ids (a moving group)."""
        cands = [0, self.pos / self.fps * US] if playhead else [0]
        for tr in self.rows:
            for c in tr["clips"]:
                if c is not exclude and not (isinstance(exclude, set) and c["id"] in exclude):
                    s = c["start_us"]
                    cands += [s, s + c["duration_us"]]
                    cands += [s + k for k in edit.key_times(c) if 0 <= k <= c["duration_us"]]
                    cands += [t for t, _ in self._beat_lines(c)]
        return cands

    def _beat_lines(self, c, lo=None, hi=None, bars=False):
        """A clip's beat grid lines [(time us, place in the beat)] that are far enough apart
        at this zoom to be seen (halves can show while sixths are too dense)."""
        beat = c.get("beat")
        if not beat or not beat.get("on"):
            return []
        period_px = 60 / beat["bpm"] * self.px_per_s
        div = beat.get("div", 1)
        if div < 1:                                      # a line every 2 / 4 beats
            return edit.beat_grid(c, lo, hi, bars) if period_px / div >= BEAT_PX else []
        return [(t, d) for t, d in edit.beat_grid(c, lo, hi, bars) if period_px / max(d, 1) >= BEAT_PX]

    def _snap(self, t_us, exclude, playhead=True):
        """Snap a time to the nearest _snap_targets within SNAP_PX. With snapping off, times
        are left as they are."""
        if not self.snapping:
            return t_us
        best, limit = t_us, SNAP_PX / self.px_per_s * US
        for t in self._snap_targets(exclude, playhead):
            if abs(t - t_us) < limit:
                best, limit = t, abs(t - t_us)
        return best

    def _snap_span(self, start, length, exclude):
        """Start of a moved span [start, start + length): snapped by whichever of its ends
        lands on a target nearer; unchanged when neither does."""
        moved = [x for x in (self._snap(start, exclude), self._snap(start + length, exclude) - length)
                 if x != start and x >= 0]
        return min(moved, key=lambda x: abs(x - start)) if moved else start

    def _seek_to(self, x):
        """Move the playhead to screen x, snapped like a dragged clip (but not to itself)."""
        t = self._snap(max(0.0, self._sec(x)) * US, None, playhead=False)
        if self.drag and self.drag["mode"] == "seek":
            self.drag["t"] = t
        self.seekRequested.emit(max(0, round(t / US * self.fps)))

    def _on_playhead(self, pos):
        """Whether pos is on the playhead line (below the ruler: the ruler seeks anyway)."""
        x = self._x(self.pos / self.fps)
        return x >= self.header_w and pos.x() >= self.header_w and pos.y() >= RULER_H and abs(pos.x() - x) <= PLAYHEAD_PX

    def _snap_guides(self):
        """Times where the current drag sits on a snap target (drawn as guide lines)."""
        d = self.drag
        if self.snapping and d and d["mode"] == "seek" and "t" in d:
            t = d["t"]
            return [t] if any(abs(t - k) < 1 for k in self._snap_targets(None, playhead=False)) else []
        if not (self.snapping and d and d.get("moved") and d.get("clip")):
            return []
        c = d["clip"]
        if d["mode"] == "key":
            edges, exclude = [c["start_us"] + d["t"]] if "t" in d else [], c
        elif d["mode"] == "group":
            sh = d.get("shift", 0)
            edges, exclude = [c["start_us"] + sh, c["start_us"] + c["duration_us"] + sh], d["ids"]
        elif d["mode"] in ("body", "start", "end"):
            edges = [d.get("start", c["start_us"]), d.get("end", c["start_us"] + c["duration_us"])]
            exclude = c
        else:
            return []
        targets = self._snap_targets(exclude)
        return sorted({e for e in edges if any(abs(e - t) < 1 for t in targets)})

    # -- painting -------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()                                  # never leave the painter open on an error

    def _paint(self, p):
        p.fillRect(self.rect(), QColor("#161618"))
        if not self.proj:
            p.setPen(QColor("#777"))
            p.drawText(self.rect(), Qt.AlignCenter, "檔案 > 匯入剪映草稿")
            return
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        p.fillRect(0, 0, w, RULER_H, QColor("#1e1e21"))
        p.fillRect(0, RULER_H - 1, w, 1, QColor("#0e0e10"))
        steps = sorted({n / self.fps for n in (1, 2, 5, 10, 20)} | {0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300})
        step = next(s for s in steps if s * self.px_per_s >= 70)
        p.setPen(QColor("#4a4a50"))
        if self.px_per_s / self.fps >= 6:                # a mark for every frame (時間線精度)
            f = math.floor(self.scroll_s * self.fps)
            while self._x(f / self.fps) < w:
                x = self._x(f / self.fps)
                if x >= self.header_w:
                    p.drawLine(int(x), RULER_H - 3, int(x), RULER_H)
                f += 1
        p.setPen(QColor("#8a8a90"))
        p.setFont(QFont("Segoe UI", 8))
        n = int(self.scroll_s / step)
        while self._x(n * step) < w:
            t = n * step
            x = self._x(t)
            if x >= self.header_w:
                p.drawLine(int(x), RULER_H - 6, int(x), RULER_H)
                label = timecode(t * US, self.fps)
                p.drawText(int(x) + 3, RULER_H - 9, label if step < 1 else label[:5])
            n += 1
        if self.mark_in is not None or self.mark_out is not None:
            a = self._x((self.mark_in or 0) / self.fps)
            b = self._x(((self.mark_out if self.mark_out is not None else
                          self.proj["duration_us"] / US * self.fps)) / self.fps)
            a, b = max(a, self.header_w), max(b, self.header_w)
            p.fillRect(QRectF(a, 0, b - a, RULER_H), QColor(255, 255, 255, 70))
            p.fillRect(QRectF(a, self.height() - 3, b - a, 3), QColor(255, 255, 255, 160))
            p.setPen(QPen(QColor("#e6e6e6"), 2))
            if self.mark_in is not None and a > self.header_w:
                p.drawLine(int(a), 0, int(a), RULER_H)
            if self.mark_out is not None and b > self.header_w:
                p.drawLine(int(b), 0, int(b), RULER_H)
        # a clip being moved / trimmed is drawn at its new place (other drags have no ghost)
        dragged = self.drag["clip"] if self.drag and self.drag["moved"] and self.drag["mode"] in ("body", "start", "end")             else None
        group = self.drag["ids"] if self.drag and self.drag["moved"] and self.drag["mode"] == "group" else ()
        tracks = self.proj["tracks"]
        p.save()
        p.setClipRect(QRectF(0, RULER_H, w, self.height() - RULER_H))
        for i, tr in enumerate(self.rows):
            if self.tops[i] > self.height() or self.tops[i] + self.row_h(i) < RULER_H:
                continue
            y, h = self.tops[i], self.row_h(i)
            p.fillRect(0, y, w, h - 1, row_color(tr))       # the track colour: its row, and clip_color
            picked = tr["id"] in self.selected_tracks
            p.fillRect(0, y, self.header_w, h - 1, QColor("#3a3a42" if picked else "#242427"))   # as in Resolve
            p.fillRect(self.header_w - 1, y, 1, h - 1, QColor("#0e0e10"))
            if tr.get("color"):
                p.fillRect(0, y, 3, h - 1, QColor(tr["color"]))
            if picked:
                p.setPen(QPen(QColor("#c9c9cd"), 1))
                p.drawRect(QRectF(0.5, y + 0.5, self.header_w - 2, h - 2))
            # V1 is the bottom picture track, A1 the first sound track (Resolve's numbering)
            if tr["kind"] == "audio":
                label = f"A{sum(1 for t in self.rows[:i] if t['kind'] == 'audio') + 1}"
            else:
                label = f"V{sum(1 for t in self.rows[i:] if t['kind'] != 'audio')}"
            p.setPen(QColor("#8e8e94"))
            f0 = p.font()
            fb = QFont(f0)
            fb.setBold(True)
            p.setFont(fb)
            p.drawText(QRectF(8, y, 26, min(h - 1, 26)), Qt.AlignVCenter, label)
            p.setFont(f0)
            btns = self.header_buttons(i)
            name_w = (btns[0][1].left() if btns else self.header_w) - 40
            p.setPen(QColor("#c8c8cc"))
            name = p.fontMetrics().elidedText(tr.get("name") or tr["kind"], Qt.ElideRight, int(name_w))
            gain = tr.get("gain", 1.0)
            if abs(gain - 1.0) > 1e-6:
                p.drawText(QRectF(34, y + 5, name_w, 16), Qt.AlignVCenter, name)
                p.setPen(QColor("#8a8a90"))
                db = "-∞" if gain <= 0 else f"{20 * math.log10(gain):+.1f}"
                p.drawText(QRectF(34, y + 21, name_w, 16), Qt.AlignVCenter, f"{db} dB")
            else:
                p.drawText(QRectF(34, y, name_w, min(h - 1, 26)), Qt.AlignVCenter, name)
            for flag, r in btns:
                self._draw_button(p, flag, r, bool(tr.get(flag)))
            dim = (project.sounds(tr, tracks) <= 0) if tr["kind"] == "audio" else not project.visible(tr)
            copying = bool(self.drag and self.drag.get("dup"))      # (Alt: the clips stay, copies move)
            for c in tr["clips"]:
                if copying or (c is not dragged and c["id"] not in group):
                    self._draw_clip(p, c, y, c["start_us"], c["duration_us"], track=tr, h=self.base_h(i), dim=dim)
            self._draw_lanes(p, i, dim)
            if project.locked(tr):                          # locked: hatched over, nothing to grab
                p.save()
                p.setClipRect(QRectF(self.header_w, RULER_H, w - self.header_w, self.height() - RULER_H))
                p.fillRect(QRectF(self.header_w, y, w - self.header_w, h - 2), QBrush(QColor(0, 0, 0, 70)))
                p.fillRect(QRectF(self.header_w, y, w - self.header_w, h - 2), QBrush(QColor(255, 255, 255, 26), Qt.BDiagPattern))
                p.restore()
        self._paint_into(p)
        self._paint_track_drag(p)
        if group:                                         # the moving clips, on the rows they will land on
            dr = self.drag.get("drow", 0)
            for i, tr in enumerate(self.rows):
                for c in tr["clips"]:
                    if c["id"] in group and 0 <= i + dr < len(self.rows):
                        j = i + dr
                        self._draw_clip(p, c, self.tops[j], c["start_us"] + self.drag["shift"], c["duration_us"],
                                        ghost=True, track=self.rows[j], h=self.base_h(j))
        if dragged:
            d = self.drag
            h = self.base_h(d["row"])
            if d.get("new") == "top":                   # landing on a new top track
                p.fillRect(QRectF(self.header_w, RULER_H, w - self.header_w, 3), QColor("#e6e6e6"))
                y = RULER_H - h + 2
            elif d.get("new") == "bottom":              # landing on a new last audio track
                p.fillRect(QRectF(self.header_w, self.rows_end, w - self.header_w, 3), QColor("#e6e6e6"))
                y = self.rows_end + 2
            else:
                y = self.tops[d["row"]]
            self._draw_clip(p, dragged, y, d["start"], d["end"] - d["start"], ghost=True,
                            track=None if d.get("new") else self.rows[d["row"]], h=h)
        self._draw_matte_region(p)
        if self.band is not None:
            p.setPen(QPen(QColor("#e6e6e6"), 1, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 35))
            p.drawRect(self.band)
        if self.drop_clip is not None:
            lit = self.replace_lit() if self.drop_replace else [self.drop_clip]
            for c in lit:
                row = next((i for i, t in enumerate(self.rows) if c in t["clips"]), None)
                if row is None:
                    continue
                x0 = max(self._x(c["start_us"] / US), self.header_w)
                x1 = self._x((c["start_us"] + c["duration_us"]) / US)
                p.setPen(QPen(QColor("#ffb020"), 2))
                p.setBrush(QColor(255, 176, 32, 40))
                box = QRectF(x0, self.tops[row] + 2, max(2.0, x1 - x0), self.row_h(row) - 6)
                p.drawRect(box)
                if self.drop_replace and c is self.drop_clip:   # (written on the part of the clip in view)
                    shown = box.intersected(QRectF(self.header_w, box.top(), w - self.header_w, box.height()))
                    p.setPen(QColor("#ffd34d"))
                    p.drawText(shown.adjusted(6, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight,
                               "替換素材" + (f"（{len(lit)} 個）" if len(lit) > 1 else ""))
        if self.drop_at is not None:
            row, t = self.drop_at
            dx = self._x(t / US)
            p.setPen(QPen(QColor("#e6e6e6"), 2, Qt.DashLine))
            p.drawLine(int(dx), RULER_H, int(dx), self.height())
            if row is not None:
                p.fillRect(QRectF(self.header_w, self.tops[row], w - self.header_w, self.row_h(row) - 2),
                           QColor(255, 255, 255, 30))
            if self.drop_many is not None:              # how several items will be laid out
                n, across = self.drop_many
                p.setPen(QColor("#e6e6e6"))
                p.drawText(QPointF(dx + 6, RULER_H + 14),
                           f"{n} 個素材：接在後面" if across else f"{n} 個素材：上下疊放（按 Alt 接在後面）")
        p.setPen(QPen(QColor("#ffd34d"), 1))                     # where a drag has snapped
        for t in self._snap_guides():
            gx = self._x(t / US)
            if gx >= self.header_w:
                p.drawLine(QPointF(gx, RULER_H), QPointF(gx, self.height()))
        p.restore()
        x = self._x(self.pos / self.fps)
        if x >= self.header_w:
            grab = self.hover_playhead or (self.drag and self.drag["mode"] == "seek")
            p.setPen(QPen(QColor("#ff6b6d" if grab else "#ff4d4f"), 3 if grab else 2))
            p.drawLine(int(x), 0, int(x), self.height())

    @staticmethod
    def clip_label(c):
        if c.get("compound") and not c.get("named"):
            return c["compound"].get("name") or c.get("name") or "複合片段"
        if c.get("named") or not c.get("text"):
            return c.get("name") or c["type"]
        return c["text"]["content"]

    @staticmethod
    def _draw_button(p, flag, r, on):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e6e6e6") if on
                   else QColor("#2c2c31"))
        p.drawRoundedRect(r, 3, 3)
        ink = QColor("#111114") if on else QColor("#a0a0a6")
        p.setPen(QPen(ink, 1.3))
        cx, cy = r.center().x(), r.center().y()
        if flag == "solo":
            p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            p.drawText(r, Qt.AlignCenter, "S")
        elif flag == "locked":                  # a padlock; shut when locked
            p.setBrush(ink)
            p.drawRoundedRect(QRectF(cx - 4.5, cy - 0.5, 9, 6.5), 1.2, 1.2)
            p.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - 2.8, cy - 0.5)
            path.lineTo(cx - 2.8, cy - 3)
            path.arcTo(QRectF(cx - 2.8, cy - 5.8, 5.6, 5.6), 180, -180)
            if on:
                path.lineTo(cx + 2.8, cy - 0.5)
            p.drawPath(path)
        elif flag == "muted":                   # a speaker; crossed when muted
            p.setBrush(ink)
            p.drawPolygon(QPolygonF([QPointF(cx - 6, cy - 2), QPointF(cx - 3, cy - 2), QPointF(cx + 1, cy - 5),
                                     QPointF(cx + 1, cy + 5), QPointF(cx - 3, cy + 2), QPointF(cx - 6, cy + 2)]))
            p.setBrush(Qt.NoBrush)
            if on:
                p.drawLine(QPointF(cx + 3, cy - 3), QPointF(cx + 7, cy + 3))
                p.drawLine(QPointF(cx + 7, cy - 3), QPointF(cx + 3, cy + 3))
            else:
                p.drawArc(QRectF(cx - 2, cy - 4, 7, 8), -60 * 16, 120 * 16)
        else:                                   # an eye; crossed when hidden
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(cx - 6, cy - 3.5, 12, 7))
            p.setBrush(ink)
            p.drawEllipse(QPointF(cx, cy), 1.8, 1.8)
            if on:
                p.drawLine(QPointF(cx - 6, cy + 5), QPointF(cx + 6, cy - 5))
        p.restore()

    def _wave(self, c, x, wx0, wx1, height):
        """Waveform of an audio / video clip starting at screen x, between screen wx0..wx1, as
        (x, pixmap) tiles of a white shape on transparent; [] when there is none (yet). Tiles are
        measured from the clip's start, so scrolling or moving the clip draws the same pixmaps."""
        if self.peaks is None or not c.get("media") or c["type"] not in ("audio", "video"):
            return []
        if project.frozen(c) is not None:                   # (a frozen clip is silent)
            return []
        res = self.peaks.get(c["media"]["path"])
        if res is None or not len(res[0]):
            return []
        dpr = self.devicePixelRatioF()
        base = (c["media"]["path"], c["duration_us"], c.get("source_start_us", 0), str(c.get("speed")),
                str(c.get("volume", 1.0)), c.get("fade_in_us", 0), c.get("fade_out_us", 0), height, self.px_per_s, dpr)
        tiles = []
        for i in range(max(0, int((wx0 - x) // WAVE_TILE)), int((wx1 - x) // WAVE_TILE) + 1):
            key = base + (i,)
            pix = self._waves.get(key)
            if pix is None:
                pix = self._waves[key] = self._wave_tile(c, res, i, height, dpr)
                self._wave_bytes += pix.width() * pix.height() * 4
                while self._wave_bytes > WAVE_BYTES and len(self._waves) > 1:
                    old = self._waves.popitem(last=False)[1]
                    self._wave_bytes -= old.width() * old.height() * 4
            else:
                self._waves.move_to_end(key)
            tiles.append((x + i * WAVE_TILE, pix))
        return tiles

    def _wave_tile(self, c, res, i, height, dpr):
        """Tile i (WAVE_TILE px from the clip's start on) of a clip's waveform, height px tall
        (in device pixels: dpr times as many)."""
        peaks, lead = res
        n, height = round(WAVE_TILE * dpr), round(height * dpr)
        t0, t1 = i * WAVE_TILE / self.px_per_s, (i + 1) * WAVE_TILE / self.px_per_s     # seconds into the clip
        src, k = c.get("source_start_us", 0) / US, project.speed(c)
        hi, lo = waveform.columns(peaks, lead, src + t0 * k, src + t1 * k, n)   # highest / lowest sample per px
        # the clip's volume and fades, sampled every few columns
        vol, fi, fo, dur = c.get("volume", 1.0), c.get("fade_in_us", 0), c.get("fade_out_us", 0), c["duration_us"]
        if curves.is_animated(vol) or fi or fo:
            ts = np.linspace(t0, t1, n // 4) * US
            g = np.array([curves.value(vol, t) for t in ts], np.float32)
            if fi:
                g *= np.clip(ts / fi, 0, 1)
            if fo:
                g *= np.clip((dur - ts) / fo, 0, 1)
            gain = np.interp(np.linspace(t0, t1, n) * US, ts, g)
        else:
            gain = curves.value(vol, 0)
        # quieter parts stay visible; the line stays at least a hair thick
        shape = lambda a: np.sign(a) * np.clip(np.abs(a * gain), 0, 1) ** 0.7
        hi, lo = np.maximum(shape(hi), 0.02), np.minimum(shape(lo), -0.02)
        half = height / 2
        top, bottom = (half - hi * half)[None, :], (half - lo * half)[None, :]
        rows = np.arange(height, dtype=np.float32)[:, None]
        # how much of each pixel the shape covers (smooth top and bottom edges), as premultiplied white
        a = (np.clip(np.minimum(rows + 1, bottom) - np.maximum(rows, top), 0, 1) * 255 + 0.5).astype(np.uint32)
        argb = np.ascontiguousarray(a * 0x01010101)
        img = QImage(argb.data, n, height, n * 4, QImage.Format_ARGB32_Premultiplied)
        pix = QPixmap.fromImage(img.copy())                # (copied: the array goes away)
        pix.setDevicePixelRatio(dpr)
        return pix

    def _draw_clip(self, p, c, y, start, dur, ghost=False, track=None, h=TRACK_H, dim=False):
        w = self.width()
        x0, x1 = self._x(start / US), self._x((start + dur) / US)
        if x1 < self.header_w or x0 > w:
            return
        r = QRectF(max(x0, self.header_w) + 0.5, y + 3, max(1.0, x1 - max(x0, self.header_w) - 1), h - 8)
        kind = clip_kind(c)
        col = clip_color(c, track)
        sel = c["id"] in self.selected_ids
        if dim:
            col = col.darker(220)
        # the colour on the outline, a see-through tint of it inside (FILL_ALPHA): light
        # colours no longer swallow the name; a selected clip is tinted a little more, outlined white
        fill = QColor(col)
        fill.setAlpha(FILL_ALPHA * (3 if sel else 2) // 2 * (3 if ghost else 4) // 4)
        edge = QColor(col)
        edge.setAlpha(190 if ghost else 255)
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawRect(r)
        p.setBrush(Qt.NoBrush)
        if sel:
            p.setPen(QPen(edge, 4))
            p.drawRect(r.adjusted(1, 1, -1, -1))
            p.setPen(QPen(QColor("#ffffff"), 1.5))
        else:
            p.setPen(QPen(edge, 2))
        p.drawRect(r.adjusted(1, 1, -1, -1))
        audio = c["type"] == "audio"
        wx0, wx1 = max(r.left() + 1, self.header_w), min(r.right() - 1, w)
        if wx1 - wx0 >= 2:
            # sound clips: the waveform under the label; video: a thin strip at the bottom
            wt, wh = (r.top() + 15, r.height() - 17) if audio else (r.bottom() - 10, 9)
            if not audio and r.height() > 40:            # tall video rows: a bigger strip
                wt, wh = r.top() + r.height() / 2, r.height() / 2 - 1
            wt, wh = round(wt), round(wh)
            tiles = self._wave(c, x0, wx0, wx1, wh) if wh >= 4 and (audio or r.height() >= 24) else []
            if tiles:
                p.save()
                p.setClipRect(r)
                p.setOpacity((90 if dim else 235 if audio else 200) / 255)
                for tx, pix in tiles:
                    p.drawPixmap(QPointF(tx, wt), pix)
                p.restore()
        if r.width() > 24:
            p.setPen(QColor("#9a9aa0") if dim else QColor("#f2f2f2"))
            label = self.clip_label(c).replace("\n", " ")
            if c["type"] == "compound":
                label = ("⧉ " if c.get("timeline_id") else components.ICON + " " if kind == "component"
                         else "◧ " if kind == "static" else "▣ ") + label
            elif c["type"] == "filter":
                label = "✦ " + label
            elif project.is_group(c):                    # its ▸ / ▾ (click to open or fold it)
                label = ("▾ " if self.is_open(c) else "▸ ") + label + f"  ({sum(len(t['clips']) for t in c['tracks'])})"
            elif c.get("effects"):
                label += "  ✦" + (str(len(c["effects"])) if len(c["effects"]) > 1 else "")
            if c["id"] in self._bound():                 # a parameter of the open component sets it
                label += "  " + components.ICON
            lr = r.adjusted(4, 0, -2, 0)
            if audio and r.height() > 20:
                lr.setHeight(16)
            elif c["type"] == "video" and r.height() >= 24:
                lr.setBottom(wt - 1 if r.height() > 40 else r.bottom() - 9)
            p.drawText(lr, Qt.AlignVCenter, label)
        row = next((i for i, t in enumerate(self.rows) if c in t["clips"]), None)
        if row is not None and not ghost and abs(self.tops[row] - y) < 0.5:
            self._draw_volume(p, c, row, r)
        if c.get("beat", {}).get("on") and r.height() > 10:
            # BPM alignment: a tick per grid line along the top, longer and yellow on the beat
            # (the grid moves with a dragged clip)
            shift = start - c["start_us"]
            lo, hi = self._sec(self.header_w) * US - shift, self._sec(w) * US - shift
            lines = self._beat_lines(c, lo, hi, bars=True)
            if lines:
                p.save()
                p.setClipRect(r)
                pens, lengths = {}, {}
                for d, col in BEAT_COLORS.items():
                    col = QColor(col)
                    col.setAlpha(110 if dim else 235)
                    share, least, width = BEAT_TICKS[d]
                    pens[d] = QPen(col, width, Qt.SolidLine, Qt.FlatCap)
                    lengths[d] = min(r.height() - 2, max(least, r.height() * share))
                for t, d in lines:
                    bx = self._x((t + shift) / US)
                    p.setPen(pens.get(d, pens[1]))
                    p.drawLine(QPointF(bx, r.top() + 1), QPointF(bx, r.top() + 1 + lengths.get(d, lengths[1])))
                p.restore()
        if c["id"] == self.selected_id and not ghost:
            # keyframes of the selected clip, as diamonds along its bottom edge
            d = self.drag if self.drag and self.drag["mode"] == "key" and self.drag["clip"] is c else None
            p.setPen(QPen(QColor("#111114"), 1))
            for k in edit.key_times(c):
                moving = d is not None and abs(k - d["t0"]) <= edit.KEY_TOL_US
                kx = self._x((start + (d["t"] if moving else k)) / US)
                if self.header_w <= kx <= w:
                    ky = r.bottom() - 5
                    p.setBrush(QColor("#ffffff") if moving else QColor("#ffb020"))
                    p.drawPolygon([QPointF(kx, ky - 5), QPointF(kx + 5, ky), QPointF(kx, ky + 5), QPointF(kx - 5, ky)])

    # -- 編輯區域 (a compound mask's part) ------------------------------------------------------
    def set_matte_region(self, region):
        """{clip: id, t_off: us, duration: the compound's us, name} to show, or None."""
        if region != self.matte_region:
            self.matte_region = region
            self.update()

    def _matte_rect(self):
        """(screen rect of the ghost, the clip) or (None, None)."""
        mr = self.matte_region
        if not mr:
            return None, None
        for i, t in enumerate(self.rows):
            for c in t["clips"]:
                if c["id"] == mr["clip"]:
                    d = self.drag if self.drag and self.drag.get("mode") == "matte" else None
                    off = d["t_off"] if d else mr["t_off"]
                    k = project.speed(c)
                    x0 = self._x((c["start_us"] - off / k) / US)
                    x1 = self._x((c["start_us"] + (mr["duration"] - off) / k) / US)
                    y, h = self.tops[i], self.row_h(i)
                    return QRectF(x0, y + 2, max(4.0, x1 - x0), h - 5), c
        return None, None

    def _draw_matte_region(self, p):
        r, c = self._matte_rect()
        if r is None:
            return
        p.save()
        p.setClipRect(QRectF(self.header_w, RULER_H, self.width() - self.header_w, self.height() - RULER_H))
        p.setPen(QPen(QColor("#d6a8ff"), 1.5, Qt.DashLine))
        p.setBrush(QColor(170, 110, 255, 60))
        p.drawRect(r)
        p.setPen(QColor("#f0e0ff"))
        name = self.matte_region.get("name") or "複合片段"
        p.drawText(r.adjusted(6, 0, -6, 0), Qt.AlignLeft | Qt.AlignBottom, f"⧉ {name}（編輯區域：左右拖曳）")
        p.restore()

    # -- volume line ----------------------------------------------------------------------------
    DB_LO, DB_HI = -40.0, 20.0

    def _vol_band(self, c, row):
        """(top, bottom) of the area the volume line moves in, or None (no line on this clip)."""
        if "volume" not in c or c["type"] not in ("audio", "video"):
            return None
        h = self.row_h(row)
        top, bottom = self.tops[row] + 5, self.tops[row] + h - 7       # the clip's whole height
        if c["type"] == "video" and h < 44 or bottom - top < 10:
            return None
        return top, bottom

    def _vol_y(self, g, band):
        db = 20 * math.log10(g) if g > 1e-5 else self.DB_LO
        f = (min(max(db, self.DB_LO), self.DB_HI) - self.DB_LO) / (self.DB_HI - self.DB_LO)
        return band[1] - f * (band[1] - band[0])

    def _vol_of_y(self, y, band):
        f = (band[1] - y) / max(1.0, band[1] - band[0])
        db = self.DB_LO + min(max(f, 0.0), 1.0) * (self.DB_HI - self.DB_LO)
        return 0.0 if f <= 0 else 10 ** (db / 20)

    def _volume(self, c):
        """The clip's volume, or the one being dragged."""
        d = self.drag
        if d and d["mode"] in ("vol", "volkey") and d["clip"] is c:
            return d["vol"]
        return c.get("volume", 1.0)

    def _vol_hit(self, pos, alt=False):
        """("vol" | "volkey", clip, row, key index or the keys a "vol" drag moves) under pos, or
        None. A keyframed line is only grabbed on a level stretch (its keys move), or anywhere
        with alt (every key: None)."""
        row = self._row_at(pos.y())
        if row is None or pos.x() < self.header_w or project.locked(self.rows[row]):
            return None
        for c in self.rows[row]["clips"]:
            band = self._vol_band(c, row)
            x0, x1 = self._x(c["start_us"] / US), self._x((c["start_us"] + c["duration_us"]) / US)
            if band is None or not x0 + EDGE_PX <= pos.x() <= x1 - EDGE_PX:
                continue
            vol = c.get("volume", 1.0)
            if curves.is_animated(vol):
                for i, k in enumerate(vol["keys"]):
                    kx = self._x((c["start_us"] + k[0]) / US)
                    if abs(pos.x() - kx) <= 5 and abs(pos.y() - self._vol_y(k[1], band)) <= 5:
                        return "volkey", c, row, i
            t = (self._sec(pos.x()) * US) - c["start_us"]
            if abs(pos.y() - self._vol_y(curves.value(vol, t), band)) <= 4:
                if alt or not curves.is_animated(vol):
                    return "vol", c, row, None
                seg = level_stretch(vol["keys"], t)
                if seg is not None:
                    return "vol", c, row, seg
        return None

    def _draw_volume(self, p, c, row, r):
        band = self._vol_band(c, row)
        if band is None:
            return
        vol = self._volume(c)
        x0, x1 = max(r.left(), self.header_w), min(r.right(), self.width())
        p.save()
        p.setClipRect(r)
        p.setPen(QPen(QColor("#e6e6e6"), 1.4))
        if curves.is_animated(vol):
            pts = []
            x = x0
            while True:
                t = self._sec(x) * US - c["start_us"]
                pts.append(QPointF(x, self._vol_y(curves.value(vol, t), band)))
                if x >= x1:
                    break
                x = min(x + 3, x1)
            p.drawPolyline(QPolygonF(pts))
            p.setPen(QPen(QColor("#111114"), 1))
            p.setBrush(QColor("#ffb020"))
            for k in vol["keys"]:
                kx = self._x((c["start_us"] + k[0]) / US)
                if x0 - 4 <= kx <= x1 + 4:
                    p.drawEllipse(QPointF(kx, self._vol_y(k[1], band)), 3.5, 3.5)
        else:
            y = self._vol_y(curves.value(vol, 0), band)
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
        d = self.drag
        if d and d["mode"] in ("vol", "volkey") and d["clip"] is c and d["moved"]:
            g = d["shown"]
            text = "-∞ dB" if g <= 1e-5 else f"{20 * math.log10(g):+.1f} dB"
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(d["x"] + 8, band[0] - 2, 90, 14), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.restore()

    # -- mouse ----------------------------------------------------------------------------------
    def _key_hit(self, pos):
        """(clip, keyframe clip time) of the selected clip's diamond under pos, or (None, None)."""
        c = self.selected
        if c is None:
            return None, None
        row = next((i for i, t in enumerate(self.rows) if c in t["clips"]), None)
        if row is None:
            return None, None
        ky = self.tops[row] + 3 + (self.row_h(row) - 8) - 5
        if abs(pos.y() - ky) > 7 or pos.y() < RULER_H:
            return None, None
        best = None
        for k in edit.key_times(c):
            dx = abs(pos.x() - self._x((c["start_us"] + k) / US))
            if dx <= 7 and (best is None or dx < best[0]):
                best = (dx, k)
        return (c, best[1]) if best else (None, None)

    def mousePressEvent(self, e):
        if self.proj and e.button() == Qt.RightButton and e.position().x() >= self.header_w:
            # right-drag selects time; a right click without moving opens the menu (on release)
            self.drag = {"clip": None, "mode": "region", "moved": False, "pos": e.position(),
                         "t0": self._snap(max(0.0, self._sec(e.position().x())) * US, None)}
            return
        if self.proj and e.button() == Qt.MiddleButton:     # drag the view (Ctrl: zoom it)
            zoom = bool(e.modifiers() & Qt.ControlModifier)
            self.drag = {"clip": None, "mode": "zoom" if zoom else "pan", "moved": False, "pos": e.position(),
                         "s": self.scroll_s, "y": self.scroll_y, "px": self.px_per_s,
                         "at": self._sec(e.position().x()), "row": self._row_part(max(RULER_H, e.position().y())),
                         "vz": self.vzoom, "heights": dict(self.heights)}
            self.setCursor(Qt.SizeAllCursor if zoom else Qt.ClosedHandCursor)
            return
        if not self.proj or e.button() != Qt.LeftButton:
            return
        if self._on_header_edge(e.position()):                   # widen / narrow the track headers
            self.drag = {"clip": None, "mode": "header", "x0": e.position().x(), "w0": self.header_w, "moved": False}
            return
        if e.position().x() < self.header_w:
            edge = self._edge_at(e.position())
            if edge is not None:
                self.drag = {"clip": None, "mode": "resize", "row": edge, "y0": e.position().y(),
                             "h0": self.row_h(edge), "moved": False}
                return
            row = self._row_at(e.position().y())
            if row is not None:
                for flag, r in self.header_buttons(row):
                    if r.contains(e.position()):
                        self.trackAction.emit("toggle:" + flag, self.rows[row]["id"])
                        return
                mods = e.modifiers()
                tid = self.rows[row]["id"]
                later = tid in self.selected_tracks and not mods & (Qt.ControlModifier | Qt.ShiftModifier)
                if not later:                                # (a picked one: it may be dragged with the rest)
                    self._click_header(row, mods)
                sound = self.rows[row]["kind"] == "audio"
                moving = [t["id"] for t in self.rows if t["id"] in self.selected_tracks
                          and (t["kind"] == "audio") == sound] if tid in self.selected_tracks else [tid]
                self.drag = {"clip": None, "mode": "tracks", "row": row, "y0": e.position().y(), "moved": False,
                             "ids": moving, "slot": None, "later": later}
            return
        if self.selected_tracks:                                  # a click among the clips: no tracks picked
            self.selected_tracks = set()
            self.update()
        pos = e.position()
        mr, mc = self._matte_rect()
        if mr is not None and mr.contains(pos) and not e.modifiers():     # 編輯區域: the compound's part
            self.drag = {"clip": None, "mode": "matte", "x0": pos.x(), "t_off0": self.matte_region["t_off"],
                         "t_off": self.matte_region["t_off"], "cid": mc["id"], "speed": project.speed(mc),
                         "moved": False}
            return
        if self._on_playhead(pos) and not e.modifiers():         # the playhead line: drag it
            self.drag = {"clip": None, "mode": "seek", "moved": False}
            self.update()
            return
        mods = e.modifiers()
        vh = self._vol_hit(pos, alt=mods == Qt.AltModifier) if mods in (Qt.NoModifier, Qt.AltModifier) else None
        if vh is not None:
            kind, c, row, i = vh
            self.select(c)
            vol = copy.deepcopy(c.get("volume", 1.0))
            self.drag = {"clip": c, "mode": kind, "row": row, "i": i, "y0": pos.y(), "x0": pos.x(), "x": pos.x(),
                         "orig": copy.deepcopy(vol), "vol": vol, "moved": False,
                         "shown": curves.value(vol, self._sec(pos.x()) * US - c["start_us"]) if kind == "vol"
                         else vol["keys"][i][1]}
            return
        kc, kt = self._key_hit(pos)
        if kc is not None and not e.modifiers():
            self.drag = {"clip": kc, "mode": "key", "t0": kt, "t": kt, "x0": pos.x(), "moved": False}
            return
        fold = self._fold_hit(pos)
        if fold is not None and not e.modifiers():             # a group's ▸ / ▾: open or fold it
            self.toggle_group(fold)
            return
        adding = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        ln, lc, lzone = self._lane_hit(pos)
        if lc is not None:                                     # a clip on an open group's lane
            if adding:
                ids = set(self.selected_ids) ^ {lc["id"]}
                self.set_selection(ids, lc["id"] if lc["id"] in ids else None)
                return
            self.select(lc)
            row = self._row_at(pos.y())
            self.drag = {"clip": lc, "mode": "lane_" + lzone, "x0": pos.x(), "row": row, "lane0": ln,
                         "lane_to": ln, "start": lc["start_us"], "end": lc["start_us"] + lc["duration_us"],
                         "moved": False}
            return
        row, c, zone = self._hit(pos)
        if c is None:
            if pos.y() < RULER_H or row is None and pos.y() < self.rows_end:
                self.drag = {"clip": None, "mode": "seek", "moved": False}
                self._seek_to(pos.x())
                self.update()
                return
            # empty track space: a click seeks and clears, a drag draws a selection box
            self.drag = {"clip": None, "mode": "band", "moved": False, "x0": pos.x(), "y0": pos.y(),
                         "base": set(self.selected_ids) if adding else set(), "remove": None}
            return
        if adding:
            # Ctrl / Shift: the clip flips in or out of the selection, and dragging on draws a box
            # whose clips follow it (all selected, or all deselected when it was selected)
            base = set(self.selected_ids)
            remove = c["id"] in base
            ids = base - {c["id"]} if remove else base | {c["id"]}
            self.set_selection(ids, None if remove else c["id"])
            self.drag = {"clip": c, "mode": "band", "moved": False, "x0": pos.x(), "y0": pos.y(),
                         "base": base, "remove": remove}
            return
        if c["id"] not in self.selected_ids or len(self.selected_ids) == 1:
            self.select(c)
        else:
            self.set_selection(self.selected_ids, c["id"])
        if len(self.selected_ids) > 1 and zone == "body":
            self.drag = {"clip": c, "mode": "group", "x0": pos.x(), "moved": False, "shift": 0,
                         "ids": set(self.selected_ids), "adding": adding, "row0": row, "drow": 0}
            return
        self.drag = {"clip": c, "mode": zone, "x0": pos.x(), "row0": row, "row": row,
                     "start": c["start_us"], "end": c["start_us"] + c["duration_us"], "moved": False}

    def mouseMoveEvent(self, e):
        pos = e.position()
        d = self.drag
        if d is not None and d["mode"] in ("body", "group") and d["moved"] and not d.get("dup"):
            ids = d["ids"] if d["mode"] == "group" else [d["clip"]["id"]]
            self.into_lane = self._into_lane(pos, ids)
        if d is None:
            on = bool(self.proj) and self._on_playhead(pos) and not self._on_header_edge(pos)    # (the edge wins)
            if on != self.hover_playhead:
                self.hover_playhead = on
                self.update()
            if on:
                self.setCursor(Qt.SizeHorCursor)
                return
            if self.proj and self._on_header_edge(pos):
                self.setCursor(Qt.SplitHCursor)
                return
            if self.proj and self._edge_at(pos) is not None:
                self.setCursor(Qt.SizeVerCursor)
                return
            if self.proj and self._key_hit(pos)[0] is not None:
                self.setCursor(Qt.SizeHorCursor)
                return
            vh = self._vol_hit(pos, alt=bool(e.modifiers() & Qt.AltModifier)) if self.proj else None
            if vh is not None:
                self.setCursor(Qt.SizeAllCursor if vh[0] == "volkey" else Qt.SizeVerCursor)
                return
            _, c, zone = self._hit(pos) if self.proj else (None, None, None)
            self.setCursor(Qt.SizeHorCursor if zone in ("start", "end") else Qt.ArrowCursor)
            return
        if d["mode"].startswith("lane_"):                       # a clip of an open group
            if not d["moved"] and abs(pos.x() - d["x0"]) < DRAG_PX:
                return
            d["moved"] = True
            c, ln0 = d["clip"], d["lane0"]
            g, abs0 = ln0["group"], ln0["abs0"]
            dt = (pos.x() - d["x0"]) / self.px_per_s * US
            s0, e0 = c["start_us"], c["start_us"] + c["duration_us"]
            if d["mode"] == "lane_body":
                start = self._snap_span(abs0 + s0 + dt, e0 - s0, c) - abs0
                d["start"] = min(max(0.0, start), g["duration_us"] - (e0 - s0))
                d["end"] = d["start"] + (e0 - s0)
                for ln in self.lanes(d["row"]):          # another lane of the same group, same kind
                    if ln["group"] is g and ln["y"] <= pos.y() < ln["y"] + ln["h"] and \
                            ln["track"]["kind"] == ln0["track"]["kind"]:
                        d["lane_to"] = ln
            elif d["mode"] == "lane_start":
                d["start"] = min(max(0.0, self._snap(abs0 + s0 + dt, c) - abs0), e0 - US / self.fps)
            else:
                d["end"] = max(min(g["duration_us"], self._snap(abs0 + e0 + dt, c) - abs0), s0 + US / self.fps)
            self.clipDragging.emit(c["id"], int(round(abs0 + d["start"])), int(round(d["end"] - d["start"])))
            self.update()
            return
        if d["mode"] == "matte":
            if not d["moved"] and abs(pos.x() - d["x0"]) < DRAG_PX:
                return
            d["moved"] = True
            frame = US / self.fps
            off = d["t_off0"] - (pos.x() - d["x0"]) / self.px_per_s * US * d["speed"]
            d["t_off"] = int(round(off / frame) * frame)
            self.matteOffsetLive.emit(d["cid"], d["t_off"])
            self.update()
            return
        if d["mode"] == "region":
            if not d["moved"] and abs(pos.x() - d["pos"].x()) < DRAG_PX:
                return
            d["moved"] = True
            t = self._snap(max(0.0, self._sec(pos.x())) * US, None)
            a, b = sorted((d["t0"], t))
            self.mark_in = round(a / US * self.fps)
            self.mark_out = max(self.mark_in, round(b / US * self.fps) - 1)
            self.marksChanged.emit()
            self.update()
            return
        if d["mode"] in ("vol", "volkey"):
            if not d["moved"] and abs(pos.y() - d["y0"]) + abs(pos.x() - d["x0"]) < DRAG_PX:
                return
            d["moved"] = True
            d["x"] = pos.x()
            band = self._vol_band(d["clip"], d["row"])
            c, orig = d["clip"], d["orig"]
            if d["mode"] == "vol":                         # the whole volume (or a level stretch), in dB steps
                db = -(pos.y() - d["y0"]) / max(1.0, band[1] - band[0]) * (self.DB_HI - self.DB_LO)
                k = 10 ** (db / 20)
                clamp = lambda g: min(10.0, max(0.0, g * k))
                if curves.is_animated(orig):
                    moving = d["i"]                         # None: every key
                    d["vol"] = {"keys": [[q[0], clamp(q[1]) if moving is None or j in moving else q[1]] + q[2:]
                                         for j, q in enumerate(orig["keys"])]}
                    d["shown"] = clamp(curves.value(orig, self._sec(d["x0"]) * US - c["start_us"]))
                else:
                    d["vol"] = d["shown"] = clamp(curves.value(orig, 0))
            else:                                          # one keyframe: value and time
                keys = [list(q) for q in orig["keys"]]
                i = d["i"]
                frame = US / self.fps
                t = keys[i][0] + (pos.x() - d["x0"]) / self.px_per_s * US
                lo = keys[i - 1][0] + frame if i > 0 else 0
                hi = keys[i + 1][0] - frame if i + 1 < len(keys) else c["duration_us"]
                keys[i][0] = int(min(max(round(t / frame) * frame, lo), hi))
                keys[i][1] = min(10.0, self._vol_of_y(self._vol_y(orig["keys"][i][1], band) + pos.y() - d["y0"], band))
                d["vol"], d["shown"] = {"keys": keys}, keys[i][1]
            self.update()
            return
        if d["mode"] == "key":
            if not d["moved"] and abs(pos.x() - d["x0"]) < DRAG_PX:
                return
            d["moved"] = True
            c = d["clip"]
            frame = US / self.fps
            t = d["t0"] + (pos.x() - d["x0"]) / self.px_per_s * US
            g = c["start_us"] + t                                   # snap on the timeline's frames
            snapped = self._snap(g, c)                              # or onto other clips' edges / keys
            g = snapped if snapped != g else round(g / frame) * frame
            others = [k for k in edit.key_times(c) if abs(k - d["t0"]) > edit.KEY_TOL_US]
            lo = max([k + frame for k in others if k < d["t0"]], default=0)
            hi = min([k - frame for k in others if k > d["t0"]], default=c["duration_us"])
            d["t"] = int(round(min(max(g - c["start_us"], lo), hi)))
            self.update()
            return
        if d["mode"] == "pan":
            self.scroll_s = max(0.0, d["s"] - (pos.x() - d["pos"].x()) / self.px_per_s)
            self.vbar.setValue(round(d["y"] - (pos.y() - d["pos"].y())))
            self.update()
            return
        if d["mode"] == "zoom":                                 # around the press; right / up: in
            v = pos - d["pos"]
            self.px_per_s = min(self.max_zoom(), max(1.0, d["px"] * 2 ** (v.x() / 200)))
            self.scroll_s = max(0.0, d["at"] - (d["pos"].x() - self.header_w) / self.px_per_s)
            self.heights, self.vzoom = dict(d["heights"]), d["vz"]   # from the press: no rounding creep
            self.set_vzoom(d["vz"] * 2 ** (-v.y() / 200))
            i, f = d["row"]
            y = sum(self.row_h(j) for j in range(i)) + (f * self.row_h(i) if i < len(self.rows) else f)
            self.vbar.setValue(round(y - max(0.0, d["pos"].y() - RULER_H)))
            self.update()
            return
        if d["mode"] == "header":
            d["moved"] = True
            self.header_w = int(min(HEADER_MAX, max(HEADER_MIN, d["w0"] + pos.x() - d["x0"])))
            self.update()
            return
        if d["mode"] == "tracks":
            if not d["moved"] and abs(pos.y() - d["y0"]) < 4:
                return
            d["moved"] = True
            d["slot"] = self._track_slot(pos.y(), self.rows[d["row"]]["kind"] == "audio")
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            return
        if d["mode"] == "resize":
            h = min(MAX_H, max(MIN_H, round(d["h0"] + pos.y() - d["y0"])))
            self.heights[self.rows[d["row"]]["id"]] = h
            self._layout()
            self.update()
            return
        if d["mode"] == "seek":
            self._seek_to(pos.x())
            self.update()
            return
        if d["mode"] == "band":
            if not d["moved"] and abs(pos.x() - d["x0"]) + abs(pos.y() - d["y0"]) < DRAG_PX:
                return
            d["moved"] = True
            self.band = QRectF(QPointF(d["x0"], d["y0"]), pos).normalized()
            hit = {}                                    # clip id -> its distance from where the box began
            for i, tr in enumerate(self.rows):
                top, bottom = self.tops[i], self.tops[i] + self.row_h(i)
                if bottom < self.band.top() or top > self.band.bottom() or project.locked(tr):
                    continue
                for c in tr["clips"]:
                    left, right = self._x(c["start_us"] / US), self._x((c["start_us"] + c["duration_us"]) / US)
                    if left <= self.band.right() and right >= self.band.left():
                        hit[c["id"]] = math.hypot(max(left - d["x0"], 0, d["x0"] - right),
                                                  max(top - d["y0"], 0, d["y0"] - bottom))
            if d["remove"] is None and hit:              # the first clip reached: was it selected?
                d["remove"] = min(hit, key=hit.get) in d["base"]
            self.set_selection(d["base"] - hit.keys() if d["remove"] else d["base"] | hit.keys())
            return
        if d["mode"] in ("group", "body"):
            d["dup"] = bool(e.modifiers() & Qt.AltModifier)        # Alt: copies are dragged, the clips stay
        if d["mode"] == "group":
            if not d["moved"] and abs(pos.x() - d["x0"]) < DRAG_PX and self._row_at(pos.y()) == d["row0"]:
                return
            d["moved"] = True
            d["drow"] = self._group_rows(d, pos.y())
            c = d["clip"]
            dt = (pos.x() - d["x0"]) / self.px_per_s * US
            group = [k for t in self.rows for k in t["clips"] if k["id"] in d["ids"]]
            dt = max(dt, -min(k["start_us"] for k in group))
            # snap the clip under the mouse by its start or its end
            d["shift"] = self._snap_span(c["start_us"] + dt, c["duration_us"], d["ids"]) - c["start_us"]
            self.update()
            return
        if not d["moved"] and abs(pos.x() - d["x0"]) < DRAG_PX and self._row_at(pos.y()) == d["row0"]:
            return
        d["moved"] = True
        c = d["clip"]
        dt = (pos.x() - d["x0"]) / self.px_per_s * US
        s0, e0 = c["start_us"], c["start_us"] + c["duration_us"]
        if d["mode"] == "body":
            start = self._snap_span(max(0.0, s0 + dt), e0 - s0, c)
            d["start"], d["end"] = start, start + (e0 - s0)
            row = self._row_at(pos.y())
            audio = self.rows[d["row0"]]["kind"] == "audio"
            d["new"] = None
            if row is not None and (self.rows[row]["kind"] == "audio") == audio and \
                    (row == d["row0"] or not project.locked(self.rows[row])):     # (never onto a locked track)
                d["row"] = row
            elif row is None and not audio and pos.y() < RULER_H:
                d["new"] = "top"                        # above the top layer: a new top track
            elif row is None and audio and pos.y() >= self.rows_end:
                d["new"] = "bottom"                     # below the last audio row
        elif d["mode"] == "start":
            d["start"] = min(self._snap(s0 + dt, c), e0 - US / self.fps)
        else:
            d["end"] = max(self._snap(e0 + dt, c), s0 + US / self.fps)
        s1 = d.get("start", s0) if d["mode"] != "end" else s0
        e1 = d.get("end", e0) if d["mode"] != "start" else e0
        self.clipDragging.emit(c["id"], int(round(s1)), int(round(e1 - s1)))
        self.update()

    def _group_rows(self, d, y):
        """How many rows down (negative: up) the dragged group goes with the mouse at y: the row
        under the mouse, held to what every moving clip can reach among its own kind of track."""
        row = self._row_at(y)
        if row is None:
            row = 0 if y < RULER_H else len(self.rows) - 1
        n_vis = sum(1 for t in self.rows if t["kind"] != "audio")
        lo, hi = -len(self.rows), len(self.rows)
        moving = [i for i, t in enumerate(self.rows) if any(c["id"] in d["ids"] for c in t["clips"])]
        for i in moving:
            t = self.rows[i]
            a, b = (n_vis, len(self.rows) - 1) if t["kind"] == "audio" else (0, n_vis - 1)
            lo, hi = max(lo, a - i), min(hi, b - i)
        drow = min(max(row - d["row0"], lo), hi)
        if any(project.locked(self.rows[i + drow]) for i in moving if drow):
            return d.get("drow", 0)                         # (never onto a locked track: stay where it was)
        return drow

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        into, self.into_lane = self.into_lane, None
        if d and d["mode"] in ("body", "group") and d["moved"] and not d.get("dup") and into is not None:
            if d["mode"] == "group":                    # (onto a group's lane: into it, at the same shift)
                ids = sorted(d["ids"])
                start = min(k["start_us"] for k in self.level_clips() if k["id"] in d["ids"]) + d["shift"]
            else:
                ids, start = [d["clip"]["id"]], d["start"]
            self.intoGroupRequested.emit(ids, into["group"]["id"], into["track"]["id"], int(round(max(0, start))))
            self.update()
            return
        if d and d["mode"].startswith("lane_"):
            c = d["clip"]
            if d["moved"] and d["mode"] == "lane_body":
                self.moveRequested.emit(c["id"], int(round(d["start"])), d["lane_to"]["track"]["id"])
            elif d["moved"] and d["mode"] == "lane_start":
                self.trimRequested.emit(c["id"], "start", int(round(d["start"])))
            elif d["moved"]:
                self.trimRequested.emit(c["id"], "end", int(round(d["end"])))
            self.update()
            return
        if d and d["mode"] == "matte":
            if d["moved"]:
                self.matte_region = dict(self.matte_region, t_off=d["t_off"])
                self.matteOffsetEdited.emit(d["cid"], d["t_off"])
            self.update()
            return
        if d and d["mode"] == "region":
            if not d["moved"]:
                self._menu(e.position().toPoint(), e.globalPosition().toPoint())
            return
        if d and d["mode"] in ("vol", "volkey"):
            if d["moved"]:
                self.volumeEdited.emit(d["clip"]["id"], d["vol"])
            self.update()
            return
        if d and d["mode"] == "key":
            if d["moved"] and d["t"] != d["t0"]:
                self.keyMoveRequested.emit(d["clip"]["id"], int(d["t0"]), int(d["t"]))
            elif not d["moved"]:                        # a click goes to the keyframe
                self.seekRequested.emit(round((d["clip"]["start_us"] + d["t0"]) / US * self.fps))
            self.update()
            return
        if d and d["mode"] in ("pan", "zoom"):
            self.setCursor(Qt.ArrowCursor)
        if d and d["mode"] == "seek":
            self.update()                               # (its guide line goes)
        if d and d["mode"] == "tracks":
            self.setCursor(Qt.ArrowCursor)
            if d["moved"] and d["slot"] is not None:
                ids = [t["id"] for t in self.rows]
                order = edit.reordered(ids, set(d["ids"]), d["slot"])
                if order != ids:
                    self.tracksReordered.emit(order)
            elif not d["moved"] and d["later"]:              # a plain click on a picked track: it alone
                self._click_header(d["row"], Qt.NoModifier)
            self.update()
            return
        if not d or d["mode"] in ("seek", "resize", "pan", "zoom", "header"):
            return
        if d["mode"] == "band":
            self.band = None
            if not d["moved"] and d["clip"] is None:
                if not d["base"]:
                    self.select(None)
                self._seek_to(e.position().x())
            self.update()
            return
        if d["mode"] == "group":
            if d["moved"] and d.get("dup"):
                self.dupMoveRequested.emit(sorted(d["ids"]), int(round(d["shift"])), d["drow"])
            elif d["moved"] and (d["shift"] or d["drow"]):
                self.groupMoveRequested.emit(sorted(d["ids"]), int(round(d["shift"])), d["drow"])
            elif not d["moved"] and not d["adding"]:
                self.select(d["clip"])                  # a plain click picks one of the group
            self.update()
            return
        c = d["clip"]
        if not d["moved"]:                              # clicking a clip only selects it (as in
            self.update()                               # Jianying): the playhead stays put
            return
        if d["mode"] == "body" and d.get("dup"):
            self.dupMoveRequested.emit([c["id"]], int(round(d["start"] - c["start_us"])),
                                       0 if d.get("new") else d["row"] - d["row0"])
        elif d["mode"] == "body" and d.get("new"):
            self.newTrackRequested.emit(c["id"], int(round(d["start"])), d["new"] == "top")
        elif d["mode"] == "body":
            self.moveRequested.emit(c["id"], int(round(d["start"])), self.rows[d["row"]]["id"])
        elif d["mode"] == "start":
            self.trimRequested.emit(c["id"], "start", int(round(d["start"])))
        else:
            self.trimRequested.emit(c["id"], "end", int(round(d["end"])))
        self.update()

    # -- drops from the media library -----------------------------------------------------------
    def _accepts(self, md):
        return (bool(self.proj) and (md.hasFormat(MEDIA_MIME) or md.hasFormat(FX_MIME))) or md.hasUrls()

    def dragEnterEvent(self, e):
        if self._accepts(e.mimeData()):
            e.setDropAction(Qt.CopyAction)
            e.accept()

    def dragMoveEvent(self, e):
        if not self._accepts(e.mimeData()):
            return
        pos = e.position()
        if self.proj:
            self.drop_at = (self._drop_row(pos.y()), max(0.0, self._sec(pos.x())) * US)
            md = e.mimeData()
            n = len(self._media_ids(md)) if md.hasFormat(MEDIA_MIME) else len(self._file_paths(md))
            self.drop_many = (n, self._alt(e)) if n > 1 else None
            self.drop_replace = self._alt(e) and e.mimeData().hasFormat(MEDIA_MIME) and n <= 1
            if e.mimeData().hasFormat(FX_MIME):
                self.drop_clip = self._fx_target(pos)
            elif self.drop_replace:
                self.drop_clip = self._replace_target(pos)
            else:
                self.drop_clip = None
            if self.drop_clip is not None:                 # onto a clip: no time line, the clip is lit
                self.drop_at = None
            fx = e.mimeData().hasFormat(FX_MIME)
            self.into_lane = None if fx or self.drop_clip is not None else self._into_lane(pos)
            if self.into_lane is not None:                 # onto an open group's lane: it is lit
                self.drop_at = None
        e.setDropAction(Qt.CopyAction)                     # (Alt must not turn the drop into a link)
        e.accept()
        self.update()

    def _drop_row(self, y):
        """The row a drop at y lands on: none over a locked track (a new track is made instead)."""
        row = self._row_at(y)
        return None if row is None or project.locked(self.rows[row]) else row

    @staticmethod
    def _media_ids(md):
        """Media library items in a drag (not compounds or built-in assets)."""
        if not md.hasFormat(MEDIA_MIME):
            return []
        return [i for i in bytes(md.data(MEDIA_MIME)).decode().split(",") if i.startswith("m")]

    @staticmethod
    def _file_paths(md):
        """Files (or folders) dragged in from the file manager."""
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    @staticmethod
    def _alt(e):
        return bool((e.modifiers() | QApplication.queryKeyboardModifiers()) & Qt.AltModifier)

    def _replace_target(self, pos):
        """The clip whose source media dropped at pos with Alt would replace."""
        _, c, _ = self._hit(pos)
        return c if c is not None and c["type"] in edit.REPLACEABLE + ("audio",) else None

    def replace_lit(self):
        """The clips an Alt-drop on drop_clip would give the new source: it, and with it the
        other selected clips of its kind (pictures or sounds) when it is selected."""
        c = self.drop_clip
        if c is None or c["id"] not in self.selected_ids:
            return [c] if c is not None else []
        sound = c["type"] == "audio"
        return [c] + [k for k in self.selected_clips() if k is not c and
                      (k["type"] == "audio" if sound else k["type"] in edit.REPLACEABLE)]

    def _fx_target(self, pos):
        """The clip a filter dropped at pos goes onto (pictures, texts, compounds, filter clips)."""
        _, c, _ = self._hit(pos)
        return c if c is not None and c["type"] in edit.VISUAL else None

    def leaveEvent(self, e):
        if self.hover_playhead:
            self.hover_playhead = False
            self.update()

    def dragLeaveEvent(self, e):
        self.into_lane = None
        self.drop_at = self.drop_clip = self.drop_many = None
        self.drop_replace = False
        self.update()

    def dropEvent(self, e):
        self.drop_at = self.drop_clip = self.drop_many = None
        self.drop_replace = False
        self.into_lane = None
        pos = e.position()
        many = self._media_ids(e.mimeData())
        many = many if len(many) > 1 else None             # (with several, Alt lines them up instead)
        target = self._replace_target(pos) if self.proj and self._alt(e) and not many else None
        if target is not None and e.mimeData().hasFormat(MEDIA_MIME):     # Alt: replace that clip's source
            ident = bytes(e.mimeData().data(MEDIA_MIME)).decode().split(",")[0]
            self.replaceDropped.emit(ident, target["id"])
            e.setDropAction(Qt.CopyAction)
            e.accept()
            self.update()
            return
        if e.mimeData().hasFormat(FX_MIME):                  # a filter from the VFX tab
            if self.proj:
                ref = bytes(e.mimeData().data(FX_MIME)).decode("utf-8")
                row = self._drop_row(pos.y())
                c = self._fx_target(pos)
                tid = self.rows[row]["id"] if row is not None and self.rows[row]["kind"] != "audio" else ""
                self.filterDropped.emit(ref, c["id"] if c else "", tid, int(max(0.0, self._sec(pos.x())) * US))
                e.acceptProposedAction()
            self.update()
            return
        ln = self._into_lane(pos) if self.proj else None
        if ln is not None:                                   # onto an open group's lane: into the group
            md = e.mimeData()
            ids = [i for i in bytes(md.data(MEDIA_MIME)).decode().split(",") if i] if md.hasFormat(MEDIA_MIME) else []
            paths = [] if ids else self._file_paths(md)
            if ids or paths:
                self.groupDropped.emit(ids, paths, ln["group"]["id"], ln["track"]["id"],
                                       int(max(0.0, self._sec(pos.x())) * US))
                e.acceptProposedAction()
            self.update()
            return
        row = self._drop_row(pos.y()) if self.proj else None
        tid = self.rows[row]["id"] if row is not None else ""
        start = int(max(0.0, self._sec(pos.x())) * US) if self.proj else 0
        if not e.mimeData().hasFormat(MEDIA_MIME):           # files from the file manager
            paths = self._file_paths(e.mimeData())
            if paths:                                         # (stacked, or one after another with Alt)
                self.filesDropped.emit(paths, tid, start, self._alt(e))
                e.acceptProposedAction()
            self.update()
            return
        if many:                                         # several library items: one edit
            self.mediaManyDropped.emit(many, tid, start, self._alt(e))
            e.acceptProposedAction()
            self.update()
            return
        for ident in bytes(e.mimeData().data(MEDIA_MIME)).decode().split(","):
            if ident.startswith("cmp:"):                 # from the compound browser
                self.compoundDropped.emit(ident[4:], tid, start)
            elif ident.startswith("asset:"):             # from the 內建素材 tab
                self.assetDropped.emit(ident, tid, start)
            elif ident.startswith("m"):
                self.mediaDropped.emit(ident, tid, start)
        e.acceptProposedAction()
        self.update()

    def clear_marks(self):
        if self.mark_in is not None or self.mark_out is not None:
            self.mark_in = self.mark_out = None
            self.marksChanged.emit()
            self.update()

    def contextMenuEvent(self, e):
        # menus from the mouse open on the right button's release (a right drag selects
        # time instead); the keyboard's menu key still opens one here
        if e.reason() == e.Reason.Mouse and e.pos().x() >= self.header_w:
            return
        self._menu(e.pos(), e.globalPos())

    def _menu(self, pos, global_pos):
        if not self.proj:
            return
        row, c, _ = self._hit(QPointF(pos))
        if row is None:
            return
        if c is None:                                    # (a clip on an open group's lane)
            c = self._lane_hit(QPointF(pos))[1]
        menu = QMenu(self)
        if pos.x() < self.header_w:
            tr = self.rows[row]
            tid = tr["id"]
            if tid not in self.selected_tracks:
                self.select_tracks({tid}, tid)
            n = len(self.selected_tracks)
            if tr["clips"]:
                ids = {c["id"] for c in tr["clips"]}
                menu.addAction("選取軌道上的所有片段", lambda: self.set_selection(ids, tr["clips"][0]["id"]))
                menu.addSeparator()
            items = [("重新命名軌道…", "rename"), ("軌道顏色…", "color"), ("預設顏色", "nocolor"), None]
            if tr["clips"]:
                if tr.get("color"):
                    items += [("將軌道顏色套用到所有片段", "clips:track")]
                items += [("設定所有片段的顏色…", "clips:pick"), ("所有片段改回預設顏色", "clips:none"), None]
            if tr["kind"] == "audio" or any(c["type"] in ("video", "compound") for c in tr["clips"]):
                items += [("軌道音量…", "gain")]
            items += [("上移", "up"), ("下移", "down"), None,
                      ("新增影片軌道", "add:video"), ("新增文字軌道", "add:text"), ("新增音訊軌道", "add:audio"),
                      None, (f"刪除 {n} 條軌道" if n > 1 else "刪除軌道", "delete"), ("清除空軌道", "clear_empty")]
            for it in items:
                if it is None:
                    menu.addSeparator()
                else:
                    menu.addAction(it[0], lambda a=it[1]: self.trackAction.emit(a, tid))
        elif c is not None:
            if c["id"] not in self.selected_ids:
                self.select(c)
            items = [("複製", "copy"), ("剪下", "cut"), ("貼上到播放頭", "paste"), ("建立副本", "duplicate"), None,
                     ("重新命名…", "rename"), ("顏色…", "color"), ("預設顏色", "nocolor"), None,
                     ("在播放頭分割", "split"), ("頭尾對齊拍子", "snap_beats"), ("打亂順序", "shuffle"),
                     ("刪除", "delete")]
            if c["type"] == "compound":
                comp = components.of_clip(c)
                head = [("編輯元件" if comp else "編輯靜態片段" if project.is_static(c) else "編輯複合片段", "enter"),
                        ("在新的分頁開啟", "open_tab"), ("建立獨立副本", "clone"), ("設為獨立（不再共用）", "unique")]
                if comp:
                    head.append(("轉回靜態片段" if project.is_static(c) else "轉回複合片段", "from_component"))
                elif c.get("compound_id"):
                    head.append(("轉為元件", "to_component"))
                if c.get("compound_id"):                     # (not a nested timeline)
                    head.append(("存到 Library…", "save_library"))
                items = head + [None] + items
            if project.is_group(c):
                m = c.get("matte") or {}
                head = [("摺疊群組" if self.is_open(c) else "展開群組", "fold"), ("解散群組", "ungroup"),
                        ("✓ 最下面的物件當遮罩" if m.get("on") else "最下面的物件當遮罩", "group_matte")]
                if m.get("on"):
                    head.append(("✓ 反轉遮罩" if m.get("invert") else "反轉遮罩", "group_invert"))
                items = head + [None] + items
            if all(k["type"] != "audio" for k in self.selected_clips()):
                items += [None, ("建立群組", "group")]
            if all(k["type"] != "audio" for k in self.selected_clips()):
                items += [None, ("建立靜態片段", "make_static"), ("建立靜態元件", "make_static_component"),
                          ("建立複合片段", "make_compound"), ("建立元件", "make_component")]
            else:
                items += [None, ("建立複合片段", "make_compound"), ("建立元件", "make_component")]
            if c["type"] == "video":
                items = [("分離音訊", "detach_audio"), None] + items
            for it in items:
                if it is None:
                    menu.addSeparator()
                else:
                    menu.addAction(it[0], lambda a=it[1]: self.clipAction.emit(a, c["id"]))
            sel = self.selected_clips()
            comp = self.proj.get("open_component")
            if comp is not None and all(k["type"] != "audio" for k in sel):     # 設為參數 (元件)
                menu.addSeparator()
                param_menu(menu, comp, sel, self.paramBind.emit, self.paramUnbind.emit)
            if all(k["type"] != "audio" for k in sel):           # 移入群組: one of the level's groups
                skip = {k["id"] for g in sel for k in [g] + list(project.walk_clips(g.get("tracks") or []))}
                groups = [(gid, name) for gid, name in edit.group_ids(self.proj) if gid not in skip]
                if groups:
                    sub = menu.addMenu("移入群組")
                    for gid, name in groups:
                        sub.addAction(name, lambda g=gid: self.clipAction.emit("into:" + g, c["id"]))
        else:                                          # a free spot on a track
            menu.addAction("貼上到播放頭", lambda: self.clipAction.emit("paste", ""))
            if row is not None and self.rows[row]["kind"] != "audio":
                tid = self.rows[row]["id"]
                menu.addAction("新增空白靜態片段（在播放頭）", lambda: self.clipAction.emit("new_static", tid))
                menu.addAction("新增空白靜態元件（在播放頭）", lambda: self.clipAction.emit("new_component", tid))
        menu.exec(global_pos)

    def mouseDoubleClickEvent(self, e):
        if not self.proj:
            return
        row, c, _ = self._hit(e.position())
        if row is None:
            return
        if e.position().x() < self.header_w:
            edge = self._edge_at(e.position())
            if edge is not None:                       # double-click the edge: default height
                self.heights.pop(self.rows[edge]["id"], None)
                self._layout()
                self.update()
                return
            if not any(r.contains(e.position()) for _, r in self.header_buttons(row)):
                self.trackAction.emit("rename", self.rows[row]["id"])
        elif c is not None and project.is_group(c):
            self.toggle_group(c)
        elif c is not None and c["type"] == "compound":
            self.clipAction.emit("enter", c["id"])
        else:
            _ln, lc, _z = self._lane_hit(e.position())
            if lc is not None and project.is_group(lc):
                self.toggle_group(lc)
            elif lc is not None and lc["type"] == "compound":
                self.clipAction.emit("enter", lc["id"])

    def wheelEvent(self, e):
        if not self.proj:
            return
        dy, dx = e.angleDelta().y(), e.angleDelta().x()
        d = dy or dx                                     # Alt / Shift may turn the wheel sideways
        mods = e.modifiers()
        if mods & Qt.AltModifier:                        # track height
            self.set_vzoom(self.vzoom * (1.15 if d > 0 else 1 / 1.15))
        elif mods & Qt.ControlModifier:                  # zoom time around the mouse
            anchor = self._sec(e.position().x())
            self.px_per_s = min(self.max_zoom(), max(1.0, self.px_per_s * (1.25 if d > 0 else 0.8)))
            self.scroll_s = max(0.0, anchor - (e.position().x() - self.header_w) / self.px_per_s)
        elif mods & Qt.ShiftModifier or (dx and not dy):  # left / right (also touchpad sideways)
            self.scroll_s = max(0.0, self.scroll_s - d / 120 * 80 / self.px_per_s)
        else:                                            # up / down
            self.vbar.setValue(self.scroll_y - round(d / 120 * 40))
            return
        self.update()
