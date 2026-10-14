"""Actual-file ABA regressions; no benchmark answers or external execution."""
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import pytest
from ravel.workflow import public_source_tools as tools
from ravel.workflow import scientific_task_delivery as delivery
from ravel.workflow import scientific_artifact as typed


def pin(path):
    raw=path.read_bytes()
    return {'path':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def request(root,source='instruction'):
    (root/'prompt.txt').write_text('Total: 10\n')
    (root/'policy.txt').write_text('Total: 10\n')
    return {'schema_version':1,'prompt':pin(root/'prompt.txt'),'policy':pin(root/'policy.txt'),
        'bindings':[],'outputs':{'total':{'op':'extract','source':source,'pattern':r'^Total: (\d+)$','group':1}}}


@pytest.mark.parametrize('name,source',[('prompt.txt','instruction'),('policy.txt','policy')])
def test_reviewer_actual_file_ABA_returns_authenticated_10(tmp_path,name,source):
    """The exact 10->99->10 Path.read_text attack cannot feed the parser."""
    req=request(tmp_path,source)
    target=tmp_path/name
    original='Total: 10\n';altered='Total: 99\n';old_read=Path.read_text
    calls=[]
    def temporary_changed_read(self,*args,**kwargs):
        if self==target:
            calls.append(str(self));self.write_text(altered)
            try:return old_read(self,*args,**kwargs)
            finally:self.write_text(original)
        return old_read(self,*args,**kwargs)
    with patch.object(Path,'read_text',temporary_changed_read):
        result=tools.calculate(req,base_dir=tmp_path)
    assert result['facts']['total']=='10'
    assert result['prompt']==req['prompt'] and result['policy']==req['policy']
    assert calls==[] and target.read_text()==original and pin(target)==req['prompt' if source=='instruction' else 'policy']


def test_changed_bytes_during_the_authenticated_read_are_refused(tmp_path):
    req=request(tmp_path);target=tmp_path/'prompt.txt';old_open=Path.open
    class AlteredRead:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):self.stream.__enter__();return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def fileno(self):return self.stream.fileno()
        def read(self,size):self.stream.read(size);return b'Total: 99\n'
    def swapped_read(self,*args,**kwargs):
        stream=old_open(self,*args,**kwargs)
        return AlteredRead(stream) if self==target and args==('rb',) else stream
    with patch.object(Path,'open',swapped_read),pytest.raises(ValueError,match='bytes differ'):
        tools.calculate(req,base_dir=tmp_path)
    assert pin(target)==req['prompt']


def test_different_open_descriptor_is_refused_before_consumption(tmp_path):
    req=request(tmp_path);target=tmp_path/'prompt.txt';other=tmp_path/'other.txt'
    other.write_text('Total: 99\n');old_open=Path.open
    def substitute(self,*args,**kwargs):
        return old_open(other,*args,**kwargs) if self==target and args==('rb',) else old_open(self,*args,**kwargs)
    with patch.object(Path,'open',substitute),pytest.raises(ValueError,match='descriptor differs'):
        tools.calculate(req,base_dir=tmp_path)


def test_verified_snapshot_stays_original_when_path_changes_then_restores(tmp_path):
    req=request(tmp_path);target=tmp_path/'prompt.txt';old_inputs=tools._inputs
    def while_parsing(text):
        target.write_text('Total: 99\n')
        try:return old_inputs(text)
        finally:target.write_text('Total: 10\n')
    with patch.object(tools,'_inputs',while_parsing):
        result=tools.calculate(req,base_dir=tmp_path)
    assert result['facts']['total']=='10' and pin(target)==req['prompt']


def test_source_persistent_change_after_snapshot_is_refused_at_commit(tmp_path):
    req=request(tmp_path);target=tmp_path/'prompt.txt';old_inputs=tools._inputs
    def while_parsing(text):
        target.write_text('Total: 99\n');return old_inputs(text)
    with patch.object(tools,'_inputs',while_parsing),pytest.raises(ValueError,match='bytes differ'):
        tools.calculate(req,base_dir=tmp_path)


