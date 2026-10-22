"""The lease root is scoped to the host or Slurm allocation; user-wide stores stay in the state root.

On a cluster the home directory is shared by every node, so an unscoped lease is one lease for the
whole cluster. These tests drive the scope resolution through its seams (the cgroup file, the mount
table, the state root) and never touch the real per-user directory.
"""
from pathlib import Path

import pytest

from ravel.workflow import machine_lease as ml

V2 = '0::/system.slice/slurmstepd.scope/job_9031740/step_batch/user/task_0\n'
V1 = ('12:memory:/slurm/uid_1000/job_9031740/step_0\n'
      '11:cpuset:/slurm/uid_1000/job_9031740/step_0\n')
LOGIN = '0::/user.slice/user-1060200643.slice/session-45623.scope\n'
SHARED = ('nas:/export/homes /net/homes nfs4 rw,relatime 0 0\n'
          '/dev/nvme0n1p2 / ext4 rw 0 0\n')
LOCAL = '/dev/disk3s1 / apfs rw 0 0\n/dev/sda1 /local/homes ext4 rw 0 0\n'
JOB = {'SLURM_JOB_ID': '9031740', 'SLURM_CLUSTER_NAME': 'clustera'}


@pytest.mark.parametrize('cgroup', [V2, V1])
def test_an_allocation_is_proven_by_the_jobs_cgroup(cgroup):
    assert ml.slurm_allocation(JOB, cgroup) == {'cluster': 'clustera', 'job_id': '9031740'}


@pytest.mark.parametrize('environ,cgroup', [
    (JOB, LOGIN),                                                   # copied variable on a login node
    ({'SLURM_JOB_ID': '903174'}, V2),                               # a prefix of the real job id
    ({'SLURM_JOB_ID': '9031740;rm'}, V2),                           # not a job id
    ({}, V2),                                                       # no variable
])
def test_a_variable_without_the_cgroup_selects_no_allocation(environ, cgroup):
    assert ml.slurm_allocation(environ, cgroup) is None


def test_an_unreadable_cgroup_selects_no_allocation(monkeypatch, tmp_path):
    monkeypatch.setattr(ml, '_PROC_CGROUP', str(tmp_path / 'absent'))
    assert ml.slurm_allocation(JOB) is None


def test_a_site_without_a_cluster_name_keys_the_scope_by_job_id():
    found = ml.slurm_allocation({'SLURM_JOB_ID': '9031740'}, V2)
    assert found == {'cluster': None, 'job_id': '9031740'}
    assert ml.allocation_key(found) == 'slurm-9031740'


def test_a_cluster_name_is_rendered_file_name_safe():
    found = ml.slurm_allocation({'SLURM_JOB_ID': '7', 'SLURM_CLUSTER_NAME': '../x y'}, '0::/job_7/step_0\n')
    assert found['cluster'] == '_x_y' and '/' not in found['cluster']


def test_the_home_file_system_is_matched_by_the_longest_mount_point():
    assert ml.shared_filesystem('/net/homes/a/u/.local/state/ravel/machine', SHARED) == 'nfs4'
    assert ml.shared_filesystem('/local/homes/u/.local/state', LOCAL) is None
    nested = SHARED + 'tmpfs /net/homes/a/u/.local tmpfs rw 0 0\n'
    assert ml.shared_filesystem('/net/homes/a/u/.local/state', nested) is None
    escaped = r'srv:/h /mnt/my\040home lustre rw 0 0' + '\n'
    assert ml.shared_filesystem('/mnt/my home/u', escaped) == 'lustre'
    assert ml.shared_filesystem('/mnt/my homework/u', escaped) is None


def test_scope_kinds():
    root = Path('/net/homes/a/u/.local/state/ravel/machine')
    assert ml.lease_scope(root, environ=JOB, cgroup_text=V2)['key'] == 'slurm-clustera-9031740'
    host = ml.lease_scope(root, environ={}, cgroup_text=LOGIN, mounts_text=SHARED, host='epyc-1-1')
    assert host == {'kind': 'host', 'key': 'host-epyc-1-1', 'host': 'epyc-1-1', 'filesystem': 'nfs4'}
    laptop = ml.lease_scope(Path('/local/homes/u/.local/state/ravel/machine'), environ=JOB, cgroup_text=LOGIN,
                            mounts_text=LOCAL, host='laptop')
    assert laptop == {'kind': 'machine', 'key': None}


