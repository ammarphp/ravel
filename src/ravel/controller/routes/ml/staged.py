"""Route adapter of ``ml.training``: the staged ML executor's plan steps under the controller.

The controller graph calls these functions (``routes.select.adapter_module``) with a context
``{store, run_dir, plan, state, reading, contract}``:

- ``parameters(spec, reading, contract, supplied)`` (compile time): the installed interpreter and the
  one supplied training table with its intake digest. A missing or ambiguous table stays unbound, so
  the compiler keeps it an open obligation and the request is planned by the judgment route.
- ``step(step, outcome, context)``: after a stage step completed, its adopted receipt (read through its
  custody record and digest) must say ``completed`` and its stage record must agree; a refused, held,
  budget-exhausted or failed stage fails the step with its typed code. When the full training
  completes, the withheld population is claimed and spent in the machine-wide exposure ledger before
  the evaluation can read it (one read across studies); the evaluation closes the claim.
- ``gate(transition, context)``: every gate refuses a plan in which a step other than the one
  evaluation reads the withheld partition; CHECK-IN 1 also refuses when a training prerequisite is
  missing on this host or the admitted withheld population was already claimed or read by another
  study; the delivery gate refuses unless the executable reviewer items passed.
- ``checkin(kind, context)``: the admitted data, the leakage screen, the smoke, the evaluation and the
  review, for the check-in views.
- ``ending(reason, context)``: the stage-by-stage state for the qualified delivery; a withheld
  population spent without a completed evaluation is closed as failed and never reused.

Nothing here grants authority or edits a plan; a problem is a typed reason, and the store records are
evidence for the sink and the receipt.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import training as rules

RECEIPT = 'outputs/ml/receipt.json'
STAGE_RECORD = 'ml-stage'
EXPOSURE_RECORD = 'ml-exposure'
ENDING_RECORD = 'ml-stage-ending'
TABLE_SUFFIXES = ('.npz', '.csv', '.root')
EXPLICIT_KIND = 'ml-table'
# The record each stage writes beside its receipt, and the status it must carry.
RECORDS = {'admit': 'outputs/admission.json', 'features': 'outputs/features.json', 'train': 'outputs/training.json',
           'evaluate': 'outputs/evaluation.json', 'card': 'outputs/model_card.json', 'review': 'outputs/review.json'}
SPEC_OUTPUT = 'outputs/ml_study_spec.json'


class AdoptionMissing(ValueError):
    """An output the check needs is not an accepted adopted artifact with its recorded bytes."""


def _unwrap(row):
    return row['record'] if type(row) is dict and type(row.get('record')) is dict else row


def records(store, kind):
    return [_unwrap(row) for row in store.scan(kind)]


# ---- compile time -------------------------------------------------------------------------------

def training_table(supplied):
    """The one supplied training table: an explicit ``ml-table`` input, else the one table-like file."""
    rows = [r for r in supplied or () if type(r) is dict]
    explicit = [r for r in rows if r.get('kind') == EXPLICIT_KIND]
    pool = explicit or [r for r in rows if type(r.get('path')) is str
                       and r['path'].lower().endswith(TABLE_SUFFIXES)]
    if (len(pool) != 1 or type(pool[0].get('path')) is not str or not pool[0]['path']
            or not re.fullmatch('[0-9a-f]{64}', str(pool[0].get('sha256', '')))):
        return None
    return pool[0]


def parameters(spec, reading, contract, supplied):
    import sys
    found = {'python': sys.executable}
    row = training_table(supplied)
    if row is not None:
        found.update(dataset_path=row['path'], dataset_sha256=row['sha256'])
    return found


EXECUTOR_ROLE = 'ml-trainer'


def signatures():
    """The operation signatures of the staged stages (to register in ``data/operation_signatures.json``)."""
    from ravel.workflow import ml_stages
    found = {}
    for stage in ml_stages.STAGES:
        consumes = [{'slot': 'specification', 'kind': 'document'}]
        if stage != 'admit':
            consumes.append({'slot': 'records', 'kind': 'table', 'cardinality': '1..*'})
        if stage in ('evaluate', 'review'):
            consumes.append({'slot': 'models', 'kind': 'selection'})
        found[ml_stages.OPERATIONS[stage]] = {
            'summary': SUMMARIES[stage],
            'implementation': {'kind': 'command', 'module': 'ravel.workflow.ml_stages'},
            'consumes': consumes,
            'produces': [{'slot': _slot(path, ml_stages.OUTPUTS[stage]), 'kind': kind}
                         for path, kind in ml_stages.OUTPUTS[stage]],
            'effects': [], 'cost': {'unit': 'task', 'forecast': None, 'ceiling_pointer': None}, 'critical_fields': [],
            'basis': {'adds': [{'element': BASIS[stage]}] if stage in BASIS else [], 'passes': ['specification']},
            'tools': ['NumPy'],
            'stages': [], 'review': {'checks': ['io_contract', 'known_answer_tests']}, 'fidelity_rank': 1}
    return found


def _slot(path, outputs):
    """A produced slot name unique within the stage: the file stem, with its suffix when stems repeat."""
    stem = Path(path).stem
    if sum(Path(other).stem == stem for other, _ in outputs) == 1:
        return stem
    return Path(path).name.replace('.', '_')


def executors():
    """``operation -> production role`` rows for ``data/roles/executors.json``."""
    from ravel.workflow import ml_stages
    return {ml_stages.OPERATIONS[stage]: EXECUTOR_ROLE for stage in ml_stages.STAGES}


SUMMARIES = {
    'admit': 'Admission of one supplied binary-classification table and its split into train, validation and a '
             'withheld partition, with provenance, identity, overlap and sizing checks.',
    'features': 'Feature definition on the training partition with the label-leakage screen and train-only '
                'preprocessing.',
    'train': 'Training launch of every declared arm and seed within the approved budget, never given the withheld '
             'partition; the smoke rung trains one seed briefly.',
    'evaluate': 'The one evaluation read of the withheld partition with the frozen models; metrics, calibration and '
                'the overtraining comparison.',
    'card': 'Model card from the stage records.',
    'review': 'Executable reviewer items recomputed from pinned arrays and stage records.'}
# Basis elements from the closed signature vocabulary: admission passes the supplied data on,
# features are authored definitions, training adds the trained model. The metrics, card and
# review products add no basis element of their own.
BASIS = {'admit': 'supplied_inputs', 'features': 'authored_code', 'train': 'trained_model'}


# ---- adopted artifacts --------------------------------------------------------------------------

def custody_index(store):
    found = {}
    for row in records(store, 'custody'):
        if type(row) is dict and type(row.get('artifact')) is str:
            found[row['artifact']] = row
    return found


def adopted(store, run_dir, step_id, path, *, index=None):
    """``(bytes, absolute path, custody record)`` of an accepted adopted output, digest-checked."""
    index = custody_index(store) if index is None else index
    record = index.get(f'{step_id}:{path}')
    if record is None or record.get('status') != 'accepted' or type(record.get('sha256')) is not str:
        raise AdoptionMissing(f'{step_id}:{path} is not an accepted adopted artifact')
    run = Path(run_dir).resolve()
    destination = Path(record.get('destination', ''))
    target = run / destination
    if (destination.is_absolute() or '..' in destination.parts or not target.resolve().is_relative_to(run)
            or any(p.is_symlink() for p in (target, *target.parents)) or not target.is_file()):
        raise AdoptionMissing(f'{step_id}:{path} is missing from the run directory')
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise AdoptionMissing(f'{step_id}:{path} differs from its custody digest')
    return raw, target, record


def adopted_json(store, run_dir, step_id, path, *, index=None):
    raw, target, record = adopted(store, run_dir, step_id, path, index=index)
    return json.loads(raw), target, record


def stage_of(step):
    return rules.stage_of(step)


def is_smoke(step):
    return '--smoke' in (((step.get('parameters') or {}).get('launch') or {}).get('argv') or ())


def stage_steps(plan, stage, *, smoke=None):
    return [s for s in (plan or {}).get('steps') or () if stage_of(s) == stage
            and (smoke is None or is_smoke(s) == smoke)]


def _one(plan, stage, *, smoke=None):
    found = stage_steps(plan, stage, smoke=smoke)
    if len(found) != 1:
        raise AdoptionMissing(f'the plan has {len(found)} {stage} stage steps')
    return found[0]


# ---- step checks --------------------------------------------------------------------------------

def _problem(code, message):
    return f'{code}: {message}'


def receipt_problems(step, receipt):
    stage = stage_of(step)
    if type(receipt) is not dict or receipt.get('kind') != 'ml-stage-receipt' or receipt.get('stage') != stage:
        return [_problem('ml_stage_receipt_invalid', f"step {step['id']} has no {stage} stage receipt")]
    if receipt.get('operation') != step.get('operation'):
        return [_problem('ml_stage_receipt_invalid', f"the receipt names {receipt.get('operation')}, the step "
                                                     f"{step.get('operation')}")]
    if receipt.get('status') != 'completed':
        code = (receipt.get('codes') or [f"ml_stage_{receipt.get('status')}"])[0]
        return [_problem(code, f"{stage} stage {receipt.get('status')}: {receipt.get('reason') or 'no reason given'}")]
    if receipt.get('placeholders'):
        return [_problem('ml_output_missing', f"{stage} stage left placeholders: {receipt['placeholders']}")]
    if type(receipt.get('outputs')) is not dict:
        return [_problem('ml_stage_receipt_invalid', 'the receipt has no output digest mapping')]
    return []


def stage_problems(step, record):
    """The stage record beside the receipt agrees with it (a second, independent reading)."""
    stage = stage_of(step)
    if type(record) is not dict or record.get('status') != 'completed':
        status = record.get('status') if type(record) is dict else None
        return [_problem('ml_stage_record_invalid', f'the {stage} record says {status}')]
    if stage == 'train':
        if record.get('mode') != ('smoke' if is_smoke(step) else 'full'):
            return [_problem('ml_stage_record_invalid', 'the training record is not the rung this step runs')]
        if 'test' in (record.get('inputs') or {}):
            return [_problem('ml_withheld_partition_in_training', 'the training record lists the withheld partition')]
    if stage == 'evaluate' and record.get('test_reads') != 1:
        return [_problem('ml_test_once_violated', 'the evaluation records other than one withheld read')]
    if stage == 'review' and record.get('passed') is not True:
        return [_problem('ml_review_failed', 'the executable reviewer items did not pass')]
    return []


def admit(step, context):
    """Reserve all populations before the first training read; spend test only after model freeze."""
    from .modes import unresolved_placeholders
    if stage_of(step) is None:
        return []
    if step not in context['plan'].get('steps', []):
        return [_gate_error('mode_step_not_in_plan', 'the stage differs from the current plan')]
    errors = [_gate_error(e['code'], e.get('detail') or e['code'])
              for e in rules.staged_errors(step, context['plan'])] if stage_of(step) else []
    if unresolved_placeholders(step):
        errors.append(_gate_error('mode_unresolved_placeholder', 'the stage has unresolved parameters'))
    if stage_of(step):
        errors += prerequisite_errors(step, context)
    if errors or stage_of(step) not in ('train', 'evaluate'):
        return errors
    store, run_dir, plan = context['store'], context['run_dir'], context['plan']
    try:
        spec_sha, identities = _identities(store, run_dir, plan)
        if stage_of(step) == 'train':
            study = _study(store, spec_sha, identities, create=True)
            author = next(r for r in step['inputs'] if str(r['artifact']).endswith(':' + SPEC_OUTPUT))
            sid, path = author['artifact'].split(':', 1)
            document, target, custody = adopted_json(store, run_dir, sid, path)
            frozen = {'kind': 'ml-population-freeze', 'spec_sha256': spec_sha,
                      'selection': {'primary_arm': document['primary_arm'], 'arms': document['arms'],
                                    'seeds': document['seeds']},
                      'specification': {'path': str(target), 'sha256': custody['sha256']}}
            freeze_path = store.path('ml', 'population-freeze-' + spec_sha + '.json')
            freeze_path.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps(frozen, sort_keys=True, allow_nan=False).encode()
            if freeze_path.exists():
                if freeze_path.is_symlink() or freeze_path.read_bytes() != raw:
                    raise AdoptionMissing('the population freeze changed')
            else:
                import os
                descriptor = os.open(freeze_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(raw)
            freeze = {'path': str(freeze_path), 'sha256': hashlib.sha256(raw).hexdigest()}

            for name in ('train', 'validation'):
                _read_once(study, identities[name]['sha256'], 'train', freeze)
        else:
            errors += unblind_errors(step, context, spec_sha, identities)
            if not errors and not any(r.get('spec_sha256') == spec_sha and r.get('state') == 'spent'
                                      for r in records(store, EXPOSURE_RECORD)):
                errors.append(_gate_error('ml_test_once_violated', 'the evaluator has no charged withheld read'))
    except (AdoptionMissing, OSError, KeyError, TypeError, ValueError, StopIteration) as exc:
        errors.append(_gate_error('ml_population_unavailable', str(exc)[:400]))
    return errors


def prerequisite_errors(step, context):
    """Recheck accepted predecessor endings and every declared input at each stage boundary."""
    from .modes import ancestors
    plan, store, run_dir = context['plan'], context['store'], context['run_dir']
    index = custody_index(store)
    latest = {r['step_id']: r for r in records(store, STAGE_RECORD) if r.get('step_id')}
    above = ancestors(plan, step['id'])
    errors = []
    for prior in plan.get('steps') or ():
        if prior['id'] not in above or stage_of(prior) is None:
            continue
        accepted = latest.get(prior['id']) or {}
        try:
            receipt, _, custody = adopted_json(store, run_dir, prior['id'], RECEIPT, index=index)
            record, _, _ = adopted_json(store, run_dir, prior['id'], RECORDS[stage_of(prior)], index=index)
            if (not accepted.get('accepted') or accepted.get('status') != 'completed'
                    or accepted.get('plan_sha256') != plan.get('sha256')
                    or accepted.get('receipt_sha256') != custody['sha256']
                    or receipt_problems(prior, receipt) or stage_problems(prior, record)):
                raise AdoptionMissing('the predecessor has no current completed stage acceptance')
        except (AdoptionMissing, OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(_gate_error('ml_stage_prerequisite_incomplete', f"{prior['id']}: {exc}"))
    for item in step.get('inputs') or ():
        try:
            source, path = item['artifact'].split(':', 1)
            if source not in above:
                raise AdoptionMissing('input is not from a declared predecessor')
            adopted(store, run_dir, source, path, index=index)
        except (AdoptionMissing, OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(_gate_error('ml_stage_input_custody_missing', str(exc)[:400]))
    if stage_of(step) in ('train', 'evaluate') and not errors:
        try:
            errors += prerequisite_problems(specification(store, run_dir, plan, index=index))
        except (AdoptionMissing, OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(_gate_error('ml_prepare_incomplete', str(exc)[:400]))
    return errors


def authority_service():
    from ... import authority
    return authority


def unblind_errors(step, context, spec_sha, identities):
    """The parent requests and verifies this exact withheld read; a smoke GO never substitutes."""
    store, plan = context['store'], context['plan']
    service = authority_service()
    try:
        train = _one(plan, 'train', smoke=False)
        _, _, freeze = adopted(store, context['run_dir'], train['id'], RECORDS['train'])
        pins = {'plan_sha256': plan['sha256'], 'step': step['id'], 'operation': step['operation'],
                'ml_spec_sha256': spec_sha, 'ml_test_sha256': identities['test']['sha256'],
                'ml_training_sha256': freeze['sha256']}
        for name in ('pins', 'scope_pins'):
            scope = context.get(name, {})
            if type(scope) is not dict or any(k in pins and pins[k] != v for k, v in scope.items()):
                raise ValueError('unblind authority conflicts with context scope pins')
            pins.update(scope)
        record = service.current(store, 'r3_action', pins)
        if record is None:
            from ...authority import retained
            reading = {'request_pins': {}, 'inferred_critical_facts': [], 'flags': [],
                       **deepcopy(context.get('reading') or {})}
            reading['flags'] = list(reading['flags']) + [{'kind': 'risk', 'text': 'one irreversible withheld read'}]
            view = {'run_id': store.run_id, 'pins': pins, 'sections': [
                {'id': 'preamble', 'title': 'Evaluation authority',
                 'lines': ['The completed training is frozen. The next stage reads the withheld partition once.']},
                {'id': 'action', 'title': 'Withheld evaluation read',
                 'lines': [f"Evaluate {step['id']} with the frozen training and withheld population pinned here."]}],
                'items': retained.view_items(plan, reading), 'flags': reading['flags'],
                'options': [{'id': 'unblind', 'text': 'authorize this one evaluation read', 'effect': True},
                            {'id': 'hold', 'text': 'keep the withheld population closed', 'effect': False}]}
            retained.capture(store, 'r3_action', plan=plan, reading=reading, view=view)
            from ...authority.operator import BUDGET_KEYS
            reserved = {key: value for key, value in (step.get('budget') or {}).items()
                        if key in BUDGET_KEYS and value is not None}
            record = service.request(store, 'r3_action',
                                     {'view': view, 'gate': 'unblind', 'conservative_default': 'hold'},
                                     {'rung': step.get('rung'), 'budget': reserved})
        if not record or not record.get('id') or 'pending' in record:
            return [_gate_error('ml_unblind_authority_missing', 'the exact withheld read awaits authority')]
        verified = service.verify(store, record['id'], kind='r3_action', subject=pins)
        if (not verified or (verified.get('subject') or {}).get('gate') != 'unblind'):
            raise ValueError('the action is not an unblind authorization')
    except Exception as exc:
        return [_gate_error('ml_unblind_authority_missing', str(exc)[:400])]
    return []


def step(step, outcome, context):
    """Problems with a completed stage step (empty when it may count as completed)."""
    stage = stage_of(step)
    if stage is None:
        return []
    store, run_dir, plan = context['store'], Path(context['run_dir']), context.get('plan') or {}
    index = custody_index(store)
    try:
        receipt, _, receipt_custody = adopted_json(store, run_dir, step['id'], RECEIPT, index=index)
        problems = receipt_problems(step, receipt)
        declared = {o['path'] for o in step.get('outputs') or () if o['path'] != RECEIPT}
        if not problems and set(receipt.get('outputs') or {}) != declared:
            problems.append(_problem('ml_stage_receipt_invalid', 'the receipt does not bind every declared output'))
        for path, digest in (receipt.get('outputs') or {}).items() if not problems else ():
            _, _, output_custody = adopted(store, run_dir, step['id'], path, index=index)
            if output_custody['sha256'] != digest:
                problems.append(_problem('ml_stage_output_changed', path))
        record = None
        if not problems:
            record, _, _ = adopted_json(store, run_dir, step['id'], RECORDS[stage], index=index)
            problems = stage_problems(step, record)
    except (AdoptionMissing, OSError, ValueError) as exc:
        receipt, receipt_custody, record = None, None, None
        problems = [_problem('ml_stage_receipt_missing', str(exc)[:500])]
    if outcome.get('status') != 'completed':
        problems.append(_problem('ml_step_incomplete', 'the governed step did not complete'))
    if not problems and stage == 'train' and not is_smoke(step):
        problems = spend_withheld(store, run_dir, plan, step, index=index)
    if not problems and stage == 'evaluate':
        problems = close_exposure(store, run_dir, plan, step, index=index)
    store.append(STAGE_RECORD, {'schema_version': 1, 'step_id': step['id'], 'plan_sha256': plan.get('sha256'), 'stage': stage,
                                'smoke': is_smoke(step) if stage == 'train' else None,
                                'status': (receipt or {}).get('status') if type(receipt) is dict else None,
                                'codes': list((receipt or {}).get('codes') or []) if type(receipt) is dict else [],
                                'receipt_sha256': (receipt_custody or {}).get('sha256'),
                                'accepted': not problems, 'problems': list(problems)})
    return problems


# ---- the withheld population in the machine-wide exposure ledger --------------------------------

def _identities(store, run_dir, plan, *, index=None):
    """``(spec digest, {partition: identity})`` of the admitted partitions, from the adopted records."""
    import numpy as np
    from ravel.physics import ml_exposure
    admit = _one(plan, 'admit')
    admission, _, _ = adopted_json(store, run_dir, admit['id'], RECORDS['admit'], index=index)
    _, path, _ = adopted(store, run_dir, admit['id'], 'outputs/partitions/identities.npz', index=index)
    found = {}
    with np.load(path, allow_pickle=False) as arrays:
        for name in ('train', 'validation', 'test'):
            events = arrays[f'{name}__event_id'].astype(str).tolist()
            groups = arrays[f'{name}__group_id'].astype(str).tolist()
            found[name] = ml_exposure.manifest_identity({'event_ids': events, 'group_ids': groups},
                                                        admission['partitions'][name]['sha256'])
    if found['test']['sha256'] != admission['partitions']['test']['identity_sha256']:
        raise AdoptionMissing('the admitted withheld identities differ from the admission record')
    return admission['spec_sha256'], found


def _token(store, spec_sha):
    rows = [r for r in records(store, EXPOSURE_RECORD) if r.get('spec_sha256') == spec_sha]
    return rows[-1]['token'] if rows else None


def _study(store, spec_sha, identities, *, create):
    from ravel.physics import ml_exposure
    token = _token(store, spec_sha)
    if token is None and not create:
        return None
    study = ml_exposure.Study(spec_sha, token)
    schedule = {identities['train']['sha256']: ['train'], identities['validation']['sha256']: ['train'],
                identities['test']['sha256']: ['test']}
    if token is None:
        store.append(EXPOSURE_RECORD, {'schema_version': 1, 'spec_sha256': spec_sha, 'token': study.token,
                                       'state': 'claiming', 'test_sha256': identities['test']['sha256']})
    study.claim_all([(identities['train'], 'train_split'), (identities['validation'], 'validation_split'),
                     (identities['test'], 'test_split')], schedule=schedule)
    return study


def _owned(token):
    """The ledger records this study's token claimed."""
    from ravel.physics import ml_exposure
    root = ml_exposure.root()
    found = []
    for path in sorted(root.glob('*.json')) if root.is_dir() else ():
        record = ml_exposure._load(path)
        if type(record) is dict and record.get('token') == token and 'identity' in record:
            found.append(record)
    return found


