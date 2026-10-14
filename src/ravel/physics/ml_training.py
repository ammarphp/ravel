"""Governed CPU binary classification with a permanently spent test exposure.

Planning hashes opaque split bytes. Only evaluation decodes the test payload,
after every arm and seed checkpoint has been fixed. This is run-local custody,
not a sandbox against a user who can copy data or delete exposure records.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import numpy as np
from ravel.workflow import execution_backend as eb
from ravel.workflow.state_io import atomic_json
from . import ml_backends, ml_exposure, ml_custody

MAX_BYTES = 64 * 1024**2


def digest(value):
    return hashlib.sha256(eb.canonical(value)).hexdigest()


def pin(path):
    path = Path(path)
    return {'path': str(path), 'sha256': eb.file_sha256(path)}


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('expected fields: ' + ', '.join(expected))


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('sha256 required')


def _pin(p):
    _keys(p, ('path', 'sha256')); _sha(p['sha256'])
    if not isinstance(p['path'], str) or not p['path']: raise ValueError('pin path required')


def _path(p, base):
    path = Path(p['path']); path = path if path.is_absolute() else Path(base)/path
    if any(q.is_symlink() for q in (path, *path.parents)) or not path.is_file():
        raise ValueError('pin must name a regular nonsymlink file')
    if path.stat().st_size > MAX_BYTES: raise ValueError('pinned input exceeds 64 MiB reference bound')
    return path


def _bytes(p, base):
    if p['path'].startswith('sealed://'): return ml_custody.read(p)
    path = _path(p, base)
    raw = path.read_bytes()
    if len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest()!=p['sha256']:
        raise ValueError('input pin sha256 changed')
    return raw


def _integer(x, low, high):
    if type(x) is not int or not low <= x <= high: raise ValueError('integer outside training bound')


def _number(x, low, high):
    if type(x) not in (int, float) or not math.isfinite(x) or not low <= x <= high:
        raise ValueError('finite number outside training bound')


def split_digest(splits):
    return digest({k: v for k, v in splits.items() if k not in ('split_sha256', 'test_withheld')})


@dataclass(frozen=True)
class TrainingSpec:
    """Validated JSON task, with a stable identity for the complete declaration."""
    task: dict[str, Any]
    sha256: str

    @classmethod
    def parse(cls, task):
        validate(task)
        return cls(json.loads(json.dumps(task)), digest(task))


def validate(task):
    if task.get('splits',{}).get('method')=='kfold_crossfit':
        from . import ml_crossfit
        return ml_crossfit.validate(task)
    if task.get('claim_kind')=='method_performance': raise ValueError('method_performance requires the research-protocol claim contract')
    _keys(task, ('objective', 'dataset', 'splits', 'baselines', 'models', 'seeds', 'budget', 'metrics', 'placement')+(('claim_kind',) if 'claim_kind' in task else ()))
    if task.get('claim_kind','diagnostic')!='diagnostic': raise ValueError('claim kind not admitted before the research-protocol claim contract exists')
    if task['objective'] != 'classification': raise ValueError('binary classification required')
    data = task['dataset']
    _keys(data, ('pins', 'manifest_sha256', 'features', 'label', 'weights', 'id_column') + (('population_index',) if 'population_index' in data else ()))
    if not isinstance(data['pins'], list) or len(data['pins'])!=3: raise ValueError('three disjoint split pins required')
    for p in data['pins']: _pin(p)
    if data['manifest_sha256'] != digest({k:v for k,v in data.items() if k!='manifest_sha256'}):
        raise ValueError('dataset manifest sha256 changed')
    if not isinstance(data['features'], list) or not 1 <= len(data['features']) <= 256:
        raise ValueError('bounded declared feature columns required')
    if any(not isinstance(v,str) or not v for v in data['features']) or len(set(data['features']))!=len(data['features']):
        raise ValueError('unique feature names required')
    if (data['label'], data['weights'], data['id_column']) != ('y', 'weight', 'event_id'):
        raise ValueError('reference NPZ schema requires y, weight, event_id')
    s = task['splits']
    _keys(s, ('method', 'seed', 'fractions', 'files', 'split_sha256', 'test_withheld'))
    if 'population_index' not in data:
        raise ValueError('complete population_index required: withheld test identities come from it, never from the test file')
    _pin(data['population_index'])
    if s['method'] not in ('hash', 'explicit') or s['test_withheld'] is not True:
        raise ValueError('withheld test split required')
    _integer(s['seed'], 0, 2**32-1)
    _keys(s['fractions'], ('train','val','test')); _keys(s['files'], ('train','val','test'))
    for value in s['fractions'].values(): _number(value, .001, .998)
    if not math.isclose(sum(s['fractions'].values()), 1, abs_tol=1.e-12): raise ValueError('split fractions must sum to one')
    for p in s['files'].values(): _pin(p)
    if len({p['path'] for p in s['files'].values()})!=3 or len({p['sha256'] for p in s['files'].values()})!=3:
        raise ValueError('split files must be distinct')
    if sorted(map(digest, s['files'].values())) != sorted(map(digest, data['pins'])):
        raise ValueError('dataset pins must match split files')
    if s['split_sha256']!=split_digest(s): raise ValueError('split sha256 changed')
    seeds = task['seeds']
    if not isinstance(seeds, list) or not 3 <= len(seeds) <= 32: raise ValueError('at least three bounded seeds required')
    for seed in seeds: _integer(seed, 0, 2**32-1)
    if len(set(seeds))!=len(seeds): raise ValueError('distinct seeds required')
    b = task['budget']; _keys(b, ('wall_seconds','epochs','max_trials','equal_across_arms'))
    _integer(b['wall_seconds'], 1, 86400); _integer(b['epochs'], 1, 100000)
    if type(b['max_trials']) is not int or b['max_trials']!=1 or b['equal_across_arms'] is not True:
        raise ValueError('equal budgets and exactly one trial; hyperparameter search is not admitted')
    if any(not isinstance(task[k],list) or not 1<=len(task[k])<=8 for k in ('models','baselines')):
        raise ValueError('at least one bounded model and baseline required')
    ids = set()
    for arm in task['baselines']+task['models']:
        cut = arm.get('kind') == 'cut_based'
        _keys(arm, ('id','kind','spec') if cut else ('id','architecture','backend','config') + (('code',) if 'code' in arm else ()))
        if not isinstance(arm['id'],str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]{0,39}',arm['id']) or arm['id'] in ids:
            raise ValueError('unique safe arm id required')
        ids.add(arm['id'])
        if cut:
            if arm not in task['baselines']: raise ValueError('cut_based is an untrained baseline')
            _keys(arm['spec'], ('feature', 'threshold', 'direction'))
            if arm['spec']['feature'] not in data['features'] or arm['spec']['direction'] not in ('above', 'below'):
                raise ValueError('cut requires a declared feature and direction')
            _number(arm['spec']['threshold'], -1.e100, 1.e100)
            continue
        if arm['backend'] not in ml_backends.FAMILIES or arm['architecture'] not in ml_backends.FAMILIES[arm['backend']]:
            raise ValueError('model family/backend outside allowlist')
        if 'code' in arm: _pin(arm['code'])
        if is_config_pin(arm):
            _pin(arm['config'])
            continue
        expected = (('learning_rate','hidden_units','nodes','edge_index') if arm['architecture']=='gnn' else
                    ('learning_rate','hidden_units') if arm['architecture']=='mlp' else ('learning_rate',))
        _keys(arm['config'], expected); _number(arm['config']['learning_rate'], 1.e-8, 1)
        if 'hidden_units' in arm['config']: _integer(arm['config']['hidden_units'], 1, 128)
        if arm['architecture']=='gnn':
            _integer(arm['config']['nodes'], 2, 128)
            edges=arm['config']['edge_index']
            if (not isinstance(edges,list) or len(edges)!=2 or
                any(not isinstance(row,list) for row in edges) or
                not 1<=len(edges[0])<=4096 or len(edges[0])!=len(edges[1])):
                raise ValueError('explicit bounded directed edge_index required')
            for row in edges:
                for node in row: _integer(node,0,arm['config']['nodes']-1)
            if len(set(zip(*edges)))!=len(edges[0]): raise ValueError('duplicate graph edges')
    m = task['metrics']; _keys(m, ('primary','operating_point','secondary','calibration','uncertainty'))
    if m['primary']!='background_rejection_at_signal_eff' or m['secondary']!=['roc_auc'] or m['uncertainty']!='seed_spread':
        raise ValueError('declared rejection, AUC and seed spread required')
    _number(m['operating_point'], .001, .999)
    _keys(m['calibration'], ('method','bins','report')); _integer(m['calibration']['bins'], 2, 100)
    if m['calibration']['method']!='reliability' or m['calibration']['report']!=['ece','brier']:
        raise ValueError('reliability ECE and Brier required')
    _keys(task['placement'], ('backend_plan','device')); _pin(task['placement']['backend_plan'])
    if task['placement']['device']!='cpu': raise ValueError('current qualified implementation requires CPU')
    return task


def execution_seconds(task, base_dir):
    if task.get('splits',{}).get('method')=='kfold_crossfit':
        from . import ml_crossfit
        return ml_crossfit.execution_seconds(task)
    validate(task)
    return task['budget']['wall_seconds']*len(task['seeds'])*(len(task['models'])+len(task['baselines']))+30


def _plan(task, base):
    plan = eb.check_plan(json.loads(_bytes(task['placement']['backend_plan'], base)))
    if plan['spec']['backend']!='native' or not plan['backend']['local'] or plan['spec']['stage']!='ml-training':
        raise ValueError('reference executor requires native ml-training placement')
    if plan['spec']['resources']['wall_seconds'] < execution_seconds(task, base):
        raise ValueError('backend plan wall ceiling does not contain complete training and evaluation budget')
    actual = {(str(_path(p,base).resolve()),p['sha256']) for p in task['dataset']['pins']+([task['dataset']['population_index']] if 'population_index' in task['dataset'] else [])}
    declared = {(str(_path(p,base).resolve()),p['sha256']) for p in plan['inputs']}
    if not actual<=declared: raise ValueError('backend plan must bind every dataset pin')
    return plan


def inputs(task, base_dir):
    if task.get('splits',{}).get('method')=='kfold_crossfit':
        from . import ml_crossfit
        return ml_crossfit.inputs(task,base_dir)
    validate(task); _plan(task,base_dir)
    resolved = resolved_task(task,base_dir)
    validate(resolved)
    paths = []
    for p in task['dataset']['pins']+[task['placement']['backend_plan']]+([task['dataset']['population_index']] if 'population_index' in task['dataset'] else []):
        _bytes(p,base_dir); paths.append(_path(p,base_dir))
    if any(not ml_backends.available().get(a.get('backend'), a.get('kind')=='cut_based') for a in task['models']+task['baselines']):
        raise ValueError('selected training backend is not installed')
    for arm in task['models']+task['baselines']:
        if is_config_pin(arm): paths.append(_path(arm['config'],base_dir))
        if 'code' in arm: paths.append(_path(arm['code'],base_dir))
    return paths+[Path(__file__),Path(ml_backends.__file__)]


def hash_partition(event_id, seed, fractions):
    value = int(hashlib.sha256(f'{seed}:{event_id}'.encode()).hexdigest(),16)/2**256
    return 'train' if value<fractions['train'] else 'val' if value<fractions['train']+fractions['val'] else 'test'


def _census_identities(task, base):
    """Per-split identifiers from the pinned population index; no split file is decoded."""
    census=json.loads(_bytes(task['dataset']['population_index'],base))
    if not isinstance(census,list) or not census or any(not isinstance(r,dict) or 'event_id' not in r or 'group_id' not in r for r in census):
        raise ValueError('population index requires event_id and group_id records')
    method=task['splits']['method']; rows={'train':[],'val':[],'test':[]}
    for r in census:
        name=(hash_partition(str(r['group_id']),task['splits']['seed'],task['splits']['fractions'])
              if method=='hash' else r.get('partition'))
        if name not in rows: raise ValueError('explicit population index rows require partition train, val or test')
        rows[name].append(r)
    return {name:{'event_ids':[str(r['event_id']) for r in found],'group_ids':[str(r['group_id']) for r in found]}
            for name,found in rows.items()}


def load_split(task, base, name):
    raw = _bytes(task['splits']['files'][name],base)
    import zipfile
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_BYTES: raise ValueError('expanded split exceeds byte bound')
    with np.load(io.BytesIO(raw),allow_pickle=False) as d:
        if set(d.files)!={'x','y','weight','event_id','group_id'}: raise ValueError('NPZ requires x,y,weight,event_id,group_id')
        groups=d['group_id'].astype(str)
        x,y,w,ids = d['x'],d['y'],d['weight'],d['event_id']
    graph_arms=[resolve_arm(a,base) for a in task['models']+task['baselines'] if a.get('architecture')=='gnn']
    if x.ndim!=(3 if graph_arms else 2) or x.shape[-1]!=len(task['dataset']['features']) or not 2<=len(x)<=100000:
        raise ValueError('bounded feature matrix required')
    for arm in graph_arms:
        config=arm['config']
        if x.shape[1]!=config['nodes']: raise ValueError('graph node count differs from declaration')
        if len(x)*config['nodes']*config['hidden_units']>4_000_000 or len(x)*len(config['edge_index'][0])>2_000_000:
            raise ValueError('graph expansion exceeds reference memory bound')
    if y.shape!=(len(x),) or w.shape!=y.shape or ids.shape!=y.shape: raise ValueError('split column lengths differ')
    if any(a.dtype.kind not in 'fiu' or not np.all(np.isfinite(a)) for a in (x,y,w)):
        raise ValueError('finite numeric features, labels and weights required')
    if not math.isfinite(float(w.sum())) or not set(y.tolist())<={0,1} or np.any(w<0) or any(w[y==c].sum()<=0 for c in (0,1)):
        raise ValueError('binary classes with positive weight totals required; signed weights are unsupported')
    if ids.dtype.kind not in 'iuUS': raise ValueError('integer or string event identities required')
    ids=ids.astype(str)
    if len(set(ids))!=len(ids): raise ValueError('duplicate event ids')
    if task['splits']['method']=='hash' and any(hash_partition(i,task['splits']['seed'],task['splits']['fractions'])!=name for i in groups):
        raise ValueError('group does not belong to declared hash split')
    return x.astype(float),y.astype(float),w.astype(float),ids


def metrics(y, score, weight, operating_point, bins):
    """Weighted, tie-grouped ROC; no invented finite rejection for zero FPR."""
    order=np.argsort(-score,kind='stable'); yy=y[order]; ss=score[order]; ww=weight[order]
    ends=np.r_[np.flatnonzero(np.diff(ss)!=0),len(ss)-1]
    tpr=np.r_[0,np.cumsum(ww*(yy==1))[ends]/ww[yy==1].sum()]
    fpr=np.r_[0,np.cumsum(ww*(yy==0))[ends]/ww[yy==0].sum()]
    auc=float(np.trapz(tpr,fpr)); idx=int(np.searchsorted(tpr,operating_point,side='left'))
    background=float(fpr[idx]); rejection=None if background==0 else 1/background
    reliability=[]; ece=0.
    bin_id=np.minimum((score*bins).astype(int),bins-1)
    for k in range(bins):
        mask=bin_id==k; mass=float(weight[mask].sum())
        conf=float(np.average(score[mask],weights=weight[mask])) if mass else None
        freq=float(np.average(y[mask],weights=weight[mask])) if mass else None
        if mass: ece+=mass/weight.sum()*abs(conf-freq)
        reliability.append({'lo':k/bins,'hi':(k+1)/bins,'weight':mass,'probability':conf,'frequency':freq})
    return ({'roc_auc':auc,'background_rejection_at_signal_eff':rejection,
             'background_efficiency':background,'achieved_signal_efficiency':float(tpr[idx]),
             'rejection_status':'zero_background_observed' if background==0 else 'finite',
             'ece':float(ece),'brier':float(np.average((score-y)**2,weights=weight))},
            reliability,{'false_positive_rate':fpr.tolist(),'true_positive_rate':tpr.tolist()})


def _write_new(path, document):
    with Path(path).open('x') as stream:
        json.dump(document,stream,sort_keys=True,allow_nan=False); stream.flush(); os.fsync(stream.fileno())


def _summary(arms):
    result={}
    for identity in dict.fromkeys(a['id'] for a in arms):
        result[identity]={}
        for metric in ('roc_auc','background_rejection_at_signal_eff','ece','brier'):
            values=[a['metrics'][metric] for a in arms if a['id']==identity]
            finite=[v for v in values if v is not None]
            result[identity][metric]={'mean':float(np.mean(finite)) if len(finite)==len(values) else None,
                'spread':float(np.std(finite,ddof=1)) if len(finite)==len(values) else None,
                'seeds':len(values),'undefined_seeds':len(values)-len(finite)}
    return result


def validate_receipt(receipt, task, output, *, pending=False, test_arrays=None):
    # pending: the executor's own pre-write check over the arrays of its one charged read.
    # Every later validation requires the ledger pin and records one replay before it decodes test data.
    if task.get('splits',{}).get('method')=='kfold_crossfit':
        from . import ml_crossfit
        return ml_crossfit.validate_receipt(receipt,task,output,pending=pending)
    validate(task)
    if receipt.get('kind')!='ml-training-receipt' or receipt.get('schema_version')!=1 or type(receipt.get('test_reads')) is not int or receipt['test_reads']!=1:
        raise ValueError('receipt requires exactly one test read')
    if receipt.get('claim_kind')!=task.get('claim_kind','diagnostic'): raise ValueError('receipt claim kind changed')
    if receipt.get('task')!=task: raise ValueError('receipt must retain complete task declaration')
    environment=json.loads((Path(output)/'environment.json').read_text())
    if receipt.get('environment_sha256')!=digest(environment): raise ValueError('receipt environment changed')
    if receipt.get('splits')!=task['splits']: raise ValueError('receipt split pins changed')
    if receipt.get('spec_sha256')!=digest(task) or receipt.get('split_sha256')!=task['splits']['split_sha256']:
        raise ValueError('receipt specification or split changed')
    expected={(a['id'],s,k) for k,group in (('baseline','baselines'),('model','models')) for a in task[group] for s in task['seeds']}
    rows=receipt['arms']
    if len(rows)!=len(expected) or {(a['id'],a['seed'],a['kind']) for a in rows}!=expected:
        raise ValueError('receipt must cover every arm and seed exactly once')
    if pending and test_arrays is None: raise ValueError('pending validation reuses the arrays of the charged read')
    if not pending:
        ml_exposure.verify_receipt(receipt,Path(output)/'receipt.json')
        ml_exposure.record_replay(receipt['exposure_ledger'],receipt['spec_sha256'],'test',pin(Path(output)/'frozen.json'))
        with np.load(io.BytesIO(_bytes(task['splits']['files']['test'],receipt['input_base'])),allow_pickle=False) as test:
            test_arrays={k:test[k] for k in test.files}
    for a in rows:
        try:
            with np.load(io.BytesIO(_bytes(a['checkpoint'],output)),allow_pickle=False) as checkpoint:
                model={k:checkpoint[k] for k in checkpoint.files}
            score=ml_backends.predict(model,test_arrays['x'])
            if score.shape!=test_arrays['y'].shape or not np.isfinite(score).all() or np.any((score<0)|(score>1)):
                raise ValueError('invalid checkpoint predictions')
            expected_metrics,reliability,roc=metrics(test_arrays['y'],score,test_arrays['weight'],task['metrics']['operating_point'],task['metrics']['calibration']['bins'])
            if a['metrics']!=expected_metrics or a['roc']!=roc or json.loads(_bytes(a['calibration']['reliability'],output))!=reliability:
                raise ValueError('receipt recomputation differs from checkpoint metrics/ROC/reliability')
        except (KeyError,TypeError,IndexError) as exc:
            raise ValueError('receipt checkpoint structure invalid') from exc
        if a['epochs']!=(0 if a.get('training_kind')=='cut_based' else task['budget']['epochs']) or a['budget']!=task['budget'] or a['wall_seconds']>task['budget']['wall_seconds']:
            raise ValueError('receipt training budget mismatch')
        _number(a['wall_seconds'], 0, task['budget']['wall_seconds'])
        for key in ('roc_auc','ece','brier','background_efficiency','achieved_signal_efficiency'):
            _number(a['metrics'][key],0,1)
        m=a['metrics']; rejection=m['background_rejection_at_signal_eff']
        if m['background_efficiency']==0:
            if rejection is not None or m['rejection_status']!='zero_background_observed': raise ValueError('invalid zero-background rejection')
        elif rejection!=1/m['background_efficiency'] or m['rejection_status']!='finite':
            raise ValueError('rejection and background efficiency differ')
        if a['calibration']['ece']!=m['ece'] or a['calibration']['brier']!=m['brier']:
            raise ValueError('calibration metrics differ')
        for p in (a['checkpoint'], a['calibration']['reliability']): _bytes(p,output)
    if receipt['summary']!=_summary(rows): raise ValueError('receipt seed summary changed')
    by_metric={metric:{arm:values[metric] for arm,values in _summary(rows).items()} for metric in ('roc_auc','background_rejection_at_signal_eff','ece','brier')}
    if receipt.get('summary_by_metric')!=by_metric: raise ValueError('receipt metric summary changed')
    if receipt['backend_plan']!=task['placement']['backend_plan'] or receipt['dataset']!=task['dataset']:
        raise ValueError('receipt input pins changed')
    return receipt


def run(task, base_dir, output_dir):
    if task.get('splits',{}).get('method')=='kfold_crossfit':
        from . import ml_crossfit
        return ml_crossfit.run(task,base_dir,output_dir)
    spec=TrainingSpec.parse(task); task=spec.task; base=Path(base_dir)
    inputs(task,base); plan=_plan(task,base)
    output=Path(output_dir).absolute()/'ml'
    if any(p.is_symlink() for p in (output,*output.parents,base/'ml-exposure')):
        raise ValueError('output and exposure paths must not traverse symlinks')
    # The ordinary science supervisor provides approval and the hard process wall.
    # This context supplies the native lease even before placement integration lands.
    # Adaptive splits are decoded for their identities; the withheld test identity comes from the
    # pinned population index, and its file is decoded only after the freeze and the charged read.
    census=_census_identities(task,base)
    identities={name:ml_exposure.identity(task['splits']['files'][name],base) for name in ('train','val')}
    identities['test']=ml_exposure.manifest_identity(census['test'],task['splits']['files']['test']['sha256'])
    names=list(identities)
    if any(ml_exposure.overlaps(identities[a],identities[b]) for i,a in enumerate(names) for b in names[:i]):
        raise ValueError('supervised event/group/value overlap between splits')
    for name in ('train','val'):
        if sorted(census[name]['event_ids'])!=identities[name]['event_ids']:
            raise ValueError('incomplete hash partition events' if task['splits']['method']=='hash'
                             else 'split file events differ from the population index')
    with eb.capacity(plan,f'{base}:ml-training',nested=True):
        state=base/'ml-exposure'; state.mkdir(exist_ok=True)
        exposure=state/(identities['test']['sha256']+'.json')
        try: _write_new(exposure,{'spec_sha256':spec.sha256,'state':'reserved','test_reads':0})
        except FileExistsError as exc:
            if exposure.is_symlink(): raise ValueError('symlink exposure record') from exc
            prior=json.loads(exposure.read_text())
            if (prior.get('state') not in ('failed','reserved') or type(prior.get('test_reads')) is not int
                    or prior['test_reads']!=0 or prior.get('spec_sha256')!=spec.sha256):
                raise ValueError('test split attempt already spent or unresolved') from exc
            atomic_json(exposure, {'spec_sha256':spec.sha256,'state':'reserved',
                                  'test_reads':0,'prior_failure':prior})
        # The machine-wide ledger binds this content to one study across directories and rounds.
        study=ml_exposure.Study(spec.sha256)
        study.claim_all([(identities[n],r) for n,r in [('train','train_split'),('val','validation_split'),('test','test_split')]],
                        schedule={identities[n]['sha256']:[n] for n in names})
        output.mkdir(parents=True,exist_ok=False); (output/'checkpoints').mkdir()
        rows=[]; frozen=[]; reads=0; start=time.monotonic()
        try:
            _write_new(output/'training-freeze.json',{'spec_sha256':spec.sha256,'selection':task['models']+task['baselines']})
            for name in ('train','val'): study.read(identities[name]['sha256'],name,pin(output/'training-freeze.json'))
            train=load_split(task,base,'train'); val=load_split(task,base,'val')
            if set(train[3]) & set(val[3]): raise ValueError('train/validation event overlap')
            for kind,group in (('baseline','baselines'),('model','models')):
                for arm in task[group]:
                    for seed in task['seeds']:
                        began=time.monotonic()
                        def deadline():
                            if time.monotonic()-began>task['budget']['wall_seconds'] or time.monotonic()-start>execution_seconds(task,base):
                                raise ValueError('training wall budget exhausted')
                        if arm.get('kind')=='cut_based':
                            model={'cut_feature':np.array(task['dataset']['features'].index(arm['spec']['feature'])),
                                   'cut_threshold':np.array(arm['spec']['threshold']),
                                   'cut_above':np.array(arm['spec']['direction']=='above')}
                        else:
                            model=ml_backends.fit(resolve_arm(arm,base),*train[:3],seed,task['budget']['epochs'],deadline)
                        deadline()
                        path=output/'checkpoints'/f'{arm["id"]}-{seed}.npz'; np.savez(path,**model)
                        vm,_,_=metrics(val[1],ml_backends.predict(model,val[0]),val[2],task['metrics']['operating_point'],task['metrics']['calibration']['bins'])
                        deadline()
                        frozen.append((arm,seed,kind,pin(path),vm,time.monotonic()-began))
            _write_new(output/'frozen.json',{'spec_sha256':spec.sha256,'checkpoints':[f[3] for f in frozen]})
            # Spend before opening: crashes never make a second evaluation admissible.
            study.read(task['splits']['files']['test']['sha256'],'test',pin(output/'frozen.json'))
            reads=1; atomic_json(exposure,{'spec_sha256':spec.sha256,'state':'test_opening','test_reads':reads})
            test=load_split(task,base,'test')
            if sorted(test[3].tolist())!=identities['test']['event_ids']:
                raise ValueError('test file identifiers differ from the population index')
            if (set(train[3])|set(val[3])) & set(test[3]): raise ValueError('withheld test event overlap')
            for arm,seed,kind,checkpoint,vm,wall in frozen:
                with np.load(io.BytesIO(_bytes(checkpoint,base)),allow_pickle=False) as d: model={k:d[k] for k in d.files}
                m,rel,roc=metrics(test[1],ml_backends.predict(model,test[0]),test[2],task['metrics']['operating_point'],task['metrics']['calibration']['bins'])
                relpath=output/f'{arm["id"]}-{seed}-reliability.json'; _write_new(relpath,rel)
                rows.append({'id':arm['id'],'kind':kind,'seed':seed,'checkpoint':checkpoint,
                    'metrics':m,'validation_metrics':vm,'roc':roc,
                    'calibration':{'ece':m['ece'],'brier':m['brier'],'reliability':pin(relpath)},
                    'wall_seconds':wall,'epochs':0 if arm.get('kind')=='cut_based' else task['budget']['epochs'],
                    'training_kind':arm.get('kind','trained'),'budget':task['budget']})
            environment={'python':sys.version,'numpy':np.__version__,'backends':ml_backends.available(),
                         'package_versions':{name:importlib.metadata.version(name) for name in
                             ['numpy','matplotlib','mplhep'] +
                             (['scikit-learn'] if any(a.get('backend')=='sklearn' for a in task['models']+task['baselines']) else []) +
                             (['torch'] if any(a.get('backend') in ('torch','torch-geometric') for a in task['models']+task['baselines']) else []) +
                             (['torch-geometric'] if any(a.get('backend')=='torch-geometric' for a in task['models']+task['baselines']) else [])},
                         'executor':pin(__file__),'backend_code':pin(ml_backends.__file__)}
            _write_new(output/'environment.json',environment)
            receipt={'schema_version':1,'kind':'ml-training-receipt','claim_kind':task.get('claim_kind','diagnostic'),'spec_sha256':spec.sha256,
                'split_sha256':task['splits']['split_sha256'],'dataset':task['dataset'],'splits':task['splits'],
                'task':task,'input_base':str(base.resolve()),'exposure_ledger':study.provenance(),'arms':rows,'summary':_summary(rows),
                'summary_by_metric':{metric:{arm:values[metric] for arm,values in _summary(rows).items()} for metric in ('roc_auc','background_rejection_at_signal_eff','ece','brier')},'test_reads':1,'environment_sha256':digest(environment),
                'backend_plan':task['placement']['backend_plan'],'device':'cpu',
                'budget_definition':'Equal full-dataset epochs and wall ceilings per arm/seed; not equal FLOPs.',
                'scope':'Weighted binary classification on supplied disjoint events; seed spread is sample standard deviation, not a confidence interval.'}
            validate_receipt(receipt,task,output,pending=True,test_arrays={'x':test[0],'y':test[1],'weight':test[2]})
            _write_new(output/'receipt.json',receipt)
            result={'status':'passed','physics_validated':False,'receipt':pin(output/'receipt.json'),
                    'summary':receipt['summary'],'scope':receipt['scope'],
                    'limitations':['No detector or physics certification.', 'No hyperparameter search or post-test selection.',
                     'Zero observed background is reported as undefined rejection, not infinite sensitivity.',
                     'Reliability metrics measure calibration; probabilities are not recalibrated on test data.']}
            (output/'RESULT.md').write_text('# ML method study\n\nEvery declared arm and seed was trained before the withheld test split was decoded once.\n\n'
                'The complete metrics, seed spread and pins are in [receipt.json](receipt.json). '
                'Training uses equal epoch counts and wall ceilings per arm; this is not equal FLOPs. '
                'No model is selected using test scores.\n\nSee [ROC](roc.png) and [reliability](reliability.png). '
                'This computation does not establish physics validity.\n')
            from ravel.plotting.ml_training_figures import render
            result['figures']=render(receipt,output)
            _write_new(output/'result.json',result)
            atomic_json(exposure,{'spec_sha256':spec.sha256,'state':'complete','test_reads':reads,'receipt':pin(output/'receipt.json')})
            study.close('complete',pin(output/'receipt.json'))
            return result
        except BaseException as exc:
            atomic_json(exposure,{'spec_sha256':spec.sha256,'state':'failed','test_reads':reads,'error':str(exc)})
            study.close('failed')
            raise


def size_study(spec):
    """Executor-local cross-fit counts and cost preflight; see ml_crossfit.size_study."""
    from . import ml_crossfit
    return ml_crossfit.size_study(spec)


def is_config_pin(arm):
    return isinstance(arm.get('config'),dict) and set(arm['config'])=={'path','sha256'}


def resolve_arm(arm, base):
    result=json.loads(json.dumps(arm))
    if is_config_pin(arm): result['config']=json.loads(_bytes(arm['config'],base))
    if 'code' in arm:
        if hashlib.sha256(_bytes(arm['code'],base)).hexdigest()!=pin(ml_backends.__file__)['sha256']:
            raise ValueError('model code pin must match the installed allowlisted backend; arbitrary code is not admitted')
        result.pop('code')
    return result


def resolved_task(task, base):
    result=json.loads(json.dumps(task))
    for key in ('models','baselines'): result[key]=[resolve_arm(a,base) for a in task[key]]
    return result


def run_in_worker(task, base_dir, output_dir, *, worker_started):
    """Carry the admitted run root to gates while pins retain the spec directory."""
    if task.get('splits',{}).get('method')!='kfold_crossfit':
        return run(task,base_dir,output_dir)
    out=Path(output_dir).resolve()
    if out.parent.name!='outputs' or not re.fullmatch(r'attempt-[1-9][0-9]*',out.name):
        raise ValueError('cross-fit worker requires the admitted attempt output directory')
    rundir=out.parent.parent
    plan=json.loads((rundir/'inputs/science-plan.json').read_text())
    attempt=json.loads((rundir/'execution_attempt.json').read_text())
    if (plan['mode']!='ml-training' or Path(plan['base_dir']).resolve()!=Path(base_dir).resolve()
            or out.name!=f"attempt-{attempt['attempt']}"):
        raise ValueError('cross-fit worker run/spec/attempt context differs')
    from . import ml_crossfit
    return ml_crossfit.run(task,base_dir,output_dir,rundir=rundir)
