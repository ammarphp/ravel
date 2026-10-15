"""RAVEL-level bounded retries for partition tasks of a workflow-manager project.

Snakemake retries stay 0: a Snakemake retry would re-run a spent `run-step`. When a
partition task's run-step ends without delivery, `retry` prepares a fresh attempt
run dir from the same approved master partition specification:

1. The first call checks the partition's attempt journal. Earlier attempts must
   be failed or have run without ordinary delivery. An unresolved attempt blocks
   the retry until supervised recovery resolves it, and the attempts
   used must be below the master's approved `max_attempts`. It then plans the fresh
   run dir. Nothing is approved here.
2. After the operator approves that plan (`ravel approve --rundir <attempt>`), the
   second call registers it as a new workflow task (`wms_launch.add`).

Earlier attempt run dirs are kept, failed attempts stay charged, and every step is
recorded in `workflow/retries/<master>-<partition>.json`. The merge consumes exactly
one delivered attempt per partition (`root_stream_partitions.fanin`).
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ravel.physics import root_stream_core as core, root_stream_partitions as partitions
from .state_io import atomic_json, file_lock


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _read(path):
    return json.loads(Path(path).read_bytes())


def _registrar():
    """The same project-workflow `add` route used by `ravel wms add`."""
    from . import wms_launch
    return wms_launch.add


def _workflow(project):
    wf = Path(project).expanduser().absolute().resolve() / 'workflow'
    core.require((wf / 'index.json').is_file(), f'no workflow-manager project at {wf}; run `ravel wms init` first')
    return wf


def _branch(rundir):
    """(master, partition id) of an ordinary partition run dir, from its copied specification.

    The failed attempt itself is not re-verified here: its execution record may be the
    very thing that is unresolved. The master and its journal are authenticated.
    """
    from . import science
    spec = _read(Path(rundir) / science.SPEC)
    core.require(spec.get('mode') == 'root-stream', 'retry applies to partition tasks only')
    cap = core.Capture()
    selected = partitions.dispatch_master(spec['task'], Path(rundir), cap)
    cap.finish()
    core.require(selected is not None and selected[1] != 'merge',
                 'retry applies to partition tasks only; a merge or full stream needs its own recovery')
    return selected


def retry(project, task):
    """Plan a fresh attempt for a failed partition task, or register an approved one."""
    from . import method_selection, science
    wf = _workflow(project)
    with file_lock(wf / '.wms-retry.lock', blocking=False):
        index = _read(wf / 'index.json')
        entry = next((row for row in index['tasks'] if row['id'] == task), None)
        core.require(entry is not None, f'task {task} is not in the index')
        core.require(entry['owner'] == {'kind': 'ordinary'},
                     'a campaign-owned partition is retried as a new campaign experiment, not by ravel wms retry')
        master, pid = _branch(entry['rundir'])
        _, state = partitions.owner_state(master)
        claims = [row for row in partitions.master_claims(master, state) if row['task_id'] == pid]
        core.require(claims, f'partition {pid} has no attempt yet; launch task {task} instead of retrying it')
        ledger_path = wf / 'retries' / f"{master['master_pin']['sha256'][:16]}-{pid}.json"
        ledger = _read(ledger_path) if ledger_path.is_file() else {
            'schema_version': 1, 'master': master['master_pin'], 'partition_id': pid,
            'max_attempts': partitions.master_fanout(master)['max_attempts'], 'root_task': task, 'attempts': []}
        core.require(ledger['master'] == master['master_pin'] and ledger['partition_id'] == pid, 'retry ledger belongs to another partition')
        tasks = {row['rundir']: row['id'] for row in index['tasks']}
        first = Path(claims[0]['rundir'])
        number = len(claims) + 1
        fresh = first.parent / f'{first.name}-attempt{number}'
        # Retained attempts as they stand now; an attempt that never reached its claim is pending.
        ledger['attempts'] = [{'attempt': i + 1, 'rundir': row['rundir'], 'task': tasks.get(row['rundir']),
                               'state': partitions.attempt_state(row['rundir'])} for i, row in enumerate(claims)]
        reason = partitions.retry_admission(master, partitions.master_claims(master, state), pid)
        core.require(reason is None, reason or '')
        # After admission: a governed project's own export of the original verifies its plan,
        # which an unresolved attempt record must not turn into a different refusal.
        if 'merge_exports' not in ledger:
            ledger['merge_exports'] = _merge_exports(wf, ledger['root_task'], claims[0]['rundir'])
        # Always carry the first claimed run's decision, including later retries.
        method_selection.require_launch(first)
        decision = (first / method_selection.DECISION_PATH).read_bytes()
        decision_sha256 = hashlib.sha256(decision).hexdigest()
        if not fresh.exists():
            specification = Path(master['master_pin']['path']).parent / f'{pid}-spec.json'
            core.require(_read(specification) == _read(Path(entry['rundir']) / science.SPEC),
                         'the attempt specification differs from the approved master partition plan')
            science.plan(fresh, str(specification))
            (fresh / method_selection.DECISION_PATH).write_bytes(decision)
            method_selection.refresh_checkin(fresh)
            step = {'attempt': number, 'rundir': str(fresh), 'action': 'planned', 'utc': _utc()}
            result = {'status': 'planned', 'rundir': str(fresh), 'attempt': number,
                      'next': f'ravel approve --rundir {fresh}; then ravel wms retry --task {task}'}
        else:
            core.require(str(fresh) not in tasks, f'attempt {fresh} is already registered as task {tasks.get(str(fresh))}')
            carried = fresh / method_selection.DECISION_PATH
            core.require(carried.is_file() and carried.read_bytes() == decision,
                         'retry method-decision bytes differ from the origin record; preserve the planned attempt for review')
            try:
                science.verify_plan(fresh, approved=True)
            except (ValueError, OSError, KeyError) as exc:
                raise ValueError(f'attempt {fresh} is planned but not approved ({exc}); approve it with '
                                 f'`ravel approve --rundir {fresh}`; a retry never approves') from exc
            identity = f"{ledger['root_task']}_a{number}"
            added = _registrar()(project, fresh, task=identity)
            step = {'attempt': number, 'rundir': str(fresh), 'action': 'registered', 'task': added['id'], 'utc': _utc()}
            result = {'status': 'registered', 'rundir': str(fresh), 'attempt': number, 'task': added['id'],
                      'next': f"ravel wms launch --task {added['id']}"}
        step['method_decision_sha256'] = decision_sha256
        ledger.setdefault('steps', []).append(step)
        ledger_path.parent.mkdir(exist_ok=True)
        atomic_json(ledger_path, ledger)
    return {**result, 'partition_id': pid, 'max_attempts': ledger['max_attempts'], 'ledger': str(ledger_path),
            'method_decision_sha256': decision_sha256,
            'merge_exports': ledger['merge_exports'], 'execution_authorized': False, 'scientific_acceptance_inferred': False}



def _merge_exports(wf,root_task,rundir):
    """Retain byte-pinned exports waiting for this original partition's delivery."""
    from . import site_workflow
    exports=[]
    for path in sorted((wf/'exports').glob('*/workflow.json')):
        # Another task's export, whatever its state, neither blocks nor informs this retry.
        try:rows=_read(path)['tasks']
        except (OSError,ValueError,KeyError,TypeError):continue
        if type(rows) is not list or not any(type(t) is dict and t.get('id')==root_task and t.get('rundir')==rundir for t in rows):continue
        pin=site_workflow._pin(path);document=site_workflow.verify(path,pin['sha256'])
        if any(t['id']==root_task and t['rundir']==rundir for t in document['tasks']) and \
                site_workflow._partition_binding(document,root_task) is not None:
            exports.append({'path':str(path),'sha256':pin['sha256'],'task':root_task})
    return exports


