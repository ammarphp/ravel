"""Inventory is custody; explicit full source inputs establish reading."""
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph as graph, agent_host, intake, research_cycle as cycle
from ravel.workflow import research_coordinator_decisions as decisions
from test_agent_graph import node, spec, external_response
from test_agent_host import node as host_node, request as host_request, pin as host_pin
from test_research_cycle import write, contract
from test_research_full_cycle_authority import intake as original_intake


def source_request(tmp_path, extensions, *, stale=False):
    catalogue = decisions.catalogue(['quantities'])
    if stale:
        row = next(row for row in catalogue['extensions'] if row['action'] == 'replication-prepare')
        row['source']['sha256'] = '0'*64
    core = write(tmp_path/'core.json', {'catalogue': catalogue, 'prior_operation_effects': []})
    public = {'kind': 'research-action', 'action': 'source-context',
        'arguments_json': json.dumps({'modes': [], 'extensions': extensions}),
        'reason': 'Request complete source; no execution or scientific acceptance.'}
    request_node = node('decision', kind='model', role='designer', inputs=[{
        'id': 'scientific-core', 'path': core['path'], 'sha256': core['sha256']}])
    request_node.update(action='external', parameters={
        'instructions': 'Return only the inert nonvoting source request.',
        'model': 'test-external-model', 'reasoning_effort': 'high', 'max_output_tokens': 256,
        'output_schema': {'type': 'object', 'properties': {key: {'type': 'string'} for key in public},
            'required': list(public), 'additionalProperties': False}})
    root = tmp_path/'request-graph'
    graph.create(root, spec([request_node], calls=1, tokens=256))
    prepared = graph.prepare_external(root, 'decision')
    graph.deliver_external(root, 'decision', external_response(prepared, tmp_path/'response.json', value=public))
    return {'candidate_modes': ['quantities']}, cycle._graph_result(root, 'decision')


def test_unrequested_extensions_remain_in_inventory_without_body_read_credit(tmp_path):
    selected = decisions.catalogue(['quantities'])
    parent = write(tmp_path/'original.json', {'prompt': 'Complete original source control.'})
    inputs = decisions._input_sources({'parent_contract': parent, 'evidence': []}, selected)
    extension = next(row for row in selected['extensions'] if row['action'] == 'replication-prepare')
    assert extension['status'] == 'connected_public_source'
    assert extension['source'] == cycle._pin(extension['source']['path'])
    assert extension['source']['path'] not in {pin['path'] for pin in inputs}
    assert parent in inputs


def test_explicit_extension_request_supplies_the_complete_actual_source(tmp_path):
    value, origin = source_request(tmp_path, ['replication-prepare'])
    pins = decisions.requested_sources(value, origin)
    expected = next(row['source'] for row in decisions.catalogue(['quantities'])['extensions']
        if row['action'] == 'replication-prepare')
    assert pins == [expected]
    # Normal Host source presentation reads all bytes; a catalogue pin alone
    # would not produce this content or establish actual source reading.
    n = host_node(inputs=[host_pin(Path(pins[0]['path']))])
    host = agent_host.AgentHost(max_request_bytes=8_000_000)
    shown = host.prepare_model_context(n, host_request(n))['context']['input_artifacts'][0]
    assert shown['content'] == Path(expected['path']).read_bytes().decode('utf-8')
    assert shown['sha256'] == expected['sha256']


@pytest.mark.parametrize('extensions', [['unknown-extension'], ['replication-prepare', 'replication-prepare'], [7]])
def test_unknown_duplicate_or_untyped_extension_selection_refuses(tmp_path, extensions):
    value, origin = source_request(tmp_path, extensions)
    with pytest.raises(ValueError, match='distinct actual source catalogue extensions'):
        decisions.requested_sources(value, origin)
    assert graph.status(origin['root'])['usage']['calls'] == 1


