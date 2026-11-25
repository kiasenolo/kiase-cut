"""3D model files for the objects of a scene: OBJ (with its MTL) and glTF 2.0 (.gltf, .glb) are read and kept as one .kmodel file -
the triangles and the textures together, so that a project has everything of a model in one file (convert). What is read: shapes,
node transforms, normals, UVs, vertex colours, base colour (and its texture), metallic and roughness. Not read: animations and skins
(a skinned model stands as it was bound), normal, emissive and occlusion maps; a texture of metallic and roughness is averaged.

A mesh is mesh.py's with two more columns, (n, 12): position, normal, colour (r, g, b, a as picked - sRGB), u, v (v down the
picture). In a .kmodel the model is centred and its longest side is 1 (x right, y down, z away); mesh() makes it any size."""
import base64
import hashlib
import io
import json
import os
import struct
import urllib.parse

import numpy as np

EXTS = (".obj", ".gltf", ".glb")
SUFFIX = ".kmodel"
MOST_TRIANGLES = 2_000_000
TEXTURE_MAX = 2048                 # px: the longest side a texture is kept with
SMOOTH_COS = 0.766                 # (40 degrees: faces of a model without normals meeting flatter than this are shaded as one curve)


class ModelError(Exception):
    pass


def is_model(path):
    return os.path.splitext(str(path))[1].lower() in EXTS


def _srgb(linear):
    return np.clip(linear, 0.0, 1.0) ** (1.0 / 2.2)


def _beside(folder, name):
    """The file a model names, which has to be relative to the model's own folder."""
    name = name.replace("\\", "/")
    if "://" in name or os.path.isabs(name) or (len(name) > 1 and name[1] == ":"):
        raise ModelError(f"模型指向外面的檔案：{name}")
    return os.path.join(folder, name)


def _face_normals(positions):
    """The normals (n, 3) of triangles (n, 3, 3), as long as twice their areas."""
    return np.cross(positions[:, 1] - positions[:, 0], positions[:, 2] - positions[:, 0])


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def _made_normals(positions, ids):
    """Normals (n, 3, 3) for triangles without them: the mean of the faces round a corner (ids: (n, 3) which corners are one),
    except where a face turns too far from it - a sharp edge."""
    whole = _face_normals(positions)
    face = _unit(whole)
    total = np.zeros((int(ids.max()) + 1, 3))
    for k in range(3):
        np.add.at(total, ids[:, k], whole)
    mean = _unit(total)[ids]
    flat = np.repeat(face[:, None, :], 3, axis=1)
    return np.where(np.sum(mean * flat, axis=2, keepdims=True) > SMOOTH_COS, mean, flat)


# -- OBJ -------------------------------------------------------------------------------------------------------------------------
def _read_mtl(path):
    out, cur = {}, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        key, rest = parts[0].lower(), parts[1:]
        if key == "newmtl":
            cur = out[" ".join(rest)] = {"color": [0.8, 0.8, 0.8], "alpha": 1.0, "texture": None, "metallic": 0.0, "roughness": 0.5}
        elif cur is None or not rest:
            continue
        elif key == "kd" and len(rest) >= 3:
            cur["color"] = [float(x) for x in rest[:3]]
        elif key == "d":
            cur["alpha"] = float(rest[-1])
        elif key == "ns":
            cur["roughness"] = float(np.clip(1.0 - np.sqrt(max(float(rest[0]), 0.0) / 1000.0), 0.05, 1.0))
        elif key == "pr":
            cur["roughness"] = float(rest[0])
        elif key == "pm":
            cur["metallic"] = float(rest[0])
        elif key == "map_kd":
            name = rest[-1] if rest[0].startswith("-") else line.split(None, 1)[1].strip()
            try:
                with open(_beside(os.path.dirname(path), name), "rb") as f:
                    cur["texture"] = f.read()
            except OSError:
                pass
    return out


