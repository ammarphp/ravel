"""Source-bound native event-group acquisition; no native runner.

Complete effective-weight groups, separate per-fill RAW moments and unique-event
normalization counters are retained. Whole native blocks preserve error/status
identity without reinterpreting marginal errors as covariance. Independent native
execution/review and physical applicability remain separate source obligations.
"""
import bisect,gzip,hashlib,json,math,re,os,stat,io,copy
from contextvars import ContextVar
from decimal import Decimal,localcontext
from fractions import Fraction
from pathlib import Path
from .truth_reco_response import study_contract
class NativeGroupFillError(ValueError):
 def __init__(self,message,reason='invalid_input'):
  super().__init__(message);self.reason=reason
def require(v,m):
 if not v:raise NativeGroupFillError(m)
LIMIT=32*1024*1024
REFERENCE_LIMIT=4*1024*1024
TOTAL_LIMIT=128*1024*1024
_SNAPSHOT=ContextVar('native_group_snapshot',default=None)
def _identity(st):return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
def _ordinary(path):
 require(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)),'ordinary complete unlinked source required')
def _read_bytes(p):
 path=Path(p).absolute();cache=_SNAPSHOT.get()
 if cache is not None and path in cache:return cache[path][0]
 _ordinary(path);before=path.stat(follow_symlinks=False)
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as stream:
  selected=os.fstat(stream.fileno());require(stat.S_ISREG(selected.st_mode) and _identity(before)==_identity(selected) and selected.st_size<=LIMIT,'stable bounded source descriptor required')
  require(cache is None or sum(len(value[0]) for value in cache.values())+selected.st_size<=TOTAL_LIMIT,'bounded complete source snapshot graph required')
  raw=stream.read(LIMIT+1);require(len(raw)<=LIMIT and len(raw)==selected.st_size,'bounded complete source read required')
  _ordinary(path);require(_identity(os.fstat(stream.fileno()))==_identity(selected) and _identity(path.stat(follow_symlinks=False))==_identity(selected),'source changed while reading')
 if cache is not None:cache[path]=(raw,_identity(selected))
 return raw
def _read_text(p):return _read_bytes(p).decode('utf-8')
def _reference_text(p):
 with gzip.GzipFile(fileobj=io.BytesIO(_read_bytes(p))) as stream:
  raw=stream.read(REFERENCE_LIMIT+1)
  require(len(raw)<=REFERENCE_LIMIT,'bounded expanded reference required')
 return raw.decode('utf-8')
def _ending(cache):
 for path,(_,identity) in cache.items():
  _ordinary(path);require(_identity(path.stat(follow_symlinks=False))==identity,'source changed during complete acquisition')
def digest(p):return hashlib.sha256(_read_bytes(p)).hexdigest()
def unique(pairs):
 d={}
 for k,v in pairs:require(k not in d,'duplicate JSON key');d[k]=v
 return d
def decode(text):return json.loads(text,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(NativeGroupFillError('nonfinite JSON')))
def finite(v):require(type(v) in (int,float) and math.isfinite(v),'finite numeric record required');return float(v)
def fill_schema(contract):
 schema=contract.get('fill_schema')
 if not isinstance(schema,dict):raise NativeGroupFillError('supplied fill_schema required','missing_input')
 require(set(schema)=={'schema_version','routine','native_analysis_alias','source','sources','sites','outputs','rules','native_object_paths','study'},'closed supplied fill schema required')
 require(type(schema['schema_version']) is int and schema['schema_version']==1,'fill schema version required')
 require(schema['routine']==contract.get('routine') and schema['native_analysis_alias']==contract.get('native_analysis_alias'),'source namespace differs from supplied schema')
 require(schema['source']['sha256']==contract.get('original_source_sha256'),'original source differs from supplied schema')
 source=_read_text(schema['source']['path']);require(digest(schema['source']['path'])==schema['source']['sha256'],'fill source hash differs')
 require(isinstance(schema['sources'],list),'explicit dependency source census required')
 for pin in schema['sources']:require(digest(pin['path'])==pin['sha256'],'fill dependency source hash differs')
 study_contract(schema['study'])
 sites=schema['sites'];require(isinstance(sites,list) and sites and len(sites)<=256,'complete supplied fill sites required')
 require(all(set(row)=={'id','arity','anchor','count','max_per_event'} and type(row['id']) is int and type(row['arity']) is int and 1<=row['arity']<=2 and isinstance(row['anchor'],str) and row['anchor'] and type(row['count']) is int and row['count']>0 and type(row['max_per_event']) is int and 1<=row['max_per_event']<=65536 for row in sites),'complete fill hook and arity schema required')
 require(len({row['id'] for row in sites})==len(sites),'unique fill site identifiers required')
 for row in sites:require(source.count(row['anchor'])==row['count'],'qualified fill anchor census differs')
 require(contract.get('outputs')==schema['outputs'],'whole supplied booking census required')
 require(isinstance(schema['rules'],list),'explicit fill relationship rules required')
 for rule in schema['rules']:
  require(set(rule)=={'kind','sites'} and rule['kind'] in ('equal_count','implies','ordered') and isinstance(rule['sites'],list) and len(rule['sites'])>=2 and all(type(x) is int and x in {s['id'] for s in sites} for x in rule['sites']),'supported complete fill relationship required')
 require(isinstance(schema['native_object_paths'],list) and len(set(schema['native_object_paths']))==len(schema['native_object_paths']),'explicit complete native object namespace required')
 return schema


