"""Portable fabricated trace/counter controls; no native acquisition implied."""
import copy,hashlib,json,math
from fractions import Fraction
from pathlib import Path
import pytest
from ravel.physics import group_composition as c

NATIVE=[[200.,250.,300.,350.,500.,700.,1000.,1400.],
        [200.,250.,300.,350.,500.,700.,1400.],
        [200.,400.,600.,1000.,2000.,4000.],
        [0.,.5235988,1.047198,1.570796,2.094396,2.617993,3.141592]]
TARGET=[*NATIVE[:3],[0.,.5235988,1.047198,1.570796,2.094395,2.617994,3.141593]]
WEIGHTS=[[2.,2.4],[-.5,-.6],[0.,1.],[1.,1.],[1.,1.2],[2.,1.8],[1.,1.],[.5,.7],[1.,1.],[1.,1.],[1.,1.],[1.,1.]]

def save(path,obj,ident):
    path.write_text(json.dumps(obj,allow_nan=False));return pin(path,ident)

def pin(path,ident):
    raw=path.read_bytes();return {'id':ident,'path':str(path),'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def binning(edges):return [{'id':str(i),'low':a,'high':b} for i,(a,b) in enumerate(zip(edges,edges[1:]))]

def native(directory,arm,coordinates,weights=None,weight_values=None):
    directory.mkdir();source=directory/'definition.cc';source.write_text('Synthetic default fill(value); sf=fixed_coefficient/sumW.\n')
    sourcepin=pin(source,'routine');definition={'source':'routine','first_line':1,'last_line':1,'text':source.read_text().strip()}
    weights=weights or ['nominal','closure-up'];components=[];basis=[]
    weight_values=weight_values if weight_values is not None else [row if len(weights)==2 else [row[0]]+[row[1]]*(len(weights)-1) for row in WEIGHTS]
    for site,edges in enumerate(NATIVE):
        output='d'+str(site+1);axis={'name':output,'unit':'RAD' if site==3 else 'GEV'}
        q={'axis':axis,'bins':binning(edges),'unit':'FB','representation':'integrated'}
        components.append({'id':output,'output':output,'quantity':q,'fixed_coefficients':{w:{'value':1.,'unit':'FB','source':'routine','semantics':'fixed_cross_section_times_source_factor'} for w in weights},'denominator_policy':'positive','definition':definition})
    for w in weights:
        for component in components:
            edges=NATIVE[int(component['id'][1:])-1];q=component['quantity']
            for b,lo,hi in [('underflow',None,edges[0]),*[(b['id'],b['low'],b['high']) for b in q['bins']],('overflow',edges[-1],None)]:
                basis.append({'weight':w,'output':component['id'],'native_path':'/'+arm+'/'+component['id'],'bin':b,'unit':'1','axis_unit':q['axis']['unit'],'low':lo,'high':hi})
    events=[{'input_sha256':'a'*64,'encounter_ordinal':i,'event_number':10+i,'selected_weights':ws} for i,ws in enumerate(weight_values)]
    mapping=[{'id':w,'native':'' if i==0 else w,'raw_suffix':'' if i==0 else '['+w+']'} for i,w in enumerate(weights)]
    original={'schema_version':2,'native_analysis_alias':arm,'routine':'synthetic-rmiss','original_source_sha256':sourcepin['sha256'],
              'group_rule':'independent_single_subevent','same_process_pid':42 if arm=='NU' else 43,'native_weight_cap':0,
              'weight_mapping':mapping,'outputs':[{'id':p['id'],'path':'/'+arm+'/'+p['id'],'edges':NATIVE[i], 'axis_unit':p['quantity']['axis']['unit'],'unit':'1'} for i,p in enumerate(components)],'events':events}
    trace=[];groups=[]
    for ordinal,(event,fills) in enumerate(zip(events,coordinates)):
        trace.append({'schema':'ravel-native-fills/v1','routine':'synthetic-rmiss','original_source_sha256':sourcepin['sha256'],'ordinal':ordinal,
                      'event_number':event['event_number'],'pid':original['same_process_pid'],'unwinding':not bool(fills),
                      'native_weight_names':[r['native'] for r in mapping],'weights':event['selected_weights'],
                      'fills':[{'site':site,'coordinates':[x]} for site,x in fills]})
        vector=[]
        for b in basis:
            comp=components[int(b['output'][1:])-1];ws=event['selected_weights'][weights.index(b['weight'])]
            vector.append(math.fsum(ws for site,x in fills if 'd'+str(site+1)==b['output'] and c.cell(x,comp['quantity']['bins'])==b['bin']))
        groups.append({'id':'a'*64+':'+str(ordinal),'values':vector})
    tracepath=directory/'trace.jsonl';tracepath.write_text(''.join(json.dumps(r)+'\n' for r in trace));tp=pin(tracepath,'trace')
    rawpin=save(directory/'RAW.json',{'kind':'fabricated-RAW-not-native'},'RAW')
    acquired={'schema_version':2,'native_analysis_alias':arm,'logical_source_routine':'synthetic-rmiss','uninstrumented_source_sha256':sourcepin['sha256'],
              'basis':basis,'values':[math.fsum(g['values'][i] for g in groups) for i in range(len(basis))],
              'uncertainty':{'kind':'independent_groups','semantics':'uncentered_poissonized_second_moment','groups':groups},
              'normalization_event_weights':[{'id':g['id'],'weights':dict(zip(weights,e['selected_weights']))} for g,e in zip(groups,events)],
              'normalization_counter_by_weight':{w:{'sumw':math.fsum(v[i] for v in weight_values),'sumw2':math.fsum(v[i]*v[i] for v in weight_values),'entries':12,
                       'raw_tokens':[str(math.fsum(v[i] for v in weight_values)),str(math.fsum(v[i]*v[i] for v in weight_values)),'12']} for i,w in enumerate(weights)},
              'source_file_encounter_groups':12,'native_trace_sha256':tp['sha256'],'raw_yoda_sha256':rawpin['sha256'],'native_weight_cap':0,
              'same_process_pid':original['same_process_pid'],'group_rule':'independent_single_subevent','native_marginal_covariance_inferred':False,
              'physics_validated':False,'requires_separate_execution_custody_review':True,'raw_primitive_cells_checked':326}
    contract={'schema_version':1,'kind':'group-normalization-contract','analysis_id':'synthetic-rmiss',
              'sources':[sourcepin,tp,rawpin,save(directory/'original.json',original,'original'),save(directory/'acquired.json',acquired,'acquired')],
              'acquisition_source':'acquired','acquisition_contract_source':'original','native_trace_source':'trace','raw_yoda_source':'RAW',
              'weights':[{'id':w,'counter_id':'sumw/'+w,'weight_policy':'signed'} for w in weights],'components':components,
              'group_rule':'independent_single_subevent','flow_policy':'scale_integrated_flows','coefficient_uncertainty':'fixed_conditional'}
    cp=save(directory/'normalization.json',contract,'normalization')
    targets=[{'output':p['output'],'quantity':{**p['quantity'],'bins':binning(TARGET[i])}} for i,p in enumerate(components)]
    rp={'schema_version':1,'kind':'source-coordinate-rebin-contract','sources':[cp,sourcepin,save(directory/'target.json',targets,'target')],
        'original_normalization':'normalization','target_geometry_source':'target','targets':targets,
        'sites':[{'site':i,'output':p['output'],'definition':definition} for i,p in enumerate(components)],
        'fill_semantics':'native_default_event_weight_fraction1','boundary_rule':'half_open_finite_underflow_overflow'}
    return save(directory/'rebin.json',rp,arm),contract,acquired,rp

@pytest.fixture
def sample(tmp_path):
    angular=[]
    for edge in (2.094395,2.617994,3.141593):angular.extend([math.nextafter(edge,-math.inf),edge,math.nextafter(edge,math.inf)])
    nu=[[(0,225.),(1,225.),(2,300.),(3,x)] for x in angular]+[[],[(0,1500.),(2,4500.)],[(0,100.)]]
    el=[[(1,275.),(2,700.),(3,x)] for x in reversed(angular)]+[[],[(0,325.)],[(0,100.)]]
    a=native(tmp_path/'NU','NU',nu);b=native(tmp_path/'EL','EL',el)
    contract={'schema_version':1,'kind':'same-event-group-composition-contract','sources':[a[0],b[0]],
              'arms':[{'id':'numerator','kind':'source_coordinate_rebin','source':'NU'}, {'id':'denominator','kind':'source_coordinate_rebin','source':'EL'}],
              'group_join':'exact_ordered_source_sha256_encounter','counter_policy':'share_one_counter_per_weight'}
    return contract,a,b

def test_full_counter_once_and_cross_mode_covariance(sample):
    contract,a,b=sample;r=c.compose(contract)
    assert len(r['input_basis'])==130 and len(r['output_basis'])==128
    assert len(r['input_groups'])==12 and sum(b['kind']=='normalization_counter' for b in r['input_basis'])==2
    assert r['input_values'][-2:]==[11.,12.5]
    assert r['input_covariance'][-2][-2]==15.5 and r['input_covariance'][-1][-1]==18.29
    assert r['input_covariance'][-2][-1]==16.25
    assert any(r['output_covariance'][i][j]!=0 for i in range(64) for j in range(64,128))
    assert not r['native_acquisition_qualified'] and r['inference'] is None
    assert c.derived_joint(r)['uncertainty']['kind']=='supplied_covariance'

def test_full_fraction_gram_enclosed_and_scalar_counter_derivative(sample):
    r=c.compose(sample[0]);F=Fraction.from_float;phi=[]
    for row in r['jacobian']:
        phi.append([sum((F(j)*F(v) for j,v in zip(row,g['vector'])),Fraction()) for g in r['input_groups']])
    bound=F(r['covariance_maximum_entry_forward_error_bound'])
    for i,row in enumerate(r['output_covariance']):
        for j,value in enumerate(row):assert abs(F(value)-sum((a*b for a,b in zip(phi[i],phi[j])),Fraction()))<=bound
    for i,f in enumerate(r['normalization_factors']):
        assert r['jacobian'][i][f['counter_coordinate']]==-r['values'][i]/f['counter']

def test_exact_half_open_boundaries_original_overflow_and_repeated_fills(sample):
    contract,a,b=sample;arm=c.rebin(a[3]);groups=arm['hist_groups'];basis=arm['hist_basis']
    old=a[2]['uncertainty']['groups']; original=a[2]['basis']
    index=lambda bs,w,output,bin:next(i for i,r in enumerate(bs) if (r['weight'],r['output'],r['bin'])==(w,output,bin))
    # Native pi edge is smaller. Group6 lies below published pi but in original overflow.
    assert old[6]['values'][index(original,'nominal','d4','overflow')]==1.
    assert groups[6]['values'][index(basis,'nominal','d4','5')]==1.
    assert groups[7]['values'][index(basis,'nominal','d4','overflow')]==.5
    assert groups[8]['values'][index(basis,'nominal','d4','overflow')]==1.
    assert arm['origin_kind']=='source_coordinate_rebin'
    assert arm['result']['input_basis'][:-2]==[{**r,'kind':'histogram'} for r in original]

@pytest.mark.parametrize('fault',['coordinate','extra_fill','pid','label','ordinal','weights','boolean_weight','missing_event','target_unpinned','site','closed'])
def test_resealed_trace_and_contract_adversaries_refuse(sample,fault):
    _,a,_=sample;rp=a[3];normal=a[1];acquired=a[2];path=Path(next(p['path'] for p in normal['sources'] if p['id']=='trace'))
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    if fault=='coordinate':rows[0]['fills'][0]['coordinates']=[1400.]
    elif fault=='extra_fill':rows[0]['fills'].append(rows[0]['fills'][0])
    elif fault=='pid':rows[0]['pid']=100
    elif fault=='label':rows[0]['native_weight_names'].reverse()
    elif fault=='ordinal':rows[0]['ordinal']=1
    elif fault=='weights':rows[0]['weights'][0]=3.
    elif fault=='boolean_weight':rows[2]['weights'][0]=False
    elif fault=='missing_event':rows.pop()
    elif fault=='target_unpinned':rp['targets'][3]['quantity']['bins'][-1]['high']=4.
    elif fault=='site':rows[0]['fills'][0]['site']=5
    else:rows[0]['extra']='no'
    if fault!='target_unpinned':
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows));p=pin(path,'trace')
        normal['sources']=[p if r['id']=='trace' else r for r in normal['sources']]
        acquired['native_trace_sha256']=p['sha256']
        ap=save(path.parent/'acquired.json',acquired,'acquired');normal['sources']=[ap if r['id']=='acquired' else r for r in normal['sources']]
        np=save(path.parent/'normalization.json',normal,'normalization');rp['sources']=[np if r['id']=='normalization' else r for r in rp['sources']]
    with pytest.raises(ValueError):c.rebin(rp)

