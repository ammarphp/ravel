"""The scoped CHECK-IN 1 carries the sections of the trusted registry; nothing is executed."""
from copy import deepcopy

from ravel.cli import main
from ravel.validation import validate_checkin
from ravel.workflow import recipe_ledger, scoped
from ravel.workflow.state_io import atomic_json, read_json


def counting_spec():
    return {'schema_version': 1, 'mode': 'likelihood', 'source': 'Synthetic one-bin counting control',
            'assumptions': ['One synthetic bin with a Poisson background constraint'],
            'max_seconds': 60, 'approval_mode': 'scripted_yes',
            'likelihood': {'counting': {'observed': 10, 'background': 9, 'background_uncertainty': 2, 'signal': 1},
                           'poi_cap': 64, 'normalization': {'kind': 'signal_events', 'luminosity_fb': 1}}}


def planned(tmp_path):
    rd = tmp_path / 'run'
    assert main(['initiate', '--prompt', 'Compute a likelihood-only control for the supplied counting model.',
                 '--out', str(rd)]) == 0
    source = tmp_path / 'spec.json'
    atomic_json(source, counting_spec())
    scoped.plan(rd, source)
    return rd


def test_scoped_checkin1_carries_the_registered_recipe_ledger(tmp_path):
    rd = planned(tmp_path)
    checkin = read_json(rd / 'inputs/checkin1.json')
    section = checkin['sections']['recipe_ledger']
    assert section['kind'] == 'recipe-ledger' and section['rows']
    assert section == recipe_ledger.build(rd, checkin=checkin)
    # The planner used the registry itself: composing again changes nothing.
    assert validate_checkin.with_registered_sections(checkin, str(rd)) == checkin
    assert validate_checkin.validate(checkin, base_dir=str(rd)) == []


def test_scoped_checkin1_without_its_recipe_ledger_is_refused(tmp_path):
    rd = planned(tmp_path)
    checkin = read_json(rd / 'inputs/checkin1.json')
    stripped = deepcopy(checkin)
    del stripped['sections']['recipe_ledger']
    errors = validate_checkin.validate(stripped, base_dir=str(rd))
    assert 'CHECK-IN 1 missing or changed registered section (recipe_ledger)' in errors
    assert 'CHECK-IN 1 recipe ledger missing or changed' in errors
    changed = deepcopy(checkin)
    changed['sections']['recipe_ledger']['rows'][0]['requested'] = 'changed after planning'
    assert 'CHECK-IN 1 recipe ledger missing or changed' in validate_checkin.validate(changed, base_dir=str(rd))
