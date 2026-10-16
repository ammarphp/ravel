"""Staged scientific protocols over the existing cycle, Graph and study journal.

Progress is derived from current ordinary evidence. This module has no worker,
call ledger, independent review journal, automatic assent or acceptance vote.
"""
from copy import deepcopy
from . import provider_transport
from pathlib import Path
from . import candidate_experiments as ce, state_io
from ravel.physics import research_comparison as comparison

_json = comparison.document

PURPOSES = {"baseline", "screen", "full", "confirm", "ablation", "objection_test"}
EXPOSURES = {"adaptive_screen", "adaptive_full", "withheld_confirmation"}
DECISIONS = {"better", "equivalent", "worse", "unknown"}


def instruction(key):
    import json
    value = json.loads((Path(__file__).parents[1] / 'data/research/instructions.json').read_text())
    if value.get('schema_version') != 1 or value.get('kind') != 'research-instructions':
        raise ValueError('research instruction data/v1 required')
    return value['texts'][key]


def default_protocol():
    """Load the packaged methodology; stage roles and instructions are data."""
    import json
    path = Path(__file__).parents[1] / 'data/research/protocol-default.json'
    value = json.loads(path.read_text())
    if value.get('schema_version') != 1 or value.get('kind') != 'research-protocol-definition':
        raise ValueError('research protocol definition/v1 required')
    return value


def required_for(value):
    """Use typed intake facts, never prompt keywords or task identities."""
    if isinstance(value, list):
        return any(required_for(item) for item in value)
    if not isinstance(value, dict):
        return False
    triggers = default_protocol()['binding_triggers']
    if any(value.get(key) in allowed for key, allowed in triggers.items() if isinstance(value.get(key), str)):
        return True
    return any(required_for(item) for item in value.values() if isinstance(item, (dict, list)))


def _method_path(root):
    return Path(root) / 'research/protocol.json'


# Binding origin and preregistration history are mirrored in the broker custody
# ledger, outside the run tree. Editing or deleting a run-file key cannot uncap a
# migrated run or relabel a post-hoc preregistration while the custody row exists.
CUSTODY = 'research-protocol'
CAPPED = ('pre_protocol_capped', 'pre_protocol_executed', 'binding_origin_unverified')


def _custody_path(root):
    """``$RAVEL_STATE_DIR/research-protocol/<run digest>.jsonl``, outside the run tree."""
    import hashlib, os
    run = Path(os.path.realpath(root))
    state = Path(os.path.realpath(os.environ.get('RAVEL_STATE_DIR') or str(Path.home() / '.local/state/ravel')))
    if state.is_relative_to(run) or run.is_relative_to(state):
        raise ValueError('research protocol custody must be outside the run tree')
    return state / CUSTODY / (hashlib.sha256(str(run).encode()).hexdigest() + '.jsonl')


def custody_rows(root):
    """Read the append-only hash chain; a changed chain fails closed."""
    import hashlib, json
    path = _custody_path(root)
    if not path.exists():
        return []
    rows, previous = [], None
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if set(row) != {'n', 'previous_sha256', 'record'} or row['n'] != len(rows) + 1 or row['previous_sha256'] != previous:
            raise ValueError('research protocol custody ledger chain changed')
        previous = hashlib.sha256(line.encode()).hexdigest()
        rows.append(row['record'])
    return rows


def custody_append(root, record):
    import hashlib, json, os
    path = _custody_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with state_io.file_lock(path.with_suffix('.lock')):
        lines = path.read_text().splitlines() if path.exists() else []
        custody_rows(root)
        row = {'n': len(lines) + 1, 'previous_sha256': hashlib.sha256(lines[-1].encode()).hexdigest() if lines else None,
               'record': deepcopy(record)}
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())


def binding_bytes(regime, origin):
    """The deterministic binding record; a migration receipt pins its digest before publication."""
    import hashlib, json
    definition_path = Path(__file__).parents[1] / 'data/research/protocol-default.json'
    record = {'schema_version': 1, 'kind': 'research-protocol-binding',
              'protocol': {'path': 'src/ravel/data/research/protocol-default.json',
                           'sha256': hashlib.sha256(definition_path.read_bytes()).hexdigest()},
              'regime': regime, 'origin': origin}
    return (json.dumps(record, indent=2, sort_keys=True) + '\n').encode()


def recover_binding(root):
    """Complete or roll back an interrupted publication; never invent a binding.

    ``binding.json`` is published last. A protocol record or staged migration
    receipt without it is an interrupted bind: with no stage progress it is rolled
    back so the next bind starts clean; with progress it is refused.
    """
    root = Path(root)
    if (root / 'research/binding.json').exists():
        return None
    protocol, receipt = _method_path(root), root / 'research/migration.json'
    if protocol.exists():
        value = state_io.read_json(protocol)
        if value.get('preregistration') is not None or any(
                row.get('status') == 'done' or row.get('worker_receipts') for row in value.get('stages', [])):
            raise ValueError('interrupted research binding has stage progress; restore the original binding')
        protocol.unlink()
        if receipt.exists():
            receipt.unlink()
        return 'rolled_back'
    if receipt.exists():
        receipt.unlink()
        return 'rolled_back'
    return None


def bind_default(root, *, regime='open_exploratory', origin='intake', migration=None):
    """Bind once, preserving the original stage population on every resume.

    Publication order is protocol record, custody row, then ``binding.json``. A
    crash before the last write leaves no binding, which ``recover_binding`` rolls
    back; a lone binding without its record is never produced by a crash.
    """
    definition = default_protocol()
    if regime not in definition['regimes']:
        raise ValueError('declared research regime required')
    if origin not in ('intake', 'migration') or (origin == 'migration') != (migration is not None):
        raise ValueError('binding origin intake, or migration with its receipt, required')
    root = Path(root)
    if _method_path(root).exists() and (root / 'research/binding.json').exists():
        value = methodology_status(root)['record']
        if value['regime'] != regime:
            raise ValueError('bound research regime cannot change on resume')
        return value
    binding = root / 'research/binding.json'
    if binding.exists():
        raise ValueError('bound research protocol is missing; restore the original record')
    if migration is None:
        # A migration stages its receipt after its own recovery; keep that receipt.
        recover_binding(root)
    import hashlib
    raw = binding_bytes(regime, origin)
    value = {'schema_version': 1, 'kind': 'research-protocol',
             'protocol': __import__('json').loads(raw)['protocol'],
             'regime': regime, 'preregistration': None, 'evaluator_pins': {},
             'mandatory_protocols': deepcopy(definition['mandatory_protocols']),
             'stages': [{**deepcopy(row), 'status': 'pending', 'reason': None,
                         'artifact': None, 'worker_receipts': {}} for row in definition['stages']]}
    if migration is not None:
        value['migration'] = migration
    state_io.atomic_json(_method_path(root), value)
    custody_append(root, {'event': 'bound', 'origin': origin, 'binding_sha256': hashlib.sha256(raw).hexdigest(),
                          'migration_sha256': None if migration is None else migration['sha256']})
    binding.parent.mkdir(parents=True, exist_ok=True)
    tmp = binding.with_name('.binding.json.tmp')
    tmp.write_bytes(raw)
    import os
    os.replace(tmp, binding)
    return value


def _method_pin(pin, base_dir):
    """Authenticate a contract PIN without inventing a size field."""
    import hashlib
    if (type(pin) is not dict or not {'path', 'sha256'} <= pin.keys()
            or not isinstance(pin['path'], str) or not isinstance(pin['sha256'], str)):
        raise ValueError('research artifact PIN required')
    path = Path(pin['path'])
    if not path.is_absolute():
        path = Path(base_dir) / path
    # The existing bounded, no-follow snapshot reader validates the exact bytes.
    actual = _cycle()._pin(path)
    if actual['sha256'] != pin['sha256'] or ('size' in pin and pin['size'] != actual['size']):
        raise ValueError('research artifact changed: ' + str(path))
    _, raw, _ = comparison._snapshot(actual, base_dir)
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('research artifact changed during read')
    return raw


def _method_json(pin, base_dir):
    import json
    return json.loads(_method_pin(pin, base_dir))


def _required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' requires a nonempty reason or statement')


def _rdj(row, minimum, base_dir):
    """Check the RDJ receipt binding interface; the RDJ module remains its authority."""
    receipt = _method_json(row.get('rdj_receipt'), base_dir)
    levels = ['R0', 'R1', 'R2', 'R3']
    action = {k: v for k, v in row.items() if k != 'rdj_receipt'}
    import hashlib, json
    digest = hashlib.sha256(json.dumps(action, sort_keys=True, separators=(',', ':'),
                                      ensure_ascii=False).encode()).hexdigest()
    if (receipt.get('schema_version') != 1 or receipt.get('kind') != 'rdj-receipt'
            or receipt.get('outcome') != 'authorize' or receipt.get('gate') != 'research_choice'
            or receipt.get('action_digest') != digest or receipt.get('class') not in levels
            or levels.index(receipt['class']) < levels.index(minimum)
            or receipt.get('open_a_findings') != 0 or receipt.get('unresolved_branches') != 0):
        raise ValueError('current ' + minimum + ' RDJ research_choice authorization required')
    case = _method_json(receipt.get('case'), base_dir)
    if receipt.get('case_sha256') != receipt['case']['sha256'] or case.get('schema_version') != 2:
        raise ValueError('RDJ receipt requires its pinned v2 case')
    return receipt


def validate_stage_artifact(stage_id, value, *, base_dir, regime):
    """Validate required outputs and evidence; never turn novelty into acceptance."""
    definitions = {row['id']: row for row in default_protocol()['stages']}
    if stage_id not in definitions or type(value) is not dict:
        raise ValueError('known research stage artifact required')
    if value.get('status') == 'not_applicable':
        _required_text(value.get('reason'), 'not_applicable stage')
        if not stage_inapplicable(stage_id, base_dir):
            raise ValueError('computed applicability does not permit not_applicable: ' + stage_id)
        return deepcopy(value)
    for key in definitions[stage_id]['required_outputs']:
        if key not in value:
            raise ValueError(stage_id + ' missing required artifact field: ' + key)
    pin = lambda p: _method_pin(p, base_dir)
    if stage_id == 'limitation_census':
        limitations = value['limitations']
        if not limitations:
            raise ValueError('limitation census requires actual limitations')
        for row in limitations:
            for key in ('id', 'subject', 'flaw', 'consequence', 'opportunity', 'testable_signature'):
                _required_text(row.get(key), 'limitation ' + key)
            if not row.get('evidence'):
                raise ValueError('located limitation evidence required')
    elif stage_id == 'ideas':
        seed_to_test(value, base_dir=base_dir)
        if {row.get('stream') for row in value['ideas']} != {'a', 'b'}:
            raise ValueError('both independent idea streams required')
        for row in value['ideas']:
            for key in ('id', 'seed', 'hypothesis', 'prediction'):
                _required_text(row.get(key), 'idea ' + key)
            novelty = row.get('novelty', {})
            if type(novelty.get('rank')) is not int or novelty['rank'] < 1:
                raise ValueError('novelty ordering required; it is not acceptance')
            pin(novelty.get('scout_receipt'))
            for source in novelty.get('prior_art', []):
                pin(source)
    elif stage_id == 'baseline':
        if not value['three_columns']:
            raise ValueError('three-column baseline required')
        for row in value['three_columns']:
            _required_text(row.get('quantity'), 'baseline quantity')
            for key in ('ours', 'reproduced', 'published'):
                cell = row.get(key)
                if not isinstance(cell, dict) or not cell:
                    raise ValueError('baseline requires ours / reproduced / published columns')
                if 'unavailable_reason' in cell:
                    _required_text(cell['unavailable_reason'], key)
                else:
                    for field in ('value', 'unit', 'uncertainty', 'source'):
                        if field not in cell:
                            raise ValueError('baseline column missing ' + field)
                    pin(cell['source'])
            pin(row.get('published_source'))
    elif stage_id == 'screen':
        if not value['subset'].get('cells') or type(value['omitted_regimes']) is not list:
            raise ValueError('screen needs explicit cells and omitted regimes')
        if not value['verdicts']:
            raise ValueError('screen verdicts required')
        for row in value['verdicts']:
            if row.get('verdict') not in {'promote', 'discard', 'engineer'}:
                raise ValueError('screen verdict must promote, discard or engineer')
            paths = row.get('mutable_paths')
            if type(paths) is not list or any(Path(p).is_absolute() or '..' in Path(p).parts for p in paths):
                raise ValueError('declared run-relative mutable paths required')
            if row['verdict'] == 'engineer' and not paths:
                raise ValueError('engineering requires declared mutable paths')
            _rdj(row, 'R2' if row['verdict'] == 'promote' else 'R1', base_dir)
    elif stage_id == 'validate':
        computed_stop(value, base_dir=base_dir, state=_observed_state(base_dir))
        stop = value['stop']
        if any(type(stop.get(k)) is not int or stop[k] < 1 for k in ('successes', 'max_rounds')):
            raise ValueError('finite evolution success and round bounds required')
        rounds = value['rounds']
        if not rounds or len(rounds) > stop['max_rounds'] or not value['withheld_cells']:
            raise ValueError('bounded evolution and withheld confirmation required')
        for number, row in enumerate(rounds, 1):
            if (row.get('round') != number or not row.get('candidates')
                    or type(row.get('successes')) is not int or row['successes'] < 0):
                raise ValueError('evolution needs complete ordered traces and seed re-injection')
            if 'trace' in row:
                pin(row['trace'])
        if value['selection'].get('rule') != 'reviewed_dominance':
            raise ValueError('selection requires reviewed dominance')
        if 'comparison' in value['selection']:
            pin(value['selection']['comparison'])
        _rdj(value['selection'], 'R2', base_dir)
    elif stage_id == 'critique_to_experiments':
        for row in value['concerns']:
            for key in ('id', 'finding', 'experiment'):
                _required_text(row.get(key), 'concern ' + key)
            if row.get('status') != 'done':
                raise ValueError('critique experiment remains unresolved')
            pin(row.get('result'))
    elif stage_id == 'acceptance':
        if any(c.get('verdict') == 'accepted' for c in value.get('claims', [])):
            pending = producer_pending()
            if pending:
                raise ValueError('; '.join(pending))
        if not value['claims']:
            raise ValueError('explicit scoped claim dispositions required')
        for row in value['claims']:
            if type(row.get('N')) is not int or row['N'] < 0:
                raise ValueError('trials_unreported')
            if row.get('kind') not in {'mechanism', 'performance', 'finding', 'agreement'}:
                raise ValueError('known research claim kind required')
            if row.get('verdict') not in {'accepted', 'exploratory', 'refused'}:
                raise ValueError('explicit research claim disposition required')
            if row['verdict'] != 'accepted':
                validate_selection_claim(row, base_dir=base_dir)
                continue
            if row['kind'] == 'mechanism':
                ablation = row.get('ablation')
                if not isinstance(ablation, dict) or not ablation.get('controls_fixed'):
                    raise ValueError('mechanism acceptance requires a controlled ablation')
                pin(ablation.get('arm_without_mechanism'))
            validate_selection_claim(row, base_dir=base_dir)
            minimum = 'R3' if regime == 'open_exploratory' or row['kind'] == 'performance' else 'R2'
            receipt = _rdj(row, minimum, base_dir)
            if minimum == 'R3':
                attestation = receipt.get('attestation_summary', {})
                if (not attestation.get('distinct_sessions')
                        or not attestation.get('distinct_actors')):
                    raise ValueError('open findings require an independent review and R3 case')
    elif stage_id == 'meta_review':
        _required_text(value['transport_id'], 'meta-review transport')
        pin(value['receipt'])
        if value['verdict'].get('outcome') != 'accept':
            raise ValueError('meta-review objections require registered experiments')
    elif stage_id == 'integrity':
        for key in definitions[stage_id]['required_outputs']:
            record = _method_json(value[key], base_dir)
            if key in {'rerun', 'references', 'paper_vs_code'} and record.get('status') != 'passed':
                raise ValueError('integrity audit unresolved: ' + key)
    return deepcopy(value)


def review_limitation_census(root):
    """Current journal classifications, original findings and per-claim consequences."""
    from . import physics_review
    if not physics_review.registered(root):
        return []
    registration, events = physics_review._read(physics_review._root(root))
    return physics_review._view(registration, events)['limitation_census']


def current_limitation_census(root, artifact=None):
    """Overlay current review effects without rewriting a historical scientific record."""
    value = deepcopy(artifact) if artifact is not None else {'limitations': []}
    value['review_limitations'] = review_limitation_census(root)
    return value


def methodology_status(root):
    """Read-only current protocol projection; missing/altered stages fail closed."""
    root = Path(root)
    try:
        value = state_io.read_json(_method_path(root))
        binding = state_io.read_json(root / 'research/binding.json')
    except (OSError, ValueError) as exc:
        raise ValueError('bound research protocol missing or unreadable') from exc
    definition = default_protocol()
    import hashlib
    expected_sha = hashlib.sha256((Path(__file__).parents[1] / 'data/research/protocol-default.json').read_bytes()).hexdigest()
    if (value.get('schema_version') != 1 or value.get('kind') != 'research-protocol'
            or value.get('protocol') != binding.get('protocol')
            or value.get('regime') != binding.get('regime')
            or value.get('protocol', {}).get('sha256') != expected_sha
            or value.get('regime') not in definition['regimes']
            or [r.get('id') for r in value.get('stages', [])] != [r['id'] for r in definition['stages']]):
        raise ValueError('bound complete research protocol differs')
    if value.get('mandatory_protocols') != definition['mandatory_protocols']:
        raise ValueError('mandatory protocol bindings differ')
    pending = []
    for row, declared in zip(value['stages'], definition['stages']):
        if any(row.get(k) != declared[k] for k in declared):
            raise ValueError('bound research stage role/input/output definition differs')
        if row.get('status') not in {'pending', 'running', 'done', 'not_applicable', 'blocked'}:
            raise ValueError('known research stage status required')
        if row['status'] == 'not_applicable':
            _required_text(row.get('reason'), 'not_applicable')
            if not stage_inapplicable(row['id'], root):
                raise ValueError('computed applicability does not permit not_applicable: ' + row['id'])
        elif row['status'] == 'done':
            if pending:
                raise ValueError('research stage skipped its pending predecessor')
            validate_stage_artifact(row.get('id'), _method_json(row.get('artifact'), root),
                                    base_dir=root, regime=value['regime'])
        else:
            pending.append(row['id'])
        if row['status'] == 'not_applicable' and row.get('applicability') == 'computed':
            # Route-computed inapplicability runs no roles; it is rechecked above.
            continue
        if row['status'] in {'done', 'not_applicable'}:
            if set(row.get('worker_receipts', {})) != set(row['roles']):
                raise ValueError('research stage requires every role receipt')
            for receipt in row['worker_receipts'].values():
                _method_pin(receipt, root)
    for pin in value['evaluator_pins'].values():
        _method_pin(pin, root)
    if value['preregistration'] is not None:
        _method_pin(value['preregistration'], root)
    prior, caps = _prior_results(root, value, binding)
    census_stage = value['stages'][0]
    census = current_limitation_census(root, _method_json(census_stage['artifact'], root) if census_stage['status'] == 'done' else None)
    return {'schema_version': 1, 'kind': 'research-methodology-status', 'record': value,
            'pending': pending, 'next_stage': pending[0] if pending else None,
            'complete': not pending, 'scientific_acceptance': False, 'prior_results': prior,
            'claim_cap': caps, 'prospective': not caps,
            'producer_contracts': protocol_producers_present()['contracts'],
            'review_limitations': census['review_limitations'], 'limitation_census': census}


def _prior_results(root, value, binding):
    """Compute the prior-results label and claim caps from custody and run records.

    The custody row decides a binding's origin; the run's ``migration`` key and
    the binding's ``origin`` key are mirrors. Without a custody row, an intake
    binding of a run that already has results cannot be verified and is capped.
    """
    import hashlib
    from . import research_launch
    sha = hashlib.sha256((Path(root) / 'research/binding.json').read_bytes()).hexdigest()
    rows = custody_rows(root)
    bound = [r for r in rows if r.get('event') == 'bound' and r.get('binding_sha256') == sha]
    if not bound and any(r.get('event') == 'bound' for r in rows):
        raise ValueError('research binding differs from its custody record')
    origin = bound[-1]['origin'] if bound else binding.get('origin')
    if bound and binding.get('origin', origin) != origin:
        raise ValueError('research binding origin differs from its custody record')
    if origin == 'migration' or 'migration' in value:
        if 'migration' not in value:
            raise ValueError('migrated research binding requires its migration receipt')
        if bound and bound[-1].get('migration_sha256') != value['migration']['sha256']:
            raise ValueError('research migration receipt differs from its custody record')
        receipt = _method_json(value['migration'], root)
        if receipt['new_binding']['binding']['sha256'] != sha:
            raise ValueError('research migration receipt names another binding')
        prior = receipt['prior_results']['label']
    elif bound or not research_launch.has_results(root):
        prior = 'protocol_bound_from_intake'
    else:
        prior = 'binding_origin_unverified'
    caps = ['prior_results:' + prior] if prior in CAPPED else []
    registered = [r for r in rows if r.get('event') == 'preregistered']
    history = value.get('preregistration_history', [])
    if value['preregistration'] is not None:
        record = _method_json(value['preregistration'], root)
        if record.get('post_hoc') or any(r.get('post_hoc') for r in registered):
            caps.append('post_hoc_preregistration')
        elif not registered and research_launch.has_results(root):
            caps.append('preregistration_timing_unverified')
    if any(r.get('superseded_after_execution') for r in [*registered, *history]):
        caps.append('plan_revised_after_execution')
    return prior, caps


def methodology_errors(root):
    """Applicable stages without completion; ordinary runs use their workflow records."""
    status = methodology_status(root)
    if (Path(root)/'head.json').exists():
        return ['required research stage incomplete: ' + stage for stage in status['pending']
                if not stage_inapplicable(stage, root)]
    evidence = ordinary_stage_evidence(root)
    return ['required research stage incomplete: ' + stage + ' (' + evidence[stage]['reason'] + ')'
            for stage in status['pending'] if evidence[stage]['status'] == 'missing']