def export_project(path):
    """The project whose `workflow/exports/` holds this export; None for an export elsewhere."""
    path=Path(path).absolute();wf=path.parent.parent.parent
    inside=path.parent.parent.name=='exports' and wf.name=='workflow' and (wf/'index.json').is_file()
    return wf.parent if inside else None


def registered_project(project,master,pid,claim,path):
    """The project that registered this attempt through `ravel wms retry`, else None.

    An attempt approved and run outside the retry command (a direct ordinary run or a
    new campaign experiment) has no retry ledger: its journal claim is its custody.
    """
    project=Path(project).expanduser().absolute().resolve() if project is not None else export_project(path)
    if project is None:return None
    ledger_path=project/'workflow'/'retries'/f"{master['master_pin']['sha256'][:16]}-{pid}.json"
    if not ledger_path.is_file():return None
    steps=_read(ledger_path).get('steps',[])
    return project if any(step['action']=='registered' and step['rundir']==claim['rundir'] for step in steps) else None


def registered_delivery_ledger(project,master,pid,claim,path,digest,identity):
    """An approved, registered retry may publish only to its recorded original export."""
    core.require(project is not None,'registered retry publication requires its project')
    wf=_workflow(project);ledger_path=wf/'retries'/f"{master['master_pin']['sha256'][:16]}-{pid}.json"
    ledger=_read(ledger_path)
    core.require(ledger['master']==master['master_pin'] and ledger['partition_id']==pid and
                 ledger['root_task']==identity,'retry publication belongs to another master or partition')
    core.require({'path':str(Path(path).absolute()),'sha256':digest,'task':identity} in ledger['merge_exports'],
                 'retry was not registered for this original export')
    index=_read(wf/'index.json')
    registered=[step for step in ledger['steps'] if step['action']=='registered' and step['rundir']==claim['rundir']]
    core.require(len(registered)==1 and any(row['id']==registered[0]['task'] and row['rundir']==claim['rundir']
                 and row['owner']=={'kind':'ordinary'} for row in index['tasks']),
                 'attempt has no original project retry registration')
    return str(ledger_path)


