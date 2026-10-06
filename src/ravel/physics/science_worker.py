"""Private supervised entrypoint for approved supplied-data scientific studies."""
from pathlib import Path
import sys
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow import execution
from ravel.workflow.science import SPEC, verify_worker, regular


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise ValueError('one approved run directory required')
    rd = Path(args[0]).resolve()
    proposal = verify_worker(rd)
    spec = read_json(rd / SPEC)
    out = rd / 'outputs'
    out.mkdir(exist_ok=False)
    mode, task, base = spec['mode'], spec['task'], Path(proposal['base_dir'])
    if mode == 'quantities':
        import json
        from ravel.physics.quantities import calculate
        contract = read_json(regular(task['contract'], base))
        # Strict JSON per row, including duplicate keys and nonfinite numbers.
        from ravel.workflow.state_io import _unique
        def reject(s):
            raise ValueError('nonfinite record: ' + s)
        with regular(task['records'], base).open() as stream:
            records = (json.loads(line, object_pairs_hook=_unique, parse_constant=reject) for line in stream if line.strip())
            result = calculate(contract, records)
        atomic_json(out / 'quantities.json', result)
        result = {'status': 'passed', 'physics_validated': False, 'quantities': result,
                  'scope': 'Declared weighted bin quantities and conditional group MC covariance',
                  'limitations': ['Weight semantics and fills are supplied; this does not validate an event generator.']}
    else:
        from importlib import import_module
        module = import_module('ravel.physics.' + {'analyze': 'existing_events', 'measurement': 'measurement', 'domain': 'domain_adapters'}[mode])
        result = module.run(task, base, out / 'measurement' if mode == 'measurement' else out)
    # No module may silently upgrade adapter delivery to scientific certification.
    if result.get('physics_validated') is not False:
        raise ValueError('adapter must state its scientific evidence boundary')
    status = result.get('status')
    if status not in ('passed', 'failed'):
        raise ValueError('adapter result lacks an explicit postcondition status')
    atomic_json(out / 'result.json', result)
    from ravel.plotting.science_figures import render
    figures = render(spec, result, base, out)
    atomic_json(out / 'figures.json', figures)
    atomic_json(out / 'recipe.json', {'specification': spec, 'input_snapshot': proposal['stage_binding']['input_snapshot'],
                                     'sha256': execution.digest(spec)})
    atomic_json(out / 'verification.json', {'passed': status == 'passed', 'scope': mode,
        'physics_validated': False, 'expert_review': False, 'result_sha256': execution.file_hash(out / 'result.json')})
    atomic_json(out / 'checkin2.json', {'schema_version': 1, 'kind': 'checkin2', 'sections': {
        'waypoint': {'scope': mode, 'status': status, 'result': 'outputs/result.json'},
        'expectation': 'Review the declared quantities and comparisons. Adapter checks do not establish detector fidelity, paper closure or expert review.',
        'ask': {'options': ['GO', 'ADJUST'], 'scope': 'Any follow-up calculation requires its own concrete plan and approval.'}}})
    (out / 'RESULT.md').write_text('# Scientific adapter result\n\n' + mode + ': ' + status + '.\n\n' +
        ''.join('![Diagnostic](' + f['stem'] + '.png)\n\n' for f in figures.get('figures', [])) +
        'The values, postconditions and limitations are in `result.json`. The exact input identities are in '
        '`recipe.json`; review `checkin2.json` before additional work.\n\nAssumptions:\n\n' +
        '\n'.join('- ' + a for a in spec['assumptions']) + '\n\nNo paper reproduction or physics certification is inferred.\n')
    return 0 if status == 'passed' else 3


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError, ImportError, RuntimeError) as exc:
        print('Scientific study failed: ' + str(exc), file=sys.stderr)
        sys.exit(2)
