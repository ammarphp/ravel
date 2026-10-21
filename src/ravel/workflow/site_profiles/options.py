"""Stdlib-only validation shared by profile rendering and scheduler clients."""
from copy import deepcopy
import os
from pathlib import Path
import re
import sys

IDENTIFIER = re.compile(r'[A-Za-z0-9_.-]{1,64}\Z')
KEY = re.compile(r'[A-Za-z+][A-Za-z0-9_.+-]{0,63}\Z')
RESERVED = {k.lower() for k in (
    'universe', 'executable', 'arguments', 'initialdir', 'request_cpus', 'request_memory',
    'request_disk', 'output', 'error', 'log', 'queue', 'getenv', 'environment',
    'should_transfer_files', 'use_x509userproxy', 'x509userproxy', 'batch_name',
    '+RavelProject', '+RavelRun', '+RavelTask', '+RavelPause', '+MaxRuntime',
    '+JobFlavour', 'periodic_remove')}
# Other names the scheduler accepts for the fixed lines above.
ALIASES = ('cmd', 'args', 'arguments2', 'iwd', 'job_iwd', 'out', 'err', 'stdout', 'stderr',
           'userlog', 'env', 'environment2', 'jobuniverse', 'jobbatchname')
DEFAULTS = {'mem_mb': 1024, 'runtime': 60, 'runtime_attribute': '+MaxRuntime',
            'flavour': None, 'analysis_bin': str(Path(sys.executable).parent),
            'ravel_env': [], 'workflow_dir': None, 'log_dir': None,
            'output_dir': None, 'error_dir': None, 'lease_scope': 'batch-slot',
            'use_x509userproxy': False, 'x509userproxy_env': None, 'site_options': {},
            'hold_grace_seconds': 1800, 'status_cache_seconds': 20,
            'missing_grace_seconds': 600}
# How the profile's scheduler commands reach the scheduler: the executor's own client (the default,
# recorded as no option so an executor profile keeps its original bytes) or the controller
# submission broker of a confined workflow child (``ravel.workflow.wms_broker``).
SUBMISSION_MODES = ('executor', 'broker')
OPTIONAL = ('submission',)


def _field(key):
    # `+Name`, `MY.Name`, `Name` and `na_me` reach the same job attribute.
    key = key.lower()
    return (key[3:] if key.startswith('my.') else key).lstrip('+').replace('_', '')


FIXED = {_field(k) for k in (*RESERVED, *ALIASES)}


def protected(key):
    # Queue is submit syntax, not a job attribute. All other aliases stay protected.
    return _field(key) in FIXED and not re.fullmatch(r'\+queue', key, re.IGNORECASE)


def identifier(value, label):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(label + ' must match [A-Za-z0-9_.-]{1,64}')
    return value


def single_line(value):
    if not isinstance(value, str) or any(c in value for c in '\n\r\x00'):
        raise ValueError('single-line string required')
    return value


def normalize(options=None):
    if options is None:
        options = {}
    if not isinstance(options, dict) or set(options) - set(DEFAULTS) - set(OPTIONAL):
        raise ValueError('known HTCondor profile options required')
    result = deepcopy(DEFAULTS)
    result.update(deepcopy(options))
    for key in ('mem_mb', 'runtime', 'hold_grace_seconds', 'status_cache_seconds', 'missing_grace_seconds'):
        if type(result[key]) is not int or result[key] <= 0:
            raise ValueError(key + ' must be a positive integer')
    for key in ('analysis_bin', 'workflow_dir', 'log_dir', 'output_dir', 'error_dir', 'flavour'):
        if result[key] is not None:
            single_line(result[key])
            if not result[key]:
                raise ValueError(key + ' must not be empty')
    attr = result['runtime_attribute']
    if (not isinstance(attr, str) or not KEY.fullmatch(attr) or not attr.startswith('+')
            or (_field(attr) in FIXED and attr.lower() != '+maxruntime')):
        raise ValueError('runtime_attribute must be a site ClassAd key that does not override fixed fields')
    if result.get('submission', 'executor') not in SUBMISSION_MODES:
        raise ValueError('submission must be executor or broker')
    if result.get('submission') == 'executor':
        del result['submission']
    if type(result['use_x509userproxy']) is not bool:
        raise ValueError('use_x509userproxy must be a boolean')
    proxy = result['x509userproxy_env']
    if proxy is not None and (not isinstance(proxy, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', proxy)):
        raise ValueError('x509userproxy_env must name an environment variable')
    if proxy and result['use_x509userproxy']:
        raise ValueError('choose one credential hand-off mode')
    names = result['ravel_env']
    if not isinstance(names, list) or any(not isinstance(n, str) or not re.fullmatch(r'RAVEL_[A-Z0-9_]+', n) for n in names):
        raise ValueError('ravel_env must list named RAVEL variables')
    if 'RAVEL_LEASE_SCOPE' in names:
        raise ValueError('RAVEL_LEASE_SCOPE is controlled by lease_scope')
    if result['lease_scope'] not in ('batch-slot', 'machine'):
        raise ValueError('lease_scope must be batch-slot or machine')
    site = result['site_options']
    if not isinstance(site, dict):
        raise ValueError('site_options must be a key/value map')
    for key, value in site.items():
        if not isinstance(key, str) or not KEY.fullmatch(key) or protected(key) or _field(key) == _field(attr):
            raise ValueError('site options cannot override fixed fields and require plain keys')
        if type(value) not in (str, int):
            raise ValueError('site option values must be strings or integers')
        single_line(str(value))
    return result


def unpack(profile=None):
    if profile is None:
        return None, normalize()
    if not isinstance(profile, dict):
        raise ValueError('profile must be a JSON object')
    project = profile.get('project_id')
    if project is not None:
        identifier(project, 'project_id')
    return project, normalize(profile.get('options'))


def workflow_dir(options):
    return Path(options['workflow_dir'] or os.getcwd()).absolute()
