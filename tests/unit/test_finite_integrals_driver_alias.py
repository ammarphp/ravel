"""Pure file/module-map controls, no optional package/native/process execution."""
from pathlib import Path
from types import ModuleType
import hashlib
import json
import sys
import pytest
from ravel.physics import finite_integrals_worker as worker, finite_integrals as adapter

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def case(tmp_path,monkeypatch):
    src=tmp_path/'source'/'ravel'/'physics';src.mkdir(parents=True)
    origin=src/'finite_integrals_worker.py';origin.write_bytes(Path(worker.__file__).read_bytes())
    native=tmp_path/'native';native.mkdir();driver=native/'driver.py';driver.write_bytes(origin.read_bytes())
    site=tmp_path/'site';site.mkdir();package=site/'actual_source.py';package.write_text('# inert source only\n')
    main=ModuleType('__main__');main.__file__=str(driver)
    backend=ModuleType('pySecDec');backend.__file__=str(package)
    modules={'__main__':main,'__mp_main__':main,'pySecDec':backend}
    request={'driver':{'path':str(driver),'sha256':sha(origin)},
        'ravel_source_root':str(src.parents[1]),'sites':[str(site)],
        'runtime_assets':{str(driver):sha(origin),str(package):sha(package)}}
    monkeypatch.setattr(worker,'__file__',str(driver))
    return request,modules,driver,origin,package

def census(request,modules,baseline=()):
    return worker._import_census(request,set(baseline),Path('/not-the-fixture'),set(),modules)

@pytest.mark.parametrize('already_present',[False,True])
def test_genuine_alias_is_authenticated_and_retained(tmp_path,monkeypatch,already_present):
    request,modules,driver,origin,_=case(tmp_path,monkeypatch)
    rows=census(request,modules,modules if already_present else {'__main__'})
    row=next(r for r in rows if r['path']==str(driver))
    assert '__mp_main__' in row['modules'] and row['sha256']==sha(origin)
    assert worker._authenticated_driver(request)['source_path']==str(origin)
    assert set(r['path'] for r in rows)=={str(driver),modules['pySecDec'].__file__}

@pytest.mark.parametrize('fault',['distinct_object_same_file','unrelated_main','alias_other_file','missing_main'])
def test_alias_name_is_never_an_exemption(tmp_path,monkeypatch,fault):
    request,modules,driver,_,package=case(tmp_path,monkeypatch)
    other=ModuleType('unrelated');other.__file__=str(driver if fault=='distinct_object_same_file' else package)
    if fault=='missing_main':modules.pop('__main__')
    elif fault=='unrelated_main':modules['__main__']=other;modules['__mp_main__']=other
    else:modules['__mp_main__']=other
    with pytest.raises(ValueError,match='multiprocessing alias'):census(request,modules,modules)

@pytest.mark.parametrize('fault',['changed_driver','changed_source','undeclared_driver','wrong_hash','wrong_path','missing_pin'])
def test_exact_driver_and_original_source_are_required(tmp_path,monkeypatch,fault):
    request,modules,driver,origin,package=case(tmp_path,monkeypatch)
    if fault=='changed_driver':driver.write_text('# substituted driver\n')
    elif fault=='changed_source':origin.write_text('# substituted admitted source\n')
    elif fault=='undeclared_driver':request['runtime_assets'].pop(str(driver))
    elif fault=='wrong_hash':request['driver']['sha256']='0'*64
    elif fault=='wrong_path':request['driver']['path']=str(package)
    else:request.pop('driver')
    with pytest.raises(ValueError):census(request,modules)

@pytest.mark.parametrize('fault',['driver_leaf','driver_parent','source_leaf'])
def test_aliased_source_refuses(tmp_path,monkeypatch,fault):
    request,modules,driver,origin,_=case(tmp_path,monkeypatch)
    if fault=='driver_leaf':
        stored=driver.with_name('old.py');driver.rename(stored);driver.symlink_to(stored)
    elif fault=='driver_parent':
        parent=driver.parent;stored=parent.with_name('stored');parent.rename(stored);parent.symlink_to(stored,target_is_directory=True)
    else:
        stored=origin.with_name('old.py');origin.rename(stored);origin.symlink_to(stored)
    with pytest.raises(ValueError):census(request,modules)

def test_unchanged_name_does_not_hide_optional_source_drift(tmp_path,monkeypatch):
    request,modules,_,_,package=case(tmp_path,monkeypatch)
    package.write_text('# changed optional bytes\n')
    with pytest.raises(ValueError,match='outside exact runtime census'):census(request,modules,modules)

def test_ending_driver_recheck_refuses_late_change(tmp_path,monkeypatch):
    request,modules,driver,_,_=case(tmp_path,monkeypatch)
    census(request,modules)
    driver.write_bytes(driver.read_bytes()+b'\n# changed after first census\n')
    with pytest.raises(ValueError,match='driver bytes changed'):census(request,modules)

def test_no_alias_still_requires_exact_backend_bytes(tmp_path,monkeypatch):
    request,modules,_,_,_=case(tmp_path,monkeypatch);modules.pop('__mp_main__')
    rows=census(request,modules,{'__main__'})
    assert [r['modules'] for r in rows]==[['pySecDec']]
    modules.pop('pySecDec')
    with pytest.raises(ValueError,match='missing actual pySecDec'):census(request,modules)

def test_selected_driver_bound_without_extending_captured_tree(tmp_path,monkeypatch):
    # Actual caller route, deterministic retained fake returns only.
    from ravel.physics import reinterpret_db,finite_integrals_core as core
    import importlib.util
    path=Path(adapter.__file__).parents[3]/'tests/unit/test_finite_integrals.py'
    spec=importlib.util.spec_from_file_location('owned_original_control',path)
    controls=importlib.util.module_from_spec(spec);spec.loader.exec_module(controls)
    task,config=controls.fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(adapter,'approved',lambda *_:{'max_seconds':30})
    retained={}
    def fake(command,out,c):
        request=json.loads((out/'request.json').read_bytes());retained.update(request)
        assert request['driver']['path']==str(out/'driver.py')
        assert request['driver']['sha256']==sha(Path(worker.__file__))
        assert request['runtime_assets'][str(out/'driver.py')]==request['driver']['sha256']
        return controls.fake_execution(command,out,c)
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    result=adapter.run(task,tmp_path,tmp_path/'delivered')
    assert result['status']=='passed' and result['physics_validated'] is False
    assert set(retained['runtime_assets'])=={str(tmp_path/'tool'),str(tmp_path/'delivered/native/driver.py')}

def test_changed_copy_refuses_before_native_callback(tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    import importlib.util
    path=Path(adapter.__file__).parents[3]/'tests/unit/test_finite_integrals.py'
    spec=importlib.util.spec_from_file_location('owned_copy_control',path)
    controls=importlib.util.module_from_spec(spec);spec.loader.exec_module(controls)
    task,_=controls.fixture(tmp_path,monkeypatch);monkeypatch.setattr(adapter,'approved',lambda *_:{'max_seconds':30})
    copy=adapter.shutil.copyfile
    def changed(source,target):copy(source,target);Path(target).write_text('# altered selected entry\n')
    monkeypatch.setattr(adapter.shutil,'copyfile',changed)
    monkeypatch.setattr(reinterpret_db,'execute_native',lambda *_:pytest.fail('must refuse before native callback'))
    with pytest.raises(ValueError,match='copied integral driver'):adapter.run(task,tmp_path,tmp_path/'badcopy')
