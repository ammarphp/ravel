#!/usr/bin/env python3
"""Append acquired SM PDF-set pins to a PDF-set catalogue without network access.

Usage: python scripts/setup/build_sm_pdf_sets.py --catalogue native/setup/pdf-sets.json \
    --pins native/setup/sm-pins.json --out native/setup/pdf-sets.json

The pin document (``native/setup/sm-pins.schema.json``) carries each set's LHAPDF identifier, size,
sha256 and use as acquired. Existing catalogue rows are kept as they are; the new rows are appended
with digest status ``single-download``. The set list and every refusal live in
``ravel.setup.manifest``, so this script and the catalogue validator cannot disagree.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ravel.setup import manifest  # noqa: E402


def build(catalogue, pins):
    return manifest.append_sm_pdf_sets(catalogue, pins)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--pins", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    result = build(json.loads(args.catalogue.read_text(encoding="utf-8")),
                   json.loads(args.pins.read_text(encoding="utf-8")))
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
