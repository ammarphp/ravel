"""A package that declares an event trace binds a supplied cutflow definition to its own selection bytes.

Planning only: no generation, shower, detector or analysis process runs."""
import pytest

from ravel.physics import native_pipeline as pipeline
from analysis_package_fixtures import native_package
from source_record_fixtures import cutflow
from test_native_dispatch import configuration


def _trace_configuration(tmp_path):
    """The ordinary fictional native configuration, with its package declaring the trace output."""
    config = configuration(tmp_path)
    native_package(tmp_path / 'packages' / 'fictional', 'FictionalRoutine700', ['SRlow'], models=['c1n2-wz'],
                   helper_outputs=[pipeline.TRACE_OUTPUT])
    return config


def _with_definition(config, definition):
    lines = config.read_text().splitlines()
    lines.insert(lines.index('[ravel.native]') + 1,
                 f'cutflow_definition = {{ path = "{definition["path"]}", sha256 = "{definition["sha256"]}" }}')
    config.write_text('\n'.join(lines) + '\n')
    return config


def test_trace_package_without_a_definition_is_refused(tmp_path):
    with pytest.raises(ValueError) as error:
        pipeline.build_execution_plan(tmp_path, _trace_configuration(tmp_path))
    assert error.value.reason == 'missing_cutflow_definition'


def test_trace_definition_joins_the_analysis_stage_and_its_census(tmp_path):
    config = _trace_configuration(tmp_path)
    (tmp_path / 'definition').mkdir()
    binding, value = cutflow(tmp_path / 'definition', native=tmp_path / 'packages' / 'fictional' / 'selection.py')
    plan = pipeline.build_execution_plan(tmp_path, _with_definition(config, binding))
    stage = next(s for s in plan['stages'] if s['stage'] == 'simpleanalysis')
    flags = stage['command'][stage['command'].index('--validation-definition'):][:4]
    assert flags == ['--validation-definition', binding['path'], '--validation-definition-sha256', binding['sha256']]
    assert any(str(output).endswith(pipeline.TRACE_OUTPUT) for output in stage['outputs'])
    from pathlib import Path
    assert str(Path(binding['path']).resolve()) in {str(Path(p).resolve()) for p in stage['inputs']}
    assert all(str(Path(p['path']).resolve()) in {str(Path(i).resolve()) for i in stage['inputs']}
               for p in value['sources'].values())
