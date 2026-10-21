"""Workload chains W1-W4 through the registered graphs on stub transports, tripwire on.

Each chain is one ``lifecycle.drive`` instance; its review and production work runs in the
``review.points``/``review.item`` and ``production.node`` subgraphs. The assertions:

1. the dispatched role set equals the set the merged rows derive, and the pinned expectation;
2. every design role that is not dispatched, and every derived point the lifecycle does not
   route, is listed as skipped with its landing slot;
3. the L-10 grader reports raw beside strict, and its ABC probes (empty, copied reference,
   format-only) score 0 on both;
4. no fixture, helper, test or chain record names a benchmark, paper or person (R-10).

The tripwire runs in block mode for every chain: a dispatch or broker call without a substrate
context fails the chain. Synthetic numbers only; no model, network or native tool.
"""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workload_chains as wc  # noqa: E402

WORKLOADS = {w['id']: w for w in wc.workloads()}
REFERENCES = wc.load('references.json')['references']
CHAIN_GRAPHS = {'lifecycle.drive', 'production.node', 'review.item'}


def _workload(wid):
    return WORKLOADS[wid]


def _run(tmp_path, monkeypatch, wid, **options):
    wc.reset_tripwire()
    root = wc.run_root(tmp_path, monkeypatch)
    chain = wc.run_chain(root, _workload(wid), monkeypatch, tripwire_record=tmp_path / 'tripwire.jsonl', **options)
    record = wc.chain_record(root, _workload(wid), chain, wc.observed_tripwire())
    return root, chain, record


# ---- the chains ------------------------------------------------------------------------------

@pytest.mark.parametrize('wid', sorted(WORKLOADS))
def test_workload_chain_runs_through_the_registered_graphs(wid, tmp_path, monkeypatch):
    """Acceptance 1 and 2, the tripwire record and the L-10 scores for one chain."""
    from ravel.workflow import graph_registry, role_registry
    root, chain, record = _run(tmp_path, monkeypatch, wid)
    workload = _workload(wid)
    wc.keep(record)

    # The lifecycle ran to its end through CHECK-IN 1, 2 and 3 on the run's own records.
    assert record['terminal'] is None and chain['observation']['next'] == [], chain['observation']
    assert record['stops'][0] == ['checkin1_response'] and record['stops'][-2] == ['checkin3_response']
    assert record['stops'][-1] == []
    assert all(executor == 'worker' for executor in record['nodes'].values()), record['nodes']
    assert set(record['graphs']) == CHAIN_GRAPHS
    registered = {row['id'] for row in graph_registry.load()}
    assert set(record['graphs']) <= registered

    # 1. The role set derived from merged rows, and nothing else, was dispatched.
    assert wc.role_set_problems(record, workload) == []

    # 2. Skipped roles are listed with their landing slot.
    assert wc.skipped_problems(record, workload) == []
    assert record['skipped'], 'every workload design names roles that no merged row dispatches yet'

    # Tripwire in block mode: every dispatch and broker write ran inside an acting substrate node.
    assert record['tripwire']['violations'] == [] and record['tripwire']['verdicts'] >= len(chain['workers'].calls)
    assert {'agent_worker.launch', 'broker.call'} <= set(record['tripwire']['layers'])
    lines = [json.loads(line) for line in (tmp_path / 'tripwire.jsonl').read_text().splitlines()]
    assert len(lines) == record['tripwire']['verdicts'] and all(v['ok'] and v['mode'] == '1' for v in lines)
    # Every verdict ran in a registered graph, inside a node kind its layer is sanctioned for; dispatch and
    # broker calls ran inside acting agent nodes.
    from ravel.validation import check_agent_paths
    sanctioned = {row['layer']: set(row['acting_kinds']) for row in check_agent_paths.load_sanctioned()['tripwire_layers']}
    misplaced = [v for v in lines if v['context']['graph_id'] not in registered
                 or v['context']['ravel_kind'] not in sanctioned[v['layer']]
                 or (v['layer'] in ('agent_worker.launch', 'broker.call') and v['context']['ravel_kind'] != 'agent')]
    assert misplaced == [], misplaced
    assert record['refused_connections'] == []

    # Each call carries its registered card digest, its graph and a framework step.
    for call in record['calls']:
        assert call['card_sha256'] == role_registry.card_sha256(call['role']), call
        assert call['graph_id'] in CHAIN_GRAPHS and call['ravel_kind'] == 'agent', call
        assert call['framework_step'] is not None, call

    # L-10: raw beside strict, against the tolerance declared before the run.
    assert wc.score(root, workload, REFERENCES[wid]) == {'raw': 1, 'strict': 1, 'reason': 'scored'}

    # 4. The chain's own record names no benchmark, paper or person.
    assert scan_text(json.dumps(record, default=str)) == []

    # 3. Trivial outputs planted over the finished chain score 0 on both scales.
    result = root / f"outputs/{workload['scored_node']}/result.json"
    for planted in ('', json.dumps(REFERENCES[wid]), json.dumps({'verdict': None, 'quantity': None, 'value': None})):
        result.write_text(planted)
        scored = wc.score(root, workload, REFERENCES[wid])
        assert (scored['raw'], scored['strict']) == (0, 0), (planted, scored)


