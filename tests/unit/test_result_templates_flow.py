"""Synthetic flow declarations, pinned delivery and requester value policies."""
import hashlib
import json
import os

import pytest
import yaml

from ravel import cli
from ravel.workflow import result_templates as rt
from test_result_templates import accepted_run, edges, table, template, run_fill

SENTENCE = 'The rightmost bin includes all events above its lower edge.'
TABLE = """name: Synthetic observable
independent_variables:
- header: {name: coordinate, units: GeV}
  values:
  - {low: 0, high: 1}
  - {low: 1, high: 2}
dependent_variables:
- header: {name: content}
  values:
  - {value: null}
  - {value: null}
"""
MULTI = 'instructions: ' + SENTENCE + '\nowner: supplied metadata\n---\n' + TABLE


def result(**extra):
    return table(edges((0, 1), (1, 2), values=[2, 3]), **extra)


def values(path):
    docs = list(yaml.safe_load_all(path.read_bytes()))
    return [v['value'] for v in docs[-1]['dependent_variables'][0]['values']]


def test_metadata_flow_requires_declaration(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='rightmost.*last-bin.*excluded'):
        run_fill(tmp_path, monkeypatch, result(overflow=4), MULTI)
    assert not (tmp_path / 'filled.yaml').exists()


def test_missing_evidence_is_refused(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='evidence.*template'):
        run_fill(tmp_path, monkeypatch, result(overflow=4), MULTI,
                 overflow='last-bin', flow_evidence='A sentence absent from every document.')


def test_folded_result_cannot_be_excluded(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='last bin includes overflow'):
        run_fill(tmp_path, monkeypatch, result(overflow_in_last_bin=True), MULTI,
                 overflow='excluded', flow_evidence=SENTENCE)


def test_separate_flow_requires_convention_without_wording(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='overflow.*last-bin.*excluded'):
        run_fill(tmp_path, monkeypatch, result(overflow=4), TABLE)


def test_negative_requester_value_is_refused(tmp_path, monkeypatch):
    document = table(edges((0, 1), (1, 2), values=[2, -3]))
    with pytest.raises(ValueError, match='negative.*bin 1'):
        run_fill(tmp_path, monkeypatch, document, TABLE, require_nonnegative=True)
    assert not (tmp_path / 'filled.yaml').exists()


def test_fraction_with_separate_flow_requires_fold_first(tmp_path, monkeypatch):
    document = result(overflow=0.25, normalization={'kind': 'normalized', 'histogram_mode': 'fraction'})
    with pytest.raises(ValueError, match='fold.*before.*normali'):
        run_fill(tmp_path, monkeypatch, document, MULTI,
                 overflow='last-bin', flow_evidence=SENTENCE)


@pytest.mark.parametrize('mutation', ['before', 'during'])
def test_delivery_refuses_changed_requester_file(tmp_path, monkeypatch, mutation):
    rd = tmp_path / 'run'
    captured = accepted_run(rd, monkeypatch, result())
    tpl = template(tmp_path / 'template.yaml', TABLE)
    target = template(tmp_path / 'requester.yaml', TABLE)
    changed = TABLE.replace('{value: null}', '{value: 9}')
    if mutation == 'before':
        target.write_text(changed)
    else:
        original = rt.accepted
        def mutate(*args, **kwargs):
            target.write_text(changed)
            return original(*args, **kwargs)
        monkeypatch.setattr(rt, 'accepted', mutate)
    with pytest.raises(ValueError, match='deliver.*(changed|sha256|pin)'):
        rt.fill(tpl, captured, tmp_path / 'filled.yaml', rundir=rd, claim_scope='diagnostic',
                base_dir=tmp_path, deliver_into=target)
    assert target.read_text() == changed


