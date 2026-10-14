"""Unrun software boundaries; actual ordinary reader with explicitly inert effects.

The original54 controls remain byte-exact. No native/provider action is admitted
by these fixtures; source-role and partial-read physics semantics are unchanged.
"""
from pathlib import Path
import hashlib
import pytest
from ravel.physics import dataset_query_quantities_core, root_stream as stream, root_stream_core as core
from ravel.workflow import data_read_outcomes as reads, research_cycle
from test_data_read_outcomes import effect_result, no_native_or_provider


def declaration(path, *, size=True):
    raw=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),**({'size':len(raw)} if size else {})}


@pytest.mark.parametrize('shape',[2,3])
@pytest.mark.parametrize('relative',[False,True])
def test_original_path_hash_and_observed_size_enter_strict_capture(tmp_path,shape,relative):
    parent=tmp_path/'nested';parent.mkdir();path=parent/'result.json';raw=b'{"original":true}\n';path.write_bytes(raw)
    source=declaration(path,size=shape==3)
    if relative:source['path']='nested/result.json'
    capture=core.Capture();current,consumed=reads._capture_artifact(source,tmp_path,capture)
    assert current==path and consumed==raw
    assert capture.rows[path]==declaration(path)
    assert source['path']==('nested/result.json' if relative else str(path))
    assert set(source)==({'path','sha256'} if shape==2 else {'path','sha256','size'})
    capture.finish()


@pytest.mark.parametrize('fault',['wrong_hash','wrong_size','boolean_size','extra_field'])
def test_original_digest_and_supplied_size_are_never_rebased(tmp_path,fault):
    path=tmp_path/'result.json';path.write_bytes(b'{}\n');source=declaration(path,size=fault!='wrong_hash')
    if fault=='wrong_hash':source['sha256']='0'*64
    elif fault=='wrong_size':source['size']+=1
    elif fault=='boolean_size':source['size']=True
    else:source['authorization']=True
    capture=core.Capture()
    with pytest.raises(ValueError):reads._capture_artifact(source,tmp_path,capture)
    assert capture.rows=={}
    assert path.read_bytes()==b'{}\n'


def test_changed_bytes_between_size_observation_and_strict_capture_refuse(tmp_path,monkeypatch):
    path=tmp_path/'result.json';path.write_bytes(b'{"value":1}\n');source=declaration(path,size=False)
    original=research_cycle._bounded_source_snapshot;calls=[]
    def observe_then_change(value,maximum):
        current,raw=original(value,maximum);calls.append(current)
        if len(calls)==1:path.write_bytes(b'{"value":2}\n')
        return current,raw
    monkeypatch.setattr(research_cycle,'_bounded_source_snapshot',observe_then_change)
    capture=core.Capture()
    with pytest.raises(ValueError,match='consumed source bytes differ'):
        reads._capture_artifact(source,tmp_path,capture)
    assert calls==[path,path] and capture.rows=={}
    assert source['sha256']==hashlib.sha256(b'{"value":1}\n').hexdigest()


@pytest.mark.parametrize('different_size',[False,True])
def test_legacy_artifact_retains_normal_capture_ending_check(tmp_path,different_size):
    path=tmp_path/'result.json';path.write_bytes(b'{"value":1}\n');source=declaration(path,size=False)
    capture=core.Capture();reads._capture_artifact(source,tmp_path,capture)
    path.write_bytes(b'{"value":200}\n' if different_size else b'{"value":2}\n')
    with pytest.raises(ValueError,match='consumed source bytes differ'):capture.finish()
    assert capture.rows[path]['sha256']==source['sha256']
    assert capture.rows[path]['size']==len(b'{"value":1}\n')


def test_generic_columnar_capture_still_requires_closed_pin3(tmp_path):
    path=tmp_path/'result.json';path.write_bytes(b'{}\n');capture=dataset_query_quantities_core.Capture()
    with pytest.raises(ValueError,match='closed source pin'):capture.read(declaration(path,size=False),tmp_path)
    assert capture.rows=={}


@pytest.mark.parametrize('shape',[2,3])
def test_ordinary_artifact_alias_cannot_supply_observed_size(tmp_path,shape):
    path=tmp_path/'original.json';path.write_bytes(b'{}\n');alias=tmp_path/'alias.json';alias.symlink_to(path)
    source=declaration(path,size=shape==3);source['path']=str(alias);capture=core.Capture()
    with pytest.raises(ValueError):reads._capture_artifact(source,tmp_path,capture)
    assert capture.rows=={}


def test_legacy_size_observation_preserves_original_document_bound(tmp_path):
    path=tmp_path/'large.json';path.write_bytes(b' '*(dataset_query_quantities_core.MAX_DOCUMENT+1))
    source=declaration(path,size=False);capture=core.Capture()
    with pytest.raises(ValueError,match='bounded regular research source'):
        reads._capture_artifact(source,tmp_path,capture)
    assert capture.rows=={}


def test_actual_reader_producer_retains_original_plan_pin2_and_full_population(tmp_path,monkeypatch):
    parts,result,result_pin,output=effect_result(tmp_path,monkeypatch)
    stream.guard(result,output/'root-stream').finish(result,common=output)
    record=core.strict(Path(result['read_outcomes']['path']).read_bytes())
    # The existing science.PLAN spelling is authoritative, not a fixture alias.
    from ravel.workflow import science
    plan=output.parent/science.PLAN
    assert record['reader']['ordinary_plan']==declaration(plan,size=False)
    assert record['outcome']=='read_complete' and len(record['population'])==3
    assert [row['expected_entries'] for row in record['population']]==[5,3,4]
    assert not record['subset_renormalized'] and not record['physics_validated']
    assert core.strict(Path(result_pin['path']).read_bytes())==result


@pytest.mark.parametrize('failure',[False,True])
def test_actual_reader_result_pin2_and_pin3_share_exact_consumer(tmp_path,monkeypatch,failure):
    parts,result,result_pin,output=effect_result(tmp_path,monkeypatch,failure=failure)
    stream.guard(result,output/'root-stream').finish(result,common=output)
    # Only actual admitted-attempt inspection is replaced; producer, ledger,
    # guard, exact source representation and complete/partial reconstruction run.
    monkeypatch.setattr(reads,'ordinary_outcome',lambda *args:{'explicit_inert_attempt_reader':True})
    requirement=parts[4]['read_requirements']['regions']
    full=reads.consume(result_pin,requirement,tmp_path)
    legacy=reads.consume({k:result_pin[k] for k in ('path','sha256')},requirement,tmp_path)
    assert full==legacy
    assert legacy['passed'] is (not failure)
    assert legacy['outcome']==('read_partial' if failure else 'read_complete')
    assert legacy['original_scientific_obligation_complete'] is (not failure)
    assert not legacy['scientific_acceptance']
