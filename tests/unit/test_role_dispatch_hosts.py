"""Every registered role on every native host: parser and fail-closed handoff.

Collected by the default suite. Profiles are rendered in memory; no installed
host configuration is read or changed and no model or native job is launched.
"""
import re
import shlex

import pytest

from ravel.workflow import role_registry
from ravel.workflow.transports import generic_delegate, host_subagent
from test_role_dispatch import call, spec, tool

HOSTS = ('claude', 'codex', 'gemini', 'opencode', 'antigravity')
CARDS = role_registry.all_cards()
PROFILES = {host: role_registry.render(host) for host in HOSTS}


@pytest.mark.parametrize('host', HOSTS)
@pytest.mark.parametrize('card', CARDS, ids=lambda c: c['id'])
def test_every_role_redirect_parses_and_refuses_unqualified_required_host(host, card, tmp_path):
    path = role_registry.profile_paths(host)[card['id']]
    content = PROFILES[host][path]
    commands = re.findall(r'`(python -m ravel\.workflow\.transports\.host_subagent dispatch [^`]+)`', content)
    assert len(commands) == 1
    command = shlex.split(commands[0])
    args = host_subagent.dispatch_parser().parse_args(command[3:])
    assert args.role == card['id'] and args.node == 'NODE'
    assert str(args.rundir) == 'RUN' and str(args.spec) == 'SPEC.json' and str(args.subject) == 'SUBJECT.json'
    assert 'never substitute a parent persona' in content
    run = tmp_path / 'fictional-run'
    run.mkdir()
    adapter = generic_delegate.DelegateAdapter(tool(host=host), lambda _: pytest.fail('required role was delegated'))
    result = call(run, spec(role=card['id'], host=host), adapter=adapter)
    assert result['status'] == 'refused' and not result['required_role_satisfied']
    assert result['role'] == card['id'] and result['missing']
    assert not list(run.rglob('*.host-brief.json'))


def test_census_includes_every_role_on_exactly_five_hosts():
    assert len(CARDS) == len(role_registry.registry_document()['roles'])
    assert len(CARDS) >= 89 and len(PROFILES) == 5