def test_same_ids_cannot_hide_effective_weight_population_difference(sample):
    contract,a,b=sample
    # Swap complete events in the denominator, preserving its local normalizer.
    original_path=Path(next(p['path'] for p in b[1]['sources'] if p['id']=='original'))
    original=json.loads(original_path.read_text());original['events'][0]['event_number']+=1
    op=save(original_path,original,'original');normal=b[1];normal['sources']=[op if p['id']=='original' else p for p in normal['sources']]
    np=save(original_path.parent/'normalization.json',normal,'normalization');rp=b[3];rp['sources']=[np if p['id']=='normalization' else p for p in rp['sources']]
    p=save(original_path.parent/'rebin.json',rp,'EL');contract['sources']=[p if s['id']=='EL' else s for s in contract['sources']]
    with pytest.raises(ValueError):c.compose(contract)

def test_operation_inventory_and_fresh_output(sample,tmp_path):
    contract,_,_=sample;path=tmp_path/'compose.json';p=save(path,contract,'compose')
    task={'schema_version':1,'operation':'same-event-compose','input':str(path),'contract_sha256':p['sha256']}
    files=c.inputs(task,tmp_path);assert len(files)==17
    r=c.run(task,tmp_path,tmp_path/'output');assert json.loads((tmp_path/'output/normalized-joint.json').read_text())==c.derived_joint(r)
    before=(tmp_path/'output/group-composition.json').read_bytes()
    with pytest.raises(ValueError,match='fresh'):c.run(task,tmp_path,tmp_path/'output')
    assert (tmp_path/'output/group-composition.json').read_bytes()==before

