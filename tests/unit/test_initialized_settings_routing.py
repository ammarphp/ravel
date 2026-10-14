"""Portable public mode routing guards; no native or compiler calls."""
import json,pathlib
import pytest
from ravel.workflow import science
MODE='initialized-settings-qualification'

def test_actual_resolver_uses_reviewed_implementation():
    a=science.adapter({'mode':MODE,'task':{}})
    assert a.__name__=='ravel.validation.initialized_settings_qualification'
    assert MODE in science.MODES and science._new_capability({'mode':MODE,'task':{}})

def test_legacy_spec_refuses_before_any_source_or_native_call(tmp_path,monkeypatch):
    a=science.adapter({'mode':MODE,'task':{}})
    monkeypatch.setattr(a,'inputs',lambda *args,**kwargs:pytest.fail('runtime census should not run'))
    monkeypatch.setattr(a.native,'child',lambda *args,**kwargs:pytest.fail('native process should not run'))
    s={'schema_version':1,'mode':MODE,'source':'explicit synthetic routing control','assumptions':['No native or model calls'],
       'max_seconds':600,'approval_mode':'scripted_yes','task':{'input':'absent.json','sha256':'a'*64}}
    p=tmp_path/'spec.json';p.write_text(json.dumps(s))
    with pytest.raises(ValueError,match='prospective version 2'):science.plan(tmp_path/'run',p)
    assert not (tmp_path/'run').exists()

def test_declared_inner_budget_still_enforced(tmp_path,monkeypatch):
    a=science.adapter({'mode':MODE,'task':{}})
    monkeypatch.setattr(a,'inputs',lambda *args,**kwargs:[])
    monkeypatch.setattr(a,'execution_seconds',lambda *args:600)
    s={'mode':MODE,'task':{},'max_seconds':599}
    with pytest.raises(ValueError,match='budget exceeds'):science.task_inputs(s,tmp_path)
    s['max_seconds']=600;assert science.task_inputs(s,tmp_path)==[]
