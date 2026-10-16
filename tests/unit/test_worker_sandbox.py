"""Sandbox command construction; OS probes are qualified separately."""
from pathlib import Path
import pytest


def test_profiles_allow_only_worker_output_scratch_and_broker_socket(tmp_path):
    from ravel.workflow import sandbox
    ws=tmp_path/'worker';ws.mkdir()
    profile=sandbox.macos_profile(ws,read_paths=['/usr/bin','/System/Library'])
    assert '(deny default)' in profile and '(allow network*' not in profile
    assert str(ws/'outputs') in profile and str(ws/'scratch') in profile
    assert str(ws/'inputs') in profile and str(ws/'.broker.sock') in profile
    assert '(allow file-write* (subpath '+sandbox.quote(str(ws))+')' not in profile


def test_linux_command_has_no_network_or_custody_mount(tmp_path):
    from ravel.workflow import sandbox
    ws=tmp_path/'worker';ws.mkdir()
    argv=sandbox.linux_command(ws,['/usr/bin/python3','-c','pass'],read_paths=['/usr'])
    assert '--unshare-net' in argv and '--die-with-parent' in argv
    assert '--ro-bind' in argv and '--bind' in argv
    assert '/state' not in argv


def test_sandbox_refuses_symlink_workspace_or_read_root(tmp_path):
    from ravel.workflow import sandbox
    real=tmp_path/'real';real.mkdir();link=tmp_path/'link';link.symlink_to(real)
    with pytest.raises(ValueError):sandbox.macos_profile(link)
    with pytest.raises(ValueError):sandbox.macos_profile(real,read_paths=['/'])


def test_profile_permits_runtime_listing_of_root_and_workspace_only(tmp_path):
    from ravel.workflow import sandbox
    ws=tmp_path/'worker';ws.mkdir()
    profile=sandbox.macos_profile(ws,read_paths=['/usr'])
    assert '(allow file-read* (literal "/"))' in profile
    assert '(allow file-read* (literal '+sandbox.quote(str(ws))+'))' in profile
    assert '(subpath "/")' not in profile and '(allow file-read* (subpath '+sandbox.quote(str(ws))+'))' not in profile


def test_child_permission_failure_is_a_probe_failure_not_unavailable(tmp_path,monkeypatch):
    import subprocess
    from ravel.workflow import sandbox
    ws=tmp_path/'worker'
    for name in ('inputs','outputs','scratch'):(ws/name).mkdir(parents=True)
    monkeypatch.setattr(sandbox,'available',lambda:'macos')
    def child_denied(*a,**k):
        return subprocess.CompletedProcess(a,1,'','PermissionError: [Errno 1] Operation not permitted\n')
    monkeypatch.setattr(sandbox.subprocess,'run',child_denied)
    with pytest.raises(sandbox.SandboxProbeFailed):
        sandbox.probe(ws,forbidden=tmp_path/'private')
    def launcher_denied(*a,**k):
        return subprocess.CompletedProcess(a,71,'','sandbox-exec: sandbox_apply: Operation not permitted\n')
    monkeypatch.setattr(sandbox.subprocess,'run',launcher_denied)
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.probe(ws,forbidden=tmp_path/'private')
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    def namespace_denied(*a, **k):
        return subprocess.CompletedProcess(a, 1, '', 'bwrap: Creating new namespace failed: Operation not permitted\n')
    monkeypatch.setattr(sandbox.subprocess, 'run', namespace_denied)
    with pytest.raises(sandbox.SandboxUnavailable, match='namespace'):
        sandbox.probe(ws, forbidden=tmp_path/'private')
    monkeypatch.setattr(sandbox.subprocess, 'run', child_denied)
    with pytest.raises(sandbox.SandboxProbeFailed):
        sandbox.probe(ws, forbidden=tmp_path/'private')


def test_extra_read_roots_must_avoid_run_tree_workspaces_and_custody(tmp_path,monkeypatch):
    from ravel.workflow import broker, sandbox
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'))
    run=tmp_path/'run';run.mkdir();(run/'calls').mkdir()
    ws=broker.work_root(run)/'worker'/'1';(ws/'calls').mkdir(parents=True)
    sibling=broker.work_root(run)/'peer'/'1';sibling.mkdir(parents=True)
    tool=tmp_path/'toolchain';tool.mkdir()
    protected=sandbox.protected_roots(run)
    for root in (run,run/'calls',tmp_path,sibling,broker.work_root(run),broker.custody(run),tmp_path/'state',ws/'calls'):
        with pytest.raises(ValueError):sandbox.macos_profile(ws,read_paths=[str(root)],protected=protected)
        with pytest.raises(ValueError):sandbox.linux_command(ws,['/usr/bin/true'],read_paths=[str(root)],protected=protected)
    assert str(tool) in sandbox.macos_profile(ws,read_paths=[str(tool),'/usr'],protected=protected)


