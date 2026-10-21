"""Supplied evidence reaches custody only through the controller's sink-bound import."""
from copy import deepcopy
import hashlib
import importlib
import json
import sys

import pytest

from ravel.controller import result_import
from ravel.controller.routes import manuscript
from ravel.controller.routes.manuscript import staged
from ravel.controller.routes.ml import staged as artifacts
from ravel.controller.sink import receipts
from p07_support import Run, FakeStore, READING
from test_p06_support import operator_home  # noqa: F401


def pin(store, source, **fields):
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    store.append('supplied', {'inputs': [{'kind': 'file', 'path': str(source), 'sha256': sha, **fields}]})
    return sha


def importer(tmp_path, *, frozen=False):
    """A controller-owned consumer run. ``frozen`` freezes its operating mode with the real authority, as
    intake does: copies into a governed run are admitted against the frozen mode and its current resource
    bounds, so a run with no frozen mode grants no custody (needs the ``operator_home`` fixture)."""
    run = tmp_path / 'run'
    run.mkdir(parents=True)
    store = FakeStore(tmp_path / 'protected', run_id='import-fixture')
    (run / 'controller-run.json').write_text(json.dumps({'run_id': store.run_id}))
    store.append('run', {'run_dir': str(run)})
    if frozen:
        from ravel.controller.authority import freeze_mode, operator
        if not operator._ledger_rows():
            operator.init(mode='physicist-in-the-loop')
        freeze_mode(store, {'prompt': 'Import the supplied fictional measurement.'}, run_dir=run)
    return store, run


def delivery(tmp_path, monkeypatch, *, qualified=False):
    options = {}
    if qualified:
        reading = deepcopy(READING)
        reading['constraints'] = [{'id': 'formula', 'type': 'prescribed_statistic',
                                   'value': {'statistic': 'S/sqrt(B + dB^2)', 'verbatim': True}}]
        options['reading'] = reading
    origin = Run(tmp_path / 'origin', monkeypatch, **options).complete()
    receipt = origin.deliver()
    assert receipt['label'] == ('qualified' if qualified else 'accepted'), receipt['work']['current_refusals']
    return origin, origin.delivered('artifacts/s1/outputs/value.json'), receipt


def test_missing_receipt_imports_external_bytes_with_provenance_and_idempotent_custody(tmp_path, operator_home):
    store, run = importer(tmp_path, frozen=True)
    source = tmp_path / 'measurement.json'
    source.write_bytes(b'{"value":0.75}')
    sha = pin(store, source)
    row = result_import.import_result(store, source, sha)
    assert row['status'] == 'accepted' and (run / row['destination']).read_bytes() == source.read_bytes()
    provenance = store.latest('result-import')['record']
    assert provenance['verification'] == 'external_unverified' and provenance['qualified'] is True
    assert provenance['receipt_sha256'] is None and provenance['origin_run'] is None
    assert store.get_blob(provenance['source_blob']) == source.read_bytes()
    before = len(store.entries)
    repeated = result_import.import_result(store, source, sha)
    assert repeated['artifact'] == row['artifact'] and len(store.entries) == before


@pytest.mark.parametrize('qualified', [False, True])
def test_sink_receipt_chain_admits_exact_delivered_bytes(tmp_path, monkeypatch, qualified):
    origin, source, receipt = delivery(tmp_path, monkeypatch, qualified=qualified)
    store, run = importer(tmp_path / 'consumer')
    row = result_import.import_result(store, source, pin(store, source))
    provenance = store.latest('result-import')['record']
    assert row['status'] == 'accepted' and row['evidence']['verification'] == 'verified'
    assert provenance['receipt_sha256'] == receipt['sha256']
    assert provenance['origin_run'] == origin.store.run_id
    assert provenance['qualified'] is qualified
    assert set(provenance['evidence_blobs']) == {'receipt', 'inventory', 'sidecar'}
    assert receipts.verify_saved(json.loads(store.get_blob(provenance['evidence_blobs']['receipt']))) == \
        json.loads(origin.delivered('RECEIPT.json').read_bytes())
    assert (run / row['destination']).read_bytes() == source.read_bytes()


