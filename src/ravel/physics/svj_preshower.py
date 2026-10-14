"""Opt-in SVJ preparation and original runner phase integration.

Authenticated scientific source/build declarations are inputs, not native or
physics certification. The old generation path is selected when the field is absent.
"""
import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from . import model_tool_bridge as bridge, model_event_weights as weights
from .model_event_weights import require
from . import svj_lhe_transform as transform
from ravel.workflow.state_io import _unique

MODE = 'svj_dark_flavour_absolute_v1'
FRAGMENT_SHA = '4bb332d003d2f5265a5cd91b6524ec3f93e6342f827be2b30076cd11f30c0ca2'
CONTRACT_SHA = '83a0490a8ec1c156def23afd92fc58c2a083f5f8853433be9692b21de31f5010'
INTERFACE_SHA = '590c8ea4cc7643358a64e2d7e0113f17403cb72a274748dda44950fdc3e3c414'
ARCHIVE_SHA = '1a7a62e96207701f9a8a44fec01426b7f474b580ba2c4fbb82ecd0d83fcea332'
BINDINGS = [dict(pdg=pdg,ufo_name=name,mass_parameter=mass,width_parameter='ZERO',spin=2,color=1,charge='0')
            for pdg,name,mass in [(49001011,'gv11','Mgv11'),(49001012,'gv12','Mgv12'),
                                  (49001013,'gv21','Mgv21'),(49001014,'gv22','Mgv22')]]
MG_SOURCES = {
 'madgraph/interface/madgraph_interface.py':'04c293c5e478b5ce525fbc625bdc8bf81b70ad9c52c8f467df4a91d1561adada',
 'madgraph/interface/madevent_interface.py':'0f59f5a9300985fabc5da3156e42a2c6dc080b632fb94a50016284354cd402d8',
 'madgraph/interface/common_run_interface.py':'0e915210fffd2fddead6b36ed06390d528e378664daba7555bce3d86c1ba1d98',
 'madgraph/interface/extended_cmd.py':'133a0109fba0958612a7ab1fb7f13624073833c2bea0426453877e7d4367c7ee',
 'madgraph/various/banner.py':'17b4b0ed0b13afa013a94e6715c47a4fb1552ee160347cd3b9db644fb89c4ee9',
}


def _pin_spec(x):
    require(type(x) is dict and set(x) in ({'path','sha256'},{'path','sha256','size'}),
            'exact scientific file pin required')
    require(type(x['path']) is str and x['path'] and type(x['sha256']) is str and
            re.fullmatch('[0-9a-f]{64}',x['sha256']), 'literal scientific pin required')
    if 'size' in x: require(type(x['size']) is int and x['size'] >= 0, 'literal pinned size required')


def _pin(x,base):
    _pin_spec(x)
    p=bridge._pin({k:x[k] for k in ('path','sha256')},base)
    if 'size' in x: require(p.stat().st_size==x['size'],'scientific pinned size changed')
    return p


def _doc(x,base):
    from .model_events import authenticated_text
    p=_pin(x,base)
    require(p.stat().st_size<=8*1024**2,'finite scientific declaration exceeds 8MiB')
    def bad(x): raise ValueError('nonfinite scientific declaration')
    return p,json.loads(authenticated_text(p,x['sha256']),object_pairs_hook=_unique,parse_constant=bad)


