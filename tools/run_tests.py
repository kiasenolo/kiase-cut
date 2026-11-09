"""Run the tests, one file in a process of its own, and sum up.

    python tools/run_tests.py [test_name ...] [-t SECONDS]      (no names: every tests/test_*.py)

All of them in one process (`unittest discover`) never finished: a test file that leaves a widget or a thread to the end of the process
crashes it there (a segmentation fault, an abort), and the crash takes the whole run's summary with it. Here a file whose tests all passed but
whose process then crashed is told apart ("ok, crashed at exit") from one that failed, and one that hangs is stopped after the time given."""
import glob
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_one(name, timeout):
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"), KIASECUT_NO_WIKI_DEMOS="1",
               PYTHONPATH=ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
    start = time.time()
    try:
        proc = subprocess.run([sys.executable, "-m", "unittest", f"tests.{name}"], cwd=ROOT, env=env, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return "hang", f"no end after {timeout} s", time.time() - start, ""
    text = proc.stderr + proc.stdout
    ran = re.search(r"^Ran (\d+) tests?", text, re.M)
    passed = bool(re.search(r"^OK", text, re.M))
    if proc.returncode == 0:
        return "ok", ran.group(0) if ran else "", time.time() - start, text
    if passed:
        return "ok-crash", f"{ran.group(0)}, then the process ended with {proc.returncode}", time.time() - start, text
    failed = re.search(r"^FAILED.*$", text, re.M)
    return "FAIL", (failed.group(0) if failed else f"exit {proc.returncode}, no result (crashed?)"), time.time() - start, text


def main(argv):
    timeout = 300
    if "-t" in argv:
        i = argv.index("-t")
        timeout = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    names = [os.path.basename(a)[:-3] if a.endswith(".py") else a for a in argv] or \
        [os.path.basename(f)[:-3] for f in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py")))]
    bad = 0
    for name in names:
        status, note, secs, text = run_one(name, timeout)
        if status in ("FAIL", "hang"):
            bad += 1
        if status != "ok":
            print(f"{status:9} {name} ({secs:.0f} s) {note}", flush=True)
            if status == "FAIL":
                print("\n".join("          " + ln for ln in text.strip().splitlines()[-8:]))
    print(f"\n{len(names)} files, {bad} failed or hung")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