@pytest.mark.parametrize('damage', ['result', 'receipt', 'rehash_receipt', 'inventory', 'sidecar',
                                   'origin_chain', 'origin_receipt', 'origin_binding'])
def test_present_but_invalid_receipt_is_typed_and_never_adopted(tmp_path, monkeypatch, damage):
    origin, source, _ = delivery(tmp_path, monkeypatch)
    store, run = importer(tmp_path / 'consumer')
    if damage == 'result':
        source.write_bytes(b'{"value":0.99}')
    elif damage in ('receipt', 'rehash_receipt'):
        path = origin.delivered('RECEIPT.json')
        value = json.loads(path.read_bytes())
        if damage == 'rehash_receipt':
            value['request']['channel'] = 'substituted'
            value = receipts.finalize(value)
        else:
            value['run_id'] = 'fabricated-origin'
        path.write_text(json.dumps(value))
    elif damage in ('inventory', 'sidecar'):
        path = origin.delivered('INVENTORY.json') if damage == 'inventory' else source.with_name(source.name + '.provenance.json')
        path.write_bytes(path.read_bytes() + b' ')
    elif damage == 'origin_chain':
        origin.store.tampered.append('altered journal')
    elif damage == 'origin_receipt':
        origin.store.entries[:] = [r for r in origin.store.entries if r['kind'] != 'receipt']
    elif damage == 'origin_binding':
        (origin.dir / 'controller-run.json').write_text('{}')
    with pytest.raises(result_import.ImportRefused) as refused:
        result_import.import_result(store, source, pin(store, source))
    assert refused.value.reason == 'result_import_receipt_invalid'
    assert store.latest('result-import-refusal')['record']['code'] == refused.value.reason
    assert not store.scan('custody') and not store.scan('result-import')
    assert not (run / 'steps').exists()


def test_missing_delivery_receipt_remains_external_even_with_a_provenance_sidecar(tmp_path, monkeypatch):
    origin, source, _ = delivery(tmp_path, monkeypatch)
    origin.delivered('RECEIPT.json').unlink()
    store, _ = importer(tmp_path / 'consumer')
    result_import.import_result(store, source, pin(store, source))
    imported = store.latest('result-import')['record']
    assert imported['verification'] == 'external_unverified' and imported['qualified'] is True
    assert imported['verification_reason'] == 'receipt_missing'


def test_delivery_bundle_name_does_not_determine_receipt_verification(tmp_path, monkeypatch):
    origin, source, receipt = delivery(tmp_path, monkeypatch)
    import shutil
    copied = tmp_path / 'supplied-bundle'
    shutil.copytree(origin.delivered(''), copied)
    source = copied / source.relative_to(origin.delivered(''))
    store, _ = importer(tmp_path / 'consumer')
    result_import.import_result(store, source, pin(store, source))
    assert store.latest('result-import')['record']['receipt_sha256'] == receipt['sha256']


@pytest.mark.parametrize('damage', ['unlisted', 'bytes_changed', 'linked'])
def test_import_requires_original_supplied_pin(tmp_path, damage):
    store, _ = importer(tmp_path / 'consumer')
    source = tmp_path / 'value.json'
    source.write_bytes(b'{"value":0.75}')
    sha = pin(store, source) if damage != 'unlisted' else '0' * 64
    expected = 'result_import_not_supplied'
    if damage == 'bytes_changed':
        source.write_bytes(b'{"value":0.99}')
        expected = 'result_import_bytes_changed'
    elif damage == 'linked':
        copy = source.with_suffix('.copy')
        source.rename(copy)
        source.symlink_to(copy)
        expected = 'result_import_invalid'
    with pytest.raises(result_import.ImportRefused) as refused:
        result_import.import_result(store, source, sha)
    assert refused.value.reason == expected
    assert not store.scan('custody')