def preregister(root, preregistration, evaluator_pins, *, supersedes=None, evaluation_harness=False):
    """Freeze code-derived expectations and evaluator code before scientific trials.

    Production records come from ``research_launch``; a supplied record is accepted
    only with ``evaluation_harness`` set and is labelled so. ``supersedes`` names the
    record a re-approved plan replaces; the history entry and the new pin are one
    atomic protocol write, and the custody ledger keeps the chain.
    """
    from .research_launch import PRODUCER, PROVENANCE_KEYS, has_results
    cycle = _cycle()
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        ordinary = not (Path(root)/'head.json').exists()
        if ordinary:
            from .research_admission import run_contract
            state = {'contract': run_contract(root), 'experiments': []}
        else:
            _, state = cycle._load(root)
        value = methodology_status(root)['record']
        if value['preregistration'] != supersedes or (supersedes is None and state['experiments']):
            raise ValueError('preregistration must precede experiments and cannot be replaced')
        declaration = _method_json(preregistration, root)
        if type(evaluation_harness) is not bool:
            raise ValueError('evaluation_harness must be explicit')
        if declaration.get('producer') != PRODUCER and not evaluation_harness:
            raise ValueError('a supplied preregistration is admitted only with evaluation_harness set; '
                             'production records come from ' + PRODUCER)
        if supersedes is not None and (declaration.get('supersedes') != supersedes
                                       or declaration.get('superseded_after_execution') is not has_results(root)):
            raise ValueError('a superseding preregistration must name its record and the execution state')
        if (declaration.get('schema_version') != 1 or declaration.get('kind') != 'research-preregistration'
                or not isinstance(declaration.get('approximations'), list)
                or not declaration.get('expected_effect')
                or not isinstance(declaration.get('evaluator_not_applicable'), dict)):
            raise ValueError('research preregistration needs approximations, expected effect and evaluator applicability')
        if not ordinary or any(k in declaration for k in ('selection_rule', 'stop_rule')):
            validate_followup_schema('selection_rule', declaration.get('selection_rule'))
            validate_followup_schema('stop', {**declaration.get('stop_rule', {}), 'reason': 'budget'})
        original = (cycle._read(state['contract']['goal_binding']['contract'], state.get('base_dir', root))
                    if 'goal_binding' in state['contract'] else state['contract'])
        if precision_required(declaration) or precision_required(original):
            sizing = precision_size(declaration)
            if declaration.get('sizing') != sizing:
                raise ValueError('preregistration sizing must match declared precision target')
        names = {'limit_setter', 'likelihood_builder', 'cutflow_comparator'}
        omitted = declaration['evaluator_not_applicable']
        if set(evaluator_pins) & set(omitted) or not names <= (set(evaluator_pins) | set(omitted)):
            raise ValueError('pin applicable evaluators and explain every inapplicable evaluator')
        for reason in omitted.values():
            _required_text(reason, 'inapplicable evaluator')
        for pin in evaluator_pins.values():
            _method_pin(pin, root)
        if supersedes is not None:
            value.setdefault('preregistration_history', []).append(
                {'record': supersedes, 'replaced_by': preregistration,
                 'superseded_after_execution': declaration['superseded_after_execution']})
        value.update(preregistration=preregistration, evaluator_pins=evaluator_pins)
        if evaluation_harness and declaration.get('producer') != PRODUCER:
            value['preregistration_authority'] = 'evaluation_harness'
        else:
            value.pop('preregistration_authority', None)
        state['methodology'] = deepcopy(value)
        if not ordinary:
            cycle._commit(Path(root), state, 'research_preregistered', preregistration=preregistration)
        state_io.atomic_json(_method_path(root), value)
        custody_append(root, {'event': 'preregistered', 'sha256': preregistration['sha256'],
                              'supersedes': None if supersedes is None else supersedes['sha256'],
                              'superseded_after_execution': bool(declaration.get('superseded_after_execution')),
                              'post_hoc': bool(declaration.get('post_hoc')),
                              'evaluation_harness': 'preregistration_authority' in value})
    return methodology_status(root)


def register_concerns(root, request_pin):
    """Turn source-bound critique findings into ordinary registered experiments."""
    request = _method_json(request_pin, root)
    if request.get('schema_version') != 1 or request.get('kind') != 'research-concern-experiments':
        raise ValueError('research concern-experiment request/v1 required')
    cycle = _cycle()
    for row in request['concerns']:
        _required_text(row.get('id'), 'concern identity')
        _required_text(row.get('finding'), 'concern finding')
        experiment = _method_json(row.get('experiment'), root)
        _, state = cycle._load(root)
        existing = [event for event in state['events'] if event['kind'] == 'research_concern_registered'
                    and event['concern_id'] == row['id']]
        if existing:
            if existing[-1]['request'] != request_pin:
                raise ValueError('registered critique finding cannot be replaced')
            continue
        if not any(e['id'] == experiment['id'] for e in state['experiments']):
            cycle.design(root, experiment)
        with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
            _, state = cycle._load(root)
            declared = next(e for e in state['experiments'] if e['id'] == experiment['id'])
            if declared['study'] != experiment['study']:
                raise ValueError('critique experiment conflicts with its ordinary registration')
            cycle._commit(Path(root), state, 'research_concern_registered', concern_id=row['id'],
                          finding=row['finding'], experiment_id=experiment['id'], request=request_pin)
    return {'schema_version': 1, 'kind': 'registered-research-concerns',
            'concerns': [{'id': row['id'], 'experiment': _method_json(row['experiment'], root)['id']}
                         for row in request['concerns']], 'execution_authorized': False}


def prepare_stage(root, stage_id, artifact, output_dir, *, model, reasoning_effort='high',
                  adapter='external', max_output_tokens=2048, max_wall_seconds=120):
    """Create the existing charged Graph/Host handoff for a proposed stage report.

    The host drafts the artifact from actual sources and results. Every declared
    role then reviews that exact proposal. This bridge uses existing Graph roles;
    A dedicated role worker can consume the named stage roles directly.
    """
    from . import agent_graph as graph, research_presentation as material
    errors = decision_errors(root, {'scope': stage_id, 'artifact': artifact})
    if errors: raise ValueError('; '.join(e.code + ': ' + e.message for e in errors))
    status = methodology_status(root)
    if status['next_stage'] != stage_id:
        raise ValueError('research stages must run in their bound order')
    record = status['record']
    if stage_id not in {'limitation_census', 'ideas'} and record['preregistration'] is None:
        raise ValueError('prospective preregistration and evaluator pins required')
    row = next(r for r in record['stages'] if r['id'] == stage_id)
    if row.get('round', 0) >= row['bound']['max_rounds']:
        raise ValueError('declared research stage review round bound exhausted')
    proposed = _method_json(artifact, root)
    if stage_id == 'validate':
        declared_stop = _method_json(record['preregistration'], root).get('stop_rule')
        if declared_stop != {k: v for k, v in proposed.get('stop', {}).items() if k != 'reason'}:
            raise ValueError('computed stop must retain prospectively registered bounds and coverage floor')
    if stage_id in {'validate', 'acceptance'}:
        _methodology_journal_guard(_cycle()._load(root)[1], stage_id, proposed, base_dir=root, regime=record['regime'])
    validate_stage_artifact(stage_id, proposed, base_dir=root, regime=record['regime'])
    if adapter not in {'external', *provider_transport.HTTP_MODEL_ACTIONS}:
        raise ValueError('research stage requires external delivery or an isolated model transport')
    out = Path(output_dir)
    if out.exists():
        raise ValueError('fresh research stage review directory required')
    out.mkdir(parents=True)
    subject = material.write_json_new(out / 'subject.json', {
        'schema_version': 1, 'kind': 'research-stage-subject', 'stage': stage_id,
        'proposal': artifact, 'artifact': proposed, 'protocol': record['protocol'],
        'world_digest': world_digest(root), 'regime': record['regime']})
    source_pins = []
    def collect(value):
        if isinstance(value, dict):
            if {'path', 'sha256'} <= value.keys():
                source_pins.append(value)
            else:
                for item in value.values():
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(proposed)
    collect(record['preregistration'])
    collect(record['evaluator_pins'])
    sources = {}
    total = subject['size']
    for pin in source_pins:
        raw = _method_pin(pin, root)
        identity = (pin['path'], pin['sha256'])
        if identity in sources:
            continue
        total += len(raw)
        if total > ce.MAX_BYTES:
            raise ValueError('complete research stage source packet exceeds bound; no truncation')
        sources[identity] = (pin, raw.decode('utf-8'))
    nodes = []
    for number, role_id in enumerate(row['roles']):
        role = 'critic' if number % 2 == 0 else 'verifier'
        packet = out / role_id / 'packet'
        (packet / 'artifacts').mkdir(parents=True)
        content = material.write_json_new(packet / 'artifacts/public_case.json', _method_json(subject, root))
        manifest = {'schema_version': 1, 'role': role, 'run_id': str(root),
                    'cycle_id': subject['sha256'], 'source_event_sha256': subject['sha256'],
                    'artifacts': [{'id': 'public_case', 'path': 'artifacts/public_case.json',
                                   'sha256': content['sha256'], 'source_sha256': subject['sha256'],
                                   'source_path': subject['path'], 'projection': 'complete_research_stage_subject'}],
                    'omissions': [], 'findings': [], 'reviews': [], 'allowed_claim_scopes': {},
                    'required_checks': [], 'access_limitation': 'Methodology review only; no independent physics acceptance.'}
        for index, (pin, text) in enumerate(sources.values()):
            name = 'source-' + str(index)
            source = material.write_new(packet / ('artifacts/' + name + '.txt'), text.encode('utf-8'))
            manifest['artifacts'].append({'id': name, 'path': 'artifacts/' + name + '.txt',
                'sha256': source['sha256'], 'source_sha256': pin['sha256'], 'source_path': pin['path'],
                'projection': 'full_authenticated_source_or_evidence'})
        manifest['sha256'] = graph.digest(manifest)
        material.write_json_new(packet / 'manifest.json', manifest)
        fields = {'stage': {'type': 'string', 'const': stage_id},
                  'role_id': {'type': 'string', 'const': role_id},
                  'subject_sha256': {'type': 'string', 'const': subject['sha256']},
                  'verdict': {'type': 'string', 'enum': ['accept', 'revise']},
                  'findings': {'type': 'array', 'items': {'type': 'string'}},
                  'attributed_claim_ids': {'type': 'array', 'items': {'type': 'string'}}}
        nodes.append({'id': role_id, 'kind': 'model', 'role': role, 'depends_on': [],
                      'inputs': [], 'packet': {'path': str(packet), 'manifest_sha256': manifest['sha256']},
                      'action': adapter, 'max_attempts': 1,
                      'parameters': {'model': model, 'reasoning_effort': reasoning_effort,
                                     'max_output_tokens': max_output_tokens,
                                     'instructions': ' '.join(row['protocol']),
                                     'output_schema': {'type': 'object', 'properties': fields,
                                                       'required': list(fields), 'additionalProperties': False}}})
    spec = {'schema_version': 1, 'graph_id': 'research-' + stage_id, 'nodes': nodes,
            'budget': {'max_nodes': len(nodes), 'max_calls': len(nodes),
                       'max_output_tokens': max_output_tokens * len(nodes),
                       'max_wall_seconds': max_wall_seconds, 'max_reworks': 0}}
    graph.validate(spec)
    specification = material.write_json_new(out / 'graph-spec.json', spec)
    prepared = {'schema_version': 1, 'kind': 'research-stage-preparation', 'stage': stage_id,
            'artifact': artifact, 'subject': subject, 'specification': specification,
            'roles': row['roles'], 'workers': len(nodes), 'execution_authorized': False}
    cycle = _cycle()
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = cycle._load(root)
        if state.get('methodology') != record:
            raise ValueError('research stage changed during preparation')
        row.update(status='running', round=row.get('round', 0) + 1,
                   active_preparation=deepcopy(prepared))
        state['methodology'] = deepcopy(record)
        cycle._commit(Path(root), state, 'research_stage_review_prepared', stage=stage_id,
                      specification=specification)
        state_io.atomic_json(_method_path(root), record)
    return prepared


def complete_stage(root, prepared, graph_root):
    """Adopt only current, charged, actually delivered stage-role results."""
    from . import agent_graph as graph, research_presentation as material
    cycle = _cycle()
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = cycle._load(root)
        status = methodology_status(root)
        if prepared['stage'] != status['next_stage']:
            raise ValueError('research stage already consumed or not currently admissible')
        spec = _method_json(prepared['specification'], root)
        # The campaign reserved and dispatched this stage Graph with its inherited parent
        # assignment (research_cycle.execute_graph); re-check the reservation on that same Graph.
        inherited = state['contract'].get('goal_binding')
        if inherited is not None:
            if spec.get('goal_binding', inherited) != inherited:
                raise ValueError('research stage Graph cannot replace its original parent assignment')
            spec = {**spec, 'goal_binding': deepcopy(inherited)}
        cycle.validate_graph_reservation(state, Path(graph_root), spec)
        subject = _method_json(prepared['subject'], root)
        if subject['world_digest'] != world_digest(root):
            raise ValueError('research evidence changed since stage review preparation')
        artifact = _method_json(prepared['artifact'], root)
        if subject['proposal'] != prepared['artifact'] or subject['artifact'] != artifact:
            raise ValueError('research stage proposal changed')
        record = status['record']
        row = next(r for r in record['stages'] if r['id'] == prepared['stage'])
        if row.get('active_preparation') != prepared:
            raise ValueError('research stage review belongs to a superseded proposal')
        errors = decision_errors(root, {'scope': row['id'], 'artifact': prepared['artifact']})
        if errors: raise ValueError('; '.join(e.code for e in errors))
        _methodology_journal_guard(state, row['id'], artifact, base_dir=root, regime=record['regime'])
        validate_stage_artifact(row['id'], artifact, base_dir=root, regime=record['regime'])
        receipts = {}
        attributed = set()
        for node in spec['nodes']:
            if node['id'] not in row['roles']:
                raise ValueError('unexpected research stage role')
            try:
                origin = cycle._graph_result(graph_root, node['id'])
            except (ValueError, OSError, KeyError) as exc:
                cycle._commit(Path(root), state, 'completion_claimed_without_receipts',
                              worker=node['id'], model_cell=node['parameters']['model'], stage=row['id'])
                raise
            value = origin['value']['value']
            if (value.get('verdict') != 'accept' or value.get('stage') != row['id']
                    or value.get('role_id') != node['id']
                    or value.get('subject_sha256') != prepared['subject']['sha256']):
                raise ValueError('research stage review requires revision')
            receipt = graph.role_receipt(graph_root, node['id'],
                expected_subject_sha256=prepared['subject']['sha256'],
                expected_packet_sha256=node['packet']['manifest_sha256'],
                allowed_roles={node['role']}, require_exact_subject=True)
            if (not receipt['context_transport_separated'] or receipt['execution_observation'] not in
                    {'remote_transport_observed', 'local_transport_observed', 'host_attested_external'}):
                raise ValueError('actual fresh stage-role delivery required')
            from . import review_context
            manifest = review_context.verify_packet(node['packet']['path'],
                expected_manifest_sha256=node['packet']['manifest_sha256'])
            required = {item['sha256'] for item in manifest['artifacts']}
            if not required <= set(receipt.get('presented_subject_sha256s', [])):
                raise ValueError('complete stage evidence must actually be presented to every role')
            if node['id'] == 'ablation-critic':
                attributed = set(value.get('attributed_claim_ids', []))
            receipts[node['id']] = material.write_json_new(
                Path(prepared['subject']['path']).parent / (node['id'] + '-receipt.json'), receipt)
        if set(receipts) != set(row['roles']):
            raise ValueError('every declared stage role must complete')
        if row['id'] == 'acceptance' and artifact.get('status') != 'not_applicable':
            required = {c['id'] for c in artifact['claims'] if c['kind'] == 'mechanism' and c['verdict'] == 'accepted'}
            if not required <= attributed:
                raise ValueError('ablation critic did not attribute the claimed mechanism gain')
        if row['id'] == 'critique_to_experiments' and artifact.get('status') != 'not_applicable':
            experiments = {e['id']: e for e in state['experiments']}
            for concern in artifact['concerns']:
                registered = [event for event in state['events'] if event['kind'] == 'research_concern_registered'
                              and event['concern_id'] == concern['id']
                              and event['finding'] == concern['finding']
                              and event['experiment_id'] == concern['experiment']]
                if not registered:
                    raise ValueError('critique finding needs its registered discriminating experiment')
                if concern['experiment'] not in experiments:
                    raise ValueError('critique finding lacks its registered experiment')
                experiment = experiments[concern['experiment']]
                cycle._current_evidence(state, experiment, accepted=True)
                if concern['result']['sha256'] != experiment['observation']['result']['sha256']:
                    raise ValueError('critique result differs from its actual reviewed experiment')
        row.update(status='not_applicable' if artifact.get('status') == 'not_applicable' else 'done',
                   reason=artifact.get('reason'), artifact=prepared['artifact'], worker_receipts=receipts)
        state['methodology'] = deepcopy(record)
        cycle._commit(Path(root), state, 'research_methodology_stage_completed', stage=row['id'],
                      artifact=prepared['artifact'], graph_root=str(graph_root))
        state_io.atomic_json(_method_path(root), record)
    return methodology_status(root)


def world_digest(root):
    """Carry verified current results and ruled-out directions, never raw votes."""
    import hashlib, json
    root = Path(root)
    verified, excluded, unresolved = [], [], []
    register = {}
    if (root / 'head.json').exists():
        cycle = _cycle()
        _, state = cycle._load(root)
        register = cycle.replay_register(state['events'], base_dir=state['base_dir'])
        for experiment in state['experiments']:
            if (experiment.get('adjudication') or {}).get('view', {}).get('state') == 'accepted':
                cycle._current_evidence(state, experiment, accepted=True)
                verified.append({'id': experiment['id'], 'observation': experiment['observation'],
                                 'scope': experiment['acceptance_scope'],
                                 'review': experiment['adjudication']['snapshot']})
            else:
                unresolved.append({'id': experiment['id'], 'observation': experiment.get('observation')})
    record = state_io.read_json(_method_path(root))
    for stage in record['stages']:
        if stage['id'] == 'screen' and stage['status'] == 'done':
            artifact = _method_json(stage['artifact'], root)
            excluded.extend(deepcopy(row) for row in artifact['verdicts'] if row['verdict'] == 'discard')
    value = {'schema_version': 1, 'kind': 'research-world-digest',
             'verified_results': verified, 'ruled_out_directions': excluded, 'unresolved': unresolved,
             'hypothesis_register': register}
    value['sha256'] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                              ensure_ascii=False).encode()).hexdigest()
    return value


def gate_errors(rundir, gate, action):
    """research_choice decision-gate provider; checking never dispatches or mutates."""
    if gate != 'research_choice':
        return []
    from .research_admission import GateError, decision_provider
    provider = decision_provider()
    if provider is None:
        return [GateError('decision_gate_unavailable', gate, 'research_protocol',
                          'research_choice decision provider is not installed',
                          'Install the ravel.workflow.decision_gate module.')]
    GateError = provider.GateError
    try:
        status = methodology_status(rundir)
        if action.get('purpose') == 'confirm' or action.get('exposure') == 'withheld_confirmation' or _action_reads_withheld(rundir, action):
            _, state = _cycle()._load(rundir)
            receipt, reads = _selection_state(state)
            codes = confirmation_errors(receipt, reads, action)
            return [GateError(code=code, gate=gate, provider='research_protocol', message=code,
                              fix='Commit selection and use disjoint unused confirmation inputs.') for code in codes]
        stage = action.get('scope') or status['next_stage']
        if stage not in {r['id'] for r in status['record']['stages']}:
            messages = ['research choice requires a declared protocol stage']
        else:
            index = [r['id'] for r in status['record']['stages']].index(stage)
            messages = ['required research stage incomplete: ' + r['id']
                        for r in status['record']['stages'][:index]
                        if r['status'] not in {'done', 'not_applicable'}]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        messages = [str(exc)]
    return [GateError(code='research_protocol_pending', gate=gate, provider='research_protocol',
                      message=message, fix='Complete the bound research stage and its required artifacts.')
            for message in messages]


def _cycle():
    from . import research_cycle
    return research_cycle


def _ids(rows, limit, label):
    if type(rows) is not list or not 1 <= len(rows) <= limit:
        raise ValueError("bounded complete " + label + " required")
    out = {}
    for row in rows:
        ce.identity(row["id"])
        if row["id"] in out: raise ValueError("duplicate " + label)
        out[row["id"]] = row
    return out


def _list_ids(ids, known, *, empty=True):
    if type(ids) is not list or len(set(ids)) != len(ids) or set(ids) - set(known) or (not empty and not ids):
        raise ValueError("complete distinct declared identities required")


def _pins(pins, base):
    found = comparison._census(pins, base, max_entries=8192, max_unique=128)
    for pin in found: comparison._snapshot(pin, base)
    return found


