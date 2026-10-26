"""批量編輯關鍵幀: an edit of one clip's curve carried over to the other selected clips.

Two keyframes are alike when they are on the same parameter, at most a frame apart (in clip
time: from each clip's own start) and their values close: within 1% of the larger value or
of the curve's range (a colour: 1% on every channel; a choice: the same one). match() pairs
each keyframe of the edited curve with the nearest alike one of another clip.

carry() takes the edited curve before and after an edit (the curve editor keeps the keys in
order while dragging, adds or removes whole keys, and changes handles in place) and does
the same to the paired keyframes: moved by the same time and value (each keeps its own
small difference), the same new ease, removed with it; a key added among paired ones is
added at the same time, its value moved from the other curve's as much as the edited one's.
"""
import copy

from . import curves

US = 1_000_000
VALUE_TOL = 0.01


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def span(keys):
    """The range a curve's numbers cover (0 for colours and choices)."""
    nums = [k[1] for k in keys if _number(k[1])]
    return max(nums) - min(nums) if nums else 0.0


def close(a, b, rng=0.0):
    """Whether two keyframe values are alike (see the module notes)."""
    if isinstance(a, list) or isinstance(b, list):
        return (isinstance(a, list) and isinstance(b, list) and len(a) == len(b)
                and all(abs(x - y) <= VALUE_TOL + 1e-9 for x, y in zip(a, b)))
    if not (_number(a) and _number(b)):
        return a == b
    return abs(a - b) <= VALUE_TOL * max(abs(a), abs(b), rng) + 1e-9


def match(keys, other, fps):
    """{index in keys: index in other}: each keyframe of keys paired with the nearest unpaired
    alike keyframe of other (see the module notes)."""
    frame = US / fps
    rng = span(keys)
    out, used = {}, set()
    for i, k in enumerate(keys):
        best = None
        for j, o in enumerate(other):
            dt = abs(o[0] - k[0])
            if j not in used and dt <= frame + 1 and close(k[1], o[1], rng) and (best is None or dt < best[0]):
                best = (dt, j)
        if best is not None:
            out[i] = best[1]
            used.add(best[1])
    return out


def _diff(old, new):
    """({old index: new index}, old indices removed, new indices added) between a curve before
    and after one curve-editor edit: the same number of keys keep their places; otherwise
    the keys left alone are found unchanged in order."""
    if len(old) == len(new):
        return {i: i for i in range(len(old))}, [], []
    pairs, removed, added = {}, [], []
    i = j = 0
    while i < len(old) or j < len(new):
        if i < len(old) and j < len(new) and old[i] == new[j]:
            pairs[i] = j
            i, j = i + 1, j + 1
        elif len(new) < len(old) and i < len(old):
            removed.append(i)
            i += 1
        elif j < len(new):
            added.append(j)
            j += 1
        else:
            removed.append(i)
            i += 1
    return pairs, removed, added


def _shift(mine, before, after):
    """Another curve's value moved as an edit moved before to after."""
    if _number(mine) and _number(before) and _number(after):
        return mine + (after - before)
    if isinstance(mine, list) and isinstance(before, list) and isinstance(after, list):
        return [min(1.0, max(0.0, m + (a - b))) for m, b, a in zip(mine, before, after)]
    return after if mine == before else mine


def carry(old, new, other, fps, duration, tol_us=0):
    """The keys of another clip's curve other after the edit old -> new of the edited curve;
    None when no keyframe of other is alike one of old (nothing to do), and None too when
    the edit would put two of its keys at the same moment (closer than tol_us)."""
    pairs_of = match(old, other, fps)
    if not pairs_of:
        return None
    pairs, removed, added = _diff(old, new)
    out = [copy.deepcopy(o) for o in other]
    for i, j in pairs.items():
        if i not in pairs_of or new[j] == old[i]:
            continue
        o, n, k = old[i], new[j], out[pairs_of[i]]
        k[0] = int(min(max(k[0] + n[0] - o[0], 0), duration))
        k[1] = _shift(k[1], o[1], n[1])
        if n[2:] != o[2:]:
            k[2:] = copy.deepcopy(n[2:])
    gone = {pairs_of[i] for i in removed if i in pairs_of}
    keep = out[min(gone)][1] if gone else None          # (all gone: the value the first of them had)
    out = [k for idx, k in enumerate(out) if idx not in gone]
    for j in added:
        n = new[j]
        before = curves.value({"keys": old}, n[0]) if old else n[1]
        mine = curves.value({"keys": other}, n[0])
        out.append([n[0], _shift(mine, before, n[1])] + copy.deepcopy(n[2:]))
    out.sort(key=lambda k: k[0])
    if any(b[0] - a[0] <= tol_us for a, b in zip(out, out[1:])):
        return None
    return out, keep
