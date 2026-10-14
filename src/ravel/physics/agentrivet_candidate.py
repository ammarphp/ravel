"""Import AgentRivet outputs as supplied, unqualified RAVEL source candidates.

No upstream code, provider or generated C++ is imported or executed. This small
file boundary deliberately does not manufacture AgentGraph model genealogy.
"""
from pathlib import Path
import hashlib,json,math,os,re,stat
from ravel import analysis_sources

MAX_FILE_BYTES=8*1024*1024
MAX_TOTAL_BYTES=32*1024*1024
MODEL_FIELDS={'beam_energy','process','object_construction','cuts','histograms','hepdata_url','fiducial_definition'}
HIST_FIELDS={'name','observable_definition','binning_source','hepdata_id','bin_edges','description'}

REQUEST_FIELDS={'schema_version','routine','translation_unit','memory','paper','assets'}
SELECTION_BASES={'upstream_accepted','last_observed_compile','last_draft'}


def request_fields(request):
    """Import request fields; ``selection`` names a draft other than the upstream default."""
    return REQUEST_FIELDS|({'selection'} if type(request) is dict and 'selection' in request else set())


def _selected(memory,drafts,selection):
    if selection is None:return memory.get('accepted_code') or drafts[-1]
    _closed(selection,{'draft_index','basis'})
    index=selection['draft_index']
    if type(index) is not int or not 0<=index<len(drafts) or selection['basis'] not in SELECTION_BASES:raise ValueError('selected draft index and basis required')
    if memory.get('accepted_code') is not None and (selection['basis']!='upstream_accepted' or drafts[index]!=memory['accepted_code']):raise ValueError('an upstream-accepted draft must be the selection')
    if selection['basis']=='last_draft' and index!=len(drafts)-1:raise ValueError('last-draft selection must name the last draft')
    return drafts[index]


def _closed(value,fields):
    if type(value) is not dict or set(value)!=set(fields):raise ValueError('closed importer fields required')

def _pairs(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise ValueError('duplicate JSON key')
        out[key]=value
    return out

def _json(raw):
    def refuse(value):raise ValueError('nonfinite JSON number')
    out=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=refuse)
    def finite(value):
        if type(value) is float and not math.isfinite(value):raise ValueError('nonfinite JSON number')
        if type(value) is list:
            for row in value:finite(row)
        if type(value) is dict:
            for row in value.values():finite(row)
    finite(out);return out

