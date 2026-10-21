"""Candidate P03 selector/projection binding, never an installed-support claim.

Logical check-in spelling, malformed synthetic floor step metadata and envelopes.json
are bound. Packets and validators delegate to the current implementation on those
normalized inputs; policy decisions, ledger gates and the sink are unchanged.
"""
from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path

from nc_cases import ROOT, require_controller

LABEL = 'SUITE-ENABLE candidate P03 aliases + P18 floor steps + calculated calculation/full fixture envelope'
FLOOR_ROLES = {'attack': 'physics-critic', 'integrity': 'integrity-auditor'}
ALIASES = {'checkin1': 'CI1', 'checkin2': 'CI2', 'checkin3': 'CI3',
           'approve_plan': 'CI1', 'go': 'CI2', 'final': 'CI3'}


def normalize_floor_step(step):
    step = deepcopy(step)
    category = step.get('checkin')
    if (category in FLOOR_ROLES and step.get('id') == category and step.get('kind') == 'review'
            and step.get('role') == FLOOR_ROLES[category]):
        step.pop('checkin')
        if category == 'attack':
            step['protocols'] = list(dict.fromkeys([*step.get('protocols', []), 'P8']))
    return step


def bind_candidate(nc, plan):
    engagement, catalogue = require_controller('engagement', 'instructions.catalogue')
    instructions = require_controller('instructions')
    from ravel.controller.engagement import policy, records
    existing = getattr(nc, '_engagement_candidate_binding', None)
    if existing is not None:
        return existing
    original_resolve = catalogue.Catalogue.resolve

    def resolve(self, selector):
        kind, separator, value = selector.partition(':')
        if kind == 'checkin':
            selector = kind + separator + ALIASES.get(value, value)
        return original_resolve(self, selector)

    resolve.__wrapped__ = original_resolve
    nc.patch.setattr(catalogue.Catalogue, 'resolve', resolve)
    # resolve_all, manifest and check_packet all use the same bound installed resolver.
    installed_selector_errors = {}
    cat = catalogue.installed()
    for category in FLOOR_ROLES:
        try:
            original_resolve(cat, 'checkin:' + category)
        except KeyError as exc:
            installed_selector_errors[category] = str(exc)
    delivery = require_controller('instructions.delivery')
    original_manifest, original_packet, original_check = delivery.manifest, delivery.packet, delivery.check_packet

    def manifest(step, card):
        return original_manifest(normalize_floor_step(step), card)

    def packet(manifest, card, step, inputs):
        return original_packet(manifest, card, normalize_floor_step(step), inputs)

    def check_packet(packet_, manifest, card, step, inputs):
        return original_check(packet_, manifest, card, normalize_floor_step(step), inputs)

    for owner in (instructions, delivery):
        nc.patch.setattr(owner, 'manifest', manifest)
        nc.patch.setattr(owner, 'packet', packet)
        nc.patch.setattr(owner, 'check_packet', check_packet)
    nc.patch.setattr(delivery, '_node_manifest', manifest)
    builder_path = ROOT / 'scripts/maintenance/build_engagement_envelopes.py'
    spec = importlib.util.spec_from_file_location('nc_engagement_projection_builder', builder_path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    installed_data = records.data
    calibration = installed_data('calibration.json')
    rules = policy.load_policy()
    pins = builder.source_inventory(ROOT / 'src/ravel/data')
    for name in ('policy.json', 'calibration.json'):
        path = ROOT / 'src/ravel/data/controller/engagement' / name
        pins['controller/engagement/' + name] = sha256(path.read_bytes()).hexdigest()
    pins.update({'fixture/calculation-plan': records.digest(plan),
                 'fixture/route-seats.json': sha256((ROOT / 'tests/fixtures/engagement/route-seats.json').read_bytes()).hexdigest(),
                 'fixture/binding.py': sha256(Path(__file__).read_bytes()).hexdigest(),
                 'engagement/policy.json': records.digest(rules),
                 'engagement/calibration.json': records.digest(calibration),
                 'candidate/checkin-aliases': records.digest(ALIASES),
                 'candidate/floor-step-roles': records.digest(FLOOR_ROLES)})
    arguments = {'cards': policy.role_cards(), 'instructions': instructions, 'policy': rules,
                 'calibration': calibration, 'source_pins': pins}
    # Preserve the real all-tier builder failure; these probes exercise the code-selected full tier.
    all_tier_error = None
    try:
        builder.build([deepcopy(plan)], **arguments)
    except (ValueError, RuntimeError) as exc:
        all_tier_error = {'type': type(exc).__name__, 'message': str(exc)}
    # This module was loaded privately above. Installed policy, instructions and global TIERS stay intact.
    builder.TIERS = ('full',)
    pins['candidate/projection-tiers'] = records.digest(['full'])
    envelopes = builder.build([deepcopy(plan)], **arguments)
    assert set(envelopes['routes']['calculation']) == {'full'}
    original_data = engagement.data

    def data(name):
        return deepcopy(envelopes) if name == 'envelopes.json' else original_data(name)

    nc.patch.setattr(engagement, 'data', data)
    # Engagement decisions read the content-pinned installed projection. This candidate (fixture plan, candidate
    # pins, full tier only) is never an installed one, so the probe binds it explicitly where decisions read it;
    # the binding record above names its digest and pins.
    from ravel.controller.engagement import envelope as projection
    nc.patch.setattr(projection, 'installed_projection', lambda: deepcopy(envelopes))
    result = {'label': LABEL, 'aliases': deepcopy(ALIASES), 'envelopes': envelopes,
              'installed_projection': installed_data('envelopes.json'), 'calibration': calibration,
              'projection_tiers': ['full'], 'unsupported_tiers': ['lean', 'standard'],
              'all_tier_builder_error': all_tier_error,
              'installed_synthetic_selector_errors': installed_selector_errors,
              'floor_step_normalization': {'roles': deepcopy(FLOOR_ROLES), 'attack_protocols': ['P8']}}
    nc._engagement_candidate_binding = result
    return result


def bind_optional_context_fixture(nc, *, card, step):
    """One synthetic reviewed optional input, scoped to EG13's packet component probe.

    This deliberately supplies a missing test precondition. It is neither an actual
    catalogue review nor a released projection. Source text, ids, hashes and all
    other duty classifications stay exactly as installed.
    """
    catalogue, instructions = require_controller('instructions.catalogue', 'instructions')
    installed = catalogue.installed()
    base = instructions.manifest(step, card)
    required = {unit['id'] for unit in base['units']}
    optional = next((unit for unit in installed.document['units']
                     if unit['id'].startswith('docs/') and unit['id'] not in required
                     and unit.get('form') != 'heading'), None)
    assert optional is not None, 'EG13 fixture requires a real optional source outside the base manifest'
    document, manifests = deepcopy(installed.document), deepcopy(installed.manifests)
    unit = next(unit for unit in document['units'] if unit['id'] == optional['id'])
    old_kind = unit['kind']
    review = {'id': unit['id'], 'sha256': unit['sha256'], 'kind': 'context',
              'reviewed_by': 'fictional-EG13-fixture-review',
              'reason': 'Synthetic packet-test optional input only; not an actual release catalogue review.'}
    unit.update(kind='context', context_review=review)
    document = catalogue._seal(document)
    manifests['catalogue_sha256'] = document['sha256']
    manifests = catalogue._seal(manifests)
    bound = catalogue.Catalogue(document, manifests)
    assert bound.document['files'] == installed.document['files']
    assert bound.units[unit['id']]['text'] == installed.units[unit['id']]['text']
    assert bound.units[unit['id']]['sha256'] == installed.units[unit['id']]['sha256']
    for original in installed.document['units']:
        if original['id'] != unit['id']:
            assert next(row for row in bound.document['units'] if row['id'] == original['id']) == original
    nc.patch.setattr(catalogue, 'installed', lambda: bound)
    from ravel.controller.engagement.records import digest
    metadata = {'label': 'EG13 synthetic reviewed optional unit; component fixture only',
                'installed_context_units': sum(row['kind'] == 'context' for row in installed.document['units']),
                'installed_catalogue_sha256': installed.sha256,
                'fixture_catalogue_sha256': bound.sha256,
                'installed_manifests_sha256': installed.manifests.get('sha256'),
                'fixture_manifests_sha256': bound.manifests['sha256'],
                'source_files_sha256': digest(installed.document['files']),
                'unit': {'id': unit['id'], 'sha256': unit['sha256'], 'original_kind': old_kind},
                'context_review': review, 'release_review_claim': False,
                'projection_scope': 'Existing calculation/full candidate predates this packet-only fixture.'}
    return bound, metadata
