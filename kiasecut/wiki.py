"""說明 Wiki: the pages of the help window, made from what the program knows about itself - the node menu's layout (nodemenu.py), every
filter's header (name, description, sockets, parameters: fx.py) and the 濾鏡寫法 document. A page is an id and some HTML for a
QTextBrowser (ui/wiki_window.py shows them); nothing here needs Qt, so it is tested and can be exported alone.

Page ids: "home", "types" (the data types and their socket dots), "nodes" and "cat:<menu>" (a menu of the node editor's Add menu),
"node:<ref or key>" (one node), "fx" and "fxcat:<category>" (KiaseCut's own effects, which are nodes too), "format" (濾鏡寫法)."""
import glob
import html
import os
import re
from urllib.parse import quote, unquote

from . import assets, fx, nodegraph as ng, nodemenu, wikidata, wikidemo

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
    (ng.SOURCE, "vector", "rasterize"): "把一個矢量畫成圖片（柵格化）：給出的是一般的圖像，可以接濾鏡，不能再接回矢量節點；解析度調低會變成低解析度的圖。",
    (ng.FONT, "", ""): "字體常數：一個字體檔。不是圖片，只能接到文字節點的字體。",
    (ng.STRING, "", ""): "字串常數：一段文字。不是圖片，只能接到文字節點的內容。",
    (ng.VIEWER, "", ""): "編輯器的預覽看這個節點的結果。不會被匯出。",
    (ng.REROUTE, "", ""): "繞線點：連線的一個彎，圖片原樣通過。用來整理線路。",
    (ng.FRAME, "", ""): "框架／註解：圈起一群節點並寫上說明，不影響結果。",
}
HOME = """<h1>KiaseCut 說明</h1>
<p>這裡的頁面大多是從程式自己的資料產生的：節點的說明、插槽、參數都和你現在用的版本一致。</p>
<ul>
<li><a href="wiki:guide%3Aoverview">認識 KiaseCut</a>：第一次用，先看這篇</li>
<li><a href="wiki:sec%3Aedit">剪輯</a>：專案與素材、時間線、預覽與屬性、複合片段</li>
<li><a href="wiki:sec%3Afx">效果</a>：加效果、關鍵幀、效果清單、自己寫濾鏡</li>
<li><a href="wiki:sec%3Anodes">節點</a>：節點是什麼、做第一個節點效果、編輯器操作，以及資料類型、連線規則和每個節點的說明</li>
</ul>
<p>左邊的搜尋欄可以找節點、參數和說明。</p>"""


def link(page, text):
    return f'<a href="{SCHEME}{quote(page, safe=":")}">{html.escape(text)}</a>'


LINK = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")


def expand(text):
    """[[page|text]] of the guides as links; [[node:blur|..]] is the page of builtin:blur."""
    def one(m):
        page = m.group(1)
        if page.startswith("node:") and not page.startswith(("node:builtin:", "node:special:")):
            page = "node:builtin:" + page[len("node:"):]
        return link(page, m.group(2))
    return LINK.sub(one, text)


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


def dot(kind, shape="single", size=14):
    """A socket dot as an image: "socket:<colour>:<shape>" (ui/wiki_window.py draws it as the node editor draws its sockets: "single" is
    a circle, "field" a diamond, "either" a diamond with a dot)."""
    return (f'<img src="socket:{colors().get(kind, "#888888").lstrip("#")}:{shape}" width="{size}" height="{size}" '
            'style="vertical-align: middle">')


# -- the pages as a tree ----------------------------------------------------------------------------
def _key(item):
    t, kind, op = item.get("type"), item.get("kind", ""), ("svg" if item.get("svg") else item.get("op", ""))
    return (t, kind if t in (ng.SOURCE,) else "", op)


def node_key(node):
    return "special:%s|%s|%s" % _key(node)