def native_inventory(text):
 """Retain whole typed native census/block identity without parsing estimate errors.

 Every exact block remains in the hash-bound YODA file; undefined/status/flow
 tokens are neither omitted nor assigned histogram moment interpretations.
 This is transport completeness, not authenticated native execution provenance.
 """
 rows=[];seen=set();lines=text.splitlines(keepends=True);i=0
 while i<len(lines):
  line=lines[i].rstrip('\r\n')
  if not line or line.startswith('#'):i+=1;continue
  match=re.fullmatch(r'BEGIN YODA_([A-Z][A-Z0-9]*|BINNED(?:ESTIMATE|HISTO|PROFILE)<[DIS](?:,[DIS]){0,2}>)_V([0-9]+) ([^\s]+)',line)
  require(match is not None,'unexpected text outside typed YODA block')
  kind,version,path=match.groups();require(path not in seen,'duplicate whole typed native path');seen.add(path)
  end=f'END YODA_{kind}_V{version}';start=i;i+=1
  while i<len(lines) and lines[i].rstrip('\r\n')!=end:
   require(not lines[i].startswith(('BEGIN ','END ')),'nested or mismatched native block');i+=1
  require(i<len(lines),'unterminated typed native block');i+=1;block=''.join(lines[start:i])
  rows.append({'path':path,'type':kind,'version':int(version),'block_sha256':hashlib.sha256(block.encode()).hexdigest()})
 require(rows,'empty native object census');return rows

def parse_raw(text):
 blocks=re.findall(r'^BEGIN YODA_(HISTO1D|COUNTER)_V3 ([^\n]+)\n(.*?)^END YODA_\1_V3',text,re.M|re.S);out={}
 for kind,path,body in blocks:
  if not path.startswith('/RAW/'):continue
  require(path not in out,'duplicate native RAW object');lines=body.splitlines();head=next((i for i,l in enumerate(lines) if l.startswith('# sumW ')),None);require(head is not None,'native RAW columns')
  labels=lines[head][1:].split();expected=['sumW','sumW2','sumW(A1)','sumW2(A1)','numEntries'] if kind=='HISTO1D' else ['sumW','sumW2','numEntries'];require(labels==expected,'exact complete native RAW moment columns')
  rows=[l.split() for l in lines[head+1:] if l.strip() and not l.startswith('#')];require(all(len(r)==len(expected) for r in rows),'native RAW complete row population')
  edges=json.loads(re.search(r'^Edges\(A1\): (.+)$',body,re.M)[1]) if kind=='HISTO1D' else None
  out[path]={'kind':kind,'edges':edges,'rows':rows}
 return out

def enclosed(token,terms,products):
 # Fixed operation-count binary64 forward error plus literal decimal half digit.
 # Exact Fraction terms retain signs/cancellation; no tolerance fitted to output scale.
 require(terms,'empty primitive term list must be explicitly zero')
 exact=sum((Fraction.from_float(v) for v in terms),Fraction());scale=sum((abs(Fraction.from_float(v)) for v in terms),Fraction());n=len(terms)+products;u=Fraction(1,2**53);require(n*u<1,'bounded arithmetic operation count')
 bound=n*u/(1-n*u)*scale+Fraction(n,2**1074)
 with localcontext() as c:
  c.prec=100;d=Decimal(token);require(d.is_finite(),'finite native RAW token');half=Decimal(5).scaleb(d.as_tuple().exponent-1);actual=Fraction(d);decimal=Fraction(half)
 require(abs(actual-exact)<=bound+decimal,'native RAW primitive outside source arithmetic/serialization enclosure')

