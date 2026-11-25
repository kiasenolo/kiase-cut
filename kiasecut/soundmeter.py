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
"""
import copy
import hashlib
import json
import math
import os

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
    up = 1.0 if spec["attack"] <= 0 else 1.0 - math.exp(-step / spec["attack"])
    down = 1.0 if spec["release"] <= 0 else 1.0 - math.exp(-step / spec["release"])
    raw = np.concatenate([raw, np.zeros(int(spec["release"] * 7 / step) + 2, raw.dtype)])
    if up == 1.0 and down == 1.0:
        return raw.astype(np.float32)
    out, v = [], 0.0
    for x in raw.tolist():
        v += (x - v) * (up if x > v else down)
        out.append(v)
    return np.array(out, np.float32)


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
            return np.load(path)
        except (OSError, ValueError):
            pass                        # (half written: measured again)
    out = _run(snap, cache_dir, cancelled, on_progress)
    os.makedirs(folder, exist_ok=True)
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "wb") as fh:
        np.save(fh, out)
    os.replace(tmp, path)
    return out


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
