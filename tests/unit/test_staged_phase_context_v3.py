"""Actual phase-context producer/consumer regression; inherited inert role transport.
No model/provider/native outcome is claimed. Root exclusively executes controls.
"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from ravel.workflow import manuscript_workflow as mw, manuscript_production as mp
from test_staged_manuscript_authoring import consumed_story


def test_prepared_phase_context_contains_complete_current_products(tmp_path, monkeypatch):
    story, req, document, production, state, final, registry = consumed_story(tmp_path, monkeypatch)
    prepared = mw.prepare_phase(story, 'phase1', tmp_path/'workflow/issued/phase1',
                 base_dir=tmp_path, campaign=tmp_path/'campaign', prior_products=[story])
    binding = prepared['binding']
    context = mw._read(binding['presentation'], tmp_path)
    actual = mw.verify_product(story, base_dir=tmp_path, campaign=tmp_path/'campaign')
    assert binding['prior_products'] == [story]
    assert context['prior_actual_products'] == [actual]
    assert context['prior_actual_products'][0]['actual_receipt'] == actual['actual_receipt']
    assert context['prior_actual_products'][0]['actual_usage'] == actual['actual_usage']
    assert context['prior_actual_products'][0]['input_pins'] == actual['input_pins']
    assert mw.consumption_destination(prepared, base_dir=tmp_path) == tmp_path/'workflow/issued/phase1/consumed'


@pytest.mark.parametrize('fault', ['pins-only', 'omitted', 'changed-product'])
def test_rehashed_phase_context_cannot_drop_or_replace_current_product_contents(tmp_path, monkeypatch, fault):
    story, req, document, production, state, final, registry = consumed_story(tmp_path, monkeypatch)
    prepared = mw.prepare_phase(story, 'phase1', tmp_path/'workflow/issued/phase1',
                 base_dir=tmp_path, campaign=tmp_path/'campaign', prior_products=[story])
    binding = deepcopy(prepared['binding'])
    context = mw._read(binding['presentation'], tmp_path)
    if fault == 'pins-only': context['prior_actual_products'] = [story]
    elif fault == 'omitted': context['prior_actual_products'] = []
    else: context['prior_actual_products'][0]['output']['claim_map'][0]['text'] = 'Foreign claim.'
    presentation = Path(binding['presentation']['path'])
    presentation.write_text(json.dumps(context))
    binding['presentation'] = mp._pin(presentation)
    saved = Path(binding['graph']).parent/'binding.json'
    saved.write_text(json.dumps(binding))
    changed = {'binding': binding, 'binding_pin': mp._pin(saved), 'execution_authorized': False}
    with pytest.raises(ValueError, match='^phase changed full retained source/plan/dependency context$'):
        mw.consumption_destination(changed, base_dir=tmp_path)
    assert not (saved.parent/'consumed').exists()
