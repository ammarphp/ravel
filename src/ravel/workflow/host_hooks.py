"""Native hook projections from the role registry's shared hook table.

Every generated hook loads the installed RAVEL. Inherited package variables are cleared; the
installer's runtime (``.ravel/hook-runtime.sh``) selects the interpreter and package path, and
the working directory is never searched for the package (``PYTHONSAFEPATH``). Without a
runtime, only a RAVEL source checkout at its own repository top level supplies ``src``: a
nested directory that merely holds settings and a package copy never does. A guard that
cannot run blocks the call, prompts included, and records a NOT GOVERNED event in the host
ledger (``host_governance.HOST_LEDGER``); a changed runtime is detected at the next RAVEL call.
"""
import json

from ravel.paths import package_data_path


def table():
    return json.loads(package_data_path('agent_surface', 'hooks.json').read_text())


def command(host, phase):
    # Bootstrap before importing RAVEL: nested projects own their local runtime.
    seed = '"${CLAUDE_PROJECT_DIR:-$PWD}"' if host == 'claude' else '"$PWD"'
    project = ('RAVEL_PROJECT_DIR="$(ravel_start=' + seed + '; '
               'ravel_dir="$ravel_start"; '
               'while :; do '
               'if [ -f "$ravel_dir/.claude/settings.json" ]; then '
               'printf \'%s\\n\' "$ravel_dir"; break; fi; '
               'if [ "$ravel_dir" = / ]; then '
               'git -C "$ravel_start" rev-parse --show-toplevel 2>/dev/null || '
               'printf \'%s\\n\' "$ravel_start"; break; fi; '
               'ravel_dir="$(dirname "$ravel_dir")"; done)"; ')
    loader = ('ravel_inherited="${RAVEL_PYTHON:-}"; '
              'unset RAVEL_PYTHON PYTHONPATH PYTHONHOME PYTHONSTARTUP; '
              'if [ -f "$RAVEL_PROJECT_DIR/.ravel/hook-runtime.sh" ]; then '
              '. "$RAVEL_PROJECT_DIR/.ravel/hook-runtime.sh"; '
              'elif [ -d "$RAVEL_PROJECT_DIR/src/ravel" ] && [ -f "$RAVEL_PROJECT_DIR/.claude/hooks/pretooluse-bash.sh" ] '
              '&& [ "$(git -C "$RAVEL_PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null)" = "$(cd "$RAVEL_PROJECT_DIR" && pwd -P)" ]; then '
              'export PYTHONPATH="$RAVEL_PROJECT_DIR/src"; fi; '
              'RAVEL_PYTHON="${RAVEL_PYTHON:-${ravel_inherited:-python3}}"; export PYTHONSAFEPATH=1; ')
    # Exit 2 is the guard's own refusal; any other failure means it could not run: both block,
    # prompts included, and only the second records a NOT GOVERNED event for the event's session.
    label = ('ravel_ledger="${RAVEL_STATE_DIR:-$HOME/.local/state/ravel}/host-integrity"; '
             'mkdir -p "$ravel_ledger" 2>/dev/null; '
             'ravel_sid="$(printf \'%s\' "$ravel_input" | tr -d \'\\n\' | sed -n '
             '\'s/.*"session_id"[[:space:]]*:[[:space:]]*"\\([A-Za-z0-9._:-]*\\)".*/\\1/p\')"; '
             'printf \'{"schema_version": 1, "kind": "hook_failure", "hook": "%s", "project": "%s", '
             '"session": "%s", "utc": "%s"}\\n\' '
             '"' + host + '-' + phase + '" "$(printf \'%s\' "$RAVEL_PROJECT_DIR" | tr -d \'\\042\\134\')" '
             '"$ravel_sid" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$ravel_ledger/events.jsonl" 2>/dev/null; ')
    what = 'prompt routing' if phase == 'prompt' else 'host guard'
    return (project + loader + 'ravel_input="$(cat)"; '
            'printf \'%s\' "$ravel_input" | "$RAVEL_PYTHON" -m ravel.workflow.host_guards '
            '--host ' + host + ' --phase ' + phase + ' --project "$RAVEL_PROJECT_DIR"; '
            'RAVEL_GUARD_STATUS=$?; [ "$RAVEL_GUARD_STATUS" -eq 0 ] && exit 0; '
            'if [ "$RAVEL_GUARD_STATUS" -ne 2 ]; then ' + label +
            'echo "BLOCKED: RAVEL ' + what + ' is unavailable; this session is labelled NOT GOVERNED" >&2; exit 2; fi; '
            'echo "BLOCKED: RAVEL ' + what + ' refused" >&2; exit 2')

def render(host):
    adapter = table()['adapters'].get(host)
    if adapter is None:
        return {}
    if host == 'opencode':
        # node:child_process is built into the host runtime, no npm dependency.
        body = '''// Generated from RAVEL's role registry; do not hand edit.
import { execFileSync } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
export const RavelGuards = async ({ directory }) => {
  let project = resolve(directory);
  while (!existsSync(join(project, '.claude/settings.json'))) {
    const parent = dirname(project);
    if (parent === project) {
      try { project = execFileSync('git', ['rev-parse', '--show-toplevel'],
        { cwd: directory, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim(); }
      catch { project = resolve(directory); }
      break;
    }
    project = parent;
  }
  let runtime = {};
  try { runtime = JSON.parse(readFileSync(join(project, '.ravel/agent-surface.local.json'), 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  // Only the installer's runtime selects the guard's package path; the working directory is never searched.
  const python = runtime.python || process.env.RAVEL_PYTHON || 'python3';
  const check = (phase, input, args) => {
    const env = { ...process.env, PYTHONSAFEPATH: '1' };
    for (const name of ['RAVEL_PYTHON', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP']) delete env[name];
    if (runtime.pythonpath) env.PYTHONPATH = runtime.pythonpath;
    try {
      execFileSync(python,
        ['-m', 'ravel.workflow.host_guards', '--host', 'opencode', '--project', project, '--phase', phase],
        { input: JSON.stringify({tool_name: input.tool, tool_input: args,
            session_id: input.sessionID, cwd: directory}), env, stdio: ['pipe', 'pipe', 'pipe'] });
    } catch (error) {
      if (error.status !== 2) {
        // The guard could not run: the call stays blocked and the session is labelled NOT GOVERNED.
        try {
          const ledger = join(process.env.RAVEL_STATE_DIR || join(homedir(), '.local/state/ravel'), 'host-integrity');
          mkdirSync(ledger, { recursive: true, mode: 0o700 });
          appendFileSync(join(ledger, 'events.jsonl'), JSON.stringify({ schema_version: 1, kind: 'hook_failure',
            hook: 'opencode-' + phase, project, session: input.sessionID || '',
            utc: new Date().toISOString().slice(0, 19) + 'Z' }) + '\\n');
        } catch { /* detection never unblocks the call */ }
      }
      throw error;
    }
  };
  return {
    'tool.execute.before': async (input, output) => check('pre', input, output.args),
    'tool.execute.after': async (input) => check('post', input, input.args),
  };
};
'''
    else:
        hooks = {}
        for phase in ('pre', 'post', 'prompt'):
            event = adapter[phase]
            hooks[event] = [{'hooks': [{'type': 'command', 'command': command(host, phase)}]}]
        body = json.dumps({'hooks': hooks}, indent=2) + '\n'
    return {adapter['path']: body}


def enforcement_levels():
    caps = json.loads(package_data_path('agent_surface', 'host_capabilities.json').read_text())
    return {name: row.get('enforcement', {}) for name, row in caps['surfaces'].items()}
