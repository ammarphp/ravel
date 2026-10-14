"""One frontend for an explicitly selected supplied reconstructed-selection package."""
from .sa_native_core import (Lester, _ellipse, _helper, get_mT2, Obj, ELECTRON, MUON, ME, MMU,
    NotBit, NOT, LooseBadJet, JVT50Jet, LessThan3Tracks, BTag85MV2c10,
    filterObjects, countObjects, overlapRemoval, concat_sorted, invmass, pairDeltaPhi_to_met,
    calcMT, calcMTauTau, calcAMT2, minDphi, load_ntuple, write_txt, write_root, _g, CONDA)
from pathlib import Path
from .analysis_packages import load_routine, load_package, PackageInputError, selected_attribute


def __getattr__(name):
    return selected_attribute(name)


def main(argv=None):
    import argparse
    from .sa_native_core import run_counting_routine
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis-package', required=True, help='supplied analysis-package/v1 manifest')
    parser.add_argument('--execution-plan', required=True, help='approved supervised native plan')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--routine', required=True, help='selected package identity')
    parser.add_argument('--ngen', type=int)
    args, remaining = parser.parse_known_args(argv)
    from .native_pipeline import load_plan, verify_native_stage_authority, verify_execution_approval
    plan = load_plan(args.execution_plan)
    verify_execution_approval(plan)
    from ravel.workflow.execution import load_execution
    stage = next(item for item in plan['stages'] if item['stage'] == 'simpleanalysis')
    running = load_execution(plan['rundir'])['stages'].get('simpleanalysis', {})
    if running.get('status') != 'running' or running.get('command') != stage['command']:
        raise PackageInputError('missing_supervised_stage')
    if (str(args.input) != str(stage['inputs'][0]) or str(args.output) != str(Path(stage['outputs'][0]).parent)
            or args.ngen != plan['nevents']):
        raise PackageInputError('package_plan_mismatch')
    if plan['capability'].get('analysis_package') != str(load_package(args.analysis_package)['manifest_path']):
        raise PackageInputError('package_plan_mismatch')
    verify_native_stage_authority(plan, 'simpleanalysis', inside_supervised=True)
    routine = load_routine(args.analysis_package, require_qualification=True)
    if args.routine != routine.NAME:
        raise PackageInputError('package_plan_mismatch')
    kind = routine.ANALYSIS_PACKAGE['routine']['kind']
    if kind == 'counting':
        if remaining:
            parser.error('counting interface has no undeclared arguments')
        run_counting_routine(routine, args.input, args.output, args.ngen)
    elif kind == 'two-pass':
        routine.run(['--input', args.input, '--output', args.output, '--routine', args.routine,
                     *(['--ngen', str(args.ngen)] if args.ngen is not None else []), *remaining])
    else:
        raise PackageInputError('unsupported_routine_interface')


if __name__ == '__main__':
    main()
