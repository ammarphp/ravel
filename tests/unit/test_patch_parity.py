"""Structural controls using synthetic released patch siblings."""
from copy import deepcopy
import json
from pathlib import Path

import jsonpatch
import pytest

FIXTURES = Path(__file__).parents[1] / 'fixtures/statistics-core'


def operands():
    background = json.loads((FIXTURES / 'background.json').read_text())
    patchset = json.loads((FIXTURES / 'patchset.json').read_text())
    produced = jsonpatch.apply_patch(background, deepcopy(patchset['patches'][0]['patch']))
    return background, patchset, produced


def check(background, patchset, produced, **kwargs):
    from ravel.validation.patch_parity import patch_parity
    return patch_parity(background, patchset, produced, patch_name='nominal', record_id='7', **kwargs)


def test_omitted_channel_and_signal_modifier_are_both_named():
    background, patchset, produced = operands()
    produced['channels'].pop()
    produced['channels'][0]['samples'][1]['modifiers'].pop()
    result = check(background, patchset, produced)
    assert result['status'] == 'fail'
    assert any(r['channel'] == 'region_b' and r['check'] == 'missing_channel' for r in result['mismatches'])
    assert any(r.get('modifier') == 'response' and r.get('type') == 'normsys' for r in result['mismatches'])


def test_background_only_control_region_is_a_missing_signal_sample():
    background, patchset, produced = operands()
    produced['channels'][1]['samples'].pop()
    result = check(background, patchset, produced)
    assert result['status'] == 'fail'
    assert any(r['check'] == 'missing_signal_sample' and r['channel'] == 'region_b' for r in result['mismatches'])


def test_matching_released_patch_passes_with_different_signal_coefficients():
    background, patchset, produced = operands()
    produced['channels'][0]['samples'][1]['data'] = [3]
    result = check(background, patchset, produced)
    assert result['status'] == 'pass'
    assert result['mismatches'] == []
    assert result['physics_validated'] is False


@pytest.mark.parametrize('mutation,match', [
    ('record', 'record'), ('digest', 'background'), ('ambiguous', 'unique'), ('patch', 'selected')])
def test_wrong_or_ambiguous_source_is_refused(mutation, match):
    background, patchset, produced = operands()
    if mutation == 'record': patchset['metadata']['references']['hepdata'] = '8'
    if mutation == 'digest': background['observations'][0]['data'] = [21]
    if mutation == 'ambiguous': patchset['patches'].append(deepcopy(patchset['patches'][0]))
    if mutation == 'patch': patchset['patches'][0]['metadata']['name'] = 'other'
    with pytest.raises(ValueError, match=match):
        check(background, patchset, produced)


def test_modifier_type_change_and_extra_channel_are_named():
    background, patchset, produced = operands()
    produced['channels'][0]['samples'][1]['modifiers'][1]['type'] = 'histosys'
    produced['channels'].append({'name':'region_c', 'samples':[]})
    result = check(background, patchset, produced)
    assert result['status'] == 'fail'
    assert {'missing_modifier','extra_modifier','extra_channel'} <= {r['check'] for r in result['mismatches']}


def test_duplicate_channel_is_not_collapsed():
    background, patchset, produced = operands()
    produced['channels'].append(deepcopy(produced['channels'][0]))
    with pytest.raises(ValueError, match='duplicate'):
        check(background, patchset, produced)
