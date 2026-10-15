#!/usr/bin/env python3
"""Build RAVEL's pinned PDG subset from the SQLite file bundled in the PDG ``pdg`` wheel.

Usage: python -I scripts/setup/build_pdg_subset.py --sqlite pdg.sqlite --wheel pdg-2026.0-py3-none-any.whl

Writes ``src/ravel/data/reference/pdg/pdg-subset.json`` (the quantities listed in ``QUANTITIES`` and
``EW_QUANTITIES``, read row by row from the database), ``SOURCE.json`` (edition, release time, citation,
licence and the sha256 of the wheel, the database and the subset) and the electroweak input bundle
``src/ravel/data/sm/ew-inputs.json`` projected from those rows. Nothing is typed in by hand: every value
comes from the database row named by its PDG identifier. The data are CC BY 4.0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

OUT = Path(__file__).resolve().parents[2] / "src/ravel/data/reference/pdg"
EW_OUT = Path(__file__).resolve().parents[2] / "src/ravel/data/sm/ew-inputs.json"

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

# (key, PDG identifier, summary-table row). A row is selected by its identifier and table only,
# never by matching its description: descriptions of unrelated quantities read alike. False marks a
# fit value that the Particle Listings carry and the Summary Tables do not repeat.
#
# The database holds no row for the strong coupling at the Z mass, the Fermi constant, the
# fine-structure constant or the hadronic vacuum polarisation, and only per-flavour lepton asymmetry
# parameters; none of these is listed. The pole forward-backward asymmetries are stored in percent
# with an empty unit on their summary rows and are not listed until that unit is carried through.
EW_QUANTITIES = [
    ("sin2theta_eff_lept", "S044SEF", True),
    ("z_pole.sigma_hadronic", "S044SH", True),
    ("z_pole.r_lepton", "S044R20", False), ("z_pole.r_b", "S044R18", False), ("z_pole.r_c", "S044R29", False),
    ("z_pole.a_b", "S044AB", True), ("z_pole.a_c", "S044AC", True),
]
# Electroweak-bundle key -> subset key.
EW_INPUTS = {"z_pole.gamma_z": "z_boson.width", **{key: key for key, _, _ in EW_QUANTITIES}}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _row(db, pdgid, summary=True):
    rows = db.execute(
        "select d.pdgid, i.description, d.value_type, d.value, d.error_positive, d.error_negative, "
        "d.unit_text, d.edition, d.confidence_level from pdgdata d join pdgid i on i.pdgid = d.pdgid "
        "where d.pdgid = ? and d.in_summary_table = ?", (pdgid, int(summary))).fetchall()
    if len(rows) != 1:
        table = "summary-table" if summary else "listing"
        raise SystemExit(f"{pdgid}: expected one {table} row, found {len(rows)}")
    pdgid, description, value_type, value, plus, minus, unit, edition, cl = rows[0]
    return {"pdgid": pdgid, "description": description, "value": value, "error_positive": plus,
            "error_negative": minus, "unit": unit, "value_type": value_type, "edition": edition,
            "confidence_level": cl}


def ew_inputs(rows, edition):
    """Project database rows into the compact EW-input interface.

    ``uncertainty`` is the larger of the row's two errors; the bundle states that rule. A row with
    no value, or without two positive errors, is refused, never given a zero uncertainty.
    """
    def quantity(key):
        row = rows[key]
        errors = (row["error_positive"], row["error_negative"])
        if row["value"] is None or None in errors or min(abs(error) for error in errors) <= 0:
            raise SystemExit(f"{key}: {row['pdgid']} has no value with a two-sided uncertainty")
        return {"pdgid": row["pdgid"], "value": row["value"], "uncertainty": max(abs(error) for error in errors),
                "unit": row["unit"]}
    return {"schema_version": 1, "kind": "ravel-ew-inputs", "edition": edition, "symmetrization": "max",
            "inputs": {key: quantity(source) for key, source in EW_INPUTS.items()},
            "m_w_variants": {rows["w_boson.mass"]["pdgid"]: quantity("w_boson.mass")}}


def build(sqlite_path, wheel_path):
    db = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    info = dict(db.execute("select name, value from pdginfo"))
    rows = {key: _row(db, pdgid) for key, pdgid in QUANTITIES}
    rows.update((key, _row(db, pdgid, summary)) for key, pdgid, summary in EW_QUANTITIES)
    mismatched = [key for key, row in rows.items() if row["edition"] != info["edition"]]
    if mismatched:
        raise SystemExit("rows do not match the database edition: " + ", ".join(mismatched))
    return info, rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--wheel-name", help="the wheel's published file name when the local copy is renamed")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--ew-out", default=str(EW_OUT))
    args = ap.parse_args(argv)
    info, rows = build(args.sqlite, args.wheel)
    bundle = ew_inputs(rows, info["edition"])  # refuses before any file is written
    wheel_name = args.wheel_name or Path(args.wheel).name
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    subset = {"schema_version": 1, "kind": "ravel-pdg-subset", "edition": info["edition"], "quantities": rows}
    text = json.dumps(subset, indent=1, sort_keys=True) + "\n"
    (out / "pdg-subset.json").write_text(text, encoding="utf-8")
    ew_out = Path(args.ew_out)
    ew_out.parent.mkdir(parents=True, exist_ok=True)
    ew_out.write_text(json.dumps(bundle, indent=1, sort_keys=True) + "\n", encoding="utf-8")
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
