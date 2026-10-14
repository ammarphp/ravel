"""Current recipe comparisons, without claiming runtime consumption or certification.

``build(rundir)`` recomputes rows from the request plan's operation critical fields,
native effective settings, current cards and signal-patch metadata. Missing evidence
is unknown. CHECK-IN 1 flags name the exact deviation payload; RDJ authorization
uses the accepted-receipt interface against separately materialized deviation bytes.
CHECK-IN 3 consumers use ``with_checkin3_section`` and ``checkin3_errors``; the
CHECK-IN registry currently composes only CHECK-IN 1. Root-cause analysis and residual diagnosis consume ``rows``.
No tools are run and inspection never writes. Byte pins establish source identity,
not independent measurement, installed-runtime authentication or physics validity.

An effective value from ``inputs/recipe_observations.json`` counts only when its pinned
file is an output of a registered stage receipt from a recognized RAVEL module or native
tool (``custody_authority.stage_output``); a file the agent wrote is never authority.
Each ``/generation/run_settings`` and ``/generation/shower`` key of the request plan has a
``translation`` row, so an option the native translation drops is ``deviated``. CHECK-IN 1
binds the requested side of each row: correct evidence that arrives later changes the
status without invalidating the approval. Evidence paths inside the run are run-relative.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
import re

from .state_io import atomic_json, read_json

RECORD = 'outputs/recipe_ledger.json'
OBSERVATIONS = 'inputs/recipe_observations.json'
NATIVE_PLAN = 'inputs/native_execution_plan.json'
MANIFEST = 'output/native_effective_settings.json'
_MISSING = object()
_MAX_BYTES = 16 * 1024 * 1024
_DETECTOR_FIELDS = ('b_tag_working_point', 'lepton_id', 'isolation', 'impact_parameter',
                    'trigger', 'pileup', 'jvt')
# Request-plan run-card maps and the native layer each key is compared in.
TRANSLATED = {'/generation/run_settings': 'generation', '/generation/shower': 'shower'}
# RDJ tuning classes that may accept a recipe deviation; detector rows also accept calibration.
RECIPE_TUNING_CLASSES = ('recipe_restoration', 'implementation_correction', 'new_approximation')
# CHECK-IN 1 binds the requested side; status and effective values are current evidence.
_REQUESTED_VIEW = ('id', 'layer', 'field', 'node_id', 'claim_id', 'requested', 'requested_present')


def schema():
    return json.loads(files('ravel').joinpath('data/claims/recipe_ledger.schema.json').read_text())


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _path(root, value):
    path = Path(value)
    return path if path.is_absolute() else root / path


def _bytes(path):
    if path.is_symlink() or path.stat().st_size > _MAX_BYTES:
        raise ValueError(f'unsupported recipe input (symlink or too large): {path}')
    return path.read_bytes()


def _name(root, path):
    """Run-relative POSIX name inside the run, so a moved or symlinked run keeps its evidence."""
    from .custody_authority import run_relative
    return run_relative(root, path) or str(path)


def _pin(root, path):
    path = _path(root, path)
    return {'path': _name(root, path), 'sha256': hashlib.sha256(_bytes(path)).hexdigest()}


def _document(root, path, *, optional=True):
    path = _path(root, path)
    if optional and not path.exists():
        return {}, None
    raw = _bytes(path)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON key: ' + key)
            value[key] = item
        return value
    def finite(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('nonfinite JSON')
        return value
    value = json.loads(raw, object_pairs_hook=unique, parse_float=finite,
                       parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    if not isinstance(value, dict):
        raise ValueError(f'recipe input must be an object: {path}')
    return value, {'path': _name(root, path), 'sha256': hashlib.sha256(raw).hexdigest()}


def _pointer(value, pointer):
    if pointer == '':
        return value
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('recipe evidence needs a JSON pointer')
    for token in pointer[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            value = value[int(token)]
        else:
            value = value[token]
    return value


def _escape(key):
    return str(key).replace('~', '~0').replace('/', '~1')


def _leaves(value, prefix=''):
    if isinstance(value, dict) and value:
        for key in sorted(value):
            yield from _leaves(value[key], prefix + '/' + _escape(key))
    else:
        yield prefix or '/', value


def _equal(layer, requested, effective):
    if layer in ('generation', 'shower', 'masses', 'widths', 'translation') and not isinstance(requested, (dict, list)):
        from ravel.physics.native_effective_config import equivalent
        return equivalent(requested, effective)
    return _canonical(requested) == _canonical(effective)


def deviation_payload(row):
    """Exact row content for a numbered flag or the bytes submitted to RDJ.

    Evidence pins enter the payload, so replacing a card with identical settings
    still requires the new source identity to be disclosed.
    """
    return {key: deepcopy(row[key]) for key in ('id', 'layer', 'field', 'node_id', 'claim_id',
        'requested', 'effective', 'requested_present', 'effective_present', 'evidence')}


def _deviation_path(row):
    digest = hashlib.sha256(_canonical(deviation_payload(row))).hexdigest()
    return f'outputs/recipe-deviations/{row["id"]}-{digest}.json'


def deviation_action(rundir, row):
    """RDJ tuning-change action on immutable materialized current-deviation bytes.

    Call ``materialize`` first, then open a ``deviation`` case with this action and
    the applicable tuning class. This function refuses changed/missing payloads.
    """
    root = Path(rundir)
    if row['status'] != 'deviated':
        raise ValueError('only a deviated recipe row has a deviation action')
    path = _deviation_path(row)
    value, pin = _document(root, path, optional=False)
    if value != deviation_payload(row):
        raise ValueError('recipe deviation bytes differ from current row')
    pin['path'] = path
    from .rdj_loop import action_digest
    return {'kind': 'tuning_change', 'summary': 'Accept recipe deviation ' + row['id'],
            'digest': action_digest([pin]), 'pins': [pin]}


def _authorization(root, row, checkin):
    if row['status'] != 'deviated':
        return None
    flags = checkin.get('sections', {}).get('v', [])
    if isinstance(flags, list):
        for flag in flags:
            if (isinstance(flag, dict) and re.fullmatch(r'F[1-9][0-9]*', str(flag.get('id', '')))
                    and isinstance(flag.get('text'), str) and flag['text'].strip()
                    and flag.get('recipe_deviation') == deviation_payload(row)):
                return {'kind': 'checkin1_flag', 'id': flag['id']}
    if not (root / _deviation_path(row)).exists():
        return None
    try:
        action = deviation_action(root, row)
    except (OSError, ValueError):
        return None
    from .rdj_loop import authorizing_receipt
    accepted = authorizing_receipt(root, 'deviation', action)
    if accepted is None:
        return None
    # The receipt authorizes only within its tuning class, and only with a custody human approval.
    point = (accepted.get('case') or {}).get('decision_point') or {}
    tuning = (point.get('tuning') or {}).get('class')
    allowed = RECIPE_TUNING_CLASSES + (('calibration',) if row['layer'] == 'detector' else ())
    if point.get('action_kind') != 'tuning_change' or tuning not in allowed:
        return None
    if not (accepted['receipt'].get('attestation_summary') or {}).get('human_approver'):
        return None
    return {'kind': 'rdj', 'id': accepted['receipt']['receipt_id'],
            'receipt_sha256': accepted['receipt_sha256'], 'case_sha256': accepted['case_sha256'],
            'action_digest': action['digest'], 'tuning_class': tuning}


class _Rows:
    def __init__(self):
        self.values = {}

    def add(self, layer, field, requested=_MISSING, effective=_MISSING, *, node=None, claim=None,
            evidence=(), reason='', absent=False):
        """``absent``: the effective side was read and lacks the setting; never equal to a request."""
        identity = (layer, node, field, claim)
        if identity in self.values:
            raise ValueError('duplicate recipe row: ' + str(identity))
        requested_present, effective_present = requested is not _MISSING, effective is not _MISSING or absent
        if absent:
            effective = None
        status = ('unknown' if not requested_present or not effective_present else
                  'deviated' if absent or not _equal(layer, requested, effective) else 'matched')
        value = {'id': 'R' + hashlib.sha256(_canonical(identity)).hexdigest()[:20],
                 'layer': layer, 'field': field, 'node_id': node, 'claim_id': claim,
                 'requested': requested if requested_present else None,
                 'effective': effective if effective_present else None,
                 'requested_present': requested_present, 'effective_present': effective_present,
                 'status': status, 'evidence': [p for p in evidence if p is not None],
                 'reason': reason or ('requested or effective evidence missing' if status == 'unknown' else
                                     'requested and effective values compared'), 'authorization': None}
        self.values[identity] = value
        return value

    def maps(self, layer, requested, effective, *, evidence=(), claim=None):
        want, got = dict(_leaves(requested)) if requested else {}, dict(_leaves(effective)) if effective else {}
        for field in sorted(want.keys() | got.keys()):
            self.add(layer, field, want.get(field, _MISSING), got.get(field, _MISSING),
                     evidence=evidence, claim=claim)

    def card_settings(self, layer, requested, effective, *, evidence, observed):
        """A read card lacking a setting is an observed omission, not missing evidence."""
        for field in sorted(requested.keys() | effective.keys()):
            absent = field not in effective and observed
            self.add(layer, '/' + _escape(field), requested.get(field, _MISSING),
                     effective.get(field, _MISSING), evidence=evidence, absent=absent,
                     reason='setting absent from current card' if absent else '')


def _observations(root, excluded):
    """Effective values from producer custody: the pinned file must be an output of the named
    registered stage receipt from a recognized tool. The observation list itself is only an index."""
    from .custody_authority import stage_output
    document, _ = _document(root, OBSERVATIONS)
    result = {}
    for observation in document.get('observations', []):
        key = (observation['layer'], observation.get('node_id'), observation['field'])
        if key in result:
            raise ValueError('duplicate recipe observation: ' + str(key))
        pin = observation['pin']
        value, reason, evidence = _MISSING, '', []
        try:
            if _path(root, pin['path']).resolve() in excluded:
                raise ValueError('planning declarations cannot ground an effective observation')
            if not isinstance(observation.get('receipt_id'), str):
                raise ValueError('an observation names the stage receipt that produced its file')
            custody = stage_output(root, observation['receipt_id'], _name(root, _path(root, pin['path'])),
                                   pin['sha256'])
            source, actual = _document(root, pin['path'], optional=False)
            if actual['sha256'] != pin['sha256']:
                raise ValueError('observation sha256 differs from current bytes')
            value = _pointer(source, observation['pointer'])
            evidence = [{**actual, 'receipt_id': custody['receipt_id']}]
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            reason = 'unverified recipe observation: ' + str(exc)
        result[key] = (value, evidence, reason)
    return result


def _parameters(text):
    masses, widths, block = {}, {}, None
    for line in text.splitlines():
        tokens = line.split('#', 1)[0].split()
        if not tokens:
            continue
        if tokens[0].lower() == 'block':
            block = tokens[1].lower()
        elif tokens[0].lower() == 'decay':
            block = None
            widths[str(int(tokens[1]))] = tokens[2]
        elif block == 'mass' and len(tokens) >= 2:
            masses[str(int(tokens[0]))] = tokens[1]
    return masses, widths


def _native(root, rows, plan, plan_pin, manifest, manifest_pin, observations, translated=()):
    from ravel.physics.native_effective_config import assignments, ADAPTER_BASELINE
    controls = plan.get('effective_controls', manifest.get('requested_controls', {}))
    if not isinstance(controls, dict):
        raise ValueError('native effective_controls must be an object')
    current = {}
    rendered = plan.get('rendered', {})
    cards = manifest.get('cards', {})
    names = set(cards) | set(rendered)
    evidence_by_layer = {}
    observed_layers = set()
    for name in sorted(names):
        declared = cards.get(name, {})
        path = declared.get('path') or ('output/' + name)
        expected_hash = (hashlib.sha256(rendered[name].encode()).hexdigest() if name in rendered
                         else declared.get('sha256', _MISSING))
        pin, text, problem = None, None, ''
        try:
            raw = _bytes(_path(root, path))
            pin = {'path': _name(root, _path(root, path)), 'sha256': hashlib.sha256(raw).hexdigest()}
            text = raw.decode()
        except (OSError, ValueError, UnicodeError) as exc:
            problem = 'current card unavailable: ' + str(exc)
        rows.add('cards', '/' + _escape(name), expected_hash,
                 pin['sha256'] if pin else _MISSING, evidence=[plan_pin, manifest_pin, pin], reason=problem)
        if name in ('run_card.dat', 'shower.cfg'):
            layer = 'generation' if name == 'run_card.dat' else 'shower'
            current[layer] = assignments(text, run=layer == 'generation') if text is not None else {}
            evidence_by_layer[layer] = [plan_pin, pin]
            if text is not None:
                observed_layers.add(layer)
        if name == 'param_card.dat':
            masses, widths = _parameters(text or '')
            current.update(masses=masses, widths=widths)
            evidence_by_layer.update(masses=[plan_pin, pin], widths=[plan_pin, pin])
            if text is not None:
                observed_layers.update(('masses', 'widths'))
    generation = {**assignments(rendered.get('run_card.dat', ''), run=True), **controls.get('generation', {})}
    shower = {**ADAPTER_BASELINE, **assignments(rendered.get('shower.cfg', '')),
              **plan.get('shower_translation', {}).get('requested_overlays', {})}
    rows.card_settings('generation', generation, current.get('generation', {}),
                       evidence=evidence_by_layer.get('generation', [plan_pin, manifest_pin]), observed='generation' in observed_layers)
    rows.card_settings('shower', shower, current.get('shower', {}),
                       evidence=evidence_by_layer.get('shower', [plan_pin, manifest_pin]), observed='shower' in observed_layers)
    # A request option the native translation dropped is deviated, never unknown: the read card
    # decides when it exists, else the native requested side.
    native_requested = {'generation': generation, 'shower': shower}
    for node, layer, key, value, request_pin in translated:
        source = current.get(layer, {}) if layer in observed_layers else native_requested[layer]
        present = key in source
        rows.add('translation', f'/{layer}/{_escape(key)}', value, source[key] if present else _MISSING,
                 node=node, absent=not present,
                 evidence=[request_pin, *evidence_by_layer.get(layer, [plan_pin, manifest_pin])],
                 reason=('requested option dropped by native translation' if not present else
                         'request compared with the ' + ('current card' if layer in observed_layers
                                                          else 'native requested side')))
    masses, widths = _parameters(rendered.get('param_card.dat', ''))
    rows.card_settings('masses', {**masses, **plan.get('expected_masses_gev', {})}, current.get('masses', {}),
                       evidence=evidence_by_layer.get('masses', [plan_pin, manifest_pin]), observed='masses' in observed_layers)
    rows.card_settings('widths', widths, current.get('widths', {}),
                       evidence=evidence_by_layer.get('widths', []), observed='widths' in observed_layers)
    process_path = plan.get('inputs', {}).get('process_card')
    if process_path:
        try:
            text = _bytes(_path(root, process_path)).decode()
            current['process_commands'] = [line.split('#', 1)[0].strip() for line in text.splitlines()
                                           if line.split('#', 1)[0].strip()]
            pin = _pin(root, process_path)
        except (OSError, ValueError, UnicodeError):
            pin = None
        source = next((p for p in plan.get('sources', []) if _path(root, p['path']) == _path(root, process_path)), None)
        rows.add('cards', '/process_card', source['sha256'] if source else _MISSING,
                 pin['sha256'] if pin else _MISSING, evidence=[plan_pin, pin])
    rows.maps('process', controls.get('process', {}), {'commands': current['process_commands']} if 'process_commands' in current else {},
              evidence=[plan_pin, manifest_pin])
    # Prepared statistics are declarations, not effective patch evidence.
    metadata, metadata_pin = _document(root, 'output/signal_model.json')
    stats = {}
    for source, destination in {'mc_stat_policy': 'mc_stat', 'additional_scale': 'kfactor',
            'luminosity_pb_inverse': 'luminosity_pb_inverse', 'compressed_signal_model': 'compressed_signal_model'}.items():
        if source in metadata:
            stats[destination] = metadata[source]
    rows.maps('statistics', controls.get('statistics', {}), stats, evidence=[plan_pin, metadata_pin])
    for field in ('detector_trigger_ISR_theory_variations', 'input_combination', 'control_region_definition'):
        if field in metadata:
            rows.add('patch_metadata', '/' + field, effective=metadata[field], evidence=[metadata_pin])
    if 'patch' in metadata:
        pin = metadata['patch']
        try:
            actual = _pin(root, pin['path'])
        except (OSError, ValueError):
            actual = None
        rows.add('cards', '/signal_patch', pin['sha256'], actual['sha256'] if actual else _MISSING,
                 evidence=[metadata_pin, actual])
    labels = controls.get('tool_version_labels', manifest.get('requested_controls', {}).get('tool_version_labels', {}))
    for tool, declaration in sorted(labels.items()):
        field = '/' + _escape(tool)
        effective, pins, reason = observations.get(('tool_versions', None, field), (_MISSING, [], 'installed version unobserved'))
        rows.add('tool_versions', field, declaration['declared'], effective,
                 evidence=[plan_pin, manifest_pin, *pins], reason=reason)
    for name in _DETECTOR_FIELDS:
        field = '/' + name
        effective, pins, reason = observations.get(('detector', None, field), (_MISSING, [], 'detector recipe detail unobserved'))
        rows.add('detector', field, effective=effective, evidence=pins, reason=reason)


def _targets(root, rows):
    if not (root / 'inputs/agreement_targets.json').exists():
        return
    from ravel.validation.agreement_target import targets
    for claim, target in sorted(targets(root).items()):
        for index, recipe in enumerate(target['reference']['recipe_pins']):
            locator = recipe['locator']
            if '://' in locator:
                rows.add('reference_recipe', f'/pins/{index}', recipe['sha256'], claim=claim,
                         reason='remote recipe pin unverified; no acquisition performed')
                continue
            try:
                record, pin = _document(root, locator, optional=False)
                if pin['sha256'] != recipe['sha256']:
                    raise ValueError('reference recipe hash differs from its target pin')
            except (OSError, ValueError) as exc:
                rows.add('reference_recipe', f'/pins/{index}', recipe['sha256'], claim=claim, reason=str(exc))
                continue
            # A pinned recipe may supply generic layers plus card_hashes. Unmapped
            # formats are retained as unknown rather than interpreted by name.
            layers = dict(record.get('layers', {}))
            if 'card_hashes' in record:
                layers['cards'] = record['card_hashes']
            if not layers:
                rows.add('reference_recipe', f'/pins/{index}', recipe['sha256'], claim=claim,
                         evidence=[pin], reason='pinned recipe format has no comparable layers')
            for layer, requested in sorted(layers.items()):
                for field, value in _leaves(requested):
                    runtime = rows.values.get((layer, None, field, None))
                    effective = (runtime['effective'] if runtime and runtime['effective_present'] else _MISSING)
                    rows.add(layer, f'/recipes/{index}' + field, value, effective, claim=claim,
                             evidence=[pin, *(runtime['evidence'] if runtime else [])])


def build(rundir, *, checkin=None):
    """Recompute the complete ledger; missing observations stay unknown.

    Caller CHECK-IN context is used only while composing its numbered flags.
    Pre-full checks independently read the on-disk CHECK-IN and verify approval.
    """
    root = Path(rundir).absolute()
    contract, _ = _document(root, 'inputs/task_contract.json')
    def planned(key, default):
        declared = contract.get(key)
        value, pin = _document(root, declared['path'] if declared else default, optional=not bool(declared))
        if declared and pin['sha256'] != declared['sha256']:
            raise ValueError(f'{key} hash differs from contract pin')
        return value, pin
    request, request_pin = planned('request_plan', 'inputs/plan.json')
    native, native_pin = planned('execution_plan', NATIVE_PLAN)
    manifest, manifest_pin = _document(root, MANIFEST)
    excluded = {(root / path).resolve() for path in (OBSERVATIONS, RECORD, MANIFEST, 'inputs/task_contract.json',
                                        'inputs/checkin1.json', 'inputs/agreement_targets.json')}
    excluded.update(_path(root, p['path']).resolve() for p in (request_pin, native_pin) if p)
    observations = _observations(root, excluded)
    rows = _Rows()
    from ravel.validation.validate_request_plan import signatures
    registry = signatures()
    translated = []
    for node in request.get('nodes', []):
        fields = {f['pointer']: f['value'] for f in node.get('fields', [])}
        for pointer, layer in TRANSLATED.items():
            if isinstance(fields.get(pointer), dict):
                translated += [(node['id'], layer, key, value, request_pin)
                               for key, value in sorted(fields[pointer].items())]
        critical = registry.get(node.get('operation'), {}).get('critical_fields', [])
        for field in sorted(set(critical) | fields.keys()):
            effective, pins, reason = observations.get(('operation', node['id'], field),
                (_MISSING, [], 'operation effective value unobserved'))
            rows.add('operation', field, fields.get(field, _MISSING), effective, node=node['id'],
                     evidence=[request_pin, *pins], reason=reason)
        if node.get('operation') and node['operation'] not in registry:
            rows.add('operation', '/signature', node['operation'], node=node['id'],
                     evidence=[request_pin], reason='operation critical-field signature unavailable')
    if native or manifest:
        _native(root, rows, native, native_pin, manifest, manifest_pin, observations, translated)
    _targets(root, rows)
    if checkin is None:
        checkin, _ = _document(root, 'inputs/checkin1.json')
    values = sorted(rows.values.values(), key=lambda row: (row['layer'], row['node_id'] or '',
                                                         row['field'], row['claim_id'] or ''))
    for value in values:
        value['authorization'] = _authorization(root, value, checkin)
    return {'schema_version': 1, 'kind': 'recipe-ledger', 'rows': values,
            'limitations': ['Current prepared settings and pinned observations do not prove runtime consumption',
                            'Recipe matching is not physics or detector certification',
                            'Observations count only as registered stage outputs of recognized tools']}


def rows(rundir):
    """Consumer seam: current rows, not an unchecked cached ledger."""
    return build(rundir)['rows']


def materialize(rundir):
    """Write ledger and deviation payloads for prospective review; never executes tools."""
    root = Path(rundir)
    record = build(root)
    for row in record['rows']:
        if row['status'] == 'deviated':
            path = root / _deviation_path(row)
            if path.exists() and read_json(path) != deviation_payload(row):
                raise ValueError('retained recipe deviation changed; use a prospective run or restore its source bytes')
            atomic_json(path, deviation_payload(row))
    atomic_json(root / RECORD, record)
    return record


def _deviation_errors(record):
    return [f'recipe deviation {r["id"]} ({r["layer"]}{r["field"]}) needs an accepted RDJ receipt or an exact CHECK-IN 1 flag'
            for r in record['rows'] if r['status'] == 'deviated' and r['authorization'] is None]


def _unpinned_plan_errors(rundir):
    """An epoch-2 contract must pin the native plan, or its requested side is self-editable."""
    contract, _ = _document(Path(rundir), 'inputs/task_contract.json')
    if (contract and not _legacy(contract) and not contract.get('execution_plan')
            and (Path(rundir) / NATIVE_PLAN).exists()):
        return [f'the native execution plan {NATIVE_PLAN} is not pinned by the task contract; '
                'a requested side the run can edit cannot ground a match']
    return []


def before_full_errors(rundir):
    record = build(rundir)
    errors = _unpinned_plan_errors(rundir) + _deviation_errors(record)
    if any(r['authorization'] and r['authorization']['kind'] == 'checkin1_flag' for r in record['rows']):
        from .workflow_state import verify_approval
        errors += ['recipe CHECK-IN 1 flag is not approval-bound: ' + e for e in verify_approval(str(rundir))]
    return errors


def checkin_section(context):
    root = context.get('base_dir')
    if root is None:
        return None
    from ravel.validation.validate_checkin import _sibling_contract
    current = _sibling_contract(root)
    contract = current if isinstance(current, dict) else context.get('contract')
    if (not _has_inputs(root, contract) or
            (_legacy(contract) and 'recipe_ledger' not in context.get('document', {}).get('sections', {}))):
        return None
    record = build(root, checkin=context.get('document'))
    return record if record['rows'] else None


def _requested_view(record):
    """CHECK-IN 1 commitments: the requested side of each row, by row id."""
    if not isinstance(record, dict) or not isinstance(record.get('rows'), list):
        return None
    try:
        return {r['id']: {k: r[k] for k in _REQUESTED_VIEW} for r in record['rows']}
    except (KeyError, TypeError):
        return None


def section_errors(content, context):
    """The approved requested side must still hold, and every current requested row except
    card identities (which preparation may add) must have been shown. Status changes, such as
    an unknown row that becomes matched, are evidence, not a changed approval."""
    expected = checkin_section(context)
    if expected is None:
        return []
    approved, current = _requested_view(content), _requested_view(expected)
    changed = approved is None or any(current.get(i) != v for i, v in approved.items()) or any(
        i not in approved for i, v in current.items() if v['requested_present'] and v['layer'] != 'cards')
    return (['CHECK-IN 1 recipe ledger missing or changed'] if changed else []) + _deviation_errors(expected)


def checkin3_section(rundir, record=None):
    record = build(rundir) if record is None else record
    if not record['rows']:
        return None
    return {'schema_version': 1, 'unknown': [r for r in record['rows'] if r['status'] == 'unknown'],
            'deviated': [r for r in record['rows'] if r['status'] == 'deviated'],
            'matched_count': sum(r['status'] == 'matched' for r in record['rows']),
            'limitations': record['limitations']}


def with_checkin3_section(document, rundir):
    result = deepcopy(document)
    section = checkin3_section(rundir)
    if section is not None:
        result.setdefault('sections', {})['recipe_ledger'] = section
    return result


def checkin3_errors(sections, rundir):
    from ravel.validation.validate_checkin import _sibling_contract
    if _legacy(_sibling_contract(rundir)) and 'recipe_ledger' not in sections:
        return []
    try:
        record = build(rundir)
        expected = checkin3_section(rundir, record)
    except Exception as exc:  # noqa: BLE001 - any unreadable evidence is a refusal, never a traceback
        return ['CHECK-IN 3 recipe evidence unreadable: ' + str(exc)]
    if expected is None:
        return []
    errors = [] if sections.get('recipe_ledger') == expected else [
        'CHECK-IN 3 must list every unknown recipe ledger row and current deviation']
    return errors + _deviation_errors(record)


def _has_inputs(root, contract):
    return (any((Path(root) / name).exists() for name in (NATIVE_PLAN, MANIFEST, OBSERVATIONS,
                'inputs/plan.json', 'inputs/agreement_targets.json')) or
            (isinstance(contract, dict) and bool(contract.get('request_plan') or contract.get('execution_plan'))))


def _legacy(contract):
    # Preserve existing epoch-one byte decisions; absence of a contract is not
    # an escape hatch for prospective recipe inputs.
    return isinstance(contract, dict) and bool(contract) and contract.get('agent_layer_epoch', 1) == 1


def gate_errors(rundir, gate, action):
    """Launch-provider seam. Inspection preserves all evidence and never writes."""
    if gate != 'launch':
        return []
    from .decision_gate import GateError
    try:
        errors = before_full_errors(rundir)
    except Exception as exc:  # noqa: BLE001 - a malformed input refuses the launch, never escapes the gate
        errors = ['recipe evidence unreadable: ' + str(exc)]
    return [GateError('recipe_deviation', gate, 'recipe_ledger', error,
                      'Record an exact numbered CHECK-IN 1 flag and re-approve, or obtain the RDJ deviation receipt.',
                      ('recipe:current-inputs',)) for error in errors]


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--rundir', type=Path, required=True)
    parser.add_argument('--write', action='store_true', help='Materialize prospective ledger and deviation bytes')
    parser.add_argument('--check-full', action='store_true', help='Refuse deviations without current authorization')
    parser.add_argument('--checkin3', action='store_true', help='Print the current delivery disclosure section')
    args = parser.parse_args(argv)
    try:
        if args.check_full:
            errors = before_full_errors(args.rundir)
            if errors:
                print('\n'.join(errors), file=sys.stderr)
                return 1
        record = materialize(args.rundir) if args.write else build(args.rundir)
        if args.checkin3:
            record = checkin3_section(args.rundir)
        print(json.dumps(record, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print('recipe ledger refused: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
