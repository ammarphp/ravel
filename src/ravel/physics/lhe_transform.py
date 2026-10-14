"""Declarative, streaming LHE particle rewrites between generation and shower.

A rule set names particles by (status, PDG set) and gives each a new PDG code and,
optionally, a new mass column. Nothing else in the file changes: the header, the
<init> block, every event weight, colour line and four-momentum stay byte for
byte. A second pass proves that, the original file is pinned by hash, and the
receipt counts every change.

Rules that change electric charge, lepton or baryon number, or that touch
non-incoming particles, are refused unless the rule declares the change with a
rationale. A charge change leaves the event charge-unbalanced, so the receipt
requires ``Check:event = off`` in the Pythia settings and lists the change as a
deviation for the run record and the CHECK-IN text.

Example: a photon-PDF proxy relabels incoming leptons from a lepton-in-proton
PDF as photons (status -1, PDG +-11/13/15 -> 22, mass 0). The SVJ dark-flavour
remap is another instance (``data/lhe_transforms/svj-dark-flavour.json``).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

SCHEMA_VERSION = 1
DECLARATIONS = ("touches_outgoing", "changes_charge", "changes_lepton_number", "changes_baryon_number")
STATUSES = (-1, 1, 2, -2, 3, -9)
MAX_RULES = 64
CHECK_EVENT_OFF = "Check:event = off"

# Standard Model quantum numbers: (3 x charge, colour representation, lepton number, 3 x baryon number).
_SM = {1: (-1, 3, 0, 1), 2: (2, 3, 0, 1), 3: (-1, 3, 0, 1), 4: (2, 3, 0, 1), 5: (-1, 3, 0, 1), 6: (2, 3, 0, 1),
       11: (-3, 1, 1, 0), 13: (-3, 1, 1, 0), 15: (-3, 1, 1, 0), 12: (0, 1, 1, 0), 14: (0, 1, 1, 0), 16: (0, 1, 1, 0),
       21: (0, 8, 0, 0), 22: (0, 1, 0, 0), 23: (0, 1, 0, 0), 24: (3, 1, 0, 0), 25: (0, 1, 0, 0)}
_SELF_CONJUGATE = {21, 22, 23, 25}


def quantum_numbers(pdg, particle_data):
    """(charge3, colour, lepton, baryon3) of a PDG code; antiparticles flip charges."""
    key = str(abs(pdg))
    if key in particle_data:
        row = particle_data[key]
        base = (row["charge3"], row["colour"], row.get("lepton", 0), row.get("baryon3", 0))
        conjugate = row.get("self_conjugate", False)
    elif abs(pdg) in _SM:
        base = _SM[abs(pdg)]
        conjugate = abs(pdg) in _SELF_CONJUGATE
    else:
        raise ValueError(f"PDG {pdg} has no known quantum numbers; declare it in particle_data")
    charge, colour, lepton, baryon = base
    if pdg < 0:
        if conjugate:
            raise ValueError(f"PDG {pdg}: a self-conjugate particle has no negative code")
        charge, lepton, baryon = -charge, -lepton, -baryon
        colour = -colour if colour == 3 else colour
    return charge, colour, lepton, baryon


def _keys(value, required, optional, label):
    if type(value) is not dict:
        raise ValueError(f"{label} must be an object")
    missing = set(required) - set(value)
    extra = set(value) - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f"{label}: missing {sorted(missing)} unknown {sorted(extra)}")


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def validate_rules(doc):
    """Check a rule document and return its normalized form plus its implications."""
    _keys(doc, ("schema_version", "kind", "name", "rationale", "rules"),
          ("approximation", "particle_data", "downstream_settings"), "LHE transform rules")
    if doc["schema_version"] != SCHEMA_VERSION or type(doc["schema_version"]) is not int or doc["kind"] != "lhe_transform_rules":
        raise ValueError("lhe_transform_rules schema 1 required")
    _text(doc["name"], "name")
    _text(doc["rationale"], "rationale")
    if "approximation" in doc:
        _text(doc["approximation"], "approximation")
    data = doc.get("particle_data", {})
    if type(data) is not dict:
        raise ValueError("particle_data must map PDG codes to quantum numbers")
    for key, row in data.items():
        if not re.fullmatch(r"[1-9][0-9]{0,8}", key):
            raise ValueError(f"particle_data key must be a positive PDG code, not {key!r}")
        _keys(row, ("charge3", "colour"), ("lepton", "baryon3", "self_conjugate"), f"particle_data[{key}]")
        if row["colour"] not in (1, 3, 8) or any(type(row.get(k, 0)) is not int for k in ("charge3", "lepton", "baryon3")):
            raise ValueError(f"particle_data[{key}]: integer charge3/lepton/baryon3 and colour 1, 3 or 8 required")
    settings = doc.get("downstream_settings", [])
    if type(settings) is not list or any(type(s) is not str or "=" not in s for s in settings):
        raise ValueError("downstream_settings must be a list of 'Key = value' Pythia settings")
    rules = doc["rules"]
    if type(rules) is not list or not 1 <= len(rules) <= MAX_RULES:
        raise ValueError(f"supply 1..{MAX_RULES} rules")
    seen_ids, claimed = set(), {}
    breaks = set()
    for rule in rules:
        _keys(rule, ("id", "match", "replace_pdg", "rationale"), ("mass_gev", "preserve_sign", "declares"), "rule")
        rid = rule["id"]
        if type(rid) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", rid) or rid in seen_ids:
            raise ValueError(f"rule id must be a unique identifier, not {rid!r}")
        seen_ids.add(rid)
        _text(rule["rationale"], f"rule {rid} rationale")
        _keys(rule["match"], ("status", "pdg"), (), f"rule {rid} match")
        statuses, pdgs = rule["match"]["status"], rule["match"]["pdg"]
        if (type(statuses) is not list or not statuses or any(s not in STATUSES or type(s) is not int for s in statuses)
                or type(pdgs) is not list or not pdgs or any(type(p) is not int or p == 0 for p in pdgs)):
            raise ValueError(f"rule {rid}: match needs nonempty status (from {STATUSES}) and nonzero PDG lists")
        target = rule["replace_pdg"]
        if type(target) is not int or target == 0:
            raise ValueError(f"rule {rid}: replace_pdg must be a nonzero PDG code")
        preserve = rule.get("preserve_sign", False)
        if type(preserve) is not bool:
            raise ValueError(f"rule {rid}: preserve_sign must be true or false")
        if "mass_gev" in rule and (type(rule["mass_gev"]) not in (int, float) or not math.isfinite(rule["mass_gev"])
                                   or rule["mass_gev"] < 0):
            raise ValueError(f"rule {rid}: mass_gev must be a finite non-negative number")
        declares = rule.get("declares", [])
        if type(declares) is not list or any(d not in DECLARATIONS for d in declares) or len(set(declares)) != len(declares):
            raise ValueError(f"rule {rid}: declares must list distinct items from {DECLARATIONS}")
        for status in statuses:
            for pdg in pdgs:
                if (status, pdg) in claimed:
                    raise ValueError(f"(status {status}, PDG {pdg}) is matched by rules {claimed[(status, pdg)]} and {rid}")
                claimed[(status, pdg)] = rid
        if any(s != -1 for s in statuses) and "touches_outgoing" not in declares:
            raise ValueError(f"rule {rid} rewrites non-incoming particles; declare touches_outgoing with its rationale")
        for pdg in pdgs:
            new = new_pdg(rule, pdg)
            before, after = quantum_numbers(pdg, data), quantum_numbers(new, data)
            if before[1] != after[1]:
                raise ValueError(f"rule {rid}: {pdg} -> {new} changes the colour representation; "
                                 "colour-flow columns cannot stay consistent")
            for index, flag in ((0, "changes_charge"), (2, "changes_lepton_number"), (3, "changes_baryon_number")):
                if before[index] != after[index]:
                    if flag not in declares:
                        raise ValueError(f"rule {rid}: {pdg} -> {new} {flag.replace('_', ' ')}; declare {flag} with its rationale")
                    breaks.add(flag)
    required = list(settings)
    if "changes_charge" in breaks and not any(_setting_key(s) == "check:event" for s in required):
        required.append(CHECK_EVENT_OFF)
    for s in required:
        if _setting_key(s) == "check:event" and _setting_value(s) not in ("off", "false", "0"):
            raise ValueError("a charge-changing transform cannot run with Check:event on")
    return {"claimed": claimed, "breaks": sorted(breaks), "required_settings": required}


def new_pdg(rule, pdg):
    target = rule["replace_pdg"]
    if rule.get("preserve_sign", False):
        return -abs(target) if pdg < 0 else abs(target)
    return target


def _setting_key(text):
    return text.split("=", 1)[0].strip().lower()


def _setting_value(text):
    return text.split("=", 1)[1].strip().lower() if "=" in text else ""


def missing_settings(receipt, settings):
    """Required downstream settings absent from a Pythia settings list."""
    have = {_setting_key(s): _setting_value(s) for s in settings}
    return [s for s in receipt["required_downstream_settings"]
            if have.get(_setting_key(s)) != _setting_value(s)]


def _open(path, mode):
    path = Path(path)
    if path.name.endswith(".gz"):
        if "w" in mode or "x" in mode:
            raw = path.open("xb")
            return gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0), raw
        return gzip.open(path, "rb"), None
    return path.open("xb" if ("w" in mode or "x" in mode) else "rb"), None


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pin(path):
    path = Path(path).absolute()
    return {"path": str(path), "sha256": sha256(path), "size": path.stat().st_size}


_TOKEN = re.compile(rb"\S+")


def _number(token):
    value = float(token.replace(b"D", b"e").replace(b"d", b"e"))
    if not math.isfinite(value):
        raise ValueError("nonfinite LHE number")
    return value


def _format_mass(value):
    return repr(float(value)).encode() if value else b"0.0"


class _Stream:
    """Line-level LHE walker that yields (kind, line, event_index, row_index)."""

    def __init__(self):
        self.state = "outside"
        self.events = 0
        self.inits = 0
        self.remaining = 0

    def classify(self, line):
        text = line.strip()
        if self.state == "outside":
            if text.startswith(b"<init"):
                self.inits += 1
                if self.events:
                    raise ValueError("<init> after events")
                self.state = "init"
                return "init"
            if text.startswith(b"<event"):
                if not text.endswith(b">") or text.count(b">") != 1:
                    raise ValueError("event data on the <event> tag line is not supported")
                self.state = "event_header"
                self.events += 1
                return "event"
            return "other"
        if self.state == "init":
            if text.startswith(b"</init>"):
                self.state = "outside"
            return "init"
        if self.state == "event_header":
            if not text or text.startswith(b"#"):
                return "event"
            fields = text.split()
            if len(fields) != 6:
                raise ValueError(f"event {self.events}: invalid event header")
            self.remaining = int(fields[0])
            if self.remaining < 1:
                raise ValueError(f"event {self.events}: no particles")
            self.state = "particles"
            return "event_header"
        if self.state == "particles":
            self.remaining -= 1
            if self.remaining == 0:
                self.state = "event_tail"
            return "particle"
        if self.state == "event_tail":
            if text.startswith(b"</event>"):
                self.state = "outside"
            elif text.startswith(b"<event"):
                raise ValueError("nested <event>")
            return "event"
        raise AssertionError(self.state)


def _balance(rows):
    """Largest component of sum(incoming) - sum(outgoing), relative to the incoming energy."""
    incoming = [sum(r[i] for r in rows if r[4] == -1) for i in range(4)]
    outgoing = [sum(r[i] for r in rows if r[4] == 1) for i in range(4)]
    scale = max(1.0, abs(incoming[3]))
    return max(abs(a - b) for a, b in zip(incoming, outgoing)) / scale


def transform(source, output, rules, *, tolerance=1e-6):
    """Apply ``rules`` (a validated document) to ``source``; write ``output`` and a receipt.

    Returns the receipt. ``output`` must not exist. The receipt is written next to
    ``output`` as ``<output name>.transform.json``.
    """
    implied = validate_rules(rules)
    source, output = Path(source).absolute(), Path(output).absolute()
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"original LHE must be a regular file: {source}")
    if output.exists() or output == source:
        raise ValueError(f"fresh output path required: {output}")
    receipt_path = output.with_name(output.name + ".transform.json")
    if receipt_path.exists():
        raise ValueError(f"receipt already exists: {receipt_path}")
    original = pin(source)
    by_key = implied["claimed"]
    by_id = {rule["id"]: rule for rule in rules["rules"]}
    census = {rule["id"]: {} for rule in rules["rules"]}
    stream = _Stream()
    events_changed, residual = 0, 0.0
    current_rows, current_changed, particle_index = [], False, 0
    reader, _ = _open(source, "r")
    writer, raw = _open(output, "w")
    try:
        with reader:
            for line in reader:
                kind = stream.classify(line)
                if kind == "event_header":
                    current_rows, current_changed, particle_index = [], False, 0
                if kind == "particle":
                    line, changed, row = _rewrite_particle(line, stream.events, particle_index, by_key, by_id,
                                                           census, tolerance)
                    particle_index += 1
                    current_rows.append(row)
                    current_changed |= changed
                    if stream.state == "event_tail":
                        residual = max(residual, _balance(current_rows))
                        events_changed += current_changed
                writer.write(line)
        if stream.state != "outside" or stream.inits != 1 or stream.events < 1:
            raise ValueError("incomplete LHE: one <init> and complete events required")
    except BaseException:
        writer.close()
        if raw:
            raw.close()
        output.replace(output.with_name("failed-" + output.name))
        raise
    writer.close()
    if raw:
        raw.close()
    if pin(source) != original:
        raise ValueError("original LHE changed during the transform")
    proof = verify_pair(source, output, rules, tolerance=tolerance)
    if proof["events"] != stream.events or proof["changed_rows"] != sum(sum(c.values()) for c in census.values()):
        raise ValueError("verification pass disagrees with the rewrite census")
    deviations = [f"LHE transform '{rules['name']}': rule {r['id']} rewrites status {r['match']['status']} PDG "
                  f"{r['match']['pdg']} to {r['replace_pdg']}" + (f" with mass {r['mass_gev']} GeV" if "mass_gev" in r else "")
                  + f" ({r['rationale']})" for r in rules["rules"] if census[r["id"]]]
    if implied["breaks"]:
        deviations.append("Declared bookkeeping changes: " + ", ".join(b.replace("_", " ") for b in implied["breaks"]) + ".")
    receipt = {
        "schema_version": 1, "kind": "lhe_transform", "name": rules["name"], "rationale": rules["rationale"],
        "approximation": rules.get("approximation"),
        "rules": rules, "rules_sha256": hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest(),
        "original": original, "output": pin(output), "events": stream.events, "events_changed": events_changed,
        "census": {rid: dict(sorted(rows.items())) for rid, rows in census.items()},
        "invariants": {"event_count": True, "init_unchanged": True, "header_unchanged": True,
                       "weights_unchanged": True, "momenta_unchanged": True, "colour_unchanged": True,
                       "max_momentum_imbalance": residual},
        "declared_changes": implied["breaks"], "required_downstream_settings": implied["required_settings"],
        "deviations": deviations,
        "checkin_text": ("Events pass through the declared LHE transform '" + rules["name"] + "' before the shower: "
                         + "; ".join(deviations) + (" Pythia must run with " + ", ".join(implied["required_settings"]) + "."
                                                    if implied["required_settings"] else "")),
        "physics_validated": False,
    }
    with receipt_path.open("x") as stream_out:
        stream_out.write(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    return receipt


def _rewrite_particle(line, event, index, by_key, by_id, census, tolerance):
    tokens = list(_TOKEN.finditer(line))
    if len(tokens) != 13:
        raise ValueError(f"event {event}: particle row needs 13 fields")
    pdg, status = int(tokens[0].group()), int(tokens[1].group())
    values = [_number(t.group()) for t in tokens[6:11]]
    row = (*values[:4], status)
    rid = by_key.get((status, pdg))
    if rid is None:
        return line, False, row
    rule = by_id[rid]
    new = new_pdg(rule, pdg)
    edits = [(tokens[0].start(), tokens[0].end(), str(new).encode())]
    if "mass_gev" in rule:
        mass = float(rule["mass_gev"])
        px, py, pz, energy = values[:4]
        m2 = energy * energy - px * px - py * py - pz * pz
        if abs(m2 - mass * mass) > tolerance * max(1.0, energy * energy):
            raise ValueError(f"event {event} particle {index + 1}: mass reset to {mass} GeV breaks E^2 - p^2 = m^2 "
                             f"(E^2 - p^2 = {m2:.6g}); this transform never changes momenta")
        edits.append((tokens[10].start(), tokens[10].end(), _format_mass(mass)))
    out = bytearray()
    cursor = 0
    for a, b, text in edits:
        out += line[cursor:a] + text
        cursor = b
    out += line[cursor:]
    key = f"{pdg}->{new}"
    census[rid][key] = census[rid].get(key, 0) + 1
    return bytes(out), True, row


def verify_pair(original, derived, rules, *, tolerance=1e-6):
    """Second pass: every line outside particle rows is identical, and particle rows
    differ only in the PDG and mass fields that the rules allow."""
    implied = validate_rules(rules)
    by_key, by_id = implied["claimed"], {rule["id"]: rule for rule in rules["rules"]}
    a, _ = _open(original, "r")
    b, _ = _open(derived, "r")
    walk = _Stream()
    changed = 0
    with a, b:
        for left in a:
            right = b.readline()
            kind = walk.classify(left)
            if kind != "particle":
                if left != right:
                    raise ValueError(f"event {walk.events}: a line outside the particle rows changed")
                continue
            lt, rt = left.split(), right.split()
            if len(rt) != 13:
                raise ValueError(f"event {walk.events}: derived particle row is malformed")
            pdg, status = int(lt[0]), int(lt[1])
            rid = by_key.get((status, pdg))
            if rid is None:
                if left != right:
                    raise ValueError(f"event {walk.events}: an unmatched particle row changed")
                continue
            rule = by_id[rid]
            if int(rt[0]) != new_pdg(rule, pdg) or lt[1:10] != rt[1:10] or lt[11:] != rt[11:]:
                raise ValueError(f"event {walk.events}: particle row changed beyond its rule")
            if "mass_gev" in rule:
                if _number(rt[10]) != float(rule["mass_gev"]):
                    raise ValueError(f"event {walk.events}: mass column differs from the rule")
            elif lt[10] != rt[10]:
                raise ValueError(f"event {walk.events}: mass column changed without a mass rule")
            changed += 1
        if b.readline():
            raise ValueError("derived LHE has extra content")
    return {"events": walk.events, "changed_rows": changed}


def load_rules(path):
    from ravel.workflow.state_io import read_json
    doc = read_json(Path(path))
    validate_rules(doc)
    return doc


# Science-mode protocol: task {"input": LHE path, "rules": rules JSON path}.

def validate(task):
    _keys(task, ("input", "rules"), (), "lhe-transform task")
    for key in ("input", "rules"):
        _text(task[key], key)
    return dict(task)


def _path(value, base):
    p = Path(value)
    p = p if p.is_absolute() else Path(base) / p
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"regular file required: {p}")
    return p.resolve()


def inputs(task, base):
    validate(task)
    rules = _path(task["rules"], base)
    load_rules(rules)
    return [_path(task["input"], base), rules]


def execution_seconds(task, base):
    size = _path(task["input"], base).stat().st_size
    return max(60, int(size / 2e6))


def run(task, base, output):
    validate(task)
    source = _path(task["input"], base)
    rules = load_rules(_path(task["rules"], base))
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    name = "transformed.lhe.gz" if source.name.endswith(".gz") else "transformed.lhe"
    receipt = transform(source, out / name, rules)
    result = {"schema_version": 1, "kind": "lhe-transform", "status": "passed",
              "receipt": pin(out / (name + ".transform.json")), "events": receipt["events"],
              "events_changed": receipt["events_changed"], "census": receipt["census"],
              "required_downstream_settings": receipt["required_downstream_settings"],
              "deviations": receipt["deviations"], "physics_validated": False}
    with (out / "lhe-transform.json").open("x") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def census(source, rules):
    """Read-only count of the rows each rule would change; nothing is written."""
    implied = validate_rules(rules)
    by_key = implied["claimed"]
    counts = {rule["id"]: {} for rule in rules["rules"]}
    by_id = {rule["id"]: rule for rule in rules["rules"]}
    walk = _Stream()
    reader, _ = _open(source, "r")
    with reader:
        for line in reader:
            if walk.classify(line) != "particle":
                continue
            fields = line.split()
            pdg, status = int(fields[0]), int(fields[1])
            rid = by_key.get((status, pdg))
            if rid is not None:
                key = f"{pdg}->{new_pdg(by_id[rid], pdg)}"
                counts[rid][key] = counts[rid].get(key, 0) + 1
    return {"events": walk.events, "census": counts, "declared_changes": implied["breaks"],
            "required_downstream_settings": implied["required_settings"]}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ravel lhe-transform",
        description="Check an LHE transform rule document, optionally counting its matches in an LHE file. "
                    "Applying a transform is a science study (mode lhe-transform) or part of approved scoped generation.")
    parser.add_argument("action", choices=("check",))
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--input", type=Path, help="LHE file to count matches in (read only)")
    args = parser.parse_args(argv)
    rules = load_rules(args.rules)
    if args.input:
        print(json.dumps(census(args.input, rules), indent=2))
        return 0
    implied = validate_rules(rules)
    print(json.dumps({"declared_changes": implied["breaks"],
                      "required_downstream_settings": implied["required_settings"],
                      "matches": sorted(f"status {s} PDG {p} -> rule {r}" for (s, p), r in implied["claimed"].items())},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
