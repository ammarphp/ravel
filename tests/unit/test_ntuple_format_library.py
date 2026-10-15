"""Packaged ntuple-format descriptors resolve through the same engine as a supplied one.

Original use: the former built-in format table of the eight earlier ntuple-analysis modules (last at
974985d) answered the recipe checks below. The expected outcomes here were produced by running that implementation
on identical recipes and events, so they are the original behaviour, not a restatement of this one.
Second use: an unrelated recipe and a different public format through ``branch_roles`` by name.
"""
from copy import deepcopy
import json
import pytest
from ravel.physics import columnar_ntuple_recipe as h, columnar_selection as s

CP = 'atlas-cp-nominal-ntuple'
OPEN_DATA = 'atlas-opendata-13tev-ntuple'
PIN = {'path': '/supplied-input-description', 'sha256': '0'*64, 'size': 1}


def base(**changes):
    r = {'schema_version': 1, 'objects': [{'name': 'leptons', 'prefix': 'el', 'selection': 'baseline',
         'pt_min_GeV': 20, 'abs_eta_max': 2.5, 'scale_factors': ['el_recoSF_NOSYS'], 'tagger': None}],
         'overlap_removal': 'standard', 'met': 'Baseline', 'trigger_by_year': {'2018': ['trigPassed_electron']},
         'scalar_scale_factors': ['weight_pileup_NOSYS', 'weight_beamspot'],
         'sf_applicability': [{'subject': 'x', 'source': PIN,
                               'treatment': 'declared_conditional_not_calibration_qualification', 'limitations': ['l']}],
         'regions': [{'id': 'SR', 'role': 'signal', 'counts': {'leptons': [1, None]}, 'ht': None, 'met_GeV': [50, None]}],
         'uncertainty_policy': 'nominal_only_missing_variations_explicit', 'branch_roles': CP}
    r.update(changes)
    return r


TAGGER = {'tagged': 'largeRjet_T_tagged_NOSYS', 'valid': 'largeRjet_T_validKinRange_NOSYS', 'score': None, 'mass': None}


def mutate(name):
    r = base()
    o = r['objects'][0]
    if name == 'year2023_beamspot': r['trigger_by_year'] = {'2023': ['trigPassed_electron']}
    elif name == 'year2031': r['trigger_by_year'] = {'2031': ['trigPassed_electron']}
    elif name == 'year2023_pileup_only':
        r['trigger_by_year'] = {'2023': ['trigPassed_electron']}; r['scalar_scale_factors'] = ['weight_pileup_NOSYS']
    elif name == 'unknown_prefix': o['prefix'] = 'xx'
    elif name == 'signal_with_or': o['selection'] = 'signal'
    elif name == 'signal_no_or': r.update(overlap_removal='none', met='Signal'); o['selection'] = 'signal'
    elif name == 'jet_baseline': o.update(prefix='jet', selection='baseline', scale_factors=[])
    elif name == 'jet_stored': o.update(prefix='jet', selection='stored', scale_factors=[])
    elif name == 'largeR_tagged':
        r['overlap_removal'] = 'largeR'; o.update(prefix='largeRjet', selection='stored', scale_factors=[], tagger=dict(TAGGER))
    elif name == 'lepton_tagger': r['overlap_removal'] = 'largeR'; o['tagger'] = dict(TAGGER)
    elif name == 'bad_valid_name':
        r['overlap_removal'] = 'largeR'
        o.update(prefix='largeRjet', selection='stored', scale_factors=[], tagger=dict(TAGGER, valid='largeRjet_T_validFlag'))
    return r


# Outcome of the former implementation on exactly these recipes (production run of 974985d).
ORIGINAL_OUTCOMES = {'base': 'ok', 'year2023_beamspot': 'refused', 'year2031': 'refused',
                     'year2023_pileup_only': 'ok', 'unknown_prefix': 'refused', 'signal_with_or': 'refused',
                     'signal_no_or': 'ok', 'jet_baseline': 'refused', 'jet_stored': 'ok', 'largeR_tagged': 'ok',
                     'lepton_tagger': 'refused', 'bad_valid_name': 'refused'}


