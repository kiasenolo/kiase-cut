"""The sound effects (聲音效果) there are, and where a project keeps them.

An effect entry is {"id", "effect": a key of EFFECTS, "params": {name: number or curve},
optional "enabled" (default true), "side": {"id": a track or bus of the same level} (the
side-chain, for effects that take one)}. A chain is a list of them, applied in order:

    clip["sound_effects"]       the clip's own, after its 音量 and fades (keys in clip time)
    track["sound_effects"]      the whole track's
    bus["sound_effects"]        a bus's, on what is sent into it
    master["sound_effects"]     the level's output

A level (timeline or compound) also holds its buses and master, in the compound that is the
level (project.mix_of): "buses": [{id, name, gain, pan, muted, solo, output, sends,
sound_effects}], "master": {"sound_effects"}. A track has the same pan, output, sends next
to its gain, muted and solo. output: a bus id, absent: the master. sends: [{"bus": id,
"gain": dB (number or curve), "pre": before the fader}]. pan: -1 (left) ... 1 (right).
The signal's way is soundgraph.py's.
"""
from . import curves, project

MASTER = "master"
SEND_OFF_DB = -60.0              # a send turned this low sends nothing
MAX_TAIL_S = 30.0


def P(name, label, lo, hi, default, unit="", **kw):
    return dict(name=name, label=label, min=lo, max=hi, default=default, unit=unit, **kw)


def C(name, label, choices, default, **kw):
    """A parameter that is one of a few choices (stored as its number)."""
    return P(name, label, 0, len(choices) - 1, default, choices=list(choices), **kw)


def switch(name, label, default=0, **kw):
    return C(name, label, ["關", "開"], default, **kw)


EQ_BANDS = 8
EQ_TYPES = ("鐘形", "低架", "高架", "低切", "高切", "陷波")
EQ_GAIN_TYPES, EQ_Q_TYPES, EQ_CUT_TYPES = (0, 1, 2), (0, 1, 2, 5), (3, 4)
EQ_DEFAULT = [(1, 80.0, 1), (0, 250.0, 1), (0, 1000.0, 1), (0, 4000.0, 1), (2, 10000.0, 1), (0, 500.0, 0),
              (0, 2000.0, 0), (0, 8000.0, 0)]          # (type, frequency, on)
FILTER_MODES = ["低通 12", "低通 24", "低通 36", "高通 12", "高通 24", "高通 36", "帶通 6", "帶通 12", "帶通 18",
                "帶阻 6", "帶阻 12", "帶阻 18", "全通"]


def _eq_params():
    """Each band's parameters carry its number ("band") and, where they only count for
    some types, "when": a function of the effect's values."""
    out = []
    for i, (kind, f, on) in enumerate(EQ_DEFAULT, 1):
        is_a = lambda kinds, i=i: lambda v, i=i: round(v[f"t{i}"]) in kinds
        out += [switch(f"o{i}", "啟用", on, band=i), C(f"t{i}", "類型", EQ_TYPES, kind, band=i),
                C(f"s{i}", "斜率", ["12 dB/oct", "24 dB/oct", "36 dB/oct", "48 dB/oct"], 1, band=i,
                  when=is_a(EQ_CUT_TYPES)),
                P(f"f{i}", "頻率", 20.0, 20000.0, f, "Hz", log=True, band=i),
                P(f"g{i}", "增益", -24.0, 24.0, 0.0, "dB", band=i, when=is_a(EQ_GAIN_TYPES)),
                P(f"q{i}", "Q", 0.1, 18.0, 0.7 if kind in (1, 2) else 1.0, band=i, when=is_a(EQ_Q_TYPES))]
    return out + [P("out", "輸出增益", -24.0, 24.0, 0.0, "dB")]


# key: {title, params, optional visual: what the panel draws above them, optional side: it takes a side-chain}; the key names the C effect too
EFFECTS = {
    "gain": {"title": "增益", "params": [P("gain", "增益", -60.0, 24.0, 0.0, "dB")]},
    "highpass": {"title": "高通濾波", "params": [P("f", "截止頻率", 20.0, 20000.0, 80.0, "Hz", log=True),
                                              P("q", "Q", 0.1, 10.0, 0.7071)]},
    "lowpass": {"title": "低通濾波", "params": [P("f", "截止頻率", 20.0, 20000.0, 12000.0, "Hz", log=True),
                                             P("q", "Q", 0.1, 10.0, 0.7071)]},
    "eq": {"title": "參數等化器 (EQ)", "visual": "eq", "params": _eq_params()},
    "filter": {"title": "多模式濾波器", "visual": "response",
               "params": [C("mode", "模式", FILTER_MODES, 1), P("freq", "頻率", 20.0, 20000.0, 2000.0, "Hz", log=True),
                          P("res", "共振", 0.71, 32.0, 0.7071, log=True)]},
    "analyzer": {"title": "頻譜分析器", "visual": "spectrum", "params": []},
}
CATEGORIES = [("增益、EQ 與濾波", ["gain", "eq", "highpass", "lowpass", "filter", "analyzer"])]
KEYWORDS = {"gain": "volume 音量", "highpass": "高通 low cut", "lowpass": "低通 high cut", "eq": "equalizer 等化 均衡",
            "filter": "濾波 lowpass highpass bandpass 帶通 帶阻", "analyzer": "spectrum 頻譜 meter"}


def new_effect(kind, effect_id):
    return {"id": effect_id, "effect": kind, "params": {p["name"]: p["default"] for p in EFFECTS[kind]["params"]}}


def title(e):
    spec = EFFECTS.get(e.get("effect"))
    return spec["title"] if spec else str(e.get("effect"))


def active(chain):
    """The entries of a chain that do something: on, and of a kind there is."""
    return [e for e in chain or () if e.get("enabled", True) and e.get("effect") in EFFECTS]


def values(e, t_us):
    """{name: number} of entry e's parameters at time t_us (a missing one: its default)."""
    given = e.get("params") or {}
    out = {}
    for p in EFFECTS[e["effect"]]["params"]:
        v = given.get(p["name"], p["default"])
        out[p["name"]] = float(curves.value(v, t_us))
    return out


def pan_of(holder):
    return holder.get("pan", 0.0)


def routed(holder):
    """Whether a track or bus is set to anything but straight into the master, unchanged."""
    return bool(active(holder.get("sound_effects")) or holder.get("output") or holder.get("sends")
                or holder.get("pan", 0.0) != 0.0)


def level_used(tracks, mix, seen=None):
    """Whether a level's sound needs the processing engine: an effect, a bus, a send or a pan
    on it or in anything its clips show. Without any, audiomix mixes it as it always did."""
    mix = mix or {}
    if mix.get("buses") or active((mix.get(MASTER) or {}).get("sound_effects")):
        return True
    seen = set() if seen is None else seen
    for t in tracks:
        if routed(t):
            return True
        for c in t["clips"]:
            if active(c.get("sound_effects")):
                return True
            comp = c.get("compound")
            if project.is_group(c) or (c.get("type") == "compound" and not project.is_static(c)):
                inner = c.get("tracks") if project.is_group(c) else (comp or {}).get("tracks")
                if inner is not None and id(inner) not in seen:
                    seen.add(id(inner))
                    if level_used(inner, comp, seen):
                        return True
    return False


def used(view):
    """level_used of the level a view (or the project) shows."""
    return level_used(view["tracks"], project.mix_of(view))
