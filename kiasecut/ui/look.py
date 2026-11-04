"""The program's look, the same on every platform.

It was made under KDE (the Breeze style and a dark colour scheme), and parts the style sheet
did not cover came from them; elsewhere those parts took the platform's own style and colours
(on Windows the effects' boxes got white borders). So the style is always Fusion, the colours
are always KDE's as they were (but the accent colour is the system's, read as the program starts:
Windows' too), the style sheet covers every kind of widget the program uses the
way Breeze drew it, and the standard icons are Breeze Dark's (kiasecut/look/icons).
"""
import gc
import os
import re

from PySide6.QtCore import QByteArray, QMargins, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractScrollArea, QComboBox, QFrame, QMenu, QStyle, QStyleOptionButton,
                               QStyleOptionMenuItem, QStyleOptionProgressBar, QStyleOptionToolButton)

from . import motion, wheel

FILES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "look").replace("\\", "/")
FRAME = "#404042"         # Breeze's frame around scroll areas, spin boxes and tool buttons
ACCENT = "#5b4731"        # the system's accent colour (apply reads it; this is KDE's as it was):
                          # a hovered tool button's frame, a radio button, a progress bar, selections
ARROW = f"{FILES}/arrow"  # its chevrons: arrow-down.svg, arrow-up.svg ...

