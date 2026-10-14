"""Proposed ordinary role/CLI regressions using only inert fixture boundaries."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from ravel.workflow import agent_graph as graph, agent_host as host, scientific_judgment as judgment
from ravel.workflow import research_cycle, research_board_discussion, research_followup
from ravel.workflow.state_io import atomic_json
from test_physics_review import run, opened
from test_scientific_judgment import prepare, FakeHost
from test_provider_transport import capabilities, document, install_http, Control, node, request


@pytest.fixture
def cycle(run):
    opened(run)
    return run[0]


@pytest.mark.parametrize('adapter',['anthropic','gemini','chat_completions'])
def test_original_scientific_judgment_preparation_and_execution_use_configured_provider(cycle,tmp_path,monkeypatch,adapter):
    binding=prepare(cycle,tmp_path,'critic')
    spec,state=graph._load(Path(binding['graph_root']));n=spec['nodes'][0]
    assert n['action']=='model'
    # Existing synthetic scientific-case fixture supplies the full original
    # role schema; only the provider wire is replaced by an inert connection.
    public=FakeHost().execute(n,graph._request(spec,state,n,'0'*64),Control())['value']
    # The actual role schema has a root anyOf. Every HTTP transport uses
    # the same strict object wrapper and returns the original public record.
    assert 'anyOf' in n['parameters']['output_schema']
    seen=install_http(monkeypatch,document(adapter,{'public_record':public}))
    endpoint={'anthropic':'http://127.0.0.1:8000/v1/messages',
              'gemini':'http://127.0.0.1:8000/v1beta/models/{model}:generateContent',
              'chat_completions':'http://127.0.0.1:8000/v1/chat/completions'}[adapter]
    h=host.AgentHost(adapter=adapter,endpoint=endpoint,privacy='local_only',local_models=['control'],
                     capabilities=capabilities(adapter,max_output_tokens=1024))
    state=judgment.execute_role(binding,h)
    assert state['complete'] and len(seen)==1 and state['usage']['calls']==1
    receipt=graph.model_receipt(binding['graph_root'],binding['node_id'],expected_subject_sha256=binding['subject_sha256'])
    assert receipt['execution_observation']=='local_transport_observed'
    assert receipt['transport']['adapter']==adapter and receipt['transport']['requested_model']=='control'
    assert receipt['transport']['observed_model']=='observed-snapshot' and receipt['public_value']==public
    assert not receipt['physics_validated'] and not receipt['scientific_independence_proven']
    assert 'PRIVATE-' not in json.dumps(receipt)


@pytest.mark.parametrize('action',['responses','anthropic','gemini','command'])
def test_explicit_wrong_adapter_is_refused_without_connection(monkeypatch,action):
    seen=install_http(monkeypatch,document('chat_completions'));n=node(action=action);c=Control()
    h=host.AgentHost(adapter='chat_completions',endpoint='http://127.0.0.1:8000/v1/chat/completions',capabilities=capabilities())
    with pytest.raises(host.HostFailure,match='action differs'): h.execute(n,request(n),c)
    assert seen==[] and c.calls==[]


def test_discussion_cli_consumes_exact_selected_config_with_original_run_boundary(tmp_path,monkeypatch,capsys):
    root=tmp_path/'cycle';root.mkdir()
    cfg={'type':'chat_completions','endpoint':'http://127.0.0.1:8000/v1/chat/completions','privacy':'local_only',
         'local_models':['fixture-model'],'capabilities':capabilities()}
    config=tmp_path/'host.json';atomic_json(config,cfg)
    import hashlib
    pin={'path':'host.json','sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'size':config.stat().st_size}
    req=tmp_path/'request.json';atomic_json(req,{'preparation_pin':{'path':'original-preparation.json','sha256':'a'*64,'size':1},'host_config':pin})
    observed=[];report=tmp_path/'discussion/report.json'
    def run_boundary(cycle,preparation_pin,*,host):
        observed.append((cycle,deepcopy(preparation_pin),host))
        # The run boundary returns the pin of its written report, as the actual entry does.
        report.parent.mkdir();atomic_json(report,{'inert':True})
        return research_cycle._pin(report)
    monkeypatch.setattr(research_board_discussion,'run',run_boundary)
    assert research_cycle.main(['discussion-run','--cycle',str(root),'--request',str(req)])==0
    assert len(observed)==1 and observed[0][2].adapter=='chat_completions' and observed[0][2].privacy=='local_only'
    assert observed[0][1]=={'path':'original-preparation.json','sha256':'a'*64,'size':1}
    # The consumed config is recorded beside the report by its resolved path and exact bytes.
    receipt=json.loads((report.parent/'host-config-receipt.json').read_text())
    assert receipt=={'schema_version':1,'kind':'research-host-config-receipt','report':research_cycle._pin(report),
        'host_config':{'path':str(config.resolve()),'sha256':pin['sha256'],'size':pin['size']}}
    assert json.loads(capsys.readouterr().out)==receipt['report']
    saved=(report.parent/'host-config-receipt.json').read_bytes()
    config.write_text('{}')
    with pytest.raises(SystemExit) as refused:
        research_cycle.main(['discussion-run','--cycle',str(root),'--request',str(req)])
    assert refused.value.code==2 and len(observed)==1
    assert (report.parent/'host-config-receipt.json').read_bytes()==saved


@pytest.mark.parametrize('adapter',['anthropic','gemini','chat_completions','model'])
def test_shared_ideation_builder_provider_selection_keeps_schema_and_budget(tmp_path,adapter):
    context={'kind':'research_ideation_context','stream':'citation_led','instructions':'Use all retained scientific source content.'}
    path=tmp_path/'context.json';atomic_json(path,context)
    import hashlib
    pin={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    options=dict(graph_id='provider-ideation',model='fixture-model',reasoning_effort='high',max_output_tokens=120,max_wall_seconds=30)
    original=research_followup.ideation_spec(pin,**options)
    selected=research_followup.ideation_spec(pin,adapter=adapter,**options)
    assert original['nodes'][0]['action']=='responses' and selected['nodes'][0]['action']==adapter
    expected=deepcopy(original);expected['nodes'][0]['action']=adapter
    assert selected==expected
    with pytest.raises(ValueError):research_followup.ideation_spec(pin,adapter='undeclared-provider',**options)
