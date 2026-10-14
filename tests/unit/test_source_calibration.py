"""Portable production unit candidate: synthetic math/custody fixtures only.

Original-container bytes here are deliberately not ROOT files. No local-runs,
uproot, detector calibration or genuine source payload is needed or claimed.
Actual primary-container controls remain a separate retained local validation.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace, FrozenInstanceError
import hashlib,json,unittest
from ravel.physics.source_calibration import (
    ArtifactPin,SourceDomain,CalibrationProvider,JointCategoricalResponse,
    exclusive_probabilities,exclusive_scale_factors,
)
COMMIT='0c2e91577f7832d6dc527b00f61f7e03db46064b'
def digest(raw):return hashlib.sha256(raw).hexdigest()
def content_digest(obj):return digest(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def pin(path):return ArtifactPin(str(path),digest(path.read_bytes()))
def save(path,obj):path.write_text(json.dumps(obj,allow_nan=False));return pin(path)

class PortableScalarTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.h=Path(self.tmp.name)
  self.root=self.h/'JetID_TrueHadTau_synthetic.root'
  self.root.write_bytes(b'SYNTHETIC custody token, intentionally not ROOT; no physics calibration.\n')
  self.domain=SourceDomain(COMMIT,'00-03-16','synthetic-config','synthetic-MC','synthetic-era','medium')
  objects=[];aliases={}
  for n in (1,3):
   def hist(name,values):return {'key':name+';1','name':name,'class':'TH2F','edges':[[20,25,1000],[-2,0,2]],'values_without_flow':values}
   objects.append(hist(f'sf_medium_{n}p',[[1,1.1],[1.2,1.3]]))
   for direction,magnitude in [('up',.1),('down',.2)]:
    name=f'STAT_{direction}_medium_{n}p';objects.append(hist(name,[[magnitude,magnitude],[magnitude,magnitude]]));aliases[name]={'key':name+';1'}
   name=f'HIGHPT_medium_{n}p'
   objects.append({'name':name,'key':name+';1','class':'TF1','function':{'formula':'.001*((x-100.)*(x>=100))','title':'.001*((x-100.)*(x>=100))','npar':0,'ndim':1,'type':0,'parameters':[],'xmin':0,'xmax':2000}})
   for direction in ('up','down'):aliases[f'HIGHPT_{direction}_medium_{n}p']={'key':name+';1'}
  self.payload={'path':str(self.root.resolve()),'sha256':pin(self.root).sha256,'literal_coordinates':{'x':'final_pt','y':'final_eta'},'objects':objects,'source_efficiency_aliases':aliases}
  correction={'binding_id':'synthetic-only','quantity':'marginal_data_over_mc_sf','payload_sha256':self.payload['sha256'],'decoded_payload_sha256':content_digest(self.payload),'expected_truth':'had_tau','three_prong_unity':False,'x_coordinate':'final_pt','y_coordinate':'final_eta','keys_by_prong':{str(n):{'nominal':f'sf_medium_{n}p;1'} for n in (1,3)},'nuisances':{}}
  for nuisance in ['STAT','HIGHPT']:
   correction['nuisances'][nuisance]={}
   for n in (1,3):
    ua=f'{nuisance}_up_medium_{n}p';da=f'{nuisance}_down_medium_{n}p'
    correction['nuisances'][nuisance][str(n)]=[{'up_alias':ua,'down_alias':da,'up_key':aliases[ua]['key'],'down_key':aliases[da]['key'],'parameter':1.}]
  self.spec={'domain':self.domain.__dict__.copy(),'correction':correction}
  self.dp=self.h/'decoded.json';self.bp=self.h/'binding.json';self.write()
 def write(self):
  self.decoded=save(self.dp,{'payloads':[self.payload]});self.binding=save(self.bp,self.spec)
 def load(self):return CalibrationProvider.load(decoded=self.decoded,original_root=pin(self.root),binding=self.binding)
 def event(self,pt=30):return {'truth_category':'had_tau','prongs':1,'pt_final_calib_gev':pt,'eta_final_calib':.7}
 def test_literal_edges_clamp_and_asymmetry(self):
  p=self.load()
  self.assertEqual(p.evaluate(self.event(24.999),context=self.domain)['value'],1.1)
  self.assertEqual(p.evaluate(self.event(25),context=self.domain)['value'],1.3)
  self.assertEqual(p.evaluate(self.event(5000),context=self.domain)['value'],1.3)
  self.assertAlmostEqual(p.evaluate(self.event(),context=self.domain,nuisance='STAT',direction=1)['value'],1.43)
  self.assertAlmostEqual(p.evaluate(self.event(),context=self.domain,nuisance='STAT',direction=-1)['value'],1.04)
 def test_formula_no_histogram_clamp(self):
  p=self.load()
  self.assertAlmostEqual(p.evaluate(self.event(2500),context=self.domain,nuisance='HIGHPT',direction=1)['value'],1.3*(1+2.4))
 def test_immutable_state_and_context(self):
  p=self.load()
  with self.assertRaises(FrozenInstanceError):p.binding_id='changed'
  with self.assertRaises(TypeError):p._binding['expected_truth']='electron'
  with self.assertRaises(TypeError):p._payload.object_index['sf_medium_1p;1']['values_without_flow'][0][0]=9
  with self.assertRaises(ValueError):p.evaluate(self.event(),context=replace(self.domain,era_namespace='missing'))
 def test_truth_prong_coordinate_and_nuisance_requirements(self):
  p=self.load();self.assertEqual(p.evaluate(dict(self.event(),truth_category='electron'),context=self.domain)['value'],1.)
  for changed in [{'truth_category':'unknown'},{'prongs':True},{'pt_final_calib_gev':True},{'eta_final_calib':float('inf')}]:
   with self.assertRaises(ValueError):p.evaluate(dict(self.event(),**changed),context=self.domain)
  missing=self.event();missing.pop('pt_final_calib_gev')
  with self.assertRaises(ValueError):p.evaluate(missing,context=self.domain)
  for args in [{'direction':True,'nuisance':'STAT'},{'direction':1},{'direction':1,'nuisance':'absent'}]:
   with self.assertRaises(ValueError):p.evaluate(self.event(),context=self.domain,**args)
 def test_each_byte_pin(self):
  pins={'decoded':self.decoded,'original_root':pin(self.root),'binding':self.binding}
  for name in pins:
   bad=dict(pins);bad[name]=replace(bad[name],sha256='0'*64)
   with self.assertRaises(ValueError):CalibrationProvider.load(**bad)
 def test_corrupt_decoded_content_preserved_root_label(self):
  self.payload['objects'][0]['values_without_flow'][0][0]=9;self.write()
  with self.assertRaises(ValueError):self.load()
 def test_source_mapping_and_boolean_config_refused(self):
  original=json.loads(json.dumps(self.spec))
  mutations=[lambda s:s['correction'].update(x_coordinate='final_p'),lambda s:s['correction'].update(three_prong_unity=1),lambda s:s['correction']['nuisances']['STAT']['1'][0].update(up_key='STAT_down_medium_1p;1'),lambda s:s['domain'].update(working_point='tight')]
  for fn in mutations:
   self.spec=json.loads(json.dumps(original));fn(self.spec);self.write()
   with self.assertRaises(ValueError):self.load()
 def test_multiple_cycles_refused(self):
  extra=dict(self.payload['objects'][0],key='sf_medium_1p;2');self.payload['objects'].append(extra)
  self.spec['correction']['decoded_payload_sha256']=content_digest(self.payload);self.write()
  with self.assertRaises(ValueError):self.load()
 def test_strict_decoded_json(self):
  raw=self.dp.read_text()
  for prefix in ['"duplicate":1,"duplicate":1,','"bad":NaN,']:
   self.dp.write_text('{'+prefix+raw[1:]);self.decoded=pin(self.dp)
   with self.assertRaises(ValueError):self.load()

class PortableJointTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.h=Path(self.tmp.name)
  e=self.h/'synthetic-evidence';e.write_text('Synthetic probability arithmetic only; not measured calibration.');self.evidence=pin(e)
  self.context={'era':'synthetic'}
  self.spec={'quantity':'absolute_joint_data_and_mc_probabilities','calibration_evidence_sha256':self.evidence.sha256,'exhaustive_mutually_exclusive':True,'conditioning_fields':['era'],'cells':[{'context':self.context.copy(),'mc':{'none':.4,'both':.4,'a_only':.1,'b_only':.1},'data':{'none':.1,'both':.1,'a_only':.4,'b_only':.4}}]}
 def load(self):return JointCategoricalResponse.load(save(self.h/'joint.json',self.spec),evidence=self.evidence)
 def test_correlated_OR_and_signed_application(self):
  p=self.load();self.assertAlmostEqual(p.selection_sf(self.context,['both','a_only']),1.)
  self.assertAlmostEqual(p.selection_sf(self.context,['both','a_only','b_only']),1.5)
  self.assertEqual(p.weight_category(-2,self.context,'a_only'),-8)
  self.assertAlmostEqual(sum(self.spec['cells'][0]['mc'][k]*p.category_sf(self.context,k) for k in self.spec['cells'][0]['mc']),1.)
 def test_nested_absolute_efficiencies_and_subnormal_overflow(self):
  self.assertAlmostEqual(exclusive_scale_factors([.9,.8,.6],[.882,.76,.63])['medium_only'],.65)
  with self.assertRaises(ValueError):exclusive_scale_factors([5e-324,0,0],[.5,0,0])
  with self.assertRaises(ValueError):exclusive_probabilities(True,.8,.6)
  with self.assertRaises(ValueError):exclusive_probabilities(.8,.9,.6)
 def test_joint_support_and_normalization(self):
  self.spec['cells'][0]['data']['none']+=1e-10
  with self.assertRaises(ValueError):self.load()
  self.spec['cells'][0]['data']['none']=.1;self.spec['cells'][0]['mc'].update(none=0,both=.8)
  with self.assertRaises(ValueError):self.load()
 def test_explicit_cells_and_duplicate_JSON(self):
  p=self.load()
  with self.assertRaises(ValueError):p.selection_sf({'era':'unknown'},['both'])
  with self.assertRaises(ValueError):p.selection_sf(self.context,['both','both'])
  raw=json.dumps(self.spec).replace('"none": 0.4','"none": 0.4,"none": 0.4',1)
  path=self.h/'dup.json';path.write_text(raw)
  with self.assertRaises(ValueError):JointCategoricalResponse.load(pin(path),evidence=self.evidence)
 def test_finite_joint_ratios_and_signed_weights(self):
  self.spec['cells'][0]['mc'].update(none=1.,both=5e-324,a_only=0,b_only=0)
  self.spec['cells'][0]['data'].update(none=0.,both=1.,a_only=0,b_only=0)
  p=self.load()
  with self.assertRaises(ValueError):p.category_sf(self.context,'both')
  with self.assertRaises(ValueError):p.selection_sf(self.context,['both'])
  with self.assertRaises(ValueError):p.weight_category(True,self.context,'none')
if __name__=='__main__':unittest.main()
