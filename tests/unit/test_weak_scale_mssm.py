"""Bounded source input law; synthetic complete cards are not physical points."""
from copy import deepcopy
import pytest
from ravel.physics import weak_scale_mssm as weak, model_specific_spectrum as named


def complete_card():
    lines=['BLOCK MINPAR',' 3 10','BLOCK HMIXIN',' 1 -150',' 101 10000',
        'BLOCK MSOFTIN',' 1 200',' 2 200',' 3 2000','BLOCK MODSEL',' 6 0',' 12 0','BLOCK SMINPUTS']
    lines += [f' {i} 1' for i in weak.SM_INPUTS]
    lines += ['BLOCK FLEXIBLESUSY']+[f' {i} '+('1e-4' if i==0 else '1' if i==23 else '0') for i in range(33)]
    for block in weak.MATRICES:
        lines += ['BLOCK '+block]+[f' {i} {j} '+('10000' if i==j else '0') for i in range(1,4) for j in range(1,4)]
    return ('\n'.join(lines)+'\n').encode()


def test_complete_lowmssm_input_has_no_defaults_or_decays():
    witness=weak.input_witness(complete_card(),False,'none')
    assert len(witness['parameters'])==129
    assert witness['input_defaults_selected_by_adapter'] is False
    assert witness['decay_implementation_available'] is False


@pytest.mark.parametrize('block',['MINPAR','HMIXIN','MSOFTIN',*weak.MATRICES,'MODSEL','SMINPUTS','FLEXIBLESUSY'])
def test_missing_full_parameter_family_refuses_native_defaults(block):
    raw=complete_card().decode();parts=raw.split('BLOCK ')
    raw='BLOCK '.join(p for p in parts if not p.startswith(block+'\n')).encode()
    with pytest.raises(ValueError):weak.input_witness(raw,False,'none')


@pytest.mark.parametrize('tail',[b'BLOCK IMHMIXIN\n 1 1\n',b'BLOCK EXTPAR\n 23 150\n',
    b'BLOCK FLEXIBLEDECAY\n 0 1\n',b'BLOCK VCKMIN\n 1 0.2\n'])
def test_no_ignored_alternative_model_or_decay(tail):
    with pytest.raises(ValueError):weak.input_witness(complete_card()+tail,False,'none')


def test_selected_card_changes_only_complete_authorized_four_rows():
    original=complete_card()
    bindings=[{'parameter':key,'block':block,'codes':[code]} for key,block,code in [('mu','HMIXIN',1),('m1','MSOFTIN',1),('m2','MSOFTIN',2),('ratio','MINPAR',3)]]
    changed=weak.selected_card(original,bindings,{'mu':'300','m1':'400','m2':'400','ratio':'50'})
    assert sum(a!=b for a,b in zip(original.splitlines(),changed.splitlines()))==4
    doc=named.inventory(changed)
    assert named.scalar(doc,{'block':'HMIXIN','codes':[1],'scale':None})=='300'
    assert named.scalar(doc,{'block':'MSOFTIN','codes':[1],'scale':None})=='400'
    assert named.scalar(doc,{'block':'MSOFTIN','codes':[2],'scale':None})=='400'
    assert named.scalar(doc,{'block':'MINPAR','codes':[3],'scale':None})=='50'


def test_lowmssm_width_mapping_cannot_invent_stability():
    mapping={'schema_version':2,'profile':weak.NAME,'basis':'Explicit inert test',
        'source_evidence':[{'path':'unread-fixture','sha256':'a'*64}],
        'rows':[{'parameter':'Wchi','block':'decay','codes':[1000022],'origin':'spectrum',
            'selector':{'block':'DECAY','codes':[1000022],'scale':None},'convention':'identity',
            'operation':'identity','source_unit':'GeV','target_unit':'GeV'}]}
    ext=[{'name':'Wchi','block':'decay','codes':[1000022]}]
    with pytest.raises(ValueError,match='missing'):
        named.map_card(named.inventory(b'BLOCK MASS\n 1000022 -100\n'),named.inventory(complete_card()),ext,mapping)
