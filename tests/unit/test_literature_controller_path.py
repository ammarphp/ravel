"""One fictional corpus through the whole governed literature path.

Admission and pinned build (the trusted lineage driver), settings binding, a
production broker serving one search, the expansion and scoring operations, one
discovery advance and a worker's final citations. Every source, record and
route is fictional; scripted HTTPS answers stand in for the network,
subprocesses are refused and no model is called. The literature cards are
dispatched against synthetic qualified routes: the released blind cards select a
sandbox CLI worker, on which the Host has no one-shot Graph ``model`` node path,
so this standalone campaign retains its ``transport_unsupported`` refusal with
the deterministic expansion and unscored originals. Bound controller success with
the installed cards is exercised in controller/test_literature_seats.py.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ravel.workflow import agent_host, broker as core, knowledge_bundles, literature_corpus as corpus
from ravel.workflow import literature_discovery as discovery
from ravel.workflow import literature_query as q, literature_serving
from ravel.workflow import literature_settings, research_cycle as cycle, research_tools as tools, role_registry
from ravel.workflow import tool_gate, toolbelt
from test_knowledge_bundles import sources  # noqa: F401
from test_literature_corpus import Clock, connected
from test_literature_discovery_agent import ROUTES, routed as routed_inspire, scope
from test_literature_query import QUERY, vocabulary
from test_literature_query_ops import SELECTED, campaign, preferences, qualified_routes
from test_literature_serving import Embedder, args, lineage_provider, lineage_settings, make_run
from test_research_cycle import write

SCOUT = 'literature-scout'


@pytest.fixture
def inert(monkeypatch, tmp_path):
    def refuse(*a, **k):
        raise AssertionError('no process, provider or model dispatch on the governed literature path')
    monkeypatch.setattr(subprocess, 'Popen', refuse)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path.resolve() / 'state'))
    calls = []

    def respond(self, data, parameters, request, control):
        calls.append(parameters['model'])
        raise AssertionError('no model call is admissible for the released literature cards')
    monkeypatch.setattr(agent_host.AgentHost, '_responses', respond)
    return calls


def scout_tools():
    card = deepcopy(role_registry.load(SCOUT))
    card['knowledge']['literature_operations'] = list(literature_serving.TOOL_NAMES)
    if literature_serving.ACTION not in card['tools']['ravel_actions']:
        card['tools']['ravel_actions'].append(literature_serving.ACTION)
    return toolbelt.build(card, max_tools=64)['tools']


def test_one_fictional_corpus_through_the_governed_controller_path(tmp_path, monkeypatch, inert, sources):
    # Admission and the pinned build, with the evaluation-style exclusion root declared by installation settings.
    base, root, host, plan_pin, exclusion_pin, _ = connected(tmp_path, monkeypatch)
    corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                   sleep=Clock().sleep, clock=Clock())
    record_pin = cycle._pin(root / 'corpus' / 'record.json')
    receipts = {hashlib.sha256(p.read_bytes()).hexdigest(): 'receipt-' + p.name for p in base.rglob('*') if p.is_file()}
    # Until the settings key is installed, the closed schema is widened only inside this test.
    monkeypatch.setattr(literature_settings, 'SETTINGS_KEYS', literature_settings.SETTINGS_KEYS | {'excluded_roots'})
    held = base / 'held-out'
    held.mkdir()
    build = dict(embedder=Embedder(), reranker_identity={'name': 'fictional-cross-encoder', 'revision': '1'},
                 receipt_ids=receipts, provider_factory=lineage_provider)
    with pytest.raises(ValueError, match='excluded root'):
        corpus.build_from_records([record_pin], exclusion_pin, **build,
                                  settings=lineage_settings(base, excluded_roots=[str(root / 'corpus')]))
    assert not (base / 'qualification.json').exists()
    settings = lineage_settings(base, excluded_roots=[str(held)])
    built = corpus.build_from_records([record_pin], exclusion_pin, settings=settings, **build)
    assert built['record']['excluded_roots'] == [str(held.resolve())]
    assert built['record']['census']['acquisition']['planned'] == 4

    # The installation settings document binds the serving configuration; no worker selects it.
    monkeypatch.setenv(literature_settings.SETTINGS_ENV, str(settings))
    monkeypatch.setattr(literature_settings, '_local_provider',
                        lambda snapshot, *, cursor_key, models_root: lineage_provider(snapshot, cursor_key=cursor_key))
    configuration = literature_settings.from_settings()
    assert isinstance(configuration, literature_serving.Serving)
    assert configuration.index['manifest_sha256'] == built['snapshot']['manifest']['manifest_sha256']

    # A production broker serves one search with authenticated bytes.
    run = make_run(base / 'worker-run')
    workspace = core.work_root(run) / 'worker' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True)
    broker = tool_gate.production_broker(run, workspace, tools=scout_tools(), role=SCOUT, node_id='worker',
                                         attempt=1, max_calls=40, retrieval=configuration)
    reply = literature_serving.call(broker, 'search', args('search', query='fictional located method'))
    assert reply['status'] == 'ok', reply
    raw = literature_serving.load(run, reply)
    assert hashlib.sha256(raw).hexdigest() == reply['outputs'][0]['sha256']
    envelope = json.loads(raw)
    assert envelope['results'] and envelope['provider_id'] == 'local-hybrid'
    serving_id = json.loads(reply['stdout_tail'])['serving_id']

    # Expansion and scoring operations, dispatched through the role dispatcher under a research campaign.
    (base / 'operations').mkdir()
    root = campaign(base / 'operations')
    routes = dict(preferences=preferences(), executables=qualified_routes())
    expanded = tools.expand_literature_query(root, QUERY, root / 'expand', agent_host.AgentHost(),
                                             vocabulary=vocabulary(base), **routes)
    assert expanded['reason'] == 'transport_unsupported' and expanded['missing'] == [SELECTED]
    assert expanded['expansion'] == q.expand(QUERY, vocabulary=vocabulary(base / 'operations'))
    scored = tools.score_literature_evidence(root, run, serving_id, 'Which method is located?', root / 'score',
                                             agent_host.AgentHost(), node_id='worker', attempt=1, **routes)
    assert scored['reason'] == 'transport_unsupported' and scored['missing'] == [SELECTED]
    record = json.loads(Path(scored['scoring']['path']).read_text())
    assert [e['original'] for e in record['evidence']] == envelope['results']
    assert all(e['assessment']['relevance_score'] is None for e in record['evidence'])

    # One deterministic discovery advance with inert search pages.
    pages = routed_inspire(monkeypatch, ROUTES)
    discovering = agent_host.AgentHost(timeout_seconds=30, literature_origins=[discovery.ORIGIN])
    crawl = tools.crawl_literature(root, write(base / 'scope.json', scope()), root / 'discovery', discovering,
                                   max_advances=1)
    assert crawl['status'] == 'complete' and crawl['advances'] == 1 and len(pages) == 5
    assert tools.admit_crawl(root, root / 'discovery')['record'] == crawl

    # The worker's final record cites only evidence served to its attempt.
    card, facts, binding = deepcopy(sources)
    card.update(id=SCOUT, tools={'ravel_actions': [literature_serving.ACTION]}, requires={'tools': 'broker-readonly'})
    card['knowledge'].update(literature_operations=['search'], budget_tokens=100000)
    facts['node_id'] = broker.node_id
    binding.update(workspace=broker.workspace, literature_broker=broker,
                   literature_requests=[{'op': 'search', 'args': args('search', query='fictional located method')}])
    index = knowledge_bundles.materialize(card, facts, binding)
    served = index['literature']['served_ids']
    assert served and set(served) <= {row['id'] for row in envelope['results']}
    assert knowledge_bundles.validate_cited_ids({'knowledge_used': [], 'literature_used': served[:1]}, index,
                                                atlas_path=binding['atlas_path'], literature_broker=broker) == []
    with pytest.raises(ValueError):
        knowledge_bundles.validate_cited_ids({'knowledge_used': [], 'literature_used': ['unit:never-served']}, index,
                                             atlas_path=binding['atlas_path'], literature_broker=broker)
    assert inert == []
