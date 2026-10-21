"""Stable resource mechanism identities shared by launch records and their readers.

Mechanism identity is distinct from scope: cooperative thread settings and
per-process address space establish no aggregate launch-tree guarantee.
"""
from enum import Enum


class ResourceMechanism(str, Enum):
    CONTROLLER_WATCHDOG = 'controller-watchdog'
    LINUX_CPU_AFFINITY = 'linux-cpu-affinity'
    COOPERATIVE_THREAD_ENVIRONMENT = 'cooperative-thread-environment'
    LINUX_RLIMIT_AS = 'linux-rlimit-as'


ALLOWED_MECHANISMS = {
    'bwrap': {
        'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG,
        'cpus': ResourceMechanism.LINUX_CPU_AFFINITY,
        'memory_mib': ResourceMechanism.LINUX_RLIMIT_AS,
    },
    'sandbox-exec': {
        'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG,
        'cpus': ResourceMechanism.COOPERATIVE_THREAD_ENVIRONMENT,
    },
}

RESOURCE_SCOPES = {
    ResourceMechanism.CONTROLLER_WATCHDOG: 'controller wall-clock watchdog',
    ResourceMechanism.LINUX_CPU_AFFINITY: 'inherited Linux CPU affinity set',
    ResourceMechanism.COOPERATIVE_THREAD_ENVIRONMENT: 'thread environment (cooperative)',
    ResourceMechanism.LINUX_RLIMIT_AS: 'per-process address-space only (not aggregate RSS)',
}


def resource_scopes(enforced):
    """Describe only implemented mechanisms, keeping unsupported claims explicit."""
    return {name: RESOURCE_SCOPES[value] if value in RESOURCE_SCOPES else 'unsupported'
            for name, value in enforced.items()}


def valid_resource_mapping(backend, limits, enforced):
    """Require exact, supported identities and well-formed finite positive bounds."""
    if (not isinstance(backend, str) or backend not in ALLOWED_MECHANISMS
            or not isinstance(limits, dict) or not isinstance(enforced, dict)
            or not {'wall_seconds', 'cpus'}.issubset(limits)
            or set(limits) != set(enforced)):
        return False
    allowed = ALLOWED_MECHANISMS[backend]
    for key, value in limits.items():
        if key not in allowed or not isinstance(enforced[key], str) or enforced[key] != allowed[key].value:
            return False
        if key == 'wall_seconds':
            if type(value) not in (int, float) or not 0 < value < float('inf'):
                return False
        elif type(value) is not int or value <= 0:
            return False
    return True
