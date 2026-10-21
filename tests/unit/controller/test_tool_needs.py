"""Controller wiring of capability needs: the profile at intake, the planner's view and check, fixed-route open
obligations, the step preflight re-check and the offline acquisition forms.

Every tool availability is injected; nothing probes this host's network or tools, and no native process starts.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.controller import graph
from ravel.controller.confine import profile as confine_profile
from ravel.controller.judgment import planning
from ravel.controller.routes import CompileError, plan_sha256
from ravel.controller.routes.analysis import execution
from ravel.controller.step import graph as step_graph
from ravel.controller.step.services import StepHold
from ravel.setup import environment_profile as ep
from ravel.workflow import acquisition_http, resource_census, restriction_guard, tool_selection

AGENTRIVET = 'census-agentrivet-e4d12ecc'
SFITTER = 'census-sfitteragents-sfitter-6072a79e-pytorch-2-14-0'


class Store:
    """The store surface the wiring reads: append, read, scan, latest, blobs."""

    def __init__(self, root=None):
        self.rows, self.blobs, self.run_id, self.store_root = [], {}, 'fictional-run', root

    def append(self, kind, record):
        identifier = f'{kind}-{len(self.rows) + 1:06d}-fictional'
        self.rows.append({'id': identifier, 'kind': kind, 'record': json.loads(json.dumps(record))})
        return identifier

    def read(self, kind, identifier):
        return next(r for r in self.rows if r['kind'] == kind and r['id'] == identifier)

    def scan(self, kind):
        return [deepcopy(r) for r in self.rows if r['kind'] == kind]

    def latest(self, kind):
        found = self.scan(kind)
        return found[-1] if found else None

    def put_blob(self, raw):
        import hashlib
        digest = hashlib.sha256(raw).hexdigest()
        self.blobs[digest] = raw
        return digest

    def get_blob(self, digest):
        return self.blobs[digest]


def profile(*, available=(), missing=(), egress='unknown', mirror=None):
    rows = {cid: {'readiness': 'ready', 'status': 'qualified', 'version': '1', 'licence': 'not_applicable',
                  'platform_qualification': ''} for cid in available}
    rows.update({cid: {'readiness': 'missing', 'status': 'not_installed', 'version': None,
                       'licence': 'not_applicable', 'platform_qualification': ''} for cid in missing})
    return {'schema': ep.SCHEMA, 'network': {'egress': egress, 'source': 'site-profile', 'checks': []},
            'tools': {'observed': True, 'source': 'doctor-census', 'prefix': None, 'reason': None, 'rows': rows},
            'sources': {'mirror': mirror}, 'site_profile': None, 'probe_errors': []}


def run_with(store, *, task_mode='no_routine', text='Construct the analysis.', facts=()):
    request = store.put_blob(text.encode())
    reading = {'facts': list(facts), 'constraints': [], 'deliverables': [{'id': 'D1'}]}
    intake = store.append('intake', {'contract_blob': store.put_blob(json.dumps({}).encode()),
                                     'reading_blob': store.put_blob(json.dumps(reading).encode()),
                                     'label': {'task_mode': task_mode}})
    return {'run': {'run_id': store.run_id}, 'request': {'sha256': request, 'intake_record_id': intake}}


def step(step_id, **fields):
    return {'id': step_id, 'kind': 'author', 'inputs': [], 'outputs': [], 'depends_on': [], 'parameters': {},
            **fields}


def plan_of(*steps, **extra):
    plan = {'schema_version': 1, 'kind': 'controller-plan', 'route': {'id': 'analysis'}, 'steps': list(steps),
            'deliverables': [], 'waypoints': [], 'open_obligations': [], **extra}
    plan['sha256'] = plan_sha256(plan)
    return plan


# ---- the profile at intake ----------------------------------------------------------------------

def test_the_profile_is_observed_once_and_never_probes_the_network_in_a_test_domain(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(ep.PROBES, 'network', lambda **_: calls.append('network') or {'egress': 'available'})
    monkeypatch.setitem(ep.PROBES, 'tools', lambda **_: {'observed': False, 'reason': 'fictional', 'rows': {}})
    monkeypatch.setitem(ep.PROBES, 'sandbox', lambda: {'backend': None, 'backends': {}})
    store = Store(tmp_path)
    first = confine_profile.observe(store, run_dir=str(tmp_path / 'run'))
    again = confine_profile.observe(store, run_dir=str(tmp_path / 'run'))
    assert first['id'] == again['id'] and len(store.scan('environment-profile')) == 1
    assert calls == [] and first['record']['network']['source'] == 'not-probed'


def test_a_saved_offline_site_profile_reaches_the_run_profile(tmp_path, monkeypatch):
    monkeypatch.setitem(ep.PROBES, 'tools', lambda **_: {'observed': False, 'reason': 'fictional', 'rows': {}})
    monkeypatch.setitem(ep.PROBES, 'sandbox', lambda: {'backend': None, 'backends': {}})
    path = tmp_path / 'home' / 'site' / 'profile.json'
    monkeypatch.setattr(ep, 'site_profile_path', lambda: path)
    settings = {'scheduler': 'htcondor', 'requires_proxy': False, 'requires_kerberos': False, 'requires_afs': False,
                'cvmfs': []}
    pin = ep.save_site_profile(ep.site_profile_document(name='fictional-site', seed='generic', settings=settings,
                                                        network_policy='offline', mirror=str(tmp_path / 'mirror')))
    found = confine_profile.observe(Store(tmp_path), run_dir=str(tmp_path / 'run'))['record']
    assert found['network'] == {'egress': 'none', 'source': 'site-profile', 'checks': []}
    assert found['batch']['system'] == 'htcondor' and found['sources']['mirror'] == str(tmp_path / 'mirror')
    assert found['site_profile'] == pin


def test_an_unreadable_site_profile_is_a_recorded_probe_error(tmp_path, monkeypatch):
    monkeypatch.setitem(ep.PROBES, 'tools', lambda **_: {'observed': False, 'reason': 'fictional', 'rows': {}})
    monkeypatch.setitem(ep.PROBES, 'sandbox', lambda: {'backend': None, 'backends': {}})
    path = tmp_path / 'site' / 'profile.json'
    path.parent.mkdir()
    path.write_text('{"schema": "other"}')
    monkeypatch.setattr(ep, 'site_profile_path', lambda: path)
    found = confine_profile.observe(Store(tmp_path), run_dir=str(tmp_path))['record']
    assert any(row['probe'] == 'site_profile' for row in found['probe_errors']) and found['site_profile'] is None


# ---- the planner's view and check ---------------------------------------------------------------

def test_the_judgment_check_feeds_capability_problems_back_to_the_planner():
    tools = {'profile': profile(available=[AGENTRIVET]), 'supplied': [], 'label': {'task_mode': 'no_routine'},
             'reading': {}, 'request_text': 'x'}
    plan = {'steps': [{'id': 'impl', 'kind': 'operate', 'operation': 'authored-analysis'}]}
    record, problems = tool_selection.check(plan, **tools)
    assert problems and 'AgentRivet' in problems[0]
    view = tool_selection.planning_view(**tools)
    row = next(r for r in view['needs'] if r['need'] == 'routine-construction')
    assert row['arises'] and row['best'] == AGENTRIVET


def test_judgment_steps_carry_their_needs_and_reasons_into_the_controller_plan():
    reason = {'code': 'not_applicable', 'statement': 'two measurements; their combination is requested',
              'evidence': ['step:why']}
    row = {'id': 'fit', 'kind': 'operate', 'purpose': 'fit', 'inputs': [], 'outputs': [], 'depends_on': [],
           'protocols': [], 'review': [], 'obligations': [], 'class': 'R0', 'budget_share': {'fraction': 0.1},
           'operation': 'measurement', 'needs': ['global-fit'], 'tool_reasons': {'global-fit': reason}}
    found = planning.controller_step(row, inputs={}, deliverables=[])
    assert found['parameters']['needs'] == ['global-fit'] and found['parameters']['tool_reasons']['global-fit'] == reason
    bare = planning.controller_step({**row, 'needs': [], 'tool_reasons': {}}, inputs={}, deliverables=[])
    assert 'needs' not in bare['parameters'] and 'tool_reasons' not in bare['parameters']


# ---- fixed routes: an unserved need becomes an open obligation --------------------------------

def test_a_fixed_route_leaves_an_unserved_need_to_the_judgment_graph(tmp_path):
    store = Store(tmp_path)
    state = run_with(store, task_mode='reproduce', text='Perform a global fit of the couplings.')
    store.append('environment-profile', profile(available=[SFITTER]))
    plan = plan_of(step('synthesize', kind='synthesize'))
    found = graph.need_obligations(state, store, plan)
    obligation, = [o for o in found['open_obligations'] if o['kind'] == 'capability_need']
    assert obligation['id'] == 'need:global-fit' and obligation['best'] == SFITTER
    assert found['sha256'] == plan_sha256(found) != plan['sha256']
    assert graph.need_obligations(run_with(store, task_mode='reproduce', text='Reproduce the limit.'), store,
                                  plan) is plan


def test_a_route_naming_an_unknown_need_is_a_compile_error(tmp_path):
    store = Store(tmp_path)
    state = run_with(store, task_mode='reproduce')
    with pytest.raises(CompileError, match='capability needs'):
        graph.need_obligations(state, store, plan_of(step('x', parameters={'needs': ['no-such-need']})))


# ---- offline acquisition ------------------------------------------------------------------------

def census_step():
    return {'id': 'inputs.census', 'kind': 'acquire', 'operation': 'acquire-published',
            'parameters': {'task': {'max_bytes': 100000}, 'launch': {
                'argv': ['python', '-m', 'ravel.workflow.resource_census', '--reading', 'reading.json',
                         '--controller-output', 'census.json']}},
            'outputs': [{'path': 'outputs/census.json'}], 'inputs': []}


def data_step():
    return {'id': 'acquire.data', 'kind': 'acquire', 'operation': 'acquire-published',
            'parameters': {'task': {'max_bytes': 100000}, 'launch': {
                'argv': ['python', '-m', 'ravel.workflow.resource_census', '--fetch-published-data', '--inspire',
                         'ins1001', '--out', 'hepdata', '--download-likelihood', '--tables']}},
            'outputs': [{'path': 'outputs/hepdata/hepdata_manifest.json'}], 'inputs': []}


def test_an_offline_profile_switches_route_acquisitions_to_local_sources(tmp_path):
    store = Store(tmp_path)
    store.append('environment-profile', profile(egress='none', mirror='/fictional/mirror'))
    plan = plan_of(census_step(), data_step())
    found = graph.offline_sources(store, plan)
    census, data = found['steps']
    assert census['parameters']['launch']['argv'][-3:] == ['--offline', '--mirror', '/fictional/mirror']
    assert data['parameters']['launch']['argv'][-3:] == ['--offline', '--offline-mirror', '/fictional/mirror']
    assert census['parameters']['source_mode']['mode'] == 'local'
    assert census['parameters']['source_mode']['profile_record'].startswith('environment-profile-')
    assert found['sha256'] == plan_sha256(found)
    online = Store(tmp_path)
    online.append('environment-profile', profile(egress='available'))
    assert graph.offline_sources(online, plan) is plan


@pytest.fixture
def acquired(tmp_path, monkeypatch):
    monkeypatch.setattr(restriction_guard, 'require', lambda *a, **k: None)

    @contextmanager
    def scope(*args):
        yield {}
    monkeypatch.setattr(acquisition_http, 'scope', scope)
    seen = []

    def fetch(args):
        seen.append(list(args))
        if '--fetch-published-data' in args:
            folder = Path(args[4])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'hepdata_manifest.json').write_text(json.dumps({'table_files': []}))
        else:
            Path(args[3]).write_bytes(b'{"records": []}')
        return 0
    monkeypatch.setattr(resource_census, 'main', fetch)

    def run(step, environment_profile):
        execution.acquire(step, {'run_dir': str(tmp_path), 'environment_profile': environment_profile},
                          output_root=tmp_path / 'outputs', inputs=[])
        return seen[-1]
    return run


def test_the_local_acquisition_forms_are_admitted_only_under_an_offline_profile(acquired):
    store = Store()
    store.append('environment-profile', profile(egress='none', mirror='/fictional/mirror'))
    offline = graph.offline_sources(store, plan_of(census_step(), data_step()))
    census, data = offline['steps']
    assert acquired(census, profile(egress='none', mirror='/fictional/mirror'))[-3:] == [
        '--offline', '--mirror', '/fictional/mirror']
    assert acquired(data, profile(egress='none', mirror='/fictional/mirror'))[-2:] == [
        '--offline-mirror', '/fictional/mirror']
    for local, environment in ((census, profile(egress='available')), (data, None),
                               (census, profile(egress='none', mirror='/other/mirror'))):
        with pytest.raises(ValueError, match='differs from the approved action'):
            acquired(local, environment)
    with pytest.raises(ValueError, match='differs from the approved action'):
        acquired(census_step(), profile(egress='none'))
    # The ordinary online forms stay admitted for every other profile.
    assert acquired(census_step(), profile(egress='available'))[0] == '--reading'
    assert acquired(data_step(), None)[0] == '--fetch-published-data'


# ---- the step preflight re-check ----------------------------------------------------------------

def selection_for(store, plan, prof):
    record, problems = tool_selection.check(plan, profile=prof, label={'task_mode': 'no_routine'})
    assert problems == []
    return store.append('tool-selection', record)


def test_a_tool_lost_since_approval_holds_the_step_with_its_alternatives(monkeypatch):
    store = Store()
    plan = plan_of(step('construct', role='routine-constructor'))
    store.append('environment-profile', profile(available=[AGENTRIVET]))
    record_id = selection_for(store, plan, profile(available=[AGENTRIVET]))
    monkeypatch.setitem(ep.PROBES, 'tools', lambda **kw: profile(missing=kw['only'])['tools'])
    with pytest.raises(StepHold) as held:
        step_graph.tool_check(store, 'construct', plan['sha256'])
    assert held.value.reason == 'tool_unavailable'
    lost, = held.value.evidence['lost']
    assert lost['candidate'] == AGENTRIVET and lost['reason'] == 'not_installed'
    assert [a['id'] for a in lost['alternatives']] == ['hand-written-analysis']
    assert held.value.evidence['selection'] == record_id


def test_a_tool_still_present_or_unobservable_lets_the_step_run(monkeypatch):
    store = Store()
    plan = plan_of(step('construct', role='routine-constructor'))
    record_id = selection_for(store, plan, profile(available=[AGENTRIVET]))
    monkeypatch.setitem(ep.PROBES, 'tools', lambda **kw: profile(available=kw['only'])['tools'])
    assert step_graph.tool_check(store, 'construct', plan['sha256']) == record_id
    monkeypatch.setitem(ep.PROBES, 'tools', lambda **kw: {'observed': False, 'reason': 'no manifest', 'rows': {}})
    assert step_graph.tool_check(store, 'construct', plan['sha256']) == record_id
    assert step_graph.tool_check(store, 'construct', 'f' * 64) is None
    assert step_graph.tool_check(store, 'other-step', plan['sha256']) == record_id