# DaVinci Resolve-like: charcoal panels on a near-black frame, flat controls, light grey
# text; colour is left to clips, keyframes, the playhead and the meter
STYLE = """
QWidget { background: #111111; color: #d0d0d2; font-family: 'Segoe UI', 'Microsoft JhengHei UI', 'Noto Sans CJK TC', sans-serif; font-size: 12px; }
QMainWindow { background: #050505; }
QMenuBar { background: #0b0b0b; border-bottom: 1px solid #000000; }
QMenu { background: #1a1a1a; border: none; border-radius: 5px; padding: 10px 0; }
QMenu::item { padding: 5px 30px 5px 28px; background: transparent; color: #cccccc; }
QMenu::item:disabled { color: rgba(255, 255, 255, 77); }
QMenu::item:selected { background: rgba(255, 255, 255, 26); color: #ffffff; }
QMenuBar::item:selected { background: #3d3d43; }
QMenu::separator { height: 2px; background: #4d4d4d; margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 4px; }
QMenu::indicator:checked { image: url(@/check.svg); }
QMenu::right-arrow { image: url(@ARROW-right.svg); width: 14px; height: 14px; right: 4px; }
QToolBar { border: none; }
QToolBar::separator { background: @FRAME; width: 1px; height: 1px; margin: 4px; }
QSplitter::handle { background: #000000; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }
QDoubleSpinBox, QSpinBox, QPlainTextEdit, QTextEdit, QLineEdit, QComboBox { background: transparent; color: #ffffff; border: 2px solid #808080; border-radius: 0; padding: 0px 4px; selection-background-color: #808080; selection-color: #000000; placeholder-text-color: rgba(255, 255, 255, 128); }
QDoubleSpinBox:hover, QSpinBox:hover, QPlainTextEdit:hover, QTextEdit:hover, QLineEdit:hover, QComboBox:hover { border-color: #b3b3b3; }
QDoubleSpinBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QComboBox:on { border: 2px solid transparent; border-bottom-color: #ffffff; background: rgba(128, 128, 128, 77); }
QDoubleSpinBox:disabled, QSpinBox:disabled, QLineEdit:disabled, QComboBox:disabled { color: rgba(255, 255, 255, 128); border-color: #4d4d4d; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; border: none; subcontrol-origin: border; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; background: transparent; subcontrol-origin: border; }
QSpinBox::up-button { subcontrol-position: top right; margin: 3px 3px 0 0; }
QSpinBox::down-button { subcontrol-position: bottom right; margin: 0 3px 3px 0; }
QSpinBox::up-arrow { image: url(@ARROW-up.svg); width: 14px; height: 14px; }
QSpinBox::down-arrow { image: url(@ARROW-down.svg); width: 14px; height: 14px; }
QComboBox { padding-right: 22px; }
QComboBox:editable { padding-left: 5px; }
QComboBox::drop-down { width: 20px; border: none; subcontrol-origin: padding; subcontrol-position: top right; }
QComboBox::down-arrow { image: url(@ARROW-down.svg); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: #1a1a1a; border: none; outline: none; }
QTreeWidget, QListWidget { background: #111111; border: none; alternate-background-color: #141414; }
QTreeWidget::item, QListWidget::item { padding: 2px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #3d3d43; color: #ffffff; }
QTreeView::branch:has-children:closed { image: url(@ARROW-right.svg); }
QTreeView::branch:has-children:open { image: url(@ARROW-down.svg); }
QHeaderView { background: #161616; border: none; }
QHeaderView::section { background: #161616; color: #8e8e94; border: none; border-bottom: 1px solid #000000; padding: 4px; }
QLabel#time { font-family: Consolas, 'Cascadia Mono', monospace; font-size: 15px; color: #e8e8ea; }
QLabel#viewer { color: #8e8e94; }
QLabel#title { color: #8e8e94; font-weight: 600; font-size: 11px; }
QLabel#crumb { color: #d0d0d2; font-weight: 600; }
QWidget#bar { background: #161616; border-top: 1px solid #000000; border-bottom: 1px solid #000000; }
QTabWidget::pane { border: none; border-top: 1px solid #000000; }
QWidget#docktitle { background: #0b0b0b; border-bottom: 1px solid #000000; }
QMainWindow::separator { background: #000000; width: 3px; height: 3px; }
QMainWindow::separator:hover { background: #4a4a52; }
QTabBar#layouts { background: transparent; }
QTabBar#layouts::tab { padding: 3px 12px; border: none; background: transparent; }
QTabBar#layouts::tab:selected { background: #1f1f1f; color: #ffffff; border-radius: 3px; }
QTabBar { background: #0b0b0b; }
QTabBar::tab { background: #0b0b0b; color: #8e8e94; padding: 6px 14px; border: none; border-right: 1px solid #000000; }
QTabBar::tab:selected { background: #161616; color: #ffffff; }
QTabBar::tab:hover:!selected { color: #c0c0c4; }
QTabBar#timelines::tab { padding: 4px 14px; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QTabBar#timelines::tab:selected { background: #1f1f1f; }
QTabBar QToolButton { background: #0b0b0b; border: none; padding: 0; }
QTabBar::tear { width: 0; border: none; }
QMessageBox, QInputDialog, QColorDialog, QDialog { background: #111111; }
QMessageBox QLabel { color: #d0d0d2; background: transparent; }
QStatusBar { background: #0b0b0b; color: #8e8e94; border-top: 1px solid #000000; }
QStatusBar::item { border: none; }
QSlider:horizontal { min-height: 20px; }
QSlider:vertical { min-width: 20px; }
QSlider::groove:horizontal { height: 6px; background: #4d4d4d; }
QSlider::groove:horizontal:hover { background: #666666; }
QSlider::sub-page:horizontal { background: #808080; }
QSlider::handle:horizontal { background: #cccccc; width: 8px; margin: -7px 0; }
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::groove:vertical { width: 6px; background: #4d4d4d; }
QSlider::groove:vertical:hover { background: #666666; }
QSlider::add-page:vertical { background: #808080; }
QSlider::handle:vertical { background: #cccccc; height: 8px; margin: 0 -7px; }
QSlider::handle:vertical:hover { background: #ffffff; }
QScrollBar { background: #111111; width: 10px; height: 10px; }
QScrollBar::handle { background: #3a3a40; border-radius: 4px; min-height: 20px; min-width: 20px; }
QScrollBar::handle:hover { background: #4a4a52; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { width: 0; height: 0; background: none; }
QAbstractScrollArea::corner { background: transparent; border: none; }
QCheckBox::indicator { width: 12px; height: 12px; border-radius: 2px; }
QCheckBox::indicator:checked { background: #c9c9cd; border: 1px solid #c9c9cd; }
QCheckBox::indicator:unchecked { background: #0a0a0a; border: 1px solid #4a4a52; }
QCheckBox::indicator:indeterminate { background: #0a0a0a; border: 1px solid #c9c9cd; image: url(@/partial.svg); }
QRadioButton { min-height: 22px; }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 9px; border: 1px solid #3a3a3c; background: #111111; }
QRadioButton::indicator:hover { border-color: @ACCENT; }
QRadioButton::indicator:checked { border-color: @ACCENT; background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5, stop: 0 #d0d0d2, stop: 0.32 #d0d0d2, stop: 0.4 @DIM, stop: 1 @DIM); }
QGroupBox { border: 1px solid @FRAME; border-radius: 5px; margin-top: 22px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 2px 4px; }
QToolTip { background: #1f1f1f; color: #e0e0e2; border: 1px solid #000000; }
QProgressDialog QLabel { background: transparent; }
""".replace("@ARROW", ARROW).replace("@FRAME", FRAME).replace("@/", FILES + "/")   # (@ACCENT, @DIM: style_sheet)

# KDE's colours as the program was made with them; the parts the style sheet leaves to the style
# (selected text, links, placeholders, frames and lines) take these
COLOURS = {
    "Window": "#0d0d0d", "WindowText": "#fcfdfd", "Base": "#0d0d0d", "AlternateBase": "#0d0d0d",
    "ToolTipBase": "#0d0d0d", "ToolTipText": "#fcfdfd", "PlaceholderText": "#f2f3f3", "Text": "#fefefe",
    "Button": "#141414", "ButtonText": "#fefefe", "BrightText": "#ffffff", "Light": "#abaebb",
    "Midlight": "#888da2", "Mid": "#515669", "Dark": "#6f758f", "Shadow": "#888da2",
    "Highlight": ACCENT, "HighlightedText": "#ffffff", "Link": "#edbc84", "LinkVisited": "#7f8c8d",
    "Accent": ACCENT,
}
DISABLED = {
    "WindowText": "#636467", "PlaceholderText": "#606163", "Text": "#646567", "ButtonText": "#67696c",
    "Highlight": "#0d0d0d", "HighlightedText": "#636467", "Link": "#5e4e3d", "LinkVisited": "#383d40",
    "Accent": "#0d0d0d",
}


