"""The way of the sound when a project processes it (soundfx.py): used by audiomix.Mixer.

    clip: source (speed, 標準化, 音量, fades: audiomix.mix_window) -> the clip's effects
          (they ring on after the clip ends)
    track: its clips added -> its effects -> pan, fader -> its output, and its sends
    bus: what is sent to it added -> its effects -> pan, fader -> its output, and its sends
    master: what comes to it added -> its effects
A compound or group clip is a level of its own, mixed this way and then taken as one clip.

The engine works in blocks of BLOCK samples on a grid fixed to the mixed timeline, whatever
is asked for, so a preview and an export come out the same. Effects remember what they have
heard: asked for a place that does not follow the last one, they start over and are run
over what came before it (up to PREROLL_S). Effects that make their output late (a
limiter looking ahead) are made up for: paths that are added are delayed to match, and the
whole mix is taken that much further along.
"""
import bisect
import math

import numpy as np

from . import curves, dsp, normalize, project, soundfx, stretch

BLOCK = 512
RATE = dsp.RATE
US = 1_000_000
PREROLL_MIN_S, PREROLL_S = 0.25, 10.0
SILENT = 10 ** (-90 / 20)
LEVELS_KEPT = 4096                      # blocks of meter history (about 40 s)


def samples(us):
    return int(round(us * RATE / US))


class Delay:
    """A signal n samples later."""

    def __init__(self, n):
        self.n = n
        self.reset()

    def reset(self):
        self.held = np.zeros((self.n, 2), np.float32)

    def run(self, x):
        both = np.concatenate([self.held, x])
        self.held = both[len(x):].copy()
        return both[:len(x)]


# -- the graph, as compiled from a view ------------------------------------------------------------
class Fx:
    """One entry of a chain: its processor (None without the sound library: passed through)."""

    def __init__(self, key, entry, proc):
        self.key, self.entry, self.proc = key, entry, proc
        self.side = None                    # the channel id of its side-chain, if one counts

    def apply(self, t_us):
        if self.proc is not None:
            for name, v in soundfx.values(self.entry, t_us).items():
                self.proc.set(name, v)

    @property
    def latency(self):
        return self.proc.latency if self.proc else 0

    @property
    def tail(self):
        return self.proc.tail if self.proc else 0.0


class ClipNode:
    """A clip that sounds on a channel: source (an audiomix.Source) or sub (a Level: a
    compound's or group's content), and its effects. Times in samples of the mixed line."""

    def __init__(self, key, clip, start_us, rate, win, source=None, sub=None, chain=()):
        self.key, self.clip, self.start_us, self.rate = key, clip, start_us, rate
        self.source, self.sub, self.chain = source, sub, list(chain)
        self.first = samples(win[0])
        self.last = samples(win[1]) if math.isfinite(win[1]) else 1 << 62
        self.latency = (sub.latency if sub else 0) + sum(f.latency for f in self.chain)
        ring = min(soundfx.MAX_TAIL_S, sum(f.tail for f in self.chain) + (sub.tail if sub else 0.0))
        self.tail = int(ring * RATE)
        self.pad = 0                        # samples it waits for the latest clip of its track


class Channel:
    def __init__(self, cid, kind, holder, name):
        self.id, self.kind, self.holder, self.name = cid, kind, holder, name
        self.clips, self.chain = [], []
        self.fader = 1.0                    # 推桿, 0 when off
        self.off = False                    # muted, another one soloed, or a 參考 track out of level
        self.routes = []                    # [(channel id, send entry or None: the output)]
        self.in_latency = self.latency = 0
        self.tail = 0.0


class Level:
    def __init__(self, key):
        self.key = key
        self.channels = {}                  # id -> Channel, in the order they are worked out
        self.offset_us, self.rate = 0.0, 1.0     # its content time: (t - offset) * rate
        self.latency = 0
        self.tail = 0.0

    def time(self, t_us):
        return (t_us - self.offset_us) * self.rate


def _toposort(ids, needs):
    """ids with every one after those it needs; a link that would close a circle is left out.
    Returns (order, {(id, needed)} left out)."""
    order, state, cut = [], {}, set()

    def visit(i):
        state[i] = 1
        for j in needs.get(i, ()):
            if state.get(j) == 1:
                cut.add((i, j))
            elif j not in state:
                visit(j)
        state[i] = 2
        order.append(i)
    for i in ids:
        if i not in state:
            visit(i)
    return order, cut