def validate(c):
    x=c['pre_shower_lhe_transform']
    bridge._keys(x,('schema_version','mode','source_fragment','source_particle_bindings',
        'mapped_pdgs_absent_from_model','target_pythia_pdg','mass_gev','normalization',
        'interface','shower_stream_census','maximum_event_bytes','scientific_equivalence_claim'), 'SVJ pre-shower contract')
    require(type(x['schema_version']) is int and x['schema_version']==1 and x['mode']==MODE,
            'fixed source SVJ particle/absolute representation mode required')
    _pin_spec(x['source_fragment']);require(x['source_fragment']['sha256']==FRAGMENT_SHA,'exact original SVJ fragment required')
    require(json.dumps(x['source_particle_bindings'],sort_keys=True,allow_nan=False)==json.dumps(BINDINGS,sort_keys=True) and
            type(x['mapped_pdgs_absent_from_model']) is list and all(type(v) is int for v in x['mapped_pdgs_absent_from_model']) and
            x['mapped_pdgs_absent_from_model']==[49001010],
            'complete original four-particle plus inactive-fifth inventory required')
    require(type(x['target_pythia_pdg']) is int and x['target_pythia_pdg']==transform.TARGET and
            type(x['mass_gev']) is str and x['mass_gev']=='10','source-defined original target/mass required')
    n=x['normalization'];bridge._keys(n,('mode','input_strategy','output_strategy','source_contract'),'SVJ weight representation')
    require(n['mode']=='mg_sum_to_absolute_average_v1' and type(n['input_strategy']) is int and n['input_strategy']==-3 and
            type(n['output_strategy']) is int and n['output_strategy']==-4,'explicit original sum to absolute-average representation required')
    _pin_spec(n['source_contract']);require(n['source_contract']['sha256']==CONTRACT_SHA,'exact source-derived all-weight law required')
    i=x['interface'];bridge._keys(i,('source_sha256','archive_sha256','build_evidence'),'selected released SVJ interface')
    require(i['source_sha256']==INTERFACE_SHA and i['archive_sha256']==ARCHIVE_SHA,'exact released V1.3 interface selected source required')
    _pin_spec(i['build_evidence']);_pin_spec(x['shower_stream_census'])
    require(type(x['maximum_event_bytes']) is int and 1<=x['maximum_event_bytes']<=8*1024**2,'bounded prospective event bytes required')
    require(x['scientific_equivalence_claim'] is False,'source transport cannot claim scientific equivalence')
    require(c['generation']['order']=='LO' and c['generation']['scheme']=='mlm' and c['shower']['backend']=='PYTHIA8' and
            c['decay']['mode']=='OFF' and c['reweight']['mode']=='OFF','this source recipe requires complete LO MLM/PYTHIA8 hard generation with native decay/ME reweight off')
    require('operative_seed_observation' in c,'explicit original hard-stage operative seed observation required')
    require(c['outputs']['lhe_relative']=='Events/ravel/unweighted_events.lhe.gz','released SVJ reentry consumes fixed complete gzip hard endpoint')
    return x


def _cut_tag(value):
    d=weights.number(value)
    require(d>0 and math_finite(d),'finite positive matching cut required')
    # Released named branch uses fixed setprecision(3) on native doubles.
    return format(float(d),'.3f')


def math_finite(d):
    import math
    return math.isfinite(float(d)) and (d==0 or float(d)!=0)