def _acquire(trace_path,raw_yoda_path,contract,*,expected_trace_sha256,expected_raw_sha256):
 schema=fill_schema(contract)
 require(digest(trace_path)==expected_trace_sha256 and digest(raw_yoda_path)==expected_raw_sha256,'actual trace/RAW hashes required')
 require(contract['schema_version']==2 and contract['group_rule']=='independent_single_subevent','correlated subevent collapse is unqualified')
 require(type(contract.get('native_weight_cap')) is int and contract['native_weight_cap']==0,'weight capping must be explicitly disabled and separately source/custody bound')
 routine=contract['routine'];alias=contract['native_analysis_alias'];source_sha=contract['original_source_sha256'];sites={row['id']:row for row in schema['sites']}
 events=contract['events'];names=contract['weight_mapping'];require(isinstance(events,list) and 0<len(events)<=65536 and names and len(names)<=64,'bounded complete input event/weight census')
 require(all(isinstance(p['id'],str) and p['id'] and isinstance(p['native'],str) and isinstance(p['raw_suffix'],str) for p in names),'explicit selected native label/RAW suffix mapping required')
 require(len({p['id'] for p in names})==len(names) and len({p['native'] for p in names})==len(names) and len({p['raw_suffix'] for p in names})==len(names),'exact unique named selected weight mapping')
 selection=contract.get('nominal_weight_selection')
 if 'nominal_weight_selection' in contract:
  from .event_census import nominal_selection, nominal_version
  require(type(selection) is dict,'explicit nominal selection record required')
  require(selection==nominal_selection(selection.get('original_weight_names'),selection.get('nominal_weight'),rivet_version=nominal_version(selection)),'complete source-defined original nominal selection differs')
  require([w['native'] for w in names]==selection['native_weight_names'] and [w['raw_suffix'] for w in names]==selection['native_raw_suffixes'],'selected native names/suffixes must preserve every original stream and order')
 outputs=contract['outputs'];require(outputs and len({o['id'] for o in outputs})==len(outputs),'complete unique output census');require({o['site'] for o in outputs}==set(sites),'complete source fill-site census')
 ref=contract['reference'];require(digest(ref['path'])==ref['sha256'],'source reference hash')
 reference=_reference_text(ref['path']);geometry={path.replace('/REF',''):json.loads(re.search(r'^Edges\(A1\): (.+)$',body,re.M)[1]) for path,body in re.findall(r'^BEGIN YODA_ESTIMATE1D_V3 (/REF/[^\n]+)\n(.*?)^END YODA_ESTIMATE1D_V3',reference,re.M|re.S)}
 for o in outputs:
  require(o['reference_path'] in geometry and o['edges']==geometry[o['reference_path']],'source booking/reference geometry differs')
  require(isinstance(o['axis_unit'],str) and o['axis_unit'] and o['unit']=='1','explicit RAW coordinate units required')
  if sites[o['site']]['arity']==2:require(finite(o['group_low'])<finite(o['group_high']),'ordered supplied group interval required')
 for o in outputs:
  e=o['edges'];require(len(e)>=2 and all(finite(a)<finite(b) for a,b in zip(e,e[1:])),'ordered explicit reference geometry')
  require(o['unit'] and o['axis_unit'] and o['source_fill_weight']==o['source_fill_fraction']==1,'source default fill/fraction identities')
 require(all(type(e['event_number']) is int for e in events) and all(a['event_number']!=b['event_number'] for a,b in zip(events,events[1:])), 'consecutive repeated event numbers imply unqualified native correlated collapse')
 trace=[decode(l) for l in _read_text(trace_path).splitlines()];require(len(trace)==len(events),'missing or extra observed native events')
 raw=parse_raw(_read_text(raw_yoda_path));expected_raw={ '/RAW'+o['path']+w['raw_suffix'] for w in names for o in outputs }|{'/RAW/_EVTCOUNT'+w['raw_suffix'] for w in names}
 require(set(raw)==expected_raw,'complete RAW histogram/counter census, no extra objects')
 inventory=native_inventory(_read_text(raw_yoda_path))
 require(contract.get('native_object_inventory')==inventory,'complete exact typed native object inventory required')
 require({row['path'] for row in inventory}==set(schema['native_object_paths']),'whole supplied native object census differs')
 basis=[{'weight':w['id'],'output':o['id'],'native_path':o['path'],'bin':'underflow' if i==0 else ('overflow' if i==len(o['edges']) else str(i-1)),'unit':o['unit'],'axis_unit':o['axis_unit'],'low':None if i==0 else o['edges'][i-1],'high':None if i==len(o['edges']) else o['edges'][i]} for w in names for o in outputs for i in range(len(o['edges'])+1)]
 require(len({(b['weight'],b['output'],b['bin']) for b in basis})==len(basis),'unique complete output basis')
 require(len(basis)<=4096 and len(events)*len(basis)<=8_000_000 and len(events)*len(names)*len(sites)<=2_000_000,'bounded complete group/vector/moment population required; no groups omitted')
 positions={(b['weight'],b['output'],b['bin']):i for i,b in enumerate(basis)};terms={i:[[],[],[],[],[]] for i in range(len(basis))};groups=[];seen=set();pids=set()
 for ordinal,(r,e) in enumerate(zip(trace,events)):
  require(set(r)=={'schema','routine','original_source_sha256','ordinal','event_number','pid','unwinding','native_weight_names','weights','fills'} and r['schema']=='ravel-native-fills/v1','closed native trace protocol')
  require(r['routine']==routine and r['original_source_sha256']==contract['original_source_sha256'] and type(r['ordinal']) is int and r['ordinal']==ordinal and type(r['event_number']) is int and r['event_number']==e['event_number'],'exact encounter/source/native event identities')
  require(type(r['pid']) is int and r['pid']==contract['same_process_pid'] and type(r['unwinding']) is bool,'same source-qualified loader process')
  require(r['native_weight_names']==[w['native'] for w in names] and len(r['weights'])==len(names) and r['weights']==e['selected_weights'],'effective native selected weight vector differs')
  ident=(e['input_sha256'],e['encounter_ordinal']);require(re.fullmatch('[0-9a-f]{64}',e['input_sha256']) and type(e['encounter_ordinal']) is int and e['encounter_ordinal']>=0 and ident not in seen,'event group requires source file identity and unique encounter ordinal');seen.add(ident);pids.add(r['pid']);v=[0.]*len(basis)
  require(isinstance(r['fills'],list) and len(r['fills'])<=65536,'bounded native fill population')
  counts={site:sum(f.get('site')==site for f in r['fills']) for site in sites}
  require(all(counts[site]<=row['max_per_event'] for site,row in sites.items()),'supplied per-site fill multiplicity differs')
  for rule in schema['rules']:
   cs=[counts[site] for site in rule['sites']]
   if rule['kind']=='equal_count':require(len(set(cs))==1,'supplied equal-count fill relationship differs')
   elif rule['kind']=='implies':require(not cs[0] or all(cs[1:]),'supplied fill implication differs')
   else:
    ranks={site:i for i,site in enumerate(rule['sites'])};sequence=[ranks[f['site']] for f in r['fills'] if f['site'] in ranks]
    require(sequence==sorted(sequence),'supplied fill encounter order differs')
  for f in r['fills']:
   require(set(f)=={'site','coordinates'} and type(f['site']) is int and f['site'] in sites,'unknown native fill-site identity');coords=[finite(x) for x in f['coordinates']];require(len(coords)==sites[f['site']]['arity'],'source fill coordinate arity')
   choices=[o for o in outputs if o['site']==f['site']]
   if len(coords)==2:choices=[o for o in choices if o['group_low']<=coords[0]<o['group_high']]
   require(len(choices)==1,'native group coordinate outside complete declared histogram groups');o=choices[0];x=coords[-1];bi=bisect.bisect_right(o['edges'],x);binid='underflow' if bi==0 else ('overflow' if bi==len(o['edges']) else str(bi-1))
   for k,wmap in enumerate(names):
    w=finite(r['weights'][k]);i=positions[(wmap['id'],o['id'],binid)];v[i]+=w
    for dest,value in zip(terms[i],[w,w*w,w*x,w*(x*x),1.]):dest.append(finite(value))
  groups.append({'id':e['input_sha256']+':'+str(e['encounter_ordinal']),'values':v})
 # Compare every observed RAW finite/flow primitive separately from group outer products.
 checked=0
 for w in names:
  suffix=w['raw_suffix']
  for o in outputs:
   path='/RAW'+o['path']+suffix;require(path in raw and raw[path]['kind']=='HISTO1D' and raw[path]['edges']==o['edges'],'complete exact RAW histogram/geometry')
   rows=raw[path]['rows'];require(len(rows)==len(o['edges'])+1,'complete RAW finite/flow row census')
   for bi,tokens in enumerate(rows):
    binid='underflow' if bi==0 else ('overflow' if bi==len(o['edges']) else str(bi-1));i=positions[(w['id'],o['id'],binid)]
    for k,token in enumerate(tokens):enclosed(token,terms[i][k] or [0.],len(terms[i][k])*(2 if k==3 else (1 if k in (1,2) else 0)));checked+=1
  counter=raw.get('/RAW/_EVTCOUNT'+suffix);require(counter and counter['kind']=='COUNTER' and len(counter['rows'])==1,'exact full-event normalization counter')
  weights=[finite(e['selected_weights'][names.index(w)]) for e in events]
  for token,ts,operations in zip(counter['rows'][0],[weights,[x*x for x in weights],[1.]*len(events)],[0,len(events),0]):enclosed(token,ts,operations);checked+=1
 values=[math.fsum(g['values'][i] for g in groups) for i in range(len(basis))]
 return {'schema_version':2,'native_analysis_alias':alias,'logical_source_routine':routine,'uninstrumented_source_sha256':source_sha,'native_semantics_qualified':False,'basis':basis,'values':values,'uncertainty':{'kind':'independent_groups','groups':groups,'semantics':'uncentered_poissonized_second_moment'},'normalization_counter_by_weight':{w['id']:{'sumw':math.fsum(e['selected_weights'][k] for e in events),'sumw2':math.fsum(e['selected_weights'][k]**2 for e in events),'entries':len(events),'raw_tokens':raw['/RAW/_EVTCOUNT'+w['raw_suffix']]['rows'][0]} for k,w in enumerate(names)},'normalization_event_weights':[{'id':g['id'],'weights':dict(zip([w['id'] for w in names],e['selected_weights']))} for g,e in zip(groups,events)],'normalization_scope':'Separate unique-event counter, with group-aligned weights retained. Fixed-exposure derived contracts are conditional; no inferred normalization covariance/derivative.','raw_primitive_cells_checked':checked,'source_file_encounter_groups':len(groups),'native_trace_sha256':expected_trace_sha256,'raw_yoda_sha256':expected_raw_sha256,'native_weight_cap':0,'same_process_pid':list(pids)[0],'group_rule':'independent_single_subevent','native_marginal_covariance_inferred':False,'experimental_independence':None,'physics_validated':False,'requires_separate_execution_custody_review':True,'limits':['No correlated-subevent/native collapse qualification.','Source fill defaults1/fraction1 and exact selected weight mapping only.','Dense group covariance is a conditional Poissonized moment, no sparse Gaussian/inference calibration.','Full output/weight/bin basis retained; source finalization/exposure/denominator transforms require separate derive contract.']}