def read_obj(path):
    """[piece] of an OBJ file: one for each material."""
    points, colours, uvs, normals = [], [], [], []
    materials, groups, current = {}, {}, ""
    total = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            key = parts[0]
            if key == "v":
                points.append((float(parts[1]), float(parts[2]), float(parts[3])))
                colours.append(tuple(float(x) for x in parts[4:7]) if len(parts) >= 7 else (1.0, 1.0, 1.0))
            elif key == "vt":
                uvs.append((float(parts[1]), float(parts[2]) if len(parts) > 2 else 0.0))
            elif key == "vn":
                normals.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif key == "f":
                corners = []
                for word in parts[1:]:
                    bits = word.split("/")
                    one = []
                    for k, held in enumerate((points, uvs, normals)):
                        i = int(bits[k]) if k < len(bits) and bits[k] else 0
                        one.append(i - 1 if i > 0 else len(held) + i if i < 0 else -1)
                    corners.append(one)
                made = groups.setdefault(current, [])
                for i in range(1, len(corners) - 1):
                    made.append((corners[0], corners[i], corners[i + 1]))
                    total += 1
                if total > MOST_TRIANGLES:
                    raise ModelError(f"模型的三角面超過 {MOST_TRIANGLES:,} 個")
            elif key == "usemtl":
                current = " ".join(parts[1:])
            elif key == "mtllib":
                materials.update(_read_mtl(_beside(os.path.dirname(path), line.split(None, 1)[1].strip())))
    if not total:
        raise ModelError("檔案裡沒有任何面")
    points, colours = np.array(points, float), np.array(colours, float)
    pieces = []
    for name, tris in groups.items():
        index = np.array(tris, np.int64)                               # (n, 3 corners, (v, vt, vn))
        vi, ti, ni = index[..., 0], index[..., 1], index[..., 2]
        if vi.min() < 0 or vi.max() >= len(points):
            raise ModelError("面用到了不存在的頂點")
        m = materials.get(name) or {"color": [0.8, 0.8, 0.8], "alpha": 1.0, "texture": None, "metallic": 0.0, "roughness": 0.5}
        pos = points[vi]
        if normals and ni.min() >= 0 and ni.max() < len(normals):
            n = _unit(np.array(normals, float)[ni])
        else:
            n = _made_normals(pos, vi)
        uv = np.zeros(pos.shape[:2] + (2,))
        if uvs and ti.min() >= 0 and ti.max() < len(uvs):
            uv = np.array(uvs, float)[ti]
            uv = np.stack([uv[..., 0], 1.0 - uv[..., 1]], axis=-1)     # (OBJ counts v from the bottom)
        textured = m["texture"] is not None
        base = np.ones(3) if textured and max(m["color"]) <= 0.0 else np.array(m["color"], float)
        rgb = np.clip(base * colours[vi], 0.0, 1.0)
        rgba = np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 1.0)], axis=-1)
        data = np.concatenate([pos, n, rgba, uv], axis=-1).reshape(-1, 12)
        pieces.append({"data": data, "texture": m["texture"], "metallic": m["metallic"], "roughness": m["roughness"],
                       "cutoff": 0.5 if textured else 0.0})
    for p in pieces:                                                   # (y up, z to the viewer -> y down, z away)
        p["data"][:, [1, 2, 4, 5]] *= -1.0
    return pieces


