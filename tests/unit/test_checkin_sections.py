"""Synthetic registered sections bind rendered CHECK-IN content in stable order."""
import json
import sys
from types import SimpleNamespace
import pytest
from ravel.validation import validate_checkin as vc


def document():
    return {'schema_version': 1, 'kind': 'checkin1', 'sections': {
        'i': 'Bounded synthetic study', 'i-b': 'Supplied definitions', 'ii': 'Supplied comparison',
        'iii': {'waypoint': 'Review the bounded witness'}, 'iv': 'One bounded call',
        'v': [{'id': 'F1', 'text': 'Synthetic inputs only'}], 'vi': ['answer', 'ask', 'propose']}}


def test_data_only_section_is_in_stable_checkin_bytes(tmp_path):
    registry = tmp_path / 'sections.json'
    rows = [{'id': 'late', 'order': 20, 'content': {'value': 2}},
            {'id': 'early', 'order': 10, 'content': {'value': 1}}]
    registry.write_text(json.dumps({'schema_version': 1, 'sections': rows}))
    raw = vc.checkin_bytes(document(), registry=registry)
    assert list(json.loads(raw)['sections'])[-2:] == ['early', 'late']
    registry.write_text(json.dumps({'schema_version': 1, 'sections': rows[::-1]}))
    assert vc.checkin_bytes(document(), registry=registry) == raw


def test_registered_section_cannot_be_omitted_or_changed(tmp_path):
    registry = tmp_path / 'sections.json'
    registry.write_text(json.dumps({'schema_version': 1, 'sections': [
        {'id': 'limits', 'order': 1, 'content': {'bound': .25}}]}))
    assert any('limits' in e for e in vc.registered_section_errors(document(), registry=registry))
    rendered = json.loads(vc.checkin_bytes(document(), registry=registry))
    assert vc.registered_section_errors(rendered, registry=registry) == []
    rendered['sections']['limits']['bound'] = .5
    assert any('limits' in e for e in vc.registered_section_errors(rendered, registry=registry))


def test_duplicate_registration_is_refused(tmp_path):
    registry = tmp_path / 'sections.json'
    row = {'id': 'same', 'order': 1, 'content': 'Bounded content'}
    registry.write_text(json.dumps({'schema_version': 1, 'sections': [row, row]}))
    with pytest.raises(ValueError, match='distinct'):
        vc.checkin_bytes(document(), registry=registry)


def test_module_provider_renders_and_validates_without_validator_edit(tmp_path, monkeypatch):
    module = SimpleNamespace(section=lambda context: {'bound': .3},
                             errors=lambda content, context: ['named refusal'] if content != {'bound': .3} else [])
    monkeypatch.setitem(sys.modules, 'ravel.validation.synthetic_section', module)
    registry = tmp_path / 'sections.json'
    registry.write_text(json.dumps({'schema_version': 1, 'sections': [{'id': 'bound', 'order': 5,
        'module': 'ravel.validation.synthetic_section', 'render': 'section', 'validate': 'errors'}]}))
    rendered = json.loads(vc.checkin_bytes(document(), registry=registry))
    assert vc.registered_section_errors(rendered, registry=registry) == []
    rendered['sections']['bound'] = {}
    assert 'named refusal' in vc.registered_section_errors(rendered, registry=registry)


REVIEW_POINTS_ROW = {'id': 'review_points', 'order': 100, 'module': 'ravel.validation.validate_checkin',
                     'render': 'review_points_section'}


def _applicable_registry(tmp_path):
    registry = tmp_path / 'sections.json'
    registry.write_text(json.dumps({'schema_version': 1, 'sections': [REVIEW_POINTS_ROW]}))
    return registry


def test_review_points_one_call_uses_section_seam(tmp_path, monkeypatch):
    calls = []
    def section(context):
        calls.append(context)
        return {'missing_evidence_ids': ['E1']}
    monkeypatch.setitem(sys.modules, 'ravel.workflow.review_points', SimpleNamespace(checkin_section=section))
    rendered = json.loads(vc.checkin_bytes(document(), registry=_applicable_registry(tmp_path)))
    assert rendered['sections']['review_points'] == {'missing_evidence_ids': ['E1']}
    assert len(calls) == 1


def test_review_points_seam_resolves_the_loaded_module_after_a_real_import(tmp_path, monkeypatch):
    import ravel.workflow.review_points  # noqa: F401 -- the package attribute now names the real module
    monkeypatch.setitem(sys.modules, 'ravel.workflow.review_points',
                        SimpleNamespace(checkin_section=lambda context: {'missing_evidence_ids': []}))
    rendered = json.loads(vc.checkin_bytes(document(), registry=_applicable_registry(tmp_path)))
    assert rendered['sections']['review_points'] == {'missing_evidence_ids': []}


def test_inapplicable_registry_row_is_declared_not_inferred(tmp_path, monkeypatch):
    registry = tmp_path / 'sections.json'
    registry.write_text(json.dumps({'schema_version': 1, 'sections': [{**REVIEW_POINTS_ROW, 'applicable': False}]}))
    monkeypatch.setitem(sys.modules, 'ravel.workflow.review_points', SimpleNamespace(approve=lambda rundir: None))
    rendered = json.loads(vc.checkin_bytes(document(), registry=registry))
    assert 'review_points' not in rendered['sections']
    assert vc.registered_section_errors(rendered, registry=registry) == []


def test_applicable_row_with_a_missing_producer_is_refused(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'ravel.workflow.review_points', SimpleNamespace(approve=lambda rundir: None))
    with pytest.raises(ValueError, match='producer'):
        vc.checkin_bytes(document(), registry=_applicable_registry(tmp_path))


def test_review_points_section_failure_is_not_a_handoff(tmp_path, monkeypatch):
    def section(context):
        raise ValueError('synthetic provider failure')
    monkeypatch.setitem(sys.modules, 'ravel.workflow.review_points', SimpleNamespace(checkin_section=section))
    with pytest.raises(ValueError, match='synthetic provider failure'):
        vc.checkin_bytes(document(), registry=_applicable_registry(tmp_path))


def test_science_composer_emits_a_data_registered_section(tmp_path, monkeypatch):
    from ravel.workflow import science, state_io
    registry = tmp_path / 'sections.json'
    state_io.atomic_json(registry, {'schema_version': 1, 'sections': [
        {'id': 'bounds', 'order': 1, 'content': {'max_calls': 1}}]})
    original = vc.section_registry
    monkeypatch.setattr(vc, 'section_registry', lambda path=None: original(registry))
    spec = {'mode': 'quantities', 'source': 'Synthetic records', 'task': {}, 'max_seconds': 5,
            'assumptions': ['Synthetic witness only']}
    checkin = science.make_checkin(spec, 'a' * 64, base=tmp_path)
    target = tmp_path / 'checkin.json'
    state_io.atomic_json(target, checkin)
    assert state_io.read_json(target)['sections']['bounds'] == {'max_calls': 1}
    assert target.read_bytes() == vc.checkin_bytes(checkin, tmp_path)


def test_shipped_review_points_row_matches_its_producer():
    """The registry declares the review-points section inapplicable exactly while its producer is absent."""
    from importlib.resources import files
    from ravel.workflow import review_points
    shipped = json.loads(files('ravel').joinpath('data/checkin/sections.json').read_text())
    row = next(r for r in shipped['sections'] if r['id'] == 'review_points')
    assert row.get('applicable', True) is hasattr(review_points, 'checkin_section')
