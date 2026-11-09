"""說明 Wiki: the pages of the help window, made from what the program knows about itself - the node menu's layout (nodemenu.py), every
filter's header (name, description, sockets, parameters: fx.py) and the 濾鏡寫法 document. A page is an id and some HTML for a
QTextBrowser (ui/wiki_window.py shows them); nothing here needs Qt, so it is tested and can be exported alone.

Page ids: "home", "types" (the data types and their socket dots), "nodes" and "cat:<menu>" (a menu of the node editor's Add menu),
"node:<ref or key>" (one node), "fx" and "fxcat:<category>" (KiaseCut's own effects, which are nodes too), "format" (濾鏡寫法)."""
import html
import os
from urllib.parse import quote, unquote

from . import assets, fx, nodegraph as ng, nodemenu

SCHEME = "wiki:"

# What the socket dots mean, in the order of the legend: (key of ui/node_editor.SOCKET_COLORS, name, what it is)
TYPES = (
    ("image", "圖片", "預乘透明度的 RGBA 圖：所有連線其實都是它，下面幾種只是對這張圖的不同解讀"),
    ("color", "顏色", "RGBA 原樣；顏色常數是整張圖一個顏色"),
    ("float", "浮點（數值）", "圖的明度當成一個數字，透明的地方是 0；遮罩就是黑白的浮點"),
    ("int", "整數", "取整數的數值"),
    ("bool", "布林", "開關：開是 1（整張白）、關是 0（黑）"),
    ("vector", "向量", "圖的紅、綠、藍當成 X、Y、Z（整數向量也屬於這一種）"),
    ("menu", "選單", "選項的編號，從 0 開始"),
    ("string", "字串", "文字內容。不是圖片：只能接到文字節點的內容"),
    ("font", "字體", "字體檔。不是圖片：只能接到文字節點的字體"),
    ("outline", "矢量輪廓", "形狀、文字、SVG 圖片、矢量節點給出的路徑。不是圖片：接到矢量節點（相加、布林運算…）"),
)
FALLBACK_COLORS = {"image": "#c8c85a", "float": "#a0a0a8", "color": "#d6b04a", "string": "#70b870", "font": "#b070b0", "int": "#598c5c",
                   "bool": "#cca6d6", "vector": "#6363c7", "menu": "#e08a4a", "outline": "#3fc7a8"}
PARAM_TYPES = {"float": ("數值", "float"), "int": ("整數", "int"), "bool": ("開關", "bool"), "color": ("顏色", "color"),
               "vec2": ("二維向量", "vector"), "vec3": ("向量", "vector"), "menu": ("選單", "menu"), "curve": ("曲線", None),
               "gradient": ("漸層", None)}

# The nodes that are not filters, by (type, kind, op): what they are
SPECIAL = {
    (ng.INPUT, "", ""): "這個效果收到的片段畫面，節點圖的起點。",
    (ng.PARAMS, "", ""): "把效果自己的參數接進節點圖（Blender 的群組輸入）：每個參數一個輸出，接到別的節點的參數欄位就把那個參數綁上來；"
                         "值顯示在「效果」面板，是這個效果自己的欄位。",
    (ng.SOURCE, "image", ""): "一張圖片當來源。它在片段上的位置像遮罩一樣擺放。",
    (ng.SOURCE, "video", ""): "一段影片當來源。位置像遮罩一樣擺放。",
    (ng.SOURCE, "compound", ""): "一個複合片段當來源。",
    (ng.SOURCE, "track", ""): "時間線上的一條軌道當來源。",
    (ng.SOURCE, "text", ""): "文字產生器：字號、顏色、字距、對齊、外框等。內容可以接字串節點，字體可以接字體節點；也能當矢量輪廓接進矢量節點。",
    (ng.SOURCE, "image", "svg"): "讀進一個 SVG 圖片，給出它的矢量輪廓，可以接到矢量節點。",
    (ng.SOURCE, "vector", "add"): "矢量：把多個矢量（形狀、文字、SVG、其他矢量節點）的輪廓疊在一起。",
    (ng.SOURCE, "vector", "boolean"): "矢量：把輪廓做布林運算：聯集、差集、交集、排除。",
    (ng.SOURCE, "vector", "rotate"): "矢量：旋轉一個矢量，可以繞它自己的中心或畫面中心。",
    (ng.SOURCE, "vector", "move"): "矢量：移動一個矢量。",
    (ng.SOURCE, "vector", "scale"): "矢量：縮放一個矢量。",
    (ng.FONT, "", ""): "字體常數：一個字體檔。不是圖片，只能接到文字節點的字體。",
    (ng.STRING, "", ""): "字串常數：一段文字。不是圖片，只能接到文字節點的內容。",
    (ng.VIEWER, "", ""): "編輯器的預覽看這個節點的結果。不會被匯出。",
    (ng.REROUTE, "", ""): "繞線點：連線的一個彎，圖片原樣通過。用來整理線路。",
    (ng.FRAME, "", ""): "框架／註解：圈起一群節點並寫上說明，不影響結果。",
}
HOME = """<h1>KiaseCut 說明</h1>
<p>這裡的頁面大多是從程式自己的資料產生的：節點的說明、插槽、參數都和你現在用的版本一致。</p>
<ul>
<li><a href="wiki:types">資料類型</a>：插槽上的點是什麼顏色、什麼形狀</li>
<li><a href="wiki:nodes">節點</a>：節點編輯器的 Add 選單，照選單的順序，每個節點的輸入、輸出和參數</li>
<li><a href="wiki:fx">KiaseCut 效果</a>：Blender 沒有的、「效果」清單裡的其他效果（它們也是節點）</li>
<li><a href="wiki:format">濾鏡寫法</a>：自己用 .glsl 寫濾鏡</li>
</ul>
<p>左邊的搜尋欄可以找節點、參數和說明。</p>"""


