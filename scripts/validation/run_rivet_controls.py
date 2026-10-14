#!/usr/bin/env python3
"""Prepare a supplied control suite; execute through the approved science lifecycle."""
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from ravel.workflow.state_io import atomic_json,read_json
from ravel.workflow import science

class MissingControlInput(ValueError):
    """A control suite must be supplied explicitly."""
    reason = 'missing_control_input'


def load_suite(path):
    """Schema1 selects synthetic kinematics; schema2 selects complete supplied specs."""
    if path is None:
        raise MissingControlInput('explicit control manifest required')
    from ravel.workflow.state_io import _unique
    with open(path) as stream:
        document = json.load(stream, object_pairs_hook=_unique,
                             parse_constant=lambda value: (_ for _ in ()).throw(ValueError('finite JSON required')))
    if type(document) is not dict or type(document.get('schema_version')) is not int:
        raise MissingControlInput('control manifest schema required')
    if document['schema_version'] == 1:
        return {'schema_version': 1, 'cases': load_cases(path)}
    if document['schema_version'] != 2 or set(document) != {'schema_version', 'cases', 'report'}:
        raise MissingControlInput('schema2 cases and report required')
    report = document['report']
    if type(report) is not dict or set(report) != {'path', 'format'}:
        raise MissingControlInput('explicit report path and format required')
    if report['format'] not in ('json', 'jsonl'):
        raise ValueError('report format must be json or jsonl')
    if type(report['path']) is not str or not report['path']:
        raise MissingControlInput('explicit report path required')
    dest = Path(report['path'])
    if dest.is_absolute() or '..' in dest.parts or not dest.parts or dest.parts[0] in ('inputs', 'runs', 'cases.json'):
        raise ValueError('report must be a relative output path outside inputs and runs')
    cases = document['cases']
    if type(cases) is not list or not 1 <= len(cases) <= 4096:
        raise MissingControlInput('finite supplied control population required')
    import re
    names = set()
    resolved = []
    for row in cases:
        if type(row) is not dict or set(row) != {'name', 'spec', 'expected'}:
            raise MissingControlInput('explicit name, spec and expected required')
        if type(row['name']) is not str or re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,100}', row['name']) is None or row['name'] in names:
            raise ValueError('distinct safe control name required')
        names.add(row['name'])
        if type(row['spec']) is not str or not row['spec']:
            raise MissingControlInput('explicit scientific spec required')
        spec = Path(row['spec'])
        spec = spec if spec.is_absolute() else Path(path).resolve().parent / spec
        if not spec.is_file():
            raise MissingControlInput('selected scientific spec missing')
        if row['expected'] not in ('passed', 'normalization_failure', 'execution_error', 'admission_error'):
            raise ValueError('explicit expected control outcome required')
        resolved.append({**row, 'spec': str(spec.resolve())})
    return {**document, 'cases': resolved}


def execute_cases(root, cases, assent, report):
    """Run only through plan/admission/approval and preserve all failed case slots."""
    results = []
    destination = root / report['path']
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError('control report destination already exists')
    for c in cases:
        print('CONTROL ' + c['name'], flush=True)
        rd = root / 'runs' / c['name']
        try:
            science.plan(rd, c['spec'])
            # Internal validation launches record a bounded machine method decision before approval.
            from ravel.workflow import method_selection
            spec = read_json(rd / science.SPEC)
            method_selection.record_validation_decision(rd,
                required_output=spec['source'], max_seconds=spec['max_seconds'],
                evidence=[science.SPEC], operation=spec['mode'], authority='scripted_experiment')
            science.approve(rd, assent, scripted=True)
            code = science.run(rd)
            packet = science.packet(rd)
            log = (rd/'outputs/export.log').read_text() if (rd/'outputs/export.log').is_file() else ''
            actual = ('passed' if packet['lifecycle_verdict'] == 'PASS' else 'normalization_failure'
                      if 'normalized observable does not have unit integrated area' in log else 'execution_error')
            row = {**c, 'actual': actual, 'exit': code, 'packet': packet, 'expected_observed': actual == c['expected']}
        except (OSError, ValueError, RuntimeError) as exc:
            # Admission failures remain failures; an expectation never grants approval.
            row = {**c, 'actual': 'admission_error', 'error': str(exc),
                   'reason': getattr(exc, 'reason', 'control_admission_error'),
                   'expected_observed': c['expected'] == 'admission_error'}
        results.append(row)
        if report['format'] == 'json':
            atomic_json(destination, {'scope': 'supplied controls only; no scientific acceptance', 'results': results})
        else:
            with destination.open('a') as stream:
                stream.write(json.dumps(row, allow_nan=False) + '\n')
        print(row['actual'], flush=True)
    return 0 if all(r['expected_observed'] for r in results) else 1


