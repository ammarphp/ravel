#!/usr/bin/env python3
"""Run the analytic test fixtures through real approved CLI lifecycle machinery.

Validation harness: requires a repository checkout with the [test,science,measurement,classifier] extras.
This measures adapter delivery on synthetic fixtures, not independent physics validation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/p) for p in ('src','tests/unit')]
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json, read_json
import test_scientific_quantities as q
import test_measurement as m
import test_domain_adapters as d
import test_existing_events as r


def prepare(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    data=root/'inputs';data.mkdir()
    cases=[]
    def case(name,mode,task,expected='passed'):
        spec={'schema_version':1,'mode':mode,'source':'Synthetic engineering fixture: '+name+'. No physics prediction or paper closure.',
              'assumptions':['Synthetic analytic or boundary input. Agreement tests only the declared operation.',
                             'Scripted assent is experimental consent, not expert scientific review.'],
              'max_seconds':45,'approval_mode':'scripted_yes','task':task}
        p=data/(name+'-spec.json');atomic_json(p,spec)
        cases.append({'name':name,'spec':str(p),'expected':expected})
    def write(name,obj): atomic_json(data/name,obj); return name
    write('quantity-contract.json',q.contract(normalization={'kind':'normalized','scope':'all_events'},representation='differential'))
    rows=[q.event('a',[[.5]],2),q.event('b',[],-1),q.event('c',[[2]],3,shard='b')]
    (data/'quantity-records.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in rows))
    case('signed-density','quantities',{'contract':'quantity-contract.json','records':'quantity-records.jsonl'})
    for name,model,cap in [('correlated-measurement',m.document(),20),('normalized-measurement',m.normalized_document(),10),('bounded-measurement',m.document(),.01)]:
        file=write(name+'.json',model)
        case(name,'measurement',m.task(input=file,inference='spey_cls',poi_max=cap),'failed' if cap<1 else 'passed')
    eftdir=data/'eft';eftdir.mkdir()
    eft,basis=d.eft.__wrapped__(eftdir)
    case('eft-interference','domain',eft)
    bad=deepcopy(basis);bad['controls'][0]['values'][0]+=1
    file=write('eft-bad-control.json',bad);bad_spec=deepcopy(eft);bad_spec['config']['basis_file']=file
    case('eft-failed-control','domain',bad_spec,'failed')
    ufodir=data/'ufo';ufodir.mkdir()
    model,_,_=d.ufo.__wrapped__(ufodir)
    case('model-structure','domain',model)
    nndir=data/'classifier';nndir.mkdir()
    nn,_=d.classifier_fixture(nndir)
    case('classifier','domain',nn)
    llpdir=data/'llp';llpdir.mkdir()
    case('llp-decay','domain',d.llp(llpdir,[d.event([d.momentum()])],geometry={'r_min_mm':10,'r_max_mm':20,'z_half_mm':30},combination='all'))
    lifedir=data/'lifetime';lifedir.mkdir()
    case('llp-reweight','domain',d.llp(lifedir,[d.event([{'proper_length_mm':5,'right_censored':False}])],'reweight',source_ctau={'value':5,'unit':'mm'}))
    mapdir=data/'efficiency-map';mapdir.mkdir()
    mapping,_,_=d.efficiency_map_fixture(mapdir)
    case('efficiency-map','domain',mapping)
    nuc={'beam_mass_numbers':[208,208],'sqrt_sNN_GeV':5020,'centrality_percent':[0,10],'centrality_definition':'synthetic estimator',
         'event_exposure':100,'observable_unit':'GeV','source':'analytic control','bins':[{'low':0,'high':1,'sumw':100,'sumw2':100},{'low':1,'high':3,'sumw':100,'sumw2':100}]}
    forward={'plane_z_mm':1000,'radius_mm':10,'transport':'neutral-straight-line-vacuum','source':'analytic geometry',
         'events':[{'event_id':'one','weight':2,'x_mm':0,'y_mm':0,'z_mm':0,'px_GeV':1,'py_GeV':0,'pz_GeV':100,'charge':0}]}
    for name,family,doc in [('nuclear-normalization','heavy-ion',nuc),('forward-acceptance','forward',forward),('neutrino-fold','neutrino',d.neutrino_data())]:
        file=write(name+'.json',doc)
        case(name,'domain',{'domain':'applicability','config':{'family':family,'data_file':file}})
    write('selection.json',r.selection());write('objects.json',r.contract())
    write('reconstructed.json',[r.event('1',[r.obj(pt=20),r.obj(pt=20,phi=3.141592653589793)]),r.event('2',[r.obj(eta=2.5)]),r.event('3',weight=-.5)])
    write('reference-decisions.json',{'source':'analytic boundary expectation','events':[{'event_id':'1','regions':['dilepton']},{'event_id':'2','regions':['zero_lepton']},{'event_id':'3','regions':['zero_lepton']}]})
    case('reconstructed-selection','analyze',{'backend':'native-selection','events':'reconstructed.json','selection':'selection.json','object_contract':'objects.json','reference':'reference-decisions.json'})
    atomic_json(root/'cases.json',{'scope':'synthetic analytic controls, not independent physics evidence','cases':cases})
    return cases


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--execute',action='store_true')
    ap.add_argument('--assent',help='Actual authorization for scripted affirmative controls')
    a=ap.parse_args()
    if a.execute and not a.assent: ap.error('--execute requires the actual authorized --assent text')
    cases=prepare(a.out)
    if not a.execute:
        print(f'Prepared {len(cases)} proposals; no calculations executed.');return 0
    rows=[]
    for c in cases:
        rd=a.out.resolve()/'runs'/c['name'];print('CONTROL '+c['name'],flush=True)
        try:
            science.plan(rd,c['spec']);science.approve(rd,a.assent,scripted=True);code=science.run(rd)
            p=science.packet(rd)
            result=read_json(rd/'outputs/result.json') if (rd/'outputs/result.json').is_file() else {}
            actual='passed' if p['lifecycle_verdict']=='PASS' else 'failed' if result.get('status')=='failed' else 'execution_error'
            entry={**c,'actual':actual,'expected_observed':actual==c['expected'],'exit':code,'packet':p}
        except (ValueError,OSError,RuntimeError) as exc:
            entry={**c,'actual':'admission_error','expected_observed':False,'error':str(exc)}
        rows.append(entry);atomic_json(a.out/'results.json',{'scope':'synthetic adapter controls only','results':rows})
        print(entry['actual'],flush=True)
    return 0 if all(x['expected_observed'] for x in rows) else 1


if __name__=='__main__':sys.exit(main())
