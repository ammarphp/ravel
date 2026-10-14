"""Model admission: the checks a UFO must pass before it is used for generation.

``admit(ufo, ...)`` runs every check it has evidence for and returns one record:

* ``ufo-static``: ``ufo_check.check`` (Python 3 parse, Mathematica leftovers,
  PDG codes, mass and width parameters; spec agreement when a ModelSpec is given);
* ``vertex-quantum-numbers``: every additive quantum number the UFO declares on
  its particles (``charge`` and any extra keyword such as ``LeptonNumber``,
  ``GhostNumber`` or ``Y``) sums to zero over every vertex, all legs incoming;
* ``conjugate-vertices``: every non-ghost vertex has a vertex with the
  conjugate particle content, so the Lagrangian contains its Hermitian conjugate;
* ``spec-charge-census``: the ModelSpec charge census, when a spec is given
  (hypercharge and weak-doublet count of every gauge-basis term, electric
  charge of every physical-field term, colour triality, declared lepton number);
* ``hermiticity-feynrules``: the FeynRules ``CheckHermiticity`` verdict from a
  native receipt (two-gauge checks or derivation physical checks), when given;
* ``mg5-check-gauge``, ``mg5-check-lorentz``, ``mg5-check-permutation``: MadGraph
  ``check <kind> <process>`` on the requested process, each in a fresh session;
* ``ward-identity``: recorded as not evaluated (not part of minimal admission).

Every row states what the check cannot detect. The decision is ``refused`` when
any check fails, ``incomplete`` when a required check has no verdict, and
``admitted`` otherwise. The MadGraph runner is injectable so tests never start
MadGraph.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from ravel.physics import ufo_check

SCHEMA = 1
KIND = 'model-admission'
MG5_CHECKS = ('gauge', 'lorentz', 'permutation')
REQUIRED = ('ufo-static', 'vertex-quantum-numbers', 'conjugate-vertices',
            *(f'mg5-check-{k}' for k in MG5_CHECKS))
STATIC_REQUIRED = ('ufo-static', 'vertex-quantum-numbers', 'conjugate-vertices')
STANDARD_KEYS = {'pdg_code', 'name', 'antiname', 'spin', 'color', 'mass', 'width', 'texname', 'antitexname',
                 'charge', 'line', 'propagating', 'goldstoneboson', 'GoldstoneBoson', 'goldstone', 'propagator',
                 'selfconjugate', 'counterterm', 'loop_particles'}
SUMMARY = re.compile(r'Summary:\s*(\d+)/(\d+)\s+passed,\s*(\d+)/(\d+)\s+failed')
SCOPE = ('Tree-level structural admission of a UFO: static parse, per-vertex additive quantum numbers, conjugate '
         'vertex closure, the ModelSpec hypercharge census and FeynRules Hermiticity when supplied, and MadGraph '
         'gauge, Lorentz and permutation checks on the requested process.')
CANNOT_DETECT = {
    'ufo-static': ['wrong numerical values or wrong analytic coupling expressions',
                   'Lorentz or colour structures that parse but are physically wrong'],
    'vertex-quantum-numbers': ['quantum numbers the UFO does not declare on its particles',
                               'hypercharge in a broken-phase UFO: mass eigenstates carry Y = 0, so the sum is vacuous',
                               'colour flow and non-additive (multiplicative or discrete) symmetries'],
    'conjugate-vertices': ['a conjugate vertex whose coupling is not the complex conjugate of the original',
                           'ghost vertices, which are skipped (the ghost Lagrangian is not Hermitian term by term)'],
    'spec-charge-census': ['terms the ModelSpec does not list; it checks the spec, not the generated UFO',
                                'whether the spec matches the supplied Lagrangian'],
    'hermiticity-feynrules': ['parts of the Lagrangian the receipt did not check (two-gauge checks cover the new terms)',
                              'errors introduced after FeynRules, in the UFO export or by hand edits'],
    'mg5-check-gauge': ['gauge dependence in processes without massive vector bosons, where the check is vacuous',
                        'processes other than the requested one; loop-level gauge invariance'],
    'mg5-check-lorentz': ['Lorentz violation that cancels at the sampled phase-space points',
                          'processes other than the requested one'],
    'mg5-check-permutation': ['errors symmetric under the permutations of external legs MadGraph tries',
                              'processes other than the requested one'],
    'ward-identity': ['not run by minimal admission; gauge-current conservation on the requested process is unchecked'],
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
                          .encode()).hexdigest()


def tree_digest(root):
    """Digest of the {relative path: sha256} map of every regular file outside caches."""
    root = Path(root)
    files = {p.relative_to(root).as_posix(): _sha(p) for p in sorted(root.rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    return _digest(files)


def _row(check_id, status, **detail):
    return {'id': check_id, 'status': status, 'required': check_id in REQUIRED,
            'cannot_detect': CANNOT_DETECT[check_id], **detail}


def _parse(ufo, name):
    return ast.parse((Path(ufo) / name).read_text(errors='replace'))


def particle_table(ufo):
    """Particle variables from particles.py, including ``X = Y.anti()`` with negated quantum numbers."""
    table, problems = {}, []
    for stmt in _parse(ufo, 'particles.py').body:
        if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.targets[0], ast.Name)):
            continue
        var, call = stmt.targets[0].id, stmt.value
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == 'anti' and isinstance(func.value, ast.Name):
            base = table.get(func.value.id)
            if base is None:
                problems.append(f'{var}: anti() of undeclared particle {func.value.id}')
                continue
            table[var] = {'name': base['antiname'], 'antiname': base['name'], 'pdg': -base['pdg'],
                          'spin': base['spin'], 'self_conjugate': False, 'anti': func.value.id,
                          'quantum_numbers': {k: -v for k, v in base['quantum_numbers'].items()}}
            base['anti'] = var
            continue
        if ufo_check._call_name(call) != 'Particle':
            continue
        kw = {k.arg: k.value for k in call.keywords if k.arg}
        name, antiname = ufo_check._literal(kw.get('name')), ufo_check._literal(kw.get('antiname'))
        qn = {}
        for key, node in kw.items():
            if isinstance(node, ast.Constant) and isinstance(node.value, bool):
                continue  # a flag such as GoldstoneBoson = True, not an additive quantum number
            if key == 'charge' or key not in STANDARD_KEYS:
                value = ufo_check._charge(node)
                if value is None:
                    problems.append(f'{var}: quantum number {key} is not a literal number')
                else:
                    qn[key] = value
        if 'charge' not in qn and 'charge' not in kw:
            problems.append(f'{var}: no charge')
        table[var] = {'name': name, 'antiname': antiname, 'pdg': ufo_check._literal(kw.get('pdg_code')),
                      'spin': ufo_check._literal(kw.get('spin')), 'self_conjugate': name == antiname,
                      'anti': var if name == antiname else None, 'quantum_numbers': qn}
    by_name = {row['name']: var for var, row in table.items()}
    for var, row in table.items():
        if row['anti'] is None:
            row['anti'] = by_name.get(row['antiname'])
            if row['anti'] is None:
                problems.append(f'{var}: antiparticle {row["antiname"]} is not declared')
    if problems:
        raise ValueError('; '.join(problems))
    return table


def _vertices(ufo):
    rows = []
    for var, v in ufo_check._objects(_parse(ufo, 'vertices.py'), 'Vertex').items():
        node = v['kw'].get('particles')
        refs = [ufo_check._ref(e) for e in getattr(node, 'elts', [])]
        rows.append({'vertex': var, 'particles': refs})
    return rows


def _fraction_text(value):
    return str(Fraction(value))


def vertex_quantum_numbers(ufo, table=None):
    table = table if table is not None else particle_table(ufo)
    numbers = sorted({k for row in table.values() for k in row['quantum_numbers']})
    vertices = _vertices(ufo)
    violations, undeclared = [], []
    for v in vertices:
        missing = [p for p in v['particles'] if p not in table]
        if missing or not v['particles']:
            undeclared.append({'vertex': v['vertex'], 'particles': missing})
            continue
        for qn in numbers:
            total = sum((table[p]['quantum_numbers'].get(qn, Fraction(0)) for p in v['particles']), Fraction(0))
            if total != 0:
                violations.append({'vertex': v['vertex'], 'quantum_number': qn, 'sum': _fraction_text(total)})
    status = 'fail' if violations or undeclared else 'pass'
    return _row('vertex-quantum-numbers', status, quantum_numbers=numbers, vertices=len(vertices),
                violations=violations, undeclared_particles=undeclared)


def conjugate_vertices(ufo, table=None):
    table = table if table is not None else particle_table(ufo)
    vertices = [v for v in _vertices(ufo) if all(p in table for p in v['particles'])]
    contents = {tuple(sorted(v['particles'])) for v in vertices}
    missing, ghosts = [], 0
    for v in vertices:
        if any(table[p]['spin'] == -1 for p in v['particles']):
            ghosts += 1
            continue
        conjugate = tuple(sorted(table[p]['anti'] for p in v['particles']))
        if conjugate not in contents:
            missing.append({'vertex': v['vertex'], 'particles': sorted(table[p]['name'] for p in v['particles']),
                            'conjugate_particles': sorted(table[p]['name'] for p in conjugate)})
    return _row('conjugate-vertices', 'fail' if missing else 'pass', vertices=len(vertices),
                ghost_vertices_skipped=ghosts, missing=missing)


def hypercharge_check(spec, census=None):
    if census is None:
        if spec is None:
            return _row('spec-charge-census', 'not_evaluated', reason='no ModelSpec was given')
        from ravel.physics import model_authoring
        census = model_authoring.charge_census(spec)
    violations = [{'term': t['term'], 'problems': t['problems']} for t in census['terms'] if not t['passed']]
    return _row('spec-charge-census', 'fail' if violations else 'pass', terms=len(census['terms']),
                violations=violations)


def hermiticity_check(native):
    """FeynRules CheckHermiticity from a two-gauge receipt or a derivation physical-checks receipt."""
    native = native or {}
    gauge = native.get('gauge_checks')
    if isinstance(gauge, dict) and {'feynman', 'unitary'} <= set(gauge):
        verdicts = {}
        for name in ('unitary', 'feynman'):
            row = (gauge.get(name) or {}).get('CheckHermiticity') or {}
            verdicts[name] = row.get('holds') is True and row.get('message_free') is True
        return _row('hermiticity-feynrules', 'pass' if all(verdicts.values()) else 'fail', source='two-gauge checks',
                    verdicts=verdicts, lagrangian=(gauge.get('lagrangians') or {}).get('hermiticity_and_kinetic'))
    herm = (native.get('physical_checks') or {}).get('hermiticity')
    if isinstance(herm, dict) and herm.get('requested') is True:
        holds = (herm.get('message_free') is True and herm.get('returned_list') is True
                 and herm.get('vertex_count') == 0)
        return _row('hermiticity-feynrules', 'pass' if holds else 'fail', source='derivation physical checks',
                    non_hermitian_vertex_count=herm.get('vertex_count'))
    return _row('hermiticity-feynrules', 'not_evaluated', reason='no FeynRules CheckHermiticity receipt was given')


def _process_line(process):
    if not isinstance(process, str) or not process.strip() or '\n' in process or ';' in process:
        raise ValueError('one MadGraph process line is required')
    return process.strip()


def mg5_check(ufo, kind, process, *, mg5, workdir, runner=None, timeout=900):
    """``import model`` then ``check <kind> <process>`` in a fresh MadGraph session on a copy of the UFO."""
    if kind not in MG5_CHECKS:
        raise ValueError(f'MadGraph check must be one of {", ".join(MG5_CHECKS)}')
    process = _process_line(process)
    workdir = Path(workdir).absolute()
    workdir.mkdir(parents=True, exist_ok=False)
    model = workdir / Path(ufo).name
    shutil.copytree(ufo, model)  # MadGraph writes caches next to the model; keep the admitted tree untouched
    script = workdir / 'check.mg5'
    script.write_text(f'set auto_update 0\nset automatic_html_opening False\nimport model {model}\n'
                      f'check {kind} {process}\n')
    command = [str(c) for c in (*(mg5 if isinstance(mg5, (list, tuple)) else [mg5]), script)]
    run = runner or (lambda cmd: subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout))
    completed = run(command)
    output = (completed.stdout or '') + '\n' + (completed.stderr or '')
    log = workdir / 'mg5.log'
    log.write_text(output)
    found = SUMMARY.findall(output)
    detail = {'process': process, 'command': command, 'returncode': completed.returncode,
              'log': {'path': str(log), 'sha256': _sha(log)}}
    if not found:
        return _row(f'mg5-check-{kind}', 'error', reason='MadGraph printed no check summary', **detail)
    passed, total, failed, _ = (int(x) for x in found[-1])
    failures = re.findall(r'Failed processes:\s*(.+)', output)
    if failed or passed < total:
        status = 'fail'
    elif total < 1 or completed.returncode != 0:
        status = 'error'
    else:
        status = 'pass'
    return _row(f'mg5-check-{kind}', status, passed_count=passed, total=total, failed_count=failed,
                failed_processes=failures, **detail)


def _decide(rows, required):
    refusals = [f'{r["id"]}: {_reason(r)}' for r in rows if r['status'] == 'fail']
    not_evaluated = [r['id'] for r in rows if r['id'] in required and r['status'] not in ('pass', 'fail')]
    decision = 'refused' if refusals else 'incomplete' if not_evaluated else 'admitted'
    return decision, refusals, not_evaluated


def _reason(row):
    if row['id'] == 'ufo-static':
        return '; '.join(row.get('errors') or [])
    if row['id'] == 'vertex-quantum-numbers':
        parts = [f'{v["vertex"]} {v["quantum_number"]} sums to {v["sum"]}' for v in row['violations']]
        parts += [f'{u["vertex"]} uses undeclared particles {", ".join(map(str, u["particles"]))}'
                  for u in row['undeclared_particles']]
        return '; '.join(parts)
    if row['id'] == 'conjugate-vertices':
        return '; '.join(f'{m["vertex"]} ({" ".join(m["particles"])}) has no conjugate vertex '
                         f'({" ".join(m["conjugate_particles"])})' for m in row['missing'])
    if row['id'] == 'spec-charge-census':
        return '; '.join(f'{v["term"]}: {", ".join(v["problems"])}' for v in row['violations'])
    if row['id'] == 'hermiticity-feynrules':
        return 'FeynRules CheckHermiticity reports non-Hermitian terms'
    return f'{row.get("failed_count")}/{row.get("total")} failed: {", ".join(row.get("failed_processes") or [])}'


def _static_rows(ufo, spec):
    static = ufo_check.check(ufo, spec=spec)
    rows = [_row('ufo-static', 'pass' if static['passed'] else 'fail', errors=static['errors'],
                 warnings=static['warnings'], counts=static.get('counts'))]
    if not all(n in static.get('counts', {}) for n in ('particles', 'vertices')):
        reason = 'the UFO did not parse'
        return rows + [_row(i, 'not_evaluated', reason=reason) for i in ('vertex-quantum-numbers', 'conjugate-vertices')]
    try:
        table = particle_table(ufo)
    except ValueError as exc:
        return rows + [_row(i, 'fail', reason=str(exc), violations=[], undeclared_particles=[], missing=[])
                       for i in ('vertex-quantum-numbers', 'conjugate-vertices')]
    return rows + [vertex_quantum_numbers(ufo, table), conjugate_vertices(ufo, table)]


def _record(ufo, rows, required, **extra):
    decision, refusals, not_evaluated = _decide(rows, required)
    return {'schema_version': SCHEMA, 'kind': KIND, 'ufo': str(Path(ufo).absolute()), 'ufo_digest': tree_digest(ufo),
            **extra, 'decision': decision, 'refusals': refusals, 'not_evaluated': not_evaluated,
            'checks': rows, 'scope': SCOPE}


def static_admission(ufo, *, spec=None):
    """The checks that need no MadGraph: static parse, vertex quantum numbers, conjugate vertices.

    ``decision`` is ``passed`` or ``refused``; this is not an admission.
    """
    rows = _static_rows(ufo, spec)
    record = _record(ufo, rows, STATIC_REQUIRED)
    record['decision'] = 'refused' if record['decision'] == 'refused' else (
        'passed' if record['decision'] == 'admitted' else 'incomplete')
    return record


def admit(ufo, *, spec=None, native=None, mg5=None, process=None, workdir=None, mg5_runner=None, timeout=900):
    """Run every admission check with available evidence; return the admission record."""
    if mg5 is not None:
        _process_line(process)
        if workdir is None:
            raise ValueError('a fresh MadGraph work directory is required')
    rows = _static_rows(ufo, spec)
    rows += [hypercharge_check(spec), hermiticity_check(native)]
    static_failed = any(r['status'] == 'fail' for r in rows)
    for kind in MG5_CHECKS:
        if mg5 is None:
            rows.append(_row(f'mg5-check-{kind}', 'not_evaluated', reason='no MadGraph executable was given'))
        elif static_failed:
            rows.append(_row(f'mg5-check-{kind}', 'not_evaluated', reason='static admission already refused the UFO'))
        else:
            rows.append(mg5_check(ufo, kind, process, mg5=mg5, workdir=Path(workdir) / kind, runner=mg5_runner,
                                  timeout=timeout))
    rows.append(_row('ward-identity', 'not_evaluated', reason='not part of minimal admission'))
    return _record(ufo, rows, REQUIRED, process=process)


def add_arguments(parser):
    parser.add_argument('--ufo', required=True, type=Path)
    parser.add_argument('--spec', type=Path, help='ModelSpec JSON: spec agreement and the hypercharge census')
    parser.add_argument('--native-checks', type=Path,
                        help='FeynRules receipt with two-gauge checks or physical checks (CheckHermiticity)')
    parser.add_argument('--mg5', help='MadGraph executable for check gauge, lorentz and permutation')
    parser.add_argument('--process', help='the requested process, one MadGraph process line')
    parser.add_argument('--workdir', type=Path, help='fresh directory for the MadGraph sessions')
    parser.add_argument('--out', type=Path, help='write the admission record here (a new file)')


def command(args):
    spec = json.loads(args.spec.read_text()) if args.spec else None
    native = json.loads(args.native_checks.read_text()) if args.native_checks else None
    if args.mg5 and not args.process:
        raise SystemExit('--mg5 needs --process')
    record = admit(args.ufo, spec=spec, native=native, mg5=args.mg5, process=args.process,
                   workdir=args.workdir or (args.mg5 and Path(args.ufo).absolute().parent / 'admission-mg5'))
    text = json.dumps(record, indent=2, default=str) + '\n'
    if args.out:
        with Path(args.out).open('x') as handle:
            handle.write(text)
        print(json.dumps({k: record[k] for k in ('decision', 'refusals', 'not_evaluated')}, indent=2))
    else:
        print(text, end='')
    return 0 if record['decision'] == 'admitted' else 1