def _resumed(spec_sha, token):
    """A study object holding exactly the claims its token made (no new claim)."""
    from ravel.physics import ml_exposure
    study = ml_exposure.Study(spec_sha, token)
    study.claims = {record['sha256']: record['identity'] for record in _owned(token)}
    return study


def _read_once(study, sha, context, freeze):
    from ravel.physics import ml_exposure
    record = ml_exposure._load(ml_exposure._record_path(sha)) or {}
    if any(r.get('context') == context for r in record.get('reads') or ()) and record.get('token') == study.token:
        return
    study.read(sha, context, freeze)


def spend_withheld(store, run_dir, plan, step, *, index=None):
    """Claim train, validation and the withheld partition, then spend the withheld one, before evaluation."""
    try:
        spec_sha, identities = _identities(store, run_dir, plan, index=index)
        _, path, record = adopted(store, run_dir, step['id'], RECORDS['train'], index=index)
        freeze = {'path': str(path), 'sha256': record['sha256']}
        if any(r.get('spec_sha256') == spec_sha and r.get('test_sha256') == identities['test']['sha256']
               and r.get('state') in ('spent', 'complete') and r.get('freeze', freeze) == freeze
               for r in records(store, EXPOSURE_RECORD)):
            return []  # a replayed check: this study already spent it for these frozen models
        study = _study(store, spec_sha, identities, create=True)
        for name in ('train', 'validation'):
            _read_once(study, identities[name]['sha256'], 'train', freeze)
        _read_once(study, identities['test']['sha256'], 'test', freeze)
    except (AdoptionMissing, OSError, KeyError, TypeError, ValueError) as exc:
        return [_problem('ml_withheld_population_spent', f'the withheld population cannot be claimed and spent '
                                                         f'for this study: {str(exc)[:400]}')]
    store.append(EXPOSURE_RECORD, {'schema_version': 1, 'spec_sha256': spec_sha, 'token': study.token, 'state': 'spent',
                                   'test_sha256': identities['test']['sha256'], 'freeze': freeze, 'step_id': step['id']})
    return []


