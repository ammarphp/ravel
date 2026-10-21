"""Bounded supplied linear-response calibration with evaluator-owned confirmation.

No simulator is executed. Each node supplies nominal bin yields and a declared
knob coefficient matrix from frozen generated/showered sample provenance.
The production role sees only adaptive nodes. The evaluator reads held-out
artifacts once, after live approval binds the response and freeze bytes.

Every node input is read once and must be a registered acquisition or registered
stage output (``calibration_checks.custody``). Exposure is also kept per agreement
target, keyed by the content of its reference pins: trials accumulate across studies
(``target_trials``), and a held-out value vector already scored for the target is
refused in any later study. Each study keeps its own run journal under
``research/calibration/``. Held-out files are ordinary run files, so the receipt
records that sealing is an evaluator convention backed by the worker sandbox.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import itertools
import math
import os
import json
from pathlib import Path

from ravel.physics import ml_exposure
from ravel.validation import calibration_checks as cc
from ravel.workflow.state_io import atomic_json


def write_new(path, value):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError('regular calibration output required')
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with path.open('xb') as handle: handle.write(raw)
    return {'path':str(path.absolute()),'sha256':hashlib.sha256(raw).hexdigest()}


def target_binding(rundir,spec):
    """Consume valid current agreement targets and exclude every claim reference."""
    from ravel.validation import agreement_target
    targets=agreement_target.targets(rundir)
    declared={cc.pin_identity(p,rundir) for p in spec['agreement_target']['reference']['pins']}
    matched=[cid for cid,t in targets.items() if declared=={cc.pin_identity(p,rundir) for p in t['reference']['pins']}]
    if not matched: raise ValueError('calibration must bind a current agreement target')
    check=deepcopy(spec)
    check['agreement_target']['reference']['pins']=[p for t in targets.values() for p in t['reference']['pins']]
    cc.calibration_target_disjoint(check,rundir)
    return {'claim_ids':sorted(matched),'reference_pins':check['agreement_target']['reference']['pins']}


def approval_binding(rundir, *, spec=None, pins=()):
    """Replay the live approval and require explicit commitments, not a claimed fingerprint."""
    from ravel.workflow import workflow_state
    errors=workflow_state.verify_approval(rundir)
    if errors: raise ValueError('calibration approval refused: '+'; '.join(errors))
    path=Path(rundir)/'inputs/checkin1_approval.json'
    record=json.loads(path.read_bytes())
    rows=record.get('approved_inputs',[])
    for pin in pins:
        identity=cc.pin_identity(pin,rundir)
        if not any(cc.pin_identity({'path':r['path'],'sha256':r['sha256']},rundir)==identity
                   for r in rows if r.get('state')=='file'):
            raise ValueError('calibration approval does not bind response/freeze hash')
    if spec is not None:
        target_binding(rundir,spec)
        matched=False
        # Only the explicitly named specification is read, never arbitrary approved held-out artifacts.
        for row in rows:
            if row.get('state')=='file' and Path(row['path']).name == 'calibration-spec.json':
                if cc.digest(cc.read_pin(row,rundir)) == cc.digest(spec): matched=True
        if not matched: raise ValueError('calibration approval must pin calibration-spec.json')
    return {'input_fingerprint':record['input_fingerprint'],'approval_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def calibration_action(spec, *, response_sha256=None, floor='R2'):
    value={'kind':'detector-calibration','spec_sha256':cc.digest(spec),'response_sha256':response_sha256}
    return {**value,'digest':cc.digest(value),'floor':floor}


def calibration_authorization(rundir, spec, *, response_sha256=None, floor='R2', human=False):
    from ravel.workflow import rdj_loop
    action=calibration_action(spec,response_sha256=response_sha256,floor=floor)
    result=rdj_loop.authorizing_receipt(rundir,'checkin2_accept',action)
    if result is None: raise ValueError(f'calibration requires scoped {floor}'+(' human approval' if human else ' authorization'))
    case=result['case'];receipt=result['receipt']
    if case.get('decision_point',{}).get('tuning',{}).get('class') != 'calibration':
        raise ValueError('RDJ decision must be calibration')
    if human and (result.get('review_independence') or {}).get('human_approver') is not True:
        raise ValueError('out-of-band calibration requires R3 human approval')
    return {'receipt_sha256':result['receipt_sha256'],'case_sha256':result['case_sha256'], 'action':action}


def signal_model_authorization(rundir,spec):
    from ravel.workflow import rdj_loop
    action=spec['signal_model']['approximation_action']
    if not isinstance(action,dict) or action.get('kind')!='approximation':
        raise ValueError('signal-model approximation requires an exact decision action')
    if rdj_loop.authorizing_receipt(rundir,'checkin2_accept',{**action,'floor':'R2'}) is None:
        raise ValueError('signal-model approximation requires its scoped R2 authorization')


SEALING = ('evaluator-convention: held-out artifacts are run files; separation relies on the evaluator '
           'store and the worker sandbox')


def _state_path(study):
    # Existing authority lock/root, independent of a run directory or ordinary state override.
    return ml_exposure.root()/'calibration'/f'{study}.json'


def _target_key(spec):
    """Content key of the agreement target: the sha256 of its reference pins, not a study id."""
    return cc.digest(sorted(p['sha256'] for p in spec['agreement_target']['reference']['pins']))


def _target_path(spec):
    return ml_exposure.root()/'calibration-targets'/f'{_target_key(spec)}.json'


def _target_load(spec):
    path=_target_path(spec)
    if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError('symlink calibration target ledger')
    return json.loads(path.read_bytes()) if path.exists() else {'schema_version':1,'trials':0,'scored':[]}


def _target_save(spec,value):
    path=_target_path(spec);path.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(path,value)


def _journal(state):
    return Path(state['reader'])/'research/calibration'/f'{state["study_id"]}.jsonl'


def _load(path):
    if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError('symlink calibration authority')
    value=json.loads(path.read_bytes()) if path.exists() else None
    if value is not None:
        previous=None
        for event in value['events']:
            unsigned={k:v for k,v in event.items() if k!='sha256'}
            if event['previous_sha256'] != previous or cc.digest(unsigned)!=event['sha256']:
                raise ValueError('calibration exposure journal changed')
            previous=event['sha256']
    return value


def _keys(node):
    return {*(p['sha256'] for p in cc.node_pins(node)), *['sample:'+s for s in node['sample_ids']]}


def _append(state, node, event, role, *, receipt=None):
    row={'schema_version':1,'kind':'exposure-entry','study_id':state['study_id'],
         'key':cc.digest(node),'key_kind':'cell','role':role,'event':event,
         'reader':{'rundir':state['reader'],'arm':'response','candidate':state['candidate'],
                   'seed':node.get('seed'),'round':state['epoch']},
         'selection_receipt':state.get('freeze'),'receipt':receipt,
         'utc':datetime.now(timezone.utc).isoformat(),
         'previous_sha256':state['events'][-1]['sha256'] if state['events'] else None}
    row['sha256']=cc.digest(row);state['events'].append(row)


def _save(state):
    path=_state_path(state['study_id']);path.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(path,state)
    local=_journal(state)
    if any(p.is_symlink() for p in (local,*local.parents)): raise ValueError('symlink run exposure journal')
    local.parent.mkdir(parents=True,exist_ok=True)
    raw=''.join(json.dumps(e,sort_keys=True)+'\n' for e in state['events'])
    prior=local.read_text() if local.exists() else ''
    if not raw.startswith(prior): raise ValueError('run journal is not a prefix of authority')
    with local.open('a') as handle: handle.write(raw[len(prior):])


def _start(rundir,spec):
    with ml_exposure._locked():
        path=_state_path(spec['study_id']);state=_load(path)
        cohort=cc.digest({'calibration':spec['calibration_nodes'],'held_out':spec['held_out_nodes'],
                          'reference':spec['agreement_target']})
        if state and state['cohort_sha256']!=cohort: raise ValueError('preregistered calibration population changed')
        held={key for n in spec['held_out_nodes'] for key in _keys(n)}
        adaptive={key for n in spec['calibration_nodes'] for key in _keys(n)}
        for other in path.parent.glob('*.json'):
            prior=_load(other)
            if other!=path and (held|adaptive).intersection(prior['reserved_keys']):
                raise ValueError('calibration samples already reserved by another study')
        if state and state['spent']:
            raise ValueError('held-out nodes already read/spent; new calibration cannot reuse them')
        if state is None:
            state={'study_id':spec['study_id'],'cohort_sha256':cohort,'events':[], 'epoch':0,'trials':0,
                   'reserved_keys':sorted(held|adaptive),'spent':False,'freeze':None}
        state.update(reader=str(Path(rundir).absolute()),candidate=cc.digest(spec),epoch=state['epoch']+1,freeze=None)
        for n in spec['calibration_nodes']:_append(state,n,'claim','adaptive_full')
        for n in spec['held_out_nodes']:_append(state,n,'claim','withheld_confirmation')
        _save(state)
        return state['epoch']


def _read_node(rundir,spec,node,epoch,*,freeze=None):
    with ml_exposure._locked():
        state=_load(_state_path(spec['study_id']))
        if not state or state['epoch']!=epoch or state['candidate']!=cc.digest(spec): raise ValueError('calibration epoch changed')
        withheld=node in spec['held_out_nodes']
        if withheld:
            if freeze is None or state.get('freeze')!=freeze: raise ValueError('confirmation requires current freeze hash')
            key=cc.digest(node)
            if any(e['event']=='read' and e['key']==key for e in state['events']): raise ValueError('held-out node already read/spent')
            state['spent']=True
        elif state['spent']: raise ValueError('adaptive read after confirmation refused')
        _append(state,node,'read','withheld_confirmation' if withheld else 'adaptive_full')
        _save(state) # Debit before reading bytes. An interrupted/failed read is spent too.
    for stage,pin in node['samples'].items():
        try:
            cc.read_custody(pin,rundir,f'node {node["id"]} {stage} sample',limit=64*1024**2)
        except ValueError as exc:
            raise ValueError(f'frozen generated/showered sample pin changed or lacks custody: {exc}') from None
    response=json.loads(cc.read_custody(node['response'],rundir,f'node {node["id"]} response'))
    values=cc.observable(json.loads(cc.read_custody(node['observable'],rundir,f'node {node["id"]} observable')),node)
    if withheld:
        with ml_exposure._locked():
            ledger=_target_load(spec);key=cc.digest([round(float(v),9) for v in values])
            if key in ledger['scored']:
                raise ValueError('held-out values already scored for this agreement target in an earlier study')
            ledger['scored'].append(key);_target_save(spec,ledger)
    else:
        cc.refuse_reference_values(values,cc.reference_vectors(spec,rundir),node['id'])
    if any(response.get(k)!=node[k] for k in ('seed','sample_ids','samples')) or response.get('node')!=node['id']:
        raise ValueError('response lineage differs from declared node/seed/samples')
    base=response.get('base');matrix=response.get('coefficients')
    if not isinstance(base,list) or len(base)!=len(values) or not all(cc.number(x) for x in base): raise ValueError('finite nominal per-bin response required')
    if not isinstance(matrix,list) or len(matrix)!=len(base): raise ValueError('one coefficient row per bin required')
    for b,row in enumerate(matrix):
        if not isinstance(row,list) or len(row)!=len(spec['knobs']) or not all(cc.number(x) for x in row): raise ValueError('finite declared knob matrix required')
        if any(x!=0 and b not in k['bins'] for x,k in zip(row,spec['knobs'])):
            raise ValueError('global signal scalar or undeclared knob-bin response refused')
    for k,knob in enumerate(spec['knobs']):
        column=[row[k] for row in matrix]
        norms=math.sqrt(sum(x*x for x in column))*math.sqrt(sum(x*x for x in base))
        if set(range(len(base)))<=set(knob['bins']) and norms>0 and \
                sum(x*y for x,y in zip(column,base))/norms>=cc.SCALAR_COSINE:
            raise ValueError(f'global signal scalar refused: knob {knob["module"]}/{knob["parameter"]} scales '
                             'every bin in proportion to the nominal response')
    return {'node':node['id'],'base':base,'coefficients':matrix,'target':values}


def _prediction(row,knobs,parameters):
    return [v+sum(c*(x-k['nominal']) for c,x,k in zip(cs,parameters,knobs)) for v,cs in zip(row['base'],row['coefficients'])]


def _loss(rows,knobs,parameters):
    return sum((p-y)**2 for row in rows for p,y in zip(_prediction(row,knobs,parameters),row['target']))


def fit(rundir,spec,output_dir):
    """Fit the finite declared candidates, stop, and freeze; never read held-out files."""
    rundir=Path(rundir).absolute();spec=deepcopy(spec)
    if not Path(output_dir).absolute().is_relative_to(rundir): raise ValueError('calibration output must belong to this run')
    flags=cc.validate_spec(spec,rundir,check_observables=False)
    if flags['approximation']: signal_model_authorization(rundir,spec)
    floor='R3' if flags['outside_band'] else 'R2'
    authorization=calibration_authorization(rundir,spec,floor=floor,human=flags['outside_band'])
    approved=approval_binding(rundir,spec=spec)
    epoch=_start(rundir,spec)
    rows=[_read_node(rundir,spec,node,epoch) for node in spec['calibration_nodes']]
    knobs=spec['knobs'];nominal=[k['nominal'] for k in knobs]
    imported=spec['imported_calibration']
    if imported is None:
        candidates=itertools.product(*(k['values'] for k in knobs))
    else:
        supplied=cc.read_pin(imported['response'],rundir)
        values=supplied.get('parameters')
        if not isinstance(values,list) or len(values)!=len(knobs) or not all(cc.number(x) for x in values): raise ValueError('imported parameters required')
        if any(v not in k['values'] for v,k in zip(values,knobs)): raise ValueError('imported parameters outside declared candidates')
        candidates=iter([values])
    cap=min(spec['stop']['max_trials'],spec['budget']['max_trials'])
    best=None;trials=[];reason='candidate_exhausted'
    for parameters in candidates:
        if len(trials)>=cap: reason='max_trials';break
        with ml_exposure._locked():
            state=_load(_state_path(spec['study_id']))
            if state['epoch']!=epoch or state['spent']: raise ValueError('calibration epoch changed or spent')
            state['trials']+=1
            _append(state,{'parameters':list(parameters)},'query','adaptive_full')
            _save(state)
            ledger=_target_load(spec);ledger['trials']+=1;_target_save(spec,ledger)
        loss=_loss(rows,knobs,parameters)
        if not cc.number(loss): raise ValueError('nonfinite calibration loss')
        trials.append({'parameters':list(parameters),'loss':loss})
        if best is None or loss<best['loss']: best=trials[-1]
        if loss<=spec['stop']['loss_at_most']: reason='loss_at_most';break
    response=write_new(Path(output_dir)/'response.json',{'schema_version':1,'kind':'cal:response',
                      'parameters':best['parameters'],'knobs':knobs,'spec_sha256':cc.digest(spec),'epoch':epoch})
    with ml_exposure._locked():
        state=_load(_state_path(spec['study_id']))
        if state['epoch']!=epoch: raise ValueError('calibration epoch changed before freeze')
        result={'schema_version':1,'kind':'cal:receipt','spec':spec,'parameters':best['parameters'],
                'response':response,'epoch':epoch,'n_trials':len(trials),'study_trials':state['trials'],
                'trials':trials,'stop_reason':reason,'approval':approved,'authorization':authorization,
                'calibration_nodes':[n['id'] for n in spec['calibration_nodes']],
                'imported_calibration':imported,'imported_in_sample':flags['imported_in_sample'],
                'target_trials':_target_load(spec)['trials'],'sealing':SEALING,
                'before':{'loss':_loss(rows,knobs,nominal)},'after':{'loss':best['loss']},
                'checks':[cc.calibration_target_disjoint(spec,rundir),cc.confirmation_separation(spec,rundir)],
                'exposure_head':state['events'][-1]['sha256'],'evidence_status':'checked',
                'test_namespace':bool(os.environ.get('RAVEL_ML_TEST_NAMESPACE'))}
        freeze=write_new(Path(output_dir)/'freeze.json',result)
        state['freeze']=freeze;_save(state)
    return {**result,'freeze':freeze}


def confirm(rundir,freeze):
    """Evaluator-only: approve frozen bytes, debit each held-out read once, deliver both results."""
    rundir=Path(rundir).absolute()
    result=cc.read_pin(freeze,rundir);spec=result['spec']
    response=cc.read_pin(result['response'],rundir)
    if response['parameters']!=result['parameters'] or response['spec_sha256']!=cc.digest(spec): raise ValueError('freeze response mismatch')
    approval=approval_binding(rundir,spec=spec,pins=[freeze,result['response']])
    flags=cc.validate_spec(spec,rundir,check_observables=False)
    if flags['approximation']: signal_model_authorization(rundir,spec)
    auth=calibration_authorization(rundir,spec,response_sha256=result['response']['sha256'],
                                   floor='R3' if flags['outside_band'] else 'R2',human=flags['outside_band'])
    scores=[];knobs=spec['knobs'];nominal=[k['nominal'] for k in knobs]
    for node in spec['held_out_nodes']:
        row=_read_node(rundir,spec,node,result['epoch'],freeze=freeze)
        scores.append({'node':node['id'],'before':{'values':_prediction(row,knobs,nominal),'loss':_loss([row],knobs,nominal)},
                       'after':{'values':_prediction(row,knobs,result['parameters']),'loss':_loss([row],knobs,result['parameters'])}})
    with ml_exposure._locked():
        state=_load(_state_path(spec['study_id']))
        _append(state,{'response':result['response']},'close','withheld_confirmation',receipt=result['response'])
        result.update(held_out_scores=scores,before={'loss':sum(r['before']['loss'] for r in scores)},
                      after={'loss':sum(r['after']['loss'] for r in scores)},freeze=freeze,
                      confirmation_approval=approval,confirmation_authorization=auth,
                      exposure_head=state['events'][-1]['sha256'],study_trials=state['trials'],
                      target_trials=_target_load(spec)['trials'])
        cc.delivery_check(result)
        pin=write_new(Path(freeze['path']).parent/'confirmation.json',result)
        state['delivery']=pin
        _save(state)
    return result


def verify_delivery(rundir, path, *, evidence_status='checked', allow_test_namespace=False):
    """Reconcile delivered bytes and both journal heads without rereading held-out artifacts.
    A receipt written under the test exposure namespace is refused unless the caller is a test."""
    path=Path(path).absolute();rundir=Path(rundir).absolute()
    raw=path.read_bytes();receipt=json.loads(raw);spec=receipt['spec']
    if receipt.get('test_namespace') and not allow_test_namespace:
        raise ValueError('calibration receipt was written under the test namespace; it is not a delivery')
    with ml_exposure._locked():
        state=_load(_state_path(spec['study_id']))
        actual={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
        if state is None or state.get('delivery')!=actual:
            raise ValueError('calibration delivery bytes changed or lack evaluator receipt')
        local=rundir/'research/calibration'/f'{spec["study_id"]}.jsonl'
        expected=''.join(json.dumps(e,sort_keys=True)+'\n' for e in state['events'])
        if local.read_text()!=expected or receipt['exposure_head']!=state['events'][-1]['sha256']:
            raise ValueError('calibration exposure ledger heads differ')
        reads=[e for e in state['events'] if e['event']=='read' and e['role']=='withheld_confirmation']
        if len(reads)!=len(spec['held_out_nodes']) or {e['key'] for e in reads}!={cc.digest(n) for n in spec['held_out_nodes']}:
            raise ValueError('confirmation ledger does not cover every held-out node exactly once')
        if receipt['study_trials']!=state['trials'] or receipt['freeze']!=state['freeze']:
            raise ValueError('calibration trial count or freeze changed')
    cc.read_pin(receipt['response'],rundir);cc.read_pin(receipt['freeze'],rundir)
    approval_binding(rundir,spec=spec,pins=[receipt['freeze'],receipt['response']])
    flags=cc.validate_spec(spec,rundir,check_observables=False)
    if flags['approximation']: signal_model_authorization(rundir,spec)
    calibration_authorization(rundir,spec,response_sha256=receipt['response']['sha256'],
                              floor='R3' if flags['outside_band'] else 'R2',human=flags['outside_band'])
    cc.delivery_check(receipt,evidence_status=evidence_status)
    return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rundir',type=Path,required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('fit');p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('confirm');p.add_argument('--freeze',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='fit': result=fit(args.rundir,json.loads(args.spec.read_bytes()),args.out)
        else:
            raw=args.freeze.read_bytes();result=confirm(args.rundir,{'path':str(args.freeze.absolute()),'sha256':hashlib.sha256(raw).hexdigest()})
        print(json.dumps(result,sort_keys=True));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(2,str(exc)+'\n')


if __name__=='__main__':raise SystemExit(main())