def load_cases(path):
    if path is None:
        raise MissingControlInput('explicit control manifest required')
    from ravel.workflow.state_io import _unique
    import json, re
    with open(path) as stream:
        document=json.load(stream,object_pairs_hook=_unique)
    if type(document) is not dict or set(document)!={'schema_version','cases'} or type(document['schema_version']) is not int or document['schema_version']!=1:
        raise ValueError('control manifest schema1 required')
    cases=document['cases']
    if type(cases) is not list or not 1<=len(cases)<=128:
        raise ValueError('finite supplied control population required')
    names=set()
    for row in cases:
        if type(row) is not dict or set(row)!={'name','energy','kind','observable','unit','normalized','grouped','expected'}:
            raise MissingControlInput('complete control row required')
        name=row['name']
        if type(name) is not str or re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,100}',name) is None or name in names:
            raise ValueError('distinct safe control name required')
        names.add(name)
        if type(row['energy']) not in (int,float) or not math.isfinite(row['energy']) or row['energy']<=0:
            raise ValueError('finite positive beam energy required')
        if row['kind'] not in ('dy','zz','jets') or type(row['normalized']) is not bool or type(row['grouped']) is not bool:
            raise ValueError('explicit kinematics and grouping required')
        for field in ('observable','unit'):
            if type(row[field]) is not str or not row[field].strip():raise MissingControlInput('explicit '+field+' required')
        if row['expected'] not in ('passed','normalization_failure','execution_error'):
            raise ValueError('explicit expected control outcome required')
    return cases


