"""Beam types, parton content and PDF flavour checks for MadGraph generation.

The record answers three questions before any event is generated:

- does each declared beam particle agree with its MadGraph ``lpp`` setting;
- which partons does each hadron beam supply (the declared multiparticle labels
  of the process's initial state), and does the chosen PDF set carry them;
- which generator version the parton content needs.

MadGraph's own conventions are used: ``lpp`` -> IDBMUP follows
``RunCard.get_idbmup`` (lpp = +-1/+-2 proton, +-3 electron, +-4 muon, 0 no PDF,
which MadGraph writes as IDBMUP 0). MadGraph 2.9.27 evaluates PDFs only for
quarks, gluons and photons (``pdg2pdf_lhapdf6.f`` stops for |pdg| > 7 other
than 22); charged-lepton partons in a hadron beam need MadGraph 3.
"""
from __future__ import annotations

from pathlib import Path
import re

# MadGraph SM particle names -> PDG identifiers.
SM_NAMES = {
    "d": 1, "u": 2, "s": 3, "c": 4, "b": 5, "t": 6,
    "d~": -1, "u~": -2, "s~": -3, "c~": -4, "b~": -5, "t~": -6,
    "g": 21, "a": 22, "z": 23, "w+": 24, "w-": -24, "h": 25,
    "e-": 11, "e+": -11, "mu-": 13, "mu+": -13, "ta-": 15, "ta+": -15,
    "ve": 12, "ve~": -12, "vm": 14, "vm~": -14, "vt": 16, "vt~": -16,
}
# MadGraph's default multiparticle labels when a process card does not redefine
# them (p and j include the b quark only in five-flavour restrictions; both
# spellings are recorded as the default rather than guessed).
DEFAULT_MULTIPARTICLES = {"p": "g u c d s b u~ c~ d~ s~ b~", "j": "g u c d s b u~ c~ d~ s~ b~",
                          "l+": "e+ mu+", "l-": "e- mu-", "vl": "ve vm vt", "vl~": "ve~ vm~ vt~"}
HADRON_BEAMS = {2212: 1, -2212: -1}
# Beam particle -> admitted lpp values. Lepton and photon beams enter without a
# PDF (lpp = 0). Lepton ISR structure functions (lpp = +-3/+-4) are not admitted
# here; they use generator-specific labels outside this adapter.
ALLOWED_LPP = {2212: (1,), -2212: (-1,), 11: (0,), -11: (0,), 13: (0,), -13: (0,), 22: (0,),
               12: (0,), -12: (0,), 14: (0,), -14: (0,), 16: (0,), -16: (0,)}
QUARKS_GLUON = {1, 2, 3, 4, 5, 6, 21}
CHARGED_LEPTONS = {11, 13, 15}
PHOTON = 22


def idbmup(lpp):
    """MadGraph's IDBMUP for an lpp value (``RunCard.get_idbmup``)."""
    if type(lpp) is not int:
        raise ValueError("lpp must be an integer")
    if lpp in (1, 2, -1, -2):
        return 2212 if lpp > 0 else -2212
    if lpp in (3, -3):
        return 11 if lpp > 0 else -11
    if lpp in (4, -4):
        return 13 if lpp > 0 else -13
    if lpp == 0:
        return 0
    return lpp


def beam_errors(beam_pdg, settings):
    """Declared beam particles against lpp1/lpp2 (both must be explicit)."""
    errors = []
    if type(beam_pdg) is not list or len(beam_pdg) != 2:
        return ["beam_pdg must list the two beam particles"]
    for i, pdg in enumerate(beam_pdg, 1):
        key = f"lpp{i}"
        if key not in settings:
            errors.append(f"explicit run setting required: {key}")
            continue
        if pdg not in ALLOWED_LPP:
            errors.append(f"beam {i}: particle {pdg} is not a supported beam (proton, antiproton, lepton, photon, neutrino)")
        elif settings[key] not in ALLOWED_LPP[pdg]:
            errors.append(f"beam {i}: {key}={settings[key]!r} does not describe a {pdg} beam "
                          f"(expected {' or '.join(map(str, ALLOWED_LPP[pdg]))})")
    return errors