def record_delivery_publication(ledger_path,claim,publication,path,digest,identity,*,visible=False):
    """Retain issuance first; record visibility only after the task output exists."""
    ledger_path=Path(ledger_path);wf=ledger_path.parent.parent
    # Waits for a concurrent `ravel wms retry`: a delivered attempt must not fail its step on a busy ledger.
    with file_lock(wf/'.wms-retry.lock'):
        ledger=_read(ledger_path)
        registered=next(step for step in ledger['steps'] if step['action']=='registered' and step['rundir']==claim['rundir'])
        action='delivery-published' if visible else 'delivery-publication-issued'
        existing=[step for step in ledger['steps'] if step['action']==action and
                  step['publication']==publication and step['rundir']==claim['rundir']]
        if existing:return
        ledger['steps'].append({'action':action,'attempt':registered['attempt'],
            'rundir':claim['rundir'],'utc':_utc(),'publication':publication,
            'export':{'path':str(Path(path).absolute()),'sha256':digest,'task':identity}})
        atomic_json(ledger_path,ledger)


def verify_delivery_publication(ledger_path,master_pin,pid,claim,publication,path,digest,identity):
    """Refuse a marker placed by hand or detached from its registered retry."""
    core.require(type(ledger_path) is str,'retry delivery needs its publication ledger')
    candidate=Path(ledger_path);project=candidate.parent.parent.parent
    master=partitions.read_master(master_pin,Path(path).parent)
    core.require(str(candidate)==registered_delivery_ledger(project,master,pid,claim,path,digest,identity),
                 'canonical retry delivery ledger required')
    ledger=_read(candidate)
    steps=[step for step in ledger['steps'] if step['action']=='delivery-publication-issued' and
           step['publication']==publication and step['rundir']==claim['rundir'] and
           step['export']=={'path':str(Path(path).absolute()),'sha256':digest,'task':identity}]
    registered=next(step for step in ledger['steps'] if step['action']=='registered' and step['rundir']==claim['rundir'])
    core.require(len(steps)==1 and steps[0]['attempt']==registered['attempt'] and steps[0]['utc'],
                 'retry delivery was not issued by the registered publication step')



