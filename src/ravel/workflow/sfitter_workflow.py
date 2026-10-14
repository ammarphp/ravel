"""Portable SFitterAgents scientific phases on ordinary Ravel Host/Graph.

Adapted domain workflow from MIT-licensed SFitterAgents 6072a79e. The original
specialist text is exact pinned context, with explicit Ravel authority and native
statistical overrides. This module neither launches models/natives nor votes.
"""
from pathlib import Path
import re
from ravel.physics import model_tool_bridge as custody, sfitter_inputs, sfitter_native, eft_conventions
from ravel.workflow import agent_graph, provider_transport
from ravel.workflow.state_io import read_json

PHASES=('extraction','sm_template','parameterization','conventions','datacard')
ROLES={
 'extraction':('sf-measurement-extractor','sf-systematics-decomposer','sf-id-encoder'),
 'sm_template':('sf-order-corrector','sf-scale-uncertainty-estimator','sf-pdf-uncertainty-estimator','sf-parametric-uncertainty-estimator','ma-scales-pdf-consultant'),
 'parameterization':('sf-scan-designer','sf-scan-sanitizer','sf-kappa-extractor','ma-eft-consultant','ma-coupling-order-consultant','ma-ufo-consultant'),
 'conventions':('sf-convention-translator','sf-methodology-consultant'),
 'datacard':('sf-modifier-namer','sf-datacard-schema-reviewer','sf-reviewer')}
SKILLS={'extraction':'sf-extract','sm_template':'sf-sm-template','parameterization':'sf-parameterize','conventions':'sf-parameterize','datacard':'sf-datacard'}
CORE=('sfitter/sfitter/likelihood/full_likelihood.py','sfitter/sfitter/likelihood/predictions.py','sfitter/sfitter/likelihood/datacard.py','sfitter/sfitter/eval/confidence.py')
BOUNDARY=('Upstream specialists are scientific knowledge, not authority to spawn jobs, use SLURM, install tools, mutate memory or approve a stage. '
 'Use only pinned full-study inputs; do not invent measurements, theory errors, covariance, k-factors or fit diagnostics. '
 'The native top code uses signed component-wise RFit clamp, correlated contraction and capped correlation shrinkage; it returns -Q and profiles exp(-Q). '
 'Native top multi-bin groups normalize exact polynomial predictions by their width-weighted sum; native Higgs channels stay absolute and retain branching/production/EWPO source laws. Keep signed SM-D6 interference and optional D6-square/cross terms separate. '
 'No automatic Gaussian/pyhf substitution, Taylor normalization, omitted-operator aliasing, RGE or basis transformation is admitted. '
 'A generated artifact is a source-bound draft; native execution and independent critique/verifier decisions use ordinary science/review gates.')


def _known():return read_json(sfitter_native.upstream_census_path())['files']
def _pin(path):return {'path':str(path),'sha256':custody._hash(path)}
def _closed(v,keys,label):sfitter_native._keys(v,keys,label)
def _refs(value):
    for pin in sfitter_native._pins(value):yield pin

def model_action(model):
    """Source-declared adapter; omission retains the original Responses graph."""
    _closed(model, {'name','reasoning_effort','max_output_tokens'} |
            ({'adapter'} if type(model) is dict and 'adapter' in model else set()),
            'portable model declaration')
    for key in ('name','reasoning_effort'):sfitter_native._text(model[key],key)
    sfitter_native._integer(model['max_output_tokens'],'model tokens',16,32768)
    adapter=model.get('adapter','responses')
    if type(adapter) is not str or adapter not in provider_transport.MODEL_ACTIONS:
        raise ValueError('known explicit model adapter or configured model action required')
    return adapter


def validate(request):
    fields={'schema_version','id','upstream_tree','sources','target','handoffs','model','max_wall_seconds'}
    _closed(request,fields|({'retained_review_contexts'} if 'retained_review_contexts' in request else set())|({'native_profile'} if 'native_profile' in request else set()),'SFitter workflow request')
    if 'retained_review_contexts' in request:
        _review_context_shape(request['retained_review_contexts'])
    if type(request['schema_version']) is not int or request['schema_version']!=1 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,50}',str(request['id'])):raise ValueError('workflow identity required')
    if type(request['sources']) is not list or not request['sources']:raise ValueError('actual measurement/model source pins required')
    _closed(request['target'],('observables','eft','process','perturbative_order','model_source'),'scientific population')
    target=request['target']
    for k in ('process','perturbative_order','model_source'):sfitter_native._text(target[k],k)
    if type(target['observables']) is not list or not target['observables']:raise ValueError('whole observation population required')
    names=[]
    for row in target['observables']:
        _closed(row,('ID','name','bins','representation','normalization','unit'),'requested observable')
        for k in ('ID','name','unit'):sfitter_native._text(row[k],k)
        if type(row['bins']) is not list or not row['bins'] or len(set(row['bins']))!=len(row['bins']):raise ValueError('whole unique bin identities required')
        for name in row['bins']:sfitter_native._text(name,'bin identity')
        if row['normalization']!=('absolute' if request.get('native_profile',{}).get('profile')=='higgs' else 'normalized' if len(row['bins'])>1 else 'absolute') or row['representation'] not in ('integrated','differential'):raise ValueError('native group meaning requires normalized multi-bin groups and absolute singletons')
        names.append(row['ID'])
    if len(set(names))!=len(names):raise ValueError('duplicate observation')
    eft=target['eft']
    _closed(eft,('basis','quadratic','mixed_pairs','source_scale_gev','target_scale_gev','coefficient_unit','lambda_unit','flavour'),'requested EFT scope')
    if type(eft['basis']) is not list or len(eft['basis']) not in (20,22) or len(set(eft['basis']))!=len(eft['basis']) or type(eft['quadratic']) is not bool or type(eft['mixed_pairs']) is not list:raise ValueError('full declared native basis/truncation required')
    if 'native_profile' in request:
        from ravel.physics import sfitter_profiles
        profile=request['native_profile']
        _closed(profile,('profile','parameters','algorithm','run_card'),'source-defined physical fit profile')
        if profile['profile'] not in ('top','higgs') or profile['algorithm'] not in sfitter_profiles.ALGORITHMS:
            raise ValueError('source-supported physical sector and fitter required')
        if type(profile['parameters']) is not list or not profile['parameters'] or len(set(profile['parameters']))!=len(profile['parameters']) or any(p not in eft['basis'] for p in profile['parameters']):raise ValueError('ordered selected sector coordinates required')
        _closed(profile['run_card'],('path','sha256'),'declared source-defined run settings')
    pairs=[]
    for pair in eft['mixed_pairs']:
        if type(pair) is not list or len(pair)!=2 or any(v not in eft['basis'] for v in pair) or pair[0]==pair[1]:raise ValueError('invalid declared mixed interference population')
        pairs.append(tuple(sorted(pair)))
    if len(set(pairs))!=len(pairs) or (pairs and not eft['quadratic']):raise ValueError('mixed terms conflict with truncation')
    if sfitter_inputs._finite(eft['source_scale_gev'])<=0 or eft['source_scale_gev']!=eft['target_scale_gev']:raise ValueError('scale evolution requires a separately admitted RGE method')
    for k in ('coefficient_unit','lambda_unit','flavour'):sfitter_native._text(eft[k],k)
    if type(request['handoffs']) is not dict or not set(request['handoffs'])<=set(PHASES):raise ValueError('known ordered phase handoffs required')
    model_action(request['model'])
    sfitter_native._integer(request['max_wall_seconds'],'advisory graph wall',1,86400)
    return request


