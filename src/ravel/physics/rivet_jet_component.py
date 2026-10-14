"""Typed particle-to-jet source construction through native Rivet FastJets.

This compiler emits C++ for the existing Rivet projection; it never clusters,
executes a routine, or substitutes reconstructed LHCO objects for particles.
The enclosing routine owns booking, selection, weights and finalization.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

ALGORITHMS = {'antikt': 'ANTIKT', 'kt': 'KT', 'cambridge': 'CAM'}
FIELDS = {'pt': ('pT', 'GeV'), 'abs_eta': ('abseta', '1'), 'abs_rapidity': ('absrap', '1')}
RELATIONS = {'gt': '>', 'ge': '>=', 'lt': '<', 'le': '<='}
TREATMENTS = {'none': 'NONE', 'decay': 'DECAY', 'all': 'ALL'}
MAX_SOURCE_BYTES = 2_000_000
CPP_KEYWORDS = set('alignas alignof and and_eq asm atomic_cancel atomic_commit atomic_noexcept auto bitand bitor bool break case catch char char8_t char16_t char32_t class compl concept const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept not not_eq nullptr operator or or_eq private protected public reflexpr register reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch synchronized template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile wchar_t while xor xor_eq'.split())


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('closed component fields required: ' + ', '.join(keys))


def _identifier(value):
    if (type(value) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', value)
            or value in CPP_KEYWORDS or value in {'event', 'jets', 'init', 'analyze', 'finalize', 'Rivet', 'std', 'class', 'auto', 'return', 'const', 'FinalState', 'FastJets', 'JetAlg', 'JetMuons', 'JetInvisibles', 'Cuts', 'Jets', 'GeV'}):
        raise ValueError('bounded nonreserved C++ identity required')
    return value


def _native_name(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', value):
        raise ValueError('bounded literal native projection name required')
    return value


def _number(value):
    if type(value) not in (int, float):
        raise ValueError('nonnegative finite binary64 literal required')
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError('representable binary64 literal required') from exc
    if type(value) is int and math.isfinite(number) and int(number) != value:
        raise ValueError('integer literal is not exactly binary64 representable')
    if not math.isfinite(number) or number < 0:
        raise ValueError('nonnegative finite binary64 literal required')
    return number


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _cuts(cuts):
    if type(cuts) is not list or len(cuts) > 8:
        raise ValueError('at most eight conjunctive cuts required')
    result, identities = [], set()
    for cut in cuts:
        _keys(cut, ('field', 'relation', 'value', 'unit'))
        field, relation = cut['field'], cut['relation']
        if type(field) is not str or type(relation) is not str or field not in FIELDS or relation not in RELATIONS or cut['unit'] != FIELDS[field][1]:
            raise ValueError('explicit supported observable/relation/unit required')
        identity = (field, relation)
        if identity in identities:
            raise ValueError('duplicate cut predicate')
        identities.add(identity)
        value = repr(_number(cut['value']))
        if field == 'pt':
            value += '*GeV'
        result.append(f'(Cuts::{FIELDS[field][0]} {RELATIONS[relation]} {value})')
    return ' && '.join(result) if result else 'Cuts::OPEN'


def compile_component(recipe):
    """Lower a typed component to native init/analyze statements.

    Input predicates act on stable final-state particles *before* clustering.
    Jet predicates act on clustered jets before native pT sorting. No eta/y
    substitution, default invisible policy, detector response or weight law.
    """
    recipe = deepcopy(recipe)
    _keys(recipe, ('schema_version', 'kind', 'components'))
    if type(recipe['schema_version']) is not int or recipe['schema_version'] != 1 or recipe['kind'] != 'native-rivet-jet-components':
        raise ValueError('native-rivet-jet-components/v1 required')
    components = recipe['components']
    if type(components) is not list or not 1 <= len(components) <= 16:
        raise ValueError('one to sixteen native jet components required')
    symbols, projection_names, init, analyze, semantics = set(), set(), [], [], []
    for component in components:
        _keys(component, ('id', 'projection_name', 'input', 'clustering', 'jet_cuts', 'output'))
        identity = _identifier(component['id'])
        output = _identifier(component['output'])
        native_name = _native_name(component['projection_name'])
        locals_ = {identity + '_fs', identity + '_finder', output}
        if len(locals_) != 3 or symbols & locals_ or native_name in projection_names:
            raise ValueError('distinct local and native projection identities required')
        symbols.update(locals_); projection_names.add(native_name)
        _keys(component['input'], ('kind', 'cuts', 'projection_name'))
        input_name = component['input']['projection_name']
        if input_name is not None:
            _native_name(input_name)
            if input_name in projection_names:
                raise ValueError('input projection identity collision')
            projection_names.add(input_name)
        if component['input']['kind'] != 'stable_final_state':
            raise ValueError('only native stable FinalState input is lowered; charged/prompt/vetoed/dressed inputs require separate recipes')
        input_cut = _cuts(component['input']['cuts'])
        clustering = component['clustering']
        _keys(clustering, ('algorithm', 'radius', 'recombination', 'muons', 'invisibles', 'area', 'grooming'))
        if (any(type(clustering[key]) is not str for key in ('algorithm', 'recombination', 'muons', 'invisibles'))
                or clustering['algorithm'] not in ALGORITHMS or clustering['recombination'] != 'E_scheme'
                or clustering['muons'] not in TREATMENTS or clustering['invisibles'] not in TREATMENTS
                or clustering['area'] is not None or clustering['grooming'] is not None):
            raise ValueError('only native longitudinally invariant E-scheme algorithms with explicit constituent treatment and no area/grooming are lowered')
        radius = _number(clustering['radius'])
        if not 0 < radius <= 10:
            raise ValueError('positive bounded native jet radius required')
        jet_cut = _cuts(component['jet_cuts'])
        init += [f'const FinalState {identity}_fs({input_cut});']
        if input_name is not None:
            init.append(f'declare({identity}_fs, "{input_name}");')
        init += [f'const FastJets {identity}_finder({identity}_fs, JetAlg::{ALGORITHMS[clustering["algorithm"]]}, {repr(radius)}, JetMuons::{TREATMENTS[clustering["muons"]]}, JetInvisibles::{TREATMENTS[clustering["invisibles"]]});',
                 f'declare({identity}_finder, "{native_name}");']
        analyze.append(f'const Jets {output} = apply<FastJets>(event, "{native_name}").jetsByPt({jet_cut});')
        semantics.append({'id': identity, 'output': output, 'projection_name': native_name,
            'input_cut_phase': 'stable_particles_before_clustering', 'jet_cut_phase': 'clustered_jets_before_native_sort',
            'sorting': 'native_cmpMomByPt_equal_pt_order_unspecified', 'clustering': clustering,
            'input': component['input'], 'jet_cuts': component['jet_cuts']})
    return {'schema_version': 1, 'kind': 'native-rivet-jet-component-source', 'recipe': recipe,
        'recipe_sha256': _digest(recipe), 'headers': ['Rivet/Projections/FinalState.hh', 'Rivet/Projections/FastJets.hh'],
        'init': '\n'.join(init), 'analyze': '\n'.join(analyze), 'components': semantics,
        'weights': 'enclosing_native_routine_unchanged_no_weight_arithmetic_added',
        'native_executed': False, 'physics_validated': False,
        'remaining_obligations': ['exact_Rivet_FastJet_API_build_and_loaded_binary', 'input_particle_decay_and_visibility_applicability',
            'full_original_event_and_named_weight_census', 'native_cluster_constituent_and_massive_rapidity_witness',
            'enclosing_routine_cuts_booking_all_outputs_flows_and_finalization', 'source_detector_and_statistical_model_validation']}


def instantiate(source, *, expected_sha256, recipe):
    """Populate three explicit template slots and return a new source identity.

    The caller supplies a fresh analysis template, not an arbitrary C++ parser.
    Each whole-line slot occurs once; no original bytes are canonicalized.
    The resulting source must enter the existing capsule/build/review lifecycle.
    """
    if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise ValueError('bounded complete UTF-8 source bytes required')
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise ValueError('original template source digest differs')
    text = source.decode('utf-8')
    component = compile_component(recipe)
    substitutions = {'// RAVEL_JET_HEADERS': '\n'.join(f'#include "{p}"' for p in component['headers']),
                     '// RAVEL_JET_INIT': component['init'], '// RAVEL_JET_ANALYZE': component['analyze']}
    lines = text.splitlines(keepends=True)
    for slot in substitutions:
        if sum(line.strip() == slot for line in lines) != 1 or text.count(slot) != 1:
            raise ValueError('three unique whole-line template slots required')
    generated = []
    for line in lines:
        key = line.strip()
        if key in substitutions:
            indent = line[:len(line) - len(line.lstrip())]
            newline = '\r\n' if line.endswith('\r\n') else '\n'
            generated.extend(indent + part + newline for part in substitutions[key].splitlines())
        else:
            generated.append(line)
    raw = ''.join(generated).encode('utf-8')
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('generated source exceeds source byte budget')
    return {'component': component, 'original_template_sha256': expected_sha256,
            'source_sha256': hashlib.sha256(raw).hexdigest(), 'source': raw,
            'source_capsule_dependency_review': 'incomplete_requires_fresh_native_admission'}