def stream_document(c,base):
    x=validate(c);p,d=_doc(x['shower_stream_census'],base)
    bridge._keys(d,('schema_version','mode','cut_values_gev','full_cut_variation','streams'),'complete shower stream census')
    require(type(d['schema_version']) is int and d['schema_version']==1 and d['mode']=='mg_py8_v1_3_hepmc2hack_full_streams','explicit selected native full-stream mode required')
    cuts=d['cut_values_gev'];require(type(cuts) is list and cuts and len(cuts)<=128 and
        all(type(v) is str and len(v)<=64 for v in cuts),'finite complete declared cut population required')
    numeric=[weights.number(v) for v in cuts]
    require(len(set(numeric))==len(cuts) and len({_cut_tag(v) for v in cuts})==len(cuts),
            'duplicate or native fixed-three-decimal cut-tag collision')
    require(type(d['full_cut_variation']) is bool,'original literal full/reduced cut cross required')
    rows=d['streams'];require(type(rows) is list and 1<=len(rows)<=16384,'finite complete shower name population required')
    ids=[i for g in c['weights']['groups'] for i in g['ids']]
    names=[];subjects=[];interfaces=[]
    for row in rows:
        bridge._keys(row,('hepmc_name','kind','lhe_id','cut_gev','units','source'),'complete returned stream')
        name=row['hepmc_name'];require(type(name) is str and name and len(name)<=512 and not any(z in name for z in ('\x00','\n','\r')), 'literal complete native stream name required')
        names.append(name);_pin_spec(row['source']);subjects.append(_pin(row['source'],base))
        require(row['kind'] in ('interface_nominal','interface_lhe','converter'),'explicit source stream kind required')
        require(type(row['units']) is str and row['units'] and len(row['units'])<=64,'explicit source units or unknown required')
        if row['kind']=='converter':
            require(row['lhe_id'] is None and row['cut_gev'] is None,'converter quantities cannot be implicit LHE/nominal normalization streams')
        else:
            require(row['units']=='pb' and type(row['cut_gev']) is str and weights.number(row['cut_gev']) in numeric,
                    'interface stream requires declared pb/cut representation')
            require(row['lhe_id'] is None if row['kind']=='interface_nominal' else row['lhe_id'] in ids,
                    'interface stream original literal identity differs')
            interfaces.append((row['kind'],row['lhe_id'],weights.number(row['cut_gev'])))
    require(len(names)==len(set(names)),'duplicate/colliding interface or converter stream name')
    expected=[('interface_nominal',None,k) for k in numeric]
    expected += [('interface_lhe',i,k) for k in (numeric if d['full_cut_variation'] else numeric[:1]) for i in ids]
    require(len(interfaces)==len(expected) and set(interfaces)==set(expected),'complete original full/reduced cut x weight population differs')
    selected=c['outputs']['shower_weight_map']
    selected_cut=None
    for row in selected:
        found=[r for r in rows if r['hepmc_name']==row['hepmc_name'] and r['lhe_id']==row['lhe_id'] and
               r['kind']==('interface_nominal' if row['lhe_id'] is None else 'interface_lhe')]
        require(len(found)==1,'selected original normalization map is absent or ambiguous in full census')
        cut=weights.number(found[0]['cut_gev'])
        if selected_cut is None:selected_cut=cut
        require(cut==selected_cut,'selected original map must share one explicit matching cut')
    return d,[p,*subjects]


def _model_bindings(x,modelroot,parameter_raw):
    from . import model_event_parameters as projection
    from .model_events import authenticated_text,parameter_values
    particles=projection._declarations(authenticated_text(Path(modelroot)/'particles.py'),'Particle')
    parameters=projection._declarations(authenticated_text(Path(modelroot)/'parameters.py'),'Parameter')
    all_pdgs={int(projection._literal(row['fields']['pdg_code'])) for row in particles.values()}
    require(not any(abs(pdg)==49001010 for pdg in all_pdgs),'inactive mapped PDG is present in the supplied model')
    card=parameter_values(parameter_raw)
    for expected in BINDINGS:
        row=particles.get(expected['ufo_name']);require(row is not None,'original mapped UFO particle missing')
        f=row['fields'];pdg=expected['pdg']
        for key,value in [('pdg_code',pdg),('spin',2),('color',1)]:require(projection._literal(f[key])==value,'mapped UFO declaration differs: '+key)
        require(Decimal(str(projection._literal(f['charge'])))==0,'source neutral mapped particle required')
        for key,name in [('mass',expected['mass_parameter']),('width','ZERO')]:
            node=f[key];require(isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and
                node.value.id=='Param' and node.attr==name,'exact mapped source mass/width reference required')
        mass=parameters.get(expected['mass_parameter']);require(mass is not None,'mapped mass parameter missing')
        q=mass['fields'];require(projection._literal(q['nature'])=='external' and projection._literal(q['type'])=='real' and
            projection._literal(q['lhablock']).lower()=='mass' and projection._literal(q['lhacode'])==[pdg],
            'mapped mass must be original literal external MASS address')
        require(card.get(('mass',(pdg,)))==Decimal(x['mass_gev']),'operative mapped source masses differ from target')
        # A same-PDG new declaration is not an antiparticle alias.
        decls={id(r) for r in particles.values() if abs(int(projection._literal(r['fields']['pdg_code'])))==pdg}
        require(len(decls)==1,'duplicate or conflicting mapped particle declaration')
    return [Path(modelroot)/'particles.py',Path(modelroot)/'parameters.py']


