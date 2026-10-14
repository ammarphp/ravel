"""Ending/partial scientific-return custody, with synthetic arithmetic only."""
import hashlib
import json
from pathlib import Path

import pytest
from test_cr_signal_study import fixture
from test_cr_switch_qualification import ToyEngine
from ravel.validation import cr_signal_study as s


@pytest.mark.parametrize('name', ['checkpoint.json', 'progress.jsonl'])
def test_prior_mutation_refuses_before_next_persistence(tmp_path, name):
    out=tmp_path/'out';out.mkdir();r=s.Recorder(out)
    r({'status':'running','returned':[1.]})
    (out/name).write_bytes(b'corruption retained')
    with pytest.raises(ValueError,match='diagnostic output changed'):
        r({'status':'running','returned':[1.,2.]})
    assert (out/name).read_bytes()==b'corruption retained'


@pytest.mark.parametrize('name', ['checkpoint.json', 'progress.jsonl'])
def test_failed_scientific_return_also_authenticates_ending_outputs(fixture,tmp_path,monkeypatch,name):
    monkeypatch.setattr(s.witness,'PyhfEngine',lambda:ToyEngine(fail_at=2))
    out=tmp_path/'out'
    def imports(inv):
        (out/name).write_bytes(b'partial failure corruption retained')
        return []
    monkeypatch.setattr(s,'observed_imports',imports)
    result=s.run(fixture[0],tmp_path,out)
    assert result['status']=='failed'
    assert any('diagnostic_outputs' in e for e in result['ending_errors'] if isinstance(e,dict))
    assert (out/name).read_bytes()==b'partial failure corruption retained'
    assert json.loads((out/'delivery-failure.json').read_text())==result
    assert {r['path'] for r in result['expected_diagnostic_outputs']}=={'checkpoint.json','progress.jsonl'}


@pytest.mark.parametrize('kind', ['extra','deleted','symlink'])
def test_complete_membership_and_leaf_type(fixture,tmp_path,monkeypatch,kind):
    out=tmp_path/'out'
    def imports(inv):
        if kind=='extra':(out/'unexpected.json').write_text('preserved')
        elif kind=='deleted':(out/'progress.jsonl').unlink()
        else:
            original=(out/'checkpoint.json').read_bytes()
            other=tmp_path/'alias-target';other.write_bytes(original)
            (out/'checkpoint.json').unlink();(out/'checkpoint.json').symlink_to(other)
        return []
    monkeypatch.setattr(s,'observed_imports',imports)
    result=s.run(fixture[0],tmp_path,out)
    assert result['status']=='failed'
    assert any('diagnostic_outputs' in e for e in result['ending_errors'] if isinstance(e,dict))
    if kind=='extra':assert (out/'unexpected.json').read_text()=='preserved'
    elif kind=='deleted':assert not (out/'progress.jsonl').exists()
    else:assert (out/'checkpoint.json').is_symlink()


@pytest.mark.parametrize('name',['checkpoint.json','progress.jsonl','cr-signal-result.json'])
def test_terminal_write_is_followed_by_authentication_without_corruption_overwrite(fixture,tmp_path,monkeypatch,name):
    original=s.Recorder.write_fresh;out=tmp_path/'out'
    def write(r,filename,state):
        original(r,filename,state)
        if filename=='cr-signal-result.json':(out/name).write_bytes(b'terminal corruption retained')
    monkeypatch.setattr(s.Recorder,'write_fresh',write)
    result=s.run(fixture[0],tmp_path,out)
    assert result['status']=='failed'
    assert (out/name).read_bytes()==b'terminal corruption retained'
    assert json.loads((out/'delivery-failure.json').read_text())==result
    assert any('terminal_outputs' in e for e in result['ending_errors'] if isinstance(e,dict))


def test_ending_runtime_observation_cannot_change_delivered_diagnostics(fixture,tmp_path,monkeypatch):
    original=s.parity.runtime_files;count=0;out=tmp_path/'out'
    def runtime(*args,**kwargs):
        nonlocal count
        value=original(*args,**kwargs);count+=1
        if count==2:(out/'progress.jsonl').write_bytes(b'changed in ending runtime observer')
        return value
    monkeypatch.setattr(s.parity,'runtime_files',runtime)
    result=s.run(fixture[0],tmp_path,out)
    assert result['status']=='failed' and count==2
    assert (out/'progress.jsonl').read_bytes()==b'changed in ending runtime observer'


def test_clean_summary_binds_complete_expected_journal_and_checkpoint(fixture,tmp_path):
    out=tmp_path/'out';result=s.run(fixture[0],tmp_path,out)
    assert result['status']=='passed'
    assert {p.name for p in out.iterdir()}=={'progress.jsonl','checkpoint.json','cr-signal-result.json'}
    assert json.loads((out/'cr-signal-result.json').read_text())==result
    for row in result['expected_diagnostic_outputs']:
        raw=(out/row['path']).read_bytes()
        assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
