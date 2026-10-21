"""Fictional artifacts through the installed public sink and real controller store.

The inert producer receives only its output directory and bytes. Journal/custody
records are fixture observations, never confinement or independence certificates.
All sink decisions, ledger transitions, notices and publication bytes are real.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from nc_controller import controller_run
from nc_cases import require_controller


def payload(kind, **changes):
    p = dict(kind=kind, refused=False, producer_journal=True,
             review_history=['unchanged-subject-sha'], max_rounds=2, tokens=42,
             prose=[1.25], source=[1.25], statistic='delta chi2', pinned_statistic='delta chi2',
             panels=['left', 'right'], required_panels=['left', 'right'],
             seats={'tier_a': True, 'tier_b': True}, ledger_status='completed',
             files={'result.json': '1.25'}, worker_files=['result.json'], lineage=['accepted'],
             certificate_run='current', certification={'status': 'uncertified', 'fidelity': 'proxy',
             'explanation': 'No detector certificate', 'certifiable_route': 'native detector validation',
             'flag': 'uncertified'}, defaults=['conservative'], presented_defaults=['conservative'],
             declared=['result.json'], offered=['result.json'], tier='central', certified=False,
             detector_mode='proxy', exclusion_of_record=False, at_poi_cap=False, resolved=False,
             rendered=[1.25], defects=[], verdict='FAIL', presented_verdict='FAIL',
             runtime={'numpy': None}, exported_runtime={'numpy': None},
             claim='All requested work is complete')
    p.update(changes)
    return p


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def assert_svg_presentation(raw, source, receipt):
    original, delivered = ET.fromstring(source), ET.fromstring(raw)
    ns = '{http://www.w3.org/2000/svg}'
    viewports = delivered.findall(ns + 'svg')
    assert len(viewports) == 1
    viewport = viewports[0]
    assert len(list(delivered.iter(ns + 'svg'))) == 2
    assert [ET.tostring(child) for child in viewport] == [ET.tostring(child) for child in original]
    assert float(viewport.get('width')) == float(original.get('width')) == 240
    assert float(viewport.get('height')) == float(original.get('height')) == 120
    assert list(map(float, viewport.get('viewBox').split())) == [0, 0, 240, 120]
    groups = delivered.findall(ns + "g[@id='ravel-provenance']")
    assert len(groups) == 1
    visible = ''.join(groups[0].itertext())
    assert receipt['label'].upper() in visible
    assert receipt['delivery']['receipt_reference'] in ''.join(visible.split())


@dataclass
class Observation:
    kind: str
    receipt: dict
    rows: list
    published: dict
    raw: dict
    directory: object
    observer: dict


def observed_review(store, root, plan, seats, verdict="pass"):
    """Record inert dispatcher observations; credit comes from the real consumer.

    No transport certificate, resolver override, or asserted independent verdict is
    installed. The existing controller observation API is the trusted fixture seam.
    """
    from ravel.workflow import review_dispatch, review_independence
    from test_nc_review_credit import _session, _review, _query, REVIEWER, PRODUCER
    review_dispatch.record_session(store, _session('session-producer', PRODUCER, 'producer', 'actor-producer'))
    results = {}
    for seat, permitted in seats.items():
        session = 'session-' + seat
        review_dispatch.record_session(store, _session(session, REVIEWER, 'reviewer', 'actor-' + seat))
        receipt = {'role': {'id': REVIEWER}, 'model': {'family': 'claude'},
                   'final_record': {'sha256': sha(seat.encode())}}
        receipt_sha = sha(json.dumps(receipt).encode())
        query = dict(_query(root, plan['sha256']), receipt_sha256=receipt_sha,
                     output_sha256=receipt['final_record']['sha256'])
        review_dispatch.record_review(store, _review(query, session if permitted else 'session-producer'))
        decision = review_independence.decide(query)
        credit = {'credited': decision['independent'], 'decision': decision,
                  'family_relation': decision.get('family_relation')}
        assert credit['credited'] is permitted, credit
        store.append('step-credit', {'schema_version': 1, 'step_id': 'final_review',
                     'attempt': 1, 'seats': [], 'own': dict(credit, verdict=verdict)})
        results[seat] = dict(credit, verdict=verdict)
    store.append('review', {'purpose': 'final', 'plan_sha256': plan['sha256'], 'seats': results})


class SinkHarness:
    def __init__(self, env):
        self.env = env
        self.serial = 0

    def run(self, p):
        self.serial += 1
        store, root = controller_run(self.env, f'sink-{p["kind"].replace("_", "-")}-{self.serial}')
        ledger = require_controller('ledger')
        sink = require_controller('sink')
        kind = p['kind']
        docs = {'result.json': json.dumps({'kind': 'calculation', 'value': 1.25,
                                         'statistic': p['statistic']}).encode()}
        if kind in ('prose', 'render'):
            text = (f'value {p["prose"][0]}\n' if kind == 'prose' else
                    f'| result |\n| --- |\n| {p["rendered"][0]} |\n')
            docs['report.md'] = text.encode()
        if kind == 'panels':
            docs['result.svg'] = b'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="120"><text>fictional</text></svg>'
            docs['result.panels.json'] = json.dumps({'panels': p['panels']}).encode()
        doc = json.loads(docs['result.json'])
        if kind == 'certificate': doc['certification'] = p['certification']
        if kind == 'certificate_origin': doc.update(kind='certificate', rundir=str(root if p['certificate_run'] == 'current' else root.parent / 'other'))
        if kind == 'tail': doc.update(tier=p['tier'], certified=p['certified'])
        if kind == 'fidelity': doc.update(fidelity=p['detector_mode'], exclusion_of_record=p['exclusion_of_record'])
        if kind == 'crossing': doc.update(at_poi_cap=p['at_poi_cap'], resolved=p['resolved'])
        if kind == 'defect': doc.update(findings=p['defects'])
        if kind == 'verdict': doc.update(verdict=p['presented_verdict'], findings=[])
        if kind == 'environment': doc.update(runtime=p['runtime'], exported_runtime=p['exported_runtime'])
        if kind == 'completion': doc.update(claim=p['claim'])
        if kind == 'defaults': doc.update(presented_defaults=p['presented_defaults'])
        docs['result.json'] = json.dumps(doc).encode()
        if kind == 'inventory':
            docs = {name: text.encode() for name, text in p['files'].items()}
        reading = {'deliverables': [{'id': 'd-' + name, 'claim_kind': 'calculation'} for name in docs],
                   'constraints': [{'type': 'prescribed_statistic', 'value': {'statistic': p['pinned_statistic']}}]}
        prompt = b'Calculate a fictional value and report the requested artifacts.'
        request = store.put_blob(prompt)
        store.append('request', {'sha256': request, 'channel': 'terminal', 'bytes': len(prompt), 'unattended': False})
        store.append('intake', {'request_sha256': request, 'channel': 'terminal',
                     'contract_blob': store.put_blob(json.dumps({'task_mode': 'calculation', 'prompt': prompt.decode()}).encode()),
                     'reading_blob': store.put_blob(json.dumps(reading).encode())})
        ledger.materialise(store, 'intake', {'run_id': store.run_id, 'task_mode': 'calculation',
                           'route': 'judgment', 'deliverables': [d['id'] for d in reading['deliverables']]})
        step = {'id': 's', 'kind': 'operate', 'inputs': [], 'depends_on': [],
                'outputs': [{'path': n, 'kind': 'artifact', 'required': True} for n in docs],
                'parameters': {'panels': p['required_panels']} if kind == 'panels' else {},
                'waypoint': False, 'rung': None, 'budget': {}, 'protocols': [], 'review': [],
                'instruction_sources': ['docs/workflow/steps/' + n + '.md' for n in
                    ('03-generate', '04-analyze', '05-visualize', '07-exclude', '09-verify')],
                'obligations': [], 'deliverables': [d['id'] for d in reading['deliverables']]}
        plan = {'schema_version': 1, 'kind': 'controller-plan', 'revision': 0,
                'route': {'id': 'judgment', 'version': 1, 'spec_sha256': None}, 'parameters': {},
                'steps': [step], 'deliverables': [{'id': 'd-' + n, 'status': 'mapped', 'step': 's',
                'output': n, 'claim_kind': 'calculation' if n.endswith('.json') else None} for n in docs],
                'waypoints': [], 'checkins': [], 'obligations': [], 'open_obligations': [], 'instruction_sources': []}
        plan['sha256'] = sha(json.dumps(plan, sort_keys=True).encode())
        store.append('plan', {'plan_sha256': plan['sha256'], 'blob': store.put_blob(json.dumps(plan, sort_keys=True).encode()),
                             'source': 'compile', 'revision': 0, 'route': 'judgment'})
        ledger.materialise(store, 'plan', {'plan': plan, 'route': 'judgment', 'task_mode': 'calculation'})
        output = root / 'steps' / 's'
        output.mkdir(parents=True)
        # Counters stay in the trusted parent, unavailable to the byte-only producer.
        observer = {'starts': 0, 'exits': [], 'published': 0}
        started = store.append('step-launch', {'schema_version': 1, 'phase': 'started', 'step_id': 's',
                                               'attempt': 1, 'launch_sha256': sha(json.dumps(sorted(docs)).encode())})
        script = ('import json,pathlib,sys; root=pathlib.Path(sys.argv[1]); '
                  '[(root/n).write_bytes(bytes.fromhex(raw)) for n,raw in json.loads(sys.argv[2]).items()]')
        emitted = ({p['offered'][0]: b'{}'} if kind == 'population'
                   and p['offered'] != p['declared'] else docs)
        observer['starts'] += 1
        proc = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(output),
                               json.dumps({n: b.hex() for n, b in emitted.items()})], capture_output=True, timeout=30)
        observer['exits'].append(proc.returncode)
        assert proc.returncode == 0, proc.stderr
        # Explicitly unqualified: this process does not attest a confinement probe.
        if p['producer_journal']:
            store.append('step-launch', {'schema_version': 1, 'phase': 'finished', 'started': started,
                         'step_id': 's', 'attempt': 1, 'exit_status': proc.returncode,
                         'backend': sys.platform, 'confinement': {'errors': []}, 'plan': {'backend': sys.platform}})
        for name, raw in docs.items():
            record = {'schema_version': 1, 'artifact': f's:{name}', 'step_id': 's', 'attempt': 1,
                      'path': name, 'destination': f'steps/s/{name}', 'sha256': sha(raw), 'kind': 'artifact',
                      'producer': {'kind': 'launch', 'journal_id': started, 'exit_status': proc.returncode},
                      'inputs': [], 'status': 'staged'}
            if name == 'result.svg':
                record['inputs'] = ['s:result.json']
            if kind == 'lineage' and 'diagnostic' in p['lineage']:
                record['inputs'] = ['old:diagnostic.json']
            store.append('custody', record)
            store.append('custody', {**record, 'status': 'accepted'})
        if kind == 'lineage' and 'diagnostic' in p['lineage']:
            prior = root / 'steps' / 'old' / 'diagnostic.json'
            prior.parent.mkdir()
            prior.write_bytes(b'{"delivery_label":"diagnostic"}')
            store.append('custody', {'artifact': 'old:diagnostic.json', 'step_id': 'old', 'attempt': 1,
                         'destination': 'steps/old/diagnostic.json', 'sha256': sha(prior.read_bytes()),
                         'status': 'diagnostic', 'inputs': []})
        store.append('step-outcome', {'schema_version': 1, 'step_id': 's', 'attempt': 1, 'status': p['ledger_status']})
        if p['refused']:
            store.append('step-refusal', {'step_id': 's', 'attempt': 1, 'reason': 'inert producer refused'})
        if kind == 'inventory':
            store.append('step-observation', {'step_id': 's', 'attempt': 1, 'status': 'ok',
                         'tool_inventory': ['python'], 'files': p['worker_files']})
        if kind == 'defaults':
            for chosen in p['defaults']:
                store.append('judgment-record', {'chosen': chosen, 'default_option': chosen,
                             'options': [], 'reason': 'conservative fictional default'})
        if kind == 'usage':
            store.append('budget-reservation', {'key': 'inert', 'amounts': {'tokens': p['tokens']}})
            store.append('budget-settlement', {'key': 'inert', 'status': 'settled',
                         'measured': {'tokens': p['tokens']}, 'charged': {'tokens': p['tokens']}})
        if kind == 'rounds':
            for i, subject in enumerate(p['review_history']):
                store.append('review', {'purpose': 'final', 'plan_sha256': plan['sha256'],
                             'round': i + 1, 'subject_sha256': subject, 'seats': {}})
        observed_review(store, root, plan, p['seats'] if kind == 'review' else {'tier_a': True, 'tier_b': True},
                        p['verdict'] if kind == 'verdict' else 'pass')
        receipt = (sink.bounded_end(store, 'review_rounds_exhausted') if kind == 'rounds'
                   and len(p['review_history']) >= p['max_rounds'] else sink.deliver(store, plan))
        assert receipt.get('id') and 'error' not in receipt, receipt
        folded = require_controller('ledger.state').load(store, full=True)
        rows = [folded.instances[key] for key in folded.current_keys()]
        directory = root / 'delivery'
        assert directory.is_dir()
        disk = json.loads((directory / 'RECEIPT.json').read_bytes())
        assert disk['sha256'] == receipt['sha256']
        published = {row['artifact']: (directory / row['path']).read_bytes()
                     for row in receipt['delivery']['artifacts']}
        for row in receipt['delivery']['artifacts']:
            assert sha(published[row['artifact']]) == row['sha256']
        observer['published'] = len(published)
        assert not receipt['architecture_complete'] and not receipt['accepted'], receipt
        assert receipt['ledger']['by_status'].get('pending', 0), 'unfinished obligations remain explicit'
        for artifact, raw in published.items():
            source = docs[artifact.split(':', 1)[1]]
            assert (output / artifact.split(':', 1)[1]).read_bytes() == source
            delivered = next(row for row in receipt['delivery']['artifacts'] if row['artifact'] == artifact)
            assert delivered['source_sha256'] == sha(source)
            if kind == 'panels' and artifact.endswith('.svg'):
                assert_svg_presentation(raw, source, receipt)
                continue
            assert raw.endswith(source), (artifact, raw)
            if not artifact.endswith(('.md', '.txt')):
                assert raw == source, (artifact, raw)
            if artifact.endswith(('.md', '.txt')):
                assert b'RAVEL SINK NOTICE' in raw and (b'DIAGNOSTIC' in raw or b'QUALIFIED' in raw)
                assert b'Receipt: delivery/RECEIPT.json' in raw
        return Observation(kind, receipt, rows, published, docs, directory, observer)