def validate_cards(c,texts,census):
    from . import model_events as m,pythia_cards
    x=validate(c)
    run=m.assignments(texts['run']);require(m.literal(run.get('event_norm',''))=='sum','original source sum card required')
    py=pythia_cards.parse(texts['pythia'])
    m.matches(py['settings'],{'HEPMCoutput:scaling':1000000000,'4900101:m0':10,'4900101:mWidth':Decimal('.2')},'explicit source SVJ target/normalization')
    settings=py['settings']
    actual=[weights.number(settings['jetmatching:qcut'])]
    if 'syscalc:qcutlist' in settings:
        # The original PY8Card formatter emits Settings vector syntax: commas,
        # not a Python list. No native 'auto' value or silent cut expansion.
        values=settings['syscalc:qcutlist'].split(',')
        require(1<=len(values)<=128 and all(v.strip() for v in values),'literal complete native SysCalc comma vector required')
        parsed=[weights.number(v.strip()) for v in values]
        require(all(math_finite(v) for v in parsed),'finite native SysCalc cut vector required')
        actual += [v for v in parsed if v>0]
    require(actual==list(map(weights.number,census['cut_values_gev'])),'source card cut population differs from complete census')
    original_full=m.literal(settings.get('syscalc:fullcutvariation','off'))
    require(type(original_full) is bool and original_full==census['full_cut_variation'],
            'declared original full/reduced cut setting differs; no automatic expansion')
    return py


def inputs(c,base,*,modelroot,mgroot,texts,compact=False):
    x=validate(c);files=[_pin(x['source_fragment'],base),_pin(x['normalization']['source_contract'],base)]
    p,law=_doc(x['normalization']['source_contract'],base)
    require(law.get('kind')=='proposed_svj_absolute_weight_representation_contract','source all-weight declaration differs')
    p,build=_doc(x['interface']['build_evidence'],base)
    bridge._keys(build,('schema_version','kind','source','binary','compile_definitions','build_record','dependencies'),'source-declared named-output build')
    require(type(build['schema_version']) is int and build['schema_version']==1 and build['kind']=='source_declared_mg_py8_named_output_build' and
            build['compile_definitions']==['HEPMC2HACK'],'explicit named-output build claim required')
    prefix=bridge._regular(c['runtime']['options']['mg5amc_py8_interface_path'],base,directory=True)
    source=_pin(build['source'],base);binary=_pin(build['binary'],base)
    require(source==prefix/'MG5aMC_PY8_interface.cc' and build['source']['sha256']==INTERFACE_SHA and
            binary==prefix/'MG5aMC_PY8_interface','exact source-bound existing interface endpoints required')
    dependencies=build['dependencies'];require(type(dependencies) is list and dependencies and len(dependencies)<=16384,'complete build dependency claim required')
    expanded=[]
    for dep in c['runtime']['dependencies']:expanded+=bridge._tree(dep['tree'],base)[2]
    covered=set(expanded)
    members=[source,binary,*[_pin(v,base) for v in dependencies]]
    require(len(members)==len(set(members)) and set(members)<=covered,'every actual source/binary/build dependency must be in existing complete native manifests')
    files += [p,_pin(build['build_record'],base)]
    if not compact:files+=members
    census,subjects=stream_document(c,base);files+=subjects
    validate_cards(c,texts,census)
    if not compact:
        files+=_model_bindings(x,modelroot,texts['parameter'])
        from .model_events import authenticated_text
        for relative,digest in MG_SOURCES.items():
            q=Path(mgroot)/relative;authenticated_text(q,digest);files.append(q)
    return sorted(set(files))


def hard_launch(c,launch):
    validate(c)
    require(launch.count('shower=PYTHIA8\n')==1,'one admitted hard-phase shower switch required')
    return launch.replace('shower=PYTHIA8\n','shower=OFF\n',1)


def reentry_script(process,c):
    process=Path(process).absolute()
    require(not re.search(r'[\s;\'"\\]',str(process)),'literal private reentry path required')
    settings=['set automatic_html_opening False --no_save','set run_mode 0 --no_save','set nb_core 1 --no_save']
    # Released interactive launch passes self.options into its child. Reapply
    # the original admitted runtime options in this fresh original bin session.
    settings += ['set '+key+' '+str(value)+' --no_save' for key,value in c['runtime']['options'].items() if value is not None]
    return '\n'.join([*settings,'launch '+str(process)+' -i','set delphes_path None --no_save',
        'pythia8 ravel --no_default --laststep=pythia8'])+'\n'


