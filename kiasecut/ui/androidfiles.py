"""File dialogs on Android: Qt's own dialog on real paths, in place of the system's chooser (which gives content:// addresses
no program here can open). install() swaps the four static functions of QFileDialog the program calls for these, so every
caller stays as it is."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QFileDialog

from .. import androidfs


def _start(directory):
    """(folder to open in, file name to preselect) for the directory argument of a static function."""
    directory = str(directory or "")
    if directory and not os.path.isdir(directory) and os.path.isdir(os.path.dirname(directory)):
        return os.path.dirname(directory), os.path.basename(directory)
    if directory and os.path.isdir(directory):
        return directory, ""
    return (androidfs.SHARED if os.path.isdir(androidfs.SHARED) else os.path.expanduser("~")), ""


def _dialog(parent, caption, directory, name_filter, mode, save=False):
    folder, name = _start(directory)
    dlg = QFileDialog(parent, caption, folder)
    dlg.setOption(QFileDialog.DontUseNativeDialog, True)
    dlg.setFileMode(mode)
    dlg.setAcceptMode(QFileDialog.AcceptSave if save else QFileDialog.AcceptOpen)
    if name_filter and mode != QFileDialog.Directory:
        dlg.setNameFilter(name_filter)
    if name:
        dlg.selectFile(name)
    dlg.setSidebarUrls([QUrl.fromLocalFile(p) for p in androidfs.sidebar()])
    top = (parent.window() if parent is not None else None) or next(iter(QApplication.topLevelWidgets()), None)
    if top is not None:
        dlg.resize(int(top.width() * 0.8), int(top.height() * 0.8))
    return dlg


def open_file(parent=None, caption="", directory="", filter="", selectedFilter="", options=None):
    dlg = _dialog(parent, caption, directory, filter, QFileDialog.ExistingFile)
    return (dlg.selectedFiles()[0], dlg.selectedNameFilter()) if dlg.exec() else ("", "")


def open_files(parent=None, caption="", directory="", filter="", selectedFilter="", options=None):
    dlg = _dialog(parent, caption, directory, filter, QFileDialog.ExistingFiles)
    return (dlg.selectedFiles(), dlg.selectedNameFilter()) if dlg.exec() else ([], "")


def save_file(parent=None, caption="", directory="", filter="", selectedFilter="", options=None):
    dlg = _dialog(parent, caption, directory, filter, QFileDialog.AnyFile, save=True)
    return (dlg.selectedFiles()[0], dlg.selectedNameFilter()) if dlg.exec() else ("", "")


def existing_directory(parent=None, caption="", dir="", options=None):
    dlg = _dialog(parent, caption, dir, "", QFileDialog.Directory)
    dlg.setOption(QFileDialog.ShowDirsOnly, True)
    return dlg.selectedFiles()[0] if dlg.exec() and dlg.selectedFiles() else ""


def install():
    QFileDialog.getOpenFileName = staticmethod(open_file)
    QFileDialog.getOpenFileNames = staticmethod(open_files)
    QFileDialog.getSaveFileName = staticmethod(save_file)
    QFileDialog.getExistingDirectory = staticmethod(existing_directory)