def close_exposure(store, run_dir, plan, step, *, index=None):
    """The completed evaluation closes the study's claim with its record as the receipt."""
    try:
        spec_sha, identities = _identities(store, run_dir, plan, index=index)
        evaluation, path, record = adopted_json(store, run_dir, step['id'], RECORDS['evaluate'], index=index)
        if evaluation.get('test_identity_sha256') != identities['test']['sha256']:
            return [_problem('ml_withheld_population_changed', 'the evaluation read another population than the '
                                                               'spent withheld partition')]
        spent = [r for r in records(store, EXPOSURE_RECORD) if r.get('spec_sha256') == spec_sha and r.get('state') == 'spent']
        if not spent:
            return [_problem('ml_test_once_violated', 'the withheld partition was read before it was spent')]
        study = _resumed(spec_sha, spent[-1]['token'])
        if identities['test']['sha256'] not in study.claims:
            return [_problem('ml_exposure_unclosed', 'the spent withheld claim is not in the exposure ledger')]
        study.close('complete', {'path': str(path), 'sha256': record['sha256']})
    except (AdoptionMissing, OSError, KeyError, TypeError, ValueError) as exc:
        return [_problem('ml_exposure_unclosed', str(exc)[:500])]
    store.append(EXPOSURE_RECORD, {'schema_version': 1, 'spec_sha256': spec_sha, 'token': study.token,
                                   'state': 'complete', 'test_sha256': identities['test']['sha256'],
                                   'receipt': {'path': str(path), 'sha256': record['sha256']}})
    return []


