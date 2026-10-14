"""Literal primary-table intake and exact declared basis/covariance join.

No likelihood/error-law construction. Numeric YAML tokens and complete error/
qualifier/geometry payloads are retained. Symmetry is checked, never repaired.
"""
import hashlib,json,math,os,stat,re
from decimal import Decimal,InvalidOperation
from pathlib import Path
LIMIT=4*1024*1024

def _yaml_module():
 try:
  import yaml
 except ModuleNotFoundError as exc:
  if exc.name!='yaml':raise
  raise ValueError('source-table parsing requires the ravel-hep[source-tables] extra') from exc
 return yaml

def bounded_read(path, limit=LIMIT):
    if not path.is_file() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('ordinary bounded supplied resource required')
    def identity(st):return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
    before=path.stat(follow_symlinks=False)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        selected=os.fstat(stream.fileno())
        if not stat.S_ISREG(selected.st_mode) or identity(before)!=identity(selected) or selected.st_size>limit:
            raise ValueError('stable bounded regular descriptor required')
        raw=stream.read(limit+1)
        if len(raw)>limit or len(raw)!=selected.st_size or not path.is_file() or any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('bounded complete ending nonlinked source required')
        if identity(os.fstat(stream.fileno()))!=identity(selected) or identity(path.stat(follow_symlinks=False))!=identity(selected):
            raise ValueError('resource changed during read')
    return raw



def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def number(value):
 if not isinstance(value,dict) or set(value)!={'literal','decimal'}:raise ValueError('literal YAML numeric scalar required')
 try:d=Decimal(value['literal'])
 except (InvalidOperation,ValueError):raise ValueError('closed decimal token required')
 if not d.is_finite() or str(d)!=value['decimal']:raise ValueError('finite consistent decimal required')
 return d

def _node(node,seen,budget,depth=0):
 yaml=_yaml_module()
 budget[0]+=1
 if depth>24 or budget[0]>100000 or id(node) in seen:raise ValueError('bounded alias-free YAML required')
 seen.add(id(node))
 if isinstance(node,yaml.ScalarNode):
  tag=node.tag.rsplit(':',1)[-1]
  if tag in ('float','int'):
   if tag=='int' and re.fullmatch(r'[+-]?(?:0|[1-9][0-9]*)',node.value) is None:raise ValueError('unambiguous decimal integer lexical grammar required')
   if tag=='float' and re.fullmatch(r'[+-]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[0-9]+[eE][+-]?[0-9]+)',node.value) is None:raise ValueError('explicit finite decimal float lexical grammar required')
   try:d=Decimal(node.value)
   except InvalidOperation:raise ValueError('closed decimal scalar grammar')
   if not d.is_finite():raise ValueError('finite primary numeric token required')
   return {'literal':node.value,'decimal':str(d)}
  if tag=='str':return node.value
  if tag=='null':return None
  if tag=='bool':
   literal=node.value.lower()
   if literal not in ('true','false','yes','no','on','off'):raise ValueError('closed YAML1.1 boolean scalar required')
   return literal in ('true','yes','on')
  raise ValueError('unserved YAML scalar type')
 if isinstance(node,yaml.SequenceNode):return [_node(x,seen,budget,depth+1) for x in node.value]
 if isinstance(node,yaml.MappingNode):
  result={}
  for key,value in node.value:
   if not isinstance(key,yaml.ScalarNode) or key.tag!='tag:yaml.org,2002:str' or key.value in result:raise ValueError('unique literal string mapping keys required')
   result[key.value]=_node(value,seen,budget,depth+1)
  return result
 raise ValueError('closed YAML nodes required')

def read_table(pin):
 raw=bounded_read(Path(pin['path']),limit=LIMIT)
 if hashlib.sha256(raw).hexdigest()!=pin['sha256']:raise ValueError('primary table source digest mismatch')
 return read_table_snapshot(raw,pin)