def test_exact_24_measurement_components_full_48_covariance_and_refused_native_join(sample):
    contract,a,b=sample;r=c.compose(contract);basis=[];mapping={'numerator':[],'denominator':[]};units=[]
    for site,edges in enumerate(TARGET):
        axis={'name':'d'+str(site+1),'unit':'RAD' if site==3 else 'GEV'}
        for j,(lo,hi) in enumerate(zip(edges,edges[1:])):
            ident=str(len(basis)+1);basis.append({'id':ident,'observable':'d'+str(site+1),'axis':axis,'low':[lo],'high':[hi]})
            for side in mapping:mapping[side].append({'weight':'nominal','component':side+'/d'+str(site+1),'bin':str(j)})
            units.append({'from':'FB/'+axis['unit'],'to':'FB '+axis['unit']+'**-1','scale':1.})
    out=c.measurement_slice(r,basis,mapping,units)
    assert len(out['bsm_numerator']['values'])==len(out['bsm_denominator']['values'])==24
    assert len(out['joint_prediction_covariance'])==48
    assert any(v!=0 for row in out['joint_prediction_covariance'][:24] for v in row[24:])
    assert out['experimental_independence'] is None and out['inference'] is None
    native_contract=copy.deepcopy(contract)
    native_contract['sources']=[pin(Path(a[0]['path']).parent/'normalization.json','NU'),pin(Path(b[0]['path']).parent/'normalization.json','EL')]
    for arm in native_contract['arms']:arm['kind']='original_native_supplied'
    with pytest.raises(ValueError,match='geometry join'):
        c.measurement_slice(c.compose(native_contract),basis,mapping,units)
    units[-1]['scale']=2.
    with pytest.raises(ValueError,match='identity-only'):c.measurement_slice(r,basis,mapping,units)

