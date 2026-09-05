#!/usr/bin/env bash
# PreToolUse-on-Bash guard (R3/H1): block a GENERATION launch BEFORE it executes unless the forced
# chain holds -- (1) not detached (nohup/setsid, N6 pre-exec), (2) not pre-intake (route-pending
# marker with no contract), (3) a v2 CHECK-IN 1 approval still binds the current input bytes,
# (4) the generation recipe exists (D7, pre-exec), (5) the command is SUPERVISED
# (run_stage|stage_supervisor|run-pipeline-native.sh). Dev sessions (no session-scoped run, no
# marker) are never touched. Exit 2 blocks. NOTE: the tool-call JSON travels via SPINE_HOOK_INPUT
# (a heredoc would swallow piped stdin -- the CLAUDE.md conda-heredoc gotcha applies to hooks too).
set -u
SPINE_HOOK_INPUT="$(cat)"
export SPINE_HOOK_INPUT
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
verdict="$(python3 -c "
import importlib.util, json, os, re, sys, glob, shlex
try:
    d = json.loads(os.environ.get('SPINE_HOOK_INPUT') or '{}')
except Exception:
    print('allow'); raise SystemExit
if (d.get('tool_name') or '') != 'Bash':
    print('allow'); raise SystemExit
cmd = ((d.get('tool_input') or {}).get('command') or '')
repo = sys.argv[1]
# Recognize the two documented bulk drivers independently of the historical point-level
# regex. This is deliberately scoped command recognition, not a general shell parser.
explicit_scan = False
try:
    segments = []
    # Separate physical commands before shlex removes comments and their final newline.
    # Otherwise '# note\necho --help' could suppress recognition of the prior launch.
    for line in cmd.replace(chr(92) + chr(10), '').splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=';&|')
        lexer.whitespace_split = True
        segments.append([])
        for token in lexer:
            if token and all(ch in ';&|' for ch in token):
                segments.append([])
            else:
                segments[-1].append(token)
    for segment in segments:
        for i, token in enumerate(segment):
            driver = os.path.basename(token)
            if driver not in ('scan_orchestrator.py', 'scan_babysitter.py'):
                continue
            prefix, args = segment[:i], segment[i + 1:]
            # Match executable scripts or normal Python invocations, including conda run.
            if prefix and (os.path.basename(prefix[0]) in ('echo', 'printf', 'cat', 'grep', 'rg')
                           or '-c' in prefix or '-m' in prefix
                           or not any(re.fullmatch(r'python(?:[0-9]+(?:[.][0-9]+)*)?', os.path.basename(t)) for t in prefix)):
                continue
            if '--help' in args or '-h' in args:
                continue
            if driver == 'scan_orchestrator.py' and args[:1] == ['launch'] and '--go' in args:
                explicit_scan = True
            if driver == 'scan_babysitter.py' and args:
                explicit_scan = True
except ValueError:
    pass  # malformed shell syntax cannot execute; the existing generation check still runs
gen = None
try:
    spec = importlib.util.spec_from_file_location(
        'rc_guard', os.path.join(repo, 'src', 'ravel', 'workflow', 'resource_census.py'))
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    gen = bool(rc.GEN_LAUNCH_RE.search(cmd))
except Exception:
    rc = None
if gen is None:
    gen = bool(re.search(r'generate_events|mg5_aMC|\bmg5\b|pythia_shower|run-pipeline-native\.sh|\.cmnd\b|madevent', cmd))
gen = gen or explicit_scan
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
              'Fire physicist-intake first (docs/workflow/start.md).')
    else:
        print('allow')
    raise SystemExit
contract = None
try:
    contract_spec = importlib.util.spec_from_file_location(
        'task_contract_guard', os.path.join(repo, 'src', 'ravel', 'validation', 'validate_task_contract.py'))
    contract_validator = importlib.util.module_from_spec(contract_spec)
    contract_spec.loader.exec_module(contract_validator)
except Exception as e:
    print('block:task-contract validator is unavailable: ' + str(e))
    raise SystemExit
for x in ('inputs/task_contract.json', 'task_contract.json'):
    fp = os.path.join(rd, x)
    if os.path.isfile(fp):
        try:
            contract = contract_validator.load_contract(fp)
        except Exception as e:
            print('block:invalid task_contract.json: ' + str(e))
            raise SystemExit
        break
contract_errors = contract_validator.validate(contract)
if contract_errors:
    print('block:invalid task_contract.json: ' + '; '.join(contract_errors))
    raise SystemExit
plan = contract['compute_plan']
if plan not in ('smoke', 'full', 'scan'):
    print('block:generation is outside task_contract compute_plan=' + plan)
    raise SystemExit
if plan in ('smoke', 'full', 'scan') and not os.path.isfile(
        os.path.join(rd, 'inputs', 'checkin1_approval.json')):
    print('block:UNAPPROVED ' + plan + ' generation -- record the go-ahead first: '
          'python3 src/ravel/workflow/workflow_state.py approve --rundir '
          + os.path.relpath(rd, repo) + ' --quote \"<the physicist reply>\" '
          '(requires a valid checkin1.json + cost_preflight.json).')
    raise SystemExit
try:
    sys.path.insert(0, os.path.join(repo, 'src'))
    from ravel.workflow import workflow_state
    approval_errors = workflow_state.verify_approval(rd, required_plan='scan' if explicit_scan else None)
except Exception as e:
    print('block:approval verifier is unavailable or failed: ' + str(e))
    raise SystemExit
if approval_errors:
    print('block:invalid approval: ' + '; '.join(approval_errors))
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
if not explicit_scan and not re.search(r'run_stage|stage_supervisor|run-pipeline-native\.sh', cmd):
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