def _snapshot(pin,base):
    _closed(pin,{'path','sha256'})
    if type(pin['path']) is not str or type(pin['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',pin['sha256']):raise ValueError('literal file and SHA256 required')
    path=Path(pin['path']);path=path if path.is_absolute() else Path(base)/path
    path=path.absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('ordinary input paths required')
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_FILE_BYTES:raise ValueError('bounded regular file required')
        raw=stream.read(before.st_size+1);after=os.fstat(stream.fileno())
    # A retained descriptor may remain identical after its parent is renamed
    # and replaced by a symlink. Refuse ending aliases as well as initial ones.
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('ordinary ending input paths required')
    identity=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if identity(before)!=identity(after) or identity(after)!=identity(path.stat()) or len(raw)!=before.st_size:raise ValueError('input changed during snapshot')
    if hashlib.sha256(raw).hexdigest()!=pin['sha256']:raise ValueError('actual consumed bytes differ')
    return path,raw

def _model(memory):
    value=memory.get('analysis_model')
    _closed(value,{'__kind__','__class__','data'})
    if value['__kind__']!='pydantic' or value['__class__']!='AnalysisModel':raise ValueError('actual Memory AnalysisModel serialization required')
    model=value['data'];_closed(model,MODEL_FIELDS)
    for k in ('beam_energy','process','object_construction','fiducial_definition'):
        if type(model[k]) is not str or not model[k].strip():raise ValueError('nonempty analysis definition required')
    if model['hepdata_url'] is not None and type(model['hepdata_url']) is not str:raise ValueError('literal HEPData URL or null required')
    if type(model['cuts']) is not list or len(model['cuts'])>256 or any(type(v) is not str for v in model['cuts']):raise ValueError('bounded cut population required')
    if type(model['histograms']) is not list or len(model['histograms'])>256:raise ValueError('bounded histogram population required')
    for hist in model['histograms']:
        _closed(hist,HIST_FIELDS)
        if any(type(hist[k]) is not str or not hist[k].strip() for k in ('name','observable_definition')):raise ValueError('literal histogram definition required')
        if hist['binning_source'] not in ('HEPDATA','TEXT'):raise ValueError('known binning source required')
        # These are upstream declarations, not verified paper or table mappings.
        if hist['bin_edges'] is not None and (type(hist['bin_edges']) is not list or len(hist['bin_edges'])>10000 or any(type(v) not in (float,int) for v in hist['bin_edges'])):raise ValueError('bounded numeric declared edges required')
        if hist['hepdata_id'] is not None and type(hist['hepdata_id']) is not str:raise ValueError('literal declared table ID required')
        if hist['description'] is not None and type(hist['description']) is not str:raise ValueError('literal description required')
    return model

def import_candidate(request,*,base_dir,output_dir):
    """Retain exact raw outputs and map all supplied scientific declarations.

    The caller supplies only four inputs: routine name, raw .cc pin, original
    Memory JSON pin and extracted paper-text pin; optional assets are explicit
    file pins/roles. Paper bytes must match Memory.paper_text, the paper
    component of Analyst input; HEPData context may also enter that prompt.
    An upstream accepted_code marker remains a supplier assertion, never a
    RAVEL review, build, runtime or scientific verdict.
    """
    _closed(request,request_fields(request))
    if type(request['schema_version']) is not int or request['schema_version']!=1:raise ValueError('import/v1 required')
    routine=request['routine']
    if type(routine) is not str or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,127}',routine):raise ValueError('literal routine required')
    if type(request['assets']) is not list or len(request['assets'])>32:raise ValueError('bounded optional assets required')
    snapshots={name:_snapshot(request[name],base_dir) for name in ('translation_unit','memory','paper')}
    memory=_json(snapshots['memory'][1])
    if type(memory) is not dict:raise ValueError('Memory object required')
    if memory.get('paper_text')!=snapshots['paper'][1].decode('utf-8'):raise ValueError('paper text differs from the retained upstream input')
    model=_model(memory);code=snapshots['translation_unit'][1]
    if not code or len(code)>2_000_000:raise ValueError('bounded nonempty C++ candidate required')
    code.decode('utf-8')
    drafts=memory.get('code_draft',[])
    if type(drafts) is not list or not drafts or any(type(d) is not str for d in drafts):raise ValueError('retained code draft population required')
    selected=_selected(memory,drafts,request.get('selection'))
    if type(selected) is not str or selected.encode('utf-8')!=code:raise ValueError('C++ differs from literal upstream selected output')
    assets=[];names={routine+'.cc'}
    for row in request['assets']:
        _closed(row,{'path','role','input'});analysis_sources.relative_path(row['path'])
        if row['path'] in names or row['path'].startswith('provenance/') or row['role'] not in {'header','reference','configuration','model','preprocessing','data','license'}:raise ValueError('distinct explicit asset role/path required')
        names.add(row['path']);assets.append((row,_snapshot(row['input'],base_dir)))
    if sum(len(raw) for _,raw in snapshots.values())+sum(len(v[1]) for _,v in assets)>MAX_TOTAL_BYTES:raise ValueError('aggregate import byte ceiling exceeded')
    output=Path(output_dir).absolute()
    if output.exists() or any(p.is_symlink() for p in (output,*output.parents)):raise ValueError('fresh ordinary output directory required')
    output.mkdir(parents=True);tree=output/'source';tree.mkdir();facts=[]
    def retain(name,raw,role):
        p=tree/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        facts.append({'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'role':role})
    retain(routine+'.cc',code,'compile')
    for name in ('memory','paper'):retain('provenance/'+name+('.json' if name=='memory' else '.source'),snapshots[name][1],'data')
    retain('provenance/import-request.json',json.dumps(request,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n','data')
    for row,(_,raw) in assets:retain(row['path'],raw,row['role'])
    capsule={'schema_version':1,'kind':'analysis-source-capsule','framework':'rivet','routine':routine,
      'source':{'repository':'supplied','revision':None,'description':'Exact caller-supplied AgentRivet .cc, Memory and paper; origin/calls not independently authenticated.'},
      'root':str(tree),'files':facts,'layout':{'include_dirs':['.'],'asset_dirs':sorted({str(Path(f['path']).parent) for f in facts if f['role'] in ('reference','configuration')})},
      'dependencies':[{'name':'fresh-source-runtime-assets','kind':'source','status':'unresolved','files':[routine+'.cc'],'reason':'Fresh dependency/API/metadata/reference review and runtime sealing required.'}],
      'dependency_review':{'complete':False,'description':'No upstream code approval or physics advisory is inherited as closure.'},'submodules':[]}
    inventory=analysis_sources.inventory(capsule,output)
    bindings=analysis_sources.routine_bindings(capsule,output,[routine+'.cc'])
    obligations=[]
    def obligation(identity,selector,declaration):
        obligations.append({'id':identity,'selector':selector,'declaration':declaration,'status':'unverified_supplier_claim','paper_fidelity_verified':False})
    for k in ('beam_energy','process','object_construction','fiducial_definition','hepdata_url'):obligation(k,'/analysis_model/data/'+k,model[k])
    for i,cut in enumerate(model['cuts']):obligation('cut-'+str(i),'/analysis_model/data/cuts/'+str(i),cut)
    for i,hist in enumerate(model['histograms']):obligation('histogram-'+str(i),'/analysis_model/data/histograms/'+str(i),hist)
    outstanding=['independent paper/specification completeness and ambiguity review','normalization, units, uncertainty and complete RAW/final/output census','exact source/header/assets/reference/runtime closure','actual compile and fresh plugin/registration','whole supplied-event and boundary/flow/signed-weight validation','independent scientific review and scope decision']
    proposal={'schema_version':1,'kind':'imported-unqualified-agentrivet-source-proposal','routine':routine,
      'original_inputs':{name:{'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()} for name,(p,raw) in snapshots.items()},
      'analysis_model':model,'upstream_code_acceptance_asserted':bool(memory.get('accepted_code')),
      'draft_selection':request.get('selection') or {'draft_index':len(drafts)-1,'basis':'upstream_accepted' if memory.get('accepted_code') else 'last_draft'},
      'upstream_reviews':{k:memory.get(k,[]) for k in ('code_review','physics_review')},
      'obligations':obligations,'outstanding_obligations':outstanding,'literal_registration_observation':bindings,
      'next_build_recipe':{'name':'rivet-plugin','compile_units':[routine+'.cc'],'output':'Rivet'+routine+'.so','flags':[]},
      'next_public_APIs':['analysis_sources.inventory','routine_build.seal_configuration after independent closure','science.design/plan/approve/run for routine-build','existing_events rivet-built after accepted actual build'],
      'AgentGraph_model_receipt':None,'provider_model_calls_authenticated':False,'prior_votes_carried':[],
      'execution_authorized':False,'physics_validated':False,'scientific_acceptance':False}
    def document(name,data):
        p=output/name;p.write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n')
        return {'path':str(p),'sha256':analysis_sources.digest(p)}
    return {'capsule':document('candidate-capsule.json',capsule),'inventory':document('source-inventory.json',inventory),'proposal':document('source-proposal.json',proposal)}