def _acquire_complete(trace_path,raw_yoda_path,contract,*,expected_trace_sha256,expected_raw_sha256):
 acquired=_acquire(trace_path,raw_yoda_path,contract,expected_trace_sha256=expected_trace_sha256,expected_raw_sha256=expected_raw_sha256)
 return {'schema_version':1,'kind':'native-group-acquisition','acquired':acquired,'study':contract['fill_schema']['study'],
         **({'nominal_weight_selection':contract['nominal_weight_selection']} if 'nominal_weight_selection' in contract else {}),
         'native_output_namespace':contract['native_analysis_alias'],
         'native_object_inventory':native_inventory(_read_text(raw_yoda_path)),
         'native_values_errors_status_reinterpreted':False,'native_census_source_qualified':False,
         'actual_native_execution_authenticated':False,'physics_validated':False}


def acquire(trace_path,raw_yoda_path,contract,*,expected_trace_sha256,expected_raw_sha256):
 """Acquire using one immutable bounded snapshot of every consumed source."""
 cache={};token=_SNAPSHOT.set(cache)
 try:
  result=_acquire_complete(trace_path,raw_yoda_path,contract,expected_trace_sha256=expected_trace_sha256,expected_raw_sha256=expected_raw_sha256)
  _ending(cache);return result
 finally:_SNAPSHOT.reset(token)


