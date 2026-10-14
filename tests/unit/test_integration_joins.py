"""Joins between generation, event production, normalization, Rivet construction and the analysis engine.

Each join only exists once the separately developed stages are merged: event production
reads the generation receipt and any LHE transform receipt, production and the columnar
engine take sigma and factors from the normalization ledger or the cross-section
registry, the Rivet construction checks its typed specification with ``analysis_spec``,
and one synthetic chain runs from an LHE fixture to a filled result template.
"""
import hashlib
import json
import math
from pathlib import Path

import pytest

import production_fixtures as pf
from columnar_fixtures import RECIPE
from ravel.physics import event_production as ep
from ravel.physics import generation_receipt as gr
from ravel.physics import lhe_transform


@pytest.fixture(autouse=True)
def fast(monkeypatch, tmp_path):
    monkeypatch.setattr(ep, 'POLL_SECONDS', 0.02)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_generation(base, lhe_files, *, sigmas=None):
    """A generation-receipt.json in ``base/gen`` naming each LHE file as one parameter point."""
    root = base / 'gen'
    points = []
    for index, source in enumerate(lhe_files):
        target = root / 'points' / f'p{index}'
        target.mkdir(parents=True)
        lhe = target / 'events.lhe'
        lhe.write_bytes(Path(source).read_bytes())
        cards = []
        for name in ('proc_card.dat', 'run_card.dat', 'param_card.dat'):
            (target / name).write_text(f'# synthetic {name} for point {index}\n')
            cards.append({'name': name, **gr.file_record(target / name, root)})
        sigma = (sigmas or [0.25] * len(lhe_files))[index]
        audit = {'events': 12, 'cross_section_pb': sigma, 'integration_error_pb': 0.001}
        points.append(gr.point(f'p{index}', [], 10 + index, audit, cards, gr.file_record(lhe, root)))
    document = gr.build(generator={'name': 'MadGraph5_aMC@NLO', 'version': '3.6.0'},
                        process={'model': 'MSSM_SLHA2', 'generate': 'p p > n2 x1+'},
                        model={'name': 'MSSM_SLHA2'}, beams={'pdg': [2212, 2212], 'energy_gev': [6500, 6500]},
                        pdf={'pdlabel': 'lhapdf', 'lhaid': 247000}, points=points, weight_convention=-4,
                        cross_section_only=False)
    path = root / 'generation-receipt.json'
    path.write_text(json.dumps(document, indent=2))
    return path, [root / 'points' / f'p{i}' / 'events.lhe' for i in range(len(lhe_files))]


IDENTITY_RULES = {'schema_version': 1, 'kind': 'lhe_transform_rules', 'name': 'identity',
                  'rationale': 'Synthetic identity relabelling of incoming up quarks for the chain test.',
                  'rules': [{'id': 'up-quarks', 'match': {'status': [-1], 'pdg': [2]}, 'replace_pdg': 2,
                             'rationale': 'Identity rule: the PDG code is rewritten to itself.'}]}


# ---------------------------------------------------------------- (a) generation receipt -> production receipt
def test_production_records_the_generation_point_and_takes_its_cross_section(tmp_path):
    task = pf.production_task(tmp_path, n=4, chunks=1)
    other = pf.write_lhe(tmp_path / 'other.lhe', n=4, sigma=0.5)
    receipt, (first, second) = write_generation(tmp_path, [other, tmp_path / 'events.lhe'], sigmas=[0.5, 0.31])
    task['events'] = {'lhe': str(second), 'generation_receipt': str(receipt)}
    task['normalization'] = {'sigma': 'generation-receipt'}
    ep.validate(task)
    production = ep.run(task, tmp_path, tmp_path / 'out')
    document = json.loads((tmp_path / 'out' / production['receipt']['path']).read_text())
    link = document['generation']
    assert link['point'] == 'p1' and link['match'] == 'generated' and link['lhe_sha256'] == sha(second)
    assert link['receipt']['sha256'] == sha(receipt) and document['generation_receipt']['sha256'] == sha(receipt)
    assert link['generator']['version'] == '3.6.0' and link['transform'] is None
    assert document['sigma']['value_pb'] == 0.31
    assert document['sigma']['generation_receipt']['pointer'] == '/points/1/cross_section/value_pb'
    assert document['sigma']['convention']['order'] == 'LO' and 'MadGraph5_aMC@NLO 3.6.0' == document['sigma']['convention']['tool']


