"""Render configuration only; site executors have no qualification from export."""
from copy import deepcopy

LABELS = {'local': 'local configuration; dry-run checks only',
          'htcondor': 'configurable, unqualified', 'slurm': 'configurable, unqualified'}


def render(name, *, cores=1, retries=0):
    if name not in LABELS or type(cores) is not int or not 1 <= cores <= 1024:
        raise ValueError('known profile and bounded positive core count required')
    if type(retries) is not int or retries != 0:
        raise ValueError('retries require guarded recovery; profiles permit zero retries')
    config = {'cores': cores, 'jobs': cores, 'retries': 0, 'rerun-incomplete': False}
    if name == 'htcondor':
        config.update({'executor': 'cluster-generic', 'cluster-generic-submit-cmd': 'python -m ravel.workflow.site_profiles.htcondor submit',
                       'cluster-generic-status-cmd': 'python -m ravel.workflow.site_profiles.htcondor status', 'cluster-generic-cancel-cmd': 'condor_rm'})
    elif name == 'slurm':
        config['executor'] = 'slurm'
    else:
        config['executor'] = 'local'
    return {'schema_version': 1, 'name': name, 'label': LABELS[name], 'qualified': False,
            'config': deepcopy(config), 'requirements': {
                'local': [], 'htcondor': ['snakemake-executor-plugin-cluster-generic', 'site submit policies and shared filesystem'],
                'slurm': ['snakemake-executor-plugin-slurm', 'site account and partition']}[name]}


def write_profiles(directory, *, cores=1):
    import json
    from pathlib import Path
    import yaml
    root = Path(directory)
    profiles = []
    for name in LABELS:
        profile = render(name, cores=cores); folder = root / name; folder.mkdir(parents=True)
        config = '# ' + profile['label'] + '\n' + yaml.safe_dump(profile['config'], sort_keys=True)
        (folder / 'config.yaml').write_text(config)
        (folder / 'profile.json').write_text(json.dumps(profile, indent=2, sort_keys=True) + '\n')
        profiles.append(profile)
    return profiles
