"""Code-derived research preregistration at CHECK-IN 1 and bind-on-resume migration.

Approving CHECK-IN 1 writes the run's preregistration. Every field is derived in
code from the approved plan files; no model or host authors it. Launch admission
re-derives the record and refuses any difference. An existing run that predates
the protocol binds on resume with a recorded, machine-applied migration receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path

from . import state_io

PRODUCER = 'ravel.workflow.research_launch'
MIGRATION = 'research/migration.json'
EVALUATOR_DIR = 'research/evaluators'
PLAIN_MODES = ('reproduce', 'reinterpret')
# Record fields that state when the record was written, not what the plan says;
# launch verifies them against the protocol history and the custody ledger.
PROVENANCE_KEYS = ('supersedes', 'superseded_after_execution', 'post_hoc', 'execution_pins')
EXECUTION_RECORDS = ('execution_state.json', 'execution_attempt.json', 'run_state.json')
# Evaluator roles are fixed by the protocol; their applicability follows the
# approved statistic and detector route, never a model's claim.
EVALUATORS = {
    'limit_setter': ('physics/pyhf_exclude.py', {'published-likelihood', 'simplified-likelihood', 'constructed-likelihood', 'best-sr-counting',
                                                 'combined-counting', 'provided-likelihood', 'sensitivity-expected-only'}),
    'likelihood_builder': ('physics/sa2json_native.py', {'published-likelihood', 'simplified-likelihood',
                                                         'provided-likelihood'}),
    'cutflow_comparator': ('validation/certify_acceptance.py', None),
}
SEED_KEYS = ('seed', 'seeds', 'iseed')


def _package():
    return Path(__file__).parents[1]


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _contract(root):
    from .research_admission import run_contract
    return run_contract(root)


def required(root):
    """The same typed trigger as admission: contract, request plan or an existing binding."""
    from . import research_protocol as p
    root = Path(root)
    contract = _contract(root)
    plan = p._method_json(contract['request_plan'], root) if contract.get('request_plan') else {}
    return bool(p.required_for([contract, plan]) or contract.get('research_protocol_required')
                or (root/'research/binding.json').exists())


def _science(root):
    return (Path(root)/'inputs/science-plan.json').exists()


def approved_plan_paths(root):
    """The exact plan files the CHECK-IN 1 approval fingerprints, in its own order."""
    root = Path(root)
    if _science(root):
        from . import science
        paths = [*science.approval_input_paths(root), root/science.PLAN]
    else:
        from . import workflow_state
        paths = workflow_state.approval_input_paths(str(root))
    return [Path(path) for path in dict.fromkeys(str(path) for path in paths) if Path(path).is_file()]


def verify_approved(root):
    """A recorded, current CHECK-IN 1 approval is the only authority for this producer."""
    root = Path(root)
    if _science(root):
        from . import science, execution
        path = root/science.APPROVAL
        if not path.is_file():
            raise ValueError('CHECK-IN 1 approval required before preregistration')
        receipt = state_io.read_json(path)
        # Both digests are required: an approval receipt without them approves nothing.
        if (receipt.get('plan_sha256') != execution.file_hash(root/science.PLAN)
                or receipt.get('input_fingerprint')
                != science._approval_fingerprint(science.approval_input_paths(root))):
            raise ValueError('approved science plan changed after CHECK-IN 1, or its approval has no plan digests')
        return
    from . import workflow_state
    if not (root/'inputs/checkin1_approval.json').is_file():
        raise ValueError('CHECK-IN 1 approval required before preregistration')
    errors = workflow_state.verify_approval(str(root))
    if errors:
        raise ValueError('CHECK-IN 1 approval is not current: ' + '; '.join(errors))


def _rel(root, path):
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return str(path)


def _declared_seeds(root, contract):
    found = {}
    sources = {'inputs/task_contract.json': contract}
    for rel in ('inputs/checkin1.json', 'inputs/science-plan.json'):
        if (Path(root)/rel).is_file():
            try:
                sources[rel] = state_io.read_json(Path(root)/rel)
            except (OSError, ValueError):
                continue
    for rel, value in sources.items():
        if isinstance(value, dict):
            for key in SEED_KEYS:
                if key in value:
                    found[rel + '#' + key] = value[key]
    return found


def _evaluators(contract):
    stat_mode = contract.get('stat_mode')
    detector = contract.get('detector_mode')
    mode = contract.get('task_mode', contract.get('task_kind'))
    pins, omitted = {}, {}
    for name, (source, modes) in EVALUATORS.items():
        if name == 'cutflow_comparator':
            applicable = mode in PLAIN_MODES and detector not in (None, 'none', 'parton-level')
            reason = f'task_mode={mode} with detector_mode={detector} has no per-run acceptance certification'
        else:
            applicable = stat_mode in modes
            reason = f'stat_mode={stat_mode} does not use the {name.replace("_", " ")}'
        if applicable:
            raw = (_package()/source).read_bytes()
            sha = _sha(raw)
            pins[name] = {'path': f'{EVALUATOR_DIR}/{name}-{sha[:16]}.py', 'sha256': sha,
                          'source': 'src/ravel/' + source}
        else:
            omitted[name] = reason
    return pins, omitted


def derive(root):
    """Pure derivation from the approved plan files; writes nothing."""
    from . import research_protocol as p
    root = Path(root)
    contract = _contract(root)
    plan_files = [{'path': _rel(root, path), 'sha256': _sha(path.read_bytes())}
                  for path in approved_plan_paths(root)]
    mode = contract.get('task_mode', contract.get('task_kind'))
    obligations = (contract.get('task_requirements') or {}).get('obligations') or []
    claims = ([{'id': row['id'], 'criteria': row.get('criteria')} for row in obligations if isinstance(row, dict)]
              or [{'id': 'original-task', 'source': 'inputs/task_contract.json'}])
    applicability = p.route_applicability(root)
    pins, omitted = _evaluators(contract)
    selection = contract.get('selection')
    seeds = _declared_seeds(root, contract)
    return {
        'schema_version': 1, 'kind': 'research-preregistration', 'producer': PRODUCER,
        'authority': 'code_derived_from_approved_checkin1_plan',
        'route': applicability['route'], 'task_mode': mode,
        'plan_digest': _sha(_canonical(plan_files)), 'plan_files': plan_files,
        'claims': claims,
        'comparators': {'targets': contract.get('targets'), 'published_reference': mode in PLAIN_MODES},
        'approximations': list(contract.get('assumptions') or []),
        'expected_effect': {'statement': f'{mode} result compared with the approved comparators; '
                                         'no effect is asserted before execution.', 'claims': [c['id'] for c in claims]},
        'stages': applicability['stages'], 'protocols': applicability['protocols'],
        'selection_policy': selection if selection else {
            'kind': 'none', 'reason': 'the approved plan declares no candidate selection'},
        'seed_policy': {'declared': seeds, 'policy': 'fixed as approved' if seeds else
                        'no seed declared in the approved plan; each stage receipt records its seed'},
        'evaluator_pins': pins, 'evaluator_not_applicable': omitted,
    }


def _stage_consumed(status):
    return any(row['status'] == 'done' for row in status['record']['stages'])


def _launched(root):
    root = Path(root)
    if (root/'execution_state.json').exists() or (root/'execution_attempt.json').exists():
        return True
    try:
        return bool(state_io.read_json(root/'run_state.json').get('compute_launched'))
    except (OSError, ValueError):
        return False


def has_results(root):
    """Execution records or a CHECK-IN 2 record exist: results may have been seen."""
    return _launched(root) or past_checkin2(root)


def _execution_pins(root):
    root = Path(root)
    rels = (*EXECUTION_RECORDS, 'inputs/checkin2.json', 'inputs/checkin2_go.json')
    return [{'path': rel, 'sha256': _sha((root/rel).read_bytes())} for rel in rels if (root/rel).is_file()]


def _mark_inapplicable(root, record, stages):
    from . import research_protocol as p
    changed = False
    for row in record['stages']:
        computed = stages[row['id']]
        if not computed['applicable'] and row['status'] == 'pending':
            row.update(status='not_applicable', reason=computed['reason'], applicability='computed')
            changed = True
        elif computed['applicable'] and row.get('applicability') == 'computed':
            row.update(status='pending', reason=None)
            row.pop('applicability')
            changed = True
    if changed:
        state_io.atomic_json(p._method_path(root), record)


def _plan_part(value):
    return {k: v for k, v in value.items() if k not in PROVENANCE_KEYS}


def _write_record(root, derived):
    for name, pin in derived['evaluator_pins'].items():
        target = root/pin['path']
        raw = (_package()/pin['source'].removeprefix('src/ravel/')).read_bytes()
        if _sha(raw) != pin['sha256']:
            raise ValueError('evaluator source changed during preregistration: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(raw)
    raw = _canonical(derived)
    path = root/'research'/f'preregistration-{_sha(raw)[:16]}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {'path': _rel(root, path), 'sha256': _sha(raw)}


def _publish(root, derived, *, evaluation_harness=False):
    """Write a new record, then switch the protocol pin to it in one atomic write.

    A record written after execution is ``post_hoc`` and pins the execution
    records; a record that replaces another names it and the execution state.
    """
    from . import research_protocol as p
    status = p.methodology_status(root)
    existing = status['record']['preregistration']
    if existing is not None:
        if _plan_part(p._method_json(existing, root)) == derived:
            return status
        # A new approval may revise the plan for later attempts. Earlier attempts
        # stay under the record they ran with; completed research stages consumed
        # that record and cannot be re-scored under a new one.
        if _stage_consumed(status):
            raise ValueError('a completed research stage used the current preregistration; it cannot be replaced')
        derived['supersedes'] = existing
        derived['superseded_after_execution'] = has_results(root)
    elif has_results(root):
        derived['post_hoc'] = True
        derived['execution_pins'] = _execution_pins(root)
    pin = _write_record(root, derived)
    if 'stages' in derived and not (root/'head.json').exists():
        _mark_inapplicable(root, p.methodology_status(root)['record'], derived['stages'])
    pins = {name: {'path': e['path'], 'sha256': e['sha256']} for name, e in derived['evaluator_pins'].items()}
    return p.preregister(root, pin, pins, supersedes=existing, evaluation_harness=evaluation_harness)


def produce(root):
    """Write the preregistration for an approved plan; idempotent for the same plan."""
    root = Path(root)
    if (root/'head.json').exists():
        raise ValueError('research campaigns preregister with produce_campaign and their design record')
    verify_approved(root)
    return _publish(root, derive(root))


def produce_if_required(root):
    return produce(root) if required(root) else None


DESIGN_KEYS = ('selection_rule', 'stop_rule', 'approximations')
DESIGN_OPTIONAL = ('withheld_cells', 'sizing')


def derive_campaign(root, design):
    """Pure derivation for a campaign from its journal contract and pinned design record.

    The design record carries only the prospective design choices (selection and
    stop rules, approximations, withheld cells, sizing). Everything else, including
    the producer identity, claims, evaluator pins and applicability, is code.
    """
    from . import research_protocol as p, research_cycle as cycle
    root = Path(root)
    _, state = cycle._load(root)
    contract = state['contract']
    original = (cycle._read(contract['goal_binding']['contract'], state['base_dir'])
                if 'goal_binding' in contract else contract)
    value = p._method_json(design, root)
    if type(value) is not dict or not set(DESIGN_KEYS) <= set(value) or set(value) - {*DESIGN_KEYS, *DESIGN_OPTIONAL}:
        raise ValueError('campaign design record needs exactly selection_rule, stop_rule, approximations '
                         'and optional withheld_cells and sizing')
    if not isinstance(value['approximations'], list):
        raise ValueError('campaign design approximations must be a list')
    obligations = (original.get('task_requirements') or {}).get('obligations') or []
    claims = ([{'id': row['id'], 'criteria': row.get('criteria')} for row in obligations if isinstance(row, dict)]
              or [{'id': contract['id'], 'question': contract['question']}])
    applicability = p.route_applicability(root)
    pins, omitted = _evaluators(original)
    return {
        'schema_version': 1, 'kind': 'research-preregistration', 'producer': PRODUCER,
        'authority': 'code_derived_from_campaign_contract_and_design',
        'route': applicability['route'], 'task_mode': original.get('task_mode', original.get('task_kind')),
        'campaign': {'id': contract['id'], 'contract_sha256': _sha(_canonical(contract))},
        'design': design, 'claims': claims,
        'approximations': value['approximations'],
        'expected_effect': {'statement': 'campaign question answered under the prospective design; '
                                         'no effect is asserted before execution.', 'claims': [c['id'] for c in claims]},
        'selection_rule': value['selection_rule'], 'stop_rule': value['stop_rule'],
        **{k: value[k] for k in DESIGN_OPTIONAL if k in value},
        'stages': applicability['stages'], 'protocols': applicability['protocols'],
        'evaluator_pins': pins, 'evaluator_not_applicable': omitted,
    }


def produce_campaign(root, design):
    """Write a campaign's code-derived preregistration from its pinned design record."""
    root = Path(root)
    if not (root/'head.json').exists():
        raise ValueError('campaign journal required')
    return _publish(root, derive_campaign(root, design))


