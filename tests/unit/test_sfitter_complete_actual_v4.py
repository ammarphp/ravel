"""Reviewed source explanations use supplied locators and exact pinned bytes."""
import hashlib
from pathlib import Path
import pytest
from source_record_fixtures import reviewed,write,defect_registry
from test_reviewed_source_records import synthetic_card
from ravel.physics import sfitter_card_derivation as derivation


def supplied(tmp):
    card=synthetic_card(1);cp=tmp/'ANA-0001.json';cpin=write(cp,card)
    note=tmp/'notes.txt';note.write_text('header\nfictional token repair explanation\nend\n')
    registry=defect_registry(tmp,card)
    quote='fictional token repair explanation'
    evidence={'source':'note','line_start':2,'line_end':2,'quote':quote,'quote_sha256':hashlib.sha256(quote.encode()).hexdigest()}
    manifest=reviewed(tmp,'repair-manifest',{'card':cpin,'note':{'path':str(note),'sha256':hashlib.sha256(note.read_bytes()).hexdigest()}},
        card_source='card',defect_registry=registry,identity_template='{identity}_{row}',
        transforms=[{'operation':'replace','path':'/predictions/0/modifiers/0/name','expected':'a','value':'c','evidence':evidence}])
    binding=write(tmp/'manifest.json',manifest)
    return cp,note,manifest,binding


def test_source_explanation_and_original_coefficient_are_retained(tmp_path):
    cp,_,manifest,binding=supplied(tmp_path)
    card,proof=derivation.derive(tmp_path,cp.name,binding)
    assert card['predictions'][0]['modifiers'][0]=={'name':'c','data':[2.]}
    assert proof['changes'][0]['evidence']==manifest['transforms'][0]['evidence']


@pytest.mark.parametrize('mutation',['bytes','line','quote','digest'])
def test_changed_note_locator_or_explanation_refuses(tmp_path,mutation):
    cp,note,manifest,binding=supplied(tmp_path)
    if mutation=='bytes':note.write_text('changed note')
    elif mutation=='line':manifest['transforms'][0]['evidence']['line_start']=1
    elif mutation=='quote':manifest['transforms'][0]['evidence']['quote']='invented'
    else:manifest['transforms'][0]['evidence']['quote_sha256']='0'*64
    binding=write(tmp_path/'manifest.json',manifest)
    with pytest.raises(ValueError):derivation.derive(tmp_path,cp.name,binding)
