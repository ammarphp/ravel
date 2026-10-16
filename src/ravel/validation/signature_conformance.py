"""Conformance of the operation signatures (architecture §2.5.3, Stage 2 row 2-02).

``src/ravel/data/operation_signatures.json`` gives each registered operation a typed
signature: the artifact kinds it consumes and produces, its effects and its evidence-basis
contributions. This module checks that registry:

- every registered mode (science modes and scoped adapters) has an entry;
- each entry is schema-valid and resolves: a science mode names itself and the module its
  adapter resolves to, a scoped adapter is registered, and a command or lifecycle stage
  names an importable module;
- every consumed and produced kind is a known artifact kind with a witness, slot names are
  unique, basis ``passes`` and ``origin_from``/``level_from`` name consumed slots;
- tool names are plain names, and no entry carries a paper or benchmark identifier (R-10).

A witness is a structural predicate for one artifact kind. ``output_errors`` applies the
witnesses of an operation's produced slots to the outputs an adapter wrote, so an adapter
test can show that its outputs are what its signature declares. ``chains`` searches the
registry for operation chains from supplied kinds to a delivered kind, and
``edge_errors`` checks one producer-to-consumer edge.

A signature declares shape, not scientific validity: passing conformance says nothing about
whether an operation's physics is right.

Other packages supply rows through a seam: they write candidate rows to a JSON file
``{operation: entry}`` and run ``python -m ravel.validation.signature_conformance --entries
FILE``; the owner of ``operation_signatures.json`` merges rows that pass.
"""
from __future__ import annotations

import argparse
from collections import deque
import importlib.util
import json
import math
from pathlib import Path, PurePath
import re
import sys

from ravel.validation import validate_request_plan as rp
from ravel.validation.validate_task_contract import _schema_errors

# --------------------------------------------------------------------------- witnesses
_SUFFIXES = {
    'event_sample': ('.lhe', '.lhe.gz', '.hepmc', '.hepmc.gz', '.hepmc2', '.hepmc3', '.root', '.parquet', '.h5',
                     '.hdf5', '.npz'),
    'model': ('.py', '.fr', '.m', '.slha', '.tar.gz', '.zip'),
    'parameter_point': ('.slha', '.dat', '.json', '.toml'),
    'figure': ('.pdf', '.png', '.svg', '.eps'),
    'document': ('.md', '.pdf', '.tex', '.txt', '.html', '.json'),
    'table': ('.csv', '.json', '.yaml', '.yml', '.tsv', '.sqlite', '.saf', '.root'),
    'binned_values': ('.yoda', '.yoda.gz', '.json', '.root', '.npz'),
    'statistical_model': ('.json', '.txt', '.root'),
    'selection': ('.cc', '.cxx', '.cpp', '.py', '.json', '.onnx', '.yaml'),
}
INFERENCE_KEYS = ('limits', 'significance', 'interval', 'intervals', 'best_fit', 'cls', 'mu95', 'result',
                  'statistic', 'posterior', 'score', 'separation', 'envelope', 'parameters')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _path(document, kind):
    name = str(document).lower()
    if any(name.endswith(s) for s in _SUFFIXES.get(kind, ())):
        return []
    if kind == 'model' and isinstance(document, Path) and document.is_dir():
        return [] if (document / 'particles.py').is_file() or any(document.glob('*.fr')) else [
            f'{document}: a model directory has particles.py (UFO) or a .fr source']
    return [f'{document}: a {kind} file has one of {", ".join(_SUFFIXES.get(kind, ()))}']


def _edges(edges):
    return (isinstance(edges, list) and len(edges) >= 2 and all(_number(e) for e in edges)
            and all(a < b for a, b in zip(edges, edges[1:])))


def _binned(doc):
    if 'edges' in doc and 'values' in doc:
        if not _edges(doc['edges']):
            return ['binned_values edges are at least two strictly increasing finite numbers']
        values = doc['values']
        if not isinstance(values, list) or len(values) != len(doc['edges']) - 1:
            return ['binned_values carry one value per bin (len(edges) - 1)']
        return [] if all(v is None or _number(v) for v in values) else ['binned_values values are numbers or null']
    if isinstance(doc.get('bins'), list) and doc['bins']:
        return [] if all(isinstance(b, dict) and 'value' in b for b in doc['bins']) else [
            'binned_values bins are objects with a value']
    if isinstance(doc.get('histograms'), (list, dict)) and doc['histograms']:
        return []
    return ['binned_values need edges and values, bins, or histograms']