def validate(value, *, base_dir, state, check_sources=True, retained_rules=None):
    ce.keys(value, ("schema_version", "id", "scope", "candidates", "cells", "stages", "comparisons", "claims",
                    "required_stage_ids", "required_comparison_ids", "round_limits", "not_applicable", "meta_actors"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("staged research protocol/v1 required")
    ce.identity(value["id"]); _cycle()._text(value["scope"])
    candidates = _ids(value["candidates"], 8, "candidate census")
    cells = _ids(value["cells"], 32, "evaluation cell census")
    stages = _ids(value["stages"], 32, "stage census")
    comparators = _ids(value["comparisons"], 16, "comparison census") if value["comparisons"] else {}
    claims = _ids(value["claims"], 32, "claim census")
    premises = {p["id"] for p in state["premises"]}
    pins = []
    ce.keys(value["round_limits"], ("generations", "ablations", "meta_reviews"))
    for k, maximum in (("generations", 8), ("ablations", 16), ("meta_reviews", 8)):
        if type(value["round_limits"][k]) is not int or not 0 <= value["round_limits"][k] <= maximum:
            raise ValueError("finite declared methodology rounds required")
    ce.keys(value["meta_actors"], ("critic", "verifier"))
    for x in value["meta_actors"].values(): _cycle()._text(x)
    if len(set(value["meta_actors"].values())) != 2: raise ValueError("separate declared meta-review actors required")
    for c in candidates.values():
        ce.keys(c, ("id", "parent", "generation", "components", "invariant_inputs", "premise_ids", "reason", "requalifies"))
        _cycle()._text(c["reason"]); _list_ids(c["premise_ids"], premises)
        if type(c["generation"]) is not int or not 0 <= c["generation"] <= value["round_limits"]["generations"]:
            raise ValueError("bounded candidate generation required")
        if type(c["components"]) is not dict or not 1 <= len(c["components"]) <= 16: raise ValueError("exact finite component map required")
        for k, p in c["components"].items(): ce.identity(k); comparison._pin(p); pins.append(p)
        pins.extend(c["invariant_inputs"])
        if c["parent"] is None:
            if c["generation"] != 0: raise ValueError("seed generation must be zero")
        elif c["parent"] not in candidates or c["generation"] != candidates[c["parent"]]["generation"] + 1:
            raise ValueError("exact retained candidate parent and next generation required")
        if c['requalifies'] is not None and (c['requalifies'] not in candidates or c['generation']<=candidates[c['requalifies']]['generation'] or c['invariant_inputs']!=candidates[c['requalifies']]['invariant_inputs']):
            raise ValueError('explicit older source requalification with held scientific inputs required')
    for cell in cells.values():
        ce.keys({k: v for k, v in cell.items() if k not in {"seeds", "generation"}}, ("id", "population", "normalization", "regime", "fidelity", "exposure", "metric", "unit", "premise_ids", "replaces"))
        for k in ("regime", "fidelity", "metric", "unit"): _cycle()._text(cell[k])
        _list_ids(cell["premise_ids"], premises)
        if cell["exposure"] not in EXPOSURES: raise ValueError("evaluation exposure must remain explicit")
        pins.extend([cell["population"], cell["normalization"]])
        if cell["replaces"] is not None:
            prior = cells.get(cell["replaces"])
            if prior is None or prior["id"] == cell["id"] or any(prior[k] != cell[k] for k in cell if k not in {"id","replaces"}):
                raise ValueError("new cell must retain exact population, normalization, metric, exposure and premise identities")
    experiment_ids = set(); ablations = 0
    for stage in stages.values():
        ce.keys(stage, ("id", "purpose", "candidate", "cells", "requires", "requires_stages", "acceptance_scope", "premise_ids", "ablation", "replaces"))
        if stage["purpose"] not in PURPOSES or stage["candidate"] not in candidates: raise ValueError("known stage purpose/candidate required")
        _cycle()._text(stage["acceptance_scope"]); _list_ids(stage["premise_ids"], premises)
        if type(stage["cells"]) is not list or not 1 <= len(stage["cells"]) <= 32: raise ValueError("complete stage cell assignment required")
        assigned = []
        for row in stage["cells"]:
            ce.keys(row, ("cell_id", "experiment_id", "value_pointer", "interval_pointer", "quality_pointer"))
            if row["cell_id"] not in cells: raise ValueError("unknown stage cell")
            assigned.append(row["cell_id"]); ce.identity(row["experiment_id"]); experiment_ids.add(row["experiment_id"])
            for key in ("value_pointer", "quality_pointer"): comparison._pointer(row[key])
            if row["interval_pointer"] is not None: comparison._pointer(row["interval_pointer"])
            exposure = cells[row["cell_id"]]["exposure"]
            if exposure == 'withheld_confirmation' and stage['purpose'] != 'confirm':
                raise ValueError('confirm_cell_in_selection_inputs: withheld cells are reserved for confirmation')
            if stage["purpose"] == "screen" and exposure != "adaptive_screen": raise ValueError("screen cells cannot claim full/withheld fidelity")
            if stage['purpose'] == 'full' and exposure != 'adaptive_full': raise ValueError('confirm_cell_in_selection_inputs: full evaluation cannot use screen-only cells or withheld cells; requires adaptive_full')
            if stage['purpose'] == 'confirm' and exposure != 'withheld_confirmation': raise ValueError('confirm_cell_in_selection_inputs: confirm requires withheld cells')
        if len(set(assigned)) != len(assigned): raise ValueError("duplicate stage cell")
        if type(stage["requires"]) is not list or len(stage["requires"]) > 16: raise ValueError("bounded comparison prerequisites required")
        _list_ids(stage["requires_stages"], stages)
        for requirement in stage["requires"]:
            ce.keys(requirement, ("comparison_id", "allowed_decisions"))
            if requirement["comparison_id"] not in comparators: raise ValueError("known comparison prerequisite required")
            _list_ids(requirement["allowed_decisions"], DECISIONS - {"unknown"}, empty=False)
        if stage["purpose"] == "ablation":
            ablations += 1
            ce.keys(stage["ablation"], ("component", "kind", "parent_candidate"))
            a = stage["ablation"]; ce.identity(a["component"])
            if a["kind"] not in {"remove_one", "replace_one", "add_one"} or a["parent_candidate"] not in candidates:
                raise ValueError("one explicitly isolated component ablation required")
            own, parent = candidates[stage["candidate"]], candidates[a["parent_candidate"]]
            if own["parent"] != parent["id"] or own["invariant_inputs"] != parent["invariant_inputs"]:
                raise ValueError("ablation must retain exact parent and held scientific inputs")
            changed = {k for k in set(own["components"]) | set(parent["components"]) if own["components"].get(k) != parent["components"].get(k)}
            if changed != {a["component"]}: raise ValueError("multi-component change is not an isolated ablation")
            if (a["kind"] == "remove_one" and a["component"] in own["components"]) or (a["kind"] == "add_one" and a["component"] in parent["components"]) or (a["kind"] == "replace_one" and a["component"] not in set(own["components"]) & set(parent["components"])):
                raise ValueError("ablation edit kind differs from component manifest")
        elif stage["ablation"] is not None: raise ValueError("only ablation stages carry component contracts")
        if stage["replaces"] is not None:
            prior = stages.get(stage["replaces"])
            if prior is None or prior["id"] == stage["id"]:
                raise ValueError("declared prior stage replacement required")
            original_cells = {r["cell_id"] for r in prior["cells"]}
            mapped_cells = {cid if cid in original_cells else cells[cid]["replaces"] for cid in assigned}
            if (prior["purpose"], prior["acceptance_scope"], original_cells) != (stage["purpose"], stage["acceptance_scope"], mapped_cells):
                raise ValueError("replacement must retain purpose, cell denominator and acceptance scope")
            own = candidates[stage["candidate"]]
            if prior['candidate'] not in {own['parent'],own['requalifies']} or own["invariant_inputs"] != candidates[prior["candidate"]]["invariant_inputs"]:
                raise ValueError("replacement needs a fresh direct candidate generation")
    confirm_cells = {r['cell_id'] for s in stages.values() if s['purpose'] == 'confirm' for r in s['cells']}
    select_cells = {r['cell_id'] for s in stages.values() if s['purpose'] != 'confirm' for r in s['cells']}
    if confirm_cells:
        for candidate in {s['candidate'] for s in stages.values() if s['purpose'] == 'confirm'}:
            assigned = [r for s in stages.values() if s['purpose'] == 'confirm' and s['candidate'] == candidate for r in s['cells']]
            if len({r['cell_id'] for r in assigned}) != len(assigned):
                raise ValueError('confirmation cell can be assigned only once per candidate')
        for cid in confirm_cells | select_cells:
            _exposure_identity({'cells': [cid], **{k: cells[cid].get(k) for k in ('seeds', 'generation')}})
        for cid in confirm_cells:
            for sid in select_cells:
                if (cid == sid or cells[cid]['population']['sha256'] == cells[sid]['population']['sha256']
                        or {str(v) for v in cells[cid]['seeds']} & {str(v) for v in cells[sid]['seeds']}
                        or cells[cid]['generation'] == cells[sid]['generation']):
                    raise ValueError('confirm_cell_in_selection_inputs')
    if ablations > value["round_limits"]["ablations"]: raise ValueError("ablation round ceiling exceeded")
    for row in comparators.values():
        ce.keys(row, ("id", "left_stage", "right_stage", "experiment_id", "rule", "acceptance_scope", "replaces"))
        if row["left_stage"] not in stages or row["right_stage"] not in stages or row["left_stage"] == row["right_stage"]:
            raise ValueError("distinct complete comparison stage operands required")
        left, right = stages[row["left_stage"]], stages[row["right_stage"]]
        ids = {x["cell_id"] for x in left["cells"]}
        if ids != {x["cell_id"] for x in right["cells"]}: raise ValueError("comparison requires same complete declared cell matrix")
        rule = comparison.rule(retained_rules[row['id']] if retained_rules is not None and row['id'] in retained_rules else _json(row["rule"], base_dir)); pins.append(row["rule"])
        if any((cells[i]["metric"], cells[i]["unit"]) != (rule["metric"], rule["unit"]) for i in ids):
            raise ValueError("heterogeneous metrics require a separate domain comparator")
        ce.identity(row["experiment_id"]); _cycle()._text(row["acceptance_scope"])
        if row["experiment_id"] in experiment_ids: raise ValueError("comparison requires its own ordinary scoped evidence")
        experiment_ids.add(row["experiment_id"])
        if row["replaces"] is not None:
            prior = comparators.get(row["replaces"])
            if prior is None or prior["id"] == row["id"] or prior["rule"] != row["rule"] or prior["acceptance_scope"] != row["acceptance_scope"]:
                raise ValueError("replacement comparison must preserve the prospective rule and scope")
            for side in ("left_stage", "right_stage"):
                if row[side] != prior[side] and stages[row[side]]["replaces"] != prior[side]:
                    raise ValueError("replacement comparator operands need exact stage replacement lineage")
    for stage in stages.values():
        if stage['purpose'] in {'screen','full'}:
            for requirement in stage['requires']:
                comp=comparators[requirement['comparison_id']]
                if stage['candidate'] not in {stages[comp[k]]['candidate'] for k in ('left_stage','right_stage')}:
                    raise ValueError('promotion cannot borrow a different candidate generation comparison')
    # Detect indirect promotion/comparison cycles before any study is planned.
    def ancestors(stage_id, seen):
        if stage_id in seen: raise ValueError("cyclic stage promotion dependencies")
        for prerequisite in stages[stage_id]["requires_stages"]:ancestors(prerequisite,seen | {stage_id})
        for req in stages[stage_id]["requires"]:
            comp = comparators[req["comparison_id"]]
            for operand in (comp["left_stage"], comp["right_stage"]): ancestors(operand, seen | {stage_id})
    for stage_id in stages: ancestors(stage_id, set())
    if len(experiment_ids) > state["contract"]["max_experiments"]: raise ValueError("protocol exceeds existing experiment ceiling")
    if set(state["contract"]["required_experiments"]) - experiment_ids: raise ValueError("original required experiment denominator must be retained")
    _list_ids(value["required_stage_ids"], stages, empty=False); _list_ids(value["required_comparison_ids"], comparators)
    for claim in claims.values():
        ce.keys(claim, ("id", "statement", "acceptance_criteria", "stage_ids", "comparison_ids", "premise_ids", "report_slot", "replaces"))
        _list_ids(claim["stage_ids"], stages, empty=False); _list_ids(claim["comparison_ids"], comparators)
        _list_ids(claim["premise_ids"], premises); _cycle()._text(claim["report_slot"])
        _cycle()._text(claim["statement"]); pins.append(claim["acceptance_criteria"])
        if claim["replaces"] is not None:
            prior = claims.get(claim["replaces"])
            if prior is None or prior["id"] == claim["id"] or any(prior[k] != claim[k] for k in ("report_slot","statement","acceptance_criteria","premise_ids")):
                raise ValueError("replacement must retain the original reporting obligation")
            for field, rows in (("stage_ids",stages),("comparison_ids",comparators)):
                original = set(prior[field])
                if {i if i in original else rows[i]["replaces"] for i in claim[field]} != original:
                    raise ValueError("replacement claim must retain every original stage and comparison obligation")
    for rows in (cells, stages, comparators, claims):
        for row in rows.values():
            seen = set(); current = row
            while current["replaces"] is not None:
                if current["id"] in seen: raise ValueError("cyclic replacement lineage")
                seen.add(current["id"]); current = rows[current["replaces"]]
    if type(value["not_applicable"]) is not list or len(value["not_applicable"]) > 5: raise ValueError("finite explicit justified phase omissions required")
    for row in value["not_applicable"]:
        ce.keys(row, ("purpose", "reason")); _cycle()._text(row["reason"])
        if row["purpose"] not in PURPOSES or row["purpose"] in {s["purpose"] for s in stages.values()}:
            raise ValueError("phase omission cannot erase a declared evaluation stage")
    if check_sources:_pins(pins,base_dir)
    else:
        comparison._census(pins,base_dir,max_entries=8192,max_unique=128)
    return deepcopy(value)


def _all_pins(protocol):
    pins = []
    for c in protocol["candidates"]: pins.extend([*c["components"].values(), *c["invariant_inputs"]])
    for c in protocol["cells"]: pins.extend([c["population"], c["normalization"]])
    pins.extend(c["rule"] for c in protocol["comparisons"])
    pins.extend(c["acceptance_criteria"] for c in protocol["claims"])
    return pins


def _bound(state):
    events = [e for e in state["events"] if e["kind"] == "staged_protocol_bound"]
    if not events: return None
    event = events[-1]; protocol = _json(event["protocol"], state["base_dir"])
    validate(protocol, base_dir=state["base_dir"], state=state,check_sources=False,retained_rules=event['rule_contracts'])
    return protocol, event


def bind(root, protocol_pin):
    cycle = _cycle()
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = cycle._load(root); value = _json(protocol_pin, state["base_dir"])
        old = _bound(state)
        rules={} if old is None else deepcopy(old[1]['rule_contracts'])
        validate(value,base_dir=state['base_dir'],state=state,check_sources=old is None,retained_rules=rules)
        if old is not None:
            previous = old[0]
            for k in ("id", "scope", "round_limits", "not_applicable", "meta_actors"):
                if value[k] != previous[k]: raise ValueError("existing protocol policy cannot be retroactively altered")
            for k in ("candidates", "cells", "stages", "comparisons", "claims"):
                new = {r["id"]:r for r in value[k]}
                if any(new.get(r["id"]) != r for r in previous[k]): raise ValueError("old protocol rows cannot disappear or change")
            for k in ("required_stage_ids", "required_comparison_ids"):
                if not set(previous[k]) <= set(value[k]): raise ValueError("old evaluation obligations cannot disappear")
            if value == previous: raise ValueError("new prospective protocol rows required")
            # Prior source changes reopen their own cells, rather than hiding
            # unaffected baselines. Only new prospective rows are admitted now.
            fresh=deepcopy(value)
            for field in ('candidates','cells','stages','comparisons','claims'):
                known={r['id'] for r in previous[field]};fresh[field]=[r for r in value[field] if r['id'] not in known]
            _pins(_all_pins(fresh),state['base_dir'])
        for c in value['comparisons']:
            if c['id'] not in rules:rules[c['id']]=comparison.rule(_json(c['rule'],state['base_dir']))
        existing = {e["id"]: e for e in state["experiments"]}
        old_ids = set() if old is None else {r["experiment_id"] for s in old[0]["stages"] for r in s["cells"]} | {c["experiment_id"] for c in old[0]["comparisons"]}
        affected = {r["experiment_id"] for s in value["stages"] for r in s["cells"]} | {c["experiment_id"] for c in value["comparisons"]}
        if any(e.get("rundir") is not None or e.get("observation") is not None for i,e in existing.items() if i in affected-old_ids):
            raise ValueError("evaluation protocol must precede affected attempt/planning")
        premises = {p for c in value["candidates"] for p in c["premise_ids"]} | {p for c in value["cells"] for p in c["premise_ids"]} | {p for s in value["stages"] for p in s["premise_ids"]} | {p for c in value["claims"] for p in c["premise_ids"]}
        bindings = {} if old is None else dict(old[1]["premise_bindings"])
        bindings.update({k:v for k,v in cycle._bindings(state, sorted(premises)).items() if k not in bindings})
        per_row = {} if old is None else deepcopy(old[1]["row_premise_bindings"])
        for kind in ("candidates", "cells", "stages", "claims"):
            for row in value[kind]:
                key = kind + ":" + row["id"]
                if key not in per_row: per_row[key] = cycle._bindings(state, row["premise_ids"])
        return cycle._commit(Path(root), state, "staged_protocol_bound", protocol=protocol_pin, premise_bindings=bindings, row_premise_bindings=per_row,rule_contracts=rules,
                             inherited_rows_preserved=old is not None)


def _stage_ids(protocol, experiment_id):
    return [s for s in protocol["stages"] if any(r["experiment_id"] == experiment_id for r in s["cells"])]


def _stage_current(state, protocol, event, stage):
    candidate = next(c for c in protocol["candidates"] if c["id"] == stage["candidate"])
    cells = {c["id"]:c for c in protocol["cells"]}
    deps = set(stage["premise_ids"]) | set(candidate["premise_ids"]) | {p for row in stage["cells"] for p in cells[row["cell_id"]]["premise_ids"]}
    keys = ["stages:" + stage["id"], "candidates:" + candidate["id"], *["cells:" + row["cell_id"] for row in stage["cells"]]]
    source_pins=[*candidate['components'].values(),*candidate['invariant_inputs']]
    for assignment in stage['cells']:source_pins.extend([cells[assignment['cell_id']]['population'],cells[assignment['cell_id']]['normalization']])
    try:_pins(source_pins,state['base_dir'])
    except (ValueError,OSError):return False
    if not all(_cycle()._fresh(state, event["row_premise_bindings"][k]) for k in keys): return False
    for meta in state["events"]:
        if meta["kind"] == "protocol_meta_review_applied" and stage["id"] in meta["invalidated_stage_ids"]:
            return False
    stage_map={s['id']:s for s in protocol['stages']};comparators={c['id']:c for c in protocol['comparisons']}
    if any(any(r['status']!='accepted_current' for r in _stage_rows(state,protocol,event,stage_map[i])) for i in stage['requires_stages']):return False
    for requirement in stage['requires']:
        measured=_comparison_current(state,protocol,event,comparators[requirement['comparison_id']])
        if measured['status']!='accepted_current' or measured['decision'] not in requirement['allowed_decisions']:return False
    return True


def _stage_rows(state, protocol, event, stage):
    by_id = {e["id"]:e for e in state["experiments"]}; rows = []
    for assignment in stage["cells"]:
        e = by_id.get(assignment["experiment_id"]); status = "unplanned"; result = None; refusal = None
        if e is not None:
            status = "planned" if e["rundir"] is not None else "declared"
            if not _stage_current(state, protocol, event, stage) or not _cycle()._applicability(state,e)["measurement"]: status = "stale"
            elif e["observation"] is not None:
                o = e["observation"]
                status = ("scientifically_unresolved" if o.get("result_category") == "scientific_unresolved" else "operationally_unresolved") if o["execution_status"] != "succeeded" else "unreviewed"
                if e["adjudication"] is not None and e["adjudication"]["view"]["state"] == "accepted":
                    try:
                        _cycle()._current_evidence(state,e,accepted=True)
                        if e["adjudication"]["scope"] != stage["acceptance_scope"] or o["result"] is None:
                            raise ValueError("stage output review scope differs")
                        source = _json(o["result"], state["base_dir"])
                        comparison._number(_cycle()._pointer(source, assignment["value_pointer"]))
                        if not (_cycle()._pointer(source, assignment["quality_pointer"]) is True or _cycle()._pointer(source, assignment["quality_pointer"]) == "passed"):
                            raise ValueError("scientific feasibility or quality unresolved")
                        result = deepcopy(o["result"]); status = "accepted_current"
                    except (ValueError, OSError, KeyError, IndexError, TypeError) as exc:
                        status = "scientifically_unresolved"; refusal = str(exc)
        rows.append({"cell_id":assignment["cell_id"], "experiment_id":assignment["experiment_id"], "status":status, "result":result, "refusal":refusal})
    return rows


def _basis(protocol, comp):
    stages = {s["id"]:s for s in protocol["stages"]}; cells = {c["id"]:c for c in protocol["cells"]}; candidates = {c["id"]:c for c in protocol["candidates"]}
    operands = [stages[comp[k]] for k in ("left_stage","right_stage")]
    return {"comparison":comp,"stages":operands,"cells":[cells[i] for i in sorted({r["cell_id"] for s in operands for r in s["cells"]})],
            "candidates":[candidates[i] for i in sorted({s["candidate"] for s in operands})]}


def _comparison_request(state, protocol, event, comp):
    stages = {s["id"]:s for s in protocol["stages"]}; cells = {c["id"]:c for c in protocol["cells"]}
    left,right = (stages[comp[k]] for k in ("left_stage","right_stage"))
    actual = {s["id"]:{r["cell_id"]:r for r in _stage_rows(state,protocol,event,s)} for s in (left,right)}
    if any(r["status"] != "accepted_current" for rows in actual.values() for r in rows.values()):
        raise ValueError("complete current scoped baseline/candidate operands required")
    rows = []
    for cid in sorted(actual[left["id"]]):
        cell=cells[cid];row={"id":cid,"metric":cell["metric"],"unit":cell["unit"],"exposure":cell["exposure"]}
        for side,s in (("left",left),("right",right)):
            assigned=next(r for r in s["cells"] if r["cell_id"]==cid)
            row[side]={"source":actual[s["id"]][cid]["result"],**{k:assigned[k] for k in ("value_pointer","interval_pointer","quality_pointer")}}
        rows.append(row)
    basis=_basis(protocol,comp)
    deps=[*sum(([c["population"],c["normalization"]] for c in basis["cells"]),[]),*sum(([*c["components"].values(),*c["invariant_inputs"]] for c in basis["candidates"]),[])]
    return {"schema_version":1,"protocol_sha256":ce.digest(basis),"comparison_id":comp["id"],"rule":comp["rule"],"cells":rows,"dependencies":_pins(deps,state["base_dir"])}


def _comparison_current(state, protocol, event, comp):
    e=next((e for e in state["experiments"] if e["id"]==comp["experiment_id"]),None)
    if e is None or e["observation"] is None or e["adjudication"] is None:
        return {"status":"pending","decision":None}
    try:
        expected=_comparison_request(state,protocol,event,comp)
        _cycle()._current_evidence(state,e,accepted=True)
        if not _cycle()._applicability(state,e)["measurement"] or e["adjudication"]["scope"]!=comp["acceptance_scope"]:
            raise ValueError("current comparison scope/premise required")
        spec=_json(e["study"],state["base_dir"])
        if spec["mode"]!="research-comparison": raise ValueError("explicit ordinary complete comparison operation required")
        supplied=_json(spec["task"]["request"],state["base_dir"])
        if supplied!=expected: raise ValueError("comparison operands/rule differ from complete current stage matrix")
        observed=_json(e["observation"]["result"],state["base_dir"])
        calculated=comparison.calculate(spec["task"],state["base_dir"])
        if observed!=calculated: raise ValueError("comparison arithmetic/result differs")
        return {"status":"accepted_current","decision":calculated["decision"],"result":e["observation"]["result"]}
    except (ValueError,OSError,KeyError,TypeError,IndexError) as exc:
        return {"status":"unresolved","decision":None,"reason":str(exc)}


def eligibility(state, identity):
    if (required_for(state['contract']) or state['contract'].get('research_protocol_required')) and not state.get('methodology'):
        return ['protocol_unbound']
    if required_for(state['contract']) or state['contract'].get('research_protocol_required'):
        stages = state['methodology']['stages']
        pending = [r['id'] for r in stages[:2] if r['status'] not in {'done', 'not_applicable'}]
        if pending:
            return ['required research methodology stages incomplete: ' + ', '.join(pending)]
        if state['methodology']['preregistration'] is None:
            return ['prospective research preregistration and evaluator pins required']
    allocation_errors = _allocation_errors(state, identity) if (required_for(state['contract']) or state['contract'].get('research_protocol_required')) else []
    bound=_bound(state)
    if bound is None:return allocation_errors
    protocol,event=bound; stages=_stage_ids(protocol,identity)
    comp=next((c for c in protocol["comparisons"] if c["experiment_id"]==identity),None)
    if not stages and comp is None: return ["experiment absent from complete staged protocol"]
    reasons=list(allocation_errors)
    if comp is not None:
        try:_comparison_request(state,protocol,event,comp)
        except (ValueError,OSError,KeyError,TypeError) as exc:reasons.append(str(exc))
    for stage in stages:
        if stage['purpose'] == 'screen':
            reasons.extend(_screen_errors(state, identity, event))
        if stage['purpose'] == 'confirm':
            receipt, reads = _selection_state(state)
            reasons.extend(confirmation_errors(receipt, reads, {'candidate': stage['candidate']}))
        if not _stage_current(state,protocol,event,stage):reasons.append("stage source premise or material meta-objection reopened")
        for prerequisite in stage["requires_stages"]:
            row=next(s for s in protocol["stages"] if s["id"]==prerequisite)
            if any(r["status"]!="accepted_current" for r in _stage_rows(state,protocol,event,row)):
                reasons.append("stage requires complete current baseline/earlier-stage evidence: "+prerequisite)
        for req in stage["requires"]:
            c=next(c for c in protocol["comparisons"] if c["id"]==req["comparison_id"])
            current=_comparison_current(state,protocol,event,c)
            if current["status"]!="accepted_current" or current["decision"] not in req["allowed_decisions"]:
                reasons.append("promotion requires current scoped comparison: "+c["id"]+" ("+current["status"]+")")
    return reasons


def admit_design(state, experiment):
    if (required_for(state['contract']) or state['contract'].get('research_protocol_required')) and not state.get('methodology'):
        raise ValueError('protocol_unbound')
    if required_for(state['contract']) or state['contract'].get('research_protocol_required'):
        stages = state['methodology']['stages']
        if any(r['status'] not in {'done', 'not_applicable'} for r in stages[:2]):
            raise ValueError('limitation census and parallel ideas required before experiment design')
        if state['methodology']['preregistration'] is None:
            raise ValueError('research preregistration required before experiment design')
    bound=_bound(state)
    if bound is None:return
    protocol,event=bound; stages=_stage_ids(protocol,experiment["id"])
    comp=next((c for c in protocol["comparisons"] if c["experiment_id"]==experiment["id"]),None)
    if not stages and comp is None:raise ValueError("new design must retain complete staged protocol membership")
    spec=_json(experiment["study"],state["base_dir"])
    study_path, _ = _cycle()._check_pin(experiment["study"], state["base_dir"])
    dependencies={p["path"]:p for p in [_cycle()._pin(p) for p in _cycle().science.task_inputs(spec,study_path.parent)]}
    if comp is not None:
        if spec["mode"]!="research-comparison" or experiment["acceptance_scope"]!=comp["acceptance_scope"]:
            raise ValueError("comparison needs distinct ordinary operation and declared scientific scope")
        expected=_comparison_request(state,protocol,event,comp)
        if _json(spec["task"]["request"],state["base_dir"])!=expected:raise ValueError("prospective comparison request differs")
    for stage in stages:
        if experiment["acceptance_scope"]!=stage["acceptance_scope"]:raise ValueError("stage scientific scope differs")
        candidate=next(c for c in protocol["candidates"] if c["id"]==stage["candidate"])
        cells={c["id"]:c for c in protocol["cells"]}
        required=[*candidate["components"].values(),*candidate["invariant_inputs"]]
        for row in stage["cells"]:
            if row["experiment_id"]==experiment["id"]:required.extend([cells[row["cell_id"]]["population"],cells[row["cell_id"]]["normalization"]])
        for pin in _pins(required,state["base_dir"]):
            if dependencies.get(pin["path"])!=pin:raise ValueError("candidate source/cohort/normalization must be ordinary execution input")


def _active_holds(state, claim_id):
    resolved = {r for e in state["events"] if e["kind"] == "protocol_meta_review_applied" and e["action"] == "resolve_objections" for r in e["resolves_meta_revisions"]}
    return [e for e in state["events"] if e["kind"] == "protocol_meta_review_applied" and
            claim_id in e["affected_claim_ids"] and e["action"] not in {"report_only", "resolve_objections"} and e["revision"] not in resolved]


def _replacement(state, rows, identity, complete, field):
    """Fresh resolution discharges an old obligation, without restoring old evidence."""
    for resolution in reversed(state["events"]):
        if resolution["kind"] != "protocol_meta_review_applied" or resolution["action"] != "resolve_objections": continue
        for new_id in resolution[field]:
            row = rows[new_id]; seen = set()
            while row["replaces"] is not None and row["id"] not in seen:
                seen.add(row["id"])
                if row["replaces"] == identity and complete(new_id): return new_id
                row = rows[row["replaces"]]
    return None


def _full_preferences(protocol, comps, valid):
    """Keep local contrasts separate from complete, compatible pair preference."""
    full = {s['id']:s for s in protocol['stages'] if s['purpose'] == 'full'}
    obligations = {candidate:{(s['id'],r['cell_id']) for s in full.values()
        if s['candidate'] == candidate for r in s['cells']} for candidate in valid}
    local = []; pairs = {}
    for c in protocol['comparisons']:
        if c['left_stage'] not in full or c['right_stage'] not in full:continue
        left,right = full[c['left_stage']],full[c['right_stage']]
        if left['candidate'] == right['candidate']:continue
        measured = comps[c['id']]
        row = {'comparison_id':c['id'],'left_stage':left['id'],'right_stage':right['id'],
            'left_candidate':left['candidate'],'right_candidate':right['candidate'],
            'cell_ids':sorted(r['cell_id'] for r in left['cells']),
            'status':measured['status'],'decision':measured['decision'],
            'rule':c['rule'],'acceptance_scope':c['acceptance_scope']}
        local.append(row)
        pair = tuple(sorted((left['candidate'],right['candidate'])))
        if set(pair) <= valid:pairs.setdefault(pair,[]).append(row)
    dominance = []
    for pair, rows in sorted(pairs.items()):
        # Neither uncovered full stages nor incompatible rule/scope choices
        # can be silently discarded from a candidate-level preference.
        policies = {ce.digest({'rule':r['rule'],'scope':r['acceptance_scope']}) for r in rows}
        if len(policies) != 1 or any(r['status'] != 'accepted_current' for r in rows):continue
        covered = {candidate:set() for candidate in pair}; decisions = []
        for r in rows:
            for side in ('left','right'):
                covered[r[side+'_candidate']].update((r[side+'_stage'],cid) for cid in r['cell_ids'])
            decision = r['decision']
            if r['left_candidate'] != pair[0]:decision = {'better':'worse','worse':'better'}.get(decision,decision)
            decisions.append(decision)
        if any(covered[candidate] != obligations[candidate] for candidate in pair):continue
        if set(decisions) <= {'better','equivalent'} and 'better' in decisions:winner,loser = pair
        elif set(decisions) <= {'worse','equivalent'} and 'worse' in decisions:loser,winner = pair
        else:continue
        dominance.append({'comparison_id':rows[0]['comparison_id'] if len(rows)==1 else None,
            'comparison_ids':sorted(r['comparison_id'] for r in rows),
            'preferred_candidate':winner,'other_candidate':loser,
            'complete_full_stage_cells':{candidate:[{'stage_id':s,'cell_id':cid} for s,cid in sorted(obligations[candidate])] for candidate in pair},
            'rule':rows[0]['rule'],'acceptance_scope':rows[0]['acceptance_scope']})
    return local,dominance


def status_state(state):
    bound=_bound(state)
    if bound is None:return None
    protocol,event=bound
    stages={s["id"]:_stage_rows(state,protocol,event,s) for s in protocol["stages"]}
    comps={c["id"]:_comparison_current(state,protocol,event,c) for c in protocol["comparisons"]}
    claims=[]
    for c in protocol["claims"]:
        held=_active_holds(state,c["id"])
        try:comparison._snapshot(c['acceptance_criteria'],state['base_dir']);criteria_current=True
        except (ValueError,OSError):criteria_current=False
        current=(criteria_current and not held and _cycle()._fresh(state,event["row_premise_bindings"]["claims:"+c["id"]]) and
                 all(all(r["status"]=="accepted_current" for r in stages[s]) for s in c["stage_ids"]) and
                 all(comps[i]["status"]=="accepted_current" and comps[i]["decision"]!="unknown" for i in c["comparison_ids"]))
        claims.append({"id":c["id"],"report_slot":c["report_slot"],"current_evidence_complete":current,"meta_objections_retained":held})
    stage_map = {r["id"]:r for r in protocol["stages"]}; comp_map = {r["id"]:r for r in protocol["comparisons"]}; claim_map = {r["id"]:r for r in protocol["claims"]}
    stage_complete = lambda i: all(r["status"] == "accepted_current" for r in stages[i])
    comp_complete = lambda i: comps[i]["status"] == "accepted_current" and comps[i]["decision"] != "unknown"
    claim_complete = lambda i: next(r["current_evidence_complete"] for r in claims if r["id"] == i)
    replacements = {"stages":{}, "comparisons":{}, "claims":{}}
    for name, rows, complete, field in (("stages",stage_map,stage_complete,"replacement_stage_ids"),
        ("comparisons",comp_map,comp_complete,"replacement_comparison_ids"),("claims",claim_map,claim_complete,"replacement_claim_ids")):
        for identity in rows:
            if not complete(identity):
                replacement = _replacement(state,rows,identity,complete,field)
                if replacement is not None: replacements[name][identity] = replacement
    for c in claims:
        c["fulfilled_by"] = replacements["claims"].get(c["id"])
        c["reporting_obligation_complete"] = not _active_holds(state,c["id"]) and (c["current_evidence_complete"] or c["fulfilled_by"] is not None)
    missing_stages=[i for i in protocol["required_stage_ids"] if not stage_complete(i) and i not in replacements["stages"]]
    missing_comps=[i for i in protocol["required_comparison_ids"] if not comp_complete(i) and i not in replacements["comparisons"]]
    full_candidates = {s['candidate'] for s in protocol['stages'] if s['purpose'] == 'full'}
    valid = {candidate for candidate in full_candidates if all(stage_complete(s['id']) for s in protocol['stages']
        if s['purpose'] == 'full' and s['candidate'] == candidate)}
    local,dominance = _full_preferences(protocol,comps,valid)
    nondominated = sorted(valid - {r["other_candidate"] for r in dominance if r["preferred_candidate"] in valid})
    return {"kind":"staged_research_protocol_status","protocol":event["protocol"],"stages":stages,"comparisons":comps,"claims":claims,
            "missing_required_stages":missing_stages,"missing_required_comparisons":missing_comps,
            "complete_scientific_evidence":not missing_stages and not missing_comps and all(c["reporting_obligation_complete"] for c in claims),
            "replacement_obligations":replacements,"incumbent_options":{"valid_full_candidate_ids":sorted(valid),"undominated_candidate_ids":nondominated,"reviewed_dominance":dominance,
                "reviewed_local_contrasts":local,
                "policy":"Candidate preference requires compatible current comparisons covering every full stage/cell of both candidates. Local, uncovered, conflicting or incompatible contrasts leave choices unresolved. An invalid incumbent is never restored because a repair failed."},
            "candidate_count":len(protocol["candidates"]),"full_stage_cell_denominator":sum(len(s["cells"]) for s in protocol["stages"]),
            "complete_exposures":[{"id":c["id"],"exposure":c["exposure"],"regime":c["regime"],"fidelity":c["fidelity"]} for c in protocol["cells"]],
            "quantitative_checks":[{"experiment_id":e["id"],"evidence":deepcopy(e["observation"].get("quantitative_evidence")),"diagnostic_not_stage_acceptance":True} for e in state["experiments"] if e.get("observation") is not None and "quantitative_evidence" in e["observation"]],
            "not_applicable":protocol["not_applicable"],"execution_authorized":False,"physics_validated":False,"benefit_measured":False}


def status(root):return status_state(_cycle()._load(root)[1])


def prepare_comparison(root, comparison_id, study_template, output_dir, *, predictions):
    cycle=_cycle(); _,state=cycle._load(root);bound=_bound(state)
    if bound is None:raise ValueError("bound prospective protocol required")
    protocol,event=bound;comp=next(c for c in protocol["comparisons"] if c["id"]==comparison_id)
    request=_comparison_request(state,protocol,event,comp)
    out=cycle._ordinary(output_dir)
    out.mkdir(exist_ok=False)
    state_io.atomic_json(out/'comparison-request.json',request)
    request_pin=cycle._pin(out/'comparison-request.json')
    template=deepcopy(study_template)
    if template["schema_version"]!=2 or template["max_attempts"]!=1 or template["mode"]!="research-comparison" or template["task"]!={}:
        raise ValueError("prospective ordinary comparison v2 template with empty task required")
    if 'goal_binding' in state['contract']:
        parent = state['contract']['goal_binding']
        if 'goal_binding' in template and template['goal_binding'] != parent:
            raise ValueError('comparison must retain the exact original parent assignment')
        template['goal_binding'] = deepcopy(parent)
    template["task"]={"schema_version":1,"request":request_pin}
    cycle.science.validate(template);state_io.atomic_json(out/'study.json',template)
    study_pin=cycle._pin(out/'study.json')
    experiment={"id":comp["experiment_id"],"question":"Compare the complete fixed evaluation matrix under its prospective rule.",
        "premise_ids":sorted({p for c in _basis(protocol,comp)["candidates"] for p in c["premise_ids"]} | {p for c in _basis(protocol,comp)["cells"] for p in c["premise_ids"]}),
        "parent":None,"change":"Evaluate both complete operands without aggregation over missing cells.","study":study_pin,
        "cost":{"calls":0,"output_tokens":0,"wall_seconds":template["max_seconds"],"native_attempts":1},"predictions":predictions,
        "observable":{"pointer":"/decision","outcomes":{d:d for d in sorted(DECISIONS)}},"context_outputs":{},
        "acceptance_scope":comp["acceptance_scope"],"exploratory":False}
    admit_design(state,experiment)
    cycle._verify_preregistration(root,state)
    if _comparison_request(cycle._load(root)[1],protocol,event,comp)!=request:raise ValueError("comparison source changed during preparation")
    pins=[request_pin,study_pin]
    for pin in pins:cycle._check_pin(pin,out)
    return {"kind":"ordinary_research_comparison_design","experiment":experiment,"generated_pins":pins,
            "ordinary_plan_approval_roles_still_required":True,"execution_authorized":False}


def context(root, *, presentation="inline", evidence_pages=None, role="critic", max_presented_bytes=ce.MAX_BYTES, manuscript_action_plan=None):
    if manuscript_action_plan is not None and presentation != "inline":
        raise ValueError("manuscript actions require complete inline meta context; no indexed omission")
    if presentation == "indexed":
        from .research_presentation import prepared
        return prepared(root, evidence_pages=evidence_pages, role=role, max_presented_bytes=max_presented_bytes)[2]
    if presentation != "inline" or evidence_pages is not None:
        raise ValueError("explicit supported presentation required")
    _,state=_cycle()._load(root)
    from .research_followup import _feedback_content
    feedback = []
    for e in state["experiments"]:
        if e["adjudication"] is not None or e.get("diagnostic_feedback") is not None:
            _, content, _, roles, _ = _feedback_content(root, e["id"])
            feedback.append({"experiment_id": e["id"], "feedback": content, "actual_role_content": roles})
    value = {"kind":"staged_protocol_review_context","state_sha256":state["sha256"],"question":state["contract"]["question"],
        "scope":state["contract"]["scope"],"protocol_status":status_state(state),
        "actual_feedback":feedback,
        "current_goal":state.get('parent_task'),"resource_ledger":state["resource_ledger"],"timing":state["timing"],
        "source_inputs":input_pins(root),
        "hypotheses":state["hypotheses"],"premises":state["premises"],"protocol":None if _bound(state) is None else _bound(state)[0],
        "actions":["report_only","additional_evidence","candidate_revision","premise_revision","resolve_objections"],
        "instructions":instruction('meta_context')}
    if manuscript_action_plan is not None:
        from . import manuscript_workflow
        supplement,pins=manuscript_workflow.action_context(manuscript_action_plan,base_dir=state['base_dir'],campaign=root)
        value['manuscript_actions']=supplement
        value['source_inputs']=_pins([*value['source_inputs'],*pins],state['base_dir'])
    if len(__import__('json').dumps(value, allow_nan=False).encode()) > ce.MAX_BYTES:
        raise ValueError("complete protocol context exceeds bound; no truncation")
    if _cycle()._load(root)[1]["sha256"] != state["sha256"]:
        raise ValueError("research changed during meta context preparation")
    return value


def prepare_meta_review(root, output_dir, *, role, model, reasoning_effort, max_output_tokens, max_wall_seconds,
                        presentation="inline", evidence_pages=None, max_presented_bytes=ce.MAX_BYTES, adapter="responses", manuscript_action_plan=None):
    """Create a fresh role packet and a normal Graph, not a review vote or dispatch."""
    if adapter not in {*provider_transport.HTTP_MODEL_ACTIONS, 'external'}:
        raise ValueError("isolated model or host-attested external meta-review adapter required")
    if manuscript_action_plan is not None and presentation!='inline':raise ValueError('manuscript action meta context requires whole inline presentation')
    if presentation not in {'inline','indexed'} or presentation == 'inline' and evidence_pages is not None:
        raise ValueError('supported explicit presentation required')
    from . import research_presentation as material
    cycle=_cycle();_,state=cycle._load(root);bound=_bound(state)
    if bound is None or role not in {'critic','verifier'}:raise ValueError('bound protocol and separate meta-role required')
    if manuscript_action_plan is not None:
        from . import manuscript_workflow
        action=manuscript_workflow.verify_actions(manuscript_action_plan,base_dir=state['base_dir'],campaign=root)
        if not any(r['kind'] in {'empirical','core-method'} for r in action['plan']['actions']):raise ValueError('no scientific meta call for purely editorial actions')
        manuscript_workflow._action_allowance(action,{'calls':1,'output_tokens':max_output_tokens,'wall_seconds':max_wall_seconds,'native_attempts':0})
    if presentation == 'indexed':
        from . import research_presentation as material
        state,value,pins,manifest,manifest_pin,selected=material.packet(root,output_dir,role=role,
            evidence_pages=evidence_pages,max_presented_bytes=max_presented_bytes)
        out=cycle._ordinary(output_dir);packet=out/'context';subject=pins['public_case']
        copied=[p for k,p in pins.items() if k!='public_case'];required=None
    else:
        value=context(root,manuscript_action_plan=manuscript_action_plan);out=cycle._ordinary(output_dir);out.mkdir(exist_ok=False)
        packet=out/'context';(packet/'artifacts').mkdir(parents=True)
        subject=material.write_json_new(packet/'artifacts/subject.json',value)
        manifest={'schema_version':1,'role':role,'cycle_id':'protocol:'+bound[0]['id'],'source_event_sha256':state['sha256'],
            'findings':[],'reviews':[],'allowed_claim_scopes':{},'required_checks':[], 'omissions':[], 'correction':None,
            'verification_scope':'Methodological meta-review; preserves previous actual role feedback, no current peer meta-response or scientific vote authority.',
            'artifacts':[{'id':'subject','path':'artifacts/subject.json','sha256':subject['sha256'],'size':subject['size'],
                'source_sha256':subject['sha256'],'source_path':subject['path'],'projection':'complete_prospective_protocol_context'}]}
        # Meta reviewers receive actual source/evidence content through the normal
        # role packet, without extra raw Graph inputs or another role's new answer.
        total=subject['size'];copied=[];required=value['source_inputs']
        for i,pin in enumerate(required):
            path,raw,actual=comparison._snapshot(pin,state['base_dir'],limit=ce.MAX_BYTES)
            raw.decode('utf-8');total+=len(raw)
            if total>ce.MAX_BYTES:raise ValueError('complete meta source/evidence packet exceeds bound; no truncation')
            identity='basis'+str(i);relative='artifacts/'+identity+'.txt'
            copied.append(material.write_new(packet/relative,raw))
            manifest['artifacts'].append({'id':identity,'path':relative,'sha256':actual['sha256'],'size':actual['size'],
                'source_sha256':actual['sha256'],'source_path':actual['path'],'projection':'full_authenticated_source_or_evidence'})
        manifest['sha256']=cycle.science.execution.digest(manifest)
        manifest_pin=material.write_json_new(packet/'manifest.json',manifest)
    schema={'type':'object','required':['kind','subject_sha256','actor_id','action','affected_claim_ids','affected_stage_ids','objections','required_experiment_ids','premise_revision',
        'resolves_meta_revisions','replacement_stage_ids','replacement_comparison_ids','replacement_claim_ids'],'additionalProperties':False,
        'properties':{k:{'type':'string'} for k in ('kind','subject_sha256','actor_id','action')}}
    schema['properties'].update({k:{'type':'array','items':{'type':'string'}} for k in ('affected_claim_ids','affected_stage_ids','required_experiment_ids','replacement_stage_ids','replacement_comparison_ids','replacement_claim_ids')})
    object_schema=lambda fields:{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
    source_pin=object_schema({'path':{'type':'string'},'sha256':{'type':'string'},'size':{'type':'integer'}})
    premise=object_schema({'id':{'type':'string'},'statement':{'type':'string'},'basis':{'type':'array','items':source_pin},'reason':{'type':'string'}})
    premise['type']=['object','null']
    schema['properties'].update({'resolves_meta_revisions':{'type':'array','items':{'type':'integer'}},
        'objections':{'type':'array','items':object_schema({'location':{'type':'string'},'statement':{'type':'string'}})},'premise_revision':premise})
    if presentation == 'indexed':
        schema['required'].append('evidence_citations')
        schema['properties']['evidence_citations']={'type':'array','items':object_schema({
            'artifact_id':{'type':'string'},'sha256':{'type':'string'},'location':{'type':'string'}})}
    actor=bound[0]['meta_actors'][role]
    spec={'schema_version':1,'graph_id':'meta-'+role,'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':max_output_tokens,'max_wall_seconds':max_wall_seconds,'max_reworks':0},
        'nodes':[{'id':'meta','kind':'model','role':role,'depends_on':[],'inputs':[],'packet':{'path':str(packet),'manifest_sha256':manifest['sha256']},
            'action':adapter,'parameters':{'model':model,'reasoning_effort':reasoning_effort,'max_output_tokens':max_output_tokens,'output_schema':schema,
                'instructions':instruction('meta_review').format(subject=subject['sha256'], actor=actor)},'max_attempts':1}]}
    cycle.agent_graph.validate(spec);spec_pin=material.write_json_new(out/'graph-spec.json',spec)
    if cycle._load(root)[1]['sha256']!=state['sha256']:raise ValueError('research changed during meta-role preparation')
    if presentation == 'indexed':
        ending=material.prepared(root,evidence_pages=evidence_pages,role=role,max_presented_bytes=max_presented_bytes)[2]
        if ending!=value:raise ValueError('whole indexed evidence changed during meta-role preparation')
    elif context(root,manuscript_action_plan=manuscript_action_plan)['source_inputs']!=required:raise ValueError('ordinary source input closure changed during meta-role preparation')
    for pin in [subject,spec_pin,manifest_pin,*copied]:comparison._snapshot(pin,state['base_dir'])
    if manuscript_action_plan is not None:
        manuscript_workflow._register_action_graph(manuscript_action_plan,out/'graph',spec,base_dir=state['base_dir'],campaign=root,kind='meta')
    return {'context':subject,'graph_spec':spec_pin,'graph_root':str(out/'graph'),'actor_id':actor,'role':role,'execution_authorized':False}


def apply_meta_review(root, *, graph_root, node_id, context_pin, allow_control=False):
    cycle=_cycle();_,state=cycle._load(root);bound=_bound(state)
    if bound is None:raise ValueError("staged protocol required")
    protocol,event=bound;presented=_json(context_pin,state["base_dir"])
    indexed = presented.get('kind') == 'indexed_staged_protocol_review_context'
    options = presented.get('presentation_options', {}) if indexed else {}
    manuscript_plan=presented.get('manuscript_actions',{}).get('action_plan')
    if indexed and manuscript_plan is not None:raise ValueError('indexed manuscript action context is unsupported; no omitted evidence')
    current = context(root, presentation='indexed', **options) if indexed else context(root,manuscript_action_plan=manuscript_plan)
    projection = lambda x: {k:v for k,v in x.items() if k not in {"state_sha256", "resource_ledger", "timing"}}
    if projection(presented) != projection(current): raise ValueError("current exact whole-protocol meta context required")
    prior = [r for r in state["resource_ledger"] if r["id"] != "graph:" + str(cycle._ordinary(graph_root))]
    if presented["resource_ledger"] != prior: raise ValueError("meta context must retain all pre-existing resource reservations")
    graph=cycle._graph_result(graph_root,node_id)
    application = {k:graph[k] for k in ('root','node_id','generation','binding_sha256')}
    result_path = comparison._census([graph['receipt']],state['base_dir'])[0]['path']
    if str(cycle._ordinary(graph_root)) not in {g["root"] for g in state["graphs"]}:raise ValueError("meta-review must retain existing cumulative Graph charge")
    if manuscript_plan is not None:
        from . import manuscript_workflow
        original_spec=cycle.agent_graph._load(Path(graph_root))[0]
        ceilings=original_spec['budget']
        manuscript_workflow._action_graph_admission(root,state,cycle._ordinary(graph_root),original_spec,
            {'calls':ceilings['max_calls'],'output_tokens':ceilings['max_output_tokens'],'wall_seconds':ceilings['max_wall_seconds'],'native_attempts':0},reserved=True,require_registered=True)
    receipt=cycle.agent_graph.model_receipt(graph_root,node_id,expected_subject_sha256=context_pin["sha256"],require_exact_subject=True)
    if receipt['context_manifest_sha256'] is None:raise ValueError('explicit fresh role context required')
    if not indexed and any(p['sha256'] not in receipt['presented_subject_sha256s'] for p in current['source_inputs']):
        raise ValueError('complete actual ordinary source input contents must be presented to meta role')
    if receipt["execution_observation"] not in {"remote_transport_observed", "local_transport_observed","host_attested_external"} and not allow_control:
        raise ValueError("fresh separately observed meta-role required")
    # Retain old-epoch applications too; no recapture or new round for an
    # already consumed saved result. State freshness below covers concurrency.
    for old in state['events']:
        if old['kind'] != 'protocol_meta_review_applied':continue
        same_node = old.get('graph_binding') == application
        same_result = comparison._census([old['graph']],state['base_dir'])[0]['path'] == result_path
        if same_node or same_result:raise ValueError('exact meta Graph/node result already consumed')
    value=graph["value"]["value"]
    ce.keys(value,("kind","subject_sha256","actor_id","action","affected_claim_ids","affected_stage_ids","objections","required_experiment_ids","premise_revision",
                   "resolves_meta_revisions","replacement_stage_ids","replacement_comparison_ids","replacement_claim_ids",
                   *(["evidence_citations"] if indexed else [])))
    if value["kind"]!="research_meta_review" or value["subject_sha256"]!=context_pin["sha256"] or value["actor_id"]!=protocol["meta_actors"][receipt["role"]]:raise ValueError("actual meta actor/subject differs")
    if value["action"] not in presented["actions"]:raise ValueError("typed meta action required")
    presentation_receipt = None
    if indexed:
        from . import research_presentation as material, review_context
        graph_spec=cycle.agent_graph._load(Path(graph_root))[0]
        node=next(n for n in graph_spec['nodes'] if n['id']==node_id)
        packet_root=Path(node['packet']['path'])
        index=review_context._PacketIndex(packet_root,expected_manifest_sha256=receipt['context_manifest_sha256'])
        presentation_receipt=material.validate_citations(value,presented,index.manifest,receipt,packet_root)
        index.finish()

    claims={c["id"]:c for c in protocol["claims"]};_list_ids(value["affected_claim_ids"],claims,empty=False)
    stages = {s["id"]:s for s in protocol["stages"]};comps={c["id"]:c for c in protocol["comparisons"]}
    permitted = {s for i in value["affected_claim_ids"] for s in claims[i]["stage_ids"]} | {comps[c][k] for i in value["affected_claim_ids"] for c in claims[i]["comparison_ids"] for k in ("left_stage","right_stage")}
    if manuscript_plan is not None:
        permitted.update(i for r in current["manuscript_actions"]["actions"] for i in r["protocol_stage_ids"])
    _list_ids(value["affected_stage_ids"],permitted)
    if type(value["objections"]) is not list or not 1<=len(value["objections"])<=16:raise ValueError("located material objections required")
    for o in value["objections"]:
        ce.keys(o,("location","statement"));cycle._text(o["location"]);cycle._text(o["statement"])
    declared_experiments = {r["experiment_id"] for s in protocol["stages"] for r in s["cells"]} | {c["experiment_id"] for c in protocol["comparisons"]}
    _list_ids(value["required_experiment_ids"],declared_experiments)
    if value['action']=='additional_evidence' and not value['required_experiment_ids']:
        raise ValueError('additional evidence needs explicit fresh ordinary test obligations')
    if value["action"]=="premise_revision":
        ce.keys(value["premise_revision"],("id","statement","basis","reason"))
        p=value["premise_revision"]
        if p["id"] not in {r["id"] for r in state["premises"]}:raise ValueError("existing premise identity required")
        cycle._text(p["statement"]);cycle._text(p["reason"]);_pins(p["basis"],state["base_dir"])
    elif value["premise_revision"] is not None:raise ValueError("only premise revision can change a premise")
    resolution_fields = ("resolves_meta_revisions","replacement_stage_ids","replacement_comparison_ids","replacement_claim_ids")
    if value["action"] == "resolve_objections":
        prior = {e["revision"]:e for e in state["events"] if e["kind"] == "protocol_meta_review_applied" and e["action"] not in {"report_only","resolve_objections"}}
        _list_ids(value["resolves_meta_revisions"],prior,empty=False)
        if any(type(i) is not int for i in value["resolves_meta_revisions"]):raise ValueError("exact prior meta revision required")
        affected = {i for r in value["resolves_meta_revisions"] for i in prior[r]["affected_claim_ids"]}
        if affected != set(value["affected_claim_ids"]):raise ValueError("whole prior affected claim census required")
        active = {e["revision"] for i in affected for e in _active_holds(state,i)}
        if active != set(value["resolves_meta_revisions"]):raise ValueError("all currently open objections must be addressed exactly once")
        required = {i for r in active for i in prior[r]["required_experiment_ids"]}
        if not required <= set(value["required_experiment_ids"]):raise ValueError("all requested objection tests remain obligations")
        by_id = {e["id"]:e for e in state["experiments"]}
        for identity in value["required_experiment_ids"]:
            if identity not in by_id:raise ValueError("actual objection-test result required before resolution")
            cycle._current_evidence(state,by_id[identity],accepted=True)
            if not cycle._applicability(state,by_id[identity])["measurement"]:raise ValueError("current objection-test applicability required")
            for revision in active:
                old=prior[revision]['required_evidence_at_objection'].get(identity)
                now={'observation':by_id[identity]['observation'],'adjudication':by_id[identity]['adjudication']}
                if identity in prior[revision]['required_experiment_ids'] and old==now:
                    raise ValueError('additional-evidence request cannot close using the same prior output and votes')
        view=status_state(state)
        for field, rows, complete in (("replacement_stage_ids",{s["id"]:s for s in protocol["stages"]},lambda i:all(r["status"]=="accepted_current" for r in view["stages"][i])),
            ("replacement_comparison_ids",{c["id"]:c for c in protocol["comparisons"]},lambda i:view["comparisons"][i]["status"]=="accepted_current" and view["comparisons"][i]["decision"]!="unknown"),
            ("replacement_claim_ids",claims,lambda i:next(c["current_evidence_complete"] for c in view["claims"] if c["id"]==i))):
            _list_ids(value[field],rows)
            if any(rows[i]["replaces"] is None or not complete(i) for i in value[field]):raise ValueError("fresh complete exact replacement evidence required")
        invalidated = {s for r in active for s in prior[r]["invalidated_stage_ids"]}
        replaced = {next(s for s in protocol["stages"] if s["id"]==i)["replaces"] for i in value["replacement_stage_ids"]}
        if not invalidated <= replaced:raise ValueError("all invalidated stage obligations need fresh replacements")
        if invalidated and {claims[i]["replaces"] for i in value["replacement_claim_ids"]} != affected:
            raise ValueError("invalidated original claims require exact replacement claims")
    elif any(value[k] != [] for k in resolution_fields):
        raise ValueError("only a fresh resolution can discharge previous objections")
    manuscript_pin=None
    if manuscript_plan is not None:
        from . import manuscript_workflow
        manuscript_pin=manuscript_workflow.validate_action_meta(manuscript_plan,value,base_dir=state['base_dir'],campaign=root)
    invalid=set()
    if value["action"] in {"candidate_revision","premise_revision"}:
        if not value["affected_stage_ids"]:raise ValueError("located material stage dependency required")
        invalid.update(value["affected_stage_ids"])
        changed=True
        while changed:
            previous=set(invalid)
            for s in protocol["stages"]:
                if any(comps[r["comparison_id"]][k] in invalid for r in s["requires"] for k in ("left_stage","right_stage")):invalid.add(s["id"])
            changed=invalid!=previous
    with state_io.file_lock(Path(root)/'operation.lock',blocking=False):
        _,fresh=cycle._load(root)
        if fresh['sha256']!=state['sha256']:raise ValueError("research state changed during meta admission")
        if sum(e['kind']=='protocol_meta_review_applied' for e in state['events'])>=protocol['round_limits']['meta_reviews']:raise ValueError("finite meta-review bound exhausted")
        if indexed and _context_projection(context(root,presentation='indexed',**options)) != _context_projection(presented):
            raise ValueError('indexed full evidence changed before meta commitment')
        if manuscript_pin is not None and _context_projection(context(root,manuscript_action_plan=manuscript_pin))!=_context_projection(presented):
            raise ValueError('whole manuscript action context changed before protocol commitment')
        by_id={e['id']:e for e in state['experiments']}
        evidence={i:None if i not in by_id else {'observation':by_id[i]['observation'],'adjudication':by_id[i]['adjudication']} for i in value['required_experiment_ids']}
        result=cycle._commit(Path(root),state,'protocol_meta_review_applied',action=value['action'],affected_claim_ids=value['affected_claim_ids'],
            affected_stage_ids=value['affected_stage_ids'],invalidated_stage_ids=sorted(invalid),required_experiment_ids=value['required_experiment_ids'],objections=value['objections'],graph=graph['receipt'],
            context=context_pin,role_receipt=receipt,graph_binding=application,control_only=receipt['execution_observation']=='control_only',old_votes_carried=False,
            required_evidence_at_objection=evidence,
            **({'manuscript_action_plan':manuscript_pin} if manuscript_pin is not None else {}),
            **({"presentation_receipt":presentation_receipt} if indexed else {}),
            **{k:value[k] for k in resolution_fields})
    if value['premise_revision'] is not None:
        p=value['premise_revision'];return cycle.revise_premise(root,p['id'],p['statement'],basis=p['basis'],reason=p['reason'])
    return result


def input_pins(root, *, presentation="inline"):
    """Complete custody inputs; indexed Host binds their authenticated inventory."""
    if presentation == "indexed":
        from .research_presentation import inventory
        return [r["pin"] for r in inventory(root)[1]["files"]]
    if presentation != "inline": raise ValueError("supported presentation required")
    cycle=_cycle();rd,state=cycle._load(root);bound=_bound(state)
    pins=[state['contract']['context_request']]
    for source in state['context']['source_inventory']:
        path=Path(source['path']);path=path if path.is_absolute() else Path(state['base_dir'])/path
        pins.append({**source,'size':path.stat().st_size})
    if state.get('parent_task') is not None:pins.extend(state['parent_task']['input_pins'])
    if bound is not None:pins.extend([bound[1]['protocol'],*_all_pins(bound[0])])
    for e in state['experiments']:
        pins.extend(e['input_pins'])
        if not cycle._failed_parent(e):pins.append(e['study'])
        if e.get('observation') is not None:
            pins.append(e['observation']['receipt'])
            if e['observation']['result'] is not None:pins.append(e['observation']['result'])
        if e.get('adjudication') is not None:pins.append(e['adjudication']['snapshot'])
        if e.get('failed_intake') is not None:pins.append(e['failed_intake'])
        if e.get('diagnostic_feedback') is not None:pins.append(e['diagnostic_feedback'])
    return _pins(pins,state['base_dir'])


def _context_projection(value):
    return {k:v for k,v in value.items() if k not in {'state_sha256','resource_ledger','timing'}}


def prepare_host_request(root, operation, parameters, graph_root, output_dir, *,
                         presentation='inline', evidence_pages=None, role='critic', max_presented_bytes=ce.MAX_BYTES):
    """Compact Graph inputs retain the full authenticated indexed closure."""
    from . import research_presentation as material
    cycle=_cycle();_,state=cycle._load(root)
    options={'evidence_pages':evidence_pages,'role':role,'max_presented_bytes':max_presented_bytes}
    subject=context(root,presentation=presentation,**options)
    required=input_pins(root) if presentation=='inline' else []
    out=cycle._ordinary(output_dir);out.mkdir(exist_ok=False)
    subject_pin=material.write_json_new(out/'subject.json',subject)
    request={'cycle_root':str(cycle._ordinary(root)),'operation':operation,'parameters':deepcopy(parameters),
             'subject':subject_pin,'graph_root':str(cycle._ordinary(graph_root))}
    if presentation=='indexed':
        from . import research_presentation as material
        _,inventory,failures,_=material.inventory(root)
        if material.core(root,inventory,failures,state)['inventory_commitment'] != subject['inventory_commitment']:
            raise ValueError('full indexed evidence differs during Host preparation')
        inventory_pin=material.write_new(out/'inventory.json',material.raw_json(inventory))
        commitment={'schema_version':1,'kind':'protocol_inventory_commitment','inventory':inventory_pin,'content_read_by_reviewer':False}
        commitment_pin=material.write_new(out/'inventory-commitment.json',material.raw_json(commitment))
        required=[commitment_pin]
        request.update(presentation='indexed',presentation_options=options,inventory=inventory_pin,inventory_commitment=commitment_pin)
    if operation in {'replication','replication-comparison'}:
        from . import fresh_replication
        closure=fresh_replication.input_pins(root,operation,parameters)
        replication_inputs=material.write_json_new(out/'replication-inputs.json',
            {'schema_version':1,'kind':'replication_operational_custody','inputs':closure,'content_read_by_reviewer':False})
        request['replication_inputs']=replication_inputs
        required.append(replication_inputs)
    request_pin=material.write_json_new(out/'request.json',request)
    if cycle._load(root)[1]['sha256']!=state['sha256']:raise ValueError('research changed during subject preparation')
    for pin in [request_pin,subject_pin,*required,*([inventory_pin] if presentation=='indexed' else [])]:
        cycle._check_pin(pin,state['base_dir'])
    if _context_projection(context(root,presentation=presentation,**options))!=_context_projection(subject):
        raise ValueError('whole scientific evidence changed during Host preparation')
    return {'request':request_pin,'inputs':[request_pin,subject_pin,*required],'execution_authorized':False}


def host_prepare(request, *, presented_pins, base_dir):
    """One normal tool call; no state mutation, vote or nested dispatch."""
    indexed=request.get('presentation')=='indexed'
    ce.keys(request,('cycle_root','operation','parameters','subject','graph_root',
                    *(['presentation','presentation_options','inventory','inventory_commitment'] if indexed else []),
                    *(['replication_inputs'] if request.get('operation') in {'replication','replication-comparison'} else [])))
    options=request['presentation_options'] if indexed else {}
    if indexed:ce.keys(options,('evidence_pages','role','max_presented_bytes'))
    root=Path(request['cycle_root']);root=root if root.is_absolute() else Path(base_dir)/root
    cycle=_cycle();state=cycle._load(root)[1];before=state['sha256']
    required=[request['subject'],request['inventory_commitment']] if indexed else [request['subject'],*input_pins(root)]
    old=_json(request['subject'],base_dir)
    current=context(root,presentation='indexed',**options) if indexed else context(root)
    if _context_projection(old)!=_context_projection(current):raise ValueError('exact pre-reservation scientific subject required')
    if indexed:
        from .research_presentation import document,inventory,MAX_INVENTORY_BYTES
        commitment=document(request['inventory_commitment'],base_dir,ce.MAX_BYTES)
        if commitment!={'schema_version':1,'kind':'protocol_inventory_commitment','inventory':request['inventory'],'content_read_by_reviewer':False}:
            raise ValueError('exact complete inventory commitment required')
        if document(request['inventory'],base_dir,MAX_INVENTORY_BYTES)!=inventory(root)[1]:
            raise ValueError('exact whole current evidence inventory required')
    charge='graph:'+str(cycle._ordinary(request['graph_root']))
    pending=[r for r in state['resource_ledger'] if r['id']==charge]
    if len(pending)!=1 or old['resource_ledger']!=[r for r in state['resource_ledger'] if r['id']!=charge]:
        raise ValueError('exactly the current Graph reservation may follow subject preparation')
    presented=set()
    for p in presented_pins:
        path=Path(p['path']);path=path if path.is_absolute() else Path(base_dir)/path
        presented.add((str(cycle._ordinary(path)),p['sha256']))
    if any((p['path'],p['sha256']) not in presented for p in required):raise ValueError('complete subject/inventory must be normal Host inputs')
    if request['operation'] in {'replication','replication-comparison'}:
        from . import fresh_replication
        closure=fresh_replication.input_pins(root,request['operation'],request['parameters'])
        pin=request['replication_inputs'];path=Path(pin['path'])
        path=path if path.is_absolute() else Path(base_dir)/path
        if (str(cycle._ordinary(path)),pin['sha256']) not in presented:
            raise ValueError('complete replication inventory commitment must be a normal Host input')
        from .research_presentation import document,MAX_INVENTORY_BYTES
        intended={'schema_version':1,'kind':'replication_operational_custody','inputs':closure,'content_read_by_reviewer':False}
        if document(pin,base_dir,MAX_INVENTORY_BYTES)!=intended:
            raise ValueError('complete replication custody changed before actual Host preparation')
        required.append(pin)
    if request['operation']=='status':
        ce.keys(request['parameters'],());value=status(root)
    elif request['operation']=='context':
        ce.keys(request['parameters'],());value=current
    elif request['operation']=='progress':
        ce.keys(request['parameters'],('report_request',) if 'report_request' in request['parameters'] else ())
        value=cycle.progress_synthesis(root,base_dir=base_dir,report_request=request['parameters'].get('report_request'))
    elif request['operation']=='replication':
        from . import fresh_replication
        ce.keys(request['parameters'],('current_report_pin','method_id','output_dir','check_contract_pin'))
        p=request['parameters']
        value=fresh_replication.prepare_replication_request(root,p['current_report_pin'],p['method_id'],p['output_dir'],check_contract_pin=p['check_contract_pin'])
    elif request['operation']=='replication-comparison':
        from . import fresh_replication
        ce.keys(request['parameters'],('request_pin','output_dir'))
        p=request['parameters'];value=fresh_replication.prepare_comparison(root,p['request_pin'],p['output_dir'])
    elif request['operation']=='comparison':
        ce.keys(request['parameters'],('comparison_id','study_template','output_dir','predictions'))
        p=request['parameters'];value=prepare_comparison(root,p['comparison_id'],p['study_template'],p['output_dir'],predictions=p['predictions'])
    else:raise ValueError('finite protocol preparation operation required')
    if request['operation'] in {'replication','replication-comparison'}:
        ending=fresh_replication.input_pins(root,request['operation'],request['parameters'])
        if ending!=closure:raise ValueError('complete replication custody changed before Host return')
    if cycle._load(root)[1]['sha256']!=before:raise ValueError('research changed during protocol tool preparation')
    for pin in [*required,*([request['inventory']] if indexed else [])]:cycle._check_pin(pin,base_dir)
    if _context_projection(context(root,presentation='indexed',**options) if indexed else context(root))!=_context_projection(old):
        raise ValueError('current full evidence changed before Host return')
    return value


def main(argv=None):
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['bind','status','context','comparison','meta-prepare','meta','host-prepare',
        'methodology-status','preregister','register-concerns','stage-prepare','stage-complete','stage-run'])
    parser.add_argument('--cycle',required=True);parser.add_argument('--request');parser.add_argument('--out')
    args=parser.parse_args(argv);cycle=_cycle()
    if args.operation=='status':value=status(args.cycle)
    elif args.operation=='methodology-status':value=methodology_status(args.cycle)
    elif args.operation=='context':
        if not args.out:parser.error('--out required')
        options={} if args.request is None else cycle._cli_document(args.request)
        ce.keys(options,tuple(k for k in ('presentation','evidence_pages','role','max_presented_bytes') if k in options))
        value=context(args.cycle,**options);path=cycle._ordinary(args.out)
        if path.exists():raise FileExistsError('fresh context required')
        from .research_presentation import write_json_new
        value=write_json_new(path,value)
    else:
        if not args.request:parser.error('--request required')
        reader=getattr(cycle,'_cli_document',None)
        if reader is None:raise ValueError('reviewed bounded research-cycle command reader required in this source epoch')
        request=reader(args.request)
        if args.operation=='preregister':
            # The CLI never accepts a supplied preregistration: code derives it
            # from the campaign journal and the pinned prospective design record.
            ce.keys(request, ('design',))
            from .research_launch import produce_campaign
            value=produce_campaign(args.cycle, request['design'])
        elif args.operation=='register-concerns':
            ce.keys(request, ('request_pin',))
            value=register_concerns(args.cycle, **request)
        elif args.operation=='stage-prepare':
            ce.keys(request, ('stage_id','artifact','output_dir','model',
                *[k for k in ('reasoning_effort','adapter','max_output_tokens','max_wall_seconds') if k in request]))
            value=prepare_stage(args.cycle, **request)
        elif args.operation=='stage-complete':
            ce.keys(request, ('prepared','graph_root'))
            value=complete_stage(args.cycle, **request)
        elif args.operation=='stage-run':
            ce.keys(request, ('artifact','output_dir','settings'))
            from .agent_host import AgentHost
            from .research_orchestrator import run_protocol_stage
            if request['settings']['adapter'] != 'external':
                raise ValueError('stage-run CLI uses keyless external delivery; library accepts a configured Host')
            value=run_protocol_stage(args.cycle, **request, host=AgentHost())
        elif args.operation=='bind':
            ce.keys(request,('protocol_pin',));value=bind(args.cycle,request['protocol_pin'])
        elif args.operation=='comparison':
            ce.keys(request,('comparison_id','study_template','output_dir','predictions'))
            value=prepare_comparison(args.cycle,request['comparison_id'],request['study_template'],request['output_dir'],predictions=request['predictions'])
        elif args.operation=='meta-prepare':
            ce.keys(request,('output_dir','role','model','reasoning_effort','max_output_tokens','max_wall_seconds',
                            *[k for k in ('presentation','evidence_pages','max_presented_bytes','adapter','manuscript_action_plan') if k in request]))
            value=prepare_meta_review(args.cycle,**request)
        elif args.operation=='host-prepare':
            ce.keys(request,('operation','parameters','graph_root','output_dir',
                            *[k for k in ('presentation','evidence_pages','role','max_presented_bytes') if k in request]))
            value=prepare_host_request(args.cycle,**request)
        else:
            ce.keys(request,('graph_root','node_id','context_pin'))
            value=apply_meta_review(args.cycle,**request)
    print(json.dumps(value,sort_keys=True,allow_nan=False));return 0


def _finite_number(value, label):
    import math
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be finite')
    return value


def _exposure_identity(row):
    """Evaluator-owned data identities, distinct from candidate ancestry."""
    for key in ('cells', 'seeds'):
        if (type(row.get(key)) is not list or not row[key]
                or any(type(x) not in (str, int) or isinstance(x, bool) for x in row[key])
                or len({str(v) for v in row[key]}) != len(row[key])):
            raise ValueError('complete distinct exposure ' + key + ' required')
    _required_text(row.get('generation'), 'data generation')
    return {key: deepcopy(row[key]) for key in ('cells', 'seeds', 'generation')}


def holm(p_values, *, alpha=.05):
    """Holm step-down familywise correction in original candidate order."""
    if not 0 < _finite_number(alpha, 'alpha') < 1:
        raise ValueError('alpha must lie in (0, 1)')
    if not p_values or any(not 0 <= _finite_number(v, 'p value') <= 1 for v in p_values):
        raise ValueError('bounded p values required')
    accepted = [False] * len(p_values)
    for rank, index in enumerate(sorted(range(len(p_values)), key=lambda i: (p_values[i], i))):
        if p_values[index] > alpha / (len(p_values) - rank):
            break
        accepted[index] = True
    return accepted


def selection_receipt(request, *, base_dir, observed_rows=None):
    """Compute the full trial census and selected k from pinned select results.

    This pure evaluator interface grants no execution/review authority. Commit it
    with commit_selection before dispatching confirmation. Failed trials remain
    in N; their absent measurements cannot win the selection.
    """
    rule = request['rule']
    ce.keys(rule, {'direction', 'metric', 'k', 'alpha'} | ({'confirmation_criterion'} if 'confirmation_criterion' in rule else set()))
    criterion = rule.get('confirmation_criterion')
    if criterion is not None:
        if (not isinstance(criterion, dict) or not {'op', 'value'} <= set(criterion) <= {'op', 'value', 'exact'}
                or criterion['op'] not in {'ge', 'le', 'eq'}):
            raise ValueError('typed deterministic confirmation criterion required')
        _finite_number(criterion['value'], 'confirmation criterion')
        # A threshold applied to k > 1 noisy confirmations inflates false
        # confirmations; Holm needs p values. The deterministic exception is an
        # explicitly declared exact (noise-free) confirmation measurement.
        if type(rule.get('k')) is int and rule['k'] > 1 and criterion.get('exact') is not True:
            raise ValueError('k > 1 confirmation uses Holm p values; a deterministic criterion needs '
                             'a declared exact measurement (exact: true)')
    _required_text(rule['metric'], 'selection metric')
    if (rule['direction'] not in {'maximize', 'minimize'} or type(rule['k']) is not int
            or not 1 <= rule['k'] <= 8 or request['regime'] not in default_protocol()['regimes']):
        raise ValueError('bounded prospective selection rule required')
    holm([1.], alpha=rule['alpha'])
    trials = _ids(request['trials'], 128, 'full trial census')
    measured = []
    for trial in trials.values():
        ce.keys(trial, ('id', 'candidate', 'result'))
        row = (_method_json(trial['result'], base_dir) if observed_rows is None else
               next(r for r in observed_rows if r['id'] == trial['id']))
        if row.get('candidate') != trial['candidate']:
            raise ValueError('trial candidate differs from evaluator receipt')
        if row.get('status') not in {'success', 'failed', 'unresolved'}:
            raise ValueError('explicit trial execution status required')
        exposure = _exposure_identity(row)
        value = _finite_number(row.get('value'), 'selection measurement') if row['status'] == 'success' else None
        fidelity = row.get('exposure', 'adaptive_full')
        if fidelity not in {'adaptive_screen', 'adaptive_full'}:
            raise ValueError('confirm_cell_in_selection_inputs')
        measured.append({**deepcopy(trial), **exposure, 'value': value, 'status': row['status'], 'exposure': fidelity})
    # All evaluated attempts count in N. The fixed aggregation is arithmetic mean,
    # never the best seed; a failed full attempt makes that candidate unresolved.
    candidate_values = {}
    for candidate in sorted({r['candidate'] for r in measured}):
        own = [r for r in measured if r['candidate'] == candidate and r['exposure'] == 'adaptive_full']
        candidate_values[candidate] = (sum(r['value'] for r in own) / len(own)
            if own and all(r['status'] == 'success' for r in own) else None)
    sign = -1 if rule['direction'] == 'maximize' else 1
    eligible = sorted((c for c, v in candidate_values.items() if v is not None),
                      key=lambda c: (sign * candidate_values[c], c))
    selected = eligible[:rule['k']]
    value = {'schema_version': 1, 'kind': 'research-selection-receipt', 'rule': deepcopy(rule),
             'regime': request['regime'], 'N': len(trials), 'candidates_considered': len(candidate_values),
             'candidate_values': candidate_values, 'k': len(selected), 'selected': selected,
             'trials': measured, 'selection_inputs': [r['result'] for r in measured]}
    if observed_rows is not None:
        value['origin'] = 'experiment_observations'
    value['sha256'] = ce.digest(value)
    return value


def _verify_selection(receipt, base_dir=None):
    if not isinstance(receipt, dict) or receipt.get('kind') != 'research-selection-receipt':
        raise ValueError('confirm_read_before_selection')
    body = {k: v for k, v in receipt.items() if k != 'sha256'}
    if ce.digest(body) != receipt.get('sha256'):
        raise ValueError('selection receipt digest differs')
    if base_dir is not None:
        request = {'rule': receipt['rule'], 'regime': receipt['regime'],
                   'trials': [{k: r[k] for k in ('id', 'candidate', 'result')} for r in receipt['trials']]}
        if receipt.get('origin') == 'experiment_observations':
            for row in receipt['trials']:
                if row['result'] is not None: _method_pin(row['result'], base_dir)
        if selection_receipt(request, base_dir=base_dir, observed_rows=receipt['trials']
                             if receipt.get('origin') == 'experiment_observations' else None) != receipt:
            raise ValueError('selection receipt differs from source results')


def confirmation_errors(receipt, reads, action):
    """Read-only gate shared with the study-wide evaluator exposure ledger."""
    if receipt is None:
        return ['confirm_read_before_selection']
    _verify_selection(receipt)
    candidate = action.get('candidate')
    if candidate not in receipt['selected']:
        return ['confirm_reads_exceed_k']
    if any(key in action for key in ('cells', 'seeds', 'generation')):
        current = _exposure_identity(action)
        for previous in receipt['trials']:
            if (set(current['cells']) & set(previous['cells'])
                    or {str(s) for s in current['seeds']} & {str(s) for s in previous['seeds']}
                    or current['generation'] == previous['generation']):
                return ['confirm_cell_in_selection_inputs']
        for previous in reads:
            if previous.get('candidate') != candidate:
                continue
            if (not all(k in previous for k in ('cells', 'seeds', 'generation'))
                    or set(current['cells']) & set(previous['cells'])
                    or {str(s) for s in current['seeds']} & {str(s) for s in previous['seeds']}
                    or current['generation'] == previous['generation']):
                return ['confirm_reads_exceed_k']
    elif any(r.get('candidate') == candidate for r in reads):
        return ['confirm_reads_exceed_k']
    return []


def selection_report(receipt, confirmation_pins, *, base_dir, state=None):
    """Claim-record interface: selected measurements, trial denominator and null funnel.

    P values are supplied by the pinned evaluator; this layer never invents a
    likelihood, uncertainty or p value. k>1 always uses Holm, including failed
    confirmation attempts (p=1 for multiplicity accounting, never a measurement).
    """
    _verify_selection(receipt, base_dir)
    rows, reads = [], []
    if state is not None:
        from .research_evaluation import records
        voided = {e['read']['experiment_id'] for e in state['events'] if e['kind'] == 'research_confirmation_void'}
        observed = [r for r in records(state, purposes={'confirm'}) if r['id'] not in voided]
        if {(r['source'] or r['attempt'])['sha256'] for r in observed} != {p['sha256'] for p in confirmation_pins}:
            raise ValueError('confirmation census differs from recorded observations')
    for pin in confirmation_pins:
        if state is None:
            row = _method_json(pin, base_dir)
        else:
            matches = [r for r in observed if (r['source'] or r['attempt']) == pin]
            if len(matches) != 1: raise ValueError('confirmation requires recorded experiment observation')
            row = deepcopy(matches[0])
        errors = confirmation_errors(receipt, reads, row)
        if errors:
            raise ValueError(errors[0])
        _exposure_identity(row)
        success = row.get('status') == 'success'
        if row.get('status') not in {'success', 'failed', 'unresolved'}:
            raise ValueError('explicit confirmation execution status required')
        criterion = receipt['rule'].get('confirmation_criterion')
        if success:
            _finite_number(row.get('value'), 'confirmation measurement')
            if criterion is None and not 0 <= _finite_number(row.get('p_value'), 'confirmation p value') <= 1:
                raise ValueError('bounded confirmation p value required')
        reads.append({**_exposure_identity(row), 'candidate': row['candidate'], 'selection_sha256': receipt['sha256']})
        rows.append({**row, 'result': deepcopy(pin), 'p_value': None if criterion is not None else row['p_value'] if success else 1.})
    if {r['candidate'] for r in rows} != set(receipt['selected']):
        raise ValueError('every selected candidate requires a confirmation disposition')
    criterion = receipt['rule'].get('confirmation_criterion')
    if criterion is None:
        passed = holm([r['p_value'] for r in rows], alpha=receipt['rule']['alpha']) if rows else []
    else:
        op = {'ge': lambda a, b: a >= b, 'le': lambda a, b: a <= b, 'eq': lambda a, b: a == b}[criterion['op']]
        passed = [r['status'] == 'success' and op(r['value'], criterion['value']) for r in rows]
    promoted = [candidate for candidate in receipt['selected'] if all(accepted and r['status'] == 'success'
        for r, accepted in zip(rows, passed) if r['candidate'] == candidate)]
    return {'schema_version': 1, 'kind': 'research-selection-report', 'N': receipt['N'],
            'candidates_considered': receipt['candidates_considered'],
            'k': receipt['k'], 'selection_receipt': receipt['sha256'], 'trials': receipt['trials'],
            'best_of_N_select': ({'label': 'optimistic', 'candidate': receipt['selected'][0],
                'value': receipt['candidate_values'][receipt['selected'][0]]}
                if receipt['selected'] else {'label': 'optimistic', 'candidate': None, 'value': None}),
            'selected_result_on_confirm': rows, 'correction': ('deterministic_exact' if criterion is not None and len(rows) > 1
                else 'deterministic' if criterion is not None else 'Holm' if len(rows) > 1 else 'single'),
            'promoted': promoted, 'status': 'confirmed' if promoted else 'null_funnel',
            'deliverable': True, 'scientific_acceptance': False}


def commit_selection(root, request_pin):
    """Freeze select results in the existing hash journal before confirm reads."""
    cycle = _cycle()
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = cycle._load(root)
        if any(e['kind'] in {'research_selection', 'research_confirm_read'} for e in state['events']):
            raise ValueError('selection already frozen or confirmation exposed')
        request = _method_json(request_pin, state['base_dir'])
        from .research_evaluation import selection_request
        observed_rows = selection_request(state, request)
        receipt = selection_receipt(request, base_dir=state['base_dir'], observed_rows=observed_rows)
        if not state.get('methodology', {}).get('preregistration'):
            raise ValueError('prospective research preregistration required before selection')
        if state.get('methodology'):
            declaration = _method_json(state['methodology']['preregistration'], state['base_dir'])
            if declaration.get('selection_rule') != request['rule'] or state['methodology']['regime'] != request['regime']:
                raise ValueError('selection must use the prospectively registered rule and regime')
        bound = _bound(state)
        if bound:
            full = [s for s in bound[0]['stages'] if s['purpose'] == 'full']
            search = [s for s in bound[0]['stages'] if s['purpose'] in {'screen', 'full'}]
            expected = {s['candidate'] for s in search}
            cells = {c['id']: c for c in bound[0]['cells']}
            for trial in receipt['trials']:
                own = {r['cell_id'] for stage in full if stage['candidate'] == trial['candidate'] for r in stage['cells']}
                expected_exposure = 'adaptive_full' if own else 'adaptive_screen'
                if not own:
                    own = {r['cell_id'] for stage in search if stage['candidate'] == trial['candidate'] for r in stage['cells']}
                if trial['exposure'] != expected_exposure:
                    raise ValueError('screen-only trial cannot compete as full fidelity')
                if set(trial['cells']) != own or any(cells[c]['metric'] != request['rule']['metric'] for c in own):
                    raise ValueError('selection trial omits or substitutes bound full cells or metric')
                if any('seeds' in cells[c] for c in own):
                    if (set(trial['seeds']) != {seed for c in own for seed in cells[c]['seeds']}
                            or {trial['generation']} != {cells[c]['generation'] for c in own}):
                        raise ValueError('selection trial data identity differs from bound cells')
            if {r['candidate'] for r in receipt['trials']} != expected:
                raise ValueError('selection requires the entire bound candidate census')
            by_candidate = {r['candidate']: r for r in receipt['trials']}
            experiments = {e['id']: e for e in state['experiments']}
            for stage in full:
                trial = by_candidate[stage['candidate']]
                if trial['status'] == 'success':
                    if any(r['status'] != 'accepted_current' for r in _stage_rows(state, bound[0], bound[1], stage)):
                        raise ValueError('selection requires current full-stage evidence')
                else:
                    for assignment in stage['cells']:
                        experiment = experiments.get(assignment['experiment_id'])
                        if experiment is None or experiment.get('observation') is None:
                            raise ValueError('failed/unresolved trial needs its retained attempt')
                        cycle._current_evidence(state, experiment, accepted=False)
        errors = decision_errors(root, {'scope': 'validate', 'operation': 'commit_selection',
                                        'request': request_pin, 'selection_sha256': receipt['sha256']})
        if errors: raise ValueError('; '.join(e.code for e in errors))
        cycle._commit(Path(root), state, 'research_selection', receipt=receipt, request=request_pin)
        state_io.atomic_json(Path(root)/'research/selection.json', receipt)
        return receipt


def _selection_state(state):
    events = state.get('events', [])
    receipts = [e['receipt'] for e in events if e['kind'] == 'research_selection']
    return (receipts[-1] if receipts else None,
            [e['read'] for e in events if e['kind'] == 'research_confirm_read'])


def record_confirmation_dispatch(root, state, identity):
    """Always-on executor seam, under operation.lock and before ordinary dispatch."""
    from .research_evaluation import dispatch
    return dispatch(root, state, identity)


def validate_protocol_controls(config, *, evaluation_harness=False):
    """Reject production schema/config/CLI switches for mandatory protocols.

    Evaluation is an explicit caller-owned wrapper boundary, never a config key.
    Operator choices are not protocol-disable switches.
    """
    if evaluation_harness:
        return
    import re
    names = {r['name'] for r in default_protocol()['mandatory_protocols']}
    names.update({'confirmation', 'board', 'protocol', 'protocols'})
    def visit(value, parents=()):
        if isinstance(value, list):
            for item in value:
                visit(item, parents)
        elif isinstance(value, dict):
            for key, item in value.items():
                normalized = key.lower().replace('-', '_').strip('_')
                mandatory = bool(re.search(r'(^|_)p(0[1-9]|1[0-7])($|_)', normalized))
                mandatory |= any(name in normalized for name in names)
                switch = any(w in normalized.split('_') for w in ('enable','enabled','disable','disabled','skip','optional','toggle'))
                boolean_schema = isinstance(item, dict) and (item.get('type') == 'boolean' or item.get('action') in {'store_true','store_false'})
                if mandatory and (switch or (boolean_schema and (normalized in names or __import__('re').fullmatch(r'p(0[1-9]|1[0-7])', normalized)))):
                    raise ValueError('mandatory_protocol_toggle: ' + '.'.join((*parents, key)))
                visit(item, (*parents, key))
    visit(config)


def computed_stop(value, *, base_dir, state=None):
    """Derive the stop from retained select results, never a worker's done vote."""
    stop = value['stop']
    observed_rows = None
    if state is not None:
        from .research_evaluation import stop_state, stop_records
        actual = stop_state(state)
        if not actual or stop != {**actual['rule'], 'reason': actual['reason']}:
            raise ValueError('stop differs from the prospective decision-authorized rule')
        observed_rows = stop_records(state)
    if stop.get('reason') not in {'successes', 'max_rounds', 'budget', 'coverage_unmet'}:
        raise ValueError('stop reason must be successes, max_rounds or budget')
    for key in ('successes', 'max_rounds', 'coverage_floor'):
        if type(stop.get(key)) is not int or stop[key] < 1:
            raise ValueError('finite positive stop ' + key + ' required')
    if _finite_number(stop.get('budget'), 'stop budget') <= 0:
        raise ValueError('positive stop budget required')
    families = stop.get('families')
    if (type(families) is not list or not families or len(set(families)) != len(families)
            or stop['coverage_floor'] > len(families)):
        raise ValueError('bounded feasible family coverage floor required')
    rounds = value['rounds']
    if not rounds or len(rounds) > stop['max_rounds']:
        raise ValueError('stop round count differs')
    covered, successes, seen = set(), set(), set()
    cost = 0.
    for number, row in enumerate(rounds, 1):
        if row.get('round') != number or not row.get('results'):
            raise ValueError('stop requires ordered rounds and select result receipts')
        round_successes = set()
        for pin in row['results']:
            identity = (pin['path'], pin['sha256'])
            if identity in seen:
                raise ValueError('stop receipt reused across trials')
            seen.add(identity)
            if state is None:
                result = _method_json(pin, base_dir)
            else:
                matches = [r for r in observed_rows if (r['source'] or r['attempt']) == pin]
                if len(matches) != 1: raise ValueError('stop requires recorded evaluation observations')
                result = matches[0]
            if (result.get('kind') != 'research-select-result' or result.get('family') not in families
                    or result.get('candidate') not in row.get('candidates', [])
                    or result.get('status') not in {'success', 'failed', 'unresolved'}
                    or result.get('decision') not in DECISIONS
                    or result.get('exposure') != 'adaptive_full'):
                raise ValueError('stop requires bound select-result receipts')
            amount = _finite_number(result.get('cost'), 'select cost')
            if amount < 0:
                raise ValueError('select cost cannot be negative')
            cost += amount
            covered.add(result['family'])
            if result['status'] == 'success' and result['decision'] == 'better':
                round_successes.add(result['candidate'])
        if row.get('successes') != len(round_successes):
            raise ValueError('success count differs from select receipts')
        successes.update(round_successes)
        reached = ((len(covered) >= stop['coverage_floor'] and len(successes) >= stop['successes'])
                   or number >= stop['max_rounds'] or cost >= stop['budget'])
        if reached and number < len(rounds):
            raise ValueError('continuing past computed stop requires a recorded decision')
    if state is not None:
        expected = {((r['source'] or r['attempt'])['path'], (r['source'] or r['attempt'])['sha256'])
                    for r in observed_rows}
        if seen != expected: raise ValueError('stop census differs from observed evaluations')
    if len(covered) < stop['coverage_floor']:
        if len(rounds) >= stop['max_rounds'] or cost >= stop['budget']:
            if stop['reason'] != 'coverage_unmet': raise ValueError('coverage_unmet stop required')
            return {'reason': 'coverage_unmet', 'successes': len(successes), 'rounds': len(rounds),
                    'cost': cost, 'covered_families': sorted(covered), 'coverage_floor': stop['coverage_floor'],
                    'uncovered_families': sorted(set(families) - covered), 'status': 'null_funnel'}
        raise ValueError('coverage floor not reached')
    # Deterministic precedence makes replay byte-identical when caps coincide.
    reason = ('successes' if len(successes) >= stop['successes'] else
              'max_rounds' if len(rounds) >= stop['max_rounds'] else
              'budget' if cost >= stop['budget'] else None)
    if reason != stop['reason']:
        raise ValueError('stop not reached or reason differs from computed receipts')
    return {'reason': reason, 'successes': len(successes), 'rounds': len(rounds),
            'cost': cost, 'covered_families': sorted(covered), 'coverage_floor': stop['coverage_floor']}


def seed_to_test(value, *, base_dir):
    """Check two actual dispatches, prospective predictions and operator yield."""
    ideas = _ids(value['ideas'], 128, 'idea census')
    streams = value.get('dispatch_receipts', {})
    if set(streams) != {'a', 'b'} or {r.get('stream') for r in ideas.values()} != {'a', 'b'}:
        raise ValueError('both streams require dispatch receipts')
    receipts = {}
    for stream, pin in streams.items():
        receipt = _method_json(pin, base_dir)
        rows = [r for r in ideas.values() if r['stream'] == stream]
        if (receipt.get('kind') != 'research-idea-dispatch' or receipt.get('stream') != stream
                or receipt.get('ideas_sha256') != ce.digest(rows)
                or type(receipt.get('committed_sequence')) is not int or receipt['committed_sequence'] < 0
                or receipt.get('execution_observation') not in {'remote_transport_observed',
                    'local_transport_observed', 'host_attested_external'}):
            raise ValueError('stream dispatch receipt must commit exact prospective predictions')
        receipts[stream] = receipt
    report = {}
    for row in ideas.values():
        validate_operator(row.get('operator'))
        _required_text(row.get('prediction'), 'idea prediction')
        operator = report.setdefault(row['operator'], {'ideas': 0,
            'screen': {'tested': 0, 'passed': 0}, 'full': {'tested': 0, 'passed': 0}})
        operator['ideas'] += 1
    seen = set()
    for test in value.get('tests', []):
        key = (test.get('idea'), test.get('stage'))
        if key in seen or key[0] not in ideas or key[1] not in {'screen', 'full'}:
            raise ValueError('distinct declared idea/stage test required')
        seen.add(key)
        idea = ideas[key[0]]
        if (type(test.get('exposure_sequence')) is not int
                or test['exposure_sequence'] <= receipts[idea['stream']]['committed_sequence']):
            raise ValueError('predictions must be committed before test exposure')
        result = _method_json(test['result'], base_dir)
        if (result.get('idea') != key[0] or result.get('status') not in {'success', 'failed', 'unresolved'}
                or result.get('decision') not in DECISIONS):
            raise ValueError('operator yield requires actual idea result')
        counts = report[idea['operator']][key[1]]
        counts['tested'] += 1
        counts['passed'] += int(result['status'] == 'success' and result['decision'] == 'better')
    if value.get('operator_yield') != report:
        raise ValueError('operator yield differs from retained results')
    return report


def feedback_arm(value, *, transform=None, evaluation_harness=False):
    """Evaluation feedback hook: the evaluator owns/blinds the transform; production is identity."""
    if transform is not None and not evaluation_harness:
        raise ValueError('feedback arms are evaluation-harness only')
    return deepcopy(value) if transform is None else transform(deepcopy(value))


def protocol_producers_present(*, bindings=None, package_root=None):
    """Report missing source/check producers; source presence is not execution."""
    import ast
    package = Path(package_root) if package_root is not None else Path(__file__).parents[1]
    registered = set()
    for path in (package / 'validation').glob('*.py'):
        tree = ast.parse(path.read_text())
        registered.add('check:' + path.stem.removeprefix('check_'))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CHECKS' for t in node.targets):
                try:
                    registered.update('check:' + name for name in ast.literal_eval(node.value))
                except (ValueError, TypeError):
                    pass
    missing = []
    for row in bindings if bindings is not None else default_protocol()['mandatory_protocols']:
        modules = [name for name in row['producers'] if not
            (package / (name.removeprefix('ravel.').replace('.', '/') + '.py')).is_file()]
        checks = sorted(set(row['checks']) - registered)
        if modules or checks:
            missing.append({'id': row['id'], 'component': PRODUCER_OWNERS.get(row['id'], 'unassigned'),
                            'producers': modules, 'checks': checks})
    return {'mode': 'report', 'valid': not missing, 'missing': missing,
            'missing_components': sorted({m['component'] for m in missing}),
            'execution_established': False,
            'contracts': [{'id': row['id'], 'owner': PRODUCER_OWNERS.get(row['id'], 'unassigned'),
                           'status': 'producer_pending:' + row['id'] if any(m['id'] == row['id'] for m in missing)
                           else 'record_contract'} for row in (bindings if bindings is not None else default_protocol()['mandatory_protocols'])]}


def family_operator_evaluation(config, *, base_dir):
    """Evaluation contract only: crossed operators plus independent best-of-N."""
    from itertools import product
    if 'best_of_n' not in config.get('arms', []):
        raise ValueError('family comparison requires independent best_of_n arm at equal evaluations')
    if type(config.get('evaluations_per_arm')) is not int or config['evaluations_per_arm'] < 1:
        raise ValueError('positive equal evaluation budget per arm required')
    families, operators = config['families'], config['operators']
    expected = set(product(families, operators))
    actual = [(c['family'], c['operator']) for c in config['cells']]
    if not expected or set(actual) != expected or len(actual) != len(expected):
        raise ValueError('family by operator comparison must be factorial')
    rows = []
    for row in config['cells']:
        receipt = row.get('qualification_receipt')
        qualification = _method_json(receipt, base_dir) if receipt else {}
        qualified = (qualification.get('status') == 'passed'
                     and qualification.get('family') == row['family']
                     and qualification.get('operator') == row['operator'])
        rows.append({**deepcopy(row), 'status': 'qualified' if qualified else 'advisory'})
    return {'cells': rows, 'evaluations_per_arm': config['evaluations_per_arm'], 'execution_authorized': False}


def authorize_screen(root, action):
    """Record the exact prospective R1 action receipt before screen dispatch."""
    _rdj(action, 'R1', root)
    _required_text(action.get('experiment_id'), 'screen experiment')
    cycle = _cycle()
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = cycle._load(root)
        bound = _bound(state)
        if bound is None or not any(s['purpose'] == 'screen' for s in _stage_ids(bound[0], action['experiment_id'])):
            raise ValueError('screen action needs a bound protocol experiment')
        if action.get('protocol_sha256') != bound[1]['protocol']['sha256']:
            raise ValueError('screen action protocol differs')
        if any(e.get('rundir') is not None for e in state['experiments'] if e['id'] == action['experiment_id']):
            raise ValueError('screen R1 authorization must precede launch preparation')
        cycle._commit(Path(root), state, 'research_screen_authorized', action=action)
        return deepcopy(action)


def _screen_errors(state, identity, event):
    actions = [e['action'] for e in state['events'] if e['kind'] == 'research_screen_authorized'
               and e['action'].get('experiment_id') == identity]
    if not actions or actions[-1].get('protocol_sha256') != event['protocol']['sha256']:
        return ['screen_launch_requires_r1']
    try:
        _rdj(actions[-1], 'R1', state['base_dir'])
    except (ValueError, OSError, KeyError, TypeError):
        return ['screen_launch_requires_r1']
    return []


def obligation_coverage(plan, claims, outputs, *, base_dir):
    """Recompute output obligations from both plan and claims; inspect content."""
    obligations = {}
    def collect(value):
        if isinstance(value, list):
            for item in value: collect(item)
        elif isinstance(value, dict):
            for row in value.get('required_outputs', []):
                if (not isinstance(row, dict) or set(row) != {'id', 'format', 'pointer'}
                        or row['format'] not in {'json', 'text'}):
                    raise ValueError('obligation requires id, format and pointer')
                _required_text(row['id'], 'obligation identity')
                if row['id'] in obligations and row != obligations[row['id']]:
                    raise ValueError('obligation collision: ' + row['id'])
                obligations[row['id']] = row
            for key, item in value.items():
                if key != 'required_outputs': collect(item)
    collect(plan); collect(claims)
    if not obligations:
        raise ValueError('obligation census is empty')
    def nonempty(value):
        if value is None: return False
        if isinstance(value, str): return bool(value.strip())
        if isinstance(value, dict): return bool(value) and any(nonempty(v) for v in value.values())
        if isinstance(value, list): return bool(value) and any(nonempty(v) for v in value)
        return True  # numeric zero and False are genuine output content
    for identity, row in obligations.items():
        if identity not in outputs:
            raise ValueError('obligation missing required output: ' + identity)
        raw = _method_pin(outputs[identity], base_dir)
        try:
            import json
            content = json.loads(raw) if row['format'] == 'json' else raw.decode('utf-8')
            if row['pointer']:
                if row['format'] != 'json': raise ValueError('text output cannot use JSON pointer')
                comparison._pointer(row['pointer'])
                content = _cycle()._pointer(content, row['pointer'])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ValueError('obligation content invalid: ' + identity) from exc
        if not nonempty(content):
            raise ValueError('obligation empty required output: ' + identity)
    return {'covered': sorted(obligations), 'complete': True}


def precision_size(declaration):
    """Size supplied independent measurements from a declared precision target.

    A mean target uses an explicitly supplied standard-deviation bound. A
    Bernoulli target uses Hoeffding's distribution-free absolute-error bound.
    These are stated sampling assumptions, not generator calibration or power.
    """
    import math
    target = declaration.get('precision_target')
    if not isinstance(target, dict):
        raise ValueError('declared precision target required; fixed smoke size is insufficient')
    error = _finite_number(target.get('absolute_error'), 'precision absolute error')
    if error <= 0: raise ValueError('positive precision target required')
    if target.get('kind') == 'mean_standard_error':
        sigma = _finite_number(target.get('sigma_bound'), 'precision sigma bound')
        if sigma <= 0: raise ValueError('positive declared sigma bound required')
        n = math.ceil((sigma / error)**2)
        assumption = 'Independent samples; supplied sigma bounds the population standard deviation.'
    elif target.get('kind') == 'bernoulli_absolute_error':
        alpha = _finite_number(target.get('alpha'), 'precision alpha')
        if not 0 < alpha < 1 or not 0 < error < 1:
            raise ValueError('precision alpha and probability error must lie in (0, 1)')
        n = math.ceil(math.log(2 / alpha) / (2 * error**2))
        assumption = 'Independent Bernoulli trials; Hoeffding two-sided failure probability at most alpha.'
    else:
        raise ValueError('unsupported precision target; supply a source-backed sizing adapter')
    if n > 1_000_000_000:
        raise ValueError('precision target exceeds bounded sizing range')
    return {'samples': max(1, n), 'precision_target': deepcopy(target), 'assumption': assumption,
            'execution_authorized': False, 'physics_validated': False}


def validate_selection_claim(claim, *, base_dir):
    if type(claim.get('N')) is not int or claim['N'] < 0:
        raise ValueError('trials_unreported')
    if not selection_claim_required(claim):
        if claim.get('kind') == 'agreement':
            _method_pin(claim.get('agreement_ledger'), base_dir)
            _method_pin(claim.get('noise_model'), base_dir)
        return
    if not claim.get('selection_report') or not claim.get('selection_receipt'):
        raise ValueError('selection receipt and confirmation report required')
    receipt = _method_json(claim['selection_receipt'], base_dir)
    report = _method_json(claim['selection_report'], base_dir)
    expected = selection_report(receipt, [r['result'] for r in report['selected_result_on_confirm']],
                                base_dir=base_dir, state=_observed_state(base_dir) if receipt.get('origin') else None)
    if report != expected or claim['N'] != receipt['N']:
        raise ValueError('selection report or reported N differs from source receipts')
    if claim.get('verdict') == 'accepted' and not report['promoted']:
        raise ValueError('null funnel is deliverable but cannot promote a performance, mechanism or agreement claim')


def selection_claim_required(claim):
    return claim.get('kind') in {'performance', 'mechanism'} or any(claim.get(k) for k in
        ('metric', 'selection_receipt', 'selection_report', 'confirmation', 'calibration'))


def completion_disclosure(receipts):
    """Completion-record interface: aggregate unsupported completion claims by worker/model."""
    workers, models, missing = {}, {}, []
    for receipt in receipts:
        absent = [key for key in receipt.get('required_outputs', [])
                  if not receipt.get('output_receipts', {}).get(key)]
        if receipt.get('complete') and absent:
            worker, model = receipt['worker'], receipt['model_cell']
            workers[worker] = workers.get(worker, 0) + 1
            models[model] = models.get(model, 0) + 1
            missing.append({'worker': worker, 'model_cell': model, 'missing_outputs': absent})
    return {'valid': not missing, 'missing': missing,
            'completion_claimed_without_receipts': {'workers': workers, 'model_cells': models}}


def _allocation_required(state):
    budget = state['contract'].get('budget', {}).get('wall_seconds')
    live = [e for e in state.get('experiments', []) if e.get('observation') is None
            and (budget is None or e['cost']['wall_seconds'] <= budget)
            and any(prediction is not None for prediction in e.get('predictions', {}).values())]
    return len(state.get('hypotheses', [])) >= 2 and len(live) >= 2


def _allocation_errors(state, identity):
    records = [event for event in state.get('events', []) if event['kind'] == 'research_allocation'
               and identity in event['work_items']]
    if not records:
        return ['allocator_recommendation_required'] if _allocation_required(state) else []
    from .experiment_allocator import check_allocation
    try:
        record = records[-1]
        case = _method_json(record['case'], state['base_dir'])
        _allocation_matches_state(state, case)
        allocation = check_allocation(case, _method_json(record['policy'], state['base_dir']),
                                      record['work_items'][identity], base_dir=state['base_dir'])
        if identity not in allocation['reserved_actions'] and identity not in allocation['selection_order'][:1]:
            return ['allocator_action_not_next']
        if identity in allocation['reserved_actions']:
            receipt, reads = _selection_state(state)
            # Reservation is advice, never permission to open held-out data.
            if receipt is None:
                return ['confirm_read_before_selection']
            return confirmation_errors(receipt, reads, {'candidate': record['work_items'][identity].get('candidate')})
    except (ValueError, OSError, KeyError, TypeError):
        return ['allocator_recommendation_required']
    return []


def _allocation_matches_state(state, case):
    live = {e['id']: e for e in state['experiments'] if e.get('observation') is None}
    if set(live) != {a['id'] for a in case['actions']}:
        raise ValueError('allocator must retain all live actions')
    if {h['id'] for h in state['hypotheses']} != {h['id'] for h in case['hypotheses']}:
        raise ValueError('allocator must retain all live hypotheses')
    for h in case['hypotheses']:
        if h['predictions'] != {i: e['predictions'].get(h['id']) for i, e in live.items()}:
            raise ValueError('allocator predictions differ from prospective experiments')
    for action in case['actions']:
        if action['cost'] != live[action['id']]['cost']['wall_seconds']:
            raise ValueError('allocator action cost must be declared wall seconds')
        for key in ('cost_class', 'cost_measurement', 'exposure'):
            if key in live[action['id']] and action.get(key) != live[action['id']][key]:
                raise ValueError('allocator action ' + key + ' differs from prospective experiment')
    bound = _bound(state)
    if bound is not None:
        protocol, _ = bound
        withheld = {r['experiment_id'] for s in protocol['stages'] if s['purpose'] == 'confirm' for r in s['cells']}
        for action in case['actions']:
            if (action.get('exposure') == 'withheld_confirmation') != (action['id'] in withheld):
                raise ValueError('allocator withheld reservation differs from bound protocol')


def bind_allocation(root, case_pin, policy_pin, work_items):
    """Queue seam: require current recommendations on adopted work items."""
    from .experiment_allocator import check_allocation
    cycle = _cycle()
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = cycle._load(root)
        case, policy = _method_json(case_pin, state['base_dir']), _method_json(policy_pin, state['base_dir'])
        _allocation_matches_state(state, case)
        if set(work_items) != {a['id'] for a in case['actions']}:
            raise ValueError('each queued action requires its allocator recommendation')
        for item in work_items.values():
            check_allocation(case, policy, item, base_dir=state['base_dir'])
        cycle._commit(Path(root), state, 'research_allocation', case=case_pin, policy=policy_pin,
                      work_items=work_items)
        return deepcopy(work_items)


def validate_followup_schema(kind, value):
    """Shared schema for source/evaluator/board consumers; status is never input."""
    import json
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).parents[1] / 'data/research/followup.schema.json').read_text())
    if kind not in schema['$defs']:
        raise ValueError('unknown research record schema')
    schema['$ref'] = '#/$defs/' + kind
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        raise ValueError('research ' + kind + ' schema: ' + errors[0].message)


