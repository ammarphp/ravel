"""Explicit SARAH4.15.4 readiness and trusted source-to-UFO bridge extension.

The mirrored source is executable and separately trusted. CheckModel is a symbol
with diagnostic output, not a Boolean certificate. No spectrum solver, widths,
events, loops, license acquisition or implicit model/card defaults are added.
"""
import ast
import hashlib
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re

from ravel.physics import model_tool_bridge as custody

READINESS = 'wolfram-sarah-readiness'
DERIVATION = 'sarah-source-ufo'
VERSION = '4.15.4'
ENTRYPOINTS = {'Start': 'down', 'CheckModel': 'own', 'MakeUFO': 'down', 'ModelOutput': 'down'}
SCOPE = 'SARAH source/model load, explicit UFO export options, raw CheckModel diagnostics and source/card convention census; no physical certification'


def _common(c):
    if type(c['schema_version']) is not int or c['schema_version'] != 2:
        raise ValueError('SARAH bridge requires explicit schema2')
    if c['trusted_provider_source'] is not True or not isinstance(c['source'], str) or not c['source'].strip():
        raise ValueError('attributed explicitly trusted executable SARAH source required')
    if type(c['expected_kernel_version']) not in (int, float) or c['expected_kernel_version'] not in (14.3, 15.0):
        raise ValueError('explicit Wolfram14.3 or15.0 binding required; compatibility must be qualified')
    if c['expected_provider_version'] != VERSION:
        raise ValueError('inspected source contract is SARAH4.15.4; other versions need source qualification')
    if type(c['max_ram_mib']) is not int or not 512 <= c['max_ram_mib'] <= 8192:
        raise ValueError('sampled RAM ceiling512..8192MiB required')


def validate_readiness(c):
    custody._keys(c, ('schema_version','operation','source','kernel','application_metadata','provider_tree',
        'trusted_provider_source','expected_kernel_version','expected_provider_version',
        'existing_installation_license_status','max_seconds','max_ram_mib'), 'SARAH readiness config')
    _common(c)
    if c['operation'] != READINESS or type(c['max_seconds']) is not int or not 1 <= c['max_seconds'] <= 120:
        raise ValueError('SARAH readiness requires1..120seconds')
    if c['max_ram_mib'] > 4096:
        raise ValueError('readiness RAM ceiling<=4096MiB')
    if c['existing_installation_license_status'] != 'unverified_no_activation_or_credentials_requested':
        raise ValueError('existing license/distribution uncertainty must remain declared')
    return c


def options(o):
    custody._keys(o, ('exclude','include_effective_higgs_vertices','bsm_couplings','must_include',
        'read_lists','replacements','python2'), 'explicit SARAH UFO options')
    ex=o['exclude']
    if (not isinstance(ex,list) or any(type(x) is not str or x not in ('SSSS','GGS','GGV') for x in ex)
            or len(set(ex)) != len(ex)):
        raise ValueError('explicit unique inspected generic exclusions SSSS/GGS/GGV only')
    if type(o['include_effective_higgs_vertices']) is not bool:
        raise ValueError('effective Higgs vertex choice must be explicit Boolean')
    if o['bsm_couplings'] != [] or o['must_include'] != [] or o['replacements'] != {}:
        raise ValueError('custom expression/coupling replacement options require a new source contract')
    if o['read_lists'] is not False or o['python2'] is not False:
        raise ValueError('fresh calculated vertices and Python3 export required')
    return {'requested':o,'effective_exclude':[*ex,'ASS'],
        'mandatory_upstream_exclusion':'GenerateUFO joins {ASS} even when requested Exclude is empty.',
        'full_interaction_population_exported':False}