def _table(doc):
    if isinstance(doc.get('rows'), list):
        return []
    if isinstance(doc.get('independent_variables'), list) and isinstance(doc.get('dependent_variables'), list):
        return []
    if isinstance(doc.get('headers'), list) and isinstance(doc.get('values'), list):
        return []
    if isinstance(doc.get('columns'), (list, dict)) or isinstance(doc.get('entries'), (list, dict)):
        return []
    return ['a table has rows, columns, entries, or the HEPData submission or web layout']


def _scalar(doc):
    return [] if _number(doc.get('value')) else ['a scalar has a finite numeric value']


def _inference(doc):
    return [] if any(k in doc for k in INFERENCE_KEYS) else [
        'an inference names its result (' + ', '.join(INFERENCE_KEYS[:6]) + ', ...)']


def _statistical_model(doc):
    if isinstance(doc.get('channels'), list) or isinstance(doc.get('distributions'), list):
        return []
    if any(k in doc for k in ('workspace', 'datacard', 'model', 'likelihoods')):
        return []
    return ['a statistical model has HistFactory channels, HS3 distributions, a workspace or a datacard']


def _event_sample(doc):
    files = doc.get('files')
    if isinstance(files, list) and files and all(isinstance(f, str) and f for f in files):
        return []
    return ['an event sample lists its files']


def _selection(doc):
    if any(k in doc for k in ('cuts', 'regions', 'routine', 'recipe', 'selection', 'classifier')):
        return []
    return ['a selection has cuts, regions, a routine, a recipe or a classifier']


def _cutflow(doc):
    steps = doc.get('steps', doc.get('cuts'))
    if isinstance(steps, list) and steps and all(isinstance(s, dict) and 'name' in s for s in steps):
        return []
    if isinstance(doc.get('regions'), dict) and doc['regions']:
        return []
    return ['a cutflow has named steps or per-region steps']


def _expression(doc):
    text = doc.get('expression', doc.get('expressions'))
    return [] if (isinstance(text, str) and text.strip()) or (isinstance(text, (list, dict)) and text) else [
        'an expression has expression text']


def _parameter_point(doc):
    params = doc.get('parameters')
    if isinstance(params, dict) and params and all(isinstance(k, str) for k in params):
        return []
    if isinstance(doc.get('points'), list) and doc['points']:
        return []
    return ['a parameter point maps parameter names to values']


def _model(doc):
    return [] if any(k in doc for k in ('format', 'path', 'ufo', 'source')) else [
        'a model names its format, path or source']


def _figure(doc):
    return [] if isinstance(doc.get('path'), str) or isinstance(doc.get('paths'), list) else [
        'a figure names its rendered path']


def _document(doc):
    return [] if any(k in doc for k in ('text', 'sections', 'path', 'paths')) else [
        'a document has text, sections or a path']


WITNESSES = {'binned_values': _binned, 'table': _table, 'scalar': _scalar, 'inference': _inference,
             'statistical_model': _statistical_model, 'event_sample': _event_sample, 'selection': _selection,
             'cutflow': _cutflow, 'expression': _expression, 'parameter_point': _parameter_point,
             'model': _model, 'figure': _figure, 'document': _document}
NAMESPACED = re.compile(rp.NAMESPACED_KIND)


def witness(kind, document):
    """Errors for one artifact (a JSON value or a path) against the witness of ``kind``; [] when it passes."""
    if isinstance(document, PurePath):
        if NAMESPACED.match(kind):
            return []
        return _path(document, kind) if kind in WITNESSES else [f'{kind} is not a known artifact kind']
    if NAMESPACED.match(kind):
        return [] if isinstance(document, dict) and document.get('kind') == kind else [
            f'a {kind} artifact states kind {kind!r}']
    check = WITNESSES.get(kind)
    if check is None:
        return [f'{kind} is not a known artifact kind']
    if kind == 'scalar' and _number(document):
        return []
    if kind == 'expression' and isinstance(document, str) and document.strip():
        return []
    if not isinstance(document, dict):
        return [f'a {kind} artifact is an object or a file path']
    return check(document)


