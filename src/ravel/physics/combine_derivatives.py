"""Fixed-point consumer of the existing Combine workspace NLL.

This module imports no ROOT and creates no PDF, NLL or optimizer. The admitted
native worker supplies its existing ModelConfig/data/NLL objects and bound staged
kernel. Actual workspace coordinates are observed before compiling a stencil;
all values/constant flags and categories are restored before each evaluation and
on every return or exception. A native qualification is still required.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import os
from pathlib import Path

MAX_PARAMETERS=4096
MAX_DATA_ROWS=100000
MAX_DATA_CELLS=1000000
MAX_COMPONENTS=32768
MAX_CATEGORY_TYPES=1024
ROOT_SOURCE_POLICIES={'6.22/00': {'release': 'v6-22-00', 'default_global_source': 'model', 'dataset_snapshot_api': False, 'external_constraints_api': False, 'source_sha256': {'v6-22-00-RooAbsData.h': '43644e54d90f60cea4638d77a81a8eadfe45ae2b5a2f06fde29be56480d5b5b2', 'v6-22-00-ModelConfig.h': '01dfa01e3b378c7b5fa2a5d78cb03c81715e9fff8de8e70c1954d9e738323cbf', 'v6-22-00-RooAbsPdf.cxx': '5a1ed952f945c34148b1b3a1d7f257c58a621eff1097d3aaecb41a7f406d3882', 'v6-22-00-RooAbsArg.h': '1fa68f9d387a7991c34ccd552aaad4a73b23f13b71dc07100f8e9a6b11d86bb4'}}, '6.24/00': {'release': 'v6-24-00', 'default_global_source': 'model', 'dataset_snapshot_api': False, 'external_constraints_api': False, 'source_sha256': {'v6-24-00-RooAbsData.h': '2ff6f916366984a1d57f5bdbf6f9b4a29d79964efd68f7c3ca5e3eec82de2d16', 'v6-24-00-ModelConfig.h': '01dfa01e3b378c7b5fa2a5d78cb03c81715e9fff8de8e70c1954d9e738323cbf', 'v6-24-00-RooAbsPdf.cxx': '1533064505a105385c595786b2267808aa847168b14838eda66d7b95d36b4bc1'}}, '6.30/00': {'release': 'v6-30-00', 'default_global_source': 'data_with_model_fallback', 'dataset_snapshot_api': True, 'external_constraints_api': True, 'source_sha256': {'v6-30-00-RooAbsData.h': '330d8a6c430a5769cdad63f6b0c2e02442dbfdb749c24b3d8132100a7e122d88', 'v6-30-00-ModelConfig.h': 'b907d94ac235703d63f1e74608d27c8386488b0a2c9bbc62585d44b93a3b4514', 'v6-30-00-RooAbsPdf.cxx': 'c90e15108bfa0e1f2cef68ced4053f639d0be364ee64a497a735dc3520cd120a', 'v6-30-00-RooFit_ModelConfig.h': 'b2ecf99c64914187a0e70a65e78b2c2ba269ed962552d5dbd0eb35d17e1c5da9', 'v6-30-00-ConstraintHelpers.cxx': 'c30f0fa5dc6c6d8fbb10a952262377fc237e6125fea8540cd9243bd08cac7ed6'}}}
MAX_JOURNAL_BYTES=64*1024*1024
MAX_JOURNAL_EVENTS=4*256+16
NAME=re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _same(a,b):
    # Python numeric equality conflates signed zero (and bool/int). These are
    # recorded native assignments, so compare the strict canonical bytes too.
    return json.dumps(a,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(b,sort_keys=True,separators=(',',':'),allow_nan=False)


def finite(value,label):
    if type(value) not in (int,float):raise ValueError('finite '+label+' required')
    v=float(value)
    if not math.isfinite(v) or type(value) is int and int(v)!=value:raise ValueError('finite representable '+label+' required')
    return v


def validate_selection(selection):
    if type(selection) is not dict or set(selection)!={'anchor','axes','max_points'}:raise ValueError('closed derivative selection required')
    if type(selection['anchor']) is not dict or len(selection['anchor'])>MAX_PARAMETERS:raise ValueError('bounded explicit anchor overrides required')
    for name,value in selection['anchor'].items():
        if type(name) is not str or not NAME.fullmatch(name):raise ValueError('literal anchor coordinate required')
        finite(value,'anchor value')
    if type(selection['axes']) is not list or not 1<=len(selection['axes'])<=7:raise ValueError('one to seven derivative axes required')
    seen=set()
    for axis in selection['axes']:
        if type(axis) is not dict or set(axis)!={'name','step'} or type(axis['name']) is not str or not NAME.fullmatch(axis['name']) or axis['name'] in seen:raise ValueError('closed unique derivative axes required')
        if finite(axis['step'],'step')<=0:raise ValueError('positive derivative step required')
        seen.add(axis['name'])
    if type(selection['max_points']) is not int or not 1<=selection['max_points']<=256:raise ValueError('one to 256 derivative points required')


def _names(collection):
    return [str(item.GetName()) for item in collection] if collection else []


def model_config(mc):
    collections={key:getattr(mc,method)() for key,method in (
        ('pois','GetParametersOfInterest'),('nuisances','GetNuisanceParameters'),
        ('observables','GetObservables'),('global_observables','GetGlobalObservables'),
        ('conditional_observables','GetConditionalObservables'))}
    sets={key:_names(collection) for key,collection in collections.items()}
    sets['supplied_nll_options']={'constrain_nuisances':bool(collections['nuisances']),
                                  'global_observables':bool(collections['global_observables'])}
    accessor=getattr(mc,'GetExternalConstraints',None)
    sets['external_constraints']=_names(accessor()) if callable(accessor) else []
    sets['external_constraints_accessor']='available' if callable(accessor) else 'unavailable'
    tag_accessor=getattr(mc.GetPdf(),'getStringAttribute',None)
    if not callable(tag_accessor):raise ValueError('PDF default global tag accessor required')
    tag=tag_accessor('DefaultGlobalObservablesTag')
    if tag is not None and (type(tag) is not str or len(tag)>1024):raise ValueError('literal bounded PDF default global tag required')
    sets['default_global_observables_tag']=tag
    if any(len(names)!=len(set(names)) for key,names in sets.items() if key not in ('external_constraints_accessor','default_global_observables_tag','supplied_nll_options')):raise ValueError('duplicate ModelConfig coordinates')
    # Preserve the original Combine evaluator's exact Constrain/Globals command
    # list. This branch refuses model options it does not already implement.
    if sets['conditional_observables'] or sets['external_constraints']:
        raise ValueError('conditional/external ModelConfig sets unsupported by this existing Combine NLL definition')
    return {'name':str(mc.GetName()),'pdf_name':str(mc.GetPdf().GetName()),
            'pdf_class':str(mc.GetPdf().ClassName()),**sets,
            'nll_options':['Constrain(nuisances)']*sets['supplied_nll_options']['constrain_nuisances']+['GlobalObservables(globals)']*sets['supplied_nll_options']['global_observables'],
            'nll_other_options':'Unchanged pinned ROOT/custom-PDF defaults; no new Extended/Offset/backend options'}


def _bound(value,side):
    value=float(value)
    if math.isnan(value) or math.isinf(value) and (side=='min' and value>0 or side=='max' and value<0):
        raise ValueError('invalid native '+side+' bound')
    return None if math.isinf(value) else value


def _category(cat):
    size=int(cat.numTypes())
    if not 1<=size<=MAX_CATEGORY_TYPES:raise ValueError('bounded native category domain required')
    # getOrdinal returns the actual label/index pair, including sparse indices;
    # do not assume that setting indices 0..numTypes-1 enumerates every state.
    states=[]
    for i in range(size):
        pair=cat.getOrdinal(i);states.append({'label':str(pair.first),'index':int(pair.second)})
    if len({r['label'] for r in states})!=size or len({r['index'] for r in states})!=size:raise ValueError('unique category states required')
    index=int(cat.getIndex());label=str(cat.getLabel())
    if {'label':label,'index':index} not in states:raise ValueError('category is outside its declared domain')
    return {'name':str(cat.GetName()),'index':index,'label':label,'constant':bool(cat.isConstant()),'states':states}


def capture(workspace,mc):
    meta=model_config(mc);parameters=[];categories=[];names=set()
    sets={key:set(meta[key]) for key in ('pois','nuisances','observables','global_observables')}
    def role(name):
        if name in sets['global_observables']:return 'global_observable'
        if name in sets['observables']:return 'observable'
        if name in sets['pois']:return 'poi'
        if name in sets['nuisances']:return 'nuisance'
        return 'fixed'
    for var in workspace.allVars():
        name=str(var.GetName())
        if not NAME.fullmatch(name) or name in names:raise ValueError('unique supported native coordinate name required')
        names.add(name)
        parameters.append({'name':name,'value':finite(float(var.getVal()),'workspace value'),
            'constant':bool(var.isConstant()),'kind':'continuous','role':role(name),
            'bounds':{'min':_bound(var.getMin(),'min'),'max':_bound(var.getMax(),'max')}})
    for cat in workspace.allCats():
        c=_category(cat);name=c['name']
        if not NAME.fullmatch(name) or name in names:raise ValueError('unique supported native category name required')
        names.add(name);categories.append(c)
        indices=[s['index'] for s in c['states']]
        parameters.append({'name':name,'value':finite(c['index'],'category index'),'constant':c['constant'],
            'kind':'discrete','role':role(name),'bounds':{'min':min(indices),'max':max(indices)}})
    if not 1<=len(parameters)<=MAX_PARAMETERS or not set.union(*sets.values())<=names:raise ValueError('bounded complete ModelConfig/workspace coordinate population required')
    return {'parameters':parameters,'categories':categories,'model_config':meta}


def restore(workspace,mc,snapshot):
    for row in snapshot['parameters']:
        obj=workspace.var(row['name']) if row['kind']=='continuous' else workspace.cat(row['name'])
        if not obj:raise ValueError('native coordinate disappeared during evaluation')
        obj.setConstant(row['constant'])
        if row['kind']=='continuous':obj.setVal(row['value'])
        else:obj.setIndex(int(row['value']))
    if not _same(capture(workspace,mc),snapshot):raise ValueError('complete native coordinate reset failed')


def dataset_globals(data):
    """Observe the attached auxiliary snapshot, separately from model globals.

    A missing accessor is recorded as unavailable, never guessed to be an empty
    snapshot. The execution policy below admits that only for pinned old releases
    whose source does not implement attached snapshots.
    """
    accessor=getattr(data,'getGlobalObservables',None)
    if not callable(accessor):return {'accessor':'unavailable','snapshot':'unavailable','coordinates':None}
    collection=accessor()
    if collection is None:return {'accessor':'available','snapshot':'null','coordinates':None}
    try:items=list(collection)
    except ReferenceError:
        if bool(collection):raise
        return {'accessor':'available','snapshot':'null','coordinates':None}
    if len(items)>MAX_PARAMETERS:raise ValueError('bounded attached dataset global snapshot required')
    rows=[]
    for item in items:
        name=str(item.GetName())
        if not NAME.fullmatch(name):raise ValueError('supported dataset global name required')
        if item.InheritsFrom('RooAbsCategory'):
            row={'kind':'category','class':str(item.ClassName()),**_category(item)}
        elif item.InheritsFrom('RooRealVar'):
            row={'name':name,'kind':'real','class':str(item.ClassName()),'value':finite(float(item.getVal()),'dataset global'),
                 'constant':bool(item.isConstant()),'bounds':{'min':_bound(item.getMin(),'min'),'max':_bound(item.getMax(),'max')}}
        else:raise ValueError('dataset globals require assignable real/category values')
        rows.append(row)
    if len({r['name'] for r in rows})!=len(rows):raise ValueError('unique attached dataset globals required')
    return {'accessor':'available','snapshot':'set','coordinates':rows}


def global_source_semantics(context,initial,dataset):
    version=context['definition'].get('native_root_version')
    policy=ROOT_SOURCE_POLICIES.get(version)
    if policy is None:raise ValueError('source-qualified exact ROOT version required for dataset global semantics')
    globals_=dataset['global_observables']
    if (globals_['accessor']=='available')!=policy['dataset_snapshot_api']:
        raise ValueError('observed dataset global API differs from pinned ROOT source policy')
    meta=initial['model_config']
    if (meta['external_constraints_accessor']=='available')!=policy['external_constraints_api']:
        raise ValueError('observed external constraint API differs from pinned ROOT source policy')
    # ROOT selects the PDF default tag before the dataset auto-global fallback.
    # Do not report an empty/wrong selected set for that unimplemented branch.
    # Explicit ModelConfig globals supply the original worker option and take
    # precedence over this tag, so that existing branch remains usable.
    if not meta['supplied_nll_options']['global_observables'] and meta['default_global_observables_tag'] is not None:
        raise ValueError('PDF DefaultGlobalObservablesTag-selected globals unsupported by this thin Combine diagnostic route')
    snap={q['name']:q for q in globals_['coordinates'] or []}
    model={p['name']:p for p in initial['parameters']}
    names=meta['global_observables'] if meta['supplied_nll_options']['global_observables'] else list(snap) if policy['default_global_source']=='data_with_model_fallback' else []
    rows=[]
    for name in names:
        source='data_snapshot' if policy['default_global_source']=='data_with_model_fallback' and name in snap else 'model'
        if source=='model' and name not in model:raise ValueError('model global absent from observed coordinates')
        rows.append({'name':name,'source':source,'recorded_coordinate':deepcopy(snap[name] if source=='data_snapshot' else model[name])})
    return {'native_root_version':version,'source_policy':deepcopy(policy),'explicit_source_option':None,
            'default_source':policy['default_global_source'],'selected_globals':rows,
            'scope':'Pinned ROOT source default; custom-PDF compliance needs native qualification. No objective option is changed.'}


def data_census(data):
    n=int(data.numEntries())
    if not 1<=n<=MAX_DATA_ROWS:raise ValueError('bounded complete observed dataset required')
    rows=[];cells=0;order=None
    for i in range(n):
        coordinates=[]
        for item in data.get(i):
            name=str(item.GetName())
            if item.InheritsFrom('RooAbsCategory'):
                coordinates.append({'name':name,'kind':'category','index':int(item.getIndex()),'label':str(item.getLabel())})
            elif item.InheritsFrom('RooAbsReal'):
                coordinates.append({'name':name,'kind':'real','value':finite(float(item.getVal()),'data coordinate')})
            else:raise ValueError('unsupported observed dataset coordinate type')
        names=[c['name'] for c in coordinates];cells+=len(names)
        if not names or len(names)!=len(set(names)) or cells>MAX_DATA_CELLS:raise ValueError('bounded complete data covariate population required')
        if order is None:order=names
        if names!=order:raise ValueError('data coordinate order/population changed')
        rows.append({'index':i,'coordinates':coordinates,'weight':finite(float(data.weight()),'data weight')})
    return {'name':str(data.GetName()),'class':str(data.ClassName()),'entries':n,
            'sum_weights':finite(float(data.sumEntries()),'data sum weights'),'coordinate_order':order,'rows':rows,
            'global_observables':dataset_globals(data)}


def components(mc,nll):
    rows=[{'name':str(c.GetName()),'class':str(c.ClassName())} for c in mc.GetPdf().getComponents()]
    if not 1<=len(rows)<=MAX_COMPONENTS or len({r['name'] for r in rows})!=len(rows):raise ValueError('bounded unique PDF component census required')
    return {'nll_name':str(nll.GetName()),'nll_class':str(nll.ClassName()),'pdf_components':rows,
            'scope':'Names/classes and workspace blob identity; not a complete internal numerical table/ABI equivalence proof'}


def definition(context,snapshot,dataset,graph):
    if type(context) is not dict or set(context)!={'model_sha256','runtime_binding_sha256','definition'}:raise ValueError('closed admitted Combine derivative context required')
    for key in ('model_sha256','runtime_binding_sha256'):
        if type(context[key]) is not str or not re.fullmatch('[a-f0-9]{64}',context[key]):raise ValueError('admitted source/runtime SHA required')
    if type(context['definition']) is not dict:raise ValueError('explicit native NLL definition required')
    return {'admitted_definition':deepcopy(context['definition']),'initial_state':deepcopy(snapshot),
            'observed_data':deepcopy(dataset),'pdf_and_nll':deepcopy(graph),
            'global_observable_semantics':global_source_semantics(context,snapshot,dataset),
            'nll_convention':'NLL_not_minus_two_log_likelihood','parameter_order':'Actual workspace allVars then allCats iteration order; not inferred source order'}


def _validate_recording(initial,dataset,graph):
    """Validate recorded native populations without impersonating a ROOT read."""
    if type(initial) is not dict or set(initial)!={'parameters','categories','model_config'}:raise ValueError('closed native state required')
    meta=initial['model_config'];sets=('pois','nuisances','observables','global_observables','conditional_observables','external_constraints')
    if type(meta) is not dict or set(meta)!={'name','pdf_name','pdf_class','nll_options','nll_other_options','external_constraints_accessor','default_global_observables_tag','supplied_nll_options',*sets}:raise ValueError('closed native ModelConfig census required')
    for key in sets:
        rows=meta[key]
        if type(rows) is not list or any(type(n) is not str for n in rows) or len(rows)!=len(set(rows)):raise ValueError('unique complete native sets required')
    if meta['default_global_observables_tag'] is not None and (type(meta['default_global_observables_tag']) is not str or len(meta['default_global_observables_tag'])>1024):raise ValueError('literal bounded recorded PDF global tag required')
    if meta['external_constraints_accessor'] not in ('available','unavailable'):raise ValueError('recorded external accessor status required')
    if meta['external_constraints_accessor']=='unavailable' and meta['external_constraints']:raise ValueError('unavailable external accessor cannot supply a set')
    if meta['conditional_observables'] or meta['external_constraints']:raise ValueError('unsupported native conditional/external sets')
    options=meta['supplied_nll_options']
    if type(options) is not dict or set(options)!={'constrain_nuisances','global_observables'} or any(type(flag) is not bool for flag in options.values()):raise ValueError('actual native NLL option truthiness required')
    if (meta['nuisances'] and not options['constrain_nuisances']) or (meta['global_observables'] and not options['global_observables']):raise ValueError('nonempty native set cannot have absent option')
    if meta['nll_options']!=['Constrain(nuisances)']*options['constrain_nuisances']+['GlobalObservables(globals)']*options['global_observables']:raise ValueError('recorded NLL options differ')
    params=initial['parameters']
    if type(params) is not list or not 1<=len(params)<=MAX_PARAMETERS:raise ValueError('bounded native parameter census required')
    byname={p['name']:p for p in params}
    if len(byname)!=len(params) or not set.union(*(set(meta[k]) for k in sets[:4]))<=set(byname):raise ValueError('incomplete/duplicate recorded native coordinates')
    for p in params:
        role=('global_observable' if p['name'] in meta['global_observables'] else 'observable' if p['name'] in meta['observables']
              else 'poi' if p['name'] in meta['pois'] else 'nuisance' if p['name'] in meta['nuisances'] else 'fixed')
        if p['role']!=role:raise ValueError('recorded coordinate role differs from ModelConfig')
    cats=initial['categories']
    if type(cats) is not list or len(cats)!=sum(p['kind']=='discrete' for p in params):raise ValueError('complete recorded category census required')
    seen=set()
    for cat in cats:
        if type(cat) is not dict or set(cat)!={'name','index','label','constant','states'} or cat['name'] in seen:raise ValueError('closed unique category census required')
        seen.add(cat['name']);p=byname.get(cat['name']);states=cat['states']
        if type(states) is not list or not 1<=len(states)<=MAX_CATEGORY_TYPES:raise ValueError('bounded recorded category domain required')
        if any(type(s) is not dict or set(s)!={'label','index'} or type(s['label']) is not str or type(s['index']) is not int for s in states):raise ValueError('literal category states required')
        if len({s['label'] for s in states})!=len(states) or len({s['index'] for s in states})!=len(states):raise ValueError('unique recorded category domain required')
        if not p or p['kind']!='discrete' or type(cat['index']) is not int or type(cat['constant']) is not bool or cat['constant']!=p['constant'] or finite(cat['index'],'category index').hex()!=float(p['value']).hex() or {'label':cat['label'],'index':cat['index']} not in states:raise ValueError('category assignment differs from coordinate census')
        if p['bounds']!={'min':min(s['index'] for s in states),'max':max(s['index'] for s in states)}:raise ValueError('recorded category bounds differ')
    if type(dataset) is not dict or set(dataset)!={'name','class','entries','sum_weights','coordinate_order','rows','global_observables'} or type(dataset['entries']) is not int or not 1<=dataset['entries']<=MAX_DATA_ROWS or type(dataset['rows']) is not list or len(dataset['rows'])!=dataset['entries']:raise ValueError('complete observed data denominator required')
    _validate_globals(dataset['global_observables'])
    finite(dataset['sum_weights'],'recorded sum weights');cells=0
    for i,row in enumerate(dataset['rows']):
        if type(row) is not dict or set(row)!={'index','coordinates','weight'} or type(row['index']) is not int or row['index']!=i or type(row['coordinates']) is not list:raise ValueError('ordered observed data rows required')
        finite(row['weight'],'recorded data weight');names=[]
        for q in row['coordinates']:
            if type(q) is not dict or q.get('kind') not in ('real','category') or type(q.get('name')) is not str:raise ValueError('typed recorded data coordinates required')
            names.append(q['name'])
            if q['kind']=='real':
                if set(q)!={'name','kind','value'}:raise ValueError('closed real data coordinate required')
                finite(q['value'],'recorded data value')
            elif set(q)!={'name','kind','index','label'} or type(q['index']) is not int or type(q['label']) is not str:raise ValueError('closed category data coordinate required')
        cells+=len(names)
        if not names or len(names)!=len(set(names)) or names!=dataset['coordinate_order'] or cells>MAX_DATA_CELLS:raise ValueError('complete bounded data covariate census required')
    if type(graph) is not dict or set(graph)!={'nll_name','nll_class','pdf_components','scope'} or type(graph['pdf_components']) is not list or not 1<=len(graph['pdf_components'])<=MAX_COMPONENTS:raise ValueError('closed bounded PDF/NLL census required')
    if any(type(p) is not dict or set(p)!={'name','class'} or any(type(v) is not str or not v for v in p.values()) for p in graph['pdf_components']) or len({p['name'] for p in graph['pdf_components']})!=len(graph['pdf_components']):raise ValueError('unique PDF component names/classes required')


def _anchor(snapshot,selection,poi_domain):
    state=deepcopy(snapshot);byname={p['name']:p for p in state['parameters']}
    poi=poi_domain['name']
    if poi not in byname or byname[poi]['role']!='poi':raise ValueError('declared POI absent from observed state')
    lo,hi=map(float,poi_domain['bounds'])
    if not math.isfinite(lo) or not math.isfinite(hi) or lo>=hi:raise ValueError('ordered finite declared POI domain required')
    p=byname[poi]
    p['bounds']['min']=max(lo,p['bounds']['min']) if p['bounds']['min'] is not None else lo
    p['bounds']['max']=min(hi,p['bounds']['max']) if p['bounds']['max'] is not None else hi
    # The effective planning domain is an intersection, but reset guards must
    # preserve actual native bounds. Keep the planning copy separate.
    for name,value in selection['anchor'].items():
        if name not in byname:raise ValueError('anchor coordinate absent')
        q=byname[name]
        if q['constant'] or q['kind']!='continuous' or q['role'] not in {'poi','nuisance'}:raise ValueError('anchor may change only floating POI/nuisance')
        q['value']=finite(value,'anchor')
    return state


def _state_after_allowed(before,after):
    if not _same(before['model_config'],after['model_config']) or len(before['parameters'])!=len(after['parameters']):return False
    data_names=(set(before['model_config']['observables'])-set(before['model_config']['global_observables'])
                -set(before['model_config']['pois'])-set(before['model_config']['nuisances']))
    for a,b in zip(before['parameters'],after['parameters']):
        expected=deepcopy(a)
        if a['name'] in data_names:expected['value']=b['value']
        if not _same(expected,b):return False
    if len(before['categories'])!=len(after['categories']):return False
    for a,b in zip(before['categories'],after['categories']):
        expected=deepcopy(a)
        if a['name'] in data_names:expected.update(index=b['index'],label=b['label'])
        if not _same(expected,b):return False
    return True


class JsonlRecorder:
    """Exclusive bounded regular JSONL in the existing worker output directory."""
    def __init__(self,path):
        self.fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        self.bytes=0
    def __call__(self,event):
        raw=(json.dumps(event,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        if self.bytes+len(raw)>MAX_JOURNAL_BYTES:raise ValueError('native point journal byte budget exceeded')
        view=memoryview(raw)
        while view:
            written=os.write(self.fd,view)
            if written<=0:raise OSError('native point journal write did not progress')
            view=view[written:]
        os.fsync(self.fd);self.bytes+=len(raw)
    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None


class _Journal:
    def __init__(self,context,recorder):
        self.binding=digest(context);self.events=[];self.bytes=0;self.recorder=recorder;self.attempted=0;self.returned=0
    def emit(self,status,**payload):
        event={'schema_version':1,'kind':'combine-native-point-event','binding_sha256':self.binding,
               'sequence':len(self.events),'previous_sha256':self.events[-1]['event_sha256'] if self.events else None,
               'status':status,'payload':payload}
        event['event_sha256']=digest(event)
        raw=json.dumps(event,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        if len(self.events)>=MAX_JOURNAL_EVENTS or self.bytes+len(raw)+1>MAX_JOURNAL_BYTES:raise ValueError('native point journal budget exceeded')
        # Commit to the supplied durable recorder before acknowledging this event.
        # A recorder failure aborts execution; no next NLL call is authorized.
        if self.recorder is not None:self.recorder(deepcopy(event))
        self.events.append(event);self.bytes+=len(raw)+1


def _literal_return(value):
    # Numeric nonfinite returns are evidence tokens, never successful JSON NLLs.
    # The finite observation check still refuses them after durable retention.
    v=float(value)
    return {'kind':'binary64','hex':v.hex(),'finite':math.isfinite(v),'value':v if math.isfinite(v) else None}


def _validate_globals(record):
    if type(record) is not dict or set(record)!={'accessor','snapshot','coordinates'}:raise ValueError('closed dataset global snapshot required')
    if record['accessor']=='unavailable':
        if record['snapshot']!='unavailable' or record['coordinates'] is not None:raise ValueError('unavailable global accessor cannot supply values')
        return
    if record['accessor']!='available' or record['snapshot'] not in ('null','set'):raise ValueError('typed dataset global accessor status required')
    if record['snapshot']=='null':
        if record['coordinates'] is not None:raise ValueError('null dataset global snapshot cannot contain coordinates')
        return
    rows=record['coordinates']
    if type(rows) is not list or len(rows)>MAX_PARAMETERS:raise ValueError('bounded dataset global coordinates required')
    names=set()
    for q in rows:
        if type(q) is not dict or type(q.get('name')) is not str or not NAME.fullmatch(q['name']) or q['name'] in names or type(q.get('class')) is not str or not q['class'] or type(q.get('constant')) is not bool:raise ValueError('typed unique dataset globals required')
        names.add(q['name'])
        if q.get('kind')=='real':
            if set(q)!={'name','kind','class','value','constant','bounds'} or type(q['bounds']) is not dict or set(q['bounds'])!={'min','max'}:raise ValueError('closed real dataset global required')
            finite(q['value'],'recorded dataset global')
            for side,b in q['bounds'].items():
                if b is not None:finite(b,'dataset global bound')
            lo,hi=q['bounds']['min'],q['bounds']['max']
            if lo is not None and hi is not None and lo>=hi:raise ValueError('ordered dataset global bounds required')
        elif q.get('kind')=='category':
            if set(q)!={'name','kind','class','index','label','constant','states'} or type(q['index']) is not int or type(q['label']) is not str:raise ValueError('closed category dataset global required')
            states=q['states']
            if type(states) is not list or not 1<=len(states)<=MAX_CATEGORY_TYPES or any(type(s) is not dict or set(s)!={'label','index'} or type(s['index']) is not int or type(s['label']) is not str for s in states) or len({s['index'] for s in states})!=len(states) or len({s['label'] for s in states})!=len(states) or {'index':q['index'],'label':q['label']} not in states:raise ValueError('complete category dataset global domain required')
        else:raise ValueError('unsupported dataset global type')


def _execute(workspace,mc,data,nll,selection,context,poi_domain,kernel,*,initial_state=None,journal):
    """Observe the SUPPLIED NLL; journal returns before checking dependent state."""
    validate_selection(selection)
    initial=deepcopy(initial_state) if initial_state is not None else capture(workspace,mc)
    attempted=returned=0;result=None
    try:
        journal.emit('started',initial_state=initial,selection=selection)
        restore(workspace,mc,initial)
        dataset=data_census(data);graph=components(mc,nll)
        restore(workspace,mc,initial)
        law=definition(context,initial,dataset,graph)
        anchor=_anchor(initial,selection,poi_domain)
        identity={'model_sha256':context['model_sha256'],'runtime_binding_sha256':context['runtime_binding_sha256'],
                  'evaluation_definition_sha256':digest(law)}
        plan=kernel.compile_stencil({'schema_version':1,'kind':'native-likelihood-stencil','identity':identity,
            'parameters':anchor['parameters'],'axes':selection['axes'],'max_points':selection['max_points']})
        journal.emit('planned',plan_sha256=plan['plan_sha256'],identity=identity,point_count=len(plan['points']),definition=law)
        rows=[];states=[]
        for point in plan['points']:
            reset=deepcopy(initial)
            for expected,actual in zip(reset['parameters'],point['parameters']):
                expected['value']=actual['value'];expected['constant']=actual['constant']
            restore(workspace,mc,reset)
            assigned=capture(workspace,mc)
            before_globals=dataset_globals(data)
            if not _same(before_globals,dataset['global_observables']):raise ValueError('dataset global snapshot changed before NLL call')
            journal.emit('running',id=point['id'],parameters=point['parameters'],assigned_state=assigned,
                         dataset_globals=before_globals,attempted_calls=attempted+1)
            attempted+=1;journal.attempted=attempted
            raw_value=nll.getVal();returned+=1;journal.returned=returned
            journal.emit('returned',id=point['id'],literal_return=_literal_return(raw_value),returned_calls=returned)
            nll_value=finite(float(raw_value),'native NLL')
            after=capture(workspace,mc);after_globals=dataset_globals(data)
            if not _same(after_globals,dataset['global_observables']):raise ValueError('dataset global snapshot changed during NLL evaluation')
            if not _state_after_allowed(assigned,after):raise ValueError('NLL changed a non-observable value/flag/bound/category')
            row={'id':point['id'],'parameters':deepcopy(point['parameters']),'nll':nll_value}
            state={'id':point['id'],'assigned_state':assigned,'after_nll_state':after,
                   'dataset_globals_before':before_globals,'dataset_globals_after':after_globals}
            journal.emit('checked',id=point['id'],row=row,native_state=state)
            rows.append(row);states.append(state)
        if not _same(data_census(data),dataset):raise ValueError('observed data changed during NLL evaluation')
        observations={'schema_version':1,'kind':'native-likelihood-stencil-observations','identity':identity,
            'plan_sha256':plan['plan_sha256'],'rows':rows}
        estimates=kernel.reduce_observations(plan,observations)
        journal.emit('reduced',observations_sha256=digest(observations),estimates_sha256=digest(estimates))
        result={'schema_version':1,'kind':'combine-native-nll-derivatives','definition':law,'plan':plan,
                'observations':observations,'estimates':estimates,'native_states':states,
                'native_nll_calls':attempted,'native_returned_calls':returned,'fit_calls':0,'profiler_derivative_qualified':False,
                'scope':'Selected-axis native fixed-point diagnostics only; no optimization, covariance, globality or inference qualification'}
    except BaseException as exc:
        journal.emit('failed',error_type=type(exc).__name__,message=str(exc)[:4096],attempted_calls=attempted,returned_calls=returned)
        raise
    finally:
        try:
            restore(workspace,mc,initial)
            journal.emit('reset',state=capture(workspace,mc),dataset_globals=dataset_globals(data),attempted_calls=attempted,returned_calls=returned)
        except BaseException as exc:
            journal.emit('reset_failed',error_type=type(exc).__name__,message=str(exc)[:4096],attempted_calls=attempted,returned_calls=returned)
            raise
    result['final_state']=capture(workspace,mc)
    journal.emit('completed',attempted_calls=attempted,returned_calls=returned,fit_calls=0)
    result['point_journal']=journal.events
    return result


def execute(workspace,mc,data,nll,selection,context,poi_domain,kernel,*,initial_state=None,recorder=None):
    """Native worker supplies a durable recorder; pure callers get exception facts.

    Partial in-memory facts attached to an exception are not durable scientific
    delivery. The admitted worker always supplies JsonlRecorder and retains it
    through the existing failed-output transport.
    """
    journal=_Journal(context,recorder)
    try:
        return _execute(workspace,mc,data,nll,selection,context,poi_domain,kernel,
                        initial_state=initial_state,journal=journal)
    except BaseException as exc:
        exc.native_point_journal=deepcopy(journal.events)
        exc.native_call_accounting={'attempted':journal.attempted,'returned':journal.returned,
                                   'durable_recorder_supplied':recorder is not None,'successful_delivery':False}
        raise


def validate_journal(events,context,delivery):
    if type(events) is not list or not 1<=len(events)<=MAX_JOURNAL_EVENTS:raise ValueError('bounded complete point journal required')
    total=0
    for i,event in enumerate(events):
        if type(event) is not dict or set(event)!={'schema_version','kind','binding_sha256','sequence','previous_sha256','status','payload','event_sha256'}:raise ValueError('closed point journal event required')
        base={k:v for k,v in event.items() if k!='event_sha256'}
        if type(event['schema_version']) is not int or event['schema_version']!=1 or event['kind']!='combine-native-point-event' or event['binding_sha256']!=digest(context) or type(event['sequence']) is not int or event['sequence']!=i or event['previous_sha256']!=(events[i-1]['event_sha256'] if i else None) or event['event_sha256']!=digest(base):raise ValueError('source-bound ordered point journal required')
        total+=len(json.dumps(event,sort_keys=True,separators=(',',':'),allow_nan=False).encode())+1
    if total>MAX_JOURNAL_BYTES:raise ValueError('point journal byte budget exceeded')
    initial=delivery['definition']['initial_state'];plan=delivery['plan'];rows=delivery['observations']['rows'];states=delivery['native_states']
    # Selection is validated by the caller; compare its exact actual start record.
    if events[0]['status']!='started' or set(events[0]['payload'])!={'initial_state','selection'} or not _same(events[0]['payload']['initial_state'],initial):raise ValueError('point journal initial state differs')
    if events[1]['status']!='planned' or not _same(events[1]['payload'],{'plan_sha256':plan['plan_sha256'],'identity':plan['identity'],'point_count':len(plan['points']),'definition':delivery['definition']}):raise ValueError('point journal plan differs')
    cursor=2
    for i,(point,row,state) in enumerate(zip(plan['points'],rows,states)):
        expected_events=[('running',{'id':point['id'],'parameters':point['parameters'],'assigned_state':state['assigned_state'],'dataset_globals':state['dataset_globals_before'],'attempted_calls':i+1}),
            ('returned',{'id':point['id'],'literal_return':_literal_return(row['nll']),'returned_calls':i+1}),
            ('checked',{'id':point['id'],'row':row,'native_state':state})]
        for status,payload in expected_events:
            if cursor>=len(events) or events[cursor]['status']!=status or not _same(events[cursor]['payload'],payload):raise ValueError('point journal running/return/check evidence differs')
            cursor+=1
    tails=[('reduced',{'observations_sha256':digest(delivery['observations']),'estimates_sha256':digest(delivery['estimates'])}),
           ('reset',{'state':delivery['final_state'],'dataset_globals':delivery['definition']['observed_data']['global_observables'],'attempted_calls':len(rows),'returned_calls':len(rows)}),
           ('completed',{'attempted_calls':len(rows),'returned_calls':len(rows),'fit_calls':0})]
    if len(events)!=cursor+len(tails):raise ValueError('complete success journal denominator differs')
    for event,(status,payload) in zip(events[cursor:],tails):
        if event['status']!=status or not _same(event['payload'],payload):raise ValueError('point journal terminal/reset evidence differs')


def read_journal(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>MAX_JOURNAL_BYTES:raise ValueError('ordinary bounded point journal required')
    with path.open('rb') as f:raw=f.read(MAX_JOURNAL_BYTES+1)
    if len(raw)>MAX_JOURNAL_BYTES or not raw.endswith(b'\n'):raise ValueError('complete bounded point journal lines required')
    return [json.loads(line) for line in raw.splitlines()]


def validate_delivery(delivery,selection,context,poi_domain,kernel):
    """Host replay of recorded protocol/weights; execution authority stays separate."""
    required={'schema_version','kind','definition','plan','observations','estimates','native_states','native_nll_calls','fit_calls','profiler_derivative_qualified','scope','final_state','native_returned_calls','point_journal'}
    if type(delivery) is not dict or set(delivery)!=required or type(delivery['schema_version']) is not int or delivery['schema_version']!=1 or delivery['kind']!='combine-native-nll-derivatives':raise ValueError('closed Combine derivative delivery required')
    validate_selection(selection)
    law=delivery['definition'];initial=law['initial_state']
    _validate_recording(initial,law['observed_data'],law['pdf_and_nll'])
    if not _same(law,definition(context,initial,law['observed_data'],law['pdf_and_nll'])):raise ValueError('Combine definition/identity changed')
    anchor=_anchor(initial,selection,poi_domain)
    identity={'model_sha256':context['model_sha256'],'runtime_binding_sha256':context['runtime_binding_sha256'],'evaluation_definition_sha256':digest(law)}
    expected=kernel.compile_stencil({'schema_version':1,'kind':'native-likelihood-stencil','identity':identity,'parameters':anchor['parameters'],'axes':selection['axes'],'max_points':selection['max_points']})
    if not _same(delivery['plan'],expected) or not _same(delivery['estimates'],kernel.reduce_observations(expected,delivery['observations'])):raise ValueError('Combine derivative plan/reduction changed')
    if type(delivery['fit_calls']) is not int or delivery['fit_calls']!=0 or delivery['profiler_derivative_qualified'] is not False or type(delivery['native_nll_calls']) is not int or delivery['native_nll_calls']!=len(expected['points']) or type(delivery['native_returned_calls']) is not int or delivery['native_returned_calls']!=len(expected['points']) or type(delivery['native_states']) is not list or len(delivery['native_states'])!=len(expected['points']):raise ValueError('complete zero-fit native point denominator required')
    for point,state in zip(expected['points'],delivery['native_states']):
        reset=deepcopy(initial)
        for expected_row,actual in zip(reset['parameters'],point['parameters']):
            expected_row['value']=actual['value'];expected_row['constant']=actual['constant']
        if type(state) is not dict or set(state)!={'id','assigned_state','after_nll_state','dataset_globals_before','dataset_globals_after'} or state['id']!=point['id'] or not _same(state['assigned_state'],reset) or not _state_after_allowed(reset,state['after_nll_state']) or not _same(state['dataset_globals_before'],law['observed_data']['global_observables']) or not _same(state['dataset_globals_after'],law['observed_data']['global_observables']):raise ValueError('recorded complete native reset/state differs')
    if not _same(delivery['final_state'],initial):raise ValueError('recorded final source state was not restored')
    if type(delivery['point_journal']) is not list or len(delivery['point_journal'])<2:raise ValueError('complete point journal required')
    if not _same(delivery['point_journal'][0]['payload']['selection'],selection):raise ValueError('journal selection differs')
    validate_journal(delivery['point_journal'],context,delivery)
    return delivery['estimates']
