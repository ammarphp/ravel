"""Pure source/transport adversaries, with inert existing-Graph review fixtures.

The receipt double exercises gate arguments and refusals. It is never an actual
critic/verifier review, native integration, numerical parity or science result.
"""
import ast
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest

from ravel.physics import native_statistical_construction as n, native_likelihood as native
from ravel.workflow import agent_graph, science
from ravel.workflow.state_io import atomic_json, read_json
from statistical_construction_fixture import fixture as law_fixture


@pytest.mark.parametrize('attack',['height_underflow','height_overflow','collapsed_edges','width_overflow','represented_integral_overflow','represented_integral_underflow'])
def test_native_representation_refuses_before_any_public_population(tmp_path,monkeypatch,attack):
    d,_=fixture(tmp_path,monkeypatch,population=True)
    # Apply the malformed geometry to the final cell and authenticate its source
    # buffers directly below, preserving the complete 16-cell input population.
    target=d['cells'][-1]
    if attack=='height_underflow':edges=[str(10**100),str(2*10**100),str(4*10**100)];values=['0.'+'0'*299+'1','0.'+'0'*299+'2']
    elif attack=='height_overflow':edges=[str(F(1,10**308)),str(F(2,10**308)),str(F(4,10**308))];values=[str(10**308),str(10**308)]
    elif attack=='collapsed_edges':edges=['1','1.'+'0'*99+'1','2'];values=['2','3']
    elif attack=='width_overflow':edges=[str(-10**308),'0',str(10**308)];values=['2','3']
    elif attack=='represented_integral_overflow':edges=[str(10**308),str(10**308+10**292),str(10**308+3*10**292)];values=[str(10**308),'3']
    else:edges=[str(F(25,10**325)),str(F(123,10**325)),str(F(246,10**325))];values=[str(F(25,10**325)),str(F(25,10**325))]
    target['observables'][0]['bounds']=[edges[0],edges[-1]]
    # Each changed final-cell template gets its own real original source file;
    # earlier cells retain their original member/source/variation bytes.
    for node in target['nodes']:
        if node['kind']=='template':
            t=node['template'];t['edges']=edges;t['values']=values
            original=t['source_path'];t['source_path']='final-'+original
            path=tmp_path/'original'/t['source_path'];path.write_bytes(n.encoded({k:t[k] for k in ('edges','values','semantics')}))
            d['source_capsule']['files'].append({'path':t['source_path'],'sha256':pin(path)['sha256'],'role':'data'})
    for term in target['components']:term['bin_windows']=[list(target['observables'][0]['bounds']) for _ in target['law']['bins']]
    subject=Path(d['review']['subject']['path']);subject.write_bytes(n.subject(d));d['review']['subject']=pin(subject)
    recipe=tmp_path/'recipe.json';recipe.write_bytes(n.encoded(d));out=tmp_path/'prepared'
    with pytest.raises(ValueError):n.run({'input':str(recipe)},tmp_path,out)
    assert not out.exists() and not list(tmp_path.glob('.native-statistical-construction-*'))


def _representation_domain(document,edges):
    cell=document['cells'][0];cell['observables'][0]['bounds']=[edges[0],edges[-1]]
    for node in cell['nodes']:
        if node['kind']=='template':node['template']['edges']=list(edges)
    for term in cell['components']:term['bin_windows']=[list(cell['observables'][0]['bounds']) for _ in cell['law']['bins']]


def _representation_prepare(document,tmp_path):
    originals=Path(document['source_capsule']['root'])
    facts={f['path']:f for f in document['source_capsule']['files']}
    for node in document['cells'][0]['nodes']:
        if node['kind']=='template':
            t=node['template'];path=originals/t['source_path']
            path.write_bytes(n.encoded({k:t[k] for k in ('edges','values','semantics')}));facts[t['source_path']]['sha256']=pin(path)['sha256']
    subject=Path(document['review']['subject']['path']);subject.write_bytes(n.subject(document));document['review']['subject']=pin(subject)
    recipe=tmp_path/'representation.json';recipe.write_bytes(n.encoded(document))
    result=n.run({'input':str(recipe)},tmp_path,tmp_path/'representation-output')
    assert result['status']=='passed' and result['physics_validated'] is False
    return Path(result['cells'][0]['bridge']['path']).read_text()


def test_exact_large_domain_midpoint_and_positive_native_template_heights_are_finite(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch)
    _representation_domain(d,[str(10**308),str(125*10**306),str(15*10**307)])
    raw=_representation_prepare(d,tmp_path)
    strings=[x.value for x in ast.walk(ast.parse(raw)) if isinstance(x,ast.Constant) and isinstance(x.value,str)]
    literal=next(v for v in strings if v.startswith('massObs['));values=list(map(float,literal.split('[',1)[1][:-1].split(',')))
    assert values==[1.25e308,1e308,1.5e308] and all(math.isfinite(v) for v in values)
    for loop in ast.walk(ast.parse(raw)):
        if isinstance(loop,ast.For) and any(isinstance(y,ast.Attribute) and y.attr=='SetBinContent' for y in ast.walk(loop)):
            heights=ast.literal_eval(loop.iter.args[0]);assert all(math.isfinite(v) and v>0 for v in heights)


