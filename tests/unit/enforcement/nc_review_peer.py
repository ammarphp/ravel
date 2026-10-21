"""Production content guards for review/research component fixtures.

All model/transport observations here are unqualified synthetic inputs. No helper
provides a successful review verdict, ledger, sink or scientific attestation.
"""
from copy import deepcopy
from hashlib import sha256

STAGES = ('limitation_census', 'ideas', 'baseline', 'screen', 'validate',
          'critique_to_experiments', 'acceptance', 'meta_review', 'integrity')
CANARY = 'withheld-interpretation-84a19'


def fixture():
    """One inert clean population, independent of the coverage row or oracle."""
    return {'packet': {'role': 'physics-critic', 'inputs': ['inputs/data.json'], 'withheld': ['held_out/source.txt'],
                       'workspace': {'inputs/data.json': 'toy observation',
                                     'held_out/source.txt': CANARY}, 'framing': []},
            'action': {'kind': 'unblind', 'declared_class': 'R3'},
            'action_digest': sha256(b'unblind').hexdigest(),
            'current_action_digest': sha256(b'unblind').hexdigest(),
            'seats': [{'role': 'physics-critic', 'session_id': 'critic', 'actor_id': 'critic',
                       'model': 'claude-x', 'fresh': True},
                      {'role': 'skeptical-verifier', 'session_id': 'verifier', 'actor_id': 'verifier',
                       'model': 'claude-x', 'fresh': True}],
            'findings_before': ['failed-check'], 'findings_after': ['failed-check'],
            'repair': {'before': 'defective bytes', 'after': 'corrected bytes',
                       'attempt': 1, 'maximum': 2, 'rereviewed': True},
            'crosscheck': {'claimed': True, 'receipt': {'producer': 'broker', 'status': 'ok',
                                                       'action': 'independent-check'}},
            'certification': {'operation': 'toy-fit', 'validator': 'toy-fit-validator',
                              'scope': 'toy-fit', 'confirmed': True},
            'stages': [{'id': s, 'status': 'done', 'reviewed_na': False} for s in STAGES],
            'ideas': {'barrier_open': False, 'stream': 'b', 'reads': ['limitation-census'],
                      'peer_proposal': 'stream-a-proposal'},
            'child': {'id': 'experiment-one', 'ci1': {'approved': True, 'subject': 'experiment-one'}},
            'preregistration': {'producer': 'approved-plan-producer', 'plan_digest': 'current-plan',
                                'current_plan_digest': 'current-plan', 'created': 1, 'first_effect': 2},
            'inventory': {'requested': 'allowed-tool', 'allowed': ['allowed-tool']},
            'author_families': ['claude', 'openai'], 'min_model_families': 1}


def result(errors=(), notices=(), disclosures=()):
    return {'errors': list(errors), 'notices': list(notices), 'disclosures': list(disclosures)}


def real_packet(nc, p):
    import json
    from ravel.workflow import review_projection
    root = nc.path('packet-probe'); root.mkdir(exist_ok=True)
    for path, data in p['packet']['workspace'].items():
        target = root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(data)
    contract = root/'inputs/task_contract.json'
    contract.write_text(json.dumps({'forbidden_sources': [{'kind': 'forbidden-source',
        'statement': 'The control source is withheld.', 'origin': 'harness', 'evidence': [],
        'paths': p['packet']['withheld']}]}))
    # The public screen consults installed card rules and the supplied source policy.
    kept, removed = review_projection.screen_inputs(root, p['packet']['role'], p['packet']['inputs'])
    nc.permitted_reads = [root / path for path in kept]
    report = result(['packet_input_forbidden'] if removed else (), disclosures=p['packet']['framing'])
    report['diagnostics'] = {'kept': kept, 'removed': removed, 'qualification': 'unqualified fixture'}
    return report


def real_cycle(nc, p):
    from ravel.workflow import review_independence
    first, second = p['seats']
    from ravel.workflow import role_registry
    reason = review_independence.seat_refusal(role_registry.load(second['role']), second, [first, second])
    if reason:
        return result([reason])
    return result()


def real_rdj(nc, p):
    from ravel.workflow import rdj_loop
    root = nc.path('rdj-probe'); root.mkdir(exist_ok=True)
    computed, factors = rdj_loop.compute_class(root, 'unblind', p['action'],
                                              declared={'class': p['action']['declared_class']})
    if computed != p['action']['declared_class']:
        return result(['consequence_class_downgraded'])
    return result()


