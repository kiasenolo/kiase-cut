"""Letter keys on menu items, as in Windows' menus: 刪除(E), 上移(U), 下移(D), 重新命名(R) ... -
pressed while the menu is open they pick the item. One table for every menu (right-click and
menu bar alike); in a menu each letter is used once, the table's earlier words getting theirs
first (a later one takes its next letter; with all of its own taken, any one left). Items not in the table (names of filters,
groups, projects) get none."""
from PySide6.QtWidgets import QMenu

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

KEYS = [                       # (word in the label, its letters in order of preference)
    # the menu bar's (words the right-click menus do not have; before the shorter ones below)
    ("專案管理器", "M"), ("新專案", "N"), ("開啟專案…", "O"), ("最近", "R"), ("儲存專案", "S"),
    ("另存新檔", "A"), ("專案資訊", "V"), ("縮圖", "H"), ("整理素材", "G"), ("緩存", "L"),
    ("設定…", "P"), ("匯入剪映", "J"), ("匯入素材", "I"), ("匯出目前", "X"), ("匯出", "E"),
    ("復原", "Z"), ("重做", "Y"), ("移到上面", "K"), ("移到下面", "J"), ("字體", "O"),
    ("自訂濾鏡", "N"), ("檢查", "K"), ("儲存目前", "V"), ("下一個佈局", "N"),
    ("上一個佈局", "P"), ("入點", "I"), ("出點", "O"), ("清除標記", "X"), ("取消選區", "N"),
    ("吸附", "S"), ("上一個剪輯點", "U"), ("下一個剪輯點", "D"), ("後退", "B"), ("前進", "G"),
    ("上一個關鍵幀", "J"), ("下一個關鍵幀", "K"), ("放大", "M"), ("縮小", "Z"), ("適合", "T"),
    ("全螢幕", "F"), ("返回上一層", "E"),
    ("刪除", "E"), ("上移", "U"), ("下移", "D"), ("重新命名", "R"),
    ("複製", "C"), ("剪下", "T"), ("貼上", "P"),
    ("編輯器開啟", "OE"), ("進入編輯", "I"), ("編輯", "I"),
    ("獨立副本", "NQ"), ("設為獨立", "J"), ("副本", "D"),
    ("全選", "A"), ("取消選", "N"), ("套用", "YP"), ("選取", "S"),
    ("分割", "S"), ("向左裁剪", "Q"), ("向右裁剪", "W"), ("對齊拍子", "B"), ("打亂", "H"),
    ("分離音訊", "A"), ("在新的分頁", "BW"), ("關閉", "W"),
    ("解散群組", "U"), ("摺疊群組", "F"), ("展開群組", "F"), ("建立群組", "G"), ("移入群組", "GM"),
    ("預設值", "F"), ("預設顏色", "FN"), ("顏色", "OC"),
    ("反轉遮罩", "V"), ("遮罩", "K"), ("隱藏", "H"), ("鎖定", "L"),
    ("全部解除", "A"), ("解除", "NX"), ("清除", "L"),
    ("轉回", "KB"), ("轉為元件", "M"), ("靜態元件", "YZ"), ("靜態", "SL"),
    ("建立元件", "MZ"), ("新增元件", "MN"), ("複合片段", "XO"), ("設為參數", "AMZ"),
    ("軌道音量", "V"), ("新增影片軌道", "IV"), ("新增文字軌道", "X"), ("新增音訊軌道", "A"),
    ("新增時間線", "T"), ("新增資料夾", "N"), ("新資料夾", "N"), ("新增專案", "P"), ("新專案", "N"),
    ("加到播放頭", "A"), ("在播放頭加入", "A"), ("放到播放頭", "A"), ("濾鏡片段", "AF"),
    ("新增文字", "T"), ("說明", "H"),
    ("在檔案總管", "X"), ("移到資料夾", "M"), ("資料夾", "F"), ("開啟", "O"),
    ("存到 Library", "L"), ("拿掉縮圖", "H"),
    ("重設", "S"), ("覆寫", "W"), ("另存", "A"), ("匯入", "I"),
    ("佈局", "L"),                # (the 佈局 submenu: after every other word with 佈局)
]


def letters(text):
    """The letters for an item labelled text ("" when it has none)."""
    return next((keys for word, keys in KEYS if word in text), "")


def with_key(text, key):
    """text with key as its letter: 重新命名(&R)… (before a trailing …)."""
    tail = "…" if text.endswith("…") else ""
    return f"{text[:len(text) - len(tail)]}(&{key}){tail}"


def apply(menu):
    """Give the items of menu (and of its submenus, when they open) their letters."""
    used, items = set(), []
    for a in menu.actions():
        text = a.text()
        if a.isSeparator() or not text or "&" in text:
            used |= {text[text.index("&") + 1].upper()} if "&" in text[:-1] else set()
            continue
        if a.menu() is not None:
            keyed(a.menu())
        keys = letters(text)
        if keys:
            items.append((next(i for i, (word, _k) in enumerate(KEYS) if word in text), a, keys))
    left = []
    for _rank, a, keys in sorted(items, key=lambda x: x[0]):
        key = next((k for k in keys if k not in used), None)
        if key is None:
            left.append(a)
        else:
            used.add(key)
            a.setText(with_key(a.text(), key))
    for a in left:                                       # (their own letters taken: any one left)
        key = next((k for k in ALPHABET if k not in used), None)
        if key is not None:
            used.add(key)
            a.setText(with_key(a.text(), key))


def keyed(menu):
    """menu, its letters given each time it opens (its items may change in between)."""
    if not menu.property("menukeys"):
        menu.setProperty("menukeys", True)
        menu.aboutToShow.connect(lambda: apply(menu))
    return menu


def Menu(parent=None):
    """A QMenu whose items get their letters."""
    return keyed(QMenu(parent))
