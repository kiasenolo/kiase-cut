"""RAM preview (RAM 預覽快取): the frames the preview has drawn, kept in memory, so playing over them again is
drawn at once - as After Effects' RAM preview - and, while the playhead rests, the frames after it are drawn
ahead of time (ui/player.py).

The frames are kept as pictures (RGBA8888) at the size the preview draws them; a frame asked for at another
size (the preview resized, another quality, the margin round the canvas) is drawn again. The memory they take is
held under a limit (a share of the system's memory, 設定), the least recently used going first, and less when the
system runs short.

What an edit changes: every new project state (set_view) is compared with the last one, clip by clip. Each clip
of the open level has a signature - the clip as it is (pickled), with the compounds it names, which track it is
on, and for an 空物體 whether it is selected; an Audio Visualizer's also has the sound's - and only the frames
from the start to the end of the clips that were added, removed or changed are dropped. Anything else that
draws every frame (the size, the frame rate, the tracks themselves, the parameter rack, the filters' files)
drops them all.

Still stretches (stillspans.py): where nothing on the level changes with time every frame is the same picture, so one
frame kept there stands for the whole stretch - it is green at once, and drawing ahead passes over it.
"""
import bisect
import collections
import hashlib
import pickle

US = 1_000_000
PAD = 1                                   # frames dropped round a changed clip's own
GLOBAL_SKIP = ("tracks", "compounds", "markers", "guides", "selected", "thumbs", "duration_us")
FREE_CHECK = 30                           # frames kept between two looks at the system's free memory


def _digest(data):
    return hashlib.blake2b(data, digest_size=16).digest()


def _blob(obj):
    return pickle.dumps(obj, pickle.HIGHEST_PROTOCOL)


def signatures(view, generation=0):
    """(signature of what every frame depends on, {clip id: (first frame, end frame, signature)}) of a view."""
    fps = float(view.get("fps") or 30.0)
    compounds = view.get("compounds") or {}
    comp_blobs, comp_sigs = {}, {}

    def comp_sig(cid, seen=()):
        if cid in comp_sigs:
            return comp_sigs[cid]
        blob = comp_blobs.get(cid)
        if blob is None:
            blob = comp_blobs[cid] = _blob(compounds[cid])
        parts = [blob] + [comp_sig(k, seen + (cid,)) for k in _named(blob, compounds) if k != cid and k not in seen]
        sig = comp_sigs[cid] = _digest(b"".join(parts))
        return sig

    tracks = view.get("tracks") or []
    audio = _digest(_blob([t for t in tracks if t.get("kind") == "audio"]))
    selected = [str(s) for s in view.get("selected") or ()]
    rest = {k: v for k, v in view.items() if k not in GLOBAL_SKIP}
    layout = [{k: v for k, v in t.items() if k != "clips"} for t in tracks]
    whole = _digest(_blob((rest, layout, generation)))
    clips = {}
    for tr in tracks:
        if tr.get("kind") == "audio":                 # (heard, not seen: what a visualizer shows of it is in its own signature)
            continue
        for c in tr.get("clips") or []:
            blob = _blob(c)
            parts = [blob, str(tr.get("id")).encode()]
            parts += [comp_sig(k) for k in _named(blob, compounds)]
            if b"empty" in blob:                      # (an 空物體 shows while it is selected)
                parts += [s.encode() for s in selected if s.encode() in blob]
            if b"viz" in blob:
                parts.append(audio)
            lo = round(c.get("start_us", 0) * fps / US)
            hi = round((c.get("start_us", 0) + c.get("duration_us", 0)) * fps / US)
            clips[c.get("id") or id(c)] = (lo, hi, _digest(b"".join(parts)))
    return whole, clips


def _named(blob, compounds):
    """The compounds whose ids a pickled clip mentions."""
    return [k for k in compounds if isinstance(k, str) and k.encode() in blob]


