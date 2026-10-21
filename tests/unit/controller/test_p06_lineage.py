"""Amendment lineage keeps historical evidence without granting historical effects."""
import pytest
from test_p06_support import autonomous, frozen_store, operator_home, view
from test_p06_request import ci1, go, effect, PLAN_A, PLAN_B
from ravel.controller import authority as a


def amend(store, approval, previous, following, events):
    return a.request(store, 'deviation', {
        'view': view(store, 'deviation', approve_plan=approval['id'],
                     plan_sha256=following, previous_plan_sha256=previous),
        'change': {'parameter': 'tolerance', 'from': previous, 'to': following,
                   'why': 'tighten precision', 'touches': ['s01'], 'direction': 'tighten'}},
        {'rung': 'full', 'stages': ['derive'], 'budget': {'events': events}})


def test_F05_old_plan_effect_is_rejected_but_amendment_chain_remains_usable(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    old_go = go(store, approval)
    assert a.authorize_effect(store, effect('smoke', stage='derive', budget={'events': 1}))
    first = amend(store, approval, PLAN_A, PLAN_B, 10)
    with pytest.raises(a.AuthorityRefused):
        a.authorize_effect(store, effect('smoke', stage='derive', budget={'events': 1}))
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, old_go['id'], kind='go')
    assert a.authorize_effect(store, effect('smoke', plan_sha256=PLAN_B, stage='derive', budget={'events': 10}))
    third = 'd'*64
    second = amend(store, approval, PLAN_B, third, 4)
    assert a.authorize_effect(store, effect('smoke', plan_sha256=third, stage='derive', budget={'events': 4}))
    with pytest.raises(a.AuthorityRefused):
        a.authorize_effect(store, effect('smoke', plan_sha256=PLAN_B, stage='derive', budget={'events': 1}))
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, first['id'], kind='deviation')
    with pytest.raises(a.AuthorityRefused):
        a.authorize_effect(store, effect('smoke', plan_sha256=third, stage='derive', budget={'events': 5}))
