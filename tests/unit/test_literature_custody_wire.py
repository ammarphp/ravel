"""AUTHORED/UNRUN. Actual ordinary callers; scripted transport only.

The consumer-adversary case discloses a temporary framing-validator waiver to
construct a genuinely journaled inconsistent response, then restores the real
consumer boundary. This is software falsification, never source acquisition.
"""
import hashlib
import json
from pathlib import Path
import pytest
from ravel.workflow import literature_context as lc
from test_literature_context import (document, request, pin, contract, write, cycle,
    tools, agent_host, task, scripted_transport, acquisition_request,
    acquired_document, refuse_real_network)


@pytest.mark.parametrize('route', ['prepare', 'consume'])
@pytest.mark.parametrize('attack', ['earlier-source', 'late-output'])
def test_last_read_cannot_hide_earlier_source_or_output_membership_change(tmp_path,monkeypatch,route,attack):
    base=tmp_path.resolve();doc=document(base,'paper','Literal original source.\n','text')
    req=request(base,[doc]);out=base/'located';product=None
    if route=='consume':product=lc.prepare(req,out,base_dir=base)['product']
    target=[];hits=[]
    original_init=lc._Reader.__init__;original_read=lc._Reader.read
    def init(self,*a,**k):
        original_init(self,*a,**k)
        if not target:target.append(self)
    def read(self,p,*a,**k):
        result=original_read(self,p,*a,**k)
        if target and self is target[0] and Path(p['path'])==out/('product.json' if route=='prepare' else 'request.json'):
            hits.append(p['path'])
            # Product is inserted last by prepare; consume remembers product
            # first, so request.json is its last generated remembered leaf.
            # Each selected leaf is first emitted/read, then finally reread.
            if len(hits)==2:
                if attack=='earlier-source':Path(doc['pin']['path']).write_bytes(b'Changed original source.\n')
                else:(out/'late.txt').write_bytes(b'Not an admitted generated member.\n')
        return result
    monkeypatch.setattr(lc._Reader,'__init__',init)
    monkeypatch.setattr(lc._Reader,'read',read)
    with pytest.raises(ValueError,match='ending identity|membership'):
        if route=='prepare':lc.prepare(req,out,base_dir=base)
        else:lc.consume(product,base_dir=base)
    assert len(hits)==2
    assert out.joinpath('product.json').is_file()  # failed evidence stays retained
    if attack=='late-output':assert out.joinpath('late.txt').read_bytes()==b'Not an admitted generated member.\n'
    else:assert Path(doc['pin']['path']).read_bytes()==b'Changed original source.\n'


def test_grouped_readers_close_all_earlier_identities_after_last_reader(tmp_path,monkeypatch):
    base=tmp_path.resolve();first=base/'first.txt';last=base/'last.txt'
    first.write_bytes(b'first');last.write_bytes(b'last')
    inputs=lc._Reader(base);outputs=lc._Reader(base)
    inputs.read(pin(first));outputs.read(pin(last))
    original=outputs.read
    def final_read(p,*a,**k):
        result=original(p,*a,**k);first.write_bytes(b'other');return result
    monkeypatch.setattr(outputs,'read',final_read)
    with pytest.raises(ValueError,match='ending identity'):
        inputs.finish(readers=(outputs,))


@pytest.mark.parametrize('headers',[
    {'Content-Length':'100'}, {'Content-Length':'8'},
    {'Content-Length':'-10'}, {'Content-Length':'+10'},
    {'Content-Length':'10, 10'}, {'Content-Length':'１０'},
    {'Content-Length':''}, {'Content-Length':'10000000000000000000000000000000000000000'},
    {'Transfer-Encoding':'chunked','Content-Length':'10'},
    {'Transfer-Encoding':'gzip'},
])
def test_actual_ordinary_bad_framing_retains_prefix_without_supplied_source(tmp_path,monkeypatch,headers):
    base=tmp_path.resolve();root=base/'campaign';cycle.create(root,contract(base),base_dir=base)
    body=b'Partial.\n';scripted_transport(monkeypatch,body,headers=headers)
    result=tools.acquire_literature(root,acquisition_request(base,max_bytes=1000,expected=None),root/'acquisition',
        agent_host.AgentHost(timeout_seconds=30,literature_origins=['https://papers.example.org']),max_wall_seconds=30)
    actual=lc.consume_acquisition(result['binding'],base_dir=base)
    assert result['status']=='failed' and result['source_artifact'] is None
    assert actual['status']=='failed' and actual['source_artifact'] is None and actual['failure']
    assert Path(actual['captured_body']['path']).read_bytes()==body
    assert actual['response_headers']['Content-Length']==headers.get('Content-Length')
    assert actual['response_headers']['Transfer-Encoding']==headers.get('Transfer-Encoding')
    context=tools.prepare_literature_context(root,
        request(base,[acquired_document(result['binding'],result)],tasks=[task()],root=root),
        root/'located',reason='Keep the exact failed advertised-body obligation.')
    assert context['knowledge_request'] is None
    assert context['context']['documents'][0]['status']=='failed'
    assert context['context']['acquisition_tasks']==[task()]
    assert not any(context['context']['claims'].values())


