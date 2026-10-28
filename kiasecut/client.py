"""Talk to the engine process (engine.py) from the UI or command line."""
import base64
import json
import os
import subprocess
import sys
from multiprocessing import shared_memory

from . import mltlib


class EngineClient:
    def __init__(self, max_w=1920, max_h=1080):
        env = mltlib.env()
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
        if getattr(sys, "frozen", False):       # built: a program of its own (packaging/kiasecut.spec)
            cmd = [os.path.join(os.path.dirname(sys.executable), "engine",
                                "kiasecut-engine" + (".exe" if sys.platform == "win32" else ""))]
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"     # (another built program, not this one again)
        else:
            cmd = [sys.executable, "-m", "kiasecut.engine"]
        self.proc = subprocess.Popen(cmd, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                     encoding="utf-8", bufsize=1,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.shm = shared_memory.SharedMemory(create=True, size=max_w * max_h * 4)
        hello = self._read()
        if not hello.get("ready"):
            raise RuntimeError(f"engine failed to start: {hello}")

    def _read(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("engine exited")
            line = line.strip()
            if line.startswith("{"):            # MLT may print plain text on stdout too
                return json.loads(line)

    def call(self, **req):
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        reply = self._read()
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply

    def load(self, xml):
        return self.call(cmd="load", xml=xml)

    def frame(self, pos, w, h, audio=False):
        """(rgba bytes, w, h, pcm bytes or None) for frame pos."""
        r = self.call(cmd="frame", pos=pos, w=w, h=h, audio=audio, shm=self.shm.name)
        pixels = bytes(self.shm.buf[: r["w"] * r["h"] * 4])
        return pixels, r["w"], r["h"], base64.b64decode(r["pcm"]) if "pcm" in r else None

    def media_frame(self, path, us, fps, w, h):
        """(rgba bytes, w, h) of a media file at source time us."""
        r = self.call(cmd="media", path=path, us=us, fps=fps, w=w, h=h, shm=self.shm.name)
        return bytes(self.shm.buf[: r["w"] * r["h"] * 4]), r["w"], r["h"]

    def export(self, xml, dest, on_progress=None, **opts):
        """Render xml to the file dest. opts: encoder settings and the frame range
        ("in" / "out", inclusive)."""
        self.proc.stdin.write(json.dumps({"cmd": "export", "xml": xml, "out": dest, "opts": opts}) + "\n")
        self.proc.stdin.flush()
        while True:
            r = self._read()
            if "error" in r:
                raise RuntimeError(r["error"])
            if "done" in r:
                return r
            if on_progress:
                on_progress(r["progress"])

    def close(self):
        try:
            self.proc.stdin.write('{"cmd": "quit"}\n')
            self.proc.stdin.flush()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        self.shm.close()
        self.shm.unlink()
