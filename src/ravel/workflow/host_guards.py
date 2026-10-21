"""Shared host guards. Standalone stdlib write checks also survive a broken package import."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys


def enforcement(data, project):
    d = data
    repo = Path(project)
    session = d.get('session_id') or ''
    ti = d.get('tool_input') or {}
    path = ti.get('file_path') or ti.get('notebook_path') or ''
    if not path:
        return "allow"
    p = os.path.abspath(path)
    resolved = str(Path(p).resolve())
    physics = bool(session) and (repo / 'logs' / ('.route-pending-' + session)).is_file()
    # Registry lookup is intentionally independent of importing the enforcement package.
    if not physics and session:
        state = Path(os.environ.get('RAVEL_STATE_DIR') or Path.home() / '.local/state/ravel')
        key = hashlib.sha256(session.encode('utf-8')).hexdigest()[:32] + '.json'
        try:
            row = json.loads((state / 'active-runs' / key).read_text())
            physics = (row.get('schema_version') == 1 and row.get('kind') == 'active-run'
                       and row.get('session_id') == session and isinstance(row.get('rundir'), str)
                       and (Path(row['rundir']) / 'run_state.json').is_file())
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    if not physics and d.get('cwd'):
        cwd = Path(d['cwd']).expanduser().absolute()
        physics = any((candidate / 'run_state.json').is_file() for candidate in (cwd, *cwd.parents))
    if not physics and session:
        for candidate in (repo / 'trial-runs').glob('*/run_state.json'):
            try:
                if json.loads(candidate.read_text()).get('session_id') == session:
                    physics = True
                    break
            except (OSError, ValueError, AttributeError):
                continue
    if not physics:
        return "allow"
    try:
        from ravel.workflow import host_governance as hg
    except Exception:
        return "block:the ravel enforcement module is unavailable; restore the installed hook interpreter"
    # Host tables (project and user level, local overrides included), hook runtimes, guard
    # code and the controller's own package and data.
    ENF = re.compile(r'/\.claude/settings(?:\.local)?\.json$|/\.claude/hooks/'
                     r'|/\.(claude|codex|gemini|antigravity|opencode)/(?:[^/]+/)*ravel-gate\.sh$'
                     r'|/\.codex/(?:hooks\.json|config\.toml)$|/\.gemini/settings\.json$'
                     r'|/\.opencode/plugins/ravel-guards\.js$'
                     r'|/\.ravel/(?:bin/|activate\.sh$|hook-runtime\.sh$|agent-surface(?:\.local)?\.json$)'
                     r'|/tests/adversarial/'
                     r'|/scripts/(green_board|check_repository)\.py$|/Makefile$'
                     r'|/src/ravel/(validation|workflow)/(?:[^/]+/)*[^/]+\.py$|/src/ravel/controller/'
                     r'|/src/ravel/data/(?:controller|obligations|instructions|judgment|agent_surface|agents|gates'
                     r'|transports)/'
                     r'|/src/ravel/plotting/figure_target\.py$'
                     r'|/src/ravel/(paths|evidence_layout|_bootstrap|cli)\.py$')
    try:
        paths = list(hg.surface_files(repo).values())
        # Digests include existing files. Write protection also includes registered
        # destinations that have not been created yet.
        for extension in hg.SURFACE_EXTENSIONS:
            paths.extend(extension(repo).values())
        registered = {str(Path(value).resolve()) for value in paths}
    except Exception:
        return "block:the enforcement surface could not be resolved"
    try:
        # The RAVEL package this guard runs, wherever it is installed, and the per-user run
        # registry and host ledger: none of them is written from a physics session.
        installed = str(hg.installed_source().resolve() / 'ravel') + os.sep
        from ravel.workflow.active_run import state_dir
        state = str(state_dir().expanduser().resolve()) + os.sep
        owned = tuple(state + name + os.sep for name in ('active-runs', 'host-integrity'))
        user = hg.user_settings_dir().expanduser().resolve()
        tables = {str(user / name) for name in hg.USER_SETTINGS_FILES}
    except Exception:
        return "block:the enforcement surface could not be resolved"
    inside = resolved in tables or any(candidate.startswith(prefix) for candidate in (p + os.sep, resolved + os.sep)
                                       for prefix in (installed, *owned))
    return ('block:the enforcement surface is read-only during a physics session'
          if ENF.search(p) or ENF.search(resolved) or resolved in registered or inside else 'allow')


def protected_cards(raw, root):
    """Legacy raw-JSON path match, preserving Claude's original verdict and message."""
    if root is not None and re.search(r'"' + re.escape(str(root)) + r'/(proc_card\.dat|param_card[^/"]*\.dat)"', raw):
        return (f'BLOCKED: the pristine original cards in {root} (proc_card.dat, param_card*.dat) '
                "are read-only ground truth. Copy them into the run's inputs/ and edit the copy. "
                '(See CLAUDE.md hard rules.)')
    return None


