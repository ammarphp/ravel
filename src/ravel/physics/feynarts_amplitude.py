"""Explicit admitted FeynArts model -> complete FeynCalc amplitude population.

Uses the existing fresh-kernel symbolic lifecycle. FeynArts and model files
must already be source-bound FeynCalc-patched copies; no global installer runs.
"""
import argparse
import json
from pathlib import Path
import re
from ravel.physics import feyn_graph as fg, model_tool_bridge as custody

SCOPE='source_bound_feynarts_amplitude_delivery'
def process(p):
    fg.keys(p,('id','incoming','outgoing','loops','incoming_momenta','outgoing_momenta','loop_momenta','adjacencies','max_diagrams','render_pdf'),'FeynArts process')
    if type(p['id']) is not str or re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',p['id']) is None:raise ValueError('unique amplitude identity required')
    fg.integer(p['loops'],0,3);fg.integer(p['max_diagrams'],1,4096)
    for key,mom in [('incoming','incoming_momenta'),('outgoing','outgoing_momenta')]:
        if type(p[key]) is not list or not 1<=len(p[key])<=8 or type(p[mom]) is not list or len(p[mom])!=len(p[key]):raise ValueError('ordered field/momentum census required')
        for f in p[key]:
            fg.keys(f,('type','index','indices','antiparticle'),'source model field')
            if f['type'] not in ('S','F','V','U','T') or type(f['antiparticle']) is not bool:raise ValueError('explicit native field kind/sign required')
            fg.integer(f['index'],1,10000)
            if type(f['indices']) is not list or len(f['indices'])>8:raise ValueError('literal model generation indices required')
            for x in f['indices']:fg.integer(x,1,10000)
    if type(p['loop_momenta']) is not list or len(p['loop_momenta'])!=p['loops']:raise ValueError('full loop momentum population required')
    names=p['incoming_momenta']+p['outgoing_momenta']+p['loop_momenta']
    if any(type(x) is not str or re.fullmatch('[A-Za-z][A-Za-z0-9]*',x) is None for x in names) or len(set(names))!=len(names):raise ValueError('unique explicit momentum symbols required')
    if type(p['adjacencies']) is not list or not p['adjacencies'] or len(set(p['adjacencies']))!=len(p['adjacencies']):raise ValueError('explicit vertex adjacency scope required')
    for x in p['adjacencies']:fg.integer(x,3,8)
    if type(p['render_pdf']) is not bool:raise ValueError('explicit native rendering choice required')
    return p

def addon(a):
    fg.keys(a,('version','tree','entry','model_tree','classes_model','generic_model','patched_source_receipt'),'FeynArts component')
    if a['version']!='3.12' or a['entry']!='FeynArts.m':raise ValueError('released FeynArts3.12 required')
    for x in ('classes_model','generic_model'):
        if type(a[x]) is not str or re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',a[x]) is None:raise ValueError('explicit admitted native model name required')
    return a

def source_inputs(a,base):
    addon(a);root,manifest,members=custody._tree(a['tree'],base);models,mm,modelmembers=custody._tree(a['model_tree'],base);receipt=custody._pin(a['patched_source_receipt'],base)
    if not (root/a['entry']).is_file() or 'patched for use with feyncalc' not in (root/a['entry']).read_text().lower():raise ValueError('explicit prepatched FeynArts source required; no auto patching in evaluation')
    for name,ext in ((a['classes_model'],'.mod'),(a['generic_model'],'.gen')):
        if not (models/(name+ext)).is_file():raise ValueError('selected classes/generic model file missing')
    from ravel.workflow.operation_resources import document
    r=document(receipt);fg.keys(r,('schema_version','operation','upstream_archive_sha256','feyncalc_revision','feynarts_files','model_files','source','physics_validated'),'source patch receipt')
    api=document(fg.API)['feynarts']
    if type(r['schema_version']) is not int or r['schema_version']!=1 or r['operation']!='FeynCalc_FAPatch_source_preparation' or r['upstream_archive_sha256']!=api['archive_sha256'] or r['feyncalc_revision']!=api['feyncalc_revision'] or r['physics_validated'] is not False:raise ValueError('explicit released patch/source provenance required')
    if r['feynarts_files']!=custody.source_tree(root) or r['model_files']!=custody.source_tree(models):raise ValueError('patch receipt differs from full admitted current trees')
    return root,models,[manifest,*members,mm,*modelmembers,receipt]