def test_cli_fold_and_provenance(tmp_path, monkeypatch, capsys):
    rd = tmp_path / 'run'
    captured = accepted_run(rd, monkeypatch, result(overflow=4))
    tpl = template(tmp_path / 'template.yaml', MULTI)
    out = tmp_path / 'filled.yaml'
    assert cli.main(['fill-template', '--template', str(tpl), '--result', str(captured),
                     '--out', str(out), '--rundir', str(rd), '--claim-scope', 'diagnostic',
                     '--base', str(tmp_path), '--overflow', 'last-bin', '--flow-evidence', SENTENCE,
                     '--require-nonnegative']) == 0
    assert values(out) == [2, 7]
    record = json.loads(out.with_name(out.name + '.provenance.json').read_text())
    assert record['totals'] == {'filled': 9, 'from_result': 9}
    assert record['conventions']['source'] == 'cli-declaration'
    assert record['conventions']['evidence'] == SENTENCE
    assert record['conventions']['document_index'] == 0
    capsys.readouterr()


def test_folded_result_fills_without_double_counting(tmp_path, monkeypatch):
    record, _, _, out = run_fill(tmp_path, monkeypatch, result(overflow_in_last_bin=True), MULTI,
                                overflow='last-bin', flow_evidence=SENTENCE)
    assert values(out) == [2, 3]
    assert record['bins'][-1]['flow_added'] == []


def test_excluded_flow_is_recorded(tmp_path, monkeypatch):
    record, _, _, out = run_fill(tmp_path, monkeypatch, result(overflow=4), MULTI,
                                overflow='excluded', flow_evidence=SENTENCE)
    assert values(out) == [2, 3]
    assert record['flow_excluded']['overflow']['value'] == 4
    assert record['flow_excluded']['overflow']['declaration'] == 'excluded'
    assert record['flow_excluded']['overflow']['source'] == 'cli-declaration'


@pytest.mark.parametrize('same_template', [True, False])
def test_pinned_delivery_is_atomic_and_preserves_metadata(tmp_path, monkeypatch, same_template):
    rd = tmp_path / 'run'
    captured = accepted_run(rd, monkeypatch, result(overflow=4))
    tpl = template(tmp_path / 'template.yaml', MULTI)
    original = tpl.read_bytes()
    target = tpl if same_template else template(tmp_path / 'requester.yaml', MULTI)
    out = tmp_path / 'filled.yaml'
    replacements = []
    replace = os.replace
    def tracked(src, dst):
        replacements.append((src, dst))
        replace(src, dst)
    monkeypatch.setattr(os, 'replace', tracked)
    kwargs = dict(template=tpl, result=captured, out=out, rundir=rd, claim_scope='diagnostic',
                  overflow='last-bin', flow_evidence=SENTENCE, deliver_into=target, require_nonnegative=True)
    record, = rt.deliver([kwargs], base_dir=tmp_path)
    assert values(target) == [2, 7]
    assert target.read_bytes() == out.read_bytes()
    parsed = list(yaml.safe_load_all(target.read_bytes()))
    assert rt.Template(tpl, original, overflow='last-bin', flow_evidence=SENTENCE).unchanged_except_values(parsed)
    assert any(str(dst) == str(target) for _, dst in replacements)
    assert record['delivered_into'] == {'path': str(target.resolve()),
        'sha256_before': hashlib.sha256(original).hexdigest(),
        'sha256_after': hashlib.sha256(target.read_bytes()).hexdigest()}
    assert json.loads(out.with_name(out.name + '.provenance.json').read_text()) == record


def test_signed_results_are_allowed_without_requester_policy(tmp_path, monkeypatch):
    _, _, _, out = run_fill(tmp_path, monkeypatch, table(edges((0, 1), (1, 2), values=[2, -3])), TABLE)
    assert values(out) == [2, -3]


def test_single_bin_with_both_flows(tmp_path, monkeypatch):
    single = TABLE.replace('  - {low: 1, high: 2}\n', '').replace('  - {value: null}\n', '', 1)
    single = 'instructions: First bin includes all events and below; last bin is inclusive.\n---\n' + single
    record, _, _, out = run_fill(tmp_path, monkeypatch, table(edges((0, 1), values=[2]), overflow=4, underflow=1),
                                single, overflow='last-bin', underflow='first-bin',
                                flow_evidence='First bin includes all events and below; last bin is inclusive.')
    assert values(out) == [7]
    assert record['totals']['filled'] == 7


