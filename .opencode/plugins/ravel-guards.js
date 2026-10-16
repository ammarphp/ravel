// Generated from RAVEL's role registry; do not hand edit.
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
