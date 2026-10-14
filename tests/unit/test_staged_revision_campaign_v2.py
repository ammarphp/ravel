"""Source-authenticated revision admission; inert inherited model/review stand-ins.
Root-only software controls, not native/provider or scientific acceptance.
"""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import manuscript_workflow as mw
from test_revision_original_campaign import _ready
from test_manuscript_production import put

BUDGET = {'calls': 1, 'output_tokens': 4096, 'wall_seconds': 60, 'native_attempts': 0}
ROLES = ['critic', 'verifier', 'synthesizer']


def _replaced(monkeypatch, campaign, **changes):
    """Disclosed stand-in: a changed state served at the unchanged original campaign path.

    The journal on disk stays the actual one. Only the loader's returned state
    differs, as it would for a replaced or rewritten campaign record.
    """
    actual = mw.cycle._load
    def load(root, *args, **kwargs):
        owner, state = actual(root, *args, **kwargs)
        if Path(root).resolve() == Path(campaign).resolve():
            state = {**state, **deepcopy(changes)}
        return owner, state
    monkeypatch.setattr(mw.cycle, '_load', load)


def test_original_remaining_charge_and_context_are_retained(tmp_path, monkeypatch):
    result, campaign, state = _ready(tmp_path, monkeypatch)
    before = mw.cycle._load(campaign)[1]
    charged = mw.cycle._usage(before)
    # The author call is an actual charge on the original campaign ledger.
    assert charged['calls'] >= 1 and charged['output_tokens'] >= 1
    prepared = mw.prepare_revision(result['package_pin'], ROLES, tmp_path/'revision',
                 base_dir=tmp_path, campaign=campaign, budget=BUDGET)
    record = mw._read(prepared['revision'], tmp_path)
    package = mw._read(result['package_pin'], tmp_path)
    current = mw.cycle._load(campaign)[1]
    assert record['author_binding'] == package['author_binding']
    # One journal commitment allocates the revision. It adds no charge, opens no
    # account and leaves the original contract, ledger and context as they were.
    assert current['revision'] == before['revision'] + 1 and current['parent_sha256'] == before['sha256']
    allocation = current['events'][-1]
    assert allocation == {'revision': current['revision'], 'kind': 'manuscript_revision_allocated',
        'criticism_sha256': mw._criticism_identity(package, ROLES, tmp_path),
        'preparation_state_sha256': before['sha256'], 'usage': charged, 'budget': BUDGET}
    assert current['events'][:-1] == before['events']
    assert mw.cycle._usage(current) == charged and current['resource_ledger'] == before['resource_ledger']
    assert current['contract'] == before['contract'] and current['context'] == before['context']
    assert record['campaign_state_sha256'] == current['sha256']
    assert record['campaign_context_sha256'] == mw.ce.digest(before['context'])
    assert record['remaining_budget'] == BUDGET
    assert not record['scientific_acceptance'] and not record['execution_authorized']
    # The same criticism cannot be allocated a larger budget, and repeating it adds no commitment.
    with pytest.raises(ValueError, match='cannot replenish'):
        mw.prepare_revision(result['package_pin'], ROLES, tmp_path/'larger', base_dir=tmp_path,
                            campaign=campaign, budget={**BUDGET, 'calls': 2})
    assert mw.cycle._load(campaign)[1] == current


@pytest.mark.parametrize('fault', ['context', 'parent-prompt', 'spent-calls',
                                  'spent-wall', 'enlarged-budget', 'bool-budget'])
def test_original_campaign_context_parent_and_allowance_cannot_be_replaced(tmp_path, monkeypatch, fault):
    result, campaign, state = _ready(tmp_path, monkeypatch)
    before = mw.cycle._load(campaign)[1]
    budget = deepcopy(BUDGET)
    if fault == 'context':
        _replaced(monkeypatch, campaign, context={'foreign': 'same path, changed original quantity context'})
    elif fault == 'parent-prompt':
        _replaced(monkeypatch, campaign, parent_task={'contract': put(tmp_path, 'foreign-parent.json',
                                              {'prompt': 'A different scientific question.'})})
    elif fault in {'spent-calls', 'spent-wall'}:
        ceiling = {'calls': 20 if fault == 'spent-calls' else 0,
                   'output_tokens': 0,
                   'wall_seconds': 2000 if fault == 'spent-wall' else 0,
                   'native_attempts': 0}
        _replaced(monkeypatch, campaign, resource_ledger=[*before['resource_ledger'], {'ceiling': ceiling}])
    elif fault == 'enlarged-budget':
        budget['calls'] = before['contract']['budget']['calls'] + 1
    else:
        budget['calls'] = True
    with pytest.raises(ValueError):
        mw.prepare_revision(result['package_pin'], ROLES, tmp_path/'refused',
                            base_dir=tmp_path, campaign=campaign, budget=budget)
    assert not (tmp_path/'refused').exists()
    monkeypatch.undo()
    # A refusal commits nothing to the original journal.
    assert mw.cycle._load(campaign)[1] == before


def test_current_campaign_cannot_change_after_remaining_budget_read(tmp_path, monkeypatch):
    result, campaign, state = _ready(tmp_path, monkeypatch)
    original = mw.integrity._new
    def changing(path, value):
        pin = original(path, value)
        if Path(path).name == 'revision-obligations.json':
            # An actual later commitment in the same journal, after the allocation was read.
            mw.cycle._commit(campaign, mw.cycle._load(campaign)[1], 'synthetic_fixture')
        return pin
    monkeypatch.setattr(mw.integrity, '_new', changing)
    with pytest.raises(ValueError, match='original campaign changed'):
        mw.prepare_revision(result['package_pin'], ROLES, tmp_path/'interrupted',
                            base_dir=tmp_path, campaign=campaign, budget=BUDGET)
    assert (tmp_path/'interrupted/revision-obligations.json').is_file()
    # The failed preparation is retained evidence; it is not a returned admission.