def test_library_lists_and_resolves_packaged_descriptors():
    assert {CP, OPEN_DATA} <= set(h.library_names())
    for name in h.library_names():
        doc = h.library_roles(name)
        assert doc['name'] == name and doc['source'].strip()
        assert h.branch_roles(name) == doc
    with pytest.raises(ValueError, match='available'):
        h.library_roles('not-a-packaged-format')
    with pytest.raises(ValueError):
        h.library_roles('../columnar-format')


def test_named_descriptor_is_resolved_into_the_recipe_so_its_digest_covers_it():
    checked = h.validate_recipe(base())
    assert checked['branch_roles'] == h.library_roles(CP)
    assert h.validate_recipe(checked) == checked
    explicit = base(branch_roles=h.library_roles(CP))
    assert h.validate_recipe(explicit) == checked


@pytest.mark.parametrize('case', sorted(ORIGINAL_OUTCOMES))
def test_original_recipe_checks_match_the_former_implementation(case):
    r = mutate(case) if case != 'base' else base()
    if ORIGINAL_OUTCOMES[case] == 'ok':
        h.validate_recipe(r)
    else:
        with pytest.raises(ValueError):
            h.validate_recipe(r)


def test_original_largeR_overlap_choice_is_enforced_at_branch_requirement():
    r = base(); r['objects'][0].update(prefix='largeRjet', selection='stored', scale_factors=[], tagger=None)
    with pytest.raises(ValueError, match='large'):
        h.required_branches(r)  # former required_branches refused standard OR on large-R jets
    r['overlap_removal'] = 'largeR'
    assert 'largeRjet_select_passesORLargeR_NOSYS' in h.required_branches(r)


def case2():
    r = base(objects=[
        {'name': 'muons', 'prefix': 'mu', 'selection': 'baseline', 'pt_min_GeV': 25, 'abs_eta_max': 2.5,
         'scale_factors': ['mu_reco_effSF_id_Tight_NOSYS'], 'tagger': None},
        {'name': 'jets', 'prefix': 'jet', 'selection': 'stored', 'pt_min_GeV': 30, 'abs_eta_max': 2.8,
         'scale_factors': [], 'tagger': None},
        {'name': 'fatjets', 'prefix': 'largeRjet', 'selection': 'stored', 'pt_min_GeV': 200, 'abs_eta_max': 2.,
         'scale_factors': [], 'tagger': {'tagged': 'largeRjet_X_tagged_NOSYS', 'valid': 'largeRjet_X_validKinRange_NOSYS',
                                         'score': 'largeRjet_X_score_NOSYS', 'mass': None}}],
        overlap_removal='largeR', trigger_by_year={'2022': ['trigPassed_HLT_mu'], '2023': ['trigPassed_HLT_mu']},
        scalar_scale_factors=['weight_pileup_NOSYS'],
        regions=[{'id': 'SR', 'role': 'signal', 'counts': {'muons': [1, 1], 'jets': [2, None], 'fatjets': [1, None]},
                  'ht': {'object': 'jets', 'range_GeV': [100, None]}, 'met_GeV': [50, None]}])
    e = {'year': 2023, 'mcChannelNumber': 410470, 'trigPassed_HLT_mu': True,
         'mu_pt_NOSYS': [30000, 26000, 12000], 'mu_eta': [.1, 1.9, .3], 'mu_select_baseline_NOSYS': [1, 1, 1],
         'mu_select_passesORLargeR_NOSYS': [1, 0, 1], 'mu_reco_effSF_id_Tight_NOSYS': [.98, .9, .95],
         'jet_pt_NOSYS': [80000, 45000, 20000], 'jet_eta': [.5, 2.0, 1.], 'jet_select_passesORLargeR_NOSYS': [1, 1, 1],
         'largeRjet_pt_NOSYS': [350000, 220000], 'largeRjet_eta': [.2, .4],
         'largeRjet_select_passesORLargeR_NOSYS': [1, 1], 'largeRjet_X_tagged_NOSYS': [1, 0],
         'largeRjet_X_validKinRange_NOSYS': [1, 1], 'largeRjet_X_score_NOSYS': [.9, .2],
         'metBaseline_met_NOSYS': 70000, 'weight_mc_NOSYS': 1., 'weight_pileup_NOSYS': 1.1}
    return r, e


# Former implementation's event view, branch requirement and region record on case2().
ORIGINAL_VIEW = {'met_GeV': 70.0, 'object_factor': 0.98, 'trigger_passed': True,
                 'objects': {'fatjets': {'indices': [0], 'pt_GeV': [350.0]},
                             'jets': {'indices': [0, 1], 'pt_GeV': [80.0, 45.0]},
                             'muons': {'indices': [0], 'pt_GeV': [30.0]}}}
