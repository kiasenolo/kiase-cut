"""python -m tesetoa [project.tesetoa.json | draft_content.json]"""
import sys


def main():
    from .ui.main_window import run
    sys.exit(run(sys.argv))


if __name__ == "__main__":
    main()
