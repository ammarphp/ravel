"""Actual public v2 plan/input admission on synthetic protocol sources only."""
import json
import platform
from pathlib import Path
import pytest
from test_simpleanalysis_build import configured_fixture
from ravel.workflow import science


def test_public_v2_plan_binds_full_qualified_extracted_dependency_census(tmp_path,monkeypatch):
    # Cache the standard read-only OS platform query before refusing every
    # further subprocess; this is not a client/compiler/scientific process.
    platform.platform()
    task,_,_=configured_fixture(tmp_path)
    monkeypatch.setattr('subprocess.run',lambda *a,**k:pytest.fail('prospective planning launched a client/compiler'))
    policy={'schema_version':1,'actors':{'proposer':'control/producer','executor':'control/producer','physics_critic':'control/critic','skeptical_verifier':'control/verifier','physics_decider':'control/decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'}],'claim_scopes':{'diagnostic':{'checks':['integrity'],'actions':['delivery','reuse']}}}
    spec={'schema_version':2,'mode':'analyze','source':'Synthetic offline-source protocol planning regression; no native qualification or physics claim.','assumptions':['The stand-in qualification and tiny source fixture test public admission only.'],'max_seconds':120,'max_attempts':1,'approval_mode':'scripted_yes','task':task,'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    sp=tmp_path/'science.json';sp.write_text(json.dumps(spec));rd=tmp_path/'plan';plan=science.plan(rd,sp)
    paths=plan['stage_binding']['input_snapshot'];inputs=science.task_inputs(spec,tmp_path)
    for name in ('HepMC3','RestFrames'):
        acquired=tmp_path/(name+'-source')/(name+'-'+'c'*40)/'source.txt';census=tmp_path/(name+'-source-files.json')
        assert acquired in inputs and census in inputs
        assert str(acquired) in paths and str(census) in paths
    assert science.verify_plan(rd,approved=False)==plan
    assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()
    acquired.write_text('qualification-source drift after planning')
    with pytest.raises(ValueError):science.task_inputs(spec,tmp_path)
    with pytest.raises(ValueError):science.verify_plan(rd,approved=False)
