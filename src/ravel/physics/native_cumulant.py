"""Complete supplied native cumulant transport without numerical inference.

Mappings and source bytes are selected by the caller. Finalized Scatter2D and
all declared RAW profiles retain their scalar states, geometry and error tokens.
"""
import math
import re
import json
from decimal import Decimal
from pathlib import Path
from . import native_categorical as reader
from .truth_reco_response import study_contract

SCATTER_COLUMNS = ['val1','err1-','err1+','val2','err2-','err2+']
PROFILE_COLUMNS = ['sumW','sumW2','sumW(A1)','sumW2(A1)',
                   'sumW(A2)','sumW2(A2)','sumW(A1,A2)','numEntries']
LIMITS = [
 'Source-bound native transport; runtime and physics qualification remain separate.',
 'No covariance, variance from error bars, normalization or group independence is inferred.',
 'All supplied outputs, native scalar states, flow and masked rows remain.',
]

class NativeCumulantError(ValueError):
    def __init__(self,message,reason='invalid_input'):
        super().__init__(message);self.reason=reason


def require(ok,why):
    if not ok:raise NativeCumulantError(why)


def _identity(path):
    p=Path(path)
    require(p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),
            'regular nonlinked source and ancestors required')
    s=p.stat(follow_symlinks=False)
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)


class _Capture:
    def __init__(self):
        self.files={}

    def read(self,path,expected=None):
        p=Path(path).absolute()
        before=_identity(p)
        raw,text=reader.read_bytes(p)
        require(_identity(p)==before,'source identity changed while reading')
        digest=reader.sha(raw)
        require(expected is None or digest==expected,'source/output digest mismatch')
        if p in self.files:
            require(self.files[p]==(before,digest),'previously read source changed')
        else:
            self.files[p]=(before,digest)
        return raw,text

    def finish(self):
        for p,(identity,digest) in self.files.items():
            require(_identity(p)==identity,'ending source descriptor/path identity differs')
            raw,_=reader.read_bytes(p)
            require(reader.sha(raw)==digest and _identity(p)==identity,
                    'ending source/output bytes differ')


