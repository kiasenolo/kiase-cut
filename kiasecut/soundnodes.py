"""聲音節點效果: an effect that is a graph of effects, wired by hand.

    {"id", "effect": "graph", "graph": {"nodes": {node id: node}, "links": [[from, output, to, input]]}}

A node is {"type", "x", "y", optional "w", "mute"} and by type:
    in, out         the effect's own sound coming in, and what it gives (one of each, always)
    ext             外部輸入: "channel": the id of a track or bus of the level, as it comes
                    out of its fader - to take apart what a bus is sent, or as a side-chain
    split, merge    分離聲道 / 合併聲道: stereo into L and R and back; a lone side goes down
                    both channels
    mix             混音: "inputs" sounds added, each with its volume (params g1, g2... dB)
    fx              one of soundfx.EFFECTS: "effect", "params" (like a chain's entry - the
                    side-chain is a socket of its own)
    reroute         繞線
    frame           框架: "name", "color", "w", "h" - a box drawn behind nodes
    value, global,  nodes that give a number (soundnumbers.py, which has the whole list):
    math, maprange, 數值, 全局參數, 數學, 映射範圍, 限制 and more
    clamp, ...
    level           電平 → 數值: a sound comes in, how loud a box of its spectrum is goes out as a
                    number
An input takes one link. Sound sockets carry stereo; a side from split is the same in both.

Numbers have wires of their own: from a number node's output into a parameter of a node, the
link's input then being "param:<name>" instead of an input's number. A wired parameter is the
number as it comes (held to the parameter's limits), over its keyframes and bindings, worked
out once a block (soundnumbers.Numbers). Sound and number sockets never join.

GraphFx is the compiled form soundgraph's engine runs in a chain.
"""
import copy

import numpy as np

from . import soundfx, soundnumbers

FIXED = ("in", "out")                   # the two nodes a graph always has, and only once
MIX_MAX = 8
TITLES = {"in": "輸入", "out": "輸出", "ext": "外部輸入", "split": "分離聲道", "merge": "合併聲道", "mix": "混音",
          "reroute": "繞線", "frame": "框架", **soundnumbers.TITLES}
PARAM = "param:"


def new_graph():
    return {"nodes": {"in": {"type": "in", "x": 0.0, "y": 0.0}, "out": {"type": "out", "x": 640.0, "y": 0.0}},
            "links": [["in", 0, "out", 0]]}


def title(node):
    if node["type"] == "fx":
        spec = soundfx.EFFECTS.get(node.get("effect"))
        return spec["title"] if spec else str(node.get("effect"))
    return node.get("name") or TITLES.get(node["type"], node["type"])


def inputs(node):
    """[(label, kind)] of a node's inputs; kind: "stereo" | "l" | "r"."""
    t = node["type"]
    if t == "fx":
        spec = soundfx.EFFECTS.get(node.get("effect")) or {}
        return [("輸入", "stereo")] + ([("側鏈", "stereo")] if spec.get("side") else [])
    if t == "level":
        return [("輸入", "stereo")]
    if t == "merge":
        return [("L", "l"), ("R", "r")]
    if t == "mix":
        return [(f"輸入 {i + 1}", "stereo") for i in range(node.get("inputs", 2))]
    if t in ("out", "split", "reroute"):
        return [("輸入" if t != "reroute" else "", "stereo")]
    return []


def outputs(node):
    t = node["type"]
    if t in soundnumbers.TYPES:
        return [(label, "num") for label in soundnumbers.OUTPUTS.get(t, ("數值",))]
    if t == "split":
        return [("L", "l"), ("R", "r")]
    if t in ("out", "frame"):
        return []
    return [("" if t == "reroute" else "輸出", "stereo")]


def wire_specs(node):
    """The parameters of a node a number can be wired into (their specs, soundfx.P)."""
    t = node["type"]
    if t == "fx":
        specs = (soundfx.EFFECTS.get(node.get("effect")) or {}).get("params", ())
    elif t == "mix":
        specs = [soundfx.spec(node, f"g{i + 1}") for i in range(len(inputs(node)))]
    else:
        specs = soundnumbers.specs(node) if t in soundnumbers.TYPES and t not in soundnumbers.CONSTANTS else ()
    return [p for p in specs if not p.get("nowire")]


def is_param(socket):
    return isinstance(socket, str)


def param_of(socket):
    return socket[len(PARAM):]


def wires(graph, cut=()):
    """{(node id, parameter name): (node, output) whose number is wired into it}. cut: (from, to) pairs left out."""
    return {(l[2], param_of(l[3])): (l[0], l[1]) for l in graph["links"]
            if is_param(l[3]) and l[0] in graph["nodes"] and l[2] in graph["nodes"] and (l[0], l[2]) not in cut}


