from copy import deepcopy
import hashlib
import pytest
from ravel.physics import rivet_shape_component as m,rivet_event_components as event
from test_rivet_event_components import recipe as pipeline

def sha(b):return hashlib.sha256(b).hexdigest()

def binding(identity,typ,definition):return dict(id=identity,type=typ,frame='caller_supplied_no_transform',definition=definition,definition_sha256=sha(definition.encode()))

def shape(identity,kind,parent,r=None,object_id=None,projection=None):
 return dict(id=identity,kind=kind,input=dict(kind='projection'if projection else'collection',id=parent),projection_name=projection,r=r,outputs=[]if projection else[dict(id=object_id,access='object',unit='native_projection')])

def recipe(kind='sphericity',typ='vector3'):
 definition='vector<Vector3> momenta;\n'
 return dict(schema_version=1,kind='native-rivet-shape-components',source_bindings=[binding('momenta',typ,definition)],nodes=[shape('shape_calc',kind,'momenta',2. if kind=='sphericity'else None,'shape_object')])

@pytest.mark.parametrize('kind,typ',[('sphericity','particles'),('sphericity','jets'),('sphericity','vector3'),('sphericity','four_momenta'),('thrust','particles'),('thrust','vector3'),('thrust','four_momenta'),('spherocity','particles'),('spherocity','vector3'),('spherocity','four_momenta')])
def test_exact_direct_overload_and_native_object(kind,typ):
 r=recipe(kind,typ);old=deepcopy(r);c=m.compile_component(r)
 assert r==old and c['analyze'].splitlines()==[m.CLASSES[kind]+' shape_calc'+('(2.0)'if kind=='sphericity'else'')+';','shape_calc.calc(momenta);','const '+m.CLASSES[kind]+'& shape_object = shape_calc;']
 assert not c['native_executed'] and not c['physics_validated']
 assert all(x not in c['analyze']for x in ('boost','setZ','ghost','isfinite','max(','min('))

@pytest.mark.parametrize('kind',['thrust','spherocity'])
def test_no_native_jet_overload(kind):
 with pytest.raises(ValueError,match='no Jets calc'):m.compile_component(recipe(kind,'jets'))

@pytest.mark.parametrize('kind',['sphericity','thrust','spherocity'])
def test_native_cached_constructor_and_complete_accessors(kind):
 r=dict(schema_version=1,kind='native-rivet-shape-components',source_bindings=[],nodes=[shape('shape',kind,'fs',1. if kind=='sphericity'else None,projection='SHAPE')])
 r['nodes'][0]['outputs']=[dict(id='out_'+name,access=name,unit='1')for name in m.SCALARS[kind]+m.AXES[kind]]
 c=m.compile_component(r,final_states=['fs'])
 assert 'const '+m.CLASSES[kind]+' shape(fs'+(', 1.0'if kind=='sphericity'else'')+');'in c['init']
 for a in m.SCALARS[kind]+m.AXES[kind]:assert f'apply<{m.CLASSES[kind]}>(event, "SHAPE").{a}();'in c['analyze']

@pytest.mark.parametrize('access',['spherocityMajorAxis','spherocityMinorAxis','axis2','axis3'])
def test_spherocity_unpopulated_axes_refuse(access):
 r=recipe('spherocity');r['nodes'][0]['outputs']=[dict(id='out',access=access,unit='1')]
 with pytest.raises(ValueError,match='accessor'):m.compile_component(r)

@pytest.mark.parametrize('mutation',['nonfinite_r','zero_r','bool_r','thrust_r','unit','axis_unit','source_unit','boost','duplicate','forward','bad_type','invalid_symbol','unused_binding','direct_projection','empty_direct','wrong_digest','schema','wrong_base'])
def test_refuse_semantic_and_source_ambiguity(mutation):
 r=recipe();n=r['nodes'][0];b=r['source_bindings'][0]
 if mutation=='nonfinite_r':n['r']=float('inf')
 elif mutation=='zero_r':n['r']=0
 elif mutation=='bool_r':n['r']=True
 elif mutation=='thrust_r':n['kind']='thrust'
 elif mutation=='unit':n['outputs'][0]['unit']='1'
 elif mutation=='axis_unit':n['outputs']=[dict(id='ax',access='axis1',unit='GeV')]
 elif mutation=='source_unit':b['type']='vector<double>'
 elif mutation=='boost':b['frame']='center_of_mass_boost_automatic'
 elif mutation=='duplicate':n['id']='momenta'
 elif mutation=='forward':n['input']['id']='later'
 elif mutation=='bad_type':b['type']=[]
 elif mutation=='invalid_symbol':n['id']='__internal'
 elif mutation=='unused_binding':r['source_bindings'].append(binding('unused','jets','Jets unused;\n'))
 elif mutation=='direct_projection':n['projection_name']='SHAPE'
 elif mutation=='empty_direct':n['outputs']=[]
 elif mutation=='wrong_digest':b['definition_sha256']='0'*64
 elif mutation=='schema':r['schema_version']=True
 else:b['type']='final_state'
 with pytest.raises(ValueError):m.compile_component(r)

