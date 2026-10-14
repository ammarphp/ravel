"""Inert connected Host/Graph controls; no network/provider/native/model effects."""
from copy import deepcopy
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import pytest

from ravel.workflow import agent_graph as graph, agent_host, langchain_service as service
from ravel.workflow.state_io import atomic_json, read_json
from test_agent_graph import Host, node, spec, pin
from test_agent_host import quantity_inputs, tool


def running(tmp_path, host=None, n=None):
    """Disclosed running-checkpoint fixture using actual canonical Control custody."""
    host = Host() if host is None else host
    n = node('n') if n is None else n
    root = tmp_path / 'graph'; graph.create(root, spec([n]))
    with graph.file_lock(root / 'state.lock'):
        document, state = graph._load(root)
        state['started_epoch'] = time.time()
        current = state['nodes'][n['id']]
        current.update(status='running', attempt_id='test-current-attempt', attempts=1, generation_attempts=1)
        graph._save(root, state)
        request = graph._request(document, state, document['nodes'][0], graph._host_identity(host))
    control = graph.Control(root, n['id'], current['attempt_id'])
    envelope = {'node': deepcopy(document['nodes'][0]), 'request': request}
    return root, host, control, envelope


def completed(root):
    state = graph.status(root)
    return graph._result(root, state['nodes']['n']['result'])


