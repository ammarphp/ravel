"""Synthetic siblings for a composed interference measurement; no native tools."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

from ravel.physics import amplitude_integration as integration, weighted_events as events
from ravel.workflow import route_prompt, task_completion
from test_amplitude_integration import FakeBackend
from test_weighted_events import _yoda


def pin(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    return pin(path)


class RawBackend:
    """An inert routine which fills every named weight from exported events."""
    def __init__(self, edges, reference):
        self.edges, self.reference, self.calls = edges, reference, []

    def prepare(self, spec, *, base=None):
        self.calls.append(spec['stage'])
        return {'spec': spec, 'plan_sha256': 'a' * 64, 'backend': {'local': True}}

    def submit(self, plan, attempt_dir):
        stage = Path(plan['spec']['inputs'][0]['path']).parent
        population = events.read_hepmc3(stage / 'events.hepmc')
        text = ''
        for name in population['weight_names']:
            rows = np.zeros((len(self.edges) + 1, 2))
            for event in population['events']:
                momentum = np.sum([p['momentum'] for p in event['particles'] if p['status'] == 1], axis=0)
                mass = np.sqrt(momentum[3] ** 2 - momentum[:3] @ momentum[:3])
                index = np.searchsorted(self.edges, mass, side='right')
                weight = event['weights'][name]
                rows[index] += (weight, weight * weight)
            text += _yoda(events.raw_path('/SYN/m', name, self.reference), self.edges, rows.tolist())
        (stage / 'rivet.yoda').write_text(text)
        return {}

    def observe(self, plan, handle):
        return {'state': 'succeeded'}

    def fetch(self, plan, handle, base):
        return {}


def case(base, monkeypatch):
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    question = 'Investigate a synthetic interference measurement and report Delta(-2 ln L) <= 1 on the supplied domain.'
    contract = route_prompt.route(question)
    contract['task_requirements'] = task_completion.initial_requirements(question)
    contract['task_requirements']['assignments'] = [{'id': 'interference', 'purpose': 'Compose all supplied stages',
        'coverage': [{'obligation_id': 'original-request', 'criteria': {'request': question}}]}]
    goal = {'contract': write(base / 'original/inputs/task_contract.json', contract), 'assignment_id': 'interference'}
    addon_root = base / 'addons/synthetic-amplitudes'
    addon_root.mkdir(parents=True)
    (addon_root / 'protocol.txt').write_text('Synthetic record contract, no executable.\n')
    protocol = {'format': 'RAVEL_MCFM_2', 'channels': {'1': {'pdg': [21, 21, 11, -11, 13, -13]}},
        'amplitude_channels': ['up', 'down', 'bottom', 'top', 'hbottom', 'htop'],
        'members': {'continuum': {'sum': {'up': 2, 'down': 2, 'bottom': 1, 'top': 1}},
                    'numerator': {'sum': {'htop': 1}, 'per_reference_propagator': True}},
        'oracle_continuum_member': 'continuum',
        'factor': ['grid_weight_over_n', 'phase_space', 'flux', 'pdf_product'],
        'factor_divisor': 'branching_ratio', 'factor_unit': 'fb',
        'operations': {'warmup': 1, 'block': 2, 'points': 3}, 'grid_file': 'proposal-grid.bin'}
    # The synthetic oracle includes exactly the two declared basis members.
    protocol['members']['reference-numerator'] = {'sum': {'hbottom': 1}, 'per_reference_propagator': True}
    write(addon_root / 'addon.json', {'schema_version': 1, 'name': addon_root.name, 'license': 'synthetic',
        'summary': 'Inert synthetic fixture', 'files': {'protocol.txt': pin(addon_root / 'protocol.txt')['sha256']},
        'protocol': protocol})
    monkeypatch.setenv('RAVEL_ADDON_PATH', str(addon_root.parent))
    card = base / 'input.ini'
    card.write_text('[integration]\nseed = 0\n')
    integrate = {'schema_version': 1, 'kind': 'amplitude-integration', 'addon': addon_root.name,
        'operation': 'blocks', 'store': 'store', 'backend': {'kind': 'native', 'program': '/inert/adapter',
            'resources': {'cpus': 1, 'memory_mib': 64}},
        'cohorts': [{'id': 'c', 'channel': 1, 'card': {k: pin(card)[k] for k in ('path', 'sha256')},
            'warmup': {'draws': 3, 'seed': 11, 'max_seconds': 10}}],
        'schedule': {'schema_version': 1, 'max_operation_seconds': 30, 'blocks': [
            {'id': f'b{i}', 'cohort': 'c', 'seed': 20 + i, 'draws': 5, 'max_seconds': 10} for i in range(2)]},
        'audit_points': 2}
    reference = {'id': 'reference', 'constant': {'continuum': 1}, 'states': [
        {'mass_gev': 125.0, 'width_gev': 0.004, 'propagator': 'fixed-width',
         'couplings': {'numerator': 1, 'reference-numerator': 1}}]}
    candidate = deepcopy(reference)
    candidate['id'] = 'candidate'
    candidate['states'].append({'mass_gev': 500.0, 'width_gev': 50.0, 'propagator': 'fixed-width',
                               'couplings': {'numerator': 0.7}})
    edges = [0., 300., 2000.]
    prediction = {'schema_version': 1, 'kind': 'amplitude-predictions', 'store': 'store',
        'hypotheses': [reference, candidate], 'reference': 'reference', 'reference_description': 'Synthetic reference',
        'observable': {'name': 'mass_gev', 'label': 'Synthetic mass', 'unit': 'GeV', 'invariant': 's_gev2'},
        'binning': {'edges': edges}, 'selection': [], 'normalization': {'unit': 'fb', 'representation': 'integrated'},
        'coupling_scaling': {'parameter': 'kappa', 'power': 1, 'states': [1], 'mc_covariance_at': 1.0}}
    event_doc = {'schema_version': 1, 'kind': 'weighted-events', 'operation': 'rivet', 'store': 'store',
        'hypotheses': [reference, candidate], 'reference': 'reference', 'reference_description': 'Synthetic reference',
        'invariant': 's_gev2', 'scale': 'factorization_scale_gev', 'beams': {'pdg': 2212, 'sqrt_s_gev': 13000.},
        'max_streams': 3, 'format': 'hepmc3', 'unit': 'fb',
        'coupling_scaling': deepcopy(prediction['coupling_scaling']),
        'rivet': {'program': '/inert/routine', 'analyses': ['SYN'], 'options': [],
            'histograms': [{'path': '/SYN/m', 'label': 'Synthetic mass', 'unit': 'GeV', 'representation': 'integrated'}]},
        'backend': {'kind': 'native', 'resources': {'cpus': 1, 'memory_mib': 64, 'wall_seconds': 10}}}
    measurement = {'schema_version': 1, 'kind': 'interference-measurement-input',
        'statistic': {'verbatim': 'Delta(-2 ln L) <= 1', 'test_statistic': 'two-sided', 'threshold': 1., 'objective': 'chi2'},
        'observable': {'name': 'mass_gev', 'unit': 'GeV', 'label': 'Synthetic mass'},
        'measurement': {'values': [1., 0.6], 'unit': 'fb', 'bin_edges': edges},
        'covariance': [{'name': 'synthetic experimental', 'law': 'fixed', 'matrix': [[1., .1], [.1, .5]],
                        'source': 'Synthetic supplied covariance'}],
        'scan': {'parameter': 'kappa', 'min': 0., 'max': 2., 'points': 7}, 'domain': [0., 2.]}
    conventions = {'schema_version': 1, 'kind': 'interference-conventions',
        'phase_convention': 'Synthetic complex amplitudes in a common basis',
        'interference_definition': '2 Re(A_fixed* A_scaled)',
        'interpretation_traps': ['A signed difference is not a positive signal yield',
                                 'A measurement interval is not a discovery claim'],
        'assumptions': ['1. Synthetic algebra and mock tool outputs only.']}
    comparison = {'schema_version': 1, 'kind': 'interference-comparator',
        'statistic': measurement['statistic'], 'quantity': 'coupling interval', 'unit': '1',
        'source': 'Synthetic supplied comparison; no empirical claim', 'values': [[0., 2.]]}
    request = {'schema_version': 1, 'kind': 'interference-research-request', 'question': question, 'goal_binding': goal,
        'conventions': write(base / 'conventions.json', conventions),
        'integration': write(base / 'integration.json', integrate),
        'events': write(base / 'events-input.json', event_doc), 'histogram': '/SYN/m',
        'predictions': write(base / 'predictions-input.json', prediction),
        'measurement': write(base / 'measurement-input.json', measurement),
        'comparison': write(base / 'comparison.json', comparison)}
    return request, FakeBackend(), RawBackend(edges, reference['id'])


def runners(integration_backend, raw_backend):
    def run_integration(stage, *, base_dir, output_dir, goal_binding):
        return integration.run({'input': stage['input']['path']}, base_dir, output_dir, backend=integration_backend)

    def run_events(stage, *, base_dir, output_dir, goal_binding):
        return events.run({'input': stage['input']['path']}, base_dir, output_dir, backend=raw_backend)

    return {'amplitude-integration': run_integration, 'weighted-events': run_events}
