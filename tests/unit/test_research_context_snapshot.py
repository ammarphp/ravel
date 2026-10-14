"""Actual Host context preparation, inert transport, and consumed-byte controls."""
import ast
import hashlib
from pathlib import Path
import subprocess
import pytest
from ravel.workflow import agent_host as host
from test_agent_host import node, request, pin


@pytest.fixture(autouse=True)
def no_dispatch(monkeypatch):
    def refuse(*a, **k): raise AssertionError("source-only context control cannot dispatch")
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(host.AgentHost, "_responses", refuse)


def prepared(path):
    n=node(inputs=[pin(path)])
    return host.AgentHost().prepare_model_context(n,request(n))["context"]["input_artifacts"][0]


def test_c3_aba_canary_and_new_snapshot_preserve_authenticated_ten(tmp_path,monkeypatch):
    path=tmp_path/'premise.txt';path.write_text('Total: 10\n');raw=path.read_bytes()
    n=node(inputs=[pin(path)]); original=Path.read_text
    def alternate(p,*a,**k):
        if p==path:
            p.write_text('Total: 99\n');value=original(p,*a,**k);p.write_bytes(raw);return value
        return original(p,*a,**k)
    monkeypatch.setattr(Path,'read_text',alternate)
    # Exact old _context AST, retained only as a development witness. This is
    # not an upstream/provider runtime qualification or a new product reader.
    old=Path(__file__).resolve().parents[3]/'development-refusals/host-context-c3-aba/agent_host_c3.py'
    if old.exists():
        tree=ast.parse(old.read_bytes())
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='AgentHost')
        function=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_context')
        scope=dict(host.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(old),'exec'),scope)
        adapter=host.AgentHost();pins=adapter._pins(n,request(n))
        observed=scope['_context'](adapter,n,request(n),pins)['input_artifacts'][0]
        assert observed['content']=='Total: 99\n' and observed['sha256']==hashlib.sha256(raw).hexdigest()
    assert prepared(path)['content']=='Total: 10\n'


def test_descriptor_aba_refuses_consumed_ninety_nine(tmp_path,monkeypatch):
    path=tmp_path/'premise.txt';path.write_text('Total: 10\n');raw=path.read_bytes();opened=Path.open
    def during(p,*a,**k):
        stream=opened(p,*a,**k)
        if p!=path or a!=('rb',): return stream
        class Wrapped:
            def __enter__(self):return self
            def __exit__(self,*a):stream.close()
            def fileno(self):return stream.fileno()
            def read(self,*a):
                p.write_text('Total: 99\n');value=stream.read(*a);p.write_bytes(raw);return value
        return Wrapped()
    n=node(inputs=[pin(path)]);adapter=host.AgentHost();pins=adapter._pins(n,request(n))
    monkeypatch.setattr(Path,'open',during)
    with pytest.raises(host.HostFailure):adapter._context(n,request(n),pins)


def test_ending_parent_symlink_even_same_inode_refuses(tmp_path,monkeypatch):
    parent=tmp_path/'inputs';parent.mkdir();path=parent/'p.txt';path.write_text('same inode\n')
    n=node(inputs=[pin(path)]);adapter=host.AgentHost();pins=adapter._pins(n,request(n));opened=Path.open
    def during(p,*a,**k):
        stream=opened(p,*a,**k)
        if p!=path or a!=('rb',):return stream
        class Wrapped:
            def __enter__(self):return self
            def __exit__(self,*a):stream.close()
            def fileno(self):return stream.fileno()
            def read(self,*a):
                value=stream.read(*a);parent.rename(tmp_path/'moved');parent.symlink_to(tmp_path/'moved',target_is_directory=True);return value
        return Wrapped()
    monkeypatch.setattr(Path,'open',during)
    with pytest.raises(host.HostFailure,match='symlink'):adapter._context(n,request(n),pins)


@pytest.mark.parametrize('raw',[b'CRLF\r\nCR\rLF\n',b'\xef\xbb\xbfsource\n','Unicode π\n'.encode(),b''])
def test_utf8_universal_newline_and_bom_parity(tmp_path,raw):
    path=tmp_path/'source.txt';path.write_bytes(raw)
    assert prepared(path)['content']==path.read_text(encoding='utf-8')


def test_invalid_utf8_and_consumed_byte_limit_refuse(tmp_path):
    path=tmp_path/'p.txt';path.write_bytes(b'\xff')
    with pytest.raises(host.HostFailure,match='UTF-8'):prepared(path)
    path.write_bytes(b'xx')
    with pytest.raises(host.HostFailure,match='consumed bytes'):
        host._input_text_snapshot(path,hashlib.sha256(b'xx').hexdigest(),1)