def test_extension_selection_cannot_refresh_a_stale_original_source_epoch(tmp_path):
    value, origin = source_request(tmp_path, ['replication-prepare'], stale=True)
    with pytest.raises(ValueError, match='original committed catalogue'):
        decisions.requested_sources(value, origin)


def test_complete_original_material_limit_remains_one_point_five_megabytes(tmp_path):
    _, parent = original_intake(tmp_path)
    definition = contract(tmp_path)
    definition['goal_binding'] = {'contract': parent, 'assignment_id': 'original-task'}
    root = tmp_path/'cycle'
    cycle.create(root, definition, base_dir=tmp_path)
    handoff = intake.execution_handoff(parent, base_dir=Path(parent['path']).parent.parent)
    evidence = write(tmp_path/'large-original-source.txt', 'x'*1_500_000)
    value = {'candidate_modes': ['quantities'], 'parent_contract': parent, 'handoff': handoff,
        'context_request': None, 'direct_mapping': None, 'knowledge': None,
        'evidence': [{'pin': evidence, 'purpose': 'model_context'}]}
    before = cycle._load(root)[1]
    assert decisions.MAX_CORE_BYTES == 1_500_000
    with pytest.raises(ValueError, match='complete decision material exceeds1.5MB') as refused:
        decisions.prepare_decision(root, value, tmp_path/'refused', phase='next-action')
    # The refusal names what to page; it never truncates anything itself.
    assert 'largest_normal_inputs=large-original-source.txt:1500000' in str(refused.value)
    assert 'largest_core_sections=' in str(refused.value)
    assert cycle._load(root)[1] == before
    assert not (tmp_path/'refused/scientific-core.json').exists()


def committed_effect_context(tmp_path):
    from test_research_full_cycle_authority import campaign
    from test_research_full_cycle_transport import InertReviewHost
    root = campaign(tmp_path)
    parent = cycle._load(root)[1]['contract']['goal_binding']['contract']
    value = {'candidate_modes': ['quantities'], 'parent_contract': parent,
        'handoff': intake.execution_handoff(parent, base_dir=Path(parent['path']).parent.parent),
        'context_request': None, 'direct_mapping': None, 'knowledge': None, 'evidence': []}
    settings = {'model': 'gpt-5', 'reasoning_effort': 'high', 'adapter': 'chat_completions',
        'max_output_tokens': 256, 'max_wall_seconds': 900}
    public = {'kind': 'research-action', 'action': 'progress', 'arguments_json': '{}',
              'reason': 'Preserve the complete failed engineering effect; no acceptance.'}
    host = InertReviewHost(lambda node, context: public, max_request_bytes=8_000_000)
    prepared = decisions.prepare_decision(root, value, root/'first-source', phase='action')
    specification = decisions.decision_spec(root, prepared, settings, graph_id='first-context')
    origin = decisions.actual(root, root/'first-graph', prepared, specification, host=host, settings=settings)
    failure = {'status': 'action_failed', 'failure': 'Complete fictional failed effect. ' + 'x'*650_000,
               'feedback': {'unresolved': ['Retain this failed result and every prior criticism.']}}
    document = {'action': public['action'], 'arguments': {}, 'origin': origin, 'actual_effect': failure,
                'parent_task_accepted': False, 'scientific_authority_from_checkpoint': False}
    effect = write(root/'complete-effect.json', document)
    cycle._record_coordinator_effect(root, origin, effect)
    prepared = decisions.prepare_decision(root, value, root/'second-source', phase='action',
        effects=[{'origin': origin, 'effect': effect}])
    return root, value, settings, host, prepared, effect, document