def field(f):return ('-' if f['antiparticle'] else '')+f['type']+'['+str(f['index'])+(',{'+','.join(map(str,f['indices']))+'}' if f['indices'] else '')+']'
def script(p):
    process(p);arr=lambda x:'{'+','.join(x)+'}'
    return ('ravelTopologies=CreateTopologies['+str(p['loops'])+','+str(len(p['incoming']))+'->'+str(len(p['outgoing']))+',Adjacencies->{'+','.join(map(str,p['adjacencies']))+'}];\n'
      'ravelInserted=InsertFields[ravelTopologies,'+arr([field(x) for x in p['incoming']])+'->'+arr([field(x) for x in p['outgoing']])+',Model->ravelClassesModel,GenericModel->ravelGenericModel,InsertionLevel->{Particles}];\n'
      'ravelFeynAmps=CreateFeynAmp[ravelInserted,AmplitudeLevel->{Particles},Truncated->False];\n'
      'ravelNativeDiagramCount=Length[ravelFeynAmps];\n'
      'If[!IntegerQ[ravelNativeDiagramCount]||ravelNativeDiagramCount>'+str(p['max_diagrams'])+',Abort[]];\n'
      'ravelConverted=FCFAConvert[ravelFeynAmps,IncomingMomenta->'+arr(p['incoming_momenta'])+',OutgoingMomenta->'+arr(p['outgoing_momenta'])+',LoopMomenta->'+arr(p['loop_momenta'])+',List->True,DropSumOver->False,ChangeDimension->False,UndoChiralSplittings->False];\n'
      'If[Length[ravelConverted]=!=ravelNativeDiagramCount,Abort[]];\n'
      'ravelAmplitude=Total[ravelConverted];\n'
      'ravelFARecords=<|"diagram_count"->ravelNativeDiagramCount,"topologies"->ToString[ravelTopologies,InputForm,PageWidth->Infinity],"insertions"->ToString[ravelInserted,InputForm,PageWidth->Infinity],"original_amplitudes"->ToString[ravelFeynAmps,InputForm,PageWidth->Infinity],"converted_amplitudes"->(ToString[#,InputForm,PageWidth->Infinity]&/@ravelConverted)|>;\n'
      +('Export[ravelDiagramPDF,Paint[ravelInserted,DisplayFunction->Identity],"PDF"];\n' if p['render_pdf'] else '')+
      'Print["SYMBOLIC_RESULT['+p['id']+']: ",InputForm[ravelAmplitude]];\nPrint["LATEX_RESULT['+p['id']+']: ",TeXForm[ravelAmplitude]];\nPrint["STATUS: complete"];\n')

def validate(task):
    from ravel.physics import symbolic_evaluation as s
    return s.validate(task)
def inputs(task,base):
    from ravel.physics import symbolic_evaluation as s
    p,c=s._load(task,base)
    if c['schema_version']!=2:raise ValueError('FeynArts requires explicit component schema2')
    return s.inputs(task,base)
def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{});scopes=policy.get('claim_scopes',{})
    if spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']:raise ValueError('one-attempt source amplitude delivery scope required')
    return spec
def execution_seconds(task,base):
    from ravel.physics import symbolic_evaluation as s
    return s.execution_seconds(task,base)
def run(task,base,output):
    inputs(task,base)
    from ravel.physics import symbolic_evaluation as s
    return s.run(task,base,output)
def finalize(result,output):
    from ravel.physics import symbolic_evaluation as s
    return s.finalize(result,output)
def write_report(result,output):
    from ravel.physics import symbolic_evaluation as s
    return s.write_report(result,output)
def context_inputs(task,base):
    from ravel.physics import symbolic_evaluation as s
    inputs(task,base);return sorted(set([Path(__file__),*s.context_inputs(task,base)]))
def context(task,base):
    from ravel.physics import symbolic_evaluation as s
    p,c=s._load(task,base);return {'schema_version':1,'mode':'feynarts-amplitude','configuration':c,'scope':SCOPE,'physics_validated':False,'execution_authorized':False}
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('script','inspect'));parser.add_argument('--input',required=True);parser.add_argument('--input-sha256');parser.add_argument('--output');a=parser.parse_args(argv)
    from ravel.workflow.operation_resources import document
    if a.command=='script':
        if not a.output:raise ValueError('explicit fresh output path required')
        fg.write_bytes(a.output,script(document(Path(a.input))).encode());return 0
    if not a.input_sha256:raise ValueError('exact request pin required')
    task={'input':a.input,'input_sha256':a.input_sha256};print(json.dumps({'mode':'feynarts-amplitude','inputs':len(inputs(task,Path.cwd())),'execution_authorized':False},indent=2));return 0
