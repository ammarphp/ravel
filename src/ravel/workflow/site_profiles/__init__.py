"""Shared-filesystem profiles; rendering is separate from site qualification."""
from copy import deepcopy
import base64
import json
import shlex

from .options import identifier, normalize

LABELS = {'local': 'local configuration; dry-run checks only',
          'htcondor': 'HTCondor shared-filesystem profile; awaits site qualification'}
# The brokered variant's commands; the client module is ravel.workflow.wms_broker_client.
BROKER_COMMANDS = ('submit', 'status', 'cancel')
BROKER_SCRIPT = ('#!/bin/sh\nexec "${{RAVEL_WMS_BROKER_PYTHON:?the controller submission broker is not available}}" '
                 '-m ravel.workflow.wms_broker_client {command} "$@"\n')


def render(name, *, cores=1, retries=0, jobs=None, options=None, project_id=None):
    if name == 'slurm':
        raise ValueError('slurm is not available in this release')
    if name not in LABELS or type(cores) is not int or not 1 <= cores <= 1024:
        raise ValueError('known profile and bounded positive core count required')
    if type(retries) is not int or retries != 0:
        raise ValueError('retries require guarded recovery; profiles permit zero retries')
    jobs = cores if jobs is None else jobs
    if type(jobs) is not int or not 1 <= jobs <= 100000:
        raise ValueError('bounded positive job count required')
    if project_id is not None:
        identifier(project_id, 'project_id')
    config = {'cores': cores, 'jobs': jobs, 'retries': 0, 'rerun-incomplete': False}
    profile = {'schema_version': 1, 'name': name, 'label': LABELS[name], 'qualified': False,
               'project_id': project_id, 'requirements': []}
    if name == 'htcondor':
        effective = normalize(options)
        # The executor variant keeps its original bytes: its mode is the default and no option.
        brokered = effective.get('submission') == 'broker'
        encoded = base64.urlsafe_b64encode(json.dumps(effective, sort_keys=True, separators=(',', ':')).encode()).decode()
        arguments = ['--options-base64', encoded]
        if project_id is not None:
            arguments += ['--project-id', project_id]
        if brokered:
            # A confined workflow child holds no capability and no scheduler command: each
            # command is a typed request to the controller's submission broker.
            profile['scripts'] = {'ravel-' + command + '.sh': BROKER_SCRIPT.format(command=command)
                                  for command in BROKER_COMMANDS}
        else:
            profile['scripts'] = {
                'ravel-' + command + '.sh': '#!/bin/sh\nexec ' + shlex.join(
                    ['ravel-wms-condor-' + command, *arguments]) + ' \"$@\"\n'
                for command in ('submit', 'status')}
        config.update({'executor': 'cluster-generic',
                       'cluster-generic-submit-cmd': 'ravel-submit.sh',
                       'cluster-generic-status-cmd': 'ravel-status.sh',
                       'cluster-generic-cancel-cmd': 'ravel-cancel.sh' if brokered else 'condor_rm',
                       # One sweep per snapshot interval. The executor applies the
                       # per-second limit to each job's call, and those read the snapshot.
                       'max-status-checks-per-second': 10,
                       'seconds-between-status-checks': effective['status_cache_seconds']})
        profile.update({'options': effective, 'release_status': 'tester-qualification',
                        'qualification_command': 'snakemake --snakefile scheduler-check.smk --profile profiles/htcondor --jobs 1',
                        'requirements': ['snakemake-executor-plugin-cluster-generic',
                            'snakemake-interface-executor-plugins>=9.3.2,<10',
                            'executor plugin exact pin from the site install lock',
                            'site submit policies and shared POSIX filesystem']})
    else:
        if options:
            raise ValueError('local profile has no scheduler options')
        config['executor'] = 'local'
    profile['config'] = deepcopy(config)
    return profile


def write_profile(directory, name, *, cores=1, jobs=None, options=None, project_id=None):
    """Write directory/name and return byte pins for its configuration and wrapper files."""
    import hashlib
    from pathlib import Path
    import yaml
    profile = render(name, cores=cores, jobs=jobs, options=options, project_id=project_id)
    folder = Path(directory).absolute() / name
    folder.mkdir(parents=True, exist_ok=True)
    contents = {'config.yaml': '# ' + profile['label'] + '\n' + yaml.safe_dump(profile['config'], sort_keys=True),
                'profile.json': json.dumps(profile, indent=2, sort_keys=True) + '\n'}
    contents.update(profile.get('scripts', {}))
    files = []
    for filename, content in contents.items():
        path = folder / filename
        path.write_text(content, encoding='utf-8')
        if filename.endswith('.sh'):
            path.chmod(0o755)
        files.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'path': str(folder), 'files': files, 'profile': profile}


def write_profiles(directory, *, cores=1):
    return [write_profile(directory, name, cores=cores)['profile'] for name in LABELS]