def test_complete_committed_effect_is_presented_once_without_discarding_failure_or_feedback(tmp_path):
    root, _, settings, host, prepared, effect, document = committed_effect_context(tmp_path)
    core = json.loads(Path(prepared['core']['path']).read_text())
    assert core['prior_operation_effects'] == [{'effect': effect}]
    assert len(Path(prepared['core']['path']).read_bytes()) < effect['size'] / 2
    assert sum(pin == effect for pin in prepared['inputs']) == 1
    assert decisions.prior_effect_documents(core, prepared['inputs']) == [document]
    specification = decisions.decision_spec(root, prepared, settings, graph_id='second-context')
    origin = decisions.actual(root, root/'second-graph', prepared, specification, host=host, settings=settings)
    shown = [row for row in host.actual_contexts[-1]['input_artifacts'] if row['sha256'] == effect['sha256']]
    assert len(shown) == 1 and json.loads(shown[0]['content']) == document
    assert decisions.prior_effect_documents(core, origin['inputs'])[0]['actual_effect'] == document['actual_effect']
    # Existing actual Graph contexts retain their original inline shape.
    assert decisions.prior_effect_documents({'prior_operation_effects': [document]}, origin['inputs']) == [document]


@pytest.mark.parametrize('damage', ['missing', 'stale', 'uncommitted'])
def test_prior_effect_references_refuse_before_host_call(tmp_path, damage):
    root, _, settings, host, prepared, effect, document = committed_effect_context(tmp_path)
    core = json.loads(Path(prepared['core']['path']).read_text())
    if damage == 'missing':
        prepared['inputs'] = [pin for pin in prepared['inputs'] if pin != effect]
    elif damage == 'stale':
        Path(effect['path']).write_text('{}')
    else:
        forged = write(root/'uncommitted-effect.json', document)
        core['prior_operation_effects'] = [{'effect': forged}]
        new_core = write(Path(prepared['core']['path']), core)
        prepared['core'] = new_core
        prepared['inputs'] = [new_core if pin['path'] == new_core['path'] else
                              forged if pin == effect else pin for pin in prepared['inputs']]
    specification = decisions.decision_spec(root, prepared, settings, graph_id='refused-context')
    before = len(host.actual_contexts)
    with pytest.raises(ValueError):
        decisions.actual(root, root/'refused-graph', prepared, specification, host=host, settings=settings)
    assert len(host.actual_contexts) == before


def test_prior_effect_changed_during_host_call_cannot_be_consumed(tmp_path):
    from langgraph.errors import GraphInterrupt
    root, _, settings, host, prepared, effect, document = committed_effect_context(tmp_path)
    def change_after_presentation(node, context):
        assert any(row['sha256'] == effect['sha256'] for row in context['input_artifacts'])
        Path(effect['path']).write_text('{}')
        return document['origin']['value']['value']
    host.callback = change_after_presentation
    specification = decisions.decision_spec(root, prepared, settings, graph_id='changed-during-context')
    # The Graph may detect changed input bytes before the ending consumer;
    # neither its unresolved interrupt nor the direct custody refusal is success.
    with pytest.raises((ValueError, GraphInterrupt)):
        decisions.actual(root, root/'changed-during-graph', prepared, specification, host=host, settings=settings)


def test_repeated_context_has_one_complete_body_and_lossless_checked_references():
    from copy import deepcopy
    observation = {'status': 'failed', 'feedback': 'Retain every failed comparison. '*20000}
    original = {'question': 'Preserve the complete original question.',
        'experiments': [{'id': 'first', 'observation': observation,
                         'feedback': {'observation': deepcopy(observation), 'unresolved': ['comparison']}}],
        'progress': {'all_experiments': [{'id': 'first', 'observation': deepcopy(observation)}]}}
    compact = decisions.compact_decision_context(original)
    assert decisions.expand_decision_context(compact) == original
    assert len(json.dumps(compact)) < len(json.dumps(original))/2
    assert compact['experiments'][0]['observation'] == observation
    assert compact['progress']['all_experiments'][0]['observation']['$research_context_ref']
    damaged = deepcopy(compact)
    damaged['experiments'][0]['observation']['status'] = 'success'
    with pytest.raises(ValueError, match='context'):
        decisions.expand_decision_context(damaged)
    alias = compact['progress']['all_experiments'][0]['observation']
    alias['$research_context_ref'] = '#/absent'
    with pytest.raises(ValueError, match='context'):
        decisions.expand_decision_context(compact)