def _family(family):
    if not isinstance(family,dict) or not {'outputs','profiles','sources'}<=set(family):
        raise NativeCumulantError('supplied native_cumulant mapping required','missing_input')
    require(set(family)=={'protocol','routine','runtime_version','sources','outputs','profiles','native_weight','semantic_notes','study'},'closed native cumulant mapping required')
    require(family['protocol']=='native-cumulant/v1','supported transport mapping protocol required')
    require(isinstance(family['routine'],str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',family['routine']) and isinstance(family['runtime_version'],str) and family['runtime_version'],'explicit source routine/runtime required')
    study_contract(family['study'])
    sources=family['sources']
    require(isinstance(sources,list) and sources and all(isinstance(s,dict) and set(s)=={'role','path','sha256'} and isinstance(s['role'],str) and s['role'] and isinstance(s['path'],str) and s['path'] and isinstance(s['sha256'],str) and re.fullmatch('[0-9a-f]{64}',s['sha256']) for s in sources),'complete supplied source/writer inventory required')
    require(len({s['role'] for s in sources})==len(sources) and len({s['path'] for s in sources})==len(sources) and sum(s['role']=='reference' for s in sources)==1,'unique sources and one reference required')
    w=family['native_weight']
    require(isinstance(w,dict) and set(w)=={'native','suffix'} and isinstance(w['native'],str) and w['native'].isascii() and not any(c.isspace() or c in '[]' for c in w['native']) and w['suffix'] in ('',f"[{w['native']}]") and (w['native'] or w['suffix']==''),'explicit ASCII native weight/suffix required')
    outputs=family['outputs'];profiles=family['profiles']
    require(isinstance(outputs,list) and 1<=len(outputs)<=256 and isinstance(profiles,list) and 1<=len(profiles)<=4096,'bounded complete supplied output/operand populations required')
    require(all(isinstance(row,dict) and set(row)=={'id','path','reference_path'} and all(isinstance(v,str) and v for v in row.values()) for row in profiles),'complete supplied operand profile mapping required')
    require(len({r['id'] for r in profiles})==len(profiles) and len({r['path'] for r in profiles})==len(profiles),'unique complete raw profile identities required')
    for row in outputs:
        require(isinstance(row,dict) and set(row)=={'path','operation','operands','reference_path','axes','unit','error_policy','error_semantics'},'complete supplied final mapping required')
        require(isinstance(row['path'],str) and row['path'].startswith('/'+family['routine']+'/') and isinstance(row['reference_path'],str) and row['reference_path'].startswith('/REF/'),'supplied source final/reference namespace required')
        require(isinstance(row['operation'],str) and row['operation'] and isinstance(row['operands'],list) and row['operands'] and len(set(row['operands']))==len(row['operands']) and set(row['operands'])<={r['id'] for r in profiles},'complete explicit final operand dependencies required')
        require(isinstance(row['axes'],list) and len(row['axes'])==1 and set(row['axes'][0])=={'name','unit'} and all(isinstance(v,str) and v for v in row['axes'][0].values()) and isinstance(row['unit'],str) and row['unit'],'supplied axis and output units required')
        require(row['error_policy'] in ('native_magnitudes','literal_zero') and isinstance(row['error_semantics'],str) and row['error_semantics'],'source error interpretation required')
    require(len({r['path'] for r in outputs})==len(outputs),'unique complete final paths required')
    require({r['id'] for r in profiles}=={v for row in outputs for v in row['operands']},'unused or missing raw profile in supplied mapping')
    require(isinstance(family['semantic_notes'],list) and all(isinstance(v,str) and v for v in family['semantic_notes']),'explicit source limitations required')
    return family


def validate_request(request):
    if not isinstance(request,dict) or 'native_cumulant' not in request or not isinstance(request['native_cumulant'],dict) or not {'outputs','profiles','sources'}<=set(request['native_cumulant']):
        raise NativeCumulantError('supplied native_cumulant mapping required','missing_input')
    require(set(request)=={'path','axes','representation','normalization','unit','quantity_kind','native_cumulant'},'closed source-native cumulant request required')
    family=_family(request['native_cumulant']);suffix=family['native_weight']['suffix']
    matches=[row for row in family['outputs'] if request['path']==row['path']+suffix]
    require(len(matches)==1,'one supplied source-native output path required');row=matches[0]
    require(request['quantity_kind']=='native_cumulant' and request['representation']=='native' and request['normalization']=='absolute' and request['unit']==row['unit'] and request['axes']==row['axes'],'native untransformed output axes/unit required')
    return row


def requests_for(family):
    """Construct the complete explicitly selected source mapping, with no default."""
    _family(family)
    return [{'path':row['path']+family['native_weight']['suffix'],'axes':row['axes'],'representation':'native','normalization':'absolute','unit':row['unit'],'quantity_kind':'native_cumulant','native_cumulant':family} for row in family['outputs']]


def validate_population(requests):
    families={}
    for r in requests:
        if r.get('quantity_kind')!='native_cumulant':continue
        validate_request(r);w=r['native_cumulant']['native_weight'];key=(w['native'],w['suffix'])
        families.setdefault(key,[]).append(r)
    require(len(families)<=64,'bounded complete native stream population')
    require(len({k[1] for k in families})==len(families),'native suffix shared by distinct weights')
    for group in families.values():
        family=group[0]['native_cumulant'];suffix=family['native_weight']['suffix']
        require(len(group)==len(family['outputs']) and {r['path'] for r in group}=={r['path']+suffix for r in family['outputs']},'all supplied cumulant outputs required for each declared stream')
        require(all(r['native_cumulant']==family for r in group),'family source/weight contracts differ')
    return families


def validate_operation(task):
    for group in validate_population(task['observables']).values():
        mapping=group[0]['native_cumulant']
        require(task['routine']==mapping['routine'] and task['runtime']['version']==mapping['runtime_version'],'native cumulant routine/runtime differs from supplied source mapping')


def _sources(family,base,capture):
    _family(family);paths=[];reference=None
    for pin in family['sources']:
        p=Path(pin['path']);p=p if p.is_absolute() else Path(base)/p
        _,text=capture.read(p,pin['sha256']);paths.append(p.absolute())
        if pin['role']=='reference':reference=reader.blocks(text)
    edges={}
    for row in [*family['outputs'],*family['profiles']]:
        name=row['reference_path'];b=reference.get(name)
        require(b is not None and b['type']=='ESTIMATE1D','complete supplied native reference geometry required')
        edges[name]=_edges(b)
    return paths,edges


def quantity_inputs(requests,base_dir='.'):
    """Capture source/grammar dependencies through ordinary existing-events inputs."""
    cap=_Capture();paths=[]
    for group in validate_population(requests).values():
        got,_=_sources(group[0]['native_cumulant'],base_dir,cap);paths+=got
    cap.finish()
    return list(dict.fromkeys(paths+[Path(__file__).resolve(),Path(reader.__file__).resolve()]))


def _edges(block):
    rows=re.findall(r'^Edges\(A1\): (.+)$',block['body'],re.M)
    require(len(rows)==1,'exact continuous source edges required')
    values=reader.decode(rows[0])
    require(isinstance(values,list) and 2<=len(values)<=100001 and
            all(type(v) in (int,float) and math.isfinite(v) for v in values) and
            all(a<b for a,b in zip(values,values[1:])), 'finite ordered geometry required')
    return values


def _columns(block,expected):
    require(re.findall(r'^Path: (.+)$',block['body'],re.M)==[block['path']],
            'BEGIN and annotation Path identity differs')
    lines=block['body'].splitlines()
    headings=[i for i,line in enumerate(lines) if line.startswith('# '+expected[0])]
    require(len(headings)==1,'one native numerical header required')
    i=headings[0]
    require(lines[i][1:].split()==expected,'exact native writer column order required')
    rows=[line.split() for line in lines[i+1:] if line.strip() and not line.startswith('#')]
    require(all(len(row)==len(expected) for row in rows), 'native row width differs')
    return rows


def _scalar(token):
    lower=token.lower()
    states={'nan':'nan','+nan':'nan','-nan':'nan','---':'undefined',
            'inf':'positive_infinity','+inf':'positive_infinity','-inf':'negative_infinity'}
    if lower in states:
        return {'value':None,'state':states[lower],'token':token}
    return {'value':reader.number(token),'state':'finite','token':token}


def booked_geometry(expected_edges):
    """Native midpoint booking geometry for the supported transport format.

    Binary64 midpoint and each absolute displacement are serialized separately.
    This is a declared transport grammar, not inferred source physics semantics.
    """
    return [((lo+hi)/2.0,abs((lo+hi)/2.0-lo),abs((lo+hi)/2.0-hi))
            for lo,hi in zip(expected_edges,expected_edges[1:])]


def _geometry_matches(token,expected):
    # WriterYODA scientific precision6, or WriterDoublePrecision max_digits10=17.
    # Exact decoded-double repr also admits source-format replay fixtures; every
    # comparison is Decimal equality, never isclose or a numeric tolerance.
    got=Decimal(token)
    return got in {Decimal(repr(expected)),Decimal(format(expected,'.6e')),
                   Decimal(format(expected,'.17e'))}


def parse_scatter(block,expected_edges,operation):
    require(block['type']=='SCATTER2D','final cumulant requires native Scatter2D')
    rows=_columns(block,SCATTER_COLUMNS)
    geometry=booked_geometry(expected_edges)
    require(len(rows)==len(geometry),'complete source-reference point count required')
    result=[];last=None
    for i,tokens in enumerate(rows):
        vals={k:_scalar(v) for k,v in zip(SCATTER_COLUMNS,tokens)}
        require(all(vals[k]['state']=='finite' for k in SCATTER_COLUMNS[:3]), 'finite native x geometry required')
        x=vals['val1']['value'];require(last is None or x>last,'ordered source x coordinates required');last=x
        require(vals['err1-']['value']>=0 and vals['err1+']['value']>=0,'native x error magnitudes required')
        require(all(_geometry_matches(token,want) for token,want in zip(tokens[:3],geometry[i])),
                'final x/error geometry differs from exact source-reference booking')
        for k in ('err2-','err2+'):
            require(vals[k]['value'] is None or vals[k]['value']>=0, 'native y error magnitudes required; do not change signs')
        if operation=='literal_zero':
            require(all(vals[k]['state']=='finite' and vals[k]['value']==0 for k in ('err2-','err2+')),
                    'supplied native no-error policy requires literal zero error bars')
        result.append({'ordinal':i,'x':x,'x_error_minus':vals['err1-']['value'],
                       'x_error_plus':vals['err1+']['value'],'value':vals['val2']['value'],
                       'native_error_minus':vals['err2-']['value'], 'native_error_plus':vals['err2+']['value'],
                       'cells':vals,'variance':None,'native_zero_fallback_distinguishable':False})
    return {'native_type':block['type'],'points':result,'native_text':block['body'],
            'block_sha256':block['block_sha256'],'error_convention':'nonnegative native magnitudes',
            'covariance':None,'bin_width_transform_applied':False}


def parse_profile(block,expected_edges):
    require(block['type']=='PROFILE1D','ECorr RAW primitive must be Profile1D')
    edges=_edges(block);require(edges==expected_edges,'source ECorr/reference edge mismatch')
    rows=_columns(block,PROFILE_COLUMNS)
    require(len(rows)==len(edges)+1,'complete RAW finite/underflow/overflow rows required')
    masks=re.findall(r'^MaskedBins: (.+)$',block['body'],re.M)
    require(len(masks)<=1,'unique native mask required')
    masked=reader.decode(masks[0]) if masks else []
    require(isinstance(masked,list) and all(type(i) is int and 0<=i<len(rows) for i in masked)
            and len(set(masked))==len(masked),'exact masked native index census required')
    out=[]
    for i,tokens in enumerate(rows):
        cells={k:_scalar(v) for k,v in zip(PROFILE_COLUMNS,tokens)}
        for k in ('sumW2','numEntries'):
            require(cells[k]['value'] is None or cells[k]['value']>=0,'negative RAW squared weight/count')
        out.append({'serialized_index':i,'flow':'underflow' if i==0 else ('overflow' if i==len(edges) else 'finite'),
                    'low':None if i==0 else edges[i-1], 'high':None if i==len(edges) else edges[i],
                    'masked':i in masked,'primitive_cells':cells,'variance':None})
    return {'native_type':block['type'],'edges':edges,'rows':out,'native_text':block['body'],
            'block_sha256':block['block_sha256'],'ordinary_profile_error_inferred':False,
            'reference_bin_recoverability':'not_inferred', 'covariance':None}


def export_family(path,requests,*,base_dir='.'):
    groups=validate_population(requests);cap=_Capture()
    raw,text=cap.read(path);objects=reader.blocks(text);observables={};families=[]
    for group in groups.values():
        family=group[0]['native_cumulant'];_,edges=_sources(family,base_dir,cap)
        suffix=family['native_weight']['suffix'];profiles={};finals={}
        for row in family['profiles']:
            name=row['path']+suffix
            require(name in objects,'missing complete supplied RAW operand profile: '+name)
            profiles[name]=parse_profile(objects[name],edges[row['reference_path']])
        expected={row['path']+suffix for row in family['outputs']}
        present={p for p,b in objects.items() if b['type']=='SCATTER2D' and p.startswith('/'+family['routine']+'/') and (p.endswith(suffix) if suffix else not re.search(r'\[[^]]*\]$',p))}
        require(present==expected,'source final Scatter2D population changed; no silent dropping')
        for request in group:
            row=validate_request(request);name=request['path']
            final=parse_scatter(objects[name],edges[row['reference_path']],row['error_policy']);finals[name]=final
            observables[name]={'contract':request,'quantity_kind':'native_cumulant',
                'native_finalized':final,'bins':final['points'],'native_operation':row['operation'],
                'operand_correlators':row['operands'],
                'raw_profile_paths':[r['path']+suffix for r in family['profiles'] if r['id'] in row['operands']],
                'native_error_semantics':row['error_semantics'],
                'normalization':'untransformed_native','flow_sumw':None,'flow_sumw2':None,
                'raw_flow_sumw':None,'variance_from_error_bars':False,'covariance':None,
                'weight_identity_status':'declared_unverified','native_weight_identity_observed':False,
                'source_yoda_sha256':reader.sha(raw),'physics_validated':False,'limits':LIMITS+family['semantic_notes']}
        families.append({'contract':family,'final_outputs':finals,'raw_profiles':profiles,
                         'complete_final_count':len(finals),'complete_raw_profile_count':len(profiles),
                         'covariance':None,'native_normalization_qualified':False})
    cap.finish()
    return {'observables':observables,'transport':{'schema_version':1,'kind':'native-cumulant-family',
        'families':families,'whole_native_object_inventory':[
            {'path':p,'native_type':b['type'],'block_sha256':b['block_sha256']} for p,b in objects.items()],
        'complete_native_text':text,'source_yoda_sha256':reader.sha(raw),
        'source_population_transport_complete':bool(groups),
        'physics_validated':False,'native_runtime_qualified':False,'limits':LIMITS}}


def write_report(observables,output):
    """Complete point/error-token tables; full RAW population stays in observables.json."""
    selected={p:o for p,o in observables.items() if o.get('quantity_kind')=='native_cumulant'}
    if not selected:
        return []
    validate_population([o['contract'] for o in selected.values()])
    rows=['# Native cumulant/flow point transport', '',
          'Source-native values and error magnitudes; no covariance or physics qualification.', '',
          '| Path | Native call | Point | x | x minus | x plus | y | y minus | y plus |',
          '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for path,obj in selected.items():
        require(path==obj['contract']['path'],'report path/contract differs')
        for row in obj['native_finalized']['points']:
            tokens=[row['cells'][k]['token'] for k in SCATTER_COLUMNS]
            rows.append('| '+' | '.join([path,obj['native_operation'],str(row['ordinal']),*tokens])+' |')
    rows+=['','The complete native file, all supplied RAW profiles per declared stream, flow/masked rows and remaining native objects are retained in observables.json and histograms.yoda.','',*['- '+v for v in LIMITS],'']
    doc={'schema_version':1,'kind':'native-cumulant-point-table','objects':selected,
         'full_raw_delivery':'observables.json/native_cumulant_transport',
         'physics_validated':False,'covariance':None,'limits':LIMITS}
    data=json.dumps(doc,indent=2,allow_nan=False)+'\n'
    content='\n'.join(rows)
    require(max(len(data.encode()),len(content.encode()))<=32*1024*1024,'bounded complete native report required')
    out=Path(output);require(out.is_dir() and not any(p.is_symlink() for p in (out,*out.parents)),
                             'regular nonlinked report directory required')
    studies=[o['contract']['native_cumulant']['study'] for o in selected.values()]
    require(all(v==studies[0] for v in studies),'one supplied report specification required')
    report=study_contract(studies[0])['output'];targets=[]
    if 'json' in report['formats']:targets.append((out/(report['stem']+'.json'),data))
    if 'markdown' in report['formats']:targets.append((out/(report['stem']+'.md'),content))
    require(all(not p.exists() and not p.is_symlink() for p,_ in targets),'fresh report outputs required')
    from ravel.workflow.state_io import atomic_json
    cap=_Capture()
    for p,text in targets:
        if p.suffix=='.json':
            atomic_json(p,doc)
        else:
            p.write_text(text,encoding='utf-8')
        cap.read(p,reader.sha(text.encode()))
    cap.finish()
    return [p.name for p,_ in targets]


def render_tables(observables,output):
    """Adapt the source-selected report to the common figure-table interface."""
    files=write_report(observables,output)
    if not files:return []
    selected=next(obj for obj in observables.values() if obj.get('quantity_kind')=='native_cumulant')
    report=study_contract(selected['contract']['native_cumulant']['study'])['output']
    return [{'stem':report['stem'],'files':files,'normalization':'Untransformed source-native cumulants and complete RAW operands; no inferred covariance'}]
