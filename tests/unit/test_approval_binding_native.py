"""Native-route byte binding: a changed approved configuration or card refuses execution."""
import pytest

from ravel.physics import native_pipeline as pipeline
from test_native_dispatch import approve_fixture, configuration, synthetic_build


@pytest.fixture(autouse=True)
def supplied_build(tmp_path, monkeypatch):
    # The approved plan binds a synthetic build root, never a host installation.
    return synthetic_build(tmp_path, monkeypatch)


@pytest.mark.parametrize('rel', ['config.toml', 'cards/run.dat', 'cards/shower.cfg', 'cards/detector.tcl'],
                         ids=['native-toml', 'generator-card', 'shower-cfg', 'detector-tcl'])
def test_changed_native_input_refuses_execution_approval(tmp_path, rel):
    plan = pipeline.build_execution_plan(tmp_path, configuration(tmp_path))
    approve_fixture(plan)
    pipeline.verify_execution_approval(plan)
    path = tmp_path / rel
    path.write_text(path.read_text() + '# unapproved revision\n')
    with pytest.raises(ValueError, match=rel):
        pipeline.verify_execution_approval(plan)


def test_native_receipted_preparation_amendment_and_hand_revert(tmp_path):
    """Use the native renderer and real receipts, without launching a tool."""
    from ravel.workflow import execution, launch_authorization

    def prepare(plan):
        stage = next(s for s in plan['stages'] if s['stage'] == 'prepare')
        spec = execution.plan_stage(tmp_path, stage['stage'], stage['command'],
                                    stage['inputs'], stage['outputs'], [], str(tmp_path))
        record = execution.begin_attempt(tmp_path, stage['stage'], spec, 'logs/prepare.log')
        # The real supervisor checks approval after archiving the old cards.
        assert pipeline.verify_execution_approval(plan)
        pipeline.prepare(plan)
        assert execution.finish_attempt(tmp_path, record, 0) == 0

    config = configuration(tmp_path)
    plan = pipeline.build_execution_plan(tmp_path, config)
    approve_fixture(plan)
    prepare(plan)
    rendered = tmp_path / 'output/run_card.dat'
    old = rendered.read_bytes()
    source = tmp_path / 'cards/run.dat'
    source.write_text(source.read_text() + '# requested revision\n')
    revised = pipeline.build_execution_plan(tmp_path, config)
    approve_fixture(revised)
    assert pipeline.verify_execution_approval(revised)
    prepare(revised)
    assert rendered.read_bytes() != old
    assert pipeline.verify_execution_approval(revised)
    rendered.write_bytes(old)
    with pytest.raises(ValueError, match='output/run_card.dat'):
        launch_authorization._capture(tmp_path, 'smoke')
