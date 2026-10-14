"""Strict original-LHA identity transport design for a future admitted MPI run.

This module launches nothing. The existing provenance verifier must recompute
original LHA/HepMC content from actual produced files; supplied counts cannot
stand in for that witness. Source compilation and producer exit custody remain
separately required native-stage evidence.
"""
from __future__ import annotations
import gzip
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def event_ids(values, expected, label):
    require(type(values) is list and len(values) == expected,
            label + ': complete event population required')
    ids=[]
    for value in values:
        if isinstance(value,list):
            require(len(value)==1,label+': exactly one event record per entry required')
            value=value[0]
        require(type(value) in (int,float) and math.isfinite(value)
                and value==int(value),label+': exact integer event identity required')
        ids.append(int(value))
    require(len(set(ids))==expected,label+': duplicate event identity')
    require(ids==list(range(expected)),label+': skipped, reordered or replaced identity')
    return ids


def original_map(expected_manifest, recomputed_provenance):
    """Join exact content first; ordinal offsets never repair a content mismatch."""
    from ravel.validation.diagnostic_plan import required
    required(expected_manifest,'rows')
    n=expected_manifest['subset_exposure']
    require(type(n)is int and n>0,'positive source exposure required')
    require(expected_manifest['full_content_unique']is True,'source identity uniqueness required')
    p=recomputed_provenance
    require(p.get('status')=='content_verified' and p.get('policy')=='original-v1',
            'actual original-LHA content witness required')
    require(p['source_files']['lhe']==expected_manifest['subset_pin'],'original LHE source bytes differ')
    require(p['original_events']==n and p['joined_events']==n,'original content population differs')
    require(p['hepmc_content']['complete_framing']is True and
            p['hepmc_content']['particle_populations_verified']is True,'complete HepMC content required')
    event_ids(p['hepmc_content']['event_numbers'],n,'HepMC')
    expected=expected_manifest['rows']; actual=p['rows']
    require(len(expected)==len(actual)==n,'complete content map required')
    mapped=[]
    for index,(source,produced) in enumerate(zip(expected,actual)):
        require(source['subset_ordinal']==produced['original_lhe_ordinal']==produced['hepmc_event_number']==index,
                'content identity mapping/order differs')
        for key in ('full_content_sha256','original_lhe_event_sha256'):
            require(source[key]==produced[key],'original content differs: '+key)
        require(float(source['original_weight']).hex()==float(produced['original_weight']).hex(),
                'original signed weight identity differs')
        require(source['particle_count']==produced['original_particle_count'],
                'original particle population differs')
        mapped.append({'hepmc_event_number':index,'original_ordinal':source['original_ordinal'],
                       'original_content_sha256':source['full_content_sha256']})
    require(len({r['original_ordinal'] for r in mapped})==n,'original source mapping repeats')
    return mapped


def verify_transport(mapping, delphes_ids, ntuple_ids, trace_ids):
    """Require literal identity preservation at each complete downstream census."""
    n=len(mapping)
    require(n>0,'original content map required before paired transport')
    event_ids([r['hepmc_event_number'] for r in mapping],n,'original map')
    for values,label in ((delphes_ids,'Delphes Event.Number'),(ntuple_ids,'converter ntuple Event'),
                         (trace_ids,'analysis trace event_id')):
        event_ids(values,n,label)
    return {'status':'transport_verified','events':n,'mapping':mapping,
            'identity_basis':'Verified full original LHA content followed by literal complete event-ID transport',
            'paired_MC_statistical_claim':False,
            'scope':'Identity transport only; no MPI effect, normalization, fit or physics validation.'}


def read_downstream_ids(delphes, ntuple, trace):
    """Read only identity branches; do not load the ROOT native runtime."""
    import uproot
    with uproot.open(delphes) as file:
        d=file['Delphes']['Event.Number'].array(library='ak').to_list()
    with uproot.open(ntuple) as file:
        a=file['ntuple']['Event'].array(library='ak').to_list()
    opener=gzip.open if str(trace).endswith('.gz') else open
    with opener(trace,'rt') as stream:
        header=json.loads(next(stream))
        require(header.get('kind')=='header','complete analysis trace header required')
        t=[json.loads(line)['event_id'] for line in stream]
    return d,a,t


def verify_files(*,expected_manifest,lhe,sidecar,hepmc,encoding,delphes,ntuple,trace):
    """Recompute content and transport from actual files in a future native stage.

    The caller's approved stage binds this source, inputs and dependencies. This
    function accepts no supplied success flag or count-only provenance report.
    """
    from ravel.physics import lhe_provenance as provenance
    files={k:Path(v).absolute() for k,v in {
        'expected_manifest':expected_manifest,'lhe':lhe,'sidecar':sidecar,
        'hepmc':hepmc,'delphes':delphes,'ntuple':ntuple,'trace':trace}.items()}
    require(len(set(files.values()))==len(files),'identity artifacts alias')
    before={k:provenance.pin(p) for k,p in files.items()}
    expected=provenance.strict_json(files['expected_manifest'].read_bytes())
    produced=provenance.verify_new_generation(files['lhe'],files['sidecar'],files['hepmc'],
        expected_events=expected['subset_exposure'],encoding=encoding)
    mapping=original_map(expected,produced)
    result=verify_transport(mapping,*read_downstream_ids(files['delphes'],files['ntuple'],files['trace']))
    require(before=={k:provenance.pin(p) for k,p in files.items()},'identity artifact changed during verification')
    result['source_files']=before
    result['original_content_witness']=produced
    result['native_producer_exit_and_build_custody']='Required separately from actual supervising-stage receipts; not inferred here.'
    return result


