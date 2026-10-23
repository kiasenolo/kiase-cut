"""Project model: plain JSON-able dicts, saved as *.tesetoa.json.

project  {format, version, width, height, fps, duration_us, tracks: [track]}  tracks[0] is
         the bottom layer; later tracks draw on top (as in Jianying).
track    {id, kind: video | text | audio, name, clips: [clip],
          muted, solo, hidden, gain}                        optional: muted / solo tracks
                     make no sound (solo silences the others), hidden ones draw nothing,
                     gain multiplies the track's sound
clip     {id, type: image | video | audio | text | compound, name,
          start_us, duration_us, source_start_us,
          media: {path, width, height, duration_us}         image / video / audio
          transform: {x, y, scale, rotation, opacity}       visual clips, Jianying units:
                     x, y in half-canvas units (y up), clockwise degrees
          mask: {kind, invert, cx, cy, w, h, rotation, feather} or None
          text: {content, font_path, size, color, letter_spacing, line_spacing,
                 italic_deg, styles}                        text clips
          volume, fade_in_us, fade_out_us                   clips with sound
          compound: {width, height, duration_us, tracks}    compound clips; children use
                     compound time, clip.source_start_us selects the window}
Numbers that animate are curve dicts, see curves.py.
"""
import json
import os

FORMAT = "tesetoa"
VERSION = 1
DEFAULT_FONT = next((f for f in (r"C:\Windows\Fonts\msjh.ttc",
                                 "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
                                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
                     if os.path.exists(f)), None)


def new(width=1920, height=1080, fps=60.0):
    return {"format": FORMAT, "version": VERSION, "width": width, "height": height,
            "fps": fps, "duration_us": 0, "tracks": []}


def load(path):
    with open(path, encoding="utf-8") as fh:
        p = json.load(fh)
    if p.get("format") != FORMAT:
        raise ValueError(f"{path} is not a tesetoa project")
    return p


def save(p, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(p, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)          # never leave a half-written project behind


def end_us(tracks):
    return max((c["start_us"] + c["duration_us"] for t in tracks for c in t["clips"]), default=0)


def refresh_duration(p):
    p["duration_us"] = end_us(p["tracks"])


def walk_clips(tracks):
    """Yield every clip, descending into compound clips."""
    for t in tracks:
        for c in t["clips"]:
            yield c
            if c.get("compound"):
                yield from walk_clips(c["compound"]["tracks"])


def sounds(track, tracks):
    """Gain of a track's sound (0 when muted, or when another track of its level is solo)."""
    if track.get("muted"):
        return 0.0
    if any(t.get("solo") for t in tracks) and not track.get("solo"):
        return 0.0
    return float(track.get("gain", 1.0))


def visible(track):
    return not track.get("hidden")