def link(page, text):
    return f'<a href="{SCHEME}{quote(page, safe=":")}">{html.escape(text)}</a>'


def page_of(url):
    """The page id a link ("wiki:...") points to ('' if it is not one)."""
    return unquote(url[len(SCHEME):]) if url.startswith(SCHEME) else ""


def colors():
    """The socket dots' colours - the node editor's own, so the legend is what is drawn there."""
    try:
        from .ui.node_editor import SOCKET_COLORS
        return SOCKET_COLORS
    except Exception:                                             # (no Qt: the same colours, written out)
        return FALLBACK_COLORS


def dot(kind):
    return f'<span style="color:{colors().get(kind, "#888888")}">●</span>'


# -- the pages as a tree ----------------------------------------------------------------------------
def _key(item):
    t, kind, op = item.get("type"), item.get("kind", ""), ("svg" if item.get("svg") else item.get("op", ""))
    return (t, kind if t in (ng.SOURCE,) else "", op)


def node_key(node):
    return "special:%s|%s|%s" % _key(node)


def categories():
    """[(menu label, [entries])] of the Add menu; an entry is ("node", ref or special key, name) or ("sub", label) for a nested menu's heading."""
    known = set(fx.builtin_refs())
    out = []

    def walk(items, entries, sub=None):
        for it in items:
            if it == nodemenu.SEP:
                continue
            if it == nodemenu.SHAPES:
                entries.append(("node", "shapes", "形狀"))
            elif isinstance(it, str):
                if nodemenu.ref_of(it) in known:
                    entries.append(("node", nodemenu.ref_of(it), ng.short_name(fx.get(nodemenu.ref_of(it)).name)))
            elif it[0] == "node":
                entries.append(("node", node_key(it[2]), it[1]))
            else:
                entries.append(("sub", it[1]))
                walk(it[2], entries, it[1])
    for it in nodemenu.ROOT + nodemenu.AFTER:
        if not isinstance(it, str) and it[0] == "menu":
            entries = []
            walk(it[2], entries)
            out.append((it[1], entries))
    return out


def effect_categories():
    """[(category, [(ref, name)])] of the built-in filters the Add menu has no place for."""
    placed = nodemenu.placed()
    cats = {}
    for ref in sorted(fx.builtin_refs()):
        if ref not in placed and ref != ng.PICTURE:
            d = fx.get(ref)
            cats.setdefault(d.category or "其他", []).append((ref, ng.short_name(d.name)))
    return sorted(cats.items())


def tree():
    """[(page id, title, [children])] for the list at the left of the window."""
    nodes = [("cat:" + label, label, [("node:" + e[1], e[2], []) for e in entries if e[0] == "node"])
             for label, entries in categories()]
    effects = [("fxcat:" + cat, cat, [("node:" + ref, name, []) for ref, name in items]) for cat, items in effect_categories()]
    return [("home", "首頁", []), ("types", "資料類型", []), ("nodes", "節點", nodes), ("fx", "KiaseCut 效果", effects), ("format", "濾鏡寫法", [])]


