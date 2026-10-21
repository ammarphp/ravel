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


def test_provider_profile_never_grants_keychain_or_security_tool(tmp_path):
    import inspect
    from ravel.workflow import sandbox
    ws = tmp_path / 'worker'
    ws.mkdir()
    home = sandbox.cli_home_for(ws)
    home.mkdir(mode=0o700)
    forbidden = ('SecurityServer', 'securityd', 'com.apple.security.agent', 'ocspd',
                 'opendirectoryd.membership', '/usr/bin/security', '/private/var/db/mds', 'Keychains')
    profiles = (sandbox.macos_profile(ws, network='provider'),
                sandbox.macos_profile(ws, network='provider', home=home),
                sandbox.macos_profile(ws))
    for profile in profiles:
        for name in forbidden:
            assert name not in profile, name
    assert not hasattr(sandbox, 'login_keychains')
    assert not hasattr(sandbox, '_keychain')
    assert not any(name.startswith('MACOS_KEYCHAIN_') for name in dir(sandbox))
    for function in (sandbox.macos_profile, sandbox.linux_command, sandbox.command, sandbox.probe):
        assert 'keychain_home' not in inspect.signature(function).parameters


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


def test_profiles_require_file_backed_worker_homes(tmp_path):
    from ravel.workflow import sandbox
    ws = tmp_path / 'worker'
    ws.mkdir()
    with pytest.raises(TypeError):
        sandbox.macos_profile(ws, keychain_home=tmp_path / 'external')
    with pytest.raises(TypeError):
        sandbox.linux_command(ws, ['/usr/bin/true'], keychain_home=tmp_path / 'external')


def test_symlinked_run_path_refusal_names_the_real_path(tmp_path):
    import os
    from ravel.workflow import broker
    real=tmp_path/'private-tmp';(real/'run').mkdir(parents=True);link=tmp_path/'tmp';link.symlink_to(real)
    with pytest.raises(ValueError) as refused:broker.ordinary(link/'run')
    assert str(link) in str(refused.value) and os.path.realpath(link/'run') in str(refused.value)
