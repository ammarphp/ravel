"""Older current bindings are live; fully replaced historical bindings are not."""
import json
from pathlib import Path
import pytest
from ravel.workflow import research_cycle as cycle
from test_research_knowledge import setup, request, experiment, write, MAPPING


@pytest.mark.parametrize('changed', ['knowledge', 'request'])
def test_disjoint_successor_keeps_older_active_context_bound(tmp_path, changed):
    root, old_pin, _ = setup(tmp_path)
    cycle.design(root, experiment(tmp_path, 'old-flux', grouped=False, premise_ids=['flux-fixed']))
    second = request(tmp_path, identity='v2')
    obj = json.loads(Path(second['path']).read_text())
    obj['query'].update(text='zzunmatched', tags=[], roots=['rival'], domain=['absent-domain'])
    second = write(tmp_path / 'v2-request.json', obj)
    cycle.bind_knowledge(root, second, premise_map={'rival': 'new-rival'}, reason='Separate exploratory context.')
    assert cycle.select(root)['selected'] == 'old-flux'
    old = json.loads(Path(old_pin['path']).read_text())
    target = Path(old['knowledge']['path'] if changed == 'knowledge' else old_pin['path'])
    obj = json.loads(target.read_text())
    if changed == 'knowledge':
        obj['nodes'][0]['conventions'] = ['changed original convention']
    else:
        obj['query']['domain'] = ['changed original domain']
    write(target, obj)
    with pytest.raises(ValueError):
        cycle.select(root)


def test_fully_superseded_history_does_not_veto_current_selection(tmp_path):
    root, old_pin, original = setup(tmp_path)
    cycle.design(root, experiment(tmp_path, 'old-flux', grouped=False, premise_ids=['flux-fixed']))
    new_pin = request(tmp_path, identity='v2', extra=True)
    state = cycle.bind_knowledge(root, new_pin, premise_map=MAPPING, reason='Explicit immutable applicability successor.')
    assert state['knowledge_bindings'][0] == original['knowledge_bindings'][0]
    old = json.loads(Path(old_pin['path']).read_text())
    write(Path(old['knowledge']['path']), {'historical_source_now_unavailable': True})
    assert cycle.select(root)['selected'] is None
    assert cycle._load(root)[1]['experiments'][0]['applicability_reopened']
