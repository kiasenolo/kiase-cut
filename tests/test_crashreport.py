import os
import subprocess
import sys
import tempfile
import unittest

from kiasecut import crashreport, recovery

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def run(code, auto):
    return subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {ROOT!r})\n{code}"], capture_output=True, text=True,
                          env={**os.environ, "KIASECUT_X": "1"}, cwd=auto, timeout=60)


class CrashReportTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.auto = os.path.join(self.root, "auto-save")
        self.reports = os.path.join(self.root, "crashReport")

    def files(self, prefix=""):
        return sorted(n for n in os.listdir(self.reports) if n.startswith(prefix)) if os.path.isdir(self.reports) else []

    def test_the_folder_is_beside_the_autosave_folder(self):
        self.assertEqual(crashreport.folder(self.auto), self.reports)

    def test_a_native_crash_leaves_a_report_with_the_stack(self):
        res = run(f"from kiasecut import recovery\nrecovery.begin({self.auto!r})\nrecovery.note({self.auto!r}, project='/a/b.kiasecut')\n"
                  "def boom():\n    import ctypes; ctypes.string_at(0)\nboom()\n", self.root)
        self.assertNotEqual(res.returncode, 0)
        got = self.files("crash-")
        self.assertEqual(len(got), 1)
        text = read(os.path.join(self.reports, got[0]))
        for want in ("KiaseCut", "KIASECUT_X=1", "project: /a/b.kiasecut", "in boom"):
            self.assertIn(want, text)
        self.assertTrue("Fatal Python error" in text or "Windows fatal exception" in text, text)      # (faulthandler's words on Windows)

    def test_a_normal_exit_leaves_no_report(self):
        res = run(f"from kiasecut import recovery\nrecovery.begin({self.auto!r})\nrecovery.end({self.auto!r})\n", self.root)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.files(), [])

    def test_an_exception_nobody_catches_gets_a_report_once(self):
        res = run(f"from kiasecut import recovery\nrecovery.begin({self.auto!r})\nrecovery.note({self.auto!r}, project='p1')\n"
                  "import threading\n"
                  "def f():\n    raise ValueError('bad')\n"
                  "for _ in range(3):\n    t = threading.Thread(target=f, name='worker'); t.start(); t.join()\n"
                  "raise RuntimeError('top')\n", self.root)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("RuntimeError", res.stderr)                    # (the usual hook still runs)
        got = self.files("exception-")
        self.assertEqual(len(got), 2)                                 # (the thread's three alike: one)
        text = "".join(read(os.path.join(self.reports, n)) for n in got)
        for want in ("ValueError: bad", "thread worker", "RuntimeError: top", "project: p1"):
            self.assertIn(want, text)

    def test_a_report_left_by_a_killed_program_says_so(self):
        os.makedirs(self.reports)
        pid = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True).stdout.strip()
        old = os.path.join(self.reports, f"crash-20250101-000000-{pid}.txt")
        with open(old, "w") as fh:
            fh.write("KiaseCut\n")
        recovery.begin(self.auto)
        try:
            self.assertIn(crashreport.ENDED, read(old))
        finally:
            recovery.end(self.auto)


if __name__ == "__main__":
    unittest.main()