def test_independent_normalization_finite_differences_and_ratio_counter_cancellation(sample):
    r=c.compose(sample[0]);x=r['input_values'];h=1e-5
    for i,f in enumerate(r['normalization_factors']):
        ci=f['counter_coordinate'];k=f['fixed_coefficient'];W=x[ci];N=x[i]
        dN=(k*(N+h)/W-k*(N-h)/W)/(2*h)
        dW=(k*N/(W+h)-k*N/(W-h))/(2*h)
        assert abs(dN-r['jacobian'][i][i])<1e-10
        assert abs(dW-r['jacobian'][i][ci])<1e-10
    available=[tuple(b[k] for k in ('weight','component','bin')) for b in r['output_basis']]
    a=available.index(('nominal','numerator/d4','3'));b=available.index(('nominal','denominator/d4','3'))
    # If both source selections populate this bin, the shared counter cancels
    # from the analytical quotient chain independently of cross-mode phi.
    assert r['values'][a]!=0 and r['values'][b]!=0
    chain=[r['jacobian'][a][j]/r['values'][b]-r['values'][a]*r['jacobian'][b][j]/r['values'][b]**2 for j in range(len(x))]
    assert max(abs(v) for v in chain[-2:])<1e-16

def test_union_budget_not_armwise_and_duplicate_component_identity(sample,tmp_path):
    contract,_,_=sample;extended=copy.deepcopy(contract)
    names=['nominal']+['variation'+str(i) for i in range(15)]
    a=native(tmp_path/'many-NU','NU',[[] for _ in WEIGHTS],names)
    b=native(tmp_path/'many-EL','EL',[[] for _ in WEIGHTS],names)
    extended['sources']=[a[0],b[0]]
    # Each arm528 coordinates admits; full1040-coordinate union refuses.
    with pytest.raises(ValueError,match='union covariance budget'):c.compose(extended)
    contract['arms'][1]['id']=contract['arms'][0]['id']
    with pytest.raises(ValueError,match='unique bound arm'):c.compose(contract)

