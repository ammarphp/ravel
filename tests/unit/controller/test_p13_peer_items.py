"""Reviewer obligations survive computed-check filtering in the exact P04 handoff."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

from ravel.validation.higgs_checks import REVIEWER_ITEMS as SCALAR_ITEMS
from ravel.workflow import review_projection_checks as rpc, role_registry

ROOT = Path(__file__).resolve().parents[3]
PATCH = ROOT / 'tests/fixtures/peer_contracts/review-items.patch'


def _ctx(state):
    return state.get('context') or {}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _subject(adopted):
    # Exact peer helper: retain the real subject assembly while faking store boundaries.
    artifacts = sorted(({'artifact': r['artifact'], 'sha256': r['sha256']} for r in adopted),
                       key=lambda r: r['artifact'])
    return {'artifacts': artifacts, 'sha256': digest(artifacts)}


@pytest.fixture
def reviewer_items(tmp_path):
    lines = PATCH.read_text().splitlines(keepends=True)
    header = next(i for i, line in enumerate(lines) if line.startswith('@@'))
    match = re.match(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', lines[header])
    old_start, old_count, new_start, new_count = map(int, match.groups())
    body = lines[header + 1:]
    before = [line[1:] for line in body if line[:1] in (' ', '-')]
    assert len(before) == old_count
    copied = tmp_path / 'peer'
    path = copied / 'src/ravel/controller/step/graph.py'
    path.parent.mkdir(parents=True)
    path.write_text('\n' * (old_start - 1) + ''.join(before))
    applied = subprocess.run(['patch', '--batch', '-p1', '-d', str(copied), '-i', str(PATCH)],
                             capture_output=True, text=True, check=False)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert 'fuzz' not in applied.stdout
    source = ''.join(path.read_text().splitlines(keepends=True)[new_start - 1:new_start - 1 + new_count])
    class StepHold(ValueError):
        def __init__(self, code, message, **kwargs):
            super().__init__(message)
            self.code = code

    def harness(role, *, explicit=(), error=None):
        producer = role_registry.load(role)
        roles = producer['reviewed_by']
        assert roles  # This case exercises an actually owed review seat.
        required = set(producer['must_check']) & rpc.reviewer_items()
        existing_check = sorted(required)[0] if required else 'check:fictional-existing'
        existing = [{'id': 'manifest:authored-unit', 'kind': 'manifest', 'text': 'Preserve this authored obligation.'},
                    {'id': 'must_check:' + existing_check, 'kind': 'must_check', 'check': existing_check,
                     'source': 'authored reviewer item'}]
        calls = []
        def instructions_items(manifest, reviewer):
            calls.append((manifest, reviewer['id']))
            if error is not None:
                raise error('reviewer manifest unavailable')
            return existing
        namespace = {'deepcopy': deepcopy, 'StepHold': StepHold, '_ctx': _ctx, '_subject': _subject,
                     '_store': lambda state: object(), '_card': lambda state: producer,
                     '_seat_roles': lambda store, step, card, ctx: list(roles),
                     'cards': SimpleNamespace(resolve=lambda role, pin: (role_registry.load(role), None, None)),
                     'module': lambda name: SimpleNamespace(reviewer_items=instructions_items)}
        exec(compile(source, str(path), 'exec'), namespace)
        state = {'branch': 'worker', 'card': {'registry_sha256': 'a' * 64}, 'step': {'id': 'fictional-step'},
                 'packet': {'manifest': {'units': [{'id': 'fictional-unit'}]}},
                 'checks': {'accepted': [{'artifact': 'producer:outputs/result.json', 'sha256': 'b' * 64}],
                            'reviewer_items': list(explicit)},
                 'observation': {'session_id': 'fictional-producer-session'}}
        return namespace['review_items'], state, producer, existing, calls, StepHold
    return harness


@pytest.mark.parametrize('role,expected', [
    ('ml-planner', rpc.ML_REVIEWER_ITEMS),
    ('extended-scalar-modeler', SCALAR_ITEMS),
])
def test_CF12_producer_reviewer_items_survive_when_the_computed_check_list_omits_them(
        reviewer_items, role, expected):
    run, state, card, existing, calls, _ = reviewer_items(role)
    before = deepcopy(existing)
    required = set(card['must_check']) & rpc.reviewer_items()
    assert required == set(expected)
    for seats in (run(state), run(state)):
        assert [seat['role'] for seat in seats] == card['reviewed_by']
        for seat in seats:
            ids = [item['id'] for item in seat['items']]
            assert len(ids) == len(set(ids))
            assert {'must_check:' + check for check in expected} <= set(ids)
            assert seat['items'][:len(before)] == before
            for item in seat['items'][len(before):]:
                assert item == {'id': 'must_check:' + item['check'], 'kind': 'must_check',
                                'check': item['check'], 'source': 'producer reviewer obligation'}
            assert seat['producer'] == {'session_id': 'fictional-producer-session', 'role': role}
            assert seat['subject']['artifacts'] == state['checks']['accepted']
    assert existing == before
    assert len(calls) == 2 * len(card['reviewed_by'])


def test_CF12_computed_check_reviewer_items_are_unioned_into_each_seat_without_duplicates(reviewer_items):
    extra = 'check:fictional-additional-review-obligation'
    run, state, card, _, _, _ = reviewer_items('ml-planner', explicit=[rpc.ML_REVIEWER_ITEMS[0], extra, extra])
    for seat in run(state):
        ids = [item['id'] for item in seat['items']]
        assert len(ids) == len(set(ids))
        assert 'must_check:' + extra in ids
        assert {'must_check:' + check for check in rpc.ML_REVIEWER_ITEMS} <= set(ids)
    assert len(run(state)) == len(card['reviewed_by'])


@pytest.mark.parametrize('error', [KeyError, ValueError])
def test_CF12_reviewer_manifest_failure_holds_instead_of_dropping_all_items(reviewer_items, error):
    run, state, _, _, calls, StepHold = reviewer_items('ml-planner', error=error)
    with pytest.raises(StepHold) as held:
        run(state)
    assert held.value.code == 'reviewer_items_unavailable'
    assert 'reviewer manifest unavailable' in str(held.value)
    assert len(calls) == 1