def test_declared_framework_versions_and_actual_import_origins():
    assert service.identity()['runtime'] == service.REQUIRED
    selected = os.environ.get('RAVEL_CHARGED_FRAMEWORK_ROOT')
    origins = {}
    for name, module in list(sys.modules.items()):
        if name.split('.')[0] not in {'langchain_core', 'langgraph', 'langsmith', 'pydantic', 'pydantic_core'}:
            continue
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if selected: assert path.is_relative_to(Path(selected).resolve()), (name, str(path))
            origins[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    assert 'langchain_core.runnables.base' in origins and 'pydantic' in origins
    output = os.environ.get('RAVEL_CHARGED_FRAMEWORK_OBSERVATION')
    if output:
        intended = (json.dumps({'runtime': service.identity(), 'origins': origins}, sort_keys=True) + '\n').encode()
        with Path(output).open('xb') as stream: stream.write(intended)
        assert Path(output).read_bytes() == intended


def test_actual_framework_node_uses_service_observation_and_reuses_original_call(tmp_path):
    root = tmp_path / 'graph'; graph.create(root, spec([node('n')]))
    host = Host(); first = graph.execute(root, host)
    assert first['complete'] and first['usage']['calls'] == 1 and host.dispatched == ['n']
    attempt = completed(root); observation = attempt['service_observation']
    assert observation['runtime']['runtime'] == service.REQUIRED
    assert observation['effect_authority'] == 'agent_graph.Control.call'
    assert observation['scientific_acceptance'] is False
    assert [event['event'] for event in observation['events']] == ['start', 'end']
    assert observation['result_sha256'] == attempt['result_sha256']
    assert graph.execute(root, host)['usage']['calls'] == 1 and host.dispatched == ['n']
    assert completed(root) == attempt


def test_real_host_tiny_paired_quantity_tool_retains_complete_numerical_return(tmp_path):
    contract, records = quantity_inputs(tmp_path)
    n = tool('quantities', {'contract_input': 'contract', 'records_input': 'records'},
             [pin(contract, 'contract'), pin(records, 'records')]); n['id'] = 'n'
    root = tmp_path / 'graph'; graph.create(root, spec([n]))
    host = agent_host.AgentHost()
    status = graph.execute(root, host)
    assert status['complete'] and status['usage']['calls'] == 1
    attempt = completed(root); result = attempt['result']
    from ravel.physics import quantities
    expected = quantities.calculate(read_json(contract), read_json(records))
    assert result == {'kind': 'ravel_tool_result', 'action': 'quantities', 'value': expected,
                      'execution_authorized': False, 'physics_validated': False}
    assert expected['covariance_order'] == [
        {'weight': weight, 'bin_id': bin_id}
        for weight in expected['contract']['weight_names'] for bin_id in expected['bin_ids']]
    assert len(expected['covariance_order']) > 1
    assert all(len(row) == len(expected['covariance_order']) for row in expected['covariance'])
    assert expected['covariance'][0][2] > 0  # Shared events retain the paired-weight cross moment.
    call = next(iter((root / 'calls').glob('*.json')))
    assert read_json(call)['result'] == result
    assert 'ravel.workflow.langchain_service' in host.identity['sources']


def test_raw_structured_usage_endpoint_model_and_vision_identities_are_opaque(tmp_path):
    # Inert delivery fixture, not an image rendering or live model qualification.
    raw = {'kind': 'model_result', 'value': {'answer': 'RAW-CANARY', 'n': 1.0},
           'model': 'exact-snapshot', 'requested_model': 'exact-model',
           'adapter': 'responses', 'endpoint_sha256': 'a' * 64,
           'usage': {'input_tokens': 11, 'output_tokens': 5, 'reasoning_tokens': 3},
           'vision': {'images': [{'sha256': 'b' * 64, 'wire_sha256': 'c' * 64, 'detail': 'original'}]},
           'structured_response': {'output': [{'text': '{"answer":"RAW-CANARY"}'}]}}
    host = Host(operation=lambda *_: deepcopy(raw))
    n = node('n', kind='model', role='proposer')
    root = tmp_path / 'graph'; graph.create(root, spec([n])); graph.execute(root, host)
    attempt = completed(root)
    assert attempt['result'] == raw and type(attempt['result']['value']['n']) is float
    assert read_json(next((root / 'calls').glob('*.json')))['result'] == raw
    assert 'RAW-CANARY' not in json.dumps(attempt['service_observation'])
    assert 'endpoint_sha256' not in json.dumps(attempt['service_observation'])


def test_schema_reflection_and_finite_local_config_are_on_the_effect_path(tmp_path):
    _, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    assert adapter.get_input_schema() is service.ServiceInput
    assert adapter.get_output_schema() is service.ServiceResult
    assert adapter.config_schema() is service.ServiceConfig
    assert set(adapter.get_input_schema().model_json_schema()['properties']) == {'node', 'request'}
    result = adapter.invoke(envelope, {'tags': ['software-control'], 'configurable': {'local_trace': False}})
    assert result == {'public': 'n'} and host.dispatched == ['n']
    assert adapter.observation['events'] == []
    assert adapter.observation['config']['tags'] == ['software-control']
    returned = adapter.observation; returned['config']['tags'].clear()
    assert adapter.observation['config']['tags'] == ['software-control']


@pytest.mark.parametrize('field', ['request_id', 'binding_sha256', 'node_sha256', 'graph_revision', 'generation'])
def test_changed_request_refuses_before_any_effect(tmp_path, field):
    _, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    altered = deepcopy(envelope)
    altered['request'][field] = 1 if type(altered['request'][field]) is int else 'e' * 64
    with pytest.raises(ValueError): adapter.invoke(altered)
    assert host.dispatched == [] and graph.status(control.root)['usage']['calls'] == 0


@pytest.mark.parametrize('change', ['attempt', 'generation', 'host', 'cancel', 'deadline'])
def test_current_authority_is_rechecked_after_adapter_preparation(tmp_path, change):
    root, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    if change == 'host':
        host.identity = {'test_fixture': 'replacement-host'}
    else:
        with graph.file_lock(root / 'state.lock'):
            _, state = graph._load(root)
            if change == 'attempt': state['nodes']['n']['attempt_id'] = 'replacement-attempt'
            if change == 'generation': state['nodes']['n']['generation'] += 1
            if change == 'cancel': state['cancelled'] = True
            if change == 'deadline': state['started_epoch'] = time.time() - 4000
            graph._save(root, state)
    with pytest.raises(ValueError): adapter.invoke(envelope)
    assert host.dispatched == [] and graph.status(root)['usage']['calls'] == 0


@pytest.mark.parametrize('change', ['tuple', 'bool', 'unknown'])
def test_strict_types_and_keys_cannot_alias_an_admitted_request(tmp_path, change):
    _, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    altered = deepcopy(envelope)
    if change == 'tuple': altered['node']['depends_on'] = ()
    if change == 'bool': altered['request']['schema_version'] = True
    if change == 'unknown': altered['request']['messages'] = []
    with pytest.raises(ValueError): adapter.invoke(altered)
    assert host.dispatched == []


@pytest.mark.parametrize('config', [
    {'callbacks': []}, {'metadata': {'secret': 'RAW-CANARY'}}, {'max_concurrency': 2},
    {'configurable': {'local_trace': 1}}, {'configurable': {'retry': True}}, {'tags': [1]},
])
def test_ambient_callback_and_untyped_config_are_not_effect_authority(tmp_path, config):
    _, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    with pytest.raises(ValueError): adapter.invoke(envelope, config)
    assert host.dispatched == []


@pytest.mark.parametrize('flag', ['LANGCHAIN_TRACING', 'LANGCHAIN_HANDLER', 'LANGCHAIN_TRACING_V2', 'LANGSMITH_TRACING'])
def test_ambient_cloud_trace_refuses_without_creating_a_client(tmp_path, monkeypatch, flag):
    _, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    monkeypatch.setenv(flag, 'true')
    with pytest.raises(service.ServiceError, match='cloud tracing'): adapter.invoke(envelope)
    assert host.dispatched == [] and graph.status(control.root)['usage']['calls'] == 0


def test_inherited_context_callbacks_are_not_presented_the_service_body(tmp_path, monkeypatch):
    from langchain_core.tracers import context as tracing
    class Forbidden(service._LocalTrace):
        def on_chain_start(self, *args, **kwargs): pytest.fail('inherited callback consumed content')
    var = ContextVar('software-control-inherited-callback', default=None)
    monkeypatch.setattr(tracing, '_configure_hooks', [*tracing._configure_hooks, (var, True, None, None)])
    token = var.set(Forbidden())
    try:
        _, host, control, envelope = running(tmp_path)
        adapter = service.ChargedService(host, **envelope, control=control)
        assert adapter.invoke(envelope) == {'public': 'n'}
    finally: var.reset(token)


def test_global_callback_hook_and_debug_refuse_before_dispatch(tmp_path, monkeypatch):
    from langchain_core.tracers import context as tracing
    from langchain_core import globals as settings
    _, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    var = ContextVar('software-control-global-callback', default=service._LocalTrace())
    monkeypatch.setattr(tracing, '_configure_hooks', [*tracing._configure_hooks, (var, True, None, None)])
    with pytest.raises(service.ServiceError, match='callback hooks'): adapter.invoke(envelope)
    assert host.dispatched == []
    monkeypatch.setattr(tracing, '_configure_hooks', [])
    monkeypatch.setattr(settings, '_debug', True)
    second = service.ChargedService(host, **envelope, control=control)
    with pytest.raises(service.ServiceError, match='local callbacks'): second.invoke(envelope)
    assert host.dispatched == []


def test_unknown_effect_is_held_and_no_framework_retry_is_available(tmp_path):
    dispatched = []
    def ambiguous(*_):
        dispatched.append(True)
        raise agent_host.HostFailure('inert unknown dispatch', ambiguous=True, retryable=True)
    host = Host(operation=ambiguous)
    root = tmp_path / 'graph'; graph.create(root, spec([node('n', attempts=3)]))
    first = graph.execute(root, host)
    assert first['nodes']['n']['status'] == 'ambiguous' and first['usage']['calls'] == 1
    assert graph.execute(root, host)['usage']['calls'] == 1 and len(dispatched) == 1


@pytest.mark.parametrize('method', ['with_retry', 'with_fallbacks', 'batch', 'stream'])
def test_framework_effect_multiplication_is_not_a_service_api(tmp_path, method):
    _, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    with pytest.raises(service.ServiceError): getattr(adapter, method)(envelope)
    assert host.dispatched == []


def test_single_use_adapter_does_not_repeat_a_completed_dispatch(tmp_path):
    _, host, control, envelope = running(tmp_path)
    adapter = service.ChargedService(host, **envelope, control=control)
    assert adapter.invoke(envelope) == {'public': 'n'}
    with pytest.raises(service.ServiceError, match='single-use'): adapter.invoke(envelope)
    assert host.dispatched == ['n'] and graph.status(control.root)['usage']['calls'] == 1


def test_missing_real_control_or_bare_messages_never_authorize_service(tmp_path):
    _, host, control, envelope = running(tmp_path)
    with pytest.raises(service.ServiceError, match='actual Graph Control'):
        service.ChargedService(host, **envelope, control=object())
    adapter = service.ChargedService(host, **envelope, control=control)
    with pytest.raises(ValueError): adapter.invoke({'messages': []})
    assert host.dispatched == []


def test_host_mutation_of_consumed_node_is_refused_before_call_reservation(tmp_path):
    class AlteredHost(Host):
        def execute(self, item, request, control):
            item['parameters']['unadmitted'] = True
            return super().execute(item, request, control)
    root = tmp_path / 'graph'; host = AlteredHost(); graph.create(root, spec([node('n')]))
    result = graph.execute(root, host)
    assert result['nodes']['n']['status'] == 'failed' and result['usage']['calls'] == 0
    assert host.dispatched == []


def test_artifact_change_after_real_reservation_is_refused_before_effect(tmp_path, monkeypatch):
    data = tmp_path / 'input.txt'; data.write_text('original')
    root = tmp_path / 'graph'; host = Host(); graph.create(root, spec([node('n', inputs=[pin(data)])]))
    original = graph.Control.call
    original_check = graph._artifact_checks
    refused_checks = []
    def artifact_check(item):
        try:
            return original_check(item)
        except graph.GraphError as exc:
            state = read_json(root / 'graph_state.json')
            refused_checks.append({'message': str(exc), 'calls': state['usage']['calls'],
                                   'node_status': state['nodes']['n']['status']})
            raise
    def call(control, label, kind, request, function, output_tokens=0):
        def late():
            data.write_text('changed after reservation')
            return function()
        return original(control, label, kind, request, late, output_tokens=output_tokens)
    monkeypatch.setattr(graph.Control, 'call', call)
    monkeypatch.setattr(graph, '_artifact_checks', artifact_check)
    with pytest.raises(graph.GraphError, match='input artifact changed: data; supply an explicit graph revision'):
        graph.execute(root, host)
    result = graph.status(root)
    assert result['nodes']['n']['status'] == 'failed' and result['usage']['calls'] == 1
    assert host.dispatched == []
    assert read_json(next((root / 'calls').glob('*.json')))['status'] == 'failed'
    assert refused_checks and refused_checks[0]['calls'] == 1 and refused_checks[0]['node_status'] == 'running'
    assert all(check['message'] == 'input artifact changed: data; supply an explicit graph revision'
               for check in refused_checks)
    current = result['nodes']['n']
    assert current['attempts'] == current['generation_attempts'] == 1 and current['result'] is None
    assert current['error'] == {'type': 'GraphError', 'message': refused_checks[0]['message']}
    assert current['retryable'] is False and list((root / 'attempts').glob('*.json')) == []
    calls = list((root / 'calls').glob('*.json')); assert len(calls) == 1
    receipt = read_json(calls[0])
    assert receipt['attempt_id'] == current['attempt_id'] and receipt['error_type'] == 'GraphError'
    assert receipt['retryable'] is False and result['calls'][receipt['call_id']]['status'] == 'failed'


def test_returned_runnable_cannot_turn_a_host_result_into_a_second_effect(tmp_path):
    from langchain_core.runnables import RunnableLambda
    other = []
    host = Host(operation=lambda *_: RunnableLambda(lambda _: other.append(True)))
    _, host, control, envelope = running(tmp_path, host)
    adapter = service.ChargedService(host, **envelope, control=control)
    # The original Control's JSON commitment already refuses the object, before
    # RunnableLambda can perform its automatic returned-Runnable invocation.
    with pytest.raises((TypeError, ValueError)): adapter.invoke(envelope)
    assert other == [] and host.dispatched == ['n']
