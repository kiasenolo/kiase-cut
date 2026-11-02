"""The program's look, the same on every platform.

It was made under KDE (the Breeze style and a dark colour scheme), and parts the style sheet
did not cover came from them; elsewhere those parts took the platform's own style and colours
(on Windows the effects' boxes got white borders). So the style is always Fusion, the colours
are always KDE's as they were (but the accent colour is the system's, read as the program starts:
Windows' too), the style sheet covers every kind of widget the program uses the
way Breeze drew it, and the standard icons are Breeze Dark's (kiasecut/look/icons).
"""
import os
import re

from PySide6.QtCore import QByteArray, QMargins, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractScrollArea, QComboBox, QFrame, QMenu, QStyle, QStyleOptionMenuItem, QStyleOptionProgressBar

from . import wheel

FILES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "look").replace("\\", "/")
FRAME = "#404042"         # Breeze's frame around scroll areas, spin boxes and tool buttons
ACCENT = "#5b4731"        # the system's accent colour (apply reads it; this is KDE's as it was):
                          # a hovered tool button's frame, a radio button, a progress bar, selections
ARROW = f"{FILES}/arrow"  # its chevrons: arrow-down.svg, arrow-up.svg ...

# DaVinci Resolve-like: charcoal panels on a near-black frame, flat controls, light grey
# text; colour is left to clips, keyframes, the playhead and the meter
STYLE = """
QWidget { background: #1c1c1e; color: #d0d0d2; font-family: 'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC', sans-serif; font-size: 12px; }
QMainWindow { background: #111113; }
QMenuBar { background: #18181a; border-bottom: 1px solid #0e0e10; }
QMenu { background: #26262a; border: 1px solid #0e0e10; }
QMenu::item { padding: 4px 25px; }
QMenu::item:selected, QMenuBar::item:selected { background: #3d3d43; }
QMenu::separator { height: 1px; background: #3a3a40; margin: 3px 6px; }
QMenu::indicator { width: 14px; height: 14px; left: 4px; }
QMenu::indicator:checked { image: url(@/check.svg); }
QMenu::right-arrow { image: url(@ARROW-right.svg); width: 14px; height: 14px; right: 4px; }
QPushButton { background: #2b2b2f; border: 1px solid #141416; border-radius: 3px; padding: 4px 10px; }
QPushButton:hover { background: #36363b; }
QPushButton:pressed { background: #1f1f22; }
QPushButton:checked { background: #c9c9cd; color: #121214; border-color: #c9c9cd; }
QPushButton:disabled { color: #5c5c62; }
QPushButton#tool { background: transparent; border: 1px solid transparent; padding: 3px; }
QPushButton#tool:hover { background: #33333a; border-color: #141416; }
QPushButton#tool:checked { background: #4a4a52; border-color: #5c5c64; }
QPushButton#tool:disabled { background: transparent; }
QToolButton { background: transparent; border: 1px solid @FRAME; border-radius: 5px; padding: 6px 8px; }
QToolButton[autoRaise="true"] { border-color: transparent; padding: 3px; }
QToolButton:hover { border-color: @ACCENT; }
QToolButton:checked, QToolButton:pressed { background: #323234; border-color: @FRAME; }
QToolButton:checked:hover { border-color: @ACCENT; }
QToolButton[popupMode="InstantPopup"] { padding-right: 22px; }
QToolButton::menu-indicator { image: url(@ARROW-down.svg); width: 14px; height: 14px; subcontrol-origin: padding; subcontrol-position: center right; right: 5px; }
QToolBar { border: none; }
QToolBar::separator { background: @FRAME; width: 1px; height: 1px; margin: 4px; }
QSplitter::handle { background: #0e0e10; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }
QDoubleSpinBox, QSpinBox, QPlainTextEdit, QLineEdit, QComboBox { background: #141416; border: 1px solid #2c2c31; border-radius: 3px; padding: 2px 5px; selection-background-color: #4a4a52; selection-color: #ffffff; }
QDoubleSpinBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus { border-color: #6a6a72; }
QDoubleSpinBox:disabled { color: #5c5c62; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; border: none; subcontrol-origin: border; }
QSpinBox { background: transparent; border-color: @FRAME; border-radius: 5px; padding: 2px 5px; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; background: transparent; subcontrol-origin: border; }
QSpinBox::up-button { subcontrol-position: top right; margin: 3px 3px 0 0; }
QSpinBox::down-button { subcontrol-position: bottom right; margin: 0 3px 3px 0; }
QSpinBox::up-arrow { image: url(@ARROW-up.svg); width: 14px; height: 14px; }
QSpinBox::down-arrow { image: url(@ARROW-down.svg); width: 14px; height: 14px; }
QComboBox { padding-right: 22px; }
QComboBox:editable { padding-left: 5px; }
QComboBox::drop-down { width: 20px; border: none; border-left: 1px solid #171719; subcontrol-origin: padding; subcontrol-position: top right; }
QComboBox::down-arrow { image: url(@ARROW-down.svg); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: #26262a; border: none; outline: none; }
QTreeWidget, QListWidget { background: #1c1c1e; border: none; alternate-background-color: #202023; }
QTreeWidget::item, QListWidget::item { padding: 2px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #3d3d43; color: #ffffff; }
QTreeView::branch:has-children:closed { image: url(@ARROW-right.svg); }
QTreeView::branch:has-children:open { image: url(@ARROW-down.svg); }
QHeaderView { background: #232326; border: none; }
QHeaderView::section { background: #232326; color: #8e8e94; border: none; border-bottom: 1px solid #0e0e10; padding: 4px; }
QLabel#time { font-family: Consolas, 'Cascadia Mono', monospace; font-size: 15px; color: #e8e8ea; }
QLabel#viewer { color: #8e8e94; }
QLabel#title { color: #8e8e94; font-weight: 600; font-size: 11px; }
QLabel#crumb { color: #d0d0d2; font-weight: 600; }
QWidget#bar { background: #232326; border-top: 1px solid #0e0e10; border-bottom: 1px solid #0e0e10; }
QTabWidget::pane { border: none; border-top: 1px solid #0e0e10; }
QWidget#docktitle { background: #18181a; border-bottom: 1px solid #0e0e10; }
QMainWindow::separator { background: #0e0e10; width: 3px; height: 3px; }
QMainWindow::separator:hover { background: #4a4a52; }
QTabBar#layouts { background: transparent; }
QTabBar#layouts::tab { padding: 3px 12px; border: none; background: transparent; }
QTabBar#layouts::tab:selected { background: #2b2b2f; color: #ffffff; border-radius: 3px; }
QTabBar { background: #18181a; }
QTabBar::tab { background: #18181a; color: #8e8e94; padding: 6px 14px; border: none; border-right: 1px solid #0e0e10; }
QTabBar::tab:selected { background: #232326; color: #ffffff; }
QTabBar::tab:hover:!selected { color: #c0c0c4; }
QTabBar#timelines::tab { padding: 4px 14px; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QTabBar#timelines::tab:selected { background: #2b2b2f; }
QTabBar QToolButton { background: #18181a; border: none; padding: 0; }
QTabBar::tear { width: 0; border: none; }
QMessageBox, QInputDialog, QColorDialog, QDialog { background: #1c1c1e; }
QMessageBox QLabel { color: #d0d0d2; background: transparent; }
QStatusBar { background: #18181a; color: #8e8e94; border-top: 1px solid #0e0e10; }
QStatusBar::item { border: none; }
QSlider:horizontal { min-height: 20px; }
QSlider:vertical { min-width: 20px; }
QSlider::groove:horizontal { height: 4px; background: #34343a; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #8e8e94; border-radius: 2px; }
QSlider::handle:horizontal { background: #d0d0d2; width: 10px; margin: -4px 0; border-radius: 5px; }
QSlider::groove:vertical { width: 4px; background: #34343a; border-radius: 2px; }
QSlider::add-page:vertical { background: #8e8e94; border-radius: 2px; }
QSlider::handle:vertical { background: #d0d0d2; height: 10px; margin: 0 -5px; border-radius: 5px; }
QScrollBar { background: #1c1c1e; width: 10px; height: 10px; }
QScrollBar::handle { background: #3a3a40; border-radius: 4px; min-height: 20px; min-width: 20px; }
QScrollBar::handle:hover { background: #4a4a52; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { width: 0; height: 0; background: none; }
QAbstractScrollArea::corner { background: transparent; border: none; }
QCheckBox::indicator { width: 12px; height: 12px; border-radius: 2px; }
QCheckBox::indicator:checked { background: #c9c9cd; border: 1px solid #c9c9cd; }
QCheckBox::indicator:unchecked { background: #141416; border: 1px solid #4a4a52; }
QCheckBox::indicator:indeterminate { background: #141416; border: 1px solid #c9c9cd; image: url(@/partial.svg); }
QRadioButton { min-height: 22px; }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 9px; border: 1px solid #3a3a3c; background: #1c1c1e; }
QRadioButton::indicator:hover { border-color: @ACCENT; }
QRadioButton::indicator:checked { border-color: @ACCENT; background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5, stop: 0 #d0d0d2, stop: 0.32 #d0d0d2, stop: 0.4 @DIM, stop: 1 @DIM); }
QGroupBox { border: 1px solid @FRAME; border-radius: 5px; margin-top: 22px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 2px 4px; }
QToolTip { background: #2b2b2f; color: #e0e0e2; border: 1px solid #0e0e10; }
QProgressDialog QLabel { background: transparent; }
""".replace("@ARROW", ARROW).replace("@FRAME", FRAME).replace("@/", FILES + "/")   # (@ACCENT, @DIM: style_sheet)

