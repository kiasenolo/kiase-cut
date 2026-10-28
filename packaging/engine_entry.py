"""Entry point of the built render engine (kiasecut.spec): kiasecut.engine, started by the
editor (client.py) with the environment mltlib.env() gives it."""
import multiprocessing
import runpy

if __name__ == "__main__":
    multiprocessing.freeze_support()
    runpy.run_module("kiasecut.engine", run_name="__main__", alter_sys=True)
