"""Host-side rows: on an unrestricted host the hooks are detection, fail closed, and label NOT GOVERNED.

The adversary switches hooks off in local settings, removes the workflow-manager guard, redirects
the hook runtime to a planted package copy, breaks the gate module or the prompt routing, ends a
turn with results but no run, and lowers the tripwire through the environment inside a controller
process. Oracles are the host findings, the hook exit status, the per-user host ledger, the
delivery's governance label and the tripwire verdict; positive controls are the clean project,
a working guard and a process the controller does not own.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from nc_cases import CONTROLLER, ROOT, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _project(nc, name='host-project'):
    """A fictional unrestricted-host project with an ordinary settings file and a legacy run."""
    project = nc.root / name
    (project / '.claude').mkdir(parents=True)
    (project / '.claude' / 'settings.json').write_text(json.dumps({'hooks': {}}))
    run = project / 'trial-runs' / 'legacy-run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'task_contract.json').write_text(json.dumps({'schema_version': 1}))
    return project, run


def _codes(found):
    return {row['code'] for row in found}


@case('SW14', binding=CONTROLLER)
def test_SW14_local_settings_that_switch_hooks_off_are_noticed_and_label_the_delivery(nc):
    require_controller()
    from ravel.workflow import host_governance as governance
    project, run = _project(nc)
    clean = governance.governance_label(run, project)
    assert 'hooks_disabled' not in clean['reasons']  # positive control
    (project / '.claude' / 'settings.local.json').write_text(json.dumps({'disableAllHooks': True}))
    assert 'hooks_disabled' in _codes(governance.settings_findings(project))
    label = governance.governance_label(run, project)
    assert label['label'] == governance.NOT_GOVERNED and 'hooks_disabled' in label['reasons'], label
    (project / '.claude' / 'settings.local.json').write_text(json.dumps({'env': {'PYTHONPATH': '/fictional'}}))
    assert 'settings_environment' in _codes(governance.settings_findings(project))


register(Mutation('SW14', 'ravel.workflow.host_governance:settings_findings', lambda original: lambda *a, **k: [],
                  ('SW14',), binding=MUTATION_CONTROLLER, why='switched-off hooks go unnoticed'))


@case('SW10', binding=CONTROLLER)
def test_SW10_a_hook_table_without_the_workflow_manager_guard_is_noticed(nc):
    require_controller()
    from ravel.workflow import agent_surface, host_governance as governance
    project, run = _project(nc)
    (project / 'workflow').mkdir()
    (project / 'workflow' / 'policy.json').write_text(json.dumps({'schema_version': 1, 'wms_required': True,
                                                                 'engine': 'snakemake'}))
    assert 'wms_guard_absent' in _codes(governance.wms_guard_findings(project))
    assert 'wms_guard_absent' in governance.governance_label(run, project)['reasons']
    # Positive control: a hook table that carries the guard is not reported.
    guarded = {'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
        {'type': 'command', 'command': f'fictional-guard {agent_surface.GUARD_MARK}'}]}]}}
    (project / '.claude' / 'settings.json').write_text(json.dumps(guarded))
    assert 'wms_guard_absent' not in _codes(governance.wms_guard_findings(project))


register(Mutation('SW10', 'ravel.workflow.host_governance:wms_guard_findings', lambda original: lambda *a, **k: [],
                  ('SW10',), binding=MUTATION_CONTROLLER, why='a removed workflow-manager guard goes unnoticed'))


PLANTED_GATE = '''import pathlib, sys
pathlib.Path({marker!r}).write_text("planted gate ran")
print("allow")
'''


# The hook under test; the SW19 mutation substitutes a disposable fail-open copy of it.
HOOK_SCRIPT = ROOT / '.claude' / 'hooks' / 'pretooluse-bash.sh'


def _bash_hook(project, event, env_extra=None):
    hook = HOOK_SCRIPT
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'RAVEL_PYTHON')}
    env.update({'CLAUDE_PROJECT_DIR': str(project), 'RAVEL_PYTHON': sys.executable}, **(env_extra or {}))
    return subprocess.run(['bash', str(hook)], input=json.dumps(event), capture_output=True, text=True, env=env,
                          cwd=project, timeout=120)


@case('SW18', binding=CONTROLLER)
def test_SW18_a_planted_project_gate_is_never_imported_and_a_redirected_runtime_is_noticed(nc):
    require_controller()
    from ravel.workflow import host_governance as governance
    project, _ = _project(nc)
    marker = nc.root / 'planted-gate-ran.txt'
    planted = project / 'src' / 'ravel' / 'workflow'
    planted.mkdir(parents=True)
    (project / 'src' / 'ravel' / '__init__.py').write_text('')
    (planted / '__init__.py').write_text('')
    (planted / 'host_gate.py').write_text(PLANTED_GATE.format(marker=str(marker)))
    event = {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'session_id': 'nc-session', 'cwd': str(project)}
    result = _bash_hook(project, event, {'PYTHONPATH': str(project / 'src')})
    assert not marker.exists(), 'the hook imported the planted project copy of the gate'
    assert result.returncode in (0, 2), result.stderr[-400:]  # the installed gate decided
    runtime = project / '.ravel' / 'hook-runtime.sh'
    runtime.parent.mkdir()
    runtime.write_text(f'# Local runtime settings; never commit this file.\n'
                       f'if [ -z "${{RAVEL_PYTHON:-}}" ]; then RAVEL_PYTHON={sys.executable}; fi\n'
                       f'export RAVEL_PYTHON\nexport PYTHONPATH={project / "src"}${{PYTHONPATH:+:$PYTHONPATH}}\n')
    assert 'hook_runtime_package' in _codes(governance.runtime_findings(project))


register(Mutation('SW18', 'ravel.workflow.host_governance:runtime_findings', lambda original: lambda *a, **k: [],
                  ('SW18',), binding=MUTATION_CONTROLLER, why='a redirected hook runtime goes unnoticed'))


def _ledger_kinds(nc):
    path = Path(os.environ.get('RAVEL_STATE_DIR', '')) / 'host-integrity' / 'events.jsonl'
    if not path.is_file():
        return []
    return [json.loads(line)['kind'] for line in path.read_text().splitlines() if line.strip()]


@case('SW19', binding=CONTROLLER)
def test_SW19_a_broken_gate_module_blocks_the_command_and_labels_the_session(nc):
    require_controller()
    from ravel.workflow import host_governance as governance
    project, run = _project(nc)
    event = {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'session_id': 'nc-session', 'cwd': str(project)}
    broken = nc.root / 'broken-python'
    broken.write_text('#!/bin/sh\nexit 1\n')
    broken.chmod(0o755)
    result = _bash_hook(project, event, {'RAVEL_PYTHON': str(broken)})
    assert result.returncode == 2 and 'NOT GOVERNED' in result.stderr, (result.returncode, result.stderr[-400:])
    assert 'hook_failure' in _ledger_kinds(nc)
    working = _bash_hook(project, event)  # positive control: the installed gate allows a plain listing
    assert working.returncode == 0, working.stderr[-400:]


def _fail_open_copy(original):
    """A disposable copy of the hook whose gate-failure branch lets the command through."""
    import tempfile
    text = Path(original).read_text()
    assert 'ravel_hook_failed pretooluse-bash' in text
    copy = Path(tempfile.mkdtemp(prefix='nc-fail-open-')) / 'pretooluse-bash.sh'
    copy.write_text(text.replace('ravel_hook_failed pretooluse-bash', 'exit 0'))
    copy.chmod(0o755)
    return copy


register(Mutation('SW19', 'test_nc_hosts:HOOK_SCRIPT', _fail_open_copy, ('SW19',), binding=MUTATION_CONTROLLER,
                  why='the bash hook lets a command through when its gate module fails'))


@case('SW32', binding=CONTROLLER)
def test_SW32_a_failed_prompt_routing_blocks_the_prompt_and_labels_the_session(nc):
    require_controller()
    from ravel.workflow import host_hooks
    project, _ = _project(nc)
    command = host_hooks.command('claude', 'prompt')
    broken = nc.root / 'broken-python'
    broken.write_text('#!/bin/sh\nexit 1\n')
    broken.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH',)}
    env.update(CLAUDE_PROJECT_DIR=str(project), RAVEL_PYTHON=str(broken))
    prompt = json.dumps({'prompt': 'Compute a fictional observable.', 'session_id': 'nc-session'})
    result = subprocess.run(['bash', '-c', command], input=prompt, capture_output=True, text=True, env=env,
                            cwd=project, timeout=120)
    assert result.returncode == 2 and 'NOT GOVERNED' in result.stderr, (result.returncode, result.stderr[-400:])
    assert 'hook_failure' in _ledger_kinds(nc)
    assert 'exit 0' not in command.split('[ "$RAVEL_GUARD_STATUS" -eq 0 ] && exit 0', 1)[1], \
        'no failure path of the prompt hook lets the prompt through'


def _prompt_fails_open(original):
    def command(host, phase):
        text = original(host, phase)
        marker = '[ "$RAVEL_GUARD_STATUS" -eq 0 ] && exit 0; '
        return text.replace(marker, marker + 'exit 0; ') if phase == 'prompt' else text
    return command


register(Mutation('SW32', 'ravel.workflow.host_hooks:command', _prompt_fails_open, ('SW32',),
                  binding=MUTATION_CONTROLLER, why='a failed prompt routing lets the prompt through'))


@case('SW31', binding=CONTROLLER)
def test_SW31_a_delivery_turn_without_a_resolvable_run_is_labelled_not_governed(nc):
    require_controller()
    from ravel.workflow import stop_dispatch
    project, _ = _project(nc)
    notice = stop_dispatch.unresolved_notice(str(project), 'nc-session',
                                             'Here is the results deck for the fictional limit (see RESULT.md).')
    assert notice and 'NOT GOVERNED' in notice
    assert 'stop_unresolved' in _ledger_kinds(nc)
    # A session whose physics request was routed is labelled whatever its last message says.
    (project / 'logs').mkdir(exist_ok=True)
    (project / 'logs' / '.route-pending-nc-routed').write_text('routed')
    assert stop_dispatch.unresolved_notice(str(project), 'nc-routed', 'The limit is 1.0.')
    # Positive control: an unrouted turn that delivers nothing carries no notice.
    assert stop_dispatch.unresolved_notice(str(project), 'nc-session-two', 'Reading the inputs now.') is None


register(Mutation('SW31', 'ravel.workflow.stop_dispatch:unresolved_notice', lambda original: lambda *a, **k: None,
                  ('SW31',), binding=MUTATION_CONTROLLER, why='an ungoverned delivery turn carries no label'))


@case('SW15', binding=CONTROLLER)
def test_SW15_the_tripwire_blocks_in_a_controller_process_whatever_the_environment_says(nc):
    require_controller()
    from ravel.workflow import agent_tripwire as tripwire
    layer = sorted(tripwire._layers())[0]
    nc.patch.setenv(tripwire.ENV, '0')
    tripwire.check(layer)  # positive control: outside a controller process the variable turns it off
    with tripwire.controller_scope('nc-run-one'):
        with pytest.raises(tripwire.TripwireViolation):
            tripwire.check(layer)
        nc.patch.delenv(tripwire.ENV)
        with pytest.raises(tripwire.TripwireViolation):
            tripwire.check(layer)


register(Mutation('SW15', 'ravel.workflow.agent_tripwire:effective_mode',
                  lambda original: lambda: ((os.environ.get('RAVEL_AGENT_TRIPWIRE', '') or '').lower(),) * 2,
                  ('SW15',), binding=MUTATION_CONTROLLER, why='the environment lowers the tripwire in a controller process'))


@case('CT08', binding=CONTROLLER)
def test_CT08_every_delivery_of_a_run_the_controller_does_not_own_is_labelled_not_governed(nc):
    require_controller()
    from ravel.workflow import host_governance as governance
    project, run = _project(nc)
    label = governance.governance_label(run, project)
    assert label['label'] == governance.NOT_GOVERNED and 'unrestricted_host' in label['reasons'], label
    store, run_dir = controller_run(nc)
    owned = governance.governance_label(run_dir)
    assert owned['label'] is None and owned['controller_run'] == store.run_id  # positive control


register(Mutation('CT08', 'ravel.workflow.host_governance:governance_label',
                  lambda original: lambda *a, **k: {'label': None, 'controller_run': None, 'reasons': []},
                  ('CT08',), binding=MUTATION_CONTROLLER, why='host deliveries carry no NOT GOVERNED label'))