def verify(root):
    """Launch check: the recorded preregistration is this producer's derivation of the current plan.

    The supersession chain must match the protocol history and the custody
    ledger. A record written after execution never admits a research launch.
    """
    from . import research_protocol as p
    root = Path(root)
    try:
        status = p.methodology_status(root)
        record = status['record']
        if record['preregistration'] is None:
            return ['prospective research preregistration and evaluator pins required']
        value = p._method_json(record['preregistration'], root)
        campaign = (root/'head.json').exists()
        if record.get('preregistration_authority') == 'evaluation_harness':
            if campaign:
                return []
            return ['an evaluation-harness preregistration cannot admit an ordinary launch']
        if value.get('producer') != PRODUCER:
            return ['preregistration was not produced from the approved plan by ' + PRODUCER]
        derived = derive_campaign(root, value.get('design')) if campaign else derive(root)
        plan = _plan_part(value)
        if plan != derived:
            changed = sorted(k for k in set(plan) | set(derived) if plan.get(k) != derived.get(k))
            return ['preregistration differs from the approved plan: ' + ', '.join(changed)]
        errors = _chain_errors(root, record, value)
        search = p.route_applicability(root)['route'] == p.SEARCH_ROUTE
        if search and 'post_hoc_preregistration' in status['claim_cap']:
            errors.append('a preregistration written after execution cannot admit a research launch')
        if search and 'preregistration_timing_unverified' in status['claim_cap']:
            errors.append('preregistration timing is unverified; a research launch needs a custody-recorded record')
        return errors
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]


