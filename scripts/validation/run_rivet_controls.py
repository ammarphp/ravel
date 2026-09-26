#!/usr/bin/env python3
"""Small unmodified-upstream controls on balanced synthetic kinematic records.

These are NOT showered MC predictions or paper reproductions. The CMS ZZ target
is expected to expose the upstream double-width normalization, not be repaired.
"""
import argparse
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from ravel.workflow.state_io import atomic_json,read_json
from ravel.workflow import science

CASES=[('ATLAS_2013_I1234228',3500,'dy','d01-x01-y02','pb/GeV',False),
       ('CMS_2018_I1711625',6500,'dy','d06-x01-y01','pb/GeV',False),
       ('ATLAS_2016_I1494075',4000,'zz','d02-x01-y01','fb/GeV',False),
       ('CMS_2012_I1298807',4000,'zz','d01-x01-y04','1/GeV',True),
       ('ATLAS_2010_I871366',3500,'jets','d01-x01-y01','pb/GeV',False),
       ('CMS_2016_I1459051',6500,'jets','d08-x01-y01','pb/GeV',False)]


def events(energy,kind):
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
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--runtime',type=Path,required=True)
    ap.add_argument('--source',type=Path,required=True);ap.add_argument('--execute',action='store_true')
    ap.add_argument('--assent');a=ap.parse_args()
    if a.execute and not a.assent:ap.error('--execute requires the actual authorized --assent text')
    root=a.out.resolve();root.mkdir(parents=True,exist_ok=False);data=root/'inputs';data.mkdir()
    runtime=read_json(a.runtime);cases=[]
    for name,energy,kind,obs,unit,normalized in CASES:
        text=events(energy,kind)
        grouped = name == 'ATLAS_2013_I1234228'
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
        cases.append({'name':name,'spec':str(sp),'expected':'normalization_failure' if normalized else 'passed'})
    atomic_json(root/'cases.json',{'scope':'synthetic kinematic controls only','cases':cases})
    if not a.execute:print('Prepared six proposals; no compute launched.');return 0
    results=[]
    for c in cases:
        print('CONTROL '+c['name'],flush=True);rd=root/'runs'/c['name']
        try:
            science.plan(rd,c['spec']);science.approve(rd,a.assent,scripted=True);code=science.run(rd)
            packet=science.packet(rd)
            log=(rd/'outputs/export.log').read_text() if (rd/'outputs/export.log').is_file() else ''
            actual='passed' if packet['lifecycle_verdict']=='PASS' else 'normalization_failure' if 'normalized observable does not have unit integrated area' in log else 'execution_error'
            row={**c,'actual':actual,'exit':code,'packet':packet,'expected_observed':actual==c['expected']}
        except (OSError,ValueError,RuntimeError) as exc:
            row={**c,'actual':'admission_error','error':str(exc),'expected_observed':False}
        results.append(row);atomic_json(root/'results.json',{'scope':'synthetic controls, no physical cross sections or paper closure','results':results})
        print(row['actual'],flush=True)
    return 0 if all(r['expected_observed'] for r in results) else 1


if __name__=='__main__':sys.exit(main())