def withheld_conflicts(identity, token=None):
    """Prior ledger records that make this withheld population unusable (read-only)."""
    from ravel.physics import ml_exposure
    found = []
    root = ml_exposure.root()
    for path in sorted(root.glob('*.json')) if root.is_dir() else ():
        prior = ml_exposure._load(path)
        if type(prior) is not dict or 'identity' not in prior or prior.get('token') == token:
            continue
        if ml_exposure.overlaps(identity, prior['identity']) and (prior.get('reads') or prior.get('state') == 'claimed'):
            found.append({'sha256': prior.get('sha256'), 'state': prior.get('state'), 'reads': len(prior.get('reads') or ()),
                          'roles': prior.get('roles')})
    return found


# ---- gates ------------------------------------------------------------------------------------------

def _gate_error(code, message, fix=''):
    return {'code': code, 'message': message, 'fix': fix}


def prerequisite_problems(spec):
    """Training prerequisites on this host for a validated specification (backends, accelerator)."""
    from ravel.physics import ml_backends
    available = ml_backends.available()
    found = []
    for arm in spec.get('arms') or ():
        if arm.get('kind') == 'trained' and not available.get(arm.get('backend')):
            found.append(_gate_error('ml_backend_unavailable', f"arm {arm['id']} trains with {arm.get('backend')}, which "
                                     'is not installed', 'install the backend or revise the arms'))
    device = spec.get('device', 'cpu')
    if device != 'cpu':
        try:
            import torch
            visible = bool(torch.cuda.is_available())
        except ImportError:
            visible = False
        if not visible:
            found.append(_gate_error('ml_device_unavailable', f'{device} is not visible on this host',
                                     'run on a host with the accelerator or declare device cpu'))
    return found


