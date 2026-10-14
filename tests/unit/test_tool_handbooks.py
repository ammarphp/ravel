"""Tool-handbook contract checks on tiny own fixtures, plus the packaged handbooks."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

import pytest

from ravel.validation import check_agent_surface as surface, tool_handbooks as hb

REPO = Path(__file__).resolve().parents[2]
MODES = set(json.loads((REPO / 'src/ravel/data/mode_descriptors.json').read_text())['modes'])
PINS = {'madgraph': ('"madgraph": "2.9.27 / eb76"', {'2.9.27'})}

SKILL = '''---
name: {name}
description: Use when testing the handbook contract checker with a small own fixture skill and nothing else.
license: Apache-2.0
compatibility: Fixture only.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "model-events"
  upstream-version: "madgraph:madgraph=2.9.27"
  ravel-parameters: "model-events.generation.events"
  last-reviewed: "2026-10-11"
{extra}---

# Fixture

Set `model-events.generation.events`.

```python ravel-block=fixture-block
VALUE = 1
```

## Pitfalls

- A card mismatch. Caught by `ravel.physics.model_events.check_cards`.
- Advisory: something RAVEL does not check.
'''

REVIEW = {'skill': 'fixture', 'reviewed': '2026-10-11', 'reviewer': 'machine', 'sources': ['own fixture'],
          'tested_versions': {}, 'executable_blocks': ['fixture-block'], 'illustrative_blocks': [], 'limits': []}


def make(tmp_path, name='fixture', *, extra='', body=None, review=None):
    root = tmp_path / 'tools' / name
    (root / 'references').mkdir(parents=True)
    (root / 'SKILL.md').write_text(body if body is not None else SKILL.format(name=name, extra=extra))
    record = dict(REVIEW, skill=name, **(review or {}))
    (root / 'references/review.md').write_text('# Review\n\n```json\n' + json.dumps(record) + '\n```\n')
    return root


def check(root, **kwargs):
    fields, operations = hb.load_operation_fields()
    options = dict(modes=MODES, fields=fields, operations=operations, manifest_pins_=PINS, python_pins_={})
    options.update(kwargs)
    return hb.check_handbook(root, **options)


def test_fixture_handbook_passes(tmp_path):
    assert check(make(tmp_path)) == ([], [])


def test_extra_top_level_key_fails(tmp_path):
    errors, _ = check(make(tmp_path, extra='when_to_use: always\n'))
    assert any('outside the closed set' in e and 'when_to_use' in e for e in errors)


def test_duplicate_and_non_string_metadata_fail(tmp_path):
    text = SKILL.format(name='fixture', extra='').replace('  last-reviewed: "2026-10-11"\n',
                                                          '  last-reviewed: 2026-10-11\n  ravel-extra: "x"\n')
    errors, _ = check(make(tmp_path, body=text))
    assert any('quoted string' in e for e in errors) and any('ravel-extra' in e for e in errors)
    dup = SKILL.format(name='fixture', extra='license: MIT\n')
    errors, _ = check(make(tmp_path / 'b', body=dup))
    assert errors == ["fixture: duplicate frontmatter key 'license'"]


def test_pitfall_without_check_or_advisory_fails(tmp_path):
    text = SKILL.format(name='fixture', extra='').replace('- Advisory: something RAVEL does not check.',
                                                         '- Something nobody checks.')
    errors, _ = check(make(tmp_path, body=text))
    assert any('not labelled Advisory' in e for e in errors)


def test_pitfall_naming_a_missing_check_fails(tmp_path):
    text = SKILL.format(name='fixture', extra='').replace('model_events.check_cards', 'model_events.no_such_check')
    errors, _ = check(make(tmp_path, body=text))
    assert any('no_such_check' in e for e in errors)


def test_unlisted_or_unknown_parameter_fails(tmp_path):
    text = SKILL.format(name='fixture', extra='').replace('Set `model-events.generation.events`.',
                                                         'Set `model-events.generation.events` and `model-events.generation.seed`.')
    errors, _ = check(make(tmp_path, body=text))
    assert any("'model-events.generation.seed' without listing" in e for e in errors)
    text = SKILL.format(name='fixture', extra='').replace('ravel-parameters: "model-events.generation.events"',
                                                         'ravel-parameters: "model-events.generation.nevents"')
    errors, _ = check(make(tmp_path / 'b', body=text))
    assert any('not an operation.field' in e for e in errors)


def test_version_mismatch_fails_unless_marked(tmp_path):
    text = SKILL.format(name='fixture', extra='').replace('madgraph:madgraph=2.9.27', 'madgraph:madgraph=3.7.0')
    errors, _ = check(make(tmp_path, body=text))
    assert any('does not match the toolchain' in e for e in errors)
    marked = text.replace('  last-reviewed:', '  ravel-version-unpinned: "madgraph:madgraph=3.7.0"\n  last-reviewed:')
    assert check(make(tmp_path / 'b', body=marked)) == ([], [])
    stale_mark = SKILL.format(name='fixture', extra='').replace(
        '  last-reviewed:', '  ravel-version-unpinned: "madgraph:madgraph=2.9.27"\n  last-reviewed:')
    errors, notes = check(make(tmp_path / 'c', body=stale_mark))
    assert errors == [] and notes and 'pinned now' in notes[0]


def test_python_pins_are_checked(tmp_path):
    text = SKILL.format(name='fixture', extra='').replace('madgraph:madgraph=2.9.27', 'pypi:pyhf=0.7.6')
    root = make(tmp_path, body=text)
    assert check(root, python_pins_={'pyhf': '0.7.6'}) == ([], [])
    errors, _ = check(root, python_pins_={'pyhf': '0.7.5'})
    assert any('pyproject pins 0.7.5' in e for e in errors)


def test_token_budget_uses_the_line_proxy(tmp_path):
    root = make(tmp_path)
    cost = hb.estimate_tokens((root / 'SKILL.md').read_text())
    assert cost == sum(-(-len(line) // 4) + 1 for line in (root / 'SKILL.md').read_text().splitlines())
    errors, _ = check(root, budget=cost - 1)
    assert any('over the' in e and 'line proxy' in e for e in errors)


def test_review_record_must_list_every_block(tmp_path):
    errors, _ = check(make(tmp_path, review={'executable_blocks': []}))
    assert any("block 'fixture-block' is not listed" in e for e in errors)
    errors, _ = check(make(tmp_path / 'b', review={'illustrative_blocks': ['ghost']}))
    assert any("lists block 'ghost'" in e for e in errors)
    errors, _ = check(make(tmp_path / 'c'), tests_root=tmp_path / 'no-tests')
    assert any('has no test running' in e for e in errors)


def test_stale_or_incomplete_installed_copy_fails(tmp_path):
    root = make(tmp_path)
    project = tmp_path / 'project/.claude/skills'
    project.mkdir(parents=True)
    shutil.copytree(root, project / 'fixture')
    assert hb.check_installed([project], root.parent) == []
    (project / 'fixture/SKILL.md').write_text('old text\n')
    (project / 'fixture/references/review.md').unlink()
    (project / 'fixture/extra.md').write_text('x')
    errors = hb.check_installed([project], root.parent)
    assert any('is stale' in e for e in errors) and any('lacks references/review.md' in e for e in errors)
    assert any('carries extra.md' in e for e in errors)


def test_collision_lint_reports_overlapping_descriptions(tmp_path):
    a, b = make(tmp_path, 'alpha'), make(tmp_path, 'beta')
    found = hb.collisions([a / 'SKILL.md', b / 'SKILL.md'])
    assert found and found[0][:2] == ('alpha', 'beta')


def test_manifest_pins_read_both_shapes():
    v1 = {'groups': [{'id': 'recast-base', 'version_contract': {'delphes': '3.5.1'}}]}
    v2 = {'groups': [{'id': 'recast-base', 'title': 'ROOT 6.40, FastJet 3.5.1 and Delphes 3.5.1',
                      'checks': [{'id': 'delphes', 'kind': 'executable'}]}]}
    meta = {'upstream-version': 'recast-base:delphes=3.5.1'}
    for manifest in (v1, v2):
        assert hb.check_versions(meta, manifest_pins_=hb.manifest_pins(manifest)) == ([], [])
    errors, _ = hb.check_versions({'upstream-version': 'recast-base:delphes=3.6.0'},
                                  manifest_pins_=hb.manifest_pins(v2))
    assert errors


def test_doctor_reports_give_the_unavailable_ledger(tmp_path):
    make(tmp_path)
    ravel_doctor = {'kind': 'ravel-doctor-report', 'groups': [{'group': 'madgraph', 'status': 'missing'}]}
    assert hb.availability(ravel_doctor, tmp_path / 'tools')['fixture']['status'] == 'unavailable'
    ready = {'kind': 'ravel-doctor-report', 'groups': [{'group': 'madgraph', 'status': 'ready'}]}
    assert hb.availability(ready, tmp_path / 'tools')['fixture']['status'] == 'available'
    native = {'schema_version': 1, 'checks': [{'name': 'madgraph_source', 'status': 'fail'},
                                              {'name': 'mg5_make', 'status': 'pass'}]}
    assert hb.availability(native, tmp_path / 'tools')['fixture']['status'] == 'unavailable'
    assert hb.availability({'checks': []}, tmp_path / 'tools')['fixture']['status'] == 'unknown'
    with pytest.raises(ValueError):
        hb.group_status({'other': 1})


def test_live_doctor_prefers_ravel_doctor_and_falls_back(monkeypatch):
    from ravel.validation import native_doctor
    monkeypatch.setattr(native_doctor, 'diagnose', lambda: {'checks': [], 'fallback': True})
    monkeypatch.setitem(sys.modules, 'ravel.setup', None)       # installer stream absent
    assert hb.doctor_report()['fallback'] is True

    class Doctor:
        def __init__(self, *args):
            self.args = args

        def report(self, groups):
            return {'kind': 'ravel-doctor-report', 'groups': [{'group': g, 'status': 'ready'} for g in groups]}

    doctor = type(sys)('ravel.setup.doctor')
    doctor.Doctor, doctor.resolve_prefix = Doctor, lambda repo, prefix, env: Path('/prefix')
    doctor.select_groups = lambda manifest: [g['id'] for g in manifest['groups']]
    manifest = type(sys)('ravel.setup.manifest')
    manifest.repo_root = lambda: REPO
    manifest.load = lambda root: ({'groups': [{'id': 'madgraph'}]}, {})
    manifest.detect_platform = lambda: 'macos-arm64'
    package = type(sys)('ravel.setup')
    package.doctor, package.manifest = doctor, manifest
    monkeypatch.setitem(sys.modules, 'ravel.setup', package)
    monkeypatch.setitem(sys.modules, 'ravel.setup.doctor', doctor)
    monkeypatch.setitem(sys.modules, 'ravel.setup.manifest', manifest)
    report = hb.doctor_report()
    assert hb.group_status(report) == {'madgraph': 'ready'}


def test_packaged_handbooks_pass_the_contract():
    errors, notes = surface.check_handbooks(str(REPO))
    assert errors == []
    names = {p.name for p in hb.handbooks()}
    assert {'madgraph-launch', 'madgraph-model-import', 'feynrules', 'lhapdf-pdf-sets', 'pythia-shower-cards',
            'delphes-cards', 'rivet-routine', 'ma5-expert', 'smodels-input', 'pyhf-workspace-patching',
            'hepdata-retrieval'} <= names
    for name in names:
        assert (REPO / 'tests/skills' / name).is_dir()


def test_handbooks_ship_in_the_wheel():
    from hatchling.builders.wheel import WheelBuilder
    shipped = {f.distribution_path for f in WheelBuilder(str(REPO)).recurse_included_files()}
    packaged = {('ravel/data/skills/tools/' + p.name + '/' + rel)
                for p in hb.handbooks() for rel in hb.handbook_files(p)}
    assert packaged and packaged <= shipped
    assert 'ravel/data/skills/operation-fields.json' in shipped


def test_operation_fields_are_required_by_their_validators(tmp_path):
    sys.path.insert(0, str(REPO / 'tests/unit'))
    try:
        from test_model_events import config
    finally:
        sys.path.remove(str(REPO / 'tests/unit'))
    from ravel.physics import model_events
    data = json.loads(hb.operation_fields_path().read_text())
    row = data['operations']['model-events']
    assert row['validator'] == 'ravel.physics.model_events.validate_config'
    base = config(tmp_path / 'cfg', 'mlm', variations=True, decay=True)
    model_events.validate_config(deepcopy(base))
    for field in row['fields']:
        c = deepcopy(base)
        *path, last = field.split('.')
        node = c
        for key in path:
            node = node[key]
        del node[last]
        with pytest.raises((ValueError, KeyError)):
            model_events.validate_config(c)


def test_agent_surface_reports_handbook_and_installed_results(tmp_path, monkeypatch, capsys):
    from ravel.paths import repository_root
    monkeypatch.setattr(surface, 'require_repository_root', lambda: Path(REPO))
    for name in ('check_fork', 'check_roles', 'check_knowledge', 'check_refs', 'check_skills', 'check_mirror',
                 'check_readiness', 'check_stepcount', 'check_hygiene'):
        monkeypatch.setattr(surface, name, lambda *a, **k: [])
    monkeypatch.setattr(surface, 'check_dirmap', lambda root: ([], []))
    installed = tmp_path / 'skills'
    shutil.copytree(REPO / surface.HANDBOOK_ROOT / 'delphes-cards', installed / 'delphes-cards')
    (installed / 'delphes-cards/SKILL.md').write_text('stale\n')
    report = tmp_path / 'doctor.json'
    report.write_text(json.dumps({'kind': 'ravel-doctor-report', 'groups': [{'group': 'recast-base', 'status': 'ready'}]}))
    monkeypatch.setattr(sys, 'argv', ['check_agent_surface', '--installed', str(installed),
                                      '--doctor-report', str(report)])
    with pytest.raises(SystemExit) as exit_:
        surface.main()
    out = capsys.readouterr().out
    assert exit_.value.code == 1
    assert '[PASS] handbooks' in out and '[FAIL] installed' in out and 'is stale' in out
    assert 'delphes-cards: available (recast-base ready)' in out
    assert repository_root() is not None
