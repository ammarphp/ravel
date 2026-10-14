"""Full-cohort, frozen-strategy MC closure through ordinary deliveries.

No event reader, partitioner, sampler or fit is defined here. Source declares
independent complete replicas and either a Poissonized or fixed-N IID physical
entry/group law. Those scientific claims need fresh review; disjoint filenames alone
are not evidence of independence. Complementary parent partitions require the
separate source-bound joint partition construction, never an assumed zero block.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from ravel.physics import root_stream as stream, root_stream_core as c
from ravel.physics import columnar_ntuple_recipe as h

SCOPE='frozen_full_replica_mc_closure'
LAWS=('poissonized_independent_source_physical_entries','fixed_N_IID_source_physical_entries',
      'poissonized_independent_source_physical_groups','fixed_N_IID_source_physical_groups')
PARTITION_SOURCE_REQUEST='59feb1b5f1f2e67c723b4a921b1570413f3603d081f7d27a325d0aea228b3d94'


def rational(x):
    if type(x) is str:
        q=Fraction(x);c.scalar(float(q));return q
    c.scalar(x);return Fraction(x)


def moments(quantity,sampling_law):
    """Full original entry exposure including no-fill/zero/signed entries."""
    c.require(sampling_law in LAWS,'explicit independent physical-entry sampling law required')
    contract=quantity['contract'];state=quantity['state'];n=len(contract['bins'])
    c.require(contract['representation']=='integrated' and contract['normalization']['kind']=='absolute' and
        contract['normalization']['unit']=='events' and contract['weight_names']==['nominal'], 'nominal full expected event integrals required')
    c.require(quantity['state_sha256']==c.digest({'contract':contract,'state':state}), 'complete moment state differs')
    c.require(len(state['sumw'])==n+2 and len(state['second_moment'])==n+2 and all(len(row)==n+2 for row in state['second_moment']), 'whole bin/flow/weight-counter moment geometry required')
    count=state['counts']['records'];c.require(type(count) is int and count>=1, 'full preselection independent entry exposure required')
    values=[rational(x) for x in state['sumw'][:n]]
    gram=[[rational(x) for x in row[:n]] for row in state['second_moment'][:n]]
    c.require(all(gram[i][j]==gram[j][i] for i in range(n) for j in range(n)), 'literal joint Gram symmetry differs')
    k=rational(contract['normalization']['scale']);c.require(k!=0, 'nonzero full original exposure normalization required')
    covariance=gram
    if sampling_law in (LAWS[1],LAWS[3]):
        c.require(count>=2, 'fixed-N centered estimator requires at least two independent groups')
        covariance=[[Fraction(count,count-1)*(gram[i][j]-values[i]*values[j]/count) for j in range(n)] for i in range(n)]
    c.require(all(covariance[i][i]>=0 for i in range(n)), 'negative emitted centered variance refuses; no clipping')
    return {'basis':[b['id'] for b in contract['bins']], 'yield':[k*x for x in values],
        'covariance':[[k*k*x for x in row] for row in covariance], 'full_units':count,'independent_unit':'physical_group' if sampling_law in LAWS[2:] else 'source_entry',
        'raw_group_sum':values,'raw_group_gram':gram,'scale':k,'sampling_law':sampling_law,
        'denominator_treatment':'conditional_on_original_source_full_signed_generator_sumw',
        'all_flow_and_counter_retained':deepcopy(state)}


def contrast(predicted,heldout,matrix,cross_covariance):
    """d=H-T P; C=CH+T CP T^t-CHP T^t-T CPH, exact emitted-binary law."""
    basis=predicted['basis'];n=len(basis)
    c.require(heldout['basis']==basis and type(matrix) is list and len(matrix)==n and
        all(type(row) is list and len(row)==n for row in matrix), 'full ordered closure basis/operator required')
    t=[[rational(x) for x in row] for row in matrix]
    c.require(type(cross_covariance) is list and len(cross_covariance)==n and all(len(row)==n for row in cross_covariance), 'complete heldout,prediction cross block required')
    cross=[[rational(x) for x in row] for row in cross_covariance]
    delta=[heldout['yield'][i]-sum((t[i][a]*predicted['yield'][a] for a in range(n)),Fraction()) for i in range(n)]
    covariance=[[heldout['covariance'][i][j]+sum((t[i][a]*predicted['covariance'][a][b]*t[j][b] for a in range(n) for b in range(n)),Fraction())-
        sum((cross[i][a]*t[j][a]+t[i][a]*cross[j][a] for a in range(n)),Fraction()) for j in range(n)] for i in range(n)]
    c.require(all(covariance[i][j]==covariance[j][i] for i in range(n) for j in range(n)) and all(covariance[i][i]>=0 for i in range(n)), 'closure covariance symmetry/variance differs')
    return {'basis':basis,'residual':[str(x) for x in delta], 'covariance':[[str(x) for x in row] for row in covariance],
        'residual_binary64':[c.scalar(float(x)) for x in delta], 'covariance_binary64':[[c.scalar(float(x)) for x in row] for row in covariance],
        'cross_covariance':[[str(x) for x in row] for row in cross],
        'arithmetic':'Fraction from exact emitted binary64 moments; no enclosure/conditioning certificate',
        'closure_p_value':None,'coverage_qualified':False,'physics_validated':False}


def validate(task):
    c.keys(task,('request',),'MC closure task');c.pin(task['request']);return task


def full_transport(config,ds,analysis,native,base,cap,protocol,sampling_law):
    """Complete original entry/group transport; no partial/fold independence."""
    grouped=sampling_law in LAWS[2:]
    if config['schema_version']==1:
        c.require(protocol is None and not grouped and native['delivery']['sampling_law']=='poissonized_independent_physical_events_with_event_common_weights',
            'original full entry transport required; groups require the exact complete ordinary merge')
        return {s['id']:sum(m['entries'] for m in s['members']) for s in ds['samples']}
    c.require(config['schema_version']==2 and config['partitioning']['operation']=='merge' and protocol is not None,
        'only complete ordinary partition MERGE is a closure cohort; a raw partition is not validation')
    from ravel.physics import root_stream_partitions as partition,root_stream_partition_core as pc
    c.keys(protocol,('source_request','modules'),'exact prospective partition source join')
    c.require(protocol['source_request']['sha256']==PARTITION_SOURCE_REQUEST,'the bound partition interface epoch changed; fresh source review required')
    cap.read(protocol['source_request'],base)
    c.require(type(protocol['modules']) is dict and set(protocol['modules'])==set(partition.FILES),'complete joined partition module identity roster required')
    for name,pin in protocol['modules'].items():
        installed=Path(stream.__file__).with_name(name).absolute();actual,raw=cap.read(pin,base,max(8*1024**2,pin['size']))
        c.require(actual==installed,'partition protocol must bind the actual joined source, not a separate donor copy')
    m=partition.bound_master(config,ds,analysis,base,cap)
    c.require((m['grouping']['kind']=='declared_groups')==grouped,'entry law and grouped source cannot be silently interchanged')
    if not grouped:
        c.require(native['delivery']['sampling_law']==pc.ENTRY_LAW,'complete merged entry transport differs')
        return {s['id']:sum(member['entries'] for member in s['members']) for s in ds['samples']}
    c.require(native['delivery']['sampling_law']==pc.GROUP_LAW and native['delivery']['physical_grouping']=={
        'master':m['master_pin'],'source':m['grouping']['source'],'group_ids':[g['id'] for g in m['groups']],'statement':m['grouping']['statement']},
        'full original physical group source/order/membership differs')
    # bound_master reconstructs full disjoint coverage. Groups may cross members
    # within this sample and remain indivisible; their count is NOT entry count.
    return {s['id']:sum(g['sample']==s['id'] for g in m['groups']) for s in ds['samples']}


def _load(task,base):
    validate(task);cap=c.Capture();path,raw=cap.read(task['request'],base);request=c.strict(raw)
    c.keys(request,('schema_version','original_goal','goal_binding','requirements','strategy','independence','cohorts','partition_protocol'),'full closure request')
    c.require(type(request['schema_version']) is int and request['schema_version']==2,'closure schema2 with explicit prospective partition binding required')
    cap.read(request['original_goal'],path.parent)
    requirements=cap.document(request['requirements'],path.parent)
    from ravel.physics.ntuple_inventory import roster
    roster(requirements,complete=False)
    c.require(type(request['goal_binding']) is dict,'whole goal binding required')
    c.keys(request['cohorts'],('prediction','heldout'),'complete two original MC cohorts')
    strategy=cap.document(request['strategy'],path.parent);independence=cap.document(request['independence'],path.parent)
    c.keys(strategy,('schema_version','selection_recipe','branch_contract','prediction_operator','sampling_law','normalization_treatment','sample_pairs','statement'),'frozen complete closure strategy')
    c.require(strategy['schema_version']==1 and type(strategy['schema_version']) is int and strategy['sampling_law'] in LAWS and
        strategy['normalization_treatment']=='conditional_on_original_full_generator_denominator', 'fixed declared source moment/exposure law required')
    c.text(strategy['statement']);recipe=h.validate_recipe(strategy['selection_recipe']);c.text(independence['statement'])
    if recipe['schema_version']==2:
        from ravel.physics import columnar_selection as selection
        strategy_path,_=cap.read(request['strategy'],path.parent)
        recipe=selection.canonical_references(recipe,strategy_path.parent)
    c.keys(independence,('schema_version','kind','sampling_law','cohorts','statement'),'original production independence source')
    c.require(independence['schema_version']==1 and type(independence['schema_version']) is int and independence['kind']=='source_declared_independent_complete_MC_replicas' and
        independence['sampling_law']==strategy['sampling_law'], 'independent production contract required; partitions are not independent replicas')
    c.keys(independence['cohorts'],('prediction','heldout'),'independent full source membership')
    c.require(type(strategy['sample_pairs']) is list and strategy['sample_pairs'],'whole original paired sample population required')
    # Conservative known source aliases refuse; disjointness still does not prove independence.
    from urllib.parse import urlsplit,unquote_to_bytes
    from posixpath import normpath
    loaded={};guards=[];origin=[];guids=set();uris=set()
    for role in ('prediction','heldout'):
        declarations=request['cohorts'][role];c.keys(declarations,('stream_task','stream_result','stream_closure'),'ordinary complete stream origin')
        original_task=cap.document(declarations['stream_task'],path.parent)
        config_path,config,ds,analysis=stream._load(original_task,path.parent,cap)
        rp,raw=cap.read(declarations['stream_result'],path.parent,max(8*1024**2,declarations['stream_result']['size']))
        c.require(rp.name=='root-stream-result.json','canonical actual stream result required')
        value=c.strict(raw);result={**value,'commitment':declarations['stream_closure']};guard=stream.guard(result,rp.parent)
        receipt=stream.ordinary_stream_delivery(result,rp.parent,original_task)
        c.require(value['status']=='passed' and all(s['kind']=='background_mc' for s in ds['samples']), 'closure uses complete successful background MC; no observation/signal substitution')
        native,original=stream.private_delivery(guard)
        c.require(original['dataset']==ds and original['analysis']==analysis and original['config']==config, 'full original stream projection/source differs')
        protocol=request['partition_protocol']
        exposure=full_transport(config,ds,analysis,native,config_path.parent,cap,protocol,strategy['sampling_law'])
        projected=stream.public_delivery(native,ds,analysis,config) if config['schema_version']==2 else stream.public_delivery(native,ds,analysis)
        c.require(value['delivery']==projected,'full source public projection differs')
        c.require(analysis==h.analysis_document(recipe,strategy['branch_contract'],request['original_goal'],config['bundle']['files']['kernel.py']) and
            config['bundle']['files'].get('closure_frozen_strategy.json')==request['strategy'] and
            config['bundle']['files'].get('closure_production_independence.json')==request['independence'],
            'exact strategy, SF, source branching/bin mapping and independence declaration must be ordinary producer inputs BEFORE source access')
        if recipe['schema_version']==2:
            checked,_=selection.verify_bundle(recipe,config,config_path.parent,cap,
                extra_members=('closure_frozen_strategy.json','closure_production_independence.json'))
            c.require(checked==recipe,'source-rebased complete frozen selection differs')
        else:
            _,kernel=cap.read(config['bundle']['files']['kernel.py'],config_path.parent)
            c.require(kernel==h.kernel_bytes(recipe),'actual original source selection kernel differs')
        population=[]
        for sample in ds['samples']:
            original_population=cap.document(sample['normalization']['original_population'],config_path.parent)
            actual=[{k:m[k] for k in ('guid','did','entries')} for m in sample['members']]
            c.require(original_population['members']==actual, 'full original exposure must be processed; selected/partial denominator refuses')
            for m in sample['members']:
                c.require(m['guid'] not in guids,'shared physical GUID cannot certify independent replica validation');guids.add(m['guid'])
                u=urlsplit(m['uri'])
                # file:/ and file://localhost/ share local authority; remote host
                # case/default port and lexical path aliases are compared without
                # accessing data, resolving remote storage or rewriting the source.
                authority='' if u.scheme=='file' else (u.hostname.lower(),u.port or 1094)
                uri_path=unquote_to_bytes(u.path)
                if u.scheme=='file':
                    # The local reader uses UTF-8 replacement decoding.
                    # Refuse malformed bytes before comparing byte keys.
                    try:uri_path.decode('utf-8','strict')
                    except UnicodeDecodeError:
                        raise ValueError('strict UTF-8 local URI required; reader replacement aliases refuse') from None
                uri_path=normpath(uri_path)
                if u.scheme=='file':uri_path=b'/'+uri_path.lstrip(b'/')
                uri_identity=(u.scheme,authority,uri_path)
                c.require(uri_identity not in uris,'shared source URI alias cannot certify independent replica validation');uris.add(uri_identity)
            population.append({'sample':sample['id'],'dsid':sample['dsid'],'process':sample['process'],
                'members':actual,'normalization':deepcopy(sample['normalization'])})
        c.require(independence['cohorts'][role]==population,'complete original source independence/exposure association differs')
        q={s['id']:s['quantities']['regions'] for s in native['delivery']['samples']}
        for sample in ds['samples']:
            c.require(q[sample['id']]['state']['counts']['records']==exposure[sample['id']], 'full preselection entry/group exposure lost')
        loaded[role]={'quantities':q,'dataset':ds,'receipt':receipt,'full_delivery':value['delivery'],'result':result,'result_path':rp,'task':original_task}
        guards.append(guard)
        from ravel.workflow import science
        origin.extend(science.review_waypoint_paths(Path(receipt['rundir'])))
        origin.extend(rp.parent/'native'/name for name,fact in guard.native_outputs.items() if fact.get('kind')=='file')
    pairs=strategy['sample_pairs'];c.require(all(type(row) is dict and set(row)=={'prediction','heldout'} for row in pairs),'literal full sample pairs required')
    for role in ('prediction','heldout'):
        ids=[r[role] for r in pairs];c.require(len(ids)==len(set(ids)) and set(ids)==set(loaded[role]['quantities']), 'all original sample terms must remain; no best-only subset')
    results=[]
    for row in pairs:
        ps=next(s for s in loaded['prediction']['dataset']['samples'] if s['id']==row['prediction'])
        hs=next(s for s in loaded['heldout']['dataset']['samples'] if s['id']==row['heldout'])
        # root_stream_core.dataset/scale fixes pb, inverse-fb, dimensionless
        # filter/K and the conditional full signed denominator convention. Match
        # each physical factor, not merely their product. Independent original
        # denominators and member populations may differ; no transport is inferred.
        factors=('luminosity_fb_inverse','cross_section_pb','filter_efficiency','k_factor')
        c.require(ps['dsid']==hs['dsid'] and ps['process']==hs['process'] and
            all(ps['normalization'][name]==hs['normalization'][name] for name in factors),
            'matched source process and exact sigma/filter/K/luminosity normalization convention required; no implicit transport')
        pred=moments(loaded['prediction']['quantities'][row['prediction']],strategy['sampling_law'])
        hold=moments(loaded['heldout']['quantities'][row['heldout']],strategy['sampling_law'])
        c.require(pred['basis']==[r['id'] for r in recipe['regions']],'complete original SR/CR/VR closure basis required')
        n=len(pred['basis']);result=contrast(pred,hold,strategy['prediction_operator'],[[0]*n for _ in range(n)])
        results.append({'samples':row,'result':result,'prediction':_serial(pred),'heldout':_serial(hold),
            'original_source_entries':{'prediction':sum(m['entries'] for m in ps['members']),
                                       'heldout':sum(m['entries'] for m in hs['members'])}})
    cap.finish()
    for guard,item in zip(guards,loaded.values()):guard.finish(item['result'])
    return path,request,strategy,independence,loaded,guards,origin,cap,results


def _serial(value):
    if isinstance(value,Fraction):return str(value)
    if type(value) is dict:return {k:_serial(v) for k,v in value.items()}
    if type(value) is list:return [_serial(v) for v in value]
    return value


def inputs(task,base):
    *_,origin,cap,results=_load(task,base);return sorted({*cap.rows,*origin,Path(__file__),Path(h.__file__)})


def execution_seconds(task,base):_load(task,base);return 60


def goal_inputs(spec,base):
    _,request,*_=_load(spec['task'],base)
    c.require(spec.get('schema_version')==2 and spec.get('goal_binding')==request['goal_binding'],'whole original question binding required')


def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{})
    c.require(spec.get('schema_version')==2 and spec.get('max_attempts')==1 and policy.get('max_redos')==0 and set(policy.get('claim_scopes',{}))=={SCOPE} and
        policy['claim_scopes'][SCOPE].get('actions')==['delivery'],'MC closure arithmetic delivery only')
    return spec


def context(task,base):
    _,request,strategy,independence,*_=_load(task,base)
    return {'kind':SCOPE,'request':request,'strategy':strategy,'source_independence_contract':independence,'prospective_partition_protocol':request['partition_protocol'],
        'normalization':'each complete source replica has its own original full signed denominator; no selected/fold normalization',
        'execution_authorized':False,'physics_validated':False,'scope':'Prospective full-cohort MC residual/covariance. This tool admits/reads source evidence; it does not execute a scientific worker or prove production independence/absence of earlier adaptive data access.'}


def run(task,base,output):
    from ravel.workflow import science
    out=Path(output).absolute();owner=next((rd for rd in (out,*out.parents) if (rd/science.PLAN).is_file()),None)
    c.require(owner is not None,'ordinary approved MC closure worker required')
    plan=science.verify_worker(owner);spec=science.execution_spec(owner);validate_scope(spec)
    c.require(spec['mode']=='mc-closure' and spec['task']==task and out==(owner/plan['output_directory']/'mc-closure').absolute(),'actual closure task/destination differs')
    path,request,strategy,independence,loaded,guards,origin,cap,results=_load(task,base)
    c.require(not out.exists() and '..' not in out.parts and not any(p.is_symlink() for p in (out,*out.parents)) and
        not any(out.is_relative_to(p.parent) for p in [*cap.rows,*origin]),'fresh disjoint closure output required')
    out.mkdir(parents=True)
    evidence={'schema_version':1,'kind':SCOPE,'status':'passed','status_scope':SCOPE,'original_goal':request['original_goal'],
        'original_task_complete':False,'physics_validated':False,'execution_authorized':False,'requirements':request['requirements'],
        'sampling_law':strategy['sampling_law'],'full_sample_pairs':results,
        'full_original_deliveries':{role:row['full_delivery'] for role,row in loaded.items()},
        'original_source_independence':request['independence'],'frozen_strategy':request['strategy'],
        'prospective_partition_protocol':request['partition_protocol'],'partition_source_or_runtime_qualification_inferred':False,
        'strategy_retained_as_original_producer_input_before_both_runs':True,
        'earlier_adaptive_heldout_access_independently_excluded':False,'source_independence_independently_qualified':False,
        'observed_data_validation':False,'closure_p_value':None,'coverage_qualified':False,
        'limitations':['Complete independent production replicas, optionally assembled by the exact complete ordinary partition merge. Complementary train/validation folds require an explicit original joint fold construction/cross block; partition boundaries alone are not independent held-out cohorts.',
            'IID law and independent production are supplied scientific claims; member disjointness and source pinning alone cannot certify them.',
            'Original full denominator is conditioned fixed. Random denominator, uncertain transfer and cross-sample correlation require complete joint laws.',
            'All original signed entries/no-fills and SR/CR/VR moments retained. Fixed-N centered covariance differs from Poissonized Gram.',
            'No actual data-dependent closure, asymptotic p-value, calibration or discovery claim.']}
    pin=stream.write_new(out/'mc-closure-result.json',evidence)
    cap.finish()
    for guard,row in zip(guards,loaded.values()):
        guard.finish(row['result']);c.require(stream.ordinary_stream_delivery(row['result'],row['result_path'].parent,row['task'])==row['receipt'],'ending original delivery differs')
    stream.custody.asset_check({pin['path']:pin});return evidence


def write_report(result,out):
    pin=stream.write_new(Path(out)/'mc-closure-report.json',result)
    return [{'stem':'mc-closure-report','files':['mc-closure-report.json'],'normalization':'Original complete source exposures/conditional full signed denominators; explicit moment law','intended_commitments':[pin]}]
