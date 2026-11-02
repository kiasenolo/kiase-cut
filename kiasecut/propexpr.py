"""Expressions on a clip's own numbers (表達式): clip["expr"] {"group.key": expression}, the props of
components.number_props_of (position, scale, rotation, opacity, a text's size, a mask's numbers,
volume, a shape's numbers). The expression replaces the number: it reads

    value       the number as the clip has it (its keyframes included), as the inspector shows it
    time        seconds into the clip      progress  0 - 1 along the clip      duration  its seconds
    ... and the names the renderer gives it (the parameter rack, rack.py)

so `value + wiggle(2, 30)` shakes a keyframed position, `100 * Math.abs(Math.sin(time))` pulses an
opacity. A broken expression, or one that gives no number, leaves the number as it is. Both
renderers draw the clip given by at(); the editor's boxes and handles keep to the clip's own numbers.
"""
from . import components, curves, expr


def exprs_of(c):
    """{prop: expression} of clip c that still apply (props it has)."""
    e = c.get("expr")
    return e if e else {}


def at(c, t_us, names=None):
    """Clip c as it is drawn t_us into it: the very clip when it has no expressions, else a copy
    with each expression's number put in."""
    e = exprs_of(c)
    if not e:
        return c
    dur = max(c.get("duration_us") or 1, 1)
    base = {"time": t_us / curves.US, "progress": min(1.0, max(0.0, t_us / dur)), "duration": dur / curves.US}
    base.update(names or {})
    out = c
    for prop, text in e.items():
        try:
            cur = components.number_at(c, prop, t_us)
        except (KeyError, ValueError, TypeError):
            continue                                         # (a prop the clip has not got any more)
        v = expr.safe(text, dict(base, value=cur), default=cur)
        out = components._put(out, prop, v)
    return out