def test_strict_is_reported_beside_raw_and_can_be_lower(tmp_path, monkeypatch):
    """A right verdict with a quantity outside the declared tolerance is raw 1, strict 0."""
    workload = _workload('W2')
    result = dict(workload['producer_result'], value=REFERENCES['W2']['value'] * 1.5)
    root, _, record = _run(tmp_path, monkeypatch, 'W2', result=result)
    assert record['terminal'] is None
    assert wc.score(root, workload, REFERENCES['W2']) == {'raw': 1, 'strict': 0, 'reason': 'scored'}


# ---- ABC probes inside a chain ---------------------------------------------------------------

PROBES = {
    'empty': '',
    'copied_reference': json.dumps(REFERENCES['W1']),
    'format_only': json.dumps({'verdict': 'pending', 'quantity': 'selected_fraction', 'value': 'n/a'}),
}


@pytest.mark.parametrize('probe', sorted(PROBES))
def test_abc_probe_scores_zero(probe, tmp_path, monkeypatch):
    """Acceptance 3: the scored producer emits the probe through its broker inside the chain.

    A copied reference and a format-only result are credited and the chain finishes; an empty
    result is not credited, so the production node holds. Each scores 0 raw and 0 strict.
    """
    workload = _workload('W1')
    root, chain, record = _run(tmp_path, monkeypatch, 'W1', result=PROBES[probe])
    assert record['tripwire']['violations'] == []
    if probe == 'empty':
        assert record['terminal']['reason'] == 'lifecycle_node_held', record['terminal']
    else:
        assert record['terminal'] is None, record['terminal']
    assert wc.score(root, workload, REFERENCES['W1']) == {'raw': 0, 'strict': 0, 'reason': probe}


def test_an_uncredited_result_scores_zero_even_when_it_is_right(tmp_path, monkeypatch):
    """A correct-looking result written outside the worker's broker has no custody and scores 0."""
    workload = _workload('W4')
    root, _, record = _run(tmp_path, monkeypatch, 'W4')
    assert record['terminal'] is None
    path = root / 'outputs/N2/result.json'
    value = json.loads(path.read_text())
    path.write_text(json.dumps({**value, 'value': REFERENCES['W4']['value']}))
    assert wc.score(root, workload, REFERENCES['W4']) == {'raw': 0, 'strict': 0, 'reason': 'no_custody'}


# ---- negative controls for the assertions ----------------------------------------------------

def test_a_dispatch_outside_a_substrate_node_trips(tmp_path, monkeypatch):
    """The stub transport asserts the substrate context first; outside every node it refuses."""
    from ravel.workflow import agent_tripwire
    monkeypatch.setenv(agent_tripwire.ENV, '1')
    workers = wc.ChainWorkers(tmp_path, scored_node='N1', result=None)
    with pytest.raises(agent_tripwire.TripwireViolation, match='agent_worker.launch'):
        workers(tmp_path, {'role': {'id': 'generator'}})
    with pytest.raises(agent_tripwire.TripwireViolation, match='broker.call'):
        wc.put(tmp_path, tmp_path / 'N1' / '1', 'outputs/x.json', '{}')
    assert workers.calls == []


def test_role_set_assertion_catches_extra_missing_and_drifted_roles():
    workload = _workload('W1')
    expected = sorted(workload['expect_dispatched'])
    clean = {'workload': 'W1', 'dispatched_roles': expected, 'derived_roles': expected}
    assert wc.role_set_problems(clean, workload) == []
    extra = {**clean, 'dispatched_roles': expected + ['figure-critic']}
    assert any('figure-critic dispatched but no merged row derives it' in p for p in wc.role_set_problems(extra, workload))
    missing = {**clean, 'dispatched_roles': [r for r in expected if r != 'trap-auditor']}
    assert any('trap-auditor derived but never dispatched' in p for p in wc.role_set_problems(missing, workload))
    drifted = {**clean, 'dispatched_roles': expected + ['inference'], 'derived_roles': expected + ['inference']}
    assert wc.role_set_problems(drifted, workload) == ['W1: dispatched set differs from the pinned expectation']