@pytest.fixture
def machine_domain(monkeypatch, tmp_path):
    """The machine-domain rules, resolved at a temporary state root through the scope seams."""
    root = tmp_path / 'state/machine'
    monkeypatch.setattr(ml, '_TEST_DOMAIN', None)
    monkeypatch.setattr(ml, '_GRANTED', None)
    monkeypatch.delenv(ml.GRANT_ENV, raising=False)
    monkeypatch.setattr(ml, 'RUNNER_ENV', 'RAVEL_SCOPE_TEST_UNSET_RUNNER')  # pytest resets its own variable per phase
    monkeypatch.setattr(ml, '_state_root_path', lambda: root)
    cgroup = tmp_path / 'cgroup'
    monkeypatch.setattr(ml, '_PROC_CGROUP', str(cgroup))
    mounts = tmp_path / 'mounts'
    mounts.write_text(f'srv:/home {tmp_path} nfs4 rw 0 0\n')
    monkeypatch.setattr(ml, '_PROC_MOUNTS', str(mounts))
    monkeypatch.setattr(ml.sys, 'platform', 'linux')
    monkeypatch.setattr(ml.socket, 'gethostname', lambda: 'epyc-2-11')

    def enter(job):
        if job is None:
            monkeypatch.delenv('SLURM_JOB_ID', raising=False)
            cgroup.write_text(LOGIN)
        else:
            monkeypatch.setenv('SLURM_JOB_ID', job)
            monkeypatch.setenv('SLURM_CLUSTER_NAME', 'clustera')
            cgroup.write_text(f'0::/system.slice/slurmstepd.scope/job_{job}/step_batch/user/task_0\n')
    return root, enter


def test_each_allocation_has_its_own_lease_root_and_the_state_root_is_shared(machine_domain):
    root, enter = machine_domain
    enter('101')
    assert ml.domain() == 'machine'
    assert ml.machine_dir() == root / 'scopes/slurm-clustera-101'
    assert ml.machine_state_root() == root
    assert ml.scope()['kind'] == 'slurm-job'
    enter('102')
    assert ml.machine_dir() == root / 'scopes/slurm-clustera-102'
    assert ml.machine_state_root() == root
    enter(None)
    assert ml.machine_dir() == root / 'scopes/host-epyc-2-11'
    assert ml.scope() == {'kind': 'host', 'key': 'host-epyc-2-11', 'host': 'epyc-2-11', 'filesystem': 'nfs4',
                               'directory': str(root / 'scopes/host-epyc-2-11')}


def test_two_allocations_hold_their_locks_at_once_and_one_allocation_stays_exclusive(machine_domain):
    root, enter = machine_domain
    enter('101')
    with ml.machine_lock(ml.MUTEX_NAME, wait_seconds=0):
        enter('102')
        with ml.machine_lock(ml.MUTEX_NAME, wait_seconds=0) as second:
            assert second == root / 'scopes/slurm-clustera-102' / ml.MUTEX_NAME
        enter('101')
        with pytest.raises(ml.LeaseBusy):
            with ml.machine_lock(ml.MUTEX_NAME, wait_seconds=0):
                pass


def test_a_fresh_machine_lease_still_needs_an_approved_stage_in_an_allocation(machine_domain):
    _, enter = machine_domain
    enter('101')
    with pytest.raises(ml.LeaseBusy, match='approved stage'):
        ml.acquire('unbound probe')


def test_htcondor_batch_slots_use_worker_scratch_and_keep_persistent_state(machine_domain, tmp_path, monkeypatch):
    root, enter = machine_domain
    enter(None)
    monkeypatch.setenv('RAVEL_LEASE_SCOPE', 'batch-slot')
    scratch = tmp_path / 'slot-a'
    scratch.mkdir()
    (scratch / '.job.ad').write_text('ClusterId = 1\n')
    monkeypatch.setenv('_CONDOR_SCRATCH_DIR', str(scratch))
    monkeypatch.setenv('_CONDOR_JOB_AD', str(scratch / '.job.ad'))
    assert ml.machine_dir() == scratch / '.ravel-lease'
    assert ml.machine_state_root() == root
    assert ml.scope()['kind'] == 'batch-slot'
    first = ml.machine_dir()
    second = tmp_path / 'slot-b'
    second.mkdir()
    (second / '.job.ad').write_text('ClusterId = 2\n')
    monkeypatch.setenv('_CONDOR_SCRATCH_DIR', str(second))
    monkeypatch.setenv('_CONDOR_JOB_AD', str(second / '.job.ad'))
    assert ml.machine_dir() != first
    assert ml.lease_domain()['policy']['batch_slot_dir_env'] == '_CONDOR_SCRATCH_DIR'
    monkeypatch.delenv('_CONDOR_SCRATCH_DIR')
    with pytest.raises(ValueError, match='_CONDOR_SCRATCH_DIR'):
        ml.machine_dir()