def conventions(rows):
    if not isinstance(rows,list) or not 1 <= len(rows) <= 64:
        raise ValueError('1..64 explicit particle convention obligations required')
    seen=set()
    for row in rows:
        custody._keys(row, ('pdg','spin','color','charge','mass_parameter','width_parameter'), 'particle convention')
        if type(row['pdg']) is not int or not 0 < abs(row['pdg']) < 1000000000 or row['pdg'] in seen:
            raise ValueError('unique nonzero explicit signed PDG required')
        seen.add(row['pdg'])
        if type(row['spin']) is not int or row['spin'] not in (-1,1,2,3,4,5):
            raise ValueError('explicit UFO2S+1 spin (ghost=-1) required')
        if type(row['color']) is not int or row['color'] not in (1,-3,3,-6,6,8):
            raise ValueError('explicit UFO color representation required')
        if type(row['charge']) not in (int,float) or not math.isfinite(row['charge']):
            raise ValueError('finite explicit electric charge required')
        for key in ('mass_parameter','width_parameter'):
            if not isinstance(row[key],str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',row[key]):
                raise ValueError('explicit UFO mass/width parameter identifier required')
    return rows


def validate_derivation(c):
    custody._keys(c, ('schema_version','operation','source','kernel','application_metadata','provider_tree',
        'model_tree','model_name','eigenstate','ufo_options','particle_conventions','point_policy','parameter_card',
        'trusted_provider_source','trusted_model_source','provider_readiness_receipt','provider_readiness_run',
        'expected_kernel_version','expected_provider_version','max_seconds','max_ram_mib'), 'SARAH derivation config')
    _common(c)
    if c['operation'] != DERIVATION or c['trusted_model_source'] is not True:
        raise ValueError('explicit trusted SARAH source model required')
    for key in ('model_name','eigenstate'):
        if not isinstance(c[key],str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',c[key]):
            raise ValueError('one literal model/eigenstate name required; submodel paths/expressions unsupported')
    options(c['ufo_options']); conventions(c['particle_conventions'])
    if c['point_policy'] not in ('no_parameter_point_selected','supplied_complete_card'):
        raise ValueError('SARAH export defaults cannot silently define a point; explicitly choose no point or a supplied complete card')
    if (c['point_policy']=='no_parameter_point_selected' and c['parameter_card'] is not None):
        raise ValueError('no-point export must not carry an implicit parameter card')
    if c['point_policy']=='supplied_complete_card':
        custody._keys(c['parameter_card'],('path','sha256'),'explicit complete parameter card')
    custody._keys(c['provider_readiness_run'], ('path','attempt_id','attempt_record'), 'qualified SARAH run')
    for key in ('path','attempt_id'):
        if not isinstance(c['provider_readiness_run'][key],str) or not c['provider_readiness_run'][key]:
            raise ValueError('actual accepted SARAH readiness run/attempt required')
    if type(c['max_seconds']) is not int or not 1 <= c['max_seconds'] <= 900:
        raise ValueError('SARAH derivation ceiling1..900seconds required')
    return c


def provider_source(c,base):
    root,manifest,files=custody._tree(c['provider_tree'],base)
    for name in ('SARAH.m','SARAH.config','Package/checkModel.m','Package/Outputs/madgraph.m',
                 'Models/parameters.m','Models/particles.m'):
        custody._regular(name,root)
    match=re.search(r'SA`Version\s*=\s*"([^\"]+)"',(root/'SARAH.m').read_text())
    if not match or match.group(1) != c['expected_provider_version']:
        raise ValueError('SARAH source version differs')
    return root,manifest,files


def readiness_inputs(task,base):
    path=custody._regular(task['config'],base); c=validate_readiness(custody._read(path))
    kernel=custody._pin(c['kernel'],path.parent)
    if not os.access(kernel,os.X_OK): raise ValueError('native kernel not executable')
    metadata=custody._pin(c['application_metadata'],path.parent)
    _,manifest,files=provider_source(c,path.parent)
    return sorted(set([path,kernel,metadata,manifest,*files,*Path(__file__).resolve().parents[1].rglob('*.py')]))


def derivation_inputs(task,base):
    from ravel.physics import model_derivation_bridge as bridge
    path=custody._regular(task['config'],base); c=validate_derivation(custody._read(path))
    kernel=custody._pin(c['kernel'],path.parent)
    if not os.access(kernel,os.X_OK): raise ValueError('native kernel not executable')
    metadata=custody._pin(c['application_metadata'],path.parent)
    root,manifest,files=provider_source(c,path.parent)
    model,mm,mf=custody._tree(c['model_tree'],path.parent)
    # Source tree is the exact parent containing <model>/<model>.m plus both files.
    for name in (c['model_name']+'.m','parameters.m','particles.m'):
        custody._regular(c['model_name']+'/'+name,model)
    prior=custody._pin(c['provider_readiness_receipt'],path.parent)
    qualified,proof=bridge._qualification(c,path.parent)
    if qualified != custody.source_tree(root): raise ValueError('SARAH provider differs from actual readiness bytes')
    cards=[]
    if c['point_policy']=='supplied_complete_card':
        from ravel.validation.model_tool_witness import card_values
        card=custody._pin(c['parameter_card'],path.parent); card_values(card.read_text());cards=[card]
    return sorted(set([path,kernel,metadata,manifest,mm,prior,*cards,*files,*mf,*proof,
                       *Path(__file__).resolve().parents[1].rglob('*.py')]))


def load_script(root):
    q=json.dumps(str(root),ensure_ascii=False)
    return ('$HistoryLength=0; SA`Parallelize=False; $MessageList={};\n'
        'loaded=CheckAbort[Check[Get[FileNameJoin[{'+q+',"SARAH.m"}]];True,False],False];\n'
        'loadMessages=ToString[#,InputForm]& /@ $MessageList;\n')


def readiness_script(root,output):
    q=lambda x:json.dumps(str(x),ensure_ascii=False)
    definitions=', '.join(q(k)+' -> Length['+('OwnValues' if v=='own' else 'DownValues')+'[SARAH`'+k+']]' for k,v in ENTRYPOINTS.items())
    return (load_script(root)+'kernels=Kernels[];\n'
        'r=<|"schema_version"->2,"provider_kind"->"sarah","provider_root"->'+q(root)+',\n'
        ' "process_id"->$ProcessID,"kernel_version"->$VersionNumber,"kernel_version_string"->$Version,\n'
        ' "provider_version"->SA`Version,"provider_loaded"->TrueQ[loaded],"load_messages"->loadMessages,\n'
        ' "kernel_arithmetic_control"->(2+2),"parallel_disabled"->TrueQ[SA`Parallelize===False],\n'
        ' "parallel_kernels_list"->ListQ[kernels],"parallel_kernel_count"->If[ListQ[kernels],Length[kernels],-1],\n'
        ' "entrypoint_definition_counts"-><|'+definitions+'|>,"definition_kinds"-><|'+
        ','.join(q(k)+'->'+q(v) for k,v in ENTRYPOINTS.items())+'|>,\n'
        ' "model_calculation_performed"->False,"generated_events"->0|>;\n'
        'Export['+q(output)+',r,"RawJSON"]; Exit[0];\n')


def readiness_adjudicate(r,c,root,pid):
    counts=r.get('entrypoint_definition_counts')
    checks={'source_path':r.get('provider_root')==str(root),'actual_owned_kernel':type(r.get('process_id')) is int and r['process_id']==pid,
        'qualified_versions':type(r.get('kernel_version')) in (int,float) and r['kernel_version']==c['expected_kernel_version'] and r.get('provider_version')==c['expected_provider_version'],
        'provider_kind':r.get('provider_kind')=='sarah','message_free_load':r.get('provider_loaded') is True and r.get('load_messages')==[],
        'arithmetic':type(r.get('kernel_arithmetic_control')) is int and r['kernel_arithmetic_control']==4,
        'definition_kinds':r.get('definition_kinds')==ENTRYPOINTS,
        'evaluated_definitions':isinstance(counts,dict) and set(counts)==set(ENTRYPOINTS) and all(type(v) is int and v>0 for v in counts.values()),
        'no_parallel':r.get('parallel_disabled') is True and r.get('parallel_kernels_list') is True and type(r.get('parallel_kernel_count')) is int and r['parallel_kernel_count']==0,
        'no_model_calculation':r.get('model_calculation_performed') is False and type(r.get('generated_events')) is int and r['generated_events']==0}
    return {'passed':all(checks.values()),'checks':checks,'scope':'Operational SARAH source load/evaluated definitions only; no model validity or runtime compatibility beyond this attempt.'}


def qualified_receipt(r,version=None):
    n=r.get('native_provider',{}); v=n.get('kernel_version')
    if type(v) not in (int,float) or v not in (14.3,15.0) or (version is not None and v!=version):
        raise ValueError('actual qualified SARAH/runtime differs')
    expected=readiness_adjudicate({}, {'expected_kernel_version':v,'expected_provider_version':VERSION},Path('/unused'),0)['checks']
    if (r.get('status')!='passed' or r.get('physics_validated') is not False or r.get('model_calculation_performed') is not False
        or type(r.get('generated_events')) is not int or r['generated_events']!=0 or r.get('checks',{}).get('passed') is not True
        or set(r.get('checks',{}).get('checks',{}))!=set(expected) or not all(x is True for x in r['checks']['checks'].values())
        or n.get('provider_kind')!='sarah' or n.get('provider_version')!=VERSION or not isinstance(n.get('provider_root'),str) or not n['provider_root']):
        raise ValueError('actual successful source-bound SARAH readiness required')
    e=r.get('native_execution',{})
    if type(e.get('returncode')) is not int or e['returncode']!=0 or e.get('resource_violation') is not None or not isinstance(e.get('command'),list) or not e['command']:
        raise ValueError('prior actual bounded successful kernel execution required')
    return r


def derivation_script(c,root,model,exported,receipt):
    validate_derivation(c); q=lambda x:json.dumps(str(x),ensure_ascii=False)
    o=c['ufo_options']; effective=options(o); output=Path(exported).parent/'sarah-output'
    opts='SARAH`Exclude->{'+','.join('SARAH`'+x for x in o['exclude'])+'}, SARAH`IncludeEffectiveHiggsVertices->'+str(o['include_effective_higgs_vertices'])+', SARAH`BSMcouplings->{}, SARAH`MustInclude->{}, SARAH`ReadLists->False, SARAH`Replacements->{}, SARAH`python2->False'
    # CheckModel is intentionally invoked as a symbol; raw Null is retained.
    return (load_script(root)+
        'SARAH`Private=False; SARAH`SARAH[SARAH`InputDirectories]={'+q(model)+'};\n'
        'SARAH`SARAH[SARAH`OutputDirectory]='+q(output)+';\n'
        'SetOptions[SARAH`ModelOutput,SARAH`SixParticleInteractions->False,SARAH`effectiveOperators->False,SARAH`ReadLists->False,SARAH`IncludeLoopCorrections->False,SARAH`IncludeRGEs->False,SARAH`IncludeVertices->True];\n'
        'modelChoices=<|"six_particle_interactions"->(SARAH`SixParticleInteractions/.Options[SARAH`ModelOutput]),"effective_operators"->(SARAH`effectiveOperators/.Options[SARAH`ModelOutput]),"read_lists"->(SARAH`ReadLists/.Options[SARAH`ModelOutput]),"loop_corrections"->(SARAH`IncludeLoopCorrections/.Options[SARAH`ModelOutput]),"rges"->(SARAH`IncludeRGEs/.Options[SARAH`ModelOutput]),"vertices"->(SARAH`IncludeVertices/.Options[SARAH`ModelOutput])|>;\n'
        'startOK=False; startMessages={}; checkInvoked=False; checkRaw="not_invoked"; checkMessages={}; exportOK=False;\n'
        'If[TrueQ[loaded], Block[{$MessageList={}},startOK=CheckAbort[Check[SARAH`Start['+q(c['model_name'])+'];True,False],False];startMessages=ToString[#,InputForm]& /@ $MessageList]];\n'
        'stateNames=If[ListQ[SARAH`NameOfStates],ToString[#,InputForm]& /@ SARAH`NameOfStates,{}];\n'
        'stateOK=Length[stateNames]>0 && Last[stateNames]==='+q(c['eigenstate'])+';\n'
        'startOK=TrueQ[startOK && SARAH`ModelLoaded===True && SARAH`AbortStart===False && stateOK];\n'
        'If[startOK,Print["RAVEL_SARAH_CHECKMODEL_BEGIN"];Block[{$MessageList={}},\n'
        ' checkInvoked=CheckAbort[checkValue=Check[SARAH`CheckModel,$Failed];True,False];\n'
        ' checkRaw=ToString[checkValue,InputForm];checkMessages=ToString[#,InputForm]& /@ $MessageList];Print["RAVEL_SARAH_CHECKMODEL_END"]];\n'
        'If[startOK && checkInvoked && checkMessages==={} && checkRaw=!= "$Failed",\n'
        ' exportOK=Block[{$MessageList={}}, CheckAbort[Check[SARAH`MakeUFO['+opts+'];True,False],False]]];\n'
        'rawUFO=If[ValueQ[SARAH`$sarahCurrentUfoDir],SARAH`$sarahCurrentUfoDir,""];\n'
        'If[exportOK && DirectoryQ[rawUFO],CopyDirectory[rawUFO,'+q(exported)+']];kernels=Kernels[];\n'
        'r=<|"schema_version"->2,"provider_kind"->"sarah","process_id"->$ProcessID,\n'
        ' "kernel_version"->$VersionNumber,"provider_version"->SA`Version,"provider_root"->'+q(root)+',"model_root"->'+q(model)+',"export_root"->'+q(exported)+',\n'
        ' "model_name"->'+q(c['model_name'])+',"requested_eigenstate"->'+q(c['eigenstate'])+',"state_names"->stateNames,\n'
        ' "load_messages"->loadMessages,"start_messages"->startMessages,"provider_loaded"->TrueQ[loaded],"start_completed"->startOK,\n'
        ' "input_directories"->SARAH`SARAH[SARAH`InputDirectories],"output_directory"->SARAH`SARAH[SARAH`OutputDirectory],\n'
        ' "check_model_invoked"->TrueQ[checkInvoked],"check_model_return_expression"->checkRaw,"check_model_messages"->checkMessages,\n'
        ' "model_output_choices"->modelChoices,"check_model_boolean_certificate"->False,"export_completed"->TrueQ[exportOK && DirectoryQ['+q(exported)+']],"native_ufo_root"->rawUFO,\n'
        ' "explicit_ufo_options_json"->'+q(json.dumps(o,sort_keys=True))+',"effective_exclude"->{'+','.join(q(x) for x in effective['effective_exclude'])+'},\n'
        ' "parallel_disabled"->TrueQ[SA`Parallelize===False],"parallel_kernels_list"->ListQ[kernels],"parallel_kernel_count"->If[ListQ[kernels],Length[kernels],-1],\n'
        ' "model_calculation_performed"->True,"decay_calculation_requested"->False,"generated_events"->0|>;\n'
        'Export['+q(receipt)+',r,"RawJSON"];Exit[0];\n')


def derivation_adjudicate(n,c,root,model,exported,pid):
    output=Path(exported).parent/'sarah-output'; states=n.get('state_names')
    checks={'actual_owned_kernel':type(n.get('process_id')) is int and n['process_id']==pid,
        'qualified_versions':type(n.get('kernel_version')) in (int,float) and n['kernel_version']==c['expected_kernel_version'] and n.get('provider_version')==VERSION and n.get('provider_kind')=='sarah',
        'source_paths':n.get('provider_root')==str(root) and n.get('model_root')==str(model) and n.get('export_root')==str(exported),
        'isolated_model_selection':n.get('model_name')==c['model_name'] and n.get('input_directories')==[str(model)] and n.get('output_directory')==str(output),
        'message_free_source_start':n.get('provider_loaded') is True and n.get('start_completed') is True and n.get('load_messages')==[] and n.get('start_messages')==[],
        'last_eigenstate':n.get('requested_eigenstate')==c['eigenstate'] and isinstance(states,list) and bool(states) and all(isinstance(x,str) for x in states) and states[-1]==c['eigenstate'],
        'raw_check_model_diagnostics':n.get('check_model_invoked') is True and isinstance(n.get('check_model_return_expression'),str) and n['check_model_return_expression'] not in ('','not_invoked','$Failed') and n.get('check_model_messages')==[] and n.get('check_model_boolean_certificate') is False,
        'explicit_tree_model_choices':_tree_choices(n.get('model_output_choices')),
        'explicit_export':n.get('export_completed') is True and n.get('explicit_ufo_options_json')==json.dumps(c['ufo_options'],sort_keys=True) and n.get('effective_exclude')==options(c['ufo_options'])['effective_exclude'],
        'native_ufo_path':n.get('native_ufo_root')==str(output/c['model_name']/c['eigenstate']/'UFO') or n.get('native_ufo_root')==str(output/c['model_name']/c['eigenstate']/'UFO')+'/',
        'no_parallel':n.get('parallel_disabled') is True and n.get('parallel_kernels_list') is True and type(n.get('parallel_kernel_count')) is int and n['parallel_kernel_count']==0,
        'no_unrequested_work':n.get('model_calculation_performed') is True and n.get('decay_calculation_requested') is False and type(n.get('generated_events')) is int and n['generated_events']==0}
    return {'passed':all(checks.values()),'checks':checks,'scope':SCOPE,'check_model_physical_acceptance':None,
        'diagnostic_interpretation':'Printed full CheckModel diagnostics in native stdout require scoped review; a returned Null is not a Boolean pass.'}


def _tree_choices(value):
    expected={'six_particle_interactions':False,'effective_operators':False,'read_lists':False,'loop_corrections':False,'rges':False,'vertices':True}
    return isinstance(value,dict) and set(value)==set(expected) and all(type(value[k]) is bool and value[k] is v for k,v in expected.items())


def _ref(node,module):
    if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id==module: return node.attr
    raise ValueError('canonical static UFO reference required')


def _numeric(node):
    if isinstance(node,ast.Constant) and type(node.value) in (int,float) and math.isfinite(node.value): return Fraction(str(node.value))
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
        v=_numeric(node.operand); return -v if isinstance(node.op,ast.USub) else v
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div):
        denominator=_numeric(node.right)
        if not denominator: raise ValueError('zero UFO charge denominator')
        return _numeric(node.left)/denominator
    raise ValueError('literal rational finite charge required; arbitrary expression not evaluated')


def ufo_census(exported,required):
    """Static full source records + selected obligations; no UFO code is imported."""
    from ravel.physics import model_derivation_bridge as bridge
    root=Path(exported); conventions(required)
    _,external=bridge.literal_external_card((root/'parameters.py').read_text())
    parameters={}; particles={}; couplings={}; vertices={}; lorentz={}
    tables={'Parameter':parameters,'Particle':particles,'Coupling':couplings,'Vertex':vertices,'Lorentz':lorentz}
    for filename,factory in (('parameters.py','Parameter'),('particles.py','Particle'),('couplings.py','Coupling'),('vertices.py','Vertex'),('lorentz.py','Lorentz')):
        text=(root/filename).read_text()
        for st in ast.parse(text).body:
            if not isinstance(st,ast.Assign) or not isinstance(st.value,ast.Call): continue
            call=st.value
            if factory=='Particle' and isinstance(call.func,ast.Attribute) and call.func.attr=='anti':
                if len(st.targets)!=1 or not isinstance(st.targets[0],ast.Name) or call.args or call.keywords or not isinstance(call.func.value,ast.Name) or call.func.value.id not in particles:
                    raise ValueError('canonical ordered particle anti() declaration required')
                original=particles[call.func.value.id]; target=st.targets[0].id
                if target in particles or original['name']==original['antiname']: raise ValueError('duplicate/self-conjugate anti declaration')
                row={**original,'source_line':st.lineno,'name':original['antiname'],'antiname':original['name'],
                    'pdg':-original['pdg'],'charge':-original['charge'],'color':-original['color'] if abs(original['color']) in (3,6) else original['color'],
                    'anti_of':call.func.value.id,'source_expression':ast.get_source_segment(text,st)}
                particles[target]=row; continue
            f=call.func.id if isinstance(call.func,ast.Name) else None
            if f!=factory: continue
            if len(st.targets)!=1 or not isinstance(st.targets[0],ast.Name) or call.args: raise ValueError('canonical named keyword UFO declaration required')
            k={x.arg:x.value for x in call.keywords}
            if None in k or len(k)!=len(call.keywords): raise ValueError('duplicate/expanded UFO keyword')
            target=st.targets[0].id; table=tables[factory]
            if target in table: raise ValueError('duplicate UFO assignment')
            name=ast.literal_eval(k['name'])
            if not isinstance(name,str) or not name or any(x['name']==name for x in table.values()): raise ValueError('unique UFO declared name required')
            row={'name':name,'source_line':st.lineno,'source_expression':ast.get_source_segment(text,st)}
            if factory=='Particle':
                row.update(pdg=ast.literal_eval(k['pdg_code']),spin=ast.literal_eval(k['spin']),color=ast.literal_eval(k['color']),
                    charge=float(_numeric(k['charge'])),antiname=ast.literal_eval(k['antiname']),mass_parameter=_ref(k['mass'],'Param'),width_parameter=_ref(k['width'],'Param'))
                conventions([{key:row[key] for key in ('pdg','spin','color','charge','mass_parameter','width_parameter')}])
            if factory=='Vertex':
                if not isinstance(k.get('particles'),ast.List) or not isinstance(k.get('lorentz'),ast.List) or not isinstance(k.get('couplings'),ast.Dict): raise ValueError('canonical vertex incidence required')
                if not isinstance(k.get('color'),ast.List): raise ValueError('explicit vertex color basis required')
                indices=[ast.literal_eval(x) for x in k['couplings'].keys]
                if any(not isinstance(x,tuple) or len(x)!=2 or any(type(n) is not int or n<0 for n in x) for x in indices) or len(set(indices))!=len(indices): raise ValueError('unique finite vertex coupling basis indices required')
                if any(x[0]>=len(k['color'].elts) or x[1]>=len(k['lorentz'].elts) for x in indices): raise ValueError('vertex coupling basis index outside source population')
                row.update(particles=[_ref(x,'P') for x in k['particles'].elts],lorentz=[_ref(x,'L') for x in k['lorentz'].elts],couplings=[_ref(x,'C') for x in k['couplings'].values],coupling_indices=[list(x) for x in indices])
            table[target]=row
    if not particles or not couplings or not vertices or not lorentz: raise ValueError('nonvacuous complete UFO particle/coupling/vertex/Lorentz census required')
    pdgs={}
    external_names={x['name']:x for x in external}
    for key,row in particles.items():
        if row['pdg'] in pdgs: raise ValueError('duplicate signed UFO PDG')
        pdgs[row['pdg']]=row
        if row['mass_parameter'] not in parameters or row['width_parameter'] not in parameters: raise ValueError('particle mass/width reference missing')
    for row in vertices.values():
        if not row['particles'] or not row['lorentz'] or not row['couplings'] or any(x not in particles for x in row['particles']) or any(x not in lorentz for x in row['lorentz']) or any(x not in couplings for x in row['couplings']): raise ValueError('unresolved complete vertex references')
    selected=[]
    for expected in required:
        actual=pdgs.get(expected['pdg'])
        if actual is None or any(actual[k]!=v for k,v in expected.items()): raise ValueError('selected particle convention differs from request')
        for kind,block in (('mass_parameter','mass'),('width_parameter','decay')):
            ref=expected[kind]
            if ref=='ZERO': continue
            param=external_names.get(parameters[ref]['name'])
            if not param or param['block']!=block or param['codes']!=[abs(expected['pdg'])]: raise ValueError('selected mass/width card address differs')
        selected.append({'requested':expected,'source_particle':actual})
    return {'parameters':parameters,'particles':particles,'couplings':couplings,'vertices':vertices,'lorentz':lorentz,
        'all_literal_external_card_parameters':external,'selected_convention_checks':selected,
        'full_source_census':True,'coupling_expressions_evaluated':False,'physical_model_validated':False,
        'upstream_parameter_defaults':{'mass_nan_substitution':100.0,'width_nan_substitution':0.0,'observed_applied_substitutions':None,
            'source':'SARAH4.15.4 madgraph.m WriteUfoParameters; potential substitutions are source facts, actual applied population is unmeasured.',
            'selected_as_physical_point':False}}


def prepare_readiness(args):
    if not args.trust_provider_source: raise ValueError('explicit trusted executable SARAH source required')
    rd=Path(args.rundir).expanduser().absolute(); proposal=rd.with_name(rd.name+'-proposal')
    if rd.exists() or proposal.exists(): raise ValueError('fresh provider study/proposal required')
    root=custody._regular(args.sarah,Path.cwd(),directory=True)
    proposal.mkdir(parents=True)
    manifest=proposal/'provider-source.json'; custody._write(manifest,custody.source_tree(root))
    pin=lambda p:{'path':str(p),'sha256':custody._hash(p)}
    c={'schema_version':2,'operation':READINESS,'source':args.source,'provider_tree':{'root':str(root),'manifest':pin(manifest)},
       'kernel':pin(custody._regular(args.kernel,Path.cwd())),'application_metadata':pin(custody._regular(args.application_metadata,Path.cwd())),
       'trusted_provider_source':True,'expected_kernel_version':args.expected_kernel_version,'expected_provider_version':VERSION,
       'existing_installation_license_status':'unverified_no_activation_or_credentials_requested','max_seconds':args.max_seconds,'max_ram_mib':args.max_ram_mib}
    config=proposal/'model-provider-bridge.json'; custody._write(config,c); task={'config':str(config)}
    readiness_inputs(task,proposal)
    policy=custody._read(custody._regular(args.review_policy,Path.cwd()))
    spec={'schema_version':2,'mode':'model-provider-bridge','source':args.source,'task':task,
        'max_seconds':args.max_seconds+240,'max_attempts':1+policy['policy']['max_redos'],'approval_mode':args.approval_mode,'review_policy':policy,
        'assumptions':['Trusted executable SARAH4.15.4 mirror, not an asserted current official release or redistribution permission.',
           'Load/evaluated API readiness only; no Start/model calculation/CheckModel/UFO/decays/events.',
           'Existing proprietary kernel license/startup and SARAH compatibility remain actual execution questions.']}
    doc=proposal/'science.json'; custody._write(doc,spec)
    from ravel.workflow.science import plan
    plan(rd,doc)
    return 0


def prepare_derivation(args):
    if not args.trust_model_source or not args.trust_provider_source: raise ValueError('explicit trusted executable sources required')
    from ravel.physics import model_derivation_bridge as bridge
    from ravel.workflow import execution
    rd=Path(args.rundir).expanduser().absolute(); proposal=rd.with_name(rd.name+'-proposal')
    if rd.exists() or proposal.exists(): raise ValueError('fresh SARAH derivation study/proposal required')
    root=custody._regular(args.sarah,Path.cwd(),directory=True); model=custody._regular(args.model,Path.cwd(),directory=True)
    original=custody._regular(args.provider_readiness_run,Path.cwd(),directory=True)
    stage=execution.load_execution(original)['stages']['science']
    prior=custody._regular(args.provider_readiness_receipt,Path.cwd()); readiness=qualified_receipt(custody._read(prior))
    # No proposal is created before actual receipt screening.
    proposal.mkdir(parents=True); pin=lambda p:{'path':str(p),'sha256':custody._hash(p)}
    def tree(path,name):
        manifest=proposal/name; custody._write(manifest,custody.source_tree(path)); return {'root':str(path),'manifest':pin(manifest)}
    c={'schema_version':2,'operation':DERIVATION,'source':args.source,'kernel':pin(custody._regular(args.kernel,Path.cwd())),
        'application_metadata':pin(custody._regular(args.application_metadata,Path.cwd())),
        'provider_tree':tree(root,'provider-source.json'),'model_tree':tree(model,'model-source.json'),
        'model_name':args.model_name,'eigenstate':args.eigenstate,'ufo_options':custody._read(custody._regular(args.ufo_options,Path.cwd())),
        'particle_conventions':custody._read(custody._regular(args.particle_conventions,Path.cwd())),'point_policy':args.point_policy,'parameter_card':pin(custody._regular(args.parameter_card,Path.cwd())) if args.parameter_card else None,
        'trusted_provider_source':True,'trusted_model_source':True,'provider_readiness_receipt':pin(prior),
        'provider_readiness_run':{'path':str(original),'attempt_id':stage['attempt_id'],'attempt_record':pin(custody._regular(stage['attempt_record'],original))},
        'expected_kernel_version':readiness['native_provider']['kernel_version'],'expected_provider_version':VERSION,
        'max_seconds':args.max_seconds,'max_ram_mib':args.max_ram_mib}
    config=proposal/'model-derivation-bridge.json'; custody._write(config,c); task={'config':str(config)}
    derivation_inputs(task,proposal)
    policy=custody._read(custody._regular(args.review_policy,Path.cwd()))
    spec={'schema_version':2,'mode':'model-derivation-bridge','source':args.source,'task':task,
        'max_seconds':args.max_seconds+240,'max_attempts':1+policy['policy']['max_redos'],'approval_mode':args.approval_mode,'review_policy':policy,
        'assumptions':['Exactly accepted SARAH readiness/runtime bytes; explicit trusted full model source parent and final eigenstate.',
            'Explicit tree ModelOutput/MakeUFO settings; mandatory upstream ASS exclusion retained; no complete interaction/width/physics certificate.',
            'CheckModel raw printed diagnostics/return are retained; Null never means passed physics.',
            'Native exporter may substitute NaN mass100/width0; defaults are retained as diagnostics, never implicitly adopted. Only a supplied complete card selects a downstream point.']}
    doc=proposal/'science.json'; custody._write(doc,spec)
    from ravel.workflow.science import plan
    plan(rd,doc)
    return 0


def cli_arguments(parser,derivation=False):
    for name in ('kernel','application-metadata','sarah','source','rundir','review-policy'): parser.add_argument('--'+name,required=True)
    parser.add_argument('--trust-provider-source',action='store_true')
    parser.add_argument('--approval-mode',choices=('physicist','scripted_yes'),default='physicist')
    parser.add_argument('--max-seconds',type=int,default=900 if derivation else 60)
    parser.add_argument('--max-ram-mib',type=int,default=8192 if derivation else 2048)
    if derivation:
        for name in ('model','model-name','eigenstate','ufo-options','particle-conventions','provider-readiness-receipt','provider-readiness-run'): parser.add_argument('--'+name,required=True)
        parser.add_argument('--point-policy',choices=('no_parameter_point_selected','supplied_complete_card'),required=True)
        parser.add_argument('--parameter-card',help='Required only for supplied_complete_card; exact complete external address census, no implicit UFO defaults')
        parser.add_argument('--trust-model-source',action='store_true')
    else: parser.add_argument('--expected-kernel-version',type=float,choices=(14.3,15.0),required=True)


def select_card(c,base,external_rows,destination):
    """Select only a supplied full point; never infer one from native fallback values."""
    if c['point_policy']=='no_parameter_point_selected': return None
    from ravel.validation.model_tool_witness import card_values
    source=custody._pin(c['parameter_card'],base); raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=c['parameter_card']['sha256']:
        raise ValueError('supplied SARAH card changed before captured-buffer validation')
    values=card_values(raw.decode('utf-8'))
    addresses={(row['block'],tuple(row['codes'])) for row in external_rows}
    if set(values)!=addresses: raise ValueError('supplied SARAH card must cover exactly every exported external address')
    for key,value in values.items():
        if key[0]=='decay' and value<0: raise ValueError('supplied total width must be nonnegative; no auto width substitution')
    if source.read_bytes()!=raw:
        raise ValueError('supplied SARAH card changed during captured-buffer validation')
    destination.write_bytes(raw)
    if source.read_bytes()!=raw or destination.read_bytes()!=raw:
        raise ValueError('supplied SARAH card or selected output changed during point delivery')
    return {'path':str(destination),'sha256':hashlib.sha256(raw).hexdigest()}
