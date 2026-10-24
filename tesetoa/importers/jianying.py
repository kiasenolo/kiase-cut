"""Import a decrypted Jianying (剪映) draft_content.json into a tesetoa project.

Jianying stores keyframe times relative to the material's time zero (clip start minus
source start); tesetoa keeps them relative to the clip start.
"""
import json

from .. import curves, project


def _kfs(seg):
    return {k["property_type"]: k["keyframe_list"]
            for k in seg.get("common_keyframes", []) if k.get("keyframe_list")}


class Importer:
    def __init__(self, draft, remap=()):
        self.d = draft
        self.remap = list(remap)
        self.registry = {}
        self.warnings = []
        self._n = 0
        self._collect(draft)

    def _collect(self, draft):
        """Compound drafts may live in any ancestor's material lists."""
        for kind, lst in draft.get("materials", {}).items():
            if isinstance(lst, list):
                for x in lst:
                    if isinstance(x, dict) and "id" in x:
                        self.registry.setdefault(kind, {}).setdefault(x["id"], x)
                        if kind == "drafts" and x.get("draft"):
                            self._collect(x["draft"])

    def _mats(self, draft, kind):
        return {**self.registry.get(kind, {}),
                **{v["id"]: v for v in draft.get("materials", {}).get(kind, [])}}

    def _path(self, p):
        p = (p or "").replace("\\", "/")
        for old, new in self.remap:
            if p.startswith(old):
                return new + p[len(old):]
        return p

    def _id(self):
        self._n += 1
        return f"c{self._n}"

    # -- per segment ----------------------------------------------------------------------
    def _param(self, kfs, ptype, static, shift):
        return curves.from_jianying(kfs[ptype], shift) if ptype in kfs else static

    def _transform(self, seg, kfs, shift, is_text, global_alpha=1.0):
        clip = seg.get("clip") or {}
        sc, tf = clip.get("scale", {}), clip.get("transform", {})
        alpha_key = "KFTypeGlobalAlpha" if is_text else "KFTypeAlpha"
        opacity = self._param(kfs, alpha_key, clip.get("alpha", 1.0) * global_alpha, shift)
        t = {
            "x": self._param(kfs, "KFTypePositionX", tf.get("x", 0.0), shift),
            "y": self._param(kfs, "KFTypePositionY", tf.get("y", 0.0), shift),
            # an empty uniform_scale still scales uniformly (checked against an export)
            "scale": self._param(kfs, "KFTypeScaleX", sc.get("x", 1.0), shift),
            "rotation": self._param(kfs, "KFTypeRotation", clip.get("rotation", 0.0), shift),
            "opacity": opacity,
        }
        if (seg.get("uniform_scale") or {}).get("on", True) is False:
            t["scale_y"] = self._param(kfs, "KFTypeScaleY", sc.get("y", 1.0), shift)
        flip = clip.get("flip") or {}
        if flip.get("horizontal"):
            t["flip_h"] = True
        if flip.get("vertical"):
            t["flip_v"] = True
        return t

    def _mask(self, m, kfs, shift):
        kind = m.get("resource_type")
        if kind not in ("line", "mirror", "circle", "rectangle"):
            self.warnings.append(f"mask {m.get('name')!r} ({kind}) not supported")
            return None
        cfg = m.get("config", {})
        p = lambda name, key, default: self._param(kfs, "KFTypeCommonMask" + name,
                                                   cfg.get(key, default), shift)
        return {"kind": kind, "invert": bool(cfg.get("invert")),
                "cx": p("PositionX", "centerX", 0.0), "cy": p("PositionY", "centerY", 0.0),
                "w": p("SizeWidth", "width", 1.0), "h": p("SizeHeight", "height", 1.0),
                "rotation": p("Rotation", "rotation", 0.0), "feather": p("Feather", "feather", 0.0)}

    def _text(self, mat):
        c = json.loads(mat["content"])
        styles = c.get("styles") or [{}]

        def col(st):
            return st.get("fill", {}).get("content", {}).get("solid", {}).get("color", [1, 1, 1])[:3]

        spec = {
            "content": c["text"],
            "font_path": styles[0].get("font", {}).get("path") or mat.get("font_path"),
            "size": mat.get("font_size", styles[0].get("size", 5.0)),
            "color": col(styles[0]),
            "letter_spacing": mat.get("letter_spacing", 0.0),
            "line_spacing": mat.get("line_spacing", 0.0),
            "italic_deg": mat.get("italic_degree", 0) if any(s.get("italic") for s in styles) else 0,
        }
        if len(styles) > 1:
            spec["styles"] = [{"range": s.get("range"), "size": s.get("size"), "color": col(s),
                               "font_path": s.get("font", {}).get("path")} for s in styles]
        return spec

    def tracks(self, draft):
        vid, aud = self._mats(draft, "videos"), self._mats(draft, "audios")
        txt, drf = self._mats(draft, "texts"), self._mats(draft, "drafts")
        masks, fades = self._mats(draft, "common_mask"), self._mats(draft, "audio_fades")
        out = []
        for ti, tr in enumerate(draft.get("tracks", [])):
            kind = tr.get("type")
            if kind not in ("video", "text", "audio"):
                if tr.get("segments"):
                    self.warnings.append(f"{kind} track not imported")
                continue
            clips = []
            for seg in tr.get("segments", []):
                rng = seg["target_timerange"]
                src = seg.get("source_timerange") or {}
                c = {"id": self._id(), "start_us": rng.get("start", 0), "duration_us": rng["duration"],
                     "source_start_us": src.get("start", 0)}
                shift = -c["source_start_us"]
                kfs = _kfs(seg)
                mid = seg["material_id"]
                refs = seg.get("extra_material_refs", [])
                if mid in txt:
                    mat = txt[mid]
                    c.update(type="text", text=self._text(mat), name=json.loads(mat["content"])["text"][:20])
                    ga = mat.get("global_alpha", 1.0)
                    c["transform"] = self._transform(seg, kfs, shift, True, ga)
                elif mid in vid:
                    v = vid[mid]
                    c["transform"] = self._transform(seg, kfs, shift, False)
                    sub = [drf[r] for r in refs if r in drf]
                    if sub:
                        inner = sub[0]["draft"]
                        cc = inner.get("canvas_config", {})
                        c.update(type="compound", name=v.get("material_name") or "compound",
                                 compound={"width": cc.get("width", 1920), "height": cc.get("height", 1080),
                                           "duration_us": inner.get("duration"),
                                           "tracks": self.tracks(inner)})
                    elif v.get("path"):
                        c.update(type="image" if v["type"] == "photo" else "video",
                                 name=v.get("material_name") or v["path"].split("/")[-1],
                                 media={"path": self._path(v["path"]), "width": v["width"],
                                        "height": v["height"]})
                        if v["type"] != "photo":
                            c["media"]["duration_us"] = v.get("duration")
                        if c["type"] == "video":
                            c["volume"] = self._param(kfs, "KFTypeVolume", seg.get("volume", 1.0), shift)
                    else:
                        self.warnings.append(f"video segment without media skipped ({mid})")
                        continue
                    for r in refs:
                        if r in masks:
                            c["mask"] = self._mask(masks[r], kfs, shift)
                elif mid in aud:
                    a = aud[mid]
                    c.update(type="audio", name=a.get("name") or a["path"].split("/")[-1],
                             media={"path": self._path(a["path"]), "duration_us": a.get("duration")},
                             volume=self._param(kfs, "KFTypeVolume", seg.get("volume", 1.0), shift))
                    fd = [fades[r] for r in refs if r in fades]
                    if fd:
                        c["fade_in_us"] = fd[0].get("fade_in_duration", 0)
                        c["fade_out_us"] = fd[0].get("fade_out_duration", 0)
                else:
                    continue
                clips.append(c)
            out.append({"id": f"t{ti}", "kind": kind, "name": f"{kind} {ti + 1}", "clips": clips})
        return out

    def run(self):
        p = project.new(self.d["canvas_config"]["width"], self.d["canvas_config"]["height"],
                        float(self.d["fps"]))
        p["tracks"] = self.tracks(self.d)
        p["duration_us"] = self.d.get("duration") or project.end_us(p["tracks"])
        return project.normalize(p)


def import_draft(path, remap=()):
    with open(path, encoding="utf-8") as fh:
        draft = json.load(fh)
    imp = Importer(draft, remap)
    return imp.run(), imp.warnings