def derived_run_card(raw):
    from .model_events import assignments,literal
    before=assignments(raw,native_lo_empty_strings=True)
    require(literal(before.get('event_norm',''))=='sum','original hard ending sum field required')
    rows=[]
    for match in re.finditer(r'(?m)^([^\r\n]*?)(\r?\n|$)',raw):
        line=match.group(1);operative=line.split('#',1)[0].split('!',1)[0]
        if '=' not in operative:continue
        value,key=map(str.strip,operative.split('=',1))
        if key.lower()=='event_norm':
            a=match.start()+line.index(value);rows.append((a,a+len(value),value))
    require(len(rows)==1,'one unique operative event_norm token required')
    a,b,value=rows[0];require(literal(value)=='sum','source sum normalization token required')
    replacement= value[0]+'average'+value[-1] if value[0:1] in ('\"',"'") and value[-1:]==value[0] else 'average'
    result=raw[:a]+replacement+raw[b:]
    after=assignments(result,native_lo_empty_strings=True)
    require(after==dict(before,event_norm=replacement),'unapproved hard ending run-card field changed')
    return result,{'original_start':a,'original_end':b,'original_token':value,'derived_token':replacement,
                   'original_sha256':hashlib.sha256(raw.encode()).hexdigest(),'derived_sha256':hashlib.sha256(result.encode()).hexdigest(),
                   'complete_field_count':len(before),'physical_law_change':'explicit full-N weight representation; original generation prescription retained'}


def _snapshot(pin,out,name):
    origin=Path(pin['path']);require(transform.pin(origin)==pin,'consumed hard source changed before snapshot')
    target=out/name
    with origin.open('rb') as a,target.open('xb') as b:shutil.copyfileobj(a,b,65536)
    copied=transform.pin(target)
    require(copied['sha256']==pin['sha256'] and copied['size']==pin['size'] and transform.pin(origin)==pin,'hard subject changed during retained snapshot')
    return {'source_origin':pin,'retained':copied}


def _components(raw):
    from . import model_event_seed as seed
    header=seed._header(raw,banner=True)
    body=header[header.index(b'<header>')+8:header.rindex(b'</header>')]
    result={};cursor=0
    while body[cursor:].strip():
        found=re.match(rb'\s*<([A-Za-z][A-Za-z0-9_]*)>(.*?)</\1>',body[cursor:],re.S)
        require(found is not None,'complete released native banner section population required')
        name=found[1].decode();require(name not in result,'duplicate native banner section')
        result[name]=found[2].strip();cursor+=found.end()
    return result


def observe_banner(hard_banner,final_banner,cmd_card,*,mlm=True):
    from . import model_event_seed as seed
    old,_=seed._read(hard_banner);new,new_pin=seed._read(final_banner);cmd,cmd_pin=seed._read(cmd_card)
    a,b=_components(old),_components(new)
    require(set(b)==set(a)|{'MGPythiaCard'},'native shower banner added/omitted foreign section')
    for name,value in a.items():
        if name=='MGPythiaCard':continue
        if name=='MGGenerationInfo' and mlm:
            require(b[name].startswith(value+b'\n'),'original generation info changed')
            addition=b[name][len(value)+1:]
            match=re.fullmatch(rb'#  Matched Integrated weight \(pb\)  :  ([^\r\n]+)',addition)
            require(match is not None,'only source-supported matched-weight line may be added')
            weights.number(match[1].decode())
        else:require(b[name]==value,'original native generation banner component changed: '+name)
    # Banner.write applies its declared CDATA framing when command text contains < or @.
    expected=cmd.strip()
    if b'<' in expected or b'@' in expected:expected=b'<![CDATA[\n'+expected+b'\n]]>'
    require(b['MGPythiaCard']==expected,'complete native Pythia command card differs from banner')
    return {'hard_banner':transform.pin(hard_banner),'final_native_banner':new_pin,'actual_native_command_card':cmd_pin,
            'preserved_original_sections':sorted(k for k in a if k!='MGPythiaCard'),
            'allowed_native_additions':['MGPythiaCard','MGGenerationInfo matched integrated weight'],
            'generation_header_rewritten':False,'native_numerical_equivalence':False}