# KDE's colours as the program was made with them; the parts the style sheet leaves to the style
# (selected text, links, placeholders, frames and lines) take these
COLOURS = {
    "Window": "#111216", "WindowText": "#fcfdfd", "Base": "#111216", "AlternateBase": "#111216",
    "ToolTipBase": "#111216", "ToolTipText": "#fcfdfd", "PlaceholderText": "#f2f3f3", "Text": "#fefefe",
    "Button": "#16181d", "ButtonText": "#fefefe", "BrightText": "#ffffff", "Light": "#abaebb",
    "Midlight": "#888da2", "Mid": "#515669", "Dark": "#6f758f", "Shadow": "#888da2",
    "Highlight": ACCENT, "HighlightedText": "#ffffff", "Link": "#edbc84", "LinkVisited": "#7f8c8d",
    "Accent": ACCENT,
}
DISABLED = {
    "WindowText": "#636467", "PlaceholderText": "#606163", "Text": "#646567", "ButtonText": "#67696c",
    "Highlight": "#111216", "HighlightedText": "#636467", "Link": "#5e4e3d", "LinkVisited": "#383d40",
    "Accent": "#111216",
}


def system_accent(p):
    """The accent colour the platform's palette `p` has (Windows', macOS's, KDE's)."""
    role = getattr(QPalette.ColorRole, "Accent", None)  # (Qt 6.6 on; before it, the highlight)
    return p.color(role if role is not None else QPalette.Highlight).name()