@pytest.mark.parametrize('mutation',['missing','after','duplicate','drift'])
def test_exact_preceding_source_excerpt(mutation):
 r=recipe();raw=b'// RAVEL_SHAPE_HEADERS\n// RAVEL_SHAPE_INIT\nvector<Vector3> momenta;\n// RAVEL_SHAPE_ANALYZE\n// retained finalize\n'
 if mutation=='missing':raw=raw.replace(b'vector<Vector3> momenta;\n',b'')
 elif mutation=='after':raw=raw.replace(b'vector<Vector3> momenta;\n',b'')+b'vector<Vector3> momenta;\n'
 elif mutation=='duplicate':raw+=b'vector<Vector3> momenta;\n'
 else:raw=raw.replace(b'vector<Vector3>',b'vector<FourMomentum>')
 with pytest.raises(ValueError):m.instantiate(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),recipe=r)

def test_whole_source_positive_and_ending_finalize():
 r=recipe();raw=b'// RAVEL_SHAPE_HEADERS\n// RAVEL_SHAPE_INIT\nvector<Vector3> momenta;\n// RAVEL_SHAPE_ANALYZE\n// retained finalize\n'
 result=m.instantiate(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),recipe=r)
 assert result['source'].endswith(b'// retained finalize\n') and b'shape_calc.calc(momenta);'in result['source']

def test_dilepton_remaining_fastjets_met_to_both_shape_modes():
 r=pipeline();r['event_shapes']=dict(schema_version=1,kind='native-rivet-shape-components',source_bindings=[],nodes=[shape('spherical','sphericity','remaining',1.,projection='SPHERICAL'),shape('jet_shape','sphericity','selected_jets',2.,'jet_sphericity')])
 c=event.compile_component(r)
 assert c['init'].index('VetoedFinalState remaining')<c['init'].index('Sphericity spherical(remaining, 1.0)')
 assert c['analyze'].index('selected_jets =')<c['analyze'].index('jet_shape.calc(selected_jets)')
 assert c['analyze'].index('vectorMissingEt')<c['analyze'].index('jet_shape.calc')
 assert 'Jets jet_sphericity'not in c['analyze'] and 'const Sphericity& jet_sphericity = jet_shape;'in c['analyze']

@pytest.mark.parametrize('mutation',['wrong_FS','no_jet_output','output_collision','native_class_shadow','projection_collision','DressedLeptons'])
def test_connected_shape_type_and_namespace_guards(mutation):
 r=pipeline();r['event_shapes']=dict(schema_version=1,kind='native-rivet-shape-components',source_bindings=[],nodes=[shape('spherical','sphericity','remaining',2.,projection='SPHERICAL')])
 n=r['event_shapes']['nodes'][0]
 if mutation=='wrong_FS':n['input']['id']='selected_jets'
 elif mutation=='no_jet_output':r['jets'][0]['output']=None;r['jets'][0]['jet_cuts']=[];n.update(input=dict(kind='collection',id='selected_jets'),projection_name=None,outputs=[dict(id='val',access='sphericity',unit='1')])
 elif mutation=='output_collision':n['outputs']=[dict(id='leptons',access='sphericity',unit='1')]
 elif mutation=='native_class_shadow':r['particles']['nodes'][0]['id']='Sphericity';r['particles']['nodes'][1]['input']='Sphericity'
 elif mutation=='projection_collision':n['projection_name']='PAIR'
 else:r['particles']['nodes'][1].update(kind='dressed',leptons='fs',photons='fs',radius=.1,dressing='cone',cuts=[],projection_name='DRESS',output=dict(id='selected_dressed',access='dressed_leptons'));r['particles']['nodes'][1].pop('input');r['particles']['nodes'][1].pop('pids');n.update(input=dict(kind='collection',id='selected_dressed'),projection_name=None,outputs=[dict(id='val',access='sphericity',unit='1')])
 with pytest.raises(ValueError):event.compile_component(r)