def specification(store, run_dir, plan, *, index=None):
    """The validated staged specification the admission step read (from its producer's adopted output)."""
    from ravel.workflow import ml_stages
    admit = _one(plan, 'admit')
    refs = [i['artifact'] for i in admit.get('inputs') or () if str(i.get('artifact', '')).endswith(':' + SPEC_OUTPUT)]
    if len(refs) != 1:
        raise AdoptionMissing('the admission names no single specification input')
    spec, _, _ = adopted_json(store, run_dir, refs[0].split(':', 1)[0], SPEC_OUTPUT, index=index)
    try:
        return ml_stages.validate_spec(spec)
    except ml_stages.StageRefused as exc:
        raise AdoptionMissing(f'{exc.code}: {exc.detail}') from None


def gate(transition, context):
    plan = context.get('plan') or {}
    errors = [_gate_error(e['code'], e.get('detail') or e['code']) for e in rules.staged_plan_errors(plan)]
    store, run_dir = context['store'], Path(context['run_dir'])
    if transition.startswith('checkin1->'):
        try:
            errors += prerequisite_problems(specification(store, run_dir, plan))
            spec_sha, identities = _identities(store, run_dir, plan)
            conflicts = withheld_conflicts(identities['test'], _token(store, spec_sha))
            if conflicts:
                errors.append(_gate_error('ml_withheld_population_spent', 'the admitted withheld population was already '
                                          f'claimed or read by another study ({len(conflicts)} ledger records)',
                                          'supply a fresh withheld population; a read test set is never reused'))
        except (AdoptionMissing, OSError, KeyError, TypeError, ValueError) as exc:
            errors.append(_gate_error('ml_prepare_incomplete', f'the prepared stages are not complete: {str(exc)[:400]}',
                                      'complete the admission and the feature definition'))
    if transition.startswith('checkin3->'):
        latest = {r['step_id']: r for r in records(store, STAGE_RECORD)}
        accepted = {r['step_id'] for r in latest.values() if r.get('accepted') and r.get('stage') == 'review'
                    and r.get('plan_sha256') == plan.get('sha256')}
        if not any(s['id'] in accepted for s in stage_steps(plan, 'review')):
            errors.append(_gate_error('ml_review_failed', 'the executable reviewer items have not passed'))
    return errors