def validate(spec):
 require(type(spec) is dict and set(spec)=={'schema_version','input','request_sha256'} and type(spec['schema_version']) is int and spec['schema_version']==1,'closed native-group-acquisition task/v1 required')
 require(type(spec['input']) is str and spec['input'] and type(spec['request_sha256']) is str and re.fullmatch('[0-9a-f]{64}',spec['request_sha256']),'exact request path and SHA required')
 return dict(spec)


def _load(spec,base):
 from ravel.workflow.science import regular
 spec=validate(spec);path=regular(spec['input'],base);cache={};token=_SNAPSHOT.set(cache)
 try:
  raw=_read_bytes(path);require(hashlib.sha256(raw).hexdigest()==spec['request_sha256'],'request source digest differs');doc=decode(raw)
  require(type(doc) is dict and set(doc)=={'schema_version','operation','contract','trace','raw_yoda','source_evidence','event_inputs','execution_evidence'} and type(doc['schema_version']) is int and doc['schema_version']==1 and doc['operation']=='acquire-groups','closed native group acquisition request/v1 required')
  pins={};resolved=copy.deepcopy(doc)
  def pin(value,parent):
   require(type(value) is dict and {'path','sha256'}<=set(value) and type(value['path']) is str and value['path'] and type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}',value['sha256']),'complete source file pin required')
   file=regular(value['path'],parent);data=_read_bytes(file);sha=hashlib.sha256(data).hexdigest();require(sha==value['sha256'],'nested source digest differs')
   require(file!=path and (file not in pins or pins[file]==sha),'conflicting/recursive source identity')
   if 'size' in value:require(type(value['size']) is int and value['size']==len(data),'declared complete source size differs')
   pins[file]=sha;value['path']=str(file);return file,data
  for key in ('contract','trace','raw_yoda','source_evidence'):pin(resolved[key],path.parent)
  for key in ('event_inputs','execution_evidence'):
   require(type(resolved[key]) is list and len(resolved[key])<=256,'bounded explicit source graph required')
   for value in resolved[key]:pin(value,path.parent)
  contract=decode(_read_bytes(resolved['contract']['path']))
  def walk(value):
   if isinstance(value,dict):
    if 'path' in value and 'sha256' in value:pin(value,Path(resolved['contract']['path']).parent)
    for v in value.values():walk(v)
   elif isinstance(value,list):
    for v in value:walk(v)
  walk(contract)
  require(resolved['source_evidence']['sha256']==contract.get('original_source_sha256'),'exact original source evidence required')
  require({e['input_sha256'] for e in contract['events']}=={p['sha256'] for p in resolved['event_inputs']},'all original encounter-file inputs required')
  require(len(pins)<=256,'bounded full acquisition input graph required')
  result=_acquire_complete(resolved['trace']['path'],resolved['raw_yoda']['path'],contract,expected_trace_sha256=resolved['trace']['sha256'],expected_raw_sha256=resolved['raw_yoda']['sha256'])
  _ending(cache)
  return path,doc,resolved,contract,list(pins),result
 finally:_SNAPSHOT.reset(token)


