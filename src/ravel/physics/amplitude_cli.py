"""``ravel amplitudes``: inspect amplitude-basis documents and prepare ordinary studies.

Subcommands (none of them computes a result):

- ``modes``: list the amplitude-basis science modes;
- ``research-parents``: list registered amplitude research-parent instances and their stages;
- ``example --mode M``: print a small example document for a mode (illustrative values);
- ``check --mode M --input doc.json``: validate a document and list every input file with its sha256;
- ``spec --mode M --input doc.json --policy review.json --source TEXT --assumption TEXT [...]
  --max-seconds N --out spec.json``: write the schema 2 study specification for ``ravel plan``.

Computation runs through ``ravel plan``, ``ravel approve`` and ``ravel run``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from importlib import import_module
from pathlib import Path

MODES = {
    'amplitude-integration': ('amplitude_integration', 'integrate with an amplitude program (MCFM) through the execution backend into a resumable Gram store'),
    'amplitude-predictions': ('amplitude_predictions', 'binned predictions for any coupling, mass, width and propagator from a Gram store'),
    'weighted-events': ('weighted_events', 'stored points as LHE or HepMC3 events with named weights; Rivet RAW normalization'),
    'amplitude-crosscheck': ('amplitude_crosscheck', 'independent JHUGen/MELA matrix elements at stored points'),
}

_HYPOTHESIS = {'id': 'S600', 'constant': {'continuum': 1}, 'states': [
    {'mass_gev': 125.0, 'width_gev': 0.0041, 'propagator': 'fixed-width', 'couplings': {'scalar_bottom': 1, 'scalar_top': 1}},
    {'mass_gev': 600.0, 'width_gev': 60.0, 'propagator': 'running-width', 'couplings': {'scalar_top': 0.4}}]}
_REFERENCE = {'id': 'SM', 'constant': {'continuum': 1}, 'states': [_HYPOTHESIS['states'][0]]}
EXAMPLES = {
    'amplitude-predictions': {
        'schema_version': 1, 'kind': 'amplitude-predictions', 'store': 'store', 'hypotheses': [_REFERENCE, _HYPOTHESIS],
        'reference': 'SM', 'reference_description': 'continuum and 125 GeV Higgs boson from the stored amplitudes',
        'observable': {'name': 'mass_gev', 'label': 'Four-lepton invariant mass', 'unit': 'GeV', 'invariant': 's_gev2'},
        'binning': {'hepdata': {'path': 'table.yaml', 'sha256': '<sha256 of the table>', 'variable': 0}},
        'selection': [], 'normalization': {'unit': 'fb', 'representation': 'differential'},
        'coupling_scaling': {'parameter': 'kappa', 'power': 1, 'states': [1], 'mc_covariance_at': 1.0}},
    'amplitude-integration': {
        'schema_version': 1, 'kind': 'amplitude-integration', 'addon': 'mcfm-amplitudes', 'operation': 'blocks', 'store': 'store',
        'backend': {'kind': 'oci-local', 'program': '/opt/mcfm/ravel_mcfm_amplitudes', 'workdir': '/work',
                    'image': {'reference': '<registry/name@sha256:...>', 'platform': 'linux/arm64'},
                    'resources': {'cpus': 1, 'memory_mib': 4096}},
        'cohorts': [{'id': 'mixed', 'channel': 1, 'card': {'path': 'mixed.ini', 'sha256': '<sha256>'},
                     'warmup': {'draws': 100000, 'seed': 11, 'max_seconds': 3600}}],
        'schedule': {'schema_version': 1, 'max_operation_seconds': 36000, 'blocks': [
            {'id': f'mixed-{i}', 'cohort': 'mixed', 'seed': 21 + i, 'draws': 50000, 'max_seconds': 3600} for i in range(4)]},
        'audit_points': 16},
    'weighted-events': {
        'schema_version': 1, 'kind': 'weighted-events', 'operation': 'rivet', 'store': 'store',
        'hypotheses': [_REFERENCE, _HYPOTHESIS], 'reference': 'SM', 'reference_description': 'continuum and 125 GeV Higgs boson',
        'invariant': 's_gev2', 'scale': 'factorization_scale_gev', 'beams': {'pdg': 2212, 'sqrt_s_gev': 13000.0},
        'max_streams': 150, 'format': 'hepmc3', 'unit': 'fb',
        'rivet': {'program': 'rivet', 'analyses': ['<routine>'], 'options': ['--ignore-beams'],
                  'histograms': [{'path': '/<routine>/d01-x01-y01', 'label': 'Four-lepton invariant mass', 'unit': 'GeV',
                                  'representation': 'differential'}]},
        'backend': {'kind': 'native', 'resources': {'cpus': 1, 'memory_mib': 2048, 'wall_seconds': 3600}}},
    'amplitude-crosscheck': {
        'schema_version': 1, 'kind': 'amplitude-crosscheck', 'store': 'store', 'block': 'mixed-0', 'max_points': 200,
        'tolerance': 1e-3, 'hypothesis': _REFERENCE,
        'mela': {'sqrts_tev': 13, 'reference_mass_gev': 125.0, 'verbosity': 'ERROR',
                 'process': ['bkgZZ_SMHiggs', 'JHUGen', 'ZZGG'],
                 'resonances': [{'index': 0, 'mass_gev': 125.0, 'width_gev': 0.0041}],
                 'couplings': {'ghz1': [2.0, 0.0]}, 'call': 'computeP'},
        'backend': {'kind': 'oci-local', 'program': 'python3', 'workdir': '/work',
                    'image': {'reference': '<registry/name@sha256:...>', 'platform': 'linux/arm64'},
                    'resources': {'cpus': 1, 'memory_mib': 2048, 'wall_seconds': 600}}},
}


def _module(mode):
    if mode not in MODES:
        raise ValueError('mode must be one of ' + ', '.join(MODES))
    return import_module('ravel.physics.' + MODES[mode][0])


def check(mode, document):
    module = _module(mode)
    task = {'input': str(Path(document).absolute())}
    module.validate(task)
    paths = module.inputs(task, Path.cwd())
    return {'mode': mode, 'status': 'checked', 'compute_authorized': False,
            'inputs': [{'path': str(p), 'sha256': hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in paths],
            'next': 'ravel amplitudes spec ... then ravel plan --rundir <new-dir> --spec <spec.json>'}


def specification(mode, document, *, policy, source, assumptions, max_seconds, approval_mode):
    check(mode, document)
    if not assumptions:
        raise ValueError('state at least one assumption')
    return {'schema_version': 2, 'mode': mode, 'source': source, 'assumptions': list(assumptions),
            'max_seconds': max_seconds, 'max_attempts': 1, 'approval_mode': approval_mode,
            'task': {'input': str(Path(document).absolute())}, 'review_policy': json.loads(Path(policy).read_text())}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel amplitudes', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('modes', help='list the amplitude-basis science modes')
    sub.add_parser('research-parents', help='list research-parent instances; no execution')
    ex = sub.add_parser('example', help='print an example document')
    ex.add_argument('--mode', required=True, choices=list(MODES))
    ck = sub.add_parser('check', help='validate a document and list its inputs; no computation')
    ck.add_argument('--mode', required=True, choices=list(MODES))
    ck.add_argument('--input', required=True, type=Path)
    sp = sub.add_parser('spec', help='write a schema 2 study specification for ravel plan')
    sp.add_argument('--mode', required=True, choices=list(MODES))
    sp.add_argument('--input', required=True, type=Path)
    sp.add_argument('--policy', required=True, type=Path, help='review policy JSON')
    sp.add_argument('--source', required=True, help='scientific source of the inputs')
    sp.add_argument('--assumption', action='append', default=[], help='one numbered assumption; repeat')
    sp.add_argument('--max-seconds', type=int, default=3600)
    sp.add_argument('--approval-mode', choices=('physicist', 'scripted_yes'), default='physicist')
    sp.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == 'research-parents':
        from .amplitude_chain import instances
        print(json.dumps(instances(), indent=2))
        return 0
    if args.command == 'modes':
        print(json.dumps([{'mode': m, 'summary': s} for m, (_, s) in MODES.items()], indent=2))
    elif args.command == 'example':
        print(json.dumps(EXAMPLES[args.mode], indent=2))
    elif args.command == 'check':
        print(json.dumps(check(args.mode, args.input), indent=2))
    else:
        value = specification(args.mode, args.input, policy=args.policy, source=args.source, assumptions=args.assumption,
                              max_seconds=args.max_seconds, approval_mode=args.approval_mode)
        with args.out.open('x') as stream:
            stream.write(json.dumps(value, indent=2) + '\n')
        print(f'wrote {args.out}; next: ravel plan --rundir <new-dir> --spec {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