def _api_rows(split):
    from . import svj_mg_reentry as driver
    p=Path(split['native_api_journal']['path'])
    require(transform.pin(p)==split['native_api_journal'],'native API journal changed')
    rows=[json.loads(line,object_pairs_hook=_unique) for line in p.read_text().splitlines()]
    require(len(rows)==2 and rows[0].get('kind')=='native_original_card_reload' and
            rows[1].get('kind')=='native_reentry_dispatch_complete' and rows[1].get('calls')==1,
            'complete one-call original native API observation required')
    request=split['native_api_request'];actual=rows[0]
    require(actual['mode']==driver.MODE and actual['process']==request['process'] and
            actual['driver_sha256']==request['driver_sha256'] and actual['operative_run_card']==request['operative_run_card'],
            'native API observation belongs to foreign source/card/process')
    require(actual['loaded_source']==split['native_reentry_method_source']['path'] and
            rows[1]['original_bin_dispatch']==split['native_original_bin_source']['path'],
            'actual loaded original method/bin source identity differs')
    require(actual['original_arguments_before']==['ravel','--laststep=pythia8'] and
            actual['original_arguments_after']==['ravel','--laststep=pythia8','pythia8'] and actual['original_result'] is None,
            'original check argument mutations/result differ from one intended invocation')
    before,after=actual['before_native_fields'],actual['after_native_fields']
    require(set(before)==set(after) and before.get('event_norm')=='sum' and after.get('event_norm')=='average' and
            before.get('iseed')==request['hard_seed'] and after.get('iseed')==0 and
            before.get('nevents')==after.get('nevents')==request['complete_N'] and
            all(after[k]==v for k,v in before.items() if k not in ('event_norm','iseed')),
            'complete native loaded card values differ beyond declared representation/reset')
    require(rows[1]['script']==request['script'] and rows[1]['driver_sha256']==request['driver_sha256'] and
            all(row.get('scientific_acceptance') is False for row in rows), 'native API dispatch/source scope differs')
    return rows