# -- glTF ------------------------------------------------------------------------------------------------------------------------
_TYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_SIZES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class _Gltf:
    def __init__(self, path):
        self.folder = os.path.dirname(os.path.abspath(path))
        with open(path, "rb") as f:
            raw = f.read()
        binary = None
        if raw[:4] == b"glTF":
            if struct.unpack_from("<I", raw, 4)[0] != 2:
                raise ModelError("只支援 glTF 2.0")
            at, chunks = 12, {}
            while at + 8 <= len(raw):
                length, kind = struct.unpack_from("<I4s", raw, at)
                chunks[kind] = raw[at + 8:at + 8 + length]
                at += 8 + length
            doc, binary = chunks.get(b"JSON"), chunks.get(b"BIN\x00")
            if doc is None:
                raise ModelError("GLB 檔案壞了")
            raw = doc
        self.doc = json.loads(raw.decode("utf-8-sig"))
        if str((self.doc.get("asset") or {}).get("version", "")).split(".")[0] != "2":
            raise ModelError("只支援 glTF 2.0")
        for ext in self.doc.get("extensionsRequired") or []:
            if ext in ("KHR_draco_mesh_compression", "EXT_meshopt_compression"):
                raise ModelError(f"不支援壓縮過的 glTF（{ext}）；匯出時請關掉壓縮")
        self.buffers = [self.uri(b["uri"]) if "uri" in b else binary for b in self.doc.get("buffers") or []]

    def uri(self, uri):
        if uri.startswith("data:"):
            return base64.b64decode(uri.split(",", 1)[1])
        with open(_beside(self.folder, urllib.parse.unquote(uri)), "rb") as f:
            return f.read()

    def view(self, i):
        v = self.doc["bufferViews"][i]
        start = v.get("byteOffset", 0)
        return self.buffers[v["buffer"]][start:start + v["byteLength"]], v.get("byteStride")

    def accessor(self, i):
        """(count, components) of accessor i, normalized integers as floats."""
        a = self.doc["accessors"][i]
        kind, size, count = _TYPES[a["componentType"]], _SIZES[a["type"]], a["count"]
        if count > MOST_TRIANGLES * 3:
            raise ModelError(f"模型的三角面超過 {MOST_TRIANGLES:,} 個")
        item = size * np.dtype(kind).itemsize
        if "bufferView" in a:
            data, stride = self.view(a["bufferView"])
            start, stride = a.get("byteOffset", 0), stride or item
            raw = np.frombuffer(data, np.uint8)
            if count and start + stride * (count - 1) + item > len(raw):
                raise ModelError("glTF 的資料不完整")
            rows = start + np.arange(count)[:, None] * stride + np.arange(item)[None, :]
            out = np.frombuffer(raw[rows].tobytes(), kind).reshape(count, size)
        else:
            out = np.zeros((count, size), kind)
        if "sparse" in a:
            s = a["sparse"]
            out = out.copy()
            ik = _TYPES[s["indices"]["componentType"]]
            where = np.frombuffer(self.view(s["indices"]["bufferView"])[0], ik, s["count"], s["indices"].get("byteOffset", 0))
            values = np.frombuffer(self.view(s["values"]["bufferView"])[0], kind, s["count"] * size, s["values"].get("byteOffset", 0))
            out[where] = values.reshape(-1, size)
        if a.get("normalized") and kind is not np.float32:
            return np.maximum(out / float(np.iinfo(kind).max), -1.0)
        return out

    def image(self, texture):
        """The bytes of the picture of texture info `texture`, or None."""
        if not texture:
            return None
        source = self.doc["textures"][texture["index"]].get("source")
        if source is None:
            return None
        img = self.doc["images"][source]
        try:
            return self.uri(img["uri"]) if "uri" in img else bytes(self.view(img["bufferView"])[0])
        except OSError:
            return None

    def material(self, i):
        m = self.doc["materials"][i] if i is not None else {}
        pbr = m.get("pbrMetallicRoughness") or {}
        factor = pbr.get("baseColorFactor") or [1.0, 1.0, 1.0, 1.0]
        base, info = factor, pbr.get("baseColorTexture")
        metallic, roughness = pbr.get("metallicFactor", 1.0), pbr.get("roughnessFactor", 1.0)
        old = (m.get("extensions") or {}).get("KHR_materials_pbrSpecularGlossiness")
        if old and not pbr:
            base, info = old.get("diffuseFactor") or [1.0, 1.0, 1.0, 1.0], old.get("diffuseTexture")
            metallic, roughness = 0.0, 1.0 - old.get("glossinessFactor", 1.0)
        both = self.image(pbr.get("metallicRoughnessTexture"))
        if both is not None:                                    # (one value for the piece: the picture's mean, green and blue)
            mean = _mean(both)
            if mean is not None:
                roughness, metallic = roughness * mean[1], metallic * mean[2]
        if i is None:
            metallic, roughness = 0.0, 0.5
        mode = m.get("alphaMode", "OPAQUE")
        return {"color": list(_srgb(np.array(base[:3], float))), "alpha": float(base[3]) if mode != "OPAQUE" else 1.0,
                "texture": self.image(info), "set": (info or {}).get("texCoord", 0), "metallic": float(metallic),
                "roughness": float(roughness), "cutoff": m.get("alphaCutoff", 0.5) if mode == "MASK" else 0.5 if mode == "BLEND" else 0.0}


def _mean(data):
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            return np.asarray(im.convert("RGB").resize((16, 16)), float).reshape(-1, 3).mean(axis=0) / 255.0
    except Exception:
        return None


def _node_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T
    x, y, z, w = node.get("rotation") or (0.0, 0.0, 0.0, 1.0)
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * np.array(node.get("scale") or (1.0, 1.0, 1.0), float)
    m[:3, 3] = node.get("translation") or (0.0, 0.0, 0.0)
    return m