@pytest.mark.parametrize('edge',[2.094395,2.094396,2.617993,2.617994,3.141592,3.141593])
def test_every_original_and_target_mismatched_edge_with_nextafter(edge):
    old=binning(NATIVE[3]);target=binning(TARGET[3])
    for bins in (old,target):
        left=c.cell(math.nextafter(edge,-math.inf),bins);at=c.cell(edge,bins);right=c.cell(math.nextafter(edge,math.inf),bins)
        edges=[bins[0]['low']]+[b['high'] for b in bins]
        if edge in edges:
            assert left!=at and at==right
        else:assert left==at==right


def measurement_contract(sample,tmp_path):
    contract,_,_=sample;basis=[];mapping={'numerator':[],'denominator':[]};units=[]
    for site,edges in enumerate(TARGET):
        axis={'name':'d'+str(site+1),'unit':'RAD' if site==3 else 'GEV'}
        for j,(lo,hi) in enumerate(zip(edges,edges[1:])):
            basis.append({'id':str(len(basis)+1),'observable':'d'+str(site+1),'axis':axis,'low':[lo],'high':[hi]})
            for side in mapping:mapping[side].append({'weight':'nominal','component':side+'/d'+str(site+1),'bin':str(j)})
            units.append({'from':'FB/'+axis['unit'],'to':'FB '+axis['unit']+'**-1','scale':1.})
    cp=save(tmp_path/'compose.json',contract,'composition');bp=save(tmp_path/'basis.json',basis,'measurement-basis')
    document={'schema_version':1,'kind':'source-bound-measurement-components-contract','sources':[cp,bp],
              'composition_source':'composition','measurement_basis_source':'measurement-basis','mapping':mapping,'unit_join':units}
    dp=save(tmp_path/'measurement-components-contract.json',document,'component-contract')
    task={'schema_version':1,'operation':'measurement-components','input':dp['path'],'contract_sha256':dp['sha256']}
    return task,document,basis


def test_public_component_operation_full_graph_and_three_deliveries(sample,tmp_path):
    task,document,basis=measurement_contract(sample,tmp_path)
    assert len(c.inputs(task,tmp_path))==19
    result=c.run(task,tmp_path,tmp_path/'component-output')
    sliced=json.loads((tmp_path/'component-output/measurement-components.json').read_text())
    assert result['measurement_components']==sliced
    assert sliced['basis']==basis and sliced['sources']==document['sources']
    assert len(sliced['joint_prediction_covariance'])==48
    assert not sliced['native_acquisition_qualified'] and sliced['experimental_independence'] is None
    assert len(json.loads((tmp_path/'component-output/normalized-joint.json').read_text())['basis'])==128


@pytest.mark.parametrize('fault',['outer-operation','unknown-key','wrong-arm-kind','missing-pin','duplicate-arm','target-change','slice-population','unknown-component-key'])
def test_prospective_closed_graph_refuses_without_numerical_evaluation(sample,tmp_path,monkeypatch,fault):
    task,document,_=measurement_contract(sample,tmp_path)
    if fault=='outer-operation':task['operation']='same-event-compose'
    elif fault=='unknown-component-key':document['unbound']='extra'
    elif fault=='slice-population':document['mapping']['numerator'].pop()
    else:
        cp=Path(document['sources'][0]['path']);composition=json.loads(cp.read_text())
        if fault=='unknown-key':composition['extra']='unbound'
        elif fault=='wrong-arm-kind':composition['arms'][0]['kind']='original_native_supplied'
        elif fault=='missing-pin':composition['arms'][0]['source']='absent'
        elif fault=='duplicate-arm':composition['arms'][1]['id']=composition['arms'][0]['id']
        else:
            rp=Path(composition['sources'][0]['path']);rebin=json.loads(rp.read_text());rebin['targets'][0]['quantity']['bins'][0]['high']=249.
            composition['sources'][0]=save(rp,rebin,'NU')
        document['sources'][0]=save(cp,composition,'composition')
    path=Path(task['input']);p=save(path,document,'component-contract');task['contract_sha256']=p['sha256']
    monkeypatch.setattr(c.n,'normalize',lambda *_a,**_k:pytest.fail('planning evaluated normalization'))
    with pytest.raises(ValueError):c.inputs(task,tmp_path)


