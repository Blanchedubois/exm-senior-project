"""python -m exm_explorer [scenario.json]: open the GUI."""

import importlib.util
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if importlib.util.find_spec("exm_explorer.app") is None:
        print("The ExM Explorer window is not built yet (it arrives in milestone 3).\n"
              "For now: run the tests with  python -m pytest -q")
        return 0
    from .app import main as app_main
    return app_main(argv)


if __name__ == "__main__":
    sys.exit(main())