def read_table_snapshot(raw,pin):
 # Parsing and copied evidence share the exact bounded authenticated snapshot.
 if type(raw) is not bytes or not 0<len(raw)<=LIMIT or hashlib.sha256(raw).hexdigest()!=pin['sha256']:
  raise ValueError('bounded exact primary table snapshot required')
 yaml=_yaml_module()
 node=yaml.compose(raw.decode(),Loader=yaml.SafeLoader)
 if node is None:raise ValueError('complete primary table required')
 table=_node(node,set(),[0])
 if set(table)!={'independent_variables','dependent_variables'}:raise ValueError('closed primary table sections required')
 axes,columns=table['independent_variables'],table['dependent_variables']
 if not isinstance(axes,list) or not 1<=len(axes)<=4 or not isinstance(columns,list) or not 1<=len(columns)<=32:raise ValueError('bounded complete table census')
 lengths=[]
 for variable in axes+columns:
  if not isinstance(variable,dict) or not {'header','values'}<=set(variable) or not isinstance(variable['header'],dict) or not isinstance(variable['values'],list):raise ValueError('complete typed variable census')
  if set(variable)-{'header','values','qualifiers'}:raise ValueError('unserved variable fields')
  lengths.append(len(variable['values']))
 if not lengths or not 0<lengths[0]<=65536 or len(set(lengths))!=1:raise ValueError('exact full row census required')
 return {'source':dict(pin),'payload':table,'rows':lengths[0],'literal_tokens_retained':True,'source_format':'HEPData_yaml_grammar','source_origin_authenticated':False,'error_law_inferred':False}

def select(table,selection):
 if set(selection)!={'header','qualifiers'}:raise ValueError('literal complete dependent selection required')
 matches=[v for v in table['payload']['dependent_variables'] if v['header']==selection['header'] and v.get('qualifiers',[])==selection['qualifiers']]
 if len(matches)!=1:raise ValueError('unique exact header+qualifier column required')
 return matches[0]