def dim(colour, part=0.3, under="#1c1c1e"):
    """`colour` laid at `part` strength over `under`: a selection's fill."""
    a, b = QColor(colour), QColor(under)
    return QColor(*(round(y + (x - y) * part) for x, y in zip(a.getRgb()[:3], b.getRgb()[:3]))).name()


def style_sheet():
    return STYLE.replace("@ACCENT", ACCENT).replace("@DIM", dim(ACCENT))


def palette():
    p = QPalette()
    for name, colour in COLOURS.items():
        role = getattr(QPalette.ColorRole, name, None)
        if role is not None:                          # (Accent: Qt 6.6 on)
            p.setColor(role, QColor(ACCENT if name in ("Highlight", "Accent") else colour))
            if name in DISABLED:
                p.setColor(QPalette.Disabled, role, QColor(DISABLED[name]))
    return p


# QStyle's standard icons -> Breeze Dark's names for them
ICONS = {
    QStyle.SP_DirIcon: "folder", QStyle.SP_DirOpenIcon: "folder", QStyle.SP_DirClosedIcon: "folder",
    QStyle.SP_FileIcon: "text-plain", QStyle.SP_MediaVolume: "audio-volume-medium",
    QStyle.SP_MediaPlay: "media-playback-start",
    QStyle.SP_DialogOkButton: "dialog-ok", QStyle.SP_DialogCancelButton: "dialog-cancel",
    QStyle.SP_DialogApplyButton: "dialog-ok-apply", QStyle.SP_DialogSaveButton: "document-save",
    QStyle.SP_DialogDiscardButton: "edit-delete", QStyle.SP_DialogCloseButton: "dialog-close",
    QStyle.SP_DialogYesButton: "dialog-ok-apply", QStyle.SP_DialogNoButton: "dialog-cancel",
    QStyle.SP_DialogResetButton: "edit-undo", QStyle.SP_DialogHelpButton: "help-contents",
    QStyle.SP_DialogOpenButton: "document-open", QStyle.SP_DialogAbortButton: "dialog-cancel",
    QStyle.SP_DialogRetryButton: "view-refresh", QStyle.SP_DialogIgnoreButton: "dialog-cancel",
    QStyle.SP_DialogYesToAllButton: "dialog-ok", QStyle.SP_DialogNoToAllButton: "dialog-cancel",
    QStyle.SP_DialogSaveAllButton: "document-save-all", QStyle.SP_RestoreDefaultsButton: "document-revert",
    QStyle.SP_MessageBoxInformation: "dialog-information", QStyle.SP_MessageBoxWarning: "dialog-warning",
    QStyle.SP_MessageBoxCritical: "dialog-error", QStyle.SP_MessageBoxQuestion: "dialog-question",
}
_icons = {}

