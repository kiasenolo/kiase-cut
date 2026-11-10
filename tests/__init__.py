"""The tests run against a home of their own: the user's settings, Library and caches (a Library that lives on a drive
which is not plugged in makes a window ask a question nobody answers) are never read or written."""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("KIASECUT_TEST_REAL_HOME"):
    _home = tempfile.mkdtemp(prefix="kiasecut-test-home-")
    atexit.register(shutil.rmtree, _home, ignore_errors=True)
    os.environ["HOME"] = _home
    for _k, _d in (("XDG_CONFIG_HOME", ".config"), ("XDG_CACHE_HOME", ".cache"), ("XDG_DATA_HOME", ".local/share")):
        os.environ[_k] = os.path.join(_home, _d)
    os.environ.pop("XDG_DOCUMENTS_DIR", None)
    if os.name == "nt":
        # Windows keeps settings in the registry, which no folder above moves (nor does QSettings.setPath, for the native format):
        # the tests read the user's own settings there and wrote theirs into them. QSettings(organisation, program) is an .ini
        # file in the home above instead, for every module loaded after this one
        try:
            from PySide6 import QtCore

            class _Settings(QtCore.QSettings):
                def __init__(self, *args):
                    if len(args) == 2 and all(isinstance(a, str) for a in args):
                        args = (QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope) + args
                    super().__init__(*args)

            _Settings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, os.path.join(_home, ".config"))
            QtCore.QSettings = _Settings
        except ImportError:
            pass
