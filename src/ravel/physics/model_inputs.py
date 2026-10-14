"""Source-pinned, static SLHA MASS/DECAY model-input preflight.

Adopted from the sealed lower-tier B2 bookkeeping prototype, then source-checked
on actual SModelS cards. This module reads text only. It never imports or evaluates UFO/Python model code,
never invokes a generator, and never edits the supplied source artifact.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

MAX_BYTES = 2 * 1024 * 1024
MAX_PARTICLES = 512
MAX_CHANNELS = 16384
MAX_DAUGHTERS = 32
BR_TOLERANCE = Fraction(1, 1_000_000)
HBARC_GEV_FM = Fraction(1973269804, 10**10)  # PDG: 197.3269804 MeV fm
FM_TO_MM = Fraction(1, 10**12)
REAL_RE = re.compile(r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[EeDd][+-]?\d+)?\Z")
INTEGER_RE = re.compile(r"[+-]?\d+\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fraction(token: str, label: str) -> Fraction:
    if len(token) > 128 or not REAL_RE.fullmatch(token):
        raise ValueError(f"{label}: invalid SLHA decimal token {token!r}")
    normalized = token.replace("d", "e").replace("D", "E")
    exponent_match = re.search(r"[Ee]([+-]?\d+)\Z", normalized)
    if exponent_match and abs(int(exponent_match.group(1))) > 308:
        raise ValueError(f"{label}: exponent outside bounded parser range")
    try:
        return Fraction(normalized)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"{label}: invalid SLHA decimal token {token!r}") from exc


def _integer(token: str, label: str) -> int:
    if len(token) > 16 or not INTEGER_RE.fullmatch(token):
        raise ValueError(f"{label}: invalid integer token {token!r}")
    value = int(token)
    if value == 0:
        raise ValueError(f"{label}: PDG/count value must be nonzero")
    return value


def _pinned_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError(f"{label}: expected lowercase SHA256")
    return value


def _validate_completeness_manifest(manifest: dict, source_digest: str) -> dict[int, dict]:
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "source_sha256", "channel_completeness"}:
        raise ValueError("completeness manifest requires exactly schema_version, source_sha256, channel_completeness")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("unsupported completeness-manifest schema")
    if _pinned_hash(manifest["source_sha256"], "completeness manifest source_sha256") != source_digest:
        raise ValueError("completeness manifest is bound to different SLHA source bytes")
    entries = manifest["channel_completeness"]
    if not isinstance(entries, dict) or len(entries) > MAX_PARTICLES:
        raise ValueError("channel_completeness must be a bounded object")
    normalized: dict[int, dict] = {}
    for key, record in entries.items():
        if not isinstance(key, str) or len(key) > 16 or not INTEGER_RE.fullmatch(key) or abs(int(key)) == 0:
            raise ValueError(f"invalid completeness PDG key {key!r}")
        pdg = abs(int(key))
        if pdg in normalized:
            raise ValueError(f"duplicate completeness PDG {pdg}")
        if not isinstance(record, dict) or set(record) != {"status", "source_ref", "evidence_text", "evidence_sha256"}:
            raise ValueError(f"completeness entry for PDG {pdg} requires status, source_ref, evidence_text, evidence_sha256")
        if record["status"] not in {"complete", "incomplete"}:
            raise ValueError(f"invalid explicit completeness status for PDG {pdg}")
        if not isinstance(record["source_ref"], str) or not record["source_ref"].strip() or len(record["source_ref"]) > 4096:
            raise ValueError(f"completeness entry for PDG {pdg} needs a source reference")
        if not isinstance(record["evidence_text"], str) or not record["evidence_text"].strip() or len(record["evidence_text"]) > 16384:
            raise ValueError(f"completeness entry for PDG {pdg} needs evidence text")
        if _pinned_hash(record["evidence_sha256"], f"PDG {pdg} evidence_sha256") != _sha(record["evidence_text"].encode("utf-8")):
            raise ValueError(f"completeness evidence hash mismatch for PDG {pdg}")
        normalized[pdg] = dict(record)
    return normalized


def _parse_slha(text: str) -> tuple[dict[int, dict], dict[int, dict], list[str]]:
    masses: dict[int, dict] = {}
    decays: dict[int, dict] = {}
    opaque_blocks: list[str] = []
    block: str | None = None
    mass_blocks = 0
    current_decay: dict | None = None

    total_channels = 0
    for line_number, raw in enumerate(text.splitlines(), start=1):
        active = raw.split("#", 1)[0].strip()
        if not active:
            continue
        tokens = active.split()
        first = tokens[0].casefold()
        if first == "block":
            if len(tokens) < 2:
                raise ValueError(f"line {line_number}: malformed BLOCK header")
            block = tokens[1].casefold()
            current_decay = None
            if block == "mass":
                mass_blocks += 1
                if mass_blocks > 1:
                    raise ValueError(f"line {line_number}: multiple BLOCK MASS sections are outside this preflight contract")
            elif block not in opaque_blocks:
                opaque_blocks.append(block)
            continue
        if first == "xsection":
            # SModelS cards may carry this cross-section extension. It is
            # preserved in source custody but numerically opaque here.
            block = "xsection"
            current_decay = None
            if block not in opaque_blocks:
                opaque_blocks.append(block)
            continue
        if first == "decay":
            if len(tokens) != 3:
                raise ValueError(f"line {line_number}: DECAY header must contain PDG and total width")
            raw_pdg = _integer(tokens[1], f"line {line_number} DECAY PDG")
            pdg = abs(raw_pdg)
            if pdg in decays:
                raise ValueError(f"line {line_number}: duplicate DECAY parent PDG {pdg}")
            width = _fraction(tokens[2], f"line {line_number} total width")
            if width < 0:
                raise ValueError(f"line {line_number}: negative total width for PDG {pdg}")
            current_decay = {"pdg": pdg, "declared_pdg": raw_pdg, "width_GeV_exact": width,
                             "header_line": line_number, "channels": [], "channel_keys": set()}
            if len(decays) >= MAX_PARTICLES:
                raise ValueError("DECAY parents exceed bounded inventory")
            decays[pdg] = current_decay
            block = None
            continue
        if block == "mass":
            if len(tokens) != 2:
                raise ValueError(f"line {line_number}: MASS row must contain exactly PDG and mass")
            raw_pdg = _integer(tokens[0], f"line {line_number} MASS PDG")
            pdg = abs(raw_pdg)
            if pdg in masses:
                raise ValueError(f"line {line_number}: duplicate MASS PDG {pdg}")
            value = _fraction(tokens[1], f"line {line_number} mass")
            if len(masses) >= MAX_PARTICLES:
                raise ValueError("MASS entries exceed bounded inventory")
            masses[pdg] = {"pdg": pdg, "declared_pdg": raw_pdg, "mass_GeV_exact": value,
                           "source_line": line_number}
            continue
        if current_decay is not None:
            if len(tokens) < 3:
                raise ValueError(f"line {line_number}: malformed DECAY channel row")
            branching = _fraction(tokens[0], f"line {line_number} branching fraction")
            if branching < 0:
                raise ValueError(f"line {line_number}: negative BR is unsupported by this consumer-neutral preflight")
            if branching > 1:
                raise ValueError(f"line {line_number}: branching fraction exceeds one")
            if not INTEGER_RE.fullmatch(tokens[1]):
                raise ValueError(f"line {line_number}: malformed NDA daughter count")
            nda = int(tokens[1])
            if nda < 1 or nda > MAX_DAUGHTERS or len(tokens) != nda + 2:
                raise ValueError(f"line {line_number}: NDA count does not match daughter PDG count")
            daughters = [_integer(token, f"line {line_number} daughter PDG") for token in tokens[2:]]
            key = tuple(sorted(daughters))
            if key in current_decay["channel_keys"]:
                raise ValueError(f"line {line_number}: duplicate decay channel identity for parent PDG {current_decay['pdg']}")
            total_channels += 1
            if total_channels > MAX_CHANNELS:
                raise ValueError("DECAY channels exceed bounded inventory")
            current_decay["channel_keys"].add(key)
            current_decay["channels"].append({"branching_fraction_exact": branching,
                                               "nda": nda, "daughter_pdgs": daughters,
                                               "source_line": line_number})
            continue
        if block is None:
            raise ValueError(f"line {line_number}: data outside BLOCK or DECAY section")
        # Unrecognized blocks stay opaque, per SLHA's forward-compatible block convention.

    if mass_blocks != 1 or not masses:
        raise ValueError("preflight requires exactly one nonempty BLOCK MASS")
    for decay in decays.values():
        total = decay["width_GeV_exact"]
        br_sum = sum((row["branching_fraction_exact"] for row in decay["channels"]), Fraction(0))
        if br_sum > 1 + BR_TOLERANCE:
            raise ValueError(f"parent PDG {decay['pdg']} known BR sum exceeds one")
        decay["branching_fraction_sum_exact"] = br_sum
    return masses, decays, opaque_blocks


def _rational(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _decimal(value: Fraction, places: int = 24) -> str:
    if value == 0:
        return "0"
    with localcontext() as context:
        context.prec = places
        return format(Decimal(value.numerator) / Decimal(value.denominator), f".{places - 4}E")


def _inventory_card(source_digest: str, source_name: str, masses: dict[int, dict],
                    decays: dict[int, dict], completeness: dict[int, dict], opaque_blocks: list[str]) -> dict:
    mass_rows = []
    for pdg, row in sorted(masses.items()):
        mass = row["mass_GeV_exact"]
        mass_rows.append({"pdg": pdg, "declared_pdg": row["declared_pdg"],
                          "mass_GeV_exact": _rational(mass), "mass_GeV_decimal": _decimal(mass),
                          "source_line": row["source_line"],
                          "sign_interpretation": "preserved_uninterpreted" if mass < 0 else "nonnegative_as_supplied"})

    decay_rows = []
    for pdg, row in sorted(decays.items()):
        width = row["width_GeV_exact"]
        if width == 0:
            lifetime = {"status": "stable_by_card", "proper_ctau_mm": None,
                        "reason": "supplied DECAY total width is exactly zero; no finite c*tau is assigned"}
        else:
            ctau = HBARC_GEV_FM * FM_TO_MM / width
            lifetime = {"status": "finite_from_supplied_total_width", "proper_ctau_mm_exact": _rational(ctau),
                        "proper_ctau_mm_decimal": _decimal(ctau),
                        "formula": "c*tau = hbar*c/Gamma_total",
                        "arithmetic_scope": "exact rational evaluation conditional on supplied width and stated rounded hbar*c literal", "hbar_c_GeV_fm": "0.1973269804",
                        "fm_to_mm": "1/1000000000000",
                        "approximation": "Treats the supplied DECAY total width as the particle's total rest-frame width; no uncertainty or model correction is added."}
        declaration = completeness.get(pdg)
        if declaration is None:
            channel_status = "unresolved_completeness_unknown"
            declaration_out = None
        elif declaration["status"] == "incomplete":
            channel_status = "unresolved_explicitly_incomplete"
            declaration_out = {k: declaration[k] for k in ("status", "source_ref", "evidence_text", "evidence_sha256")}
        else:
            declaration_out = {k: declaration[k] for k in ("status", "source_ref", "evidence_text", "evidence_sha256")}
            if width == 0 and not row["channels"]:
                channel_status = "complete_stable_no_channels"
            elif abs(row["branching_fraction_sum_exact"] - 1) <= BR_TOLERANCE:
                channel_status = "complete_br_sum_consistent"
            else:
                raise ValueError(f"complete channel declaration for PDG {pdg} has BR sum {_rational(row['branching_fraction_sum_exact'])}, not one within tolerance")
        decay_rows.append({
            "pdg": pdg,
            "declared_pdg": row["declared_pdg"],
            "total_width_GeV_exact": _rational(width),
            "total_width_GeV_decimal": _decimal(width),
            "width_unit": "GeV",
            "branching_ratio_unit": "dimensionless_fraction",
            "branching_fraction_sum_exact": _rational(row["branching_fraction_sum_exact"]),
            "branching_fraction_sum_decimal": _decimal(row["branching_fraction_sum_exact"]),
            "channels": [{"branching_fraction_exact": _rational(ch["branching_fraction_exact"]),
                          "branching_fraction_decimal": _decimal(ch["branching_fraction_exact"]),
                          "implied_partial_width_GeV_exact": _rational(width * ch["branching_fraction_exact"]),
                          "partial_width_scope": "supplied total width times supplied branching fraction, not an independent calculation",
                          "nda": ch["nda"], "daughter_pdgs": ch["daughter_pdgs"],
                          "source_line": ch["source_line"]} for ch in row["channels"]],
            "channel_completeness": channel_status,
            "completeness_declaration": declaration_out,
            "lifetime": lifetime,
            "source_line": row["header_line"],
        })
    return {
        "schema_version": 1,
        "kind": "model_input_preflight",
        "status": "static_inventory",
        "advisory_only": True,
        "execution_authorized": False,
        "mass_pdgs_without_decay_record": sorted(set(masses) - set(decays)),
        "decay_pdgs_without_mass_record": sorted(set(decays) - set(masses)),
        "source": {"name": source_name, "sha256": source_digest, "bytes_read_only": True},
        "units": {"mass": "GeV", "total_width": "GeV", "branching_fraction": "dimensionless"},
        "masses": mass_rows,
        "decays": decay_rows,
        "opaque_blocks": opaque_blocks,
        "checks_passed": True,
        "physics_validated": False,
        "limitations": [
            "Static source syntax and supplied card arithmetic only; no UFO/model code is imported or evaluated.",
            "A source-pinned completeness declaration is an inspectable assertion, not proof that all physical channels were calculated.",
            "No daughter threshold, off-shell mediator, spectrum-wide mass relation, tachyon, mixing, coupling, matrix-element, or generator-runtime judgment is made.",
            "A zero source width is labeled stable_by_card only. Missing DECAY blocks remain unknown; no missing channel or width is invented.",
            "Proper c*tau uses the total rest-frame width as supplied and the declared hbar*c conversion; no width uncertainty or energy dependence is modeled.",
            "Passing does not establish physical model validity, source authenticity, or workflow approval."
        ],
    }


def audit_slha_bytes(data: bytes, *, source_name: str, expected_sha256: str,
                     completeness_manifest: dict) -> dict:
    """Audit a pinned SLHA byte string using static MASS/DECAY parsing only."""
    if not isinstance(data, bytes):
        raise ValueError("SLHA input must be bytes so source identity is exact")
    if len(data) > MAX_BYTES:
        raise ValueError(f"SLHA input exceeds {MAX_BYTES} byte preflight limit")
    if not isinstance(source_name, str) or not source_name.strip() or len(source_name) > 4096:
        raise ValueError("source_name must be nonempty")
    actual_digest = _sha(data)
    expected = _pinned_hash(expected_sha256, "expected source hash")
    if actual_digest != expected:
        raise ValueError("SLHA source bytes do not match expected SHA256")
    completeness = _validate_completeness_manifest(completeness_manifest, actual_digest)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SLHA source is not UTF-8 text") from exc
    if text.startswith("\ufeff"):
        text = text[1:]
    masses, decays, opaque = _parse_slha(text)
    unknown_declared_pdgs = sorted(set(completeness) - set(decays))
    if unknown_declared_pdgs:
        raise ValueError(f"completeness manifest refers to absent DECAY parent PDG(s): {unknown_declared_pdgs}")
    return _inventory_card(actual_digest, source_name, masses, decays, completeness, opaque)


def audit_slha_file(path: str | Path, *, expected_sha256: str,
                    completeness_manifest: dict) -> dict:
    """Read-only regular-file wrapper; symlink input paths are refused."""
    source_path = Path(path)
    if source_path.is_symlink():
        raise ValueError(f"symlink SLHA input is forbidden: {source_path}")
    if not source_path.is_file():
        raise ValueError(f"SLHA input is not a regular file: {source_path}")
    with source_path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    return audit_slha_bytes(data, source_name=str(source_path.resolve()),
                            expected_sha256=expected_sha256,
                            completeness_manifest=completeness_manifest)


def make_completeness_entry(status: str, *, source_ref: str, evidence_text: str) -> dict:
    """Fixture helper: create a manifest entry with integrity-pinned declaration text."""
    if status not in {"complete", "incomplete"}:
        raise ValueError("status must be complete or incomplete")
    return {"status": status, "source_ref": source_ref, "evidence_text": evidence_text,
            "evidence_sha256": _sha(evidence_text.encode("utf-8"))}


def make_manifest(data: bytes, entries: dict[str, dict] | None = None) -> dict:
    """Fixture helper: bind completeness declarations to exact source bytes."""
    return {"schema_version": 1, "source_sha256": _sha(data),
            "channel_completeness": {} if entries is None else entries}
