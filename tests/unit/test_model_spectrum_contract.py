"""Portable named-spectrum contract checks, no model or native invocation."""
from copy import deepcopy
import json
import pytest
from ravel.physics import model_specific_spectrum as named, generated_spectrum as engine

RAW=b'BLOCK SPINFO\n 3 retained warning\nBLOCK MASS\n 1000022 -101\nBLOCK GAUGE Q= 1000\n 1 .36\nBLOCK IMNMNMIX\n 1 1 -.2\nDECAY 25 .004\n .2 2 22 22\nBLOCK UNKNOWN\n opaque source row\n'

def source_map():
    external=[{'name':'Mchi','block':'mass','codes':[1000022]},
              {'name':'gY','block':'gauge','codes':[1]},
              {'name':'Wh','block':'decay','codes':[25]}]
    rows=[{'parameter':r['name'],'block':r['block'],'codes':r['codes'],
        'origin':'spectrum','selector':{'block':r['block'],'codes':r['codes'],
        'scale':'1000' if r['block']=='gauge' else None},
        'convention':'Explicit synthetic identity, not a physical map',
        'unit':'dimensionless' if r['block']=='gauge' else 'GeV'} for r in external]
    for r in rows:
        unit=r.pop('unit');r.update(operation='identity',source_unit=unit,target_unit=unit)
    mapping={'schema_version':2,'profile':named.NAME,'basis':'Synthetic source control',
             'source_evidence':[{'path':'source-reference','sha256':'a'*64}],'rows':rows}
    return external,mapping

def test_full_return_keeps_signed_scaled_opaque_and_diagnostic_rows():
    doc=named.inventory(RAW)
    assert ''.join(doc['original_lines']).encode()==RAW
    assert named.scalar(doc,{'block':'MASS','codes':[1000022],'scale':None})=='-101'
    assert doc['sections'][-1]['rows'][0]['kind']=='opaque'
    assert len(doc['all_info_rows'])==1 and doc['missing_channels_are_unknown']
    assert doc['physics_validated'] is False

@pytest.mark.parametrize('selector',[
    {'block':'GAUGE','codes':[1],'scale':None},
    {'block':'DECAY','codes':[1000022],'scale':None},
    {'block':'UNKNOWN','codes':[1],'scale':None}])
def test_no_missing_default_scale_or_width_inference(selector):
    with pytest.raises(ValueError,match='missing'):
        named.scalar(named.inventory(RAW),selector)

def test_complete_identity_card_retains_signed_mass_and_actual_width():
    ext,mapping=source_map();raw,rows=named.map_card(named.inventory(RAW),named.inventory(RAW),ext,mapping)
    assert b'1000022 -101' in raw and b'DECAY 25 .004' in raw
    assert len(rows)==3 and rows[1]['value']=='.36'

@pytest.mark.parametrize('change',['missing','duplicate','wrong-name','default-width','native-error'])
def test_material_population_and_native_error_refusals(change):
    ext,mapping=source_map();doc=named.inventory(RAW)
    if change=='missing':mapping['rows'].pop()
    if change=='duplicate':mapping['rows'].append(deepcopy(mapping['rows'][0]))
    if change=='wrong-name':mapping['rows'][0]['parameter']='another_basis'
    if change=='default-width':mapping['rows'][-1]['origin']='input'
    if change=='native-error':doc=named.inventory(RAW+b'BLOCK SPINFO\n +4 native error\n')
    with pytest.raises(ValueError):named.map_card(doc,named.inventory(RAW),ext,mapping)

def test_direct_cli_preserves_named_source_description(tmp_path,monkeypatch):
    from ravel.workflow import science
    config=tmp_path/'config.json';config.write_text('{}')
    policy=tmp_path/'policy.json';policy.write_text(json.dumps({'policy':{'max_redos':0}}))
    monkeypatch.setattr(engine,'inputs',lambda *a:[])
    monkeypatch.setattr(engine,'_load',lambda *a:(config,{'schema_version':2,'source':'Exact supplied NMSSM source point'}))
    observed=[]
    monkeypatch.setattr(science,'plan',lambda root,spec:observed.append(json.loads(spec.read_text())))
    assert engine.main(['--config',str(config),'--rundir',str(tmp_path/'run'),'--review-policy',str(policy)])==0
    assert observed[0]['source']=='Exact supplied NMSSM source point'
    assert observed[0]['approval_mode']=='physicist' and observed[0]['max_attempts']==1

