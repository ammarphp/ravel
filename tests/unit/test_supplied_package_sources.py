"""Controls that read the shipped analysis packages (src/ravel/data/analysis_packages/) directly.

The ordinary planner, join and package controls run with synthetic packages; these use the shipped ones."""
import copy
import gzip
import json
from pathlib import Path

import pytest

from ravel.physics import compressed_validation
from ravel.physics import compressed_validation as validation
from ravel.physics import native_pipeline as pipeline
from ravel.physics import stau_adapter
from ravel.physics import truth_reco_response as response
from source_record_fixtures import TRACE_PRODUCER, cutflow
from test_native_dispatch import configuration
from test_trace_package_planning import _trace_configuration, _with_definition
from test_truth_reco_response import analyze, event, join


def test_native_trace_flags_and_all_reviewed_inputs_are_explicit(tmp_path):
    from source_record_fixtures import cutflow
    binding,value=cutflow(tmp_path,native=True)
    planned=validation.native_plan_inputs(binding,tmp_path,TRACE_PRODUCER)
    assert planned['arguments']==['--validation-definition',binding['path'],'--validation-definition-sha256',binding['sha256']]
    paths={str(path) for path in planned['inputs']}
    assert binding['path'] in paths
    assert all(pin['path'] in paths for pin in value['sources'].values())
    assert all(pin['path'] in paths for pin in value['review']['evidence'])


def test_native_definition_cannot_claim_a_different_producer(tmp_path):
    from source_record_fixtures import cutflow
    binding,_=cutflow(tmp_path,native=False)
    with pytest.raises(ValueError) as error:validation.native_plan_inputs(binding,tmp_path,TRACE_PRODUCER)
    assert error.value.reason=='source_scope_mismatch'


def test_trace_definition_must_bind_the_selected_package_bytes(tmp_path):
    config = _trace_configuration(tmp_path)
    (tmp_path / 'other').mkdir()
    binding, _ = cutflow(tmp_path / 'other', native=True)  # bound to a different producer
    with pytest.raises(ValueError) as error:
        pipeline.build_execution_plan(tmp_path, _with_definition(config, binding))
    assert error.value.reason == 'source_scope_mismatch'


def test_package_without_a_trace_output_refuses_a_supplied_definition(tmp_path):
    config = configuration(tmp_path)  # its counting package declares no trace output
    (tmp_path / 'definition').mkdir()
    config = _with_definition(config, cutflow(tmp_path / 'definition', native=True)[0])
    with pytest.raises(ValueError, match='cutflow_definition'):
        pipeline.build_execution_plan(tmp_path, config)


def native_fixture(tmp_path, mutation=None):
    original, converted, converter = [tmp_path/name for name in ('input.root','native.root','converter.py')]
    for path in (original,converted,converter): path.write_bytes(path.name.encode())
    receipt = {'sources':[response.fingerprint(original),response.fingerprint(converter)],
               'output':response.fingerprint(converted), 'scale_pb_per_weight': .25,
               'schema_version':1, 'luminosity_applied':False,
               'raw':{'n_events':1,'sumw':1.,'sumw2':1.,'negative_weights':0},
               'normalized':{'n_events':1,'sumw':.25,'sumw2':.0625,'negative_weights':0}}
    receipt_path = tmp_path/'native.root.normalization.json'
    receipt_path.write_text(json.dumps(receipt))
    native_rows = [{'event_id':41, 'weight_pb':.25}]
    from source_record_fixtures import cutflow
    definition=compressed_validation.bind(cutflow(tmp_path,native=True)[0])
    rows = [definition.new_event(41,.25)]
    metadata = {'input_events':1, 'input_sha256':response.fingerprint(converted)['sha256'],
                'selection_source_sha256':response.fingerprint(__import__('analysis_package_fixtures').selected_source('selection-a'))['sha256'],
                'analysis_package':__import__('analysis_package_fixtures').manifest_pin('selection-a'),
                'diagnostic_source_sha256':response.fingerprint(compressed_validation.__file__)['sha256']}
    if mutation == 'trace_hash': metadata['input_sha256'] = '0'*64
    elif mutation == 'native_id': native_rows[0]['event_id'] = 0
    elif mutation == 'weight': rows[0]['weight_pb'] = .4
    elif mutation == 'count': metadata['input_events'] = 2
    elif mutation == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    elif mutation == 'artifact': original.write_text('changed')
    elif mutation == 'boolean_count': metadata['input_events'] = True
    elif mutation == 'source_hash': metadata['selection_source_sha256'] = '0'*64
    elif mutation == 'membership':
        rows[0]['predicates']['two_signal_leptons'] = False
        rows[0]['accepted_regions'] = ['SR_S_high_eMT2a']
    elif mutation in ('schema','luminosity','moments'):
        if mutation == 'schema': receipt['schema_version'] = 999
        elif mutation == 'luminosity': receipt['luminosity_applied'] = True
        else: receipt['normalized']['sumw2'] *= 2
        receipt_path.write_text(json.dumps(receipt))
    trace = tmp_path/'trace.gz'
    # Write directly so malformed traces can be tested rather than caught by the producer.
    with gzip.open(trace,'wt') as stream:
        stream.write(json.dumps(dict(kind='header',schema_version=1,level='reco',weight_unit='pb',metadata=metadata,cutflow_definition=definition.pin))+'\n')
        for row in rows: stream.write(json.dumps(row)+'\n')
    return original, converted, trace, native_rows