def reserve_confirmation(root, action):
    """Evaluator seam for default-methodology runs without a staged cell matrix.

    Must run before opening withheld results. The evaluator also reserves the
    shared study split; this campaign-local event is deliberately not a lease.
    """
    cycle = _cycle()
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = cycle._load(root)
        receipt, reads = _selection_state(state)
        if receipt is not None:
            _verify_selection(receipt, state['base_dir'])
        _exposure_identity(action)
        errors = confirmation_errors(receipt, reads, action)
        if errors: raise ValueError(errors[0])
        ledger = reserve_study_exposure(state['contract'].get('context_request', state['contract']), action,
                                        selection_sha256=receipt['sha256'])
        read = {**deepcopy(action), 'selection_sha256': receipt['sha256'], 'ledger': ledger}
        cycle._commit(Path(root), state, 'research_confirm_read', read=read)
        return read


def precision_required(value):
    """Typed original-intake trigger, including nested bound task contracts."""
    if isinstance(value, list): return any(precision_required(x) for x in value)
    if not isinstance(value, dict): return False
    if any(value.get(k) in {'anomaly_search', 'method_study'} for k in ('task_kind', 'task_mode')):
        return True
    return any(precision_required(v) for v in value.values() if isinstance(v, (dict, list)))


def selection_oracle_gap(receipt, confirmation_values, *, evaluation_harness=False):
    """Synthetic evaluator diagnostic; never read unselected confirm in production."""
    if not evaluation_harness:
        raise ValueError('oracle gap is evaluation-harness only')
    _verify_selection(receipt)
    if receipt['k'] != 1 or set(confirmation_values) != {r['candidate'] for r in receipt['trials']}:
        raise ValueError('oracle gap requires one selected candidate and the complete fixture census')
    for value in confirmation_values.values(): _finite_number(value, 'fixture confirmation value')
    selected = confirmation_values[receipt['selected'][0]]
    if receipt['rule']['direction'] == 'maximize':
        return max(confirmation_values.values()) - selected
    return selected - min(confirmation_values.values())