@pytest.mark.parametrize('values',[['0','1/1024'],['-2','3'],['0.'+'0'*99+'1','0.'+'0'*99+'2']])
def test_representable_zero_signed_and_tiny_source_bin_integrals_remain_literal(tmp_path,monkeypatch,values):
    d,_=fixture(tmp_path,monkeypatch);_representation_domain(d,['1','3','4'])
    for node in d['cells'][0]['nodes']:
        if node['kind']=='template':node['template']['values']=values
    raw=_representation_prepare(d,tmp_path)
    loops=[x for x in ast.walk(ast.parse(raw)) if isinstance(x,ast.For) and any(isinstance(y,ast.Attribute) and y.attr=='SetBinContent' for y in ast.walk(x))]
    assert len(loops)==3
    reference=[float(F(values[0])/2),float(F(values[1]))]
    for loop in loops:assert ast.literal_eval(loop.iter.args[0])==reference


def pin(p):
    return {'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}


def fixture(tmp_path, monkeypatch, *, population=False):
    law = law_fixture(tmp_path, True)
    source = tmp_path/'original'; source.mkdir()
    code = b'class OriginalShape {};\n// original observable and parameter mapping\n// original full nominal/up/down morph mapping\n'
    (source/'Original.cc').write_bytes(code)
    capsule_files = [{'path':'Original.cc','sha256':pin(source/'Original.cc')['sha256'],'role':'compile'}]
    nodes = []
    for name,values in [('nominal',['2','3']),('up',['4','6']),('down',['1','3/2'])]:
        t = {'edges':['1','2','4'],'values':values,'semantics':'absolute_bin_integrals_piecewise_constant'}
        path=name+'.json'; (source/path).write_bytes(n.encoded(t))
        capsule_files.append({'path':path,'sha256':pin(source/path)['sha256'],'role':'data'})
        nodes.append({'name':name,'kind':'template','class':'RooHistFunc','depends_on':['massObs'],'members':['morph_source'],
                      'template':{'source_path':path,'observable':'massObs',**t}})
    nodes += [{'name':'morph','kind':'factory','class':'RooAddition','depends_on':['nominal','up','down'],'members':['morph_source'],
               'factory':'sum::morph(nominal,up,down)'},
              {'name':'interference','kind':'factory','class':'RooFormulaVar','depends_on':['massObs','slope'],'members':['class_source'],
               'factory':'expr::interference("@0*@1",massObs,slope)'}]
    members = [{'id':name,'path':'Original.cc','first_line':i,'last_line':i,'sha256':hashlib.sha256(code.splitlines(keepends=True)[i-1]).hexdigest(),'depends_on':deps}
               for i,name,deps in [(1,'class_source',['coordinate_source']),(2,'coordinate_source',[]),(3,'morph_source',['class_source'])]]
    tool=tmp_path/'tool';tool.write_text('#!/bin/sh\nexit 99\n');tool.chmod(0o755)
    lib=tmp_path/'libHiggsAnalysisCombinedLimit.so';lib.write_bytes(b'inert library, never loaded')
    module=tmp_path/'PhysicsModel.py';module.write_text('# inert module, never imported\n')
    version=tmp_path/'combine.cc';version.write_text('std::string combineTagString = "v9.2.1";\nif(datacard == "") { cerr << "Missing datacard file" << endl; return 1002; }\nif (seed == -1) {}\ncombiner.applyOptions(vm);\n')
    runtime={'tools':{k:pin(tool) for k in ('combine','text2workspace','python')},'artifacts':[pin(lib),pin(module)],'environment':{'PATH':'/usr/bin:/bin'},
             'expected':{'combine_version':'9.2.1','root_version':'6.22/00','cmssw_version':None,'architecture':'x86_64','custom_classes':['RooParametricHist']},
             'transport':{'kind':'local'},'version_proof':{'kind':'missing_datacard_diagnostic','source':pin(version),'expected_returncode':234}}
    fit={'method':'MultiDimFit','data':'observed','poi':'c','domain':['-2','2'],'mass':120,'seed':12345,'points':None,'minimizer':None,'fixed_witness_points':['0','1'],'reference_quantiles':None,
         'saved_fit':{'algorithm':'none','required_object':'multidimfit.ravel.root:fit_mdf','maximum_edm':.001}}
    axes={'mass':['120','240'] if population else ['120'],'width':['narrow','wide'] if population else ['declared_width'],
          'hypothesis':['signal','interference'] if population else ['source_hypothesis'],'candidate':['first','second'] if population else ['source_candidate']}
    cell={'id':'cell','coordinates':{},'law':law,'parameters':[{'name':'slope','initial':'0','bounds':['-2','2'],'fixed':False,'unit':'dimensionless','member':'coordinate_source'}],
          'observables':[{'name':'massObs','bounds':['1','4'],'unit':'GeV','member':'coordinate_source'}], 'nodes':nodes,
          'integration':{'eps_abs':'1e-8','eps_rel':'1e-8','max_steps':12,'policy':'ROOT6.22-RooIntegrator1D-original-default-zero-policy'}, 'fit':fit}
    common={'observable':'massObs','bin_windows':[['1','2'],['2','4'],['1','3'],['3','4']], 'log_response':[['1','-1'],['0','0'],['1/2','0'],['0','1']], 'meaning':'Complete supplied SR/CR leakage and shared auxiliary response'}
    cell['components']=[{**deepcopy(common),'id':'resonance','node':'morph','normalization':'full_domain','measure':'density','role':'signal','coefficients':['6','2','3','1'],'powers':{'c':2}},
                        {**deepcopy(common),'id':'signed','node':'interference','normalization':'absolute_integral','measure':'signed_density','role':'interference','coefficients':['-1','2','-3','1'],'powers':{'c':1}}]
    cells=[]
    for i,values in enumerate(itertools.product(*(axes[a] for a in n.AXES))):
        row=deepcopy(cell);row['id']='cell'+str(i);row['coordinates']=dict(zip(n.AXES,values));cells.append(row)
    review=tmp_path/'existing-review';review.mkdir();(review/'state.lock').write_bytes(b'');(review/'state.json').write_bytes(b'inert existing review fixture\n')
    d={'schema_version':1,'kind':n.KIND,'question':'Construct the complete original native likelihood without a prebuilt card.','scope':'All original cells and full four-region counting/auxiliary law',
       'population':axes,'cells':cells,'source_capsule':{'schema_version':1,'kind':'analysis-source-capsule','framework':'cpp','routine':'OriginalShape',
       'source':{'repository':'supplied','revision':None,'description':'Inert source fixture, not actual independent review'},'root':str(source),'files':capsule_files,
       'layout':{'include_dirs':['.'],'asset_dirs':['.']},'dependencies':[{'name':'original','kind':'source','status':'resolved','files':['Original.cc'],'reason':'Explicit complete original member mapping'}],
       'dependency_review':{'complete':True,'description':'Synthetic gate control only'},'submodules':[]},'members':members,'runtime':runtime,'max_seconds':30,
       'assumptions':['Synthetic source/buildout control; no ROOT/native or scientific qualification.'],'review':{}}
    subject=tmp_path/'subject.json';subject.write_bytes(n.subject(d))
    d['review']={'root':str(review),'files':[{'path':p.name,'sha256':pin(p)['sha256']} for p in sorted(review.iterdir())], 'subject':pin(subject),
                 'critic':{'node':'critic','packet_sha256':'1'*64},'verifier':{'node':'verifier','packet_sha256':'2'*64}}
    seen=[]
    def receipt(root,node,**kwargs):
        seen.append((root,node,kwargs))
        assert kwargs=={'expected_subject_sha256':d['review']['subject']['sha256'],'expected_packet_sha256':d['review'][node]['packet_sha256'],'require_exact_subject':True}
        return {'role':node,'public_value':{'kind':'native-source-graph-review/v1','decision':'source_clear','subject_sha256':d['review']['subject']['sha256'],
                'members':[r['id'] for r in members],'unresolved':[],'physics_validated':False,'numerical_equivalence_qualified':False}}
    monkeypatch.setattr(agent_graph,'model_receipt',receipt)
    return d,seen


def test_ordinary_constructor_emits_every_real_cell_bundle_and_tasks(tmp_path,monkeypatch):
    d,seen=fixture(tmp_path,monkeypatch,population=True)
    cp=tmp_path/'recipe.json';atomic_json(cp,d)
    before={p:pin(p) for p in (tmp_path/'original').iterdir()}
    result=n.run({'input':str(cp)},tmp_path,tmp_path/'prepared')
    assert result['status']=='passed' and result['physics_validated'] is False and result['native_calls']==result['fit_calls']==0
    assert len(result['cells'])==16 and [r['coordinates'] for r in result['cells']]==[c['coordinates'] for c in d['cells']]
    for row in result['cells']:
        path=Path(row['task']['input']); cfg=read_json(path)
        assert row['parent_scope']==d['scope'] and row['max_seconds']==d['max_seconds']
        assert cfg['fit']==next(c['fit'] for c in d['cells'] if c['id']==row['id'])
        parsed=native._configuration(row['task'],path.parent)
        assert parsed[8]['kind']==n.KIND and parsed[9]['numerical_equivalence_qualified'] is False
        assert set(parsed[2])=={n.CARD,'source/Original.cc','source/nominal.json','source/up.json','source/down.json'}
        assert cfg['model']['card']==n.CARD # native cwd is the preserved original relative source/asset tree
        build,_=native.commands(cfg,parsed[3],path.parent,has_response=True)
        assert Path(build[1]).parent==path.parent/'source'
        assert Path(row['card']['path']).read_bytes()==n.datacard(d,row['id'])
        assert 'source_graph' in cfg['model'] and 'construction' not in cfg['model']
        paths=science.task_inputs({'mode':'native-likelihood','task':row['task'],'max_seconds':30},path.parent)
        assert cp.parent/'original/Original.cc' in paths and Path(n.__file__) in paths
    assert all(pin(p)==v for p,v in before.items()) and {node for _,node,_ in seen}=={'critic','verifier'}


def test_ordinary_preparation_mode_and_session_inputs(tmp_path,monkeypatch):
    from ravel.workflow import execution
    d,_=fixture(tmp_path,monkeypatch);cp=tmp_path/'recipe.json';atomic_json(cp,d)
    spec={'mode':'native-statistical-construction','task':{'input':str(cp)},'max_seconds':30}
    assert science.adapter(spec) is n and science._new_capability(spec)
    n.validate(spec['task'])
    session=execution._validation_session(tmp_path)
    try:
        paths=science.task_inputs(spec,tmp_path,_session=session)
        assert cp in paths and tmp_path/'existing-review/state.lock' in paths
        assert n.execution_seconds(spec['task'],tmp_path,_session=session)==30
        session.finish()
    finally:
        session.close()
    assert 'native-statistical-construction' in science.MODES


def test_source_gate_binds_whole_recipe_full_members_variations_and_reviews(tmp_path,monkeypatch):
    d,seen=fixture(tmp_path,monkeypatch); paths=n.source_inputs(d,tmp_path)
    assert {tmp_path/'original'/v for v in ('Original.cc','nominal.json','up.json','down.json')} <= set(paths)
    assert [x[1] for x in seen]==['critic','verifier']
    changed=deepcopy(d);changed['runtime']['expected']['custom_classes'].append('HiddenClass')
    with pytest.raises(ValueError,match='subject'): n.source_inputs(changed,tmp_path)


@pytest.mark.parametrize('field,value',[('physics_validated',True),('numerical_equivalence_qualified',True),('unresolved',['missing']),('decision','pending'),('members',['class_source'])])
def test_transport_review_never_inherits_scientific_or_incomplete_clearance(tmp_path,monkeypatch,field,value):
    d,_=fixture(tmp_path,monkeypatch);original=agent_graph.model_receipt
    def bad(*args,**kwargs):
        row=original(*args,**kwargs);row['public_value'][field]=value;return row
    monkeypatch.setattr(agent_graph,'model_receipt',bad)
    with pytest.raises(ValueError,match='critic/verifier'): n.source_inputs(d,tmp_path)


@pytest.mark.parametrize('change',[
    lambda d:d['cells'].pop(),
    lambda d:d['population']['mass'].append('missing_mass'),
    lambda d:d['cells'][0]['coordinates'].update(width='invented_width'),
    lambda d:d['cells'][0]['parameters'][0].update(name='c'),
    lambda d:d['cells'][0]['parameters'][0].update(name='MH'),
    lambda d:d['cells'][0]['observables'][0].update(name='slope'),
    lambda d:d['cells'][0]['nodes'][0].update(name='c'),
    lambda d:d['cells'][0]['nodes'][3]['depends_on'].append('missing'),
    lambda d:d['cells'][0]['nodes'][3]['depends_on'].append('morph'),
    lambda d:d['cells'][0]['nodes'][4]['depends_on'].remove('slope'),
    lambda d:d['cells'][0]['nodes'].append({'name':'unused','kind':'factory','class':'RooFormulaVar','depends_on':['slope'],'members':['class_source'],'factory':'expr::unused("@0",slope)'}),
    lambda d:d['members'][0]['depends_on'].append('morph_source'),
    lambda d:d['members'][0]['depends_on'].append('missing'),
    lambda d:d['members'].append({'id':'unused_member','path':'Original.cc','first_line':1,'last_line':1,'sha256':'1'*64,'depends_on':[]}),
    lambda d:d['cells'][0]['nodes'][3].update(factory='sum::different(nominal,up,down)'),
    lambda d:d['cells'][0]['nodes'][0]['template']['edges'].pop(),
    lambda d:d['cells'][0]['nodes'][0]['template']['values'].append('0'),
    lambda d:d['cells'][0]['nodes'][0]['template']['edges'].__setitem__(0,'0'),
    lambda d:d['cells'][0]['components'][0]['bin_windows'].pop(),
    lambda d:d['cells'][0]['components'][0]['coefficients'].pop(),
    lambda d:d['cells'][0]['components'][0]['log_response'][0].pop(),
    lambda d:d['cells'][0]['components'][1].update(normalization='full_domain'),
    lambda d:d['cells'][0]['components'][0]['coefficients'].__setitem__(0,'-1'),
    lambda d:d['cells'][0]['components'][0]['bin_windows'].__setitem__(0,['0','2']),
    lambda d:d['cells'][0]['components'][0]['powers'].update(hidden=1),
    lambda d:d['cells'][0]['components'][0]['powers'].update(c=-1),
    lambda d:d['cells'][0]['integration'].update(max_steps=21),
    lambda d:d['cells'][0]['integration'].update(eps_rel='0'),
    lambda d:d['cells'][0]['integration'].update(policy='fixed_midpoints'),
    lambda d:d['source_capsule']['dependency_review'].update(complete=False),
    lambda d:d['source_capsule']['files'].append({'path':'ravel_graph_model.txt','sha256':'1'*64,'role':'configuration'}),
    lambda d:d['cells'][0]['fit'].update(domain=['0','2']),
    lambda d:d['cells'][0]['fit'].update(data='asimov_background'),
])
def test_complete_source_population_graph_and_measure_refusals(tmp_path,monkeypatch,change):
    d,_=fixture(tmp_path,monkeypatch);change(d)
    with pytest.raises(ValueError): n.validate_document(d)


@pytest.mark.parametrize('target',['Original.cc','nominal.json','up.json','down.json'])
def test_original_full_source_and_each_variation_byte_drift_refused(tmp_path,monkeypatch,target):
    d,_=fixture(tmp_path,monkeypatch);(tmp_path/'original'/target).write_bytes(b'changed\n')
    with pytest.raises(ValueError,match='pin changed'):n.source_inputs(d,tmp_path)


def test_template_buffer_is_consumed_exactly_and_member_span_not_declaration_only(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch);d['cells'][0]['nodes'][0]['template']['values'][0]='999'
    with pytest.raises(ValueError,match='consumed template'):n.source_inputs(d,tmp_path)


def test_member_span_and_review_snapshot_drift_are_refused(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch);d['members'][0]['sha256']='1'*64
    with pytest.raises(ValueError,match='span'): n.source_inputs(d,tmp_path)
    d['members'][0]['sha256']=hashlib.sha256((tmp_path/'original/Original.cc').read_bytes().splitlines(keepends=True)[0]).hexdigest()
    (tmp_path/'existing-review/new-dependency').write_bytes(b'new')
    with pytest.raises(ValueError,match='snapshot'): n.source_inputs(d,tmp_path)


@pytest.mark.parametrize('window,expected',[(['1','4'],F(5)),(['3/2','3'],F(5,2)),(['2','4'],F(3)),(['0','1'],F(0)),(['3','5'],F(3,2))])
def test_unequal_width_template_reference_uses_complete_bin_integrals(window,expected):
    t={'edges':['1','2','4'],'values':['2','3']}
    assert n.template_integral(t,window)==expected


def test_signed_zero_full_integral_is_never_normalized_or_clipped(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch)
    t={'edges':['1','2','4'],'values':['-2','2']}
    assert n.template_integral(t,['1','4'])==0 and n.template_integral(t,['1','2'])==-2
    source=n.native_bridge_source(n.response(d,'cell0'));tree=ast.parse(source)
    literals=[node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
    assert any('ravel_graph_den_0' in v for v in literals) and not any('ravel_graph_den_1' in v for v in literals)
    assert any(v.startswith('expr::ravel_graph_term_1_0("-1*@0') for v in literals)
    assert any(v.startswith('sum::ravel_mean_0(ravel_base_mean_0,ravel_graph_term_0_0,ravel_graph_term_1_0)') for v in literals)
    assert 'NormSet' not in source and 'fitTo' not in source and 'max(' not in source
    assert source.count("setConstant(True)")==4 # fixed base kappa, two auxiliary observations, integration observable
    assert n.datacard(d,'cell0').count(b' param ')==2 and n.datacard(d,'cell0').count(b'slope flatParam')==1
    assert n.response(d,'cell0')['base']==n.regional.response(d['cells'][0]['law'])


def test_generated_bridge_original_defaults_and_no_hidden_integration_fit_coordinate(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch);raw=n.native_bridge_source(n.response(d,'cell0'))
    ast.parse(raw);ast.parse(native.NATIVE_PROBE)
    assert 'setRealValue(\'minSteps\', 999)' in raw and 'setRealValue(\'fixSteps\', 0)' in raw
    assert "setCatLabel('sumRule', 'Trapezoid')" in raw and "setCatLabel('extrapolation', 'Wynn-Epsilon')" in raw
    assert "SetBinContent(i, v)" in raw and '[2.0, 1.5]' in raw
    assert "extraNuisances.append(w.var('massObs'))" not in raw and "setUnit('GeV')" in raw
    assert 'createIntegral' in raw and 'NumIntConfig' in raw


def test_observed_native_route_refuses_expected_derivative_calibration_and_rebound_resources(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch);p=tmp_path/'recipe.json';atomic_json(p,d)
    result=n.run({'input':str(p)},tmp_path,tmp_path/'prepared');cp=Path(result['cells'][0]['task']['input']);cfg=read_json(cp)
    for field,value in [('calibration',{}),('expected_data',{}),('max_seconds',29)]:
        changed=deepcopy(cfg);changed[field]=value;atomic_json(cp,changed)
        with pytest.raises(ValueError): native._configuration({'input':str(cp)},cp.parent)
    changed=deepcopy(cfg);changed['model']['files'].pop();atomic_json(cp,changed)
    with pytest.raises(ValueError,match='omitted'):native._configuration({'input':str(cp)},cp.parent)


def test_constructor_requires_prospective_v2_plan_and_runs_no_worker(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch);p=tmp_path/'recipe.json';atomic_json(p,d)
    spec={'schema_version':1,'mode':'native-statistical-construction','source':d['question'],'assumptions':d['assumptions'],'max_seconds':30,
          'approval_mode':'scripted_yes','task':{'input':str(p)}}
    cp=tmp_path/'spec.json';atomic_json(cp,spec)
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'run',cp)
    assert not (tmp_path/'run').exists()


def test_population_overflow_is_refused_before_materializing_cartesian_cells(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch)
    for axis in n.AXES:d['population'][axis]=[str(i) for i in range(30)]
    with pytest.raises(ValueError,match='bounded complete population'):n.validate_document(d)


def structural_fixture(tmp_path,monkeypatch):
    from statistical_construction_fixture import count_product_fixture, state
    d,_=fixture(tmp_path,monkeypatch);r=n.response(d,'cell0');cell=d['cells'][0]
    witnesses=[]
    for point in cell['fit']['fixed_witness_points']:
        values=state(cell['law']);values['c']['value']=float(F(point))
        values['slope']={'value':0.,'minimum':-2.,'maximum':2.,'constant':False}
        witnesses.append({'point':point,'raw_nll_at_source_nuisance_values':123.,'construction_state':values,
                          'scales':{name:37.+i for i,name in enumerate(r['functions'])}})
    probe=count_product_fixture(cell['law'],witnesses)
    probe['workspace']['nuisances'].append('slope')
    probe['construction_linkage']['coordinate_domains']['slope']={'minimum':-2.,'maximum':2.,'constant':False}
    probe['source_graph_nodes']={node['name']:{'class':node['class'],'servers':sorted(node['depends_on'])} for node in cell['nodes']}
    probe['source_graph_observables']={'massObs':{'bounds':[1.,4.],'unit':'GeV','constant':True}}
    cfg={'fit':cell['fit'],'model':{'regions':[{'channel':b['id'],'role':b['role']} for b in cell['law']['bins']]}}
    return probe,cfg,r


def test_source_graph_structural_witness_cannot_inherit_regional_numerical_parity(tmp_path,monkeypatch):
    probe,cfg,r=structural_fixture(tmp_path,monkeypatch)
    # Deliberately arbitrary finite native values cannot become a source numeric
    # reference. This is only a transport/data/graph postcondition.
    rows=native._check_workspace(probe,cfg,r)
    assert len(rows)==8 and all(x['numerical_equivalence_qualified'] is False and x['expected_data_qualified'] is False and x['calibration_qualified'] is False for x in rows)
    assert not any('reference_mean' in x or 'exact_rational' in x or 'tolerance' in x for x in rows)


@pytest.mark.parametrize('change',[
    lambda p:p['source_graph_nodes'].pop('up'),
    lambda p:p['source_graph_nodes']['nominal'].update(**{'class':'RooHistPdf'}),
    lambda p:p['source_graph_nodes']['morph']['servers'].remove('down'),
    lambda p:p['source_graph_nodes']['interference']['servers'].append('hidden_coordinate'),
    lambda p:p['source_graph_observables']['massObs'].update(unit='TeV'),
    lambda p:p['source_graph_observables']['massObs'].update(constant=False),
    lambda p:p['source_graph_observables']['massObs'].update(bounds=[1.,3.]),
    lambda p:p['workspace']['nuisances'].append('massObs'),
    lambda p:p['workspace']['global_observables'].pop(),
    lambda p:p['construction_observations']['counts'].pop('D'),
    lambda p:p['fixed_witnesses'][0]['construction_state'].pop('slope'),
    lambda p:p['fixed_witnesses'][0]['construction_state']['slope'].update(value=3.),
    lambda p:p['fixed_witnesses'][0]['construction_state']['kappa'].update(value=0.),
    lambda p:p['fixed_witnesses'][0]['scales'].update(ravel_mean_0=-1.),
    lambda p:p['fixed_witnesses'][0]['scales'].pop('ravel_mean_3'),
])
def test_structural_native_graph_full_law_and_name_ownership_adversaries(tmp_path,monkeypatch,change):
    probe,cfg,r=structural_fixture(tmp_path,monkeypatch);change(probe)
    with pytest.raises(ValueError):native._check_workspace(probe,cfg,r)


def test_actual_unapproved_v2_science_plan_reaches_constructor_without_card_or_worker(tmp_path,monkeypatch):
    from test_physics_review import policy
    d,_=fixture(tmp_path,monkeypatch);recipe=tmp_path/'recipe.json';atomic_json(recipe,d)
    review=policy();review.update(max_redos=0,allowed_stages=['science'],allowed_changed_paths=[])
    spec={'schema_version':2,'mode':'native-statistical-construction','source':d['question'],'assumptions':d['assumptions'],'max_seconds':30,
          'approval_mode':'scripted_yes','task':{'input':str(recipe)},'max_attempts':1,
          'review_policy':{'schema_version':1,'policy':review,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    cp=tmp_path/'spec.json';atomic_json(cp,spec)
    plan=science.plan(tmp_path/'unapproved',cp)
    assert plan['mode']=='native-statistical-construction' and plan['max_attempts']==1 and plan['execution_task']=={'input':str(recipe)}
    assert not (tmp_path/'unapproved'/science.APPROVAL).exists() and not (tmp_path/'unapproved/outputs').exists()
    assert str(tmp_path/'original/up.json') in plan['stage_binding']['inputs']


def test_generated_probe_single_region_source_graph_has_count_vector_not_invented_category():
    tree=ast.parse(native.NATIVE_PROBE)
    outer=next(x for x in tree.body if isinstance(x,ast.If) and 'len(sys.argv)' in ast.unparse(x.test))
    branch=next(x for x in outer.body if isinstance(x,ast.If) and ast.unparse(x.test)=='cat')
    for model,expected in [({'source_graph':{}},[]),({'construction':{}},[]),({},['only'])]:
        cfg={'schema_version':2,'model':{'regions':[{'channel':'only'}],**model}}
        ns={'cat':None,'channels':[],'cfg':cfg};exec(compile(ast.Module(body=[branch],type_ignores=[]),'actual-channel-collector','exec'),ns)
        assert ns['channels']==expected


def test_original_prepared_custom_libraries_load_before_identity_for_new_source_graph_only():
    import os
    tree=ast.parse(native.NATIVE_PROBE)
    branch=next(x for x in tree.body if isinstance(x,ast.For) and ast.unparse(x.iter)=="cfg['runtime']['artifacts']")
    for model,expected in [({'source_graph':{}},['/p/libHiggsAnalysisCombinedLimit.so','/p/original_custom.so']),({},['/p/libHiggsAnalysisCombinedLimit.so'])]:
        loaded=[];root=SimpleNamespace(gSystem=SimpleNamespace(Load=lambda path:loaded.append(path) or 0))
        cfg={'model':model,'runtime':{'artifacts':[{'path':p} for p in ['/p/PhysicsModel.py','/p/libHiggsAnalysisCombinedLimit.so','/p/original_custom.so']]}}
        exec(compile(ast.Module(body=[branch],type_ignores=[]),'actual-library-load-source','exec'),{'cfg':cfg,'ROOT':root,'os':os})
        assert loaded==expected


def test_malformed_final_cell_leaves_no_partial_public_population(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch,population=True)
    # The recipe and inert review subject both bind this malformed final native
    # API request. The complete ordinary native parser must still refuse it.
    d['cells'][-1]['fit']['saved_fit']['maximum_edm']=-1
    subject=Path(d['review']['subject']['path']);subject.write_bytes(n.subject(d));d['review']['subject']=pin(subject)
    recipe=tmp_path/'recipe.json';atomic_json(recipe,d)
    target=tmp_path/'public-prepared'
    with pytest.raises(ValueError,match='EDM'):
        n.run({'input':str(recipe)},tmp_path,target)
    assert not target.exists()
    staging=list(tmp_path.glob('.native-statistical-construction-*'))
    assert len(staging)==1 and (staging[0]/'cell0/task.json').is_file() and (staging[0]/'cell15/native.json').is_file()


def test_actual_emitted_bridge_inert_api_full_domain_density_signed_absolute_and_total(tmp_path,monkeypatch):
    """Execute emitted Python with an analytic inert API, never ROOT or Combine.

    Unequal-width template bins and x*slope have independently known integrals.
    This catches lowered mean/normalization/coordinate wiring, not native parity.
    """
    d,_=fixture(tmp_path,monkeypatch);compiled=n.response(d,'cell0');objects={};seen=[]
    class Var:
        def __init__(self,name,value,lo,hi):self.name=name;self.value=value;self.bounds=(lo,hi);self.ranges={}
        def setConstant(self,value):self.constant=value
        def setUnit(self,value):self.unit=value
        def setRange(self,name,lo,hi):self.ranges[name]=(lo,hi)
        def getVal(self):return self.value
        def GetName(self):return self.name
    class Function:
        def __init__(self,name,kind,args,formula=None):self.name=name;self.kind=kind;self.args=args;self.formula=formula
        def getVal(self):
            values=[objects[x].getVal() for x in self.args]
            if self.kind=='sum':return sum(values)
            text=re.sub(r'@(\d+)',lambda m:repr(values[int(m[1])]),self.formula)
            return eval(text,{'__builtins__':{},'pow':pow,'exp':math.exp})
        def setIntegratorConfig(self,config):seen.append(('config',self.name,config))
        def integral(self,lo,hi):
            if self.name=='interference':return objects['slope'].value*(hi*hi-lo*lo)/2
            if self.kind=='sum':return sum(objects[x].integral(lo,hi) for x in self.args)
            raise AssertionError('undeclared inert integral')
        def getObservables(self,variables):
            names={v.name for v in variables};pending=self.args[:];used=set()
            while pending:
                name=pending.pop()
                if name in names:used.add(name)
                elif hasattr(objects[name],'args'):pending.extend(objects[name].args)
            return [objects[n]for n in sorted(used)]
        def createIntegral(self,variables,config,range_name=None):
            assert len(variables)==1
            var=variables[0];bounds=var.ranges[range_name] if range_name is not None else var.bounds
            seen.append(('integral',self.name,bounds,'raw_no_NormSet'))
            return Integral(self,*bounds)
    class Integral:
        def __init__(self,fn,lo,hi):self.fn=fn;self.lo=lo;self.hi=hi
        def SetName(self,name):self.name=name
        def getVal(self):return self.fn.integral(self.lo,self.hi)
        def numIntRealVars(self):return []
    class Hist:
        def __init__(self,name,title,count,edges):self.edges=list(edges);self.values=[0.]*count
        def SetDirectory(self,value):assert value==0
        def SetBinContent(self,i,value):self.values[i-1]=value
    class Data:
        def __init__(self,name,title,variables,hist):self.hist=hist
    class HistFunction(Function):
        def __init__(self,name,title,variables,data,order):
            assert order==0;self.name=name;self.hist=data.hist;self.args=[v.name for v in variables]
        def integral(self,lo,hi):
            return sum(height*max(0.,min(hi,b)-max(lo,a)) for a,b,height in zip(self.hist.edges,self.hist.edges[1:],self.hist.values))
    class Config:
        def __init__(self,default):self.values={}
        def setEpsAbs(self,value):self.values['epsAbs']=value
        def setEpsRel(self,value):self.values['epsRel']=value
        def method1D(self):return self
        def setLabel(self,label):self.values['method']=label
        def getConfigSection(self,name):assert name=='RooIntegrator1D';return self
        def setRealValue(self,name,value):self.values[name]=value
        def setCatLabel(self,name,value):self.values[name]=value
    class Workspace:
        def var(self,name):return objects[name]
        def function(self,name):return objects.get(name)
        def pdf(self,name):return objects.get(name)
    w=Workspace();setattr(w,'import',lambda fn,*options:objects.__setitem__(fn.name,fn))
    class Builder:
        out=w
        def __init__(self):self.extraNuisances=[];self.sets={}
        def doVar(self,literal):
            name,values=literal[:-1].split('[');value,lo,hi=map(float,values.split(','));objects[name]=Var(name,value,lo,hi)
        def doSet(self,name,value):self.sets[name]=value
        def factory_(self,literal):
            match=re.fullmatch(r'expr::(\w+)\("([^"]*)",(.*)\)',literal)
            if match:name,formula,args=match.groups();objects[name]=Function(name,'expr',args.split(','),formula)
            else:
                match=re.fullmatch(r'sum::(\w+)\((.*)\)',literal);assert match,literal
                name,args=match.groups();objects[name]=Function(name,'sum',args.split(','))
    root=ModuleType('ROOT');root.TH1D=Hist;root.RooDataHist=Data;root.RooHistFunc=HistFunction;root.RooNumIntConfig=Config
    root.RooAbsReal=SimpleNamespace(defaultIntegratorConfig=lambda:object())
    root.RooArgSet=root.RooArgList=lambda *args:args
    root.RooFit=SimpleNamespace(Range=lambda name:name,RecycleConflictNodes=lambda:object())
    root.gSystem=SimpleNamespace(Load=lambda path:seen.append(('inert_library_mapping',path)) or 0)
    module=ModuleType('HiggsAnalysis.CombinedLimit.PhysicsModel');module.PhysicsModel=type('PhysicsModel',(),{})
    monkeypatch.setitem(sys.modules,'ROOT',root);monkeypatch.setitem(sys.modules,'HiggsAnalysis.CombinedLimit.PhysicsModel',module)
    ns={};exec(compile(n.native_bridge_source(compiled),'actual-generated-bridge-inert-API','exec'),ns)
    model=ns['model'];model.modelBuilder=Builder();model.doParametersOfInterest()
    assert [objects['ravel_mean_'+str(i)].getVal() for i in range(4)]==[30.,10.,15.,5.]
    objects['c'].value=1.;objects['slope'].value=.1
    assert [objects['ravel_mean_'+str(i)].getVal() for i in range(4)]==pytest.approx([30.25,14.4,16.9,6.65])
    assert objects['ravel_graph_den_0'].getVal()==17.5 and 'ravel_graph_den_1' not in objects
    assert ('integral','morph',(1.,4.),'raw_no_NormSet') in seen
    assert objects['massObs'].constant is True and objects['massObs'].unit=='GeV'
    assert model.modelBuilder.extraNuisances==[objects[v] for v in ('beta','u','v','slope')]
    assert model.modelBuilder.sets=={'POI':'c'} and model.modelBuilder.doModelBOnly is False
    assert model.getYieldScale('A','ravel_full')=='ravel_mean_0' and model.getYieldScale('A','ravel_dummy')==0