@pytest.mark.parametrize('job_ad', ['missing', 'unset', 'outside', 'linked'])
def test_batch_slot_scope_requires_the_starter_job_ad_in_worker_scratch(machine_domain, tmp_path, monkeypatch, job_ad):
    # The variables alone do not prove a batch slot: an owned directory on a laptop
    # would otherwise give every process its own lease.
    root, enter = machine_domain
    enter(None)
    scratch = tmp_path / 'slot'
    scratch.mkdir()
    monkeypatch.setenv('RAVEL_LEASE_SCOPE', 'batch-slot')
    monkeypatch.setenv('_CONDOR_SCRATCH_DIR', str(scratch))
    ad = scratch / '.job.ad'
    if job_ad == 'unset':
        ad.write_text('ClusterId = 1\n')
        monkeypatch.delenv('_CONDOR_JOB_AD', raising=False)
    elif job_ad == 'outside':
        ad = tmp_path / '.job.ad'
        ad.write_text('ClusterId = 1\n')
    elif job_ad == 'linked':
        (tmp_path / 'ad').write_text('ClusterId = 1\n')
        ad.symlink_to(tmp_path / 'ad')
    if job_ad != 'unset':
        monkeypatch.setenv('_CONDOR_JOB_AD', str(ad))
    with pytest.raises(ValueError, match='_CONDOR_JOB_AD'):
        ml.machine_dir()


WHOLE = '         0          0 4294967295\n'
SANDBOX = '      1000       1000          1\n'


@pytest.mark.parametrize('text,confined', [(WHOLE, False), (SANDBOX, True), ('0 100000 65536\n', True), ('', False)])
def test_a_partial_uid_map_marks_a_user_namespace_sandbox(monkeypatch, tmp_path, text, confined):
    uid_map = tmp_path / 'uid_map'
    uid_map.write_text(text)
    monkeypatch.setattr(ml, '_PROC_UID_MAP', str(uid_map))
    assert ml._in_user_namespace() is confined
    monkeypatch.setattr(ml, '_PROC_UID_MAP', str(tmp_path / 'absent'))
    assert ml._in_user_namespace() is False


@pytest.mark.parametrize('uid_map,passwd,declared,home,expected', [
    # The host: the account's home, whatever the environment says.
    (WHOLE, '/srv/account', '/declared', '/scratch/private', '/srv/account/.local/state/ravel/machine'),
    # A sandbox that keeps the host's password file: the declared launch state, else the private HOME.
    (SANDBOX, '/srv/account', '/declared', '/scratch/private', '/declared/machine'),
    (SANDBOX, '/srv/account', None, '/scratch/private', '/scratch/private/.local/state/ravel/machine'),
    (SANDBOX, '/srv/account', None, None, '/srv/account/.local/state/ravel/machine'),
    (SANDBOX, '/srv/account', None, 'relative', '/srv/account/.local/state/ravel/machine'),
    # A sandbox with no entry for the uid.
    (SANDBOX, None, '/declared', '/scratch/private', '/declared/machine'),
    (SANDBOX, None, None, '/scratch/private', '/scratch/private/.local/state/ravel/machine'),
    (WHOLE, None, None, '/scratch/private', '/scratch/private/.local/state/ravel/machine'),
])
def test_a_confined_launch_keeps_its_state_in_its_declared_or_private_location(
        monkeypatch, tmp_path, uid_map, passwd, declared, home, expected):
    import types
    mapping = tmp_path / 'uid_map'
    mapping.write_text(uid_map)
    monkeypatch.setattr(ml, '_PROC_UID_MAP', str(mapping))

    def entry(uid):
        if passwd is None:
            raise KeyError(uid)
        return types.SimpleNamespace(pw_dir=passwd)
    monkeypatch.setattr(ml.pwd, 'getpwuid', entry)
    for name, value in (('RAVEL_LAUNCH_STATE', declared), ('HOME', home)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert ml._state_root_path() == Path(expected)


def test_a_launch_with_no_password_entry_and_no_home_has_no_state_root(monkeypatch, tmp_path):
    def entry(uid):
        raise KeyError(uid)
    monkeypatch.setattr(ml.pwd, 'getpwuid', entry)
    monkeypatch.delenv('HOME', raising=False)
    monkeypatch.delenv('RAVEL_LAUNCH_STATE', raising=False)
    with pytest.raises(ValueError, match='no state root'):
        ml._state_root_path()
