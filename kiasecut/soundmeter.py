"""聲音轉數值 (peak to value): how loud one box of the spectrum is, along a channel's whole
timeline, as a number 0 - 1 (design/sound-values.md).

A meter spec: {"level": a compound's id (a timeline's too), "channel": a track or bus of it, or
"master", "lo_hz", "hi_hz": the box's sides, "floor_db", "top_db": the levels that read 0 and 1
(its bottom and top edges), "attack", "release": seconds the number takes to rise and fall}

Nothing is measured while playing. The channel's sound (after its effects, fader and pan - its
own mute and anyone's solo not counted) is run through soundgraph's engine from the start of
its level once (tap), then each moment is looked up in a table: any place asked for, a preview,
a part of an export or a command-line render read the same numbers.

    tap       the channel's sound, mono, kept in the cache by signature(): what feeds it
    box_db    the strongest frequency of the box every HOP samples (kept in memory per box)
    shape     that as 0 - 1, with attack and release: cheap, so the box's edges can be dragged

A global parameter takes its value from a meter with p["sound"] = spec (rack.py; a number only):

    plan      what there is to measure, in order - a channel whose effects follow another such
              parameter after that one - and what cannot be (a circle: a parameter that hears a
              channel its own number has a say in). Copies the project: call it where it is edited
    run       measures a plan (any thread) and publishes the curves value() reads
    require   both, and raises for a parameter in use that cannot be measured (exports)
"""
import copy
import hashlib
import json
import math
import os
import threading

import numpy as np

from . import dsp, project, soundfx, soundnodes

RATE = 48000
N, HOP = 2048, 512                      # the window a level is taken from, and the step between two (the engine's block)
US = 1_000_000
VERSION = 1                             # (of what a tap holds: raise it when the same project would sound different)
LO_HZ, HI_HZ = 20.0, 20000.0
MIN_DB, MAX_DB = -90.0, 6.0
MIN_SPAN_DB = 1.0
MAX_ATTACK, MAX_RELEASE = 5.0, 10.0
SILENT_DB = -200.0
TAPS_KEPT = 16                          # taps a cache folder holds (a new one each time what feeds a channel changes)
DEFAULTS = {"lo_hz": 40.0, "hi_hz": 120.0, "floor_db": -36.0, "top_db": -6.0, "attack": 0.0, "release": 0.15}
RANGES = {"lo_hz": (LO_HZ, HI_HZ), "hi_hz": (LO_HZ, HI_HZ), "floor_db": (MIN_DB, MAX_DB - MIN_SPAN_DB),
          "top_db": (MIN_DB + MIN_SPAN_DB, MAX_DB), "attack": (0.0, MAX_ATTACK), "release": (0.0, MAX_RELEASE)}
# what of a clip and of a track or bus has a say in the sound (all a signature and a tap look at)
CLIP_KEYS = ("id", "type", "start_us", "duration_us", "source_start_us", "speed", "speed_curve", "keep_pitch", "volume",
             "fade_in_us", "fade_out_us", "normalize", "freeze", "audio_stream", "sound_effects")
CHANNEL_KEYS = ("id", "kind", "gain", "pan", "muted", "routes", "output", "sends", "sound_effects", "reference")


class MeterError(Exception):
    pass


class Cancelled(Exception):
    pass


# -- the spec ---------------------------------------------------------------------------------------
def make(level, channel, **values):
    return clean(dict(DEFAULTS, level=level, channel=channel, **values))


def is_spec(x):
    return isinstance(x, dict) and "channel" in x and "lo_hz" in x


def check(spec):
    """None when the spec is usable, else why not."""
    if not is_spec(spec) or not isinstance(spec.get("level"), str) or not isinstance(spec.get("channel"), str):
        return "沒有聲音來源"
    for k in RANGES:
        v = spec.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return "框選和時間要是有限的數字"
    return None


def clean(spec):
    """A copy of spec with every number inside its range and the box the right way up."""
    why = check(spec)
    if why:
        raise ValueError(why)
    out = {"level": spec["level"], "channel": spec["channel"]}
    for k, (lo, hi) in RANGES.items():
        out[k] = float(min(hi, max(lo, spec[k])))
    out["hi_hz"] = max(out["hi_hz"], out["lo_hz"])
    out["top_db"] = max(out["top_db"], out["floor_db"] + MIN_SPAN_DB)
    return out


