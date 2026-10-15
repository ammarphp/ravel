"""Voting reviewers as full-tool agent nodes: projection workspaces, receipts, divergence and screening."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'unit'))

from ravel.workflow import agent_worker, graph_nodes, rdj_custody  # noqa: E402

from planted_fixtures import HEADLINE, write  # noqa: E402
from test_agent_worker import put  # noqa: E402

PROVIDERS = ('review_points', 'rdj', 'ceilings', 'executor', 'spawn_rows', 'input_closure', 'raw_launch',
             'figure_critique')


def review():
    from ravel.workflow.graphs import review as module
    return module


@pytest.fixture
def root(tmp_path):
    from rdj_fixtures import Run
    return Run(tmp_path.resolve() / 'run', snapshot=False).root


def plan(root, claim):
    pin = write(root / 'inputs/request_plan.json', {'nodes': [], 'edges': [], 'claims': [claim]})
    pin['path'] = 'inputs/request_plan.json'
    contract = json.loads((root / 'inputs/task_contract.json').read_text()) if (root / 'inputs/task_contract.json').exists() else {}
    write(root / 'inputs/task_contract.json', {**contract, 'agent_layer_epoch': 2, 'delegated': True, 'request_plan': pin})
    write(root / 'RESULT.md', HEADLINE + '\n')
    write(root / 'inputs/checkin2.json', {'summary': HEADLINE})


class Workers:
    """Stands in for the transport: materializes the real workspace, records what it holds, finishes."""

    def __init__(self, root, *, findings=None, regions=None):
        self.root, self.findings, self.regions = Path(root), findings or {}, regions or []
        self.seen = []

    def __call__(self, rundir, spec, **options):
        role = spec['role']['id']
        ws = agent_worker.materialize(rundir, spec, **{k: v for k, v in options.items()
                                                       if k in ('graph', 'framework_step', 'packet', 'protected', 'effect')})
        packet = json.loads((ws / 'inputs/review-packet.json').read_text())
        files = {p.relative_to(ws).as_posix(): p.read_bytes() for p in ws.rglob('*') if p.is_file()}
        self.seen.append({'role': role, 'files': files, 'packet': options.get('packet')})
        final = {'completed': True, 'disposition': 'supported', 'findings': deepcopy(self.findings.get(role, []))}
        if role == 'analysis-author':
            final['regions'] = self.regions[len([s for s in self.seen if s['role'] == role]) - 1]
        put(rundir, ws, 'outputs/review.json', json.dumps({'findings': final['findings']}))
        # The dispatcher assigns the actor of each worker session before it runs.
        agent_worker.bind_actor(rundir, spec['node_id'], spec['attempt'], transport_id='unknown',
                                model_id='synthetic-model')
        receipt = agent_worker.finish(rundir, spec, execution={'exit_status': 0}, final=final)
        assert receipt['status'] == 'ok', receipt
        # Credit needs an attested, independent registration; the transport layer supplies it in production.
        rel = f"agent-work/{spec['node_id']}/{spec['attempt']}/receipt.json"
        value = json.loads((self.root / rel).read_text())
        credit = 'credit-' + spec['node_id']
        actor = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', 'ws-' + credit, credit + '/1')
        value.update(execution_mode='transport_attested_cli', session_id='s-' + spec['node_id'],
                     actor_id=actor['actor_id'], transport={'id': 'synthetic-cli', 'transport_kind': 'cli-worker'},
                     model={'family': 'f-' + spec['node_id']})
        final_pin = write(self.root / 'agent-work' / credit / '1/final.json', final)
        value.update(node_id=credit, attempt=1, final_record={**value['final_record'], 'sha256': final_pin['sha256']})
        write(self.root / 'agent-work' / credit / '1/receipt.json', value)
        rdj_custody.register_worker_receipt(self.root, f'agent-work/{credit}/1/receipt.json',
                                            verified_label='transport_attested', actor=actor)
        return receipt


def run_review(root, monkeypatch, workers, at='checkin2:C1'):
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    try:
        return review().run(root, at, gate_check=lambda *a: [], gate_providers=lambda g: {p: True for p in PROVIDERS})
    finally:
        graph_nodes.forget_handled()


def test_worker_receipt_carries_the_dispatcher_review_subject(root, monkeypatch):
    """A governed receipt's review_subject comes from the code-computed packet."""
    plan(root, {'id': 'C1', 'kind': 'agreement', 'absolute_yield': True})
    from ravel.workflow import review_points
    run_review(root, monkeypatch, Workers(root))
    subjects = {}
    for path in sorted((root / 'agent-work').glob('review-*/1/receipt.json')):
        receipt = json.loads(path.read_text())
        subjects[receipt['review_point_id']] = receipt['review_subject']
    facts = review_points._facts(root)
    points = {p['id']: p for p in review_points.derive(facts)}
    assert subjects and all(v['sha256'] == review_points.subject_digest(facts, points[k]) for k, v in subjects.items())
    for path in sorted((root / 'agent-work').glob('review-*/1/receipt.json')):
        # The transport registers its receipts; here the real receipt itself is registered, unmodified.
        actor = agent_worker._record(root, path.parent.parent.name, 1)['actor']
        rdj_custody.register_worker_receipt(root, path.relative_to(root).as_posix(), verified_label='transport_attested',
                                            actor=actor)
    eligible = [r for r in review_points._receipt_records(root, facts) if r['node_id'].startswith('review-')]
    assert eligible and all(r['_eligible'] and r['_advisory'] is None for r in eligible)


