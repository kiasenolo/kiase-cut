"""Questions with 不再詢問: each yes / no question the program asks has a key; ticking 不再詢問
remembers the answer given then (QSettings ask/<key>: "yes" or "no") and the question is not
asked again. 設定 > 詢問 resets them all or sets each (每次詢問 / 一律「是」 / 一律「否」).
Questions whose wrong remembered answer would lose work for good (unsaved changes, deleting
for ever) are not here: they are always asked."""
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QMessageBox

SETTINGS = ("KiaseCut", "KiaseCut")              # (MainWindow.SETTINGS)
QUESTIONS = {                                    # key: what it asks, as the settings list it
    "delete_timeline": "刪除時間線（和上面的片段）",
    "overwrite_project": "另存新檔時覆蓋同名的專案檔",
    "collect_media": "把專案資料夾外的素材複製進 Media",
    "delete_compound": "刪除複合片段（和使用它的片段）",
    "unmake_component": "轉回複合片段時清掉片段自己設定的參數",
    "delete_param": "刪除元件參數時清掉片段自己設定的值",
    "delete_tracks": "刪除有片段的軌道",
    "delete_media": "刪除專案素材（移到資源回收筒）",
    "clear_cache": "清除專案緩存",
    "delete_library": "刪除 Library 的項目（移到資源回收筒）",
    "overwrite_layout": "另存新佈局時覆寫同名的佈局",
    "delete_layout": "刪除佈局",
    "delete_project": "專案管理器：把專案或資料夾移到資源回收筒",
    "remove_thumbnail": "專案管理器：拿掉由 _thumbnail 畫的縮圖",
    "reset_bpm": "重置 BPM 對齊",
    "speed_keys": "變速曲線：換掉方式時清掉它的點",
    "variable_kind": "文字變數：換類型時清掉它的關鍵幀",
}
ANSWERS = (("", "每次詢問"), ("yes", "一律「是」"), ("no", "一律「否」"))


def remembered(key):
    """"yes", "no" or "" (ask)."""
    v = QSettings(*SETTINGS).value("ask/" + key, "")
    return v if v in ("yes", "no") else ""


def remember(key, answer):
    s = QSettings(*SETTINGS)
    if answer in ("yes", "no"):
        s.setValue("ask/" + key, answer)
    else:
        s.remove("ask/" + key)


def reset():
    """Ask every question again."""
    s = QSettings(*SETTINGS)
    s.remove("ask")


def question(parent, key, title, text):
    """Yes (True) or no, asked unless 不再詢問 was ticked for key before."""
    v = remembered(key)
    if v:
        return v == "yes"
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No, parent)
    box.setDefaultButton(QMessageBox.Yes)
    again = QCheckBox("不再詢問（記住這次的選擇，可在 設定 > 詢問 改回來）")
    box.setCheckBox(again)
    yes = box.exec() == QMessageBox.Yes
    if again.isChecked():
        remember(key, "yes" if yes else "no")
    return yes
