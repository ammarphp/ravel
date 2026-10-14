"""Two incoming-gluon fixed-point Ward diagnostics, not model certification.

The supplied unrestricted UFO/card remains executable trusted source. This narrow
operation uses an explicit zero-width card and records both original gluon slots
through a leg exchange, never inferring all-leg coverage from the first check.
"""
import argparse
import itertools
import math
import os
from pathlib import Path
import re
import shutil
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ravel.physics import model_tool_bridge as bridge
from ravel.validation import model_tool_witness as witness

MAPS = [[1, 2, 3, 4], [2, 1, 3, 4]]
TOTAL_RATIO_LIMIT = 1e-10
COLOUR_RATIO_LIMIT = 1e-15
EXCHANGE_LIMIT = 1e-8
SCOPE = 'Explicit zero-width supplied-UFO tree gg→ttbar, both incoming gluon slots, same on-shell point/card native Ward diagnostic'

def validate(task):
    bridge._keys(task, ['config'], 'model-ward task')
    if not isinstance(task['config'], str) or not task['config'].strip():
        raise ValueError('explicit Ward configuration required')
    return dict(task)

def diagnostic_lineage(original, zero):
    before, after = witness.card_values(original), witness.card_values(zero)
    if set(before) != set(after):
        raise ValueError('diagnostic card parameter membership changed')
    changed = []
    for key, value in before.items():
        if key[0] == 'decay':
            if value < 0 or after[key] != 0:
                raise ValueError('all explicitly supplied widths must be zero only in diagnostic copy')
        elif value != after[key]:
            raise ValueError('diagnostic changed a non-width parameter')
        if value != after[key]:
            changed.append({'block':key[0], 'codes':list(key[1]), 'original':value, 'diagnostic':after[key]})
    if not changed:
        raise ValueError('distinct original finite-width card and explicit zero-width diagnostic required')
    return changed

def _load(task, base):
    validate(task)
    path = bridge._regular(task['config'], base)
    config = bridge._read(path)
    bridge._keys(config, ['schema_version','source','bridge_configuration','original_parameter_card','explicit_zero_width_diagnostic'], 'Ward configuration')
    if type(config['schema_version']) is not int or config['schema_version'] != 1 or config['explicit_zero_width_diagnostic'] is not True:
        raise ValueError('explicit schema1 zero-width diagnostic admission required')
    if not isinstance(config['source'], str) or not config['source'].strip():
        raise ValueError('source attribution required')
    nested = bridge._pin(config['bridge_configuration'], path.parent)
    c = bridge.validate_config(bridge._read(nested))
    if len(c['processes']) != 1 or c['processes'][0]['initial_pdgs'] != [21,21] or c['processes'][0]['final_pdgs'] != [6,-6] or c['processes'][0]['orders'] != {'QCD':2,'QED':0} or c['processes'][0]['forbidden_pdgs']:
        raise ValueError('this first supplied-SM diagnostic admits only tree gg→ttbar QCD2/QED0')
    original = bridge._pin(config['original_parameter_card'], path.parent)
    zero = bridge._pin(c['parameter_card'], nested.parent)
    diagnostic_lineage(original.read_text(), zero.read_text())
    return path, config, nested, c, original, zero

def inputs(task, base):
    path, config, nested, c, original, zero = _load(task, base)
    return sorted(set([path,original,zero,*bridge.inputs({'config':str(nested)},nested.parent)]))

def _approved(task, output):
    for rd in (Path(output).absolute(), *Path(output).absolute().parents):
        if (rd/'inputs/science-plan.json').is_file():
            from ravel.workflow import science
            selected = science.verify_worker(rd)
            spec = science.execution_spec(rd)
            if spec['mode'] != 'model-ward' or spec['task'] != task or Path(output).resolve() != (rd/selected['output_directory']).resolve():
                raise ValueError('Ward diagnostic differs from exact approved task/output')
            return rd, selected
    raise ValueError('Ward native execution requires its approved supervised worker')