# -- the pages ---------------------------------------------------------------------------------------
def esc(text):
    return html.escape(str(text))


def _default(p):
    v = p.default
    if p.type == "color" and isinstance(v, (list, tuple)):
        return "#" + "".join("%02x" % round(max(0, min(1, c)) * 255) for c in v[:3])
    if p.type == "bool":
        return "開" if v else "關"
    if p.type in ("curve", "gradient"):
        return "—"
    if isinstance(v, (list, tuple)):
        return ", ".join(("%g" % c) for c in v)
    if isinstance(v, float):
        return "%g" % v
    return str(v)


def _range(p):
    if p.type in ("float", "int", "vec2", "vec3"):
        return "%g ～ %g" % (p.lo, p.hi)
    if p.type == "menu":
        return "、".join(p.items)
    return ""


def params_table(d):
    rows = []
    for p in d.params:
        name, sock = PARAM_TYPES.get(p.type, (p.type, None))
        where = f"<br><small>（面板：{esc(p.panel)}）</small>" if p.panel else ""
        rows.append(f"<tr><td>{dot(sock) if sock else ''} {esc(p.label)}{where}</td><td>{esc(name)}</td><td>{esc(_default(p))}</td><td>{esc(_range(p))}</td></tr>")
    if not rows:
        return "<p>（沒有參數）</p>"
    return ('<table border="1" cellspacing="0" cellpadding="4"><tr><th>參數</th><th>種類</th><th>預設</th><th>範圍／選項</th></tr>'
            + "".join(rows) + "</table>")


def sockets_table(d):
    rows = [f"<tr><td>輸入</td><td>{dot(d.socket_type('in', 'src'))} {esc(d.src_label)}</td></tr>"]
    for name, label in d.inputs:
        rows.append(f"<tr><td>輸入</td><td>{dot(d.socket_type('in', name))} {esc(label)}</td></tr>")
    for name, label in (d.outputs or [("", d.out_label)]):
        rows.append(f"<tr><td>輸出</td><td>{dot(d.socket_type('out', name))} {esc(label)}</td></tr>")
    return '<table border="1" cellspacing="0" cellpadding="4"><tr><th></th><th>插槽</th></tr>' + "".join(rows) + "</table>"


def filter_page(ref):
    d = fx.get(ref)
    name = ng.short_name(d.name)
    where = "Blender 合成器的節點" if ref.startswith("builtin:nodes/") or ref.startswith("builtin:blender_") else "KiaseCut 的效果"
    desc = esc(d.description).replace("\n", "<br>")
    return (f"<h1>{esc(name)}</h1><p><small>{where}"
            + (f" ・ 類別：{esc(d.category)}" if d.category else "") + f" ・ <code>{esc(ref)}</code></small></p>"
            f"<p>{desc or '（沒有說明）'}</p><h3>插槽</h3>{sockets_table(d)}<h3>參數</h3>{params_table(d)}")


def special_page(key):
    t, kind, op = key[len("special:"):].split("|")
    label = next((e[2] for _, entries in categories() for e in entries if e[0] == "node" and e[1] == key), kind or t)
    out = {ng.FONT: "font", ng.STRING: "string"}.get(t, "outline" if t == ng.SOURCE and (kind in ("vector", "text") or op == "svg") else "image")
    ins = ""
    if t == ng.SOURCE and kind == "vector":
        ins = "<p>輸入：矢量輪廓（%s）</p>" % dot("outline")
    return (f"<h1>{esc(label)}</h1><p>{esc(SPECIAL.get((t, kind, op), ''))}</p>{ins}"
            f"<p>輸出：{dot(out)} {esc(dict((k, n) for k, n, _ in TYPES).get(out, out))}"
            + ("（也可以當圖片用）" if out == "outline" else "") + "</p>")


def shapes_page():
    rows = [f"<li>{esc(a.name)}</li>" for a in assets.ASSETS if a.cat == "shape"]
    return ("<h1>形狀</h1><p>內建的形狀來源，填充和外框都可以設定，也能換成圖片。輸出圖片，也能當矢量輪廓接進矢量節點。</p><ul>"
            + "".join(rows) + "</ul>")


def node_page(key):
    if key == "shapes":
        return shapes_page()
    if key.startswith("special:"):
        return special_page(key)
    return filter_page(key)


