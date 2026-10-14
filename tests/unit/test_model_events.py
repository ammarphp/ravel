"""Inert source/card/event-protocol fixtures; never execute MG/UFO/native tools."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import pytest
from ravel.physics import model_events as m, model_event_weights as w, native_pipeline, model_event_process
from ravel.workflow import model_event_plan as p, science, agent_graph, agent_host


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+'\n' if isinstance(data,dict) else data)
    return pin(path)


def tree(root, files):
    for name,raw in files.items(): write(root/name,raw)
    manifest=root.parent/(root.name+'-manifest.json')
    return {'root':str(root),'manifest':write(manifest,m.bridge.source_tree(root))}


def policy():
    return {'schema_version':1,'policy':{'schema_version':1,
        'actors':{'proposer':'source-author','executor':'executor','physics_critic':'critic','skeptical_verifier':'verifier','physics_decider':'decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'generator-population','kind':'scientific'}],
        'claim_scopes':{'generated_event_delivery':{'checks':['integrity','generator-population'],'actions':['delivery','reuse']}}},
        'correction_contract':{'task_fields':[],'input_slots':[]}}


def config(base, scheme='unmerged_lo', *, variations=False, decay=False):
    base.mkdir(parents=True,exist_ok=True)
    mg=tree(base/'mg',{'VERSION':'version = 2.9.27\n','bin/mg5_aMC':'# Synthetic non-executable MG stand-in\n',
        'madgraph/interface/madevent_interface.py':'class MadEventCmd:\n    def do_pythia8(self, line):\n        return line\n',
        'madgraph/interface/amcatnlo_run_interface.py':'class aMCatNLOCmd:\n    def do_shower(self, line):\n        return line\n'})
    model=tree(base/'ufo',{x:'# Synthetic non-executable UFO stand-in\n' for x in ('__init__.py','parameters.py','particles.py','vertices.py','couplings.py','object_library.py','lorentz.py')})
    deps=tree(base/'deps',{'fc':'inert','cxx':'inert'})
    py=pin(Path(sys.executable).resolve()); support=write(base/'python-support.json',{'python_sha256':py['sha256'],'files':[pin(base/'deps/fc')]})
    order=m.SCHEMES[scheme];merged=scheme in ('mlm','ckkw_l','fxfx');mult=[0,1] if merged else [0]
    process='define p = g u u~ d d~\ndefine j = g u u~ d d~\ngenerate p p > t t~'+(' [QCD]' if order=='NLO' else '')+'\n'
    if merged:process+='add process p p > t t~ j'+(' [QCD]' if order=='NLO' else '')+'\n'
    run={'nevents':3,'iseed':19,'lpp1':1,'lpp2':1,'ebeam1':6500,'ebeam2':6500,'ickkw':{'unmerged_lo':0,'mlm':1,'ckkw_l':0,'mcatnlo':0,'fxfx':3}[scheme]}
    if order=='LO':run.update(use_syst=variations,systematics_program='systematics',systematics_arguments="['--mur=0.5,1,2','--muf=0.5,1,2','--pdf=errorset']",xqcut=20 if scheme=='mlm' else 0,ktdurham=20 if scheme=='ckkw_l' else -1,ptlund=-1)
    else:run.update(parton_shower='PYTHIA8',store_rwgt_info=True,reweight_scale=variations,reweight_pdf=variations,rw_rscale='[1,2,.5]',rw_fscale='[1,2,.5]')
    shower_on=scheme!='unmerged_lo'
    cards={name:None for name in m.CARD_NAMES}
    cards.update(process=write(base/'proc.dat',process),parameter=write(base/'param.dat','BLOCK MASS\n 6 172.5\nDECAY 6 1.4\n'),run=write(base/'run.dat','\n'.join(str(value)+' = '+key for key,value in run.items())+'\n'))
    if shower_on and order=='LO':
        pytext='Main:numberOfEvents = 3\nHEPMCoutput:file = auto\n'
        if scheme=='mlm':pytext+='JetMatching:qCut = 30\nJetMatching:nJetMax = 1\nJetMatching:merge = on\nJetMatching:scheme = 1\n'
        else:pytext+='Merging:TMS = 30\nMerging:Process = pp>ttbar\nMerging:nJetMax = 1\n'
        cards['pythia']=write(base/'pythia.dat',pytext)
    if order=='NLO':cards['shower']=write(base/'shower.dat','Qcut = '+('30' if merged else '-1')+'\nnjmax = 1\n')
    if decay:cards['madspin']=write(base/'madspin.dat','set spinmode madspin\nset seed 101\ndecay t > b w+\ndecay t~ > b~ w-\nlaunch\n')
    group=[{'name':'scale_variation','combine':'envelope','ids':['1001','1002']}] if variations else []
    vsource=write(base/'scale-source.json',{'synthetic':True,'literal_mur':[.5,2]})
    return {'schema_version':1,'source':'Synthetic source/API controls only; no physics sample',
        'runtime':{'madgraph_tree':mg,'python':py,'python_manifest':support,'dependencies':[{'role':'compiler','tree':deps}],
            'options':{'fortran_compiler':str(base/'deps/fc'),'cpp_compiler':str(base/'deps/cxx'),'pythia8_path':str(base/'deps') if shower_on else None,
                       'mg5amc_py8_interface_path':str(base/'deps') if shower_on and order=='LO' else None,'lhapdf':None}},
        'model_tree':model,'cards':cards,'generation':{'order':order,'scheme':scheme,'events':3,'seed':19,'beam_type':[1,1],'beam_pdg':[2212,2212],
            'energy_gev':[6500,6500],'jet_token':'j','jet_multiplicities':mult,'run_settings':{},'scale_pdf':('lo_systematics' if order=='LO' else 'nlo_on_the_fly') if variations else 'none'},
        'shower':{'backend':'PYTHIA8' if shower_on else 'OFF','settings':{},'merging_scale_gev':30 if merged else None,'max_jets':max(mult),
            'process':'pp>ttbar' if scheme=='ckkw_l' else None,'minimum_returned_events':1 if shower_on else 0},
        'decay':{'mode':'MADSPIN' if decay else 'OFF','spinmode':'madspin' if decay else None,'seed':101 if decay else None,
                 'commands':['decay t > b w+','decay t~ > b~ w-'] if decay else []},'reweight':{'mode':'OFF','weight_ids':[]},
        'weights':{'groups':group,'variation_points':[{'id':identity,'kind':'scale','source':vsource,'definition':{'mu_r_factor':factor,'mu_f_factor':1,'normalization':'absolute_lhe_weight'}} for identity,factor in zip(['1001','1002'],[.5,2])] if variations else [],'sampling_law':'unknown'},
        'outputs':{'lhe_relative':'Events/ravel/unweighted_events.lhe','hepmc_relative':'Events/ravel/tag_1_pythia8_events.hepmc' if shower_on else None,'max_decoded_lhe_bytes':1000000,
                   'shower_weight_map':[{'hepmc_name':'nominal','lhe_id':None},*([{'hepmc_name':'scale_'+identity,'lhe_id':identity} for identity in ['1001','1002']] if variations else [])] if shower_on else []},
        'max_seconds':60,'max_ram_mib':512,'assumptions':['Synthetic API control; matching stability, source amplitudes and physical validity unknown.']}


def texts(c):return {name:Path(ref['path']).read_text() for name,ref in c['cards'].items() if ref is not None}


@pytest.mark.parametrize('scheme',list(m.SCHEMES))
def test_each_regime_renders_actual_upstream_switches_and_preserves_cards(tmp_path,scheme):
    c=config(tmp_path,scheme,variations=True,decay=True);before=deepcopy(c)
    assert m.validate_config(c) is c
    observed=m.check_cards(c,texts(c));build,launch=m.render_scripts(c,texts(c),model_path=tmp_path/'model',process_path=tmp_path/'PROC')
    assert 'set nb_core 1' in build and 'output '+str(tmp_path/'PROC') in build
    assert 'import model '+str(tmp_path/'model')+'-full' in build
    assert 'madspin=ON' in launch and 'reweight=OFF' in launch
    assert ('order=NLO' in launch)==(m.SCHEMES[scheme]=='NLO')
    assert ('shower=PYTHIA8' in launch)==(scheme!='unmerged_lo')
    assert c==before and observed['decay']['seed']==101


@pytest.mark.parametrize('defect',['missing_scheme','lo_from_nlo','shower_off','dropped_weights','wrong_order','guess_qcut','no_multijet','process_command','process_order','madspin_seed','run_seed','run_override','exposure_override','merged_off','fxfx_as_lo'])
def test_material_regime_and_source_changes_refuse(tmp_path,defect):
    c=config(tmp_path,'mlm',variations=True,decay=True);t=texts(c)
    if defect=='missing_scheme':del c['generation']['scheme']
    elif defect=='lo_from_nlo':c['generation']['order']='NLO'
    elif defect=='shower_off':c['shower']['backend']='OFF'
    elif defect=='dropped_weights':c['weights']['groups']=[]
    elif defect=='wrong_order':t['process']+='add process p p > t t~ j [QCD]\n'
    elif defect=='guess_qcut':t['pythia']=t['pythia'].replace('qCut = 30','qCut = -1')
    elif defect=='no_multijet':c['generation']['jet_multiplicities']=[0]
    elif defect=='process_command':t['process']+='launch /unbound/path\n'
    elif defect=='process_order':t['process']=t['process'].replace('generate ','add process ',1)
    elif defect=='madspin_seed':t['madspin']=t['madspin'].replace('seed 101','seed 102')
    elif defect=='run_seed':t['run']=t['run'].replace('19 = iseed','20 = iseed')
    elif defect=='run_override':c['generation']['run_settings']['nevents']=999
    elif defect=='exposure_override':c['shower']['settings']['Main:numberOfEvents']=999
    elif defect=='merged_off':t['pythia']=t['pythia'].replace('merge = on','merge = off')
    elif defect=='fxfx_as_lo':c['generation']['scheme']='fxfx'
    with pytest.raises((ValueError,KeyError)):m.validate_config(c);m.check_cards(c,t)


def lhe(groups=True,compact=False):
    header='<header><initrwgt><weightgroup name="scale_variation" combine="envelope"><weight id="1001" MUR="0.5" MUF="1" PDF="260000">MUR=.5 MUF=1</weight><weight id="1002" MUR="2" MUF="1" PDF="260000">MUR=2 MUF=1</weight></weightgroup></initrwgt></header>' if groups else '<header></header>'
    events=''
    for nominal,a,b in [('1','2','3'),('-1','-2','-3'),('0','0','0')]:
        extra='<weights>'+a+' '+b+'</weights>' if compact else '<rwgt><wgt id="1001">'+a+'</wgt><wgt id="1002">'+b+'</wgt></rwgt>'
        events+='<event>\n2 1 '+nominal+' 100 .007 .1\n1 -1 0 0 0 0 0 0 6500 6500 0 0 9\n-1 -1 0 0 0 0 0 0 -6500 6500 0 0 9\n'+(extra if groups else '')+'\n</event>\n'
    return '<LesHouchesEvents version="3.0">'+header+'\n<init>\n2212 2212 6500 6500 0 0 260000 260000 -4 1\n1 .01 1 1\n</init>\n'+events+'</LesHouchesEvents>\n'


@pytest.mark.parametrize('compact',[False,True])
def test_full_signed_zero_multiweight_population_and_normalization_are_retained(tmp_path,compact):
    path=tmp_path/'events.lhe';path.write_text(lhe(compact=compact))
    group=[{'name':'scale_variation','combine':'envelope','ids':['1001','1002']}]
    result=w.scan(path,expected_events=3,expected_groups=group,maximum_bytes=100000,journal_path=tmp_path/'weights.jsonl')
    assert result['signed_nominal_counts']=={'positive':1,'negative':1,'zero':1}
    assert result['weight_moments']['nominal']=={'sumw':'0','sumw2':'2'}
    assert result['weight_moments']['1002']=={'sumw':'0','sumw2':'18'}
    assert result['init']['idwtup']==-4 and result['cross_variation_independence'] is False
    assert result['sampling_law']=='unknown' and len((tmp_path/'weights.jsonl').read_text().splitlines())==3


@pytest.mark.parametrize('defect',['missing','duplicate','extra','nonfinite','particle','count','truncated','group','entity','bound','process'])
def test_no_partial_or_false_multiweight_delivery(tmp_path,defect):
    raw=lhe();maximum=100000;expected=3
    if defect=='missing':raw=raw.replace('<wgt id="1002">3</wgt>','',1)
    elif defect=='duplicate':raw=raw.replace('<wgt id="1002">3</wgt>','<wgt id="1001">3</wgt>',1)
    elif defect=='extra':raw=raw.replace('</rwgt>','<wgt id="extra">1</wgt></rwgt>',1)
    elif defect=='nonfinite':raw=raw.replace('<wgt id="1001">2','<wgt id="1001">NaN',1)
    elif defect=='particle':raw=raw.replace('2 1 1 100','3 1 1 100',1)
    elif defect=='count':expected=2
    elif defect=='truncated':raw=raw.replace('</LesHouchesEvents>','')
    elif defect=='group':raw=raw.replace('name="scale_variation"','name="wrong"')
    elif defect=='entity':raw='<!DOCTYPE foo [<!ENTITY xx "lost">]>'+raw
    elif defect=='bound':maximum=100
    elif defect=='process':raw=raw.replace('2 1 1 100','2 2 1 100',1)
    path=tmp_path/'events.lhe';path.write_text(raw)
    with pytest.raises((ValueError,ET.ParseError)):
        w.scan(path,expected_events=expected,expected_groups=[{'name':'scale_variation','combine':'envelope','ids':['1001','1002']}],maximum_bytes=maximum,journal_path=tmp_path/'partial.jsonl')


def test_unapproved_generation_refuses_before_writing(tmp_path):
    with pytest.raises(ValueError,match='approved'):m.run({'config':'missing.json'},tmp_path,tmp_path/'output')
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('controls',[{'madspin':'ON'},{'reweight':'ON'},{'scheme':'fxfx'},{'order':'NLO'}])
def test_legacy_request_never_silently_drops_new_physics(controls):
    native_pipeline.require_legacy_regime({'madgraph':{}})
    with pytest.raises(ValueError,match='model-events'):native_pipeline.require_legacy_regime({'madgraph':controls})


def setup_request(tmp_path):
    c=config(tmp_path/'inputs');cp=write(tmp_path/'config.json',c);pol=write(tmp_path/'policy.json',policy())
    req={'schema_version':1,'config':cp,'review_policy':pol,'supervisor_seconds':90,'goal_binding':None}
    return req,c


def test_public_cli_to_full_source_inputs_and_real_unapproved_ordinary_plan(tmp_path,capsys):
    from ravel.cli import main
    req,c=setup_request(tmp_path);rp=tmp_path/'request.json';write(rp,req)
    assert main(['model-events','prepare','--request',str(rp),'--out',str(tmp_path/'prepared')])==0
    spec=tmp_path/'prepared/science.json';science.plan(tmp_path/'run',spec)
    plan=json.loads((tmp_path/'run/inputs/science-plan.json').read_text())
    checkin=json.loads((tmp_path/'run/inputs/checkin1.json').read_text())
    assert plan['mode']=='model-events' and checkin['sections']['iv']['new_generated_events']==3
    assert not (tmp_path/'run/inputs/science-approval.json').exists()
    assert science.verify_plan(tmp_path/'run',approved=False)['mode']=='model-events'


def test_actual_graph_host_source_tool_preserves_full_generator_inputs(tmp_path):
    req,c=setup_request(tmp_path);rp=tmp_path/'request.json';write(rp,req)
    files=[rp,*p.graph_inputs(req,tmp_path)]
    pins=[{'id':'f'+str(i),'path':str(path),'sha256':m.bridge._hash(path)} for i,path in enumerate(files)]
    node={'id':'prepare','kind':'tool','role':'designer','depends_on':[],'inputs':pins,'packet':None,'action':'model-event-plan',
        'parameters':{'request_input':'f0','output_dir':str(tmp_path/'prepared')},'max_attempts':1}
    graph={'schema_version':1,'graph_id':'generation','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[node]}
    agent_graph.create(tmp_path/'graph',graph)
    agent_graph.execute(tmp_path/'graph',agent_host.AgentHost(),workers=1)
    assert (tmp_path/'prepared/science.json').is_file()
    assert not (tmp_path/'prepared/science-approval.json').exists()


def test_incomplete_graph_dependencies_refuse(tmp_path):
    req,c=setup_request(tmp_path)
    with pytest.raises(ValueError,match='Graph inputs'):p.prepare(req,base_dir=tmp_path,output_dir=tmp_path/'prepared',presented_pins=[])
    assert not (tmp_path/'prepared').exists()


def hepmc(names=None):
    names=names or ['nominal','scale_1001','scale_1002']
    raw='HepMC::Version 2.06.11\nHepMC::IO_GenEvent-START_EVENT_LISTING\n'
    for event,values in enumerate(['1 2 3','-1 -2 -3','0 0 0']):
        raw+='E '+str(event)+' 0 100 .1 .007 0 0 0 1 2 0 3 '+values+'\n'
        raw+='N 3 '+' '.join('"'+name+'"' for name in names)+'\nU GEV MM\nP 1 2212 0 0 6500 6500 0 4 0 0 0 0\nP 2 2212 0 0 -6500 6500 0 4 0 0 0 0\n'
    return raw+'HepMC::IO_GenEvent-END_EVENT_LISTING\n'


def test_named_shower_signed_vectors_are_complete_and_not_an_original_lhe_join(tmp_path):
    path=tmp_path/'events.hepmc';path.write_text(hepmc())
    result=w.scan_hepmc2_weights(path,names=['nominal','scale_1001','scale_1002'],minimum_events=1,maximum_events=3,maximum_bytes=100000,journal_path=tmp_path/'weights.jsonl')
    rows=[json.loads(x) for x in (tmp_path/'weights.jsonl').read_text().splitlines()]
    assert [r['weights'][0]['value'] for r in rows]==['1','-1','0']
    assert result['returned_events']==3 and result['original_lhe_join_qualified'] is False
    assert all(r['original_lhe_ordinal'] is None for r in rows)


@pytest.mark.parametrize('defect',['missing','extra','name','truncated','nonfinite','exposure','map'])
def test_dropped_or_inferred_shower_variations_refuse(tmp_path,defect):
    raw=hepmc();maximum=3
    if defect=='missing':raw=raw.replace(' 0 3 1 2 3',' 0 2 1 2',1)
    elif defect=='extra':raw=raw.replace(' 0 3 1 2 3',' 0 4 1 2 3 4',1)
    elif defect=='name':raw=raw.replace('"scale_1002"','"guessed"',1)
    elif defect=='truncated':raw=raw.replace('HepMC::IO_GenEvent-END_EVENT_LISTING','')
    elif defect=='nonfinite':raw=raw.replace(' 0 3 1 2 3',' 0 3 1 NaN 3',1)
    elif defect=='exposure':maximum=2
    elif defect=='map':
        c=config(tmp_path/'inputs','mlm',variations=True);c['outputs']['shower_weight_map'].pop()
        with pytest.raises(ValueError,match='complete unique'):m.validate_config(c)
        return
    path=tmp_path/'events.hepmc';path.write_text(raw)
    with pytest.raises(ValueError):w.scan_hepmc2_weights(path,names=['nominal','scale_1001','scale_1002'],minimum_events=1,maximum_events=maximum,maximum_bytes=100000,journal_path=tmp_path/'partial.jsonl')


def parameter_reweight(c,base,mode='LO'):
    # The native card applies edits AFTER their associated launch.
    identity='eft'+{'LO':'','NLO':'_nlo','NLO_tree':'_tree'}[mode]
    c['reweight']={'mode':mode,'weight_ids':[identity]}
    c['cards']['reweight']=write(base/'reweight.dat','change mode '+mode+'\nlaunch --rwgt_name=eft\nset mass 6 180\n')
    point={'id':identity,'kind':'parameter','source':write(base/'coefficients.json',{'source':'synthetic complete point'}),
           'definition':{'basis':'explicit-test-basis','flavour':'full','scale_gev':1000,'normalization':'absolute_lhe_weight',
                         'components':[{'name':'c','real':180,'imag':0}],'expansion':'full_matrix_element',
                         'ufo_mapping':[{'coefficient':'c','component':'real','block':'MASS','codes':[6],'factor':1,'unit':'GeV'}]}}
    c['weights']['groups'].append({'name':'reweight','combine':None,'ids':[identity]})
    c['weights']['variation_points'].append(point)
    if c['shower']['backend']!='OFF':c['outputs']['shower_weight_map'].append({'hepmc_name':identity,'lhe_id':identity})
    return point


@pytest.mark.parametrize('mode',['LO','NLO','NLO_tree'])
def test_reweight_launch_card_preserves_complex_convention_and_native_suffix(tmp_path,mode):
    c=config(tmp_path,'unmerged_lo' if mode=='LO' else 'mcatnlo');parameter_reweight(c,tmp_path,mode)
    m.validate_config(c);result=m.check_cards(c,texts(c))
    assert result['reweight']['mode']==mode
    _,launch=m.render_scripts(c,texts(c),model_path=tmp_path/'model',process_path=tmp_path/'PROC')
    assert 'reweight=ON' in launch


@pytest.mark.parametrize('defect',['wrong_value','before_launch','imaginary_unmapped','unknown_coefficient','interference','incomplete_point'])
def test_eft_coefficient_card_mapping_cannot_be_inferred_or_mislabelled(tmp_path,defect):
    c=config(tmp_path);point=parameter_reweight(c,tmp_path);t=texts(c)
    if defect=='wrong_value':t['reweight']=t['reweight'].replace('180','181')
    elif defect=='before_launch':t['reweight']='change mode LO\nset mass 6 180\nlaunch --rwgt_name=eft\n'
    elif defect=='imaginary_unmapped':point['definition']['components'][0]['imag']=1
    elif defect=='unknown_coefficient':point['definition']['ufo_mapping'][0]['coefficient']='unknown'
    elif defect=='interference':point['definition']['expansion']='linear_interference'
    elif defect=='incomplete_point':point['definition']['ufo_mapping']=[]
    with pytest.raises(ValueError):m.validate_config(c);m.check_cards(c,t)


def test_explicit_scaled_slha_blocks_and_decay_tables_are_preserved_without_width_computation():
    source='BLOCK SMEFT Q= 1000\n 1 -2.5D-4\nDECAY 25 4D-3\n .75 2 5 -5\n .25 2 15 -15\n'
    values=m.parameter_values(source)
    assert values[('@scale',('smeft',))]==1000 and len(values)==5
    with pytest.raises(ValueError,match='automatic'):m.parameter_values(source.replace('4D-3','Auto'))


def test_manifest_alone_does_not_allow_graph_source_member_substitution(tmp_path):
    req,c=setup_request(tmp_path);rp=tmp_path/'request.json';write(rp,req)
    pins=[{'path':str(x),'sha256':m.bridge._hash(x)} for x in p.graph_inputs(req,tmp_path)]
    Path(c['model_tree']['root'],'vertices.py').write_text('changed after Graph binding\n')
    with pytest.raises(ValueError):p.prepare(req,base_dir=tmp_path,output_dir=tmp_path/'prepared',presented_pins=pins)
    assert not (tmp_path/'prepared').exists()


@pytest.mark.parametrize('style',['attributes','nlo_text'])
def test_actual_upstream_scale_header_syntax_binds_factors_not_positional_ids(tmp_path,style):
    c=config(tmp_path/'inputs',variations=True);raw=lhe()
    if style=='nlo_text':
        raw=raw.replace(' MUR="0.5" MUF="1" PDF="260000"','').replace(' MUR="2" MUF="1" PDF="260000"','')
    source=tmp_path/'events.lhe';source.write_text(raw)
    pop=w.scan(source,expected_events=3,expected_groups=c['weights']['groups'],maximum_bytes=100000,journal_path=tmp_path/'weights.jsonl')
    m.check_weight_definitions(c,pop)
    pop['native_weight_header_definitions'][0]['attributes'].pop('MUR',None)
    pop['native_weight_header_definitions'][0]['description']='muR=2 muF=1'
    with pytest.raises(ValueError,match='differs'):m.check_weight_definitions(c,pop)


def test_goal_binding_preserves_original_request_and_external_contract_in_unapproved_plan(tmp_path):
    from ravel.workflow import task_completion
    req,c=setup_request(tmp_path)
    prompt='Generate matched events AND preserve decay and all variations; then reinterpret all signal and control regions.'
    requirements=task_completion.initial_requirements(prompt)
    requirements['assignments']=[{'id':'generation','purpose':'Generate source-bound events as one part of the original request',
                                  'coverage':[{'obligation_id':'original-request','criteria':{'request':prompt}}]}]
    from ravel.workflow import route_prompt
    original_contract=route_prompt.route(prompt);original_contract['task_requirements']=requirements
    contract=write(tmp_path/'original/task_contract.json',original_contract)
    contract['size']=Path(contract['path']).stat().st_size
    req['goal_binding']={'contract':contract,'assignment_id':'generation'}
    files=p.graph_inputs(req,tmp_path);assert Path(contract['path']) in files
    result=p.prepare(req,base_dir=tmp_path,output_dir=tmp_path/'prepared',presented_pins=[pin(x) for x in files])
    spec=json.loads((tmp_path/'prepared/science.json').read_text())
    assert spec['goal_binding']==req['goal_binding'] and result['execution_authorized'] is False
    assert not (tmp_path/'prepared/task_contract.json').exists()
    # The routed parent is a production objective. A fixed generation bound to it is
    # refused as an ordinary plan and is planned only as a declared same-process pilot.
    parent=Path(contract['path']).read_bytes()
    assert original_contract['compute_plan'] in ('full','scan')
    with pytest.raises(ValueError,match='same-process measured pilot'):
        science.plan(tmp_path/'refused',tmp_path/'prepared/science.json')
    assert not (tmp_path/'refused/inputs/science-plan.json').exists()
    assert not (tmp_path/'refused/inputs/science-approval.json').exists()
    from ravel.workflow import generation_efficiency
    def sized(path):return {**pin(path),'size':path.stat().st_size}
    production=sized(tmp_path/'prepared/science.json')
    write(tmp_path/'prepared/efficiency-request.json',{'schema_version':1,'kind':'generation_efficiency_request',
        'production':production,'pilots':[],'scaling_assumption':None,'wall_margin':None,'precision':None})
    write(tmp_path/'prepared/pilot.json',{**spec,'generation_efficiency':{'schema_version':1,'purpose':'pilot',
        'request':sized(tmp_path/'prepared/efficiency-request.json'),'forecast':None}})
    prepared=generation_efficiency.prepare_pilot(production,sized(tmp_path/'prepared/pilot.json'),tmp_path/'run',base_dir=tmp_path)
    assert prepared['approved'] is False and prepared['executed'] is False
    plan=science.verify_plan(tmp_path/'run',approved=False)
    assert plan['mode']=='model-events' and not (tmp_path/'run/inputs/science-approval.json').exists()
    assert str(Path(contract['path']).resolve()) in plan['stage_binding']['input_snapshot']
    assert Path(contract['path']).read_bytes()==parent
    projection=task_completion.binding_projection(spec['goal_binding'],base_dir=tmp_path)
    assert projection['original_request']==prompt and projection['parent_task_complete'] is False


@pytest.mark.parametrize('target',['input','specification','commitment'])
def test_preparation_drift_after_commitment_never_returns_or_leaves_success_receipt(tmp_path,monkeypatch,target):
    req,c=setup_request(tmp_path);original=Path.write_bytes;changed=[]
    def mutate(path,data):
        result=original(path,data)
        if path.name=='preparation.pending.json':
            destination=Path(c['cards']['parameter']['path']) if target=='input' else tmp_path/'prepared/science.json' if target=='specification' else path
            original(destination,destination.read_bytes()+b' ');changed.append(destination)
        return result
    monkeypatch.setattr(Path,'write_bytes',mutate)
    with pytest.raises(ValueError):p.prepare(req,base_dir=tmp_path,output_dir=tmp_path/'prepared')
    assert len(changed)==1 and not (tmp_path/'prepared/preparation.json').exists()


def test_preparation_cannot_write_inside_original_model_tree(tmp_path):
    req,c=setup_request(tmp_path);out=Path(c['model_tree']['root'])/'would-mutate-source'
    with pytest.raises(ValueError,match='original generator'):p.prepare(req,base_dir=tmp_path,output_dir=out)
    assert not out.exists()


@pytest.mark.parametrize('cfg',[{'madgraph':{'run':{'use_syst':True}}},{'madgraph':{'run':{'ickkw':1}}},
                               {'madgraph':{'matching':{'scheme':'mlm'}}},{'generation':{'scheme':'fxfx'}}])
def test_legacy_nested_regime_never_disables_requested_physics(cfg):
    with pytest.raises(ValueError,match='model-events'):native_pipeline.require_legacy_regime(cfg)


def test_only_source_backed_pythia_auto_filename_transformation_is_allowed(tmp_path):
    c=config(tmp_path,'mlm');t=texts(c)
    t['pythia']=t['pythia'].replace('file = auto','file = tag_1_pythia8_events.hepmc')
    m.check_cards(c,t,observed=True)
    with pytest.raises(ValueError):m.check_cards(c,t)
    t['pythia']=t['pythia'].replace('tag_1_pythia8_events.hepmc','unbound.hepmc')
    with pytest.raises(ValueError):m.check_cards(c,t,observed=True)


@pytest.mark.parametrize('ceiling',[None,3])
def test_existing_native_executor_default_keeps_zero_events_and_new_route_keeps_count_unknown(tmp_path,monkeypatch,ceiling):
    from ravel.physics import reinterpret_db
    class InertProcess:
        pid=999999999;returncode=0
        def poll(self):return 0
    monkeypatch.setattr(reinterpret_db.subprocess,'Popen',lambda *a,**k:InertProcess())
    monkeypatch.setattr(reinterpret_db.os,'killpg',lambda *a,**k:None)
    doc={'max_seconds':30,'max_ram_mib':512}
    result=reinterpret_db.execute_native(['INERT-NOT-LAUNCHED'],tmp_path,doc,generated_event_ceiling=ceiling)
    assert result['new_events_generated']==(0 if ceiling is None else None)
    if ceiling is not None:
        assert result['generated_event_ceiling']==3 and result['event_observation']=='pending adapter population census'
    else:assert 'generated_event_ceiling' not in result


@pytest.mark.parametrize('ceiling',[True,0,-1])
def test_invalid_native_event_ceiling_refuses_before_command_or_file(tmp_path,ceiling):
    from ravel.physics import reinterpret_db
    with pytest.raises(ValueError,match='positive'):reinterpret_db.execute_native(['NEVER-LAUNCH'],tmp_path,{'max_seconds':30,'max_ram_mib':512},generated_event_ceiling=ceiling)
    assert not list(tmp_path.iterdir())


def test_pythia_prefix_alone_is_not_a_bound_mg_integrated_matching_interface(tmp_path):
    c=config(tmp_path,'mlm');c['runtime']['options']['mg5amc_py8_interface_path']=None
    with pytest.raises(ValueError,match='MG5aMC_PY8 interface'):m.validate_config(c)