def node_refs():
    """Refs of the filters made for graphs (filters/nodes/*.glsl): fx.builtin_refs() has not got them, as the node editor's own list."""
    refs = ["builtin:nodes/" + os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(fx.PKG, "nodes", "*.glsl"))]
    return sorted(r for r in refs if r != ng.PICTURE)


def known_refs():
    return set(fx.builtin_refs()) | set(node_refs())


def categories():
    """[(menu label, [entries])] of the Add menu; an entry is ("node", ref or special key, name) or ("sub", label) for a nested menu's heading."""
    known = known_refs()
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
    for ref in sorted(known_refs()):
        if ref not in placed and ref != ng.PICTURE:
            d = fx.get(ref)
            cats.setdefault(d.category or "其他", []).append((ref, ng.short_name(d.name)))
    return sorted(cats.items())


def tree():
    """[(page id, title, [children])] for the list at the left of the window."""
    nodes = [("cat:" + label, label, [("node:" + e[1], e[2], []) for e in entries if e[0] == "node"])
             for label, entries in categories()]
    effects = [("fxcat:" + cat, cat, [("node:" + ref, name, []) for ref, name in items]) for cat, items in effect_categories()]
    special = {"nodes": ("節點目錄", nodes), "fx": ("效果清單", effects), "format": ("濾鏡寫法", []), "types": ("資料類型", []), "rules": ("連線規則", [])}
    out = [("home", "首頁", []), ("guide:overview", wikidata.GUIDES["guide:overview"][0], [])]
    for sec, (title, _, pages) in wikidata.SECTIONS.items():
        kids = []
        for pid in pages:
            name, children = special[pid] if pid in special else (wikidata.GUIDES[pid][0], [])
            kids.append((pid, name, children))
        out.append((sec, title, kids))
    return out


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


ACCEPTS = {"image": "任何圖片（顏色、影片、遮罩都行）", "float": "數值：圖讀成明度，逐像素各讀自己那一點", "color": "顏色：一張圖，或顏色常數",
           "vector": "向量：圖的紅、綠、藍當 X、Y、Z", "int": "整數", "bool": "開關", "menu": "選單的編號"}
LINKABLE = (("逐像素（圖讀成明度或顏色）", ("color", "float")), ("單一值（只讀圖的中心一點）", ("bool", "int", "menu")),
            ("向量（讀圖中心的 R、G、B）", ("vec2", "vec3")))


def wiring(d):
    """怎麼接: the sockets of a filter, what each takes, and which parameters take a link too - from the filter's header."""
    inputs = [("src", d.src_label)] + list(d.inputs)
    by_param = {n: pn for n, pn in d.input_param.items()}
    labels = {p.name: p.label for p in d.params}
    rows = []
    for name, label in inputs:
        kind = d.socket_type("in", name)
        notes = [ACCEPTS.get(kind, "")]
        if name in by_param:
            notes.append(f"沒接線就用欄位「{labels.get(by_param[name], by_param[name])}」")
        if name in d.input_use:
            notes.append("沒被選到時這條線不運算")
        rows.append(f"<tr><td>輸入</td><td>{dot(kind)} {esc(label)}</td><td>{esc('；'.join(n for n in notes if n))}</td></tr>")
    for name, label in (d.outputs or [("", d.out_label)]):
        kind = d.socket_type("out", name)
        rows.append(f"<tr><td>輸出</td><td>{dot(kind)} {esc(label)}</td><td>{esc(ACCEPTS.get(kind, '')) if kind != 'image' else '一張圖片'}</td></tr>")
    out = ('<table border="1" cellspacing="0" cellpadding="4"><tr><th></th><th>插槽</th><th>接什麼</th></tr>' + "".join(rows) + "</table>")
    if len(d.outputs) > 1:
        out += "<p><small>每個輸出可以分別拉線；只有被接出去的輸出才會被運算。</small></p>"
    extra = []
    for title, types in LINKABLE:
        names = [p.label for p in d.params if p.type in types and p.name not in by_param.values()]
        if names:
            extra.append(f"<li><b>{title}</b>：{esc('、'.join(names))}</li>")
    if extra:
        out += "<p>參數欄位也有自己的插槽，可以接線（接上後欄位由線決定）：</p><ul>" + "".join(extra) + "</ul>"
    return out


