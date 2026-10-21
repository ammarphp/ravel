"""P06: the physicist's answer is read at the controller's own controlling terminal (CT07, A03).

A helper process opens a pseudo-terminal pair with ``pty.fork``: the child, whose controlling
terminal is the pseudo-terminal, runs the production ``terminal.ask``; the parent plays the
physicist on the master side. No seam replaces the terminal exchange. A process started in its
own session without standard input (as every worker and governed launch is) has no controlling
terminal and cannot be asked.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='pseudo-terminals are POSIX')

HELPER = textwrap.dedent(r'''
    import json, os, pty, re, sys, time
    mode = sys.argv[1]
    pid, master = pty.fork()
    if pid == 0:
        from ravel.controller.authority import terminal
        if mode == 'typeahead':
            time.sleep(1.0)  # let the parent's type-ahead arrive before the prompt
        try:
            offered = ['Keep', 'proceed', 'reject'] if mode == 'case' else ['approve', 'adjust', 'reject']
            result = terminal.ask('CHECK-IN 1: plan (fictional)\n', decisions=offered,
                                  timeout=3 if mode == 'timeout' else 30)
            print('RESULT ' + json.dumps(result), flush=True)
        except Exception as exc:
            print('RESULT ' + json.dumps({'error': type(exc).__name__, 'message': str(exc)}), flush=True)
        os._exit(0)
    seen = b''
    def read_until(pattern, limit=40.0):
        global seen
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            match = re.search(pattern, seen)
            if match:
                return match
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            seen += chunk
        return re.search(pattern, seen)
    if mode == 'typeahead':
        os.write(master, b'AAAA-AAAA approve typed before the prompt\n')
    codes = []
    def prompt():
        match = read_until(rb'Reply on one line: (\S+) <decision>', 40)
        code = match.group(1).decode()
        global seen
        seen = seen[match.end():]
        codes.append(code)
        return code
    if mode in ('answer', 'typeahead'):
        os.write(master, (prompt() + ' approve Looks right; keep the smoke rung.\n').encode())
    elif mode == 'retry':
        prompt()
        os.write(master, b'WRONG-CODE approve\n')
        os.write(master, (prompt() + ' sign-off\n').encode())
        os.write(master, (prompt() + ' adjust Use fewer events.\n').encode())
    elif mode == 'case':
        os.write(master, (prompt().lower() + ' KEEP as offered.\n').encode())
    elif mode == 'timeout':
        prompt()
    match = read_until(rb'RESULT (\{.*\})', 60)
    os.waitpid(pid, 0)
    print(json.dumps({'codes': codes, 'result': json.loads(match.group(1)) if match else None}))
''')


def run_helper(tmp_path, mode):
    script = tmp_path / 'tty_helper.py'
    script.write_text(HELPER)
    done = subprocess.run([sys.executable, str(script), mode], capture_output=True, text=True, timeout=120,
                          stdin=subprocess.DEVNULL, start_new_session=True, env=os.environ.copy())
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_answer_is_read_at_the_controlling_terminal_with_its_code(tmp_path):
    out = run_helper(tmp_path, 'answer')
    result = out['result']
    assert result['decision'] == 'approve' and result['attempts'] == 1
    assert result['comment'] == 'Looks right; keep the smoke rung.'
    assert len(result['prompt_sha256']) == 64 and len(result['nonce_sha256']) == 64
    assert result['device']['name'] is None or result['device']['name'].startswith('/dev/')


def test_type_ahead_before_the_prompt_is_discarded(tmp_path):
    out = run_helper(tmp_path, 'typeahead')
    assert out['result']['decision'] == 'approve' and out['result']['attempts'] == 1
    assert out['result']['comment'] == 'Looks right; keep the smoke rung.'


def test_a_wrong_code_or_unoffered_decision_is_asked_again_with_a_new_code(tmp_path):
    out = run_helper(tmp_path, 'retry')
    assert out['result']['decision'] == 'adjust' and out['result']['attempts'] == 3
    assert len(set(out['codes'])) == 3  # every prompt shows its own code


def test_codes_and_decisions_match_without_regard_to_case_and_record_the_offered_spelling(tmp_path):
    out = run_helper(tmp_path, 'case')
    assert out['result']['decision'] == 'Keep' and out['result']['attempts'] == 1
    assert out['result']['comment'] == 'as offered.'


def test_no_answer_within_the_bound_records_nothing(tmp_path):
    out = run_helper(tmp_path, 'timeout')
    assert out['result']['error'] == 'TerminalRefused'


def test_a_process_in_its_own_session_without_stdin_cannot_be_asked():
    code = ('from ravel.controller.authority import terminal\n'
            'print(terminal.available())\n'
            'try:\n'
            '    terminal.ask("x", decisions=["approve"], timeout=1)\n'
            'except terminal.TerminalUnavailable:\n'
            '    print("unavailable")\n')
    done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=60,
                          stdin=subprocess.DEVNULL, start_new_session=True, env=os.environ.copy())
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ['False', 'unavailable']