def join(contract,*,expected_contract_sha256):
 if digest(contract)!=expected_contract_sha256:raise ValueError('reviewed source/basis contract digest required')
 if set(contract)!={'kind','distributions','basis_link','matrices'} or contract['kind']!='primary-table-basis-join/v2':raise ValueError('closed basis join contract required')
 distributions=contract['distributions'];bases=[];out=[];loaded={}
 if not isinstance(distributions,list) or not 1<=len(distributions)<=16:raise ValueError('bounded ordered distribution list required')
 for row in distributions:
  if set(row)!={'id','source','expected_axes','expected_row_count','selections','bin_ids'}:raise ValueError('closed distribution declaration required')
  table=read_table(row['source']);loaded[digest(row['source'])]=table
  axes=table['payload']['independent_variables'];geometry=[dict(a) for a in axes]
  if geometry!=row['expected_axes'] or type(row['expected_row_count']) is not int or table['rows']!=row['expected_row_count']:raise ValueError('literal geometry/header/full row census mismatch')
  ids=row['bin_ids']
  if not isinstance(ids,list) or len(ids)!=table['rows'] or any(type(i) is not str or not i for i in ids):raise ValueError('complete declared source bin identities')
  bases.extend(ids)
  if not row['selections']:raise ValueError('explicit requested dependent census required')
  selected=[]
  for selection in row['selections']:
   column=select(table,selection);selected.append(column)
  if len({digest(s) for s in row['selections']})!=len(row['selections']):raise ValueError('unique dependent selections required')
  out.append({'id':row['id'],'source':row['source'],'axes':geometry,'bin_ids':ids,'selected_columns':selected,'all_source_column_headers':[{'header':c['header'],'qualifiers':c.get('qualifiers',[])} for c in table['payload']['dependent_variables']]})
 if len(set(bases))!=len(bases) or len(bases)>256:raise ValueError('bounded unique full joint basis required')
 link=contract['basis_link']
 if set(link)!={'matrix_labels','ordered_bin_ids','source_evidence'} or not isinstance(link['ordered_bin_ids'],list) or not set(bases)<=set(link['ordered_bin_ids']) or len(set(link['ordered_bin_ids']))!=len(link['ordered_bin_ids']) or len(link['ordered_bin_ids'])>256 or len(link['matrix_labels'])!=len(link['ordered_bin_ids']) or len(set(link['matrix_labels']))!=len(link['matrix_labels']):raise ValueError('explicit complete matrix-label to distribution-basis link required')
 evidence=link['source_evidence'];raw=bounded_read(Path(evidence['path']),limit=LIMIT)
 if hashlib.sha256(raw).hexdigest()!=evidence['sha256'] or not evidence.get('interpretation'):raise ValueError('source-backed declared basis ordering evidence required')
 matrices=[]
 if not isinstance(contract['matrices'],list) or not 1<=len(contract['matrices'])<=16:raise ValueError('complete supplied matrix components required')
 for m in contract['matrices']:
  if set(m)!={'id','source','selection','axis_headers','axis_qualifiers','kind','declared_output_unit'} or m['kind'] not in ('covariance','correlation'):raise ValueError('closed original matrix semantics required')
  source_key=digest(m['source'])
  if source_key not in loaded:loaded[source_key]=read_table(m['source'])
  table=loaded[source_key];axes=table['payload']['independent_variables'];col=select(table,m['selection']);n=len(link['ordered_bin_ids'])
  if len(axes)!=2 or [a['header'] for a in axes]!=m['axis_headers'] or [a.get('qualifiers',[]) for a in axes]!=m['axis_qualifiers'] or table['rows']!=n*n:raise ValueError('complete declared matrix geometry/census required')
  cells={};labels=link['matrix_labels'];lookup={v:i for i,v in enumerate(labels)}
  for r in range(table['rows']):
   coordinates=[]
   for axis in axes:
    item=axis['values'][r]
    if set(item)!={'value'}:raise ValueError('literal matrix coordinate required')
    value=item['value'];key=str(number(value)) if isinstance(value,dict) else value
    if key not in lookup:raise ValueError('matrix coordinate outside declared source labels')
    coordinates.append(lookup[key])
   key=tuple(coordinates)
   if key in cells:raise ValueError('duplicate source matrix cell')
   value=col['values'][r]
   if set(value)!={'value'}:raise ValueError('matrix cells cannot be synthesized from errors')
   cells[key]=value['value'];number(value['value'])
  matrix=[[cells[i,j] for j in range(n)] for i in range(n)]
  if any(number(matrix[i][j])!=number(matrix[j][i]) for i in range(n) for j in range(n)):raise ValueError('source matrix is asymmetric; repair refused')
  if m['kind']=='correlation' and any(abs(number(v))>1 for row in matrix for v in row):raise ValueError('correlation domain violation')
  if type(m['declared_output_unit']) is not str or not m['declared_output_unit']:raise ValueError('explicit matrix output unit required')
  original_unit=col['header'].get('units','')
  if original_unit and original_unit!=m['declared_output_unit']:raise ValueError('source matrix unit mismatch; implicit conversion refused')
  selected_indices=[link['ordered_bin_ids'].index(v) for v in bases]
  matrices.append({'id':m['id'],'source':m['source'],'header':col['header'],'qualifiers':col.get('qualifiers',[]),'kind':m['kind'],'declared_output_unit':m['declared_output_unit'],'declared_output_unit_admitted':bool(original_unit),'unit_semantics':'exact_source_unit' if original_unit else 'unadmitted_caller_annotation_source_unit_empty','source_axes':axes,'full_source_bin_ids':link['ordered_bin_ids'],'literal_full_source_matrix':matrix,'bin_ids':bases,'source_indices':selected_indices,'literal_matrix':[[matrix[i][j] for j in selected_indices] for i in selected_indices],'symmetry':'exact_decimal_source','source_matrix_modified':False,'PSD_or_sampling_law_admitted':False})
 if len({m['id'] for m in matrices})!=len(matrices) or len({d['id'] for d in out})!=len(out):raise ValueError('unique output identities required')
 return {'kind':'source-primary-table-basis-join','contract_sha256':expected_contract_sha256,'distributions':out,'bin_ids':bases,'matrix_components':matrices,'basis_source_evidence':evidence,'joint_matrix_sum_constructed':False,'covariance_from_marginal_errors':False,'source_interpretation':'Literal primary bytes and caller-declared exact ordering; physical applicability, original error law, PSD and inference require separate admission.','native_calls':0,'fits':0}


