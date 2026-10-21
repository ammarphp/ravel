"""Shared support for the P02 ledger tests: a file-backed run store with the binding signatures, and fictional catalogues.

The store has the ``RunStore`` signatures of PACKAGES.md 0.2 (``append``, ``read``, ``scan``, ``path``) until the
controller core publishes ``tests/unit/controller/fakes.py``. It adds bookkeeping fields to every record, as a real
store may, so the ledger must ignore them. Nothing here is a test; pytest collects no case from this file.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import secrets
import sys
import types

import pytest

from ravel.controller import ledger
from ravel.controller.ledger import catalogue as catalogue_module, state as state_module


class FakeStore:
    """One append-only journal under ``root/<run_id>`` (mode 0700), shaped like the controller core's store.

    ``scan`` and ``read`` return envelopes ``{id, kind, seq, time_ns, prev, digest, record, schema_version}`` with
    the appended record under ``record``; ``bare=True`` returns the records themselves, as another store might.
    ``path()`` without parts is refused, as the controller core's store refuses it.
    """

    def __init__(self, run_id: str, *, root: Path | None = None, bare: bool = False):
        self.run_id = run_id
        self.bare = bare
        self.root = Path(root) / run_id
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    @property
    def journal(self) -> Path:
        return self.root / 'journal.jsonl'

    def entries(self) -> list[dict]:
        if not self.journal.exists():
            return []
        return [json.loads(line) for line in self.journal.read_text(encoding='utf-8').splitlines() if line.strip()]

    def append(self, kind: str, record: dict) -> str:
        entries = self.entries()
        body = {'schema_version': 1, 'seq': len(entries) + 1, 'kind': kind, 'time_ns': 1,
                'prev': entries[-1]['digest'] if entries else '0' * 64, 'record': json.loads(json.dumps(record))}
        entry = {**body, 'id': f'{kind}-{body["seq"]:06d}-{sha(json.dumps(body, sort_keys=True))[:12]}'}
        entry['digest'] = sha(json.dumps(entry, sort_keys=True))
        with open(self.journal, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, sort_keys=True) + '\n')
        return entry['id']

    def _shape(self, entry):
        return copy.deepcopy(entry['record'] if self.bare else entry)

    def read(self, kind: str, record_id: str) -> dict:
        for entry in self.entries():
            if entry['kind'] == kind and entry['id'] == record_id:
                return self._shape(entry)
        raise KeyError(f'{kind}/{record_id}')

    def scan(self, kind: str) -> list[dict]:
        return [self._shape(e) for e in self.entries() if e['kind'] == kind]

    def path(self, *parts: str) -> Path:
        if not parts:
            raise ValueError('invalid store path parts ()')
        return self.root.joinpath(*parts)

    # test helpers --------------------------------------------------------------------------------------
    def rewrite(self, entries: list[dict]) -> None:
        with open(self.journal, 'w', encoding='utf-8') as handle:
            for entry in entries:
                handle.write(json.dumps(entry, sort_keys=True) + '\n')


def row(rid, node, stage, scope, *, cls='E', ledger_class='execution/tool', mechanisms=('M01',),
        waivability='diagnostic', waiver=None, select=None, package='P99'):
    applicability = {'stage': stage, 'scope': scope}
    if select:
        applicability['select'] = select
    result = {'id': rid, 'kind': 'census-decision', 'ledger_class': ledger_class, 'category': 'fixture',
              'class': cls, 'mechanisms': list(mechanisms), 'node': node, 'package': package,
              'applicability': applicability, 'source': 'fixture:1', 'text': f'fictional obligation {rid}',
              'waivability': waivability}
    if waiver:
        result['waiver'] = waiver
    return result


def fixture_rows() -> list[dict]:
    """A small fictional catalogue that exercises every stage, scope, class and waivability."""
    return [
        row('X-INTAKE', 'controller.intake', 'intake', 'run'),
        row('X-ROUTE', 'controller.route_select', 'intake', 'run', ledger_class='route', waivability='authority',
            waiver='scope'),
        row('X-STANDING', 'authority.service', 'intake', 'run', ledger_class='authority/approval'),
        row('X-LABEL', 'hosts.surface', 'intake', 'run', cls='L'),
        row('X-MODE-scan', 'controller.intake', 'intake', 'run', select={'task_mode': 'scan'}, ledger_class='route',
            waivability='authority', waiver='scope'),
        row('X-KEEP', 'ledger.parent_join', 'intake', 'deliverable', ledger_class='route', waivability='authority',
            waiver='scope'),
        row('X-CI1', 'authority.ci1', 'plan', 'run', ledger_class='authority/approval', waivability='authority',
            waiver='authority'),
        row('CHECKIN-1', 'authority.ci1', 'plan', 'run', select={'checkin': '1'}, ledger_class='authority/approval',
            waivability='authority', waiver='authority'),
        row('CHECKIN-3', 'authority.ci3', 'plan', 'run', select={'checkin': '3'}, ledger_class='authority/approval',
            waivability='authority', waiver='authority'),
        row('X-CI3', 'authority.ci3', 'plan', 'run', ledger_class='authority/approval'),
        row('GATE-approve_plan', 'ledger.gate[approve_plan]', 'plan', 'run', select={'gate': 'approve_plan'},
            ledger_class='authority/approval'),
        row('X-FRAME', 'judgment.frame', 'plan', 'run', select={'route': ['judgment']}, ledger_class='route'),
        row('X-OP-alpha', 'step.operation[alpha]', 'plan', 'step', select={'operation': 'alpha'}),
        row('X-SEATDERIV', 'step.seat_derivation', 'plan', 'step', ledger_class='review/credit'),
        row('X-STEPDOC', 'route.analysis.step[03-generate]', 'plan', 'step', select={'workflow_step': '03-generate'}),
        row('GATE-launch', 'ledger.gate[launch]', 'plan', 'step', select={'gate': 'launch', 'launches': True},
            ledger_class='authority/approval'),
        row('X-CI2', 'authority.ci2', 'plan', 'waypoint', ledger_class='authority/approval', waivability='authority',
            waiver='authority'),
        row('CHECKIN-2', 'authority.ci2', 'plan', 'waypoint', select={'checkin': '2'},
            ledger_class='authority/approval', waivability='authority', waiver='authority'),
        row('GATE-checkin2_accept', 'ledger.gate[checkin2_accept]', 'plan', 'waypoint',
            select={'gate': 'checkin2_accept'}, ledger_class='authority/approval'),
        row('X-POINT', 'route.analysis.scan', 'plan', 'point'),
        row('X-SEAT', 'step.dispatch', 'seat', 'seat', select={'seat_kind': ['worker', 'review']},
            ledger_class='delegation/independence'),
        row('X-LAUNCH', 'confine.launch', 'seat', 'seat', select={'seat_kind': ['launch']}),
        row('X-ROLE-maker', 'step.packet[maker]', 'seat', 'seat', select={'role': 'maker'}, cls='I',
            ledger_class='role/instruction', mechanisms=('M12', 'M13'), waivability='never'),
        row('X-REVIEW', 'review.credit', 'review', 'seat', cls='R', ledger_class='review/credit'),
        row('X-SINK', 'controller.deliver', 'deliver', 'run', ledger_class='delivery/claims'),
        row('X-ART', 'controller.deliver', 'deliver', 'artifact', ledger_class='delivery/claims'),
        row('GATE-delivery', 'ledger.gate[delivery]', 'deliver', 'run', select={'gate': 'delivery'},
            ledger_class='authority/approval'),
        row('CHECKIN-deviation', 'controller.deviation', 'event', 'event', select={'checkin': 'deviation'},
            ledger_class='authority/approval', waivability='authority', waiver='authority'),
        row('GATE-deviation', 'ledger.gate[deviation]', 'event', 'event', select={'gate': 'deviation'},
            ledger_class='authority/approval'),
        row('GATE-correction', 'ledger.gate[correction]', 'event', 'event', select={'gate': 'correction'},
            ledger_class='authority/approval'),
    ]


def fixture_catalogue(rows=None, *, registry_sha256=None) -> bytes:
    from ravel.workflow import decision_gate
    rows = sorted(rows or fixture_rows(), key=lambda r: r['id'])
    document = {
        'schema': 'obligation-catalogue.v1',
        'gate_registry': {'path': 'src/ravel/data/gates/providers.json',
                          'sha256': registry_sha256 or decision_gate.registry_sha256(), 'providers': []},
        'counts': {'rows': len(rows)},
        'rows': rows,
    }
    return json.dumps(document, sort_keys=True).encode()


def use_catalogue(monkeypatch, data: bytes) -> None:
    """Serve ``data`` as the installed catalogue for this test (an in-process override of the package reader)."""
    monkeypatch.setattr(catalogue_module, '_bytes', lambda: data)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def install_controller(monkeypatch, owned: dict, root: Path) -> None:
    """Stand in for the controller core's ``ravel.controller.store`` (ownership and stores) in this process."""
    module = types.ModuleType('ravel.controller.store')

    def controller_owned(run_dir):
        return owned.get(str(Path(run_dir)))

    def make_store(run_id, *, root_dir=None):
        return FakeStore(run_id, root=root_dir or root)

    module.controller_owned = controller_owned
    module.RunStore = lambda run_id, *, root=None: make_store(run_id, root_dir=root)
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', module)


