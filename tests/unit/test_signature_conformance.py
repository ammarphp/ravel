"""Operation signatures: every registered mode is signed, every entry conforms, chains resolve."""
import synthetic_identifiers as syn
import copy
import json
from pathlib import Path

import pytest

from ravel.validation import signature_conformance as sc
from ravel.validation import validate_request_plan as rp

REGISTRY = rp.registry()
CHAIN_MODES = ('asimov-sensitivity', 'ntuple-inventory', 'root-stream', 'mc-closure')
MEASURED_ON = ('analyze', 'columnar-analysis', 'measurement', 'normalized-measurement', 'differential-likelihood',
               'search-statistics', 'prescribed-statistic')


def _entry(name='ex-op', **changes):
    entry = {'summary': 'A synthetic operation.', 'implementation': {'kind': 'command', 'module': 'ravel.workflow.grid_recipe'},
             'consumes': [{'slot': 'axes', 'kind': 'table'}], 'produces': [{'slot': 'points', 'kind': 'parameter_point'}],
             'effects': [], 'cost': {'unit': 'task', 'forecast': None, 'ceiling_pointer': None}, 'critical_fields': [],
             'basis': {'adds': [], 'passes': ['axes']}, 'tools': [], 'stages': [], 'review': {'checks': ['io_contract']},
             'fidelity_rank': 1}
    entry.update(changes)
    return entry


# --------------------------------------------------------------------------- the registry
def test_every_registered_mode_has_a_conforming_signature():
    assert sc.conformance() == []


def test_every_registered_operation_has_artifact_kinds():
    for name, entry in REGISTRY.items():
        assert entry is not None, name
        assert entry['produces'], name
        assert all(sc.known_kind(s['kind']) for s in entry['consumes'] + entry['produces']), name


def test_every_artifact_kind_has_a_witness():
    assert set(rp.ARTIFACT_KINDS) == set(sc.WITNESSES)


@pytest.mark.parametrize('name', CHAIN_MODES)
def test_search_chain_rows_exist_and_resolve(name):
    entry = REGISTRY[name]
    assert entry is not None
    assert entry['implementation'] == {'kind': 'science-mode', 'mode': name, 'module': sc._science_module(name)}
    assert sc.entry_errors(name, entry) == []


def test_search_chain_composes_from_inventory_to_expected_significance_and_closure():
    chain = ['ntuple-inventory', 'root-stream', 'mc-expected-construction', 'asimov-sensitivity', 'mc-closure']
    assert sc.resolves(chain) == []
    found = sc.chains('root-stream', 'inference', limit=500)
    assert ['root-stream', 'mc-expected-construction', 'asimov-sensitivity'] in found
    assert all(sc.resolves(c) == [] for c in found)
    assert REGISTRY['asimov-sensitivity']['produces'][0]['require'] == {'level': 'expected'}


def test_chain_refuses_an_edge_whose_kinds_or_properties_differ():
    assert sc.edge_errors('ntuple-inventory', 'inventory', 'root-stream', 'read_contract')  # content differs
    assert sc.edge_errors('ntuple-inventory', 'read_contract', 'root-stream', 'read_contract') == []
    assert sc.edge_errors('literal-calculation', 'value', 'mc-closure', 'deliveries')  # scalar into inference
    assert sc.resolves(['literal-calculation', 'mc-closure']) == ['no resolvable edge from literal-calculation to mc-closure']


@pytest.mark.parametrize('name', MEASURED_ON)
def test_measured_data_slot_on_analysis_and_measurement_statistics(name):
    slot = {s['slot']: s for s in REGISTRY[name]['consumes']}['measured']
    assert slot['kind'] == 'table' and slot['optional'] is True
    assert slot['require'] == {'source': ['published', 'requester'], 'observed': True}
    assert 'measured' in REGISTRY[name]['basis']['passes']


def test_grid_recipe_and_table_converter_are_registered_commands():
    for name, module in (('grid-recipe', 'ravel.workflow.grid_recipe'),
                         ('table-bin-edges', 'ravel.physics.table_bin_edges')):
        assert REGISTRY[name]['implementation'] == {'kind': 'command', 'module': module}
    assert REGISTRY['grid-recipe']['effects'] == ['varies_parameters']
    assert sc.edge_errors('table-bin-edges', 'values', 'search-statistics', 'signal') == []


def test_figure_stage_operations_check_the_figure_spec():
    figure_ops = [n for n, e in REGISTRY.items() if 'figure' in e['stages']]
    assert figure_ops
    assert all('validation.plot_lint' in REGISTRY[n]['review']['checks'] for n in figure_ops)


# --------------------------------------------------------------------------- entry conformance (negative cases)
def test_a_conforming_synthetic_entry_passes():
    assert sc.entry_errors('ex-op', _entry()) == []