def test_context_aliases_refuse_cycles_and_preserve_legacy_plain_documents():
    plain = {'question': 'Original uncompressed context.', 'phase': 'action'}
    assert decisions.expand_decision_context(plain) == plain
    compact = decisions.compact_decision_context({'first': {'body': 'x'*2000}, 'second': {'body': 'x'*2000}})
    compact['second']['$research_context_ref'] = '#/second'
    with pytest.raises(ValueError, match='context'):
        decisions.expand_decision_context(compact)


def test_reference_shaped_user_material_remains_literal():
    original = {'literal': {'$research_context_ref': 'original user text', 'sha256': 'literal'},
                'first': {'body': 'x'*2000}, 'second': {'body': 'x'*2000}}
    assert decisions.expand_decision_context(decisions.compact_decision_context(original)) == original


@pytest.mark.parametrize('material', [[[]]*100001, [{'x'*2000: []}]*6500])
def test_context_expansion_bounds_containers_and_dictionary_keys(material):
    document = {'value': material, 'context_aliases': {'format': 'local-exact-json-v1',
                'references': [], 'expanded_sha256': '0'*64}}
    with pytest.raises(ValueError, match='expansion exceeds'):
        decisions.expand_decision_context(document)


def test_oversized_operational_instrumentation_is_summarized_and_retained_complete(tmp_path, monkeypatch):
    """Only operational metrics are summarized, only beyond the unchanged bound; nothing else shrinks."""
    from test_research_full_cycle_authority import campaign
    from ravel.workflow import research_outcome_metrics
    root = campaign(tmp_path)
    parent = cycle._load(root)[1]['contract']['goal_binding']['contract']
    value = {'candidate_modes': ['quantities'], 'parent_contract': parent,
        'handoff': intake.execution_handoff(parent, base_dir=Path(parent['path']).parent.parent),
        'context_request': None, 'direct_mapping': None, 'knowledge': None, 'evidence': []}
    complete = decisions.prepare_decision(root, value, root/'complete', phase='action')
    full = json.loads(Path(complete['core']['path']).read_text())
    assert 'outcome_metrics' in full['progress'] and 'outcome_metrics_record' not in full['progress']
    total = len(json.dumps(full, sort_keys=True).encode()) + sum(p['size'] for p in complete['inputs'][1:])
    # Isolate this presentation step from the separately tested lossless aliasing.
    monkeypatch.setattr(decisions, 'compact_decision_context', lambda core: core)
    monkeypatch.setattr(decisions, 'MAX_CORE_BYTES', total - 1)
    bounded = decisions.prepare_decision(root, value, root/'bounded', phase='action')
    core = json.loads(Path(bounded['core']['path']).read_text())
    assert 'outcome_metrics' not in core['progress']
    record = core['progress']['outcome_metrics_record']
    assert record == cycle._pin(record['path'])
    retained = json.loads(Path(record['path']).read_text())
    assert retained == full['progress']['outcome_metrics']
    assert core['progress']['outcome_metrics_summary'] == research_outcome_metrics.markdown(retained)
    assert record not in bounded['inputs']
    unchanged = {key: value for key, value in full.items() if key != 'progress'}
    assert {key: value for key, value in core.items() if key != 'progress'} == unchanged
    assert ({k: v for k, v in core['progress'].items() if not k.startswith('outcome_metrics')}
            == {k: v for k, v in full['progress'].items() if k != 'outcome_metrics'})
    monkeypatch.setattr(decisions, 'MAX_CORE_BYTES', len(json.dumps(core, sort_keys=True).encode()))
    with pytest.raises(ValueError, match='complete decision material exceeds1.5MB'):
        decisions.prepare_decision(root, value, root/'refused', phase='action')
    assert not (root/'refused/scientific-core.json').exists() and not (root/'refused/outcome-metrics.json').exists()
