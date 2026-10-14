"""authority-bearing sources, paraphrased suppression, symlinks, installed seals and the CI scan."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.validation import check_protected_paths as pp

ROOT = Path(__file__).resolve().parents[2]


# --- F-11: every authority-bearing source and switch is protected ---

@pytest.mark.parametrize('path', [
    'src/ravel/data/gates/providers.json',
    'src/ravel/workflow/decision_gate.py',
    'src/ravel/workflow/review_points.py',
    'src/ravel/workflow/decision_case.py',
    'src/ravel/workflow/run_ceilings.py',
    'src/ravel/workflow/raw_launch.py',
    'src/ravel/workflow/evidence_queue.py',
    'src/ravel/workflow/scientific_judgment.py',
    'src/ravel/workflow/knowledge_lessons.py',
    'src/ravel/workflow/workflow_state.py',
    'src/ravel/workflow/launch_authorization.py',
    'src/ravel/workflow/transport_receipt.py',
    'src/ravel/workflow/agent_graph.py',
    'src/ravel/workflow/execution.py',
    'src/ravel/workflow/machine_lease.py',
    'src/ravel/workflow/rdj_custody.py',
    'src/ravel/workflow/work_dispatch.py',
    'src/ravel/workflow/comparison.py',
    'src/ravel/workflow/research_protocol.py',
    'CLAUDE.md',
    'AGENTS.md',
    '.claude/skills/certify/SKILL.md',
    '.claude/rules/statistics.md',
    '.claude/agents/physics-reviewer.md',
    '.agents/skills/certify/SKILL.md',
    '.codex/config.toml',
    'pyproject.toml',
    'docs/workflow/checklists/check-ins.md',
    'tests/unit/test_anything.py',
])
def test_authority_bearing_sources_are_protected(path):
    assert pp.is_protected(path), path


@pytest.mark.parametrize('pointer', [
    '/providers/3/active', '/required_providers/launch', '/required_providers', '/attestation_min'])
def test_provider_switches_are_protected_fields(pointer):
    assert pp.field_is_protected(pointer), pointer


def test_rca_fix_flipping_a_provider_active_flag_is_refused():
    by_path = pp.fix_errors({'kind': 'rca-fix', 'edits': [
        {'path': 'src/ravel/data/gates/providers.json', 'pointer': '/providers/3/active', 'value': False}]})
    assert any('protected path' in e for e in by_path) and any('protected field' in e for e in by_path)
    # The same switch in a copied registry under a run directory is still refused by field.
    copied = pp.fix_errors({'kind': 'rca-fix', 'edits': [
        {'path': 'outputs/providers.json', 'pointer': '/providers/0/active', 'value': False}]})
    assert any('providers.active' in e for e in copied)
    assert pp.fix_errors({'kind': 'lesson', 'required_fix': 'Edit providers.json: set active to false for the comparison provider.'})


def test_replacing_an_ancestor_of_a_protected_field_is_refused():
    assert pp.fix_errors({'edits': [{'path': 'inputs/contract.json', 'pointer': '/review',
                                     'value': {'thresholds': {'closure_pull_max': 10}}}]})
    assert pp.fix_errors({'edits': [{'path': 'inputs/contract.json', 'pointer': '', 'value': {}}]})
    assert pp.fix_errors({'edits': [{'path': 'inputs/contract.json', 'pointer': '/notes',
                                     'value': {'x': {'must_check': []}}}]})
    assert pp.fix_errors({'edits': [{'path': 'inputs/contract.json', 'pointer': '/notes', 'value': 'shorter'}]}) == []


def test_every_required_entry_still_matches_a_file():
    assert pp.manifest_errors() == []


# --- F-10: paraphrased weakening is refused; descriptive and strengthening sentences pass ---

@pytest.mark.parametrize('text', [
    'Remove gate:correction from the required providers for replay runs.',
    'Patch check:closure to return no findings when the sample is a replay.',
    'Stub RP4:C1 with an empty receipt.',
    'Drop RP16:N1 from the derived points.',
    'Set review.thresholds.closure_pull_max to 10 for wide bins.',
    'Mark check:closure as not applicable.',
    'check:normalization_ledger can be left out for replays.',
    'Rewrite trap:ml-label-leakage so that it only fires above 50% leakage.',
    'gate:correction: pass it when the fix touches only cards.',
    'Edit providers.json: set active to false for the comparison provider.',
    'Use --no-lint for every figure.',
    'Omit check:closure.',
    'check:closure is too strict. Disable it.',
    'check:closure is optional for replays.',
    'Hardcode the result of check:closure.',
    'Delete gate:delivery for small grids.',
    'check:closure no longer needs to run on replays.',
    'Force check:closure to pass.',
    'Exclude premise:p3 from the replay plan.',
    'Mock rp:approval in replay runs.',
])
def test_paraphrased_weakening_is_refused(text):
    assert pp.suppression_rule(text), text


@pytest.mark.parametrize('text', [
    'Never skip check:closure.',
    "Don't disable gate:correction when the sample is a replay.",
    'check:closure fails when the per-bin pull exceeds the declared limit.',
    'check:normalization_ledger requires the generated and inclusive rates.',
    'Run check:closure after every merge.',
    'Re-run the lookup for the pinned version; do not copy a value between versions.',
    'Remove the stale cache directory before re-running.',
    'Set the generator seed to 7 and re-run.',
])
def test_descriptive_and_strengthening_sentences_pass(text):
    assert pp.suppression_rule(text) == [], text


def test_lesson_writer_forwards_known_check_ids():
    from ravel.workflow.knowledge_lessons import lesson_errors
    row = {
        'id': 'lesson:synthetic',
        'trigger': {'all': [{'fact': 'failure_class', 'equals': 'stale-lookup'}]},
        'body': 'Skip normalization_ledger when replaying.',
        'evidence': {'ticket': {'id': 't1', 'facts': {'failure_class': 'stale-lookup'}},
                     'receipts': [{'path': 'r.json', 'sha256': '0' * 64}]},
        'confirming_check': 'normalization_ledger',
        'scope': {'tool': 'a', 'tool_version': '1', 'ravel_version': '0.1'},
        'status': 'candidate',
    }
    assert any('do-not-learn' in e for e in lesson_errors(row, check_ids={'normalization_ledger'}))


# --- F-12: relative spellings and symlinks are resolved against the root ---

def test_relative_symlink_to_a_protected_source_is_protected(tmp_path):
    run = tmp_path / 'run'
    (run / 'outputs').mkdir(parents=True)
    (run / 'outputs/alias.py').symlink_to(ROOT / 'src/ravel/workflow/rdj_loop.py')
    (run / 'outputs/ok.py').write_text('x = 1\n')
    assert pp.is_protected('outputs/alias.py', root=run)
    assert not pp.is_protected('outputs/ok.py', root=run)
    receipt = {'kind': 'agent-worker-receipt', 'outputs': [{'path': 'outputs/alias.py'}]}
    assert pp.artefact_errors(receipt, root=run)


def test_relative_symlinked_directory_is_resolved(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    (run / 'gates').symlink_to(ROOT / 'src/ravel/data/governance')
    assert pp.is_protected('gates/protected_paths.json', root=run)


# --- F-13: the seal covers an installed package and refuses an empty snapshot ---

def installed_copy(tmp_path):
    site = tmp_path / 'lib/python3.12/site-packages'
    (site / 'ravel/validation').mkdir(parents=True)
    (site / 'ravel/validation/gate.py').write_text('LIMIT = 3.0\n')
    (site / 'ravel/workflow').mkdir()
    (site / 'ravel/workflow/rdj_loop.py').write_text('X = 1\n')
    (site / 'ravel/workflow/intake.py').write_text('Y = 1\n')
    return site


def test_installed_package_snapshot_hashes_the_package_files(tmp_path):
    site = installed_copy(tmp_path)
    snap = pp.evaluator_snapshot(site)
    assert snap['layout'] == 'installed'
    assert set(snap['files']) == {'src/ravel/validation/gate.py', 'src/ravel/workflow/rdj_loop.py'}
    before = snap
    (site / 'ravel/validation/gate.py').write_text('LIMIT = 30.0\n')
    sealed = pp.seal_worker_receipt({'kind': 'agent-worker-receipt'}, before, pp.evaluator_snapshot(site))
    assert sealed['void']['changed'] == ['src/ravel/validation/gate.py']


def test_source_snapshot_is_labelled(tmp_path):
    (tmp_path / 'src/ravel/validation').mkdir(parents=True)
    (tmp_path / 'src/ravel/validation/gate.py').write_text('LIMIT = 3.0\n')
    assert pp.evaluator_snapshot(tmp_path)['layout'] == 'source'
    assert pp.evaluator_snapshot()['layout'] == 'source'


def test_no_protected_file_refuses_to_snapshot_or_seal(tmp_path):
    with pytest.raises(ValueError):
        pp.evaluator_snapshot(tmp_path)
    empty = {'digest': 'd', 'files': {}}
    with pytest.raises(ValueError):
        pp.seal_worker_receipt({'kind': 'agent-worker-receipt'}, empty, empty)


def test_malformed_seal_is_void():
    assert pp.receipt_void_reason({'evaluator': {'before': 'x', 'after': 'x'}}) == 'evaluator_seal_malformed'
    assert pp.receipt_void_reason({'evaluator': {'before': 'a' * 64, 'after': 'a' * 64}}) is None


# --- F-14: RCA text on any record kind, and the CI scan over the repository ---

def test_rca_text_on_any_record_kind_is_scanned():
    record = {'kind': 'broker-receipt', 'required_fix': 'Skip check:closure for replays.'}
    assert pp.artefact_errors(record)


def test_ci_workflow_runs_the_protected_path_scan():
    ci = (ROOT / '.github/workflows/ci.yml').read_text()
    assert 'ravel.validation.check_protected_paths --check-manifest' in ci


def test_protected_path_scan_over_the_repository_is_clean(tmp_path):
    roots = [d for d in ('evidence', 'trial-runs', 'src/ravel/data/knowledge/lessons') if (ROOT / d).exists()]
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    proc = subprocess.run([sys.executable, '-m', 'ravel.validation.check_protected_paths', '--check-manifest',
                           '--json', '--root', str(ROOT), *roots], capture_output=True, text=True, env=env, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)['ok'] is True


def test_consumer_wiring_is_recorded_as_handoffs():
    handoffs = pp.load_manifest().get('handoffs') or []
    assert {'broker', 'knowledge-lessons', 'root-cause-analysis'} <= {h['to'] for h in handoffs}
    assert all(h.get('wiring') and h.get('until_wired') for h in handoffs)
