"""Citations for physics-critical numbers and pinned PDG/Higgs reference contracts.

A number that sets a physical result (a mass, a width, a coupling, a luminosity, a cross section, an
efficiency or a branching ratio) must say where it came from. ``check_document`` walks any JSON-like
document and returns one finding per physics-critical number that has no citation, naming its field path
(for example ``particles[2].mass``). A number that cites a PDG identifier is also compared with the pinned
subset and reported if it disagrees by more than its stated or PDG uncertainty.

    python -m ravel.validation.constants_manifest DOC.json [--pdg]   # exit 1 on any finding
    python -m ravel.validation.constants_manifest --verify-subset    # exit 1 if the subset checksum differs

Typed Higgs tables additionally resolve citation keys, declared absolute uncertainty envelopes and
row-derived ratios. Their acquisition hold and schema live in ``data/knowledge/higgs/``.
``load_higgs_tables`` checks local primary/table pins and rejects synthetic fixtures by default.

The PDG subset and its provenance are ``src/ravel/data/reference/pdg/``: edition, release time, source wheel
and database digests, and the subset's own sha256, all from ``SOURCE.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

REFERENCE = Path(__file__).resolve().parents[1] / "data/reference/pdg"
HIGGS_REFERENCE = Path(__file__).resolve().parents[1] / "data/knowledge/higgs"

CRITICAL = re.compile(
    r"(^|_)(mass|width|gamma|lifetime|alpha_s|alphas|alpha_em|sin2theta\w*|g_f|k_factor|luminosity|lumi|"
    r"cross_section|xsec|sigma|efficiency|acceptance|branching_ratio|br)(_|$)", re.I)
# Keys that, in the same mapping, count as a citation for any number beside them.
CITATION_KEYS = ("source", "sources", "citation", "reference", "references", "provenance", "pdg_ref", "pdgid",
                 "record", "hepdata", "inspire", "doi", "arxiv", "derivation", "input_ref")
# Units PDG reports that a document may state differently.
SCALE_TO_PDG = {("GeV", "MeV"): 1e3, ("MeV", "GeV"): 1e-3, ("GeV", "GeV"): 1.0, ("MeV", "MeV"): 1.0}


class ConstantsError(ValueError):
    pass


def load_source():
    return json.loads((REFERENCE / "SOURCE.json").read_text(encoding="utf-8"))


def load_subset(verify=True):
    """The pinned subset, refusing it if its checksum differs from the recorded one."""
    raw = (REFERENCE / "pdg-subset.json").read_bytes()
    if verify and hashlib.sha256(raw).hexdigest() != load_source()["subset_sha256"]:
        raise ConstantsError("pdg-subset.json does not match the checksum recorded in SOURCE.json")
    return validate_subset(json.loads(raw))


def validate_subset(subset):
    """Require every pinned value to retain its database identity and edition."""
    if not isinstance(subset, dict) or subset.get("schema_version") != 1 or subset.get("kind") != "ravel-pdg-subset":
        raise ConstantsError("PDG subset schema 1 required")
    edition = subset.get("edition")
    rows = subset.get("quantities")
    if not isinstance(edition, str) or not edition or not isinstance(rows, dict) or not rows:
        raise ConstantsError("PDG subset requires an edition and quantities")
    for key, row in rows.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            raise ConstantsError("PDG subset has an invalid quantity row")
        if not isinstance(row.get("pdgid"), str) or not row["pdgid"]:
            raise ConstantsError(f"{key}: pdgid is required")
        if row.get("edition") != edition:
            raise ConstantsError(f"{key}: edition must match subset edition")
        # The database gives a dimensionless quantity an empty unit; a missing unit is refused.
        if not isinstance(row.get("unit"), str) or not isinstance(row.get("value"), (int, float)):
            raise ConstantsError(f"{key}: value and unit are required")
    return subset


def _cited(mapping, key):
    for name in (key + "_source", key + "_ref", key + "_citation") + CITATION_KEYS:
        value = mapping.get(name)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, dict)) and value:
            return True
    return False


def _pdg_row(mapping, subset):
    ref = mapping.get("pdg_ref") or mapping.get("pdgid")
    if not isinstance(ref, str):
        return None
    for row in subset["quantities"].values():
        if row["pdgid"] == ref:
            return row
    return None


def _walk(node, path, out, subset):
    if isinstance(node, dict):
        if node.get("kind") == "higgs-reference-tables":
            # The typed table extension resolves citation keys, including generic
            # value fields, rather than treating an arbitrary key as a citation.
            return
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            if numeric and CRITICAL.search(str(key)) and not str(key).endswith(("_source", "_ref", "_citation")):
                if not _cited(node, str(key)):
                    out.append({"field_path": here, "value": value, "kind": "uncited",
                                "reason": "physics-critical number with no citation beside it"})
                elif subset is not None:
                    row = _pdg_row(node, subset)
                    if row is not None and str(key) in ("mass", "width", "value"):
                        _compare(here, value, node.get("unit", row["unit"]), row, out)
            else:
                _walk(value, here, out, subset)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk(item, f"{path}[{i}]", out, subset)


def _compare(here, value, unit, row, out):
    scale = SCALE_TO_PDG.get((unit, row["unit"]))
    if scale is None:
        out.append({"field_path": here, "value": value, "kind": "unit",
                    "reason": f"unit {unit!r} cannot be compared with PDG's {row['unit']!r}"})
        return
    pdg_value = row["value"]
    tolerance = max(row["error_positive"] or 0.0, row["error_negative"] or 0.0)
    if abs(value * scale - pdg_value) > max(tolerance, 1e-12 * abs(pdg_value)):
        out.append({"field_path": here, "value": value, "kind": "pdg-mismatch",
                    "reason": f"differs from PDG {row['edition']} {row['pdgid']} = {pdg_value} {row['unit']} "
                              f"(uncertainty {tolerance}) by more than its uncertainty"})


def check_document(document, *, pdg=False):
    """Findings for one JSON-like document: uncited physics-critical numbers, and with ``pdg`` also
    disagreements with the pinned subset for numbers that cite a PDG identifier."""
    out = []
    _walk(document, "", out, load_subset() if pdg else None)
    _walk_higgs(document, "", out)
    return out


def load_higgs_source(directory=None):
    """Read the local source registration, including an explicit acquisition hold."""
    source = json.loads((Path(directory or HIGGS_REFERENCE) / "SOURCE.json").read_bytes())
    if source.get("kind") != "higgs-reference-source" or source.get("schema_version") != 1:
        raise ConstantsError("Higgs source schema1 required")
    if source.get("status") not in ("installed", "not installed — owner action: approve download"):
        raise ConstantsError("unknown Higgs source status")
    return source


def _pinned_higgs_bytes(directory, pin):
    if not isinstance(pin, dict):
        raise ConstantsError("Higgs file requires a path and checksum pin")
    name, digest = pin.get("path"), pin.get("sha256")
    if (not isinstance(name, str) or not name or Path(name).name != name or name in (".", "..")
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ConstantsError("Higgs file requires an ordinary basename and sha256 checksum")
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ConstantsError("Higgs pinned file must be an ordinary local file: " + name)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ConstantsError("Higgs checksum mismatch: " + name)
    return raw


def fetch_higgs_source(name, cache_dir=None, *, directory=None, opener=None):
    """Fetch one pinned primary source on demand into a cache outside the repository.

    The source documents are not redistributed with RAVEL. The download is verified
    against the pinned sha256 and byte size before it is kept; a cached copy that
    fails verification is replaced. `opener(url)` returns bytes and exists for tests.
    """
    import os
    import urllib.request
    source = load_higgs_source(Path(directory or HIGGS_REFERENCE))
    pin = next((p for p in source.get("source_files", []) if p.get("path") == name), None)
    if pin is None or Path(name).name != name:
        raise ConstantsError("not a pinned Higgs source: " + str(name))
    root = Path(cache_dir) if cache_dir else Path(os.environ.get("RAVEL_CACHE_DIR")
                                                  or Path.home() / ".cache" / "ravel") / "higgs-sources"
    target = root / name
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == pin["sha256"]:
        return target
    if opener is None:
        def opener(url):
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - pinned https URL
                return response.read()
    raw = opener(pin["url"])
    if len(raw) != pin["bytes"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ConstantsError("Higgs source download does not match its pin: " + name)
    root.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return target


def higgs_reference_install_steps(source, destination):
    """Build existing installer steps from a reviewed runtime table registration.

    No acquisition runs here. The installer owns network policy and digest checks.
    Reference values and source identities are supplied, never selected by this helper.
    Primary documents remain locator/hash registrations unless separately acquired.
    """
    pin = source.get("table") if isinstance(source, dict) else None
    if not isinstance(pin, dict):
        raise ConstantsError("reviewed Higgs table pin required")
    name, digest, url, size = (pin.get(k) for k in ("path", "sha256", "url", "bytes"))
    if (not isinstance(name, str) or not name or Path(name).name != name or name in (".", "..")
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(url, str) or not url.startswith("https://")
            or type(size) is not int or size <= 0):
        raise ConstantsError("table pin requires basename, HTTPS URL, sha256 and byte size")
    if pin.get("licence") not in ("CC-BY-4.0", "CC0-1.0"):
        raise ConstantsError("table redistribution requires a reviewed CC BY or CC0 licence")
    if (source.get("kind") != "higgs-reference-source" or source.get("schema_version") != 1
            or source.get("status") != "installed" or not isinstance(source.get("source_files"), list)
            or not source["source_files"] or name == "SOURCE.json"):
        raise ConstantsError("complete reviewed source registration required")
    root = Path(destination)
    return [{"id": "reference-table", "kind": "download", "url": url, "sha256": digest, "size": size,
             "dest": str(root / name)},
            {"id": "reference-source", "kind": "write_file", "path": str(root / "SOURCE.json"),
             "content": json.dumps(source, indent=2, allow_nan=False) + "\n"}]


def load_higgs_tables(directory=None, *, version=None, allow_synthetic=False):
    """Load reviewed local tables only after table and primary-source pin checks.

    Version 2 defaults to the installed cache under RAVEL_CACHE_DIR; a supplied
    directory overrides it. There is no downloader or interpolation. Synthetic data require an explicit
    test-only opt-in and cannot silently substitute for absent physics tables.
    """
    if version is not None and (type(version) is not int or version not in (1, 2)):
        raise ConstantsError("Higgs table version must be 1 or 2")
    if directory is None and version == 2:
        import os
        directory = Path(os.environ.get("RAVEL_CACHE_DIR")
                         or Path.home() / ".cache" / "ravel") / "higgs-tables-v2"
    directory = Path(directory or HIGGS_REFERENCE)
    source = load_higgs_source(directory)
    if source["status"] != "installed":
        raise ConstantsError(source["status"])
    pin = source.get("table_versions", {}).get(str(version), source.get("table"))
    document = json.loads(_pinned_higgs_bytes(directory, pin))
    if version is not None and document.get("schema_version") != version:
        raise ConstantsError("Higgs installed table version differs from requested version")
    findings = check_higgs_tables(document)
    if findings:
        raise ConstantsError("invalid Higgs tables: " + json.dumps(findings, allow_nan=False))
    if document["synthetic"] and not allow_synthetic:
        raise ConstantsError("synthetic Higgs tables are test-only, not physics reference data")
    if document["schema_version"] == 2 and not document["synthetic"]:
        # The inherited digests are declared by the document itself; bind them to the installed rows.
        base = json.loads(_pinned_higgs_bytes(HIGGS_REFERENCE, load_higgs_source(HIGGS_REFERENCE).get("table")))
        for section in ("rows", "ratios"):
            if document["legacy_" + section + "_sha256"] != {r["id"]: _higgs_row_digest(r) for r in base[section]}:
                raise ConstantsError("version 2 Higgs tables must inherit exactly the installed version 1 " + section)
    pins = source.get("source_files")
    if not isinstance(pins, list) or not pins:
        raise ConstantsError("Higgs tables require primary source pins")
    primary = {}
    for pin in pins:
        if not isinstance(pin, dict):
            raise ConstantsError("Higgs file requires a path and checksum pin")
        if (directory / str(pin.get("path"))).exists():
            _pinned_higgs_bytes(directory, pin)  # a local copy must match its pin
        elif not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("sha256"))) or not isinstance(pin.get("bytes"), int):
            raise ConstantsError("Higgs source pin requires a sha256 checksum and byte size")
        if pin["path"] in primary or not isinstance(pin.get("url"), str) or not pin["url"].strip():
            raise ConstantsError("unique primary source pins with locators required")
        primary[pin["path"]] = pin["url"]
    for citation in document["citations"].values():
        if primary.get(citation["source_file"]) != citation["locator"]:
            raise ConstantsError("Higgs citation must resolve to its pinned primary source locator")
        if not document["synthetic"] and not citation["locator"].startswith("https://"):
            raise ConstantsError("physics reference requires a public HTTPS primary locator")
    return document


def _field_path(path):
    result = ""
    for part in path:
        result += f"[{part}]" if isinstance(part, int) else ("." if result else "") + str(part)
    return result


def check_higgs_tables(document):
    """Schema, citation resolution, absolute envelopes and row-derived ratio checks."""
    from jsonschema import Draft202012Validator
    schema = json.loads((HIGGS_REFERENCE / "schema.json").read_bytes())
    out = [{"field_path": _field_path(error.absolute_path), "kind": "schema", "reason": error.message}
           for error in Draft202012Validator(schema).iter_errors(document)]
    if not isinstance(document, dict):
        return out
    citations = document.get("citations", {})
    rows = document.get("rows", [])
    ratios = document.get("ratios", [])
    if not isinstance(citations, dict) or not isinstance(rows, list) or not isinstance(ratios, list):
        return out
    by_id = {}
    v2 = document.get("schema_version") == 2
    legacy = document.get("legacy_rows_sha256", {}) if v2 else {}
    bins = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        here = f"rows[{i}].value"
        key = row.get("citation_key")
        if not isinstance(key, str) or not key.strip():
            out.append({"field_path": here, "kind": "uncited", "reason": "table value requires citation_key"})
        elif key not in citations:
            out.append({"field_path": f"rows[{i}].citation_key" if v2 else here, "kind": "citation", "reason": "citation_key does not resolve"})
        identity = row.get("id")
        if isinstance(identity, str):
            if identity in by_id:
                out.append({"field_path": f"rows[{i}].id", "kind": "schema", "reason": "duplicate table row"})
            by_id[identity] = row
        if v2 and (not isinstance(legacy, dict) or not isinstance(identity, str) or identity not in legacy):
            if not isinstance(row.get("locator"), dict):
                out.append({"field_path": f"rows[{i}].locator", "kind": "provenance",
                            "reason": "new row requires printed-source locator and extraction digest"})
        if v2 and row.get("quantity") == "stxs_bin":
            bins.append((i, row))
        value, reference, uncertainty = row.get("value"), row.get("reference_value"), row.get("uncertainty")
        if isinstance(uncertainty, dict) and all(_finite(v) for v in
                (value, reference, uncertainty.get("minus"), uncertainty.get("plus"))):
            lower, upper = reference - uncertainty["minus"], reference + uncertainty["plus"]
            if not lower <= value <= upper:
                out.append({"field_path": here, "kind": "envelope", "reason": "value outside declared absolute uncertainty envelope"})
    ratio_ids = set()
    for i, ratio in enumerate(ratios):
        if not isinstance(ratio, dict):
            continue
        here = f"ratios[{i}].value"
        key = ratio.get("citation_key")
        if not isinstance(key, str) or not key.strip():
            out.append({"field_path": here, "kind": "uncited", "reason": "ratio value requires citation_key"})
        elif key not in citations:
            out.append({"field_path": here, "kind": "citation", "reason": "ratio citation_key does not resolve"})
        identity = ratio.get("id")
        if isinstance(identity, str):
            if identity in ratio_ids:
                out.append({"field_path": f"ratios[{i}].id", "kind": "schema", "reason": "duplicate ratio row"})
            ratio_ids.add(identity)
        try:
            computed = _higgs_ratio(ratio, by_id)
            if not _finite(ratio.get("value")) or not _finite(ratio.get("absolute_tolerance")):
                raise ConstantsError("finite ratio value and absolute tolerance required")
            if abs(computed - ratio["value"]) > ratio["absolute_tolerance"]:
                raise ConstantsError("ratio differs from recomputed table-row quotient")
        except (ConstantsError, KeyError, TypeError) as exc:
            out.append({"field_path": here, "kind": "ratio", "reason": str(exc)})
    if v2:
        _check_higgs_legacy(document, out)
        _check_higgs_bins(bins, out)
    _nonfinite(document, "", out)
    return out


def _higgs_row_digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _check_higgs_legacy(document, out):
    """Bind inherited JSON row content without adding fields to inherited rows."""
    for section in ("rows", "ratios"):
        pins = document.get("legacy_" + section + "_sha256", {})
        if not isinstance(pins, dict):
            continue
        current = {r.get("id"): r for r in document[section]
                   if isinstance(r, dict) and isinstance(r.get("id"), str)}
        for identity, digest in pins.items():
            try:
                valid = identity in current and _higgs_row_digest(current[identity]) == digest
            except (ValueError, TypeError):
                valid = False
            if not valid:
                out.append({"field_path": "legacy_" + section + "_sha256." + identity,
                            "kind": "identity", "reason": "inherited row missing or changed"})


def _check_higgs_bins(bins, out):
    """Check supplied rectangular half-open bins; null denotes an unbounded end."""
    valid = []
    for i, row in bins:
        bounds = row.get("boundaries")
        if not isinstance(bounds, dict) or not bounds:
            continue
        intervals = {}
        for axis, interval in bounds.items():
            if not isinstance(interval, dict):
                continue
            lo, hi = interval.get("lower"), interval.get("upper")
            if ("lower" not in interval or "upper" not in interval
                    or lo is not None and not _finite(lo)
                    or hi is not None and not _finite(hi)
                    or lo is not None and hi is not None and lo >= hi):
                out.append({"field_path": f"rows[{i}].boundaries.{axis}",
                            "kind": "boundary", "reason": "strictly ordered finite or unbounded ends required"})
                continue
            intervals[axis] = (float("-inf") if lo is None else lo,
                               float("inf") if hi is None else hi, interval.get("unit"))
        if len(intervals) == len(bounds):
            valid.append((i, row, intervals))
    for position, (i, row, intervals) in enumerate(valid):
        for _, other, other_intervals in valid[:position]:
            if (row.get("process"), row.get("stage")) != (other.get("process"), other.get("stage")):
                continue
            if row.get("bin_id") == other.get("bin_id"):
                out.append({"field_path": f"rows[{i}].bin_id", "kind": "identity",
                            "reason": "duplicate bin identity in process and stage"})
            if intervals.keys() != other_intervals.keys() or any(
                    intervals[a][2] != other_intervals[a][2] for a in intervals):
                out.append({"field_path": f"rows[{i}].boundaries", "kind": "boundary",
                            "reason": "same process and stage require comparable axes and units"})
            elif all(max(intervals[a][0], other_intervals[a][0])
                     < min(intervals[a][1], other_intervals[a][1]) for a in intervals):
                out.append({"field_path": f"rows[{i}].boundaries", "kind": "overlap",
                            "reason": "overlapping half-open bins in the same process and stage"})


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _nonfinite(node, path, out):
    if isinstance(node, dict):
        for key, value in node.items():
            _nonfinite(value, (path + "." if path else "") + key, out)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _nonfinite(value, f"{path}[{i}]", out)
    elif isinstance(node, float) and not math.isfinite(node):
        out.append({"field_path": path, "kind": "schema", "reason": "finite table numbers required"})


def _higgs_ratio(ratio, by_id):
    numerator = by_id[ratio["numerator"]]
    denominator = by_id[ratio["denominator"]]
    if numerator["unit"] != denominator["unit"]:
        raise ConstantsError("ratio requires identical units; explicit conversion is not implemented")
    if not _finite(numerator["value"]) or not _finite(denominator["value"]) or denominator["value"] <= 0:
        raise ConstantsError("ratio requires finite rows and a positive denominator")
    value = numerator["value"] / denominator["value"]
    if not math.isfinite(value):
        raise ConstantsError("ratio quotient must be finite")
    return value


def recompute_higgs_ratios(document):
    findings = check_higgs_tables(document)
    if findings:
        raise ConstantsError("invalid Higgs ratio inputs: " + json.dumps(findings, allow_nan=False))
    by_id = {row["id"]: row for row in document["rows"]}
    return {ratio["id"]: _higgs_ratio(ratio, by_id) for ratio in document["ratios"]}


def _walk_higgs(node, path, out):
    if isinstance(node, dict):
        if node.get("kind") == "higgs-reference-tables":
            for finding in check_higgs_tables(node):
                finding["field_path"] = (path + "." if path else "") + finding["field_path"]
                out.append(finding)
        else:
            for key, value in node.items():
                _walk_higgs(value, (path + "." if path else "") + str(key), out)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _walk_higgs(value, f"{path}[{i}]", out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ravel.validation.constants_manifest")
    ap.add_argument("document", nargs="?")
    ap.add_argument("--pdg", action="store_true", help="also compare PDG-cited numbers with the pinned subset")
    ap.add_argument("--verify-subset", action="store_true")
    args = ap.parse_args(argv)
    if args.verify_subset:
        load_subset(verify=True)
        print(json.dumps({"status": "ok", "edition": load_source()["edition"]}))
        return 0
    if not args.document:
        ap.error("a document or --verify-subset is required")
    findings = check_document(json.loads(Path(args.document).read_text(encoding="utf-8")), pdg=args.pdg)
    print(json.dumps({"findings": findings}, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