def test_generation_receipt_must_name_the_lhe_and_its_files_must_be_unchanged(tmp_path):
    task = pf.production_task(tmp_path, n=4, chunks=1)
    other = pf.write_lhe(tmp_path / 'other.lhe', n=4, sigma=0.5)
    receipt, (first,) = write_generation(tmp_path, [other])
    task['events']['generation_receipt'] = str(receipt)
    with pytest.raises(ValueError, match='names no LHE file'):
        ep.compile_task(task, tmp_path)
    task['events']['lhe'] = str(first)
    task['model']['name'] = 'MSSM_SLHA2'
    assert ep.compile_task(task, tmp_path)['generation']['point'] == 'p0'
    (first.parent / 'run_card.dat').write_text('# edited after generation\n')
    with pytest.raises(ValueError, match='missing or changed: points/p0/run_card.dat'):
        ep.compile_task(task, tmp_path)


def test_transform_required_settings_reach_every_shower_variant(tmp_path):
    task = pf.production_task(tmp_path, n=4, chunks=1)
    rules = dict(IDENTITY_RULES, downstream_settings=['Check:event = off'])
    (tmp_path / 'rules.json').write_text(json.dumps(rules))
    transformed = lhe_transform.run({'input': 'events.lhe', 'rules': 'rules.json'}, tmp_path, tmp_path / 'tx')
    receipt, _ = write_generation(tmp_path, [tmp_path / 'events.lhe'])
    task['events'] = {'lhe': 'tx/transformed.lhe', 'generation_receipt': str(receipt),
                      'lhe_transform': 'tx/transformed.lhe.transform.json'}
    with pytest.raises(ValueError, match='lacks the settings the LHE transform requires: Check:event = off'):
        ep.compile_task(task, tmp_path)
    task['shower']['commands'].append('Check:event = off')
    task['shower']['variants'] = [{'name': 'mpi-off', 'commands': ['PartonLevel:MPI = off']}]
    link = ep.compile_task(task, tmp_path)['generation']
    assert link['match'] == 'transformed' and link['point'] == 'p0'
    assert link['transform']['receipt']['sha256'] == transformed['receipt']['sha256']
    assert link['transform']['required_downstream_settings'] == ['Check:event = off']


def test_transform_recorded_inside_the_generation_receipt_is_followed(tmp_path):
    """Scoped generation writes events.transformed.lhe and lists it under transform.points."""
    task = pf.production_task(tmp_path, n=4, chunks=1)
    receipt, (generated,) = write_generation(tmp_path, [tmp_path / 'events.lhe'])
    root = receipt.parent
    rules = dict(IDENTITY_RULES, rules=[dict(IDENTITY_RULES['rules'][0], replace_pdg=1, rationale='u to d relabel',
                                             declares=['changes_charge'])])
    output = generated.with_name('events.transformed.lhe')
    lhe_transform.transform(generated, output, rules)
    document = json.loads(receipt.read_text())
    document['transform'] = {'name': 'identity', 'rules_sha256': 'x', 'required_downstream_settings': ['Check:event = off'],
                             'deviations': [], 'points': {'p0': {
                                 'output': gr.file_record(output, root),
                                 'receipt': gr.file_record(output.with_name(output.name + '.transform.json'), root),
                                 'census': {}, 'events_changed': 4}}}
    receipt.write_text(json.dumps(document))
    task['events'] = {'lhe': str(output), 'generation_receipt': str(receipt)}
    task['shower']['commands'].append('Check:event = off')
    link = ep.compile_task(task, tmp_path)['generation']
    assert link['match'] == 'transformed' and link['transform']['output_sha256'] == sha(output)
    assert link['transform']['original_sha256'] == sha(generated) and link['transform']['events_changed'] == 4


