"""UNRUN source-review witnesses; all model/review receipts are explicit stand-ins.

These exercise the ordinary author/collect/revision API. They establish no
scientific review, provider use or native execution. Root alone may run them.
"""
from copy import deepcopy
import pytest
from ravel.workflow import manuscript_workflow as mw, manuscript_production as mp
from ravel.workflow import scientific_judgment
from test_staged_manuscript_authoring import revision_case, revision_completed, revision_review

OBJECTION = {'verdict': 'send_back', 'audit': {
    'nodes': [{'id': 'material-method', 'decision': 'unresolved', 'assumptions': []}], 'edges': []}}


def _ready(tmp_path, monkeypatch):
    """An actual campaign journal with the author call charged to its ledger.

    Revision preparation commits its allocation to the original campaign and
    binds each review by contract, receipt and value. The reviews here are
    located explicit synthetic records with all three parts.
    """
    req, document, production, state, final = revision_case(tmp_path, monkeypatch)
    campaign = tmp_path / 'campaign'
    binding = mp.prepare_writer(production, tmp_path / 'writer',
                                base_dir=tmp_path, campaign=campaign)
    revision_completed({'binding': binding}, state, final, monkeypatch, {})
    result = mp.collect(binding, tmp_path / 'note')
    monkeypatch.setattr(mw.integrity, 'assess',
                        lambda *a, **k: {'complete_actual_independent_roles': True})
    monkeypatch.setattr(mw.integrity, 'assessment_pins', lambda *a, **k: [])
    monkeypatch.setattr(scientific_judgment, 'verify_binding',
                        lambda role: revision_review(tmp_path, role, deepcopy(OBJECTION)))
    return result, campaign, state


def test_original_campaign_remains_a_valid_revision_baseline(tmp_path, monkeypatch):
    result, campaign, state = _ready(tmp_path, monkeypatch)
    budget = {'calls': 1, 'output_tokens': 4096, 'wall_seconds': 60,
              'native_attempts': 0}
    before = mw.cycle._load(campaign)[1]
    prepared = mw.prepare_revision(result['package_pin'],
        ['critic', 'verifier', 'synthesizer'], tmp_path / 'revision',
        base_dir=tmp_path, campaign=campaign, budget=budget)
    revision = mw._read(prepared['revision'], tmp_path)
    assert revision['campaign'] == str(campaign.absolute())
    assert revision['remaining_budget'] == budget
    assert revision['unresolved'] == revision['objections']
    assert not revision['execution_authorized']
    assert not revision['scientific_acceptance']
    # The allocation is one commitment in the original journal, bound to the reviewed criticism.
    current = mw.cycle._load(campaign)[1]
    allocation = current['events'][-1]
    assert current['revision'] == before['revision'] + 1 and current['parent_sha256'] == before['sha256']
    assert allocation['kind'] == 'manuscript_revision_allocated' and allocation['budget'] == budget
    assert allocation['preparation_state_sha256'] == before['sha256']
    assert revision['campaign_state_sha256'] == current['sha256']
    assert len(revision['objections']) == 3 and {row['role'] for row in revision['objections']} == {'critic', 'verifier', 'synthesizer'}
    package = mw._read(result['package_pin'], tmp_path)
    assert allocation['criticism_sha256'] == mw._criticism_identity(package, ['critic', 'verifier', 'synthesizer'], tmp_path)


@pytest.mark.parametrize('same_context', [False, True])
def test_revision_cannot_borrow_a_fresh_campaign_budget(tmp_path, monkeypatch, same_context):
    result, campaign, state = _ready(tmp_path, monkeypatch)
    foreign = tmp_path / 'foreign-campaign'
    foreign.mkdir()
    fresh = deepcopy(state)
    fresh['resource_ledger'] = []
    fresh['contract']['budget'] = {'calls': 100, 'output_tokens': 1000000,
                                 'wall_seconds': 100000, 'native_attempts': 100}
    if not same_context:
        fresh['context'] = {'unrelated': 'explicit synthetic foreign context'}
    original_load = mw.cycle._load
    monkeypatch.setattr(mw.cycle, '_load',
        lambda root: (foreign, fresh) if str(root) == str(foreign)
        else original_load(root))
    # The A package/review positive above is valid under its disclosed fixture.
    # This B request must fail for original-campaign ownership even if B copied
    # the same context and has ample current allowance; no budget reset is valid.
    with pytest.raises(ValueError, match='campaign'):
        mw.prepare_revision(result['package_pin'], ['critic', 'verifier', 'synthesizer'],
            tmp_path / 'foreign-revision', base_dir=tmp_path, campaign=foreign,
            budget={'calls': 1, 'output_tokens': 4096, 'wall_seconds': 60,
                    'native_attempts': 0})
    assert not (tmp_path / 'foreign-revision').exists()