def verify_selection_journal(state, receipt):
    """Verify chronology and complete read accounting in either protocol path."""
    _verify_selection(receipt, state['base_dir'])
    selected = False
    reads = []
    for event in state['events']:
        if event['kind'] == 'research_selection':
            if selected or event['receipt'] != receipt:
                raise ValueError('selection receipt differs from its immutable journal commitment')
            selected = True
        elif event['kind'] == 'research_confirm_read':
            if not selected:
                raise ValueError('confirm_read_before_selection')
            read = event['read']
            if read.get('selection_sha256') != receipt['sha256']:
                raise ValueError('confirm_read_before_selection: read has no matching commitment')
            _exposure_identity(read)
            errors = confirmation_errors(receipt, reads, read)
            if errors: raise ValueError(errors[0])
            reads.append(deepcopy(read))
    if not selected:
        raise ValueError('confirm_read_before_selection')
    if {r['candidate'] for r in reads} != set(receipt['selected']):
        raise ValueError('confirmation_read_receipt_missing')
    from .research_evaluation import selection_request
    request = {'rule': receipt['rule'], 'regime': receipt['regime'],
               'trials': [{k: row[k] for k in ('id', 'candidate', 'result')} for row in receipt['trials']]}
    observed = selection_request(state, request)
    if selection_receipt(request, base_dir=state['base_dir'], observed_rows=observed) != receipt:
        raise ValueError('selection differs from observed evaluation census')
    from ravel.physics.ml_exposure import verify_research_read
    for read in reads:
        verify_research_read(read)
    voided = {e['read']['experiment_id'] for e in state['events'] if e['kind'] == 'research_confirmation_void'}
    return [r for r in reads if r.get('experiment_id') not in voided]


