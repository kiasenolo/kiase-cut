"""python -m kiasecut [project.kiasecut.json | draft_content.json]
python -m kiasecut render | marks ...   (without a window: cli.py)"""
import sys


def main():
    from . import cli
    if len(sys.argv) > 1 and sys.argv[1] in cli.COMMANDS:
        sys.exit(cli.main(sys.argv[1:]))
    from .ui.main_window import run
    sys.exit(run(sys.argv))


if __name__ == "__main__":
    main()