def numbers(graph, t_us, names=None, heard=None, length=0):
    """soundnumbers.Numbers of a graph at one moment."""
    return soundnumbers.Numbers(graph["nodes"], wires(graph, _order(graph)[1]), t_us, names, heard, length)


def new_node(kind, x=0.0, y=0.0, **extra):
    """kind: a node type, or an effect of soundfx.EFFECTS."""
    if kind in soundfx.EFFECTS:
        node = {"type": "fx", "effect": kind, "params": soundfx.new_effect(kind, "")["params"]}
    elif kind in soundnumbers.TYPES:
        node = {"type": kind, "params": soundnumbers.new_params(kind)}
    elif kind in TITLES and kind not in FIXED:
        node = {"type": kind}
        if kind == "mix":
            node.update(inputs=2, params={"g1": 0.0, "g2": 0.0})
        elif kind == "ext":
            node["channel"] = ""
        elif kind == "frame":
            node.update(name="框架", color="#6c696f", w=300.0, h=200.0)
    else:
        raise ValueError("unknown node " + str(kind))
    node.update(x=float(x), y=float(y), **extra)
    return node


def new_id(graph):
    n = 1
    while f"n{n}" in graph["nodes"]:
        n += 1
    return f"n{n}"


def link_into(graph, nid, socket):
    return next((l for l in graph["links"] if l[2] == nid and l[3] == socket), None)


def reaches(graph, start, goal):
    """Whether sound from node start gets to node goal."""
    seen, stack = set(), [start]
    while stack:
        i = stack.pop()
        if i == goal:
            return True
        if i not in seen:
            seen.add(i)
            stack += [l[2] for l in graph["links"] if l[0] == i]
    return False


def can_link(graph, src, out, dst, socket):
    nodes = graph["nodes"]
    if src not in nodes or dst not in nodes or not 0 <= out < len(outputs(nodes[src])):
        return False
    number = outputs(nodes[src])[out][1] == "num"
    if is_param(socket):
        if not number or not socket.startswith(PARAM) or all(p["name"] != param_of(socket) for p in wire_specs(nodes[dst])):
            return False
    else:
        count = len(inputs(nodes[dst])) + (1 if nodes[dst]["type"] == "mix" and len(inputs(nodes[dst])) < MIX_MAX else 0)
        if number or not 0 <= socket < count:
            return False
    return src != dst and not reaches(graph, dst, src)


def connect(graph, src, out, dst, socket):
    """Wire output out of src into input socket of dst (in place of what was there). The
    socket one past a mixer's last is a new one."""
    if not can_link(graph, src, out, dst, socket):
        raise ValueError("不能這樣接（會接成迴圈，或沒有這個接點）")
    node = graph["nodes"][dst]
    if node["type"] == "mix" and not is_param(socket) and socket == len(inputs(node)):
        node["inputs"] = socket + 1
        node.setdefault("params", {})[f"g{socket + 1}"] = 0.0
    graph["links"] = [l for l in graph["links"] if not (l[2] == dst and l[3] == socket)]
    graph["links"].append([src, out, dst, socket])


def disconnect(graph, links):
    """Take links (each [from, output, to, input]) out."""
    gone = {tuple(l) for l in links}
    graph["links"] = [l for l in graph["links"] if tuple(l) not in gone]


def add(graph, node):
    nid = new_id(graph)
    graph["nodes"][nid] = node
    return nid


def insert_on_link(graph, nid, link):
    """Put node nid (its first input and output) into a link."""
    node = graph["nodes"][nid]
    if list(link) not in graph["links"] or not inputs(node) or not outputs(node) or nid in (link[0], link[2]) \
            or is_param(link[3]) or outputs(node)[0][1] == "num":
        raise ValueError("這個節點不能插進這條線")
    graph["links"] = [l for l in graph["links"] if l[0] != nid and l[2] != nid and l != list(link)]
    connect(graph, link[0], link[1], nid, 0)
    connect(graph, nid, 0, link[2], link[3])


def remove(graph, ids, keep_links=False):
    """Delete nodes (never 輸入 / 輸出). keep_links: join what fed each one's first input to
    what its outputs fed."""
    for nid in ids:
        node = graph["nodes"].get(nid)
        if node is None or node["type"] in FIXED:
            continue
        feed = link_into(graph, nid, PARAM + soundnumbers.THROUGH[node["type"]]
                         if node["type"] in soundnumbers.THROUGH else 0)
        if node["type"] == "level":             # (sound in, a number out: nothing to join)
            feed = None
        onward = [l for l in graph["links"] if l[0] == nid]
        graph["links"] = [l for l in graph["links"] if nid not in (l[0], l[2])]
        del graph["nodes"][nid]
        if keep_links and feed is not None:
            graph["links"] += [[feed[0], feed[1], l[2], l[3]] for l in onward]