def readback_errors(beam_pdg, effective_settings, init_fields):
    """Effective run card and LHE <init> against the declared beams.

    ``init_fields`` is the first <init> row (IDBMUP1 IDBMUP2 EBMUP1 EBMUP2 ...).
    MadGraph silently switches a beam to lpp = 0 for lepton-initiated processes;
    this check refuses that for a declared hadron beam.
    """
    errors = []
    for i in (1, 2):
        if f"lpp{i}" not in effective_settings:
            errors.append(f"effective run card lacks lpp{i}")
    if errors:
        return errors
    lpp = [effective_settings["lpp1"], effective_settings["lpp2"]]
    if any(type(v) is not float and type(v) is not int for v in lpp) or any(v != int(v) for v in lpp):
        return ["effective lpp values must be integers"]
    lpp = [int(v) for v in lpp]
    errors += beam_errors(beam_pdg, {"lpp1": lpp[0], "lpp2": lpp[1]})
    expected = [idbmup(v) for v in lpp]
    observed = [int(float(v)) for v in init_fields[:2]]
    if observed != expected:
        errors.append(f"LHE beam identity {observed} differs from the effective lpp setting {lpp} (expected {expected})")
    return errors


def _initial_legs(process):
    core = process.split(",", 1)[0]
    if ">" not in core:
        raise ValueError("process needs an explicit initial and final state")
    legs = core.split(">", 1)[0].split()
    if len(legs) != 2:
        raise ValueError("process needs exactly two initial-state particles")
    return legs


def leg_content(label, definitions):
    """PDG identifiers a process label stands for (declared multiparticles first)."""
    if label in definitions:
        names = definitions[label].split()
    elif label in DEFAULT_MULTIPARTICLES:
        names = DEFAULT_MULTIPARTICLES[label].split()
    else:
        names = [label]
    result = []
    for name in names:
        if name not in SM_NAMES:
            raise ValueError(f"initial-state particle {name!r} has no Standard Model parton identity; "
                             "declare the multiparticle label in definitions")
        result.append(SM_NAMES[name])
    return sorted(set(result))


def read_info_flavours(info_path):
    """Flavour census of an installed LHAPDF set (its ``Flavors:`` entry)."""
    text = Path(info_path).read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^Flavors:\s*\[([^\]]*)\]", text, re.M)
    if not match:
        raise ValueError(f"LHAPDF info file has no Flavors entry: {info_path}")
    values = []
    for token in match.group(1).replace("\n", " ").split(","):
        token = token.strip()
        if not token:
            continue
        if not re.fullmatch(r"[+-]?\d+", token):
            raise ValueError(f"invalid flavour in {info_path}: {token!r}")
        values.append(21 if int(token) == 0 else int(token))
    if not values:
        raise ValueError(f"empty Flavors entry: {info_path}")
    return sorted(set(values))


