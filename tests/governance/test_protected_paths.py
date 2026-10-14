"""Protected paths: manifest coverage, the do-not-learn rule, RCA fixes, evaluator seals and the CI scan.

Synthetic records only; no native execution and no network.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.validation import check_protected_paths as pp

ROOT = Path(__file__).resolve().parents[2]


def lesson(**changes):
    row = {
        'id': 'lesson:synthetic',
        'trigger': {'all': [{'fact': 'failure_class', 'equals': 'stale-lookup'}]},
        'body': 'Re-run the lookup for the pinned version.',
        'evidence': {'ticket': {'id': 'ticket-1', 'facts': {'failure_class': 'stale-lookup'}},
                     'receipts': [{'path': 'receipts/r1.json', 'sha256': '0' * 64}]},
        'confirming_check': 'check:validation.validate_run_state',
        'scope': {'tool': 'tool-a', 'tool_version': '1.2', 'ravel_version': '0.1'},
        'status': 'candidate',
        'impact': None,
    }
    row.update(changes)
    return row


# --- acceptance 1: manifest coverage ---

@pytest.mark.parametrize('path', [
    'src/ravel/validation/validate_cutflow.py',
    'src/ravel/validation/regression_triggers.py',
    'src/ravel/workflow/decision_gate.py',
    'src/ravel/workflow/rdj_loop.py',
    'src/ravel/workflow/rdj_anchor.py',
    'src/ravel/data/rdj/policy.json',
    'src/ravel/data/ml/role-cards.json',
    'src/ravel/data/review_points.json',
    'src/ravel/data/knowledge/premises.json',
    'src/ravel/workflow/premises.py',
    'src/ravel/workflow/source_policy.py',
    'src/ravel/workflow/research_protocol.py',
    'src/ravel/data/research/protocol-default.json',
    'src/ravel/physics/ml_training.py',
    'src/ravel/physics/ml_crossfit.py',
    'src/ravel/data/governance/protected_paths.json',
])
def test_manifest_protects_every_listed_source(path):
    assert pp.is_protected(path), path


@pytest.mark.parametrize('pointer, field', [
    ('/review/thresholds/closure_pull_max', 'review.thresholds'),
    ('/roles/0/must_check/2', 'must_check'),
    ('roles.1.sees.profile', 'sees'),
    ('/roles/0/sees/forbidden_inputs/0', 'forbidden_inputs'),
    ('/stages/3/review_points/0', 'review_points'),
    ('/premises/4/predicate', 'predicate'),
    ('/evaluator_pins/limit', 'evaluator_pins'),
])
def test_manifest_protects_every_listed_field(pointer, field):
    assert pp.field_is_protected(pointer) in (field, 'sees')


@pytest.mark.parametrize('path', ['outputs/analysis.py', 'scratch/check.py', 'src/ravel/workflow/intake.py',
                                  'src/ravel/data/knowledge/lessons/l1.json'])
def test_ordinary_paths_are_not_protected(path):
    assert not pp.is_protected(path)


def test_absolute_installed_and_traversing_spellings_are_resolved(tmp_path):
    assert pp.is_protected(ROOT / 'src/ravel/validation/regression_triggers.py')
    assert pp.is_protected('/opt/venv/lib/python3.12/site-packages/ravel/validation/regression_triggers.py')
    assert pp.is_protected('outputs/../src/ravel/workflow/rdj_loop.py')
    assert pp.is_protected('../../outside')
    link = tmp_path / 'alias.py'
    link.symlink_to(ROOT / 'src/ravel/workflow/rdj_loop.py')
    assert pp.is_protected(link)


def test_required_entries_match_files_and_pending_ones_name_their_producer():
    manifest = pp.load_manifest()
    assert pp.manifest_errors(manifest) == []
    ids = {e['id'] for e in manifest['entries']}
    assert {'validation', 'regression-trigger-thresholds', 'decision-gate', 'rdj', 'role-card-scope', 'review-points',
            'premise-predicates', 'source-policy', 'evaluator-pins', 'ml-evaluator'} <= ids
    assert all(e.get('required') or e.get('pending') for e in manifest['entries'])


def test_malformed_manifest_is_refused(tmp_path):
    bad = tmp_path / 'm.json'
    bad.write_text(json.dumps({'schema_version': 1, 'kind': 'protected-path-manifest',
                               'entries': [{'id': 'x', 'paths': ['/abs/**']}]}))
    with pytest.raises(ValueError):
        pp.load_manifest(bad)


# --- acceptance 2: the do-not-learn rule ---

@pytest.mark.parametrize('text', [
    'Skip check:normalization_ledger when the sample is a replay.',
    'When the backend is tool-b, bypass `trap:ml-label-leakage`.',
    'Ignore gate:correction for small grids.',
    'Treat RP13:baseline as passed once the baseline exists.',
    'Raise the threshold of check:closure for wide bins.',
])
def test_suppression_sentences_are_refused(text):
    assert pp.suppression_rule(text)


@pytest.mark.parametrize('text', [
    'check:normalization_ledger fails when the denominator omits a charge state.',
    'Skip the cache when the pinned version changes.',
    'Re-run the lookup for the pinned version; do not copy a value between versions.',
])
def test_lessons_without_a_suppression_pair_pass(text):
    assert pp.suppression_rule(text) == []


def test_known_bare_ids_are_matched_only_when_supplied():
    assert pp.suppression_rule('skip normalization_ledger when replaying') == []
    assert pp.suppression_rule('skip normalization_ledger when replaying', known_ids=['normalization_ledger'])


def test_lesson_writer_refuses_a_planted_suppression_lesson():
    from ravel.workflow.knowledge_lessons import lesson_errors
    assert lesson_errors(lesson()) == []
    errors = lesson_errors(lesson(body='Skip check:normalization_ledger when the sample is a replay.'))
    assert any('do-not-learn' in e for e in errors)


# --- acceptance 3: RCA fixes and evaluator seals ---

def test_rca_fix_editing_a_threshold_is_refused():
    assert pp.fix_errors({'kind': 'rca-fix', 'edits': [{'path': 'src/ravel/validation/regression_triggers.py'}]})
    assert any('review.thresholds' in e for e in pp.fix_errors(
        {'kind': 'rca-fix', 'edits': [{'path': 'inputs/contract.json', 'pointer': '/review/thresholds/closure_pull_max'}]}))
    assert pp.fix_errors({'required_fix': 'Lower the threshold of check:closure_pull to pass.'})
    assert pp.fix_errors({'edits': [{'path': 'inputs/run_card.dat'}], 'required_fix': 'Re-seed the generator.'}) == []


def make_root(tmp_path):
    (tmp_path / 'src/ravel/validation').mkdir(parents=True)
    (tmp_path / 'src/ravel/validation/gate.py').write_text('LIMIT = 3.0\n')
    (tmp_path / 'outputs').mkdir()
    return tmp_path


def test_evaluator_change_between_before_and_after_voids_the_receipt(tmp_path):
    root = make_root(tmp_path)
    receipt = {'schema_version': 1, 'kind': 'agent-worker-receipt', 'node_id': 'N1.author', 'attempt': 1}
    before = pp.evaluator_snapshot(root)
    assert 'src/ravel/validation/gate.py' in before['files']
    (root / 'outputs/result.json').write_text('{}')
    kept = pp.seal_worker_receipt(receipt, before, pp.evaluator_snapshot(root))
    assert pp.receipt_void_reason(kept) is None and 'void' not in kept
    (root / 'src/ravel/validation/gate.py').write_text('LIMIT = 30.0\n')
    voided = pp.seal_worker_receipt(receipt, before, pp.evaluator_snapshot(root))
    assert voided['void'] == {'code': 'evaluator_changed', 'changed': ['src/ravel/validation/gate.py']}
    assert pp.receipt_void_reason(voided) == 'evaluator_changed'
    assert pp.receipt_void_reason(receipt) == 'evaluator_unsealed'
    assert 'void' not in receipt


def test_repository_snapshot_covers_the_evaluator_files():
    files = pp.evaluator_snapshot()['files']
    assert {'src/ravel/validation/regression_triggers.py', 'src/ravel/physics/ml_training.py',
            'src/ravel/data/governance/protected_paths.json', 'src/ravel/workflow/rdj_loop.py'} <= set(files)


# --- acceptance 4: CI refusal and investigator bundles ---

def write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path


def test_ci_scan_fails_on_a_runtime_write_to_a_protected_path(tmp_path, capsys):
    clean = write(tmp_path / 'clean/calls/1.json', {'kind': 'broker-receipt', 'output_pins': [{'path': 'outputs/a.json'}]})
    assert pp.main([str(clean.parent)]) == 0
    bad = write(tmp_path / 'bad/calls/2.json', {'kind': 'broker-receipt', 'output_pins': [
        {'path': 'src/ravel/validation/regression_triggers.py', 'sha256': '0' * 64}]})
    assert pp.main([str(bad.parent)]) == 1
    assert 'writes protected path' in capsys.readouterr().out


@pytest.mark.parametrize('record', [
    {'kind': 'agent-worker-receipt', 'outputs': [{'path': 'src/ravel/workflow/rdj_loop.py'}]},
    {'kind': 'rca-fix', 'edits': [{'path': 'inputs/c.json', 'pointer': '/review/thresholds/gof_p_value_min'}]},
    {'kind': 'lesson', 'body': 'Disable check:ml-label-leakage when the run is a replay.'},
    {'kind': 'rca-investigator-bundle', 'checks': [{'check_id': 'check:x', 'verdict': 'fail', 'source': 'def x(): ...'}]},
    {'kind': 'agent-worker-receipt', 'evaluator': {'before': 'a', 'after': 'b'}},
])
def test_ci_scan_flags_each_runtime_artefact_kind(tmp_path, record):
    assert pp.scan([write(tmp_path / 'r.json', record)])


def test_ci_scan_reads_jsonl_transcripts(tmp_path):
    path = tmp_path / 'knowledge-served.jsonl'
    path.write_text(json.dumps({'kind': 'broker-receipt', 'writes': ['ok.txt']}) + '\n'
                    + json.dumps({'kind': 'broker-receipt', 'writes': ['src/ravel/data/rdj/policy.json']}) + '\n')
    assert len(pp.scan([path])) == 1


def test_committed_runtime_artefacts_write_no_protected_path():
    roots = [ROOT / d for d in ('evidence', 'trial-runs', 'src/ravel/data/knowledge/lessons') if (ROOT / d).exists()]
    assert pp.scan(roots) == []


def test_cli_runs_as_a_module_with_the_standard_library_only(tmp_path):
    bad = write(tmp_path / 'calls/1.json', {'kind': 'broker-receipt', 'writes': ['src/ravel/validation/x.py']})
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    proc = subprocess.run([sys.executable, '-m', 'ravel.validation.check_protected_paths', '--check-manifest',
                           '--json', str(bad)], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert proc.returncode == 1 and json.loads(proc.stdout)['ok'] is False


def test_investigator_bundle_carries_id_and_verdict_not_source():
    results = [{'check_id': 'check:closure', 'verdict': 'fail', 'finding_id': 'F2',
                'source': 'def closure(...): ...', 'predicate': {'fact': 'x'}, 'threshold': 3.0,
                'path': 'src/ravel/validation/regression_triggers.py', 'message': 'chi2/ndf 4.1 above 3.0'}]
    bundle = pp.investigator_bundle(results)
    assert bundle == [{'check_id': 'check:closure', 'verdict': 'fail', 'finding_id': 'F2'}]
    assert pp.bundle_errors({'checks': bundle}) == []
    assert pp.bundle_errors({'checks': results})
    with pytest.raises(ValueError):
        pp.investigator_bundle([{'verdict': 'fail'}])
