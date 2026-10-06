"""Keep failed cases in the public evidence denominator and detect byte drift."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

BASE=Path(__file__).resolve().parents[2]/'evidence/audits/2026-09-26-scientific-studies'
spec=importlib.util.spec_from_file_location('science_evidence_verify',BASE/'verify.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_complete_frozen_control_population():
    result=module.verify(BASE)
    assert result['status']=='PASS',result['errors']
    assert result['controls']==21
    assert result['physics_validated'] is False

def test_changed_quantity_and_dropped_failure_rejected(tmp_path):
    dest=tmp_path/'bundle';shutil.copytree(BASE,dest)
    p=dest/'controls/ATLAS_2013_I1234228/observables.json'
    saved=p.read_bytes();p.write_bytes(saved+b'\n')
    assert module.verify(dest)['status']=='FAIL'
    p.write_bytes(saved)
    (dest/'controls/CMS_2012_I1298807/export.log').unlink()
    assert module.verify(dest)['status']=='FAIL'


def test_a_curated_control_record_verifies_only_as_its_recorded_copy(tmp_path):
    """A control record whose wording or recorded paths were curated for the distribution keeps its
    original digest in the bundle manifest and in its verification record; the verifier accepts the file
    only as the exact copy that evidence/curation.json maps from that digest."""
    root = tmp_path / 'tree'
    bundle = root / 'evidence/audits' / BASE.name
    shutil.copytree(BASE, bundle)
    key = f'evidence/audits/{BASE.name}/controls/model-structure/result.json'
    path = bundle / 'controls/model-structure/result.json'
    pinned = json.loads((bundle / 'manifest.json').read_text())['files']['controls/model-structure/result.json']
    curated = path.read_bytes() + b' '
    path.write_bytes(curated)
    assert module.verify(bundle)['status'] == 'FAIL'
    # Keep this tree's own curation entries (a distributed tree ships curated controls) and map the pinned
    # digest of this record to the edited copy.
    records = json.loads((BASE.parents[1] / 'curation.json').read_text())['records']
    records[key] = {'original_sha256': pinned, 'original_bytes': 0,
                    'curated_sha256': hashlib.sha256(curated).hexdigest(), 'curated_bytes': len(curated),
                    'pinned_by': [], 'change': 'test', 'reason': 'test'}
    (root / 'evidence/curation.json').write_text(json.dumps({'schema_version': 1, 'purpose': 'test', 'records': records}))
    result = module.verify(bundle)
    assert result['status'] == 'PASS', result['errors']
    path.write_bytes(curated + b'\n')
    assert module.verify(bundle)['status'] == 'FAIL'
