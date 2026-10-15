"""The documented prescribed-statistic path keeps wording, quantity and boundaries."""
import json
import re

import pytest

from ravel.physics.inference import record

SKILL = 'inference-engines'


def document():
    return {'schema_version': 1, 'kind': 'prescribed-statistic',
            'statistic': {'kind': 'closed-form', 'verbatim': 'Synthetic rule: accept p squared at or below one.'},
            'grid': {'axes': [{'name': 'p', 'unit': '', 'label': 'Synthetic parameter',
                               'min': -2., 'max': 2., 'points': 17}]},
            'program': {'constants': [], 'definitions': [],
                        'outputs': [{'name': 'q', 'expression': 'p**2', 'unit': '', 'label': 'Squared parameter'}]},
            'statistic_output': 'q', 'threshold': 1., 'region': 'at-or-below'}


def run_doc(handbook, tmp_path, doc):
    path = tmp_path / 'document.json'; path.write_text(json.dumps(doc))
    evaluate = handbook.load(SKILL, 'evaluate-prescribed-statistic')['evaluate_prescribed']
    result = evaluate(path, tmp_path / 'out')
    return result, json.loads((tmp_path / 'out/inference.json').read_text())


def test_record_lists_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ['evaluate-prescribed-statistic']


def test_prescribed_result_is_primary_and_not_physics_certification(handbook, tmp_path):
    _, inference = run_doc(handbook, tmp_path, document())
    record.validate(inference)
    assert inference['statistic']['verbatim'] == document()['statistic']['verbatim']
    assert inference['statistic']['origin'] == 'prescribed' and inference['physics_validated'] is False
    region = next(r for r in inference['results'] if r['quantity'] == 'contour')['region']
    assert next(r for r in inference['results'] if r['quantity'] == 'contour')['role'] == 'primary'
    assert region['intervals'][0]['low']['value'] == pytest.approx(-1.)
    assert region['intervals'][0]['high']['value'] == pytest.approx(1.)


def test_scan_edge_is_unresolved(handbook, tmp_path):
    doc = document(); doc['grid']['axes'][0]['max'] = .5
    _, inference = run_doc(handbook, tmp_path, doc)
    assert inference['status'] == 'failed'
    region = next(r for r in inference['results'] if r['quantity'] == 'contour')['region']
    assert region['intervals'][0]['high']['status'] == 'beyond_scan'


def test_omitted_statistic_wording_is_refused(handbook, tmp_path):
    doc = document(); del doc['statistic']['verbatim']
    with pytest.raises(ValueError, match='verbatim'):
        run_doc(handbook, tmp_path, doc)


def test_uncited_constant_is_refused(handbook, tmp_path):
    doc = document()
    doc['program']['constants'] = [{'name': 'c', 'value': 2., 'unit': '', 'origin': 'cited'}]
    with pytest.raises(ValueError, match='citation'):
        run_doc(handbook, tmp_path, doc)


def test_six_handbook_bindings_and_advisory_candidates():
    from ravel.setup import manifest as mf
    from ravel.validation import tool_handbooks as hb
    from ravel.workflow.science import MODES

    manifest = mf.load()[0]
    declared_groups, held_groups = set(mf.by_id(manifest)), mf.unreleased_groups(manifest)
    held_operations = mf.unreleased_operations(manifest)
    shipped = {path.name for path in hb.handbooks()}
    bindings = {
        'columnar-analysis': {'columnar-analysis', 'authored-analysis', 'reco-ntuple-routine',
                             'ntuple-inventory', 'mc-expected-construction', 'root-stream',
                             'dataset-query-quantities'},
        'cross-section-normalization': {'cross-section', 'simplified-spectrum', 'group-normalization'},
        'inference-engines': {'formula-grid', 'coupling-morphing', 'prescribed-statistic',
                             'search-statistics', 'differential-likelihood'},
        'roofit-histfactory': {'native-statistical-construction', 'statistical-model',
                             'asimov-sensitivity', 'mc-closure'},
        # af8ce1e: the handbook binds only the MCFM-backed modes; the JHUGen/MELA cross-check mode
        # belongs to an unreleased tool group and is not bound by this handbook.
        'mcfm-amplitudes': {'amplitude-integration', 'amplitude-predictions', 'weighted-events'},
        'model-authoring': {'model-authoring', 'model-sources', 'model-derivation-bridge', 'model-provider-bridge'},
    }
    # A handbook written for one toolchain group ships exactly where the tree declares that group.
    tool_group = {'mcfm-amplitudes': 'mcfm-amplitudes'}
    for name, expected in bindings.items():
        group = tool_group.get(name)
        if group is not None and group not in declared_groups:
            assert name not in shipped
            continue
        path = hb.handbook_root() / name
        front, body = hb.split_frontmatter((path / 'SKILL.md').read_text())
        assert set(front) == set(hb.FRONTMATTER_KEYS)
        assert set(hb.words(front['metadata']['ravel-requires-modes'])) == expected <= set(MODES)
        if group not in held_groups:
            assert not expected & held_operations, name
        for _, file in hb.handbook_files(path).items():
            text = file.read_text()
            assert hb.estimate_tokens(text) <= hb.TOKEN_BUDGET
            assert not re.search(r'\bM-\d+\b|Codex|coordinator|this stream', text), file
        checks = (path / 'references/checks.md').read_text()
        advisory = [p for p in hb.pitfalls(body) if p.startswith('Advisory:')]
        assert len(advisory) == 1 and 'Candidate check' in advisory[0]
        candidate_id = advisory[0].split('Candidate check ')[1].split()[0]
        assert f'| {candidate_id} |' in checks
        assert '## Wrong versus right' in body
    all_pitfalls = []
    for path in hb.handbooks():
        _, body = hb.split_frontmatter((path / 'SKILL.md').read_text())
        all_pitfalls.extend(hb.pitfalls(body))
    assert sum('Advisory:' in p for p in all_pitfalls) / len(all_pitfalls) <= .4
