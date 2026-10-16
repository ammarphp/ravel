"""Pinned HTCondor project profiles and shared-state launch admission."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from ravel.physics import root_stream_core as core
from . import site_workflow, wms_runtime


def profile_pin(folder):
    """Pin the complete profile directory, including its exact member roster."""
    folder = Path(folder)
    core.require(folder.is_dir() and not folder.is_symlink(), 'ordinary site profile directory required')
    core.require({p.name for p in folder.iterdir()} == {'config.yaml', 'profile.json'},
                 'site profile members changed')
    files = []
    for name in ('config.yaml', 'profile.json'):
        path = folder / name
        core.require(path.is_file() and not path.is_symlink(), 'ordinary site profile files required')
        files.append(site_workflow._pin(path))
    digest = hashlib.sha256(json.dumps(
        [{k: v for k, v in row.items() if k != 'path'} | {'name': Path(row['path']).name} for row in files],
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'path': str(folder), 'sha256': digest, 'files': files}


def shared_state(project, declared):
    """Check a declared shared POSIX root; declaration still requires worker qualification."""
    from . import machine_lease
    core.require(declared is not None and Path(declared).is_absolute(),
                 'HTCondor requires --shared-state-root: a declared worker-reachable shared POSIX path')
    root = Path(declared).resolve()
    project = Path(project).resolve()
    core.require(root.is_dir() and (project == root or root in project.parents),
                 'project and run state must be inside the declared shared state root')
    local = [Path(p).resolve() for p in ('/tmp', '/var/tmp', '/dev/shm', '/scratch')]
    local += [Path(os.environ[n]).resolve() for n in ('_CONDOR_SCRATCH_DIR', 'TMPDIR') if os.environ.get(n)]
    # A mounted shared work area may sit underneath /tmp on a qualified test host.
    network = machine_lease.shared_filesystem(project)
    core.require(network is not None or not any(p == project or p in project.parents for p in local),
                 'node-local state refused for HTCondor multi-node launch; use a shared POSIX work area')
    return str(root)


def initialize(project, *, jobs, remote_ceiling, shared_state_root, options):
    from .site_profiles.htcondor import write_governed_profile
    wms = {**site_workflow.LEGACY_WMS, 'profile': 'htcondor', 'jobs': jobs,
           'remote_ceiling': remote_ceiling}
    site_workflow.validate_wms(wms)
    shared = shared_state(project, shared_state_root)
    shim = wms_runtime._site_wms_record()
    core.require(shim and len(shim) == 1 and Path(shim[0]).name == 'ravel-snakemake',
                 'HTCondor requires the installed site ravel-snakemake shim (RAVEL_SITE_PREFIX)')
    folder = Path(project) / '.ravel-site' / 'profiles' / 'htcondor'
    core.require(not folder.exists(), 'site profile already exists; preserve it and its original pin')
    write_governed_profile(project, jobs=jobs, options=options)
    return wms, {'profile': profile_pin(folder), 'shim': site_workflow._pin(shim[0]),
                 'shared_state_root': shared, 'lease_scope': 'batch-slot',
                 'batch_slot_dir_env': '_CONDOR_SCRATCH_DIR'}


def validate(project, config, jobs=None):
    core.require(config.get('profile') == 'htcondor', 'HTCondor project required')
    site = config['site']
    folder = Path(project) / '.ravel-site' / 'profiles' / 'htcondor'
    core.require(profile_pin(folder) == site['profile'], 'pinned site profile changed; restore its original bytes')
    shim = site['shim']
    core.require(site_workflow._pin(shim['path']) == shim and os.access(shim['path'], os.X_OK),
                 'pinned site shim changed or is not executable')
    shared_state(project, site['shared_state_root'])
    wms = dict(config['wms'])
    if jobs is not None:
        wms['jobs'] = jobs
    site_workflow.validate_wms(wms)
    return site, wms['jobs']


def freeze(project, site, task, number):
    folder = Path(project) / '.ravel-site' / 'launches' / task / f'{number:06d}' / 'htcondor'
    folder.mkdir(parents=True)
    for row in site['profile']['files']:
        target = folder / Path(row['path']).name
        shutil.copyfile(row['path'], target)
        target.chmod(0o444)
    pin = profile_pin(folder)
    core.require(pin['sha256'] == site['profile']['sha256'], 'site profile changed while freezing launch')
    return pin


def require_approved_fanout(workflow, task, jobs):
    """A project ceiling cannot widen the exact fan-out of an approved partition master."""
    from . import science, wms_launch
    if jobs == json.loads((Path(workflow) / 'project.json').read_bytes())['wms']['jobs']:
        return  # add and verify already checked this exact exported WMS block
    index = json.loads((Path(workflow) / 'index.json').read_bytes())
    bound = wms_launch._closure(index, task)
    for row in index['tasks']:
        if row['id'] not in bound:
            continue
        document = site_workflow.verify(row['export']['path'], row['export']['sha256'])
        if jobs == site_workflow.wms_profile(document['wms'])['jobs']:
            continue
        effective = {**document['wms'], 'jobs': jobs}
        for stage in document['tasks']:
            rd = Path(stage['rundir'])
            spec = science.execution_spec(rd)
            if spec['mode'] == 'root-stream':
                site_workflow._partition_task(spec, rd, core.Capture(), effective, set(), {})


def admit_command(argv, project, cwd):
    """Only the exact command of a live governed launch may use a site profile."""
    from . import wms_policy, wms_launch
    project = Path(project).resolve()
    wf = project / 'workflow'
    config = json.loads((wf / 'project.json').read_bytes())
    site, _ = validate(project, config)
    core.require(Path(cwd).resolve() == wf and argv[0] == site['shim']['path'],
                 'site command must use the pinned shim and workflow directory')
    core.require(not os.path.lexists(wf / 'profiles'), 'unmanaged workflow profiles refused')
    for path in (wf / '.live').glob('launch-*.json'):
        live = wms_policy._live(path)
        if live and live.get('argv') == argv:
            pinned = live['site_profile']
            expected = project / '.ravel-site' / 'launches' / live['task'] / f"{live['launch']:06d}" / 'htcondor'
            core.require(pinned['path'] == str(expected) and profile_pin(expected) == pinned
                         and pinned['sha256'] == site['profile']['sha256'], 'live site profile digest differs')
            _, count = validate(project, config, live['jobs'])
            require_approved_fanout(wf, live['task'], count)
            wms_launch._parse_inputs(wf, live['task'])
            parse = live['parse_inputs']
            core.require(not os.path.lexists(Path(parse['snakefile']['path']).parent / 'profiles'),
                         'unmanaged frozen workflow profiles refused')
            for pin in [parse['snakefile'], parse['index'], *parse['rules']]:
                core.require(site_workflow._pin(pin['path']) == pin, 'live parse input changed')
            core.require(Path(parse['snakefile']['path']).read_bytes() == wms_launch.SNAKEFILE,
                         'live Snakefile differs')
            target = f"exports/{live['task']}/completed/{live['task']}.json"
            expected_argv = [site['shim']['path'], '--snakefile', parse['snakefile']['path'], '--directory', str(wf),
                             '--cores', '1', '--retries', '0', '--profile', pinned['path'], '--jobs', str(count), target]
            core.require(argv == expected_argv, 'command differs from governed site launch')
            return
    raise ValueError('site profiles run only inside a live `ravel wms launch`; arbitrary --profile/--executor refused')
