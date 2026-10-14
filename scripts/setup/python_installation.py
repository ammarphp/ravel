#!/usr/bin/env python3
"""From any cwd: python3.12 /path/to/ravel/scripts/setup/python_installation.py."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.python_installation import main
if __name__ == '__main__':
    raise SystemExit(main(source_root=ROOT))