class FrameCache:
    """Frames by position (the player's frames, view["fps"]): (geometry, QImage); see the module's text."""

    def __init__(self, limit=0):
        self.limit = limit                    # bytes; 0: nothing is kept
        self.frames = collections.OrderedDict()     # pos -> (geometry, picture, bytes), least recently used first
        self.bytes = 0
        self.whole = None
        self.clips = {}
        self.changed = True                   # what is kept changed since the last look (the timeline's bar)
        self.puts = 0
        self.still = []                       # [(first, end)] frames of the view's still stretches (stillspans.py)
        self._still_lo = []
        self._reps = {}                       # still stretch -> the frame kept that stands for it
        self._misses = {}                     # (stretch, geometry) -> self.puts when it was looked for in vain

    def set_limit(self, limit):
        self.limit = max(0, int(limit))
        self._shrink(self.limit)

    def clear(self):
        if self.frames:
            self.changed = True
        self.frames.clear()
        self.bytes = 0

    def set_view(self, view, generation=0):
        """Drop what a new project state changes (see the module's text)."""
        whole, clips = signatures(view, generation)
        if whole != self.whole:
            self.clear()
        else:
            spans = []
            for cid in set(clips) | set(self.clips):
                a, b = self.clips.get(cid), clips.get(cid)
                if a != b:
                    spans += [s[:2] for s in (a, b) if s is not None]
            for lo, hi in spans:
                self.drop(lo - PAD, hi + PAD)
        self.whole, self.clips = whole, clips
        try:
            from . import render, stillspans
            still = stillspans.frame_spans(view, render.frame_count(view))
        except Exception:                     # (a project it cannot read: every frame is drawn)
            still = []
        self.set_still(still)

    def set_still(self, spans):
        """The frames [(first, end)] that are each one picture (see the module's text)."""
        self.still = sorted(spans)
        self._still_lo = [a for a, _b in self.still]
        self._reps, self._misses = {}, {}
        self.changed = True

    def _span(self, pos):
        i = bisect.bisect_right(self._still_lo, pos) - 1
        return self.still[i] if i >= 0 and pos < self.still[i][1] else None

    def _rep(self, span, geometry):
        """The frame kept in still stretch span at this geometry, or None."""
        p = self._reps.get(span)
        hit = self.frames.get(p) if p is not None else None
        if hit is not None and hit[0] == geometry:
            return p
        if self._misses.get((span, geometry)) == self.puts:     # (nothing kept since it was looked for: none still)
            return None
        p = next((q for q, (g, _i, _n) in self.frames.items() if span[0] <= q < span[1] and g == geometry), None)
        if p is not None:
            self._reps[span] = p
        else:
            self._misses[(span, geometry)] = self.puts
        return p

    def _kept(self, pos, geometry):
        """The frame kept for pos: itself, or the one standing for its still stretch."""
        hit = self.frames.get(pos)
        if hit is not None and hit[0] == geometry:
            return pos
        span = self._span(pos)
        return self._rep(span, geometry) if span else None

    def drop(self, lo, hi):
        """Forget frames lo .. hi - 1."""
        for pos in [p for p in self.frames if lo <= p < hi]:
            self.bytes -= self.frames.pop(pos)[2]
            self.changed = True

    def get(self, pos, geometry):
        p = self._kept(pos, geometry)
        if p is None:
            return None
        self.frames.move_to_end(p)
        return self.frames[p][1]

    def has(self, pos, geometry):
        return self._kept(pos, geometry) is not None

    def room_for(self, nbytes):
        """Whether a frame of nbytes fits without dropping any kept one (drawing ahead stops there)."""
        return self.bytes + nbytes <= self.limit

    def put(self, pos, geometry, img, low_memory=None):
        """Keep picture img as frame pos (the least recently used go to make room). low_memory(): whether the
        system is short of memory (asked every FREE_CHECK frames): then half of what is kept goes."""
        nbytes = img.sizeInBytes()
        if nbytes > self.limit:
            return
        span = self._span(pos)
        if span is not None:
            rep = self._rep(span, geometry)
            if rep is not None and rep != pos:      # (its stretch has its picture already)
                self.frames.move_to_end(rep)
                return
            self._reps[span] = pos
        old = self.frames.pop(pos, None)
        if old is not None:
            self.bytes -= old[2]
        self._shrink(self.limit - nbytes)
        self.frames[pos] = (geometry, img, nbytes)
        self.bytes += nbytes
        self.changed = True
        self.puts += 1
        if low_memory is not None and self.puts % FREE_CHECK == 0 and low_memory():
            self._shrink(self.bytes // 2)

    def _shrink(self, to):
        while self.frames and self.bytes > to:
            self.bytes -= self.frames.popitem(last=False)[1][2]
            self.changed = True

    def positions(self, geometry):
        """The positions of the frames kept at this geometry: every frame of a still stretch one of them stands for."""
        out = [p for p, (g, _i, _n) in self.frames.items() if g == geometry]
        for span in self.still:
            if self._rep(span, geometry) is not None:
                out += range(span[0], span[1])
        return out


def runs(positions, step=1):
    """[(first, end)] of the positions as runs: positions up to step apart (a timeline finer than the playing rate
    keeps every step-th frame) are one run, which ends step after its last."""
    out = []
    for p in sorted(positions):
        if out and p <= out[-1][1]:
            out[-1][1] = p + step
        else:
            out.append([p, p + step])
    return [tuple(r) for r in out]