def _chain_errors(root, record, value):
    from . import research_protocol as p
    history = record.get('preregistration_history', [])
    previous = history[-1] if history else None
    errors = []
    if value.get('supersedes') != (previous['record'] if previous else None):
        errors.append('preregistration supersession differs from the protocol history')
    if previous and (previous['replaced_by'] != record['preregistration']
                     or value.get('superseded_after_execution') is not previous['superseded_after_execution']):
        errors.append('preregistration supersession flag differs from the protocol history')
    rows = [r for r in p.custody_rows(root) if r.get('event') == 'preregistered']
    if rows:
        chain = [h['record']['sha256'] for h in history] + [record['preregistration']['sha256']]
        if [r['sha256'] for r in rows] != chain:
            errors.append('preregistration history differs from its custody record')
        last = rows[-1]
        if (last['post_hoc'] is not bool(value.get('post_hoc'))
                or last['superseded_after_execution'] is not bool(value.get('superseded_after_execution'))):
            errors.append('preregistration timing flags differ from their custody record')
        for row, entry in zip(rows[1:], history):
            if row['superseded_after_execution'] is not entry['superseded_after_execution']:
                errors.append('preregistration history flag differs from its custody record')
    return errors


def existing_run(root):
    root = Path(root)
    return has_results(root) or any((root/rel).exists() for rel in (
        'inputs/checkin1_approval.json', 'inputs/science-approval.json'))