# ---- check-in views -----------------------------------------------------------------------------

# The controller asks with the authority kind of each check-in point; the check-in names are aliases.
CHECKIN_KINDS = {'approve_plan': 'checkin1', 'go': 'checkin2', 'final': 'checkin3',
                 'checkin1': 'checkin1', 'checkin2': 'checkin2', 'checkin3': 'checkin3'}


def checkin(kind, context):
    """The route part of a check-in view: ``items`` and ``pins`` the controller merges, a risk flag when the
    stage evidence is unavailable (the gate, not the view, refuses), and the structured view itself."""
    view, pins = _checkin_view(CHECKIN_KINDS.get(kind), context)
    if not view:
        return {}
    if 'unavailable' in view:
        return {'ml_training': view, 'items': {}, 'pins': {},
                'flags': [{'kind': 'risk', 'text': f"ML stage evidence unavailable: {view['unavailable']}"}]}
    rows = [f'{key}: {json.dumps(value, sort_keys=True, allow_nan=False)}' for key, value in sorted(view.items())]
    return {'ml_training': view, 'items': {'ml_training': rows}, 'pins': pins, 'flags': []}


def _checkin_view(kind, context):
    store, run_dir, plan = context['store'], Path(context['run_dir']), context.get('plan') or {}
    index = custody_index(store)
    view, pins = {}, {}
    try:
        if kind == 'checkin1':
            admission, _, admitted = adopted_json(store, run_dir, _one(plan, 'admit')['id'], RECORDS['admit'],
                                                  index=index)
            features, _, defined = adopted_json(store, run_dir, _one(plan, 'features')['id'], RECORDS['features'],
                                                index=index)
            pins = {'ml_admission_sha256': admitted['sha256'], 'ml_features_sha256': defined['sha256']}
            leakage = features['items'][0]
            view = {'dataset': admission['source'], 'split': admission['split'],
                    'partitions': {p: {k: admission['partitions'][p][k] for k in ('rows', 'signal', 'background')}
                                   for p in admission['partitions']},
                    'admission_items': {r['id']: r['verdict'] for r in admission['items']},
                    'features': features['features'], 'leakage': {'verdict': leakage['verdict'],
                                                                 'declared': leakage['evidence'].get('declared')}}
        elif kind == 'checkin2':
            smoke = _one(plan, 'train', smoke=True)
            training, _, _ = adopted_json(store, run_dir, smoke['id'], RECORDS['train'], index=index)
            view = {'smoke': {'status': training['status'], 'wall_seconds': training['wall_seconds'],
                              'replicates': [{k: r.get(k) for k in ('key', 'status', 'train_auc', 'validation_auc')}
                                             for r in training['replicates']]},
                    'full_training': {s['id']: s.get('budget') for s in stage_steps(plan, 'train', smoke=False)}}
        elif kind == 'checkin3':
            evaluation, _, _ = adopted_json(store, run_dir, _one(plan, 'evaluate')['id'], RECORDS['evaluate'], index=index)
            review, _, _ = adopted_json(store, run_dir, _one(plan, 'review')['id'], RECORDS['review'], index=index)
            view = {'primary_arm': evaluation['primary_arm'], 'summary': evaluation['summary'],
                    'overtraining': evaluation['overtraining']['verdict'],
                    'review': {'passed': review['passed'], 'failing': review['failing']}}
    except (AdoptionMissing, OSError, KeyError, TypeError, ValueError, IndexError) as exc:
        view, pins = {'unavailable': str(exc)[:300]}, {}
    return view, pins