ORIGINAL_REQUIRED = ['jet_eta', 'jet_pt_NOSYS', 'jet_select_passesORLargeR_NOSYS', 'largeRjet_X_score_NOSYS',
                     'largeRjet_X_tagged_NOSYS', 'largeRjet_X_validKinRange_NOSYS', 'largeRjet_eta',
                     'largeRjet_pt_NOSYS', 'largeRjet_select_passesORLargeR_NOSYS', 'mcChannelNumber',
                     'metBaseline_met_NOSYS', 'mu_eta', 'mu_pt_NOSYS', 'mu_reco_effSF_id_Tight_NOSYS',
                     'mu_select_baseline_NOSYS', 'mu_select_passesORLargeR_NOSYS', 'trigPassed_HLT_mu',
                     'weight_mc_NOSYS', 'weight_pileup_NOSYS', 'year']


def test_original_event_view_requirements_and_records_match_the_former_implementation():
    r, e = case2()
    checked = h.validate_recipe(r)
    assert h.event_view(e, checked) == ORIGINAL_VIEW
    assert h.required_branches(r) == ORIGINAL_REQUIRED
    assert h.records([e], [7], {'dsid': 410470}, checked) == [{'source_entry': 7, 'fills': {'regions': [[0.5]]}}]


def test_stored_overlap_flags_cannot_define_a_changed_predicate_by_library_role():
    roles = h.library_roles(CP)
    recipe = {'branch_roles': roles, 'scalar_scale_factors': [], 'trigger_by_year': {}, 'objects': []}
    for flag in ('el_select_passesOR_NOSYS', 'jet_select_passesORLargeR_NOSYS'):
        with pytest.raises(ValueError, match='stored baseline OR'):
            s._changed_predicate(recipe, flag)
    s._changed_predicate(recipe, 'el_select_baseline_NOSYS')  # an ordinary stored flag stays admissible
    assert s._known_branch_role(recipe, 'weight_beamspot') == ('scale_weight', 'scalar', '1')


def test_changed_selection_recipe_accepts_a_named_descriptor_and_applies_its_containers(tmp_path):
    import test_columnar_changed_selection as t
    root, r = t.source(tmp_path)
    r['branch_roles'] = CP
    checked = s.validate_recipe(r)
    assert checked['branch_roles'] == h.library_roles(CP)
    # the descriptor's container table is applied to the changed recipe's shadow check too
    bad = deepcopy(r); bad['objects'][0]['prefix'] = 'xx'
    with pytest.raises(ValueError):
        s.validate_recipe(bad)


# ---- second, unrelated use: another recipe and a different public format --------------------

def test_second_use_run2_electron_photon_recipe_with_signal_flags_and_beamspot():
    r = base(objects=[
        {'name': 'el', 'prefix': 'el', 'selection': 'signal', 'pt_min_GeV': 30, 'abs_eta_max': 2.37,
         'scale_factors': ['el_id_effSF_id_TightLH_NOSYS'], 'tagger': None},
        {'name': 'ph', 'prefix': 'ph', 'selection': 'signal', 'pt_min_GeV': 25, 'abs_eta_max': 2.37,
         'scale_factors': [], 'tagger': None}],
        overlap_removal='none', met='Signal', trigger_by_year={'2016': ['trigPassed_HLT_e26'], '2017': ['trigPassed_HLT_e26']},
        regions=[{'id': 'A', 'role': 'signal', 'counts': {'el': [1, 1], 'ph': [1, None]}, 'ht': None, 'met_GeV': [0, None]}])
    checked = h.validate_recipe(r)
    ev = {'year': 2016, 'mcChannelNumber': 1, 'trigPassed_HLT_e26': True,
          'el_pt_NOSYS': [40000], 'el_eta': [.3], 'el_select_signal_NOSYS': [1], 'el_id_effSF_id_TightLH_NOSYS': [.95],
          'ph_pt_NOSYS': [60000, 30000], 'ph_eta': [.1, 1.], 'ph_select_signal_NOSYS': [1, 0],
          'metSignal_met_NOSYS': 10000}
    view = h.event_view(ev, checked)
    assert view['objects']['el']['indices'] == [0] and view['objects']['ph']['indices'] == [0]
    assert view['object_factor'] == pytest.approx(.95) and view['met_GeV'] == 10.
    assert h.records([ev], [0], {'dsid': 1}, checked) == [{'source_entry': 0, 'fills': {'regions': [[.5]]}}]
    # signal flags are refused once stored overlap removal is requested; Run 3 refuses the Run-2 beamspot weight
    with pytest.raises(ValueError):
        h.validate_recipe({**deepcopy(r), 'overlap_removal': 'standard', 'met': 'Baseline'})
    late = deepcopy(r); late['trigger_by_year'] = {'2024': ['trigPassed_HLT_e26']}
    with pytest.raises(ValueError, match='supplied only for periods'):
        h.validate_recipe(late)
    late['scalar_scale_factors'] = ['weight_pileup_NOSYS']
    assert h.validate_recipe(late)['trigger_by_year'] == {'2024': ['trigPassed_HLT_e26']}


