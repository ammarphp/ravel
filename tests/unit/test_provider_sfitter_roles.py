"""Proposed connected SFitter provider controls; all wire/launches are inert.

These exercise the original source fixtures, Graph/cycle accounting and exact
reconstruction consumers. No live provider, native fitter or scientific run.
"""
from copy import deepcopy
import json
from pathlib import Path
import platform
import subprocess

import pytest

from ravel.workflow import agent_graph as g, agent_host as ah, sfitter_workflow as w
from ravel.workflow import sfitter_conductor as c, sfitter_application as a
from ravel.workflow import review_context as rc
from ravel.workflow.state_io import read_json
from test_provider_transport import capabilities, document, install_http, Control
from test_sfitter_adapter import workflow_fixture, save, pin
from test_sfitter_conductor import proposal
from test_sfitter_source_context import references
import test_sfitter_application as app_controls


@pytest.fixture(autouse=True)
def no_external_process(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('external process forbidden in provider source controls')
    for name in ('Popen', 'run', 'check_output', 'check_call', 'call'):
        monkeypatch.setattr(subprocess, name, denied)
    monkeypatch.setattr(platform, 'platform', lambda: 'inert-provider-control')


def selected(tmp, action):
    wf, docs, _ = workflow_fixture(tmp)
    if action is not None:
        wf['model']['adapter'] = action
    return wf, docs, save(tmp/'workflow.json', wf)


def mocked_host(monkeypatch, adapter, value, model):
    seen = install_http(monkeypatch, document(adapter, value))
    endpoint = {'anthropic': 'http://127.0.0.1:8000/v1/messages',
                'gemini': 'http://127.0.0.1:8000/v1beta/models/{model}:generateContent',
                'chat_completions': 'http://127.0.0.1:8000/v1/chat/completions'}[adapter]
    host = ah.AgentHost(adapter=adapter, endpoint=endpoint, privacy='local_only',
                        local_models=[model], capabilities=capabilities(adapter, max_output_tokens=4096))
    return host, seen


def application_selection(monkeypatch):
    # The old application fixture intentionally replaces its entire model dict.
    # Declare the adapter after that replacement and create a fresh pinned session;
    # its original unselected fixture session stays retained and unused.
    original = app_controls.fixture
    def declared(base):
        wf, docs, wp, goal, unused_session = original(base)
        wf['model']['adapter'] = 'model'; wp = save(Path(wp['path']), wf)
        request = save(base/'inputs/provider-create.json', {
            'schema_version':1, 'label':'provider-control', 'workflow':wp,
            'goal_binding':goal, 'parent_session':None})
        session = a.create(request, base/'inputs', base/'provider-session')
        return wf, docs, wp, goal, session
    monkeypatch.setattr(app_controls, 'fixture', declared)


@pytest.mark.parametrize('action,adapter', [('anthropic','anthropic'), ('gemini','gemini'),
                                          ('chat_completions','chat_completions'), ('model','chat_completions')])
def test_actual_consultants_lead_and_adoption_preserve_selected_provider(tmp_path, monkeypatch, action, adapter):
    wf, docs, wp = selected(tmp_path, action)
    spec = c.consultant_graph(wf, tmp_path, wp, max_reworks=1)
    assert all(n['action'] == action for n in spec['nodes'])
    assert spec['budget']['max_calls'] == 2*len(spec['nodes'])
    consultants = tmp_path/'consultants'; g.create(consultants, spec)
    host, seen = mocked_host(monkeypatch, adapter, {'claims':['Explicit synthetic advice; no science claim']}, wf['model']['name'])
    assert g.execute(consultants, host, workers=1)['complete']
    assert len(seen) == len(spec['nodes'])
    cp = c.prepare(wp, tmp_path, tmp_path/'context', consultations=consultants)
    lead_spec = c.lead_graph(cp, tmp_path, graph_id='selected-lead', model=wf['model'], max_wall_seconds=60)
    assert lead_spec['nodes'][0]['action'] == action
    lead = tmp_path/'lead'; g.create(lead, lead_spec)
    host, seen = mocked_host(monkeypatch, adapter, proposal(wf,'extraction',handoff=docs['extraction']), wf['model']['name'])
    status = g.execute(lead, host, workers=1)
    assert status['complete'] and status['usage']['calls'] == 1 and len(seen) == 1
    result = g._result(lead, status['nodes']['sfitter_lead']['result'])['result']
    assert result['transport']['adapter'] == adapter
    assert result['transport']['requested_model'] == wf['model']['name']
    assert result['transport']['observed_model'] == 'observed-snapshot'
    adopted = c.adopt(lead, cp, tmp_path, tmp_path/'adopted')
    draft = read_json(adopted['workflow_draft']['path'])
    assert draft['model'] == wf['model'] and draft['target'] == wf['target']
    assert set(draft['handoffs']) == {'extraction'}
    assert adopted['calls_dispatched_by_adoption'] == 0 and not adopted['review_approved']
    assert not result['physics_validated']


def test_actual_same_graph_page_continuation_retains_source_selected_action(tmp_path, monkeypatch):
    wf, docs, wp = selected(tmp_path, 'model')
    cp = c.prepare(wp, tmp_path, tmp_path/'context')
    packet = c.prepare_lead_packet(cp, tmp_path, tmp_path/'packet')
    spec = c.lead_graph(cp, tmp_path, graph_id='selected-pages', model=wf['model'], max_wall_seconds=120,
                        packet_pin=packet, max_context_reworks=1)
    manifest = rc.verify_packet(packet['path'], expected_manifest_sha256=packet['manifest_sha256'])
    value = proposal(wf, 'extraction', 'request_context'); value['documentation_markdown'] = ''
    value['context_pages'] = references(docs, manifest)
    root = tmp_path/'graph'; g.create(root, spec)
    host, _ = mocked_host(monkeypatch, 'anthropic', value, wf['model']['name'])
    assert g.execute(root, host, workers=1)['complete']
    before = g.status(root)
    c.followup_context(root, cp, tmp_path, tmp_path/'pages')
    revised, _ = g._load(root); after = g.status(root)
    assert revised['nodes'][0]['action'] == 'model' and revised['budget'] == spec['budget']
    assert after['instance_id'] == before['instance_id'] and after['usage'] == before['usage']
    value = proposal(wf, 'extraction', handoff=docs['extraction']); value['context_pages'] = []
    host, _ = mocked_host(monkeypatch, 'anthropic', value, wf['model']['name'])
    assert g.execute(root, host, workers=1)['complete']
    assert c.adopt(root, cp, tmp_path, tmp_path/'adopted')['disposition'] == 'source_draft'
    assert g.status(root)['usage']['calls'] == 2


@pytest.mark.parametrize('adapter', ['anthropic','gemini','chat_completions'])
def test_actual_application_skill_and_production_reconstruct_source_adapter(tmp_path, monkeypatch, adapter):
    application_selection(monkeypatch)
    def supplied(value):
        return mocked_host(monkeypatch, adapter, value, 'explicit-mock')[0]
    monkeypatch.setattr(app_controls, 'SuppliedHost', supplied)
    # Existing full production fixture executes a real cycle/lead/adoption and
    # makes a source-bound table study. Its Host wire is the only substituted law.
    session, adoption, design, cycle_root, _, _ = app_controls.production_fixture(tmp_path)
    _, _, _, selected_row, _, _ = a._production(adoption, tmp_path, 0)
    assert selected_row['operation'] == 'measurement_extraction'
    binding = a.plan_production(session, tmp_path, adoption, 0, design, cycle_root,
                                tmp_path/'ordinary-run', tmp_path/'binding')
    value, *_ = a._binding(binding, tmp_path)
    assert not value['execution_authorized'] and value['requests_dispatched'] == 0
    assert not (tmp_path/'ordinary-run/inputs/checkin1_approval.json').exists()
    current = read_json(read_json(session['path'])['workflow']['path'])
    gp = a.skill_graph(session, tmp_path, tmp_path/'skill-plan', actors=['lead'], skill='sf-deep-verify',
                       graph_id='selected-skill', max_wall_seconds=30)
    spec = read_json(gp['path']); assert spec['nodes'][0]['action'] == 'model'
    host, _ = mocked_host(monkeypatch, adapter, app_controls.advice('lead',current), 'explicit-mock')
    result = a.execute_skill_graph(session, tmp_path, cycle_root, tmp_path/'skill', gp, host)
    assert result['complete'] and result['usage']['calls'] == 1
    result_doc = g._result(tmp_path/'skill', result['nodes']['lead']['result'])['result']
    assert result_doc['transport']['adapter'] == adapter
    assert result_doc['transport']['requested_model'] == 'explicit-mock'


@pytest.mark.parametrize('consumer', ['adopt','followup'])
def test_rehashed_lead_action_cannot_override_source_declaration(tmp_path, monkeypatch, consumer):
    wf, docs, wp = selected(tmp_path, 'anthropic')
    cp = c.prepare(wp, tmp_path, tmp_path/'context')
    packet = c.prepare_lead_packet(cp, tmp_path, tmp_path/'packet')
    spec = c.lead_graph(cp, tmp_path, graph_id='wrong-provider', model=wf['model'], max_wall_seconds=60,
                        packet_pin=packet, max_context_reworks=1)
    value = proposal(wf, 'extraction', 'request_context'); value['documentation_markdown'] = ''
    value['context_pages'] = [{'input_id':'input1','offset':0,'max_bytes':1}]
    if consumer == 'adopt':
        value = proposal(wf, 'extraction', 'unresolved'); value['context_pages'] = []
    # A real current wrong-provider return is still insufficient: the source
    # reconstruction must refuse, rather than trusting the result/action pair.
    spec['nodes'][0]['action'] = 'gemini'
    root = tmp_path/'graph'; g.create(root, spec)
    host, _ = mocked_host(monkeypatch, 'gemini', value, wf['model']['name'])
    assert g.execute(root, host, workers=1)['complete']
    with pytest.raises(ValueError, match='specification'):
        if consumer == 'adopt': c.adopt(root, cp, tmp_path, tmp_path/'refused')
        else: c.followup_context(root, cp, tmp_path, tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_rehashed_specialist_action_and_wrong_host_are_refused(tmp_path, monkeypatch):
    wf, _, wp = selected(tmp_path, 'anthropic')
    spec = c.consultant_graph(wf, tmp_path, wp)
    host, seen = mocked_host(monkeypatch, 'gemini', {}, wf['model']['name'])
    n = spec['nodes'][0]
    with pytest.raises(ah.HostFailure, match='action differs'):
        host.execute(n, {'request_id':'inert','packet':None,'input_artifacts':n['inputs']}, Control())
    assert seen == []
    for node in spec['nodes']: node['action'] = 'gemini'
    root = tmp_path/'consultants'; g.create(root, spec)
    with pytest.raises(ValueError, match='differs'):
        c.prepare(wp, tmp_path, tmp_path/'refused', consultations=root)
    assert not (tmp_path/'refused').exists()


def test_rehashed_application_action_is_refused_before_cycle_charge(tmp_path, monkeypatch):
    application_selection(monkeypatch)
    _, _, _, goal, session = app_controls.fixture(tmp_path)
    cycle_root = app_controls.cycle_fixture(tmp_path, goal)
    prior_ledger = deepcopy(app_controls.cycle._load(cycle_root)[1]['resource_ledger'])
    gp = a.skill_graph(session, tmp_path, tmp_path/'skill-plan', actors=['lead'], skill='sf-deep-verify',
                       graph_id='wrong-skill', max_wall_seconds=30)
    spec = read_json(gp['path']); spec['nodes'][0]['action'] = 'gemini'; gp = save(Path(gp['path']), spec)
    host, seen = mocked_host(monkeypatch, 'gemini', {}, 'explicit-mock')
    with pytest.raises(ValueError, match='contract'):
        a.execute_skill_graph(session, tmp_path, cycle_root, tmp_path/'refused', gp, host)
    assert seen == [] and app_controls.cycle._load(cycle_root)[1]['resource_ledger'] == prior_ledger


@pytest.mark.parametrize('change', [None, '', True, 'undeclared', ['anthropic']])
def test_source_model_adapter_refuses_unknown_or_malformed_declarations(tmp_path, change):
    wf, _, _ = selected(tmp_path, None); wf['model']['adapter'] = change
    with pytest.raises(ValueError): w.validate(wf)


def test_default_review_and_cli_selection_preserve_declared_source(tmp_path):
    wf, _, wp = selected(tmp_path, None)
    assert w.model_action(wf['model']) == 'responses'
    assert all(n['action'] == 'responses' for n in w.phase_graph(wf,tmp_path,wp)['nodes'])
    empty_model = deepcopy(wf['model'])
    critic = {'path':str(tmp_path/'critic-packet'),'manifest_sha256':'a'*64}
    verifier = {'path':str(tmp_path/'verifier-packet'),'manifest_sha256':'b'*64}
    base = w.review_graph(critic,verifier,empty_model,graph_id='review-default',max_wall_seconds=30)
    selected_model = {**empty_model,'adapter':'model'}
    reviewed = w.review_graph(critic,verifier,selected_model,graph_id='review-default',max_wall_seconds=30)
    expected = deepcopy(base)
    for n in expected['nodes']: n['action'] = 'model'
    assert reviewed == expected
    wf['model']['adapter'] = 'model'; wp = save(Path(wp['path']),wf)
    cp = c.prepare(wp,tmp_path,tmp_path/'context')
    omitted = c.lead_graph(cp,tmp_path,graph_id='default-inherits',model=empty_model,max_wall_seconds=30)
    assert omitted['nodes'][0]['action'] == 'model'
    with pytest.raises(ValueError,match='authenticated'):
        c.lead_graph(cp,tmp_path,graph_id='wrong-explicit',model={**empty_model,'adapter':'responses'},max_wall_seconds=30)
    assert c.main(['lead-graph','--input',cp['path'],'--output',str(tmp_path/'cli.json'),
                   '--model',empty_model['name'],'--adapter','model']) == 0
    assert read_json(tmp_path/'cli.json')['nodes'][0]['action'] == 'model'
    with pytest.raises(ValueError,match='authenticated'):
        c.main(['lead-graph','--input',cp['path'],'--output',str(tmp_path/'bad-cli.json'),
                '--model',empty_model['name'],'--adapter','gemini'])
    assert not (tmp_path/'bad-cli.json').exists()
