"""Released SPheno4.0.5 real weak-scale MSSM source/card and output contract.

No spectrum or decay formula is reimplemented. The native operation creates a
new consistent full SLHA origin; it cannot graft widths onto another solver.
"""
import hashlib,json,math,os,re,stat
from fractions import Fraction
from pathlib import Path
from . import model_tool_bridge as custody,model_specific_spectrum as named

NAME='MSSM-SPheno-4.0.5'
OPERATION='spheno-4.0.5-mssm-spectrum-decays'
PROFILE=Path(__file__).resolve().parents[1]/'data/spectrum/mssm-spheno-4.0.5.json'
TOOLS=('fc','make','ar','uname','rm','mv')
# Required literal choices, including disabled side effects. No adapter defaults.
SETTINGS=(1,2,3,4,5,6,7,8,9,10,11,12,13,21,31,32,34,35,36,37,38,39,40,41,42,45,48,49,70,80,99,100,101,110)
EXTPAR=(0,1,2,3,11,12,13,23,24,31,32,33,34,35,36,41,42,43,44,45,46,47,48,49)
SM=(1,2,3,4,5,6,7,8,11,12,13,14,21,22,23,24)

require=named.require

def read(path,expected=None,limit=8*1024*1024):
    p=custody._regular(path,Path.cwd()); before=p.stat()
    ident=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(0<=before.st_size<=limit,'bounded SPheno descriptor required')
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        opened=os.fstat(stream.fileno())
        require(stat.S_ISREG(opened.st_mode) and ident(before)==ident(opened),'stable regular SPheno descriptor required')
        raw=stream.read(limit+1); after=os.fstat(stream.fileno())
    require(len(raw)==before.st_size and len(raw)<=limit and ident(before)==ident(after)==ident(p.stat()) and not any(x.is_symlink() for x in (p,*p.parents)),'SPheno source changed during bounded read')
    require(expected is None or hashlib.sha256(raw).hexdigest()==expected,'authenticated SPheno bytes differ')
    return raw

def document(raw):
    from ravel.workflow.state_io import _unique
    def reject(value):raise ValueError('nonfinite SPheno source document '+value)
    def finite(value):
        result=float(value)
        if not math.isfinite(result):reject(value)
        return result
    return json.loads(raw,object_pairs_hook=_unique,parse_constant=reject,parse_float=finite)

def profile():return document(read(PROFILE))
def selected(c):return c.get('schema_version')==3 and c.get('operation')==OPERATION

def input_witness(raw):
    # Exact native block/row grammar and order, excluding ignored namespaces.
    require(type(raw) is bytes and 0<len(raw)<=2*1024*1024,'bounded complete native input required')
    text=raw.decode('ascii'); doc=named.inventory(raw); required={'MODSEL':(1,4,5,6),'SMINPUTS':SM,'VCKMIN':(1,2,3,4),'MINPAR':(3,), 'EXTPAR':EXTPAR,'SPHENOINPUT':SETTINGS}
    rows={}; order=[]
    for section in doc['sections']:
        name=section.get('name'); require(section['kind']=='block' and name in required and name not in rows and section['scale'] is None,'no unknown, duplicate, scaled, output or external-spectrum block allowed')
        rows[name]={}; order.append(name)
        # Native prefix matching is positional: BLOCK at column1, one space.
        require(section['source_text'].split('#',1)[0].strip().upper()=='BLOCK '+name and section['source_text'][0] in 'Bb','literal native BLOCK prefix required')
        for row in section['rows']:
            require(row['kind']=='scalar' and len(row['codes'])==1 and row['codes'][0] not in rows[name],'unique explicit scalar input row required')
            rows[name][row['codes'][0]]=row['value']
        require(set(rows[name])==set(required[name]),'complete exact source-consumed '+name+' census required')
    require(order==list(required),'native reader order MODSEL/SMINPUTS/VCKMIN/MINPAR/EXTPAR/SPHENOINPUT required')
    require(all(len(line.split('#',1)[0])<=80 for line in text.splitlines()),'native80-character read buffer exceeded')
    n=lambda block,k:named.number(rows[block][k])
    require(all(n('MODSEL',i)==0 for i in (1,4,5,6)),'real, R-parity-conserving weak-scale MSSM with no generation mixing required')
    require(n('VCKMIN',4)==0 and 0<=n('VCKMIN',1)<1,'real CKM source branch; no phase silently discarded')
    require(n('MINPAR',3)>0 and n('EXTPAR',0)>0 and n('EXTPAR',24)>0,'positive tanbeta, Q GeV and running m_A^2 GeV^2 required')
    require(all(n('EXTPAR',i)>=0 for i in EXTPAR if 31<=i<=49),'soft mass card entries are nonnegative masses GeV, not mass-squared')
    require(all(n('SMINPUTS',i)>0 for i in SM if i not in (8,12,14)) and all(n('SMINPUTS',i)==0 for i in (8,12,14)),'complete positive SM values and explicit massless-neutrino branch required')
    fixed={2:0,3:0,4:0,6:0,8:0,11:1,12:0,21:0,31:0,32:0,39:0,80:1,89:0}
    for k,v in fixed.items():
        if k in SETTINGS:require(n('SPHENOINPUT',k)==v,'native setting '+str(k)+' must explicitly equal '+str(v))
    integers=set(SETTINGS)-{12,31,34,40,41,42}
    for k in integers:require(n('SPHENOINPUT',k).denominator==1,'integral native flag required')
    for k in integers-{1,35,37,38}:require(n('SPHENOINPUT',k) in (0,1),'explicit source Boolean branch required')
    require(n('SPHENOINPUT',1) in (-1,0,1,2) and n('SPHENOINPUT',37) in (1,2) and n('SPHENOINPUT',38) in (1,2,3),'released error/Yukawa/RGE branch required')
    require(0<n('SPHENOINPUT',34)<1 and 1<=n('SPHENOINPUT',35)<=10000 and all(n('SPHENOINPUT',k)>0 for k in (40,41,42)),'explicit positive precision/iterations/SM source inputs required')
    return {'profile':NAME,'all_input':doc,'literal_rows':rows,'conventions':profile()['conventions'],'native_selected_branch':'MSSM_mu_mA2_real_no_generation_mixing','native_numerical_defaults':{'three_body_epsI':'1e-5','three_body_deltaM':'1e-3','CalcTBD':False},'adapter_defaults_selected':False,'physical_validity_established':False}

