#!/usr/bin/env python3
"""likelihood_appropriateness -- is a published likelihood an appropriate model for this run?

A published background-only workspace and the run's signal patch can pair structurally (the
pairing gate, ``pairing_check.check_pairing``) and still describe a different measurement: a
signal normfactor that is not the workspace POI, modifier types the published model never uses,
a declared signal model or selection that differs from the one the run simulated, or control
regions that receive no signal although the signal would populate them. This check compares
those structural and declared-metadata facts and returns a typed verdict:

  ``inappropriate``              any blocking finding
  ``appropriate-with-cautions``  no blocking finding, at least one caution
  ``appropriate``                otherwise

Finding codes (fixed vocabulary; severity in parentheses):
  missing-channels (blocking)                 workspace channels without signal that the
                                              channel map does not declare zero (or, without a
                                              map, signal-region channels the pairing gate
                                              finds unpatched)
  patch-targets-outside-workspace (blocking)  any other pairing mismatch: bin counts, paths
  parameterisation-differs (blocking)         signal normfactor is not the measurement POI, or
                                              the patch adds an unsupported modifier type
  signal-model-differs (blocking)             declared and selected process or final state differ
  signal-model-undeclared (caution)           either side of that comparison is absent
  selection-changed (blocking)                declared and run selection identities differ
  selection-unverified (caution)              either selection identity is absent
  control-regions-without-signal (caution)    channels that receive no signal while others do;
                                              blocking when a supplied unmodelled s/b exceeds
                                              the recorded threshold
  cr-signal-contamination-unknown (info)      such channels exist and no yields were supplied

The record's scope is structural and declared-metadata comparison only. It does not establish
acceptance, coverage or physics certification.

CLI:
  python -m ravel.validation.likelihood_appropriateness --bkg W --patch P
      [--channel-map F | --shipped-channel-map ID] [--declared F] [--selection F]
      [--signal-yields F] [--threshold-unmodelled-control-fraction X]
      --out likelihood_appropriateness.json
Exit codes: 0 appropriate / appropriate-with-cautions * 1 inappropriate * 2 usage or unreadable input
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile

from ravel.validation.pairing_check import check_pairing

SCHEMA_VERSION = 1
KIND = "likelihood-appropriateness"
VERDICTS = ("appropriate", "appropriate-with-cautions", "inappropriate")
SEVERITIES = ("blocking", "caution", "info")
FINDING_CODES = {
    "missing-channels": "blocking",
    "patch-targets-outside-workspace": "blocking",
    "parameterisation-differs": "blocking",
    "signal-model-differs": "blocking",
    "signal-model-undeclared": "caution",
    "selection-changed": "blocking",
    "selection-unverified": "caution",
    "control-regions-without-signal": "caution",
    "cr-signal-contamination-unknown": "info",
}
ALLOWED_MODIFIER_TYPES = frozenset({"normfactor", "staterror", "shapesys", "normsys", "histosys", "lumi"})
DEFAULT_THRESHOLDS = {"max_unmodelled_control_fraction": 0.05}
SCOPE = ("structural and declared-metadata comparison of a published likelihood with the run's "
         "signal model and selection; it does not establish acceptance, coverage or physics "
         "certification")
CHECK_NAMES = ("pairing-structure", "channel-coverage", "parameterisation", "signal-model",
               "selection-identity", "control-region-signal")

_SIGNAL_MODEL_KEYS = ("process", "final_state", "parameters")
_PATCH_PATH = re.compile(r"/channels/(\d+)/samples/(\d+)")
# check_pairing reports these two mismatch forms; every other mismatch is a target/shape fault.
_SR_UNPATCHED = "SR channels NOT patched"
_NO_NORMFACTOR = "lacks the mu normfactor"


# --------------------------------------------------------------------------- input shapes

def _signal_model(value, where):
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    unknown = set(value) - set(_SIGNAL_MODEL_KEYS)
    if unknown:
        raise ValueError(f"{where} has unknown keys {sorted(unknown)}")
    for key in ("process", "final_state"):
        if key in value and not isinstance(value[key], str):
            raise ValueError(f"{where}.{key} must be a string")
    if "parameters" in value and not (isinstance(value["parameters"], list)
                                      and all(isinstance(p, str) for p in value["parameters"])):
        raise ValueError(f"{where}.parameters must be a list of strings")
    return value


def _declared(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("declared must be an object")
    unknown = set(value) - {"signal_model", "selection_identity"}
    if unknown:
        raise ValueError(f"declared has unknown keys {sorted(unknown)}")
    if value.get("signal_model") is not None:
        _signal_model(value["signal_model"], "declared.signal_model")
    if value.get("selection_identity") is not None and not isinstance(value["selection_identity"], str):
        raise ValueError("declared.selection_identity must be a string")
    return value


def _selection(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("selection must be an object")
    unknown = set(value) - {"identity", "signal_model"}
    if unknown:
        raise ValueError(f"selection has unknown keys {sorted(unknown)}")
    if value.get("signal_model") is not None:
        _signal_model(value["signal_model"], "selection.signal_model")
    if value.get("identity") is not None and not isinstance(value["identity"], str):
        raise ValueError("selection.identity must be a string")
    return value


def _thresholds(value):
    out = dict(DEFAULT_THRESHOLDS)
    if value is None:
        return out
    if not isinstance(value, dict):
        raise ValueError("thresholds must be an object")
    unknown = set(value) - set(DEFAULT_THRESHOLDS)
    if unknown:
        raise ValueError(f"thresholds has unknown keys {sorted(unknown)}")
    for key, number in value.items():
        if isinstance(number, bool) or not isinstance(number, (int, float)) \
                or not math.isfinite(number) or number < 0:
            raise ValueError(f"threshold {key} must be a finite nonnegative number")
        out[key] = float(number)
    return out


def _signal_yields(value, channel_names):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("signal_yields must be an object keyed by workspace channel")
    out = {}
    for channel, row in value.items():
        if channel not in channel_names:
            raise ValueError(f"signal_yields names {channel!r}, which is not a workspace channel")
        if not isinstance(row, dict) or set(row) != {"s", "b"}:
            raise ValueError(f"signal_yields[{channel!r}] must be exactly {{'s', 'b'}}")
        for key in ("s", "b"):
            number = row[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) \
                    or not math.isfinite(number) or number < 0:
                raise ValueError(f"signal_yields[{channel!r}].{key} must be a finite nonnegative number")
        out[channel] = {"s": float(row["s"]), "b": float(row["b"])}
    return out


def _workspace_shape(workspace, patch):
    if not isinstance(workspace, dict) or not isinstance(workspace.get("channels"), list) \
            or not workspace["channels"]:
        raise ValueError("workspace must be an object with a nonempty channels list")
    names = []
    for channel in workspace["channels"]:
        if not isinstance(channel, dict) or not isinstance(channel.get("name"), str) \
                or not isinstance(channel.get("samples"), list) or not channel["samples"]:
            raise ValueError("every workspace channel needs a name and a nonempty samples list")
        names.append(channel["name"])
    if len(set(names)) != len(names):
        raise ValueError("workspace channel names must be unique")
    if not isinstance(patch, list) or not all(isinstance(op, dict) for op in patch):
        raise ValueError("patch must be a JSON-patch list of operations")
    return names


# --------------------------------------------------------------------------- helpers

def _tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower()) if isinstance(text, str) else None


def _pairing(workspace, patch):
    """Run the structural pairing gate on the in-memory documents (it reads files)."""
    with tempfile.TemporaryDirectory(prefix="likelihood_appropriateness_") as td:
        bkg, sig = os.path.join(td, "bkg.json"), os.path.join(td, "patch.json")
        with open(bkg, "w") as fh:
            json.dump(workspace, fh)
        with open(sig, "w") as fh:
            json.dump(patch, fh)
        try:
            return check_pairing(bkg, sig)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"pairing check could not read the workspace or patch: {exc!r}") from exc


def _signal_samples(workspace, patch):
    """{channel name: [added sample values]} for the patch's add operations on samples."""
    channels = workspace["channels"]
    out = {}
    for op in patch:
        if op.get("op") != "add" or not isinstance(op.get("path"), str):
            continue
        m = _PATCH_PATH.match(op["path"])
        if not m or int(m.group(1)) >= len(channels) or not isinstance(op.get("value"), dict):
            continue
        out.setdefault(channels[int(m.group(1))]["name"], []).append(op["value"])
    return out