def copy_nodes(graph, ids):
    """What Ctrl+C keeps: the nodes (not 輸入 / 輸出) and the links among them."""
    keep = [i for i in ids if i in graph["nodes"] and graph["nodes"][i]["type"] not in FIXED]
    return {"nodes": {i: copy.deepcopy(graph["nodes"][i]) for i in keep},
            "links": [list(l) for l in graph["links"] if l[0] in keep and l[2] in keep]}


def paste(graph, data, dx=0.0, dy=0.0):
    """Add copied nodes, moved by (dx, dy). Returns their new ids."""
    names = {}
    for old, node in data["nodes"].items():
        node = copy.deepcopy(node)
        node["x"], node["y"] = node["x"] + dx, node["y"] + dy
        names[old] = add(graph, node)
    for src, out, dst, socket in data["links"]:
        graph["links"].append([names[src], out, names[dst], socket])
    return [names[k] for k in data["nodes"]]


def param_dicts(graph):
    """Every node's params (for what walks a clip's keyframes)."""
    return [n["params"] for n in graph["nodes"].values() if n.get("params")]


def channels_used(graph):
    return [n["channel"] for n in graph["nodes"].values() if n["type"] == "ext" and n.get("channel") and not n.get("mute")]


def _order(graph):
    """Node ids (frames left out) with every one after what feeds it; links that would make
    a loop (a hand-edited file) are returned to be left out."""
    nodes = [i for i, n in graph["nodes"].items() if n["type"] != "frame"]
    feeds = {i: [] for i in nodes}
    for l in graph["links"]:
        if l[2] in feeds and l[0] in feeds:
            feeds[l[2]].append(l[0])
    order, state, cut = [], {}, set()

    def visit(i):
        state[i] = 1
        for j in feeds[i]:
            if state.get(j) == 1:
                cut.add((j, i))
            elif j not in state:
                visit(j)
        state[i] = 2
        order.append(i)
    for i in nodes:
        if i not in state:
            visit(i)
    return order, cut


