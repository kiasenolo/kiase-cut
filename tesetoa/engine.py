"""Render engine process.

The UI never loads MLT itself: an engine crash cannot take the editor down, and MLT's Qt
(from Kdenlive/Shotcut) never meets PySide6's Qt in one process.

Protocol: one JSON object per line on stdin; one JSON reply per line on stdout.
Pixels go through shared memory, audio as base64 PCM (s16, stereo, 48 kHz).
  {"cmd": "load", "xml": path}                          -> {length, fps, width, height}
  {"cmd": "frame", "pos": n, "w": w, "h": h,
   "audio": bool, "shm": name}                          -> {pos, w, h, [pcm]}
  {"cmd": "export", "xml": path, "out": path, ...}      -> {progress} lines, then {done}
  {"cmd": "quit"}
"""
import base64
import ctypes as C
import json
import sys
import time
from multiprocessing import shared_memory

from .mltlib import AUDIO_S16, IMAGE_RGBA, P, Mlt

RATE, CHANNELS = 48000, 2


class Engine:
    def __init__(self):
        self.m = Mlt()
        self.profile = None
        self.producer = None
        self.shm = {}

    def load(self, xml):
        m = self.m
        if self.producer:
            m.producer_close(self.producer)
        self.profile = m.profile_init(None)
        self.profile.contents.is_explicit = 0       # let the document set the profile
        self.producer = m.factory_producer(self.profile, b"xml", xml.encode())
        if not self.producer:
            raise RuntimeError(f"MLT could not load {xml}")
        pr = self.profile.contents
        return {"length": m.producer_get_length(self.producer),
                "fps": pr.frame_rate_num / pr.frame_rate_den, "width": pr.width, "height": pr.height}

    def frame(self, pos, w, h, audio, shm):
        m = self.m
        m.producer_seek(self.producer, pos)
        fr = P()
        m.service_get_frame(self.producer, C.byref(fr), 0)
        buf = C.POINTER(C.c_uint8)()
        fmt, cw, ch = C.c_int(IMAGE_RGBA), C.c_int(w), C.c_int(h)
        m.frame_get_image(fr, C.byref(buf), C.byref(fmt), C.byref(cw), C.byref(ch), 0)
        size = cw.value * ch.value * 4
        if shm not in self.shm:
            self.shm[shm] = shared_memory.SharedMemory(name=shm)
        mem = self.shm[shm]
        C.memmove((C.c_char * size).from_buffer(mem.buf), buf, size)
        reply = {"pos": pos, "w": cw.value, "h": ch.value}
        if audio:
            pr = self.profile.contents
            n = C.c_int(m.audio_samples(pr.frame_rate_num / pr.frame_rate_den, RATE, pos))
            abuf, afmt = P(), C.c_int(AUDIO_S16)
            freq, chans = C.c_int(RATE), C.c_int(CHANNELS)
            m.frame_get_audio(fr, C.byref(abuf), C.byref(afmt), C.byref(freq), C.byref(chans), C.byref(n))
            reply["pcm"] = base64.b64encode(C.string_at(abuf, n.value * chans.value * 2)).decode()
        m.frame_close(fr)
        return reply

    def export(self, xml, out, opts, emit):
        m = self.m
        info = self.load(xml)
        cons = m.factory_consumer(self.profile, b"avformat", out.encode())
        m.set(cons, vcodec=opts.get("vcodec", "libx264"), crf=opts.get("crf", 18),
              preset=opts.get("preset", "medium"), acodec=opts.get("acodec", "aac"),
              ab=opts.get("ab", "320k"), ar=RATE, channels=CHANNELS,
              real_time=-max(1, opts.get("threads", 4)), terminate_on_pause=1)
        m.set(self.producer, **{"in": 0, "out": info["length"] - 1})
        m.producer_seek(self.producer, 0)
        m.consumer_connect(cons, self.producer)
        m.consumer_start(cons)
        t0 = time.time()
        while not m.consumer_is_stopped(cons):
            time.sleep(0.25)
            emit({"progress": m.producer_position(self.producer) / info["length"],
                  "elapsed": time.time() - t0})
        m.consumer_close(cons)
        return {"done": out, "elapsed": time.time() - t0}


def main():
    eng = Engine()
    out = sys.stdout

    def emit(obj):
        out.write(json.dumps(obj) + "\n")
        out.flush()

    emit({"ready": True})
    for line in sys.stdin:
        req = json.loads(line)
        cmd = req.get("cmd")
        try:
            if cmd == "load":
                emit(eng.load(req["xml"]))
            elif cmd == "frame":
                emit(eng.frame(req["pos"], req["w"], req["h"], req.get("audio", False), req["shm"]))
            elif cmd == "export":
                emit(eng.export(req["xml"], req["out"], req.get("opts", {}), emit))
            elif cmd == "quit":
                break
        except Exception as exc:            # report and keep serving
            emit({"error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