def known_kind(kind):
    return kind in WITNESSES or bool(NAMESPACED.match(kind))


def output_errors(operation, outputs, registry=None):
    """Witness errors for an adapter's outputs ``{slot: artifact}`` against the operation's produced slots.

    Every produced slot that is not optional must be present; each present artifact passes its
    kind's witness, and an artifact that states a property the slot requires states an allowed value.
    """
    registry = rp.registry() if registry is None else registry
    signature = registry.get(operation)
    if signature is None:
        return [f'{operation} has no signature']
    errors = []
    slots = {s['slot']: s for s in signature['produces']}
    for name in sorted(set(outputs) - set(slots)):
        errors.append(f'{operation} declares no produced slot {name!r}')
    for name, slot in slots.items():
        if name not in outputs:
            if not slot.get('optional'):
                errors.append(f'{operation} produced nothing for slot {name!r}')
            continue
        artifact = outputs[name]
        if isinstance(artifact, dict) and 'quantity' in artifact:
            from ravel.validation.semantic_composition import artifact_report, message
            errors += list(map(message, artifact_report(artifact, slot.get('require', {}).get('quantity', {}),
                                                        f'{operation}.{name}')['errors']))
        errors += [f'{operation}.{name}: {e}' for e in witness(slot['kind'], artifact)]
        if isinstance(artifact, dict) and slot.get('require'):
            stated = {k: artifact[k] for k in slot['require'] if k in artifact}
            if not rp._require_ok(stated, slot['require']):
                errors.append(f'{operation}.{name}: stated {stated} does not meet {slot["require"]}')
    return errors


# --------------------------------------------------------------------------- entry conformance
def _identifier_patterns():
    from ravel.validation.tool_selection_score import IDENTIFIER_PATTERNS
    return IDENTIFIER_PATTERNS


def _module_errors(name, module):
    try:
        found = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        found = None
    return [] if found is not None else [f'{name}: module {module} does not resolve']


def _science_module(name):
    from ravel.workflow import science
    try:
        return science.adapter({'mode': name, 'task': {}}).__name__
    except (ImportError, KeyError, ValueError) as exc:
        return exc


def implementation_errors(name, entry, modes=None, scoped=None):
    """Errors when an entry's implementation does not resolve to what it names."""
    from ravel.workflow.science import MODES
    from ravel.workflow.scoped_spec import MODES as SCOPED
    modes = frozenset(MODES) if modes is None else modes
    scoped = frozenset(SCOPED) if scoped is None else scoped
    impl = entry.get('implementation', {})
    kind = impl.get('kind')
    if kind == 'science-mode':
        errors = []
        if impl.get('mode') != name:
            errors.append(f'{name}: a science-mode entry names its own mode (found {impl.get("mode")!r})')
        if name not in modes:
            return errors + [f'{name}: no registered science mode {name!r}']
        resolved = _science_module(name)
        if isinstance(resolved, Exception):
            return errors + [f'{name}: the mode adapter does not resolve ({resolved})']
        if impl.get('module') != resolved:
            errors.append(f'{name}: module {impl.get("module")!r} differs from the adapter {resolved}')
        if impl.get('dispatch_group'):
            from ravel.workflow.operation_definitions import definitions
            try:
                definitions({name: entry})
                if impl.get('presentation'):
                    from importlib import import_module
                    hook = getattr(import_module(resolved), impl['presentation'], None)
                    if not callable(hook):
                        errors.append(f'{name}: presentation hook does not resolve to a callable')
            except ValueError as exc:
                errors.append(str(exc))
        return errors
    if kind == 'scoped-adapter':
        return [] if name in scoped else [f'{name}: no registered scoped adapter {name!r}']
    if kind in ('command', 'lifecycle-stage'):
        module = impl.get('module')
        if not module:
            return [] if kind == 'lifecycle-stage' and impl.get('stage') else [f'{name}: a {kind} names its module']
        return _module_errors(name, module)
    return [f'{name}: unknown implementation kind {kind!r}']


