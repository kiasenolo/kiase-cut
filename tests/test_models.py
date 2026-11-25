"""models.py: OBJ and glTF files read and kept as .kmodel files."""
import base64
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from kiasecut import edit, models, project  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])

TRIANGLE = np.array([(0, 0, 0), (2, 0, 0), (0, 1, 0)], "f4")


def gltf(nodes, extra=None, mesh_extra=None):
    """A one-triangle glTF document with its data inside it."""
    raw = TRIANGLE.tobytes()
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"primitives": [dict({"attributes": {"POSITION": 0}}, **(mesh_extra or {}))]}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
           "bufferViews": [{"buffer": 0, "byteLength": len(raw)}],
           "buffers": [{"byteLength": len(raw), "uri": "data:application/octet-stream;base64," + base64.b64encode(raw).decode()}]}
    doc.update(extra or {})
    return doc


class Models(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.d, name)
        with open(path, "wb") as f:
            f.write(text if isinstance(text, bytes) else text.encode())
        return path

    def test_obj_faces_are_cut_into_triangles_and_stood_the_right_way_up(self):
        path = self.write("a.obj", "v 0 0 0\nv 1 0 0\nv 1 2 0\nv 0 2 0\nf -4 -3 -2 -1\n")      # (counted from the end)
        (piece,) = models.read(path)
        data = piece["data"]
        self.assertEqual(data.shape, (6, 12))
        self.assertEqual((float(data[:, 1].min()), float(data[:, 1].max())), (-2.0, 0.0))     # (y up -> y down)
        self.assertTrue(np.allclose(data[:, 3:6], (0, 0, -1)))                                # (no normals: made, facing the viewer)

    def test_obj_materials_make_pieces(self):
        self.write("m.mtl", "newmtl a\nKd 1 0 0\nnewmtl b\nKd 0 0 1\nPm 1\nPr 0.2\n")
        path = self.write("b.obj", "mtllib m.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nusemtl a\nf 1 2 3\nusemtl b\nf 1 2 4\n")
        a, b = models.read(path)
        self.assertEqual(tuple(a["data"][0, 6:9]), (1.0, 0.0, 0.0))
        self.assertEqual((tuple(b["data"][0, 6:9]), b["metallic"], b["roughness"]), ((0.0, 0.0, 1.0), 1.0, 0.2))

    def test_gltf_nodes_move_their_meshes_and_those_of_their_children(self):
        nodes = [{"translation": [10, 0, 0], "scale": [2, 2, 2], "children": [1]},
                 {"mesh": 0, "rotation": [0, 0, 0.70710678, 0.70710678]}]                      # (a quarter turn about z)
        (piece,) = models.read(self.write("a.gltf", json.dumps(gltf(nodes))))
        got = piece["data"][:, :3] * (1, -1, -1)
        self.assertTrue(np.allclose(got, [(10, 0, 0), (10, 4, 0), (8, 0, 0)], atol=1e-4), got)

    def test_glb_with_a_material(self):
        doc = gltf([{"mesh": 0}], {"materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 1], "metallicFactor": 0.25}}]},
                   {"material": 0})
        del doc["buffers"][0]["uri"]
        j = json.dumps(doc).encode()
        j += b" " * (-len(j) % 4)
        raw = TRIANGLE.tobytes()
        glb = struct.pack("<4sII", b"glTF", 2, 28 + len(j) + len(raw)) + struct.pack("<I4s", len(j), b"JSON") + j + \
            struct.pack("<I4s", len(raw), b"BIN\0") + raw
        (piece,) = models.read(self.write("a.glb", glb))
        self.assertEqual((tuple(piece["data"][0, 6:9]), piece["metallic"], piece["roughness"]), ((1.0, 0.0, 0.0), 0.25, 1.0))

    def test_bad_files_say_what_is_wrong(self):
        for name, text in (("empty.obj", "v 0 0 0\n"), ("lost.obj", "v 0 0 0\nf 1 2 3\n"), ("junk.glb", "glTF junk"),
                           ("old.gltf", '{"asset": {"version": "1.0"}}'),
                           ("draco.gltf", json.dumps(gltf([{"mesh": 0}], {"extensionsRequired": ["KHR_draco_mesh_compression"]}))),
                           ("out.gltf", json.dumps(gltf([{"mesh": 0}], {"buffers": [{"byteLength": 36, "uri": "/etc/hostname"}]})))):
            with self.assertRaises(models.ModelError, msg=name):
                models.read(self.write(name, text))

    def test_converted_it_is_one_file_that_can_be_made_any_size(self):
        path = self.write("a.gltf", json.dumps(gltf([{"mesh": 0}])))
        kept, size = models.convert(path, os.path.join(self.d, "kept"))
        self.assertEqual([round(x, 3) for x in size], [1.0, 0.5, 0.0])
        self.assertEqual(models.convert(path, os.path.join(self.d, "kept"))[0], kept)          # (the same model: the same file)
        data, ranges = models.mesh(kept, 400.0, 100.0, 1.0)
        self.assertTrue(np.allclose(np.ptp(data[:, :3], axis=0), (400, 100, 0)))
        self.assertTrue(np.allclose(np.linalg.norm(data[:, 3:6], axis=1), 1.0))
        self.assertEqual([(a, n) for a, n, _p in ranges], [(0, 3)])
        with self.assertRaises(models.ModelError):
            models.mesh(kept + "x", 1, 1, 1)

    def test_a_projects_model_and_surface_paths_follow_the_files(self):
        clip = {"id": "a", "solid": {"on": True, "model": "/old/m.kmodel", "surface": "/old/p.png"}}
        data = {"timelines": [{"tracks": [{"id": "t", "kind": "video", "clips": [clip]}]}]}
        project._map_paths(data, lambda p: p.replace("/old", "/new"))
        self.assertEqual((clip["solid"]["model"], clip["solid"]["surface"]), ("/new/m.kmodel", "/new/p.png"))

    def test_a_surface_has_to_be_a_picture_or_a_video(self):
        from PySide6.QtGui import QImage
        pic = QImage(8, 4, QImage.Format_RGB32)
        pic.fill(0)
        pic.save(os.path.join(self.d, "p.png"))
        held = {}
        edit._set_surface(held, os.path.join(self.d, "p.png"))
        self.assertEqual(held["surface_info"], {"kind": "image", "width": 8, "height": 4})
        edit._set_surface(held, None)
        self.assertEqual(held, {})
        with self.assertRaises(edit.EditError):
            edit._set_surface(held, os.path.join(self.d, "nothing.png"))


if __name__ == "__main__":
    unittest.main()
