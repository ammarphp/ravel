"""Normalization evidence for the bounded unmerged native pipeline (stdlib only).

Cross sections in an LHE init block are pb by the LHE convention. The native
Pythia writer reports mb explicitly. Neither a missing rate nor a missing event
weight has a numerical fallback. This validates normalization bookkeeping, not
the physical accuracy of a generator, detector card or correction.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from decimal import Decimal


def positive(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} is unresolved or not numeric") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return result


def fingerprint(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest()}


def weight_summary(weights):
    values = list(map(float, weights))
    if not values or any(not math.isfinite(v) for v in values):
        raise ValueError("nominal event weights must be present and finite")
    try:
        total, squared = math.fsum(values), math.fsum(v*v for v in values)
    except OverflowError as exc:
        raise ValueError("nominal event weight sums overflow") from exc
    # A positive physical cross section may include negative individual weights,
    # but cannot normalize a non-positive total by silently reversing its sign.
    positive(total, "sum of nominal event weights")
    positive(squared, "sum of squared nominal event weights")
    return {"n_events": len(values), "sumw": total, "sumw2": squared,
            "negative_weights": sum(v < 0 for v in values)}


def read_lhe(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    init, weights, rows = [], [], []
    in_init = in_event = False
    init_metadata = False
    closed = False
    with opener(path, "rt") as stream:
        for raw in stream:
            # A hash starts a numeric-record comment, but is legitimate inside
            # XML metadata (for example a generator URL fragment or text).
            line = (raw.strip() if in_init and (init_metadata or raw.lstrip().startswith("<"))
                    else raw.split("#", 1)[0].strip())
            if line == "<init>":
                if init:
                    raise ValueError("multiple LHE init blocks")
                in_init = True
            elif line == "</init>":
                in_init = False
            elif in_init and line:
                init_metadata = init_metadata or line.startswith("<")
                init.append(line)
            elif line == "<event>":
                if in_event:
                    raise ValueError("unterminated LHE event")
                in_event, rows = True, []
            elif line == "</event>":
                if not in_event or not rows:
                    raise ValueError("empty or malformed LHE event")
                header = rows[0]
                try:
                    particles = int(header[0])
                    if particles < 1 or len(rows) < particles + 1:
                        raise ValueError("truncated particle rows")
                    weights.append(float(header[2]))
                except (ValueError, IndexError) as exc:
                    raise ValueError("invalid LHE event header/particle count") from exc
                in_event = False
            elif in_event and line and not line.startswith("<"):
                rows.append(line.split())
            elif line == "</LesHouchesEvents>":
                closed = True
    if in_event or in_init or not closed:
        raise ValueError("truncated LHE document")
    try:
        header = init[0].split()
        if len(header) != 10:
            raise ValueError("invalid LHE init header")
        nprocess = int(header[9])
        if nprocess < 1 or len(init) < nprocess + 1:
            raise ValueError("LHE subprocess count does not match init block")
        process_rows = [row.split() for row in init[1:nprocess+1]]
        if any(len(row) != 4 for row in process_rows):
            raise ValueError("invalid LHE subprocess row")
        process_ids = [int(row[3]) for row in process_rows]
        if len(set(process_ids)) != nprocess:
            raise ValueError("duplicate LHE subprocess ID")
        # LHEF permits XML metadata after the numeric init block. MadGraph's
        # <generator> element is not another subprocess. Accept well-formed
        # metadata but never swallow extra numeric rows or malformed tags.
        metadata = "\n".join(init[nprocess+1:])
        if metadata:
            try:
                tree = ET.fromstring("<metadata>" + metadata + "</metadata>")
            except ET.ParseError as exc:
                raise ValueError("malformed LHE init metadata") from exc
            if (tree.text or "").strip() or any((child.tail or "").strip() for child in tree):
                raise ValueError("extra numeric or untagged content in LHE init block")
        rates = [positive(row[0], "LHE subprocess cross section (pb)") for row in process_rows]
        for row in process_rows:
            uncertainty, maximum_weight = float(row[1]), float(row[2])
            if not all(math.isfinite(x) and x >= 0 for x in (uncertainty, maximum_weight)):
                raise ValueError("invalid LHE subprocess uncertainty or maximum weight")
        sigma = positive(math.fsum(rates), "LHE cross section (pb)")
    except (IndexError, OverflowError) as exc:
        raise ValueError("missing or malformed LHE cross section") from exc
    return {"cross_section_pb": sigma, **weight_summary(weights)}


def reconcile_weights(raw, normalized, xs_pb, *, rel_tol=2e-6):
    """Check every converted nominal weight, including negative weights."""
    before = weight_summary(raw)
    after = weight_summary(normalized)
    xs_pb = positive(xs_pb, "applied cross section (pb)")
    if len(raw) != len(normalized):
        raise ValueError("conversion changed event count")
    scale = xs_pb / before["sumw"]
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("weight normalization scale is unusable")
    for old, new in zip(raw, normalized):
        expected = float(old) * scale
        if not math.isclose(float(new), expected, rel_tol=rel_tol, abs_tol=abs(scale)*1e-12):
            raise ValueError("converted nominal weights do not match declared cross-section normalization")
    if not math.isclose(after["sumw"], xs_pb, rel_tol=rel_tol):
        raise ValueError("converted weight sum does not reproduce cross section")
    return {"raw": before, "normalized": after, "scale_pb_per_weight": scale,
            "applied_cross_section_pb": xs_pb, "luminosity_applied": False}


def resolve_normalization(lhe, madgraph_log, shower_log, kfactor, nevents):
    evidence = read_lhe(lhe)
    kfactor = positive(kfactor, "explicit kfactor")  # k < 1 is allowed.
    if type(nevents) is not int or nevents < 1:
        raise ValueError("requested event count must be a positive integer")
    if evidence["n_events"] != nevents:
        raise ValueError("generated event count differs from the execution plan")
    # The LHE rate is authoritative. A log is only a corroborating representation
    # and may omit the summary on resumed generator runs.
    rate = evidence["cross_section_pb"]
    text = Path(madgraph_log).read_text(errors="replace")
    records = re.findall(r"Cross-section[^\n]*", text)
    if records:
        match = re.fullmatch(r"Cross-section\s*:\s*(\S+)(?:\s+\+-\s+\S+)?\s+(\w+)\s*", records[-1])
        if not match or match[2] != "pb":
            raise ValueError("MadGraph cross-section summary has unsupported units")
        value = match[1]
        reported = positive(value, "MadGraph cross section")
        precision = float(Decimal(1).scaleb(Decimal(value).as_tuple().exponent))/2
        if not math.isclose(reported, rate, rel_tol=1e-8, abs_tol=precision):
            raise ValueError("MadGraph log and LHE cross sections disagree")
    shower = re.findall(r"pythia_shower:\s*wrote\s+(\d+)\s+events;\s*sigma\s*=\s*([^\s]+)\s+(\w+)",
                        Path(shower_log).read_text(errors="replace"))
    if len(shower) != 1:
        raise ValueError("missing or ambiguous native shower normalization report")
    count, value, unit = shower[0]
    if unit != "mb":
        raise ValueError("native shower cross section must be explicitly in mb")
    shower_pb = positive(value, "shower cross section (mb)") * 1e9
    if int(count) != nevents:
        raise ValueError("unmerged shower did not preserve the generated event count")
    if not math.isfinite(shower_pb) or not math.isclose(rate, shower_pb, rel_tol=1e-4):
        raise ValueError("unmerged shower and LHE cross sections disagree")
    applied = positive(rate * kfactor, "corrected cross section (pb)")
    return {"schema_version": 1, "status": "resolved", "basis": "unmerged_lo_lhe",
            "cross_section_pb": rate, "kfactor": kfactor, "applied_cross_section_pb": applied,
            "correction_applications": 1, "luminosity_applied": False,
            "generation": evidence, "shower": {"n_events": int(count), "cross_section_pb": shower_pb},
            "sources": [fingerprint(p) for p in (lhe, madgraph_log, shower_log)]}


def load_normalization(path):
    record = json.loads(Path(path).read_text())
    if record.get("status") != "resolved" or record.get("luminosity_applied") is not False:
        raise ValueError("normalization is unresolved or luminosity was already applied")
    base = positive(record.get("cross_section_pb"), "cross section (pb)")
    correction = positive(record.get("kfactor"), "explicit correction")
    applied = positive(record.get("applied_cross_section_pb"), "applied cross section (pb)")
    if record.get("correction_applications") != 1 or not math.isclose(base*correction, applied, rel_tol=1e-12):
        raise ValueError("cross-section corrections do not reconcile exactly once")
    for source in record.get("sources", []):
        if fingerprint(source["path"])["sha256"] != source["sha256"]:
            raise ValueError("normalization source changed")
    if not record.get("sources"):
        raise ValueError("normalization lacks source evidence")
    sources=record["sources"]
    if len(sources)!=3 or not isinstance(record.get("generation"),dict):
        raise ValueError("normalization requires LHE, MadGraph and shower evidence")
    expected=resolve_normalization(*(source["path"] for source in sources),correction,record["generation"].get("n_events"))
    if record!=expected:
        raise ValueError("normalization fields do not reconcile with generated/showered evidence")
    return record


# ---------------------------------------------------------------------------
# Branching and filter factors from declared decay settings.
#
# A forced-decay or filtered sample covers only part of the inclusive rate. The
# factor is derived from the decay settings actually used (Pythia onMode
# commands, MadSpin decay lines, SLHA decay tables) and generator filter counts,
# against a declared physical decay table. Each factor is applied once.

_PYTHIA = re.compile(r'^\s*(-?\d+)\s*:\s*([A-Za-z]+)\s*=\s*(.*?)\s*$')
_MATCHERS = {'onIfAny': ('any', 1), 'offIfAny': ('any', 0), 'onPosIfAny': ('any', 2), 'onNegIfAny': ('any', 3),
             'onIfAll': ('all', 1), 'offIfAll': ('all', 0), 'onPosIfAll': ('all', 2), 'onNegIfAll': ('all', 3),
             'onIfMatch': ('match', 1), 'offIfMatch': ('match', 0), 'onPosIfMatch': ('match', 2),
             'onNegIfMatch': ('match', 3)}
_MG5_NAMES = {'d': 1, 'u': 2, 's': 3, 'c': 4, 'b': 5, 't': 6, 'e-': 11, 've': 12, 'mu-': 13, 'vm': 14,
              'ta-': 15, 'vt': 16, 'g': 21, 'a': 22, 'z': 23, 'w+': 24, 'h': 25,
              'd~': -1, 'u~': -2, 's~': -3, 'c~': -4, 'b~': -5, 't~': -6, 'e+': -11, 've~': -12, 'mu+': -13,
              'vm~': -14, 'ta+': -15, 'vt~': -16, 'w-': -24}
_MG5_MULTI = {'l+': [-11, -13], 'l-': [11, 13], 'vl': [12, 14, 16], 'vl~': [-12, -14, -16],
              'j': [21, 1, 2, 3, 4, -1, -2, -3, -4], 'p': [21, 1, 2, 3, 4, -1, -2, -3, -4]}


def _channel_key(daughters):
    return tuple(sorted(int(d) for d in daughters))


def _abs_key(daughters):
    return tuple(sorted(abs(int(d)) for d in daughters))


def _decay_tables(settings, base_dir):
    tables, sources = {}, []
    for key, table in (settings.get('decay_tables') or {}).items():
        if not isinstance(table, dict) or not isinstance(table.get('source'), str) or not table['source'].strip():
            raise ValueError(f'decay table {key} needs its source')
        if table.get('complete') is not True:
            raise ValueError(f'decay table {key} must be the complete physical table (complete: true)')
        rows = [(_channel_key(c['daughters']), float(c['br'])) for c in table['channels']]
        tables[abs(int(key))] = rows
        sources.append({'particle': abs(int(key)), 'source': table['source']})
    if settings.get('slha'):
        from ravel.physics import declared_study, simplified_spectrum
        path = declared_study.pinned(settings['slha'], base_dir)
        doc = simplified_spectrum.parse_slha(path.read_text())
        for pdg, decay in doc['decays'].items():
            if decay['channels'] and abs(pdg) not in tables:
                rows = [(_channel_key(d), br) for br, d in decay['channels']]
                if not math.isclose(math.fsum(br for _, br in rows), 1.0, abs_tol=1e-4):
                    raise ValueError(f'SLHA decay table {pdg} is not complete (branching fractions do not sum to one)')
                tables[abs(pdg)] = rows
        sources.append({'slha': str(path), 'sha256': fingerprint(path)['sha256']})
    for pdg, rows in tables.items():
        total = math.fsum(br for _, br in rows)
        if any(br < 0 for _, br in rows) or not math.isclose(total, 1.0, abs_tol=1e-4):
            raise ValueError(f'decay table {pdg} must be complete: branching fractions sum to {total:.6g}')
    return tables, sources


def _pythia_modes(commands, tables):
    """Replay Pythia decay-table commands in order -> {pdg: [(daughters, mode)]} for touched particles."""
    state = {}
    for command in commands:
        match = _PYTHIA.match(command)
        if not match:
            raise ValueError(f'unparsed Pythia command {command!r}')
        pdg, verb, argument = abs(int(match[1])), match[2], match[3]
        if pdg not in tables:
            raise ValueError(f'Pythia command for {pdg} needs its declared physical decay table')
        channels = state.setdefault(pdg, [[key, 1] for key, _ in tables[pdg]])
        if verb == 'onMode':
            value = {'on': 1, 'off': 0, 'true': 1, 'false': 0}.get(argument.lower(), argument)
            mode = int(value)
            if mode not in (0, 1, 2, 3):
                raise ValueError(f'onMode must be 0..3 in {command!r}')
            for channel in channels:
                channel[1] = mode
        elif verb in _MATCHERS:
            kind, mode = _MATCHERS[verb]
            products = sorted(abs(int(x)) for x in argument.split())
            for channel in channels:
                daughters = sorted(abs(d) for d in channel[0])
                if kind == 'any':
                    hit = any(p in daughters for p in products)
                else:
                    remaining = list(daughters)
                    hit = True
                    for p in products:
                        if p in remaining:
                            remaining.remove(p)
                        else:
                            hit = False
                            break
                    hit = hit and (kind == 'all' or not remaining)
                if hit:
                    channel[1] = mode
        elif verb in ('oneChannel', 'addChannel'):
            fields = argument.split()
            if len(fields) < 5:
                raise ValueError(f'{verb} needs onMode bRatio meMode and products: {command!r}')
            daughters = _channel_key(fields[3:])
            known = {key for key, _ in tables[pdg]}
            conjugate = _channel_key(-d for d in daughters)
            if daughters not in known and conjugate not in known:
                raise ValueError(f'{verb} channel {list(daughters)} of {pdg} is absent from the declared physical table')
            if verb == 'oneChannel':
                channels.clear()
            channels.append([daughters if daughters in known else conjugate, int(fields[0])])
        else:
            raise ValueError(f'Pythia command {verb!r} is not supported for normalization; supported: onMode, '
                             'on/off(Pos/Neg)IfAny/IfAll/IfMatch, oneChannel, addChannel')
    return state


def _madspin_channels(madspin, tables):
    definitions = dict(_MG5_MULTI)
    allowed = {}
    for line in madspin.get('definitions', []):
        parts = line.split()
        if len(parts) < 4 or parts[0] != 'define' or parts[2] != '=':
            raise ValueError(f'unparsed MadSpin definition {line!r}')
        definitions[parts[1]] = [p for name in parts[3:] for p in _mg5(name, definitions)]
    for line in madspin['decays']:
        parts = line.split()
        if len(parts) < 4 or parts[0] != 'decay' or parts[2] != '>' or ',' in line:
            raise ValueError(f'only single-step MadSpin decay lines are supported: {line!r}')
        parents = _mg5(parts[1], definitions)
        options = [_mg5(name, definitions) for name in parts[3:]]
        for parent in parents:
            rows = tables.get(abs(parent))
            if rows is None:
                raise ValueError(f'MadSpin decay of {parent} needs its declared physical decay table')
            sign = 1 if parent > 0 else -1
            for key, _ in rows:
                conjugated = sorted(sign * d for d in key)
                if _assignable(conjugated, options):
                    allowed.setdefault(abs(parent), set()).add(key)
    return allowed


def _mg5(name, definitions):
    if name in definitions:
        return list(definitions[name])
    if name in _MG5_NAMES:
        return [_MG5_NAMES[name]]
    raise ValueError(f'unknown MG5 particle label {name!r}; add a define line')


def _assignable(daughters, options):
    if len(daughters) != len(options):
        return False
    def search(index, used):
        if index == len(options):
            return True
        for i, d in enumerate(daughters):
            if i not in used and d in options[index] and search(index + 1, used | {i}):
                return True
        return False
    return search(0, frozenset())


def decay_factors(settings, *, base_dir=None):
    """Branching and filter factors for a forced-decay or filtered sample, each with provenance."""
    allowed = {'schema_version', 'produced', 'decay_tables', 'slha', 'pythia', 'madspin',
               'sigma_includes_decays', 'filters', 'sigma_after_filter', 'source'}
    if not isinstance(settings, dict) or settings.get('schema_version') != 1:
        raise ValueError('decay settings schema_version 1 required')
    extra = set(settings) - allowed
    if extra:
        raise ValueError('unknown decay-setting keys: ' + ', '.join(sorted(extra)))
    for key in ('sigma_includes_decays', 'sigma_after_filter'):
        if type(settings.get(key)) is not bool:
            raise ValueError(f'{key} must be declared true or false')
    base_dir = Path(base_dir or Path.cwd())
    tables, sources = _decay_tables(settings, base_dir)
    pythia = _pythia_modes(settings.get('pythia') or [], tables)
    madspin = settings.get('madspin')
    madspin_allowed, madspin_included = {}, False
    if madspin:
        if type(madspin.get('cross_section_includes_branching')) is not bool:
            raise ValueError('MadSpin settings must declare cross_section_includes_branching')
        madspin_allowed = _madspin_channels(madspin, tables)
        madspin_included = madspin['cross_section_includes_branching']
        overlap = set(madspin_allowed) & set(pythia)
        if overlap:
            raise ValueError(f'double counting: {sorted(overlap)} decayed by both MadSpin and forced Pythia decays')
    if settings['sigma_includes_decays'] and pythia:
        raise ValueError('double counting: the cross section already includes the decays, '
                         'but forced Pythia decays would apply branching fractions again')
    per_particle, factor = [], 1.0
    for produced in settings.get('produced', []):
        pdg = int(produced)
        a = abs(pdg)
        row = {'particle': pdg}
        if a in madspin_allowed:
            if madspin_included or settings['sigma_includes_decays']:
                row.update(source='madspin', factor=1.0, already_in_cross_section=True)
            else:
                open_keys = sorted(madspin_allowed[a])
                value = math.fsum(br for key, br in tables[a] if key in madspin_allowed[a])
                row.update(source='madspin', factor=value, open_channels=[list(k) for k in open_keys],
                           open_branching_fractions=[dict(tables[a])[k] for k in open_keys],
                           already_in_cross_section=False)
        elif a in pythia:
            wanted = (1, 2) if pdg > 0 else (1, 3)
            physical = dict(tables[a])
            open_keys = [key for key, mode in pythia[a] if mode in wanted]
            value = math.fsum(physical[key] for key in open_keys)
            row.update(source='pythia', factor=value, open_channels=[list(k) for k in open_keys],
                       open_branching_fractions=[physical[k] for k in open_keys], already_in_cross_section=False)
        else:
            row.update(source='inclusive', factor=1.0, already_in_cross_section=False)
        factor *= row['factor']
        per_particle.append(row)
    filters, efficiency = [], 1.0
    for f in settings.get('filters') or []:
        if not isinstance(f.get('source'), str) or not f['source'].strip():
            raise ValueError(f'filter {f.get("name")!r} needs the source of its efficiency')
        if 'n_pass' in f or 'n_total' in f:
            n_pass, n_total = f.get('n_pass'), f.get('n_total')
            if type(n_pass) is not int or type(n_total) is not int or not 0 <= n_pass <= n_total or n_total == 0:
                raise ValueError('filter counts need 0 <= n_pass <= n_total, n_total > 0')
            value = n_pass / n_total
        else:
            value = positive(f.get('efficiency'), 'filter efficiency')
            if value > 1:
                raise ValueError('filter efficiency cannot exceed one')
        filters.append({'name': f.get('name'), 'efficiency': value, 'source': f['source']})
        efficiency *= value
    if filters and settings['sigma_after_filter']:
        raise ValueError('double counting: the cross section is already the filtered cross section')
    status = 'no_open_channels' if per_particle and factor == 0 else 'resolved'
    return {'schema_version': 1, 'status': status, 'per_particle': per_particle, 'branching_factor': factor,
            'filters': filters, 'filter_factor': efficiency, 'total_factor': factor * efficiency,
            'sources': sources, 'pythia_commands': list(settings.get('pythia') or []),
            'madspin': madspin, 'sigma_includes_decays': settings['sigma_includes_decays'],
            'sigma_after_filter': settings['sigma_after_filter'], 'source': settings.get('source')}


def decay_frequency_closure(record, observed, *, z_max=5.0):
    """Compare observed decay-mode counts per forced particle with BR_i / sum(open BR)."""
    z_max = positive(z_max, 'z_max')
    reports, seen_particles = [], set()
    for row in record['per_particle']:
        if 'open_channels' not in row or abs(row['particle']) in seen_particles:
            continue
        a = abs(row['particle'])
        seen_particles.add(a)
        counts = observed.get(str(a), observed.get(a))
        if counts is None:
            continue
        if row['factor'] <= 0:
            raise ValueError(f'{a} has no open channels to compare')
        tally = {}
        for key, n in counts.items():
            if type(n) is not int or n < 0:
                raise ValueError('observed counts must be nonnegative integers')
            k = _abs_key(str(key).split())
            tally[k] = tally.get(k, 0) + n
        expected = {}
        for channel, br in zip(row['open_channels'], row['open_branching_fractions']):
            k = _abs_key(channel)
            expected[k] = expected.get(k, 0.0) + br / row['factor']
        n = sum(tally.values())
        closed = sorted(k for k, v in tally.items() if k not in expected and v > 0)
        passed, details = not closed and n > 0, []
        for k, p in expected.items():
            seen = tally.get(k, 0)
            sd = math.sqrt(n * p * (1.0 - p))
            z = (seen - n * p) / sd if sd > 0 else (0.0 if seen == n * p else math.inf)
            details.append({'channel': list(k), 'observed': seen, 'expected_fraction': p, 'z': z})
            passed = passed and abs(z) <= z_max
        reports.append({'particle': a, 'events': n, 'channels': details,
                        'closed_channels_observed': [list(k) for k in closed], 'passed': passed})
    if not reports:
        raise ValueError('no observed counts for any forced particle')
    return {'passed': all(r['passed'] for r in reports), 'z_max': z_max, 'particles': reports}


def combine_cross_section(normalization, factors):
    """Apply a resolved factor record once to a resolved, luminosity-free normalization."""
    if normalization.get('status') != 'resolved' or normalization.get('luminosity_applied') is not False:
        raise ValueError('a resolved normalization without luminosity is required')
    if 'decay_factors' in normalization:
        raise ValueError('branching and filter factors may be applied only once')
    if factors.get('status') not in ('resolved',):
        raise ValueError('the factor record has no open decay channels')
    sigma = positive(normalization['applied_cross_section_pb'], 'applied cross section (pb)')
    return {**normalization, 'decay_factors': factors, 'factor_applications': 1,
            'cross_section_times_factors_pb': sigma * factors['total_factor']}


def main(argv=None):
    arguments = list(argv) if argv is not None else None
    if arguments and arguments[0] == 'factors':
        factor_parser = argparse.ArgumentParser(prog='ravel normalization factors',
                                                description='branching and filter factors from declared decay settings')
        factor_parser.add_argument('--settings', required=True)
        factor_parser.add_argument('--out', required=True)
        factor_args = factor_parser.parse_args(arguments[1:])
        settings_path = Path(factor_args.settings).resolve()
        record = decay_factors(json.loads(settings_path.read_text()), base_dir=settings_path.parent)
        with Path(factor_args.out).open('x') as handle:
            handle.write(json.dumps(record, indent=2, allow_nan=False) + '\n')
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("lhe", "madgraph-log", "shower-log", "out"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--kfactor", type=float, required=True)
    parser.add_argument("--nevents", type=int, required=True)
    args = parser.parse_args(argv)
    result = resolve_normalization(args.lhe, args.madgraph_log, args.shower_log, args.kfactor, args.nevents)
    Path(args.out).write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    return 0


if __name__ == "__main__":
    main()