def read_gltf(path):
    """[piece] of a .gltf or .glb file: one for each part of each mesh in its scene."""
    g = _Gltf(path)
    doc = g.doc
    nodes = doc.get("nodes") or []
    if doc.get("scenes"):
        roots = doc["scenes"][doc.get("scene", 0)].get("nodes") or []
    else:
        children = {k for n in nodes for k in n.get("children") or []}
        roots = [i for i in range(len(nodes)) if i not in children]
    pieces, total, seen = [], 0, set()
    todo = [(i, np.eye(4)) for i in reversed(roots)]
    while todo:
        i, parent = todo.pop()
        if i in seen:                                           # (a tree: a node is in it once)
            continue
        seen.add(i)
        node = nodes[i]
        moved = parent @ _node_matrix(node)
        world = np.eye(4) if "skin" in node else moved           # (a skinned mesh is where its bones bind it, not where its node is)
        todo += [(k, moved) for k in reversed(node.get("children") or [])]
        if "mesh" not in node:
            continue
        for prim in doc["meshes"][node["mesh"]]["primitives"]:
            mode, attributes = prim.get("mode", 4), prim["attributes"]
            if mode not in (4, 5, 6) or "POSITION" not in attributes:
                continue
            points = g.accessor(attributes["POSITION"]).astype(float)
            index = g.accessor(prim["indices"]).reshape(-1).astype(np.int64) if "indices" in prim else np.arange(len(points))
            if mode == 4:
                tris = index[:len(index) // 3 * 3].reshape(-1, 3)
            else:
                tris = np.stack([index[:-2], index[1:-1], index[2:]] if mode == 5 else
                                [np.full(max(len(index) - 2, 0), index[0] if len(index) else 0), index[1:-1], index[2:]], axis=1)
                if mode == 5:
                    tris[1::2] = tris[1::2][:, [1, 0, 2]]
            if not len(tris):
                continue
            if tris.min() < 0 or tris.max() >= len(points):
                raise ModelError("面用到了不存在的頂點")
            total += len(tris)
            if total > MOST_TRIANGLES:
                raise ModelError(f"模型的三角面超過 {MOST_TRIANGLES:,} 個")
            m = g.material(prim.get("material"))
            turn = world[:3, :3]
            pos = (points @ turn.T + world[:3, 3])[tris]
            if "NORMAL" in attributes:
                back = np.linalg.pinv(turn)
                n = _unit(g.accessor(attributes["NORMAL"]).astype(float) @ back)[tris]
            else:                                               # (glTF: without normals the faces are flat)
                n = np.repeat(_unit(_face_normals(pos))[:, None, :], 3, axis=1)
            uv = np.zeros(pos.shape[:2] + (2,))
            name = f"TEXCOORD_{m['set']}"
            if name in attributes:
                uv = g.accessor(attributes[name]).astype(float)[tris]
            rgb = np.tile(np.array(m["color"]), pos.shape[:2] + (1,))
            if "COLOR_0" in attributes:
                vc = g.accessor(attributes["COLOR_0"]).astype(float)
                rgb = rgb * _srgb(vc[:, :3])[tris]
            rgba = np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 1.0)], axis=-1)
            if m["alpha"] < 0.05:                               # (made to be unseen)
                continue
            data = np.concatenate([pos, n, rgba, uv], axis=-1).reshape(-1, 12)
            data[:, [1, 2, 4, 5]] *= -1.0                       # (y up, z to the viewer -> y down, z away)
            pieces.append({"data": data, "texture": m["texture"], "metallic": m["metallic"], "roughness": m["roughness"],
                           "cutoff": m["cutoff"]})
    if not pieces:
        raise ModelError("檔案裡沒有任何面")
    return pieces


def read(path):
    try:
        return read_obj(path) if str(path).lower().endswith(".obj") else read_gltf(path)
    except ModelError:
        raise
    except OSError as exc:
        raise ModelError(f"讀不到檔案：{exc}") from None
    except (ValueError, KeyError, IndexError, TypeError, struct.error) as exc:
        raise ModelError(f"模型檔的內容看不懂（{type(exc).__name__}: {exc}）") from None