def _verify_report_reads(receipt, report, reads):
    for result in report['selected_result_on_confirm']:
        matches = [r for r in reads if r['candidate'] == result['candidate'] and set(r['cells']) == set(result['cells'])]
        if len(matches) != 1: raise ValueError('confirmation result has no unique reserved read')
        read = matches[0]
        if (set(result['cells']) != set(read['cells']) or {str(v) for v in result['seeds']} != {str(v) for v in read['seeds']}
                or result['generation'] != read['generation']):
            raise ValueError('confirmation result differs from its prospectively reserved read')


def _methodology_journal_guard(state, stage_id, artifact, *, base_dir, regime):
    """Default-stage adoption uses the same immutable boundary as staged dispatch."""
    if artifact.get('status') == 'not_applicable':
        return
    if stage_id == 'validate':
        withheld = set(artifact.get('withheld_cells', []))
        for event in state.get('events', []):
            if event['kind'] == 'research_adaptive_read' and withheld & set(event['read']['cells']):
                raise ValueError('confirm_cell_in_selection_inputs')
        for stage in (state.get('methodology') or {}).get('stages', []):
            if stage['id'] == 'screen' and stage.get('artifact'):
                screen = _method_json(stage['artifact'], base_dir)
                if withheld & set(screen.get('subset', {}).get('cells', [])):
                    raise ValueError('confirm_cell_in_selection_inputs')
        selected = artifact.get('selection', {})
        if not selected.get('receipt'):
            raise ValueError('confirm_read_before_selection')
        receipt = _method_json(selected['receipt'], base_dir)
        reads = verify_selection_journal(state, receipt)
        if receipt['regime'] != regime:
            raise ValueError('bound selection regime differs')
        computed_stop(artifact, base_dir=base_dir, state=state)
        report = selection_report(receipt, selected.get('confirmation_pins', []), base_dir=base_dir, state=state)
        _verify_report_reads(receipt, report, reads)
        confirmed_cells = {c for r in report['selected_result_on_confirm'] for c in r['cells']}
        if receipt['k'] and confirmed_cells != set(artifact['withheld_cells']):
            raise ValueError('confirmation report must cover the declared withheld cells')
    elif stage_id == 'acceptance':
        for claim in artifact.get('claims', []):
            if not selection_claim_required(claim):
                # A committed search cannot be hidden by changing the claim label.
                from .research_evaluation import declaration
                calibration = any((_method_json(e['study'], state['base_dir']).get('mode') == 'detector-calibration')
                                  for e in state.get('experiments', []) if e.get('study'))
                confirm = any((declaration(state, e) or {}).get('purpose') == 'confirm' for e in state.get('experiments', []))
                if _selection_state(state)[0] is not None or calibration or confirm:
                    raise ValueError('selection receipt and confirmation report required')
                validate_selection_claim(claim, base_dir=base_dir)
                continue
            if not claim.get('selection_receipt') or not claim.get('selection_report'):
                raise ValueError('selection receipt and confirmation report required')
            receipt = _method_json(claim['selection_receipt'], base_dir)
            reads = verify_selection_journal(state, receipt)
            report = _method_json(claim['selection_report'], base_dir)
            expected = selection_report(receipt, [r['result'] for r in report['selected_result_on_confirm']],
                                        base_dir=base_dir, state=state)
            if report != expected: raise ValueError('confirmation report differs from observed evaluations')
            _verify_report_reads(receipt, report, reads)