# -- compiled --------------------------------------------------------------------------------------
class GraphFx:
    """A graph as one step of a chain (soundgraph.Fx's interface)."""

    def __init__(self, key, entry, make_fx, length=0):
        """make_fx(key, entry, name) -> soundgraph.Fx for an effect node. length: of what the
        chain runs through (the clip, or the timeline), for 場景時間."""
        self.key, self.entry, self.length = key, entry, length
        graph = entry["graph"]
        self.nodes = graph["nodes"]
        self.order, cut = _order(graph)
        self.id = entry["id"]
        self.feeds = {(l[2], l[3]): (l[0], l[1]) for l in graph["links"]
                      if l[0] in self.nodes and l[2] in self.nodes and (l[0], l[2]) not in cut}
        self.wires = wires(graph, cut)
        self.wired = {dst for dst, _name in self.wires}
        self.fx = {}
        self.blocked = set()                # channels it may not listen to (that would be a loop)
        self.before, self.after, ring = {}, {}, {}
        self.settle = 0.0                   # seconds a start from the middle should run first (a slow follower)
        for nid in self.order:
            node = self.nodes[nid]
            sources = [self.feeds[(nid, i)][0] for i in range(len(inputs(node))) if (nid, i) in self.feeds]
            # (a number measured from late sound makes what it is wired into wait for it, as a sound path would)
            numbers_from = [src for (dst, _name), (src, _out) in self.wires.items() if dst == nid]
            lat = max([self.after.get(s, 0) for s in sources + numbers_from], default=0)
            if node["type"] == "level":
                held_ms = soundnumbers.own_values(node, 0.0)
                self.settle = max(self.settle, 5 * max(held_ms["attack"], held_ms["release"]) / 1000)
            own = 0.0
            self.before[nid] = lat
            if node["type"] == "fx" and node.get("effect") in soundfx.EFFECTS and not node.get("mute"):
                one = self.fx[nid] = make_fx(key + (nid,), node, entry["id"] + "/" + nid)
                lat += one.latency
                own = one.tail
            self.after[nid] = lat
            ring[nid] = max([ring.get(s, 0.0) for s in sources], default=0.0) + own
        out = next((i for i, n in self.nodes.items() if n["type"] == "out"), None)
        self.out = out
        self.latency = self.before.get(out, 0)
        self.tail = min(soundfx.MAX_TAIL_S, ring.get(out, 0.0))

    def _listen(self, engine, nid, node, x, pos, late, t_of, given):
        """A block of the sound into level node nid, `late` samples late."""
        from . import soundmeter
        key = self.key + (nid, "level")
        follower = engine.state.get(key)
        if follower is None:
            follower = engine.state[key] = soundmeter.Follower()
        mixed = (pos - late) * 1_000_000 / engine.rate
        v = soundnumbers.own_values(node, t_of(mixed), engine.names(mixed) if node.get("expr") else None)
        v.update(given or {})
        mono = x.mean(axis=1)
        number = follower.feed(mono, v["lo_hz"], v["hi_hz"], v["floor_db"], v["top_db"], v["attack"] / 1000,
                               v["release"] / 1000)
        name = self.id + "/" + nid              # (for the node's number and the spectrum drawn in it)
        engine._remember(engine.meters, name, pos - late, np.array([number], np.float32))
        if name in engine.watched:
            engine.keep(name, pos - late, mono)

    def listens(self):
        return [c for c in channels_used(self.entry["graph"]) if c not in self.blocked]

    def unlisten(self, channel_id):
        self.blocked.add(channel_id)

    def run(self, engine, x, pos, latency, t_of, posts, post_latency, top):
        """x (latency samples late) through the graph; returns (sound, how late it is now)."""
        made = {}
        quiet = np.zeros_like(x)
        moments = {}                        # how late a node is -> the graph's numbers at its time

        def wired(nid, late):
            """{name: number} wired into node nid, whose sound is `late` samples late."""
            if nid not in self.wired:
                return None
            at = moments.get(late)
            if at is None:
                mixed = (pos - late) * 1_000_000 / engine.rate
                at = moments[late] = soundnumbers.Numbers(self.nodes, self.wires, t_of(mixed),
                                                          lambda: engine.names(mixed), lambda n: heard(n, late),
                                                          self.length)
            return at.into(nid, wire_specs(self.nodes[nid]))

        def heard(nid, late):
            """What level node nid read from the sound that is `late` samples late (or the nearest it has)."""
            follower = engine.state.get(self.key + (nid, "level"))
            return None if follower is None else follower.at(late - (latency + self.before[nid]))


        for nid in self.order:
            node, kind = self.nodes[nid], self.nodes[nid]["type"]
            if kind in soundnumbers.TYPES and kind != "level":
                continue                    # (worked out as they are read)
            ins = []
            for i in range(len(inputs(node))):
                feed = self.feeds.get((nid, i))
                if feed is None or feed[0] not in made:
                    ins.append(None)
                else:               # paths that meet are brought to the same time
                    ins.append(engine._delayed(self.key + (nid, i), made[feed[0]][feed[1]],
                                               self.before[nid] - self.after[feed[0]]))
            first = ins[0] if ins and ins[0] is not None else quiet
            if kind == "level":
                if not node.get("mute"):
                    self._listen(engine, nid, node, first, pos, latency + self.before[nid], t_of,
                                 wired(nid, latency + self.before[nid]))
                made[nid] = [quiet]         # (it gives no sound: nothing is wired to this)
                continue
            if kind == "in":
                result = [x]
            elif kind == "ext":
                c = node.get("channel")
                if c in posts and c not in self.blocked and not node.get("mute"):
                    result = [engine._delayed(self.key + (nid, "ext"), posts[c], latency - post_latency[c])]
                else:
                    result = [quiet]
            elif kind == "split":
                result = [np.repeat(first[:, 0:1], 2, axis=1), np.repeat(first[:, 1:2], 2, axis=1)]
            elif kind == "merge":
                sides = [(s if s is not None else quiet).mean(axis=1) for s in ins]
                result = [np.stack(sides, axis=1)]
            elif kind == "mix":
                total = quiet
                if node.get("mute"):
                    total = first
                else:
                    now = t_of((pos - latency - self.before[nid]) * 1_000_000 / engine.rate)
                    names = engine.names((pos - latency - self.before[nid]) * 1_000_000 / engine.rate) \
                        if node.get("expr") else None
                    given = wired(nid, latency + self.before[nid]) or {}
                    for i, s in enumerate(ins):
                        if s is not None:
                            db = given.get(f"g{i + 1}")
                            if db is None:
                                db = soundfx.curve_value((node.get("params") or {}).get(f"g{i + 1}", 0.0), now)
                                db = soundfx.followed(node, f"g{i + 1}", db, now, names)
                            g = 0.0 if db <= -60.0 else 10 ** (db / 20)
                            total = total + engine._ramp(self.key + (nid, "g", i), s, g, g)
                result = [total]
            elif kind == "fx" and nid in self.fx:
                side = ins[1] if len(ins) > 1 else None
                y, _ = self.fx[nid].run(engine, first, pos, latency + self.before[nid], t_of, posts, post_latency,
                                        top, side, wired(nid, latency + self.before[nid]))
                result = [y]
            else:                   # out, reroute, a muted or unknown node: straight through
                result = [first]
            made[nid] = result
        return made[self.out][0] if self.out in made else quiet, latency + self.latency
