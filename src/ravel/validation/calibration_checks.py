"""Refusing detector-calibration invariants, independent of an optimizer's verdict.

Authority comes from custody, not from a pin. Each calibration input (node samples,
responses and observables, knob band anchors, imported calibrations) must be a registered
acquisition or a registered stage output of a recognized tool. Signal-model completeness is a
registered ``signal_model_complete_before_calibration`` check result from a recognized check.
A file the agent wrote inside the run satisfies none of these.
"""
from __future__ import annotations
import hashlib
import json
import math
from importlib.resources import files
from pathlib import Path

CHECKS = ('calibration_target_disjoint', 'confirmation_separation', 'anchored_bounds',
          'calibration_frozen', 'imported_calibration', 'calibration_before_and_after',
          'calibration_no_global_scalar', 'signal_model_complete_before_calibration')
INTERMEDIATE = {'signal_yields', 'efficiency_map', 'cutflow'}
PARITY_CHECK = 'signal_model_complete_before_calibration'
PARITY_PRODUCERS = ('ravel.validation.claim_checks', 'ravel.validation.patch_parity')
SCALAR_COSINE = 0.999


def response_modules():
    return set(json.loads(files('ravel').joinpath('data/calibration/response_modules.json').read_text())['modules'])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def pin_path(pin, base):
    path = Path(pin.get('path', pin.get('locator', '')))
    if not path.is_absolute(): path = Path(base) / path
    if not path.name or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('regular local pin required')
    sha = pin.get('sha256')
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('local sha256 pin required')
    return path.absolute()


def read_pin(pin, base):
    path = pin_path(pin, base)
    raw = path.read_bytes()
    if len(raw) > 16 * 1024**2 or hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('calibration pin changed or exceeds size bound')
    return json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def pin_identity(pin, base):
    return str(pin_path(pin, base)), pin['sha256']


def custody(pin, base, label, *, checked=False):
    """The custody record of a calibration input: a registered stage output when the pin names
    ``receipt_id``, else a registered acquisition. ``checked``: the caller already hashed the bytes."""
    from ravel.workflow import custody_authority as ca
    rel = ca.run_relative(base, pin_path(pin, base))
    if rel is None:
        raise ValueError(f'{label} lies outside the run')
    try:
        if pin.get('receipt_id') is not None:
            return ca.stage_output(base, pin['receipt_id'], rel, pin['sha256'], checked=checked)
        return ca.acquisition(base, rel, pin['sha256'], checked=checked)
    except ca.AuthorityError as exc:
        raise ValueError(f'{label} is neither a registered acquisition nor a registered stage output: {exc}') from None


def read_custody(pin, base, label, *, limit=16 * 1024**2):
    """Bytes of a calibration input, read once, checked against its pin and its custody record."""
    raw = pin_path(pin, base).read_bytes()
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError(f'{label} pin changed or exceeds its size bound')
    custody(pin, base, label, checked=True)
    return raw


def _vectors(value, found):
    if isinstance(value, list) and value and all(number(x) for x in value):
        found.add(tuple(round(float(x), 9) for x in value))
    elif isinstance(value, dict):
        for item in value.values(): _vectors(item, found)
    elif isinstance(value, list):
        for item in value: _vectors(item, found)
    return found


def reference_vectors(spec, base):
    """Every numeric vector in the local agreement-reference pins; a calibration observable may not repeat one."""
    found = set()
    for pin in spec['agreement_target']['reference']['pins']:
        if '://' in str(pin.get('locator', pin.get('path', ''))):
            continue
        _vectors(read_pin(pin, base), found)
    return found


def refuse_reference_values(values, vectors, node_id):
    if tuple(round(float(x), 9) for x in values) in vectors:
        raise ValueError(f'calibration_target_disjoint: node {node_id} observable repeats agreement reference values')


def node_pins(node):
    return [node['response'],node['observable'],*node['samples'].values()]


def calibration_target_disjoint(spec, base):
    refs = spec['agreement_target']['reference']['pins']
    if not refs: raise ValueError('calibration_target_disjoint needs agreement reference pins')
    held = [pin_identity(p, base) for n in spec['held_out_nodes'] for p in node_pins(n)]
    forbidden = [pin_identity(p, base) for p in refs] + held
    adaptive_pins = [p for n in spec['calibration_nodes'] for p in node_pins(n)]
    if spec['signal_model'].get('patch_parity'): adaptive_pins.append(spec['signal_model']['patch_parity'])
    if spec.get('imported_calibration'): adaptive_pins.append(spec['imported_calibration']['response'])
    for pin in adaptive_pins:
        path, sha = pin_identity(pin, base)
        if any(path == p or sha == s for p,s in forbidden):
            raise ValueError('calibration_target_disjoint: claim or held-out artifact used for calibration')
    # A band anchor may share the claim's reference record (a published band beside the claim);
    # it may never be a held-out artifact.
    for knob in spec['knobs']:
        path, sha = pin_identity(knob['anchor']['pin'], base)
        if any(path == p or sha == s for p, s in held):
            raise ValueError('calibration_target_disjoint: held-out artifact used as a band anchor')
    return {'id': 'check:calibration_target_disjoint', 'passed': True,
            'subject_sha256': digest(spec), 'reference_pins': refs}


