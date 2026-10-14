"""Existing nonvoting page continuation with an explicit ordinary campaign.

Control transport is opt-in only in these software fixtures. Original charges,
independent clocks and current Graph reservation remain the real consumers.
"""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import research_cycle as rc,scientific_judgment as j,agent_graph as graph,physics_review as review
from test_scientific_judgment import observed_role_boundary
from test_scientific_judgment import campaign_for,prepare,cycle
from test_physics_review import run
from test_scientific_context_continuation import PresentedHost,select
import socket
import subprocess


def no_external(monkeypatch):
    # Synthetic platform string avoids a uname subprocess; process and network calls stay denied.
    import platform
    monkeypatch.setattr(platform,'platform',lambda:'synthetic no-process platform fixture; not native runtime qualification')
    def deny(*args,**kwargs):raise AssertionError("pure control attempted external/native/model execution")
    for name in ("Popen","run","check_output","call","check_call"):
        monkeypatch.setattr(subprocess,name,deny)
    monkeypatch.setattr(socket,"create_connection",deny)


def standalone_reserved(cycle,tmp_path,monkeypatch):
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    binding=prepare(cycle,tmp_path/'role','critic',evidence_pages=[],max_context_reworks=1)
    spec,_=graph._load(Path(binding['graph_root']))
    rc.execute_graph(campaign,binding['graph_root'],spec,PresentedHost(select(binding)),prepared=True)
    assert j.consume(cycle,binding,allow_control=True)['value']['kind']=='scientific_context_request'
    assert 'campaign' not in j._read_pin(binding['request'])
    return campaign,binding


def test_actual_caller_explicit_campaign_nonvote_revision_and_same_budget_vote(cycle,tmp_path,monkeypatch, observed_role_boundary):
    campaign,binding=standalone_reserved(cycle,tmp_path,monkeypatch)
    _,before=rc._load(campaign);_,old=graph._load(Path(binding['graph_root']))
    follow=j.continue_role(binding,tmp_path/'follow',campaign_root=campaign,allow_control=True)
    spec,revised=graph._load(Path(follow['graph_root']));_,after=rc._load(campaign)
    assert follow['graph_root']==binding['graph_root'] and revised['graph_revision']==1
    assert after['resource_ledger']==before['resource_ledger'] and after['timing']==before['timing']
    assert revised['started_epoch']==old['started_epoch'] and revised['usage']==old['usage']
    rc.execute_graph(campaign,follow['graph_root'],spec,PresentedHost(),prepared=True)
    assert j.consume(cycle,follow,allow_control=True)['verdict']=='accept'
    _,ending=rc._load(campaign)
    assert ending['resource_ledger']==before['resource_ledger'] and ending['timing']==before['timing']
    assert len(review._view(*review._read(cycle))['reviews'])==1


def test_foreign_campaign_cannot_adopt_a_context_graph(cycle,tmp_path,monkeypatch):
    campaign,binding=standalone_reserved(cycle,tmp_path,monkeypatch)
    foreign=campaign_for(cycle,tmp_path/'foreign',monkeypatch)
    out=tmp_path/'must-not-exist'
    with pytest.raises(ValueError):j.continue_role(binding,out,campaign_root=foreign,allow_control=True)
    assert not out.exists()


def test_existing_experiment_association_and_explicit_campaign_are_ambiguous(cycle,tmp_path,monkeypatch):
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    binding=prepare(cycle,tmp_path/'role','critic',campaign=campaign,experiment='observed',evidence_pages=[],max_context_reworks=1)
    j.execute_role(binding,PresentedHost(select(binding)));j.consume(cycle,binding,allow_control=True)
    out=tmp_path/'ambiguous'
    with pytest.raises(ValueError,match='ambiguous'):
        j.continue_role(binding,out,campaign_root=campaign,allow_control=True)
    assert not out.exists()


def test_unadmitted_revision_never_reuses_explicit_campaign_allowance(cycle,tmp_path,monkeypatch):
    campaign,binding=standalone_reserved(cycle,tmp_path,monkeypatch)
    spec,_=graph._load(Path(binding['graph_root']));changed=deepcopy(spec)
    changed['nodes'][0]['parameters']['instructions']+=' foreign unadmitted replacement'
    graph.revise(binding['graph_root'],changed,reason='source-only adverse fixture')
    out=tmp_path/'unadmitted'
    with pytest.raises(ValueError):j.continue_role(binding,out,campaign_root=campaign,allow_control=True)
    assert not out.exists()
