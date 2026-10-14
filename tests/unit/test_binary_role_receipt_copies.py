from pathlib import Path
import hashlib
import pytest
from ravel.workflow import agent_graph as graph
from ravel.workflow.state_io import atomic_json
from test_binary_role_evidence import packet,node
from test_binary_role_manifest_bounds import deliver


@pytest.mark.parametrize('mutation',['none','bytes','aba','member'])
def test_receipt_ending_boundary_preserves_all_indexed_copy_custody(tmp_path,monkeypatch,mutation):
    subject=b'{"scope":"diagnostic-control"}'
    opaque=b'\xff\x00original'
    p=packet(tmp_path/'packet',{'judgment_request':subject,'opaque':opaque})
    root=tmp_path/'graph';deliver(root,node(p))
    target=Path(p['path'])/'artifacts/opaque.dat'
    original=graph.read_json;mutated=[]
    def read(path):
        data=original(path)
        if Path(path).parent==root/'calls' and not mutated:
            mutated.append(mutation)
            if mutation in {'bytes','aba'}:
                target.write_bytes(b'\xee\x00modified')
                if mutation=='aba':target.write_bytes(opaque)
            elif mutation=='member':(target.parent/'foreign.dat').write_bytes(b'new')
        return data
    monkeypatch.setattr(graph,'read_json',read)
    result=None;refusal=None
    try:
        result=graph.role_receipt(root,'critic',expected_subject_sha256=hashlib.sha256(subject).hexdigest(),require_exact_subject=True)
    except ValueError as error:refusal=str(error)
    atomic_json(tmp_path/'witness.json',{'mutation':mutation,'mutated_during_receipt':mutated,
        'returned_receipt':result,'refusal':refusal,'copy_sha256_at_end':hashlib.sha256(target.read_bytes()).hexdigest(),
        'expected_copy_sha256':hashlib.sha256(opaque).hexdigest(),'actual_model_native_provider_calls':0})
    assert mutated==[mutation]
    if mutation=='none':assert result is not None and result['exact_subject_presented'] is True
    else:assert result is None, 'current role receipt returned after indexed copy mutation during its final observation'