# The producer contracts remain explicit until their owning packages land.
PRODUCER_OWNERS = {
    'P01': 'research board', 'P02': 'research board',
    'P03': 'research evaluation', 'P04': 'evidence queue / knowledge support closure',
    'P05': 'authority broker', 'P06': 'root-cause analysis',
    'P07': 'evidence queue / experiment allocator', 'P08': 'research board / seed-to-test',
    'P09': 'hypothesis register', 'P10': 'decision gate / request fidelity',
    'P11': 'normalization ledger', 'P12': 'analysis IR',
    'P13': 'event accounting', 'P14': 'knowledge promotion',
    'P15': 'work dispatch / RDJ', 'P16': 'research evaluation / ML exposure', 'P17': 'RDJ / role registry',
}


def producer_pending(root=None):
    """Missing producers; with a run, only those its route makes applicable.

    An ordinary (non-campaign) run satisfies a protocol through the ordinary
    workflow producer named in ``ORDINARY_PROTOCOL_PRODUCERS``, which must exist.
    """
    if root is None:
        return ['producer_pending:' + r['id'] for r in protocol_producers_present()['missing']]
    table = route_applicability(root)['protocols']
    pending = []
    for row in protocol_producers_present()['missing']:
        entry = table[row['id']]
        if not entry['applicable']:
            continue
        producer = entry.get('ordinary_producer')
        if producer is not None and _module_present(producer):
            continue
        pending.append('producer_pending:' + row['id'])
    return pending