def events(energy,kind):
    if kind not in ('dy','zz','jets'):raise ValueError('unsupported synthetic kinematics')
    if not math.isfinite(energy) or energy<=0:raise ValueError('positive finite beam energy required')
    lines=['HepMC::Version 3.03.01','HepMC::Asciiv3-START_EVENT_LISTING','W nominal']
    for eid,v in enumerate((1.,1.1)):
        groups=([(23,[(11,75*v,0,0),(-11,-75*v,0,0)])] if kind=='dy' else
                [(23,[(11,60*v,0,0),(-11,-30*v,0,0)]),(23,[(13,0,60*v,0),(-13,0,-30*v,0)])] if kind=='zz' else
                [(0,[(211,180*v,0,0),(-211,-180*v,0,0)])])
        finals=[p for _,parts in groups for p in parts]
        en=lambda p:math.sqrt(p[1]**2+p[2]**2+p[3]**2)
        rem_e=energy-sum(en(p) for p in finals)/2
        rem_x=-sum(p[1] for p in finals)/2; rem_y=-sum(p[2] for p in finals)/2
        rem_z=math.sqrt(rem_e**2-rem_x**2-rem_y**2)
        resonances=sum(pid!=0 for pid,_ in groups)
        lines += [f'E {eid} {1+resonances} {4+len(finals)+resonances}','U GEV MM','W 1','A 0 GenCrossSection 1 0 -1 -1',
           f'P 1 0 2212 0 0 {energy} {energy} 0 4',f'P 2 0 2212 0 0 {-energy} {energy} 0 4','V -1 0 [1,2]',
           f'P 3 -1 2212 {rem_x} {rem_y} {rem_z} {rem_e} 0 1',f'P 4 -1 2212 {rem_x} {rem_y} {-rem_z} {rem_e} 0 1']
        counter=5;vertices=[];children=[]
        for pid,parts in groups:
            if pid:
                e=sum(en(p) for p in parts);px=sum(p[1] for p in parts);py=sum(p[2] for p in parts);pz=sum(p[3] for p in parts)
                mass=math.sqrt(e*e-px*px-py*py-pz*pz)
                lines.append(f'P {counter} -1 {pid} {px} {py} {pz} {e} {mass} 2')
                vertices.append((counter,parts));counter+=1
            else: children+=parts
        for p in children:
            lines.append(f'P {counter} -1 {p[0]} {p[1]} {p[2]} {p[3]} {en(p)} 0 1');counter+=1
        for v,(parent,parts) in enumerate(vertices,start=2):
            lines.append(f'V {-v} 0 [{parent}]')
            for p in parts:
                lines.append(f'P {counter} {-v} {p[0]} {p[1]} {p[2]} {p[3]} {en(p)} 0 1');counter+=1
    return '\n'.join(lines+['HepMC::Asciiv3-END_EVENT_LISTING'])+'\n'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--runtime',type=Path)
    ap.add_argument('--source',type=Path);ap.add_argument('--execute',action='store_true')
    ap.add_argument('--cases',type=Path,required=True)
    ap.add_argument('--assent');a=ap.parse_args()
    try:
        suite = load_suite(a.cases)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    supplied_cases = suite['cases']
    if a.execute and not a.assent:ap.error('--execute requires the actual authorized --assent text')
    if suite['schema_version'] == 1 and (a.runtime is None or a.source is None):
        ap.error('schema1 synthetic kinematics require --runtime and --source')
    if suite['schema_version'] == 2:
        root = a.out.resolve(); root.mkdir(parents=True, exist_ok=False)
        atomic_json(root/'cases.json', suite)
        if not a.execute:
            print('Prepared ' + str(len(supplied_cases)) + ' supplied proposals; no compute launched.')
            return 0
        return execute_cases(root, supplied_cases, a.assent, suite['report'])
    root=a.out.resolve();root.mkdir(parents=True,exist_ok=False);data=root/'inputs';data.mkdir()
    runtime=read_json(a.runtime);cases=[]
    for case in supplied_cases:
        name,energy,kind,obs,unit,normalized=(case[k] for k in ('name','energy','kind','observable','unit','normalized'))
        text=events(energy,kind)
        grouped = case['grouped']
        if grouped:
            text=text.replace('W nominal','W nominal\\|scale').replace('E 1 ', 'E 0 ')
            text=text.replace('W 1','W 2 4',1).replace('W 1','W -1 -2',1)
        (data/(name+'.hepmc')).write_text(text)
        atomic_json(data/(name+'-metadata.json'),{'schema_version':1,'event_level':'hadron','beam_pdg':[2212,2212],'beam_energy_gev':[energy,energy],
          'weight_names':['nominal','scale'] if grouped else ['nominal'],'events':2,
          'groups':'correlated_event_number' if grouped else 'independent','cross_section_pb':1.,
          'source':'Hand-constructed balanced massless kinematic fixture with synthetic cross section. No shower, hadronization or physical prediction.'})
        spec={'schema_version':1,'mode':'analyze','source':'Synthetic fixed-event adapter control through unmodified '+name,
          'assumptions':['The events and cross section are synthetic, not a physical prediction.',
             'The pinned routine is compiled against the explicitly declared runtime; no equivalence with another runtime is assumed.'],
          'max_seconds':120,'approval_mode':'scripted_yes','task':{'backend':'rivet','routine':'rivet:'+name,'source_root':str(a.source.resolve()),
          'events':name+'.hepmc','metadata':name+'-metadata.json','runtime':runtime,'options':{},'seed':1729,
          'observables':[{'path':'/'+name+'/'+obs,'axes':[{'name':'mass' if kind=='dy' or normalized else 'transverse momentum','unit':'GeV'}],
              'representation':'differential','normalization':'normalized' if normalized else 'absolute','unit':unit}]}}
        sp=data/(name+'-spec.json');atomic_json(sp,spec)
        cases.append({'name':name,'spec':str(sp),'expected':case['expected']})
    atomic_json(root/'cases.json',{'scope':'synthetic kinematic controls only','cases':cases})
    if not a.execute:print('Prepared '+str(len(cases))+' supplied proposals; no compute launched.');return 0
    return execute_cases(root, cases, a.assent, {'path': 'results.json', 'format': 'json'})


if __name__=='__main__':sys.exit(main())