# Breeze's sizes where Fusion's differ (the style sheet sets most others)
S = QStyle
METRICS = {
    S.PM_CheckBoxLabelSpacing: 4, S.PM_RadioButtonLabelSpacing: 4, S.PM_MenuHMargin: 4, S.PM_MenuVMargin: 4,
    S.PM_MenuBarItemSpacing: 0, S.PM_SubMenuOverlap: 0, S.PM_MenuButtonIndicator: 20, S.PM_MessageBoxIconSize: 64,
    S.PM_ListViewIconSize: 16, S.PM_HeaderMargin: 6, S.PM_HeaderMarkSize: 10, S.PM_ToolTipLabelFrameWidth: 3,
    S.PM_ToolBarFrameWidth: 0, S.PM_ToolBarItemMargin: 6, S.PM_ToolBarItemSpacing: 0, S.PM_ToolBarSeparatorExtent: 8,
    S.PM_ToolBarExtensionExtent: 28, S.PM_ToolBarHandleExtent: 10, S.PM_DockWidgetFrameWidth: 0,
    S.PM_DockWidgetTitleMargin: 2, S.PM_DockWidgetTitleBarButtonMargin: 6, S.PM_DockWidgetHandleExtent: 8,
    S.PM_TitleBarButtonSize: 16, S.PM_TabCloseIndicatorWidth: 16, S.PM_TabCloseIndicatorHeight: 16,
    S.PM_TabBarTabShiftVertical: 0, S.PM_TabBarBaseHeight: 0, S.PM_SliderTickmarkOffset: 0,
}
MARGINS = (S.PM_LayoutLeftMargin, S.PM_LayoutTopMargin, S.PM_LayoutRightMargin, S.PM_LayoutBottomMargin)
HINTS = {
    S.SH_DialogButtonBox_ButtonsHaveIcons: 1, S.SH_UnderlineShortcut: 0,
    S.SH_FormLayoutFieldGrowthPolicy: 1, S.SH_FormLayoutLabelAlignment: int(Qt.AlignRight.value),
    S.SH_ItemView_ShowDecorationSelected: 0, S.SH_ItemView_ChangeHighlightOnFocus: 0,
    S.SH_Menu_Scrollable: 1, S.SH_Menu_SubMenuPopupDelay: 150, S.SH_Menu_SubMenuSloppyCloseTimeout: 300,
    S.SH_MenuBar_AltKeyNavigation: 0, S.SH_ScrollBar_LeftClickAbsolutePosition: 1,
    S.SH_Slider_SnapToValue: 0, S.SH_Slider_StopMouseOverSlider: 0, S.SH_DockWidget_ButtonsHaveFrame: 0,
    S.SH_TitleBar_AutoRaise: 0,
}