def _review_context_shape(bindings):
    """Optional copied-source provenance, never a carried review verdict."""
    from . import physics_review as review
    if type(bindings) is not list or not 1 <= len(bindings) <= len(PHASES):
        raise ValueError('finite original phase context provenance required')
    roots=[]
    for binding in bindings:
        _closed(binding,('root','support'),'retained phase contexts')
        sfitter_native._text(binding['root'],'original review root')
        if type(binding['support']) is not list or not 1 <= len(binding['support']) <= 512:
            raise ValueError('complete bounded typed context roster required')
        for pin in binding['support']:
            review._support_shape(pin)
            if pin.get('kind')!='role_context':raise ValueError('typed original context provenance required')
        if len({pin['path'] for pin in binding['support']})!=len(binding['support']):
            raise ValueError('duplicate retained phase context')
        roots.append(binding['root'])
    if len(set(roots))!=len(roots):raise ValueError('duplicate retained review root')


def _review_empty_sources(bindings,base):
    """Reuse the producer's complete context/cycle law; identify only empty SOURCE copies."""
    import hashlib
    from . import physics_review as review, review_context
    _review_context_shape(bindings)
    empty=hashlib.sha256(b'').hexdigest();allowed={};required=set()
    for binding in bindings:
        root=review._root(custody._regular(binding['root'],base,directory=True))
        reg,events=review._read(root);view=review._view(reg,events)
        canonical=lambda pin:{**pin,'path':str(review._path(root,pin['path']))}
        actual={pin['path']:pin for row in view['reviews'] for pin in row.get('supporting_artifacts',[]) if pin.get('kind')=='role_context'}
        expected=sorted((canonical(pin) for pin in actual.values()),key=lambda pin:pin['path'])
        supplied=sorted((canonical(pin) for pin in binding['support']),key=lambda pin:pin['path'])
        if supplied!=expected:raise ValueError('retained contexts differ from complete original review roster')
        review._supporting(root,binding['support'])
        required.update(Path(path) for path in review.bound_paths(root))
        for pin in binding['support']:
            index=review_context._PacketIndex(review._path(root,pin['path']).parent,pin['manifest_sha256'])
            cycle=next(e for e in events if e['event']=='cycle' and e['cycle_id']==pin['cycle_id'] and e['sha256']==pin['cycle_sha256'])
            for entry in index.entries.values():
                if entry['sha256']!=empty:continue
                if index.read(entry)!=b'':raise ValueError('retained empty SOURCE copy changed')
                snapshot=next(s for s in cycle['snapshots'] if s['path']==entry['source_path'] and s['sha256']==empty)
                for path in (index.paths[entry['id']],review._path(root,snapshot['path'],allow_empty=True),review._path(root,snapshot['snapshot'],allow_empty=True)):
                    allowed[path]=empty
            index.finish()
    if not set(allowed)<=required:raise ValueError('empty SOURCE provenance escaped complete source census')
    return allowed,required


def _capture_review_sources(bindings,base,capture=None):
    """SFitter-local zero-byte SOURCE reader; generic Capture stays strict."""
    import copy
    import os
    from ravel.physics.ma5_saf import Capture, _identity
    combined=copy.deepcopy(getattr(capture,'review_contexts',[]))
    for binding in bindings:
        same=[b for b in combined if b['root']==binding['root']]
        if same and same[0]!=binding:raise ValueError('retained context provenance changed')
        if not same:combined.append(copy.deepcopy(binding))
    allowed,required=_review_empty_sources(combined,base)
    class SourceCapture(Capture):
        def bounded(self,path):
            if path not in self.empty_sources:return super().bounded(path)
            before=self.ordinary(path)
            if before[3]!=0:raise ValueError('authenticated empty SOURCE became nonempty')
            with path.open('rb') as stream:
                if _identity(os.fstat(stream.fileno()))!=before:raise ValueError('empty SOURCE descriptor replaced')
                raw=stream.read(1)
                if raw or _identity(os.fstat(stream.fileno()))!=before:raise ValueError('empty SOURCE changed during capture')
            if self.ordinary(path)!=before:raise ValueError('empty SOURCE pathname changed')
            return before,raw
        def finish(self):
            if _review_empty_sources(self.review_contexts,self.review_base)!=(self.empty_sources,self.review_paths):
                raise ValueError('complete retained context/source population changed')
            super().finish()
            if _review_empty_sources(self.review_contexts,self.review_base)!=(self.empty_sources,self.review_paths):
                raise ValueError('ending retained context/source population changed')
    result=SourceCapture()
    if capture is not None:
        result.files=copy.deepcopy(capture.files);result.paths=copy.deepcopy(capture.paths);result.roots=copy.deepcopy(capture.roots)
    result.review_contexts=combined;result.review_base=base
    result.empty_sources=allowed;result.review_paths=required
    return result