@pytest.mark.parametrize('headers',[
    {'Content-Length':'9'}, {'Content-Length':'0009'},
    {'Content-Length':'\t9 '}, {}, {'Transfer-Encoding':'chunked'},
])
def test_actual_ordinary_valid_length_chunked_or_eof_without_optional_hash(tmp_path,monkeypatch,headers):
    base=tmp_path.resolve();root=base/'campaign';cycle.create(root,contract(base),base_dir=base)
    body=b'Partial.\n';scripted_transport(monkeypatch,body,headers=headers)
    result=tools.acquire_literature(root,acquisition_request(base,max_bytes=1000,expected=None),root/'acquisition',
        agent_host.AgentHost(timeout_seconds=30,literature_origins=['https://papers.example.org']),max_wall_seconds=30)
    actual=lc.consume_acquisition(result['binding'],base_dir=base)
    assert result['status']=='acquired' and actual['source_artifact']['size']==len(body)
    assert Path(actual['source_artifact']['path']).read_bytes()==body
    assert actual['request_value']['expected_sha256'] is None
    assert 'unknown length is connection EOF only' in actual['coverage']
    assert not any(actual['claims'].values())


def test_consumer_rechecks_genuinely_journaled_short_advertised_response(tmp_path,monkeypatch):
    base=tmp_path.resolve();root=base/'campaign';cycle.create(root,contract(base),base_dir=base)
    body=b'Partial.\n';scripted_transport(monkeypatch,body,headers={'Content-Length':'100'})
    # Explicitly inject old admission behavior for this counterexample ONLY.
    # Ordinary receipt, full request/helper/body inputs and result bindings stay real.
    with monkeypatch.context() as old_admission:
        old_admission.setattr(lc,'_wire_body_complete',lambda *a:None)
        result=tools.acquire_literature(root,acquisition_request(base,max_bytes=1000,expected=None),root/'acquisition',
            agent_host.AgentHost(timeout_seconds=30,literature_origins=['https://papers.example.org']),max_wall_seconds=30)
    assert result['status']=='acquired' and Path(result['source_artifact']['path']).read_bytes()==body
    with pytest.raises(ValueError,match='Content-Length'):
        lc.consume_acquisition(result['binding'],base_dir=base)
    assert Path(result['binding']['path']).is_file() and Path(result['product']['path']).is_file()


@pytest.mark.parametrize('mode',['short-length','valid-length'])
def test_actual_httpresponse_amt_eof_uses_real_stdlib_framing(tmp_path,monkeypatch,mode):
    # In-memory wire, no socket/DNS/native operation; real HTTPResponse parser.
    # The original fake HTTPResponse does not exercise read(amt)'s EOF behavior.
    import io
    import http.client
    from test_literature_context import scripted_transport
    body=b'Partial.\n';length='100' if mode=='short-length' else str(len(body))
    calls=scripted_transport(monkeypatch,body)
    old_connection=lc.http.client.HTTPSConnection
    class WireSocket:
        def makefile(self,*a,**k):return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: '+length.encode()+b'\r\nConnection: close\r\n\r\n'+body)
    class Connection(old_connection):
        def getresponse(self):
            response=http.client.HTTPResponse(WireSocket());response.begin();self.sock=None;return response
    monkeypatch.setattr(lc.http.client,'HTTPSConnection',Connection)
    base=tmp_path.resolve();result=lc.acquire(acquisition_request(base,expected=None),base/'acquisition',
        base_dir=base,configured_origins=['https://papers.example.org'],privacy='configured')
    value=json.loads(Path(result['product']['path']).read_text())
    assert Path(value['captured_body']['path']).read_bytes()==body
    assert result['status']==('failed' if mode=='short-length' else 'acquired')
    assert (result['source_artifact'] is None)==(mode=='short-length')
    assert len(calls)==1 and not any(value['claims'].values())


@pytest.mark.parametrize('complete',[False,True])
def test_actual_httpresponse_chunk_terminator_retained_not_guessed(tmp_path,monkeypatch,complete):
    import io
    import http.client
    calls=scripted_transport(monkeypatch,b'')
    old_connection=lc.http.client.HTTPSConnection
    wire=b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n9\r\nPartial.\n\r\n'
    if complete:wire+=b'0\r\n\r\n'
    class WireSocket:
        def makefile(self,*a,**k):return io.BytesIO(wire)
    class Connection(old_connection):
        def getresponse(self):
            response=http.client.HTTPResponse(WireSocket());response.begin();self.sock=None;return response
    monkeypatch.setattr(lc.http.client,'HTTPSConnection',Connection)
    base=tmp_path.resolve();result=lc.acquire(acquisition_request(base,expected=None),base/'acquisition',
        base_dir=base,configured_origins=['https://papers.example.org'],privacy='configured')
    value=json.loads(Path(result['product']['path']).read_text())
    assert result['status']==('acquired' if complete else 'failed')
    assert (result['source_artifact'] is None)==(not complete)
    if complete:assert Path(result['source_artifact']['path']).read_bytes()==b'Partial.\n'
    else:assert value['failure'] and value['source_artifact'] is None
    assert len(calls)==1 and not any(value['claims'].values())