CARD_HOOK = None


def card_protection_enabled(project):
    """The same hook registration that enables Claude's source-card guard."""
    if CARD_HOOK is None:
        return False
    settings = Path(project) / '.claude/settings.json'
    if not settings.is_file():
        return False
    data = json.loads(settings.read_text())
    return any(token.endswith('/' + CARD_HOOK) or token == CARD_HOOK
               for group in data.get('hooks', {}).get('PreToolUse', [])
               for hook in group.get('hooks', [])
               for token in shlex.split(hook.get('command', '')))


def card_root(project):
    import subprocess
    if not card_protection_enabled(project):
        return None
    if os.environ.get('RAVEL_PROTECTED_CARD_ROOT'):
        return Path(os.environ['RAVEL_PROTECTED_CARD_ROOT'])
    done = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=project,
                          text=True, capture_output=True)
    if done.returncode == 0:
        return (Path(project) / done.stdout.strip()).resolve().parent.parent
    return Path(project).resolve().parent


def normalize(data, host):
    """Translate documented argument names; never evaluate shell or patch content."""
    if not isinstance(data, dict) or not isinstance(data.get('tool_input', {}), dict):
        raise ValueError('tool event must be an object with object tool_input')
    event = dict(data)
    ti = dict(event.get('tool_input', {}))
    name = event.get('tool_name', '')
    event['tool_name'] = {'run_shell_command': 'Bash', 'bash': 'Bash', 'exec_command': 'Bash',
                         'shell_command': 'Bash', 'write_file': 'Write', 'replace': 'Edit',
                         'edit': 'Edit', 'write': 'Write', 'multiedit': 'MultiEdit'}.get(name, name)
    if 'cmd' in ti and 'command' not in ti:
        ti['command'] = ti['cmd']
    if 'filePath' in ti:
        ti['file_path'] = ti['filePath']
    event['tool_input'] = ti
    return event


def edited_paths(data):
    ti = data.get('tool_input', {})
    if data.get('tool_name') == 'apply_patch':
        patch = ti.get('command') or ti.get('patch') or ti.get('patchText') or ''
        if not isinstance(patch, str):
            raise ValueError('patch must be text')
        paths = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', patch, re.M)
        if patch and not paths:
            raise ValueError('cannot resolve patch write destinations')
        return paths
    return [ti[key] for key in ('file_path', 'path', 'notebook_path') if ti.get(key)]


def write_errors(data, project, *, deviations=False):
    errors = []
    root = card_root(project)
    for name in edited_paths(data):
        path = Path(name)
        if not path.is_absolute():
            path = Path(data.get('cwd') or project) / path
        # Check lexical and canonical destinations, including not-yet-created files.
        for candidate in {path.absolute(), path.resolve()}:
            reason = protected_cards(json.dumps(str(candidate)), root)
            if reason:
                errors.append(reason)
            verdict = enforcement({**data, 'tool_input': {'file_path': str(candidate)}}, project)
            if verdict.startswith('block:'):
                errors.append(verdict[6:])
        if deviations:
            from ravel.validation.validate_run_state import edit_guard
            if edit_guard(str(path)):
                errors.append('approved input edit requires a deviation record or amendment and reapproval: ' + str(path))
    return errors


def check(data, host, project, *, phase='pre', rundir=None):
    """All adapters share these admission decisions, including explicit gate calls."""
    from ravel.workflow import execution_guard, host_gate
    event = normalize(data, host)
    name = event.get('tool_name')
    if phase == 'post' and name.startswith('mcp__'):
        from ravel.workflow import site_tools
        site_tools.observe(event, project=project, rundir=rundir)
        return []
    if phase == 'post':
        return write_errors(event, project, deviations=True) if name in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'apply_patch') else []
    if phase == 'prompt':
        # Route prompts through the existing host-neutral owner; no prompt text is executed.
        route(event, project, host)
        return []
    if name in ('Skill', 'Agent', 'Task'):
        return skill_errors(event, project)
    if name in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'apply_patch'):
        return write_errors(event, project)
    if name == 'Bash':
        from ravel.workflow import native_shims
        command = event['tool_input'].get('command', '')
        for segment in host_gate._segments(command):
            argv = host_gate._argv(segment)
            if argv and Path(argv[0]).name in native_shims.executables():
                errors = native_shims.admit(project, command, rundir=rundir,
                                            cwd=event.get('cwd'), session=event.get('session_id'))
                if errors:
                    return errors
        allowed, reason = execution_guard.hook(json.dumps(event), project)
        if not allowed:
            return [reason]
        result = host_gate.verdict(rundir, 'tool_call', event['tool_input'].get('command', ''),
                                   session_id=event.get('session_id'), cwd=event.get('cwd'), project=project)
        return [row['message'] for row in result['errors']]
    if name.startswith('mcp__'):
        from ravel.workflow import site_tools
        return site_tools.check(event, project=project, rundir=rundir)['errors']
    return []