def supplied_tags(expected,identities):
    from ravel.validation.diagnostic_plan import PlanError
    if expected is None:raise PlanError('missing_input','events','supply the complete event count')
    if identities is None:raise PlanError('missing_input','identities','supply every replacement event identifier')
    require(type(expected) is int and expected>0 and type(identities) is list and len(identities)==expected and len(set(identities))==expected and all(type(v) is int and v>=0 for v in identities),'complete unique replacement identities required')
    return identities


def audit_relabel(original,tagged,expected=None,identities=None):
    """Prove exactly the declared E-number substitutions and no other bytes."""
    identities=supplied_tags(expected,identities)
    import itertools,re
    from ravel.physics import lhe_provenance as prov
    original,tagged=Path(original),Path(tagged)
    before=[prov.pin(p) for p in (original,tagged)]
    with original.open('rb') as stream:prov.scan_hepmc(stream,expected)
    mapping=[]
    with original.open('rb') as left,tagged.open('rb') as right:
        for a,b in itertools.zip_longest(left,right):
            require(a is not None and b is not None,'sentinel line population differs')
            match=re.match(rb'^(E[ \t]+)([0-9]+)([ \t].*)$',a)
            if match:
                i=len(mapping);tag=identities[i] if i<expected else None
                require(i<expected and int(match[2])==i,'original E-number population differs')
                replacement=match[1]+str(tag).encode()+match[3]+b'\n'
                require(b==replacement,'sentinel changed an E-record field other than ID')
                mapping.append({'source_event_id':i,'sentinel_event_id':tag})
            else:require(a==b,'sentinel changed a non-ID byte')
    require(len(mapping)==expected and len({r['sentinel_event_id'] for r in mapping})==expected,'sentinel mapping incomplete or ambiguous')
    require(before==[prov.pin(p) for p in (original,tagged)],'sentinel artifact changed during audit')
    return {'status':'sentinel_rewrite_verified','events':expected,'mapping':mapping,'non_ID_bytes_identical':True,'source_files':before,'scope':'Deterministic E-number substitution only; no particle, weight, vertex, unit or event-order change.'}


def relabel(original,tagged,expected=None,identities=None):
    identities=supplied_tags(expected,identities)
    import re
    from ravel.physics import lhe_provenance as prov
    original,tagged=Path(original),Path(tagged)
    require(not tagged.exists() and not tagged.is_symlink(),'sentinel destination already exists')
    with original.open('rb') as stream:prov.scan_hepmc(stream,expected)
    tagged.parent.mkdir(parents=True,exist_ok=True)
    i=0
    with original.open('rb') as source,tagged.open('xb') as target:
        for line in source:
            match=re.match(rb'^(E[ \t]+)([0-9]+)([ \t].*)$',line)
            if match:
                require(int(match[2])==i and i<expected,'source E identity changed during rewrite')
                line=match[1]+str(identities[i]).encode()+match[3]+b'\n';i+=1
            target.write(line)
    return audit_relabel(original,tagged,expected,identities)


def verify_tagged_files(original,tagged,delphes,ntuple,trace,expected=None,identities=None):
    from ravel.physics import lhe_provenance as prov
    paths=[Path(p) for p in (original,tagged,delphes,ntuple,trace)]
    before=[prov.pin(p) for p in paths]
    audit=audit_relabel(original,tagged,expected,identities);wanted=[r['sentinel_event_id'] for r in audit['mapping']]
    rows=[]
    for data,label in zip(read_downstream_ids(delphes,ntuple,trace),('Delphes Event.Number','ntuple Event','trace event_id')):
        require(len(data)==expected,'sentinel downstream population differs')
        values=[]
        for value in data:
            if isinstance(value,list):
                require(len(value)==1,'one sentinel event record per entry required');value=value[0]
            require(type(value) in (int,float) and math.isfinite(value) and int(value)==value,'exact sentinel integer identity required');values.append(int(value))
        require(values==wanted,'installed downstream stage lost/reordered/reassigned sentinel identity: '+label)
        rows.append({'stage':label,'ids':values})
    require(before==[prov.pin(p) for p in paths],'sentinel input bytes changed')
    return {'status':'tagged_transport_verified','events':expected,'source_files':before,'rewrite_audit':audit,'downstream':rows,'physics_validated':False,'scope':'Actual supplied non-ordinal ID preservation only; original hard-event correspondence comes separately from the actual LHA sidecar/content proof.'}


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=('original','relabel','tagged'))
    p.add_argument('--encoding',choices=('plain','gzip'),default='plain');p.add_argument('--report',required=True);p.add_argument('--expected-manifest');p.add_argument('--lhe');p.add_argument('--sidecar');p.add_argument('--hepmc');p.add_argument('--tagged');p.add_argument('--delphes');p.add_argument('--ntuple');p.add_argument('--trace')
    p.add_argument('--events',type=int);p.add_argument('--identities',help='JSON file containing all supplied replacement event IDs')
    a=p.parse_args()
    tags=json.loads(Path(a.identities).read_text()) if a.identities else None
    if a.action=='original':result=verify_files(expected_manifest=a.expected_manifest,lhe=a.lhe,sidecar=a.sidecar,hepmc=a.hepmc,encoding=a.encoding,delphes=a.delphes,ntuple=a.ntuple,trace=a.trace)
    elif a.action=='relabel':result=relabel(a.hepmc,a.tagged,a.events,tags)
    else:result=verify_tagged_files(a.hepmc,a.tagged,a.delphes,a.ntuple,a.trace,a.events,tags)
    with Path(a.report).open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False)


if __name__=='__main__':main()
