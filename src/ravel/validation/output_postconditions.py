"""Output contracts: what each stage must produce before a downstream stage may read it.

A contract is a small JSON object::

    {"name": "detector events", "kind": "delphes-root", "path": "events.root",
     "min_events": 1, "max_events": null, "expected_events": 1000,
     "required": ["Jet.PT", "MissingET.MET"], "weight": "Event.Weight",
     "forbid_all_zero_weights": true, "finite_fraction": 1.0,
     "forbid_constant": ["MissingET.MET"], "reference": {"path": "...", "rel_tol": 1e-9}}

``check(contract, base, snapshot=None)`` returns ``{"passed", "failures", "observed"}``.
Kinds and what they delegate to:

* ``lhe``: ``native_normalization.read_lhe`` (complete document, positive cross section,
  weight census); zero weights fail.
* ``hepmc``: HepMC3/HepMC2 ASCII framing and the event count (plain or gzip).
* ``root-tree`` and ``delphes-root`` (tree ``Delphes``): entries, branch presence, finite
  values, constant branches and the weight sum.
* ``json``: required JSON pointers, finite numbers.
* ``yoda``: ``BEGIN YODA_`` objects and their paths.
* ``saf``: MadAnalysis 5 SAF header and body.
* ``pyhf-workspace``: channels, observations, measurements and version.
* ``file``: a nonempty regular file.

Freshness uses a snapshot taken before the attempt (``snapshot(paths)``): an output that
already existed with the same identity is stale. ``reference`` compares the numeric content
with a reference file and fails a near copy. ``zero_cross_section_status`` classifies a zero
or missing generator cross section: it is confirmed only when the banner states no positive
rate, the log carries a recognised signature and no events were written; anything else is
suspicious and stops the chain.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re

KINDS = ('lhe', 'hepmc', 'root-tree', 'delphes-root', 'json', 'yoda', 'saf', 'pyhf-workspace', 'file')
FIELDS = {'name', 'kind', 'path', 'tree', 'min_events', 'max_events', 'expected_events', 'required', 'weight',
          'forbid_all_zero_weights', 'finite_fraction', 'forbid_constant', 'reference', 'description'}


def validate_contract(contract):
    if not isinstance(contract, dict) or set(contract) - FIELDS or not {'name', 'kind', 'path'} <= set(contract):
        raise ValueError(f'an output contract needs name, kind and path and may add {sorted(FIELDS - {"name", "kind", "path"})}')
    if contract['kind'] not in KINDS:
        raise ValueError(f'unknown output contract kind {contract["kind"]!r}; known kinds: {", ".join(KINDS)}')
    for key in ('min_events', 'max_events', 'expected_events'):
        value = contract.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f'{key} must be a nonnegative integer')
    fraction = contract.get('finite_fraction', 1.0)
    if type(fraction) not in (int, float) or not 0 <= fraction <= 1:
        raise ValueError('finite_fraction must be between 0 and 1')
    for key in ('required', 'forbid_constant'):
        if key in contract and (not isinstance(contract[key], list) or any(not isinstance(x, str) or not x for x in contract[key])):
            raise ValueError(f'{key} must be a list of names')
    if 'reference' in contract:
        ref = contract['reference']
        if not isinstance(ref, dict) or not isinstance(ref.get('path'), str) or set(ref) - {'path', 'rel_tol'}:
            raise ValueError('reference needs a path and may add rel_tol')
    return contract


def _identity(path):
    st = os.stat(path)
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return {'size': st.st_size, 'inode': st.st_ino, 'device': st.st_dev, 'sha256': digest.hexdigest()}


def snapshot(paths):
    """Identities of the given paths before an attempt (absent paths recorded as absent)."""
    out = {}
    for p in paths:
        p = Path(p)
        out[str(p.resolve())] = _identity(p) if p.is_file() else None
    return out


def _resolve(path, base):
    path = Path(path)
    return path if path.is_absolute() or base is None else Path(base) / path


def _opener(path):
    return gzip.open if str(path).endswith('.gz') else open


def _fail(failures, code, message):
    failures.append({'code': code, 'message': message})


def _count_checks(contract, n, failures):
    if contract.get('min_events') is not None and n < contract['min_events']:
        _fail(failures, 'too_few_events', f'{n} events, at least {contract["min_events"]} required')
    if contract.get('max_events') is not None and n > contract['max_events']:
        _fail(failures, 'too_many_events', f'{n} events, at most {contract["max_events"]} allowed')
    if contract.get('expected_events') is not None and n != contract['expected_events']:
        _fail(failures, 'event_count_mismatch', f'{n} events, {contract["expected_events"]} expected')


def _numeric_checks(contract, columns, failures):
    fraction = contract.get('finite_fraction', 1.0)
    for name, values in columns.items():
        if not len(values):
            continue
        finite = sum(1 for v in values if math.isfinite(v)) / len(values)
        if finite < fraction:
            _fail(failures, 'nonfinite_values', f'{name}: finite fraction {finite:.6g} below {fraction}')
    for name in contract.get('forbid_constant', []):
        values = columns.get(name)
        if values is not None and len(values) > 1 and min(values) == max(values):
            _fail(failures, 'constant_values', f'{name} has one value in every entry')


def _check_lhe(contract, path, failures, observed):
    from ravel.physics.native_normalization import read_lhe
    try:
        record = read_lhe(path)
    except (ValueError, OSError, EOFError) as exc:
        code = 'all_zero_weights' if 'sum of nominal event weights' in str(exc) else 'invalid_lhe'
        _fail(failures, code, str(exc))
        return []
    n = record.get('n_events', 0)
    observed.update(events=n, cross_section_pb=record['cross_section_pb'], sum_weights=record.get('sumw'),
                    negative_weights=record.get('negative_weights'))
    _count_checks(contract, n, failures)
    return []


def _check_hepmc(contract, path, failures, observed):
    events, started, ended, weights = 0, False, False, []
    with _opener(path)(path, 'rt', errors='replace') as stream:
        for raw in stream:
            if raw.startswith('HepMC::Asciiv3-START_EVENT_LISTING') or raw.startswith('HepMC::IO_GenEvent-START_EVENT_LISTING'):
                started = True
            elif raw.startswith('HepMC::Asciiv3-END_EVENT_LISTING') or raw.startswith('HepMC::IO_GenEvent-END_EVENT_LISTING'):
                ended = True
            elif raw.startswith('E '):
                events += 1
            elif raw.startswith('W ') and events and contract.get('forbid_all_zero_weights', True):
                # Before the first event a W line names the weights (HepMC3 run information).
                try:
                    weights.append(float(raw.split()[1]))
                except (IndexError, ValueError):
                    _fail(failures, 'malformed_weight', 'malformed HepMC weight line')
    observed.update(events=events, complete_listing=started and ended)
    if not (started and ended):
        _fail(failures, 'incomplete_listing', 'HepMC start or end marker missing (truncated file)')
    _count_checks(contract, events, failures)
    if weights:
        observed['sum_weights'] = math.fsum(weights)
        if all(w == 0 for w in weights):
            _fail(failures, 'all_zero_weights', 'every HepMC event weight is zero')
    return weights


def _check_root(contract, path, failures, observed):
    import numpy as np
    import uproot
    tree_name = contract.get('tree', 'Delphes' if contract['kind'] == 'delphes-root' else None)
    if not tree_name:
        _fail(failures, 'no_tree', 'root-tree contracts name their tree')
        return []
    try:
        with uproot.open(path) as handle:
            if tree_name not in handle:
                _fail(failures, 'missing_tree', f'tree {tree_name} is absent')
                return []
            tree = handle[tree_name]
            n = int(tree.num_entries)
            # Split Delphes branches appear as 'Jet/Jet.PT'; a contract names them 'Jet.PT'.
            names = set(tree.keys(recursive=True)) | set(tree.keys(recursive=True, full_paths=False))
            observed.update(entries=n, events=n, tree=tree_name)
            _count_checks(contract, n, failures)
            if n == 0:
                _fail(failures, 'empty_tree', f'tree {tree_name} has no entries')
            required = list(contract.get('required', []))
            weight = contract.get('weight', 'Event.Weight' if contract['kind'] == 'delphes-root' else None)
            missing = [b for b in required + ([weight] if weight else []) if b not in names]
            if missing:
                _fail(failures, 'missing_branches', 'branches absent: ' + ', '.join(missing))
            columns = {}
            for name in [b for b in dict.fromkeys(required + contract.get('forbid_constant', [])) if b in names]:
                arr = tree[name].array(library='ak') if n else []
                try:
                    import awkward as ak
                    flat = np.asarray(ak.flatten(arr, axis=None), dtype=float)
                except Exception:
                    flat = np.asarray(arr, dtype=float).ravel()
                columns[name] = flat.tolist()
            _numeric_checks(contract, columns, failures)
            values = []
            if weight and weight in names and n:
                import awkward as ak
                w = tree[weight].array(library='ak')
                w = ak.firsts(w) if w.ndim > 1 else w
                values = np.asarray(ak.fill_none(w, np.nan), dtype=float).tolist()
                observed.update(sum_weights=math.fsum(values), sum_weights2=math.fsum(v * v for v in values))
                if not all(math.isfinite(v) for v in values):
                    _fail(failures, 'nonfinite_weights', 'event weights are not all finite')
                if contract.get('forbid_all_zero_weights', True) and all(v == 0 for v in values):
                    _fail(failures, 'all_zero_weights', 'every event weight is zero')
            return values + [x for c in columns.values() for x in c]
    except (OSError, ValueError, KeyError) as exc:
        _fail(failures, 'unreadable_root', f'{type(exc).__name__}: {exc}')
        return []


def _pointer(document, pointer):
    node = document
    for part in pointer.lstrip('/').split('/') if pointer != '/' else []:
        part = part.replace('~1', '/').replace('~0', '~')
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _flatten_numbers(node, out):
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        out.append(float(node))
    elif isinstance(node, dict):
        for value in node.values():
            _flatten_numbers(value, out)
    elif isinstance(node, list):
        for value in node:
            _flatten_numbers(value, out)
    return out


def _check_json(contract, path, failures, observed):
    try:
        document = json.loads(Path(path).read_text(), parse_constant=lambda s: float('nan'))
    except (OSError, ValueError) as exc:
        _fail(failures, 'invalid_json', str(exc))
        return []
    for pointer in contract.get('required', []):
        try:
            value = _pointer(document, pointer)
        except (KeyError, IndexError, ValueError, TypeError):
            _fail(failures, 'missing_key', f'{pointer} is absent')
            continue
        if value is None:
            _fail(failures, 'missing_key', f'{pointer} is null')
    numbers = _flatten_numbers(document, [])
    _numeric_checks(contract, {'numbers': numbers}, failures)
    observed['numbers'] = len(numbers)
    return numbers


def _check_yoda(contract, path, failures, observed):
    text = Path(path).read_text(errors='replace')
    objects = re.findall(r'^BEGIN YODA_\S+\s+(\S+)', text, re.M)
    observed.update(objects=len(objects))
    if text.count('BEGIN YODA_') != text.count('END YODA_'):
        _fail(failures, 'truncated_yoda', 'BEGIN and END markers do not pair')
    if not objects:
        _fail(failures, 'empty_yoda', 'no YODA objects')
    missing = [p for p in contract.get('required', []) if p not in objects]
    if missing:
        _fail(failures, 'missing_objects', 'YODA objects absent: ' + ', '.join(missing))
    numbers = [float(x) for x in re.findall(r'^\s*([-+0-9.eE]+)\s', text, re.M) if _is_float(x)]
    return numbers


def _is_float(x):
    try:
        float(x)
        return True
    except ValueError:
        return False


def _check_saf(contract, path, failures, observed):
    text = Path(path).read_text(errors='replace')
    if '<SAFheader>' not in text or '</SAFheader>' not in text:
        _fail(failures, 'invalid_saf', 'SAF header missing')
    observed['bytes'] = len(text)
    if len(text.strip()) == 0:
        _fail(failures, 'empty_saf', 'empty SAF file')
    for token in contract.get('required', []):
        if token not in text:
            _fail(failures, 'missing_block', f'{token} is absent')
    return []


def _check_pyhf(contract, path, failures, observed):
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        _fail(failures, 'invalid_json', str(exc))
        return []
    for key in ('channels', 'observations', 'measurements', 'version'):
        if key not in document:
            _fail(failures, 'missing_key', f'workspace has no {key}')
    channels = document.get('channels') or []
    observed['channels'] = len(channels)
    if not channels:
        _fail(failures, 'empty_workspace', 'workspace has no channels')
    numbers = _flatten_numbers(document.get('observations', []), [])
    _numeric_checks(contract, {'observations': numbers}, failures)
    return numbers


CHECKS = {'lhe': _check_lhe, 'hepmc': _check_hepmc, 'root-tree': _check_root, 'delphes-root': _check_root,
          'json': _check_json, 'yoda': _check_yoda, 'saf': _check_saf, 'pyhf-workspace': _check_pyhf,
          'file': lambda c, p, f, o: []}


def _reference_numbers(contract, path, base):
    reference = dict(contract)
    reference.pop('reference', None)
    reference['path'] = str(path)
    reference.update(min_events=None, max_events=None, expected_events=None)
    return CHECKS[contract['kind']](reference, path, [], {})


def check(contract, base=None, *, snapshot_before=None):
    """Evaluate one contract against its output. Never modifies the output."""
    validate_contract(contract)
    path = _resolve(contract['path'], base)
    failures, observed = [], {}
    result = {'name': contract['name'], 'kind': contract['kind'], 'path': str(path), 'failures': failures,
              'observed': observed}
    if path.is_symlink() or not path.is_file():
        _fail(failures, 'missing_output', 'output file is absent')
        result['passed'] = False
        return result
    identity = _identity(path)
    observed.update(size=identity['size'], sha256=identity['sha256'])
    if identity['size'] == 0:
        _fail(failures, 'empty_file', 'output file is empty')
    if snapshot_before is not None:
        before = snapshot_before.get(str(path.resolve()), 'unrecorded')
        if before == 'unrecorded':
            _fail(failures, 'not_in_snapshot', 'output was not part of the attempt snapshot')
        elif before is not None and before['sha256'] == identity['sha256'] and before['inode'] == identity['inode']:
            _fail(failures, 'stale_output', 'output already existed unchanged before the attempt')
    numbers = CHECKS[contract['kind']](contract, path, failures, observed) if identity['size'] else []
    if 'reference' in contract and numbers:
        ref_path = _resolve(contract['reference']['path'], base)
        tolerance = contract['reference'].get('rel_tol', 1e-9)
        ref = _reference_numbers(contract, ref_path, base) if ref_path.is_file() else None
        if ref is not None and len(ref) == len(numbers) and all(
                math.isclose(a, b, rel_tol=tolerance, abs_tol=0.0) or (math.isnan(a) and math.isnan(b))
                for a, b in zip(numbers, ref)):
            _fail(failures, 'near_copy_of_reference', f'numeric content equals {ref_path.name} within {tolerance}')
    result['passed'] = not failures
    return result


def check_all(contracts, base=None, *, snapshot_before=None):
    results = [check(c, base, snapshot_before=snapshot_before) for c in contracts]
    return {'passed': all(r['passed'] for r in results), 'contracts': results}


def zero_cross_section_status(*, banner_sigma_pb, log_text, events_written, signatures):
    """Classify a zero or missing cross section: confirmed, suspicious or not_zero.

    Confirmed only when all three hold: the banner states no positive rate, the log
    carries one of the declared signatures and no events were written.
    """
    zero = banner_sigma_pb is None or (isinstance(banner_sigma_pb, (int, float)) and banner_sigma_pb == 0)
    if not zero:
        return {'status': 'not_zero', 'evidence': {'banner_sigma_pb': banner_sigma_pb}}
    matched = [s for s in signatures if re.search(s, log_text or '', re.M)]
    evidence = {'banner_sigma_pb': banner_sigma_pb, 'log_signatures': matched, 'events_written': events_written}
    if matched and not events_written:
        return {'status': 'confirmed', 'evidence': evidence}
    return {'status': 'suspicious', 'evidence': evidence,
            'reason': 'a zero or missing cross section without all three confirmations stops the chain'}
