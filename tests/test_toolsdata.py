"""The extra tools' data (toolsdata.py): my cubic-bezier curves, colour cards with Info, and a
card's colours exported / imported as a JSON string[]."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kiasecut import toolsdata  # noqa: E402


class ToolsDataTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_curves(self):
        self.assertEqual(toolsdata.load_curves(self.root), [])
        toolsdata.save_curves(self.root, [{"name": "彈跳", "value": [0.34, 1.56, 0.64, 1]}])
        self.assertTrue(toolsdata.curves_file(self.root).endswith(os.path.join("tools", "cubic-bezier-tools", "curves.json")))
        self.assertEqual(toolsdata.load_curves(self.root), [{"name": "彈跳", "value": [0.34, 1.56, 0.64, 1.0]}])
        self.assertEqual(toolsdata.bezier_text([0.34, 1.56, 0.64, 1.0]), "cubic-bezier(0.34, 1.56, 0.64, 1)")

    def test_cards(self):
        path = toolsdata.save_card(self.root, {"name": "海邊", "info": "夏天", "colors": ["#1E90FF", "nope", "#ffd70080"]})
        self.assertEqual(os.path.dirname(path), toolsdata.palette_dir(self.root))
        card, = toolsdata.load_cards(self.root)
        self.assertEqual((card["name"], card["info"], card["colors"]), ("海邊", "夏天", ["#1e90ff", "#ffd70080"]))
        out = os.path.join(self.root, "x.json")
        toolsdata.export_colors(card, out)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), ["#1e90ff", "#ffd70080"])
        self.assertEqual(toolsdata.import_colors(out), ["#1e90ff", "#ffd70080"])
        toolsdata.save_card(self.root, {"name": "海邊", "info": "", "colors": []})       # a second of the same name
        self.assertEqual(len(toolsdata.load_cards(self.root)), 2)
        with open(out, "w") as fh:
            json.dump([1, 2], fh)
        with self.assertRaises(ValueError):
            toolsdata.import_colors(out)


if __name__ == "__main__":
    unittest.main()
