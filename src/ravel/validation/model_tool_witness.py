"""Independent card, kinematic and numerical witnesses for native UFO checks.

These checks do not derive a Lagrangian or an independent matrix element.
They adjudicate observed native evaluations, not a general model's validity.
"""
import math


def finite(value, label):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite real number')
    return float(value)


def card_values(text):
    """Read explicit scalar LHA addresses, refusing ambiguity and Auto widths."""
    values, block = {}, None
    for number, line in enumerate(text.splitlines(), 1):
        tokens = line.split('#', 1)[0].split()
        if not tokens:
            continue
        head = tokens[0].lower()
        if head == 'block':
            if len(tokens) != 2:
                raise ValueError('only unscaled explicit parameter-card blocks are supported')
            block = tokens[1].lower()
            continue
        if head == 'decay':
            if len(tokens) != 3 or tokens[2].lower() == 'auto':
                raise ValueError('explicit finite DECAY widths required; Auto is unsupported')
            address = ('decay', (int(tokens[1]),))
            value = finite(float(tokens[2].replace('D', 'E').replace('d', 'e')), 'width')
            if value < 0:
                raise ValueError('negative DECAY width')
            block = None
        elif block is not None:
            if len(tokens) < 2:
                raise ValueError('missing parameter-card address/value')
            address = (block, tuple(int(x) for x in tokens[:-1]))
            value = finite(float(tokens[-1].replace('D', 'E').replace('d', 'e')), 'card value')
        else:
            raise ValueError('decay tables or rows outside explicit parameter blocks are unsupported')
        if address in values:
            raise ValueError('duplicate parameter-card address at line ' + str(number))
        values[address] = value
    if not values:
        raise ValueError('empty parameter card')
    return values


def effective_card(snapshot, supplied):
    rows = snapshot['external_parameters']
    if not rows:
        raise ValueError('native evaluator emitted no external parameters')
    seen = set()
    for row in rows:
        address = (row['block'].lower(), tuple(row['codes']))
        if address in seen or address not in supplied:
            raise ValueError('duplicate or unsupplied native external parameter')
        seen.add(address)
        value = row['observed_value']
        if (set(value) != {'real', 'imag'} or finite(value['imag'], 'imaginary parameter') != 0
                or finite(value['real'], 'observed parameter') != supplied[address]):
            raise ValueError('native effective parameter differs from the explicit supplied card')
    if seen != set(supplied):
        raise ValueError('supplied card has addresses not consumed by the full source UFO')
    for collection in ('parameters', 'couplings'):
        if not snapshot[collection]:
            raise ValueError('native ' + collection + ' census is empty')
        for value in snapshot[collection].values():
            finite(value['real'], collection)
            finite(value['imag'], collection)
    return len(rows)


def consistency(values):
    values = [finite(x, 'matrix element') for x in values]
    if len(values) < 2 or any(x <= 0 for x in values):
        raise ValueError('nonvacuous consistency needs multiple positive matrix elements')
    return 2 * (max(values) - min(values)) / (max(values) + min(values))


def phase_space(row, process, energy):
    momenta = row['momenta_gev']
    pdgs = process['initial_pdgs'] + process['final_pdgs']
    if row['ordered_leg_pdgs'] != pdgs or len(momenta) != 4:
        raise ValueError('native phase-space leg identities differ from the supplied process')
    if (row['ordered_leg_states'] != [False, False, True, True]
            or row['effective_orders'] != process['orders']
            or row['effective_forbidden_pdgs'] != process['forbidden_pdgs']
            or row['effective_perturbation_couplings'] != []):
        raise ValueError('native effective process differs from the declared tree process')
    for pdg, p in zip(pdgs, momenta):
        if len(p) != 4:
            raise ValueError('native momentum must contain E,px,py,pz')
        p = [finite(x, 'momentum') for x in p]
        mass = finite(row['effective_masses_gev'][str(pdg)], 'effective external mass')
        scale = max(1., p[0] ** 2, mass ** 2)
        if p[0] <= 0 or mass < 0 or abs(p[0] ** 2 - math.fsum(x*x for x in p[1:]) - mass*mass) > 1e-8 * scale:
            raise ValueError('native external momentum is off shell')
    incoming = [math.fsum(p[i] for p in momenta[:2]) for i in range(4)]
    outgoing = [math.fsum(p[i] for p in momenta[2:]) for i in range(4)]
    if any(abs(a-b) > 1e-8 * max(1., incoming[0]) for a, b in zip(incoming, outgoing)):
        raise ValueError('native phase-space point violates momentum conservation')
    squared = incoming[0] ** 2 - math.fsum(x*x for x in incoming[1:])
    if squared <= 0 or not math.isclose(math.sqrt(squared), energy, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError('native silently changed the requested centre-of-mass energy')


def adjudicate(native, config, card_text):
    supplied = card_values(card_text)
    expected = {(p['id'], seed) for p in config['processes'] for seed in config['seeds']}
    observed = {(r['process_id'], r['seed']) for r in native['checks']}
    if len(native['checks']) != len(expected) or observed != expected:
        raise ValueError('native process/seed coverage differs from the exact task')
    if native['restriction_applied'] is not False:
        raise ValueError('bridge must retain the full source UFO without implicit restriction')
    processes = {p['id']: p for p in config['processes']}
    failures, points, card_count = [], 0, 0
    for row in native['checks']:
        try:
            effective_card(native['model_point'], supplied)
            if len(row['evaluator_snapshots']) != 2:
                raise ValueError('both native check evaluators must expose their effective cards')
            for snapshot in row['evaluator_snapshots']:
                card_count += effective_card(snapshot, supplied)
            if any(snapshot != native['model_point'] for snapshot in row['evaluator_snapshots']):
                raise ValueError('native checks used different effective model points')
            if row['permutation']['native_passed'] is not True:
                raise ValueError('native permutation check failed')
            if consistency(row['permutation']['values']) >= 1e-8:
                raise ValueError('independent permutation comparison failed')
            if consistency(row['lorentz']['m2_values']) >= 1e-8:
                raise ValueError('independent Lorentz comparison failed or was vacuous')
            if len(row['evaluations']) < 2:
                raise ValueError('native evaluator observations are missing')
            for point in row['evaluations']:
                phase_space(point, processes[row['process_id']], config['energy_gev'])
                if finite(point['m2'], 'observed matrix element') <= 0:
                    raise ValueError('zero native amplitude is not a passing witness')
                points += 1
        except (ValueError, KeyError, TypeError) as exc:
            failures.append({'process_id': row['process_id'], 'seed': row['seed'], 'reason': str(exc)})
    return {'passed': not failures, 'failures': failures, 'process_seed_cases': len(expected),
            'observed_phase_points': points, 'observed_external_parameter_checks': card_count,
            'scope': 'Explicit-card fidelity, on-shell/conservation/energy checks and native tree numerical consistency.',
            'independent_amplitude_or_lagrangian_validation': False}
