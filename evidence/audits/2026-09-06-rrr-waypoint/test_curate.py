"""Tamper and interpretation controls for the standalone public waypoint verifier."""
import importlib.util
import json
from pathlib import Path
import shutil
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('waypoint_curator',HERE/'curate.py')
curator=importlib.util.module_from_spec(spec);spec.loader.exec_module(curator)

@pytest.fixture
def bundle(tmp_path):
    out=tmp_path/'bundle';shutil.copytree(HERE,out,ignore=shutil.ignore_patterns('__pycache__'))
    return out

def update(bundle,name,change):
    path=bundle/name;value=json.loads(path.read_text());change(value);data=curator.encoded(value);path.write_bytes(data)
    manifest=json.loads((bundle/'manifest.json').read_text());manifest['files'][name]['sha256']=curator.digest(data);manifest['files'][name]['bytes']=len(data)
    (bundle/'manifest.json').write_bytes(curator.encoded(manifest))

def test_public_verification_without_raw_data():
    result=curator.verify(HERE)
    assert result['status']=='PASS'
    assert result['original_small_sources_checked'] is False
    assert result['large_raw_event_files_rehashed'] is False
    assert result['physics_certified'] is False

def test_bytes_tamper_rejected(bundle):
    with (bundle/'channels.csv').open('a') as out:out.write('tampered\n')
    with pytest.raises(ValueError,match='byte mismatch'):curator.verify(bundle)

def test_semantic_rate_change_even_with_new_manifest_rejected(bundle):
    update(bundle,'waypoint.json',lambda d:d['results']['anchor20k'].__setitem__('conditional_observed_sigma95_fb',46.633))
    with pytest.raises(ValueError,match='limit conversion'):curator.verify(bundle)

def test_missing_stage_even_with_new_manifest_rejected(bundle):
    update(bundle,'execution-provenance.json',lambda d:d['anchor20k']['stages'].pop())
    with pytest.raises(ValueError,match='completion'):curator.verify(bundle)

def test_missing_event_denominator_rejected(bundle):
    update(bundle,'truth-response.json',lambda d:d['anchor20k'].__setitem__('input_events',19999))
    with pytest.raises(ValueError,match='population'):curator.verify(bundle)

def test_private_path_rejected(bundle):
    update(bundle,'waypoint.json',lambda d:d.__setitem__('unsafe','/'+'Users/example/private'))
    with pytest.raises(ValueError,match='absolute path'):curator.verify(bundle)

@pytest.mark.parametrize('name',['../outside','/absolute','C:\\drive','nested/../outside','a//b'])
def test_unsafe_source_path_rejected(bundle,name):
    update(bundle,'source-provenance.json',lambda d:d['sources'].__setitem__(name,{'sha256':'0'*64}))
    with pytest.raises(ValueError,match='path'):curator.verify(bundle)

def test_missing_retained_sources_is_not_a_public_fallback(bundle,tmp_path):
    with pytest.raises(FileNotFoundError):curator.verify(bundle,tmp_path/'missing')

def test_extra_unlisted_artifact_rejected(bundle):
    (bundle/'unlisted.txt').write_text('unexpected')
    with pytest.raises(ValueError,match='unlisted'):curator.verify(bundle)

def test_symlink_escape_rejected(bundle,tmp_path):
    path=bundle/'waypoint.json';outside=tmp_path/'outside.json';outside.write_bytes(path.read_bytes());path.unlink();path.symlink_to(outside)
    with pytest.raises(ValueError,match='escape/symlink'):curator.verify(bundle)

def test_duplicate_and_overflow_json_fail_closed():
    for text in ('{"a":1,"a":2}','{"value":1e400}','{"value":NaN}'):
        with pytest.raises(ValueError):curator.strict(text)


def test_actual_fixed_parameter_positive_control():
    pytest.importorskip('pyhf');pytest.importorskip('jsonpatch')
    result=curator.units(HERE)
    assert result['parameters']==217
    assert sum(r['parameter_points'] for r in result['checks'])==54
    assert result['negative_control_auxdata_difference']>1

@pytest.mark.parametrize('value',[float('nan'),float('inf')])
@pytest.mark.parametrize('method',['twice_nll','expected_data'])
def test_nonfinite_actual_model_evaluation_fails(monkeypatch,value,method):
    pyhf=pytest.importorskip('pyhf');np=pytest.importorskip('numpy');pytest.importorskip('jsonpatch')
    if method=='twice_nll':monkeypatch.setattr(pyhf.infer.mle,'twice_nll',lambda *a,**k:np.array([value]))
    else:monkeypatch.setattr(pyhf.pdf.Model,'expected_data',lambda *a,**k:np.array([value]))
    with pytest.raises(ValueError,match='nonfinite'):curator.units(HERE)

@pytest.mark.parametrize('name',['fits/anchor20k.json','waypoint.json'])
def test_censored_fit_or_summary_cannot_claim_six_resolved_roots(bundle,name):
    def change(d):
        target=d['results']['anchor20k'] if name=='waypoint.json' else d
        target['limit_status']['observed']='above_scan'
    update(bundle,name,change)
    with pytest.raises(ValueError,match='six resolved'):curator.verify(bundle)

@pytest.mark.parametrize('field,value',[('point_id','m999_m1'),('m_parent_GeV',999),('observed_sigma95_fb',1)])
def test_summary_reference_is_bound_to_bundled_reference_record(bundle,field,value):
    update(bundle,'waypoint.json',lambda d:d['reference_point'].__setitem__(field,value))
    with pytest.raises(ValueError,match='reference point'):curator.verify(bundle)

@pytest.mark.parametrize('field,value',[('central_relative_difference',0),('selected_events',2000),('reference_algebraic_acceptance_efficiency_product',1),('conditional_sampling_standard_error_on_inclusive_fraction',0)])
def test_reco_diagnostic_recomputed_not_only_copied(bundle,field,value):
    update(bundle,'reco-fraction-diagnostics.json',lambda d:d['anchor20k']['rows'][0].__setitem__(field,value))
    with pytest.raises(ValueError,match='reco'):curator.verify(bundle)

def test_reco_source_pin_must_match_actual_curated_source_inventory(bundle):
    update(bundle,'reco-fraction-diagnostics.json',lambda d:d['anchor20k']['inputs'][0].__setitem__('sha256','0'*64))
    with pytest.raises(ValueError,match='source pin'):curator.verify(bundle)


def repin_bytes(bundle,name,data):
    (bundle/name).write_bytes(data)
    manifest=json.loads((bundle/'manifest.json').read_text());manifest['files'][name]['sha256']=curator.digest(data);manifest['files'][name]['bytes']=len(data)
    (bundle/'manifest.json').write_bytes(curator.encoded(manifest))

def test_recipe_rejects_nonpath_config_changes_even_after_manifest_update(bundle):
    path='recipe/config.toml.template'
    repin_bytes(bundle,path,(bundle/path).read_bytes().replace(b'nevents = 20000',b'nevents = 200000'))
    with pytest.raises(ValueError,match='non-path'):curator.verify(bundle)

def test_recipe_requires_exact_source_card_bytes(bundle):
    path='recipe/inputs/cards/detector.tcl'
    repin_bytes(bundle,path,(bundle/path).read_bytes()+b'\n# changed card\n')
    with pytest.raises(ValueError,match='exact card source'):curator.verify(bundle)
