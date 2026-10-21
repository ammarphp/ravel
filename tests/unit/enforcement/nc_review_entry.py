"""Production review guards, inert observed effects and real qualified publication.

The guard may admit an inert byte producer. An independent observer always publishes
its component report through ordinary byte custody and the real sink. No helper
records an obligation satisfied/violated from the guard's answer; the real ledger and
sink make their own records. Fixture observations earn no scientific review credit.
"""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import subprocess
import sys
from pathlib import Path

from nc_cases import require_controller
from nc_controller import controller_run


class Scope:
    def __init__(self, parent, name):
        self.root = parent.root / name
        self.root.mkdir(parents=True)
        self.patch = parent.patch
        self.operator = None
        self.permitted_reads = []

    def path(self, *parts):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


@dataclass
class Outcome:
    errors: tuple
    notices: tuple
    disclosures: tuple
    allowed: bool
    effects: int
    reads: int
    diagnostics: dict
    receipt: dict
    ending: dict
    published: dict
    report: dict
    ledger: dict
    source_gap: str | None


class ReviewEntry:
    def __init__(self, nc, row):
        self.nc, self.row, self.sequence = nc, row, 0

    def run(self, probe, payload):
        self.sequence += 1
        scope = Scope(self.nc, f'review-{self.row.lower()}-{self.sequence}')
        self.nc.patch.setenv('RAVEL_STATE_DIR', str(self.nc.state))
        store, run_dir = controller_run(self.nc, f'review-{self.row.lower()}-{self.sequence}')
        ledger, sink = require_controller('ledger', 'sink')
        gap = None
        try:
            observed = probe(scope, deepcopy(payload))
        except (AttributeError, ImportError, NotImplementedError) as exc:
            gap = f'SOURCE-GAP {self.row} review/research owner: {type(exc).__name__}: {exc}'
            observed = {'errors': ['source_guard_unavailable'], 'notices': [], 'disclosures': [],
                        'diagnostics': {'source_gap': gap}}
        assert isinstance(observed, dict), ('invalid production probe result', self.row, observed)
        errors = tuple(observed.get('errors', ()))
        notices = tuple(observed.get('notices', ()))
        disclosures = tuple(observed.get('disclosures', ()))
        # These counters are held here, not in the worker payload or probe return value.
        starts, reads = [], []
        if not errors:
            for path in scope.permitted_reads:
                raw = Path(path).read_bytes()
                reads.append({'path': Path(path).relative_to(scope.root).as_posix(),
                              'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)})
            target = run_dir / 'steps/inert-producer/effect.txt'
            target.parent.mkdir(parents=True)
            output = b'inert byte producer executed\n'
            # Count in the parent before spawning. The child receives only its one declared
            # target and output bytes, and cannot edit this in-memory counter.
            starts.append({'kind': 'python-byte-producer'})
            process = subprocess.run([sys.executable, '-I', '-B', '-c',
                "import sys; open(sys.argv[1], 'wb').write(bytes.fromhex(sys.argv[2]))",
                str(target), output.hex()], capture_output=True, timeout=30)
            assert process.returncode == 0, process.stderr
            assert target.read_bytes() == output
        diagnostics = deepcopy(observed.get('diagnostics') or {})
        report = {'kind': 'component-guard-observation', 'row': self.row,
                  'consumer': probe.__name__, 'evidence_scope': 'unqualified fixture observation',
                  'fixture_models': {'qualification': 'unqualified', 'scientific_credit': 'none'},
                  'errors': list(errors), 'notices': list(notices), 'disclosures': list(disclosures),
                  'producer_starts': len(starts), 'input_reads': reads, 'diagnostics': diagnostics}
        raw = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
        plan = {'id': 'component-observation', 'route': {'id': 'judgment'},
                'steps': [{'id': 'inert-producer', 'kind': 'derive', 'depends_on': [],
                           'outputs': [{'path': 'effect.txt', 'kind': 'fixture-bytes', 'required': False}]},
                          {'id': 'observer', 'kind': 'derive', 'depends_on': [],
                           'outputs': [{'path': 'component.json', 'kind': 'component-observation', 'required': True}]}],
                'deliverables': [{'id': 'component-record', 'status': 'mapped', 'step': 'observer',
                                  'output': 'component.json', 'artifact_kind': 'component-observation',
                                  'claim_kind': 'component-observation'}]}
        from ravel.controller.engagement.records import digest
        plan['sha256'] = digest(plan)
        blob = store.put_blob(json.dumps(plan, sort_keys=True).encode())
        store.append('plan', {'plan': plan, 'blob': blob, 'plan_sha256': plan['sha256'], 'revision': 1})
        store.append('route', {'route': 'judgment'})
        ledger.materialise(store, 'intake', {'run_id': store.run_id, 'route': 'judgment'})
        ledger.materialise(store, 'plan', plan)
        target = run_dir / 'steps/observer/component.json'
        target.parent.mkdir(parents=True)
        target.write_bytes(raw)
        # Ordinary custody says only that this observer ran and adopted these exact bytes.
        store.append('custody', {'schema_version': 1, 'artifact': 'observer:component.json',
            'step_id': 'observer', 'attempt': 1, 'path': 'component.json',
            'destination': 'steps/observer/component.json', 'sha256': sha256(raw).hexdigest(),
            'status': 'accepted', 'kind': 'component-observation', 'inputs': [],
            'fixture_qualification': 'unqualified'})
        store.append('step-outcome', {'step_id': 'observer', 'attempt': 1, 'status': 'completed',
                                     'observation_scope': 'unqualified component observer'})
        reason = (errors or notices or disclosures or ('production component guard permitted inert effect',))[0]
        receipt = sink.bounded_end(store, reason)
        delivery = run_dir / 'delivery'
        assert delivery.is_dir(), ('SOURCE-GAP', self.row, 'sink owner: delivery missing', receipt)
        saved = json.loads((delivery / 'RECEIPT.json').read_bytes())
        ending = json.loads((delivery / 'qualified-delivery.json').read_bytes())
        assert saved['sha256'] == receipt['sha256']
        assert saved['qualified'] and not saved['accepted'] and not saved['architecture_complete']
        assert ending['reason'] == reason and ending['scientific_claims_adopted'] == []
        published = {row['path']: (delivery / row['path']).read_bytes() for row in saved['delivery']['artifacts']}
        expected = 'artifacts/observer/component.json'
        assert expected in published, ('SOURCE-GAP', self.row, 'sink observer-byte publication owner', saved)
        assert published[expected] == raw and json.loads(published[expected]) == report
        assert sink.receipt(store)['verification']['delivery_intact']
        assert ledger.verify(store)['verified'], ledger.verify(store)
        return Outcome(errors, notices, disclosures, not errors, len(starts), len(reads), diagnostics,
                       saved, ending, published, report, ledger.summary(store), gap)
