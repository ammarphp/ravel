#!/usr/bin/env python3
"""Checkout entry point for local recorded-run diagnostics."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from ravel.controller.diagnostics.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
