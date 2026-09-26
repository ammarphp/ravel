"""Keep failed cases in the public evidence denominator and detect byte drift."""
import importlib.util
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
