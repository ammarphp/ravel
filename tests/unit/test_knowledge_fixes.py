"""Lesson schema and rules, the retrieval floor, request-free text, installed source root and export regeneration.

Synthetic requests, facts and numbers only; no native execution and no network.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ravel.workflow import knowledge as K
from ravel.workflow import knowledge_atlas as ka
from ravel.workflow import premises
from ravel.validation import check_knowledge as ck

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / 'src/ravel/data/knowledge'


def good_lesson(**changes):
    row = {
        'id': 'lesson:cache-the-lookup',
        'trigger': {'all': [{'fact': 'failure_class', 'equals': 'stale-lookup'},
                            {'fact': 'tool', 'in': ['tool-a', 'tool-b']}]},
        'body': 'Re-run the lookup for the pinned version; do not copy a value between versions.',
        'evidence': {'ticket': {'id': 'ticket-1', 'facts': {'failure_class': 'stale-lookup', 'tool': 'tool-a'}},
                     'receipts': [{'path': 'receipts/r1.json', 'sha256': '0' * 64}]},
        'confirming_check': 'check:validation.validate_run_state',
        'scope': {'tool': 'tool-a', 'tool_version': '1.2', 'ravel_version': '0.1'},
        'status': 'candidate',
        'impact': None,
    }
    row.update(changes)
    return row


def errors_for(row, **kw):
    from ravel.workflow.knowledge_lessons import lesson_errors
    return lesson_errors(row, **kw)


# --- lesson schema and rules (acceptance 1) ---

def test_schema_declares_the_lesson_fields():
    schema = json.loads((KNOWLEDGE / 'schema/lesson.json').read_text())
    assert {'trigger', 'body', 'evidence', 'confirming_check', 'scope', 'status', 'impact'} <= set(schema['required'])
    assert schema['properties']['status']['enum'] == ['candidate', 'trial', 'promoted', 'revoked', 'dormant']


def test_a_complete_lesson_is_accepted():
    assert errors_for(good_lesson()) == []


def test_lesson_without_a_trigger_is_refused():
    row = good_lesson(); del row['trigger']
    assert errors_for(row)
    assert errors_for(good_lesson(trigger={'all': []}))


def test_trigger_that_does_not_fire_on_its_own_ticket_is_refused():
    row = good_lesson()
    row['evidence']['ticket']['facts'] = {'failure_class': 'other-class', 'tool': 'tool-a'}
    assert any('own ticket' in e for e in errors_for(row))


def test_trigger_over_unknown_facts_is_refused():
    row = good_lesson(trigger={'all': [{'fact': 'prose', 'equals': 'x'}]})
    assert errors_for(row)


def test_lesson_without_a_confirming_check_is_refused():
    row = good_lesson(); del row['confirming_check']
    assert errors_for(row)
    assert errors_for(good_lesson(confirming_check=''))
    assert any('confirming_check' in e for e in errors_for(good_lesson(confirming_check='check:absent'),
                                                          check_ids={'check:present'}))


def test_promoted_without_impact_is_refused():
    assert any('impact' in e for e in errors_for(good_lesson(status='promoted', impact=None)))
    impact = {'arm_with': 'run-a', 'arm_without': 'run-b', 'tasks': ['t1'], 'metric': 'success'}
    assert errors_for(good_lesson(status='promoted', impact=impact)) == []
    assert errors_for(good_lesson(status='promoted', impact={**impact, 'tasks': []}))


def test_lesson_without_receipts_or_with_long_body_is_refused():
    row = good_lesson(); row['evidence']['receipts'] = []
    assert errors_for(row)
    assert errors_for(good_lesson(body='\n'.join(['line'] * 41)))


def test_unknown_status_is_refused():
    assert errors_for(good_lesson(status='reviewed'))


def test_check_knowledge_reads_the_lesson_store(tmp_path):
    store = tmp_path / 'src/ravel/data/knowledge/lessons'
    store.mkdir(parents=True)
    (store / 'ok.json').write_text(json.dumps(good_lesson()))
    broken = good_lesson(id='lesson:broken', status='promoted'); broken['impact'] = None
    (store / 'broken.json').write_text(json.dumps(broken))
    errors = ck.lesson_store_errors(tmp_path, {'check:validation.validate_run_state'})
    assert any('lesson:broken' in e for e in errors)
    assert not any('lesson:cache-the-lookup' in e for e in errors)


# --- retrieval floor (acceptance 2) ---

def test_nonsense_query_returns_nothing_below_floor():
    for text in ('flibbertigibbet wombat sandwich', 'what is the capital of france',
                 'how do I bake sourdough bread', 'best pizza recipe in naples'):
        result = K.query('find', text=text)
        assert result['results'] == [] and result['served_ids'] == [], text
        assert result['items'] == [] and result['reason'] == 'below_floor', text
        assert result['floor']['value'] > 0
        assert result['result_sha256']


def test_a_real_query_is_served():
    result = K.query('find', text='narrow width approximation for a wide resonance')
    assert result['results'] and 'reason' not in result


def test_floor_is_recorded_and_separates_the_battery():
    record = json.loads((KNOWLEDGE / 'floor.json').read_text())
    battery = record['battery']
    rows = K.load_atlas()['entries']
    best = lambda q: (K._rank(rows, q) or [(0.0,)])[0][0]
    low_positive = min(best(q) for q in battery['positive'])
    high_negative = max(best(q) for q in battery['negative'])
    assert high_negative < record['floor'] <= low_positive
    assert K.FLOOR == record['floor']


# --- request-free text (acceptance 3, 4) ---

PLANTED = [
    'T1 example: a heavy scalar (the "pair threshold boson" ask).',
    'Requested width (the wide-mediator ask goes to 0.3).',
    'The ask extends below the trigger threshold.',
]


@pytest.mark.parametrize('text', PLANTED)
def test_planted_request_phrase_is_found(tmp_path, text):
    target = tmp_path / 'docs/workflow/checklists'
    target.mkdir(parents=True)
    (target / 'note.md').write_text('| T0 | ' + text + ' |\n')
    errors = ck.request_paraphrase_errors(tmp_path)
    assert errors and 'note.md' in errors[0]


def test_registered_literal_is_found_in_data_files(tmp_path):
    target = tmp_path / 'src/ravel/data/knowledge'
    target.mkdir(parents=True)
    (target / 'row.json').write_text(json.dumps({'statement': 'A distinctive Held-Out Phrase appears.'}))
    assert not ck.request_paraphrase_errors(tmp_path)
    assert ck.request_paraphrase_errors(tmp_path, literals=['held-out phrase'])


def test_the_tree_carries_no_request_paraphrase():
    assert ck.request_paraphrase_errors(ROOT) == []


def test_scan_covers_the_declared_trees():
    assert {'src/ravel/data/knowledge', 'docs/workflow/checklists'} <= set(ck.ANTI_BENCH_TREES)


def test_power_law_scaling_premise_fires_on_planted_facts():
    plan = {'nodes': [{'id': 'n1', 'operation': 'limit-mapping',
                       'tags': ['power-law-signal-scaling', 'shared-amplitudes']}]}
    ids = {r['id'] for r in premises.firing(plan)}
    assert 'trap:power-law-signal-scaling' in ids
    alone = {r['id'] for r in premises.firing({'nodes': [{'id': 'n1', 'tags': ['power-law-signal-scaling']}]})}
    assert 'trap:power-law-signal-scaling' not in alone
    morph = {r['id'] for r in premises.firing({'nodes': [{'id': 'n1', 'tags': ['morphing-basis', 'shared-amplitudes']}]})}
    assert 'trap:power-law-signal-scaling' in morph


def test_tuning_to_observed_data_premise_fires_on_planted_facts():
    for tag in ('tuned-to-observed-data', 'selection-optimized-on-data', 'normalization-fit-to-data'):
        ids = {r['id'] for r in premises.firing({'nodes': [{'id': 'n1', 'tags': [tag]}]})}
        assert 'trap:tuning-to-observed-data' in ids, tag
    assert 'trap:tuning-to-observed-data' not in {r['id'] for r in premises.firing({'nodes': [{'id': 'n1', 'tags': ['trigger']}]})}


def test_new_premises_are_cited_and_in_the_atlas():
    rows = {r['id']: r for r in K.load_atlas()['entries']}
    assert 'trap:power-law-signal-scaling' in rows and 'trap:tuning-to-observed-data' in rows
    for row in premises.registry()['premises']:
        assert row['citation'] and all(c['locator'] for c in row['citation'])


# --- installed source root (acceptance 5) ---

@pytest.fixture(scope='module')
def installed(tmp_path_factory):
    site = tmp_path_factory.mktemp('site')
    shutil.copytree(ROOT / 'src/ravel', site / 'ravel', ignore=shutil.ignore_patterns('__pycache__'))
    return site


def run_installed(site, args, cwd, root=None):
    env = {k: v for k, v in os.environ.items() if k not in ('RAVEL_ROOT', 'PYTHONPATH')}
    env.update(PYTHONPATH=str(site), HOME=str(cwd), RAVEL_STATE_DIR=str(cwd / 'state'))
    if root is not None:
        env['RAVEL_ROOT'] = str(root)
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


def test_installed_source_root_is_the_checkout_not_site_packages(installed, tmp_path):
    code = 'from ravel.workflow.knowledge_atlas import source_root; import ravel; print(ravel.__file__); print(source_root())'
    done = run_installed(installed, ['-c', code], tmp_path, root=ROOT)
    assert done.returncode == 0, done.stderr
    package, root = done.stdout.split('\n')[:2]
    assert package.startswith(str(installed)) and Path(root) == ROOT


def test_installed_without_a_checkout_says_so(installed, tmp_path):
    done = run_installed(installed, ['-m', 'ravel.workflow.knowledge', 'check'], tmp_path)
    assert done.returncode != 0
    assert 'source checkout' in (done.stdout + done.stderr)
    assert 'Traceback' not in done.stderr


def test_installed_build_resolves_sources(installed, tmp_path):
    done = run_installed(installed, ['-m', 'ravel.workflow.knowledge', 'build'], tmp_path, root=ROOT)
    assert done.returncode == 0, done.stderr
    assert done.stdout.encode() == (ROOT / ka.ATLAS).read_bytes()