def test_complete_cross_arm_effective_weights_differ_despite_same_counters(tmp_path):
    coordinates=[[(0,225.),(3,1.)] for _ in WEIGHTS]
    a=native(tmp_path/'NU','NU',coordinates)
    changed=copy.deepcopy(WEIGHTS);changed[0],changed[1]=changed[1],changed[0]
    b=native(tmp_path/'EL','EL',coordinates,weight_values=changed)
    # Each supplied arm is valid on its own, including its own reconciled trace;
    # global W/Q are equal, so the exact group population join is essential.
    assert c.rebin(a[3])['result']['counter_diagnostics']==c.rebin(b[3])['result']['counter_diagnostics']
    contract={'schema_version':1,'kind':'same-event-group-composition-contract','sources':[a[0],b[0]],
              'arms':[{'id':'numerator','kind':'source_coordinate_rebin','source':'NU'},{'id':'denominator','kind':'source_coordinate_rebin','source':'EL'}],
              'group_join':'exact_ordered_source_sha256_encounter','counter_policy':'share_one_counter_per_weight'}
    with pytest.raises(ValueError,match='encounter/weight population'):c.compose(contract)


def test_all_source_weights_common_rescaling_preserves_normalization_full_covariance(sample,tmp_path):
    original=c.compose(sample[0]);coordinates=[]
    for _,data in [('NU',sample[1]),('EL',sample[2])]:
        trace=Path(next(p['path'] for p in data[1]['sources'] if p['id']=='trace'))
        coordinates.append([[(f['site'],f['coordinates'][0]) for f in json.loads(line)['fills']] for line in trace.read_text().splitlines()])
    scaled=[[2*w for w in row] for row in WEIGHTS]
    a=native(tmp_path/'scaled-NU','NU',coordinates[0],weight_values=scaled)
    b=native(tmp_path/'scaled-EL','EL',coordinates[1],weight_values=scaled)
    contract=copy.deepcopy(sample[0]);contract['sources']=[a[0],b[0]];other=c.compose(contract)
    assert other['values']==original['values'] and other['output_covariance']==original['output_covariance']
    assert other['input_values'][-2:]==[2*x for x in original['input_values'][-2:]]
    for i in range(2):
        for j in range(2):assert other['input_covariance'][-2+i][-2+j]==4*original['input_covariance'][-2+i][-2+j]


def test_outer_contract_changed_during_transform_refuses_before_writing(sample,tmp_path,monkeypatch):
    contract,_,_=sample;path=tmp_path/'compose.json';p=save(path,contract,'compose')
    task={'schema_version':1,'operation':'same-event-compose','input':p['path'],'contract_sha256':p['sha256']}
    real=c.compose
    def changed(*args,**kwargs):
        result=real(*args,**kwargs);path.write_bytes(path.read_bytes()+b' ');return result
    monkeypatch.setattr(c,'compose',changed)
    with pytest.raises(ValueError,match='digest'):c.run(task,tmp_path,tmp_path/'unwritten')
    assert not (tmp_path/'unwritten').exists()


def test_coordinate_rebin_task_retains_original_and_distinct_target(sample,tmp_path):
    pin,_,_,_=sample[1];task={'schema_version':1,'operation':'coordinate-rebin','input':pin['path'],'contract_sha256':pin['sha256']}
    result=c.run(task,tmp_path,tmp_path/'rebin-output')
    assert result['kind']=='source-coordinate-rebin-result'
    assert result['original_native']['components'][3]['quantity']['bins'][-1]['high']==NATIVE[3][-1]
    assert result['target_basis'][-1]['low']==TARGET[3][-1]
    assert not (tmp_path/'rebin-output/normalized-joint.json').exists()
    assert not result['native_acquisition_qualified']


@pytest.mark.parametrize('ident',['numerator/d1','a'*65])
def test_arm_namespace_cannot_collide_with_component_paths(sample,ident):
    contract=sample[0];contract['arms'][0]['id']=ident
    with pytest.raises(ValueError,match='namespace'):c.compose(contract)