def confirmation_separation(spec, base):
    all_nodes = spec['calibration_nodes'] + spec['held_out_nodes']
    if not spec['calibration_nodes'] or not spec['held_out_nodes']:
        raise ValueError('confirmation_separation requires both partitions')
    ids = [n['id'] for n in all_nodes]
    if len(set(ids)) != len(ids): raise ValueError('confirmation_separation: overlapping nodes or seeds')
    # Seeds separate the partitions; nodes within one partition may share a seed with distinct samples.
    if {n['seed'] for n in spec['calibration_nodes']} & {n['seed'] for n in spec['held_out_nodes']}:
        raise ValueError('confirmation_separation: overlapping nodes or seeds')
    seen = set(); pins = set()
    for node in all_nodes:
        if not isinstance(node['id'], str) or not node['id'] or type(node['seed']) is not int:
            raise ValueError('explicit node and integer seed required')
        ids = node['sample_ids']
        if not ids or any(not isinstance(i,str) or not i for i in ids) or len(set(ids)) != len(ids) or seen.intersection(ids):
            raise ValueError('confirmation_separation: overlapping sample identities')
        seen.update(ids)
        if set(node) != {'id','seed','sample_ids','samples','response','observable'} or set(node['samples']) != {'generated','showered'}:
            raise ValueError('frozen generated and showered sample pins required')
        for pin in node_pins(node):
            identity = pin_identity(pin, base)
            if identity in pins: raise ValueError('confirmation_separation: duplicate artifact')
            pins.add(identity)
    return {'id':'check:confirmation_separation','passed':True,'subject_sha256':digest(spec)}


def pointer(value, path):
    if not isinstance(path,str) or not path.startswith('/'): raise ValueError('anchor JSON pointer required')
    for part in path[1:].split('/'):
        key = part.replace('~1','/').replace('~0','~')
        value = value[int(key)] if isinstance(value,list) else value[key]
    return value


def signal_model_complete_before_calibration(spec, base):
    """False for a passed registered completeness check; True when a scoped approximation must replay."""
    from ravel.workflow import custody_authority as ca
    model = spec['signal_model']
    if model.get('patch_parity'):
        pin = model['patch_parity']
        rel = ca.run_relative(base, pin_path(pin, base))
        try:
            if rel is None: raise ca.AuthorityError('the completeness check result lies outside the run')
            parity = ca.registered_check(base, rel, pin['sha256'], PARITY_CHECK, producers=PARITY_PRODUCERS)
        except ca.AuthorityError as exc:
            raise ValueError(f'{PARITY_CHECK}: {exc}') from None
        if parity.get('status') in ('passed', 'pass') and parity.get('missing_components', []) == []:
            return False
    if model.get('approximation_action'):
        return True  # The operation must replay the scoped R2 authority before any read.
    raise ValueError('signal_model_complete_before_calibration: complete patch or scoped approximation required')