def inputs(spec,base):
 path,doc,resolved,contract,pins,result=_load(spec,base)
 return [path,*pins]


def run(spec,base,out):
 from ravel.workflow.state_io import atomic_json
 path,doc,resolved,contract,pins,result=_load(spec,base)
 out=Path(out)
 require(not out.exists() and not out.is_symlink() and not any(p.is_symlink() for p in out.parents),'fresh unlinked acquisition output required')
 result=dict(result,status='passed',status_scope='Source-bound event group/RAW reconciliation and complete native block transport only',input={'path':str(path),'sha256':spec['request_sha256']},source_graph=resolved)
 out.mkdir(parents=True,exist_ok=False)
 atomic_json(out/'native-group-acquisition.json',result)
 atomic_json(out/'acquired.json',result['acquired'])
 return result


def write_report(result,out):
 from ravel.workflow.state_io import atomic_json
 require(result.get('kind')=='native-group-acquisition' and result.get('physics_validated') is False,'source-bound acquisition report required')
 out=Path(out);report=study_contract(result['study'])['output'];stem=report['stem'];files=[]
 if 'json' in report['formats']:atomic_json(out/(stem+'.json'),result);files.append(stem+'.json')
 a=result['acquired']
 if 'markdown' in report['formats']:
  (out/(stem+'.md')).write_text('# Native event-group acquisition\n\n'+str(a['source_file_encounter_groups'])+' complete encounter groups; '+str(len(a['basis']))+' weight/output/finite/flow coordinates; '+str(a['raw_primitive_cells_checked'])+' RAW primitive checks.\n\nWhole native error/status blocks remain bound to the original file. Per-fill squared weights and shared-event outer products are different estimators; no physics qualification is granted.\n');files.append(stem+'.md')
 return [{'stem':stem,'files':files,'normalization':'RAW integral event-weight groups and separate once-per-event normalization counters; source finalization retained unchanged'}]
