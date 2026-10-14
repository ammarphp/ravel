# census-module: ravel.workflow.synthetic_caller
"""A host call reached through import aliases and a helper function."""
from ravel.workflow import agent_host as hosts
from ravel.workflow.agent_host import AgentHost as Host


def _make(config):
    return Host(config)


def through_alias(config, request):
    return Host(config).execute(request)


def through_module_alias(config, request):
    return hosts.AgentHost(config).execute(request)


def through_helper(config, request):
    return _make(config).execute(request)


def through_annotation(host: Host, request):
    return host.execute(request)


def through_getattr(config, request):
    cls = getattr(hosts, "AgentHost")
    return cls(config).execute(request)