def real_repair(nc, p):
    from ravel.workflow import physics_review
    row = p['repair']
    finding = {'check_ids': ['toy-check'], 'required_stages': ['toy-stage'],
               'evidence': [{'path': 'outputs/defect.txt', 'location': '$'}]}
    def cycle_record(identity, content, correction_id):
        return {'event': 'cycle', 'cycle_id': identity, 'correction_id': correction_id,
                'inherited_findings': [deepcopy(finding)],
                'snapshots': [{'path': 'outputs/defect.txt', 'sha256': sha256(content.encode()).hexdigest()}],
                'checks': [{'id': 'toy-check', 'status': 'fail'}], 'utc': '2026-01-01T00:00:00Z'}
    before = cycle_record('before', row['before'], None)
    correction = {'event': 'correction', 'cycle_id': 'before', 'correction_id': 'redo-one',
                  'stages': ['toy-stage'], 'sequence': 2, 'redo_number': row['attempt'],
                  'sha256': 'c' * 64}
    after = cycle_record('after', row['after'], 'redo-one')
    observed = physics_review.correction_progress({}, [before, correction, after],
                                                 view={'findings': [finding]})
    progress = observed['finding_progress'][0]['history'][0]['progress']
    report = result(['repair_no_progress'] if not progress else ())
    report['diagnostics'] = {'redos_consumed': observed['redo_counts_by_stage']['toy-stage']}
    return report


def real_crosscheck(nc, p):
    import json
    from test_worker_broker import make
    from ravel.workflow import review_projection_checks, role_registry
    broker = make(nc.root, nc.patch)
    broker.allowed_actions.add('check run')
    card = role_registry.load('normalization-auditor')
    review_projection_checks.register(broker, card)
    document = broker.workspace / 'inputs/normalization.json'
    document.write_text(json.dumps({'cross_section_pb': 1, 'luminosity_ifb': 1,
        'branching_ratio': 1, 'efficiency': 1, 'reported_yield': 1000}))
    if p['crosscheck']['receipt'] is not None:
        reply = broker.call({'call_id': 'crosscheck', 'action': 'check run',
            'args': {'check_id': 'review.normalization_recompute', 'paths': ['inputs/normalization.json']}})
    else:
        # The hostile prose action explicitly did not execute a validator; the production
        # broker must withhold both successful status and validator identity.
        broker.allowed_actions.add('verbal-check')
        broker.register('verbal-check', lambda args: {'validator_executed': False, 'exit_status': 0,
            'stdout': 'worker verbally asserts a crosscheck'}, derivation='registered_validator',
            validator_id='review.normalization_recompute')
        broker.call({'call_id': 'crosscheck', 'action': 'verbal-check', 'args': {}})
    receipt = broker.verify_ledger()[-1]
    valid = bool(receipt and receipt['status'] == 'ok' and receipt['validator_id'] is not None)
    report = result(notices=['crosscheck_execution_missing', 'method_independence_unverified']
                    if p['crosscheck']['claimed'] and not valid else ())
    report['diagnostics'] = {'receipt': receipt, 'qualification': 'inert normalization fixture'}
    return report


def real_certify(nc, p):
    import json
    from ravel.controller.step import validate
    from ravel.workflow import role_registry
    card = deepcopy(role_registry.load('normalization-auditor'))
    check = 'review.normalization_recompute'
    card['must_check'] = [check]
    card['independence']['kind'] = 'reviewer'
    card['family'] = 'review'
    document = nc.path('normalization.json')
    document.write_text(json.dumps({'cross_section_pb': 1, 'luminosity_ifb': 1,
        'branching_ratio': 1, 'efficiency': 1, 'reported_yield': 1000}))
    params = {check: {'document': document.name}} if p['certification']['validator'] else {}
    report = validate.run_validators(card, {'check_inputs': params},
                                    run_dir=nc.root, scratch=nc.root/'scratch')
    return result(notices=['operation_validator_missing', 'NOT CERTIFIED'] if not report['passed'] else ())


def real_research_join(nc, p):
    import json
    from test_nc_routes_param import _bound_run, PROTOCOL
    from ravel.workflow import research_protocol
    root, artifacts = _bound_run(nc, 'join', done=9)
    path = root / PROTOCOL; record = json.loads(path.read_text())
    ids = {row['id'] for row in p['stages']}
    record['stages'] = [row for row in record['stages'] if row['id'] in ids]
    path.write_text(json.dumps(record))
    try:
        status = research_protocol.methodology_status(root)
    except ValueError:
        return result(['research_stage_population_incomplete'])
    return result(['research_stage_incomplete'] if status['pending'] else ())


