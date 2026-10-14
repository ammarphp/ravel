"""Released NMSSM spectrum conventions and explicit, reviewed UFO-point joins.

No model is imported or evaluated here. FlexibleSUSY remains the sole solver;
source-compatible basis/scale/address mappings are explicit reviewed inputs.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

from . import model_tool_bridge as custody, model_inputs

PROFILE = Path(__file__).resolve().parents[1]/'data/spectrum/nmssm-2.9.0.json'
NAME = 'NMSSM-FlexibleSUSY-2.9.0'
SCOPE = 'generated_model_spectrum_transport'


def require(condition, message):
    if not condition: raise ValueError(message)


def raw_file(path, expected=None):
    """Authenticate the bytes actually consumed, including descriptor identity."""
    import os
    p=custody._regular(path,Path.cwd());before=p.stat()
    require(0<before.st_size<=model_inputs.MAX_BYTES,'bounded nonempty spectrum document required')
    with p.open('rb') as stream:
        opened=os.fstat(stream.fileno());raw=stream.read(model_inputs.MAX_BYTES+1);closed=os.fstat(stream.fileno())
    after=p.stat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(opened)==identity(closed)==identity(after),'spectrum document changed during consumption')
    require(expected is None or hashlib.sha256(raw).hexdigest()==expected,'consumed spectrum document differs from pin')
    return raw


def profile_path(name=NAME):
    if name==NAME:return PROFILE
    from . import spheno_mssm
    if name==spheno_mssm.NAME:return spheno_mssm.PROFILE
    from . import weak_scale_mssm as weak
    require(name==weak.NAME,'explicit released named-model profile required')
    return weak.PROFILE


def profile(name=NAME):
    return json.loads(raw_file(profile_path(name)))


def layout(c):
    if c['schema_version']==1:
        return {'model':'CMSSM','root':'cmssm','target':'models/CMSSM/run_CMSSM.x','input':'models/CMSSM/LesHouches.in.CMSSM'}
    from . import spheno_mssm
    if spheno_mssm.selected(c):return {'model':'MSSM','root':'spheno','target':'bin/SPheno','input':'selected-input.slha'}
    from . import weak_scale_mssm as weak
    if c['profile']==weak.NAME:
        return {'model':'lowMSSM','root':'lowmssm','target':'models/lowMSSM/run_lowMSSM.x','input':'models/lowMSSM/LesHouches.in.lowMSSM'}
    require(c['profile']==NAME,'only genuine released named-model profiles are supported')
    return {'model':'NMSSM','root':'nmssm','target':'models/NMSSM/run_NMSSM.x','input':'models/NMSSM/LesHouches.in.NMSSM'}


def number(token):
    require(type(token) is str and len(token)<=128 and re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?',token) is not None,'literal finite SLHA number required')
    value=Fraction(token.replace('D','E').replace('d','e'))
    require(math.isfinite(float(value)) and (value==0 or float(value)!=0),'finite nonunderflowing binary64-representable SLHA number required')
    return value


def inventory(raw):
    """Lossless original lines plus occurrence/scale-aware static rows.

    Unknown block bodies are retained opaquely, never silently discarded or
    treated as physics. Only explicit finite scalar rows can become card values.
    """
    require(type(raw) is bytes and 0<len(raw)<=model_inputs.MAX_BYTES,'bounded raw SLHA bytes required')
    lines=raw.decode('utf-8-sig').splitlines(keepends=True);sections=[];current=None
    for n,line in enumerate(lines,1):
        tokens=line.split('#',1)[0].strip().split()
        if not tokens: continue
        head=tokens[0].upper()
        if head=='BLOCK':
            require(len(tokens)>=2 and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',tokens[1]),'literal SLHA block name required')
            rest=' '.join(tokens[2:])
            if tokens[1].upper()=='QNUMBERS':
                require(re.fullmatch(r'[+-]?\d{1,9}',rest) is not None and 0<abs(int(rest))<10**9,'literal QNUMBERS particle header required')
                current={'kind':'opaque','name':'QNUMBERS','pdg':int(rest),'line':n,'source_text':line,'rows':[]};sections.append(current)
                continue
            match=re.fullmatch(r'Q\s*=\s*(\S+)',rest,re.I) if rest else None
            require(not rest or match is not None,'unknown BLOCK header syntax is retained only by raw solver artifact; cannot map it')
            scale=match.group(1) if match else None
            if scale is not None:number(scale)
            current={'kind':'block','name':tokens[1].upper(),'scale':scale,'line':n,'source_text':line,'rows':[]};sections.append(current)
        elif head=='DECAY':
            require(len(tokens)==3 and re.fullmatch(r'[+-]?\d+',tokens[1]),'explicit DECAY header required')
            width=number(tokens[2]);require(width>=0,'negative total width refused')
            current={'kind':'decay','pdg':int(tokens[1]),'width':tokens[2],'line':n,'source_text':line,'rows':[]};sections.append(current)
        elif head=='XSECTION':
            current={'kind':'opaque','name':'XSECTION','line':n,'source_text':line,'rows':[]};sections.append(current)
        else:
            require(current is not None,'row outside SLHA section refused')
            row={'line':n,'source_text':line,'tokens':tokens,'kind':'opaque'}
            if current['kind']=='block' and current['name'] not in ('SPINFO','DCINFO','OBSINFO'):
                try:
                    codes=[int(x) for x in tokens[:-1]]
                    require(codes and all(re.fullmatch(r'[+-]?\d+',x) for x in tokens[:-1]),'not a numeric scalar row')
                    number(tokens[-1]);row.update(kind='scalar',codes=codes,value=tokens[-1])
                except (ValueError,OverflowError):pass
            elif current['kind']=='decay':
                require(len(tokens)>=2 and re.fullmatch(r'\d+',tokens[1]),'explicit decay-channel arity required')
                require(len(tokens)==int(tokens[1])+2,'complete declared decay-channel daughters required')
                branch=number(tokens[0]);require(0<=branch<=1,'literal branching ratio outside [0,1]')
                require(all(re.fullmatch(r'[+-]?\d+',x) for x in tokens[2:]),'literal decay daughter identities required')
                row.update(kind='channel',branching_ratio=tokens[0],daughters=[int(x) for x in tokens[2:]])
            current['rows'].append(row)
    require(sections,'empty SLHA population refused')
    diagnostics=[{'block':s['name'],**row} for s in sections if s.get('name') in ('SPINFO','DCINFO') for row in s['rows']]
    errors=[r for r in diagnostics if re.fullmatch(r'[+-]?\d+',r['tokens'][0]) and int(r['tokens'][0])==4]
    return {'schema_version':1,'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw),'original_lines':lines,'sections':sections,
        'all_info_rows':diagnostics,'native_error_rows':errors,'physics_validated':False,
        'missing_channels_are_unknown':True,'signed_masses_preserved':True}


def scalar(doc,selector):
    custody._keys(selector,('block','codes','scale'),'explicit source scalar selector')
    require(type(selector['block']) is str and selector['codes'] and all(type(x) is int for x in selector['codes']),'explicit source address required')
    block=selector['block'].upper();scale=selector['scale']
    require(scale is None or type(scale) is str,'explicit scale token or null required')
    values=[]
    for s in doc['sections']:
        if block=='DECAY':
            require(scale is None and len(selector['codes'])==1,'width selector cannot carry a scale or matrix address')
            if s['kind']=='decay' and s['pdg']==selector['codes'][0]:values.append(s['width'])
        elif s['kind']=='block' and s['name']==block and s['scale']==scale:
            values += [r['value'] for r in s['rows'] if r['kind']=='scalar' and r['codes']==selector['codes']]
    require(len(values)==1,'missing, duplicate, opaque or ambiguous source scalar: '+block+' '+str(selector['codes']))
    number(values[0]);return values[0]


def input_witness(raw,decays,library,profile_name=NAME):
    if profile_name!=NAME:
        from . import weak_scale_mssm as weak
        require(profile_name==weak.NAME,'explicit named input profile required')
        return weak.input_witness(raw,decays,library)
    doc=inventory(raw);rows=[]
    for row in profile()['input_map']:
        value=scalar(doc,{**{k:row[k] for k in ('block','codes')},'scale':None})
        rows.append({**row,'value':value})
    byname={r['parameter']:number(r['value']) for r in rows}
    require(byname['SignvS'] in (-1,1) and byname['TanBeta']>0,'explicit SignvS +/-1 and positive TanBeta required')
    require(not doc['native_error_rows'],'input SPINFO/DCINFO failure must not become a native point')
    require(scalar(doc,{'block':'FlexibleSUSY','codes':[12],'scale':None})=='0' or number(scalar(doc,{'block':'FlexibleSUSY','codes':[12],'scale':None}))==0,'force_output must explicitly be disabled')
    expected={'none':0,'collier':1,'looptools':2}[library]
    require(number(scalar(doc,{'block':'FlexibleSUSY','codes':[31],'scale':None}))==expected,'selected loop-library must match actual input setting31')
    settings=[scalar(doc,{'block':'FlexibleDecay','codes':[n],'scale':None}) for n in range(10)]
    require(number(settings[0])==(1 if decays else 0),'decay request must match actual native input')
    require(not decays or library in ('collier','looptools'),'decays require an explicitly bound Collier or LoopTools runtime')
    require(number(settings[7])==number(settings[8])==0,'HiggsTools/Lilith subprocess providers are excluded from this bounded route')
    return {'profile':NAME,'parameters':rows,'all_input':doc,'explicit_decay_settings':settings,'loop_library':library,
        'basis':profile()['conventions'],'input_defaults_selected_by_adapter':False}


def validate_extension(c):
    profile_path(c['profile'])
    from . import weak_scale_mssm as weak
    if c['profile']==weak.NAME:
        require(c['calculate_decays'] is False and c['loop_library'] is None,'released lowMSSM has no generated decay provider; unknown widths cannot become defaults')
    require(type(c['calculate_decays']) is bool,'explicit native decay choice required')
    require(c['loop_library'] is None or type(c['loop_library']) is dict,'explicit loop runtime or null required')
    if c['loop_library'] is not None:
        q=c['loop_library'];custody._keys(q,('name','include_directory','library_directory','files'),'closed loop library source/runtime')
        require(q['name'] in ('collier','looptools') and type(q['files']) is list and q['files'],'explicit bound decay loop library required')
    require(not c['calculate_decays'] or c['loop_library'] is not None,'cannot silently omit decay provider')
    custody._keys(c['input_card'],('path','sha256'),'explicit named-model input card')
    return c


def extension_inputs(c,base):
    files=[profile_path(c['profile']),custody._pin(c['input_card'],base)]
    q=c['loop_library'];name=q['name'] if q else 'none'
    input_witness(raw_file(files[-1],c['input_card']['sha256']),c['calculate_decays'],name,c['profile'])
    if q:
        pinned=[custody._pin(row,base) for row in q['files']]
        for role in ('include_directory','library_directory'):
            directory=custody._regular(q[role],base,directory=True)
            require(all(not p.is_symlink() for p in directory.rglob('*')),'loop-library aliases need explicit prior regularization')
            members=sorted(p.resolve() for p in directory.rglob('*') if p.is_file())
            require(members and set(members)<=set(pinned),'complete selected loop header/library directories must be pinned')
        files+=pinned
    return files


def source_contract(doc,profile_name=NAME):
    p=profile(profile_name)
    require(doc['baseline_kind']=='pregenerated-spectrum' and doc['files']==p['files'] and doc['modes']==p['modes'],'entire released framework plus generated NMSSM files/modes must match the named source profile')


def write_exact(path,doc):
    raw=(json.dumps(doc,indent=2,allow_nan=False)+'\n').encode();Path(path).write_bytes(raw)
    require(Path(path).read_bytes()==raw,'generated spectrum metadata altered during write')
    return {'path':str(Path(path).resolve()),'sha256':hashlib.sha256(raw).hexdigest()}


def map_card(spectrum,input_doc,external_rows,mapping):
    custody._keys(mapping,('schema_version','profile','basis','source_evidence','rows'),'explicit spectrum-to-UFO convention map')
    require(type(mapping['schema_version']) is int and mapping['schema_version']==2,'named source map schema2 required')
    profile_path(mapping['profile'])
    require(type(mapping['basis']) is str and mapping['basis'].strip() and mapping['source_evidence'],'explicit source-backed basis/convention evidence required')
    require(not spectrum['native_error_rows'],'native error return cannot form an event point')
    require(type(mapping['rows']) is list and 1<=len(mapping['rows'])<=10000,'bounded complete external mapping population required')
    expected={(r['block'].lower(),tuple(r['codes'])):r['name'] for r in external_rows}
    require(len(expected)==len(external_rows),'full unique external UFO population required')
    values={};delivered=[]
    for r in mapping['rows']:
        custody._keys(r,('parameter','block','codes','origin','selector','operation','source_unit','target_unit','convention'),'explicit card mapping row')
        key=(r['block'].lower(),tuple(r['codes']))
        require(key not in values and key in expected and expected[key]==r['parameter'],'full unique source UFO external address/name map required')
        require(r['operation']=='identity','only an explicitly requested identity operation is supported; nonidentity conversion refuses')
        require(type(r['source_unit']) is str and r['source_unit'].strip() and type(r['target_unit']) is str and r['source_unit']==r['target_unit'],'identity source/target units must be explicit and equal; no unit conversion')
        require(r['origin'] in ('spectrum','input') and type(r['convention']) is str and r['convention'].strip(),'unverified source convention annotation required')
        value=scalar(spectrum if r['origin']=='spectrum' else input_doc,r['selector'])
        require(key[0]!='decay' or (r['origin']=='spectrum' and r['selector']['block'].upper()=='DECAY' and number(value)>=0),'every event width must be an actual returned total width, never an input/default/branch sum')
        values[key]=value;delivered.append({**r,'value':value})
    require(set(values)==set(expected),'complete external population must be mapped, no inferred default values')
    lines=[];block=None
    for (name,codes),value in sorted(values.items()):
        if name=='decay':lines.append('DECAY '+str(codes[0])+' '+value)
        else:
            if name!=block:lines.append('BLOCK '+name.upper());block=name
            lines.append(' '.join(map(str,codes))+' '+value)
    raw=('\n'.join(lines)+'\n').encode()
    from ravel.validation.model_tool_witness import card_values
    actual=card_values(raw.decode())
    require(set(actual)==set(values) and all(actual[k]==float(number(v)) for k,v in values.items()),'full emitted external card changed scalar values')
    return raw,delivered


def _sources(request,inputs,profile_name=NAME):
    """Actual current role/custody gates, using the existing call-scoped sessions."""
    from ravel.workflow import task_completion, execution, science
    sr,_=task_completion._accepted_review(request['spectrum_run'],SCOPE,inputs)
    dr,_=task_completion._accepted_review(request['derivation_run'],'model_source_derivation',inputs)
    spec=science.execution_spec(sr)
    require(spec['mode']=='generated-spectrum','actual spectrum mode required')
    from . import generated_spectrum
    path,c=generated_spectrum._load(spec['task'],sr)
    from . import spheno_mssm
    require(c['schema_version']==2 or spheno_mssm.selected(c),'named-model spectrum receipt required, no CMSSM relabeling')
    stage=execution.load_execution(sr)['stages']['science'];require(len(stage['outputs'])==1,'one closed spectrum output required')
    out=custody._regular(stage['outputs'][0],sr,directory=True)
    resultpath=out/'generated-spectrum.json';inputs.capture(resultpath);result=custody._read(resultpath)
    require(c['profile']==profile_name and result['status']=='passed' and result['model_profile']==profile_name and result['physics_validated'] is False,'passed exact named-model transport result required')
    require(result['configuration']=={'path':str(path),'sha256':custody._hash(path)},'result must bind the executed config')
    # API pins use path/sha256; task_completion additionally requires size.
    sp=result['generated_slha'];raw,p=inputs.file({'path':sp['path'],'sha256':sp['sha256'],'size':sp['bytes']})
    require(p==out/(layout(c)['model']+'.slha'),'spectrum raw return must be the actual receipt output member')
    ip=custody._pin(c['input_card'],path.parent);inputs.capture(ip)
    returned=inventory(raw);original=inventory(raw_file(ip,c['input_card']['sha256']))
    require(result['full_slha']==returned and result['input_witness']['all_input']==original,'complete raw return/input census differs from actual result')
    return sr,dr,returned,original


def point_handoff(request,*,base_dir,output_dir):
    """Join two actual accepted studies to a NEW explicit card, never alter either."""
    custody._keys(request,('schema_version','spectrum_run','derivation_run','mapping'),'spectrum point handoff request')
    require(type(request['schema_version']) is int and request['schema_version']==1,'point handoff schema1 required')
    from ravel.workflow import task_completion
    from . import model_derivation_bridge
    observed=task_completion._Inputs(base_dir);out=Path(output_dir).expanduser().absolute();emitted=[]
    try:
        mpath=custody._pin(request['mapping'],base_dir);observed.capture(mpath);mapping=json.loads(raw_file(mpath,request['mapping']['sha256']))
        profile_path(mapping['profile'])
        sr,dr,spectrum,input_doc=_sources(request,observed,mapping['profile'])
        for pin in mapping['source_evidence']:observed.capture(custody._pin(pin,mpath.parent))
        require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)) and
                not any(out==r or out.is_relative_to(r) or r.is_relative_to(out) for r in (sr,dr)),'fresh independent point output required')
        require(not any(Path(p).is_relative_to(out) for p in observed.pins),'point output may not contain original inputs')
        out.mkdir(parents=True)
        qualified=model_derivation_bridge.qualified_handoff(dr,out/'qualified-ufo.json');emitted.append(observed.capture(out/'qualified-ufo.json'))
        parameters=custody._regular('parameters.py',Path(qualified['ufo']));observed.capture(parameters)
        _,external=model_derivation_bridge.literal_external_card(raw_file(parameters).decode())
        card,rows=map_card(spectrum,input_doc,external,mapping)
        target=out/'param_card.dat';target.write_bytes(card);require(target.read_bytes()==card,'point card changed during delivery');cp={'path':str(target),'sha256':hashlib.sha256(card).hexdigest()};emitted.append(observed.capture(target))
        doc={'schema_version':1,'kind':'named-spectrum-qualified-UFO-point','profile':mapping['profile'],'spectrum_run':str(sr),'derivation_run':str(dr),'qualified_source':{'path':str(out/'qualified-ufo.json'),'sha256':custody._hash(out/'qualified-ufo.json')},
             'model_tree':{'root':qualified['ufo'],'manifest':qualified['ufo_manifest']},'parameter_card':cp,'mapping':request['mapping'],'mapped_external_rows':rows,
             'spectrum_sha256':spectrum['raw_sha256'],'full_return':spectrum,'original_input':input_doc,'input_pins':list(observed.pins.values()),'physics_validated':False,'execution_authorized':False,
             'convention_scope':'Explicit complete external address/scale identity mapping; no inferred basis conversion, spectrum accuracy, coupling amplitude equality or physical model certificate.'}
        pending=out/'point-handoff.pending.json';write_exact(pending,doc);pendingpin=observed.capture(pending)
        observed.finish()
        # Preserve initial generated commitments; do not recapture to hide drift.
        require(all(custody._hash(Path(p['path']))==p['sha256'] for p in emitted+[pendingpin]),'generated point outputs changed before commitment')
        pending.rename(out/'point-handoff.json')
        try:
            require(custody._hash(out/'point-handoff.json')==pendingpin['sha256'],'point handoff commitment changed')
            observed.pins.pop(pendingpin['path']);observed.identities.pop(pendingpin['path']);observed.finish()
        except Exception:
            (out/'point-handoff.json').rename(out/'failed-point-handoff.json');raise
        return doc
    finally:observed.close()


def origin_inputs(pin,base,card_pin,model_tree):
    """Downstream native configs bind this whole source join, not just the card."""
    from ravel.workflow import task_completion
    observed=task_completion._Inputs(base)
    try:
        path=custody._pin(pin,base);observed.capture(path);doc=json.loads(raw_file(path,pin['sha256']))
        profile_path(doc['profile'])
        require(doc['kind']=='named-spectrum-qualified-UFO-point' and doc['parameter_card']==card_pin and doc['model_tree']==model_tree,'spectrum origin differs from downstream full model/card')
        req={'spectrum_run':doc['spectrum_run'],'derivation_run':doc['derivation_run']}
        sr,dr,spectrum,input_doc=_sources(req,observed,doc['profile'])
        for p in doc['input_pins']:observed.file(p)
        qualifiedpath=custody._pin(doc['qualified_source'],path.parent);observed.capture(qualifiedpath);qualified=json.loads(raw_file(qualifiedpath,doc['qualified_source']['sha256']))
        # Rebind the historical actual export rather than trusting a copied label.
        from ravel.workflow import execution
        stage=execution.load_execution(dr)['stages']['science'];ufoout=custody._regular(stage['outputs'][0],dr,directory=True)
        candidate=custody._read(ufoout/'model-tool-handoff-candidate.json')
        require(all(qualified.get(k)==v for k,v in candidate.items()) and qualified['qualified_for_scoped_reuse'] is True,'qualified UFO origin changed')
        require(doc['model_tree']=={'root':candidate['ufo'],'manifest':candidate['ufo_manifest']},'spectrum model tree differs from actual qualified export')
        require(custody.source_tree(Path(candidate['ufo']))==custody._read(custody._pin(candidate['ufo_manifest'],ufoout)),'actual qualified source changed')
        parameters=custody._regular('parameters.py',Path(candidate['ufo']));observed.capture(parameters)
        from . import model_derivation_bridge
        _,external=model_derivation_bridge.literal_external_card(raw_file(parameters).decode())
        mpath=custody._pin(doc['mapping'],path.parent);observed.capture(mpath);mapping=json.loads(raw_file(mpath,doc['mapping']['sha256']))
        for p in mapping['source_evidence']:observed.capture(custody._pin(p,mpath.parent))
        require(mapping['profile']==doc['profile'],'mapping profile must match actual accepted source')
        raw,rows=map_card(spectrum,input_doc,external,mapping);cp=custody._pin(card_pin,base);observed.capture(cp)
        require(raw_file(cp,card_pin['sha256'])==raw and doc['mapped_external_rows']==rows and doc['full_return']==spectrum and doc['original_input']==input_doc,'complete point data does not reproduce the accepted source mapping')
        observed.finish();return sorted(Path(p) for p in observed.pins)
    finally:observed.close()