def _jamp(rows):
    if not isinstance(rows,list) or not rows or len(rows)>4096 or not isinstance(rows[0],list) or not 1<=len(rows[0])<=64:
        raise ValueError('bounded nonempty complete helicity/colour array required')
    width=len(rows[0]); result=[]
    for row in rows:
        if not isinstance(row,list) or len(row)!=width:
            raise ValueError('ragged native colour array')
        result.append([])
        for value in row:
            bridge._keys(value,['real','imag'],'raw complex JAMP')
            result[-1].append(complex(witness.finite(value['real'],'JAMP real'), witness.finite(value['imag'],'JAMP imag')))
    return result

def sample_ratios(physical, brs):
    m2=witness.finite(physical['m2'],'physical matrix element')
    b2=witness.finite(brs['m2'],'BRS matrix element')
    if m2<=0:
        raise ValueError('zero/negative physical denominator cannot qualify Ward identity')
    p,b=_jamp(physical['jamp']),_jamp(brs['jamp'])
    if len(p)!=len(b) or len(p[0])!=len(b[0]):
        raise ValueError('physical/BRS helicity-colour populations differ')
    ratios=[]
    for column in range(len(p[0])):
        denominator=math.fsum(abs(row[column])**2 for row in p)
        numerator=math.fsum(abs(row[column])**2 for row in b)
        if not math.isfinite(denominator) or denominator<=0 or not math.isfinite(numerator):
            raise ValueError('every colour denominator must be finite/nonzero; zero columns are refused, never silently skipped')
        ratios.append(numerator/denominator)
    total=abs(b2)/m2
    if not math.isfinite(total) or any(not math.isfinite(r) for r in ratios):
        raise ValueError('nonfinite Ward ratio')
    return {'total_ratio':total,'colour_ratios':ratios,'total_limit':TOTAL_RATIO_LIMIT,'colour_limit':COLOUR_RATIO_LIMIT,
            'passed':total<=TOTAL_RATIO_LIMIT and all(r<=COLOUR_RATIO_LIMIT for r in ratios)}

def adjudicate(native, c, zero_text):
    if native['restriction_applied'] is not False or native['generated_events'] != 0 or native['polarization_normalization'] != 'massless_vxxxxx_nhel4_is_p_over_E':
        raise ValueError('native diagnostic semantics changed')
    supplied=witness.card_values(zero_text)
    witness.effective_card(native['model_point'],supplied)
    if native['total_ratio_limit']!=TOTAL_RATIO_LIMIT or native['colour_ratio_limit']!=COLOUR_RATIO_LIMIT:
        raise ValueError('original installed MG5 threshold changed')
    expected={(seed,tuple(mapping)) for seed in c['seeds'] for mapping in MAPS}
    if not isinstance(native['cases'],list) or len(native['cases'])!=len(expected):
        raise ValueError('full seed/original-slot population required')
    observed=set(); results=[]; by_seed={}
    spec=c['processes'][0]
    helicities=set(itertools.product((-1,1),repeat=4))
    for row in native['cases']:
        key=(row['seed'],tuple(row['local_to_original_slots']))
        if key not in expected or key in observed:
            raise ValueError('duplicate/foreign original-slot diagnostic')
        observed.add(key)
        if row['reuse_generated_matrix'] is not False or not any(name.startswith('Matrix_') for name in row['discarded_generated_globals']):
            raise ValueError('actual generated native matrix must be fresh and discarded per case')
        mapping=row['local_to_original_slots']
        evaluations=row['evaluations']
        if len(evaluations)!=2 or [x['gauge_check'] for x in evaluations]!=[True,False]:
            raise ValueError('exact fresh BRS then physical evaluation required')
        anchor=row['original_momenta_gev']
        for evaluation in evaluations:
            if evaluation['momenta_gev'] != [anchor[i-1] for i in mapping]:
                raise ValueError('native silently resampled/reordered the anchored point')
            witness.phase_space(evaluation,spec,c['energy_gev'])
            witness.effective_card(evaluation['model_point'],supplied)
            if evaluation['model_point'] != native['model_point']:
                raise ValueError('effective parameters/couplings changed between anchored native calls')
            if len(evaluation['helicities'])!=16 or {tuple(v) for v in evaluation['helicities']}!=helicities or len(evaluation['sample']['jamp'])!=16:
                raise ValueError('complete native16-helicity population required')
        basis=evaluations[0]['colour_basis']
        if (not isinstance(basis,list) or not basis or any(not isinstance(v,str) or not v for v in basis)
                or len(set(basis))!=len(basis)):
            raise ValueError('complete unique ordered native colour basis required')
        if evaluations[0]['helicities']!=evaluations[1]['helicities'] or basis!=evaluations[1]['colour_basis'] or len(basis)!=len(evaluations[0]['sample']['jamp'][0]):
            raise ValueError('native colour/helicity basis differs between BRS and physical calls')
        calls=row['actual_ward_calls']
        if len(calls)!=1:
            raise ValueError('one observed first-eligible native replacement required')
        matched=re.search(r'\bvxxxxx\(\s*p\[(\d+)\]\s*,\s*ZERO\s*,\s*4\s*,',calls[0]['generated_call'])
        if matched is None or int(matched[1])+1!=calls[0]['local_slot'] or calls[0]['local_slot'] not in (1,2) or calls[0]['original_slot']!=mapping[calls[0]['local_slot']-1]:
            raise ValueError('actual writer replacement/original-slot mapping differs')
        ratios=sample_ratios(evaluations[1]['sample'],evaluations[0]['sample'])
        results.append({'seed':row['seed'],'original_gluon_slot':calls[0]['original_slot'],**ratios})
        by_seed.setdefault(row['seed'],[]).append((row['original_momenta_gev'],calls[0]['original_slot'],evaluations[1]['sample']['m2']))
    for seed,rows in by_seed.items():
        if len(rows)!=2 or rows[0][0]!=rows[1][0] or {r[1] for r in rows}!={1,2}:
            raise ValueError('each original incoming gluon must be observed exactly once at the same point')
        if witness.consistency([r[2] for r in rows])>=EXCHANGE_LIMIT:
            raise ValueError('physical incoming exchange consistency failed')
    return {'passed':all(r['passed'] for r in results),'checks':results,'observed_original_slots_per_seed':{str(seed):[1,2] for seed in c['seeds']},'physics_validated':False}