def test_probe_checks_every_denied_location(tmp_path,monkeypatch):
    import json,subprocess
    from ravel.workflow import sandbox
    ws=tmp_path/'worker'
    for name in ('inputs','outputs','scratch'):(ws/name).mkdir(parents=True)
    denied=[tmp_path/'custody.json',tmp_path/'run-canary',tmp_path/'peer-canary']
    for path in denied:path.write_text('x')
    seen={}
    monkeypatch.setattr(sandbox,'available',lambda:'macos')
    def run(argv,**kwargs):
        seen['targets']=json.loads(argv[-2])
        return subprocess.CompletedProcess(argv,0,json.dumps({'read_denied':[True,True,False],'write_denied':True,
            'listen_denied':True,'other_port_denied':True,'allowed_input_read':True}),'')
    monkeypatch.setattr(sandbox.subprocess,'run',run)
    with pytest.raises(sandbox.SandboxProbeFailed):sandbox.probe(ws,forbidden=denied)
    assert seen['targets']==[str(p) for p in denied]


def test_metadata_is_scoped_to_ancestors_and_readable_roots(tmp_path, require_sandbox):
    import json,subprocess,sys
    from ravel.workflow import sandbox
    (tmp_path/'w').mkdir();profile=sandbox.macos_profile(tmp_path/'w',read_paths=['/usr'])
    assert '(allow file-read-metadata)' not in profile
    if sandbox.available() != 'macos':
        pytest.skip('metadata visibility is a macOS sandbox profile property')
    ws=tmp_path/'ws';[(ws/n).mkdir(parents=True) for n in ('inputs','outputs','scratch')]
    hidden=tmp_path/'unrelated';hidden.mkdir();(hidden/'present.txt').write_text('x')
    program=('import json,os,sys\nr={}\nfor n,p in json.loads(sys.argv[1]):\n'
             ' try:os.stat(p);r[n]="visible"\n except PermissionError:r[n]="denied"\n except FileNotFoundError:r[n]="absent"\n'
             'print(json.dumps(r))')
    argv=[sys.executable,'-B','-c',program,json.dumps([['unrelated',str(hidden/'present.txt')],['own',str(ws/'outputs')]])]
    done=subprocess.run(sandbox.command(ws,argv,read_paths=sandbox.runtime_paths(argv)),cwd=ws,
                        env={'PATH':'/usr/bin:/bin','HOME':str(ws/'scratch')},capture_output=True,text=True,timeout=10)
    if 'sandbox_apply' in done.stderr:pytest.skip('sandbox-blocked here')
    assert done.returncode==0,done.stderr
    assert json.loads(done.stdout)=={'unrelated':'denied','own':'visible'}


def test_provider_network_allows_outbound_tcp_443_only(tmp_path):
    from ravel.workflow import sandbox
    (tmp_path/'w').mkdir()
    profile=sandbox.macos_profile(tmp_path/'w',network='provider')
    assert '(allow network-outbound (remote tcp "*:443"))' in profile
    assert '(remote tcp))' not in profile and 'network-bind' not in profile and 'network-inbound' not in profile
    assert '(remote tcp' not in sandbox.macos_profile(tmp_path/'w')
    assert sandbox.egress(None)=='none' and sandbox.egress('provider','macos')=='tcp-443'
    assert sandbox.egress('provider','linux')==('tcp-443' if sandbox.linux_port_rules() else 'unrestricted')


def test_denial_probe_runs_the_launch_profile_home_and_network(tmp_path,monkeypatch):
    import json,subprocess
    from ravel.workflow import sandbox
    ws=tmp_path/'worker'
    for name in ('inputs','outputs','scratch'):(ws/name).mkdir(parents=True)
    home=sandbox.cli_home_for(ws);home.mkdir()
    (tmp_path/'private').write_text('x')
    monkeypatch.setattr(sandbox,'available',lambda:'macos')
    seen={}
    def run(argv,**kwargs):
        seen['profile']=argv[2]
        return subprocess.CompletedProcess(argv,0,json.dumps({'read_denied':[True],'write_denied':True,
            'listen_denied':True,'other_port_denied':True,'allowed_input_read':True}),'')
    monkeypatch.setattr(sandbox.subprocess,'run',run)
    evidence=sandbox.probe(ws,forbidden=tmp_path/'private',home=home,network='provider')
    assert seen['profile']==sandbox.macos_profile(ws,home=home,network='provider')
    assert evidence['network']=='tcp-443' and evidence['computed_checks']['network_denied'] is False
    assert evidence['cli_home'] is True