def delivery_request(root):
    task=root/'task.txt';task.write_text('One tool number and literal interpretation string.\n')
    tool=root/'tool.json';tool.write_text('{"number":"10"}\n')
    return {'schema_version':1,'format':'json','artifact_request':{'schema_version':1,
        'basis':[pin(task)],'tools':{'source':pin(tool)},
        'contract':{'source_scope':'Synthetic supplied source only.','tool_fields':[{'field':'number','type':'integer',
            'source':{'kind':'direct','tool_id':'source','pointer':'/number'}}],
            'interpretation_fields':['status'],'unresolved_semantics':[],'max_artifact_bytes':4096},
        'interpretation':{'status':'unobserved'}}}


def test_response_path_ABA_cannot_supply_unbound_text_or_byte_count(tmp_path):
    req=delivery_request(tmp_path);target=tmp_path/'reply.txt'
    original='{"status":"ten"}\n';target.write_text(original);response=pin(target);old_read=Path.read_text
    calls=[]
    def temporary_changed_read(self,*args,**kwargs):
        if self==target:
            calls.append(str(self));self.write_text('{"status":"unbound longer text"}\n')
            try:return old_read(self,*args,**kwargs)
            finally:self.write_text(original)
        return old_read(self,*args,**kwargs)
    old_reader=typed.ce.read_pin
    def no_separate_response_read(p,base):
        assert p!=response,'response JSON must use its authenticated snapshot'
        return old_reader(p,base)
    with patch.object(Path,'read_text',temporary_changed_read),patch.object(typed.ce,'read_pin',no_separate_response_read):
        out=delivery.from_response(req,response,base_dir=tmp_path)
    assert out['artifact']=={'number':10,'status':'ten'}
    assert out['model_response_bytes']==len(original.encode()) and calls==[]


@pytest.mark.parametrize('raw',['{"status":"x","status":"y"}','{"status":"x","number":NaN}','{"status":"x","number":1e999}'])
def test_snapshot_response_preserves_strict_duplicate_and_nonfinite_rules(tmp_path,raw):
    req=delivery_request(tmp_path);target=tmp_path/'reply.txt';target.write_text(raw)
    with pytest.raises(ValueError):delivery.from_response(req,pin(target),base_dir=tmp_path)
    assert target.read_text()==raw


def test_snapshot_decodes_exact_utf8_without_newline_rewriting(tmp_path):
    target=tmp_path/'basis.txt';raw='π source\r\n'.encode();target.write_bytes(raw)
    path,text=typed._basis_snapshot(pin(target),tmp_path.resolve())
    assert path==target.resolve() and text.encode()==raw
    assert typed._basis(pin(target),tmp_path.resolve())==target.resolve()


def test_response_unicode_text_keeps_authenticated_utf8_size(tmp_path):
    req=delivery_request(tmp_path);target=tmp_path/'reply.txt'
    raw=json.dumps({'status':'π interpretation'},ensure_ascii=False)+'\n';target.write_text(raw)
    out=delivery.from_response(req,pin(target),base_dir=tmp_path)
    assert out['artifact']['status']=='π interpretation' and out['model_response_bytes']==len(raw.encode())


def test_response_utf8_BOM_preserves_existing_strict_bytes_reader_behavior(tmp_path):
    req=delivery_request(tmp_path);target=tmp_path/'reply.txt'
    raw=b'\xef\xbb\xbf{"status":"literal BOM reply"}\n';target.write_bytes(raw)
    response=pin(target)
    assert typed.ce.read_pin(response,tmp_path)=={'status':'literal BOM reply'}
    out=delivery.from_response(req,response,base_dir=tmp_path)
    assert out['artifact']=={'number':10,'status':'literal BOM reply'}
    assert out['model_response_bytes']==len(raw)
