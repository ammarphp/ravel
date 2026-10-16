"""Native hook projections from the role registry's shared hook table."""
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
    # Prompt routing is advisory on every host: a routing failure warns and never blocks the prompt.
    failure = ('echo "RAVEL hook unavailable: prompt routing failed" >&2; exit 0' if phase == 'prompt'
               else 'echo "BLOCKED: RAVEL host guard refused or is unavailable" >&2; exit 2')
    return (project +
            'if [ -f "$RAVEL_PROJECT_DIR/.ravel/hook-runtime.sh" ]; then '
            '. "$RAVEL_PROJECT_DIR/.ravel/hook-runtime.sh"; fi; '
            'if [ -d "$RAVEL_PROJECT_DIR/src/ravel" ]; then '
            'export PYTHONPATH="$RAVEL_PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"; fi; '
            '"${RAVEL_PYTHON:-python3}" -m ravel.workflow.host_guards '
            '--host ' + host + ' --phase ' + phase + ' --project "$RAVEL_PROJECT_DIR"; '
            'RAVEL_GUARD_STATUS=$?; [ "$RAVEL_GUARD_STATUS" -eq 0 ] && exit 0; '
            + failure)


def render(host):
    adapter = table()['adapters'].get(host)
    if adapter is None:
        return {}
    if host == 'opencode':
        # node:child_process is built into the host runtime, no npm dependency.
        body = '''// Generated from RAVEL's role registry; do not hand edit.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
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
  const check = (phase, input, args) => {
    const env = { ...process.env };
    if (runtime.pythonpath) env.PYTHONPATH = runtime.pythonpath + (env.PYTHONPATH ? ':' + env.PYTHONPATH : '');
    execFileSync(env.RAVEL_PYTHON || runtime.python || 'python3',
      ['-m', 'ravel.workflow.host_guards', '--host', 'opencode', '--project', project, '--phase', phase],
      { input: JSON.stringify({tool_name: input.tool, tool_input: args,
          session_id: input.sessionID, cwd: directory}), env, stdio: ['pipe', 'pipe', 'pipe'] });
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