def test_copied_result_can_name_original_receipt_and_superseded_delivery(tmp_path, monkeypatch):
    origin, source, first = delivery(tmp_path, monkeypatch)
    copied = tmp_path / 'copy.json'
    copied.write_bytes(source.read_bytes())
    origin.deliver()
    old = next(origin.dir.glob('delivery.superseded-*'))
    store, _ = importer(tmp_path / 'consumer')
    result_import.import_result(store, copied, pin(store, copied, receipt_path=str(old / 'RECEIPT.json')))
    assert store.latest('result-import')['record']['receipt_sha256'] == first['sha256']


def restore_routes(monkeypatch):
    # The sole-sink fixtures deliberately model absent route packages; these controls use the real ones.
    monkeypatch.setitem(sys.modules, manuscript.__name__, manuscript)
    monkeypatch.setitem(sys.modules, staged.__name__, staged)
    monkeypatch.setitem(sys.modules, artifacts.__name__, artifacts)


def note_plan(source, sha):
    note = importlib.import_module('ravel.controller.routes.manuscript.note')
    return {'parameters': {'result_path': str(source)}, 'steps': [
        {'id': 'author', 'kind': 'author', 'depends_on': [], 'outputs': [
            {'kind': 'manuscript:claim-map', 'required': True}]},
        {'id': 'sources', 'kind': 'operate', 'operation': note.OPERATIONS['sources'],
         'depends_on': ['author'], 'inputs': [], 'outputs': [{'path': note.RECEIPT, 'required': True}],
         'parameters': {'launch': {'argv': [sys.executable, '-I', '-m', note.__name__, 'sources',
                                '--result', 'measurement=' + str(source) + '@' + sha], 'reads': [str(source)]}}},
        {'id': 'report', 'kind': 'synthesize', 'depends_on': ['sources'], 'outputs': []}]}


@pytest.mark.parametrize('mode', ['verified', 'external', 'tampered'])
def test_composed_note_binding_admission_and_sink_qualification(tmp_path, monkeypatch, operator_home, mode):
    if mode == 'external':
        source = tmp_path / 'external.json'
        source.write_bytes(b'{"value":0.75}')
    else:
        origin, source, _ = delivery(tmp_path, monkeypatch)
        if mode == 'tampered':
            source.write_bytes(b'{"value":0.99}')
    restore_routes(monkeypatch)
    # The verified and tampered origins run under the p07 stand-in authority, which does not own this consumer;
    # the external consumer runs under the real authority and so needs its frozen mode.
    store, run = importer(tmp_path / 'consumer', frozen=mode == 'external')
    sha = pin(store, source)
    original = note_plan(source, sha)
    context = {'store': store, 'run_dir': run, 'plan': original}
    before = deepcopy(original)
    if mode == 'tampered':
        with pytest.raises(result_import.ImportRefused) as held:
            staged.bind(original, context)
        assert held.value.reason == 'result_import_receipt_invalid'
        assert not store.scan('custody') and not store.scan('result-import-use')
        return
    bound = staged.bind(original, context)
    assert original == before
    source_step = bound['steps'][1]
    assert str(source) not in source_step['parameters']['launch']['reads']
    assert staged.admit(source_step, {**context, 'plan': bound}) == []
    assert len(store.scan('result-import-use')) == 1
    assert staged.bind(bound, {**context, 'plan': bound}) == bound
    # The actual sink classification/label decision consumes the protected import dependency.
    from ravel.controller.sink import checks
    from ravel.controller.sink.deliver import decide_label
    findings = checks.Findings()
    classification = {'declared': [{'artifact': 'report:outputs/note.md', 'step': 'report'}]}
    shown = result_import.delivery_labels(store, bound, classification, findings)
    assert shown[0]['verification'] == ('verified' if mode == 'verified' else 'external_unverified')
    label = decide_label(findings, {'available': True, 'unmet': [], 'decisions': {}})
    assert label == ('accepted' if mode == 'verified' else 'qualified')
    if mode == 'external':
        assert findings.labels[0]['label'] == result_import.EXTERNAL
        assert findings.refusals[0]['code'] == 'external_result_unverified'