def recipes(key, name):
    """用法 and 接法範例 of a page from wikidata.USAGE (html; "" if it has none)."""
    got = wikidata.USAGE.get(key.replace("builtin:", "", 1))
    if not got:
        return ""
    how, chains = got
    out = f"<h3>怎麼用</h3><p>{esc(how)}</p>"
    if chains:
        out += "<h3>接法範例</h3><ul>" + "".join(f"<li>{esc(c).replace('＊', '<b>' + esc(name) + '</b>')}</li>" for c in chains) + "</ul>"
    return out + f'<p><small>連線的通則見{link("rules", "連線規則")}。</small></p>'


SHOW_W, ARROW_W, ROW_W = 156, 28, 660          # (what was given, an arrow, three results: one row)


def demo(ref):
    """示範: the node run on a sample picture - the pictures it was given, an arrow, then what it made (the pictures wikidemo drew)."""
    tiles = wikidemo.index().get(wikidemo.slug(ref))
    if not tiles:
        return ""
    cells, width = [], 0
    rows = []
    arrow_at = next((i for i, (_c, kind) in enumerate(tiles) if kind == "out"), 0) if any(k == "in" for _c, k in tiles) else -1
    for i, (caption, _kind) in enumerate(tiles):
        parts = []
        if i == arrow_at and i > 0:
            parts.append(("arrow", ARROW_W))
        parts.append((i, SHOW_W))
        need = sum(w for _, w in parts)
        if cells and width + need > ROW_W:
            rows.append(cells)
            cells, width = [], 0
        for item, w in parts:
            cells.append((item, w, tiles[item][0] if item != "arrow" else ""))
            width += w
    rows.append(cells)
    slug = wikidemo.slug(ref)
    out = ""
    for row in rows:
        out += '<table cellspacing="0" cellpadding="3"><tr>'
        for item, w, caption in row:
            if item == "arrow":
                out += f'<td width="{w}" align="center" valign="middle"><img src="demo:_arrow" width="22" height="22"></td>'
            else:
                out += f'<td width="{w}" align="center"><img src="demo:{slug}/{item}" width="{w - 6}"><br><small>{esc(caption)}</small></td>'
        out += "</tr></table>"
    return "<h3>示範</h3>" + out


def filter_page(ref):
    d = fx.get(ref)
    name = ng.short_name(d.name)
    where = "Blender 合成器的節點" if ref.startswith("builtin:nodes/") or ref.startswith("builtin:blender_") else "KiaseCut 的效果"
    desc = esc(d.description).replace("\n", "<br>")
    return (f"<h1>{esc(name)}</h1><p><small>{where}"
            + (f" ・ 類別：{esc(d.category)}" if d.category else "") + f" ・ <code>{esc(ref)}</code></small></p>"
            f"<p>{desc or '（沒有說明）'}</p>{demo(ref)}{recipes(ref, name)}<h3>怎麼接</h3>{wiring(d)}<h3>參數</h3>{params_table(d)}")


def special_page(key):
    t, kind, op = key[len("special:"):].split("|")
    label = next((e[2] for _, entries in categories() for e in entries if e[0] == "node" and e[1] == key), kind or t)
    out = {ng.FONT: "font", ng.STRING: "string"}.get(t, "outline" if t == ng.SOURCE and ((kind == "vector" and op != "rasterize") or kind == "text" or op == "svg") else "image")
    ins = ""
    if t == ng.SOURCE and kind == "vector":
        ins = "<p>輸入：矢量輪廓（%s）</p>" % dot("outline")
    return (f"<h1>{esc(label)}</h1><p>{esc(SPECIAL.get((t, kind, op), ''))}</p>{ins}"
            f"<p>輸出：{dot(out)} {esc(dict((k, n) for k, n, _ in TYPES).get(out, out))}"
            + ("（也可以當圖片用）" if out == "outline" else "") + f"</p>{recipes(key, label)}")


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
    cells = "".join(f'<td align="center" width="70">{dot(k, size=24)}<br><small>{esc(n.split("（")[0])}</small></td>'
                    for k, n, _ in TYPES)
    return f'<table cellspacing="0" cellpadding="4"><tr>{cells}</tr></table><br>'