def require_delivery_visible(ledger_path,publication,path,digest,identity):
    """The merge needs the recorded visibility step, not merely an issued file."""
    ledger=_read(ledger_path)
    steps=[step for step in ledger['steps'] if step['action']=='delivery-published' and
           step['publication']==publication and
           step['export']=={'path':str(Path(path).absolute()),'sha256':digest,'task':identity}]
    issued=next(step for step in ledger['steps'] if step['action']=='delivery-publication-issued' and step['publication']==publication)
    core.require(len(steps)==1 and steps[0]['attempt']==issued['attempt'] and steps[0]['rundir']==issued['rundir'] and steps[0]['utc'],
                 'retry delivery publication is unfinished; call wms_retry.publish_registered_attempt(project, rundir) before the merge')


def publish_registered_attempt(project,rundir):
    """Launch seam: call after ordinary delivery, before relaunching the original export."""
    from . import site_workflow
    wf=_workflow(project)
    registered=[path for path in (wf/'retries').glob('*.json') if any(
        step['action']=='registered' and step['rundir']==str(Path(rundir).absolute())
        for step in _read(path).get('steps',[]))]
    if not registered:return []
    master,pid=_branch(rundir)
    ledger_path=wf/'retries'/f"{master['master_pin']['sha256'][:16]}-{pid}.json"
    if not ledger_path.exists():return []
    ledger=_read(ledger_path)
    if not any(step['action']=='registered' and step['rundir']==str(Path(rundir).absolute()) for step in ledger['steps']):return []
    return [site_workflow.publish_partition_delivery(row['path'],row['task'],row['sha256'],rundir,project=project)
            for row in ledger['merge_exports']]


def publish_original_attempt(project,rundir):
    """Hand-off of a delivered original partition attempt to the project's exports that merge it.

    A governed project runs each original through its own indexed export, so the export
    with the merge rule never dispatches it. Delivery only: publication checks the
    journal claim, the canonical completion and the ordinary pins, and runs nothing.
    """
    from . import site_workflow
    wf=_workflow(project);rd=str(Path(rundir).absolute());published=[]
    for path in sorted((wf/'exports').glob('*/workflow.json')):
        # An export that does not merge this run dir as a partition neither blocks nor informs it.
        try:document=_read(path);rows=document['tasks'];merges=document.get('fanin',[])
        except (OSError,ValueError,KeyError,TypeError,AttributeError):continue
        if type(rows) is not list or type(merges) is not list:continue
        names={name for row in merges if type(row) is dict and type(row.get('partition_tasks')) is dict
               for name in row['partition_tasks']}
        for task in rows:
            if type(task) is dict and task.get('rundir')==rd and task.get('id') in names:
                pin=site_workflow._pin(path)
                published.append(site_workflow.publish_partition_delivery(path,task['id'],pin['sha256'],rd))
    return published


def publish_registered_attempt_for_run(rundir):
    """Ordinary run-step hand-off for project attempts; no registry or launch authority.

    A registered retry publishes through its ledger; an original partition run publishes
    to the project's exports that hold its merge rule.
    """
    rd=Path(rundir).absolute()
    for parent in rd.parents:
        index=parent/'workflow'/'index.json'
        if not index.is_file():continue
        # An unrelated workflow/index.json above the run dir is not a project of this run.
        try:rows=_read(index)['tasks']
        except (OSError,ValueError,KeyError,TypeError):continue
        if type(rows) is list and any(type(row) is dict and row.get('rundir')==str(rd) for row in rows):
            return publish_registered_attempt(parent,rd)+publish_original_attempt(parent,rd)
    return []


def main(argv=None):
    p = argparse.ArgumentParser(prog='ravel wms retry', description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--task', required=True)
    args = p.parse_args(argv)
    print(json.dumps(retry(args.project, args.task), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