def content(generation, *, pdf_flavours=None, generator_version=None, census_required=False):
    """Return (record, errors) for a scoped generation section.

    ``pdf_flavours`` is the installed set's census (required when a hadron beam
    supplies a lepton or photon parton through LHAPDF). ``generator_version`` is
    the MadGraph VERSION string, when known. A static check (no installed set
    yet) passes ``census_required=False``; plan time passes True.
    """
    errors = []
    settings = generation["run_settings"]
    beams = generation["beam_pdg"]
    errors += beam_errors(beams, settings)
    try:
        legs = _initial_legs(generation["process"])
        partons = [leg_content(label, generation.get("definitions", {})) for label in legs]
    except ValueError as exc:
        return None, errors + [str(exc)]
    record_beams, needed, exotic = [], set(), set()
    definitions = generation.get("definitions", {})
    for i, (pdg, leg, ids) in enumerate(zip(beams, legs, partons), 1):
        hadron = pdg in HADRON_BEAMS
        default = leg not in definitions and leg in DEFAULT_MULTIPARTICLES
        record_beams.append({"beam": i, "pdg": pdg, "lpp": settings.get(f"lpp{i}"), "kind":
                             "hadron" if hadron else "photon" if pdg == PHOTON else "lepton",
                             "initial_state_label": leg, "partons": ids,
                             "content_source": "MadGraph default multiparticle" if default else "declared"})
        if hadron and not default:
            needed |= set(ids)
        if hadron:
            exotic |= {p for p in ids if abs(p) in CHARGED_LEPTONS or p == PHOTON}
            other = [p for p in ids if abs(p) not in QUARKS_GLUON | CHARGED_LEPTONS and p != PHOTON]
            if other:
                errors.append(f"beam {i}: hadron beam cannot supply partons {other}")
        elif ids != [pdg]:
            errors.append(f"beam {i}: a {pdg} beam without a PDF supplies only itself, not {ids}")
    leptons = sorted(p for p in exotic if abs(p) in CHARGED_LEPTONS)
    minimum = "3.0.0" if leptons else None
    declared_hadron = [b for b in record_beams if b["kind"] == "hadron" and b["content_source"] == "declared"]
    scheme = None
    if declared_hadron:
        scheme = "5F" if any(abs(p) == 5 for b in declared_hadron for p in b["partons"]) else "4F"
    record = {"schema_version": 1, "kind": "beam_content", "beams": record_beams,
              "hadron_partons": sorted(needed), "lepton_or_photon_partons": sorted(exotic),
              "flavour_scheme": scheme,
              "minimum_generator_version": minimum,
              "basis": "declared beams, lpp settings and initial-state multiparticle labels"}
    if exotic:
        if settings.get("pdlabel") != "lhapdf":
            errors.append("lepton or photon partons in a hadron beam need pdlabel=lhapdf with a set that carries them")
        elif pdf_flavours is None and census_required:
            errors.append("lepton or photon partons in a hadron beam need the PDF set's flavour census")
        elif pdf_flavours is not None:
            missing = sorted(p for p in exotic if p not in pdf_flavours)
            if missing:
                errors.append(f"PDF set {settings.get('lhaid')} does not carry partons {missing} "
                              f"(its flavours are {pdf_flavours})")
    if pdf_flavours is not None:
        record["pdf_flavours"] = pdf_flavours
        absent = sorted(p for p in needed if p not in pdf_flavours and abs(p) != 6)
        if absent and settings.get("pdlabel") == "lhapdf":
            errors.append(f"PDF set {settings.get('lhaid')} does not carry partons {absent}")
    if minimum and generator_version is not None and version_tuple(generator_version) < version_tuple(minimum):
        errors.append(f"charged-lepton partons {leptons} in a hadron beam need MadGraph {minimum} or later; "
                      f"the selected runtime is {generator_version}")
    return record, errors


def scheme_errors(record, param_blocks):
    """A five-flavour proton needs a massless b quark in the executed card."""
    if not record or record.get("flavour_scheme") != "5F":
        return []
    mass = param_blocks.get("MASS", {}).get((5,))
    if mass is None:
        return ["five-flavour proton: the executed card has no b-quark mass entry"]
    if mass not in (0, 0.0):
        return [f"five-flavour proton (b in the proton) needs a massless b quark; the card has MASS 5 = {mass}"]
    return []


def version_tuple(text):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text))
    if not match:
        raise ValueError(f"unrecognised generator version: {text!r}")
    return tuple(int(x) for x in match.groups())


def pdf_manifest_row(lhaid, *, catalog=None):
    """The pinned LHAPDF set for an identifier, from native/setup/pdf-sets.json."""
    if catalog is None:
        from ravel.setup import manifest
        path = manifest.repo_root() / "native/setup/pdf-sets.json"
        if not path.is_file():
            raise ValueError(f"PDF-set manifest not found: {path}")
        catalog = manifest.validate_pdf_sets(manifest.read_json(path))
    rows = [row for row in catalog["sets"] if row["lhaid"] == lhaid]
    if not rows:
        known = ", ".join(f"{row['name']} ({row['lhaid']})" for row in catalog["sets"])
        raise ValueError(f"LHAPDF identifier {lhaid} is not pinned in native/setup/pdf-sets.json (pinned: {known})")
    return dict(rows[0])