def _source_capture(request,base,capture=None):
    from ravel.physics.ma5_saf import Capture
    if 'retained_review_contexts' not in request:return capture if capture is not None else Capture()
    result=_capture_review_sources(request['retained_review_contexts'],base,capture)
    declared={custody._pin(pin,base) for pin in request['sources']}
    if not result.review_paths<=declared:raise ValueError('retained review child/source population was dropped')
    return result


def _knowledge(request,base,phase):
    tree=request['upstream_tree'];_closed(tree,('root','manifest'),'source declaration')
    root=custody._regular(tree['root'],base,directory=True);manifest=custody._pin(tree['manifest'],base)
    declared=read_json(manifest);_closed(declared,('schema_version','files'),'source census')
    if type(declared['schema_version']) is not int or declared['schema_version']!=1 or declared['files']!=_known():raise ValueError('declared upstream source epoch differs')
    paths=[manifest]
    rels=[*CORE,'LICENSE','sfitteragents/.claude/skills/'+SKILLS[phase]+'/SKILL.md',
          *['sfitteragents/.claude/agents/'+role+'.md' for role in ROLES[phase]]]
    for rel in rels:
        path=custody._regular(root/rel,base)
        if custody._hash(path)!=declared['files'].get(rel):raise ValueError('specialist/core source changed')
        paths.append(path)
    from ravel.physics import sfitter_profiles
    expected_basis=(sfitter_profiles.basis(root,request['native_profile']['profile']) if 'native_profile' in request else sfitter_inputs.native_basis(root))
    if request['target']['eft']['basis']!=expected_basis:raise ValueError('declared basis differs from native code')
    return root,paths


def _terms(target):
    basis=target['eft']['basis']
    return [*basis,*([x+'x'+x for x in basis] if target['eft']['quadratic'] else []),
            *[a+'x'+b for a,b in target['eft']['mixed_pairs']]]

def _handoff(request,document,base,phase):
    _closed(document,('schema_version','phase','target_sha256','sources','payload','physics_validated','execution_authorized'),'scientific handoff')
    if type(document['schema_version']) is not int or document['schema_version']!=1 or document['phase']!=phase or document['target_sha256']!=agent_graph.digest(request['target']) or document['physics_validated'] is not False or document['execution_authorized'] is not False:raise ValueError('handoff premise/population/authority differs')
    if type(document['sources']) is not list or not document['sources']:raise ValueError('actual phase evidence required')
    for pin in document['sources']:custody._pin(pin,base)
    target=request['target'];payload=document['payload']
    if phase in ('extraction','sm_template','parameterization'):
        _closed(payload,('rows',),'whole phase population')
        if type(payload['rows']) is not list or len(payload['rows'])!=len(target['observables']):raise ValueError('partial scientific population refused')
        for row,wanted in zip(payload['rows'],target['observables']):
            if row.get('ID')!=wanted['ID'] or row.get('name')!=wanted['name']:raise ValueError('positional observable identity changed')
            n=len(wanted['bins'])
            if phase=='extraction':
                required={'ID','name','bin_widths','Meas','Bkg','modifiers'}
                if set(row) not in (required,required|{'bin_correlation'},required|{'Luminosity','Decay'},required|{'bin_correlation','Luminosity','Decay'}):raise ValueError('closed extracted native observation required')
                # Native parser checks shapes, named uncertainty keys and full modifiers.
                dummy={'observations':[row], 'predictions':[{'ID':row['ID'],'name':row['name'],'data':[1.]*n,'modifiers':[]}]}
                if 'native_profile' in request:
                    root=custody._regular(request['upstream_tree']['root'],base,directory=True)
                    sfitter_inputs.inspect_profile_datacard(dummy,root,request['native_profile']['profile'],_observation_only=True)
                else:sfitter_inputs.inspect_datacard(dummy,target['eft']['basis'])
                if len(row['Meas']['data'])!=n:raise ValueError('extracted bins missing')
            elif phase=='sm_template':
                _closed(row,('ID','name','data','theory_modifiers','perturbative_order','evidence'),'SM template')
                sfitter_inputs._vector(row['data'],n,'SM template')
                if row['perturbative_order']!=target['perturbative_order']:raise ValueError('SM perturbative order changed')
                custody._pin(row['evidence'],base)
                if type(row['theory_modifiers']) is not list:raise ValueError('explicit scale/PDF/parametric/order theory sources required')
                fake={'ID':row['ID'],'name':row['name'],'Meas':{'data':[1.]*n,'modifiers':[]},'Bkg':{'data':[0.]*n,'modifiers':[]},'modifiers':row['theory_modifiers'],'bin_widths':[1.]*n}
                fake['Meas']['modifiers']=[{'type':kind,'name':kind,'data':[0.]*n} for kind in ('pois','stat')]
                sfitter_inputs.inspect_datacard({'observations':[fake],'predictions':[{'ID':row['ID'],'name':row['name'],'data':row['data'],'modifiers':[]}]},target['eft']['basis'])
            else:
                _closed(row,('ID','name','modifiers','scan_evidence','coupling_sanity_evidence','fit_diagnostics'),'signed EFT template')
                mods=row['modifiers']
                if type(mods) is not list or (request.get('native_profile',{}).get('profile')!='higgs' and [m.get('name') for m in mods]!=_terms(target)):raise ValueError('complete ordered linear/square/mixed coefficient population required')
                for term in mods:
                    _closed(term,{'name','data'}|({'type'} if 'type' in term else set()),'native EFT coefficient')
                    if request.get('native_profile',{}).get('profile')=='higgs':
                        if type(term['data']) is not list or not term['data']:raise ValueError('full native Higgs mixture/coefficient source required')
                        for value in term['data']:sfitter_inputs._finite(value)
                    else:sfitter_inputs._vector(term['data'],n,'signed EFT coefficient')
                for field in ('scan_evidence','coupling_sanity_evidence','fit_diagnostics'):custody._pin(row[field],base)
    elif phase=='conventions':
        if type(payload) is not dict or set(payload) not in ({'semantic_manifest'}, {'semantic_manifest','transport_request','transport_result'}):
            raise ValueError('closed source-bound convention mapping required')
        custody._pin(payload['semantic_manifest'],base)
        if 'transport_request' in payload:
            rp=custody._pin(payload['transport_request'],base);result_path=custody._pin(payload['transport_result'],base)
            eft_conventions.verify_result({'request':str(rp)},rp.parent,read_json(result_path))
    else:
        _closed(payload,('datacard','run_card','semantic_manifest'),'native-card handoff')
        for pin in payload.values():custody._pin(pin,base)
    return document