# -- numbers from the sound -------------------------------------------------------------------------
_window = np.hanning(N).astype(np.float32)


def bins(lo_hz, hi_hz):
    """The FFT bins a box from lo_hz to hi_hz looks at (the nearest one when it holds none)."""
    hz = np.arange(N // 2 + 1) * RATE / N
    got = np.nonzero((hz >= lo_hz) & (hz <= hi_hz))[0]
    if not len(got):
        got = np.array([int(np.argmin(np.abs(hz - math.sqrt(lo_hz * hi_hz))))])
    return got


def box_db(mono, lo_hz, hi_hz):
    """float32 [len // HOP + 1]: the strongest frequency of the box, in dB (a sine at full scale: 0,
    as the spectra on the 聲音 page show it), in the window of N samples centred on sample k * HOP."""
    frames = len(mono) // HOP + 1
    padded = np.zeros(N // 2 + (frames - 1) * HOP + N // 2, np.float32)
    n = min(len(mono), len(padded) - N // 2)
    padded[N // 2:N // 2 + n] = mono[:n]
    views = np.lib.stride_tricks.sliding_window_view(padded, N)[::HOP]
    sel = bins(lo_hz, hi_hz)
    out = np.empty(frames, np.float32)
    for i in range(0, frames, 1024):
        mag = np.abs(np.fft.rfft(views[i:i + 1024] * _window, axis=1)[:, sel]).max(axis=1) / (N / 4)
        out[i:i + 1024] = 20 * np.log10(np.maximum(mag, 10 ** (SILENT_DB / 20)))
    return out


def shape(db, spec):
    """box_db's levels as the numbers 0 - 1: floor_db and below 0, top_db and above 1, rising in
    about `attack` seconds and falling in about `release` (one-pole, from the start). Long enough
    past the end of db for the last fall to die away."""
    raw = np.clip((db - spec["floor_db"]) / max(MIN_SPAN_DB, spec["top_db"] - spec["floor_db"]), 0.0, 1.0)
    step = HOP / RATE
    up, down = _toward(spec["attack"]), _toward(spec["release"])
    raw = np.concatenate([raw, np.zeros(int(spec["release"] * 7 / step) + 2, raw.dtype)])
    if up == 1.0 and down == 1.0:
        return raw.astype(np.float32)
    out, v = [], 0.0
    for x in raw.tolist():
        v += (x - v) * (up if x > v else down)
        out.append(v)
    return np.array(out, np.float32)


def _toward(seconds):
    """How much of the way to the new level one step goes, for a rise or fall of about `seconds`."""
    return 1.0 if seconds <= 0 else 1.0 - math.exp(-HOP / RATE / seconds)


class Follower:
    """The same measuring while the sound plays (a graph's 電平 → 數值 node): fed a block of HOP
    samples at a time, it hears only what has gone by - its window ends with the block, so its
    number is about a hundredth of a second behind a rack parameter's."""
    KEPT = 128                          # numbers kept, for what hears its sound later than this node does

    def __init__(self):
        self.sound = np.zeros(N, np.float32)
        self.number = 0.0
        self.past = []

    def feed(self, mono, lo_hz, hi_hz, floor_db, top_db, attack, release):
        self.sound = np.concatenate([self.sound[len(mono):], mono.astype(np.float32)])
        sel = bins(min(lo_hz, hi_hz), max(lo_hz, hi_hz))
        mag = float(np.abs(np.fft.rfft(self.sound * _window)[sel]).max()) / (N / 4)
        db = 20 * math.log10(max(mag, 10 ** (SILENT_DB / 20)))
        raw = min(1.0, max(0.0, (db - floor_db) / max(MIN_SPAN_DB, top_db - floor_db)))
        self.number += (raw - self.number) * _toward(attack if raw > self.number else release)
        self.past.append(self.number)
        del self.past[:-self.KEPT]
        return self.number

    def at(self, lag):
        """The number `lag` samples before the newest block's."""
        if not self.past:
            return 0.0
        back = min(len(self.past) - 1.0, max(0.0, lag / HOP))
        i = int(back)
        a = self.past[-1 - i]
        return a if back == i else a + (self.past[-2 - i] - a) * (back - i)


def at(curve, t_us):
    """The number at time t_us of a curve of shape() (between two steps: between their numbers)."""
    x = max(0.0, t_us) * RATE / US / HOP
    i = int(x)
    if i >= len(curve) - 1:
        return 0.0
    return float(curve[i] + (curve[i + 1] - curve[i]) * (x - i))


# -- what is listened to ----------------------------------------------------------------------------
class Snapshot:
    """What a channel's sound is made of, copied out of the project (so it can be measured on
    another thread while the project is edited).

    view     a view of the level for audiomix.Mixer, holding the channel and what feeds it (other
             channels are there, empty); solo is off everywhere, the channel itself is heard
             whether or not it is muted or a 參考 track
    entries  [sound effect entry or graph node] with parameters, of everything that feeds it"""

    def __init__(self, level, channel, view, entries):
        self.level, self.channel, self.view, self.entries = level, channel, view, entries

    def reads(self):
        """The names its effects' bindings and expressions read."""
        from . import rack
        return {n for e in self.entries for x in (e.get("expr") or {}).values() for n in rack._names(x)}


def _content(root, c):
    """(tracks, mix) a compound or group clip plays, or None."""
    comp = c.get("compound") or (root.get("compounds") or {}).get(c.get("compound_id")) or {}
    tracks = c["tracks"] if project.is_group(c) and "tracks" in c else comp.get("tracks")
    return None if tracks is None else (tracks, comp)


def _entries(chain):
    """Every dict with parameters of a chain's effects that are on."""
    return [one for _path, one in soundfx.entries(soundfx.active(chain))]


def _listens(chain):
    """The channels a chain's effects hear besides what they are on."""
    out = []
    for e in soundfx.active(chain):
        if e.get("graph"):
            out += soundnodes.channels_used(e["graph"])
        elif soundfx.EFFECTS[e["effect"]].get("side") and (e.get("side") or {}).get("id"):
            out.append(e["side"]["id"])
    return out


def _copy_clip(root, c, entries, depth):
    """Clip c as far as it sounds, or None when it makes no sound."""
    out = {k: copy.deepcopy(c[k]) for k in CLIP_KEYS if k in c}
    entries += _entries(out.get("sound_effects"))
    if c["type"] in ("audio", "video") and c.get("media"):
        out["media"] = copy.deepcopy(c["media"])
        return out
    if not (project.is_group(c) or (c["type"] == "compound" and not project.is_static(c))) or depth > 16:
        return None
    got = _content(root, c)
    if got is None:
        return None
    tracks, comp = got
    inner = {"tracks": [], "buses": [], "master": {}}
    for t in tracks:
        one = _copy_channel(t, entries)
        one["clips"] = [x for x in (_copy_clip(root, k, entries, depth + 1) for k in t.get("clips") or ()) if x]
        inner["tracks"].append(one)
    inner["buses"] = [_copy_channel(b, entries) for b in comp.get("buses") or ()]
    master = comp.get(soundfx.MASTER) or {}
    inner["master"] = {"sound_effects": copy.deepcopy(master.get("sound_effects") or [])}
    entries += _entries(inner["master"]["sound_effects"])
    out["compound"] = inner
    if project.is_group(c):
        out["tracks"] = inner["tracks"]
    return out


def _copy_channel(h, entries):
    out = {k: copy.deepcopy(h[k]) for k in CHANNEL_KEYS if k in h}
    entries += _entries(out.get("sound_effects"))
    return out


def holder(root, level):
    """The compound a level id names, or raise."""
    comp = (root.get("compounds") or {}).get(level)
    if comp is None:
        raise MeterError("找不到聲音來源的時間線")
    return comp


def channels(comp):
    """[(id, kind, name)] of what can be listened to in a compound: its tracks, buses and master."""
    return ([(t["id"], "track", t.get("name") or t.get("kind")) for t in comp.get("tracks") or ()]
            + [(b["id"], "bus", b.get("name") or "Bus") for b in comp.get("buses") or ()]
            + [(soundfx.MASTER, "master", "Master")])


def upstream(comp, channel):
    """The ids of channel and of every channel of the compound that has a say in how it sounds."""
    holders = {t["id"]: t for t in comp.get("tracks") or ()}
    holders.update({b["id"]: b for b in comp.get("buses") or ()})
    holders[soundfx.MASTER] = comp.get(soundfx.MASTER) or {}
    if channel not in holders:
        raise MeterError("找不到聲音來源的軌道或 bus")
    needs = {i: set() for i in holders}
    for i, h in holders.items():
        if i != soundfx.MASTER:
            for r in soundfx.live_routes(h, holders, i):
                needs[r["to"]].add(i)
        chains = [h.get("sound_effects")] + [c.get("sound_effects") for c in h.get("clips") or ()]
        needs[i] |= {x for chain in chains for x in _listens(chain) if x in holders and x not in (i, soundfx.MASTER)}
    found, stack = set(), [channel]
    while stack:
        i = stack.pop()
        if i not in found:
            found.add(i)
            stack += needs[i]
    return found


def snapshot(root, level, channel):
    comp = holder(root, level)
    wanted = upstream(comp, channel)
    entries = []

    def one(h, track):
        if h["id"] in wanted:
            out = _copy_channel(h, entries)
            if track:
                out["clips"] = [x for x in (_copy_clip(root, c, entries, 0) for c in h.get("clips") or ()) if x]
        else:                           # (there, so that what is wired to it stays wired; silent)
            out = {k: copy.deepcopy(h[k]) for k in ("id", "kind", "routes", "output", "sends") if k in h}
            if track:
                out["clips"] = []
        if h["id"] == channel:
            out.pop("muted", None)
            out.pop("reference", None)
        return out

    tracks = [one(t, True) for t in comp.get("tracks") or ()]
    buses = [one(b, False) for b in comp.get("buses") or ()]
    master = {}
    if soundfx.MASTER in wanted:
        master["sound_effects"] = copy.deepcopy((comp.get(soundfx.MASTER) or {}).get("sound_effects") or [])
        entries += _entries(master["sound_effects"])
    view = {"fps": root.get("fps", 30.0), "tracks": tracks, "buses": buses, "master": master, "compounds": {},
            "rack": copy.deepcopy(root.get("rack") or []), "meter_channels": True,
            "master_gain": float(root.get("master_gain", 1.0))}
    return Snapshot(level, channel, view, entries)


def _files(tracks):
    for t in tracks:
        for c in t.get("clips") or ():
            if c.get("media"):
                yield c["media"]["path"]
            if c.get("compound"):
                yield from _files(c["compound"]["tracks"])


def _stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def signature(snap, more=()):
    """What the tap of a snapshot is kept under. more: anything else its sound depends on (the
    global parameters its effects follow and what they in turn listen to)."""
    view = {k: v for k, v in snap.view.items() if k not in ("rack", "fps", "meter_channels")}
    if snap.channel != soundfx.MASTER:
        view.pop("master_gain")
    stamps = {p: _stamp(p) for p in sorted(set(_files(snap.view["tracks"])))}
    text = json.dumps([VERSION, dsp.available(), snap.level, snap.channel, view, stamps, list(more)],
                      sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


def tap(snap, cache_dir, key, cancelled=lambda: False, on_progress=None):
    """The channel's sound from the start of its level to where it has died away: mono float16
    (it may go past full scale), kept in the cache's soundmeter folder under key."""
    folder = os.path.join(cache_dir, "soundmeter")
    path = os.path.join(folder, key + ".npy")
    if os.path.exists(path):
        try:
            out = np.load(path)
            os.utime(path)                  # (the ones used longest ago are the ones dropped)
            return out
        except (OSError, ValueError):
            pass                        # (half written: measured again)
    out = _run(snap, cache_dir, cancelled, on_progress)
    os.makedirs(folder, exist_ok=True)
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "wb") as fh:
        np.save(fh, out)
    os.replace(tmp, path)
    _prune(folder)
    return out


def _prune(folder):
    files = []
    for name in os.listdir(folder):
        if name.endswith(".npy"):
            try:
                files.append((os.stat(os.path.join(folder, name)).st_mtime_ns, name))
            except OSError:
                pass
    for _when, name in sorted(files)[:-TAPS_KEPT]:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def _run(snap, cache_dir, cancelled, on_progress):
    from . import audiomix, soundgraph
    mix = audiomix.Mixer(cache_dir)
    mix.set_view(snap.view)
    while mix.thread is not None and mix.thread.is_alive():
        if cancelled():
            raise Cancelled()
        mix.thread.join(0.05)
    engine = mix.engine
    channel = engine.root.channels[snap.channel]
    end = project.end_us(snap.view["tracks"])
    n = soundgraph.samples(end) + int(channel.tail * RATE) if end > 0 else 0
    out = np.zeros(n, np.float32)

    def hear(pos, x):
        lo, hi = max(pos, 0), min(pos + len(x), n)
        if hi > lo:
            out[lo:hi] = x[lo - pos:hi - pos].mean(axis=1)

    engine.capture = (snap.channel, hear)
    gain = mix.master if snap.channel == soundfx.MASTER else 1.0
    a, until = 0, n + engine.latency + soundgraph.BLOCK
    while n and a < until:
        if cancelled():
            raise Cancelled()
        engine.render(a, min(a + RATE, until))
        a += RATE
        if on_progress:
            on_progress(min(1.0, a / until))
    return (out * gain).astype(np.float16)


# -- the global parameters that follow a meter -------------------------------------------------------
def sounding(root):
    """The rack parameters that take their value from a meter."""
    return [p for p in (root or {}).get("rack") or () if (p.get("kind") or "number") == "number" and is_spec(p.get("sound"))]


def needs(root, spec):
    """(snapshot, [the names of the parameters its sound reads, through their expressions too], [the ids
    of those among them that take their value from a meter])"""
    from . import rack
    snap = snapshot(root, spec["level"], spec["channel"])
    queue, followed, waits = sorted(snap.reads()), {}, []
    while queue:
        n = queue.pop(0)
        q = rack.by_name(root, n)
        if n in followed or q is None:
            continue
        followed[n] = q
        if q in sounding(root):
            waits.append(q["id"])
        queue += sorted(rack.refs(root, q))
    return snap, list(followed), waits


def _circles(waits):
    """{id: [id, ..., id]} of the parameters that wait for themselves: the way round."""
    out = {}
    for start in waits:
        stack, seen = [(start, [start])], set()
        while stack:
            i, path = stack.pop()
            for j in waits.get(i, ()):
                if j == start:
                    out[start] = path + [start]
                    stack = []
                    break
                if j not in seen:
                    seen.add(j)
                    stack.append((j, path + [j]))
    return out


def _looked_at(root):
    """({id: parameter}, {id: (snapshot, names read, ids waited for)}, {id: why it cannot be measured})"""
    by, found, problems = {}, {}, {}
    for p in sounding(root):
        by[p["id"]] = p
        why = check(p["sound"])
        if why:
            problems[p["id"]] = why
            continue
        try:
            found[p["id"]] = needs(root, clean(p["sound"]))
        except MeterError as exc:
            problems[p["id"]] = str(exc)
    return by, found, problems


def loops(root):
    """{id: what to say} of the parameters whose meter hears something their own number has a say in."""
    by, found, _problems = _looked_at(root)
    circles = _circles({i: x[2] for i, x in found.items()})
    return {i: "循環依賴：" + " → ".join(by[j]["name"] for j in path) for i, path in circles.items()}


def refuse_new_loops(root, before):
    """Raise MeterError when root has a circle that was not among `before` (loops() before an edit)."""
    new = [why for i, why in loops(root).items() if i not in before]
    if new:
        raise MeterError(new[0] + "（聲音來源聽到的聲音會用到它自己的值）")


class Job:
    def __init__(self, rid, spec, snap, tap_key):
        self.rid, self.spec, self.snap, self.tap_key = rid, spec, snap, tap_key
        self.key = (tap_key, json.dumps(spec, sort_keys=True))     # what the curve is of


class Plan:
    def __init__(self, jobs, problems):
        self.jobs, self.problems = jobs, problems

    def keys(self):
        return {j.rid: j.key for j in self.jobs}

    def stale(self):
        """Whether running it would change what value() reads."""
        return _made != self.keys()


def definitions(root, names, measured):
    """What the parameters called names are, for a signature. measured: {id: Job.key} of those
    already planned that take their value from a meter."""
    from . import rack
    out = []
    for n in names:
        q = rack.by_name(root, n)
        out.append({k: q.get(k) for k in ("name", "kind", "value", "expr", "lfo", "items", "sound")}
                   | {"measured": measured.get(q["id"])})
    return out


def plan(root):
    by, found, problems = _looked_at(root)
    if dsp.error():
        for i, (snap, _names, _waits) in found.items():
            if snap.entries:
                problems[i] = "聲音效果函式庫無法使用"
    circles = _circles({i: x[2] for i, x in found.items()})
    for i, path in circles.items():
        problems[i] = "循環依賴：" + " → ".join(by[j]["name"] for j in path)
    jobs, done = [], {}

    def add(i):
        if i in done:
            return
        done[i] = None
        if i in problems:
            return
        snap, names, waits = found[i]
        for j in waits:
            add(j)
        spec = clean(by[i]["sound"])
        job = Job(i, spec, snap, signature(snap, definitions(root, names, done)))
        done[i] = job.key
        jobs.append(job)

    for i in by:
        add(i)
    return Plan(jobs, problems)


_curves = {}                            # rack parameter id -> curve (shape()), replaced whole when it changes
_made = {}                              # ... -> the Job.key it was made from
_levels = {}                            # (tap key, lo, hi) -> box_db, the last few
_lock = threading.Lock()                # (one run at a time)
_generation = 0
LEVELS_KEPT = 12


def generation():
    """A number that changes whenever what value() reads does (for caches of drawn frames)."""
    return _generation


def forget():
    """Another project: nothing measured so far is its."""
    global _generation
    _curves.clear()
    _made.clear()
    _levels.clear()
    _generation += 1


def stale_without(root):
    """Whether curves are published for parameters root no longer has."""
    return bool(_made) and not sounding(root)


def curve(rid):
    return _curves.get(rid)


def value(p, t_us):
    """What parameter p's meter reads at timeline time t_us (0 while it has not been measured)."""
    c = _curves.get(p["id"])
    return 0.0 if c is None else at(c, t_us)


def _publish(rid, key, made):
    global _generation
    if made is None:
        if rid not in _curves and rid not in _made:
            return
        _curves.pop(rid, None)
        _made.pop(rid, None)
    else:
        _curves[rid] = made
        _made[rid] = key
    _generation += 1


def run(todo, cache_dir, cancelled=lambda: False, on_progress=None):
    """Measure what of a Plan has changed and publish it. Returns {id: why not} (the plan's own
    problems among them). Raises Cancelled."""
    problems = dict(todo.problems)
    with _lock:
        for rid in list(_made):
            if rid not in todo.keys():
                _publish(rid, None, None)
        for n, job in enumerate(todo.jobs):
            if _made.get(job.rid) == job.key:
                continue
            box = (job.tap_key, job.spec["lo_hz"], job.spec["hi_hz"])
            try:
                db = _levels.get(box)
                if db is None:
                    pcm = tap(job.snap, cache_dir, job.tap_key, cancelled,
                              on_progress and (lambda f: on_progress((n + f) / len(todo.jobs))))
                    db = box_db(pcm.astype(np.float32), job.spec["lo_hz"], job.spec["hi_hz"])
                    _levels[box] = db
                    while len(_levels) > LEVELS_KEPT:
                        _levels.pop(next(iter(_levels)))
                _publish(job.rid, job.key, shape(db, job.spec))
            except Cancelled:
                raise
            except Exception as exc:                    # (the others are still measured)
                problems[job.rid] = f"{type(exc).__name__}: {exc}"
                _publish(job.rid, None, None)
    return problems


def prepare(root, cache_dir, cancelled=lambda: False, on_progress=None):
    return run(plan(root), cache_dir, cancelled, on_progress)


def in_use(root, p):
    """Whether anything reads parameter p."""
    from . import rack
    return rack.users(root, p["name"]) > 0 or any(p["name"] in rack.refs(root, q) for q in rack.params(root))


def require(root, cache_dir, cancelled=lambda: False, on_progress=None, allow_errors=False, say=None):
    """Everything measured, for an export. A parameter in use that cannot be: RuntimeError, or with
    allow_errors said and left reading 0."""
    if not sounding(root):
        return
    try:
        problems = prepare(root, cache_dir, cancelled, on_progress)
    except Cancelled:
        raise RuntimeError("已取消") from None
    bad = [f"  {p['name']}：{problems[p['id']]}" for p in sounding(root) if p["id"] in problems and in_use(root, p)]
    if bad:
        text = "有全局參數的聲音來源算不出來：\n" + "\n".join(bad)
        if not allow_errors:
            raise RuntimeError(text)
        if say:
            say(text)
