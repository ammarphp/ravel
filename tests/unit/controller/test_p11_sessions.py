"""Research XF04: family labels never substitute for separate observed seats."""
from copy import deepcopy

import pytest

from ravel.workflow import research_coordinator_decisions as decisions, transport_registry


def receipt(identity, model='opaque-model'):
    return {'transport': {'actor_id': 'actor-' + identity, 'invocation_id': 'session-' + identity,
                          'observed_model': model},
            'context_manifest_sha256': identity * 64, 'context_transport_separated': True}


@pytest.mark.parametrize('stage', ['screen', 'validate', 'acceptance'])
def test_XF04_same_family_R2_stage_proceeds_only_with_observed_separation(stage):
    assignments = {'producer-seat': {'kind': 'producer'}, 'critic-seat': {'kind': 'reviewer'}}
    models = {role: 'gpt-5' for role in assignments}
    prepared = decisions.dispatch_check(stage, assignments, models=models)
    assert prepared['critic-seat']['session_check'] == 'pending'
    assert prepared['critic-seat']['family_label'] == 'pending separation, same model family'
    actual = decisions.dispatch_check(stage, assignments, models=models,
        receipts={'producer-seat': receipt('a'), 'critic-seat': receipt('b')})
    assert actual['critic-seat']['session_check'] == 'distinct'
    assert actual['critic-seat']['family_label'] == 'separate session, same model family'


@pytest.mark.parametrize('shared', ['actor', 'session', 'packet', 'missing', 'transcript'])
def test_XF04_same_family_does_not_waive_actor_session_or_packet_separation(shared):
    assignments = {'producer-seat': {'kind': 'producer'}, 'critic-seat': {'kind': 'reviewer'}}
    receipts = {'producer-seat': receipt('a'), 'critic-seat': receipt('b')}
    critic = receipts['critic-seat']
    if shared == 'actor':
        critic['transport']['actor_id'] = receipts['producer-seat']['transport']['actor_id']
    elif shared == 'session':
        critic['transport']['invocation_id'] = receipts['producer-seat']['transport']['invocation_id']
    elif shared == 'packet':
        critic['context_manifest_sha256'] = receipts['producer-seat']['context_manifest_sha256']
    elif shared == 'missing':
        del critic['transport']['invocation_id']
    else:
        critic['context_transport_separated'] = False
    before = deepcopy(receipts)
    with pytest.raises(transport_registry.TransportRefusal, match='actor|session|packet'):
        decisions.dispatch_check('screen', assignments, models={role: 'gpt-5' for role in assignments},
                                 receipts=receipts)
    assert receipts == before


def test_XF04_unknown_family_keeps_observation_unknown_after_real_separation():
    assignments = {'producer-seat': {'kind': 'producer'}, 'critic-seat': {'kind': 'reviewer'}}
    actual = decisions.dispatch_check('screen', assignments, models={role: 'opaque-model' for role in assignments},
        receipts={'producer-seat': receipt('a'), 'critic-seat': receipt('b')})
    assert actual['critic-seat']['family_check'] == 'unknown'
    assert actual['critic-seat']['session_check'] == 'distinct'