def _resolve(request,base):
    validate(request);documents={};phase=None
    for p in PHASES:
        if p not in request['handoffs']:
            phase=p;break
        path=custody._pin(request['handoffs'][p],base)
        documents[p]=_handoff(request,read_json(path),path.parent,p)
    if set(request['handoffs'])!=set(documents):raise ValueError('phase skipped before genuine prior handoff')
    return documents,phase


def input_pins(request,base):
    docs,phase=_resolve(request,base);_,knowledge=_knowledge(request,base,phase or 'datacard')
    paths=[*([custody._pin(request['native_profile']['run_card'],base)] if 'native_profile' in request else []),*knowledge,*[custody._pin(pin,base) for pin in request['sources']],*[custody._pin(pin,base) for pin in request['handoffs'].values()]]
    for p,doc in docs.items():
        parent=custody._pin(request['handoffs'][p],base).parent
        paths.extend(custody._pin(pin,parent) for pin in _refs(doc))
        if p=='conventions' and 'transport_request' in doc['payload']:
            rp=custody._pin(doc['payload']['transport_request'],parent)
            paths.extend(eft_conventions.inputs({'request':str(rp)},rp.parent))
    if 'retained_review_contexts' in request:
        _,required=_review_empty_sources(request['retained_review_contexts'],base)
        if not required<=set(paths):raise ValueError('retained review child/source population was dropped')
    return [_pin(path) for path in sorted(set(paths))]


def context(request,base):
    docs,phase=_resolve(request,base);pins=input_pins(request,base)
    if phase is None:ready=ready_native(request,base)
    else:ready=None
    return {'schema_version':1,'kind':'sfitter_scientific_workflow','phase':phase or 'native_plan_required',
            'upstream_commit':sfitter_native.COMMIT,'upstream_license':'MIT; original notices remain in source',
            'target':request['target'],'phase_handoffs':docs,'inputs':pins,
            'specialists':list(ROLES[phase]) if phase else [],'native_input':ready,
            'execution_authorized':False,'physics_validated':False,'model_calls_observed':0,
            'limits':[BOUNDARY,'Memory is only an explicitly supplied source pin, never a cached scientific verdict.']}


def phase_graph(request,base,request_pin,*,source_packet=None):
    prepared=context(request,base);phase=prepared['phase']
    if phase not in PHASES:raise ValueError('all source handoffs complete: prepare the ordinary native science plan')
    root,_=_knowledge(request,base,phase);nodes=[]
    pins=[request_pin,*prepared['inputs']]
    if source_packet is not None:
        from . import sfitter_source_context
        cp,_=sfitter_source_context.verified_packet_sources(source_packet,request_pin,base,purpose='specialist')
        pins=[cp]
    elif len(pins)>128:raise ValueError('complete specialist context requires a separately prepared specialist source packet')
    for i,role in enumerate(ROLES[phase]):
        instruction=BOUNDARY+'\nScientific phase: '+phase+'\nAdapt the following upstream specialist to the requested whole population. Return a draft handoff and explicit missing evidence; do not fabricate completion.\n'+(root/'sfitteragents/.claude/agents'/ (role+'.md')).read_text()
        nodes.append({'id':role,'kind':'model','role':'designer','depends_on':[],
                      'inputs':[{'id':'source'+str(j),**pin} for j,pin in enumerate(pins)],'packet':source_packet,'action':model_action(request['model']),
                      'parameters':{'instructions':instruction,'model':request['model']['name'],'reasoning_effort':request['model']['reasoning_effort'],
                                    'max_output_tokens':request['model']['max_output_tokens'],'output_schema':None},'max_attempts':1})
    return agent_graph.validate({'schema_version':1,'graph_id':request['id']+'_'+phase,
        'budget':{'max_nodes':len(nodes),'max_calls':len(nodes),'max_output_tokens':len(nodes)*request['model']['max_output_tokens'],
                  'max_wall_seconds':request['max_wall_seconds'],'max_reworks':0},'nodes':nodes})


