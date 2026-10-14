"""Fictional source mappings and native text; no upstream snapshots."""
import hashlib
import json
from pathlib import Path
from ravel.physics import native_cumulant as n

def pin(path,role):
    return {'role':role,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def block(kind,path,columns,rows,edges=None,masked=None):
    extra=[]
    if edges is not None:extra.append('Edges(A1): '+json.dumps(edges))
    if masked is not None:extra.append('MaskedBins: '+json.dumps(masked))
    return '\n'.join([f'BEGIN YODA_{kind}_V3 {path}',f'Path: {path}',f'Type: {kind}','---',*extra,'# '+' '.join(columns),*[' '.join(row) for row in rows],f'END YODA_{kind}_V3',''])

def mapping(root,routine='ANA_0001',count=2,edges=None,subsamples=2,native_weight='',suffix=''):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);edges=edges or [0.,1.,3.]
    source=root/'source.txt';source.write_text('Fictional source-format specification; not native qualification.\n')
    reference=root/'reference.yoda';reference.write_text(''.join(block('ESTIMATE1D',f'/REF/{routine}/q{i}',[],[],edges) for i in range(count)))
    outputs=[];profiles=[]
    for i in range(count):
        operands=[]
        for j in range(subsamples):
            key=f'operand{i}_{j}';operands.append(key)
            profiles.append({'id':key,'path':f'/RAW/{routine}/TMP/{key}','reference_path':f'/REF/{routine}/q{i}'})
        outputs.append({'path':f'/{routine}/q{i}','operation':'source_operation_'+str(i),'operands':operands,'reference_path':f'/REF/{routine}/q{i}','axes':[{'name':'coordinate','unit':'1'}],'unit':'1','error_policy':'literal_zero' if i%2 else 'native_magnitudes','error_semantics':'Supplied literal error magnitudes; no inferred covariance.'})
    return {'protocol':'native-cumulant/v1','routine':routine,'runtime_version':'4.1.3','sources':[pin(source,'analysis'),pin(reference,'reference')],'outputs':outputs,'profiles':profiles,'native_weight':{'native':native_weight,'suffix':suffix},'semantic_notes':['Fictional source semantics only.'],'study':{'study_id':routine,'parameter_grid':[{'coordinate':v} for v in edges],'datasets':['DATA-'+str(i) for i in range(subsamples)],'output':{'stem':'native-cumulant-observables','formats':['json','markdown']}}}

def payload(requests,precision=None):
    family=requests[0]['native_cumulant'];cap=n._Capture();_,edges=n._sources(family,'.',cap);cap.finish();parts=[];suffix=family['native_weight']['suffix']
    for row in family['outputs']:
        rows=[]
        for x,lo,hi in n.booked_geometry(edges[row['reference_path']]):
            geometry=[str(v) if precision is None else format(v,precision) for v in (x,lo,hi)]
            rows.append([*geometry,'-0.125',*(['0','0'] if row['error_policy']=='literal_zero' else ['0.0625','0.0625'])])
        parts.append(block('SCATTER2D',row['path']+suffix,n.SCATTER_COLUMNS,rows))
    for row in family['profiles']:
        e=edges[row['reference_path']];rows=[['-2','4','0','0','-1','0','0','1'] for _ in range(len(e)+1)]
        parts.append(block('PROFILE1D',row['path']+suffix,n.PROFILE_COLUMNS,rows,e,[1]))
    parts.append(block('COUNTER','/RAW/_EVTCOUNT'+suffix,['sumW','sumW2','numEntries'],[['-2','4','3']]))
    return ''.join(parts)
