"""Mandatory composition suite: the legacy agent-graph tests, the worker substrate tests and
the worker adversarial tests run against the merged kernel. A skip is a failure; the only
admitted skips are the real-sandbox one on a host with no OS sandbox launcher and, under a
launcher other than the macOS one, the tests that name a property only the macOS profile has."""
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PAIR = ('test_agent_graph.py', 'test_worker_substrate.py')
SANDBOXED = ('test_agent_worker.py', 'test_worker_broker.py', 'test_worker_sandbox.py')
# The adversarial boundaries the merge depends on; deleting one fails this suite.
REQUIRED = {
    'test_worker_substrate.py': (
        'test_exception_after_a_possible_commit_is_ambiguous_and_never_redispatched',
        'test_typed_not_dispatched_failure_closes_its_effect_and_retries_on_new_attempt',
        'test_failed_reconciliation_cannot_close_a_ledger_completed_effect',
        'test_never_dispatched_reservation_recovers_on_a_single_attempt_node',
        'test_blind_worker_nodes_require_a_packet_matching_role_card_and_no_raw_inputs',
        'test_blind_worker_dispatch_materializes_only_the_packet_and_protects_the_graph_root',
        'test_worker_receipt_carries_effect_identity_and_closes_a_crashed_effect_through_its_validator',
        'test_legacy_execution_holds_the_scope_runner_and_honours_stop'),
    'test_worker_broker.py': (
        'test_directory_swapped_after_policy_check_cannot_redirect_the_broker',
        'test_repeat_snapshot_walks_by_descriptor_and_never_follows_links',
        'test_crash_between_custody_append_and_state_pin_adopts_the_receipt',
        'test_crash_after_broker_reservation_cannot_repeat_effect'),
    'test_agent_worker.py': (
        'test_real_sandbox_blind_worker_cannot_read_producer_output_or_graph_custody',
        'test_blind_worker_workspace_holds_only_its_role_packet',
        'test_interrupted_publication_is_repaired_before_a_receipt_is_returned',
        'test_read_roots_outside_the_tool_runtime_are_refused_for_every_role',
        'test_kernel_stop_now_terminates_sandboxed_child_and_leaves_receipt'),
    'test_worker_sandbox.py': ('test_metadata_is_scoped_to_ancestors_and_readable_roots',),
}


def _run(tmp_path, names, label):
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    done = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', '-rs', '-p', 'no:cacheprovider',
                           '--basetemp', str(tmp_path / label), *(str(HERE / name) for name in names)],
                          cwd=HERE.parents[1], env=env, capture_output=True, text=True, timeout=900)
    summary = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else done.stderr
    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]
    return done.stdout, summary


def test_legacy_graph_and_worker_substrate_pass_together_without_skips(tmp_path):
    from ravel.workflow import effect_ledger, graph_substrate  # noqa: F401  (the kernel is required)
    _, summary = _run(tmp_path, PAIR, 'pair')
    assert not re.search(r'\b(skipped|xfailed|xpassed|deselected|error)', summary), summary
    passed = int(re.search(r'(\d+) passed', summary).group(1))
    assert passed >= 44, summary


def test_worker_adversarial_suite_passes_and_skips_only_without_a_sandbox(tmp_path):
    from ravel.workflow import sandbox
    output, summary = _run(tmp_path, SANDBOXED, 'sandboxed')
    assert not re.search(r'\b(xfailed|xpassed|deselected|error)', summary), summary
    if sandbox.available() == 'macos':
        assert 'skipped' not in summary, summary
    elif sandbox.available() is not None:
        # The login keychain exists on macOS only, and port filtering elsewhere needs kernel port rules.
        reasons = [line for line in output.splitlines() if line.startswith('SKIPPED')]
        admitted = re.compile(r'^SKIPPED \[1\] tests/unit/test_worker_sandbox\.py:\d+: '
                              r'(the keychain home|port filtering) is a macOS sandbox profile property\b')
        assert all(admitted.match(line) for line in reasons), reasons
        declared = (HERE / 'test_worker_sandbox.py').read_text().count('is a macOS sandbox profile property')
        assert len(reasons) <= declared, reasons
        counted = re.search(r'(\d+) skipped', summary)
        assert (int(counted.group(1)) if counted else 0) == len(reasons), summary
    else:
        reasons = [line for line in output.splitlines() if line.startswith('SKIPPED')]
        assert all('sandbox-blocked' in line for line in reasons), reasons


def test_pair_files_do_not_skip_on_a_missing_kernel():
    for name in PAIR:
        source = (HERE / name).read_text()
        assert 'importorskip' not in source and 'pytest.skip' not in source


def test_required_adversarial_boundaries_are_present():
    for name, tests in REQUIRED.items():
        source = (HERE / name).read_text()
        missing = [test for test in tests if f'def {test}(' not in source]
        assert not missing, (name, missing)