def _composed_card(docs):
    # Released sf-datacard phases 2 and 3: lift existing values; never infer them.
    import copy
    expected=[]
    for obs,sm,terms in zip(docs['extraction']['payload']['rows'],docs['sm_template']['payload']['rows'],docs['parameterization']['payload']['rows']):
        row={**obs,'modifiers':[*obs['modifiers'],*sm['theory_modifiers']]};expected.append(row)
    predictions=[{'ID':sm['ID'],'name':sm['name'],'data':sm['data'],'modifiers':terms['modifiers']} for sm,terms in zip(docs['sm_template']['payload']['rows'],docs['parameterization']['payload']['rows'])]
    return copy.deepcopy({'observations':expected,'predictions':predictions})


def _native_conventions(request,docs,base,card,sem,sem_path):
    if sem['purpose']!='supplied_full_study' or sem['observables']!=request['target']['observables']:raise ValueError('native manifest differs from whole-study scientific population')
    target=request['target']['eft']
    for a,b in (('basis','target_basis'),('quadratic','quadratic'),('mixed_pairs','mixed_pairs'),('source_scale_gev','source_scale_gev'),('target_scale_gev','target_scale_gev'),('coefficient_unit','coefficient_unit'),('lambda_unit','lambda_unit'),('flavour','flavour')):
        if target[a]!=sem['eft'][b]:raise ValueError('convention/truncation handoff changed')
    convention=custody._pin(docs['conventions']['payload']['semantic_manifest'],custody._pin(request['handoffs']['conventions'],base).parent)
    if custody._hash(convention)!=custody._hash(sem_path):raise ValueError('native convention evidence changed after translation')
    payload=docs['conventions']['payload']
    if 'transport_request' in payload:
        parent=custody._pin(request['handoffs']['conventions'],base).parent
        rp=custody._pin(payload['transport_request'],parent)
        transported=eft_conventions.verify_result({'request':str(rp)},rp.parent,read_json(custody._pin(payload['transport_result'],parent)))
        native=transported['target_convention'];original=transported['source_convention']
        if (native['axes']!=target['basis'] or transported['quadratic']!=target['quadratic'] or
            sem['eft']['conversion']!='preconverted_source_bound_card' or original['basis']!=sem['eft']['source_basis'] or
            any(native[k]!=sem['eft'][k] for k in ('flavour','coefficient_unit','lambda_unit')) or
            eft_conventions._q(native['renormalization_scale_gev'])!=eft_conventions._q(str(target['target_scale_gev']))):
            raise ValueError('exact transported convention differs from native scientific target')
        population=[{key:row[key] for key in ('ID','name','bins','unit')} for row in transported['observables']]
        if population!=[{key:row[key] for key in ('ID','name','bins','unit')} for row in request['target']['observables']]:
            raise ValueError('transported whole observable/bin/unit population changed')
        predicted=[]
        axis_order={axis:i for i,axis in enumerate(native['axes'])}
        def term_key(axes):
            return tuple(sorted(axes,key=axis_order.__getitem__))
        for row,exact in zip(transported['binary64_projection'],transported['observables']):
            terms={term_key(term['axes']):term['data'] for term in row['terms']}
            exact_terms={():exact['sm'],**{(term['axis'],):term['data'] for term in exact['linear']},
                         **{term_key(term['axes']):term['data'] for term in exact['quadratic']}}
            names=_terms(target=request['target'])
            modifiers=[{'name':name,'data':terms[term_key(name.split('x'))]} for name in names]
            used={term_key(name.split('x')) for name in names}|{()}
            if any(any(eft_conventions._q(v)!=0 for v in data) for key,data in exact_terms.items() if key not in used):
                raise ValueError('nonzero transported operator term omitted by native card')
            predicted.append({'ID':row['ID'],'name':row['name'],'data':terms[()], 'modifiers':modifiers})
        if predicted!=card['predictions']:raise ValueError('native card differs from exact recorded binary64 projection')


def ready_native(request,base):
    docs,phase=_resolve(request,base)
    if phase is not None:raise ValueError('all full scientific handoffs must exist before native planning')
    root,_=_knowledge(request,base,'datacard');last=docs['datacard']['payload'];lastbase=custody._pin(request['handoffs']['datacard'],base).parent
    card_path=custody._pin(last['datacard'],lastbase);run_path=custody._pin(last['run_card'],lastbase);sem_path=custody._pin(last['semantic_manifest'],lastbase)
    card=read_json(card_path)
    if 'native_profile' in request:
        from ravel.physics import sfitter_profiles
        from ravel.physics import sfitter_complete_native
        profile=request['native_profile']
        bound=sfitter_profiles.compile_card(root,card_path,run_path,profile['profile'],profile['parameters'],profile['algorithm'])
        sem=sfitter_complete_native.semantic(read_json(sem_path),card,bound)
    else:
        bound=sfitter_inputs.compile_known_card(root,card_path,run_path,input_scope='upstream_known_card')
        sem=sfitter_native.semantic(read_json(sem_path),card,bound['active_parameter_names'])
    _native_conventions(request,docs,base,card,sem,sem_path)
    if 'native_profile' in request:
        original=custody._pin(request['native_profile']['run_card'],base)
        wanted=sfitter_profiles.yaml_document(original.read_text());actual=bound['params'].copy()
        for k in ('run_name','datacard'):wanted.pop(k,None);actual.pop(k,None)
        if actual!=wanted:raise ValueError('composed native numerical settings differ from original declared card')
    if card!=_composed_card(docs):raise ValueError('datacard is not the exact lossless full scientific handoff composition')
    return {'datacard':_pin(card_path),'run_card':_pin(run_path),'semantic_manifest':_pin(sem_path),
            'native_score':'-Q','native_profile':'exp(-Q)','requires':'fresh ordinary sfitter-native-fit plan, admitted runtime and CHECK-IN 1',
            'execution_authorized':False,'physics_validated':False}