@pytest.mark.parametrize('wording, flow', [
    ('The final bin is inclusive.', 'overflow'),
    ('The last bin contains values 2 and above.', 'overflow'),
    ('The rightmost bin contains values greater than 2.', 'overflow'),
    ('The leftmost bin contains values 0 and below.', 'underflow'),
    ('The first bin is inclusive.', 'underflow'),
    ('Explicit underflow instructions apply.', 'underflow'),
])
def test_flow_vocabulary_in_any_metadata_document(tmp_path, wording, flow):
    raw = (TABLE + '\n---\ninstructions: ' + wording + '\n').encode()
    with pytest.raises(ValueError, match=f'mentions {flow}.*document 1'):
        rt.Template(tmp_path / 'template.yaml', raw)


def test_evidence_normalizes_whitespace_and_preserves_quote(tmp_path):
    raw = ('instructions: |\n  The rightmost bin includes all\n  events above its lower edge.\n---\n' + TABLE).encode()
    quote = 'The rightmost bin includes all events above its lower edge.'
    shape = rt.Template(tmp_path / 'template.yaml', raw, overflow='last-bin', flow_evidence=quote)
    assert shape.convention_provenance['evidence'] == quote
    assert shape.convention_provenance['document_index'] == 0


def test_cli_cannot_override_conflicting_metadata(tmp_path):
    raw = TABLE.replace('- header: {name: content}',
                        '- header: {name: content}\n  qualifiers:\n  - {name: overflow, value: last-bin}').encode()
    with pytest.raises(ValueError, match='conflicts'):
        rt.Template(tmp_path / 'template.yaml', raw, overflow='excluded', flow_evidence='content')


def test_one_bin_without_flow_fills(tmp_path, monkeypatch):
    single = TABLE.replace('  - {low: 1, high: 2}\n', '').replace('  - {value: null}\n', '', 1)
    _, _, _, out = run_fill(tmp_path, monkeypatch, table(edges((0, 1), values=[2])), single)
    assert values(out) == [2]


def test_delivery_rechecks_pin_after_staging(tmp_path, monkeypatch):
    rd = tmp_path / 'run'
    captured = accepted_run(rd, monkeypatch, result())
    tpl = template(tmp_path / 'template.yaml', TABLE)
    target = template(tmp_path / 'requester.yaml', TABLE)
    out = tmp_path / 'filled.yaml'
    changed = TABLE.replace('{value: null}', '{value: 8}')
    chmod = os.chmod
    def mutate(path, mode):
        chmod(path, mode)
        target.write_text(changed)
    monkeypatch.setattr(os, 'chmod', mutate)
    with pytest.raises(ValueError, match='deliver-into.*changed'):
        rt.fill(tpl, captured, out, rundir=rd, claim_scope='diagnostic', base_dir=tmp_path,
                deliver_into=target)
    assert target.read_text() == changed
    assert values(out) == [2, 3]
    assert 'delivered_into' not in json.loads(out.with_name(out.name + '.provenance.json').read_text())
    assert not list(tmp_path.glob('.requester.yaml.*.tmp'))


def test_cli_delivery_into_supplied_file(tmp_path, monkeypatch, capsys):
    rd = tmp_path / 'run'
    captured = accepted_run(rd, monkeypatch, result())
    tpl = template(tmp_path / 'template.yaml', TABLE)
    out = tmp_path / 'filled.yaml'
    assert cli.main(['fill-template', '--template', str(tpl), '--result', str(captured),
                     '--out', str(out), '--rundir', str(rd), '--claim-scope', 'diagnostic',
                     '--base', str(tmp_path), '--deliver-into', str(tpl), '--require-nonnegative']) == 0
    assert values(tpl) == [2, 3]
    capsys.readouterr()