def _finding(code, evidence, reason, severity=None):
    return {"code": code, "severity": severity or FINDING_CODES[code], "evidence": evidence,
            "reason": reason}


def _verdict(findings):
    severities = {f["severity"] for f in findings}
    if "blocking" in severities:
        return "inappropriate"
    if "caution" in severities:
        return "appropriate-with-cautions"
    return "appropriate"


# --------------------------------------------------------------------------- the check

def assess(workspace, patch, *, channel_map=None, declared=None, selection=None,
           signal_yields=None, thresholds=None):
    """Compare a published likelihood with the run's signal patch, signal model and selection.

    Raises ValueError for malformed inputs. Returns the likelihood-appropriateness record
    (``inputs`` is left empty; the CLI fills it with the files it read).
    """
    names = _workspace_shape(workspace, patch)
    declared, selection = _declared(declared), _selection(selection)
    limits = _thresholds(thresholds)
    yields = _signal_yields(signal_yields, set(names))
    if channel_map is not None and not isinstance(channel_map, dict):
        raise ValueError("channel_map must be an object keyed by workspace channel")

    findings, checks = [], []
    paired, _n_channels, mismatches, _report = _pairing(workspace, patch)
    signal = _signal_samples(workspace, patch)
    untouched = [n for n in names if n not in signal]

    # pairing structure: every mismatch except the two classified below
    sr_unpatched = [m for m in mismatches if m.startswith(_SR_UNPATCHED)]
    no_normfactor = [m for m in mismatches if m.endswith(_NO_NORMFACTOR)]
    structural = [m for m in mismatches if m not in sr_unpatched and m not in no_normfactor]
    if structural:
        findings.append(_finding("patch-targets-outside-workspace", {"pairing_mismatches": structural},
                                 "the signal patch does not fit the published workspace structure"))
    checks.append({"name": "pairing-structure", "status": "finding" if structural else "pass",
                   "reason": (f"{len(structural)} structural pairing mismatch(es)" if structural
                              else "every patch target exists with matching bin counts")})

    # channel coverage
    if channel_map is not None:
        unknown = sorted(set(channel_map) - set(names))
        absent = [n for n in names if n not in channel_map]
        missing = [n for n in untouched if channel_map.get(n, "absent") is not None]
        declared_zero = [n for n in untouched if n in channel_map and channel_map[n] is None]
        evidence = {"basis": "channel-map", "missing": missing, "declared_zero": declared_zero,
                    "map_channels_not_in_workspace": unknown, "workspace_channels_not_in_map": absent}
        problem = bool(missing or unknown or absent)
        reason = ("workspace channels receive no signal and the channel map does not declare them "
                  "zero, or the map does not cover the workspace channel set exactly")
    else:
        missing = sorted(c for m in sr_unpatched for c in re.findall(r"'([^']+)'", m))
        declared_zero = []
        evidence = {"basis": "pairing-check", "missing": missing, "pairing_mismatches": sr_unpatched}
        problem = bool(sr_unpatched)
        reason = "signal-region channels receive no signal from the patch"
    if not signal:
        evidence["no_channel_receives_signal"] = True
        problem, reason = True, "the patch adds signal to no workspace channel"
    if problem:
        findings.append(_finding("missing-channels", evidence, reason))
    checks.append({"name": "channel-coverage", "status": "finding" if problem else "pass",
                   "reason": reason if problem else
                   f"{len(signal)} channel(s) receive signal; every other channel is accounted for"})

    # parameterisation: the POI and the modifier types the patch adds
    pois = sorted({m.get("config", {}).get("poi") for m in workspace.get("measurements") or []
                   if isinstance(m, dict) and isinstance(m.get("config", {}).get("poi"), str)})
    wrong_poi, foreign_types = [], []
    for channel, samples in sorted(signal.items()):
        for sample in samples:
            modifiers = [m for m in sample.get("modifiers") or [] if isinstance(m, dict)]
            norms = sorted(m.get("name") for m in modifiers if m.get("type") == "normfactor")
            if not set(norms) & set(pois):
                wrong_poi.append({"channel": channel, "sample": sample.get("name"), "normfactors": norms})
            extra = sorted({str(m.get("type")) for m in modifiers} - ALLOWED_MODIFIER_TYPES)
            if extra:
                foreign_types.append({"channel": channel, "sample": sample.get("name"), "types": extra})
    param_problem = bool(not pois or wrong_poi or foreign_types)
    if param_problem:
        findings.append(_finding("parameterisation-differs",
                                 {"workspace_pois": pois, "signal_without_poi_normfactor": wrong_poi,
                                  "unsupported_modifier_types": foreign_types,
                                  "allowed_modifier_types": sorted(ALLOWED_MODIFIER_TYPES),
                                  "pairing_mismatches": no_normfactor},
                                 ("the workspace declares no measurement POI" if not pois else
                                  "the signal parameterisation differs from the published measurement")))
    checks.append({"name": "parameterisation", "status": "finding" if param_problem else "pass",
                   "reason": ("signal normfactor or modifier types differ from the published model"
                              if param_problem else f"signal carries the POI {pois} with supported modifiers")})

    # signal model: declared versus simulated
    want, have = declared.get("signal_model"), selection.get("signal_model")
    if want is None or have is None:
        findings.append(_finding("signal-model-undeclared",
                                 {"declared": want, "selection": have},
                                 "the signal model is not declared on both sides; the comparison was not made"))
        checks.append({"name": "signal-model", "status": "not-evaluated",
                       "reason": "declared or selected signal model absent"})
    else:
        differs = [k for k in ("process", "final_state") if _tokens(want.get(k)) != _tokens(have.get(k))]
        if differs:
            findings.append(_finding("signal-model-differs",
                                     {"fields": differs, "declared": want, "selection": have},
                                     "the run's signal model differs from the one the likelihood was "
                                     "published for in " + ", ".join(differs)))
        checks.append({"name": "signal-model", "status": "finding" if differs else "pass",
                       "reason": ("differs in " + ", ".join(differs)) if differs else
                       "process and final state agree (normalised tokens)"})

    # selection identity
    want_id, have_id = declared.get("selection_identity"), selection.get("identity")
    if not want_id or not have_id:
        findings.append(_finding("selection-unverified", {"declared": want_id, "selection": have_id},
                                 "the selection identity is not recorded on both sides; the comparison was not made"))
        checks.append({"name": "selection-identity", "status": "not-evaluated",
                       "reason": "declared or run selection identity absent"})
    elif want_id != have_id:
        findings.append(_finding("selection-changed", {"declared": want_id, "selection": have_id},
                                 "the run's selection is not the one the likelihood was published for"))
        checks.append({"name": "selection-identity", "status": "finding", "reason": "identities differ"})
    else:
        checks.append({"name": "selection-identity", "status": "pass", "reason": "identities agree"})

    # channels without signal while others carry it (control regions without signal)
    reported_missing = set(missing) if problem else set()
    quiet = [n for n in untouched if n not in reported_missing] if signal else []
    limit = limits["max_unmodelled_control_fraction"]
    if quiet:
        fractions, over, unknown_yield = {}, [], []
        for channel in quiet:
            row = (yields or {}).get(channel)
            if row is None:
                unknown_yield.append(channel)
                continue
            fraction = (row["s"] / row["b"]) if row["b"] > 0 else (math.inf if row["s"] > 0 else 0.0)
            fractions[channel] = fraction if math.isfinite(fraction) else "infinite"
            if fraction > limit:
                over.append(channel)
        severity = "blocking" if over else "caution"
        findings.append(_finding("control-regions-without-signal",
                                 {"channels": quiet, "declared_zero": declared_zero,
                                  "unmodelled_fraction": fractions, "above_threshold": over,
                                  "max_unmodelled_control_fraction": limit},
                                 ("supplied signal yields put an unmodelled s/b above "
                                  f"{limit} in {over}" if over else
                                  "these channels receive no signal from the patch; signal contamination "
                                  "there is not modelled"), severity=severity))
        if unknown_yield:
            findings.append(_finding("cr-signal-contamination-unknown", {"channels": unknown_yield},
                                     "no signal yields were supplied for these channels"))
        checks.append({"name": "control-region-signal", "status": "finding",
                       "reason": f"{len(quiet)} channel(s) without signal"})
    else:
        checks.append({"name": "control-region-signal", "status": "pass" if signal else "not-evaluated",
                       "reason": "every channel receives signal" if signal else "no channel receives signal"})

    return {"schema_version": SCHEMA_VERSION, "kind": KIND, "verdict": _verdict(findings),
            "findings": findings, "checks": checks, "thresholds": limits, "inputs": [],
            "scope": SCOPE}