def past_checkin2(root):
    root = Path(root)
    return (root/'inputs/checkin2_go.json').exists() or (root/'inputs/checkin2.json').exists()


def migrate(root):
    """Bind the default protocol to an existing unbound run, with a recorded receipt.

    The receipt is staged first and pins the binding it will publish; the protocol
    record, the custody row and ``binding.json`` follow, binding last. An
    interrupted migration is rolled back on the next open and redone, so a bound
    run without its receipt cannot arise.
    """
    from . import research_protocol as p
    from .launch_authorization import operational_utc
    root = Path(root)
    if (root/'research/binding.json').exists() or not required(root):
        return None
    p.recover_binding(root)
    if not existing_run(root):
        return None
    contract = _contract(root)
    regime = 'open_exploratory'
    binding = p.binding_bytes(regime, 'migration')
    prior = _execution_pins(root) + [{'path': rel, 'sha256': _sha((root/rel).read_bytes())} for rel in (
        'inputs/checkin1_approval.json', 'inputs/science-approval.json', 'current_state.json') if (root/rel).is_file()]
    label = ('pre_protocol_capped' if past_checkin2(root) else
             'pre_protocol_executed' if _launched(root) else 'none_before_checkin2')
    import json as _json
    receipt = {'schema_version': 1, 'kind': 'research-protocol-migration',
               'old_binding': None,
               'new_binding': {'protocol': _json.loads(binding)['protocol'], 'regime': regime,
                               'binding': {'path': 'research/binding.json', 'sha256': _sha(binding)}},
               'epoch': {'agent_layer_epoch': contract.get('agent_layer_epoch', 1),
                         'protocol_version': p.default_protocol()['version']},
               'utc': operational_utc(), 'applied_by': 'machine',
               'authority': 'machine-applied migration on resume; not a human or physicist approval',
               'prior_results': {'label': label, 'pins': sorted(prior, key=lambda row: row['path'])}}
    raw = _canonical(receipt)
    (root/'research').mkdir(parents=True, exist_ok=True)
    (root/MIGRATION).write_bytes(raw)
    p.bind_default(root, regime=regime, origin='migration', migration={'path': MIGRATION, 'sha256': _sha(raw)})
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel research-preregister', description=__doc__)
    parser.add_argument('--rundir', required=True, type=Path)
    parser.add_argument('--check', action='store_true', help='verify the recorded preregistration only')
    args = parser.parse_args(argv)
    if args.check:
        errors = verify(args.rundir)
        print(json.dumps({'valid': not errors, 'errors': errors}, indent=2))
        return 1 if errors else 0
    try:
        migrate(args.rundir)
        status = produce(args.rundir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'ravel research-preregister: REFUSED -- {exc}', file=__import__('sys').stderr)
        return 1
    print(json.dumps({'preregistration': status['record']['preregistration'],
                      'evaluator_pins': status['record']['evaluator_pins'],
                      'execution_authorized': False}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