def skill_errors(data, project):
    """Contract-before-skill and route-before-fanout policy, shared with Claude."""
    from ravel.workflow import active_run
    ti = data.get('tool_input') or {}
    tool = (data.get('tool_name') or '').strip()
    skill = (ti.get('skill') or ti.get('name') or '').strip()
    session = (data.get('session_id') or '').strip()
    cwd = (data.get('cwd') or '').strip()
    def have_contract():
        try:
            rd = active_run.resolve(session, cwd, project)
            return rd is not None and any((Path(rd) / name).is_file() for name in ('task_contract.json', 'inputs/task_contract.json'))
        except Exception:
            return False
    if tool in ('Agent', 'Task'):
        marker = Path(project) / 'logs' / ('.route-pending-' + session)
        if not session or not marker.is_file():
            return []
        if have_contract():
            marker.unlink(missing_ok=True)
            return []
        return ["BLOCKED (routing gate): this session's physics request has not been routed yet (no task_contract.json). Invoke the physicist-intake skill FIRST -- it produces the contract + CHECK-IN 1; subagent fan-out (the pre-routing survey failure) unblocks the moment the contract exists."]
    if tool and tool != 'Skill':
        return []
    if skill in ('new-analysis', 'run-scan', 'run-stage', 'certify', 'route-analysis', 'verification-panel') and not have_contract():
        return [f"BLOCKED (G22/N1): the '{skill}' skill presupposes an approved task_contract.json for THIS run, but the active run has none yet. Invoke the physicist-intake skill FIRST -- it routes the request, runs the no-generation survey, and composes CHECK-IN 1 (docs/workflow/start.md)."]
    return []


def skill_main(project):
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    errors = skill_errors(data, project)
    for error in errors:
        print(error, file=sys.stderr)
    return 2 if errors else 0

def route(data, project, host):
    from ravel.workflow import active_run, host_governance, route_prompt, workflow_state
    prompt = data.get('prompt') or data.get('user_prompt') or ''
    if not prompt or host_governance.development_prompt(prompt) or host_governance.conversational_reply(prompt):
        return
    try:
        contract = route_prompt.route(prompt)
    except ValueError as refused:
        # An overfull output census (more than 32 declared paths, or a full census) refuses at
        # `ravel initiate`; the hook binds no workspace and records no census, so the routing
        # reminder is derived without the output rows. A refusal that remains without them is
        # raised unchanged.
        try:
            contract = route_prompt.route_records(prompt, output_census=False)[0]
        except ValueError:
            raise refused from None
    errors = route_prompt.validate(contract)
    if errors:
        raise ValueError('the router produced an invalid contract: ' + '; '.join(errors))
    mode = contract.get('task_mode')
    if not mode:
        return
    session = data.get('session_id') or ''
    rd = active_run.resolve(session, data.get('cwd') or '', project)
    if rd is not None:
        import argparse
        import contextlib
        import io
        # Best effort, as before: the reminder JSON stays the only stdout payload.
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                workflow_state.cmd_record(argparse.Namespace(rundir=str(rd), project_dir=None, kind='route',
                                                             what=mode, payload=None, stage=None, session_id=session))
        except Exception:
            pass
    if session and mode != 'unsupported' and contract.get('compute_plan') not in (None, 'none'):
        logs = Path(project) / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        (logs / ('.route-pending-' + session)).touch()
    reminder = 'ROUTING (G1): this is a physics request (task_mode=$tmode). Per docs/workflow/start.md, FIRST invoke the physicist-intake skill (it runs route_prompt.py -> a validated task_contract.json, the no-generation survey, cost_preflight, the run scaffold, then CHECK-IN 1). NO heavy compute before the CHECK-IN 1 go-ahead. Do NOT invoke new-analysis/run-scan/run-stage/certify before task_contract.json exists.'.replace('$tmode', mode)
    event = 'BeforeAgent' if host == 'gemini' else 'UserPromptSubmit'
    print(json.dumps({'hookSpecificOutput': {'hookEventName': event, 'additionalContext': reminder}}))

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=('claude', 'codex', 'gemini', 'opencode', 'antigravity'), required=True)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--phase', choices=('pre', 'post', 'prompt'), default='pre')
    parser.add_argument('--rundir', type=Path)
    args = parser.parse_args(argv)
    try:
        errors = check(json.load(sys.stdin), args.host, args.project, phase=args.phase, rundir=args.rundir)
    except Exception as exc:
        # Exit 3: the guard could not decide. Generated hooks block on it and label the session.
        print('BLOCKED: RAVEL guard unavailable or invalid event: ' + str(exc), file=sys.stderr)
        return 3
    if args.phase == 'prompt':
        from ravel.workflow import host_governance
        host_governance.observe_host(args.project, source='prompt-hook')
    if errors:
        print('BLOCKED: ' + '; '.join(errors), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