def validate(c):
    custody._keys(c,('schema_version','operation','profile','source','trusted_generated_source','source_capsule','input_card','tools','runtime_inputs','native_path','max_ram_mib'),'SPheno spectrum/decay config')
    require(type(c['schema_version']) is int and selected(c) and c['profile']==NAME,'released SPheno MSSM schema3/profile required')
    require(c['trusted_generated_source'] is True and type(c['source']) is str and c['source'].strip(),'explicit executable-source trust/provenance required')
    custody._keys(c['tools'],TOOLS,'SPheno native tools')
    require(type(c['native_path']) is str and c['native_path'] and all(p and Path(p).is_absolute() for p in c['native_path'].split(os.pathsep)),'closed explicit native PATH required')
    require(type(c['runtime_inputs']) is list and 1<=len(c['runtime_inputs'])<=100000,'complete explicit finite native runtime inventory required')
    require(type(c['max_ram_mib']) is int and 1024<=c['max_ram_mib']<=4096,'same admitted single-worker RAM contract required')
    return c

def source_contract(doc):
    p=profile(); require(doc['baseline_kind']=='pregenerated-spectrum' and doc['files']==p['files'] and doc['modes']==p['modes'],'complete55 released SPheno members/modes required; no mirror or prebuilt solver substitution')

def inputs(c,base):
    from . import generated_spectrum as engine
    validate(c);manifest,bundle,doc,_=engine._bundle(c['source_capsule'],base);source_contract(doc)
    rows=[PROFILE,manifest,bundle,custody._pin(c['input_card'],base)]
    input_witness(read(rows[-1],c['input_card']['sha256']))
    for role,fact in c['tools'].items():
        p=custody._pin(fact,base);require(os.access(p,os.X_OK),'executable native tool required')
        label='gfortran' if role=='fc' else role
        found=next((Path(d)/label for d in c['native_path'].split(os.pathsep) if (Path(d)/label).exists()),None)
        require(found is not None and not any(x.is_symlink() for x in (found,*found.parents)) and found.resolve()==p,'first native PATH lookup must be exact regular pinned '+label+'; aliases require explicit regularization')
        rows.append(p)
    rows += [custody._pin(p,base) for p in c['runtime_inputs']]
    return rows

def commands(c,base,work,out):
    paths={k:str(custody._pin(v,base)) for k,v in c['tools'].items()}
    target=work/'source/spheno/bin/SPheno'
    # Released120-character argument buffers: exact isolated-cwd basenames.
    return {'compile':[paths['make'],'-j1','F90=gfortran','bin/SPheno'],'solver':[str(target),'selected-input.slha','spectrum-output.slha']}

def launcher(command,cwd,path,removed):
    return ('import os\ncommand='+repr(command)+'\nos.chdir('+repr(str(cwd))+')\n'+
        'for key in '+repr(tuple(removed))+': os.environ.pop(key,None)\n'+
        'os.environ["PATH"]='+repr(path)+'\nos.environ["LC_ALL"]="C"\n'+
        'for key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS"): os.environ[key]="1"\n'+
        'os.execv(command[0],command)\n')

def population(root,limit=512*1024*1024):
    root=custody._regular(root,Path.cwd(),directory=True);rows={'.':{'kind':'directory'}};total=0
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(),'no generated source/output aliases')
        if p.is_dir():rows[p.relative_to(root).as_posix()]={'kind':'directory'}
        else:
            require(p.is_file(),'only complete regular generated files/directories allowed')
            before=p.stat(); require(stat.S_ISREG(before.st_mode),'regular generated population required')
            total+=before.st_size; require(total<=limit and len(rows)<20000,'complete generated population exceeds declared ceiling; never truncate')
            raw=read(p,limit=limit);rows[p.relative_to(root).as_posix()]={'kind':'file','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'mode':stat.S_IMODE(before.st_mode)}
    return rows

def write_exact(path,doc):
    raw=(json.dumps(doc,indent=2,allow_nan=False)+'\n').encode();Path(path).write_bytes(raw)
    require(read(path,limit=64*1024*1024)==raw,'generated SPheno metadata differs from intended serialization')
    return {'path':str(Path(path).absolute()),'sha256':hashlib.sha256(raw).hexdigest()}