def validate_record(record):
    """Structural errors of a likelihood-appropriateness record ([] when valid)."""
    if not isinstance(record, dict):
        return ["record must be an object"]
    errors = []
    if record.get("kind") != KIND or record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"record must be kind {KIND!r} schema_version {SCHEMA_VERSION}")
    if record.get("verdict") not in VERDICTS:
        errors.append(f"verdict must be one of {VERDICTS}")
    findings = record.get("findings")
    if not isinstance(findings, list) or not all(
            isinstance(f, dict) and f.get("code") in FINDING_CODES and f.get("severity") in SEVERITIES
            for f in findings):
        errors.append("findings must be a list of coded findings")
    elif record.get("verdict") in VERDICTS and _verdict(findings) != record["verdict"]:
        errors.append(f"verdict {record['verdict']!r} disagrees with its findings ({_verdict(findings)!r})")
    return errors


def blocking_codes(record):
    """Sorted unique codes of a record's blocking findings."""
    return sorted({f["code"] for f in record.get("findings") or []
                   if isinstance(f, dict) and f.get("severity") == "blocking"})


# --------------------------------------------------------------------------- CLI

def _load(path, what):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return json.loads(raw), {"path": path, "sha256": hashlib.sha256(raw).hexdigest()}
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {what} {path}: {exc}") from exc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bkg", required=True, help="published background-only workspace")
    ap.add_argument("--patch", required=True, help="the run's signal patch")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--channel-map", help="channel map: workspace channel -> region or null")
    group.add_argument("--shipped-channel-map", metavar="ID", help="id of a shipped channel map")
    ap.add_argument("--declared", help="declared signal model and selection identity (JSON)")
    ap.add_argument("--selection", help="the run's selection identity and signal model (JSON)")
    ap.add_argument("--signal-yields", help="{channel: {s, b}} for channels the patch leaves without signal")
    ap.add_argument("--threshold-unmodelled-control-fraction", type=float, default=None,
                    help=f"blocking s/b threshold (default {DEFAULT_THRESHOLDS['max_unmodelled_control_fraction']})")
    ap.add_argument("--out", required=True, help="likelihood_appropriateness.json to write")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        inputs = []
        workspace, pin = _load(args.bkg, "workspace"); inputs.append(pin)
        patch, pin = _load(args.patch, "patch"); inputs.append(pin)
        mapping = None
        if args.channel_map:
            mapping, pin = _load(args.channel_map, "channel map"); inputs.append(pin)
        elif args.shipped_channel_map:
            from ravel.physics.sa2json_native import shipped_channel_map
            try:
                mapping, shipped = shipped_channel_map(args.shipped_channel_map)
            except (ValueError, OSError) as exc:
                raise ValueError(str(exc)) from exc
            inputs.append({"path": shipped["path"], "sha256": shipped["sha256"],
                           "shipped_channel_map": shipped["id"]})
        optional = {}
        for key, what in (("declared", "declared metadata"), ("selection", "selection metadata"),
                          ("signal_yields", "signal yields")):
            path = getattr(args, key)
            if path:
                optional[key], pin = _load(path, what); inputs.append(pin)
        thresholds = None
        if args.threshold_unmodelled_control_fraction is not None:
            thresholds = {"max_unmodelled_control_fraction": args.threshold_unmodelled_control_fraction}
        record = assess(workspace, patch, channel_map=mapping, thresholds=thresholds, **optional)
    except ValueError as exc:
        print(f"likelihood_appropriateness: {exc}", file=sys.stderr)
        return 2
    record["inputs"] = copy.deepcopy(inputs)
    outdir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(outdir, exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(record, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, args.out)
    for finding in record["findings"]:
        print(f"[{finding['severity']}] {finding['code']}: {finding['reason']}")
    print(f"likelihood appropriateness: {record['verdict']} -> {args.out}")
    return 1 if record["verdict"] == "inappropriate" else 0


if __name__ == "__main__":
    sys.exit(main())
