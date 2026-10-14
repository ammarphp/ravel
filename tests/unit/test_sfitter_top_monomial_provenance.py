"""Supplied parser projections preserve last-value semantics and every source term."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from source_record_fixtures import reviewed,write,defect_registry
from test_reviewed_source_records import synthetic_card
from ravel.physics import sfitter_card_derivation as derivation


def selected(tmp):
    card=synthetic_card(2);cp=tmp/'ANA-0001.json';cpin=write(cp,card)
    law=tmp/'reader.txt';law.write_text('Fictional reviewed last-value parser law')
    import hashlib
    registry=defect_registry(tmp,card)
    transform={'operation':'project-last','path':'/predictions/0/modifiers','key':'name','expected':card['predictions'][0]['modifiers']}
    manifest=reviewed(tmp,'repair-manifest',{'card':cpin,'evaluator':{'path':str(law),'sha256':hashlib.sha256(law.read_bytes()).hexdigest()}},
        card_source='card',defect_registry=registry,identity_template='{identity}_{row}',transforms=[transform])
    return card,cp,law,manifest,write(tmp/'manifest.json',manifest)


def test_last_value_projection_has_same_parser_output_and_full_lineage(tmp_path):
    original,cp,_,_,binding=selected(tmp_path)
    card,proof=derivation.derive(tmp_path,cp.name,binding)
    parse=lambda terms:{m['name']:m['data'] for m in terms}
    assert parse(original['predictions'][0]['modifiers'])==parse(card['predictions'][0]['modifiers'])
    assert proof['changes'][0]['before']==original['predictions'][0]['modifiers']
    assert proof['changes'][0]['after']==card['predictions'][0]['modifiers']
    assert proof['original_bins']==proof['derived_bins']==2 and proof['physics_validated'] is False
    assert json.loads(cp.read_text())==original


@pytest.mark.parametrize('mutation',['earlier','later','new_duplicate','evaluator','population'])
def test_projection_refuses_changed_source_or_unreviewed_population(tmp_path,mutation):
    original,cp,law,_,binding=selected(tmp_path)
    if mutation=='evaluator':law.write_text('other law')
    else:
        if mutation=='earlier':original['predictions'][0]['modifiers'][0]['data']=[1.]
        elif mutation=='later':original['predictions'][0]['modifiers'][2]['data']=[1.]
        elif mutation=='new_duplicate':original['predictions'][0]['modifiers'].append(deepcopy(original['predictions'][0]['modifiers'][0]))
        else:original['observations'].pop()
        cp.write_text(json.dumps(original))
    with pytest.raises(ValueError,match='bytes changed'):derivation.derive(tmp_path,cp.name,binding)


def test_projection_without_manifest_is_a_typed_refusal(tmp_path):
    with pytest.raises(ValueError) as error:derivation.derive(tmp_path,'ANA-0002.json')
    assert error.value.reason=='missing_repair_manifest'
