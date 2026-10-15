"""Proposed pure setup-plan/idempotence controls; no real install by author."""
import importlib.util
import json
from pathlib import Path
import shutil
import types
import pytest
from site_install_fixture import lock_text, VERSIONS


SOURCE=Path(__file__).parents[2]


def fixture(tmp_path):
    script=SOURCE/'scripts/setup/site_installation.py'
    spec=importlib.util.spec_from_file_location('ravel_site_setup_control',script)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    root=tmp_path/'checkout';(root/'src/ravel').mkdir(parents=True);(root/'src/ravel/__init__.py').write_text('# synthetic\n')
    for name in ('requirements-full.txt','requirements-site.txt','requirements-site-wms.txt','environment/site-profiles.json','pyproject.toml','scripts/setup/site_installation.py'):
        q=root/name;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/name,q)
    (root/'requirements-site-wms.lock').write_text(lock_text())
    helper.release_id=lambda root:'synthetic-release-a'
    class Host:
        def which(self,name):return None
        def exists(self,path):return Path(path).exists()
        def run(self,argv):return 0,'Filesystem 1024-blocks Used Available Capacity Mounted on\nsynthetic 40000000 1 20000000 1% /work\n'
    helper.Host=Host
    original_views=helper.lcg_views
    helper.lcg_views=lambda base=None,**kwargs:original_views(base if base is not None else tmp_path/'absent-views',**kwargs)
    return helper,root


def test_required_linux_profiles_and_explicit_mac_remote_plan(tmp_path,monkeypatch):
    h,root=fixture(tmp_path);monkeypatch.setattr(h.platform,'system',lambda:'Linux')
    p=h.plan(root);assert p['required_profiles']==['site-analysis','site-wms'] and p['requirements_required'] is True
    assert p['analysis_python']==str(root/'.ravel-site/site-analysis/bin/python')
    monkeypatch.setattr(h.platform,'system',lambda:'Darwin')
    with pytest.raises(ValueError):h.plan(root)
    p=h.plan(root,linux_root='/supplied/linux/ravel')
    assert p['remote_site_required'] and p['local_install_argv'] is None
    assert p['remote_install_argv']==['python3.12','/supplied/linux/ravel/scripts/setup/site_installation.py','--install','--prefix','/supplied/linux/ravel','--lcg-view','none']
    assert p['runtime_or_site_data_qualified'] is False


def test_idempotent_owned_profiles_keep_interpreter_copies_and_separate_wms(tmp_path,monkeypatch):
    h,root=fixture(tmp_path);monkeypatch.setattr(h.platform,'system',lambda:'Linux');monkeypatch.setattr(h.sys,'version_info',(3,12))
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if 'venv' in argv:
            assert '--copies' in argv
            path=Path(argv[-1]);(path/'bin').mkdir(parents=True);(path/'bin/python').write_text('synthetic never executed')
        if '-c' in argv and 'sys.base_prefix' in argv[-1]:
            path=Path(argv[0]).parents[1]
            return types.SimpleNamespace(stdout=json.dumps([str(path),'/synthetic/base',[3,12],'Linux','CPython']))
        if '-c' in argv:return types.SimpleNamespace(stdout=json.dumps(VERSIONS))
        if argv[-1]=='--version':return types.SimpleNamespace(stdout='9.27.0\n')
        return types.SimpleNamespace(stdout='synthetic==1\n')
    monkeypatch.setattr(h.subprocess,'run',run)
    assert h.install(root,lcg_view='none')['installed_profiles']==['site-analysis','site-wms']
    first=list(calls);h.install(root,lcg_view='none')
    assert sum('venv' in x for x in calls)==2
    pip=[x for x in first if 'install' in x]
    assert any('requirements-full.txt' in item for item in pip[0])
    assert not any('requirements-full.txt' in item for item in pip[1])
    assert all((root/'.ravel-site'/p/'ravel-site-installed.json').is_file() for p in h.PROFILES)
    assert [json.loads((root/'.ravel-site'/p/'ravel-site-installed.json').read_text())['profile'] for p in h.PROFILES]==['site-analysis','site-wms']
    assert sum('-I' in x and '-c' in x and 'sys.base_prefix' in x[-1] for x in calls)==12
    (root/'requirements-site.txt').write_text('changed-original\n')
    with pytest.raises(ValueError):h.install(root)


def test_no_implicit_install_and_source_alias_refusal(tmp_path,monkeypatch):
    h,root=fixture(tmp_path);monkeypatch.setattr(h.platform,'system',lambda:'Linux')
    monkeypatch.setattr(h.subprocess,'run',lambda *a,**k:pytest.fail('plan must not install'))
    assert h.plan(root)['requirements_required']
    file=root/'requirements-site.txt';file.unlink();file.symlink_to(SOURCE/'requirements-site.txt')
    with pytest.raises(ValueError):h.plan(root)


@pytest.mark.parametrize('bad', ['global-prefix','wrong-version','wrong-os','wrong-implementation','base-is-prefix'])
def test_replaced_interpreter_refuses_before_any_pip(tmp_path,monkeypatch,bad):
    h,root=fixture(tmp_path);monkeypatch.setattr(h.platform,'system',lambda:'Linux');monkeypatch.setattr(h.sys,'version_info',(3,12))
    calls=[];replaced=False
    def run(argv,**kwargs):
        calls.append(argv)
        if 'venv' in argv:
            path=Path(argv[-1]);(path/'bin').mkdir(parents=True);(path/'bin/python').write_text('synthetic never executed')
        if '-c' in argv and 'sys.base_prefix' in argv[-1]:
            target=Path(argv[0]).parents[1]
            value=[str(target),'/synthetic/base',[3,12],'Linux','CPython']
            if replaced:
                if bad=='global-prefix':value[0]='/synthetic/base'
                elif bad=='wrong-version':value[2]=[3,13]
                elif bad=='wrong-os':value[3]='Darwin'
                elif bad=='wrong-implementation':value[4]='PyPy'
                else:value[1]=str(target)
            return types.SimpleNamespace(stdout=json.dumps(value))
        if '-c' in argv:return types.SimpleNamespace(stdout=json.dumps(VERSIONS))
        if argv[-1]=='--version':return types.SimpleNamespace(stdout='9.27.0\n')
        return types.SimpleNamespace(stdout='')
    monkeypatch.setattr(h.subprocess,'run',run)
    h.install(root,lcg_view='none');calls.clear();replaced=True
    with pytest.raises(ValueError,match='declared Linux CPython3.12'):h.install(root,lcg_view='none')
    assert not any('pip' in argv for argv in calls)


def test_lcg_views_on_cvmfs_are_detected_newest_first(tmp_path):
    h,root=fixture(tmp_path)
    base=tmp_path/'cvmfs/views'
    for release,plat in (('LCG_105','x86_64-el9-gcc13-opt'),('LCG_107a','x86_64-el9-gcc13-opt'),
                         ('LCG_107a','aarch64-el9-gcc13-opt'),('LCG_106','x86_64-el9-gcc13-dbg')):
        view=base/release/plat;view.mkdir(parents=True);(view/'setup.sh').write_text('# view\n')
    views=h.lcg_views(base,machine='x86_64')
    assert [v['release'] for v in views]==['LCG_107a','LCG_105']
    assert h.lcg_views(tmp_path/'absent')==[]
    binding=h.write_lcg_binding(root,views[0]['path'])
    helper=(root/'.ravel-site/lcg-view.sh').read_text()
    assert binding['view']==views[0]['path'] and 'source '+views[0]['setup'] in helper
    with pytest.raises(ValueError):h.write_lcg_binding(root,tmp_path/'not-a-view')