def test_review_item_workspace_holds_the_card_projection_and_never_the_headline(root, monkeypatch):
    plan(root, {'id': 'C1', 'kind': 'agreement', 'absolute_yield': True})
    workers = Workers(root)
    run_review(root, monkeypatch, workers)
    by_role = {s['role']: s for s in workers.seen}
    assert {'physics-critic', 'normalization-auditor'} <= set(by_role)
    for seen in workers.seen:
        manifest = json.loads(seen['files']['inputs/packet/manifest.json'])
        assert manifest['role'] == seen['role'] and manifest['kind'] == 'review-projection'
        assert not any(HEADLINE.encode() in raw for raw in seen['files'].values())
        assert not Path(seen['packet']['path']).resolve().is_relative_to(root)


def test_finding_citing_a_non_receipt_pin_is_refused_and_recorded(root, monkeypatch):
    plan(root, {'id': 'C1', 'kind': 'agreement', 'absolute_yield': True})
    bad = {'summary': 'cites a run file', 'materiality': 'A', 'evidence_class': 'code_check',
           'evidence_locators': ['outputs/yields.json']}
    run_review(root, monkeypatch, Workers(root, findings={'normalization-auditor': [bad]}))
    refused = [json.loads(p.read_text()) for p in (root / 'review/refused-findings').glob('*.json')]
    assert len(refused) == 1
    assert refused[0]['findings'][0]['refusal'][0]['code'] == 'non_receipt_pin'


AUTHORED = {'id': 'C1', 'kind': 'measurement', 'basis_declared': ['authored_code']}


def test_divergent_analysis_authors_raise_an_a_finding_routed_to_rca(root, monkeypatch):
    plan(root, AUTHORED)
    regions = [{'SRA': {'yield': 10.0, 'stat': 0.1}}, {'SRA': {'yield': 15.0, 'stat': 0.1}}]
    observation = run_review(root, monkeypatch, Workers(root, regions=regions))
    assert observation['terminal']['reason'] == 'rca_ticket_required', observation
    records = list((root / 'review/divergence').glob('*.json'))
    assert len(records) == 1 and json.loads(records[0].read_text())['status'] == 'failed'


def test_consistent_analysis_authors_do_not_block(root, monkeypatch):
    plan(root, AUTHORED)
    regions = [{'SRA': {'yield': 10.0, 'stat': 0.3}}, {'SRA': {'yield': 10.3, 'stat': 0.3}}]
    observation = run_review(root, monkeypatch, Workers(root, regions=regions))
    assert (observation['terminal'] or {}).get('reason') != 'rca_ticket_required', observation
    records = list((root / 'review/divergence').glob('*.json'))
    assert len(records) == 1 and json.loads(records[0].read_text())['status'] == 'passed'
