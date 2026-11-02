"""效果預設: a clip's chain of effects saved in the Library (.kcfx) and put on other clips, or as a
filter clip; a new Library gets a few to start with."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kiasecut import edit, fx, project, userlib  # noqa: E402
from test_edit import S, proj  # noqa: E402


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_starters(self):
        userlib.ensure_layout(self.root)
        folder = userlib.category_dir(self.root, "presets")
        names = sorted(os.listdir(folder))
        self.assertEqual(len(names), len(userlib.STARTER_PRESETS))
        for n in names:
            effects = userlib.load_preset(os.path.join(folder, n))
            self.assertTrue(all(fx.get(e["filter"]).error is None for e in effects), n)
        os.remove(os.path.join(folder, names[0]))
        userlib.ensure_layout(self.root)                                  # (not brought back once there)
        self.assertEqual(len(os.listdir(folder)), len(names) - 1)

    def test_save_and_put_on(self):
        p = proj()
        edit.add_effect(p, "c1", "builtin:blur")
        edit.add_effect(p, "c1", "builtin:grayscale")
        e = edit.find(p, "c1")[1]["effects"][0]
        e["params"]["radius"] = {"keys": [[0, 1.0, 0, 0, 0, 0], [S, 20.0, 0, 0, 0, 0]]}     # keyframes come along
        e["mix"] = 0.5
        path = userlib.save_preset(self.root, "我的", edit.find(p, "c1")[1]["effects"])
        effects = userlib.load_preset(path)
        self.assertEqual([x["filter"] for x in effects], ["builtin:blur", "builtin:grayscale"])
        self.assertEqual((effects[0]["mix"], effects[0]["params"]["radius"]["keys"][1][1]), (0.5, 20.0))
        for x in effects:
            edit.put_effect(p, "c2", x)
        c2 = edit.find(p, "c2")[1]
        self.assertEqual(len(c2["effects"]), 2)
        self.assertEqual(len({x["id"] for x in c2["effects"]} | {x["id"] for x in edit.find(p, "c1")[1]["effects"]}), 4)

    def test_library_filter_paths_travel(self):
        filt = os.path.join(userlib.category_dir(self.root, "filters"), "mine.glsl")
        os.makedirs(os.path.dirname(filt))
        with open(filt, "w") as fh:
            fh.write("vec4 effect(vec2 uv) { return src(uv); }")
        path = userlib.save_preset(self.root, "x", [{"filter": filt, "params": {}}], self.root)
        with open(path, encoding="utf-8") as fh:
            self.assertIn(project.LIB_TAG + "filters/mine.glsl", fh.read())
        project.LIBRARY_ROOT = self.root
        self.assertEqual(userlib.load_preset(path)[0]["filter"].replace("\\", "/"), filt.replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