def page_title(pid):
    return {"nodes": "節點目錄", "fx": "效果清單", "format": "濾鏡寫法", "types": "資料類型", "rules": "連線規則"}.get(pid) or wikidata.GUIDES[pid][0]


def section_page(sec):
    title, intro, pages = wikidata.SECTIONS[sec]
    return f"<h1>{esc(title)}</h1><p>{esc(intro)}</p><ol>" + "".join(f"<li>{link(pid, page_title(pid))}</li>" for pid in pages) + "</ol>"


def shapes_row():
    """The three shapes of a socket, drawn, each with what it means."""
    cells = "".join(f'<td align="center" width="170">{dot("float", shape, 28)}<br><b>{esc(n)}</b><br><small>{esc(t)}</small></td>'
                    for shape, n, t in (("single", "圓點", "整張圖一個值"), ("field", "菱形", "每個像素各一個值（場）"),
                                        ("either", "菱形帶點", "兩種都可以")))
    return f'<table cellspacing="0" cellpadding="4"><tr>{cells}</tr></table>'


def types_page():
    rows = "".join(f"<tr><td>{dot(k)}</td><td>{esc(name)}</td><td>{esc(text)}</td></tr>" for k, name, text in TYPES)
    return ("<h1>資料類型</h1><p>節點插槽上的點，顏色是資料類型。每條連線帶的其實都是一張圖片，數字、顏色、遮罩都是圖片的不同解讀；"
            "字串、字體和矢量輪廓不是圖片，只接特定的節點。</p>"
            + legend_row() + "<h3>點的形狀</h3>" + shapes_row() + "<h3>類型</h3>" +
            '<table border="1" cellspacing="0" cellpadding="4"><tr><th></th><th>類型</th><th>是什麼</th></tr>' + rows + "</table>")


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
        return "<h1>效果清單</h1><p>KiaseCut 自己的效果（Blender 的合成器沒有的），依類別列出。它們也都能在節點編輯器的「KiaseCut 效果」選單加成節點。</p>" + "".join(
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
    if page in wikidata.SECTIONS:
        return "html", section_page(page)
    if page in wikidata.GUIDES:
        return "html", expand(wikidata.GUIDES[page][1])
    if page == "types":
        return "html", types_page()
    if page == "rules":
        return "html", expand(wikidata.RULES)
    if page == "nodes":
        return "html", "<h1>節點目錄</h1><p>每個節點的用法、接法、插槽和參數，照 Blender 5.2 合成器 Add 選單的順序。</p>" + "".join(
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
    for pid, (title, body) in wikidata.GUIDES.items():
        plain = re.sub(r"<[^>]+>", "", body)
        if text in title.lower() or text in plain.lower():
            out.append((pid, f"{title}　（入門）", ""))
    for key, name, where in found:
        hay = [name, key]
        if key.startswith("special:") or key == "shapes":
            hay.append(_summary(key))
        else:
            d = fx.get(key)
            hay += [d.description] + [p.label for p in d.params] + [lbl for _, lbl in d.inputs] + list(wikidata.USAGE.get(key.replace("builtin:", "", 1), ("", ()))[:1])
        hit = next((h for h in hay if text in h.lower()), None)
        if hit is not None:
            out.append(("node:" + key, f"{name}　（{where}）", hit if hit != name else ""))
            if len(out) >= limit:
                break
    return out
