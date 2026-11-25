"""The right-click items by which a sound parameter follows a global parameter (全局參數) or an
expression: soundfx keeps it as entry["expr"][name]."""
from PySide6.QtWidgets import QInputDialog

from .. import curves, edit, expr, mapping, rack, soundedit
from . import mapdialog

TITLE = "綁定全局參數"


def followed_by(page, target, address, name):
    """What the parameter follows now, or None."""
    try:
        return (soundedit.effect(page.level(), target, address).get("expr") or {}).get(name)
    except edit.EditError:
        return None


def said(text):
    """A line for a tooltip."""
    if mapping.is_mapping(text):
        return f"{text.get('src') or ''}（{mapping.label(text)}）"
    return str(text)


def add_items(menu, page, target, address, spec, time, done=lambda: None):
    """Add the items for parameter spec of target's effect at address; time: the chain's time."""
    win, name = page.win, spec["name"]
    have = followed_by(page, target, address, name)

    def put(text, label=TITLE):
        win.apply_root(label, lambda root: soundedit.bind(root, win.container(root), target, address, name, text))
        done()

    def current():
        held = (soundedit.effect(page.level(), target, address).get("params") or {}).get(name, spec["default"])
        return float(curves.value(held, time or 0))

    def ask_mapping(src, source_label, value, values):
        m = have if mapping.is_mapping(have) and have.get("src") == src else mapping.make(src=src)
        return mapdialog.ask_mapping(win, f"綁定：{spec['label']}", m, source_label, value, values,
                                     (0.0, 1.0) if spec.get("free") else (float(spec["min"]), float(spec["max"])))

    def bind(src):
        values = rack.values(win.proj, win.playhead_us())
        x = values.get(src)
        out = ask_mapping(src, f"全局參數「{src}」", None if x is None else float(x), values)
        if out is not None:
            put(out)

    def bind_new():
        made = win.ask_rack_name()
        if not made:
            return
        value = current()
        out = ask_mapping(made, f"新的全局參數「{made}」", value, {made: value})
        if out is None:
            return

        def fn(root):
            edit.add_rack_param(root, made, value)
            soundedit.bind(root, win.container(root), target, address, name, out)
        win.apply_root("新增全局參數並綁定", fn)
        done()

    def ask_expression():
        text, ok = QInputDialog.getText(win, f"表達式：{spec['label']}",
                                        "value 是原本的數值，time 是秒，全局參數直接寫名稱：",
                                        text=have if isinstance(have, str) else "value")
        if not ok:
            return
        why = expr.check(text.strip()) if text.strip() else None
        if why:
            win.statusBar().showMessage(f"表達式有問題：{why}", 6000)
            return
        put(text.strip(), "聲音參數表達式")

    sub = menu.addMenu(TITLE)
    sub.addAction("新增全局參數並綁定…", bind_new)
    numbers = [p["name"] for p in rack.params(win.proj) if rack.kind_of(p) in rack.NUMERIC]
    vectors = [p for p in rack.params(win.proj) if rack.kind_of(p) in rack.SIZES]
    if numbers or vectors:
        sub.addSeparator()
    for n in numbers:
        sub.addAction(n, lambda n=n: bind(n))
    for p in vectors:                                   # (one of a vector's numbers, as it is)
        parts = sub.addMenu(p["name"])
        for i, axis in enumerate("XYZ"[:rack.SIZES[rack.kind_of(p)]]):
            part = f"{p['name']}[{i}]"
            parts.addAction(f"{axis}　{part}", lambda part=part: put(part))
    if mapping.is_mapping(have) and have.get("src"):
        menu.addAction(f"映射…（{mapping.label(have)}）", lambda: bind(have["src"]))
    menu.addAction("自訂表達式…", ask_expression)
    if have:
        menu.addAction("解除綁定／清除表達式", lambda: put("", "清除表達式"))