def validate(spec):
    if type(spec) is not dict or set(spec)!={'schema_version','input','contract_sha256'} or type(spec['schema_version']) is not int or spec['schema_version']!=1:
        raise ValueError('closed source-table task/v1 required')
    if type(spec['input']) is not str or not spec['input'] or type(spec['contract_sha256']) is not str or len(spec['contract_sha256'])!=64 or any(c not in '0123456789abcdef' for c in spec['contract_sha256']):
        raise ValueError('literal contract path and file SHA256 required')
    return dict(spec)


def _contract(spec,base):
    from ravel.workflow.science import regular
    spec=validate(spec);path=regular(spec['input'],base);raw=bounded_read(path)
    if hashlib.sha256(raw).hexdigest()!=spec['contract_sha256']:raise ValueError('contract file digest mismatch')
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out:raise ValueError('duplicate contract key')
            out[k]=v
        return out
    doc=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite contract')))
    # Preserve the supplied relative path declaration and complete source graph;
    # materialization changes paths only after its exact file digest is verified.
    import copy
    resolved=copy.deepcopy(doc);pins={}
    def walk(value):
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value:
                p=regular(value['path'],path.parent);data=bounded_read(p)
                if hashlib.sha256(data).hexdigest()!=value['sha256']:raise ValueError('nested source digest mismatch')
                if p in pins and pins[p]!=value['sha256']:raise ValueError('conflicting nested source identity')
                pins[p]=value['sha256'];value['path']=str(p)
            for v in value.values():walk(v)
        elif isinstance(value,list):
            for v in value:walk(v)
    walk(resolved)
    if path in pins or len(pins)>128:raise ValueError('bounded distinct complete source graph required')
    return path,doc,resolved,list(pins)


def inputs(spec,base):
    path,doc,resolved,pins=_contract(spec,base)
    # Admit original source/basis/table semantics as well as every nested pin.
    join(resolved,expected_contract_sha256=digest(resolved))
    return [path,*pins]


def run(spec,base,out):
    from ravel.workflow.state_io import atomic_json
    path,doc,resolved,pins=_contract(spec,base)
    result=join(resolved,expected_contract_sha256=digest(resolved))
    result.update(status='passed',physics_validated=False,statistical_inference=None,
        status_scope='Literal source-table and explicitly declared basis/matrix delivery only',
        input={'path':str(path),'sha256':spec['contract_sha256']},
        original_declared_contract_sha256=digest(doc),resolved_contract_sha256=digest(resolved))
    out=Path(out)
    if out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents):raise ValueError('fresh unlinked source-table output directory required')
    out.mkdir(parents=True,exist_ok=False);atomic_json(out/'source-tables.json',result)
    return result


def write_report(result,out):
    """Literal source table report, avoiding histogram/variance reinterpretation."""
    from ravel.workflow.state_io import atomic_json
    if result.get('kind')!='source-primary-table-basis-join' or result.get('physics_validated') is not False:
        raise ValueError('literal source table delivery required')
    out=Path(out);rows=[]
    def escape(value):return str(value).replace('|','\\|').replace('\n',' ')
    for d in result['distributions']:
        for col in d['selected_columns']:
            if len(col['values'])!=len(d['bin_ids']):raise ValueError('report complete source row census required')
            for identity,value in zip(d['bin_ids'],col['values']):
                central=value.get('value');literal=central['literal'] if isinstance(central,dict) and set(central)=={'literal','decimal'} else central
                rows.append('| '+' | '.join(escape(v) for v in (d['id'],identity,col['header'].get('name'),col['header'].get('units',''),literal,json.dumps(value.get('errors',[]),sort_keys=True)))+' |')
    atomic_json(out/'source-table-report.json',result)
    (out/'source-table-report.md').write_text('# Literal primary source tables\n\n| Table | Bin | Dependent variable | Original unit | Value token | Original error payload |\n|---|---|---|---|---|---|\n'+'\n'.join(rows)+'\n\nAll original axes and qualifiers, complete supplied matrices and explicit selected basis are in source-table-report.json. Blank original matrix units retain unadmitted caller annotations; no unit conversion, error law, matrix sum, covariance repair or inference is implied.\n')
    return [{'stem':'source-table-report','files':['source-table-report.json','source-table-report.md'],'normalization':'Literal source values/errors/axes/matrix coefficients without scaling or statistical interpretation'}]