def test_real_provider_profile_denies_ports_other_than_443(tmp_path, require_sandbox):
    import sys
    from ravel.workflow import sandbox
    ws=tmp_path/'worker'
    for name in ('inputs','outputs','scratch'):(ws/name).mkdir(parents=True)
    (tmp_path/'private').write_text('x')
    if sandbox.egress('provider')!='tcp-443':
        pytest.skip('port filtering is a macOS sandbox profile property where the kernel has no port rules')
    try:
        evidence=sandbox.probe(ws,forbidden=tmp_path/'private',read_paths=sandbox.runtime_paths([sys.executable]),
                               network='provider')
    except sandbox.SandboxUnavailable:
        pytest.skip('sandbox-blocked: actual OS confinement unavailable here')
    assert evidence['confirmed'] and evidence['computed_checks']['other_port_denied'] is True


def _keychain_fixture(tmp_path,monkeypatch):
    from ravel.workflow import sandbox
    ws=tmp_path/'worker'
    for name in ('inputs','outputs','scratch'):(ws/name).mkdir(parents=True)
    real=tmp_path/'account/Library/Keychains';real.mkdir(parents=True)
    monkeypatch.setattr(sandbox,'login_keychains',lambda:real)
    home=sandbox.user_home_for(ws);(home/'Library').mkdir(parents=True)
    (home/'Library/Keychains').symlink_to(real,target_is_directory=True)
    return ws,home,real


def test_keychain_home_reads_the_login_keychain_and_never_writes_it(tmp_path,monkeypatch):
    from ravel.workflow import sandbox
    ws,home,real=_keychain_fixture(tmp_path,monkeypatch)
    profile=sandbox.macos_profile(ws,network='provider',keychain_home=home)
    assert '(allow file-read* (subpath '+sandbox.quote(str(real))+') (subpath "/private/var/db/mds"))' in profile
    assert '(allow file-read* file-write* (subpath '+sandbox.quote(str(home))+'))' in profile
    assert not any('file-write' in line and str(real) in line for line in profile.splitlines())
    # The account home and its Library are visible as path entries only, never as readable trees.
    for above in (real.parent,real.parent.parent):
        assert '(subpath '+sandbox.quote(str(above))+')' not in profile
    for name in ('com.apple.securityd','com.apple.security.agent','com.apple.ocspd',
                 'com.apple.system.opendirectoryd.membership'):
        assert '(global-name "'+name+'")' in profile
    assert 'com.apple.SecurityServer' in profile and 'com.apple.trustd' in profile
    # The CLI reads its stored login by running exactly /usr/bin/security; nothing else is named.
    assert '(allow process-exec (literal "/usr/bin/security"))' in profile
    assert '(allow file-read* (literal "/usr/bin/security"))' in profile
    with pytest.raises(sandbox.ReadRootRefused):
        sandbox.macos_profile(ws,keychain_home=sandbox.cli_home_for(ws))
    with pytest.raises(ValueError):
        sandbox.linux_command(ws,['/usr/bin/true'],keychain_home=home)


def test_profiles_without_a_keychain_home_never_name_the_login_keychain(tmp_path,monkeypatch):
    from ravel.workflow import sandbox
    ws,home,real=_keychain_fixture(tmp_path,monkeypatch)
    for kwargs in ({'network':'provider'},{'network':'provider','home':sandbox.cli_home_for(ws)},{}):
        profile=sandbox.macos_profile(ws,**kwargs)
        assert str(real) not in profile and str(home) not in profile and '/private/var/db/mds' not in profile
        assert not any('(global-name "'+name+'")' in profile for name in sandbox.MACOS_KEYCHAIN_SERVICES)
        assert '/usr/bin/security' not in profile


def test_real_keychain_profile_still_denies_ports_other_than_443(tmp_path,monkeypatch,require_sandbox):
    import sys
    from ravel.workflow import sandbox
    ws,home,real=_keychain_fixture(tmp_path,monkeypatch)
    (tmp_path/'private').write_text('x')
    if sandbox.available()!='macos':pytest.skip('the keychain home is a macOS sandbox profile property')
    try:
        evidence=sandbox.probe(ws,forbidden=tmp_path/'private',read_paths=sandbox.runtime_paths([sys.executable]),
                               network='provider',keychain_home=home)
    except sandbox.SandboxUnavailable:
        pytest.skip('sandbox-blocked: actual OS confinement unavailable here')
    assert evidence['confirmed'] and evidence['login_keychain'] is True
    assert evidence['computed_checks']['other_port_denied'] is True and evidence['network']=='tcp-443'