# -- .kmodel ---------------------------------------------------------------------------------------------------------------------
def _fitted(data):
    """A texture's bytes, made smaller when it is bigger than TEXTURE_MAX; None when it is no picture."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            if max(im.size) <= TEXTURE_MAX and im.format in ("PNG", "JPEG"):
                return data
            im = im.convert("RGBA")
            im.thumbnail((TEXTURE_MAX, TEXTURE_MAX))
            out = io.BytesIO()
            im.save(out, "PNG")
            return out.getvalue()
    except Exception:
        return None


def convert(path, folder):
    """Read model file path and keep it as one .kmodel file in folder. Returns (its path, (x, y, z) sizes with the longest 1)."""
    pieces = read(path)
    every = np.concatenate([p["data"][:, :3] for p in pieces])
    if not np.isfinite(every).all():
        raise ModelError("模型裡有不是數字的座標")
    lo, hi = every.min(axis=0), every.max(axis=0)
    longest = float((hi - lo).max())
    if longest <= 0:
        raise ModelError("模型沒有大小")
    size = [float(x) for x in (hi - lo) / longest]
    arrays, meta, textures = {}, [], {}
    for i, p in enumerate(pieces):
        data = p["data"]
        data[:, :3] = (data[:, :3] - (lo + hi) / 2.0) / longest
        data[:, 3:6] = _unit(data[:, 3:6])
        arrays[f"mesh{i}"] = np.nan_to_num(data).astype("f4")
        texture = None
        if p["texture"] is not None:
            key = hashlib.sha1(p["texture"]).hexdigest()
            if key not in textures:
                fitted = _fitted(p["texture"])
                textures[key] = None if fitted is None else f"texture{len(textures)}"
                if fitted is not None:
                    arrays[textures[key]] = np.frombuffer(fitted, np.uint8)
            texture = textures[key]
        meta.append({"uv": bool(np.ptp(data[:, 10:12], axis=0).max() > 1e-6), "texture": texture, "metallic": float(np.clip(p["metallic"], 0.0, 1.0)),
                     "roughness": float(np.clip(p["roughness"], 0.0, 1.0)), "cutoff": float(p["cutoff"])})
    arrays["meta"] = np.frombuffer(json.dumps({"size": size, "pieces": meta}).encode(), np.uint8)
    out = io.BytesIO()
    np.savez_compressed(out, **arrays)
    raw = out.getvalue()
    mark = hashlib.sha1(b"".join(arrays[k].tobytes() for k in sorted(arrays))).hexdigest()[:10]    # (the same model: the same file)
    stem = os.path.splitext(os.path.basename(path))[0][:60] or "model"
    os.makedirs(folder, exist_ok=True)
    kept = os.path.join(folder, f"{stem}-{mark}{SUFFIX}").replace("\\", "/")
    if not os.path.exists(kept):
        with open(kept + ".part", "wb") as f:
            f.write(raw)
        os.replace(kept + ".part", kept)
    return kept, size


_loaded = {}                 # path -> (mtime, model)
_made = {}                   # (path, mtime, sizes, tint) -> (mesh, ranges)
MAX_LOADED, MAX_MADE = 8, 12


def load(path):
    """{"size": (x, y, z), "pieces": [{"data", "texture": QImage or None, "metallic", "roughness", "cutoff"}]} of a .kmodel, kept."""
    from PySide6.QtGui import QImage
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        raise ModelError(f"找不到模型檔：{os.path.basename(path)}") from None
    got = _loaded.get(path)
    if got is None or got[0] != stamp:
        try:
            with np.load(path, allow_pickle=False) as z:
                meta = json.loads(z["meta"].tobytes().decode())
                pictures = {}
                pieces = []
                for i, m in enumerate(meta["pieces"]):
                    name = m["texture"]
                    if name and name not in pictures:
                        img = QImage.fromData(z[name].tobytes())
                        pictures[name] = None if img.isNull() else img
                    pieces.append(dict(m, data=z[f"mesh{i}"], texture=pictures.get(name) if name else None))
        except (OSError, ValueError, KeyError) as exc:
            raise ModelError(f"模型檔壞了：{os.path.basename(path)}（{exc}）") from None
        while len(_loaded) >= MAX_LOADED:
            _loaded.pop(next(iter(_loaded)))
        got = _loaded[path] = (stamp, {"size": meta["size"], "pieces": pieces})
    return got[1]


def mesh(path, w, h, d, tint=(1.0, 1.0, 1.0)):
    """(the mesh (n, 12) of a .kmodel made w x h x d px, its colours times tint; [(first row, rows, piece)]), kept."""
    model = load(path)
    key = (path, _loaded[path][0], round(w, 3), round(h, 3), round(d, 3), tuple(round(float(x), 4) for x in tint[:3]))
    got = _made.get(key)
    if got is None:
        data = np.concatenate([p["data"] for p in model["pieces"]]).astype("f4")
        unit = np.array(model["size"], float)
        k = np.where(unit > 1e-6, np.array([w, h, d], float) / np.maximum(unit, 1e-6), max(w, h, d))
        k = np.maximum(k, 1e-6)
        data[:, :3] *= k.astype("f4")
        data[:, 3:6] = _unit(data[:, 3:6] / k)
        data[:, 6:9] *= np.array(tint[:3], "f4")
        ranges, at = [], 0
        for p in model["pieces"]:
            ranges.append((at, len(p["data"]), p))
            at += len(p["data"])
        while len(_made) >= MAX_MADE:
            _made.pop(next(iter(_made)))
        got = _made[key] = (data, ranges)
    return got