def entry_errors(name, entry, modes=None, scoped=None):
    """Conformance errors for one signature entry; [] when it conforms."""
    errors = [f'{name}: {e}' for e in _schema_errors(entry, rp.SIGNATURE_SCHEMA, 'signature')]
    if errors:
        return errors
    errors += implementation_errors(name, entry, modes, scoped)
    if not entry['produces']:
        errors.append(f'{name}: an operation produces at least one artifact')
    for side in ('consumes', 'produces'):
        names = [s['slot'] for s in entry[side]]
        if len(names) != len(set(names)):
            errors.append(f'{name}: duplicate {side} slot names')
        for slot in entry[side]:
            from ravel.validation.semantic_composition import requirement_errors, message
            if 'quantity' in slot.get('require', {}):
                errors += list(map(message, requirement_errors(slot['require']['quantity'],
                                   f'{name}.{slot["slot"]}.quantity')))
            if not known_kind(slot['kind']):
                errors.append(f'{name}: {side} slot {slot["slot"]!r} has unknown kind {slot["kind"]!r}')
    consumed = {s['slot'] for s in entry['consumes']}
    from ravel.validation.semantic_composition import FIELDS, NORMALIZATION
    paths = set(FIELDS) | {'normalization.' + k for k in NORMALIZATION} | {'exposure.id', 'exposure.revision'}
    for rule in entry.get('quantity_relations', []):
        if set(rule['slots']) - consumed or set(rule['fields'] + rule.get('group_by', [])) - paths:
            errors.append(f'{name}: quantity relation names an unknown consumed slot or quantity field')
    for slot_name in entry['basis']['passes']:
        if slot_name not in consumed:
            errors.append(f'{name}: basis passes {slot_name!r}, which is not a consumed slot')
    for add in entry['basis']['adds']:
        for key in ('origin_from', 'level_from'):
            if key in add and add[key].partition('.')[0] not in consumed:
                errors.append(f'{name}: basis {key} {add[key]!r} names no consumed slot')
    for tool in entry['tools']:
        if tool != tool.strip() or tool.startswith('re:'):
            errors.append(f'{name}: tool {tool!r} is not a plain tool name')
    text = json.dumps(entry, ensure_ascii=False)
    for pattern in _identifier_patterns():
        if pattern.search(text):
            errors.append(f'{name}: identifier shape {pattern.pattern} (R-10)')
    return errors


def conformance(document=None):
    """Every conformance error over the registry: missing entries and nonconforming entries."""
    from ravel.workflow.science import MODES
    from ravel.workflow.scoped_spec import MODES as SCOPED
    if document is None:
        document = rp._signature_document()
    errors = [f'signatures: {e}' for e in _schema_errors(document, rp.SIGNATURES_SCHEMA, 'signatures')]
    operations = document.get('operations', {}) if isinstance(document, dict) else {}
    for mode in sorted(frozenset(MODES) | frozenset(SCOPED)):
        if mode not in operations:
            errors.append(f'{mode}: registered mode has no operation signature')
    modes, scoped = frozenset(MODES), frozenset(SCOPED)
    for name, entry in sorted(operations.items()):
        errors += entry_errors(name, entry, modes, scoped)
    from ravel.validation.claim_checks import conformance as claim_check_conformance
    errors += claim_check_conformance(registry=operations)
    return errors


# --------------------------------------------------------------------------- edges and chain search
def _structural_edge_errors(producer, out_slot, consumer, in_slot, registry=None):
    """Errors for one edge ``producer.out_slot -> consumer.in_slot``; [] when it resolves."""
    registry = rp.registry() if registry is None else registry
    source, target = registry.get(producer), registry.get(consumer)
    if source is None or target is None:
        return [f'{producer if source is None else consumer} has no signature']
    produced = {s['slot']: s for s in source['produces']}.get(out_slot)
    wanted = {s['slot']: s for s in target['consumes']}.get(in_slot)
    if produced is None:
        return [f'{producer} produces no slot {out_slot!r}']
    if wanted is None:
        return [f'{consumer} consumes no slot {in_slot!r}']
    if not rp._kind_ok(produced['kind'], wanted['kind']):
        return [f'{producer}.{out_slot} is {produced["kind"]}; {consumer}.{in_slot} consumes {wanted["kind"]}']
    if not rp._require_ok(produced.get('require', {}), wanted.get('require', {})):
        return [f'{producer}.{out_slot} {produced.get("require", {})} does not meet '
                f'{consumer}.{in_slot} {wanted.get("require", {})}']
    return []