def run(task, base, output):
    rd, selected=_approved(task,output)
    path,config,nested,c,original,zero=_load(task,base)
    if c['max_seconds']>selected['max_seconds']:
        raise ValueError('native Ward work exceeds approved supervisor budget')
    files=inputs(task,base);before={str(p):bridge._hash(p) for p in files}
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True)
    work=rd/'work/model-ward'/out.name
    if work.exists() or any(p.is_symlink() for p in (work,*work.parents)):
        raise ValueError('fresh regular Ward workspace required')
    work.mkdir(parents=True)
    bridge._copy(c['runtime']['madgraph_tree'],nested.parent,work/'madgraph')
    bridge._copy(c['model_tree'],nested.parent,work/'model_source')
    shutil.copyfile(zero,work/'param_card.dat')
    request={'config':c,'madgraph':str(work/'madgraph'),'model':str(work/'model_source'),'card':str(work/'param_card.dat'),'source_sha256':before[str(path)]}
    bridge._write(out/'native-input.json',request)
    from ravel.physics.reinterpret_db import execute_native
    receipt=execute_native([str(bridge._pin(c['runtime']['python'],nested.parent)),'-I','-B',str(Path(__file__).resolve()),'--native-worker',str(out/'native-input.json'),'--out',str(out)],out,c)
    native=bridge._read(out/'native-ward-checks.json')
    if native['source_sha256']!=before[str(path)] or native['card_sha256']!=c['parameter_card']['sha256']:
        raise ValueError('Ward native output source/card identity differs')
    allowed=dict(before)
    for spec,copied in ((c['runtime']['madgraph_tree'],work/'madgraph'),(c['model_tree'],work/'model_source')):
        root,_,_=bridge._tree(spec,nested.parent)
        allowed.update({str(copied/name):digest for name,digest in bridge.source_tree(root)['files'].items()})
    bridge.imported_sources(native['imported_source_files'],allowed)
    checks=adjudicate(native,c,zero.read_text())
    if before!={str(p):bridge._hash(p) for p in inputs(task,base)}:
        raise ValueError('original source/runtime/card bytes or membership changed')
    result={'status':'passed' if checks['passed'] else 'failed','scope':SCOPE,'source':config['source'],'checks':checks,'original_parameter_card_sha256':bridge._hash(original),'diagnostic_parameter_card_sha256':bridge._hash(zero),'explicit_width_changes':diagnostic_lineage(original.read_text(),zero.read_text()),'native_execution':receipt,'generated_events':0,'physics_validated':False,'limitations':['Only two incoming massless gluon slots for supplied tree gg→ttbar at retained points/card; no massive-vector, loop, full-model or UV certification.','An explicit zero-width diagnostic is distinct from the original finite-width supplied-SM Lorentz/permutation study.','p/E polarization convention is installed MG5 Python HELAS convention; no absolute amplitude reference or independent generator result.','All colour columns must be nonzero for nonvacuous diagnostic; original MG5 silent skip of zero columns is narrowed to refusal.','General UFO/process, event/decay/shower/detector/likelihood validity remain separate.']}
    bridge._write(out/'result.json',result)
    return result

