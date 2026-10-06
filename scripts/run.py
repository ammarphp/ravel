#!/usr/bin/env python3
"""Run a source Ravel module without installing it in a native tool environment."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "src/ravel/_bootstrap.py"),
                  run_name="__main__")
