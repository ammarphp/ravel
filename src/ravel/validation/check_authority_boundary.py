"""Inert artifact/board canaries at the broker data/control boundary.

This check tests the owned admission path, not all downstream gates. Registered
gate/work-order producers must separately test their typed input projection.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import tempfile

from ravel.workflow.broker import Broker, authority_inputs, runtime_dir, work_root

CHECK_ID = 'check:authority_boundary'


def check(fixtures=None):
    root=Path(fixtures) if fixtures else Path(__file__).resolve().parents[3]/'tests/fixtures/canaries'
    gate_inputs=[];work_orders=[];errors=[];observations=[]
    # Never override HOME. Restore only the isolated custody variable we own.
    previous=os.environ.get('RAVEL_STATE_DIR')
    with tempfile.TemporaryDirectory(prefix='rv-boundary-',dir=runtime_dir()) as temporary:
        temp=Path(temporary);os.environ['RAVEL_STATE_DIR']=str(temp/'state')
        run=temp/'run';run.mkdir();workspace=work_root(run)/'canary/1'
        for name in ('inputs','outputs','scratch','calls'):(workspace/name).mkdir(parents=True,exist_ok=True)
        try:
            broker=Broker(run,workspace,node_id='canary',attempt=1,
                allowed_actions=['read','board read'],max_calls=20)
            board_post={}
            broker.register('board read',lambda args:{'stdout':board_post['text']},read_only=True)
            # These trusted spies are deliberately registered but absent from
            # the role allowlist. Both prose surfaces are exercised identically.
            broker.register('gate authorize',lambda args:gate_inputs.append(args) or {})
            broker.register('work dispatch',lambda args:work_orders.append(args) or {})
            for i,name in enumerate(('artifact.txt','board-post.json')):
                content=(root/name).read_text()
                if 'AUTHORITY_CANARY_' not in content:raise ValueError('missing canary')
                (workspace/'inputs'/name).write_text(content)
                if name=='board-post.json':
                    board_post['text']=content
                    request={'call_id':f'read-{i}','action':'board read','args':{'actor_id':'self'}}
                else:request={'call_id':f'read-{i}','action':'read','args':{'path':'inputs/'+name}}
                reply=broker.call(request)
                projection=authority_inputs(reply)
                if 'AUTHORITY_CANARY_' in json.dumps(projection):errors.append('prose reached authority projection')
                for j,action in enumerate(('gate authorize','work dispatch')):
                    refused=broker.call({'call_id':f'control-{i}-{j}','action':action,'args':{'text':content}})
                    if refused['status']!='refused':errors.append('injected control admitted')
                observations.append({'surface':name,'read_status':reply['status'],'projection':projection})
            broker.verify_ledger()
            if gate_inputs or work_orders:errors.append('canary created authority')
        except (OSError,ValueError) as exc:errors.append(str(exc))
        finally:
            if previous is None:os.environ.pop('RAVEL_STATE_DIR',None)
            else:os.environ['RAVEL_STATE_DIR']=previous
    return {'check_id':CHECK_ID,'valid':not errors,'errors':errors,
            'gate_inputs':gate_inputs,'work_orders':work_orders,'observations':observations,
            'scope':'broker admission and receipt projection; downstream consumer gates require their own controls'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--fixtures',type=Path)
    args=parser.parse_args(argv);value=check(args.fixtures);print(json.dumps(value,indent=2))
    return 0 if value['valid'] else 1


if __name__=='__main__':raise SystemExit(main())
