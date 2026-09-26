#!/usr/bin/env python3
"""Verify the frozen survey's bytes, identities and denominators, never physics."""
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import re


def verify(base):
    errors=[]
    try:
        manifest=json.loads((base/'manifest.json').read_text())
        for name,expected in manifest['files'].items():
            path=base/name
            if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink():
                errors.append('invalid manifest path: '+name);continue
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                errors.append('changed or missing artifact: '+name)
        c=json.loads(gzip.decompress((base/'catalog.json.gz').read_bytes()))
        rows=c['entries']; ids=[r['id'] for r in rows]
        if len(ids)!=633 or len(set(ids))!=633: errors.append('census denominator or identity mismatch')
        if sum(r['framework']=='rivet' for r in rows)!=554: errors.append('Rivet denominator mismatch')
        if sum(r['framework']=='simpleanalysis' for r in rows)!=79: errors.append('SimpleAnalysis denominator mismatch')
        if any(r['physics_validated_by_ravel'] is not False for r in rows): errors.append('unsupported scientific validation')
        actual=list(csv.DictReader(io.StringIO((base/'routines.csv').read_text())))
        if len(actual)!=633 or {r['id'] for r in actual}!=set(ids): errors.append('CSV population mismatch')
        html=(base/'index.html').read_text()
        data=json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>',html,re.S)[1])
        if len(data)!=633 or {r['id'] for r in data}!=set(ids): errors.append('browser population mismatch')
        if any(r['packet']['compute_authorized'] is not False or r['packet']['physics_validated'] is not False for r in data):
            errors.append('browser falsely grants admission')
        targets=json.loads((base/'validation-targets.json').read_text())['entries']
        if len(targets)!=40 or len({r['routine_id'] for r in targets})!=40: errors.append('target population mismatch')
        lookup={r['id']:r for r in rows}
        for target in targets:
            source=lookup[target['routine_id']]
            if any(target[k] is not False for k in ('likelihood_bytes_verified','experiment_executed','compute_authorized')):
                errors.append('proposed experiment promoted to execution')
            if target['source_revision']!=c['sources'][source['source_id']]['revision']:
                errors.append('target source revision mismatch')
            if [{k:v for k,v in f.items() if k!='url'} for f in target['source_files']]!=source['source_files']:
                errors.append('target source-file identity mismatch')
        models=(base/'probability-models.json').read_bytes()
        if hashlib.sha256(models).hexdigest()!=c['sources']['probability-models']['sha256']:
            errors.append('probability index identity mismatch')
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:
        errors.append(str(exc))
    return {'status':'FAIL' if errors else 'PASS','errors':errors,'catalogue_entries':633,
            'proposed_targets':40,'new_physics_validations':0,
            'scope':'Frozen survey integrity and population consistency; not routine compilation, likelihood validation or scientific closure.'}


if __name__=='__main__':
    result=verify(Path(__file__).resolve().parent)
    print(json.dumps(result,indent=2));raise SystemExit(result['status']!='PASS')
