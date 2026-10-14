"""Deliver numerical tool values as strict artifacts without model rewriting.

The model supplies interpretation text. A prospective field contract maps every
numerical/boolean output to pinned scientific tool results. Exact fraction text
is retained alongside any JSON binary64 conversion. This composes evidence; it
does not authenticate a tool's truth, invent absent status semantics or approve
scientific execution. New hypotheses and interpretations remain model work.
"""
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from fractions import Fraction
import hashlib,json,math,os,re,stat
from pathlib import Path
from . import candidate_experiments as ce

MAX_FIELDS=64
RESERVED={'scientific_acceptance','execution_authorized','physics_validated'}


def _text(value,maximum=4096):
    if type(value) is not str or not value.strip() or len(value.encode())>maximum:raise ValueError('bounded explicit scientific artifact text required')


def _basis_snapshot(pin,base):
    """Return literal source text decoded from the exact authenticated read.

    The immutable text, rather than a subsequent path read, is the parser's
    input. Path and descriptor observations also refuse replacement during
    acquisition; the pin hashes the bytes actually returned to the caller.
    """
    ce.keys(pin,['path','sha256','size']);ce.sha(pin['sha256'])
    if type(pin['size']) is not int or not 1<=pin['size']<=ce.MAX_BYTES:raise ValueError('bounded source basis required')
    if type(pin['path']) is not str or not pin['path']:raise ValueError('relative source basis required')
    relative=Path(pin['path'])
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('relative source basis required')
    path=base
    for component in relative.parts:
        path=path/component
        if path.is_symlink():raise ValueError('symlink basis refused')
    if not path.is_file() or not path.resolve().is_relative_to(base):raise ValueError('regular source basis required')
    def identity(info):
        return (info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    before=path.stat()
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or identity(before)!=identity(opened):
            raise ValueError('source basis descriptor differs')
        raw=stream.read(ce.MAX_BYTES+1)
        closed=os.fstat(stream.fileno())
        after=path.stat()
        if path.is_symlink() or identity(opened)!=identity(closed) or identity(closed)!=identity(after):
            raise ValueError('source basis changed during read')
    if len(raw)!=pin['size'] or hashlib.sha256(raw).hexdigest()!=pin['sha256']:raise ValueError('source basis bytes differ')
    return path.resolve(strict=True),raw.decode('utf-8')


def _basis(pin,base):
    """Validate a literal basis without changing the existing Path API."""
    return _basis_snapshot(pin,base)[0]


def _pointer(document,pointer):
    if type(pointer) is not str or len(pointer)>1024 or not pointer.startswith('/'):raise ValueError('explicit non-root JSON pointer required')
    current=document
    for token in pointer[1:].split('/'):
        for index,char in enumerate(token):
            if char=='~' and (index+1>=len(token) or token[index+1] not in '01'):raise ValueError('valid JSON pointer escape required')
        key=token.replace('~1','/').replace('~0','~')
        if type(current) is dict:
            if key not in current:raise ValueError('tool result lacks requested field')
            current=current[key]
        elif type(current) is list:
            if not re.fullmatch(r'0|[1-9][0-9]*',key) or int(key)>=len(current):raise ValueError('literal in-range array index required')
            current=current[int(key)]
        else:raise ValueError('tool field path crosses scalar')
    return current


def _fraction(value):
    if type(value) is int:return Fraction(value)
    if type(value) is not str or not 1<=len(value)<=128:raise ValueError('bounded exact numeric token required')
    try:
        if '/' in value:
            parts=value.split('/')
            if len(parts)!=2 or any(not p.lstrip('+-').isdigit() for p in parts):raise ValueError('rational token required')
            return Fraction(int(parts[0]),int(parts[1]))
        decimal=Decimal(value)
        if not decimal.is_finite() or abs(decimal.as_tuple().exponent)>1024:raise ValueError('finite bounded decimal exponent required')
        return Fraction(decimal)
    except (ValueError,ZeroDivisionError,InvalidOperation):raise ValueError('finite exact numeric source required') from None


def _convert(value,kind):
    if type(kind) is dict:
        if kind['type']=='nullable':
            if value is None:return None,{'conversion':'source_defined_JSON_null'}
            return _convert(value,kind['item'])
        if kind['type']=='array':
            if type(value) is not list or len(value)>kind['max_items']:raise ValueError('complete bounded source array required')
            pairs=[_convert(item,kind['items']) for item in value]
            return [x[0] for x in pairs],{'conversion':'typed_source_array','items':[x[1] for x in pairs]}
        if type(value) is not dict or set(value)!=set(kind['properties']):raise ValueError('exact complete typed source object required')
        pairs={key:_convert(value[key],schema) for key,schema in kind['properties'].items()}
        return {k:x[0] for k,x in pairs.items()},{'conversion':'typed_source_object','properties':{k:x[1] for k,x in pairs.items()}}
    if kind=='string':
        _text(value,8192);return value,{'conversion':'unchanged_string'}
    if kind=='boolean':
        if type(value) is not bool:raise ValueError('literal source boolean required')
        return value,{'conversion':'unchanged_boolean'}
    if kind=='integer':
        fraction=_fraction(value)
        if fraction.denominator!=1:raise ValueError('fractional yield cannot be rounded into integer artifact')
        return int(fraction),{'conversion':'exact_integer','source_exact':str(fraction)}
    if kind!='number':raise ValueError('explicit primitive artifact type required')
    if type(value) is float:
        if not math.isfinite(value):raise ValueError('finite source number required')
        return value,{'conversion':'unchanged_source_binary64','source_numeric_token_enclosure_proved':False}
    fraction=_fraction(value)
    try:converted=float(fraction)
    except OverflowError:raise ValueError('finite representable JSON number required') from None
    if not math.isfinite(converted) or (fraction!=0 and converted==0):raise ValueError('nonzero finite source cannot overflow/underflow JSON number')
    return converted,{'conversion':'exact_rational_to_JSON_binary64','source_exact':str(fraction),
        'binary64_exact':str(Fraction.from_float(converted)),'conversion_error_exact':str(Fraction.from_float(converted)-fraction),
        'decimal_rounding_applied':False}


def _type(kind,depth=0):
    if type(kind) is str:
        if kind not in ('integer','number','boolean','string'):raise ValueError('explicit primitive artifact type required')
        return
    if type(kind) is not dict or depth>=4:raise ValueError('finite typed JSON structure required')
    if kind.get('type')=='nullable':
        ce.keys(kind,['type','item']);_type(kind['item'],depth+1)
    elif kind.get('type')=='array':
        ce.keys(kind,['type','items','max_items'])
        if type(kind['max_items']) is not int or not 1<=kind['max_items']<=256:raise ValueError('finite array population bound required')
        _type(kind['items'],depth+1)
    elif kind.get('type')=='object':
        ce.keys(kind,['type','properties'])
        if type(kind['properties']) is not dict or not 1<=len(kind['properties'])<=MAX_FIELDS:raise ValueError('finite complete object property census required')
        for field,schema in kind['properties'].items():
            ce.identity(field)
            if field in RESERVED:raise ValueError('source artifacts cannot carry authorization fields')
            _type(schema,depth+1)
    else:raise ValueError('explicit primitive/array/object type required')


def _source(selector,documents):
    if type(selector) is not dict or selector.get('tool_id') not in documents:raise ValueError('bound tool identity required')
    document=documents[selector['tool_id']]
    if selector.get('kind')=='direct':
        ce.keys(selector,['kind','tool_id','pointer'])
        return _pointer(document,selector['pointer'])
    if selector.get('kind')!='unique_row':raise ValueError('direct or unique-row tool selector required')
    ce.keys(selector,['kind','tool_id','rows_pointer','matches_pointer','row_key','field'])
    ce.identity(selector['row_key']);ce.identity(selector['field'])
    rows=_pointer(document,selector['rows_pointer']);matches=_pointer(document,selector['matches_pointer'])
    if type(rows) is not list or not 1<=len(rows)<=128 or type(matches) is not list or len(matches)!=1:
        raise ValueError('unique selected row required; retain ambiguity rather than inventing tie winner')
    keys=[];selected=[]
    for row in rows:
        if type(row) is not dict or selector['row_key'] not in row:raise ValueError('complete typed row census required')
        key=row[selector['row_key']]
        if type(key) not in (int,str) or key in keys:raise ValueError('distinct literal row identities required')
        keys.append(key)
        if type(key) is type(matches[0]) and key==matches[0]:selected.append(row)
    if len(selected)!=1 or selector['field'] not in selected[0]:raise ValueError('matched source row field required')
    return selected[0][selector['field']]


def _load(request,base):
    ce.keys(request,['schema_version','contract','basis','tools','interpretation'])
    if type(request['schema_version']) is not int or request['schema_version']!=1:raise ValueError('scientific-artifact/v1 required')
    contract=request['contract'];ce.keys(contract,['source_scope','tool_fields','interpretation_fields','unresolved_semantics','max_artifact_bytes'])
    _text(contract['source_scope'])
    if type(contract['max_artifact_bytes']) is not int or not 128<=contract['max_artifact_bytes']<=128000:raise ValueError('finite artifact byte bound required')
    if type(request['tools']) is not dict or not 1<=len(request['tools'])<=8:raise ValueError('one to eight exact tool results required')
    if type(request['basis']) is not list or not 1<=len(request['basis'])<=8:raise ValueError('one to eight literal task/API/policy basis inputs required')
    documents={};pins=[];basis_paths=set()
    for pin in request['basis']:
        canonical=_basis(pin,base)
        if canonical in basis_paths:raise ValueError('distinct canonical source basis required')
        basis_paths.add(canonical);pins.append(deepcopy(pin))
    for identity,pin in request['tools'].items():
        ce.identity(identity);documents[identity]=ce.read_pin(pin,base);pins.append(deepcopy(pin))
    fields=contract['tool_fields'];models=contract['interpretation_fields']
    if type(fields) is not list or not 1<=len(fields)<=MAX_FIELDS or type(models) is not list or len(fields)+len(models)>MAX_FIELDS:raise ValueError('finite complete artifact field census required')
    ids=set()
    for row in fields:
        ce.keys(row,['field','type','source']);ce.identity(row['field'])
        if row['field'] in ids or row['field'] in RESERVED:raise ValueError('distinct nonauthorizing artifact fields required')
        ids.add(row['field'])
        _type(row['type'])
        _source(row['source'],documents)
    for field in models:
        ce.identity(field)
        if field in ids or field in RESERVED:raise ValueError('model interpretation cannot overwrite scientific tool field')
        ids.add(field)
    if type(request['interpretation']) is not dict or set(request['interpretation'])!=set(models):raise ValueError('exact interpretation text fields required')
    for value in request['interpretation'].values():_text(value)
    ambiguous=contract['unresolved_semantics']
    if type(ambiguous) is not list or len(ambiguous)>MAX_FIELDS:raise ValueError('bounded unserved semantic obligations required')
    seen=set()
    for row in ambiguous:
        ce.keys(row,['field','reason']);ce.identity(row['field']);_text(row['reason'])
        if row['field'] not in ids or row['field'] in seen:raise ValueError('distinct existing artifact ambiguity required')
        seen.add(row['field'])
    return contract,documents,pins


def compose(request,*,base_dir):
    """Construct strict JSON while retaining exact tool-to-field provenance."""
    contract,documents,_=_load(request,Path(base_dir).resolve(strict=True))
    artifact={};provenance=[]
    for row in contract['tool_fields']:
        raw=_source(row['source'],documents);value,conversion=_convert(raw,row['type'])
        artifact[row['field']]=value
        provenance.append({'field':row['field'],'type':row['type'],'source':deepcopy(row['source']),
            'tool_artifact_sha256':request['tools'][row['source']['tool_id']]['sha256'],'source_value':deepcopy(raw),**conversion})
    artifact.update(deepcopy(request['interpretation']))
    text=json.dumps(artifact,sort_keys=True,indent=2,allow_nan=False)+'\n'
    if len(text.encode())>contract['max_artifact_bytes']:raise ValueError('scientific artifact exceeds complete output budget')
    return {'kind':'scientific_tool_artifact','contract_sha256':ce.digest(contract),'basis':deepcopy(request['basis']),'artifact':artifact,'artifact_text':text,
        'tool_provenance':provenance,'model_interpretation_fields':list(contract['interpretation_fields']),
        'unresolved_semantics':deepcopy(contract['unresolved_semantics']),'source_scope':contract['source_scope'],
        'tool_report_truth_verified':False,'interpretation_scientifically_validated':False,
        'complete_task_semantics_claimed':False,'scientific_acceptance':False,'execution_authorized':False}


def input_pins(request,*,base_dir):return _load(request,Path(base_dir).resolve(strict=True))[2]
