import copy,hashlib,json,math
from fractions import Fraction
from pathlib import Path
import pytest
from test_mssm_observable_map import fixture,change_spectrum,save,emit
from ravel.physics import mssm_observable_map as m

def test_provider_evidence_census_uses_exact_authenticated_buffer(tmp_path,monkeypatch):
 task,d=fixture(tmp_path/'inputs',grid=False);provider=Path(d['points'][0]['provider']['path'])
 body=json.loads(provider.read_bytes());declared=Path(body['source_evidence'][0]['path']);foreign=emit(tmp_path/'foreign.json',{'not_the_declared_provider_source':True})
 alternate=copy.deepcopy(body);alternate['source_evidence']=[foreign];alternate_raw=json.dumps(alternate).encode();original=m.slha.raw_file
 def substituted(path,expected=None):
  raw=original(path,expected)
  if Path(path)==provider and expected is None:return alternate_raw
  return raw
 monkeypatch.setattr(m.slha,'raw_file',substituted)
 try:result=m.compile_map(task,tmp_path)
 except ValueError:return
 pins={p['path'] for p in result['input_pins']}
 assert str(declared) in pins and str(Path(foreign['path'])) not in pins,'consumed provider source-evidence census differs from declared authenticated provider'

@pytest.mark.parametrize('phase',['real-signed','complex-positive'])
def test_exact_primary_sign_and_complex_phase_mass_and_basis(tmp_path,phase):
 task,d=fixture(tmp_path,phase,False);result=m.compile_map(task,tmp_path);p=result['points'][0]
 assert p['mixings']['UMIX']['basis']==['-i_wino_minus','higgsino_d_minus']
 assert p['mixings']['VMIX']['basis']==['-i_wino_plus','higgsino_u_plus']
 assert p['mixings']['NMIX']['rows'][1]['pdg']==1000023
 assert p['mixings']['NMIX']['rows'][1]['entries'][0]['real_exact']=='-4/5'
 assert p['mixings']['NMIX']['row_rephasing_performed'] is False
 if phase=='complex-positive':
  row=p['mixings']['NMIX']['rows'][0]['entries'];assert sum(Fraction(v['absolute_squared_exact']) for v in row)==1
 else:
  mass=next(v for v in p['full_mass_decay_inventory']['masses'] if v['pdg']==1000023);assert Fraction(mass['mass_GeV_exact'])==-150

@pytest.mark.parametrize('replacement',[b'DECAY 1000024 0',b'DECAY 1000024 2e-14',b''])
def test_total_width_never_channel_sum_or_missing_stability(tmp_path,replacement):
 task,d=fixture(tmp_path,grid=False)
 def changed(raw):
  if not replacement:return raw.replace(b'DECAY 1000024 1e-14\n .25 2 1000022 211\n',b'')
  return raw.replace(b'DECAY 1000024 1e-14',replacement)
 # For exact zero total width, retain physically absent decay channels in this source fixture.
 if replacement==b'DECAY 1000024 0':
  change_spectrum(task,d,lambda raw:changed(raw).replace(b' .25 2 1000022 211\n',b''))
 else:change_spectrum(task,d,changed)
 life=m.compile_map(task,tmp_path)['points'][0]['observables'][1]['lifetime']
 if not replacement:assert life['status']=='unknown_missing_total_width'
 elif replacement.endswith(b' 0'):assert life['status']=='stable_by_card' and life['proper_ctau_mm'] is None
 else:assert Fraction(life['proper_ctau_mm_exact'])==Fraction('0.1973269804')*Fraction(1,10**12)/Fraction('2e-14')

@pytest.mark.parametrize('attack',['dup_mass','dup_decay','dup_channel','bad_im','nonfinite','negative_scalar','wrong_scale','rpv','nmssm'])
def test_physical_representation_failures_refuse(tmp_path,attack):
 task,d=fixture(tmp_path,grid=False)
 mutate={
  'dup_mass':lambda r:r.replace(b'BLOCK MASS',b'BLOCK MASS\n 1000022 100'),
  'dup_decay':lambda r:r+b'DECAY 1000024 1e-14\n',
  'dup_channel':lambda r:r.replace(b' .25 2 1000022 211',b' .25 2 1000022 211\n .1 2 211 1000022'),
  'bad_im':lambda r:r+b'BLOCK IMNMIX\n 1 1 .1\n',
  'nonfinite':lambda r:r.replace(b'1000022 100',b'1000022 NaN'),
  'negative_scalar':lambda r:r+b'BLOCK MASS\n 1000011 -200\n',
  'wrong_scale':lambda r:r.replace(b'BLOCK NMIX',b'BLOCK NMIX Q= 1000'),
  'rpv':lambda r:r+b'BLOCK MODSEL\n 4 1\n',
  'nmssm':lambda r:r+b'BLOCK NMSSMRUN\n 1 .1\n'}[attack]
 change_spectrum(task,d,mutate)
 with pytest.raises(ValueError):m.compile_map(task,tmp_path)

@pytest.mark.parametrize('attack',['coordinate','species','component','scope'])
def test_pinned_construction_does_not_grant_numerical_or_child_scope(tmp_path,attack):
 task,d=fixture(tmp_path,grid=False)
 if attack=='coordinate':d['points'][0]['coordinate'][0]='201'
 elif attack=='species':d['species'][1]['charge_e']='0'
 elif attack=='component':d['components'][0]['species']=['omitted']
 else:
  with pytest.raises(ValueError):m.validate_scope({'schema_version':2,'max_attempts':1,'review_policy':{'policy':{'max_redos':0,'claim_scopes':{'physics_validated':{'actions':['delivery']}}}}})
  return
 save(task,d)
 with pytest.raises(ValueError):m.compile_map(task,tmp_path)

def test_source_list_population_uses_exact_authenticated_buffer(tmp_path,monkeypatch):
 task,d=fixture(tmp_path/'inputs');allpoints=[{'id':p['id'],'coordinate':p['coordinate']} for p in d['points']]
 population=emit(tmp_path/'original-population.json',{'schema_version':1,'points':allpoints})
 d['population']={'kind':'source-listed','source':population,'layout':'point-list-v1'};d['points']=d['points'][:1];save(task,d)
 alternate_raw=json.dumps({'schema_version':1,'points':allpoints[:1]}).encode();original=m.slha.raw_file
 def substituted(path,expected=None):
  raw=original(path,expected)
  if Path(path)==Path(population['path']) and expected is None:return alternate_raw
  return raw
 monkeypatch.setattr(m.slha,'raw_file',substituted)
 with pytest.raises(ValueError):m.compile_map(task,tmp_path)