def real_baseline(nc, p):
    import json
    from test_nc_routes_param import _bound_run, PROTOCOL
    from ravel.workflow import research_protocol
    root, artifacts = _bound_run(nc, 'baseline', done=3)
    path = root / PROTOCOL; record = json.loads(path.read_text())
    baseline = next(row for row in p['stages'] if row['id'] == 'baseline')
    record['stages'][2]['status'] = baseline['status']
    if baseline['status'] == 'not_applicable':
        record['stages'][2]['reason'] = 'Worker says baseline unnecessary.'
    path.write_text(json.dumps(record))
    try:
        errors = research_protocol.gate_errors(root, 'research_choice', {'scope': 'screen'})
    except ValueError:
        return result(['baseline_review_required'])
    return result(['baseline_review_required'] if errors else ())


def real_idea_barrier(nc, p):
    from test_worker_broker import make
    row = p['ideas']
    broker = make(nc.root, nc.patch, season={'phase': 'sealed' if not row['barrier_open'] else 'open',
        'participants': [{'actor_id': 'stream-a', 'session_id': 'session-a', 'attestation': 'transport'},
                         {'actor_id': 'stream-b', 'session_id': 'session-b', 'attestation': 'transport'}]},
        actor_id='stream-b')
    observed = []
    broker.register('board read', lambda args: observed.append(args) or {'text': CANARY if args['actor_id'] == 'stream-a' else 'own source'}, read_only=True)
    target = 'stream-a' if row['peer_proposal'] in row['reads'] else 'stream-b'
    reply = broker.call({'call_id': 'peer-proposal', 'action': 'board read', 'args': {'actor_id': target}})
    denied = (reply.get('error') or {}).get('code') == 'peer_read_denied'
    report = result(['idea_stream_barrier_closed'] if denied else ())
    report['diagnostics'] = {'broker_reply': reply, 'guard_reads': len(observed),
                             'qualification': 'unqualified stream fixture'}
    assert len(observed) == (0 if denied else 1), report
    return report


def real_child_authority(nc, p):
    from test_research_launch import approved
    from test_checkin2_gate import _write_inputs
    from ravel.workflow import workflow_state
    if p['child']['ci1'] is not None:
        root = approved(nc.root)
    else:
        root = nc.root/'run'; _write_inputs(root, 'smoke')
        workflow_state.main(['init', '--rundir', str(root)])
    errors = workflow_state.verify_approval(str(root), required_plan='smoke')
    return result(['child_ci1_required'] if errors else ())


def real_preregistration(nc, p):
    import json
    from test_research_launch import approved, prereg
    from ravel.workflow import research_launch, research_protocol
    root = approved(nc.root)
    if p['preregistration']['producer'] != 'approved-plan-producer':
        value = prereg(root); value['producer'] = p['preregistration']['producer']
        raw = json.dumps(value).encode(); (root/'research/forged.json').write_bytes(raw)
        record = research_protocol.methodology_status(root)['record']
        record['preregistration'] = {'path': 'research/forged.json', 'sha256': sha256(raw).hexdigest()}
        (root/'research/protocol.json').write_text(json.dumps(record))
    return result(['producer_preregistration_required'] if research_launch.verify(root) else ())


def real_inventory(nc, p):
    from test_worker_broker import make
    broker = make(nc.root, nc.patch)
    calls = []
    row = p['inventory']
    for identity in row['allowed']:
        broker.allowed_actions.add(identity)
        broker.register(identity, lambda args: calls.append(args) or {'inventory': 'inert'}, read_only=True)
    reply = broker.call({'call_id': 'inventory', 'action': row['requested'], 'args': {}})
    report = result(['inventory_provider_restricted'] if (reply.get('error') or {}).get('code') == 'not_allowlisted' else ())
    report['diagnostics'] = {'probe_calls': len(calls), 'broker_reply': reply}
    return report


def real_stage_seats(nc, p):
    from ravel.workflow import research_coordinator_decisions as decisions
    from ravel.workflow import review_independence, role_registry
    assignments = {seat['role']: {'model': seat['model'], 'kind': 'reviewer',
                                  'distinct_family_from': []} for seat in p['seats']}
    dispatch = decisions.dispatch_check('screen', assignments)
    reasons = [review_independence.seat_refusal(role_registry.load(seat['role']), seat, p['seats'])
               for seat in p['seats']]
    relation = review_independence.family_relation({s['role']: s['model'] for s in p['seats']})
    report = result([reason for reason in reasons if reason],
                    disclosures=[review_independence.family_label(relation)] if relation == 'same' else ())
    report['diagnostics'] = {'dispatch_check': dispatch, 'family_relation': relation,
                             'qualification': 'unqualified model/session fixtures'}
    return report


def real_author_diversity(nc, p):
    from ravel.workflow import spawn_rows
    families = set(p['author_families'])
    label = spawn_rows.family_label(families)
    report = result(disclosures=[label] if label == 'single model family' else ())
    report['diagnostics'] = {'family_label': label, 'qualification': 'unqualified supplied family labels'}
    return report