def test_real_keychain_profile_reads_through_the_link_and_never_writes(tmp_path,monkeypatch,require_sandbox):
    import subprocess,sys
    from ravel.workflow import sandbox
    ws,home,real=_keychain_fixture(tmp_path,monkeypatch)
    (real/'login.keychain-db').write_text('synthetic')
    (tmp_path/'account/.profile').write_text('private')
    if sandbox.available()!='macos':pytest.skip('the keychain home is a macOS sandbox profile property')
    program=('import json,pathlib,sys\nh=pathlib.Path(sys.argv[1]);out={}\n'
             'out["read"]=(h/"Library/Keychains/login.keychain-db").read_text()\n'
             'for k,p in (("link_write",h/"Library/Keychains/new"),("real_write",pathlib.Path(sys.argv[2])/"new")):\n'
             ' try:p.write_text("x");out[k]=False\n'
             ' except PermissionError:out[k]=True\n'
             'try:pathlib.Path(sys.argv[3]).read_text();out["home_read"]=False\n'
             'except PermissionError:out["home_read"]=True\n'
             'print(json.dumps(out))\n')
    argv=[sys.executable,'-B','-c',program,str(home),str(real),str(tmp_path/'account/.profile')]
    done=subprocess.run(sandbox.command(ws,argv,read_paths=sandbox.runtime_paths([sys.executable]),network='provider',
                                        keychain_home=home),cwd=ws,env={'PATH':'/usr/bin:/bin','HOME':str(home)},
                        capture_output=True,text=True,timeout=20)
    if 'sandbox_apply' in done.stderr:pytest.skip('sandbox-blocked: actual OS confinement unavailable here')
    import json
    assert json.loads(done.stdout)=={'read':'synthetic','link_write':True,'real_write':True,'home_read':True},done.stderr
    assert sorted(p.name for p in real.iterdir())==['login.keychain-db']


def test_real_keychain_profile_runs_the_security_tool_read_only(tmp_path, require_sandbox):
    """The account's real login keychain, read through the worker's keychain home; no secret is read or printed."""
    import os,pwd,subprocess,sys
    from ravel.workflow import sandbox
    if sandbox.available()!='macos':pytest.skip('the keychain home is a macOS sandbox profile property')
    if not (sandbox.login_keychains()/'login.keychain-db').is_file():pytest.skip('no login keychain on this account')
    ws=tmp_path/'worker'
    for name in ('inputs','outputs','scratch'):(ws/name).mkdir(parents=True)
    home=sandbox.user_home_for(ws);(home/'Library').mkdir(parents=True)
    (home/'Library/Keychains').symlink_to(sandbox.login_keychains(),target_is_directory=True)
    account=pwd.getpwuid(os.getuid()).pw_name
    env={'PATH':'/usr/bin:/bin','HOME':str(home),'TMPDIR':str(ws/'scratch'),'USER':account,'LOGNAME':account}
    def run(*args):
        argv=sandbox.command(ws,['/usr/bin/security',*args],read_paths=sandbox.runtime_paths([sys.executable]),
                             network='provider',keychain_home=home)
        return subprocess.run(argv,cwd=ws,env=env,capture_output=True,text=True,timeout=30)
    info=run('show-keychain-info',str(home/'Library/Keychains/login.keychain-db'))
    if 'sandbox_apply' in info.stderr:pytest.skip('sandbox-blocked: actual OS confinement unavailable here')
    assert info.returncode==0,info.stderr
    # A lookup of a service that does not exist reaches the keychain search (exit 44, item not found).
    missing=run('find-generic-password','-a',account,'-s','ravel-synthetic-absent-service')
    assert missing.returncode==44 and 'could not be found' in missing.stderr


def test_symlinked_run_path_refusal_names_the_real_path(tmp_path):
    import os
    from ravel.workflow import broker
    real=tmp_path/'private-tmp';(real/'run').mkdir(parents=True);link=tmp_path/'tmp';link.symlink_to(real)
    with pytest.raises(ValueError) as refused:broker.ordinary(link/'run')
    assert str(link) in str(refused.value) and os.path.realpath(link/'run') in str(refused.value)