def legend_row():
    """The dots in a row, each with its name below."""
    cells = "".join(f'<td align="center" width="70"><span style="font-size:22px">{dot(k)}</span><br><small>{esc(n.split("（")[0])}</small></td>'
                    for k, n, _ in TYPES)
    return f'<table cellspacing="0" cellpadding="4"><tr>{cells}</tr></table><br>'


def types_page():
    rows = "".join(f"<tr><td>{dot(k)}</td><td>{esc(name)}</td><td>{esc(text)}</td></tr>" for k, name, text in TYPES)
    return ("<h1>資料類型</h1><p>節點插槽上的點，顏色是資料類型。每條連線帶的其實都是一張圖片，數字、顏色、遮罩都是圖片的不同解讀；"
            "字串、字體和矢量輪廓不是圖片，只接特定的節點。</p>"
            + legend_row() +
            '<table border="1" cellspacing="0" cellpadding="4"><tr><th></th><th>類型</th><th>是什麼</th></tr>' + rows + "</table>"
            "<h3>點的形狀</h3><ul><li>● 圓點：整張圖一個值</li><li>◆ 菱形：每個像素各一個值（場）</li><li>◈ 菱形帶點：兩種都可以</li></ul>")


def category_page(label):
    for lab, entries in categories():
        if lab == label:
            body = ""
            for kind, key, *rest in entries:
                if kind == "sub":
                    body += f"<h3>{esc(key)}</h3>"
                else:
                    name = rest[0]
                    body += f"<p>{link('node:' + key, name)}<br><small>{esc(_summary(key))}</small></p>"
            return f"<h1>{esc(label)}</h1>{body}"
    return ""


def _summary(key):
    if key == "shapes":
        return "內建的形狀"
    if key.startswith("special:"):
        t, kind, op = key[len("special:"):].split("|")
        return SPECIAL.get((t, kind, op), "")
    text = fx.get(key).description.replace("節點用：", "")
    return text if len(text) < 90 else text[:88] + "…"


def effects_page(cat=None):
    if cat is None:
        return "<h1>KiaseCut 效果</h1><p>Blender 沒有的效果。它們都能在節點編輯器的「KiaseCut 效果」選單加成節點。</p>" + "".join(
            f"<p>{link('fxcat:' + c, c)}（{len(items)}）</p>" for c, items in effect_categories())
    items = dict(effect_categories()).get(cat, [])
    return f"<h1>{esc(cat)}</h1>" + "".join(f"<p>{link('node:' + ref, name)}<br><small>{esc(_summary(ref))}</small></p>" for ref, name in items)


def format_page():
    try:
        with open(fx.DOC_PATH, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        return f"找不到說明文件：{exc}"


def render(page):
    """(kind, text) of a page: ("html", ...) or ("markdown", ...)."""
    if page == "format":
        return "markdown", format_page()
    if page == "home" or not page:
        return "html", HOME
    if page == "types":
        return "html", types_page()
    if page == "nodes":
        return "html", "<h1>節點</h1><p>照 Blender 5.2 合成器 Add 選單的順序。</p>" + "".join(
            f"<p>{link('cat:' + lab, lab)}（{sum(1 for k, *_ in entries if k == 'node')}）</p>" for lab, entries in categories())
    if page == "fx":
        return "html", effects_page()
    kind, _, rest = page.partition(":")
    if kind == "cat":
        return "html", category_page(rest)
    if kind == "fxcat":
        return "html", effects_page(rest)
    if kind == "node":
        return "html", node_page(rest)
    return "html", HOME


def search(text, limit=60):
    """[(page id, title, what matched)] of the nodes whose name, description or parameter names hold `text`."""
    text = text.strip().lower()
    if not text:
        return []
    found = []
    for lab, entries in categories():
        for kind, key, *rest in entries:
            if kind == "node":
                found.append((key, rest[0], lab))
    for cat, items in effect_categories():
        found += [(ref, name, "KiaseCut 效果 ▸ " + cat) for ref, name in items]
    out = []
    for key, name, where in found:
        hay = [name, key]
        if key.startswith("special:") or key == "shapes":
            hay.append(_summary(key))
        else:
            d = fx.get(key)
            hay += [d.description] + [p.label for p in d.params] + [lbl for _, lbl in d.inputs]
        hit = next((h for h in hay if text in h.lower()), None)
        if hit is not None:
            out.append(("node:" + key, f"{name}　（{where}）", hit if hit != name else ""))
            if len(out) >= limit:
                break
    return out
