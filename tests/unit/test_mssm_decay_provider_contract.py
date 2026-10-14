"""Pure source/card/table contract checks; no compiler or physics provider calls."""
from copy import deepcopy
from fractions import Fraction
import pytest
from ravel.physics import spheno_mssm as spheno,chargino_decay_table as table

def explicit_card():
    # Artificial software-control numbers; not the original81 physical input.
    r={'MODSEL':{i:'0' for i in (1,4,5,6)},'SMINPUTS':{i:'1' for i in spheno.SM},'VCKMIN':{1:'.2',2:'.8',3:'.1',4:'0'},'MINPAR':{3:'50'},'EXTPAR':{i:'1000' for i in spheno.EXTPAR},'SPHENOINPUT':{i:'0' for i in spheno.SETTINGS}}
    r['SMINPUTS'].update({8:'0',12:'0',14:'0'});r['EXTPAR'].update({0:'1500',1:'-200',23:'-150',24:'1000000'})
    r['SPHENOINPUT'].update({1:'-1',11:'1',34:'1e-5',35:'40',37:'1',38:'1',40:'137',41:'2.4',42:'2.0',80:'1'})
    return ''.join('BLOCK '+b+'\n'+''.join(' '+str(k)+' '+v+'\n' for k,v in rows.items()) for b,rows in r.items()).encode()

def test_external_card_units_signs_and_no_adapter_defaults():
    d=spheno.input_witness(explicit_card());assert d['literal_rows']['EXTPAR'][0]=='1500' and d['literal_rows']['EXTPAR'][31]=='1000'
    assert d['literal_rows']['EXTPAR'][24]=='1000000' and d['literal_rows']['EXTPAR'][23]=='-150' and not d['adapter_defaults_selected']

@pytest.mark.parametrize('extra',[b'BLOCK MASS\n 1000022 1\n',b'BLOCK IMEXTPAR\n 1 .1\n',b'BLOCK EXTPAR\n 23 1\n'])
def test_no_hidden_spectrum_phase_or_duplicate_branch(extra):
    with pytest.raises(ValueError):spheno.input_witness(explicit_card()+extra)

def test_complete_author_table_exact_pure_factor_and_overlap():
    _,t=table.population();assert (len(t['columns']),len(t['rows']),t['unique_coordinates'],t['duplicate_rows'])==(13,3794,3654,140)
    d={'basis':'pure_higgsino_single_neutralino_normalization','chargino_mass_GeV':'200','neutralinos':[{'id':'n1','mass_difference_GeV':'.2'}]}
    a=table.calculate(d,t);b=table.calculate({**d,'basis':'pure_wino_four_times_normalization'},t)
    q=lambda r:Fraction(**r['total_width_exact_GeV'])
    assert q(b)==4*q(a) and not a['inclusive_exclusive_double_counting_performed'] and not a['uncertainty_assigned']
    assert t['overlap']['contained_exclusive_columns']==[7,8,9]

def test_table_offgrid_refuses_interpolation():
    _,t=table.population()
    with pytest.raises(ValueError,match='no interpolation'):
        table.calculate({'basis':'pure_higgsino_single_neutralino_normalization','chargino_mass_GeV':'201','neutralinos':[{'id':'n1','mass_difference_GeV':'.2'}]},t)