def execute_split(request,out,*,texts,process_identity,observations,journal,command):
    """Use only the existing approved _command phases; no optional external import."""
    from . import model_events as m,model_event_seed as seed,model_event_commitment as commitment,svj_mg_reentry as driver
    c=request['config'];x=validate(c);out=Path(out);process=Path(request['process']);mg=Path(request['madgraph'])
    base=Path(request['source_base'])
    census,_=stream_document(c,base);validate_cards(c,texts,census)
    _model_bindings(x,Path(request['model']),texts['parameter'])
    observations.append(m._command([*command,str(out/'launch.mg5')],mg,out,journal,'hard-generate'))
    m._copied_source_custody(request,out,'after-hard-generate')
    observed={name:m.authenticated_text(process/'Cards'/m.CARD_NAMES[name]) for name in request['card_paths'] if name!='process'}
    hard_commitment=commitment.snapshot(process)
    artifacts=[{k:row[k] for k in ('path','sha256','size')} for row in hard_commitment['files']]
    bridge._write(out/'hard-generated-member-commitment.json',hard_commitment)
    hard_seed=seed.observe(c,texts['run'],observed['run'],supplied_process=texts['process'],mgroot=mg,
        model_path=Path(request['model']),process_root=process,process_identity=process_identity,
        stdout_path=out/'hard-generate-stdout.log',artifacts=artifacts)
    bridge._write(out/'hard-stage-operative-seed-observation.json',hard_seed)
    lhe=bridge._regular(str(process/c['outputs']['lhe_relative']),process)
    conversion=transform.transform(lhe,out/'preshower-transform',expected_events=c['generation']['events'],
        expected_groups=c['weights']['groups'],maximum_bytes=c['outputs']['max_decoded_lhe_bytes'],
        maximum_event_bytes=x['maximum_event_bytes'],require_detailed=True)
    retained=out/'hard-stage-subject';retained.mkdir()
    subjects=[]
    for field in ('banner','native_stdout','ending_mutable_card','native_parameter_card','native_modern_process_card',
                  'native_legacy_process_card','generation_identity_journal'):
        subjects.append(dict(role=field,**_snapshot(hard_seed[field],retained,field+'.raw')))
    subjects.append({'role':'embedded_lhe','source_origin':hard_seed['embedded_lhe'],'retained':conversion['raw_hard']})
    subjects.append(dict(role='observation_record',**_snapshot(transform.pin(out/'hard-stage-operative-seed-observation.json'),retained,'observation.json')))
    subjects.append(dict(role='complete_hard_commitment',**_snapshot(transform.pin(out/'hard-generated-member-commitment.json'),retained,'complete-member-commitment.json')))
    # The original observation still authenticates actual old endpoints right
    # before the explicitly authorized operative replacements below.
    seed.ending_custody(hard_seed);commitment.verify(hard_commitment,process)
    derive,card_change=derived_run_card(observed['run'])
    derived_card=out/'derived-operative-run-card.dat'
    with derived_card.open('xb') as f:f.write(derive.encode());f.flush();os.fsync(f.fileno())
    original_card=process/'Cards/run_card.dat'
    require(transform.pin(original_card)==hard_seed['ending_mutable_card'],'actual hard ending card changed before lowering')
    pending_card=original_card.with_name('run_card.dat.svj-pending')
    with pending_card.open('xb') as f:f.write(derive.encode());f.flush();os.fsync(f.fileno())
    require(pending_card.read_bytes()==derived_card.read_bytes(),'operative card differs from explicit derived representation')
    pending_lhe=lhe.with_name('unweighted_events.lhe.gz.svj-pending')
    with Path(conversion['derived_shower_input']['path']).open('rb') as a,pending_lhe.open('xb') as b:shutil.copyfileobj(a,b,65536)
    require(transform.pin(lhe)==conversion['source_origin'] and
            transform.pin(pending_lhe)['sha256']==conversion['derived_shower_input']['sha256'],
            'hard/derived operative LHE commitment changed before installation')
    transform.verify(conversion);seed.ending_custody(hard_seed)
    os.replace(pending_card,original_card);os.replace(pending_lhe,lhe)
    operative_lhe=transform.pin(lhe);operative_card=transform.pin(original_card)
    require(operative_lhe['sha256']==conversion['derived_shower_input']['sha256'] and
            operative_card['sha256']==transform.pin(derived_card)['sha256'],'installed operative representation differs')
    script=out/'shower-reentry.mg5';script.write_text(reentry_script(process,c))
    native_driver=out/'native-svj-reentry.py'
    source_driver=Path(driver.__file__)
    native_driver.write_bytes(m.authenticated_text(source_driver,request['svj_reentry_driver_sha256']).encode())
    api_request={'schema_version':1,'mode':driver.MODE,'script':transform.pin(script),'process':str(process),
        'operative_run_card':operative_card,'driver_sha256':transform.pin(native_driver)['sha256'],
        'hard_seed':c['generation']['seed'],'complete_N':c['generation']['events']}
    api_file=out/'native-svj-reentry-request.json';bridge._write(api_file,api_request)
    api_journal=out/'native-svj-reentry-observation.jsonl'
    m._copied_source_custody(request,out,'before-shower-reentry')
    observations.append(m._command([request['python'],'-O','-I','-B',str(native_driver),str(mg),str(api_file),
        str(api_journal),transform.pin(api_file)['sha256']],mg,out,journal,'shower-reentry'))
    m._copied_source_custody(request,out,'after-shower-reentry')
    hard_banner=next(v['retained']['path'] for v in subjects if v['role']=='banner')
    final_banner=hard_seed['banner']['path']
    tag=m.literal(m.assignments(observed['run'],native_lo_empty_strings=True)['run_tag'])
    command_card=process/'Events/ravel'/(tag+'_pythia8.cmd')
    transition=observe_banner(hard_banner,final_banner,command_card)
    from . import pythia_cards
    actual_cmd=pythia_cards.parse(m.authenticated_text(command_card));source_cmd=pythia_cards.parse(texts['pythia'])
    m.matches(actual_cmd['settings'],{'Beams:LHEF':'unweighted_events.lhe.gz','HEPMCoutput:scaling':1000000000,
        'Main:numberOfEvents':c['generation']['events']},'actual released shower command normalization/input')
    require(pythia_cards._identity(source_cmd)['ordered_particle_program']==pythia_cards._identity(actual_cmd)['ordered_particle_program'],
            'actual native command changed original particle/ordered decay program')
    for k,v in source_cmd['settings'].items():
        if k=='hepmcoutput:file':continue
        m.matches(actual_cmd['settings'],{k:m.literal(v)},'actual complete declared source shower setting')
    result={'schema_version':1,'mode':MODE,'complete_original_N':c['generation']['events'],
        'hard_stage_scope':'retained actual hard-stage observation; old native endpoints were explicitly replaced afterwards',
        'hard_seed_observation':hard_seed,'retained_hard_subject':subjects,'hard_member_commitment':hard_commitment,
        'transform':conversion,'transform_receipt':transform.pin(out/'preshower-transform/transform.json'),
        'derived_operative_card':transform.pin(derived_card),'operative_native_card':operative_card,
        'operative_native_lhe':operative_lhe,'card_token_change':card_change,'native_api_request':api_request,
        'native_reentry_method_source':transform.pin(mg/'madgraph/interface/madevent_interface.py'),
        'native_original_bin_source':transform.pin(mg/'bin/mg5_aMC'),
        'native_api_journal':transform.pin(api_journal),'native_stage_inputs':[transform.pin(native_driver),transform.pin(api_file),transform.pin(script)],
        'native_banner_transition':transition,'declared_complete_stream_census':census,
        'full_cut_population':census['cut_values_gev'],'full_cut_variation':census['full_cut_variation'],
        'weight_cross_scope':'full declared Cartesian cross' if census['full_cut_variation'] else 'source-declared reduced cross: all nominal cuts plus central-cut LHE variations',
        'build_claim_verified_as_compilation':False,'native_ABI_qualified':False,'native_numerical_equivalence':False,
        'physical_hard_to_shower_association':'unknown','matching_acceptance_qualified':False,'Athena_equivalence':False,
        'scientific_acceptance':False}
    _api_rows(result)
    ending_custody(result,process)
    bridge._write(out/'pre-shower-transport.json',result)
    return result


