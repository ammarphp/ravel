# census-module: ravel.workflow.agent_host
"""Planted inside the sanctioned agent_host module, at qualnames no sanction names."""


class AgentHost:
    def execute(self, request):
        return request


def rogue_direct(config, request):
    return AgentHost(config).execute(request)


def rogue_alias(config, request):
    run = AgentHost(config).execute
    return run(request)