class Compiler:
    """Makes the graph of a level, keeping the processors of an earlier one (store: key ->
    Processor) so that an edit does not make effects forget what they have heard."""

    def __init__(self, store, source_of):
        self.store, self.source_of = store, source_of       # source_of(...) -> audiomix.Source
        self.used = {}
        self.library = dsp.available()

    def chain(self, owner, entries):
        out = []
        for e in soundfx.active(entries):
            key = owner + (e["id"], e["effect"])
            proc = self.used.get(key) or self.store.get(key)
            if proc is None and self.library:
                try:
                    proc = dsp.Processor(e["effect"])
                except dsp.DspError:
                    proc = None
            if proc is not None:
                self.used[key] = proc
            out.append(Fx(key, e, proc))
        return out

    def level(self, key, tracks, mix, level_ids, offset_us=0.0, win=(0, float("inf")), rate=1.0, only=None):
        mix = mix or {}
        lv = Level(key)
        lv.offset_us, lv.rate = offset_us, rate
        buses = {b["id"]: b for b in mix.get("buses") or ()}
        chans = {}
        for t in tracks:
            ch = chans[t["id"]] = Channel(t["id"], "track", t, t.get("name") or t["kind"])
        for bid, b in buses.items():
            chans[bid] = Channel(bid, "bus", b, b.get("name") or "Bus")
        master = chans[soundfx.MASTER] = Channel(soundfx.MASTER, "master", mix.get(soundfx.MASTER) or {}, "Master")
        self._faders(chans, tracks, level_ids)
        for ch in chans.values():
            if ch.kind == "master":
                continue
            out = ch.holder.get("output")
            ch.routes = [(out if out in buses and out != ch.id else soundfx.MASTER, None)]
            ch.routes += [(s["bus"], s) for s in ch.holder.get("sends") or () if s.get("bus") in buses and s["bus"] != ch.id]
        for ch in chans.values():
            ch.chain = self.chain(key + ("ch", ch.id), ch.holder.get("sound_effects"))
        for t in tracks:
            chans[t["id"]].clips = self.clips(key, t, level_ids, offset_us, win, rate)
        # who needs whom: what is sent into it, and what its effects listen to
        needs = {i: set() for i in chans}
        for ch in chans.values():
            for dst, _ in ch.routes:
                needs[dst].add(ch.id)
            for f in ch.chain + [f for n in ch.clips for f in n.chain]:
                side = (f.entry.get("side") or {}).get("id")
                if side in chans and side not in (ch.id, soundfx.MASTER) and soundfx.EFFECTS[f.entry["effect"]].get("side"):
                    f.side = side
                    needs[ch.id].add(side)
        order, cut = _toposort(list(chans), needs)
        for i, j in cut:                    # (a loop: a route or a side-chain in it is dropped)
            chans[j].routes = [r for r in chans[j].routes if r[0] != i]
            for f in chans[i].chain + [f for n in chans[i].clips for f in n.chain]:
                if f.side == j:
                    f.side = None
        lv.channels = {i: chans[i] for i in order}
        self._timing(lv)
        return lv

    def _faders(self, chans, tracks, level_ids):
        """Mute and solo. With anything soloed, only it sounds - and the buses it goes
        through, and, for a soloed bus, what feeds it."""
        solo = {i for i, ch in chans.items() if ch.holder.get("solo") and
                (ch.kind != "track" or project.present(ch.holder, level_ids))}
        heard = None
        if solo:
            def targets(i):
                h = chans[i].holder
                out = [h.get("output") or soundfx.MASTER] + [s.get("bus") for s in h.get("sends") or ()]
                return [d for d in out if d in chans]
            down, stack = set(), list(solo)
            while stack:                    # what the soloed ones go through
                i = stack.pop()
                for d in targets(i) if i != soundfx.MASTER else ():
                    if d not in down:
                        down.add(d)
                        stack.append(d)
            up, more = {i for i in solo if chans[i].kind == "bus"}, True
            while more:                     # what feeds a soloed bus
                more = False
                for i in chans:
                    if i != soundfx.MASTER and i not in up and any(d in up for d in targets(i)):
                        up.add(i)
                        more = True
            heard = solo | down | up | {soundfx.MASTER}
        for i, ch in chans.items():
            if ch.kind == "master":
                continue
            ch.off = bool(ch.holder.get("muted") or (heard is not None and i not in heard) or
                          (ch.kind == "track" and not project.present(ch.holder, level_ids)))
            ch.fader = 0.0 if ch.off else float(ch.holder.get("gain", 1.0))

    def clips(self, key, track, level_ids, offset_us, win, rate):
        out = []
        if track.get("reference") and id(track) not in level_ids:
            return out
        for c in track["clips"]:
            s = offset_us + c["start_us"] / rate
            e = s + c["duration_us"] / rate
            lo, hi = max(s, win[0]), min(e, win[1])
            if hi <= lo or project.frozen(c) is not None:
                continue
            ck = key + ("clip", c["id"])
            source = sub = None
            if c["type"] in ("audio", "video") and c.get("media"):
                source = self.source_of(c, s, (lo, hi), rate)
            elif project.is_group(c) or (c["type"] == "compound" and not project.is_static(c)):
                inner = rate if project.is_group(c) else rate * project.speed(c)
                comp = c.get("compound") or {}
                sub = self.level(ck, c["tracks"] if project.is_group(c) else comp["tracks"], comp, level_ids,
                                 s - c.get("source_start_us", 0) / inner, (lo, hi), inner)
                if not any(ch.clips for ch in sub.channels.values()):
                    continue
            else:
                continue
            out.append(ClipNode(ck, c, s, rate, (lo, hi), source, sub, self.chain(ck, c.get("sound_effects"))))
        return out

    def _timing(self, lv):
        """Latencies and tails along the way, in the channels' order."""
        arrive, ring = {}, {}
        for i, ch in lv.channels.items():
            lat = max([n.latency for n in ch.clips], default=0)
            for n in ch.clips:
                n.pad = lat - n.latency
            lat = max([lat] + arrive.get(i, []))
            sides = [lv.channels[f.side].latency for f in ch.chain + [f for n in ch.clips for f in n.chain] if f.side]
            ch.in_latency = max([lat] + sides)
            ch.latency = ch.in_latency + sum(f.latency for f in ch.chain)
            inner = max([n.tail / RATE for n in ch.clips] + ring.get(i, []), default=0.0)
            ch.tail = min(soundfx.MAX_TAIL_S, inner + sum(f.tail for f in ch.chain))
            for dst, _ in ch.routes:
                arrive.setdefault(dst, []).append(ch.latency)
                ring.setdefault(dst, []).append(ch.tail)
        top = lv.channels[soundfx.MASTER]
        lv.latency, lv.tail = top.latency, top.tail


