"""Reviewed transformations must preserve a complete paired population and original identity."""
import pytest
from ravel.physics import sfitter_card_derivation as derivation
from source_record_fixtures import reviewed,write,defect_registry
from test_reviewed_source_records import synthetic_card


def selected(tmp,transforms):
    card=synthetic_card(2);cp=tmp/'ANA-0001.json';cpin=write(cp,card)
    binding=write(tmp/'repairs.json',reviewed(tmp,'repair-manifest',{'card':cpin},card_source='card',
        defect_registry=defect_registry(tmp,card),identity_template='{identity}_{row}',transforms=transforms(card)))
    return cp,binding


def test_a_reviewed_transform_cannot_publish_unpaired_or_untraced_rows(tmp_path):
    cp,binding=selected(tmp_path,lambda card:[{'operation':'replace','path':'/observations',
        'expected':card['observations'],'value':card['observations'][:1]}])
    with pytest.raises(ValueError) as error:derivation.derive(tmp_path,cp.name,binding)
    assert error.value.reason=='source_scope_mismatch'


def test_repaired_identity_lineage_retains_original_and_corrected_id(tmp_path):
    cp,binding=selected(tmp_path,lambda card:[{'operation':'replace','path':'/'+field+'/0/ID',
        'expected':'row-0','value':'corrected'} for field in ('observations','predictions')])
    _,proof=derivation.derive(tmp_path,cp.name,binding)
    assert proof['rows'][0]['original_ID']=='row-0'
    assert proof['rows'][0]['corrected_ID']=='corrected'
