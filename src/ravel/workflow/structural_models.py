"""Typed structural proposal retrieval through the located knowledge kernel.

Independently implemented from FERMIACC 2603.22538v1, Appendix A.3/A.5;
no FERMIACC code or licence is asserted. Matching is a coarse multiset search,
not an interaction comparison, novelty decision or model-validity certificate.
All source annotations, failed outcomes and unknowns remain visible.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
from pathlib import Path
import re
import stat

from . import physics_knowledge as knowledge

MAX_MODELS = 32
MAX_FIELDS = 64
MAX_TOTAL_FIELDS = 256
FEATURES = ('twice_spin', 'cp', 'color_dynkin', 'weak_dynkin', 'hypercharge',
            'self_conjugate', 'conjugation')
CONVENTIONS = ('gauge_basis', 'phase', 'hypercharge_normalization', 'cp_convention', 'field_population')
SECTIONS = ('interactions', 'kinetic_terms', 'topologies', 'processes', 'outcomes')
SCOPE = ('Source-declared field-signature retrieval only. Equal signatures do not '
         'establish equal interactions, physical equivalence, novelty, executable '
         'UFO completeness, applicability or scientific validation.')


def _fraction(value):
    if type(value) is not str or not re.fullmatch(r'-?[0-9]{1,18}(?:/[1-9][0-9]{0,17})?', value):
        raise ValueError('bounded exact integer/rational hypercharge required; no float coercion')
    result = Fraction(value)
    return str(result.numerator) + '/' + str(result.denominator)


def _nodes(value, nodes, *, prior, minimum=1):
    knowledge._items(value, 16, minimum)
    if any(type(i) is not str or i not in nodes for i in value) or len(value) != len(set(value)):
        raise ValueError('distinct existing located knowledge node identities required')
    if prior and any(not nodes[i]['source_evidence'] for i in value):
        raise ValueError('prior proposal annotations need retained located evidence')
    return value


def _field(row, nodes, *, prior):
    knowledge._keys(row, ('id', *FEATURES, 'conjugate_of', 'node_ids'))
    knowledge._id(row['id']); _nodes(row['node_ids'], nodes, prior=prior)
    normalized = deepcopy(row)
    spin = row['twice_spin']
    if spin is not None and (type(spin) is not int or not 0 <= spin <= 16):
        raise ValueError('declared bounded physical 2s or null required; UFO 2s+1 is distinct')
    if row['cp'] is not None and row['cp'] not in ('even', 'odd', 'not-eigenstate'):
        raise ValueError('declared CP eigenvalue status or null required')
    for key, length in (('color_dynkin', 2), ('weak_dynkin', 1)):
        value = row[key]
        if value is not None and (type(value) is not list or len(value) != length
                or any(type(n) is not int or not 0 <= n <= 32 for n in value)):
            raise ValueError('explicit SU3/SU2 Dynkin labels or null required; dimensions are not labels')
    if row['hypercharge'] is not None:
        normalized['hypercharge'] = _fraction(row['hypercharge'])
    if row['self_conjugate'] is not None and type(row['self_conjugate']) is not bool:
        raise ValueError('explicit self-conjugacy boolean or null required')
    if row['conjugation'] is not None and row['conjugation'] not in ('self', 'independent', 'conjugate'):
        raise ValueError('explicit conjugation role or null required')
    if row['conjugate_of'] is not None:
        knowledge._id(row['conjugate_of'])
        if row['conjugation'] != 'conjugate' or row['conjugate_of'] == row['id']:
            raise ValueError('conjugate_of must name another explicit field in a conjugate declaration')
    elif row['conjugation'] == 'conjugate':
        raise ValueError('a declared conjugate needs its original field identity')
    return normalized


def _source_bytes(pin, base):
    # This existing reader also retains legitimate empty source files. The
    # general located-text reader remains strict and unchanged.
    from .research_followup import _bytes
    path, raw = _bytes(pin, base)
    return {'path': str(path), 'sha256': pin['sha256'], 'size': len(raw)}, raw


def _source_shape(root):
    """Bound complete source enumeration before reading any supplied bytes."""
    files, directories, total, count = {}, {}, 0, 0
    for path in root.rglob('*'):
        count += 1
        if count > 256 or path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('complete bounded ordinary UFO membership required; no aliases/exclusions')
        row = path.stat(); name = path.relative_to(root).as_posix()
        if path.is_dir():
            directories[name] = stat.S_IMODE(row.st_mode)
        else:
            total += row.st_size; files[name] = {'size': row.st_size, 'mode': stat.S_IMODE(row.st_mode)}
            if len(files) > 128 or row.st_size > knowledge.MAX_DOCUMENT_BYTES or total > knowledge.MAX_SOURCE_BYTES:
                raise ValueError('complete UFO source exceeds bounded input population/bytes')
    return {'files': files, 'directories': directories}


def _ufo(spec, fields, base):
    """Reuse the existing static census; do not import/evaluate supplied UFOs."""
    from ravel.physics import model_sarah, ufo_interop
    knowledge._keys(spec, ('tree', 'particle_conventions', 'field_pdgs'))
    knowledge._keys(spec['tree'], ('root', 'manifest'))
    rawroot = Path(spec['tree']['root'])
    root = (rawroot if rawroot.is_absolute() else Path(base) / rawroot).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError('ordinary complete supplied UFO source root required')
    root = root.resolve()
    shape = _source_shape(root)
    manifest, raw = knowledge._snapshot(spec['tree']['manifest'], base)
    declared = knowledge._json(raw)
    knowledge._keys(declared, ('schema_version', 'files'))
    # Unlike the execution bridge's cache exclusions, this reader keeps ALL
    # source members, including empty __init__.py and additional custom code.
    before = ufo_interop.source_tree(root)
    if declared != before:
        raise ValueError('complete UFO source membership/bytes differ from declared manifest')
    if len(before['files']) > 128:
        raise ValueError('complete UFO source exceeds ordinary Graph input ceiling; no truncation')
    pins, modes = [manifest], {}
    for name, sha in before['files'].items():
        path = root / name
        size = path.stat().st_size
        pin, _ = _source_bytes({'path': str(path), 'sha256': sha, 'size': size}, root)
        pins.append(pin); modes[name] = stat.S_IMODE(path.stat().st_mode)
    model_sarah.conventions(spec['particle_conventions'])
    mapping, pdgs = {}, set()
    for row in knowledge._items(spec['field_pdgs'], MAX_FIELDS, 1):
        knowledge._keys(row, ('field', 'pdg'))
        if (type(row['field']) is not str or row['field'] not in fields or row['field'] in mapping
                or type(row['pdg']) is not int or row['pdg'] in pdgs):
            raise ValueError('unique explicit field to signed UFO PDG association required')
        mapping[row['field']] = row['pdg']; pdgs.add(row['pdg'])
    if pdgs != {r['pdg'] for r in spec['particle_conventions']}:
        raise ValueError('all selected UFO convention obligations must have a field association')
    census = model_sarah.ufo_census(root, spec['particle_conventions'])
    particles = {r['pdg']: r for r in census['particles'].values()}
    checks = []
    for identity, pdg in mapping.items():
        field, actual = fields[identity], particles[pdg]
        # A ghost is not a physical 2s signature. Electric charge is NOT Y;
        # dimensions/codes are NOT inferred Dynkin labels or weak reps.
        spin_equal = (None if field['twice_spin'] is None or actual['spin'] == -1
                      else field['twice_spin'] == actual['spin'] - 1)
        conjugacy_equal = (None if field['self_conjugate'] is None else
                           field['self_conjugate'] == (actual['name'] == actual['antiname']))
        checks.append({'field': identity, 'pdg': pdg, 'source_particle': actual,
                       'declared_2s_matches_literal_ufo_2s_plus_1': spin_equal,
                       'declared_self_conjugacy_matches_literal_names': conjugacy_equal,
                       'cp_ew_hypercharge_dynkin_association': 'not_inferred'})
    # Contradictory associations remain diagnostic source evidence rather than
    # being patched, clipped, dropped or promoted to a valid model.
    if (_source_shape(root) != shape or ufo_interop.source_tree(root) != before or
            modes != {name: stat.S_IMODE((root / name).stat().st_mode) for name in modes}):
        raise ValueError('complete UFO source changed during static census')
    return {'root': str(root), 'manifest': manifest, 'source_tree': before, 'source_modes': modes,
            'source_shape': shape,
            'census': census, 'field_associations': checks, 'model_imported': False,
            'coupling_expressions_evaluated': False, 'physical_model_validated': False}, pins


def _model(row, nodes, base):
    knowledge._keys(row, ('id', 'name', 'kind', 'conventions', 'fields', *SECTIONS, 'ufo', 'node_ids'))
    knowledge._id(row['id']); knowledge._text(row['name'], 500)
    if row['kind'] not in ('proposal', 'prior'):
        raise ValueError('explicit proposal or retained prior record required')
    prior = row['kind'] == 'prior'
    _nodes(row['node_ids'], nodes, prior=prior)
    knowledge._keys(row['conventions'], (*CONVENTIONS, 'node_ids'))
    _nodes(row['conventions']['node_ids'], nodes, prior=prior)
    for key in CONVENTIONS:
        if row['conventions'][key] is not None:
            knowledge._text(row['conventions'][key], 500)
    fields = [_field(f, nodes, prior=prior) for f in knowledge._items(row['fields'], MAX_FIELDS)]
    by_id = {f['id']: f for f in fields}
    if len(by_id) != len(fields) or any(f['conjugate_of'] is not None and f['conjugate_of'] not in by_id for f in fields):
        raise ValueError('distinct complete field/conjugate identity census required')
    used = set(row['node_ids']) | set(row['conventions']['node_ids'])
    for field in fields:
        used.update(field['node_ids'])
    for section in SECTIONS:
        if row[section] is None:
            continue  # unknown, distinct from an explicit empty population
        for item in knowledge._items(row[section], 32):
            keys = ('statement', 'node_ids', 'status') if section == 'outcomes' else ('statement', 'node_ids')
            knowledge._keys(item, keys)
            knowledge._text(item['statement'], 4000)
            _nodes(item['node_ids'], nodes, prior=prior); used.update(item['node_ids'])
            if section == 'outcomes' and item['status'] not in ('accepted', 'rejected', 'failed', 'unresolved', 'unexecuted'):
                raise ValueError('complete declared outcome disposition required')
    observed, pins = (None, []) if row['ufo'] is None else _ufo(row['ufo'], by_id, base)
    return {'record': deepcopy(row), 'normalized_fields': fields, 'knowledge_node_ids': sorted(used),
            'assertion_kinds': {i: nodes[i]['kind'] for i in sorted(used)}, 'ufo_observation': observed}, pins


def _load(request, base):
    knowledge._keys(request, ('schema_version', 'knowledge', 'query', 'structural_query'))
    if type(request['schema_version']) is not int or request['schema_version'] != 2:
        raise ValueError('explicit structural physics-knowledge request/v2 required')
    knowledge._keys(request['structural_query'], ('library', 'proposal'))
    ordinary = {k: deepcopy(request[k]) for k in ('knowledge', 'query')}
    ordinary['schema_version'] = 1
    _, _, nodes, _, inventory = knowledge._load(ordinary, base)
    library_pin, library_raw = knowledge._snapshot(request['structural_query']['library'], base)
    proposal_pin, proposal_raw = knowledge._snapshot(request['structural_query']['proposal'], base)
    library = knowledge._json(library_raw); proposal = knowledge._json(proposal_raw)
    knowledge._keys(library, ('schema_version', 'id', 'models'))
    if type(library['schema_version']) is not int or library['schema_version'] != 1:
        raise ValueError('typed structural model library/v1 required')
    knowledge._id(library['id'])
    query, pins = _model(proposal, nodes, Path(proposal_pin['path']).parent)
    if proposal['kind'] != 'proposal':
        raise ValueError('current structural query must be an explicit proposed model')
    models, ids = [], {proposal['id']}
    for row in knowledge._items(library['models'], MAX_MODELS):
        model, deps = _model(row, nodes, Path(library_pin['path']).parent)
        if row['id'] in ids:
            raise ValueError('unique proposal/library model identities required')
        ids.add(row['id']); models.append(model); pins.extend(deps)
    if sum(len(m['normalized_fields']) for m in [query, *models]) > MAX_TOTAL_FIELDS:
        raise ValueError('complete structural field population exceeds bounded retrieval')
    from . import research_followup, research_cycle
    implementation = [__file__, knowledge.__file__, research_followup.__file__, research_cycle.__file__]
    if any(m['ufo_observation'] is not None for m in [query, *models]):
        from ravel.physics import model_sarah, ufo_interop, model_derivation_bridge, model_tool_bridge
        implementation.extend(m.__file__ for m in (model_sarah, ufo_interop, model_derivation_bridge, model_tool_bridge))
    implementation_pins = [research_cycle._pin(path) for path in implementation]
    by_path = {}
    for pin in [*inventory, library_pin, proposal_pin, *pins, *implementation_pins]:
        if pin['path'] in by_path and by_path[pin['path']] != pin:
            raise ValueError('conflicting structural source identities')
        by_path[pin['path']] = pin
    inventory = list(by_path.values())
    if len(inventory) > 128 or sum(p['size'] for p in inventory) > knowledge.MAX_SOURCE_BYTES:
        raise ValueError('complete structural source exceeds existing Graph/corpus bounds; no exclusions')
    # Every compared model annotation is retained through the same dependency
    # and conflict closure; max_nodes cannot silently drop a bad prior outcome.
    ordinary['query']['roots'] = sorted(set(ordinary['query']['roots']) |
        {i for model in [query, *models] for i in model['knowledge_node_ids']})
    return ordinary, query, models, inventory, library_pin, proposal_pin, implementation_pins


def input_pins(request, base):
    return _load(request, base)[3]


def _pair(a, b, incomparable=()):
    equal, unknown, differing, uncomparable = [], [], [], []
    for key in FEATURES:
        if key in incomparable:
            uncomparable.append(key)
        elif a[key] is None or b[key] is None:
            unknown.append(key)
        elif a[key] == b[key]:
            equal.append(key)
        else:
            differing.append(key)
    return {'query_field': a['id'], 'prior_field': b['id'], 'known_equal': equal,
            'unknown': unknown, 'incomparable': uncomparable, 'differing': differing}


def compare(query, prior):
    """Maximum compatible multiset correspondence; no greedy field collapse.

    Fields remain individual occurrences. Names/ordering are not signature
    identity. Conjugate-of graph links remain displayed, but are a finer-level
    comparison obligation rather than an implicit graph-isomorphism proof.
    """
    qa, pb = query['normalized_fields'], prior['normalized_fields']
    qc, pc = query['record']['conventions'], prior['record']['conventions']
    conflicts = [{'property': k, 'query': qc[k], 'prior': pc[k]} for k in CONVENTIONS
                 if qc[k] is not None and pc[k] is not None and qc[k] != pc[k]]
    unknown_conventions = [k for k in CONVENTIONS if qc[k] is None or pc[k] is None]
    incomparable = set()
    if qc['gauge_basis'] is None or pc['gauge_basis'] is None or qc['gauge_basis'] != pc['gauge_basis']:
        incomparable.update(('color_dynkin', 'weak_dynkin', 'hypercharge'))
    if (qc['hypercharge_normalization'] is None or pc['hypercharge_normalization'] is None or
            qc['hypercharge_normalization'] != pc['hypercharge_normalization']):
        incomparable.add('hypercharge')
    if qc['phase'] is None or pc['phase'] is None or qc['phase'] != pc['phase']:
        incomparable.update(('color_dynkin', 'weak_dynkin', 'hypercharge', 'cp'))
    if qc['cp_convention'] is None or pc['cp_convention'] is None or qc['cp_convention'] != pc['cp_convention']:
        incomparable.add('cp')
    pairs = {(i, j): _pair(a, b, incomparable) for i, a in enumerate(qa) for j, b in enumerate(pb)}
    adjacency = {i: sorted((j for j in range(len(pb)) if not pairs[i, j]['differing']),
                          key=lambda j: (len(pairs[i, j]['unknown']), pb[j]['id'])) for i in range(len(qa))}
    owner = {}
    def augment(i, visited):
        for j in adjacency[i]:
            if j in visited:
                continue
            visited.add(j)
            if j not in owner or augment(owner[j], visited):
                owner[j] = i; return True
        return False
    for i in sorted(range(len(qa)), key=lambda i: (len(adjacency[i]), qa[i]['id'])):
        augment(i, set())
    correspondence = [pairs[i, j] for j, i in sorted(owner.items(), key=lambda item: qa[item[1]]['id'])]
    complete = len(owner) == len(qa) == len(pb)
    status = ('conflicting' if conflicts else
              'exact' if complete and not unknown_conventions and all(not p['unknown'] and not p['incomparable'] for p in correspondence) else
              'partial' if complete or owner else 'different')
    if not conflicts and len(qa) == len(pb) and not complete:
        status = 'conflicting'  # incompatible signatures, not a physics falsification
    used_q = set(owner.values()); used_p = set(owner)
    return {'model_id': prior['record']['id'], 'match': status, 'complete_field_correspondence': complete,
            'query_field_count': len(qa), 'prior_field_count': len(pb), 'correspondence': correspondence,
            'unmatched_query': [f['id'] for i, f in enumerate(qa) if i not in used_q],
            'unmatched_prior': [f['id'] for j, f in enumerate(pb) if j not in used_p],
            'convention_conflicts': conflicts, 'unknown_conventions': unknown_conventions,
            'incompatible_pairs': [p for p in pairs.values() if p['differing']],
            'explanation': ('Exact means this declared field-signature multiset only. Unknowns prevent exactness. '
                            'Conflicting means declared signatures/conventions cannot be identified; it is not a falsified model.'),
            'interactions_equal': None, 'physical_equivalence': None, 'novelty_established': False}


def _ending(inventory, models):
    for pin in inventory:
        _source_bytes(pin, Path.cwd())
    for model in models:
        observed = model['ufo_observation']
        if observed is not None:
            from ravel.physics import ufo_interop
            root = Path(observed['root'])
            if (_source_shape(root) != observed['source_shape'] or
                    ufo_interop.source_tree(root) != observed['source_tree'] or
                    observed['source_modes'] != {n: stat.S_IMODE((root/n).stat().st_mode)
                                                for n in observed['source_modes']}):
                raise ValueError('complete UFO membership/modes changed before structural delivery')


def retrieve(request, base):
    ordinary, query, models, inventory, library_pin, proposal_pin, implementation_pins = _load(request, base)
    packet = knowledge.retrieve(ordinary, base)
    packet['request'] = deepcopy(request)
    packet['request_sha256'] = hashlib.sha256(knowledge._canonical(request)).hexdigest()
    packet['source_inventory'] = inventory
    # Typed annotations are themselves committed inputs even for exploratory
    # premises whose external evidence is intentionally unknown.
    for premise in packet['premises']:
        by_path = {p['path']: p for p in [*premise['basis'], library_pin, proposal_pin]}
        premise['basis'] = list(by_path.values())
        if len(premise['basis']) > 16:
            raise ValueError('complete model premise exceeds ordinary research basis ceiling')
    packet['structural_models'] = {'schema_version': 1, 'kind': 'structural-model-proposals',
        'library': library_pin, 'proposal': proposal_pin, 'query': query,
        'implementation_sources': implementation_pins,
        'models': models, 'matches': [compare(query, model) for model in models],
        'complete_model_ids': [m['record']['id'] for m in models], 'omitted_models': [],
        'scope': SCOPE, 'comparison_obligations': ['interactions', 'kinetic_terms', 'topologies',
            'processes', 'outcomes', 'conjugate_of_links', 'executable_source_applicability'],
        'method_provenance': 'FERMIACC 2603.22538v1 Appendix A.3/A.5; independent RAVEL implementation; no located upstream code adoption',
        'ordinary_preparation': 'research_tools.prepare_model_proposals; existing bind_knowledge/propose/design/select; no new scheduler',
        'scientific_acceptance': False}
    if len(knowledge._canonical(packet)) > knowledge.MAX_PACKET_BYTES:
        raise ValueError('complete structural packet exceeds existing bound; use a smaller explicit corpus, no hidden trimming')
    _ending(inventory, [query, *models])
    return packet
