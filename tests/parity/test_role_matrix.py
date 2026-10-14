"""P-3, P-12, P-14 and P-16 across every transport kind x registered role family (parity neutrality rule 3).

Every cell is either admitted or refused with the missing capability named; none is skipped or weakened.
"""
from collections import Counter

import pytest

from parity_support import STUB_KINDS, cards, cell, declarations, violations, mode_of
from ravel.workflow import transport_registry as tr


@pytest.mark.parametrize('kind', STUB_KINDS)
@pytest.mark.parametrize('qualified', [False, True], ids=['unqualified', 'qualified'])
def test_every_cell_is_admitted_or_refused_with_a_named_capability(parity_env, kind, qualified):
    documents = declarations(kind)
    assert documents, f'no declaration of kind {kind}'
    bad, tally = [], Counter()
    for document in documents:
        for card in cards():
            row = cell(card, document, qualified=qualified)
            tally[row['status']] += 1
            bad += [(card['id'], document['id'], v) for v in violations(row, card, document)]
    assert tally['admitted'] + tally['refused'] == len(documents) * len(cards())
    assert not bad, bad[:10]


def test_checker_flags_an_admission_a_declaration_cannot_support():
    document = tr.load('http-anthropic')                       # declares tools: none
    card = next(c for c in cards() if (c.get('requires') or {}).get('tools') == 'broker-full')
    forged = {'status': 'admitted', 'missing': [], 'selection': {'transport_id': document['id']}}
    assert 'admitted with fewer tools than the card requires' in violations(forged, card, document)
    assert violations({'status': 'refused', 'missing': []}, card, document)


@pytest.mark.parametrize('document', declarations('http-model') + declarations('external-relay'),
                         ids=lambda d: d['id'])
def test_tool_needing_roles_are_refused_on_tools_none_kinds(parity_env, document):
    assert document['capabilities']['tools'] == 'none'
    for card in cards():
        needs = (card.get('requires') or {}).get('tools', 'none')
        if needs == 'none':
            continue
        row = cell(card, document, qualified=True)
        assert row['status'] == 'refused' and 'tools' in row['missing'], (card['id'], document['id'], row)


def test_a_critic_block_is_placeable_only_on_tool_capable_kinds(parity_env):
    """the evidence-purchasing critic's block carries a receipt on a tool-capable kind, refused on tools-none."""
    critic = next(c for c in cards() if c['id'] == 'rdj-critic')
    by_kind = {kind: [cell(critic, d, qualified=True) for d in declarations(kind)] for kind in STUB_KINDS}
    for kind in ('http-model', 'external-relay'):
        assert all(r['status'] == 'refused' and 'tools' in r['missing'] for r in by_kind[kind])
    admitted = [r for r in by_kind['cli-worker'] if r['status'] == 'admitted']
    assert admitted and all(r['attestation_capability'] == 'transport' for r in admitted)
    # Every cli-worker cell that is not admitted names why (adapter, probe, surface, structured output ...).
    assert all(r['missing'] for r in by_kind['cli-worker'] if r['status'] == 'refused')


@pytest.mark.xfail(strict=True, reason="defect: read_qualification and effective_capabilities "
                   "treat only CLI kinds as qualifiable, so no ravel-loop declaration can reach ravel-sandbox isolation "
                   "or blind admission; the cell is refused explicitly, not weakened")
def test_a_critic_block_is_placeable_on_the_ravel_loop_kind(parity_env):
    critic = next(c for c in cards() if c['id'] == 'rdj-critic')
    rows = [cell(critic, d, qualified=True) for d in declarations('ravel-loop')]
    assert any(r['status'] == 'admitted' for r in rows), [(r['transport'], r['missing']) for r in rows]


def test_host_subagents_and_oneshots_never_carry_a_blind_or_voting_role(parity_env):
    for kind in ('host-subagent', 'cli-oneshot'):
        for document in declarations(kind):
            for card in cards():
                if (card.get('requires') or {}).get('blind') or tr.is_voting(card):
                    row = cell(card, document, qualified=True)
                    assert row['status'] == 'refused', (card['id'], document['id'])


def test_qualification_never_removes_an_admission(parity_env):
    for kind in STUB_KINDS:
        for document in declarations(kind):
            for card in cards():
                before = cell(card, document, qualified=False)
                after = cell(card, document, qualified=True)
                assert before['status'] != 'admitted' or after['status'] == 'admitted', (card['id'], document['id'])


def test_local_only_refuses_every_cli_and_host_route_and_any_non_loopback_http(parity_env):
    """P-12 across kinds: with a local-model constraint nothing but a loopback, locally billed route is placed."""
    card = next(c for c in cards() if c['id'] == 'consult-columnar')
    for document in declarations():
        row = cell(card, document, qualified=True, local_models=[tr_model(document)])
        if document['transport_kind'] in tr.CLI_KINDS + ('host-subagent',):
            assert row['status'] == 'refused', document['id']
        elif row['status'] == 'admitted':
            assert document['billing'] == 'local' and tr.is_loopback(document['endpoint']), document['id']


def tr_model(document):
    from parity_support import _model_for
    return _model_for(document)


def test_modes_cover_every_registered_card():
    assert {mode_of(c) for c in cards()} <= {'voting', 'blocking', 'advisory'}
    assert Counter(mode_of(c) for c in cards())['voting'] >= 1