# ---------------------------------------------------------------- (b) ledger and registry
LEDGER = {'schema_version': 1, 'sample': 'synthetic', 'luminosity': {'value': 139, 'unit': 'fb^-1', 'source': 's'},
          'sigma': {'value': 300.0, 'unit': 'fb', 'order': 'NLO+NLL', 'tool': 'declared table', 'pdf': 'PDF4LHC15',
                    'scales': 'central', 'process_basis': 'n2 x1+', 'source': 'synthetic reference table'},
          'br': [{'value': 0.5, 'source': 'paper_assumption', 'detail': 'declared'}],
          'filter_eff': {'value': 0.8, 'source': 'generator filter'}, 'k': None,
          'generated': {'sumw': 1.0, 'sumw2': 1.0}, 'selected': {'r': {'sumw': [1.0], 'sumw2': [1.0]}},
          'bin_convention': 'per-bin'}


def _analysis(tmp_path, production, normalization):
    (tmp_path / 'recipe.json').write_text(json.dumps(RECIPE))
    return {'recipe': 'recipe.json', 'format': 'delphes', 'inputs': production['outputs']['synthetic'],
            'normalization': normalization, 'chunk_size': 50}


def test_ledger_sigma_and_factors_reach_the_analysis_engine_through_the_receipt(tmp_path):
    from ravel.physics import columnar_analysis
    task = pf.production_task(tmp_path, n=6, chunks=1)
    (tmp_path / 'ledger.json').write_text(json.dumps(LEDGER))
    task['normalization'] = {'sigma': 'ledger', 'ledger': 'ledger.json'}
    production = ep.run(task, tmp_path, tmp_path / 'out')
    receipt_path = tmp_path / 'out' / production['receipt']['path']
    receipt = json.loads(receipt_path.read_text())
    assert math.isclose(receipt['sigma']['value_pb'], 0.3 * 0.5 * 0.8)
    declared = receipt['analysis_normalization']
    assert declared['cross_section_pb'] == {'production_receipt': ep.RECEIPT}
    normalization = {**declared, 'cross_section_pb': {'production_receipt': str(receipt_path)},
                     'luminosity_ifb': 139.0, 'luminosity_source': 'synthetic'}
    analysis = _analysis(tmp_path, production, normalization)
    assert receipt_path in [Path(f) for f in columnar_analysis.inputs(analysis, tmp_path)]
    result = columnar_analysis.run(analysis, tmp_path, tmp_path / 'analysis')
    norm = result['normalization']
    assert norm['cross_section_pb'] == pytest.approx(0.3) and norm['factor']['value'] == pytest.approx(0.4)
    assert norm['scale'] == pytest.approx(0.3 * 0.4 * 1000 * 139.0 / receipt['weights']['sum'], rel=1e-12)
    ledger = norm['cross_section_from']['normalization_ledger']
    assert ledger['br_product'] == 0.5 and ledger['filter'] == 0.8 and ledger['sigma_convention']['order'] == 'NLO+NLL'
    assert norm['cross_section_from']['sha256'] == sha(receipt_path)
    with pytest.raises(ValueError, match='apply them twice'):
        columnar_analysis.run({**analysis, 'normalization': {**normalization, 'factor': {'value': 0.4, 'source': 'again'}}},
                              tmp_path, tmp_path / 'again')