def edge_report(producer, out_slot, consumer, in_slot, registry=None, *, artifact=None):
    """Composition report with located quantity obligations for absent facts.

    An optional actual artifact is checked against both endpoint declarations.
    Registry-only queries cannot establish the semantics of missing output bytes.
    """
    from ravel.validation.semantic_composition import compare, artifact_report, message
    registry = rp.registry() if registry is None else registry
    structural = _structural_edge_errors(producer, out_slot, consumer, in_slot, registry)
    if structural:
        return {'errors': structural, 'obligations': []}
    produced = next(s for s in registry[producer]['produces'] if s['slot'] == out_slot)
    wanted = next(s for s in registry[consumer]['consumes'] if s['slot'] == in_slot)
    location = f'{producer}.{out_slot} -> {consumer}.{in_slot}'
    provided = produced.get('require', {}).get('quantity')
    required = wanted.get('require', {}).get('quantity', {})
    if artifact is None:
        result = compare(provided, required, location)
    else:
        result = artifact_report(artifact, required, location)
        if provided is not None:
            other = artifact_report(artifact, provided, location + '.producer')
            for side in result:
                result[side].extend(other[side])
    return {'errors': list(map(message, result['errors'])), 'obligations': result['obligations']}


def edge_errors(producer, out_slot, consumer, in_slot, registry=None, *, artifact=None):
    """Contradictions on an edge; use edge_report for unresolved obligations."""
    return edge_report(producer, out_slot, consumer, in_slot, registry, artifact=artifact)['errors']


def _feeds(producer, consumer, registry):
    return [(p['slot'], c['slot']) for p in registry[producer]['produces'] for c in registry[consumer]['consumes']
            if not edge_errors(producer, p['slot'], consumer, c['slot'], registry)]


def chains(start, target_kind, registry=None, max_length=5, limit=20):
    """Operation chains from ``start`` (an operation) to an operation that produces ``target_kind``.

    Each chain is a list of operation names joined by resolvable edges; chains are found
    breadth first, shortest first, and never revisit an operation.
    """
    registry = rp.registry() if registry is None else registry
    signed = {k: v for k, v in registry.items() if v is not None}
    if start not in signed:
        return []
    found, queue = [], deque([[start]])
    while queue and len(found) < limit:
        chain = queue.popleft()
        last = chain[-1]
        if any(s['kind'] == target_kind for s in signed[last]['produces']):
            found.append(chain)
            continue
        if len(chain) >= max_length:
            continue
        for name in sorted(signed):
            if name not in chain and _feeds(last, name, signed):
                queue.append(chain + [name])
    return found


def resolves(chain, registry=None):
    """Errors for a chain of operations: each consecutive pair must have at least one resolvable edge."""
    registry = rp.registry() if registry is None else registry
    errors = []
    for name in chain:
        if registry.get(name) is None:
            errors.append(f'{name} has no signature')
    if errors:
        return errors
    for producer, consumer in zip(chain, chain[1:]):
        if not _feeds(producer, consumer, registry):
            errors.append(f'no resolvable edge from {producer} to {consumer}')
    return errors


# --------------------------------------------------------------------------- command line
def main(argv=None):
    ap = argparse.ArgumentParser(prog='signature_conformance', description=__doc__.split('\n\n')[0])
    ap.add_argument('--entries', type=Path, help='check candidate rows {operation: entry} instead of the registry')
    args = ap.parse_args(argv)
    if args.entries:
        rows = json.loads(args.entries.read_text())
        errors = [e for name, entry in sorted(rows.items()) for e in entry_errors(name, entry)]
    else:
        errors = conformance()
    for error in errors:
        print(error)
    print(f'{len(errors)} conformance error(s)', file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
