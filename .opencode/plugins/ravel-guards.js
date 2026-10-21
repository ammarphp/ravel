// Generated from RAVEL's role registry; do not hand edit.
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
            utc: new Date().toISOString().slice(0, 19) + 'Z' }) + '\n');
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