# ---- the bounded ending -------------------------------------------------------------------------

def ending(reason, context):
    """Record each stage's state and close a spent, unevaluated withheld population as failed."""
    store, plan = context['store'], context.get('plan') or {}
    latest = {}
    for row in records(store, STAGE_RECORD):
        latest[row['step_id']] = row
    stages = []
    for row in (plan.get('steps') or ()):
        if stage_of(row) is None:
            continue
        found = latest.get(row['id'])
        if found is not None and found.get('plan_sha256') != plan.get('sha256'):
            found = None
        stages.append({'step_id': row['id'], 'stage': stage_of(row),
                       'state': 'not_run' if found is None else ('completed' if found.get('accepted') else 'refused'),
                       'status': (found or {}).get('status'), 'codes': (found or {}).get('codes') or [],
                       'problems': (found or {}).get('problems') or []})
    exposure = None
    rows = records(store, EXPOSURE_RECORD)
    if rows and rows[-1].get('state') in ('claiming', 'claimed', 'spent'):
        last = rows[-1]
        try:
            study = _resumed(last['spec_sha256'], last['token'])
            if study.claims:
                # A claim made or spent without a completed evaluation is closed failed: never reused.
                study.close('failed')
                exposure = 'closed_failed'
                store.append(EXPOSURE_RECORD, {'schema_version': 1, 'spec_sha256': last['spec_sha256'],
                                               'token': last['token'], 'state': 'failed',
                                               'test_sha256': last.get('test_sha256')})
            else:
                exposure = 'nothing_claimed'
        except (OSError, KeyError, TypeError, ValueError) as exc:
            exposure = f'unclosed: {str(exc)[:300]}'
    record = {'schema_version': 1, 'kind': 'ml-qualified-ending', 'reason': str(reason)[:2000], 'stages': stages,
              'completed': [s['step_id'] for s in stages if s['state'] == 'completed'],
              'unfinished': [s['step_id'] for s in stages if s['state'] != 'completed'],
              'exposure': exposure, 'accepted_label': False}
    store.append(ENDING_RECORD, record)
    return deepcopy(record)


def delivery_errors_from_store(store, plan):
    """Universal sink check, also for typed training stages in a judgment-planned branch."""
    latest = {row['step_id']: row for row in records(store, STAGE_RECORD) if row.get('step_id')}
    found = []
    for step in plan.get('steps') or ():
        stage = rules.stage_of(step)
        if stage is None:
            continue
        record = latest.get(step['id']) or {}
        if (not record.get('accepted') or record.get('status') != 'completed'
                or record.get('plan_sha256') != plan.get('sha256')):
            found.append({'code': 'ml_stage_unreceipted', 'step': step['id'], 'stage': stage})
    return found
