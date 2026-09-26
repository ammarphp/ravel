#!/usr/bin/env python3
"""Curate small adapter controls; never claim paper or detector closure."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'evidence/audits/2026-09-26-scientific-studies'
def read(p):return json.loads(p.read_text())
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def copy_public(source,target):
    raw=source.read_bytes()
    if source.suffix not in ('.png','.pdf'):
        raw=raw.replace(str(ROOT.parent).encode(),b'$DSRLAB_ROOT').replace(str(Path.home()).encode(),b'$OPERATOR_HOME')
    target.write_bytes(raw)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--analytic',type=Path,required=True);ap.add_argument('--rivet',type=Path,required=True)
    a=ap.parse_args();records=[]
    for family,base in [('analytic',a.analytic),('rivet',a.rivet)]:
        rows=read(base/'results.json')['results']
        for row in rows:
            if not row['expected_observed']:raise ValueError('unexpected control result: '+row['name'])
            rd=base/'runs'/row['name'];dest=OUT/'controls'/row['name']
            if dest.exists():raise ValueError('preserve previous curation; destination already exists')
            dest.mkdir(parents=True)
            picked=[]
            for f in sorted((rd/'outputs').rglob('*')):
                if f.is_file() and f.name!='recipe.json':
                    if f.suffix not in ('.json','.png','.pdf','.yoda','.log','.md'):continue
                    target=dest/f.relative_to(rd/'outputs');target.parent.mkdir(parents=True,exist_ok=True)
                    if target.name=='RESULT.md':target=target.with_name('result.md')
                    copy_public(f,target);picked.append(str(target.relative_to(OUT)))
            if (rd/'logs/science-worker.log').is_file():copy_public(rd/'logs/science-worker.log',dest/'worker.log')
            if (dest/'verification.json').is_file():
                v=read(dest/'verification.json')
                v['original_result_sha256']=v['result_sha256']
                v['result_sha256']=sha(dest/'result.json')
                v['public_transformation']='Only operator-home and DSRLab-root path redaction; original result hash retained.'
                write(dest/'verification.json',v)
            spec=read(rd/'inputs/science.json')
            plan=read(rd/'inputs/science-plan.json')
            record={'name':row['name'],'family':family,'expected':row['expected'],'actual':row['actual'],
                    'exit':row['exit'],'physics_validated':False,'mode':spec['mode'],'assumptions':spec['assumptions'],
                    'expert_review':False,'approval_mode':spec['approval_mode'],'max_seconds':spec['max_seconds'],
                    'stage_fingerprint':plan['stage_binding']['fingerprint'],
                    'original_plan_sha256':sha(rd/'inputs/science-plan.json'),
                    'original_approval_sha256':sha(rd/'inputs/science-approval.json'),
                    'original_attempt_sha256':sha(rd/'execution_attempt.json'),
                    'original_output_files':picked}
            if family=='rivet' and row['actual']=='passed':
                obs=next(iter(read(dest/'observables.json')['observables'].values()))
                actual=math.fsum(b['integrated_sumw'] for b in obs['bins'])
                expected={'ATLAS_2013_I1234228':1.,'CMS_2018_I1711625':1.,
                          'ATLAS_2016_I1494075':1000/((3.3632+3.3662)/100)**2,
                          'ATLAS_2010_I871366':2/(2*.3),'CMS_2016_I1459051':2/(2*.5)}[row['name']]
                if not math.isclose(actual,expected,rel_tol=2e-6):raise ValueError('independent normalization failed: '+row['name'])
                record['normalization_oracle']={'actual':actual,'expected':expected,'relative_tolerance':2e-6,
                     'basis':'Synthetic 1 pb exposure; explicit branching-ratio and rapidity-width factors in pinned routine. Not a measured cross section.'}
            records.append(record)
    write(OUT/'controls.json',{'schema_version':1,'controls':records,'physics_validated':False,
          'scope':'Frozen synthetic adapter controls, not a fresh replay or paper reproduction'})
    files={str(p.relative_to(OUT)):sha(p) for p in sorted((OUT/'controls').rglob('*')) if p.is_file()}
    files['controls.json']=sha(OUT/'controls.json')
    source={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'src/ravel').rglob('*.py'))}
    write(OUT/'manifest.json',{'schema_version':1,'files':files,'implementation_sha256':source,
          'sources':{'rivet':'74816bd4cf29a9d71447f8c122887d498d3dea3a','rivet_runtime':'4.1.3','yoda_runtime':'2.1.3',
                     'simpleanalysis':'5a33033d788619bb1039a5b8116fdf43c46fc72a','simpleanalysis_framework':'d9f8c7044dacd40b0a8f42795181f99e2c6d6e7b'},
          'note':'Source identities record the implementation at execution; later source changes do not rewrite frozen evidence.'})
    print('Curated',len(records),'controls and',len(files),'artifacts')
if __name__=='__main__':main()
