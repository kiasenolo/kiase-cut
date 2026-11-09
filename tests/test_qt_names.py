"""No attribute of ours hides a method of the Qt class it is set on.

`self.shape = "field"` on a QGraphicsItem replaces QGraphicsItem.shape(), which Qt itself calls to find what is under the
pointer: every move over the item then ended in "'str' object is not callable" (and, once, in a segmentation fault). A dialog's
`self.width = QDoubleSpinBox()` did the same to the dialog frame, which asks every dialog for its width(). Nothing says so
until that code runs, so the names are checked here, from the source."""
import ast
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtOpenGLWidgets, QtWidgets  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# names kept as they are: nothing calls the Qt method on these objects (the playhead's frame, a worker's QThread, a scroll area)
KNOWN = {("MainWindow", "pos"), ("Timeline", "pos"), ("SeekBar", "pos"), ("Player", "thread"), ("Thumbs", "thread"),
         ("ParamPanel", "scroll")}


def hidden():
    qt = {}
    for m in (QtWidgets, QtCore, QtGui, QtOpenGLWidgets):
        qt.update({k: getattr(m, k) for k in dir(m) if isinstance(getattr(m, k), type)})
    classes = {}
    for f in glob.glob(os.path.join(ROOT, "kiasecut", "**", "*.py"), recursive=True):
        with open(f, encoding="utf-8") as fh:
            for n in ast.walk(ast.parse(fh.read())):
                if isinstance(n, ast.ClassDef):
                    classes[n.name] = (f, n)

    def bases(name, seen=()):
        if name in qt:
            return [qt[name]]
        if name not in classes or name in seen:
            return []
        out = []
        for b in classes[name][1].bases:
            bn = b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else None
            if bn:
                out += bases(bn, seen + (name,))
        return out

    found = set()
    for name, (f, node) in classes.items():
        qts = bases(name)
        if not qts:
            continue
        own = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
        for a in ast.walk(node):
            if isinstance(a, ast.Attribute) and isinstance(a.ctx, ast.Store) and isinstance(a.value, ast.Name) \
                    and a.value.id == "self" and a.attr not in own and (name, a.attr) not in KNOWN \
                    and any(callable(getattr(b, a.attr, None)) for b in qts):
                found.add(f"{os.path.relpath(f, ROOT)}:{a.lineno}: {name}.{a.attr}")
    return sorted(found)


class QtNameTests(unittest.TestCase):
    def test_no_attribute_hides_a_qt_method(self):
        self.assertEqual(hidden(), [])


if __name__ == "__main__":
    unittest.main()