def apply_handoff(request,document,base):
    _,phase=_resolve(request,base)
    if phase is None:raise ValueError('source phases complete; no automatic fit or new phase')
    _handoff(request,document,base,phase)
    return {'schema_version':1,'kind':'sfitter_phase_handoff','phase':phase,'target_sha256':agent_graph.digest(request['target']),
            'handoff_sha256':agent_graph.digest(document),'accepted_as':'source_bound_draft',
            'execution_authorized':False,'physics_validated':False,'next_phase':PHASES[PHASES.index(phase)+1] if phase!='datacard' else 'ordinary_native_plan_required'}


def assembly_inputs(request,base):
    """Exact bytes read by deterministic card construction, not fit inputs."""
    docs,phase=_resolve(request,base)
    if phase!='datacard':raise ValueError('assembly requires exactly four complete scientific handoffs')
    root,_=_knowledge(request,base,'datacard')
    template=custody._pin(request['native_profile']['run_card'],base) if 'native_profile' in request else custody._regular(root/'sfitter/params/top_fit.yaml',base)
    if 'native_profile' not in request and custody._hash(template)!=_known().get('sfitter/params/top_fit.yaml'):
        raise ValueError('upstream numerical run template changed')
    parent=custody._pin(request['handoffs']['conventions'],base).parent
    sem_path=custody._pin(docs['conventions']['payload']['semantic_manifest'],parent)
    paths=[template,*[Path(pin['path']) for pin in input_pins(request,base)]]
    paths.extend(custody._pin(pin,sem_path.parent) for pin in _refs(read_json(sem_path)))
    return [_pin(path) for path in sorted(set(paths))]


def _absolute_pins(value,base):
    if type(value) is dict:
        if set(value)=={'path','sha256'}:return _pin(custody._pin(value,base))
        return {key:_absolute_pins(item,base) for key,item in value.items()}
    if type(value) is list:return [_absolute_pins(item,base) for item in value]
    return value


def _strict_document(raw):
    import json
    from ravel.workflow.state_io import _unique
    def reject(value):raise ValueError('nonfinite scientific document number: '+value)
    return json.loads(raw,object_pairs_hook=_unique,parse_constant=reject,
                      parse_float=lambda value:sfitter_inputs._finite(float(value)))


def assembly_graph(request,base,request_pin,*,source_packet=None):
    from ravel.physics.ma5_saf import Capture
    capture=_source_capture(request,base);path,raw=capture.pin(request_pin,base)
    if _strict_document(raw)!=request:raise ValueError('assembly graph request bytes differ')
    pins=[_pin(path),*assembly_inputs(request,base)]
    if source_packet is not None:
        from . import sfitter_source_context
        _,allowed=sfitter_source_context.verified_packet_sources(source_packet,request_pin,base,purpose='assembly')
        if not {tuple(sorted(p.items())) for p in assembly_inputs(request,base)}<={tuple(sorted(p.items())) for p in allowed}:
            raise ValueError('complete deterministic assembly dependencies required')
        pins=[_pin(path)]
    elif len(pins)>128:raise ValueError('complete assembly requires a separately prepared assembly source packet')
    graph=agent_graph.validate({'schema_version':1,'graph_id':request['id']+'_assemble',
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,
                  'max_wall_seconds':request['max_wall_seconds'],'max_reworks':0},
        'nodes':[{'id':'assemble_native_card','kind':'tool','role':'designer','depends_on':[],
                  'inputs':[{'id':'source'+str(j),**pin} for j,pin in enumerate(pins)],'packet':source_packet,
                  'action':'sfitter-assemble','parameters':{'request_input':'source0'},'max_attempts':1}]})
    capture.finish()
    return graph


def assemble_datacard(request,base,*,run_name='ravel_source_draft'):
    """Port released assembly to native JSON/YAML; no numerical library import."""
    if type(run_name) is not str or not re.fullmatch(r'[A-Za-z0-9_]{1,64}',run_name):
        raise ValueError('safe literal native run name required')
    pins=assembly_inputs(request,base)
    # Reuse the ordinary bounded descriptor/ancestor capture. Parse and copy
    # these same authenticated bytes, never a later pathname read.
    from ravel.physics.ma5_saf import Capture
    capture=_source_capture(request,base);raws={}
    for pin in pins:
        path,raw=capture.pin(pin,base);raws[path]=raw
    docs={}
    for phase in PHASES[:4]:
        path=custody._pin(request['handoffs'][phase],base)
        docs[phase]=_handoff(request,_strict_document(raws[path]),path.parent,phase)
    root,_=_knowledge(request,base,'datacard')
    card=_composed_card(docs)
    if 'native_profile' in request:
        from ravel.physics import sfitter_profiles
        selected=sfitter_profiles.selection(root,request['native_profile']['profile'],request['native_profile']['parameters'])
        if selected['full']!=request['target']['eft']['basis']:raise ValueError('scientific card sector convention differs')
        from ravel.physics.sfitter_card_derivation import profile_census
        selected_run=request['native_profile']['run_card']
        census=profile_census(card,root,request['native_profile']['profile'],selected_run,raws[custody._pin(selected_run,base)],base)
    else:census=sfitter_inputs.inspect_datacard(card,request['target']['eft']['basis'])
    parent=custody._pin(request['handoffs']['conventions'],base).parent
    sem_path=custody._pin(docs['conventions']['payload']['semantic_manifest'],parent)
    sem=(_complete_semantic(request,_strict_document(raws[sem_path]),card,root) if 'native_profile' in request else sfitter_native.semantic(_strict_document(raws[sem_path]),card,request['target']['eft']['basis']))
    _native_conventions(request,docs,base,card,sem,sem_path)
    template=raws[custody._pin(request['native_profile']['run_card'],base) if 'native_profile' in request else root/'sfitter/params/top_fit.yaml'].decode('utf-8')
    run_card=re.sub(r'^run_name:[^\n]*$',lambda _: 'run_name: '+run_name,template,flags=re.M)
    run_card=re.sub(r'^datacard:[^\n]*$','datacard: data/assembled.json',run_card,flags=re.M)
    if assembly_inputs(request,base)!=pins:
        raise ValueError('scientific assembly inputs changed before return')
    capture.finish()
    return {'schema_version':1,'kind':'sfitter_native_datacard_draft','upstream_commit':sfitter_native.COMMIT,
            'target_sha256':agent_graph.digest(request['target']),'inputs':[*pins,*census.get('reviewed_inputs',[])],
            'datacard':card,'run_card':run_card,'semantic_manifest':sem,
            'semantic_source':_pin(sem_path),'semantic_source_text':raws[sem_path].decode('utf-8'),
            'census':census,'native_score':'-Q','native_profile':'exp(-Q)',
            'native_parser_roundtrip':'not_executed','scientific_handoffs':'source_bound_drafts_not_review_votes',
            'physics_validated':False,'execution_authorized':False}


