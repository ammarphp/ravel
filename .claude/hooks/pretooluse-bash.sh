#!/usr/bin/env bash
# PreToolUse-on-Bash guard (R3/H1): block a GENERATION launch BEFORE it executes unless the forced
# chain holds -- (1) not detached (nohup/setsid, N6 pre-exec), (2) not pre-intake (route-pending
# marker with no contract), (3) the CHECK-IN 1 approval artifact exists for smoke|full|scan,
# (4) the generation recipe exists (D7, pre-exec), (5) the command is SUPERVISED
# (run_stage|stage_supervisor|run-pipeline-native.sh). Dev sessions (no session-scoped run, no
# marker) are never touched. Exit 2 blocks. NOTE: the tool-call JSON travels via SPINE_HOOK_INPUT
# (a heredoc would swallow piped stdin -- the CLAUDE.md conda-heredoc gotcha applies to hooks too).
set -u
SPINE_HOOK_INPUT="$(cat)"
export SPINE_HOOK_INPUT
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
verdict="$(python3 -c "
import importlib.util, json, os, re, sys, glob
try:
    d = json.loads(os.environ.get('SPINE_HOOK_INPUT') or '{}')
except Exception:
    print('allow'); raise SystemExit
if (d.get('tool_name') or '') != 'Bash':
    print('allow'); raise SystemExit
cmd = ((d.get('tool_input') or {}).get('command') or '')
repo = sys.argv[1]
gen = None
try:
    spec = importlib.util.spec_from_file_location(
        'rc_guard', os.path.join(repo, 'trial-runs', '_infrastructure', 'resource_census.py'))
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    gen = bool(rc.GEN_LAUNCH_RE.search(cmd))
except Exception:
    rc = None
if gen is None:
    gen = bool(re.search(r'generate_events|mg5_aMC|\bmg5\b|pythia_shower|run-pipeline-native\.sh|\.cmnd\b|madevent', cmd))
if not gen:
    print('allow'); raise SystemExit
if re.search(r'\bnohup\b|\bsetsid\b|start_new_session', cmd):
    print('block:DETACHED generation launch -- nohup/setsid silently defeats the completion '
          'notification (N6). Use the harness run_in_background with stage_supervisor/run_stage.')
    raise SystemExit
session = d.get('session_id') or ''
cwd = d.get('cwd') or ''
tr = os.path.join(repo, 'trial-runs')
rd = None
if cwd:
    c = os.path.abspath(cwd)
    if c == tr or c.startswith(tr + os.sep):
        rest = os.path.relpath(c, tr).split(os.sep)
        if rest and rest[0] not in ('.', '..'):
            rd = os.path.join(tr, rest[0])
if rd is None and session:
    for p in glob.glob(os.path.join(tr, '*', 'run_state.json')):
        try:
            if json.load(open(p)).get('session_id') == session:
                rd = os.path.dirname(p); break
        except Exception:
            pass
marker = os.path.join(repo, 'logs', '.route-pending-' + session) if session else ''
if rd is None:
    if marker and os.path.isfile(marker):
        print('block:generation BEFORE intake -- this session has no run/contract yet. '
              'Fire physicist-intake first (workflow/INITIATE.md).')
    else:
        print('allow')
    raise SystemExit
contract = None
for x in ('inputs/task_contract.json', 'task_contract.json'):
    fp = os.path.join(rd, x)
    if os.path.isfile(fp):
        try:
            contract = json.load(open(fp))
        except Exception:
            contract = None
        break
plan = (contract or {}).get('compute_plan') or ''
if plan in ('smoke', 'full', 'scan') and not os.path.isfile(
        os.path.join(rd, 'inputs', 'checkin1_approval.json')):
    print('block:UNAPPROVED ' + plan + ' generation -- record the go-ahead first: '
          'python3 trial-runs/_infrastructure/workflow_state.py approve --rundir '
          + os.path.relpath(rd, repo) + ' --quote \"<the physicist reply>\" '
          '(requires a valid checkin1.json + cost_preflight.json).')
    raise SystemExit
rcode = 0
if rc is not None:
    try:
        rcode = rc.assert_pre_generate(rd)[0]
    except Exception:
        rcode = 0
if rcode != 0:
    print('block:NO generation recipe recorded for the declared model (D7) -- fetch/record it '
          '(resource_census.py --debug recipe-search -> inputs/generation_recipe.json) BEFORE '
          'generating; recipe-after-generation is how the trial hung.')
    raise SystemExit
if not re.search(r'run_stage|stage_supervisor|run-pipeline-native\.sh', cmd):
    print('block:UNSUPERVISED generation launch -- wrap it (stage_supervisor.py / run_stage / '
          'run-pipeline-native.sh) so a hang converts to a completion (the trial hung silent, D6).')
    raise SystemExit
print('allow')
" "$REPO")"
case "$verdict" in
  allow) exit 0 ;;
  block:*)
    echo "BLOCKED (R3/H1 pre-exec compute gate): ${verdict#block:}" >&2
    exit 2 ;;
  *) exit 0 ;;
esac