def test_offset_event_number_join_and_artifact_binding(tmp_path):
    original, converted, trace, rows = native_fixture(tmp_path)
    joined, scale, _, _ = join(original,converted,trace,native_rows=rows)
    row = analyze(event(),native=joined[41])
    assert scale == .25
    assert row['source_entry'] == 0 and row['delphes_event_number'] == row['native_event_id'] == 41
    assert row['native']['predicates']['trigger'] is None


@pytest.mark.parametrize('mutation', ['trace_hash','native_id','weight','count','duplicate','artifact',
                                    'boolean_count','source_hash','membership','schema','luminosity','moments'])
def test_join_rejects_mismatches(tmp_path, mutation):
    original, converted, trace, rows = native_fixture(tmp_path,mutation)
    with pytest.raises(ValueError): join(original,converted,trace,native_rows=rows)


def test_projection_population_changes_all_supplied_contract_dimensions(tmp_path, monkeypatch):
    import json
    from test_stau_adapter import contract, record
    from analysis_package_fixtures import selected_manifest
    monkeypatch.setenv('RAVEL_ANALYSIS_PACKAGE', str(selected_manifest('selection-d')))
    from ravel.physics.stau_adapter import project_contract
    from ravel.physics.analysis_packages import PackageInputError
    a = {'study_id': 'ANA-0001', 'parameter_points': [{'parameters': {'axis-a': 1}, 'dataset': 'first',
         'document': contract({'nominal': 1})}], 'datasets': {'first': [record('a', 1)]},
         'output': {'format': 'json', 'path': str(tmp_path / 'projection.json')}}
    b = {'study_id': 'ANA-0002', 'parameter_points': [
         {'parameters': {'axis-b': 2, 'axis-c': 3}, 'dataset': 'second', 'document': contract({'nominal': 2})},
         {'parameters': {'axis-b': 5, 'axis-c': 7}, 'dataset': 'third', 'document': contract({'nominal': 1})}],
         'datasets': {'second': [record('b', 1), record('c', 1, 'high')], 'third': [record('d', 1, 'rejected')]},
         'output': {'format': 'jsonl', 'path': str(tmp_path / 'projection.jsonl')}}
    first, second = project_contract(a), project_contract(b)
    assert first['study_id'] == 'ANA-0001' and len(first['points']) == 1
    assert second['study_id'] == 'ANA-0002' and len(second['points']) == 2
    assert [row['parameters'] for row in second['points']] == [row['parameters'] for row in b['parameter_points']]
    assert [row['prediction']['events'] for row in second['points']] == [2, 1]
    assert second['points'][1]['prediction']['predictions']['nominal']['yields'] == [0.] * 5
    assert json.loads(Path(a['output']['path']).read_text()) == first
    assert len(Path(b['output']['path']).read_text().splitlines()) == 2
    del a['datasets']
    with pytest.raises(PackageInputError) as caught:
        project_contract(a)
    assert caught.value.reason == 'missing_datasets'


def test_selected_package_attribute_probe_returns_default_for_absent_hook(monkeypatch):
    from analysis_package_fixtures import selected_manifest
    monkeypatch.setenv('RAVEL_ANALYSIS_PACKAGE', str(selected_manifest('selection-d')))
    assert getattr(stau_adapter, 'helper_declaration', None) is None
    assert stau_adapter.CHANNELS