def _module_present(name):
    from importlib.util import find_spec
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# Code-owned applicability per route. A plain reproduction or reinterpretation
# declares no candidate search, calibration or selection: the search stages and
# their protocols have nothing to act on. Integrity, meta-review and every other
# stage and protocol still apply. Any declared or observed search restores them.
PLAIN_ROUTE = 'plain_reproduction'
SEARCH_ROUTE = 'research_search'
ROUTE_APPLICABILITY = {
    PLAIN_ROUTE: {
        'stages': {
            'ideas': 'no candidate search: the route proposes no ideas to screen',
            'screen': 'no candidate search: nothing to screen',
            'validate': 'no selection: no adaptive rounds or withheld confirmation cells',
            'critique_to_experiments': 'no candidate experiments: critique is reviewed at meta_review',
        },
        'protocols': {
            'P01': 'no candidate search: no hypothesis board',
            'P02': 'no candidate search: no sealed idea seeding',
            'P07': 'no candidate search: no experiment allocation',
            'P08': 'no candidate search: no seed-to-test chain',
            'P09': 'no candidate search: no excluded-hypothesis register',
            'P16': 'no selection: no confirmation separation',
        },
    },
    SEARCH_ROUTE: {'stages': {}, 'protocols': {}},
}

# An ordinary (non-campaign) run completes each applicable stage through the
# workflow record that already produces it. The mapping is code; nothing here is
# supplied by a run or a model.
ORDINARY_STAGE_PRODUCERS = {
    'limitation_census': 'research preregistration: the approved approximations and evaluator applicability',
    'baseline': 'CHECK-IN 2 comparison: the reviewed produced, reference and comparison records',
    'acceptance': 'CHECK-IN 2/3 acceptance: every reviewer accepted one claim scope that authorizes delivery',
    'meta_review': 'CHECK-IN 2/3 review records: physics critic, skeptical verifier and physics decider',
    'integrity': 'claim checks and certificates: every integrity and machine claim check of the accepted cycle passed',
}
# Ordinary-run producers for the mandatory protocols, or the route-derived reason
# the protocol has nothing to act on. Event-processing protocols apply only when
# the approved plan processes events.
ORDINARY_PROTOCOL_PRODUCERS = {
    'P04': ('ravel.validation.claim_checks', None),
    'P06': (None, 'ordinary run: no rival mechanisms are adjudicated; a discrepancy is a physics review finding'),
    'P10': ('ravel.workflow.decision_gate', None),
    'P11': ('ravel.validation.normalization_ledger', None),
    'P12': (None, 'ordinary run: no executable contrasts between candidates'),
    'P13': ('ravel.validation.event_accounting', None),
    'P15': (None, 'ordinary run: no research work dispatch; stages run under the CHECK-IN 1 approval and launch authorization'),
    'P17': ('ravel.workflow.physics_review', None),
}
EVENT_PROTOCOLS = ('P11', 'P13')
NO_EVENT_PLANS = ('none', 'dry')


SEARCH_KEYS = ('candidate_search', 'calibration', 'selection')


def _search_declared(contract, plan):
    """Search, calibration or selection declared by the contract or its request plan.

    The contract's own mode and route, the plan's top-level search keys, and every
    plan claim's kind and search keys are declarations. The plan's ``label`` is a
    derived compatibility label, not a declaration, and is not read here.
    """
    triggers = default_protocol()['binding_triggers']
    plain = {'reproduce', 'reinterpret', 'agreement'}
    search = {key: [v for v in allowed if v not in plain] for key, allowed in triggers.items()}
    def declares(value):
        return isinstance(value, dict) and (
            any(value.get(k) for k in SEARCH_KEYS)
            or any(isinstance(value.get(k), str) and value[k] in allowed for k, allowed in search.items()))
    claims = plan.get('claims') if isinstance(plan.get('claims'), list) else []
    return declares(contract) or any(plan.get(k) for k in SEARCH_KEYS) or any(declares(c) for c in claims)


def _route(root):
    from .research_admission import run_contract
    contract = run_contract(root)
    plain = contract.get('task_mode', contract.get('task_kind')) in {'reproduce', 'reinterpret'}
    plan = _method_json(contract['request_plan'], root) if contract.get('request_plan') else {}
    search = _search_declared(contract, plan if isinstance(plan, dict) else {})
    if (Path(root)/'head.json').exists():
        state = _cycle()._read(state_io.read_json(Path(root)/'head.json'), root)
        search |= _selection_state(state)[0] is not None or any(
            (e.get('evaluation') or {}).get('purpose') in {'screen', 'full', 'confirm'} for e in state['experiments'])
        bound = _bound(state)
        search |= bool(bound and any(s['purpose'] in {'screen', 'full', 'confirm'} for s in bound[0]['stages']))
    return PLAIN_ROUTE if plain and not search else SEARCH_ROUTE


def route_applicability(root):
    """Per-stage and per-protocol applicability with route-derived reasons."""
    from .research_admission import run_contract
    route = _route(root)
    table = ROUTE_APPLICABILITY[route]
    definition = default_protocol()
    ordinary = not (Path(root)/'head.json').exists()
    stages = {i: {'applicable': i not in table['stages'], 'reason': table['stages'].get(i)}
              for i in [r['id'] for r in definition['stages']]}
    protocols = {i: {'applicable': i not in table['protocols'], 'reason': table['protocols'].get(i)}
                 for i in [r['id'] for r in definition['mandatory_protocols']]}
    if ordinary and route == PLAIN_ROUTE:
        plan = run_contract(root).get('compute_plan')
        for pid, (producer, reason) in ORDINARY_PROTOCOL_PRODUCERS.items():
            if pid in EVENT_PROTOCOLS and plan in NO_EVENT_PLANS:
                reason = f'ordinary run: compute_plan={plan} processes no events'
                producer = None
            if producer is None:
                protocols[pid] = {'applicable': False, 'reason': reason}
            else:
                protocols[pid] = {'applicable': True, 'reason': None, 'ordinary_producer': producer}
    return {'route': route, 'stages': stages, 'protocols': protocols}


def stage_inapplicable(stage_id, root):
    """Compute from the original ordinary task, never from a claimed reason."""
    return stage_id in ROUTE_APPLICABILITY[_route(root)]['stages']


def ordinary_stage_evidence(root):
    """Stage completion for an ordinary run, computed from its workflow records.

    Each applicable stage maps to the record that already produces it; a stage
    that the route makes inapplicable is ``stage_inapplicable`` with its reason.
    Nothing is written; every read recomputes from the current records.
    """
    root = Path(root)
    applicability = route_applicability(root)['stages']
    record = methodology_status(root)['record']
    review, review_error = _ordinary_review(root)
    out = {}
    for stage, entry in applicability.items():
        if not entry['applicable']:
            out[stage] = {'status': 'stage_inapplicable', 'reason': entry['reason']}
            continue
        producer = ORDINARY_STAGE_PRODUCERS.get(stage)
        if producer is None:
            out[stage] = {'status': 'missing', 'producer': 'research campaign',
                          'reason': 'a research campaign produces this stage; start the campaign route'}
            continue
        if stage == 'limitation_census':
            ok = record['preregistration'] is not None and isinstance(
                _method_json(record['preregistration'], root).get('approximations'), list)
            reason = None if ok else 'the code-produced research preregistration is missing'
            evidence = [record['preregistration']] if ok else []
        elif review is None:
            ok, reason, evidence = False, review_error, []
        else:
            ok, reason, evidence = _ordinary_review_stage(root, stage, *review)
        out[stage] = {'status': 'satisfied' if ok else 'missing', 'producer': producer,
                      'reason': reason or producer, 'evidence': evidence}
    return out


def _ordinary_review(root):
    from . import physics_review as review
    if not review.registered(root):
        return None, 'no CHECK-IN 2 physics review is registered'
    try:
        reg, events = review._read(review._root(root))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, 'CHECK-IN 2 physics review is unreadable: ' + str(exc)
    return (reg, review._view(reg, events)), None


def _ordinary_review_stage(root, stage, reg, view):
    from . import physics_review as review, waypoint_evidence
    cycle = view['cycle']
    if view['state'] != 'accepted':
        return False, f'CHECK-IN 2/3 review is {view["state"]}, not accepted by every reviewer', []
    roles = {r['role'] for r in view['reviews']}
    scope = review._accepted_scope(view)
    evidence = [{'cycle_id': cycle['cycle_id'], 'role': r['role'], 'actor_id': r['actor_id'],
                 'claim_scope': r['claim_scope']} for r in view['reviews']]
    if stage == 'meta_review':
        if roles != set(review.ROLES):
            return False, 'a CHECK-IN 2/3 review record is missing: ' + ', '.join(sorted(set(review.ROLES) - roles)), []
        return True, None, evidence
    policy = reg['policy']
    if stage == 'acceptance':
        if 'delivery' not in policy['claim_scopes'][scope]['actions']:
            return False, f'accepted claim scope {scope} does not authorize delivery', []
        return True, None, evidence
    kinds = {c['id']: c['kind'] for c in policy['required_checks']}
    checks = {c['id']: c for c in cycle['checks']}
    if stage == 'integrity':
        integrity = [cid for cid in policy['claim_scopes'][scope]['checks'] if kinds.get(cid) == 'integrity']
        machine = [cid for cid in checks if cid not in kinds]
        failed = [cid for cid in [*integrity, *machine] if checks[cid]['status'] != 'pass']
        if not integrity or failed:
            return False, 'integrity checks did not pass: ' + (', '.join(failed) or 'none declared'), []
        return True, None, [{'cycle_id': cycle['cycle_id'], 'check': cid} for cid in [*integrity, *machine]]
    # baseline: the reviewed produced/reference/comparison records of the waypoint.
    pinned = {Path(p['path']).name if isinstance(p, dict) and 'path' in p else None for p in cycle['snapshots']}
    manifest = Path(root) / waypoint_evidence.MANIFEST
    if not manifest.is_file() or manifest.name not in pinned:
        return False, 'the reviewed cycle pins no CHECK-IN 2 comparison of produced and reference results', []
    value = state_io.read_json(manifest)
    # Corrections admitted after a comparison are retained beside the baseline: an
    # agreement reached after revising inputs is reported with that count.
    return True, None, [*({'cycle_id': cycle['cycle_id'], role: value[role]} for role in ('produced', 'reference', 'comparison')),
                        {'cycle_id': cycle['cycle_id'], 'corrections_before_acceptance': view['redos_used']}]


def validate_operator(operator, *, evaluation_harness=False):
    allowed = {'limitation_fix', 'ablation_refinement', 'provocation'}
    if evaluation_harness:
        allowed |= {'recombination', 'technique_transfer'}
    if operator not in allowed:
        raise ValueError('declared production idea operator required')


def _action_reads_withheld(root, action):
    if not (Path(root)/'head.json').exists():
        return False
    state = _cycle()._load(root)[1]
    bound = _bound(state)
    if not bound:
        return False
    cells = [c for c in bound[0]['cells'] if c['exposure'] == 'withheld_confirmation']
    return bool(set(action.get('cells', [])) & {c['id'] for c in cells}
        or {p.get('sha256') for p in action.get('population_pins', [])}
           & {c['population']['sha256'] for c in cells})


from .research_admission import decision_errors
from .research_evaluation import enforce_dispatch_stop, reserve_study_exposure


def void_confirmation(root, experiment_id):
    """One code-written recovery, with failure custody and no returned result.

    This voids a report disposition, never the shared exposure. A replacement
    must use new cells, seeds and populations and remains subject to dispatch.
    """
    cycle = _cycle()
    with state_io.file_lock(Path(root)/'operation.lock', blocking=False):
        _, state = cycle._load(root)
        reads = [e['read'] for e in state['events'] if e['kind'] == 'research_confirm_read'
                 and e['read'].get('experiment_id') == experiment_id]
        if len(reads) != 1:
            raise ValueError('one recorded confirmation attempt required')
        read = reads[0]
        if any(e['kind'] == 'research_confirmation_void' and e['read']['candidate'] == read['candidate'] for e in state['events']):
            raise ValueError('confirmation recovery already consumed for candidate')
        experiment = next(e for e in state['experiments'] if e['id'] == experiment_id)
        observation = experiment.get('observation') or {}
        if (observation.get('execution_status') not in {'failed', 'interrupted'}
                or observation.get('result') is not None
                or (Path(experiment['rundir'])/'outputs/attempt-1/result.json').exists()):
            raise ValueError('failed confirmation with no result required')
        cycle._current_evidence(state, experiment, accepted=False)
        attempt = _method_json(observation['receipt'], state['base_dir'])
        if attempt.get('status') not in {'failed', 'interrupted'}:
            raise ValueError('terminal failed attempt receipt required')
        return cycle._commit(Path(root), state, 'research_confirmation_void', read=read,
                             failure_receipt=observation['receipt'])


def authorize_stop_continuation(root, stop_rule, decision):
    """A fresh decision authorizes explicit new bounds, never an unrecorded retry."""
    from .research_evaluation import stop_state
    cycle = _cycle()
    with state_io.file_lock(Path(root)/'operation.lock', blocking=False):
        _, state = cycle._load(root)
        stop = stop_state(state)
        if not stop or not stop['reason']:
            raise ValueError('computed stop required before continuation')
        validate_followup_schema('stop', {**stop_rule, 'reason': 'budget'})
        ce.keys(decision, ('rdj_receipt',))
        action = {'scope': 'validate', 'operation': 'continue_after_stop',
                  'stop_sha256': stop['sha256'], 'stop_rule': stop_rule, **decision}
        _rdj(action, 'R2', state['base_dir'])
        errors = decision_errors(root, action)
        if errors: raise ValueError('; '.join(e.code for e in errors))
        return cycle._commit(Path(root), state, 'research_stop_continuation',
                             previous_stop=stop, stop_rule=stop_rule,
                             after_revision=state['revision'], decision=deepcopy(decision))


def produce_selection_report(root):
    """Write the report from observed confirmation outputs and dispatch custody."""
    cycle = _cycle()
    with state_io.file_lock(Path(root)/'operation.lock', blocking=False):
        _, state = cycle._load(root)
        receipt, _ = _selection_state(state)
        if receipt is None: raise ValueError('confirm_read_before_selection')
        reads = verify_selection_journal(state, receipt)
        from .research_evaluation import records
        confirmations = records(state, purposes={'confirm'})
        voided = {e['read']['experiment_id'] for e in state['events'] if e['kind'] == 'research_confirmation_void'}
        pins = [r['source'] or r['attempt'] for r in confirmations if r['id'] not in voided]
        report = selection_report(receipt, pins, base_dir=state['base_dir'], state=state)
        _verify_report_reads(receipt, report, reads)
        path = Path(root)/'research'/f'selection-report-{state["revision"] + 1}.json'
        if path.exists(): raise ValueError('report revision already exists')
        state_io.atomic_json(path, report)
        pin = cycle._pin(path)
        cycle._commit(Path(root), state, 'research_confirmation_report', report=pin)
        return pin


def validation_trace(root):
    """Project the observed evaluation rounds and stopping receipts; no result input."""
    from .research_evaluation import stop_records, stop_state
    state = _cycle()._load(root)[1]
    stop = stop_state(state)
    if not stop or not stop['reason']:
        raise ValueError('computed stopping boundary has not been reached')
    rows = stop_records(state)
    rounds = []
    for number, original_round in enumerate(sorted({r['round'] for r in rows}), 1):
        own = [r for r in rows if r['round'] == original_round]
        rounds.append({'round': number, 'candidates': sorted({r['candidate'] for r in own}),
                       'successes': len({r['candidate'] for r in own if r['status'] == 'success' and r['decision'] == 'better'}),
                       'results': [r['source'] or r['attempt'] for r in own]})
    value = {'stop': {**stop['rule'], 'reason': stop['reason']}, 'rounds': rounds}
    computed_stop(value, base_dir=state['base_dir'], state=state)
    return value


def _observed_state(root):
    head = Path(root)/'head.json'
    return _cycle()._read(state_io.read_json(head), root) if head.exists() else None