def _executed_helicities(generated, expected_class, pre_export, jamp):
    """Observe the exact generated smatrix loop, before writer-mutated metadata."""
    if not isinstance(expected_class,type) or type(generated) is not expected_class:
        raise ValueError('actual fresh generated Matrix instance required')
    rows=getattr(generated,'helEvals',None)
    if not isinstance(rows,list) or len(rows)!=len(jamp):
        raise ValueError('actual executed helicity/JAMP row census differs')
    labels=[]
    for row in rows:
        if (not isinstance(row,list) or len(row)!=2 or not isinstance(row[0],list)
                or len(row[0])!=4 or any(type(v) is not int or v not in (-1,1) for v in row[0])):
            raise ValueError('actual executed four-leg helicity labels required')
        labels.append(list(row[0]))
    if labels!=pre_export:
        raise ValueError('executed helicities differ from pre-export ordered census')
    return labels

def native_worker(request,out):
    """Owned native process only; tests never import/evaluate MG5 or a UFO."""
    import random
    os.environ.pop('HOME',None)
    sys.path.insert(0,request['madgraph'])
    from models import import_ufo
    from models.model_reader import ModelReader
    from madgraph.core import base_objects
    from madgraph.various import process_checks
    from madgraph.iolibs import helas_call_writers
    c=bridge.validate_config(request['config'])
    model=import_ufo.import_model(request['model'],restrict=False,complex_mass_scheme=False)
    supplied=witness.card_values(Path(request['card']).read_text())
    if any((p.lhablock.lower(),tuple(p.lhacode)) not in supplied for p in model.get('parameters')[('external',)]):
        raise ValueError('full supplied card required; no UFO external defaults')
    reader=ModelReader(model);reader.set_parameters_and_couplings(request['card'],complex_mass_scheme=False)
    snapshot=bridge._snapshot(reader);witness.effective_card(snapshot,supplied)
    if any(value!=0 for (block,_),value in supplied.items() if block=='decay'):
        raise ValueError('native process requires explicit zero-width diagnostic card')
    for pdg,spin in ((21,3),(6,2),(-6,2)):
        if model.get_particle(pdg) is None or model.get_particle(pdg).get('spin')!=spin:
            raise ValueError('supplied source external-spin scope differs')
    def process(mapping):
        ids=[21,21,6,-6]
        legs=base_objects.LegList([base_objects.Leg({'id':ids[i-1],'state':local>=2,'number':local+1}) for local,i in enumerate(mapping)])
        return base_objects.Process({'legs':legs,'model':model,'orders':c['processes'][0]['orders'],'forbidden_particles':[]})
    cases=[];options={'energy':c['energy_gev'],'events':None,'skip_evt':0}
    for seed in c['seeds']:
        random.seed(seed)
        anchor_evaluator=process_checks.MatrixElementEvaluator(model,param_card=request['card'],auth_skipping=False,reuse=False)
        anchor,_=anchor_evaluator.get_momenta(process(MAPS[0]),options)
        anchor=[list(v) for v in anchor]
        for mapping in MAPS:
            process_checks.clean_added_globals(process_checks.ADDED_GLOBAL)
            baseline=set(process_checks.__dict__)
            fixed=[list(anchor[i-1]) for i in mapping];evaluations=[];calls=[]
            original_writer=helas_call_writers.PythonUFOHelasCallWriter
            class ObservedWriter(original_writer):
                def get_matrix_element_calls(self,matrix_element,gauge_check=False):
                    result=super().get_matrix_element_calls(matrix_element,gauge_check=gauge_check)
                    if gauge_check:
                        for call in result:
                            matched=re.search(r'\bvxxxxx\(\s*p\[(\d+)\]\s*,\s*ZERO\s*,\s*4\s*,',call)
                            if matched:
                                slot=int(matched[1])+1
                                calls.append({'local_slot':slot,'original_slot':mapping[slot-1],'generated_call':call})
                    return result
            class AnchoredEvaluator(process_checks.MatrixElementEvaluator):
                def evaluate_matrix_element(self,matrix_element,*args,**kwargs):
                    if args or kwargs.get('p') not in (None,fixed):
                        raise ValueError('native helper supplied an unexpected independent point')
                    kwargs['p']=[list(v) for v in fixed]
                    pre_export_helicities=[list(v) for v in matrix_element.get_helicity_matrix()]
                    result=super().evaluate_matrix_element(matrix_element,**kwargs)
                    if not isinstance(result,dict) or set(result)!= {'m2','jamp'}:
                        raise ValueError('nonvacuous raw native JAMP output required')
                    proc=matrix_element.get('processes')[0]
                    legs=sorted(proc.get('legs'),key=lambda leg:leg.get('number'))
                    pdgs=[leg.get('id') for leg in legs]
                    helicities=_executed_helicities(process_checks.__dict__.get('data'),
                        process_checks.__dict__.get('Matrix_'+proc.shell_string()),pre_export_helicities,result['jamp'])
                    evaluations.append({'gauge_check':kwargs['gauge_check'],'momenta_gev':kwargs['p'],'ordered_leg_pdgs':pdgs,'ordered_leg_states':[leg.get('state') for leg in legs],'effective_orders':dict(proc.get('orders')),'effective_forbidden_pdgs':list(proc.get('forbidden_particles')),'effective_perturbation_couplings':list(proc.get('perturbation_couplings')),'effective_masses_gev':{str(pdg):self.full_model.get_mass(pdg) for pdg in pdgs},'model_point':bridge._snapshot(self.full_model),'helicities':helicities,'helicity_provenance':{'source':'actual_generated_Matrix.smatrix.helEvals','pre_export_matrix':pre_export_helicities,'post_writer_matrix':[list(v) for v in matrix_element.get_helicity_matrix()]},'colour_basis':[repr(key) for key in sorted(matrix_element.get('color_basis'))],'sample':{'m2':float(result['m2']),'jamp':[[bridge._complex(value) for value in row] for row in result['jamp']]}})
                    return result
            evaluator=AnchoredEvaluator(model,param_card=request['card'],auth_skipping=False,reuse=False)
            evaluator.helas_writer=ObservedWriter(model)
            checked=process_checks.check_gauge_process(process(mapping),evaluator,options=options)
            if checked is None:
                raise ValueError('native Ward helper returned no nonvacuous diagrams/result')
            added=sorted(set(process_checks.__dict__)-baseline)
            process_checks.clean_added_globals(process_checks.ADDED_GLOBAL)
            for name in added:
                process_checks.__dict__.pop(name,None)
            cases.append({'seed':seed,'local_to_original_slots':mapping,'original_momenta_gev':anchor,'actual_ward_calls':calls,'evaluations':evaluations,'reuse_generated_matrix':False,'discarded_generated_globals':added})
    imported={}
    for module in tuple(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if filename:
            path=Path(filename).resolve()
            if path.is_file():imported[str(path)]=bridge._hash(path)
    payload={'schema_version':1,'source_sha256':request['source_sha256'],'card_sha256':bridge._hash(request['card']),'restriction_applied':False,'generated_events':0,'polarization_normalization':'massless_vxxxxx_nhel4_is_p_over_E','total_ratio_limit':TOTAL_RATIO_LIMIT,'colour_ratio_limit':COLOUR_RATIO_LIMIT,'model_point':snapshot,'cases':cases,'native_python_version':sys.version,'imported_source_files':[{'path':path,'sha256':digest} for path,digest in sorted(imported.items())]}
    bridge._write(Path(out)/'native-ward-checks.json',payload)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-worker',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args()
    native_worker(bridge._read(args.native_worker),args.out)
