"""Synthetic siblings for run-bound retrieval and source refusal custody."""
from copy import deepcopy
import json

import pytest


def row(**updates):
    value = {'kind': 'forbidden-source', 'classes': [], 'identifiers': {},
             'paths': ['refs/**/*.bin'], 'origin': 'harness',
             'statement': 'Withhold the declared source.', 'evidence': []}
    value.update(updates)
    return value


def setup(tmp_path, monkeypatch, restrictions=(), role='executor'):
    from ravel.workflow import knowledge_broker as kb
    from ravel.workflow.broker import work_root
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'; (run / 'inputs').mkdir(parents=True)
    (run / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': list(restrictions)}))
    ws = work_root(run) / 'worker/1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (ws / name).mkdir(parents=True)
    entries = [
        {'id': 'doc:visible', 'kind': 'doc', 'title': 'Visible guide', 'summary': 'Synthetic definitions',
         'source': {'path': 'refs/guide.txt', 'sha256': '1' * 64}, 'links': {}},
        {'id': 'doc:hidden', 'kind': 'doc', 'title': 'Hidden guide', 'summary': 'PRIVATE VALUE 37',
         'source': {'path': 'refs/deep/value.bin', 'sha256': '2' * 64}, 'links': {}},
        {'id': 'doc:quantity', 'kind': 'doc', 'title': 'Quantity table', 'summary': 'PRIVATE QUANTITY 41',
         'source': {'path': 'refs/table.txt', 'quantities': ['edge_value'], 'sha256': '3' * 64}, 'links': {}}
    ]
    atlas = tmp_path / 'atlas.json'
    atlas.write_text(json.dumps({'schema_version': 1, 'kind': 'knowledge-atlas', 'entries': entries}))
    broker = kb.create(run, ws, role=role, atlas_path=atlas, node_id='worker', attempt=1,
                       allowed_actions=['read', 'write', 'knowledge.show', 'knowledge.find', 'knowledge'], max_calls=40)
    return kb, broker, entries


def call(broker, identity, n='one'):
    return broker.call({'call_id': n, 'action': 'knowledge.show', 'args': {'id': identity}})


def answer(broker, reply):
    from ravel.workflow.broker import locate
    return json.loads(locate(broker.rundir, reply['outputs'][0]['path']).read_text())


def test_query_cannot_override_run_binding_and_is_receipted(tmp_path, monkeypatch):
    kb, broker, _ = setup(tmp_path, monkeypatch)
    denied = broker.call({'call_id': 'spoof', 'action': 'knowledge.show',
                         'args': {'id': 'doc:visible', 'rundir': '/different-run'}})
    assert denied['status'] == 'refused'
    reply = call(broker, 'doc:visible')
    assert reply['status'] == 'ok'
    result = answer(broker, reply)
    assert result['binding']['run_id'] == kb.run_id(broker.rundir)
    assert result['binding']['node_id'] == 'worker' and result['binding']['role'] == 'executor'
    receipt = broker.verify_ledger()[-1]
    assert receipt['derivation'] == 'retrieval'
    assert receipt['policy']['source_restriction_sha256'] == kb.policy_digest(broker.rundir)
    served = [json.loads(x) for x in (broker.rundir / 'knowledge/served.jsonl').read_text().splitlines()]
    assert served[-1]['run_id'] == kb.run_id(broker.rundir)
    assert served[-1]['item_ids'] == ['doc:visible']
    assert broker.call({'call_id': 'one', 'action': 'knowledge.show', 'args': {'id': 'doc:visible'}}) == reply
    assert len((broker.rundir / 'knowledge/served.jsonl').read_text().splitlines()) == len(served)


def test_glob_excludes_read_inventory_and_bundle_with_refusals(tmp_path, monkeypatch):
    kb, broker, entries = setup(tmp_path, monkeypatch, [row()])
    (broker.workspace / 'inputs/refs/deep').mkdir(parents=True)
    (broker.workspace / 'inputs/refs/deep/value.bin').write_text('PRIVATE VALUE 37')
    denied = broker.call({'call_id': 'read-hidden', 'action': 'read',
                          'args': {'path': 'inputs//./refs/deep/value.bin'}})
    assert denied['status'] == 'refused' and denied['error']['code'] == 'forbidden_source'
    assert kb.policy_digest(broker.rundir) in denied['error']['message']
    for surface in ('inventory', 'bundle'):
        visible, withheld = broker.filter_sources(entries, surface=surface)
        assert 'doc:hidden' not in {x['id'] for x in visible}
        assert withheld[0]['id'] == 'doc:hidden' and withheld[0]['receipt_id']
        assert 'PRIVATE VALUE' not in json.dumps(withheld)
    reply = call(broker, 'doc:hidden')
    assert reply['status'] == 'refused' and reply['error']['code'] == 'forbidden_source'
    assert broker.verify_ledger()[-1]['status'] == 'refused'


def test_scoped_quantity_is_withheld_but_same_source_definitions_survive(tmp_path, monkeypatch):
    restriction = row(kind='no-value-extraction', paths=[], scope={'quantities': ['edge_value']})
    kb, broker, entries = setup(tmp_path, monkeypatch, [restriction])
    reply = call(broker, 'doc:quantity')
    assert reply['status'] == 'refused' and reply['error']['code'] == 'forbidden_source'
    definitions = deepcopy(entries[-1]); definitions['source']['quantities'] = []
    definitions['summary'] = 'Definitions only'
    visible, withheld = broker.filter_sources([definitions], surface='bundle')
    assert visible == [definitions] and withheld == []
    reply = call(broker, 'doc:visible', 'definitions')
    assert reply['status'] == 'ok'
    assert 'PRIVATE QUANTITY' not in json.dumps(answer(broker, reply))


def test_source_policy_glob_and_quantity_semantics():
    from ravel.workflow.source_policy import matches, digest, from_reading
    restriction = row()
    assert matches([restriction], {'path': 'refs/value.bin'}) == [restriction]
    assert matches([restriction], {'path': 'refs/a/b/value.bin'}) == [restriction]
    assert matches([restriction], {'path': 'refs/value.txt'}) == []
    scoped = row(kind='no-value-extraction', paths=[], identifiers={'analysis': ['synthetic-source']},
                 scope={'quantities': ['edge_value']})
    assert matches([scoped], {'analysis': 'synthetic-source', 'quantities': ['edge_value']}) == [scoped]
    assert matches([scoped], {'analysis': 'synthetic-source', 'quantities': ['selection']}) == []
    assert matches([scoped], {'analysis': 'sibling-source', 'quantities': ['edge_value']}) == []
    assert digest([restriction]) != digest([dict(restriction, paths=['other/*'])])
    assert digest([scoped]) != digest([dict(scoped, scope={'quantities': ['other_value']})])
    assert from_reading({'source_restrictions': [scoped, restriction]}) == sorted([scoped, restriction], key=lambda r: (r['kind'], r['statement']))


def test_worker_materialization_never_copies_withheld_input(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker as worker
    from ravel.workflow.broker import sha
    from test_agent_worker import spec
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'; (run / 'inputs/refs/deep').mkdir(parents=True)
    (run / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': [row()]}))
    target = run / 'inputs/refs/deep/value.bin'; target.write_text('PRIVATE VALUE 37')
    s = spec(); s['inputs'] = [{'pin': {'path': 'inputs/refs/deep/value.bin', 'sha256': sha(target)}, 'as': 'inputs/renamed.txt'}]
    ws = worker.materialize(run, s)
    assert not (ws / 'inputs/renamed.txt').exists()
    receipts = [json.loads(p.read_text()) for p in (ws / 'calls').glob('*.json')]
    assert receipts and all(r['status'] == 'refused' for r in receipts)
    assert receipts[0]['reply']['error']['code'] == 'forbidden_source'


def test_nested_source_metadata_keeps_quantity_and_selector_together(tmp_path, monkeypatch):
    restriction = row(kind='no-value-extraction', paths=[], identifiers={'analysis': ['synthetic-source']},
                      scope={'quantities': ['edge_value']})
    _, broker, _ = setup(tmp_path, monkeypatch, [restriction])
    item = {'id': 'table:nested', 'quantities': ['edge_value'],
            'source': {'path': 'refs/another.txt', 'analysis': 'synthetic-source'}}
    visible, withheld = broker.filter_sources([item], surface='bundle')
    assert not visible and withheld[0]['id'] == item['id']


def test_filtered_sources_do_not_consume_find_limit(tmp_path, monkeypatch):
    _, broker, entries = setup(tmp_path, monkeypatch, [row()])
    for entry in entries:
        entry['title'] = 'Calibration detector response'
        entry['summary'] = 'Calibration detector response definitions'
    entries[1]['id'] = 'doc:a-hidden'
    entries.extend({'id': 'doc:sibling-' + str(i), 'kind': 'doc', 'title': 'Other convention',
                    'summary': 'Unrelated definitions', 'links': {},
                    'source': {'path': 'refs/sibling-' + str(i) + '.txt'}} for i in range(40))
    broker.atlas_path.write_text(json.dumps({'kind': 'knowledge-atlas', 'schema_version': 1, 'entries': entries}))
    reply = broker.call({'call_id': 'find', 'action': 'knowledge.find', 'args': {'text': 'calibration detector response', 'limit': 1}})
    assert reply['status'] == 'ok'
    result = answer(broker, reply)
    assert len(result['results']) == 1 and result['results'][0]['id'] != 'doc:a-hidden'
    assert result['withheld'][0]['id'] == 'doc:a-hidden'


def test_binding_budget_removes_plan_ids_for_dropped_results(tmp_path, monkeypatch):
    _, broker, entries = setup(tmp_path, monkeypatch)
    entries[0].update(id='op:synthetic', kind='op', op={'examples': [{}], 'validation_tier': 'registered'},
                      links={'docs': ['doc:quantity'], 'handbooks': []})
    entries[2]['summary'] = 'Definitions ' * 50
    broker.atlas_path.write_text(json.dumps({'kind': 'knowledge-atlas', 'schema_version': 1, 'entries': entries}))
    broker.allowed_actions.add('knowledge.plan_check')
    reply = broker.call({'call_id': 'plan', 'action': 'knowledge.plan_check',
                         'args': {'plan': {'nodes': [{'id': 'a', 'operation': 'synthetic'}]}, 'max_bytes': 1800}})
    assert reply['status'] == 'ok'
    result = answer(broker, reply)
    from ravel.workflow.knowledge_atlas import encode, digest
    assert len(encode(result)) <= 1800
    assert set(result['nodes'][0]['served_ids']) <= set(result['served_ids'])
    sha = result.pop('result_sha256')
    assert sha == digest(encode(result))


def test_changed_policy_refuses_existing_binding(tmp_path, monkeypatch):
    _, broker, _ = setup(tmp_path, monkeypatch)
    (broker.rundir / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': [row()]}))
    reply = call(broker, 'doc:visible')
    assert reply['status'] == 'refused' and reply['error']['code'] == 'forbidden_source'
    assert broker.verify_ledger()[-1]['status'] == 'refused'


@pytest.mark.parametrize('args', [{'id': 'doc:visible', 'atlas_path': '/outside'},
                                  {'id': 'doc:visible', 'binding': {}},
                                  {'id': 'doc:visible', 'floor': 0}])
def test_untrusted_file_or_binding_overrides_are_refused(tmp_path, monkeypatch, args):
    _, broker, _ = setup(tmp_path, monkeypatch)
    reply = broker.call({'call_id': 'override', 'action': 'knowledge.show', 'args': args})
    assert reply['status'] == 'refused' and reply['error']['code'] == 'invalid_args'


def test_malformed_policy_never_serves_sources(tmp_path, monkeypatch):
    _, broker, _ = setup(tmp_path, monkeypatch)
    (broker.rundir / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': [row(paths='bad')]}))
    reply = call(broker, 'doc:visible')
    assert reply['status'] != 'ok' and reply['outputs'] == []


def test_reviewer_cannot_read_a_lesson_by_exact_id(tmp_path, monkeypatch):
    _, broker, entries = setup(tmp_path, monkeypatch, role='skeptical-verifier')
    entries[0].update(id='lesson:synthetic', kind='lesson', summary='PRIVATE LESSON 43')
    broker.atlas_path.write_text(json.dumps({'kind': 'knowledge-atlas', 'schema_version': 1, 'entries': entries}))
    reply = call(broker, 'lesson:synthetic')
    assert reply['status'] == 'refused' and reply['outputs'] == []
    assert 'PRIVATE LESSON' not in json.dumps(reply)


def test_descriptor_pattern_restrictions_remain_effective(tmp_path, monkeypatch):
    kb, broker, _ = setup(tmp_path, monkeypatch)
    second = kb.create(broker.rundir, broker.workspace, role='executor', node_id='worker', attempt=1,
                       allowed_actions=['read'], max_calls=40, forbidden_sources=['inputs/private*'])
    reply = second.call({'call_id': 'legacy-pattern', 'action': 'read', 'args': {'path': 'inputs//./private.txt'}})
    assert reply['status'] == 'refused' and reply['error']['code'] == 'forbidden_source'


def test_scoped_input_alias_cannot_be_read_or_copied(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker as worker
    from ravel.workflow.broker import sha
    from test_agent_worker import spec
    kb, broker, _ = setup(tmp_path, monkeypatch, [row(kind='no-value-extraction', paths=[], scope={'quantities': ['edge_value']})])
    target = broker.rundir / 'inputs/data.txt'; target.write_text('PRIVATE QUANTITY 41')
    s = spec(name='sibling'); s['inputs'] = [{'pin': {'path': 'inputs/data.txt', 'sha256': sha(target), 'quantities': ['edge_value']},
                                          'as': 'inputs/renamed.txt'}]
    ws = worker.materialize(broker.rundir, s)
    assert not (ws / 'inputs/renamed.txt').exists()
    bound = kb.create(broker.rundir, ws, role='executor', node_id='sibling', attempt=1, allowed_actions=['read'], max_calls=40)
    (ws / 'inputs/renamed.txt').write_text('A later copy cannot grant read access')
    reply = bound.call({'call_id': 'later', 'action': 'read', 'args': {'path': 'inputs/renamed.txt'}})
    assert reply['status'] == 'refused' and reply['error']['code'] == 'forbidden_source'


def test_worker_inventory_rejects_malformed_hidden_copy(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker as worker
    from test_agent_worker import spec
    _, broker, _ = setup(tmp_path, monkeypatch, [row()])
    s = spec(name='sibling'); s['inputs'] = [{'pin': {'path': 'refs/hidden.bin', 'sha256': '0' * 64},
                                          'as': 'inputs/value.txt', 'unexpected': True}]
    with pytest.raises(ValueError, match='input copy'):
        worker.materialize(broker.rundir, s)


def test_failed_result_write_never_records_a_successful_serve(tmp_path, monkeypatch):
    _, broker, _ = setup(tmp_path, monkeypatch)
    outside = tmp_path / 'outside'; outside.mkdir()
    (broker.workspace / 'outputs/knowledge').symlink_to(outside)
    reply = call(broker, 'doc:visible')
    assert reply['status'] == 'refused' and reply['outputs'] == []
    assert list(outside.iterdir()) == []
    assert not (broker.rundir / 'knowledge/served.jsonl').exists()


@pytest.mark.parametrize('variant', ['case', 'copy', 'hardlink', 'workspace'])
def test_withheld_bytes_cannot_be_copied_through_another_path(tmp_path, monkeypatch, variant):
    import os
    from ravel.workflow import agent_worker as worker
    from ravel.workflow.broker import sha, work_root
    from test_agent_worker import spec
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'; (run / 'inputs/refs/deep').mkdir(parents=True)
    (run / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': [row()]}))
    target = run / 'inputs/refs/deep/value.bin'; target.write_text('PRIVATE VALUE 37')
    if variant == 'case':
        path = 'inputs/REFS/deep/value.bin'
    elif variant == 'copy':
        (run / 'inputs/other.txt').write_text('PRIVATE VALUE 37'); path = 'inputs/other.txt'
    elif variant == 'hardlink':
        os.link(target, run / 'inputs/linked.txt'); path = 'inputs/linked.txt'
    else:
        folder = work_root(run) / 'prior/1/inputs/refs/deep'; folder.mkdir(parents=True)
        (folder / 'value.bin').write_text('PRIVATE VALUE 37'); path = 'agent-work/prior/1/inputs/refs/deep/value.bin'
    s = spec(); s['inputs'] = [{'pin': {'path': path, 'sha256': sha(target)}, 'as': 'inputs/renamed.txt'}]
    ws = worker.materialize(run, s)
    assert not (ws / 'inputs/renamed.txt').exists()
    receipts = [json.loads(p.read_text()) for p in (ws / 'calls').glob('*.json')]
    assert receipts and receipts[0]['reply']['error']['code'] == 'forbidden_source'


def test_unrestricted_byte_identical_input_is_still_copied(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker as worker
    from ravel.workflow.broker import sha
    from test_agent_worker import spec
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'; (run / 'inputs/refs').mkdir(parents=True)
    (run / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': [row()]}))
    target = run / 'inputs/refs/value.txt'; target.write_text('Public definitions')
    s = spec(); s['inputs'] = [{'pin': {'path': 'inputs/refs/value.txt', 'sha256': sha(target)}, 'as': 'inputs/renamed.txt'}]
    ws = worker.materialize(run, s)
    assert (ws / 'inputs/renamed.txt').read_text() == 'Public definitions'


def test_production_knowledge_tools_serve_the_shipped_atlas_with_example_paths(tmp_path, monkeypatch):
    """The shipped atlas carries absolute example paths; a search over it is served, not failed."""
    from ravel.workflow import role_registry, tool_gate, toolbelt
    from ravel.workflow.broker import work_root
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'; run.mkdir()
    ws = work_root(run) / 'worker/1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (ws / name).mkdir(parents=True)
    tools = toolbelt.for_card(role_registry.load('analysis-author'))
    broker = tool_gate.production_broker(run, ws, tools=tools, role='analysis-author', node_id='worker', attempt=1,
                                         max_calls=5)
    for n, (name, args) in enumerate([('knowledge_find', {'text': 'calculation contract'}), ('knowledge_coverage', {})]):
        reply = broker.call(toolbelt.to_request(tools, name, args, f'k{n}'))
        assert reply['status'] == 'ok', (name, reply)
    outside = broker.call({'call_id': 'k9', 'action': 'knowledge query', 'args': {'op': 'xsec', 'args': {}}})
    assert outside['error']['code'] == 'not_allowlisted'
