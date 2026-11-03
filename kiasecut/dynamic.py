"""Filters whose sockets and choices come from the node's own data (a filter file saying `// @dynamic name`): Blender's Menu
Switch has as many options as its user gave it, each with a name of its own, which a fixed .glsl header cannot say. The node
keeps node["items"] = [{"sock": socket name, "name": label}]; fx.for_node() asks generate() for the filter text of those.

The first item is always on the socket "src" (the main picture of any filter node); the others are "i<number>", a number
never used again by that node, so a link stays with its item whatever is added, removed or put in another order."""
import re

DEFAULT_NAMES = ("選項 1", "選項 2", "選項 3")


def clean(name):
    """A name the filter header can carry: no | (the choices' separator) and no quotes or line breaks."""
    return re.sub(r'[|"\'\\\r\n]', "", str(name)).strip() or "選項"


def default_items(kind):
    return [{"sock": "src" if i == 0 else f"i{i + 1}", "name": n} for i, n in enumerate(DEFAULT_NAMES)]


def items_of(node, kind):
    """The items of a node (the default ones for a node made before it had any)."""
    got = node.get("items")
    return [(it["sock"], it["name"]) for it in got] if got else [(it["sock"], it["name"]) for it in default_items(kind)]


def unique(names):
    out, seen = [], set()
    for n in map(clean, names):
        base, k = n, 1
        while n in seen:
            k += 1
            n = f"{base} {k}"
        seen.add(n)
        out.append(n)
    return out


def generate(kind, items):
    """The text of the filter `kind` for items [(socket, name)]."""
    return GENERATORS[kind](items)


def menu_switch(items):
    names = unique(n for _s, n in items)
    head = ["// @filter 選單切換",
            "// @category 轉換器",
            "// @description 節點用：照 Blender 的「選單切換」節點（Menu Switch）：用選單選一張圖輸出，沒被選到的圖不會被運算。選項自己加（把線拉到最下面的空插槽）、改名（在選項上按右鍵）、刪除；選單可以在效果面板做成參數，一次切換整個效果",
            "// @dynamic menu_switch",
            f'// @source "{names[0]}"']
    head += [f'// @input {s} "{n}"' for (s, _), n in zip(items[1:], names[1:])]
    head += [f'// @param choice menu "{names[0]}" "{"|".join(names)}" "選單"']
    head += [f"// @use {s} choice == {n}" for (s, _), n in zip(items, names)]
    body = ["", "vec4 effect(vec2 uv) {", "    switch (choice) {"]
    body += [f"    case {k}: return {'src(uv)' if s == 'src' else f'input_{s}(uv)'};" for k, (s, _) in enumerate(items)]
    body += ["    }", "    return vec4(0.0);", "}", ""]
    return "\n".join(head + body)


GENERATORS = {"menu_switch": menu_switch}