def breeze_icon(name):
    """Breeze Dark's icon `name`, every size it comes in, each drawn from its own file (a small
    size is a different drawing, not the big one scaled) - also on a screen of twice the pixels."""
    if name not in _icons:
        ic = QIcon()
        folder = os.path.join(FILES, "icons")
        for size in sorted(os.listdir(folder)):
            f = os.path.join(folder, size, name + ".svg")
            if size.isdigit() and os.path.exists(f):
                with open(f, encoding="utf-8") as fh:  # (as KDE does: their accent is the system's)
                    svg = QSvgRenderer(QByteArray(re.sub(r"(\.ColorScheme-Accent\s*\{\s*color:\s*)#[0-9a-fA-F]+",
                                                         r"\g<1>" + ACCENT, fh.read()).encode()))
                for scale in (1.0, 2.0):
                    pm = QPixmap(int(int(size) * scale), int(int(size) * scale))
                    pm.fill(Qt.transparent)
                    painter = QPainter(pm)
                    svg.render(painter)
                    painter.end()
                    pm.setDevicePixelRatio(scale)
                    ic.addPixmap(pm)
        _icons[name] = ic
    return _icons[name]


SIDES = {QStyle.PE_IndicatorArrowUp: "up", QStyle.PE_IndicatorArrowDown: "down",
         QStyle.PE_IndicatorArrowLeft: "left", QStyle.PE_IndicatorArrowRight: "right"}


def arrow_icon(kind):
    """The chevron arrow<kind>.svg ("-down", "-up", ...)."""
    if kind not in _icons:
        _icons[kind] = QIcon(ARROW + kind + ".svg")
    return _icons[kind]