PLAN = {
    'sha256': 'f' * 64,
    'steps': [
        {'id': 's1', 'kind': 'operate', 'operation': 'alpha', 'role': 'maker', 'waypoint': True,
         'instruction_sources': ['docs/workflow/steps/03-generate.md'], 'review': ['checker']},
        {'id': 's2', 'kind': 'operate', 'operation': 'beta', 'role': 'maker', 'depends_on': ['s1'],
         'points': ['p1', 'p2'], 'instruction_sources': []},
    ],
    'deliverables': [{'id': 'D1', 'steps': ['s1']}, {'id': 'D2', 'steps': ['s2']}],
}


RUN = 'run-one'
INTAKE = {'run_id': RUN, 'task_mode': 'reproduce', 'deliverables': ['D1', 'D2']}


@pytest.fixture
def fixture_store(tmp_path, monkeypatch):
    """A fresh run store over the fictional catalogue (the installed catalogue is not touched)."""
    use_catalogue(monkeypatch, fixture_catalogue())
    store = FakeStore(RUN, root=tmp_path / 'store')
    yield store
    state_module.forget(store)


def evidence_for(row_class: str, **extra) -> dict:
    evidence = {'mechanism': 'fixture'}
    if row_class == 'R':
        evidence['credit'] = 'credit-1'
    if row_class == 'I':
        evidence['ack'] = 'ack-1'
    evidence.update(extra)
    return evidence


