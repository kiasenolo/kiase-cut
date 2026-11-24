"""Importing a file that the media library already has (the very file, spelled otherwise, or its copy in Media) adds no
second item; a scan of Media drops the item of an outside file whose copy is there."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402

from kiasecut import library, project  # noqa: E402


class MediaDupeTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "Media"))
        self.out = os.path.join(tempfile.mkdtemp(), "20231219_194308.jpg")
        Image.new("RGB", (8, 8), "red").save(self.out)
        self.p = project.new()

    def test_the_same_file_again_is_not_added(self):
        a = library.add_files(self.p, [self.out], reuse=True)
        b = library.add_files(self.p, [self.out.replace("/", "//")], reuse=True)       # (spelled otherwise)
        self.assertIs(a[0], b[0])
        self.assertEqual(len(library.lib(self.p)["items"]), 1)

    def test_a_copy_in_media_counts_as_the_same(self):
        copy = os.path.join(self.root, "Media", os.path.basename(self.out))
        shutil.copy2(self.out, copy)                                   # (as 整理素材 / import_copy do)
        library.add_files(self.p, [copy], reuse=True)
        library.add_files(self.p, [self.out], reuse=True)              # the original, imported again
        self.assertEqual(len(library.lib(self.p)["items"]), 1)
        other = os.path.join(tempfile.mkdtemp(), os.path.basename(self.out))
        Image.new("RGB", (8, 8), "blue").save(other)                   # same name, another picture
        os.utime(other, (1, 1))
        library.add_files(self.p, [other], reuse=True)
        self.assertEqual(len(library.lib(self.p)["items"]), 2)

    def test_a_scan_keeps_one_row_for_a_file_and_its_copy(self):
        library.add_files(self.p, [self.out])                          # (an older project: the outside file's item)
        copy = os.path.join(self.root, "Media", os.path.basename(self.out))
        shutil.copy2(self.out, copy)
        library.apply_scan(self.p, self.root, library.scan(self.root))
        items = library.lib(self.p)["items"]
        self.assertEqual([library.norm(it["path"]) for it in items], [library.norm(copy)])


if __name__ == "__main__":
    unittest.main()