def test_skipped_assertion_catches_an_unlisted_role_and_a_missing_slot():
    workload = _workload('W1')
    dispatched = set(workload['expect_dispatched'])
    rows = wc.skipped(workload, dispatched, [{'point': 'RP3:N2', 'row': 3, 'at': 'node:N2',
                                               'roles': ['consult-pythia-delphes']}])
    record = {'workload': 'W1', 'dispatched_roles': sorted(dispatched), 'skipped': rows}
    assert wc.skipped_problems(record, workload) == []
    unlisted = {**record, 'skipped': [r for r in rows if r['role'] != 'literature-scout']}
    assert wc.skipped_problems(unlisted, workload) == ['W1: design role literature-scout neither dispatched nor skipped']
    # A design role the chain does not dispatch (the delivery-stage assumption auditor) without its slot is caught.
    assert any(r['role'] == 'assumption-auditor' and r['source'] == 'design' for r in rows)
    slotless = {**record, 'skipped': [dict(r, landing=None) if r['role'] == 'assumption-auditor' else r for r in rows]}
    assert any('assumption-auditor' in p and 'no landing slot' in p for p in wc.skipped_problems(slotless, workload))


def test_every_skipped_point_kind_and_design_role_has_a_slot():
    table = wc.landing()
    slots = set(table['slots'])
    assert set(table['roles'].values()) | set(table['components'].values()) | set(table['ats'].values()) <= slots
    from ravel.workflow import role_registry
    known = {card['id'] for card in role_registry.all_cards()}
    for workload in WORKLOADS.values():
        assert workload['expect_dispatched'] and set(workload['expect_dispatched']) <= known
        for component in workload['design']:
            for role in component['roles']:
                if role in workload['expect_dispatched']:
                    continue
                assert (table['roles'].get(role) or table['components'].get(component['component'])) in slots, role


# ---- R-10 scan -------------------------------------------------------------------------------

# Digests of blocked terms (benchmark, paper and person identities this package's design table
# carries). The words themselves never appear in the tree; the scan compares digests.
BLOCKED = frozenset({
    'a55b9d54dd8892f5f10251b30a77f171a6d7ab73cdf452087ad5df0ac456cf37',
    '7276efffd40dedad8714a82d93110c1f6cd6ac61c6e6368e101c07a62abbb216',
    'c0e7aec81a1a194e9f54f6b297f6544041188c741ae8f55c2133b5c510a7dc1d',
    'a73e8e7a60a0109a7657cc991ca24ae94b2c083777ae09234cf5decf853d47c8',
    'd2e6584907a815aa7b0eaf285d7d839d15670c78dcb1fee0991c653f3c82a1d6',
    '12b0f0dcaefb10c02a83aa9adb025978ddb5512dc04eb39df6811c6a6bf9770c',
    '359df2a16e4ff580b39e064c9649ddf157d0682515344c37f57e60f183e9a08e',
})


def scan_text(text, blocked=BLOCKED):
    from ravel.validation import tool_selection_score as tss
    return tss.scan_identifiers([{'case_id': 'scan', 'text': text}], blocked_digests=blocked)


def _package_files():
    here = Path(__file__).resolve().parent
    return [Path(__file__).resolve(), here / 'workload_chains.py', *sorted((here / 'fixtures' / 'workload_chains').glob('*.json'))]


def test_no_fixture_names_a_benchmark_paper_or_person():
    """Acceptance 4: identifier shapes and blocked-term digests over every file of this package."""
    findings = {}
    for path in _package_files():
        text = path.read_text()
        if path == Path(__file__).resolve():
            text = text.split('BLOCKED = frozenset', 1)[0] + text.split('})\n', 1)[1]
        found = scan_text(text)
        if found:
            findings[path.name] = found
    assert findings == {}


def test_the_r10_scan_detects_a_planted_identifier():
    import hashlib
    planted_term = 'planted' + 'identity'
    assert scan_text('see ' + 'ar' + 'Xiv:' + '2101.' + '00001 for the target') != []
    assert scan_text(f'a fixture named {planted_term}', frozenset({hashlib.sha256(planted_term.encode()).hexdigest()})) != []
    assert scan_text('a synthetic sibling with generic operations') == []
