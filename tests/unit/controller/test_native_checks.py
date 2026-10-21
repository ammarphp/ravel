"""Native enforcement records retain their real capsule and reservation boundary."""
from copy import deepcopy
import pytest
from ravel.controller.confine.resource_mechanisms import ResourceMechanism
from ravel.controller.step import native_checks, spec


def subject():
    return ({'journal_id': 'started', 'finished_id': 'finished', 'backend': 'bwrap',
             'plan': {'kind': 'confined', 'network': 'none', 'backend': 'bwrap',
                      'custody_sha256': 'a'*64, 'qualification': {'confirmed': True, 'backend': 'bwrap'},
                      'limits': {'cpus': 1, 'wall_seconds': 60},
                      'limits_enforced': {'cpus': ResourceMechanism.LINUX_CPU_AFFINITY.value, 'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG.value}},
             'confinement': {'errors': []}},
            {'record_id': 'reserved', 'amounts': {'core_hours': 60/3600}},
            {'kind': 'launch', 'equal': True, 'differences': []})


def test_actual_capsule_limits_join_original_reservation():
    args=subject(); before=deepcopy(args)
    rows=native_checks.confinement_rows(*args)
    assert set(rows)=={'T04','E06','T09'}
    assert all(r['status']=='satisfied' and r['evidence']['record']=='finished' for r in rows.values())
    assert rows['E06']['evidence']['reservation']=='reserved'
    assert args==before


@pytest.mark.parametrize('field', ['finished_id','journal_id','plan','confinement'])
def test_missing_actual_record_cannot_lend_credit(field):
    launch,reserve,probe=subject();launch.pop(field)
    assert native_checks.confinement_rows(launch,reserve,probe)=={}


@pytest.mark.parametrize('change', ['unconfined','network','custody','qualification','errors'])
def test_broken_confinement_never_closes_protected_rows(change):
    launch,reserve,probe=subject()
    if change=='unconfined':launch['plan']['kind']='unconfined'
    if change=='network':launch['plan']['network']='host'
    if change=='custody':launch['plan'].pop('custody_sha256')
    if change=='qualification':launch['plan']['qualification']=None
    if change=='errors':launch['confinement']['errors']=['escape']
    assert native_checks.confinement_rows(launch,reserve,probe)=={}


@pytest.mark.parametrize('change', ['cpus','wall','grant','enforced','reserve','overspend'])
def test_limits_without_enforcement_or_original_budget_stay_pending(change):
    launch,reserve,probe=subject()
    if change=='cpus':launch['plan']['limits']['cpus']=True
    if change=='wall':launch['plan']['limits']['wall_seconds']=0
    if change=='grant':launch['plan']['limits_enforced']['cpus']=False
    if change=='enforced':launch['plan']['limits_enforced']['wall_seconds']=None
    if change=='reserve':reserve.pop('record_id')
    if change=='overspend':reserve['amounts']['core_hours']/=2
    assert 'E06' not in native_checks.confinement_rows(launch,reserve,probe)


@pytest.mark.parametrize('probe',[None,{}, {'kind':'worker','equal':True,'differences':[]},
                                  {'kind':'launch','equal':True,'differences':['extra']},
                                  {'kind':'launch','equal':False,'differences':[]}])
def test_inventory_mismatch_cannot_lend_tool_admission(probe):
    launch,reserve,_=subject()
    assert 'T09' not in native_checks.confinement_rows(launch,reserve,probe)


def test_source_admission_checks_each_input_and_records_only_after_all_pass(tmp_path, monkeypatch):
    from ravel.workflow import restriction_guard
    class Store:
        def __init__(self): self.rows=[]
        def append(self, kind, body): self.rows.append((kind,body)); return 'admission-record'
    store=Store(); calls=[]
    def require(tool, descriptor, **scope):
        calls.append((tool,descriptor,scope))
        if descriptor['path'].endswith('denied'): raise ValueError('source denied')
    monkeypatch.setattr(restriction_guard,'require',require)
    step={'id':'s1'}
    admitted=[{'artifact':'inputs/one','path':'inputs/one','sha256':'a'*64}]
    proof=native_checks.source_admission(store,step,tmp_path,admitted,attempt=2)
    assert proof['record']=='admission-record'
    assert len(calls)==1 and calls[0][1]['path']==str(tmp_path/'inputs/one')
    assert store.rows[0][1]['inputs']==admitted
    with pytest.raises(ValueError, match='source denied'):
        native_checks.source_admission(store,step,tmp_path,
          admitted+[{'artifact':'inputs/denied','path':'inputs/denied','sha256':'b'*64}],attempt=2)
    assert len(store.rows)==1


@pytest.mark.parametrize('path',['../denied','/outside',''])
def test_source_admission_refuses_unbound_input_paths(tmp_path,path):
    with pytest.raises(ValueError):
        native_checks.source_admission(object(),{'id':'s1'},tmp_path,
            [{'artifact':'foreign','path':path,'sha256':'a'*64}],attempt=1)


def test_authority_rows_join_both_effect_checks_to_exact_current_attempt():
    class Store:
        def __init__(self):
            self.rows=[{'id':str(i),'record':{'step_id':'s1','attempt':2,'plan_sha256':'plan',
                'effect':{'id':'s1','pins':{'plan_sha256':'plan'},'started_ns':i},
                'authority':{'approve_plan':'approval'}}} for i in (1,2)]
        def scan(self,kind):
            assert kind=='step-authority';return deepcopy(self.rows)
    store=Store();ctx={'attempt':2,'plan_sha256':'plan'}
    rows=native_checks.authority_rows(store,{'id':'s1'},ctx)
    assert rows['G05']['evidence']['record']=='2'
    assert rows['G05']['evidence']['checks']==['1','2']
    for field,value in [('attempt',1),('plan_sha256','other'),('step_id','other')]:
        changed=deepcopy(store.rows);store.rows[-1]['record'][field]=value
        assert native_checks.authority_rows(store,{'id':'s1'},ctx)=={}
        store.rows=changed
    store.rows.pop()
    assert native_checks.authority_rows(store,{'id':'s1'},ctx)=={}


def test_source_rows_cannot_close_without_actual_confined_input_action():
    import sys
    launch,reserve,probe=subject();probe['tools']=[sys.executable]
    step={'id':'s1'};ctx={'attempt':1}
    source={'record':'source','passed':True,'mechanism':'restriction_guard.require',
            'step_id':'s1','attempt':1,'inputs':[]}
    enforced=native_checks.confinement_rows(launch,reserve,probe)
    rows=native_checks.input_rows(step,ctx,source,launch,probe,enforced)
    assert set(rows)=={'C24','E02'}
    assert rows['C24']['status']=='satisfied' and rows['C24']['evidence']['record']=='source'
    assert rows['E02']['status']=='not_applicable'
    for key,value in [('record',None),('passed',False),('mechanism','foreign'),
                      ('step_id','other'),('attempt',2),('inputs',None)]:
        changed={**source,key:value}
        assert native_checks.input_rows(step,ctx,changed,launch,probe,enforced)=={}
    assert native_checks.input_rows(step,ctx,source,launch,probe,{})=={}
    assert native_checks.input_rows(step,ctx,source,launch,probe,{'T04':{'status':'violated'}})=={}
    probe['tools']=['excluded-provider']
    assert 'E02' not in native_checks.input_rows(step,ctx,source,launch,probe,enforced)


def acquisition_subject():
    launch={'backend':'controller-acquisition','journal_id':'start','finished_id':'finish',
            'exit_status':0,'timed_out':False,'acquisition':{'source_scope_completed':True,
              'source_admission':{'bytes':2,'requests':[{'url':'https://example.test/source',
                'descriptor_sha256':'a'*64,'admission':'restriction_guard.require'}]}}}
    return launch,{'passed':True,'record':'source'}


def test_guarded_source_reader_records_actual_admission_and_typed_child_absence():
    args=acquisition_subject();before=deepcopy(args)
    rows=native_checks.acquisition_rows(*args)
    assert {key for key,row in rows.items() if row['status']=='satisfied'}=={'C24','E16','T05','SW22'}
    assert set(rows)=={'C24','E16','T05','SW22','G10','G14','SW27','SW17','SW34','SW35',
                       'SW36','SW37','SW38','SW24','T04','T09'}
    assert all(row['evidence']['record']=='finish' for row in rows.values())
    assert not(set(rows)&{'G04','SW08','GATE-launch','P05','E07','E08','E10','E13'})
    assert args==before


@pytest.mark.parametrize('fault',['backend','finished','failure','timeout','source','scope','requests','guard','digest','bytes'])
def test_reader_never_credits_incomplete_or_unguarded_acquisition(fault):
    launch,source=acquisition_subject();audit=launch['acquisition']['source_admission']
    if fault=='backend':launch['backend']='native'
    if fault=='finished':launch.pop('finished_id')
    if fault=='failure':launch['exit_status']=1
    if fault=='timeout':launch['timed_out']=True
    if fault=='source':source['passed']=False
    if fault=='scope':launch['acquisition'].pop('source_scope_completed')
    if fault=='requests':audit['requests']=None
    if fault=='guard':audit['requests'][0]['admission']='worker_says_allowed'
    if fault=='digest':audit['requests'][0]['descriptor_sha256']='bad'
    if fault=='bytes':audit['bytes']=-1
    assert native_checks.acquisition_rows(launch,source)=={}


def native_gate_subject():
    from ravel.controller.step import spec
    from ravel.controller.step.services import digest
    step={'id':'derive','kind':'operate','operation':'toy','parameters':{}}
    pins={'plan_sha256':'a'*64,'step_sha256':spec.step_sha256(step),'launch_sha256':'b'*64,
          'attempt':'2','native_preflight':'preflight'}
    action={'step':'derive','node_id':'derive','view_pins':pins,'digest':digest(pins)}
    mapped={'mechanism':'controller.native_launch.mapping','native_preflight':'preflight',
            'action_digest':action['digest'],'view_pins':deepcopy(pins),'approval_context':'approval',
            'approval':{'record':'review'},'scientific_review':{
                'mechanism':'controller.native-review-admission','plan_sha256':'a'*64,'step_id':'derive'}}
    body={'gate':'launch','passed':True,'action':action,'action_sha256':digest(action),'providers':{'rdj':mapped}}
    class Store:
        def scan(self,kind):return [{'id':'decision','record':body}] if kind=='gate-provider-check' else []
    return Store(),step,{'plan_sha256':'a'*64,'attempt':2}, {'native_preflight':'preflight','launch_sha256':'b'*64}, {'journal_id':'start','finished_id':'finish'},body


def test_actual_passed_provider_mapping_closes_stage_review_rows():
    args=native_gate_subject()
    result=native_checks.gate_rows(*args[:5])
    assert set(result)=={'G04','SW08'}
    assert all(row['status']=='satisfied' and row['evidence']['record']=='decision' for row in result.values())
    assert 'GATE-launch' not in result


@pytest.mark.parametrize('change',['passed','gate','action_hash','step','attempt','launch','preflight',
                                  'mapping','approval','review','finish'])
def test_unrelated_or_incomplete_gate_record_never_closes_native_rows(change):
    from ravel.controller.step.services import digest
    store,step,ctx,prepared,launch,body=native_gate_subject()
    if change=='passed':body['passed']=False
    if change=='gate':body['gate']='approve_plan'
    if change=='action_hash':body['action_sha256']='foreign'
    if change=='step':body['action']['step']='other'
    if change=='attempt':body['action']['view_pins']['attempt']='1'
    if change=='launch':prepared['launch_sha256']='c'*64
    if change=='preflight':prepared['native_preflight']='other'
    if change=='mapping':body['providers']['rdj']['mechanism']='other'
    if change=='approval':body['providers']['rdj'].pop('approval')
    if change=='review':body['providers']['rdj']['scientific_review']['step_id']='other'
    if change=='finish':launch.pop('finished_id')
    if change in ('step','attempt'):body['action_sha256']=digest(body['action'])
    assert native_checks.gate_rows(store,step,ctx,prepared,launch)=={}


def worker_inventory_subject():
    step={'id':'inspect','kind':'inspect','parameters':{'phase':'prepare'}}
    record={'status':'ok','attestation':'transport_attested','transport':'qualified-cli',
            'tool_inventory':{'kind':'worker','equal':True,'differences':[], 'mcp_observed':True,
                              'mcp_error':None,'tools':['ws_read','ws_write']}}
    prepared={'qualification_record':'qualification','selection':{'transport_id':'qualified-cli'},
              'toolbelt':{'manifest_sha256':'a'*64,'tools':['ws_read','ws_write']}}
    return step,record,prepared


@pytest.mark.parametrize('kind', ['inspect', *spec.WORKER_KINDS])
def test_preparation_inventory_records_actual_provider_and_tool_filtering(kind):
    subject = worker_inventory_subject()
    subject[0]['kind'] = kind
    rows=native_checks.worker_inventory_rows('observation',*subject)
    assert set(rows)=={'E02'} and rows['E02']['status']=='satisfied'
    assert rows['E02']['evidence']['record']=='observation'
    assert rows['E02']['evidence']['qualification']=='qualification'


@pytest.mark.parametrize('status', ['completed', 'refused', 'failed', 'ambiguous'])
def test_preparation_inventory_requires_actual_success_receipt_status(status):
    step, record, prepared = worker_inventory_subject()
    record['status'] = status
    assert native_checks.worker_inventory_rows('observation', step, record, prepared) == {}


@pytest.mark.parametrize('change',['phase','kind','operation','qualification','provider','observed_tools',
                                  'mcp','mismatch','attestation','status','manifest'])
def test_unverified_preparation_inventory_cannot_lend_exclusion_credit(change):
    step,record,prepared=worker_inventory_subject()
    if change=='phase':step['parameters']['phase']='execute'
    if change=='kind':step['kind']='operate'
    if change=='operation':step['operation']='external-operation'
    if change=='qualification':prepared.pop('qualification_record')
    if change=='provider':record['transport']='excluded-cli'
    if change=='observed_tools':record['tool_inventory']['tools'].append('excluded-probe')
    if change=='mcp':record['tool_inventory']['mcp_observed']=False
    if change=='mismatch':record['tool_inventory']['differences']=['extra']
    if change=='attestation':record['attestation']='unverified'
    if change=='status':record['status']='ambiguous'
    if change=='manifest':prepared['toolbelt'].pop('manifest_sha256')
    assert native_checks.worker_inventory_rows('observation',step,record,prepared)=={}


@pytest.mark.parametrize('kind', ['operate', 'acquire', 'ask', 'route', 'subgraph', None])
def test_preparation_inventory_requires_actual_worker_branch(kind):
    step, record, prepared = worker_inventory_subject()
    if kind is None:
        step.pop('kind')
    else:
        step['kind'] = kind
    if kind == 'acquire':
        step['parameters']['launch'] = {'argv': ['fictional-native']}
    assert native_checks.worker_inventory_rows('observation', step, record, prepared) == {}


def acquisition_quantity_subject(representation='file_bytes'):
    from ravel.controller.step.services import digest
    launch,source=acquisition_subject()
    acquired=launch['acquisition']
    acquired['members']=[{'path':'source/manifest.json','sha256':'a'*64},
                         {'path':'source/tables/values.json','sha256':'b'*64}]
    acquired['quantity_transport']={'kind':'uninterpreted_source_transfer',
        'representation':representation,'members':deepcopy(acquired['members']),
        'inventory_sha256':digest(acquired['members']),'source_fields_transformed':False,
        'source_quantities':['text'] if representation=='metadata' else ['values']}
    acquired['member_inventory']=[{'path':'tables/values.json','sha256':'b'*64,
                                   'bytes':10,'blob':'tables/values.json'}]
    acquired['member_inventory_sha256']=digest(acquired['member_inventory'])
    if representation=='metadata':
        acquired.pop('member_inventory'); acquired.pop('member_inventory_sha256')
    return launch,source


@pytest.mark.parametrize('representation',['metadata','file_bytes'])
def test_guarded_acquisition_quantity_handoff_is_backed_by_completed_inventory(representation):
    rows=native_checks.acquisition_rows(*acquisition_quantity_subject(representation))
    assert rows['P05']['status']==('not_applicable' if representation=='metadata' else 'satisfied')
    assert rows['P05']['evidence']['record']=='finish'
    assert rows['P05']['evidence']['mechanism']=='controller_acquisition.uninterpreted_source_transfer'


@pytest.mark.parametrize('change',['proof','kind','representation','members','digest','transformed',
                                  'member','member_digest','member_path','member_bytes','member_blob','member_sha'])
def test_incomplete_or_changed_source_transfer_never_closes_quantity_handoff(change):
    launch,source=acquisition_quantity_subject()
    acquired=launch['acquisition'];proof=acquired['quantity_transport']
    if change=='proof':acquired.pop('quantity_transport')
    if change=='kind':proof['kind']='quantity-conversion'
    if change=='representation':proof['representation']='numbers'
    if change=='members':proof['members']=[]
    if change=='digest':proof['inventory_sha256']='c'*64
    if change=='transformed':proof['source_fields_transformed']=True
    if change=='member':acquired['member_inventory']=[]
    if change=='member_digest':acquired['member_inventory_sha256']='c'*64
    if change=='member_path':acquired['member_inventory'][0]['path']='../values.json'
    if change=='member_bytes':acquired['member_inventory'][0]['bytes']=-1
    if change=='member_blob':acquired['member_inventory'][0]['blob']='../outside'
    if change=='member_sha':acquired['member_inventory'][0]['sha256']='c'*64
    if change in ('member_path','member_bytes','member_blob','member_sha'):
        from ravel.controller.step.services import digest
        acquired['member_inventory_sha256']=digest(acquired['member_inventory'])
    assert 'P05' not in native_checks.acquisition_rows(launch,source)


def preparation_gate_subject():
    from ravel.controller.routes.analysis.execution import acquisition_implementation
    from ravel.controller.step import spec
    from ravel.controller.step.services import digest
    store, step, ctx, prepared, launch, body = native_gate_subject()
    step.update(kind='acquire', operation='acquire-published', rung='none', budget={'events': 0})
    step['parameters'] = {'phase': 'prepare', 'task': {'max_bytes': 4096},
        'launch': {'argv': ['python', '-m', 'ravel.workflow.resource_census', '--reading', 'input.json']}}
    body['action']['view_pins']['step_sha256'] = spec.step_sha256(step)
    body['action']['digest'] = digest(body['action']['view_pins'])
    body['action_sha256'] = digest(body['action'])
    mapped = body['providers']['rdj']
    mapped.update(mechanism='controller.native_preparation.mapping', preparation_authority='authority',
                  mode_record='mode', preparation_implementation=acquisition_implementation(step),
                  view_pins=deepcopy(body['action']['view_pins']), action_digest=body['action']['digest'])
    mapped.pop('approval_context'); mapped.pop('approval')
    return store, step, ctx, prepared, launch, body


def test_preparation_gate_rows_require_actual_preparation_mapping_without_approval_claim():
    args = preparation_gate_subject()
    rows = native_checks.gate_rows(*args[:5])
    assert set(rows) == {'G04', 'SW08'}
    assert all(row['evidence']['mechanism'] == 'controller.native_preparation.mapping' for row in rows.values())
    assert 'GATE-launch' not in rows


@pytest.mark.parametrize('fault', ['authority', 'mode', 'implementation', 'approval', 'review', 'passed', 'hash'])
def test_preparation_row_mapping_cannot_borrow_incomplete_or_approval_evidence(fault):
    args = preparation_gate_subject(); body = args[-1]; mapped = body['providers']['rdj']
    if fault == 'authority': mapped.pop('preparation_authority')
    if fault == 'mode': mapped.pop('mode_record')
    if fault == 'implementation': mapped['preparation_implementation'] = {}
    if fault == 'approval': mapped['approval_context'] = 'not-a-plan-approval'
    if fault == 'review': mapped['scientific_review'] = {}
    if fault == 'passed': body['passed'] = False
    if fault == 'hash': body['action_sha256'] = 'changed'
    assert native_checks.gate_rows(*args[:5]) == {}
