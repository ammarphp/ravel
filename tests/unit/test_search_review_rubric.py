"""The search-analysis review rubric, its pinned overlay and its place in the reviewer packet.

Every analysis, region, process and value below is invented.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import review_projection_checks as checks
from ravel.workflow import review_rubric as rr

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = ROOT / 'src/ravel/data/review/search_analysis_rubric.json'


def complete():
    """A synthetic review packet of search ANA-0001 that satisfies every computed item."""
    return {
        'schema_version': 1, 'kind': 'search-analysis-review-packet', 'analysis': 'ANA-0001',
        'strategy': {
            'signal_regions': [{'name': 'SR-A', 'motivation': 'high dilepton mass from the heavy resonance'},
                               {'name': 'SR-B', 'motivation': 'boosted topology at large resonance mass'}],
            'blinding': {'statement': 'signal regions stay blinded until the background model is frozen'},
            'data': {'observed': False, 'pseudo_data': {'statement': 'background-only Asimov data from the post-fit model'}}},
        'backgrounds': {
            'processes': [
                {'name': 'BKG-A', 'major': True, 'control_regions': ['CR-A'], 'method': {'kind': 'simulation', 'citation': None}},
                {'name': 'BKG-B', 'major': True, 'control_regions': [],
                 'method': {'kind': 'data-driven', 'citation': 'synthetic method note 1', 'closure': {'result': 'closes within 8%'}}},
                {'name': 'BKG-C', 'major': False, 'control_regions': [], 'method': {'kind': 'simulation', 'citation': None}}],
            'control_regions': [{'name': 'CR-A', 'signal_contamination': {'max_fraction': 0.02}}],
            'normalization_factors': [{'process': 'BKG-A', 'value': 1.04, 'uncertainty': 0.07}],
            'multijet': {'applicable': True, 'method': 'data-driven', 'closure': {'result': 'closes within 15%'}}},
        'validation': {
            'regions': [{'name': 'VR-A', 'post_fit_comparison': 'pseudo-data over prediction 0.97 +- 0.06'}],
            'simulated_samples': [{'name': 'SAMPLE-1', 'heavily_weighted': True, 'effective_events': 5400.0,
                                   'adequacy': 'relative statistical uncertainty below the fitted one in every bin'},
                                  {'name': 'SAMPLE-2', 'heavily_weighted': False}]},
        'multivariate': {'used': True, 'folds': {'by_event_identifier': True, 'count': 4},
                         'evaluated_on_training_folds': False,
                         'overtraining_check': {'result': 'training and held-out response agree'}},
        'systematics': {
            'alternative_sample_comparisons': [{'name': 'ALT-1', 'same_process': True, 'same_campaign': True}],
            'cited_values': [{'name': 'luminosity', 'source': 'synthetic luminosity record'}]},
        'sensitivity': {'previous_analysis': {'reference': 'synthetic previous search ANA-0000'},
                        'same_signal_points': True, 'same_luminosity': True,
                        'comparison': 'expected significance 3.1 against 2.4 at the same point'},
        'note': {'pages': 9, 'page_limit': 10,
                 'floats': [{'name': 'fig-1', 'referenced': True}, {'name': 'tab-1', 'referenced': True}],
                 'build': {'command': 'make note', 'reproduced': True}}}


def no_control_region():
    """The same search with no control region and no cited method for its main background."""
    packet = complete()
    packet['backgrounds']['processes'][0].update(control_regions=[], method={'kind': 'simulation', 'citation': None})
    return packet


def blocking(result):
    return [f for f in result['findings'] if f['materiality'] in ('A', 'B')]


def pinned(tmp_path, overlay, name='overlay.json'):
    path = tmp_path / name
    path.write_text(json.dumps(overlay, indent=2))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def overlay(**parts):
    return {'schema_version': 1, 'kind': 'review-rubric-overlay', 'id': 'synthetic-overlay',
            'rubric': 'search-analysis-review', **parts}


ADDED = {'id': 'X-01', 'section': 'note', 'topic': 'Synthetic added item', 'severity': 'blocking',
         'question': 'Does the note carry the synthetic appendix?', 'evidence': 'The appendix is named.',
         'blocking': 'The synthetic appendix is absent.', 'rule': {'present': ['note.synthetic_appendix']}}


# ---- acceptance 1: without the rubric nothing blocks -----------------------------------------

def test_no_other_registered_check_blocks_a_search_without_a_control_region():
    packet = no_control_region()
    for check_id in sorted(set(checks.CHECKS) - {'review.rubric'}):
        for doc in (packet, {'rubric': 'search-analysis-review', 'packet': packet}):
            assert blocking(checks.run_check(check_id, doc)) == [], check_id


# ---- acceptance 2: the rubric names the item; a complete packet passes -----------------------

def test_a_main_background_without_a_control_region_is_a_blocking_finding_naming_the_item():
    result = checks.run_check('review.rubric', {'packet': no_control_region()})
    assert result['status'] == 'failed' and result['kind'] == 'ravel-check-result'
    found = blocking(result)
    assert [f['item'] for f in found] == ['BKG-01']
    finding = found[0]
    assert finding['id'] == 'review.rubric:BKG-01' and finding['evidence_class'] == 'code_check'
    assert finding['evidence_locators'] == ['check:review.rubric']
    assert 'BKG-01' in finding['summary'] and 'BKG-A' in finding['summary']
    assert finding['misses'] and finding['required_evidence']


def test_a_complete_packet_passes_and_lists_the_judgment_items():
    result = checks.run_check('review.rubric', {'packet': complete()})
    assert result['status'] == 'passed' and result['findings'] == []
    rubric = rr.load('search-analysis-review')
    computed = [i['id'] for i in rubric['items'] if i['rule'] is not None]
    assert result['diagnostics']['satisfied'] == computed
    assert result['diagnostics']['judgment_items'] == [i['id'] for i in rubric['items'] if i['rule'] is None]
    assert result['diagnostics']['overlay'] is None


def _drop(path):
    def change(packet):
        node = packet
        *head, last = path
        for key in head:
            node = node[key]
        del node[last]
    return change


def _set(path, value):
    def change(packet):
        node = packet
        *head, last = path
        for key in head:
            node = node[key]
        node[last] = value
    return change


DEFECTS = [
    ('STR-01', _drop(('strategy', 'signal_regions', 1, 'motivation'))),
    ('STR-01', _set(('strategy', 'signal_regions'), [])),
    ('STR-02', _set(('strategy', 'blinding'), {'statement': '  '})),
    ('STR-03', _drop(('strategy', 'data', 'pseudo_data'))),
    ('STR-03', _drop(('strategy', 'data', 'observed'))),
    ('BKG-01', _set(('backgrounds', 'processes'), [{'name': 'BKG-C', 'major': False}])),
    ('BKG-02', _drop(('backgrounds', 'normalization_factors', 0, 'uncertainty'))),
    ('BKG-02', _drop(('backgrounds', 'normalization_factors'))),
    ('BKG-03', _set(('backgrounds', 'control_regions', 0, 'signal_contamination'), {})),
    ('BKG-04', _drop(('backgrounds', 'multijet', 'closure'))),
    ('BKG-04', _set(('backgrounds', 'multijet'), {'applicable': False})),
    ('VAL-01', _drop(('validation', 'regions', 0, 'post_fit_comparison'))),
    ('VAL-01', _set(('validation', 'regions'), [])),
    ('VAL-02', _drop(('backgrounds', 'processes', 1, 'method', 'closure'))),
    ('VAL-03', _drop(('validation', 'simulated_samples', 0, 'effective_events'))),
    ('MVA-01', _set(('multivariate', 'folds', 'by_event_identifier'), False)),
    ('MVA-02', _set(('multivariate', 'evaluated_on_training_folds'), True)),
    ('MVA-03', _drop(('multivariate', 'overtraining_check'))),
    ('SYS-01', _set(('systematics', 'alternative_sample_comparisons', 0, 'same_campaign'), False)),
    ('SYS-02', _drop(('systematics', 'cited_values', 0, 'source'))),
    ('SEN-01', _set(('sensitivity', 'same_luminosity'), False)),
    ('SEN-01', _drop(('sensitivity', 'comparison'))),
    ('NOTE-01', _set(('note', 'pages'), 11)),
    ('NOTE-03', _set(('note', 'build', 'reproduced'), False)),
]


@pytest.mark.parametrize('item,change', DEFECTS, ids=[f'{i}-{n}' for n, (i, _) in enumerate(DEFECTS)])
def test_each_blocking_item_fires_when_its_evidence_is_removed(item, change):
    packet = complete()
    change(packet)
    result = rr.evaluate(packet)
    assert result['status'] == 'failed'
    assert item in [f['item'] for f in blocking(result)]


def test_declared_alternatives_satisfy_their_items():
    packet = complete()
    packet['strategy']['data'] = {'observed': True}                     # observed data: no pseudo-data statement needed
    packet['multivariate'] = {'used': False}                            # no multivariate method
    packet['backgrounds']['multijet'] = {'applicable': False, 'justification': 'two isolated leptons; below 1% of the yield'}
    packet['sensitivity'] = {'no_previous_analysis': 'no earlier search of this final state exists'}
    del packet['note']['page_limit']                                    # the request set no limit
    packet['note']['pages'] = 40
    assert rr.evaluate(packet)['status'] == 'passed'


def test_an_advisory_item_is_reported_without_blocking():
    packet = complete()
    packet['note']['floats'][0]['referenced'] = False
    result = rr.evaluate(packet)
    assert result['status'] == 'passed' and blocking(result) == []
    assert [(f['item'], f['materiality']) for f in result['findings']] == [('NOTE-02', 'C')]


def test_a_missing_section_or_packet_is_inconclusive_never_a_pass():
    packet = complete()
    del packet['systematics']
    result = rr.evaluate(packet)
    assert result['status'] == 'inconclusive' and result['diagnostics']['sections_missing'] == ['systematics']
    assert result['diagnostics']['unread_items'] == ['SYS-01', 'SYS-02']
    assert checks.run_check('review.rubric', {})['status'] == 'inconclusive'
    assert checks.run_check('review.rubric', {'packet': {'kind': 'something-else'}})['status'] == 'inconclusive'
    del packet['backgrounds']['multijet']                               # a blocking finding outranks the missing section
    assert rr.evaluate(packet)['status'] == 'failed'


def test_true_is_not_one_and_absent_is_not_false():
    packet = complete()
    packet['multivariate']['evaluated_on_training_folds'] = 0
    assert 'MVA-02' in [f['item'] for f in blocking(rr.evaluate(packet))]
    del packet['multivariate']['evaluated_on_training_folds']
    assert 'MVA-02' in [f['item'] for f in blocking(rr.evaluate(packet))]


# ---- the rubric as data ----------------------------------------------------------------------

def test_the_shipped_rubric_follows_its_schema():
    rubric = json.loads(RUBRIC.read_text())
    assert rr.rubric_errors(rubric) == []
    assert rubric['id'] == 'search-analysis-review' and rr.load(rubric['id']) == rubric
    assert 'overlay' not in rubric
    ids = [i['id'] for i in rubric['items']]
    assert len(ids) == len(set(ids))
    assert {i['section'] for i in rubric['items']} == set(rubric['packet']['sections'])
    for item in rubric['items']:
        assert item['evidence'].strip() and item['blocking'].strip() and item['question'].endswith('?')
    assert {i['severity'] for i in rubric['items']} == {'blocking', 'advisory'}
    with pytest.raises(ValueError, match='unknown review rubric'):
        rr.load('not-a-rubric')


@pytest.mark.parametrize('rule', [
    {}, {'present': []}, {'present': ['a b']}, {'present': ['a'], 'equals': {'path': 'a', 'value': 1}},
    {'equals': {'path': 'a', 'value': [1]}}, {'at_most': {'path': 'a'}}, {'at_most': {'path': 'a', 'limit': 'x'}},
    {'each': {'path': 'a'}}, {'each': {'path': 'a', 'require': {'present': ['b']}, 'drop': True}},
    {'all': []}, {'any': [{'unknown': 1}]}, {'when': {'present': ['a']}}, {'matches': {'path': 'a', 'regex': '.*'}}, 'present'])
def test_malformed_rules_are_refused(rule):
    assert rr.rule_errors(rule)
    item = {**ADDED, 'rule': rule}
    assert rr.item_errors(item)


def test_the_committed_rubric_passes_the_generality_scan():
    from ravel.validation import check_generality
    paths = [RUBRIC, ROOT / 'src/ravel/workflow/review_rubric.py', Path(__file__)]
    assert check_generality.main([str(p) for p in paths]) == 0


# ---- acceptance 3: a pinned overlay adds or tightens at run time ------------------------------

def test_an_overlay_adds_an_item_at_run_time(tmp_path):
    pin = pinned(tmp_path, overlay(add=[ADDED]))
    rubric = rr.merged('search-analysis-review', pin)
    assert rubric['items'][-1] == ADDED and rubric['overlay'] == {'id': 'synthetic-overlay', 'sha256': pin['sha256']}
    assert rr.rubric_errors(rubric) == [] and rr.extension_errors(rubric) == []
    result = rr.evaluate(complete(), rubric)
    assert [f['item'] for f in blocking(result)] == ['X-01'] and result['diagnostics']['overlay'] == rubric['overlay']
    packet = complete()
    packet['note']['synthetic_appendix'] = 'appendix A'
    assert rr.evaluate(packet, rubric)['status'] == 'passed'
    # The shipped rubric is unchanged, and the same packet passes without the overlay.
    assert rr.load('search-analysis-review') == json.loads(RUBRIC.read_text())
    assert rr.evaluate(complete())['status'] == 'passed'
    # The reviewer's broker check takes the merged rubric it received.
    assert checks.run_check('review.rubric', {'rubric': rubric, 'packet': complete()})['status'] == 'failed'


def test_an_overlay_tightens_severity_and_adds_a_rule(tmp_path):
    tighten = [{'id': 'NOTE-02', 'severity': 'blocking'},
               {'id': 'NOTE-01', 'rule': {'at_most': {'path': 'note.pages', 'limit': 8}},
                'blocking': 'The note exceeds eight pages.'},
               {'id': 'NOTE-04', 'rule': {'present': ['note.readability_review']}, 'severity': 'blocking'}]
    rubric = rr.merged('search-analysis-review', pinned(tmp_path, overlay(tighten=tighten)))
    items = {i['id']: i for i in rubric['items']}
    base = {i['id']: i for i in rr.load('search-analysis-review')['items']}
    assert items['NOTE-02']['severity'] == 'blocking'
    assert items['NOTE-01']['rule'] == {'all': [base['NOTE-01']['rule'], tighten[1]['rule']]}
    assert items['NOTE-01']['blocking'].startswith(base['NOTE-01']['blocking']) and 'eight pages' in items['NOTE-01']['blocking']
    assert items['NOTE-04']['rule'] == tighten[2]['rule']
    assert rr.extension_errors(rubric) == []
    packet = complete()                                                # nine pages: inside the request limit, above the overlay's
    packet['note']['floats'][0]['referenced'] = False
    assert {f['item'] for f in blocking(rr.evaluate(packet, rubric))} == {'NOTE-01', 'NOTE-02', 'NOTE-04'}
    packet['note'].update(pages=8, readability_review='read by an outside physicist')
    packet['note']['floats'][0]['referenced'] = True
    assert rr.evaluate(packet, rubric)['status'] == 'passed'


@pytest.mark.parametrize('parts,message', [
    ({}, 'at least one row'),
    ({'remove': ['BKG-01'], 'add': [ADDED]}, 'no way to remove'),
    ({'tighten': [{'id': 'BKG-01', 'severity': 'advisory'}]}, 'only raise'),
    ({'tighten': [{'id': 'BKG-01', 'rule': None}]}, 'a rule is an object'),
    ({'tighten': [{'id': 'BKG-01', 'replace_rule': {'present': ['note.pages']}}]}, 'id with any of'),
    ({'tighten': [{'id': 'NO-SUCH', 'severity': 'blocking'}]}, 'not an item'),
    ({'tighten': [{'id': 'BKG-01'}]}, 'id with any of'),
    ({'add': [{**ADDED, 'id': 'BKG-01'}]}, 'already exists'),
    ({'add': [{**ADDED, 'rule': {'unknown': 1}}]}, 'exactly one form'),
    ({'add': [ADDED], 'rubric': 'another-rubric'}, 'is for rubric'),
])
def test_an_overlay_cannot_weaken_remove_or_replace(tmp_path, parts, message):
    with pytest.raises(ValueError, match=message):
        rr.merged('search-analysis-review', pinned(tmp_path, overlay(**parts)))


def test_an_overlay_is_read_only_through_its_pin(tmp_path):
    pin = pinned(tmp_path, overlay(add=[ADDED]))
    Path(pin['path']).write_text(json.dumps(overlay(add=[{**ADDED, 'severity': 'advisory'}])))
    with pytest.raises(ValueError, match='differ from the pinned sha256'):
        rr.merged('search-analysis-review', pin)
    with pytest.raises(ValueError, match='not a readable file'):
        rr.merged('search-analysis-review', {'path': str(tmp_path / 'absent.json'), 'sha256': pin['sha256']})
    with pytest.raises(ValueError, match='pin'):
        rr.merged('search-analysis-review', {'path': pin['path']})
    bad = tmp_path / 'bad.json'
    bad.write_text('not json')
    with pytest.raises(ValueError, match='not a JSON document'):
        rr.merged('search-analysis-review', {'path': str(bad), 'sha256': hashlib.sha256(bad.read_bytes()).hexdigest()})


def test_a_weakened_rubric_document_is_refused_by_the_check(tmp_path):
    base = rr.load('search-analysis-review')
    packet = no_control_region()
    dropped = deepcopy(base)
    dropped['items'] = [i for i in dropped['items'] if i['id'] != 'BKG-01']
    lowered = deepcopy(base)
    next(i for i in lowered['items'] if i['id'] == 'BKG-01')['severity'] = 'advisory'
    replaced = deepcopy(base)
    next(i for i in replaced['items'] if i['id'] == 'BKG-01')['rule'] = {'present': ['backgrounds.processes']}
    unpinned = deepcopy(base)
    unpinned['items'].append(ADDED)
    for weakened in (dropped, lowered, replaced, unpinned, {'id': 'search-analysis-review'}):
        result = checks.run_check('review.rubric', {'rubric': weakened, 'packet': packet})
        assert result['status'] == 'inconclusive' and result['outcome'] == 'rubric_refused'
    assert checks.run_check('review.rubric', {'rubric': 'not-a-rubric', 'packet': packet})['outcome'] == 'rubric_refused'
    assert checks.run_check('review.rubric', {'rubric': base, 'packet': packet})['status'] == 'failed'


# ---- the reviewer path -----------------------------------------------------------------------

@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path.resolve() / 'state'))
    root = tmp_path.resolve() / 'run'
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2, 'delegated': True}))
    (root / 'inputs/request_plan.json').write_text(json.dumps({'nodes': [], 'edges': [], 'claims': []}))
    (root / 'review_packet.json').write_text(json.dumps(no_control_region()))
    return root


@pytest.mark.parametrize('role', ['plan-critic', 'physics-critic', 'skeptical-verifier', 'physics-decider',
                                  'integrity-auditor'])
def test_review_roles_may_run_the_rubric_check(role):
    from ravel.workflow import role_registry
    assert checks.permitted(role_registry.load(role), 'review.rubric')
    row = next(r for r in checks.allowlist()['validators'] if r['id'] == 'review.rubric')
    assert row['module'] == 'ravel.workflow.review_rubric' and row['function'] == 'check' and callable(rr.check)


def test_a_run_without_a_selection_projects_no_rubric(run):
    from ravel.workflow import review_projection as rp
    manifest, _ = rp.build(run, 'physics-critic')
    assert not any(a['id'] == 'rubric' for a in manifest['artifacts'])


def test_reviewers_of_a_run_receive_the_selected_rubric_with_its_overlay(run, tmp_path):
    from ravel.workflow import review_projection as rp
    pin = pinned(tmp_path, overlay(add=[ADDED]))
    selection = rr.select(run, 'search-analysis-review', pin['path'])
    assert selection == {'schema_version': 1, 'kind': 'review-rubric-selection', 'rubric': 'search-analysis-review',
                         'overlay': pin}
    assert json.loads((run / rr.SELECTION).read_text()) == selection
    for role in ('plan-critic', 'physics-critic', 'physics-decider'):
        packet = rp.project(run, role, key='k-' + role, subjects=['review_packet.json'], out_root=tmp_path / 'packets')
        manifest, contents = rp.load(packet)
        rubric = json.loads(contents['ravel:review-rubric/search-analysis-review'])
        assert rubric == rr.merged('search-analysis-review', pin) and rubric['items'][-1]['id'] == 'X-01'
        entry = next(a for a in manifest['artifacts'] if a['id'] == 'rubric')
        assert 'overlay' in entry['projection'] and entry['path'] == 'artifacts/rubric.json'
        # The packet holds the ready check input: the merged rubric with the review-packet subject.
        ready = json.loads(contents['ravel:review-rubric-check/review_packet.json'])
        assert ready == {'rubric': rubric, 'packet': json.loads(contents['review_packet.json'])}
        assert {f['item'] for f in blocking(checks.run_check('review.rubric', ready))} == {'BKG-01', 'X-01'}
    # A subject that is not a review packet gets no check input.
    (run / 'note.json').write_text(json.dumps({'kind': 'something-else'}))
    (run / 'note.txt').write_text('plain text')
    manifest, _ = rp.build(run, 'physics-critic', subjects=['note.json', 'note.txt'])
    ids = [a['id'] for a in manifest['artifacts']]
    capabilities = [i for i in ids if i.startswith('capabilities-')]
    context = [i for i in ids if not i.startswith('capabilities-')]
    assert context[:2] == ['s0000', 's0001'] and context[-1] == 'rubric'
    assert context.count('rubric') == 1
    assert capabilities and ids[-len(capabilities):] == capabilities
    assert not any(i.startswith('rubric-check') for i in ids)
    # The evaluation control arm holds its subjects and nothing else.
    manifest, _ = rp.build(run, 'integrity-auditor', subjects=['review_packet.json'], arm='manuscript-only')
    assert [a['id'] for a in manifest['artifacts']] == ['s0000']


def test_a_reviewer_runs_the_rubric_through_the_broker_and_gets_a_validator_receipt(run, tmp_path):
    from ravel.workflow import agent_worker, broker, review_projection as rp, role_registry
    rr.select(run, 'search-analysis-review', pinned(tmp_path, overlay(add=[ADDED]))['path'])
    role = 'physics-critic'
    card = role_registry.load(role)
    packet = rp.project(run, role, key='k-broker', subjects=['review_packet.json'])
    spec = {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': 'rv-' + role, 'attempt': 1,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': role_registry.card_sha256(role)},
            'transport_preference': ['default'], 'inputs': [],
            'declared_outputs': [{'path': 'outputs/review.json', 'kind': 'review-findings', 'required': False}],
            'budgets': {'max_turns': 5, 'max_wall_seconds': 60, 'max_broker_calls': 20, 'max_cost_usd': None},
            'final_record_schema': 'reviewer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}
    ws = agent_worker.materialize(run, spec, packet=packet)
    target = broker.Broker(run, ws, node_id=spec['node_id'], attempt=1, allowed_actions=['read', 'check run'], max_calls=20)
    checks.register(target, card)
    reply = target.call({'call_id': 'c1', 'action': 'check run', 'args': {
        'check_id': 'review.rubric', 'paths': ['inputs/packet/artifacts/rubric-check-s0000.json']}})
    assert reply['status'] == 'failed', reply
    value = json.loads((ws / json.loads(reply['stdout_tail'])['result']).read_text())
    assert {f['item'] for f in blocking(value)} == {'BKG-01', 'X-01'} and value['diagnostics']['overlay']['id'] == 'synthetic-overlay'
    receipt = json.loads((ws / 'calls/1.json').read_text())
    assert receipt['derivation'] == 'registered_validator' and receipt['validator_id'] == 'review.rubric'
    assert receipt['exit_status'] == 1 and receipt['input_pins'] and receipt['output_pins']
    # The receipt is evidence a blocking finding may cite.
    manifest, _ = rp.load(packet)
    finding = {**blocking(value)[0], 'evidence_class': 'new_receipt', 'evidence_locators': ['receipt:' + reply['receipt_id']]}
    assert rp.finding_errors(run, finding, node_id=spec['node_id'], attempt=1, packet_manifest=manifest) == []


def test_a_changed_or_invalid_selection_refuses_the_projection(run, tmp_path):
    from ravel.workflow import review_projection as rp
    pin = pinned(tmp_path, overlay(add=[ADDED]))
    rr.select(run, 'search-analysis-review', pin['path'])
    Path(pin['path']).write_text(json.dumps(overlay(tighten=[{'id': 'NOTE-02', 'severity': 'blocking'}])))
    with pytest.raises(rp.ProjectionRefused) as refused:
        rp.build(run, 'physics-critic')
    assert refused.value.code == 'rubric_invalid'
    (run / rr.SELECTION).write_text(json.dumps({'rubric': 'search-analysis-review'}))
    with pytest.raises(rp.ProjectionRefused):
        rp.build(run, 'physics-critic')
    with pytest.raises(ValueError, match='unknown review rubric'):
        rr.select(run, 'not-a-rubric')
    assert rr.selected(tmp_path / 'no-run') is None


# ---- command line ----------------------------------------------------------------------------

def test_command_line_shows_selects_and_checks(run, tmp_path, capsys):
    from ravel import cli
    assert cli.FOCUSED_COMMANDS['review-rubric'][0] == 'workflow.review_rubric'
    pin = pinned(tmp_path, overlay(add=[ADDED]))
    assert rr.main(['show']) == 0
    assert json.loads(capsys.readouterr().out) == rr.load('search-analysis-review')
    assert rr.main(['show', '--overlay', pin['path'], '--overlay-sha256', pin['sha256']]) == 0
    assert json.loads(capsys.readouterr().out)['overlay']['sha256'] == pin['sha256']
    assert rr.main(['show', '--overlay', pin['path'], '--overlay-sha256', '0' * 64]) == 2
    assert 'pinned sha256' in capsys.readouterr().err
    good, bad = tmp_path / 'good.json', run / 'review_packet.json'
    good.write_text(json.dumps(complete()))
    assert rr.main(['check', '--packet', str(good)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'passed'
    assert rr.main(['check', '--packet', str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)['findings'][0]['item'] == 'BKG-01'
    assert rr.main(['check', '--packet', str(good), '--rundir', str(run)]) == 2      # no selection yet
    capsys.readouterr()
    assert rr.main(['select', '--rundir', str(run), '--overlay', pin['path']]) == 0
    assert json.loads(capsys.readouterr().out)['overlay'] == pin
    assert rr.main(['check', '--packet', str(good), '--rundir', str(run)]) == 1      # the overlay's added item
    incomplete = complete()
    del incomplete['note']
    good.write_text(json.dumps(incomplete))
    assert rr.main(['check', '--packet', str(good)]) == 3
