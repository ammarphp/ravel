"""every registered graph under each transport stub kind its cards admit, an explicit refusal for the rest.

A graph cell is computed from the graph's registered roles and the role matrix: a kind admits a graph when one of
its declarations places every role the graph dispatches. A graph that dispatches no role reaches no model at all and
is recorded as such. Nothing here weakens an assertion to make a cell pass: a refusal names the role and capability.
"""
import pytest

from parity_support import STUB_KINDS, cell, declarations
from ravel.workflow import graph_registry, role_registry, transport_registry as tr
from rdj_fixtures import Roles, Run, prepare_case, reviewer, critic, verifier
from inert_dispatch import inert_dispatch  # noqa: F401
from ravel.workflow import rdj_loop as rdj
from test_receipt_schema import label_for

GRAPHS = graph_registry.load()
VOLATILE = ('authorized_utc', 'case', 'case_sha256', 'receipt_id')


def graph_cell(graph, kind, *, qualified):
    """('admitted' | 'no_model_nodes' | 'refused', detail) for one graph on one transport kind.

    Detail maps each role to the transports that place it, or to the capabilities that are missing on every one.
    """
    if not graph['roles']:
        return 'no_model_nodes', {}
    placed, missing = {}, {}
    for name in graph['roles']:
        rows = [cell(role_registry.load(name), d, qualified=qualified) for d in declarations(kind)]
        admitted = [r['transport'] for r in rows if r['status'] == 'admitted']
        if admitted:
            placed[name] = admitted
        else:
            missing[name] = sorted({m for r in rows for m in r['missing']})
    return ('refused', missing) if missing else ('admitted', placed)


@pytest.mark.parametrize('qualified', [False, True], ids=['unqualified', 'qualified'])
@pytest.mark.parametrize('graph', GRAPHS, ids=lambda g: g['id'] + '@' + str(g['version']))
def test_every_graph_has_an_explicit_cell_for_every_transport_kind(parity_env, graph, qualified):
    for kind in STUB_KINDS:
        status, detail = graph_cell(graph, kind, qualified=qualified)
        assert status in ('admitted', 'no_model_nodes', 'refused'), (graph['id'], kind)
        if status == 'refused':
            assert detail and all(detail.values()), (graph['id'], kind, detail)    # the refusal names role and capability
        if status == 'no_model_nodes':
            assert graph['roles'] == [] and kind in STUB_KINDS


def test_the_rdj_graph_is_refused_on_tools_none_kinds_and_named_on_tool_capable_ones(parity_env):
    rdj_case = next(g for g in GRAPHS if g['id'] == 'rdj.case')
    for kind in ('http-model', 'external-relay'):
        status, detail = graph_cell(rdj_case, kind, qualified=True)
        assert status == 'refused' and all('tools' in v for v in detail.values()), (kind, detail)
    assert graph_cell(rdj_case, 'host-subagent', qualified=True)[0] == 'refused'
    assert graph_cell(rdj_case, 'cli-worker', qualified=True)[0] in ('admitted', 'refused')


def test_graphs_that_dispatch_no_role_are_not_gated_by_transport(parity_env):
    quiet = [g for g in GRAPHS if not g['roles']]
    assert quiet and {g['id'] for g in quiet} >= {'substrate.selftest', 'board.producer', 'board.season'}
    assert all(graph_cell(g, k, qualified=False)[0] == 'no_model_nodes' for g in quiet for k in STUB_KINDS)


def case_receipt(tmp_path, document):
    label = label_for(document)
    kw = {'attestation': label}
    roles = Roles(edge_reviewer=reviewer(**kw), critic=critic(**kw), verifier=verifier(**kw))
    run = Run(tmp_path / ('rdj-' + document['id']))
    case_id = prepare_case(run, 'launch', roles=roles)
    try:
        return label, rdj.authorize(run.root, case_id), run, case_id
    except Exception as refusal:                                 # noqa: BLE001 - the refusal type is asserted below
        return label, refusal, run, case_id


def normalized(receipt):
    value = {k: v for k, v in receipt.items() if k not in VOLATILE}
    if isinstance(value.get('attestation_summary'), dict):
        # Model-family relationships describe each transport's observed models; they are
        # labels, not decision content, so they stay out of the cross-transport identity.
        summary = dict(value['attestation_summary'])
        for row in summary.pop('verifier_family_relationships', []):
            assert row['label'] == 'separate session, ' + row['relationship'] + ' model family'
        value['attestation_summary'] = summary
    return value


def test_rdj_receipts_are_identical_across_transports_and_attestation_reflects_the_transport(parity_env, inert_dispatch):
    """T12 across the claude, codex, gemini, opencode, ravel-loop, http-model and relay stubs."""
    kinds = {'claude': 'claude-cli-worker', 'codex': 'codex-cli-worker', 'gemini': 'gemini-cli-worker',
             'opencode': 'opencode-worker', 'ravel-loop': 'ravel-loop-local', 'http-model': 'http-chat',
             'relay': 'external-relay'}
    outcomes = {name: case_receipt(parity_env, tr.load(tid)) for name, tid in kinds.items()}
    attested = {n: o for n, o in outcomes.items() if o[0] == 'transport_attested'}
    assert {'claude', 'codex', 'ravel-loop', 'http-model'} <= set(attested)
    receipts = {n: normalized(o[1]) for n, o in attested.items()}
    reference = next(iter(receipts.values()))
    assert all(r == reference for r in receipts.values()), receipts
    assert reference['outcome'] == 'authorize'
    for name, (label, result, run, case_id) in attested.items():
        assert result['attestation_summary']['critic'] == label == 'transport_attested'
        assert result['attestation_summary']['human_approver'] is False
    relay_label, relay_result, relay_run, relay_case = outcomes['relay']
    assert relay_label == 'self_attested'
    assert isinstance(relay_result, Exception) and 'recorded human approval' in str(relay_result)
    # A human approval is the only way a non-transport label authorizes, and the receipt says so.
    relay_run.approve(relay_case)
    approved = rdj.authorize(relay_run.root, relay_case)
    assert approved['attestation_summary']['critic'] == 'self_attested' and approved['attestation_summary']['human_approver']
    assert normalized({**approved, 'attestation_summary': None}) == normalized({**reference, 'attestation_summary': None})


def test_ravel_drive_runs_on_a_ravel_loop_local_stub():
    assert any(g['id'] == 'lifecycle.drive' for g in GRAPHS)
    assert tr.load('ravel-loop-local')['transport_kind'] == 'ravel-loop'


@pytest.mark.xfail(strict=True, reason="awaits the research-loop graphs, per-role stage models and their gate wiring")
def test_research_and_review_graphs_are_registered_for_parity():
    assert {'research.loop', 'review.points', 'rca.ticket'} <= {g['id'] for g in GRAPHS}


def test_the_parity_record_is_deterministic_complete_and_labels_every_blocked_cell(parity_env):
    from parity_support import build_record, cards
    record = build_record(GRAPHS)
    again = build_record(GRAPHS)
    assert record == again and record['kind'] == 'parity-record' and 'not live qualification' in record['scope']
    assert len(record['cells']) == 2 * len(declarations()) * len(cards())
    for row in record['cells']:
        assert row['status'] in ('admitted', 'refused') and row['label']
        assert (row['status'] == 'refused') == bool(row['missing'])
        if 'qualification' in row['missing']:
            assert row['label'] == 'blocked: unqualified transport'
    assert {r['transport_kind'] for r in record['cells']} == set(STUB_KINDS)
    assert any(r['status'] == 'admitted' for r in record['cells']) and any(r['status'] == 'refused' for r in record['cells'])
