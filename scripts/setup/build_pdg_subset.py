#!/usr/bin/env python3
"""Build RAVEL's pinned PDG subset from the SQLite file bundled in the PDG ``pdg`` wheel.

Usage: python -I scripts/setup/build_pdg_subset.py --sqlite pdg.sqlite --wheel pdg-2026.0-py3-none-any.whl

Writes ``src/ravel/data/reference/pdg/pdg-subset.json`` (the quantities listed in ``QUANTITIES``,
read row by row from the database) and ``SOURCE.json`` (edition, release time, citation, licence and the
sha256 of the wheel, the database and the subset). Nothing is typed in by hand: every value comes from
the database row named by its PDG identifier. The data are CC BY 4.0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

OUT = Path(__file__).resolve().parents[2] / "src/ravel/data/reference/pdg"

# (key, PDG identifier). Identifiers are PDG's own: S = boson or lepton, Q = quark; M = mass, W = width.
QUANTITIES = [
    ("electron.mass", "S003M"), ("muon.mass", "S004M"), ("tau.mass", "S035M"),
    ("d_quark.mass", "Q001M"), ("u_quark.mass", "Q002M"), ("s_quark.mass", "Q003M"),
    ("c_quark.mass", "Q004M"), ("b_quark.mass", "Q005M"),
    ("top_quark.mass_direct", "Q007TP"), ("top_quark.pole_mass_cross_section", "Q007TP4"),
    ("top_quark.width", "Q007W"),
    ("w_boson.mass", "S043M"), ("w_boson.width", "S043W"),
    ("z_boson.mass", "S044M"), ("z_boson.width", "S044W"),
    ("higgs_boson.mass", "S126M"), ("higgs_boson.width", "S126W"),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(sqlite_path, wheel_path):
    db = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    info = dict(db.execute("select name, value from pdginfo"))
    rows = {}
    for key, pdgid in QUANTITIES:
        row = db.execute(
            "select d.pdgid, i.description, d.value_type, d.value, d.error_positive, d.error_negative, "
            "d.unit_text, d.edition, d.confidence_level from pdgdata d join pdgid i on i.pdgid = d.pdgid "
            "where d.pdgid = ? and d.in_summary_table = 1", (pdgid,)).fetchall()
        if len(row) != 1:
            raise SystemExit(f"{pdgid}: expected one summary-table row, found {len(row)}")
        _, description, value_type, value, plus, minus, unit, edition, cl = row[0]
        rows[key] = {"pdgid": pdgid, "description": description, "value": value, "error_positive": plus,
                     "error_negative": minus, "unit": unit, "value_type": value_type, "edition": edition,
                     "confidence_level": cl}
    return info, rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--wheel-name", help="the wheel's published file name when the local copy is renamed")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    info, rows = build(args.sqlite, args.wheel)
    wheel_name = args.wheel_name or Path(args.wheel).name
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    subset = {"schema_version": 1, "kind": "ravel-pdg-subset", "edition": info["edition"], "quantities": rows}
    text = json.dumps(subset, indent=1, sort_keys=True) + "\n"
    (out / "pdg-subset.json").write_text(text, encoding="utf-8")
    source = {"schema_version": 1, "kind": "ravel-pdg-source", "edition": info["edition"],
              "data_release_timestamp": info["data_release_timestamp"], "citation": info["citation"],
              "license": info["license"], "schema": info["schema_version"],
              "origin": {"package": "pdg", "version": wheel_name.split("-")[1],
                         "url": "https://pypi.org/project/pdg/", "wheel": wheel_name,
                         "wheel_sha256": sha256(args.wheel), "wheel_size": Path(args.wheel).stat().st_size,
                         "database_member": "pdg/pdg.sqlite", "database_sha256": sha256(args.sqlite),
                         "database_size": Path(args.sqlite).stat().st_size},
              "subset_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
              "regenerate": "python -I scripts/setup/build_pdg_subset.py --sqlite <pdg.sqlite from the wheel> --wheel <wheel>"}
    (out / "SOURCE.json").write_text(json.dumps(source, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"subset_sha256": source["subset_sha256"], "quantities": len(rows)}))


if __name__ == "__main__":
    main()