def checked_cards(c,split,observed):
    from . import model_events as m
    ending=m.assignments(observed['run'],native_lo_empty_strings=True)
    expected=m.assignments(Path(split['derived_operative_card']['path']).read_text(),native_lo_empty_strings=True)
    require(ending==expected,'native ending card differs from complete explicit derived hard ending card')
    checked=dict(observed)
    checked['run']=derived_run_card(split['hard_seed_observation']['operative_run_card'])[0]
    config=deepcopy(c);config['generation']['run_settings']['event_norm']='average'
    return config,checked,ending


def ending_custody(split,process):
    require(split.get('scientific_acceptance') is False and split['physical_hard_to_shower_association']=='unknown',
            'source transport cannot inherit physical genealogy/numerical acceptance')
    transform.verify(split['transform'])
    pins=[split['transform_receipt'],split['derived_operative_card'],split['operative_native_card'],
          split['operative_native_lhe'],split['native_api_journal'],split['native_reentry_method_source'],
          split['native_original_bin_source'],*split['native_stage_inputs'],
          *[v['retained'] for v in split['retained_hard_subject']]]
    transition=split['native_banner_transition']
    pins += [transition['hard_banner'],transition['final_native_banner'],transition['actual_native_command_card']]
    require(all(transform.pin(x['path'])==x for x in pins),'retained hard/derived/native subject changed before ending')
    require(Path(split['operative_native_card']['path'])==Path(process)/'Cards/run_card.dat' and
            Path(split['operative_native_lhe']['path'])==Path(process)/'Events/ravel/unweighted_events.lhe.gz',
            'operative subject belongs to foreign native process')
    require(observe_banner(transition['hard_banner']['path'],transition['final_native_banner']['path'],
                           transition['actual_native_command_card']['path'])==transition,
            'native banner transition differs at ending')
    _api_rows(split)
    # Original full native source facts consumed by the historical seed observer
    # remain original inputs; changed native evidence paths are retained above.
    require(all(transform.pin(p['path'])==p for p in split['hard_seed_observation']['native_sources']),
            'hard-stage consumed native source changed at ending')
    return True
