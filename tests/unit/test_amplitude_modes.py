"""Amplitude-basis modes are reachable from the ordinary study lifecycle and the focused CLI."""
import json

import pytest

from amplitude_fixtures import build_store, hypotheses
from shipped_catalogue import shipped_operations
from ravel import cli
from ravel.physics import amplitude_cli
from ravel.workflow import capability_routing, science

ALL_MODES = ('amplitude-integration', 'amplitude-predictions', 'weighted-events', 'amplitude-crosscheck')
MODES = shipped_operations(ALL_MODES)


@pytest.mark.parametrize('mode', MODES)
def test_modes_are_registered_with_ordinary_adapters(mode):
    assert mode in science.MODES and science._new_capability({'mode': mode, 'task': {}})
    module = science.adapter({'mode': mode, 'task': {}})
    assert all(callable(getattr(module, name)) for name in ('validate', 'inputs', 'run'))
    row = next(r for r in capability_routing.catalogue()['operations'] if r['mode'] == mode)
    assert row['module'] == module.__name__ and row['entrypoints'] == ['inputs', 'run', 'validate']


def test_descriptors_route_an_interference_reinterpretation_prompt():
    catalog = capability_routing.catalogue()
    by_mode = {row['mode']: row for row in catalog['operations']}
    prompt = 'Reweight the stored helicity amplitudes to a broad heavy scalar interfering with the continuum and predict the differential cross section.'
    suggested = capability_routing.suggest(prompt, by_mode)
    assert 'amplitude-predictions' in [s['mode'] for s in suggested]


def test_focused_cli_checks_and_writes_a_study_specification(tmp_path, capsys):
    build_store(tmp_path / 'store')
    doc = {'schema_version': 1, 'kind': 'amplitude-predictions', 'store': 'store', 'hypotheses': hypotheses(),
           'reference': 'SM', 'reference_description': 'synthetic reference', 'selection': [],
           'observable': {'name': 'mass_gev', 'label': 'Synthetic mass', 'unit': 'GeV', 'invariant': 's_gev2'},
           'binning': {'edges': [0.0, 300.0, 600.0]}, 'normalization': {'unit': 'fb', 'representation': 'integrated'}}
    (tmp_path / 'doc.json').write_text(json.dumps(doc))
    (tmp_path / 'policy.json').write_text(json.dumps({'policy': {}}))
    assert cli.main(['amplitudes', 'check', '--mode', 'amplitude-predictions', '--input', str(tmp_path / 'doc.json')]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked['compute_authorized'] is False and len(checked['inputs']) == 2 + 2 * 4
    assert cli.main(['amplitudes', 'spec', '--mode', 'amplitude-predictions', '--input', str(tmp_path / 'doc.json'),
                     '--policy', str(tmp_path / 'policy.json'), '--source', 'synthetic store',
                     '--assumption', '1. The stored amplitudes describe the process.', '--out', str(tmp_path / 'spec.json')]) == 0
    spec = json.loads((tmp_path / 'spec.json').read_text())
    assert spec['mode'] == 'amplitude-predictions' and spec['approval_mode'] == 'physicist' and spec['max_attempts'] == 1


@pytest.mark.parametrize('mode', ALL_MODES)
def test_examples_name_their_mode(mode, capsys):
    assert amplitude_cli.main(['example', '--mode', mode]) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == mode
