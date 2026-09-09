"""Run a Ravel module using this installation with the chosen interpreter."""
from pathlib import Path
import runpy
import sys


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or not args[0].startswith("ravel."):
        raise SystemExit("usage: python scripts/run.py ravel.DOMAIN.MODULE [arguments]")
    package_parent = Path(__file__).resolve().parent.parent
    # An installed interpreter already has this directory on sys.path. Adding
    # it twice duplicates distribution discovery and invalidates runtime custody.
    if not any(Path(path or ".").resolve() == package_parent for path in sys.path):
        sys.path.insert(0, str(package_parent))
    module, *arguments = args
    sys.argv = [module, *arguments]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