def system_accent(p):
    """The accent colour the platform's palette `p` has (Windows', macOS's, KDE's)."""
    role = getattr(QPalette.ColorRole, "Accent", None)  # (Qt 6.6 on; before it, the highlight)
    return p.color(role if role is not None else QPalette.Highlight).name()


def dim(colour, part=0.3, under="#111111"):
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

    def polish(self, widget):
        super().polish(widget)
        motion.attach(widget)                         # (a push or tool button: its fill and ink are drawn from the Fader)

    def unpolish(self, widget):
        super().unpolish(widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        fader = motion.of(widget)
        if fader is not None and element in (QStyle.PE_PanelButtonCommand, QStyle.PE_PanelButtonTool):
            painter.fillRect(option.rect, fader.bg)
            return
        if fader is not None and element in (QStyle.PE_FrameDefaultButton, QStyle.PE_FrameButtonBevel, QStyle.PE_FrameButtonTool):
            return
        side = SIDES.get(element)
        if side:                                      # every arrow is Breeze's chevron
            size = min(16, option.rect.width(), option.rect.height())
            r = QRect(0, 0, size, size)
            r.moveCenter(option.rect.center())
            if fader is not None and self._dark_ink(fader):      # (on a white button: black)
                painter.drawPixmap(r, self._tinted(arrow_icon("-" + side), r.size(), fader.ink))
            else:
                arrow_icon("-" + side).paint(painter, r)
            return
        super().drawPrimitive(element, option, painter, widget)

    @staticmethod
    def _dark_ink(fader):
        return fader.ink.alpha() == 255 and fader.ink.lightness() < 250

    @staticmethod
    def _tinted(icon, size, colour, state=QIcon.Off):
        """icon at size, every opaque part of it in colour."""
        dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
        pm = icon.pixmap(size, dpr, QIcon.Normal, state)
        out = QPixmap(pm)
        painter = QPainter(out)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(out.rect(), colour)
        painter.end()
        return out

    def _inked(self, option, fader, icon_size=None):
        """option (a button's) with its palette's text and its icon in the Fader's ink, and no state that makes the base draw a
        panel or a hovered icon."""
        opt = type(option)(option)
        pal = QPalette(opt.palette)
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            for role in (QPalette.ButtonText, QPalette.WindowText, QPalette.Text):
                pal.setColor(group, role, fader.ink)
        opt.palette = pal
        opt.state &= ~(QStyle.State_MouseOver | QStyle.State_Sunken | QStyle.State_Raised)
        if self._dark_ink(fader) and not opt.icon.isNull() and opt.state & QStyle.State_Enabled:
            size = opt.iconSize if opt.iconSize.isValid() and not opt.iconSize.isEmpty() else QSize(16, 16)
            state = QIcon.On if opt.state & QStyle.State_On else QIcon.Off
            opt.icon = QIcon(self._tinted(opt.icon, size, fader.ink, state))
        return opt

    def drawComplexControl(self, control, option, painter, widget=None):
        fader = motion.of(widget)
        if control == QStyle.CC_ToolButton and fader is not None and isinstance(option, QStyleOptionToolButton):
            painter.fillRect(option.rect, fader.bg)
            opt = self._inked(option, fader)
            opt.state &= ~QStyle.State_On
            super().drawComplexControl(control, opt, painter, widget)
            return
        super().drawComplexControl(control, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        fader = motion.of(widget)
        if fader is not None and element == QStyle.CE_PushButtonLabel and isinstance(option, QStyleOptionButton):
            super().drawControl(element, self._inked(option, fader), painter, widget)
            return
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
            painter.setBrush(QColor(dim(ACCENT, under="#1a1a1a")))
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
        elif kind == QStyle.CT_PushButton and motion.of(widget) is not None:
            tool = widget.objectName() == "tool"          # (what the style sheet's padding was: 4 x 14, an icon button's 3)
            size = QSize(contents.width() + (6 if tool else 28), contents.height() + (6 if tool else 8))
        elif kind == QStyle.CT_ToolButton and motion.of(widget) is not None:
            flat = widget.autoRaise()
            size = QSize(contents.width() + (9 if flat else 19), contents.height() + (9 if flat else 15))
            if isinstance(option, QStyleOptionToolButton) and option.features & QStyleOptionToolButton.HasMenu:
                size.setWidth(size.width() + 14)
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
    gc.collect()                      # (dead widgets still waiting for the collector must not go while the style changes under them)
    ACCENT = system_accent(app.palette())
    _icons.clear()
    app.setStyle(Style())
    app.setPalette(palette())
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "setColorScheme"):                  # Qt 6.8 on: Windows' title bars go dark
        hints.setColorScheme(Qt.ColorScheme.Dark)
    app.setStyleSheet(style_sheet())