def satisfy(store, keys) -> None:
    """Satisfy every named entry with the evidence its class needs (conserved obligations excepted)."""
    catalogue = ledger.load_catalogue()
    changes = [(key, 'satisfied', evidence_for(catalogue.rows[key.split('@', 1)[0]]['class']))
               for key in keys if '/deliverable=' not in key]
    ledger.record_many(store, changes)


def compose_authority(store, monkeypatch):
    """The controller's composition for one store: an autonomous operator, the mode frozen by the authority
    service (P06) and P06's authenticated reader installed in the ledger. Needs ``operator_home``."""
    import importlib
    from ravel.controller import authority as service
    from test_p06_support import autonomous
    monkeypatch.setattr(importlib.import_module('ravel.controller.ledger.record'), '_authority_reader', None)
    autonomous()
    service.freeze_mode(store, {'prompt': 'Compute a fictional quantity.'})
    assert service.register_ledger_reader() is True


def issued_waiver(store, capfd, obligations, *, kind='approve_plan', change=None) -> str:
    """The store id of an authority record that the authority service issued for ``obligations``.

    A subject that names obligations never resolves by machine: the request waits, and the operator's answer
    quoting the request's code is recorded as ``operator_command``. A deviation binds the current CHECK-IN 1.
    """
    import re
    from ravel.controller import authority as service
    from test_p06_support import view
    pins = {'plan_sha256': PLAN['sha256']}
    if kind == 'deviation':
        approval = service.request(store, 'approve_plan', {'view': view(store, 'approve_plan', **pins)}, {})
        assert approval.get('decision') == 'approve', approval
        pins = {'approve_plan': approval['id']}
    subject = {'view': view(store, kind, **pins), 'obligations': sorted(obligations)}
    if change is not None:
        subject['change'] = change
    held = service.request(store, kind, subject, {})
    assert 'pending' in held, held
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    record = service.answer(store, held['pending']['request'], code, 'approve')
    assert record['label'] == service.OPERATOR_COMMAND and record['authorizes_effects'] is True
    return record['id']


def authority(store, *, run_id=RUN, label='physicist_terminal_response', kind='r3_action', decision='approve',
              obligations=None, touches=None, authorizes=True, uid=None) -> str:
    """A caller-written imitation of an authority record, without the issuer's seal; returns its uid.

    Only a test reader registered explicitly returns it; the authority service's own reader refuses it.
    """
    subject = {'pins': {}, 'checkin_sha256': 'c' * 64, 'gate': None, 'change': None}
    if obligations is not None:
        subject['obligations'] = list(obligations)
    if touches is not None:
        subject['change'] = {'parameter': 'scope', 'from': 'a', 'to': 'b', 'why': 'fixture', 'touches': list(touches),
                             'direction': 'narrow'}
    uid = uid or secrets.token_hex(16)
    store.append('authority', {'schema': 'authority-record.v1', 'uid': uid, 'run_id': run_id, 'kind': kind,
                               'decision': decision, 'label': label, 'subject': subject, 'bounds': {},
                               'authorizes_effects': authorizes, 'source': 'fixture'})
    return uid