def test_second_use_open_data_format_through_the_same_branch_description_engine():
    roles = h.library_roles(OPEN_DATA)
    assert 'containers' not in roles and 'periods' not in roles
    assert h.descriptor_role(roles, 'lep_pt') == ('object_pt', 'jagged', None)
    assert h.descriptor_role(roles, 'jet_eta') == ('object_eta', 'jagged', '1')
    assert h.descriptor_role(roles, 'largeRjet_m') == ('object_mass', 'jagged', None)
    assert h.descriptor_role(roles, 'scaleFactor_PILEUP') == ('scale_weight', 'scalar', '1')
    assert h.descriptor_role(roles, 'trigE') == ('trigger_decision', 'scalar', '1')
    assert h.descriptor_role(roles, 'lep_charge') == ('object_charge', 'jagged', '1')
    assert h.descriptor_role(roles, 'no_such_branch') is None
    r = base(branch_roles=OPEN_DATA, overlap_removal='none', scalar_scale_factors=['scaleFactor_PILEUP'],
             objects=[{'name': 'leptons', 'prefix': 'lep', 'selection': 'stored', 'pt_min_GeV': 20, 'abs_eta_max': 2.5,
                       'scale_factors': [], 'tagger': None}], trigger_by_year={'2018': ['trigPassed_trigE']})
    checked = h.validate_recipe(r)
    assert checked['branch_roles']['name'] == OPEN_DATA
    assert h.branch_description(r, 'lep_phi') == ('jagged', 'rad')
    assert h.branch_description(r, 'lep_pt') == ('jagged', None)  # the format fixes no unit: the branch schema states it
    assert h.branch_description(r, 'scaleFactor_PILEUP') == ('scalar', '1')
    # a descriptor's scale weight keeps its role against a recipe that tries to use it elsewhere
    bad = deepcopy(r); bad['branch_roles'] = deepcopy(roles)
    for row in bad['branch_roles']['branches']:
        if row['name'] == 'scaleFactor_PILEUP': row['role'] = 'object_pt'
    with pytest.raises(ValueError, match='scale-weight role'):
        h.validate_recipe(bad)


@pytest.mark.parametrize('change', [
    lambda d: d.__setitem__('containers', []),
    lambda d: d.__setitem__('containers', [{'prefix': 'el'}]),
    lambda d: d.__setitem__('containers', [{'prefix': 'el', 'selections': ['nope']}]),
    lambda d: d.__setitem__('containers', [{'prefix': 'el', 'selections': ['stored'], 'x': 1}]),
    lambda d: d.__setitem__('containers', [{'prefix': 'el', 'selections': ['stored'], 'tagger_valid': 'a'}]),
    lambda d: d.__setitem__('containers', [{'prefix': 'el', 'selections': ['stored']},
                                           {'prefix': 'el', 'selections': ['stored']}])])
def test_container_rows_are_closed_and_typed(change):
    d = h.library_roles(CP); change(d)
    with pytest.raises(ValueError):
        h.branch_roles(d)


def test_packaged_descriptors_carry_no_document_hash_or_page_citation():
    import re
    for name in h.library_names():
        text = json.dumps(h.library_roles(name))
        assert not re.search(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])', text)
        assert 'page' not in text.lower().split('source')[0]
        assert 'http' in h.library_roles(name)['source'] or name == CP