def test_registry_cross_section_in_production_and_ledger_file_in_the_engine(tmp_path):
    from ravel.physics import columnar_analysis, cross_sections
    request = {'schema_version': 1, 'basis': 'gluino_pair', 'sqrt_s_GeV': 13000, 'masses': {'mass': 2050},
               'convention': {'order': 'aNNLO+NNLL', 'pdf': 'as-published', 'scale': 'as-published'}}
    expected = cross_sections.lookup(request)['sigma_pb']
    task = pf.production_task(tmp_path, n=4, chunks=1)
    task['normalization'] = {'sigma': 'registry', 'request': request, 'process_basis': 'p p > go go'}
    production = ep.run(task, tmp_path, tmp_path / 'out')
    receipt_path = tmp_path / 'out' / production['receipt']['path']
    sigma = json.loads(receipt_path.read_text())['sigma']
    assert sigma['value_pb'] == expected and sigma['convention']['order'] == 'aNNLO+NNLL'
    assert sigma['cross_section_lookup']['table']['sha256'] and sigma['convention']['process_basis'] == 'p p > go go'
    (tmp_path / 'ledger.json').write_text(json.dumps(LEDGER))
    base = {'mode': 'cross-section', 'cross_section_source': 'ledger', 'luminosity_ifb': 139.0,
            'luminosity_source': 'synthetic', 'sum_of_weights': 'all-input-events'}
    by_registry = columnar_analysis.run(_analysis(tmp_path, production, {**base, 'cross_section_pb': {'cross_section_registry': request}}),
                                        tmp_path, tmp_path / 'registry')['normalization']
    assert by_registry['cross_section_pb'] == expected
    assert by_registry['cross_section_from']['cross_section_registry']['table']['sha256'] == sigma['cross_section_lookup']['table']['sha256']
    by_ledger = columnar_analysis.run(_analysis(tmp_path, production, {**base, 'cross_section_pb': {'normalization_ledger': 'ledger.json'}}),
                                      tmp_path, tmp_path / 'ledger')['normalization']
    assert by_ledger['cross_section_pb'] == pytest.approx(0.3) and by_ledger['factor']['value'] == pytest.approx(0.4)
    assert by_ledger['cross_section_from']['normalization_ledger']['sha256'] == sha(tmp_path / 'ledger.json')


# ---------------------------------------------------------------- (c) Rivet construction uses analysis_spec
def _spec(tmp_path, paper_text):
    from ravel.workflow import analysis_spec
    paper = tmp_path / 'spec' / 'paper.txt'
    paper.parent.mkdir()
    paper.write_text(paper_text)
    raw = paper.read_bytes()
    document = {'schema_version': 1, 'kind': 'typed-analysis-spec', 'analysis': 'synthetic',
                'sources': [{'id': 'paper', 'path': 'paper.txt'}],
                'items': [{'id': 'met-hist', 'role': 'histogram', 'region': 'signal region',
                           'slice': {'variable': 'y', 'low': 0, 'high': 2},
                           'fields': {'normalization_basis': {'value': 'bin_width_area_2D', 'status': 'explicit',
                                                              'span': analysis_spec.span_for(raw, 'paper', 2, 2)},
                                      'hepdata_id': {'value': 'd04-x01-y01', 'status': 'inferred', 'note': 'table order'},
                                      'cross_section_unit': {'value': 'fb', 'status': 'explicit',
                                                             'span': analysis_spec.span_for(raw, 'paper', 3, 3)}}}]}
    path = tmp_path / 'spec' / 'spec.json'
    path.write_text(json.dumps(document))
    return path, paper


def test_rivet_construction_spec_is_span_checked_and_its_slice_reaches_the_contract(tmp_path):
    from ravel.physics import rivet_sample_checks
    from ravel.workflow import agentrivet_brief
    path, paper = _spec(tmp_path, 'Intro\nCross sections are double differential.\nUnits are fb.\n')
    pin = {'path': str(path), 'sha256': sha(path)}
    sources = []
    document = agentrivet_brief.load_spec(pin, tmp_path, sources=sources)
    assert sources == [{'id': 'paper', 'path': str(paper.resolve()), 'sha256': sha(paper)}]
    rows = rivet_sample_checks.contract_from_spec(document)
    assert rows[0]['slice'] == {'variable': 'y', 'low': 0, 'high': 2} and rows[0]['unit'] == 'fb'
    paper.write_text('Intro\nCross sections are single differential.\nUnits are fb.\n')
    with pytest.raises(ValueError, match='differ from the span hash'):
        agentrivet_brief.load_spec(pin, tmp_path)


