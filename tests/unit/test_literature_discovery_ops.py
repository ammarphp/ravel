"""Discovery as the bounded selector loop: an explicit, admitted controller operation.

Fictional records only. Routed HTTPS answers pass through the real campaign,
Host, Graph and discovery client; subprocesses are refused and no model is
reached. The registered selector card is dispatched through the real role
dispatcher against synthetic qualified routes in a per-test state directory.
The released blind card selects a qualified sandbox CLI worker, on which the
Host has no one-shot Graph ``model`` node path, so the selector loop is refused
as ``transport_unsupported`` before any page (an open design item). The
deterministic crawl exercises the same loop, ledger, resume, halts, source
policy and receipt without a selector. Synthetic no-tool selector cards also
exercise HTTP selection, pause/resume and charged graph custody without claiming
that the released broker-tool card can use that route.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import synthetic_identifiers as syn

from ravel.controller.step import host_operations, operations
from ravel.validation import signature_conformance
from ravel.workflow import literature_discovery_agent as a, production_executor
from ravel.workflow import research_cycle as cycle, research_tools as tools
from test_literature_context import task
from test_literature_discovery_agent import ROUTES, WITHHELD_TITLE, campaign, routed, scope, write  # noqa: F401
from test_literature_query_ops import SELECTED, dispatch, inert, preferences  # noqa: F401
from test_literature_query_ops import http_dispatch, inert_response  # noqa: F401
from test_literature_discovery_agent import JUDGE


def test_http_selector_pauses_and_resumes_with_charged_graph_custody(monkeypatch, campaign, http_dispatch):
    base, root, host = campaign()
    pages = routed(monkeypatch, ROUTES)
    out, pin = root / 'discovery', write(base / 'scope.json', scope())

    def choose(data, parameters):
        # The generated schema remains the authority for candidate membership.
        schema = parameters['output_schema']['properties']
        candidates = schema['decisions']['items']['properties']['candidate']['enum']
        return {'kind': a.CHOICE_KIND, 'request_sha256': schema['request_sha256']['const'],
                'decisions': [{'candidate': key, 'judgments': deepcopy(JUDGE[key])}
                              for key in candidates if key in JUDGE]}
    calls = inert_response(monkeypatch, host, choose)
    paused = tools.crawl_literature(root, pin, out, host, max_advances=1, **http_dispatch)
    assert paused['status'] == 'paused' and paused['dispatch']['transport_id'] == 'http-responses'
    assert len(pages) == 3 and calls == []
    _, before = cycle._load(root)
    before_charges = len(before['resource_ledger'])
    done = tools.crawl_literature(root, pin, out, host, **http_dispatch)
    assert done['status'] == 'complete' and done['resumed']
    receipt = tools.admit_crawl(root, out, roles=http_dispatch['roles'])
    report = receipt['report']
    assert receipt['record'] == done and report == a.consume(root, out, roles=http_dispatch['roles'])
    assert len(calls) == report['usage']['selection_calls'] == 2
    assert len(pages) == 9 and [page['q'] for page in pages].count('recid:9101') == 1
    assert report['population']['demonstrated'] and report['withheld']['count'] == 1
    assert WITHHELD_TITLE not in json.dumps(report) and syn.arxiv(6) not in json.dumps(report)
    _, after = cycle._load(root)
    assert len(after['resource_ledger']) - before_charges == 8
    assert sum(row['usage']['calls'] for row in after['graphs']) == 11
    charges = len(after['resource_ledger'])
    repeated = tools.crawl_literature(root, pin, out, host, **http_dispatch)
    assert repeated['status'] == 'complete' and len(pages) == 9 and len(calls) == 2
    assert len(cycle._load(root)[1]['resource_ledger']) == charges


def test_the_selector_loop_is_refused_on_the_selected_route_before_any_page(monkeypatch, campaign, dispatch, inert):
    base, root, host = campaign()
    pages = routed(monkeypatch, ROUTES)
    out = root / 'discovery'
    refused = tools.crawl_literature(root, write(base / 'scope.json', scope()), out, host, **dispatch)
    assert refused['status'] == 'refused' and refused['reason'] == 'transport_unsupported'
    assert refused['missing'] == [SELECTED] and pages == [] and not out.exists() and inert == []


@pytest.mark.parametrize('case', ['missing-card', 'weak-tier'])
def test_selector_dispatch_refusals_stay_specific(monkeypatch, campaign, dispatch, inert, case):
    base, root, host = campaign()
    pages = routed(monkeypatch, ROUTES)
    options = dict(dispatch)
    if case == 'missing-card':
        options['roles'] = {'aliases': {}, 'roles': {}}
    else:
        options['preferences'] = preferences(drop_tiers=('cheap',))
    refused = tools.crawl_literature(root, write(base / 'scope.json', scope()), root / 'discovery', host, **options)
    assert refused['reason'] == {'missing-card': 'role_card_unavailable', 'weak-tier': 'model_tier_unavailable'}[case]
    assert refused['status'] == 'refused' and pages == [] and inert == []


def test_an_interrupted_crawl_resumes_without_repeated_charges_and_satisfies_the_receipt(monkeypatch, campaign, inert):
    base, root, host = campaign()
    pages = routed(monkeypatch, ROUTES)
    pin, out = write(base / 'scope.json', scope()), root / 'discovery'
    real = a._append

    def crash(out_dir, steps, head, event):
        if event['type'] == 'request' and not any(s['event']['type'] == 'request' for s in steps):
            raise KeyboardInterrupt('simulated interruption after the first charged request')
        return real(out_dir, steps, head, event)
    monkeypatch.setattr(a, '_append', crash)
    with pytest.raises(KeyboardInterrupt):
        tools.crawl_literature(root, pin, out, host)
    monkeypatch.setattr(a, '_append', real)
    assert len(pages) == 1
    done = tools.crawl_literature(root, pin, out, host)
    assert done['status'] == 'complete' and done['resumed'] and done['dispatch'] is None
    assert [c['q'] for c in pages].count('recid:9101') == 1 and len(pages) == 5
    receipt = tools.admit_crawl(root, out)
    report = receipt['report']
    assert report == a.consume(root, out) and receipt['record'] == done
    assert {tuple(e['reasons']) for e in report['population']['unresolved']} == {('selector_disabled',)}
    assert report['withheld']['count'] == 1 and WITHHELD_TITLE not in json.dumps(report)
    assert syn.arxiv(6) not in json.dumps(report)
    assert tools.crawl_literature(root, pin, out, host)['status'] == 'complete' and len(pages) == 5


def test_budget_exhaustion_halts_with_a_qualified_receipt(monkeypatch, campaign, inert):
    base, root, host = campaign(calls=2)
    pages = routed(monkeypatch, ROUTES)
    out = root / 'discovery'
    done = tools.crawl_literature(root, write(base / 'scope.json', scope()), out, host)
    assert done['status'] == 'halted' and 'ceiling exhausted' in done['reason'] and len(pages) == 2
    report = tools.admit_crawl(root, out)['report']
    assert ('request_failed', 'variant:broad:p2') in {(g['kind'], g.get('key')) for g in report['gaps']}
    assert not report['population']['demonstrated']


def test_denied_seeds_and_queries_are_withheld_and_counted_only(monkeypatch, campaign, inert):
    base, root, host = campaign()
    pages = routed(monkeypatch, ROUTES)
    value = scope(queries=[{'id': 'broad', 'text': 'glimmer resonance'}, {'id': 'named', 'text': 'eprint ' + syn.arxiv(6)}],
                  seeds=['9101', '9106'])
    value['source_restrictions'][0]['identifiers']['inspire'] = ['ins9106']
    done = tools.crawl_literature(root, write(base / 'scope.json', value), root / 'discovery', host)
    assert done['status'] == 'complete' and done['dispatch'] is None
    report = tools.admit_crawl(root, root / 'discovery')['report']
    assert not any('9106' in str(c['q']) or syn.arxiv(6) in str(c['q']) for c in pages)
    assert report['counts']['withheld_seeds'] == 1
    assert ('query_withheld', 'variant:named:p1') in {(g['kind'], g.get('key')) for g in report['gaps']}
    assert '"9106"' not in json.dumps(report) and WITHHELD_TITLE not in json.dumps(report)


def test_a_tampered_ledger_is_refused_as_a_stale_crawl(monkeypatch, campaign, inert):
    base, root, host = campaign()
    routed(monkeypatch, ROUTES)
    pin, out = write(base / 'scope.json', scope()), root / 'discovery'
    assert tools.crawl_literature(root, pin, out, host)['status'] == 'complete'
    step = out / 'ledger' / '0001.json'
    value = json.loads(step.read_text()); value['event']['query'] = 'something else'
    step.write_text(json.dumps(value))
    refused = tools.crawl_literature(root, pin, out, host)
    assert refused['status'] == 'refused' and refused['reason'] == 'stale_crawl'
    with pytest.raises(ValueError):
        tools.admit_crawl(root, out)


def test_the_single_query_call_cannot_satisfy_the_selector_loop_receipt(monkeypatch, campaign, inert):
    base, root, host = campaign()
    pages = routed(monkeypatch, ROUTES)
    _, state = cycle._load(root)
    request = write(base / 'legacy-request.json', {
        'schema_version': 1, 'kind': 'literature-discovery-request', 'id': 'legacy-r0001',
        'cycle_binding': {'root': str(cycle._ordinary(root)), 'contract_sha256': cycle.ce.digest(state['contract'])},
        'provider': 'inspire', 'operation': 'query', 'query': 'glimmer resonance', 'page': 1, 'max_results': 4,
        'discovery': None, 'recid': None, 'bibliography_selection': None, 'max_bytes': 200000, 'max_seconds': 20,
        'tasks': [task()]})
    legacy = tools.discover_literature(root, request, root / 'legacy', host, max_wall_seconds=20)
    assert legacy['product'] and len(pages) == 1
    with pytest.raises(ValueError, match='not a crawl'):
        tools.admit_crawl(root, root / 'legacy')
    advertised = tools.literature_operations()
    assert 'research_tools.discover_literature' not in json.dumps(advertised)
    assert advertised['literature-discovery-crawl']['receipt'] == 'research_tools.admit_crawl'


def test_the_crawl_is_a_registered_host_operation_with_a_closed_launch():
    name = 'literature-discovery-crawl'
    signature, policy = operations.signatures()[name], operations.LITERATURE_OPERATIONS[name]
    assert signature_conformance.entry_errors(name, signature) == []
    assert signature['implementation'] == policy['implementation'] and signature['effects'] == []
    table = production_executor.executors()
    assert name in table['host_operations'] and policy['dispatches'] == a.ROLE
    step = {'id': 'S-1', 'kind': 'operate', 'operation': name, 'role': None,
            'outputs': [{'path': 'outputs/report.json', 'kind': 'document'}],
            'parameters': {'task': {'max_wall_seconds': 900, 'scope_pin': {'path': 'inputs/scope.json'}},
                           'launch': {'argv': [*policy['argv'], '--request', 'inputs/request.json']}}}
    assert operations.admission_errors(step) == [] and operations.literature_launch_errors(step) == []
    assert host_operations.admission_errors(step, table, branch='launch') == []