class Style(wheel.Style):
    """Fusion, with what Breeze drew differently: its sizes and behaviour (METRICS, HINTS: dialog
    buttons show their icons, shortcuts' letters are not underlined), arrows are chevrons, plain
    frames have no border and a scroll area's is rounded, a line is #404042, a combo box's list
    marks the item under the mouse with a frame, a progress bar is a thin line with its text
    beside it, and the icons are Breeze's."""

    def __init__(self):
        super().__init__("Fusion")

    def standardIcon(self, which, option=None, widget=None):
        name = ICONS.get(which)
        if name:
            ic = breeze_icon(name)
            if not ic.isNull():
                return ic
        return super().standardIcon(which, option, widget)

    def styleHint(self, hint, option=None, widget=None, data=None):
        if hint in HINTS:
            return HINTS[hint]
        return super().styleHint(hint, option, widget, data)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in METRICS:
            return METRICS[metric]
        if metric in MARGINS:                         # a window's own margins, or a widget's inside
            return 10 if widget is not None and widget.isWindow() else 6
        if metric == QStyle.PM_DefaultFrameWidth and isinstance(widget, QFrame):
            return 2 if isinstance(widget, QAbstractScrollArea) else 0
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        side = SIDES.get(element)
        if side:                                      # every arrow is Breeze's chevron
            size = min(16, option.rect.width(), option.rect.height())
            r = QRect(0, 0, size, size)
            r.moveCenter(option.rect.center())
            arrow_icon("-" + side).paint(painter, r)
            return
        super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        if element == QStyle.CE_ShapedFrame and option.frameShape in (QFrame.HLine, QFrame.VLine):
            painter.fillRect(QRect(option.rect.x(), option.rect.center().y(), option.rect.width(), 1)
                             if option.frameShape == QFrame.HLine else
                             QRect(option.rect.center().x(), option.rect.y(), 1, option.rect.height()), QColor(FRAME))
            return
        if element == QStyle.CE_ShapedFrame and option.frameShape == QFrame.StyledPanel:
            if isinstance(widget, QAbstractScrollArea):
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QColor(FRAME))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
                painter.restore()
            return                                    # a plain QFrame: no border
        if element == QStyle.CE_MenuItem and isinstance(widget, QComboBox) and option.state & QStyle.State_Selected:
            painter.save()                            # a combo box's list: the item under the mouse
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QColor(ACCENT))
            painter.setBrush(QColor(dim(ACCENT, under="#26262a")))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            painter.restore()
            option = QStyleOptionMenuItem(option)
            option.state &= ~QStyle.State_Selected
        if element in (QStyle.CE_ProgressBarGroove, QStyle.CE_ProgressBarContents) and self._line(option):
            self._draw_bar(element, option, painter)
            return
        if element == QStyle.CE_ProgressBarLabel and self._line(option):
            if option.textVisible:
                painter.save()
                painter.setPen(option.palette.color(QPalette.WindowText))
                painter.drawText(option.rect, Qt.AlignRight | Qt.AlignVCenter, option.text)
                painter.restore()
            return
        super().drawControl(element, option, painter, widget)

    def subElementRect(self, element, option, widget=None):
        if element in (QStyle.SE_ProgressBarGroove, QStyle.SE_ProgressBarContents, QStyle.SE_ProgressBarLabel) \
                and self._line(option):
            r = option.rect
            text = option.fontMetrics.horizontalAdvance("100%") + 6 if option.textVisible else 0
            if element == QStyle.SE_ProgressBarLabel:
                return QRect(r.right() - text + 1, r.y(), text, r.height())
            return QRect(r.x(), r.center().y() - 2, r.width() - text - (4 if text else 0), 6)
        return super().subElementRect(element, option, widget)

    def sizeFromContents(self, kind, option, size, widget=None):
        contents = size
        size = super().sizeFromContents(kind, option, size, widget)
        if kind == QStyle.CT_SpinBox:                 # as tall as a text field: the style sheet
            size.setHeight(contents.height())         # adds the padding and border, not Fusion
        elif kind == QStyle.CT_ItemViewItem:            # Breeze's rows are 3 px roomier all round
            size = size.grownBy(QMargins(3, 3, 3, 3))
        elif kind == QStyle.CT_MenuItem and not isinstance(widget, QMenu) \
                and option.menuItemType != QStyleOptionMenuItem.Separator:
            size.setHeight(size.height() + 6)         # a combo box's list
        return size

    @staticmethod
    def _line(option):
        """A horizontal progress bar that is not busy (Fusion draws a busy one)."""
        return (isinstance(option, QStyleOptionProgressBar) and option.state & QStyle.State_Horizontal
                and option.maximum > option.minimum)

    @staticmethod
    def _draw_bar(element, option, painter):
        r = QRectF(option.rect)
        if element == QStyle.CE_ProgressBarContents:
            part = (option.progress - option.minimum) / (option.maximum - option.minimum)
            part = min(max(part, 0.0), 1.0)
            if part <= 0:
                return
            w = r.width() * part
            r = QRectF(r.right() - w, r.y(), w, r.height()) if option.invertedAppearance else QRectF(r.x(), r.y(), w, r.height())
            colour = QColor(ACCENT)
        else:
            colour = QColor("#353537")
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawRoundedRect(r, 3, 3)
        painter.restore()


def apply(app):
    """Give `app` the look: the style, KDE's colours with the system's accent colour, the style
    sheet (and dark title bars)."""
    global ACCENT
    ACCENT = system_accent(app.palette())
    _icons.clear()
    app.setStyle(Style())
    app.setPalette(palette())
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "setColorScheme"):                  # Qt 6.8 on: Windows' title bars go dark
        hints.setColorScheme(Qt.ColorScheme.Dark)
    app.setStyleSheet(style_sheet())