# ---------------------------------------------------------------- (d) one synthetic chain
def test_lhe_to_filled_template_chain_links_every_receipt(tmp_path, monkeypatch):
    """LHE -> lhe-transform (identity) -> event-production (stub Pythia/Delphes) -> columnar-analysis
    -> binned_values -> fill-template, with each stage pinning the one before it."""
    from ravel.physics import columnar_analysis
    from ravel.workflow import result_templates as rt
    from test_task_completion import review_run
    task = pf.production_task(tmp_path, n=30, chunks=2)
    fixture = tmp_path / 'events.lhe'
    receipt, (generated,) = write_generation(tmp_path, [fixture])
    (tmp_path / 'rules.json').write_text(json.dumps(IDENTITY_RULES))
    transform = lhe_transform.run({'input': str(generated), 'rules': 'rules.json'}, tmp_path, tmp_path / 'tx')
    transform_receipt = json.loads((tmp_path / 'tx/transformed.lhe.transform.json').read_text())
    assert transform_receipt['events'] == 30 and transform_receipt['invariants']['weights_unchanged']
    task['events'] = {'lhe': 'tx/transformed.lhe', 'generation_receipt': str(receipt),
                      'lhe_transform': 'tx/transformed.lhe.transform.json'}
    task['normalization'] = {'sigma': 'generation-receipt'}
    production = ep.run(task, tmp_path, tmp_path / 'out')
    assert production['status'] == 'passed'
    receipt_path = tmp_path / 'out' / production['receipt']['path']
    produced = json.loads(receipt_path.read_text())
    link = produced['generation']
    assert link['receipt']['sha256'] == sha(receipt) and link['point'] == 'p0' and link['match'] == 'transformed'
    assert link['transform']['original_sha256'] == sha(generated) == json.loads(receipt.read_text())['points'][0]['lhe']['sha256']
    assert link['transform']['output_sha256'] == sha(tmp_path / 'tx/transformed.lhe') == produced['cards']['lhe']['sha256']
    assert link['transform']['receipt']['sha256'] == transform['receipt']['sha256']
    assert produced['sigma']['value_pb'] == 0.25 and produced['events']['accepted'] == 30

    normalization = {**produced['analysis_normalization'], 'luminosity_ifb': 139.0, 'luminosity_source': 'synthetic',
                     'cross_section_pb': {'production_receipt': str(receipt_path), 'pointer': '/sigma/value_pb'}}
    analysis = _analysis(tmp_path, production, normalization)
    result = columnar_analysis.run(analysis, tmp_path, tmp_path / 'analysis')
    assert result['status'] == 'passed'
    assert result['normalization']['cross_section_from']['sha256'] == sha(receipt_path)
    histogram_path = tmp_path / 'analysis' / result['histograms']['met in three-lepton region']['file']
    histogram = json.loads(histogram_path.read_text())
    assert histogram['kind'] == 'binned_values'

    rd = tmp_path / 'run'
    accepted = rd / 'inputs/result.json'
    accepted.parent.mkdir(parents=True)
    accepted.write_bytes(histogram_path.read_bytes())
    review_run(rd, [str(accepted)], monkeypatch)
    axis = histogram['axes'][0]
    # The histogram carries the events beyond its edges as separate flow. A template is filled from
    # such a result only under a declared convention that the template's own text supports.
    carried = [name for name in ('overflow', 'underflow') if name in histogram]
    assert 'overflow' in carried
    convention = 'Events outside the listed edges are not part of this table.'
    template = tmp_path / 'template.yaml'
    template.write_text(
        f"instructions: {convention}\nowner: supplied metadata\n---\n"
        f"name: {axis['name']}\nindependent_variables:\n- header: {{name: {axis['name']}, units: {axis.get('unit', 'GeV')}}}\n"
        "  values:\n  - {low: 30, high: 60}\n  - {low: 60, high: 120}\n  - {low: 120, high: 200}\n"
        "dependent_variables:\n- header: {name: Events}\n  values:\n  - {value: null}\n  - {value: null}\n  - {value: null}\n")
    record = rt.fill(template, accepted, tmp_path / 'filled.yaml', rundir=rd, claim_scope='diagnostic', base_dir=tmp_path,
                     flow_evidence=convention, **{name: 'excluded' for name in carried})
    assert {name: (row['declaration'], row['value']) for name, row in record['flow_excluded'].items()} \
        == {name: ('excluded', histogram[name]) for name in carried}
    assert record['result']['sha256'] == sha(histogram_path)
    assert [b['value'] for b in record['bins']] == pytest.approx([b['value'] for b in histogram['bins']])
    assert record['edges_unchanged'] and record['values_from_result_only']