def validate_spec(spec, base, *, check_observables=True):
    expected = {'schema_version','kind','study_id','agreement_target','knobs','calibration_nodes','held_out_nodes',
                'loss','stop','budget','signal_model','imported_calibration'}
    if set(spec) != expected:
        raise ValueError('global signal scalar or undeclared calibration field is refused')
    if spec['schema_version'] != 1 or spec['kind'] != 'cal:spec': raise ValueError('calibration spec v1 required')
    sha = spec['study_id']
    if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha): raise ValueError('preregistration digest required')
    calibration_target_disjoint(spec,base); confirmation_separation(spec,base)
    for node in spec['calibration_nodes']:
        for pin in node_pins(node): custody(pin, base, f'calibration node {node["id"]} input')
    modules = response_modules()
    outside = False; names=set()
    if not spec['knobs'] or len(spec['knobs'])>8: raise ValueError('one to eight declared response knobs required')
    for knob in spec['knobs']:
        if set(knob) != {'module','parameter','bins','nominal','values','bounds','anchor'}: raise ValueError('declared response knob required')
        name = (knob['module'],knob['parameter'])
        if not all(isinstance(x,str) and x for x in name) or name in names: raise ValueError('distinct response knob required')
        if knob['module'] not in modules:
            raise ValueError(f'knob module {knob["module"]!r} is not a declared detector-response module')
        names.add(name)
        if not knob['bins'] or len(set(knob['bins'])) != len(knob['bins']) or any(type(b)!=int or b<0 for b in knob['bins']): raise ValueError('declared response bins required')
        anchor = knob['anchor']
        if anchor.get('kind') not in ('external_fact','retrieved_document'): raise ValueError('anchored band requires a source')
        source = json.loads(read_custody(anchor['pin'], base, 'knob band anchor'))
        band = [pointer(source,anchor['low_pointer']),pointer(source,anchor['high_pointer'])]
        if len(knob['bounds']) != 2 or not all(number(x) for x in band) or band[0]>=band[1] or knob['bounds'] != band:
            raise ValueError('knob bounds differ from anchored band')
        if not number(knob['nominal']) or not band[0]<=knob['nominal']<=band[1]: raise ValueError('nominal outside anchored band')
        if not isinstance(knob['values'],list) or not knob['values'] or len(set(knob['values'])) != len(knob['values']) or not all(number(x) for x in knob['values']): raise ValueError('finite declared knob candidates required')
        outside |= any(not band[0]<=x<=band[1] for x in knob['values'])
    if spec['loss'] != 'squared_error': raise ValueError('only declared squared_error loss is supported')
    for row in (spec['stop'],spec['budget']):
        cap=row.get('max_trials')
        if type(cap)!=int or not 1<=cap<=10000: raise ValueError('bounded max_trials required')
    if set(spec['stop']) != {'max_trials','loss_at_most'} or set(spec['budget']) != {'max_trials'} or not number(spec['stop']['loss_at_most']) or spec['stop']['loss_at_most']<0:
        raise ValueError('declared stop and budget required')
    approximation=signal_model_complete_before_calibration(spec,base)
    imported=spec['imported_calibration']
    in_sample = False
    if imported is not None:
        if set(imported) != {'source','fitted_on','response'} or not isinstance(imported['fitted_on'],list) or not imported['fitted_on'] \
                or not all(isinstance(x, str) and x for x in imported['fitted_on']):
            raise ValueError('imported_calibration requires source and fitted_on')
        custody(imported['source'], base, 'imported calibration source')
        custody(imported['response'], base, 'imported calibration response')
        fitted = set(imported['fitted_on'])
        if fitted & {n['id'] for n in spec['held_out_nodes']}:
            raise ValueError('imported_calibration was fitted on held-out node(s); they cannot confirm it')
        # In-sample for this target: fitted on any node of this study.
        in_sample = bool(fitted & {n['id'] for n in spec['calibration_nodes']})
    if check_observables:
        vectors = reference_vectors(spec, base)
        for node in spec['calibration_nodes']:
            refuse_reference_values(observable(read_pin(node['observable'],base),node), vectors, node['id'])
    return {'outside_band':outside,'approximation':approximation,'imported_in_sample':in_sample}


def observable(value, node):
    if value.get('node') != node['id'] or value.get('quantity') not in INTERMEDIATE:
        raise ValueError('only intermediate calibration observables at the declared node are admitted')
    if not value.get('values') or not all(number(x) for x in value['values']): raise ValueError('finite per-bin observables required')
    return value['values']


def delivery_check(receipt, *, evidence_status='checked'):
    if receipt.get('imported_calibration') is not None and evidence_status == 'validated' \
            and receipt.get('imported_in_sample', True):
        raise ValueError('imported_calibration is in-sample for this target and cannot be validated')
    if not receipt.get('before') or not receipt.get('after') or not receipt.get('held_out_scores'):
        raise ValueError('calibration before-and-after delivery and held-out scores required')
    if not receipt.get('response') or not receipt.get('n_trials') or not receipt.get('study_trials'):
        raise ValueError('frozen response and all trials required')
    return []


def gate_errors(rundir, gate, action):
    """Decision-gate seam: replay exact calibration spec, never accept a producer's pass flag."""
    from ravel.workflow.decision_gate import GateError
    pin=action.get('calibration_spec')
    if pin is None:
        if action.get('kind') != 'detector-calibration': return []
        return [GateError('calibration_target_disjoint',gate,'calibration','a detector-calibration action names no pinned calibration spec',
                          'Supply the pinned calibration spec the approval binds.',('check:calibration_target_disjoint',))]
    try:
        spec=read_pin(pin,rundir)
        validate_spec(spec,rundir,check_observables=False)
    except Exception as exc:  # noqa: BLE001 - a malformed spec refuses, never escapes the gate
        return [GateError('calibration_target_disjoint',gate,'calibration',str(exc),
                          'Supply an admissible pinned calibration spec.',('check:calibration_target_disjoint',))]
    return []