@pytest.mark.parametrize('dependent', [True, False])
def test_real_sink_keeps_dependent_delivery_qualified_and_records_imports(tmp_path, monkeypatch, dependent):
    run = Run(tmp_path, monkeypatch).complete()
    source = tmp_path / 'external.json'
    source.write_bytes(b'{"value":0.75}')
    row = result_import.import_result(run.store, source, pin(run.store, source))
    consumer = run.steps[0] if dependent else {'id': 'unused', 'kind': 'synthesize', 'depends_on': []}
    result_import.record_use(run.store, consumer, [row])
    receipt = run.deliver()
    assert receipt['label'] == ('qualified' if dependent else 'accepted')
    assert receipt['accepted'] is (not dependent)
    assert bool(receipt['imports']) is dependent
    if dependent:
        assert receipt['architecture_complete'] is False
        assert result_import.EXTERNAL in receipt['labels']
        assert result_import.EXTERNAL in run.delivered('DELIVERY.md').read_text()
        assert all(r['presentation_label'] == 'QUALIFIED' for r in receipt['delivery']['artifacts'])


def test_custody_lineage_cannot_launder_external_import_or_changed_snapshot(tmp_path, operator_home):
    store, run = importer(tmp_path, frozen=True)
    source = tmp_path / 'external.json'
    source.write_bytes(b'{"value":0.75}')
    row = result_import.import_result(store, source, pin(store, source))
    store.append('custody', {'artifact': 'middle:outputs/value.json', 'step_id': 'middle', 'inputs': [row['artifact']]})
    from ravel.controller.sink import checks
    plan = {'steps': [{'id': 'middle'}, {'id': 'report', 'depends_on': ['middle']}]}
    classification = {'declared': [{'artifact': 'report:outputs/note.md', 'step': 'report'}]}
    findings = checks.Findings()
    result_import.delivery_labels(store, plan, classification, findings)
    assert findings.refusals[0]['code'] == 'external_result_unverified'
    (run / row['destination']).write_bytes(b'changed')
    findings = checks.Findings()
    result_import.delivery_labels(store, plan, classification, findings)
    assert {r['code'] for r in findings.refusals} == {'result_import_custody_invalid', 'external_result_unverified'}


def test_completed_source_outputs_keep_import_lineage_across_plan_revisions(tmp_path, monkeypatch, operator_home):
    store, run = importer(tmp_path, frozen=True)
    source = tmp_path / 'external.json'
    source.write_bytes(b'{"value":0.75}')
    plan = staged.bind(note_plan(source, pin(store, source)), {'store': store, 'run_dir': run})
    step = plan['steps'][1]
    assert staged.admit(step, {'store': store, 'run_dir': run, 'plan': plan}) == []
    # Model the confined stage's accepted outputs with its real completed stage receipt.
    target = run / 'steps/sources/outputs/receipt.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'kind': 'manuscript-stage-receipt', 'stage': 'sources',
                                 'status': 'completed', 'outputs': {}, 'codes': []}))
    store.append('custody', {'artifact': 'sources:outputs/receipt.json', 'step_id': 'sources',
                            'path': 'outputs/receipt.json', 'destination': 'steps/sources/outputs/receipt.json',
                            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'inputs': [], 'status': 'accepted'})
    assert staged.step(step, {'status': 'completed'}, {'store': store, 'run_dir': run}) == []
    imported = store.latest('result-import')['record']['custody_artifact']
    latest = store.latest('custody')['record']
    assert latest['inputs'] == [imported] and latest['status'] == 'accepted'
    before = len(store.scan('custody'))
    result_import.retain_inputs(store, step)
    assert len(store.scan('custody')) == before
    # A later plan's changed step fingerprint cannot strip the original output's parents.
    step['title'] = 'Revised display text'
    from ravel.controller.sink import checks
    findings = checks.Findings()
    shown = result_import.delivery_labels(store, plan, {'declared': [
        {'step': 'report', 'artifact': 'report:outputs/note.md'}]}, findings)
    assert shown[0]['verification'] == 'external_unverified'
    assert findings.refusals[0]['code'] == 'external_result_unverified'