def materialize_datacard(request,base,output,*,run_name='ravel_source_draft',native_settings=None,request_pin=None,production_roster=None):
    """Write a fresh native bundle and optional fit config for ordinary planning.

    This neither calls science.plan nor approves or dispatches anything. Runtime
    settings are explicit supplied declarations; their admission is still fresh.
    """
    from ravel.workflow.state_io import atomic_json
    out=Path(output).absolute()
    if ('..' in out.parts or out.exists() or out.is_symlink() or
        any(p.is_symlink() for p in out.parents)):
        raise ValueError('fresh ordinary assembly directory without aliases required')
    root=custody._regular(request['upstream_tree']['root'],base,directory=True)
    if out.is_relative_to(root):raise ValueError('assembly must preserve the original upstream source tree')
    bundle=assemble_datacard(request,base,run_name=run_name)
    source_paths=[Path(pin['path']) for pin in bundle['inputs']]
    before=sfitter_native._identity(source_paths)
    settings=None;settings_path=None
    from ravel.physics.ma5_saf import Capture
    capture=_source_capture(request,base)
    if 'native_profile' in request:
        from ravel.physics.sfitter_complete_native import transport_capture
        settings_capture=transport_capture();generated=transport_capture()
    else:settings_capture=capture;generated=Capture()
    members={'data','params'}
    def written(path,raw):
        import hashlib
        generated.read(path,out,hashlib.sha256(raw).hexdigest())
        members.add(path.relative_to(out).as_posix())
    def write_json(path,value):
        import json
        raw=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf-8')
        atomic_json(path,value);written(path,raw)
    def write_bytes(path,raw):
        path.write_bytes(raw);written(path,raw)
    if request_pin is not None:
        path,raw=capture.pin(request_pin,base)
        if _strict_document(raw)!=request:raise ValueError('supplied assembly request bytes differ')
        source_paths.append(path);before=sfitter_native._identity(source_paths)
    if native_settings is not None:
        settings_path,raw=settings_capture.pin(native_settings,base);settings=_strict_document(raw)
        _closed(settings,('schema_version','source','trusted_upstream_python','runtime','max_seconds','max_ram_mib','max_export_bytes'),'supplied native planning settings')
        if type(settings['schema_version']) is not int or settings['schema_version']!=1:
            raise ValueError('native planning settings version required')
        settings=_absolute_pins(settings,settings_path.parent)
        source_paths.append(settings_path)
        source_paths.extend(custody._pin(pin,settings_path.parent) for pin in _refs(settings))
        before=sfitter_native._identity(source_paths)
    producers=None
    if production_roster is not None:
        if 'native_profile' not in request or settings is None:raise ValueError('producer continuity requires complete native profile and planning settings')
        roster_path,raw=capture.pin(production_roster,base);roster=_strict_document(raw)
        _closed(roster,('schema_version','producers'),'ordinary producer roster')
        if type(roster['schema_version']) is not int or roster['schema_version']!=1:raise ValueError('ordinary producer roster version required')
        producers=roster['producers'];source_paths.append(roster_path);before=sfitter_native._identity(source_paths)
    out.mkdir(parents=True,exist_ok=False);(out/'data').mkdir();(out/'params').mkdir()
    for path in (out,out/'data',out/'params'):generated.ordinary(path,directory=True)
    card=out/'data/assembled.json';run=out/'params/assembled.yaml';sem=out/'semantic.json'
    write_json(card,bundle['datacard']);write_bytes(run,bundle['run_card'].encode('utf-8'));write_bytes(sem,bundle['semantic_source_text'].encode('utf-8'))
    handoff={'schema_version':1,'phase':'datacard','target_sha256':bundle['target_sha256'],
             'sources':bundle['inputs'],'payload':{'datacard':_pin(card),'run_card':_pin(run),'semantic_manifest':bundle['semantic_source']},
             'physics_validated':False,'execution_authorized':False}
    hp=out/'datacard-handoff.json';write_json(hp,handoff)
    updated=_absolute_pins(request,base)
    updated['upstream_tree']['root']=str(root)
    updated['handoffs']['datacard']=_pin(hp)
    wp=out/'workflow.json';write_json(wp,updated)
    ready=ready_native(updated,out)
    config=None
    if settings is not None:
        config={'schema_version':1,'operation':'fit','purpose':'supplied_full_study',
                'source':settings['source'],'upstream_tree':updated['upstream_tree'],
                'trusted_upstream_python':settings['trusted_upstream_python'],'runtime':settings['runtime'],
                **handoff['payload'],'vectors':[],
                **{key:settings[key] for key in ('max_seconds','max_ram_mib','max_export_bytes')}}
        if 'native_profile' in request:
            profile=request['native_profile']
            config.update(schema_version=2,profile=profile['profile'],parameters=profile['parameters'],algorithm=profile['algorithm'],phase='run',saved_run=None,inference='native_profile_and_marginal_measure_unqualified',production_handoff=None)
        if producers is not None:
            producer_path=out/'producer-handoff.json'
            producer_doc={'schema_version':1,'kind':'sfitter_ordinary_producer_to_fit','workflow':_pin(wp),'producers':producers,'target_sha256':bundle['target_sha256']}
            write_json(producer_path,producer_doc);config['production_handoff']=_pin(producer_path)
        sfitter_native.validate_config(config)
        cp=out/'native-config.json';write_json(cp,config)
        # Actual native adapter input enumeration; no Torch/SFitter/fit import.
        native_inputs=sfitter_native.inputs({'config':str(cp)},out)
        prior={p:before[str(p)] for p in source_paths}
        for path,row in sfitter_native._identity(native_inputs).items():
            if Path(path) not in prior:before[path]=row;source_paths.append(Path(path))
        config=_pin(cp)
    if (assemble_datacard(request,base,run_name=run_name)!=bundle or
        sfitter_native._identity(source_paths)!=before):
        raise ValueError('scientific assembly or supplied runtime changed before completion')
    capture.finish();settings_capture.finish()
    # Compare original emitted commitments after all ending callbacks; never
    # recapture a changed draft as the successful output. Scientific members
    # outside this closed bundle are not silently admitted.
    if {p.relative_to(out).as_posix() for p in out.rglob('*')}!=members:
        raise ValueError('generated native bundle membership changed before completion')
    generated.finish()
    receipt={'schema_version':1,'kind':'sfitter_native_bundle_preparation','workflow':_pin(wp),
             'datacard_handoff':_pin(hp),'native_input':ready,'native_config':config,
             'native_task':{'config':config['path']} if config else None,
             'next_action':'fresh ordinary sfitter-native-fit science plan and actual CHECK-IN 1',
             'physics_validated':False,'execution_authorized':False,'native_calls_observed':0,
             'generated_files':[{'path':str(p),'sha256':__import__('hashlib').sha256(v[1]).hexdigest()} for p,v in sorted(generated.files.items())],
             'native_parser_roundtrip':'not_executed','upstream_reviews':'not_inferred_from_draft_handoffs'}
    atomic_json(out/'assembly-receipt.json',receipt)
    return receipt


