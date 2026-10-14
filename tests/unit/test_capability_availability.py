"""Fictional registry and manifest availability, without executing tools."""
import json
import pytest
from ravel.workflow import capability_availability as ca
from ravel.workflow import release_registry as rr


def package(tmp_path):
    data = tmp_path/'src/ravel/data'
    data.mkdir(parents=True)
    (data/'operation_signatures.json').write_text(json.dumps({'operations':{
        'alpha':{'implementation':{'kind':'science-mode','module':'ravel.physics.alpha'}}}}))
    return tmp_path


def manifest(root, groups):
    p=root/'native/setup/toolchain-manifest.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'groups':groups,'operations':[{'mode':'alpha','groups':['gamma']}]}))


def test_missing_group_is_unavailable(tmp_path):
    root=package(tmp_path);manifest(root, {})
    result=ca.availability('alpha', root=root, find_spec=lambda name:object())
    assert not result.available
    assert not result.manifest_fallback


def test_missing_module_is_refused(tmp_path):
    root=package(tmp_path);manifest(root, {'gamma':{}})
    with pytest.raises(ca.CapabilityNotInRelease, match='This capability is not part of this release of RAVEL.'):
        ca.require('alpha', root=root, find_spec=lambda name:None)


def test_unreadable_manifest_falls_back(tmp_path):
    result=ca.availability('alpha',root=package(tmp_path),find_spec=lambda name:object())
    assert result.available and result.manifest_fallback


def test_fragment_exists_then_disappears(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "module_present", lambda *a, **k:True)
    root=package(tmp_path)
    p=root/'src/ravel/data/release/in-development.json';p.parent.mkdir()
    p.write_text(json.dumps({'science_modes':['beta'],'adapters':{'beta':'ravel.physics.beta'},
                            'mode_descriptors':{'beta':{'summary':'fictional'}}}))
    assert 'beta' in rr.science_modes(('alpha',),root=root)
    assert 'beta' in rr.merge_entries('mode_descriptors',{},root=root)
    p.unlink()
    assert 'beta' not in rr.science_modes(('alpha',),root=root)


def test_duplicate_fragment_key_is_rejected(tmp_path):
    root=package(tmp_path);p=root/'src/ravel/data/release/in-development.json';p.parent.mkdir()
    p.write_text(json.dumps({'adapters':{'alpha':'ravel.physics.gamma'}}))
    with pytest.raises(ValueError,match='duplicate'):
        rr.merge_entries('adapters',{'alpha':'ravel.physics.alpha'},root=root)


def test_lazy_module_patches_reach_the_implementation(monkeypatch):
    import types, sys
    target=types.ModuleType('ravel_fictional_lazy');target.value=1
    monkeypatch.setitem(sys.modules,'ravel_fictional_lazy',target)
    monkeypatch.setattr(rr,'import_module',lambda name:sys.modules[name])
    monkeypatch.setattr(ca,'module_present',lambda *a,**k:True)
    proxy=rr.lazy_module('ravel_fictional_lazy')
    with monkeypatch.context() as patch:
        patch.setattr(proxy,'value',2)
        assert target.value==2 and proxy.value==2
    assert target.value==1 and proxy.value==1
    assert 'value' not in vars(proxy)