# -- the engine ------------------------------------------------------------------------------------
class Engine:
    def __init__(self, source_of):
        """source_of(clip, start_us, win, rate) -> the audiomix.Source of a clip (its
        decoded sound is filled in by the Mixer)."""
        self.source_of = source_of
        self.root = None
        self.only = None
        self.procs = {}                     # key -> Processor
        self.state = {}                     # key -> Delay, or the fader gains last block ended at
        self.next_in = None                 # the input sample the next block starts at
        self.ready = np.zeros((0, 2), np.float32)       # output made and not yet taken,
        self.ready_at = 0                               # from this output sample on
        self.tap = {}                       # channel id (the root's) -> [(sample, peak l, peak r)]
        self.meters = {}                    # effect key -> [(sample, meters)]
        self.scope = []                     # [(sample, mono block)] of the output, for the spectrum
        self.watched = frozenset()          # effect ids whose output is kept to be drawn
        self.watch = {}                     # effect id -> [(sample, mono block)]

    def set_view(self, view, only=None, level_ids=None):
        """only: the id of a track of the view, to give that track's sound alone (after its
        fader), as an export's stem."""
        compiler = Compiler(self.procs, self.source_of)
        ids = project.level_tracks(view) if level_ids is None else level_ids
        root = compiler.level((), view["tracks"], project.mix_of(view), ids)
        latency_was = self.latency
        self.root, self.only = root, only
        self.procs = compiler.used
        if latency_was != self.latency:
            self.next_in = None             # (the output moved against the input: start over)

    @property
    def latency(self):
        if self.root is None:
            return 0
        if self.only is not None and self.only in self.root.channels:
            return self.root.channels[self.only].latency
        return self.root.latency

    def sources(self):
        """Every audiomix.Source in the graph."""
        out = []

        def walk(lv):
            for ch in lv.channels.values():
                for n in ch.clips:
                    if n.source is not None:
                        out.append(n.source)
                    if n.sub is not None:
                        walk(n.sub)
        if self.root is not None:
            walk(self.root)
        return out

    def reset(self):
        for p in self.procs.values():
            p.reset()
        self.state = {}
        self.tap, self.meters, self.scope, self.watch = {}, {}, [], {}

    # -- what was heard (for the mixer's meters; read from another thread) ----------------------
    @staticmethod
    def _around(kept, sample, back):
        """The values of the [(sample, value)] list kept that start in (sample - back, sample]."""
        kept = list(kept)                   # (the sound's thread goes on adding to it)
        i = bisect.bisect_right(kept, sample, key=lambda k: k[0])
        return [v for s, v in kept[max(0, i - back // BLOCK - 2):i] if s > sample - back]

    def level_at(self, channel_id, sample, back=RATE // 30):
        """(left, right) peak of a channel of the open level around output sample `sample`."""
        got = self._around(self.tap.get(channel_id, ()), sample, back)
        return (max(v[0] for v in got), max(v[1] for v in got)) if got else (0.0, 0.0)

    def meters_at(self, effect_id, sample, back=RATE // 30):
        """The meters of an effect on a track, bus or master around `sample`, or None."""
        got = self._around(self.meters.get(effect_id, ()), sample, back)
        return got[-1] if got else None

    def output_before(self, sample, n, effect_id=None):
        """The n samples of the output (mono) before `sample` - or of a watched effect's;
        zeros where there are none."""
        out = np.zeros(n, np.float32)
        for s, block in list(self.scope if effect_id is None else self.watch.get(effect_id, ())):
            lo, hi = max(s, sample - n), min(s + len(block), sample)
            if hi > lo:
                out[lo - (sample - n):hi - (sample - n)] = block[lo - s:hi - s]
        return out

    # -- asking for sound ---------------------------------------------------------------------------
    def render(self, a, b):
        """Output samples a..b of the mix, float32 [b - a, 2] (1.0 = full scale)."""
        if self.root is None or b <= a:
            return np.zeros((max(0, b - a), 2), np.float32)
        have_to = self.ready_at + len(self.ready)
        if self.next_in is None or not self.ready_at <= a <= have_to:
            self._seek(a)
        while self.ready_at + len(self.ready) < b:
            self._step()
        i = a - self.ready_at
        out = self.ready[i:i + (b - a)].copy()
        self.ready, self.ready_at = self.ready[i + (b - a):], b
        return out

    def _seek(self, a):
        """Start over so that output sample a comes next, heard from far enough back."""
        self.reset()
        lat = self.latency
        back = min(PREROLL_S, max(PREROLL_MIN_S, self.root.tail + PREROLL_MIN_S))
        first = (max(0, a - int(back * RATE)) // BLOCK) * BLOCK
        self.next_in = first
        self.ready, self.ready_at = np.zeros((0, 2), np.float32), first - lat
        while self.ready_at + len(self.ready) < a:
            self._step()
            drop = min(len(self.ready), a - self.ready_at)
            self.ready, self.ready_at = self.ready[drop:], self.ready_at + drop

    def _step(self):
        pos = self.next_in
        out = self._level(self.root, pos, self.only, top=True)
        top = self.root.channels[soundfx.MASTER]
        self.scope.append((pos - top.latency, out.mean(axis=1)))
        if len(self.scope) > LEVELS_KEPT // 8:
            del self.scope[:len(self.scope) - LEVELS_KEPT // 8]
        self.next_in += BLOCK
        self.ready = np.concatenate([self.ready, out])

    # -- one block --------------------------------------------------------------------------------
    def _delayed(self, key, x, n):
        if n <= 0:
            return x
        d = self.state.get(key)
        if d is None or d.n != n:
            d = self.state[key] = Delay(n)
        return d.run(x)

    def _ramp(self, key, x, left, right):
        """x with gains going from where they ended last block to left, right."""
        was = self.state.get(key, (left, right))
        self.state[key] = (left, right)
        if was == (left, right):
            if left == right == 1.0:
                return x
            return x * np.array([left, right], np.float32)
        k = (np.arange(1, BLOCK + 1, dtype=np.float32) / BLOCK)[:, None]
        a, b = np.array(was, np.float32), np.array([left, right], np.float32)
        return x * (a + (b - a) * k)

    def _chain(self, chain, x, pos, latency, t_of, posts, post_latency, top):
        """x (whose samples are latency late) through a chain. t_of(mixed us) -> the time the
        parameters are read at."""
        for f in chain:
            if f.proc is None:
                continue
            f.apply(t_of((pos - latency) * US / RATE))
            side = None
            if f.side is not None and f.side in posts:
                side = self._delayed(f.key + ("side",), posts[f.side], latency - post_latency[f.side])
            x = f.proc.process(x, side, pos - latency)
            latency += f.proc.latency
            if top:
                self._remember(self.meters, f.key[-2], pos - latency, f.proc.meters())
            if f.key[-2] in self.watched:
                kept = self.watch.setdefault(f.key[-2], [])
                kept.append((pos - latency, x.mean(axis=1)))
                if len(kept) > LEVELS_KEPT // 8:
                    del kept[:len(kept) - LEVELS_KEPT // 8]
        return x, latency

    def _remember(self, store, key, sample, value):
        kept = store.get(key)
        if kept is None:
            kept = store[key] = []
        kept.append((sample, value))
        if len(kept) > LEVELS_KEPT:
            del kept[:len(kept) - LEVELS_KEPT]

    def _clip(self, n, pos, posts, post_latency, latency_cap):
        """The block of one clip (n.latency late), or None when it is silent here."""
        end = n.last + n.tail + n.latency + n.pad
        if pos + BLOCK <= n.first or pos >= end:
            return None
        x = np.zeros((BLOCK, 2), np.float32)
        if n.source is not None:
            lo, hi = max(pos, n.first), min(pos + BLOCK, n.last)
            s = n.source
            if hi > lo and s.pcm is not None:
                from .audiomix import mix_window
                t = max(lo * US / RATE, s.win[0])
                x[lo - pos:hi - pos] = mix_window([s], hi - lo, t) / 32768.0
        else:
            x = self._level(n.sub, pos, None)
        if n.chain:
            start, rate = n.start_us, n.rate
            side_lat = {k: v for k, v in post_latency.items()}
            lat = n.sub.latency if n.sub else 0
            x, _ = self._chain(n.chain, x, pos, lat, lambda t: max(0.0, (t - start) * rate), posts, side_lat, False)
        return self._delayed(n.key + ("pad",), x, n.pad)

    def _level(self, lv, pos, only, top=False):
        sums, posts, post_latency = {}, {}, {}
        for cid, ch in lv.channels.items():
            lat = max([c.latency + c.pad for c in ch.clips], default=0)
            x = np.zeros((BLOCK, 2), np.float32)
            for n in ch.clips:
                got = self._clip(n, pos, posts, post_latency, ch.in_latency)
                if got is not None:
                    x = x + got
            x = self._delayed(lv.key + ("own", cid), x, ch.in_latency - lat)
            for src, part, src_latency, tag in sums.get(cid, ()):
                x = x + self._delayed(lv.key + ("route", src, cid, tag), part, ch.in_latency - src_latency)
            t_of = lv.time
            x, lat = self._chain(ch.chain, x, pos, ch.in_latency, t_of, posts, post_latency, top)
            before = x
            if ch.kind != "master":
                now = t_of((pos - lat) * US / RATE)
                pan = max(-1.0, min(1.0, float(curves.value(soundfx.pan_of(ch.holder), now))))
                x = self._ramp(lv.key + ("fader", cid), x, ch.fader * min(1.0, 1.0 - pan), ch.fader * min(1.0, 1.0 + pan))
            posts[cid], post_latency[cid] = x, lat
            if top:
                peak = np.abs(x).max(axis=0)
                self._remember(self.tap, cid, pos - lat, (float(peak[0]), float(peak[1])))
            for i, (dst, send) in enumerate(ch.routes):
                part = x
                if send is not None:
                    db = float(curves.value(send.get("gain", 0.0), t_of((pos - lat) * US / RATE)))
                    g = 0.0 if db <= soundfx.SEND_OFF_DB else 10 ** (db / 20)
                    if send.get("pre"):                  # before the fader; a muted channel sends nothing
                        g *= 0.0 if ch.off else 1.0
                        part = before
                    part = self._ramp(lv.key + ("send", cid, i), part, g, g)
                sums.setdefault(dst, []).append((cid, part, lat, i))
        return posts[only if only is not None and only in posts else soundfx.MASTER]
