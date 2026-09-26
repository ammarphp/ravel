#!/usr/bin/env python3
"""Validate frozen control identities, populations and numerical postconditions."""
import hashlib
import json
import math
from pathlib import Path

EXPECTED={
 'signed-density':'passed','correlated-measurement':'passed','normalized-measurement':'passed',
 'bounded-measurement':'failed','eft-interference':'passed','eft-failed-control':'failed',
 'model-structure':'passed','classifier':'passed','llp-decay':'passed','llp-reweight':'passed',
 'nuclear-normalization':'passed','forward-acceptance':'passed','neutrino-fold':'passed',
 'reconstructed-selection':'passed','efficiency-map':'passed',
 'ATLAS_2013_I1234228':'passed','CMS_2018_I1711625':'passed','ATLAS_2016_I1494075':'passed',
 'CMS_2012_I1298807':'normalization_failure','ATLAS_2010_I871366':'passed','CMS_2016_I1459051':'passed'}

def verify(base):
    base=Path(base);errors=[]
    try:
        m=json.loads((base/'manifest.json').read_text())
        for name,h in m['files'].items():
            p=base/name
            if Path(name).is_absolute() or '..' in Path(name).parts or p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:
                errors.append('changed or missing artifact: '+name)
        frozen=json.loads((base/'controls.json').read_text());rows=frozen['controls']
        if len(rows)!=len(EXPECTED) or {r['name'] for r in rows}!=set(EXPECTED):errors.append('control denominator differs')
        for r in rows:
            if r['actual']!=EXPECTED.get(r['name']) or r['actual']!=r['expected']:errors.append('unexpected control result: '+r['name'])
            if r['physics_validated'] is not False or r['expert_review'] is not False or r['approval_mode']!='scripted_yes':errors.append('unsupported scientific review claim')
            d=base/'controls'/r['name']
            if r['actual']!='normalization_failure':
                result=json.loads((d/'result.json').read_text())
                if result['status']!=r['actual'] or result['physics_validated'] is not False:errors.append('result classification differs')
                v=json.loads((d/'verification.json').read_text())
                if v['passed']!=(r['actual']=='passed') or v['result_sha256']!=hashlib.sha256((d/'result.json').read_bytes()).hexdigest():errors.append('result receipt differs')
            else:
                if 'normalized observable does not have unit integrated area' not in (d/'export.log').read_text():errors.append('expected upstream normalization failure absent')
            if 'normalization_oracle' in r:
                q=json.loads((d/'observables.json').read_text());b=next(iter(q['observables'].values()))['bins']
                actual=math.fsum(x['integrated_sumw'] for x in b);o=r['normalization_oracle']
                if not math.isclose(actual,o['expected'],rel_tol=o['relative_tolerance']) or actual!=o['actual']:errors.append('normalization oracle failed')
        grouped=json.loads((base/'controls/ATLAS_2013_I1234228/observables.json').read_text())['event_counters']
        if grouped['/RAW/_EVTCOUNT']!={'entries':1.,'sumw':1.,'sumw2':1.} or grouped['/RAW/_EVTCOUNT[scale]']!={'entries':1.,'sumw':2.,'sumw2':4.}:errors.append('grouped-weight counter mismatch')
    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:errors.append(str(exc))
    return {'status':'FAIL' if errors else 'PASS','errors':errors,'controls':len(EXPECTED),'physics_validated':False,
            'scope':'Frozen synthetic adapter evidence only; no new scientific execution'}
if __name__=='__main__':
    result=verify(Path(__file__).resolve().parent);print(json.dumps(result,indent=2));raise SystemExit(result['status']!='PASS')
