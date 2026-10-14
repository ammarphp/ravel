#!/usr/bin/env python3
"""Install RAVEL's toolchain. Normally started by scripts/setup/install.sh.

Uses only the Python standard library, so it runs under the Miniforge base
interpreter before any RAVEL dependency exists.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ravel.setup.installer import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(repo=ROOT))