def review_graph(critic_packet,verifier_packet,model,*,graph_id,max_wall_seconds):
    """Only genuine ordinary review_context/failed_stage_review role packets work."""
    action=model_action(model);nodes=[]
    for role,packet in (('critic',critic_packet),('verifier',verifier_packet)):
        nodes.append({'id':'sfitter_'+role,'kind':'model','role':role,'depends_on':[],'inputs':[],'packet':packet,'action':action,
          'parameters':{'instructions':BOUNDARY+' Review actual native outputs independently. Check entire bin/operator/pair population, exact conventions, input correlations, nonfinite/underflow arrays, profile-search status and interval method. Preserve failure and missing evidence. A delivery vote cannot certify an EFT domain or convergence.',
                        'model':model['name'],'reasoning_effort':model['reasoning_effort'],'max_output_tokens':model['max_output_tokens'],'output_schema':None},'max_attempts':1})
    return agent_graph.validate({'schema_version':1,'graph_id':graph_id,'budget':{'max_nodes':2,'max_calls':2,'max_output_tokens':2*model['max_output_tokens'],'max_wall_seconds':max_wall_seconds,'max_reworks':0},'nodes':nodes})


def main(argv=None):
    import argparse
    from ravel.workflow.state_io import atomic_json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('context','graph','handoff','assemble','assembly-graph','materialize'))
    parser.add_argument('--request',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--handoff')
    parser.add_argument('--run-name',default='ravel_source_draft');parser.add_argument('--native-settings');parser.add_argument('--producers')
    args=parser.parse_args(argv);path=custody._regular(args.request,Path.cwd())
    if args.action in ('assemble','assembly-graph','materialize'):
        from ravel.physics.ma5_saf import Capture
        request_capture=Capture();_,raw=request_capture.read(path,path.parent)
        request=_strict_document(raw)
    else:request=read_json(path)
    if args.action=='materialize':
        settings=_pin(custody._regular(args.native_settings,path.parent)) if args.native_settings else None
        materialize_datacard(request,path.parent,args.output,run_name=args.run_name,native_settings=settings,request_pin=_pin(path),production_roster=_pin(custody._regular(args.producers,path.parent)) if args.producers else None)
        request_capture.finish()
        return 0
    if args.action=='context':result=context(request,path.parent)
    elif args.action=='graph':result=phase_graph(request,path.parent,_pin(path))
    elif args.action=='assembly-graph':result=assembly_graph(request,path.parent,_pin(path))
    elif args.action=='assemble':result=assemble_datacard(request,path.parent,run_name=args.run_name)
    else:
        if not args.handoff:parser.error('handoff needs --handoff')
        handoff_path=custody._regular(args.handoff,path.parent)
        result=apply_handoff(request,read_json(handoff_path),handoff_path.parent)
    out=Path(args.output).absolute()
    if out.exists():raise ValueError('fresh workflow output required')
    if args.action in ('assemble','assembly-graph'):request_capture.finish()
    atomic_json(out,result);return 0


def _complete_semantic(request,document,card,root):
    from ravel.physics import sfitter_profiles, sfitter_complete_native
    profile=request['native_profile']
    selection=sfitter_profiles.selection(root,profile['profile'],profile['parameters'])
    return sfitter_complete_native.semantic(document,card,{'profile':profile['profile'],'selection':selection})


if __name__=='__main__':raise SystemExit(main())