@pytest.mark.parametrize('changes,needle', [
    ({'produces': []}, 'produces at least one artifact'),
    ({'consumes': [{'slot': 'axes', 'kind': 'histogram'}]}, 'signature'),
    ({'consumes': [{'slot': 'axes', 'kind': 'fam:bad kind'}]}, 'signature'),
    ({'basis': {'adds': [], 'passes': ['missing']}}, "passes 'missing'"),
    ({'basis': {'adds': [{'element': 'simulated_acceptance', 'origin_from': 'routine.origin'}], 'passes': []}},
     'origin_from'),
    ({'tools': ['re:\\bTool\\b']}, 'plain tool name'),
    ({'summary': ('Reads table ' + syn.arxiv(683) + ' for the operation.')}, 'R-10'),
    ({'implementation': {'kind': 'command', 'module': 'ravel.workflow.no_such_module'}}, 'does not resolve'),
    ({'produces': [{'slot': 'p', 'kind': 'table'}, {'slot': 'p', 'kind': 'figure'}]}, 'duplicate produces'),
])
def test_nonconforming_entries_are_refused(changes, needle):
    errors = sc.entry_errors('ex-op', _entry(**changes))
    assert errors and any(needle in e for e in errors), errors


def test_science_mode_entry_must_name_its_mode_and_adapter_module():
    entry = copy.deepcopy(REGISTRY['quantities'])
    assert sc.entry_errors('quantities', entry) == []
    entry['implementation']['mode'] = 'other'
    assert any('names its own mode' in e for e in sc.entry_errors('quantities', entry))
    entry = copy.deepcopy(REGISTRY['quantities'])
    entry['implementation']['module'] = 'ravel.physics.measurement'
    assert any('differs from the adapter' in e for e in sc.entry_errors('quantities', entry))
    assert any('no registered science mode' in e for e in sc.entry_errors('not-a-mode', _entry(
        implementation={'kind': 'science-mode', 'mode': 'not-a-mode', 'module': 'ravel.physics.quantities'})))


def test_a_registered_mode_without_a_signature_is_reported():
    document = copy.deepcopy(rp._signature_document())
    del document['operations']['quantities']
    assert 'quantities: registered mode has no operation signature' in sc.conformance(document)


def test_candidate_rows_from_another_stream_are_checked_through_the_seam(tmp_path, capsys):
    good, bad = tmp_path / 'good.json', tmp_path / 'bad.json'
    good.write_text(json.dumps({'ex-op': _entry()}))
    bad.write_text(json.dumps({'ex-op': _entry(produces=[])}))
    assert sc.main(['--entries', str(good)]) == 0
    assert sc.main(['--entries', str(bad)]) == 1
    assert 'produces at least one artifact' in capsys.readouterr().out


# --------------------------------------------------------------------------- witnesses and adapter outputs
GOOD = {
    'binned_values': {'edges': [0, 1, 2], 'values': [3.0, None]},
    'table': {'rows': [[1, 2]]},
    'scalar': {'value': 1.5, 'unit': 'pb'},
    'inference': {'limits': {'observed': 1.2}},
    'statistical_model': {'channels': []},
    'event_sample': {'files': ['events.lhe.gz'], 'format': 'lhe'},
    'selection': {'cuts': ['n_jets >= 2']},
    'cutflow': {'steps': [{'name': 'all', 'count': 10}]},
    'expression': {'expression': 'a*x**2'},
    'parameter_point': {'parameters': {'axis_a': 1.0}},
    'model': {'format': 'ufo', 'path': 'model'},
    'figure': {'path': 'figure.pdf'},
    'document': {'text': 'report'},
}
BAD = {
    'binned_values': {'edges': [0, 2, 1], 'values': [1, 2]},
    'table': {'value': 1},
    'scalar': {'value': float('nan')},
    'inference': {'note': 'no result'},
    'statistical_model': {'bins': []},
    'event_sample': {'files': []},
    'selection': {'note': 'nothing'},
    'cutflow': {'steps': [{'count': 1}]},
    'expression': {'expression': ' '},
    'parameter_point': {'parameters': {}},
    'model': {'note': 'x'},
    'figure': {'caption': 'x'},
    'document': {'note': 'x'},
}


@pytest.mark.parametrize('kind', sorted(GOOD))
def test_witness_accepts_its_kind_and_refuses_a_malformed_artifact(kind):
    assert sc.witness(kind, GOOD[kind]) == []
    assert sc.witness(kind, BAD[kind])


def test_witness_reads_paths_and_namespaced_kinds(tmp_path):
    assert sc.witness('figure', Path('out/figure.pdf')) == []
    assert sc.witness('event_sample', Path('events.hepmc.gz')) == []
    assert sc.witness('figure', Path('out/figure.txt'))
    ufo = tmp_path / 'ufo'
    ufo.mkdir()
    assert sc.witness('model', ufo)
    (ufo / 'particles.py').write_text('')
    assert sc.witness('model', ufo) == []
    assert sc.witness('fam:store', {'kind': 'fam:store'}) == []
    assert sc.witness('fam:store', {'kind': 'other:store'})
    assert sc.witness('histogram', {'edges': [0, 1], 'values': [1]})


def test_adapter_outputs_are_checked_against_the_declared_kinds():
    good = {'significance': {'significance': 2.1, 'level': 'expected'}}
    assert sc.output_errors('asimov-sensitivity', good) == []
    assert any('produced nothing' in e for e in sc.output_errors('asimov-sensitivity', {}))
    assert any('does not meet' in e for e in sc.output_errors(
        'asimov-sensitivity', {'significance': {'significance': 2.1, 'level': 'observed'}}))
    assert any('declares no produced slot' in e for e in sc.output_errors(
        'asimov-sensitivity', dict(good, extra={'text': 'x'})))
    assert any('an inference names its result' in e for e in sc.output_errors(
        'asimov-sensitivity', {'significance': {'level': 'expected'}}))
